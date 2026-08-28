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
