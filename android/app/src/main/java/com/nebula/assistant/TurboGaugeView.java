package com.nebula.assistant;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.BlurMaskFilter;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.os.SystemClock;
import android.view.View;
import org.json.JSONObject;
import java.util.Locale;

/** Manometro AMOLED: nenhum preenchimento fora dos elementos do instrumento. */
final class TurboGaugeView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int neon = Color.rgb(20,225,255);
    private int hot = Color.rgb(255,72,145);
    private int background = Color.rgb(2,5,8);
    private boolean valid;
    private float value, needle, scale = 3;
    private long lastFrame;
    private String status = "Aguardando BeamNG";

    TurboGaugeView(Context context) {
        super(context); setBackgroundColor(Color.BLACK); setLayerType(View.LAYER_TYPE_SOFTWARE,null);
        glow.setStyle(Paint.Style.STROKE);glow.setStrokeCap(Paint.Cap.ROUND);
        applyStyle(context.getSharedPreferences("nebula", Context.MODE_PRIVATE).getString("boost_style", "cyber"));
    }

    void applyStyle(String style) {
        if ("heat".equals(style)) {
            neon = Color.rgb(255, 92, 24); hot = Color.rgb(255, 20, 78); background = Color.rgb(13, 3, 5);
        } else if ("lime".equals(style)) {
            neon = Color.rgb(166, 255, 54); hot = Color.rgb(255, 214, 48); background = Color.rgb(3, 10, 6);
        } else {
            neon = Color.rgb(20, 225, 255); hot = Color.rgb(255, 72, 145); background = Color.rgb(2, 5, 8);
        }
        invalidate();
    }

    void update(JSONObject data, String error) {
        boolean nextValid = data != null && data.optBoolean("valid") && data.optBoolean("has_turbo")
            && !data.isNull("turbo_bar") && Double.isFinite(data.optDouble("turbo_bar"));
        valid = nextValid;
        if (valid) {
            value = (float)data.optDouble("turbo_bar");
            float maximum = (float)data.optDouble("max_turbo_bar",3);
            scale = Math.max(3, Math.min(20, (float)Math.ceil(Math.max(maximum,value))));
            status = "BEAMNG · AO VIVO";
        } else {
            status = error != null ? "PC indisponível" : data != null && "no_turbo".equals(data.optString("status"))
                ? "Veículo sem turbo" : "Aguardando BeamNG";
            needle = 0;
        }
        setContentDescription(valid ? String.format(Locale.ROOT,"Pressão do turbo: %.2f bar",value) : status);
        invalidate();
    }

    private void text(Canvas canvas, String text, float x, float y, float size, int color) {
        paint.setStyle(Paint.Style.FILL); paint.setColor(color); paint.setTextSize(size);
        paint.setTextAlign(Paint.Align.CENTER); paint.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
        canvas.drawText(text,x,y,paint);
    }

    private void neonArc(Canvas canvas, RectF arc, float start, float sweep, float width, int color) {
        glow.setColor(color);glow.setStrokeWidth(width*2.5f);glow.setMaskFilter(new BlurMaskFilter(width*2.3f,BlurMaskFilter.Blur.NORMAL));
        canvas.drawArc(arc,start,sweep,false,glow);
        glow.setMaskFilter(null);glow.setStrokeWidth(width);canvas.drawArc(arc,start,sweep,false,glow);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(background);
        float radius = Math.min(getWidth()*.43f,getHeight()*.41f);
        float cx=getWidth()/2f, cy=getHeight()*.49f;
        long now=SystemClock.elapsedRealtime();
        float dt=lastFrame==0 ? .05f : Math.min(.1f,(now-lastFrame)/1000f); lastFrame=now;
        if(valid) needle += (value-needle)*(1f-(float)Math.exp(-dt/.09f));
        paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(Math.max(1,radius*.006f));
        paint.setColor(Color.rgb(28,42,48));
        RectF arc=new RectF(cx-radius,cy-radius,cx+radius,cy+radius);
        canvas.drawArc(arc,150,240,false,paint);
        if(valid) {
            float sweep=Math.max(0,Math.min(1,needle/scale))*240;
            neonArc(canvas,arc,150,sweep,radius*.013f,needle/scale>.82f?hot:neon);
        }
        for(int i=0;i<=30;i++) {
            double angle=Math.toRadians(150+i*8);
            boolean major=i%5==0;
            float inner=radius*(major?.89f:.95f);
            paint.setColor(major?Color.rgb(196,223,227):Color.rgb(48,70,76));
            paint.setStrokeWidth(radius*(major?.011f:.005f));
            canvas.drawLine(cx+inner*(float)Math.cos(angle),cy+inner*(float)Math.sin(angle),
                cx+radius*(float)Math.cos(angle),cy+radius*(float)Math.sin(angle),paint);
            if(major) text(canvas,String.format(Locale.ROOT,"%.1f",i*scale/30),
                cx+radius*.75f*(float)Math.cos(angle),cy+radius*.75f*(float)Math.sin(angle)+radius*.035f,
                radius*.105f,Color.rgb(190,215,220));
            paint.setStyle(Paint.Style.STROKE);
        }
        text(canvas,"BOOST PRESSURE",cx,cy-radius*.36f,radius*.09f,neon);
        if(valid) {
            float angle=150+Math.max(0,Math.min(1,needle/scale))*240;
            int needleColor=needle/scale>.82f?hot:neon;
            glow.setColor(needleColor);glow.setStrokeWidth(radius*.06f);glow.setMaskFilter(new BlurMaskFilter(radius*.055f,BlurMaskFilter.Blur.NORMAL));
            canvas.drawLine(cx,cy,cx+radius*.84f*(float)Math.cos(Math.toRadians(angle)),cy+radius*.84f*(float)Math.sin(Math.toRadians(angle)),glow);
            glow.setMaskFilter(null);
            paint.setColor(needleColor); paint.setStrokeWidth(radius*.014f); paint.setStrokeCap(Paint.Cap.ROUND);
            canvas.drawLine(cx,cy,cx+radius*.84f*(float)Math.cos(Math.toRadians(angle)),
                cy+radius*.84f*(float)Math.sin(Math.toRadians(angle)),paint);
            paint.setStyle(Paint.Style.FILL); canvas.drawCircle(cx,cy,radius*.045f,paint);
            paint.setStrokeCap(Paint.Cap.BUTT);
        }
        text(canvas,valid?String.format(Locale.ROOT,"%.2f",value):"—",cx,cy+radius*.43f,radius*.31f,valid && needle/scale>.82f?hot:neon);
        text(canvas,"bar",cx,cy+radius*.59f,radius*.105f,Color.rgb(170,170,170));
        text(canvas,status,cx,cy+radius*.91f,radius*.075f,Color.rgb(130,130,130));
        if(valid && Math.abs(value-needle)>.002f) postInvalidateOnAnimation();
    }
}
