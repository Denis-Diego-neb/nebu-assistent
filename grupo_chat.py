"""Ponte persistente para um chat em grupo entre o usuário, Qwen e Codex."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import requests

from config_modelo import obter_url_ollama, qwen_ativa
from memoria_nebula import (
    MEMORIA,
    interpretar_comando_contexto,
    interpretar_comando_correcao,
)

CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
HISTORICO_PADRAO = CONFIG_DIR / "grupo_chat.json"
PASTA_CODEX = CONFIG_DIR / "grupo_codex"
MAX_MENSAGENS = 200
MAX_TEXTO = 8_000

PROMPT_QWEN = """Você é Qwen e participa de um grupo privado chamado Nebula.
Os participantes são o usuário, Qwen e Codex. Responda em português brasileiro,
de forma natural, inteligente e concisa. Você pode conversar diretamente com o
usuário ou comentar ideias do Codex. Você é somente uma participante do chat:
não afirme que executou comandos, alterou arquivos ou controlou dispositivos."""

PROMPT_CODEX = """Você é Codex e participa de um grupo privado com o usuário e
Qwen. Esta é uma conversa geral, não uma solicitação para alterar o computador.
Não use ferramentas, não execute comandos e não edite arquivos. Responda em
português brasileiro, naturalmente e de forma concisa. Considere a fala mais
recente da Qwen e acrescente algo útil, evitando apenas repetir o que ela disse."""


class GrupoOcupadoError(RuntimeError):
    """Indica que uma rodada anterior ainda está sendo processada."""


def localizar_codex() -> str | None:
    configurado = os.environ.get("NEBULA_CODEX_PATH", "").strip()
    if configurado and Path(configurado).is_file():
        return configurado
    encontrado = shutil.which("codex")
    if encontrado:
        return encontrado
    extensoes = Path.home() / ".vscode" / "extensions"
    candidatos = sorted(
        extensoes.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
        reverse=True,
    )
    return str(candidatos[0]) if candidatos else None


def ambiente_filho() -> dict[str, str]:
    ambiente = os.environ.copy()
    for chave in list(ambiente):
        if chave.startswith("_PYI") or chave in {"TCL_LIBRARY", "TK_LIBRARY"}:
            ambiente.pop(chave, None)
    return ambiente


def extrair_resposta_codex(saida: str) -> str:
    respostas: list[str] = []
    for linha in saida.splitlines():
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        item = evento.get("item") if isinstance(evento, dict) else None
        if (
            isinstance(item, dict)
            and evento.get("type") == "item.completed"
            and item.get("type") == "agent_message"
        ):
            texto = str(item.get("text", "")).strip()
            if texto:
                respostas.append(texto)
    return respostas[-1] if respostas else ""


class PonteGrupo:
    """Coordena uma rodada sequencial: usuário, Qwen e depois Codex."""

    def __init__(
        self,
        ao_evento: Callable[[str, object], None] | None = None,
        caminho_historico: Path | None = None,
        post_http: Callable[..., Any] | None = None,
        executar_codex: Callable[[str], str] | None = None,
    ) -> None:
        self.url_ollama = obter_url_ollama()
        self.modelo_qwen = os.environ.get("NEBULA_OLLAMA_MODEL", "qwen3:8b")
        self.caminho_historico = caminho_historico or HISTORICO_PADRAO
        self._post_http = post_http or requests.post
        self._executor_codex = executar_codex or self._consultar_codex_cli
        self._ao_evento = ao_evento
        self._lock = threading.RLock()
        self._ocupado = False
        self._thread: threading.Thread | None = None
        self._mensagens = self._carregar()

    @property
    def ocupado(self) -> bool:
        with self._lock:
            return self._ocupado

    def historico(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(mensagem) for mensagem in self._mensagens]

    def enviar(self, texto: str, participantes: Iterable[str] = ("qwen", "codex")) -> None:
        texto = texto.strip()
        if not texto:
            raise ValueError("Escreva uma mensagem para o grupo.")
        if len(texto) > MAX_TEXTO:
            raise ValueError(f"A mensagem deve ter no máximo {MAX_TEXTO} caracteres.")
        selecionados = tuple(
            participante for participante in participantes
            if participante in {"qwen", "codex"}
            and (participante != "qwen" or qwen_ativa())
        )
        if not selecionados:
            if "qwen" in participantes and not qwen_ativa():
                raise ValueError("A Qwen está desativada para poupar o notebook.")
            raise ValueError("Escolha Qwen ou Codex.")
        correcao = interpretar_comando_correcao(texto)
        contexto = interpretar_comando_contexto(texto)
        if correcao or contexto:
            self._adicionar("Você", texto)
            if correcao:
                ouvido, correto = MEMORIA.registrar_correcao(*correcao)
                self._adicionar(
                    "Sistema",
                    f'Correção compartilhada: "{ouvido}" agora será entendido como "{correto}".',
                )
            else:
                assert contexto is not None
                MEMORIA.adicionar_contexto(contexto)
                self._adicionar("Sistema", "Novo contexto compartilhado com Qwen e Codex.")
            return
        with self._lock:
            if self._ocupado:
                raise GrupoOcupadoError("A rodada anterior ainda está em andamento.")
            self._ocupado = True
        self._adicionar("Você", texto)
        self._emitir("ocupado", True)
        self._thread = threading.Thread(
            target=self._processar_rodada,
            args=(selecionados,),
            daemon=True,
            name="NebulaGrupo",
        )
        self._thread.start()

    def aguardar(self, timeout: float | None = None) -> bool:
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def limpar(self) -> None:
        with self._lock:
            if self._ocupado:
                raise GrupoOcupadoError("Espere a rodada terminar antes de limpar o grupo.")
            self._mensagens.clear()
            self._salvar_locked()
        self._emitir("limpo", True)

    def _processar_rodada(self, participantes: tuple[str, ...]) -> None:
        try:
            if "qwen" in participantes:
                self._emitir("status", f"Qwen ({self.modelo_qwen}) está digitando…")
                try:
                    self._adicionar("Qwen", self._consultar_qwen())
                except Exception as exc:
                    self._adicionar("Sistema", f"Qwen indisponível: {self._erro_curto(exc)}")
            if "codex" in participantes:
                self._emitir("status", "Codex está lendo o grupo e digitando…")
                try:
                    contexto = self._montar_contexto(PROMPT_CODEX)
                    self._adicionar("Codex", self._executor_codex(contexto))
                except Exception as exc:
                    self._adicionar("Sistema", f"Codex indisponível: {self._erro_curto(exc)}")
        finally:
            with self._lock:
                self._ocupado = False
            self._emitir("status", "Grupo pronto.")
            self._emitir("ocupado", False)

    def _consultar_qwen(self) -> str:
        resposta = self._post_http(
            f"{self.url_ollama}/api/chat",
            json={
                "model": self.modelo_qwen,
                "messages": [
                    {"role": "system", "content": PROMPT_QWEN},
                    {"role": "user", "content": self._montar_contexto("")},
                ],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.7, "num_predict": 260},
                "keep_alive": "30m",
            },
            timeout=(5, 300),
        )
        resposta.raise_for_status()
        texto = str(resposta.json().get("message", {}).get("content", "")).strip()
        if not texto:
            raise RuntimeError("o modelo não retornou texto")
        return texto

    def _consultar_codex_cli(self, prompt: str) -> str:
        codex = localizar_codex()
        if not codex:
            raise RuntimeError("executável do Codex não encontrado")
        PASTA_CODEX.mkdir(parents=True, exist_ok=True)
        comando = [
            codex,
            "-a", "never",
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox", "read-only",
            "-C", str(PASTA_CODEX),
            "--json",
            prompt,
        ]
        kwargs: dict[str, object] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        processo = subprocess.run(
            comando,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            env=ambiente_filho(),
            **kwargs,
        )
        texto = extrair_resposta_codex(processo.stdout)
        if processo.returncode != 0 or not texto:
            detalhe = (processo.stderr or processo.stdout or "sem detalhes").strip()
            raise RuntimeError(detalhe[-1_000:])
        return texto

    def _montar_contexto(self, instrucao: str) -> str:
        with self._lock:
            mensagens = [dict(mensagem) for mensagem in self._mensagens[-30:]]
        linhas = []
        for mensagem in mensagens:
            autor = str(mensagem.get("autor", "Participante"))
            texto = str(mensagem.get("texto", "")).strip()
            if texto:
                linhas.append(f"[{autor}] {texto[:2_000]}")
        transcricao = "\n".join(linhas)
        if len(transcricao) > 18_000:
            transcricao = transcricao[-18_000:]
        prefixo = f"{instrucao}\n\n" if instrucao else ""
        memoria = MEMORIA.para_prompt()
        bloco_memoria = (
            f"MEMÓRIA COMPARTILHADA DA NEBULA:\n{memoria}\n\n"
            if memoria else ""
        )
        return (
            f"{prefixo}{bloco_memoria}Histórico recente do grupo, em ordem cronológica:\n"
            f"{transcricao}\n\nResponda agora como você mesma, sem prefixar seu nome."
        )

    def _adicionar(self, autor: str, texto: str) -> None:
        mensagem: dict[str, object] = {
            "autor": autor,
            "texto": texto.strip(),
            "criado_em": time.time(),
        }
        with self._lock:
            self._mensagens.append(mensagem)
            del self._mensagens[:-MAX_MENSAGENS]
            self._salvar_locked()
        self._emitir("mensagem", dict(mensagem))

    def _carregar(self) -> list[dict[str, object]]:
        try:
            dados = json.loads(self.caminho_historico.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(dados, list):
            return []
        mensagens = []
        for item in dados[-MAX_MENSAGENS:]:
            if isinstance(item, dict) and item.get("autor") and item.get("texto"):
                mensagens.append(dict(item))
        return mensagens

    def _salvar_locked(self) -> None:
        self.caminho_historico.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho_historico.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._mensagens[-MAX_MENSAGENS:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(self.caminho_historico)

    def _emitir(self, tipo: str, valor: object) -> None:
        if self._ao_evento:
            self._ao_evento(tipo, valor)

    @staticmethod
    def _erro_curto(exc: Exception) -> str:
        texto = " ".join(str(exc).split())
        return texto[-500:] or exc.__class__.__name__
