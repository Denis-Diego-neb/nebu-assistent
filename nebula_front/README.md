# Espaço — front compartilhado da Nebula

HTML, CSS e JS sem npm e sem CDN. Uma cópia só, servida em três lugares:

| Onde | Endereço | Quem serve |
| --- | --- | --- |
| Nebula no PC (EXE) | `http://127.0.0.1:8765/espaco/` | `remote_server.py` |
| Nebula no celular (APK) | `<painel>/espaco/` no WebView | `remote_server.py` |
| Nebula Home Hub (notebook) | `http://127.0.0.1:8766/hub/` | `notebook_power_server/power_server.py` |

Para mexer no visual sem subir a Nebula inteira: `py -m http.server 5500` nesta
pasta. A cena aparece, mas as seções ficam vazias — elas dependem das APIs do
painel.

## Arquivos

- `index.html` — o Espaço: conversa, casa, projetos, memória, áudio, telefone e terminal.
- `nebula-app.js` — as funções reais; cada seção chama as APIs do painel.
- `app.js` — casca: cena, navegação, sensor do telefone e pausa das animações.
- `nebula-scene.js` — nebulosa volumétrica e estrelas em WebGL.
- `fullscreen.js` — F11 no EXE, no APK e no hub.
- `hub.html` / `hub.js` / `hub.css` — console do Home Hub com o log do servidor ao vivo.
- `style.css` — layout; `atmosphere.css` — acentos; `panel.css` — os controles do painel.

## O que cada seção faz

Nada aqui é demonstração: são as mesmas APIs que a janela do PC e o painel do
celular já usavam.

| Seção | APIs |
| --- | --- |
| Conversa | `/api/conversation`, `/api/nebula`, `/api/feedback`, `/api/pause`, `/api/state`, `/api/show` |
| Casa | `/api/control` — modo mudo, modos, abajur, ar-condicionado, dispositivos, presets, telemetria |
| Projetos e workspace | `/api/projects`, `/api/project`, `/api/codex`, `/api/job`, `/api/terminal`, `/api/vscode` |
| Memória | `/api/idea`, `/api/conversation` |
| Áudio | `/api/media`, `/api/media/action` |
| Telefone | `/api/device`, `/api/device/command`, `/api/transfer/messages`, `/api/transfer/message` |
| Terminal | `/api/terminal` |

Cada seção só consulta enquanto está aberta e a aba está visível, para não
manter o PC respondendo à toa.

## Celular e conversa Dupla

A navegação inferior oferece Conversa, Dupla, Casa e Menu; o Menu mostra todas
as oito páginas em telas pequenas. Em Dupla, Enviar inicia desenvolvimento real
no projeto selecionado: Astra implementa e Claude revisa e testa. Os comandos e
resultados aparecem em Atividade; Interromper agora encerra a rodada, mantendo
as alterações já feitas. As sessões são retomadas em novas mensagens do mesmo
pedido; não controlam as conversas abertas nos editores.

O APK carrega esse front do PC, por isso a atualização visual vem do servidor.
Fora de casa, mantenha PC e Nebula ligados e Tailscale conectado no PC e no
telefone. O app já tenta o endereço privado Tailscale após a LAN. Sem essa
conexão, o endereço da rede doméstica não funciona na faculdade.

## Cena

`nebula-scene.js` renderiza um campo volumétrico procedural com WebGL: a câmera
amostra o interior das nuvens, com absorção de luz e faixas de vermelho, rosa,
magenta, violeta, lilás e azul. As estrelas têm posições fixas em três faixas de
profundidade ao redor da câmera. Cada clique de navegação move o cenário para a
direita. A inclinação do telefone entra pelo botão **Movimento do telefone**, que
pede permissão ao navegador e depende de contexto seguro. Sem WebGL, há uma
versão em camadas 2D. O acento da interface acompanha o hue da cena — o mesmo
passeio de cor é reproduzido na janela nativa do hub.

A posição e o tempo da cena ficam em `sessionStorage`, então recarregar a aba
mantém o mesmo enquadramento. Pausar as animações congela tudo, inclusive o
sensor.

## Tela cheia

F11 alterna a tela cheia nos três lugares, e há um botão no cabeçalho:

- **EXE** — a janela é uma janela de aplicativo do Chromium aberta por `front_window.py`.
- **APK** — `fullscreen.js` chama a ponte `NebulaHost`, que esconde as barras do
  sistema; o F11 de um teclado Bluetooth também funciona.
- **Hub** — no console web pelo F11, e na janela Tk pelo mesmo F11.

## Acesso

O Espaço exige sessão do painel. A Nebula no PC abre a janela com um bilhete de
uso único, válido por 90 segundos e aceito só no loopback (`criar_ticket_espaco`
em `remote_server.py`); o APK troca a credencial do aparelho por uma sessão em
`/api/device-session`. Pela rede, sem sessão, `/espaco/` manda para a tela do PIN.
O console do hub é liberado no loopback e exige `X-Nebula-Power-Token` de fora.
