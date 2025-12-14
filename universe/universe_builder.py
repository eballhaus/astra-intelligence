"""
Universe Builder – Phase-90 Unified Version
-------------------------------------------
Provides both the UniverseBuilder class (for legacy modules)
and build_universe() function (for Phase-90 components).
Integrated with guardian_v6 for self-healing and logging.
"""

import os
import pandas as pd
import json
from core.cache_manager import CacheManager

# Import guardian safely
try:
    from guardian.guardian_v6 import guardian_log, self_heal, log_event, _write_log
except Exception:
    # Fallback if Guardian isn't loaded yet (FastBoot mode)
    def guardian_log(msg):
        print(f"[LazyGuardian] {msg}")

    def self_heal(value, expected_type, default):
        return default if not isinstance(value, expected_type) else value

    def log_event(event_type, message):
        print(f"[LazyGuardian-Event] {event_type}: {message}")

    def _write_log(msg):
        print(f"[LazyGuardian-Write] {msg}")


class UniverseBuilder:
    """Legacy-compatible UniverseBuilder class."""

    def __init__(self, source: str = None):
        self.source = source
        _write_log("UniverseBuilder initialized.")

    def build(self):
        """Build or load the universe from CSV/JSON/default."""
        return build_universe(self.source)


def build_universe(source: str = None):
    """
    Safely build or load Astra’s universe list.

    Parameters
    ----------
    source : str, optional
        Path to a CSV, JSON, or dataset file defining the universe.

    Returns
    -------
    list
        A list of trading symbols or assets.
    """
    import os
    if os.getenv("ASTRA_FASTBOOT") == "1":
        guardian_log("[FastBoot] Skipping full universe build.")
        return []

    cached = CacheManager.get("universe_symbols")
    if cached is not None:
        return cached

    _write_log("Building universe...")

    default_universe = ["AAPL", "MSFT", "GOOG", "NVDA", "AMZN"]

    try:
        if source and os.path.exists(source):
            if source.endswith(".csv"):
                df = pd.read_csv(source)
                if "symbol" in df.columns:
                    symbols = df["symbol"].dropna().unique().tolist()
                else:
                    raise ValueError("CSV missing 'symbol' column.")
            elif source.endswith(".json"):
                with open(source, "r") as f:
                    data = json.load(f)
                    symbols = list(data.get("symbols", []))
            else:
                raise ValueError("Unsupported file format.")
        else:
            symbols = default_universe

        symbols = self_heal(symbols, list, default_universe)
        log_event("universe_build", f"Universe built with {len(symbols)} symbols.")
        CacheManager.set("universe_symbols", symbols, ttl_seconds=3600)
        return symbols

    except Exception as e:
        log_event("universe_error", f"Universe build failed: {e}")
        return default_universe


if __name__ == "__main__":
    builder = UniverseBuilder()
    print("Universe built successfully:", builder.build())
