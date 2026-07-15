from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

from .document import DocumentError, scan_secrets, validate_task_id

ACTIVITY_KINDS = frozenset({"milestone", "completed"})
EVENT_COMMENT = re.compile(r"<!--\s*event\s+(\{.*?\})\s*-->")


@dataclass(frozen=True)
class ActivityEvent:
    timestamp: str
    kind: str
    project_id: str
    task_id: str
    summary: str

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return self.project_id, self.task_id, self.kind, self.timestamp


def render_activity(events: list[ActivityEvent], day: date) -> str:
    lines = [f"# Activity for {day.isoformat()}", ""]
    for event in sorted(events, key=lambda item: (item.timestamp, item.project_id, item.task_id)):
        metadata = json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)
        local = datetime.fromisoformat(event.timestamp)
        lines.append(f"<!-- event {metadata} -->")
        lines.append(
            f"- {local:%H:%M} {local:%z} — `{event.kind}` — "
            f"`{event.project_id}/{event.task_id}`：{event.summary}"
        )
    return "\n".join(lines).rstrip() + "\n"


def parse_activity(text: str) -> list[ActivityEvent]:
    findings = scan_secrets(text)
    if findings:
        summary = ", ".join(f"{item.kind}@{item.line}" for item in findings)
        raise DocumentError("secret_detected", summary)
    events: list[ActivityEvent] = []
    for match in EVENT_COMMENT.finditer(text):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise DocumentError("invalid_activity") from error
        if not isinstance(payload, dict):
            raise DocumentError("invalid_activity")
        timestamp = payload.get("timestamp")
        kind = payload.get("kind")
        project_id = payload.get("project_id")
        task_id = payload.get("task_id")
        summary = payload.get("summary")
        if not all(isinstance(value, str) for value in (timestamp, kind, project_id, task_id, summary)):
            raise DocumentError("invalid_activity")
        assert isinstance(timestamp, str)
        assert isinstance(kind, str)
        assert isinstance(project_id, str)
        assert isinstance(task_id, str)
        assert isinstance(summary, str)
        if kind not in ACTIVITY_KINDS:
            raise DocumentError("invalid_activity")
        try:
            datetime.fromisoformat(timestamp)
        except ValueError as error:
            raise DocumentError("invalid_activity") from error
        validate_task_id(task_id)
        if not project_id.strip() or not summary.strip():
            raise DocumentError("invalid_activity")
        secret_hits = scan_secrets(summary)
        if secret_hits:
            detail = ", ".join(f"{item.kind}@{item.line}" for item in secret_hits)
            raise DocumentError("secret_detected", detail)
        events.append(
            ActivityEvent(
                timestamp=timestamp,
                kind=kind,
                project_id=project_id,
                task_id=task_id,
                summary=summary,
            )
        )
    return events


def merge_event(existing: list[ActivityEvent], event: ActivityEvent) -> list[ActivityEvent]:
    if event.kind not in ACTIVITY_KINDS:
        raise DocumentError("invalid_activity")
    validate_task_id(event.task_id)
    findings = scan_secrets(event.summary)
    if findings:
        detail = ", ".join(f"{item.kind}@{item.line}" for item in findings)
        raise DocumentError("secret_detected", detail)
    merged: list[ActivityEvent] = []
    found = False
    for item in existing:
        if item.identity == event.identity:
            if item != event:
                raise DocumentError("history_conflict")
            found = True
            merged.append(item)
        else:
            merged.append(item)
    if not found:
        merged.append(event)
    return merged
