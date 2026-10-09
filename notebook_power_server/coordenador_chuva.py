"""Coordena o modo chuva no hub: sessão, trovões, abajur, ar e telas.

O hub fica ligado a noite toda e é o relógio de referência. Ele dispara o
relâmpago no abajur e o som do trovão no notebook; o celular toca o mesmo trovão
lendo a lista em ``estado()``. O ar alterna 1 hora ligado e 1 hora desligado.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import threading
import time
from typing import Callable

try:
    from modo_chuva import (
        PESQUISA_PADRAO, Trovao, ar_ligado_no_ciclo, extrair_video_id, gerar_trovoes,
        sintetizar_trovao,
    )
except ImportError:  # executado de dentro de notebook_power_server/
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from modo_chuva import (  # type: ignore[no-redef]
        PESQUISA_PADRAO, Trovao, ar_ligado_no_ciclo, extrair_video_id, gerar_trovoes,
        sintetizar_trovao,
    )

# Retomada depois de um reinício do hub só dentro da mesma noite.
DURACAO_MAXIMA_S = 16 * 3600
ATRASO_INICIO_S = 3.0
"""Folga para as telas abrirem antes do instante zero do vídeo."""
ANTECEDENCIA_TROVAO_S = 10.0
JANELA_TROVOES_S = 15 * 60
NOVA_TENTATIVA_AR_S = 60.0


class CoordenadorChuva:
    def __init__(
        self,
        *,
        caminho: Path,
        ar: object | None = None,
        timer_ar: object | None = None,
        lampada: Callable[[], object | None] = lambda: None,
        tocar: Callable[[bytes], None] = lambda _dados: None,
        tela: object | None = None,
        url_tela: Callable[[str], str] = lambda chave: f"http://127.0.0.1:8766/hub/chuva.html?k={chave}",
        avisar_pc: Callable[[str, object], object] | None = None,
        url_pc: Callable[[str], str | None] = lambda _chave: None,
        resolver_video: Callable[[str], str | None] | None = None,
        relogio: Callable[[], float] = time.time,
        aguardar: Callable[[float], None] = time.sleep,
        em_segundo_plano: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.caminho = Path(caminho)
        self.ar, self.timer_ar, self.lampada = ar, timer_ar, lampada
        self.tocar, self.tela, self.url_tela = tocar, tela, url_tela
        self.avisar_pc, self.url_pc = avisar_pc, url_pc
        self.resolver_video = resolver_video or _primeiro_video
        self.relogio, self.aguardar = relogio, aguardar
        self._fundo = em_segundo_plano or (
            lambda tarefa: threading.Thread(target=tarefa, daemon=True, name="Chuva").start()
        )
        self._lock = threading.RLock()
        self._sessao: dict[str, object] | None = None
        self._trovoes: list[Trovao] = []
        self._disparados: set[float] = set()
        self._ar_aplicado: bool | None = None
        self._ar_tentar_em = 0.0
        self._ar_ocupado = False
        self._erros: dict[str, str] = {}
        self._carregar()

    # -- sessão -----------------------------------------------------------

    def _carregar(self) -> None:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        campos = ("video_id", "inicio", "semente", "chave", "origem")
        if not isinstance(dados, dict) or not all(campo in dados for campo in campos):
            return
        try:
            inicio = float(dados["inicio"])
            semente = int(dados["semente"])
        except (TypeError, ValueError):
            return
        video_id = extrair_video_id(dados["video_id"])
        if video_id is None or not 0 <= self.relogio() - inicio < DURACAO_MAXIMA_S:
            return
        self._sessao = {
            "video_id": video_id, "inicio": inicio, "semente": semente,
            "chave": str(dados["chave"]), "origem": str(dados["origem"]),
        }
        self._trovoes = gerar_trovoes(semente, inicio, inicio + DURACAO_MAXIMA_S)
        # Trovões que já passaram não tocam ao retomar.
        self._disparados = {t.instante for t in self._trovoes if t.instante < self.relogio()}

    def _salvar(self) -> None:
        if self._sessao is None:
            try:
                self.caminho.unlink()
            except OSError:
                pass
            return
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        temporario.write_text(json.dumps(self._sessao), encoding="utf-8")
        temporario.replace(self.caminho)

    @property
    def ativo(self) -> bool:
        return self._sessao is not None

    def autoriza(self, chave: object) -> bool:
        """Chave de uso da página da sessão atual; nada além disso."""
        with self._lock:
            esperada = str(self._sessao["chave"]) if self._sessao else ""
        return bool(esperada) and isinstance(chave, str) and secrets.compare_digest(chave, esperada)

    def iniciar(self, video: object = "", origem: str = "hub") -> dict[str, object]:
        pedido = str(video or "").strip()
        video_id = extrair_video_id(pedido)
        if video_id is None:
            video_id = extrair_video_id(self.resolver_video(pedido or PESQUISA_PADRAO) or "")
        if video_id is None:
            raise ValueError("Não encontrei um vídeo de chuva no YouTube. Envie um link.")
        if self.ativo:
            # Troca de vídeo: as telas reabrem com a sessão nova. Avisar o PC
            # para parar aqui correria contra o aviso de iniciar logo abaixo.
            self.parar("reinicio", avisar=False)
        inicio = self.relogio() + ATRASO_INICIO_S
        semente = secrets.randbits(31)
        chave = secrets.token_urlsafe(18)
        with self._lock:
            self._sessao = {
                "video_id": video_id, "inicio": inicio, "semente": semente,
                "chave": chave, "origem": str(origem)[:40],
            }
            self._trovoes = gerar_trovoes(semente, inicio, inicio + DURACAO_MAXIMA_S)
            self._disparados = set()
            self._ar_aplicado = None
            self._ar_tentar_em = 0.0
            self._erros = {}
            self._salvar()
        # O ciclo é dono do ar enquanto o modo estiver ativo.
        cancelar_timer = getattr(self.timer_ar, "set", None)
        if callable(cancelar_timer):
            try:
                cancelar_timer(0)
            except (OSError, ValueError):
                pass
        self._fundo(self._apagar_abajur)
        if self.tela is not None:
            try:
                self.tela.abrir(self.url_tela(chave))
            except OSError as exc:
                self._erros["notebook"] = f"A tela do notebook não abriu: {exc}"
        self._fundo(lambda: self._avisar_pc("chuva.iniciar", chave))
        return self.estado()

    def parar(self, motivo: str = "pedido", *, avisar: bool = True) -> dict[str, object]:
        with self._lock:
            sessao, self._sessao = self._sessao, None
            self._trovoes, self._disparados = [], set()
            self._salvar()
        if sessao is not None and avisar:
            if self.tela is not None:
                self.tela.fechar()
            self._fundo(lambda: self._avisar_pc("chuva.parar", ""))
        # O ar e o abajur ficam como estão: quem acorda decide.
        return {**self.estado(), "motivo": str(motivo)[:40]}

    # -- efeitos ----------------------------------------------------------

    def _apagar_abajur(self) -> None:
        lampada = self.lampada()
        if lampada is None:
            return
        try:
            lampada.energia(False)
        except Exception as exc:
            self._erros["abajur"] = str(exc)

    def _avisar_pc(self, acao: str, chave: str) -> None:
        if self.avisar_pc is None:
            return
        try:
            if acao == "chuva.iniciar":
                url = self.url_pc(chave)
                if url is None:
                    raise RuntimeError("O hub não descobriu o próprio endereço para o PC.")
                self.avisar_pc(acao, {"url": url})
            else:
                self.avisar_pc(acao, "")
            self._erros.pop("pc", None)
        except Exception as exc:
            self._erros["pc"] = f"PC fora do modo chuva: {exc}"

    def _executar_trovao(self, trovao: Trovao, chave: object) -> None:
        def ainda_ativo() -> bool:
            return self._sessao is not None and self._sessao.get("chave") == chave

        som = sintetizar_trovao(trovao.semente, trovao.intensidade)
        self.aguardar(max(0.0, trovao.instante - self.relogio()))
        if not ainda_ativo():
            return
        lampada = self.lampada()
        if lampada is not None:
            def relampago() -> None:
                try:
                    lampada.relampago(trovao.flashes)
                except Exception as exc:
                    self._erros["abajur"] = str(exc)
            self._fundo(relampago)
        self.aguardar(max(0.0, trovao.som - self.relogio()))
        if ainda_ativo():
            try:
                self.tocar(som)
            except Exception as exc:
                self._erros["som"] = str(exc)

    def _aplicar_ar(self, ligar: bool) -> None:
        try:
            self.ar.executar("power", ligar)  # type: ignore[union-attr]
            with self._lock:
                self._ar_aplicado = ligar
            self._erros.pop("ar", None)
        except Exception as exc:
            self._erros["ar"] = str(exc)
            self._ar_tentar_em = self.relogio() + NOVA_TENTATIVA_AR_S
        finally:
            self._ar_ocupado = False

    def tick(self) -> None:
        agora = self.relogio()
        with self._lock:
            sessao = self._sessao
            if sessao is None:
                return
            inicio = float(sessao["inicio"])  # type: ignore[arg-type]
            for trovao in self._trovoes:
                if trovao.instante - agora > ANTECEDENCIA_TROVAO_S:
                    break
                if trovao.instante in self._disparados:
                    continue
                self._disparados.add(trovao.instante)
                if agora - trovao.instante < 5.0:
                    self._fundo(lambda t=trovao, c=sessao["chave"]: self._executar_trovao(t, c))
            ligar = ar_ligado_no_ciclo(inicio, agora)
            aplicar = (
                self.ar is not None and not self._ar_ocupado and ligar != self._ar_aplicado
                and agora >= self._ar_tentar_em
            )
            if aplicar:
                self._ar_ocupado = True
        if aplicar:
            self._fundo(lambda: self._aplicar_ar(ligar))

    def iniciar_loop(self) -> None:
        def laco() -> None:
            while True:
                try:
                    self.tick()
                except Exception:
                    pass
                time.sleep(0.2)
        threading.Thread(target=laco, daemon=True, name="ChuvaTick").start()

    # -- estado -----------------------------------------------------------

    def estado(self) -> dict[str, object]:
        """Estado para o app do celular: inclui os trovões dos próximos minutos."""
        agora = self.relogio()
        with self._lock:
            sessao = self._sessao
            if sessao is None:
                return {"ativo": False, "agora": agora}
            inicio = float(sessao["inicio"])  # type: ignore[arg-type]
            proximos = [
                t.para_json() for t in self._trovoes
                if agora - 5.0 <= t.som and t.instante <= agora + JANELA_TROVOES_S
            ]
            ligar = ar_ligado_no_ciclo(inicio, agora)
            troca = inicio + (int(max(0.0, agora - inicio) // 3600) + 1) * 3600
            return {
                "ativo": True,
                "agora": agora,
                "inicio": inicio,
                "video_id": sessao["video_id"],
                "origem": sessao["origem"],
                "trovoes": proximos,
                "ar": {"ligado": ligar, "proxima_troca": troca, "aplicado": self._ar_aplicado},
                "erros": dict(self._erros),
            }

    def estado_tela(self) -> dict[str, object]:
        """O mínimo que a página do vídeo precisa, sem a lista de trovões."""
        estado = self.estado()
        return {chave: estado[chave] for chave in ("ativo", "agora", "inicio", "video_id") if chave in estado}


def _primeiro_video(pesquisa: str) -> str | None:
    try:
        from youtube_player import primeiro_video
    except ImportError:
        return None
    try:
        return primeiro_video(pesquisa)
    except Exception:
        return None


__all__ = ["CoordenadorChuva"]
