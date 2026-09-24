"""Desenvolvimento real no workspace: implementação e revisão em sessões próprias."""
import json
import threading

from .store import AGENTS, Conflict


class Development:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.cancel = threading.Event()
        self.thread = None

    def start(self, content, idea_id=None, token_budget=60000):
        if not (self.store.root / ".git").exists():
            raise ValueError("Selecione a raiz de um projeto Git em Projetos antes de desenvolver.")
        idea_id, chat_id = self.store.begin_development(content, idea_id, token_budget)
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(content, idea_id, chat_id),
                                       name="nebula-development", daemon=True)
        try:
            self.thread.start()
        except Exception:
            self.store.end_chat(chat_id)
            raise
        return {"ok": True, "idea_id": idea_id, "chat_id": chat_id, "mode": "development"}

    def stop(self):
        if not self.thread or not self.thread.is_alive():
            raise Conflict("Nenhuma rodada de desenvolvimento em execução nesta instância.")
        self.cancel.set()
        return {"ok": True, "message": "Interrupção solicitada; aguardando o processo encerrar."}

    def run(self, content, idea_id, chat_id):
        try:
            for actor in AGENTS:
                if self.cancel.is_set() or self.store.snapshot()["paused"]:
                    self.store.message(idea_id, "system", "Rodada interrompida antes do próximo agente.", "chat_error")
                    break
                ticket = None
                try:
                    state = self.store.snapshot()
                    history = [{"author": m["actor"], "text": m["data"].get("text", "")}
                               for m in state["messages"] if m["idea"] == idea_id
                               and m["kind"] in {"user_message", "chat_reply", "chat_error"}][-12:]
                    role = ("Implemente o pedido e rode os testes apropriados." if actor == "codex" else
                            "Revise o trabalho do primeiro agente no disco, rode os testes apropriados e corrija pendências. "
                            "Se ele falhou, assuma a implementação. Não repita mudanças já concluídas.")
                    prompt = (
                        f"Você é {actor} numa sessão de desenvolvimento da Dupla Nebula. "
                        f"O usuário autorizou trabalhar no projeto {self.store.root}. "
                        "Você tem ferramentas reais: leia arquivos, edite o código e execute comandos e testes "
                        "necessários para atender ao pedido. Trabalhe apenas neste projeto. "
                        "Leia as instruções AGENTS.md/CLAUDE.md aplicáveis. Preserve alterações existentes e "
                        "não reverta trabalho alheio. Não altere .nebula-collaboration, credenciais ou configurações "
                        "de permissões. Não publique nem envie mensagens externas sem pedido explícito. "
                        "Uma pergunta pede resposta; um pedido de alteração pede implementação. "
                        "Não crie tarefas extras. Comunique progresso curto e termine com alterações, testes "
                        "realmente executados e limitações, em português. Nunca alegue uma ação não executada. "
                        + role + "\nHistórico compartilhado:\n" + json.dumps(history, ensure_ascii=False)
                        + "\nPedido atual do usuário:\n" + content
                    )
                    ticket = self.store.reserve_tokens(idea_id, actor, max(6000, len(prompt) // 3 + 2000))
                    self.store.message(idea_id, actor, "Implementando no projeto…" if actor == "codex" else
                                       "Revisando e testando o projeto…", "agent_update")
                    def activity(kind, data):
                        if kind == "session":
                            self.store.development_session(idea_id, actor, data)
                        elif kind == "process":
                            self.store.development_process(chat_id, json.loads(data))
                        else:
                            self.store.message(idea_id, actor, data, kind)
                    reply = self.provider.develop(actor, prompt, self.store.root,
                        session_id=self.store.development_session(idea_id, actor),
                        on_event=activity, cancel=self.cancel)
                    self.store.settle_tokens(ticket, reply.tokens)
                    ticket = None
                    self.store.development_session(idea_id, actor, reply.session_id)
                    self.store.chat_reply(idea_id, actor, reply)
                except Exception as exc:
                    if ticket:
                        self.store.settle_tokens(ticket, None)
                    self.store.message(idea_id, "system", f"{actor}: {str(exc)[:1500]}", "chat_error")
                finally:
                    self.store.development_process(chat_id, None)
        finally:
            self.store.end_chat(chat_id)
