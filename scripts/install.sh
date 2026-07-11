#!/usr/bin/env bash
# Idempotent installer for maintaining-task-handoffs.
# - Installs skill under $HOME/.agents/skills/
# - Optionally appends a bounded adapter once to global instruction files
# - Optionally ensures Git global excludes for local-only handoffs
# Does not overwrite existing global rules outside the marked adapter block.

set -euo pipefail

SKILL_NAME="maintaining-task-handoffs"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST_SKILL="${HOME}/.agents/skills/${SKILL_NAME}"
BIN_DIR="${HOME}/.local/bin"
BIN_PATH="${BIN_DIR}/handoff"
ADAPTER_SRC="${REPO_ROOT}/adapters/trigger-block.md"
BACKUP_DIR="${HOME}/.agents/backups/maintaining-task-handoffs-$(date +%Y%m%d-%H%M%S)"
WITH_ADAPTERS=1
WITH_HOOKS=1
WITH_GITIGNORE=1
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: install.sh [options]

  --skill-only       Install skill + discovery symlinks only (no adapters)
  --no-gitignore     Skip Git global exclude entries
  --dry-run          Print actions without writing
  -h, --help         Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill-only) WITH_ADAPTERS=0; WITH_HOOKS=0; shift ;;
    --no-gitignore) WITH_GITIGNORE=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

backup_file() {
  local src="$1"
  [[ -f "$src" ]] || return 0
  run mkdir -p "$BACKUP_DIR"
  run cp "$src" "$BACKUP_DIR/$(basename "$src")"
  echo "Backed up: $src -> $BACKUP_DIR/"
}

install_skill() {
  local expected_link="../../.agents/skills/${SKILL_NAME}/handoff.py"
  if [[ -e "$BIN_PATH" || -L "$BIN_PATH" ]]; then
    if [[ ! -L "$BIN_PATH" || "$(readlink "$BIN_PATH")" != "$expected_link" ]]; then
      echo "Refusing to replace unrelated command: $BIN_PATH" >&2
      return 1
    fi
  fi
  run mkdir -p "$(dirname "$DEST_SKILL")"
  if [[ -e "$DEST_SKILL" || -L "$DEST_SKILL" ]]; then
    if [[ -L "$DEST_SKILL" ]]; then
      run rm "$DEST_SKILL"
    else
      run rm -rf "$DEST_SKILL"
    fi
  fi
  # Prefer copy so uninstalling the clone does not break the install.
  run mkdir -p "$DEST_SKILL/agents"
  run cp "$REPO_ROOT/SKILL.md" "$DEST_SKILL/SKILL.md"
  run cp "$REPO_ROOT/handoff.py" "$DEST_SKILL/handoff.py"
  run cp -R "$REPO_ROOT/handoff_core" "$DEST_SKILL/handoff_core"
  run cp -R "$REPO_ROOT/hooks" "$DEST_SKILL/hooks"
  if [[ -f "$REPO_ROOT/agents/openai.yaml" ]]; then
    run cp "$REPO_ROOT/agents/openai.yaml" "$DEST_SKILL/agents/openai.yaml"
  fi
  echo "Installed skill: $DEST_SKILL"

  run mkdir -p "$BIN_DIR"
  if [[ -L "$BIN_PATH" ]]; then
    run rm -f "$BIN_PATH"
  fi
  run ln -s "$expected_link" "$BIN_PATH"
  echo "Installed CLI: $BIN_PATH"

  for link_dir in "${HOME}/.claude/skills" "${HOME}/.grok/skills"; do
    run mkdir -p "$link_dir"
    local link_path="${link_dir}/${SKILL_NAME}"
    if [[ -L "$link_path" || -e "$link_path" ]]; then
      run rm -rf "$link_path"
    fi
    # Relative symlink keeps portable structure when $HOME layout is standard.
    run ln -s "../../.agents/skills/${SKILL_NAME}" "$link_path"
    echo "Linked: $link_path"
  done
}

install_hooks() {
  local claude_state="missing"
  local codex_state="missing"
  if command -v claude >/dev/null 2>&1; then
    claude_state="$(claude --help 2>&1 | grep -q -- '--include-hook-events' && echo detected || echo unverified)"
  fi
  if command -v codex >/dev/null 2>&1; then
    codex_state="$(codex --help 2>&1 | grep -q -- '--dangerously-bypass-hook-trust' && echo detected || echo unverified)"
  fi
  if [[ "$claude_state" == detected ]]; then
    backup_file "${HOME}/.claude/settings.json"
    run python3 "$REPO_ROOT/scripts/merge_hooks.py" install "${HOME}/.claude/settings.json" "$REPO_ROOT/hooks/claude/hooks.json"
    echo "Claude hooks installed; Claude may still require project trust."
  else
    echo "Claude hooks not installed (capability $claude_state); use manual CLI gates."
  fi
  if [[ "$codex_state" == detected ]]; then
    backup_file "${HOME}/.codex/hooks.json"
    run python3 "$REPO_ROOT/scripts/merge_hooks.py" install "${HOME}/.codex/hooks.json" "$REPO_ROOT/hooks/codex/hooks.json"
    echo "Codex hooks installed; review and trust them with /hooks."
  else
    echo "Codex hooks not installed (capability $codex_state); use manual CLI gates."
  fi
}

install_adapter() {
  local target="$1"
  local parent
  parent="$(dirname "$target")"
  run mkdir -p "$parent"

  backup_file "$target"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] install or update adapter -> $target"
    return 0
  fi
  python3 "$REPO_ROOT/scripts/merge_adapter.py" "$target" "$ADAPTER_SRC"
  echo "Adapter installed or updated: $target"
}

ensure_git_excludes() {
  local excludes
  excludes="$(git config --global --get core.excludesFile 2>/dev/null || true)"
  if [[ -z "$excludes" ]]; then
    excludes="${HOME}/.config/git/ignore"
    run mkdir -p "$(dirname "$excludes")"
    if [[ ! -f "$excludes" ]]; then
      run touch "$excludes"
    fi
    run git config --global core.excludesFile "$excludes"
    echo "Set core.excludesFile: $excludes"
  fi

  backup_file "$excludes"
  local line
  for line in '.ai/HANDOFF.md' '.ai/handoff-state.json' '.ai/handoff-metrics.jsonl' '.ai/handoff-hook-errors.jsonl' '.ai/handoff-transaction.json' '.ai/designs/' '.ai/plans/'; do
    if [[ -f "$excludes" ]] && grep -qxF "$line" "$excludes" 2>/dev/null; then
      echo "Ignore already present (skip): $line"
      continue
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      echo "[dry-run] append ignore $line -> $excludes"
    else
      printf '%s\n' "$line" >>"$excludes"
      echo "Ignore added: $line"
    fi
  done
}

main() {
  [[ -f "$REPO_ROOT/SKILL.md" ]] || { echo "SKILL.md missing in $REPO_ROOT" >&2; exit 1; }
  [[ -f "$ADAPTER_SRC" ]] || { echo "Adapter missing: $ADAPTER_SRC" >&2; exit 1; }

  install_skill
  if [[ "$WITH_HOOKS" -eq 1 ]]; then
    install_hooks
  fi

  if [[ "$WITH_ADAPTERS" -eq 1 ]]; then
    install_adapter "${HOME}/.codex/AGENTS.md"
    install_adapter "${HOME}/.claude/Claude.md"
    install_adapter "${HOME}/.gemini/GEMINI.md"
  fi

  if [[ "$WITH_GITIGNORE" -eq 1 ]]; then
    ensure_git_excludes
  fi

  echo
  echo "Done. Skill path: $DEST_SKILL"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "(dry-run: no files were modified)"
  fi
}

main
