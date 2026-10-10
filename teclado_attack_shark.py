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

# Efeito do firmware mais parecido com cada efeito do Kumara, pela tabela de luz
# do X98HE no sharkfin: modo, opcao (direcao), arco-iris e velocidade de 0
# (lenta) a 4 (rapida).
EFEITOS_X98HE = {
    "onda": (4, 0, True, 2),                 # Wave para a direita
    "onda_curta": (4, 0, True, 4),           # Wave rapida
    "ciclo": (3, 0, True, 2),                # Spectrum cycle
    "respirar": (2, 0, False, 2),            # Breathing
    "reativo": (8, 0, False, 2),             # Key shadow: a tecla acende ao apertar
    "ripple": (5, 0, False, 2),              # Ripple
    "linha": (7, 0, False, 2),               # Flow em zigue-zague
    "estrelas": (6, 0, False, 2),            # Star dots
    "florescer": (11, 0, False, 2),          # Spring, de dentro para fora
    "arco_iris_vertical": (4, 2, True, 2),   # Wave para baixo
    "furacao": (14, 0, True, 2),             # Radiant: arco-iris girando
    "acumular": (9, 0, False, 2),            # Layers: as teclas vao ficando acesas
    "visor": (10, 0, False, 2),              # Sine wave: pontos correndo pela fileira
    "arco_iris_circular": (11, 0, True, 2),  # Spring em arco-iris
}
# O driver do fabricante manda 7 para o arco-iris neste teclado (8 e a cor do
# pacote). Se o firmware ler ao contrario, o efeito sai na cor escolhida.
FLAG_ARCO_IRIS = 7
BRILHO_EFEITOS = 4

# Ambilight: troca de cor pronta so quando a nova fica bem mais perto da cena, e
# de nivel so quando o brilho passa da divisa com folga, para o teclado nao
# piscar entre duas cores vizinhas. Em cena quase preta a matiz e ruido.
FOLGA_COR = 0.7
FOLGA_NIVEL = 5
BRILHO_MINIMO_MATIZ = 32

_DEFAULT_HID_BACKEND = object()
# Um efeito por vez: cada objeto restaura, ao fechar, o perfil que leu ao abrir.
_DONO = threading.Lock()


class AttackSharkError(RuntimeError):
    """Falha ao acessar ou controlar a iluminacao do teclado."""


class AttackSharkNotFoundError(AttackSharkError):
    """O X98HE compativel nao esta conectado por USB."""


class AttackSharkProtocolError(AttackSharkError):
    """O teclado respondeu fora do protocolo esperado."""


def _checksum(pacote: bytearray, ate: int) -> None:
    pacote[ate] = (0xFF - sum(pacote[:ate])) & 0xFF


def _validar_cor(cor: object, mensagem: str) -> tuple[int, int, int]:
    try:
        canais = tuple(cor)  # type: ignore[call-overload]
    except TypeError:
        raise ValueError(mensagem) from None
    if len(canais) != 3 or not all(
        isinstance(canal, int) and not isinstance(canal, bool) and 0 <= canal <= 255
        for canal in canais
    ):
        raise ValueError(mensagem)
    return canais  # type: ignore[return-value]


def _matiz(cor: tuple[int, int, int]) -> tuple[int, int, int]:
    """A mesma cor no brilho maximo: uma cena escura e azulada continua azul."""
    maior = max(cor)
    return tuple(round(canal * 255 / maior) for canal in cor)  # type: ignore[return-value]


def _distancia(cor: tuple[int, int, int], indice: int) -> int:
    return sum((canal - preset) ** 2 for canal, preset in zip(cor, CORES_PRESET_X98HE[indice]))


def _nivel_brilho(brilho: int) -> int:
    return max(1, min(4, (brilho + 24) // 25))


def _nivel_com_folga(brilho: int, atual: int) -> int:
    novo = _nivel_brilho(brilho)
    if novo > atual and brilho < 25 * atual + 1 + FOLGA_NIVEL:
        return atual
    if novo < atual and brilho > 25 * (atual - 1) - FOLGA_NIVEL:
        return atual
    return novo


def _rgb_no_fio(cor: tuple[int, int, int]) -> tuple[int, int, int]:
    """Abaixo de 8 o firmware apaga tudo; o branco puro viaja como FAFAFA."""
    if max(cor) < 8:
        return (8, 8, 8)
    return (250, 250, 250) if cor == (255, 255, 255) else cor


class AttackSharkX98HE:
    """Controla a cor em tempo real e restaura o perfil ao fechar."""

    nome = "Attack Shark"
    # Sem zonas: o Ambilight multizona manda a media das zonas para enviar_rgb.
    ambilight_multizona_seguro = False

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
        if not _DONO.acquire(blocking=False):
            raise AttackSharkError("O Attack Shark ja esta em uso por outro efeito da Nebula.")
        self._dono = True
        self._lock = threading.RLock()
        self._aberto = False
        self._original: bytes | None = None
        # Campos 1..7 do ultimo SET_LED enviado; None enquanto vale o perfil original.
        self._aplicado: bytes | None = None
        try:
            self._device = backend.device()
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
        except BaseException:
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
        return min(range(len(CORES_PRESET_X98HE)), key=lambda indice: _distancia(cor, indice))

    def definir_cor_base(self, cor: tuple[int, int, int]) -> None:
        if not isinstance(cor, tuple):
            raise ValueError("A cor base do teclado precisa ser um RGB valido.")
        cor = _validar_cor(cor, "A cor base do teclado precisa ser um RGB valido.")
        with self._lock:
            self._cor_base = cor
            self._indice_cor = self._preset_mais_proximo(cor)

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

    def _aplicar(
        self,
        modo: int,
        velocidade: int,
        brilho: int,
        flags: int,
        rgb: tuple[int, int, int] = (255, 255, 255),
    ) -> None:
        """Envia SET_LED so quando muda algo: o X98HE guarda a iluminacao na flash."""
        campos = bytes((modo, velocidade, brilho, flags, *rgb))
        with self._lock:
            if campos == self._aplicado:
                return
            pacote = bytearray(REPORT_SIZE)
            pacote[0] = OP_SET_LED
            pacote[1:8] = campos
            _checksum(pacote, 8)
            self._enviar(pacote)
            self._aplicado = campos

    def _estatico_aplicado(self) -> tuple[int, int] | None:
        """(cor pronta, nivel) do quadro estatico em exibicao, se houver um."""
        campos = self._aplicado
        if campos is None or campos[0] != MODE_STATIC or campos[3] >= len(CORES_PRESET_X98HE):
            return None
        return campos[3], campos[2]

    @staticmethod
    def _limitar_brilho(brilho: int) -> int:
        if isinstance(brilho, bool) or not isinstance(brilho, int) or not 1 <= brilho <= 100:
            raise ValueError("O brilho do teclado precisa ficar entre 1 e 100.")
        return brilho

    def set_boost(self, brilho: int) -> None:
        nivel = _nivel_brilho(self._limitar_brilho(brilho))
        with self._lock:
            self._aplicar(MODE_STATIC, 1, nivel, self._indice_cor)

    def enviar_rgb(self, vermelho: int, verde: int, azul: int) -> None:
        """Ambilight no X98HE: a cor pronta mais próxima e o brilho pela luminância.

        O firmware só aceita as sete cores prontas e quatro níveis de brilho.
        Quadros que não mudam a cor pronta nem o nível não vão ao teclado, e as
        folgas evitam que ele alterne entre duas cores ou dois níveis vizinhos.
        A cor base do Boost não muda: um flash de escapamento volta para ela.
        """
        cor = _validar_cor((vermelho, verde, azul), "A cor do teclado precisa ser um RGB valido.")
        maior = max(cor)
        with self._lock:
            atual = self._estatico_aplicado()
            indice = atual[0] if atual is not None else self._indice_cor
            if maior and (atual is None or maior >= BRILHO_MINIMO_MATIZ):
                alvo = _matiz(cor)
                melhor = self._preset_mais_proximo(alvo)
                if atual is None or (
                    melhor != indice
                    and _distancia(alvo, melhor) < FOLGA_COR * _distancia(alvo, indice)
                ):
                    indice = melhor
            brilho = max(1, round(maior * 100 / 255))
            nivel = _nivel_brilho(brilho) if atual is None else _nivel_com_folga(brilho, atual[1])
            self._aplicar(MODE_STATIC, 1, nivel, indice)

    @classmethod
    def efeitos_nativos(cls) -> tuple[str, ...]:
        """Efeitos do Kumara que o firmware do X98HE também executa."""
        return tuple(EFEITOS_X98HE)

    def efeito_nativo(self, efeito: str, cor: tuple[int, int, int] = (0, 80, 255)) -> None:
        """Deixa a animação com o firmware: um único comando, sem quadros contínuos."""
        if efeito not in EFEITOS_X98HE:
            raise ValueError(f"Efeito nativo do teclado invalido: {efeito}")
        cor = _validar_cor(cor, "A cor do teclado precisa ser um RGB valido.")
        modo, opcao, arco_iris, velocidade = EFEITOS_X98HE[efeito]
        with self._lock:
            if arco_iris:
                flags, rgb = FLAG_ARCO_IRIS, _rgb_no_fio(cor)
            else:
                indice = self._preset_mais_proximo(_matiz(cor)) if max(cor) else self._indice_cor
                flags, rgb = indice, (255, 255, 255)
            self._aplicar(modo, 4 - velocidade, BRILHO_EFEITOS, (opcao << 4) | flags, rgb)

    def restaurar(self) -> None:
        with self._lock:
            if not self._aberto or self._original is None or self._aplicado is None:
                return
            pacote = bytearray(REPORT_SIZE)
            pacote[:8] = bytes([OP_SET_LED]) + self._original[1:8]
            _checksum(pacote, 8)
            self._enviar(pacote)
            self._aplicado = None

    def _fechar_handle(self) -> None:
        try:
            if self._aberto:
                self._device.close()
        finally:
            self._aberto = False
            if self._dono:
                self._dono = False
                _DONO.release()

    def close(self) -> None:
        with self._lock:
            if not self._dono:
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
    "EFEITOS_X98HE",
    "AttackSharkError",
    "AttackSharkNotFoundError",
    "AttackSharkProtocolError",
    "AttackSharkX98HE",
]
