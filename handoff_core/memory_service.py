from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from .activity import ActivityEvent, merge_event, parse_activity, render_activity
from .atomic import write_json, write_text
from .document import DocumentError
from .git import repo_root
from .memory_git import MemoryGit
from .project import load_or_create_project, parse_project_identity
from .snapshot import Snapshot, load_snapshot, stage_snapshot
from .task_document import TaskDraft, parse_task_draft, render_task_index
from .task_service import TaskService


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

    def _memory_sync_path(self) -> Path:
        return self.root / ".ai" / "memory-sync.json"

    def _load_base(self, project_id: str) -> dict[str, object] | None:
        path = self._memory_sync_path()
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return None
        if raw.get("project_id") != project_id:
            return None
        if not isinstance(raw.get("base_hash"), str):
            return None
        return raw

    def _write_base(self, project_id: str, base_hash: str, memory_commit: str) -> None:
        write_json(
            self._memory_sync_path(),
            {
                "version": 1,
                "project_id": project_id,
                "base_hash": base_hash,
                "memory_commit": memory_commit,
            },
        )

    def _preflight(self, git: MemoryGit) -> None:
        if not git.is_clean():
            raise DocumentError("memory_dirty")
        upstream = git.upstream()
        if upstream is not None:
            git.fetch()
            if not git.can_fast_forward(upstream):
                raise DocumentError("pull_not_fast_forward")
            git.fast_forward(upstream)
            if not git.is_clean():
                raise DocumentError("memory_dirty")

    def _memory_snapshot(self, memory_root: Path, project_id: str) -> Snapshot | None:
        project_dir = memory_root / "projects" / project_id
        if not project_dir.is_dir():
            return None
        return load_snapshot(project_dir)

    def _apply_memory_files(
        self, memory_root: Path, desired: dict[str, str | None]
    ) -> None:
        manifest_path = memory_root / ".memory-transaction.json"
        snapshots: dict[str, str | None] = {}
        for relative in desired:
            path = memory_root / relative
            if path.is_symlink():
                raise DocumentError("snapshot_symlink")
            if path.is_file():
                snapshots[relative] = path.read_text(encoding="utf-8")
            else:
                snapshots[relative] = None
        write_json(manifest_path, {"version": 1, "files": desired})
        try:
            for relative, content in desired.items():
                path = memory_root / relative
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    write_text(path, content)
        except Exception:
            for relative, content in snapshots.items():
                path = memory_root / relative
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    write_text(path, content)
            manifest_path.unlink(missing_ok=True)
            raise
        manifest_path.unlink(missing_ok=True)

    def _upload(
        self,
        git: MemoryGit,
        memory_root: Path,
        snapshot: Snapshot,
        push: bool,
    ) -> MemoryResult:
        project_id = snapshot.project_id
        project_prefix = f"projects/{project_id}"
        with tempfile.TemporaryDirectory(prefix="memory-stage-") as staged:
            stage_root = Path(staged) / "snapshot"
            stage_snapshot(snapshot, stage_root)
            desired: dict[str, str | None] = {}
            for relative, content in snapshot.files.items():
                desired[f"{project_prefix}/{relative}"] = content.decode("utf-8")

            synced = datetime.now(timezone.utc).astimezone().isoformat()
            sync_meta = {
                "version": 1,
                "snapshot_hash": snapshot.digest,
                "synced": synced,
                "source_repo": str(self.root),
            }
            desired[f"{project_prefix}/sync.json"] = (
                json.dumps(sync_meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )

            mirror = Path(staged) / "mirror"
            if (memory_root / "projects").is_dir():
                shutil.copytree(memory_root / "projects", mirror / "projects")
            else:
                (mirror / "projects").mkdir(parents=True)
            target_project = mirror / "projects" / project_id
            if target_project.exists():
                shutil.rmtree(target_project)
            shutil.copytree(stage_root, target_project)
            write_json(target_project / "sync.json", sync_meta)

            views = rebuild_memory_views(mirror)
            for relative, content in views.items():
                desired[relative] = content

            history_dir = memory_root / "history"
            if history_dir.is_dir():
                for path in history_dir.glob("*.md"):
                    key = f"history/{path.name}"
                    if key not in desired:
                        desired[key] = None

            existing_project = memory_root / "projects" / project_id
            if existing_project.is_dir():
                for sub in ("tasks", "history"):
                    directory = existing_project / sub
                    if directory.is_dir():
                        for path in directory.glob("*"):
                            key = f"{project_prefix}/{sub}/{path.name}"
                            if key not in desired:
                                desired[key] = None

            self._apply_memory_files(memory_root, desired)
            (memory_root / project_prefix / "tasks").mkdir(parents=True, exist_ok=True)
            (memory_root / project_prefix / "history").mkdir(parents=True, exist_ok=True)

        commit = git.commit(f"Sync project memory for {date.today().isoformat()}")
        head = git.head()
        self._write_base(project_id, snapshot.digest, head)
        details: dict[str, object] = {
            "project_id": project_id,
            "snapshot_hash": snapshot.digest,
            "memory_commit": head,
            "committed": commit is not None,
            "remote_synced": False,
        }
        if push and git.upstream() is not None:
            try:
                git.push()
                details["remote_synced"] = True
            except DocumentError as error:
                if error.code == "push_failed":
                    details["remote_synced"] = False
                    return MemoryResult(False, "push_failed", details)
                raise
        return MemoryResult(True, "memory_uploaded", details)

    def _download(self, memory_root: Path, project_id: str, snapshot: Snapshot) -> MemoryResult:
        # Validate already done via load_snapshot.
        TaskService(self.root).install_snapshot(snapshot.files)
        head = MemoryGit(memory_root).head()
        self._write_base(project_id, snapshot.digest, head)
        return MemoryResult(
            True,
            "memory_downloaded",
            {
                "project_id": project_id,
                "snapshot_hash": snapshot.digest,
                "memory_commit": head,
            },
        )

    def _ensure_local_snapshot_ready(self) -> None:
        identity = load_or_create_project(self.root)
        state_path = self.root / ".ai" / "task-state.json"
        if not state_path.is_file():
            write_json(state_path, {"version": 1, "tasks": {}})
        _ = identity

    def sync(self, push: bool = True) -> MemoryResult:
        config = self._load_config()
        git = self._require_git_repo(config.memory_path)
        identity = load_or_create_project(self.root)
        project_id = identity.project_id

        transaction = self.root / ".ai" / "task-transaction.json"
        if transaction.is_file():
            raise DocumentError("invalid_transaction")

        self._preflight(git)
        self._ensure_local_snapshot_ready()
        local = load_snapshot(self.root)
        if local.project_id != project_id:
            raise DocumentError("invalid_project")
        memory = self._memory_snapshot(config.memory_path, project_id)
        base = self._load_base(project_id)
        base_hash = str(base["base_hash"]) if base is not None else None
        memory_hash = memory.digest if memory is not None else None
        local_tasks = json.loads(local.files["task-state.json"].decode("utf-8")).get("tasks", {})
        if (
            base_hash is None
            and memory_hash is not None
            and local.digest != memory_hash
            and isinstance(local_tasks, dict)
            and not local_tasks
        ):
            # New device with empty local tasks may bootstrap from memory.
            direction = "download"
        else:
            direction = sync_direction(local.digest, memory_hash, base_hash)

        if direction == "current":
            head = git.head()
            if base is None or base.get("base_hash") != local.digest:
                self._write_base(project_id, local.digest, head)
            return MemoryResult(
                True,
                "memory_current",
                {
                    "project_id": project_id,
                    "snapshot_hash": local.digest,
                    "memory_commit": head,
                },
            )
        if direction == "upload":
            return self._upload(git, config.memory_path, local, push)
        assert memory is not None
        return self._download(config.memory_path, project_id, memory)


def sync_direction(local: str, memory: str | None, base: str | None) -> str:
    if memory is None and base is None:
        return "upload"
    if memory is None and base is not None:
        # Memory lost the project while we still have a base; treat as upload if local matches base? stop.
        raise DocumentError("memory_diverged")
    if local == memory:
        return "current"
    if base is None and memory is not None and local != memory:
        raise DocumentError("memory_diverged")
    if base is not None and memory == base and local != base:
        return "upload"
    if base is not None and local == base and memory != base:
        return "download"
    raise DocumentError("memory_diverged")
