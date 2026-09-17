"""Focused safety contracts for bounded real-evidence discovery."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1
from engine.paper_autopilot import _paper_selection_priority


class _FakeDiscoveryRouter:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_fmp_bounded_discovery(self, *, mode: str, limit: int) -> dict:
        self.calls.append(mode)
        if mode == "company_screener":
            rows = [
                {"symbol": "AAPL", "isActivelyTrading": True, "isEtf": False, "isFund": False, "marketCap": 3_000_000_000, "price": 100.0, "volume": 2_000_000},
                {"symbol": "SPY", "isActivelyTrading": True, "isEtf": True, "isFund": False, "marketCap": 3_000_000_000, "price": 500.0, "volume": 2_000_000},
                {"symbol": "ONDO-USD", "isActivelyTrading": True, "isEtf": False, "isFund": False, "marketCap": 3_000_000_000, "price": 10.0, "volume": 2_000_000},
                {"symbol": "THIN", "isActivelyTrading": True, "isEtf": False, "isFund": False, "marketCap": 3_000_000_000, "price": 10.0, "volume": 10},
                {"symbol": "SHOP.TO", "exchange": "TSX", "isActivelyTrading": True, "isEtf": False, "isFund": False, "marketCap": 3_000_000_000, "price": 80.0, "volume": 2_000_000},
                {"symbol": "LEVG", "name": "Leveraged ETF", "isActivelyTrading": True, "isEtf": False, "isFund": False, "marketCap": 3_000_000_000, "price": 80.0, "volume": 2_000_000},
            ]
        elif mode == "biggest_gainers":
            rows = [{"symbol": "NVDA", "changesPercentage": "4.0%", "volume": 3_000_000}]
        else:
            rows = [{"symbol": "MSFT", "changesPercentage": 1.0, "volume": 9_000_000}]
        return {"ok": True, "rows": rows, "status": 200, "response_bytes": 128, "provider": "FMP"}


def test_inventory_does_not_inject_synthetic_candidates() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        original = [{"symbol": "AAPL", "price": 200.0, "provider_quote_timestamp": "2026-08-27T14:00:00Z"}]
        assert owner.decorate_candidates(original) == original


def test_rotation_is_bounded_and_preserves_exploration(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("ASTRA_DISCOVERY_ROTATION_SIZE", "24")
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        inventory = [f"A{chr(65 + (i // 26))}{chr(65 + (i % 26))}" for i in range(40)]
        known = [
            {"symbol": "AAA", "confidence": 90.0, "quote_age_seconds": 10.0},
            {"symbol": "AAB", "confidence": 80.0, "quote_age_seconds": 10.0},
        ]
        result = owner.select_rotation(known_rows=known, inventory_symbols=inventory)
        symbols = result["symbols"]
        status = result["status"]
        assert len(symbols) == 24
        assert len(set(symbols)) == 24
        assert symbols[:2] == ["AAA", "AAB"]
        assert status["exploration_count"] > 0
        assert status["candidate_evidence_fabricated"] is False


def test_known_duplicate_is_pruned_before_rotation() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.select_rotation(
            inventory_symbols=["AAPL", "MSFT", "NVDA"],
            excluded_symbols=["MSFT"],
        )
        assert "MSFT" not in result["symbols"]
        assert result["status"]["excluded_duplicate_or_active_symbols"] == 1


def test_crypto_pair_is_not_an_equity_discovery_symbol() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.select_rotation(inventory_symbols=["AAPL", "ONDO-USD", "ETH-USD"])
        assert result["symbols"] == ["AAPL"]


def test_prospective_marker_is_write_once() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        first = owner.select_rotation(inventory_symbols=["AAPL"])["status"]["prospective_cohort"]
        second = owner.select_rotation(inventory_symbols=["MSFT"])["status"]["prospective_cohort"]
        assert first == second
        assert (Path(directory) / "adaptive_discovery_v1.json").exists()


def test_authoritative_fmp_universe_keeps_only_liquid_common_stocks() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        router = _FakeDiscoveryRouter()
        owner._provider_router = router
        assert owner.inventory_symbols() == ["AAPL"]
        assert router.calls == ["company_screener"]


def test_market_indexes_prioritize_real_mover_without_creating_candidate_evidence(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("ASTRA_DISCOVERY_ROTATION_SIZE", "8")
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        router = _FakeDiscoveryRouter()
        owner._provider_router = router
        market = owner.refresh_market_discovery()
        result = owner.select_rotation(
            inventory_symbols=["AAPL", "MSFT", "NVDA", "AMD", "META", "GOOG", "AMZN", "TSLA", "AVGO"],
            market_rows=market["rows"],
        )
        assert result["symbols"][0] == "NVDA"
        assert result["source_by_symbol"]["NVDA"] == "fmp_biggest_gainers"
        assert market["executable_evidence"] is False
        assert all(row["discovery_evidence_only"] is True for row in market["rows"])


def test_existing_allocation_score_prefers_stronger_candidate_independent_of_source_order() -> None:
    weaker = {"symbol": "AAA", "paper_allocation_priority": 61.0, "risk_adjusted_profit_score": 65.0}
    stronger = {"symbol": "ZZZ", "paper_allocation_priority": 82.0, "risk_adjusted_profit_score": 78.0}
    assert sorted([weaker, stronger], key=_paper_selection_priority, reverse=True)[0]["symbol"] == "ZZZ"


def _lane_evidence(symbol: str, lane: str, score: float, rank: int) -> dict:
    return {
        "symbol": symbol,
        "lane_ranked_entry_lane": lane,
        "lane_ranked_entry_funnel_v1": True,
        "lane_shortlist_rank": rank,
        "lane_ranked_entry_score": score,
        "qualified": True,
        "candidate_freshness_status": "FRESH",
        "candidate_source": "paper_opportunity_allocation_engine_v1",
    }


def test_lane_hot_lists_use_existing_current_evidence_and_preserve_multi_lane_identity() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.build_lane_aware_discovery_v1(
            [
                _lane_evidence("AAPL", "SCALP", 88.0, 1),
                _lane_evidence("AAPL", "SCALP", 87.0, 3),
                _lane_evidence("AAPL", "DAY", 82.0, 2),
                _lane_evidence("MSFT", "SWING", 79.0, 1),
                {"symbol": "NVDA", "lane": "DAY", "qualified": True, "lane_ranked_entry_score": 99.0},
            ],
            master_universe_size=474,
            rotation_size=24,
            now_timestamp=1_800_000_000.0,
        )
        assert [row["symbol"] for row in result["hot_lists"]["SCALP"]] == ["AAPL"]
        assert [row["symbol"] for row in result["hot_lists"]["DAY"]] == ["AAPL"]
        assert [row["symbol"] for row in result["hot_lists"]["SWING"]] == ["MSFT"]
        assert result["total_count"] == 3
        assert result["multiple_lane_symbol_count"] == 1
        assert result["symbols_scheduled_for_tier0"] == 24
        assert result["symbols_scanned_this_cycle"] == 0
        assert result["candidate_evidence_fabricated"] is False


def test_lane_hot_lists_reject_stale_or_unresolved_rows_without_inventory_promotion() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.build_lane_aware_discovery_v1(
            [
                {**_lane_evidence("STALE", "SCALP", 99.0, 1), "candidate_freshness_status": "STALE"},
                {"symbol": "AAPL", "lane": "DAY", "qualified": True, "lane_ranked_entry_score": 90.0},
            ],
            master_universe_size=474,
            rotation_size=24,
        )
        assert result["total_count"] == 0
        assert result["hot_lists"] == {"SCALP": [], "DAY": [], "SWING": []}
        assert result["rejected_rows"]["not_current_qualified_lane_evidence"] == 2


def test_lane_hot_lists_are_bounded_and_resource_aware() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        rows = [
            _lane_evidence(f"A{chr(65 + i // 26)}{chr(65 + i % 26)}", "SCALP", 100.0 - i, i + 1)
            for i in range(200)
        ]
        result = owner.build_lane_aware_discovery_v1(
            rows,
            resource_state="RESOURCE_ELEVATED",
            cycle_elapsed_seconds=19.0,
        )
        assert len(result["hot_lists"]["SCALP"]) == 37  # elevated mode reduces the 150-symbol cap to 37
        assert result["deep_analysis_target"]["SCALP"] == 20
        assert result["resource_capacity"]["discovery_capacity_factor"] == 0.25
        assert all(row["execution_authority"] is False for row in result["hot_lists"]["SCALP"])


def test_lane_hot_list_refresh_preserves_first_seen_and_selection_window() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        first = owner.build_lane_aware_discovery_v1(
            [_lane_evidence("AAPL", "DAY", 80.0, 1)], now_timestamp=1_800_000_000.0
        )
        second = owner.build_lane_aware_discovery_v1(
            [_lane_evidence("AAPL", "DAY", 85.0, 1)], now_timestamp=1_800_000_120.0
        )
        first_row = first["hot_lists"]["DAY"][0]
        second_row = second["hot_lists"]["DAY"][0]
        assert second_row["first_seen"] == first_row["first_seen"]
        assert second_row["selected_at"] == first_row["selected_at"]
        assert second_row["material_score_change"] == 5.0


def test_lane_hot_list_never_creates_execution_or_broker_activity() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.build_lane_aware_discovery_v1(
            [_lane_evidence("AAPL", "SCALP", 80.0, 1)]
        )
        assert result["broker_actions_added"] == 0
        assert result["trading_policy_changed"] is False
        assert all(row["discovery_only"] for row in result["hot_lists"]["SCALP"])
