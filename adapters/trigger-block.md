<!-- maintaining-task-handoffs:start -->
## Long-task handoffs

Use judgment to mark work as long. Do not activate this workflow for short or unrelated tasks. Once active, use the `maintaining-task-handoffs` skill: run `handoff checkpoint` at activation; before compaction when stale; when work pauses or becomes blocked; or after a milestone whose loss would require material reconstruction. Ordinary edits and test runs do not independently trigger rewrites. Run `handoff complete` before finishing. If the skill cannot load, read `$HOME/.agents/skills/maintaining-task-handoffs/SKILL.md`. Keep detail in `<repo>/.ai/HANDOFF.md`; final chat contains only its path and one next action.
<!-- maintaining-task-handoffs:end -->
