from __future__ import annotations

from datetime import datetime, timezone

from engine.astra_daily_intelligence_summary_v1 import (
    build_astra_daily_intelligence_summary_v1,
    bundle1_statuses_with_canonical_truths,
)
from engine.astra_intelligence_effectiveness_learning_velocity_v1 import (
    AstraIntelligenceEffectivenessLearningVelocityV1,
)


NOW = datetime(2026, 8, 20, 16, 0, tzinfo=timezone.utc)


def _truth(identifier: str, *, lane: str = "DAY", entry: str = "2026-08-20T13:00:00Z", exit: str = "2026-08-20T15:00:00Z", result: float = 1.0) -> dict:
    return {
        "truth_id": identifier,
        "lifecycle_id": f"life-{identifier}",
        "symbol": "ABC",
        "lane_id": lane,
        "entry_timestamp": entry,
        "exit_timestamp": exit,
        "created_at": exit,
        "realized_return_pct": result,
    }


def _bundle1() -> dict:
    return {
        "generated_at": "2026-08-20T15:59:00Z",
        "truth_progression_v1": {
            "official_truth_source": "BROKER_CONFIRMED_CANONICAL_ONLY",
            "is_astra_improving": "MIXED",
            "overall": {"status": "FLAT_OR_MIXED", "truth_count": 2, "win_rate": 50.0, "profit_factor": 1.2, "average_return": 0.1, "median_return": 0.1, "cohorts": {}},
        },
        "canonical_lesson_outcome_linkage_v1": {"lessons": [{"lesson_id": "one"}], "linked_outcomes": 1, "explicit_application_events": 1},
        "lesson_effectiveness_v1": {"improved_outcomes": 1, "worsened_outcomes": 0, "effective_lessons": 0, "underperforming_lessons": 0},
        "mistake_recurrence_lesson_linkage_v1": {"recurrence_after_lesson_count": 0},
        "contextual_learning_summary_v1": {"lessons_evaluated": 1, "lane_specific_lessons": 1, "regime_specific_lessons": 0, "globally_applicable_lessons": 0, "generalization_not_proven": 1, "context_mismatches": 0, "contradictions_resolved_by_context": 0, "contradictions_unresolved": 0, "cross_lane_leakage_detected": False, "regime_leakage_detected": False},
        "learning_loop_summary_v1": {"is_astra_improving": "MIXED"},
    }


def _bundle2() -> dict:
    return {"generated_at": "2026-08-20T15:59:30Z", "completed_broker_truth_sample_size": 2, "profitable_trade_count": 1, "losing_trade_count": 1, "top_success_drivers": [{"driver": "entry_quality", "count": 1}], "top_failure_drivers": [{"driver": "exit_delay", "count": 1}], "controlled_loss_count": 1, "partly_preventable_loss_count": 0, "preventable_loss_count": 0, "losses_not_proven_count": 0, "average_return_per_hour": 0.2, "median_return_per_hour": 0.2, "average_realized_return_per_day": 1.0}


def _health() -> dict:
    return {"generated_at": "2026-08-20T15:59:20Z", "strict_truth_total": 2, "truths_consumed_by_learning_total": 1, "sentinel_status": "PASS", "governance_status": "PASS", "cortex_status": "PASS", "control_plane_agreement": True, "lanes": {"DAY": {"broker_confirmed_active_positions": 0, "waiting_state": "LEGITIMATE_WAIT", "current_lifecycle_stage": "STRICT_BROKER_TRUTH", "first_causal_blocker": "NO_CURRENT_MARKET_OPPORTUNITY", "blocker_validity": "VALID_STRATEGY_REJECTION"}}}


def _build(**overrides) -> dict:
    arguments = {
        "canonical_truths": [_truth("one", result=1.0), _truth("two", lane="SCALP", result=-0.8)],
        "bundle1": _bundle1(),
        "bundle2": _bundle2(),
        "operating_health": _health(),
        "worker_state": {"heartbeat_at": "2026-08-20T15:59:55Z"},
        "control_plane": {"generated_at": "2026-08-20T15:59:45Z", "active_root_causes": []},
        "provider_health": {"generated_at": "2026-08-20T15:59:40Z", "status": "PASS"},
        "now": NOW,
    }
    arguments.update(overrides)
    return build_astra_daily_intelligence_summary_v1(**arguments)


def test_uses_canonical_truths_and_surfaces_count_disagreement() -> None:
    result = _build(secondary_truth_counts={"legacy_summary": 0})
    assert result["today_at_a_glance"]["total_canonical_truths"] == 2
    assert result["contract_disagreements"][0]["status"] == "CONTRACT_DISAGREEMENT"
    assert result["contract_disagreements"][0]["canonical_value"] == 2


def test_bundle_and_operating_health_truth_counts_cannot_claim_alignment_when_stale() -> None:
    result = _build(
        bundle1={**_bundle1(), "truth_progression_v1": {**_bundle1()["truth_progression_v1"], "overall": {**_bundle1()["truth_progression_v1"]["overall"], "truth_count": 1}}},
        operating_health={**_health(), "strict_truth_total": 0},
    )

    assert result["truth_contract_status"] == "CONTRACT_DISAGREEMENT"
    assert {row["conflicting_source"] for row in result["contract_disagreements"]} >= {
        "operating_health.strict_truth_total",
        "bundle1.truth_progression_v1.overall.truth_count",
    }


def test_noncanonical_closed_rows_are_separate_from_official_truth_totals() -> None:
    result = _build(noncanonical_or_legacy_records=[{"symbol": "LEGACY", "closed_indicator": True}])
    assert result["truth_contract_status"] == "ALIGNED"
    assert result["canonical_truth_total"] == 2
    assert result["noncanonical_or_legacy_records"] == {"count": 1, "symbols": ["LEGACY"], "official_metrics_excluded": True}


def test_today_filter_uses_report_timezone_and_separates_prior_day_activity() -> None:
    # 02:00Z is still the prior calendar day in America/New_York.
    result = _build(canonical_truths=[_truth("prior", entry="2026-08-19T20:00:00Z", exit="2026-08-20T02:00:00Z")])
    assert result["report_date"] == "2026-08-20"
    assert result["today_at_a_glance"]["trades_entered_today"] == 0
    assert result["today_at_a_glance"]["trades_closed_today"] == 0


def test_bundle_outputs_are_consumed_without_recomputing_attribution_or_context() -> None:
    result = _build()
    assert result["bundle2"]["top_failure_drivers"] == [{"driver": "exit_delay", "count": 1}]
    assert result["bundle3"]["lane_specific_lessons"] == 1
    assert result["efficiency"]["large_file_full_scans"] == 0
    assert result["efficiency"]["provider_calls"] == result["efficiency"]["broker_calls"] == result["efficiency"]["llm_calls"] == 0


def test_bundle1_receives_the_same_canonical_truths_as_daily_summary() -> None:
    truths = [
        {
            **_truth("one"),
            "evidence_class": "BROKER_CONFIRMED_COMPLETE",
            "entry_price": 10.0,
            "exit_price": 11.0,
            "realized_return": 10.0,
        },
        {
            **_truth("two", lane="DAY", result=-1.0),
            "evidence_class": "BROKER_CONFIRMED_COMPLETE",
            "entry_price": 10.0,
            "exit_price": 9.9,
            "realized_return": -1.0,
        },
    ]
    statuses = bundle1_statuses_with_canonical_truths({"broker_truth_records_v1": []}, truths)

    result = AstraIntelligenceEffectivenessLearningVelocityV1().status(statuses=statuses, force=True)

    assert result["truth_progression_v1"]["overall"]["truth_count"] == 2


def test_lanes_remain_separated_and_zero_truth_lane_is_explicit() -> None:
    result = _build()
    assert result["today_at_a_glance"]["truths_by_lane"]["DAY"] == 1
    assert result["today_at_a_glance"]["truths_by_lane"]["SCALP"] == 1
    assert result["lanes"]["CRYPTO"]["total_truths"] == 0
    assert result["lanes"]["CRYPTO"]["truth_readiness"] == "INSUFFICIENT_EVIDENCE"


def test_market_data_wait_is_not_reported_as_a_lane_defect() -> None:
    health = {
        **_health(),
        "lanes": {
            "SWING": {
                "broker_confirmed_active_positions": 0,
                "waiting_state": "LEGITIMATE_WAIT",
                "current_lifecycle_stage": "candidate_freshness",
                "first_causal_blocker": "CANDIDATE_STALE",
                "blocker_validity": "VALID_MARKET_DATA_LIMITATION",
            },
        },
    }
    result = _build(operating_health=health)
    assert result["lanes"]["SWING"]["status"] == "LEGITIMATE_WAIT"
    assert result["lanes"]["SWING"]["truth_readiness"] == "WAITING_NATURAL_EVIDENCE"


def test_pending_position_is_not_promoted_to_closed_truth() -> None:
    result = _build(open_positions=[{"symbol": "PENDING", "lane_id": "DAY", "lifecycle_id": "open", "broker_confirmed": True, "reconciliation_state": "FILLED_AWAITING_BROKER_ZERO"}])
    assert result["today_at_a_glance"]["reconciliation_pending_count"] == 1
    assert len(result["daily_activity"]["completed_today"]) == 2
    assert result["current_open_positions"]["broker_confirmed_active"][0]["symbol"] == "PENDING"


def test_lane_monitor_counts_are_not_presented_as_canonical_positions_without_position_input() -> None:
    result = _build(operating_health={**_health(), "lanes": {"SWING": {"broker_confirmed_active_positions": 40}}})

    assert result["today_at_a_glance"]["current_open_broker_positions"] == 0
    assert result["lanes"]["SWING"]["open_positions"] == 0
    assert result["lanes"]["SWING"]["lane_monitor_active_count"] == 40
    assert result["lanes"]["SWING"]["lane_monitor_position_count_status"] == "UNVERIFIED_COMPACT_POSITION_LIST_UNAVAILABLE"


def test_shadow_or_replay_input_cannot_enter_official_truth_metrics() -> None:
    # The caller supplies only the canonical broker-truth owner output.  A
    # shadow/replay row is not independently promoted by this consumer.
    result = _build(canonical_truths=[_truth("official")])
    assert result["today_at_a_glance"]["total_canonical_truths"] == 1
    assert result["current_canonical_profitability"]["official_truth_source"] == "BROKER_CONFIRMED_CANONICAL_ONLY"


def test_stale_or_missing_dependencies_are_exposed_and_optional_metrics_remain_unavailable() -> None:
    result = _build(provider_health={})
    assert "provider_health" in result["data_freshness"]["stale_dependencies"]
    assert result["today_at_a_glance"]["today_realized_pnl_dollars"] is None
    assert result["current_canonical_profitability"]["best_trade_return"] is None


def test_summary_is_idempotent_and_reporting_only() -> None:
    first, second = _build(), _build()
    first["efficiency"].pop("generation_ms")
    second["efficiency"].pop("generation_ms")
    assert first == second
    assert first["reporting_only"] is True
    assert first["execution_authority"] == "NONE"
    assert first["trading_behavior_changed"] is False
