package com.nebula.assistant;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Handler;
import android.os.Looper;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Chat da Dupla desenhado pelo próprio app: você, Astra e Claude.
 *
 * <p>Nada de página: só o texto das mensagens vem da rede, por
 * {@code /api/dupla/conversa}, que devolve apenas o que é novo depois de um
 * cursor. O painel do PC busca o diário inteiro (270 KB) a cada 3 s; pelo 4G
 * isso passaria de 300 MB por hora de chat aberto.</p>
 */
final class NebulaChat {
    private static final long INTERVALO_MS = 3000;
    private static final Pattern MARCACAO = Pattern.compile("\\*\\*(.+?)\\*\\*|`([^`\\n]+)`");

    /** Rola para baixo: a conversa ocupa a tela e o painel de uso vem depois. */
    final ScrollView root;
    private final LinearLayout tela, painelUso;
    /** Nome da parceira: o do modelo configurado no Codex (Astra, Sol...). */
    private String nomeCodex = "GPT";
    private long ultimoUso;
    private final Activity activity;
    private final String token;
    private final String[] servidores;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService rede = Executors.newSingleThreadExecutor();
    private final LinearLayout lista;
    private final ScrollView rolagem;
    private final EditText campo;
    private final Button enviar;
    private final TextView pedido, estado, projetoNome;
    private final ScrollView seletor;
    private final LinearLayout listaProjetos;
    private final Button modoConversa, modoDesenvolver;
    /** Desenvolver: as duas implementam e revisam no projeto. Conversar: só respondem. */
    private boolean desenvolver;
    private boolean projetoComGit;
    private String modoAtivo;

    private String servidor;
    private String ideiaId = "";
    private long cursor;
    private boolean ativo, buscando, respondendo, fechado;
    /** Depois de enviar, a própria mensagem tem que aparecer mesmo com você lendo acima. */
    private boolean irAoFinal = true;

    private final Runnable ciclo = new Runnable() {
        @Override public void run() {
            if (!ativo || fechado) return;
            atualizar();
            if (System.currentTimeMillis() - ultimoUso >= 60_000) atualizarUso();
            ui.postDelayed(this, INTERVALO_MS);
        }
    };

    NebulaChat(Activity activity, String token, String[] servidores, Runnable voltar) {
        this.activity = activity;
        this.token = token;
        this.servidores = servidores;

        tela = coluna();
        painelUso = coluna();
        root = new ScrollView(activity);
        root.setFillViewport(true);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            v.setPadding(dp(14) + insets.getSystemWindowInsetLeft(), dp(10) + insets.getSystemWindowInsetTop(),
                    dp(14) + insets.getSystemWindowInsetRight(), dp(10) + insets.getSystemWindowInsetBottom());
            return insets;
        });

        LinearLayout topo = new LinearLayout(activity);
        topo.setGravity(Gravity.CENTER_VERTICAL);
        Button sair = new Button(activity);
        sair.setText("‹");
        sair.setTextSize(26);
        sair.setTextColor(Tema.TEXTO);
        sair.setBackground(Tema.forma(activity, Color.TRANSPARENT, 20, Color.TRANSPARENT));
        sair.setContentDescription("Voltar");
        sair.setOnClickListener(v -> voltar.run());
        topo.addView(sair, new LinearLayout.LayoutParams(dp(48), dp(48)));
        LinearLayout titulos = coluna();
        TextView sobrelinha = Tema.destaque(texto("DUAS IAS, UMA FILA", 10, Tema.TEXTO));
        sobrelinha.setLetterSpacing(.2f);
        titulos.addView(sobrelinha);
        TextView titulo = texto("Dupla", 24, Tema.TEXTO);
        titulo.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        titulos.addView(titulo);
        topo.addView(titulos, new LinearLayout.LayoutParams(0, -2, 1));
        tela.addView(topo);

        pedido = texto("Consultando a conversa…", 12, Tema.SUAVE);
        pedido.setMaxLines(2);
        pedido.setEllipsize(TextUtils.TruncateAt.END);
        pedido.setPadding(dp(6), 0, dp(6), dp(6));
        tela.addView(pedido);

        LinearLayout projeto = new LinearLayout(activity);
        projeto.setGravity(Gravity.CENTER_VERTICAL);
        projeto.setPadding(dp(14), dp(8), dp(14), dp(8));
        Tema.vidro(projeto, 16);
        LinearLayout textosProjeto = coluna();
        textosProjeto.addView(Tema.destaque(texto("PROJETO", 10, Tema.TEXTO)));
        projetoNome = texto("…", 15, Tema.TEXTO);
        textosProjeto.addView(projetoNome);
        projeto.addView(textosProjeto, new LinearLayout.LayoutParams(0, -2, 1));
        projeto.addView(Tema.destaque(texto("trocar", 13, Tema.TEXTO)));
        projeto.setClickable(true);
        projeto.setOnClickListener(v -> alternarSeletor());
        LinearLayout.LayoutParams lpProjeto = new LinearLayout.LayoutParams(-1, -2);
        lpProjeto.setMargins(0, 0, 0, dp(6));
        tela.addView(projeto, lpProjeto);

        rolagem = new ScrollView(activity);
        rolagem.setFillViewport(true);
        lista = coluna();
        lista.setPadding(0, dp(4), 0, dp(12));
        rolagem.addView(lista);
        tela.addView(rolagem, new LinearLayout.LayoutParams(-1, 0, 1));

        // Lista de projetos no lugar da conversa enquanto aberta: por cima dela,
        // o vidro deixaria as mensagens aparecendo através da lista.
        seletor = new ScrollView(activity);
        listaProjetos = coluna();
        listaProjetos.setPadding(0, dp(4), 0, dp(12));
        seletor.addView(listaProjetos);
        seletor.setVisibility(View.GONE);
        tela.addView(seletor, new LinearLayout.LayoutParams(-1, 0, 1));

        estado = texto("", 12, Tema.SUAVE);
        estado.setPadding(dp(6), dp(4), dp(6), dp(4));
        tela.addView(estado);

        LinearLayout modos = new LinearLayout(activity);
        modos.setPadding(0, 0, 0, dp(6));
        modoConversa = new Button(activity);
        modoConversa.setText("Conversar");
        modoDesenvolver = new Button(activity);
        modoDesenvolver.setText("Desenvolver");
        for (Button b : new Button[]{modoConversa, modoDesenvolver}) {
            b.setAllCaps(false);
            b.setTextSize(13);
            b.setStateListAnimator(null);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(40), 1);
            lp.setMargins(b == modoConversa ? 0 : dp(6), 0, 0, 0);
            modos.addView(b, lp);
        }
        modoConversa.setOnClickListener(v -> escolherModo(false));
        modoDesenvolver.setOnClickListener(v -> escolherModo(true));
        tela.addView(modos);

        LinearLayout entrada = new LinearLayout(activity);
        entrada.setGravity(Gravity.BOTTOM);
        entrada.setPadding(dp(12), dp(6), dp(6), dp(6));
        Tema.vidro(entrada, 24);
        campo = new EditText(activity);
        campo.setHint("Fale com Astra e Claude…");
        campo.setHintTextColor(Tema.SUAVE);
        campo.setTextColor(Tema.TEXTO);
        campo.setTextSize(16);
        campo.setMaxLines(5);
        campo.setBackground(null);
        campo.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        entrada.addView(campo, new LinearLayout.LayoutParams(0, -2, 1));
        enviar = new Button(activity);
        enviar.setText("Enviar");
        enviar.setAllCaps(false);
        enviar.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        Tema.botao(enviar, 20);
        enviar.setOnClickListener(v -> {
            if (respondendo && "development".equals(modoAtivo)) pararDesenvolvimento();
            else enviarMensagem();
        });
        entrada.addView(enviar, new LinearLayout.LayoutParams(-2, dp(44)));
        tela.addView(entrada, new LinearLayout.LayoutParams(-1, -2));
        TextView dica = texto("▾   uso das IAs", 12, Tema.SUAVE);
        dica.setGravity(Gravity.CENTER);
        dica.setPadding(0, dp(6), 0, 0);
        dica.setOnClickListener(v -> root.smoothScrollTo(0, painelUso.getTop()));
        tela.addView(dica, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout conteudo = coluna();
        conteudo.addView(tela, new LinearLayout.LayoutParams(-1, dp(600)));
        painelUso.setPadding(0, dp(18), 0, dp(24));
        painelUso.addView(texto("Consultando o uso das duas…", 13, Tema.SUAVE));
        conteudo.addView(painelUso);
        root.addView(conteudo);
        // A conversa ocupa exatamente a altura visível; o painel fica logo abaixo.
        root.addOnLayoutChangeListener((v, l, t, r, b, ol, ot, or, ob) -> {
            int alto = v.getHeight() - v.getPaddingTop() - v.getPaddingBottom();
            android.view.ViewGroup.LayoutParams lp = tela.getLayoutParams();
            if (alto > 0 && lp.height != alto) {
                lp.height = alto;
                tela.post(() -> tela.setLayoutParams(lp));
            }
        });
        // Ao chegar no fim da conversa, continuar rolando desce para o painel.
        rolagem.setNestedScrollingEnabled(true);
        escolherModo(false);
    }

    /** Liga a consulta quando a tela aparece e desliga fora dela: sem dado gasto à toa. */
    void ativar(boolean sim) {
        ativo = sim && !fechado;
        ui.removeCallbacks(ciclo);
        if (ativo) ui.post(ciclo);
    }

    void fechar() {
        fechado = true;
        ativar(false);
        rede.shutdownNow();
    }

    private void atualizar() {
        if (buscando) return;
        buscando = true;
        final String ideia = ideiaId;
        final long desde = cursor;
        rede.execute(() -> {
            JSONObject resposta = null;
            String erro = null;
            try {
                resposta = pedir("/api/dupla/conversa?depois=" + desde + "&ideia=" + ideia, null, 10000);
            } catch (Exception e) {
                erro = e.getMessage();
            }
            final JSONObject dados = resposta;
            final String falha = erro;
            ui.post(() -> {
                buscando = false;
                if (fechado) return;
                if (falha != null) {
                    estado.setTextColor(Tema.ALERTA);
                    estado.setText("Sem contato com o PC: " + falha);
                    return;
                }
                mostrar(dados);
            });
        });
    }

    /** Tenta o último servidor que respondeu e só então os outros. */
    private JSONObject pedir(String caminho, JSONObject corpo, int leituraMs) throws Exception {
        Exception ultimo = null;
        if (servidor != null) {
            try {
                return Rede.json(servidor, caminho, corpo, token, leituraMs);
            } catch (Exception e) {
                ultimo = e;
                servidor = null;
            }
        }
        for (String candidato : servidores) {
            try {
                JSONObject r = Rede.json(candidato, caminho, corpo, token, leituraMs);
                servidor = candidato;
                return r;
            } catch (Exception e) {
                ultimo = e;
            }
        }
        throw ultimo != null ? ultimo : new java.io.IOException("nenhum endereço configurado");
    }

    private void mostrar(JSONObject dados) {
        JSONObject ideia = dados.optJSONObject("ideia");
        if (dados.optBoolean("recomecar")) {
            lista.removeAllViews();
            ideiaId = ideia == null ? "" : ideia.optString("id");
            irAoFinal = true;
        }
        pedido.setText(ideia == null ? "Nenhum pedido aberto. A primeira mensagem abre um."
                : ideia.optString("texto"));
        cursor = dados.optLong("cursor", cursor);
        JSONObject nomes = dados.optJSONObject("nomes");
        if (nomes != null && !nomes.optString("codex").isEmpty() && !nomes.optString("codex").equals(nomeCodex)) {
            nomeCodex = nomes.optString("codex");
            escolherModo(desenvolver);
        }
        JSONObject projeto = dados.optJSONObject("projeto");
        if (projeto != null) {
            projetoComGit = projeto.optBoolean("git");
            projetoNome.setText(projeto.optString("nome") + (projetoComGit ? "" : "  ·  sem Git, só conversa"));
            if (!projetoComGit && desenvolver) escolherModo(false);
            modoDesenvolver.setEnabled(projetoComGit);
            modoDesenvolver.setAlpha(projetoComGit ? 1f : .4f);
        }
        respondendo = dados.optBoolean("respondendo");
        modoAtivo = dados.optString("modo", "");
        boolean parar = respondendo && "development".equals(modoAtivo);
        // Durante o desenvolvimento o botão vira Parar; numa conversa só espera.
        enviar.setText(parar ? "Parar" : "Enviar");
        enviar.setEnabled(!respondendo || parar);
        enviar.setAlpha(!respondendo || parar ? 1f : .45f);
        estado.setTextColor(Tema.SUAVE);
        estado.setText(!respondendo ? "" : parar ? nomeCodex + " e Claude estão trabalhando no projeto…"
                : nomeCodex + " e Claude estão respondendo…");

        JSONArray novas = dados.optJSONArray("mensagens");
        if (novas == null || novas.length() == 0) {
            if (lista.getChildCount() == 0) {
                lista.addView(texto("Envie uma mensagem para conversar com as duas.", 14, Tema.SUAVE));
            }
            return;
        }
        if (lista.getChildCount() == 1 && !(lista.getChildAt(0) instanceof LinearLayout)) {
            lista.removeAllViews();
        }
        // Mede antes de acrescentar: só acompanha o final se você já estava nele.
        boolean noFinal = irAoFinal || estaNoFinal();
        for (int i = 0; i < novas.length(); i++) {
            JSONObject m = novas.optJSONObject(i);
            if (m != null) lista.addView(bolha(m));
        }
        irAoFinal = false;
        if (noFinal) rolagem.post(() -> rolagem.fullScroll(View.FOCUS_DOWN));
    }

    private boolean estaNoFinal() {
        View filho = rolagem.getChildAt(0);
        return filho == null || filho.getBottom() - (rolagem.getHeight() + rolagem.getScrollY()) <= dp(48);
    }

    private void enviarMensagem() {
        final String texto = campo.getText().toString().trim();
        if (texto.isEmpty() || respondendo) return;
        enviar.setEnabled(false);
        estado.setTextColor(Tema.SUAVE);
        estado.setText("Enviando às duas…");
        final String ideia = ideiaId;
        rede.execute(() -> {
            String erro = null;
            try {
                JSONObject corpo = new JSONObject().put("text", texto);
                // Sem o pedido atual o servidor abriria uma conversa nova a cada mensagem.
                if (!ideia.isEmpty()) corpo.put("idea_id", ideia);
                // Desenvolver: o Codex implementa e o Claude revisa no disco, com
                // ferramentas de verdade. Orçamento: o PC sempre aplica o máximo.
                pedir(desenvolver ? "/api/collaboration/develop" : "/api/collaboration/chat", corpo, 20000);
            } catch (Exception e) {
                erro = e.getMessage();
            }
            final String falha = erro;
            ui.post(() -> {
                if (fechado) return;
                if (falha != null) {
                    enviar.setEnabled(true);
                    estado.setTextColor(Tema.ALERTA);
                    estado.setText(falha);
                    return;
                }
                campo.setText("");
                irAoFinal = true;
                atualizar();
            });
        });
    }

    private void escolherModo(boolean desenvolverAgora) {
        if (desenvolverAgora && !projetoComGit) return;
        desenvolver = desenvolverAgora;
        Tema.seguir(modoConversa, (v, a) -> pintarModo((Button) v, !desenvolver, a));
        Tema.seguir(modoDesenvolver, (v, a) -> pintarModo((Button) v, desenvolver, a));
        campo.setHint(desenvolver ? "O que as duas devem fazer no projeto?" : "Fale com " + nomeCodex + " e Claude…");
    }

    private void pintarModo(Button b, boolean ativo, Tema.Acento a) {
        b.setBackground(Tema.forma(activity, ativo ? a.botao : Color.TRANSPARENT, 20, ativo ? Color.TRANSPARENT : a.borda));
        b.setTextColor(ativo ? a.botaoTexto : Tema.TEXTO);
    }

    private void pararDesenvolvimento() {
        enviar.setEnabled(false);
        rede.execute(() -> {
            String erro = null;
            try { pedir("/api/collaboration/stop", new JSONObject(), 15000); }
            catch (Exception e) { erro = e.getMessage(); }
            final String falha = erro;
            ui.post(() -> {
                if (fechado) return;
                estado.setTextColor(falha == null ? Tema.SUAVE : Tema.ALERTA);
                estado.setText(falha == null ? "Pedido de parada enviado." : falha);
                atualizar();
            });
        });
    }

    private void alternarSeletor() {
        abrirSeletor(seletor.getVisibility() != View.VISIBLE);
    }

    private void abrirSeletor(boolean aberto) {
        seletor.setVisibility(aberto ? View.VISIBLE : View.GONE);
        rolagem.setVisibility(aberto ? View.GONE : View.VISIBLE);
        if (!aberto) return;
        listaProjetos.removeAllViews();
        listaProjetos.addView(texto("Procurando os projetos do VS Code…", 14, Tema.SUAVE));
        rede.execute(() -> {
            JSONObject dados = null;
            String erro = null;
            try { dados = pedir("/api/projects", null, 15000); }
            catch (Exception e) { erro = e.getMessage(); }
            final JSONObject resposta = dados;
            final String falha = erro;
            ui.post(() -> {
                if (fechado) return;
                listaProjetos.removeAllViews();
                if (falha != null) {
                    listaProjetos.addView(texto("Não consegui listar: " + falha, 14, Tema.ALERTA));
                    return;
                }
                mostrarProjetos(resposta);
            });
        });
    }

    private void mostrarProjetos(JSONObject dados) {
        String ativo = dados.optString("active");
        Button abrirVsCode = new Button(activity);
        abrirVsCode.setText("Abrir o projeto ativo no VS Code do PC");
        abrirVsCode.setAllCaps(false);
        Tema.botao(abrirVsCode, 16);
        abrirVsCode.setOnClickListener(v -> acaoNoPc("/api/vscode", new JSONObject()));
        listaProjetos.addView(abrirVsCode, new LinearLayout.LayoutParams(-1, dp(48)));
        JSONArray projetos = dados.optJSONArray("projects");
        for (int i = 0; projetos != null && i < projetos.length(); i++) {
            JSONObject pr = projetos.optJSONObject(i);
            if (pr == null) continue;
            final String caminho = pr.optString("path");
            boolean git = pr.optBoolean("git");
            LinearLayout linha = coluna();
            linha.setPadding(dp(14), dp(10), dp(14), dp(10));
            Tema.vidro(linha, 14);
            TextView nome = texto(pr.optString("name") + (caminho.equalsIgnoreCase(ativo) ? "  · ativo" : ""), 16, Tema.TEXTO);
            if (caminho.equalsIgnoreCase(ativo)) Tema.destaque(nome);
            linha.addView(nome);
            TextView detalhe = texto((git ? "Git · " : "sem Git · ") + caminho, 11, Tema.SUAVE);
            detalhe.setMaxLines(1);
            detalhe.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            linha.addView(detalhe);
            linha.setClickable(true);
            linha.setOnClickListener(v -> escolherProjeto(caminho));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(0, dp(8), 0, 0);
            listaProjetos.addView(linha, lp);
        }
    }

    private void escolherProjeto(String caminho) {
        acaoNoPc("/api/project", jsonCom("path", caminho));
        // Cada projeto tem o próprio diário: a conversa recomeça do zero.
        ideiaId = "";
        cursor = 0;
        lista.removeAllViews();
        irAoFinal = true;
        abrirSeletor(false);
    }

    private void acaoNoPc(String caminho, JSONObject corpo) {
        rede.execute(() -> {
            String mensagem;
            try { mensagem = pedir(caminho, corpo, 15000).optString("message", "Feito."); }
            catch (Exception e) { mensagem = e.getMessage(); }
            final String texto = mensagem;
            ui.post(() -> {
                if (fechado) return;
                estado.setTextColor(Tema.SUAVE);
                estado.setText(texto);
                atualizar();
            });
        });
    }

    private static JSONObject jsonCom(String chave, String valor) {
        try { return new JSONObject().put(chave, valor); }
        catch (Exception e) { return new JSONObject(); }
    }

    private void atualizarUso() {
        ultimoUso = System.currentTimeMillis();
        rede.execute(() -> {
            JSONObject dados = null;
            String erro = null;
            try { dados = pedir("/api/dupla/uso", null, 20000); }
            catch (Exception e) { erro = e.getMessage(); }
            final JSONObject resposta = dados;
            final String falha = erro;
            ui.post(() -> {
                if (fechado) return;
                if (falha != null) {
                    painelUso.removeAllViews();
                    painelUso.addView(texto("Uso indisponível: " + falha, 13, Tema.ALERTA));
                    return;
                }
                pintarUso(resposta);
            });
        });
    }

    /** Limites de 5 h e da semana de cada uma, e as duas juntas. Só dado real. */
    private void pintarUso(JSONObject d) {
        painelUso.removeAllViews();
        painelUso.addView(Tema.destaque(texto("USO DAS IAS", 10, Tema.TEXTO)));
        TextView titulo = texto("Limites", 24, Tema.TEXTO);
        titulo.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        painelUso.addView(titulo);
        JSONObject nomes = d.optJSONObject("nomes");
        String[][] agentes = {{"opus", "Claude"}, {"codex", nomes == null ? nomeCodex : nomes.optString("codex", nomeCodex)}};
        JSONObject dupla = d.optJSONObject("dupla");
        String maisPerto = null;
        double maior = -1;
        for (String[] ag : agentes) {
            JSONObject a = d.optJSONObject(ag[0]);
            if (a == null) continue;
            LinearLayout cartao = coluna();
            cartao.setPadding(dp(16), dp(14), dp(16), dp(14));
            Tema.vidro(cartao, 16);
            JSONObject modelo = a.optJSONObject("modelo");
            Modelo origem = Modelo.de(ag[0], modelo == null ? "" : modelo.optString("texto", ""));
            SpannableStringBuilder cab = new SpannableStringBuilder();
            if (origem != null) {
                cab.append(origem.simbolo).append("  ");
                cab.setSpan(new ForegroundColorSpan(origem.cor), 0, origem.simbolo.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            }
            cab.append(ag[1]);
            String plano = a.optString("plano", "");
            if (!plano.isEmpty() && !"null".equals(plano)) cab.append(" · ").append(plano.substring(0, 1).toUpperCase(Locale.ROOT)).append(plano.substring(1));
            if (origem != null && "codex".equals(ag[0])) cab.append(" · ").append(origem.nome);
            TextView cabecalho = texto("", 16, Tema.TEXTO);
            cabecalho.setText(cab);
            cartao.addView(cabecalho);
            String erro = a.optString("erro", "");
            if (!erro.isEmpty()) {
                cartao.addView(texto(erro, 13, Tema.ALERTA));
            } else {
                for (String[] janela : new String[][]{{"janela_5h", "Janela de 5 h"}, {"semanal", "Semana"}}) {
                    JSONObject j = a.optJSONObject(janela[0]);
                    double pct = j == null ? -1 : j.optDouble("pct", -1);
                    if (pct > maior) { maior = pct; maisPerto = ag[1] + " · " + janela[1].toLowerCase(Locale.ROOT) + " " + formatar(pct) + "%"; }
                    LinearLayout linha = new LinearLayout(activity);
                    linha.setGravity(Gravity.CENTER_VERTICAL);
                    linha.setPadding(0, dp(10), 0, dp(4));
                    TextView rotulo = texto(janela[1], 13, Tema.SUAVE);
                    linha.addView(rotulo, new LinearLayout.LayoutParams(0, -2, 1));
                    TextView valor = texto(pct < 0 ? "sem dado" : formatar(pct) + "%", 15, pct >= 80 ? Tema.ALERTA : Tema.TEXTO);
                    valor.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
                    linha.addView(valor);
                    cartao.addView(linha);
                    BarraUso barra = new BarraUso(activity);
                    barra.definir(pct);
                    cartao.addView(barra, new LinearLayout.LayoutParams(-1, dp(8)));
                    String reinicio = j == null ? "" : reinicio(j.optString("reinicia_em", ""));
                    if (!reinicio.isEmpty()) cartao.addView(texto(reinicio, 12, Tema.SUAVE));
                }
            }
            if (dupla != null) {
                cartao.addView(texto("Pela Dupla: " + milhares(dupla.optLong(ag[0])) + " tokens medidos", 13, Tema.SUAVE));
            }
            String fonte = a.optString("fonte", "");
            String quando = hora(a.optString("atualizado_em", ""));
            if (!fonte.isEmpty()) cartao.addView(texto(fonte + (quando.isEmpty() ? "" : " · " + quando), 11, Tema.SUAVE));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.setMargins(0, dp(12), 0, 0);
            painelUso.addView(cartao, lp);
        }
        LinearLayout juntas = coluna();
        juntas.setPadding(dp(16), dp(14), dp(16), dp(14));
        Tema.vidro(juntas, 16);
        juntas.addView(Tema.destaque(texto("AS DUAS JUNTAS", 10, Tema.TEXTO)));
        if (dupla != null) {
            TextView soma = texto(milhares(dupla.optLong("soma")) + " tokens", 22, Tema.TEXTO);
            juntas.addView(soma);
            juntas.addView(texto("medidos pela Dupla: Claude " + milhares(dupla.optLong("opus")) + " + "
                + agentes[1][1] + " " + milhares(dupla.optLong("codex")), 12, Tema.SUAVE));
        }
        if (maisPerto != null) {
            juntas.addView(texto("Mais perto do limite: " + maisPerto, 13, maior >= 80 ? Tema.ALERTA : Tema.TEXTO));
        }
        // As porcentagens são de planos diferentes: somá-las não teria sentido.
        juntas.addView(texto("Porcentagens são de planos diferentes e não se somam; a soma é em tokens.", 11, Tema.SUAVE));
        LinearLayout.LayoutParams lpJuntas = new LinearLayout.LayoutParams(-1, -2);
        lpJuntas.setMargins(0, dp(12), 0, 0);
        painelUso.addView(juntas, lpJuntas);
    }

    private static String formatar(double pct) {
        return pct == Math.rint(pct) ? String.valueOf((long) pct) : String.format(Locale.ROOT, "%.1f", pct);
    }

    private static String milhares(long n) {
        return n >= 1_000_000 ? String.format(Locale.ROOT, "%.1f mi", n / 1e6)
             : n >= 1000 ? String.format(Locale.ROOT, "%.1f mil", n / 1e3) : String.valueOf(n);
    }

    /** "reinicia 01:19 · em 3 h 40 min" a partir do horário ISO do provedor. */
    private static String reinicio(String iso) {
        if (iso.isEmpty() || "null".equals(iso)) return "";
        try {
            String normal = iso.replaceFirst("\\.\\d+", "");
            Date d = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT).parse(normal);
            if (d == null) return "";
            long faltam = (d.getTime() - System.currentTimeMillis()) / 60000;
            String quando = new SimpleDateFormat(faltam > 24 * 60 ? "EEE HH:mm" : "HH:mm", new Locale("pt", "BR")).format(d);
            if (faltam <= 0) return "reinicia " + quando;
            String resto = faltam >= 24 * 60 ? (faltam / 1440) + " d " + (faltam % 1440 / 60) + " h"
                         : faltam >= 60 ? (faltam / 60) + " h " + (faltam % 60) + " min" : faltam + " min";
            return "reinicia " + quando + " · em " + resto;
        } catch (Exception e) {
            return "";
        }
    }

    private View bolha(JSONObject m) {
        String autor = m.optString("autor");
        String tipo = m.optString("tipo");
        boolean minha = "user".equals(autor);
        boolean erro = "chat_error".equals(tipo);

        LinearLayout caixa = coluna();
        caixa.setPadding(dp(14), dp(10), dp(14), dp(12));
        Tema.vidro(caixa, 16);

        String nome = minha ? "Você" : "codex".equals(autor) ? nomeCodex
                : "opus".equals(autor) ? "Claude" : "Nebula";
        Modelo origem = Modelo.de(autor, m.optString("modelo", ""));
        SpannableStringBuilder cabecalho = new SpannableStringBuilder();
        if (origem != null) {
            // Símbolo na cor da marca: dá para saber de relance quem respondeu.
            cabecalho.append(origem.simbolo).append("  ");
            cabecalho.setSpan(new ForegroundColorSpan(origem.cor), 0, origem.simbolo.length(),
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        cabecalho.append(nome);
        if (origem != null) cabecalho.append(" · ").append(origem.nome);
        if ("confirmation".equals(tipo)) cabecalho.append(" · confirmou");
        String hora = hora(m.optString("em"));
        if (!hora.isEmpty()) cabecalho.append("   ").append(hora);
        TextView cab = texto("", 12, Tema.SUAVE);
        cab.setText(cabecalho);
        if (erro) cab.setTextColor(Tema.ALERTA);
        else if (!minha) Tema.destaque(cab);
        cab.setPadding(0, 0, 0, dp(4));
        caixa.addView(cab);

        TextView corpo = texto("", 15, Tema.TEXTO);
        corpo.setText(formatar(m.optString("texto")));
        corpo.setTextIsSelectable(true);
        corpo.setLineSpacing(0, 1.18f);
        caixa.addView(corpo);

        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2);
        p.setMargins(minha ? dp(44) : 0, dp(10), minha ? 0 : dp(24), 0);
        caixa.setLayoutParams(p);
        return caixa;
    }

    /** Negrito, código e listas: o que as duas usam nas respostas. Sempre texto, nunca HTML. */
    static CharSequence formatar(String bruto) {
        SpannableStringBuilder sb = new SpannableStringBuilder();
        String[] linhas = bruto.split("\n", -1);
        for (int i = 0; i < linhas.length; i++) {
            String linha = linhas[i];
            boolean titulo = linha.startsWith("#");
            if (titulo) linha = linha.replaceFirst("^#+\\s*", "");
            if (linha.matches("^\\s*[-*] .*")) linha = "•  " + linha.replaceFirst("^\\s*[-*] ", "");
            int inicio = sb.length();
            Matcher achado = MARCACAO.matcher(linha);
            int ultimo = 0;
            while (achado.find()) {
                sb.append(linha, ultimo, achado.start());
                int de = sb.length();
                if (achado.group(1) != null) {
                    sb.append(achado.group(1));
                    sb.setSpan(new StyleSpan(Typeface.BOLD), de, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                } else {
                    sb.append(achado.group(2));
                    sb.setSpan(new TypefaceSpan("monospace"), de, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                    sb.setSpan(new ForegroundColorSpan(Tema.acento().texto), de, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                }
                ultimo = achado.end();
            }
            sb.append(linha, ultimo, linha.length());
            if (titulo) sb.setSpan(new StyleSpan(Typeface.BOLD), inicio, sb.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
            if (i < linhas.length - 1) sb.append('\n');
        }
        return sb;
    }

    private static String hora(String iso) {
        try {
            Date d = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT).parse(iso);
            return d == null ? "" : new SimpleDateFormat("HH:mm", Locale.getDefault()).format(d);
        } catch (Exception e) {
            return "";
        }
    }

    private LinearLayout coluna() {
        LinearLayout v = new LinearLayout(activity);
        v.setOrientation(LinearLayout.VERTICAL);
        return v;
    }

    private TextView texto(String conteudo, int tamanho, int cor) {
        TextView v = new TextView(activity);
        v.setText(conteudo);
        v.setTextSize(tamanho);
        v.setTextColor(cor);
        return v;
    }

    private int dp(int valor) { return Tema.dp(activity, valor); }
}
