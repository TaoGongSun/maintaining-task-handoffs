from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from handoff_core.document import DocumentError, parse_draft, scan_secrets
from handoff_core.git import git_metadata
from handoff_core.service import HandoffService


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
        self.service = HandoffService(self.repo, now=lambda: self.now)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def draft(self, status: str = "in-progress") -> str:
        return BASE_DRAFT.format(status=status)


class LifecycleTests(RepoCase):
    def test_pause_closes_current_run_without_completing_goal(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        result = self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)

        self.assertTrue(result.ok)
        self.assertEqual("paused", result.code)
        self.assertEqual("paused", self.service._state()["phase"])
        handoff = self.service.handoff.read_text(encoding="utf-8")
        self.assertIn("Status: in-progress", handoff)
        self.assertIn("Run the hook contract tests.", handoff)

    def test_pause_rejects_a_completed_goal(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        with self.assertRaisesRegex(DocumentError, "pause_status_completed"):
            self.service.pause("task-123", self.draft("completed"), harness="test", fresh_minutes=30)

    def test_checkpoint_resumes_a_paused_task(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)

        result = self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        self.assertTrue(result.ok)
        self.assertEqual("active", self.service._state()["phase"])


class DocumentTests(unittest.TestCase):
    @staticmethod
    def sized_draft(target_bytes: int) -> str:
        marker = "PADDING"
        skeleton = BASE_DRAFT.replace("- CLI contract.", marker).format(status="in-progress")
        fixed_bytes = len(skeleton.encode("utf-8")) - len(marker.encode("utf-8"))
        return skeleton.replace(marker, "x" * (target_bytes - fixed_bytes))

    def test_draft_size_boundary_uses_utf8_bytes(self) -> None:
        exact = self.sized_draft(8192)
        self.assertEqual(8192, len(exact.encode("utf-8")))
        self.assertEqual("in-progress", parse_draft(exact, "task-123").status)

        oversized = self.sized_draft(8193)
        with self.assertRaisesRegex(DocumentError, "handoff_too_large"):
            parse_draft(oversized, "task-123")

    def test_multibyte_draft_is_rejected_by_encoded_size(self) -> None:
        oversized = BASE_DRAFT.replace(
            "- CLI contract.", "界" * 2700
        ).format(status="in-progress")
        self.assertGreater(len(oversized.encode("utf-8")), 8192)
        with self.assertRaisesRegex(DocumentError, "handoff_too_large"):
            parse_draft(oversized, "task-123")

    def test_missing_section_is_rejected(self) -> None:
        with self.assertRaisesRegex(DocumentError, "missing_section"):
            parse_draft(BASE_DRAFT.replace("## Goal", "## Purpose").format(status="in-progress"), "task-123")

    def test_task_identity_must_match(self) -> None:
        with self.assertRaisesRegex(DocumentError, "task_id_mismatch"):
            parse_draft(BASE_DRAFT.format(status="in-progress"), "other-task")

    def test_next_action_must_be_one_non_placeholder_line(self) -> None:
        two = BASE_DRAFT.replace(
            "Run the hook contract tests.", "Run tests.\nThen publish."
        ).format(status="in-progress")
        with self.assertRaisesRegex(DocumentError, "next_action_count"):
            parse_draft(two, "task-123")

        todo = BASE_DRAFT.replace("Run the hook contract tests.", "TODO").format(status="in-progress")
        with self.assertRaisesRegex(DocumentError, "next_action_placeholder"):
            parse_draft(todo, "task-123")

    def test_completed_keeps_a_concrete_next_action(self) -> None:
        draft = BASE_DRAFT.format(status="completed")
        parsed = parse_draft(draft, "task-123")
        self.assertEqual("completed", parsed.status)
        self.assertEqual("Run the hook contract tests.", parsed.sections["Next action"])

    def test_secret_errors_name_type_and_line_but_not_value(self) -> None:
        secret = "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        findings = scan_secrets(f"safe\n{secret}\n")
        self.assertTrue(findings)
        rendered = json.dumps([item.to_dict() for item in findings])
        self.assertIn("github_token", rendered)
        self.assertIn('"line": 2', rendered)
        self.assertNotIn("ghp_", rendered)

    def test_safe_security_words_are_not_secrets(self) -> None:
        text = "Do not include secrets.\nToken count is 200.\npassword validation is required.\n"
        self.assertEqual([], scan_secrets(text))

    def test_encrypted_private_key_header_is_blocked(self) -> None:
        findings = scan_secrets("-----BEGIN ENCRYPTED PRIVATE KEY-----\n")
        self.assertEqual("private_key", findings[0].kind)


class MetadataTests(RepoCase):
    def test_git_metadata_tracks_head_branch_and_dirty_state(self) -> None:
        clean = git_metadata(self.repo)
        self.assertFalse(clean.dirty)
        self.assertEqual(run("git", "branch", "--show-current", cwd=self.repo).stdout.strip(), clean.branch)
        (self.repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
        dirty = git_metadata(self.repo)
        self.assertTrue(dirty.dirty)
        self.assertEqual(clean.head, dirty.head)

    def test_checkpoint_becomes_stale_by_time_head_branch_or_dirty_state(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.assertTrue(self.service.validate("task-123", fresh_minutes=30).ok)

        self.now += timedelta(minutes=31)
        self.assertEqual("stale_time", self.service.validate("task-123", fresh_minutes=30).code)

        self.now -= timedelta(minutes=31)
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        self.assertEqual("stale_git", self.service.validate("task-123", fresh_minutes=30).code)

    def test_more_edits_to_already_dirty_file_make_checkpoint_stale(self) -> None:
        (self.repo / "tracked.txt").write_text("dirty one\n", encoding="utf-8")
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        (self.repo / "tracked.txt").write_text("dirty two\n", encoding="utf-8")
        self.assertEqual("stale_git", self.service.validate("task-123", fresh_minutes=30).code)

    def test_task_mismatch_is_stale(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.assertEqual("task_id_mismatch", self.service.validate("other", fresh_minutes=30).code)

    def test_tampered_document_metadata_is_invalid(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        text = self.service.handoff.read_text(encoding="utf-8")
        self.service.handoff.write_text(text.replace("- Dirty: false", "- Dirty: true"), encoding="utf-8")
        self.assertEqual("metadata_mismatch", self.service.validate("task-123", fresh_minutes=30).code)

    def test_duplicate_contradictory_metadata_is_invalid(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        text = self.service.handoff.read_text(encoding="utf-8")
        self.service.handoff.write_text(
            text.replace("- Dirty: false", "- Dirty: false\n- Dirty: true"), encoding="utf-8"
        )
        self.assertEqual("metadata_mismatch", self.service.validate("task-123", fresh_minutes=30).code)


class CheckpointTests(RepoCase):
    def test_checkpoint_writes_handoff_and_state(self) -> None:
        result = self.service.checkpoint("task-123", self.draft(), harness="claude", fresh_minutes=30)
        self.assertTrue(result.ok)
        handoff = (self.repo / ".ai/HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("Updated: 2026-07-11T10:00:00+00:00", handoff)
        self.assertIn(f"- Repo: {self.repo.resolve()}", handoff)
        branch = run("git", "branch", "--show-current", cwd=self.repo).stdout.strip()
        self.assertIn(f"- Branch: {branch}", handoff)
        self.assertRegex(handoff, r"- HEAD: [0-9a-f]{40}")
        self.assertIn("- Dirty: false", handoff)
        state = json.loads((self.repo / ".ai/handoff-state.json").read_text(encoding="utf-8"))
        self.assertEqual("task-123", state["task_id"])
        self.assertEqual("active", state["phase"])

    def test_invalid_checkpoint_preserves_existing_file(self) -> None:
        target = self.repo / ".ai/HANDOFF.md"
        target.parent.mkdir()
        target.write_text("old\n", encoding="utf-8")
        with self.assertRaises(DocumentError):
            self.service.checkpoint("task-123", "bad", harness="test", fresh_minutes=30)
        self.assertEqual("old\n", target.read_text(encoding="utf-8"))

    def test_atomic_replace_failure_preserves_existing_file(self) -> None:
        target = self.repo / ".ai/HANDOFF.md"
        target.parent.mkdir()
        target.write_text("old\n", encoding="utf-8")
        with patch("handoff_core.atomic.os.replace", side_effect=OSError("simulated")):
            with self.assertRaisesRegex(OSError, "simulated"):
                self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.assertEqual("old\n", target.read_text(encoding="utf-8"))

    def test_interrupted_state_write_is_recovered_from_transaction(self) -> None:
        from handoff_core.atomic import write_json as real_write_json

        def fail_state(path: Path, value: dict) -> None:
            if path.name == "handoff-state.json":
                raise OSError("state interrupted")
            real_write_json(path, value)

        with patch("handoff_core.service.write_json", side_effect=fail_state):
            with self.assertRaisesRegex(OSError, "state interrupted"):
                self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        recovered = HandoffService(self.repo, now=lambda: self.now)
        self.assertTrue(recovered.validate("task-123", fresh_minutes=30).ok)
        self.assertFalse((self.repo / ".ai/handoff-transaction.json").exists())

    def test_no_call_means_short_task_does_not_touch_existing_handoff(self) -> None:
        target = self.repo / ".ai/HANDOFF.md"
        target.parent.mkdir()
        target.write_text("short tasks leave this alone\n", encoding="utf-8")
        self.assertEqual("short tasks leave this alone\n", target.read_text(encoding="utf-8"))
        self.assertFalse((self.repo / ".ai/handoff-state.json").exists())

    def test_different_active_task_cannot_overwrite_handoff(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        original = self.service.handoff.read_text(encoding="utf-8")
        other = BASE_DRAFT.replace("task-123", "task-456").format(status="in-progress")
        with self.assertRaisesRegex(DocumentError, "active_task_mismatch"):
            self.service.checkpoint("task-456", other, harness="test", fresh_minutes=30)
        self.assertEqual(original, self.service.handoff.read_text(encoding="utf-8"))


class CompleteTests(RepoCase):
    def completed_draft(self) -> str:
        return BASE_DRAFT.replace(
            "Run the hook contract tests.", "Read HANDOFF.md before starting follow-up work."
        ).format(status="completed")

    def test_complete_requires_active_task(self) -> None:
        result = self.service.complete("task-123", self.completed_draft(), harness="test", fresh_minutes=30)
        self.assertFalse(result.ok)
        self.assertEqual("no_active_task", result.code)

    def test_complete_rejects_task_id_mismatch(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        other = self.completed_draft().replace("task-123", "other-task")
        result = self.service.complete("other-task", other, harness="test", fresh_minutes=30)
        self.assertFalse(result.ok)
        self.assertEqual("task_id_mismatch", result.code)

    def test_complete_rejects_non_completed_draft(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        with self.assertRaisesRegex(DocumentError, "status_not_completed"):
            self.service.complete("task-123", self.draft(), harness="test", fresh_minutes=30)
        report = self.service.compliance()
        self.assertEqual(1, report["attempts"])
        self.assertEqual(0, report["valid"])

    def test_complete_accepts_stale_checkpoint_time(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.now += timedelta(minutes=31)
        result = self.service.complete("task-123", self.completed_draft(), harness="test", fresh_minutes=30)
        self.assertTrue(result.ok)

    def test_complete_accepts_current_draft_after_tracked_changes(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        result = self.service.complete("task-123", self.completed_draft(), harness="codex", fresh_minutes=30)
        self.assertTrue(result.ok)
        self.assertIn("- Dirty: true", self.service.handoff.read_text(encoding="utf-8"))

    def test_invalid_completed_draft_preserves_existing_handoff(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        original = self.service.handoff.read_text(encoding="utf-8")
        oversized = self.completed_draft().replace("- CLI contract.", "x" * 9000)
        with self.assertRaisesRegex(DocumentError, "handoff_too_large"):
            self.service.complete("task-123", oversized, harness="test", fresh_minutes=30)
        self.assertEqual(original, self.service.handoff.read_text(encoding="utf-8"))

    def test_complete_writes_completed_state_and_compliance_metrics(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        result = self.service.complete("task-123", self.completed_draft(), harness="claude", fresh_minutes=30)
        self.assertTrue(result.ok)
        state = json.loads((self.repo / ".ai/handoff-state.json").read_text(encoding="utf-8"))
        self.assertEqual("completed", state["phase"])
        report = self.service.compliance()
        self.assertEqual(1, report["attempts"])
        self.assertEqual(1, report["valid"])
        self.assertEqual(1.0, report["rate"])

    def test_complete_rechecks_git_snapshot_before_writing(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        original = git_metadata(self.repo)
        changed = original.__class__(
            original.repo, original.branch, original.head, True, "changed-fingerprint"
        )
        with patch("handoff_core.service.git_metadata", side_effect=[original, changed]):
            result = self.service.complete(
                "task-123", self.completed_draft(), harness="test", fresh_minutes=30
            )
        self.assertFalse(result.ok)
        self.assertEqual("stale_git", result.code)
        self.assertEqual("active", json.loads(self.service.state_path.read_text())["phase"])


if __name__ == "__main__":
    unittest.main()
