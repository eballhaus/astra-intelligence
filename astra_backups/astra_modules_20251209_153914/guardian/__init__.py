# -*- coding: utf-8 -*-
"""
Astra Intelligence — Guardian Init (v7)
---------------------------------------
Initializes the Guardian system and exposes the guardian_log class.
Allows both:
    from astra_modules.guardian import guardian_log
and:
    python -m astra_modules.guardian
to work seamlessly.

Now also confirms Quota Monitor initialization.
"""

from __future__ import annotations

import traceback
from importlib import import_module

# ------------------------------------------------------------
# Try importing guardian_log from guardian_v7.py
# ------------------------------------------------------------
try:
    module = import_module("astra_modules.guardian.guardian_v7")
    guardian_log = getattr(module, "guardian_log", None)
    GuardianQuotaMonitor = getattr(module, "GuardianQuotaMonitor", None)

    if guardian_log:
        print("[Guardian] ✅ guardian_log successfully loaded from guardian_v7.py")

        # Optional safety check: ensure Quota Monitor exists
        if GuardianQuotaMonitor:
            print(
                "[Guardian] 🧠 Quota Monitor class detected — Guardian is quota-aware."
            )
        else:
            print(
                "[Guardian] ⚠️ Quota Monitor not found. Please verify guardian_v7.py is updated."
            )
    else:
        print("[Guardian] 🚨 guardian_v7 loaded, but guardian_log class not found.")

except Exception as e:
    guardian_log = None
    print(f"[Guardian] ⚠️ guardian_v7 import failed: {e}")
    traceback.print_exc()

# ------------------------------------------------------------
# Exported symbols
# ------------------------------------------------------------
__all__ = ["guardian_log"]

# ------------------------------------------------------------
# Safety fallback (only logs, does not break import)
# ------------------------------------------------------------
if guardian_log is None:
    print("[Guardian] ⚠️ Guardian aliasing skipped — guardian_log unavailable.")
else:
    try:
        # Try a lightweight self-test (initializes Guardian)
        guardian = guardian_log()
        guardian.log(
            "[Guardian] ✅ guardian_log instance initialized via __init__.py")
    except Exception as e:
        print(f"[Guardian] ⚠️ guardian_log instance init failed: {e}")
