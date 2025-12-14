"""
🧠 Astra Guardian Schema Validator (v1.0)
-----------------------------------------
Centralized data structure validator and normalizer for all Astra modules.
"""

import json
import os

import pandas as pd

from astra_core.guardian import guardian_log

guardian = guardian_log()

SCHEMA_PATH = os.path.join(guardian.base_dir, "guardian", "data_schemas.json")

DEFAULT_SCHEMAS = {
    "fetch_unified": {
        "expected_fields": ["symbol", "price", "percent_change"],
        "types": {"symbol": "str", "price": "float", "percent_change": "float"},
    },
    "dashboard_data": {
        "expected_fields": ["timestamp", "open", "high", "low", "close", "volume"],
        "types": {
            "timestamp": "datetime64[ns]",
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "float",
        },
    },
}

if not os.path.exists(SCHEMA_PATH):
    os.makedirs(os.path.dirname(SCHEMA_PATH), exist_ok=True)
    with open(SCHEMA_PATH, "w") as f:
        json.dump(DEFAULT_SCHEMAS, f, indent=2)


def validate_and_normalize(data, module_name: str) -> pd.DataFrame:
    schema = DEFAULT_SCHEMAS.get(module_name)
    if not schema:
        guardian.log(f"[Schema] No schema for {module_name}. Skipping validation.")
        return _ensure_dataframe(data)
    df = _ensure_dataframe(data)
    for field in schema["expected_fields"]:
        if field not in df.columns:
            df[field] = None
            guardian.log(f"[Schema] Added missing column '{field}' for {module_name}.")
    for field, dtype in schema["types"].items():
        if field in df.columns:
            try:
                if dtype.startswith("datetime"):
                    df[field] = pd.to_datetime(df[field], errors="coerce")
                elif dtype == "float":
                    df[field] = pd.to_numeric(df[field], errors="coerce")
                elif dtype == "int":
                    df[field] = pd.to_numeric(
                        df[field], errors="coerce", downcast="integer"
                    )
                elif dtype == "str":
                    df[field] = df[field].astype(str)
            except Exception as e:
                guardian.log(
                    f"[Schema Warning] {module_name}: failed to cast {field} to {dtype}: {e}"
                )
    return df


def _ensure_dataframe(data):
    if isinstance(data, pd.DataFrame):
        return data
    if isinstance(data, dict):
        first_value = next(iter(data.values()), [])
        if isinstance(first_value, list):
            return pd.DataFrame(data)
        return pd.DataFrame([data])
    if isinstance(data, list):
        return pd.DataFrame(data)
    guardian.log(
        f"[Schema] Unexpected data type {type(data)}. Returning empty DataFrame."
    )
    return pd.DataFrame()
