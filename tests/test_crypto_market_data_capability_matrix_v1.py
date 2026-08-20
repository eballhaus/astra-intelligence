from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from engine.astra_crypto_market_data_capability_matrix_v1 import CryptoMarketDataCapabilityMatrixV1
from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.provider_router import ProviderRouter, canonical_crypto_market_symbol_v1


class CryptoMarketDataCapabilityMatrixTests(unittest.TestCase):
    def _matrix(self, rows):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        matrix = CryptoMarketDataCapabilityMatrixV1(temp.name)
        return matrix, matrix.build(
            capability={"supported_pairs": ["BTC/USD", "ETH/USD"], "tradable_pairs": ["BTC/USD", "ETH/USD"]},
            ranking_snapshot={"generated_at": "2026-07-19T00:00:00Z", "crypto_discovery_universe": ["BTC/USD", "ETH/USD"], "crypto_quote_integrity_rows": rows},
        )

    def test_symbol_normalization_is_deterministic(self):
        for raw in ("BTC/USD", "BTCUSD", "BTC-USD", "BTC_USD"):
            identity = canonical_crypto_market_symbol_v1(raw)
            self.assertEqual(identity["internal_pair"], "BTC/USD")
            self.assertEqual(identity["provider_request_symbol"], "BTC/USD")
            self.assertEqual(identity["provider_response_compact_key"], "BTCUSD")

    def test_response_key_and_bid_ask_survive_provider_normalization(self):
        router = ProviderRouter(); router._crypto_keys["ALPACA"] = "key"; router._effective_provider_order = lambda *_args, **_kwargs: ["ALPACA"]
        with patch.dict(os.environ, {"APCA_API_SECRET_KEY": "secret"}), patch.object(router, "_request", return_value=({"quotes": {"BTCUSD": {"bp": 10.0, "ap": 10.1, "t": "2026-07-19T00:00:00Z", "i": "q1"}}}, 200, "", 1.0)):
            quote = router.get_quote("BTC/USD", asset_type="crypto", bypass_cache=True)
        self.assertEqual(quote["bid"], 10.0)
        self.assertEqual(quote["ask"], 10.1)
        self.assertEqual(quote["provider_diagnostics"]["response_key"], "BTCUSD")
        self.assertEqual(quote["quote_timestamp"], "2026-07-19T00:00:00Z")
        self.assertGreater(quote["quote_age_seconds"], 0.0)

    def test_trade_price_is_not_substituted_for_bid_or_ask(self):
        router = ProviderRouter()
        payload = router._normalize_quote_payload(symbol="BTC/USD", provider="ALPACA", price=10.0, prev_close=None, attempted=["ALPACA"], cache_hit=False, quote_quality="live", quote_age_seconds=0.0, data_unavailable_reason=None, quote_timestamp="2026-07-19T00:00:00Z")
        self.assertIsNone(payload["bid"])
        self.assertIsNone(payload["ask"])

    def test_provider_adapter_exception_does_not_abort_crypto_fallbacks(self):
        router = ProviderRouter()
        router._effective_provider_order = lambda *_args, **_kwargs: ["BROKEN", "ALPACA"]
        router._provider_active = lambda *_args, **_kwargs: True
        valid_alpaca_quote = {
            "ok": True, "price": 10.1, "prev_close": 10.0, "bid": 10.0, "ask": 10.1,
            "quote_timestamp": "2026-07-19T00:00:00Z", "quote_source": "ALPACA_MARKET_DATA",
            "endpoint": "/v1beta3/crypto/us/latest/quotes", "request_symbol": "BTC/USD",
        }
        with patch.object(router, "_fetch_quote_from_provider", side_effect=[RuntimeError("adapter defect"), valid_alpaca_quote]):
            quote = router.get_quote("BTC/USD", asset_type="crypto", bypass_cache=True)
        self.assertEqual(quote["provider_used"], "alpaca")
        self.assertEqual(quote["bid"], 10.0)
        self.assertEqual(quote["provider_diagnostics"]["failed_probes"][0]["error"], "provider_adapter_exception:RuntimeError")

    def test_matrix_distinguishes_tradable_from_quote_observable(self):
        _, payload = self._matrix([{"symbol": "BTC/USD", "quote_received": False, "failure_reason": "FRESH_QUOTE_UNAVAILABLE"}])
        btc = next(row for row in payload["pairs"] if row["symbol"] == "BTC/USD")
        self.assertTrue(btc["broker_tradable"])
        self.assertFalse(btc["latest_quote_observable"])
        self.assertFalse(btc["execution_readiness_eligible"])

    def test_empty_auth_entitlement_and_rate_limit_are_classified(self):
        cases = [(401, "PROVIDER_AUTHENTICATION_FAILURE"), (403, "PROVIDER_ENTITLEMENT_LIMITATION"), (429, "PROVIDER_RATE_LIMIT")]
        for status, expected in cases:
            _, payload = self._matrix([{"symbol": "BTC/USD", "quote_received": False, "provider_diagnostics": {"failed_probes": [{"http_status": status, "error": "http"}]}}])
            self.assertEqual(payload["pairs"][0]["failure_classification"], expected)
        _, empty = self._matrix([{"symbol": "BTC/USD", "quote_received": False, "provider_diagnostics": {"failed_probes": [{"empty_response": True}]}}])
        self.assertEqual(empty["pairs"][0]["failure_classification"], "PROVIDER_EMPTY_RESPONSE")

    def test_timestamp_volume_and_spread_are_independent(self):
        _, payload = self._matrix([{"symbol": "BTC/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1, "bid_present": True, "ask_present": True, "spread_present": True, "quote_timestamp": "2026-07-19T00:00:00Z", "quote_observed_at": "2026-07-19T00:00:01Z", "snapshot_generated_at": "2026-07-19T00:00:02Z", "bars_available": True, "volume_available": True, "candidate_persisted": True}])
        btc = payload["pairs"][0]
        self.assertEqual(btc["last_quote_timestamp"], "2026-07-19T00:00:00Z")
        self.assertTrue(btc["spread_eligible"])
        self.assertTrue(btc["completed_volume_observable"])
        self.assertTrue(btc["data_quality_ready"])

    def test_completed_bar_timestamp_is_preserved_without_a_false_bar_failure_streak(self):
        timestamp = "2026-07-19T00:00:00Z"
        _, payload = self._matrix([{
            "symbol": "BTC/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1,
            "bid_present": True, "ask_present": True, "spread_present": True, "quote_timestamp": timestamp,
            "bar_timestamp": timestamp, "bars_available": True, "volume_available": True, "candidate_persisted": True,
        }])
        btc = payload["pairs"][0]
        self.assertEqual(btc["last_completed_bar_timestamp"], timestamp)
        self.assertEqual(btc["last_bar_success_at"], timestamp)
        self.assertTrue(btc["completed_bar_observable"])
        self.assertEqual(btc["bar_failure_streak"], 0)

    def test_missing_completed_bar_timestamp_remains_fail_closed(self):
        _, payload = self._matrix([{
            "symbol": "BTC/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1,
            "bid_present": True, "ask_present": True, "spread_present": True, "bars_available": True,
            "volume_available": False, "candidate_persisted": False,
        }])
        btc = payload["pairs"][0]
        self.assertFalse(btc["completed_bar_observable"])
        self.assertGreaterEqual(btc["bar_failure_streak"], 1)
        self.assertFalse(btc["liquidity_eligible"])

    def test_missing_volume_and_repeated_unobservable_are_fail_closed_and_bounded(self):
        matrix, first = self._matrix([{"symbol": "BTC/USD", "quote_received": False}])
        matrix.write(first)
        second = matrix.build(capability={"supported_pairs": ["BTC/USD"], "tradable_pairs": ["BTC/USD"]}, ranking_snapshot={"crypto_discovery_universe": ["BTC/USD"], "crypto_quote_integrity_rows": [{"symbol": "BTC/USD", "quote_received": False}]})
        third = matrix.build(capability={"supported_pairs": ["BTC/USD"], "tradable_pairs": ["BTC/USD"]}, ranking_snapshot={"crypto_discovery_universe": ["BTC/USD"], "crypto_quote_integrity_rows": [{"symbol": "BTC/USD", "quote_received": False}]})
        self.assertLessEqual(len(third["pairs"]), 30)
        self.assertFalse(third["pairs"][0]["liquidity_eligible"])
        self.assertGreaterEqual(second["pairs"][0]["quote_failure_streak"], 2)

    def test_last_successful_observation_survives_rotation_without_becoming_fresh(self):
        matrix, first = self._matrix([{"symbol": "BTC/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1, "bid_present": True, "ask_present": True, "spread_present": True, "quote_timestamp": "2026-07-19T00:00:00Z"}])
        matrix.write(first)
        second = matrix.build(capability={"supported_pairs": ["BTC/USD"], "tradable_pairs": ["BTC/USD"]}, ranking_snapshot={"crypto_discovery_universe": ["BTC/USD"], "crypto_quote_integrity_rows": []})
        btc = second["pairs"][0]
        self.assertFalse(btc["latest_quote_observable"])
        self.assertEqual(btc["last_bid"], 10.0)
        self.assertAlmostEqual(btc["last_spread"], 0.99502488, places=7)

    def test_sentinel_distinguishes_router_defect_from_provider_absence(self):
        _, signals, waiting = ContinuousSystemIntegrityScannerV1._crypto_market_data(
            {"crypto_ranking_snapshot": {"crypto_quote_integrity_rows": [{"symbol": "BTC/USD", "quote_received": False, "provider_diagnostics": {"failure_classification": "ASTRA_REQUEST_NOT_SENT", "worker_exception": "adapter defect"}}]}},
            {},
            8,
        )
        self.assertEqual(signals[0]["kind"], "CRYPTO_PROVIDER_PATH_DEFECT")
        self.assertFalse(waiting)

    def test_snapshot_is_read_only_and_safety_is_preserved(self):
        matrix, payload = self._matrix([]); matrix.write(payload)
        before = os.stat(matrix.path).st_mtime_ns
        snapshot = matrix.snapshot()
        self.assertEqual(before, os.stat(matrix.path).st_mtime_ns)
        self.assertEqual(snapshot["provider_calls_from_get"], 0)
        self.assertEqual(snapshot["broker_actions_from_get"], 0)
        self.assertTrue(snapshot["paper_only_preserved"])
        self.assertFalse(snapshot["behavior_safe_to_apply"])


if __name__ == "__main__":
    unittest.main()
