"""
guardian_autoswap.py – Astra Phase 6
Lightweight proxy that hot-swaps LazyGuardian → GuardianCore safely.
"""

import threading
import importlib
import time
from utils.performance_profiler import Profiler

swap_ready_event = threading.Event()
_guardian_core = None


class GuardianProxy:
    def __init__(self):
        self._core = None
        self._loading = True
        print("[GuardianAutoSwap] Lazy proxy initialized")

    def __getattr__(self, name):
        # If real guardian loaded, forward calls to it
        if self._core is not None:
            return getattr(self._core, name)
        raise RuntimeError(f"GuardianCore not ready yet: attempted '{name}'")


def _load_guardian_core():
    global _guardian_core
    try:
        start = time.time()
        mod = importlib.import_module("guardian.guardian_v6")
        _guardian_core = getattr(mod, "GuardianCore", mod)
        proxy._core = _guardian_core
        swap_ready_event.set()
        Profiler.measure("autoswap_complete", time.time() - start)
        print(f"[GuardianAutoSwap] GuardianCore loaded in {time.time()-start:.2f}s")
    except Exception as e:
        print(f"[GuardianAutoSwap] Failed to load GuardianCore: {e}")


# Initialize proxy and background loader
proxy = GuardianProxy()
threading.Thread(target=_load_guardian_core, daemon=True).start()


def get_guardian():
    return proxy
