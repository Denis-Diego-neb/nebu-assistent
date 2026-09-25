"""Ciclo de vida do job no notebook (secao 20 do GOAL).

Cada job tem no maximo uma transicao terminal: uma vez completed, failed ou
cancelled, nenhum outro caminho o reescreve.
"""

from __future__ import annotations

TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"validating"}),
    "validating": frozenset({"queued", "rejected"}),
    "queued": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"completed", "failed", "cancelled"}),
    "completed": frozenset({"expired"}),
    "failed": frozenset({"expired"}),
    "cancelled": frozenset({"expired"}),
    "rejected": frozenset({"expired"}),
    "expired": frozenset(),
}
FINISHED = frozenset({"completed", "failed", "cancelled", "rejected"})


class InvalidTransition(RuntimeError):
    pass


def check_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"Transicao invalida: {current} -> {target}")
