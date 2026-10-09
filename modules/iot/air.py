"""Pedidos falados para o ar-condicionado, independentes da interface da Nebula.

O módulo só traduz a frase para as ações do controle do Smart IR (`power`,
`temperature`, `mode` e `fan`) e monta a resposta falada. A transmissão
infravermelha continua no driver, e o host decide quando consultar o módulo.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Protocol, Sequence


@dataclass(frozen=True)
class PedidoAr:
    """Ação do driver ou ajuste relativo (`temperature_delta`, `fan_delta`)."""

    acao: str
    valor: object = None


class ControleAr(Protocol):
    def estado(self) -> dict[str, object]: ...
    def executar(self, acao: str, valor: object) -> dict[str, object]: ...


@dataclass(frozen=True)
class ResultadoAr:
    mensagem: str
    falhou: bool = False


_ALVO = re.compile(r"\bar(?:[- ]?condicionado)?\b")
# Frases que também citam a luz continuam com o parser do abajur.
_OUTROS_ALVOS = re.compile(r"\b(?:abajur|lampadas?|luz|luzes)\b")
# Pesquisas, notas e ensino de vocabulário apenas mencionam o ar.
_OUTROS_PEDIDOS = re.compile(
    r"^(?:pesquis|procur|busqu|busc|toqu|toca|escrev|anot|digit|abr[ae]\b|abrir|"
    r"aprend|lembr|memoriz|corrij|corrig)"
    r"|\b(?:youtube|google|significa|significado)\b"
    r"|\bcomo (?:eu )?(?:ligo|ligar|desligo|desligar|uso|usar|configuro|configurar|funciona)\b"
)
# O desligamento programado existe só no hub do notebook; um horário nunca
# pode virar temperatura nem um desligamento imediato.
_AGENDAMENTO = re.compile(
    r"\b(?:minutos?|min|horas?|segundos?|daqui|amanha|timer|temporizador)\b"
    r"|\bas \d|\b\d{1,2}h\d{0,2}\b|\b\d{1,2}:\d{2}\b"
)
_DESLIGAR = re.compile(
    r"\b(?:desligue|desliga|desligar|apague|apaga|apagar|desative|desativa|desativar)\b"
    r"|\b(?:deixe|deixa|mantenha|mantem) o ar(?:[- ]?condicionado)? desligado\b"
)
_LIGAR = re.compile(
    r"\b(?:ligue|liga|ligar|acione|aciona|acionar|ative|ativa|ativar)\b"
    r"|\b(?:deixe|deixa|mantenha|mantem) o ar(?:[- ]?condicionado)? ligado\b"
)
_SUBIR = re.compile(
    r"\b(?:aumente|aumenta|aumentar|suba|sobe|subir|eleve|eleva|elevar|"
    r"esquente|esquenta|esquentar)\b|\bmais quente\b"
)
_DESCER = re.compile(
    r"\b(?:diminua|diminui|diminuir|abaixe|abaixa|abaixar|baixe|baixa|baixar|"
    r"reduza|reduz|reduzir|esfrie|esfria|esfriar)\b|\bmais (?:frio|gelado)\b"
)
_STATUS = re.compile(
    r"\b(?:status|estado)\b|\b(?:esta|ta) (?:ligado|desligado)\b|\b(?:esta|ta) (?:em|no|na|a) \d"
    r"|\bcomo (?:esta|ta)\b|\bqual (?:e )?(?:a )?temperatura\b|\bquantos graus\b"
)
# Verbos de comando: com eles, "como está" não transforma o pedido em pergunta.
_COMANDO = re.compile(
    r"\b(?:coloque|coloca|deixe|deixa|ponha|poe|bote|bota|mude|muda|troque|troca|"
    r"ajuste|ajusta|defina|define|regule|regula)\b"
)
_TEMPERATURA = re.compile(r"\b(?:temperatura|graus?)\b")
_VENTILACAO = re.compile(r"\b(?:ventilacao|vento|velocidade|ventoinha)\b")
_PREFIXO_VENTILACAO = (
    r"(?:ventilacao|vento|velocidade|ventoinha)(?: d[oe] ar(?:[- ]?condicionado)?)?"
    r"(?: (?:no|na|em|para|pra))?"
)
_VENTILACAO_NUMERO = re.compile(rf"\b{_PREFIXO_VENTILACAO} ([123])\b")
_MODO = re.compile(r"\bmodo\b")
_MODO_CURTO = re.compile(
    r"\b(?:no|em|para|pra|pro)(?: o)? (frio|quente|automatico|auto|seco)\b"
)
# Decimais ("22,5") ficam de fora; "22," no meio da frase ainda vale.
_NUMERO = re.compile(r"(?<!\d)(?<!\d[.,])(\d{1,3})(?!\d)(?![.,]\d)")

_MODOS = {
    "frio": "cool", "resfriar": "cool", "resfriamento": "cool",
    "refrigerar": "cool", "refrigeracao": "cool", "gelar": "cool",
    "quente": "heat", "aquecer": "heat", "aquecimento": "heat", "calor": "heat",
    "auto": "auto", "automatico": "auto",
    "ventilar": "fan", "ventilacao": "fan", "ventilador": "fan",
    "secar": "dry", "seco": "dry", "secagem": "dry",
    "desumidificar": "dry", "desumidificacao": "dry", "desumidificador": "dry",
}
# Palavras entre "modo" e o nome do modo: "mude o modo do ar para frio".
_LIGACOES_MODO = frozenset({
    "o", "a", "de", "do", "da", "no", "na", "em", "para", "pra", "pro",
    "ar", "condicionado", "ar-condicionado", "arcondicionado",
})
_NIVEIS_VENTILACAO = {
    "auto": "auto", "automatica": "auto", "automatico": "auto",
    "fraca": "low", "fraco": "low", "baixa": "low", "baixo": "low",
    "minima": "low", "minimo": "low",
    "media": "medium", "medio": "medium",
    "forte": "high", "alta": "high", "alto": "high", "maxima": "high", "maximo": "high",
}
_NIVEL_POR_NUMERO = {"1": "low", "2": "medium", "3": "high"}
_ORDEM_VENTILACAO = ("low", "medium", "high")

_UNIDADES = {
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
}
_DEZENAS = {
    "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
    "vinte": 20, "trinta": 30,
}

_ROTULOS_MODO = {
    "cool": "frio", "heat": "quente", "auto": "automático",
    "fan": "ventilar", "dry": "secar",
}
_ROTULOS_VENTILACAO = {
    "auto": "automática", "low": "fraca", "medium": "média", "high": "forte",
}


def _normalizar(comando: str) -> str:
    texto = unicodedata.normalize("NFD", str(comando).casefold())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(texto.strip(" ,.!?").split())


def _numeros_por_extenso(texto: str) -> str:
    unidades = "|".join(_UNIDADES)
    texto = re.sub(
        rf"\bvinte e ({unidades})\b",
        lambda achado: str(20 + _UNIDADES[achado.group(1)]),
        texto,
    )
    texto = re.sub(
        r"\b(" + "|".join(_DEZENAS) + r")\b",
        lambda achado: str(_DEZENAS[achado.group(1)]),
        texto,
    )
    # Unidades isoladas só valem como graus ("aumente dois graus") ou como
    # velocidade ("velocidade tres"); "um pouco" não é temperatura.
    texto = re.sub(
        rf"\b({unidades}) (graus?)\b",
        lambda achado: f"{_UNIDADES[achado.group(1)]} {achado.group(2)}",
        texto,
    )
    return re.sub(
        rf"\b({_PREFIXO_VENTILACAO}) ({unidades})\b",
        lambda achado: f"{achado.group(1)} {_UNIDADES[achado.group(2)]}",
        texto,
    )


def _modo_dito(texto: str) -> str | None:
    """Devolve o modo pedido, "" para um modo desconhecido ou None sem modo."""
    achado = _MODO.search(texto)
    if achado:
        for palavra in texto[achado.end():].split():
            if palavra not in _LIGACOES_MODO:
                # "modo turbo" e outros recursos que o controle não oferece.
                return _MODOS.get(palavra, "")
        return ""
    if _VENTILACAO.search(texto):
        # "ventilação no automático" ajusta a ventilação, não o modo.
        return None
    curto = _MODO_CURTO.search(texto)
    return _MODOS[curto.group(1)] if curto else None


def _nivel_ventilacao(texto: str, inicio: int, fim: int) -> str | None:
    # Prefere o nível dito depois de "ventilação": "modo auto com ventilação
    # forte" não deve virar ventilação automática.
    for trecho in (texto[fim:], texto[:inicio]):
        for palavra in trecho.split():
            if palavra in _NIVEIS_VENTILACAO:
                return _NIVEIS_VENTILACAO[palavra]
    return None


def interpretar_comando_ar(comando: str) -> list[PedidoAr] | None:
    """Traduz uma frase em pedidos ao ar, ou None quando ela não é para o ar."""
    texto = _normalizar(comando)
    if (
        not _ALVO.search(texto)
        or _OUTROS_ALVOS.search(texto)
        or _OUTROS_PEDIDOS.search(texto)
        or _AGENDAMENTO.search(texto)
    ):
        return None
    texto = _numeros_por_extenso(texto)
    if _DESLIGAR.search(texto):
        return [PedidoAr("power", False)]
    subir = bool(_SUBIR.search(texto))
    descer = bool(_DESCER.search(texto))
    if _STATUS.search(texto) and not (
        subir or descer or _LIGAR.search(texto) or _COMANDO.search(texto)
    ):
        # "O ar está em 22?" pergunta; não deve ligar o ar em 22 graus.
        return [PedidoAr("status")]

    pedidos: list[PedidoAr] = []
    modo = _modo_dito(texto)
    if modo == "":
        return None
    if modo:
        pedidos.append(PedidoAr("mode", modo))

    relativo = subir != descer
    texto_numeros = texto
    ventilacao = _VENTILACAO.search(texto)
    if ventilacao:
        numero_ventilacao = _VENTILACAO_NUMERO.search(texto)
        if numero_ventilacao:
            nivel = _NIVEL_POR_NUMERO[numero_ventilacao.group(1)]
            texto_numeros = (
                texto[:numero_ventilacao.start(1)] + texto[numero_ventilacao.end(1):]
            )
        else:
            nivel = _nivel_ventilacao(texto, ventilacao.start(), ventilacao.end())
        if nivel:
            pedidos.append(PedidoAr("fan", nivel))
        elif relativo and not _TEMPERATURA.search(texto):
            pedidos.append(PedidoAr("fan_delta", 1 if subir else -1))

    ajusta_temperatura = relativo and (
        ventilacao is None or bool(_TEMPERATURA.search(texto))
    )
    numero = _NUMERO.search(texto_numeros)
    if numero:
        valor = int(numero.group(1))
        if valor < 16 and ajusta_temperatura:
            pedidos.append(PedidoAr("temperature_delta", valor if subir else -valor))
        else:
            # Fora de 16 a 30 o driver recusa com a mensagem da faixa.
            pedidos.append(PedidoAr("temperature", valor))
    elif ajusta_temperatura:
        pedidos.append(PedidoAr("temperature_delta", 1 if subir else -1))

    if pedidos:
        return pedidos
    if _LIGAR.search(texto):
        return [PedidoAr("power", True)]
    if _STATUS.search(texto):
        return [PedidoAr("status")]
    return None


def descrever_estado_ar(estado: dict[str, object]) -> str:
    """Resume o último estado enviado; o ar não confirma o que recebeu."""
    if not estado.get("available", True):
        return str(estado.get("error") or "O Smart IR ainda não foi configurado na Nebula.")
    # O estado só muda quando o Smart IR confirma; uma falha depois disso
    # também precisa ser dita.
    falha = f" O último envio falhou: {estado['error']}" if estado.get("error") else ""
    if not estado.get("power"):
        return f"Pelo último comando que enviei, o ar está desligado.{falha}"
    suportadas = estado.get("supported_actions") or ("temperature", "mode", "fan")
    partes = []
    if "temperature" in suportadas and estado.get("temperature") is not None:
        partes.append(f"em {estado['temperature']} graus")
    if "mode" in suportadas and estado.get("mode") in _ROTULOS_MODO:
        partes.append(f"no modo {_ROTULOS_MODO[str(estado['mode'])]}")
    if "fan" in suportadas and estado.get("fan") in _ROTULOS_VENTILACAO:
        partes.append(f"com ventilação {_ROTULOS_VENTILACAO[str(estado['fan'])]}")
    detalhes = (" " + ", ".join(partes)) if partes else ""
    return f"Pelo último comando que enviei, o ar está ligado{detalhes}.{falha}"


def _resolver_relativo(pedido: PedidoAr, controle: ControleAr) -> tuple[str, object]:
    if pedido.acao == "temperature_delta":
        estado = controle.estado()
        atual = int(estado.get("temperature", 17))  # type: ignore[arg-type]
        minimo = int(estado.get("temperature_min", 16))  # type: ignore[arg-type]
        return "temperature", max(minimo, min(30, atual + int(pedido.valor)))  # type: ignore[arg-type]
    if pedido.acao == "fan_delta":
        atual = str(controle.estado().get("fan", "auto"))
        passo = int(pedido.valor)  # type: ignore[arg-type]
        if atual not in _ORDEM_VENTILACAO:
            return "fan", "high" if passo > 0 else "low"
        indice = _ORDEM_VENTILACAO.index(atual) + passo
        return "fan", _ORDEM_VENTILACAO[max(0, min(len(_ORDEM_VENTILACAO) - 1, indice))]
    return pedido.acao, pedido.valor


def _juntar(partes: list[str]) -> str:
    return partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]


def executar_pedidos_ar(pedidos: Sequence[PedidoAr], controle: ControleAr) -> ResultadoAr:
    """Envia os pedidos em ordem e informa também o que saiu antes de uma falha."""
    if not pedidos:
        return ResultadoAr("Nenhum comando foi enviado ao ar.", falhou=True)
    if any(pedido.acao == "status" for pedido in pedidos):
        return ResultadoAr(descrever_estado_ar(controle.estado()))
    ajustes: list[str] = []
    try:
        for pedido in pedidos:
            acao, valor = _resolver_relativo(pedido, controle)
            controle.executar(acao, valor)
            if acao == "power":
                # Ligar e desligar sempre chegam sozinhos do interpretador.
                return ResultadoAr("Mandei ligar o ar." if valor else "Mandei desligar o ar.")
            if acao == "temperature":
                ajustes.append(f"{valor} graus")
            elif acao == "mode":
                ajustes.append(f"o modo {_ROTULOS_MODO.get(str(valor), valor)}")
            elif acao == "fan":
                ajustes.append(f"ventilação {_ROTULOS_VENTILACAO.get(str(valor), valor)}")
    except (RuntimeError, ValueError, OSError) as exc:
        if ajustes:
            return ResultadoAr(
                f"Mandei o ar para {_juntar(ajustes)}, mas não consegui concluir o resto. {exc}",
                falhou=True,
            )
        return ResultadoAr(f"Não consegui controlar o ar. {exc}", falhou=True)
    return ResultadoAr(f"Mandei o ar para {_juntar(ajustes)}.")


__all__ = [
    "ControleAr",
    "PedidoAr",
    "ResultadoAr",
    "descrever_estado_ar",
    "executar_pedidos_ar",
    "interpretar_comando_ar",
]
