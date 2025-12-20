import importlib
import threading


def lazy_import(module_name: str):
    """Import a module in a background thread, return a proxy dict."""
    container = {}

    def _load():
        container["mod"] = importlib.import_module(module_name)

    threading.Thread(target=_load, daemon=True).start()
    return container
