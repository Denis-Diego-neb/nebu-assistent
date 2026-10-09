"""Pasta de rascunho por job (INV-008): criada no inicio, apagada no fim.

O nome da pasta e o proprio job_id, que o protocolo ja restringe a um ULID;
mesmo assim todo caminho e resolvido e conferido contra a raiz, para que um
nome estranho nunca alcance outra pasta.
"""

from __future__ import annotations

import shutil
from pathlib import Path, PurePath

from nebula_worker.protocol.ids import is_ulid


class Workspaces:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _job_dir(self, job_id: str) -> Path:
        if not is_ulid(job_id):
            raise ValueError("job_id invalido para pasta de rascunho.")
        path = (self.root / job_id).resolve()
        if path.parent != self.root:
            raise ValueError("Pasta de rascunho fora da raiz.")
        return path

    def create(self, job_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._job_dir(job_id)
        path.mkdir(exist_ok=False)
        return path

    def resolve(self, job_id: str, relative: str) -> Path:
        """Caminho dentro da pasta do job; absoluto ou com ``..`` e recusado."""
        pure = PurePath(relative)
        if not relative or pure.is_absolute() or pure.drive or ".." in pure.parts:
            raise ValueError("Caminho de rascunho invalido.")
        base = self._job_dir(job_id)
        target = (base / pure).resolve()
        if target != base and base not in target.parents:
            raise ValueError("Caminho de rascunho fora da pasta do job.")
        return target

    def cleanup(self, job_id: str) -> None:
        try:
            path = self._job_dir(job_id)
        except ValueError:
            return
        shutil.rmtree(path, ignore_errors=True)

    def sweep(self) -> int:
        """Apaga rascunhos deixados por uma execucao anterior interrompida."""
        if not self.root.is_dir():
            return 0
        removed = 0
        for entry in self.root.iterdir():
            if entry.is_dir() and is_ulid(entry.name):
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        return removed
