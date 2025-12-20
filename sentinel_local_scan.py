import os, json, hashlib
from datetime import datetime

# ✅ Corrected paths for macOS
FOLDERS = [
    "/Users/ericballhaus/Desktop/astra-intelligence/backups",
    "/Users/ericballhaus/Desktop/astra-intelligence/guardian",
    "/Users/ericballhaus/Desktop/astra-intelligence/legacy_backups"
]

def hash_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read(4096)).hexdigest()
    except Exception as e:
        return f"ERROR: {e}"

def scan_dir(path):
    report = []
    for root, _, files in os.walk(path):  # 👈 Recursively scans every subfolder
        for f in files:
            full_path = os.path.join(root, f)
            try:
                report.append({
                    "file": f,
                    "path": full_path,
                    "size_bytes": os.path.getsize(full_path),
                    "modified": datetime.fromtimestamp(os.path.getmtime(full_path)).isoformat(),
                    "hash": hash_file(full_path)
                })
            except Exception as e:
                report.append({
                    "file": f,
                    "path": full_path,
                    "error": str(e)
                })
    return report

all_reports = {}
for folder in FOLDERS:
    if os.path.exists(folder):
        print(f"Scanning: {folder}")
        all_reports[folder] = scan_dir(folder)
    else:
        print(f"⚠️ Folder not found: {folder}")

output_file = "sentinel_local_scan.json"
with open(output_file, "w", encoding="utf-8") as out:
    json.dump(all_reports, out, indent=2)

print(f"\n✅ Deep recursive scan complete. Report saved as: {os.path.abspath(output_file)}")
print("Now upload sentinel_local_scan.json to ChatGPT for Sentinel analysis.")
