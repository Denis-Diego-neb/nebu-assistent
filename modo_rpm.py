"""Sincroniza telemetria de jogos com a lightbar do DS4 e a lâmpada Tuya.

Pontes de jogos enviam telemetria somente para ``127.0.0.1`` por UDP. O modo
RPM aceita qualquer jogo/adaptador que implemente o protocolo Nebula v2. O
modo boost recebe a quantidade de boost do Rocket League e altera somente o
brilho da lâmpada. Saídas Wi-Fi são sempre cadenciadas em outra thread.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import select
from telemetry_udp import subscribe, TelemetrySubscription
import socket
import threading
import time
from typing import Callable

from lightbar_ds4 import DS4Lightbar, DS4LightbarError
from teclado_attack_shark import AttackSharkError, AttackSharkX98HE
from teclado_openrgb import OpenRGBKeyboardError, TecladoKumaraOpenRGB
from teclado_evision import TecladoKumaraUSB


TELEMETRY_HOST = "127.0.0.1"
TELEMETRY_PORT = 29876
TELEMETRY_VERSION = 1
PACKET_TIMEOUT = 0.75
LAMP_INTERVAL = 0.25
LAMP_CUT_INTERVAL = 0.12
LAMP_RETRY_INTERVAL = 1.0

COR_NEUTRA = (0, 0, 32)
COR_AMARELA = (255, 225, 96)
COR_LARANJA = (255, 72, 0)
COR_VERMELHA = (255, 0, 0)
COR_CORTE_ESCURO = (0, 0, 0)
COR_CORTE_BRILHO = COR_VERMELHA
COR_BOOST = (0, 80, 255)


class ErroModoRPM(RuntimeError):
    """Falha ao preparar ou executar o modo RPM."""


class ErroModoBoost(RuntimeError):
    """Falha ao preparar ou executar o modo boost."""


@dataclass(frozen=True)
class AmostraRPM:
    sequencia: int
    valida: bool
    rpm: float = 0.0
    minimo: float = 0.0
    redline: float = 0.0
    maximo: float = 0.0
    acelerador: float = 0.0
    marcha: int = 1
    trocando_marcha: bool = False
    drag: bool = False
    fonte: str = "desconhecida"
    velocidade_kmh: float | None = None
    turbo_bar: float | None = None
    pressao_oleo: float | None = None
    combustivel_percentual: float | None = None
    temperatura_agua: float | None = None
    mapa_motor: int | None = None
    temperatura_oleo: float | None = None


@dataclass(frozen=True)
class AmostraBoost:
    sequencia: int
    valida: bool
    boost: float = 0.0
    fonte: str = "rocket_league"


@dataclass(frozen=True)
class EstadoVisual:
    faixa: str
    cor: tuple[int, int, int]
    corte: bool = False
    percentual: float = 0.0


ESTADO_NEUTRO = EstadoVisual("neutro", COR_NEUTRA)


def _numero_finito(valor: object, nome: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"{nome} não é numérico.")
    numero = float(valor)
    if not math.isfinite(numero):
        raise ValueError(f"{nome} não é finito.")
    return numero


def _numero_opcional(
    objeto: dict[str, object],
    campo: str,
    minimo: float,
    maximo: float,
) -> float | None:
    valor = objeto.get(campo)
    if valor is None:
        return None
    numero = _numero_finito(valor, campo)
    if not minimo <= numero <= maximo:
        raise ValueError(f"{campo} fora da faixa segura.")
    return numero


def _carregar_pacote(dados: bytes) -> dict[str, object]:
    if not dados or len(dados) > 4096:
        raise ValueError("Tamanho de pacote inválido.")
    try:
        objeto = json.loads(dados.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Pacote de telemetria inválido.") from exc
    if not isinstance(objeto, dict):
        raise ValueError("Pacote de telemetria inválido.")
    return objeto


def _cabecalho_pacote(objeto: dict[str, object]) -> tuple[int, bool, str]:
    sequencia = objeto.get("seq")
    valida = objeto.get("valid")
    if isinstance(sequencia, bool) or not isinstance(sequencia, int):
        raise ValueError("Sequência de telemetria inválida.")
    if not 0 <= sequencia <= 0xFFFFFFFF or not isinstance(valida, bool):
        raise ValueError("Cabeçalho de telemetria inválido.")
    fonte = objeto.get("source", "desconhecida")
    if not isinstance(fonte, str) or not fonte or len(fonte) > 64:
        raise ValueError("Fonte de telemetria inválida.")
    return sequencia, valida, fonte


def interpretar_pacote(dados: bytes) -> AmostraRPM:
    """Valida RPM genérico v2 e, por compatibilidade, o antigo pacote v1."""
    objeto = _carregar_pacote(dados)
    versao = objeto.get("v")
    if versao not in (TELEMETRY_VERSION, 2):
        raise ValueError("Versão de telemetria incompatível.")
    if versao == 2 and objeto.get("metric") != "rpm":
        raise ValueError("Métrica de telemetria incompatível com o modo RPM.")
    sequencia, valida, fonte = _cabecalho_pacote(objeto)
    if not valida:
        return AmostraRPM(sequencia, False, fonte=fonte)

    rpm = _numero_finito(objeto.get("rpm"), "rpm")
    minimo = _numero_finito(objeto.get("min_rpm"), "min_rpm")
    redline = _numero_finito(objeto.get("redline_rpm"), "redline_rpm")
    maximo = _numero_finito(objeto.get("max_rpm"), "max_rpm")
    acelerador = _numero_finito(objeto.get("gas"), "gas")
    marcha = objeto.get("gear")
    trocando = objeto.get("shifting")
    drag = objeto.get("drag")
    if isinstance(marcha, bool) or not isinstance(marcha, int) or not 0 <= marcha <= 9:
        raise ValueError("Marcha de telemetria inválida.")
    if not isinstance(trocando, bool) or not isinstance(drag, bool):
        raise ValueError("Flags de telemetria inválidas.")
    if not (
        0.0 <= minimo < redline <= maximo <= 40000.0
        and 0.0 <= acelerador <= 1.0
        and 0.0 <= rpm <= maximo * 1.25 + 1000.0
    ):
        raise ValueError("Valores de telemetria fora da faixa segura.")
    velocidade_kmh = _numero_opcional(objeto, "speed_kmh", 0.0, 1000.0)
    turbo_bar = _numero_opcional(objeto, "turbo_bar", -5.0, 20.0)
    pressao_oleo = _numero_opcional(objeto, "oil_pressure", -1.0, 50.0)
    combustivel = _numero_opcional(objeto, "fuel_percent", 0.0, 100.0)
    temperatura_agua = _numero_opcional(objeto, "water_temp", -100.0, 300.0)
    temperatura_oleo = _numero_opcional(objeto, "oil_temp", -100.0, 300.0)
    mapa_motor = objeto.get("engine_map")
    if mapa_motor is not None and (
        isinstance(mapa_motor, bool)
        or not isinstance(mapa_motor, int)
        or not 0 <= mapa_motor <= 99
    ):
        raise ValueError("engine_map fora da faixa segura.")
    return AmostraRPM(
        sequencia,
        True,
        rpm,
        minimo,
        redline,
        maximo,
        acelerador,
        marcha,
        trocando,
        drag,
        fonte,
        velocidade_kmh,
        turbo_bar,
        pressao_oleo,
        combustivel,
        temperatura_agua,
        mapa_motor,
        temperatura_oleo,
    )


def interpretar_pacote_boost(dados: bytes) -> AmostraBoost:
    """Valida um datagrama de boost normalizado do protocolo Nebula v2."""
    objeto = _carregar_pacote(dados)
    if objeto.get("v") != 2 or objeto.get("metric") != "boost":
        raise ValueError("Pacote incompatível com o modo boost.")
    sequencia, valida, fonte = _cabecalho_pacote(objeto)
    if not valida:
        return AmostraBoost(sequencia, False, fonte=fonte)
    boost = _numero_finito(objeto.get("value"), "value")
    if not 0.0 <= boost <= 1.0:
        raise ValueError("Boost fora da faixa segura.")
    return AmostraBoost(sequencia, True, boost, fonte)


class ClassificadorRPM:
    """Transforma RPM em faixas estáveis e reconhece o limitador por debounce."""

    LIMITE_AMARELO = 0.55
    LIMITE_VERMELHO = 0.82
    HISTERESE = 0.03
    GAS_CORTE = 0.70
    RPM_CORTE = 0.97
    RPM_SAIDA_CORTE = 0.90
    ATRASO_CORTE = 0.08
    GRACA_CORTE = 0.18

    def __init__(self) -> None:
        self._faixa = "neutro"
        self._inicio_corte: float | None = None
        self._ultimo_perto_corte: float | None = None
        self._em_corte = False

    def neutralizar(self) -> EstadoVisual:
        self._faixa = "neutro"
        self._inicio_corte = None
        self._ultimo_perto_corte = None
        self._em_corte = False
        return ESTADO_NEUTRO

    def atualizar(self, amostra: AmostraRPM, agora: float | None = None) -> EstadoVisual:
        if not amostra.valida:
            return self.neutralizar()
        instante = time.monotonic() if agora is None else agora
        limite = amostra.maximo if amostra.drag else amostra.redline
        intervalo = max(1.0, limite - amostra.minimo)
        percentual = max(0.0, min(1.25, (amostra.rpm - amostra.minimo) / intervalo))

        acelerando = amostra.acelerador >= self.GAS_CORTE and not amostra.trocando_marcha
        perto_corte = acelerando and amostra.rpm >= limite * self.RPM_CORTE
        if perto_corte:
            if self._inicio_corte is None:
                self._inicio_corte = instante
            self._ultimo_perto_corte = instante
            if instante - self._inicio_corte >= self.ATRASO_CORTE:
                self._em_corte = True
        elif (
            self._ultimo_perto_corte is not None
            and acelerando
            and amostra.rpm >= limite * self.RPM_SAIDA_CORTE
            and instante - self._ultimo_perto_corte <= self.GRACA_CORTE
        ):
            # O limitador derruba o giro por alguns quadros. Esta janela mantém
            # o pisca ativo durante a queda, sem confundir uma troca de marcha.
            pass
        else:
            self._inicio_corte = None
            self._ultimo_perto_corte = None
            self._em_corte = False
        if self._em_corte:
            self._faixa = "vermelho"
            return EstadoVisual("corte", COR_VERMELHA, True, percentual)

        if self._faixa == "neutro":
            if percentual < self.LIMITE_AMARELO:
                faixa = "amarelo"
            elif percentual < self.LIMITE_VERMELHO:
                faixa = "laranja"
            else:
                faixa = "vermelho"
        elif self._faixa == "amarelo":
            faixa = "laranja" if percentual >= self.LIMITE_AMARELO + self.HISTERESE else "amarelo"
        elif self._faixa == "laranja":
            if percentual < self.LIMITE_AMARELO - self.HISTERESE:
                faixa = "amarelo"
            elif percentual >= self.LIMITE_VERMELHO + self.HISTERESE:
                faixa = "vermelho"
            else:
                faixa = "laranja"
        else:
            faixa = "laranja" if percentual < self.LIMITE_VERMELHO - self.HISTERESE else "vermelho"

        self._faixa = faixa
        cor = {
            "amarelo": COR_AMARELA,
            "laranja": COR_LARANJA,
            "vermelho": COR_VERMELHA,
        }[faixa]
        return EstadoVisual(faixa, cor, False, percentual)


class ModoRPM:
    """Recebe a telemetria e mantém DS4 e saída Wi-Fi coordenados."""

    def __init__(
        self,
        saida_abajur: Callable[[int, int, int], None] | None = None,
        fabrica_lightbar: Callable[[], DS4Lightbar] | None = DS4Lightbar,
        host: str = TELEMETRY_HOST,
        port: int = TELEMETRY_PORT,
    ) -> None:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError("O receptor RPM só pode escutar no endereço local.") from exc
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Porta de telemetria inválida.")
        self._saida_abajur = saida_abajur
        self._fabrica_lightbar = fabrica_lightbar
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None
        self._lightbar: DS4Lightbar | None = None
        self._thread: threading.Thread | None = None
        self._thread_abajur: threading.Thread | None = None
        self._parar = threading.Event()
        self._lock = threading.RLock()
        self._condicao_abajur = threading.Condition()
        self._classificador = ClassificadorRPM()
        self._estado = ESTADO_NEUTRO
        self._chave_saida = (ESTADO_NEUTRO.cor, False)
        self._amostra: AmostraRPM | None = None
        self._ultimo_pacote: float | None = None
        self._ultima_sequencia: int | None = None
        self._erro: str | None = None
        self._erro_abajur: str | None = None
        self._revisao_abajur = 0
        self._estado_abajur = ESTADO_NEUTRO

    @property
    def ativo(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and not self._parar.is_set())

    @property
    def erro(self) -> str | None:
        with self._lock:
            return self._erro

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        receptor = None
        try:
            receptor = subscribe(self._host, self._port)
            lightbar = self._fabrica_lightbar() if self._fabrica_lightbar is not None else None
        except Exception as exc:
            if receptor is not None:
                receptor.close()
            if isinstance(exc, ErroModoRPM):
                raise
            if isinstance(exc, DS4LightbarError):
                raise ErroModoRPM(str(exc)) from exc
            raise ErroModoRPM(
                "Não consegui preparar o modo RPM. Confira se outra Nebula já está ativa."
            ) from exc

        with self._lock:
            self._socket = receptor
            self._lightbar = lightbar
            self._erro = None
            self._erro_abajur = None
            self._amostra = None
            self._ultimo_pacote = None
            self._ultima_sequencia = None
            self._estado = self._classificador.neutralizar()
            self._chave_saida = (self._estado.cor, self._estado.corte)
        with self._condicao_abajur:
            self._estado_abajur = ESTADO_NEUTRO
            self._revisao_abajur += 1

        if self._saida_abajur is not None:
            self._thread_abajur = threading.Thread(
                target=self._loop_abajur,
                name="Nebula-RPM-Tuya",
                daemon=True,
            )
            self._thread_abajur.start()
        self._thread = threading.Thread(
            target=self._loop_receptor,
            name="Nebula-RPM-Telemetria",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _sequencia_nova(atual: int, anterior: int | None) -> bool:
        if anterior is None:
            return True
        diferenca = (atual - anterior) & 0xFFFFFFFF
        return 0 < diferenca < 0x80000000

    def _loop_receptor(self) -> None:
        try:
            while not self._parar.is_set():
                receptor = self._socket
                if receptor is None:
                    return
                try:
                    dados, origem = receptor.recvfrom(4097)
                except socket.timeout:
                    self._verificar_timeout()
                    continue
                except OSError:
                    if self._parar.is_set():
                        return
                    raise
                if origem[0] != TELEMETRY_HOST:
                    continue
                try:
                    amostra = interpretar_pacote(dados)
                except ValueError:
                    continue
                if not self._sequencia_nova(amostra.sequencia, self._ultima_sequencia):
                    continue
                agora = time.monotonic()
                self._ultima_sequencia = amostra.sequencia
                with self._lock:
                    self._ultimo_pacote = agora
                    self._amostra = amostra
                estado = self._classificador.atualizar(amostra, agora)
                self._aplicar_estado(estado)
        except Exception as exc:
            with self._lock:
                self._erro = f"O modo RPM foi interrompido: {exc}"
            self._parar.set()
            with self._condicao_abajur:
                self._condicao_abajur.notify_all()
            self.parar()

    def _verificar_timeout(self) -> None:
        with self._lock:
            ultimo = self._ultimo_pacote
            estado = self._estado
        if ultimo is not None and time.monotonic() - ultimo <= PACKET_TIMEOUT:
            return
        with self._lock:
            self._amostra = None
            self._ultima_sequencia = None
        if estado.faixa != "neutro":
            self._aplicar_estado(self._classificador.neutralizar())

    def _aplicar_estado(self, estado: EstadoVisual) -> None:
        chave = (estado.cor, estado.corte)
        with self._lock:
            self._estado = estado
            if chave == self._chave_saida:
                return
            self._chave_saida = chave
            lightbar = self._lightbar
        if lightbar is None or self._parar.is_set():
            return
        try:
            if estado.corte:
                lightbar.flash(*COR_VERMELHA, on_ms=250, off_ms=250)
            else:
                lightbar.set_rgb(*estado.cor)
        except DS4LightbarError as exc:
            with self._lock:
                self._erro = str(exc)
            self._parar.set()
            with self._condicao_abajur:
                self._condicao_abajur.notify_all()
            self.parar()
            return
        if self._saida_abajur is not None:
            with self._condicao_abajur:
                self._estado_abajur = estado
                self._revisao_abajur += 1
                self._condicao_abajur.notify()

    def _loop_abajur(self) -> None:
        ultima_revisao = -1
        ultima_cor: tuple[int, int, int] | None = None
        proximo_envio = 0.0
        fase_corte = False
        repetir = False
        while True:
            with self._condicao_abajur:
                while True:
                    agora = time.monotonic()
                    estado = self._estado_abajur
                    mudou = self._revisao_abajur != ultima_revisao
                    devido_corte = estado.corte and agora >= proximo_envio
                    devido_retry = repetir and agora >= proximo_envio
                    if self._parar.is_set() or ((mudou or devido_corte or devido_retry) and agora >= proximo_envio):
                        break
                    espera = max(0.01, proximo_envio - agora) if estado.corte or mudou or repetir else LAMP_INTERVAL
                    self._condicao_abajur.wait(min(LAMP_INTERVAL, espera))
                if self._parar.is_set():
                    # Nunca abandona a lâmpada na fase quase apagada do corte.
                    cor_final = (
                        COR_VERMELHA
                        if ultima_cor in (COR_CORTE_ESCURO, COR_CORTE_BRILHO)
                        else None
                    )
                    if cor_final is None:
                        return
                    alvo = cor_final
                else:
                    ultima_revisao = self._revisao_abajur
                    if estado.corte:
                        fase_corte = not fase_corte
                        # O corte pulsa vermelho no maximo contra preto, como se
                        # a lampada estivesse ligando e desligando rapidamente.
                        alvo = COR_CORTE_BRILHO if fase_corte else COR_CORTE_ESCURO
                    else:
                        fase_corte = False
                        alvo = estado.cor
            callback = self._saida_abajur
            if callback is None:
                return
            try:
                callback(*alvo)
            except Exception:
                with self._lock:
                    self._erro_abajur = "O abajur perdeu a conexão Wi-Fi; o controle continua ativo."
                proximo_envio = time.monotonic() + LAMP_RETRY_INTERVAL
                repetir = True
            else:
                with self._lock:
                    self._erro_abajur = None
                ultima_cor = alvo
                proximo_envio = time.monotonic() + (
                    LAMP_CUT_INTERVAL if estado.corte else LAMP_INTERVAL
                )
                repetir = False
            if self._parar.is_set():
                return

    def parar(self) -> None:
        self._parar.set()
        receptor = self._socket
        if receptor is not None:
            try:
                receptor.close()
            except OSError:
                pass
        with self._condicao_abajur:
            self._condicao_abajur.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        thread_abajur = self._thread_abajur
        if thread_abajur is not None and thread_abajur is not threading.current_thread():
            thread_abajur.join(timeout=15.0)
            if thread_abajur.is_alive():
                with self._lock:
                    self._erro_abajur = "O envio Wi-Fi ainda está sendo encerrado."

        lightbar = self._lightbar
        if lightbar is not None:
            try:
                if lightbar.is_open:
                    lightbar.set_rgb(*COR_NEUTRA)
            except DS4LightbarError as exc:
                with self._lock:
                    self._erro = str(exc)
            try:
                lightbar.close()
            except DS4LightbarError as exc:
                with self._lock:
                    self._erro = str(exc)
        with self._lock:
            self._socket = None
            self._lightbar = None
            self._thread = None
            self._thread_abajur = None
            self._estado = self._classificador.neutralizar()

    def status(self) -> dict[str, object]:
        agora = time.monotonic()
        with self._lock:
            ultimo = self._ultimo_pacote
            amostra = self._amostra
            estado = self._estado
            return {
                "ativo": self.ativo,
                "recebendo": ultimo is not None and agora - ultimo <= PACKET_TIMEOUT,
                "telemetria_valida": bool(amostra is not None and amostra.valida),
                "faixa": estado.faixa,
                "rpm": round(amostra.rpm) if amostra is not None and amostra.valida else None,
                "fonte": amostra.fonte if amostra is not None else None,
                "percentual": round(estado.percentual * 100, 1),
                "marcha": amostra.marcha if amostra is not None and amostra.valida else None,
                "acelerador_percentual": (
                    round(amostra.acelerador * 100, 1)
                    if amostra is not None and amostra.valida else None
                ),
                "rpm_minimo": amostra.minimo if amostra is not None and amostra.valida else None,
                "rpm_corte": amostra.redline if amostra is not None and amostra.valida else None,
                "rpm_maximo": amostra.maximo if amostra is not None and amostra.valida else None,
                "trocando_marcha": bool(
                    amostra is not None and amostra.valida and amostra.trocando_marcha
                ),
                "velocidade_kmh": (
                    amostra.velocidade_kmh if amostra is not None and amostra.valida else None
                ),
                "turbo_bar": amostra.turbo_bar if amostra is not None and amostra.valida else None,
                "pressao_oleo": (
                    amostra.pressao_oleo if amostra is not None and amostra.valida else None
                ),
                "combustivel_percentual": (
                    amostra.combustivel_percentual
                    if amostra is not None and amostra.valida else None
                ),
                "temperatura_agua": (
                    amostra.temperatura_agua if amostra is not None and amostra.valida else None
                ),
                "temperatura_oleo": (
                    amostra.temperatura_oleo if amostra is not None and amostra.valida else None
                ),
                "mapa_motor": amostra.mapa_motor if amostra is not None and amostra.valida else None,
                "controle": "conectado" if self._lightbar is not None else "desconectado",
                "abajur": (
                    "desativado"
                    if self._saida_abajur is None
                    else "erro" if self._erro_abajur else "conectado"
                ),
                "erro": self._erro,
                "erro_abajur": self._erro_abajur,
            }


class ModoBoost:
    """Converte o boost em brilho para lampada, DualShock 4 e teclado RGB."""

    def __init__(
        self,
        saida_abajur: Callable[[int], None],
        host: str = TELEMETRY_HOST,
        port: int = TELEMETRY_PORT,
        brilho_retorno: int = 100,
        fonte_esperada: str | None = None,
        fabrica_lightbar: Callable[[], DS4Lightbar] | None = DS4Lightbar,
        fabrica_teclado: Callable[[], AttackSharkX98HE | TecladoKumaraOpenRGB | TecladoKumaraUSB] | None = AttackSharkX98HE,
        cor_controle: tuple[int, int, int] = COR_BOOST,
        cor_teclado: tuple[int, int, int] = COR_BOOST,
    ) -> None:
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError as exc:
            raise ValueError("O receptor de boost só pode escutar no endereço local.") from exc
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Porta de telemetria inválida.")
        if not callable(saida_abajur):
            raise ValueError("O modo boost precisa de uma saída de brilho para a lâmpada.")
        if fonte_esperada is not None and (not fonte_esperada or len(fonte_esperada) > 64):
            raise ValueError("Fonte esperada de boost inválida.")
        self._saida_abajur = saida_abajur
        self._host = host
        self._port = port
        self._brilho_retorno = self._limitar_brilho(brilho_retorno)
        self._fonte_esperada = fonte_esperada
        self._fabrica_lightbar = fabrica_lightbar
        self._fabrica_teclado = fabrica_teclado
        self._cor_controle = self._validar_cor(cor_controle)
        self._cor_teclado = self._validar_cor(cor_teclado)
        self._socket: socket.socket | None = None
        self._lightbar: DS4Lightbar | None = None
        self._teclado: AttackSharkX98HE | TecladoKumaraOpenRGB | TecladoKumaraUSB | None = None
        self._thread: threading.Thread | None = None
        self._thread_abajur: threading.Thread | None = None
        self._parar = threading.Event()
        self._lock = threading.RLock()
        self._condicao_abajur = threading.Condition()
        self._amostra: AmostraBoost | None = None
        self._ultimo_pacote: float | None = None
        self._ultima_sequencia: int | None = None
        self._erro: str | None = None
        self._erro_abajur: str | None = None
        self._erro_controle: str | None = None
        self._erro_teclado: str | None = None
        self._brilho_desejado: int | None = None
        self._brilho_aplicado: int | None = None
        self._revisao_abajur = 0
        self._chave_hardware: tuple[bool, int] | None = None

    @staticmethod
    def _limitar_brilho(valor: int | float) -> int:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ValueError("O brilho precisa ser numérico.")
        return max(1, min(100, round(valor)))

    @staticmethod
    def brilho_do_boost(boost: float) -> int:
        """Mapeia 0..1 linearmente para 1..100, sem nunca desligar a lâmpada."""
        if isinstance(boost, bool) or not isinstance(boost, (int, float)):
            raise ValueError("O boost precisa ser numérico.")
        boost = float(boost)
        if not math.isfinite(boost) or not 0.0 <= boost <= 1.0:
            raise ValueError("O boost precisa ficar entre zero e um.")
        return round(1.0 + boost * 99.0)

    @staticmethod
    def _validar_cor(cor: tuple[int, int, int]) -> tuple[int, int, int]:
        if (
            not isinstance(cor, tuple)
            or len(cor) != 3
            or not all(isinstance(canal, int) and not isinstance(canal, bool) and 0 <= canal <= 255 for canal in cor)
            or not any(cor)
        ):
            raise ValueError("A cor do controle precisa ser um RGB visivel.")
        return cor

    @staticmethod
    def cor_do_boost(
        brilho: int,
        cor_base: tuple[int, int, int] = COR_BOOST,
    ) -> tuple[int, int, int]:
        brilho = ModoBoost._limitar_brilho(brilho)
        cor_base = ModoBoost._validar_cor(cor_base)
        return tuple(round(canal * brilho / 100) for canal in cor_base)  # type: ignore[return-value]

    def definir_cor_controle(self, cor: tuple[int, int, int]) -> None:
        """Define a matiz da lightbar antes de iniciar o modo boost."""
        with self._lock:
            if self.ativo:
                raise RuntimeError("Defina a cor do controle antes de iniciar o modo boost.")
            self._cor_controle = self._validar_cor(cor)

    def definir_cor_teclado(self, cor: tuple[int, int, int]) -> None:
        """Define a cor da barra do teclado sem alterar a lightbar."""
        with self._lock:
            if self.ativo:
                raise RuntimeError("Defina a cor do teclado antes de iniciar o modo boost.")
            self._cor_teclado = self._validar_cor(cor)

    def definir_brilho_retorno(self, brilho: int) -> None:
        """Define o brilho restaurado ao parar ou perder a telemetria."""
        with self._lock:
            if self.ativo:
                raise RuntimeError("Defina o brilho de retorno antes de iniciar o modo boost.")
            self._brilho_retorno = self._limitar_brilho(brilho)

    @property
    def ativo(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive() and not self._parar.is_set())

    @property
    def erro(self) -> str | None:
        with self._lock:
            return self._erro

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._parar.clear()
        receptor = None
        try:
            receptor = subscribe(self._host, self._port)
        except OSError as exc:
            raise ErroModoBoost(
                "Não consegui abrir a telemetria. Confira se outro modo da Nebula já está ativo."
            ) from exc
        lightbar = None
        teclado = None
        erro_controle = None
        erro_teclado = None
        if self._fabrica_lightbar is not None:
            try:
                lightbar = self._fabrica_lightbar()
            except DS4LightbarError as exc:
                erro_controle = str(exc)
        if self._fabrica_teclado is not None:
            try:
                teclado = self._fabrica_teclado()
                teclado.definir_cor_base(self._cor_teclado)
            except (AttackSharkError, OpenRGBKeyboardError) as exc:
                erro_teclado = str(exc)
        with self._lock:
            self._socket = receptor
            self._lightbar = lightbar
            self._teclado = teclado
            self._amostra = None
            self._ultimo_pacote = None
            self._ultima_sequencia = None
            self._erro = None
            self._erro_abajur = None
            self._erro_controle = erro_controle
            self._erro_teclado = erro_teclado
            self._brilho_desejado = None
            self._brilho_aplicado = None
            self._chave_hardware = None
        self._thread_abajur = threading.Thread(
            target=self._loop_abajur,
            name="Nebula-Boost-Tuya",
            daemon=True,
        )
        self._thread_abajur.start()
        self._thread = threading.Thread(
            target=self._loop_receptor,
            name="Nebula-Boost-Telemetria",
            daemon=True,
        )
        self._thread.start()

    @staticmethod
    def _sequencia_nova(atual: int, anterior: int | None) -> bool:
        return ModoRPM._sequencia_nova(atual, anterior)

    def _loop_receptor(self) -> None:
        try:
            while not self._parar.is_set():
                receptor = self._socket
                if receptor is None:
                    return
                try:
                    dados, origem = receptor.recvfrom(4097)
                except socket.timeout:
                    self._verificar_timeout()
                    continue
                except OSError:
                    if self._parar.is_set():
                        return
                    raise
                amostra = self._amostra_boost_recente(receptor, dados, origem)
                if amostra is None:
                    continue
                agora = time.monotonic()
                with self._lock:
                    self._ultimo_pacote = agora
                    self._amostra = amostra
                if amostra.valida:
                    brilho = self.brilho_do_boost(amostra.boost)
                    self._agendar_brilho(brilho)
                    self._aplicar_hardware(brilho)
                else:
                    self._agendar_brilho(self._brilho_retorno)
                    self._aplicar_hardware(None)
        except Exception as exc:
            with self._lock:
                self._erro = f"O modo boost foi interrompido: {exc}"
            self._parar.set()
            with self._condicao_abajur:
                self._condicao_abajur.notify_all()

    def _amostra_boost_recente(self, receptor, dados, origem):
        """Descarta atraso acumulado enquanto o quadro USB era confirmado."""
        latest = None
        for index in range(256):
            if origem[0] == TELEMETRY_HOST:
                try:
                    candidate = interpretar_pacote_boost(dados)
                except ValueError:
                    candidate = None
                if (candidate is not None
                    and (self._fonte_esperada is None or candidate.fonte == self._fonte_esperada)
                    and self._sequencia_nova(candidate.sequencia, self._ultima_sequencia)):
                    self._ultima_sequencia = candidate.sequencia
                    latest = candidate
            if index == 255 or not (receptor.has_pending() if isinstance(receptor, TelemetrySubscription) else select.select([receptor], [], [], 0)[0]):
                break
            dados, origem = receptor.recvfrom(4097)
        return latest

    def _verificar_timeout(self) -> None:
        with self._lock:
            ultimo = self._ultimo_pacote
            tinha_amostra = self._amostra is not None
        if ultimo is not None and time.monotonic() - ultimo <= PACKET_TIMEOUT:
            return
        with self._lock:
            self._amostra = None
            self._ultima_sequencia = None
        if tinha_amostra:
            self._agendar_brilho(self._brilho_retorno)
            self._aplicar_hardware(None)

    def _aplicar_hardware(self, brilho: int | None) -> None:
        chave = (brilho is not None, brilho or 0)
        with self._lock:
            if chave == self._chave_hardware:
                return
            self._chave_hardware = chave
            lightbar = self._lightbar
            teclado = self._teclado
        if lightbar is not None:
            try:
                cor = (
                    self.cor_do_boost(brilho, self._cor_controle)
                    if brilho is not None
                    else COR_NEUTRA
                )
                lightbar.set_rgb(*cor)
            except DS4LightbarError as exc:
                with self._lock:
                    self._erro_controle = str(exc)
                    self._lightbar = None
                try:
                    lightbar.close()
                except DS4LightbarError:
                    pass
        if teclado is not None:
            try:
                if brilho is None:
                    teclado.restaurar()
                else:
                    teclado.set_boost(brilho)
            except (AttackSharkError, OpenRGBKeyboardError) as exc:
                with self._lock:
                    self._erro_teclado = str(exc)
                    self._teclado = None
                try:
                    teclado.close()
                except (AttackSharkError, OpenRGBKeyboardError):
                    pass

    def _agendar_brilho(self, brilho: int) -> None:
        brilho = self._limitar_brilho(brilho)
        with self._condicao_abajur:
            if brilho == self._brilho_desejado:
                return
            self._brilho_desejado = brilho
            self._revisao_abajur += 1
            self._condicao_abajur.notify()

    def _loop_abajur(self) -> None:
        ultima_revisao = -1
        proximo_envio = 0.0
        repetir = False
        restaurou = False
        while True:
            with self._condicao_abajur:
                while True:
                    agora = time.monotonic()
                    mudou = self._revisao_abajur != ultima_revisao
                    if self._parar.is_set():
                        if self._brilho_aplicado is None or restaurou:
                            return
                        alvo = self._brilho_retorno
                        restaurou = True
                        break
                    if self._brilho_desejado is not None and (mudou or repetir) and agora >= proximo_envio:
                        alvo = self._brilho_desejado
                        ultima_revisao = self._revisao_abajur
                        break
                    espera = max(0.01, proximo_envio - agora) if mudou or repetir else LAMP_INTERVAL
                    self._condicao_abajur.wait(min(LAMP_INTERVAL, espera))
            try:
                self._saida_abajur(alvo)
            except Exception:
                with self._lock:
                    self._erro_abajur = "A lâmpada perdeu a conexão Wi-Fi."
                if restaurou:
                    return
                proximo_envio = time.monotonic() + LAMP_RETRY_INTERVAL
                repetir = True
            else:
                with self._lock:
                    self._erro_abajur = None
                    self._brilho_aplicado = alvo
                proximo_envio = time.monotonic() + LAMP_INTERVAL
                repetir = False
                if restaurou:
                    return

    def parar(self) -> None:
        self._parar.set()
        receptor = self._socket
        if receptor is not None:
            try:
                receptor.close()
            except OSError:
                pass
        with self._condicao_abajur:
            self._condicao_abajur.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        thread_abajur = self._thread_abajur
        if thread_abajur is not None and thread_abajur is not threading.current_thread():
            thread_abajur.join(timeout=15.0)
            if thread_abajur.is_alive():
                with self._lock:
                    self._erro_abajur = "O envio Wi-Fi ainda está sendo encerrado."
        lightbar = self._lightbar
        teclado = self._teclado
        if lightbar is not None:
            try:
                if lightbar.is_open:
                    lightbar.set_rgb(*COR_NEUTRA)
            except DS4LightbarError as exc:
                with self._lock:
                    self._erro_controle = str(exc)
            try:
                lightbar.close()
            except DS4LightbarError:
                pass
        if teclado is not None:
            try:
                teclado.close()
            except (AttackSharkError, OpenRGBKeyboardError) as exc:
                with self._lock:
                    self._erro_teclado = str(exc)
        with self._lock:
            self._socket = None
            self._thread = None
            self._thread_abajur = None
            self._lightbar = None
            self._teclado = None

    def status(self) -> dict[str, object]:
        agora = time.monotonic()
        with self._lock:
            ultimo = self._ultimo_pacote
            amostra = self._amostra
            return {
                "ativo": self.ativo,
                "recebendo": ultimo is not None and agora - ultimo <= PACKET_TIMEOUT,
                "telemetria_valida": bool(amostra is not None and amostra.valida),
                "boost": round(amostra.boost * 100) if amostra is not None and amostra.valida else None,
                "brilho": self._brilho_aplicado,
                "fonte": amostra.fonte if amostra is not None else None,
                "abajur": "erro" if self._erro_abajur else "conectado",
                "controle": "conectado" if self._lightbar is not None else "indisponivel",
                "teclado": "conectado" if self._teclado is not None else "indisponivel",
                "cor_teclado": self._cor_teclado,
                "erro": self._erro,
                "erro_abajur": self._erro_abajur,
                "erro_controle": self._erro_controle,
                "erro_teclado": self._erro_teclado,
            }


__all__ = [
    "AmostraBoost",
    "AmostraRPM",
    "ClassificadorRPM",
    "COR_AMARELA",
    "COR_BOOST",
    "COR_CORTE_ESCURO",
    "COR_LARANJA",
    "COR_NEUTRA",
    "COR_VERMELHA",
    "ErroModoBoost",
    "ErroModoRPM",
    "EstadoVisual",
    "ModoBoost",
    "ModoRPM",
    "TELEMETRY_HOST",
    "TELEMETRY_PORT",
    "interpretar_pacote",
    "interpretar_pacote_boost",
]
