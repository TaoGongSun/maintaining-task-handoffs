---
name: maintaining-task-handoffs
description: Use when work has a formal plan, three or more substantive steps, multiple changed files, branch or commit work, more than about ten minutes of work, unfinished state another conversation may need, or the user mentions handoff, resume, checkpoint, or long-task continuity.
---

# Maintaining Task Handoffs

Keep one current, local-only handoff at `<git-root>/.ai/HANDOFF.md`.

## Activation is soft

Use judgment to mark work as long. Short tasks and unrelated small tasks do not activate this workflow. Once activated, the gates below are mandatory until `handoff complete` succeeds.

## Semantic draft

Write the meaning yourself. The CLI validates but never invents Goal, Current state, Completed, Verification, Remaining, Next action, or Constraints. Use one non-placeholder line for Next action. For completed work use exactly `你目前不需要做任何事。`

The draft must contain `# Task handoff`, `Task-ID`, `Status`, and those seven `##` sections. Never include secrets.

## Hard gates

1. At activation, author the initial draft and run:

   `handoff checkpoint --task-id <id> --input <draft> --harness <harness>`

2. During active work, write another checkpoint only at a recovery boundary: before compaction when validation is stale; when work pauses or becomes blocked; or after a milestone whose loss would require material reconstruction. Ordinary edits and test runs do not independently require checkpoint rewrites. A configured `PreCompact` hook blocks stale active tasks.

3. Before finishing, author a completed draft and run:

   `handoff complete --task-id <id> --input <draft> --harness <harness>`

If hooks are unavailable or untrusted, run these commands manually and report that enforcement was degraded. Hook errors are observable under `.ai/`; do not describe a failed hook as successful.

Hooks and session-end handlers cannot guarantee a checkpoint after SIGKILL, power loss, or host failure. Earlier checkpoints reduce loss; they do not eliminate it.

## Final response

After a long-task checkpoint, respond with only:

```text
交接文件已更新：<path>
下一步：<one action>
```

When completed, the last line is `你目前不需要做任何事。`
