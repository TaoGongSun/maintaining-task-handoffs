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
    if not (path / ".git").exists():
        run("git", "init", "-q", cwd=path)
        run("git", "config", "user.email", "test@example.com", cwd=path)
        run("git", "config", "user.name", "Test", cwd=path)
    tracked = path / "tracked.txt"
    if not tracked.exists():
        tracked.write_text("one\n", encoding="utf-8")
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


def create_snapshot_fixture(project_dir: Path, project_id: str, task_id: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    project = {
        "version": 1,
        "id": project_id,
        "name": project_id.split("-")[-1] if "-" in project_id else project_id,
        "remote": None,
    }
    created = "2026-07-15T09:00:00+08:00"
    updated = "2026-07-15T10:00:00+08:00"
    state = {
        "version": 1,
        "tasks": {
            task_id: {
                "status": "in-progress",
                "created": created,
                "updated": updated,
            }
        },
    }
    task_text = f"""# Task
Task-ID: {task_id}
Title: Task {task_id}
Status: in-progress
Created: {created}
Updated: {updated}

## Summary
Summary for {task_id}.

## Next action
Work on {task_id}.
"""
    history_text = f"""# Activity for 2026-07-15

<!-- event {{"kind": "milestone", "project_id": "{project_id}", "summary": "Started {task_id}.", "task_id": "{task_id}", "timestamp": "2026-07-15T09:30:00+08:00"}} -->
- 09:30 +0800 — `milestone` — `{project_id}/{task_id}`：Started {task_id}.
"""
    (project_dir / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (project_dir / "task-state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (project_dir / "tasks").mkdir(exist_ok=True)
    (project_dir / "tasks" / f"{task_id}.md").write_text(task_text, encoding="utf-8")
    (project_dir / "history").mkdir(exist_ok=True)
    (project_dir / "history" / "2026-07-15.md").write_text(history_text, encoding="utf-8")
    (project_dir / "sync.json").write_text(
        json.dumps(
            {
                "version": 1,
                "snapshot_hash": "fixture",
                "synced": "2026-07-15T11:00:00+08:00",
                "source_repo": "/tmp/fixture",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def make_duplicate_project_fixture() -> Path:
    root = Path(tempfile.mkdtemp())
    create_snapshot_fixture(root / "projects" / "github.com-owner-one", "github.com-owner-one", "task-one")
    create_snapshot_fixture(root / "projects" / "github.com-owner-dup", "github.com-owner-one", "task-dup")
    return root


def make_conflicting_history_fixture() -> Path:
    root = Path(tempfile.mkdtemp())
    project_id = "github.com-owner-one"
    create_snapshot_fixture(root / "projects" / project_id, project_id, "task-one")
    history = root / "projects" / project_id / "history" / "2026-07-15.md"
    history.write_text(
        f"""# Activity for 2026-07-15

<!-- event {{"kind": "milestone", "project_id": "{project_id}", "summary": "Summary A.", "task_id": "task-one", "timestamp": "2026-07-15T09:30:00+08:00"}} -->
- 09:30 +0800 — `milestone` — `{project_id}/task-one`：Summary A.
<!-- event {{"kind": "milestone", "project_id": "{project_id}", "summary": "Summary B.", "task_id": "task-one", "timestamp": "2026-07-15T09:30:00+08:00"}} -->
- 09:30 +0800 — `milestone` — `{project_id}/task-one`：Summary B.
""",
        encoding="utf-8",
    )
    return root


class MemoryAggregationTests(unittest.TestCase):
    def test_rebuilds_global_tasks_projects_and_history(self) -> None:
        from handoff_core.memory_service import rebuild_memory_views

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create_snapshot_fixture(
                root / "projects/github.com-owner-one", "github.com-owner-one", "task-one"
            )
            create_snapshot_fixture(
                root / "projects/github.com-owner-two", "github.com-owner-two", "task-two"
            )
            views = rebuild_memory_views(root)
            self.assertIn("github.com-owner-one", views["TASKS.md"])
            self.assertIn("task-two", views["TASKS.md"])
            self.assertIn("projects/github.com-owner-one/TASKS.md", views["PROJECTS.md"])
            self.assertIn("github.com-owner-two/task-two", views["history/2026-07-15.md"])

    def test_conflicting_project_or_event_stops_rebuild(self) -> None:
        from handoff_core.memory_service import rebuild_memory_views

        with self.assertRaisesRegex(DocumentError, "project_id_conflict"):
            rebuild_memory_views(make_duplicate_project_fixture())
        with self.assertRaisesRegex(DocumentError, "history_conflict"):
            rebuild_memory_views(make_conflicting_history_fixture())


class MemoryConfigurationTests(TaskRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.config_home = self.repo / "config-home"
        self.memory = self.repo / "memory-repo"
        init_repo(self.memory)
        from handoff_core.memory_service import MemoryService

        self.service = MemoryService(self.repo, config_home=self.config_home)

    def test_init_persists_existing_git_repository(self) -> None:
        result = self.service.init(self.memory)
        self.assertEqual("memory_initialized", result.code)
        config = json.loads(
            (self.config_home / "maintaining-task-handoffs/config.json").read_text(encoding="utf-8")
        )
        self.assertEqual(str(self.memory.resolve()), config["memory_path"])

    def test_init_rejects_non_git_directory(self) -> None:
        plain = self.repo.parent / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(DocumentError, "memory_not_git_repo"):
            self.service.init(plain)

    def test_status_reports_dirty_and_upstream(self) -> None:
        self.service.init(self.memory)
        (self.memory / "dirty").write_text("x", encoding="utf-8")
        status = self.service.status()
        self.assertTrue(status.details["dirty"])
        self.assertFalse(status.details["has_upstream"])


if __name__ == "__main__":
    unittest.main()
