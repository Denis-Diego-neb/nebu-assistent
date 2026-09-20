"""Servidor de execução genérico: sem Qwen, SSH ou lógica de dispositivos."""

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.dispatcher import Dispatcher


class ToolServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, dispatcher: Dispatcher, token: str):
        if len(token) < 24:
            raise ValueError("Configure um token do servidor com pelo menos 24 caracteres.")
        self.dispatcher = dispatcher
        self.token = token
        super().__init__(address, ToolHandler)


class ToolHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("X-Nebula-Token", "")
        if not supplied:
            authorization = self.headers.get("Authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
        expected = self.server.token
        if not secrets.compare_digest(supplied.encode(), expected.encode()):
            self.respond(401, {"error": "Não autorizado."})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/api/tools":
            self.respond(200, {"tools": self.server.dispatcher.list_tools()})
        else:
            self.respond(404, {"error": "Rota inexistente."})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/api/tools/call":
            self.respond(404, {"error": "Rota inexistente."})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 100_000:
                raise ValueError("Corpo ausente ou grande demais.")
            self.connection.settimeout(10)
            call = json.loads(self.rfile.read(size).decode("utf-8"))
            result = self.server.dispatcher.call_tool(call)
        except (ValueError, UnicodeError) as exc:
            self.respond(400, {"error": str(exc)})
            return
        except OSError:
            self.respond(408, {"error": "Tempo de leitura excedido."})
            return
        self.respond(200, result)
