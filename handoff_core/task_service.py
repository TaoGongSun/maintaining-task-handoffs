from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .activity import ActivityEvent, merge_event, parse_activity, render_activity
from .atomic import write_json, write_text
from .document import DocumentError, scan_secrets, validate_task_id
from .git import repo_root
from .project import load_or_create_project
from .task_document import TaskDraft, parse_task_draft, render_task, render_task_index

ENTRY_TEXT = """# Project memory

- [未完成待辦](TASKS.md)
- [長任務交接](HANDOFF.md)
- [每日活動紀錄](history/)
"""

EMPTY_REGISTRY: dict[str, object] = {"version": 1, "tasks": {}}
ALLOWED_TOP_LEVEL = frozenset(
    {"task-state.json", "TASKS.md", "README.md", "project.json", "memory-sync.json"}
)
ALLOWED_DIRS = frozenset({"tasks", "history"})


@dataclass(frozen=True)
class TaskResult:
    ok: bool
    code: str
    task_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"ok": self.ok, "code": self.code}
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        return payload


class TaskService:
    def __init__(
        self,
        cwd: Path,
        now: Callable[[], datetime] | None = None,
        timezone_name: str | None = None,
    ) -> None:
        self.root = repo_root(cwd)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.tzinfo = self._resolve_timezone(timezone_name)
        self.ai = self.root / ".ai"
        self.tasks_dir = self.ai / "tasks"
        self.state_path = self.ai / "task-state.json"
        self.index_path = self.ai / "TASKS.md"
        self.entry_path = self.ai / "README.md"
        self.transaction_path = self.ai / "task-transaction.json"
        self.history_dir = self.ai / "history"
        self._recover_transaction()

    def _resolve_timezone(self, timezone_name: str | None):
        if timezone_name:
            try:
                return ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as error:
                raise DocumentError("invalid_timezone", timezone_name) from error
        return self.now().astimezone().tzinfo or timezone.utc

    def _current_time(self) -> datetime:
        moment = self.now()
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self.tzinfo)
        return moment.astimezone(self.tzinfo)

    def _timestamp(self) -> str:
        return self._current_time().isoformat()

    def _local_day(self) -> str:
        return self._current_time().date().isoformat()

    def _task_relative(self, task_id: str) -> str:
        validate_task_id(task_id)
        return f".ai/tasks/{task_id}.md"

    def _history_relative(self, day: str | None = None) -> str:
        return f".ai/history/{day or self._local_day()}.md"

    def _read_json(self, path: Path) -> dict[str, object] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeError):
            return None
        return value if isinstance(value, dict) else None

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError, UnicodeError):
            return None

    def _registry(self) -> dict[str, object]:
        state = self._read_json(self.state_path)
        if state is None:
            return {"version": 1, "tasks": {}}
        self._validate_registry(state)
        return state

    @staticmethod
    def _validate_registry(registry: dict[str, object]) -> None:
        if registry.get("version") != 1:
            raise DocumentError("invalid_state")
        tasks = registry.get("tasks")
        if not isinstance(tasks, dict):
            raise DocumentError("invalid_state")
        for task_id, entry in tasks.items():
            if not isinstance(task_id, str) or not isinstance(entry, dict):
                raise DocumentError("invalid_state")
            try:
                validate_task_id(task_id)
            except DocumentError as error:
                raise DocumentError("invalid_state") from error
            if entry.get("status") not in {"todo", "in-progress", "blocked"}:
                raise DocumentError("invalid_state")
            if not isinstance(entry.get("created"), str) or not isinstance(entry.get("updated"), str):
                raise DocumentError("invalid_state")

    def _load_documents(self, tasks: dict[str, dict[str, object]]) -> dict[str, TaskDraft]:
        documents: dict[str, TaskDraft] = {}
        for task_id in tasks:
            path = self.root / self._task_relative(task_id)
            text = self._read_text(path)
            if text is None:
                raise DocumentError("task_missing", task_id)
            documents[task_id] = parse_task_draft(self._strip_timestamps(text), task_id)
        return documents

    @staticmethod
    def _strip_timestamps(text: str) -> str:
        lines = [
            line
            for line in text.splitlines()
            if not line.startswith("Created:") and not line.startswith("Updated:")
        ]
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")

    def _json_text(self, value: dict[str, object]) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _validate_relative(self, relative: str) -> Path:
        if not relative.startswith(".ai/") or relative != relative.replace("\\", "/"):
            raise DocumentError("invalid_path")
        parts = Path(relative).parts
        if ".." in parts or parts[0] != ".ai":
            raise DocumentError("invalid_path")
        remainder = parts[1:]
        if not remainder:
            raise DocumentError("invalid_path")
        if len(remainder) == 1:
            if remainder[0] not in ALLOWED_TOP_LEVEL:
                raise DocumentError("invalid_path")
        elif len(remainder) == 2:
            directory, name = remainder
            if directory not in ALLOWED_DIRS or not name or name in {".", ".."}:
                raise DocumentError("invalid_path")
            if directory == "tasks":
                if not name.endswith(".md"):
                    raise DocumentError("invalid_path")
                validate_task_id(name[:-3])
            elif directory == "history":
                if not name.endswith(".md"):
                    raise DocumentError("invalid_path")
        else:
            raise DocumentError("invalid_path")

        path = self.root
        for part in parts:
            path = path / part
            if path.exists() and path.is_symlink():
                raise DocumentError("invalid_path")
        return self.root / relative

    def _write_target(self, relative: str, content: str | None) -> None:
        path = self._validate_relative(relative)
        if content is None:
            path.unlink(missing_ok=True)
            return
        write_text(path, content)

    def _apply_transaction(self, transaction: dict[str, object]) -> None:
        files = transaction.get("files")
        if transaction.get("version") != 1 or not isinstance(files, dict):
            raise DocumentError("invalid_transaction")
        snapshots: dict[str, str | None] = {}
        for relative, content in files.items():
            if not isinstance(relative, str) or not (content is None or isinstance(content, str)):
                raise DocumentError("invalid_transaction")
            path = self._validate_relative(relative)
            snapshots[relative] = self._read_text(path)
        try:
            for relative, content in files.items():
                assert content is None or isinstance(content, str)
                self._write_target(relative, content)
        except Exception:
            for relative, content in snapshots.items():
                self._write_target(relative, content)
            self.transaction_path.unlink(missing_ok=True)
            raise

    def _commit_transaction(self, files: dict[str, str | None]) -> None:
        for relative in files:
            self._validate_relative(relative)
        transaction: dict[str, object] = {"version": 1, "files": files}
        write_json(self.transaction_path, transaction)
        self._apply_transaction(transaction)
        self.transaction_path.unlink(missing_ok=True)

    def _recover_transaction(self) -> None:
        if not self.transaction_path.is_file():
            return
        try:
            transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(transaction, dict) or transaction.get("version") != 1:
            return
        try:
            self._apply_transaction(transaction)
            self.transaction_path.unlink(missing_ok=True)
        except (DocumentError, OSError, UnicodeError):
            return

    def _build_index(
        self, tasks: dict[str, dict[str, object]], documents: dict[str, TaskDraft]
    ) -> str:
        return render_task_index(tasks, documents)

    def _base_files(
        self,
        registry: dict[str, object],
        documents: dict[str, TaskDraft],
        task_files: dict[str, str | None],
        history_relative: str | None = None,
        history_text: str | None = None,
    ) -> dict[str, str | None]:
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        files: dict[str, str | None] = {
            ".ai/task-state.json": self._json_text(registry),
            ".ai/TASKS.md": self._build_index(tasks, documents),
            ".ai/README.md": ENTRY_TEXT,
        }
        files.update(task_files)
        if history_relative is not None:
            files[history_relative] = history_text
        return files

    def add(self, task_id: str, text: str) -> TaskResult:
        validate_task_id(task_id)
        draft = parse_task_draft(text, task_id)
        load_or_create_project(self.root)
        registry = self._registry()
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        if task_id in tasks:
            raise DocumentError("task_exists")
        timestamp = self._timestamp()
        tasks[task_id] = {
            "status": draft.status,
            "created": timestamp,
            "updated": timestamp,
        }
        documents = self._load_documents({key: value for key, value in tasks.items() if key != task_id})
        documents[task_id] = draft
        rendered = render_task(draft, timestamp, timestamp)
        self._commit_transaction(
            self._base_files(registry, documents, {self._task_relative(task_id): rendered})
        )
        return TaskResult(True, "task_added", task_id)

    def update(self, task_id: str, text: str) -> TaskResult:
        validate_task_id(task_id)
        draft = parse_task_draft(text, task_id)
        registry = self._registry()
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        entry = tasks.get(task_id)
        if not isinstance(entry, dict):
            raise DocumentError("task_missing")
        created = entry["created"]
        assert isinstance(created, str)
        updated = self._timestamp()
        tasks[task_id] = {
            "status": draft.status,
            "created": created,
            "updated": updated,
        }
        documents = self._load_documents({key: value for key, value in tasks.items() if key != task_id})
        documents[task_id] = draft
        rendered = render_task(draft, created, updated)
        self._commit_transaction(
            self._base_files(registry, documents, {self._task_relative(task_id): rendered})
        )
        return TaskResult(True, "task_updated", task_id)

    def list(self) -> str:
        existing = self._read_text(self.index_path)
        if existing is not None and self.state_path.is_file():
            return existing
        return render_task_index({}, {})

    def show(self, task_id: str) -> str:
        validate_task_id(task_id)
        text = self._read_text(self.root / self._task_relative(task_id))
        if text is None:
            raise DocumentError("task_missing")
        return text

    def _load_history_events(self, day: str) -> list[ActivityEvent]:
        text = self._read_text(self.root / self._history_relative(day))
        if text is None:
            return []
        return parse_activity(text)

    def milestone(self, task_id: str, text: str, summary: str) -> TaskResult:
        validate_task_id(task_id)
        if not summary.strip():
            raise DocumentError("invalid_task")
        findings = scan_secrets(summary)
        if findings:
            detail = ", ".join(f"{item.kind}@{item.line}" for item in findings)
            raise DocumentError("secret_detected", detail)
        draft = parse_task_draft(text, task_id)
        registry = self._registry()
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        entry = tasks.get(task_id)
        if not isinstance(entry, dict):
            raise DocumentError("task_missing")
        created = entry["created"]
        assert isinstance(created, str)
        current = self._current_time()
        updated = current.isoformat()
        tasks[task_id] = {
            "status": draft.status,
            "created": created,
            "updated": updated,
        }
        documents = self._load_documents({key: value for key, value in tasks.items() if key != task_id})
        documents[task_id] = draft
        rendered = render_task(draft, created, updated)
        identity = load_or_create_project(self.root)
        day = current.date().isoformat()
        event = ActivityEvent(
            timestamp=updated,
            kind="milestone",
            project_id=identity.project_id,
            task_id=task_id,
            summary=summary.strip(),
        )
        history_events = merge_event(self._load_history_events(day), event)
        history_text = render_activity(history_events, current.date())
        self._commit_transaction(
            self._base_files(
                registry,
                documents,
                {self._task_relative(task_id): rendered},
                self._history_relative(day),
                history_text,
            )
        )
        return TaskResult(True, "milestone_recorded", task_id)

    def complete(self, task_id: str, summary: str) -> TaskResult:
        validate_task_id(task_id)
        if not summary.strip():
            raise DocumentError("invalid_task")
        findings = scan_secrets(summary)
        if findings:
            detail = ", ".join(f"{item.kind}@{item.line}" for item in findings)
            raise DocumentError("secret_detected", detail)
        registry = self._registry()
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        if task_id not in tasks:
            raise DocumentError("task_missing")
        handoff_state = self._read_json(self.ai / "handoff-state.json") or {}
        handoff_tasks = handoff_state.get("tasks")
        if isinstance(handoff_tasks, dict):
            entry = handoff_tasks.get(task_id)
            if isinstance(entry, dict) and entry.get("status") in {"in-progress", "blocked"}:
                raise DocumentError("handoff_still_open")
        del tasks[task_id]
        documents = self._load_documents(tasks)
        identity = load_or_create_project(self.root)
        current = self._current_time()
        day = current.date().isoformat()
        event = ActivityEvent(
            timestamp=current.isoformat(),
            kind="completed",
            project_id=identity.project_id,
            task_id=task_id,
            summary=summary.strip(),
        )
        history_events = merge_event(self._load_history_events(day), event)
        history_text = render_activity(history_events, current.date())
        self._commit_transaction(
            self._base_files(
                registry,
                documents,
                {self._task_relative(task_id): None},
                self._history_relative(day),
                history_text,
            )
        )
        return TaskResult(True, "task_completed", task_id)

    def install_snapshot(self, files: dict[str, bytes]) -> None:
        required = {"project.json", "task-state.json"}
        if not required.issubset(files):
            raise DocumentError("invalid_snapshot")
        try:
            project_data = json.loads(files["project.json"].decode("utf-8"))
            registry = json.loads(files["task-state.json"].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise DocumentError("invalid_snapshot") from error
        if not isinstance(project_data, dict) or not isinstance(registry, dict):
            raise DocumentError("invalid_snapshot")
        self._validate_registry(registry)
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)

        documents: dict[str, TaskDraft] = {}
        task_files: dict[str, str | None] = {}
        for relative, content in files.items():
            if relative in ROOT_SKIP:
                continue
            if relative.startswith("tasks/"):
                name = relative.removeprefix("tasks/")
                if not name.endswith(".md"):
                    raise DocumentError("invalid_snapshot")
                task_id = name[:-3]
                validate_task_id(task_id)
                if task_id not in tasks:
                    raise DocumentError("invalid_snapshot")
                text = content.decode("utf-8")
                draft = parse_task_draft(self._strip_timestamps(text), task_id)
                if draft.status != tasks[task_id]["status"]:
                    raise DocumentError("invalid_snapshot")
                documents[task_id] = draft
                task_files[self._task_relative(task_id)] = text
            elif relative.startswith("history/"):
                name = relative.removeprefix("history/")
                if not name.endswith(".md"):
                    raise DocumentError("invalid_snapshot")
                task_files[f".ai/history/{name}"] = content.decode("utf-8")
            elif relative not in required:
                raise DocumentError("invalid_snapshot")

        if set(documents) != set(tasks):
            raise DocumentError("invalid_snapshot")

        existing_tasks = sorted(self.tasks_dir.glob("*.md")) if self.tasks_dir.is_dir() else []
        for path in existing_tasks:
            relative = f".ai/tasks/{path.name}"
            if relative not in task_files:
                task_files[relative] = None

        existing_history = sorted(self.history_dir.glob("*.md")) if self.history_dir.is_dir() else []
        for path in existing_history:
            relative = f".ai/history/{path.name}"
            if relative not in task_files:
                task_files[relative] = None

        payload = self._base_files(registry, documents, task_files)
        payload[".ai/project.json"] = self._json_text(project_data)
        self._commit_transaction(payload)


ROOT_SKIP = frozenset({"project.json", "task-state.json"})
