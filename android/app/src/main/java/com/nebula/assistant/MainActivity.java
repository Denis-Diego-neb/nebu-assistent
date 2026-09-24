package com.nebula.assistant;

import android.app.Activity;
import android.app.KeyguardManager;
import android.hardware.biometrics.BiometricPrompt;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceResponse;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.URL;
import java.util.LinkedHashSet;
import java.util.concurrent.Executor;

/** Tela única para acordar o computador e iniciar a Nebula. */
public class MainActivity extends Activity {
    private static final int REQUEST_DEVICE_CREDENTIAL = 4107;
    private static final String POWER_TOKEN = BuildConfig.NEBULA_POWER_TOKEN;
    private static final String PC_MAC = "00:E0:23:7C:7B:4D";
    private static final String PC_LAN_IP = "192.168.15.12";
    private static final String NOTEBOOK_LAN_SERVER = "http://192.168.15.4:8766";
    private static final String NOTEBOOK_WIFI_SERVER = "http://192.168.15.86:8766";
    private static final String NOTEBOOK_TAILSCALE_SERVER = "http://100.78.67.81:8766";
    private static final String OLD_NOTEBOOK_SERVER = "http://192.168.15.10:8766";
    private static final String PC_LAN_PANEL = "http://192.168.15.12:8765";
    private static final String NOTEBOOK_LAN_PANEL = "http://192.168.15.4:8765";
    private static final String PC_TAILSCALE_PANEL = "http://100.92.82.41:8765";
    private static final String NOTEBOOK_TAILSCALE_PANEL = "http://100.78.67.81:8765";
    private static final int WAKE_PORT = 9;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private Button powerButton;
    private Button panelButton;
    private TextView status;
    private boolean waking;
    private boolean panelOpening;
    private boolean sessionUnlocked;
    private WebView panelWebView;
    private String panelBaseUrl;
    private boolean panelFullscreen;
    private boolean panelFallbackTried;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("nebula", MODE_PRIVATE);
        migrateNotebookAddress();
        // Entrada ADB para o mostrador somente de leitura. Não libera o painel
        // de controle nem confirma credenciais do Android/Windows.
        if ("com.nebula.assistant.SHOW_GAUGE".equals(getIntent().getAction())) {
            if (android.os.Build.VERSION.SDK_INT >= 27) setShowWhenLocked(true);
            else getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED);
            Intent gauge = new Intent(this, TurboGaugeActivity.class);
            gauge.putExtra("endpoints", new String[]{"http://127.0.0.1:8765", PC_LAN_PANEL, PC_TAILSCALE_PANEL});
            gauge.putExtra("token", POWER_TOKEN);
            gauge.putExtra("panel_mode", getPreferences(MODE_PRIVATE).getString("instrument_panel", "auto"));
            gauge.putExtra("turbo_style", prefs.getString("boost_style", "cyber"));
            startActivity(gauge);
            finish();
            return;
        }
        getWindow().setStatusBarColor(Color.rgb(48, 48, 52));
        getWindow().setNavigationBarColor(Color.rgb(41, 42, 45));
        buildUi();
        try { PhoneUnlock.prepare(this); }
        catch (Exception error) { status.setText("Configure o PIN do Android para preparar o desbloqueio do PC."); }
    }

    private MobileDashboard dashboard;

    private void buildUi() {
        if (dashboard != null) dashboard.close();
        panelOpening = false;
        panelWebView = null;
        panelBaseUrl = null;
        if (!sessionUnlocked) {
            dashboard = null;
            LinearLayout gate = new LinearLayout(this);
            gate.setOrientation(LinearLayout.VERTICAL);
            gate.setPadding(dp(24), dp(24), dp(24), dp(24));
            gate.setBackground(background());
            TextView brand = text("NEBULA", 22, Color.rgb(247, 241, 232), Typeface.BOLD);
            brand.setGravity(Gravity.START); brand.setLetterSpacing(.12f); gate.addView(brand);
            TextView signature = text("SUA CASA. UM CONTROLE.", 10, Color.rgb(234, 211, 174), Typeface.BOLD);
            signature.setGravity(Gravity.START); signature.setLetterSpacing(.08f); gate.addView(signature);
            gate.addView(new android.widget.Space(this), new LinearLayout.LayoutParams(1, 0, .55f));

            LinearLayout access = new LinearLayout(this); access.setOrientation(LinearLayout.VERTICAL);
            access.setGravity(Gravity.CENTER_HORIZONTAL); access.setPadding(dp(22), dp(22), dp(22), dp(22));
            GradientDrawable accessShape = new GradientDrawable(); accessShape.setColor(Color.rgb(58, 59, 63));
            accessShape.setCornerRadius(dp(10)); accessShape.setStroke(dp(1), Color.rgb(78, 78, 82));
            access.setBackground(accessShape); access.setElevation(dp(10));
            access.addView(new PulseView(this), new LinearLayout.LayoutParams(-1, dp(112)));
            access.addView(text("Tudo à mão", 28, Color.rgb(247, 241, 232), Typeface.BOLD));
            status = text("Confirme o PIN do celular para entrar e autorizar o Windows do PC.", 15,
                    Color.rgb(190, 181, 168), Typeface.NORMAL);
            status.setPadding(dp(4), dp(8), dp(4), dp(22)); access.addView(status);
            powerButton = new Button(this);
            powerButton.setText("Entrar e ligar o PC");
            powerButton.setTextColor(Color.rgb(43, 40, 35));
            powerButton.setTextSize(15); powerButton.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
            powerButton.setBackgroundTintList(android.content.res.ColorStateList.valueOf(Color.rgb(234, 211, 174)));
            powerButton.setStateListAnimator(null);
            powerButton.setAllCaps(false);
            powerButton.setOnClickListener(view -> requirePhoneCredential());
            GradientDrawable powerShape = new GradientDrawable(); powerShape.setColor(Color.rgb(234, 211, 174));
            powerShape.setCornerRadius(dp(10)); powerButton.setBackground(powerShape);
            access.addView(powerButton, new LinearLayout.LayoutParams(-1, dp(50)));
            gate.addView(access, new LinearLayout.LayoutParams(-1, -2));
            TextView privacy = text("Seu PIN permanece protegido pelo Android.", 11,
                Color.rgb(150, 143, 134), Typeface.NORMAL); privacy.setPadding(0, dp(14), 0, 0); gate.addView(privacy);
            gate.addView(new android.widget.Space(this), new LinearLayout.LayoutParams(1, 0, 1f));
            panelButton = new Button(this); // Painel só fica disponível após o PIN.
            setContentView(gate);
            return;
        }
        dashboard = new MobileDashboard(this, POWER_TOKEN,
                notebookEndpoints().toArray(new String[0]),
                new String[]{PC_LAN_PANEL, PC_TAILSCALE_PANEL},
            this::requirePhoneCredential, this::openPanelWhenReady);
        powerButton = dashboard.powerButton;
        panelButton = dashboard.espacoButton;
        status = dashboard.status;
        setContentView(dashboard.root);
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (dashboard != null) dashboard.setActive(false);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (dashboard != null) dashboard.setActive(true);
    }

    @Override
    protected void onDestroy() {
        if (dashboard != null) dashboard.close();
        if (panelWebView != null) panelWebView.destroy();
        ui.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private void requirePhoneCredential() {
        if (waking) return;
        try {
            PhoneUnlock.prepare(this);
        } catch (Exception error) {
            setButtonState("TENTAR NOVAMENTE", "Não foi possível preparar a chave: " + errorMessage(error), true);
            return;
        }
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            BiometricPrompt prompt = new BiometricPrompt.Builder(this)
                    .setTitle("Autorizar a inicialização")
                    .setSubtitle("Use sua digital ou o PIN do celular para ligar a Nebula.")
                    .setDescription("A autorização libera o comando de inicialização do PC.")
                    .setAllowedAuthenticators(
                            android.hardware.biometrics.BiometricManager.Authenticators.BIOMETRIC_STRONG
                                    | android.hardware.biometrics.BiometricManager.Authenticators.DEVICE_CREDENTIAL
                    )
                    .build();
            Executor executor = getMainExecutor();
            prompt.authenticate(new CancellationSignal(), executor, new BiometricPrompt.AuthenticationCallback() {
                @Override public void onAuthenticationSucceeded(BiometricPrompt.AuthenticationResult result) {
                    wakeNebula();
                }

                @Override public void onAuthenticationError(int errorCode, CharSequence errorString) {
                    setButtonState("TENTAR NOVAMENTE", errorString.toString(), true);
                }
            });
            return;
        }
        KeyguardManager keyguard = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (keyguard == null || !keyguard.isDeviceSecure()) {
            setButtonState(
                    "CONFIGURE UM PIN",
                    "Cadastre um PIN de bloqueio no celular antes de ligar o PC.",
                    true
            );
            return;
        }
        Intent confirmation = keyguard.createConfirmDeviceCredentialIntent(
                "Autorizar a inicialização",
                "Confirme o PIN do celular para ligar a Nebula."
        );
        if (confirmation == null) {
            setButtonState(
                    "TENTAR NOVAMENTE",
                    "O Android não conseguiu abrir a confirmação do PIN.",
                    true
            );
            return;
        }
        startActivityForResult(confirmation, REQUEST_DEVICE_CREDENTIAL);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_DEVICE_CREDENTIAL) return;
        if (resultCode == RESULT_OK) {
            wakeNebula();
        } else {
            setButtonState("LIGAR PC", "Autorização cancelada. O PC não foi ligado.", true);
        }
    }

    private void wakeNebula() {
        if (waking) return;
        final JSONObject unlockProof;
        try {
            unlockProof = PhoneUnlock.sign();
        } catch (Exception error) {
            setButtonState("CONFIRMAR PIN", "Confirme novamente o PIN para autorizar o Windows.", true);
            return;
        }
        if (!sessionUnlocked) {
            sessionUnlocked = true;
            buildUi();
        }
        waking = true;
        setButtonState("LIGANDO…", "Enviando o sinal direto pelo Wi-Fi…", false);

        new Thread(() -> {
            String directError = "celular fora do Wi-Fi de casa";
            boolean directSent = false;
            try {
                String broadcast = sendDirectWake();
                directSent = broadcast != null;
            } catch (Exception error) {
                directError = errorMessage(error);
            }

            String relayError = "hub indisponível";
            boolean hubNotified = false;
            for (String endpoint : notebookEndpoints()) {
                try {
                    sendRelayWake(endpoint, unlockProof);
                    prefs.edit().putString("notebook_server", endpoint).apply();
                    hubNotified = true;
                    break;
                } catch (Exception error) {
                    relayError = errorMessage(error);
                }
            }

            if (directSent || hubNotified) {
                final boolean fallbackReady = hubNotified;
                ui.post(() -> wakeSucceeded(fallbackReady
                        ? "PIN confirmado. Se o PC não responder, a Nebula abrirá no notebook."
                        : "PIN confirmado. Sinal enviado direto ao PC; o hub do notebook está offline."
                ));
                return;
            }

            String detail = "Wi-Fi direto: " + directError + ". Hub: " + relayError + ".";
            ui.post(() -> {
                waking = false;
                setButtonState("TENTAR NOVAMENTE", detail, true);
            });
        }, "NebulaWake").start();
    }

    private void wakeSucceeded(String message) {
        setButtonState("NEBULA AUTORIZADA", message, false);
        // Depois que o PIN autorizou o aparelho e o Hub respondeu, entre no
        // Espaço automaticamente. É ali que ficam o tema de nebulosa e o chat
        // Dupla; voltar pelo Android ainda retorna ao painel nativo.
        openPanelWhenReady();
    }

    private void openPanelWhenReady() {
        if (panelOpening) return;
        panelOpening = true;
        panelButton.setEnabled(false);
        panelButton.setText("CONECTANDO…");
        status.setText("Procurando o Espaço da Nebula no PC e no notebook…");

        new Thread(() -> {
            long deadline = System.currentTimeMillis() + 100_000L;
            String lastError = "servidor ainda não respondeu";
            int round = 0;
            while (!isDestroyed() && System.currentTimeMillis() < deadline) {
                round += 1;
                // Em casa a LAN responde na primeira volta e a abertura continua
                // instantânea. Longe, pelo Tailscale, a primeira conexão ainda
                // precisa furar o NAT ou cair no relé, e esse aperto de mão leva
                // segundos: com 1,2 s fixo toda tentativa morria antes de o
                // caminho existir, então ele nunca se estabelecia por mais que o
                // laço repetisse. Daí crescer a cada volta em vez de insistir
                // sempre com o mesmo limite curto.
                int connectMs = Math.min(1500 * round, 9000);
                int readMs = Math.min(2500 * round, 15000);
                for (String endpoint : panelEndpoints()) {
                    try {
                        String token = requestPanelSession(endpoint, connectMs, readMs);
                        ui.post(() -> showPanel(endpoint, token));
                        return;
                    } catch (Exception error) {
                        lastError = errorMessage(error);
                    }
                }
                try {
                    Thread.sleep(1500L);
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    lastError = "tentativa interrompida";
                    break;
                }
            }
            String finalError = lastError;
            ui.post(() -> {
                panelOpening = false;
                waking = false;
                panelButton.setEnabled(true);
                panelButton.setText("TENTAR ABRIR O ESPAÇO");
                setButtonState(
                        "LIGAR NOVAMENTE",
                        "O sinal foi enviado, mas o Espaço não respondeu: " + finalError,
                        true
                );
            });
        }, "NebulaPanel").start();
    }

    private LinkedHashSet<String> panelEndpoints() {
        LinkedHashSet<String> endpoints = new LinkedHashSet<>();
        endpoints.add(PC_LAN_PANEL);
        endpoints.add(NOTEBOOK_LAN_PANEL);
        endpoints.add(PC_TAILSCALE_PANEL);
        endpoints.add(NOTEBOOK_TAILSCALE_PANEL);
        return endpoints;
    }

    private String requestPanelSession(String endpoint, int connectMs, int readMs)
            throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(
                endpoint + "/api/device-session"
        ).openConnection();
        try {
            connection.setConnectTimeout(connectMs);
            connection.setReadTimeout(readMs);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("X-Nebula-Power-Token", POWER_TOKEN);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setDoOutput(true);
            connection.getOutputStream().write("{}".getBytes("UTF-8"));
            int code = connection.getResponseCode();
            if (code >= 400) throw new IOException("o painel respondeu " + code);
            StringBuilder body = new StringBuilder();
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(connection.getInputStream(), "UTF-8")
            )) {
                String line;
                while ((line = reader.readLine()) != null) body.append(line);
            }
            String token = new JSONObject(body.toString()).optString("token", "");
            if (token.isEmpty()) throw new IOException("sessão do painel não foi criada");
            return token;
        } finally {
            connection.disconnect();
        }
    }

    private void showPanel(String endpoint, String token) {
        if (isDestroyed() || isFinishing()) return;
        panelOpening = false;
        waking = false;
        panelBaseUrl = endpoint;

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setCookie(
                endpoint,
                "nebula_session=" + token + "; Path=/; HttpOnly; SameSite=Strict"
        );
        cookies.flush();

        WebView webView = new WebView(this);
        panelWebView = webView;
        // O Espaço abre em fundo preto: branco piscaria antes da nebulosa.
        webView.setBackgroundColor(Color.BLACK);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                Uri panelUri = Uri.parse(panelBaseUrl);
                if (uri.getHost() != null && uri.getHost().equalsIgnoreCase(panelUri.getHost())) {
                    return false;
                }
                startActivity(new Intent(Intent.ACTION_VIEW, uri));
                return true;
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse response) {
                // Um PC ainda na versão anterior não conhece /espaco/; nesse caso
                // o painel clássico continua atendendo no mesmo endereço.
                if (request.isForMainFrame() && !panelFallbackTried
                        && response.getStatusCode() == 404) {
                    panelFallbackTried = true;
                    view.loadUrl(panelBaseUrl + "/");
                }
            }
        });
        webView.addJavascriptInterface(new FullscreenBridge(), "NebulaHost");
        if (isDestroyed() || isFinishing()) { webView.destroy(); return; }
        if (dashboard != null) dashboard.setActive(false);
        panelFallbackTried = false;
        setContentView(webView);
        webView.loadUrl(endpoint + "/espaco/");
    }

    /** Ponte de tela cheia usada pelo botão e pelo F11 do front espacial. */
    private final class FullscreenBridge {
        @JavascriptInterface
        public void enterFullscreen() { ui.post(() -> setPanelFullscreen(true)); }

        @JavascriptInterface
        public void exitFullscreen() { ui.post(() -> setPanelFullscreen(false)); }
    }

    private void setPanelFullscreen(boolean on) {
        panelFullscreen = on;
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                controller.setSystemBarsBehavior(
                        WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                if (on) controller.hide(WindowInsets.Type.systemBars());
                else controller.show(WindowInsets.Type.systemBars());
            }
        } else if (on) {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        } else {
            getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_VISIBLE);
        }
        if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (panelWebView != null) {
            panelWebView.evaluateJavascript(
                    "window.NebulaFullscreen&&window.NebulaFullscreen.set(" + on + ")", null);
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        // Teclado físico ou Bluetooth: o F11 vale o mesmo que no EXE.
        if (keyCode == KeyEvent.KEYCODE_F11 && panelWebView != null) {
            setPanelFullscreen(!panelFullscreen);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_ESCAPE && panelFullscreen) {
            setPanelFullscreen(false);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void onBackPressed() {
        if (panelFullscreen) {
            setPanelFullscreen(false);
            return;
        }
        if (panelWebView != null) {
            if (panelWebView.canGoBack()) {
                panelWebView.goBack();
            } else {
                panelWebView.destroy();
                panelWebView = null;
                setPanelFullscreen(false);
                buildUi();
            }
            return;
        }
        super.onBackPressed();
    }

    private void setButtonState(String label, String message, boolean enabled) {
        powerButton.setText(label);
        powerButton.setEnabled(enabled);
        powerButton.setAlpha(enabled ? 1f : 0.72f);
        status.setText(message);
    }

    private LinkedHashSet<String> notebookEndpoints() {
        LinkedHashSet<String> endpoints = new LinkedHashSet<>();
        String configured = cleanEndpoint(prefs.getString("notebook_server", NOTEBOOK_LAN_SERVER));
        if (!configured.isEmpty()) endpoints.add(configured);
        endpoints.add(NOTEBOOK_LAN_SERVER);
        endpoints.add(NOTEBOOK_TAILSCALE_SERVER);
        endpoints.add(NOTEBOOK_WIFI_SERVER);
        return endpoints;
    }

    private void migrateNotebookAddress() {
        String saved = cleanEndpoint(prefs.getString("notebook_server", NOTEBOOK_LAN_SERVER));
        if (saved.isEmpty() || OLD_NOTEBOOK_SERVER.equals(saved) || NOTEBOOK_WIFI_SERVER.equals(saved)) {
            prefs.edit().putString("notebook_server", NOTEBOOK_LAN_SERVER).apply();
        }
    }

    /** Endereco do Tailscale, na faixa 100.64/10 que ele usa para o tailnet. */
    private static boolean viaTailscale(String endpoint) {
        return endpoint != null && endpoint.contains("//100.");
    }

    private void sendRelayWake(String endpoint, JSONObject unlockProof) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(endpoint + "/wake").openConnection();
        try {
            // Este caminho tenta cada endereco uma vez so, sem repetir. Pelo
            // Tailscale a primeira conexao ainda precisa furar o NAT ou cair no
            // rele antes de existir, e 2,5 s nao cobriam isso longe de casa; na
            // LAN o limite curto continua, para nao fazer esperar a toa quando o
            // endereco simplesmente nao atende.
            connection.setConnectTimeout(viaTailscale(endpoint) ? 9000 : 2500);
            connection.setReadTimeout(viaTailscale(endpoint) ? 15000 : 5000);
            connection.setRequestMethod("POST");
            connection.setRequestProperty("X-Nebula-Power-Token", POWER_TOKEN);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setDoOutput(true);
            connection.getOutputStream().write(new JSONObject().put("unlock_proof", unlockProof).toString().getBytes("UTF-8"));
            connection.getOutputStream().close();
            int code = connection.getResponseCode();
            if (code >= 400) throw new IOException("o hub respondeu " + code);
        } finally {
            connection.disconnect();
        }
    }

    private String sendDirectWake() throws Exception {
        ConnectivityManager manager = (ConnectivityManager) getSystemService(CONNECTIVITY_SERVICE);
        if (manager == null) return null;
        Inet4Address target = (Inet4Address) InetAddress.getByName(PC_LAN_IP);
        for (Network network : manager.getAllNetworks()) {
            NetworkCapabilities capabilities = manager.getNetworkCapabilities(network);
            if (capabilities == null
                    || !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    || capabilities.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue;
            LinkProperties properties = manager.getLinkProperties(network);
            if (properties == null) continue;
            for (LinkAddress link : properties.getLinkAddresses()) {
                if (!(link.getAddress() instanceof Inet4Address)) continue;
                Inet4Address phone = (Inet4Address) link.getAddress();
                int prefix = link.getPrefixLength();
                if (!sameSubnet(phone, target, prefix)) continue;
                InetAddress broadcast = broadcastAddress(phone, prefix);
                byte[] packet = magicPacket(PC_MAC);
                try (DatagramSocket socket = new DatagramSocket(
                        new InetSocketAddress(phone, 0))) {
                    socket.setBroadcast(true);
                    for (int i = 0; i < 4; i++) {
                        socket.send(new DatagramPacket(packet, packet.length, broadcast, WAKE_PORT));
                        socket.send(new DatagramPacket(packet, packet.length, target, WAKE_PORT));
                    }
                }
                return broadcast.getHostAddress();
            }
        }
        return null;
    }

    private static boolean sameSubnet(Inet4Address first, Inet4Address second, int prefix) {
        if (prefix < 0 || prefix > 32) return false;
        int mask = prefix == 0 ? 0 : (int) (0xffffffffL << (32 - prefix));
        return (ipv4(first) & mask) == (ipv4(second) & mask);
    }

    private static InetAddress broadcastAddress(Inet4Address address, int prefix) throws Exception {
        int mask = prefix == 0 ? 0 : (int) (0xffffffffL << (32 - prefix));
        int value = ipv4(address) | ~mask;
        return InetAddress.getByAddress(new byte[]{
                (byte) (value >>> 24), (byte) (value >>> 16),
                (byte) (value >>> 8), (byte) value
        });
    }

    private static int ipv4(Inet4Address address) {
        byte[] bytes = address.getAddress();
        return ((bytes[0] & 255) << 24) | ((bytes[1] & 255) << 16)
                | ((bytes[2] & 255) << 8) | (bytes[3] & 255);
    }

    private static byte[] magicPacket(String macAddress) {
        String clean = macAddress.replace(":", "").replace("-", "");
        byte[] mac = new byte[6];
        for (int i = 0; i < 6; i++) mac[i] = (byte) Integer.parseInt(clean.substring(i * 2, i * 2 + 2), 16);
        byte[] packet = new byte[6 + 16 * mac.length];
        for (int i = 0; i < 6; i++) packet[i] = (byte) 0xff;
        for (int i = 6; i < packet.length; i += mac.length) System.arraycopy(mac, 0, packet, i, mac.length);
        return packet;
    }

    private static String cleanEndpoint(String endpoint) {
        return endpoint == null ? "" : endpoint.trim().replaceAll("/+$", "");
    }

    private static String errorMessage(Exception error) {
        String message = error.getMessage();
        return message == null || message.isEmpty() ? error.getClass().getSimpleName() : message;
    }

    private TextView text(String value, int size, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setTypeface(Typeface.DEFAULT, style);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private GradientDrawable background() {
        GradientDrawable drawable = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.rgb(67, 67, 70), Color.rgb(47, 48, 52), Color.rgb(40, 41, 45)}
        );
        drawable.setGradientType(GradientDrawable.LINEAR_GRADIENT);
        return drawable;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class PulseView extends View {
        private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint core = new Paint(Paint.ANTI_ALIAS_FLAG);

        PulseView(Context context) {
            super(context);
            glow.setColor(Color.argb(42, 234, 211, 174));
            core.setShader(new android.graphics.RadialGradient(
                    0, 0, 1,
                    new int[]{Color.rgb(255, 244, 224), Color.rgb(234, 211, 174), Color.rgb(132, 106, 75)},
                    new float[]{0f, .55f, 1f}, android.graphics.Shader.TileMode.CLAMP));
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float cx = getWidth() / 2f;
            float cy = getHeight() / 2f;
            float radius = Math.min(getWidth(), getHeight()) * .32f;
            canvas.drawCircle(cx, cy, radius * 1.55f, glow);
            canvas.save();
            canvas.translate(cx - radius * .25f, cy - radius * .25f);
            canvas.scale(radius, radius);
            canvas.drawCircle(.25f, .25f, 1f, core);
            canvas.restore();
        }
    }
}
