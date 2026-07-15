from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .activity import parse_activity
from .atomic import write_text
from .document import DocumentError, validate_task_id
from .project import parse_project_identity
from .task_document import parse_task_draft
from .task_service import TaskService

ROOT_FILES = ("project.json", "task-state.json")
TREE_DIRS = ("tasks", "history")
HISTORY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


@dataclass(frozen=True)
class Snapshot:
    project_id: str
    digest: str
    files: dict[str, bytes]


def snapshot_root(root: Path) -> Path:
    ai = root / ".ai"
    if ai.is_dir():
        return ai
    return root


def _reject_symlink(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise DocumentError("snapshot_symlink")


def _walk_components(base: Path, relative: str) -> Path:
    path = base
    _reject_symlink(path)
    for part in Path(relative).parts:
        if part in {"", ".", ".."}:
            raise DocumentError("invalid_snapshot")
        path = path / part
        _reject_symlink(path)
    return path


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def _hash_files(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        content = files[path]
        path_bytes = path.encode("utf-8")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except (OSError, UnicodeError) as error:
        raise DocumentError("invalid_snapshot") from error


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentError("invalid_snapshot") from error
    if not isinstance(value, dict):
        raise DocumentError("invalid_snapshot")
    return value


def _validate_registry(registry: dict[str, object]) -> dict[str, dict[str, object]]:
    if registry.get("version") != 1:
        raise DocumentError("invalid_snapshot")
    tasks = registry.get("tasks")
    if not isinstance(tasks, dict):
        raise DocumentError("invalid_snapshot")
    result: dict[str, dict[str, object]] = {}
    for task_id, entry in tasks.items():
        if not isinstance(task_id, str) or not isinstance(entry, dict):
            raise DocumentError("invalid_snapshot")
        try:
            validate_task_id(task_id)
        except DocumentError as error:
            raise DocumentError("invalid_snapshot") from error
        if entry.get("status") not in {"todo", "in-progress", "blocked"}:
            raise DocumentError("invalid_snapshot")
        if not isinstance(entry.get("created"), str) or not isinstance(entry.get("updated"), str):
            raise DocumentError("invalid_snapshot")
        result[task_id] = entry
    return result


def _strip_timestamps(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not line.startswith("Created:") and not line.startswith("Updated:")
    ]
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def load_snapshot(root: Path) -> Snapshot:
    base = snapshot_root(root)
    _reject_symlink(base)
    if base.name == ".ai":
        _reject_symlink(root / ".ai")

    files: dict[str, bytes] = {}
    project_path = _walk_components(base, "project.json")
    if not project_path.is_file():
        raise DocumentError("invalid_snapshot")
    identity = parse_project_identity(_load_json(project_path))
    files["project.json"] = _canonical_json_bytes(
        {
            "version": 1,
            "id": identity.project_id,
            "name": identity.name,
            "remote": identity.remote,
        }
    )

    state_path = _walk_components(base, "task-state.json")
    if not state_path.is_file():
        raise DocumentError("invalid_snapshot")
    registry = _load_json(state_path)
    tasks = _validate_registry(registry)
    files["task-state.json"] = _canonical_json_bytes(
        {
            "version": 1,
            "tasks": {
                task_id: {
                    "status": entry["status"],
                    "created": entry["created"],
                    "updated": entry["updated"],
                }
                for task_id, entry in sorted(tasks.items())
            },
        }
    )

    tasks_dir = base / "tasks"
    if tasks_dir.exists():
        _reject_symlink(tasks_dir)
        if not tasks_dir.is_dir():
            raise DocumentError("invalid_snapshot")
        seen: set[str] = set()
        for path in sorted(tasks_dir.iterdir()):
            _reject_symlink(path)
            if not path.is_file() or not path.name.endswith(".md"):
                raise DocumentError("invalid_snapshot")
            task_id = path.name[:-3]
            try:
                validate_task_id(task_id)
            except DocumentError as error:
                raise DocumentError("invalid_snapshot") from error
            if task_id not in tasks:
                raise DocumentError("invalid_snapshot")
            text = path.read_text(encoding="utf-8")
            draft = parse_task_draft(_strip_timestamps(text), task_id)
            if draft.status != tasks[task_id]["status"]:
                raise DocumentError("invalid_snapshot")
            files[f"tasks/{path.name}"] = text.encode("utf-8")
            seen.add(task_id)
        if seen != set(tasks):
            raise DocumentError("invalid_snapshot")
    elif tasks:
        raise DocumentError("invalid_snapshot")

    history_dir = base / "history"
    if history_dir.exists():
        _reject_symlink(history_dir)
        if not history_dir.is_dir():
            raise DocumentError("invalid_snapshot")
        for path in sorted(history_dir.iterdir()):
            _reject_symlink(path)
            if not path.is_file() or not HISTORY_NAME.fullmatch(path.name):
                raise DocumentError("invalid_snapshot")
            day = path.name[:-3]
            text = path.read_text(encoding="utf-8")
            events = parse_activity(text)
            for event in events:
                if event.project_id != identity.project_id:
                    raise DocumentError("invalid_snapshot")
                try:
                    event_day = datetime.fromisoformat(event.timestamp).date().isoformat()
                except ValueError as error:
                    raise DocumentError("invalid_snapshot") from error
                if event_day != day:
                    raise DocumentError("invalid_snapshot")
            files[f"history/{path.name}"] = text.encode("utf-8")

    return Snapshot(identity.project_id, _hash_files(files), files)


def stage_snapshot(snapshot: Snapshot, destination: Path) -> None:
    if destination.exists():
        raise DocumentError("invalid_snapshot")
    destination.mkdir(parents=True, exist_ok=False)
    for relative, content in snapshot.files.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, content.decode("utf-8"), mode=0o600)
    loaded = load_snapshot(destination)
    if loaded.digest != snapshot.digest or loaded.project_id != snapshot.project_id:
        raise DocumentError("invalid_snapshot")


def install_snapshot(snapshot: Snapshot, project_root: Path) -> None:
    ai = project_root / ".ai"
    ai.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".memory-stage-", dir=ai) as staged_name:
        staged = Path(staged_name)
        # TemporaryDirectory already created the directory; stage into a child.
        target = staged / "snapshot"
        stage_snapshot(snapshot, target)
        validated = load_snapshot(target)
        TaskService(project_root).install_snapshot(validated.files)
