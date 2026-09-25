package com.nebula.assistant;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.View;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.Map;
import java.util.WeakHashMap;

/**
 * Paleta espacial das telas nativas.
 *
 * <p>Não há mais cor de destaque fixa: o dourado antigo virou a cor da própria
 * nebulosa. {@link NebulaSkyView} lê o gás e chama {@link #definirMatiz}, e
 * tudo que foi registrado com {@link #seguir} se repinta. Os cartões não têm
 * cor: são vidro fosco, desenhado pelo céu por trás deles.</p>
 */
final class Tema {
    private Tema() { }

    static final int TEXTO = Color.rgb(237, 237, 247);
    static final int SUAVE = Color.rgb(176, 170, 200);
    static final int ALERTA = Color.rgb(255, 200, 145);

    /** Cores derivadas de um matiz, no mesmo espírito do --accent do front web. */
    static final class Acento {
        final float matiz;
        final int texto, botao, botaoTexto, borda;

        Acento(float h) {
            matiz = h;
            texto = hsl(h, .72f, .80f);
            botao = hsl(h, .62f, .82f);
            botaoTexto = hsl(h, .35f, .13f);
            int b = hsl(h, .65f, .72f);
            borda = Color.argb(0x5C, Color.red(b), Color.green(b), Color.blue(b));
        }
    }

    interface Pintor { void pintar(View v, Acento a); }

    /** Lilás do visual novo até a primeira leitura do céu. */
    private static Acento atual = new Acento(252f);
    /** Chave fraca: a tela fechada sai sozinha. O pintor não pode segurar a view. */
    private static final Map<View, Pintor> PINTORES = new WeakHashMap<>();

    static Acento acento() { return atual; }

    static <V extends View> V seguir(V v, Pintor p) {
        PINTORES.put(v, p);
        p.pintar(v, atual);
        return v;
    }

    /** Chamado pelo céu, na thread principal. Mudança imperceptível não repinta. */
    static void definirMatiz(float h) {
        float diferenca = Math.abs(((h - atual.matiz + 540f) % 360f) - 180f);
        if (diferenca < 1.5f) return;
        atual = new Acento(h);
        for (Map.Entry<View, Pintor> e : new ArrayList<>(PINTORES.entrySet())) {
            if (e.getKey() != null) e.getValue().pintar(e.getKey(), atual);
        }
    }

    /** Texto de destaque: sobrelinhas, nomes, rótulos. */
    static <T extends TextView> T destaque(T v) {
        return seguir(v, (x, a) -> ((TextView) x).setTextColor(a.texto));
    }

    /** Botão principal na cor do céu, com texto escuro do mesmo matiz. */
    static <T extends TextView> T botao(T v, int raioDp) {
        v.setStateListAnimator(null);
        return seguir(v, (x, a) -> {
            x.setBackground(forma(x.getContext(), a.botao, raioDp, Color.TRANSPARENT));
            ((TextView) x).setTextColor(a.botaoTexto);
        });
    }

    /**
     * Cartão de vidro fosco: sem preenchimento próprio, só a borda fina na cor do
     * céu. O desfoque por dentro é desenhado pela {@link NebulaSkyView}.
     */
    static <V extends View> V vidro(V v, int raioDp) {
        NebulaSkyView.vidro(v, dp(v.getContext(), raioDp));
        return seguir(v, (x, a) -> x.setBackground(forma(x.getContext(), Color.TRANSPARENT, raioDp, a.borda)));
    }

    static int dp(Context c, int valor) {
        return Math.round(valor * c.getResources().getDisplayMetrics().density);
    }

    static GradientDrawable forma(Context c, int preenchimento, int raio, int borda) {
        GradientDrawable f = new GradientDrawable();
        f.setColor(preenchimento);
        f.setCornerRadius(dp(c, raio));
        if (borda != Color.TRANSPARENT) f.setStroke(dp(c, 1), borda);
        return f;
    }

    static int hsl(float h, float s, float l) {
        float c = (1 - Math.abs(2 * l - 1)) * s;
        float hp = (h % 360f + 360f) % 360f / 60f;
        float x = c * (1 - Math.abs(hp % 2 - 1));
        float r = 0, g = 0, b = 0;
        if (hp < 1) { r = c; g = x; } else if (hp < 2) { r = x; g = c; } else if (hp < 3) { g = c; b = x; }
        else if (hp < 4) { g = x; b = c; } else if (hp < 5) { r = x; b = c; } else { r = c; b = x; }
        float m = l - c / 2;
        return Color.rgb(Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255));
    }
}
