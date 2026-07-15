from __future__ import annotations

import subprocess
from pathlib import Path

from .document import DocumentError


class MemoryGit:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise DocumentError("memory_not_git_repo")
        return result

    def is_clean(self) -> bool:
        result = self._run("status", "--porcelain", "--untracked-files=all")
        return result.stdout.strip() == ""

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def current_branch(self) -> str:
        result = self._run("branch", "--show-current")
        branch = result.stdout.strip()
        if not branch:
            raise DocumentError("memory_detached")
        return branch

    def upstream(self) -> str | None:
        result = self._run(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False
        )
        if result.returncode != 0:
            return None
        value = result.stdout.strip()
        return value or None

    def fetch(self) -> None:
        self._run("fetch", "--prune")

    def can_fast_forward(self, upstream: str) -> bool:
        result = self._run("merge-base", "--is-ancestor", "HEAD", upstream, check=False)
        return result.returncode == 0

    def fast_forward(self, upstream: str) -> None:
        if not self.can_fast_forward(upstream):
            raise DocumentError("pull_not_fast_forward")
        result = self._run("merge", "--ff-only", upstream, check=False)
        if result.returncode != 0:
            raise DocumentError("pull_not_fast_forward")

    def commit(self, message: str) -> str | None:
        self._run("add", "-A")
        status = self._run("status", "--porcelain", "--untracked-files=all")
        if status.stdout.strip() == "":
            return None
        result = self._run("commit", "-m", message, check=False)
        if result.returncode != 0:
            raise DocumentError("memory_not_git_repo")
        return self.head()

    def push(self) -> None:
        result = self._run("push", check=False)
        if result.returncode != 0:
            raise DocumentError("push_failed")
