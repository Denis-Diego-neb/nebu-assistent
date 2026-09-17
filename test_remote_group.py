import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import remote_server
from grupo_chat import PonteGrupo
from memoria_nebula import MemoriaNebula


class RespostaQwen:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"message": {"content": "Oi do Qwen pelo grupo móvel"}}


class GrupoRemotoTests(unittest.TestCase):
    def test_api_do_grupo_envia_lista_avalia_e_limpa(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            memoria = MemoriaNebula(
                contexto_usuario=raiz / "contexto.md",
                correcoes_file=raiz / "correcoes.json",
                feedback_file=raiz / "feedback.json",
            )
            ponte = PonteGrupo(
                caminho_historico=raiz / "grupo.json",
                post_http=lambda *_args, **_kwargs: RespostaQwen(),
                executar_codex=lambda _prompt: "Resposta Codex",
            )
            servidor = ThreadingHTTPServer(("127.0.0.1", 0), remote_server.Handler)
            thread = threading.Thread(target=servidor.serve_forever, daemon=True)
            token = "teste-grupo-remoto"
            ponte_anterior = remote_server.STATE.group_bridge
            show_anterior = remote_server.STATE.show_callback
            mostrada = threading.Event()
            remote_server.STATE.group_bridge = ponte
            remote_server.STATE.show_callback = mostrada.set
            remote_server.STATE.sessions.add(token)
            thread.start()
            base = f"http://127.0.0.1:{servidor.server_port}"

            def chamar(caminho: str, dados: dict[str, object] | None = None):
                corpo = None if dados is None else json.dumps(dados).encode("utf-8")
                pedido = urllib.request.Request(
                    base + caminho,
                    data=corpo,
                    method="GET" if dados is None else "POST",
                    headers={
                        "X-Nebula-Token": token,
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(pedido, timeout=5) as resposta:
                    return json.loads(resposta.read().decode("utf-8"))

            try:
                with patch.object(remote_server, "MEMORIA", memoria):
                    enviado = chamar("/api/group", {"text": "Olá pelo celular", "mode": "codex"})
                    self.assertTrue(enviado["ok"])
                    self.assertTrue(ponte.aguardar(2))
                    grupo = chamar("/api/group")
                    self.assertEqual(
                        [mensagem["autor"] for mensagem in grupo["messages"]],
                        ["Você", "Codex"],
                    )
                    avaliado = chamar(
                        "/api/group/feedback",
                        {"author": "Codex", "rating": "positivo", "comment": "Ficou natural"},
                    )
                    self.assertIn("Codex", avaliado["message"])
                    self.assertEqual(memoria.listar_feedbacks()[0]["comentario"], "Ficou natural")
                    apagado = chamar("/api/group/clear", {})
                    self.assertTrue(apagado["ok"])
                    self.assertEqual(chamar("/api/group")["messages"], [])
                    exibida = chamar("/api/show", {})
                    self.assertTrue(exibida["ok"])
                    self.assertTrue(mostrada.wait(1))
            finally:
                servidor.shutdown()
                servidor.server_close()
                remote_server.STATE.sessions.discard(token)
                remote_server.STATE.group_bridge = ponte_anterior
                remote_server.STATE.show_callback = show_anterior


if __name__ == "__main__":
    unittest.main()
