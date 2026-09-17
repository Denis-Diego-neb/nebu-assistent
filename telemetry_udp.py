"""Distribui cada datagrama para RPM e boost sem disputar a porta do jogo."""
import queue
import socket
import threading

_lock = threading.RLock()
_hubs = {}


class _Hub:
    def __init__(self, address):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.socket.bind(address)
            self.socket.settimeout(.1)
        except Exception:
            self.socket.close()
            raise
        self.address = self.socket.getsockname()
        self.clients = set()
        self.closed = False

    def run(self):
        while not self.closed:
            try:
                item = self.socket.recvfrom(4097)
            except socket.timeout:
                continue
            except OSError as exc:
                if self.closed:
                    return
                item = exc
            with _lock:
                for client in tuple(self.clients):
                    try:
                        client.pending.put_nowait(item)
                    except queue.Full:
                        try:
                            client.pending.get_nowait()
                        except queue.Empty:
                            pass
                        client.pending.put_nowait(item)
            if isinstance(item, OSError):
                return


class TelemetrySubscription:
    def __init__(self, hub):
        self.hub = hub
        self.pending = queue.Queue(maxsize=256)
        self.closed = False

    def getsockname(self):
        return self.hub.address

    def has_pending(self):
        return not self.pending.empty()

    def recvfrom(self, size):
        if self.closed:
            raise OSError('Assinatura de telemetria encerrada.')
        try:
            item = self.pending.get(timeout=.1)
        except queue.Empty:
            raise socket.timeout() from None
        if isinstance(item, OSError):
            raise item
        data, origin = item
        return data[:size], origin

    def close(self):
        with _lock:
            if self.closed:
                return
            self.closed = True
            hub = self.hub
            hub.clients.discard(self)
            if not hub.clients:
                hub.closed = True
                hub.socket.close()
                _hubs.pop(hub.address, None)


def subscribe(host, port):
    with _lock:
        hub = _hubs.get((host, port)) if port else None
        fresh = hub is None
        if fresh:
            hub = _Hub((host, port))
            _hubs[hub.address] = hub
        client = TelemetrySubscription(hub)
        hub.clients.add(client)
        if fresh:
            threading.Thread(target=hub.run, daemon=True, name='Nebula-Telemetry-UDP').start()
        return client
