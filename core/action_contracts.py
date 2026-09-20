"""Contratos compartilhados das acoes existentes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from abajur_wifi import CORES, resolver_cor

ACOES_QWEN = (
    "encaminhar_codex",
    "abajur_ligar",
    "abajur_desligar",
    "abajur_cor",
    "abajur_temperatura",
    "abajur_brilho",
    "abajur_diminuir_brilho",
    "abajur_aumentar_brilho",
    "abajur_musica_iniciar",
    "abajur_musica_parar",
    "abajur_musica_intensidade",
    "abajur_musica_intensidade_aumentar",
    "abajur_musica_intensidade_diminuir",
    "abajur_tocha_iniciar",
    "abajur_tocha_parar",
    "modo_rpm_iniciar",
    "modo_rpm_parar",
    "modo_rpm_status",
    "modo_boost_iniciar",
    "modo_boost_parar",
    "modo_boost_status",
    "modo_ambilight_iniciar",
    "modo_ambilight_parar",
    "modo_ambilight_status",
    "abrir_aplicativo",
    "fechar_aplicativo",
    "tocar_youtube",
    "pesquisar_youtube",
    "pesquisar_google",
    "criar_nota",
    "pausar_midia",
    "continuar_midia",
    "aumentar_volume",
    "diminuir_volume",
    "capturar_tela",
    "salvar_clipe",
    "identificar_musica",
    "ver_horas",
    "abrir_emails",
    "desligar_pc",
)

ACOES_SEM_ARGUMENTO = frozenset((
    "abajur_ligar",
    "abajur_desligar",
    "abajur_musica_iniciar",
    "abajur_musica_parar",
    "abajur_musica_intensidade_aumentar",
    "abajur_musica_intensidade_diminuir",
    "abajur_tocha_iniciar",
    "abajur_tocha_parar",
    "modo_rpm_iniciar",
    "modo_rpm_parar",
    "modo_rpm_status",
    "modo_boost_iniciar",
    "modo_boost_parar",
    "modo_boost_status",
    "modo_ambilight_iniciar",
    "modo_ambilight_parar",
    "modo_ambilight_status",
    "pausar_midia",
    "continuar_midia",
    "aumentar_volume",
    "diminuir_volume",
    "capturar_tela",
    "salvar_clipe",
    "identificar_musica",
    "ver_horas",
    "abrir_emails",
    "desligar_pc",
))

LIMITES_ARGUMENTO = {
    "encaminhar_codex": 4_000,
    "abajur_cor": 32,
    "abajur_temperatura": 8,
    "abajur_brilho": 3,
    "abajur_diminuir_brilho": 2,
    "abajur_aumentar_brilho": 2,
    "abajur_musica_intensidade": 3,
    "abrir_aplicativo": 200,
    "fechar_aplicativo": 200,
    "tocar_youtube": 500,
    "pesquisar_youtube": 500,
    "pesquisar_google": 500,
    "criar_nota": 4_000,
}

FORMATO_RESULTADO_QWEN = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tipo", "acoes", "resposta"],
    "properties": {
        "tipo": {"type": "string", "enum": ["comando", "conversa"]},
        "acoes": {
            "type": "array",
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["acao", "argumento"],
                "properties": {
                    "acao": {"type": "string", "enum": list(ACOES_QWEN)},
                    "argumento": {"type": "string", "maxLength": 4_000},
                },
            },
        },
        "resposta": {"type": "string", "maxLength": 1_000},
    },
}

@dataclass(frozen=True)
class AcaoQwen:
    acao: str
    argumento: str = ""


@dataclass(frozen=True)
class ResultadoQwen:
    tipo: str
    acoes: tuple[AcaoQwen, ...]
    resposta: str = ""


class ContratoAcoes:
    @staticmethod
    def _validar_cor(argumento: str) -> str:
        cor = argumento.lower()
        if cor in CORES:
            return CORES[cor]
        hexadecimal = re.fullmatch(r"#?([0-9a-f]{6})", cor)
        if hexadecimal:
            return "#" + hexadecimal.group(1).upper()
        rgb = re.fullmatch(
            r"(?:rgb\s+)?(\d{1,3})[\s,]+(\d{1,3})[\s,]+(\d{1,3})",
            cor,
        )
        if rgb:
            canais = tuple(map(int, rgb.groups()))
            if all(0 <= canal <= 255 for canal in canais):
                return "rgb " + " ".join(map(str, canais))
        try:
            resolver_cor(cor)
        except (TypeError, ValueError, RuntimeError):
            pass
        else:
            return cor
        raise RuntimeError("a Qwen retornou uma cor de abajur inválida")

    @classmethod
    def _validar_acao(cls, item: object) -> AcaoQwen:
        if not isinstance(item, dict) or set(item) != {"acao", "argumento"}:
            raise RuntimeError("a Qwen retornou uma ação em formato inválido")
        acao = item["acao"]
        argumento = item["argumento"]
        if not isinstance(acao, str) or acao not in ACOES_QWEN:
            raise RuntimeError("a Qwen retornou uma ação não permitida")
        if not isinstance(argumento, str):
            raise RuntimeError("a Qwen retornou um argumento em formato inválido")
        argumento = argumento.strip()

        if acao in ACOES_SEM_ARGUMENTO:
            if argumento:
                raise RuntimeError(f"a ação {acao} não aceita argumento")
            return AcaoQwen(acao)

        limite = LIMITES_ARGUMENTO[acao]
        if not argumento or len(argumento) > limite:
            raise RuntimeError(f"a Qwen retornou um argumento inválido para {acao}")
        if acao == "abajur_cor":
            argumento = cls._validar_cor(argumento)
        elif acao == "abajur_temperatura":
            argumento = argumento.lower()
            if argumento not in {"quente", "neutra", "fria"}:
                raise RuntimeError("a Qwen retornou uma temperatura de abajur inválida")
        elif acao in {
            "abajur_brilho", "abajur_diminuir_brilho", "abajur_aumentar_brilho",
            "abajur_musica_intensidade",
        }:
            if not re.fullmatch(r"\d{1,3}", argumento):
                raise RuntimeError("a Qwen retornou um brilho de abajur inválido")
            brilho = int(argumento)
            maximo = 100 if acao in {
                "abajur_brilho", "abajur_musica_intensidade",
            } else 99
            if not 1 <= brilho <= maximo:
                raise RuntimeError(
                    f"a Qwen retornou um brilho fora da faixa de 1 a {maximo}"
                )
            argumento = str(brilho)
        return AcaoQwen(acao, argumento)

    @classmethod
    def _validar_resultado(cls, conteudo: str, validar_acao=None) -> ResultadoQwen:
        try:
            dados = json.loads(conteudo)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("a Qwen não retornou JSON válido") from exc
        if not isinstance(dados, dict) or set(dados) != {"tipo", "acoes", "resposta"}:
            raise RuntimeError("a Qwen retornou um resultado em formato inválido")

        tipo = dados["tipo"]
        itens = dados["acoes"]
        resposta = dados["resposta"]
        if tipo not in {"comando", "conversa"}:
            raise RuntimeError("a Qwen retornou um tipo de resultado inválido")
        if not isinstance(itens, list) or len(itens) > 4:
            raise RuntimeError("a Qwen retornou uma lista de ações inválida")
        if not isinstance(resposta, str) or len(resposta) > 1_000:
            raise RuntimeError("a Qwen retornou uma resposta de conversa inválida")

        acoes = tuple((validar_acao or cls._validar_acao)(item) for item in itens)
        resposta = resposta.strip()
        if tipo == "comando":
            if not acoes or resposta:
                raise RuntimeError("um comando deve conter ações e não deve conter resposta")
        elif acoes or not resposta:
            raise RuntimeError("uma conversa deve conter resposta e não deve conter ações")
        return ResultadoQwen(tipo=tipo, acoes=acoes, resposta=resposta)
