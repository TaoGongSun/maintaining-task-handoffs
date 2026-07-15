from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .atomic import write_json, write_text
from .document import (
    DocumentError,
    legacy_handoff_identity,
    metadata_matches,
    parse_draft,
    render,
    render_index,
    validate_task_id,
)
from .git import GitMetadata, git_metadata, repo_root


@dataclass(frozen=True)
class Result:
    ok: bool
    code: str

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "code": self.code}


class HandoffService:
    def __init__(self, cwd: Path, now: Callable[[], datetime] | None = None) -> None:
        self.root = repo_root(cwd)
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.ai = self.root / ".ai"
        self.handoff = self.ai / "HANDOFF.md"
        self.handoffs = self.ai / "handoffs"
        self.state_path = self.ai / "handoff-state.json"
        self.metrics_path = self.ai / "handoff-metrics.jsonl"
        self.transaction_path = self.ai / "handoff-transaction.json"
        self._recover_transaction()

    def _recover_transaction(self) -> None:
        try:
            transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
            if transaction.get("version") == 2:
                self._apply_transaction(transaction)
            else:
                document = transaction["document"]
                state = transaction["state"]
                if self.handoff.read_text(encoding="utf-8") == document:
                    write_json(self.state_path, state)
            self.transaction_path.unlink(missing_ok=True)
        except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError):
            return

    def _task_path(self, task_id: str) -> Path:
        validate_task_id(task_id)
        return self.handoffs / f"{task_id}.md"

    def _apply_transaction(self, transaction: dict[str, object]) -> None:
        documents = transaction.get("documents")
        index = transaction.get("index")
        state = transaction.get("state")
        if not isinstance(documents, dict) or not isinstance(index, str) or not isinstance(state, dict):
            raise DocumentError("invalid_transaction")
        self._validate_registry(state)
        tasks = state["tasks"]
        assert isinstance(tasks, dict)
        if index != render_index(tasks, state["active_task_id"]):
            raise DocumentError("invalid_transaction")
        for task_id, document in documents.items():
            path = self._task_path(str(task_id))
            if document is None:
                path.unlink(missing_ok=True)
            elif isinstance(document, str):
                write_text(path, document)
            else:
                raise DocumentError("invalid_transaction")
        write_text(self.handoff, index)
        write_json(self.state_path, state)

    def _commit_store(
        self, registry: dict[str, object], documents: dict[str, str | None]
    ) -> None:
        self._validate_registry(registry)
        tasks = registry.get("tasks")
        active_task_id = registry.get("active_task_id")
        if not isinstance(tasks, dict) or (active_task_id is not None and not isinstance(active_task_id, str)):
            raise DocumentError("invalid_state")
        index = render_index(tasks, active_task_id)
        transaction = {
            "version": 2,
            "index": index,
            "state": registry,
            "documents": documents,
        }
        write_json(self.transaction_path, transaction)
        self._apply_transaction(transaction)
        self.transaction_path.unlink(missing_ok=True)

    @staticmethod
    def _validate_registry(registry: dict[str, object]) -> None:
        if registry.get("version") != 2:
            raise DocumentError("invalid_state")
        tasks = registry.get("tasks")
        active_task_id = registry.get("active_task_id")
        if not isinstance(tasks, dict) or (active_task_id is not None and not isinstance(active_task_id, str)):
            raise DocumentError("invalid_state")
        active_entries: list[str] = []
        for task_id, entry in tasks.items():
            if not isinstance(task_id, str) or not isinstance(entry, dict):
                raise DocumentError("invalid_state")
            try:
                validate_task_id(task_id)
            except DocumentError as error:
                raise DocumentError("invalid_state") from error
            if entry.get("phase") not in {"active", "paused"}:
                raise DocumentError("invalid_state")
            if entry.get("status") not in {"in-progress", "blocked"}:
                raise DocumentError("invalid_state")
            if entry.get("phase") == "active":
                active_entries.append(task_id)
        expected = [] if active_task_id is None else [active_task_id]
        if active_entries != expected:
            raise DocumentError("invalid_state")

    def _read_state(self) -> dict[str, object] | None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else None
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _legacy_registry(self) -> tuple[dict[str, object], dict[str, str | None]]:
        registry: dict[str, object] = {"version": 2, "active_task_id": None, "tasks": {}}
        documents: dict[str, str | None] = {}
        legacy_state = self._read_state() or {}
        try:
            legacy_document = self.handoff.read_text(encoding="utf-8")
        except FileNotFoundError:
            legacy_document = ""
        identity = legacy_handoff_identity(legacy_document) if legacy_document else None
        if identity is None:
            if legacy_state.get("phase") in {"active", "paused"}:
                raise DocumentError("invalid_handoff")
            return registry, documents
        task_id, status = identity
        if status == "completed":
            return registry, documents
        same_state = legacy_state.get("task_id") == task_id
        phase = "active" if same_state and legacy_state.get("phase") == "active" else "paused"
        metadata = legacy_state.get("git") if same_state and isinstance(legacy_state.get("git"), dict) else {}
        entry = {
            "phase": phase,
            "status": status,
            "updated": str(legacy_state.get("updated", "")) if same_state else "",
            "fresh_minutes": int(legacy_state.get("fresh_minutes", 30)) if same_state else 30,
            "harness": str(legacy_state.get("harness", "legacy")) if same_state else "legacy",
            "git": metadata,
        }
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        tasks[task_id] = entry
        if phase == "active":
            registry["active_task_id"] = task_id
        documents[task_id] = legacy_document
        return registry, documents

    def _registry_for_mutation(self) -> tuple[dict[str, object], dict[str, str | None]]:
        state = self._read_state()
        if state and state.get("version") == 2:
            self._validate_registry(state)
            return state, {}
        return self._legacy_registry()

    def checkpoint(self, task_id: str, text: str, harness: str, fresh_minutes: int) -> Result:
        validate_task_id(task_id)
        draft = parse_draft(text, task_id)
        if draft.status == "completed":
            raise DocumentError("checkpoint_status_completed")
        registry, documents = self._registry_for_mutation()
        active_task_id = registry.get("active_task_id")
        if active_task_id is not None and active_task_id != task_id:
            raise DocumentError("active_task_mismatch")
        metadata = git_metadata(self.root)
        updated = self.now().astimezone(timezone.utc).isoformat()
        document = render(draft, updated, metadata)
        entry = {
            "phase": "active",
            "status": draft.status,
            "updated": updated,
            "fresh_minutes": fresh_minutes,
            "harness": harness,
            "git": metadata.to_dict(),
        }
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        tasks[task_id] = entry
        registry["active_task_id"] = task_id
        documents[task_id] = document
        self._commit_store(registry, documents)
        return Result(True, "checkpoint_valid")

    def _state(self) -> dict[str, object] | None:
        return self._read_state()

    def validate(self, task_id: str | None = None, fresh_minutes: int = 30) -> Result:
        state = self._read_state()
        if not state:
            return Result(False, "no_active_task")
        if state.get("version") != 2:
            return self._validate_legacy(state, task_id, fresh_minutes)
        try:
            self._validate_registry(state)
        except DocumentError:
            return Result(False, "invalid_state")
        active_task_id = state.get("active_task_id")
        tasks = state.get("tasks")
        if not isinstance(active_task_id, str) or not isinstance(tasks, dict):
            return Result(False, "no_active_task")
        if task_id is not None and active_task_id != task_id:
            return Result(False, "task_id_mismatch")
        entry = tasks.get(active_task_id)
        if not isinstance(entry, dict) or entry.get("phase") != "active":
            return Result(False, "invalid_state")
        return self._validate_entry(active_task_id, entry, fresh_minutes, self._task_path(active_task_id))

    def _validate_legacy(
        self, state: dict[str, object], task_id: str | None, fresh_minutes: int
    ) -> Result:
        if state.get("phase") != "active":
            return Result(False, "no_active_task")
        legacy_task_id = state.get("task_id")
        if not isinstance(legacy_task_id, str):
            return Result(False, "invalid_state")
        if task_id is not None and legacy_task_id != task_id:
            return Result(False, "task_id_mismatch")
        return self._validate_entry(legacy_task_id, state, fresh_minutes, self.handoff)

    def _validate_entry(
        self, task_id: str, entry: dict[str, object], fresh_minutes: int, document_path: Path
    ) -> Result:
        try:
            updated = datetime.fromisoformat(str(entry["updated"]))
        except (KeyError, ValueError):
            return Result(False, "invalid_state")
        age = self.now().astimezone(timezone.utc) - updated.astimezone(timezone.utc)
        if age.total_seconds() > fresh_minutes * 60:
            return Result(False, "stale_time")
        current = git_metadata(self.root).to_dict()
        if entry.get("git") != current:
            return Result(False, "stale_git")
        try:
            text = document_path.read_text(encoding="utf-8")
            parse_draft(text, task_id)
        except (FileNotFoundError, DocumentError):
            return Result(False, "invalid_handoff")
        if not metadata_matches(text, str(entry["updated"]), current):
            return Result(False, "metadata_mismatch")
        return Result(True, "valid")

    def pause(self, task_id: str, text: str, harness: str, fresh_minutes: int) -> Result:
        validate_task_id(task_id)
        registry, documents = self._registry_for_mutation()
        active_task_id = registry.get("active_task_id")
        if active_task_id is None:
            return Result(False, "no_active_task")
        if active_task_id != task_id:
            return Result(False, "task_id_mismatch")
        draft = parse_draft(text, task_id)
        if draft.status == "completed":
            raise DocumentError("pause_status_completed")
        metadata = git_metadata(self.root)
        if git_metadata(self.root).to_dict() != metadata.to_dict():
            return Result(False, "stale_git")
        updated = self.now().astimezone(timezone.utc).isoformat()
        tasks = registry["tasks"]
        assert isinstance(tasks, dict)
        tasks[task_id] = {
            "phase": "paused",
            "status": draft.status,
            "updated": updated,
            "fresh_minutes": fresh_minutes,
            "harness": harness,
            "git": metadata.to_dict(),
        }
        registry["active_task_id"] = None
        documents[task_id] = render(draft, updated, metadata)
        self._commit_store(registry, documents)
        return Result(True, "paused")

    def complete(self, task_id: str, text: str, harness: str, fresh_minutes: int) -> Result:
        validate_task_id(task_id)
        registry, documents = self._registry_for_mutation()
        active_task_id = registry.get("active_task_id")
        if active_task_id is None:
            self._metric("complete", task_id, harness, False, "no_active_task")
            return Result(False, "no_active_task")
        if active_task_id != task_id:
            self._metric("complete", task_id, harness, False, "task_id_mismatch")
            return Result(False, "task_id_mismatch")
        try:
            draft = parse_draft(text, task_id)
            if draft.status != "completed":
                raise DocumentError("status_not_completed")
        except DocumentError as error:
            self._metric("complete", task_id, harness, False, error.code)
            raise
        now = self.now().astimezone(timezone.utc)
        try:
            moves = self._plan_archive_moves(draft.plan_files, now.year)
        except DocumentError as error:
            self._metric("complete", task_id, harness, False, error.code)
            raise
        previous_document = self._read_optional(self.handoff)
        previous_state = self._read_state()
        affected_ids = set(documents) | {task_id}
        previous_tasks = {item: self._read_optional(self._task_path(item)) for item in affected_ids}
        moved: list[tuple[Path, Path]] = []
        try:
            for source, destination in moves:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, destination)
                moved.append((source, destination))
            metadata = git_metadata(self.root)
            if git_metadata(self.root).to_dict() != metadata.to_dict():
                raise DocumentError("stale_git")
            tasks = registry["tasks"]
            assert isinstance(tasks, dict)
            tasks.pop(task_id, None)
            registry["active_task_id"] = None
            documents[task_id] = None
            self._commit_store(registry, documents)
        except Exception as error:
            for source, destination in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(destination, source)
            self._restore_store(previous_document, previous_state, previous_tasks)
            reason = error.code if isinstance(error, DocumentError) else "io_error"
            self._metric("complete", task_id, harness, False, reason)
            if isinstance(error, DocumentError) and error.code == "stale_git":
                return Result(False, "stale_git")
            raise
        self._metric("complete", task_id, harness, True, "valid")
        return Result(True, "completed")

    @staticmethod
    def _read_optional(path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    @staticmethod
    def _restore_text(path: Path, value: str | None) -> None:
        if value is None:
            path.unlink(missing_ok=True)
        else:
            write_text(path, value)

    def _restore_store(
        self,
        document: str | None,
        state: dict[str, object] | None,
        task_documents: dict[str, str | None],
    ) -> None:
        self._restore_text(self.handoff, document)
        for task_id, task_document in task_documents.items():
            self._restore_text(self._task_path(task_id), task_document)
        if state is None:
            self.state_path.unlink(missing_ok=True)
        else:
            write_json(self.state_path, state)
        self.transaction_path.unlink(missing_ok=True)

    def _plan_archive_moves(self, plan_files: tuple[str, ...], year: int) -> list[tuple[Path, Path]]:
        moves: list[tuple[Path, Path]] = []
        destinations: set[Path] = set()
        for value in plan_files:
            if "\\" in value:
                raise DocumentError("plan_path_outside_repo")
            relative = Path(value)
            if relative.is_absolute() or not relative.parts or relative == Path(".") or ".." in relative.parts:
                raise DocumentError("plan_path_outside_repo")
            if "archive" in relative.parts:
                raise DocumentError("plan_already_archived")
            source = self.root / relative
            self._reject_symlink_components(source)
            try:
                source.resolve(strict=False).relative_to(self.root)
            except ValueError as error:
                raise DocumentError("plan_path_outside_repo") from error
            if not source.is_file():
                raise DocumentError("plan_file_missing")
            if relative.parts[:2] == (".ai", "plans"):
                remainder = Path(*relative.parts[2:])
                if not remainder.parts:
                    raise DocumentError("invalid_plan_file_entry")
                destination = self.root / ".ai" / "archive" / "plans" / str(year) / remainder
            else:
                destination = source.parent / "archive" / str(year) / source.name
            self._reject_symlink_components(destination)
            try:
                destination.resolve(strict=False).relative_to(self.root)
            except ValueError as error:
                raise DocumentError("plan_path_outside_repo") from error
            if destination.exists() or destination in destinations:
                raise DocumentError("plan_archive_conflict")
            destinations.add(destination)
            moves.append((source, destination))
        return moves

    def _reject_symlink_components(self, path: Path) -> None:
        relative = path.relative_to(self.root)
        current = self.root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise DocumentError("plan_symlink_rejected")

    def _metric(self, event: str, task_id: str, harness: str, ok: bool, reason: str) -> None:
        self.ai.mkdir(parents=True, exist_ok=True)
        record = {
            "event": event,
            "time": self.now().astimezone(timezone.utc).isoformat(),
            "task": hashlib.sha256(task_id.encode()).hexdigest()[:16],
            "harness": harness,
            "ok": ok,
            "reason": reason,
        }
        with self.metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def record_failed_completion(self, task_id: str, harness: str, reason: str) -> None:
        self._metric("complete", task_id, harness, False, reason)

    def compliance(self) -> dict[str, object]:
        records = []
        try:
            for line in self.metrics_path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                if item.get("event") == "complete":
                    records.append(item)
        except FileNotFoundError:
            pass
        valid = sum(1 for item in records if item.get("ok") is True)
        attempts = len(records)
        return {"attempts": attempts, "valid": valid, "rate": valid / attempts if attempts else None}
