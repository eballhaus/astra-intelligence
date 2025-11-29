"""
GuardianV6 – Safe Runtime + Fallback Mode
-----------------------------------------
Protects Astra Intelligence from runtime import and attribute errors.
Keeps UI components responsive and logs actionable repair instructions.
"""

from __future__ import annotations

import importlib
import logging
import traceback
from types import ModuleType
from typing import Any, Callable, Optional

# ------------------------------------------------------
# Logging configuration
# ------------------------------------------------------
logger = logging.getLogger("GuardianV6")
logger.setLevel(logging.INFO)
handler = logging.FileHandler(
    "astra_modules/guardian/guardian_v6.log", mode="a")
formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)


# ------------------------------------------------------
# Core GuardianV6 Class
# ------------------------------------------------------
class GuardianV6:
    def __init__(self, base_path: str | None = None):
        """
        GuardianV6 — Astra Intelligence System Integrity Layer
        Handles system monitoring, auto-repair, and secure logging.
        Compatible with both legacy and new init patterns.
        """
        import os

        self.base_path = base_path or os.getcwd()
        self.memory = {"events": []}
        self.status = "initialized"

        try:
            os.makedirs(os.path.join(self.base_path, "logs"), exist_ok=True)
        except Exception:
            pass

        print(f"✅ GuardianV6 active (base: {self.base_path})")

    # -------------------------------
    # Safe Import Handling
    # -------------------------------
    def safe_import(self, module_path: str, fallback: Optional[Any] = None) -> Any:
        """Safely import a module; fallback to placeholder if unavailable."""
        try:
            mod = importlib.import_module(module_path)
            logger.info(f"✅ Imported {module_path}")
            return mod
        except Exception as e:
            logger.error(f"⚠️ Import failed for {module_path}: {e}")
            logger.debug(traceback.format_exc())
            if fallback is not None:
                logger.info(f"→ Using fallback for {module_path}")
                self.fallbacks[module_path] = fallback
                return fallback
            return self._generate_stub(module_path)

    # -------------------------------
    # Safe Execution Wrapper
    # -------------------------------
    def safe_run(self, func: Callable, *args, **kwargs) -> Any:
        """Run a function safely, logging exceptions and preventing crashes."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"❌ Runtime error in {func.__name__}: {e}")
            logger.debug(traceback.format_exc())
            return self._handle_failure(func.__name__, e)

    # -------------------------------
    # Self-Inspection Utilities
    # -------------------------------
    def verify_attribute(self, module: ModuleType, attr: str) -> bool:
        """Check whether an attribute exists within a module."""
        if hasattr(module, attr):
            return True
        logger.warning(
            f"⚠️ Missing attribute '{attr}' in module {module.__name__}")
        return False

    # -------------------------------
    # Internal Helpers
    # -------------------------------
    def _generate_stub(self, name: str) -> ModuleType:
        """Create a minimal placeholder module when import fails."""
        stub = ModuleType(name)
        setattr(stub, "__guardian_stub__", True)
        logger.info(f"🧩 Stub created for missing module: {name}")
        return stub

    def _handle_failure(self, context: str, error: Exception) -> None:
        """Gracefully handle runtime failure."""
        msg = f"[GuardianV6] Failure in {context}: {error}"
        logger.error(msg)
        print(msg)
        return None

    # -------------------------------
    # Self-Test
    # -------------------------------
    def integrity_check(self) -> None:
        """Scan for known missing modules or attributes and log results."""
        targets = [
            "astra_modules.chart_core.chart_engine",
            "astra_modules.learning.performance_tracker",
            "astra_modules.forecast.forecast_engine",
        ]
        for t in targets:
            mod = self.safe_import(t)
            if getattr(mod, "__guardian_stub__", False):
                logger.warning(f"🔍 Missing core module detected: {t}")

        logger.info("GuardianV6 integrity check complete.")


# ------------------------------------------------------
# Singleton Pattern for Easy Import
# ------------------------------------------------------
guardian = GuardianV6()


# Example usage (non-blocking):
if __name__ == "__main__":
    guardian.integrity_check()
    guardian.safe_run(lambda: print("✅ GuardianV6 operational"))
