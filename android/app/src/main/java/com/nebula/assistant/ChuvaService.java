package com.nebula.assistant;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.media.AudioAttributes;
import android.media.AudioFormat;
import android.media.AudioTrack;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/**
 * Modo chuva no celular: toca os trovões junto com o notebook e encerra o modo
 * quando o celular é desbloqueado. O relâmpago é só do abajur: aqui nada acende.
 * O hub é o relógio da noite; a diferença de relógio sai do tempo de ida e volta
 * da consulta mais rápida.
 */
public class ChuvaService extends Service {
    private static final String CANAL = "nebula_chuva";
    private static final String EXTRA_HUB = "hub", EXTRA_TOKEN = "token";
    private static final int NOTIFICACAO = 23;
    private static volatile boolean emExecucao;

    private volatile boolean rodando;
    private volatile long deslocamentoMs;
    private long melhorIdaMs = Long.MAX_VALUE;
    private volatile JSONArray trovoes = new JSONArray();
    private final Set<Long> tocados = Collections.synchronizedSet(new HashSet<>());
    private String hub, token;
    private PowerManager.WakeLock acordado;
    private BroadcastReceiver desbloqueio;

    static boolean ativo() { return emExecucao; }

    static void iniciar(Context contexto, String hub, String token) {
        contexto.startForegroundService(new Intent(contexto, ChuvaService.class)
            .putExtra(EXTRA_HUB, hub).putExtra(EXTRA_TOKEN, token));
    }

    static void parar(Context contexto) {
        contexto.stopService(new Intent(contexto, ChuvaService.class));
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        // O sistema exige a notificação logo depois de startForegroundService.
        mostrarNotificacao();
        if (intent != null && intent.getStringExtra(EXTRA_HUB) != null) {
            hub = intent.getStringExtra(EXTRA_HUB).replaceAll("/+$", "");
            token = intent.getStringExtra(EXTRA_TOKEN);
        }
        if (hub == null || token == null) { stopSelf(); return START_NOT_STICKY; }
        if (!rodando) {
            rodando = true;
            emExecucao = true;
            PowerManager energia = (PowerManager) getSystemService(POWER_SERVICE);
            acordado = energia.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Nebula:chuva");
            acordado.acquire(16L * 60 * 60 * 1000);
            desbloqueio = new BroadcastReceiver() {
                @Override public void onReceive(Context contexto, Intent recebido) { encerrarPeloCelular(); }
            };
            IntentFilter filtro = new IntentFilter(Intent.ACTION_USER_PRESENT);
            if (Build.VERSION.SDK_INT >= 33) registerReceiver(desbloqueio, filtro, Context.RECEIVER_NOT_EXPORTED);
            else registerReceiver(desbloqueio, filtro);
            new Thread(this::laco, "NebulaChuva").start();
        }
        return START_REDELIVER_INTENT;
    }

    private void mostrarNotificacao() {
        NotificationManager gerente = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        gerente.createNotificationChannel(new NotificationChannel(CANAL, "Modo chuva", NotificationManager.IMPORTANCE_LOW));
        PendingIntent abrir = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
            PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification aviso = new Notification.Builder(this, CANAL)
            .setSmallIcon(android.R.drawable.ic_media_play)
            .setContentTitle("Modo chuva ativo")
            .setContentText("Desbloqueie o celular para encerrar.")
            .setOngoing(true)
            .setContentIntent(abrir)
            .build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIFICACAO, aviso, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        else startForeground(NOTIFICACAO, aviso);
    }

    private void laco() {
        long proximaConsulta = 0;
        while (rodando) {
            long agora = System.currentTimeMillis();
            if (agora >= proximaConsulta) {
                try { consultar(); proximaConsulta = agora + 20000; }
                catch (Exception falha) { proximaConsulta = agora + 5000; }
            }
            tocarPendentes();
            try { Thread.sleep(100); } catch (InterruptedException interrompido) { break; }
        }
    }

    private void consultar() throws Exception {
        long ida = System.currentTimeMillis();
        JSONObject chuva = pedir("/chuva", null);
        long volta = System.currentTimeMillis();
        if (!chuva.optBoolean("ativo")) { rodando = false; stopSelf(); return; }
        long percurso = volta - ida;
        if (melhorIdaMs == Long.MAX_VALUE || percurso <= melhorIdaMs + melhorIdaMs / 2) {
            melhorIdaMs = Math.min(melhorIdaMs, percurso);
            deslocamentoMs = Math.round(chuva.getDouble("agora") * 1000) - (ida + volta) / 2;
        }
        JSONArray lista = chuva.optJSONArray("trovoes");
        trovoes = lista != null ? lista : new JSONArray();
    }

    private void tocarPendentes() {
        JSONArray lista = trovoes;
        long agoraHub = System.currentTimeMillis() + deslocamentoMs;
        for (int i = 0; i < lista.length(); i++) {
            JSONObject trovao = lista.optJSONObject(i);
            if (trovao == null) continue;
            long som = Math.round(trovao.optDouble("som") * 1000);
            // Sintetiza 1,5 s antes; atrasado demais, deixa passar.
            if (agoraHub < som - 1500 || agoraHub > som + 2000 || !tocados.add(som)) continue;
            double intensidade = trovao.optDouble("intensidade", 0.7);
            long semente = trovao.optLong("semente");
            new Thread(() -> tocar(som, semente, intensidade), "NebulaTrovao").start();
        }
    }

    private void tocar(long somHub, long semente, double intensidade) {
        short[] pcm = Trovao.sintetizar(semente, intensidade);
        AudioTrack faixa = null;
        try {
            faixa = new AudioTrack.Builder()
                .setAudioAttributes(new AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
                .setAudioFormat(new AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(Trovao.TAXA)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
                .setTransferMode(AudioTrack.MODE_STATIC)
                .setBufferSizeInBytes(pcm.length * 2)
                .build();
            faixa.write(pcm, 0, pcm.length);
            long espera = somHub - (System.currentTimeMillis() + deslocamentoMs);
            if (espera > 0) Thread.sleep(espera);
            if (!rodando) return;
            faixa.play();
            Thread.sleep(pcm.length * 1000L / Trovao.TAXA + 300);
        } catch (Exception ignorado) {
            // Um trovão perdido não derruba o modo.
        } finally {
            if (faixa != null) faixa.release();
        }
    }

    private void encerrarPeloCelular() {
        if (!rodando) return;
        rodando = false;
        new Thread(() -> {
            for (int tentativa = 0; tentativa < 3; tentativa++) {
                try {
                    pedir("/control", new JSONObject().put("action", "chuva.parar")
                        .put("value", new JSONObject().put("origem", "celular")));
                    break;
                } catch (Exception falha) {
                    try { Thread.sleep(2000); } catch (InterruptedException interrompido) { break; }
                }
            }
            stopSelf();
        }, "NebulaChuvaFim").start();
    }

    private JSONObject pedir(String caminho, JSONObject corpo) throws Exception {
        HttpURLConnection conexao = (HttpURLConnection) new URL(hub + caminho).openConnection();
        try {
            conexao.setConnectTimeout(Rede.conexaoMs(hub));
            conexao.setReadTimeout(corpo != null ? 15000 : 8000);
            conexao.setRequestProperty("X-Nebula-Power-Token", token);
            if (corpo != null) {
                conexao.setRequestMethod("POST");
                conexao.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                conexao.setDoOutput(true);
                try (OutputStream saida = conexao.getOutputStream()) {
                    saida.write(corpo.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            int codigo = conexao.getResponseCode();
            InputStream entrada = codigo >= 400 ? conexao.getErrorStream() : conexao.getInputStream();
            if (entrada == null) throw new java.io.IOException("Hub respondeu " + codigo);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream fluxo = entrada) {
                byte[] buffer = new byte[4096];
                int lidos;
                while ((lidos = fluxo.read(buffer)) != -1) {
                    if (bytes.size() + lidos > 500000) throw new java.io.IOException("Resposta muito grande.");
                    bytes.write(buffer, 0, lidos);
                }
            }
            if (codigo >= 400) throw new java.io.IOException("Hub respondeu " + codigo);
            return new JSONObject(bytes.toString("UTF-8"));
        } finally {
            conexao.disconnect();
        }
    }

    @Override public void onDestroy() {
        rodando = false;
        emExecucao = false;
        if (desbloqueio != null) {
            try { unregisterReceiver(desbloqueio); } catch (IllegalArgumentException jaRemovido) { }
            desbloqueio = null;
        }
        if (acordado != null && acordado.isHeld()) acordado.release();
        super.onDestroy();
    }
}
