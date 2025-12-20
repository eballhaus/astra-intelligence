import re, os, shutil
from pathlib import Path

root = Path(__file__).resolve().parent
print("\n🧭 Sentinel Auto-Repair started\n")

targets = [
    "guardian/startup_hook.py",
    "guardian/schema_validator.py",
    "guardian/pipeline_sanitizer.py",
    "engine/scan_manager.py",
    "engine/background_loop.py",
    "learning/fusion_calibrator.py",
    "ui/dashboard/tab_dashboard_v7.py"
]

def safe_backup(f):
    src = root / f
    if src.exists():
        backup = src.with_suffix(".bak_before_repair")
        shutil.copy2(src, backup)
        print(f"📦 Backed up {f} → {backup.name}")
        return src
    else:
        print(f"⚠️ File not found: {f}")
        return None

def replace_in_file(path, patterns):
    text = path.read_text()
    for old, new in patterns:
        text = re.sub(old, new, text)
    path.write_text(text)

# --- 1. guardian/startup_hook.py ---
f = safe_backup("guardian/startup_hook.py")
if f:
    replace_in_file(f, [
        (r"from\s+core\.guardian\s+import\s+guardian_v6", "from guardian.guardian_v6 import GuardianV6"),
    ])

# --- 2. guardian/schema_validator.py ---
f = safe_backup("guardian/schema_validator.py")
if f:
    replace_in_file(f, [
        (r"from\s+core\.guardian\s+import\s+guardian_log", "from guardian.guardian_v6 import guardian_log"),
    ])

# --- 3. guardian/pipeline_sanitizer.py ---
f = root / "guardian/auto_repair.py"
if not f.exists():
    f.write_text(
        "def repair_pipeline(data=None):\n"
        "    '''Placeholder repair function created by Sentinel Auto-Repair.'''\n"
        "    return data\n"
    )
    print("🩹 Created guardian/auto_repair.py stub")

# --- 4. engine/scan_manager.py ---
f = safe_backup("engine/scan_manager.py")
if f:
    replace_in_file(f, [
        (r"from\s+core\.core", "from engine"),
    ])

# --- 5. engine/background_loop.py ---
f = safe_backup("engine/background_loop.py")
if f:
    replace_in_file(f, [
        (r"from\s+performance\.performance_logger", "from learning.performance_tracker"),
    ])

# --- 6. learning/fusion_calibrator.py ---
f = safe_backup("learning/fusion_calibrator.py")
if f:
    text = f.read_text()
    text = re.sub(r"(^|\n)import\s+torch\.distributions\.constraints", "", text)
    insertion = "\n    import torch.distributions.constraints as constraints  # moved inside to avoid circular import\n"
    text = re.sub(r"(def\s+\w+\(.*?\):)", r"\1" + insertion, text, count=1)
    f.write_text(text)
    print("🩹 Adjusted import placement in learning/fusion_calibrator.py")

# --- 7. ui/dashboard/tab_dashboard_v7.py ---
f = safe_backup("ui/dashboard/tab_dashboard_v7.py")
if f:
    txt = f.read_text()
    if "fetch_live_data" not in txt:
        txt += "\n\n# Added by Sentinel Auto-Repair\n" \
               "def fetch_live_data(symbol=None):\n" \
               "    '''Fallback stub if engine.data_orchestrator lacks fetch_live_data.'''\n" \
               "    return {}\n"
        f.write_text(txt)
        print("🩹 Added fallback fetch_live_data() stub")

print("\n✅ Auto-Repair complete. Backups saved as *.bak_before_repair\n")
