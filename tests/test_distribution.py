import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def assert_event_based_checkpoint_contract(self, text: str) -> None:
        lowered = text.lower()
        for phrase in (
            "at activation",
            "before compaction",
            "pauses or becomes blocked",
            "milestone whose loss",
            "ordinary edits and test runs",
        ):
            self.assertIn(phrase, lowered)
        self.assertNotIn("whenever state changes materially", lowered)

    def test_skill_names_soft_activation_and_three_hard_gates(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("soft", text.lower())
        self.assertIn("handoff checkpoint", text)
        self.assertIn("handoff pause", text)
        self.assertIn("PreCompact", text)
        self.assertIn("handoff complete", text)
        self.assertIn("Short tasks", text)
        self.assertIn("cannot guarantee", text)
        self.assert_event_based_checkpoint_contract(text)

    def test_skill_documents_index_and_per_task_lifecycle(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`.ai/HANDOFF.md` is the unfinished-task index", text)
        self.assertIn("`.ai/handoffs/<task-id>.md`", text)
        self.assertIn("one active task", text.lower())
        self.assertIn("multiple paused or blocked tasks", text.lower())
        self.assertIn("removes that task document", text.lower())

    def test_adapter_requires_cli_after_activation(self) -> None:
        text = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8")
        self.assertIn("handoff checkpoint", text)
        self.assertIn("handoff pause", text)
        self.assertIn("handoff complete", text)
        self.assertIn("Do not activate", text)
        self.assert_event_based_checkpoint_contract(text)
        self.assertIn("list only those plans under `## Plan files`", text)
        self.assertIn("archive only the listed plans", text)
        self.assertIn("Never scan directories for unrelated plans", text)
        self.assertIn("`.ai/HANDOFF.md` as an index", text)
        self.assertIn("`.ai/handoffs/<task-id>.md`", text)

    def test_skill_requires_status_and_concrete_next_action_in_final_chat(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("狀況：<one concise status>", text)
        self.assertIn("下一步：<one concrete action>", text)
        self.assertIn("checkpoint or pause, report the task-document path", text)
        self.assertIn("after completion, report `<repo>/.ai/handoff.md`", text.lower())
        self.assertNotIn("你目前不需要做任何事。", text)

    def test_readme_documents_bounded_context_contract_bilingually(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in (
            "8 KiB",
            "handoff_too_large",
            "本機 I/O",
            "不會將 HANDOFF 內容注入模型 context",
            "local I/O",
            "does not inject HANDOFF contents into model context",
            "一般編輯與測試不會各自觸發 checkpoint",
            "ordinary edits and tests do not independently trigger checkpoints",
            "`.ai/HANDOFF.md` 是未完成任務索引",
            "`.ai/HANDOFF.md` is the unfinished-task index",
            "同時只允許一個 active 任務",
            "only one task may be active",
            "完成後會刪除該任務文件",
            "completion deletes that task document",
            ".ai/TASKS.md",
            ".ai/tasks/",
            ".ai/history/",
            "handoff task",
            "milestone",
            "completed",
            "handoff_still_open",
            "本機專案待辦",
            "local project tasks",
            "handoff memory init",
            "handoff memory sync",
            "memory_diverged",
            "同 ID handoff",
            "same-ID handoff",
        ):
            self.assertIn(phrase.lower(), text.lower())

    def test_task_guidance_routes_bounded_queries(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        adapter = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8")
        for text in (skill, adapter):
            self.assertIn(".ai/TASKS.md", text)
            self.assertIn("handoff task complete", text)
            self.assertIn("yesterday", text.lower())
            self.assertIn("multiple matches", text.lower())
            self.assertIn("do not guess", text.lower())

    def test_memory_guidance_and_bilingual_docs(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        adapter = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for text in (skill, adapter, readme):
            lowered = text.lower()
            for phrase in (
                "handoff memory init",
                "handoff memory sync",
                "all projects",
                "private",
                "memory_diverged",
                "fast-forward",
                "does not copy handoff",
            ):
                self.assertIn(phrase.lower(), lowered)
        for phrase in (
            "所有專案",
            "私人",
            "不複製 handoff",
            "不同步秘密",
            "雙邊都有變更",
        ):
            self.assertIn(phrase, readme)


class HookMergeTests(unittest.TestCase):
    def test_install_and_remove_preserve_unrelated_hooks_in_managed_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "hooks.json"
            managed = {"type": "command", "command": "run maintaining-task-handoffs hook"}
            glass = {"type": "command", "command": "afplay Glass.aiff"}
            target.write_text(json.dumps({"hooks": {
                "Stop": [{"matcher": "keep-me", "hooks": [managed, glass]}],
                "Legacy": [{"matcher": "remove-me", "hooks": [managed]}],
            }}), encoding="utf-8")
            command = ["python3", str(ROOT / "scripts/merge_hooks.py"), "install", str(target),
                       str(ROOT / "hooks/claude/hooks.json")]

            for _ in range(3):
                subprocess.run(command, check=True)
            merged = json.loads(target.read_text(encoding="utf-8"))
            stop_groups = merged["hooks"]["Stop"]
            stop_commands = [hook["command"] for group in stop_groups for hook in group["hooks"]]
            self.assertEqual(1, sum("maintaining-task-handoffs" in item for item in stop_commands))
            retained = next((group for group in stop_groups if glass in group["hooks"]), None)
            self.assertIsNotNone(retained, "install removed the unrelated Glass hook")
            self.assertEqual("keep-me", retained["matcher"])
            self.assertNotIn("Legacy", merged["hooks"])

            subprocess.run(command[:2] + ["remove", str(target)], check=True)
            cleaned = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual({"hooks": {"Stop": [{"matcher": "keep-me", "hooks": [glass]}]}}, cleaned)

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
    def test_reinstall_upgrades_managed_adapter_and_preserves_other_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            target = home / ".codex/AGENTS.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "Keep this rule.\n"
                "<!-- maintaining-task-handoffs:start -->\n"
                "Old managed adapter.\n"
                "<!-- maintaining-task-handoffs:end -->\n"
                "Keep this rule too.\n",
                encoding="utf-8",
            )
            env = {**os.environ, "HOME": str(home)}
            subprocess.run(
                ["bash", str(ROOT / "scripts/install.sh"), "--no-gitignore"],
                cwd=ROOT, env=env, check=True, capture_output=True, text=True,
            )
            installed = target.read_text(encoding="utf-8")
            current = (ROOT / "adapters/trigger-block.md").read_text(encoding="utf-8").strip()
            self.assertNotIn("Old managed adapter.", installed)
            self.assertIn(current, installed)
            self.assertIn("Keep this rule.\n", installed)
            self.assertIn("Keep this rule too.\n", installed)

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
            ".ai/handoffs/",
        ):
            self.assertIn(name, installer)

    def test_all_task_runtime_files_are_ignored(self) -> None:
        installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        for path in (
            ".ai/README.md",
            ".ai/TASKS.md",
            ".ai/tasks/",
            ".ai/history/",
            ".ai/project.json",
            ".ai/task-state.json",
            ".ai/task-transaction.json",
            ".ai/memory-sync.json",
        ):
            self.assertIn(path, installer)


if __name__ == "__main__":
    unittest.main()
