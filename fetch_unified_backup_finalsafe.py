# =============================================================================
# Unified dashboard fetch entrypoint
# =============================================================================
def fetch_unified(symbol: str = "BTC-USD"):
    """
    Unified data fetch entrypoint for Astra Intelligence Dashboard.
    Ensures dashboard always receives complete OHLC data.
    """
    from importlib import import_module

    mod = import_module("astra_core.fetch_core")
    cls = getattr(mod, "FetchUnifiedClass", None)
    get_symbol_data = getattr(cls(), "get_symbol_data", None)
    import importlib.util
    import sys
    import os

    path = os.path.join(os.getcwd(), "astra_core/fetch_core.py")
    spec = importlib.util.spec_from_file_location("fetch_core_real", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fetch_core_real"] = mod
    spec.loader.exec_module(mod)
    cls = None
    for name, obj in mod.__dict__.items():
        if isinstance(obj, type) and "get_symbol_data" in obj.__dict__:
            cls = obj
            break
    if cls:
        get_symbol_data = getattr(cls(), "get_symbol_data", None)
    else:
        print("[FetchBridge] ⚠️ No class with get_symbol_data found in fetch_core_real")
    try:
        data = get_symbol_data(symbol)
        if isinstance(data, dict):
            # Normalize expected keys
            for key in ["open", "high", "low", "close"]:
                data[key] = data.get(key, data.get("price", 0))
            return data
        else:
            return {"open": 0, "high": 0, "low": 0, "close": 0}
    except Exception as e:
        print(f"[fetch_unified] Error: {e}")
        return {"open": 0, "high": 0, "low": 0, "close": 0}
