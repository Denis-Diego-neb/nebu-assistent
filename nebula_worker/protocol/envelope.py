"""JobEnvelope v1.0: o unico formato de pedido aceito pelo worker (INV-006).

O parser e estrito de proposito: campo desconhecido, tipo errado ou valor fora
da faixa rejeitam o envelope inteiro antes de qualquer efeito. Assim o notebook
nunca recebe, por descuido, historico, objetivo global ou perfil do usuario
(INV-002): nao existe campo onde isso caiba.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.ids import is_ulid, new_ulid
from nebula_worker.protocol.serialization import canonical_json, sha256_hex
from nebula_worker.protocol.version import PROTOCOL_VERSION, negotiate

ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
OPERATIONS = frozenset({"generate"})
INPUT_FORMATS = frozenset({"text"})
OUTPUT_FORMATS = frozenset({"text", "json"})

# Tetos do protocolo. A politica do notebook aplica limites menores; estes so
# impedem valores absurdos de chegarem ate ela.
MAX_PAYLOAD_CHARS = 1_000_000
MAX_SYSTEM_CHARS = 20_000
MAX_SCHEMA_BYTES = 32_768
MAX_TIMEOUT_MS = 3_600_000
MAX_OUTPUT_TOKENS = 131_072
MIN_CONTEXT_TOKENS = 256
MAX_CONTEXT_TOKENS = 262_144

_TOP_REQUIRED = frozenset({
    "protocol_version", "job_id", "trace_id", "model_alias", "operation",
    "input", "output", "limits",
})
_TOP_OPTIONAL = frozenset({"generation", "capability_ticket"})


@dataclass(frozen=True)
class JobInput:
    format: str
    payload: str
    system: str | None


@dataclass(frozen=True)
class OutputSpec:
    format: str
    schema: dict | None


@dataclass(frozen=True)
class JobLimits:
    timeout_ms: int
    max_output_tokens: int


@dataclass(frozen=True)
class Generation:
    temperature: float | None = None
    seed: int | None = None
    context_tokens: int | None = None
    think: bool | None = None


@dataclass(frozen=True)
class JobEnvelope:
    protocol_version: str
    job_id: str
    trace_id: str
    model_alias: str
    operation: str
    input: JobInput
    output: OutputSpec
    limits: JobLimits
    generation: Generation
    capability_ticket: dict | None
    digest: str

    @property
    def required_scope(self) -> str:
        return required_scope(self.model_alias, self.operation)


def required_scope(model_alias: str, operation: str) -> str:
    return f"model:{model_alias}:{operation}"


def _invalid(message: str) -> WorkerError:
    return WorkerError(ErrorCode.INVALID_ENVELOPE, message)


def _object(value: object, where: str, required: frozenset[str],
            optional: frozenset[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise _invalid(f"{where} deve ser um objeto.")
    keys = set(value)
    missing = required - keys
    if missing:
        raise _invalid(f"{where}: campos obrigatorios ausentes: {sorted(missing)}.")
    extra = keys - required - optional
    if extra:
        raise _invalid(f"{where}: campos desconhecidos: {sorted(extra)}.")
    return value


def _text(value: object, where: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{where} deve ser um texto nao vazio.")
    if len(value) > maximum:
        raise _invalid(f"{where} excede {maximum} caracteres.")
    return value


def _integer(value: object, where: str, minimum: int, maximum: int) -> int:
    # bool e subclasse de int em Python; True nao pode virar timeout de 1 ms.
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(f"{where} deve ser inteiro entre {minimum} e {maximum}.")
    return value


def _number(value: object, where: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise _invalid(f"{where} deve ser numero entre {minimum} e {maximum}.")
    return float(value)


def envelope_digest(raw: dict) -> str:
    """Hash do envelope sem o ticket; o ticket assina exatamente este valor."""
    unsigned = {key: value for key, value in raw.items() if key != "capability_ticket"}
    return sha256_hex(canonical_json(unsigned))


def parse_envelope(raw: object, *, require_ticket: bool = True) -> JobEnvelope:
    if not isinstance(raw, dict):
        raise _invalid("O envelope deve ser um objeto JSON.")
    # A versao vem antes do resto: um campo novo de uma versao futura deve
    # resultar em "versao nao suportada", nao em "campo desconhecido".
    if "protocol_version" in raw:
        version = negotiate(raw["protocol_version"])
    else:
        raise _invalid("protocol_version ausente.")
    _object(raw, "envelope", _TOP_REQUIRED, _TOP_OPTIONAL)
    if require_ticket and "capability_ticket" not in raw:
        raise WorkerError(ErrorCode.TICKET_INVALID, "O envelope nao traz capability_ticket.")
    if raw.get("capability_ticket") is not None and not isinstance(raw["capability_ticket"], dict):
        raise WorkerError(ErrorCode.TICKET_INVALID, "capability_ticket deve ser um objeto.")

    if not is_ulid(raw["job_id"]):
        raise _invalid("job_id deve ser um ULID.")
    if not is_ulid(raw["trace_id"]):
        raise _invalid("trace_id deve ser um ULID.")
    alias = raw["model_alias"]
    if not isinstance(alias, str) or ALIAS_RE.fullmatch(alias) is None:
        raise _invalid("model_alias invalido.")
    operation = raw["operation"]
    if operation not in OPERATIONS:
        raise WorkerError(ErrorCode.UNSUPPORTED_OPERATION, "Operacao nao suportada neste protocolo.")

    source = _object(raw["input"], "input", frozenset({"format", "payload"}), frozenset({"system"}))
    if source["format"] not in INPUT_FORMATS:
        raise _invalid("input.format deve ser text.")
    job_input = JobInput(
        format=source["format"],
        payload=_text(source["payload"], "input.payload", MAX_PAYLOAD_CHARS),
        system=_text(source["system"], "input.system", MAX_SYSTEM_CHARS) if "system" in source else None,
    )

    target = _object(raw["output"], "output", frozenset({"format"}), frozenset({"schema"}))
    if target["format"] not in OUTPUT_FORMATS:
        raise _invalid("output.format deve ser text ou json.")
    schema = target.get("schema")
    if "schema" in target:
        if target["format"] != "json":
            raise _invalid("output.schema so e aceito com output.format json.")
        if not isinstance(schema, dict) or not schema:
            raise _invalid("output.schema deve ser um objeto JSON Schema nao vazio.")
        try:
            schema_size = len(canonical_json(schema))
        except (TypeError, ValueError) as exc:
            raise _invalid("output.schema nao e JSON valido.") from exc
        if schema_size > MAX_SCHEMA_BYTES:
            raise _invalid(f"output.schema excede {MAX_SCHEMA_BYTES} bytes.")
    output = OutputSpec(format=target["format"], schema=schema)

    limits_raw = _object(raw["limits"], "limits", frozenset({"timeout_ms", "max_output_tokens"}))
    limits = JobLimits(
        timeout_ms=_integer(limits_raw["timeout_ms"], "limits.timeout_ms", 1, MAX_TIMEOUT_MS),
        max_output_tokens=_integer(
            limits_raw["max_output_tokens"], "limits.max_output_tokens", 1, MAX_OUTPUT_TOKENS
        ),
    )

    generation = Generation()
    if "generation" in raw:
        options = _object(raw["generation"], "generation", frozenset(),
                          frozenset({"temperature", "seed", "context_tokens", "think"}))
        think = options.get("think")
        if "think" in options and type(think) is not bool:
            raise _invalid("generation.think deve ser booleano.")
        generation = Generation(
            temperature=(_number(options["temperature"], "generation.temperature", 0.0, 2.0)
                         if "temperature" in options else None),
            seed=(_integer(options["seed"], "generation.seed", -(2 ** 31), 2 ** 31 - 1)
                  if "seed" in options else None),
            context_tokens=(_integer(options["context_tokens"], "generation.context_tokens",
                                     MIN_CONTEXT_TOKENS, MAX_CONTEXT_TOKENS)
                            if "context_tokens" in options else None),
            think=think if "think" in options else None,
        )

    try:
        digest = envelope_digest(raw)
    except (TypeError, ValueError) as exc:
        raise _invalid("O envelope contem valores que nao sao JSON puro.") from exc
    return JobEnvelope(
        protocol_version=version,
        job_id=raw["job_id"],
        trace_id=raw["trace_id"],
        model_alias=alias,
        operation=operation,
        input=job_input,
        output=output,
        limits=limits,
        generation=generation,
        capability_ticket=raw.get("capability_ticket"),
        digest=digest,
    )


def build_generate_envelope(
    prompt: str,
    *,
    model_alias: str = "qwen_edge",
    system: str | None = None,
    output_format: str = "text",
    schema: dict | None = None,
    timeout_ms: int = 120_000,
    max_output_tokens: int = 2048,
    temperature: float | None = None,
    seed: int | None = None,
    context_tokens: int | None = None,
    think: bool | None = None,
    job_id: str | None = None,
    trace_id: str | None = None,
) -> dict:
    """Monta um envelope sem ticket; quem assina e o PC, na hora do envio."""
    envelope: dict = {
        "protocol_version": PROTOCOL_VERSION,
        "job_id": job_id or new_ulid(),
        "trace_id": trace_id or new_ulid(),
        "model_alias": model_alias,
        "operation": "generate",
        "input": {"format": "text", "payload": prompt},
        "output": {"format": output_format},
        "limits": {"timeout_ms": timeout_ms, "max_output_tokens": max_output_tokens},
    }
    if system is not None:
        envelope["input"]["system"] = system
    if schema is not None:
        envelope["output"]["schema"] = schema
    generation = {
        key: value for key, value in (
            ("temperature", temperature), ("seed", seed),
            ("context_tokens", context_tokens), ("think", think),
        ) if value is not None
    }
    if generation:
        envelope["generation"] = generation
    parse_envelope(envelope, require_ticket=False)
    return envelope
