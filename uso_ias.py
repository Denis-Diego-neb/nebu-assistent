"""Uso real das duas IAs da Dupla: janela de 5 horas e limite semanal.

Nada aqui é estimado. Cada número vem da fonte oficial do próprio provedor:

- **Claude**: o endpoint de uso da conta (``api/oauth/usage``), o mesmo que o
  ``/usage`` do Claude Code consulta, com a credencial que o Claude Code já
  guarda nesta máquina. O token **nunca é renovado** aqui: a renovação troca o
  token, e fazê-la por fora derrubaria a sessão do próprio Claude Code. Vencido,
  o painel só avisa.
- **Codex**: o último evento ``token_count`` dos logs de sessão do Codex, que
  trazem ``rate_limits`` com a janela primária (5 h) e a secundária (semanal).
  Ler o log não gasta cota; o número vale até a última vez que o Codex rodou.

Quando uma fonte não responde, o campo fica ``None`` com o motivo — nunca um
zero inventado. O token do Claude não sai deste processo: o celular recebe só
as porcentagens.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL_USO_CLAUDE = "https://api.anthropic.com/api/oauth/usage"
# O endpoint é consultado no máximo uma vez por minuto, por mais que o celular pergunte.
CACHE_CLAUDE_S = 60
ARQUIVOS_CODEX = 25

_cache = {"claude": None, "claude_em": 0.0}
_trava = threading.Lock()


def _iso(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def _janela(pct, reinicia_em) -> dict | None:
    if pct is None:
        return None
    return {"pct": round(float(pct), 1), "reinicia_em": reinicia_em}


def uso_claude(credenciais: Path | None = None, abrir=urllib.request.urlopen) -> dict:
    caminho = credenciais or Path.home() / ".claude" / ".credentials.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))["claudeAiOauth"]
    except (OSError, ValueError, KeyError, TypeError):
        return {"erro": "Credencial do Claude Code não encontrada neste PC."}
    plano = dados.get("subscriptionType")
    if float(dados.get("expiresAt", 0)) / 1000 <= time.time():
        return {"plano": plano, "erro": "Credencial do Claude Code vencida; ela se renova quando o Claude Code rodar."}
    pedido = urllib.request.Request(URL_USO_CLAUDE, headers={
        "Authorization": "Bearer " + str(dados.get("accessToken", "")),
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "User-Agent": "nebula-uso/1.0",
    })
    try:
        with abrir(pedido, timeout=15) as resposta:
            uso = json.loads(resposta.read())
    except urllib.error.HTTPError as exc:
        return {"plano": plano, "erro": f"A Anthropic respondeu {exc.code} ao consultar o uso."}
    except (OSError, ValueError) as exc:
        return {"plano": plano, "erro": f"Sem resposta da Anthropic: {exc.__class__.__name__}."}
    cinco = uso.get("five_hour") or {}
    semana = uso.get("seven_day") or {}
    return {
        "plano": plano,
        "janela_5h": _janela(cinco.get("utilization"), cinco.get("resets_at")),
        "semanal": _janela(semana.get("utilization"), semana.get("resets_at")),
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "fonte": "uso oficial da conta Claude",
    }


def _ultimo_limite_codex(pasta: Path) -> tuple[dict, str] | None:
    arquivos = sorted(pasta.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for arquivo in arquivos[:ARQUIVOS_CODEX]:
        try:
            linhas = arquivo.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for linha in reversed(linhas):
            if '"rate_limits"' not in linha:
                continue
            try:
                evento = json.loads(linha)
            except ValueError:
                continue
            limites = (evento.get("payload") or {}).get("rate_limits")
            if isinstance(limites, dict) and (limites.get("primary") or limites.get("secondary")):
                return limites, evento.get("timestamp") or _iso(arquivo.stat().st_mtime)
    return None


def uso_codex(pasta: Path | None = None) -> dict:
    sessoes = pasta or Path.home() / ".codex" / "sessions"
    achado = _ultimo_limite_codex(sessoes) if sessoes.is_dir() else None
    if achado is None:
        return {"erro": "O Codex ainda não registrou limites neste PC."}
    limites, quando = achado
    janelas = {}
    for chave in ("primary", "secondary"):
        j = limites.get(chave) or {}
        minutos = j.get("window_minutes")
        # O Codex chama as janelas de primária e secundária; é a duração que diz qual é qual.
        nome = "janela_5h" if minutos == 300 else "semanal" if minutos == 10080 else None
        if nome:
            janelas[nome] = _janela(j.get("used_percent"), _iso(j.get("resets_at")))
    creditos = limites.get("credits") or {}
    return {
        "plano": limites.get("plan_type"),
        "janela_5h": janelas.get("janela_5h"),
        "semanal": janelas.get("semanal"),
        "creditos": {"tem": bool(creditos.get("has_credits")), "saldo": creditos.get("balance")},
        "atualizado_em": quando,
        "fonte": "último registro de sessão do Codex",
    }


def modelo_codex(config: Path | None = None) -> dict:
    """Modelo e esforço que o Codex usa quando ninguém força outro.

    A Dupla chama o Codex sem --model, então vale o que está no config.toml —
    o mesmo que o seletor do VS Code grava. Trocar lá troca aqui.
    """
    caminho = config or Path.home() / ".codex" / "config.toml"
    forcado = os.environ.get("NEBULA_COLLAB_CODEX_MODEL", "").strip()
    try:
        import tomllib
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        dados = {}
    ident = forcado if forcado and forcado != "configured" else str(dados.get("model") or "")
    esforco = str(dados.get("model_reasoning_effort") or "")
    partes = ident.split("-")
    # gpt-6-sol -> Sol, gpt-6-astra -> Astra: o nome da parceira é o do modelo.
    nome = partes[-1].capitalize() if len(partes) >= 3 and partes[0] == "gpt" else "GPT"
    return {"id": ident or None, "esforco": esforco or None, "nome": nome,
            "texto": " ".join(p for p in (ident, esforco) if p) or None}


def tokens_da_dupla(estado: dict) -> dict:
    """Tokens que a própria Dupla mediu por agente, somando todos os pedidos."""
    total = {"opus": 0, "codex": 0}
    sem_medida = {"opus": 0, "codex": 0}
    for orcamento in (estado.get("budgets") or {}).values():
        for agente in total:
            dados = orcamento.get(agente) or {}
            total[agente] += int(dados.get("measured") or 0)
            sem_medida[agente] += int(dados.get("unknown_calls") or 0)
    return {"opus": total["opus"], "codex": total["codex"], "soma": total["opus"] + total["codex"],
            "chamadas_sem_medida": sem_medida}


def uso(estado: dict | None = None) -> dict:
    with _trava:
        if _cache["claude"] is None or time.monotonic() - _cache["claude_em"] >= CACHE_CLAUDE_S:
            _cache["claude"] = uso_claude()
            _cache["claude_em"] = time.monotonic()
        claude = _cache["claude"]
    codex = dict(uso_codex())
    codex["modelo"] = modelo_codex()
    return {"opus": claude, "codex": codex, "nomes": {"opus": "Claude", "codex": codex["modelo"]["nome"]},
            "dupla": tokens_da_dupla(estado or {}),
            "gerado_em": datetime.now(timezone.utc).isoformat()}


def resumo_para_agentes(dados: dict) -> str:
    """Uma linha para o prompt das IAs: cada uma sabe quanto resta dela e da outra."""
    partes = []
    for chave, nome in (("opus", "Claude"), ("codex", "Codex")):
        a = dados.get(chave) or {}
        if a.get("erro"):
            partes.append(f"{nome}: uso indisponível")
            continue
        j = a.get("janela_5h") or {}
        s = a.get("semanal") or {}
        partes.append(f"{nome}: 5 h {j.get('pct', '?')}%, semana {s.get('pct', '?')}%")
    return ("USO REAL DAS DUAS (fonte oficial de cada provedor): " + "; ".join(partes) +
            ". Quem estiver perto do limite deixa a parte maior para a outra.")
