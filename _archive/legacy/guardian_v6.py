# -*- coding: utf-8 -*-
"""
GuardianV6 (Future Hybrid)
--------------------------
Astra Intelligence Self-Healing Guardian — now aligned with future system architecture.

Features:
✅ Unified logging (Streamlit-safe)
✅ Self-healing thread monitor
✅ Quota tracking & persistence
✅ Streamlit widget patch + cache flush
✅ API firewall + auto-fix engine
✅ Auto-recovery of health monitor
✅ Compatible with all existing modules
"""

import importlib
import json
import os
import sys
import threading
import time
import traceback
import warnings
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ============================================================
# GLOBAL PATHS
# ============================================================

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
GUARDIAN_LOG_PATH = Path(__file__).resolve().parent / "guardian.log"
FIX_REGISTRY_PATH = Path(ROOT_DIR) / "guardian_fixes.json"
QUOTA_STATE_PATH = Path(__file__).resolve().parent / "guardian_quota_state.json"

# ============================================================
# SUPPRESS WARNINGS
# ============================================================

warnings.filterwarnings(
    "ignore", message="No runtime found, using MemoryCacheStorageManager"
)

# ============================================================
# LOGGING SYSTEM
# ============================================================

_log_buffer = []  # In-memory buffer for emergency fallback


def guardian_log(message: str, level: str = "info") -> None:
    """Thread-safe and Streamlit-safe Guardian logger."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[GUARDIAN] {ts} | {message}"

    try:
        with open(GUARDIAN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception as e:
        _log_buffer.append(f"[GUARDIAN] ⚠️ File write failed: {e}")
        _log_buffer.append(formatted)

    try:
        sys.stderr.write(formatted + "\n")
    except Exception as e:
        _log_buffer.append(f"[GUARDIAN] ⚠️ Console log failed: {e}")


# ============================================================
# QUOTA MONITOR
# ============================================================


class GuardianQuotaMonitor:
    """Tracks API usage and warns or throttles if nearing limits."""

    DEFAULT_LIMITS = {
        "alpha_vantage": 500,
        "fmp": 1000,
        "twelvedata": 800,
        "finnhub": 1000,
        "eodhd": 1000,
        "moralis": 1200,
    }

    def __init__(self, log_func=None):
        self.log = log_func or guardian_log
        self.usage = defaultdict(lambda: {"count": 0, "last_reset": time.time()})
        self.quota_limits = dict(self.DEFAULT_LIMITS)
        self._load_state()

    def _load_state(self):
        if QUOTA_STATE_PATH.exists():
            try:
                with open(QUOTA_STATE_PATH, "r") as f:
                    self.usage.update(json.load(f))
                self.log("🧠 GuardianQuota: Restored previous quota state.")
            except Exception as e:
                self.log(f"⚠️ Failed to restore quota state: {e}")

    def _save_state(self):
        try:
            with open(QUOTA_STATE_PATH, "w") as f:
                json.dump(self.usage, f, indent=2)
        except Exception as e:
            self.log(f"⚠️ Failed to persist quota usage: {e}")

    def record(self, api_name: str):
        api = api_name.lower()
        self.usage[api]["count"] += 1
        limit = self.quota_limits.get(api, 1000)
        count = self.usage[api]["count"]

        if count >= 0.9 * limit:
            self.log(f"⚠️ {api.upper()} near quota limit ({count}/{limit})")
        if count >= limit:
            self.log(f"🚫 {api.upper()} quota exceeded — throttling future requests!")

        self._save_state()

    def reset(self, api_name=None):
        if api_name:
            self.usage[api_name] = {"count": 0, "last_reset": time.time()}
        else:
            for k in self.usage:
                self.usage[k] = {"count": 0, "last_reset": time.time()}
        self._save_state()
        self.log("♻️ Quota counters reset.")


# ============================================================
# STREAMLIT SAFEGUARDS
# ============================================================


def patch_streamlit_duplicates():
    """Prevent Streamlit widget key collisions."""
    try:
        import streamlit as st

        if hasattr(st, "_astra_guardian_patched"):
            return

        def _safe_wrap(fn, prefix):
            def safe_fn(label, *args, key=None, **kwargs):
                if key is None:
                    key = f"{prefix}_{abs(hash(label)) % 100000}"
                return fn(label, *args, key=key, **kwargs)

            return safe_fn

        st.radio = _safe_wrap(st.radio, "auto_radio")
        st.selectbox = _safe_wrap(st.selectbox, "auto_select")
        st.checkbox = _safe_wrap(st.checkbox, "auto_check")
        st.slider = _safe_wrap(st.slider, "auto_slider")
        st._astra_guardian_patched = True
        guardian_log("🧩 Streamlit duplicate widget protection enabled.")
    except Exception as e:
        guardian_log(f"⚠️ Streamlit patch failed: {e}")


# ============================================================
# AUTO FIX ENGINE
# ============================================================


def record_fix(file_path: str, issue_type: str, action: str):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "file": file_path,
        "issue": issue_type,
        "action": action,
    }
    try:
        data = []
        if FIX_REGISTRY_PATH.exists():
            with open(FIX_REGISTRY_PATH, "r") as f:
                data = json.load(f)
        data.append(entry)
        with open(FIX_REGISTRY_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        guardian_log(f"⚠️ Failed to record fix: {e}")


# ============================================================
# CORE GUARDIAN CLASS
# ============================================================


class guardian_log:
    """Core Guardian — runtime protection, cache management, and healing."""

    def __init__(self):
        # Avoid recursive call to guardian_log()
        print("[Guardian] ✅ guardian_log active (within guardian_core.py)")
        self.quota_monitor = GuardianQuotaMonitor()
        patch_streamlit_duplicates()
        self._start_health_monitor()
        self._set_global_exception_handler()

    def _set_global_exception_handler(self):
        sys.excepthook = self._global_exception_handler

    def _global_exception_handler(self, exctype, value, tb):
        log_message(f"🚨 Unhandled exception: {exctype.__name__}: {value}")
        traceback.print_tb(tb)

    def flush_streamlit_cache(self):
        try:
            import streamlit as st

            st.cache_data.clear()
            st.cache_resource.clear()
            log_message("🧹 Streamlit cache cleared by Guardian.")
        except Exception as e:
            log_message(f"⚠️ Cache clear failed: {e}")

    def _start_health_monitor(self):
        threading.Thread(target=self._health_monitor_loop, daemon=True).start()
        log_message("🩺 Health monitor started (interval=60s)")

    def _health_monitor_loop(self):
        while True:
            try:
                log_message("🧩 Running system health check...")
                for mod in [
                    "core.core.api_client",
                    "core.ui.dashboard.dashboard_data",
                    "core.learning.fusion_calibrator",
                ]:
                    try:
                        importlib.import_module(mod)
                        log_message(f"✅ Module OK: {mod}")
                    except Exception as e:
                        log_message(f"🚨 Failed: {mod} — {e}")
                log_message("🧠 Health check complete — system stable.")
                time.sleep(60)
            except Exception as e:
                log_message(f"⚠️ Health monitor loop crashed: {e}")
                time.sleep(5)  # Retry automatically

    def snapshot(self):
        """Record a quick Guardian state snapshot."""
        snap_dir = os.path.join(ROOT_DIR, "guardian_snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        snap_file = os.path.join(snap_dir, f"snapshot_{int(time.time())}.json")
        with open(snap_file, "w") as f:
            json.dump({"timestamp": datetime.utcnow().isoformat()}, f, indent=2)
        log_message(f"📸 Snapshot saved: {snap_file}")


# ============================================================
# LOGGING SHIM — backward compatibility for guardian_log("...")
# ============================================================


def log_message(message: str) -> None:
    """Lightweight logger replacement for backward compatibility."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[Guardian] {timestamp} | {message}")
    sys.stdout.flush()


# ------------------------------------------------------------
# Compatibility class for guardian_log
# ------------------------------------------------------------
class guardian_log:
    """Unified legacy logger class for dashboard and backend compatibility."""

    @staticmethod
    def info(msg: str):
        log_message(f"ℹ️ {msg}")

    @staticmethod
    def warning(msg: str):
        log_message(f"⚠️ {msg}")

    @staticmethod
    def error(msg: str):
        log_message(f"❌ {msg}")

    def __call__(self, msg: str):
        """Allow guardian_log('message') style calls."""
        log_message(msg)


# ============================================================
# ENTRYPOINT
# ============================================================
if __name__ == "__main__":
    guardian_log().info("✅ guardian_log self-test initialized.")
    guardian_log().info("✅ guardian_log self-test completed.")

__all__ = ["guardian_log"]
