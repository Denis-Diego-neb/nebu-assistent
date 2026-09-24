/* Funções reais do Espaço. Cada seção fala com as mesmas APIs que o painel
   móvel e a janela do PC já usam — nada aqui é demonstração. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const shell = window.NebulaShell;

  // --------------------------------------------------------------- rede
  const TIMEOUT = 15000;

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeout || TIMEOUT);
    try {
      const init = { signal: controller.signal, cache: 'no-store', credentials: 'same-origin' };
      if (options.body !== undefined) {
        init.method = 'POST';
        init.headers = { 'Content-Type': 'application/json' };
        init.body = JSON.stringify(options.body);
      }
      const response = await fetch(path, init);
      if (response.status === 401) {
        setLink('offline', 'SESSÃO EXPIRADA');
        throw new Error('A sessão expirou. Abra o Espaço de novo pela Nebula.');
      }
      let data = {};
      try { data = await response.json(); } catch { data = {}; }
      if (!response.ok) {
        const falha = new Error(data.error || `O PC respondeu ${response.status}.`);
        falha.status = response.status;
        falha.dados = data;
        throw falha;
      }
      setLink('online', 'CONECTADA');
      return data;
    } catch (error) {
      if (error.name === 'AbortError') {
        setLink('offline', 'SEM RESPOSTA');
        throw new Error('O computador não respondeu a tempo.');
      }
      if (error instanceof TypeError) setLink('offline', 'SEM CONEXÃO');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  const get = path => request(path);
  const post = (path, body = {}) => request(path, { body });

  let linkState = '';
  function setLink(state, label) {
    if (linkState === state + label) return;
    linkState = state + label;
    const pill = $('link-state');
    pill.textContent = label;
    pill.classList.toggle('online', state === 'online');
    pill.classList.toggle('offline', state === 'offline');
  }

  function say(element, message, tone = '') {
    const target = typeof element === 'string' ? $(element) : element;
    if (!target) return;
    target.textContent = message;
    target.classList.toggle('error', tone === 'error');
    target.classList.toggle('good', tone === 'good');
  }

  async function run(statusId, work, pendente = 'Enviando…') {
    say(statusId, pendente);
    try {
      const result = await work();
      if (result && result.message) say(statusId, result.message, 'good');
      else say(statusId, '');
      return result;
    } catch (error) {
      say(statusId, error.message, 'error');
      return null;
    }
  }

  // ---------------------------------------------------------------- voz
  function ditar(target, statusId) {
    const Reconhecimento = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Reconhecimento) {
      say(statusId, 'Use o microfone do teclado neste campo.');
      target.focus();
      return;
    }
    const reconhecimento = new Reconhecimento();
    const base = target.value.trim();
    reconhecimento.lang = 'pt-BR';
    reconhecimento.interimResults = true;
    reconhecimento.onstart = () => say(statusId, 'Ouvindo…');
    reconhecimento.onresult = event => {
      let texto = '';
      for (let i = event.resultIndex; i < event.results.length; i++) texto += event.results[i][0].transcript;
      target.value = (base ? base + ' ' : '') + texto.trim();
    };
    reconhecimento.onerror = () => say(statusId, 'Não consegui ouvir. Tente de novo ou digite.');
    reconhecimento.onend = () => say(statusId, 'Pronta.');
    try { reconhecimento.start(); } catch { say(statusId, 'O microfone já está em uso.'); }
  }

  // ----------------------------------------------------------- conversa
  const messages = $('messages');
  let assinaturaConversa = '';

  function renderConversa(lista, alvo, limite) {
    const itens = limite ? lista.slice(-limite) : lista;
    alvo.replaceChildren();
    for (const item of itens) {
      const bloco = document.createElement('div');
      const autor = String(item.author || '');
      bloco.className = 'message ' + (autor === 'Nebula' ? 'nebula' : 'user');
      const quem = document.createElement('b');
      quem.textContent = autor;
      bloco.append(quem, document.createTextNode(' ' + String(item.text || '')));
      alvo.append(bloco);
    }
    alvo.scrollTop = alvo.scrollHeight;
  }

  async function carregarConversa() {
    const data = await get('/api/conversation');
    const lista = data.messages || [];
    // Redesenhar a cada rodada apagaria a seleção de texto do usuário: só
    // refaz quando a conversa muda ou quando o destino ainda está vazio.
    const historico = $('history');
    const assinatura = lista.length + ':' + (lista[lista.length - 1]?.id || '');
    const faltaPintar = !messages.childElementCount
      || (shell.view === 'memory' && !historico.childElementCount);
    if (assinatura !== assinaturaConversa || faltaPintar) {
      assinaturaConversa = assinatura;
      renderConversa(lista, messages, 30);
      document.getElementById('chat').classList.toggle('has-messages', lista.length > 0);
      renderConversa(lista, historico, 0);
    }
    return lista;
  }

  $('chat-form').addEventListener('submit', async event => {
    event.preventDefault();
    const campo = $('prompt');
    const comando = campo.value.trim();
    if (!comando) return;
    campo.value = '';
    const resultado = await run('chat-status', () => post('/api/nebula', { command: comando }),
      'Enviando à Nebula…');
    if (resultado) carregarConversa().catch(() => {});
  });
  $('chat-listen').addEventListener('click', () => ditar($('prompt'), 'chat-status'));
  for (const botao of document.querySelectorAll('[data-prompt]')) {
    botao.addEventListener('click', () => { $('prompt').value = botao.dataset.prompt; $('prompt').focus(); });
  }
  for (const botao of document.querySelectorAll('[data-feedback]')) {
    botao.addEventListener('click', () => run('feedback-status', () => post('/api/feedback', {
      avaliacao: botao.dataset.feedback,
      comentario: $('feedback-comment').value.trim(),
      canal: 'espaco',
    }), 'Salvando…').then(() => { $('feedback-comment').value = ''; }));
  }
  for (const botao of document.querySelectorAll('[data-pause]')) {
    botao.addEventListener('click', () => run('chat-status',
      async () => { mostrarPausa((await post('/api/pause', { paused: botao.dataset.pause === '1' })).paused); return null; },
      'Atualizando…'));
  }
  $('show-window').addEventListener('click', () => run('chat-status', () => post('/api/show'), 'Chamando…'));
  $('show-window-workspace').addEventListener('click', () => run('actions-status', () => post('/api/show'), 'Chamando…'));

  function mostrarPausa(pausada) {
    say('pause-state', pausada
      ? 'Nebula pausada: novos comandos estão bloqueados.'
      : 'Nebula ativa e pronta.');
  }

  async function atualizarEstado() {
    const estado = await get('/api/state');
    mostrarPausa(estado.paused);
    projetoAtivo = estado.project || projetoAtivo;
    $('terminal-project').textContent = 'nebula / ' + nomeDaPasta(projetoAtivo);
  }

  // --------------------------------------------------------------- casa
  const ROTULOS = {
    manual: 'Desativado / manual', ambilight: 'Ambilight', music: 'Música', torch: 'Tocha',
    rpm: 'RPM / FuelTech', boost: 'Boost', beamng: 'BeamNG', ambilight_rpm: 'Ambilight + RPM',
    turbo: 'Pressão do turbo', independent: 'Independente por dispositivo',
    static: 'Estático', onda: 'WRGB Wave', onda_curta: 'WRGB Wave rápida', ciclo: 'Color Cycle',
    respirar: 'Breathing', reativo: 'Reactive', ripple: 'Ripple', linha: 'Linha',
    estrelas: 'Estrelas', florescer: 'Florescer', arco_iris_vertical: 'Arco-íris vertical',
    furacao: 'Furacão', acumular: 'Acumular', visor: 'Visor', arco_iris_circular: 'Arco-íris circular',
  };
  const DISPOSITIVOS = { lamp: 'Abajur', keyboard: 'Teclado', controller: 'Controle', mobile: 'Celular' };
  const MODOS_PRINCIPAIS = ['manual', 'ambilight', 'music', 'torch', 'rpm', 'boost', 'beamng'];
  const AR_MODOS = { cool: 'Ar frio', heat: 'Ar quente', auto: 'Auto', fan: 'Ventilar', dry: 'Desumidificar' };
  const AR_VENTILACAO = { auto: 'Auto', low: 'Fraco', medium: 'Médio', high: 'Forte' };

  const rotulo = chave => ROTULOS[chave] || String(chave || '—');
  let controle = null;
  let ajustandoControle = false;

  function chip(texto, ativo, acao) {
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'chip' + (ativo ? ' active' : '');
    botao.textContent = texto;
    botao.addEventListener('click', acao);
    return botao;
  }

  function acaoControle(action, value, statusId = 'casa-error') {
    return run(statusId, async () => {
      const resposta = await post('/api/control', { action, value });
      if (resposta.state) pintarControle(resposta.state);
      return resposta;
    }, 'Enviando…');
  }

  function pintarControle(estado) {
    controle = estado;
    if (!estado || estado.ready === false) {
      say('casa-subtitle', 'A Nebula ainda está iniciando no computador.');
      return;
    }
    say('casa-subtitle', `Modo ${rotulo(estado.mode)} · abajur ${estado.lamp || '—'} · teclado ${estado.keyboard || '—'}`);
    say('casa-error', estado.error ? String(estado.error) : '', estado.error ? 'error' : '');

    const mudo = $('mute-toggle');
    mudo.setAttribute('aria-pressed', String(Boolean(estado.muted)));
    mudo.textContent = estado.muted ? 'Modo mudo ativo' : 'Modo mudo';

    const modos = $('modes');
    modos.replaceChildren();
    for (const modo of MODOS_PRINCIPAIS) {
      modos.append(chip(rotulo(modo), estado.mode === modo, () => acaoControle('mode', modo)));
    }
    say('mode-detail', estado.receiving
      ? `Telemetria ${estado.telemetry_valid ? 'válida' : 'instável'} · fonte ${estado.telemetry_source || '—'}`
      : 'Sem telemetria recebida no momento.');

    // Abajur
    say('lamp-status', estado.lamp_power === null || estado.lamp_power === undefined
      ? String(estado.lamp || '—')
      : `${estado.lamp_power ? 'Ligado' : 'Desligado'} · ${estado.lamp_selection || estado.lamp || '—'}`);
    if (!ajustandoControle && typeof estado.effect_color === 'string' && /^#[0-9a-f]{6}$/i.test(estado.effect_color)) {
      $('lamp-color').value = estado.effect_color;
    }

    // Ar-condicionado
    const ar = estado.air || {};
    $('air-temperature').textContent = ar.temperature ? `${ar.temperature} °C` : '—';
    const suportadas = new Set(ar.supported_actions || ['power', 'temperature', 'mode', 'fan']);
    const modosAr = $('air-modes');
    modosAr.replaceChildren();
    if (suportadas.has('mode')) {
      for (const [chave, nome] of Object.entries(AR_MODOS)) {
        modosAr.append(chip(nome, ar.mode === chave, () => acaoControle('air.mode', chave, 'air-status')));
      }
    }
    const ventilacao = $('air-fans');
    ventilacao.replaceChildren();
    if (suportadas.has('fan')) {
      for (const [chave, nome] of Object.entries(AR_VENTILACAO)) {
        ventilacao.append(chip('Vento ' + nome, ar.fan === chave, () => acaoControle('air.fan', chave, 'air-status')));
      }
    }
    say('air-status', ar.error ? String(ar.error) : `${ar.power ? 'Ligado' : 'Desligado'} · ${ar.mode_label || ''} ${ar.fan_label ? '· vento ' + ar.fan_label : ''}`.trim(),
      ar.error ? 'error' : '');

    // Dispositivos
    const lista = $('devices');
    lista.replaceChildren();
    for (const [nome, ajustes] of Object.entries(estado.devices || {})) {
      const linha = document.createElement('div');
      linha.className = 'device';
      const titulo = document.createElement('strong');
      titulo.textContent = DISPOSITIVOS[nome] || nome;
      const seletor = document.createElement('select');
      seletor.setAttribute('aria-label', 'Modo do ' + (DISPOSITIVOS[nome] || nome));
      for (const modo of (estado.device_modes || {})[nome] || []) {
        const opcao = document.createElement('option');
        opcao.value = modo;
        opcao.textContent = rotulo(modo);
        opcao.selected = ajustes.mode === modo;
        seletor.append(opcao);
      }
      seletor.addEventListener('change', () => acaoControle('device.mode', { device: nome, mode: seletor.value }));
      linha.append(titulo, seletor);
      if (['lamp', 'keyboard', 'controller'].includes(nome)) {
        linha.append(chip(ajustes.afterfire ? 'Flash ligado' : 'Flash', Boolean(ajustes.afterfire),
          () => acaoControle('device.flash', { device: nome, enabled: !ajustes.afterfire })));
      }
      if (ajustes.error) {
        const erro = document.createElement('span');
        erro.className = 'hint error';
        erro.textContent = String(ajustes.error);
        linha.append(erro);
      }
      lista.append(linha);
    }

    // Presets
    const presets = $('presets');
    presets.replaceChildren();
    for (const nome of estado.presets || []) {
      const aplicar = chip(nome, estado.active_preset === nome, () => acaoControle('preset.apply', nome));
      const excluir = document.createElement('button');
      excluir.type = 'button';
      excluir.className = 'chip ghost';
      excluir.title = 'Excluir o preset ' + nome;
      excluir.textContent = '×';
      excluir.addEventListener('click', () => acaoControle('preset.delete', nome));
      const par = document.createElement('span');
      par.className = 'preset';
      par.append(aplicar, excluir);
      presets.append(par);
    }
    if (!(estado.presets || []).length) {
      const vazio = document.createElement('span');
      vazio.className = 'hint';
      vazio.textContent = 'Nenhum preset salvo ainda.';
      presets.append(vazio);
    }

    // Telemetria
    const leituras = [
      ['RPM', estado.rpm], ['Marcha', estado.gear], ['Acelerador', estado.throttle_percent, '%'],
      ['Velocidade', estado.speed_kmh, ' km/h'], ['Turbo', estado.turbo_bar, ' bar'],
      ['Boost', estado.boost_percent, '%'], ['Óleo', estado.oil_temp, ' °C'],
      ['Água', estado.water_temp, ' °C'], ['Combustível', estado.fuel_percent, '%'],
    ];
    const grade = $('telemetry');
    grade.replaceChildren();
    for (const [nome, valor, unidade = ''] of leituras) {
      if (valor === null || valor === undefined) continue;
      const celula = document.createElement('div');
      const numero = document.createElement('strong');
      numero.textContent = (typeof valor === 'number' ? Math.round(valor * 10) / 10 : valor) + unidade;
      const legenda = document.createElement('small');
      legenda.textContent = nome;
      celula.append(numero, legenda);
      grade.append(celula);
    }
    if (!grade.childElementCount) {
      const vazio = document.createElement('span');
      vazio.className = 'hint';
      vazio.textContent = 'Nenhuma telemetria ativa.';
      grade.append(vazio);
    }
  }

  async function carregarControle() {
    const resposta = await get('/api/control');
    pintarControle(resposta.state);
  }

  $('mute-toggle').addEventListener('click',
    () => acaoControle('mute', $('mute-toggle').getAttribute('aria-pressed') !== 'true'));
  for (const botao of document.querySelectorAll('[data-lamp]')) {
    botao.addEventListener('click', () => acaoControle('lamp.power', botao.dataset.lamp === 'on', 'lamp-status'));
  }
  $('lamp-color').addEventListener('change', () => acaoControle('lamp.color', $('lamp-color').value, 'lamp-status'));
  $('lamp-color').addEventListener('input', () => { ajustandoControle = true; });
  for (const [campo, acao, sufixo] of [['lamp-brightness', 'lamp.brightness', '%'], ['lamp-temperature', 'lamp.temperature', '%']]) {
    const controlo = $(campo);
    controlo.addEventListener('input', () => {
      ajustandoControle = true;
      $(campo + '-value').textContent = controlo.value + sufixo;
    });
    controlo.addEventListener('change', () => {
      ajustandoControle = false;
      acaoControle(acao, Number(controlo.value), 'lamp-status');
    });
  }
  for (const botao of document.querySelectorAll('[data-air]')) {
    botao.addEventListener('click', () => acaoControle('air.power', botao.dataset.air === 'on', 'air-status'));
  }
  for (const botao of document.querySelectorAll('[data-air-temp]')) {
    botao.addEventListener('click', () => {
      const atual = Number(controle?.air?.temperature || 22);
      const minimo = Number(controle?.air?.temperature_min || 16);
      const alvo = Math.max(minimo, Math.min(30, atual + Number(botao.dataset.airTemp)));
      acaoControle('air.temperature', alvo, 'air-status');
    });
  }
  $('preset-save').addEventListener('click', () => {
    const nome = $('preset-name').value.trim();
    if (!nome) { say('casa-error', 'Dê um nome ao preset antes de salvar.', 'error'); return; }
    acaoControle('preset.save', nome).then(() => { $('preset-name').value = ''; });
  });

  // ----------------------------------------------------------- projetos
  let projetoAtivo = '';
  const nomeDaPasta = caminho => String(caminho || '').split(/[\\/]/).filter(Boolean).pop() || '—';

  async function carregarProjetos() {
    const data = await get('/api/projects');
    projetoAtivo = data.active || projetoAtivo;
    say('projects-active', 'Projeto ativo: ' + projetoAtivo);
    const lista = $('project-list');
    lista.replaceChildren();
    const cores = ['purple', 'blue', 'silver'];
    (data.projects || []).forEach((projeto, indice) => {
      const botao = document.createElement('button');
      botao.className = 'project' + (projeto.path === data.active ? ' active' : '');
      botao.type = 'button';
      const pasta = document.createElement('span');
      pasta.className = 'folder ' + cores[indice % cores.length];
      const marca = document.createElement('i');
      marca.textContent = projeto.path === data.active ? '✧' : '▱';
      pasta.append(marca);
      const nome = document.createElement('strong');
      nome.textContent = projeto.name;
      const caminho = document.createElement('small');
      caminho.textContent = projeto.path;
      botao.append(pasta, nome, caminho);
      botao.addEventListener('click', () => abrirProjeto(projeto.path, projeto.name));
      lista.append(botao);
    });
    if (!(data.projects || []).length) {
      const vazio = document.createElement('p');
      vazio.className = 'hint';
      vazio.textContent = 'Nenhuma pasta encontrada. Informe o caminho completo abaixo.';
      lista.append(vazio);
    }
  }

  async function selecionarProjeto(caminho) {
    const resposta = await run('project-status', () => post('/api/project', { path: caminho }), 'Trocando de projeto…');
    if (resposta) {
      projetoAtivo = resposta.path || caminho;
      $('terminal-project').textContent = 'nebula / ' + nomeDaPasta(projetoAtivo);
      carregarProjetos().catch(() => {});
    }
    return resposta;
  }

  async function abrirProjeto(caminho, nome) {
    $('project-title').textContent = nome || nomeDaPasta(caminho);
    say('project-subtitle', caminho);
    await selecionarProjeto(caminho);
    shell.navigate('workspace');
    painelWorkspace('codex');
  }

  $('project-form').addEventListener('submit', event => {
    event.preventDefault();
    const caminho = $('project-path').value.trim();
    if (caminho) selecionarProjeto(caminho).then(() => { $('project-path').value = ''; });
  });
  $('project-reload').addEventListener('click', () => carregarProjetos().catch(erro => say('project-status', erro.message, 'error')));

  function painelWorkspace(nome) {
    for (const aba of document.querySelectorAll('[data-panel]')) {
      aba.setAttribute('aria-selected', String(aba.dataset.panel === nome));
    }
    for (const bloco of document.querySelectorAll('[data-workspace]')) {
      bloco.hidden = bloco.dataset.workspace !== nome;
    }
  }
  for (const aba of document.querySelectorAll('[data-panel]')) {
    aba.addEventListener('click', () => painelWorkspace(aba.dataset.panel));
  }

  // -------------------------------------------------------------- codex
  let jobAtual = null, jobTimer = null;

  async function acompanharJob() {
    if (!jobAtual) return;
    try {
      const job = await get('/api/job?id=' + encodeURIComponent(jobAtual));
      $('codex-output').textContent = String(job.output || job.status || '');
      say('codex-status', job.done ? 'Tarefa finalizada.' : 'Codex ativo; aguardando resposta final…');
      if (job.done) { clearInterval(jobTimer); jobTimer = null; }
    } catch (error) {
      say('codex-status', error.message, 'error');
    }
  }

  $('codex-form').addEventListener('submit', async event => {
    event.preventDefault();
    const pedido = $('codex-prompt').value.trim();
    if (!pedido) return;
    const resposta = await run('codex-status', () => post('/api/codex', { prompt: pedido }), 'Enviando ao Codex…');
    if (!resposta) return;
    jobAtual = resposta.job;
    $('codex-output').textContent = '';
    say('codex-status', 'Codex ativo; aguardando resposta final…');
    clearInterval(jobTimer);
    jobTimer = setInterval(acompanharJob, 2500);
    acompanharJob();
  });
  $('codex-listen').addEventListener('click', () => ditar($('codex-prompt'), 'codex-status'));
  $('codex-clear').addEventListener('click', () => { $('codex-prompt').value = ''; say('codex-status', ''); });
  $('open-vscode').addEventListener('click', () => run('actions-status', () => post('/api/vscode'), 'Abrindo o VS Code…'));

  // ------------------------------------------------------------ memória
  $('idea-form').addEventListener('submit', async event => {
    event.preventDefault();
    const texto = $('idea-text').value.trim();
    if (!texto) return;
    const resposta = await run('idea-status', () => post('/api/idea', { text: texto }), 'Salvando…');
    if (resposta) $('idea-text').value = '';
  });
  $('idea-listen').addEventListener('click', () => ditar($('idea-text'), 'idea-status'));
  $('history-reload').addEventListener('click', () => {
    assinaturaConversa = '';
    carregarConversa().catch(() => {});
  });

  // --------------------------------------------------------------- áudio
  let artworkConhecida = null;

  async function carregarMidia() {
    let midia;
    try {
      midia = await get('/api/media' + (artworkConhecida ? '?artwork_id=' + encodeURIComponent(artworkConhecida) : ''));
    } catch (error) {
      say('audio-status', error.message, 'error');
      return;
    }
    say('audio-status', '');
    const orbe = $('audio-orb');
    if (!midia.available) {
      $('audio-title').textContent = 'Nenhuma mídia ativa';
      $('audio-description').textContent = midia.message || 'Toque algo no computador para controlar por aqui.';
      $('audio-art').hidden = true;
      $('audio-orb-icon').hidden = false;
      orbe.classList.remove('playing');
      $('audio-progress').style.width = '0%';
      return;
    }
    $('audio-title').textContent = midia.title || 'Mídia sem título';
    $('audio-description').textContent = [midia.artist, midia.album].filter(Boolean).join(' · ') || 'Reproduzindo no computador';
    const tocando = midia.playback_status === 'playing';
    orbe.classList.toggle('playing', tocando);
    $('audio-orb-icon').textContent = tocando ? 'Ⅱ' : '▷';
    if (midia.artwork) {
      artworkConhecida = midia.artwork_id || artworkConhecida;
      $('audio-art').src = `data:${midia.artwork_type || 'image/jpeg'};base64,${midia.artwork}`;
      $('audio-art').hidden = false;
      $('audio-orb-icon').hidden = true;
    } else if (!midia.artwork_id) {
      artworkConhecida = null;
      $('audio-art').hidden = true;
      $('audio-orb-icon').hidden = false;
    }
    const duracao = Number(midia.duration_seconds) || 0;
    const posicao = Number(midia.position_seconds) || 0;
    $('audio-progress').style.width = duracao > 0 ? Math.min(100, (posicao / duracao) * 100).toFixed(1) + '%' : '0%';
  }

  function comandoMidia(acao) {
    return run('audio-status', async () => {
      const resposta = await post('/api/media/action', { action: acao });
      carregarMidia().catch(() => {});
      return resposta;
    }, 'Enviando ao player…');
  }
  $('audio-orb').addEventListener('click', () => comandoMidia('play_pause'));
  for (const botao of document.querySelectorAll('[data-media]')) {
    botao.addEventListener('click', () => comandoMidia(botao.dataset.media));
  }

  // ------------------------------------------------------------ telefone
  function quando(carimbo) {
    const valor = Number(carimbo);
    if (!valor) return 'nunca';
    return new Date(valor * 1000).toLocaleString('pt-BR');
  }

  async function carregarTelefone() {
    const aparelho = await get('/api/device');
    const bateria = aparelho.battery === undefined ? '—' : `${aparelho.battery}%${aparelho.charging ? ' carregando' : ''}`;
    const idade = aparelho.last_seen ? Math.max(0, Math.round(Date.now() / 1000 - Number(aparelho.last_seen))) : null;
    const situacao = idade === null ? 'sem contato' : (idade <= 15 ? 'online' : 'offline');
    say('device-summary', `Bateria ${bateria} · ${situacao} · última conexão ${quando(aparelho.last_seen)}`);

    const mapa = $('device-map');
    if (aparelho.latitude !== undefined && aparelho.longitude !== undefined) {
      mapa.href = `https://maps.google.com/?q=${aparelho.latitude},${aparelho.longitude}`;
      mapa.hidden = false;
    } else {
      mapa.hidden = true;
    }

    const painel = $('device-notifications');
    painel.replaceChildren();
    const notificacoes = Array.isArray(aparelho.notifications) ? aparelho.notifications.slice(-12).reverse() : [];
    for (const item of notificacoes) {
      const linha = document.createElement('div');
      linha.className = 'history-line';
      // O telefone pode mandar texto puro em vez de objeto.
      const dados = (item && typeof item === 'object') ? item : { text: String(item) };
      const app = document.createElement('b');
      app.textContent = String(dados.app || 'App');
      linha.append(app, document.createTextNode(' ' + String(dados.title || dados.text || '')));
      painel.append(linha);
    }
    if (!notificacoes.length) {
      const vazio = document.createElement('p');
      vazio.className = 'hint';
      vazio.textContent = 'Nenhuma notificação compartilhada.';
      painel.append(vazio);
    }
  }

  for (const botao of document.querySelectorAll('[data-device]')) {
    botao.addEventListener('click', () => {
      if (botao.dataset.device === 'lock_nebula'
        && !confirm('A tela do telefone será bloqueada e exigirá o PIN do Android. Continuar?')) return;
      run('device-status', async () => {
        await post('/api/device/command', { action: botao.dataset.device });
        return { message: 'Comando enviado; aguardando o telefone executar.' };
      }, 'Enviando…');
    });
  }

  async function carregarTransferencia() {
    const data = await get('/api/transfer/messages');
    const lista = $('transfer-list');
    lista.replaceChildren();
    for (const item of (data.messages || []).slice(-25)) {
      const linha = document.createElement('div');
      linha.className = 'history-line';
      const quem = document.createElement('b');
      quem.textContent = String(item.sender || 'Computador');
      linha.append(quem);
      if (item.text) linha.append(document.createTextNode(' ' + item.text));
      if (item.filename) {
        const link = document.createElement('a');
        link.href = '/api/transfer/file?id=' + encodeURIComponent(item.id);
        link.textContent = ' ' + item.filename;
        link.rel = 'noreferrer noopener';
        linha.append(link);
      }
      lista.append(linha);
    }
    if (!(data.messages || []).length) {
      const vazio = document.createElement('p');
      vazio.className = 'hint';
      vazio.textContent = 'Nenhuma mensagem trocada ainda.';
      lista.append(vazio);
    }
  }

  function novoIdentificador() {
    // O painel pela LAN roda em http, onde crypto.randomUUID não existe.
    if (crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '');
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  }

  $('transfer-form').addEventListener('submit', async event => {
    event.preventDefault();
    const texto = $('transfer-text').value.trim();
    if (!texto) return;
    const identificador = novoIdentificador();
    const enviado = await run('transfer-status', () => post('/api/transfer/message', {
      id: identificador, sender: 'Computador', text: texto,
    }), 'Enviando…');
    if (enviado) { $('transfer-text').value = ''; carregarTransferencia().catch(() => {}); }
  });
  $('transfer-reload').addEventListener('click', () => carregarTransferencia().catch(erro => say('transfer-status', erro.message, 'error')));

  // ------------------------------------------------------------ terminal
  async function executarComando(comando, saidaId, estadoId) {
    const saida = $(saidaId);
    if (estadoId) $(estadoId).textContent = 'EXECUTANDO';
    saida.textContent = (saida.textContent ? saida.textContent + '\n' : '') + '> ' + comando;
    try {
      const resposta = await post('/api/terminal', { command: comando });
      saida.textContent += '\n' + String(resposta.output || '').trimEnd()
        + `\n[código ${resposta.exit_code}]`;
      projetoAtivo = resposta.project || projetoAtivo;
    } catch (error) {
      saida.textContent += '\n' + error.message;
    } finally {
      if (estadoId) $(estadoId).textContent = 'PRONTO';
      saida.scrollTop = saida.scrollHeight;
    }
  }

  $('terminal-form').addEventListener('submit', event => {
    event.preventDefault();
    const comando = $('terminal-input').value.trim();
    if (!comando) return;
    $('terminal-input').value = '';
    executarComando(comando, 'terminal-output', 'terminal-state');
  });
  $('workspace-shell-form').addEventListener('submit', event => {
    event.preventDefault();
    const comando = $('workspace-shell-input').value.trim();
    if (!comando) return;
    $('workspace-shell-input').value = '';
    executarComando(comando, 'workspace-shell-output');
  });

  // ------------------------------------------------- bateria compartilhada
  async function compartilharBateria() {
    if (!navigator.getBattery) return;
    try {
      const bateria = await navigator.getBattery();
      const enviar = () => post('/api/device', {
        battery: Math.round(bateria.level * 100), charging: bateria.charging,
      }).catch(() => {});
      enviar();
      bateria.addEventListener('levelchange', enviar);
      bateria.addEventListener('chargingchange', enviar);
    } catch { /* O navegador pode recusar; o painel continua sem isso. */ }
  }

  // --------------------------------------------------------------- dupla
  // Contrato em services/collaboration/README.md. O backend é do Codex; aqui
  // só se desenha o snapshot e se repassa a ação do usuário.
  // As chaves vêm de services/collaboration/store.py: AGENTS = (codex, opus).
  const NOMES_AGENTE = { opus: 'Claude', codex: 'Astra', user: 'Você', system: 'Nebula' };
  const ESTADOS_TAREFA = {
    queued: 'na fila', running: 'em execução', interrupted: 'interrompida',
    completed: 'concluída', failed: 'falhou',
  };
  const EVENTOS = {
    agent_update: 'progresso', tool_activity: 'ferramenta', chat_error: 'erro', chat_reply: 'resposta',
    idea: 'pedido', coordination: 'coordenação', confirmation: 'confirmação',
    task_planned: 'tarefa planejada', task_claimed: 'tarefa reservada',
    code_section: 'seção de código', tokens_reserved: 'tokens reservados',
    tokens_settled: 'tokens medidos', run_started: 'execução iniciada',
    run_finished: 'execução encerrada',
  };
  const nomeAgente = chave => NOMES_AGENTE[chave] || String(chave || '—');
  let ideiaAtual = null;
  let ideiaEmEdicao = false;
  let projetoDupla = null;

  function quandoCurto(valor) {
    const data = new Date(valor);
    return Number.isNaN(data.getTime()) ? '' : data.toLocaleTimeString('pt-BR');
  }

  function linha(autor, texto, { tipo = '', em = '' } = {}) {
    const bloco = document.createElement('div');
    bloco.className = 'history-line fala fala-' + String(autor || 'system');
    const quem = document.createElement('b');
    quem.textContent = nomeAgente(autor);
    bloco.append(quem);
    if (tipo) {
      const selo = document.createElement('span');
      selo.className = 'selo';
      selo.textContent = tipo;
      bloco.append(selo);
    }
    bloco.append(document.createTextNode(' ' + String(texto || '')));
    if (em) {
      const hora = document.createElement('span');
      hora.className = 'hora';
      hora.textContent = quandoCurto(em);
      bloco.append(hora);
    }
    return bloco;
  }

  function pintarLinhas(alvo, linhas, vazio) {
    alvo.replaceChildren();
    for (const item of linhas) alvo.append(item);
    if (!linhas.length) {
      const nada = document.createElement('p');
      nada.className = 'hint';
      nada.textContent = vazio;
      alvo.append(nada);
    }
    alvo.scrollTop = alvo.scrollHeight;
  }

  // Uma das duas pode esbarrar no limite de crédito no meio de uma seção. Aqui
  // só se detecta e se avisa: quem transfere a reserva é o coordenador, do
  // outro lado. Sem isto, a tarefa ficaria "em execução" para sempre e a outra
  // IA não teria como saber que precisa assumir.
  const PARADA_MINUTOS = 12;

  function minutosDesde(quando) {
    const marca = Date.parse(quando || '');
    return Number.isFinite(marca) ? (Date.now() - marca) / 60000 : null;
  }

  function detectarParada(estado, daIdeia) {
    const ultima = {};
    for (const mensagem of estado.messages || []) {
      if (mensagem.actor && mensagem.actor !== 'user' && mensagem.actor !== 'system') {
        ultima[mensagem.actor] = mensagem.at;
      }
    }
    return (estado.tasks || []).filter(daIdeia)
      .filter(t => t.status === 'running' || t.status === 'interrupted')
      .map(tarefa => {
        const desde = minutosDesde(ultima[tarefa.owner] || tarefa.started_at);
        return { tarefa, minutos: desde };
      })
      .filter(item => item.minutos !== null && item.minutos >= PARADA_MINUTOS);
  }

  function pintarParada(estado, daIdeia) {
    const alvo = $('dupla-parada');
    const paradas = detectarParada(estado, daIdeia);
    if (!paradas.length) { alvo.hidden = true; alvo.textContent = ''; return; }
    const outro = chave => (chave === 'opus' ? 'codex' : 'opus');
    alvo.hidden = false;
    alvo.textContent = paradas.map(({ tarefa, minutos }) =>
      `${nomeAgente(tarefa.owner)} está sem dar sinal há ${Math.round(minutos)} min com "`
      + `${tarefa.title}" reservada. ${nomeAgente(outro(tarefa.owner))} deve assumir o que faltou.`
    ).join(' ');
  }

  function pintarOrcamentos(orcamento) {
    const alvo = $('dupla-orcamentos');
    alvo.replaceChildren();
    const agentes = Object.keys(orcamento || {});
    if (!agentes.length) {
      const nada = document.createElement('p');
      nada.className = 'hint';
      nada.textContent = 'Abra um pedido para as duas ganharem orçamento.';
      alvo.append(nada);
      return;
    }
    for (const agente of agentes) {
      const dados = orcamento[agente] || {};
      const limite = Number(dados.limit) || 0;
      const medido = Number(dados.measured) || 0;
      const comprometido = medido + (Number(dados.estimated) || 0) + (Number(dados.reserved) || 0);
      const bloco = document.createElement('div');
      bloco.className = 'saldo-linha';
      const topo = document.createElement('div');
      topo.className = 'saldo-topo';
      const nome = document.createElement('strong');
      nome.textContent = nomeAgente(agente);
      const valor = document.createElement('span');
      valor.textContent = medido.toLocaleString('pt-BR') + ' / ' + limite.toLocaleString('pt-BR');
      topo.append(nome, valor);
      const barra = document.createElement('div');
      barra.className = 'barra';
      const medida = document.createElement('span');
      medida.style.width = limite > 0 ? Math.min(100, medido / limite * 100).toFixed(1) + '%' : '0%';
      const reservada = document.createElement('span');
      reservada.className = 'reservada';
      reservada.style.width = limite > 0
        ? Math.min(100, Math.max(0, (comprometido - medido) / limite * 100)).toFixed(1) + '%' : '0%';
      barra.append(medida, reservada);
      const nota = document.createElement('p');
      nota.className = 'hint';
      const desconhecidas = Number(dados.unknown_calls) || 0;
      nota.textContent = 'reservado ' + (comprometido - medido).toLocaleString('pt-BR')
        + (desconhecidas ? ` · ${desconhecidas} chamadas sem consumo reportado` : '');
      bloco.append(topo, barra, nota);
      alvo.append(bloco);
    }
  }

  function cartaoDeTarefa(tarefa) {
    const cartao = document.createElement('article');
    cartao.className = 'item estado-' + String(tarefa.status || 'queued');
    const topo = document.createElement('div');
    topo.className = 'item-topo';
    const titulo = document.createElement('strong');
    titulo.textContent = tarefa.title || '(sem título)';
    const prioridade = document.createElement('span');
    prioridade.className = 'reading';
    prioridade.title = 'prioridade por mil tokens estimados';
    prioridade.textContent = Number(tarefa.priority || 0).toFixed(2);
    topo.append(titulo, prioridade);
    cartao.append(topo);

    const marcas = document.createElement('div');
    marcas.className = 'item-marcas';
    const etiquetas = [
      [nomeAgente(tarefa.owner), 'dono'],
      [ESTADOS_TAREFA[tarefa.status] || tarefa.status, 'estado'],
      ['impacto ' + tarefa.impact, ''],
      ['urgência ' + tarefa.urgency, ''],
      ['risco ' + tarefa.risk, ''],
      ['confiança ' + Math.round((Number(tarefa.confidence) || 0) * 100) + '%', ''],
      ['~' + (Number(tarefa.estimated_tokens) || 0).toLocaleString('pt-BR') + ' tokens', ''],
    ];
    for (const [rotulo, classe] of etiquetas) {
      const marca = document.createElement('span');
      marca.className = 'marca' + (classe ? ' ' + classe : '');
      marca.textContent = rotulo;
      marcas.append(marca);
    }
    cartao.append(marcas);

    if (tarefa.reason) {
      const razao = document.createElement('p');
      razao.textContent = tarefa.reason;
      cartao.append(razao);
    }
    if ((tarefa.paths || []).length) {
      const caminhos = document.createElement('p');
      caminhos.className = 'hint arquivos';
      caminhos.textContent = 'Reserva: ' + tarefa.paths.join(', ');
      cartao.append(caminhos);
    }
    if ((tarefa.dependencies || []).length) {
      const deps = document.createElement('p');
      deps.className = 'hint';
      deps.textContent = 'Depende de ' + tarefa.dependencies.length + ' tarefa(s).';
      cartao.append(deps);
    }
    if (tarefa.summary) {
      const resumo = document.createElement('p');
      resumo.className = 'hint ' + (tarefa.status === 'failed' ? 'error' : 'good');
      resumo.textContent = tarefa.summary;
      cartao.append(resumo);
    }
    if (tarefa.evidence) {
      const prova = document.createElement('p');
      prova.className = 'hint arquivos';
      prova.textContent = 'Verificação: ' + tarefa.evidence;
      cartao.append(prova);
    }
    return cartao;
  }

  function pintarColaboracao(estado) {
    if (projetoDupla !== estado.project_root) {
      projetoDupla = estado.project_root;
      ideiaEmEdicao = false;
    }
    say('dupla-projeto', 'Projeto: ' + (estado.project_root || 'não informado') +
      (estado.development_available ? '' : ' · Selecione um repositório Git em Projetos.'));
    const ideias = estado.ideas || [];
    const ideia = ideias[ideias.length - 1] || null;
    ideiaAtual = ideia ? ideia.id : null;
    say('dupla-subtitle', ideia
      ? `${ideia.text} · ${ideia.status}`
      : 'Envie seu pedido para começar a desenvolver com as duas.');
    if (!ideiaEmEdicao && ideia) $('dupla-ideia').value = ideia.text;

    const daIdeia = registro => !ideiaAtual || !registro.idea_id || registro.idea_id === ideiaAtual;

    // Conversa inclui respostas reais dos CLIs e erros visíveis da rodada.
    const frente = [];
    for (const mensagem of estado.messages || []) {
      if (mensagem.idea !== ideiaAtual) continue;
      if (['idea', 'user_message', 'chat_reply', 'chat_error'].includes(mensagem.kind) && mensagem.data?.text) {
        frente.push({ em: mensagem.at, no: linha(mensagem.actor, mensagem.data.text,
          { em: mensagem.at, tipo: mensagem.data.model || (mensagem.kind === 'chat_error' ? 'erro' : '') }) });
      }
    }
    for (const confirmacao of (estado.confirmations || []).filter(daIdeia)) {
      const origem = [confirmacao.model, confirmacao.session_id].filter(Boolean).join(' · ');
      frente.push({
        em: confirmacao.at,
        no: linha(confirmacao.agent, confirmacao.text + (origem ? ` (${origem})` : ''),
          { tipo: 'confirmou', em: confirmacao.at }),
      });
    }
    frente.sort((a, b) => String(a.em).localeCompare(String(b.em)));
    pintarLinhas($('dupla-frente'), frente.map(item => item.no),
      'Envie uma mensagem para conversar com Astra e Claude.');
    const enviando = Boolean(estado.active_chat || estado.active_run);
    $('dupla-mensagem-form').querySelector('button[type="submit"]').disabled = enviando || !estado.development_available || estado.paused;
    $('dupla-stop').disabled = estado.active_chat?.mode !== 'development';
    if (enviando) say('dupla-mensagem-status', 'Astra e Claude estão trabalhando no projeto…');
    else if ($('dupla-mensagem-status').textContent === 'Astra e Claude estão trabalhando no projeto…') say('dupla-mensagem-status', 'Rodada encerrada.');
    const atividades = (estado.messages || []).filter(m => m.idea === ideiaAtual &&
      ['tool_activity', 'agent_update'].includes(m.kind)).slice(-14);
    pintarLinhas($('dupla-atividade'), atividades.map(m => linha(m.actor, m.data.text,
      { em: m.at, tipo: EVENTOS[m.kind] })), 'Os comandos, arquivos e testes executados aparecerão aqui.');

    // Coordenação: o resto dos eventos, sem raciocínio privado.
    const bastidores = (estado.messages || [])
      .filter(mensagem => mensagem.idea === ideiaAtual)
      .filter(mensagem => !(mensagem.actor === 'user' && mensagem.kind !== 'confirmation'))
      .map(mensagem => {
        const dados = mensagem.data || {};
        const texto = dados.text || dados.title || dados.summary
          || Object.keys(dados).map(chave => `${chave}: ${JSON.stringify(dados[chave])}`).join(' · ');
        return linha(mensagem.actor, texto, { tipo: EVENTOS[mensagem.kind] || mensagem.kind, em: mensagem.at });
      });
    pintarLinhas($('dupla-bastidores'), bastidores, 'Nenhum evento de coordenação ainda.');

    const tarefas = (estado.tasks || []).filter(daIdeia);
    const fila = $('dupla-tarefas');
    fila.replaceChildren();
    for (const tarefa of tarefas) fila.append(cartaoDeTarefa(tarefa));
    if (!tarefas.length) {
      const nada = document.createElement('p');
      nada.className = 'hint';
      nada.textContent = 'Acompanhe a implementação e a revisão em Atividade. Esta fila guarda tarefas estruturadas anteriores.';
      fila.append(nada);
    }

    pintarOrcamentos((estado.budgets || {})[ideiaAtual] || {});
    pintarParada(estado, daIdeia);

    const execucao = estado.running || estado.active_run || estado.active_chat;
    const provedores = Object.entries(estado.providers || {})
      .map(([agente, dados]) => `${nomeAgente(agente)}: ${dados?.model || dados || '—'}`)
      .join(' · ');
    say('dupla-execucao', [
      estado.paused ? 'Pausada entre etapas.' : (execucao ? 'Execução em andamento.' : 'Nenhuma execução em andamento.'),
      provedores,
    ].filter(Boolean).join(' '));
    $('dupla-pause').textContent = estado.paused ? 'Retomar' : 'Pausar';
    $('dupla-pause').dataset.paused = String(Boolean(estado.paused));
    $('dupla-run').disabled = !ideiaAtual || Boolean(execucao) || !estado.development_available || estado.paused;

    say('dupla-log-caminho', estado.log_path
      ? 'Diário em ' + estado.log_path
      : 'Nenhuma seção registrada ainda.');
  }

  function colaboracaoAguardando(mensagem) {
    say('dupla-subtitle', mensagem);
    const fila = $('dupla-tarefas');
    fila.replaceChildren();
    const aviso = document.createElement('p');
    aviso.className = 'hint';
    aviso.textContent = mensagem;
    fila.append(aviso);
  }

  async function carregarDupla() {
    try {
      pintarColaboracao(await get('/api/collaboration'));
    } catch (erro) {
      if (erro.status === 503 && erro.dados && erro.dados.aguardando_backend) {
        colaboracaoAguardando(erro.message);
        return;
      }
      throw erro;
    }
  }

  $('dupla-ideia').addEventListener('input', () => { ideiaEmEdicao = true; });
  $('dupla-ideia-form').addEventListener('submit', async event => {
    event.preventDefault();
    const texto = $('dupla-ideia').value.trim();
    if (!texto) return;
    const criado = await run('dupla-ideia-status', () => post('/api/collaboration/ideas', {
      text: texto, token_budget: Number($('dupla-orcamento').value) || 60000,
    }), 'Abrindo pedido…');
    ideiaEmEdicao = false;
    if (criado) carregarDupla().catch(() => {});
  });

  $('dupla-mensagem-form').addEventListener('submit', async event => {
    event.preventDefault();
    const texto = $('dupla-mensagem').value.trim();
    if (!texto) return;
    const enviado = await run('dupla-mensagem-status', () => post('/api/collaboration/develop', {
      idea_id: ideiaAtual, text: texto, token_budget: Number($('dupla-orcamento').value) || 60000,
    }), 'Enviando às duas…');
    if (enviado) { $('dupla-mensagem').value = ''; carregarDupla().catch(() => {}); }
  });

  $('dupla-run').addEventListener('click', async () => {
    if (!ideiaAtual) { say('dupla-execucao-status', 'Abra um pedido primeiro.', 'error'); return; }
    await run('dupla-execucao-status',
      () => post('/api/collaboration/develop', { idea_id: ideiaAtual, text: $('dupla-ideia').value.trim() }), 'Iniciando as duas…');
    carregarDupla().catch(() => {});
  });

  $('dupla-pause').addEventListener('click', async () => {
    const pausar = $('dupla-pause').dataset.paused !== 'true';
    await run('dupla-execucao-status',
      () => post('/api/collaboration/pause', { paused: pausar }),
      pausar ? 'Pausando entre etapas…' : 'Retomando…');
    carregarDupla().catch(() => {});
  });

  $('dupla-stop').addEventListener('click', async () => {
    await run('dupla-execucao-status', () => post('/api/collaboration/stop', {}), 'Interrompendo…');
    carregarDupla().catch(() => {});
  });

  $('dupla-bastidores-abrir').addEventListener('click', () => {
    const painel = $('dupla-bastidores');
    painel.hidden = !painel.hidden;
    $('dupla-bastidores-abrir').setAttribute('aria-expanded', String(!painel.hidden));
    $('dupla-bastidores-abrir').textContent = painel.hidden ? 'Mostrar' : 'Esconder';
  });

  $('dupla-log-abrir').addEventListener('click', async () => {
    const painel = $('dupla-log');
    if (!painel.hidden) {
      painel.hidden = true;
      $('dupla-log-abrir').textContent = 'Abrir';
      $('dupla-log-abrir').setAttribute('aria-expanded', 'false');
      return;
    }
    try {
      const resposta = await get('/api/collaboration/log');
      // O diário vem como Markdown; entra como texto para nunca virar HTML cru.
      painel.textContent = String(resposta.markdown || '').trim() || 'O diário ainda está vazio.';
      painel.hidden = false;
      $('dupla-log-abrir').textContent = 'Fechar';
      $('dupla-log-abrir').setAttribute('aria-expanded', 'true');
    } catch (erro) {
      say('dupla-log-caminho', erro.message, 'error');
    }
  });

  // --------------------------------------------------------- orquestração
  const ROTINAS = {
    chat: [() => Promise.all([carregarConversa(), atualizarEstado()]), 2500],
    casa: [carregarControle, 2000],
    projects: [carregarProjetos, 15000],
    workspace: [atualizarEstado, 10000],
    memory: [carregarConversa, 5000],
    audio: [carregarMidia, 2000],
    device: [() => Promise.all([carregarTelefone(), carregarTransferencia()]), 4000],
    terminal: [atualizarEstado, 10000],
    dupla: [carregarDupla, 3000],
  };

  let rotinaTimer = null;
  function trocarRotina(view) {
    clearInterval(rotinaTimer);
    const rotina = ROTINAS[view];
    if (!rotina) return;
    const [tarefa, intervalo] = rotina;
    const executar = () => Promise.resolve(tarefa()).catch(erro => console.debug('Nebula:', erro.message));
    executar();
    rotinaTimer = setInterval(() => { if (!document.hidden) executar(); }, intervalo);
  }

  shell.onView(trocarRotina);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) trocarRotina(shell.view); });

  (async () => {
    try {
      await get('/api/session');
    } catch {
      say('chat-status', 'Sem sessão ativa. Abra o Espaço pela Nebula ou informe o PIN no painel.', 'error');
    }
    trocarRotina(shell.view);
    compartilharBateria();
    atualizarEstado().catch(() => {});
    carregarProjetos().catch(() => {});
  })();
})();
