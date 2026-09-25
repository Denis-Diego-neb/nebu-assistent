# nebula_sky

Fonte única da nebulosa dos apps nativos: o Android lê estes arquivos como
assets do APK e o app nativo do PC lê os mesmos. Nada aqui passa por rede.

GLSL ES 1.00 (OpenGL ES 2.0). A precisão não fica nos arquivos: cada carregador
declara a sua por estágio, porque nem toda GPU de celular aceita `highp` no
fragment shader. `common.glsl` é colado antes de `volume.frag` e `stars.vert`.

| arquivo | papel |
| --- | --- |
| `common.glsl` | ruído, densidade do gás e cor; uniformes compartilhados |
| `quad.vert` + `volume.frag` | raymarch do gás, desenhado num quadrado de tela cheia |
| `stars.vert` + `stars.frag` | estrelas como pontos, escurecidas pelo gás na frente |

Uniformes calculados na CPU, iguais nos dois apps: `uCamera`, `uRotation`
(pose da câmera, que o giroscópio desloca), `uDrift` e `uShear` (deriva lenta
do gás, somas de senos de períodos incomensuráveis), `uTime`, `uResolution`.

`SEM_TEXTURA_NO_VERTICE` desliga o escurecimento das estrelas em GPUs sem
leitura de textura no vertex shader, que é opcional em OpenGL ES 2.0.
