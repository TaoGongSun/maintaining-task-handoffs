from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_tasks import TASK_DRAFT


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "handoff.py"


def run_cli(
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=merged,
    )


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=path)
    git("config", "user.email", "test@example.com", cwd=path)
    git("config", "user.name", "Test", cwd=path)
    (path / "tracked.txt").write_text("x\n", encoding="utf-8")
    git("add", "tracked.txt", cwd=path)
    git("commit", "-qm", "init", cwd=path)
    return path


def payload(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    return json.loads(result.stdout)


def memory_env(config_home: Path) -> dict[str, str]:
    return {"XDG_CONFIG_HOME": str(config_home)}


def make_two_device_fixture() -> tuple[Path, Path, Path, Path, Path]:
    base = Path(tempfile.mkdtemp())
    remote = base / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    memory = base / "memory-device-a"
    subprocess.run(["git", "clone", str(remote), str(memory)], check=True, capture_output=True)
    git("config", "user.email", "test@example.com", cwd=memory)
    git("config", "user.name", "Test", cwd=memory)
    (memory / "README.md").write_text("# private memory\n", encoding="utf-8")
    git("add", "README.md", cwd=memory)
    git("commit", "-qm", "seed", cwd=memory)
    git("push", "-u", "origin", "HEAD", cwd=memory)

    first_device = init_repo(base / "project-a")
    second_device = init_repo(base / "project-b")
    # Same remote identity so both devices share project_id.
    for device in (first_device, second_device):
        git(
            "remote",
            "add",
            "origin",
            "https://github.com/example/shared-memory-project.git",
            cwd=device,
        )

    config_home = base / "config"
    return first_device, second_device, memory, remote, config_home


def clone_memory_for_second_device(remote: Path, memory_path: Path) -> Path:
    parent = memory_path.parent
    second = parent / "memory-device-b"
    if second.exists():
        subprocess.run(["rm", "-rf", str(second)], check=True)
    subprocess.run(
        ["git", "clone", str(remote), str(second)],
        check=True,
        capture_output=True,
        text=True,
    )
    git("config", "user.email", "test@example.com", cwd=second)
    git("config", "user.name", "Test", cwd=second)
    return second


def add_task_via_cli(repo: Path, task_id: str) -> None:
    draft = repo / "task.md"
    text = TASK_DRAFT.replace("project-memory", task_id)
    draft.write_text(text, encoding="utf-8")
    result = run_cli("task", "add", "--task-id", task_id, "--input", str(draft), cwd=repo)
    assert result.returncode == 0, result.stdout + result.stderr


class MemoryCliTests(unittest.TestCase):
    def test_init_upload_pull_download_and_noop(self) -> None:
        first_device, second_device, memory, remote, config_home = make_two_device_fixture()
        add_task_via_cli(first_device, "shared-task")
        initialized = run_cli(
            "memory",
            "init",
            "--path",
            str(memory),
            cwd=first_device,
            env=memory_env(config_home),
        )
        uploaded = run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))
        second_memory = clone_memory_for_second_device(remote, memory)
        # Second device uses its own config pointing at its clone.
        config_home_b = config_home.parent / "config-b"
        initialized_second = run_cli(
            "memory",
            "init",
            "--path",
            str(second_memory),
            cwd=second_device,
            env=memory_env(config_home_b),
        )
        downloaded = run_cli(
            "memory", "sync", cwd=second_device, env=memory_env(config_home_b)
        )
        current = run_cli(
            "memory",
            "sync",
            "--no-push",
            cwd=second_device,
            env=memory_env(config_home_b),
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout)
        self.assertEqual("memory_initialized", payload(initialized)["code"])
        self.assertEqual(0, uploaded.returncode, uploaded.stdout)
        self.assertEqual("memory_uploaded", payload(uploaded)["code"])
        self.assertEqual("memory_initialized", payload(initialized_second)["code"])
        self.assertEqual(0, downloaded.returncode, downloaded.stdout)
        self.assertEqual("memory_downloaded", payload(downloaded)["code"])
        self.assertEqual("memory_current", payload(current)["code"])
        self.assertIn(
            "shared-task",
            (second_device / ".ai/tasks/shared-task.md").read_text(encoding="utf-8"),
        )

    def test_missing_config_is_structured(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = init_repo(Path(temp) / "repo")
            config_home = Path(temp) / "empty-config"
            result = run_cli("memory", "status", cwd=repo, env=memory_env(config_home))
            self.assertEqual(4, result.returncode)
            self.assertEqual("memory_not_configured", payload(result)["code"])

    def test_dirty_memory_rejects_sync(self) -> None:
        first_device, _second, memory, _remote, config_home = make_two_device_fixture()
        add_task_via_cli(first_device, "shared-task")
        run_cli("memory", "init", "--path", str(memory), cwd=first_device, env=memory_env(config_home))
        run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))
        (memory / "dirty.txt").write_text("x\n", encoding="utf-8")
        result = run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))
        self.assertEqual(4, result.returncode)
        self.assertEqual("memory_dirty", payload(result)["code"])

    def test_divergence_is_structured(self) -> None:
        first_device, second_device, memory, remote, config_home = make_two_device_fixture()
        add_task_via_cli(first_device, "shared-task")
        run_cli("memory", "init", "--path", str(memory), cwd=first_device, env=memory_env(config_home))
        run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))

        second_memory = clone_memory_for_second_device(remote, memory)
        config_home_b = config_home.parent / "config-b"
        run_cli(
            "memory",
            "init",
            "--path",
            str(second_memory),
            cwd=second_device,
            env=memory_env(config_home_b),
        )
        run_cli("memory", "sync", cwd=second_device, env=memory_env(config_home_b))

        # Local change on device A.
        draft = first_device / "task.md"
        draft.write_text(
            TASK_DRAFT.replace("project-memory", "shared-task").replace(
                "parser", "device-a"
            ),
            encoding="utf-8",
        )
        run_cli(
            "task",
            "update",
            "--task-id",
            "shared-task",
            "--input",
            str(draft),
            cwd=first_device,
        )
        # Memory-only change on device B path: update task then sync from B would upload.
        # Instead mutate second_memory project snapshot and push, then try device A sync after local change.
        draft_b = second_device / "task.md"
        draft_b.write_text(
            TASK_DRAFT.replace("project-memory", "shared-task").replace(
                "parser", "device-b"
            ),
            encoding="utf-8",
        )
        run_cli(
            "task",
            "update",
            "--task-id",
            "shared-task",
            "--input",
            str(draft_b),
            cwd=second_device,
        )
        run_cli("memory", "sync", cwd=second_device, env=memory_env(config_home_b))

        # Device A has local change and remote has B's upload -> diverged after fetch.
        result = run_cli("memory", "sync", cwd=first_device, env=memory_env(config_home))
        self.assertEqual(4, result.returncode)
        self.assertEqual("memory_diverged", payload(result)["code"])


if __name__ == "__main__":
    unittest.main()
