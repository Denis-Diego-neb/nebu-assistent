"""Ponte autenticada Nebula/extensao. Nunca escuta fora do loopback."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from integrations.gemini import GeminiBrowserReviewGate
from ai_sprints.review_contract import parse_gemini_review

MAX_BODY = 2 * 1024 * 1024
FIELDS = {'version', 'job_id', 'fingerprint', 'content_sha256', 'created_at', 'transport', 'prompt'}
# A 8765 e do painel da Nebula. No Windows os dois processos conseguem escutar a
# mesma porta e as conexoes se dividem entre eles, o que fazia o navegador abrir
# a ponte no lugar do Espaco. A ponte tem porta propria.
BRIDGE_PORT = int(os.environ.get('NEBULA_GEMINI_BRIDGE_PORT', '8767'))


def extension_id(value: str) -> str:
    """Aceita o ID puro ou uma URL chrome-extension:// copiada do Brave."""
    value = value.strip().strip('"\'')
    match = re.fullmatch(r'(?:chrome-extension://)?([a-p]{32})(?:/.*)?', value)
    if not match:
        raise argparse.ArgumentTypeError(
            'use o ID de 32 letras (a-p) exibido em brave://extensions; '
            'nao use o texto ID_DA_EXTENSAO nem as crases ```'
        )
    return match.group(1)


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root: Path, token: str, extension_id: str, port: int = BRIDGE_PORT):
        if not re.fullmatch(r'[a-p]{32}', extension_id):
            raise ValueError('ID da extensao invalido.')
        if len(token) < 32 or not token.isascii():
            raise ValueError('Token precisa ter ao menos 32 caracteres ASCII.')
        self.gate = GeminiBrowserReviewGate(root)
        self.token = token
        self.origin = 'chrome-extension://' + extension_id
        self.mutex = threading.Lock()
        super().__init__(('127.0.0.1', port), BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = 'NebulaGeminiBridge/0.2'

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, fmt, *args):
        # Nao registra URLs, prompts, tokens ou respostas.
        pass

    def reply(self, status, value=None):
        raw = b'' if value is None else json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        if self.headers.get('Origin') == self.server.origin:
            self.send_header('Access-Control-Allow-Origin', self.server.origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def allowed(self, authenticate=True):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            self.reply(403, {'error': 'Host bloqueado.'})
            return False
        if self.headers.get('Origin') not in (None, self.server.origin):
            self.reply(403, {'error': 'Origem bloqueada.'})
            return False
        if authenticate and not hmac.compare_digest(
            self.headers.get('Authorization', '').encode(), ('Bearer ' + self.server.token).encode()
        ):
            self.reply(401, {'error': 'Configure o token da ponte na extensao.'})
            return False
        return True

    def do_OPTIONS(self):
        if not self.allowed(False):
            return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', self.server.origin)
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if not self.allowed(self.path != '/health'):
            return
        if self.path == '/health':
            return self.reply(200, {'ok': True, 'service': 'nebula-gemini-bridge', 'version': 2})
        if self.path != '/gemini/next':
            return self.reply(404, {'error': 'Endpoint inexistente.'})
        gate = self.server.gate
        with self.server.mutex:
            gate.outbox.mkdir(parents=True, exist_ok=True)
            for path in sorted(gate.outbox.glob('*.json')):
                try:
                    if path.stat().st_size > MAX_BODY:
                        continue
                    job = json.loads(path.read_text(encoding='utf-8'))
                    if not isinstance(job, dict) or set(job) != FIELDS:
                        continue
                    gate.request_path(job['job_id'])
                    if job['job_id'] != path.stem or type(job['version']) is not int or job['version'] != 1:
                        continue
                    if job['transport'] != 'gemini_web_browser':
                        continue
                    if any(not isinstance(job[k], str) or not job[k].strip()
                           for k in ('fingerprint', 'content_sha256', 'created_at', 'prompt')):
                        continue
                    if not re.fullmatch('[0-9a-f]{64}', job['content_sha256']):
                        continue
                    gate._assert_safe_for_browser(job['prompt'])
                    if gate.result_path(job['job_id']).exists():
                        continue
                    return self.reply(200, job)
                except (ValueError, TypeError, OSError):
                    continue
        self.reply(204)

    def do_POST(self):
        if not self.allowed():
            return
        if self.path != '/gemini/result':
            return self.reply(404, {'error': 'Endpoint inexistente.'})
        if self.headers.get('Transfer-Encoding'):
            return self.reply(400, {'error': 'Transfer-Encoding nao suportado.'})
        if self.headers.get_content_type() != 'application/json':
            return self.reply(415, {'error': 'Use application/json.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY:
                return self.reply(413, {'error': 'Tamanho de resposta invalido.'})
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            if not isinstance(body, dict) or set(body) != {'job_id', 'fingerprint', 'content_sha256', 'response'}:
                raise ValueError('Payload invalido.')
            if any(not isinstance(body[k], str) or not body[k] for k in ('job_id', 'fingerprint', 'content_sha256')):
                raise ValueError('Identidade do job invalida.')
            self.server.gate.request_path(body['job_id'])
            review = parse_gemini_review(body['response'])
            with self.server.mutex:
                try:
                    self.server.gate.record(body['job_id'], review,
                        expected_fingerprint=body['fingerprint'],
                        expected_content_sha256=body['content_sha256'])
                except ValueError as exc:
                    return self.reply(409, {'error': str(exc)})
            self.reply(200, {'ok': True, 'job_id': body['job_id']})
        except FileNotFoundError:
            self.reply(404, {'error': 'Job nao existe.'})
        except (ValueError, TypeError, KeyError, UnicodeError):
            self.reply(400, {'error': 'JSON ou contrato de review invalido; confira rewards e evidencias.'})
        except OSError:
            self.reply(500, {'error': 'Falha local ao registrar resultado.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--extension-id', required=True, type=extension_id,
        help='ID de 32 letras exibido no cartao da extensao em brave://extensions',
    )
    args = parser.parse_args()
    token = os.environ.get('NEBULA_GEMINI_BRIDGE_TOKEN') or secrets.token_urlsafe(32)
    server = BridgeServer(PROJECT_ROOT, token, args.extension_id)
    print(f'Nebula Gemini Bridge: http://127.0.0.1:{BRIDGE_PORT}', flush=True)
    print('Cole este token no popup da extensao: ' + token, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
