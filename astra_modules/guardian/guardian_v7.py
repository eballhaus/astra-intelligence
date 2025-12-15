"""
guardian_v7.py — Clean Redirect to Guardian v6
-----------------------------------------------
Fixes 'PatchedGuardianLog object is not callable' by directly referencing guardian_v6.
"""

from astra_modules.guardian.guardian_v6 import guardian_log as GuardianV6

guardian = GuardianV6
guardian_boot = GuardianV6  # simple alias for backward compatibility

__all__ = ["guardian", "guardian_boot"]
Guardian = guardian_v7 = globals()


# --- Compatibility Stub ---
class Guardian:
    """Lightweight compatibility alias for older modules."""

    def __getattr__(self, name):
        print(f"[Guardian Stub] Accessed legacy attribute: {name}")
        return lambda *a, **kw: None


guardian_log = guardian_boot
GuardianV7 = Guardian
