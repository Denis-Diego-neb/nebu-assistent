"""Vocabulário do painel Dupla; a persistência continua no mesmo serviço."""

from functools import lru_cache
from pathlib import Path

from .api import CollaborationAPI
from .providers import availability
from .store import Conflict

ALIASES = {"codex": "astra", "opus": "claude", "user": "usuario", "system": "sistema"}
STATES = {"queued": "proposto", "running": "em_execucao", "completed": "concluido",
          "failed": "bloqueado", "interrupted": "bloqueado"}


@lru_cache(maxsize=8)
def get_api(project_root=None):
    return CollaborationAPI(Path(project_root) if project_root else Path(__file__).resolve().parents[2])


def _idea(api, idea_id=None):
    ideas = api.store.snapshot()["ideas"]
    if not ideas:
        raise ValueError("Defina uma ideia primeiro.")
    return api.store.find(ideas, idea_id) if idea_id else ideas[-1]


def snapshot(project_root=None):
    api = get_api(project_root)
    state = api.store.snapshot()
    idea = state["ideas"][-1] if state["ideas"] else None
    front = [{"id": str(m["seq"]), "autor": "usuario", "tipo": "mensagem",
              "texto": m["data"].get("text", ""), "em": m["at"]}
             for m in state["messages"] if m["actor"] == "user" and m["kind"] in {"idea", "user_message"}]
    front += [{"id": f"{c['idea_id']}-{c['agent']}", "autor": ALIASES[c["agent"]],
               "tipo": "confirmacao", "texto": c["text"], "em": c["at"],
               "origem": c["session_id"], "modelo": c["model"]} for c in state["confirmations"]]
    front.sort(key=lambda m: m["em"])
    backstage = [{"id": str(m["seq"]), "autor": ALIASES.get(m["actor"], m["actor"]),
                  "texto": m["data"].get("text") or str(m["data"]), "em": m["at"]}
                 for m in state["messages"] if m["kind"] not in {"idea", "user_message", "confirmation"}]
    agents = {}
    for actor in ("codex", "opus"):
        budgets = [b[actor] for b in state["budgets"].values()]
        tasks = [t for t in state["tasks"] if t["owner"] == actor]
        measured = sum(b["measured"] for b in budgets)
        reported = any(m["kind"] == "tokens_used" and m["actor"] == actor
                       and m["data"].get("measured") is not None for m in state["messages"])
        agents[ALIASES[actor]] = {"tokens": measured if measured or reported else None,
            "tokens_estimados": sum(b["estimated"] for b in budgets),
            "reservados": sum(b["reserved"] for b in budgets),
            "limite": sum(b["limit"] for b in budgets),
            "itens": sum(t["status"] == "completed" for t in tasks),
            "em_execucao": next((t["id"] for t in tasks if t["status"] == "running"), None),
            "visto_em": next((m["at"] for m in reversed(state["messages"]) if m["actor"] == actor), None)}
    items = [{"id": t["id"], "titulo": t["title"], "detalhe": t["reason"],
              "impacto": t["impact"], "confianca": round(t["confidence"] * 5, 1),
              "custo": max(1, min(5, round(t["estimated_tokens"] / 2000))),
              "prioridade": t["priority"], "arquivos": t["paths"], "depende_de": t["dependencies"],
              "dono": ALIASES[t["owner"]], "estado": STATES[t["status"]],
              "resumo": t.get("summary", ""), "tokens_reais": None,
              "criado_por": ALIASES[t["owner"]], "criado_em": t["created_at"],
              "atualizado_em": t.get("finished_at", t.get("started_at", t["created_at"]))}
             for t in state["tasks"]]
    return {"objetivo": idea["text"] if idea else "", "idea_id": idea["id"] if idea else None,
            "atualizado_em": state["messages"][-1]["at"] if state["messages"] else None,
            "agentes": agents, "itens": items, "frente": front, "bastidores": backstage,
            "pausado": state["paused"], "executando": state["active_run"] is not None,
            "providers": availability(), "estado": idea["status"] if idea else "empty",
            "diario": {"caminho": str(api.store.log_path),
                       "secoes": sum(m["kind"] == "code_section" for m in state["messages"]),
                       "ultima": backstage[-1]["texto"] if backstage else ""}}


def definir_objetivo(texto, project_root=None, token_budget=60000):
    api = get_api(project_root)
    return api.store.create_idea(texto, token_budget)


def mensagem_usuario(texto, project_root=None):
    api = get_api(project_root)
    idea = _idea(api)
    api.store.message(idea["id"], "user", texto, "user_message")
    return {"ok": True, "idea_id": idea["id"]}


def propor(titulo, detalhe, impacto, confianca, custo, arquivos=(), depende_de=(),
           criado_por="usuario", project_root=None):
    api = get_api(project_root)
    idea = _idea(api)
    if criado_por != "usuario":
        raise ValueError("Propostas pela interface devem ser atribuídas ao usuário.")
    if any(type(n) is not int or not 1 <= n <= 5 for n in (impacto, confianca, custo)):
        raise ValueError("Impacto, confiança e custo devem ser de 1 a 5.")
    state = api.store.snapshot()
    budgets = state["budgets"][idea["id"]]
    owner = min(budgets, key=lambda a: budgets[a]["measured"] + budgets[a]["estimated"])
    return api.store.add_task(idea["id"], "user", title=titulo, reason=detalhe, owner=owner,
                             paths=list(arquivos), dependencies=list(depende_de), impact=impacto,
                             confidence=confianca / 5, estimated_tokens=custo * 2000)


def executar(idea_id=None, project_root=None):
    api = get_api(project_root)
    return api.coordinator.start(_idea(api, idea_id)["id"])


def pausar(paused, project_root=None):
    api = get_api(project_root)
    api.store.pause(paused)
    return {"ok": True, "paused": paused}
