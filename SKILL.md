---
name: maintaining-task-handoffs
description: Use when work is genuinely long or continuation-sensitive, such as a formal plan, three or more substantive steps, broad multi-file work, a complex branch or commit sequence, more than about ten minutes of work, unfinished state another conversation may need, or an explicit request for handoff, resume, checkpoint, or long-task continuity. Do not use for a short standalone stage, commit, push, branch operation, or other routine Git task.
---

# Maintaining Task Handoffs

Keep local-only handoffs under `<git-root>/.ai/`. `.ai/HANDOFF.md` is the unfinished-task index, while each task's semantic handoff lives at `.ai/handoffs/<task-id>.md`. A repository may have one active task and multiple paused or blocked tasks.

## Activation is soft

Use judgment to mark work as long. Short tasks and unrelated small tasks do not activate this workflow. A Git operation alone does not activate this workflow. Once activated, the gates below are mandatory until `handoff pause` or `handoff complete` succeeds.

## Semantic draft

Write the meaning yourself. The CLI validates but never invents Goal, Current state, Completed, Verification, Remaining, Next action, or Constraints. Use one concrete, non-placeholder line for Next action, including after completed work. `completed` means the whole stated Goal is complete, not merely that the current run ended.

The draft must contain `# Task handoff`, `Task-ID`, `Status`, and those seven `##` sections. Never include secrets.

If the current task has plan documents, add an optional `## Plan files` section with one repo-relative path per Markdown bullet. List only plans owned by the current task. Never scan directories for other plans.

## Hard gates

1. At activation, author the initial draft and run:

   `handoff checkpoint --task-id <id> --input <draft> --harness <harness>`

2. During active work, write another checkpoint only at a recovery boundary: before compaction when validation is stale; when work pauses or becomes blocked; or after a milestone whose loss would require material reconstruction. Ordinary edits and test runs do not independently require checkpoint rewrites. A configured `PreCompact` hook blocks stale active tasks.

3. Before finishing the current run, choose the lifecycle outcome that matches the Goal:

   - If work remains for a later run, keep `Status: in-progress` or `Status: blocked` and run:

     `handoff pause --task-id <id> --input <draft> --harness <harness>`

   - Only when the whole Goal is complete, use `Status: completed` and run:

     `handoff complete --task-id <id> --input <draft> --harness <harness>`

   Pause preserves the task document and all plan files. Completion removes that task document and its index entry, then archives only files explicitly listed under that task handoff's `## Plan files`. Other paused or blocked tasks remain untouched. General plans move to a sibling `archive/<year>/` directory. Plans under `.ai/plans/` move to `.ai/archive/plans/<year>/`. Checkpoint, paused, blocked, and unfinished states never archive plans. Invalid sources or destinations and any archival failure block completion; cleanup and multi-file archival are all-or-nothing.

If hooks are unavailable or untrusted, run these commands manually and report that enforcement was degraded. Hook errors are observable under `.ai/`; do not describe a failed hook as successful.

Hooks and session-end handlers cannot guarantee a checkpoint after SIGKILL, power loss, or host failure. Earlier checkpoints reduce loss; they do not eliminate it.

## Project tasks

Local project todos are independent of long-task handoffs and live under the same `.ai/` tree:

- Entry: `.ai/README.md`
- Unfinished index: `.ai/TASKS.md`
- Task documents: `.ai/tasks/<task-id>.md`
- Daily activity: `.ai/history/YYYY-MM-DD.md`

### Query routing

- Current-project task questions read `.ai/TASKS.md` first.
- A named task follows exactly one index link into `.ai/tasks/<task-id>.md`. If multiple matches appear, list them and stop; do not guess.
- “Yesterday” (or another local day) reads only the configured local date file under `.ai/history/`.
- Explicit **all projects** task queries read the configured private memory root `TASKS.md` (not product Git).
- Explicit cross-project “yesterday” queries read only the matching root history file under that private memory repository.
- Ordinary prompts stay on the current project; do not open the private memory tree unless the user asks for all projects or sync.
- Long-task handoff activation remains independent; do not invent a project task just because a handoff exists.

### Mutations

Author semantic drafts yourself. Mutate only through CLI commands; do not hand-edit generated indexes or registry files:

```text
handoff task add --task-id <id> --input <draft>
handoff task update --task-id <id> --input <draft>
handoff task milestone --task-id <id> --input <draft> --summary <one line>
handoff task complete --task-id <id> --summary <one line>
handoff task list
handoff task show --task-id <id>
```

Completion requires evidence that the whole task goal is done, then `handoff task complete`. Inactivity, a clean Git tree, or a likely commit never imply completion. If a same-ID handoff is still open (active, paused, or blocked), complete or pause that handoff first.

### Private memory (optional)

Cross-project memory is an independent **private** Git repository the user creates and authorizes. It is not a task editing surface and does not copy handoff documents or secrets.

```text
handoff memory init --path <private-memory-clone>
handoff memory status
handoff memory sync [--no-push]
```

- Run `handoff memory sync` only when the user asks to synchronize; report local commit success separately from remote push success.
- Sync fetches and only **fast-forward**s the memory branch; never force, rebase, or merge task content.
- Direction uses content hashes (`local` / `memory` / `base`). Both sides changed yields `memory_diverged` and stops without overwriting either side.
- Project task mutations always happen in the source repository via `handoff task …`; never edit tasks inside the private memory tree.

## Final response

After a checkpoint or pause, report the task-document path. After completion, report `<repo>/.ai/HANDOFF.md` because the completed task document has been removed. Respond with only:

```text
交接文件已更新：<task-document-or-index-path>
狀況：<one concise status>
下一步：<one concrete action>
```
