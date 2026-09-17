"""Timer persistente do notebook; somente o hub dispara o desligamento IR."""
import json
import math
from pathlib import Path
import threading
import time


class AirTimer:
    def __init__(self, air, path, clock=time.time):
        self.air, self.path, self.clock = air, Path(path), clock
        self.lock = threading.RLock()
        self.data = {'deadline': None, 'status': 'idle', 'error': None}
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            deadline = saved.get('deadline') if isinstance(saved, dict) else None
            valid_deadline = deadline is None or (type(deadline) in (int, float) and math.isfinite(deadline) and deadline >= 0)
            if isinstance(saved, dict) and valid_deadline and (saved.get('status') != 'armed' or deadline is not None) and saved.get('status') in {'armed', 'sending', 'sent', 'failed', 'idle'}:
                self.data.update(saved)
        except (OSError, ValueError):
            pass
        # Uma interrupcao durante o envio tem resultado desconhecido: nao repetir.
        if self.data['status'] == 'sending':
            self.data.update(status='failed', error='O hub reiniciou durante o envio. Confira o ar.')

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data), encoding='utf-8')
        tmp.replace(self.path)

    def status(self):
        with self.lock:
            result = dict(self.data)
            result['remaining_minutes'] = max(0, math.ceil(((result.get('deadline') or self.clock())-self.clock())/60)) if result['status'] == 'armed' else 0
            return result

    def set(self, minutes):
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0 or minutes > 1440 or minutes % 30:
            raise ValueError('Escolha de 30 minutos a 24 horas, em passos de 30; zero cancela.')
        with self.lock:
            self.data.update(deadline=self.clock()+minutes*60 if minutes else None,
                             status='armed' if minutes else 'idle', error=None)
            self.save()
            return {'ok': True, 'message': f'Ar sera desligado em {minutes} minutos. Mantenha o notebook ligado.' if minutes else 'Timer cancelado.', 'timer': self.status()}

    def tick(self):
        with self.lock:
            if self.data['status'] != 'armed' or self.clock() < self.data['deadline']:
                return
            self.data['status'] = 'sending'
            self.save()
            try:
                self.air.executar('power', False)
                self.data.update(status='sent', error=None)
            except Exception:
                self.data.update(status='failed', error='Nao foi possivel confirmar o desligamento pelo Ekaza. Confira o ar.')
            self.save()

    def start(self):
        def worker():
            while True:
                time.sleep(1)
                try:
                    self.tick()
                except OSError:
                    # Persistencia indisponivel: nao executar sem registrar.
                    pass
        threading.Thread(target=worker, daemon=True, name='AirOffTimer').start()
