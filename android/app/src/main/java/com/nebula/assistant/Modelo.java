package com.nebula.assistant;

import android.graphics.Color;

import java.util.Locale;

/**
 * Qual IA respondeu, com o símbolo e a cor que a identificam de relance.
 *
 * <p>Os símbolos lembram as marcas sem copiar logotipo: a faísca da Anthropic,
 * o hexágono da OpenAI, a estrela de quatro pontas do Gemini e o losango da
 * Qwen.</p>
 */
final class Modelo {
    final String simbolo, nome;
    final int cor;

    private Modelo(String simbolo, String nome, int cor) {
        this.simbolo = simbolo;
        this.nome = nome;
        this.cor = cor;
    }

    /** {@code null} quando não houve IA: você, a própria Nebula ou uma resposta fixa. */
    static Modelo de(String autor, String modelo) {
        String m = modelo == null ? "" : modelo.toLowerCase(Locale.ROOT);
        if (m.contains("claude") || "opus".equals(autor) || m.startsWith("opus") || m.startsWith("sonnet")) {
            return new Modelo("✺", claude(m), Color.rgb(217, 119, 87));
        }
        if (m.contains("gemini")) {
            return new Modelo("✦", legivel(m), Color.rgb(138, 180, 248));
        }
        if (m.contains("qwen")) {
            return new Modelo("◈", legivel(m), Color.rgb(139, 135, 255));
        }
        if (m.contains("gpt") || m.contains("codex") || "codex".equals(autor)) {
            return new Modelo("⬡", gpt(m), Color.rgb(16, 163, 127));
        }
        return null;
    }

    /** gpt-6-sol high → GPT-6 Sol · alto. Sem modelo conhecido, só GPT. */
    static String gpt(String m) {
        if (!m.startsWith("gpt")) return "GPT";
        String[] tokens = m.split(" ");
        String[] p = tokens[0].split("-");
        StringBuilder s = new StringBuilder("GPT-").append(p.length > 1 ? p[1] : "");
        for (int i = 2; i < p.length; i++) s.append(' ').append(maiuscula(p[i]));
        if (tokens.length > 1) s.append(" · ").append(esforco(tokens[1]));
        return s.toString();
    }

    static String esforco(String e) {
        switch (e) {
            case "low": return "baixo";
            case "medium": return "médio";
            case "high": return "alto";
            case "xhigh": return "muito alto";
            case "max": return "máximo";
            default: return e;
        }
    }

    /** claude-opus-5-5 → Opus 5.5 */
    private static String claude(String m) {
        String resto = m.replace("claude-", "");
        String[] partes = resto.split("[-, ]+");
        if (partes.length == 0 || partes[0].isEmpty()) return "Claude";
        StringBuilder nome = new StringBuilder(maiuscula(partes[0]));
        StringBuilder versao = new StringBuilder();
        for (int i = 1; i < partes.length && partes[i].matches("[0-9]+"); i++) {
            if (versao.length() > 0) versao.append('.');
            versao.append(partes[i]);
        }
        if (versao.length() > 0) nome.append(' ').append(versao);
        return nome.toString();
    }

    private static String legivel(String m) {
        String[] partes = m.split("[-_:]+");
        StringBuilder s = new StringBuilder();
        for (String p : partes) {
            if (p.isEmpty()) continue;
            if (s.length() > 0) s.append(' ');
            s.append(maiuscula(p));
        }
        return s.toString();
    }

    private static String maiuscula(String p) {
        return p.isEmpty() ? p : Character.toUpperCase(p.charAt(0)) + p.substring(1);
    }
}
