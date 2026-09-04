from __future__ import annotations

from datetime import UTC, datetime

from engine.astra_natural_truth_lifecycle_intelligence_v1 import (
    build_lesson_evidence_gate_v1,
    build_natural_truth_lifecycle_intelligence_v1,
    build_truth_quality_assessment_v1,
)
from engine.astra_premarket_certification_v1 import build_runtime_certification_v1


def _truth(lifecycle_id: str = "life-1", lane: str = "DAY", **extra) -> dict:
    row = {
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "truth_state": "BROKER_TRUTH_CONFIRMED",
        "natural_trade_label": f"NATURAL_PAPER_{lane}_EQUITY",
        "paper_mode_verified": True,
        "lifecycle_id": lifecycle_id,
        "lane_id": lane,
        "symbol": "ABC",
        "entry_order_id": f"entry-order-{lifecycle_id}",
        "entry_fill_id": f"entry-fill-{lifecycle_id}",
        "entry_timestamp": "2026-08-20T13:00:00Z",
        "entry_price": 100.0,
        "entry_quantity": 1.0,
        "exit_order_id": f"exit-order-{lifecycle_id}",
        "exit_fill_id": f"exit-fill-{lifecycle_id}",
        "exit_timestamp": "2026-08-20T14:00:00Z",
        "exit_price": 101.0,
        "exit_filled_quantity": 1.0,
        "broker_residual_zero_confirmed": True,
        "learning_acknowledged": True,
        "realized_return": 1.0,
        "lesson_id": "lesson-day",
        "pretrade_context_v1": {"market_regime": "TREND", "thesis": "recorded"},
    }
    row.update(extra)
    return row


def _runtime() -> dict:
    return {
        "position_lane_horizon_recovery_v1": {
            "positions": [{
                "symbol": "ABC",
                "canonical_lifecycle_id": "life-open",
                "canonical_position_id": "life-open",
                "entry_fill_id": "entry-open",
                "entry_order_id": "entry-open-order",
                "candidate_id": "candidate-open",
                "lane": "DAY",
                "horizon": "day_trade",
                "canonical_identity_status": "RESOLVED",
                "position_owner": "PaperAutopilot",
            }],
        },
        "position_exit_readiness_v1": {
            "positions": [{
                "symbol": "ABC",
                "canonical_position_id": "life-open",
                "exit_readiness_state": "HOLD",
                "recommendation": "HOLD",
            }],
        },
        "active_equity_fmp_observations_v1": {
            "observations": {"ABC": {
                "provider": "alpaca_ws",
                "provider_native_timestamp": "2026-08-20T13:30:00Z",
                "receive_timestamp": "2026-08-20T13:30:01Z",
                "freshness_state": "CURRENT",
            }},
        },
        "multilane_completion_matrix": {"lanes": {"DAY": {
            "candidate_count": 2,
            "eligible_candidate_count": 1,
            "finalist_count": 1,
            "order_ready_count": 0,
            "paper_order_intents": 0,
        }}},
        "shadow_exit_intelligence_v1": {"evaluations": [{"symbol": "ABC"}]},
    }


def _readiness(*, fault: dict | None = None) -> dict:
    lane = {
        "last_discovery_time": "2026-08-20T13:00:00Z",
        "last_candidate_time": "2026-08-20T13:00:00Z",
        "last_management_evaluation_time": "2026-08-20T13:30:00Z",
        "technical_readiness": "TECHNICALLY_READY",
        "current_earliest_blocker": "",
        "technical_truth_starvation_status": "NATURAL_OPEN_POSITION",
    }
    return {
        "truth_production_watchdog": {"lanes": {"DAY": lane, "SCALP": {}, "SWING": {}, "CRYPTO": {}}},
        "active_faults": [fault] if fault else [],
    }


def test_open_lifecycle_joins_canonical_identity_and_preserves_fresh_observation() -> None:
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state=_runtime(),
        readiness=_readiness(),
        open_positions=[{"symbol": "ABC", "qty": 1.0, "original_lane": "DAY", "original_horizon": "day_trade"}],
        current_commit="test",
        now=datetime(2026, 8, 20, 13, 31, tzinfo=UTC),
    )
    row = result["current_lifecycle_state"][0]
    assert row["lifecycle_id"] == "life-open"
    assert row["entry_fill_id"] == "entry-open"
    assert row["current_stage"] == "NATURAL_EXIT"
    assert row["observation"]["provider_native_timestamp"] == "2026-08-20T13:30:00Z"
    assert row["observation"]["receive_timestamp"] == "2026-08-20T13:30:01Z"
    assert row["pre_exit_reconciliation_assurance"]["status"] == "PASS"
    assert row["wait_classification"] == "NATURAL_WAIT"
    assert result["lane_truth_starvation_scorecard"]["DAY"]["candidates"] == 2
    assert result["lane_truth_starvation_scorecard"]["DAY"]["finalists"] == 1
    assert result["safety"]["production_truths_created"] == 0


def test_missing_identity_is_explicit_and_never_assigned_by_symbol() -> None:
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state={},
        readiness=_readiness(),
        open_positions=[{"symbol": "ABC", "qty": 1.0, "original_lane": "DAY"}],
        current_commit="test",
    )
    row = result["current_lifecycle_state"][0]
    assert row["lifecycle_id"] is None
    assert row["current_stage"] == "POSITION_IDENTITY"
    assert row["wait_classification"] == "EXTERNAL_WAIT"
    assert row["pre_exit_reconciliation_assurance"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert row["pre_exit_reconciliation_assurance"]["mutation_performed"] is False


def test_truth_accounting_accepts_strict_truth_or_explicit_external_blocker() -> None:
    fault = {
        "fault_type": "RECONCILIATION_FAILURE",
        "classification": "BROKER_EXTERNAL",
        "earliest_stage": "RECONCILIATION",
        "failing_invariant": "BROKER_FILLED_EXIT_RECONCILES_TO_CANONICAL_LIFECYCLE",
        "lifecycle_id": "life-blocked",
        "lanes": ["DAY"],
    }
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state={},
        readiness=_readiness(fault=fault),
        truth_records=[_truth()],
        learning_records=[{"lifecycle_id": "life-1", "truth_id": "life-1"}],
        current_commit="test",
    )
    accounting = result["truth_accounting_integrity"]
    assert accounting["strict_truth_count"] == 1
    assert accounting["explicitly_blocked_completion_count"] == 1
    assert accounting["unexplained_gaps"] == 0
    assert accounting["status"] == "PASS"


def test_learning_quality_does_not_change_strict_truth_and_missing_detail_is_explicit() -> None:
    quality = build_truth_quality_assessment_v1({"lifecycle_id": "life", "entry_fill_id": "entry"})
    assert quality["grade"] == "MINIMAL_STRICT_TRUTH"
    assert quality["strict_truth_validity_unchanged"] is True
    assert "entry_context" in quality["missing_or_unavailable"]


def test_lesson_gate_is_lane_aware_low_sample_and_non_promotional() -> None:
    result = build_lesson_evidence_gate_v1(
        lessons=[{"lesson_id": "lesson-day"}],
        truth_records=[_truth()],
    )
    evaluation = result["evaluations"][0]
    assert evaluation["applicable_lanes"] == ["DAY"]
    assert evaluation["lane_scope"] == "LANE_SPECIFIC"
    assert evaluation["promotion_state"] == "EVIDENCE_ACCUMULATING"
    assert evaluation["low_sample_confidence_guard"] is True
    assert evaluation["automatic_promotion"] is False
    assert evaluation["execution_authority"] == "NONE"


def test_shadow_evidence_is_visible_but_never_promoted_to_truth() -> None:
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state=_runtime(),
        readiness=_readiness(),
        truth_records=[_truth()],
        current_commit="test",
    )
    shadow = result["shadow_counterfactual_status"]
    assert shadow["available"] is True
    assert shadow["broker_truth_separate"] is True
    assert shadow["promoted_to_broker_truth"] is False
    assert result["truth_accounting_integrity"]["strict_truth_count"] == 1


def test_completed_truths_receive_learning_quality_without_new_position_rows() -> None:
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state={},
        readiness=_readiness(),
        truth_records=[_truth()],
        current_commit="test",
    )
    assert result["current_lifecycle_state"] == []
    assert len(result["truth_quality_assessments"]) == 1
    assert len(result["outcome_attribution"]) == 1
    assert result["truth_quality_assessments"][0]["lifecycle_id"] == "life-1"


def test_premarket_certification_rejects_unexplained_truth_accounting_gap() -> None:
    result = build_runtime_certification_v1(
        worker_state={
            "active_worker_present": True,
            "active_worker_pid": 1,
            "process_role": "PAPER_AUTOPILOT_WORKER",
            "worker_count": 1,
            "heartbeat_at": "2026-08-20T13:30:00Z",
            "last_cycle_completed_at": "2026-08-20T13:30:01Z",
            "cycle_count": 1,
            "resource_state": "RESOURCE_NORMAL",
            "runtime_revision": "test",
        },
        runtime_state={
            "astra_natural_truth_lifecycle_intelligence_v1": {
                "truth_accounting_integrity": {
                    "status": "FAIL",
                    "unexplained_gaps": 1,
                },
            },
        },
        readiness={
            "generated_at": "2026-08-20T13:30:00Z",
            "discovery_integrity": "READY",
            "strict_truth_integrity": "READY",
            "truth_production_watchdog": {"lanes": {}},
        },
        backend_health={"ok": True, "runtime_revision": "test"},
        expected_revision="test",
        now=datetime(2026, 8, 20, 13, 30, 2, tzinfo=UTC),
    )
    assert result["checks"]["lifecycle_truth_continuity"]["passed"] is False
    assert result["checks"]["truth_path"]["passed"] is False


def test_open_position_wait_is_not_entry_truth_starvation() -> None:
    runtime = {
        "position_lane_horizon_recovery_v1": {
            "positions": [{
                "symbol": "ETH/USD",
                "canonical_lifecycle_id": "crypto-life",
                "entry_fill_id": "crypto-entry",
                "lane": "CRYPTO",
                "horizon": "day_trade",
                "canonical_identity_status": "RESOLVED",
            }],
        },
        "multilane_completion_matrix": {
            "lanes": {
                "CRYPTO": {
                    "candidate_count": 3,
                    "eligible_candidate_count": 0,
                    "first_blocker": "capacity_concentration",
                },
            },
        },
    }
    readiness = {
        "truth_production_watchdog": {
            "lanes": {
                "CRYPTO": {
                    "technical_readiness": "TECHNICALLY_READY",
                    "current_earliest_blocker": "candidate contract -> eligibility gate",
                    "technical_truth_starvation_status": "ENTRY_PIPELINE_TECHNICAL_FAILURE",
                },
            },
        },
    }
    result = build_natural_truth_lifecycle_intelligence_v1(
        runtime_state=runtime,
        readiness=readiness,
        open_positions=[],
        current_commit="test",
    )
    scorecard = result["lane_truth_starvation_scorecard"]["CRYPTO"]
    assert scorecard["current_truth_blocker"] == "NATURAL_OPEN_POSITION"
    assert scorecard["truth_starvation_status"] == "NATURAL_OPEN_POSITION"
