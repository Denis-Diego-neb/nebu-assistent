package com.nebula.assistant;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Rect;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.View;
import android.view.ViewTreeObserver;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;

import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;

/**
 * Nebulosa espacial desenhada pelo próprio app, em OpenGL ES 2.0.
 *
 * <p>Os shaders vêm de {@code nebula_sky/}, a mesma fonte que o app nativo do PC
 * usa, empacotada como asset: nada é baixado da rede. O fundo acompanha para
 * onde a câmera traseira aponta — no front web isso era impossível pelo celular,
 * porque o Chrome só entrega o sensor de orientação a páginas em contexto
 * seguro, e a Nebula era aberta por {@code http://} da rede local.</p>
 *
 * <p>Além do céu, este renderizador desenha o <b>vidro fosco</b> dos cartões e
 * decide a <b>cor de destaque</b> da interface. As duas coisas precisam dele: uma
 * view do Android não consegue desfocar o que está atrás quando o fundo é uma
 * superfície OpenGL, e a cor dos botões vem da cor do próprio gás.</p>
 */
public final class NebulaSkyView extends GLSurfaceView implements SensorEventListener {

    private static final String TAG = "NebulaSky";
    /** Pixels do render do gás. É suave: amplia com filtro bilinear sem perda visível. */
    private static final int PIXELS = 150_000;
    /** 25 quadros por segundo para o gás, como o front web; ele muda devagar. */
    private static final long QUADRO_MS = 40;
    /** A cor de destaque é relida duas vezes por segundo. */
    private static final long ACENTO_MS = 500;
    /** Graus de giro que levam o deslocamento ao limite. */
    private static final float SPAN_GRAUS = 30f;
    /** Retângulos de vidro por quadro; o que passa disso fica sem desfoque. */
    private static final int MAX_VIDROS = 32;

    /** Views que viram vidro fosco. Chave fraca: tela fechada sai sozinha. */
    private static final Map<View, Integer> VIDROS = new WeakHashMap<>();

    /** Marca uma view como vidro: o céu desfocado aparece dentro dela. */
    static void vidro(View v, int raioPx) {
        VIDROS.put(v, raioPx);
        v.setElevation(0);
    }

    private final SensorManager sensores;
    private final Sensor rotacao;
    private final boolean movimentoReduzido;
    private final Ceu ceu;
    private final Handler principal = new Handler(Looper.getMainLooper());
    private boolean ativo;

    // Escritos pela thread principal (sensor), lidos pela thread de GL.
    private volatile float alvoX, alvoY;
    private float baseRumo = Float.NaN, baseElevacao = Float.NaN;
    private final float[] matriz = new float[9];

    /** 9 floats por vidro: x, y, largura, altura, raio, recorte esquerda, topo, direita, base. */
    private volatile float[] vidrosDoQuadro = new float[0];

    private final Runnable proximoQuadro = new Runnable() {
        @Override public void run() {
            if (!ativo) return;
            requestRender();
            postDelayed(this, QUADRO_MS);
        }
    };

    /** A cada quadro da interface: se um cartão mexeu, o vidro acompanha já. */
    private final ViewTreeObserver.OnPreDrawListener acompanharVidros = () -> {
        coletarVidros();
        return true;
    };

    public NebulaSkyView(Context context) {
        super(context);
        sensores = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        rotacao = sensores == null ? null : sensores.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR);
        // "Remover animações" nas configurações do Android vale para o céu também.
        movimentoReduzido = Settings.Global.getFloat(context.getContentResolver(),
                Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f;
        setEGLContextClientVersion(2);
        setEGLConfigChooser(8, 8, 8, 0, 0, 0);
        setPreserveEGLContextOnPause(true);
        ceu = new Ceu(context);
        setRenderer(ceu);
        setRenderMode(RENDERMODE_WHEN_DIRTY);
    }

    @Override
    protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        getViewTreeObserver().addOnPreDrawListener(acompanharVidros);
    }

    @Override
    protected void onDetachedFromWindow() {
        getViewTreeObserver().removeOnPreDrawListener(acompanharVidros);
        super.onDetachedFromWindow();
    }

    private final int[] base = new int[2], posicao = new int[2];
    private final Rect visivel = new Rect();

    private void coletarVidros() {
        getLocationInWindow(base);
        List<float[]> achados = new ArrayList<>();
        for (Map.Entry<View, Integer> e : VIDROS.entrySet()) {
            View v = e.getKey();
            if (v == null || !v.isAttachedToWindow() || !v.isShown() || v.getWidth() == 0) continue;
            // Parte visível já recortada pela rolagem; o arredondamento usa o
            // retângulo inteiro, senão a borda cortada ficaria arredondada.
            if (!v.getGlobalVisibleRect(visivel)) continue;
            v.getLocationInWindow(posicao);
            achados.add(new float[]{posicao[0] - base[0], posicao[1] - base[1], v.getWidth(), v.getHeight(),
                    e.getValue(), visivel.left - base[0], visivel.top - base[1],
                    visivel.right - base[0], visivel.bottom - base[1]});
            if (achados.size() == MAX_VIDROS) break;
        }
        float[] novo = new float[achados.size() * 9];
        for (int i = 0; i < achados.size(); i++) System.arraycopy(achados.get(i), 0, novo, i * 9, 9);
        if (!Arrays.equals(novo, vidrosDoQuadro)) {
            vidrosDoQuadro = novo;
            requestRender();
        }
    }

    /** Chamar no onResume da Activity. */
    public void retomar() {
        onResume();
        ativo = !movimentoReduzido;
        baseRumo = Float.NaN;
        if (ativo && rotacao != null) {
            sensores.registerListener(this, rotacao, SensorManager.SENSOR_DELAY_GAME);
        }
        removeCallbacks(proximoQuadro);
        if (ativo) post(proximoQuadro); else requestRender();
    }

    /** Chamar no onPause da Activity: sem quadro nem sensor fora da tela. */
    public void pausar() {
        ativo = false;
        removeCallbacks(proximoQuadro);
        if (sensores != null) sensores.unregisterListener(this);
        onPause();
    }

    @Override
    public void onSensorChanged(SensorEvent evento) {
        SensorManager.getRotationMatrixFromVector(matriz, evento.values);
        // A câmera traseira olha para -Z do aparelho. Em coordenadas do mundo
        // (X leste, Y norte, Z para cima) isso é a terceira coluna, negada.
        float dx = -matriz[2], dy = -matriz[5], dz = -matriz[8];
        float elevacao = (float) Math.toDegrees(Math.asin(Math.max(-1f, Math.min(1f, dz))));
        float rumo = (float) Math.toDegrees(Math.atan2(dx, dy));
        if (Float.isNaN(baseRumo)) {
            baseRumo = rumo;
            baseElevacao = elevacao;
            return;
        }
        // Apontando quase para o chão ou para o teto o rumo perde sentido e
        // trepida; ali só a elevação conta.
        if (Math.abs(elevacao) < 70f) {
            float giro = ((rumo - baseRumo + 540f) % 360f) - 180f;
            alvoX = limitar(giro / SPAN_GRAUS * 13f, 13f);
        }
        // Inclinar a câmera para cima olha para cima: no shader isso é pitch
        // negativo (pitch positivo aponta o raio central para baixo).
        alvoY = limitar(-(elevacao - baseElevacao) / SPAN_GRAUS * 10f, 10f);
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    private static float limitar(float v, float max) {
        return Math.max(-max, Math.min(max, v));
    }

    private final class Ceu implements Renderer {
        private final Context contexto;
        private int volume, estrelas, textura, copia, desfoque, vidro;
        private FloatBuffer quad, pontos;
        /** Render do gás (pequeno), desfoque (metade dele) e a tela cheia. */
        private int largura, altura, telaL, telaA, desfL, desfA;
        private final int[] ceuFbo = new int[2], desfX = new int[2], desfY = new int[2];
        private long ultimo, ultimoCeu, ultimoAcento, ultimoLog;
        private float tempoMs;
        private int quadros;
        private boolean temCeu;
        float sx, sy;
        private final float[] corMedia = {-1, 0, 0};
        private ByteBuffer leitura;
        private static final int TOTAL = 3200;

        Ceu(Context contexto) { this.contexto = contexto; }

        @Override
        public void onSurfaceCreated(GL10 gl, EGLConfig config) {
            int[] unidades = new int[1];
            GLES20.glGetIntegerv(GLES20.GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS, unidades, 0);
            String comum = asset("common.glsl");
            String semTextura = unidades[0] > 0 ? "" : "#define SEM_TEXTURA_NO_VERTICE\n";
            String alta = "precision highp float;\n";
            String fragmento = "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n"
                    + "#else\nprecision mediump float;\n#endif\n";
            String quadUv = alta + "attribute vec2 aPosition;varying vec2 vUv;"
                    + "void main(){vUv=aPosition*0.5+0.5;gl_Position=vec4(aPosition,0.0,1.0);}";
            // Ruído de gradiente intercalado para dithering: sem padrão visível.
            String ruido = "float ruido(vec2 c){return fract(52.9829189*fract(dot(c,vec2(0.06711056,0.00583715))));}";

            volume = programa(alta + asset("quad.vert"), fragmento + comum + asset("volume.frag"));
            estrelas = programa(alta + semTextura + comum + asset("stars.vert"),
                    "precision mediump float;\n" + asset("stars.frag"));
            // Amplia o render pequeno para a tela e aplica dithering. O gás escuro
            // fica em torno de 10/255, onde cada degrau de 8 bits vira uma borda
            // visível; num gradiente horizontal essas bordas parecem listras
            // verticais. Tem que ser depois da ampliação: no render pequeno o
            // filtro bilinear alisaria o ruído e o degrau voltaria.
            copia = programa(quadUv, fragmento + "uniform sampler2D uCena;varying vec2 vUv;" + ruido
                    + "void main(){vec3 c=texture2D(uCena,vUv).rgb;"
                    + "c+=(ruido(gl_FragCoord.xy)-0.5)/255.0;gl_FragColor=vec4(c,1.0);}");
            // Gaussiana separável de 9 amostras (5 leituras com filtro linear).
            desfoque = programa(quadUv, fragmento + "uniform sampler2D uFonte;uniform vec2 uPasso;varying vec2 vUv;"
                    + "void main(){vec3 c=texture2D(uFonte,vUv).rgb*0.2270270270;"
                    + "c+=texture2D(uFonte,vUv+uPasso*1.3846153846).rgb*0.3162162162;"
                    + "c+=texture2D(uFonte,vUv-uPasso*1.3846153846).rgb*0.3162162162;"
                    + "c+=texture2D(uFonte,vUv+uPasso*3.2307692308).rgb*0.0702702703;"
                    + "c+=texture2D(uFonte,vUv-uPasso*3.2307692308).rgb*0.0702702703;"
                    + "gl_FragColor=vec4(c,1.0);}");
            // Vidro: o céu desfocado dentro de um retângulo arredondado, escurecido
            // o bastante para o texto claro continuar legível. Quanto mais claro o
            // gás atrás, mais escurece — sobre o vermelho vivo, um véu fixo não
            // bastava para o texto.
            vidro = programa(alta + "attribute vec2 aPosition;void main(){gl_Position=vec4(aPosition,0.0,1.0);}",
                    fragmento + "uniform sampler2D uDesfoque;uniform vec2 uTela;uniform vec4 uRet;uniform float uRaio;"
                    + ruido
                    + "void main(){vec2 p=gl_FragCoord.xy;vec2 c=uRet.xy+uRet.zw*0.5;"
                    + "vec2 q=abs(p-c)-(uRet.zw*0.5-vec2(uRaio));"
                    + "float d=length(max(q,0.0))+min(max(q.x,q.y),0.0)-uRaio;"
                    + "float cobre=clamp(0.5-d,0.0,1.0);if(cobre<=0.0)discard;"
                    + "vec3 b=texture2D(uDesfoque,p/uTela).rgb;"
                    + "float luz=dot(b,vec3(0.2126,0.7152,0.0722));"
                    + "vec3 cor=mix(b,vec3(0.03,0.025,0.06),clamp(0.34+luz*1.7,0.34,0.84));"
                    + "cor+=(ruido(p)-0.5)/255.0;gl_FragColor=vec4(cor,cobre);}");
            quad = buffer(new float[]{-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1});
            criarTexturaEEstrelas();
            ultimo = SystemClock.uptimeMillis();
            temCeu = false;
            Log.i(TAG, "céu pronto; texturas no vertex shader: " + unidades[0]);
        }

        @Override
        public void onSurfaceChanged(GL10 gl, int w, int h) {
            telaL = w;
            telaA = h;
            double escala = Math.min(1.0, Math.sqrt(PIXELS / (double) (w * h)));
            largura = Math.max(1, (int) Math.round(w * escala));
            altura = Math.max(1, (int) Math.round(h * escala));
            desfL = Math.max(1, largura / 2);
            desfA = Math.max(1, altura / 2);
            alvoDeRender(ceuFbo, largura, altura);
            alvoDeRender(desfX, desfL, desfA);
            alvoDeRender(desfY, desfL, desfA);
            leitura = ByteBuffer.allocateDirect(desfL * desfA * 4).order(ByteOrder.nativeOrder());
            temCeu = false;
        }

        /** [0] framebuffer, [1] textura de cor. Recria se já existir. */
        private void alvoDeRender(int[] alvo, int w, int h) {
            if (alvo[0] != 0) {
                GLES20.glDeleteFramebuffers(1, alvo, 0);
                GLES20.glDeleteTextures(1, alvo, 1);
            }
            GLES20.glGenTextures(1, alvo, 1);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, alvo[1]);
            GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GLES20.GL_RGBA, w, h, 0,
                    GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, null);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_CLAMP_TO_EDGE);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_CLAMP_TO_EDGE);
            GLES20.glGenFramebuffers(1, alvo, 0);
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, alvo[0]);
            GLES20.glFramebufferTexture2D(GLES20.GL_FRAMEBUFFER, GLES20.GL_COLOR_ATTACHMENT0,
                    GLES20.GL_TEXTURE_2D, alvo[1], 0);
            if (GLES20.glCheckFramebufferStatus(GLES20.GL_FRAMEBUFFER) != GLES20.GL_FRAMEBUFFER_COMPLETE) {
                Log.e(TAG, "framebuffer incompleto " + w + "x" + h);
            }
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
        }

        @Override
        public void onDrawFrame(GL10 gl) {
            long agora = SystemClock.uptimeMillis();
            // O gás é caro e só avança no ritmo dele; a composição (céu ampliado
            // e vidros) é barata e acompanha cada movimento da interface, senão o
            // desfoque ficaria para trás do cartão durante a rolagem.
            if (!temCeu || agora - ultimoCeu >= QUADRO_MS - 4) {
                desenharCeu(agora);
                desfocar();
                ultimoCeu = agora;
                temCeu = true;
            }
            compor();
            if (agora - ultimoAcento >= ACENTO_MS) {
                lerAcento();
                ultimoAcento = agora;
            }
        }

        private void desenharCeu(long agora) {
            float dt = Math.min(agora - ultimo, 60);
            ultimo = agora;
            if (ativo) {
                tempoMs += dt;
                float suave = 1f - (float) Math.exp(-dt / 420.0);
                sx += (alvoX - sx) * suave;
                sy += (alvoY - sy) * suave;
            }
            float segundos = tempoMs / 1000f;
            float[] camera = new float[3], rotacaoCam = new float[9];
            pose(segundos, sx, sy, camera, rotacaoCam);
            float[] deriva = new float[3], cisalhamento = new float[3];
            fluxo(segundos, deriva, cisalhamento);

            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, ceuFbo[0]);
            GLES20.glViewport(0, 0, largura, altura);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, textura);
            GLES20.glDisable(GLES20.GL_BLEND);
            uniformes(volume, camera, rotacaoCam, segundos, deriva, cisalhamento);
            atributo(volume, "aPosition", quad, 2, 0, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 6);

            uniformes(estrelas, camera, rotacaoCam, segundos, deriva, cisalhamento);
            atributo(estrelas, "aPosition", pontos, 3, 24, 0);
            atributo(estrelas, "aProperties", pontos, 3, 24, 3);
            GLES20.glEnable(GLES20.GL_BLEND);
            GLES20.glBlendFunc(GLES20.GL_ONE, GLES20.GL_ONE);
            GLES20.glDrawArrays(GLES20.GL_POINTS, 0, TOTAL);
            GLES20.glDisable(GLES20.GL_BLEND);

            quadros++;
            if (agora - ultimoLog >= 2000) {
                Log.d(TAG, String.format(java.util.Locale.ROOT,
                        "fps=%.1f render=%dx%d sx=%.2f sy=%.2f vidros=%d",
                        quadros * 1000f / Math.max(1, agora - ultimoLog), largura, altura, sx, sy,
                        vidrosDoQuadro.length / 9));
                quadros = 0;
                ultimoLog = agora;
            }
        }

        /** Duas voltas de gaussiana na metade da resolução: desfoque largo e barato. */
        private void desfocar() {
            GLES20.glDisable(GLES20.GL_BLEND);
            GLES20.glViewport(0, 0, desfL, desfA);
            passar(ceuFbo[1], desfX[0], 1f / largura, 0);
            passar(desfX[1], desfY[0], 0, 1f / desfA);
            passar(desfY[1], desfX[0], 2.2f / desfL, 0);
            passar(desfX[1], desfY[0], 0, 2.2f / desfA);
        }

        private void passar(int fonte, int destino, float px, float py) {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, destino);
            GLES20.glUseProgram(desfoque);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, fonte);
            GLES20.glUniform1i(GLES20.glGetUniformLocation(desfoque, "uFonte"), 0);
            GLES20.glUniform2f(GLES20.glGetUniformLocation(desfoque, "uPasso"), px, py);
            atributo(desfoque, "aPosition", quad, 2, 0, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 6);
        }

        private void compor() {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            GLES20.glViewport(0, 0, telaL, telaA);
            GLES20.glDisable(GLES20.GL_BLEND);
            GLES20.glUseProgram(copia);
            GLES20.glActiveTexture(GLES20.GL_TEXTURE0);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, ceuFbo[1]);
            GLES20.glUniform1i(GLES20.glGetUniformLocation(copia, "uCena"), 0);
            atributo(copia, "aPosition", quad, 2, 0, 0);
            GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 6);

            float[] v = vidrosDoQuadro;
            if (v.length == 0) return;
            GLES20.glUseProgram(vidro);
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, desfY[1]);
            GLES20.glUniform1i(GLES20.glGetUniformLocation(vidro, "uDesfoque"), 0);
            GLES20.glUniform2f(GLES20.glGetUniformLocation(vidro, "uTela"), telaL, telaA);
            int ret = GLES20.glGetUniformLocation(vidro, "uRet");
            int raio = GLES20.glGetUniformLocation(vidro, "uRaio");
            atributo(vidro, "aPosition", quad, 2, 0, 0);
            GLES20.glEnable(GLES20.GL_BLEND);
            GLES20.glBlendFunc(GLES20.GL_SRC_ALPHA, GLES20.GL_ONE_MINUS_SRC_ALPHA);
            GLES20.glEnable(GLES20.GL_SCISSOR_TEST);
            for (int i = 0; i + 8 < v.length; i += 9) {
                // A interface conta y de cima para baixo; o GL, de baixo para cima.
                int esq = (int) v[i + 5], topo = (int) v[i + 6], dir = (int) v[i + 7], base = (int) v[i + 8];
                if (dir <= esq || base <= topo) continue;
                GLES20.glScissor(esq, telaA - base, dir - esq, base - topo);
                GLES20.glUniform4f(ret, v[i], telaA - (v[i + 1] + v[i + 3]), v[i + 2], v[i + 3]);
                GLES20.glUniform1f(raio, Math.min(v[i + 4], Math.min(v[i + 2], v[i + 3]) / 2f));
                GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 6);
            }
            GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
            GLES20.glDisable(GLES20.GL_BLEND);
        }

        /**
         * Cor de destaque a partir do gás desfocado. Pesa mais o que é vivo e
         * claro: pela média simples o céu, quase todo escuro, daria um cinza sem
         * graça no lugar da cor da nebulosa.
         */
        private void lerAcento() {
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, desfY[0]);
            leitura.position(0);
            GLES20.glReadPixels(0, 0, desfL, desfA, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, leitura);
            GLES20.glBindFramebuffer(GLES20.GL_FRAMEBUFFER, 0);
            double r = 0, g = 0, b = 0, peso = 0;
            float[] hsv = new float[3];
            for (int i = 0; i < desfL * desfA * 4; i += 16) {
                int cr = leitura.get(i) & 0xFF, cg = leitura.get(i + 1) & 0xFF, cb = leitura.get(i + 2) & 0xFF;
                Color.RGBToHSV(cr, cg, cb, hsv);
                double w = hsv[1] * hsv[2] * hsv[2];
                r += cr * w; g += cg * w; b += cb * w; peso += w;
            }
            if (peso < 1e-3) return;
            float[] cor = {(float) (r / peso), (float) (g / peso), (float) (b / peso)};
            if (corMedia[0] < 0) {
                System.arraycopy(cor, 0, corMedia, 0, 3);
            } else {
                // Transição de ~1,5 s: a cor segue o céu sem piscar quando ele gira.
                for (int k = 0; k < 3; k++) corMedia[k] += (cor[k] - corMedia[k]) * .3f;
            }
            Color.RGBToHSV((int) corMedia[0], (int) corMedia[1], (int) corMedia[2], hsv);
            final float matiz = hsv[0];
            principal.post(() -> Tema.definirMatiz(matiz));
        }

        /** Mesma pose de câmera do front web: giroscópio vira yaw/pitch e deslocamento. */
        private void pose(float s, float sx, float sy, float[] camera, float[] r) {
            float yaw = sx * .007f, pitch = sy * .006f;
            float cy = (float) Math.cos(yaw), sn = (float) Math.sin(yaw);
            float cp = (float) Math.cos(pitch), sp = (float) Math.sin(pitch);
            float[] m = {cy, 0, -sn, sn * sp, cp, cy * sp, sn * cp, -sp, cy * cp};
            System.arraycopy(m, 0, r, 0, 9);
            camera[0] = sx * .024f;
            camera[1] = sy * .022f + (float) Math.sin(s * .021) * .09f;
            camera[2] = (float) Math.sin(s * .016) * .35f;
        }

        // Somas de senos de períodos incomensuráveis, iguais às do front web:
        // o gás respira sem repetir e o valor fica limitado.
        private final float[][] DERIVA = {
                {0.18f, 0.2110f, 0.00f, 0.11f, 0.0873f, 1.70f},
                {0.15f, 0.1670f, 2.30f, 0.09f, 0.1231f, 0.40f},
                {0.20f, 0.1390f, 4.10f, 0.10f, 0.0977f, 2.90f}};
        private final float[][] CISALHAMENTO = {
                {0.12f, 0.0731f, 0.90f}, {0.14f, 0.0619f, 3.40f}, {0.11f, 0.0857f, 1.90f}};

        private void fluxo(float s, float[] deriva, float[] cis) {
            for (int i = 0; i < 3; i++) {
                float[] d = DERIVA[i];
                deriva[i] = d[0] * (float) Math.sin(d[1] * s + d[2]) + d[3] * (float) Math.sin(d[4] * s + d[5]);
                float[] c = CISALHAMENTO[i];
                cis[i] = c[0] * (float) Math.sin(c[1] * s + c[2]);
            }
        }

        private void uniformes(int p, float[] cam, float[] rot, float t, float[] der, float[] cis) {
            GLES20.glUseProgram(p);
            GLES20.glUniform1i(GLES20.glGetUniformLocation(p, "uNoise"), 0);
            GLES20.glUniform3fv(GLES20.glGetUniformLocation(p, "uCamera"), 1, cam, 0);
            GLES20.glUniformMatrix3fv(GLES20.glGetUniformLocation(p, "uRotation"), 1, false, rot, 0);
            GLES20.glUniform2f(GLES20.glGetUniformLocation(p, "uResolution"), largura, altura);
            GLES20.glUniform1f(GLES20.glGetUniformLocation(p, "uTime"), t);
            GLES20.glUniform3fv(GLES20.glGetUniformLocation(p, "uDrift"), 1, der, 0);
            GLES20.glUniform3fv(GLES20.glGetUniformLocation(p, "uShear"), 1, cis, 0);
        }

        private void atributo(int p, String nome, FloatBuffer dados, int tamanho, int passo, int inicio) {
            int local = GLES20.glGetAttribLocation(p, nome);
            if (local < 0) return;
            dados.position(inicio);
            GLES20.glEnableVertexAttribArray(local);
            // passo em bytes: 0 no quadrado (compacto), 24 nas estrelas (6 floats).
            GLES20.glVertexAttribPointer(local, tamanho, GLES20.GL_FLOAT, false, passo, dados);
        }

        /** Mesmo gerador e mesma ordem de sorteio do front web: o céu é o mesmo. */
        private void criarTexturaEEstrelas() {
            int[] semente = {7331};
            byte[] base = new byte[256 * 256];
            for (int i = 0; i < base.length; i++) base[i] = (byte) (int) Math.floor(sorteio(semente) * 256);
            ByteBuffer pixels = ByteBuffer.allocateDirect(256 * 256 * 4);
            for (int y = 0; y < 256; y++) {
                for (int x = 0; x < 256; x++) {
                    pixels.put(base[y * 256 + x]);
                    pixels.put(base[((y + 17) % 256) * 256 + (x + 37) % 256]);
                    pixels.put((byte) 0);
                    pixels.put((byte) 255);
                }
            }
            pixels.position(0);
            int[] id = new int[1];
            GLES20.glGenTextures(1, id, 0);
            textura = id[0];
            GLES20.glBindTexture(GLES20.GL_TEXTURE_2D, textura);
            GLES20.glTexImage2D(GLES20.GL_TEXTURE_2D, 0, GLES20.GL_RGBA, 256, 256, 0,
                    GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, pixels);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MIN_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_MAG_FILTER, GLES20.GL_LINEAR);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_S, GLES20.GL_REPEAT);
            GLES20.glTexParameteri(GLES20.GL_TEXTURE_2D, GLES20.GL_TEXTURE_WRAP_T, GLES20.GL_REPEAT);

            float[] p = new float[TOTAL * 6];
            for (int i = 0; i < TOTAL; i++) {
                int camada = i % 3;
                double raio = camada == 0 ? 2.6 + sorteio(semente) * 3.0
                        : camada == 1 ? 6 + sorteio(semente) * 5 : 12 + sorteio(semente) * 11;
                double azimute = sorteio(semente) * Math.PI * 2, elevacao = sorteio(semente) * 2 - 1;
                double anel = raio * Math.sqrt(1 - elevacao * elevacao);
                boolean forte = i % 19 == 0;
                float tamanho = forte ? 9f : (float) (3 + sorteio(semente) * 3);
                float tom = (float) sorteio(semente);
                float brilho = forte ? 1.25f : (float) (.65 + sorteio(semente) * .4);
                int k = i * 6;
                p[k] = (float) (Math.sin(azimute) * anel);
                p[k + 1] = (float) (elevacao * raio);
                p[k + 2] = (float) (Math.cos(azimute) * anel);
                p[k + 3] = tamanho;
                p[k + 4] = tom;
                p[k + 5] = brilho;
            }
            pontos = buffer(p);
        }

        /** Math.imul(seed,1664525)+1013904223 >>> 0, dividido por 2^32. */
        private double sorteio(int[] s) {
            s[0] = s[0] * 1664525 + 1013904223;
            return (s[0] & 0xFFFFFFFFL) / 4294967296.0;
        }

        private FloatBuffer buffer(float[] dados) {
            FloatBuffer b = ByteBuffer.allocateDirect(dados.length * 4)
                    .order(ByteOrder.nativeOrder()).asFloatBuffer();
            b.put(dados).position(0);
            return b;
        }

        private int programa(String vertice, String fragmento) {
            int p = GLES20.glCreateProgram();
            int v = shader(GLES20.GL_VERTEX_SHADER, vertice);
            int f = shader(GLES20.GL_FRAGMENT_SHADER, fragmento);
            GLES20.glAttachShader(p, v);
            GLES20.glAttachShader(p, f);
            GLES20.glLinkProgram(p);
            int[] ok = new int[1];
            GLES20.glGetProgramiv(p, GLES20.GL_LINK_STATUS, ok, 0);
            if (ok[0] == 0) throw new IllegalStateException("link: " + GLES20.glGetProgramInfoLog(p));
            GLES20.glDeleteShader(v);
            GLES20.glDeleteShader(f);
            return p;
        }

        private int shader(int tipo, String fonte) {
            int s = GLES20.glCreateShader(tipo);
            GLES20.glShaderSource(s, fonte);
            GLES20.glCompileShader(s);
            int[] ok = new int[1];
            GLES20.glGetShaderiv(s, GLES20.GL_COMPILE_STATUS, ok, 0);
            if (ok[0] == 0) {
                String erro = GLES20.glGetShaderInfoLog(s);
                Log.e(TAG, "shader não compilou: " + erro);
                throw new IllegalStateException(erro);
            }
            return s;
        }

        private String asset(String nome) {
            try (InputStream in = contexto.getAssets().open(nome)) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] b = new byte[4096];
                int n;
                while ((n = in.read(b)) > 0) out.write(b, 0, n);
                return out.toString("UTF-8");
            } catch (java.io.IOException e) {
                throw new IllegalStateException("asset ausente: " + nome, e);
            }
        }
    }
}
