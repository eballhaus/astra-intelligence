import unittest
from datetime import UTC, datetime

from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.astra_unified_position_lifecycle_v1 import build_legacy_swing_required_evidence_v1
from engine.paper_autopilot import PaperAutopilotEngine


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
            bars.append({"t": f"2026-07-{10 + index:02d}T20:00:00Z", "o": close - 0.1, "h": close + 0.15, "l": close - 0.2, "c": close, "v": 1000 + index})
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


def _fmp_success(symbol):
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"provider": "FMP", "endpoint_family": "company_profile", "symbol": symbol, "requested_at": now, "response_at": now, "response_state": "SUCCESS", "records_received": 1, "records_valid": 1, "normalized_fields": {"sector": "Technology"}}


def _registry():
    return {"activation-a": {"activation_id": "activation-a", "baseline_id": "legacy-forward:asset-a", "position_id": "asset-a", "symbol": "AAA", "legacy_activation_timestamp": "2026-07-15T12:00:00Z", "activation_price": 10.0}}


def _engine(market):
    engine = object.__new__(PaperAutopilotEngine)
    engine._runtime_state = {}
    engine._legacy_swing_market_broker = market
    engine._legacy_swing_fmp_fetcher = _fmp_success
    engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False}  # type: ignore[method-assign]
    return engine


class LegacySwingBrokerMarketEvidenceTests(unittest.TestCase):
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
