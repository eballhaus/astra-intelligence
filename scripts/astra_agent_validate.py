#!/usr/bin/env python3
"""Validate a workstream or all active workstreams."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.registry import get_workstream, get_active_workstreams, refresh_ownership_registries
from ops.multi_agent.validator import validate_workstream


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate workstream(s).")
    parser.add_argument("--id", help="Workstream ID to validate")
    parser.add_argument("--all", action="store_true", help="Validate all active workstreams")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    refresh_ownership_registries()

    results = []
    if args.id:
        ws = get_workstream(args.id)
        if ws is None:
            print(f"Workstream not found: {args.id}", file=sys.stderr)
            return 1
        results.append(validate_workstream(ws, include_worktree=True))
    elif args.all:
        for ws in get_active_workstreams():
            results.append(validate_workstream(ws, include_worktree=True))
    else:
        print("Specify --id or --all", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            status = "VALID" if r["valid"] else "INVALID"
            print(f"{status}: {r['workstream_id']}")
            for err in r.get("errors", []):
                print(f"  - {err}")

    return 0 if all(r["valid"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
