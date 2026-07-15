# Local Project Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, local-only per-repository tasks, compact activity history, natural-language guidance, and handoff lifecycle integration without changing existing handoff behavior.

**Architecture:** Add focused task document, project identity, activity, and task service modules beside the existing handoff modules. Task files are the semantic source of truth; `task-state.json`, `TASKS.md`, `README.md`, and daily history are transactionally updated projections. The existing CLI gains a nested `task` command group while all current top-level commands remain unchanged.

**Tech Stack:** Python 3 standard library (`dataclasses`, `datetime`, `hashlib`, `json`, `pathlib`, `re`, `urllib.parse`, `uuid`, `zoneinfo`), `unittest`, existing atomic write and Git helpers, Bash installer.

## Global Constraints

- Keep existing `checkpoint`, `pause`, `validate`, `complete`, and `compliance` behavior compatible.
- Add no third-party dependency.
- Keep task and activity files local-only through managed Git global excludes.
- Reject secrets before any write and never echo secret values in errors.
- Use one concrete, non-placeholder `Next action` line.
- Persist task states only as `todo`, `in-progress`, or `blocked`; completion removes the active task.
- Do not complete a task while a same-ID handoff remains active, paused, or blocked.
- Use recoverable transactions for task document, registry, index, entry point, and history changes.
- Use the configured IANA timezone when supplied; otherwise use the system local timezone.
- Do not alter or archive handoff plan files from task operations.

## File Map

- Create `handoff_core/task_document.py`: parse and render task semantic drafts and deterministic task indexes.
- Create `handoff_core/project.py`: create and validate stable local project identity.
- Create `handoff_core/activity.py`: render, parse, merge, and validate daily activity events.
- Create `handoff_core/task_service.py`: task lifecycle, registry validation, transaction recovery, and handoff guard.
- Modify `handoff.py`: nested task CLI and structured output.
- Create `tests/test_tasks.py`: document, identity, activity, service, rollback, and handoff integration tests.
- Create `tests/test_task_cli.py`: end-to-end task CLI contract.
- Modify `tests/test_distribution.py`: skill, adapter, README, and ignore contract tests.
- Modify `SKILL.md`: project-task query and mutation contract.
- Modify `adapters/trigger-block.md`: bounded-context task routing instructions.
- Modify `scripts/install.sh`: local task file excludes.
- Modify `README.md`: bilingual local task behavior and file layout.

---

### Task 1: Task Document Contract

**Files:**
- Create: `handoff_core/task_document.py`
- Create: `tests/test_tasks.py`

**Interfaces:**
- Consumes: `handoff_core.document.DocumentError`, `scan_secrets`, `validate_task_id`.
- Produces: `TaskDraft`, `parse_task_draft(text: str, expected_task_id: str) -> TaskDraft`, `render_task(draft: TaskDraft, created: str, updated: str) -> str`, `render_task_index(tasks: dict[str, dict[str, object]], documents: dict[str, TaskDraft]) -> str`.

- [ ] **Step 1: Write failing parser and renderer tests**

```python
from handoff_core.document import DocumentError
from handoff_core.task_document import parse_task_draft, render_task, render_task_index

TASK_DRAFT = """# Task
Task-ID: project-memory
Title: Build project memory
Status: in-progress

## Summary
Track repository work locally.

## Progress
- Design approved.

## Next action
Implement the task parser.

## Constraints
- Keep handoff behavior unchanged.
"""


class TaskDocumentTests(unittest.TestCase):
    def test_parse_and_render_task(self) -> None:
        draft = parse_task_draft(TASK_DRAFT, "project-memory")
        rendered = render_task(
            draft,
            "2026-07-15T09:00:00+08:00",
            "2026-07-15T10:00:00+08:00",
        )
        self.assertEqual("Build project memory", draft.title)
        self.assertEqual("in-progress", draft.status)
        self.assertIn("Created: 2026-07-15T09:00:00+08:00", rendered)
        self.assertIn("Updated: 2026-07-15T10:00:00+08:00", rendered)

    def test_task_rejects_invalid_content(self) -> None:
        cases = {
            "invalid_task": TASK_DRAFT.replace("Status: in-progress", "Status: completed"),
            "task_id_mismatch": TASK_DRAFT.replace("Task-ID: project-memory", "Task-ID: other"),
            "next_action_count": TASK_DRAFT.replace(
                "Implement the task parser.", "Implement the parser.\nRun another action."
            ),
            "secret_detected": TASK_DRAFT.replace(
                "Track repository work locally.",
                "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij",
            ),
        }
        for code, text in cases.items():
            with self.subTest(code=code), self.assertRaisesRegex(DocumentError, code):
                parse_task_draft(text, "project-memory")

    def test_index_is_deterministic_and_compact(self) -> None:
        first = parse_task_draft(TASK_DRAFT, "project-memory")
        second = parse_task_draft(
            TASK_DRAFT.replace("project-memory", "blocked-release")
            .replace("Build project memory", "Publish release")
            .replace("Status: in-progress", "Status: blocked")
            .replace("Implement the task parser.", "Request package permission."),
            "blocked-release",
        )
        registry = {
            "blocked-release": {"status": "blocked", "updated": "2026-07-15T08:00:00+08:00"},
            "project-memory": {"status": "in-progress", "updated": "2026-07-15T10:00:00+08:00"},
        }
        text = render_task_index(registry, {"project-memory": first, "blocked-release": second})
        self.assertIn("## In progress", text)
        self.assertIn("## Todo\n- None.", text)
        self.assertIn("## Blocked", text)
        self.assertIn("下一步：Implement the task parser.", text)
```

- [ ] **Step 2: Run the focused tests and confirm the missing module failure**

Run: `python3 -m unittest tests.test_tasks.TaskDocumentTests -v`

Expected: import failure for `handoff_core.task_document`.

- [ ] **Step 3: Implement the minimal document contract**

Create `handoff_core/task_document.py` with these exact public definitions and validation rules:

```python
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
        sections[match.group(1)] = text[match.end():end].strip()
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
        task_ids = sorted(
            (task_id for task_id, entry in tasks.items() if entry["status"] == status),
            key=lambda task_id: (str(tasks[task_id]["updated"]), task_id),
            reverse=True,
        )
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
```

- [ ] **Step 4: Run document tests**

Run: `python3 -m unittest tests.test_tasks.TaskDocumentTests -v`

Expected: all `TaskDocumentTests` pass.

- [ ] **Step 5: Commit the task document contract**

```bash
git add handoff_core/task_document.py tests/test_tasks.py
git commit -m "Add local task document contract"
```

---

### Task 2: Stable Project Identity and Activity Events

**Files:**
- Create: `handoff_core/project.py`
- Create: `handoff_core/activity.py`
- Modify: `tests/test_tasks.py`

**Interfaces:**
- Consumes: `repo_root`, `write_json`, `scan_secrets`, `DocumentError`.
- Produces: `ProjectIdentity`, `load_or_create_project(root: Path) -> ProjectIdentity`, `ActivityEvent`, `render_activity(events: list[ActivityEvent], day: date) -> str`, `parse_activity(text: str) -> list[ActivityEvent]`, `merge_event(existing: list[ActivityEvent], event: ActivityEvent) -> list[ActivityEvent]`.

- [ ] **Step 1: Add failing identity and activity tests**

```python
from datetime import date
from handoff_core.activity import ActivityEvent, merge_event, parse_activity, render_activity
from handoff_core.project import load_or_create_project


class ProjectAndActivityTests(RepoCase):
    def test_remote_identity_normalizes_ssh_and_https(self) -> None:
        run("git", "remote", "add", "origin", "git@github.com:TaoGongSun/repo.git", cwd=self.repo)
        ssh = load_or_create_project(self.repo)
        (self.repo / ".ai/project.json").unlink()
        run("git", "remote", "set-url", "origin", "https://github.com/TaoGongSun/repo.git", cwd=self.repo)
        https = load_or_create_project(self.repo)
        self.assertEqual("github.com-taogongsun-repo", ssh.project_id)
        self.assertEqual(ssh.project_id, https.project_id)

    def test_local_identity_survives_directory_move(self) -> None:
        first = load_or_create_project(self.repo)
        moved = self.repo.parent / f"{self.repo.name}-moved"
        self.temp.cleanup = lambda: None
        self.repo.rename(moved)
        second = load_or_create_project(moved)
        self.assertEqual(first.project_id, second.project_id)

    def test_activity_round_trip_and_conflict(self) -> None:
        event = ActivityEvent(
            timestamp="2026-07-15T10:30:00+08:00",
            kind="milestone",
            project_id="github.com-taogongsun-repo",
            task_id="project-memory",
            summary="Design approved.",
        )
        rendered = render_activity([event], date(2026, 7, 15))
        self.assertEqual([event], parse_activity(rendered))
        self.assertEqual([event], merge_event([], event))
        conflicting = ActivityEvent(**{**event.__dict__, "summary": "Different summary."})
        with self.assertRaisesRegex(DocumentError, "history_conflict"):
            merge_event([event], conflicting)
```

- [ ] **Step 2: Run tests and confirm missing modules**

Run: `python3 -m unittest tests.test_tasks.ProjectAndActivityTests -v`

Expected: import failure for `handoff_core.activity` or `handoff_core.project`.

- [ ] **Step 3: Implement stable project identity**

Create `handoff_core/project.py` with `ProjectIdentity(project_id, name, remote)`, URL normalization for SCP-style SSH and standard URLs, and persisted UUID fallback. Use this exact ID rule:

```python
def _remote_parts(value: str) -> tuple[str, str] | None:
    scp = re.fullmatch(r"(?:[^@]+@)?([^:]+):(.+)", value)
    if scp and "://" not in value:
        host, path = scp.groups()
    else:
        parsed = urlparse(value)
        if not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    clean = path.strip("/").removesuffix(".git")
    if not clean:
        return None
    return host.casefold(), clean.casefold()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-")
```

`load_or_create_project()` must return a valid existing `.ai/project.json` unchanged; otherwise use `git remote get-url origin`, or generate `local-<uuid4 hex>` and persist it with `write_json`.

- [ ] **Step 4: Implement activity event round-trip**

Create `handoff_core/activity.py`. Render each event as one metadata comment followed by one readable line:

```python
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
```

`parse_activity()` must parse only `<!-- event {...} -->` comments, validate kind in `{"milestone", "completed"}`, validate task ID, parse ISO timestamps, and run `scan_secrets()` on summaries. `merge_event()` must deduplicate identical identities and raise `DocumentError("history_conflict")` when the same identity has different content.

- [ ] **Step 5: Run identity and activity tests**

Run: `python3 -m unittest tests.test_tasks.ProjectAndActivityTests -v`

Expected: all tests pass.

- [ ] **Step 6: Commit identity and activity support**

```bash
git add handoff_core/project.py handoff_core/activity.py tests/test_tasks.py
git commit -m "Add project identity and activity events"
```

---

### Task 3: Transactional Task Add and Update

**Files:**
- Create: `handoff_core/task_service.py`
- Modify: `tests/test_tasks.py`

**Interfaces:**
- Consumes: `TaskDraft`, project identity, activity helpers, `write_json`, `write_text`, `repo_root`.
- Produces: `TaskResult(ok: bool, code: str, task_id: str | None = None)`, `TaskService.add(task_id: str, text: str)`, `TaskService.update(task_id: str, text: str)`, `TaskService.list()`, `TaskService.show(task_id: str)`.

- [ ] **Step 1: Add failing lifecycle and recovery tests**

Add `TaskServiceTests` covering:

```python
from handoff_core.task_service import TaskService


class TaskServiceTests(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.service = TaskService(self.repo, now=lambda: self.now)

    def test_add_writes_document_registry_index_and_entrypoint(self) -> None:
        result = self.service.add("project-memory", TASK_DRAFT)
        self.assertEqual("task_added", result.code)
        self.assertTrue((self.repo / ".ai/tasks/project-memory.md").is_file())
        state = json.loads((self.repo / ".ai/task-state.json").read_text())
        self.assertEqual("in-progress", state["tasks"]["project-memory"]["status"])
        self.assertIn("project-memory", (self.repo / ".ai/TASKS.md").read_text())
        self.assertIn("[未完成待辦](TASKS.md)", (self.repo / ".ai/README.md").read_text())

    def test_update_preserves_created_and_rejects_duplicates(self) -> None:
        self.service.add("project-memory", TASK_DRAFT)
        created = json.loads((self.repo / ".ai/task-state.json").read_text())["tasks"]["project-memory"]["created"]
        self.now += timedelta(hours=1)
        updated = TASK_DRAFT.replace("Implement the task parser.", "Implement the task service.")
        self.assertEqual("task_updated", self.service.update("project-memory", updated).code)
        state = json.loads((self.repo / ".ai/task-state.json").read_text())
        self.assertEqual(created, state["tasks"]["project-memory"]["created"])
        with self.assertRaisesRegex(DocumentError, "task_exists"):
            self.service.add("project-memory", updated)

    def test_interrupted_transaction_recovers(self) -> None:
        self.service.add("project-memory", TASK_DRAFT)
        changed = TASK_DRAFT.replace("Implement the task parser.", "Implement the task service.")
        with patch.object(self.service, "_apply_transaction", side_effect=OSError("process stopped")):
            with self.assertRaisesRegex(OSError, "process stopped"):
                self.service.update("project-memory", changed)
        self.assertTrue(self.service.transaction_path.is_file())

        recovered = TaskService(self.repo, now=lambda: self.now)

        self.assertFalse(recovered.transaction_path.exists())
        self.assertIn("Implement the task service.", recovered.show("project-memory"))
```

`_commit_transaction()` must write the complete manifest before calling `_apply_transaction()`. This fixed patch therefore simulates a process failure after the recovery data is durable and before any target write.

- [ ] **Step 2: Run focused service tests and confirm failure**

Run: `python3 -m unittest tests.test_tasks.TaskServiceTests -v`

Expected: import failure for `handoff_core.task_service`.

- [ ] **Step 3: Implement registry and transaction validation**

Create `TaskService` paths:

```python
self.ai = self.root / ".ai"
self.tasks_dir = self.ai / "tasks"
self.state_path = self.ai / "task-state.json"
self.index_path = self.ai / "TASKS.md"
self.entry_path = self.ai / "README.md"
self.transaction_path = self.ai / "task-transaction.json"
```

Registry schema is `{"version": 1, "tasks": {}}`. Transaction schema is:

```python
{
    "version": 1,
    "files": {
        ".ai/tasks/project-memory.md": "full text or null",
        ".ai/task-state.json": "full JSON text",
        ".ai/TASKS.md": "full text",
        ".ai/README.md": "full text"
    }
}
```

Validate every relative path against an explicit allowlist rooted under `.ai/`, reject symlink components, write the manifest first, apply each file with `write_text` or unlink, then remove the manifest. Constructor recovery reapplies a valid manifest idempotently.

- [ ] **Step 4: Implement add, update, list, and show**

`add()` parses semantic input, rejects an existing ID, records `created == updated == now`, renders the task, rebuilds the index from all parsed task documents, and commits one transaction.

`update()` requires an existing ID, preserves `created`, changes `updated`, renders the replacement, and commits one transaction.

`list()` returns the current `TASKS.md` text, creating the fixed empty index only when no state exists. `show()` returns the exact task file text or raises `DocumentError("task_missing")`.

Use this fixed entry point:

```python
ENTRY_TEXT = """# Project memory

- [未完成待辦](TASKS.md)
- [長任務交接](HANDOFF.md)
- [每日活動紀錄](history/)
"""
```

- [ ] **Step 5: Run task service tests**

Run: `python3 -m unittest tests.test_tasks.TaskServiceTests -v`

Expected: all tests pass, including recovery.

- [ ] **Step 6: Commit transactional add and update**

```bash
git add handoff_core/task_service.py tests/test_tasks.py
git commit -m "Add transactional local task service"
```

---

### Task 4: Milestones, Completion, and Handoff Guard

**Files:**
- Modify: `handoff_core/task_service.py`
- Modify: `tests/test_tasks.py`

**Interfaces:**
- Consumes: Task 3 service and Task 2 activity helpers.
- Produces: `TaskService.milestone(task_id: str, text: str, summary: str) -> TaskResult`, `TaskService.complete(task_id: str, summary: str) -> TaskResult`.

- [ ] **Step 1: Add failing milestone, completion, and rollback tests**

```python
class TaskCompletionTests(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.tasks = TaskService(self.repo, now=lambda: self.now)
        self.tasks.add("project-memory", TASK_DRAFT)

    def test_milestone_updates_task_and_history_atomically(self) -> None:
        changed = TASK_DRAFT.replace("Design approved.", "- Parser implemented.")
        result = self.tasks.milestone("project-memory", changed, "Parser implemented.")
        self.assertEqual("milestone_recorded", result.code)
        history = (self.repo / ".ai/history/2026-07-11.md").read_text()
        self.assertIn("`milestone`", history)
        self.assertIn("Parser implemented.", history)

    def test_complete_removes_active_task_and_writes_history(self) -> None:
        result = self.tasks.complete("project-memory", "Local task support shipped.")
        self.assertEqual("task_completed", result.code)
        self.assertFalse((self.repo / ".ai/tasks/project-memory.md").exists())
        self.assertNotIn("project-memory", (self.repo / ".ai/TASKS.md").read_text())
        self.assertIn("`completed`", (self.repo / ".ai/history/2026-07-11.md").read_text())

    def test_open_handoff_blocks_task_completion(self) -> None:
        handoff = HandoffService(self.repo, now=lambda: self.now)
        handoff.checkpoint("project-memory", BASE_DRAFT.replace("task-123", "project-memory").format(status="in-progress"), "test", 30)
        with self.assertRaisesRegex(DocumentError, "handoff_still_open"):
            self.tasks.complete("project-memory", "Local task support shipped.")

    def test_mid_apply_failure_restores_task(self) -> None:
        task_path = self.repo / ".ai/tasks/project-memory.md"
        original_task = task_path.read_text()
        original_state = (self.repo / ".ai/task-state.json").read_text()
        original_write = self.tasks._write_target
        calls = 0

        def fail_second_write(relative: str, content: str | None) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            original_write(relative, content)

        with patch.object(self.tasks, "_write_target", side_effect=fail_second_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.tasks.complete("project-memory", "Local task support shipped.")

        self.assertEqual(original_task, task_path.read_text())
        self.assertEqual(original_state, (self.repo / ".ai/task-state.json").read_text())
        self.assertFalse((self.repo / ".ai/history/2026-07-11.md").exists())
        self.assertFalse(self.tasks.transaction_path.exists())
```

Define `_write_target(relative: str, content: str | None)` as the only target mutation helper used by `_apply_transaction()` and rollback. The custom side effect fails exactly the second forward write, then delegates every rollback write to the real helper.

- [ ] **Step 2: Run focused completion tests**

Run: `python3 -m unittest tests.test_tasks.TaskCompletionTests -v`

Expected: failures because `milestone()` and `complete()` are absent.

- [ ] **Step 3: Add timezone-aware event creation**

`TaskService.__init__` accepts `timezone_name: str | None = None`. Resolve it with `ZoneInfo(timezone_name)` or use `self.now().astimezone().tzinfo`. Convert every service timestamp through one `_current_time()` helper and store ISO 8601 with offset.

- [ ] **Step 4: Implement milestone and completion transactions**

`milestone()` must parse the replacement draft, preserve `created`, update task state, merge one milestone event into that local date file, rebuild the index, and write all files in one transaction.

`complete()` must:

```python
handoff_state = self._read_json(self.ai / "handoff-state.json") or {}
entry = handoff_state.get("tasks", {}).get(task_id)
if isinstance(entry, dict) and entry.get("status") in {"in-progress", "blocked"}:
    raise DocumentError("handoff_still_open")
```

Then validate the summary with `scan_secrets`, create a completed event, remove the registry entry and task document, rebuild the index, and write history in the same transaction.

For rollback, `_commit_transaction()` must snapshot every target before applying. On apply failure, restore snapshots and leave no transaction manifest. Constructor recovery is for a process crash after manifest write; handled exceptions restore the old state immediately.

- [ ] **Step 5: Run all task service tests**

Run: `python3 -m unittest tests.test_tasks -v`

Expected: all task document, identity, activity, lifecycle, completion, and rollback tests pass.

- [ ] **Step 6: Commit task completion and history**

```bash
git add handoff_core/task_service.py tests/test_tasks.py
git commit -m "Add task milestones and completion history"
```

---

### Task 5: Task CLI Contract

**Files:**
- Modify: `handoff.py`
- Create: `tests/test_task_cli.py`

**Interfaces:**
- Consumes: `TaskService` methods from Tasks 3 and 4.
- Produces commands: `handoff task add|update|milestone|complete|list|show`.

- [ ] **Step 1: Write failing CLI end-to-end tests**

Create a temporary Git repository and test this flow:

```python
class TaskCliTests(unittest.TestCase):
    def test_task_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = init_repo(Path(temp))
            draft = repo / "task.md"
            draft.write_text(TASK_DRAFT, encoding="utf-8")
            added = run_cli("task", "add", "--task-id", "project-memory", "--input", str(draft), cwd=repo)
            listed = run_cli("task", "list", cwd=repo)
            shown = run_cli("task", "show", "--task-id", "project-memory", cwd=repo)
            milestone = run_cli(
                "task", "milestone", "--task-id", "project-memory", "--input", str(draft),
                "--summary", "Parser implemented.", cwd=repo,
            )
            completed = run_cli(
                "task", "complete", "--task-id", "project-memory",
                "--summary", "Local task support shipped.", cwd=repo,
            )
            self.assertEqual("task_added", json.loads(added.stdout)["code"])
            self.assertIn("project-memory", listed.stdout)
            self.assertIn("Title: Build project memory", shown.stdout)
            self.assertEqual("milestone_recorded", json.loads(milestone.stdout)["code"])
            self.assertEqual("task_completed", json.loads(completed.stdout)["code"])

    def test_task_errors_are_structured(self) -> None:
        result = run_cli("task", "show", "--task-id", "missing", cwd=self.repo)
        self.assertEqual(4, result.returncode)
        self.assertEqual("task_missing", json.loads(result.stdout)["code"])
```

- [ ] **Step 2: Run CLI tests and confirm parser rejection**

Run: `python3 -m unittest tests.test_task_cli -v`

Expected: `argparse` rejects the unknown `task` command.

- [ ] **Step 3: Add nested task parsers without changing existing parsers**

Add a `task = commands.add_parser("task")` parser and nested required subparsers. Shared mutation flags are `--task-id`, `--input`, and `--timezone`; `milestone` adds `--summary`; `complete` requires `--summary`; `show` requires `--task-id`; `list` accepts no task ID.

- [ ] **Step 4: Dispatch task commands with existing JSON error behavior**

Instantiate `TaskService(root, timezone_name=args.timezone)` for task commands. Mutation commands print `TaskResult.to_dict()` JSON. `list` and `show` print Markdown directly. Continue mapping `DocumentError` to exit code 4 and I/O failures to exit code 5.

- [ ] **Step 5: Run old and new CLI tests**

Run: `python3 -m unittest tests.test_cli tests.test_task_cli -v`

Expected: all existing lifecycle commands and all task commands pass.

- [ ] **Step 6: Commit the task CLI**

```bash
git add handoff.py tests/test_task_cli.py
git commit -m "Add local task CLI commands"
```

---

### Task 6: Skill, Adapter, Installer, and Bilingual Documentation

**Files:**
- Modify: `tests/test_distribution.py`
- Modify: `SKILL.md`
- Modify: `adapters/trigger-block.md`
- Modify: `scripts/install.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: task CLI from Task 5.
- Produces: bounded-context natural-language routing and installed local-only file contract.

- [ ] **Step 1: Add failing distribution contract tests**

Add assertions that:

```python
def test_task_guidance_routes_bounded_queries(self) -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    adapter = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8")
    for text in (skill, adapter):
        self.assertIn(".ai/TASKS.md", text)
        self.assertIn("handoff task complete", text)
        self.assertIn("yesterday", text.lower())
        self.assertIn("multiple matches", text.lower())
        self.assertIn("do not guess", text.lower())


def test_all_task_runtime_files_are_ignored(self) -> None:
    installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    for path in (
        ".ai/README.md", ".ai/TASKS.md", ".ai/tasks/", ".ai/history/",
        ".ai/project.json", ".ai/task-state.json", ".ai/task-transaction.json",
        ".ai/memory-sync.json",
    ):
        self.assertIn(path, installer)
```

Extend the bilingual README test with local task layout, milestone/completed history, and handoff guard phrases in both languages.

- [ ] **Step 2: Run distribution tests and confirm failures**

Run: `python3 -m unittest tests.test_distribution -v`

Expected: new assertions fail because task guidance and excludes are absent.

- [ ] **Step 3: Update skill and adapter with bounded-context behavior**

Add a separate `## Project tasks` section. It must say:

- Current-project task questions read `.ai/TASKS.md` first.
- A named task follows exactly one index link; multiple title matches are listed and the agent does not guess.
- “Yesterday” reads only the configured local date file under `.ai/history/`.
- Mutations use `handoff task` commands; agents author semantic drafts but do not hand-edit generated indexes.
- Completion requires evidence and uses `handoff task complete`; inactivity, Git cleanliness, or a likely commit never imply completion.
- Existing long-task handoff activation remains independent.

Keep the adapter short enough to avoid loading task contents into every context.

- [ ] **Step 4: Add every new local-only path to installer excludes**

Extend the `for line in ...` list in `ensure_git_excludes()` with the eight paths from the test. Preserve idempotence and unrelated existing excludes.

- [ ] **Step 5: Update README in Chinese and English**

Document the task file layout, commands, query behavior, activity event policy, same-ID handoff guard, local-only default, and explicit statement that private Git sync is phase two. Do not duplicate the full design spec.

- [ ] **Step 6: Run distribution and shell checks**

Run:

```bash
python3 -m unittest tests.test_distribution -v
bash -n scripts/install.sh
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit documentation and installation support**

```bash
git add tests/test_distribution.py SKILL.md adapters/trigger-block.md scripts/install.sh README.md
git commit -m "Document and install local project tasks"
```

---

### Task 7: Stage-One End-to-End Verification

**Files:**
- Modify only if verification exposes a defect in files changed by Tasks 1–6.

**Interfaces:**
- Consumes: all stage-one deliverables.
- Produces: verified local task release candidate with no private Git sync dependency.

- [ ] **Step 1: Run the complete test suite in a harness-capable environment**

If `codex` is absent, prepend a temporary executable that prints `--dangerously-bypass-hook-trust` for `--help`, matching the existing test fixture assumption. Then run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: all existing 78 tests plus new task tests pass.

- [ ] **Step 2: Run syntax and repository checks**

```bash
python3 -m py_compile handoff.py handoff_core/*.py hooks/handoff_hook.py
bash -n scripts/install.sh scripts/uninstall.sh scripts/detect-hooks.sh
git diff --check
git status --short
```

Expected: syntax commands and diff check exit 0; status contains only intentional stage-one changes or is clean after commits.

- [ ] **Step 3: Exercise the real CLI flow in a temporary repository**

Create one task, update it with a milestone, list and show it, complete it, then verify:

- `.ai/TASKS.md` no longer contains the ID.
- `.ai/tasks/<task-id>.md` is gone.
- the local date history contains one milestone and one completed event.
- existing `handoff checkpoint`, `pause`, and `complete` still work in the same repository.

- [ ] **Step 4: Review stage-one diff against the design**

Run: `git diff 3ebbdce..HEAD --stat` and `git diff 3ebbdce..HEAD --check`.

Verify each stage-one acceptance criterion has a corresponding passing test. Do not start private Git sync until this gate passes.

- [ ] **Step 5: Create the stage-one integration commit only if fixes remain uncommitted**

```bash
git add handoff.py handoff_core tests SKILL.md adapters scripts README.md
git commit -m "Complete local project task support"
```

Skip this commit when the working tree is already clean.
