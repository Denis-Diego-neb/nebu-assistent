package com.nebula.assistant;

import android.app.Notification;
import android.content.SharedPreferences;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Deque;

public class NebulaNotificationService extends NotificationListenerService {
    private static final Deque<JSONObject> recent = new ArrayDeque<>();

    @Override public void onNotificationPosted(StatusBarNotification sbn) {
        rebuildAndSync();
    }

    @Override public void onNotificationRemoved(StatusBarNotification sbn) { rebuildAndSync(); }
    @Override public void onListenerConnected() { super.onListenerConnected(); rebuildAndSync(); }

    private JSONObject item(StatusBarNotification sbn) throws Exception {
        Notification n=sbn.getNotification();
        CharSequence title=n.extras.getCharSequence(Notification.EXTRA_TITLE,"");
        CharSequence text=n.extras.getCharSequence(Notification.EXTRA_TEXT,"");
        JSONObject item=new JSONObject();
        item.put("app",getPackageManager().getApplicationLabel(getPackageManager().getApplicationInfo(sbn.getPackageName(),0)).toString());
        item.put("title",title==null?"":title.toString());
        item.put("text",text==null?"":text.toString());
        return item;
    }

    private void rebuildAndSync() {
        try {
            Deque<JSONObject> current=new ArrayDeque<>();
            StatusBarNotification[] active=getActiveNotifications();
            if(active!=null)for(StatusBarNotification notification:active){
                try{current.addLast(item(notification));while(current.size()>30)current.removeFirst();}catch(Exception ignored){}
            }
            synchronized(recent){recent.clear();recent.addAll(current);}
            syncInBackground(new JSONArray(current));
        } catch(Exception ignored) {}
    }

    private void syncInBackground(JSONArray notifications) {
        SharedPreferences prefs=getSharedPreferences("nebula",MODE_PRIVATE);
        String server=prefs.getString("server","").replaceAll("/+$","");
        String token=prefs.getString("token","");
        if(server.isEmpty()||token.isEmpty())return;
        new Thread(()->{try{
            HttpURLConnection connection=(HttpURLConnection)new URL(server+"/api/device").openConnection();
            connection.setConnectTimeout(10000);connection.setReadTimeout(15000);connection.setRequestMethod("POST");connection.setDoOutput(true);
            connection.setRequestProperty("X-Nebula-Token",token);connection.setRequestProperty("Content-Type","application/json; charset=utf-8");
            JSONObject body=new JSONObject();body.put("notifications",notifications);
            try(OutputStream output=connection.getOutputStream()){output.write(body.toString().getBytes(StandardCharsets.UTF_8));}
            connection.getResponseCode();connection.disconnect();
        }catch(Exception ignored){}}).start();
    }

    public static JSONArray snapshot() {
        synchronized (recent) { return new JSONArray(recent); }
    }
}
