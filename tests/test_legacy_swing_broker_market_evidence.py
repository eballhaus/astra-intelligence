import unittest
from datetime import UTC, datetime

import engine.provider_router as provider_router_module
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.astra_unified_position_lifecycle_v1 import build_legacy_swing_required_evidence_v1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.provider_router import ProviderRouter


class _MarketDataFixture:
    def __init__(self):
        self.bar_calls = []
        self.quote_calls = []
        self.asset_calls = []
        self.order_calls = 0

    def historical_bars(self, symbol, **_kwargs):
        self.bar_calls.append(symbol)
        bars = []
        for index, close in enumerate((10.0, 10.1, 10.2, 10.35, 10.5, 10.7)):
            bars.append({"t": f"2026-07-15T{14 + index:02d}:00:00Z", "o": close - 0.1, "h": close + 0.15, "l": close - 0.2, "c": close, "v": 1000 + index})
        return {"ok": True, "symbol": symbol, "response_state": "SUCCESS", "http_status": 200, "bars": bars, "broker_actions": 0}

    def latest_quote(self, symbol):
        self.quote_calls.append(symbol)
        return {"ok": True, "symbol": symbol, "response_state": "SUCCESS", "http_status": 200, "quote": {"bp": 10.68, "ap": 10.70, "t": "2026-07-16T14:00:00Z"}, "broker_actions": 0}

    def asset_metadata(self, symbol):
        self.asset_calls.append(symbol)
        return {"ok": True, "symbol": symbol, "response_state": "SUCCESS", "http_status": 200, "asset": {"symbol": symbol, "tradable": True, "fractionable": True, "shortable": True, "status": "active", "exchange": "NASDAQ", "asset_class": "us_equity"}, "broker_actions": 0}


class _MalformedBars(_MarketDataFixture):
    def historical_bars(self, symbol, **_kwargs):
        self.bar_calls.append(symbol)
        return {"ok": True, "symbol": symbol, "response_state": "SUCCESS", "http_status": 200, "bars": [{"t": "bad", "o": 10, "h": 9, "l": 11, "c": 10, "v": -1}], "broker_actions": 0}


class _EmptyBars(_MarketDataFixture):
    def historical_bars(self, symbol, **_kwargs):
        self.bar_calls.append(symbol)
        return {"ok": True, "symbol": symbol, "response_state": "EMPTY_RESPONSE", "http_status": 200, "bars": [], "broker_actions": 0}


def _fmp_success(symbol):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"provider": "FMP", "endpoint_family": "company_profile", "symbol": symbol, "requested_at": now, "response_at": now, "response_state": "SUCCESS", "records_received": 1, "records_valid": 1, "normalized_fields": {"sector": "Technology"}}


def _registry():
    return {"activation-a": {"activation_id": "activation-a", "baseline_id": "legacy-forward:asset-a", "position_id": "asset-a", "symbol": "AAA", "legacy_activation_timestamp": "2026-07-15T12:00:00Z", "activation_price": 10.0}}


def _registry_with_backlog():
    return {
        f"activation-{index}": {
            "activation_id": f"activation-{index}", "baseline_id": f"legacy-forward:asset-{index}",
            "position_id": f"asset-{index}", "symbol": f"A{index:02d}",
            "legacy_activation_timestamp": "2026-07-15T12:00:00Z", "activation_price": 10.0,
            "refresh_priority": 100,
        }
        for index in range(6)
    }


def _engine(market):
    engine = object.__new__(PaperAutopilotEngine)
    engine._runtime_state = {}
    engine._legacy_swing_market_broker = market
    engine._legacy_swing_fmp_fetcher = _fmp_success
    engine._legacy_swing_fmp_historical_fetcher = lambda *_args, **_kwargs: {"response_state": "EMPTY_RESPONSE", "bars": []}
    engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False}  # type: ignore[method-assign]
    return engine


class LegacySwingBrokerMarketEvidenceTests(unittest.TestCase):
    def test_existing_fmp_router_normalizes_hourly_historical_response(self):
        router = ProviderRouter()
        router._stock_keys["FMP"] = "test-key"
        router._temp_fmp_rest_disabled = False
        router._fmp_probe_hard_limited = lambda: False  # type: ignore[method-assign]
        router._request = lambda *_args, **_kwargs: ({"_list": [
            {"date": "2026-07-15T14:00:00Z", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}
        ]}, 200, "", 1.0)  # type: ignore[method-assign]
        original = provider_router_module._FMP_HISTORICAL_FALLBACK_ENABLED
        provider_router_module._FMP_HISTORICAL_FALLBACK_ENABLED = True
        try:
            response = router.fetch_fmp_historical_bars("AAA", limit=5)
        finally:
            provider_router_module._FMP_HISTORICAL_FALLBACK_ENABLED = original
        self.assertEqual(response["response_state"], "SUCCESS")
        self.assertEqual(response["endpoint_family"], "historical_prices")
        self.assertEqual(response["bars"][0]["timestamp"], "2026-07-15T14:00:00Z")
    def test_alpaca_empty_uses_valid_fmp_fallback_as_canonical(self):
        engine = _engine(_EmptyBars())
        calls = []
        def fallback(symbol, **_kwargs):
            calls.append(symbol)
            return {"response_state": "SUCCESS", "http_status": 200, "bars": [
                {"timestamp": f"2026-07-15T{14 + index:02d}:00:00Z", "open": close - .1, "high": close + .2, "low": close - .2, "close": close, "volume": 1000}
                for index, close in enumerate((10.0, 10.2, 10.4, 10.5, 10.7, 10.9))
            ]}
        engine._legacy_swing_fmp_historical_fetcher = fallback
        records, activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bar = records["activation-a"]["HISTORICAL_BARS"]
        self.assertEqual(calls, ["AAA"])
        self.assertEqual(bar["canonical_provider"], "FMP_HISTORICAL_PRICES")
        self.assertEqual(bar["quality_state"], "CURRENT_SUFFICIENT")
        self.assertTrue(bar["fallback_used"])
        self.assertEqual(activity["families"]["FMP_HISTORICAL_BARS"]["success_count"], 1)

    def test_material_provider_conflict_blocks_canonical_momentum(self):
        class _InsufficientBars(_MarketDataFixture):
            def historical_bars(self, symbol, **_kwargs):
                return {"response_state": "SUCCESS", "bars": [
                    {"t": f"2026-07-15T{14 + index:02d}:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10, "v": 1000}
                    for index in range(4)
                ]}
        engine = _engine(_InsufficientBars())
        engine._legacy_swing_fmp_historical_fetcher = lambda *_args, **_kwargs: {"response_state": "SUCCESS", "bars": [
            {"timestamp": f"2026-07-15T{14 + index:02d}:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for index in range(6)
        ]}
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        self.assertEqual(records["activation-a"]["HISTORICAL_BARS"]["quality_state"], "CONFLICT_BLOCKED")

    def test_fresh_alpaca_bars_do_not_invoke_fmp_fallback(self):
        engine = _engine(_MarketDataFixture())
        calls = []
        engine._legacy_swing_fmp_historical_fetcher = lambda symbol, **_kwargs: calls.append(symbol) or {"response_state": "SUCCESS", "bars": []}
        _records, activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        self.assertEqual(calls, [])
        self.assertGreaterEqual(activity["fmp_requests_avoided"], 1)

    def test_certified_daily_swing_fallback_remains_distinct_from_hourly(self):
        class _DailyFallback(_EmptyBars):
            def historical_bars(self, symbol, **kwargs):
                if kwargs.get("timeframe") == "1Day":
                    return {"response_state": "SUCCESS", "bars": [
                        {"t": f"2026-07-{10 + index:02d}T00:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10 + index * .1, "v": 1000}
                        for index in range(6)
                    ]}
                return super().historical_bars(symbol, **kwargs)
        engine = _engine(_DailyFallback())
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bar = records["activation-a"]["HISTORICAL_BARS"]
        self.assertEqual(bar["timeframe"], "1Day")
        self.assertEqual(bar["momentum_contract"], "LEGACY_SWING_DAILY")
        evidence = build_legacy_swing_required_evidence_v1({"symbol": "AAA", "broker_bar_record": bar}, _registry()["activation-a"])
        self.assertEqual(evidence["MOMENTUM"]["status"], "UNAVAILABLE")
    def test_existing_client_uses_read_only_market_routes(self):
        broker = AlpacaPaperBroker()
        broker._market_data_request = lambda path: (True, {"bars": [{"t": "2026-07-16T00:00:00Z"}]}, "", 200)  # type: ignore[method-assign]
        bars = broker.historical_bars("AAA", limit=5)
        self.assertEqual(bars["response_state"], "SUCCESS")
        broker._market_data_request = lambda path: (True, {"quote": {"bp": 10, "ap": 10.1}}, "", 200)  # type: ignore[method-assign]
        quote = broker.latest_quote("AAA")
        self.assertEqual(quote["response_state"], "SUCCESS")
        broker._request = lambda *_args, **_kwargs: (True, {"symbol": "AAA", "tradable": True}, "")  # type: ignore[method-assign]
        asset = broker.asset_metadata("AAA")
        self.assertEqual(asset["response_state"], "SUCCESS")
        self.assertEqual(bars["broker_actions"] + quote["broker_actions"] + asset["broker_actions"], 0)

    def test_existing_client_consumes_bounded_bar_pagination_with_request_lineage(self):
        broker = AlpacaPaperBroker()
        paths = []
        def request(path):
            paths.append(path)
            if "page_token=" not in path:
                return True, {"bars": [{"t": "2026-06-01T00:00:00Z"}], "next_page_token": "next"}, "", 200
            return True, {"bars": [{"t": "2026-06-02T00:00:00Z"}]}, "", 200
        broker._market_data_request = request  # type: ignore[method-assign]
        bars = broker.historical_bars("AAA", timeframe="1Day", limit=20, start="2026-06-01T00:00:00Z", end="2026-07-01T00:00:00Z")
        self.assertEqual(len(bars["bars"]), 2)
        self.assertEqual(bars["pagination_state"], "MULTI_PAGE_COMPLETE")
        self.assertEqual(bars["pages_consumed"], 2)
        self.assertIn("start=2026-06-01T00%3A00%3A00Z", paths[0])
        self.assertEqual(bars["broker_actions"], 0)

    def test_daily_fallback_uses_explicit_completed_session_contract(self):
        class _DailyHistory(_EmptyBars):
            def historical_bars(self, symbol, **kwargs):
                if kwargs.get("timeframe") != "1Day":
                    return super().historical_bars(symbol, **kwargs)
                self.bar_calls.append(symbol)
                bars = [
                    {"t": f"2026-06-{day:02d}T04:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10 + day / 100, "v": 1000}
                    for day in range(1, 25) if day not in {6, 7, 13, 14, 20, 21}
                ]
                return {"response_state": "SUCCESS", "http_status": 200, "bars": bars,
                        "requested_start": kwargs.get("start"), "requested_end": kwargs.get("end"),
                        "requested_limit": kwargs.get("limit"), "requested_feed": kwargs.get("feed"),
                        "requested_adjustment": kwargs.get("adjustment"), "requested_sort": kwargs.get("sort"),
                        "pagination_state": "PAGE_COMPLETE", "pages_consumed": 1}
        engine = _engine(_DailyHistory())
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        daily = records["activation-a"]["HISTORICAL_BARS_DAILY"]
        self.assertTrue(daily["requested_start"])
        self.assertTrue(daily["requested_end"])
        self.assertGreaterEqual(daily["requested_limit"], 15)
        self.assertGreaterEqual(daily["records_valid"], 15)
        self.assertEqual(daily["quality_state"], "CURRENT_SUFFICIENT")
        self.assertEqual(records["activation-a"]["HISTORICAL_BARS"]["momentum_contract"], "LEGACY_SWING_DAILY")

    def test_worker_normalizes_and_reuses_fresh_market_records(self):
        market = _MarketDataFixture()
        engine = _engine(market)
        records, activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bundle = records["activation-a"]
        self.assertEqual(bundle["HISTORICAL_BARS"]["activation_id"], "activation-a")
        self.assertEqual(bundle["HISTORICAL_BARS"]["position_id"], "asset-a")
        self.assertEqual(len(bundle["HISTORICAL_BARS"]["bars"]), 6)
        self.assertEqual(bundle["LATEST_QUOTE"]["freshness_state"], "CURRENT")
        self.assertTrue(bundle["ASSET_METADATA"]["tradable"])
        self.assertEqual(activity["broker_order_actions"], 0)
        engine._refresh_legacy_swing_broker_market_evidence(_registry())
        self.assertEqual(market.bar_calls, ["AAA"])
        self.assertEqual(market.quote_calls, ["AAA"])
        self.assertEqual(market.asset_calls, ["AAA"])

    def test_worker_liveness_is_local_and_does_not_require_a_broker_status_read(self):
        engine = _engine(_MarketDataFixture())
        engine._thread = None
        engine.interval_seconds = 45
        engine._enabled = True
        engine._runtime_state.update({
            "worker_generation_id": "paper-autopilot:test",
            "worker_heartbeat_at": "2026-07-17T12:00:00Z",
            "worker_cycle_started_at": "2026-07-17T12:00:00Z",
            "worker_cycle_completed_at": "2026-07-17T11:59:00Z",
            "worker_cycle_phase": "market_data:HISTORICAL_BARS:AAA",
            "worker_cycle_count": 3,
            "last_cycle_utc": "2026-07-17T11:59:00Z",
        })
        liveness = engine.worker_liveness_status()
        self.assertFalse(liveness["running"])
        self.assertEqual(liveness["worker_cycle_phase"], "market_data:HISTORICAL_BARS:AAA")
        self.assertEqual(liveness["worker_cycle_count"], 3)
        self.assertEqual(liveness["interval_seconds"], 45)

    def test_nested_canary_market_records_survive_worker_restart(self):
        market = _MarketDataFixture()
        first = _engine(market)
        records, _activity = first._refresh_legacy_swing_broker_market_evidence(_registry())
        restarted = _engine(market)
        restarted._runtime_state["legacy_swing_canary"] = {"market_records": records, "market_activity": first._runtime_state["legacy_swing_market_activity"]}
        restored, _activity = restarted._refresh_legacy_swing_broker_market_evidence(_registry())
        self.assertIn("activation-a", restored)
        self.assertEqual(market.bar_calls, ["AAA"])

    def test_malformed_bars_fail_closed_without_overwriting_evidence(self):
        market = _MalformedBars()
        engine = _engine(market)
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        record = records["activation-a"]["HISTORICAL_BARS"]
        self.assertEqual(record["response_state"], "MALFORMED_RESPONSE")
        self.assertEqual(record["records_stored"], 0)
        self.assertEqual(record["freshness_state"], "UNAVAILABLE")

    def test_empty_refresh_preserves_prior_sufficient_bars_as_stale(self):
        market = _MarketDataFixture()
        engine = _engine(market)
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        prior = records["activation-a"]["HISTORICAL_BARS"]
        prior["received_at"] = "2026-07-01T00:00:00Z"
        prior["freshness_state"] = "CURRENT"
        prior["quality_state"] = "CURRENT_SUFFICIENT"
        engine._runtime_state["legacy_swing_market_evidence"] = records
        engine._legacy_swing_market_broker = _EmptyBars()
        restored, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bar = restored["activation-a"]["HISTORICAL_BARS"]
        self.assertEqual(bar["response_state"], "SUCCESS")
        self.assertEqual(bar["freshness_state"], "STALE")
        self.assertEqual(bar["quality_state"], "STALE_SUFFICIENT")
        self.assertEqual(len(bar["bars"]), 6)
        self.assertEqual(bar["replacement_reason"], "LOWER_QUALITY_REJECTED_PRESERVED_PRIOR")

    def test_empty_broker_response_is_external_empty_not_invalid_bar_data(self):
        engine = _engine(_EmptyBars())
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bar = records["activation-a"]["HISTORICAL_BARS"]
        self.assertEqual(bar["response_state"], "EMPTY_RESPONSE")
        self.assertEqual(bar["quality_state"], "EMPTY")
        self.assertEqual(bar["source_error"], "empty_response")

    def test_round_robin_persists_and_eventually_reaches_later_symbols(self):
        market = _EmptyBars()
        engine = _engine(market)
        registry = _registry_with_backlog()
        _records, first = engine._refresh_legacy_swing_broker_market_evidence(registry)
        self.assertEqual(len(first["symbols_requested"]), 3)
        engine._runtime_state["legacy_swing_market_activity"] = first
        _records, second = engine._refresh_legacy_swing_broker_market_evidence(registry)
        self.assertEqual(len(second["symbols_requested"]), 3)
        self.assertEqual(len(set(first["symbols_requested"] + second["symbols_requested"])), 6)
        self.assertNotEqual(first["next_symbol_cursor"], second["next_symbol_cursor"])
        self.assertEqual(second["scheduler"]["worker_generation_id"].split(":")[0], "paper-autopilot")

    def test_insufficient_bar_context_cannot_fallback_to_current_momentum(self):
        evidence = build_legacy_swing_required_evidence_v1(
            {
                "symbol": "AAA", "current_price": 10.5, "recent_price_path": [10.0],
                "broker_bar_record": {
                    "response_state": "SUCCESS", "freshness_state": "CURRENT", "quality_state": "CURRENT_INSUFFICIENT",
                    "bars": [{"close": 10.0, "volume": 1000}],
                },
            },
            _registry()["activation-a"],
        )
        self.assertEqual(evidence["MOMENTUM"]["status"], "UNAVAILABLE")

    def test_canonical_records_produce_current_momentum_and_liquidity(self):
        market = _MarketDataFixture()
        engine = _engine(market)
        records, _activity = engine._refresh_legacy_swing_broker_market_evidence(_registry())
        bundle = records["activation-a"]
        evidence = build_legacy_swing_required_evidence_v1({"symbol": "AAA", "broker_bar_record": bundle["HISTORICAL_BARS"], "broker_quote_record": bundle["LATEST_QUOTE"], "broker_asset_record": bundle["ASSET_METADATA"]}, _registry()["activation-a"])
        self.assertEqual(evidence["MOMENTUM"]["status"], "CURRENT")
        self.assertEqual(evidence["LIQUIDITY"]["status"], "CURRENT")
        self.assertEqual(evidence["LIQUIDITY"]["liquidity_state"], "ACCEPTABLE")

    def test_worker_persists_acknowledgement_and_influence_without_orders(self):
        market = _MarketDataFixture()
        engine = _engine(market)
        engine._runtime_state["legacy_forward_activations"] = _registry()
        result = engine._refresh_legacy_swing_canary_pre_submit({"AAA": {"symbol": "AAA", "asset_id": "asset-a", "qty": 2, "qty_available": 2, "market_value": 21.4, "current_price": 10.7, "unrealized_plpc": 0}})
        bundle = engine._runtime_state["legacy_swing_market_evidence"]["activation-a"]
        self.assertTrue(bundle["HISTORICAL_BARS"]["consumer_acknowledged"])
        self.assertTrue(bundle["LATEST_QUOTE"]["consumer_acknowledged"])
        self.assertTrue(bundle["ASSET_METADATA"]["consumer_acknowledged"])
        self.assertIn(bundle["HISTORICAL_BARS"]["influence_state"], {"NEUTRAL", "BLOCKING"})
        self.assertEqual(result["broker_actions"], 0)
        self.assertEqual(market.order_calls, 0)


if __name__ == "__main__":
    unittest.main()
