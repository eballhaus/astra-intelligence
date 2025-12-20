import importlib
import threading


def deferred_import(module_name: str, delay: float = 2.0):
    """Import a module asynchronously after delay (non-blocking)."""

    def _load():
        import time

        time.sleep(delay)
        try:
            importlib.import_module(module_name)
            print(f"[Deferred] Loaded {module_name}")
        except Exception as e:
            print(f"[Deferred] Failed to load {module_name}: {e}")

    threading.Thread(target=_load, daemon=True).start()
