from __future__ import annotations

import re
from dataclasses import dataclass


REQUIRED_SECTIONS = (
    "Goal",
    "Current state",
    "Completed",
    "Verification",
    "Remaining",
    "Next action",
    "Constraints",
)
PLAN_FILES_SECTION = "Plan files"
PLACEHOLDERS = {"tbd", "todo", "none", "n/a", "unknown", "later", "-"}
MAX_DRAFT_BYTES = 8 * 1024


class DocumentError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "line": self.line}


@dataclass(frozen=True)
class Draft:
    task_id: str
    status: str
    sections: dict[str, str]

    @property
    def plan_files(self) -> tuple[str, ...]:
        value = self.sections.get(PLAN_FILES_SECTION, "")
        paths: list[str] = []
        for line in value.splitlines():
            item = line.strip()
            if not item or not item.startswith("- "):
                raise DocumentError("invalid_plan_file_entry")
            path = item[2:].strip()
            if path.startswith("`") and path.endswith("`") and len(path) > 2:
                path = path[1:-1]
            if not path:
                raise DocumentError("invalid_plan_file_entry")
            paths.append(path)
        if len(paths) != len(set(paths)):
            raise DocumentError("duplicate_plan_file")
        return tuple(paths)


SECRET_PATTERNS = (
    ("private_key", re.compile(r"-----BEGIN (?:(?:RSA|EC|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)),
    (
        "assigned_secret",
        re.compile(r"\b(?:password|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    ),
)


def scan_secrets(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(SecretFinding(kind, number))
    return findings


def parse_draft(text: str, expected_task_id: str) -> Draft:
    if len(text.encode("utf-8")) > MAX_DRAFT_BYTES:
        raise DocumentError("handoff_too_large")
    findings = scan_secrets(text)
    if findings:
        summary = ", ".join(f"{item.kind}@{item.line}" for item in findings)
        raise DocumentError("secret_detected", summary)
    if not text.startswith("# Task handoff\n"):
        raise DocumentError("invalid_title")

    task_match = re.search(r"^Task-ID:\s*(\S+)\s*$", text, re.MULTILINE)
    status_match = re.search(r"^Status:\s*(in-progress|blocked|completed)\s*$", text, re.MULTILINE)
    if not task_match:
        raise DocumentError("missing_task_id")
    if task_match.group(1) != expected_task_id:
        raise DocumentError("task_id_mismatch")
    if not status_match:
        raise DocumentError("invalid_status")

    matches = list(re.finditer(r"^## ([^\n]+)\s*$", text, re.MULTILINE))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end() : end].strip()
    for name in REQUIRED_SECTIONS:
        if not sections.get(name):
            raise DocumentError("missing_section", name)

    action_lines = [line.strip() for line in sections["Next action"].splitlines() if line.strip()]
    if len(action_lines) != 1:
        raise DocumentError("next_action_count")
    action = action_lines[0].removeprefix("- ").strip()
    if action.casefold().rstrip(".。") in PLACEHOLDERS:
        raise DocumentError("next_action_placeholder")
    draft = Draft(task_match.group(1), status_match.group(1), sections)
    draft.plan_files
    return draft


def render(draft: Draft, updated: str, metadata: object) -> str:
    lines = [
        "# Task handoff",
        f"Task-ID: {draft.task_id}",
        f"Updated: {updated}",
        f"Status: {draft.status}",
        "",
    ]
    for name in REQUIRED_SECTIONS[:4]:
        lines.extend((f"## {name}", draft.sections[name], ""))
    if PLAN_FILES_SECTION in draft.sections:
        lines.extend((f"## {PLAN_FILES_SECTION}", draft.sections[PLAN_FILES_SECTION], ""))
    lines.extend(
        (
            "## Working context",
            f"- Repo: {metadata.repo}",
            f"- Branch: {metadata.branch}",
            f"- HEAD: {metadata.head}",
            f"- Dirty: {str(metadata.dirty).lower()}",
            f"- Dirty fingerprint: {metadata.dirty_fingerprint}",
            "",
        )
    )
    for name in REQUIRED_SECTIONS[4:]:
        lines.extend((f"## {name}", draft.sections[name], ""))
    return "\n".join(lines).rstrip() + "\n"


def metadata_matches(text: str, updated: str, metadata: dict[str, object]) -> bool:
    expected = (
        ("Updated:", f"Updated: {updated}"),
        ("- Repo:", f"- Repo: {metadata.get('repo')}"),
        ("- Branch:", f"- Branch: {metadata.get('branch')}"),
        ("- HEAD:", f"- HEAD: {metadata.get('head')}"),
        ("- Dirty:", f"- Dirty: {str(metadata.get('dirty')).lower()}"),
        ("- Dirty fingerprint:", f"- Dirty fingerprint: {metadata.get('dirty_fingerprint')}"),
    )
    lines = text.splitlines()
    return all(
        [line for line in lines if line.startswith(prefix)] == [value]
        for prefix, value in expected
    )
