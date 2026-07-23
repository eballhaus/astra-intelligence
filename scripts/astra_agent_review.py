#!/usr/bin/env python3
"""Manage review transitions for a workstream."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.registry import get_workstream, update_workstream_status
from ops.multi_agent.validator import validate_workstream, validate_status_transition
from ops.multi_agent.ledger import validate_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a workstream.")
    parser.add_argument("id", help="Workstream ID")
    parser.add_argument("--status", required=True, choices=["passed", "failed"], help="Review outcome")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    ws = get_workstream(args.id)
    if ws is None:
        print(f"Workstream not found: {args.id}", file=sys.stderr)
        return 1

    if args.status == "passed":
        if ws.get("status") != "implementation_complete":
            print(f"Workstream not ready for review: {ws.get('status')}", file=sys.stderr)
            return 1
        ledger = validate_ledger(ws)
        if not ledger["valid"]:
            print("Ledger validation failed:", file=sys.stderr)
            for err in ledger["errors"]:
                print(f"  - {err}", file=sys.stderr)
            return 1
        validation = validate_workstream(ws, include_worktree=True)
        if not validation["valid"]:
            print("Workstream validation failed:", file=sys.stderr)
            for err in validation["errors"]:
                print(f"  - {err}", file=sys.stderr)
            return 1
        transition = validate_status_transition(args.id, "review_passed")
        if transition:
            print("Invalid transition:", transition, file=sys.stderr)
            return 1
        update_workstream_status(args.id, "review_passed")
        update_workstream_status(args.id, "integration_ready")
        result = {"ok": True, "id": args.id, "review": "passed", "status": "integration_ready"}
    else:
        transition = validate_status_transition(args.id, "review_failed")
        if transition:
            print("Invalid transition:", transition, file=sys.stderr)
            return 1
        update_workstream_status(args.id, "review_failed")
        result = {"ok": True, "id": args.id, "review": "failed", "status": "review_failed"}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Review {args.status}: {args.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
