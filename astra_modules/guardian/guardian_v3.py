"""
guardian_v3.py — Phase-90 GuardianV3
------------------------------------
Self-Healing • Defensive Pipeline • ML-Safe Sanitization • Feature Integrity

This is Astra’s primary defense / auto-repair system.
All scanners, ranking engines, universe builders, and ML pipelines are routed
through GuardianV3 for safety, stability, and consistent data structure.
"""

import traceback
import pandas as pd


class GuardianV3:
    """
    Phase-90 Guardian with upgraded:
        • Safe execution wrappers
        • Auto-sanitization
        • ML feature protection
        • Scan/Ranking integrity checks
        • Universe fallback caching
    """

    def __init__(self):
        self.last_good_scan = {}
        self.last_good_ranking = []
        self.last_good_universe = ([], [])

    # ============================================================
    # SAFE RUN WRAPPER
    # ============================================================
    def run_safe(self, func, *args, fallback=None, **kwargs):
        """
        Executes ANY function safely.
        Returns fallback on any exception.
        Applies auto-sanitization for lists/dicts.
        """

        try:
            result = func(*args, **kwargs)

            # Auto-sanitize list of dict results
            if isinstance(result, list):
                result = [self.sanitize_record(r) for r in result if isinstance(r, dict)]

            if isinstance(result, dict):
                result = self.sanitize_record(result)

            return result

        except Exception as e:
            print(f"⚠ GuardianV3 caught error in {func.__name__}: {e}")
            traceback.print_exc()
            return fallback

    # ============================================================
    # SANITIZE INDIVIDUAL RECORD (Phase-90)
    # ============================================================
    def sanitize_record(self, r):
        """
        Ensures that every record produced by scans or ranking engines
        includes all Phase-90 fields required by UI + ML subsystems.
        """

        if not isinstance(r, dict):
            return self.default_record()

        out = {
            "ticker": r.get("ticker", "UNKNOWN"),
            "price": float(r.get("price", 0.0)),

            # Core scores
            "final_score": float(r.get("final_score", 50.0)),
            "buy_score": float(r.get("buy_score", 50.0)),
            "confidence": float(r.get("confidence", 50.0)),
            "safety_score": float(r.get("safety_score", 0.0)),

            # Visual/UI fields
            "sparkline": r.get("sparkline", []),
            "summary_text": r.get("summary_text", "Unknown"),
            "forecast": r.get("forecast", "Unknown"),

            # ML Feature Vector
            "features": self._sanitize_feature_vector(
                r.get("features")
            )
        }

        return out

    # ============================================================
    # DEFAULT FALLBACK RECORD
    # ============================================================
    def default_record(self):
        """Always returns a safe object for UI + ML systems."""
        return {
            "ticker": "UNKNOWN",
            "price": 0.0,
            "final_score": 50.0,
            "buy_score": 50.0,
            "confidence": 50.0,
            "safety_score": 0.0,
            "sparkline": [],
            "summary_text": "Unknown",
            "forecast": "Unknown",
            "features": [0.0] * 8,
        }

    # ============================================================
    # FEATURE VECTOR SANITIZER
    # ============================================================
    def _sanitize_feature_vector(self, fv):
        """
        Guarantees an 8-length numeric vector for neural learning agent.
        This ensures:
            • No crash on None / short arrays
            • No string pollution
            • Proper ML training format
        """
        try:
            if fv is None:
                return [0.0] * 8

            # Convert to float safely
            cleaned = []
            for v in fv:
                try:
                    cleaned.append(float(v))
                except Exception:
                    cleaned.append(0.0)

            # Pad or trim
            if len(cleaned) < 8:
                cleaned += [0.0] * (8 - len(cleaned))
            elif len(cleaned) > 8:
                cleaned = cleaned[:8]

            return cleaned

        except Exception:
            return [0.0] * 8

    # ============================================================
    # RANKING SANITIZATION
    # ============================================================
    def ensure_ranking(self, entries):
        try:
            return [self.sanitize_record(r) for r in entries if isinstance(r, dict)]
        except Exception as e:
            print(f"⚠ GuardianV3 ranking sanitization failed: {e}")
            return []

    # ============================================================
    # VALIDATE SYMBOL LISTS
    # ============================================================
    def validate_symbol_list(self, items):
        """Returns a clean, uppercase, duplicate-free list of tickers."""
        if items is None or not isinstance(items, (list, tuple)):
            return []

        out = [x.strip().upper() for x in items if isinstance(x, str) and x.strip()]
        return list(dict.fromkeys(out))

    # ============================================================
    # DATAFRAME VALIDATOR
    # ============================================================
    def validate_dataframe(self, df, required_columns=None):
        """
        Ensures all DataFrames returned to UI/chart engines are valid.
        """

        if df is None or not isinstance(df, pd.DataFrame):
            return pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        # Ensure required columns exist
        if required_columns:
            for col in required_columns:
                if col not in df.columns:
                    df[col] = None

        return df


# ============================================================
# SINGLE SHARED INSTANCE
# ============================================================
guardian = GuardianV3()
