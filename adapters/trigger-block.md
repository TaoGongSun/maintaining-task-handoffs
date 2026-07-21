<!-- maintaining-task-handoffs:start -->
## Long-task handoffs

Use judgment to mark work as long. Do not activate this workflow for short or unrelated tasks. A Git operation alone does not activate this workflow. Once active, use the `maintaining-task-handoffs` skill: run `handoff checkpoint` at activation; before compaction when stale; when work pauses or becomes blocked; or after a milestone whose loss would require material reconstruction. Ordinary edits and test runs do not independently trigger rewrites. Before finishing the current run, use `handoff pause` when the Goal still has remaining work, or `handoff complete` only when the whole Goal is complete. If the skill cannot load, read `$HOME/.agents/skills/maintaining-task-handoffs/SKILL.md`. The CLI maintains `.ai/HANDOFF.md` as an index and stores detail in `.ai/handoffs/<task-id>.md`; only one task may be active, while multiple paused or blocked tasks may remain. Final chat contains only a path, concise status, and one concrete next action: use the task-document path after checkpoint/pause, or the index path after completion.

When the current task has plan documents, list only those plans under `## Plan files` in the handoff. `handoff pause` preserves them; during `handoff complete`, archive only the listed plans. Never scan directories for unrelated plans.

## Project tasks

Current-project todos start at `.ai/TASKS.md`; open only the linked task file for detail. Multiple matches: list them and do not guess. “Yesterday” reads only `.ai/history/<local-date>.md`. Mutations use `handoff task add|update|milestone|complete|list|show`; agents author drafts and never hand-edit generated indexes. Completion needs evidence via `handoff task complete`—inactivity, clean Git, or a commit never imply done. Same-ID open handoffs block task completion. Long-task handoff activation stays independent.

Explicit all projects queries read the configured private memory root `TASKS.md`; cross-project day queries use only that root’s history file. Prefer local `.ai/` for the current project. Manual sync: `handoff memory init --path …`, `handoff memory status`, `handoff memory sync` (optional `--no-push`). Memory is private; does not copy handoff or secrets; fetch then fast-forward only; `memory_diverged` stops without overwrite. Never treat the memory repo as a task edit surface.
<!-- maintaining-task-handoffs:end -->
