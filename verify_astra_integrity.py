import os

BASE_DIR = "astra_core"

print("🔍 Scanning Astra Core for missing imports...\n")


def validate_imports(base):
    for root, _, files in os.walk(base):
        for file in files:
            if file.endswith(".py"):
                path = os.path.join(root, file)
                rel = os.path.relpath(path, base)
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for line in lines:
                    if line.startswith("from ") or line.startswith("import "):
                        mod = line.split()[1].split(".")[0]
                        try:
                            __import__(mod)
                        except Exception:
                            print(f"[⚠️ Missing] {rel} → {mod}")


validate_imports(BASE_DIR)
print("\n✅ Integrity scan complete.")
