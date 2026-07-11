from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


class NotGitRepoError(RuntimeError):
    pass


def repo_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise NotGitRepoError(str(cwd))
    return Path(result.stdout.strip()).resolve()


@dataclass(frozen=True)
class GitMetadata:
    repo: str
    branch: str
    head: str
    dirty: bool
    dirty_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise NotGitRepoError(str(root))
    return result.stdout.rstrip("\n")


def git_metadata(cwd: Path) -> GitMetadata:
    root = repo_root(cwd)
    branch = _git(root, "branch", "--show-current") or "(detached)"
    head = _git(root, "rev-parse", "HEAD")
    changed = subprocess.run(
        ["git", "diff", "HEAD", "--name-only", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True,
    ).stdout
    paths = sorted(set((changed + untracked).decode("utf-8", "surrogateescape").split("\0")))
    relevant: list[tuple[str, str]] = []
    for path in paths:
        if not path:
            continue
        if path.startswith(".ai/") or path == ".ai":
            continue
        candidate = root / path
        content_hash = "missing"
        if candidate.is_symlink():
            content_hash = hashlib.sha256(os.readlink(candidate).encode()).hexdigest()
        elif candidate.is_file():
            content_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        relevant.append((path, content_hash))
    fingerprint = hashlib.sha256(
        json.dumps(relevant, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return GitMetadata(str(root), branch, head, bool(relevant), fingerprint)
