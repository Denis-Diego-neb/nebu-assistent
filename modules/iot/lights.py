"""Execução dos comandos do abajur, independente da interface da Nebula.

Recebe pedidos interpretados e uma fábrica de controle. O host fica responsável
por exibir mensagens e decidir quais efeitos dos outros dispositivos interromper.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from abajur_wifi import ComandoAbajur, ErroAbajur


def pedido_da_tool(nome: str, argumento: str) -> ComandoAbajur | None:
    """Traduz argumentos já validados diretamente para o driver, sem analisar frases."""
    fixos = {
        "abajur_ligar": ("energia", True),
        "abajur_desligar": ("energia", False),
        "abajur_musica_iniciar": ("musica_pc", None),
        "abajur_musica_parar": ("musica_parar", None),
        "abajur_musica_intensidade_aumentar": ("intensidade_ritmo_relativa", 20),
        "abajur_musica_intensidade_diminuir": ("intensidade_ritmo_relativa", -20),
        "abajur_tocha_iniciar": ("tocha_iniciar", None),
        "abajur_tocha_parar": ("tocha_parar", None),
    }
    if nome in fixos:
        return ComandoAbajur(*fixos[nome])
    if nome == "abajur_cor":
        return ComandoAbajur("cor", argumento)
    if nome == "abajur_temperatura":
        return ComandoAbajur("temperatura", argumento)
    numericos = {
        "abajur_brilho": ("brilho", 1),
        "abajur_diminuir_brilho": ("brilho_relativo", -1),
        "abajur_aumentar_brilho": ("brilho_relativo", 1),
        "abajur_musica_intensidade": ("intensidade_ritmo", 1),
    }
    if nome in numericos:
        acao, sinal = numericos[nome]
        return ComandoAbajur(acao, sinal * int(argumento))
    return None


class ControleAbajur(Protocol):
    def energia(self, ligar: bool) -> None: ...
    def cor(self, nome: str) -> None: ...
    def temperatura(self, nome: str) -> None: ...
    def brilho(self, percentual: int) -> None: ...
    def ajustar_brilho(self, variacao: int) -> int: ...
    def definir_intensidade_ritmo(self, percentual: int) -> int: ...
    def ajustar_intensidade_ritmo(self, variacao: int) -> int: ...
    def iniciar_ritmo_navegador(self, cor_fixa: tuple[int, int, int] | None = None) -> None: ...
    def parar_ritmo_navegador(self) -> None: ...
    def iniciar_modo_tocha(self) -> None: ...
    def parar_modo_tocha(self) -> None: ...
    def salvar_cor(self, nome: str, especificacao: str) -> str: ...
    def salvar_cor_atual(self, nome: str) -> str: ...
    def usar_cor_salva(self, nome: str) -> None: ...
    def rgb(self, vermelho: int, verde: int, azul: int) -> None: ...


@dataclass(frozen=True)
class ResultadoAbajur:
    mensagem: str | None = None
    falhou: bool = False


def executar_pedidos_abajur(
    pedidos: Sequence[ComandoAbajur],
    obter_controle: Callable[[], ControleAbajur],
) -> ResultadoAbajur:
    """Executa em ordem e informa também os ajustes anteriores a uma falha.

    A fábrica só é chamada quando há pedidos; falhas de conexão usam o mesmo
    resultado das falhas de execução. O chamador decide como exibir e repetir.
    """
    if not pedidos:
        return ResultadoAbajur()
    confirmacoes: list[str] = []
    try:
        controle = obter_controle()
        for pedido in pedidos:
            if pedido.acao == "energia":
                ligar = bool(pedido.valor)
                controle.energia(ligar)
                confirmacoes.append("Abajur ligado" if ligar else "Abajur desligado")
            elif pedido.acao == "cor":
                controle.cor(str(pedido.valor))
                confirmacoes.append(f"cor {pedido.valor}")
            elif pedido.acao == "temperatura":
                controle.temperatura(str(pedido.valor))
                confirmacoes.append(f"luz {pedido.valor}")
            elif pedido.acao == "brilho":
                percentual = int(pedido.valor)  # type: ignore[arg-type]
                controle.brilho(percentual)
                confirmacoes.append(f"brilho em {percentual} por cento")
            elif pedido.acao == "brilho_relativo":
                variacao = int(pedido.valor)  # type: ignore[arg-type]
                percentual = controle.ajustar_brilho(variacao)
                verbo = "reduzido" if variacao < 0 else "aumentado"
                confirmacoes.append(
                    f"brilho {verbo} em {abs(variacao)} por cento, agora em {percentual} por cento"
                )
            elif pedido.acao == "intensidade_ritmo":
                percentual = controle.definir_intensidade_ritmo(
                    int(pedido.valor)  # type: ignore[arg-type]
                )
                confirmacoes.append(
                    f"intensidade do pulso em {percentual} por cento"
                )
            elif pedido.acao == "intensidade_ritmo_relativa":
                variacao = int(pedido.valor)  # type: ignore[arg-type]
                percentual = controle.ajustar_intensidade_ritmo(
                    variacao
                )
                confirmacoes.append(
                    f"intensidade do pulso agora em {percentual} por cento"
                )
            elif pedido.acao == "musica_pc":
                cor_fixa = pedido.valor if isinstance(pedido.valor, tuple) else None
                controle.iniciar_ritmo_navegador(cor_fixa)
                confirmacoes.append(
                    "pulso em cor fixa ativado; deixe a música tocando no navegador"
                    if cor_fixa else
                    "ritmo ativado e aguardando áudio do navegador; Discord e outros aplicativos ficam de fora"
                )
            elif pedido.acao == "musica_parar":
                controle.parar_ritmo_navegador()
                confirmacoes.append("animação musical do abajur desativada")
            elif pedido.acao == "tocha_iniciar":
                controle.iniciar_modo_tocha()
                confirmacoes.append("modo tocha ativado")
            elif pedido.acao == "tocha_parar":
                controle.parar_modo_tocha()
                confirmacoes.append("modo tocha desativado")
            elif pedido.acao == "salvar_cor":
                especificacao, nome = pedido.valor  # type: ignore[misc]
                hexadecimal = controle.salvar_cor(nome, especificacao)
                confirmacoes.append(f"cor {hexadecimal} salva como {nome}")
            elif pedido.acao == "salvar_cor_atual":
                nome = str(pedido.valor)
                hexadecimal = controle.salvar_cor_atual(nome)
                confirmacoes.append(f"cor atual {hexadecimal} salva como {nome}")
            elif pedido.acao == "usar_cor_salva":
                nome = str(pedido.valor)
                controle.usar_cor_salva(nome)
                confirmacoes.append(f"cor salva {nome} aplicada")
            elif pedido.acao == "rgb":
                vermelho, verde, azul = pedido.valor  # type: ignore[misc]
                controle.rgb(vermelho, verde, azul)
                confirmacoes.append(f"cor RGB {vermelho}, {verde}, {azul}")
    except (ErroAbajur, OSError) as exc:
        prefixo = f"Consegui ajustar {', '.join(confirmacoes)}. " if confirmacoes else ""
        return ResultadoAbajur(
            mensagem=f"{prefixo}Não consegui concluir o controle do abajur. {exc}",
            falhou=True,
        )
    mensagem = None
    if len(confirmacoes) == 1 and confirmacoes[0].startswith("Abajur"):
        mensagem = confirmacoes[0] + "."
    elif confirmacoes:
        mensagem = "Ajustei " + " e ".join(confirmacoes) + "."
    return ResultadoAbajur(mensagem=mensagem)
