from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .atomic import write_json
from .document import DocumentError
from .git import repo_root
from .memory_git import MemoryGit
from .project import load_or_create_project


@dataclass(frozen=True)
class MemoryConfig:
    version: int
    memory_path: Path


@dataclass(frozen=True)
class MemoryResult:
    ok: bool
    code: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"ok": self.ok, "code": self.code}
        if self.details:
            payload["details"] = self.details
        return payload


class MemoryService:
    def __init__(self, cwd: Path, config_home: Path | None = None) -> None:
        self.root = repo_root(cwd)
        if config_home is None:
            xdg = os.environ.get("XDG_CONFIG_HOME")
            config_home = Path(xdg) if xdg else Path.home() / ".config"
        self.config_home = Path(config_home)
        self.config_path = self.config_home / "maintaining-task-handoffs" / "config.json"

    def _load_config(self) -> MemoryConfig:
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise DocumentError("memory_not_configured") from error
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise DocumentError("memory_not_configured") from error
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise DocumentError("memory_not_configured")
        path_value = raw.get("memory_path")
        if not isinstance(path_value, str) or not path_value.strip():
            raise DocumentError("memory_not_configured")
        return MemoryConfig(1, Path(path_value).expanduser().resolve())

    def _write_config(self, memory_path: Path) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            self.config_path,
            {"version": 1, "memory_path": str(memory_path.resolve())},
        )

    def _require_git_repo(self, path: Path) -> MemoryGit:
        if not path.is_dir() or not (path / ".git").exists():
            # Also accept worktrees where .git is a file.
            git_meta = path / ".git"
            if not path.is_dir() or not git_meta.exists():
                raise DocumentError("memory_not_git_repo")
        git = MemoryGit(path)
        try:
            git.head()
            git.current_branch()
        except DocumentError:
            raise
        except Exception as error:
            raise DocumentError("memory_not_git_repo") from error
        return git

    def init(self, path: Path) -> MemoryResult:
        resolved = path.expanduser().resolve()
        self._require_git_repo(resolved)
        self._write_config(resolved)
        return MemoryResult(True, "memory_initialized", {"memory_path": str(resolved)})

    def status(self) -> MemoryResult:
        config = self._load_config()
        git = self._require_git_repo(config.memory_path)
        identity = load_or_create_project(self.root)
        project_dir = config.memory_path / "projects" / identity.project_id
        upstream = git.upstream()
        details = {
            "memory_path": str(config.memory_path),
            "dirty": not git.is_clean(),
            "branch": git.current_branch(),
            "head": git.head(),
            "has_upstream": upstream is not None,
            "upstream": upstream,
            "project_id": identity.project_id,
            "project_present": project_dir.is_dir(),
        }
        return MemoryResult(True, "memory_status", details)
