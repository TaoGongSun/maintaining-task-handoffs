<!-- maintaining-task-handoffs:start -->
## Long-task handoffs

Use judgment to mark work as long. Do not activate handoffs for short or unrelated tasks. A Git operation alone does not activate this workflow. Once active, load and follow the `maintaining-task-handoffs` skill. Run `handoff checkpoint` at activation, `handoff pause` when work remains, and `handoff complete` only when the whole Goal is complete. If the skill cannot load, read `$HOME/.agents/skills/maintaining-task-handoffs/SKILL.md`.

## Project tasks

Current-project task queries start at `.ai/TASKS.md` and open only its linked task file. “Yesterday” reads only `.ai/history/<local-date>.md`. If multiple matches appear, list them and stop; do not guess. Follow the skill for routing and mutations. Use `handoff task …` for changes; completion requires evidence through `handoff task complete`. Never hand-edit generated indexes. Long-task handoff activation remains independent.

Access private cross-project memory only for explicit all projects, cross-project day, or sync requests. Run `handoff memory sync` only when requested. It does not copy handoff documents or secrets; sync is fast-forward only, and `memory_diverged` stops without overwrite. Never treat private memory as a task edit surface.
<!-- maintaining-task-handoffs:end -->
