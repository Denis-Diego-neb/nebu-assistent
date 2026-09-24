package com.nebula.assistant;

import android.app.Activity;
import android.graphics.Color;
import android.os.Bundle;
import android.view.View;
import android.view.WindowManager;

/** Mostrador horizontal, preto puro, toque para voltar. */
public final class TurboGaugeActivity extends Activity {
    private DevicePanelView gauge;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (android.os.Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().setStatusBarColor(Color.BLACK);getWindow().setNavigationBarColor(Color.BLACK);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN,WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        gauge=new DevicePanelView(this);
        gauge.setLocalMode(getIntent().getStringExtra("panel_mode"));
        gauge.setTurboStyle(getIntent().getStringExtra("turbo_style"));
        gauge.setOnClickListener(v->finish());setContentView(gauge);
        immersive();
    }
    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            |View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            |View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN|View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }
    @Override public void onWindowFocusChanged(boolean focus) { super.onWindowFocusChanged(focus);if(focus)immersive(); }
    @Override public void onResume() {
        super.onResume();
        String[] endpoints=getIntent().getStringArrayExtra("endpoints");
        String token=getIntent().getStringExtra("token");
        if(endpoints==null||token==null) { finish();return; }
        gauge.start(endpoints,token);
    }
    @Override public void onPause() { if(gauge!=null)gauge.stop();super.onPause(); }
}
