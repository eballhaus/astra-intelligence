#!/usr/bin/env python3
"""Generate a model-specific prompt for a workstream."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ops.multi_agent.prompt import generate_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a prompt for a workstream.")
    parser.add_argument("id", help="Workstream ID")
    parser.add_argument("--model", help="Override target model")
    parser.add_argument("--output", help="Write prompt to file")
    args = parser.parse_args()

    result = generate_prompt(args.id, model=args.model)
    if not result.get("ok"):
        print(f"Error: {result.get('error')}", file=sys.stderr)
        return 1

    prompt = result["prompt"]
    print(f"# Target model: {result['target_model_name']} ({result['target_model']})")
    print()
    print(prompt)

    if args.output:
        Path(args.output).write_text(prompt, encoding="utf-8")
        print(f"\n# Prompt written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
