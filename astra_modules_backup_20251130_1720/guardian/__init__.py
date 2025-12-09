"""
Astra Guardian Initialization Layer
-----------------------------------
Centralizes imports for all Guardian classes and exposes key utilities
(safe_yahoo_request, guardian_log) for cross-module reliability.
Ensures backward compatibility across GuardianV6–V8.
"""

import importlib
import sys
import os

__all__ = ["guardian_log", "safe_yahoo_request"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------
# 🧠 Import guardian_log Class
# ------------------------------------------------------------
guardian_log = None
safe_yahoo_request = None

try:
    guardian_v6 = importlib.import_module(".guardian_v6", package=__package__)
    guardian_log = getattr(guardian_v6, "guardian_log", None)
    safe_yahoo_request = getattr(guardian_v6, "safe_yahoo_request", None)
    print("[Guardian] ✅ guardian_log and safe_yahoo_request loaded from guardian_v6.py")
except Exception as e:
    print(f"[Guardian] 🚨 Failed to import guardian_log or safe_yahoo_request from guardian_v6: {e}")

# ------------------------------------------------------------
# 🧩 Backward-Compatible Aliases
# ------------------------------------------------------------
if guardian_log:
    sys.modules["astra_core.guardian.guardian_log"] = guardian_log
if safe_yahoo_request:
    sys.modules["astra_core.guardian.safe_yahoo_request"] = safe_yahoo_request

# ------------------------------------------------------------
# 🧠 Helper: Verify Guardian Integrity
# ------------------------------------------------------------
def verify_guardian():
    """Verifies that guardian_log is active and operational."""
    if guardian_log is None:
        print("[Guardian] ❌ guardian_log unavailable — check guardian_v6.py integrity.")
        return False
    try:
        g = guardian_log()
        g.log("🧠 Guardian import verified successfully via __init__.")
        return True
    except Exception as e:
        print(f"[Guardian] ⚠️ Guardian verification failed: {e}")
        return False


if __name__ == "__main__":
    verify_guardian()
