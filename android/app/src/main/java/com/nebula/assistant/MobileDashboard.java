package com.nebula.assistant;

import android.app.Activity;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Space;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Navegação nativa; rede fora da UI, sem polling quando a tela está oculta. */
final class MobileDashboard {
    final LinearLayout root;
    final Button powerButton;
    final TextView status;
    private final Activity activity;
    private final String token;
    private final String[] hubs, pcs;
    private final Runnable wake;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final LinearLayout content, navigation;
    private final LinearLayout home;
    private final Button[] tabs = new Button[4];
    private String hubEndpoint, pcEndpoint;
    private int selected, generation;
    private boolean closed, busy, active = true;
    private TurboTelemetryClient turboTelemetry;
    private DevicePanelView devicePanel;
    private ImageView mediaArtwork;
    private TextView mediaTitle, mediaArtist, mediaProgress, mediaStatus;
    private Button mediaPlay, mediaPrevious, mediaNext;
    private String mediaArtworkId = "";
    private boolean mediaRefreshing;
    private String selectedTvId = "";
    private final Runnable mediaTicker = this::refreshMedia;
    private final int bg = Color.rgb(47, 48, 52), card = Color.rgb(58, 59, 63);
    private final int accent = Color.rgb(234, 211, 174), text = Color.rgb(247, 241, 232);
    private final int muted = Color.rgb(190, 181, 168), surface = Color.rgb(42, 43, 47);
    private interface Work { JSONObject run() throws Exception; }
    private interface Result { void show(JSONObject data); }

    MobileDashboard(Activity activity, String token, String[] hubs, String[] pcs, Runnable wake) {
        this.activity = activity; this.token = token; this.hubs = hubs; this.pcs = pcs;
        this.wake = wake;
        root = column();
        GradientDrawable backdrop = new GradientDrawable(
            GradientDrawable.Orientation.TL_BR,
            new int[]{Color.rgb(67, 67, 70), bg, Color.rgb(40, 41, 45)}
        );
        root.setBackground(backdrop);
        root.setPadding(dp(10), dp(12), dp(12), dp(12));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(dp(10) + insets.getSystemWindowInsetLeft(), dp(12) + insets.getSystemWindowInsetTop(),
                dp(12) + insets.getSystemWindowInsetRight(), dp(12) + insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout body = column(); body.setPadding(dp(14), dp(4), 0, 0);
        TextView brand = label("NEBULA", 22, text); brand.setLetterSpacing(.12f);
        body.addView(brand); body.addView(label("SUA CASA. UM CONTROLE.", 9, accent));
        ScrollView scroll = new ScrollView(activity); scroll.setFillViewport(true);
        content = column(); content.setPadding(0, dp(12), 0, dp(12)); scroll.addView(content);
        body.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        navigation = column();
        navigation.setOrientation(LinearLayout.HORIZONTAL);
        navigation.setPadding(dp(4), dp(8), dp(4), dp(8));
        GradientDrawable navShape = new GradientDrawable(); navShape.setColor(surface); navShape.setCornerRadius(dp(10));
        navigation.setBackground(navShape); navigation.setElevation(dp(10));
        TextView navBrand = label("N", 20, accent); navBrand.setGravity(Gravity.CENTER);
        navigation.addView(navBrand, new LinearLayout.LayoutParams(dp(34), -1));
        String[] names = {"⌂\nCasa", "▯\nDisp.", "◎\nModos", "♫\nMúsica"};
        for (int i = 0; i < names.length; i++) {
            final int index = i;
            tabs[i] = navigationButton(names[i], () -> select(index));
            tabs[i].setPadding(dp(2), 0, dp(2), 0);
            navigation.addView(tabs[i], new LinearLayout.LayoutParams(0, -1, 1));
        }
        root.addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
        root.addView(navigation, new LinearLayout.LayoutParams(-1, dp(76)));
        home = column();
        TextView headline = label("Tudo à mão", 31, text); headline.setGravity(Gravity.CENTER_HORIZONTAL); home.addView(headline);
        TextView intro = label("Seu computador, sua casa e seus controles em um só lugar.", 14, muted);
        intro.setGravity(Gravity.CENTER_HORIZONTAL); home.addView(intro);
        boolean landscape = activity.getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        LinearLayout homeCards = new LinearLayout(activity);
        homeCards.setOrientation(landscape ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        powerButton = primaryButton("Ligar PC", wake);
        LinearLayout pc = homeCard("COMPUTADOR", "Nebula no PC",
            "Ligue ou abra a Nebula no computador.", powerButton);
        status = label("Pronta para enviar o sinal de inicialização.", 12, muted); pc.addView(status);
        LinearLayout shortcuts = homeCard("CONTROLE UNIVERSAL", "Seus dispositivos",
            "TVs, iluminação e ar-condicionado.", primaryButton("Abrir", () -> select(1)));
        LinearLayout tools = homeCard("ARENA + EXPERIMENTOS", "Ferramentas",
            "Boost, nick e BPM sobre o jogo.", primaryButton("Abrir", () -> select(2)));
        for (LinearLayout item : new LinearLayout[]{pc, shortcuts, tools}) {
            LinearLayout.LayoutParams itemParams = landscape
                ? new LinearLayout.LayoutParams(0, -1, 1)
                : new LinearLayout.LayoutParams(-1, -2);
            itemParams.setMargins(landscape ? dp(5) : 0, dp(14), landscape ? dp(5) : 0, 0);
            homeCards.addView(item, itemParams);
        }
        home.addView(homeCards);
        select(0);
    }

    private int dp(int value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }
    private LinearLayout column() { LinearLayout v = new LinearLayout(activity); v.setOrientation(LinearLayout.VERTICAL); return v; }
    private TextView label(String text, int size, int color) {
        TextView v = new TextView(activity); v.setText(text); v.setTextSize(size); v.setTextColor(color);
        v.setPadding(0, dp(4), 0, dp(8)); v.setLineSpacing(0, 1.06f);
        v.setTypeface(Typeface.create("sans-serif", size >= 20 ? Typeface.BOLD : Typeface.NORMAL));
        return v;
    }
    private Button button(String label, Runnable action) {
        Button v = new Button(activity); v.setText(label); v.setTextColor(text); v.setAllCaps(false);
        v.setMinHeight(dp(48)); v.setTextSize(14); v.setStateListAnimator(null);
        v.setBackground(rounded(surface, 8, Color.rgb(76, 76, 80)));
        v.setOnClickListener(view -> action.run()); return v;
    }
    private Button primaryButton(String label, Runnable action) {
        Button v = button(label, action); v.setTextColor(Color.rgb(43, 40, 35));
        v.setTextSize(13); v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        v.setMinWidth(dp(84)); v.setMinHeight(dp(42)); v.setPadding(dp(16), 0, dp(16), 0);
        v.setBackground(rounded(accent, 8, Color.TRANSPARENT)); return v;
    }
    private Button navigationButton(String label, Runnable action) {
        Button v = button(label, action); v.setTextSize(10); v.setMinHeight(0);
        v.setBackground(rounded(Color.TRANSPARENT, 8, Color.TRANSPARENT)); return v;
    }
    private GradientDrawable rounded(int fill, int radius, int stroke) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(fill); shape.setCornerRadius(dp(radius));
        if (stroke != Color.TRANSPARENT) shape.setStroke(dp(1), stroke); return shape;
    }
    private LinearLayout card(String eyebrow, String title) {
        LinearLayout v = column(); v.setPadding(dp(16), dp(14), dp(16), dp(14));
        GradientDrawable shape = new GradientDrawable(); shape.setColor(card); shape.setCornerRadius(dp(10));
        shape.setStroke(dp(1), Color.rgb(78, 78, 82)); v.setBackground(shape); v.setElevation(dp(7));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.setMargins(0, dp(14), 0, 0); v.setLayoutParams(params);
        v.addView(label(eyebrow.toUpperCase(java.util.Locale.ROOT), 10, accent)); v.addView(label(title, 22, text)); return v;
    }
    private LinearLayout homeCard(String eyebrow, String title, String description, Button action) {
        LinearLayout v = column(); v.setPadding(dp(17), dp(14), dp(17), dp(14));
        v.setBackground(rounded(card, 10, Color.rgb(78, 78, 82))); v.setElevation(dp(8));
        LinearLayout header = new LinearLayout(activity); header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout copy = column();
        TextView overline = label(eyebrow.toUpperCase(java.util.Locale.ROOT), 9, accent); overline.setLetterSpacing(.06f);
        copy.addView(overline); copy.addView(label(title, 20, text));
        header.addView(copy, new LinearLayout.LayoutParams(0, -2, 1));
        header.addView(action, new LinearLayout.LayoutParams(-2, dp(42)));
        v.addView(header); v.addView(label(description, 12, muted)); return v;
    }

    private void select(int index) {
        ui.removeCallbacks(mediaTicker);
        if(devicePanel!=null) { devicePanel.stop();devicePanel=null; }
        if(turboTelemetry!=null) { turboTelemetry.close();turboTelemetry=null; }
        selected = index; generation++; content.removeAllViews();
        root.setKeepScreenOn(index == 3 || index == 4);
        for (int i = 0; i < tabs.length; i++) {
            boolean activeTab = i == index;
            tabs[i].setTextColor(activeTab ? text : muted);
            tabs[i].setBackground(rounded(activeTab ? Color.rgb(75, 71, 65) : Color.TRANSPARENT,
                8, Color.TRANSPARENT));
        }
        if (index == 0) { content.addView(home); return; }
        if (index == 1) { devices(); return; }
        if (index == 2) { tools(); return; }
        if (index == 3) { media(); return; }
        if (index == 4) { turboPanel(); return; }
    }

    private void devices() {
        content.addView(label("Dispositivos", 28, Color.WHITE));
        TextView info = label("Controles dos aparelhos configurados no hub.", 14, muted); content.addView(info);
        LinearLayout row = new LinearLayout(activity);
        row.addView(button("Atualizar", () -> loadDevices(false, info)), new LinearLayout.LayoutParams(0, -2, 1));
        row.addView(button("Buscar TVs", () -> loadDevices(true, info)), new LinearLayout.LayoutParams(0, -2, 1));
        content.addView(row); loadDevices(false, info);
    }

    private void loadDevices(boolean discover, TextView info) {
        run(info, () -> {
            String endpoint = endpoint(false);
            return request(endpoint, discover ? "/universal/discover" : "/universal/devices", discover ? new JSONObject() : null);
        }, data -> {
            while (content.getChildCount() > 3) content.removeViewAt(3);
            JSONArray devices = data.optJSONArray("devices");
            int count = devices == null ? 0 : devices.length();
            info.setText(count + " dispositivo(s) · " + (data.optBoolean("home_assistant_configured") ? "Home Assistant conectado" : "Hub local"));
            JSONArray errors = data.optJSONArray("errors");
            if (errors != null && errors.length() > 0) content.addView(label(errors.optString(0), 14, Color.rgb(255, 181, 91)));
            addTvTabs(devices);
            for (int i = 0; i < count; i++) {
                JSONObject device = devices.optJSONObject(i); if (device == null) continue;
                String id = device.optString("id");
                if ("tv".equals(device.optString("kind")) && !id.equals(selectedTvId)) continue;
                LinearLayout v = card(device.optString("source"), device.optString("name"));
                TextView state = label(device.optString("status", device.optBoolean("available") ? "Disponível" : "Indisponível"), 13, muted); v.addView(state);
                JSONArray actions = device.optJSONArray("actions");
                boolean lg = device.optString("source").equalsIgnoreCase("lg");
                if (lg) {
                    lgRemoteControls(v, id, state, device.optBoolean("available") && hubEndpoint != null);
                    linkControls(v, id, state);
                    content.addView(v);
                    continue;
                }
                LinearLayout buttons = null;
                for (int n = 0; actions != null && n < actions.length(); n++) {
                    JSONObject command = actions.optJSONObject(n); if (command == null) continue;
                    String action = command.optString("id");
                    if (id.equals("local:air") && (action.startsWith("temp_") || action.startsWith("timer_"))) continue;
                    if (n % 2 == 0) { buttons = new LinearLayout(activity); v.addView(buttons); }
                    Button b = button(command.optString("label"), () -> {
                        if (id.equals("pc:main") && action.equals("wake")) { select(0); wake.run(); return; }
                        run(state, () -> universalAction(id, action),
                            result -> { state.setText(result.optString("message", "Comando enviado.")); if (action.equals("pair")) loadDevices(false, info); });
                    });
                    buttons.addView(b, new LinearLayout.LayoutParams(0, -2, 1));
                }
                if (id.equals("local:air")) airControls(v, device, state);
                if (id.equals("local:lamp")) lampControls(v, state);
                if ("tv".equals(device.optString("kind"))) linkControls(v, id, state);
                content.addView(v);
            }
            if (count == 0) content.addView(label("Nenhum aparelho cadastrado. Ligue a TV e toque em Buscar TVs.", 15, muted));
            content.addView(label("Novas marcas dependem de integração. Conecte o Home Assistant nas configurações do hub para ampliar seus controles.", 12, muted));
        });
    }

    private void addTvTabs(JSONArray devices) {
        LinearLayout tabsRow = new LinearLayout(activity);
        tabsRow.setOrientation(LinearLayout.HORIZONTAL);
        boolean found = false;
        for (int i = 0; i < devices.length(); i++) {
            JSONObject device = devices.optJSONObject(i);
            if (device == null || !"tv".equals(device.optString("kind"))) continue;
            String id = device.optString("id");
            if (!found) {
                found = true;
                if (selectedTvId.isEmpty()) selectedTvId = id;
            }
            Button tab = button(device.optString("name", "TV"), () -> {
                selectedTvId = id;
                select(1);
            });
            tab.setTextSize(12);
            tab.setTextColor(id.equals(selectedTvId) ? Color.WHITE : muted);
            tabsRow.addView(tab, new LinearLayout.LayoutParams(0, -2, 1));
        }
        if (found) content.addView(tabsRow);
    }

    private void linkControls(LinearLayout card, String deviceId, TextView status) {
        card.addView(label("Abrir conteúdo", 13, muted));
        EditText link = new EditText(activity);
        link.setSingleLine(true);
        link.setHint("Cole um link do YouTube ou Spotify");
        link.setTextColor(Color.WHITE);
        link.setHintTextColor(muted);
        card.addView(link);
        Button send = button("Abrir link nesta TV", () -> {
            String value = link.getText().toString().trim();
            run(status,
                () -> request(endpoint(false), "/tvs/link", new JSONObject().put("id", deviceId).put("url", value)),
                result -> status.setText(result.optString("message", "Link enviado.")));
        });
        card.addView(send);
    }

    private void lgRemoteControls(LinearLayout card, String deviceId, TextView status, boolean available) {
        card.addView(label("Controle LG webOS", 14, accent));
        LinearLayout top = new LinearLayout(activity);
        top.addView(remoteButton("Desligar", deviceId, "power_off", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        top.addView(remoteButton("Mudo", deviceId, "mute", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        card.addView(top);

        LinearLayout volume = new LinearLayout(activity);
        volume.addView(remoteButton("Vol −", deviceId, "volume_down", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        volume.addView(remoteButton("Vol +", deviceId, "volume_up", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        card.addView(volume);

        card.addView(label("Navegação", 13, muted));
        DpadView dpad = new DpadView(activity, action -> run(status,
            () -> universalAction(deviceId, action),
            result -> status.setText(result.optString("message", "Comando enviado."))));
        LinearLayout.LayoutParams dpadSize = new LinearLayout.LayoutParams(dp(220), dp(220));
        dpadSize.gravity = Gravity.CENTER_HORIZONTAL;
        dpadSize.setMargins(0, dp(8), 0, dp(8));
        card.addView(dpad, dpadSize);
        dpad.setEnabled(available && !busy);
        LinearLayout nav = new LinearLayout(activity);
        nav.addView(remoteButton("Home", deviceId, "home", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        nav.addView(remoteButton("Voltar", deviceId, "back", status, available), new LinearLayout.LayoutParams(0, -2, 1));
        card.addView(nav);

        card.addView(label("Números", 13, muted));
        for (int row = 0; row < 4; row++) {
            LinearLayout numbers = new LinearLayout(activity);
            for (int column = 0; column < 3; column++) {
                int number = row * 3 + column + 1;
                if (row == 3) number = column == 1 ? 0 : -1;
                if (number < 0) numbers.addView(new Space(activity), new LinearLayout.LayoutParams(0, dp(46), 1));
                else numbers.addView(remoteButton(Integer.toString(number), deviceId, "number_" + number, status, available), new LinearLayout.LayoutParams(0, dp(46), 1));
            }
            card.addView(numbers);
        }
    }

    private Button remoteButton(String label, String deviceId, String action, TextView status, boolean available) {
        Button control = button(label, () -> run(status,
            () -> universalAction(deviceId, action),
            result -> status.setText(result.optString("message", "Comando enviado."))));
        control.setEnabled(available && !busy);
        return control;
    }

    private Button directionButton(String label, String deviceId, String action, TextView status, boolean available) {
        Button control = remoteButton(label, deviceId, action, status, available);
        GradientDrawable circle = new GradientDrawable();
        circle.setShape(GradientDrawable.OVAL);
        circle.setColor(surface);
        control.setBackground(circle);
        return control;
    }

    private static final class DpadView extends View {
        interface Listener { void send(String action); }
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Listener listener;
        DpadView(android.content.Context context, Listener listener) {
            super(context); this.listener = listener; setClickable(true);
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float cx = getWidth() / 2f, cy = getHeight() / 2f;
            float radius = Math.min(getWidth(), getHeight()) * .46f;
            paint.setColor(Color.rgb(39, 40, 44)); paint.setStyle(Paint.Style.FILL);
            canvas.drawCircle(cx, cy, radius, paint);
            paint.setColor(Color.rgb(53, 54, 59));
            canvas.drawCircle(cx, cy, radius * .34f, paint);
            paint.setColor(Color.rgb(247, 241, 232)); paint.setTextAlign(Paint.Align.CENTER);
            paint.setTypeface(Typeface.DEFAULT_BOLD); paint.setTextSize(radius * .22f);
            canvas.drawText("OK", cx, cy + radius * .08f, paint);
            paint.setTextSize(radius * .18f);
            canvas.drawText("▲", cx, cy - radius * .58f, paint);
            canvas.drawText("▼", cx, cy + radius * .72f, paint);
            canvas.drawText("◀", cx - radius * .66f, cy + radius * .08f, paint);
            canvas.drawText("▶", cx + radius * .66f, cy + radius * .08f, paint);
        }
        @Override public boolean onTouchEvent(android.view.MotionEvent event) {
            if (event.getAction() != android.view.MotionEvent.ACTION_UP || !isEnabled()) return true;
            float dx = event.getX() - getWidth() / 2f, dy = event.getY() - getHeight() / 2f;
            String action;
            if (Math.hypot(dx, dy) < getWidth() * .25) action = "ok";
            else if (Math.abs(dx) > Math.abs(dy)) action = dx < 0 ? "left" : "right";
            else action = dy < 0 ? "up" : "down";
            listener.send(action); return true;
        }
    }

    private void airControls(LinearLayout card, JSONObject device, TextView status) {
        JSONObject air = device.optJSONObject("air");
        if (air == null) return;
        JSONArray supported = air.optJSONArray("supported_actions");
        boolean temperature = false;
        for (int i = 0; supported != null && i < supported.length(); i++)
            if (supported.optString(i).equals("temperature")) temperature = true;
        final boolean hasTemperature = temperature;
        final boolean hasTimer = device.optBoolean("timer_available");
        if (!hasTemperature && !hasTimer) return;
        final boolean[] timerMode = {false};
        final int[] minutes = {30}, degrees = {air.optInt("temperature", 17)};
        TextView display = label("", 28, Color.WHITE); card.addView(display);
        TextView schedule = label("", 13, muted); card.addView(schedule);
        JSONObject initialTimer = air.optJSONObject("timer");
        schedule.setText(timerText(initialTimer));
        Button apply = button("Programar desligamento", () -> {
            final int chosen = minutes[0];
            run(status, () -> request(endpoint(false), "/universal/action", new JSONObject().put("device_id", "local:air").put("action", "timer_set_" + chosen)),
                result -> { status.setText(result.optString("message")); schedule.setText(timerText(result.optJSONObject("timer"))); });
        });
        Button mode = button("Timer", () -> {});
        Runnable render = () -> {
            display.setText(timerMode[0] ? String.format(java.util.Locale.ROOT, "%dh %02dmin", minutes[0]/60, minutes[0]%60) : degrees[0] + " °C · último ajuste");
            mode.setText(timerMode[0] ? "Voltar à temperatura" : "Timer para desligar");
            apply.setVisibility(timerMode[0] ? View.VISIBLE : View.GONE);
        };
        mode.setOnClickListener(view -> { timerMode[0] = !timerMode[0]; render.run(); });
        if (hasTimer) card.addView(mode);
        LinearLayout row = new LinearLayout(activity);
        for (int delta : new int[]{-1, 1}) row.addView(button(delta < 0 ? "−" : "+", () -> {
            if (timerMode[0]) { minutes[0] = Math.max(30, Math.min(1440, minutes[0] + delta*30)); render.run(); return; }
            if (!hasTemperature) { status.setText("Ajuste de temperatura ainda não configurado."); return; }
            run(status, () -> request(endpoint(false), "/universal/action", new JSONObject().put("device_id", "local:air").put("action", delta < 0 ? "temp_down" : "temp_up")),
                result -> {
                    JSONObject changed = result.optJSONObject("air");
                    if (changed != null) degrees[0] = changed.optInt("temperature", degrees[0]);
                    status.setText(result.optString("message")); render.run();
                });
        }), new LinearLayout.LayoutParams(0, -2, 1));
        card.addView(row); card.addView(apply);
        if (hasTimer) {
            card.addView(button("Cancelar timer", () -> run(status,
                () -> request(endpoint(false), "/universal/action", new JSONObject().put("device_id", "local:air").put("action", "timer_cancel")),
                result -> { status.setText(result.optString("message")); schedule.setText(timerText(result.optJSONObject("timer"))); })));
            card.addView(label("No timer, + e − ajustam 30 minutos. Toque em Programar para confirmar. Mantenha o notebook ligado; o celular pode ficar apagado.", 12, muted));
        }
        render.run();
    }

    private void lampControls(LinearLayout card, TextView status) {
        ColorWheelView wheel = new ColorWheelView(activity, hex -> run(status,
            () -> universalAction("local:lamp", "color_" + hex),
            result -> status.setText(result.optString("message"))));
        LinearLayout.LayoutParams wheelSize = new LinearLayout.LayoutParams(dp(210),dp(210));
        wheelSize.gravity=Gravity.CENTER_HORIZONTAL; card.addView(wheel,wheelSize);
        card.addView(label("Escolha a cor e solte para aplicar",12,muted));
        TextView brightness = label("Brilho",13,muted); card.addView(brightness);
        android.widget.SeekBar slider = new android.widget.SeekBar(activity);
        slider.setMax(99); slider.setProgress(59);
        slider.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(android.widget.SeekBar bar,int progress,boolean fromUser) { brightness.setText("Brilho · " + (progress+1) + "%"); }
            public void onStartTrackingTouch(android.widget.SeekBar bar) { }
            public void onStopTrackingTouch(android.widget.SeekBar bar) {
                int value=bar.getProgress()+1;
                run(status, () -> universalAction("local:lamp", "brightness_"+value),
                    result -> status.setText(result.optString("message")));
            }
        });
        card.addView(slider);
    }

    private String timerText(JSONObject timer) {
        if (timer == null || timer.optString("status").equals("idle")) return "Sem timer";
        if (timer.optString("status").equals("armed")) return "Desligamento agendado: " +
            java.text.DateFormat.getDateTimeInstance(java.text.DateFormat.SHORT, java.text.DateFormat.SHORT).format(new java.util.Date((long)(timer.optDouble("deadline")*1000)));
        if (timer.optString("status").equals("failed")) return timer.optString("error", "Falha ao desligar; confira o ar.");
        return "Comando de desligar enviado pelo timer";
    }

    private void tools() {
        content.addView(label("Modos e ferramentas", 28, Color.WHITE));
        independentModes();
        LinearLayout pulse = card("LABORATÓRIO WI-FI", "Pulso experimental");
        TextView bpm = label("— BPM", 34, Color.WHITE); pulse.addView(bpm);
        TextView sensor = label("Requer receptor com CSI Wi-Fi. O Wi-Fi comum do celular não fornece esta medição.", 14, muted); pulse.addView(sensor);
        pulse.addView(button("Consultar sensor", () -> run(sensor,
            () -> request(endpoint(true), "/api/wifi-bpm/status", null), data -> {
                boolean valid = data.optString("status").equals("experimental_estimate") && !data.isNull("bpm") && data.optDouble("last_sample_age_seconds", 99) <= 5;
                bpm.setText(valid ? data.optString("bpm") + " BPM*" : "— BPM");
                sensor.setText(data.optString("message") + "\nAmostras: " + data.optInt("samples") + " · janela: " + data.optDouble("window_seconds") + " s");
                if (valid) ui.postDelayed(() -> {
                    bpm.setText("— BPM"); sensor.setText("Consulte novamente para obter uma leitura recente.");
                }, Math.max(1, (long) ((5 - data.optDouble("last_sample_age_seconds", 5)) * 1000)));
            })));
        pulse.addView(label("* Estimativa de periodicidade CSI, não validada clinicamente. Valores deixam de valer quando a coleta para.", 12, muted));
        content.addView(pulse);
    }

    private void run(TextView status, Work work, Result result) {
        run(status, work, result, true);
    }

    private void media() {
        content.addView(label("Música no PC", 28, Color.WHITE));
        content.addView(label(
            "Controle o Spotify, YouTube ou outro player do Windows sem sair da partida.",
            14, muted
        ));
        LinearLayout player = card("TOCANDO AGORA", "Player do Windows");
        mediaArtwork = new ImageView(activity);
        mediaArtwork.setScaleType(ImageView.ScaleType.CENTER_CROP);
        mediaArtwork.setBackgroundColor(Color.rgb(8, 14, 24));
        LinearLayout.LayoutParams art = new LinearLayout.LayoutParams(dp(280), dp(280));
        art.gravity = Gravity.CENTER_HORIZONTAL;
        art.setMargins(0, dp(8), 0, dp(18));
        player.addView(mediaArtwork, art);
        mediaTitle = label("Procurando música…", 24, Color.WHITE);
        mediaTitle.setGravity(Gravity.CENTER_HORIZONTAL);
        player.addView(mediaTitle);
        mediaArtist = label("", 15, muted);
        mediaArtist.setGravity(Gravity.CENTER_HORIZONTAL);
        player.addView(mediaArtist);
        mediaProgress = label("--:--  /  --:--", 13, muted);
        mediaProgress.setGravity(Gravity.CENTER_HORIZONTAL);
        player.addView(mediaProgress);

        LinearLayout controls = new LinearLayout(activity);
        mediaPrevious = button("⏮  Anterior", () -> mediaAction("previous"));
        mediaPlay = button("⏯  Pausar", () -> mediaAction("play_pause"));
        mediaNext = button("Próxima  ⏭", () -> mediaAction("next"));
        controls.addView(mediaPrevious, new LinearLayout.LayoutParams(0, dp(58), 1));
        controls.addView(mediaPlay, new LinearLayout.LayoutParams(0, dp(58), 1));
        controls.addView(mediaNext, new LinearLayout.LayoutParams(0, dp(58), 1));
        player.addView(controls);
        mediaStatus = label("Conectando ao PC…", 13, muted);
        mediaStatus.setGravity(Gravity.CENTER_HORIZONTAL);
        player.addView(mediaStatus);
        player.addView(label(
            "A tela permanece ligada nesta aba. A música continua no navegador do PC.",
            12, muted
        ));
        content.addView(player);
        refreshMedia();
    }

    private void mediaAction(String action) {
        if (mediaStatus == null) return;
        run(mediaStatus,
            () -> request(endpoint(true), "/api/media/action", new JSONObject().put("action", action)),
            data -> {
                mediaStatus.setText(data.optString("message", "Comando enviado."));
                ui.removeCallbacks(mediaTicker);
                ui.postDelayed(mediaTicker, 250);
            }
        );
    }

    private void refreshMedia() {
        if (closed || !active || selected != 3 || mediaRefreshing) return;
        mediaRefreshing = true;
        final int screen = generation;
        final String knownArtwork = mediaArtworkId;
        network.execute(() -> {
            JSONObject data = null;
            String error = null;
            try {
                String suffix = knownArtwork.isEmpty() ? "" : "?artwork_id=" +
                    java.net.URLEncoder.encode(knownArtwork, "UTF-8");
                data = request(endpoint(true), "/api/media" + suffix, null);
            } catch (Exception failure) {
                error = failure.getMessage();
                pcEndpoint = null;
            }
            final JSONObject result = data;
            final String message = error;
            ui.post(() -> {
                mediaRefreshing = false;
                if (closed || !active || selected != 3 || screen != generation) return;
                if (message != null) {
                    mediaStatus.setText(message);
                } else {
                    renderMedia(result);
                }
                ui.postDelayed(mediaTicker, 1500);
            });
        });
    }

    private void renderMedia(JSONObject data) {
        if (data == null || !data.optBoolean("available")) {
            mediaTitle.setText("Nenhuma música ativa");
            mediaArtist.setText("Abra o Spotify, YouTube ou outro player no PC.");
            mediaProgress.setText("--:--  /  --:--");
            mediaStatus.setText(data == null ? "PC indisponÃ­vel." : data.optString("message"));
            mediaPlay.setEnabled(false); mediaPrevious.setEnabled(false); mediaNext.setEnabled(false);
            return;
        }
        mediaTitle.setText(data.optString("title", "Mídia sem título"));
        String artist = data.optString("artist");
        String album = data.optString("album");
        mediaArtist.setText(artist + (artist.isEmpty() || album.isEmpty() ? "" : "  ·  ") + album);
        mediaProgress.setText(formatMediaTime(data.optDouble("position_seconds")) + "  /  " +
            formatMediaTime(data.optDouble("duration_seconds")));
        String playback = data.optString("playback_status");
        mediaPlay.setText(playback.equals("playing") ? "⏯  Pausar" : "▶  Continuar");
        JSONObject controls = data.optJSONObject("controls");
        mediaPlay.setEnabled(controls == null || controls.optBoolean("play") || controls.optBoolean("pause"));
        mediaPrevious.setEnabled(controls == null || controls.optBoolean("previous"));
        mediaNext.setEnabled(controls == null || controls.optBoolean("next"));
        String source = data.optString("source").replace(".exe", "");
        mediaStatus.setText((playback.equals("playing") ? "Reproduzindo" : "Pausada") +
            (source.isEmpty() ? "" : "  ·  " + source));

        String artwork = data.optString("artwork");
        if (!artwork.isEmpty()) {
            try {
                byte[] bytes = android.util.Base64.decode(artwork, android.util.Base64.DEFAULT);
                android.graphics.Bitmap bitmap = android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                if (bitmap != null) mediaArtwork.setImageBitmap(bitmap);
            } catch (IllegalArgumentException ignored) { }
        }
        String newArtworkId = data.optString("artwork_id");
        if (!newArtworkId.isEmpty()) mediaArtworkId = newArtworkId;
    }

    private String formatMediaTime(double seconds) {
        int value = Math.max(0, (int)Math.round(seconds));
        return String.format(java.util.Locale.ROOT, "%d:%02d", value / 60, value % 60);
    }

    private void independentModes() {
        String[] devices={"lamp","keyboard","controller","mobile"};
        String[] names={"Abajur","Kumara","Controle PS4 · USB","Telefone"};
        String[][] modes={{"manual","ambilight","music","torch","rpm","boost"},
            {"manual","ambilight","boost"},{"manual","ambilight","rpm","boost"},{"manual","rpm","turbo"}};
        android.widget.Spinner[] selectors=new android.widget.Spinner[4];
        Button[] flashes=new Button[4];
        TextView[] errors=new TextView[4];
        TextView info=label("Cada dispositivo usa seu próprio modo.",14,muted);content.addView(info);
        LinearLayout presets=card("PRESETS","Suas configurações");
        android.widget.AutoCompleteTextView name=new android.widget.AutoCompleteTextView(activity);
        name.setTextColor(Color.WHITE);name.setHintTextColor(muted);name.setHint("Nome do preset");name.setSingleLine(true);name.setThreshold(0);
        presets.addView(name);
        Result render=data->{
            JSONObject state=data.optJSONObject("state");if(state==null)return;
            JSONObject configs=state.optJSONObject("devices");
            for(int i=0;i<devices.length;i++) {
                JSONObject config=configs==null?null:configs.optJSONObject(devices[i]);
                String chosen=config==null?"manual":config.optString("mode","manual");
                for(int j=0;j<modes[i].length;j++)if(modes[i][j].equals(chosen))selectors[i].setSelection(j);
                errors[i].setText(config==null || config.isNull("error")?"":config.optString("error"));
                if(flashes[i]!=null)styleFlashButton(flashes[i], config!=null && config.optBoolean("afterfire"));
            }
            JSONArray list=state.optJSONArray("presets");java.util.ArrayList<String> saved=new java.util.ArrayList<>();
            if(list!=null)for(int i=0;i<list.length();i++)saved.add(list.optString(i));
            name.setAdapter(new android.widget.ArrayAdapter<>(activity,android.R.layout.simple_dropdown_item_1line,saved));
            info.setText(data.optString("message","Modos atualizados."));
        };
        for(int i=0;i<devices.length;i++) {
            final int index=i;
            LinearLayout item=card("DISPOSITIVO",names[i]);
            selectors[i]=new android.widget.Spinner(activity);
            java.util.ArrayList<String> labels=new java.util.ArrayList<>();
            for(String mode:modes[i])labels.add(modeLabel(mode));
            android.widget.ArrayAdapter<String> adapter=new android.widget.ArrayAdapter<>(activity,android.R.layout.simple_spinner_dropdown_item,labels);
            selectors[i].setAdapter(adapter);selectors[i].setBackgroundTintList(android.content.res.ColorStateList.valueOf(accent));
            item.addView(selectors[i]);
            errors[i]=label("",12,Color.rgb(255,173,102));item.addView(errors[i]);
            item.addView(button("Aplicar neste dispositivo",()->{
                String mode=modes[index][selectors[index].getSelectedItemPosition()];
                run(info,()->request(endpoint(true),"/api/control",new JSONObject().put("action","device.mode")
                    .put("value",new JSONObject().put("device",devices[index]).put("mode",mode))),render);
            }));
            if(i==1 || i==2) {
                flashes[i]=button("Flash do escape · BeamNG", () -> {
                    boolean enabled=!flashes[index].isSelected();
                    styleFlashButton(flashes[index], enabled);
                    run(info,
                    ()->request(endpoint(true),"/api/control",new JSONObject().put("action","device.flash")
                        .put("value",new JSONObject().put("device",devices[index]).put("enabled",enabled))),render);
                });
                styleFlashButton(flashes[i], false);
                item.addView(flashes[i]);
            }
            if(i==0) {
                LinearLayout power=new LinearLayout(activity);
                for(boolean on:new boolean[]{true,false})power.addView(button(on?"Ligar":"Desligar",()->run(info,
                    ()->request(endpoint(true),"/api/control",new JSONObject().put("action","lamp.power").put("value",on)),render)),new LinearLayout.LayoutParams(0,-2,1));
                item.addView(power);
                ColorWheelView wheel=new ColorWheelView(activity,hex->run(info,
                    ()->request(endpoint(true),"/api/control",new JSONObject().put("action","lamp.color").put("value","#"+hex)),render));
                item.addView(wheel,new LinearLayout.LayoutParams(-1,dp(180)));
                android.widget.SeekBar brightness=new android.widget.SeekBar(activity);brightness.setMax(99);brightness.setProgress(59);
                brightness.setOnSeekBarChangeListener(new android.widget.SeekBar.OnSeekBarChangeListener(){
                    public void onProgressChanged(android.widget.SeekBar s,int p,boolean user){}
                    public void onStartTrackingTouch(android.widget.SeekBar s){}
                    public void onStopTrackingTouch(android.widget.SeekBar s){int value=s.getProgress()+1;run(info,
                        ()->request(endpoint(true),"/api/control",new JSONObject().put("action","lamp.brightness").put("value",value)),render);}
                });item.addView(label("Brilho",12,muted));item.addView(brightness);
            }
            content.addView(item);
        }
        presets.addView(button("Escolher preset salvo",()->name.showDropDown()));
        for(String action:new String[]{"preset.save","preset.apply","preset.delete"}) {
            String title=action.endsWith("save")?"Salvar configuração atual":action.endsWith("apply")?"▶ Aplicar preset":"Excluir preset";
            presets.addView(button(title,()->{String value=name.getText().toString().trim();run(info,
                ()->request(endpoint(true),"/api/control",new JSONObject().put("action",action).put("value",value)),render);}));
        }
        presets.addView(label("Diga: Nebula, ative o preset Corrida. Salvar com o mesmo nome atualiza o preset.",12,muted));
        content.addView(presets);
        android.widget.CheckBox overlay = new android.widget.CheckBox(activity);
        overlay.setText("Overlay do Rocket League");
        overlay.setTextColor(Color.WHITE);
        overlay.setButtonTintList(android.content.res.ColorStateList.valueOf(accent));
        overlay.setPadding(dp(10), dp(12), dp(10), dp(12));
        overlay.setOnClickListener(view -> {
            boolean enabled = overlay.isChecked();
            run(info,
                () -> request(endpoint(true), "/api/rocket-overlay/action",
                    new JSONObject().put("action", enabled ? "start" : "stop")),
                data -> {
                    JSONObject state = data.optJSONObject("state");
                    overlay.setChecked(state == null ? enabled : state.optBoolean("running", enabled));
                    info.setText(data.optString("message", enabled ? "Overlay ligada." : "Overlay desligada."));
                }
            );
        });
        content.addView(overlay);
        loadOverlayState(overlay, info);
        content.addView(button("Abrir painel do telefone",()->select(4)));
        content.addView(button("Atualizar estados",()->run(info,()->request(endpoint(true),"/api/control",null),render)));
        run(info,()->request(endpoint(true),"/api/control",null),render);
    }

    private void styleFlashButton(Button button, boolean enabled) {
        button.setSelected(enabled);
        button.setTextColor(enabled ? Color.rgb(43, 40, 35) : Color.rgb(247, 241, 232));
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setPadding(dp(18), dp(12), dp(18), dp(12));
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(enabled ? Color.rgb(234, 211, 174) : Color.rgb(65, 65, 68));
        shape.setCornerRadius(dp(12));
        shape.setStroke(dp(2), Color.BLACK);
        button.setBackground(shape);
    }

    private void loadOverlayState(android.widget.CheckBox overlay, TextView info) {
        final int screen = generation;
        network.execute(() -> {
            JSONObject data = null;
            try { data = request(endpoint(true), "/api/rocket-overlay/status", null); }
            catch (Exception ignored) { }
            final JSONObject state = data;
            ui.post(() -> {
                if (closed || !active || selected != 2 || generation != screen || state == null) return;
                overlay.setChecked(state.optBoolean("running"));
                if (!state.optString("error").isEmpty()) info.setText(state.optString("error"));
            });
        });
    }

    private String modeLabel(String mode) {
        switch(mode) {
            case "manual":return "Desativado / manual";
            case "rpm":return "RPM / FuelTech";
            case "turbo":return "Pressão do turbo";
            case "music":return "Música";
            case "torch":return "Tocha";
            case "boost":return "Boost";
            default:return "Ambilight";
        }
    }

    private JSONObject universalAction(String device,String action) throws Exception {
        if(device.equals("local:lamp")) {
            String pc=null;try {pc=endpoint(true);}catch(Exception unavailable){}
            if(pc!=null) {
                String command;Object value;
                if(action.startsWith("color_")){command="lamp.color";value="#"+action.substring(6);}
                else if(action.startsWith("brightness_")){command="lamp.brightness";value=Integer.parseInt(action.substring(11));}
                else if(action.equals("warm")||action.equals("cool")){command="lamp.temperature";value=action.equals("warm")?"quente":"fria";}
                else if(action.equals("turn_on")||action.equals("turn_off")){command="lamp.power";value=action.equals("turn_on");}
                else throw new java.io.IOException("Comando de abajur desconhecido.");
                return request(pc,"/api/control",new JSONObject().put("action",command).put("value",value));
            }
        }
        return request(endpoint(false),"/universal/action",new JSONObject().put("device_id",device).put("action",action));
    }

    private void run(TextView status, Work work, Result result, boolean announce) {
        if (closed) return;
        if (busy) { status.setText("Aguarde a operação em andamento e tente novamente."); return; }
        busy = true; final int screen = generation; if (announce) status.setText("Conectando…");
        network.execute(() -> {
            JSONObject value = null; String error = null;
            try { value = work.run(); } catch (Exception e) { error = e.getMessage(); hubEndpoint = null; pcEndpoint = null; }
            final JSONObject data = value; final String message = error;
            ui.post(() -> { busy = false; if (closed || !active || screen != generation) return;
                if (message != null) status.setText(message); else result.show(data);
            });
        });
    }

    private String endpoint(boolean pc) throws Exception {
        String cached = pc ? pcEndpoint : hubEndpoint; if (cached != null) return cached;
        for (String candidate : pc ? pcs : hubs) {
            try {
                request(candidate, pc ? "/api/rocket-overlay/status" : "/health", null);
                if (pc) pcEndpoint = candidate; else hubEndpoint = candidate;
                return candidate;
            } catch (Exception ignored) { }
        }
        throw new java.io.IOException(pc ? "PC indisponível. Abra a Nebula 1.23 no PC e confira Wi-Fi ou Tailscale." : "Hub indisponível. Atualize o hub para 1.23 e confira Wi-Fi ou Tailscale.");
    }

    private JSONObject request(String endpoint, String path, JSONObject payload) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(endpoint + path).openConnection();
        try {
            c.setConnectTimeout(1500); c.setReadTimeout(payload != null || path.contains("discover") || path.contains("action") ? 35000 : 8000);
            c.setInstanceFollowRedirects(false); c.setRequestProperty("X-Nebula-Power-Token", token);
            if (payload != null) {
                c.setRequestMethod("POST"); c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                c.setDoOutput(true); try (java.io.OutputStream out = c.getOutputStream()) { out.write(payload.toString().getBytes(StandardCharsets.UTF_8)); }
            }
            int code = c.getResponseCode(); InputStream stream = code >= 400 ? c.getErrorStream() : c.getInputStream();
            if (stream == null) throw new java.io.IOException("Servidor respondeu " + code);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream in = stream) {
                byte[] buffer = new byte[4096]; int n;
                while ((n = in.read(buffer)) != -1) { if (bytes.size() + n > 2000000) throw new java.io.IOException("Resposta muito grande."); bytes.write(buffer, 0, n); }
            }
            JSONObject result;
            try { result = new JSONObject(bytes.toString("UTF-8")); }
            catch (Exception e) { throw new java.io.IOException("Resposta incompatível. Atualize a Nebula e o hub para 1.23."); }
            if (code < 200 || code >= 300) throw new java.io.IOException(result.optString("error", "Servidor respondeu " + code));
            return result;
        } finally { c.disconnect(); }
    }

    private void turboPanel() {
        content.addView(label("Painel do telefone",28,Color.WHITE));
        content.addView(label("Cada telefone pode manter seu próprio instrumento ou seguir o modo do servidor.",14,muted));
        devicePanel=new DevicePanelView(activity);
        String savedPanel=activity.getPreferences(Activity.MODE_PRIVATE).getString("instrument_panel","auto");
        String savedStyle=activity.getSharedPreferences("nebula", Activity.MODE_PRIVATE).getString("boost_style","cyber");
        LinearLayout styles= new LinearLayout(activity);
        styles.setOrientation(LinearLayout.HORIZONTAL);
        for (String[] option : new String[][]{{"Cyber Cyan","cyber"},{"NFS Heat","heat"},{"Toxic Lime","lime"}}) {
            Button choice=button(option[0],()->{
                activity.getSharedPreferences("nebula", Activity.MODE_PRIVATE).edit().putString("boost_style",option[1]).apply();
                devicePanel.setTurboStyle(option[1]);
            });
            choice.setTextSize(11);
            styles.addView(choice,new LinearLayout.LayoutParams(0,dp(44),1));
        }
        content.addView(label("Estilo do painel de boost",14,muted));
        content.addView(styles);
        LinearLayout choices=new LinearLayout(activity);choices.setOrientation(LinearLayout.HORIZONTAL);
        for(String[] option:new String[][]{{"Servidor","auto"},{"FuelTech","rpm"},{"Turbo neon","turbo"}}) {
            Button choice=button(option[0],()->{
                activity.getPreferences(Activity.MODE_PRIVATE).edit().putString("instrument_panel",option[1]).apply();
                devicePanel.setLocalMode(option[1]);
            });
            LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(0,dp(44),1);cp.setMargins(dp(3),dp(12),dp(3),dp(8));
            choices.addView(choice,cp);
        }
        content.addView(choices);
        content.addView(devicePanel,new LinearLayout.LayoutParams(-1,dp(330)));
        content.addView(button("Tela cheia",()->{
            android.content.Intent intent=new android.content.Intent(activity,TurboGaugeActivity.class);
            intent.putExtra("endpoints",pcs);intent.putExtra("token",token);activity.startActivity(intent);
        }));
        devicePanel.setTurboStyle(savedStyle);devicePanel.setLocalMode(savedPanel);devicePanel.start(pcs,token);
    }

    void setActive(boolean active) { boolean resumed=!this.active && active; this.active = active; if(!active)ui.removeCallbacks(mediaTicker); if(!active && devicePanel!=null)devicePanel.stop(); if(!active && turboTelemetry!=null) { turboTelemetry.close();turboTelemetry=null; } if (resumed && selected==3 && !closed) refreshMedia(); if (resumed && selected==4 && !closed) select(4); }
    private void updateText(TextView view, String value) { if (!view.getText().toString().equals(value)) view.setText(value); }
    void close() { if(devicePanel!=null)devicePanel.stop(); closed = true; generation++; if(turboTelemetry!=null)turboTelemetry.close(); network.shutdownNow(); ui.removeCallbacksAndMessages(null); }
}
