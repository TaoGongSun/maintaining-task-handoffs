#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


MARKER = "maintaining-task-handoffs"


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("hook config must be a JSON object")
    return value


def is_managed(hook: dict) -> bool:
    return MARKER in str(hook.get("command", ""))


def remove_managed(config: dict) -> dict:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return config
    for event in list(hooks):
        groups = hooks[event]
        if isinstance(groups, list):
            retained_groups = []
            for group in groups:
                group_hooks = group.get("hooks")
                if not isinstance(group_hooks, list):
                    retained_groups.append(group)
                    continue
                group["hooks"] = [hook for hook in group_hooks if not is_managed(hook)]
                if group["hooks"]:
                    retained_groups.append(group)
            hooks[event] = retained_groups
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        config.pop("hooks", None)
    return config


def write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "remove"))
    parser.add_argument("target", type=Path)
    parser.add_argument("source", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "remove" and not args.target.exists():
        return 0
    config = remove_managed(load(args.target))
    if args.action == "install":
        if args.source is None:
            parser.error("install requires source")
        source = load(args.source).get("hooks", {})
        target_hooks = config.setdefault("hooks", {})
        for event, groups in source.items():
            target_hooks.setdefault(event, []).extend(groups)
    write(args.target, config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
