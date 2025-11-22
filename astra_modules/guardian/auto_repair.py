"""
auto_repair.py — Guardian 3.0
Automatically repairs objects that do not match schema definitions.
Silent error-only logging for Astra Intelligence.
"""

import pandas as pd
import os
from datetime import datetime
from .schema_contracts import SMARTSCAN_SCHEMA, HYBRIDSCAN_SCHEMA, RANKING_SCHEMA

LOG_PATH = os.path.join("astra_logs", "astra_system_log.txt")


# -------------------------------------------------------------------
# Logging Helper
# -------------------------------------------------------------------
def log_error(msg: str):
    os.makedirs("astra_logs", exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"[{datetime.now()}] {msg}\n")


# -------------------------------------------------------------------
# DataFrame Repair
# -------------------------------------------------------------------
def repair_dataframe(df):
    if not isinstance(df, pd.DataFrame):
        log_error("Guardian3: DF invalid — replaced with empty DataFrame")
        return pd.DataFrame()

    # Ensure index is sorted
    if not df.index.is_monotonic_increasing:
        df = df.sort_index()

    # Require close column
    if "close" not in df.columns:
        df["close"] = 0.0
        log_error("Guardian3: Added missing 'close' column")

    # Optional but recommended
    for col in ["open", "high", "low", "volume"]:
        if col not in df.columns:
            df[col] = 0.0

    df = df.replace([None, float("inf"), -float("inf")], 0).fillna(0)
    return df


# -------------------------------------------------------------------
# Dictionary Repair (Core)
# -------------------------------------------------------------------
def repair_dict(obj: dict, schema: dict):
    """
    Ensures all required fields exist and have valid types.
    Missing fields are created automatically.
    """
    if not isinstance(obj, dict):
        log_error("Guardian3: Object not dict — replacing with empty dict")
        return {}

    repaired = {}

    for key, expected_type in schema.items():

        # Nested schema (SmartScan metrics block)
        if isinstance(expected_type, dict):
            sub = obj.get(key, {})
            if not isinstance(sub, dict):
                sub = {}
                log_error(f"Guardian3: Replaced invalid sub-dict '{key}'")

            # Repair nested contents
            repaired[key] = repair_dict(sub, expected_type)
            continue

        # DataFrame type
        if expected_type == "DataFrame":
            repaired[key] = repair_dataframe(obj.get(key))
            continue

        # Standard fields
        raw = obj.get(key)
        if raw is None:
            # Generate fallback
            if expected_type == list:
                repaired[key] = []
            elif expected_type == str:
                repaired[key] = "Unknown"
            else:
                repaired[key] = expected_type()  # default 0, "", etc.
            log_error(f"Guardian3: Filled missing field '{key}'")
            continue

        # Attempt type conversion
        try:
            if expected_type == list:
                repaired[key] = list(raw)
            else:
                repaired[key] = expected_type(raw)
        except Exception:
            repaired[key] = expected_type()
            log_error(f"Guardian3: Type repair for field '{key}'")

    return repaired
