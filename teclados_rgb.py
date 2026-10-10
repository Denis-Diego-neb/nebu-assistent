"""Os teclados RGB conectados como uma saída só: Kumara e Attack Shark.

Os modos da Nebula falam com um teclado; o grupo repassa cada comando a todos
os que abriram. O Attack Shark não tem zonas: no Ambilight multizona ele recebe
a média das zonas. Quem não tem efeitos do firmware fica na cor escolhida. Se um
teclado para de responder, sai do grupo e os outros continuam.
"""

from __future__ import annotations

from collections.abc import Callable
import threading

from teclado_attack_shark import AttackSharkError
from teclado_openrgb import OpenRGBKeyboardError

ERROS_TECLADO = (AttackSharkError, OpenRGBKeyboardError, OSError)


class TecladoIndisponivel(OpenRGBKeyboardError, AttackSharkError):
    """Nenhum teclado respondeu; os modos já tratam os dois tipos de erro."""


def _nome(teclado: object) -> str:
    return str(getattr(teclado, "nome", "Kumara"))


def _fechar_quieto(teclado: object) -> str | None:
    try:
        teclado.close()  # type: ignore[attr-defined]
    except ERROS_TECLADO as exc:
        return str(exc)
    return None


class TecladosRGB:
    """Repassa cada comando de iluminação a todos os teclados do grupo."""

    def __init__(self, teclados: list[object]) -> None:
        if not teclados:
            raise ValueError("O grupo precisa de ao menos um teclado.")
        self._teclados = list(teclados)
        self._lock = threading.RLock()
        self.erros: list[str] = []

    @property
    def nomes(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(_nome(teclado) for teclado in self._teclados)

    @property
    def nome(self) -> str:
        return " e ".join(self.nomes)

    @property
    def ambilight_multizona_seguro(self) -> bool:
        with self._lock:
            return any(
                bool(getattr(teclado, "ambilight_multizona_seguro", False))
                for teclado in self._teclados
            )

    def _repassar(self, acao: Callable[[object], None]) -> None:
        with self._lock:
            if not self._teclados:
                raise TecladoIndisponivel("Nenhum teclado RGB continua conectado.")
            falhas: list[tuple[object, Exception]] = []
            for teclado in self._teclados:
                try:
                    acao(teclado)
                except ERROS_TECLADO as exc:
                    falhas.append((teclado, exc))
            for teclado, exc in falhas:
                self._teclados.remove(teclado)
                self.erros.append(f"{_nome(teclado)}: {exc}")
                _fechar_quieto(teclado)
            if not self._teclados:
                raise TecladoIndisponivel(str(falhas[-1][1])) from falhas[-1][1]

    def enviar_rgb(self, vermelho: int, verde: int, azul: int) -> None:
        self._repassar(lambda teclado: teclado.enviar_rgb(vermelho, verde, azul))

    def enviar_zonas(self, cores) -> None:
        cores = tuple(tuple(cor) for cor in cores)
        if not cores:
            raise ValueError("Informe ao menos uma cor RGB.")
        media = tuple(round(sum(cor[canal] for cor in cores) / len(cores)) for canal in range(3))

        def enviar(teclado: object) -> None:
            if getattr(teclado, "ambilight_multizona_seguro", False):
                teclado.enviar_zonas(cores)  # type: ignore[attr-defined]
            else:
                teclado.enviar_rgb(*media)  # type: ignore[attr-defined]

        self._repassar(enviar)

    def definir_cor_base(self, cor: tuple[int, int, int]) -> None:
        self._repassar(lambda teclado: teclado.definir_cor_base(cor))

    def set_boost(self, brilho: int) -> None:
        self._repassar(lambda teclado: teclado.set_boost(brilho))

    def efeito_nativo(self, efeito: str, cor: tuple[int, int, int] = (0, 80, 255)) -> None:
        with self._lock:
            if not any(callable(getattr(teclado, "efeito_nativo", None)) for teclado in self._teclados):
                raise TecladoIndisponivel(
                    "Os efeitos do firmware precisam do Kumara por USB ou do Attack Shark."
                )

            def aplicar(teclado: object) -> None:
                nativo = getattr(teclado, "efeito_nativo", None)
                if callable(nativo):
                    nativo(efeito, cor)
                else:
                    teclado.enviar_rgb(*cor)  # type: ignore[attr-defined]

            self._repassar(aplicar)

    def restaurar(self) -> None:
        self._repassar(lambda teclado: teclado.restaurar())

    def close(self) -> None:
        """Fecha todos; cada teclado volta ao próprio perfil, mesmo se outro falhar."""
        with self._lock:
            teclados, self._teclados = self._teclados, []
            for teclado in teclados:
                erro = _fechar_quieto(teclado)
                if erro:
                    self.erros.append(f"{_nome(teclado)}: {erro}")


def abrir_teclados(
    fabrica_attack_shark: Callable[[], object],
    fabrica_kumara: Callable[..., object],
) -> TecladosRGB:
    """Abre todos os teclados RGB conectados; falha só se nenhum responder."""
    abertos: list[object] = []
    erros: list[str] = []
    attack_shark = None
    try:
        try:
            attack_shark = fabrica_attack_shark()
        except ERROS_TECLADO as exc:
            erros.append(str(exc))
        try:
            # Com o Attack Shark respondendo, não abre o OpenRGB só para procurar o Kumara.
            abertos.append(fabrica_kumara(iniciar_openrgb=attack_shark is None))
        except ERROS_TECLADO as exc:
            erros.append(str(exc))
    except BaseException:
        for teclado in (*abertos, attack_shark):
            if teclado is not None:
                _fechar_quieto(teclado)
        raise
    if attack_shark is not None:
        abertos.append(attack_shark)
    if not abertos:
        raise TecladoIndisponivel(" ".join(erros) or "Nenhum teclado RGB conectado.")
    return TecladosRGB(abertos)


__all__ = ["ERROS_TECLADO", "TecladoIndisponivel", "TecladosRGB", "abrir_teclados"]
