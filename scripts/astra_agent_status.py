#!/usr/bin/env python3
"""Report status of active workstreams and integration queue."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.registry import get_active_workstreams, load_integration_queue
from ops.multi_agent.ledger import validate_ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Multi-Agent OS status.")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    workstreams = []
    for ws in get_active_workstreams():
        ledger = validate_ledger(ws)
        workstreams.append({
            "id": ws.get("id"),
            "title": ws.get("title"),
            "model": ws.get("primary_model"),
            "risk": ws.get("risk_level"),
            "status": ws.get("status"),
            "branch": ws.get("branch"),
            "worktree": ws.get("worktree"),
            "files_locked": len(ws.get("owned_files", [])) + len(ws.get("owned_patterns", [])),
            "contracts_locked": len(ws.get("owned_contracts", [])),
            "acceptance": f"{ledger['pass_count']}/{ledger['total']} PASS",
            "integration": "Ready" if ws.get("status") == "review_passed" else "Not ready",
        })

    queue = load_integration_queue()
    payload = {
        "active_workstreams": workstreams,
        "integration_queue": queue.get("queue", []),
        "current_integration": queue.get("current"),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("ACTIVE WORKSTREAMS")
        print()
        for ws in workstreams:
            print(f"{ws['id']}")
            print(f"  Model: {ws['model']}")
            print(f"  Risk: {ws['risk']}")
            print(f"  Status: {ws['status']}")
            print(f"  Branch: {ws['branch']}")
            print(f"  Files locked: {ws['files_locked']}")
            print(f"  Contracts locked: {ws['contracts_locked']}")
            print(f"  Acceptance: {ws['acceptance']}")
            print(f"  Integration: {ws['integration']}")
            print()
        if queue.get("current"):
            print(f"CURRENT INTEGRATION: {queue['current']['id']}")
        if queue.get("queue"):
            print("QUEUE:")
            for item in queue["queue"]:
                print(f"  - {item['id']} (order={item['integration_order']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
