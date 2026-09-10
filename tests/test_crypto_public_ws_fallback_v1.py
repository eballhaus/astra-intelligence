"""Contract coverage for public, read-only crypto websocket fallbacks."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from engine.alpaca_ws_monitor import AlpacaWSMonitor
from engine.provider_router import (
    normalize_public_crypto_websocket_quote_v1,
    select_crypto_websocket_quote_v1,
)


NOW = 1_789_000_000.0
STAMP = "2026-09-10T20:32:27Z"


def _quote(provider: str, timestamp: str = STAMP, symbol: str = "ETH/USD"):
    return {
        "symbol": symbol,
        "bid": 100.0,
        "ask": 101.0,
        "provider": provider,
        "provider_native_timestamp": timestamp,
        "provider_quote_timestamp": timestamp,
        "quote_timestamp": timestamp,
        "receive_timestamp": NOW,
    }


class CryptoPublicWebsocketFallbackTests(unittest.TestCase):
    def test_kraken_eth_and_shib_normalization_preserves_native_timestamp(self):
        rows = normalize_public_crypto_websocket_quote_v1("KRAKEN", {
            "channel": "ticker",
            "data": [
                {"symbol": "ETH/USD", "bid": 100.0, "ask": 101.0, "timestamp": STAMP},
                {"symbol": "SHIB/USD", "bid": 0.00001, "ask": 0.000011, "timestamp": STAMP},
            ],
        }, receive_timestamp=NOW)
        self.assertEqual([row["symbol"] for row in rows], ["ETH/USD", "SHIB/USD"])
        self.assertTrue(all(row["provider"] == "KRAKEN_PUBLIC_WS" for row in rows))
        self.assertTrue(all(row["provider_native_timestamp"] == STAMP for row in rows))
        self.assertTrue(all(row["receive_timestamp"] == NOW for row in rows))

    def test_coinbase_eth_and_shib_normalization_preserves_envelope_timestamp(self):
        rows = normalize_public_crypto_websocket_quote_v1("COINBASE", {
            "channel": "ticker", "timestamp": STAMP,
            "events": [{"tickers": [
                {"product_id": "ETH-USD", "best_bid": "100", "best_ask": "101"},
                {"product_id": "SHIB-USD", "best_bid": "0.00001", "best_ask": "0.000011"},
            ]}],
        }, receive_timestamp=NOW)
        self.assertEqual([row["symbol"] for row in rows], ["ETH/USD", "SHIB/USD"])
        self.assertTrue(all(row["provider"] == "COINBASE_PUBLIC_WS" for row in rows))
        self.assertTrue(all(row["provider_native_timestamp"] == STAMP for row in rows))

    def test_malformed_missing_timestamp_and_symbol_mismatch_fail_closed(self):
        self.assertEqual(normalize_public_crypto_websocket_quote_v1("KRAKEN", {"channel": "ticker", "data": [{"symbol": "ETH/USD", "bid": 1, "ask": 2}]}), [])
        self.assertEqual(normalize_public_crypto_websocket_quote_v1("COINBASE", {"channel": "ticker", "timestamp": STAMP, "events": [{"tickers": [{"product_id": "WETH-USD", "best_bid": "1", "best_ask": "2"}]}]}), [])

    def test_selection_prefers_fresh_alpaca_then_kraken_then_coinbase(self):
        now = 1_789_000_010.0
        fresh = "2026-09-10T20:32:27Z"
        # Use a deterministic current timestamp with the fixture clock.
        with patch("engine.provider_router._coerce_ts_seconds", return_value=now - 5.0):
            selected = select_crypto_websocket_quote_v1(_quote("ALPACA_WS_CRYPTO", fresh), _quote("KRAKEN_PUBLIC_WS", fresh), _quote("COINBASE_PUBLIC_WS", fresh), now_timestamp=now)
            self.assertEqual(selected["provider"], "ALPACA_WS_CRYPTO")
        with patch("engine.provider_router._coerce_ts_seconds", side_effect=[now - 30.0, now - 4.0]):
            selected = select_crypto_websocket_quote_v1(_quote("ALPACA_WS_CRYPTO"), _quote("KRAKEN_PUBLIC_WS"), None, now_timestamp=now)
            self.assertEqual(selected["provider"], "KRAKEN_PUBLIC_WS")
        with patch("engine.provider_router._coerce_ts_seconds", side_effect=[now - 30.0, now - 25.0, now - 3.0]):
            selected = select_crypto_websocket_quote_v1(_quote("ALPACA_WS_CRYPTO"), _quote("KRAKEN_PUBLIC_WS"), _quote("COINBASE_PUBLIC_WS"), now_timestamp=now)
            self.assertEqual(selected["provider"], "COINBASE_PUBLIC_WS")

    def test_all_stale_or_invalid_quotes_fail_closed(self):
        now = 1_789_000_010.0
        with patch("engine.provider_router._coerce_ts_seconds", return_value=now - 21.0):
            self.assertIsNone(select_crypto_websocket_quote_v1(_quote("ALPACA_WS_CRYPTO"), _quote("KRAKEN_PUBLIC_WS"), _quote("COINBASE_PUBLIC_WS"), now_timestamp=now))

    def test_selection_uses_bbo_midpoint_when_upstream_price_is_invalid(self):
        now = 1_789_000_010.0
        quote = _quote("KRAKEN_PUBLIC_WS")
        quote["price"] = 0.0
        with patch("engine.provider_router._coerce_ts_seconds", return_value=now - 1.0):
            selected = select_crypto_websocket_quote_v1(None, quote, None, now_timestamp=now)
        self.assertEqual(selected["price"], 100.5)

    def test_monitor_records_only_desired_symbol_and_never_claims_broker_truth(self):
        monitor = AlpacaWSMonitor()
        monitor._desired_crypto_symbols = {"ETH/USD"}
        monitor._record_public_crypto_message("KRAKEN", {
            "channel": "ticker", "data": [
                {"symbol": "ETH/USD", "bid": 100.0, "ask": 101.0, "timestamp": STAMP},
                {"symbol": "SHIB/USD", "bid": 1.0, "ask": 2.0, "timestamp": STAMP},
            ],
        })
        rows = monitor._public_crypto_quotes["KRAKEN"]
        self.assertEqual(set(rows), {"ETH/USD"})
        self.assertTrue(rows["ETH/USD"]["market_observation_only"])
        self.assertFalse(rows["ETH/USD"]["consolidated_market_truth"])

    def test_active_position_status_consumes_a_native_fresh_kraken_fallback(self):
        monitor = AlpacaWSMonitor()
        monitor._desired_crypto_symbols = {"ETH/USD"}
        monitor._public_crypto_quotes["KRAKEN"]["ETH/USD"] = {
            **_quote("KRAKEN_PUBLIC_WS"),
            "market_observation_only": True,
            "consolidated_market_truth": False,
        }
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch(
            "engine.provider_router._coerce_ts_seconds", return_value=__import__("time").time() - 1.0,
        ):
            observation = monitor.status()["observations"]["ETH/USD"]
        self.assertEqual(observation["provider"], "KRAKEN_PUBLIC_WS")
        self.assertEqual(observation["crypto_fallback_selection_state"], "KRAKEN_FALLBACK_FRESH")
        self.assertTrue(observation["market_observation_only"])
        self.assertFalse(observation["consolidated_market_truth"])

    def test_public_fallback_streams_remain_worker_owned_and_do_not_require_credentials(self):
        monitor = AlpacaWSMonitor()
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api", "ASTRA_CRYPTO_PUBLIC_WS_FALLBACK_ENABLED": "1"}, clear=False):
            monitor.configure_symbols(open_crypto_position_symbols=["ETH/USD"])
            self.assertIsNone(monitor._thread)
        self.assertEqual(monitor._public_crypto_endpoint("KRAKEN"), "wss://ws.kraken.com/v2")
        self.assertEqual(monitor._public_crypto_endpoint("COINBASE"), "wss://advanced-trade-ws.coinbase.com")

    def test_symbol_change_closes_existing_public_streams_for_single_resubscribe(self):
        class Connection:
            closed = 0

            def close(self):
                self.closed += 1

        monitor = AlpacaWSMonitor()
        kraken = Connection()
        coinbase = Connection()
        monitor._desired_crypto_symbols = {"ETH/USD"}
        monitor._public_crypto_connections = {"KRAKEN": kraken, "COINBASE": coinbase}
        with patch.object(monitor, "_ensure_thread"):
            monitor.configure_symbols(open_crypto_position_symbols=["SHIB/USD"])
        self.assertEqual(kraken.closed, 1)
        self.assertEqual(coinbase.closed, 1)
        monitor._public_crypto_connections = {"KRAKEN": kraken, "COINBASE": coinbase}
        with patch.object(monitor, "_ensure_thread"):
            monitor.configure_symbols(open_crypto_position_symbols=["SHIB/USD"])
        self.assertEqual(kraken.closed, 1)
        self.assertEqual(coinbase.closed, 1)

    def test_equity_quote_store_is_not_used_by_crypto_fallback(self):
        monitor = AlpacaWSMonitor()
        monitor._desired_crypto_symbols = {"ETH/USD"}
        monitor._quotes["ETH"] = _quote("ALPACA_WS_IEX", symbol="ETH")
        monitor._record_public_crypto_message("COINBASE", {
            "channel": "ticker", "timestamp": STAMP,
            "events": [{"tickers": [{"product_id": "ETH-USD", "best_bid": "100", "best_ask": "101"}]}],
        })
        self.assertIn("ETH", monitor._quotes)
        self.assertIn("ETH/USD", monitor._public_crypto_quotes["COINBASE"])


if __name__ == "__main__":
    unittest.main()
