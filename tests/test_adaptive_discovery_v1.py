"""Focused safety contracts for bounded real-evidence discovery."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import UTC, datetime, timedelta

from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1
from engine.paper_autopilot import _paper_selection_priority
from engine.provider_router import ProviderRouter
from engine.paper_autopilot_worker import PaperAutopilotWorker


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


class _FakeBroadRouter(_FakeDiscoveryRouter):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot_batches: list[list[str]] = []

    def fetch_alpaca_tradable_equity_assets(self) -> dict:
        return {
            "ok": True,
            "rows": [
                {"symbol": "AAPL", "status": "active", "tradable": True},
                {"symbol": "MSFT", "status": "active", "tradable": True},
                {"symbol": "OLD", "status": "inactive", "tradable": False},
            ],
        }

    def fetch_alpaca_stock_snapshots(self, symbols, *, feed="sip", batch_size=100) -> dict:
        names = list(symbols)
        self.snapshot_batches.extend(names[index:index + batch_size] for index in range(0, len(names), batch_size))
        rows = []
        now = datetime.now(UTC).replace(microsecond=0)
        quote_time = now.isoformat().replace("+00:00", "Z")
        trade_time = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        bar_time = (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        for symbol in names:
            rows.append({
                "symbol": symbol,
                "snapshot": {
                    "latestQuote": {"t": quote_time, "bp": 99.9, "ap": 100.1},
                    "latestTrade": {"t": trade_time, "p": 100.0, "s": 10},
                    "minuteBar": {"t": bar_time, "o": 99.0, "h": 101.0, "l": 98.5, "c": 100.0, "v": 5000},
                    "prevDailyBar": {"c": 98.0},
                },
            })
        return {
            "ok": True,
            "rows": rows,
            "provider_calls": len(self.snapshot_batches),
            "batches": len(self.snapshot_batches),
            "response_bytes": len(rows) * 100,
            "errors": [],
        }


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


def test_alpaca_inventory_extends_cached_universe_without_inactive_symbols() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        router = _FakeBroadRouter()
        owner._provider_router = router
        symbols = owner.inventory_symbols()
        assert "AAPL" in symbols and "MSFT" in symbols
        assert "OLD" not in symbols


def test_broad_snapshots_are_batched_normalized_and_published_as_observation_only() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        router = _FakeBroadRouter()
        owner._provider_router = router
        owner._refresh_alpaca_universe = lambda cached, now: {}
        published: list[dict] = []
        owner.set_observation_publisher(lambda rows: published.extend(rows))
        def symbol_for(index: int) -> str:
            value = index
            chars = []
            while value:
                chars.append(chr(65 + (value % 26)))
                value //= 26
            return "A" + "".join(reversed(chars or ["A"]))

        symbols = [symbol_for(i) for i in range(251)]
        owner._refresh_broad_observations(symbols)
        assert len(router.snapshot_batches) == 3
        assert [len(batch) for batch in router.snapshot_batches] == [100, 100, 51]
        rows = owner.current_broad_observation_rows()
        assert len(rows) == 251
        assert len(published) == 251
        assert rows[0]["provider"] == "ALPACA_SIP_BROAD_SNAPSHOT"
        assert rows[0]["observation_role"] == "BROAD_DISCOVERY_TIER0"
        assert rows[0]["observation_authority"] is False
        assert rows[0]["executable_evidence"] is False
        assert rows[0]["bid"] == 99.9
        assert rows[0]["volume"] == 5000.0


def test_broad_observation_refresh_is_worker_only_and_asynchronous(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("ASTRA_PROCESS_ROLE", "worker")
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        owner._provider_router = _FakeBroadRouter()
        result = owner.schedule_broad_observation_refresh(["AAPL", "MSFT"])
        assert result["scheduled"] is True
        thread = owner._observation_thread
        assert thread is not None
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert owner._observation_status["status"] == "CURRENT"
        assert owner.schedule_broad_observation_refresh(["AAPL"]) ["status"] in {"COOLDOWN", "RUNNING"}


def test_broad_observation_scheduler_does_not_run_in_api_process(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("ASTRA_PROCESS_ROLE", "api")
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.schedule_broad_observation_refresh(["AAPL"])
        assert result == {"status": "NOT_WORKER", "scheduled": False}


def test_priority_tiers_are_bounded_discovery_only_and_deterministic() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        rows = [
            {
                "symbol": f"T{chr(65 + index)}",
                "change_percent": float(index),
                "volume": 1_000_000 + index,
                "bid": 99.9,
                "ask": 100.1,
                "quote_age_seconds": 5.0,
                "provider_native_timestamp": "2026-09-17T14:30:00Z",
                "freshness_state": "CURRENT",
                "provider_provenance": "ALPACA_SIP_BATCH_SNAPSHOT",
            }
            for index in range(20)
        ]
        first = owner.build_priority_tiers_v2(rows, now_timestamp=1_800_000_000.0)
        second = owner.build_priority_tiers_v2(rows, now_timestamp=1_800_000_000.0)
        assert first["tier_counts"] == {"NEAR_ENTRY": 0, "HOT": 1, "WARM": 3, "COLD": 16}
        assert second["tier_counts"] == first["tier_counts"]
        saved = (Path(directory) / "lane_aware_discovery_v1.json").read_text(encoding="utf-8")
        assert '"priority_tier_discovery_only": true' in saved
        assert '"observation_authority": false' in saved
        assert first["broker_actions_added"] == 0


def test_priority_refresh_plan_adapts_capacity_and_prioritizes_existing_tiers() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        owner.build_priority_tiers_v2(
            [
                {
                    "symbol": "HOT",
                    "change_percent": 10.0,
                    "volume": 10_000_000,
                    "bid": 99.9,
                    "ask": 100.1,
                    "quote_age_seconds": 5.0,
                    "provider_native_timestamp": "2026-09-17T14:30:00Z",
                    "freshness_state": "CURRENT",
                },
                {
                    "symbol": "COLD",
                    "change_percent": 0.1,
                    "volume": 100_000,
                    "bid": 99.0,
                    "ask": 101.0,
                    "quote_age_seconds": 5.0,
                    "provider_native_timestamp": "2026-09-17T14:30:00Z",
                    "freshness_state": "CURRENT",
                },
            ],
            now_timestamp=1_800_000_000.0,
        )
        def alpha_symbol(index: int) -> str:
            chars = []
            value = index
            while True:
                chars.append(chr(65 + (value % 26)))
                value = value // 26 - 1
                if value < 0:
                    break
            return "S" + "".join(reversed(chars))

        symbols = ["COLD", "HOT"] + [alpha_symbol(index) for index in range(1_401)]
        normal = owner._priority_refresh_plan(symbols, resource_state="RESOURCE_NORMAL")
        elevated = owner._priority_refresh_plan(symbols, resource_state="RESOURCE_ELEVATED")
        assert normal["symbols"][0] == "HOT"
        assert normal["priority_refresh_capacity"] == 1_300
        assert 300 <= elevated["priority_refresh_capacity"] < normal["priority_refresh_capacity"]
        assert elevated["symbols_deferred"] > 0


def test_priority_controller_uses_hysteresis_and_coverage_pressure() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        symbols = [f"S{chr(65 + (index // 26))}{chr(65 + (index % 26))}" for index in range(1_400)]
        first = owner._priority_refresh_plan(symbols, resource_state="RESOURCE_NORMAL", cycle_elapsed_seconds=10.0)
        outlier = owner._priority_refresh_plan(symbols, resource_state="RESOURCE_NORMAL", cycle_elapsed_seconds=31.0)
        assert first["priority_refresh_capacity"] == 1_200
        assert outlier["priority_refresh_capacity"] == 1_200
        assert outlier["controller_reason"] == "hysteresis_hold"

        path = Path(directory) / "lane_aware_discovery_v1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["priority_controller_v1"] = {
            "throughput_target": 1_200,
            "cycle_history_seconds": [10.0, 10.0, 10.0, 10.0],
        }
        payload["priority_tier_age_stats_seconds"] = {"COLD": {"p95": 1_000.0, "max": 1_200.0}}
        path.write_text(json.dumps(payload), encoding="utf-8")
        expanded = owner._priority_refresh_plan(symbols, resource_state="RESOURCE_NORMAL", cycle_elapsed_seconds=10.0)
        assert expanded["priority_refresh_capacity"] == 1_300
        assert expanded["controller_reason"] == "coverage_age_pressure_with_cycle_headroom"


def test_cold_catch_up_prioritizes_age_without_promoting_tier() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        now = datetime.now(UTC)
        old = (now - timedelta(seconds=1_000)).isoformat().replace("+00:00", "Z")
        fresh = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        rows = [
            {"symbol": "OLD", "change_percent": 0.1, "volume": 100, "bid": 99.0, "ask": 101.0, "quote_age_seconds": 5, "provider_native_timestamp": old, "freshness_state": "CURRENT"},
            {"symbol": "NEW", "change_percent": 0.2, "volume": 100, "bid": 99.0, "ask": 101.0, "quote_age_seconds": 5, "provider_native_timestamp": fresh, "freshness_state": "CURRENT"},
        ]
        result = owner.build_priority_tiers_v2(rows)
        records = {row["symbol"]: row for row in json.loads((Path(directory) / "lane_aware_discovery_v1.json").read_text())["priority_tiers"]}
        assert records["OLD"]["tier"] == "COLD"
        assert result["cold_catch_up_queue_size"] == 1
        plan = owner._priority_refresh_plan(["NEW", "OLD"], resource_state="RESOURCE_NORMAL")
        assert plan["symbols"][0] == "OLD"


def test_worker_cycle_timing_rollup_is_bounded_and_reports_slow_stage() -> None:
    worker = PaperAutopilotWorker.__new__(PaperAutopilotWorker)
    worker.autopilot = type("Autopilot", (), {"_runtime_state": {
        "worker_phase_timing_v1": {"durations_seconds": {"candidate_collection": 2.0, "broker_position_snapshot": 1.0}},
        "worker_open_review_timing_v1": {"durations_seconds": {"exit_evaluation": 4.0, "exit_submission": 1.0}},
    }})()
    worker._cycle_timing_history = []
    worker._cycle_state_write_samples = [0.2]
    metrics = worker._record_cycle_timing_v1(16.0, 0.5)
    assert metrics["rolling_median_seconds"] == 16.0
    assert metrics["rolling_p90_seconds"] == 16.0
    assert metrics["recent_max_seconds"] == 16.0
    assert metrics["cycles_over_15_seconds"] == 1
    assert metrics["largest_stage_on_slow_cycles"] == "active_position_management"


def test_provider_router_uses_multi_symbol_alpaca_snapshot_batches(monkeypatch) -> None:
    router = ProviderRouter()
    calls: list[dict] = []
    monkeypatch.setattr(router, "_key_for", lambda _provider, _asset_type: "key")

    def request(provider, url, *, params=None, headers=None):
        calls.append({"provider": provider, "url": url, "params": dict(params or {})})
        return ({symbol: {"latestTrade": {"p": 100.0}} for symbol in str(params["symbols"]).split(",")}, 200, "", 1.0)

    monkeypatch.setattr(router, "_request", request)
    monkeypatch.setattr(router, "_request_bytes", lambda *args, **kwargs: 0)
    symbols = [f"B{chr(65 + (i // 26))}{chr(65 + (i % 26))}" for i in range(205)]
    result = router.fetch_alpaca_stock_snapshots(symbols, batch_size=100)
    assert result["batches"] == 3
    assert result["provider_calls"] == 3
    assert [len(call["params"]["symbols"].split(",")) for call in calls] == [100, 100, 5]


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
        assert result["eligible_count"] == {"SCALP": 1, "DAY": 1, "SWING": 1}
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
        assert result["eligible_count"]["SCALP"] == 200
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
