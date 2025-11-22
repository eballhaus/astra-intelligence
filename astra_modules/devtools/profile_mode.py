# ================================================================
# Astra DevTools — Profiling Tools
# ================================================================

import time


def profile_astra_load(symbol="AAPL"):
    report = {}

    from astra_modules.scanners.smart_scan import smart_scan
    from astra_modules.scanners.hybrid_scan import hybrid_scan

    # -------------------------------
    # SMART SCAN TIMING
    # -------------------------------
    t0 = time.time()
    try:
        smart_scan(symbol)
        report["smart_scan"] = round(time.time() - t0, 4)
        print(f"✔ smart_scan({symbol}) completed in {report['smart_scan']}s")
    except Exception as e:
        report["smart_scan"] = f"ERROR: {e}"
        print(f"❌ smart_scan error: {e}")

    # -------------------------------
    # HYBRID SCAN TIMING
    # -------------------------------
    t1 = time.time()
    try:
        hybrid_scan(symbol)
        report["hybrid_scan"] = round(time.time() - t1, 4)
        print(f"✔ hybrid_scan({symbol}) completed in {report['hybrid_scan']}s")
    except Exception as e:
        report["hybrid_scan"] = f"ERROR: {e}"
        print(f"❌ hybrid_scan error: {e}")

    return report
