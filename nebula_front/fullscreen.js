/* Tela cheia por F11, compartilhada pelo front espacial e pelo console do hub.
   Em navegador comum o F11 nativo já funciona; aqui ele é interceptado para dar
   o mesmo comportamento dentro da janela --app do EXE e do WebView do APK, onde
   a tecla não chega ao navegador. NebulaHost é a ponte injetada pelo Android. */
(() => {
  'use strict';
  const host = () => (typeof window.NebulaHost === 'object' ? window.NebulaHost : null);
  const root = document.documentElement;
  let hostActive = false;

  function active() {
    return hostActive || Boolean(document.fullscreenElement || document.webkitFullscreenElement);
  }

  function sync() {
    const on = active();
    document.body.classList.toggle('is-fullscreen', on);
    for (const button of document.querySelectorAll('[data-fullscreen]')) {
      button.setAttribute('aria-pressed', String(on));
      button.title = on ? 'Sair da tela cheia (F11)' : 'Tela cheia (F11)';
      button.setAttribute('aria-label', button.title);
      const face = button.querySelector('[data-fullscreen-icon]') || button;
      face.textContent = on ? '⤡' : '⤢';
    }
  }

  async function enter() {
    const bridge = host();
    if (bridge && typeof bridge.enterFullscreen === 'function') {
      bridge.enterFullscreen();
      hostActive = true;
      sync();
      return;
    }
    const request = root.requestFullscreen || root.webkitRequestFullscreen;
    if (!request) return;
    try {
      await request.call(root, { navigationUI: 'hide' });
    } catch (error) {
      console.warn('Nebula: tela cheia indisponível.', error);
    }
  }

  async function leave() {
    const bridge = host();
    if (bridge && typeof bridge.exitFullscreen === 'function') {
      bridge.exitFullscreen();
      hostActive = false;
      sync();
      return;
    }
    const exit = document.exitFullscreen || document.webkitExitFullscreen;
    if (!exit || !document.fullscreenElement) return;
    try {
      await exit.call(document);
    } catch (error) {
      console.warn('Nebula: não foi possível sair da tela cheia.', error);
    }
  }

  function toggle() {
    return active() ? leave() : enter();
  }

  document.addEventListener('keydown', event => {
    if (event.key === 'F11') {
      event.preventDefault();
      toggle();
      return;
    }
    // O Escape já sai do modo nativo; aqui ele cobre a ponte do Android.
    if (event.key === 'Escape' && hostActive) leave();
  });

  document.addEventListener('DOMContentLoaded', () => {
    for (const button of document.querySelectorAll('[data-fullscreen]')) {
      button.addEventListener('click', toggle);
    }
    sync();
  });
  for (const event of ['fullscreenchange', 'webkitfullscreenchange']) {
    document.addEventListener(event, () => {
      if (!document.fullscreenElement && !document.webkitFullscreenElement) hostActive = false;
      sync();
    });
  }

  // O host Android avisa quando o usuário sai pelo gesto do sistema.
  window.NebulaFullscreen = { toggle, enter, leave, sync, set(on) { hostActive = Boolean(on); sync(); } };
})();
