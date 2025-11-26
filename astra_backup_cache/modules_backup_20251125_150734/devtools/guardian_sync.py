"""
GUARDIAN SYNC (AstraDoctor 2.0)
Makes sure guardian exports and imports match exactly across modules.
"""

import os
import re

def sync_guardian():
    path = "astra_modules/guardian/environment_guardian.py"
    if not os.path.exists(path):
        return ["environment_guardian.py missing"]

    expected = [
        "ensure_dataframe",
        "ensure_numeric",
        "guard_pipeline_output",
        "verify_no_stale_imports",
    ]

    with open(path, "r") as f:
        content = f.read()

    updated = content

    # Make sure all expected functions are exported
    def update_all_block(match):
        items = match.group(1).split(",")
        items = [i.strip().strip('"').strip("'") for i in items]
        for e in expected:
            if e not in items:
                items.append(e)
        items_str = ",\n    ".join(f'"{i}"' for i in items)
        return f"__all__ = [\n    {items_str},\n]"

    updated = re.sub(r"__all__\s*=\s*\[([^\]]*)\]", update_all_block, updated)

    if updated != content:
        with open(path, "w") as f:
            f.write(updated)
        return ["Guardian exports synced"]

    return []
