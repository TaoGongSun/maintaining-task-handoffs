#!/usr/bin/env bash
# Removes skill install and marked adapter blocks. Does not delete handoff files.

set -euo pipefail

SKILL_NAME="maintaining-task-handoffs"
MARKER_START="<!-- maintaining-task-handoffs:start -->"
MARKER_END="<!-- maintaining-task-handoffs:end -->"
DEST_SKILL="${HOME}/.agents/skills/${SKILL_NAME}"

remove_adapter_block() {
  local target="$1"
  [[ -f "$target" ]] || return 0
  if ! grep -qF "$MARKER_START" "$target" 2>/dev/null; then
    echo "No adapter in: $target"
    return 0
  fi
  local tmp
  tmp="$(mktemp)"
  # Delete from start marker through end marker inclusive
  awk -v s="$MARKER_START" -v e="$MARKER_END" '
    $0 == s {skip=1; next}
    $0 == e {skip=0; next}
    !skip {print}
  ' "$target" >"$tmp"
  mv "$tmp" "$target"
  echo "Adapter removed: $target"
}

rm -rf "$DEST_SKILL"
rm -f "${HOME}/.claude/skills/${SKILL_NAME}"
rm -f "${HOME}/.grok/skills/${SKILL_NAME}"
echo "Removed skill and discovery links."

remove_adapter_block "${HOME}/.codex/AGENTS.md"
remove_adapter_block "${HOME}/.claude/Claude.md"
remove_adapter_block "${HOME}/.gemini/GEMINI.md"

echo "Uninstall complete. Global Git excludes (if any) were left unchanged."
