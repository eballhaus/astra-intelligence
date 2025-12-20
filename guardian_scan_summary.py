import hashlib
import json
from pathlib import Path
from datetime import datetime

ROOTS = [
    "core",
    "engine",
    "guardian",
    "state",
    "ui",
    "agents",
    "forecast",
    "learning",
    "scanners",
    "chart_core",
    "utils",
]
MIRROR_ROOT = Path("astra_modules")
RESULT_DIR = Path("guardian_merge_review")
RESULT_DIR.mkdir(exist_ok=True)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


records = []
for root in ROOTS:
    main = Path(root)
    mirror = MIRROR_ROOT / root
    if not mirror.exists():
        continue
    for path in mirror.rglob("*.py"):
        rel = path.relative_to(mirror)
        mirror_hash = sha(path)
        main_path = main / rel
        status = "unique"
        if main_path.exists():
            main_hash = sha(main_path)
            if mirror_hash == main_hash:
                status = "identical"
            elif path.stat().st_mtime > main_path.stat().st_mtime:
                status = "newer_in_mirror"
            else:
                status = "older_in_mirror"
        records.append(
            {
                "module": root,
                "file": str(rel),
                "status": status,
                "mirror_path": str(path),
                "main_path": str(main_path if main_path.exists() else ""),
                "mirror_hash": mirror_hash,
            }
        )

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
(RESULT_DIR / f"merge_matrix_{ts}.json").write_text(json.dumps(records, indent=2))
summary = [f"{r['module']}/{r['file']}: {r['status']}" for r in records]
(RESULT_DIR / f"summary_{ts}.md").write_text("\n".join(summary))
print(f"Scan complete. Reports saved in {RESULT_DIR}")
