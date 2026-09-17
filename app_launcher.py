"""Descoberta e abertura segura de aplicativos instalados no Windows."""

from __future__ import annotations

import difflib
import csv
import os
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


@dataclass(frozen=True)
class Aplicativo:
    nome: str
    destino: str


class IniciadorAplicativos:
    def __init__(self) -> None:
        self.aplicativos = self._catalogar()

    def _catalogar(self) -> dict[str, Aplicativo]:
        encontrados: dict[str, Aplicativo] = {}
        pastas = (
            Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
            Path(os.environ.get("USERPROFILE", "")) / "Desktop",
            Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
        )
        ignorar = {"uninstall", "desinstalar", "help", "manual", "readme", "website"}
        for pasta in pastas:
            if not pasta.exists():
                continue
            for caminho in pasta.rglob("*"):
                if caminho.suffix.lower() not in {".lnk", ".url", ".appref-ms"}:
                    continue
                nome = caminho.stem
                chave = _normalizar(nome)
                if not chave or any(palavra in chave for palavra in ignorar):
                    continue
                encontrados.setdefault(chave, Aplicativo(nome, str(caminho)))

        # Aplicativos nativos nem sempre criam atalhos visíveis no Menu Iniciar.
        nativos = {
            "bloco de notas": ("Bloco de Notas", "notepad.exe"),
            "notepad": ("Bloco de Notas", "notepad.exe"),
            "calculadora": ("Calculadora", "calc.exe"),
            "calc": ("Calculadora", "calc.exe"),
            "paint": ("Paint", "mspaint.exe"),
            "explorador de arquivos": ("Explorador de Arquivos", "explorer.exe"),
            "explorador": ("Explorador de Arquivos", "explorer.exe"),
            "configuracoes": ("Configurações do Windows", "ms-settings:"),
        }
        for alias, (nome, comando) in nativos.items():
            destino = shutil.which(comando) if comando.endswith(".exe") else comando
            if destino:
                encontrados[_normalizar(alias)] = Aplicativo(nome, destino)

        # Aliases que o reconhecimento de voz costuma produzir.
        aliases = {
            "vscode": ("visual studio code", "code"),
            "vs code": ("visual studio code", "code"),
            "visual studio code": ("visual studio code", "code"),
            "brave": ("brave",),
            "navegador": ("brave",),
            "browser": ("brave",),
            "discord": ("discord",),
            "steam": ("steam",),
            "epic": ("epic games launcher",),
        }
        for alias, candidatos in aliases.items():
            for candidato in candidatos:
                app = encontrados.get(_normalizar(candidato))
                if app:
                    encontrados[_normalizar(alias)] = app
                    break
        return encontrados

    def encontrar(self, nome: str) -> Aplicativo | None:
        consulta = _normalizar(nome)
        if not consulta:
            return None
        # Jogos iniciados por URI podem não deixar um atalho próprio no Menu Iniciar.
        if consulta == "rocket league":
            return Aplicativo("Rocket League", "RocketLeague.exe")
        if consulta in self.aplicativos:
            return self.aplicativos[consulta]

        contidos = [
            app for chave, app in self.aplicativos.items()
            if consulta in chave or chave in consulta
        ]
        unicos = {app.destino: app for app in contidos}
        if len(unicos) == 1:
            return next(iter(unicos.values()))

        proximos = difflib.get_close_matches(
            consulta, self.aplicativos.keys(), n=2, cutoff=0.76
        )
        if len(proximos) == 1:
            return self.aplicativos[proximos[0]]
        return None

    @staticmethod
    def abrir(aplicativo: Aplicativo) -> None:
        if aplicativo.destino.lower().endswith(".exe"):
            subprocess.Popen([aplicativo.destino])
        else:
            os.startfile(aplicativo.destino)  # type: ignore[attr-defined]

    @staticmethod
    def _processo_ativo(nome: str) -> bool:
        resultado = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {nome}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for linha in csv.reader(resultado.stdout.splitlines()):
            if linha and linha[0].casefold() == nome.casefold():
                return True
        return False

    @classmethod
    def _aguardar_processo_fechar(cls, nome: str, segundos: float) -> bool:
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            if not cls._processo_ativo(nome):
                return True
            time.sleep(0.25)
        return not cls._processo_ativo(nome)

    @staticmethod
    def _fechar_explorador() -> tuple[bool, str]:
        """Fecha janelas de pastas sem encerrar a área de trabalho do Windows."""
        try:
            import win32com.client

            shell = win32com.client.Dispatch("Shell.Application")
            janelas = []
            for janela in shell.Windows():
                try:
                    executavel = Path(str(janela.FullName)).name.casefold()
                    if executavel == "explorer.exe":
                        janelas.append(janela)
                except Exception:
                    continue
            if not janelas:
                return False, "Não encontrei nenhuma janela do Explorador de Arquivos aberta."
            for janela in janelas:
                janela.Quit()
            quantidade = len(janelas)
            texto = "janela" if quantidade == 1 else "janelas"
            return True, f"Fechei {quantidade} {texto} do Explorador de Arquivos."
        except Exception as exc:
            return False, f"Não consegui fechar o Explorador de Arquivos. {exc}"

    @classmethod
    def _fechar_steam(cls) -> tuple[bool, str]:
        if not cls._processo_ativo("steam.exe"):
            return False, "Não encontrei a Steam aberta."

        caminhos = (
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Steam/steam.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Steam/steam.exe",
        )
        executavel = next((str(c) for c in caminhos if c.is_file()), None)
        if executavel:
            try:
                subprocess.run(
                    [executavel, "-shutdown"],
                    capture_output=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            if cls._aguardar_processo_fechar("steam.exe", 6):
                return True, "Steam foi fechada."

        # A confirmação do usuário já foi obtida. Se o cliente ignorar o pedido
        # gracioso, encerra também os processos filhos da interface da Steam.
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", "steam.exe"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cls._aguardar_processo_fechar("steam.exe", 3):
            return True, "Steam e seus processos de interface foram fechados."
        return False, "Tentei fechar a Steam, mas o processo continua aberto."

    @classmethod
    def fechar(cls, aplicativo: Aplicativo) -> tuple[bool, str]:
        conhecidos = {
            "brave": "brave.exe", "discord": "Discord.exe",
            "visual studio code": "Code.exe", "steam": "steam.exe",
            "epic": "EpicGamesLauncher.exe", "bloco de notas": "notepad.exe",
            "rocket league": "RocketLeague.exe",
        }
        texto = _normalizar(f"{aplicativo.nome} {aplicativo.destino}")
        if "explorador" in texto or "explorer exe" in texto:
            return cls._fechar_explorador()
        if "steam" in texto:
            return cls._fechar_steam()

        processo = next((exe for nome, exe in conhecidos.items() if nome in texto), None)
        if processo is None and aplicativo.destino.lower().endswith(".exe"):
            processo = Path(aplicativo.destino).name
        if not processo:
            return False, "Não consegui identificar o processo desse aplicativo."
        if not cls._processo_ativo(processo):
            return False, f"Não encontrei {aplicativo.nome} aberto."
        resultado = subprocess.run(
            ["taskkill", "/IM", processo], capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if resultado.returncode == 0 and cls._aguardar_processo_fechar(processo, 3):
            return True, f"{aplicativo.nome} foi fechado."

        # Alguns aplicativos ignoram o encerramento normal. A confirmação
        # explícita permite o fallback forçado, incluindo processos filhos.
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", processo],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if cls._aguardar_processo_fechar(processo, 2):
            return True, f"{aplicativo.nome} foi fechado."
        detalhe = (resultado.stderr or resultado.stdout).strip()
        return False, detalhe or f"Tentei fechar {aplicativo.nome}, mas o processo continua aberto."
