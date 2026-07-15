from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_tasks import TASK_DRAFT


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "handoff.py"


def run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def init_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "tracked").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "tracked"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


class TaskCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = init_repo(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_task_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = init_repo(Path(temp))
            draft = repo / "task.md"
            draft.write_text(TASK_DRAFT, encoding="utf-8")
            added = run_cli("task", "add", "--task-id", "project-memory", "--input", str(draft), cwd=repo)
            listed = run_cli("task", "list", cwd=repo)
            shown = run_cli("task", "show", "--task-id", "project-memory", cwd=repo)
            milestone = run_cli(
                "task",
                "milestone",
                "--task-id",
                "project-memory",
                "--input",
                str(draft),
                "--summary",
                "Parser implemented.",
                cwd=repo,
            )
            completed = run_cli(
                "task",
                "complete",
                "--task-id",
                "project-memory",
                "--summary",
                "Local task support shipped.",
                cwd=repo,
            )
            self.assertEqual(0, added.returncode, added.stderr or added.stdout)
            self.assertEqual("task_added", json.loads(added.stdout)["code"])
            self.assertIn("project-memory", listed.stdout)
            self.assertIn("Title: Build project memory", shown.stdout)
            self.assertEqual("milestone_recorded", json.loads(milestone.stdout)["code"])
            self.assertEqual("task_completed", json.loads(completed.stdout)["code"])

    def test_task_errors_are_structured(self) -> None:
        result = run_cli("task", "show", "--task-id", "missing", cwd=self.repo)
        self.assertEqual(4, result.returncode)
        self.assertEqual("task_missing", json.loads(result.stdout)["code"])


if __name__ == "__main__":
    unittest.main()
