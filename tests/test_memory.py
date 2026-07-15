from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from handoff_core.document import DocumentError
from handoff_core.task_service import TaskService
from tests.test_tasks import TASK_DRAFT, RepoCase


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True)


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run("git", "init", "-q", cwd=path)
    run("git", "config", "user.email", "test@example.com", cwd=path)
    run("git", "config", "user.name", "Test", cwd=path)
    (path / "tracked.txt").write_text("one\n", encoding="utf-8")
    run("git", "add", "tracked.txt", cwd=path)
    run("git", "commit", "-qm", "initial", cwd=path)
    return path


def commit_count(path: Path) -> int:
    result = run("git", "rev-list", "--count", "HEAD", cwd=path)
    return int(result.stdout.strip())


def commit_all(path: Path, message: str) -> None:
    run("git", "add", "-A", cwd=path)
    run("git", "commit", "-qm", message, cwd=path)


class TaskRepoCase(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.now = datetime(2026, 7, 15, 2, 0, tzinfo=timezone.utc)
        self.tasks = TaskService(self.repo, now=lambda: self.now)


class SnapshotTests(TaskRepoCase):
    def test_hash_ignores_generated_indexes_and_file_times(self) -> None:
        from handoff_core.snapshot import load_snapshot

        self.tasks.add("project-memory", TASK_DRAFT)
        first = load_snapshot(self.repo)
        (self.repo / ".ai/TASKS.md").write_text("tampered generated view\n", encoding="utf-8")
        os.utime(self.repo / ".ai/tasks/project-memory.md", (1, 1))
        second = load_snapshot(self.repo)
        self.assertEqual(first.digest, second.digest)

    def test_hash_changes_with_semantic_task_or_history(self) -> None:
        from handoff_core.snapshot import load_snapshot

        self.tasks.add("project-memory", TASK_DRAFT)
        first = load_snapshot(self.repo)
        self.tasks.milestone("project-memory", TASK_DRAFT, "Parser implemented.")
        second = load_snapshot(self.repo)
        self.assertNotEqual(first.digest, second.digest)

    def test_snapshot_rejects_symlinks_and_registry_mismatch(self) -> None:
        from handoff_core.snapshot import load_snapshot

        self.tasks.add("project-memory", TASK_DRAFT)
        task = self.repo / ".ai/tasks/project-memory.md"
        task.unlink()
        task.symlink_to(self.repo / "tracked.txt")
        with self.assertRaisesRegex(DocumentError, "snapshot_symlink"):
            load_snapshot(self.repo)


if __name__ == "__main__":
    unittest.main()
