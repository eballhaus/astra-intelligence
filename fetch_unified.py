# =============================================================================
# Unified dashboard fetch entrypoint
# =============================================================================

def fetch_unified(symbol: str = "BTC-USD"):
    """
    Unified data fetch entrypoint for Astra Intelligence Dashboard.
    Ensures dashboard always receives complete OHLC data.
    """
    try:
        import importlib.util, os, sys

        path = os.path.join(os.getcwd(), "astra_core/fetch_core.py")
        spec = importlib.util.spec_from_file_location("fetch_core_real", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["fetch_core_real"] = mod
        spec.loader.exec_module(mod)

        cls = getattr(mod, "FetchUnified", None)
        if cls is None:
            print("[FetchBridge] ⚠️ FetchUnified class not found")
            return {"open": 0, "high": 0, "low": 0, "close": 0}

        get_symbol_data = getattr(cls(), "get_symbol_data", None)
        if get_symbol_data is None:
            print("[FetchBridge] ⚠️ get_symbol_data() missing")
            return {"open": 0, "high": 0, "low": 0, "close": 0}

        data = get_symbol_data(symbol)
        return data

    except Exception as e:
        print(f"[fetch_unified] Error: {e}")
        return {"open": 0, "high": 0, "low": 0, "close": 0}
