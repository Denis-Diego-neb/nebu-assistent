"""Prepara refactors com dois Ollamas sem tocar na arvore de trabalho principal.

O worker gera um patch restrito por manifesto. O patch so e aplicado em um Git
worktree descartavel depois de uma revisao previa. Testes fixos do manifesto e
uma revisao final produzem um artefato para o Codex ou usuario revisar. Este
programa nunca faz commit, merge ou push.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_sprints.orchestrator import (
    build_evidence,
    compact_evidence,
    load_candidate,
    valid_review,
)
from core.agents import OllamaClient


QUEUE_DIR = PROJECT_ROOT / "ai_sprints" / "queue"
RUNS_DIR = PROJECT_ROOT / "ai_sprints" / "autopilot_runs"
GLOBAL_STATE = PROJECT_ROOT / "ai_sprints" / "autopilot_state.json"
WORKTREE_ROOT = PROJECT_ROOT.parent / ".nebula-ai-worktrees"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
FORBIDDEN_ADDED_TEXT = (
    "os.system(",
    "subprocess.",
    "shutil.rmtree(",
    "requests.",
    "socket.",
    ".unlink(",
    "remove-item",
    "format c:",
    "shutdown ",
)


@dataclass(frozen=True)
class Job:
    job_id: str
    candidate_path: Path
    allowed_paths: frozenset[str]
    tests: tuple[tuple[str, ...], ...]
    timeout_seconds: int


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_job(path: Path) -> Job:
    raw = _read_json(path)
    expected = {"id", "candidate", "allowed_paths", "tests", "timeout_seconds"}
    if set(raw) != expected:
        raise ValueError(f"Job deve conter exatamente: {sorted(expected)}")
    job_id = str(raw["id"])
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("ID do job invalido.")
    allowed = frozenset(PurePosixPath(str(item)).as_posix() for item in raw["allowed_paths"])
    if not allowed or any(path.startswith("../") or path.startswith("/") for path in allowed):
        raise ValueError("allowed_paths precisa conter caminhos relativos seguros.")
    tests = tuple(tuple(str(arg) for arg in command) for command in raw["tests"])
    if not tests or len(tests) > 6 or any(not command or command[0] != "{python}" for command in tests):
        raise ValueError("Cada teste deve ser uma lista iniciada por {python}; limite de seis.")
    timeout = int(raw["timeout_seconds"])
    if not 10 <= timeout <= 1800:
        raise ValueError("timeout_seconds deve ficar entre 10 e 1800.")
    candidate_path = (PROJECT_ROOT / str(raw["candidate"])).resolve()
    if PROJECT_ROOT not in candidate_path.parents:
        raise ValueError("Manifesto do candidato fora do projeto.")
    return Job(job_id, candidate_path, allowed, tests, timeout)


def git(*args: str, cwd: Path = PROJECT_ROOT, timeout: int = 120) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git falhou")
    return result.stdout


def _source_fingerprint(job: Job, evidence: str) -> str:
    payload = {
        "base": git("rev-parse", "HEAD").strip(),
        "job": {
            "id": job.job_id,
            "allowed_paths": sorted(job.allowed_paths),
            "tests": job.tests,
            "timeout": job.timeout_seconds,
        },
        "candidate": _read_json(job.candidate_path),
        "evidence": evidence,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_sources_clean(job: Job, evidence_paths: set[str]) -> None:
    paths = sorted(job.allowed_paths | evidence_paths)
    dirty = git("status", "--porcelain", "--", *paths).strip()
    if dirty:
        raise RuntimeError(
            "O job nao pode partir de arquivos nao commitados. Revise primeiro:\n" + dirty
        )


def _worker_prompt(job: Job, objective: str, acceptance: tuple[str, ...], evidence: str) -> str:
    return f"""Voce e o worker de implementacao da Nebula. Gere um refactor incremental.

OBJETIVO:
{objective}

CRITERIOS:
{chr(10).join('- ' + item for item in acceptance)}

ARQUIVOS QUE PODEM SER ALTERADOS OU CRIADOS, E NENHUM OUTRO:
{chr(10).join('- ' + item for item in sorted(job.allowed_paths))}

EVIDENCIA:
{evidence}

Retorne somente um unified diff Git entre as linhas PATCH_START e PATCH_END.
Nao inclua comandos, commit, explicacoes, binarios, rename ou exclusoes. Preserve
interfaces existentes e nao acesse rede ou hardware em testes.
"""


def _extract_patch(response: str) -> str:
    match = re.search(r"PATCH_START\s*(.*?)\s*PATCH_END", response, re.DOTALL)
    if not match:
        raise ValueError("Worker nao retornou PATCH_START/PATCH_END.")
    patch = match.group(1).strip()
    if patch.startswith("```"):
        patch = re.sub(r"^```(?:diff)?\s*", "", patch)
        patch = re.sub(r"\s*```$", "", patch)
    if not patch.startswith("diff --git "):
        raise ValueError("Worker nao retornou um unified diff Git.")
    return patch + "\n"


def _patch_paths(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        match = re.fullmatch(r"diff --git a/(.+) b/(.+)", line)
        if not match or match.group(1) != match.group(2):
            raise ValueError("Rename ou cabecalho de diff invalido.")
        paths.add(PurePosixPath(match.group(2)).as_posix())
    if not paths:
        raise ValueError("Patch sem arquivos.")
    return paths


def validate_patch(patch: str, allowed_paths: frozenset[str]) -> set[str]:
    paths = _patch_paths(patch)
    outside = paths - allowed_paths
    if outside:
        raise ValueError(f"Patch tentou alterar arquivos fora do escopo: {sorted(outside)}")
    lowered = patch.casefold()
    if "deleted file mode" in lowered or "rename from" in lowered or "git binary patch" in lowered:
        raise ValueError("Exclusoes, renames e binarios nao sao permitidos.")
    added = "\n".join(
        line[1:] for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ).casefold()
    forbidden = [item for item in FORBIDDEN_ADDED_TEXT if item in added]
    if forbidden:
        raise ValueError(f"Patch contem operacao bloqueada: {forbidden}")
    return paths


def _review_prompt(stage: str, objective: str, evidence: str, patch: str, tests: str = "") -> str:
    return f"""Voce e o reviewer 9B da Nebula. Revise o patch de forma adversarial.
ETAPA: {stage}
OBJETIVO: {objective}

EVIDENCIA RESUMIDA:
{compact_evidence(evidence, per_section=1200)}

PATCH REAL:
{patch}

RESULTADOS DE TESTE:
{tests or '[ainda nao executados]'}

Comece exatamente com VEREDITO: APROVADO ou VEREDITO: REVISAR. Depois inclua
as secoes RISCOS, PLANO e TESTES. Aprove somente se o patch respeita o escopo,
preserva contratos e os testes apresentados sustentam a mudanca.
"""


def _approved(review: str) -> bool:
    return valid_review(review) and review.upper().startswith("VEREDITO: APROVADO")


def _worktree_path(job_id: str) -> Path:
    path = (WORKTREE_ROOT / job_id).resolve()
    if path.parent != WORKTREE_ROOT.resolve() or not ID_PATTERN.fullmatch(job_id):
        raise RuntimeError("Caminho de worktree inseguro.")
    return path


def _create_worktree(job_id: str) -> Path:
    path = _worktree_path(job_id)
    WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)
    if path.exists():
        git("worktree", "remove", "--force", str(path))
    git("worktree", "add", "--detach", str(path), "HEAD", timeout=180)
    return path


def _remove_worktree(path: Path) -> None:
    if path.resolve().parent != WORKTREE_ROOT.resolve():
        raise RuntimeError("Recusa ao remover worktree fora da raiz isolada.")
    if path.exists():
        git("worktree", "remove", "--force", str(path), timeout=180)
    git("worktree", "prune")


def _python_executable() -> str:
    configured = os.getenv("NEBULA_AUTOPILOT_PYTHON")
    if configured:
        return configured
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv if venv.exists() else Path(sys.executable))


def run_tests(job: Job, worktree: Path) -> str:
    logs: list[str] = []
    env = os.environ.copy()
    env.update({"NEBULA_QWEN_ENABLED": "0", "NEBULA_AUTOPILOT": "1", "PYTHONUTF8": "1"})
    for command in job.tests:
        expanded = [_python_executable() if arg == "{python}" else arg for arg in command]
        result = subprocess.run(
            expanded, cwd=worktree, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=job.timeout_seconds, env=env,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        logs.append(f"$ {' '.join(command)}\nexit={result.returncode}\n{output[-8000:]}")
        if result.returncode:
            raise RuntimeError("Teste falhou:\n" + logs[-1])
    return "\n\n".join(logs)


def _save_state(run_dir: Path, status: str, fingerprint: str, **extra: Any) -> None:
    _write_json(run_dir / "state.json", {
        "status": status,
        "fingerprint": fingerprint,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        **extra,
    })


def process(job_path: Path, *, force: bool = False) -> None:
    job = load_job(job_path)
    candidate = load_candidate(job.candidate_path)
    evidence = build_evidence(candidate)
    evidence_paths = {item.path for item in candidate.evidence}
    fingerprint = _source_fingerprint(job, evidence)
    run_dir = RUNS_DIR / job.job_id
    state_path = run_dir / "state.json"
    previous = _read_json(state_path) if state_path.exists() else {}
    same_source = previous.get("fingerprint") == fingerprint
    failures_before = int(previous.get("agent_failures", 0)) if same_source else 0
    resume_stage = previous.get("resume_stage") if same_source else None
    if (
        not force
        and previous.get("fingerprint") == fingerprint
        and previous.get("status") == "waiting_agents"
        and float(previous.get("next_retry_at", 0)) > time.time()
    ):
        print(f"{job.job_id}: aguardando a proxima tentativa dos agentes.")
        return
    if not force and previous.get("fingerprint") == fingerprint and previous.get("status") in {
        "ready_for_human_review", "rejected", "failed", "blocked_agents", "waiting_human_review",
    }:
        print(f"{job.job_id}: estado {previous['status']} ja salvo; fonte inalterada.")
        return
    try:
        _assert_sources_clean(job, evidence_paths)
    except RuntimeError as exc:
        _save_state(run_dir, "waiting_human_review", fingerprint, error=str(exc))
        print(f"{job.job_id}: aguardando revisao/commit dos arquivos de origem.")
        return

    worker = OllamaClient(
        os.getenv("NEBULA_SPRINT_WORKER_HOST", "http://127.0.0.1:11434"),
        os.getenv("NEBULA_SPRINT_WORKER_MODEL", "qwen3.5:4b"), timeout=300,
    )
    reviewer = OllamaClient(
        os.getenv("NEBULA_SPRINT_REVIEWER_HOST", "http://192.168.15.4:11434"),
        os.getenv("NEBULA_SPRINT_REVIEWER_MODEL", "qwen3.5:9b"), timeout=360,
    )
    if not worker.is_alive() or not reviewer.is_alive():
        attempts = failures_before + 1
        status = "blocked_agents" if attempts >= 3 else "waiting_agents"
        _save_state(
            run_dir,
            status,
            fingerprint,
            error="Worker ou reviewer offline.",
            agent_failures=attempts,
            resume_stage=resume_stage,
            next_retry_at=time.time() + min(900, 60 * (2 ** (attempts - 1))),
        )
        print(f"{job.job_id}: {status}; tentativa {attempts}.")
        return

    worktree = _create_worktree(job.job_id)
    try:
        _save_state(run_dir, "baseline_tests", fingerprint)
        baseline = run_tests(job, worktree)
        (run_dir / "baseline_tests.txt").write_text(baseline + "\n", encoding="utf-8")

        patch_path = run_dir / "candidate.patch"
        can_reuse_patch = resume_stage in {"pre_review", "tests_running", "final_review"} and patch_path.exists()
        if can_reuse_patch:
            patch = patch_path.read_text(encoding="utf-8")
            changed_paths = validate_patch(patch, job.allowed_paths)
        else:
            _save_state(run_dir, "worker_running", fingerprint)
            response = worker.chat(
                _worker_prompt(job, candidate.objective, candidate.acceptance, evidence),
                temperature=0.05, num_ctx=16384, num_predict=4096,
            )
            patch = _extract_patch(response)
            changed_paths = validate_patch(patch, job.allowed_paths)
            patch_path.write_text(patch, encoding="utf-8")

        pre_review_path = run_dir / "pre_review.md"
        can_reuse_pre_review = resume_stage in {"tests_running", "final_review"} and pre_review_path.exists()
        if can_reuse_pre_review:
            pre_review = pre_review_path.read_text(encoding="utf-8")
        else:
            _save_state(run_dir, "pre_review", fingerprint, changed_paths=sorted(changed_paths))
            pre_review = reviewer.chat(
                _review_prompt("antes dos testes", candidate.objective, evidence, patch),
                temperature=0.05, num_ctx=12288, num_predict=1400,
            )
            pre_review_path.write_text(pre_review + "\n", encoding="utf-8")
        if not _approved(pre_review):
            _save_state(run_dir, "rejected", fingerprint, stage="pre_review")
            return

        git("apply", "--check", str(patch_path), cwd=worktree)
        git("apply", str(patch_path), cwd=worktree)
        _save_state(run_dir, "tests_running", fingerprint)
        test_log = run_tests(job, worktree)
        (run_dir / "tests.txt").write_text(test_log + "\n", encoding="utf-8")
        actual_diff = git("diff", "--no-ext-diff", cwd=worktree)
        (run_dir / "actual.diff").write_text(actual_diff, encoding="utf-8")

        _save_state(run_dir, "final_review", fingerprint)
        final_review = reviewer.chat(
            _review_prompt("apos testes", candidate.objective, evidence, actual_diff, test_log),
            temperature=0.05, num_ctx=12288, num_predict=1400,
        )
        (run_dir / "final_review.md").write_text(final_review + "\n", encoding="utf-8")
        status = "ready_for_human_review" if _approved(final_review) else "rejected"
        _save_state(run_dir, status, fingerprint, stage="final_review")
        print(f"{job.job_id}: {status}. Nenhuma mudanca aplicada ao projeto principal.")
    except requests.RequestException as exc:
        current = _read_json(state_path) if state_path.exists() else {}
        attempts = failures_before + 1
        status = "blocked_agents" if attempts >= 3 else "waiting_agents"
        _save_state(
            run_dir,
            status,
            fingerprint,
            error=f"{type(exc).__name__}: {exc}",
            agent_failures=attempts,
            resume_stage=current.get("status"),
            next_retry_at=time.time() + min(900, 60 * (2 ** (attempts - 1))),
        )
        print(f"{job.job_id}: {status}; tentativa {attempts}.")
    except Exception as exc:
        _save_state(run_dir, "failed", fingerprint, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _remove_worktree(worktree)


def _global_state() -> dict[str, Any]:
    return _read_json(GLOBAL_STATE) if GLOBAL_STATE.exists() else {"paused": False}


def set_paused(paused: bool) -> None:
    state = _global_state()
    state.update({
        "paused": paused,
        "stop_requested": False,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    _write_json(GLOBAL_STATE, state)
    print("Autopilot pausado." if paused else "Autopilot liberado.")


def request_stop() -> None:
    state = _global_state()
    state.update({
        "stop_requested": True,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    _write_json(GLOBAL_STATE, state)
    print("Parada solicitada; o watcher encerrara no proximo ciclo.")


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def queued_jobs() -> list[Path]:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(path for path in QUEUE_DIR.glob("*.json") if not path.name.startswith("_"))


def watch(interval: int) -> None:
    state = _global_state()
    previous_pid = state.get("watcher_pid")
    if previous_pid != os.getpid() and _pid_alive(previous_pid):
        raise RuntimeError(f"Ja existe um watcher ativo no processo {previous_pid}.")
    state.update({
        "watcher_pid": os.getpid(),
        "watcher_started_at": datetime.now().isoformat(timespec="seconds"),
        "stop_requested": False,
    })
    _write_json(GLOBAL_STATE, state)
    print("Autopilot observando a fila. Use --pause antes de usar a GPU para outra tarefa.")
    try:
        while True:
            state = _global_state()
            if state.get("stop_requested"):
                break
            if not state.get("paused", False):
                for path in queued_jobs():
                    try:
                        process(path)
                    except Exception as exc:
                        print(f"{path.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            time.sleep(interval)
    finally:
        state = _global_state()
        state.update({
            "watcher_pid": None,
            "watcher_stopped_at": datetime.now().isoformat(timespec="seconds"),
            "stop_requested": False,
        })
        _write_json(GLOBAL_STATE, state)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path, nargs="?", help="Job JSON para uma execucao")
    parser.add_argument("--watch", action="store_true", help="Observa ai_sprints/queue")
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--force", action="store_true")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pause", action="store_true")
    group.add_argument("--resume", action="store_true")
    group.add_argument("--stop", action="store_true")
    group.add_argument("--status", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.pause or args.resume:
        set_paused(args.pause)
        return
    if args.stop:
        request_stop()
        return
    if args.status:
        print(json.dumps(_global_state(), ensure_ascii=False, indent=2))
        return
    if args.watch:
        if not 10 <= args.interval <= 300:
            raise SystemExit("--interval deve ficar entre 10 e 300 segundos.")
        watch(args.interval)
        return
    if args.job is None:
        raise SystemExit("Informe um job, --watch, --pause, --resume, --stop ou --status.")
    process(args.job.resolve(), force=args.force)


if __name__ == "__main__":
    main()
