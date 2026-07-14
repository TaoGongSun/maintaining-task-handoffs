#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from handoff_core.document import DocumentError
from handoff_core.git import NotGitRepoError, repo_root
from handoff_core.service import HandoffService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="handoff")
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("checkpoint", "pause", "complete"):
        command = commands.add_parser(name)
        command.add_argument("--task-id", required=True)
        command.add_argument("--input", required=True, type=Path)
        command.add_argument("--harness", default="unknown")
        command.add_argument("--fresh-minutes", type=int, default=30)
    validate = commands.add_parser("validate")
    validate.add_argument("--task-id")
    validate.add_argument("--fresh-minutes", type=int, default=30)
    commands.add_parser("compliance")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repo_root(Path.cwd())
    except NotGitRepoError:
        print(json.dumps({"ok": False, "code": "not_git_repo"}))
        return 3
    service = HandoffService(root)
    try:
        if args.command == "checkpoint":
            result = service.checkpoint(
                args.task_id,
                args.input.read_text(encoding="utf-8"),
                args.harness,
                args.fresh_minutes,
            )
        elif args.command == "pause":
            result = service.pause(
                args.task_id,
                args.input.read_text(encoding="utf-8"),
                args.harness,
                args.fresh_minutes,
            )
        elif args.command == "validate":
            result = service.validate(args.task_id, args.fresh_minutes)
        elif args.command == "complete":
            result = service.complete(
                args.task_id,
                args.input.read_text(encoding="utf-8"),
                args.harness,
                args.fresh_minutes,
            )
        else:
            print(json.dumps(service.compliance(), sort_keys=True))
            return 0
    except DocumentError as error:
        print(json.dumps({"ok": False, "code": error.code}))
        return 4
    except (OSError, UnicodeError):
        print(json.dumps({"ok": False, "code": "io_error"}))
        return 5
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0 if result.ok else 4


if __name__ == "__main__":
    sys.exit(main())
