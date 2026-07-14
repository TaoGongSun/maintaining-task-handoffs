from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from handoff_core.document import DocumentError
from handoff_core.service import HandoffService


ROOT = Path(__file__).resolve().parents[1]


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, check=True, capture_output=True, text=True)


def make_repo(root: Path) -> Path:
    run(root, "git", "init", "-q")
    run(root, "git", "config", "user.email", "test@example.com")
    run(root, "git", "config", "user.name", "Test")
    (root / "seed").write_text("seed\n", encoding="utf-8")
    run(root, "git", "add", "seed")
    run(root, "git", "commit", "-qm", "seed")
    return root


def draft(task_id: str, status: str, plans: list[str]) -> str:
    action = "檢查交接文件並決定下一個具體動作。" if status == "completed" else "繼續實作。"
    plan_section = ""
    if plans:
        plan_section = "\n## Plan files\n" + "\n".join(f"- {item}" for item in plans) + "\n"
    return f"""# Task handoff
Task-ID: {task_id}
Status: {status}

## Goal
完成測試。

## Current state
進行中。

## Completed
已建立案例。

## Verification
執行測試。
{plan_section}
## Remaining
完成流程。

## Next action
{action}

## Constraints
只處理明列計畫。
"""


class PlanArchivalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self.temp.name))
        self.now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        self.service = HandoffService(self.root, now=lambda: self.now)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def activate(self, task_id: str, plans: list[str]) -> None:
        self.service.checkpoint(task_id, draft(task_id, "in-progress", plans), "test", 30)

    def complete(self, task_id: str, plans: list[str]):
        return self.service.complete(task_id, draft(task_id, "completed", plans), "test", 30)

    def write(self, relative: str, content: str = "plan\n") -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_complete_archives_only_listed_plan(self) -> None:
        listed = self.write("docs/feature/plan.md", "listed\n")
        unlisted = self.write("docs/feature/other.md", "unlisted\n")
        self.activate("task-1", ["docs/feature/plan.md"])

        self.assertTrue(self.complete("task-1", ["docs/feature/plan.md"]).ok)

        self.assertFalse(listed.exists())
        self.assertEqual("listed\n", (self.root / "docs/feature/archive/2026/plan.md").read_text())
        self.assertEqual("unlisted\n", unlisted.read_text())

    def test_pause_preserves_listed_plan(self) -> None:
        listed = self.write("docs/feature/plan.md", "listed\n")
        self.activate("paused-task", ["docs/feature/plan.md"])

        result = self.service.pause(
            "paused-task", draft("paused-task", "in-progress", ["docs/feature/plan.md"]), "test", 30
        )

        self.assertTrue(result.ok)
        self.assertTrue(listed.exists())
        self.assertFalse((self.root / "docs/feature/archive/2026/plan.md").exists())

    def test_ai_plan_uses_ai_archive_and_preserves_subdirectories(self) -> None:
        self.write(".ai/plans/feature/plan.md")
        self.activate("task-2", [".ai/plans/feature/plan.md"])
        self.complete("task-2", [".ai/plans/feature/plan.md"])
        self.assertTrue((self.root / ".ai/archive/plans/2026/feature/plan.md").is_file())

    def test_destination_conflict_blocks_all_moves(self) -> None:
        first = self.write("docs/first.md")
        second = self.write("docs/second.md")
        self.write("docs/archive/2026/second.md", "existing\n")
        plans = ["docs/first.md", "docs/second.md"]
        self.activate("task-3", plans)
        with self.assertRaisesRegex(DocumentError, "plan_archive_conflict"):
            self.complete("task-3", plans)
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertFalse((self.root / "docs/archive/2026/first.md").exists())

    def test_runtime_move_failure_rolls_back_prior_moves(self) -> None:
        first = self.write("docs/first.md")
        second = self.write("docs/second.md")
        plans = ["docs/first.md", "docs/second.md"]
        self.activate("move-failure", plans)
        calls = 0

        def fail_second_move(source: Path, destination: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated move failure")
            os.replace(source, destination)

        with patch("handoff_core.service.os.replace", side_effect=fail_second_move):
            with self.assertRaisesRegex(OSError, "simulated move failure"):
                self.complete("move-failure", plans)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())
        self.assertFalse((self.root / "docs/archive/2026/first.md").exists())
        self.assertEqual("active", json.loads(self.service.state_path.read_text())["phase"])

    def test_rejects_outside_absolute_missing_duplicate_and_archived_paths(self) -> None:
        cases = (
            (["../outside.md"], "plan_path_outside_repo"),
            ([str(self.root / "absolute.md")], "plan_path_outside_repo"),
            (["docs/missing.md"], "plan_file_missing"),
            (["docs/plan.md", "docs/plan.md"], "duplicate_plan_file"),
            (["docs/archive/2025/plan.md"], "plan_already_archived"),
        )
        self.write("docs/plan.md")
        self.write("docs/archive/2025/plan.md")
        for index, (plans, code) in enumerate(cases):
            with self.subTest(code=code):
                task = f"invalid-{index}"
                if code == "duplicate_plan_file":
                    with self.assertRaisesRegex(DocumentError, code):
                        self.service.checkpoint(task, draft(task, "in-progress", plans), "test", 30)
                    continue
                self.activate(task, plans)
                with self.assertRaisesRegex(DocumentError, code):
                    self.complete(task, plans)
                self.service.state_path.unlink()

    def test_rejects_source_and_parent_symlinks(self) -> None:
        real = self.write("real/plan.md")
        (self.root / "linked.md").symlink_to(real)
        (self.root / "linked-dir").symlink_to(self.root / "real", target_is_directory=True)
        for index, path in enumerate(("linked.md", "linked-dir/plan.md")):
            task = f"symlink-{index}"
            self.activate(task, [path])
            with self.assertRaisesRegex(DocumentError, "plan_symlink_rejected"):
                self.complete(task, [path])
            self.service.state_path.unlink()

    def test_checkpoint_and_blocked_drafts_do_not_archive(self) -> None:
        plan = self.write("docs/plan.md")
        self.activate("task-active", ["docs/plan.md"])
        self.assertTrue(plan.exists())
        blocked = draft("task-active", "in-progress", ["docs/plan.md"]).replace(
            "Status: in-progress", "Status: blocked"
        )
        self.service.checkpoint("task-active", blocked, "test", 30)
        self.assertTrue(plan.exists())

    def test_completion_write_failure_restores_plans_and_active_state(self) -> None:
        plan = self.write("docs/plan.md")
        self.activate("rollback", ["docs/plan.md"])
        real_write_json = __import__("handoff_core.service", fromlist=["write_json"]).write_json

        def fail_completed_state(path: Path, value: dict) -> None:
            if path == self.service.state_path and value.get("phase") == "completed":
                raise OSError("simulated state failure")
            real_write_json(path, value)

        with patch("handoff_core.service.write_json", side_effect=fail_completed_state):
            with self.assertRaisesRegex(OSError, "simulated state failure"):
                self.complete("rollback", ["docs/plan.md"])
        self.assertTrue(plan.is_file())
        self.assertFalse((self.root / "docs/archive/2026/plan.md").exists())
        state = json.loads(self.service.state_path.read_text())
        self.assertEqual("active", state["phase"])
        self.assertFalse(self.service.transaction_path.exists())


class PlanArchivalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(ROOT / "handoff.py"), *args], cwd=self.root,
            capture_output=True, text=True, check=False,
        )

    def write_draft(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_cli_reports_success_and_archives_plan(self) -> None:
        plan = self.root / "plan.md"
        plan.write_text("plan\n", encoding="utf-8")
        active = self.write_draft("active.md", draft("cli-ok", "in-progress", ["plan.md"]))
        completed = self.write_draft("completed.md", draft("cli-ok", "completed", ["plan.md"]))
        self.assertEqual(0, self.cli("checkpoint", "--task-id", "cli-ok", "--input", str(active)).returncode)
        result = self.cli("complete", "--task-id", "cli-ok", "--input", str(completed))
        self.assertEqual(0, result.returncode)
        self.assertEqual({"code": "completed", "ok": True}, json.loads(result.stdout))
        self.assertTrue((self.root / "archive/2026/plan.md").is_file())

    def test_cli_reports_failure_without_moving_any_plan(self) -> None:
        first = self.root / "first.md"
        second = self.root / "second.md"
        first.write_text("first\n", encoding="utf-8")
        second.write_text("second\n", encoding="utf-8")
        conflict = self.root / "archive" / str(datetime.now().year) / "second.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("existing\n", encoding="utf-8")
        plans = ["first.md", "second.md"]
        active = self.write_draft("active.md", draft("cli-fail", "in-progress", plans))
        completed = self.write_draft("completed.md", draft("cli-fail", "completed", plans))
        self.cli("checkpoint", "--task-id", "cli-fail", "--input", str(active))
        result = self.cli("complete", "--task-id", "cli-fail", "--input", str(completed))
        self.assertEqual(4, result.returncode)
        self.assertEqual({"code": "plan_archive_conflict", "ok": False}, json.loads(result.stdout))
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())


if __name__ == "__main__":
    unittest.main()
