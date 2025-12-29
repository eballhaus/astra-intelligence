import importlib

def load_guardian_v6():
    try:
        return importlib.import_module("guardian_v6")
    except Exception as e:
        print(f"[GUARDIAN_INIT] Deferred import failed: {e}")
        return None

guardian_v6 = load_guardian_v6()

