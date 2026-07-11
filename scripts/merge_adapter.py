#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path


START = "<!-- maintaining-task-handoffs:start -->"
END = "<!-- maintaining-task-handoffs:end -->"
MANAGED_BLOCK = re.compile(
    rf"(?ms)^{re.escape(START)}\n.*?^{re.escape(END)}\n?"
)


def merge(existing: str, block: str) -> str:
    matches = list(MANAGED_BLOCK.finditer(existing))
    if len(matches) > 1:
        raise ValueError("multiple managed adapter blocks")
    rendered = block.strip() + "\n"
    if matches:
        match = matches[0]
        return existing[: match.start()] + rendered + existing[match.end() :]
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + rendered


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(content)
        temp = Path(handle.name)
    temp.replace(path)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: merge_adapter.py TARGET SOURCE", file=sys.stderr)
        return 2
    target, source = map(Path, sys.argv[1:])
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    block = source.read_text(encoding="utf-8")
    try:
        write(target, merge(existing, block))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
