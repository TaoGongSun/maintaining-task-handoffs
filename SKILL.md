---
name: maintaining-task-handoffs
description: >
  Maintain a compact project handoff for long-running agent work. Use when a task
  has a formal plan, three or more substantive steps, multiple changed files,
  branch or commit work, more than about ten minutes of work, unfinished state
  another conversation may need to continue, or when the user mentions handoff,
  resume, checkpoint, or long-task continuity.
license: MIT
metadata:
  version: "1.0.0"
---

# Maintaining Task Handoffs

Preserve only the current state another agent needs to continue without rereading the conversation.

## Start

If `<root>/.ai/HANDOFF.md` exists and matches the current request, read it first. Reverify mutable Git, test, runtime, and external state before relying on it. Use the Git root as `<root>`; otherwise use the working directory.

## Checkpoint

Before the final response of a long task, update `<root>/.ai/HANDOFF.md`. Also update it immediately when work pauses because of limits, user request, missing authority, or another blocker. Do not create it for a simple answer or a short task with no continuation value.

Use this structure and overwrite stale state instead of appending history:

```markdown
# Task handoff
Updated: YYYY-MM-DD HH:MM TZ
Status: in-progress | blocked | completed

## Goal
## Current state
## Completed
## Verification
## Working context
- Repo:
- Branch/worktree:
- Important files:
- Relevant commits:
- Dirty changes:
## Remaining
## Next action
## Constraints
```

Keep it under about 120 lines. Preserve exact paths, commands, errors, commits, and verification status when useful. Treat the handoff as local-only and never recommend committing it unless the user explicitly asks. Never include secrets or unrelated conversation.

## Final Response

After updating the handoff, respond with only:

```text
交接文件已更新：<path>
下一步：<one action>
```

If the user has nothing to do, end with `你目前不需要做任何事。` If blocked, state the blocker in one sentence and put the needed decision on the final line. Expand details only when the user explicitly requests them. Prefer the user's language when the fixed phrases above would be jarring; keep the same two-line structure.
