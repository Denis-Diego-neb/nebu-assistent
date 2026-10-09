"""Converte a saida crua do modelo no ``output`` do JobResult, ou num erro claro.

JSON truncado ou invalido e falha, nunca "quase sucesso": o PC precisa saber
que a resposta foi cortada pelo limite de tokens em vez de receber um objeto
pela metade (foi assim que patches truncados pareciam validos nas sprints).
"""

from __future__ import annotations

import json
import re

from nebula_worker.models.ollama_client import GenerationOutput
from nebula_worker.protocol.envelope import OutputSpec
from nebula_worker.protocol.errors import ErrorCode, WorkerError
from nebula_worker.protocol.serialization import canonical_json

RAW_PREVIEW_CHARS = 4000
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


def clean(generated: GenerationOutput, spec: OutputSpec, max_bytes: int) -> dict:
    text = generated.text.strip()
    truncated = generated.stop_reason == "length"
    if spec.format == "json":
        if truncated:
            raise WorkerError(ErrorCode.OUTPUT_TRUNCATED,
                              "A resposta atingiu max_output_tokens antes de terminar o JSON.",
                              {"output_tokens": generated.output_tokens})
        # So remove a cerca de Markdown quando ela envolve a resposta inteira;
        # o conteudo em si nunca e reescrito.
        fenced = _FENCE.fullmatch(text)
        try:
            payload = json.loads(fenced.group(1) if fenced else text)
            # NaN/Infinity passam no json.loads do Python, mas nao sao JSON.
            encoded = canonical_json(payload)
        except ValueError as exc:
            raise WorkerError(ErrorCode.INVALID_OUTPUT, "A resposta do modelo nao e JSON valido.",
                              {"raw_output": text[:RAW_PREVIEW_CHARS]}) from exc
        if len(encoded) > max_bytes:
            raise WorkerError(ErrorCode.OUTPUT_TOO_LARGE, "O resultado excede o limite do worker.")
        return {"format": "json", "payload": payload}
    if not text:
        raise WorkerError(ErrorCode.INVALID_OUTPUT, "O modelo devolveu uma resposta vazia.")
    if len(text.encode("utf-8")) > max_bytes:
        raise WorkerError(ErrorCode.OUTPUT_TOO_LARGE, "O resultado excede o limite do worker.")
    return {"format": "text", "payload": text, "truncated": truncated}
