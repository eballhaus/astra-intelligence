#!/usr/bin/env python3
"""Register a new workstream in the Multi-Agent OS."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.common import load_yaml, fail
from ops.multi_agent.registry import register_workstream


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a workstream from a YAML file.")
    parser.add_argument("file", help="Path to workstream YAML file")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        fail(f"file_not_found:{path}")

    workstream = load_yaml(path)
    result = register_workstream(workstream)

    if args.json:
        import json
        print(json.dumps(result))
    else:
        if result.get("ok"):
            print(f"Registered workstream: {result['registered']}")
        else:
            print(f"Failed: {result.get('error')}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
