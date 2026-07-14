<!-- maintaining-task-handoffs:start -->
## Long-task handoffs

Use judgment to mark work as long. Do not activate this workflow for short or unrelated tasks. Once active, use the `maintaining-task-handoffs` skill: run `handoff checkpoint` at activation; before compaction when stale; when work pauses or becomes blocked; or after a milestone whose loss would require material reconstruction. Ordinary edits and test runs do not independently trigger rewrites. Before finishing the current run, use `handoff pause` when the Goal still has remaining work, or `handoff complete` only when the whole Goal is complete. If the skill cannot load, read `$HOME/.agents/skills/maintaining-task-handoffs/SKILL.md`. Keep detail in `<repo>/.ai/HANDOFF.md`; final chat contains only its path, a concise status, and one concrete next action.

When the current task has plan documents, list only those plans under `## Plan files` in the handoff. `handoff pause` preserves them; during `handoff complete`, archive only the listed plans. Never scan directories for unrelated plans.
<!-- maintaining-task-handoffs:end -->
