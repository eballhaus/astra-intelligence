# ================================================================
# Astra DevTools — Runtime Simulator
# ================================================================

def safe_import(module_path):
    try:
        module = __import__(module_path, fromlist=["*"])
        return module, None
    except Exception as e:
        return None, str(e)


def simulate_astra_run():
    report = {}

    modules_to_test = [
        "astra_modules.scanners.smart_scan",
        "astra_modules.scanners.hybrid_scan",
        "astra_modules.fetch_core.fetch_unified",
        "astra_modules.ui.components.ticker_card",
        "astra_modules.ui.tab_dashboard"
    ]

    for name in modules_to_test:
        module, err = safe_import(name)
        if err:
            print(f"❌ Import Failure: {name} → {err}")
            report[name] = err
        else:
            print(f"✔ Import OK: {name}")
            report[name] = "ok"

    # Validate hybrid_scan execution
    try:
        from astra_modules.scanners.hybrid_scan import hybrid_scan
        check = hybrid_scan("AAPL")
        if not check:
            print("⚠ hybrid_scan returned invalid output.")
        else:
            print("✔ hybrid_scan executed successfully.")
    except Exception as e:
        print(f"❌ hybrid_scan execution error: {e}")
        report["hybrid_scan_run"] = str(e)

    return report
