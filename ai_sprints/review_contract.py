"""Contrato estrito compartilhado pelos revisores Qwen e Gemini."""

from __future__ import annotations

import json
import re
from typing import Any


# ============================================================
# REVIEW NORMAL — QWEN 9B
# ============================================================

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "risk_level",
        "blocking_findings",
        "evidence",
        "required_tests",
        "summary",
    ],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["approved", "revise"],
        },
        "risk_level": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "blocking_findings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "line", "reason"],
                "properties": {
                    "path": {"type": "string"},
                    "line": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "reason": {"type": "string"},
                },
            },
        },
        "required_tests": {
            "type": "array",
            "items": {"type": "string"},
        },
        "summary": {
            "type": "string",
        },
    },
}


# ============================================================
# REWARD — SOMENTE GEMINI
# ============================================================

REWARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "delta",
        "reason",
    ],
    "properties": {
        "delta": {
            "type": "integer",
            "minimum": -10,
            "maximum": 10,
        },
        "reason": {
            "type": "string",
        },
    },
}


GEMINI_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "verdict",
        "risk_level",
        "blocking_findings",
        "evidence",
        "required_tests",
        "summary",
        "rewards",
    ],
    "properties": {
        "verdict": REVIEW_SCHEMA["properties"]["verdict"],
        "risk_level": REVIEW_SCHEMA["properties"]["risk_level"],
        "blocking_findings": REVIEW_SCHEMA["properties"]["blocking_findings"],
        "evidence": REVIEW_SCHEMA["properties"]["evidence"],
        "required_tests": REVIEW_SCHEMA["properties"]["required_tests"],
        "summary": REVIEW_SCHEMA["properties"]["summary"],
        "rewards": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "worker_4b",
                "reviewer_9b",
            ],
            "properties": {
                "worker_4b": REWARD_SCHEMA,
                "reviewer_9b": REWARD_SCHEMA,
            },
        },
    },
}


# ============================================================
# HELPERS
# ============================================================

def _parse_json_object(
    value: str | dict[str, Any],
    *,
    source_name: str,
) -> dict[str, Any]:
    """Converte JSON textual em dict sem corrigir respostas inválidas."""

    if isinstance(value, str):
        raw = value.strip()

        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        )

        raw = re.sub(
            r"\s*```$",
            "",
            raw,
        )

        try:
            value = json.loads(raw)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{source_name} nao retornou JSON valido."
            ) from exc

    if not isinstance(value, dict):
        raise ValueError(
            f"Resposta do {source_name} precisa ser um objeto JSON."
        )

    return value


def _base_review(
    value: dict[str, Any],
) -> dict[str, Any]:
    """Extrai somente os campos pertencentes ao REVIEW_SCHEMA."""

    return {
        field: value[field]
        for field in REVIEW_SCHEMA["required"]
    }


# ============================================================
# QWEN REVIEW
# ============================================================

def parse_review(
    value: str | dict[str, Any],
) -> dict[str, Any]:
    """Converte e valida a resposta; nunca corrige silenciosamente um reviewer."""

    value = _parse_json_object(
        value,
        source_name="Reviewer",
    )

    required = set(REVIEW_SCHEMA["required"])

    if set(value) != required:
        raise ValueError(
            f"Campos do reviewer invalidos; esperado: {sorted(required)}"
        )

    if value["verdict"] not in {
        "approved",
        "revise",
    }:
        raise ValueError(
            "verdict invalido."
        )

    if value["risk_level"] not in {
        "low",
        "medium",
        "high",
    }:
        raise ValueError(
            "risk_level invalido."
        )

    for field in (
        "blocking_findings",
        "evidence",
        "required_tests",
    ):
        if not isinstance(value[field], list):
            raise ValueError(
                f"{field} precisa ser uma lista."
            )

    if (
        not isinstance(value["summary"], str)
        or not value["summary"].strip()
    ):
        raise ValueError(
            "summary precisa explicar a decisao."
        )

    for finding in value["blocking_findings"]:
        if (
            not isinstance(finding, str)
            or not finding.strip()
        ):
            raise ValueError(
                "blocking_findings contem item invalido."
            )

    for test in value["required_tests"]:
        if (
            not isinstance(test, str)
            or not test.strip()
        ):
            raise ValueError(
                "required_tests contem item invalido."
            )

    for item in value["evidence"]:
        if (
            not isinstance(item, dict)
            or set(item) != {
                "path",
                "line",
                "reason",
            }
        ):
            raise ValueError(
                "Evidencia precisa conter path, line e reason."
            )

        if (
            not isinstance(item["path"], str)
            or not item["path"].strip()
        ):
            raise ValueError(
                "path da evidencia invalido."
            )

        if (
            type(item["line"]) is not int
            or item["line"] < 1
        ):
            raise ValueError(
                "line da evidencia invalida."
            )

        if (
            not isinstance(item["reason"], str)
            or not item["reason"].strip()
        ):
            raise ValueError(
                "reason da evidencia invalido."
            )

    return value


def review_approved(
    value: str | dict[str, Any],
) -> bool:
    review = parse_review(value)

    return (
        review["verdict"] == "approved"
        and review["risk_level"] == "low"
        and not review["blocking_findings"]
        and bool(review["evidence"])
        and not review["required_tests"]
    )


def review_safe_to_test(
    value: str | dict[str, Any],
) -> bool:
    """Libera apenas a aplicacao no worktree; testes pendentes ainda sao aceitos."""

    review = parse_review(value)

    return (
        review["verdict"] == "approved"
        and review["risk_level"] == "low"
        and not review["blocking_findings"]
        and bool(review["evidence"])
    )


# ============================================================
# GEMINI REVIEW + REWARD
# ============================================================

def parse_gemini_review(
    value: str | dict[str, Any],
) -> dict[str, Any]:
    """
    Valida a revisao final do Gemini.

    Alem do contrato normal de review, o Gemini precisa avaliar:
    - worker_4b
    - reviewer_9b

    Cada delta precisa ser inteiro entre -10 e +10.
    """

    value = _parse_json_object(
        value,
        source_name="Gemini",
    )

    required = set(
        GEMINI_REVIEW_SCHEMA["required"]
    )

    if set(value) != required:
        raise ValueError(
            "Campos do Gemini invalidos; "
            f"esperado: {sorted(required)}"
        )

    # Valida toda a parte técnica usando exatamente
    # o contrato normal já utilizado pelo Qwen.
    parse_review(
        _base_review(value)
    )

    rewards = value["rewards"]

    if not isinstance(rewards, dict):
        raise ValueError(
            "rewards precisa ser um objeto."
        )

    expected_agents = {
        "worker_4b",
        "reviewer_9b",
    }

    if set(rewards) != expected_agents:
        raise ValueError(
            "Agentes de reward invalidos; "
            f"esperado: {sorted(expected_agents)}"
        )

    for agent in sorted(expected_agents):
        reward = rewards[agent]

        if not isinstance(reward, dict):
            raise ValueError(
                f"Reward de {agent} precisa ser um objeto."
            )

        if set(reward) != {
            "delta",
            "reason",
        }:
            raise ValueError(
                f"Reward de {agent} precisa conter "
                "exatamente delta e reason."
            )

        delta = reward["delta"]

        # bool também é int em Python,
        # portanto usamos type(...) is int.
        if type(delta) is not int:
            raise ValueError(
                f"delta de {agent} precisa ser inteiro."
            )

        if not -10 <= delta <= 10:
            raise ValueError(
                f"delta de {agent} precisa ficar "
                "entre -10 e +10."
            )

        reason = reward["reason"]

        if (
            not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError(
                f"reason de {agent} nao pode ser vazio."
            )

    return value


def gemini_review_approved(
    value: str | dict[str, Any],
) -> bool:
    """Aplica as mesmas regras de aprovação ao review do Gemini."""

    review = parse_gemini_review(value)

    return review_approved(
        _base_review(review)
    )


def gemini_rewards(
    value: str | dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    Retorna somente os rewards depois de validar completamente
    a resposta do Gemini.
    """

    review = parse_gemini_review(value)

    return {
        "worker_4b": dict(
            review["rewards"]["worker_4b"]
        ),
        "reviewer_9b": dict(
            review["rewards"]["reviewer_9b"]
        ),
    }