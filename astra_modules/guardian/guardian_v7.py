"""
guardian_v7.py — Clean Redirect to Guardian v6
-----------------------------------------------
Fixes 'PatchedGuardianLog object is not callable' by directly referencing guardian_v7.
"""

# from astra_modules.guardian.guardian_v7 import guardian_log as GuardianV6

# guardian = GuardianV6  # removed old alias
# guardian_boot = GuardianV6  # removed obsolete alias  # simple alias for backward compatibility

import datetime
import sys

__all__ = ["guardian", "guardian_boot"]
Guardian = guardian_v7 = globals()


# --- Compatibility Stub ---
class Guardian:
    """Lightweight compatibility alias for older modules."""

    def __getattr__(self, name):
        print(f"[Guardian Stub] Accessed legacy attribute: {name}")
        return lambda *a, **kw: None


GuardianV7 = Guardian

# ============================================================
# ✅ FIX: Local guardian_log definition to avoid self-import
# ============================================================


def guardian_log(message: str):
    """Safe local logging method for GuardianV7"""
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"[GUARDIAN] {timestamp} | {message}\n")
    sys.stdout.flush()


# ============================================================
# ✅ Finalized Guardian V7 Local Logger
# ============================================================


def guardian_log(message: str):
    """Stable, circular-safe Guardian logger"""
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout.write(f"[GUARDIAN] {timestamp} | {message}\n")
    sys.stdout.flush()
