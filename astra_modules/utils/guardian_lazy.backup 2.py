import importlib
import threading
import types

_guardian_proxy = None
_guardian_lock = threading.Lock()


def get_guardian():
    import os

    if os.getenv("ASTRA_FASTBOOT") == "1":
        print("[FastBoot] Guardian deferred until after UI start.")

    """Load guardian.guardian_v6 lazily on first use."""
    global _guardian_proxy
    if _guardian_proxy is not None:
        return _guardian_proxy

    with _guardian_lock:
        if _guardian_proxy is None:

            def _load():
                global _guardian_proxy
                _guardian_proxy = importlib.import_module(
                    "guardian.guardian_v6")

            threading.Thread(target=_load, daemon=True).start()
            # return lightweight placeholder immediately
            fake = types.SimpleNamespace(
                guardian_log=lambda msg: print("[LazyGuardian]", msg)
            )
            return fake
    return _guardian_proxy
