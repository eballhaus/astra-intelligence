from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_canonical_market_timestamp_v1 import canonical_market_timestamp_v1
from engine.astra_trading_readiness_v1 import AstraTradingReadinessV1
from engine.paper_autopilot import PaperAutopilotEngine


def _iso(seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class TradingReadinessTests(unittest.TestCase):
    def _monitor(self) -> AstraTradingReadinessV1:
        directory = tempfile.TemporaryDirectory(prefix="astra_readiness_")
        self.addCleanup(directory.cleanup)
        monitor = AstraTradingReadinessV1(directory.name)
        monitor._session = lambda: {"timezone": "America/New_York", "equity_session_open": True, "preopen_window": False, "market_local_time": "2026-08-31T10:00:00-04:00"}
        return monitor

    def test_healthy_runtime_is_technically_ready_without_a_trade(self):
        result = self._monitor().run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self.assertEqual(result["trading_integrity_state"], "READY")
        self.assertEqual(result["day_readiness"], "TECHNICALLY_READY")
        self.assertEqual(result["technical_no_trade"], "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT")
        self.assertFalse(result["forced_trades_enabled"])
        self.assertFalse(result["entry_policy_changed"])

    def test_discovery_bypass_runs_only_allowlisted_rebuild(self):
        calls: list[str] = []
        result = self._monitor().run_if_due(
            runtime_state={"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}},
            worker_state={},
            actions={"REBUILD_CANONICAL_DISCOVERY_STATE": lambda: calls.append("rebuild") or {"candidate_source_available": True}},
        )
        self.assertEqual(calls, ["rebuild"])
        self.assertEqual(result["technical_no_trade"], "TECHNICAL_NO_TRADE")
        self.assertEqual(result["active_faults"][0]["fault_type"], "DISCOVERY_LEGACY_BYPASS")
        self.assertEqual(result["recoveries"][0]["repair_action"], "REBUILD_CANONICAL_DISCOVERY_STATE")

    def test_missing_active_symbol_is_reconciled_without_provider_or_broker_action(self):
        calls: list[str] = []
        result = self._monitor().run_if_due(
            runtime_state={
                "active_equity_fmp_observations_v1": {"observations": {"AAPL": {"provider_native_timestamp": _iso(-1)}}},
                "alpaca_ws_active_position_monitor_v1": {"subscribed_symbols": []},
            },
            worker_state={},
            actions={"RECONCILE_WS_SUBSCRIPTIONS": lambda: calls.append("ws") or {"status": "ok"}},
        )
        self.assertEqual(calls, ["ws"])
        self.assertEqual(result["ws_coverage_integrity"], "FAULT")
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)

    def test_alias_matched_observation_preserves_native_timestamp(self):
        directory = tempfile.TemporaryDirectory(prefix="astra_alias_")
        self.addCleanup(directory.cleanup)
        engine = PaperAutopilotEngine(db_path=os.path.join(directory.name, "paper.db"), state_path=os.path.join(directory.name, "state.json"), enabled=False)
        engine.get_latest_row_fn = lambda *_args: self.fail("identity aliases should reuse the existing observation")
        engine._runtime_state["active_equity_fmp_observations_v1"] = {
            "observations": {
                "AAPL": {
                    "symbol": "AAPL", "canonical_position_id": "lifecycle-a",
                    "canonical_position_aliases": ["lifecycle-a", "position-a"],
                    "provider_native_timestamp": _iso(-2), "receive_timestamp": _iso(), "price": 100.0,
                }
            }
        }
        quotes = engine._loss_containment_quote_evidence(
            {"AAPL": {"asset_type": "stock", "current_price": 99.0}},
            managed_rows_by_symbol={"AAPL": {"symbol": "AAPL", "position_id": "position-a", "lane_id": "DAY"}},
        )
        evidence = canonical_market_timestamp_v1(quotes["AAPL"], source_type="QUOTE", max_age_seconds=20)
        self.assertTrue(evidence["executable_freshness"])
        self.assertEqual(evidence["provider_native_timestamp"], engine._runtime_state["active_equity_fmp_observations_v1"]["observations"]["AAPL"]["provider_native_timestamp"])

    def test_truth_watchdog_classifies_open_position_without_declaring_a_fault(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "position_lane_horizon_recovery_v1": {"positions": [{"symbol": "AAPL", "lane_id": "DAY", "position_id": "p-1"}]},
                "position_exit_readiness_v1": {"positions": [{"symbol": "AAPL", "lane_id": "DAY"}]},
            },
            worker_state={},
        )
        day = result["truth_production_watchdog"]["lanes"]["DAY"]
        self.assertEqual(day["current_open_positions"], 1)
        self.assertEqual(day["technical_truth_starvation_status"], "NATURAL_OPEN_POSITION")
        self.assertEqual(result["day_readiness"], "TECHNICALLY_READY")

    def test_truth_without_learning_acknowledgement_is_an_explicit_fault(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "broker_truth_records_v1": [{"lane_id": "DAY", "closed_at": _iso(-5), "learning_acknowledged": False}],
            },
            worker_state={},
        )
        self.assertEqual(result["strict_truth_integrity"], "FAULT")
        self.assertEqual(result["truth_production_watchdog"]["lanes"]["DAY"]["technical_truth_starvation_status"], "LEARNING_HANDOFF_FAILURE")
        self.assertEqual(result["active_faults"][0]["fault_type"], "STRICT_TRUTH_LEARNING_HANDOFF_FAILURE")

    def test_monitor_result_is_persisted_with_worker_state(self):
        directory = tempfile.TemporaryDirectory(prefix="astra_readiness_persist_")
        self.addCleanup(directory.cleanup)
        state_path = os.path.join(directory.name, "state.json")
        engine = PaperAutopilotEngine(db_path=os.path.join(directory.name, "paper.db"), state_path=state_path, enabled=False)
        engine._runtime_state["astra_trading_readiness_v1"] = {"trading_integrity_state": "READY"}
        engine._runtime_state["trading_readiness_last_error_v1"] = {"error_type": "None"}
        engine._save_state_file()
        with open(state_path, "r", encoding="utf-8") as handle:
            payload = __import__("json").load(handle)
        self.assertEqual(payload["astra_trading_readiness_v1"]["trading_integrity_state"], "READY")
        self.assertEqual(payload["trading_readiness_last_error_v1"]["error_type"], "None")


if __name__ == "__main__":
    unittest.main()
