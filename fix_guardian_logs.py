from pathlib import Path
import re
from datetime import datetime

path = Path("guardian/guardian_v6.py")
backup = path.with_suffix(f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
path.replace(backup)
print(f"✅ Backup saved to {backup}")

text = backup.read_text()

# Replace all guardian_log(…) calls except class definitions and logger creation
fixed = re.sub(r"(?<!class )guardian_log\s*\(", "print(", text)

Path("guardian/guardian_v6.py").write_text(fixed)
print("✅ guardian_v6.py cleaned and updated successfully.")
