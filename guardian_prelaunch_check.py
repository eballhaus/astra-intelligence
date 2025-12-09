# guardian_prelaunch_check.py
import os, sys, importlib

project_root = os.path.abspath(os.getcwd())
if project_root not in sys.path:
    sys.path.append(project_root)

required_paths = [
    "astra_modules/guardian",
    "astra_modules/ui/dashboard",
    "astra_modules/fetch_core",
]
required_modules = [
    "astra_core.guardian.guardian_v6",
    "astra_core.fetch_core.fetch_unified",
    "astra_core.ui.dashboard.dashboard_data",
    "astra_core.ui.dashboard.dashboard_chart",
    "astra_core.ui.dashboard.dashboard_cards",
    "astra_core.ui.dashboard.dashboard_sidebar",
    "astra_core.ui.dashboard.dashboard_summary",
    "astra_core.ui.dashboard.dashboard_assistant",
]
required_tab_files = [
    "astra_modules/ui/dashboard/tab_dashboard.py",
    "astra_modules/ui/dashboard/tab_predictions.py",
    "astra_modules/ui/dashboard/tab_learning.py",
]

print("🧠 ASTRA GUARDIAN — PRE-LAUNCH CHECK\n-----------------------------------")

# 1. confirm folder structure and __init__.py
for path in required_paths:
    if not os.path.exists(path):
        print(f"🚨 Missing folder: {path}")
    init = os.path.join(path, "__init__.py")
    if not os.path.exists(init):
        print(f"⚠️  Missing __init__.py in {path}")

# 2. confirm dashboard tabs
for tab in required_tab_files:
    if not os.path.exists(tab):
        print(f"🚨 Missing required dashboard tab: {tab}")

# 3. import tests
for mod in required_modules:
    try:
        importlib.import_module(mod)
        print(f"✅ Verified import: {mod}")
    except Exception as e:
        print(f"🚨 Failed import: {mod} — {e}")

print("-----------------------------------")
print("If no 🚨 items appear, Astra is ready to launch!\n")
print("Next:  streamlit run astra_modules/ui/dashboard/tab_dashboard.py\n")

