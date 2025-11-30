"""
Astra Intelligence — Guardian Package Bootstrap
Phase-101.9 | GuardianV6 Active
"""

from __future__ import annotations

import os
import importlib
import logging
from pathlib import Path

# ──────────────────────────────────────────────
# Guardian Environment Detection
# ──────────────────────────────────────────────
if "STREAMLIT_SERVER_ENABLED" in os.environ or "streamlit" in os.environ.get("PYTHONPATH", "").lower():
    GUARDIAN_ACTIVE = False
else:
    GUARDIAN_ACTIVE = True

# ──────────────────────────────────────────────
# GuardianV6 Core (Lazy Safe Import)
# ──────────────────────────────────────────────
try:
    if GUARDIAN_ACTIVE:
        from astra_modules.guardian import guardian_v6 as guardian_core
    else:
        guardian_core = None
except ImportError as e:
    raise ImportError(f"Failed to import GuardianV6 core: {e}") from e

# ──────────────────────────────────────────────
# Basic Logging Setup
# ──────────────────────────────────────────────
LOG_PATH = Path(__file__).resolve().parent / "guardian_v6.log"
logging.basicConfig(
    filename=LOG_PATH,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [GuardianV6] %(levelname)s: %(message)s",
)
logger = logging.getLogger("GuardianV6")

# ──────────────────────────────────────────────
# Initialization Wrapper
# ──────────────────────────────────────────────
def initialize_guardian(silent: bool = True) -> None:
    """
    Entry point for GuardianV6 initialization.
    Loads self-monitoring and integrity checks.
    """
    try:
        if guardian_core is not None:
            guardian_core.initialize_guardian()
            if not silent:
                print("🛡 GuardianV6 successfully initialized.")
            logger.info("GuardianV6 initialization complete.")
        else:
            if not silent:
                print("⚠️ Guardian inactive in Streamlit mode.")
            logger.info("GuardianV6 inactive in Streamlit mode.")
    except Exception as e:
        logger.exception(f"GuardianV6 initialization failed: {e}")
        raise

# ──────────────────────────────────────────────
# Convenience Reload Hook
# ──────────────────────────────────────────────
def reload_guardian() -> None:
    """Hot-reload GuardianV6 core."""
    if guardian_core is not None:
        importlib.reload(guardian_core)
        logger.info("GuardianV6 core reloaded.")
    else:
        logger.warning("GuardianV6 reload skipped (inactive in Streamlit mode).")

__all__ = ["initialize_guardian", "reload_guardian", "guardian_core"]
