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


if __name__ == "__main__":
    unittest.main()
