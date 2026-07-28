"""Dashboard payload builder for reset-aware Astra performance."""
from __future__ import annotations

from typing import Any, Mapping

from engine.astra_trading_reset_boundary_v1 import (
    DUST,
    LEGACY_PRE_RESET_POSITION,
    POST_RESET_CURRENT,
    PRE_RESET_LEGACY,
    build_lane_strict_truth_counts_v1,
    classify_learning_eligibility_v1,
    classify_lifecycle_reset_scope_v1,
    classify_position_reset_scope_v1,
    compute_reset_aware_metrics_v1,
    determine_reset_boundary_v1,
    _iso,
)


def build_dashboard_payload_v1(
    positions: list[Mapping[str, Any]],
    lifecycles: list[Mapping[str, Any]],
    metrics: Mapping[str, Any] | None,
    shadow_analysis: Mapping[str, Any] | None,
    sentinel_report: Mapping[str, Any],
    governance_report: Mapping[str, Any],
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a plain-language dashboard payload with reset-aware sections."""
    boundary = boundary or determine_reset_boundary_v1()

    current_metrics = (
        dict(metrics)
        if metrics is not None
        else compute_reset_aware_metrics_v1(lifecycles, boundary, scope="CURRENT_POST_RESET")
    )
    legacy_metrics = compute_reset_aware_metrics_v1(
        lifecycles, boundary, scope="LEGACY_PRE_RESET"
    )
    lifetime_metrics = compute_reset_aware_metrics_v1(
        lifecycles, boundary, scope="LIFETIME_ALL_BROKER_FACTS"
    )
    truth_counts = build_lane_strict_truth_counts_v1(lifecycles, boundary)

    position_classifications = [
        classify_position_reset_scope_v1(p, boundary) for p in positions
    ]
    legacy_portfolio = [
        c
        for c in position_classifications
        if c.get("reset_scope") in {LEGACY_PRE_RESET_POSITION, DUST}
    ]
    current_portfolio = [
        c
        for c in position_classifications
        if c.get("reset_scope") == POST_RESET_CURRENT
    ]

    learning_eligibility = [
        classify_learning_eligibility_v1(lc, boundary) for lc in lifecycles
    ]
    learning_eligible_count = sum(
        1 for r in learning_eligibility if r.get("learning_eligible")
    )

    return {
        "schema_version": "astra_reset_boundary_dashboard_payload_v1",
        "reset_id": boundary.get("reset_id"),
        "reset_timestamp_utc": boundary.get("reset_timestamp_utc"),
        "generated_at": _iso(),
        "current_astra_performance_since_reset": {
            "plain_language_summary": (
                "Performance metrics include only post-reset, strict-truth eligible "
                "completed lifecycles."
            ),
            "metric_scope": current_metrics.get("metric_scope"),
            "reset_id": current_metrics.get("reset_id"),
            "reset_timestamp": current_metrics.get("reset_timestamp"),
            "eligible_sample_count": current_metrics.get("eligible_sample_count"),
            "excluded_sample_count": current_metrics.get("excluded_sample_count"),
            "exclusion_reasons": current_metrics.get("exclusion_reasons"),
            "evidence_status": current_metrics.get("evidence_status"),
            "completed_trades": current_metrics.get("completed_trades"),
            "win_rate": current_metrics.get("win_rate"),
            "profit_factor": current_metrics.get("profit_factor"),
            "average_return": current_metrics.get("average_return"),
            "average_dollar_pl": current_metrics.get("average_dollar_pl"),
            "entry_quality": current_metrics.get("entry_quality"),
            "exit_quality": current_metrics.get("exit_quality"),
            "avg_hold_duration_minutes": current_metrics.get("avg_hold_duration_minutes"),
        },
        "legacy_portfolio": {
            "plain_language_summary": (
                "Positions and completed lifecycles from before the reset are "
                "isolated for advisory review only; they do not consume current "
                "strategy slots or feed learning."
            ),
            "metric_scope": legacy_metrics.get("metric_scope"),
            "reset_id": legacy_metrics.get("reset_id"),
            "reset_timestamp": legacy_metrics.get("reset_timestamp"),
            "eligible_sample_count": legacy_metrics.get("eligible_sample_count"),
            "excluded_sample_count": legacy_metrics.get("excluded_sample_count"),
            "exclusion_reasons": legacy_metrics.get("exclusion_reasons"),
            "evidence_status": legacy_metrics.get("evidence_status"),
            "legacy_positions_count": len(legacy_portfolio),
            "legacy_positions": legacy_portfolio,
            "legacy_completed_trades": legacy_metrics.get("completed_trades"),
        },
        "current_broker_truths_day_swing_crypto": {
            "plain_language_summary": (
                "Strict broker-confirmed post-reset truths by lane."
            ),
            "metric_scope": current_metrics.get("metric_scope"),
            "reset_id": current_metrics.get("reset_id"),
            "reset_timestamp": current_metrics.get("reset_timestamp"),
            "eligible_sample_count": current_metrics.get("eligible_sample_count"),
            "excluded_sample_count": current_metrics.get("excluded_sample_count"),
            "exclusion_reasons": current_metrics.get("exclusion_reasons"),
            "evidence_status": current_metrics.get("evidence_status"),
            "post_reset_day_strict_truths": truth_counts.get("POST_RESET_DAY_STRICT_TRUTH"),
            "post_reset_swing_strict_truths": truth_counts.get("POST_RESET_SWING_STRICT_TRUTH"),
            "post_reset_crypto_strict_truths": truth_counts.get("POST_RESET_CRYPTO_STRICT_TRUTH"),
            "learning_eligible_count": learning_eligible_count,
            "lane_performance": current_metrics.get("lane_performance", {}),
        },
        "legacy_shadow_lessons": {
            "plain_language_summary": (
                "Advisory-only patterns detected in pre-reset and mixed evidence. "
                "These findings cannot authorize trades, alter thresholds, or promote policy."
            ),
            "metric_scope": "SHADOW_LEGACY_ANALYSIS",
            "reset_id": boundary.get("reset_id"),
            "reset_timestamp": boundary.get("reset_timestamp_utc"),
            "eligible_sample_count": shadow_analysis.get("sample_size") if shadow_analysis else 0,
            "excluded_sample_count": 0,
            "exclusion_reasons": {},
            "evidence_status": "insufficient_evidence" if not shadow_analysis else "advisory_only",
            "shadow_analysis": dict(shadow_analysis) if shadow_analysis else {},
        },
        "lifetime_broker_facts": {
            "plain_language_summary": (
                "All broker-confirmed facts across the lifetime of the account, "
                "kept separate from current performance."
            ),
            "metric_scope": lifetime_metrics.get("metric_scope"),
            "reset_id": lifetime_metrics.get("reset_id"),
            "reset_timestamp": lifetime_metrics.get("reset_timestamp"),
            "eligible_sample_count": lifetime_metrics.get("eligible_sample_count"),
            "excluded_sample_count": lifetime_metrics.get("excluded_sample_count"),
            "exclusion_reasons": lifetime_metrics.get("exclusion_reasons"),
            "evidence_status": lifetime_metrics.get("evidence_status"),
            "completed_trades": lifetime_metrics.get("completed_trades"),
        },
        "sentinel_status": sentinel_report.get("sentinel_status"),
        "governance_status": governance_report.get("overall_integrity"),
        "current_positions_count": len(current_portfolio),
        "advisory_only": True,
        "execution_authority": "DISABLED",
    }
