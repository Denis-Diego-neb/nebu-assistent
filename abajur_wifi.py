"""Controle do abajur Elgin Smart por meio do aplicativo Android conectado via ADB.

Esta integração é intencionalmente separada do restante da Nebula. Ela serve como
ponte enquanto a chave local Tuya do dispositivo não está disponível: a Nebula
abre o app oficial e aciona somente os controles visíveis ao usuário.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from io import BytesIO
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time
from xml.etree import ElementTree


PACOTE_ELGIN = "com.elgin.smart"
TAMANHO_REFERENCIA = (1080, 2400)


class ErroAbajur(RuntimeError):
    """Falha compreensível ao controlar o abajur."""


def _validar_dependencias_ritmo() -> None:
    """Confirma que o medidor de áudio foi incluído nesta instalação."""
    try:
        modulo = importlib.import_module("pycaw.pycaw")
        getattr(modulo, "AudioUtilities")
        getattr(modulo, "IAudioMeterInformation")
    except Exception as exc:
        raise ErroAbajur(
            "O modo ritmo não está disponível porque a biblioteca pycaw "
            "não foi incluída corretamente nesta instalação."
        ) from exc


@dataclass(frozen=True)
class ComandoAbajur:
    acao: str
    valor: object = None


CORES = {
    "vermelho": "vermelho",
    "vermelha": "vermelho",
    "azul": "azul",
    "verde": "verde",
    "amarelo": "amarelo",
    "amarela": "amarelo",
    "roxo": "roxo",
    "roxa": "roxo",
    "rosa": "rosa",
    "ciano": "ciano",
    "laranja": "laranja",
    "laranja queimado": "laranja queimado",
    "dourado": "dourado",
    "turquesa": "turquesa",
    "azul claro": "azul claro",
    "azul celeste": "azul celeste",
    "azul marinho": "azul marinho",
    "azul royal": "azul royal",
    "verde limao": "verde limao",
    "verde agua": "verde agua",
    "verde esmeralda": "verde esmeralda",
    "verde oliva": "verde oliva",
    "violeta": "violeta",
    "lilas": "lilas",
    "magenta": "magenta",
    "fucsia": "fucsia",
    "pink": "rosa",
    "rosa claro": "rosa claro",
    "rosa choque": "rosa choque",
    "rosa avermelhado": "rosa avermelhado",
    "rosa arroxeado": "rosa arroxeado",
    "cereja": "cereja",
    "framboesa": "framboesa",
    "vinho": "vinho",
    "bordo": "bordo",
    "coral": "coral",
    "salmão": "salmao",
    "bege": "bege",
    "marrom": "marrom",
    "cinza": "cinza",
    "cinza claro": "cinza claro",
    "branco": "branco",
    "preto": "preto",
}

RGB_NOMEADAS = {
    "vermelho": (255, 0, 0),
    "azul": (0, 0, 255),
    "verde": (0, 255, 0),
    "amarelo": (255, 255, 0),
    "roxo": (128, 0, 255),
    "rosa": (255, 20, 147),
    "ciano": (0, 255, 255),
    "laranja": (255, 128, 0),
    "laranja queimado": (204, 85, 0),
    "dourado": (255, 179, 0),
    "turquesa": (64, 224, 208),
    "azul claro": (30, 144, 255),
    "azul celeste": (135, 206, 235),
    "azul marinho": (0, 35, 102),
    "azul royal": (65, 105, 225),
    "verde limao": (50, 205, 50),
    "verde agua": (0, 200, 160),
    "verde esmeralda": (0, 150, 100),
    "verde oliva": (128, 128, 0),
    "violeta": (143, 0, 255),
    "lilas": (190, 150, 255),
    "magenta": (255, 0, 170),
    "fucsia": (213, 0, 105),
    "rosa claro": (255, 150, 190),
    "rosa choque": (255, 0, 110),
    "rosa avermelhado": (199, 21, 133),
    "rosa arroxeado": (194, 24, 91),
    "cereja": (210, 0, 60),
    "framboesa": (180, 0, 80),
    "vinho": (128, 0, 32),
    "bordo": (128, 0, 32),
    "coral": (255, 100, 80),
    "salmao": (250, 128, 114),
    "bege": (220, 190, 140),
    "marrom": (128, 65, 0),
    "cinza": (128, 128, 128),
    "cinza claro": (190, 190, 190),
    "branco": (255, 255, 255),
    "preto": (1, 1, 1),
}


def _nome_preset(nome: str) -> str:
    nome = " ".join(nome.lower().strip().split())
    if not re.fullmatch(r"[a-z0-9][a-z0-9 _-]{0,39}", nome):
        raise ErroAbajur("Use um nome curto, sem símbolos, para a cor salva.")
    return nome


def resolver_cor(especificacao: str) -> tuple[int, int, int]:
    """Converte uma cor nomeada, hexadecimal ou RGB em três canais."""
    especificacao = especificacao.lower().strip()
    nomeada = CORES.get(especificacao)
    if nomeada:
        return RGB_NOMEADAS[nomeada]

    hexadecimal = re.fullmatch(r"(?:hex(?:adecimal)?\s*)?#?([0-9a-f]{6})", especificacao)
    if hexadecimal:
        valor = hexadecimal.group(1)
        return tuple(int(valor[indice:indice + 2], 16) for indice in (0, 2, 4))  # type: ignore[return-value]

    rgb = re.fullmatch(r"rgb\s+(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})", especificacao)
    if rgb:
        canais = tuple(map(int, rgb.groups()))
        if all(0 <= canal <= 255 for canal in canais):
            return canais  # type: ignore[return-value]
    raise ErroAbajur("Use uma cor conhecida, hexadecimal de seis dígitos ou RGB de 0 a 255.")


def interpretar_comandos_abajur(comando: str) -> list[ComandoAbajur]:
    """Traduz uma frase normalizada em uma ou mais ações do abajur.

    Presets continuam atômicos. Temperatura, brilho e modo música podem ser
    combinados e são devolvidos na ordem em que devem chegar ao controlador.
    """
    salvar_atual = re.fullmatch(
        r"(?:salve|salva) (?:(?:a )?cor atual|essa cor|(?:a )?cor que esta (?:agora|no momento)) como ([a-z0-9][a-z0-9 _-]{0,39})",
        comando,
    )
    if salvar_atual:
        return [ComandoAbajur("salvar_cor_atual", salvar_atual.group(1).strip())]

    salvar = re.fullmatch(
        r"(?:salve|salva) (?:no abajur )?(?:a )?cor (.+?) (?:do abajur )?como ([a-z0-9][a-z0-9 _-]{0,39})",
        comando,
    )
    if salvar:
        return [ComandoAbajur("salvar_cor", (salvar.group(1), salvar.group(2).strip()))]

    usar_salva = re.fullmatch(
        r"(?:use|aplique|coloque|deixe) (?:no abajur )?(?:a )?cor salva ([a-z0-9][a-z0-9 _-]{0,39}?)(?: no abajur)?",
        comando,
    )
    if usar_salva:
        return [ComandoAbajur("usar_cor_salva", usar_salva.group(1).strip())]

    parar_tocha = "tocha" in comando and any(
        palavra in comando for palavra in (
            "pare", "parar", "desative", "desativa", "desativar",
            "desligue", "desliga", "desligar", "encerre", "encerrar",
        )
    )
    iniciar_tocha = "tocha" in comando and not parar_tocha and any(
        palavra in comando for palavra in (
            "ative", "ativa", "ativar", "inicie", "inicia", "iniciar",
            "ligue", "liga", "ligar", "modo", "efeito",
        )
    )
    pedido_tocha = (
        ComandoAbajur("tocha_parar") if parar_tocha else
        ComandoAbajur("tocha_iniciar") if iniciar_tocha else None
    )

    parar_musica = any(frase in comando for frase in (
        "pare o modo musica", "para o modo musica", "desative o modo musica",
        "desliga o modo musica", "pare o ritmo", "desative o ritmo",
        "pare a animacao musical", "para a animacao musical",
        "desative a animacao musical", "desliga a animacao musical",
    ))
    iniciar_musica = not parar_musica and (
        any(frase in comando for frase in (
        "modo musica", "modo ritmo", "ritimo", "ritmo da musica", "reaja a musica",
        "reagir a musica", "sincronize com a musica", "sincroniza com a musica",
        "ritmo do navegador", "ritimo do navegador", "animacao musical",
        )) or ("musica" in comando and any(
            palavra in comando for palavra in ("pisque", "piscar", "pulse", "pulsar")
        ))
    )
    pedido_musica: ComandoAbajur | None = None
    if parar_musica:
        pedido_musica = ComandoAbajur("musica_parar")
    elif iniciar_musica:
        rgb_musica = re.search(r"\brgb\s+(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})\b", comando)
        if rgb_musica:
            canais = tuple(map(int, rgb_musica.groups()))
            if all(0 <= canal <= 255 for canal in canais):
                pedido_musica = ComandoAbajur("musica_pc", canais)
        hexadecimal_musica = re.search(r"\b(?:hex|hexadecimal)\s*#?([0-9a-f]{6})\b", comando)
        if pedido_musica is None and hexadecimal_musica:
            pedido_musica = ComandoAbajur(
                "musica_pc", resolver_cor(hexadecimal_musica.group(1))
            )
        if pedido_musica is None:
            for palavra, cor in sorted(CORES.items(), key=lambda item: len(item[0]), reverse=True):
                if re.search(rf"\b{palavra}\b", comando):
                    pedido_musica = ComandoAbajur("musica_pc", RGB_NOMEADAS[cor])
                    break
        if pedido_musica is None:
            pedido_musica = ComandoAbajur("musica_pc")

    topico_intensidade_ritmo = bool(re.search(
        r"\b(?:(?:intensidade|forca)\s+(?:do|da)\s+"
        r"(?:pulso|pulsar|rit(?:i)?mo|animacao(?: musical)?|modo musica)|"
        r"(?:pulso|pulsar|rit(?:i)?mo|animacao(?: musical)?|modo musica)\s+"
        r"(?:mais\s+)?(?:forte|intens[oa]|pesad[oa]|suave|brutal|maxim[oa]))\b",
        comando,
    )) or bool(re.search(
        r"\b(?:pulso|pulsar|rit(?:i)?mo|animacao(?: musical)?|modo musica)\s+"
        r"(?:no\s+)?maxim[oa]\b",
        comando,
    )) or bool(re.search(
        r"\b(?:modo\s+)?rit(?:i)?mo\b.*\b(?:intensidade|forca|%|por cento)\b",
        comando,
    ))
    pedido_intensidade: ComandoAbajur | None = None
    if topico_intensidade_ritmo:
        percentual_intensidade = re.search(
            r"\b(100|[1-9]?\d)\s*(?:%|por cento)(?=\s|$)", comando
        )
        aumentar = any(palavra in comando for palavra in (
            "aumente", "aumenta", "aumentar", "eleve", "elevar", "suba", "subir",
            "mais forte", "mais intensa", "mais intenso",
        ))
        diminuir = any(palavra in comando for palavra in (
            "diminua", "diminui", "diminuir", "reduza", "reduz", "reduzir",
            "abaixe", "abaixa", "abaixar", "mais suave",
        ))
        if percentual_intensidade:
            valor = int(percentual_intensidade.group(1))
            relativo = (aumentar or diminuir) and not re.search(
                r"\b(?:para|ate|a)\s+(?:o\s+)?(?:nivel\s+)?\d", comando
            )
            if relativo:
                pedido_intensidade = ComandoAbajur(
                    "intensidade_ritmo_relativa", -valor if diminuir else valor
                )
            else:
                pedido_intensidade = ComandoAbajur("intensidade_ritmo", valor)
        elif aumentar:
            pedido_intensidade = ComandoAbajur("intensidade_ritmo_relativa", 20)
        elif diminuir:
            pedido_intensidade = ComandoAbajur("intensidade_ritmo_relativa", -20)
        elif any(palavra in comando for palavra in ("maxima", "maximo", "brutal")):
            pedido_intensidade = ComandoAbajur("intensidade_ritmo", 100)
        elif any(palavra in comando for palavra in ("pesada", "pesado")):
            pedido_intensidade = ComandoAbajur("intensidade_ritmo", 90)
        elif "suave" in comando:
            pedido_intensidade = ComandoAbajur("intensidade_ritmo", 30)
        elif "normal" in comando:
            pedido_intensidade = ComandoAbajur("intensidade_ritmo", 50)

    if (
        not any(nome in comando for nome in ("abajur", "lampada", "luz"))
        and pedido_musica is None
        and pedido_intensidade is None
        and pedido_tocha is None
    ):
        return []

    rgb = None if pedido_musica is not None else re.search(
        r"\brgb\s+(\d{1,3})[ ,]+(\d{1,3})[ ,]+(\d{1,3})\b", comando
    )
    if rgb:
        canais = tuple(map(int, rgb.groups()))
        if all(0 <= canal <= 255 for canal in canais):
            return [ComandoAbajur("rgb", canais)]

    hexadecimal = None if pedido_musica is not None else re.search(
        r"\b(?:hex|hexadecimal)\s*#?([0-9a-f]{6})\b", comando
    )
    if hexadecimal:
        return [ComandoAbajur("rgb", resolver_cor(hexadecimal.group(1)))]

    pedidos: list[ComandoAbajur] = []

    # "Temperatura de cor mais baixa" significa menos Kelvin, portanto luz
    # mais quente. A ordem é intencional: em um pedido composto a temperatura
    # deve ser aplicada antes do brilho.
    temperatura: str | None = None
    if any(frase in comando for frase in (
        "branco quente", "luz quente", "lampada quente", "abajur quente",
    )) or re.search(
        r"temperatura(?: da (?:cor|luz|lampada|abajur))?.{0,24}\b(?:mais baixa|menor)\b",
        comando,
    ) or re.search(
        r"(?:luz|lampada|abajur).{0,32}\b(?:mais\s+)?quente\b", comando,
    ):
        temperatura = "quente"
    elif any(frase in comando for frase in (
        "branco frio", "luz fria", "lampada fria", "abajur frio",
    )) or re.search(
        r"temperatura(?: da (?:cor|luz|lampada|abajur))?.{0,24}\b(?:mais alta|maior)\b",
        comando,
    ) or re.search(
        r"(?:luz|lampada|abajur).{0,32}\b(?:mais\s+)?(?:fria|gelada)\b", comando,
    ):
        temperatura = "fria"
    elif any(frase in comando for frase in (
        "luz branca", "lampada branca", "abajur branco", "abajur branca",
        "temperatura neutra", "branco neutro",
    )):
        temperatura = "neutra"
    if temperatura:
        pedidos.append(ComandoAbajur("temperatura", temperatura))

    if pedido_musica is None or pedido_musica.valor is None:
        for palavra, cor in sorted(CORES.items(), key=lambda item: len(item[0]), reverse=True):
            padrao = rf"(?<![a-zà-ÿ]){re.escape(palavra)}(?![a-zà-ÿ])"
            if re.search(padrao, comando, flags=re.IGNORECASE):
                pedidos.append(ComandoAbajur("cor", cor))
                break

    percentual = re.search(
        r"\b(100|[1-9]?\d)\s*(?:%|por cento)(?=\s|$)", comando
    )
    if percentual and not topico_intensidade_ritmo and any(palavra in comando for palavra in (
        "brilho", "intensidade", "luminosidade", "clareia", "escureca",
    )):
        valor = int(percentual.group(1))
        relativo = any(palavra in comando for palavra in (
            "diminua", "diminui", "reduza", "reduz", "abaixe", "abaixa",
            "aumente", "aumenta", "eleve", "suba",
        )) and not re.search(
            r"\b(?:para|ate|a)\s+(?:o\s+)?(?:brilho\s+)?\d", comando
        )
        if relativo:
            direcao = -1 if any(palavra in comando for palavra in (
                "diminua", "diminui", "reduza", "reduz", "abaixe", "abaixa",
            )) else 1
            pedidos.append(ComandoAbajur("brilho_relativo", direcao * valor))
        else:
            pedidos.append(ComandoAbajur("brilho", valor))

    if pedido_intensidade is not None:
        pedidos.append(pedido_intensidade)

    if pedido_tocha is not None:
        pedidos.append(pedido_tocha)

    if pedido_musica is not None:
        pedidos.append(pedido_musica)

    # Cor, temperatura e brilho já ligam a lâmpada nos dois controladores. Isso
    # também preserva a precedência de "acenda a lâmpada azul" como ajuste de cor.
    if not pedidos:
        if any(palavra in comando for palavra in ("desliga", "desligue", "apaga", "apague")):
            pedidos.append(ComandoAbajur("energia", False))
        elif any(palavra in comando for palavra in ("liga", "ligue", "acenda", "acende")):
            pedidos.append(ComandoAbajur("energia", True))
    return pedidos


def interpretar_comando_abajur(comando: str) -> ComandoAbajur | None:
    """Compatibilidade com chamadas antigas que esperam apenas uma ação."""
    pedidos = interpretar_comandos_abajur(comando)
    return pedidos[0] if pedidos else None


class ControleAbajurElgin:
    """Aciona o painel Tuya/Thing do Elgin Smart usando a interface oficial."""

    _COORDENADAS_CORES = {
        "vermelho": (840, 1000),
        "amarelo": (690, 740),
        "verde": (390, 740),
        "ciano": (240, 1000),
        "azul": (390, 1260),
        "roxo": (620, 1285),
        "rosa": (790, 1150),
    }
    _COORDENADAS_TEMPERATURA = {
        "quente": (325, 1235),
        "neutra": (540, 500),
        "fria": (755, 1235),
    }
    _COORDENADA_CARTAO_ABAJUR = (540, 500)

    def __init__(self, adb: str | None = None, pasta_dados: Path | None = None) -> None:
        self.adb = adb or self._encontrar_adb()
        self._largura, self._altura = TAMANHO_REFERENCIA
        raiz_dados = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Nebula"
        self._pasta_dados = pasta_dados or raiz_dados
        self._ritmo_navegador: object | None = None
        # Mantém o modo escolhido durante comandos compostos. Sem isso, ajustar
        # o brilho logo depois da temperatura abriria a aba Color e desfaria o
        # branco quente/frio que acabou de ser aplicado.
        self._modo_ativo: str | None = None
        # Mais contraste por padrão, ainda ajustável enquanto a animação roda.
        from ritmo_navegador import INTENSIDADE_RITMO_PADRAO

        self._intensidade_ritmo = INTENSIDADE_RITMO_PADRAO

    def _parar_ritmo_ativo(self) -> object | None:
        ritmo = self._ritmo_navegador
        if ritmo is not None:
            try:
                ritmo.parar()  # type: ignore[attr-defined]
            except RuntimeError as exc:
                mensagem = str(exc).strip() or (
                    "A tarefa anterior do modo música ainda está sendo encerrada."
                )
                raise ErroAbajur(mensagem) from exc
            self._ritmo_navegador = None
        return ritmo

    @staticmethod
    def _encontrar_adb() -> str:
        configurado = os.environ.get("NEBULA_ADB")
        candidatos = [
            configurado,
            shutil.which("adb"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe"),
        ]
        for candidato in candidatos:
            if candidato and Path(candidato).is_file():
                return candidato
        raise ErroAbajur("Não encontrei o ADB. Instale o Android SDK Platform Tools.")

    def _executar(self, *argumentos: str, timeout: float = 12) -> str:
        try:
            resultado = subprocess.run(
                [self.adb, *argumentos],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErroAbajur(f"Falha ao conversar com o celular: {exc}") from exc
        if resultado.returncode:
            detalhe = (resultado.stderr or resultado.stdout).strip()
            raise ErroAbajur(detalhe or "O ADB recusou o comando.")
        return resultado.stdout

    @staticmethod
    def _verificar_cancelamento(cancelar: object | None) -> None:
        if cancelar is not None and cancelar.is_set():  # type: ignore[attr-defined]
            raise ErroAbajur("A preparação do modo música foi cancelada.")

    @classmethod
    def _aguardar_cancelavel(cls, segundos: float, cancelar: object | None) -> None:
        if cancelar is None:
            time.sleep(segundos)
        elif cancelar.wait(segundos):  # type: ignore[attr-defined]
            cls._verificar_cancelamento(cancelar)

    def _preparar(self, cancelar: object | None = None) -> None:
        self._verificar_cancelamento(cancelar)
        try:
            estado = self._executar("get-state").strip()
        except ErroAbajur as exc:
            detalhe = str(exc).casefold()
            if any(
                indicio in detalhe
                for indicio in (
                    "no devices/emulators found",
                    "device not found",
                    "device offline",
                    "unauthorized",
                )
            ):
                raise ErroAbajur(
                    "O celular não está conectado ou não autorizou a depuração USB."
                ) from exc
            raise
        if estado != "device":
            raise ErroAbajur("O celular não está conectado ou não autorizou a depuração USB.")
        self._verificar_cancelamento(cancelar)
        tamanho = self._executar("shell", "wm", "size")
        self._verificar_cancelamento(cancelar)
        encontrados = re.findall(r"(\d+)x(\d+)", tamanho)
        if encontrados:
            self._largura, self._altura = map(int, encontrados[-1])

    def _toque(self, x: int, y: int) -> None:
        ref_largura, ref_altura = TAMANHO_REFERENCIA
        real_x = round(x * self._largura / ref_largura)
        real_y = round(y * self._altura / ref_altura)
        self._executar("shell", "input", "tap", str(real_x), str(real_y))

    def _abrir_inicio(self, cancelar: object | None = None) -> None:
        self._verificar_cancelamento(cancelar)
        self._executar("shell", "cmd", "statusbar", "collapse")
        self._verificar_cancelamento(cancelar)
        # Reiniciar somente o app Elgin evita que o Android restaure o painel
        # React Native da lâmpada quando precisamos ler a lista de dispositivos.
        self._executar("shell", "am", "force-stop", PACOTE_ELGIN)
        self._verificar_cancelamento(cancelar)
        self._executar(
            "shell", "am", "start", "-W", "-n",
            f"{PACOTE_ELGIN}/com.smart.ThingSplashActivity",
            timeout=20,
        )
        self._aguardar_cancelavel(3, cancelar)

    def _hierarquia(self, cancelar: object | None = None) -> ElementTree.Element:
        self._verificar_cancelamento(cancelar)
        remoto = "/sdcard/nebula-elgin-ui.xml"
        self._executar("shell", "uiautomator", "dump", remoto, timeout=15)
        self._verificar_cancelamento(cancelar)
        xml = self._executar("exec-out", "cat", remoto)
        self._verificar_cancelamento(cancelar)
        try:
            return ElementTree.fromstring(xml)
        except ElementTree.ParseError as exc:
            raise ErroAbajur("O app Elgin Smart não apresentou uma tela legível.") from exc

    @staticmethod
    def _centro(elemento: ElementTree.Element) -> tuple[int, int]:
        numeros = [int(numero) for numero in re.findall(r"\d+", elemento.attrib.get("bounds", ""))]
        if len(numeros) != 4:
            raise ErroAbajur("Não consegui localizar o controle na tela do Elgin Smart.")
        return ((numeros[0] + numeros[2]) // 2, (numeros[1] + numeros[3]) // 2)

    @staticmethod
    def _por_id(raiz: ElementTree.Element, identificador: str) -> ElementTree.Element:
        for elemento in raiz.iter("node"):
            if elemento.attrib.get("resource-id") == f"{PACOTE_ELGIN}:id/{identificador}":
                return elemento
        raise ErroAbajur("A lâmpada Smart color não apareceu na tela inicial do Elgin Smart.")

    def _estado_e_elementos(
        self,
        cancelar: object | None = None,
    ) -> tuple[bool, str, ElementTree.Element, ElementTree.Element]:
        self._abrir_inicio(cancelar)
        raiz = self._hierarquia(cancelar)
        status = self._por_id(raiz, "statusView")
        interruptor = self._por_id(raiz, "switchButton")
        texto_status = status.attrib.get("text", "")
        ligado = "ON" in texto_status.upper()
        return ligado, texto_status, interruptor, self._por_id(raiz, "deviceName")

    @staticmethod
    def _extrair_brilho_status(texto_status: str) -> int:
        """Lê o primeiro percentual do cartão (brilho, temperatura, timer)."""
        percentuais = re.findall(r"(?<!\d)(100|\d{1,2})\s*%", texto_status)
        if not percentuais:
            raise ErroAbajur("Não consegui ler o brilho atual no Elgin Smart.")
        return int(percentuais[0])

    def _brilho_atual(self) -> int:
        self._preparar()
        _, texto_status, _, _ = self._estado_e_elementos()
        return self._extrair_brilho_status(texto_status)

    def energia(self, ligar: bool) -> None:
        self._parar_ritmo_ativo()
        self._preparar()
        ligado, _, interruptor, _ = self._estado_e_elementos()
        if ligado != ligar:
            x, y = self._centro(interruptor)
            self._executar("shell", "input", "tap", str(x), str(y))
            time.sleep(1)

    def _abrir_painel(self, cancelar: object | None = None) -> None:
        ligado, _, interruptor, dispositivo = self._estado_e_elementos(cancelar)
        if not ligado:
            x, y = self._centro(interruptor)
            self._executar("shell", "input", "tap", str(x), str(y))
            self._aguardar_cancelavel(1, cancelar)
        self._verificar_cancelamento(cancelar)
        x, y = self._centro(dispositivo)
        self._executar("shell", "input", "tap", str(x), str(y))
        self._aguardar_cancelavel(3, cancelar)

    def _abrir_painel_ritmo(self, cancelar: object | None = None) -> None:
        """Abre o cartão conhecido sem depender de um dump possivelmente antigo."""
        self._abrir_inicio(cancelar)
        self._verificar_cancelamento(cancelar)
        self._toque(*self._COORDENADA_CARTAO_ABAJUR)
        self._aguardar_cancelavel(3, cancelar)

    def cor(self, nome: str) -> None:
        self._parar_ritmo_ativo()
        if nome not in self._COORDENADAS_CORES:
            raise ErroAbajur(f"A cor {nome} ainda não está configurada.")
        self._preparar()
        self._abrir_painel()
        self._toque(440, 305)  # aba Color
        time.sleep(0.5)
        self._toque(*self._COORDENADAS_CORES[nome])
        self._modo_ativo = "color"

    def temperatura(self, nome: str) -> None:
        self._parar_ritmo_ativo()
        if nome not in self._COORDENADAS_TEMPERATURA:
            raise ErroAbajur(f"A temperatura {nome} ainda não está configurada.")
        self._preparar()
        self._abrir_painel()
        self._toque(220, 305)  # aba White
        time.sleep(0.5)
        self._toque(*self._COORDENADAS_TEMPERATURA[nome])
        self._modo_ativo = "white"

    def brilho(self, percentual: int) -> None:
        self._parar_ritmo_ativo()
        if not 1 <= percentual <= 100:
            raise ErroAbajur("O brilho deve ficar entre 1 e 100 por cento.")
        self._preparar()
        self._abrir_painel()
        modo = self._modo_ativo or "color"
        if modo == "white":
            self._toque(220, 305)
            y_brilho = 1645
        else:
            self._toque(440, 305)
            y_brilho = 1540
        time.sleep(0.5)
        x = round(200 + (880 - 200) * percentual / 100)
        self._toque(x, y_brilho)
        self._modo_ativo = modo

    def ajustar_brilho(self, variacao: int) -> int:
        """Altera o brilho atual e devolve o percentual efetivamente aplicado."""
        if not -99 <= variacao <= 99 or variacao == 0:
            raise ErroAbajur("O ajuste de brilho deve ficar entre 1 e 99 por cento.")
        atual = self._brilho_atual()
        novo = max(1, min(100, atual + variacao))
        self.brilho(novo)
        return novo

    def iniciar_ritmo_navegador(self, cor_fixa: tuple[int, int, int] | None = None) -> None:
        """Inicia a animação alimentada somente pela sessão do navegador no PC."""
        _validar_dependencias_ritmo()
        from ritmo_navegador import RitmoNavegador

        if cor_fixa is None and self._modo_ativo not in {"white", "color"}:
            raise ErroAbajur(
                "Escolha primeiro uma cor ou temperatura para o abajur; "
                "depois ative o modo música."
            )
        # Um novo pedido pode trocar a cor fixa de uma animação já ativa. Antes
        # ele era confirmado pela Nebu, mas simplesmente ignorado neste ponto.
        self._parar_ritmo_ativo()
        ritmo = RitmoNavegador(self, cor_fixa=cor_fixa)
        self._ritmo_navegador = ritmo
        try:
            ritmo.iniciar()
        except RuntimeError as exc:
            if not ritmo.ativo:
                self._ritmo_navegador = None
            mensagem = str(exc).strip() or "O modo ritmo falhou ao iniciar no celular."
            raise ErroAbajur(mensagem) from exc
        # ``iniciar`` só retorna depois do handshake; a checagem também cobre
        # uma implementação substituta que tenha encerrado a thread sem erro.
        if ritmo.erro is not None or not ritmo.ativo:
            if ritmo.ativo:
                try:
                    ritmo.parar()
                except RuntimeError as exc:
                    raise ErroAbajur(str(exc)) from exc
            self._ritmo_navegador = None
            raise ErroAbajur("O modo ritmo falhou ao iniciar no celular.")
        if cor_fixa is not None:
            self._modo_ativo = "color"

    def definir_intensidade_ritmo(self, percentual: int) -> int:
        if isinstance(percentual, bool) or not isinstance(percentual, int):
            raise ErroAbajur("A intensidade do pulso precisa ser um número inteiro.")
        if not 1 <= percentual <= 100:
            raise ErroAbajur("A intensidade do pulso deve ficar entre 1 e 100 por cento.")
        self._intensidade_ritmo = percentual
        return percentual

    def ajustar_intensidade_ritmo(self, variacao: int) -> int:
        if isinstance(variacao, bool) or not isinstance(variacao, int) or variacao == 0:
            raise ErroAbajur("O ajuste da intensidade do pulso precisa ser um inteiro diferente de zero.")
        if not -99 <= variacao <= 99:
            raise ErroAbajur("O ajuste da intensidade deve ficar entre 1 e 99 por cento.")
        self._intensidade_ritmo = max(1, min(100, self._intensidade_ritmo + variacao))
        return self._intensidade_ritmo

    def iniciar_modo_tocha(self) -> None:
        from animacao_tocha import AnimacaoTochaADB

        self._parar_ritmo_ativo()
        animacao = AnimacaoTochaADB(self)
        self._ritmo_navegador = animacao
        try:
            animacao.iniciar()
        except RuntimeError as exc:
            if not animacao.ativo:
                self._ritmo_navegador = None
            raise ErroAbajur(str(exc)) from exc
        self._modo_ativo = "color"

    def parar_modo_tocha(self) -> None:
        self.parar_ritmo_navegador()

    def parar_ritmo_navegador(self) -> None:
        ritmo = self._parar_ritmo_ativo()
        if ritmo is not None and getattr(ritmo, "erro", None):
            raise ErroAbajur("A animação do abajur foi interrompida por uma falha no celular.")

    @property
    def _arquivo_cores(self) -> Path:
        return self._pasta_dados / "cores_abajur.json"

    def _carregar_cores(self) -> dict[str, str]:
        try:
            dados = json.loads(self._arquivo_cores.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ErroAbajur(f"Não consegui ler as cores salvas: {exc}") from exc
        if not isinstance(dados, dict):
            raise ErroAbajur("O arquivo de cores salvas está inválido.")
        return {str(nome): str(valor) for nome, valor in dados.items()}

    def salvar_cor(self, nome: str, especificacao: str) -> str:
        """Guarda uma cor RGB em um arquivo local da Nebula."""
        vermelho, verde, azul = resolver_cor(especificacao)
        return self._salvar_rgb(nome, vermelho, verde, azul)

    def _salvar_rgb(self, nome: str, vermelho: int, verde: int, azul: int) -> str:
        nome = _nome_preset(nome)
        hexadecimal = f"#{vermelho:02X}{verde:02X}{azul:02X}"
        cores = self._carregar_cores()
        cores[nome] = hexadecimal
        self._pasta_dados.mkdir(parents=True, exist_ok=True)
        temporario = self._arquivo_cores.with_suffix(".tmp")
        try:
            temporario.write_text(
                json.dumps(cores, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporario.replace(self._arquivo_cores)
        except OSError as exc:
            raise ErroAbajur(f"Não consegui salvar a cor: {exc}") from exc
        return hexadecimal

    def capturar_cor_atual(self) -> tuple[int, int, int]:
        """Lê matiz, brilho e saturação selecionados no painel Color."""
        try:
            from PIL import Image
        except ImportError as exc:
            raise ErroAbajur("O Pillow não está instalado para ler a cor da tela.") from exc

        self._parar_ritmo_ativo()
        self._preparar()
        self._abrir_painel()
        self._toque(440, 305)
        self._modo_ativo = "color"
        time.sleep(0.8)
        try:
            captura = subprocess.run(
                [self.adb, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ErroAbajur(f"Não consegui capturar a tela do Elgin Smart: {exc}") from exc
        if captura.returncode or not captura.stdout:
            raise ErroAbajur("O celular não devolveu a tela do Elgin Smart.")
        try:
            imagem = Image.open(BytesIO(captura.stdout)).convert("RGB")
        except OSError as exc:
            raise ErroAbajur("A captura do painel de cores está inválida.") from exc

        largura, altura = imagem.size
        escala_x, escala_y = largura / 1080, altura / 2400
        centro_x, centro_y = 540 * escala_x, 1000 * escala_y
        candidatos: list[tuple[int, int]] = []
        for y in range(round(620 * escala_y), round(1380 * escala_y), 2):
            for x in range(round(140 * escala_x), round(940 * escala_x), 2):
                r, g, b = imagem.getpixel((x, y))
                distancia = math.hypot(x - centro_x, y - centro_y)
                if r > 235 and g > 235 and b > 235 and 230 * escala_x < distancia < 390 * escala_x:
                    candidatos.append((x, y))
        if len(candidatos) < 80:
            raise ErroAbajur("Não localizei o seletor da roda de cores na tela.")
        seletor_x = statistics.fmean(x for x, _ in candidatos)
        seletor_y = statistics.fmean(y for _, y in candidatos)
        matiz = (math.atan2(-(seletor_y - centro_y), seletor_x - centro_x) / (2 * math.pi)) % 1.0

        def centro_controle(y_inicio: int, y_fim: int) -> float:
            contagens: list[tuple[int, int]] = []
            for x in range(round(180 * escala_x), round(910 * escala_x)):
                quantidade = 0
                for y in range(round(y_inicio * escala_y), round(y_fim * escala_y)):
                    r, g, b = imagem.getpixel((x, y))
                    if r > 235 and g > 235 and b > 235:
                        quantidade += 1
                contagens.append((x, quantidade))
            maximo = max((quantidade for _, quantidade in contagens), default=0)
            xs = [x for x, quantidade in contagens if quantidade >= maximo - 3 and quantidade > 25 * escala_y]
            if not xs:
                raise ErroAbajur("Não localizei os controles de brilho e saturação.")
            return statistics.fmean(xs) / escala_x

        x_brilho = centro_controle(1460, 1630)
        x_saturacao = centro_controle(1660, 1810)
        brilho = max(0.01, min((x_brilho - 200) / 680, 1.0))
        saturacao = max(0.0, min((x_saturacao - 200) / 645, 1.0))
        vermelho, verde, azul = colorsys.hsv_to_rgb(matiz, saturacao, brilho)
        return round(vermelho * 255), round(verde * 255), round(azul * 255)

    def salvar_cor_atual(self, nome: str) -> str:
        vermelho, verde, azul = self.capturar_cor_atual()
        return self._salvar_rgb(nome, vermelho, verde, azul)

    def usar_cor_salva(self, nome: str) -> None:
        nome = _nome_preset(nome)
        hexadecimal = self._carregar_cores().get(nome)
        if hexadecimal is None:
            raise ErroAbajur(f"Não encontrei uma cor salva chamada {nome}.")
        self.rgb(*resolver_cor(hexadecimal))

    def rgb(self, vermelho: int, verde: int, azul: int) -> None:
        """Aproxima uma cor RGB usando matiz, saturação e brilho do painel."""
        self._parar_ritmo_ativo()
        if not all(0 <= canal <= 255 for canal in (vermelho, verde, azul)):
            raise ErroAbajur("Cada valor RGB deve ficar entre 0 e 255.")
        matiz, saturacao, brilho = colorsys.rgb_to_hsv(
            vermelho / 255, verde / 255, azul / 255
        )
        self._preparar()
        self._abrir_painel()
        if saturacao < 0.01:
            self._toque(220, 305)
            time.sleep(0.5)
            self._toque(*self._COORDENADAS_TEMPERATURA["neutra"])
            x_brilho = round(200 + 680 * max(1, round(brilho * 100)) / 100)
            self._toque(x_brilho, 1645)
            self._modo_ativo = "white"
            return

        self._toque(440, 305)
        time.sleep(0.5)
        angulo = matiz * 2 * math.pi
        x_cor = round(540 + 300 * math.cos(angulo))
        y_cor = round(1000 - 300 * math.sin(angulo))
        self._toque(x_cor, y_cor)
        x_brilho = round(200 + 680 * max(1, round(brilho * 100)) / 100)
        x_saturacao = round(200 + 680 * round(saturacao * 100) / 100)
        self._toque(x_brilho, 1540)
        self._toque(x_saturacao, 1735)
        self._modo_ativo = "color"
