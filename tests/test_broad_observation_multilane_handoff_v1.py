from __future__ import annotations

from pathlib import Path

from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1


def _observation(symbol: str = "TEST") -> dict:
    return {
        "symbol": symbol,
        "price": 100.0,
        "bid": 99.9,
        "ask": 100.1,
        "quote_age_seconds": 1.0,
        "freshness_state": "CURRENT",
        "execution_freshness_state": "CURRENT",
        "observation_authority": False,
        "executable_evidence": False,
    }


def _candidate(symbol: str, lane: str, *, duplicate: bool = False) -> dict:
    horizon = {"DAY": "day_trade", "SCALP": "scalp", "SWING": "swing_trade"}[lane]
    return {
        "symbol": symbol,
        "lane_id": lane,
        "paper_entry_horizon_style": horizon,
        "candidate_id": f"candidate-{lane.lower()}-{symbol.lower()}-{int(duplicate)}",
        "recommendation_id": f"recommendation-{lane.lower()}-{symbol.lower()}-{int(duplicate)}",
        "candidate_source": "fixture",
    }


def _qualified_observation(symbol: str, lane: str) -> dict:
    row = {
        **_observation(symbol),
        "qualified": True,
        "eligible": True,
        "candidate_id": f"candidate-{lane.lower()}-{symbol.lower()}",
        "recommendation_id": f"recommendation-{lane.lower()}-{symbol.lower()}",
        "candidate_source": "broad_observation_fixture",
    }
    if lane == "SCALP":
        row.update(
            {
                "paper_entry_horizon_style": "scalp",
                "scalp_fit_score": 85,
                "intraday_acceleration_score": 85,
                "relative_volume_score": 85,
                "spread_quality_score": 85,
                "freshness_quality_score": 85,
                "liquidity_score": 85,
            }
        )
    elif lane == "SWING":
        row.update(
            {
                "paper_entry_horizon_style": "swing_trade",
                "swing_fit_score": 85,
                "trend_persistence_score": 85,
                "trend_quality_score": 85,
                "sector": "technology",
                "market_regime": "risk_on",
            }
        )
    return row


def test_broad_observation_reaches_all_lane_evaluators_without_promotion(tmp_path: Path):
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    result = allocator.evaluate_broad_observations_v1([_observation()], max_observations=1)

    assert result["evaluations_attempted"] == {"SCALP": 1, "DAY": 1, "SWING": 1}
    assert result["eligible"] == {"SCALP": 0, "DAY": 0, "SWING": 0}
    assert result["promoted"] == {"SCALP": 0, "DAY": 0, "SWING": 0}
    assert result["observation_authority"] is False
    assert result["executable_evidence"] is False
    assert not result["promoted_rows"]


def test_missing_lane_evidence_fails_closed(tmp_path: Path):
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    result = allocator.evaluate_broad_observations_v1([_observation()], max_observations=1)

    assert result["missing_evidence"]["SCALP"]["lane_specific_features"] == 1
    assert result["missing_evidence"]["SWING"]["lane_specific_features"] == 1


def test_qualified_scalp_and_swing_evidence_can_be_promoted_independently(tmp_path: Path):
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    result = allocator.evaluate_broad_observations_v1(
        [_qualified_observation("DUAL", "SCALP"), _qualified_observation("TREND", "SWING")],
        max_observations=2,
    )

    assert result["eligible"]["SCALP"] == 1
    assert result["eligible"]["SWING"] == 1
    assert result["promoted"]["SCALP"] == 1
    assert result["promoted"]["SWING"] == 1
    assert all(row["observation_authority"] is False for row in result["promoted_rows"])
    assert all(row["executable_evidence"] is False for row in result["promoted_rows"])


def test_same_symbol_can_have_independent_lane_identities(tmp_path: Path):
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    result = allocator.evaluate_broad_observations_v1(
        [_qualified_observation("AAPL", "SCALP"), _qualified_observation("AAPL", "SWING")],
        max_observations=2,
    )
    identities = {(row["symbol"], row["lane_id"]) for row in result["promoted_rows"]}

    assert ("AAPL", "SCALP") in identities
    assert ("AAPL", "SWING") in identities


def test_candidate_intake_deduplicates_within_lane_but_preserves_other_lanes():
    engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
    engine.get_crypto_candidate_rows_fn = lambda: []
    engine.get_top_buys_fn = lambda: {
        "stocks": {
            "final": [
                _candidate("AAPL", "SCALP"),
                _candidate("AAPL", "SCALP", duplicate=True),
                _candidate("AAPL", "DAY"),
                _candidate("AAPL", "SWING"),
            ]
        }
    }
    engine.broad_universe_intake_promotion_suite = None
    engine.paper_opportunity_allocator = None
    engine.edge_development_suite = None
    engine.trade_management_portfolio_suite = None
    engine.adaptive_learning_infrastructure_suite = None
    engine.replay_lifecycle_expectancy_suite = None
    engine.regime_execution_survivability_suite = None
    engine.adaptive_execution_exit_v2_suite = None
    engine.market_calendar_knowledge_suite = None
    engine.profit_seeking_exploration_suite = None
    engine.portfolio_diversification_v2_suite = None
    engine._runtime_state = {}

    rows = engine._collect_candidate_rows()
    identities = [(row.get("symbol"), row.get("lane_id"), row.get("intended_horizon")) for row in rows]

    assert len(rows) == 3
    assert len(set(identities)) == 3
    assert {identity[1] for identity in identities} == {"SCALP", "DAY", "SWING"}
