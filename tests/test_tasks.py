from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from handoff_core.activity import ActivityEvent, merge_event, parse_activity, render_activity
from handoff_core.document import DocumentError
from handoff_core.project import load_or_create_project
from handoff_core.service import HandoffService
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

BASE_DRAFT = """# Task handoff
Task-ID: task-123
Status: {status}

## Goal
Ship the handoff gate.

## Current state
Implementation is under test.

## Completed
- CLI contract.

## Verification
- Unit tests were run.

## Remaining
- Hook integration.

## Next action
Run the hook contract tests.

## Constraints
- Do not commit local state.
"""


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        run("git", "init", "-q", cwd=self.repo)
        run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Test", cwd=self.repo)
        (self.repo / "tracked.txt").write_text("one\n", encoding="utf-8")
        run("git", "add", "tracked.txt", cwd=self.repo)
        run("git", "commit", "-qm", "initial", cwd=self.repo)
        self.now = datetime(2026, 7, 11, 10, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp.cleanup()


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
            "invalid_task_metadata": TASK_DRAFT.replace(
                "Status: in-progress\n",
                "Status: in-progress\nCreated: 2026-07-15T09:00:00+08:00\n",
            ),
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

    def test_index_sorts_equal_timestamps_by_task_id_ascending(self) -> None:
        first = parse_task_draft(
            TASK_DRAFT.replace("project-memory", "alpha-task")
            .replace("Build project memory", "Alpha task")
            .replace("Implement the task parser.", "Work on alpha."),
            "alpha-task",
        )
        second = parse_task_draft(
            TASK_DRAFT.replace("project-memory", "beta-task")
            .replace("Build project memory", "Beta task")
            .replace("Implement the task parser.", "Work on beta."),
            "beta-task",
        )
        registry = {
            "beta-task": {"status": "in-progress", "updated": "2026-07-15T10:00:00+08:00"},
            "alpha-task": {"status": "in-progress", "updated": "2026-07-15T10:00:00+08:00"},
        }

        text = render_task_index(registry, {"alpha-task": first, "beta-task": second})

        self.assertLess(text.index("[alpha-task]"), text.index("[beta-task]"))


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
        # Manual cleanup because TemporaryDirectory cleanup was disabled for the rename.
        import shutil

        shutil.rmtree(moved, ignore_errors=True)

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
        handoff.checkpoint(
            "project-memory",
            BASE_DRAFT.replace("task-123", "project-memory").format(status="in-progress"),
            "test",
            30,
        )
        with self.assertRaisesRegex(DocumentError, "handoff_still_open"):
            self.tasks.complete("project-memory", "Local task support shipped.")

    def test_legacy_open_handoff_blocks_task_completion(self) -> None:
        ai = self.repo / ".ai"
        ai.mkdir(exist_ok=True)
        (ai / "HANDOFF.md").write_text(
            BASE_DRAFT.replace("task-123", "project-memory").format(status="blocked"),
            encoding="utf-8",
        )
        (ai / "handoff-state.json").write_text(
            json.dumps(
                {
                    "phase": "paused",
                    "task_id": "project-memory",
                    "updated": "2026-07-11T10:00:00+00:00",
                    "fresh_minutes": 30,
                    "harness": "legacy",
                    "git": {},
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

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


if __name__ == "__main__":
    unittest.main()
