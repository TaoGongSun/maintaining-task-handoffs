#!/usr/bin/env bash
set -u

detect() {
  local name="$1"
  local marker="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    printf '%s=missing\n' "$name"
    return
  fi
  if "$name" --help 2>&1 | grep -q -- "$marker"; then
    printf '%s=hooks-detected\n' "$name"
  else
    printf '%s=hooks-unverified\n' "$name"
  fi
}

detect claude --include-hook-events
detect codex --dangerously-bypass-hook-trust

printf '%s\n' 'Project hooks still require the harness project/trust review. Detection does not imply trust.'
