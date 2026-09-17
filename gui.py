"""Interface gráfica da assistente virtual Nebula."""

from __future__ import annotations

import math
import base64
import json
import mimetypes
import os
import queue
import random
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
import uuid
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, scrolledtext, ttk
from urllib.error import URLError
from urllib.request import Request, urlopen
from color_wheel import ColorWheel
from device_presets import MODES as DEVICE_MODES, LABELS as MODE_LABELS

import pystray
from PIL import Image, ImageDraw, ImageTk

from grupo_chat import GrupoOcupadoError, PonteGrupo
from rocket_overlay import RocketOverlay, OVERLAY_BRIDGE
from configuracao_tuya_gui import (
    carregar_configuracao_inicial,
    criar_configuracao,
    detectar_dispositivos,
    escolher_dispositivo_preferido,
    mensagem_erro_segura,
    salvar_configuracao,
    testar_configuracao,
)
from memoria_nebula import MEMORIA, encontrar_ultima_interacao
from notebook_power_server.tv_control import TvError, TvManager
from main import (
    Microfone,
    Nebula,
    RESPOSTAS_ATIVACAO,
    Voz,
    comando_de_clipe,
    comando_incompleto,
    extrair_chamada,
    normalizar_texto,
)
from remote_server import (
    add_conversation_message, get_conversation, get_dark_mode, get_device_status,
    get_latest_job, get_pin, queue_device_command, set_dark_mode, start_server, POWER_TOKEN,
)
from transfer_chat import CHAT_STORE, MAX_FILE_BYTES
from versao import VERSAO_NEBULA


AZUL = "#a7865f"
AZUL_ESCURO = "#806849"
AZUL_CLARO = "#e6d0aa"
TEXTO = "#211f1c"
SECUNDARIO = "#706a62"
FUNDO = "#ffffff"


class BotaoArredondado(tk.Canvas):
    """Botão leve com raio consistente, sem o acabamento quadrado do Windows."""

    def __init__(
        self, pai: tk.Misc, *, text: str, command=None, bg: str = "#414144",
        fg: str = "#f4eee4", activebackground: str = "#514a40",
        activeforeground: str | None = None, anchor: str = "center",
        height: int = 42, radius: int = 12, font=("Segoe UI", 9), **kwargs,
    ) -> None:
        self._texto = text
        self._comando = command
        self._fundo = bg
        self._frente = fg
        self._fundo_ativo = activebackground
        self._frente_ativa = activeforeground or fg
        self._ancora = anchor
        self._raio = radius
        self._fonte = font
        self._estado = "normal"
        fundo_pai = str(pai.cget("bg"))
        super().__init__(
            pai, height=height, bg=fundo_pai, highlightthickness=0,
            bd=0, cursor=kwargs.pop("cursor", "hand2"), **kwargs,
        )
        self.bind("<Configure>", lambda _e: self._desenhar())
        self.bind("<Enter>", lambda _e: self._desenhar(True))
        self.bind("<Leave>", lambda _e: self._desenhar(False))
        self.bind("<Button-1>", self._clicar)
        self._desenhar()

    def _forma(self, x1: int, y1: int, x2: int, y2: int, raio: int, cor: str) -> None:
        raio = max(2, min(raio, (y2 - y1) // 2, (x2 - x1) // 2))
        self.create_rectangle(x1 + raio, y1, x2 - raio, y2, fill=cor, outline=cor)
        self.create_rectangle(x1, y1 + raio, x2, y2 - raio, fill=cor, outline=cor)
        for x, y, inicio in ((x1, y1, 90), (x2 - 2 * raio, y1, 0),
                             (x2 - 2 * raio, y2 - 2 * raio, 270),
                             (x1, y2 - 2 * raio, 180)):
            self.create_arc(x, y, x + 2 * raio, y + 2 * raio, start=inicio,
                            extent=90, fill=cor, outline=cor)

    def _desenhar(self, ativo: bool = False) -> None:
        if not self.winfo_exists():
            return
        try:
            super().configure(bg=str(self.master.cget("bg")))
        except tk.TclError:
            pass
        self.delete("all")
        largura = max(30, self.winfo_width())
        altura = max(20, self.winfo_height())
        cor = self._fundo_ativo if ativo and self._estado != "disabled" else self._fundo
        frente = self._frente_ativa if ativo else self._frente
        self._forma(1, 1, largura - 2, altura - 2, self._raio, cor)
        x = 15 if self._ancora == "w" else largura // 2
        self.create_text(x, altura // 2, text=self._texto, fill=frente,
                         font=self._fonte, anchor=self._ancora)

    def _clicar(self, _evento=None) -> None:
        if self._estado != "disabled" and self._comando:
            self._comando()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        especiais = {
            "text": "_texto", "bg": "_fundo", "fg": "_frente",
            "activebackground": "_fundo_ativo", "activeforeground": "_frente_ativa",
            "state": "_estado", "command": "_comando",
        }
        for chave, atributo in especiais.items():
            if chave in kwargs:
                setattr(self, atributo, kwargs.pop(chave))
        if kwargs:
            super().configure(**kwargs)
        self._desenhar()

    config = configure

    def cget(self, chave):
        mapa = {"text": self._texto, "bg": self._fundo, "fg": self._frente,
                "activebackground": self._fundo_ativo,
                "activeforeground": self._frente_ativa, "state": self._estado,
                "command": self._comando}
        return mapa[chave] if chave in mapa else super().cget(chave)


class PainelArredondado(tk.Canvas):
    """Superfície com cantos arredondados que recebe widgets em ``body``."""

    def __init__(self, pai: tk.Misc, *, cor="#3b3b3f", raio=10,
                 padding=12, altura_automatica=False) -> None:
        self.cor = cor
        self.raio = raio
        self.padding = padding
        self.altura_automatica = altura_automatica
        super().__init__(pai, bg=str(pai.cget("bg")), bd=0, highlightthickness=0)
        self.body = tk.Frame(self, bg=cor)
        self._janela = self.create_window(padding, padding, anchor="nw", window=self.body)
        self.bind("<Configure>", self._redesenhar)
        if altura_automatica:
            self.body.bind("<Configure>", lambda _e: self.after_idle(self._sincronizar_altura))

    def _sincronizar_altura(self) -> None:
        desejada = self.body.winfo_reqheight() + self.padding * 2
        if int(self.cget("height")) != desejada:
            super().configure(height=desejada)

    def _redesenhar(self, _evento=None) -> None:
        self.delete("painel")
        w, h = max(20, self.winfo_width()), max(20, self.winfo_height())
        r = min(self.raio, w // 2, h // 2)
        self.create_rectangle(r, 1, w-r, h-1, fill=self.cor, outline=self.cor, tags="painel")
        self.create_rectangle(1, r, w-1, h-r, fill=self.cor, outline=self.cor, tags="painel")
        for x, y, inicio in ((1, 1, 90), (w-2*r-1, 1, 0),
                             (w-2*r-1, h-2*r-1, 270), (1, h-2*r-1, 180)):
            self.create_arc(x, y, x+2*r, y+2*r, start=inicio, extent=90,
                            fill=self.cor, outline=self.cor, tags="painel")
        self.tag_lower("painel")
        self.itemconfigure(self._janela, width=max(1, w-self.padding*2),
                           height=max(1, h-self.padding*2))


class AbasArredondadas(tk.Frame):
    """Subnavegação sem abas retangulares do tema nativo."""

    def __init__(self, pai: tk.Misc) -> None:
        super().__init__(pai, bg="#303033")
        self.barra = tk.Frame(self, bg="#303033")
        self.barra.pack(fill="x", pady=(0, 10))
        self.paginas: list[tuple[tk.Widget, BotaoArredondado]] = []

    def add(self, pagina: tk.Widget, text: str) -> None:
        botao = BotaoArredondado(
            self.barra, text=text.strip(), command=lambda p=pagina: self.select(p),
            bg="#3b3b3f", fg="#b8b0a5", activebackground="#514a40",
            activeforeground="#f4eee4", width=112, height=38, radius=8,
        )
        botao.pack(side="left", padx=(0, 7))
        self.paginas.append((pagina, botao))
        if len(self.paginas) == 1:
            self.select(pagina)

    def select(self, pagina: tk.Widget) -> None:
        for item, botao in self.paginas:
            item.pack_forget()
            ativo = item is pagina
            botao.configure(bg="#6f604d" if ativo else "#3b3b3f",
                            fg="#f4eee4" if ativo else "#b8b0a5")
        pagina.pack(fill="both", expand=True)


def iniciar_servidor_do_notebook() -> None:
    """Inicia o Home Hub junto com a interface instalada no notebook."""
    if not getattr(sys, "frozen", False):
        return

    executavel = Path(sys.executable).resolve()
    if executavel.name.casefold() != "nebulanotebook.exe":
        return

    servidor = executavel.parent / "NebulaPowerServer.exe"
    if not servidor.is_file():
        return

    try:
        processos = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq NebulaPowerServer.exe", "/NH"],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if "NebulaPowerServer.exe" in processos.stdout:
            return

        subprocess.Popen(
            [str(servidor)],
            cwd=str(servidor.parent),
            close_fds=True,
        )
    except OSError:
        # A interface continua utilizavel mesmo se o componente do servidor
        # estiver ausente ou for bloqueado pelo Windows.
        pass


def caminho_recurso(*partes: str) -> str:
    """Localiza recursos no código-fonte e dentro do executável empacotado."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *partes)


class InterfaceNebula:
    def __init__(self) -> None:
        self.janela = tk.Tk()
        self.janela.title(f"Nebula {VERSAO_NEBULA}")
        self.janela.geometry("1180x780")
        self.janela.minsize(940, 620)
        self.janela.configure(bg=FUNDO)
        try:
            self._icone_janela = ImageTk.PhotoImage(
                Image.open(caminho_recurso("assets", "nebula.png"))
            )
            self.janela.iconphoto(True, self._icone_janela)
        except (OSError, tk.TclError):
            self._icone_janela = None

        # Materializa a janela antes de carregar todos os painéis e integrações.
        # Em notebooks mais lentos, a montagem completa pode levar alguns
        # segundos; sem este primeiro update o processo existia, porém o usuário
        # não recebia nenhum sinal visual de que a Nebula estava iniciando.
        self.janela.update_idletasks()
        self.janela.deiconify()
        self.janela.lift()
        self.janela.update()

        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self.comandos: queue.Queue[str] = queue.Queue()
        self.grupo = PonteGrupo(
            ao_evento=lambda tipo, valor: self._evento(f"grupo_{tipo}", valor)
        )
        self.parar = threading.Event()
        self.pausada = threading.Event()
        self.falando = False
        self.ouvindo = False
        self.fase = 0.0
        self.escala_esfera = 1.0
        self.nebula: Nebula | None = None
        self.rocket_overlay = RocketOverlay(self.janela, control_provider=self._estado_controle_remoto)
        OVERLAY_BRIDGE.register(lambda action, value: self._evento("rocket_overlay", (action, value)))
        self.tv_manager = TvManager()
        self.modo_escuro = True
        set_dark_mode(True)
        self.servidor_remoto = start_server(
            self._definir_pausa_remota, self._receber_comando_remoto,
            lambda _escuro: self._evento("tema", True),
            self.grupo,
            self._executar_controle_remoto,
            self._estado_controle_remoto,
            lambda: self.janela.after(0, self.mostrar_janela),
        )
        self.aviso_bandeja_exibido = False
        self.proxima_atualizacao_codex = 0.0
        self.ultimo_codex_renderizado = ""
        self.ultimo_mobile_renderizado = ""
        self.mensagens_renderizadas = 0
        self.historico_snapshot: list[dict[str, str]] = []

        self._montar_cabecalho()
        self._montar_aba_controle()
        self._montar_aba_casa()
        self._montar_aba_assistente()
        self._montar_aba_conversa()
        self._montar_aba_transferencia()
        self._sincronizar_historico()
        self._montar_aba_grupo()
        self._montar_aba_remoto()
        self._montar_aba_configuracao()
        self._aplicar_tema(self.modo_escuro)
        self.mostrar_aba("controle")

        self.janela.protocol("WM_DELETE_WINDOW", self.ocultar_na_bandeja)
        self.janela.after(40, self._processar_eventos)
        self.janela.after(40, self._animar_esfera)

        self.icone_bandeja = self._criar_icone_bandeja()
        self.icone_bandeja.run_detached()

        threading.Thread(target=self._executar_assistente, daemon=True).start()

    def _montar_cabecalho(self) -> None:
        self.shell = tk.Frame(self.janela, bg=FUNDO)
        self.shell.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(self.shell, bg="#292a2d", width=196)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.conteudo = tk.Frame(self.shell, bg=FUNDO)
        self.conteudo.pack(side="left", fill="both", expand=True)

        marca = tk.Frame(self.sidebar, bg="#292a2d")
        marca.pack(fill="x", padx=22, pady=(28, 30))
        tk.Label(marca, text="NEBULA", bg="#292a2d", fg=TEXTO,
                 font=("Segoe UI Semibold", 19)).pack(anchor="w")
        tk.Label(marca, text="SUA CASA. UM CONTROLE.", bg="#292a2d", fg=SECUNDARIO,
                 font=("Segoe UI Semibold", 7)).pack(anchor="w")

        navegacao = tk.Frame(self.sidebar, bg="#292a2d")
        navegacao.pack(fill="x", padx=12)
        self.botoes_abas: dict[str, tk.Button] = {}
        for chave, titulo in (
            ("controle", "◉   Modos"), ("casa", "⌂   Casa"),
            ("transferencia", "◌   Chat"),
            ("remoto", "▯   Telefone"), ("configuracao", "⚙   Ajustes"),
        ):
            botao = BotaoArredondado(
                navegacao, text=titulo, command=lambda c=chave: self.mostrar_aba(c),
                bg="#292a2d", fg="#b8b0a5", activebackground="#514a40",
                activeforeground="#f4eee4", anchor="w", height=44, radius=8,
                font=("Segoe UI", 10), cursor="hand2",
            )
            botao.pack(fill="x", pady=2)
            self.botoes_abas[chave] = botao

        rodape = tk.Frame(self.sidebar, bg="#292a2d")
        rodape.pack(side="bottom", fill="x", padx=12, pady=16)
        tk.Label(rodape, text=f"NEBULA  {VERSAO_NEBULA}", bg="#292a2d",
                 fg="#77736d", font=("Segoe UI", 7)).pack(anchor="w", padx=14)

    def _montar_aba_controle(self) -> None:
        self.aba_controle = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_controle, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=32, pady=24)
        cabecalho = tk.Frame(area, bg=FUNDO)
        cabecalho.pack(fill="x", pady=(0, 16))
        tk.Label(
            cabecalho, text="Modos e iluminação", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 23),
        ).pack(side="left")
        self.controle_botao_mudo = self._botao_painel(
            cabecalho, "Ativar modo mudo", "mute", True
        )
        self.controle_botao_mudo.pack(side="right")

        style = ttk.Style(self.janela)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TCombobox", fieldbackground="#414144", background="#414144",
            foreground="#f4eee4", arrowcolor="#e6d0aa", bordercolor="#515156",
            lightcolor="#515156", darkcolor="#515156", padding=6,
        )
        style.map(
            "TCombobox", fieldbackground=[("readonly", "#414144")],
            foreground=[("readonly", "#f4eee4")],
            selectbackground=[("readonly", "#514a40")],
            selectforeground=[("readonly", "#f4eee4")],
        )
        self.controle_subabas = AbasArredondadas(area)
        self.controle_subabas.pack(fill="both", expand=True)
        fundo_cartao = "#353538"
        lampada = tk.Frame(self.controle_subabas, bg=fundo_cartao, padx=24, pady=18)
        modos = tk.Frame(self.controle_subabas, bg=fundo_cartao, padx=24, pady=18)
        self.controle_subabas.add(lampada, text="  Abajur  ")
        self.controle_subabas.add(modos, text="  Efeitos  ")
        topo_lampada = tk.Frame(lampada, bg=fundo_cartao)
        topo_lampada.pack(fill="x", pady=(2, 18))
        tk.Label(topo_lampada, text="ILUMINAÇÃO", bg=fundo_cartao, fg=AZUL_CLARO,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")
        tk.Label(topo_lampada, text="Abajur", bg=fundo_cartao, fg="#f4eee4",
                 font=("Segoe UI Semibold", 21)).pack(anchor="w")
        tk.Label(topo_lampada, text="Controle direto pela rede Wi-Fi", bg=fundo_cartao,
                 fg="#b8b0a5", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        corpo_lampada = tk.Frame(lampada, bg=fundo_cartao)
        corpo_lampada.pack(fill="both", expand=True)
        comandos_painel = PainelArredondado(corpo_lampada, cor="#3b3b3f", raio=10, padding=18)
        comandos_painel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        comandos_lampada = comandos_painel.body
        cor_painel = PainelArredondado(corpo_lampada, cor="#3b3b3f", raio=10, padding=16)
        cor_painel.configure(width=292)
        cor_painel.pack(side="left", fill="y", padx=(10, 0))
        cor_lampada = cor_painel.body

        tk.Label(comandos_lampada, text="ENERGIA", bg="#3b3b3f", fg="#b8b0a5",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(0, 8))
        energia = tk.Frame(comandos_lampada, bg="#3b3b3f")
        energia.pack(fill="x")
        self._botao_painel(energia, "Ligar", "lamp.power", True).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        self._botao_painel(energia, "Desligar", "lamp.power", False).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        tk.Label(comandos_lampada, text="TEMPERATURA", bg="#3b3b3f", fg="#b8b0a5",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(24, 8))
        brancos = tk.Frame(comandos_lampada, bg="#3b3b3f")
        brancos.pack(fill="x")
        for titulo, valor in (("Quente", "quente"), ("Neutra", "neutra"), ("Fria", "fria")):
            self._botao_painel(brancos, titulo, "lamp.temperature", valor).pack(
                side="left", fill="x", expand=True, padx=2
            )
        tk.Label(comandos_lampada, text="BRILHO", bg="#3b3b3f", fg="#b8b0a5",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(24, 4))
        self.controle_brilho = tk.Scale(
            comandos_lampada, from_=1, to=100, orient="horizontal", bg="#3b3b3f",
            fg="#f4eee4", troughcolor="#292a2d", activebackground=AZUL_CLARO,
            highlightthickness=0, bd=0,
        )
        self.controle_brilho.set(60)
        self.controle_brilho.pack(fill="x")
        self.controle_brilho.bind(
            "<ButtonRelease-1>",
            lambda _e: self._acionar_controle_desktop(
                "lamp.brightness", self.controle_brilho.get()
            ),
        )
        tk.Label(cor_lampada, text="COR", bg="#3b3b3f", fg="#b8b0a5",
                 font=("Segoe UI Semibold", 8)).pack(anchor="w")
        wheel = ColorWheel(cor_lampada, lambda color: self._acionar_controle_desktop("lamp.color", color), size=190)
        wheel.pack(pady=(8, 6))
        tk.Label(cor_lampada, text="Arraste e solte para aplicar", bg="#3b3b3f",
                 fg="#b8b0a5", font=("Segoe UI", 9)).pack()

        self._construir_modos_independentes(modos, fundo_cartao)

        self.overlay_rocket_ativo = tk.BooleanVar(value=False)
        overlay_linha = tk.Frame(modos, bg=fundo_cartao)
        overlay_linha.pack(fill="x", pady=(4, 12))
        tk.Checkbutton(
            overlay_linha, text="Overlay do Rocket League",
            variable=self.overlay_rocket_ativo,
            command=lambda: self.rocket_overlay.apply("toggle"),
            bg=fundo_cartao, fg="#f4eee4", selectcolor="#414144",
            activebackground=fundo_cartao, activeforeground=AZUL_CLARO,
            relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2",
        ).pack(side="left")

        cor_boost = tk.Frame(modos, bg=fundo_cartao)
        cor_boost.pack(fill="x", pady=(0, 10))
        tk.Label(
            cor_boost, text="COR DO TECLADO NO BOOST", bg=fundo_cartao,
            fg="#aaaab0", font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        self.controle_cor_boost_amostra = tk.Label(
            cor_boost, text="", bg="#0050ff", width=3, relief="solid", bd=1,
        )
        self.controle_cor_boost_amostra.pack(side="right", padx=(8, 0), ipady=7)
        self.controle_cor_boost_botao = tk.Button(
            cor_boost, text="Escolher cor", command=self._escolher_cor_teclado_boost,
            bg="#414144", fg="#d1c9bd", activebackground="#6f604d",
            activeforeground="white", relief="flat", bd=0, padx=10, pady=6,
            cursor="hand2", font=("Segoe UI Semibold", 8),
        )
        self.controle_cor_boost_botao.pack(side="right")

        self.controle_status = tk.Label(
            area, text="Aguardando a Nebula iniciar...", bg=FUNDO,
            fg="#d4d4d8", anchor="w", justify="left", font=("Segoe UI", 9),
        )
        self.controle_status.pack(fill="x")
        self.janela.after(250, self._atualizar_controle_desktop)

    def _botao_painel(
        self, pai: tk.Misc, texto: str, acao: str, valor: object,
    ) -> tk.Button:
        botao = BotaoArredondado(
            pai, text=texto,
            command=lambda: self._acionar_controle_desktop(acao, valor),
            bg="#414144", fg="#d1c9bd", activebackground="#6f604d",
            activeforeground="white", height=42, radius=8, width=120,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        )
        botao._nebula_ativo = False  # type: ignore[attr-defined]
        botao.bind("<Enter>", lambda _e, b=botao: self._animar_botao(b, "#6f604d"))
        botao.bind(
            "<Leave>",
            lambda _e, b=botao: self._animar_botao(
                b, "#6f604d" if getattr(b, "_nebula_ativo", False) else "#414144"
            ),
        )
        return botao

    def _construir_modos_independentes(self, pai, fundo):
        self.controle_botoes_modo = {}
        self.controle_alvos = {}
        self.device_selectors = {}
        self.device_status = {}
        self.device_flash = {}
        tk.Label(pai, text="Cada dispositivo, seu modo", bg=fundo, fg="white",
                 font=("Segoe UI Semibold", 16)).pack(anchor="w", pady=(0, 12))
        for device, name in (("lamp", "Abajur"), ("keyboard", "Kumara"),
                             ("controller", "Controle PS4 · USB"), ("mobile", "Telefone")):
            row_painel = PainelArredondado(
                pai, cor="#3b3b3f", raio=8, padding=10, altura_automatica=True
            )
            row_painel.pack(fill="x", pady=4)
            row = row_painel.body
            tk.Label(row, text=name, width=23, anchor="w", bg="#3b3b3f", fg="#f4eee4",
                     font=("Segoe UI Semibold", 9)).pack(side="left")
            selector = ttk.Combobox(row, state="readonly", width=24,
                                   values=[MODE_LABELS[m] for m in DEVICE_MODES[device]])
            selector.current(0)
            selector.pack(side="left", padx=8)
            selector.bind("<<ComboboxSelected>>", lambda _e, d=device, s=selector:
                          self._acionar_controle_desktop("device.mode", {"device": d, "mode": DEVICE_MODES[d][s.current()]}))
            self.device_selectors[device] = selector
            if device in {"lamp", "keyboard", "controller"}:
                enabled = tk.BooleanVar(value=False)
                self.device_flash[device] = enabled
                tk.Checkbutton(row, text="Flash do escape", variable=enabled, bg="#3b3b3f", fg="#d1c9bd",
                               selectcolor="#414144", activebackground="#3b3b3f",
                               activeforeground="#f4eee4", relief="flat", bd=0,
                               command=lambda d=device, v=enabled: self._acionar_controle_desktop(
                                   "device.flash", {"device": d, "enabled": v.get()})).pack(side="left", padx=8)
            status = tk.Label(pai, text="", bg=fundo, fg="#ffad66", anchor="w")
            status.pack(fill="x")
            self.device_status[device] = status
        tk.Label(pai, text="PRESETS", bg=fundo, fg=AZUL_CLARO,
                 font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(16, 5))
        self.preset_selector = ttk.Combobox(pai, state="normal")
        self.preset_selector.pack(fill="x", pady=5)
        row = tk.Frame(pai, bg=fundo)
        row.pack(fill="x")
        for title, action in (("Salvar configuração", "preset.save"), ("▶ Aplicar", "preset.apply"), ("Excluir", "preset.delete")):
            tk.Button(row, text=title, bg="#414144", fg="white", relief="flat", padx=12, pady=9,
                      command=lambda a=action: self._acionar_controle_desktop(a, self.preset_selector.get().strip())).pack(side="left", padx=(0, 6))
        tk.Label(pai, text='Diga: “Nebula, ative o preset Corrida”. Salvar com o mesmo nome atualiza o preset.',
                 bg=fundo, fg="#aaaab0", wraplength=650, justify="left").pack(anchor="w", pady=(8, 15))

    def _animar_botao(self, botao: tk.Button, destino: str, passo: int = 0) -> None:
        try:
            origem = str(botao.cget("bg"))
            r1, g1, b1 = (int(origem[i:i + 2], 16) for i in (1, 3, 5))
            r2, g2, b2 = (int(destino[i:i + 2], 16) for i in (1, 3, 5))
        except (ValueError, tk.TclError):
            botao.configure(bg=destino)
            return
        fator = min(1.0, (passo + 1) / 6)
        cor = f"#{round(r1 + (r2-r1)*fator):02x}{round(g1 + (g2-g1)*fator):02x}{round(b1 + (b2-b1)*fator):02x}"
        botao.configure(bg=cor)
        if passo < 5:
            botao.after(18, lambda: self._animar_botao(botao, destino, passo + 1))

    def _acionar_controle_desktop(self, acao: str, valor: object) -> None:
        if acao == "mute":
            valor = not bool(self.nebula and self.nebula.modo_mudo)
        self.controle_status.configure(text="Aplicando controle...")
        threading.Thread(
            target=self._trabalhar_controle_desktop,
            args=(acao, valor), daemon=True,
        ).start()

    def _trabalhar_controle_desktop(self, acao: str, valor: object) -> None:
        try:
            resultado = self._executar_controle_remoto(acao, valor)
            self._evento("controle_resultado", resultado)
        except Exception as exc:
            self._evento("controle_erro", str(exc))

    def _alterar_alvo_desktop(self, dispositivo: str) -> None:
        modo = getattr(self, "controle_modo_atual", "manual")
        variavel, _chave = self.controle_alvos[dispositivo]
        if modo in {"manual", "starting"}:
            variavel.set(False)
            return
        self._acionar_controle_desktop(
            "mode.target",
            {"mode": modo, "device": dispositivo, "enabled": variavel.get()},
        )

    def _escolher_cor_teclado_boost(self) -> None:
        atual = str(getattr(self, "controle_cor_boost_atual", "#0050FF"))
        _rgb, escolhida = colorchooser.askcolor(
            color=atual, title="Cor do teclado no modo boost", parent=self.janela
        )
        if escolhida:
            self._acionar_controle_desktop("boost.keyboard_color", escolhida.upper())

    def _atualizar_controle_desktop(self) -> None:
        if self.parar.is_set():
            return
        estado = self._estado_controle_remoto()
        modo = str(estado.get("mode", "starting"))
        self.controle_modo_atual = modo
        devices = estado.get("devices", {})
        for device, selector in self.device_selectors.items():
            settings = devices.get(device, {})
            value = settings.get("mode", "manual")
            try:
                focado = self.janela.focus_get()
            except (KeyError, tk.TclError):
                focado = None
            if value in DEVICE_MODES[device] and selector is not focado:
                selector.current(DEVICE_MODES[device].index(value))
            self.device_status[device].configure(text=settings.get("error") or "")
            if device in self.device_flash:
                self.device_flash[device].set(bool(settings.get("afterfire")))
        self.preset_selector.configure(values=estado.get("presets", []))
        cor_boost = str(estado.get("boost_keyboard_color") or "#0050FF")
        self.controle_cor_boost_atual = cor_boost
        self.controle_cor_boost_amostra.configure(bg=cor_boost)
        self.controle_cor_boost_botao.configure(
            state="normal" if modo not in {"starting"} else "disabled"
        )
        for valor, botao in self.controle_botoes_modo.items():
            ativo = valor == modo
            botao._nebula_ativo = ativo  # type: ignore[attr-defined]
            if str(botao.cget("bg")) != "#6f604d":
                botao.configure(bg="#6f604d" if ativo else "#414144", fg="white" if ativo else "#d1c9bd")
        alvos_ativos = estado.get("targets") if isinstance(estado.get("targets"), dict) else {}
        alvos_disponiveis = set(estado.get("target_available") or [])
        for dispositivo, (variavel, chave) in self.controle_alvos.items():
            disponivel = dispositivo in alvos_disponiveis
            ativo = disponivel and bool(alvos_ativos.get(dispositivo))
            variavel.set(ativo)
            chave.configure(
                state="normal" if disponivel else "disabled",
                text="ON" if ativo else "OFF",
                bg="#6f604d" if ativo else "#414144",
                fg="white" if ativo else "#d1c9bd",
            )
        muda = bool(estado.get("muted"))
        self.controle_botao_mudo.configure(
            text="Ativar voz" if muda else "Ativar modo mudo",
            bg="#6f604d" if muda else "#414144",
        )
        if not estado.get("ready"):
            texto = "A Nebula ainda esta iniciando."
        elif modo == "independent":
            texto = "Dispositivos independentes" + (f" · preset {estado['active_preset']}" if estado.get("active_preset") else "")
        elif modo not in {"rpm", "beamng", "ambilight_rpm"}:
            texto = f"Modo atual: {modo}."
        elif not estado.get("receiving"):
            texto = "RPM ativo; aguardando telemetria do jogo."
        else:
            texto = f"Telemetria ao vivo - faixa {estado.get('range') or 'normal'}"
        self.controle_status.configure(text=estado.get("error") or texto)
        ar = estado.get("air") if isinstance(estado.get("air"), dict) else {}
        if hasattr(self, "casa_ar_temperatura"):
            self.casa_temperatura = int(ar.get("temperature", 17))
            self.casa_ar_temperatura.configure(text=f"{self.casa_temperatura} °C")
            ligado = bool(ar.get("power"))
            modo_ar = str(ar.get("mode_label") or "")
            fan_ar = str(ar.get("fan_label") or "")
            erro_ar = str(ar.get("error") or "")
            self.casa_ar_status.configure(
                text=erro_ar or f"Ar {'ligado' if ligado else 'desligado'}  •  {modo_ar}  •  {fan_ar}",
                fg="#ff8f9a" if erro_ar else "#aaaab0",
            )
        self.janela.after(250, self._atualizar_controle_desktop)

    def _montar_aba_casa(self) -> None:
        self.aba_casa = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_casa, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=32, pady=24)
        tk.Label(
            area, text="Casa conectada", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 23),
        ).pack(anchor="w", pady=(0, 16))
        colunas = tk.Frame(area, bg=FUNDO)
        colunas.pack(fill="both", expand=True)
        colunas.grid_columnconfigure(0, weight=1, uniform="casa")
        colunas.grid_columnconfigure(1, weight=1, uniform="casa")
        fundo = "#353538"

        ar = tk.Frame(colunas, bg=fundo, padx=22, pady=20)
        ar.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(ar, text="AR-CONDICIONADO VOLTAS", bg=fundo, fg=AZUL_CLARO,
                 font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(ar, text="Controle espelhado do eKasa no Samsung conectado por USB",
                 bg=fundo, fg="#aaaab0", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 14))
        energia = tk.Frame(ar, bg=fundo)
        energia.pack(fill="x")
        self._botao_painel(energia, "Ligar", "air.power", True).pack(
            side="left", fill="x", expand=True, padx=(0, 4)
        )
        self._botao_painel(energia, "Desligar", "air.power", False).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )
        temperatura = tk.Frame(ar, bg=fundo)
        temperatura.pack(fill="x", pady=(16, 10))
        self._botao_painel(temperatura, "−", "air.temperature", 16).pack(side="left")
        self.casa_temperatura = 17
        self.casa_ar_temperatura = tk.Label(
            temperatura, text="17 °C", bg=fundo, fg="white",
            font=("Segoe UI Semibold", 34),
        )
        self.casa_ar_temperatura.pack(side="left", fill="x", expand=True)
        mais = self._botao_painel(temperatura, "+", "air.temperature", 18)
        mais.pack(side="right")
        temperatura.winfo_children()[0].configure(
            command=lambda: self._acionar_controle_desktop(
                "air.temperature", max(16, self.casa_temperatura - 1)
            )
        )
        mais.configure(command=lambda: self._acionar_controle_desktop(
            "air.temperature", min(30, self.casa_temperatura + 1)
        ))
        tk.Label(ar, text="MODO", bg=fundo, fg="#aaaab0",
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")
        modos = tk.Frame(ar, bg=fundo)
        modos.pack(fill="x", pady=(5, 12))
        for indice, (nome, valor) in enumerate((
            ("Frio", "cool"), ("Quente", "heat"), ("Auto", "auto"),
            ("Ventilar", "fan"), ("Secar", "dry"),
        )):
            botao = self._botao_painel(modos, nome, "air.mode", valor)
            botao.grid(row=0, column=indice, sticky="ew", padx=2)
            modos.grid_columnconfigure(indice, weight=1)
        tk.Label(ar, text="VENTILAÇÃO", bg=fundo, fg="#aaaab0",
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")
        fans = tk.Frame(ar, bg=fundo)
        fans.pack(fill="x", pady=(5, 14))
        for indice, (nome, valor) in enumerate((
            ("Auto", "auto"), ("Fraca", "low"),
            ("Média", "medium"), ("Forte", "high"),
        )):
            botao = self._botao_painel(fans, nome, "air.fan", valor)
            botao.grid(row=0, column=indice, sticky="ew", padx=2)
            fans.grid_columnconfigure(indice, weight=1)
        self.casa_ar_status = tk.Label(
            ar, text="Ar desligado  •  Ar Frio  •  Forte", bg=fundo,
            fg="#aaaab0", anchor="w", justify="left", font=("Segoe UI", 10),
        )
        self.casa_ar_status.pack(fill="x", pady=(8, 0))

        tvs = tk.Frame(colunas, bg=fundo, padx=22, pady=20)
        tvs.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(tvs, text="TODAS AS TVS", bg=fundo, fg=AZUL_CLARO,
                 font=("Segoe UI Semibold", 12)).pack(anchor="w")
        tk.Label(tvs, text="Samsung Tizen e LG webOS encontradas no Wi-Fi",
                 bg=fundo, fg="#aaaab0", font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 12))
        self.casa_tv_ids: list[str] = []
        self.casa_tv_combo = ttk.Combobox(tvs, state="readonly")
        self.casa_tv_combo.pack(fill="x", pady=(0, 8))
        acoes_lista = tk.Frame(tvs, bg=fundo)
        acoes_lista.pack(fill="x")
        tk.Button(acoes_lista, text="Buscar TVs", command=self._casa_descobrir_tvs,
                  bg="#222226", fg="#b6b6bd", relief="flat", bd=0, pady=9,
                  cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(acoes_lista, text="Parear selecionada", command=self._casa_parear_tv,
                  bg="#222226", fg="#b6b6bd", relief="flat", bd=0, pady=9,
                  cursor="hand2").pack(side="left", fill="x", expand=True, padx=(4, 0))
        todos = tk.Frame(tvs, bg=fundo)
        todos.pack(fill="x", pady=(14, 0))
        for texto, acao in (("Ligar todas", "power_on"), ("Desligar todas", "power_off"),
                            ("Mudo", "mute"), ("Pausar", "pause")):
            tk.Button(todos, text=texto, command=lambda a=acao: self._casa_acao_tvs(a),
                      bg="#222226", fg="#b6b6bd", relief="flat", bd=0, pady=9,
                      cursor="hand2").pack(side="left", fill="x", expand=True, padx=2)
        tk.Label(tvs, text="YOUTUBE MULTIROOM", bg=fundo, fg="#aaaab0",
                 font=("Segoe UI Semibold", 9)).pack(anchor="w", pady=(18, 5))
        self.casa_youtube = tk.Entry(
            tvs, bg="#222226", fg="white", insertbackground="white",
            relief="flat", font=("Segoe UI", 11),
        )
        self.casa_youtube.pack(fill="x", ipady=10)
        youtube = tk.Frame(tvs, bg=fundo)
        youtube.pack(fill="x", pady=(8, 0))
        tk.Button(youtube, text="Nesta TV", command=lambda: self._casa_tocar_youtube(False),
                  bg="#222226", fg="#b6b6bd", relief="flat", bd=0, pady=10,
                  cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(youtube, text="Tocar em todas", command=lambda: self._casa_tocar_youtube(True),
                  bg=AZUL_ESCURO, fg="white", relief="flat", bd=0, pady=10,
                  cursor="hand2").pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.casa_tv_status = tk.Label(
            tvs, text="Toque em Buscar TVs para atualizar a casa.", bg=fundo,
            fg="#aaaab0", anchor="w", justify="left", wraplength=430,
            font=("Segoe UI", 10),
        )
        self.casa_tv_status.pack(fill="x", pady=(14, 0))
        self._casa_render_tvs(self.tv_manager.list())

    def _casa_tv_id(self) -> str:
        indice = self.casa_tv_combo.current()
        return self.casa_tv_ids[indice] if 0 <= indice < len(self.casa_tv_ids) else ""

    def _casa_render_tvs(self, itens: list[dict[str, object]]) -> None:
        self.casa_tv_ids = [str(item.get("id", "")) for item in itens]
        nomes = [
            f"{item.get('name', 'Smart TV')} • {item.get('model', '')} • "
            f"{'ligada' if item.get('online') else 'desligada'}"
            for item in itens
        ]
        self.casa_tv_combo["values"] = nomes
        if nomes:
            self.casa_tv_combo.current(0)

    def _casa_tarefa(self, tarefa: object) -> None:
        def trabalhar() -> None:
            try:
                resultado = tarefa()  # type: ignore[operator]
                self._evento("casa_tv_resultado", resultado)
            except Exception as exc:
                self._evento("casa_tv_erro", str(exc))
        threading.Thread(target=trabalhar, daemon=True).start()

    def _casa_descobrir_tvs(self) -> None:
        self.casa_tv_status.configure(text="Procurando TVs na rede...")
        self._casa_tarefa(lambda: {"message": "Busca concluída.", "tvs": self.tv_manager.discover()})

    def _casa_parear_tv(self) -> None:
        device_id = self._casa_tv_id()
        if not device_id:
            self.casa_tv_status.configure(text="Busque e selecione uma TV primeiro.")
            return
        self.casa_tv_status.configure(text="Aceite o pareamento que aparecer na TV...")
        self._casa_tarefa(lambda: {"message": "TV pareada.", "tv": self.tv_manager.pair(device_id)})

    def _casa_acao_tvs(self, acao: str) -> None:
        self.casa_tv_status.configure(text="Enviando para todas as TVs...")
        self._casa_tarefa(lambda: self.tv_manager.action_all(acao))

    def _casa_tocar_youtube(self, todas: bool) -> None:
        pesquisa = self.casa_youtube.get().strip()
        if not pesquisa:
            self.casa_tv_status.configure(text="Digite uma música, artista ou link do YouTube.")
            return
        device_id = None if todas else self._casa_tv_id()
        if not todas and not device_id:
            self.casa_tv_status.configure(text="Selecione uma TV ou use Tocar em todas.")
            return
        self.casa_tv_status.configure(text="Resolvendo a música e abrindo o YouTube...")
        self._casa_tarefa(lambda: self.tv_manager.youtube(pesquisa, device_id))

    def _montar_aba_assistente(self) -> None:
        self.aba_assistente = tk.Frame(self.conteudo, bg=FUNDO)
        self.canvas = tk.Canvas(
            self.aba_assistente, bg=FUNDO, highlightthickness=0, height=410
        )
        self.canvas.pack(fill="both", expand=True, padx=40, pady=(24, 0))
        self.canvas.bind("<Configure>", lambda _e: self._desenhar_esfera())

        self.status = tk.Label(
            self.aba_assistente, text="Iniciando...", bg=FUNDO, fg=SECUNDARIO,
            font=("Segoe UI Semibold", 12),
        )
        self.status.pack(pady=(0, 6))
        tk.Label(
            self.aba_assistente,
            text='Diga "Nebu" e depois o comando',
            bg=FUNDO, fg="#98a2b3", font=("Segoe UI", 10),
        ).pack(pady=(0, 28))

    def _montar_aba_conversa(self) -> None:
        self.aba_conversa = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_conversa, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=32, pady=24)

        self.historico = scrolledtext.ScrolledText(
            area, wrap="word", state="disabled", bg="#f7f9fc", fg=TEXTO,
            relief="flat", bd=0, padx=18, pady=16, font=("Segoe UI", 11),
        )
        self.historico.pack(fill="both", expand=True)
        self.historico.tag_configure("nebula", foreground=AZUL_ESCURO,
                                     font=("Segoe UI Semibold", 11))
        self.historico.tag_configure("usuario", foreground=TEXTO,
                                     font=("Segoe UI Semibold", 11))

        feedback = tk.Frame(area, bg=FUNDO)
        feedback.pack(fill="x", pady=(8, 0))
        tk.Label(
            feedback, text="Feedback da última resposta:", bg=FUNDO, fg=SECUNDARIO,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", padx=(0, 8))
        self.feedback_conversa_texto = tk.Entry(
            feedback, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 9), insertbackground=TEXTO,
        )
        self.feedback_conversa_texto.pack(
            side="left", fill="x", expand=True, ipady=7, padx=(0, 7)
        )
        tk.Button(
            feedback, text="👍 Gostei",
            command=lambda: self._registrar_feedback_conversa("positivo"),
            bg="#eaf8ef", fg="#18743b", relief="flat", bd=0,
            padx=10, pady=6, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            feedback, text="👎 Melhorar",
            command=lambda: self._registrar_feedback_conversa("negativo"),
            bg="#fff1f0", fg="#c43224", relief="flat", bd=0,
            padx=10, pady=6, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left")
        self.feedback_conversa_status = tk.Label(
            area, text="O comentário é opcional e fica salvo somente no PC.",
            bg=FUNDO, fg="#98a2b3", anchor="w", font=("Segoe UI", 8),
        )
        self.feedback_conversa_status.pack(fill="x", pady=(2, 0))

        codex_area = tk.Frame(area, bg="#f2f5f9", padx=14, pady=10)
        codex_area.pack(fill="x", pady=(12, 0))
        self.codex_status = tk.Label(
            codex_area, text="Codex: nenhuma tarefa enviada", bg="#f2f5f9",
            fg=AZUL_ESCURO, anchor="w", font=("Segoe UI Semibold", 10),
        )
        self.codex_status.pack(fill="x", pady=(0, 6))
        self.codex_resultado = scrolledtext.ScrolledText(
            codex_area, height=7, wrap="word", state="disabled",
            bg="#101828", fg="#e6edf6", relief="flat", bd=0,
            padx=12, pady=10, font=("Consolas", 9),
        )
        self.codex_resultado.pack(fill="x")

        entrada_area = tk.Frame(area, bg=FUNDO)
        entrada_area.pack(fill="x", pady=(14, 0))
        self.entrada = tk.Entry(
            entrada_area, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 11), insertbackground=TEXTO,
        )
        self.entrada.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 10))
        self.entrada.bind("<Return>", lambda _e: self.enviar_texto())
        tk.Button(
            entrada_area, text="Enviar", command=self.enviar_texto,
            bg=AZUL, fg="white", activebackground=AZUL_ESCURO,
            activeforeground="white", relief="flat", bd=0,
            padx=22, pady=11, font=("Segoe UI Semibold", 10), cursor="hand2",
        ).pack(side="right")

    def _montar_aba_transferencia(self) -> None:
        self.aba_transferencia = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_transferencia, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=34, pady=26)
        tk.Label(area, text="Chat", bg=FUNDO, fg=TEXTO,
                 font=("Segoe UI Semibold", 24)).pack(anchor="w")
        tk.Label(
            area, text="Textos, links, imagens e arquivos entre o notebook e o PC.",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 16))

        painel = PainelArredondado(area, cor="#353538", raio=10, padding=14)
        painel.pack(fill="both", expand=True)
        self.transfer_historico = scrolledtext.ScrolledText(
            painel.body, wrap="word", state="disabled", bg="#353538",
            fg="#f4eee4", insertbackground="#f4eee4", relief="flat", bd=0,
            padx=8, pady=8, font=("Segoe UI", 10), cursor="arrow",
        )
        self.transfer_historico.pack(fill="both", expand=True)
        self.transfer_historico.tag_configure("autor", foreground=AZUL_CLARO,
                                               font=("Segoe UI Semibold", 9))
        self.transfer_historico.tag_configure("arquivo", foreground="#ead3ae",
                                               underline=True, font=("Segoe UI Semibold", 10))
        self.transfer_historico.tag_configure("link", foreground="#e6d0aa", underline=True)
        self.transfer_imagens: list[ImageTk.PhotoImage] = []
        self.transfer_renderizado = ""
        self.transfer_sync_busy = False
        self.transfer_next_sync = 0.0

        envio = PainelArredondado(area, cor="#353538", raio=10, padding=12,
                                  altura_automatica=True)
        envio.pack(fill="x", pady=(12, 0))
        linha = tk.Frame(envio.body, bg="#353538")
        linha.pack(fill="x")
        self.transfer_entrada = tk.Entry(
            linha, bg="#414144", fg="#f4eee4", insertbackground="#f4eee4",
            relief="flat", bd=0, font=("Segoe UI", 11),
        )
        self.transfer_entrada.pack(side="left", fill="x", expand=True, ipady=11, padx=(0, 8))
        self.transfer_entrada.bind("<Return>", lambda _e: self._enviar_transferencia())
        anexar = BotaoArredondado(
            linha, text="＋  Anexar", command=self._escolher_transferencia,
            bg="#414144", fg="#d1c9bd", activebackground="#514a40",
            width=104, height=44, radius=8,
        )
        anexar.pack(side="left", padx=(0, 8))
        enviar = BotaoArredondado(
            linha, text="Enviar", command=self._enviar_transferencia,
            bg="#a7865f", fg="#211f1c", activebackground="#c5a980",
            width=88, height=44, radius=8, font=("Segoe UI Semibold", 9),
        )
        enviar.pack(side="left")
        self.transfer_anexo: Path | None = None
        self.transfer_anexo_label = tk.Label(
            envio.body, text="Nenhum anexo · limite inicial de 25 MB",
            bg="#353538", fg="#938c83", anchor="w", font=("Segoe UI", 8),
        )
        self.transfer_anexo_label.pack(fill="x", pady=(8, 0))
        self.transfer_status = tk.Label(
            area, text="Sincroniza automaticamente quando os dois computadores estão ligados.",
            bg=FUNDO, fg=SECUNDARIO, anchor="w", font=("Segoe UI", 8),
        )
        self.transfer_status.pack(fill="x", pady=(8, 0))
        self.janela.after(400, self._renderizar_transferencias)

    def _escolher_transferencia(self) -> None:
        escolhido = filedialog.askopenfilename(parent=self.janela, title="Escolher arquivo")
        if not escolhido:
            return
        path = Path(escolhido)
        try:
            tamanho = path.stat().st_size
        except OSError as exc:
            self.transfer_status.configure(text=f"Não foi possível abrir o arquivo: {exc}")
            return
        if tamanho > MAX_FILE_BYTES:
            self.transfer_status.configure(text="Este teste aceita arquivos de até 25 MB.", fg="#ff8f9a")
            return
        self.transfer_anexo = path
        self.transfer_anexo_label.configure(
            text=f"📎 {path.name} · {tamanho / 1024 / 1024:.1f} MB", fg=AZUL_CLARO
        )

    def _enviar_transferencia(self) -> None:
        texto = self.transfer_entrada.get().strip()
        anexo = self.transfer_anexo
        if not texto and anexo is None:
            return
        self.transfer_entrada.delete(0, "end")
        self.transfer_anexo = None
        self.transfer_anexo_label.configure(text="Nenhum anexo · limite inicial de 25 MB", fg="#938c83")
        self.transfer_status.configure(text="Enviando…", fg=SECUNDARIO)
        threading.Thread(target=self._trabalhar_transferencia, args=(texto, anexo), daemon=True).start()

    def _trabalhar_transferencia(self, texto: str, anexo: Path | None) -> None:
        try:
            dados = anexo.read_bytes() if anexo else None
            payload: dict[str, object] = {
                "id": uuid.uuid4().hex, "sender": socket.gethostname(),
                "text": texto, "created_at": time.time(),
            }
            if anexo:
                payload.update({
                    "filename": anexo.name, "size": len(dados or b""),
                    "mime": mimetypes.guess_type(anexo.name)[0] or "application/octet-stream",
                })
            CHAT_STORE.add(payload, dados)
            remoto = dict(payload)
            if dados is not None:
                remoto["data"] = base64.b64encode(dados).decode("ascii")
            corpo = json.dumps(remoto, ensure_ascii=False).encode("utf-8")
            entregues = 0
            for endpoint in self._endpoints_transferencia():
                try:
                    request = Request(
                        endpoint + "/api/transfer/message", data=corpo, method="POST",
                        headers={"Content-Type": "application/json", "X-Nebula-Power-Token": POWER_TOKEN},
                    )
                    with urlopen(request, timeout=35) as response:
                        if response.status < 300:
                            entregues += 1
                except (OSError, URLError):
                    continue
            texto_status = "Salvo e sincronizado." if entregues else "Salvo neste computador; o outro está offline."
            self.janela.after(0, lambda: self.transfer_status.configure(text=texto_status, fg=AZUL_CLARO))
        except (OSError, ValueError) as exc:
            erro = str(exc)
            self.janela.after(0, lambda mensagem=erro: self.transfer_status.configure(text=f"Falha: {mensagem}", fg="#ff8f9a"))

    @staticmethod
    def _endpoints_transferencia() -> list[str]:
        locais: set[str] = {"127.0.0.1"}
        try:
            locais.update(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError:
            pass
        candidatos = (("192.168.15.12", "http://192.168.15.12:8765"),
                      ("192.168.15.86", "http://192.168.15.86:8765"))
        return [endpoint for ip, endpoint in candidatos if ip not in locais]

    @staticmethod
    def _requisicao_transferencia(endpoint: str, path: str, payload: dict[str, object] | None = None) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            endpoint + path, data=body, method="POST" if body is not None else "GET",
            headers={"X-Nebula-Power-Token": POWER_TOKEN,
                     **({"Content-Type": "application/json"} if body is not None else {})},
        )
        with urlopen(request, timeout=35) as response:
            return response.read()

    def _iniciar_sincronizacao_transferencia(self) -> None:
        if self.transfer_sync_busy:
            return
        self.transfer_sync_busy = True
        self.transfer_next_sync = time.monotonic() + 8
        threading.Thread(target=self._sincronizar_transferencias_rede, daemon=True).start()

    def _sincronizar_transferencias_rede(self) -> None:
        conectados = 0
        try:
            for endpoint in self._endpoints_transferencia():
                try:
                    resposta = self._requisicao_transferencia(endpoint, "/api/transfer/messages")
                    remotas = json.loads(resposta).get("messages", [])
                    if not isinstance(remotas, list):
                        continue
                    conectados += 1
                    locais = {str(item["id"]): item for item in CHAT_STORE.messages()}
                    ids_remotos = {str(item.get("id")) for item in remotas if isinstance(item, dict)}
                    for item in remotas:
                        if not isinstance(item, dict) or str(item.get("id")) in locais:
                            continue
                        arquivo = None
                        if item.get("filename"):
                            arquivo = self._requisicao_transferencia(
                                endpoint, "/api/transfer/file?id=" + str(item.get("id"))
                            )
                        CHAT_STORE.add(item, arquivo)
                    for message_id, item in locais.items():
                        if message_id in ids_remotos:
                            continue
                        payload = {key: value for key, value in item.items() if key != "stored"}
                        if item.get("filename"):
                            _meta, path = CHAT_STORE.file(message_id)
                            payload["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
                        self._requisicao_transferencia(endpoint, "/api/transfer/message", payload)
                except (OSError, URLError, ValueError, json.JSONDecodeError):
                    continue
            if conectados:
                self.janela.after(0, lambda: self.transfer_status.configure(
                    text="Chat sincronizado com o outro computador.", fg=AZUL_CLARO
                ))
        finally:
            self.transfer_sync_busy = False

    def _renderizar_transferencias(self) -> None:
        if self.parar.is_set():
            return
        mensagens = CHAT_STORE.messages()
        assinatura = repr(mensagens)
        if assinatura != self.transfer_renderizado:
            self.transfer_renderizado = assinatura
            campo = self.transfer_historico
            campo.configure(state="normal"); campo.delete("1.0", "end")
            self.transfer_imagens.clear()
            for mensagem in mensagens:
                horario = time.strftime("%d/%m  %H:%M", time.localtime(float(mensagem.get("created_at") or 0)))
                campo.insert("end", f"{mensagem.get('sender', 'Computador')}  ·  {horario}\n", "autor")
                texto = str(mensagem.get("text") or "")
                inicio = 0
                for match in re.finditer(r"https?://[^\s]+", texto):
                    campo.insert("end", texto[inicio:match.start()])
                    tag = "link_" + str(mensagem["id"]) + str(match.start())
                    url = match.group(0).rstrip(".,;)")
                    campo.insert("end", url, ("link", tag))
                    campo.tag_bind(tag, "<Button-1>", lambda _e, link=url: webbrowser.open(link))
                    inicio = match.start() + len(url)
                campo.insert("end", texto[inicio:] + ("\n" if texto else ""))
                if mensagem.get("filename"):
                    try:
                        _item, path = CHAT_STORE.file(str(mensagem["id"]))
                        if str(mensagem.get("mime", "")).startswith("image/"):
                            imagem = Image.open(path); imagem.thumbnail((320, 190))
                            preview = ImageTk.PhotoImage(imagem.copy()); self.transfer_imagens.append(preview)
                            campo.image_create("end", image=preview); campo.insert("end", "\n")
                        tag = "file_" + str(mensagem["id"])
                        campo.insert("end", f"📎 {mensagem['filename']}  ({int(mensagem.get('size') or 0)/1024/1024:.1f} MB)\n", ("arquivo", tag))
                        campo.tag_bind(tag, "<Button-1>", lambda _e, arquivo=path: os.startfile(arquivo))
                    except (OSError, FileNotFoundError):
                        campo.insert("end", f"📎 {mensagem['filename']} · arquivo indisponível\n")
                campo.insert("end", "\n")
            campo.configure(state="disabled"); campo.see("end")
        if time.monotonic() >= self.transfer_next_sync:
            self._iniciar_sincronizacao_transferencia()
        self.janela.after(1500, self._renderizar_transferencias)

    def _montar_aba_grupo(self) -> None:
        self.aba_grupo = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_grupo, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=32, pady=22)

        titulo = tk.Frame(area, bg=FUNDO)
        titulo.pack(fill="x", pady=(0, 12))
        tk.Label(
            titulo, text="Grupo geral", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 20),
        ).pack(side="left")
        tk.Label(
            titulo, text="  Você  •  Codex  (Qwen desativada)",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 10),
        ).pack(side="left", padx=(8, 0), pady=(6, 0))
        tk.Button(
            titulo, text="Limpar histórico", command=self._limpar_grupo,
            bg="#fff1f0", fg="#c43224", activebackground="#ffe4e1",
            relief="flat", bd=0, padx=11, pady=7,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="right")
        tk.Button(
            titulo, text="Contexto e correções", command=self._abrir_contexto_grupo,
            bg="#edf8f2", fg=AZUL_ESCURO, activebackground="#d8f1e4",
            relief="flat", bd=0, padx=11, pady=7,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="right", padx=(0, 8))
        tk.Button(
            titulo, text="Feedbacks", command=self._abrir_feedbacks,
            bg="#edf8f2", fg=AZUL_ESCURO, activebackground="#d8f1e4",
            relief="flat", bd=0, padx=11, pady=7,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="right", padx=(0, 8))

        self.grupo_historico = scrolledtext.ScrolledText(
            area, wrap="word", state="disabled", bg="#f7f9fc", fg=TEXTO,
            relief="flat", bd=0, padx=18, pady=16, font=("Segoe UI", 11),
        )
        self.grupo_historico.pack(fill="both", expand=True)
        self.grupo_historico.tag_configure(
            "grupo_voce", foreground=TEXTO, font=("Segoe UI Semibold", 11)
        )
        self.grupo_historico.tag_configure(
            "grupo_qwen", foreground="#7b2cbf", font=("Segoe UI Semibold", 11)
        )
        self.grupo_historico.tag_configure(
            "grupo_codex", foreground=AZUL_ESCURO, font=("Segoe UI Semibold", 11)
        )
        self.grupo_historico.tag_configure(
            "grupo_sistema", foreground="#c2410c", font=("Segoe UI Semibold", 11)
        )

        feedback = tk.Frame(area, bg=FUNDO)
        feedback.pack(fill="x", pady=(8, 0))
        tk.Label(
            feedback, text="Feedback para:", bg=FUNDO, fg=SECUNDARIO,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left", padx=(0, 5))
        self.feedback_grupo_autor = tk.StringVar(value="Codex")
        seletor = tk.OptionMenu(feedback, self.feedback_grupo_autor, "Codex")
        seletor.configure(
            bg="#edf8f2", fg=AZUL_ESCURO, activebackground="#d8f1e4",
            relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 9),
        )
        seletor.pack(side="left", padx=(0, 6))
        self.feedback_grupo_texto = tk.Entry(
            feedback, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 9), insertbackground=TEXTO,
        )
        self.feedback_grupo_texto.pack(
            side="left", fill="x", expand=True, ipady=7, padx=(0, 7)
        )
        tk.Button(
            feedback, text="👍",
            command=lambda: self._registrar_feedback_grupo("positivo"),
            bg="#eaf8ef", fg="#18743b", relief="flat", bd=0,
            padx=10, pady=6, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            feedback, text="👎",
            command=lambda: self._registrar_feedback_grupo("negativo"),
            bg="#fff1f0", fg="#c43224", relief="flat", bd=0,
            padx=10, pady=6, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left")

        self.grupo_status = tk.Label(
            area,
            text="Grupo pronto. O envio ao Codex utiliza sua cota do Codex.",
            bg=FUNDO, fg=SECUNDARIO, anchor="w", font=("Segoe UI", 9),
        )
        self.grupo_status.pack(fill="x", pady=(8, 6))

        entrada_area = tk.Frame(area, bg=FUNDO)
        entrada_area.pack(fill="x")
        self.grupo_entrada = tk.Entry(
            entrada_area, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 11), insertbackground=TEXTO,
        )
        self.grupo_entrada.pack(fill="x", ipady=12)
        self.grupo_entrada.bind("<Return>", lambda _e: self._enviar_grupo("codex"))

        botoes = tk.Frame(area, bg=FUNDO)
        botoes.pack(fill="x", pady=(8, 0))
        self.botoes_envio_grupo: list[tk.Button] = []
        for texto, modo, fundo, cor in (
            ("Enviar ao Codex", "codex", AZUL, "white"),
        ):
            botao = tk.Button(
                botoes, text=texto, command=lambda m=modo: self._enviar_grupo(m),
                bg=fundo, fg=cor, activebackground=fundo,
                relief="flat", bd=0, padx=15, pady=9,
                font=("Segoe UI Semibold", 9), cursor="hand2",
            )
            botao.pack(side="left", padx=(0, 8))
            self.botoes_envio_grupo.append(botao)

        for mensagem in self.grupo.historico():
            self._adicionar_mensagem_grupo(mensagem)

    def _montar_aba_remoto(self) -> None:
        self.aba_remoto = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_remoto, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=36, pady=24)
        tk.Label(area, text="Nebula no celular", bg=FUNDO, fg=TEXTO,
                 font=("Segoe UI Semibold", 22)).pack(anchor="w")
        tk.Label(
            area,
            text="Abra este endereço no Galaxy A71 com o Tailscale conectado.",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 11),
        ).pack(anchor="w", pady=(6, 14))
        self.mobile_status = tk.Label(
            area, text="Aguardando o aplicativo Android…", justify="left", anchor="w",
            bg="#f7f9fc", fg=TEXTO, font=("Segoe UI", 10), padx=14, pady=10,
        )
        self.mobile_status.pack(fill="x", pady=(0, 10))
        self.mobile_map_link = tk.Label(
            area, text="Localização ainda não recebida", justify="left", anchor="w",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 10, "underline"),
        )
        self.mobile_map_link.pack(fill="x", pady=(0, 8))
        self.mobile_map_link.bind("<Button-1>", lambda _e: self._abrir_mapa_mobile())
        self.mobile_map_link.bind("<Button-3>", lambda _e: self._copiar_link_mapa_mobile())
        controles = tk.Frame(area, bg=FUNDO)
        controles.pack(fill="x", pady=(0, 12))
        for texto, acao in (
            ("⏯ Play / pausa", "media_play_pause"), ("⏮ Anterior", "media_previous"),
            ("⏭ Próxima", "media_next"), ("🔦 Ligar lanterna", "flashlight_on"),
            ("Apagar lanterna", "flashlight_off"), ("📍 Localizar", "locate"),
        ):
            tk.Button(
                controles, text=texto, command=lambda a=acao: self._comando_mobile(a),
                bg="#edf8f2", fg=AZUL_ESCURO, relief="flat", bd=0, padx=10, pady=8,
                font=("Segoe UI Semibold", 9), cursor="hand2",
            ).pack(side="left", padx=(0, 6), pady=3)
        tk.Button(
            controles, text="Abrir mapa", command=self._abrir_mapa_mobile,
            bg="#edf8f2", fg=AZUL_ESCURO, relief="flat", bd=0, padx=10, pady=8,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 6), pady=3)
        seguranca = tk.Frame(area, bg=FUNDO)
        seguranca.pack(fill="x", pady=(0, 12))
        tk.Button(
            seguranca, text="🔒 Bloquear telefone", command=self._bloquear_mobile,
            bg="#fff1f0", fg="#c43224", relief="flat", bd=0, padx=12, pady=9,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            seguranca, text="Remover modo perdido Nebula", command=lambda: self._comando_mobile("unlock_nebula"),
            bg="#edf8f2", fg=AZUL_ESCURO, relief="flat", bd=0, padx=12, pady=9,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        self.mobile_notifications = tk.Label(
            area, text="Notificações: nenhuma compartilhada.", justify="left", anchor="nw",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 9), wraplength=700,
        )
        self.mobile_notifications.pack(fill="x", pady=(0, 12))
        tk.Label(area, text="Endereço privado", bg=FUNDO, fg=SECUNDARIO,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(
            area, text="https://desktop-0sdb1i7.tail46f27e.ts.net",
            bg="#f2f5f9", fg=AZUL_ESCURO, font=("Segoe UI", 12),
            padx=16, pady=12,
        ).pack(anchor="w", fill="x", pady=(5, 10))
        tk.Label(area, text="PIN de pareamento", bg=FUNDO, fg=SECUNDARIO,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(
            area, text=get_pin(), bg="#edf8f2", fg=AZUL_ESCURO,
            font=("Consolas", 26, "bold"), padx=18, pady=12,
        ).pack(anchor="w", pady=(5, 10))
        tk.Label(
            area, text="O PIN fica somente no computador. Não compartilhe com outras pessoas.",
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 10),
        ).pack(anchor="w")

    def _montar_aba_configuracao(self) -> None:
        self.aba_configuracao = tk.Frame(self.conteudo, bg=FUNDO)
        area = tk.Frame(self.aba_configuracao, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=54, pady=30)
        area.columnconfigure(1, weight=1)

        tk.Label(
            area, text="Configuração Tuya", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 22),
        ).grid(row=0, column=0, columnspan=3, sticky="w")
        tk.Label(
            area,
            text=(
                "A Nebula controla o abajur diretamente pela rede LAN: não usa USB. "
                "A local key é necessária uma única vez e fica salva somente neste PC."
            ),
            bg=FUNDO, fg=SECUNDARIO, justify="left", wraplength=720,
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 24))

        device_id = ""
        address = "Auto"
        local_key = ""
        version = 3.5
        carregamento_erro = ""
        try:
            inicial = carregar_configuracao_inicial(
                snapshot_path=Path(caminho_recurso("snapshot.json"))
            )
            device_id = inicial.device_id
            address = inicial.address
            local_key = inicial.local_key
            version = inicial.version
        except Exception as exc:
            carregamento_erro = mensagem_erro_segura(exc)

        self.tuya_device_id = tk.StringVar(value=device_id)
        self.tuya_address = tk.StringVar(value=address)
        self.tuya_version = tk.StringVar(value=f"{version:.1f}")
        self.tuya_local_key = tk.StringVar(value=local_key)
        self.tuya_mostrar_chave = tk.BooleanVar(value=False)
        self._tuya_ocupado = False

        def rotulo(linha: int, texto: str) -> None:
            tk.Label(
                area, text=texto, bg=FUNDO, fg=TEXTO,
                font=("Segoe UI Semibold", 10), anchor="w",
            ).grid(row=linha, column=0, sticky="w", padx=(0, 18), pady=7)

        rotulo(2, "Device ID")
        self.tuya_device_id_entry = tk.Entry(
            area, textvariable=self.tuya_device_id,
            bg="#f2f5f9", fg=TEXTO, insertbackground=TEXTO,
            relief="flat", bd=0, font=("Segoe UI", 10),
        )
        self.tuya_device_id_entry.grid(
            row=2, column=1, columnspan=2, sticky="ew", ipady=9, pady=7
        )

        rotulo(3, "IP ou Auto")
        self.tuya_address_entry = tk.Entry(
            area, textvariable=self.tuya_address,
            bg="#f2f5f9", fg=TEXTO, insertbackground=TEXTO,
            relief="flat", bd=0, font=("Segoe UI", 10),
        )
        self.tuya_address_entry.grid(row=3, column=1, sticky="ew", ipady=9, pady=7)
        self.tuya_detectar_botao = tk.Button(
            area, text="Detectar na rede", command=self._detectar_tuya,
            bg="#edf8f2", fg=AZUL_ESCURO, activebackground="#d8f1e4",
            relief="flat", bd=0, padx=14, pady=9,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        )
        self.tuya_detectar_botao.grid(row=3, column=2, sticky="e", padx=(10, 0), pady=7)

        rotulo(4, "Protocolo")
        self.tuya_version_combo = ttk.Combobox(
            area,
            textvariable=self.tuya_version,
            values=("3.1", "3.2", "3.3", "3.4", "3.5"),
            state="readonly",
            width=9,
            font=("Segoe UI", 10),
        )
        self.tuya_version_combo.grid(row=4, column=1, sticky="w", ipady=5, pady=7)

        rotulo(5, "Local key")
        self.tuya_local_key_entry = tk.Entry(
            area, textvariable=self.tuya_local_key, show="*",
            bg="#f2f5f9", fg=TEXTO, insertbackground=TEXTO,
            relief="flat", bd=0, font=("Consolas", 10),
        )
        self.tuya_local_key_entry.grid(row=5, column=1, sticky="ew", ipady=9, pady=7)
        self.tuya_mostrar_chave_check = tk.Checkbutton(
            area, text="Mostrar", variable=self.tuya_mostrar_chave,
            command=self._alternar_chave_tuya,
            bg=FUNDO, fg=SECUNDARIO, activebackground=FUNDO,
            activeforeground=TEXTO, selectcolor=FUNDO,
            relief="flat", bd=0, font=("Segoe UI", 9), cursor="hand2",
        )
        self.tuya_mostrar_chave_check.grid(
            row=5, column=2, sticky="w", padx=(10, 0), pady=7
        )

        tk.Label(
            area,
            text=(
                "A detecção encontra ID, IP e versão, mas não revela a local key. "
                "Obtenha-a uma vez pelo TinyTuya wizard e cole acima."
            ),
            bg=FUNDO, fg="#98a2b3", justify="left", wraplength=650,
            font=("Segoe UI", 9),
        ).grid(row=6, column=1, columnspan=2, sticky="w", pady=(0, 18))

        self.tuya_salvar_botao = tk.Button(
            area, text="Salvar e testar", command=self._salvar_e_testar_tuya,
            bg=AZUL, fg="white", activebackground=AZUL_ESCURO,
            activeforeground="white", relief="flat", bd=0,
            padx=20, pady=10, font=("Segoe UI Semibold", 10), cursor="hand2",
        )
        self.tuya_salvar_botao.grid(row=7, column=1, sticky="w")

        if carregamento_erro:
            texto_status = carregamento_erro
            cor_status = "#c2410c"
        elif local_key:
            texto_status = "Configuração existente carregada. Você pode testá-la novamente."
            cor_status = SECUNDARIO
        elif device_id:
            texto_status = "ID/IP preenchidos. Informe a local key para concluir."
            cor_status = SECUNDARIO
        else:
            texto_status = "Detecte o abajur na LAN ou preencha os campos manualmente."
            cor_status = SECUNDARIO
        self.tuya_status = tk.Label(
            area, text=texto_status, bg="#f7f9fc", fg=cor_status,
            justify="left", anchor="w", wraplength=700,
            padx=14, pady=12, font=("Segoe UI", 9),
        )
        self.tuya_status.grid(
            row=8, column=0, columnspan=3, sticky="ew", pady=(22, 0)
        )

    def _alternar_chave_tuya(self) -> None:
        self.tuya_local_key_entry.configure(
            show="" if self.tuya_mostrar_chave.get() else "*"
        )

    def _definir_tuya_ocupado(self, ocupado: bool, mensagem: str = "") -> None:
        self._tuya_ocupado = ocupado
        estado = "disabled" if ocupado else "normal"
        self.tuya_detectar_botao.configure(state=estado)
        self.tuya_salvar_botao.configure(state=estado)
        if mensagem:
            self.tuya_status.configure(text=mensagem, fg=SECUNDARIO)

    def _detectar_tuya(self) -> None:
        if self._tuya_ocupado or self.parar.is_set():
            return
        self._definir_tuya_ocupado(
            True, "Procurando dispositivos Tuya na rede local…"
        )

        def trabalhar() -> None:
            try:
                dispositivos = detectar_dispositivos()
            except Exception as exc:
                evento = ("tuya_deteccao_erro", mensagem_erro_segura(exc))
            else:
                evento = ("tuya_deteccao_ok", dispositivos)
            if not self.parar.is_set():
                self._evento(*evento)

        threading.Thread(
            target=trabalhar, name="Nebula-Detectar-Tuya", daemon=True
        ).start()

    def _aplicar_deteccao_tuya(self, dispositivos: object) -> None:
        self._definir_tuya_ocupado(False)
        if not isinstance(dispositivos, list) or not dispositivos:
            self.tuya_status.configure(
                text=(
                    "Nenhum dispositivo Tuya respondeu. Confirme que o PC e o abajur "
                    "estão na mesma rede e tente novamente."
                ),
                fg="#c2410c",
            )
            return

        escolhido = escolher_dispositivo_preferido(
            dispositivos,
            self.tuya_device_id.get(),
        )
        if escolhido is None:
            self._mostrar_selecao_dispositivo_tuya(dispositivos)
            return
        self._preencher_dispositivo_tuya(escolhido)
        self.tuya_status.configure(
            text="Dispositivo Tuya detectado. A local key não é transmitida pela LAN.",
            fg="#18743b",
        )

    def _preencher_dispositivo_tuya(self, escolhido: object) -> None:
        self.tuya_device_id.set(str(getattr(escolhido, "device_id", "")))
        self.tuya_address.set(str(getattr(escolhido, "address", "Auto")) or "Auto")
        self.tuya_version.set(f"{float(getattr(escolhido, 'version', 3.5)):.1f}")

    def _mostrar_selecao_dispositivo_tuya(self, dispositivos: list[object]) -> None:
        janela = tk.Toplevel(self.janela)
        janela.title("Escolher dispositivo Tuya")
        janela.geometry("520x300")
        janela.minsize(440, 240)
        janela.configure(bg=FUNDO)
        janela.transient(self.janela)
        janela.grab_set()

        area = tk.Frame(janela, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=24, pady=20)
        tk.Label(
            area,
            text="Encontrei mais de um dispositivo Tuya",
            bg=FUNDO,
            fg=TEXTO,
            font=("Segoe UI Semibold", 16),
        ).pack(anchor="w")
        tk.Label(
            area,
            text="Escolha o abajur pelo IP. O final do Device ID aparece apenas para diferenciar.",
            bg=FUNDO,
            fg=SECUNDARIO,
            wraplength=460,
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(5, 14))

        def selecionar(item: object) -> None:
            self._preencher_dispositivo_tuya(item)
            self.tuya_status.configure(
                text="Dispositivo escolhido. Cole a local key e use Salvar e testar.",
                fg="#18743b",
            )
            janela.destroy()

        for item in dispositivos:
            device_id = str(getattr(item, "device_id", ""))
            endereco = str(getattr(item, "address", "Auto"))
            versao = float(getattr(item, "version", 3.5))
            tk.Button(
                area,
                text=f"{endereco}   •   protocolo {versao:.1f}   •   ID …{device_id[-6:]}",
                command=lambda escolhido=item: selecionar(escolhido),
                anchor="w",
                bg="#edf8f2",
                fg=AZUL_ESCURO,
                activebackground="#d8f1e4",
                relief="flat",
                bd=0,
                padx=14,
                pady=10,
                font=("Segoe UI Semibold", 9),
                cursor="hand2",
            ).pack(fill="x", pady=4)

        self.tuya_status.configure(
            text="Escolha qual dos dispositivos encontrados é o abajur.",
            fg=SECUNDARIO,
        )

    def _salvar_e_testar_tuya(self) -> None:
        if self._tuya_ocupado or self.parar.is_set():
            return
        chave = self.tuya_local_key.get()
        try:
            config = criar_configuracao(
                self.tuya_device_id.get(),
                self.tuya_address.get(),
                self.tuya_version.get(),
                chave,
            )
        except Exception as exc:
            mensagem = mensagem_erro_segura(exc, local_key=chave)
            self.tuya_status.configure(text=mensagem, fg="#c2410c")
            messagebox.showerror("Configuração Tuya", mensagem, parent=self.janela)
            return

        self._definir_tuya_ocupado(
            True, "Salvando e consultando o estado do abajur pela LAN…"
        )

        def trabalhar() -> None:
            try:
                caminho = salvar_configuracao(config)
            except Exception as exc:
                tipo = "tuya_salvar_erro"
                valor: object = mensagem_erro_segura(exc, local_key=config.local_key)
            else:
                try:
                    testar_configuracao(config)
                except Exception as exc:
                    tipo = "tuya_teste_erro"
                    valor = mensagem_erro_segura(exc, local_key=config.local_key)
                else:
                    tipo = "tuya_configuracao_ok"
                    valor = (config, caminho)
            if not self.parar.is_set():
                self._evento(tipo, valor)

        threading.Thread(
            target=trabalhar, name="Nebula-Testar-Tuya", daemon=True
        ).start()

    def _finalizar_configuracao_tuya(self, valor: object) -> None:
        self._definir_tuya_ocupado(False)
        if not isinstance(valor, tuple) or len(valor) != 2:
            self.tuya_status.configure(
                text="Configuração salva e testada, mas não consegui recarregá-la.",
                fg="#c2410c",
            )
            return
        config, caminho = valor
        aplicada = False
        reconfigurar = getattr(self.nebula, "reconfigurar_abajur", None)
        if callable(reconfigurar):
            try:
                reconfigurar(config)
                aplicada = True
            except Exception as exc:
                mensagem = mensagem_erro_segura(
                    exc, local_key=str(getattr(config, "local_key", ""))
                )
                self.tuya_status.configure(
                    text=(
                        "Configuração salva e testada, mas a recarga falhou. "
                        f"{mensagem}"
                    ),
                    fg="#c2410c",
                )
                messagebox.showwarning(
                    "Configuração Tuya",
                    "A conexão foi confirmada, mas reinicie a Nebula para aplicar a configuração.",
                    parent=self.janela,
                )
                return

        complemento = " e aplicada agora" if aplicada else ""
        self.tuya_status.configure(
            text=f"Conexão confirmada: configuração salva{complemento}.",
            fg="#18743b",
        )
        messagebox.showinfo(
            "Configuração Tuya",
            (
                "O abajur respondeu à consulta somente leitura.\n\n"
                f"Configuração salva em {caminho}."
            ),
            parent=self.janela,
        )

    def mostrar_aba(self, nome: str) -> None:
        for frame in (
            self.aba_controle, self.aba_casa, self.aba_transferencia,
            self.aba_assistente, self.aba_conversa, self.aba_grupo,
            self.aba_remoto, self.aba_configuracao,
        ):
            frame.pack_forget()
        getattr(self, f"aba_{nome}").pack(fill="both", expand=True)
        for chave, botao in self.botoes_abas.items():
            botao.configure(
                fg=("#f4eee4" if self.modo_escuro else AZUL_ESCURO) if chave == nome else ("#b8b0a5" if self.modo_escuro else SECUNDARIO),
                bg=("#514a40" if self.modo_escuro else "#f2e8d8") if chave == nome else ("#292a2d" if self.modo_escuro else FUNDO),
            )

    def _alternar_tema(self) -> None:
        set_dark_mode(True)

    def _comando_mobile(self, acao: str) -> None:
        queue_device_command(acao)
        self.mobile_status.configure(text="Comando enviado; aguardando o telefone executar…")

    def _bloquear_mobile(self) -> None:
        if not messagebox.askyesno(
            "Bloquear telefone",
            "A tela será bloqueada imediatamente e exigirá o PIN do Android. Continuar?",
            parent=self.janela,
        ):
            return
        self._comando_mobile("lock_nebula")

    def _abrir_mapa_mobile(self) -> None:
        dados = get_device_status()
        if "latitude" not in dados or "longitude" not in dados:
            self.mobile_status.configure(text="Ainda não há coordenadas. Toque em Localizar primeiro.")
            return
        webbrowser.open(f"https://maps.google.com/?q={dados['latitude']},{dados['longitude']}")

    def _copiar_link_mapa_mobile(self) -> None:
        dados = get_device_status()
        if "latitude" not in dados or "longitude" not in dados:
            self.mobile_status.configure(text="Ainda não há um link de localização para copiar.")
            return
        link = f"https://maps.google.com/?q={dados['latitude']},{dados['longitude']}"
        self.janela.clipboard_clear()
        self.janela.clipboard_append(link)
        self.mobile_status.configure(text="Link do mapa copiado para a área de transferência.")

    def _atualizar_mobile(self) -> None:
        dados = get_device_status()
        if not dados:
            return
        self.ultimo_mobile_renderizado = repr(dados)
        bateria = dados.get("battery", "—")
        carga = " • carregando" if dados.get("charging") else ""
        visto = float(dados.get("last_seen", 0))
        idade = max(0, int(time.time() - visto)) if visto else 0
        link_mapa = ""
        if "latitude" in dados and "longitude" in dados:
            lat, lon = float(dados["latitude"]), float(dados["longitude"])
            link_mapa = f"https://maps.google.com/?q={lat},{lon}"
        situacao = "online" if idade <= 15 else "offline"
        horario = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(visto)) if visto else "nunca"
        localizacao_em = float(dados.get("location_updated_at", 0))
        horario_localizacao = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(localizacao_em)) if localizacao_em else "ainda não recebida"
        self.mobile_status.configure(text=f"Bateria: {bateria}%{carga}  •  {situacao}  •  última conexão: {horario} ({idade}s atrás)\nÚltima localização conhecida: {horario_localizacao}")
        self.mobile_map_link.configure(
            text=link_mapa or "Localização ainda não recebida",
            fg=AZUL_ESCURO if link_mapa else SECUNDARIO,
            cursor="hand2" if link_mapa else "arrow",
        )
        notificacoes = dados.get("notifications", [])
        linhas = [f"• {n.get('app', 'App')}: {n.get('title') or n.get('text', '')}" for n in notificacoes[-8:] if isinstance(n, dict)]
        self.mobile_notifications.configure(text="Notificações:\n" + ("\n".join(linhas) if linhas else "nenhuma compartilhada."))

    def _aplicar_tema(self, escuro: bool) -> None:
        escuro = True
        self.modo_escuro = True
        claro_para_escuro = {
            "#ffffff": "#303033", "#f7f9fc": "#353538",
            "#f2f5f9": "#3b3b3f", "#eef6ff": "#514a40",
            "#edf8f2": "#514a40", "#e8edf3": "#47474b",
            "#dedee2": "#4a4948", "#211f1c": "#f4eee4",
            "#706a62": "#b8b0a5", "#98a2b3": "#938c83",
        }
        mapa = claro_para_escuro if escuro else {v: k for k, v in claro_para_escuro.items()}

        def atualizar(widget: tk.Misc) -> None:
            for opcao in ("bg", "fg", "activebackground", "activeforeground", "insertbackground"):
                try:
                    atual = str(widget.cget(opcao)).lower()
                    if atual in mapa:
                        widget.configure(**{opcao: mapa[atual]})
                except (tk.TclError, TypeError):
                    pass
            for filho in widget.winfo_children():
                atualizar(filho)

        atualizar(self.janela)
        self.mostrar_aba(next((nome for nome, botao in self.botoes_abas.items() if str(botao.cget("bg")).lower() in ("#f2e8d8", "#514a40")), "controle"))
        self._desenhar_esfera()

    def adicionar_mensagem(self, autor: str, texto: str) -> None:
        self.historico.configure(state="normal")
        tag = "nebula" if autor == "Nebula" else "usuario"
        self.historico.insert("end", f"{autor}\n", tag)
        self.historico.insert("end", f"{texto}\n\n")
        self.historico.configure(state="disabled")
        self.historico.see("end")

    def enviar_texto(self) -> None:
        texto = self.entrada.get().strip()
        if not texto:
            return
        self.entrada.delete(0, "end")
        add_conversation_message("Você", texto)
        self._sincronizar_historico()
        self.comandos.put(texto.lower().strip())

    def _registrar_feedback_conversa(self, avaliacao: str) -> None:
        alvo = encontrar_ultima_interacao(get_conversation(), {"Nebula"})
        comentario = self.feedback_conversa_texto.get().strip()
        if self._salvar_feedback(alvo, "conversa", avaliacao, comentario):
            self.feedback_conversa_texto.delete(0, "end")
            rotulo = "positivo" if avaliacao == "positivo" else "de melhoria"
            self.feedback_conversa_status.configure(
                text=f"Feedback {rotulo} salvo na memória da Nebula.",
                fg="#18743b" if avaliacao == "positivo" else "#c2410c",
            )

    def _registrar_feedback_grupo(self, avaliacao: str) -> None:
        escolha = self.feedback_grupo_autor.get()
        autores = {"Codex"} if escolha == "Última IA" else {escolha}
        alvo = encontrar_ultima_interacao(self.grupo.historico(), autores)
        comentario = self.feedback_grupo_texto.get().strip()
        if self._salvar_feedback(alvo, "grupo", avaliacao, comentario):
            self.feedback_grupo_texto.delete(0, "end")
            autor = alvo["autor"] if alvo else escolha
            self.grupo_status.configure(
                text=f"Feedback sobre {autor} salvo e incluído na memória compartilhada.",
                fg="#18743b" if avaliacao == "positivo" else "#c2410c",
            )

    def _salvar_feedback(
        self,
        alvo: dict[str, str] | None,
        canal: str,
        avaliacao: str,
        comentario: str,
    ) -> bool:
        if not alvo:
            messagebox.showinfo(
                "Feedback", "Ainda não há uma resposta desse participante para avaliar.",
                parent=self.janela,
            )
            return False
        try:
            MEMORIA.registrar_feedback(
                canal=canal,
                autor=alvo["autor"],
                pergunta=alvo["pergunta"],
                resposta=alvo["resposta"],
                avaliacao=avaliacao,
                comentario=comentario,
                alvo_id=alvo["alvo_id"],
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Feedback", str(exc), parent=self.janela)
            return False
        return True

    def _enviar_grupo(self, modo: str) -> None:
        texto = self.grupo_entrada.get().strip()
        participantes = {
            "grupo": ("codex",),
            "qwen": ("qwen",),
            "codex": ("codex",),
        }[modo]
        try:
            self.grupo.enviar(texto, participantes)
        except (ValueError, GrupoOcupadoError) as exc:
            self.grupo_status.configure(text=str(exc), fg="#c43224")
            return
        self.grupo_entrada.delete(0, "end")

    def _adicionar_mensagem_grupo(self, mensagem: dict[str, object]) -> None:
        autor = str(mensagem.get("autor", "Participante"))
        texto = str(mensagem.get("texto", ""))
        criado_em = float(mensagem.get("criado_em", 0) or 0)
        horario = time.strftime("%H:%M", time.localtime(criado_em)) if criado_em else ""
        tag = {
            "Você": "grupo_voce", "Qwen": "grupo_qwen",
            "Codex": "grupo_codex", "Sistema": "grupo_sistema",
        }.get(autor, "grupo_sistema")
        self.grupo_historico.configure(state="normal")
        cabecalho = f"{autor}  {horario}" if horario else autor
        self.grupo_historico.insert("end", f"{cabecalho}\n", tag)
        self.grupo_historico.insert("end", f"{texto}\n\n")
        self.grupo_historico.configure(state="disabled")
        self.grupo_historico.see("end")

    def _limpar_grupo(self) -> None:
        if not messagebox.askyesno(
            "Limpar grupo",
            "Apagar todo o histórico do grupo? Esta ação não pode ser desfeita.",
            parent=self.janela,
        ):
            return
        try:
            self.grupo.limpar()
        except GrupoOcupadoError as exc:
            self.grupo_status.configure(text=str(exc), fg="#c43224")

    def _abrir_feedbacks(self) -> None:
        existente = getattr(self, "janela_feedbacks", None)
        if existente is not None and existente.winfo_exists():
            existente.lift()
            existente.focus_force()
            self._recarregar_feedbacks()
            return

        janela = tk.Toplevel(self.janela)
        self.janela_feedbacks = janela
        janela.title("Feedbacks locais da Nebula")
        janela.geometry("780x560")
        janela.minsize(620, 440)
        janela.configure(bg=FUNDO)
        janela.transient(self.janela)

        area = tk.Frame(janela, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=24, pady=20)
        tk.Label(
            area, text="Feedbacks locais", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            area,
            text=(
                "São usados como sinais para a Nebula e o Codex entenderem seu jeito. Não são "
                "enviados automaticamente à OpenAI nem a terceiros."
            ),
            bg=FUNDO, fg=SECUNDARIO, justify="left", wraplength=720,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 3))
        tk.Label(
            area, text=str(MEMORIA.feedback_file), bg=FUNDO, fg="#98a2b3",
            font=("Consolas", 8),
        ).pack(anchor="w", pady=(0, 10))
        self.editor_feedbacks = scrolledtext.ScrolledText(
            area, wrap="word", state="disabled", bg="#f7f9fc", fg=TEXTO,
            relief="flat", bd=0, padx=14, pady=12, font=("Segoe UI", 10),
        )
        self.editor_feedbacks.pack(fill="both", expand=True)
        barra = tk.Frame(area, bg=FUNDO)
        barra.pack(fill="x", pady=(10, 0))
        self.feedbacks_contagem = tk.Label(
            barra, text="", bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 9),
        )
        self.feedbacks_contagem.pack(side="left")
        tk.Button(
            barra, text="Apagar todos", command=self._limpar_feedbacks,
            bg="#fff1f0", fg="#c43224", relief="flat", bd=0,
            padx=12, pady=7, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="right")
        self._recarregar_feedbacks()

    def _recarregar_feedbacks(self) -> None:
        feedbacks = MEMORIA.listar_feedbacks()
        if not hasattr(self, "editor_feedbacks"):
            return
        linhas = []
        for item in reversed(feedbacks):
            horario = time.strftime(
                "%d/%m/%Y %H:%M", time.localtime(float(item.get("criado_em", 0) or 0))
            )
            avaliacao = "👍 Funcionou bem" if item["avaliacao"] == "positivo" else "👎 Precisa melhorar"
            linhas.append(
                f"{avaliacao}  •  {item['autor']}  •  {item['canal']}  •  {horario}\n"
                f"Você: {item['pergunta'] or '(fala anterior não registrada)'}\n"
                f"Resposta: {item['resposta']}\n"
                + (f"Seu comentário: {item['comentario']}\n" if item["comentario"] else "")
            )
        self.editor_feedbacks.configure(state="normal")
        self.editor_feedbacks.delete("1.0", "end")
        self.editor_feedbacks.insert(
            "1.0", "\n".join(linhas) if linhas else "Nenhum feedback salvo ainda."
        )
        self.editor_feedbacks.configure(state="disabled")
        self.feedbacks_contagem.configure(text=f"{len(feedbacks)} feedback(s) salvo(s)")

    def _limpar_feedbacks(self) -> None:
        if not messagebox.askyesno(
            "Apagar feedbacks",
            "Apagar todos os feedbacks locais? A Nebula deixará de receber esses sinais.",
            parent=self.janela_feedbacks,
        ):
            return
        MEMORIA.limpar_feedbacks()
        self._recarregar_feedbacks()

    def _abrir_contexto_grupo(self) -> None:
        existente = getattr(self, "janela_contexto", None)
        if existente is not None and existente.winfo_exists():
            existente.lift()
            existente.focus_force()
            return

        janela = tk.Toplevel(self.janela)
        self.janela_contexto = janela
        janela.title("Contexto compartilhado da Nebula")
        janela.geometry("760x680")
        janela.minsize(620, 540)
        janela.configure(bg=FUNDO)
        janela.transient(self.janela)

        area = tk.Frame(janela, bg=FUNDO)
        area.pack(fill="both", expand=True, padx=24, pady=20)
        tk.Label(
            area, text="Memória compartilhada", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")
        tk.Label(
            area,
            text=(
                "Nebu e Codex recebem este contexto. A base mantida pelo Codex "
                "também é acrescentada automaticamente."
            ),
            bg=FUNDO, fg=SECUNDARIO, justify="left", wraplength=700,
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(4, 9))

        self.editor_contexto = scrolledtext.ScrolledText(
            area, height=12, wrap="word", bg="#f7f9fc", fg=TEXTO,
            insertbackground=TEXTO, relief="flat", bd=0,
            padx=12, pady=10, font=("Segoe UI", 10),
        )
        self.editor_contexto.pack(fill="both", expand=True)
        self.editor_contexto.insert("1.0", MEMORIA.ler_contexto_usuario())

        barra = tk.Frame(area, bg=FUNDO)
        barra.pack(fill="x", pady=(8, 16))
        tk.Button(
            barra, text="Salvar contexto", command=self._salvar_contexto_grupo,
            bg=AZUL, fg="white", relief="flat", bd=0, padx=14, pady=8,
            font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left")

        tk.Label(
            area, text="Correções de entendimento", bg=FUNDO, fg=TEXTO,
            font=("Segoe UI Semibold", 13),
        ).pack(anchor="w")
        tk.Label(
            area,
            text='Exemplo: se o microfone escreve “nevo”, ensine para interpretar como “nebu”.',
            bg=FUNDO, fg=SECUNDARIO, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 7))

        self.lista_correcoes = tk.Listbox(
            area, height=6, bg="#f7f9fc", fg=TEXTO, relief="flat", bd=0,
            selectbackground=AZUL, selectforeground="white", font=("Segoe UI", 10),
        )
        self.lista_correcoes.pack(fill="x")

        formulario = tk.Frame(area, bg=FUNDO)
        formulario.pack(fill="x", pady=(8, 0))
        self.correcao_ouvido = tk.Entry(
            formulario, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 10), insertbackground=TEXTO,
        )
        self.correcao_ouvido.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 7))
        self.correcao_ouvido.insert(0, "O microfone escreveu…")
        self.correcao_correto = tk.Entry(
            formulario, bg="#f2f5f9", fg=TEXTO, relief="flat", bd=0,
            font=("Segoe UI", 10), insertbackground=TEXTO,
        )
        self.correcao_correto.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 7))
        self.correcao_correto.insert(0, "Deveria entender…")
        tk.Button(
            formulario, text="Adicionar", command=self._adicionar_correcao_contexto,
            bg="#edf8f2", fg=AZUL_ESCURO, relief="flat", bd=0,
            padx=12, pady=8, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(side="left")
        tk.Button(
            area, text="Remover correção selecionada",
            command=self._remover_correcao_contexto,
            bg="#fff1f0", fg="#c43224", relief="flat", bd=0,
            padx=12, pady=7, font=("Segoe UI Semibold", 9), cursor="hand2",
        ).pack(anchor="e", pady=(7, 0))
        self._recarregar_correcoes_contexto()

    def _salvar_contexto_grupo(self) -> None:
        try:
            MEMORIA.salvar_contexto_usuario(self.editor_contexto.get("1.0", "end").strip())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Contexto", str(exc), parent=self.janela_contexto)
            return
        self.grupo_status.configure(text="Contexto atualizado para Nebu e Codex.", fg=SECUNDARIO)
        messagebox.showinfo("Contexto", "Memória compartilhada salva.", parent=self.janela_contexto)

    def _recarregar_correcoes_contexto(self) -> None:
        self.lista_correcoes.delete(0, "end")
        self.chaves_correcoes = list(MEMORIA.listar_correcoes())
        correcoes = MEMORIA.listar_correcoes()
        for ouvido in self.chaves_correcoes:
            self.lista_correcoes.insert("end", f"{ouvido}  →  {correcoes[ouvido]}")

    def _adicionar_correcao_contexto(self) -> None:
        ouvido = self.correcao_ouvido.get().strip()
        correto = self.correcao_correto.get().strip()
        marcadores = {"O microfone escreveu…", "Deveria entender…"}
        if ouvido in marcadores:
            ouvido = ""
        if correto in marcadores:
            correto = ""
        try:
            MEMORIA.registrar_correcao(ouvido, correto)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Correção", str(exc), parent=self.janela_contexto)
            return
        self.correcao_ouvido.delete(0, "end")
        self.correcao_correto.delete(0, "end")
        self._recarregar_correcoes_contexto()
        self.grupo_status.configure(text="Nova correção aplicada ao entendimento da Nebu.", fg=SECUNDARIO)

    def _remover_correcao_contexto(self) -> None:
        selecao = self.lista_correcoes.curselection()
        if not selecao:
            return
        ouvido = self.chaves_correcoes[selecao[0]]
        MEMORIA.remover_correcao(ouvido)
        self._recarregar_correcoes_contexto()

    def _evento(self, tipo: str, valor: object) -> None:
        self.eventos.put((tipo, valor))

    def _definir_pausa_remota(self, pausada: bool) -> None:
        if pausada:
            self.pausada.set()
            try:
                while True:
                    self.comandos.get_nowait()
            except queue.Empty:
                pass
        else:
            self.pausada.clear()
        self._evento("pausada", pausada)

    def _receber_comando_remoto(self, comando: str) -> None:
        self.comandos.put(comando.lower().strip())
        self._evento("usuario_remoto", comando)

    def _estado_controle_remoto(self) -> dict[str, object]:
        nebula = self.nebula
        if nebula is None:
            return {
                "ready": False, "muted": True, "mode": "starting",
                "rpm": None, "rpm_percent": None, "range": None,
                "receiving": False, "telemetry_valid": False,
                "lamp": "iniciando", "error": None,
            }
        return nebula.estado_controle()

    def _executar_controle_remoto(
        self, acao: str, valor: object | None,
    ) -> dict[str, object]:
        nebula = self.nebula
        if nebula is None:
            raise RuntimeError("A Nebula ainda esta iniciando.")
        return nebula.executar_controle(acao, valor)

    def _executar_assistente(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            voz = Voz(
                ao_falar=lambda texto: self._evento("nebula", texto),
                ao_mudar_estado=lambda estado: self._evento("falando", estado),
            )
            microfone = Microfone(voz)
            self.nebula = Nebula(
                voz,
                ao_solicitar_texto=lambda: self._evento("solicitar_texto", True),
                iniciar_muda=True,
            )
            self._evento("sistema", "Nebula pronta. Aguardando um nome de ativação.")
            self._evento("pronto", True)
            while not self.parar.is_set():
                if self.pausada.wait(0.2):
                    continue
                try:
                    digitado = self.comandos.get_nowait()
                except queue.Empty:
                    digitado = None

                if digitado:
                    chamou, sem_ativacao = extrair_chamada(digitado)
                    comando = sem_ativacao if chamou else digitado.strip(" ,")
                    if comando and not self.nebula.executar(comando):
                        self.parar.set()
                        break
                    continue

                # Não deixa o microfone capturar a própria voz da Nebula. Comandos
                # de texto e do celular são verificados antes e continuam livres.
                if voz.esta_falando:
                    self.parar.wait(0.08)
                    continue

                texto = microfone.ouvir()
                if self.pausada.is_set():
                    continue
                if not texto:
                    continue
                chamou, comando = extrair_chamada(texto)
                if not chamou and not self.nebula.aguardando_resposta:
                    continue
                self._evento("usuario_voz", texto)
                if self.nebula.aguardando_resposta:
                    if not chamou:
                        comando = texto
                else:
                    if comando_incompleto(comando):
                        continuacao = microfone.ouvir()
                        if continuacao:
                            self._evento("usuario_voz", continuacao)
                            comando = continuacao
                        else:
                            voz.falar(random.choice(RESPOSTAS_ATIVACAO))
                            comando = microfone.ouvir()
                            if comando:
                                self._evento("usuario_voz", comando)
                if comando and not self.nebula.executar(comando):
                    self.parar.set()
                    break
        except Exception as exc:
            self._evento("erro", str(exc))
        finally:
            if self.nebula is not None:
                self.nebula.fechar()
            pythoncom.CoUninitialize()

    def _processar_eventos(self) -> None:
        try:
            while True:
                tipo, valor = self.eventos.get_nowait()
                if tipo == "rocket_overlay":
                    self.rocket_overlay.apply(*valor)
                elif tipo == "nebula":
                    add_conversation_message("Nebula", str(valor))
                elif tipo == "usuario_voz":
                    add_conversation_message("Você", str(valor))
                elif tipo == "usuario_remoto":
                    pass  # O servidor já incluiu esta mensagem no histórico compartilhado.
                elif tipo == "sistema":
                    add_conversation_message("Sistema", str(valor))
                elif tipo == "falando":
                    self.falando = bool(valor)
                    self.status.configure(
                        text="Nebula falando..." if valor else (
                            "Escutando você..." if self.ouvindo else "Ativa"
                        )
                    )
                elif tipo == "ouvindo":
                    self.ouvindo = bool(valor)
                    if not self.falando:
                        self.status.configure(text="Escutando você..." if valor else "Processando...")
                elif tipo == "pronto":
                    self.status.configure(text="Ativa e aguardando 'Nebula'")
                elif tipo == "pausada":
                    self.status.configure(text="Pausada pelo celular" if valor else "Ativa e aguardando 'Nebula'")
                    add_conversation_message("Sistema", "Nebula pausada pelo celular." if valor else "Nebula retomada pelo celular.")
                elif tipo == "tema":
                    self._aplicar_tema(bool(valor))
                elif tipo == "controle_resultado" and isinstance(valor, dict):
                    self.controle_status.configure(
                        text=str(valor.get("message", "Controle atualizado.")),
                        fg="#f3a43b",
                    )
                elif tipo == "controle_erro":
                    self.controle_status.configure(
                        text=f"Falha no controle: {valor}", fg="#ff8f9a"
                    )
                    if hasattr(self, "casa_ar_status"):
                        self.casa_ar_status.configure(text=str(valor), fg="#ff8f9a")
                elif tipo == "casa_tv_resultado" and isinstance(valor, dict):
                    itens = valor.get("tvs")
                    if isinstance(itens, list):
                        self._casa_render_tvs(itens)
                    else:
                        self._casa_render_tvs(self.tv_manager.list())
                    self.casa_tv_status.configure(
                        text=str(valor.get("message", "Comando concluído.")), fg="#f3a43b"
                    )
                elif tipo == "casa_tv_erro":
                    self.casa_tv_status.configure(text=str(valor), fg="#ff8f9a")
                elif tipo == "erro":
                    self.status.configure(text="Erro ao iniciar", fg="#d92d20")
                    add_conversation_message("Nebula", f"Erro: {valor}")
                elif tipo == "solicitar_texto":
                    self.mostrar_aba("conversa")
                    self.entrada.focus_set()
                elif tipo == "grupo_mensagem" and isinstance(valor, dict):
                    self._adicionar_mensagem_grupo(valor)
                elif tipo == "grupo_status":
                    self.grupo_status.configure(text=str(valor), fg=SECUNDARIO)
                elif tipo == "grupo_ocupado":
                    estado = "disabled" if valor else "normal"
                    self.grupo_entrada.configure(state=estado)
                    for botao in self.botoes_envio_grupo:
                        botao.configure(state=estado)
                    if not valor:
                        self.grupo_entrada.focus_set()
                elif tipo == "grupo_limpo":
                    self.grupo_historico.configure(state="normal")
                    self.grupo_historico.delete("1.0", "end")
                    self.grupo_historico.configure(state="disabled")
                    self.grupo_status.configure(text="Histórico do grupo apagado.", fg=SECUNDARIO)
                elif tipo == "tuya_deteccao_ok":
                    self._aplicar_deteccao_tuya(valor)
                elif tipo == "tuya_deteccao_erro":
                    self._definir_tuya_ocupado(False)
                    mensagem = str(valor)
                    self.tuya_status.configure(text=mensagem, fg="#c2410c")
                    messagebox.showerror(
                        "Detecção Tuya", mensagem, parent=self.janela
                    )
                elif tipo == "tuya_salvar_erro":
                    self._definir_tuya_ocupado(False)
                    mensagem = str(valor)
                    self.tuya_status.configure(text=mensagem, fg="#c2410c")
                    messagebox.showerror(
                        "Configuração Tuya", mensagem, parent=self.janela
                    )
                elif tipo == "tuya_teste_erro":
                    self._definir_tuya_ocupado(False)
                    mensagem = str(valor)
                    self.tuya_status.configure(
                        text=f"Configuração salva, mas o teste somente leitura falhou. {mensagem}",
                        fg="#c2410c",
                    )
                    messagebox.showwarning(
                        "Configuração Tuya",
                        f"A configuração foi salva, mas o abajur não respondeu.\n\n{mensagem}",
                        parent=self.janela,
                    )
                elif tipo == "tuya_configuracao_ok":
                    self._finalizar_configuracao_tuya(valor)
        except queue.Empty:
            pass
        agora = time.monotonic()
        self._sincronizar_historico()
        if agora >= self.proxima_atualizacao_codex:
            self.proxima_atualizacao_codex = agora + 1.0
            self._atualizar_painel_codex()
            self._atualizar_mobile()
        if not self.parar.is_set():
            self.janela.after(40, self._processar_eventos)

    def _sincronizar_historico(self) -> None:
        """Espelha no desktop as mensagens recebidas por qualquer dispositivo."""
        mensagens = get_conversation()
        if mensagens == self.historico_snapshot:
            return
        self.historico.configure(state="normal")
        self.historico.delete("1.0", "end")
        self.historico.configure(state="disabled")
        for mensagem in mensagens:
            self.adicionar_mensagem(mensagem["author"], mensagem["text"])
        self.mensagens_renderizadas = len(mensagens)
        self.historico_snapshot = mensagens

    def _atualizar_painel_codex(self) -> None:
        job = get_latest_job()
        if not job:
            return
        iniciado = float(job.get("started_at", time.time()))
        segundos = max(0, int(time.time() - iniciado))
        estado = str(job.get("status", "Concluído")) if job.get("done") else f"Executando há {segundos // 60} min {segundos % 60} s"
        projeto = str(job.get("project", ""))
        texto = str(job.get("output") or job.get("status", "Executando"))
        chave = f"{estado}|{projeto}|{texto}"
        if chave == self.ultimo_codex_renderizado:
            return
        self.ultimo_codex_renderizado = chave
        self.codex_status.configure(text=f"Codex — {estado} — {projeto}")
        self.codex_resultado.configure(state="normal")
        self.codex_resultado.delete("1.0", "end")
        self.codex_resultado.insert("1.0", texto)
        self.codex_resultado.configure(state="disabled")

    def _desenhar_esfera(self) -> None:
        self.canvas.delete("esfera")
        largura = max(self.canvas.winfo_width(), 300)
        altura = max(self.canvas.winfo_height(), 300)
        raio_base = min(largura, altura) * 0.29
        # Ao ouvir, a esfera se aproxima com um zoom suave. Ao responder,
        # ela troca para uma pulsação mais viva sem um salto de tamanho.
        respiracao = math.sin(self.fase) * 0.045 if self.falando else 0
        raio = raio_base * self.escala_esfera * (1 + respiracao)
        cx, cy = largura / 2, altura / 2

        # Halo em camadas, misturado ao fundo para produzir um brilho suave.
        fundo_rgb = (11, 18, 32) if self.modo_escuro else (255, 255, 255)
        brilho_rgb = (39, 140, 245)
        pulso_halo = 1.0 + math.sin(self.fase) * (0.11 if self.falando else 0.035)
        for i in range(12):
            proporcao = i / 11
            expansao = 1.30 - proporcao * 0.25
            intensidade = (
                (0.035 + proporcao * 0.13)
                * pulso_halo
                * (1.22 if self.falando else (1.12 if self.ouvindo else 1))
            )
            cor_rgb = tuple(
                int(base + (azul - base) * intensidade)
                for base, azul in zip(fundo_rgb, brilho_rgb)
            )
            cor = f"#{cor_rgb[0]:02x}{cor_rgb[1]:02x}{cor_rgb[2]:02x}"
            self.canvas.create_oval(
                cx - raio * expansao, cy - raio * expansao,
                cx + raio * expansao, cy + raio * expansao,
                fill=cor, outline="", tags="esfera",
            )
        passos = 42
        for i in range(passos, 0, -1):
            proporcao = i / passos
            r = raio * proporcao
            mistura = 1 - proporcao
            vermelho = int(39 + (149 - 39) * mistura)
            verde = int(140 + (210 - 140) * mistura)
            azul = int(245 + (255 - 245) * mistura)
            cor = f"#{vermelho:02x}{verde:02x}{azul:02x}"
            deslocamento = (1 - proporcao) * raio * 0.18
            self.canvas.create_oval(
                cx - r + deslocamento, cy - r + deslocamento,
                cx + r + deslocamento, cy + r + deslocamento,
                fill=cor, outline="", tags="esfera",
            )

    def _animar_esfera(self) -> None:
        alvo = 1.13 if self.ouvindo and not self.falando else 1.0
        # Interpolação exponencial: zoom perceptível, porém sem mudança brusca.
        self.escala_esfera += (alvo - self.escala_esfera) * 0.16
        self.fase += 0.075 if self.falando else (0.035 if self.ouvindo else 0.015)
        self._desenhar_esfera()
        if not self.parar.is_set():
            self.janela.after(40, self._animar_esfera)

    def _criar_icone_bandeja(self) -> pystray.Icon:
        try:
            imagem = Image.open(caminho_recurso("assets", "nebula.png")).convert("RGBA")
        except OSError:
            imagem = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            desenho = ImageDraw.Draw(imagem)
            desenho.ellipse((6, 6, 58, 58), fill=(39, 140, 245, 255))
        menu = pystray.Menu(
            pystray.MenuItem(
                "Abrir Nebula",
                lambda _icone, _item: self.janela.after(0, self.mostrar_janela),
                default=True,
            ),
            pystray.MenuItem(
                "Sair",
                lambda _icone, _item: self.janela.after(0, self.fechar),
            ),
        )
        return pystray.Icon("Nebula", imagem, "Nebula", menu)

    def ocultar_na_bandeja(self) -> None:
        self.janela.withdraw()
        if not self.aviso_bandeja_exibido:
            self.aviso_bandeja_exibido = True
            try:
                self.icone_bandeja.notify(
                    "Continuo ouvindo e disponível pelo celular.", "Nebula em segundo plano"
                )
            except Exception:
                pass

    def mostrar_janela(self) -> None:
        self.janela.deiconify()
        self.janela.state("normal")
        # O Windows pode impedir que uma janela em segundo plano roube o foco.
        # Um breve topmost torna a restauração visível após o desbloqueio e é
        # removido logo depois para a Nebula não ficar sobre outros programas.
        self.janela.attributes("-topmost", True)
        self.janela.lift()
        self.janela.focus_force()
        self.janela.after(800, lambda: self.janela.attributes("-topmost", False))

    def fechar(self) -> None:
        self.parar.set()
        self.rocket_overlay.stop()
        OVERLAY_BRIDGE.unregister()
        if self.nebula is not None:
            self.nebula.fechar()
        self.servidor_remoto.shutdown()
        self.icone_bandeja.stop()
        self.janela.destroy()

    def executar(self) -> None:
        self.janela.mainloop()


if __name__ == "__main__":
    iniciar_servidor_do_notebook()
    InterfaceNebula().executar()
