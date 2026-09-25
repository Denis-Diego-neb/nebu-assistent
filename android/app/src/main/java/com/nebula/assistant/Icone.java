package com.nebula.assistant;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.view.View;

/**
 * Ícones de traço único desenhados em vetor.
 *
 * <p>A barra antiga usava símbolos de fonte (⌂ ▯ ◎ ♫) e cada um saía de uma
 * fonte diferente do Android — um deles nem renderizava. Desenhados aqui, todos
 * têm o mesmo traço, o mesmo tamanho e a cor da nebulosa.</p>
 */
final class Icone extends View {
    enum Tipo { MENU, INICIO, DISPOSITIVOS, AUDIO, DUPLA, PAINEL, ARENA, CONFIG, FECHAR }

    private final Tipo tipo;
    private final Paint traco = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path caminho = new Path();
    private final RectF oval = new RectF();

    Icone(Context contexto, Tipo tipo) {
        super(contexto);
        this.tipo = tipo;
        traco.setStyle(Paint.Style.STROKE);
        traco.setStrokeCap(Paint.Cap.ROUND);
        traco.setStrokeJoin(Paint.Join.ROUND);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        Tema.seguir(this, (v, a) -> ((Icone) v).colorir(a.texto));
    }

    void colorir(int cor) {
        traco.setColor(cor);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas c) {
        float s = Math.min(getWidth(), getHeight());
        float x0 = (getWidth() - s) / 2f, y0 = (getHeight() - s) / 2f;
        c.save();
        c.translate(x0, y0);
        c.scale(s / 24f, s / 24f);
        traco.setStrokeWidth(1.8f);
        caminho.reset();
        switch (tipo) {
            case MENU:
                linha(c, 4, 7, 20, 7); linha(c, 4, 12, 20, 12); linha(c, 4, 17, 20, 17);
                break;
            case FECHAR:
                linha(c, 6, 6, 18, 18); linha(c, 18, 6, 6, 18);
                break;
            case INICIO:
                caminho.moveTo(4, 11); caminho.lineTo(12, 4); caminho.lineTo(20, 11);
                caminho.moveTo(6, 9.5f); caminho.lineTo(6, 20); caminho.lineTo(18, 20); caminho.lineTo(18, 9.5f);
                caminho.moveTo(10, 20); caminho.lineTo(10, 14); caminho.lineTo(14, 14); caminho.lineTo(14, 20);
                c.drawPath(caminho, traco);
                break;
            case DISPOSITIVOS:
                // Três controles deslizantes: aparelhos e os modos deles.
                linha(c, 5, 7, 19, 7); linha(c, 5, 12, 19, 12); linha(c, 5, 17, 19, 17);
                ponto(c, 9, 7); ponto(c, 15, 12); ponto(c, 11, 17);
                break;
            case AUDIO:
                caminho.moveTo(9, 17); caminho.lineTo(9, 6); caminho.lineTo(18, 4.5f); caminho.lineTo(18, 15);
                c.drawPath(caminho, traco);
                oval.set(4.5f, 14.5f, 9.5f, 19.5f); c.drawOval(oval, traco);
                oval.set(13.5f, 12.5f, 18.5f, 17.5f); c.drawOval(oval, traco);
                break;
            case DUPLA:
                // Dois balões de conversa sobrepostos: você e as duas.
                oval.set(3, 5, 14, 14); c.drawRoundRect(oval, 3.5f, 3.5f, traco);
                caminho.moveTo(6, 14); caminho.lineTo(5, 17.5f); caminho.lineTo(9, 14);
                caminho.moveTo(14, 9); caminho.lineTo(18, 9); caminho.quadTo(21, 9, 21, 12);
                caminho.lineTo(21, 15); caminho.quadTo(21, 18, 18, 18); caminho.lineTo(17, 18);
                caminho.lineTo(18, 20.5f); caminho.lineTo(14.5f, 18); caminho.lineTo(12, 18);
                caminho.quadTo(9.5f, 18, 9.5f, 15.5f);
                c.drawPath(caminho, traco);
                break;
            case PAINEL:
                // Órbita em volta de um astro: o painel completo do Espaço.
                c.drawCircle(12, 12, 3, traco);
                c.save(); c.rotate(-28, 12, 12);
                oval.set(2.5f, 8, 21.5f, 16); c.drawOval(oval, traco);
                c.restore();
                break;
            case CONFIG:
                // Engrenagem: miolo, aro e oito dentes.
                c.drawCircle(12, 12, 3, traco);
                c.drawCircle(12, 12, 6.5f, traco);
                for (int i = 0; i < 8; i++) {
                    double a = Math.PI / 4 * i;
                    linha(c, 12 + (float) Math.cos(a) * 6.5f, 12 + (float) Math.sin(a) * 6.5f,
                            12 + (float) Math.cos(a) * 9.2f, 12 + (float) Math.sin(a) * 9.2f);
                }
                break;
            case ARENA:
                // Frasco de laboratório: arena e experimentos.
                caminho.moveTo(10, 4); caminho.lineTo(10, 10); caminho.lineTo(5, 19);
                caminho.quadTo(4.5f, 20, 6, 20); caminho.lineTo(18, 20); caminho.quadTo(19.5f, 20, 19, 19);
                caminho.lineTo(14, 10); caminho.lineTo(14, 4);
                caminho.moveTo(8.5f, 4); caminho.lineTo(15.5f, 4);
                caminho.moveTo(7.5f, 15); caminho.lineTo(16.5f, 15);
                c.drawPath(caminho, traco);
                break;
        }
        c.restore();
    }

    private void linha(Canvas c, float x1, float y1, float x2, float y2) {
        c.drawLine(x1, y1, x2, y2, traco);
    }

    private void ponto(Canvas c, float x, float y) {
        Paint.Style antes = traco.getStyle();
        traco.setStyle(Paint.Style.FILL_AND_STROKE);
        c.drawCircle(x, y, 1.9f, traco);
        traco.setStyle(antes);
    }
}
