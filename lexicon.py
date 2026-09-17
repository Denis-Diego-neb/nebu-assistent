"""Vocabulário persistente e ensinável da Nebula."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

LEXICON_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Nebula" / "lexicon.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(LEXICON_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def learn(term: str, meaning: str) -> None:
    term = " ".join(term.lower().strip(" .,:;!?\"'").split())
    meaning = meaning.strip()
    if not term or not meaning:
        raise ValueError("Termo e significado são obrigatórios")
    words = _load()
    words[term] = meaning
    LEXICON_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEXICON_FILE.write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8")


def lookup(term: str) -> str | None:
    clean = " ".join(term.lower().strip(" .,:;!?\"'").split())
    return _load().get(clean)


def parse_entry(line: str) -> tuple[str, str] | None:
    """Aceita linhas como ``termo: definição`` ou ``termo — definição``."""
    match = re.match(r"^\s*([^:–—\t]{1,100})\s*(?::|–|—|\t)\s*(.{2,})$", line)
    return (match.group(1), match.group(2)) if match else None


def import_dictionary(path: str) -> int:
    count = 0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        entry = parse_entry(line)
        if entry:
            learn(*entry)
            count += 1
    return count
