package com.nebula.assistant;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Regras de rede comuns às telas nativas.
 *
 * <p>A interface mora no app; pela rede só passam comandos e dados. Longe de
 * casa o único caminho até o PC e o notebook é o Tailscale, e a primeira
 * conexão por ele precisa furar o NAT ou cair no relé antes de existir — leva
 * segundos. Cada tela tinha o próprio limite curto (1,2 s e 1,5 s), que matava
 * a conexão antes disso pelo 4G. Aqui o limite depende do destino.</p>
 */
final class Rede {
    private Rede() { }

    /** Endereço do tailnet (faixa 100.64/10 do Tailscale). */
    static boolean viaTailscale(String endpoint) {
        return endpoint != null && endpoint.contains("//100.");
    }

    /** LAN responde na hora ou não responde; pelo Tailscale é preciso esperar o aperto de mão. */
    static int conexaoMs(String endpoint) {
        return viaTailscale(endpoint) ? 9000 : 1500;
    }

    /** GET quando {@code corpo} é nulo, POST com JSON caso contrário. */
    static JSONObject json(String endpoint, String caminho, JSONObject corpo, String token,
                           int leituraMs) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(endpoint + caminho).openConnection();
        try {
            c.setConnectTimeout(conexaoMs(endpoint));
            c.setReadTimeout(viaTailscale(endpoint) ? leituraMs + 6000 : leituraMs);
            c.setInstanceFollowRedirects(false);
            c.setRequestProperty("X-Nebula-Power-Token", token);
            if (corpo != null) {
                c.setRequestMethod("POST");
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                c.setDoOutput(true);
                try (OutputStream out = c.getOutputStream()) {
                    out.write(corpo.toString().getBytes(StandardCharsets.UTF_8));
                }
            }
            int codigo = c.getResponseCode();
            InputStream fluxo = codigo >= 400 ? c.getErrorStream() : c.getInputStream();
            if (fluxo == null) throw new IOException("O servidor respondeu " + codigo + ".");
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (InputStream in = fluxo) {
                byte[] b = new byte[8192];
                int n;
                while ((n = in.read(b)) != -1) {
                    if (bytes.size() + n > 4_000_000) throw new IOException("Resposta grande demais.");
                    bytes.write(b, 0, n);
                }
            }
            JSONObject resposta;
            try {
                resposta = new JSONObject(bytes.toString("UTF-8"));
            } catch (Exception e) {
                throw new IOException("Resposta inesperada do servidor (" + codigo + ").");
            }
            if (codigo < 200 || codigo >= 300) {
                throw new IOException(resposta.optString("error", "O servidor respondeu " + codigo + "."));
            }
            return resposta;
        } finally {
            c.disconnect();
        }
    }
}
