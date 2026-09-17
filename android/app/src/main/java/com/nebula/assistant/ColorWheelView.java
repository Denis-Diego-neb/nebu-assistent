package com.nebula.assistant;

import android.content.Context;
import android.graphics.*;
import android.view.MotionEvent;
import android.view.View;

/** HSV com envio apenas ao terminar o gesto. */
final class ColorWheelView extends View {
    interface Listener { void selected(String hex); }
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Listener listener;
    private float hue = 0, saturation = 0;
    ColorWheelView(Context context, Listener listener) {
        super(context); this.listener = listener;
        setContentDescription("Roda de cores do abajur");
    }
    @Override protected void onDraw(Canvas canvas) {
        float x=getWidth()/2f, y=getHeight()/2f, radius=Math.min(x,y)-8;
        paint.setStyle(Paint.Style.FILL);
        paint.setShader(new SweepGradient(x,y,new int[]{Color.RED,Color.YELLOW,Color.GREEN,Color.CYAN,Color.BLUE,Color.MAGENTA,Color.RED},null));
        canvas.drawCircle(x,y,radius,paint);
        paint.setShader(new RadialGradient(x,y,radius,Color.WHITE,Color.TRANSPARENT,Shader.TileMode.CLAMP));
        canvas.drawCircle(x,y,radius,paint); paint.setShader(null);
        float px=x+(float)Math.cos(Math.toRadians(hue))*saturation*radius;
        float py=y+(float)Math.sin(Math.toRadians(hue))*saturation*radius;
        paint.setColor(Color.BLACK); paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(6);
        canvas.drawCircle(px,py,10,paint); paint.setColor(Color.WHITE); paint.setStrokeWidth(3);
        canvas.drawCircle(px,py,10,paint);
    }
    @Override public boolean onTouchEvent(MotionEvent event) {
        if (event.getActionMasked()==MotionEvent.ACTION_CANCEL) { getParent().requestDisallowInterceptTouchEvent(false); return true; }
        float dx=event.getX()-getWidth()/2f, dy=event.getY()-getHeight()/2f;
        saturation=Math.min(1,(float)Math.hypot(dx,dy)/(Math.min(getWidth(),getHeight())/2f-8));
        hue=((float)Math.toDegrees(Math.atan2(dy,dx))+360)%360;
        invalidate();
        if (event.getActionMasked()==MotionEvent.ACTION_DOWN) getParent().requestDisallowInterceptTouchEvent(true);
        if (event.getActionMasked()==MotionEvent.ACTION_UP) {
            getParent().requestDisallowInterceptTouchEvent(false); performClick();
            listener.selected(String.format(java.util.Locale.ROOT,"%06X",Color.HSVToColor(new float[]{hue,saturation,1}) & 0xFFFFFF));
        }
        return true;
    }
    @Override public boolean performClick() { super.performClick(); return true; }
}
