from __future__ import annotations

import json
from tempfile import TemporaryDirectory

from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1


def _row(symbol: str, lane: str, *, priority: float = 70.0, fit: float = 60.0, asset_type: str = "stock", **extra):
    fit_key = {"SCALP": "scalp_fit_score", "DAY": "day_trade_fit_score", "SWING": "swing_trade_fit_score"}[lane]
    return {
        "symbol": symbol,
        "lane_id": lane,
        "asset_type": asset_type,
        "paper_allocation_priority": priority,
        "risk_adjusted_profit_score": priority,
        "confidence": 70.0,
        "entry_quality_score": 70.0,
        "liquidity_score": 70.0,
        "execution_readiness_score": 70.0,
        fit_key: fit,
        **extra,
    }


def test_lane_pools_are_isolated_and_finalists_have_no_execution_authority() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        rows = owner.decorate_candidates([
            _row("SCALP1", "SCALP", priority=70.0),
            _row("DAY1", "DAY", priority=70.0),
            _row("SWING1", "SWING", priority=70.0),
        ])
        by_symbol = {row["symbol"]: row for row in rows}
        for symbol, lane in (("SCALP1", "SCALP"), ("DAY1", "DAY"), ("SWING1", "SWING")):
            assert by_symbol[symbol]["lane_ranked_entry_lane"] == lane
            assert by_symbol[symbol]["lane_shortlist_rank"] == 1
            assert by_symbol[symbol]["lane_finalist"] is True
            assert by_symbol[symbol]["finalist_is_not_execution_authority"] is True
            assert "order_ready" not in by_symbol[symbol]


def test_optional_quality_evidence_is_neutral_and_never_rejects_a_candidate() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        source = _row("OPTIONAL", "DAY")
        prior_allocation = owner.score_row(source)["exploration_allowed"]
        row = owner.decorate_candidates([source])[0]
        assert row["relative_strength_state"] == "UNAVAILABLE"
        assert row["relative_volume_source"] == "UNAVAILABLE"
        assert row["entry_extension_source"] == "UNAVAILABLE"
        assert row["lane_soft_ranking_adjustment"] != 0.0  # Existing DAY fit remains usable.
        assert row["exploration_allowed"] is prior_allocation


def test_new_strong_candidate_can_outrank_weaker_incumbent_without_history() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        rows = owner.decorate_candidates([
            _row("INCUMBENT", "SCALP", priority=70.0, fit=55.0, momentum_score=55.0),
            _row("NEW", "SCALP", priority=70.0, fit=95.0, momentum_score=95.0, relative_volume_score=95.0),
        ])
        by_symbol = {row["symbol"]: row for row in rows}
        assert by_symbol["NEW"]["lane_shortlist_rank"] == 1
        assert by_symbol["NEW"]["rank_persistence_observations"] == 0
        assert by_symbol["NEW"]["rank_persistence_state"] == "NEW_CANDIDATE"


def test_real_market_relative_strength_is_available_only_with_real_benchmark_evidence() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        rows = owner.decorate_candidates([
            _row("SPY", "DAY", change_percent="1.0%"),
            _row("LEADER", "DAY", change_percent="3.0%"),
        ])
        leader = next(row for row in rows if row["symbol"] == "LEADER")
        assert leader["relative_strength_state"] == "AVAILABLE"
        assert leader["relative_strength_market_delta_pct"] == 2.0
        assert leader["relative_strength_market_score"] == 70.0


def test_rank_state_is_bounded_and_crypto_priority_is_unchanged() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        crypto = _row("BTC-USD", "DAY", asset_type="crypto", priority=80.0)
        expected_crypto_priority = owner.score_row(crypto)["paper_allocation_priority"]
        day_rows = [_row(f"D{i:03d}", "DAY", priority=60.0 + (i / 100.0)) for i in range(100)]
        rows = owner.decorate_candidates(day_rows + [crypto])
        crypto_out = next(row for row in rows if row["symbol"] == "BTC-USD")
        assert crypto_out["paper_allocation_priority"] == expected_crypto_priority
        assert "lane_ranked_entry_funnel_v1" not in crypto_out
        with open(owner.ranked_entry_state_path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
        assert len(state["lanes"]["DAY"]["symbols"]) <= 80


def test_ranked_entry_cohort_is_write_once() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        first = owner._ranked_entry_cohort()
        second = owner._ranked_entry_cohort()
        assert first == second
        assert first["change_id"] == "LANE_RANKED_ENTRY_FUNNEL_V1"


def test_status_reports_lane_attrition_without_turning_finalists_into_orders() -> None:
    with TemporaryDirectory() as directory:
        owner = PaperOpportunityAllocationEngineV1(state_dir=directory)
        status = owner.status([_row("DAY1", "DAY"), _row("SCALP1", "SCALP")])
        funnel = status["lane_ranked_entry_funnel_v1"]
        assert funnel["hard_gate_changes"] is False
        assert funnel["lanes"]["DAY"]["finalists"] == 1
        assert funnel["lanes"]["DAY"]["order_ready"] == 0
