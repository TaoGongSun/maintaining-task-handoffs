#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from handoff_core.document import DocumentError
from handoff_core.git import NotGitRepoError, repo_root
from handoff_core.memory_service import MemoryService
from handoff_core.service import HandoffService
from handoff_core.task_service import TaskService


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

    task = commands.add_parser("task")
    task_commands = task.add_subparsers(dest="task_command", required=True)

    task_add = task_commands.add_parser("add")
    task_add.add_argument("--task-id", required=True)
    task_add.add_argument("--input", required=True, type=Path)
    task_add.add_argument("--timezone")

    task_update = task_commands.add_parser("update")
    task_update.add_argument("--task-id", required=True)
    task_update.add_argument("--input", required=True, type=Path)
    task_update.add_argument("--timezone")

    task_milestone = task_commands.add_parser("milestone")
    task_milestone.add_argument("--task-id", required=True)
    task_milestone.add_argument("--input", required=True, type=Path)
    task_milestone.add_argument("--summary", required=True)
    task_milestone.add_argument("--timezone")

    task_complete = task_commands.add_parser("complete")
    task_complete.add_argument("--task-id", required=True)
    task_complete.add_argument("--summary", required=True)
    task_complete.add_argument("--timezone")

    task_list = task_commands.add_parser("list")
    task_list.add_argument("--timezone")

    task_show = task_commands.add_parser("show")
    task_show.add_argument("--task-id", required=True)
    task_show.add_argument("--timezone")

    memory = commands.add_parser("memory")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    memory_init = memory_commands.add_parser("init")
    memory_init.add_argument("--path", required=True, type=Path)
    memory_commands.add_parser("status")
    memory_sync = memory_commands.add_parser("sync")
    memory_sync.add_argument("--no-push", action="store_true")

    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = repo_root(Path.cwd())
    except NotGitRepoError:
        print(json.dumps({"ok": False, "code": "not_git_repo"}))
        return 3

    try:
        if args.command == "task":
            service = TaskService(root, timezone_name=getattr(args, "timezone", None))
            if args.task_command == "add":
                result = service.add(args.task_id, args.input.read_text(encoding="utf-8"))
                print(json.dumps(result.to_dict(), sort_keys=True))
                return 0 if result.ok else 4
            if args.task_command == "update":
                result = service.update(args.task_id, args.input.read_text(encoding="utf-8"))
                print(json.dumps(result.to_dict(), sort_keys=True))
                return 0 if result.ok else 4
            if args.task_command == "milestone":
                result = service.milestone(
                    args.task_id,
                    args.input.read_text(encoding="utf-8"),
                    args.summary,
                )
                print(json.dumps(result.to_dict(), sort_keys=True))
                return 0 if result.ok else 4
            if args.task_command == "complete":
                result = service.complete(args.task_id, args.summary)
                print(json.dumps(result.to_dict(), sort_keys=True))
                return 0 if result.ok else 4
            if args.task_command == "list":
                print(service.list(), end="")
                return 0
            print(service.show(args.task_id), end="")
            return 0

        if args.command == "memory":
            service = MemoryService(root)
            if args.memory_command == "init":
                result = service.init(args.path)
            elif args.memory_command == "status":
                result = service.status()
            else:
                result = service.sync(push=not args.no_push)
            print(json.dumps(result.to_dict(), sort_keys=True))
            return 0 if result.ok else 4

        service = HandoffService(root)
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
