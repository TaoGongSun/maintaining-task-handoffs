from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .activity import ActivityEvent, merge_event, parse_activity, render_activity
from .atomic import write_json
from .document import DocumentError
from .git import repo_root
from .memory_git import MemoryGit
from .project import load_or_create_project, parse_project_identity
from .snapshot import load_snapshot
from .task_document import TaskDraft, parse_task_draft, render_task_index


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


def _strip_timestamps(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith("Created:") and not line.startswith("Updated:")
    ]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _read_sync_metadata(project_dir: Path) -> dict[str, object]:
    path = project_dir / "sync.json"
    if not path.is_file():
        return {"synced": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"synced": ""}
    if not isinstance(raw, dict):
        return {"synced": ""}
    synced = raw.get("synced")
    return {"synced": synced if isinstance(synced, str) else ""}


def _global_task_index(
    entries: list[tuple[str, str, dict[str, object], TaskDraft]],
) -> str:
    labels = (("in-progress", "In progress"), ("todo", "Todo"), ("blocked", "Blocked"))
    lines = ["# All project tasks", ""]
    for status, heading in labels:
        lines.append(f"## {heading}")
        matched = [
            item
            for item in entries
            if item[2].get("status") == status
        ]
        matched.sort(
            key=lambda item: (
                item[1],
                str(item[2].get("updated", "")),
                item[3].task_id,
            ),
            reverse=False,
        )
        # project name ascending; within same project updated descending then task id
        matched.sort(key=lambda item: item[1])
        by_project: dict[str, list[tuple[str, str, dict[str, object], TaskDraft]]] = {}
        for item in matched:
            by_project.setdefault(item[1], []).append(item)
        ordered: list[tuple[str, str, dict[str, object], TaskDraft]] = []
        for name in sorted(by_project):
            group = by_project[name]
            group.sort(
                key=lambda item: (str(item[2].get("updated", "")), item[3].task_id),
                reverse=True,
            )
            ordered.extend(group)
        if not ordered:
            lines.append("- None.")
        else:
            for project_id, _name, _entry, draft in ordered:
                action = draft.sections["Next action"].removeprefix("- ").strip()
                prefix = "阻塞" if status == "blocked" else "下一步"
                lines.append(
                    f"- [{project_id}/{draft.task_id}](projects/{project_id}/tasks/{draft.task_id}.md)"
                    f" — {draft.title} — {prefix}：{action}"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def rebuild_memory_views(memory_root: Path) -> dict[str, str]:
    projects_root = memory_root / "projects"
    views: dict[str, str] = {}
    registry_projects: dict[str, dict[str, object]] = {}
    index_entries: list[tuple[str, str, dict[str, object], TaskDraft]] = []
    project_rows: list[tuple[str, str, str]] = []
    merged_events: list[ActivityEvent] = []
    seen_ids: dict[str, str] = {}

    if projects_root.exists():
        if projects_root.is_symlink():
            raise DocumentError("snapshot_symlink")
        if not projects_root.is_dir():
            raise DocumentError("invalid_snapshot")
        for entry in sorted(projects_root.iterdir()):
            if entry.is_symlink():
                raise DocumentError("snapshot_symlink")
            if not entry.is_dir():
                continue
            snapshot = load_snapshot(entry)
            if entry.name != snapshot.project_id:
                raise DocumentError("project_id_conflict")
            if snapshot.project_id in seen_ids:
                raise DocumentError("project_id_conflict")
            seen_ids[snapshot.project_id] = entry.name

            identity = parse_project_identity(
                json.loads(snapshot.files["project.json"].decode("utf-8"))
            )
            registry = json.loads(snapshot.files["task-state.json"].decode("utf-8"))
            tasks = registry["tasks"]
            assert isinstance(tasks, dict)
            documents: dict[str, TaskDraft] = {}
            for relative, content in snapshot.files.items():
                if not relative.startswith("tasks/"):
                    continue
                task_id = Path(relative).stem
                text = content.decode("utf-8")
                draft = parse_task_draft(_strip_timestamps(text), task_id)
                documents[task_id] = draft
                index_entries.append(
                    (snapshot.project_id, identity.name, tasks[task_id], draft)
                )
            local_index = render_task_index(tasks, documents)
            views[f"projects/{snapshot.project_id}/TASKS.md"] = local_index

            sync_meta = _read_sync_metadata(entry)
            synced = str(sync_meta.get("synced", ""))
            registry_projects[snapshot.project_id] = {
                "name": identity.name,
                "snapshot_hash": snapshot.digest,
                "synced": synced,
            }
            project_rows.append((identity.name, snapshot.project_id, synced))

            for relative, content in snapshot.files.items():
                if not relative.startswith("history/"):
                    continue
                for event in parse_activity(content.decode("utf-8")):
                    merged_events = merge_event(merged_events, event)

    registry = {"version": 1, "projects": dict(sorted(registry_projects.items()))}
    views["registry.json"] = json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    views["TASKS.md"] = _global_task_index(index_entries)

    project_lines = ["# Projects", ""]
    for name, project_id, synced in sorted(project_rows, key=lambda item: (item[0], item[1])):
        project_lines.append(
            f"- [{name}](projects/{project_id}/TASKS.md) — `{project_id}` — synced: {synced or 'unknown'}"
        )
    if len(project_lines) == 2:
        project_lines.append("- None.")
    views["PROJECTS.md"] = "\n".join(project_lines).rstrip() + "\n"

    by_day: dict[str, list[ActivityEvent]] = {}
    for event in merged_events:
        day = datetime.fromisoformat(event.timestamp).date().isoformat()
        by_day.setdefault(day, []).append(event)
    for day, events in sorted(by_day.items()):
        views[f"history/{day}.md"] = render_activity(events, date.fromisoformat(day))

    return views


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
