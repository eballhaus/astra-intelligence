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
    def test_only_worker_process_can_own_alpaca_ws(self):
        connect_calls: list[str] = []

        def connect(*_args, **_kwargs):
            connect_calls.append("called")
            return object()

        api_monitor = AlpacaWSMonitor(connect=connect)
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api", "ASTRA_ALPACA_WS_ENABLED": "1"}, clear=False):
            api_monitor.configure_symbols(symbols=["AAPL"])
            api_monitor._run()
        self.assertEqual(connect_calls, [])
        self.assertIsNone(api_monitor._thread)

    def test_api_monitor_consumes_worker_shared_status_and_observation(self):
        with tempfile.TemporaryDirectory(prefix="astra_ws_shared_state_") as directory:
            now = __import__("time").time()
            state_path = os.path.join(directory, "paper_autopilot_state.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                __import__("json").dump({
                    "alpaca_ws_active_position_monitor_v1": {
                        "owner_process_role": "worker",
                        "transport_health": "HEALTHY",
                        "connection_count": 1,
                        "subscribed_symbols": ["AAPL"],
                        "desired_symbols": ["AAPL"],
                        "observations": {
                            "AAPL": {
                                "symbol": "AAPL",
                                "price": 100.1,
                                "quote_timestamp": now - 1.0,
                                "provider_native_timestamp": "2026-09-02T15:00:00Z",
                                "receive_timestamp": now - 0.5,
                                "provider_used": "ALPACA_WS_IEX",
                            }
                        },
                    }
                }, handle)
            monitor = AlpacaWSMonitor()
            with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api", "ASTRA_STATE_DIR": directory}, clear=False):
                status = monitor.status()
                quote = monitor.get_quote("AAPL", max_age_seconds=20)
            self.assertTrue(status["shared_state_consumed"])
            self.assertEqual(status["connection_count"], 1)
            self.assertEqual(status["subscribed_symbols"], ["AAPL"])
            self.assertEqual(quote["provider_used"], "ALPACA_WS_IEX")
            self.assertAlmostEqual(quote["quote_age_seconds"], 0.5, delta=0.2)

    def test_worker_status_publishes_bounded_observations(self):
        monitor = AlpacaWSMonitor()
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker", "ASTRA_ALPACA_WS_ENABLED": "0"}, clear=False):
            monitor.configure_symbols(symbols=["AAPL"])
            monitor._record_message({
                "T": "q", "S": "AAPL", "bp": 100.0, "ap": 100.2, "t": _iso(),
            })
            status = monitor.status()
        self.assertEqual(status["owner_process_role"], "worker")
        self.assertEqual(status["observations"]["AAPL"]["provider_used"], "ALPACA_WS_IEX")

    def test_run_waits_for_auth_and_subscription_ack_and_configures_keepalive(self):
        class Connection:
            def __init__(self):
                self.sent: list[str] = []
                self.closed = False
                self.messages = [
                    '[{"T":"success","msg":"authenticated"}]',
                    '[{"T":"subscription","quotes":["AAPL"],"trades":["AAPL"]}]',
                    '[{"T":"q","S":"AAPL","bp":100.0,"ap":100.2,"t":"2026-09-02T14:00:00Z"}]',
                ]

            def send(self, payload):
                self.sent.append(payload)

            def recv(self, timeout):
                if self.messages:
                    return self.messages.pop(0)
                raise TimeoutError()

            def close(self):
                self.closed = True

        connection = Connection()
        kwargs = {}

        def connect(_endpoint, **options):
            kwargs.update(options)
            return connection

        monitor = AlpacaWSMonitor(connect=connect)
        monitor._desired_symbols = {"AAPL"}
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(AlpacaWSMonitor, "_credentials", return_value=("key", "secret")):
            thread = __import__("threading").Thread(target=monitor._run)
            thread.start()
            for _ in range(20):
                if monitor.status()["stats"]["messages_received"]:
                    break
                __import__("time").sleep(0.01)
            monitor._stop.set()
            monitor._wake.set()
            thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(kwargs["ping_interval"], 20.0)
        self.assertIsNone(kwargs["ping_timeout"])
        self.assertEqual(__import__("json").loads(connection.sent[0])["action"], "auth")
        self.assertEqual(__import__("json").loads(connection.sent[1])["action"], "subscribe")
        self.assertEqual(monitor._stats["auth_state"], "AUTHENTICATED")
        self.assertEqual(monitor._stats["subscription_state"], "SUBSCRIBED")

    def test_subscription_is_bounded_and_excludes_crypto_symbols(self):
        monitor = AlpacaWSMonitor()
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker", "ASTRA_ALPACA_WS_ENABLED": "0", "ASTRA_ALPACA_WS_MAX_SYMBOLS": "2"}):
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
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False):
            self.assertEqual(monitor.status()["stats"]["errors"], 0)

    def test_reconnect_storm_is_unhealthy_and_reconnect_request_is_bounded(self):
        class Connection:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        monitor = AlpacaWSMonitor()
        connection = Connection()
        monitor._connection = connection
        monitor._desired_symbols = {"AAPL"}
        monitor._subscribed_symbols = {"AAPL"}
        monitor._stats.update({"errors": 8, "reconnects": 8, "messages_received": 0})
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False):
            self.assertEqual(monitor.status()["transport_health"], "UNHEALTHY")
        result = monitor.request_reconnect()
        self.assertTrue(connection.closed)
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)


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

    def test_stale_fmp_price_is_not_persisted_as_live_observation(self):
        engine = self._engine()

        class Router:
            def get_quote(self, symbol, **kwargs):
                return {
                    "provider_used": "FMP", "price": 100.0,
                    "provider_quote_timestamp": "2000-01-01T00:00:00Z",
                    "quote_quality": "live", "attempted_providers": ["FMP"],
                }

        engine._legacy_swing_fmp_router = Router()
        engine._fetch_open_positions = lambda asset_type=None: [{
            "symbol": "AAPL", "asset_type": "stock", "status": "OPEN", "quantity": 1,
            "lane_id": "DAY", "lifecycle_id": "life-a", "entry_fill_id": "fill-a",
        }]
        state = engine._refresh_active_equity_fmp_observations_v1()
        self.assertEqual(state["successful_observation_count"], 0)
        self.assertEqual(state["failed_observation_count"], 1)
        self.assertEqual(state["observations"], {})
        self.assertEqual(state["errors"][0]["reason"], "STALE_PROVIDER_NATIVE_TIMESTAMP")

    def test_observational_monitor_state_survives_canonical_persistence(self):
        engine = self._engine()
        engine._runtime_state["active_equity_fmp_observations_v1"] = {"refresh_state": "REFRESHED"}
        engine._runtime_state["alpaca_ws_active_position_monitor_v1"] = {"connection_count": 1}
        engine._save_state_file()
        with open(engine.state_path, "r", encoding="utf-8") as handle:
            saved = __import__("json").load(handle)
        self.assertEqual(saved["active_equity_fmp_observations_v1"]["refresh_state"], "REFRESHED")
        self.assertEqual(saved["alpaca_ws_active_position_monitor_v1"]["connection_count"], 1)


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
            {
                "symbol": "LEGACY", "asset_type": "stock", "status": "OPEN", "quantity": 1,
                "lane_id": "UNKNOWN", "candidate_id": "candidate-l", "lifecycle_id": "life-l",
                "entry_fill_id": "fill-l",
            },
        ]
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(server_extend, "ALPACA_WS_MONITOR", monitor), patch.object(
            server_extend.PAPER_AUTOPILOT, "_fetch_open_positions", return_value=rows
        ), patch.object(server_extend, "_near_entry_candidates", return_value=["MSFT"]), patch.object(
            server_extend, "_ALPACA_WS_ALLOC_STATE", {"ts": 0.0, "signature": ""}
        ):
            server_extend._refresh_alpaca_ws_allocation()
        self.assertEqual(monitor.kwargs["open_position_symbols"], ["AAPL"])
        self.assertEqual(monitor.kwargs["near_entry_symbols"], ["MSFT"])

    def test_unchanged_allocation_refreshes_async_stream_status(self):
        class Monitor:
            def __init__(self):
                self.configure_calls = 0
                self.connected = False

            def configure_symbols(self, **_kwargs):
                self.configure_calls += 1
                return {"ok": True}

            def status(self):
                return {"running": self.connected, "connection_count": int(self.connected), "subscribed_symbols": ["AAPL"] if self.connected else []}

        monitor = Monitor()
        rows = [{"symbol": "AAPL", "asset_type": "stock", "status": "OPEN", "quantity": 1, "lane_id": "DAY", "lifecycle_id": "life-a", "entry_fill_id": "fill-a"}]
        allocation = {"ts": 0.0, "signature": ""}
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False), patch.object(server_extend, "ALPACA_WS_MONITOR", monitor), patch.object(
            server_extend.PAPER_AUTOPILOT, "_fetch_open_positions", return_value=rows
        ), patch.object(server_extend, "_near_entry_candidates", return_value=[]), patch.object(
            server_extend, "_ALPACA_WS_ALLOC_STATE", allocation
        ):
            server_extend._refresh_alpaca_ws_allocation()
            monitor.connected = True
            server_extend._refresh_alpaca_ws_allocation()
        self.assertEqual(monitor.configure_calls, 1)
        self.assertTrue(server_extend.PAPER_AUTOPILOT._runtime_state["alpaca_ws_active_position_monitor_v1"]["running"])

    def test_api_allocation_never_configures_process_local_monitor(self):
        class Monitor:
            def __init__(self):
                self.configure_calls = 0
                self.status_calls = 0

            def configure_symbols(self, **_kwargs):
                self.configure_calls += 1

            def status(self):
                self.status_calls += 1
                return {"owner_process_role": "worker", "connection_count": 1}

        monitor = Monitor()
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}, clear=False), patch.object(
            server_extend, "ALPACA_WS_MONITOR", monitor
        ), patch.object(server_extend.PAPER_AUTOPILOT, "_fetch_open_positions", side_effect=AssertionError("API must not read allocation")):
            server_extend._refresh_alpaca_ws_allocation(force_reconcile=True)
        self.assertEqual(monitor.configure_calls, 0)
        self.assertEqual(monitor.status_calls, 1)

    def test_current_lifecycle_metadata_repairs_horizon_recovery_join(self):
        engine = PaperAutopilotEngine(
            db_path=os.path.join(tempfile.mkdtemp(prefix="astra_recovery_"), "paper.db"),
            state_path=os.path.join(tempfile.mkdtemp(prefix="astra_recovery_state_"), "state.json"),
            enabled=False,
        )
        engine._runtime_state["last_evidence_capacity_snapshot"] = {
            "position_rows_for_read_only_consumers": [{"symbol": "ETH/USD", "asset_type": "crypto", "entry_timestamp": _iso()}],
        }
        result = engine._recover_broker_position_lane_horizon_v1(
            {"ETH/USD": {"symbol": "ETH/USD", "asset_type": "crypto"}},
            [{
                "symbol": "ETH/USD", "status": "OPEN", "asset_type": "crypto",
                "position_id": "life-eth", "entry_order_id": "order-eth", "entry_fill_id": "fill-eth",
                "lane_id": "CRYPTO", "paper_entry_horizon_style": "day_trade",
                "expected_max_hold": "2h-EOD", "same_session_exit_required": False, "overnight_allowed": True,
            }],
        )
        row = result["positions"][0]
        self.assertEqual(row["lane_status"], "RESOLVED")
        self.assertEqual(row["horizon_status"], "RESOLVED")
        self.assertEqual(row["canonical_identity_status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
