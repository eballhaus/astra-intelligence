from __future__ import annotations

from engine.adaptive_profit_capture_intelligence_v1 import (
    build_profit_capture_trade_effectiveness_v2,
)


def _truth(*, lifecycle_id: str = "life-1", realized: float = 2.0, peak: float = 3.0, **extra: object) -> dict:
    row: dict[str, object] = {
        "lifecycle_id": lifecycle_id,
        "stable_key": f"truth:{lifecycle_id}",
        "position_id": f"position:{lifecycle_id}",
        "symbol": "ABC",
        "lane_id": "DAY",
        "intended_horizon": "day_trade",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "entry_fill_id": f"entry:{lifecycle_id}",
        "exit_fill_id": f"exit:{lifecycle_id}",
        "entry_price": 100.0,
        "exit_price": 100.0 + realized,
        "realized_return_pct": realized,
        "max_favorable_excursion_pct": peak,
        "entry_timestamp": "2026-08-20T10:00:00Z",
        "exit_timestamp": "2026-08-20T12:00:00Z",
        "exit_reason": "TAKE_PROFIT",
    }
    row.update(extra)
    return row


def test_canonical_winner_has_deterministic_attribution_and_exact_return_per_time() -> None:
    result = build_profit_capture_trade_effectiveness_v2([
        _truth(selection_quality_state="SUPPORTED_POSITIVE", entry_timing_state="SUPPORTED_POSITIVE"),
    ])
    row = result["trade_rows"][0]
    assert row["decision_attribution"]["primary_success_driver"] == "selection_quality"
    assert row["hold_duration_seconds"] == 7200.0
    assert row["realized_return_per_hour"] == 1.0
    assert row["realized_return_per_day"] == 24.0
    assert row["time_normalization_state"] == "STABLE"


def test_canonical_loser_controlled_by_authorized_stop_is_not_preventable() -> None:
    row = build_profit_capture_trade_effectiveness_v2([
        _truth(realized=-1.0, peak=0.0, exit_reason="STOP_LOSS"),
    ])["trade_rows"][0]
    assert row["loss_anatomy"]["loss_classification"] == "CONTROLLED_EXPECTED_LOSS"
    assert row["loss_anatomy"]["preventability"] == "CONTROLLED"


def test_missing_attribution_evidence_stays_unavailable() -> None:
    row = build_profit_capture_trade_effectiveness_v2([_truth()])["trade_rows"][0]
    states = {item["dimension"]: item["state"] for item in row["decision_attribution"]["dimensions"]}
    assert states["selection_quality"] == "UNAVAILABLE"
    assert states["regime_context"] == "UNAVAILABLE"


def test_proven_exit_trigger_before_exit_classifies_preventable_delay() -> None:
    row = build_profit_capture_trade_effectiveness_v2([
        _truth(realized=-2.0, peak=0.0, exit_reason="STOP_LOSS", exit_trigger_timestamp="2026-08-20T11:00:00Z"),
    ])["trade_rows"][0]
    assert row["loss_anatomy"]["loss_classification"] == "PREVENTABLE_EXIT_DELAY"
    assert row["loss_anatomy"]["preventability"] == "PREVENTABLE"


def test_proven_deterioration_before_severe_giveback_classifies_preventable_giveback() -> None:
    row = build_profit_capture_trade_effectiveness_v2([
        _truth(realized=-2.0, peak=10.0, momentum_deterioration_observed_at="2026-08-20T11:00:00Z"),
    ])["trade_rows"][0]
    assert row["profit_capture_classification"] == "SEVERE_GIVEBACK"
    assert row["loss_anatomy"]["loss_classification"] == "PREVENTABLE_PROFIT_GIVEBACK"


def test_overhold_requires_authoritative_expected_hold_evidence() -> None:
    row = build_profit_capture_trade_effectiveness_v2([
        _truth(realized=-1.0, peak=0.0, expected_hold_seconds=1800),
    ])["trade_rows"][0]
    assert row["loss_anatomy"]["loss_classification"] == "PREVENTABLE_OVERHOLD"
    assert row["expected_vs_actual_hold_ratio"] == 4.0


def test_shadow_comparison_does_not_replace_official_broker_result() -> None:
    result = build_profit_capture_trade_effectiveness_v2(
        [_truth(realized=-2.0, peak=1.0)],
        shadow_exit_outputs={"outputs": [{"lifecycle_id": "life-1", "shadow_return_pct": 3.0}]},
    )
    assert result["trade_rows"][0]["realized_return_pct"] == -2.0
    assert result["counterfactual_exit_comparisons"][0]["shadow_only"] is True


def test_zero_or_invalid_exact_duration_is_not_normalized() -> None:
    row = build_profit_capture_trade_effectiveness_v2([
        _truth(exit_timestamp="2026-08-20T10:00:00Z"),
    ])["trade_rows"][0]
    assert row["hold_duration_seconds"] is None
    assert row["time_normalization_state"] == "NORMALIZATION_UNSTABLE"
    assert row["realized_return_per_hour"] is None


def test_replay_only_rows_are_excluded_and_processing_is_idempotent() -> None:
    rows = [_truth(), _truth(lifecycle_id="replay", evidence_class="REPLAY", truth_quality="REPLAY")]
    first = build_profit_capture_trade_effectiveness_v2(rows)
    second = build_profit_capture_trade_effectiveness_v2(rows)
    assert first["completed_broker_truth_sample_size"] == 1
    assert first["trade_rows"] == second["trade_rows"]
    assert first["full_history_scan_count"] == 0


def test_bundle_one_return_integrity_and_no_external_authority_are_preserved() -> None:
    result = build_profit_capture_trade_effectiveness_v2([
        _truth(realized=2.0),
        _truth(lifecycle_id="outlier", realized=2001.0, peak=2002.0),
    ])
    assert result["completed_broker_truth_sample_size"] == 1
    assert result["provider_calls_used"] == result["broker_calls_used"] == result["llm_calls_used"] == 0
    assert result["execution_behavior_changed"] is False
    assert result["paper_only_preserved"] is True
