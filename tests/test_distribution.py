import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_names_soft_activation_and_three_hard_gates(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("soft", text.lower())
        self.assertIn("handoff checkpoint", text)
        self.assertIn("PreCompact", text)
        self.assertIn("handoff complete", text)
        self.assertIn("Short tasks", text)
        self.assertIn("cannot guarantee", text)

    def test_adapter_requires_cli_after_activation(self) -> None:
        text = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8")
        self.assertIn("handoff checkpoint", text)
        self.assertIn("handoff complete", text)
        self.assertIn("Do not activate", text)


class HookMergeTests(unittest.TestCase):
    def test_merge_and_remove_preserve_unrelated_hooks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "hooks.json"
            target.write_text(
                json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}),
                encoding="utf-8",
            )
            source = ROOT / "hooks/codex/hooks.json"
            subprocess.run(
                ["python3", str(ROOT / "scripts/merge_hooks.py"), "install", str(target), str(source)],
                check=True,
            )
            merged = json.loads(target.read_text(encoding="utf-8"))
            commands = [h["command"] for group in merged["hooks"]["Stop"] for h in group["hooks"]]
            self.assertIn("other", commands)
            self.assertTrue(any("maintaining-task-handoffs" in command for command in commands))
            subprocess.run(
                ["python3", str(ROOT / "scripts/merge_hooks.py"), "remove", str(target)], check=True
            )
            cleaned = json.loads(target.read_text(encoding="utf-8"))
            commands = [h["command"] for group in cleaned["hooks"]["Stop"] for h in group["hooks"]]
            self.assertEqual(["other"], commands)


class InstallerTests(unittest.TestCase):
    def test_install_is_idempotent_and_installs_cli_hooks_and_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            env = {**os.environ, "HOME": str(home)}
            command = ["bash", str(ROOT / "scripts/install.sh"), "--no-gitignore"]
            subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            first_claude = (home / ".claude/settings.json").read_text(encoding="utf-8")
            first_codex = (home / ".codex/hooks.json").read_text(encoding="utf-8")
            subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
            skill = home / ".agents/skills/maintaining-task-handoffs"
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "handoff.py").is_file())
            self.assertTrue((skill / "hooks/handoff_hook.py").is_file())
            self.assertTrue((home / ".local/bin/handoff").is_symlink())
            claude = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
            codex = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(first_claude, json.dumps(claude, ensure_ascii=False, indent=2) + "\n")
            self.assertEqual(first_codex, json.dumps(codex, ensure_ascii=False, indent=2) + "\n")
            for config in (claude, codex):
                commands = [
                    hook["command"]
                    for groups in config["hooks"].values()
                    for group in groups
                    for hook in group["hooks"]
                ]
                managed = [command for command in commands if "maintaining-task-handoffs" in command]
                self.assertGreaterEqual(len(managed), 2)

            subprocess.run(
                ["bash", str(ROOT / "scripts/uninstall.sh")],
                cwd=ROOT, env=env, check=True, capture_output=True, text=True,
            )
            self.assertFalse(skill.exists())
            self.assertFalse((home / ".local/bin/handoff").exists())
            for path in (home / ".claude/settings.json", home / ".codex/hooks.json"):
                remaining = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn("maintaining-task-handoffs", json.dumps(remaining))

    def test_install_refuses_to_replace_unrelated_handoff_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            binary = home / ".local/bin/handoff"
            binary.parent.mkdir(parents=True)
            binary.write_text("unrelated\n", encoding="utf-8")
            env = {**os.environ, "HOME": str(home)}
            result = subprocess.run(
                ["bash", str(ROOT / "scripts/install.sh"), "--skill-only", "--no-gitignore"],
                cwd=ROOT, env=env, check=False, capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual("unrelated\n", binary.read_text(encoding="utf-8"))

    def test_skill_only_does_not_create_hook_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            env = {**os.environ, "HOME": str(home)}
            subprocess.run(
                ["bash", str(ROOT / "scripts/install.sh"), "--skill-only", "--no-gitignore"],
                cwd=ROOT, env=env, check=True, capture_output=True, text=True,
            )
            self.assertFalse((home / ".claude/settings.json").exists())
            self.assertFalse((home / ".codex/hooks.json").exists())

    def test_all_runtime_files_are_in_global_ignore_contract(self) -> None:
        installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        for name in (
            ".ai/HANDOFF.md",
            ".ai/handoff-state.json",
            ".ai/handoff-metrics.jsonl",
            ".ai/handoff-hook-errors.jsonl",
            ".ai/handoff-transaction.json",
        ):
            self.assertIn(name, installer)


if __name__ == "__main__":
    unittest.main()
