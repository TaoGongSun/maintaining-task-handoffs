import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "handoff.py"


class CliContractTests(unittest.TestCase):
    def run_cli(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_help_lists_three_commands(self) -> None:
        result = self.run_cli("--help")
        self.assertEqual(0, result.returncode)
        self.assertIn("checkpoint", result.stdout)
        self.assertIn("validate", result.stdout)
        self.assertIn("complete", result.stdout)

    def test_unknown_command_is_usage_error(self) -> None:
        result = self.run_cli("unknown")
        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)

    def test_commands_reject_non_git_directory_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_cli("validate", cwd=Path(temp))

        self.assertEqual(3, result.returncode)
        payload = json.loads(result.stdout)
        self.assertEqual("not_git_repo", payload["code"])
        self.assertFalse(payload["ok"])

    def test_checkpoint_validate_and_complete_flow(self) -> None:
        draft = """# Task handoff
Task-ID: cli-task
Status: in-progress

## Goal
Test the CLI.
## Current state
Ready.
## Completed
- Drafted.
## Verification
- Test fixture created.
## Remaining
- Complete.
## Next action
Run completion.
## Constraints
- Local only.
"""
        completed = draft.replace("Status: in-progress", "Status: completed").replace(
            "Run completion.", "你目前不需要做任何事。"
        )
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "tracked").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "tracked"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
            draft_path = repo / ".ai/draft.md"
            draft_path.parent.mkdir()
            draft_path.write_text(draft, encoding="utf-8")

            checkpoint = self.run_cli(
                "checkpoint", "--task-id", "cli-task", "--input", str(draft_path),
                "--harness", "test", cwd=repo
            )
            self.assertEqual(0, checkpoint.returncode, checkpoint.stderr)
            self.assertEqual("checkpoint_valid", json.loads(checkpoint.stdout)["code"])

            validate = self.run_cli("validate", "--task-id", "cli-task", cwd=repo)
            self.assertEqual(0, validate.returncode)
            self.assertEqual("valid", json.loads(validate.stdout)["code"])

            (repo / "tracked").write_text("changed", encoding="utf-8")
            draft_path.write_text(completed, encoding="utf-8")
            complete = self.run_cli(
                "complete", "--task-id", "cli-task", "--input", str(draft_path),
                "--harness", "test", cwd=repo
            )
            self.assertEqual(0, complete.returncode, complete.stdout)
            handoff = (repo / ".ai/HANDOFF.md").read_text(encoding="utf-8")
            self.assertIn("- Dirty: true", handoff)

            report = self.run_cli("compliance", cwd=repo)
            self.assertEqual(0, report.returncode)
            self.assertEqual({"attempts": 1, "rate": 1.0, "valid": 1}, json.loads(report.stdout))

    def test_validation_error_is_structured_and_does_not_echo_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            bad = repo / "bad.md"
            secret = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
            bad.write_text(f"token = {secret}\n", encoding="utf-8")
            result = self.run_cli(
                "checkpoint", "--task-id", "bad", "--input", str(bad), cwd=repo
            )
        self.assertEqual(4, result.returncode)
        self.assertEqual("secret_detected", json.loads(result.stdout)["code"])
        self.assertNotIn(secret, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
