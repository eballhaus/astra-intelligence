#!/usr/bin/env python3
"""
Astra Intelligence – Import Repair Utility
Automatically rewrites legacy imports to the new astra_modules.* structure,
then re-runs the validation script.
"""

import re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASTRA = ROOT / "astra_modules"
LOG_FILE = ROOT / "astra_logs" / "astra_import_repair_log.txt"
LOG_FILE.parent.mkdir(exist_ok=True)

# Legacy -> new import patterns
REWRITE_RULES = {
    r"from\s+fetch_core": "from astra_modules.fetch",
    r"import\s+fetch_core": "from astra_modules import fetch",
    r"from\s+ui\.": "from astra_modules.ui.",
    r"from\s+forecast": "from astra_modules.forecast",
    r"from\s+learning": "from astra_modules.learning",
    r"from\s+state": "from astra_modules.state",
    r"import\s+utils": "from astra_modules import utils",
    r"from\s+utils\.": "from astra_modules.utils.",
}

def rewrite_imports(base: Path):
    count = 0
    for py in base.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        new_text = text
        for old, new in REWRITE_RULES.items():
            new_text = re.sub(old, new, new_text)
        if new_text != text:
            py.write_text(new_text, encoding="utf-8")
            count += 1
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"Rewrote imports in {py}\n")
    return count

print("🔧 Running Astra Import Repair...")
files_changed = rewrite_imports(ASTRA)
print(f"✅ Import rewrite complete. {files_changed} files updated.\n")

print("🔍 Re-running validation...\n")
subprocess.run(["python", "astra_system_validation.py"])
