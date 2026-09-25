"""Painel móvel privado da Nebula, exposto apenas pelo Tailscale Serve."""

from __future__ import annotations

import base64
import io
import html
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from PIL import Image, ImageDraw

from memoria_nebula import MEMORIA, encontrar_ultima_interacao
from media_windows import MEDIA_CONTROLLER, MediaControlError
from notas import salvar_nota
from wifi_bpm import SENSOR as WIFI_BPM_SENSOR
from beamng_turbo import SENSOR as BEAMNG_TURBO
from rocket_overlay import OVERLAY_BRIDGE
from transfer_chat import CHAT_STORE, MAX_FILE_BYTES
import front_assets
import uso_ias

PORTA = 8765
PROJETO = (
    Path(sys.executable).resolve().parent.parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
CONFIG_FILE = CONFIG_DIR / "remote.json"
MAX_BODY_BYTES = 100_000
MAX_TRANSFER_BODY_BYTES = MAX_FILE_BYTES * 4 // 3 + 200_000
MAX_COMMAND_CHARS = 4_000
MAX_PROMPT_CHARS = 20_000
ESPACO_TICKET_SEGUNDOS = 90
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 8
_POWER_TOKEN_CONFIGURADO = os.environ.get("NEBULA_POWER_TOKEN", "").strip()
# Mantém os serviços locais testáveis, mas não cria uma credencial previsível.
# Integrações entre processos/dispositivos exigem NEBULA_POWER_TOKEN explícito.
POWER_TOKEN = _POWER_TOKEN_CONFIGURADO or secrets.token_urlsafe(32)


LOGIN_HTML = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nebula — acesso</title><style>body{font-family:system-ui;background:#f5f7fb;color:#172033;margin:0}.card{max-width:420px;margin:15vh auto;background:white;padding:28px;border-radius:18px;box-shadow:0 8px 30px #17203318}input,button{box-sizing:border-box;width:100%;padding:14px;border-radius:12px;font:inherit}input{border:1px solid #d7dee8}button{margin-top:12px;border:0;background:#278cf5;color:white;font-weight:700}.status{color:#667085}</style></head><body><main class="card"><h1>Nebula</h1><p>Informe o PIN exibido no computador.</p><form id="login"><input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" required><button>Conectar</button></form><p id="status" class="status"></p></main><script>document.getElementById('login').onsubmit=async e=>{e.preventDefault();const status=document.getElementById('status');status.textContent='Conectando…';try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pin:document.getElementById('pin').value})});const j=await r.json();if(!r.ok)throw Error(j.error||'Falha');location.replace('/')}catch(error){status.textContent=error.message}}</script></body></html>'''


def child_environment() -> dict[str, str]:
    """Não propaga caminhos temporários do executável PyInstaller aos filhos."""
    environment = os.environ.copy()
    for key in list(environment):
        if key.startswith("_PYI") or key in {"TCL_LIBRARY", "TK_LIBRARY"}:
            environment.pop(key, None)
    return environment

HTML = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#278cf5"><meta name="description" content="Controle remoto privado da assistente Nebula"><link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/icon-192.png"><title>Nebula</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#172033;font-family:system-ui,"Segoe UI",sans-serif}.app{max-width:680px;min-height:100vh;margin:auto;padding:24px;background:#fff}.top{display:flex;align-items:center;gap:12px;margin-bottom:24px}.orb{width:44px;height:44px;border-radius:50%;background:radial-gradient(circle at 65% 65%,#9bd7ff,#278cf5 65%,#126ed1);box-shadow:0 7px 20px #278cf540}h1,h2{margin:0}h2{font-size:18px;margin-bottom:12px}.sub,.status{color:#667085;font-size:14px}.card{border:1px solid #e4e9f0;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 5px 18px #1720330a}textarea,input{width:100%;padding:14px;border:1px solid #d7dee8;border-radius:13px;font:inherit;outline:none}textarea{min-height:180px;resize:vertical}textarea:focus,input:focus{border-color:#278cf5}.row{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}button{border:0;border-radius:12px;padding:12px 15px;font-weight:650}.primary{background:#278cf5;color:#fff}.secondary{background:#eef6ff;color:#126ed1}.danger{background:#fff1f0;color:#c43224}.confirm{display:none;background:#fff9eb;border-color:#ffdc91}.output{min-height:70px;max-height:300px;overflow:auto;white-space:pre-wrap;background:#101828;color:#e6edf6;border-radius:12px;padding:14px;font:13px Consolas,monospace}#panel{display:none}#login{margin-top:15vh}</style></head><body><main class="app"><header class="top"><div class="orb"></div><div><h1>Nebula</h1></div></header>
<style>#login{display:none!important}#panel{display:block!important}</style><div class="row"><button id="install" class="primary" style="display:none">Instalar aplicativo</button></div><form id="login"></form><div class="card"><h2>Controle direto</h2><p class="sub">Funciona sem JavaScript. Você também pode usar o microfone do teclado.</p><form method="post" action="/command"><textarea name="command" style="min-height:90px" placeholder="Digite ou dite um comando para a Nebula" required></textarea><div class="row"><button class="primary" type="submit">Enviar à Nebula</button></div></form><div class="row"><form method="post" action="/vscode"><button class="secondary" type="submit">Abrir VS Code</button></form><form method="post" action="/pause-form"><input type="hidden" name="paused" value="1"><button class="danger" type="submit">Pausar Nebula</button></form><form method="post" action="/pause-form"><input type="hidden" name="paused" value="0"><button class="secondary" type="submit">Retomar Nebula</button></form></div></div><div class="card"><h2>Histórico da Nebula</h2><div class="output" style="background:#f7f9fc;color:#172033"><!--SERVER_HISTORY--></div><div class="row"><a class="secondary" style="text-decoration:none;padding:12px 15px;border-radius:12px" href="/?refresh=1">Atualizar histórico</a></div></div><div class="card"><h2>Projeto e VS Code</h2><p class="status">Projeto ativo: <!--ACTIVE_PROJECT--></p><form method="post" action="/project-form"><select name="path" style="width:100%;padding:14px;border:1px solid #d7dee8;border-radius:13px;background:white"><!--PROJECT_OPTIONS--></select><input name="custom_path" style="margin-top:10px" placeholder="Ou informe o caminho completo"><div class="row"><button class="primary" type="submit">Selecionar projeto</button></div></form></div><div class="card"><h2>Falar com o Codex</h2><form method="post" action="/codex-form"><textarea name="prompt" style="min-height:120px" placeholder="Descreva a tarefa para o Codex" required></textarea><div class="row"><button class="primary" type="submit">Enviar ao Codex</button></div></form></div><div class="card"><h2>Salvar ideia</h2><form method="post" action="/idea-form"><textarea name="text" style="min-height:80px" placeholder="Digite ou dite sua ideia" required></textarea><div class="row"><button class="secondary" type="submit">Salvar ideia</button></div></form></div>
<section id="panel"><div class="card"><h2>Conversar com a Nebula</h2><div id="nebulaChat" class="output" style="background:#f7f9fc;color:#172033;margin-bottom:12px">Pronta para receber comandos.</div><textarea id="nebulaCommand" style="min-height:90px" placeholder="Ex.: pause o vídeo, abra o Discord, abra o Rocket League..."></textarea><div class="row"><button class="primary" onclick="listenNebula()">🎙 Falar</button><button class="primary" onclick="sendNebula()">Enviar comando</button></div><div id="nebulaStatus" class="status"></div><hr style="border:0;border-top:1px solid #e4e9f0;margin:18px 0"><p class="sub"><b>A última resposta ajudou?</b> O feedback fica salvo no seu PC.</p><input id="feedbackComment" maxlength="2000" placeholder="Opcional: diga o que ficou bom ou o que precisa mudar"><div class="row"><button class="secondary" onclick="sendFeedback('positivo')">👍 Gostei</button><button class="danger" onclick="sendFeedback('negativo')">👎 Pode melhorar</button></div><div id="feedbackStatus" class="status"></div></div><div class="card"><h2>Projeto ativo</h2><select id="project" style="width:100%;padding:14px;border:1px solid #d7dee8;border-radius:13px;background:white" onchange="selectProject(this.value)"></select><input id="projectPath" style="margin-top:10px" placeholder="Ou digite o caminho completo da pasta"><div class="row"><button class="secondary" onclick="loadProjects()">Atualizar lista</button><button class="primary" onclick="selectProject($('projectPath').value)">Usar esta pasta</button></div><div id="projectStatus" class="status"></div></div><div class="card"><h2>Falar com o Codex</h2><textarea id="draft" placeholder="Seu pedido aparecerá aqui..."></textarea><div class="row"><button class="primary" onclick="listen()">🎙 Falar</button><button class="secondary" onclick="listen()">Não, continuar</button><button class="secondary" onclick="confirmSend()">É só isso</button><button class="danger" onclick="clearDraft()">Limpar</button></div><div id="speechStatus" class="status">Pronta para ouvir.</div></div>
<div class="row"><button id="voiceButton" class="secondary" onclick="toggleVoice()">🔇 Ativar respostas em voz no celular</button></div><div id="confirm" class="card confirm"><b>Confirma o envio deste texto ao Codex?</b><p id="confirmText" class="status"></p><div class="row"><button class="primary" onclick="sendCodex()">Sim, enviar</button><button class="secondary" onclick="cancelSend()">Não, continuar</button></div></div>
<div class="card"><h2>Controle de emergência</h2><p id="pauseStatus" class="status">Consultando estado...</p><div class="row"><button class="danger" onclick="setPaused(true)">⏸ Pausar Nebula</button><button class="secondary" onclick="setPaused(false)">▶ Retomar</button></div></div><div class="card"><h2>Ações no computador</h2><div class="row"><button class="secondary" onclick="openCode()">Abrir VS Code</button><button class="secondary" onclick="saveIdea()">Salvar como ideia</button></div><div id="actionStatus" class="status"></div></div><div class="card"><h2>Resposta do Codex</h2><div id="output" class="output">Nenhuma solicitação enviada.</div></div></section></main><script>
const $=x=>document.getElementById(x);async function api(p,d={}){const c=new AbortController(),timer=setTimeout(()=>c.abort(),12000);try{const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d),signal:c.signal}),j=await r.json();if(!r.ok)throw Error(j.error||'Falha');return j}catch(e){if(e.name==='AbortError')throw Error('O PC não respondeu. Confira se a Nebula e o Tailscale estão ligados.');throw e}finally{clearTimeout(timer)}}async function login(){$('loginStatus').textContent='Conectando...';try{await api('/api/login',{pin:$('pin').value});$('login').style.display='none';$('panel').style.display='block';refreshState();loadProjects();loadConversation();shareBattery()}catch(e){$('loginStatus').textContent=e.message}}
function listen(){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){$('speechStatus').textContent='Use o microfone do teclado neste campo.';$('draft').focus();return}const r=new SR(),base=$('draft').value.trim();r.lang='pt-BR';r.interimResults=true;r.onstart=()=>$('speechStatus').textContent='Ouvindo...';r.onresult=e=>{let t='';for(let i=e.resultIndex;i<e.results.length;i++)t+=e.results[i][0].transcript;$('draft').value=(base?base+' ':'')+t};r.onend=()=>$('speechStatus').textContent='É só isso ou deseja continuar?';r.onerror=e=>$('speechStatus').textContent='Falha: '+e.error;r.start()}
async function sendFeedback(avaliacao){try{const j=await api('/api/feedback',{avaliacao,comentario:$('feedbackComment').value.trim(),canal:'celular'});$('feedbackComment').value='';$('feedbackStatus').textContent=j.message}catch(e){$('feedbackStatus').textContent=e.message}}
let knownMessages=-1,voiceEnabled=false;function toggleVoice(){voiceEnabled=!voiceEnabled;$('voiceButton').textContent=voiceEnabled?'🔊 Respostas em voz ativadas':'🔇 Ativar respostas em voz no celular';if(voiceEnabled&&'speechSynthesis'in window){const u=new SpeechSynthesisUtterance('Respostas em voz ativadas.');u.lang='pt-BR';speechSynthesis.speak(u)}}function listenNebula(){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){$('nebulaStatus').textContent='Use o microfone do teclado.';$('nebulaCommand').focus();return}const r=new SR();r.lang='pt-BR';r.interimResults=true;r.onstart=()=>$('nebulaStatus').textContent='Ouvindo...';r.onresult=e=>{let t='';for(let i=e.resultIndex;i<e.results.length;i++)t+=e.results[i][0].transcript;$('nebulaCommand').value=t};r.onend=()=>$('nebulaStatus').textContent='Confira e toque em Enviar comando.';r.onerror=e=>$('nebulaStatus').textContent='Falha: '+e.error;r.start()}function openMobileYouTube(command){const normalized=command.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();if(!normalized.includes('celular')||!/(toca|toque|youtube|musica)/.test(normalized))return false;const query=command.replace(/\b(no|do) celular\b/gi,'').replace(/\b(toca|toque|abra|abre|no youtube|youtube|uma musica|música)\b/gi,' ').trim();window.open('https://www.youtube.com/results?search_query='+encodeURIComponent(query),'_blank');$('nebulaStatus').textContent='Abrindo o YouTube neste celular.';return true}async function sendNebula(){const command=$('nebulaCommand').value.trim();if(!command)return;if(openMobileYouTube(command)){$('nebulaCommand').value='';return}try{const j=await api('/api/nebula',{command});$('nebulaCommand').value='';$('nebulaStatus').textContent=j.message;loadConversation()}catch(e){$('nebulaStatus').textContent=e.message}}async function loadConversation(){const r=await fetch('/api/conversation');if(!r.ok)return;const j=await r.json(),old=knownMessages;knownMessages=j.messages.length;$('nebulaChat').textContent=j.messages.map(m=>m.author+': '+m.text).join('\n\n')||'Pronta para receber comandos.';$('nebulaChat').scrollTop=$('nebulaChat').scrollHeight;if(voiceEnabled&&old>=0&&j.messages.length>old&&'speechSynthesis'in window)j.messages.slice(old).filter(m=>m.author==='Nebula').forEach(m=>{const u=new SpeechSynthesisUtterance(m.text);u.lang='pt-BR';speechSynthesis.speak(u)})}
function confirmSend(){const t=$('draft').value.trim();if(!t)return;$('confirmText').textContent=t;$('confirm').style.display='block'}function cancelSend(){$('confirm').style.display='none';listen()}function clearDraft(){$('draft').value='';$('confirm').style.display='none'}async function sendCodex(){try{const j=await api('/api/codex',{prompt:$('draft').value.trim()});$('confirm').style.display='none';$('output').textContent='Codex trabalhando...';poll(j.job)}catch(e){$('output').textContent=e.message}}async function poll(id){const r=await fetch('/api/job?id='+id),j=await r.json();$('output').textContent=j.output||j.status;if(!j.done)setTimeout(()=>poll(id),2000)}async function openCode(){try{$('actionStatus').textContent=(await api('/api/vscode')).message}catch(e){$('actionStatus').textContent=e.message}}async function saveIdea(){try{$('actionStatus').textContent=(await api('/api/idea',{text:$('draft').value.trim()})).message}catch(e){$('actionStatus').textContent=e.message}}fetch('/api/session').then(r=>{if(r.ok){$('login').style.display='none';$('panel').style.display='block'}})
async function shareBattery(){if(!navigator.getBattery)return;const battery=await navigator.getBattery(),send=()=>api('/api/device',{battery:Math.round(battery.level*100),charging:battery.charging}).catch(()=>{});send();battery.addEventListener('levelchange',send);battery.addEventListener('chargingchange',send)}async function loadProjects(){const r=await fetch('/api/projects');if(!r.ok)return;const j=await r.json(),s=$('project');s.innerHTML='';j.projects.forEach(p=>{const o=document.createElement('option');o.value=p.path;o.textContent=p.name+(p.path===j.active?' (ativo)':'');o.selected=p.path===j.active;s.appendChild(o)});$('projectStatus').textContent='Ativo: '+j.active}async function selectProject(path){if(!path)return;try{const j=await api('/api/project',{path});$('projectPath').value='';$('projectStatus').textContent=j.message;loadProjects()}catch(e){$('projectStatus').textContent=e.message}}async function setPaused(paused){try{const j=await api('/api/pause',{paused});showPaused(j.paused)}catch(e){$('pauseStatus').textContent=e.message}}function showPaused(p){$('pauseStatus').textContent=p?'Nebula pausada: novos comandos estão bloqueados.':'Nebula ativa e pronta.'}async function refreshState(){const r=await fetch('/api/state');if(r.ok)showPaused((await r.json()).paused)}setInterval(refreshState,5000);setInterval(loadConversation,2000);fetch('/api/session').then(r=>{if(r.ok){$('login').style.display='none';$('panel').style.display='block';refreshState();loadProjects();loadConversation();shareBattery()}})
let installPrompt;window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installPrompt=e;$('install').style.display='block'});$('install').onclick=async()=>{if(!installPrompt)return;installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;$('install').style.display='none'};window.addEventListener('appinstalled',()=>{$('install').style.display='none'});if('serviceWorker'in navigator)window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js'));
</script></body></html>'''

MANIFEST = json.dumps({
    "name": "Nebula Assistente", "short_name": "Nebula",
    "description": "Controle remoto privado da assistente Nebula",
    "start_url": "/", "scope": "/", "display": "standalone",
    "background_color": "#ffffff", "theme_color": "#278cf5",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}, ensure_ascii=False)

SERVICE_WORKER = '''self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.map(key=>caches.delete(key)))).then(()=>self.registration.unregister())));'''

HTML_NOJS = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#278cf5"><link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/icon-192.png"><title>Nebula</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:#172033;font-family:system-ui,"Segoe UI",sans-serif}.app{max-width:680px;min-height:100vh;margin:auto;padding:24px;background:#fff}.top{display:flex;align-items:center;gap:12px;margin-bottom:24px}.orb{width:44px;height:44px;border-radius:50%;background:radial-gradient(circle at 65% 65%,#9bd7ff,#278cf5 65%,#126ed1);box-shadow:0 7px 20px #278cf540}h1,h2{margin:0}h2{font-size:18px;margin-bottom:10px}.sub,.status{color:#667085;font-size:14px}.card{border:1px solid #e4e9f0;border-radius:18px;padding:18px;margin:14px 0;box-shadow:0 5px 18px #1720330a}textarea,input,select{width:100%;padding:14px;border:1px solid #d7dee8;border-radius:13px;font:inherit;background:#fff}textarea{min-height:100px;resize:vertical}.row{display:flex;gap:9px;flex-wrap:wrap;margin-top:12px}button,.button{border:0;border-radius:12px;padding:12px 15px;font-weight:650;text-decoration:none}.primary{background:#278cf5;color:#fff}.secondary{background:#eef6ff;color:#126ed1}.danger{background:#fff1f0;color:#c43224}.output{max-height:340px;overflow:auto;white-space:pre-wrap;background:#f7f9fc;border-radius:12px;padding:14px}</style></head><body><main class="app"><header class="top"><div class="orb"></div><h1>Nebula</h1></header>
<div class="card"><h2>Comando para o computador</h2><p class="sub">Controla aplicativos, jogos, mídia, prints e outras funções da Nebula no PC.</p><form method="post" action="/command"><textarea name="command" placeholder="Ex.: abra o Discord ou pause o vídeo" required></textarea><div class="row"><button class="primary" type="submit">Enviar ao computador</button></div></form></div>
<div class="card"><h2>Comando para o celular</h2><p class="sub">Abre serviços neste telefone. Você pode ditar usando o microfone do teclado.</p><form method="post" action="/phone-command"><textarea name="command" placeholder="Ex.: toque After Dark no celular" required></textarea><div class="row"><button class="primary" type="submit">Executar no celular</button></div></form></div>
<div class="card"><h2>Histórico da Nebula</h2><div class="output"><!--SERVER_HISTORY--></div><div class="row"><a class="button secondary" href="/?refresh=1">Atualizar histórico</a></div></div>
<div class="card"><h2>Controles</h2><div class="row"><form method="post" action="/vscode"><button class="secondary" type="submit">Abrir VS Code</button></form><form method="post" action="/pause-form"><input type="hidden" name="paused" value="1"><button class="danger" type="submit">Pausar Nebula</button></form><form method="post" action="/pause-form"><input type="hidden" name="paused" value="0"><button class="secondary" type="submit">Retomar Nebula</button></form></div></div>
<div class="card"><h2>Projeto e VS Code</h2><p class="status">Projeto ativo: <!--ACTIVE_PROJECT--></p><form method="post" action="/project-form"><select name="path"><!--PROJECT_OPTIONS--></select><input name="custom_path" style="margin-top:10px" placeholder="Ou informe o caminho completo"><div class="row"><button class="primary" type="submit">Selecionar projeto</button></div></form></div>
<div class="card"><h2>Falar com o Codex</h2><form method="post" action="/codex-form"><textarea name="prompt" placeholder="Descreva a tarefa para o Codex" required></textarea><div class="row"><button class="primary" type="submit">Enviar ao Codex</button></div></form></div><!--CODEX_STATUS-->
<div class="card"><h2>Salvar ideia</h2><form method="post" action="/idea-form"><textarea name="text" placeholder="Digite ou dite sua ideia" required></textarea><div class="row"><button class="secondary" type="submit">Salvar ideia</button></div></form></div>
</main></body></html>'''


def make_icon(size: int) -> bytes:
    image = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(image)
    margin = int(size * .14)
    maximum = size // 2 - margin
    for radius in range(maximum, 0, -1):
        ratio = radius / maximum
        color = (int(39 + 115 * (1 - ratio)), int(140 + 75 * (1 - ratio)), 245)
        box = (size // 2 - radius, size // 2 - radius, size // 2 + radius, size // 2 + radius)
        draw.ellipse(box, fill=color)
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class State:
    def __init__(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        else:
            data = {"pin": f"{secrets.randbelow(1_000_000):06d}"}
        if "device_token" not in data:
            data["device_token"] = secrets.token_urlsafe(32)
        CONFIG_FILE.write_text(json.dumps(data), encoding="utf-8")
        try:
            CONFIG_FILE.chmod(0o600)
        except OSError:
            pass
        self.pin = data["pin"]
        self.device_token = data["device_token"]
        self.dark_mode = bool(data.get("dark_mode", False))
        self.selected_project = data.get("selected_project", str(PROJETO))
        if not Path(self.selected_project).is_dir():
            self.selected_project = str(PROJETO)
        self.sessions: set[str] = {self.device_token}
        self.login_failures: dict[str, list[float]] = {}
        # Bilhetes de uso único que a própria Nebula emite para abrir o front local.
        self.espaco_tickets: dict[str, float] = {}
        self.jobs: dict[str, dict[str, object]] = {}
        self.paused = False
        self.pause_callback = None
        self.theme_callback = None
        self.command_callback = None
        self.control_callback = None
        self.control_status_callback = None
        self.show_callback = None
        self.group_bridge = None
        self.tools_provider = None
        self.conversation: list[dict[str, object]] = list(data.get("conversation", []))[-100:]
        self.codex_sessions: dict[str, str] = dict(data.get("codex_sessions", {}))
        # Mantém a última posição conhecida mesmo quando o celular fica offline.
        self.device_status: dict[str, object] = dict(data.get("device_status", {}))
        self.device_commands: list[dict[str, object]] = []
        self.next_device_command = 1
        self.lock = threading.RLock()
        self.codex_run_lock = threading.Lock()

    def save(self) -> None:
        with self.lock:
            CONFIG_FILE.write_text(json.dumps({
                "pin": self.pin, "device_token": self.device_token,
                "selected_project": self.selected_project, "dark_mode": self.dark_mode,
                "conversation": self.conversation[-100:],
                "codex_sessions": self.codex_sessions,
                "device_status": self.device_status,
            }, ensure_ascii=False), encoding="utf-8")
            try:
                CONFIG_FILE.chmod(0o600)
            except OSError:
                pass


STATE = State()


def set_dark_mode(enabled: bool) -> None:
    STATE.dark_mode = bool(enabled)
    STATE.save()
    if STATE.theme_callback:
        STATE.theme_callback(STATE.dark_mode)


def get_dark_mode() -> bool:
    return STATE.dark_mode


def add_conversation_message(author: str, text: str) -> None:
    with STATE.lock:
        ultima = STATE.conversation[-1] if STATE.conversation else None
        # Aviso de estado repetido (a cada arranque vinha outro "Nebula pronta")
        # so poluia o chat: o mesmo aviso seguido do Sistema entra uma vez.
        if author == "Sistema" and ultima and ultima.get("author") == author and ultima.get("text") == text:
            return
        STATE.conversation.append({
            "id": uuid.uuid4().hex,
            "author": author,
            "text": text,
            "created_at": time.time(),
        })
        del STATE.conversation[:-100]
        STATE.save()


def get_conversation() -> list[dict[str, object]]:
    """Retorna uma cópia consistente do histórico compartilhado."""
    with STATE.lock:
        return [dict(message) for message in STATE.conversation]


def register_conversation_feedback(
    avaliacao: str,
    comentario: str = "",
    canal: str = "conversa",
) -> dict[str, object]:
    alvo = encontrar_ultima_interacao(get_conversation(), {"Nebula"})
    if not alvo:
        raise ValueError("Ainda não há uma resposta da Nebula para avaliar.")
    return MEMORIA.registrar_feedback(
        canal=canal,
        autor=alvo["autor"],
        pergunta=alvo["pergunta"],
        resposta=alvo["resposta"],
        avaliacao=avaliacao,
        comentario=comentario,
        alvo_id=alvo["alvo_id"],
    )


def get_phone_battery() -> tuple[int, bool] | None:
    with STATE.lock:
        level = STATE.device_status.get("battery")
        charging = bool(STATE.device_status.get("charging", False))
    return (int(level), charging) if isinstance(level, (int, float)) else None


def get_device_status() -> dict[str, object]:
    """Snapshot seguro dos dados enviados pelo Android."""
    with STATE.lock:
        return dict(STATE.device_status)


def queue_device_command(action: str) -> int:
    allowed = {"media_play_pause", "media_next", "media_previous", "flashlight_on", "flashlight_off", "locate", "lock_nebula", "unlock_nebula"}
    if action not in allowed:
        raise ValueError("Ação móvel inválida")
    with STATE.lock:
        command_id = STATE.next_device_command
        STATE.next_device_command += 1
        STATE.device_commands.append({"id": command_id, "action": action, "created_at": time.time()})
        del STATE.device_commands[:-50]
    return command_id


def get_job(job_id: str) -> dict[str, object]:
    job = STATE.jobs.get(job_id)
    if job is not None:
        return job
    if re.fullmatch(r"[0-9a-f]{32}", job_id):
        saved = CONFIG_DIR / f"codex-{job_id}.txt"
        if saved.exists():
            return {"done": True, "status": "Concluído", "output": saved.read_text(encoding="utf-8", errors="replace")}
    return {"done": True, "status": "Não encontrado", "output": ""}


def get_latest_job() -> dict[str, object] | None:
    with STATE.lock:
        if STATE.jobs:
            job_id = next(reversed(STATE.jobs))
            return {"id": job_id, **STATE.jobs[job_id]}
    saved_jobs = sorted(CONFIG_DIR.glob("codex-*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not saved_jobs:
        return None
    saved = saved_jobs[0]
    job_id = saved.stem.removeprefix("codex-")
    return {"id": job_id, "started_at": saved.stat().st_mtime, "project": "Projeto usado na execução", **get_job(job_id)}


def discover_projects() -> list[dict[str, str]]:
    paths = {Path(STATE.selected_project), PROJETO}
    storage = Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "globalStorage" / "storage.json"
    try:
        data = json.loads(storage.read_text(encoding="utf-8"))
        def collect(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    collect(key); collect(item)
            elif isinstance(value, list):
                for item in value: collect(item)
            elif isinstance(value, str) and value.startswith("file:///"):
                path = Path(unquote(urlparse(value).path.lstrip("/")))
                if "AppData\\Local\\Temp" not in str(path): paths.add(path)
        collect(data)
    except (OSError, ValueError):
        pass
    # storage.json so guarda as janelas abertas. Cada pasta ja aberta no VS Code
    # tem um diretorio em workspaceStorage apontando para ela; a data dele diz
    # quando foi usada, e e isso que ordena a lista pelo uso. Pastas apagadas,
    # temporarias e do Windows ficam de fora.
    usado_em: dict[Path, float] = {}
    base = Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "workspaceStorage"
    try:
        pastas = list(base.iterdir()) if base.is_dir() else []
    except OSError:
        pastas = []
    for pasta in pastas:
        try:
            uri = json.loads((pasta / "workspace.json").read_text(encoding="utf-8")).get("folder", "")
            if not isinstance(uri, str) or not uri.startswith("file:///"):
                continue
            caminho = Path(unquote(urlparse(uri).path.lstrip("/")))
            quando = max((item.stat().st_mtime for item in pasta.iterdir()), default=pasta.stat().st_mtime)
        except (OSError, ValueError):
            continue
        paths.add(caminho)
        usado_em[caminho] = max(usado_em.get(caminho, 0.0), quando)
    sistema = Path(os.environ.get("SystemRoot", "C:\\Windows")).resolve()
    valid: dict[Path, float] = {}
    for path in paths:
        try:
            if not path.is_dir() or "AppData\\Local\\Temp" in str(path):
                continue
            resolvido = path.resolve()
        except OSError:
            continue
        if resolvido == sistema or sistema in resolvido.parents:
            continue
        valid[resolvido] = max(valid.get(resolvido, 0.0), usado_em.get(path, 0.0))
    # Usado por ultimo primeiro; o que nunca teve data vai para o fim, em ordem alfabetica.
    ordenados = sorted(valid.items(), key=lambda item: (-item[1], item[0].name.lower(), str(item[0]).lower()))
    return [{"name": path.name or str(path), "path": str(path), "git": (path / ".git").exists(),
             "used_at": quando or None} for path, quando in ordenados]


def render_html() -> str:
    options = []
    for project in discover_projects():
        selected = " selected" if project["path"] == STATE.selected_project else ""
        options.append(
            f'<option value="{html.escape(project["path"], quote=True)}"{selected}>'
            f'{html.escape(project["name"])}</option>'
        )
    with STATE.lock:
        messages = list(STATE.conversation[-20:])
    history = "\n\n".join(
        f'{html.escape(item["author"])}: {html.escape(item["text"])}'
        for item in messages
    ) or "Nenhuma mensagem ainda."
    latest = get_latest_job()
    if latest:
        elapsed = max(0, int(time.time() - float(latest.get("started_at", time.time()))))
        state = "Concluído" if latest.get("done") else f"Executando há {elapsed // 60} min {elapsed % 60} s"
        result = html.escape(str(latest.get("output") or latest.get("status", "Executando")))
        codex_status = f'<div class="card"><h2>Último trabalho do Codex</h2><p class="status"><b>{state}</b> — {html.escape(str(latest.get("project", "")))}</p><div class="output">{result}</div><div class="row"><a class="button secondary" href="/job?id={latest["id"]}">Abrir resultado completo</a><a class="button secondary" href="/?refresh=codex">Atualizar</a></div></div>'
    else:
        codex_status = '<div class="card"><h2>Último trabalho do Codex</h2><p class="status">Nenhuma tarefa enviada ainda.</p></div>'
    page = (
        HTML_NOJS.replace("<!--PROJECT_OPTIONS-->", "".join(options))
        .replace("<!--ACTIVE_PROJECT-->", html.escape(STATE.selected_project))
        .replace("<!--SERVER_HISTORY-->", history)
        .replace("<!--CODEX_STATUS-->", codex_status)
    )
    dark_css = '''<style>body.dark{background:#080d17;color:#e7eef8}body.dark .app{background:#0b1220}body.dark .card{background:#101a2a;border-color:#26344a;box-shadow:0 6px 22px #0005}body.dark .sub,body.dark .status{color:#9aa9bc}body.dark textarea,body.dark input,body.dark select{background:#151f31;color:#e7eef8;border-color:#34445e}body.dark .output{background:#111a2b;color:#dce8f7}body.dark .secondary{background:#172c46;color:#8dc7ff}body.dark .danger{background:#3b1d26;color:#ff9da8}</style>'''
    theme_value = "0" if STATE.dark_mode else "1"
    theme_label = "Modo claro" if STATE.dark_mode else "Modo escuro"
    theme_form = f'<a class="button secondary" href="/orb">Modo esfera</a><form method="post" action="/theme"><input type="hidden" name="dark" value="{theme_value}"><button class="secondary" type="submit">{theme_label}</button></form>'
    return page.replace("</head>", dark_css + "</head>").replace("<body>", '<body class="dark">' if STATE.dark_mode else "<body>").replace("</header>", theme_form + "</header>", 1)


def render_orb() -> str:
    background = "#080d17" if STATE.dark_mode else "#ffffff"
    foreground = "#e7eef8" if STATE.dark_mode else "#172033"
    page = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#278cf5"><title>Nebula — Modo esfera</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:{background};color:{foreground};font-family:system-ui;overflow:hidden}}main{{min-height:100vh;display:grid;place-items:center;position:relative;padding:24px}}.orb{{width:min(62vw,330px);aspect-ratio:1;border:0;border-radius:50%;cursor:pointer;background:radial-gradient(circle at 64% 66%,#a8ddff 0,#68b9fa 27%,#278cf5 68%,#126ed1 100%);box-shadow:0 0 24px #278cf548,0 0 70px #278cf538,0 0 130px #278cf520;transition:filter .5s ease}}.orb.listening{{filter:brightness(1.12)}}.orb.speaking{{animation:breathe 4.5s ease-in-out infinite}}@keyframes breathe{{0%,100%{{transform:scale(.97);box-shadow:0 0 24px #278cf548,0 0 70px #278cf538,0 0 130px #278cf520}}50%{{transform:scale(1.04);box-shadow:0 0 32px #278cf570,0 0 92px #278cf550,0 0 155px #278cf32}}}}.status{{position:absolute;bottom:9vh;text-align:center;color:{foreground};opacity:.72;font-size:15px;max-width:85vw}}.back{{position:absolute;top:calc(20px + env(safe-area-inset-top));left:22px;color:{foreground};text-decoration:none;opacity:.65}}</style></head><body><main><a class="back" href="/">← Voltar</a><button id="orb" class="orb" aria-label="Toque para falar"></button><div id="status" class="status">Toque na esfera para falar</div></main><script>
const orb=document.getElementById('orb'),status=document.getElementById('status');let listening=false,baseline=0;
async function conversation(){{const r=await fetch('/api/conversation');return r.ok?(await r.json()).messages:[]}}
async function waitReply(){{for(let i=0;i<45;i++){{await new Promise(r=>setTimeout(r,1000));const messages=await conversation();const newer=messages.slice(baseline).filter(m=>m.author==='Nebula');if(newer.length){{speak(newer[newer.length-1].text);return}}}}status.textContent='A resposta demorou. Toque para consultar novamente.'}}
function speak(text){{status.textContent=text;orb.className='orb speaking';if(!('speechSynthesis'in window)){{orb.className='orb';return}}speechSynthesis.cancel();const voice=new SpeechSynthesisUtterance(text);voice.lang='pt-BR';voice.rate=.95;voice.onend=()=>{{orb.className='orb';status.textContent='Toque na esfera para falar novamente'}};voice.onerror=voice.onend;speechSynthesis.speak(voice)}}
async function start(){{if(listening)return;const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){{status.textContent='Este navegador não liberou reconhecimento de voz. Use o campo da tela principal.';return}}listening=true;baseline=(await conversation()).length;const recognition=new SR();recognition.lang='pt-BR';recognition.interimResults=true;recognition.continuous=false;recognition.onstart=()=>{{orb.className='orb listening';status.textContent='Ouvindo...'}};recognition.onresult=e=>{{let text='';for(let i=e.resultIndex;i<e.results.length;i++)text+=e.results[i][0].transcript;status.textContent=text;recognition.command=text}};recognition.onerror=e=>{{listening=false;orb.className='orb';status.textContent='Não consegui ouvir: '+e.error}};recognition.onend=async()=>{{listening=false;orb.className='orb';const command=(recognition.command||'').trim();if(!command){{status.textContent='Não ouvi nada. Toque e tente novamente.';return}}status.textContent='Enviando: '+command;try{{const r=await fetch('/api/nebula',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{command}})}});if(!r.ok)throw Error((await r.json()).error||'Falha');status.textContent='Nebula está processando...';waitReply()}}catch(e){{status.textContent=e.message}}}};recognition.start()}}
orb.addEventListener('click',start);
</script></body></html>'''
    return (
        page.replace(
            "</style>",
            """.orb{animation:halo 7s ease-in-out infinite}.orb.speaking{animation:breathe 4.5s ease-in-out infinite}@keyframes halo{0%,100%{box-shadow:0 0 22px #278cf540,0 0 66px #278cf530,0 0 120px #278cf51c}50%{box-shadow:0 0 29px #278cf558,0 0 82px #278cf542,0 0 143px #278cf52b}}</style>""",
            1,
        )
        .replace("#278cf32", "#278cf532")
        .replace(
            "baseline=(await conversation()).length",
            "conversation().then(messages=>baseline=messages.length)",
        )
    )


def criar_ticket_espaco() -> str:
    """Bilhete de uso único para a Nebula abrir o front espacial em 127.0.0.1.

    A janela do front é aberta pelo próprio processo, que não tem como entregar
    um cookie ao navegador. O bilhete vale uma vez, expira em segundos e só é
    aceito vindo do loopback — quem está na rede continua precisando do PIN.
    """
    ticket = secrets.token_urlsafe(24)
    agora = time.monotonic()
    with STATE.lock:
        STATE.espaco_tickets = {
            chave: prazo for chave, prazo in STATE.espaco_tickets.items() if prazo > agora
        }
        if len(STATE.espaco_tickets) > 8:
            STATE.espaco_tickets.clear()
        STATE.espaco_tickets[ticket] = agora + ESPACO_TICKET_SEGUNDOS
    return ticket


def consumir_ticket_espaco(ticket: str) -> str | None:
    """Troca um bilhete válido por um token de sessão; ``None`` se não servir."""
    if not ticket:
        return None
    agora = time.monotonic()
    with STATE.lock:
        prazo = STATE.espaco_tickets.pop(ticket, None)
        if prazo is None or prazo <= agora:
            return None
        token = secrets.token_urlsafe(32)
        if len(STATE.sessions) >= 32:
            STATE.sessions = {STATE.device_token}
        STATE.sessions.add(token)
    return token


def url_espaco(host: str = "127.0.0.1", porta: int = PORTA) -> str:
    """Endereço do front espacial já com o bilhete de acesso local."""
    return f"http://{host}:{porta}/espaco/?ticket={criar_ticket_espaco()}"


def raiz_colaboracao() -> Path:
    """Raiz do projeto para o backend da colaboracao.

    Nao da para usar ``PROJETO``: aquilo e a pasta que *contem* projetos
    (``parent.parent`` no exe), entao o store e o SESSOES.md cairiam um nivel
    acima. Aqui se procura quem realmente tem ``services/collaboration``.
    """
    candidatos = [Path(__file__).resolve().parent]
    try:
        executavel = Path(sys.executable).resolve().parent
        candidatos.extend((executavel, executavel.parent))
    except (OSError, ValueError):
        pass
    for base in candidatos:
        if (base / "services" / "collaboration").is_dir():
            return base
    # Sem a pasta no disco (exe movido para fora do projeto) o _MEIPASS nao
    # serve: e temporario e some ao fechar. Grava ao lado do executavel.
    return candidatos[1] if getattr(sys, "frozen", False) and len(candidatos) > 1 else candidatos[0]


_COLABORACAO: dict[str, object] = {"api": None, "tentado_em": 0.0}
_COLABORACAO_PROJETOS: dict[str, object] = {}
_COLABORACAO_LOCK = threading.RLock()
# Todo pedido novo nasce com o maximo que o backend aceita por agente: o Denis
# nao quer ter de pedir orcamento. O limite real e o de cada provedor.
ORCAMENTO_MAXIMO = 2_000_000


def esquecer_colaboracao() -> None:
    """Zera o cache das instancias por projeto; usado nos testes."""
    with _COLABORACAO_LOCK:
        _COLABORACAO.update(api=None, tentado_em=0.0)
        _COLABORACAO.pop("tentado_projeto", None)
        _COLABORACAO_PROJETOS.clear()
COLABORACAO_AUSENTE = (
    "O painel de colaboracao ainda nao esta disponivel. O backend e mantido pelo "
    "Codex em services/collaboration/; assim que a API existir, o painel liga sozinho."
)


# So o processo que serve o painel e dono das rodadas da Dupla. Qualquer outro
# que abra a Dupla no mesmo projeto (a suite de testes, o autopilot, um script)
# enxergava a rodada viva da Nebula como "orfa", matava o CLI no meio (codex
# encerrou com codigo 15) e encerrava a conversa com "a Nebula reiniciou".
_SERVINDO_PAINEL = False
ARQUIVO_DONO = "dono_das_rodadas.json"


def _processo_vivo(registro) -> bool:
    import psutil

    try:
        processo = psutil.Process(int(registro["pid"]))
        return abs(processo.create_time() - float(registro["criado"])) < 0.01
    except (psutil.Error, KeyError, TypeError, ValueError):
        return False


def liberar_rodadas_orfas(api) -> None:
    """Destrava conversa e execucao que ficaram presas de um processo anterior.

    As duas travas valem por processo: a thread que responderia morreu junto com
    a Nebula. Sem isto, o painel fica para sempre em "as duas estao respondendo"
    e recusa toda rodada nova, sem nenhum botao que resolva - e de fora de casa,
    pelo celular, nao ha como abrir o banco na mao.

    Orfa e so a rodada cujo dono morreu. Com o dono vivo (outra Nebula, ou esta
    mesma reabrindo o projeto), nao se mexe em nada.
    """
    import psutil

    arquivo = Path(api.store.directory) / ARQUIVO_DONO
    try:
        dono = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        dono = None
    if isinstance(dono, dict) and _processo_vivo(dono):
        return
    try:
        estado = api.store.snapshot()
    except Exception:
        return
    conversa = estado.get("active_chat") or {}
    if conversa.get("id"):
        try:
            processo = conversa.get("process")
            if processo:
                import psutil
                from services.collaboration.development_transport import stop_process_tree
                try:
                    cli = psutil.Process(processo["pid"])
                    if abs(cli.create_time() - processo["created"]) < 0.01:
                        stop_process_tree(cli)
                except psutil.NoSuchProcess:
                    pass
            api.store.end_chat(conversa["id"])
            api.store.message(conversa["idea_id"], "system",
                              "Conversa anterior foi encerrada porque a Nebula reiniciou "
                              "no meio da rodada.", "chat_error")
        except Exception:
            pass
    execucao = estado.get("active_run") or {}
    identificador = execucao.get("id") if isinstance(execucao, dict) else execucao
    if identificador:
        try:
            api.store.end_run(identificador, "failed")
        except Exception:
            pass
    try:
        eu = psutil.Process()
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps({"pid": eu.pid, "criado": eu.create_time()}),
                              encoding="utf-8")
        os.replace(temporario, arquivo)
    except OSError:
        pass


def token_ponte_gemini() -> str:
    """Token da ponte do Gemini: do ambiente ou, no Windows, do registro do usuario.

    A Nebula costuma ser aberta por processos que nasceram antes de o token ser
    gravado, e ai a variavel nao esta no ambiente dela. O registro do usuario e a
    fonte que nao envelhece.
    """
    valor = os.environ.get("NEBULA_GEMINI_BRIDGE_TOKEN", "").strip()
    if valor or os.name != "nt":
        return valor
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as chave:
            return str(winreg.QueryValueEx(chave, "NEBULA_GEMINI_BRIDGE_TOKEN")[0]).strip()
    except OSError:
        return ""


TIPOS_DA_CONVERSA = ("user_message", "chat_reply", "chat_error", "confirmation")


def conversa_dupla(estado: dict, depois: int, ideia_conhecida: str) -> dict:
    """So o que o chat do celular precisa, a partir de um cursor.

    O snapshot inteiro tem centenas de KB; buscado a cada 3 s pelo 4G daria
    mais de 300 MB por hora de chat aberto. Aqui vai apenas o que e novo na
    conversa atual. A conversa atual e o pedido mais recente, a mesma regra do
    painel do PC, para as duas telas mostrarem a mesma coisa.
    """
    ideias = estado.get("ideas") or []
    ideia = ideias[-1] if ideias else None
    ideia_id = ideia["id"] if ideia else None
    # Pedido novo desde a ultima consulta: o celular recomeca do zero.
    recomecar = ideia_id != (ideia_conhecida or None)
    if recomecar:
        depois = 0
    mensagens, cursor = [], depois
    for evento in estado.get("messages") or []:
        seq = int(evento.get("seq") or 0)
        cursor = max(cursor, seq)
        if seq <= depois or evento.get("idea") != ideia_id:
            continue
        if evento.get("kind") not in TIPOS_DA_CONVERSA:
            continue
        dados = evento.get("data") or {}
        texto = dados.get("text")
        if not texto:
            continue
        mensagens.append({
            "seq": seq, "em": evento.get("at"), "autor": evento.get("actor"),
            "tipo": evento.get("kind"), "texto": texto, "modelo": dados.get("model"),
        })
    return {
        "ideia": {"id": ideia_id, "texto": ideia["text"]} if ideia else None,
        "recomecar": recomecar,
        "respondendo": bool(estado.get("active_chat")),
        # "development" quando as duas estao implementando: o celular mostra Parar.
        "modo": (estado.get("active_chat") or {}).get("mode") or ("conversa" if estado.get("active_chat") else None),
        "cursor": cursor,
        "mensagens": mensagens,
    }


def colaboracao():
    with _COLABORACAO_LOCK:
        return _colaboracao_do_projeto()


def _colaboracao_do_projeto():
    """Carrega ``CollaborationAPI`` sob demanda, sem travar o painel.

    O backend e do outro agente e pode aparecer a qualquer momento; repetir a
    importacao de tempos em tempos evita exigir reinicio da Nebula. O contrato
    esta em services/collaboration/README.md: uma instancia por projeto e todo
    o resto por ``handle(metodo, caminho, corpo)``.
    """
    api = _COLABORACAO["api"]
    projeto = Path(STATE.selected_project).resolve()
    if not projeto.is_dir():
        raise ValueError("Selecione uma pasta de projeto existente.")
    chave = str(projeto).casefold()
    if api is not None and (not hasattr(api, "store") or api.store.root == projeto):
        return api
    if api is not None and chave in _COLABORACAO_PROJETOS:
        _COLABORACAO["api"] = _COLABORACAO_PROJETOS[chave]
        return _COLABORACAO["api"]
    agora = time.monotonic()
    if _COLABORACAO.get("tentado_projeto") == chave and agora - float(_COLABORACAO["tentado_em"]) < 5:
        return None
    _COLABORACAO["tentado_em"] = agora
    _COLABORACAO["tentado_projeto"] = chave
    try:
        # O backend e do outro agente e muda sem passar por aqui. Congelado no
        # exe, ele envelhece a cada build: foi assim que o chat da Dupla passou
        # a responder 404 com a rota ja pronta no disco. Por isso a fonte em
        # disco entra no sys.path e nao se empacota copia nenhuma.
        raiz = raiz_colaboracao()
        if str(raiz) not in sys.path:
            sys.path.insert(0, str(raiz))
        from services.collaboration.api import CollaborationAPI

        # O backend chama os CLIs sem ferramenta nenhuma. Denis autorizou acesso
        # real ao repositorio, entao entra o provedor daqui pela porta que o
        # proprio backend abre, sem editar nada de services/collaboration/.
        provedor = None
        try:
            import colaboracao_ferramentas

            if colaboracao_ferramentas.ativo():
                provedor = colaboracao_ferramentas.ProvedorComAcesso()
        except Exception:
            provedor = None
        api = CollaborationAPI(projeto, provedor) if provedor else CollaborationAPI(projeto)
        if provedor is not None:
            # O store so existe depois da API: e dele que sai a memoria
            # comprimida entregue a quem voltou de um corte de cota.
            provedor.store = api.store
        if _SERVINDO_PAINEL:
            liberar_rodadas_orfas(api)
    except Exception:
        return None
    _COLABORACAO["api"] = api
    _COLABORACAO_PROJETOS[chave] = api
    return api


class ServidorExclusivo(ThreadingHTTPServer):
    """Servidor que não aceita dividir a porta com outro processo.

    No Windows, dois servidores com ``SO_REUSEADDR`` conseguem escutar a mesma
    porta e as conexões se dividem entre eles de forma imprevisível — foi assim
    que a ponte do Gemini passou a responder no lugar do painel. Com
    ``SO_EXCLUSIVEADDRUSE`` o segundo a subir falha na hora, com erro claro,
    e ainda assim é possível reabrir a porta depois que este processo encerra.
    """

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt":
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1
                )
            except OSError:
                pass
        super().server_bind()


def find_codex() -> str | None:
    found = shutil.which("codex")
    if found:
        return found
    extensions = Path.home() / ".vscode" / "extensions"
    candidates = sorted(
        extensions.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None: pass
    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self' https://www.youtube.com https://www.google.com https://mail.google.com https://wa.me")
        super().end_headers()
    def json_response(self, code: int, data: dict[str, object], token: str | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if token: self.send_header("Set-Cookie", f"nebula_session={token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=315360000")
        self.end_headers(); self.wfile.write(body)
    def authorized(self) -> bool:
        power_token = self.headers.get("X-Nebula-Power-Token", "")
        if power_token and secrets.compare_digest(power_token, POWER_TOKEN):
            return True
        supplied = self.headers.get("X-Nebula-Token", "")
        if supplied:
            with STATE.lock:
                if any(secrets.compare_digest(supplied, token) for token in STATE.sessions):
                    return True
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        session = jar.get("nebula_session")
        return bool(session and session.value in STATE.sessions)
    def body(self, limit: int = MAX_BODY_BYTES) -> dict[str, object]:
        size = int(self.headers.get("Content-Length", "0"))
        if size < 0 or size > limit:
            raise ValueError("Corpo da requisição excede o limite")
        data = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("O corpo deve ser um objeto JSON")
        return data
    def login_limited(self) -> bool:
        now = time.monotonic()
        key = self.client_address[0]
        with STATE.lock:
            failures = [stamp for stamp in STATE.login_failures.get(key, []) if now - stamp < LOGIN_WINDOW_SECONDS]
            STATE.login_failures[key] = failures
            return len(failures) >= LOGIN_MAX_FAILURES
    def record_login_failure(self) -> None:
        with STATE.lock:
            STATE.login_failures.setdefault(self.client_address[0], []).append(time.monotonic())
    def redirect(self, location: str = "/") -> None:
        self.send_response(303); self.send_header("Location", location); self.send_header("Content-Length", "0"); self.end_headers()
    def loopback(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")
    def servir_espaco(self, parsed) -> None:
        """Front espacial: ``/espaco/`` entrega o index e ``/espaco/<arquivo>`` os assets."""
        nome = parsed.path[len("/espaco"):].lstrip("/")
        ticket = parse_qs(parsed.query).get("ticket", [""])[0]
        token = consumir_ticket_espaco(ticket) if ticket and self.loopback() else None
        if token:
            # Sem "Secure": o bilhete só vale no loopback, que não usa HTTPS.
            self.send_response(303); self.send_header("Location", "/espaco/")
            self.send_header("Set-Cookie", f"nebula_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=315360000")
            self.send_header("Content-Length", "0"); self.end_headers(); return
        if not self.authorized(): self.redirect(); return
        if not nome:
            if not parsed.path.endswith("/"): self.redirect("/espaco/"); return
            nome = "index.html"
        recurso = front_assets.carregar(nome)
        if recurso is None:
            if nome != "index.html": self.send_error(404); return
            body, tipo = front_assets.INDISPONIVEL.encode(), "text/html; charset=utf-8"
        else:
            body, tipo = recurso
        self.send_response(200); self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def servir_colaboracao(self, metodo: str, caminho: str, corpo: dict) -> None:
        """Repassa o pedido ao backend da colaboracao, ja atras da autenticacao."""
        api = colaboracao()
        if api is None:
            self.json_response(503, {"error": COLABORACAO_AUSENTE, "aguardando_backend": True}); return
        if metodo == "POST" and isinstance(corpo, dict):
            corpo = dict(corpo)
            if caminho in ("/api/collaboration/ideas", "/api/collaboration/develop"):
                corpo["token_budget"] = ORCAMENTO_MAXIMO
            elif caminho == "/api/collaboration/chat" and not corpo.get("idea_id") and hasattr(api, "store"):
                # O backend criaria o pedido com o padrao de 60 mil; nasce no maximo.
                try:
                    corpo["idea_id"] = api.store.create_idea(corpo.get("text"), ORCAMENTO_MAXIMO)["id"]
                except (ValueError, TypeError) as exc:
                    self.json_response(400, {"error": str(exc)}); return
        try:
            status, payload = api.handle(metodo, caminho, corpo)
        except Exception as exc:
            self.json_response(502, {"error": f"O backend da colaboração falhou: {exc}"}); return
        self.json_response(int(status), payload if isinstance(payload, dict) else {"data": payload})
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/transfer/messages":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            self.json_response(200, {"messages": CHAT_STORE.messages()}); return
        if parsed.path == "/api/transfer/file":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            message_id = parse_qs(parsed.query).get("id", [""])[0]
            try:
                item, path = CHAT_STORE.file(message_id)
                body = path.read_bytes()
            except (OSError, FileNotFoundError):
                self.json_response(404, {"error": "Arquivo não encontrado"}); return
            self.send_response(200)
            self.send_header("Content-Type", str(item.get("mime") or "application/octet-stream"))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote_plus(str(item.get("filename") or "arquivo")))
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/media":
            if not self.authorized():
                self.json_response(401, {"error": "Nao autorizado"}); return
            known_artwork = parse_qs(parsed.query).get("artwork_id", [None])[0]
            try:
                media = MEDIA_CONTROLLER.status(known_artwork)
            except MediaControlError as exc:
                self.json_response(503, {"error": str(exc)}); return
            self.json_response(200, media); return
        if parsed.path == "/api/beamng/turbo":
            if not self.authorized(): self.json_response(401, {"error": "Nao autorizado"}); return
            BEAMNG_TURBO.start()
            self.json_response(200, BEAMNG_TURBO.status()); return
        if parsed.path in ("/api/wifi-bpm/status", "/wifi-bpm/status", "/api/rocket-overlay/status", "/rocket-overlay/status"):
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            sensor = WIFI_BPM_SENSOR if "wifi-bpm" in parsed.path else OVERLAY_BRIDGE
            self.json_response(200, sensor.status()); return
        if parsed.path == "/":
            body = (render_html() if self.authorized() else LOGIN_HTML).encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/espaco" or parsed.path.startswith("/espaco/"):
            self.servir_espaco(parsed); return
        if parsed.path == "/orb":
            if not self.authorized(): self.redirect(); return
            body = render_orb().encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/job":
            if not self.authorized(): self.redirect(); return
            job_id = parse_qs(parsed.query).get("id", [""])[0]
            job = get_job(job_id)
            refresh = "" if job.get("done") else '<meta http-equiv="refresh" content="2">'
            output = html.escape(str(job.get("output") or job.get("status", "Executando")))
            elapsed = max(0, int(time.time() - float(job.get("started_at", time.time()))))
            project = html.escape(str(job.get("project", STATE.selected_project)))
            state_label = str(job.get("status", "Concluído")) if job.get("done") else f"Executando há {elapsed // 60} min {elapsed % 60} s"
            body = f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{refresh}<title>Codex</title></head><body style="font-family:system-ui;max-width:720px;margin:auto;padding:24px"><h1>Resposta do Codex</h1><p><b>Estado:</b> {state_label}<br><b>Projeto:</b> {project}</p><pre style="white-space:pre-wrap;background:#101828;color:#e6edf6;padding:16px;border-radius:12px">{output}</pre><p>{'A página atualiza automaticamente.' if not job.get('done') else 'Tarefa finalizada.'}</p><p><a href="/">Voltar para a Nebula</a></p></body></html>'.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/install":
            body = '''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="manifest" href="/manifest.webmanifest"><meta name="theme-color" content="#278cf5"><title>Instalar Nebula</title></head><body style="font-family:system-ui;max-width:680px;margin:auto;padding:28px;color:#172033"><h1>Instalar Nebula</h1><p>Toque no botão abaixo. Se o navegador não abrir a confirmação, use o menu ⋮ e escolha <b>Adicionar à tela inicial</b> ou <b>Instalar app</b>.</p><button id="installNow" style="background:#278cf5;color:white;border:0;border-radius:12px;padding:14px 18px;font-weight:bold">Instalar agora</button><p id="status"></p><p><a href="/">Voltar</a></p><script>let prompt;window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();prompt=e;document.getElementById('status').textContent='Pronta para instalar.'});document.getElementById('installNow').onclick=async()=>{if(prompt){prompt.prompt();await prompt.userChoice}else document.getElementById('status').textContent='Abra o menu ⋮ do navegador e selecione Adicionar à tela inicial.'};if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js');</script></body></html>'''.encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/manifest.webmanifest":
            body = MANIFEST.encode(); self.send_response(200); self.send_header("Content-Type", "application/manifest+json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/sw.js":
            body = SERVICE_WORKER.encode(); self.send_response(200); self.send_header("Content-Type", "application/javascript; charset=utf-8"); self.send_header("Service-Worker-Allowed", "/"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path in ("/icon-192.png", "/icon-512.png"):
            body = make_icon(192 if "192" in parsed.path else 512); self.send_response(200); self.send_header("Content-Type", "image/png"); self.send_header("Cache-Control", "public, max-age=86400"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if parsed.path == "/api/dupla/uso":
            # Limites reais das duas IAs para o painel do celular. O token do Claude
            # fica neste processo; sai daqui so a porcentagem.
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            try:
                api = colaboracao()
                estado = api.store.snapshot() if api is not None and hasattr(api, "store") else {}
            except Exception:
                estado = {}
            self.json_response(200, uso_ias.uso(estado)); return
        if parsed.path == "/api/gemini/ponte":
            # Para copiar o token da configuracao do celular: mesma autenticacao
            # de qualquer outro comando, e so por ela.
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            token = token_ponte_gemini()
            self.json_response(200, {
                "definido": bool(token), "token": token or None,
                "porta": int(os.environ.get("NEBULA_GEMINI_BRIDGE_PORT", "8767")),
            }); return
        if parsed.path == "/api/dupla/conversa":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            api = colaboracao()
            if api is None:
                self.json_response(503, {"error": COLABORACAO_AUSENTE}); return
            consulta = parse_qs(parsed.query)
            try:
                depois = max(0, int(consulta.get("depois", ["0"])[0] or 0))
            except ValueError:
                depois = 0
            ideia = consulta.get("ideia", [""])[0]
            resposta = conversa_dupla(api.store.snapshot(), depois, ideia)
            raiz_projeto = Path(api.store.root)
            resposta["projeto"] = {"caminho": str(raiz_projeto), "nome": raiz_projeto.name or str(raiz_projeto),
                                   "git": (raiz_projeto / ".git").exists()}
            # O nome da parceira segue o modelo configurado no Codex (Astra, Sol...).
            resposta["nomes"] = {"opus": "Claude", "codex": uso_ias.modelo_codex()["nome"]}
            self.json_response(200, resposta); return
        if parsed.path == "/api/collaboration" or parsed.path.startswith("/api/collaboration/"):
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            self.servir_colaboracao("GET", parsed.path, {}); return
        if parsed.path == "/api/session": self.json_response(200 if self.authorized() else 401, {"ok": self.authorized()}); return
        if parsed.path == "/api/tools":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            executor = STATE.tools_provider() if STATE.tools_provider else None
            if executor is None:
                self.json_response(503, {"error": "Executor indisponível."}); return
            self.json_response(200, {"tools": executor.list_tools()}); return
        if parsed.path == "/api/state":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            self.json_response(200, {"paused": STATE.paused, "project": STATE.selected_project}); return
        if parsed.path == "/api/control":
            if not self.authorized(): self.json_response(401, {"error": "Nao autorizado"}); return
            callback = STATE.control_status_callback
            if callback is None:
                self.json_response(503, {"error": "Painel de controle ainda esta iniciando."}); return
            try:
                estado = callback()
            except Exception as exc:
                self.json_response(503, {"error": str(exc)}); return
            self.json_response(200, {"state": estado}); return
        if parsed.path == "/api/device":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            self.json_response(200, get_device_status()); return
        if parsed.path == "/api/device/commands":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            after = int(parse_qs(parsed.query).get("after", ["0"])[0] or 0)
            with STATE.lock: commands = [dict(c) for c in STATE.device_commands if int(c["id"]) > after]
            self.json_response(200, {"commands": commands}); return
        if parsed.path == "/api/projects":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            self.json_response(200, {"active": STATE.selected_project, "projects": discover_projects()}); return
        if parsed.path == "/api/conversation":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            with STATE.lock: messages = list(STATE.conversation)
            self.json_response(200, {"messages": messages}); return
        if parsed.path == "/api/group":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            bridge = STATE.group_bridge
            if bridge is None: self.json_response(503, {"error": "Grupo ainda não está disponível."}); return
            self.json_response(200, {
                "messages": bridge.historico(),
                "busy": bool(bridge.ocupado),
            }); return
        if parsed.path == "/api/job":
            if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
            job = parse_qs(parsed.query).get("id", [""])[0]; self.json_response(200, get_job(job)); return
        self.send_error(404)
    def do_POST(self) -> None:
        if self.path in ("/command", "/phone-command", "/vscode", "/pause-form", "/project-form", "/codex-form", "/idea-form", "/theme"):
            if not self.authorized(): self.send_error(401, "Não autorizado"); return
            try: size = int(self.headers.get("Content-Length", "0"))
            except ValueError: self.send_error(400, "Tamanho inválido"); return
            if size < 0 or size > MAX_BODY_BYTES: self.send_error(413, "Requisição muito grande"); return
            form = parse_qs(self.rfile.read(size).decode("utf-8", errors="replace"))
            if self.path == "/theme":
                set_dark_mode(form.get("dark", ["1"])[0] == "1")
                self.redirect(); return
            if self.path == "/phone-command":
                command = form.get("command", [""])[0].strip()
                normalized = "".join(c for c in unicodedata.normalize("NFD", command.lower()) if unicodedata.category(c) != "Mn")
                if any(word in normalized for word in ("youtube", "musica", "toca", "toque")):
                    query = re.sub(r"\b(no|do) celular\b|\b(toca|toque|abra|abre|no youtube|youtube|uma musica|musica)\b", " ", normalized).strip()
                    self.redirect("https://www.youtube.com/results?search_query=" + quote_plus(query)); return
                if any(word in normalized for word in ("gmail", "email", "e-mail")):
                    self.redirect("https://mail.google.com/"); return
                if "whatsapp" in normalized or "zap" in normalized:
                    self.redirect("https://wa.me/"); return
                query = re.sub(r"\b(pesquise|pesquisa|procure|buscar|busque|no celular)\b", " ", normalized).strip()
                self.redirect("https://www.google.com/search?q=" + quote_plus(query or command)); return
            if self.path == "/command":
                command = form.get("command", [""])[0].strip()
                if len(command) > MAX_COMMAND_CHARS: self.send_error(413, "Comando muito grande"); return
                normalized = "".join(c for c in unicodedata.normalize("NFD", command.lower()) if unicodedata.category(c) != "Mn")
                if "celular" in normalized and any(word in normalized for word in ("toca", "toque", "youtube", "musica")):
                    query = re.sub(r"\b(no|do) celular\b|\b(toca|toque|abra|abre|no youtube|youtube|uma musica)\b", " ", normalized).strip()
                    self.redirect("https://www.youtube.com/results?search_query=" + quote_plus(query)); return
                if command and STATE.command_callback and not STATE.paused:
                    add_conversation_message("Você", command); STATE.command_callback(command)
                self.redirect(); return
            if self.path == "/vscode":
                code = shutil.which("code")
                if code and not STATE.paused: subprocess.Popen([code, STATE.selected_project], env=child_environment())
                self.redirect(); return
            if self.path == "/project-form":
                raw_path = form.get("custom_path", [""])[0].strip() or form.get("path", [""])[0].strip()
                project = Path(raw_path).expanduser()
                if project.is_dir():
                    STATE.selected_project = str(project.resolve()); STATE.save()
                self.redirect(); return
            if self.path == "/codex-form":
                prompt = form.get("prompt", [""])[0].strip()
                if len(prompt) > MAX_PROMPT_CHARS: self.send_error(413, "Pedido muito grande"); return
                if not prompt: self.redirect(); return
                job = uuid.uuid4().hex; STATE.jobs[job] = {"done": False, "status": "Codex ativo; aguardando resposta final", "output": "", "started_at": time.time(), "project": STATE.selected_project}
                threading.Thread(target=run_codex, args=(job, prompt, STATE.selected_project), daemon=True).start()
                self.redirect("/job?id=" + job); return
            if self.path == "/idea-form":
                text = form.get("text", [""])[0].strip()
                if text: salvar_nota(text)
                self.redirect(); return
            STATE.paused = form.get("paused", ["1"])[0] != "0"
            if STATE.pause_callback: STATE.pause_callback(STATE.paused)
            self.redirect(); return
        # O APK já exige o desbloqueio seguro do próprio telefone antes de
        # chegar aqui. Troca a credencial do aparelho por uma sessão curta do
        # painel sem colocar nenhum token na URL do WebView.
        if self.path == "/api/device-session":
            power_token = self.headers.get("X-Nebula-Power-Token", "")
            if not power_token or not secrets.compare_digest(power_token, POWER_TOKEN):
                self.json_response(401, {"error": "Não autorizado"}); return
            token = secrets.token_urlsafe(32)
            with STATE.lock:
                if len(STATE.sessions) >= 32:
                    STATE.sessions = {STATE.device_token}
                STATE.sessions.add(token)
            self.json_response(200, {"ok": True, "token": token}, token)
            return
        try: data = self.body(MAX_TRANSFER_BODY_BYTES if self.path == "/api/transfer/message" else MAX_BODY_BYTES)
        except Exception: self.json_response(400, {"error": "Dados inválidos"}); return
        if self.path == "/api/login":
            if self.login_limited(): self.json_response(429, {"error": "Muitas tentativas. Aguarde 15 minutos."}); return
            if secrets.compare_digest(str(data.get("pin", "")), STATE.pin):
                # O token do aparelho pareado precisa sobreviver a reinicializações do PC;
                # caso contrário o celular perde o acesso justamente após usar Wake-on-LAN.
                token = STATE.device_token
                with STATE.lock:
                    if len(STATE.sessions) >= 32:
                        STATE.sessions = {STATE.device_token}
                    STATE.sessions.add(token)
                    STATE.login_failures.pop(self.client_address[0], None)
                self.json_response(200, {"ok": True, "token": token}, token)
            else:
                self.record_login_failure()
                self.json_response(403, {"error": "PIN incorreto"})
            return
        if not self.authorized(): self.json_response(401, {"error": "Não autorizado"}); return
        if self.path == "/api/tools/call":
            executor = STATE.tools_provider() if STATE.tools_provider else None
            if executor is None:
                self.json_response(503, {"error": "Executor indisponível."}); return
            try:
                result = executor.call_tool(data)
            except ValueError as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(200, result); return
        if self.path == "/api/transfer/message":
            try:
                encoded = data.pop("data", None)
                attachment = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) and encoded else None
                message = CHAT_STORE.add(data, attachment)
            except (ValueError, OSError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(201, {"ok": True, "message": message}); return
        if self.path == "/api/media/action":
            try:
                result = MEDIA_CONTROLLER.action(str(data.get("action", "")))
            except (MediaControlError, ValueError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(200, result); return
        if self.path in ("/api/wifi-bpm/ingest", "/api/wifi-bpm/reset", "/api/rocket-overlay/action", "/rocket-overlay/action"):
            try:
                if self.path == "/api/wifi-bpm/ingest":
                    result = WIFI_BPM_SENSOR.ingest(data)
                elif self.path == "/api/wifi-bpm/reset":
                    WIFI_BPM_SENSOR.reset()
                    result = WIFI_BPM_SENSOR.status()
                else:
                    result = OVERLAY_BRIDGE.request(data.get("action", ""), data.get("value"))
            except (ValueError, RuntimeError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(200, result); return
        if self.path == "/api/show":
            callback = STATE.show_callback
            if callback is None:
                self.json_response(503, {"error": "A janela da Nebula ainda esta iniciando."}); return
            callback()
            self.json_response(200, {"ok": True, "message": "Janela da Nebula solicitada."}); return
        if self.path == "/api/pause":
            STATE.paused = bool(data.get("paused", True))
            if STATE.pause_callback: STATE.pause_callback(STATE.paused)
            self.json_response(200, {"paused": STATE.paused}); return
        if self.path == "/api/control":
            callback = STATE.control_callback
            if callback is None:
                self.json_response(503, {"error": "Painel de controle ainda esta iniciando."}); return
            try:
                resultado = callback(str(data.get("action", "")), data.get("value"))
            except (OSError, RuntimeError, ValueError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            except Exception as exc:
                self.json_response(503, {"error": str(exc)}); return
            self.json_response(200, resultado); return
        if self.path == "/api/device":
            battery = data.get("battery")
            with STATE.lock:
                if isinstance(battery, (int, float)) and 0 <= battery <= 100:
                    STATE.device_status["battery"] = round(battery)
                    STATE.device_status["charging"] = bool(data.get("charging"))
                for key in ("latitude", "longitude", "accuracy", "location_updated_at"):
                    if isinstance(data.get(key), (int, float)): STATE.device_status[key] = data[key]
                if isinstance(data.get("notifications"), list):
                    STATE.device_status["notifications"] = data["notifications"][-30:]
                STATE.device_status["last_seen"] = time.time()
                STATE.save()
            self.json_response(200, {"ok": True}); return
        if self.path == "/api/device/command":
            try: command_id = queue_device_command(str(data.get("action", "")))
            except ValueError as exc: self.json_response(400, {"error": str(exc)}); return
            self.json_response(202, {"ok": True, "id": command_id}); return
        if self.path == "/api/feedback":
            avaliacao = str(data.get("avaliacao", "")).strip()
            comentario = str(data.get("comentario", "")).strip()
            canal = str(data.get("canal", "celular")).strip()
            if len(comentario) > 2_000: self.json_response(413, {"error": "Feedback muito grande."}); return
            try:
                register_conversation_feedback(avaliacao, comentario, canal)
            except (OSError, ValueError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(200, {"ok": True, "message": "Feedback salvo no PC."}); return
        if self.path == "/api/collaboration" or self.path.startswith("/api/collaboration/"):
            self.servir_colaboracao("POST", self.path, data); return
        if self.path == "/api/group":
            bridge = STATE.group_bridge
            if bridge is None: self.json_response(503, {"error": "Grupo ainda não está disponível."}); return
            texto = str(data.get("text", "")).strip()
            modo = str(data.get("mode", "group")).strip()
            participantes = {
                "group": ("codex",),
                "qwen": ("qwen",),
                "codex": ("codex",),
            }.get(modo)
            if participantes is None: self.json_response(400, {"error": "Modo de envio inválido."}); return
            try:
                bridge.enviar(texto, participantes)
            except ValueError as exc:
                self.json_response(400, {"error": str(exc)}); return
            except RuntimeError as exc:
                self.json_response(409, {"error": str(exc)}); return
            self.json_response(202, {"ok": True, "message": "Mensagem enviada ao grupo."}); return
        if self.path == "/api/group/feedback":
            bridge = STATE.group_bridge
            if bridge is None: self.json_response(503, {"error": "Grupo ainda não está disponível."}); return
            autor = str(data.get("author", "Codex")).strip()
            autores = {"Codex"} if autor == "Última IA" else {autor}
            if not autores <= {"Codex"}:
                self.json_response(400, {"error": "Participante inválido."}); return
            alvo = encontrar_ultima_interacao(bridge.historico(), autores)
            if not alvo: self.json_response(400, {"error": "Ainda não há uma resposta desse participante."}); return
            comentario = str(data.get("comment", "")).strip()
            if len(comentario) > 2_000: self.json_response(413, {"error": "Feedback muito grande."}); return
            try:
                MEMORIA.registrar_feedback(
                    canal="grupo-celular",
                    autor=alvo["autor"],
                    pergunta=alvo["pergunta"],
                    resposta=alvo["resposta"],
                    avaliacao=str(data.get("rating", "")),
                    comentario=comentario,
                    alvo_id=alvo["alvo_id"],
                )
            except (OSError, ValueError) as exc:
                self.json_response(400, {"error": str(exc)}); return
            self.json_response(200, {"ok": True, "message": f"Feedback sobre {alvo['autor']} salvo."}); return
        if self.path == "/api/group/clear":
            bridge = STATE.group_bridge
            if bridge is None: self.json_response(503, {"error": "Grupo ainda não está disponível."}); return
            try:
                bridge.limpar()
            except RuntimeError as exc:
                self.json_response(409, {"error": str(exc)}); return
            self.json_response(200, {"ok": True, "message": "Histórico do grupo apagado."}); return
        if STATE.paused: self.json_response(423, {"error": "Nebula está pausada. Toque em Retomar primeiro."}); return
        if self.path == "/api/nebula":
            command = str(data.get("command", "")).strip()
            if not command: self.json_response(400, {"error": "Comando vazio."}); return
            if len(command) > MAX_COMMAND_CHARS: self.json_response(413, {"error": "Comando muito grande."}); return
            if not STATE.command_callback: self.json_response(503, {"error": "Assistente ainda está iniciando."}); return
            add_conversation_message("Você", command)
            STATE.command_callback(command)
            self.json_response(202, {"message": "Comando enviado à Nebula."}); return
        if self.path == "/api/project":
            project = Path(str(data.get("path", ""))).expanduser()
            if not project.is_dir(): self.json_response(400, {"error": "Essa pasta não existe no PC."}); return
            STATE.selected_project = str(project.resolve()); STATE.save()
            self.json_response(200, {"message": f"Projeto ativo: {project.name}", "path": STATE.selected_project}); return
        if self.path == "/api/vscode":
            code = shutil.which("code")
            if not code: self.json_response(500, {"error": "VS Code não encontrado"}); return
            subprocess.Popen([code, STATE.selected_project], env=child_environment()); self.json_response(200, {"message": f"VS Code aberto em {Path(STATE.selected_project).name}."}); return
        if self.path == "/api/terminal":
            command = str(data.get("command", "")).strip()
            if not command: self.json_response(400, {"error": "Comando vazio."}); return
            if len(command) > 4000: self.json_response(413, {"error": "Comando muito grande."}); return
            try:
                completed = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                    cwd=STATE.selected_project, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60, env=child_environment(),
                )
                self.json_response(200, {"output": (completed.stdout + completed.stderr)[-20000:], "exit_code": completed.returncode, "project": STATE.selected_project}); return
            except subprocess.TimeoutExpired:
                self.json_response(408, {"error": "O comando excedeu 60 segundos."}); return
        if self.path == "/api/idea":
            text = str(data.get("text", "")).strip()
            if not text: self.json_response(400, {"error": "Ideia vazia"}); return
            path = salvar_nota(text); self.json_response(200, {"message": f"Ideia salva em {path.name}."}); return
        if self.path == "/api/codex":
            prompt = str(data.get("prompt", "")).strip()
            if not prompt: self.json_response(400, {"error": "Pedido vazio"}); return
            if len(prompt) > MAX_PROMPT_CHARS: self.json_response(413, {"error": "Pedido muito grande"}); return
            job = uuid.uuid4().hex; STATE.jobs[job] = {"done": False, "status": "Codex ativo; aguardando resposta final", "output": "", "started_at": time.time(), "project": STATE.selected_project}
            threading.Thread(target=run_codex, args=(job, prompt, STATE.selected_project), daemon=True).start(); self.json_response(202, {"job": job}); return
        self.send_error(404)


def run_codex(job: str, prompt: str, project: str) -> None:
    # Uma mesma sessão não pode receber dois turnos simultaneamente.
    with STATE.codex_run_lock:
        _run_codex(job, prompt, project)


def _run_codex(job: str, prompt: str, project: str) -> None:
    codex = find_codex()
    if not codex: STATE.jobs[job] = {"done": True, "status": "Erro", "output": "Codex não encontrado."}; return
    output = CONFIG_DIR / f"codex-{job}.txt"
    try:
        # O modo elevated não consegue alterar a ACL de alguns projetos em C:\.
        # A documentação oficial recomenda unelevated como fallback no Windows;
        # ele continua limitado ao workspace, sem usar full access.
        with STATE.lock:
            session_id = STATE.codex_sessions.get(project)
        common = ["-c", 'windows.sandbox="unelevated"', "--skip-git-repo-check", "--json", "-o", str(output)]
        if session_id:
            command = [codex, "exec", "resume", *common, session_id, prompt]
        else:
            command = [
                codex, "exec", *common, "-C", project,
                "--sandbox", "workspace-write", prompt,
            ]
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            env=child_environment(),
        )
        timer = threading.Timer(1800, process.kill)
        timer.daemon = True
        timer.start()
        raw_lines: list[str] = []
        messages: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            raw_lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "thread.started" and event.get("thread_id"):
                with STATE.lock:
                    STATE.codex_sessions[project] = str(event["thread_id"])
                    STATE.save()
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            item_type = str(item.get("type", ""))
            if event.get("type") == "item.completed" and item_type == "agent_message":
                text = str(item.get("text", "")).strip()
                if text:
                    messages.append(text)
            if event.get("type") == "item.started" and item_type == "command_execution":
                live_status = "Codex executando uma ação no projeto…"
            elif messages:
                live_status = "Codex enviou uma atualização…"
            else:
                live_status = "Codex analisando a tarefa…"
            STATE.jobs[job] = {
                **STATE.jobs.get(job, {}), "done": False,
                "status": live_status, "output": "\n\n".join(messages)[-12000:],
            }
        process.wait()
        timer.cancel()
        raw_output = "".join(raw_lines)
        answer = output.read_text(encoding="utf-8") if output.exists() else ("\n\n".join(messages) or raw_output[-12000:])
        diagnostic = (answer + raw_output).lower()
        sandbox_start_failed = (
            "helper_unknown_error" in diagnostic
            and "setup refresh had errors" in diagnostic
        )
        if sandbox_start_failed:
            status = "Falha no sandbox"
        elif process.returncode != 0:
            status = "Falhou"
        else:
            status = "Concluído"
        STATE.jobs[job] = {
            **STATE.jobs.get(job, {}), "done": True, "status": status,
            "output": answer or raw_output[-4000:],
        }
    except Exception as exc: STATE.jobs[job] = {**STATE.jobs.get(job, {}), "done": True, "status": "Erro", "output": str(exc)}


def start_server(
    pause_callback=None,
    command_callback=None,
    theme_callback=None,
    group_bridge=None,
    control_callback=None,
    control_status_callback=None,
    show_callback=None,
    tools_provider=None,
) -> ThreadingHTTPServer:
    STATE.pause_callback = pause_callback
    STATE.command_callback = command_callback
    STATE.theme_callback = theme_callback
    STATE.group_bridge = group_bridge
    STATE.control_callback = control_callback
    STATE.control_status_callback = control_status_callback
    STATE.show_callback = show_callback
    STATE.tools_provider = tools_provider
    # O app tenta a LAN como rota de recuperação quando o hub/Tailscale oscila.
    # Toda a API continua protegida por PIN/token e a regra do Firewall limita
    # esta porta à rede doméstica.
    try:
        server = ServidorExclusivo(("0.0.0.0", PORTA), Handler)
    except OSError as erro:
        raise OSError(
            f"A porta {PORTA} já está em uso por outro processo. O painel da Nebula "
            "precisa dela sozinho; um segundo servidor na mesma porta faz o navegador "
            "cair no serviço errado. Verifique com "
            f"'Get-NetTCPConnection -LocalPort {PORTA} -State Listen'."
        ) from erro
    global _SERVINDO_PAINEL
    _SERVINDO_PAINEL = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def get_pin() -> str: return STATE.pin
