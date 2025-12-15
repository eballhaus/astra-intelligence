import sys, os
import pandas as pd
import importlib.util

# === Ensure legacy alias for astra_modules is active ===
LEGACY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../astra_modules_backup_20251130_1720"))
if os.path.exists(LEGACY_PATH) and "astra_modules" not in sys.modules:
    sys.path.append(LEGACY_PATH)
    spec_path = os.path.join(LEGACY_PATH, "__init__.py")
    spec = importlib.util.spec_from_file_location("astra_modules", spec_path) if os.path.exists(spec_path) else None
    astra_modules = importlib.util.module_from_spec(spec) if spec else None
    if spec and astra_modules:
        sys.modules["astra_modules"] = astra_modules
        print("[FetchBridge] ✅ 'astra_modules' alias registered for astra_modules_backup_20251130_1720")

# --- Bridge: use advanced Astra unified fetch system ---
try:
#     import fetch_core.fetch_unified as fetch_unified
    print("[FetchBridge] ✅ Advanced fetch_unified module loaded successfully.")
except Exception as e:
    print("[FetchBridge] ⚠️ Advanced fetcher import failed:", e)
    # --- fallback: basic local fetcher ---
    import yfinance as yf
        def get_symbol_data(self, symbol):
            data = yf.download(symbol, period="5d", interval="1h", progress=False)
            return data.reset_index()
#     fetch_unified = FetchUnified()
class FetchUnified:
    def get_symbol_data(self, symbol):
        data = yf.download(symbol, period="5d", interval="1h", progress=False)
        return data.reset_index()
#     fetch_unified = FetchUnified()
