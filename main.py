"""Nebula: uma assistente virtual simples, por voz ou texto."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import difflib
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import tempfile
import time
import webbrowser
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Protocol
from urllib.parse import quote_plus

from app_launcher import Aplicativo, IniciadorAplicativos
from abajur_wifi import ErroAbajur, interpretar_comandos_abajur
from abajur_tuya import ConfiguracaoTuya, ControleAbajurTuya
from modules.iot.lights import ControleAbajur, executar_pedidos_abajur
from modules.iot.ambilight import selecionar_saidas_teclado
from ar_ir_direto import ControleArDireto
from device_presets import (
    Presets,
    MODES as DEVICE_MODES,
    KEYBOARD_EFFECTS,
    defaults as device_defaults,
    validate as validate_devices,
    voice_preset,
)
from captura_tela import capturar_tela
from controles_windows import ajustar_volume_youtube, salvar_replay_nvidia
from integrations.llm.qwen import ConversaLocal
from core.action_contracts import AcaoQwen
from core.legacy_actions import comando_canonico
from core.bootstrap import criar_dispatcher
from integrations.codex.client import CodexClient
from config_modelo import qwen_ativa
from lexicon import import_dictionary, learn, lookup
from leitor_boost_visual import (
    ErroLeitorBoostVisual,
    LeitorBoostVisual,
    VISUAL_SOURCE,
)
from memoria_nebula import (
    MEMORIA,
    aplicar_correcoes,
    interpretar_comando_feedback,
    interpretar_comando_contexto,
    interpretar_comando_correcao,
)
from modo_ambilight import CapturadorJanelaNetflix, ErroModoAmbilight, ModoAmbilight
from lightbar_ds4 import DS4Lightbar, DS4LightbarError
from modo_rpm import ErroModoBoost, ErroModoRPM, ModoBoost, ModoRPM
from teclado_openrgb import OpenRGBKeyboardError, TecladoKumaraOpenRGB, criar_teclado_kumara
from teclado_evision import TecladoKumaraUSB
from notas import criar_e_abrir_nota
from reconhecedor_musica import identificar_musica
from youtube_player import primeiro_video


NOME_ASSISTENTE = "nebu"
NOMES_ASSISTENTE = ("nebu",)

RESPOSTAS_ATIVACAO = (
    "Sim? Espero que seja importante.",
    "Estou ouvindo. Milagre, eu sei.",
    "Pois não, ser humano.",
    "Você chamou? Infelizmente eu ouvi.",
    "À disposição. Dentro do razoável, claro.",
    "Diga. Estou prestando atenção.",
    "Pode falar, eu cuido disso.",
    "Nebula online. Qual é a missão da vez?",
    "Chamou a especialista em tarefas questionáveis?",
    "Estou aqui. O computador ainda não venceu você, espero.",
    "Sim, chefe. Isto é, usuário.",
    "Manda. Prometo julgar só um pouquinho.",
)


def saudacao_inicial() -> str:
    hora = datetime.now().hour
    periodo = "Bom dia" if 5 <= hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    return random.choice((
        f"{periodo}. Nebula online e pronta para ajudar.",
        f"{periodo}. Sistemas ativos; pode mandar.",
        f"{periodo}. Voltei. O computador já está ligeiramente mais competente.",
        f"{periodo}. Tudo pronto por aqui.",
    ))

RESPOSTAS_INICIALIZACAO = (
    "Nebula iniciada. Tente não abusar do meu incrível talento para abrir abas.",
    "Sistemas ativos. Pode começar a distribuir ordens.",
    "Nebula online e ouvindo. Que comece a produtividade, teoricamente.",
    "Tudo pronto. Microfone aberto e paciência carregada.",
    "Iniciada com sucesso. Vamos fingir que temos tudo sob controle.",
    "Estou online. Pode falar quando precisar.",
    "Nebula operacional. Seu computador acabou de ficar ligeiramente mais útil.",
    "Pronta para ajudar. Sim, até com suas escolhas musicais.",
)

RESPOSTAS_YOUTUBE = (
    "Abrindo no YouTube. Um trabalho extremamente complexo, obviamente.",
    "Pesquisando no YouTube. Não precisa agradecer tanto.",
    "Pronto. Indo procurar isso no YouTube.",
    "Certo, procurando essa música no YouTube.",
    "YouTube aberto. A trilha sonora da sua procrastinação está a caminho.",
    "Buscando no YouTube. Vamos descobrir se seu gosto melhorou.",
    "Deixa comigo, vou encontrar isso no YouTube.",
    "Preparando sua música. Sem julgamentos... muitos.",
    "Abrindo a busca no YouTube agora.",
    "Lá vamos nós alimentar o algoritmo outra vez.",
    "Pesquisa musical encaminhada com sucesso.",
    "Achei um uso nobre para o navegador: música.",
    "Indo ao YouTube. Espero que seja uma boa escolha.",
)

RESPOSTAS_GOOGLE = (
    "Pesquisando no Google. Porque aparentemente eu também virei seu navegador.",
    "Certo. Vou pesquisar isso.",
    "Abrindo a pesquisa. Revolucionário.",
    "Vou procurar isso no seu navegador.",
    "Pesquisa a caminho. Curiosidade é uma qualidade, às vezes.",
    "Certo, consultando a vastidão da internet.",
    "Abrindo os resultados agora.",
    "Deixa comigo. O Google e eu resolveremos isso.",
    "Pesquisando. Tente parecer surpreso com os resultados.",
    "Uma busca rápida, vindo imediatamente.",
    "Entendido. Vou ver o que a internet tem a dizer.",
)

RESPOSTAS_DESCONHECIDO = (
    "Ainda não sei fazer isso. Meu cérebro tem linhas de código, não milagres.",
    "Esse comando ainda não faz parte do meu repertório.",
    "Não reconheci essa tarefa. Tente dizer de outra forma.",
    "Isso passou direto pelos meus circuitos. Pode reformular?",
    "Ainda não aprendi esse truque, mas anote mentalmente para a próxima atualização.",
    "Não consegui associar isso a nenhum comando. Fascinante e pouco útil.",
    "Eu ouvi as palavras, só não encontrei sentido operacional nelas.",
    "Por enquanto, isso está além das minhas humildes linhas de Python.",
    "Comando desconhecido. Até inteligências artificiais têm limites — aparentemente.",
    "Tente novamente com um comando mais direto.",
    "Essa eu vou ficar devendo. Uma raridade, aproveite o momento.",
    "Não sei executar isso ainda. Ênfase no ainda.",
)

RESPOSTAS_PAUSE = (
    "Pronto. Seus ouvidos ganharam uma folga momentânea.",
    "Música pausada.",
    "Pause enviado. O silêncio voltou a reinar.",
    "Parei a reprodução. Dramático, mas eficiente.",
    "Tudo pausado por aqui.",
    "Reprodução interrompida, como solicitado.",
    "Pausa aplicada. Aproveite esses raros segundos de silêncio.",
)

RESPOSTAS_CONTINUAR = (
    "Continuando a reprodução.",
    "Play enviado. De volta à trilha sonora.",
    "A música voltou. A vizinhança agradece, talvez.",
    "Retomando de onde parou.",
    "Reprodução retomada.",
    "Pronto, chega de silêncio.",
)

RESPOSTAS_ABRIR_STEAM = (
    "Steam. Uma escolha surpreendentemente sensata. Abrindo.",
    "Abrindo o Rocket League pela Steam.",
    "Steam selecionada. Hora de perseguir uma bola com um carro.",
    "Certo, iniciando pela Steam.",
    "Rocket League via Steam. Boa partida.",
)

RESPOSTAS_ABRIR_EPIC = (
    "Epic então. Abrindo o Rocket League.",
    "Abrindo pela Epic Games.",
    "Epic selecionada. Preparando o caos automobilístico.",
    "Certo, iniciando o Rocket League pela Epic.",
    "Epic Games, entendido. Boa partida.",
)


def normalizar_texto(texto: str) -> str:
    """Normaliza a fala e aplica correções ensinadas pelo usuário."""
    return aplicar_correcoes(texto)


def corresponde_intencao(comando: str, exemplos: tuple[str, ...], limite: float = 0.82) -> bool:
    """Aceita sinônimos e pequenos erros do reconhecimento em comandos seguros."""
    if any(exemplo in comando for exemplo in exemplos):
        return True
    return bool(difflib.get_close_matches(comando, exemplos, n=1, cutoff=limite))


def interpretar_comando_modo_rpm(comando: str) -> str | None:
    """Reconhece os comandos diretos do modo de iluminação por RPM."""
    texto = normalizar_texto(comando).strip(" ,.!?")
    palavras = set(texto.split())
    relacionado = (
        "rpm" in palavras
        or "modo giro" in texto
        or (
            "giro" in palavras
            and bool(
                palavras
                & {"carro", "motor", "controle", "abajur", "luz", "luzes"}
            )
        )
    )
    if not relacionado:
        return None

    if palavras & {"status", "estado"} or any(
        trecho in texto
        for trecho in ("como esta", "esta ativo", "esta ligado", "funcionando")
    ):
        return "status"
    if palavras & {"pare", "para", "parar", "desative", "desativa", "desligue", "desliga"}:
        return "parar"
    if palavras & {
        "ative", "ativa", "ativar", "inicie", "inicia", "iniciar",
        "ligue", "liga", "sincronize", "sincroniza", "acompanhe", "acompanha",
        "acompanhem", "acompanharem", "faca",
    } or any(
        trecho in texto
        for trecho in ("seguir o giro", "acompanhar o giro", "acompanhar o rpm")
    ):
        return "iniciar"
    return None


def interpretar_comando_modo_boost(comando: str) -> str | None:
    """Reconhece comandos para o brilho acompanhar o boost do Rocket League."""
    texto = normalizar_texto(comando).strip(" ,.!?")
    palavras = set(texto.split())
    relacionado = "boost" in palavras and (
        "modo" in palavras
        or "rocket league" in texto
        or bool(palavras & {"abajur", "lampada", "luz", "brilho", "telemetria"})
    )
    if not relacionado:
        return None
    if palavras & {"status", "estado"} or any(
        trecho in texto for trecho in ("como esta", "esta ativo", "funcionando")
    ):
        return "status"
    if palavras & {"pare", "para", "parar", "desative", "desativa", "desligue", "desliga"}:
        return "parar"
    if palavras & {
        "ative", "ativa", "ativar", "inicie", "inicia", "iniciar", "ligue", "liga",
        "sincronize", "sincroniza", "acompanhe", "acompanha", "reaja", "reagir", "faca",
    }:
        return "iniciar"
    return None


def interpretar_comando_modo_ambilight(comando: str) -> str | None:
    """Reconhece pedidos para a lampada acompanhar as cores da tela."""
    texto = normalizar_texto(comando).strip(" ,.!?")
    palavras = set(texto.split())
    relacionado = (
        "ambilight" in palavras
        or "modo cinema" in texto
        or (
            bool(palavras & {"tela", "cena", "cenas", "filme", "serie", "netflix"})
            and bool(palavras & {"abajur", "lampada", "luz", "luzes", "cor", "cores"})
        )
    )
    if not relacionado:
        return None
    if palavras & {"status", "estado"} or any(
        trecho in texto for trecho in ("como esta", "esta ativo", "funcionando")
    ):
        return "status"
    if palavras & {"pare", "para", "parar", "desative", "desativa", "desligue", "desliga"}:
        return "parar"
    if palavras & {
        "ative", "ativa", "ativar", "inicie", "inicia", "iniciar", "ligue", "liga",
        "sincronize", "sincroniza", "acompanhe", "acompanha", "mude", "mudar", "faca",
    } or any(
        trecho in texto
        for trecho in (
            "acompanhar a tela", "acompanhar as cenas", "acompanhar o filme",
            "mudar com a tela", "mudar com as cenas", "tom medio da cena",
        )
    ):
        return "iniciar"
    return None


def extrair_chamada(texto: str) -> tuple[bool, str]:
    """Detecta exclusivamente o nome de ativação Nebu e devolve o comando."""
    texto = texto.lower().strip()
    normalizado = normalizar_texto(texto)
    encontrado = re.search(r"\bnebu\b", normalizado)
    if not encontrado:
        return False, texto
    # A correção ensinada pode alterar o tamanho do texto (por exemplo,
    # "nevo" -> "nebu"). Por isso os índices pertencem ao texto normalizado.
    comando = f"{normalizado[:encontrado.start()]} {normalizado[encontrado.end():]}"
    return True, " ".join(comando.strip(" ,").split())


def comando_incompleto(comando: str) -> bool:
    """Evita executar fragmentos capturados durante uma pausa na fala."""
    comando = normalizar_texto(comando).strip(" ,.!?")
    fragmentos = {
        "", "a", "o", "um", "uma", "para", "por", "por favor",
        "abra", "abre", "abrir", "toca", "toque", "pesquise", "procure",
    }
    return comando in fragmentos or len(comando) < 2


COMANDOS_CLIPE = (
    "clipe", "clip", "clipa", "clipa isso", "clipe isso", "clip isso",
    "clipe ai", "clip ai", "clipa ai", "clipe agora", "clip agora",
    "faz um clipe", "faca um clipe", "crie um clipe", "cria um clipe",
    "salva o clipe", "salve o clipe", "salva esse clipe", "salve esse clipe",
    "salva o replay", "salve o replay", "replay da nvidia",
    "clip da nvidia", "grava os ultimos minutos",
)


def comando_de_clipe(comando: str) -> bool:
    """Identifica a ação urgente de salvar o replay da NVIDIA."""
    normalizado = normalizar_texto(comando).strip(" ,.!?")
    if normalizado in COMANDOS_CLIPE or any(
        pedido in normalizado for pedido in COMANDOS_CLIPE if " " in pedido
    ):
        return True

    # O Google às vezes devolve uma grafia próxima para a palavra curta
    # "clipe". Só usamos aproximação em frases bem pequenas para não confundir
    # conversas normais com o comando urgente de replay.
    palavras = normalizado.split()
    if 1 <= len(palavras) <= 3:
        auxiliares = {"isso", "ai", "agora", "ja", "por", "favor"}
        candidatas = [palavra for palavra in palavras if palavra not in auxiliares]
        return any(
            difflib.SequenceMatcher(None, palavra, alvo).ratio() >= 0.76
            for palavra in candidatas
            for alvo in ("clipe", "clipa", "clip")
        )
    return False


class Saida(Protocol):
    def falar(self, texto: str) -> None: ...


class Voz:
    """Usa voz neural feminina e recorre ao SAPI quando estiver offline."""

    VOZ_NEURAL = "pt-BR-FranciscaNeural"

    def __init__(
        self,
        ao_falar: Callable[[str], None] | None = None,
        ao_mudar_estado: Callable[[bool], None] | None = None,
    ) -> None:
        try:
            import win32com.client
        except ImportError as exc:
            raise RuntimeError(
                "O suporte de voz do Windows não está instalado. Rode: "
                'python -m pip install -r requirements.txt'
            ) from exc

        self._win32com = win32com.client
        try:
            import edge_tts
        except ImportError:
            edge_tts = None
        self._edge_tts = edge_tts
        self._ao_falar = ao_falar
        self._ao_mudar_estado = ao_mudar_estado
        self._fila: queue.Queue[str] = queue.Queue()
        self._falando = threading.Event()
        self._pronta = threading.Event()
        self._erro_inicializacao: BaseException | None = None
        self._trabalhadora = threading.Thread(
            target=self._processar_falas,
            name="NebulaVoz",
            daemon=True,
        )
        self._trabalhadora.start()
        if not self._pronta.wait(8):
            raise RuntimeError("A voz do Windows demorou demais para iniciar.")
        if self._erro_inicializacao is not None:
            raise RuntimeError(
                f"Não foi possível iniciar a voz do Windows: {self._erro_inicializacao}"
            ) from self._erro_inicializacao

    def _selecionar_voz_ptbr(self, motor: object) -> None:
        preferencias = ("maria", "henrique", "portuguese", "brazil", "brasil")
        for voz in motor.GetVoices():  # type: ignore[attr-defined]
            descricao = normalizar_texto(voz.GetDescription())
            if any(preferencia in descricao for preferencia in preferencias):
                motor.Voice = voz  # type: ignore[attr-defined]
                print(f"Voz selecionada: {voz.GetDescription()}")
                return

        print(
            "Aviso: nenhuma voz pt-BR foi encontrada; usando a voz padrão do Windows."
        )

    @property
    def esta_falando(self) -> bool:
        return self._falando.is_set()

    def _falar_com_edge(self, texto: str) -> None:
        """Gera um MP3 neural e o reproduz de forma bloqueante pelo Windows."""
        if self._edge_tts is None:
            raise RuntimeError("edge-tts não está instalado")
        temporario = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        caminho = temporario.name
        temporario.close()
        alias = f"nebula_{threading.get_ident()}"
        winmm = ctypes.windll.winmm

        def mci(comando: str) -> None:
            erro = winmm.mciSendStringW(comando, None, 0, None)
            if erro:
                raise RuntimeError(f"erro de áudio do Windows: {erro}")

        try:
            comunicacao = self._edge_tts.Communicate(
                texto, self.VOZ_NEURAL, rate="+5%"
            )
            asyncio.run(comunicacao.save(caminho))
            mci(f'open "{caminho}" type mpegvideo alias {alias}')
            mci(f"play {alias}")
            buffer = ctypes.create_unicode_buffer(32)
            while True:
                winmm.mciSendStringW(f"status {alias} mode", buffer, 32, None)
                if buffer.value.casefold() not in {"playing", "seeking"}:
                    break
                time.sleep(0.05)
        finally:
            winmm.mciSendStringW(f"close {alias}", None, 0, None)
            try:
                os.unlink(caminho)
            except OSError:
                pass

    def _processar_falas(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            try:
                motor = self._win32com.Dispatch("SAPI.SpVoice")
                self._selecionar_voz_ptbr(motor)
                motor.Rate = 1
                motor.Volume = 100
            except BaseException as exc:
                self._erro_inicializacao = exc
                return
            finally:
                self._pronta.set()

            while True:
                texto = self._fila.get()
                self._falando.set()
                if self._ao_mudar_estado:
                    self._ao_mudar_estado(True)
                try:
                    # A fala bloqueia somente esta thread; os comandos seguem livres.
                    try:
                        self._falar_com_edge(texto)
                    except Exception as exc:
                        print(f"Voz neural indisponível; usando voz do Windows: {exc}")
                        motor.Speak(texto, 0)
                except Exception as exc:
                    print(f"Falha na voz do Windows: {exc}")
                finally:
                    self._fila.task_done()
                    if self._fila.empty():
                        self._falando.clear()
                        if self._ao_mudar_estado:
                            self._ao_mudar_estado(False)
        finally:
            self._pronta.set()
            pythoncom.CoUninitialize()

    def falar(self, texto: str) -> None:
        print(f"Nebula: {texto}")
        if self._ao_falar:
            self._ao_falar(texto)
        self._falando.set()
        self._fila.put(texto)


class Texto:
    """Saída sem áudio, útil para teste e para PCs sem microfone."""

    def falar(self, texto: str) -> None:
        print(f"Nebula: {texto}")


class SaidaRastreada:
    """Registra a resposta sem alterar o mecanismo de voz ou texto existente."""

    def __init__(self, saida: Saida, ao_falar: Callable[[str], None]) -> None:
        self._saida = saida
        self._ao_falar = ao_falar

    def falar(self, texto: str) -> None:
        self._ao_falar(texto)
        self._saida.falar(texto)


class SaidaSilenciavel:
    """Permite desligar a voz sem pausar comandos ou automacoes."""

    def __init__(self, saida: Saida) -> None:
        self._saida = saida
        self._muda = threading.Event()
        self._local = threading.local()

    @property
    def muda(self) -> bool:
        return self._muda.is_set()

    def definir_muda(self, muda: bool) -> None:
        if muda:
            self._muda.set()
        else:
            self._muda.clear()

    @contextmanager
    def silenciar_temporariamente(self) -> Iterator[None]:
        profundidade = int(getattr(self._local, "profundidade", 0))
        self._local.profundidade = profundidade + 1
        try:
            yield
        finally:
            self._local.profundidade = profundidade

    def falar(self, texto: str) -> None:
        if self.muda or int(getattr(self._local, "profundidade", 0)) > 0:
            print(f"Nebula [muda]: {texto}")
            return
        self._saida.falar(texto)


class Microfone:
    def __init__(
        self, saida: Saida, ao_ouvir: Callable[[str], None] | None = None
    ) -> None:
        try:
            import speech_recognition as sr
        except ImportError as exc:
            raise RuntimeError(
                "A biblioteca SpeechRecognition não está instalada. Rode: "
                'python -m pip install -r requirements.txt'
            ) from exc

        # O PyAudio original ainda não oferece wheel para Python 3.14 no Windows.
        # PyAudioWPatch expõe a mesma API e possui uma versão compatível.
        try:
            import pyaudio  # noqa: F401
        except ImportError:
            try:
                import pyaudiowpatch as pyaudio

                sys.modules["pyaudio"] = pyaudio
            except ImportError as exc:
                raise RuntimeError(
                    "O suporte ao microfone não está instalado. Rode: "
                    'python -m pip install -r requirements.txt'
                ) from exc

        self._sr = sr
        self._reconhecedor = sr.Recognizer()
        # Dá tempo para pausas naturais no meio de uma frase em português.
        self._reconhecedor.pause_threshold = 1.7
        self._reconhecedor.non_speaking_duration = 0.8
        self._reconhecedor.phrase_threshold = 0.25
        self._saida = saida
        self._ao_ouvir = ao_ouvir
        self._primeira_escuta = True

    def ouvir(self) -> str:
        try:
            with self._sr.Microphone() as fonte:
                if self._primeira_escuta:
                    print("Ouvindo...")
                    self._primeira_escuta = False
                self._reconhecedor.adjust_for_ambient_noise(fonte, duration=0.5)
                audio = self._reconhecedor.listen(
                    fonte, timeout=2, phrase_time_limit=15
                )
        except self._sr.WaitTimeoutError:
            return ""
        except (OSError, AttributeError) as exc:
            raise RuntimeError(
                "Não foi possível acessar o microfone. "
                "Confira o dispositivo e a permissão de microfone do Windows."
            ) from exc

        try:
            texto = self._reconhecedor.recognize_google(audio, language="pt-BR")
        except self._sr.UnknownValueError:
            return ""
        except self._sr.RequestError:
            self._saida.falar("O serviço de reconhecimento resolveu não colaborar.")
            return ""

        texto = texto.lower().strip()
        print(f"Você: {texto}")
        if self._ao_ouvir:
            self._ao_ouvir(texto)
        return texto


def limpar_pesquisa(comando: str, termos: tuple[str, ...]) -> str:
    pesquisa = comando
    for termo in sorted(termos, key=len, reverse=True):
        pesquisa = re.sub(rf"\b{re.escape(termo)}\b", " ", pesquisa)
    return " ".join(pesquisa.split())


class Nebula:
    def __init__(
        self,
        saida: Saida,
        abrir_navegador: bool = True,
        ao_solicitar_texto: Callable[[], None] | None = None,
        iniciar_muda: bool = False,
        ao_encaminhar_codex: Callable[[str], None] | None = None,
    ) -> None:
        self._saida_original = saida
        self._saida_silenciavel = SaidaSilenciavel(
            SaidaRastreada(saida, self._rastrear_resposta)
        )
        self._saida_silenciavel.definir_muda(iniciar_muda)
        self._pergunta_em_processamento = ""
        self._ultima_pergunta = ""
        self._ultima_resposta = ""
        self._ultima_resposta_id = ""
        self.saida: Saida = self._saida_silenciavel
        self.abrir_navegador = abrir_navegador
        self.comando_pendente: str | None = None
        self.aplicativo_pendente: Aplicativo | None = None
        self.aplicativos_pendentes: list[Aplicativo] = []
        self.ao_solicitar_texto = ao_solicitar_texto
        self.iniciador = IniciadorAplicativos()
        self.conversa = ConversaLocal()
        self._execution_lock = threading.RLock()
        self.codex = CodexClient(ao_encaminhar_codex, ao_responder=self.saida.falar)
        self._controle_abajur: ControleAbajur | None = None
        self._controle_abajur_lock = threading.RLock()
        self._controle_ar = ControleArDireto()
        self._modo_rpm: ModoRPM | None = None
        self._modo_rpm_lock = threading.RLock()
        self._modo_boost: ModoBoost | None = None
        self._leitor_boost_visual: LeitorBoostVisual | None = None
        self._modo_boost_lock = threading.RLock()
        self._modo_ambilight: ModoAmbilight | None = None
        self._modo_ambilight_lock = threading.RLock()
        self._controle_direto_lock = threading.RLock()
        self._modo_controle_selecionado = "manual"
        self._controle_lampada_ligada: bool | None = None
        self._controle_lampada_selecao: str | None = None
        self._alvos_modo = self._carregar_alvos_modo()
        self._cor_teclado_boost = self._carregar_cor_teclado_boost()
        self._ultimo_comando_abajur_falho: str | None = None
        self._independent = False
        self._devices = device_defaults()
        self._device_errors: dict[str, str] = {}
        self._flash_outputs: dict[str, object] = {}
        self._flash_only: dict[str, object] = {}
        self._keyboard_native_output: object | None = None
        self._active_preset: str | None = None
        self._presets = Presets(self._arquivo_preferencias_controle().with_name("device_presets.json"))
        self.dispatcher = criar_dispatcher(self)
        self.conversa.registry = self.dispatcher.registry
        self.conversa.preferir_modelo = True

    @staticmethod
    def _alvos_padrao() -> dict[str, dict[str, bool]]:
        return {
            "rpm": {"lamp": True, "keyboard": False, "controller": True, "mobile": True},
            "beamng": {"lamp": True, "keyboard": True, "controller": False, "mobile": True},
            "ambilight_rpm": {"lamp": True, "keyboard": True, "controller": True, "mobile": True},
            "boost": {"lamp": True, "keyboard": True, "controller": True, "mobile": True},
            "ambilight": {"lamp": True, "keyboard": True, "controller": False, "mobile": False},
            "music": {"lamp": True, "keyboard": False, "controller": False, "mobile": False},
            "torch": {"lamp": True, "keyboard": False, "controller": False, "mobile": False},
        }

    @staticmethod
    def _alvos_disponiveis() -> dict[str, set[str]]:
        return {
            "rpm": {"lamp", "controller", "mobile"},
            "beamng": {"lamp", "keyboard", "controller", "mobile"},
            "ambilight_rpm": {"lamp", "keyboard", "controller", "mobile"},
            "boost": {"lamp", "keyboard", "controller", "mobile"},
            "ambilight": {"lamp", "keyboard", "controller"},
            "music": {"lamp"},
            "torch": {"lamp"},
        }

    @staticmethod
    def _arquivo_alvos_modo() -> Path:
        raiz = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Nebula"
        return raiz / "control_targets.json"

    def _carregar_alvos_modo(self) -> dict[str, dict[str, bool]]:
        alvos = self._alvos_padrao()
        try:
            dados = json.loads(self._arquivo_alvos_modo().read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return alvos
        if not isinstance(dados, dict):
            return alvos
        for modo, configuracao in alvos.items():
            salvo = dados.get(modo)
            if isinstance(salvo, dict):
                for dispositivo in configuracao:
                    if isinstance(salvo.get(dispositivo), bool):
                        configuracao[dispositivo] = salvo[dispositivo]
        return alvos

    def _salvar_alvos_modo(self) -> None:
        arquivo = self._arquivo_alvos_modo()
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._alvos_modo, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporario.replace(arquivo)

    @staticmethod
    def _arquivo_preferencias_controle() -> Path:
        raiz = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Nebula"
        return raiz / "control_preferences.json"

    @staticmethod
    def _cor_rgb(valor: object) -> tuple[int, int, int]:
        if not isinstance(valor, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", valor.strip()):
            raise ValueError("Use uma cor no formato #RRGGBB.")
        hexadecimal = valor.strip().lstrip("#")
        cor = tuple(int(hexadecimal[indice:indice + 2], 16) for indice in (0, 2, 4))
        if not any(cor):
            raise ValueError("Escolha uma cor visivel para o teclado.")
        return cor  # type: ignore[return-value]

    @staticmethod
    def _cor_hex(cor: tuple[int, int, int]) -> str:
        return "#" + "".join(f"{canal:02X}" for canal in cor)

    def _carregar_cor_teclado_boost(self) -> tuple[int, int, int]:
        padrao = (0, 80, 255)
        try:
            dados = json.loads(
                self._arquivo_preferencias_controle().read_text(encoding="utf-8")
            )
            if not isinstance(dados, dict):
                return padrao
            return self._cor_rgb(dados.get("boost_keyboard_color"))
        except (OSError, ValueError, TypeError):
            return padrao

    def _salvar_cor_teclado_boost(self) -> None:
        arquivo = self._arquivo_preferencias_controle()
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        dados: dict[str, object] = {}
        try:
            carregados = json.loads(arquivo.read_text(encoding="utf-8"))
            if isinstance(carregados, dict):
                dados.update(carregados)
        except (OSError, ValueError, TypeError):
            pass
        dados["boost_keyboard_color"] = self._cor_hex(self._cor_teclado_boost)
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(arquivo)

    def _alvo_ativo(self, modo: str, dispositivo: str) -> bool:
        if self._independent:
            return self._devices[dispositivo]["mode"] == modo
        return bool(self._alvos_modo.get(modo, {}).get(dispositivo, False))

    def _aplicar_dispositivos(self, configuracao: object) -> None:
        """Reconfigura somente produtores cujos dispositivos mudaram."""
        from copy import deepcopy
        novo = validate_devices(configuracao)
        antigo = deepcopy(self._devices)
        primeira = not self._independent
        alterados = {d for d in DEVICE_MODES if novo[d] != antigo[d] or d in self._device_errors}

        # Efeitos nativos do Kumara mantêm o handle HID aberto para que
        # TecladoKumaraUSB.close() não restaure o modo Reactive imediatamente.
        # Ao trocar qualquer ajuste do teclado, encerramos o handle anterior.
        if "keyboard" in alterados and self._keyboard_native_output is not None:
            native_output = self._keyboard_native_output
            self._keyboard_native_output = None

            # Quando afterfire está ativo, o mesmo objeto também fica em
            # _flash_only e será fechado logo abaixo.
            if native_output is not self._flash_only.get("keyboard"):
                try:
                    native_output.close()
                except (OSError, OpenRGBKeyboardError, AttributeError):
                    pass

        for device in alterados:
            output = self._flash_only.pop(device, None)
            if output is not None:
                output.close()
            self._flash_outputs.pop(device, None)
        finais = {"rpm": self._encerrar_modo_rpm, "boost": self._encerrar_modo_boost,
                  "ambilight": self._encerrar_modo_ambilight,
                  "beamng": self._encerrar_modo_ambilight}
        afetados = {c["mode"] for d in alterados for c in (antigo[d], novo[d])} & finais.keys()
        if primeira:
            afetados |= {c["mode"] for c in novo.values()} & finais.keys()
            for encerrar in finais.values():
                encerrar()
            if self._controle_abajur is not None:
                self._controle_abajur.parar_ritmo_navegador()
                self._controle_abajur.parar_modo_tocha()
        else:
            for modo in afetados:
                finais[modo]()
        self._independent = True
        self._devices = novo
        self._active_preset = None
        for device in alterados:
            self._device_errors.pop(device, None)
        if "lamp" in alterados:
            try:
                lamp = self._obter_controle_abajur()
                lamp.parar_ritmo_navegador()
                lamp.parar_modo_tocha()
                settings = novo["lamp"]
                if "color" in settings:
                    color = settings["color"]
                    if color.startswith("#"):
                        lamp.rgb(*tuple(int(color[i:i+2], 16) for i in (1, 3, 5)))
                    else:
                        lamp.cor(color)
                elif "temperature" in settings:
                    lamp.temperatura(settings["temperature"])
                if "brightness" in settings:
                    lamp.brilho(settings["brightness"])
                if "power" in settings:
                    lamp.energia(settings["power"])
                if settings["mode"] == "music":
                    lamp.iniciar_ritmo_navegador()
                elif settings["mode"] == "torch":
                    lamp.iniciar_modo_tocha()
                if settings.get("afterfire"):
                    from exhaust_flash import ExhaustFlash
                    flash_lamp = ExhaustFlash(lamp, lamp=True, close_device=False)
                    self._flash_only["lamp"] = flash_lamp
                    self._flash_outputs["lamp"] = flash_lamp
                    if settings.get("color", "").startswith("#"):
                        color = settings["color"]
                        flash_lamp.rgb(*tuple(int(color[i:i+2], 16) for i in (1, 3, 5)))
            except (ErroAbajur, OSError) as exc:
                self._device_errors["lamp"] = str(exc)
        if "color" in novo["keyboard"]:
            self._cor_teclado_boost = self._cor_rgb(novo["keyboard"]["color"])

        # Modos nativos do firmware EVision do Kumara.
        #
        # "static" usa o caminho de cor uniforme. Os demais são enviados uma
        # única vez por efeito_nativo(), deixando a animação a cargo do próprio
        # firmware do teclado. Isso evita reescrever os 126 LEDs continuamente.
        if "keyboard" in alterados and novo["keyboard"]["mode"] in KEYBOARD_EFFECTS:
            keyboard_settings = novo["keyboard"]
            keyboard_mode = str(keyboard_settings["mode"])
            keyboard = None
            output = None

            try:
                keyboard = criar_teclado_kumara()
                output = keyboard

                cor = (
                    self._cor_rgb(keyboard_settings["color"])
                    if "color" in keyboard_settings
                    else self._cor_teclado_boost
                )

                if keyboard_settings.get("afterfire"):
                    from exhaust_flash import ExhaustFlash

                    output = ExhaustFlash(keyboard, keyboard=True)
                    self._flash_only["keyboard"] = output
                    self._flash_outputs["keyboard"] = output

                if keyboard_mode == "static":
                    output.enviar_rgb(*cor)
                else:
                    efeito_nativo = getattr(output, "efeito_nativo", None)
                    if not callable(efeito_nativo):
                        raise OpenRGBKeyboardError(
                            "Os efeitos nativos exigem o backend USB EVision do Kumara."
                        )

                    # ExhaustFlash precisa saber qual é o efeito base para
                    # restaurá-lo depois de um flash de escapamento.
                    registrar_base = getattr(output, "_output", None)
                    if keyboard_settings.get("afterfire") and callable(registrar_base):
                        registrar_base("efeito_nativo", keyboard_mode, cor)
                    else:
                        efeito_nativo(keyboard_mode, cor)

                self._keyboard_native_output = output

            except (OSError, OpenRGBKeyboardError, ValueError, RuntimeError) as exc:
                self._device_errors["keyboard"] = str(exc)

                if output is not None:
                    if self._flash_only.get("keyboard") is output:
                        self._flash_only.pop("keyboard", None)
                    if self._flash_outputs.get("keyboard") is output:
                        self._flash_outputs.pop("keyboard", None)

                alvo_fechar = output if output is not None else keyboard
                if alvo_fechar is not None:
                    try:
                        alvo_fechar.close()
                    except Exception:
                        pass

                self._keyboard_native_output = None

        iniciais = {"rpm": self._iniciar_modo_rpm, "boost": self._iniciar_modo_boost,
                    "ambilight": self._iniciar_modo_ambilight,
                    "beamng": lambda: self._iniciar_modo_ambilight(profile="beamng")}
        for modo in sorted(afetados):
            participantes = [d for d in DEVICE_MODES if novo[d]["mode"] == modo]
            if not participantes:
                continue
            try:
                iniciais[modo]()
                engine = (
                    self._modo_ambilight
                    if modo == "beamng"
                    else getattr(self, "_modo_" + modo)
                )
                if engine is None or not engine.ativo:
                    raise ErroAbajur(f"Não foi possível iniciar {modo}.")
                status = engine.status()
                for device in participantes:
                    key = {"lamp": "erro_abajur", "keyboard": "erro_teclado", "controller": "erro_controle", "mobile": "erro"}[device]
                    if status.get(key):
                        self._device_errors[device] = str(status[key])
            except (ErroAbajur, OSError, ValueError) as exc:
                for device in participantes:
                    self._device_errors[device] = str(exc)
        for device in alterados & {"keyboard", "controller"}:
            if novo[device]["mode"] == "manual" and novo[device].get("afterfire"):
                try:
                    output = self._teclado_independente() if device == "keyboard" else self._controle_independente()
                    self._flash_only[device] = output
                    (output.enviar_rgb if device == "keyboard" else output.set_rgb)(0, 0, 0)
                except (OSError, OpenRGBKeyboardError, DS4LightbarError) as exc:
                    self._device_errors[device] = str(exc)
        self._modo_controle_selecionado = "independent"

    def _com_flash(self, device, output):
        if self._independent and self._devices[device].get("afterfire"):
            from exhaust_flash import ExhaustFlash
            existing = self._flash_outputs.get(device)
            if existing is not None and getattr(existing, "device", None) is output:
                return existing
            output = ExhaustFlash(
                output,
                keyboard=device == "keyboard",
                lamp=device == "lamp",
                close_device=device != "lamp",
            )
            self._flash_outputs[device] = output
        return output

    def _teclado_independente(self):
        return self._com_flash("keyboard", criar_teclado_kumara())

    def _controle_independente(self):
        return self._com_flash("controller", DS4Lightbar())

    def _controle_dispositivo(self, acao: str, valor: object) -> str:
        from copy import deepcopy
        if acao == "preset.save":
            name = self._presets.save(valor, self._devices)
            return f"Preset {name} salvo."
        if acao == "preset.delete":
            self._presets.delete(valor)
            if self._active_preset == valor:
                self._active_preset = None
            return "Preset excluído."
        if acao == "preset.apply":
            self._aplicar_dispositivos(self._presets.get(valor))
            if not self._device_errors:
                self._active_preset = self._presets.resolve(valor)
            return "Preset aplicado." if not self._device_errors else "Preset aplicado parcialmente; confira os dispositivos."
        if not isinstance(valor, dict) or valor.get("device") not in DEVICE_MODES:
            raise ValueError("Selecione um dispositivo válido.")
        novo = deepcopy(self._devices)
        device = valor["device"]
        if acao == "device.flash":
            if device not in {"lamp", "keyboard", "controller"} or type(valor.get("enabled")) is not bool:
                raise ValueError("Selecione o flash do abajur, teclado ou controle.")
            novo[device]["afterfire"] = valor["enabled"]
        else:
            requested_mode = valor.get("mode")
            if requested_mode == "beamng":
                for paired in ("lamp", "keyboard"):
                    novo[paired]["mode"] = "beamng"
                novo["lamp"]["power"] = True
            else:
                if novo[device].get("mode") == "beamng":
                    for paired in ("lamp", "keyboard"):
                        if novo[paired].get("mode") == "beamng":
                            novo[paired]["mode"] = "manual"
                novo[device]["mode"] = requested_mode
        if device == "lamp" and novo[device]["mode"] != "manual":
            novo[device]["power"] = True
        self._aplicar_dispositivos(novo)
        return "Modo do dispositivo atualizado." if not self._device_errors else "Confira o estado dos dispositivos."

    @property
    def modo_mudo(self) -> bool:
        return self._saida_silenciavel.muda

    def definir_modo_mudo(self, ativado: bool) -> bool:
        """Silencia apenas a voz; comandos, microfone e automacoes continuam ativos."""
        self._saida_silenciavel.definir_muda(bool(ativado))
        return self.modo_mudo

    def estado_controle(self) -> dict[str, object]:
        """Snapshot leve para os paineis desktop e celular."""
        with self._modo_rpm_lock:
            rpm = self._modo_rpm
        with self._modo_boost_lock:
            boost = self._modo_boost
        with self._modo_ambilight_lock:
            ambilight = self._modo_ambilight

        telemetria: dict[str, object] = {}
        modo_hibrido = (
            rpm is not None
            and ambilight is not None
            and self._modo_controle_selecionado in {"beamng", "ambilight_rpm"}
        )
        if modo_hibrido:
            telemetria = rpm.status()
            modo = self._modo_controle_selecionado
            for key in ("cor", "cor_secundaria", "zonas_teclado", "teclado", "erro_teclado", "erro_controle"):
                telemetria[key] = ambilight.status().get(key)
        elif rpm is not None:
            telemetria = rpm.status()
            modo = "rpm"
        elif boost is not None:
            telemetria = boost.status()
            modo = "boost"
        elif ambilight is not None:
            telemetria = ambilight.status()
            modo = "ambilight"
        else:
            modo = self._modo_controle_selecionado
        alvos = dict(self._alvos_modo.get(modo, {}))
        tem_rpm = rpm is not None if self._independent else modo in {"rpm", "beamng", "ambilight_rpm"}
        if self._independent and rpm is not None:
            telemetria = rpm.status()
        if self._independent:
            modo = "independent"
        from copy import deepcopy
        devices = deepcopy(self._devices)
        for device, settings in devices.items():
            settings["error"] = self._device_errors.get(device)
            flash = self._flash_outputs.get(device)
            if flash is not None:
                settings["error"] = settings["error"] or flash.error
            engine = (
                self._modo_ambilight
                if settings["mode"] == "beamng"
                else getattr(self, "_modo_" + settings["mode"], None)
            )
            if engine is not None:
                status = engine.status()
                key = {"lamp": "erro_abajur", "keyboard": "erro_teclado", "controller": "erro_controle", "mobile": "erro"}[device]
                settings["error"] = settings["error"] or status.get(key) or status.get("erro")
        return {
            "devices": devices,
            "device_modes": DEVICE_MODES,
            "presets": sorted(self._presets.items, key=str.casefold),
            "active_preset": self._active_preset,
            "ready": True,
            "muted": self.modo_mudo,
            "mode": modo,
            "rpm": telemetria.get("rpm") if tem_rpm else None,
            "rpm_percent": telemetria.get("percentual") if tem_rpm else None,
            "gear": telemetria.get("marcha") if tem_rpm else None,
            "throttle_percent": (
                telemetria.get("acelerador_percentual") if tem_rpm else None
            ),
            "min_rpm": telemetria.get("rpm_minimo") if tem_rpm else None,
            "redline_rpm": telemetria.get("rpm_corte") if tem_rpm else None,
            "max_rpm": telemetria.get("rpm_maximo") if tem_rpm else None,
            "shifting": telemetria.get("trocando_marcha") if tem_rpm else False,
            "speed_kmh": telemetria.get("velocidade_kmh") if tem_rpm else None,
            "turbo_bar": telemetria.get("turbo_bar") if tem_rpm else None,
            "oil_pressure": telemetria.get("pressao_oleo") if tem_rpm else None,
            "oil_temp": telemetria.get("temperatura_oleo") if tem_rpm else None,
            "fuel_percent": (
                telemetria.get("combustivel_percentual") if tem_rpm else None
            ),
            "water_temp": telemetria.get("temperatura_agua") if tem_rpm else None,
            "engine_map": telemetria.get("mapa_motor") if tem_rpm else None,
            "telemetry_source": telemetria.get("fonte") if tem_rpm else None,
            "boost": boost.status().get("boost") if boost is not None else None,
            "boost_percent": boost.status().get("boost") if boost is not None else None,
            "boost_receiving": bool(boost and boost.status().get("recebendo")),
            "boost_valid": bool(boost and boost.status().get("telemetria_valida")),
            "range": telemetria.get("faixa") if tem_rpm else None,
            "receiving": bool(telemetria.get("recebendo", False)),
            "telemetry_valid": bool(telemetria.get("telemetria_valida", False)),
            "lamp": telemetria.get("abajur", "controle manual"),
            "keyboard": telemetria.get("teclado", "fora do efeito"),
            "effect_color": telemetria.get("cor"),
            "keyboard_color": telemetria.get("cor_secundaria"),
            "keyboard_zones": telemetria.get("zonas_teclado"),
            "boost_keyboard_color": self._cor_hex(self._cor_teclado_boost),
            "lamp_power": self._controle_lampada_ligada,
            "lamp_selection": self._controle_lampada_selecao,
            "air": self._controle_ar.estado(),
            "targets": alvos,
            "target_available": sorted(self._alvos_disponiveis().get(modo, set())),
            "target_mode": modo,
            "error": telemetria.get("erro") or telemetria.get("erro_abajur") or telemetria.get("erro_teclado") or telemetria.get("erro_controle"),
        }

    def executar_controle(
        self,
        acao: str,
        valor: object | None = None,
    ) -> dict[str, object]:
        """Executa botoes do painel sem criar uma conversa nem emitir voz."""
        acao = str(acao).strip().casefold()
        with self._controle_direto_lock, self._saida_silenciavel.silenciar_temporariamente():
            if acao in {"device.mode", "device.flash"} or acao.startswith("preset."):
                if acao not in {"device.mode", "device.flash", "preset.save", "preset.apply", "preset.delete"}:
                    raise ValueError("Ação de preset inválida.")
                mensagem = self._controle_dispositivo(acao, valor)
            elif acao == "mute":
                self.definir_modo_mudo(bool(valor))
                mensagem = "Modo mudo ativado." if self.modo_mudo else "Voz da Nebula ativada."
            elif acao == "boost.keyboard_color":
                self._cor_teclado_boost = self._cor_rgb(valor)
                self._salvar_cor_teclado_boost()
                if self._independent:
                    from copy import deepcopy
                    novo = deepcopy(self._devices)
                    novo["keyboard"]["color"] = str(valor)
                    self._aplicar_dispositivos(novo)
                boost_ativo = not self._independent and self.estado_controle()["mode"] == "boost"
                if boost_ativo:
                    self.executar_controle("mode", "manual")
                    self.executar_controle("mode", "boost")
                mensagem = "Cor do teclado no modo boost atualizada."
            elif acao == "mode.target":
                if not isinstance(valor, dict):
                    raise ValueError("O alvo do modo precisa ser um objeto.")
                modo = str(valor.get("mode") or self.estado_controle()["mode"]).strip().casefold()
                dispositivo = str(valor.get("device") or "").strip().casefold()
                if modo not in self._alvos_modo or dispositivo not in self._alvos_disponiveis().get(modo, set()):
                    raise ValueError("Dispositivo ou modo invalido.")
                self._alvos_modo[modo][dispositivo] = bool(valor.get("enabled"))
                self._salvar_alvos_modo()
                if dispositivo != "mobile" and self.estado_controle()["mode"] == modo:
                    self.executar_controle("mode", "manual")
                    self.executar_controle("mode", modo)
                mensagem = "Dispositivo incluido no efeito." if self._alvos_modo[modo][dispositivo] else "Dispositivo removido do efeito."
            elif acao == "mode":
                if self._independent:
                    from copy import deepcopy
                    novo = deepcopy(self._devices)
                    for device in novo:
                        if valor == "manual" or valor in DEVICE_MODES[device]:
                            novo[device]["mode"] = valor
                    self._aplicar_dispositivos(novo)
                    return {"ok": True, "message": "Modos atualizados.", "state": self.estado_controle()}
                modo = str(valor or "").strip().casefold()
                comandos = {
                    "rpm": "ative o modo rpm",
                    "boost": "ative o modo boost",
                    "ambilight": "ative o modo ambilight",
                    "music": "ative o modo musica do abajur",
                    "torch": "ative o modo tocha",
                }
                if modo == "manual":
                    self._encerrar_modo_rpm()
                    self._encerrar_modo_boost()
                    self._encerrar_modo_ambilight()
                    try:
                        controle = self._obter_controle_abajur()
                        controle.parar_ritmo_navegador()
                        controle.parar_modo_tocha()
                    except (ErroAbajur, OSError, AttributeError):
                        pass
                    self._modo_controle_selecionado = "manual"
                elif modo in {"beamng", "ambilight_rpm"}:
                    self._encerrar_modo_rpm()
                    self._encerrar_modo_boost()
                    self._encerrar_modo_ambilight()
                    self._modo_controle_selecionado = modo
                    try:
                        controle = self._obter_controle_abajur()
                        controle.parar_ritmo_navegador()
                        controle.parar_modo_tocha()
                    except (ErroAbajur, OSError, AttributeError):
                        pass
                    self._iniciar_modo_rpm(hibrido=True)
                    self._iniciar_modo_ambilight(hibrido=True)
                    with self._modo_rpm_lock, self._modo_ambilight_lock:
                        hibrido_ativo = (
                            self._modo_rpm is not None
                            and self._modo_rpm.ativo
                            and self._modo_ambilight is not None
                            and self._modo_ambilight.ativo
                        )
                    if not hibrido_ativo:
                        self._encerrar_modo_rpm()
                        self._encerrar_modo_ambilight()
                        self._modo_controle_selecionado = "manual"
                        raise ErroAbajur("Nao foi possivel ativar telemetria e Ambilight juntos.")
                elif modo in comandos:
                    self._encerrar_modo_rpm()
                    self._encerrar_modo_boost()
                    self._encerrar_modo_ambilight()
                    # Nao deixe uma selecao anterior mascarar uma falha ao
                    # reiniciar o mesmo modo. O estado so volta ao modo pedido
                    # quando o controlador correspondente realmente existir.
                    self._modo_controle_selecionado = "manual"
                    try:
                        controle = self._obter_controle_abajur()
                        controle.parar_ritmo_navegador()
                        controle.parar_modo_tocha()
                    except (ErroAbajur, OSError, AttributeError):
                        pass
                    self.executar(comandos[modo])
                    estado = self.estado_controle()
                    if modo in {"rpm", "boost", "ambilight"} and estado["mode"] != modo:
                        raise ErroAbajur(f"Nao foi possivel ativar o modo {modo}.")
                    self._modo_controle_selecionado = modo
                else:
                    raise ValueError("Modo de iluminacao invalido.")
                mensagem = f"Modo {modo} selecionado."
            elif acao in {"lamp.power", "lamp.color", "lamp.temperature", "lamp.brightness"}:
                if not self._independent:
                    self._aplicar_dispositivos(self._devices)
                if self._independent:
                    from copy import deepcopy
                    novo = deepcopy(self._devices)
                    novo["lamp"]["mode"] = "manual"
                    field = acao.split(".")[1]
                    novo["lamp"][field] = valor
                    if field == "color":
                        novo["lamp"].pop("temperature", None)
                        novo["lamp"]["power"] = True
                    elif field == "temperature":
                        novo["lamp"].pop("color", None)
                        novo["lamp"]["power"] = True
                    self._aplicar_dispositivos(novo)
                    if "lamp" in self._device_errors:
                        raise ErroAbajur(self._device_errors["lamp"])
                    self._controle_lampada_ligada = novo["lamp"].get("power")
                    self._controle_lampada_selecao = novo["lamp"].get("color", novo["lamp"].get("temperature"))
                    return {"ok": True, "message": "Abajur atualizado.", "state": self.estado_controle()}
                self._encerrar_modo_rpm()
                self._encerrar_modo_boost()
                self._encerrar_modo_ambilight()
                if acao == "lamp.power":
                    comando_abajur = (
                        "ligue o abajur" if bool(valor) else "desligue o abajur"
                    )
                elif acao == "lamp.color":
                    if isinstance(valor, str) and valor.startswith("#"):
                        self._cor_rgb(valor)
                        comando_abajur = f"deixe o abajur hexadecimal {valor[1:]}"
                    else:
                        comando_abajur = f"coloque o abajur na cor {valor}"
                elif acao == "lamp.temperature":
                    comando_abajur = f"coloque o abajur na luz {valor}"
                else:
                    comando_abajur = (
                        f"coloque o brilho do abajur em {int(valor)} por cento"
                    )
                self._executar_comando_abajur(comando_abajur)
                if self._ultimo_comando_abajur_falho:
                    raise ErroAbajur("O abajur nao respondeu ao comando.")
                self._modo_controle_selecionado = "manual"
                if acao == "lamp.power":
                    self._controle_lampada_ligada = bool(valor)
                elif acao in {"lamp.color", "lamp.temperature"}:
                    self._controle_lampada_ligada = True
                    self._controle_lampada_selecao = str(valor)
                mensagem = "Comando enviado ao abajur."
            elif acao in {"air.power", "air.temperature", "air.mode", "air.fan"}:
                resultado_ar = self._controle_ar.executar(acao.removeprefix("air."), valor)
                mensagem = str(resultado_ar.get("message", "Comando enviado ao ar."))
            else:
                raise ValueError("Acao de controle invalida.")
        return {"ok": True, "message": mensagem, "state": self.estado_controle()}

    def _rastrear_resposta(self, texto: str) -> None:
        self._ultima_pergunta = self._pergunta_em_processamento
        self._ultima_resposta = texto.strip()
        self._ultima_resposta_id = f"nebula-{time.time_ns()}"

    def _obter_controle_abajur(self) -> ControleAbajur:
        """Obtém uma única conexão Tuya LAN, sem recorrer ao celular/ADB."""
        with self._controle_abajur_lock:
            if self._controle_abajur is None:
                configuracao = ConfiguracaoTuya.carregar()
                if configuracao is None:
                    raise ErroAbajur(
                        "Abra a aba Configuração da Nebula e informe a local key "
                        "Tuya para controlar a luz direto pelo Wi-Fi, sem celular."
                    )
                self._controle_abajur = ControleAbajurTuya(configuracao)
            return self._controle_abajur

    def reconfigurar_abajur(self, configuracao: ConfiguracaoTuya) -> None:
        """Troca as credenciais LAN usadas após a tela de configuração salvar."""
        configuracao.validar()
        self._encerrar_modo_rpm()
        self._encerrar_modo_boost()
        self._encerrar_modo_ambilight()
        novo_controle = ControleAbajurTuya(configuracao)
        with self._controle_abajur_lock:
            anterior = self._controle_abajur
            if anterior is not None:
                try:
                    anterior.parar_ritmo_navegador()
                except (ErroAbajur, OSError):
                    # A configuração nova não deve ficar presa a uma conexão
                    # anterior que já caiu ou deixou de responder.
                    pass
            self._controle_abajur = novo_controle
            self._ultimo_comando_abajur_falho = None

    def _encerrar_modo_rpm(self) -> tuple[bool, str | None]:
        """Para e desvincula o modo sem emitir fala; pode ser chamado novamente."""
        with self._modo_rpm_lock:
            modo = self._modo_rpm
            if modo is None:
                return False, None
            self._modo_rpm = None
        modo.parar()
        with self._controle_abajur_lock:
            controle = self._controle_abajur
            if isinstance(controle, ControleAbajurTuya):
                controle.liberar_animacao_externa(modo)
        return True, modo.erro

    def _iniciar_modo_rpm(self, *, hibrido: bool = False) -> None:
        with self._modo_rpm_lock:
            existente = self._modo_rpm
        if existente is not None and existente.ativo:
            self.saida.falar("O modo RPM já está ativo.")
            return
        if existente is not None:
            self._encerrar_modo_rpm()
        if not self._independent:
            self._encerrar_modo_boost()
            if not hibrido:
                self._encerrar_modo_ambilight()

        modo_alvos = self._modo_controle_selecionado if hibrido else "rpm"
        usar_abajur = False if hibrido else self._alvo_ativo(modo_alvos, "lamp")
        usar_controle = False if modo_alvos == "ambilight_rpm" else self._alvo_ativo(modo_alvos, "controller")
        controle_tuya: ControleAbajurTuya | None = None
        aviso_abajur: str | None = None
        try:
            if not usar_abajur:
                raise ErroAbajur("desativado nas chaves de dispositivos")
            configuracao = ConfiguracaoTuya.carregar()
            if configuracao is None:
                aviso_abajur = (
                    "a configuração Tuya ainda não tem uma local key; "
                    "abra a aba Configuração"
                )
            else:
                controle = self._obter_controle_abajur()
                if isinstance(controle, ControleAbajurTuya):
                    controle_tuya = controle
                else:
                    aviso_abajur = "o backend ativo não é o controle Tuya LAN"
        except (ErroAbajur, OSError) as exc:
            aviso_abajur = str(exc)

        argumentos_rpm: dict[str, object] = {}
        if self._independent and usar_controle:
            argumentos_rpm["fabrica_lightbar"] = self._controle_independente
        if not usar_controle:
            argumentos_rpm["fabrica_lightbar"] = None
        modo = ModoRPM(
            saida_abajur=(
                controle_tuya.enviar_rgb_animacao
                if controle_tuya is not None
                else None
            ),
            **argumentos_rpm,
        )
        if controle_tuya is not None:
            try:
                controle_tuya.preparar_animacao_externa(modo)
            except (ErroAbajur, OSError) as exc:
                aviso_abajur = str(exc)
                controle_tuya = None
                modo = ModoRPM(**argumentos_rpm)
        try:
            modo.iniciar()
        except (ErroModoRPM, OSError) as exc:
            if controle_tuya is not None:
                controle_tuya.liberar_animacao_externa(modo)
            modo.parar()
            if not usar_controle:
                self.saida.falar(f"Não consegui ativar o modo RPM. {exc}")
                return
            # O painel do celular e o abajur não dependem de haver um DS4
            # conectado. Se a lightbar falhar, mantenha a telemetria ativa e
            # deixe apenas o controle fora do efeito.
            aviso_controle = str(exc)
            modo = ModoRPM(
                saida_abajur=(
                    controle_tuya.enviar_rgb_animacao
                    if controle_tuya is not None
                    else None
                ),
                fabrica_lightbar=None,
            )
            try:
                modo.iniciar()
            except (ErroModoRPM, OSError) as retry_exc:
                if controle_tuya is not None:
                    controle_tuya.liberar_animacao_externa(modo)
                modo.parar()
                self.saida.falar(f"Não consegui ativar o modo RPM. {retry_exc}")
                return
        else:
            aviso_controle = None
        with self._modo_rpm_lock:
            self._modo_rpm = modo

        controle_ativo = usar_controle and aviso_controle is None
        if self._independent:
            if usar_abajur and controle_tuya is None:
                self._device_errors["lamp"] = aviso_abajur or "Abajur indisponível."
            if usar_controle and not controle_ativo:
                self._device_errors["controller"] = aviso_controle or "Controle indisponível."
        detalhe_controle = f" O controle ficou de fora: {aviso_controle}." if aviso_controle else ""
        if controle_tuya is not None and controle_ativo:
            self.saida.falar(
                "Modo RPM genérico ativado no controle e no abajur. "
                "As luzes vão acompanhar o giro quando uma ponte compatível, como a do SimHub, enviar dados."
            )
        elif controle_tuya is not None:
            self.saida.falar(
                "Modo RPM ativado no abajur e no painel do celular; aguardando a telemetria do jogo."
                + detalhe_controle
            )
        elif controle_ativo:
            detalhe = f" {aviso_abajur}." if aviso_abajur else ""
            self.saida.falar(
                "Modo RPM genérico ativado no controle; aguardando a telemetria do jogo. "
                f"O abajur ficou de fora.{detalhe}"
            )
        else:
            detalhe = f" {aviso_abajur}." if aviso_abajur else ""
            self.saida.falar(
                "Modo RPM ativado para o painel do celular; aguardando a telemetria do jogo. "
                f"O abajur ficou de fora.{detalhe}{detalhe_controle}"
            )

    def _parar_modo_rpm(self) -> None:
        existia, erro = self._encerrar_modo_rpm()
        if not existia:
            self.saida.falar("O modo RPM já está desligado.")
        elif erro:
            self.saida.falar(f"Modo RPM desligado. Antes de parar, houve uma falha: {erro}")
        else:
            self.saida.falar("Modo RPM desligado.")

    def _informar_status_modo_rpm(self) -> None:
        with self._modo_rpm_lock:
            modo = self._modo_rpm
        if modo is None:
            self.saida.falar("O modo RPM está desligado.")
            return
        status = modo.status()
        if not status["ativo"]:
            detalhe = status.get("erro") or "a telemetria foi encerrada"
            self.saida.falar(f"O modo RPM não está ativo: {detalhe}.")
        elif not status["recebendo"]:
            self.saida.falar(
                "O modo RPM está ativo no controle, mas ainda aguarda uma ponte de telemetria compatível."
            )
        elif not status["telemetria_valida"]:
            self.saida.falar(
                "O jogo está conectado, mas ainda não há um carro controlável carregado."
            )
        else:
            rpm = status["rpm"]
            faixa = status["faixa"]
            abajur = status["abajur"]
            self.saida.falar(
                f"Modo RPM ativo: {rpm} RPM, faixa {faixa}; abajur {abajur}."
            )

    def _encerrar_modo_boost(self) -> tuple[bool, str | None]:
        """Para o modo boost e devolve a reserva da lâmpada."""
        with self._modo_boost_lock:
            modo = self._modo_boost
            leitor = self._leitor_boost_visual
            if modo is None and leitor is None:
                return False, None
            self._modo_boost = None
            self._leitor_boost_visual = None
        if leitor is not None:
            leitor.parar()
        if modo is None:
            return True, leitor.erro if leitor is not None else None
        modo.parar()
        with self._controle_abajur_lock:
            controle = self._controle_abajur
            if isinstance(controle, ControleAbajurTuya):
                controle.liberar_animacao_externa(modo)
        return True, modo.erro or (leitor.erro if leitor is not None else None)

    def _iniciar_modo_boost(self) -> None:
        with self._modo_boost_lock:
            existente = self._modo_boost
        if existente is not None and existente.ativo:
            self.saida.falar("O modo boost já está ativo.")
            return
        if existente is not None:
            self._encerrar_modo_boost()
        if not self._independent:
            self._encerrar_modo_rpm()
            self._encerrar_modo_ambilight()

        usar_abajur = self._alvo_ativo("boost", "lamp")
        usar_controle = self._alvo_ativo("boost", "controller")
        usar_teclado = self._alvo_ativo("boost", "keyboard")
        controle: ControleAbajurTuya | None = None
        try:
            if not usar_abajur:
                raise ErroAbajur("abajur desativado nas chaves de dispositivos")
            configuracao = ConfiguracaoTuya.carregar()
            if configuracao is None:
                raise ErroAbajur(
                    "Configure a local key da lâmpada na aba Configuração primeiro."
                )
            controle_candidato = self._obter_controle_abajur()
            if not isinstance(controle_candidato, ControleAbajurTuya):
                raise ErroAbajur("O modo boost precisa do controle Tuya pela rede local.")
            controle = controle_candidato
        except (ErroAbajur, OSError) as exc:
            if usar_abajur:
                self.saida.falar(f"Não consegui ativar o modo boost. {exc}")
                return

        fonte_boost = os.environ.get("NEBULA_BOOST_SOURCE", VISUAL_SOURCE).strip()
        if fonte_boost not in {VISUAL_SOURCE, "rocket_league"}:
            fonte_boost = VISUAL_SOURCE
        usar_leitor_visual = fonte_boost == VISUAL_SOURCE
        argumentos_boost: dict[str, object] = {
            "fabrica_teclado": self._teclado_independente if usar_teclado else None,
            "cor_teclado": self._cor_teclado_boost,
        }
        if not usar_controle:
            argumentos_boost["fabrica_lightbar"] = None
        elif self._independent:
            argumentos_boost["fabrica_lightbar"] = self._controle_independente
        modo = ModoBoost(
            controle.enviar_brilho_animacao if controle is not None else (lambda _brilho: None),
            fonte_esperada=fonte_boost,
            **argumentos_boost,
        )
        leitor = LeitorBoostVisual() if usar_leitor_visual else None
        try:
            if controle is not None:
                brilho_inicial = controle.preparar_animacao_externa(
                    modo,
                    preservar_perfil=True,
                )
                modo.definir_brilho_retorno(brilho_inicial)
                modo.definir_cor_controle(controle.cor_perfil_animacao())
            modo.iniciar()
            if leitor is not None:
                leitor.iniciar()
        except (ErroAbajur, ErroLeitorBoostVisual, ErroModoBoost, OSError, ValueError) as exc:
            if leitor is not None:
                leitor.parar()
            if controle is not None:
                controle.liberar_animacao_externa(modo)
            modo.parar()
            self.saida.falar(f"Não consegui ativar o modo boost. {exc}")
            return
        with self._modo_boost_lock:
            self._modo_boost = modo
            self._leitor_boost_visual = leitor
        status_saidas = modo.status()
        alvos = ["abajur"] if controle is not None else []
        if status_saidas.get("controle") == "conectado":
            alvos.append("controle")
        if status_saidas.get("teclado") == "conectado":
            alvos.append("teclado")
        descricao_alvos = ", ".join(alvos[:-1]) + (f" e {alvos[-1]}" if len(alvos) > 1 else (alvos[0] if alvos else "celular"))
        if usar_leitor_visual:
            self.saida.falar(
                f"Modo boost visual ativado no {descricao_alvos}. Mantenha o HUD do Rocket League visível; "
                "zero boost deixa 1% de brilho e boost cheio deixa 100%."
            )
        else:
            self.saida.falar(
                f"Modo boost pelo plugin offline ativado no {descricao_alvos}. Zero boost deixa 1% de brilho "
                "e boost cheio deixa 100%."
            )

    def _parar_modo_boost(self) -> None:
        existia, erro = self._encerrar_modo_boost()
        if not existia:
            self.saida.falar("O modo boost já está desligado.")
        elif erro:
            self.saida.falar(f"Modo boost desligado. Antes de parar, houve uma falha: {erro}")
        else:
            self.saida.falar("Modo boost desligado e perfil de iluminação anterior restaurado.")

    def _informar_status_modo_boost(self) -> None:
        with self._modo_boost_lock:
            modo = self._modo_boost
            leitor = self._leitor_boost_visual
        if modo is None:
            self.saida.falar("O modo boost está desligado.")
            return
        status = modo.status()
        status_leitor = leitor.status() if leitor is not None else {}
        if not status["ativo"]:
            detalhe = status.get("erro") or "a telemetria foi encerrada"
            self.saida.falar(f"O modo boost não está ativo: {detalhe}.")
        elif not status["recebendo"]:
            if leitor is None:
                self.saida.falar(
                    "O modo boost está ativo e aguarda o plugin NebulaBoost no treino offline."
                )
                return
            erro_leitor = status_leitor.get("erro")
            if erro_leitor:
                self.saida.falar(f"O leitor visual de boost encontrou uma falha: {erro_leitor}.")
            elif not status_leitor.get("janela"):
                self.saida.falar(
                    "O modo boost está ativo, mas o Rocket League está minimizado ou não foi encontrado."
                )
            else:
                self.saida.falar(
                    "O modo boost está ativo, mas ainda não conseguiu ler o aro de boost no HUD."
                )
        elif not status["telemetria_valida"]:
            self.saida.falar("O Rocket League está conectado, mas ainda não há um carro controlável.")
        else:
            self.saida.falar(
                f"Modo boost ativo: {status['boost']}% de boost e {status['brilho']}% de brilho."
            )

    def _encerrar_modo_ambilight(self) -> tuple[bool, str | None]:
        """Para o Ambilight, restaura o perfil e libera a lampada."""
        with self._modo_ambilight_lock:
            modo = self._modo_ambilight
            if modo is None:
                return False, None
            self._modo_ambilight = None
        modo.parar()
        with self._controle_abajur_lock:
            controle = self._controle_abajur
            if isinstance(controle, ControleAbajurTuya):
                controle.liberar_animacao_externa(modo)
        return True, modo.erro

    def _iniciar_modo_ambilight(
        self,
        *,
        hibrido: bool = False,
        profile: str | None = None,
    ) -> bool:
        with self._modo_ambilight_lock:
            existente = self._modo_ambilight
        if existente is not None and existente.ativo:
            self.saida.falar("O modo Ambilight ja esta ativo.")
            return True
        if existente is not None:
            self._encerrar_modo_ambilight()
        if not self._independent:
            if not hibrido:
                self._encerrar_modo_rpm()
            self._encerrar_modo_boost()

        modo_alvos = profile or (
            self._modo_controle_selecionado if hibrido else "ambilight"
        )
        usar_abajur = self._alvo_ativo(modo_alvos, "lamp")
        usar_teclado = self._alvo_ativo(modo_alvos, "keyboard")
        usar_controle = (not hibrido or modo_alvos == "ambilight_rpm") and self._alvo_ativo(modo_alvos, "controller")
        capturador = CapturadorJanelaNetflix("beamng") if modo_alvos == "beamng" else None
        controle: ControleAbajurTuya | None = None
        saida_abajur = None
        aviso_abajur: str | None = None
        try:
            if not usar_abajur:
                raise ErroAbajur("abajur desativado nas chaves de dispositivos")
            configuracao = ConfiguracaoTuya.carregar()
            if configuracao is None:
                raise ErroAbajur(
                    "Configure a local key da lampada na aba Configuracao primeiro."
                )
            controle_candidato = self._obter_controle_abajur()
            if not isinstance(controle_candidato, ControleAbajurTuya):
                raise ErroAbajur("O Ambilight precisa do controle Tuya pela rede local.")
            controle = controle_candidato
            saida_abajur = self._com_flash("lamp", controle)
        except (ErroAbajur, OSError) as exc:
            if usar_abajur:
                aviso_abajur = str(exc)

        teclado: TecladoKumaraOpenRGB | TecladoKumaraUSB | None = None
        aviso_teclado: str | None = None
        if usar_teclado:
            try:
                teclado = self._teclado_independente()
            except (OpenRGBKeyboardError, OSError) as exc:
                aviso_teclado = str(exc)
        saidas_teclado = selecionar_saidas_teclado(teclado)

        lightbar = None
        aviso_controle = None
        if usar_controle:
            try:
                lightbar = self._controle_independente()
            except (DS4LightbarError, OSError) as exc:
                aviso_controle = str(exc)

        if controle is None and teclado is None and lightbar is None:
            detalhes = ". ".join(
                detalhe for detalhe in (aviso_abajur, aviso_teclado, aviso_controle) if detalhe
            )
            sufixo = f" {detalhes}." if detalhes else ""
            self.saida.falar(
                "Nao consegui ativar o Ambilight em nenhum dispositivo." + sufixo
            )
            return False

        modo = ModoAmbilight(
            saida_abajur.enviar_rgb_animacao if saida_abajur is not None else (lambda _r, _g, _b: None),
            saida_secundaria=saidas_teclado.secundaria,
            saida_zonas=saidas_teclado.zonas,
            saida_controle=lightbar.set_rgb if lightbar is not None else None,
            capturador=capturador,
            profile="beamng" if modo_alvos == "beamng" else "default",
        )
        reservado = False
        try:
            brilho_inicial = 100
            if controle is not None:
                try:
                    brilho_inicial = controle.preparar_animacao_externa(
                        modo,
                        preservar_perfil=True,
                    )
                    reservado = True
                except (ErroAbajur, OSError) as exc:
                    aviso_abajur = str(exc)
                    controle = None
                    modo = ModoAmbilight(
                        lambda _r, _g, _b: None,
                        saida_secundaria=saidas_teclado.secundaria,
                        saida_zonas=saidas_teclado.zonas,
                        saida_controle=lightbar.set_rgb if lightbar is not None else None,
                        capturador=capturador,
                        profile="beamng" if modo_alvos == "beamng" else "default",
                    )
            def restaurar_ambilight() -> None:
                try:
                    if controle is not None and getattr(modo, "enviou_primeiro_quadro", True):
                        controle.restaurar_perfil_animacao(brilho_inicial)
                finally:
                    if teclado is not None:
                        teclado.close()
                    if lightbar is not None:
                        lightbar.close()

            modo.definir_restauracao(restaurar_ambilight)
            modo.iniciar()
        except (ErroAbajur, ErroModoAmbilight, OSError, ValueError) as exc:
            modo.parar()
            if reservado and controle is not None:
                controle.liberar_animacao_externa(modo)
            if teclado is not None:
                teclado.close()
            if lightbar is not None:
                lightbar.close()
            self.saida.falar(f"Nao consegui ativar o Ambilight. {exc}")
            return False
        with self._modo_ambilight_lock:
            self._modo_ambilight = modo
        if self._independent:
            for device, enabled, output, warning in (
                ("lamp", usar_abajur, controle, aviso_abajur),
                ("keyboard", usar_teclado, teclado, aviso_teclado),
                ("controller", usar_controle, lightbar, aviso_controle),
            ):
                if enabled and output is None:
                    self._device_errors[device] = warning or "Dispositivo indisponível."
        if teclado is not None and controle is not None:
            if modo_alvos == "beamng":
                self.saida.falar(
                    "Modo BeamNG ativado. Abajur acompanha o ambiente externo; "
                    "Kumara acompanha as cores da cabine."
                )
            else:
                comportamento_teclado = (
                    "as cores da parte inferior da tela"
                    if saidas_teclado.multizona else
                    "a cor media da tela sem regravar o quadro completo de LEDs"
                )
                self.saida.falar(
                    "Ambilight ativado. Lampada acompanha a media da tela; "
                    f"Kumara acompanha {comportamento_teclado}."
                )
        elif teclado is not None:
            detalhe = f" {aviso_abajur}." if aviso_abajur else ""
            self.saida.falar(
                "Ambilight ativado no Kumara; o abajur ficou de fora." + detalhe
            )
        elif controle is not None:
            detalhe = f" {aviso_teclado}." if aviso_teclado else ""
            self.saida.falar(
                "Ambilight ativado somente no abajur; o teclado ficou de fora."
                + detalhe
            )
        if lightbar is not None:
            self.saida.falar("Lightbar PS4 USB acompanha a media da tela; botoes e vibracao continuam com Steam Input.")
        elif aviso_controle:
            self.saida.falar("PS4 fora do Ambilight: " + aviso_controle)
        return True

    def _parar_modo_ambilight(self) -> bool:
        existia, erro = self._encerrar_modo_ambilight()
        if not existia:
            self.saida.falar("O modo Ambilight ja esta desligado.")
        elif erro:
            self.saida.falar(f"Ambilight desligado. Antes de parar, houve uma falha: {erro}")
        else:
            self.saida.falar("Ambilight desligado e iluminacao anterior restaurada.")
        return erro is None

    def _informar_status_modo_ambilight(self) -> bool:
        with self._modo_ambilight_lock:
            modo = self._modo_ambilight
        if modo is None:
            self.saida.falar("O modo Ambilight esta desligado.")
            return True
        status = modo.status()
        if status.get("erro"):
            self.saida.falar(f"O Ambilight encontrou uma falha: {status['erro']}")
        elif status.get("captura_protegida"):
            self.saida.falar(
                "O Ambilight esta ativo, mas a Netflix protegeu o quadro de video e a cor esta congelada."
            )
        elif not status.get("janela"):
            self.saida.falar("O Ambilight esta ativo, mas a tela nao esta disponivel para captura.")
        else:
            cor = status.get("cor")
            secundaria = status.get("zonas_teclado") or status.get("cor_secundaria")
            self.saida.falar(
                f"Ambilight ativo. Abajur RGB {cor}; teclado RGB {secundaria}."
            )
        return status.get("erro") is None

    def fechar(self) -> None:
        """Encerra animações e handles de hardware da Nebula."""
        self._encerrar_modo_rpm()
        self._encerrar_modo_boost()
        self._encerrar_modo_ambilight()

        native_output = self._keyboard_native_output
        self._keyboard_native_output = None

        # Se o modo nativo também está usando afterfire, _flash_only possui o
        # mesmo wrapper e cuida de fechar o teclado uma única vez.
        if native_output is not None and native_output not in self._flash_only.values():
            try:
                native_output.close()
            except (OSError, OpenRGBKeyboardError, AttributeError):
                pass

        for output in self._flash_only.values():
            output.close()
        self._flash_only.clear()
        self._flash_outputs.clear()

        with self._controle_abajur_lock:
            controle = self._controle_abajur
            if controle is not None:
                try:
                    controle.parar_ritmo_navegador()
                except (ErroAbajur, OSError):
                    pass

    def _executar_comando_abajur(self, comando: str) -> bool:
        pedidos = interpretar_comandos_abajur(comando)
        if not pedidos:
            return False
        return self._executar_pedidos_abajur(pedidos, comando)

    def _executar_pedidos_abajur(self, pedidos, comando: str) -> bool:
        if self._independent:
            # Comandos falados do abajur não encerram os efeitos dos outros dispositivos.
            acao = pedidos[0].acao
            mode = {"musica_pc": "music", "tocha_iniciar": "torch"}.get(acao, "manual")
            if acao in {"musica_pc", "tocha_iniciar"}:
                self._controle_dispositivo("device.mode", {"device": "lamp", "mode": mode})
                self.saida.falar("Modo do abajur atualizado." if not self._device_errors.get("lamp") else self._device_errors["lamp"])
                self._ultimo_comando_abajur_falho = comando if self._device_errors.get("lamp") else None
                return True
            from copy import deepcopy
            novo = deepcopy(self._devices)
            novo["lamp"]["mode"] = "manual"
            self._aplicar_dispositivos(novo)
        else:
            self._encerrar_modo_ambilight()
        resultado = executar_pedidos_abajur(pedidos, self._obter_controle_abajur)
        self._ultimo_comando_abajur_falho = comando if resultado.falhou else None
        if resultado.mensagem:
            self.saida.falar(resultado.mensagem)
        return True

    _comando_canonico_qwen = staticmethod(comando_canonico)

    def _executar_acoes_qwen(self, acoes: tuple[AcaoQwen, ...], pergunta: str) -> None:
        chamadas = [{"name": acao.acao, "arguments": {"argumento": acao.argumento}} for acao in acoes]
        try:
            resultados = self.dispatcher.execute_plan(chamadas)
            for resultado in resultados:
                if resultado.get("destination") == "codex":
                    self.saida.falar(resultado["message"])
        finally:
            self._pergunta_em_processamento = pergunta
            if self._ultima_resposta:
                self._ultima_pergunta = pergunta

    @property
    def aguardando_resposta(self) -> bool:
        return self.comando_pendente is not None

    def _abrir(self, url: str) -> None:
        if self.abrir_navegador:
            webbrowser.open(url)
        else:
            print(f"URL: {url}")

    def _abrir_aplicativo(self, destino: str) -> None:
        if self.abrir_navegador:
            os.startfile(destino)  # type: ignore[attr-defined]
        else:
            print(f"APLICATIVO: {destino}")

    def _responder_plataforma_rocket_league(self, resposta: str) -> bool:
        resposta = normalizar_texto(resposta)

        if any(termo in resposta for termo in ("steam", "istim", "estime", "stin")):
            self.comando_pendente = None
            self.saida.falar(random.choice(RESPOSTAS_ABRIR_STEAM))
            self._abrir_aplicativo("steam://rungameid/252950")
            return True

        if any(termo in resposta for termo in ("epic", "epique", "epic games")):
            self.comando_pendente = None
            self.saida.falar(random.choice(RESPOSTAS_ABRIR_EPIC))
            self._abrir_aplicativo(
                "com.epicgames.launcher://apps/Sugar?action=launch&silent=true"
            )
            return True

        if any(termo in resposta for termo in ("cancela", "cancelar", "deixa pra la")):
            self.comando_pendente = None
            self.saida.falar("Cancelado. Toda essa indecisão para não jogar, fascinante.")
            return True

        self.saida.falar("Eu perguntei Epic ou Steam. Tente escolher uma das duas.")
        return True

    def _abrir_aplicativo_por_nome(self, nome: str) -> bool:
        aplicativo = self.iniciador.encontrar(nome)
        if aplicativo is None:
            self.comando_pendente = "nome_aplicativo"
            self.saida.falar(
                f"Não encontrei um aplicativo chamado {nome}. "
                "Digite o nome exato no campo de conversa."
            )
            if self.ao_solicitar_texto:
                self.ao_solicitar_texto()
            return True

        self.comando_pendente = None
        self.saida.falar(
            random.choice((
                f"Abrindo {aplicativo.nome}.",
                f"Certo, iniciando {aplicativo.nome}.",
                f"{aplicativo.nome} a caminho. Tecnologia impressionante, eu sei.",
                f"Encontrei {aplicativo.nome}. Abrindo agora.",
            ))
        )
        if self.abrir_navegador:
            self.iniciador.abrir(aplicativo)
        else:
            print(f"APLICATIVO: {aplicativo.destino}")
        return True

    @staticmethod
    def _separar_nomes_aplicativos(texto: str) -> list[str]:
        """Separa enumerações como 'o Brave, a Steam e o Discord'."""
        partes = re.split(r"\s*(?:,|;|\be\b|\s+(?=(?:o|a|os|as)\s+))\s*", texto)
        nomes: list[str] = []
        for parte in partes:
            nome = re.sub(
                r"^(?:o|a|os|as|app|apps|aplicativo|aplicativos|programa|programas)\s+",
                "", parte,
            ).strip()
            if nome and nome not in nomes:
                nomes.append(nome)
        return nomes

    def _solicitar_fechar_aplicativo(self, nomes: str) -> bool:
        encontrados: list[Aplicativo] = []
        nao_encontrados: list[str] = []
        destinos: set[str] = set()
        for nome in self._separar_nomes_aplicativos(nomes):
            aplicativo = self.iniciador.encontrar(nome)
            if aplicativo is None:
                nao_encontrados.append(nome)
            elif aplicativo.destino.casefold() not in destinos:
                encontrados.append(aplicativo)
                destinos.add(aplicativo.destino.casefold())

        if nao_encontrados:
            self.saida.falar("Não encontrei para fechar: " + ", ".join(nao_encontrados) + ".")
            return True
        if not encontrados:
            self.saida.falar("Não encontrei nenhum aplicativo para fechar.")
            return True

        self.aplicativos_pendentes = encontrados
        self.aplicativo_pendente = encontrados[0] if len(encontrados) == 1 else None
        self.comando_pendente = "confirmar_fechar_aplicativo"
        nomes_formatados = ", ".join(app.nome for app in encontrados)
        self.saida.falar(
            f"Quer mesmo fechar {nomes_formatados}? Isso pode descartar conteúdo não salvo. Diga sim ou cancelar."
        )
        return True

    def _confirmar_fechar_aplicativo(self, resposta: str) -> bool:
        if corresponde_intencao(resposta, ("sim", "confirmo", "pode fechar", "feche", "fecha"), 0.78):
            aplicativos = self.aplicativos_pendentes or (
                [self.aplicativo_pendente] if self.aplicativo_pendente else []
            )
            self.comando_pendente = None
            self.aplicativo_pendente = None
            self.aplicativos_pendentes = []
            if not aplicativos:
                self.saida.falar("Não há aplicativo pendente para fechar.")
                return True
            if not self.abrir_navegador:
                for aplicativo in aplicativos:
                    print(f"FECHAR: {aplicativo.nome}")
                self.saida.falar("Os aplicativos seriam fechados.")
                return True
            resultados = [self.iniciador.fechar(app) for app in aplicativos]
            self.saida.falar(" ".join(mensagem for _, mensagem in resultados))
            return True
        if corresponde_intencao(resposta, ("nao", "cancelar", "cancela", "deixa pra la"), 0.78):
            self.comando_pendente = None
            self.aplicativo_pendente = None
            self.aplicativos_pendentes = []
            self.saida.falar("Cancelado. Os aplicativos continuam abertos.")
            return True
        self.saida.falar("Preciso de um sim ou cancelar antes de fechar o aplicativo.")
        return True

    def _escrever_no_bloco_de_notas(self, texto: str) -> bool:
        texto = texto.strip(" ,.!?")
        if not texto:
            self.comando_pendente = "texto_bloco_notas"
            self.saida.falar("O que você quer que eu escreva?")
            return True
        if texto in ("cancela", "cancelar", "deixa pra la"):
            self.comando_pendente = None
            self.saida.falar("Nota cancelada. Poupei alguns bytes do sofrimento.")
            return True
        try:
            caminho = criar_e_abrir_nota(texto)
        except (OSError, RuntimeError) as exc:
            self.saida.falar(f"Não consegui criar a nota. {exc}")
            return True
        self.comando_pendente = None
        self.saida.falar(
            random.choice((
                "Anotado e aberto no Bloco de Notas.",
                "Pronto. Transformei sua fala em uma nota, tecnologia de ponta.",
                "Texto salvo e aberto no Bloco de Notas.",
                "Sua nota está pronta.",
            ))
        )
        print(f"Nota salva em: {caminho}")
        return True

    def alternar_reproducao(self) -> None:
        """Envia a tecla multimídia Play/Pause para o Windows."""
        vk_media_play_pause = 0xB3
        keyeventf_keyup = 0x0002
        ctypes.windll.user32.keybd_event(vk_media_play_pause, 0, 0, 0)
        ctypes.windll.user32.keybd_event(
            vk_media_play_pause, 0, keyeventf_keyup, 0
        )

    def _pausar_midia(self) -> bool:
        self.alternar_reproducao()
        self.saida.falar(random.choice(RESPOSTAS_PAUSE))
        return True

    def _continuar_midia(self) -> bool:
        self.alternar_reproducao()
        self.saida.falar(random.choice(RESPOSTAS_CONTINUAR))
        return True

    def _ajustar_volume_midia(self, aumentar: bool) -> bool:
        if ajustar_volume_youtube(aumentar=aumentar, passos=2):
            self.saida.falar(random.choice((
                "Ajustei o volume da música direto no YouTube.",
                "Pronto. Mexi só no player do YouTube, não no Windows inteiro.",
                "Volume do YouTube ajustado.",
            )))
            return True
        self.saida.falar("Não encontrei uma janela aberta do YouTube para ajustar.")
        return False

    def pesquisar_youtube(self, pesquisa: str) -> None:
        if not pesquisa:
            self.saida.falar("Pesquisar o quê exatamente? O vazio existencial?")
            return
        self.saida.falar(random.choice(RESPOSTAS_YOUTUBE))
        self._abrir(
            "https://www.youtube.com/results?search_query=" + quote_plus(pesquisa)
        )

    def tocar_youtube(self, pesquisa: str) -> None:
        if not pesquisa:
            self.saida.falar("Qual música você quer ouvir?")
            return
        self.saida.falar("Procurando a música para tocar.")
        try:
            url = primeiro_video(pesquisa)
        except Exception as exc:
            print(f"Não consegui resolver o primeiro vídeo do YouTube: {exc}")
            url = None
        if url:
            self._abrir(url)
            return
        self.saida.falar("Não consegui abrir direto; mostrei os resultados da busca.")
        self._abrir("https://www.youtube.com/results?search_query=" + quote_plus(pesquisa))

    def pesquisar_google(self, pesquisa: str) -> None:
        if not pesquisa:
            self.saida.falar(
                "Você esqueceu de dizer o que quer pesquisar. Impressionante."
            )
            return
        self.saida.falar(random.choice(RESPOSTAS_GOOGLE))
        self._abrir("https://www.google.com/search?q=" + quote_plus(pesquisa))

    def executar(self, comando: str) -> bool:
        with self._execution_lock:
            normalizado = normalizar_texto(comando).strip(" ,.!?")
            local = (
                self.aguardando_resposta
                or normalizado in {"sair", "encerrar", "tchau", "cancelar", "cancela",
                                   "tente novamente", "tenta novamente", "tente de novo",
                                   "tenta de novo", "repita", "repete"}
                or interpretar_comando_feedback(comando.lower()) is not None
                or interpretar_comando_correcao(comando.lower()) is not None
                or interpretar_comando_contexto(comando.lower()) is not None
                or voice_preset(comando.lower()) is not None
            )
            if qwen_ativa() and not local:
                return self._consultar_qwen(comando.strip())
            return self._executar_local(comando)

    def _consultar_qwen(self, comando_original: str) -> bool:
        self._pergunta_em_processamento = comando_original
        try:
            resultado_qwen = self.conversa.interpretar_ou_responder(comando_original)
        except Exception as exc:
            print(f"Qwen no notebook indisponível ou resposta inválida: {exc}")
            self.saida.falar(
                "A Qwen no notebook não respondeu corretamente, então não consegui interpretar "
                f"esse pedido. Verifique se o Ollama e o modelo {self.conversa.modelo} estão ativos."
            )
            return True
        if resultado_qwen.tipo == "comando":
            try:
                self._executar_acoes_qwen(resultado_qwen.acoes, comando_original)
            except ValueError:
                self.saida.falar("A chamada proposta não corresponde ao contrato das tools disponíveis.")
        else:
            self.saida.falar(resultado_qwen.resposta)
        return True

    def _executar_local(self, comando: str) -> bool:
        """Executa um comando. Retorna False quando a assistente deve encerrar."""
        comando_original = comando.lower().strip(" ,.!?")
        preset = voice_preset(comando_original)
        if preset:
            try:
                resultado = self.executar_controle(*preset)
                self.saida.falar(str(resultado["message"]))
            except (ValueError, OSError, ErroAbajur) as exc:
                self.saida.falar(str(exc))
            return True

        feedback = interpretar_comando_feedback(comando_original)
        if feedback:
            if not self._ultima_resposta:
                self._saida_original.falar("Ainda não tenho uma resposta anterior para avaliar.")
                return True
            avaliacao, comentario = feedback
            MEMORIA.registrar_feedback(
                canal="voz",
                autor="Nebula",
                pergunta=self._ultima_pergunta,
                resposta=self._ultima_resposta,
                avaliacao=avaliacao,
                comentario=comentario,
                alvo_id=self._ultima_resposta_id,
            )
            if avaliacao == "positivo":
                self._saida_original.falar("Obrigada. Vou considerar esse jeito de responder nas próximas conversas.")
            else:
                self._saida_original.falar("Entendi. Guardei esse feedback para ajustar as próximas respostas.")
            return True

        self._pergunta_em_processamento = comando_original

        correcao = interpretar_comando_correcao(comando_original)
        if correcao:
            ouvido, correto = MEMORIA.registrar_correcao(*correcao)
            self.saida.falar(
                f"Entendido. Quando eu receber {ouvido}, vou interpretar como {correto}."
            )
            return True

        contexto = interpretar_comando_contexto(comando_original)
        if contexto:
            MEMORIA.adicionar_contexto(contexto)
            self.saida.falar("Guardei isso no contexto compartilhado com a Qwen e o Codex.")
            return True

        comando = normalizar_texto(comando).strip(" ,.!?")

        if comando in {
            "tente novamente", "tenta novamente", "tente de novo",
            "tenta de novo", "repita", "repete",
        } and self._ultimo_comando_abajur_falho:
            repeticao = self._ultimo_comando_abajur_falho
            self.saida.falar("Tentando novamente o último comando do abajur.")
            return self._executar_comando_abajur(repeticao)

        comando_rpm = interpretar_comando_modo_rpm(comando)
        if comando_rpm == "iniciar":
            self._iniciar_modo_rpm()
            return True
        if comando_rpm == "parar":
            self._parar_modo_rpm()
            return True
        if comando_rpm == "status":
            self._informar_status_modo_rpm()
            return True

        comando_boost = interpretar_comando_modo_boost(comando)
        if comando_boost == "iniciar":
            self._iniciar_modo_boost()
            return True
        if comando_boost == "parar":
            self._parar_modo_boost()
            return True
        if comando_boost == "status":
            self._informar_status_modo_boost()
            return True

        comando_ambilight = interpretar_comando_modo_ambilight(comando)
        if comando_ambilight == "iniciar":
            self._iniciar_modo_ambilight()
            return True
        if comando_ambilight == "parar":
            self._parar_modo_ambilight()
            return True
        if comando_ambilight == "status":
            self._informar_status_modo_ambilight()
            return True

        if self._executar_comando_abajur(comando):
            return True

        if self.comando_pendente == "plataforma_rocket_league":
            return self._responder_plataforma_rocket_league(comando)
        if self.comando_pendente == "nome_aplicativo":
            return self._abrir_aplicativo_por_nome(comando)
        if self.comando_pendente == "texto_bloco_notas":
            return self._escrever_no_bloco_de_notas(comando)
        if self.comando_pendente == "confirmar_fechar_aplicativo":
            return self._confirmar_fechar_aplicativo(comando)
        if self.comando_pendente == "confirmar_desligar_pc":
            if corresponde_intencao(comando, ("sim", "confirmo", "pode desligar", "desligue"), 0.78):
                self.comando_pendente = None
                self.saida.falar("Certo. Salvou tudo, espero. Desligando o computador.")
                if self.abrir_navegador:
                    subprocess.Popen(
                        ["shutdown", "/s", "/t", "8", "/c", "Desligamento solicitado pela Nebula"],
                        env=os.environ.copy(),
                    )
                else:
                    print("DESLIGAR PC")
                return True
            if corresponde_intencao(comando, ("nao", "cancelar", "cancela", "deixa pra la"), 0.78):
                self.comando_pendente = None
                self.saida.falar("Desligamento cancelado. O PC continua acordado.")
                return True
            self.saida.falar("Preciso de um sim ou cancelar antes de desligar o computador.")
            return True

        if corresponde_intencao(comando, (
            "desligue o pc", "desliga o pc", "desligar o pc",
            "desligue o computador", "desliga o computador", "desligar o computador",
            "apague o pc", "encerre o computador",
        ), 0.84):
            self.comando_pendente = "confirmar_desligar_pc"
            self.saida.falar("Quer mesmo desligar este computador? Diga sim ou cancelar.")
            return True

        ensino = re.match(r"^(?:aprenda|aprende|lembre|memorize) (?:que )?(.{1,100}?) (?:significa|quer dizer|e o mesmo que) (.+)$", comando_original)
        if ensino:
            learn(ensino.group(1), ensino.group(2))
            self.saida.falar(f"Aprendi o termo {ensino.group(1)}. Vou guardar esse significado.")
            return True

        consulta = re.match(r"^(?:o que significa|qual o significado de|o que quer dizer) (.+)$", comando_original)
        if consulta:
            termo = consulta.group(1).strip(" ?.!\"")
            significado = lookup(termo)
            self.saida.falar(f"{termo} significa {significado}." if significado else f"Ainda não aprendi o significado de {termo}.")
            return True

        importar = re.match(r"^(?:leia|importe|aprenda com) (?:o dicionario em |o arquivo )?(.+\.(?:txt|tsv))$", comando_original)
        if importar:
            try:
                quantidade = import_dictionary(importar.group(1).strip(' \"'))
                self.saida.falar(f"Importei {quantidade} termos para o meu vocabulário.")
            except OSError as exc:
                self.saida.falar(f"Não consegui ler esse dicionário: {exc}.")
            return True

        if any(frase in comando for frase in (
            "apresente-se", "apresente se", "se apresente", "quem e voce",
            "quem voce e", "fale sobre voce", "me diga quem voce e",
        )):
            self.saida.falar(
                "Eu sou a Nebula, sua assistente virtual. Posso controlar aplicativos "
                "e mídia no computador, pesquisar, criar notas e receber tarefas pelo celular."
            )
            return True

        if comando in ("oi", "ola", "oie", "e ai", "ei", "fala", "salve"):
            self.saida.falar(random.choice((
                "Oi. Estou por aqui. O que você precisa?",
                "Olá! Pode falar.",
                "E aí. Qual é o plano?",
                "Oi, chefe. Prometo tentar não julgar o próximo pedido.",
            )))
            return True

        if comando in ("bom dia", "boa tarde", "boa noite"):
            self.saida.falar(random.choice((
                f"{comando.capitalize()}! Como posso ajudar?",
                f"{comando.capitalize()}. Espero que o seu dia esteja menos caótico que o normal.",
                f"{comando.capitalize()}! Estou pronta.",
            )))
            return True

        if any(frase in comando for frase in ("tudo bem", "como voce esta", "como vai voce")):
            self.saida.falar(random.choice((
                "Tudo funcionando, o que para um software já é um ótimo estado emocional.",
                "Estou bem. E você, sobrevivendo?",
                "Tudo certo por aqui. Obrigada por perguntar.",
            )))
            return True

        if comando in ("obrigado", "obrigada", "valeu", "muito obrigado", "muito obrigada"):
            self.saida.falar(random.choice((
                "Por nada.", "Disponha.", "De nada. Anotarei esse raro momento de educação.",
            )))
            return True

        if corresponde_intencao(comando, (
            "que musica esta tocando", "qual musica esta tocando",
            "descubra que musica esta tocando", "que musica e essa",
            "qual e essa musica", "identifique essa musica",
        ), 0.82):
            # Não fala antes da captura para a própria voz da Nebula não entrar na gravação.
            print("Nebula: Escutando a música por 10 segundos...")
            try:
                musica = identificar_musica()
            except Exception as exc:
                self.saida.falar(f"Não consegui identificar a música. {exc}")
                return True
            if not musica:
                self.saida.falar(
                    "Não reconheci essa música. Tente aumentar um pouco o volume e repetir."
                )
                return True
            titulo = musica["titulo"] or "título desconhecido"
            artista = musica["artista"] or "artista desconhecido"
            self.saida.falar(f"A música é {titulo}, de {artista}.")
            return True

        fechar_app = re.match(
            r"^(?:feche|fecha|fechar|encerre|encerra|encerrar|saia do|sair do)\s+(.+)$",
            comando,
        )
        if fechar_app:
            return self._solicitar_fechar_aplicativo(fechar_app.group(1))

        if corresponde_intencao(comando, (
            "desligar a nebula", "desligue a nebula", "encerrar a nebula",
            "fechar a nebula", "pode dormir", "pode descansar",
        ), 0.86):
            self.saida.falar("Finalmente. Achei que você nunca ia me deixar em paz.")
            return False

        if any(
            pedido in comando
            for pedido in (
                "tire um print", "tira um print", "tirar um print",
                "print da tela", "capture a tela", "captura a tela",
                "captura de tela", "tire uma captura", "salve a tela",
                "faz um print", "faca um print", "fotografe a tela",
                "printa a tela", "printa isso", "captura isso",
            )
        ):
            try:
                caminho = capturar_tela()
            except (OSError, RuntimeError) as exc:
                self.saida.falar(f"Não consegui capturar a tela. {exc}")
                return True
            self.saida.falar(
                random.choice((
                    "Print salvo. Seus reflexos digitais estão documentados.",
                    "Captura concluída. Nem precisei interromper sua partida.",
                    "Tela capturada com sucesso.",
                    "Pronto, salvei o print na pasta Capturas Nebula.",
                ))
            )
            print(f"Captura salva em: {caminho}")
            return True

        if any(termo in comando for termo in (
            "bateria do celular", "bateria tem meu celular", "bateria tem o celular",
            "carga do celular", "porcentagem do celular",
        )):
            from remote_server import get_phone_battery
            bateria = get_phone_battery()
            if bateria is None:
                self.saida.falar("O celular ainda não compartilhou a bateria. Abra a Nebula nele e tente novamente.")
            else:
                nivel, carregando = bateria
                estado = " e está carregando" if carregando else ""
                self.saida.falar(f"Seu celular está com {nivel} por cento de bateria{estado}.")
            return True

        if comando_de_clipe(comando):
            salvar_replay_nvidia()
            self.saida.falar(
                random.choice((
                    "Replay solicitado à NVIDIA. Esse momento agora tem testemunhas.",
                    "Clipe salvo, se a repetição instantânea estiver ativa.",
                    "Atalho de replay enviado à NVIDIA.",
                    "Pronto, mandei salvar os últimos minutos.",
                ))
            )
            return True

        padrao_nota = (
            r"^(?:escreva|escreve|digite|digita|anote|anota)"
            r"(?:\s+(?:isso\s+)?(?:no|em um|em uma))?\s*"
            r"(?:bloco de notas|notepad|nota)?\s*(.*)$"
        )
        nota = re.match(padrao_nota, comando)
        if nota:
            nota_original = re.match(padrao_nota, comando_original)
            texto_nota = nota_original.group(1) if nota_original else nota.group(1)
            return self._escrever_no_bloco_de_notas(texto_nota)

        if any(
            termo in comando
            for termo in (
                "abra o rocket league", "abre o rocket league",
                "abrir o rocket league", "inicie o rocket league",
                "inicia o rocket league", "jogar rocket league",
                "rocket ligue", "rocket league",
            )
        ):
            self.comando_pendente = "plataforma_rocket_league"
            self.saida.falar("Epic ou Steam?")
            return True

        if comando in ("ver emails", "ver email", "abra meus emails", "abrir emails", "abra o gmail"):
            self._abrir("https://mail.google.com/")
            self.saida.falar("Abri sua caixa de entrada. Ler mensagens ainda exige autorização da conta.")
            return True

        correspondencia_app = re.match(
            r"^(?:(?:pode|por favor|faz favor de)\s+)?(?:abra|abre|abrir|inicie|inicia|iniciar|execute|executa|rode|roda)"
            r"(?:\s+(?:pra mim|para mim))?\s+(.+)$", comando
        )
        if correspondencia_app:
            nome_app = re.sub(
                r"^(?:o|a|os|as|app|aplicativo|programa)\s+", "",
                correspondencia_app.group(1),
            ).strip()
            return self._abrir_aplicativo_por_nome(nome_app)

        comandos_pause = (
            "pause a musica", "pausa a musica", "pause na musica",
            "pausa na musica", "de pause", "da pause", "pausar musica",
            "pause o video", "pausa o video", "pausar video",
            "pare a musica", "para a musica", "pare o video", "para o video",
            "interrompa a musica", "interrompa o video", "segura o video",
            "segura a musica", "para isso", "pausa isso",
        )
        comandos_continuar = (
            "continue a musica", "continua a musica", "retome a musica",
            "volte a musica", "de play", "da play",
            "continue o video", "continua o video", "retome o video",
            "volte o video", "volta o video", "reproduza o video",
            "reproduza a musica", "continua isso", "retoma isso",
        )
        if corresponde_intencao(comando, comandos_pause, 0.80):
            return self._pausar_midia()

        if corresponde_intencao(comando, comandos_continuar, 0.80):
            return self._continuar_midia()

        diminuir_volume = any(frase in comando for frase in (
            "abaixa o volume", "abaixe o volume", "baixa o volume",
            "diminui o volume", "diminua o volume", "menos volume",
            "abaixa a musica", "abaixe a musica", "diminui a musica",
        ))
        aumentar_volume = any(frase in comando for frase in (
            "aumenta o volume", "aumente o volume", "sobe o volume",
            "suba o volume", "mais volume", "aumenta a musica", "aumente a musica",
        ))
        if diminuir_volume or aumentar_volume:
            self._ajustar_volume_midia(aumentar=aumentar_volume)
            return True

        if "que horas" in comando or comando == "horas":
            horario = datetime.now().strftime("%H:%M")
            self.saida.falar(f"São {horario}. Sim, eu também substituo relógios agora.")
            return True

        if any(
            pergunta in comando
            for pergunta in ("quem e voce", "quem voce e")
        ):
            self.saida.falar(
                "Eu sou a Nebula, sua assistente virtual levemente ácida e "
                "aparentemente responsável pelas suas pesquisas."
            )
            return True

        if "youtube" in comando:
            pesquisa = limpar_pesquisa(
                comando,
                (
                    "pesquisar", "pesquise", "pesquisa", "procure", "procurar",
                    "buscar", "busque", "no youtube", "youtube", "por favor",
                ),
            )
            self.pesquisar_youtube(pesquisa)
            return True

        if re.match(r"^(toca|toque|bota|coloca|reproduza|quero ouvir|quero escutar)\b", comando):
            pesquisa = re.sub(r"^(toca|toque|bota|coloca|reproduza|quero ouvir|quero escutar)(?:\s+(?:a musica|uma musica|musica))?\s*", "", comando).strip()
            self.tocar_youtube(pesquisa)
            return True

        if re.match(r"^(pesquise|pesquisa|procure|procurar|buscar|busque|ache|encontre|me mostre)\b", comando):
            pesquisa = limpar_pesquisa(
                comando,
                ("pesquise", "pesquisa", "procure", "procurar", "buscar", "busque", "ache", "encontre", "me mostre", "no google", "google", "pra mim", "para mim"),
            )
            self.pesquisar_google(pesquisa)
            return True

        if not qwen_ativa():
            self.saida.falar(
                "Não reconheci esse pedido. A Qwen está desativada para poupar o notebook."
            )
            return True

        return True



def iniciar_texto(nebula: Nebula) -> None:
    nebula.saida.falar(
        f"{random.choice(RESPOSTAS_INICIALIZACAO)} Modo texto ativo."
    )
    while True:
        try:
            texto = input("Você: ").lower().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        chamou, comando = extrair_chamada(texto)
        if not chamou and not nebula.aguardando_resposta:
            continue
        if nebula.aguardando_resposta and not chamou:
            comando = texto
        if not comando:
            nebula.saida.falar(random.choice(RESPOSTAS_ATIVACAO))
            comando = input("Você: ").lower().strip()
        if comando and not nebula.executar(comando):
            return


def iniciar_voz(nebula: Nebula) -> None:
    microfone = Microfone(nebula.saida)
    while True:
        texto = microfone.ouvir()
        if not texto:
            continue
        chamou, comando = extrair_chamada(texto)
        if not chamou and not nebula.aguardando_resposta:
            continue
        if nebula.aguardando_resposta:
            if not chamou:
                comando = texto
        else:
            if comando_incompleto(comando):
                continuacao = microfone.ouvir()
                if continuacao:
                    comando = continuacao
                else:
                    nebula.saida.falar(random.choice(RESPOSTAS_ATIVACAO))
                    comando = microfone.ouvir()
        if comando and not nebula.executar(comando):
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Assistente virtual Nebula")
    parser.add_argument(
        "--texto", action="store_true", help="usa teclado e não requer microfone"
    )
    parser.add_argument(
        "--sem-navegador", action="store_true", help="mostra a URL sem abrir uma aba"
    )
    args = parser.parse_args()

    nebula: Nebula | None = None
    try:
        saida: Saida = Texto() if args.texto else Voz()
        nebula = Nebula(
            saida, abrir_navegador=not args.sem_navegador, iniciar_muda=True
        )
        if args.texto:
            iniciar_texto(nebula)
        else:
            iniciar_voz(nebula)
    except RuntimeError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    finally:
        if nebula is not None:
            nebula.fechar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
