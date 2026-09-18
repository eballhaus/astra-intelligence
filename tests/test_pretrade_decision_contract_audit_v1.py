from __future__ import annotations

from datetime import datetime, timezone, timedelta

from engine.astra_premarket_certification_v1 import validate_pretrade_decision_contract
from engine.execution_participation_audit_v1 import _build_record


def valid_contract() -> dict:
    contract = {
        "candidate_id": "cand-1",
        "recommendation_id": "rec-1",
        "decision_id": "dec-1",
        "symbol": "AAPL",
        "lane": "DAY",
        "strategy_archetype": "momentum_continuation",
        "trade_style": "day_trade",
        "ranking_score": 0.0,
        "thesis": "bounded thesis",
        "thesis_supporting_conditions": ["current evidence"],
        "thesis_invalidation_conditions": ["invalidated"],
        "intended_horizon": "day_trade",
        "expected_hold_window": "same session",
        "expected_return_range": {"low_pct": 0.0, "high_pct": 0.5},
        "risk_envelope_id": "risk-1",
        "expected_downside_range": {"low_pct": -1.0, "high_pct": -0.2},
        "expected_drawdown": 0.0,
        "expected_return_per_day_range": {"low_pct_per_day": 0.0, "high_pct_per_day": 0.5},
        "entry_conditions": ["confirmed"],
        "hold_conditions": ["valid"],
        "profit_protection_conditions": ["review"],
        "exit_review_conditions": ["close"],
        "controlled_loss_conditions": ["risk"],
        "replacement_review_conditions": ["replacement"],
        "confidence": 0.0,
        "evidence_classes": ["CURRENT"],
        "monitoring_priorities": ["freshness"],
        "certification_snapshot_id": "snapshot-1",
        "expiry_timestamp": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        "pretrade_enrichment_v1": {"enrichment_ran": True},
        "candidate_risk_envelope_v1": {"risk_envelope_state": "RISK_ENVELOPE_COMPLETE"},
    }
    return contract


def test_complete_contract_has_no_missing_fields():
    result = validate_pretrade_decision_contract(valid_contract())
    assert result["contract_status"] == "VALID"
    assert result["missing_required_fields"] == []
    assert result["order_ready_allowed"] is True


def test_missing_required_field_still_fails_closed():
    contract = valid_contract()
    contract["expected_return_range"] = None
    result = validate_pretrade_decision_contract(contract)
    assert result["contract_status"] == "INVALID"
    assert result["missing_required_fields"] == ["expected_return_range"]
    assert result["order_ready_allowed"] is False


def test_zero_and_false_values_are_not_treated_as_absent():
    contract = valid_contract()
    contract["ranking_score"] = 0.0
    contract["confidence"] = 0.0
    contract["hold_conditions"] = False
    result = validate_pretrade_decision_contract(contract)
    assert "ranking_score" not in result["missing_required_fields"]
    assert "confidence" not in result["missing_required_fields"]
    assert "hold_conditions" not in result["missing_required_fields"]


def test_optional_diagnostics_can_remain_empty_or_unknown():
    contract = valid_contract()
    contract.update({
        "horizon_scores": {},
        "assignment_threshold": None,
        "breakout_probability_score": 0.0,
        "follow_through_probability": 0.0,
        "freshness_state": "unknown",
    })
    result = validate_pretrade_decision_contract(contract)
    assert result["contract_status"] == "VALID"
    assert result["missing_required_fields"] == []


def test_audit_missing_fields_matches_validator_fields():
    record = _build_record(
        {
            "symbol": "AAPL",
            "candidate_id": "cand-1",
            "assigned_horizon": "day_trade",
            "confidence": 80.0,
            "generated_at": "2026-09-18T14:00:00Z",
            "decision_reason": "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
            "pretrade_contract_missing_fields_trace_v1": {
                "missing_required_fields": ["expected_return_range", "candidate_risk_envelope_v1"],
            },
            "order_attempted": False,
            "order_submitted": False,
        },
        {},
    )
    assert record["missing_fields"] == ["expected_return_range", "candidate_risk_envelope_v1"]
    assert record["audit_record_missing_fields"] == []
    assert record["order_submitted"] is False
