import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HookAssetTests(unittest.TestCase):
    def test_claude_and_codex_configs_use_shared_hook(self) -> None:
        claude = json.loads((ROOT / "hooks/claude/hooks.json").read_text(encoding="utf-8"))["hooks"]
        codex = json.loads((ROOT / "hooks/codex/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual({"PreCompact", "Stop", "SessionEnd"}, set(claude))
        self.assertEqual({"PreCompact", "Stop"}, set(codex))
        for harness, config in (("claude", claude), ("codex", codex)):
            for event in ("PreCompact", "Stop"):
                command = config[event][0]["hooks"][0]["command"]
                self.assertIn("hooks/handoff_hook.py", command)
                self.assertIn(f"--harness {harness}", command)

    def test_capability_detector_reports_installed_harnesses(self) -> None:
        result = subprocess.run(
            ["bash", str(ROOT / "scripts/detect-hooks.sh")],
            text=True, capture_output=True, check=True,
        )
        self.assertRegex(result.stdout, r"claude=hooks-(?:detected|unverified)")
        self.assertRegex(result.stdout, r"codex=hooks-(?:detected|unverified)")
        self.assertIn("does not imply trust", result.stdout)


if __name__ == "__main__":
    unittest.main()
