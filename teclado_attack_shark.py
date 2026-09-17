"""Iluminacao dinamica do Attack Shark X98HE pelo canal HID de configuracao.

O protocolo usa uma colecao HID separada (usage page ``0xFFFF``, usage 2),
portanto este modulo nao recebe teclas digitadas. Somente o dispositivo 2964,
identificado pelo proprio teclado, e aceito. A descricao publica do protocolo
esta em https://github.com/dniminenn/sharkfin/blob/master/docs/PROTOCOL.md.
"""

from __future__ import annotations

import threading
import time
from typing import Any

try:
    import hid as _hid
except ImportError:
    _hid = None


VENDOR_ID = 0x3151
PRODUCT_IDS = (0x5029, 0x5030)
USAGE_PAGE_CONFIG = 0xFFFF
USAGE_CONFIG = 2
DEVICE_ID_X98HE = 2964
REPORT_SIZE = 64

OP_IDENTIFY = 0x8F
OP_GET_LED = 0x87
OP_SET_LED = 0x07
MODE_STATIC = 1

CORES_PRESET_X98HE = (
    (255, 0, 0),      # 0: vermelho
    (0, 255, 0),      # 1: verde
    (0, 0, 255),      # 2: azul
    (255, 255, 0),    # 3: amarelo
    (160, 0, 255),    # 4: roxo
    (0, 220, 255),    # 5: azul-ciano
    (100, 190, 255),  # 6: azul-claro
)

_DEFAULT_HID_BACKEND = object()


class AttackSharkError(RuntimeError):
    """Falha ao acessar ou controlar a iluminacao do teclado."""


class AttackSharkNotFoundError(AttackSharkError):
    """O X98HE compativel nao esta conectado por USB."""


class AttackSharkProtocolError(AttackSharkError):
    """O teclado respondeu fora do protocolo esperado."""


def _checksum(pacote: bytearray, ate: int) -> None:
    pacote[ate] = (0xFF - sum(pacote[:ate])) & 0xFF


class AttackSharkX98HE:
    """Controla a cor em tempo real e restaura o perfil ao fechar."""

    def __init__(self, hid_backend: Any = _DEFAULT_HID_BACKEND) -> None:
        backend = _hid if hid_backend is _DEFAULT_HID_BACKEND else hid_backend
        if backend is None:
            raise AttackSharkError("O suporte HID do teclado nao esta instalado.")
        candidatos = []
        for product_id in PRODUCT_IDS:
            candidatos.extend(backend.enumerate(VENDOR_ID, product_id))
        entrada = next(
            (
                item
                for item in candidatos
                if item.get("usage_page") == USAGE_PAGE_CONFIG
                and item.get("usage") == USAGE_CONFIG
            ),
            None,
        )
        if entrada is None:
            raise AttackSharkNotFoundError(
                "Nao encontrei o Attack Shark X98HE conectado por cabo USB."
            )
        self._lock = threading.RLock()
        self._device = backend.device()
        self._aberto = False
        self._original: bytes | None = None
        self._ultimo_nivel: int | None = None
        try:
            self._device.open_path(entrada["path"])
            self._aberto = True
            resposta = self._consultar(OP_IDENTIFY)
            identificador = int.from_bytes(resposta[1:5], "little")
            if identificador != DEVICE_ID_X98HE:
                raise AttackSharkProtocolError(
                    f"O teclado conectado se identificou como {identificador}, nao X98HE."
                )
            self._original = self._consultar(OP_GET_LED)
            if len(self._original) < 8 or self._original[0] != OP_GET_LED:
                raise AttackSharkProtocolError("Nao consegui ler o perfil RGB atual.")
            self._cor_base = self._resolver_cor_original(self._original)
            self._indice_cor = self._preset_mais_proximo(self._cor_base)
        except Exception:
            self._fechar_handle()
            raise

    @property
    def is_open(self) -> bool:
        return self._aberto

    @staticmethod
    def _resolver_cor_original(resposta: bytes) -> tuple[int, int, int]:
        modo, flags = resposta[1], resposta[4]
        indice = flags & 0x0F
        if modo not in (13, 22, 23) and indice < len(CORES_PRESET_X98HE):
            return CORES_PRESET_X98HE[indice]
        cor = tuple(resposta[5:8])
        return (255, 255, 255) if cor == (250, 250, 250) else cor  # type: ignore[return-value]

    @staticmethod
    def _preset_mais_proximo(cor: tuple[int, int, int]) -> int:
        return min(
            range(len(CORES_PRESET_X98HE)),
            key=lambda indice: sum(
                (canal - referencia) ** 2
                for canal, referencia in zip(cor, CORES_PRESET_X98HE[indice])
            ),
        )

    def definir_cor_base(self, cor: tuple[int, int, int]) -> None:
        if (
            not isinstance(cor, tuple)
            or len(cor) != 3
            or not all(isinstance(canal, int) and 0 <= canal <= 255 for canal in cor)
        ):
            raise ValueError("A cor base do teclado precisa ser um RGB valido.")
        with self._lock:
            self._cor_base = cor
            self._indice_cor = self._preset_mais_proximo(cor)
            self._ultimo_nivel = None

    def _enviar(self, pacote: bytearray) -> None:
        if not self._aberto:
            raise AttackSharkError("O canal RGB do teclado esta fechado.")
        enviados = self._device.send_feature_report(bytes([0]) + bytes(pacote))
        if enviados != REPORT_SIZE + 1:
            raise AttackSharkProtocolError(
                f"O teclado aceitou apenas {enviados} de {REPORT_SIZE + 1} bytes."
            )

    def _consultar(self, opcode: int) -> bytes:
        pacote = bytearray(REPORT_SIZE)
        pacote[0] = opcode
        _checksum(pacote, 7)
        self._enviar(pacote)
        time.sleep(0.012)
        resposta = bytes(self._device.get_feature_report(0, REPORT_SIZE + 1))
        if resposta and resposta[0] == 0:
            resposta = resposta[1:]
        if not resposta or resposta[0] != opcode:
            raise AttackSharkProtocolError(
                f"O teclado nao confirmou a consulta 0x{opcode:02X}."
            )
        return resposta

    @staticmethod
    def _limitar_brilho(brilho: int) -> int:
        if isinstance(brilho, bool) or not isinstance(brilho, int) or not 1 <= brilho <= 100:
            raise ValueError("O brilho do teclado precisa ficar entre 1 e 100.")
        return brilho

    def set_boost(self, brilho: int) -> None:
        brilho = self._limitar_brilho(brilho)
        nivel = max(1, min(4, (brilho + 24) // 25))
        with self._lock:
            if nivel == self._ultimo_nivel:
                return
            pacote = bytearray(REPORT_SIZE)
            pacote[:8] = bytes(
                [OP_SET_LED, MODE_STATIC, 1, nivel, self._indice_cor, 255, 255, 255]
            )
            _checksum(pacote, 8)
            self._enviar(pacote)
            self._ultimo_nivel = nivel

    def restaurar(self) -> None:
        with self._lock:
            if not self._aberto or self._original is None or self._ultimo_nivel is None:
                return
            pacote = bytearray(REPORT_SIZE)
            pacote[:8] = bytes([OP_SET_LED]) + self._original[1:8]
            _checksum(pacote, 8)
            self._enviar(pacote)
            self._ultimo_nivel = None

    def _fechar_handle(self) -> None:
        if self._aberto:
            try:
                self._device.close()
            finally:
                self._aberto = False

    def close(self) -> None:
        with self._lock:
            if not self._aberto:
                return
            try:
                self.restaurar()
            finally:
                self._fechar_handle()

    def __enter__(self) -> "AttackSharkX98HE":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = [
    "AttackSharkError",
    "AttackSharkNotFoundError",
    "AttackSharkProtocolError",
    "AttackSharkX98HE",
]
