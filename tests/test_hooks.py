from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from handoff_core.service import HandoffService
from tests.test_handoff import BASE_DRAFT, run


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks/handoff_hook.py"


class HookContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        run("git", "init", "-q", cwd=self.repo)
        run("git", "config", "user.email", "test@example.com", cwd=self.repo)
        run("git", "config", "user.name", "Test", cwd=self.repo)
        (self.repo / "tracked").write_text("x", encoding="utf-8")
        run("git", "add", "tracked", cwd=self.repo)
        run("git", "commit", "-qm", "init", cwd=self.repo)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def call(self, event: str, **extra: object) -> subprocess.CompletedProcess[str]:
        payload = {"cwd": str(self.repo), "hook_event_name": event, **extra}
        return subprocess.run(
            ["python3", str(HOOK), "--harness", "claude"],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
        )

    def checkpoint(self) -> HandoffService:
        service = HandoffService(self.repo)
        service.checkpoint(
            "hook-task", BASE_DRAFT.replace("task-123", "hook-task").format(status="in-progress"),
            "test", 30,
        )
        return service

    def test_no_active_task_allows_precompact_and_stop(self) -> None:
        for event in ("PreCompact", "Stop"):
            result = self.call(event)
            self.assertEqual(0, result.returncode)
            self.assertEqual({}, json.loads(result.stdout))

    def test_precompact_blocks_stale_active_task(self) -> None:
        service = self.checkpoint()
        state = json.loads(service.state_path.read_text(encoding="utf-8"))
        state["updated"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        service.state_path.write_text(json.dumps(state), encoding="utf-8")
        result = self.call("PreCompact", trigger="auto")
        output = json.loads(result.stdout)
        self.assertEqual("block", output["decision"])
        self.assertIn("handoff checkpoint", output["reason"])
        self.assertNotIn("Goal", output["reason"])

    def test_precompact_allows_fresh_checkpoint(self) -> None:
        self.checkpoint()
        result = self.call("PreCompact", trigger="manual")
        self.assertEqual({}, json.loads(result.stdout))

    def test_stop_blocks_active_task_without_looping(self) -> None:
        self.checkpoint()
        first = json.loads(self.call("Stop", stop_hook_active=False).stdout)
        self.assertEqual("block", first["decision"])
        self.assertIn("handoff pause", first["reason"])
        self.assertIn("handoff complete", first["reason"])
        repeated = json.loads(self.call("Stop", stop_hook_active=True).stdout)
        self.assertFalse(repeated["continue"])
        self.assertIn("Blocked failure", repeated["stopReason"])
        report = HandoffService(self.repo).compliance()
        self.assertEqual(2, report["attempts"])
        self.assertEqual(0, report["valid"])

    def test_stop_allows_a_deliberately_paused_task(self) -> None:
        service = self.checkpoint()
        draft = BASE_DRAFT.replace("task-123", "hook-task").format(status="in-progress")
        service.pause("hook-task", draft, "test", 30)

        result = self.call("Stop", stop_hook_active=False)

        self.assertEqual({}, json.loads(result.stdout))
        self.assertEqual("paused", HandoffService(self.repo)._state()["phase"])

    def test_session_end_records_unfinished_task_but_does_not_claim_repair(self) -> None:
        self.checkpoint()
        result = self.call("SessionEnd", reason="prompt_input_exit")
        self.assertEqual({}, json.loads(result.stdout))
        log = (self.repo / ".ai/handoff-hook-errors.jsonl").read_text(encoding="utf-8")
        self.assertIn('"event": "SessionEnd"', log)
        self.assertIn('"reason": "unfinished_at_session_end"', log)
        self.assertNotIn("checkpoint_valid", log)
        report = HandoffService(self.repo).compliance()
        self.assertEqual(1, report["attempts"])
        self.assertEqual(0, report["valid"])

    def test_invalid_input_is_visible_and_nonzero(self) -> None:
        result = subprocess.run(
            ["python3", str(HOOK), "--harness", "codex"],
            input="not json", text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("invalid_hook_input", result.stderr)


if __name__ == "__main__":
    unittest.main()
