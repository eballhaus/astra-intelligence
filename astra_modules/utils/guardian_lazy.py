"""
guardian_lazy.py — Astra Intelligence Phase 6
Non-blocking Guardian loader with auto-swap mechanism.
"""

import atexit
import threading
import time

from astra_modules.utils.performance_profiler import Profiler

_guardian_proxy = None
_guardian_lock = threading.Lock()
_swap_ready_event = threading.Event()


class GuardianProxy:
    """Lightweight proxy that upgrades itself when GuardianCore is ready."""

    def __init__(self):
        self._core = None
        print("[GuardianAutoSwap] Lazy proxy initialized")

    def __getattr__(self, name):
        if self._core is not None:
            return getattr(self._core, name)
        raise RuntimeError(f"GuardianCore not ready yet: attempted '{name}'")


def _load_guardian_core(proxy):
    """Background loader for guardian_v6."""
    global _guardian_proxy
    try:
        import importlib.util

        start = time.time()

        # Safely load guardian_v6 without triggering circular imports
        spec = importlib.util.find_spec("guardian.guardian_v6")
        if spec is None:
            raise ImportError("guardian.guardian_v6 not found")

        mod = importlib.util.module_from_spec(spec)
        loader = spec.loader
        if loader is not None:
            loader.exec_module(mod)
        else:
            raise ImportError("guardian.guardian_v6 loader not found")

        proxy._core = getattr(mod, "GuardianCore", mod)
        _swap_ready_event.set()
        Profiler.measure("autoswap_complete", time.time() - start)
        print(
            f"[GuardianAutoSwap] GuardianCore loaded in {time.time()-start:.2f}s")

    except Exception as e:
        print(f"[GuardianAutoSwap] Failed to load GuardianCore: {e}")


def get_guardian():
    """Return proxy immediately; upgrade to full GuardianCore when ready."""
    global _guardian_proxy

    if _guardian_proxy is not None:
        return _guardian_proxy

    with _guardian_lock:
        if _guardian_proxy is None:
            proxy = GuardianProxy()
            _guardian_proxy = proxy
            threading.Thread(
                target=_load_guardian_core, args=(proxy,), daemon=True
            ).start()
    return _guardian_proxy


def is_guardian_ready():
    """Check if GuardianCore swap completed."""
    return _swap_ready_event.is_set()


def _cleanup():
    try:
        if not _swap_ready_event.is_set():
            print("[GuardianAutoSwap] Exiting before GuardianCore load completed.")
    except Exception:
        pass


atexit.register(_cleanup)
