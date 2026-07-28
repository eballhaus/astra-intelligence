"""Sentinel and governance diagnostics for the reset boundary.

Produces fail-closed advisory reports about boundary integrity.  No broker
orders or strategy changes are performed here.
"""
from __future__ import annotations

from typing import Any, Mapping

from engine.astra_trading_reset_boundary_v1 import (
    DUST,
    LEGACY_PRE_RESET_POSITION,
    LEGACY_RETIREMENT,
    MIXED_BOUNDARY_LIFECYCLE,
    OWNERSHIP_UNKNOWN,
    POST_RESET_CURRENT,
    PRE_RESET_LEGACY,
    RESET_BOUNDARY_REVIEW_REQUIRED,
    determine_reset_boundary_v1,
    _iso,
    _text,
)


SCHEMA_VERSION = "astra_reset_boundary_sentinel_governance_v1"


def _classify_scope(item: Mapping[str, Any]) -> str:
    return _text(item.get("reset_scope"))


def build_sentinel_reset_boundary_report_v1(
    classifications: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    learning_reports: list[Mapping[str, Any]],
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sentinel report flagging reset-boundary anomalies."""
    boundary = boundary or determine_reset_boundary_v1()
    scopes = [_classify_scope(c) for c in classifications]

    unclassified = any(s == RESET_BOUNDARY_REVIEW_REQUIRED for s in scopes)
    legacy_positions = any(s == LEGACY_PRE_RESET_POSITION for s in scopes)
    legacy_position_slot_leak = any(
        _classify_scope(c) == LEGACY_PRE_RESET_POSITION
        and bool(c.get("strategy_slot_eligible") or c.get("strategy_slot_consumed"))
        for c in classifications
    )
    legacy_dust = any(s == DUST for s in scopes)
    mixed_lifecycle_current = any(
        _classify_scope(c) == MIXED_BOUNDARY_LIFECYCLE
        and c.get("is_post_reset_candidate") is True
        for c in classifications
    )
    post_reset_stalled = (
        metrics.get("metric_scope") == "CURRENT_POST_RESET"
        and metrics.get("eligible_sample_count", 0) == 0
        and len(classifications) > 0
    )

    # Detect leakage: non-current evidence in current metrics or learning.
    non_current_scopes = {
        PRE_RESET_LEGACY,
        LEGACY_PRE_RESET_POSITION,
        LEGACY_RETIREMENT,
        MIXED_BOUNDARY_LIFECYCLE,
        DUST,
        OWNERSHIP_UNKNOWN,
        RESET_BOUNDARY_REVIEW_REQUIRED,
    }
    leaking_ids: list[str] = []
    for c in classifications:
        if _classify_scope(c) in non_current_scopes and c.get("is_post_reset_candidate"):
            rid = _text(c.get("lifecycle_id") or c.get("position_id") or c.get("record_id"))
            if rid:
                leaking_ids.append(rid)
    for report in learning_reports:
        if report.get("learning_eligible") and report.get("truth_scope") != POST_RESET_CURRENT:
            rid = _text(report.get("lifecycle_id") or report.get("truth_id"))
            if rid:
                leaking_ids.append(rid)

    metric_leakage = bool(leaking_ids)

    flags = {
        "reset_boundary_active": boundary.get("status") == "ACTIVE",
        "unclassified_pre_reset_evidence": unclassified,
        "legacy_position_consuming_strategy_slot": legacy_position_slot_leak,
        "legacy_truth_leaking_into_current_metrics": metric_leakage,
        "mixed_lifecycle_marked_current": mixed_lifecycle_current,
        "legacy_retirement_awaiting_approval": legacy_positions or legacy_dust,
        "post_reset_truth_pipeline_stalled": post_reset_stalled,
        "reset_boundary_ambiguity": unclassified,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "reset_id": boundary.get("reset_id"),
        "reset_timestamp_utc": boundary.get("reset_timestamp_utc"),
        "generated_at": _iso(),
        "flags": flags,
        "affected_ids": list(dict.fromkeys(leaking_ids)),
        "classification_counts": _scope_counts(scopes),
        "sentinel_status": "WARNING" if any(flags.values()) else "PASS",
    }


def build_governance_reset_boundary_report_v1(
    classifications: list[Mapping[str, Any]],
    metrics: Mapping[str, Any],
    learning_reports: list[Mapping[str, Any]],
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a governance integrity report for the reset boundary."""
    boundary = boundary or determine_reset_boundary_v1()
    sentinel = build_sentinel_reset_boundary_report_v1(
        classifications, metrics, learning_reports, boundary
    )
    flags = sentinel.get("flags", {})

    current_metric_ok = (
        metrics.get("metric_scope") in {"CURRENT_POST_RESET", "LEGACY_PRE_RESET", "LIFETIME_ALL_BROKER_FACTS", "SHADOW_LEGACY_ANALYSIS"}
        and not flags.get("legacy_truth_leaking_into_current_metrics")
    )

    legacy_isolated = not flags.get("legacy_position_consuming_strategy_slot")
    learning_scope_ok = not any(
        report.get("learning_eligible") and report.get("truth_scope") != POST_RESET_CURRENT
        for report in learning_reports
    )

    current_truth_ids = [
        _text(c.get("lifecycle_id"))
        for c in classifications
        if _classify_scope(c) == POST_RESET_CURRENT
    ]
    truth_provenance_ok = not any(
        _classify_scope(c) == POST_RESET_CURRENT and not c.get("strict_truth_eligible")
        for c in classifications
    )

    # This implementation never submits retirement orders.
    retirement_workflow_ok = True

    integrity = {
        "current_metric_integrity": "PASS" if current_metric_ok else "FAIL",
        "legacy_isolation_integrity": "PASS" if legacy_isolated else "FAIL",
        "learning_scope_integrity": "PASS" if learning_scope_ok else "FAIL",
        "truth_provenance_integrity": "PASS" if truth_provenance_ok else "FAIL",
        "retirement_workflow_integrity": "PASS" if retirement_workflow_ok else "FAIL",
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "reset_id": boundary.get("reset_id"),
        "reset_timestamp_utc": boundary.get("reset_timestamp_utc"),
        "generated_at": _iso(),
        "integrity": integrity,
        "overall_integrity": "PASS" if all(v == "PASS" for v in integrity.values()) else "FAIL",
        "current_truth_lifecycle_ids": [tid for tid in current_truth_ids if tid],
        "governance_status": "PASS" if all(v == "PASS" for v in integrity.values()) else "FAIL",
        "advisory_only": True,
        "execution_authority": "DISABLED",
    }


def _scope_counts(scopes: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in scopes:
        counts[s] = counts.get(s, 0) + 1
    return counts
