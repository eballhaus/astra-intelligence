"""
guardian_v7.py — Clean Redirect to Guardian v6
-----------------------------------------------
Fixes 'PatchedGuardianLog object is not callable' by directly referencing guardian_v6.
"""
from core.guardian.guardian_v6 import guardian_log as GuardianV6

guardian = GuardianV6
guardian_boot = GuardianV6  # simple alias for backward compatibility

__all__ = ["guardian", "guardian_boot"]
