"""
pipeline_sanitizer.py — Guardian 3.0 (Phase-90)
Validates and repairs pipeline objects between all major modules.
Ensures SmartScan, HybridScan, and Ranking Engine outputs remain valid,
self-healing, and schema-consistent.
"""

from .schema_contracts import (
    SMARTSCAN_SCHEMA,
    HYBRIDSCAN_SCHEMA,
    RANKING_SCHEMA,
)
from .auto_repair import repair_dict, log_error


# -------------------------------------------------------------------
# SMARTSCAN VALIDATION
# -------------------------------------------------------------------
def sanitize_smartscan(obj):
    """
    Ensures SmartScan output is always a valid dict
    matching SMARTSCAN_SCHEMA.
    Auto-repairs missing fields or invalid structures.
    """
    if obj is None or not isinstance(obj, dict):
        log_error("Guardian3: SmartScan returned invalid or None — auto-repaired.")
        return repair_dict({}, SMARTSCAN_SCHEMA)

    return repair_dict(obj, SMARTSCAN_SCHEMA)


# -------------------------------------------------------------------
# HYBRRIDSCAN VALIDATION
# -------------------------------------------------------------------
def sanitize_hybridscan(obj):
    """
    Ensures HybridScan output is always a valid dict
    matching HYBRIDSCAN_SCHEMA.
    """
    if obj is None or not isinstance(obj, dict):
        log_error("Guardian3: HybridScan returned invalid or None — auto-repaired.")
        return repair_dict({}, HYBRIDSCAN_SCHEMA)

    return repair_dict(obj, HYBRIDSCAN_SCHEMA)


# -------------------------------------------------------------------
# RANKING ENGINE VALIDATION
# -------------------------------------------------------------------
def sanitize_ranking_list(entries: list):
    """
    Ensures the ranking engine output is:
    - A non-empty list
    - Each entry is a valid dictionary
    - Each record matches RANKING_SCHEMA
    """
    if not entries or not isinstance(entries, list):
        log_error("Guardian3: RankingEngine returned invalid or empty list — placeholder injected.")
        return [
            repair_dict(
                {"ticker": "UNKNOWN", "final_score": 0},
                RANKING_SCHEMA,
            )
        ]

    sanitized = []

    for entry in entries:
        if not isinstance(entry, dict):
            log_error("Guardian3: Ranking entry invalid — repairing to dict.")
            entry = {}

        sanitized.append(repair_dict(entry, RANKING_SCHEMA))

    return sanitized
