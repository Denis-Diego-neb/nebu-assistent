"""Controle local da lâmpada Elgin/ThingClips pelo protocolo Tuya LAN.

O celular é necessário somente para o pareamento inicial e para obter a chave
local. Depois disso, a Nebula conversa diretamente com a lâmpada na rede local.
"""

from __future__ import annotations

import colorsys
from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Protocol

from abajur_wifi import ErroAbajur, _validar_dependencias_ritmo, resolver_cor
from ritmo_navegador import (
    calcular_nivel_pulso,
    FAIXA_MINIMA_RITMO,
    INTENSIDADE_RITMO_PADRAO,
    LIMIAR_PICO_RITMO,
)

try:
    import tinytuya
except ImportError:  # A mensagem de instalação é emitida somente ao usar o controle.
    tinytuya = None  # type: ignore[assignment]


ARQUIVO_CONFIGURACAO = "abajur_tuya.json"
ARQUIVO_CORES = "cores_abajur.json"
VERSOES_SUPORTADAS = {3.1, 3.2, 3.3, 3.4, 3.5}


class AnimacaoLuz(Protocol):
    """Contrato comum para animações internas e modos externos da lâmpada."""

    @property
    def ativo(self) -> bool: ...

    @property
    def erro(self) -> str | None: ...

    def parar(self) -> None: ...


def pasta_dados_nebula() -> Path:
    """Retorna a pasta privada de dados da Nebula para o usuário atual."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Nebula"


@dataclass(frozen=True)
class ConfiguracaoTuya:
    """Credenciais necessárias para uma conexão local Tuya."""

    device_id: str = field(repr=False)
    address: str = "Auto"
    local_key: str = field(default="", repr=False)
    version: float = 3.5

    @classmethod
    def carregar(cls, pasta_dados: Path | None = None) -> "ConfiguracaoTuya | None":
        """Carrega o JSON local e aplica variáveis de ambiente por cima dele."""
        pasta = pasta_dados or pasta_dados_nebula()
        caminho = pasta / ARQUIVO_CONFIGURACAO
        dados: dict[str, object] = {}
        try:
            carregado = json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError:
            carregado = {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ErroAbajur("A configuração local da lâmpada Tuya está inválida.") from exc
        if not isinstance(carregado, dict):
            raise ErroAbajur("A configuração local da lâmpada Tuya está inválida.")
        dados.update(carregado)

        nomes_env = {
            "device_id": "NEBULA_TUYA_DEVICE_ID",
            "address": "NEBULA_TUYA_ADDRESS",
            "local_key": "NEBULA_TUYA_LOCAL_KEY",
            "version": "NEBULA_TUYA_VERSION",
        }
        for campo, nome_env in nomes_env.items():
            valor = os.environ.get(nome_env)
            if valor is not None and valor.strip():
                dados[campo] = valor.strip()

        # Ausência total de configuração mantém a ponte ADB como fallback no
        # executor principal.
        if not dados:
            return None

        # O configurador pode guardar ID/IP antes de a chave ser obtida. Até a
        # configuração ficar completa, o controle USB anterior segue disponível.
        if not str(dados.get("local_key", "")).strip():
            return None

        try:
            versao = float(dados.get("version", 3.5))
        except (TypeError, ValueError) as exc:
            raise ErroAbajur("A versão do protocolo Tuya precisa ser um número, como 3.5.") from exc

        configuracao = cls(
            device_id=str(dados.get("device_id", "")).strip(),
            address=str(dados.get("address", "Auto")).strip() or "Auto",
            local_key=str(dados.get("local_key", "")).strip(),
            version=versao,
        )
        configuracao.validar()
        return configuracao

    def validar(self) -> None:
        """Valida sem incluir credenciais em mensagens ou representações."""
        if not self.device_id:
            raise ErroAbajur(
                "Falta o ID da lâmpada Tuya. Execute configurar_abajur.py."
            )
        if not self.local_key:
            raise ErroAbajur(
                "Falta a chave local Tuya. Use o TinyTuya wizard e execute configurar_abajur.py."
            )
        try:
            chave_ascii = self.local_key.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ErroAbajur("A chave local Tuya deve ter exatamente 16 caracteres ASCII.") from exc
        if len(chave_ascii) != 16:
            raise ErroAbajur("A chave local Tuya deve ter exatamente 16 caracteres ASCII.")
        if self.version not in VERSOES_SUPORTADAS:
            raise ErroAbajur("A versão Tuya deve ficar entre 3.1 e 3.5.")


def _nome_preset(nome: str) -> str:
    nome = " ".join(nome.lower().strip().split())
    if not re.fullmatch(r"[a-z0-9][a-z0-9 _-]{0,39}", nome):
        raise ErroAbajur("Use um nome curto, sem símbolos, para a cor salva.")
    return nome


class ControleAbajurTuya:
    """Controla uma lâmpada RGB+CCT Tuya diretamente pela rede local."""

    _TEMPERATURAS = {"quente": 0, "neutra": 50, "fria": 100}
    _DPS_TIPO_B = {
        "energia": "20",
        "modo": "21",
        "brilho": "22",
        "temperatura": "23",
        "cor": "24",
    }

    def __init__(
        self,
        config: ConfiguracaoTuya,
        pasta_dados: Path | None = None,
    ) -> None:
        config.validar()
        self.config = config
        self._pasta_dados = pasta_dados or pasta_dados_nebula()
        self._dispositivo: Any | None = None
        self._estado_inicial: dict[str, Any] | None = None
        self._ritmo_navegador: AnimacaoLuz | None = None
        self._intensidade_ritmo = INTENSIDADE_RITMO_PADRAO
        self._modo_ritmo = "white"
        self._temperatura_ritmo = 50
        self._matiz_ritmo = 0.0
        self._saturacao_ritmo = 1.0
        self._lock = threading.RLock()

    def _criar_dispositivo(self) -> Any:
        if tinytuya is None:
            raise ErroAbajur(
                "A biblioteca TinyTuya não está instalada. Rode: pip install tinytuya."
            )
        try:
            return tinytuya.BulbDevice(
                dev_id=self.config.device_id,
                address=self.config.address,
                local_key=self.config.local_key,
                version=self.config.version,
                # Comandos comuns abrem e fecham a conexão. Isso deixa a
                # lâmpada livre para o app Tuya quando a Nebula está ociosa.
                persist=False,
                connection_timeout=4,
                connection_retry_limit=2,
                connection_retry_delay=0.5,
            )
        except Exception as exc:
            raise self._traduzir_excecao("preparar a conexão", exc) from exc

    def _obter_dispositivo(self) -> Any:
        if self._dispositivo is None:
            self._dispositivo = self._criar_dispositivo()
        return self._dispositivo

    def _definir_conexao_persistente(self, persistir: bool) -> None:
        """Mantém socket aberto somente durante animações de alta frequência."""
        dispositivo = self._obter_dispositivo()
        configurar = getattr(dispositivo, "set_socketPersistent", None)
        if callable(configurar):
            configurar(persistir)

    def _reconectar_animacao(self) -> None:
        """Descarta um socket Tuya cansado e prepara outro sem mudar o perfil."""
        with self._lock:
            anterior = self._dispositivo
            self._dispositivo = None
            self._estado_inicial = None
            if anterior is not None:
                try:
                    anterior.set_socketPersistent(False)
                except Exception:
                    pass
                try:
                    anterior.close()
                except Exception:
                    pass
            self._consultar_estado(atualizar=True)
            self._definir_conexao_persistente(True)

    def _registrar_falha_ritmo(self, etapa: str, exc: Exception) -> None:
        """Registra somente diagnóstico sanitizado, sem IDs nem chave local."""
        try:
            mensagem = str(self._traduzir_excecao(etapa, exc))
            caminho = self._pasta_dados / "ritmo_tuya.log"
            caminho.parent.mkdir(parents=True, exist_ok=True)
            if caminho.exists() and caminho.stat().st_size > 128 * 1024:
                caminho.write_text("", encoding="utf-8")
            instante = time.strftime("%Y-%m-%d %H:%M:%S")
            with caminho.open("a", encoding="utf-8") as arquivo:
                arquivo.write(
                    f"{instante} {etapa}: {type(exc).__name__}: {mensagem}\n"
                )
        except Exception:
            pass

    @staticmethod
    def _erro_resposta(resposta: object) -> str | None:
        if not isinstance(resposta, dict):
            return "vazia"
        if "Error" not in resposta and "Err" not in resposta:
            return None
        codigo = str(resposta.get("Err", ""))
        if codigo in {"901", "902", "905"}:
            return "rede"
        if codigo == "914":
            return "credencial"
        if codigo == "907":
            return "recurso"
        if codigo == "903":
            return "faixa"
        return "dispositivo"

    def _validar_resposta(
        self,
        resposta: object,
        operacao: str,
        *,
        exigir_dps: bool = False,
    ) -> dict[str, Any]:
        erro = self._erro_resposta(resposta)
        if erro == "rede":
            raise ErroAbajur(
                "Não encontrei a lâmpada na rede local. Confira o Wi-Fi e o endereço configurado."
            )
        if erro == "credencial":
            raise ErroAbajur(
                "A lâmpada recusou a chave local ou a versão do protocolo Tuya."
            )
        if erro == "recurso":
            raise ErroAbajur(f"A lâmpada não oferece o recurso necessário para {operacao}.")
        if erro == "faixa":
            raise ErroAbajur(f"A lâmpada recusou o valor usado para {operacao}.")
        if erro:
            raise ErroAbajur(f"A lâmpada não confirmou a operação de {operacao}.")

        resposta_dict = resposta
        if exigir_dps:
            dps = resposta_dict.get("dps")
            if not isinstance(dps, dict) or not dps:
                raise ErroAbajur("A lâmpada respondeu sem informar o estado dos controles.")
        return resposta_dict

    def _traduzir_excecao(self, operacao: str, exc: Exception) -> ErroAbajur:
        if isinstance(exc, ErroAbajur):
            return exc
        texto = str(exc).lower()
        if isinstance(exc, (TimeoutError, ConnectionError, OSError)) or any(
            trecho in texto for trecho in ("timeout", "unable to connect", "unreachable")
        ):
            return ErroAbajur(
                "Não consegui alcançar a lâmpada na rede local. Confira se ela está ligada."
            )
        if any(trecho in texto for trecho in ("key", "decrypt", "gcm", "version")):
            return ErroAbajur(
                "Não consegui autenticar na lâmpada. Confira a chave local e a versão Tuya."
            )
        return ErroAbajur(f"Falha no controle Tuya ao {operacao}.")

    def _chamar(
        self,
        operacao: str,
        funcao: Callable[..., object],
        *argumentos: object,
        exigir_dps: bool = False,
        **opcoes: object,
    ) -> dict[str, Any]:
        try:
            resposta = funcao(*argumentos, **opcoes)
        except Exception as exc:
            raise self._traduzir_excecao(operacao, exc) from exc
        return self._validar_resposta(
            resposta,
            operacao,
            exigir_dps=exigir_dps,
        )

    def _consultar_estado(self, *, atualizar: bool) -> dict[str, Any]:
        dispositivo = self._obter_dispositivo()
        if atualizar or self._estado_inicial is None:
            resposta = self._chamar(
                "consultar o estado",
                dispositivo.status,
                exigir_dps=True,
            )
            dps = resposta["dps"]
            if not all(indice in dps for indice in ("20", "21")):
                raise ErroAbajur(
                    "A lâmpada respondeu, mas não usa o mapa de controles Tuya Type B esperado."
                )
            # status() já faz esta autodetecção no TinyTuya. O fallback ajuda
            # implementações compatíveis que entregam os mesmos DPS.
            if not getattr(dispositivo, "bulb_configured", True):
                configurar = getattr(dispositivo, "set_bulb_type", None)
                if callable(configurar):
                    configurar("B")
            self._estado_inicial = resposta
        return self._estado_inicial

    def status(self) -> dict[str, Any]:
        """Lê o estado atual sem modificar nenhum DP da lâmpada."""
        with self._lock:
            return self._consultar_estado(atualizar=True)

    def _executar_apos_status(
        self,
        operacao: str,
        nome_metodo: str,
        *argumentos: object,
        **opcoes: object,
    ) -> dict[str, Any]:
        with self._lock:
            self._consultar_estado(atualizar=False)
            metodo = getattr(self._obter_dispositivo(), nome_metodo)
            resposta = self._chamar(operacao, metodo, *argumentos, **opcoes)
            self._estado_inicial = resposta if "dps" in resposta else None
            return resposta

    def _parar_ritmo_ativo(self) -> "AnimacaoLuz | None":
        ritmo = self._ritmo_navegador
        if ritmo is not None:
            try:
                ritmo.parar()
            finally:
                self._ritmo_navegador = None
                with self._lock:
                    self._definir_conexao_persistente(False)
        return ritmo

    def _animacao_finalizada(self, animacao: "AnimacaoLuz") -> None:
        """Fecha o socket se uma animação encerrar sozinha ou por falha."""
        if self._ritmo_navegador is animacao:
            self._ritmo_navegador = None
            with self._lock:
                self._definir_conexao_persistente(False)

    def preparar_animacao_externa(
        self,
        animacao: AnimacaoLuz,
        *,
        preservar_perfil: bool = False,
    ) -> int:
        """Reserva a lâmpada e devolve o brilho que deverá ser restaurado."""
        self._parar_ritmo_ativo()
        with self._lock:
            estado = self._consultar_estado(atualizar=True)
            brilho_inicial = 100
            if preservar_perfil:
                brilho_inicial = self._brilho_percentual_do_estado(estado)
                self._configurar_perfil_ritmo(estado, None)
            self._definir_conexao_persistente(True)
        self._ritmo_navegador = animacao
        return brilho_inicial

    def cor_perfil_animacao(self) -> tuple[int, int, int]:
        """Aproxima em RGB a cor/temperatura congelada no preflight."""
        with self._lock:
            if self._modo_ritmo == "colour":
                rgb = colorsys.hsv_to_rgb(
                    self._matiz_ritmo,
                    self._saturacao_ritmo,
                    1.0,
                )
                return tuple(round(canal * 255) for canal in rgb)  # type: ignore[return-value]
            proporcao = max(0.0, min(1.0, self._temperatura_ritmo / 100.0))
            quente = (255, 147, 41)
            fria = (180, 220, 255)
            return tuple(
                round(inicio + (fim - inicio) * proporcao)
                for inicio, fim in zip(quente, fria)
            )  # type: ignore[return-value]

    def liberar_animacao_externa(self, animacao: AnimacaoLuz) -> None:
        """Libera a reserva apenas se ela ainda pertencer ao mesmo modo."""
        if self._ritmo_navegador is animacao:
            self._ritmo_navegador = None
            with self._lock:
                self._definir_conexao_persistente(False)

    def enviar_rgb_animacao(self, vermelho: int, verde: int, azul: int) -> None:
        """Envia um quadro RGB já cadenciado por uma animação externa."""
        canais = tuple(
            self._percentual(valor, "Cada canal RGB")
            for valor in (vermelho, verde, azul)
        )
        if not all(0 <= canal <= 255 for canal in canais):
            raise ErroAbajur("Cada valor RGB deve ficar entre 0 e 255.")
        matiz, saturacao, valor = colorsys.rgb_to_hsv(
            *(canal / 255.0 for canal in canais)
        )
        try:
            self._enviar_hsv_ritmo(matiz, saturacao, valor)
        except Exception as primeira_falha:
            self._registrar_falha_ritmo("quadro externo perdido", primeira_falha)
            self._reconectar_animacao()
            self._enviar_hsv_ritmo(matiz, saturacao, valor)

    def restaurar_perfil_animacao(self, percentual: int) -> None:
        """Restaura o modo white/colour congelado antes da animação externa."""
        percentual = self._percentual(percentual, "O brilho restaurado")
        if not 1 <= percentual <= 100:
            raise ErroAbajur("O brilho restaurado deve ficar entre 1 e 100 por cento.")
        self._enviar_brilho_ritmo(percentual)

    def enviar_brilho_animacao(self, percentual: int) -> None:
        """Altera só o brilho, preservando cor ou temperatura do preflight."""
        percentual = self._percentual(percentual, "O brilho da animação")
        if not 1 <= percentual <= 100:
            raise ErroAbajur("O brilho da animação deve ficar entre 1 e 100 por cento.")
        self._enviar_brilho_ritmo(percentual)

    def energia(self, ligar: bool) -> None:
        self._parar_ritmo_ativo()
        self._executar_apos_status(
            "ligar a lâmpada" if ligar else "desligar a lâmpada",
            "turn_on" if ligar else "turn_off",
        )

    def cor(self, nome: str) -> None:
        self.rgb(*resolver_cor(nome))

    def temperatura(self, nome: str) -> None:
        self._parar_ritmo_ativo()
        temperatura = self._TEMPERATURAS.get(nome.lower().strip())
        if temperatura is None:
            raise ErroAbajur(f"A temperatura {nome} ainda não está configurada.")
        self._executar_apos_status(
            "ajustar a temperatura",
            "set_colourtemp_percentage",
            temperatura,
        )

    @staticmethod
    def _percentual(valor: object, nome: str) -> int:
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise ErroAbajur(f"{nome} precisa ser um número inteiro.")
        inteiro = int(valor)
        if inteiro != valor:
            raise ErroAbajur(f"{nome} precisa ser um número inteiro.")
        return inteiro

    def brilho(self, percentual: int) -> None:
        self._parar_ritmo_ativo()
        percentual = self._percentual(percentual, "O brilho")
        if not 1 <= percentual <= 100:
            raise ErroAbajur("O brilho deve ficar entre 1 e 100 por cento.")
        self._executar_apos_status(
            "ajustar o brilho",
            "set_brightness_percentage",
            percentual,
        )

    def ajustar_brilho(self, delta: int) -> int:
        """Soma pontos percentuais ao brilho atual e devolve o valor aplicado."""
        self._parar_ritmo_ativo()
        delta = self._percentual(delta, "A alteração de brilho")
        if not -100 <= delta <= 100:
            raise ErroAbajur("A alteração de brilho deve ficar entre -100 e 100 por cento.")
        with self._lock:
            estado = self._consultar_estado(atualizar=True)
            bruto = estado["dps"].get(self._DPS_TIPO_B["brilho"])
            if isinstance(bruto, bool) or not isinstance(bruto, (int, float)):
                raise ErroAbajur("A lâmpada não informou o brilho atual.")
            maximo = getattr(self._obter_dispositivo(), "dpset", {}).get("value_max", 1000)
            if not isinstance(maximo, (int, float)) or maximo <= 0:
                maximo = 1000
            atual = round(float(bruto) * 100 / float(maximo))
            novo = max(1, min(100, atual + delta))
            resposta = self._chamar(
                "ajustar o brilho",
                self._obter_dispositivo().set_brightness_percentage,
                novo,
            )
            self._estado_inicial = resposta if "dps" in resposta else None
            return novo

    def rgb(self, vermelho: int, verde: int, azul: int) -> None:
        self._parar_ritmo_ativo()
        canais = tuple(
            self._percentual(valor, "Cada canal RGB")
            for valor in (vermelho, verde, azul)
        )
        if not all(0 <= canal <= 255 for canal in canais):
            raise ErroAbajur("Cada valor RGB deve ficar entre 0 e 255.")
        self._executar_apos_status(
            "ajustar a cor",
            "set_colour",
            *canais,
        )

    def iniciar_ritmo_navegador(
        self,
        cor_fixa: tuple[int, int, int] | None = None,
    ) -> None:
        _validar_dependencias_ritmo()
        if cor_fixa is not None:
            canais = tuple(
                self._percentual(valor, "Cada canal RGB") for valor in cor_fixa
            )
            if len(canais) != 3 or not all(0 <= canal <= 255 for canal in canais):
                raise ErroAbajur("Cada valor RGB deve ficar entre 0 e 255.")
            cor_fixa = canais  # type: ignore[assignment]
        self._parar_ritmo_ativo()
        with self._lock:
            estado = self._consultar_estado(atualizar=True)
            brilho_base = self._brilho_percentual_do_estado(estado)
            self._configurar_perfil_ritmo(estado, cor_fixa)
            self._definir_conexao_persistente(True)
        ritmo = _RitmoTuya(
            self,
            cor_fixa=cor_fixa,
            brilho_base=brilho_base,
        )
        self._ritmo_navegador = ritmo
        try:
            ritmo.iniciar()
        except ErroAbajur:
            self._ritmo_navegador = None
            with self._lock:
                self._definir_conexao_persistente(False)
            raise

    def definir_intensidade_ritmo(self, percentual: int) -> int:
        percentual = self._percentual(percentual, "A intensidade do pulso")
        if not 1 <= percentual <= 100:
            raise ErroAbajur("A intensidade do pulso deve ficar entre 1 e 100 por cento.")
        self._intensidade_ritmo = percentual
        return percentual

    def ajustar_intensidade_ritmo(self, variacao: int) -> int:
        variacao = self._percentual(variacao, "O ajuste da intensidade do pulso")
        if variacao == 0 or not -99 <= variacao <= 99:
            raise ErroAbajur("O ajuste da intensidade deve ficar entre 1 e 99 por cento.")
        self._intensidade_ritmo = max(1, min(100, self._intensidade_ritmo + variacao))
        return self._intensidade_ritmo

    def iniciar_modo_tocha(self) -> None:
        self._parar_ritmo_ativo()
        with self._lock:
            self._consultar_estado(atualizar=True)
            self._definir_conexao_persistente(True)
        animacao = _AnimacaoTochaTuya(self)
        self._ritmo_navegador = animacao
        try:
            animacao.iniciar()
        except ErroAbajur:
            if not animacao.ativo:
                self._ritmo_navegador = None
                with self._lock:
                    self._definir_conexao_persistente(False)
            raise

    def parar_modo_tocha(self) -> None:
        self.parar_ritmo_navegador()

    def parar_ritmo_navegador(self) -> None:
        ritmo = self._parar_ritmo_ativo()
        if ritmo is not None and ritmo.erro:
            raise ErroAbajur(ritmo.erro)

    def _enviar_hsv_ritmo(self, matiz: float, saturacao: float, valor: float) -> None:
        with self._lock:
            resposta = self._chamar(
                "animar a lâmpada",
                self._obter_dispositivo().set_hsv,
                max(0.0, min(1.0, matiz)),
                max(0.0, min(1.0, saturacao)),
                max(0.01, min(1.0, valor)),
            )
            self._estado_inicial = resposta if "dps" in resposta else None

    def _brilho_percentual_do_estado(self, estado: dict[str, Any]) -> int:
        dps = estado.get("dps", {})
        if not isinstance(dps, dict):
            raise ErroAbajur("A lâmpada não informou o brilho atual.")
        if str(dps.get(self._DPS_TIPO_B["modo"], "")).casefold() == "colour":
            cor = dps.get(self._DPS_TIPO_B["cor"])
            if isinstance(cor, str) and re.fullmatch(r"[0-9a-fA-F]{12}", cor):
                return max(1, min(100, round(int(cor[-4:], 16) * 100 / 1000)))
        bruto = dps.get(self._DPS_TIPO_B["brilho"])
        if isinstance(bruto, bool) or not isinstance(bruto, (int, float)):
            raise ErroAbajur("A lâmpada não informou o brilho atual.")
        maximo = getattr(self._obter_dispositivo(), "dpset", {}).get("value_max", 1000)
        if not isinstance(maximo, (int, float)) or maximo <= 0:
            maximo = 1000
        return max(1, min(100, round(float(bruto) * 100 / float(maximo))))

    def _configurar_perfil_ritmo(
        self,
        estado: dict[str, Any],
        cor_fixa: tuple[int, int, int] | None,
    ) -> None:
        """Congela white/colour no início para o firmware não alternar modos."""
        if cor_fixa is not None:
            matiz, saturacao, _valor = colorsys.rgb_to_hsv(
                *(canal / 255.0 for canal in cor_fixa)
            )
            self._modo_ritmo = "colour"
            self._matiz_ritmo = matiz
            self._saturacao_ritmo = saturacao
            return

        dps = estado.get("dps", {})
        if not isinstance(dps, dict):
            raise ErroAbajur("A lâmpada não informou o modo atual.")
        modo = str(dps.get(self._DPS_TIPO_B["modo"], "white")).casefold()
        maximo = getattr(self._obter_dispositivo(), "dpset", {}).get("value_max", 1000)
        if not isinstance(maximo, (int, float)) or maximo <= 0:
            maximo = 1000
        if modo != "colour":
            temperatura = dps.get(self._DPS_TIPO_B["temperatura"], maximo / 2)
            if isinstance(temperatura, bool) or not isinstance(temperatura, (int, float)):
                temperatura = maximo / 2
            self._modo_ritmo = "white"
            self._temperatura_ritmo = max(
                0, min(100, round(float(temperatura) * 100 / float(maximo)))
            )
            return

        cor = dps.get(self._DPS_TIPO_B["cor"])
        if not isinstance(cor, str) or not re.fullmatch(r"[0-9a-fA-F]{12}", cor):
            raise ErroAbajur("A lâmpada não informou a cor atual para o modo ritmo.")
        self._modo_ritmo = "colour"
        self._matiz_ritmo = max(0.0, min(1.0, int(cor[:4], 16) / 360.0))
        self._saturacao_ritmo = max(0.0, min(1.0, int(cor[4:8], 16) / 1000.0))

    def _enviar_brilho_ritmo(self, percentual: int) -> None:
        with self._lock:
            brilho = max(1, min(100, round(percentual)))
            dispositivo = self._obter_dispositivo()
            if self._modo_ritmo == "white":
                resposta = self._chamar(
                    "animar o brilho branco da lâmpada",
                    dispositivo.set_white_percentage,
                    brilho,
                    self._temperatura_ritmo,
                )
            else:
                resposta = self._chamar(
                    "animar o brilho colorido da lâmpada",
                    dispositivo.set_hsv,
                    self._matiz_ritmo,
                    self._saturacao_ritmo,
                    brilho / 100.0,
                )
            self._estado_inicial = resposta if "dps" in resposta else None

    @property
    def _arquivo_cores(self) -> Path:
        return self._pasta_dados / ARQUIVO_CORES

    def _carregar_cores(self) -> dict[str, str]:
        try:
            dados = json.loads(self._arquivo_cores.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ErroAbajur("Não consegui ler as cores salvas.") from exc
        if not isinstance(dados, dict):
            raise ErroAbajur("O arquivo de cores salvas está inválido.")
        return {str(nome): str(valor) for nome, valor in dados.items()}

    def salvar_cor(self, nome: str, especificacao: str) -> str:
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
            raise ErroAbajur("Não consegui salvar a cor.") from exc
        return hexadecimal

    def salvar_cor_atual(self, nome: str) -> str:
        with self._lock:
            self._consultar_estado(atualizar=True)
            dispositivo = self._obter_dispositivo()
            try:
                estado = dispositivo.state()
                rgb = dispositivo.colour_rgb(state=estado)
            except Exception as exc:
                raise self._traduzir_excecao("ler a cor atual", exc) from exc
        if (
            not isinstance(rgb, (tuple, list))
            or len(rgb) != 3
            or not all(isinstance(canal, (int, float)) for canal in rgb)
        ):
            raise ErroAbajur("A lâmpada não informou uma cor RGB válida.")
        canais = tuple(max(0, min(255, round(float(canal)))) for canal in rgb)
        return self._salvar_rgb(nome, *canais)

    def usar_cor_salva(self, nome: str) -> None:
        nome = _nome_preset(nome)
        hexadecimal = self._carregar_cores().get(nome)
        if hexadecimal is None:
            raise ErroAbajur(f"Não encontrei uma cor salva chamada {nome}.")
        self.rgb(*resolver_cor(hexadecimal))


class _RitmoTuya:
    """Pulsa brilho pela LAN usando principalmente bumbo e baixo da música."""

    _QUADROS_POR_SEGUNDO = 25
    _INTERVALO = 1 / _QUADROS_POR_SEGUNDO
    _INTERVALO_RECUPERACAO = 0.10
    _MAX_FALHAS_CONSECUTIVAS = 6
    _TIMEOUT_INICIO = 5.0

    def __init__(
        self,
        controle: ControleAbajurTuya,
        cor_fixa: tuple[int, int, int] | None,
        brilho_base: int = 100,
    ) -> None:
        self.controle = controle
        self.cor_fixa = cor_fixa
        self.brilho_base = max(1, min(100, round(brilho_base)))
        self._parar = threading.Event()
        self._pronto = threading.Event()
        self._thread: threading.Thread | None = None
        self.erro: str | None = None
        self.quadros_enviados = 0
        self._falhas_consecutivas = 0
        self._sucessos_apos_falha = 0
        self._intervalo_atual = self._INTERVALO

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._thread = threading.Thread(
            target=self._executar,
            name="Nebu-Ritmo-Tuya",
            daemon=True,
        )
        self._thread.start()
        if not self._pronto.wait(self._TIMEOUT_INICIO):
            self._parar.set()
            raise ErroAbajur("O modo ritmo não terminou a preparação a tempo.")
        if self.erro:
            raise ErroAbajur(self.erro)
        if not self.ativo:
            raise ErroAbajur("O modo ritmo foi encerrado durante a inicialização.")

    def parar(self) -> None:
        self._parar.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=4)

    def _registrar_falha(self, etapa: str, exc: Exception) -> None:
        registrar = getattr(self.controle, "_registrar_falha_ritmo", None)
        if callable(registrar):
            registrar(etapa, exc)

    def _enviar_quadro_resiliente(
        self,
        funcao: Callable[..., None],
        *argumentos: object,
    ) -> bool:
        """Recupera falhas isoladas e evita encerrar uma animação saudável."""
        try:
            funcao(*argumentos)
        except Exception as primeira_falha:
            self._registrar_falha("quadro perdido", primeira_falha)
            try:
                reconectar = getattr(self.controle, "_reconectar_animacao")
                reconectar()
                funcao(*argumentos)
            except Exception as segunda_falha:
                self._falhas_consecutivas += 1
                self._sucessos_apos_falha = 0
                self._intervalo_atual = self._INTERVALO_RECUPERACAO
                self._registrar_falha("reconexão sem resposta", segunda_falha)
                if self._falhas_consecutivas >= self._MAX_FALHAS_CONSECUTIVAS:
                    raise segunda_falha
                return False

        self._falhas_consecutivas = 0
        if self._intervalo_atual > self._INTERVALO:
            self._sucessos_apos_falha += 1
            if self._sucessos_apos_falha >= 20:
                self._intervalo_atual = self._INTERVALO
                self._sucessos_apos_falha = 0
        return True

    def _executar(self) -> None:
        com_inicializado = False
        brilho_inicial_aplicado = False
        medidor_graves: Any | None = None
        matiz_fixa = saturacao_fixa = brilho_base_rgb = 1.0
        brilho_base = self.brilho_base
        try:
            import comtypes

            comtypes.CoInitialize()
            com_inicializado = True
            from ritmo_navegador import (
                atividade_indica_musica,
                DetectorRitmoMusical,
                MedidorGravesLoopback,
                MedidorNavegador,
                titulo_navegador_indica_musica,
            )

            medidor = MedidorNavegador()
            # Valida a enumeração das sessões Core Audio antes de confirmar o
            # modo ou alterar a lâmpada. Ausência momentânea de som retorna zero
            # e mantém o modo aguardando; erro do medidor falha de forma clara.
            pico_inicial = medidor.pico()
            detector = DetectorRitmoMusical(
                amostras_por_segundo=self._QUADROS_POR_SEGUNDO,
                segundos=6,
            )
            detector.adicionar(pico_inicial)
            try:
                medidor_graves = MedidorGravesLoopback(self._QUADROS_POR_SEGUNDO)
                pico_pulso_inicial = medidor_graves.pico()
            except Exception:
                # Hardware/driver sem loopback continua usando o pico do navegador.
                medidor_graves = None
                pico_pulso_inicial = pico_inicial
            ultima_tentativa_graves = time.monotonic()
            janela_pulso: deque[float] = deque(
                [pico_pulso_inicial],
                maxlen=self._QUADROS_POR_SEGUNDO * 6,
            )
            nivel_suave = 0.5
            estava_musica = False
            ultima_leitura_titulo = 0.0
            indicacao_titulo: bool | None = None
            if self.cor_fixa is not None:
                vermelho, verde, azul = self.cor_fixa
                matiz_fixa, saturacao_fixa, brilho_base_rgb = colorsys.rgb_to_hsv(
                    vermelho / 255,
                    verde / 255,
                    azul / 255,
                )
                brilho_base = max(1, round(brilho_base_rgb * 100))
                # Confirma o caminho PC -> TinyTuya -> lâmpada antes de a Nebu
                # anunciar que o pulso em cor fixa foi ativado.
                self.controle._enviar_hsv_ritmo(
                    matiz_fixa,
                    saturacao_fixa,
                    max(0.01, brilho_base_rgb),
                )
            # Confirma também a rota de brilho usada por todos os quadros sem
            # mudar matiz, saturação ou temperatura da lâmpada.
            self.controle._enviar_brilho_ritmo(brilho_base)
            brilho_inicial_aplicado = True
            self._pronto.set()

            proximo_quadro = time.monotonic()
            while not self._parar.is_set():
                proximo_quadro += self._intervalo_atual
                if self._parar.wait(max(0.0, proximo_quadro - time.monotonic())):
                    break
                agora = time.monotonic()
                try:
                    pico_atividade = medidor.pico()
                except Exception as exc:
                    # A sessão WASAPI pode ser recriada quando uma aba muda de
                    # faixa ou o dispositivo de saída troca. Um quadro perdido
                    # não deve encerrar o modo inteiro.
                    self._registrar_falha("medidor do navegador reiniciado", exc)
                    medidor = MedidorNavegador()
                    continue
                detector.adicionar(pico_atividade)
                if medidor_graves is not None:
                    try:
                        pico = medidor_graves.pico()
                    except Exception as exc:
                        self._registrar_falha("medidor de graves reiniciado", exc)
                        try:
                            medidor_graves.fechar()
                        except Exception:
                            pass
                        medidor_graves = None
                        ultima_tentativa_graves = agora
                        pico = pico_atividade
                else:
                    pico = pico_atividade
                    if agora - ultima_tentativa_graves >= 10.0:
                        ultima_tentativa_graves = agora
                        try:
                            medidor_graves = MedidorGravesLoopback(
                                self._QUADROS_POR_SEGUNDO
                            )
                            pico = medidor_graves.pico()
                        except Exception as exc:
                            medidor_graves = None
                            self._registrar_falha(
                                "medidor de graves ainda indisponível",
                                exc,
                            )
                janela_pulso.append(pico)
                if agora - ultima_leitura_titulo >= 2:
                    try:
                        indicacao_titulo = titulo_navegador_indica_musica()
                    except Exception as exc:
                        indicacao_titulo = None
                        self._registrar_falha("leitura do título reiniciada", exc)
                    ultima_leitura_titulo = agora
                musica = atividade_indica_musica(indicacao_titulo, detector)
                if not musica or pico <= LIMIAR_PICO_RITMO:
                    if estava_musica:
                        if self._enviar_quadro_resiliente(
                            self.controle._enviar_brilho_ritmo,
                            brilho_base,
                        ):
                            estava_musica = False
                    continue

                janela = list(janela_pulso)
                minimo = min(janela, default=0.0)
                maximo = max(janela, default=1.0)
                normalizado = (pico - minimo) / max(
                    FAIXA_MINIMA_RITMO, maximo - minimo
                )
                nivel_suave = calcular_nivel_pulso(
                    normalizado,
                    nivel_suave,
                    getattr(
                        self.controle,
                        "_intensidade_ritmo",
                        INTENSIDADE_RITMO_PADRAO,
                    ),
                )
                if not self._enviar_quadro_resiliente(
                    self.controle._enviar_brilho_ritmo,
                    max(1, round(brilho_base * nivel_suave)),
                ):
                    continue
                estava_musica = True
                self.quadros_enviados += 1
                # Se a rede atrasar mais de um quadro, retoma a partir de agora
                # sem disparar uma rajada de comandos atrasados no firmware.
                if time.monotonic() - proximo_quadro > self._intervalo_atual:
                    proximo_quadro = time.monotonic()
        except Exception as exc:
            # Não propagamos de uma thread daemon e não incluímos detalhes que
            # possam carregar credenciais vindas da biblioteca.
            self._registrar_falha("animação encerrada", exc)
            self.erro = "Falha na animação local da lâmpada."
            self._pronto.set()
        finally:
            if medidor_graves is not None:
                try:
                    medidor_graves.fechar()
                except Exception:
                    pass
            if brilho_inicial_aplicado:
                try:
                    # Um pulso pode terminar no vale da onda; restaura somente
                    # o brilho sem alterar cor ou temperatura.
                    self.controle._enviar_brilho_ritmo(brilho_base)
                except Exception:
                    if self.erro is None:
                        self.erro = "Falha ao restaurar o brilho após o modo ritmo."
            if com_inicializado:
                try:
                    import comtypes

                    comtypes.CoUninitialize()
                except Exception:
                    pass
            finalizar = getattr(self.controle, "_animacao_finalizada", None)
            if callable(finalizar):
                finalizar(self)


class _AnimacaoTochaTuya:
    """Varia tons de laranja e brilho pela LAN, sem depender do navegador."""

    _INTERVALO = 0.28
    _TIMEOUT_INICIO = 6.0

    def __init__(self, controle: ControleAbajurTuya) -> None:
        self.controle = controle
        self._parar = threading.Event()
        self._pronto = threading.Event()
        self._thread: threading.Thread | None = None
        self.erro: str | None = None
        self.quadros_enviados = 0

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self) -> None:
        if self.ativo:
            return
        self._thread = threading.Thread(
            target=self._executar,
            name="Nebu-Tocha-Tuya",
            daemon=True,
        )
        self._thread.start()
        if not self._pronto.wait(self._TIMEOUT_INICIO):
            self._parar.set()
            if self._thread:
                self._thread.join(timeout=4)
            raise ErroAbajur("O modo tocha não terminou a preparação a tempo.")
        if self.erro:
            raise ErroAbajur(self.erro)
        if not self.ativo:
            raise ErroAbajur("O modo tocha foi encerrado durante a inicialização.")

    def parar(self) -> None:
        self._parar.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=4)
        if self.ativo:
            raise ErroAbajur("A animação de tocha ainda está sendo encerrada.")

    def _executar(self) -> None:
        try:
            from animacao_tocha import GeradorTocha

            gerador = GeradorTocha()
            primeiro = gerador.proximo()
            self.controle._enviar_hsv_ritmo(
                primeiro.matiz, primeiro.saturacao, primeiro.brilho
            )
            self.quadros_enviados += 1
            self._pronto.set()
            while not self._parar.wait(self._INTERVALO):
                quadro = gerador.proximo()
                self.controle._enviar_hsv_ritmo(
                    quadro.matiz, quadro.saturacao, quadro.brilho
                )
                self.quadros_enviados += 1
        except Exception:
            self.erro = "Falha na animação de tocha da lâmpada."
            self._pronto.set()
        finally:
            finalizar = getattr(self.controle, "_animacao_finalizada", None)
            if callable(finalizar):
                finalizar(self)
