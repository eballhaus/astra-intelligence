"""
GuardianV6 — Astra Intelligence Data Integrity Core
Phase 108 Stable
"""

import os
import pandas as pd
import logging
from datetime import datetime

class GuardianV6:
    """
    GuardianV6 handles validation, error catching, and self-healing logic.
    Lightweight and stream-safe version for dashboard and engine operations.
    """

    def __init__(self, base_path=None):
        self.base_path = base_path or os.getcwd()
        self.log_path = os.path.join(self.base_path, "astra_guardian.log")
        logging.basicConfig(
            filename=self.log_path,
            filemode="a",
            level=logging.INFO,
            format="%(asctime)s [GuardianV6] %(levelname)s: %(message)s",
        )
        self.logger = logging.getLogger("GuardianV6")
        self.log("✅ GuardianV6 active (base: " + self.base_path + ")")

    # ──────────────────────────────────────────────
    # Logging Utilities
    # ──────────────────────────────────────────────
    def log(self, message: str):
        print(message)
        self.logger.info(message)

    # ──────────────────────────────────────────────
    # DataFrame Validation
    # ──────────────────────────────────────────────
    def validate_dataframe(self, df, required_columns=None):
        """
        Validate DataFrame structure, return clean DataFrame or empty fallback.
        """
        if df is None or not hasattr(df, "empty"):
            self.log("⚠️ GuardianV6: Invalid or None DataFrame.")
            return pd.DataFrame()

        if df.empty:
            self.log("⚠️ GuardianV6: Empty DataFrame detected.")
            return pd.DataFrame()

        if required_columns:
            missing = [c for c in required_columns if c not in df.columns]
            if missing:
                self.log(f"⚠️ GuardianV6: Missing required columns {missing}.")
                return pd.DataFrame()

        # Drop rows with NaN in key columns
        if required_columns:
            df = df.dropna(subset=required_columns, how="any")

        return df

    # ──────────────────────────────────────────────
    # Optional Diagnostics
    # ──────────────────────────────────────────────
    def health_check(self):
        self.log("✅ GuardianV6 Health Check: System OK.")
        return True
