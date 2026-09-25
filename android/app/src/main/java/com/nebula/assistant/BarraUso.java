package com.nebula.assistant;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/** Barra de uso de uma janela de limite: cor da nebulosa, alerta a partir de 80%. */
final class BarraUso extends View {
    private final Paint trilho = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint cheio = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF forma = new RectF();
    private float fracao = -1;

    BarraUso(Context contexto) {
        super(contexto);
        trilho.setColor(Color.argb(0x2E, 255, 255, 255));
        Tema.seguir(this, (v, a) -> ((BarraUso) v).invalidate());
    }

    /** {@code pct} de 0 a 100; negativo quando não há dado — a barra fica vazia, sem inventar. */
    void definir(double pct) {
        fracao = pct < 0 ? -1 : (float) Math.max(0, Math.min(1, pct / 100.0));
        invalidate();
    }

    @Override
    protected void onDraw(Canvas c) {
        float r = getHeight() / 2f;
        forma.set(0, 0, getWidth(), getHeight());
        c.drawRoundRect(forma, r, r, trilho);
        if (fracao <= 0) return;
        cheio.setColor(fracao >= .8f ? Tema.ALERTA : Tema.acento().botao);
        forma.set(0, 0, Math.max(getHeight(), getWidth() * fracao), getHeight());
        c.drawRoundRect(forma, r, r, cheio);
    }
}
