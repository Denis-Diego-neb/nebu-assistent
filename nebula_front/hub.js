/* Console do Nebula Home Hub. Mesma cena do front espacial ao fundo; na frente,
   o log real do servidor, buscado do próprio processo que serve esta página. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------- cena
  const canvas = $('cosmos');
  const ctx = canvas.getContext('2d');
  const volumeCanvas = document.createElement('canvas');
  volumeCanvas.id = 'nebula-volume';
  volumeCanvas.setAttribute('aria-hidden', 'true');
  canvas.before(volumeCanvas);
  const volume = window.NebulaVolume?.create(volumeCanvas);
  if (!volume) volumeCanvas.remove();

  let width = innerWidth, height = innerHeight, ratio = 1;
  let time = 0, last = 0, paused = reduceMotion;
  let angle = 0;

  let seed = 91733;
  const random = () => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed / 4294967296; };
  const stars = Array.from({ length: 260 }, () => ({
    x: random(), y: random(), r: .3 + random() * .8,
    a: .12 + random() * .5, phase: random() * Math.PI * 2, speed: .0003 + random() * .0005,
  }));

  function resize() {
    width = innerWidth; height = innerHeight;
    ratio = Math.min(devicePixelRatio, 1.25);
    canvas.width = width * ratio; canvas.height = height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    draw();
  }

  function draw() {
    const hue = 215 + 145 * (.5 - .5 * Math.cos(time * Math.PI / 90000));
    document.documentElement.style.setProperty('--accent-hue', hue.toFixed(1));
    ctx.clearRect(0, 0, width, height);
    if (volume) { volume.draw(time, angle, 0, 0, width, height); return; }
    // Sem WebGL o fundo vira um campo de estrelas simples, sem custo de shader.
    for (const star of stars) {
      const alpha = star.a * (.75 + .25 * Math.sin(time * star.speed + star.phase));
      ctx.fillStyle = 'rgba(234,240,255,' + alpha.toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(star.x * width, star.y * height, star.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function tick(now) {
    requestAnimationFrame(tick);
    if (document.hidden) { last = 0; return; }
    if (!last) { last = now; draw(); return; }
    if (now - last < 40) return;
    const delta = Math.min(now - last, 60);
    last = now;
    if (paused) return;
    time += delta;
    angle += delta * .000035;
    draw();
  }

  function syncMotion() {
    document.body.classList.toggle('paused', paused);
    $('motion').textContent = paused ? '▷' : 'Ⅱ';
    $('motion').setAttribute('aria-pressed', String(paused));
    const label = paused ? 'Retomar animações' : 'Pausar animações';
    $('motion').setAttribute('aria-label', label);
    $('motion').title = label;
  }
  $('motion').onclick = () => { paused = !paused; syncMotion(); draw(); };
  addEventListener('resize', resize);

  // ----------------------------------------------------------------- log
  const log = $('log');
  const follow = $('follow');
  const MAX_LINES = 600;
  let cursor = 0, offline = 0;

  function classify(message) {
    const match = /→\s*(\d{3})\s*$/.exec(message);
    if (!match) return 'note';
    const status = Number(match[1]);
    if (status === 401 || status === 403) return 'denied';
    if (status >= 400) return 'failed';
    return 'ok';
  }

  function append(lines) {
    if (!lines.length) return;
    const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    const batch = document.createDocumentFragment();
    for (const raw of lines) {
      const separator = raw.indexOf('  ');
      const stamp = separator > 0 ? raw.slice(0, separator) : '';
      const message = separator > 0 ? raw.slice(separator + 2) : raw;
      const line = document.createElement('span');
      line.className = 'hub-line ' + classify(message);
      if (stamp) {
        const when = document.createElement('span');
        when.className = 'hub-time';
        when.textContent = stamp.slice(11) || stamp;
        when.title = stamp;
        line.append(when);
      }
      line.append(document.createTextNode(message));
      batch.append(line);
    }
    log.querySelector('.hub-empty')?.remove();
    log.append(batch);
    while (log.childElementCount > MAX_LINES) log.firstElementChild.remove();
    if (follow.checked && atEnd) log.scrollTop = log.scrollHeight;
  }

  function showEmpty() {
    log.replaceChildren();
    const empty = document.createElement('span');
    empty.className = 'hub-empty';
    empty.textContent = 'Nenhuma linha nesta visualização. O arquivo de log do servidor continua intacto.';
    log.append(empty);
  }
  $('clear').onclick = showEmpty;
  showEmpty();

  // -------------------------------------------------------------- estado
  function setLink(state, label) {
    const pill = $('link-state');
    pill.textContent = label;
    pill.classList.toggle('online', state === 'online');
    pill.classList.toggle('offline', state === 'offline');
  }

  function renderSprints(sprints) {
    const target = $('sprints');
    const summary = sprints?.data;
    if (!summary || !Object.keys(summary).length) {
      target.textContent = 'Aguardando resumo do PC…';
      target.classList.remove('alert');
      return;
    }
    const counts = summary.counts || {};
    const age = sprints.age_seconds;
    const lines = [
      `${summary.paused ? 'PAUSADA' : 'ATIVA'} · ${summary.evaluated ?? 0}/${summary.total ?? 0} avaliadas · `
      + `${counts.waiting_gemini ?? 0} aguardando Gemini · CPU até ${summary.threads ?? '?'} threads / `
      + `intervalo ${summary.interval_seconds ?? '?'}s`,
    ];
    if (age != null && age > 60) lines.push(`SEM ATUALIZAÇÃO DO PC há ${age}s`);
    if (sprints.pending_command) lines.push('Comando pendente: ' + sprints.pending_command);
    for (const alert of (summary.alerts || []).slice(0, 2)) lines.push(String(alert));
    for (const item of (summary.recent || []).slice(0, 2)) {
      const scores = Object.entries(item.rewards || {})
        .map(([name, reward]) => `${name}: ${reward.delta > 0 ? '+' : ''}${reward.delta ?? 0}`)
        .join(' | ');
      lines.push(`${item.job}: ${scores}\n${String(item.summary || '').slice(0, 260)}`);
    }
    target.textContent = lines.join('\n');
    target.classList.toggle('alert', Boolean((summary.alerts || []).length) || (age != null && age > 60));
  }

  async function poll() {
    try {
      const response = await fetch('/hub/state', { cache: 'no-store' });
      if (!response.ok) throw new Error('estado ' + response.status);
      const state = await response.json();
      const metrics = state.metrics || {};
      $('m-total').textContent = metrics.total ?? 0;
      $('m-clients').textContent = metrics.active_clients ?? 0;
      $('m-denied').textContent = metrics.denied ?? 0;
      $('m-uptime').textContent = state.uptime || '00:00:00';
      $('last-connection').textContent =
        `Última conexão: ${metrics.last_client || '—'}  ·  sucesso: ${metrics.successful ?? 0}  ·  erros: ${metrics.failed ?? 0}`;
      $('hub-subtitle').textContent =
        `NOTEBOOK · PORTA ${state.port} · VERSÃO ${state.version} · LOG ${state.log_file || ''}`;
      renderSprints(state.sprints);
      offline = 0;
      setLink('online', '● SERVIDOR ATIVO');
    } catch {
      offline += 1;
      // Uma falha isolada não significa queda: só avisa depois de duas seguidas.
      if (offline >= 2) setLink('offline', '● SEM RESPOSTA');
    }
  }

  async function pollEvents() {
    try {
      const response = await fetch('/hub/events?after=' + cursor, { cache: 'no-store' });
      if (!response.ok) throw new Error('eventos ' + response.status);
      const data = await response.json();
      if (data.reset) showEmpty();
      append(data.lines || []);
      cursor = data.cursor ?? cursor;
    } catch {
      /* A próxima rodada tenta de novo; o indicador de estado já avisa. */
    }
  }


  // ------------------------------------------------------------ terminal
  // Sessões do hub: o usuário digita aqui e as duas IAs usam as mesmas rotas
  // por HTTP. A saída entra sempre como texto, nunca como HTML.
  let sessaoAtiva = null, cursorTerminal = 0, sessoes = [];

  function linhaTerminal(texto) {
    const linha = document.createElement('div');
    linha.className = 'hub-line ' + classify(texto);
    linha.textContent = texto;
    return linha;
  }

  function escreverTerminal(linhas) {
    if (!linhas.length) return;
    const alvo = $('terminal-output');
    const colado = alvo.scrollTop + alvo.clientHeight >= alvo.scrollHeight - 40;
    const lote = document.createDocumentFragment();
    for (const l of linhas) lote.appendChild(linhaTerminal(l));
    alvo.appendChild(lote);
    while (alvo.childElementCount > 4000) alvo.removeChild(alvo.firstElementChild);
    if (colado) alvo.scrollTop = alvo.scrollHeight;
  }

  function selecionar(id) {
    if (sessaoAtiva === id) return;
    sessaoAtiva = id;
    cursorTerminal = 0;
    $('terminal-output').textContent = '';
    desenharAbas();
    if (id) pollTerminal();
  }

  function desenharAbas() {
    const abas = $('terminal-tabs');
    abas.textContent = '';
    for (const s of sessoes) {
      const aba = document.createElement('button');
      aba.type = 'button';
      aba.className = 'hub-tab' + (s.id === sessaoAtiva ? ' active' : '') +
        (s.executando ? ' rodando' : '');
      aba.textContent = (s.executando ? '● ' : '○ ') + s.comando.slice(0, 42);
      aba.title = `${s.comando}\n${s.cwd}\npedido por ${s.autor}`;
      aba.onclick = () => selecionar(s.id);
      abas.appendChild(aba);
    }
    const atual = sessoes.find(s => s.id === sessaoAtiva);
    $('terminal-stop').disabled = !(atual && atual.executando);
    $('terminal-info').textContent = !atual ? (sessoes.length ? 'Escolha uma sessão.' : 'Nenhuma sessão.')
      : atual.executando ? `rodando há ${Math.round(atual.segundos)} s · ${atual.autor}`
      : `código ${atual.codigo} · ${Math.round(atual.segundos)} s · ${atual.autor}`;
  }

  async function listarSessoes() {
    try {
      const resposta = await fetch('/hub/terminal', { cache: 'no-store' });
      if (!resposta.ok) return;
      const dados = await resposta.json();
      sessoes = dados.sessions || [];
      // Desligado por padrão (MCP GOAL, INV-003): o console diz como ligar em vez
      // de deixar alguém descobrir pelo erro.
      const politica = dados.policy || {};
      const ligado = Boolean(politica.enabled);
      $('terminal-command').disabled = !ligado;
      $('terminal-cwd').disabled = !ligado;
      $('terminal-form').querySelector('button[type="submit"]').disabled = !ligado;
      $('terminal-status').textContent = ligado
        ? `Ligado em ${(politica.folders || []).join(', ')} · tempo limite ${politica.timeout_s} s · tudo auditado.`
        : `Terminal desligado por política (MCP GOAL, INV-003). Para ligar, crie ${politica.file || 'terminal_policy.json'} ` +
          'no notebook com "habilitado": true e as pastas permitidas.';
      if (sessaoAtiva && !sessoes.some(s => s.id === sessaoAtiva)) selecionar(null);
      else desenharAbas();
    } catch { /* o indicador de estado já avisa se o hub caiu */ }
  }

  async function pollTerminal() {
    if (!sessaoAtiva) return;
    const alvo = sessaoAtiva;
    try {
      const resposta = await fetch(`/hub/terminal/${alvo}?after=${cursorTerminal}`, { cache: 'no-store' });
      if (!resposta.ok) return;
      const dados = await resposta.json();
      if (sessaoAtiva !== alvo) return;
      if (dados.reset) $('terminal-output').textContent = '';
      escreverTerminal(dados.lines || []);
      cursorTerminal = dados.cursor ?? cursorTerminal;
    } catch { /* a próxima rodada tenta de novo */ }
  }

  $('terminal-form').onsubmit = async evento => {
    evento.preventDefault();
    const comando = $('terminal-command').value.trim();
    if (!comando) return;
    $('terminal-status').textContent = 'Iniciando…';
    try {
      const resposta = await fetch('/hub/terminal', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: comando, cwd: $('terminal-cwd').value.trim() || null,
                               author: 'usuario' }),
      });
      const dados = await resposta.json().catch(() => ({}));
      if (!resposta.ok) { $('terminal-status').textContent = dados.error || `Falhou (${resposta.status}).`; return; }
      $('terminal-command').value = '';
      $('terminal-status').textContent = `Sessão ${dados.id} em ${dados.cwd}`;
      await listarSessoes();
      selecionar(dados.id);
    } catch (erro) {
      $('terminal-status').textContent = 'Não consegui falar com o hub.';
    }
  };

  $('terminal-stop').onclick = async () => {
    if (!sessaoAtiva) return;
    $('terminal-stop').disabled = true;
    try { await fetch(`/hub/terminal/${sessaoAtiva}/stop`, { method: 'POST' }); }
    finally { listarSessoes(); }
  };

  for (const button of document.querySelectorAll('[data-sprint]')) {
    button.onclick = async () => {
      button.disabled = true;
      try {
        await fetch('/hub/command', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ command: button.dataset.sprint }),
        });
      } finally {
        button.disabled = false;
      }
    };
  }

  syncMotion();
  resize();
  requestAnimationFrame(tick);
  poll(); pollEvents(); listarSessoes();
  setInterval(poll, 1500);
  setInterval(pollEvents, 700);
  setInterval(listarSessoes, 2500);
  setInterval(pollTerminal, 700);
})();
