// Página do modo chuva no Chromium, com hub e YouTube simulados:
//   node --test tests/test_chuva_pagina.cjs
// Precisa do Playwright com o Chromium; sem ele, o teste é pulado.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { test } = require('node:test');

let chromium = null;
try { ({ chromium } = require('playwright')); } catch (erro) { /* opcional */ }

const PAGINA = fs.readFileSync(path.join(__dirname, '../nebula_front/chuva.html'));
const ADIANTO_HUB_MS = 5000; // relógio do hub 5 s à frente do navegador
const agoraHub = () => (Date.now() + ADIANTO_HUB_MS) / 1000;

const YT_FALSO = `
class PlayerFalso {
  constructor(id, opcoes) { this.o = opcoes; this.t = 0; this.estado = -1; this.base = performance.now();
    window.__player = this; setTimeout(() => opcoes.events.onReady({ target: this }), 50); }
  agora() { return this.estado === 1 ? this.t + (performance.now() - this.base) / 1000 : this.t; }
  getCurrentTime() { return this.agora() % 600; }
  getDuration() { return 600; }
  getPlayerState() { return this.estado; }
  seekTo(s) { this.t = s; this.base = performance.now(); }
  playVideo() { if (this.estado !== 1) { this.t = this.agora(); this.base = performance.now(); this.estado = 1;
    this.o.events.onStateChange({ data: 1 }); } }
  pauseVideo() { this.t = this.agora(); this.estado = 2; }
  stopVideo() { this.estado = 5; } mute() {} unMute() {} setVolume() {} loadVideoById() {}
}
window.YT = { PlayerState: { UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 }, Player: PlayerFalso };
if (window.onYouTubeIframeAPIReady) window.onYouTubeIframeAPIReady();
`;

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

test('telas do modo chuva tocam o vídeo no mesmo ponto', { skip: !chromium && 'Playwright ausente', timeout: 60000 }, async () => {
  const sessoes = { a: { inicio: agoraHub() - 100 }, futuro: { inicio: 0 } };
  const servidor = http.createServer((pedido, resposta) => {
    const url = new URL(pedido.url, 'http://hub');
    if (url.pathname === '/hub/chuva.html') { resposta.writeHead(200, { 'Content-Type': 'text/html' }); return resposta.end(PAGINA); }
    const sessao = sessoes[url.searchParams.get('k')];
    if (url.pathname !== '/hub/chuva/estado' || !sessao) { resposta.writeHead(401); return resposta.end('{}'); }
    resposta.writeHead(200, { 'Content-Type': 'application/json' });
    resposta.end(JSON.stringify({ ativo: true, agora: agoraHub(), inicio: sessao.inicio, video_id: 'abcdefghijk' }));
  });
  await new Promise((r) => servidor.listen(0, '127.0.0.1', r));
  const navegador = await chromium.launch();
  try {
    const base = `http://127.0.0.1:${servidor.address().port}/hub/chuva.html?k=`;
    const abrir = async (k) => {
      const pagina = await navegador.newPage();
      await pagina.route('https://www.youtube.com/iframe_api', (rota) => rota.fulfill({ contentType: 'application/javascript', body: YT_FALSO }));
      await pagina.goto(base + k);
      return pagina;
    };
    const tempo = (pagina) => pagina.evaluate(() => window.__player && window.__player.getCurrentTime());
    const esperado = (k) => ((agoraHub() - sessoes[k].inicio) % 600 + 600) % 600;

    const notebook = await abrir('a');
    await esperar(3000);
    const pc = await abrir('a'); // o PC entra 3 s depois
    await esperar(3000);
    const [tn, tp, alvo] = [await tempo(notebook), await tempo(pc), esperado('a')];
    assert.ok(Math.abs(tn - alvo) < 0.6, `notebook em ${tn}, esperado ${alvo}`);
    assert.ok(Math.abs(tn - tp) < 0.6, `telas separadas por ${Math.abs(tn - tp)} s`);

    await notebook.evaluate(() => { window.__player.t += 6; }); // o vídeo travou e desalinhou
    await esperar(4600);
    assert.ok(Math.abs(await tempo(notebook) - esperado('a')) < 0.6, 'não realinhou');

    sessoes.futuro.inicio = agoraHub() + 3; // a sessão começa 3 s depois de a tela abrir
    const futuro = await abrir('futuro');
    await esperar(1200);
    assert.deepEqual(await futuro.evaluate(() => [window.__player.getPlayerState(), window.__player.getCurrentTime() < 0.05]), [2, true]);
    await esperar(3300);
    assert.ok(Math.abs(await tempo(futuro) - esperado('futuro')) < 0.6, 'não começou no instante zero');

    const intruso = await abrir('errada');
    await esperar(1500);
    assert.equal(await intruso.evaluate(() => Boolean(window.__player)), false);
  } finally {
    await navegador.close();
    servidor.close();
  }
});
