"""Iluminacao USB do Kumara 320F:5000.

Formato EVision baseado no driver do OpenRGB:
https://github.com/CalcProgrammer1/OpenRGB/tree/master/Controllers/EVisionKeyboardController

Somente a colecao HID de iluminacao FF1C e acessada.
"""

from __future__ import annotations

import threading
import time

from teclado_openrgb import OpenRGBKeyboardError


class ErroKumaraUSB(OpenRGBKeyboardError):
    pass


# Coordenadas do mapa EVision.
# Os indices representam o buffer de 6 x 21 LEDs.
MATRIX = (
    (0, None, 1, 2, 3, 4, None, 5, 6, 7, 8, None, 9, 10, 11, 12, 14, 15, 16, None, None, None, None),
    (21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, None, 32, 33, 34, None, 35, 36, 37, 38, 39, 40, 41),
    (42, None, 43, 44, 45, 46, None, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62),
    (63, None, 64, 65, 66, 67, None, 68, 69, 70, 71, 72, 73, 74, 76, None, None, None, None, 80, 81, 82, None),
    (84, None, 86, 87, 88, 89, None, 90, None, 91, 92, 93, 94, 95, 97, None, None, 99, None, 101, 102, 103, 104),
    (105, 106, 107, None, None, None, None, 108, None, None, None, None, 109, 110, 111, 113, 119, 120, 121, 123, None, 124, None),
)


def colunas_kumara():
    columns = {
        led: x
        for row in MATRIX
        for x, led in enumerate(row)
        if led is not None
    }

    for led in range(126):
        if led not in columns:
            row = led // 21
            neighbors = [i for i in columns if i // 21 == row]

            nearest = min(
                neighbors,
                key=lambda i: (abs(i - led), i),
            )

            columns[led] = columns[nearest]

    return columns


def encontrar_kumara():
    try:
        import hid
    except ImportError:
        return None

    return next(
        (
            d
            for d in hid.enumerate(0x320F, 0x5000)
            if d.get("interface_number") == 1
            and d.get("usage_page") == 0xFF1C
            and d.get("usage") == 0x92
        ),
        None,
    )


def pacote_evision(command, payload=b"", offset=0):
    if (
        command not in (0x06, 0x11)
        or len(payload) > 54
        or not 0 <= offset <= 378
    ):
        raise ValueError("Pacote de iluminacao invalido.")

    packet = bytearray(64)

    packet[0] = 4
    packet[3] = command
    packet[4] = len(payload)
    packet[5:7] = offset.to_bytes(2, "little")
    packet[8:8 + len(payload)] = payload

    # O protocolo soma bytes com sinal.
    checksum = sum(
        x if x < 128 else x - 256
        for x in packet[3:]
    ) & 0xFFFF

    packet[1:3] = checksum.to_bytes(2, "little")

    return bytes(packet)


_OWNER = threading.Lock()


# Modos implementados diretamente pelo firmware do teclado.
#
# A vantagem desses modos é que a Nebula só envia o comando uma vez.
# Depois disso, a animacao é executada pelo proprio teclado.
NATIVE_EFFECTS = {
    "onda_curta": 0x01,
    "onda": 0x02,
    "wrgb_wave": 0x02,

    "ciclo": 0x04,
    "respirar": 0x05,

    "reativo": 0x07,
    "ripple": 0x08,
    "linha": 0x09,

    "estrelas": 0x0A,
    "florescer": 0x0B,

    "arco_iris_vertical": 0x0C,
    "furacao": 0x0D,
    "acumular": 0x0E,

    "visor": 0x10,
    "arco_iris_circular": 0x12,
}


# Nomes alternativos que podem ser usados pela interface ou comandos de voz.
EFFECT_ALIASES = {
    "wave": "onda",
    "wrgb": "wrgb_wave",
    "wrgb wave": "wrgb_wave",

    "breathing": "respirar",
    "breath": "respirar",

    "reactive": "reativo",

    "rainbow": "arco_iris_circular",
    "rainbow vertical": "arco_iris_vertical",

    "hurricane": "furacao",
}


class TecladoKumaraUSB:
    # O firmware aplica frames Custom em blocos; a troca nao e atomica e pode
    # aparecer como uma piscada durante atualizacoes continuas.
    ambilight_multizona_seguro = False

    name = "Kumara USB"

    # Antes estava limitado a 5 FPS.
    #
    # 12 FPS é um ponto inicial mais interessante para Ambilight,
    # principalmente agora que somente blocos modificados são enviados.
    CUSTOM_FPS = 12
    CUSTOM_INTERVAL = 1 / CUSTOM_FPS

    BLOCK_SIZE = 54
    LED_COUNT = 126
    FRAME_SIZE = LED_COUNT * 3

    def __init__(self, info, *, device=None):
        if not _OWNER.acquire(blocking=False):
            raise ErroKumaraUSB(
                "O Kumara ja esta em uso por outro efeito da Nebula."
            )

        self._lock = threading.RLock()
        self._closed = False

        self._base_color = (0, 80, 255)
        self._columns = colunas_kumara()

        self._last_frame: bytes | None = None
        self._last_send = 0.0

        self._custom_ready = False
        self._static_ready = False

        self._last_color = None
        self._native_effect = None

        self._device = device

        try:
            if device is None:
                import hid

                self._device = hid.device()
                self._device.open_path(info["path"])

        except Exception as exc:
            if self._device is not None:
                self._device.close()

            _OWNER.release()

            raise ErroKumaraUSB(
                "Nao consegui abrir a iluminacao USB do Kumara."
            ) from exc

    @staticmethod
    def _rgb(color):
        if (
            len(color) != 3
            or any(
                type(v) is not int or not 0 <= v <= 255
                for v in color
            )
        ):
            raise ValueError(
                "A cor do teclado precisa ser um RGB valido."
            )

        return tuple(color)

    @staticmethod
    def _normalizar_efeito(effect: str) -> str:
        effect = str(effect).strip().lower()

        effect = EFFECT_ALIASES.get(effect, effect)

        effect = (
            effect
            .replace("-", "_")
            .replace(" ", "_")
        )

        return effect

    @classmethod
    def efeitos_nativos(cls) -> tuple[str, ...]:
        """Lista os efeitos que podem ser executados pelo firmware."""
        return tuple(NATIVE_EFFECTS)

    def _mode(
        self,
        mode,
        color=(0, 0, 0),
        *,
        brightness=4,
        speed=3,
        direction=0,
        random=False,
    ):
        # Este firmware não responde corretamente ao comando de modo.
        # Portanto usamos leitura com timeout curto.
        packet = pacote_evision(
            0x06,
            bytes(
                (
                    mode,
                    brightness,
                    speed,
                    direction,
                    int(random),
                    *color,
                )
            ),
        )

        try:
            if self._device.write(packet) != len(packet):
                raise ErroKumaraUSB(
                    "O Kumara recusou a troca de modo de iluminacao."
                )

            # Alguns firmwares não retornam resposta.
            # A leitura curta apenas limpa uma eventual resposta pendente.
            self._device.read(64, 30)

        except OSError as exc:
            raise ErroKumaraUSB(
                "O Kumara perdeu a conexao USB."
            ) from exc

    def _send_block(self, payload, offset):
        packet = pacote_evision(
            0x11,
            payload,
            offset,
        )

        self._send_confirmed(
            packet,
            f"bloco de LEDs {offset // self.BLOCK_SIZE + 1}",
        )

    def _send_confirmed(
        self,
        packet,
        description,
    ):
        for _attempt in range(2):

            if self._device.write(packet) != len(packet):
                raise ErroKumaraUSB(
                    "Envio USB incompleto ao Kumara."
                )

            deadline = time.monotonic() + 0.25

            while time.monotonic() < deadline:
                remaining = max(
                    1,
                    round(
                        (deadline - time.monotonic())
                        * 1000
                    ),
                )

                response = bytes(
                    self._device.read(
                        64,
                        remaining,
                    )
                )

                if response == packet:
                    return

                if not response:
                    break

        raise ErroKumaraUSB(
            f"O Kumara nao confirmou o {description}."
        )

    def _frame(self, colors):
        """
        Envia um quadro RGB completo.

        Diferentemente da implementacao antiga, somente blocos
        realmente alterados sao enviados depois do primeiro frame.

        Isso reduz bastante o trafego HID e evita regravar
        desnecessariamente LEDs que continuam com a mesma cor.
        """

        frame = bytes(
            channel
            for color in colors
            for channel in color
        )

        if len(frame) != self.FRAME_SIZE:
            raise ValueError(
                "O Kumara precisa de um quadro completo de 126 LEDs."
            )

        with self._lock:

            if self._closed:
                raise ErroKumaraUSB(
                    "O controle do Kumara foi fechado."
                )

            if (
                self._custom_ready
                and self._last_frame == frame
            ):
                return

            elapsed = (
                time.monotonic()
                - self._last_send
            )

            wait = (
                self.CUSTOM_INTERVAL
                - elapsed
            )

            if wait > 0:
                time.sleep(wait)

            try:
                primeiro_frame = not self._custom_ready

                if primeiro_frame:
                    self._static_ready = False
                    self._last_color = None
                    self._native_effect = None

                    # Modo Custom.
                    self._mode(20)

                    self._custom_ready = True

                anterior = self._last_frame

                for offset in range(
                    0,
                    len(frame),
                    self.BLOCK_SIZE,
                ):
                    bloco = frame[
                        offset:
                        offset + self.BLOCK_SIZE
                    ]

                    bloco_anterior = (
                        anterior[
                            offset:
                            offset + self.BLOCK_SIZE
                        ]
                        if anterior is not None
                        else None
                    )

                    # No primeiro frame envia tudo.
                    #
                    # Nos seguintes envia somente blocos modificados.
                    if (
                        primeiro_frame
                        or bloco != bloco_anterior
                    ):
                        self._send_block(
                            bloco,
                            offset,
                        )

            except (OSError, ErroKumaraUSB) as exc:
                self._custom_ready = False
                self._last_frame = None

                if isinstance(exc, OSError):
                    raise ErroKumaraUSB(
                        "O Kumara perdeu a conexao USB."
                    ) from exc

                raise

            self._last_frame = frame
            self._last_send = time.monotonic()

    def enviar_rgb(
        self,
        red,
        green,
        blue,
    ):
        """
        Cor unica para todo o teclado.

        Esse caminho nao usa o buffer Custom de 126 LEDs,
        evitando a piscada observada ao regravar o frame.
        """

        color = self._rgb(
            (red, green, blue)
        )

        with self._lock:

            if self._closed:
                raise ErroKumaraUSB(
                    "O controle do Kumara foi fechado."
                )

            if (
                self._static_ready
                and self._last_color == color
            ):
                return

            try:
                if not self._static_ready:
                    self._custom_ready = False
                    self._last_frame = None
                    self._native_effect = None

                    # Modo Static.
                    self._mode(
                        0x06,
                        color,
                    )

                    self._static_ready = True

                # Atualiza somente RGB.
                #
                # Não reenvia os 126 LEDs.
                self._send_confirmed(
                    pacote_evision(
                        0x06,
                        bytes(color),
                        5,
                    ),
                    "parametro de cor",
                )

            except (OSError, ErroKumaraUSB) as exc:
                self._static_ready = False
                self._last_color = None

                if isinstance(exc, OSError):
                    raise ErroKumaraUSB(
                        "O Kumara perdeu a conexao USB."
                    ) from exc

                raise

            self._last_color = color

    def efeito_nativo(
        self,
        effect,
        color=(0, 80, 255),
        *,
        speed=3,
        brightness=4,
        direction=0,
    ):
        """
        Ativa um efeito executado diretamente pelo firmware.

        Exemplos:

            teclado.efeito_nativo("wrgb_wave")
            teclado.efeito_nativo("respirar", (255, 0, 120))
            teclado.efeito_nativo("reativo")
        """

        effect = self._normalizar_efeito(
            effect
        )

        if effect not in NATIVE_EFFECTS:
            raise ValueError(
                f"Efeito nativo do teclado invalido: {effect}"
            )

        color = self._rgb(color)

        if not 0 <= speed <= 5:
            raise ValueError(
                "A velocidade precisa ficar entre 0 e 5."
            )

        if not 0 <= brightness <= 4:
            raise ValueError(
                "O brilho precisa ficar entre 0 e 4."
            )

        if direction not in (0, 1):
            raise ValueError(
                "A direcao precisa ser 0 ou 1."
            )

        with self._lock:

            if self._closed:
                raise ErroKumaraUSB(
                    "O controle do Kumara foi fechado."
                )

            self._custom_ready = False
            self._static_ready = False

            self._last_frame = None
            self._last_color = None

            self._mode(
                NATIVE_EFFECTS[effect],
                color,
                speed=speed,
                brightness=brightness,
                direction=direction,
            )

            self._native_effect = effect

    def enviar_ambilight(
        self,
        colors,
    ):
        """
        Versao de cor unica do Ambilight.

        Recebe tres cores e usa a media no teclado inteiro.
        Esse caminho e muito mais suave que escrever 126 LEDs.
        """

        if len(colors) != 3:
            raise ValueError(
                "Informe tres cores RGB validas."
            )

        colors = [
            self._rgb(color)
            for color in colors
        ]

        media = tuple(
            round(
                sum(c[i] for c in colors)
                / len(colors)
            )
            for i in range(3)
        )

        self.enviar_rgb(*media)

    def enviar_zonas(
        self,
        colors,
    ):
        """
        Ambilight multizona.

        Distribui as cores horizontalmente pelas colunas do teclado.
        """

        if (
            not colors
            or len(colors) > 23
        ):
            raise ValueError(
                "Informe entre uma e 23 cores RGB validas."
            )

        colors = [
            self._rgb(color)
            for color in colors
        ]

        quantidade = len(colors)

        frame = [
            colors[
                min(
                    quantidade - 1,
                    self._columns[i]
                    * quantidade
                    // 23,
                )
            ]
            for i in range(self.LED_COUNT)
        ]

        self._frame(frame)

    def definir_cor_base(
        self,
        color,
    ):
        self._base_color = self._rgb(
            color
        )

    def set_boost(
        self,
        percent,
    ):
        percent = max(
            0,
            min(
                100,
                int(percent),
            ),
        )

        columns_on = round(
            23
            * percent
            / 100
        )

        frame = [
            (
                self._base_color
                if self._columns[i] < columns_on
                else (0, 0, 0)
            )
            for i in range(self.LED_COUNT)
        ]

        self._frame(frame)

    def restaurar(self):
        """
        Volta para o modo Reactive do firmware.
        """

        with self._lock:

            if self._closed:
                return

            self._mode(
                NATIVE_EFFECTS["reativo"]
            )

            self._custom_ready = False
            self._static_ready = False

            self._last_color = None
            self._last_frame = None
            self._native_effect = "reativo"

    def close(self):
        with self._lock:

            if self._closed:
                return

            try:
                self.restaurar()

            finally:
                self._closed = True

                try:
                    self._device.close()

                finally:
                    _OWNER.release()

    def __enter__(self):
        return self

    def __exit__(
        self,
        *_args,
    ):
        self.close()
