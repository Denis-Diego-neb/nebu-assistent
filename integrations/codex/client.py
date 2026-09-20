"""Encaminhamento à conversa Codex existente, sem depender do transporte HTTP."""

from typing import Callable


class CodexClient:
    def __init__(self, enviar: Callable[[str], None] | None = None, ao_responder=None):
        self._enviar = enviar
        self._ao_responder = ao_responder
        self._ponte = None

    def encaminhar(self, mensagem: str) -> dict:
        if self._enviar is not None:
            self._enviar(mensagem)
        else:
            # CLI/voz sem GUI: respostas aparecem na saída da própria Nebula.
            from grupo_chat import PonteGrupo

            if self._ponte is None:
                def evento(tipo, valor):
                    if tipo == "mensagem" and valor.get("autor") in {"Codex", "Sistema"}:
                        if self._ao_responder:
                            self._ao_responder(str(valor.get("texto", "")))
                self._ponte = PonteGrupo(ao_evento=evento)
            self._ponte.enviar(mensagem, participantes=("codex",))
        return {"ok": True, "message": "Pedido encaminhado à conversa com Codex.",
                "destination": "codex", "status": "queued"}
