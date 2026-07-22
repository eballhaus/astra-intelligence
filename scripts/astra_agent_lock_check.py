#!/usr/bin/env python3
"""Check ownership locks on files, patterns, or contracts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.registry import build_ownership_registry, get_workstream
from ops.multi_agent.common import normalize_path, path_matches_pattern


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether a file or contract is locked.")
    parser.add_argument("--file", help="File path to check")
    parser.add_argument("--pattern", help="Pattern to check")
    parser.add_argument("--contract", help="Canonical contract to check")
    parser.add_argument("--workstream", help="Workstream ID to exempt from conflicts")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if not args.file and not args.pattern and not args.contract:
        print("Specify --file, --pattern, or --contract", file=sys.stderr)
        return 1

    ownership = build_ownership_registry()
    locks: list[dict[str, Any]] = []

    def skip_owner(owner: str) -> bool:
        return bool(args.workstream and owner == args.workstream)

    if args.file:
        normalized = normalize_path(args.file)
        owner = ownership["files"].get(normalized)
        if owner and not skip_owner(owner):
            locks.append({"type": "file", "path": args.file, "owner": owner})
        for (pattern, owner), _ in ownership["patterns"].items():
            if skip_owner(owner):
                continue
            if path_matches_pattern(normalized, pattern):
                locks.append({"type": "pattern_match", "path": args.file, "pattern": pattern, "owner": owner})

    if args.pattern:
        for existing_file, owner in ownership["files"].items():
            if skip_owner(owner):
                continue
            if path_matches_pattern(existing_file, args.pattern):
                locks.append({"type": "pattern_match", "path": existing_file, "pattern": args.pattern, "owner": owner})
        for (pattern, owner), _ in ownership["patterns"].items():
            if skip_owner(owner):
                continue
            if pattern == args.pattern or pattern.startswith(args.pattern.rstrip("/") + "/"):
                locks.append({"type": "pattern", "pattern": args.pattern, "owner": owner})

    if args.contract:
        owner = ownership["contracts"].get(args.contract)
        if owner and not skip_owner(owner):
            locks.append({"type": "contract", "contract": args.contract, "owner": owner})

    if args.json:
        print(json.dumps({"locked": bool(locks), "locks": locks}, indent=2))
    else:
        if locks:
            print(f"LOCKED ({len(locks)} lock(s)):")
            for lock in locks:
                print(f"  {lock['type']} -> {lock.get('path') or lock.get('pattern') or lock.get('contract')}: owner={lock['owner']}")
        else:
            print("UNLOCKED")

    return 1 if locks else 0


if __name__ == "__main__":
    sys.exit(main())
