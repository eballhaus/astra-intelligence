"""
astra_modules.guardian
----------------------------------------------------
Guardian package initialization for Astra Intelligence (Phase-90).
Handles safe imports and auto-loading of Guardian V6 predictive system.
"""

# Core safe imports
from .environment_guardian import (
    safe_import,
    check_environment
)

# --- Guardian Core ---
try:
    from .guardian_v6 import GuardianV6
    guardian = GuardianV6(__path__[0])
    print("🛡️ Guardian V6 initialized successfully.")
except Exception as e_v6:
    guardian = None
    print(f"[Guardian Init] ⚠️ Failed to load Guardian V6: {e_v6}")

# --- Guardian Sentinel ---
try:
    from .guardian_sentinel import GuardianSentinel
except Exception as e:
    GuardianSentinel = None
    print(f"[Guardian Init] ⚠️ Failed to load GuardianSentinel: {e}")

# --- Guardian Auto-Repair (legacy + V6 helper) ---
try:
    from .auto_repair import GuardianAutoRepair
except Exception:
    GuardianAutoRepair = None

try:
    from .guardian_autofix import AutoFixEngine
except Exception:
    AutoFixEngine = None

# --- Guardian Scanner + Init Verifier ---
try:
    from .guardian_scanner import DirectoryScanner
except Exception:
    DirectoryScanner = None

try:
    from .guardian_init import InitVerifier
except Exception:
    InitVerifier = None

# --- Startup Hook ---
try:
    from .startup_hook import run_startup_check
except Exception as e:
    run_startup_check = lambda: print(f"[Guardian Init] ⚠️ StartupHook missing: {e}")

__all__ = [
    "safe_import",
    "check_environment",
    "guardian",
    "GuardianSentinel",
    "GuardianAutoRepair",
    "AutoFixEngine",
    "DirectoryScanner",
    "InitVerifier",
    "run_startup_check",
]

print("✅ Guardian package initialized (Phase-90 / V6).")
