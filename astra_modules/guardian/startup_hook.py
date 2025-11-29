"""
Astra Intelligence — Guardian Startup Hook
Phase-101.9 | GuardianV6 Bootstrap
"""

from __future__ import annotations

import logging
from pathlib import Path

# ──────────────────────────────────────────────
# Import Guardian Core
# ──────────────────────────────────────────────
try:
    from astra_modules.guardian import guardian_v6 as guardian_core
except ImportError as e:
    raise ImportError(f"Failed to import GuardianV6: {e}") from e

LOG_PATH = Path(__file__).resolve().parent / "guardian_v6.log"
logging.basicConfig(
    filename=LOG_PATH,
    filemode="a",
    level=logging.INFO,
    format="%(asctime)s [StartupHook] %(levelname)s: %(message)s",
)
logger = logging.getLogger("StartupHook")


# ──────────────────────────────────────────────
# Bootstrap Logic
# ──────────────────────────────────────────────
def startup_sequence(verbose: bool = False) -> None:
    """
    Called automatically on system boot.
    Ensures GuardianV6 is active and reporting.
    """
    try:
        guardian_core.initialize_guardian()
        if verbose:
            print("🧠 GuardianV6 startup sequence completed successfully.")
        logger.info("GuardianV6 startup completed.")
    except Exception as e:
        logger.exception(f"GuardianV6 startup failed: {e}")
        raise RuntimeError(f"GuardianV6 startup failed: {e}") from e


# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    startup_sequence(verbose=True)
