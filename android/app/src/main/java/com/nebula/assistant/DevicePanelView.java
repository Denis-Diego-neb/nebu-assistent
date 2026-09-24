package com.nebula.assistant;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.View;
import android.widget.FrameLayout;
import org.json.JSONObject;

/** Painel escolhido no PC, telefone ou preset; não cria leituras artificiais. */
final class DevicePanelView extends FrameLayout {
    private final TurboGaugeView turbo;
    private final RpmView rpm;
    private TurboTelemetryClient controlClient,turboClient;
    private String localMode;
    private String serverMode="manual";
    private JSONObject lastState;
    private String lastError;
    DevicePanelView(Context context) {
        super(context);setBackgroundColor(Color.BLACK);
        turbo=new TurboGaugeView(context);rpm=new RpmView(context);
        addView(turbo,new LayoutParams(-1,-1));addView(rpm,new LayoutParams(-1,-1));
        turbo.setVisibility(GONE);
    }
    void start(String[] endpoints,String token) {
        stop();
        turboClient=new TurboTelemetryClient(endpoints,token,turbo::update);
        controlClient=new TurboTelemetryClient(endpoints,token,"/api/control",(data,error)->{
            JSONObject state=data==null?null:data.optJSONObject("state");
            JSONObject devices=state==null?null:state.optJSONObject("devices");
            JSONObject mobile=devices==null?null:devices.optJSONObject("mobile");
            if(mobile!=null)serverMode=mobile.optString("mode","manual");
            lastState=state;lastError=error;
            renderSelectedMode();
        });
        turboClient.start();controlClient.start();
    }
    void setLocalMode(String mode) {
        localMode=(mode==null || mode.equals("auto"))?null:mode;
        renderSelectedMode();
    }
    private void renderSelectedMode() {
        String selected=localMode==null?serverMode:localMode;
        boolean showTurbo=selected.equals("turbo");
        turbo.setVisibility(showTurbo?VISIBLE:GONE);rpm.setVisibility(showTurbo?GONE:VISIBLE);
        rpm.update(lastState,selected,lastError);
    }
    void setTurboStyle(String style) { turbo.applyStyle(style); }
    void stop() {
        if(controlClient!=null)controlClient.close();
        if(turboClient!=null)turboClient.close();
        controlClient=null;turboClient=null;
    }
    private static final class RpmView extends View {
        private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        private final RectF rect=new RectF();
        private JSONObject data;
        private String mode="manual",error;
        RpmView(Context c){super(c);}
        void update(JSONObject value,String selected,String failure) {data=value;mode=selected;error=failure;invalidate();}
        private void text(Canvas c,String text,float x,float y,float size,int color) {
            paint.setColor(color);paint.setTextSize(size);paint.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
            paint.setTextAlign(Paint.Align.CENTER);c.drawText(text,x,y,paint);
        }
        private void leftText(Canvas c,String text,float x,float y,float size,int color) {
            paint.setColor(color);paint.setTextSize(size);paint.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
            paint.setTextAlign(Paint.Align.LEFT);c.drawText(text,x,y,paint);
        }
        @Override protected void onDraw(Canvas c) {
            c.drawColor(Color.rgb(5,7,8));float w=getWidth(),h=getHeight(),unit=Math.min(w/720f,h/330f);
            if(!mode.equals("rpm")) {
                text(c,error!=null?"PC indisponível":"Escolha FuelTech ou Turbo em Modos",w/2,h/2,20*unit,Color.LTGRAY);return;
            }
            boolean valid=data!=null && data.optBoolean("receiving") && data.optBoolean("telemetry_valid") && !data.isNull("rpm");
            double value=valid?data.optDouble("rpm"):0;
            double percent=valid?data.optDouble("rpm_percent",0):0;
            int cyan=Color.rgb(52,224,235),amber=Color.rgb(255,174,45),red=Color.rgb(255,55,62),muted=Color.rgb(116,127,130);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.2f*unit);paint.setColor(Color.rgb(38,50,53));
            rect.set(w*.025f,h*.035f,w*.975f,h*.965f);c.drawRoundRect(rect,8*unit,8*unit,paint);paint.setStyle(Paint.Style.FILL);
            leftText(c,"NEBULA  /  RACING DASH",w*.055f,h*.115f,13*unit,muted);
            text(c,valid?"TELEMETRIA AO VIVO":"AGUARDANDO ECU",w*.82f,h*.115f,12*unit,valid?cyan:amber);
            for(int i=0;i<24;i++) {
                float left=w*.055f+i*w*.0373f;
                boolean active=i*100/24<percent;
                int color=i>=21?red:i>=17?amber:cyan;
                paint.setColor(active?color:Color.rgb(21,29,31));
                rect.set(left,h*.17f,left+w*.028f,h*.285f);c.drawRoundRect(rect,2.5f*unit,2.5f*unit,paint);
            }
            leftText(c,"RPM",w*.06f,h*.43f,14*unit,muted);
            leftText(c,valid?String.format(java.util.Locale.US,"%.0f",value):"----",w*.055f,h*.73f,116*unit,Color.WHITE);
            paint.setColor(Color.rgb(12,18,20));rect.set(w*.70f,h*.35f,w*.94f,h*.78f);c.drawRoundRect(rect,7*unit,7*unit,paint);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(2*unit);paint.setColor(cyan);c.drawRoundRect(rect,7*unit,7*unit,paint);paint.setStyle(Paint.Style.FILL);
            text(c,"MARCHA",w*.82f,h*.44f,12*unit,muted);
            text(c,valid?data.optString("gear","-"):"-",w*.82f,h*.70f,72*unit,cyan);
            leftText(c,"VELOCIDADE",w*.06f,h*.86f,12*unit,muted);
            leftText(c,valid?String.format(java.util.Locale.US,"%.0f  km/h",data.optDouble("speed_kmh",0)):"SEM SINAL",w*.06f,h*.94f,24*unit,valid?Color.WHITE:amber);
            text(c,"SHIFT",w*.86f,h*.91f,12*unit,percent>=85?red:muted);
        }
    }
}
