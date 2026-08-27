from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from engine.alpaca_ws_monitor import AlpacaWSMonitor
from engine.paper_autopilot import PaperAutopilotEngine
import server_extend


def _iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class AlpacaWSMonitorTests(unittest.TestCase):
    def test_subscription_is_bounded_and_excludes_crypto_symbols(self):
        monitor = AlpacaWSMonitor()
        with patch.dict(os.environ, {"ASTRA_ALPACA_WS_ENABLED": "0", "ASTRA_ALPACA_WS_MAX_SYMBOLS": "2"}):
            monitor.configure_symbols(
                open_position_symbols=["MSFT", "AAPL", "ETH/USD"],
                near_entry_symbols=["NVDA", "TSLA"],
            )
        status = monitor.status()
        self.assertEqual(status["desired_symbols"], ["AAPL", "MSFT"])
        self.assertEqual(status["priority_classes"]["open_positions"], 2)
        self.assertEqual(status["priority_classes"]["near_entry"], 0)

    def test_iex_observation_retains_provenance_and_is_not_market_truth(self):
        monitor = AlpacaWSMonitor()
        monitor._record_message({
            "T": "q", "S": "AAPL", "bp": 100.0, "ap": 100.2, "t": _iso(),
        })
        quote = monitor.get_quote("AAPL", max_age_seconds=20)
        self.assertIsNotNone(quote)
        self.assertEqual(quote["provider_used"], "ALPACA_WS_IEX")
        self.assertEqual(quote["provider_provenance"], "FAST_IEX_OBSERVATION")
        self.assertTrue(quote["market_observation_only"])
        self.assertFalse(quote["consolidated_market_truth"])
        self.assertAlmostEqual(quote["price"], 100.1)

    def test_quiet_connection_timeout_is_not_a_reconnect_failure(self):
        class QuietConnection:
            def recv(self, timeout):
                raise TimeoutError()

        monitor = AlpacaWSMonitor()
        monitor._read_messages(QuietConnection())
        self.assertEqual(monitor.status()["stats"]["errors"], 0)


class ActiveEquityFMPSupplementTests(unittest.TestCase):
    def _engine(self) -> PaperAutopilotEngine:
        directory = tempfile.TemporaryDirectory(prefix="astra_active_fmp_")
        self.addCleanup(directory.cleanup)
        return PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
        )

    def test_only_canonical_broker_linked_equities_receive_fmp_observation(self):
        engine = self._engine()
        calls: list[str] = []

        class Router:
            def get_quote(self, symbol, **kwargs):
                calls.append(symbol)
                return {
                    "provider_used": "FMP", "price": 100.0,
                    "provider_quote_timestamp": _iso(), "quote_quality": "live",
                    "quote_source": "FMP_MARKET_DATA", "attempted_providers": ["FMP"],
                }

        engine._legacy_swing_fmp_router = Router()
        engine._fetch_open_positions = lambda asset_type=None: [
            {
                "symbol": "AAPL", "asset_type": "stock", "status": "OPEN", "quantity": 1,
                "lane_id": "DAY", "candidate_id": "candidate-a", "lifecycle_id": "life-a",
                "entry_fill_id": "fill-a",
            },
            {
                "symbol": "DUST", "asset_type": "stock", "status": "OPEN", "quantity": 0.00001,
                "lane_id": "DAY", "candidate_id": "candidate-d", "lifecycle_id": "life-d",
                "entry_fill_id": "fill-d",
            },
            {
                "symbol": "ORPHAN", "asset_type": "stock", "status": "OPEN", "quantity": 1,
                "lane_id": "DAY", "lifecycle_id": "life-o",
            },
            {
                "symbol": "BTC/USD", "asset_type": "crypto", "status": "OPEN", "quantity": 1,
                "lane_id": "CRYPTO", "candidate_id": "candidate-c", "lifecycle_id": "life-c",
                "entry_fill_id": "fill-c",
            },
        ]
        state = engine._refresh_active_equity_fmp_observations_v1()
        self.assertEqual(calls, ["AAPL"])
        self.assertEqual(state["canonical_active_equity_symbols"], ["AAPL"])
        observation = state["observations"]["AAPL"]
        self.assertTrue(observation["market_observation_only"])
        self.assertFalse(observation["consolidated_market_truth"])
        self.assertFalse(state["entry_freshness_eligible"])
        self.assertEqual(state["execution_authority"], "UNCHANGED")

    def test_no_canonical_equity_positions_makes_no_fmp_request(self):
        engine = self._engine()

        class Router:
            def get_quote(self, *_args, **_kwargs):
                self.fail("no request expected")

        engine._legacy_swing_fmp_router = Router()
        engine._fetch_open_positions = lambda asset_type=None: []
        state = engine._refresh_active_equity_fmp_observations_v1()
        self.assertEqual(state["refresh_state"], "NO_CANONICAL_ACTIVE_EQUITY_POSITIONS")
        self.assertEqual(state["calls_this_refresh"], 0)


class AllocationBoundaryTests(unittest.TestCase):
    def test_server_allocation_excludes_dust_and_orphan_tracker_rows(self):
        class Monitor:
            def __init__(self):
                self.kwargs = None

            def configure_symbols(self, **kwargs):
                self.kwargs = kwargs
                return {"ok": True}

            def status(self):
                return {"running": False, "connection_count": 0}

        monitor = Monitor()
        rows = [
            {
                "symbol": "AAPL", "asset_type": "stock", "status": "OPEN", "quantity": 1,
                "lane_id": "DAY", "candidate_id": "candidate-a", "lifecycle_id": "life-a",
                "entry_fill_id": "fill-a",
            },
            {
                "symbol": "DUST", "asset_type": "stock", "status": "OPEN", "quantity": 0.00001,
                "lane_id": "DAY", "candidate_id": "candidate-d", "lifecycle_id": "life-d",
                "entry_fill_id": "fill-d",
            },
            {
                "symbol": "ORPHAN", "asset_type": "stock", "status": "OPEN", "quantity": 1,
                "lane_id": "DAY", "lifecycle_id": "life-o",
            },
        ]
        with patch.object(server_extend, "ALPACA_WS_MONITOR", monitor), patch.object(
            server_extend.PAPER_AUTOPILOT, "_fetch_open_positions", return_value=rows
        ), patch.object(server_extend, "_near_entry_candidates", return_value=["MSFT"]), patch.object(
            server_extend, "_ALPACA_WS_ALLOC_STATE", {"ts": 0.0, "signature": ""}
        ):
            server_extend._refresh_alpaca_ws_allocation()
        self.assertEqual(monitor.kwargs["open_position_symbols"], ["AAPL"])
        self.assertEqual(monitor.kwargs["near_entry_symbols"], ["MSFT"])


if __name__ == "__main__":
    unittest.main()
