from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from engine.alpaca_ws_monitor import AlpacaWSMonitor
from engine.astra_continuous_governance_v1 import ContinuousGovernanceV1


class GovernanceWebSocketRepairTests(unittest.TestCase):
    def test_current_governance_integrity_resource_path_has_no_missing_float_name(self):
        worker_state = {
            "active_worker_present": True,
            "process_id": 1,
            "resource_state": "RESOURCE_NORMAL",
        }
        runtime_state = {
            "system_integrity_scanner_v1": {
                "status": "PASS",
                "scan_owner": "canonical_worker",
                "resource_protection": {
                    "state_files_over_limit": 0,
                    "sqlite_contention_detected": False,
                    "unsafe_deep_scan_under_load": False,
                },
                "crypto_market_data": {},
                "active_root_causes": [],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            result = ContinuousGovernanceV1(directory).run_worker_cycle(
                worker_state=worker_state,
                runtime_state=runtime_state,
                safety={"paper_mode_verified": True, "broker_live_endpoint_allowed": False},
            )
        self.assertTrue(result["invariants"])
        self.assertFalse(any(row.get("state") == "EXCEPTION" for row in result["invariants"]))

    def test_idle_transport_is_distinct_from_stale_data(self):
        monitor = AlpacaWSMonitor()
        monitor._read_shared_status = lambda: {}
        monitor._desired_symbols = {"AAPL"}
        monitor._connection = object()
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        idle_at = (datetime.now(UTC) - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
        monitor._stats.update({
            "auth_state": "AUTHENTICATED",
            "subscription_state": "SUBSCRIBED",
            "last_connected_utc": now,
            "last_message_utc": idle_at,
        })
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker", "ASTRA_ALPACA_WS_ENABLED": "1"}, clear=False):
            status = monitor.status()
        self.assertEqual(status["stream_state"], "NETWORK_IDLE")
        self.assertEqual(status["observation_state"], "PROVIDER_DATA_STALE")
        self.assertEqual(status["stats"]["errors"], 0)

    def test_recent_transport_is_connected_and_dead_transport_is_distinct(self):
        monitor = AlpacaWSMonitor()
        monitor._read_shared_status = lambda: {}
        monitor._desired_symbols = {"AAPL"}
        monitor._quotes["AAPL"] = {"receive_timestamp": time.time(), "symbol": "AAPL"}
        monitor._connection = object()
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        monitor._stats.update({
            "auth_state": "AUTHENTICATED",
            "subscription_state": "SUBSCRIBED",
            "last_connected_utc": now,
            "last_message_utc": now,
        })
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker", "ASTRA_ALPACA_WS_ENABLED": "1"}, clear=False):
            current = monitor.status()
            monitor._connection = None
            dead = monitor.status()
        self.assertEqual(current["stream_state"], "CONNECTED")
        self.assertEqual(current["observation_state"], "CURRENT")
        self.assertEqual(dead["stream_state"], "CONNECTION_DEAD")


if __name__ == "__main__":
    unittest.main()
