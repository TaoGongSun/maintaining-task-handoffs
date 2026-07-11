#!/usr/bin/env bash
# Idempotent installer for maintaining-task-handoffs.
# - Installs skill under $HOME/.agents/skills/
# - Optionally appends a bounded adapter once to global instruction files
# - Optionally ensures Git global excludes for local-only handoffs
# Does not overwrite existing global rules outside the marked adapter block.

set -euo pipefail

SKILL_NAME="maintaining-task-handoffs"
MARKER_START="<!-- maintaining-task-handoffs:start -->"
MARKER_END="<!-- maintaining-task-handoffs:end -->"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEST_SKILL="${HOME}/.agents/skills/${SKILL_NAME}"
ADAPTER_SRC="${REPO_ROOT}/adapters/trigger-block.md"
BACKUP_DIR="${HOME}/.agents/backups/maintaining-task-handoffs-$(date +%Y%m%d-%H%M%S)"
WITH_ADAPTERS=1
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
    --skill-only) WITH_ADAPTERS=0; shift ;;
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
  if [[ -f "$REPO_ROOT/agents/openai.yaml" ]]; then
    run cp "$REPO_ROOT/agents/openai.yaml" "$DEST_SKILL/agents/openai.yaml"
  fi
  echo "Installed skill: $DEST_SKILL"

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

append_adapter_once() {
  local target="$1"
  local parent
  parent="$(dirname "$target")"
  run mkdir -p "$parent"

  if [[ -f "$target" ]] && grep -qF "$MARKER_START" "$target" 2>/dev/null; then
    echo "Adapter already present (skip): $target"
    return 0
  fi

  backup_file "$target"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] append adapter -> $target"
    return 0
  fi
  # Ensure trailing newline before block
  if [[ -f "$target" && -s "$target" ]]; then
    printf '\n' >>"$target"
  else
    : >"$target"
  fi
  # Substitute $HOME literally for the current user path in the block is wrong;
  # keep $HOME as text for portability across machines.
  cat "$ADAPTER_SRC" >>"$target"
  printf '\n' >>"$target"
  echo "Adapter appended: $target"
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
  for line in '.ai/HANDOFF.md' '.ai/designs/' '.ai/plans/'; do
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

  if [[ "$WITH_ADAPTERS" -eq 1 ]]; then
    append_adapter_once "${HOME}/.codex/AGENTS.md"
    append_adapter_once "${HOME}/.claude/Claude.md"
    append_adapter_once "${HOME}/.gemini/GEMINI.md"
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
