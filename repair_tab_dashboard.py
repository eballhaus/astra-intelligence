from pathlib import Path

root = Path(__file__).resolve().parent
target = root / "astra_core/ui/dashboard/tab_dashboard.py"

if not target.exists():
    print("❌ tab_dashboard.py not found.")
    raise SystemExit(1)

text = target.read_text().splitlines()
new_lines = []
for line in text:
    # Remove the broken doubled import line
    if "guardian_v6 from" in line:
        continue
    new_lines.append(line)

# Ensure the correct imports exist once
import_block = [
    "from astra_core.guardian.guardian_v6 import guardian_boot",
    "from astra_core.guardian import guardian as guardian_log",
]
# Insert right after the first block of imports
insert_at = 0
for i, l in enumerate(new_lines):
    if l.strip().startswith("import") or l.strip().startswith("from "):
        insert_at = i + 1
new_lines[insert_at:insert_at] = import_block

target.write_text("\n".join(new_lines) + "\n")
print("✅ Cleaned and fixed imports in tab_dashboard.py")

