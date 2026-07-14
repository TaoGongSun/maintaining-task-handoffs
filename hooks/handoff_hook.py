#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from handoff_core.service import HandoffService  # noqa: E402


def emit(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False))


def record(service: HandoffService, event: str, harness: str, reason: str) -> None:
    service.ai.mkdir(parents=True, exist_ok=True)
    item = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "harness": harness,
        "reason": reason,
    }
    with (service.ai / "handoff-hook-errors.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        cwd = Path(payload["cwd"])
        event = payload["hook_event_name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        print("invalid_hook_input", file=sys.stderr)
        return 2

    try:
        service = HandoffService(cwd)
        state = service._state()
    except Exception:
        print("hook_repo_error", file=sys.stderr)
        return 2

    active = bool(state and state.get("phase") == "active")
    if not active:
        emit({})
        return 0

    task_id = str(state["task_id"])
    fresh_minutes = int(state.get("fresh_minutes", 30))
    if event == "PreCompact":
        validation = service.validate(task_id, fresh_minutes)
        if validation.ok:
            emit({})
        else:
            record(service, event, args.harness, validation.code)
            emit(
                {
                    "decision": "block",
                    "reason": (
                        f"HANDOFF is not fresh ({validation.code}). Author a semantic draft, then run "
                        f"handoff checkpoint --task-id {task_id} --input <draft>.md --harness {args.harness}."
                    ),
                }
            )
        return 0

    if event == "Stop":
        service.record_failed_completion(task_id, args.harness, "stop_without_complete")
        if payload.get("stop_hook_active") is True:
            record(service, event, args.harness, "stop_reentry")
            emit(
                {
                    "continue": False,
                    "stopReason": (
                        "Blocked failure: the active long task still lacks a valid pause or completion. "
                        "The task lifecycle is still active; stopping hook continuation "
                        "to avoid an infinite loop."
                    ),
                }
            )
        else:
            emit(
                {
                    "decision": "block",
                    "reason": (
                        f"If the goal continues in a later run, author an in-progress or blocked HANDOFF and run "
                        f"handoff pause --task-id {task_id} --input <draft>.md --harness {args.harness}. "
                        f"Only if the whole goal is finished, use Status: completed and run handoff complete "
                        f"--task-id {task_id} --input <draft>.md --harness {args.harness}."
                    ),
                }
            )
        return 0

    if event == "SessionEnd":
        record(service, event, args.harness, "unfinished_at_session_end")
        service.record_failed_completion(task_id, args.harness, "unfinished_at_session_end")
        emit({})
        return 0

    emit({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
