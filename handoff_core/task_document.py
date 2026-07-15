from __future__ import annotations

import re
from dataclasses import dataclass

from .document import DocumentError, MAX_DRAFT_BYTES, PLACEHOLDERS, scan_secrets, validate_task_id

TASK_STATUSES = ("todo", "in-progress", "blocked")
OPTIONAL_SECTIONS = ("Progress", "Constraints")


@dataclass(frozen=True)
class TaskDraft:
    task_id: str
    title: str
    status: str
    sections: dict[str, str]


def parse_task_draft(text: str, expected_task_id: str) -> TaskDraft:
    validate_task_id(expected_task_id)
    if len(text.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise DocumentError("task_too_large")
    findings = scan_secrets(text)
    if findings:
        summary = ", ".join(f"{item.kind}@{item.line}" for item in findings)
        raise DocumentError("secret_detected", summary)
    if not text.startswith("# Task\n"):
        raise DocumentError("invalid_task")
    if re.search(r"^(?:Created|Updated):\s*", text, re.MULTILINE):
        raise DocumentError("invalid_task_metadata")
    task_match = re.search(r"^Task-ID:\s*(\S+)\s*$", text, re.MULTILINE)
    title_match = re.search(r"^Title:\s*(.+?)\s*$", text, re.MULTILINE)
    status_match = re.search(r"^Status:\s*(todo|in-progress|blocked)\s*$", text, re.MULTILINE)
    if not task_match or task_match.group(1) != expected_task_id:
        raise DocumentError("task_id_mismatch")
    if not title_match or not status_match:
        raise DocumentError("invalid_task")
    title = title_match.group(1).strip()
    if title.casefold().rstrip(".。") in PLACEHOLDERS:
        raise DocumentError("invalid_task")
    matches = list(re.finditer(r"^## ([^\n]+)\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end].strip()
    if not sections.get("Summary") or not sections.get("Next action"):
        raise DocumentError("invalid_task")
    action_lines = [line.strip() for line in sections["Next action"].splitlines() if line.strip()]
    if len(action_lines) != 1:
        raise DocumentError("next_action_count")
    action = action_lines[0].removeprefix("- ").strip()
    if action.casefold().rstrip(".。") in PLACEHOLDERS:
        raise DocumentError("next_action_placeholder")
    return TaskDraft(expected_task_id, title, status_match.group(1), sections)


def render_task(draft: TaskDraft, created: str, updated: str) -> str:
    lines = [
        "# Task",
        f"Task-ID: {draft.task_id}",
        f"Title: {draft.title}",
        f"Status: {draft.status}",
        f"Created: {created}",
        f"Updated: {updated}",
        "",
        "## Summary",
        draft.sections["Summary"],
        "",
    ]
    for name in OPTIONAL_SECTIONS[:1]:
        if draft.sections.get(name):
            lines.extend((f"## {name}", draft.sections[name], ""))
    lines.extend(("## Next action", draft.sections["Next action"], ""))
    if draft.sections.get("Constraints"):
        lines.extend(("## Constraints", draft.sections["Constraints"], ""))
    return "\n".join(lines).rstrip() + "\n"


def render_task_index(
    tasks: dict[str, dict[str, object]], documents: dict[str, TaskDraft]
) -> str:
    labels = (("in-progress", "In progress"), ("todo", "Todo"), ("blocked", "Blocked"))
    lines = ["# Project tasks", ""]
    for status, heading in labels:
        lines.append(f"## {heading}")
        task_ids = sorted(task_id for task_id, entry in tasks.items() if entry["status"] == status)
        task_ids.sort(key=lambda task_id: str(tasks[task_id]["updated"]), reverse=True)
        if not task_ids:
            lines.append("- None.")
        else:
            for task_id in task_ids:
                draft = documents[task_id]
                action = draft.sections["Next action"].removeprefix("- ").strip()
                prefix = "阻塞" if status == "blocked" else "下一步"
                lines.append(f"- [{task_id}](tasks/{task_id}.md) — {draft.title} — {prefix}：{action}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
