"""Participação das sessões do editor no mesmo diário usado pelo painel."""

import argparse
import json
from pathlib import Path

from .store import CollaborationStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=str(Path.cwd()))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    sub.add_parser("log")
    for name in ("claim", "finish", "message", "confirm"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--agent", choices=("codex", "opus"), required=True)
        cmd.add_argument("--id", required=True, help="task_id para claim/finish; idea_id para message/confirm")
        if name != "claim":
            cmd.add_argument("--text", required=True)
        if name == "finish":
            cmd.add_argument("--evidence", required=True)
            cmd.add_argument("--failed", action="store_true")
        if name == "confirm":
            cmd.add_argument("--session", required=True)
            cmd.add_argument("--model", required=True)
    args = parser.parse_args()
    store = CollaborationStore(args.project)
    if args.command == "snapshot":
        result = store.snapshot()
    elif args.command == "log":
        result = {"path": str(store.export_markdown())}
    elif args.command == "claim":
        result = store.claim(args.id, args.agent)
    elif args.command == "finish":
        result = store.finish(args.id, args.agent, summary=args.text,
                              evidence=args.evidence, success=not args.failed)
    elif args.command == "confirm":
        result = store.confirm(args.id, args.agent, args.text, args.session, args.model)
    else:
        store.message(args.id, args.agent, args.text)
        result = {"ok": True}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
