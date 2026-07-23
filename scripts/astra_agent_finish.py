#!/usr/bin/env python3
"""Validate a workstream may be marked implementation_complete."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.registry import get_workstream, update_workstream_status
from ops.multi_agent.ledger import can_finish


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate workstream completion.")
    parser.add_argument("id", help="Workstream ID")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--mark", action="store_true", help="Mark implementation_complete if valid")
    args = parser.parse_args()

    ws = get_workstream(args.id)
    if ws is None:
        print(f"Workstream not found: {args.id}", file=sys.stderr)
        return 1

    result = can_finish(ws)
    if args.mark and result["can_finish"]:
        update_workstream_status(args.id, "implementation_complete")
        result["marked"] = True

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "CAN_FINISH" if result["can_finish"] else "CANNOT_FINISH"
        print(f"{status}: {args.id}")
        for err in result.get("errors", []):
            print(f"  - {err}")
        if result.get("marked"):
            print("Status updated to implementation_complete")

    return 0 if result["can_finish"] else 1


if __name__ == "__main__":
    sys.exit(main())
