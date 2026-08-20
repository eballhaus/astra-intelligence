"""Bounded evidence-class and return-plausibility audit for learning metrics."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


VALID_CLASSES = {"BROKER_CONFIRMED", "RECONSTRUCTED", "SHADOW", "REPLAY", "ADVISORY", "INVALID"}
BROKER_CLASSES = {"BROKER_CONFIRMED_COMPLETE", "BROKER_CONFIRMED"}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _evidence_class(row: Mapping[str, Any]) -> str:
    raw = str(row.get("evidence_class") or row.get("truth_quality") or "ADVISORY").upper()
    if raw in BROKER_CLASSES:
        return "BROKER_CONFIRMED"
    if "REPLAY" in raw:
        return "REPLAY"
    if "SHADOW" in raw:
        return "SHADOW"
    if "RECONSTRUCT" in raw or "PARTIAL" in raw:
        return "RECONSTRUCTED"
    if raw in {"INVALID", "AMBIGUOUS_REJECTED"}:
        return "INVALID"
    return "ADVISORY"


def _official_exclusion_reason(row: Mapping[str, Any]) -> str:
    """Return the existing official-metric exclusion reason without mutating truth."""
    if _evidence_class(row) != "BROKER_CONFIRMED":
        return "NON_BROKER_CONFIRMED"
    entry = _number(row.get("entry_price") or row.get("entry"))
    exit_price = _number(row.get("exit_price") or row.get("exit"))
    raw_return = _number(row.get("realized_return") if row.get("realized_return") is not None else row.get("return_pct"))
    if entry is None or entry <= 0:
        return "ZERO_OR_MISSING_COST_BASIS"
    if exit_price is not None and exit_price <= 0:
        return "MALFORMED_EXIT_PRICE"
    if raw_return is not None and abs(raw_return) > 1000.0:
        return "RETURN_PLAUSIBILITY_OUTLIER"
    if raw_return is not None and exit_price is not None:
        implied_pct = ((exit_price - entry) / entry) * 100.0
        if abs(raw_return) > 100.0 and abs(raw_return / 100.0 - implied_pct) < 0.01:
            return "DOUBLE_SCALE_SUSPECT"
    return ""


def official_broker_confirmed_rows(
    rows: Iterable[Mapping[str, Any]], *, max_rows: int = 500
) -> list[dict[str, Any]]:
    """Return bounded official rows using the canonical return-integrity rules."""
    official: list[dict[str, Any]] = []
    inspected = 0
    for raw in rows:
        if inspected >= max_rows or not isinstance(raw, Mapping):
            continue
        inspected += 1
        row = dict(raw)
        if not _official_exclusion_reason(row):
            official.append(row)
    return official


def audit_learning_return_rows(rows: Iterable[Mapping[str, Any]], *, max_rows: int = 500) -> dict[str, Any]:
    """Classify a bounded cache/registry sample without mutating raw evidence."""
    counts = Counter()
    invalid_reasons = Counter()
    suspect_rows = 0
    zero_basis = 0
    outliers = 0
    eligible = 0
    inspected = 0
    for raw in rows:
        if inspected >= max_rows or not isinstance(raw, Mapping):
            continue
        inspected += 1
        row = dict(raw)
        evidence = _evidence_class(row)
        counts[evidence] += 1
        reason = ""
        if evidence == "BROKER_CONFIRMED":
            reason = _official_exclusion_reason(row)
            if reason == "ZERO_OR_MISSING_COST_BASIS":
                zero_basis += 1
            elif reason == "RETURN_PLAUSIBILITY_OUTLIER":
                # Preserve raw value for review; do not silently rescale it.
                suspect_rows += 1
                outliers += 1
            elif reason == "DOUBLE_SCALE_SUSPECT":
                suspect_rows += 1
            if not reason:
                eligible += 1
        if reason:
            invalid_reasons[reason] += 1
    invalid = sum(invalid_reasons.values())
    counts["INVALID"] += invalid
    return {
        "status": "PASS" if not invalid else "PASS_WITH_QUARANTINED_LEGACY_ROWS",
        "rows_inspected": inspected,
        "broker_confirmed_eligible_count": eligible,
        "broker_confirmed_count": counts["BROKER_CONFIRMED"],
        "replay_count": counts["REPLAY"],
        "reconstructed_count": counts["RECONSTRUCTED"],
        "shadow_count": counts["SHADOW"],
        "advisory_count": counts["ADVISORY"],
        "invalid_count": invalid,
        "quarantined_from_official_metrics_count": invalid,
        "quarantine_mode": "derived_official_metric_exclusion_raw_evidence_preserved",
        "outlier_count": outliers,
        "double_scale_suspect_count": invalid_reasons["DOUBLE_SCALE_SUSPECT"],
        "zero_basis_count": zero_basis,
        "top_invalid_reasons": dict(invalid_reasons.most_common(8)),
        "official_metric_source": "broker_confirmed_complete_paper_round_trips_only",
        "official_metrics_guarded": True,
        "raw_values_preserved": True,
        "replay_and_reconstructed_excluded_from_official_metrics": True,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "behavior_safe_to_apply": False,
    }
