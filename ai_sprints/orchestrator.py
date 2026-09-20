"""Orquestra revisoes arquiteturais focadas com dois modelos Ollama.

Cada candidato declara os simbolos que servem de evidencia. O worker propoe uma
extracao e o reviewer valida o plano. O hash da evidencia impede rodadas
identicas e o estado persistido permite pausar e retomar sem perder resultados.
Este programa nunca altera os arquivos de producao.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agents.ollama_client import OllamaClient


PROTOCOL_VERSION = "1"
DEFAULT_WORKER_HOST = "http://127.0.0.1:11434"
DEFAULT_REVIEWER_HOST = "http://192.168.15.4:11434"


@dataclass(frozen=True)
class EvidenceItem:
    path: str
    symbols: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    objective: str
    evidence: tuple[EvidenceItem, ...]
    acceptance: tuple[str, ...]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_candidate(path: Path) -> Candidate:
    raw = _read_json(path)
    expected = {"id", "objective", "evidence", "acceptance"}
    if set(raw) != expected:
        raise ValueError(f"Manifesto deve conter exatamente: {sorted(expected)}")
    evidence = tuple(
        EvidenceItem(str(item["path"]), tuple(str(s) for s in item["symbols"]))
        for item in raw["evidence"]
    )
    return Candidate(
        candidate_id=str(raw["id"]),
        objective=str(raw["objective"]),
        evidence=evidence,
        acceptance=tuple(str(item) for item in raw["acceptance"]),
    )


def _qualified_nodes(tree: ast.AST) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = node
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        found[f"{node.name}.{child.name}"] = child
    return found


def extract_symbol(path: Path, symbol: str) -> str:
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    node = _qualified_nodes(tree).get(symbol)
    if node is None:
        raise ValueError(f"Simbolo {symbol!r} nao encontrado em {path}")
    lines = source.splitlines()
    start = node.lineno
    end = getattr(node, "end_lineno", start)
    numbered = "\n".join(
        f"{line_no:04d}: {lines[line_no - 1]}"
        for line_no in range(start, end + 1)
    )
    return f"### {path.relative_to(PROJECT_ROOT).as_posix()}::{symbol} (L{start}-L{end})\n{numbered}"


def build_evidence(candidate: Candidate) -> str:
    sections: list[str] = []
    for item in candidate.evidence:
        path = (PROJECT_ROOT / item.path).resolve()
        if PROJECT_ROOT not in path.parents:
            raise ValueError(f"Evidencia fora do projeto: {item.path}")
        for symbol in item.symbols:
            sections.append(extract_symbol(path, symbol))
    return "\n\n".join(sections)


def fingerprint(candidate: Candidate, evidence: str) -> str:
    payload = json.dumps(
        {
            "protocol": PROTOCOL_VERSION,
            "candidate": candidate.candidate_id,
            "objective": candidate.objective,
            "acceptance": candidate.acceptance,
            "evidence": evidence,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _state_path(candidate_id: str) -> Path:
    return PROJECT_ROOT / "ai_sprints" / candidate_id / "state.json"


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path)


def set_paused(candidate_id: str, paused: bool) -> None:
    path = _state_path(candidate_id)
    state = _load_state(path)
    state.update({"candidate": candidate_id, "paused": paused, "updated_at": datetime.now().isoformat(timespec="seconds")})
    _write_json(path, state)
    print("Sprint pausada." if paused else "Sprint liberada para retomar.")


def _worker_prompt(candidate: Candidate, evidence: str) -> str:
    acceptance = "\n".join(f"- {item}" for item in candidate.acceptance)
    return f"""CANDIDATO: {candidate.candidate_id}
OBJETIVO: {candidate.objective}

CRITERIOS DE ACEITE:
{acceptance}

EVIDENCIA COMPLETA E UNICA PARA ESTA ANALISE:
{evidence}

Proponha uma extracao incremental. Seja concreto e conciso. Entregue:
1. responsabilidades que saem do host;
2. contrato de entrada e saida da tool;
3. dependencias injetadas, sem importar main.py;
4. mudancas por arquivo;
5. testes que preservam o comportamento;
6. riscos ainda nao resolvidos.
O motor ModoAmbilight e seus loops ja estao fora de main.py. Nao proponha mover
calculo de pixels, suavizacao ou threads. O escopo e: tools diretas, orquestracao
que ainda esta no host e escolha entre enviar_rgb e enviar_zonas no teclado.
Nao invente comportamento ausente da evidencia.
"""


def _reviewer_prompt(candidate: Candidate, evidence: str, proposal: str) -> str:
    acceptance = "\n".join(f"- {item}" for item in candidate.acceptance)
    return f"""Revise uma proposta de modularizacao da Nebula.

OBJETIVO: {candidate.objective}
CRITERIOS DE ACEITE:
{acceptance}

EVIDENCIA:
{evidence}

PROPOSTA DO WORKER:
{proposal}

Responda de forma curta com:
- VEREDITO: APROVADO ou REVISAR;
- alegacoes nao sustentadas pela evidencia;
- riscos de regressao, thread ou hardware;
- plano final minimo por arquivo;
- testes obrigatorios.
Marque REVISAR se a proposta nao registrar iniciar/parar/status como chamadas
diretas, se ainda converter tool em frase, ou se nao tratar a diferenca entre o
frame Custom multizona e a atualizacao RGB uniforme do teclado USB.
Nao reescreva a proposta inteira e nao sugira uma segunda rodada sem indicar qual evidencia nova falta.
"""


def compact_evidence(evidence: str, per_section: int = 2200) -> str:
    """Mantem inicio e fim de cada simbolo para o reviewer nao perder a resposta."""
    sections = evidence.split("\n\n### ")
    compacted: list[str] = []
    for index, section in enumerate(sections):
        if index:
            section = "### " + section
        if len(section) > per_section:
            half = (per_section - 80) // 2
            section = section[:half] + "\n... [trecho omitido] ...\n" + section[-half:]
        compacted.append(section)
    return "\n\n".join(compacted)


def valid_review(review: str) -> bool:
    normalized = review.upper()
    return len(review.strip()) >= 400 and "VEREDITO:" in normalized and (
        "VEREDITO: APROVADO" in normalized or "VEREDITO: REVISAR" in normalized
    ) and all(marker in normalized for marker in ("RISCO", "PLANO", "TEST"))


def run(candidate_path: Path, force: bool = False) -> None:
    candidate = load_candidate(candidate_path)
    output_dir = PROJECT_ROOT / "ai_sprints" / candidate.candidate_id
    state_path = output_dir / "state.json"
    state = _load_state(state_path)
    if state.get("paused"):
        raise RuntimeError("Sprint pausada. Use --resume antes de executar.")

    evidence = build_evidence(candidate)
    evidence_hash = fingerprint(candidate, evidence)
    review_path = output_dir / "review.md"
    if not force and state.get("status") == "complete" and state.get("evidence_hash") == evidence_hash:
        previous_review = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
        if valid_review(previous_review):
            print("Evidencia inalterada; sprint ja concluida. Use --force para repetir.")
            return
        state["status"] = "review_invalid"
        _write_json(state_path, state)

    worker = OllamaClient(
        os.getenv("NEBULA_SPRINT_WORKER_HOST", DEFAULT_WORKER_HOST),
        os.getenv("NEBULA_SPRINT_WORKER_MODEL", "qwen3.5:4b"),
        timeout=240,
    )
    reviewer = OllamaClient(
        os.getenv("NEBULA_SPRINT_REVIEWER_HOST", DEFAULT_REVIEWER_HOST),
        os.getenv("NEBULA_SPRINT_REVIEWER_MODEL", "qwen3.5:9b"),
        timeout=300,
    )
    if not worker.is_alive() or not reviewer.is_alive():
        raise RuntimeError("Worker ou reviewer indisponivel; nenhum progresso foi descartado.")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evidence.md").write_text(evidence + "\n", encoding="utf-8")
    _write_json(state_path, {
        "candidate": candidate.candidate_id,
        "status": "worker_running",
        "paused": False,
        "evidence_hash": evidence_hash,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })

    worker_path = output_dir / "worker.md"
    can_resume_review = (
        not force
        and state.get("evidence_hash") == evidence_hash
        and state.get("status") in {"reviewer_running", "review_invalid", "review_failed"}
        and worker_path.exists()
    )
    if can_resume_review:
        proposal = worker_path.read_text(encoding="utf-8")
        print("Proposta do worker reaproveitada; retomando no reviewer.")
    else:
        proposal = worker.chat(
            _worker_prompt(candidate, evidence),
            temperature=0.1,
            num_ctx=12288,
            num_predict=2400,
        )
        worker_path.write_text(proposal + "\n", encoding="utf-8")
    _write_json(state_path, {
        "candidate": candidate.candidate_id,
        "status": "reviewer_running",
        "paused": False,
        "evidence_hash": evidence_hash,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })

    try:
        review = reviewer.chat(
            _reviewer_prompt(candidate, compact_evidence(evidence, per_section=900), proposal),
            temperature=0.1,
            num_ctx=8192,
            num_predict=900,
        )
    except Exception as exc:
        _write_json(state_path, {
            "candidate": candidate.candidate_id,
            "status": "review_failed",
            "paused": False,
            "evidence_hash": evidence_hash,
            "error": f"{type(exc).__name__}: {exc}",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        raise RuntimeError("Reviewer falhou; a proposta do worker foi preservada para retomar.") from exc
    review_path.write_text(review + "\n", encoding="utf-8")
    if not valid_review(review):
        _write_json(state_path, {
            "candidate": candidate.candidate_id,
            "status": "review_invalid",
            "paused": False,
            "evidence_hash": evidence_hash,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })
        raise RuntimeError("Reviewer respondeu fora do contrato; revisao nao foi aceita.")
    _write_json(state_path, {
        "candidate": candidate.candidate_id,
        "status": "complete",
        "paused": False,
        "evidence_hash": evidence_hash,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    print(f"Sprint concluida em {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, nargs="?", help="Manifesto JSON do candidato")
    parser.add_argument("--force", action="store_true", help="Repete mesmo com evidencia inalterada")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pause", metavar="ID", help="Pausa uma sprint")
    group.add_argument("--resume", metavar="ID", help="Libera uma sprint pausada")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.pause:
        set_paused(args.pause, True)
        return
    if args.resume:
        set_paused(args.resume, False)
        return
    if args.candidate is None:
        raise SystemExit("Informe um manifesto ou use --pause/--resume.")
    run(args.candidate.resolve(), force=args.force)


if __name__ == "__main__":
    main()
