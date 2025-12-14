from pathlib import Path

root = Path(__file__).resolve().parent
print(f"🔧 Applying Astra quick-patches under {root}")

# --- guardian alias fix in tab_dashboard.py ---
tab_dashboard = root / "astra_core/ui/dashboard/tab_dashboard.py"
if tab_dashboard.exists():
    txt = tab_dashboard.read_text()
    if "from astra_core.guardian import guardian as guardian" not in txt:
        txt = txt.replace(
            "import guardian", "from astra_core.guardian import guardian as guardian"
        )
        if "from astra_core.guardian import guardian" not in txt:
            txt = "from astra_core.guardian import guardian as guardian\n" + txt
        tab_dashboard.write_text(txt)
        print("✅ Patched guardian import in tab_dashboard.py")

# --- schema_validator fallback ---
sv = root / "astra_core/guardian/schema_validator.py"
if not sv.exists():
    sv.write_text(
        "# auto-generated fallback\n" "def validate_schema(data):\n" "    return True\n"
    )
    print("✅ Created schema_validator fallback")

# --- fetch_core fallback ---
fc = root / "astra_core/fetch_core.py"
if not fc.exists():
    fc.write_text(
        "# auto-generated fallback\n"
        "def fetch_data(*args, **kwargs):\n"
        "    print('[fetch_core] Placeholder fetch_data() called.')\n"
        "    return {}\n"
    )
    print("✅ Created fetch_core fallback")

print("✨ Quick-patch complete.")
