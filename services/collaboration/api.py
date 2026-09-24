"""Fachada HTTP sem servidor próprio; o host mantém sua autenticação."""

from .engine import Coordinator
from .providers import availability
from .store import CollaborationStore, Conflict
from .store import text
from .development import Development


class CollaborationAPI:
    def __init__(self, project_root, provider=None):
        self.store = CollaborationStore(project_root)
        self.coordinator = Coordinator(self.store, provider)
        self.development = Development(self.store, self.coordinator.provider)

    def handle(self, method, path, body=None):
        body = {} if body is None else body
        if not isinstance(body, dict):
            return 400, {"error": "Corpo deve ser um objeto JSON."}
        try:
            if method == "GET" and path == "/api/collaboration":
                state = self.store.snapshot()
                state["providers"] = availability()
                state["running"] = state["active_run"] is not None
                state["project_root"] = str(self.store.root)
                state["development_available"] = (self.store.root / ".git").exists()
                return 200, state
            if method == "GET" and path == "/api/collaboration/log":
                path = self.store.export_markdown()
                return 200, {"markdown": path.read_text(encoding="utf-8")}
            if method == "POST" and path == "/api/collaboration/ideas":
                return 201, self.store.create_idea(body.get("text"), body.get("token_budget", 60000))
            if method == "POST" and path == "/api/collaboration/run":
                return 202, self.coordinator.start(body.get("idea_id"))
            if method == "POST" and path == "/api/collaboration/pause":
                self.store.pause(body.get("paused"))
                return 200, {"ok": True, "paused": body["paused"]}
            if method == "POST" and path == "/api/collaboration/messages":
                # O corpo não pode simular a identidade de um agente.
                self.store.message(body.get("idea_id"), "user", body.get("text"), "user_message")
                return 201, {"ok": True}
            if method == "POST" and path == "/api/collaboration/chat":
                content = text(body.get("text"))
                idea_id = body.get("idea_id")
                if not idea_id:
                    idea_id = self.store.create_idea(content)["id"]
                return 202, self.coordinator.chat(idea_id, content)
            if method == "POST" and path == "/api/collaboration/develop":
                return 202, self.development.start(text(body.get("text")), body.get("idea_id"), body.get("token_budget", 60000))
            if method == "POST" and path == "/api/collaboration/stop":
                return 202, self.development.stop()
            return 404, {"error": "Rota de colaboração inexistente."}
        except Conflict as exc:
            return 409, {"error": str(exc)}
        except (ValueError, KeyError, TypeError) as exc:
            return 400, {"error": str(exc)}
