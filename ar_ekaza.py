"""Controle do ar Voltas cadastrado no eKasa usando o Samsung conectado por ADB.

O eKasa continua sendo o dono dos codigos infravermelhos. A Nebula apenas abre o
painel ja configurado, le o estado visivel e aciona os mesmos botoes. Assim nao
duplicamos o controle Philips quebrado nem dependemos da nuvem da Tuya.
"""

from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Iterable
import unicodedata
from xml.etree import ElementTree

from PIL import Image


EKAZA_PACKAGE = "com.ekstech.ekaza"
NEBULA_PACKAGE = "com.nebula.assistant"
UI_DUMP = "/sdcard/nebula_ekaza_ui.xml"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula"
STATE_FILE = CONFIG_DIR / "ar_ekaza.json"

MODES = {
    "cool": "Ar Frio",
    "heat": "Ar Quente",
    "auto": "Auto",
    "fan": "Fornecer ar",
    "dry": "Desumidificacao",
}
FANS = {
    "auto": "Auto",
    "low": "Fraco",
    "medium": "Medio",
    "high": "Forte",
}


class ErroAr(RuntimeError):
    """Falha segura e compreensivel ao controlar o ar pelo eKasa."""


def _normalizar(texto: object) -> str:
    bruto = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in bruto if unicodedata.category(c) != "Mn").casefold().strip()


def _bounds(valor: str) -> tuple[int, int, int, int] | None:
    achou = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", valor or "")
    return tuple(map(int, achou.groups())) if achou else None  # type: ignore[return-value]


def _centro(valor: str) -> tuple[int, int] | None:
    limites = _bounds(valor)
    if limites is None:
        return None
    x1, y1, x2, y2 = limites
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _modo_codigo(rotulo: str) -> str | None:
    valor = _normalizar(rotulo).removeprefix("modo:").strip()
    for codigo, nome in MODES.items():
        if valor == _normalizar(nome):
            return codigo
    return None


def _fan_codigo(rotulo: str) -> str | None:
    valor = _normalizar(rotulo).removeprefix("velocidade:").strip()
    for codigo, nome in FANS.items():
        if valor == _normalizar(nome):
            return codigo
    return None


class ControleArEkaza:
    """Espelha o controle Voltas do eKasa sem conhecer codigos IR proprietarios."""

    def __init__(self, state_file: Path = STATE_FILE, adb: str | None = None) -> None:
        self.state_file = state_file
        self.adb = adb or self._localizar_adb()
        self._lock = threading.RLock()
        self._state: dict[str, object] = {
            "available": bool(self.adb),
            "power": False,
            "temperature": 17,
            "mode": "cool",
            "fan": "high",
            "source": "eKasa no Samsung via USB",
        }
        self._carregar()

    @staticmethod
    def _localizar_adb() -> str | None:
        encontrado = shutil.which("adb") or shutil.which("adb.exe")
        if encontrado:
            return encontrado
        local = os.environ.get("LOCALAPPDATA", "")
        candidato = Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        return str(candidato) if candidato.is_file() else None

    def _carregar(self) -> None:
        try:
            dados = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        if isinstance(dados.get("power"), bool):
            self._state["power"] = dados["power"]
        if isinstance(dados.get("temperature"), int) and 16 <= dados["temperature"] <= 30:
            self._state["temperature"] = dados["temperature"]
        if dados.get("mode") in MODES:
            self._state["mode"] = dados["mode"]
        if dados.get("fan") in FANS:
            self._state["fan"] = dados["fan"]

    def _salvar(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.state_file.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporario.replace(self.state_file)

    def estado(self) -> dict[str, object]:
        with self._lock:
            estado = dict(self._state)
        estado["available"] = bool(self.adb)
        estado["mode_label"] = MODES.get(str(estado.get("mode")), "")
        estado["fan_label"] = FANS.get(str(estado.get("fan")), "")
        return estado

    def _run(
        self, argumentos: Iterable[str], *, timeout: float = 12, binary: bool = False
    ) -> bytes | str:
        if not self.adb:
            raise ErroAr("O ADB do Android nao foi encontrado neste computador.")
        try:
            resultado = subprocess.run(
                [self.adb, *argumentos],
                capture_output=True,
                text=not binary,
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ErroAr("Nao consegui conversar com o Samsung pelo USB.") from exc
        if resultado.returncode:
            erro = resultado.stderr if isinstance(resultado.stderr, str) else ""
            if "no devices" in erro.casefold() or "not found" in erro.casefold():
                raise ErroAr("Conecte o Samsung ao PC e autorize a depuracao USB.")
            raise ErroAr("O Samsung nao respondeu ao controle do eKasa.")
        return resultado.stdout

    def _foco_atual(self) -> str:
        saida = str(self._run(["shell", "dumpsys", "window"], timeout=8))
        achou = re.search(r"mCurrentFocus=.*?\s([a-zA-Z0-9_.]+)/", saida)
        return achou.group(1) if achou else ""

    def _abrir_pacote(self, pacote: str) -> None:
        self._run(
            ["shell", "monkey", "-p", pacote, "-c", "android.intent.category.LAUNCHER", "1"],
            timeout=10,
        )

    def _dump(self) -> ElementTree.Element:
        self._run(["shell", "uiautomator", "dump", UI_DUMP], timeout=10)
        bruto = self._run(["exec-out", "cat", UI_DUMP], timeout=8, binary=True)
        try:
            return ElementTree.fromstring(bytes(bruto))
        except (ElementTree.ParseError, TypeError) as exc:
            raise ErroAr("Nao consegui ler o painel do ar no eKasa.") from exc

    @staticmethod
    def _textos(raiz: ElementTree.Element) -> list[str]:
        return [str(no.attrib.get("text", "")) for no in raiz.iter() if no.attrib.get("text")]

    @staticmethod
    def _no_texto(raiz: ElementTree.Element, texto: str) -> ElementTree.Element | None:
        procurado = _normalizar(texto)
        for no in raiz.iter():
            if _normalizar(no.attrib.get("text")) == procurado:
                return no
        return None

    def _tocar_no(self, raiz: ElementTree.Element, no: ElementTree.Element) -> None:
        pais = {filho: pai for pai in raiz.iter() for filho in pai}
        alvo = no
        atual = no
        while atual in pais:
            atual = pais[atual]
            if atual.attrib.get("clickable") == "true" or atual.attrib.get("focusable") == "true":
                alvo = atual
                break
        ponto = _centro(alvo.attrib.get("bounds", "")) or _centro(no.attrib.get("bounds", ""))
        if ponto is None:
            raise ErroAr("O botao esperado nao apareceu no painel do eKasa.")
        self._run(["shell", "input", "tap", str(ponto[0]), str(ponto[1])], timeout=6)

    def _tocar_texto(self, raiz: ElementTree.Element, texto: str) -> None:
        no = self._no_texto(raiz, texto)
        if no is None:
            raise ErroAr(f"O eKasa nao mostrou o controle {texto}.")
        self._tocar_no(raiz, no)

    def _tocar_temperatura(self, raiz: ElementTree.Element, aumentar: bool) -> None:
        no = next((
            item for item in raiz.iter()
            if re.fullmatch(r"(?:1[6-9]|2\d|30)", str(item.attrib.get("text", "")))
        ), None)
        limites_raiz = _bounds(raiz.attrib.get("bounds", ""))
        limites_temp = _bounds(no.attrib.get("bounds", "")) if no is not None else None
        if limites_raiz is None or limites_temp is None:
            raise ErroAr("O eKasa nao mostrou os botoes de temperatura.")
        largura = limites_raiz[2] - limites_raiz[0]
        y = (limites_temp[1] + limites_temp[3]) // 2
        x = round(largura * (0.72 if aumentar else 0.28))
        self._run(["shell", "input", "tap", str(x), str(y)], timeout=6)

    def _painel_aberto(self, raiz: ElementTree.Element) -> bool:
        textos = [_normalizar(texto) for texto in self._textos(raiz)]
        return "ar" in textos and "interruptor" in textos and any(t.startswith("modo:") for t in textos)

    def _abrir_painel(self) -> ElementTree.Element:
        self._abrir_pacote(EKAZA_PACKAGE)
        time.sleep(1.2)
        for _ in range(9):
            raiz = self._dump()
            if self._painel_aberto(raiz):
                return raiz
            textos = [_normalizar(texto) for texto in self._textos(raiz)]
            if "ar" in textos and "voltas" in textos:
                self._tocar_texto(raiz, "Ar")
            elif "smart ir" in textos:
                self._tocar_texto(raiz, "Smart IR")
            else:
                time.sleep(0.8)
                continue
            time.sleep(1.4)
        raise ErroAr("Abra o eKasa e confirme se o controle Ar Voltas ainda esta cadastrado.")

    def _captura(self) -> Image.Image:
        bruto = self._run(["exec-out", "screencap", "-p"], timeout=10, binary=True)
        try:
            return Image.open(BytesIO(bytes(bruto))).convert("RGB")
        except (OSError, TypeError) as exc:
            raise ErroAr("Nao consegui confirmar se o ar esta ligado.") from exc

    def _ligado_visual(self) -> bool:
        imagem = self._captura()
        x, y = imagem.width // 2, round(imagem.height * 0.842)
        r, g, b = imagem.getpixel((x, min(imagem.height - 1, y)))
        return g > r + 25 and g > b + 15

    def _ler_painel(self, raiz: ElementTree.Element, ligado: bool | None = None) -> None:
        textos = self._textos(raiz)
        temperatura = next((int(t) for t in textos if re.fullmatch(r"(?:1[6-9]|2\d|30)", t)), None)
        modo = next((_modo_codigo(t) for t in textos if _normalizar(t).startswith("modo:")), None)
        fan = next((_fan_codigo(t) for t in textos if _normalizar(t).startswith("velocidade:")), None)
        if temperatura is not None:
            self._state["temperature"] = temperatura
        if modo:
            self._state["mode"] = modo
        if fan:
            self._state["fan"] = fan
        if ligado is not None:
            self._state["power"] = ligado

    def _alternar_energia(self, raiz: ElementTree.Element, desejado: bool) -> ElementTree.Element:
        atual = self._ligado_visual()
        if atual != desejado:
            self._tocar_texto(raiz, "Interruptor")
            time.sleep(1.1)
            raiz = self._dump()
        self._ler_painel(raiz, desejado)
        return raiz

    def _ciclar(
        self, raiz: ElementTree.Element, prefixo: str, desejado: str, opcoes: dict[str, str]
    ) -> ElementTree.Element:
        for _ in range(len(opcoes) + 1):
            textos = self._textos(raiz)
            rotulo = next((t for t in textos if _normalizar(t).startswith(prefixo)), "")
            atual = _modo_codigo(rotulo) if prefixo == "modo:" else _fan_codigo(rotulo)
            if atual == desejado:
                return raiz
            if not rotulo:
                break
            self._tocar_texto(raiz, rotulo)
            time.sleep(0.9)
            raiz = self._dump()
        raise ErroAr("O eKasa nao encontrou a opcao escolhida para o ar.")

    def executar(self, acao: str, valor: object) -> dict[str, object]:
        acao = str(acao).strip().casefold()
        if acao not in {"power", "temperature", "mode", "fan"}:
            raise ValueError("Acao do ar invalida.")
        with self._lock:
            pacote_anterior = self._foco_atual()
            try:
                raiz = self._abrir_painel()
                ligado = self._ligado_visual()
                self._ler_painel(raiz, ligado)
                if acao == "power":
                    raiz = self._alternar_energia(raiz, bool(valor))
                else:
                    raiz = self._alternar_energia(raiz, True)
                    if acao == "temperature":
                        alvo = int(valor)
                        if not 16 <= alvo <= 30:
                            raise ValueError("A temperatura deve ficar entre 16 e 30 graus.")
                        atual = int(self._state.get("temperature", 17))
                        for _ in range(abs(alvo - atual)):
                            self._tocar_temperatura(raiz, alvo > atual)
                            time.sleep(0.55)
                            raiz = self._dump()
                    elif acao == "mode":
                        desejado = str(valor).casefold()
                        if desejado not in MODES:
                            raise ValueError("Modo do ar invalido.")
                        raiz = self._ciclar(raiz, "modo:", desejado, MODES)
                    else:
                        desejado = str(valor).casefold()
                        if desejado not in FANS:
                            raise ValueError("Velocidade do ar invalida.")
                        raiz = self._ciclar(raiz, "velocidade:", desejado, FANS)
                self._ler_painel(raiz, bool(self._state.get("power")))
                self._state["available"] = True
                self._state.pop("error", None)
                self._salvar()
            except Exception as exc:
                self._state["error"] = str(exc)
                self._salvar()
                raise
            finally:
                if pacote_anterior and pacote_anterior != EKAZA_PACKAGE:
                    try:
                        self._abrir_pacote(pacote_anterior)
                    except ErroAr:
                        pass
        return {
            "ok": True,
            "message": "Comando enviado ao ar Voltas pelo eKasa.",
            "air": self.estado(),
        }


__all__ = ["ControleArEkaza", "ErroAr", "FANS", "MODES"]
