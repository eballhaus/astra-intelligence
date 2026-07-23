#!/usr/bin/env python3
"""Manage the integration queue."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.queue import (
    add_to_queue,
    remove_from_queue,
    get_queue_status,
    set_current_integrating,
    complete_integration,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Integration queue operations.")
    sub = parser.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="Add a review-passed workstream to the queue")
    add.add_argument("id", help="Workstream ID")

    remove = sub.add_parser("remove", help="Remove a workstream from the queue")
    remove.add_argument("id", help="Workstream ID")

    sub.add_parser("status", help="Show queue status")

    start = sub.add_parser("start", help="Mark a queued workstream as currently integrating")
    start.add_argument("id", help="Workstream ID")

    done = sub.add_parser("complete", help="Complete integration of the current workstream")
    done.add_argument("id", help="Workstream ID")
    done.add_argument("--fail", action="store_true", help="Mark integration as failed")

    parser.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()

    if args.action == "add":
        result = add_to_queue(args.id)
    elif args.action == "remove":
        result = remove_from_queue(args.id)
    elif args.action == "status":
        result = get_queue_status()
    elif args.action == "start":
        result = set_current_integrating(args.id)
    elif args.action == "complete":
        result = complete_integration(args.id, success=not args.fail)
    else:
        parser.print_help()
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result.get("ok"):
            print(f"OK: {args.action} {args.id if hasattr(args, 'id') else ''}".strip())
        else:
            print(f"Failed: {result.get('error') or result.get('errors')}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
