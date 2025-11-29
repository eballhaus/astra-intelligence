#!/usr/bin/env python3
"""
Astra Intelligence — Guardian Import Repair Map v101.9
Automatically upgrades imports to Phase-101.9 (GuardianV6 / fetch_unified)
"""

import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent / "astra_modules"
TARGET_EXT = (".py",)

# Mapping of old → new import paths
REPAIR_MAP = {
    "astra_modules.guardian.guardian_v3": "astra_modules.guardian.guardian_v6",
    "astra_modules.guardian.guardian_v4": "astra_modules.guardian.guardian_v6",
    "astra_modules.guardian.guardian_init": "astra_modules.guardian.guardian_v6",
    "astra_modules.guardian.guardian_sentinel": "astra_modules.guardian.guardian_v6",
    "astra_modules.guardian.guardian_sync": "astra_modules.guardian.guardian_v6",
    "astra_modules.guardian.auto_repair": "astra_modules.guardian.guardian_v6",
    "astra_modules.engine.scan_manager": "astra_modules.engine.phase90_unified",
    "astra_modules.scanners.hybrid_scan": "astra_modules.fetch_core.fetch_unified",
    "astra_modules.scanners.smart_scan": "astra_modules.fetch_core.fetch_unified",
    "astra_modules.state.state_bundle_builder": "astra_modules.fetch_core.fetch_unified",
    "astra_modules.ranking.ranking_engine": "astra_modules.fetch_core.fetch_unified",
}

# Regex patterns
IMPORT_PATTERN = re.compile(r"^from\s+([\w\.]+)\s+import\s+.*$", re.MULTILINE)
IMPORT_LINE_PATTERN = re.compile(r"^import\s+([\w\.]+)", re.MULTILINE)

def repair_file(path: Path):
    text = path.read_text(encoding="utf-8")
    original_text = text

    for old, new in REPAIR_MAP.items():
        text = text.replace(old, new)

    if text != original_text:
        path.write_text(text, encoding="utf-8")
        print(f"🔧 Repaired imports in: {path.relative_to(BASE_DIR.parent)}")

def run_repair():
    print("🚀 Starting Astra Guardian Repair Map (Phase-101.9)")
    for root, _, files in os.walk(BASE_DIR):
        for f in files:
            if f.endswith(TARGET_EXT):
                repair_file(Path(root) / f)
    print("\n✅ GuardianV6 alignment complete.")
    print("Next step: run ./setup_dev_env.sh to confirm clean imports.\n")

if __name__ == "__main__":
    run_repair()

