"""
Astra Intelligence — Guardian Package Bootstrap
Phase-101.9 | GuardianV6 Active
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

# ──────────────────────────────────────────────
# GuardianV6 Core
# ──────────────────────────────────────────────
try:
    from astra_modules.guardian import guardian_v6 as guardian_core
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
        guardian_core.initialize_guardian()
        if not silent:
            print("🛡 GuardianV6 successfully initialized.")
        logger.info("GuardianV6 initialization complete.")
    except Exception as e:
        logger.exception(f"GuardianV6 initialization failed: {e}")
        raise


# ──────────────────────────────────────────────
# Convenience Reload Hook
# ──────────────────────────────────────────────
def reload_guardian() -> None:
    """Hot-reload GuardianV6 core."""
    importlib.reload(guardian_core)
    logger.info("GuardianV6 core reloaded.")


__all__ = ["initialize_guardian", "reload_guardian", "guardian_core"]
