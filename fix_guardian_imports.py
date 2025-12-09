#!/usr/bin/env python3
import os
import re

ROOT = os.path.dirname(__file__)

PATTERN_IMPORT = re.compile(r"from\s+astra_modules\.guardian\.guardian_v7\s+import\s+guardian_log")
PATTERN_REF = re.compile(r"\bGuardianV7\b")

replacements = []

for dirpath, dirnames, filenames in os.walk(ROOT):
    # skip __pycache__ and .git etc
    if any(part.startswith(".") for part in dirpath.split(os.sep)):
        continue
    for fname in filenames:
        if not fname.endswith(".py"):
            continue
        path = os.path.join(dirpath, fname)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text = text
        changed = False

        if PATTERN_IMPORT.search(text):
            new_text = PATTERN_IMPORT.sub(
                "from astra_core.guardian.guardian_v6 import guardian_log", new_text
            )
            changed = True

        # replace any usage of guardian_log with guardian_log
        if PATTERN_REF.search(new_text):
            # but avoid replacing imports already handled
            new_text = PATTERN_REF.sub("guardian_log", new_text)
            changed = True

        if changed:
            replacements.append((path, text, new_text))

# Print a summary + patch
for path, old, new in replacements:
    print(f"✅ Updating {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
print(f"✅ Total files updated: {len(replacements)}")
ø

