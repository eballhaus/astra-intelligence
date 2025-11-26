"""
Universe Builder – Phase-90 Unified Version
-------------------------------------------
Provides both the UniverseBuilder class (for legacy modules)
and build_universe() function (for Phase-90 components).
Integrated with GuardianV6 for self-healing and logging.
"""

import os
import pandas as pd
from astra_modules.guardian.guardian_v6 import GuardianV6

guardian = GuardianV6(os.path.dirname(__file__))


class UniverseBuilder:
    """Legacy-compatible UniverseBuilder class."""

    def __init__(self, source: str = None):
        self.source = source
        guardian._write_log("UniverseBuilder initialized.")

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
    guardian._write_log("Building universe...")

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
                import json
                with open(source, "r") as f:
                    data = json.load(f)
                    symbols = list(data.get("symbols", []))
            else:
                raise ValueError("Unsupported file format.")
        else:
            symbols = default_universe

        symbols = guardian.self_heal(symbols, list, default_universe)
        guardian.log_event("universe_build", f"Universe built with {len(symbols)} symbols.")
        return symbols

    except Exception as e:
        guardian.log_event("universe_error", f"Universe build failed: {e}")
        return default_universe


if __name__ == "__main__":
    builder = UniverseBuilder()
    print("Universe built successfully:", builder.build())

