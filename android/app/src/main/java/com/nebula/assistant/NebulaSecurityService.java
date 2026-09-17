package com.nebula.assistant;

import android.app.*;
import android.app.admin.DevicePolicyManager;
import android.content.*;
import android.graphics.Color;
import android.hardware.camera2.CameraManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.media.AudioManager;
import android.os.*;
import android.view.KeyEvent;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;

/** Mantém telemetria e comandos antirroubo ativos com uma notificação visível. */
public class NebulaSecurityService extends Service {
    private volatile boolean running;
    private SharedPreferences prefs;
    private Location currentLocation;
    private final LocationListener locationListener=new LocationListener(){@Override public void onLocationChanged(Location location){currentLocation=location;}@Override public void onStatusChanged(String provider,int status,Bundle extras){}@Override public void onProviderEnabled(String provider){}@Override public void onProviderDisabled(String provider){}};
    private static final String CHANNEL="nebula_security";

    @Override public void onCreate(){
        super.onCreate();prefs=getSharedPreferences("nebula",MODE_PRIVATE);running=true;
        NotificationManager nm=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);
        if(Build.VERSION.SDK_INT>=26)nm.createNotificationChannel(new NotificationChannel(CHANNEL,"Proteção Nebula",NotificationManager.IMPORTANCE_LOW));
        Intent open=new Intent(this,MainActivity.class);PendingIntent pending=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);
        Notification notification=new Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_lock_idle_lock).setColor(Color.rgb(39,140,245)).setContentTitle("Proteção Nebula ativa").setContentText("Salvando a última localização e aguardando comandos.").setOngoing(true).setContentIntent(pending).build();
        startForeground(17,notification);
        startLocationUpdates();
        new Thread(this::loop,"NebulaSecurity").start();
    }

    private void startLocationUpdates(){try{LocationManager lm=(LocationManager)getSystemService(LOCATION_SERVICE);lm.requestLocationUpdates(LocationManager.GPS_PROVIDER,30000,10,locationListener);lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER,30000,10,locationListener);}catch(Exception ignored){}}

    private void loop(){
        while(running){
            try{String token=prefs.getString("token","");String base=prefs.getString("server","").replaceAll("/+$","");if(!token.isEmpty()&&!base.isEmpty()){postDevice(base,token);pollCommands(base,token);}}catch(Exception ignored){}
            try{Thread.sleep(5000);}catch(InterruptedException e){Thread.currentThread().interrupt();break;}
        }
    }

    private void postDevice(String base,String token)throws Exception{
        JSONObject state=new JSONObject();BatteryManager bm=(BatteryManager)getSystemService(BATTERY_SERVICE);state.put("battery",bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY));state.put("charging",bm.isCharging());state.put("notifications",NebulaNotificationService.snapshot());
        Location location=lastLocation();if(location!=null){state.put("latitude",location.getLatitude());state.put("longitude",location.getLongitude());state.put("accuracy",location.getAccuracy());state.put("location_updated_at",location.getTime()/1000.0);}
        request(base+"/api/device","POST",state,token);
    }

    private Location lastLocation(){
        try{LocationManager lm=(LocationManager)getSystemService(LOCATION_SERVICE);Location gps=lm.getLastKnownLocation(LocationManager.GPS_PROVIDER),net=lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER),best=currentLocation;if(gps!=null&&(best==null||gps.getTime()>best.getTime()))best=gps;if(net!=null&&(best==null||net.getTime()>best.getTime()))best=net;return best;}catch(SecurityException e){return null;}
    }

    private void pollCommands(String base,String token)throws Exception{
        int last=prefs.getInt("last_device_command",0);JSONObject result=request(base+"/api/device/commands?after="+last,"GET",null,token);JSONArray commands=result.optJSONArray("commands");if(commands==null)return;
        for(int i=0;i<commands.length();i++){JSONObject item=commands.optJSONObject(i);if(item==null)continue;int id=item.optInt("id");try{execute(item.optString("action"));}catch(Exception ignored){}last=Math.max(last,id);prefs.edit().putInt("last_device_command",last).apply();}
    }

    private void execute(String action)throws Exception{
        if(action.startsWith("media_")){AudioManager am=(AudioManager)getSystemService(AUDIO_SERVICE);int key=action.equals("media_next")?KeyEvent.KEYCODE_MEDIA_NEXT:action.equals("media_previous")?KeyEvent.KEYCODE_MEDIA_PREVIOUS:KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE;am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_DOWN,key));am.dispatchMediaKeyEvent(new KeyEvent(KeyEvent.ACTION_UP,key));}
        else if(action.startsWith("flashlight_")){CameraManager cm=(CameraManager)getSystemService(CAMERA_SERVICE);cm.setTorchMode(cm.getCameraIdList()[0],action.endsWith("on"));}
        else if(action.equals("lock_nebula")){prefs.edit().putBoolean("lost_mode",true).apply();DevicePolicyManager dpm=(DevicePolicyManager)getSystemService(DEVICE_POLICY_SERVICE);ComponentName admin=new ComponentName(this,NebulaDeviceAdminReceiver.class);if(dpm.isAdminActive(admin))dpm.lockNow();}
        else if(action.equals("unlock_nebula")){prefs.edit().putBoolean("lost_mode",false).apply();}
    }

    private JSONObject request(String address,String method,JSONObject body,String token)throws Exception{
        HttpURLConnection c=(HttpURLConnection)new URL(address).openConnection();try{c.setConnectTimeout(10000);c.setReadTimeout(15000);c.setRequestMethod(method);c.setRequestProperty("X-Nebula-Token",token);c.setRequestProperty("Accept","application/json");if(body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json; charset=utf-8");try(OutputStream out=c.getOutputStream()){out.write(body.toString().getBytes(StandardCharsets.UTF_8));}}int code=c.getResponseCode();InputStream in=code<400?c.getInputStream():c.getErrorStream();String text=read(in);if(code>=400)throw new IOException("HTTP "+code);return new JSONObject(text.isEmpty()?"{}":text);}finally{c.disconnect();}
    }

    private String read(InputStream in)throws IOException{if(in==null)return "";ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))>0)out.write(buffer,0,n);return out.toString("UTF-8");}
    @Override public int onStartCommand(Intent intent,int flags,int startId){return START_STICKY;}
    @Override public void onDestroy(){running=false;try{((LocationManager)getSystemService(LOCATION_SERVICE)).removeUpdates(locationListener);}catch(Exception ignored){}super.onDestroy();}
    @Override public android.os.IBinder onBind(Intent intent){return null;}
}
