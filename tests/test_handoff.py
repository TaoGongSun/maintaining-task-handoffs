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
        state = self.service._state()
        self.assertIsNone(state["active_task_id"])
        self.assertEqual("paused", state["tasks"]["task-123"]["phase"])
        task_document = self.service._task_path("task-123").read_text(encoding="utf-8")
        self.assertIn("Status: in-progress", task_document)
        self.assertIn("Run the hook contract tests.", task_document)

    def test_pause_rejects_a_completed_goal(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        with self.assertRaisesRegex(DocumentError, "pause_status_completed"):
            self.service.pause("task-123", self.draft("completed"), harness="test", fresh_minutes=30)

    def test_checkpoint_resumes_a_paused_task(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)

        result = self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        self.assertTrue(result.ok)
        self.assertEqual("task-123", self.service._state()["active_task_id"])
        self.assertEqual("active", self.service._state()["tasks"]["task-123"]["phase"])


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
        target = self.service._task_path("task-123")
        text = target.read_text(encoding="utf-8")
        target.write_text(text.replace("- Dirty: false", "- Dirty: true"), encoding="utf-8")
        self.assertEqual("metadata_mismatch", self.service.validate("task-123", fresh_minutes=30).code)

    def test_duplicate_contradictory_metadata_is_invalid(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        target = self.service._task_path("task-123")
        text = target.read_text(encoding="utf-8")
        target.write_text(
            text.replace("- Dirty: false", "- Dirty: false\n- Dirty: true"), encoding="utf-8"
        )
        self.assertEqual("metadata_mismatch", self.service.validate("task-123", fresh_minutes=30).code)


class CheckpointTests(RepoCase):
    def test_checkpoint_writes_handoff_and_state(self) -> None:
        result = self.service.checkpoint("task-123", self.draft(), harness="claude", fresh_minutes=30)
        self.assertTrue(result.ok)
        index = (self.repo / ".ai/HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("[task-123](handoffs/task-123.md)", index)
        task_document = self.service._task_path("task-123").read_text(encoding="utf-8")
        self.assertIn("Updated: 2026-07-11T10:00:00+00:00", task_document)
        self.assertIn(f"- Repo: {self.repo.resolve()}", task_document)
        branch = run("git", "branch", "--show-current", cwd=self.repo).stdout.strip()
        self.assertIn(f"- Branch: {branch}", task_document)
        self.assertRegex(task_document, r"- HEAD: [0-9a-f]{40}")
        self.assertIn("- Dirty: false", task_document)
        state = json.loads((self.repo / ".ai/handoff-state.json").read_text(encoding="utf-8"))
        self.assertEqual(2, state["version"])
        self.assertEqual("task-123", state["active_task_id"])
        self.assertEqual("active", state["tasks"]["task-123"]["phase"])

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


class MultiTaskIndexTests(RepoCase):
    def other_draft(self, task_id: str = "task-456", status: str = "in-progress") -> str:
        return BASE_DRAFT.replace("task-123", task_id).format(status=status)

    def test_paused_task_moves_to_task_document_and_stays_in_index(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)

        task_document = self.repo / ".ai/handoffs/task-123.md"
        self.assertTrue(task_document.is_file())
        self.assertIn("Task-ID: task-123", task_document.read_text(encoding="utf-8"))
        index = self.service.handoff.read_text(encoding="utf-8")
        self.assertIn("# Task handoffs", index)
        self.assertIn("[task-123](handoffs/task-123.md)", index)
        self.assertIn("paused", index)

    def test_multiple_paused_tasks_survive_a_new_checkpoint(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.checkpoint("task-456", self.other_draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-456", self.other_draft(), harness="test", fresh_minutes=30)

        registry = json.loads(self.service.state_path.read_text(encoding="utf-8"))
        self.assertEqual(2, registry["version"])
        self.assertIsNone(registry["active_task_id"])
        self.assertEqual({"task-123", "task-456"}, set(registry["tasks"]))
        self.assertEqual("paused", registry["tasks"]["task-123"]["phase"])
        self.assertEqual("paused", registry["tasks"]["task-456"]["phase"])
        index = self.service.handoff.read_text(encoding="utf-8")
        self.assertIn("[task-123](handoffs/task-123.md)", index)
        self.assertIn("[task-456](handoffs/task-456.md)", index)

    def test_only_one_task_can_be_active(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        with self.assertRaisesRegex(DocumentError, "active_task_mismatch"):
            self.service.checkpoint("task-456", self.other_draft(), harness="test", fresh_minutes=30)

        registry = json.loads(self.service.state_path.read_text(encoding="utf-8"))
        self.assertEqual("task-123", registry["active_task_id"])
        self.assertNotIn("task-456", registry["tasks"])

    def test_legacy_unfinished_handoff_is_preserved_when_state_points_to_completed_task(self) -> None:
        ai = self.repo / ".ai"
        ai.mkdir()
        legacy = self.other_draft("ssw03").replace("Status: in-progress", "Status: paused（later）")
        (ai / "HANDOFF.md").write_text(legacy, encoding="utf-8")
        (ai / "handoff-state.json").write_text(
            json.dumps({"task_id": "different-completed-task", "phase": "completed"}),
            encoding="utf-8",
        )
        service = HandoffService(self.repo, now=lambda: self.now)

        service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)

        self.assertEqual(legacy, (ai / "handoffs/ssw03.md").read_text(encoding="utf-8"))
        registry = json.loads((ai / "handoff-state.json").read_text(encoding="utf-8"))
        self.assertEqual("paused", registry["tasks"]["ssw03"]["phase"])
        self.assertEqual("task-123", registry["active_task_id"])

    def test_unsafe_task_ids_are_rejected_before_writing(self) -> None:
        for task_id in ("../escape", "nested/task", ".", "two words"):
            with self.subTest(task_id=task_id):
                draft = BASE_DRAFT.replace("task-123", task_id).format(status="in-progress")
                with self.assertRaisesRegex(DocumentError, "unsafe_task_id"):
                    self.service.checkpoint(task_id, draft, harness="test", fresh_minutes=30)

        self.assertFalse((self.repo / ".ai/handoffs").exists())

    def test_corrupt_registry_cannot_create_a_second_active_task(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        registry = json.loads(self.service.state_path.read_text(encoding="utf-8"))
        registry["active_task_id"] = None
        self.service.state_path.write_text(json.dumps(registry), encoding="utf-8")

        with self.assertRaisesRegex(DocumentError, "invalid_state"):
            self.service.checkpoint(
                "task-456", self.other_draft(), harness="test", fresh_minutes=30
            )

        self.assertFalse(self.service._task_path("task-456").exists())

    def test_registry_rejects_missing_active_entry_and_unsafe_task_key(self) -> None:
        cases = (
            {"version": 2, "active_task_id": "missing", "tasks": {}},
            {
                "version": 2,
                "active_task_id": None,
                "tasks": {"../escape": {"phase": "paused", "status": "in-progress"}},
            },
        )
        for registry in cases:
            with self.subTest(registry=registry):
                self.service.state_path.parent.mkdir(exist_ok=True)
                self.service.state_path.write_text(json.dumps(registry), encoding="utf-8")
                with self.assertRaisesRegex(DocumentError, "invalid_state"):
                    self.service.checkpoint(
                        "task-456", self.other_draft(), harness="test", fresh_minutes=30
                    )


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
        self.assertFalse(self.service._task_path("task-123").exists())
        self.assertIn("## Active\n- None.", self.service.handoff.read_text(encoding="utf-8"))

    def test_invalid_completed_draft_preserves_existing_handoff(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        original = self.service.handoff.read_text(encoding="utf-8")
        oversized = self.completed_draft().replace("- CLI contract.", "x" * 9000)
        with self.assertRaisesRegex(DocumentError, "handoff_too_large"):
            self.service.complete("task-123", oversized, harness="test", fresh_minutes=30)
        self.assertEqual(original, self.service.handoff.read_text(encoding="utf-8"))

    def test_complete_removes_task_state_and_writes_compliance_metrics(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        result = self.service.complete("task-123", self.completed_draft(), harness="claude", fresh_minutes=30)
        self.assertTrue(result.ok)
        state = json.loads((self.repo / ".ai/handoff-state.json").read_text(encoding="utf-8"))
        self.assertIsNone(state["active_task_id"])
        self.assertNotIn("task-123", state["tasks"])
        self.assertFalse(self.service._task_path("task-123").exists())
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
        state = json.loads(self.service.state_path.read_text())
        self.assertEqual("task-123", state["active_task_id"])
        self.assertEqual("active", state["tasks"]["task-123"]["phase"])

    def test_complete_removes_only_target_and_preserves_paused_task(self) -> None:
        self.service.checkpoint("task-123", self.draft(), harness="test", fresh_minutes=30)
        self.service.pause("task-123", self.draft(), harness="test", fresh_minutes=30)
        other = BASE_DRAFT.replace("task-123", "task-456").format(status="in-progress")
        completed_other = other.replace("Status: in-progress", "Status: completed")
        self.service.checkpoint("task-456", other, harness="test", fresh_minutes=30)

        result = self.service.complete(
            "task-456", completed_other, harness="test", fresh_minutes=30
        )

        self.assertTrue(result.ok)
        state = json.loads(self.service.state_path.read_text(encoding="utf-8"))
        self.assertEqual({"task-123"}, set(state["tasks"]))
        self.assertTrue(self.service._task_path("task-123").exists())
        self.assertFalse(self.service._task_path("task-456").exists())
        index = self.service.handoff.read_text(encoding="utf-8")
        self.assertIn("[task-123](handoffs/task-123.md)", index)
        self.assertNotIn("task-456", index)


if __name__ == "__main__":
    unittest.main()
