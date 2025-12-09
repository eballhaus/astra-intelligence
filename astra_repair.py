import os
import re
from datetime import datetime

LOG_FILE = f"astra_repair_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
pattern = re.compile(r'\bastra_modules(\.[\w\.]*)')

EXCLUDE_DIRS = {"venv", "__pycache__", "astra_backups", ".git", "mypy_cache"}

def should_skip(path):
    return any(part in path for part in EXCLUDE_DIRS)

def fix_imports(root):
    fixed = []
    for dirpath, _, files in os.walk(root):
        if should_skip(dirpath):
            continue
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                new_text, n = pattern.subn(r'astra_core\1', text)
                if n > 0:
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(new_text)
                    fixed.append((fpath, n))
    return fixed

if __name__ == "__main__":
    root = os.getcwd()
    print(f"🔍 Repairing import paths under: {root}")
    fixes = fix_imports(root)
    with open(LOG_FILE, "w") as log:
        for path, count in fixes:
            log.write(f"[{count}] fixed in {path}\n")
    print(f"✅ Repair complete — {len(fixes)} files updated.")
    print(f"📄 Log saved to: {LOG_FILE}")

