package com.nebula.assistant;

import android.app.Activity;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.webkit.WebView;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashSet;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Supplier;

/** Native, capability-driven controls. Network work runs only while useful to the visible screen. */
final class UniversalDashboard extends LinearLayout {
    private static final int INK = Color.rgb(234, 242, 255);
    private static final int MUTED = Color.rgb(155, 173, 195);
    private static final int BLUE = Color.rgb(43, 145, 250);
    private final Activity activity;
    private final String token;
    private final Supplier<LinkedHashSet<String>> hubAddresses;
    private final Supplier<LinkedHashSet<String>> pcAddresses;
    private final Runnable openPanel;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newFixedThreadPool(2, task -> {
        Thread thread = new Thread(task, "NebulaControls");
        thread.setDaemon(true);
        return thread;
    });
    private final FrameLayout screen;
    private final View[] pages = new View[4];
    private final Button[] tabs = new Button[4];
    final Button powerButton;
    final Button panelButton;
    final TextView status;
    private TextView deviceStatus;
    private TextView bpmStatus;
    private TextView overlayStatus;
    private LinearLayout deviceList;
    private Button refreshDevices;
    private Button discoverDevices;
    private Button startOverlay;
    private Button stopOverlay;
    private TextView panelStatus;
    private Button connectPanel;
    private FrameLayout panelFrame;
    private WebView webView;
    private int selectedTab;
    private boolean resumed;
    private volatile boolean destroyed;
    private boolean loadingDevices;
    private boolean loadingBpm;
    private boolean loadingOverlay;
    private boolean sendingAction;
    private boolean sendingOverlay;
    private String hubEndpoint;
    private String overlayEndpoint;
    private long devicesUpdated;
    private long toolsUpdated;
    private JSONArray devices = new JSONArray();
    private final Runnable toolRefresh = new Runnable() {
        @Override public void run() {
            if (destroyed || !resumed || selectedTab != 2) return;
            loadTools();
            ui.postDelayed(this, 15_000L);
        }
    };

    UniversalDashboard(Activity activity, String token,
                       Supplier<LinkedHashSet<String>> hubs,
                       Supplier<LinkedHashSet<String>> pcs, Runnable wake, Runnable openPanel) {
        super(activity);
        this.activity = activity;
        this.token = token;
        this.hubAddresses = hubs;
        this.pcAddresses = pcs;
        this.openPanel = openPanel;
        setOrientation(VERTICAL);
        setBackgroundColor(Color.rgb(6, 12, 22));
        setFitsSystemWindows(true);
        screen = new FrameLayout(activity);
        addView(screen, new LayoutParams(-1, 0, 1));

        LinearLayout home = page("NEBULA", "Sua casa, na palma da mão.");
        LinearLayout pc = card(home, "Computador", "Acorde a Nebula pelo Wi-Fi ou pelo hub do notebook.");
        powerButton = button("Ligar Nebula", true, wake);
        pc.addView(powerButton, fullButton());
        panelButton = button("Abrir painel completo", false, openPanel);
        pc.addView(panelButton, fullButton());
        status = label("Pronto para conectar. Confirme o PIN do celular ao ligar o PC.", 13, MUTED);
        addSpaced(pc, status, 10);
        LinearLayout shortcuts = card(home, "Controle rápido", "Acesse seus aparelhos e ferramentas em um toque.");
        shortcuts.addView(button("Dispositivos conectados  →", false, () -> selectTab(1)), fullButton());
        shortcuts.addView(button("Wi-Fi BPM e Rocket League  →", false, () -> selectTab(2)), fullButton());
        addSpaced(home, label("Conecte-se à rede de casa ou ao Tailscale para acessar a Nebula.", 13, MUTED), 20);
        pages[0] = scroll(home);

        LinearLayout devicePage = page("DISPOSITIVOS", "Um lugar para seus controles.");
        addSpaced(devicePage, label("Aparelhos compatíveis e cadastrados no hub. Integrações adicionais podem ser configuradas no painel.", 14, MUTED), 10);
        LinearLayout deviceActions = new LinearLayout(activity);
        refreshDevices = button("Atualizar", false, () -> loadDevices(false));
        discoverDevices = button("Buscar TVs", true, () -> loadDevices(true));
        addPair(deviceActions, refreshDevices, discoverDevices);
        addSpaced(devicePage, deviceActions, 14);
        deviceStatus = label("Abra esta aba para consultar o hub.", 13, MUTED);
        addSpaced(devicePage, deviceStatus, 12);
        deviceList = new LinearLayout(activity);
        deviceList.setOrientation(VERTICAL);
        addSpaced(devicePage, deviceList, 8);
        pages[1] = scroll(devicePage);

        LinearLayout toolPage = page("FERRAMENTAS", "Conectadas ao seu computador.");
        LinearLayout bpm = card(toolPage, "Wi-Fi BPM · experimental", "Sinais de Wi-Fi com hardware CSI compatível.");
        bpmStatus = label("Sem leitura. Conecte um coletor CSI compatível ao computador.", 16, INK);
        addSpaced(bpm, bpmStatus, 12);
        addSpaced(bpm, label("Wi-Fi comum do celular não fornece os dados necessários. Esta ferramenta não é um monitor médico.", 13, MUTED), 12);
        bpm.addView(button("Consultar sensor", false, this::loadBpm), fullButton());
        LinearLayout rocket = card(toolPage, "ROCKET LEAGUE", "Overlay no PC com visual azul e laranja inspirado na arena.");
        overlayStatus = label("Consultando o computador…", 15, INK);
        addSpaced(rocket, overlayStatus, 12);
        LinearLayout rocketActions = new LinearLayout(activity);
        startOverlay = button("Mostrar overlay", true, () -> sendOverlay("start"));
        stopOverlay = button("Ocultar", false, () -> sendOverlay("stop"));
        startOverlay.setEnabled(false);
        stopOverlay.setEnabled(false);
        addPair(rocketActions, startOverlay, stopOverlay);
        addSpaced(rocket, rocketActions, 12);
        addSpaced(rocket, label("Exibida no computador. Use o jogo em modo janela sem bordas para visualizar sobre a partida.", 13, MUTED), 12);
        toolPage.addView(button("Atualizar ferramentas", false, this::loadTools), fullButton());
        pages[2] = scroll(toolPage);

        panelFrame = new FrameLayout(activity);
        LinearLayout panelPage = page("PAINEL", "Todos os controles da Nebula.");
        panelStatus = label("Conecte ao PC ou notebook para abrir o painel completo.", 15, MUTED);
        addSpaced(panelPage, panelStatus, 14);
        connectPanel = button("Conectar ao painel", true, openPanel);
        panelPage.addView(connectPanel, fullButton());
        panelFrame.addView(scroll(panelPage), new FrameLayout.LayoutParams(-1, -1));
        pages[3] = panelFrame;

        LinearLayout navigation = new LinearLayout(activity);
        navigation.setPadding(dp(8), dp(6), dp(8), dp(6));
        navigation.setBackgroundColor(Color.rgb(11, 22, 37));
        String[] names = {"Casa", "Dispositivos", "Ferramentas", "Painel"};
        for (int i = 0; i < tabs.length; i++) {
            final int tab = i;
            tabs[i] = button(names[i], false, () -> selectTab(tab));
            tabs[i].setTextSize(11);
            tabs[i].setPadding(dp(2), 0, dp(2), 0);
            tabs[i].setMinWidth(0);
            tabs[i].setMinimumWidth(0);
            navigation.addView(tabs[i], new LayoutParams(0, dp(52), 1));
        }
        addView(navigation, new LayoutParams(-1, -2));
        selectTab(0);
    }

    void selectTab(int tab) {
        selectedTab = tab;
        screen.removeAllViews();
        screen.addView(pages[tab], new FrameLayout.LayoutParams(-1, -1));
        for (int i = 0; i < tabs.length; i++) {
            tabs[i].setTextColor(i == tab ? Color.WHITE : MUTED);
            tabs[i].setBackgroundTintList(ColorStateList.valueOf(i == tab ? Color.rgb(24, 66, 107) : Color.TRANSPARENT));
            tabs[i].setSelected(i == tab);
        }
        ui.removeCallbacks(toolRefresh);
        if (webView != null) {
            if (resumed && tab == 3) { webView.onResume(); webView.resumeTimers(); }
            else { webView.onPause(); webView.pauseTimers(); }
        }
        if (resumed && tab == 1 && SystemClock.elapsedRealtime() - devicesUpdated > 30_000L) loadDevices(false);
        if (resumed && tab == 2) ui.post(toolRefresh);
    }

    void showPanel(WebView view) {
        if (destroyed) { view.destroy(); return; }
        if (webView != null && webView != view) webView.destroy();
        webView = view;
        panelFrame.removeAllViews();
        panelFrame.addView(view, new FrameLayout.LayoutParams(-1, -1));
        selectTab(3);
    }

    void panelConnecting(boolean connecting, String message) {
        connectPanel.setEnabled(!connecting);
        connectPanel.setText(connecting ? "Conectando…" : "Conectar ao painel");
        panelStatus.setText(message);
    }

    boolean goBack() {
        if (selectedTab == 3 && webView != null && webView.canGoBack()) webView.goBack();
        else if (selectedTab != 0) selectTab(0);
        else return false;
        return true;
    }

    void resume() {
        resumed = true;
        selectTab(selectedTab);
    }

    void pause() {
        resumed = false;
        ui.removeCallbacks(toolRefresh);
        if (webView != null) { webView.onPause(); webView.pauseTimers(); }
    }

    void destroy() {
        destroyed = true;
        pause();
        network.shutdownNow();
        ui.removeCallbacksAndMessages(null);
        if (webView != null) { webView.destroy(); webView = null; }
    }

    private void loadDevices(boolean discover) {
        if (destroyed || loadingDevices || sendingAction) return;
        loadingDevices = true;
        refreshDevices.setEnabled(false);
        discoverDevices.setEnabled(false);
        deviceStatus.setText(discover ? "Buscando TVs na rede…" : "Consultando dispositivos…");
        network.execute(() -> {
            try {
                Response response = firstAvailable(hubAddresses.get(), "/universal/devices");
                JSONObject data = discover ? request(response.endpoint, "/universal/discover", new JSONObject()) : response.data;
                ui.post(() -> {
                    if (destroyed) return;
                    hubEndpoint = response.endpoint;
                    devices = data.optJSONArray("devices");
                    if (devices == null) devices = new JSONArray();
                    devicesUpdated = SystemClock.elapsedRealtime();
                    deviceStatus.setText(devices.length() + " dispositivo(s) · atualizado agora");
                    finishDeviceLoad();
                    renderDevices();
                });
            } catch (Exception error) {
                ui.post(() -> {
                    if (destroyed) return;
                    hubEndpoint = null;
                    deviceStatus.setText("Hub indisponível. Confira o notebook e a conexão. " + errorText(error));
                    finishDeviceLoad();
                    renderDevices();
                });
            }
        });
    }

    private void finishDeviceLoad() {
        loadingDevices = false;
        refreshDevices.setEnabled(true);
        discoverDevices.setEnabled(true);
    }

    private void renderDevices() {
        deviceList.removeAllViews();
        if (devices.length() == 0) {
            LinearLayout empty = card(deviceList, "Seu controle começa aqui", "Ligue o hub no notebook e cadastre seus aparelhos compatíveis. Use Buscar TVs para procurar televisores na rede.");
            empty.addView(button("Abrir painel", false, openPanel), fullButton());
            return;
        }
        for (int i = 0; i < devices.length(); i++) {
            JSONObject device = devices.optJSONObject(i);
            if (device == null) continue;
            String id = device.optString("id");
            boolean available = device.optBoolean("available", false) && hubEndpoint != null;
            LinearLayout deviceCard = card(deviceList, device.optString("name", id),
                    kindLabel(device.optString("kind")) + " · " + (available ? "Disponível" : "Indisponível"));
            JSONArray actions = device.optJSONArray("actions");
            if (actions == null || actions.length() == 0) {
                addSpaced(deviceCard, label("Nenhum controle disponível para este aparelho.", 13, MUTED), 6);
                continue;
            }
            LinearLayout row = null;
            for (int a = 0; a < actions.length(); a++) {
                JSONObject action = actions.optJSONObject(a);
                if (action == null) continue;
                if (a % 2 == 0) {
                    row = new LinearLayout(activity);
                    addSpaced(deviceCard, row, 6);
                }
                String actionId = action.optString("id");
                Button control = button(action.optString("label", actionId), false,
                        () -> sendDeviceAction(id, actionId));
                control.setEnabled(available && !sendingAction && !loadingDevices);
                LayoutParams size = new LayoutParams(0, -2, 1);
                size.setMargins(0, 0, dp(4), 0);
                row.addView(control, size);
            }
        }
    }

    private void sendDeviceAction(String deviceId, String action) {
        if (destroyed || sendingAction || loadingDevices || hubEndpoint == null) return;
        sendingAction = true;
        String endpoint = hubEndpoint;
        refreshDevices.setEnabled(false);
        discoverDevices.setEnabled(false);
        deviceStatus.setText("Enviando comando…");
        renderDevices();
        network.execute(() -> {
            String message;
            try {
                JSONObject payload = new JSONObject().put("device_id", deviceId).put("action", action);
                JSONObject result = request(endpoint, "/universal/action", payload);
                message = result.optString("message", "Comando enviado.");
            } catch (Exception error) {
                message = "Não foi possível confirmar o comando: " + errorText(error);
            }
            final String resultMessage = message;
            ui.post(() -> {
                if (destroyed) return;
                sendingAction = false;
                refreshDevices.setEnabled(true);
                discoverDevices.setEnabled(true);
                deviceStatus.setText(resultMessage);
                renderDevices();
            });
        });
    }

    private void loadTools() {
        if (destroyed) return;
        loadBpm();
        loadOverlay();
    }

    private void loadBpm() {
        if (destroyed || loadingBpm) return;
        loadingBpm = true;
        network.execute(() -> {
            String message;
            try {
                JSONObject data = firstAvailable(pcAddresses.get(), "/api/wifi-bpm/status").data;
                double bpm = data.optDouble("bpm", Double.NaN);
                String detail = data.optString("message", "Aguardando amostras CSI do sensor.");
                message = !Double.isNaN(bpm) && bpm > 0
                        ? Math.round(bpm) + " BPM · estimativa experimental\n" + detail
                        : "Sem leitura de BPM\n" + detail;
            } catch (Exception error) {
                message = "PC indisponível. Abra a Nebula para consultar o sensor.\n" + errorText(error);
            }
            final String result = message;
            ui.post(() -> {
                if (destroyed) return;
                loadingBpm = false;
                toolsUpdated = SystemClock.elapsedRealtime();
                bpmStatus.setText(result);
            });
        });
    }

    private void loadOverlay() {
        if (destroyed || loadingOverlay || sendingOverlay) return;
        loadingOverlay = true;
        network.execute(() -> {
            try {
                Response response = firstAvailable(pcAddresses.get(), "/api/rocket-overlay/status");
                ui.post(() -> {
                    if (destroyed) return;
                    loadingOverlay = false;
                    overlayEndpoint = response.endpoint;
                    renderOverlay(response.data);
                });
            } catch (Exception error) {
                ui.post(() -> {
                    if (destroyed) return;
                    loadingOverlay = false;
                    overlayEndpoint = null;
                    startOverlay.setEnabled(false);
                    stopOverlay.setEnabled(false);
                    overlayStatus.setText("PC indisponível. " + errorText(error));
                });
            }
        });
    }

    private void renderOverlay(JSONObject data) {
        boolean running = data.optBoolean("running", false);
        overlayStatus.setText((running ? "Overlay visível no PC" : "Overlay oculta")
                + (data.optString("message").isEmpty() ? "" : "\n" + data.optString("message")));
        startOverlay.setEnabled(!running && !sendingOverlay);
        stopOverlay.setEnabled(running && !sendingOverlay);
    }

    private void sendOverlay(String action) {
        if (destroyed || sendingOverlay || overlayEndpoint == null || loadingOverlay) return;
        sendingOverlay = true;
        String endpoint = overlayEndpoint;
        startOverlay.setEnabled(false);
        stopOverlay.setEnabled(false);
        overlayStatus.setText("Atualizando overlay…");
        network.execute(() -> {
            String message;
            try {
                JSONObject response = request(endpoint, "/api/rocket-overlay/action", new JSONObject().put("action", action));
                message = response.optString("message", "Comando enviado ao PC.");
            } catch (Exception error) {
                message = "Não foi possível confirmar: " + errorText(error);
            }
            final String result = message;
            ui.post(() -> {
                if (destroyed) return;
                sendingOverlay = false;
                overlayStatus.setText(result);
                loadOverlay();
            });
        });
    }

    private Response firstAvailable(LinkedHashSet<String> endpoints, String path) throws Exception {
        Exception last = new IOException("Nenhum endereço configurado.");
        for (String endpoint : endpoints) {
            if (destroyed || Thread.currentThread().isInterrupted()) throw new IOException("Consulta cancelada.");
            try { return new Response(endpoint, request(endpoint, path, null)); }
            catch (Exception error) { last = error; }
        }
        throw last;
    }

    private JSONObject request(String endpoint, String path, JSONObject body) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint + path).openConnection();
        try {
            connection.setConnectTimeout(1500);
            connection.setReadTimeout(body == null ? 4000 : 20_000);
            connection.setInstanceFollowRedirects(false);
            connection.setUseCaches(false);
            connection.setRequestProperty("X-Nebula-Power-Token", token);
            connection.setRequestProperty("Accept", "application/json");
            if (body != null) {
                connection.setRequestMethod("POST");
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                connection.setDoOutput(true);
                try (java.io.OutputStream stream = connection.getOutputStream()) {
                    stream.write(body.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            int code = connection.getResponseCode();
            InputStream input = code >= 400 ? connection.getErrorStream() : connection.getInputStream();
            StringBuilder text = new StringBuilder();
            if (input != null) try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
                char[] chunk = new char[2048];
                int count;
                while ((count = reader.read(chunk)) != -1) {
                    text.append(chunk, 0, count);
                    if (text.length() > 1_000_000) throw new IOException("Resposta maior que o limite.");
                }
            }
            if (code == 404) throw new IOException("Atualize a Nebula e o hub para habilitar este recurso.");
            JSONObject result;
            try { result = new JSONObject(text.toString()); }
            catch (Exception invalid) { throw new IOException("Resposta inválida do servidor (" + code + ")."); }
            if (code < 200 || code >= 300 || result.has("ok") && !result.optBoolean("ok")) {
                throw new IOException(result.optString("error", result.optString("message", "Falha HTTP " + code)));
            }
            return result;
        } finally { connection.disconnect(); }
    }

    private static String errorText(Exception error) {
        if (error instanceof java.net.SocketTimeoutException) return "Tempo de conexão esgotado.";
        if (error instanceof java.net.ConnectException) return "Servidor não respondeu.";
        String message = error.getMessage();
        return message == null ? "Falha de conexão." : message;
    }

    private static String kindLabel(String kind) {
        switch (kind) {
            case "tv": case "media_player": return "Mídia";
            case "pc": case "computer": return "Computador";
            case "light": case "lamp": return "Iluminação";
            case "climate": case "air": return "Climatização";
            case "switch": return "Tomada / interruptor";
            case "fan": return "Ventilador";
            case "scene": return "Cena";
            default: return "Dispositivo";
        }
    }

    private LinearLayout page(String title, String subtitle) {
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(VERTICAL);
        content.setPadding(dp(20), dp(28), dp(20), dp(24));
        TextView heading = label(title, 25, INK);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        heading.setLetterSpacing(.06f);
        content.addView(heading);
        addSpaced(content, label(subtitle, 15, MUTED), 8);
        return content;
    }

    private View scroll(LinearLayout content) {
        ScrollView scroll = new ScrollView(activity);
        scroll.setFillViewport(true);
        scroll.setClipToPadding(false);
        scroll.addView(content);
        return scroll;
    }

    private LinearLayout card(LinearLayout parent, String title, String subtitle) {
        LinearLayout card = new LinearLayout(activity);
        card.setOrientation(VERTICAL);
        card.setPadding(dp(17), dp(18), dp(17), dp(16));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(13, 26, 43));
        background.setCornerRadius(dp(10));
        background.setStroke(dp(1), Color.rgb(29, 48, 71));
        card.setBackground(background);
        TextView heading = label(title, 18, INK);
        heading.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        card.addView(heading);
        addSpaced(card, label(subtitle, 13, MUTED), 7);
        addSpaced(parent, card, 18);
        return card;
    }

    private TextView label(String value, int size, int color) {
        TextView label = new TextView(activity);
        label.setText(value);
        label.setTextSize(size);
        label.setTextColor(color);
        label.setLineSpacing(dp(3), 1);
        return label;
    }

    private Button button(String title, boolean primary, Runnable action) {
        Button button = new Button(activity);
        button.setText(title);
        button.setTextSize(14);
        button.setAllCaps(false);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setTextColor(primary ? Color.WHITE : Color.rgb(176, 214, 255));
        button.setMinHeight(dp(50));
        button.setGravity(Gravity.CENTER);
        button.setPadding(dp(10), dp(8), dp(10), dp(8));
        button.setStateListAnimator(null);
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(Color.WHITE);
        shape.setCornerRadius(dp(12));
        button.setBackground(shape);
        button.setBackgroundTintList(new ColorStateList(
                new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
                new int[]{Color.rgb(28, 37, 49), primary ? BLUE : Color.rgb(23, 48, 76)}));
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private void addPair(LinearLayout row, View first, View second) {
        LayoutParams left = new LayoutParams(0, -2, 1);
        left.setMargins(0, 0, dp(8), 0);
        row.addView(first, left);
        row.addView(second, new LayoutParams(0, -2, 1));
    }

    private LayoutParams fullButton() {
        LayoutParams params = new LayoutParams(-1, -2);
        params.setMargins(0, dp(12), 0, 0);
        return params;
    }

    private void addSpaced(LinearLayout parent, View view, int top) {
        LayoutParams params = new LayoutParams(-1, -2);
        params.setMargins(0, dp(top), 0, 0);
        parent.addView(view, params);
    }

    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private static final class Response {
        final String endpoint;
        final JSONObject data;
        Response(String endpoint, JSONObject data) { this.endpoint = endpoint; this.data = data; }
    }
}
