package com.nebula.assistant;

import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import org.json.JSONObject;
import java.net.HttpURLConnection;
import java.net.URL;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class TurboTelemetryClient {
    interface Listener { void update(JSONObject data,String error); }
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final String[] endpoints;
    private final String token;
    private final Listener listener;
    private final String path;
    private volatile boolean closed;
    private boolean busy, stale;
    private long lastData;
    private String cached;

    TurboTelemetryClient(String[] endpoints,String token,Listener listener) {
        this(endpoints,token,"/api/beamng/turbo",listener);
    }
    TurboTelemetryClient(String[] endpoints,String token,String path,Listener listener) {
        this.endpoints=endpoints;this.token=token;this.listener=listener;
        this.path=path;
    }
    void start() { ui.post(tick); }
    private final Runnable tick=new Runnable() {
        public void run() {
            if(closed)return;
            if(!stale && SystemClock.elapsedRealtime()-lastData>1500) {
                stale=true;listener.update(null,"timeout");
            }
            if(!busy) {
                busy=true;
                worker.execute(()->{
                    JSONObject data=null;String error=null;
                    try { data=fetch(); } catch(Exception e) { error=e.getMessage();cached=null; }
                    final JSONObject result=data;final String message=error;
                    ui.post(()->{
                        busy=false;if(closed)return;
                        if(result!=null) { lastData=SystemClock.elapsedRealtime();stale=false; }
                        listener.update(result,message);
                    });
                });
            }
            ui.postDelayed(this,250);
        }
    };
    private JSONObject fetch() throws Exception {
        if(cached!=null) return request(cached);
        Exception failure=null;
        for(String endpoint:endpoints) {
            if(closed)break;
            try { JSONObject data=request(endpoint);cached=endpoint;return data; }
            catch(Exception e) { failure=e; }
        }
        throw failure!=null?failure:new java.io.IOException("PC indisponível");
    }
    private JSONObject request(String endpoint) throws Exception {
        HttpURLConnection c=(HttpURLConnection)new URL(endpoint+path).openConnection();
        try {
            c.setConnectTimeout(800);c.setReadTimeout(1200);c.setInstanceFollowRedirects(false);
            c.setRequestProperty("X-Nebula-Power-Token",token);
            if(c.getResponseCode()!=200)throw new java.io.IOException("Atualize a Nebula no PC.");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(InputStream in=c.getInputStream()) {
                byte[] buffer=new byte[1024];int n;
                while((n=in.read(buffer))!=-1) {
                    if(bytes.size()+n>16000)throw new java.io.IOException("Resposta inválida.");
                    bytes.write(buffer,0,n);
                }
            }
            return new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8));
        } finally { c.disconnect(); }
    }
    void close() { closed=true;ui.removeCallbacksAndMessages(null);worker.shutdownNow(); }
}
