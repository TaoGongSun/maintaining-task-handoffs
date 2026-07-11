from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .atomic import write_json, write_text
from .document import DocumentError, metadata_matches, parse_draft, render
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
        self.state_path = self.ai / "handoff-state.json"
        self.metrics_path = self.ai / "handoff-metrics.jsonl"
        self.transaction_path = self.ai / "handoff-transaction.json"
        self._recover_transaction()

    def _recover_transaction(self) -> None:
        try:
            transaction = json.loads(self.transaction_path.read_text(encoding="utf-8"))
            document = transaction["document"]
            state = transaction["state"]
            if self.handoff.read_text(encoding="utf-8") == document:
                write_json(self.state_path, state)
            self.transaction_path.unlink(missing_ok=True)
        except (FileNotFoundError, KeyError, json.JSONDecodeError, OSError):
            return

    def _commit_pair(self, document: str, state: dict[str, object]) -> None:
        write_json(self.transaction_path, {"document": document, "state": state})
        write_text(self.handoff, document)
        write_json(self.state_path, state)
        self.transaction_path.unlink(missing_ok=True)

    def checkpoint(self, task_id: str, text: str, harness: str, fresh_minutes: int) -> Result:
        existing = self._state()
        if existing and existing.get("phase") == "active" and existing.get("task_id") != task_id:
            raise DocumentError("active_task_mismatch")
        draft = parse_draft(text, task_id)
        if draft.status == "completed":
            raise DocumentError("checkpoint_status_completed")
        metadata = git_metadata(self.root)
        updated = self.now().astimezone(timezone.utc).isoformat()
        document = render(draft, updated, metadata)
        state = {
            "task_id": task_id,
            "phase": "active",
            "updated": updated,
            "fresh_minutes": fresh_minutes,
            "harness": harness,
            "git": metadata.to_dict(),
        }
        self._commit_pair(document, state)
        return Result(True, "checkpoint_valid")

    def _state(self) -> dict[str, object] | None:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def validate(self, task_id: str | None = None, fresh_minutes: int = 30) -> Result:
        state = self._state()
        if not state or state.get("phase") != "active":
            return Result(False, "no_active_task")
        if task_id is not None and state.get("task_id") != task_id:
            return Result(False, "task_id_mismatch")
        try:
            updated = datetime.fromisoformat(str(state["updated"]))
        except (KeyError, ValueError):
            return Result(False, "invalid_state")
        age = self.now().astimezone(timezone.utc) - updated.astimezone(timezone.utc)
        if age.total_seconds() > fresh_minutes * 60:
            return Result(False, "stale_time")
        current = git_metadata(self.root).to_dict()
        if state.get("git") != current:
            return Result(False, "stale_git")
        try:
            text = self.handoff.read_text(encoding="utf-8")
            parse_draft(text, str(state["task_id"]))
        except (FileNotFoundError, DocumentError):
            return Result(False, "invalid_handoff")
        if not metadata_matches(text, str(state["updated"]), current):
            return Result(False, "metadata_mismatch")
        return Result(True, "valid")

    def complete(self, task_id: str, text: str, harness: str, fresh_minutes: int) -> Result:
        state = self._state()
        if not state or state.get("phase") != "active":
            self._metric("complete", task_id, harness, False, "no_active_task")
            return Result(False, "no_active_task")
        if state.get("task_id") != task_id:
            self._metric("complete", task_id, harness, False, "task_id_mismatch")
            return Result(False, "task_id_mismatch")
        try:
            draft = parse_draft(text, task_id)
            if draft.status != "completed":
                raise DocumentError("status_not_completed")
        except DocumentError as error:
            self._metric("complete", task_id, harness, False, error.code)
            raise
        metadata = git_metadata(self.root)
        if git_metadata(self.root).to_dict() != metadata.to_dict():
            self._metric("complete", task_id, harness, False, "stale_git")
            return Result(False, "stale_git")
        updated = self.now().astimezone(timezone.utc).isoformat()
        state.update({"phase": "completed", "updated": updated, "git": metadata.to_dict()})
        self._commit_pair(render(draft, updated, metadata), state)
        self._metric("complete", task_id, harness, True, "valid")
        return Result(True, "completed")

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
