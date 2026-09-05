from __future__ import annotations

import os
import tempfile
import time
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

    @staticmethod
    def _force_due(monitor: AstraTradingReadinessV1) -> None:
        payload = __import__("json").loads(monitor.path.read_text(encoding="utf-8"))
        payload["scan_monotonic"] = time.monotonic() - 301
        monitor.path.write_text(__import__("json").dumps(payload), encoding="utf-8")

    def test_healthy_runtime_is_technically_ready_without_a_trade(self):
        result = self._monitor().run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self.assertEqual(result["trading_integrity_state"], "READY")
        self.assertEqual(result["day_readiness"], "TECHNICALLY_READY")
        self.assertEqual(result["technical_no_trade"], "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT")
        self.assertFalse(result["forced_trades_enabled"])
        self.assertFalse(result["entry_policy_changed"])

    @staticmethod
    def _activity_scorecard(when: str, lane: str, **lane_values) -> dict:
        return {
            "generated_at": when,
            "lanes": {
                lane: {
                    "valid_activity_session": True,
                    "candidate_opportunity_observed": False,
                    "qualification_observed": False,
                    "entry_or_truth_progress_observed": False,
                    "current_open_positions": 0,
                    "truth_path_state": "READY_OR_NATURAL_WAIT",
                    "earliest_blocked_stage": "",
                    "earliest_blocker": "",
                    **lane_values,
                },
            },
        }

    def test_three_valid_equity_sessions_escalate_policy_rejection_without_policy_change(self):
        scores = [
            self._activity_scorecard(f"2026-08-2{day}T20:05:00Z", "DAY", candidate_opportunity_observed=True)
            for day in (4, 5, 6)
        ]
        payload = AstraTradingReadinessV1._lane_activity_escalation(scores, scores[-1], [])
        day = payload["lanes"]["DAY"]
        self.assertTrue(day["three_day_deep_review_required"])
        self.assertEqual(day["classification"], "POLICY_REJECTION")
        self.assertTrue(day["policy_calibration_evidence_required"])
        self.assertFalse(payload["policy_changed"])
        self.assertEqual(day["existing_recovery_state"], "NO_TECHNICAL_REPAIR_AUTHORIZED")

    def test_swing_open_position_is_not_a_three_day_starvation_false_positive(self):
        scores = [
            self._activity_scorecard(
                f"2026-08-2{day}T20:05:00Z", "SWING",
                candidate_opportunity_observed=True, current_open_positions=1,
            )
            for day in (4, 5, 6)
        ]
        payload = AstraTradingReadinessV1._lane_activity_escalation(scores, scores[-1], [])
        swing = payload["lanes"]["SWING"]
        self.assertFalse(swing["three_day_deep_review_required"])
        self.assertEqual(swing["classification"], "NATURAL_WAIT")
        self.assertEqual(swing["reason"], "NATURAL_OPEN_POSITION")

    def test_crypto_uses_a_rolling_72_hour_window(self):
        scores = [
            self._activity_scorecard(f"2026-08-26T{hour:02d}:00:00Z", "CRYPTO", candidate_opportunity_observed=True)
            for hour in (0, 12, 23)
        ]
        payload = AstraTradingReadinessV1._lane_activity_escalation(scores, scores[-1], [])
        crypto = payload["lanes"]["CRYPTO"]
        self.assertEqual(crypto["window_type"], "ROLLING_72_HOURS")
        self.assertEqual(crypto["valid_session_observations"], 3)
        self.assertTrue(crypto["three_day_deep_review_required"])

    def test_runtime_fault_reuses_existing_recovery_instead_of_becoming_policy_rejection(self):
        scores = [
            self._activity_scorecard(f"2026-08-2{day}T20:05:00Z", "SCALP", candidate_opportunity_observed=True)
            for day in (4, 5, 6)
        ]
        fault = {"lanes": ["SCALP"], "verification_result": "ACTION_DISPATCHED"}
        payload = AstraTradingReadinessV1._lane_activity_escalation(scores, scores[-1], [fault])
        scalp = payload["lanes"]["SCALP"]
        self.assertEqual(scalp["classification"], "RUNTIME_REPAIRABLE")
        self.assertEqual(scalp["existing_recovery_owner"], "AstraTradingReadinessV1")
        self.assertFalse(scalp["policy_calibration_evidence_required"])

    def test_provider_external_wait_does_not_become_a_code_or_policy_defect(self):
        scores = [
            self._activity_scorecard(f"2026-08-2{day}T20:05:00Z", "DAY", candidate_opportunity_observed=True)
            for day in (4, 5, 6)
        ]
        fault = {"lanes": ["DAY"], "classification": "PROVIDER_EXTERNAL"}
        payload = AstraTradingReadinessV1._lane_activity_escalation(scores, scores[-1], [fault])
        day = payload["lanes"]["DAY"]
        self.assertEqual(day["classification"], "PROVIDER_EXTERNAL")
        self.assertFalse(day["three_day_deep_review_required"])
        self.assertIsNone(day["existing_recovery_owner"])
        self.assertEqual(day["existing_recovery_state"], "NO_TECHNICAL_REPAIR_AUTHORIZED")

    def test_scorecard_starts_prospective_bounded_session_opportunity_accounting(self):
        monitor = self._monitor()
        first = monitor.run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self._force_due(monitor)
        payload = __import__("json").loads(monitor.path.read_text(encoding="utf-8"))
        payload["daily_scorecards"][0]["generated_at"] = _iso(-300)
        monitor.path.write_text(__import__("json").dumps(payload), encoding="utf-8")
        second = monitor.run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        accounting = second["daily_scorecard"]["lanes"]["DAY"]["session_opportunity_accounting"]
        self.assertGreater(accounting["NATURAL_WAIT_MINUTES"], 0.0)
        self.assertTrue(second["daily_scorecard"]["lanes"]["DAY"]["session_opportunity_accounting_prospective"])
        self.assertEqual(first["daily_scorecard"]["lanes"]["DAY"]["session_opportunity_accounting"]["NATURAL_WAIT_MINUTES"], 0.0)

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

    def test_current_canonical_candidate_flow_overrides_stale_failed_rebuild(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "equity_discovery_rebuild_v1": {
                    "candidate_source_available": False,
                    "generated_at": _iso(-3600),
                },
                "last_execution_trace": {
                    "final_blocker_reason": "legacy_market_evidence_bounded",
                    "candidate_source": "top_buys",
                    "candidates_seen": 4,
                    "allocation_lane_counts": {"DAY": 4},
                },
                "last_cycle_utc": _iso(),
            },
            worker_state={},
        )
        self.assertNotIn(
            "DISCOVERY_LEGACY_BYPASS",
            [row["fault_type"] for row in result["active_faults"]],
        )

    def test_current_candidate_flow_rechecks_cached_discovery_fault(self):
        monitor = self._monitor()
        monitor.run_if_due(
            runtime_state={"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}},
            worker_state={},
        )
        result = monitor.run_if_due(
            runtime_state={
                "equity_discovery_rebuild_v1": {"candidate_source_available": False, "generated_at": _iso(-3600)},
                "last_execution_trace": {
                    "final_blocker_reason": "legacy_market_evidence_bounded",
                    "candidate_source": "top_buys",
                    "candidate_source_count": 9,
                    "candidates_seen": 9,
                },
                "last_cycle_utc": _iso(),
            },
            worker_state={},
        )
        self.assertTrue(result["due"])
        self.assertNotIn("DISCOVERY_LEGACY_BYPASS", [row["fault_type"] for row in result["active_faults"]])

    def test_fresh_canonical_zero_candidates_is_not_a_discovery_code_fault(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "equity_discovery_rebuild_v1": {"candidate_source_available": False, "generated_at": _iso(-3600)},
                "last_execution_trace": {
                    "final_blocker_reason": "legacy_market_evidence_bounded",
                    "candidate_source": "top_buys",
                    "candidate_source_count": 0,
                    "candidates_seen": 0,
                    "candidate_snapshot_freshness": "SNAPSHOT_CURRENT",
                },
                "last_cycle_utc": _iso(),
            },
            worker_state={},
        )
        self.assertNotIn("DISCOVERY_LEGACY_BYPASS", [row["fault_type"] for row in result["active_faults"]])
        self.assertFalse(result["code_repair_required"])

    def test_stale_canonical_candidate_flow_fails_closed(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "equity_discovery_rebuild_v1": {"candidate_source_available": False},
                "last_execution_trace": {
                    "final_blocker_reason": "legacy_market_evidence_bounded",
                    "candidate_source": "top_buys",
                    "candidate_source_count": 9,
                    "candidates_seen": 9,
                    "generated_at": _iso(-3600),
                },
                "last_cycle_utc": _iso(),
            },
            worker_state={},
        )
        self.assertIn("DISCOVERY_LEGACY_BYPASS", [row["fault_type"] for row in result["active_faults"]])

    def test_recovery_dispatch_is_not_counted_as_success(self):
        runtime = {"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}}
        result = self._monitor().run_if_due(
            runtime_state=runtime,
            worker_state={},
            actions={"REBUILD_CANONICAL_DISCOVERY_STATE": lambda: {"status": "dispatched"}},
            refresh_runtime=lambda: runtime,
        )
        self.assertEqual(result["recoveries"][0]["verification_result"], "RECOVERY_VERIFYING")
        self.assertEqual(result["self_heal_successes"], 0)
        self.assertTrue(result["active_faults"])

    def test_recovery_counts_only_after_fresh_runtime_verification(self):
        runtime = {"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}}

        def rebuild():
            runtime["equity_discovery_rebuild_v1"] = {"candidate_source_available": True}
            return {"status": "rebuilt"}

        result = self._monitor().run_if_due(
            runtime_state=runtime,
            worker_state={},
            actions={"REBUILD_CANONICAL_DISCOVERY_STATE": rebuild},
            refresh_runtime=lambda: runtime,
        )
        self.assertEqual(result["recoveries"][0]["verification_result"], "RECOVERY_SUCCEEDED")
        self.assertEqual(result["self_heal_successes"], 1)
        self.assertEqual(result["active_faults"], [])

    def test_failed_recovery_is_not_counted_as_success(self):
        result = self._monitor().run_if_due(
            runtime_state={"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}},
            worker_state={},
            actions={"REBUILD_CANONICAL_DISCOVERY_STATE": lambda: {}},
        )
        self.assertEqual(result["recoveries"][0]["verification_result"], "RECOVERY_FAILED")
        self.assertEqual(result["self_heal_successes"], 0)

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

    def test_exact_management_timestamp_blocker_cannot_report_ready(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {"observations": {"AAPL": {"provider_native_timestamp": _iso(-1)}}},
                "alpaca_ws_active_position_monitor_v1": {"subscribed_symbols": ["AAPL"]},
                "loss_containment_state_v1": {
                    "decisions": {"AAPL": {"symbol": "AAPL", "exact_blockers": ["MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE"]}},
                },
            },
            worker_state={},
        )
        self.assertEqual(result["position_management_integrity"], "FAULT")
        self.assertNotEqual(result["trading_integrity_state"], "READY")

    def test_unresolved_legacy_management_row_cannot_override_canonical_pass(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {
                    "canonical_active_equity_symbols": ["AAPL"],
                    "observations": {"AAPL": {"provider_native_timestamp": _iso(-1)}},
                },
                "alpaca_ws_active_position_monitor_v1": {"subscribed_symbols": ["AAPL"]},
                "loss_containment_state_v1": {
                    "decisions": {
                        "canonical-a": {"symbol": "AAPL", "position_id": "canonical-a", "exact_blockers": []},
                        "unresolved:AAPL": {
                            "symbol": "AAPL",
                            "position_id": "unresolved:AAPL",
                            "ownership_classification": "UNRESOLVED_FAIL_CLOSED",
                            "exact_blockers": ["MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE"],
                        },
                    },
                },
            },
            worker_state={},
        )
        self.assertEqual(result["position_management_integrity"], "READY")
        self.assertNotIn(
            "PRODUCER_FRESH_CONSUMER_UNAVAILABLE",
            [row["fault_type"] for row in result["active_faults"]],
        )

    def test_historical_cycle_scanner_row_cannot_override_current_passing_cycle(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "system_integrity_scanner_v1": {
                    "active_root_causes": [{
                        "category": "CYCLE_WITHIN_BOUNDS",
                        "state": "VERIFYING",
                        "current_vs_historical": "CURRENT",
                        "severity": "CRITICAL",
                        "smallest_safe_repair": "historical cycle diagnostic",
                    }],
                },
            },
            worker_state={
                "cycle_state": "PARTIAL_SYMBOL_LIMIT",
                "cycle_elapsed_seconds": 12.4,
                "limits": {"maximum_cycle_elapsed_seconds": 20},
            },
        )
        self.assertNotIn(
            "WORKER_CYCLE_BOUNDARY_EXCEEDED",
            [row["fault_type"] for row in result["active_faults"]],
        )

    def test_current_cycle_failure_still_surfaces_from_worker_snapshot(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "system_integrity_scanner_v1": {
                    "active_root_causes": [{
                        "category": "CYCLE_WITHIN_BOUNDS",
                        "state": "VERIFYING",
                        "current_vs_historical": "CURRENT",
                    }],
                },
            },
            worker_state={
                "cycle_state": "ACTIVE_BOUNDED",
                "cycle_elapsed_seconds": 46.0,
                "limits": {"maximum_cycle_elapsed_seconds": 20},
            },
        )
        self.assertIn(
            "WORKER_CYCLE_BOUNDARY_EXCEEDED",
            [row["fault_type"] for row in result["active_faults"]],
        )

    def test_ws_reconnect_storm_cannot_report_ready(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {"observations": {"AAPL": {"provider_native_timestamp": _iso(-1)}}},
                "alpaca_ws_active_position_monitor_v1": {
                    "subscribed_symbols": ["AAPL"],
                    "stats": {"errors": 8, "reconnects": 8, "messages_received": 0, "last_error": "no close frame received or sent"},
                },
            },
            worker_state={},
        )
        self.assertEqual(result["active_faults"][0]["fault_type"], "WS_TRANSPORT_UNHEALTHY")
        self.assertNotEqual(result["trading_integrity_state"], "READY")

    def test_backend_health_failure_cannot_report_ready(self):
        result = self._monitor().run_if_due(
            runtime_state={"last_execution_trace": {}},
            worker_state={"resource": {"backend_health_latency_ms": None}},
        )
        self.assertEqual(result["active_faults"][0]["fault_type"], "BACKEND_UNHEALTHY")
        self.assertNotEqual(result["trading_integrity_state"], "READY")

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

    def test_operating_health_ledger_overrides_truth_row_ack_for_learning_liveness(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "broker_truth_records_v1": [{"lane_id": "DAY", "closed_at": _iso(-5), "learning_acknowledged": True}],
                "astra_operating_health_contract_v1": {
                    "truth_to_learning_ledger": [{
                        "lane": "DAY",
                        "consumption_result": "AWAITING_LEARNING",
                        "final_state": "PERSISTED_AWAITING_CONSUMPTION",
                    }],
                },
            },
            worker_state={},
        )
        self.assertEqual(result["strict_truth_integrity"], "FAULT")
        self.assertTrue(result["code_repair_required"])
        self.assertEqual(result["truth_production_watchdog"]["lanes"]["DAY"]["technical_truth_starvation_status"], "LEARNING_HANDOFF_FAILURE")
        self.assertEqual(result["truth_production_watchdog"]["lanes"]["DAY"]["last_learning_ingestion_time"], "")

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

    def test_legacy_monitor_record_does_not_delay_new_truth_watchdog(self):
        monitor = self._monitor()
        monitor.path.write_text('{"scan_monotonic":999999999,"schema_version":"ASTRA_TRADING_HOURS_INTEGRITY_MONITOR_V1"}', encoding="utf-8")
        result = monitor.run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self.assertTrue(result["due"])
        self.assertIn("truth_production_watchdog", result)

    def test_v1_watchdog_record_is_migrated_immediately_even_inside_interval(self):
        monitor = self._monitor()
        monitor.path.write_text(
            '{"scan_monotonic": %.6f, "truth_production_watchdog": {"schema_version": "ASTRA_ALL_LANE_TRUTH_PRODUCTION_WATCHDOG_V1", "lanes": {}}}'
            % time.monotonic(),
            encoding="utf-8",
        )
        result = monitor.run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self.assertTrue(result["due"])
        self.assertEqual(
            result["truth_production_watchdog"]["schema_version"],
            "ASTRA_ALL_LANE_TRUTH_PRODUCTION_WATCHDOG_V2",
        )

    def test_post_close_phase_keeps_scheduled_integrity_check_cadence(self):
        monitor = self._monitor()
        monitor._session = lambda: {
            "timezone": "America/New_York",
            "equity_session_open": False,
            "preopen_window": False,
            "check_phase": "POST_CLOSE_LANE_ACCOUNTING",
            "market_local_time": "2026-08-31T16:05:00-04:00",
        }
        monitor.path.write_text(
            "{\"scan_monotonic\": %.6f, \"truth_production_watchdog\": {\"lanes\": {}}}" % (time.monotonic() - 301),
            encoding="utf-8",
        )
        result = monitor.run_if_due(runtime_state={"last_execution_trace": {}}, worker_state={})
        self.assertTrue(result["due"])

    def test_global_noncrypto_horizon_count_cannot_degrade_crypto(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "position_lane_horizon_recovery_v1": {
                    "unresolved_horizon_count": 41,
                    "positions": [{"symbol": "ETH/USD", "asset_type": "crypto", "horizon_status": "RESOLVED"}],
                },
            },
            worker_state={},
        )
        self.assertEqual(result["crypto_readiness"], "TECHNICALLY_READY")

    def test_identity_rematerialization_stays_an_explicit_safe_action(self):
        calls: list[str] = []
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "position_lane_horizon_recovery_v1": {
                    "positions": [{"symbol": "ETH/USD", "asset_type": "crypto", "horizon_status": "UNAVAILABLE"}],
                },
            },
            worker_state={},
            actions={"RELOAD_CANONICAL_IDENTITY_STATE": lambda: calls.append("reload") or {"status": "rematerialized"}},
        )
        self.assertEqual(calls, ["reload"])
        self.assertEqual(result["recoveries"][0]["repair_action"], "RELOAD_CANONICAL_IDENTITY_STATE")
        self.assertEqual(result["broker_actions_used"], 0)

    def test_canonical_active_equity_list_detects_missing_ws_without_quote_payload(self):
        calls: list[str] = []
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {"canonical_active_equity_symbols": ["AAPL"], "observations": {}},
                "alpaca_ws_active_position_monitor_v1": {"subscribed_symbols": []},
            },
            worker_state={},
            actions={"RECONCILE_WS_SUBSCRIPTIONS": lambda: calls.append("ws") or {"status": "reconciled"}},
        )
        self.assertEqual(calls, ["ws"])
        self.assertEqual(result["active_faults"][0]["fault_type"], "ACTIVE_POSITION_NOT_STREAMED")

    def test_after_hours_ws_inactivity_is_not_an_equity_transport_fault(self):
        monitor = self._monitor()
        monitor._session = lambda: {
            "timezone": "America/New_York",
            "equity_session_open": False,
            "preopen_window": False,
            "market_local_time": "2026-08-31T20:00:00-04:00",
            "check_phase": "CRYPTO_CONTINUOUS_CHECK",
        }
        result = monitor.run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {
                    "canonical_active_equity_symbols": ["AAPL"],
                    "observations": {},
                },
                "alpaca_ws_active_position_monitor_v1": {
                    "transport_health": "UNHEALTHY",
                    "subscribed_symbols": [],
                    "stats": {"errors": 8, "reconnects": 8, "messages_received": 0},
                },
            },
            worker_state={},
        )
        self.assertEqual(result["active_faults"], [])
        self.assertFalse(result["code_repair_required"])

    def test_watchdog_tracks_bounded_stage_status_without_synthetic_learning_time(self):
        event_time = _iso(-2)
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {
                    "last_autopilot_cycle_at": event_time,
                    "per_candidate_decision_trace": [{
                        "lane_id": "DAY",
                        "finalist": True,
                        "qualified": True,
                        "order_ready": True,
                    }],
                },
                "astra_operating_health_contract_v1": {
                    "truth_to_learning_ledger": [{
                        "lane": "DAY",
                        "consumption_result": "CONSUMED",
                        "learning_acknowledgement_time": None,
                    }],
                },
            },
            worker_state={},
        )
        day = result["truth_production_watchdog"]["lanes"]["DAY"]
        self.assertEqual(day["last_discovery_time"], event_time)
        self.assertEqual(day["last_finalist_time"], event_time)
        self.assertEqual(day["last_qualified_time"], event_time)
        self.assertEqual(day["last_order_ready_time"], event_time)
        self.assertEqual(day["last_learning_ingestion_time"], "")
        self.assertEqual(day["stage_status"]["FINALIST"]["status"], "PROVEN_READY")
        self.assertEqual(day["stage_status"]["LEARNING"]["observed_at"], "")

    def test_current_matrix_failure_degrades_only_affected_lane(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "astra_multilane_completion_matrix_v1": {
                    "generated_at": _iso(-1),
                    "lanes": {
                        "SWING": {
                            "stages": {
                                "eligibility": {
                                    "status": "FAIL_UNKNOWN_CLOSED",
                                    "status_classification": "FAIL_UNKNOWN_CLOSED",
                                    "verification_state": "CURRENT",
                                    "first_bad_handoff": "candidate contract -> eligibility gate",
                                },
                            },
                        },
                    },
                },
            },
            worker_state={},
        )
        swing = result["truth_production_watchdog"]["lanes"]["SWING"]
        self.assertEqual(result["swing_readiness"], "DEGRADED")
        self.assertEqual(swing["current_earliest_blocked_stage"], "QUALIFIED")
        self.assertEqual(swing["technical_truth_starvation_status"], "ENTRY_PIPELINE_TECHNICAL_FAILURE")
        self.assertEqual(result["active_faults"][0]["fault_type"], "ENTRY_FUNNEL_STAGE_BLOCKED")
        self.assertEqual(result["day_readiness"], "TECHNICALLY_READY")

    def test_day_incomplete_candidate_evidence_does_not_create_code_repair(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "astra_multilane_completion_matrix_v1": {
                    "generated_at": _iso(-1),
                    "lanes": {
                        "DAY": {
                            "first_blocker": "CONTRACT_INCOMPLETE",
                            "stages": {
                                "eligibility": {
                                    "status": "INSUFFICIENT_EVIDENCE",
                                    "status_classification": "INSUFFICIENT_EVIDENCE",
                                    "verification_state": "CURRENT",
                                    "first_bad_handoff": "candidate contract -> eligibility gate",
                                    "insufficient_evidence_reason": "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
                                },
                            },
                        },
                    },
                },
            },
            worker_state={},
        )
        self.assertEqual(result["active_faults"], [])
        self.assertFalse(result["code_repair_required"])

    def test_explicit_capacity_wait_is_not_a_code_repair_package(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "astra_multilane_completion_matrix_v1": {
                    "generated_at": _iso(-1),
                    "lanes": {
                        "CRYPTO": {
                            "first_blocker": "capacity_concentration",
                            "stages": {
                                "eligibility": {
                                    "status": "FAIL_UNKNOWN_CLOSED",
                                    "verification_state": "CURRENT",
                                    "first_bad_handoff": "candidate contract -> eligibility gate",
                                },
                            },
                        },
                    },
                },
            },
            worker_state={},
        )
        self.assertEqual(result["crypto_readiness"], "TECHNICALLY_READY")
        self.assertEqual(result["active_faults"], [])
        self.assertEqual(result["code_repair_packages"], [])

    def test_lifecycle_broker_ambiguity_does_not_block_day_lane(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "system_integrity_scanner_v1": {
                    "active_root_causes": [{
                        "category": "CAUSAL_HANDOFF_LOSS",
                        "state": "OPEN",
                        "current_vs_historical": "CURRENT",
                        "severity": "CRITICAL",
                        "likely_owner": "authorized lane exit broker reconciliation",
                        "first_bad_handoff": "broker-confirmed exit fill -> canonical lifecycle closure",
                        "causal_handoff_integrity_v1": {
                            "lane": "DAY",
                            "symbol": "LYFT",
                            "lifecycle_id": "life-1",
                            "consumer_state": "AWAITING_BROKER_ZERO",
                        },
                    }],
                },
            },
            worker_state={},
        )
        self.assertEqual(result["day_readiness"], "DEGRADED")
        self.assertEqual(result["active_faults"][0]["classification"], "BROKER_EXTERNAL")
        self.assertEqual(result["active_faults"][0]["scope"], "LIFECYCLE")
        self.assertEqual(result["code_repair_packages"], [])

    def test_missing_current_observation_is_external_not_source_package(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {
                    "canonical_active_equity_symbols": ["AAPL"],
                    "observations": {},
                },
                "alpaca_ws_active_position_monitor_v1": {
                    "transport_health": "HEALTHY",
                    "subscribed_symbols": ["AAPL"],
                },
                "loss_containment_state_v1": {
                    "decisions": {
                        "AAPL": {
                            "symbol": "AAPL",
                            "exact_blockers": ["MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE"],
                        },
                    },
                },
            },
            worker_state={},
        )
        fault = next(row for row in result["active_faults"] if row["fault_type"] == "PRODUCER_FRESH_CONSUMER_UNAVAILABLE")
        self.assertEqual(fault["classification"], "PROVIDER_EXTERNAL")
        self.assertEqual(result["code_repair_packages"], [])

    def test_disconnected_ws_does_not_duplicate_subscription_fault(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "active_equity_fmp_observations_v1": {
                    "canonical_active_equity_symbols": ["AAPL"],
                    "observations": {"AAPL": {"provider_native_timestamp": _iso(-1)}},
                },
                "alpaca_ws_active_position_monitor_v1": {
                    "transport_health": "UNHEALTHY",
                    "subscribed_symbols": [],
                    "stats": {"errors": 8, "reconnects": 8, "messages_received": 0},
                },
            },
            worker_state={},
        )
        fault_types = [row["fault_type"] for row in result["active_faults"]]
        self.assertIn("WS_TRANSPORT_UNHEALTHY", fault_types)
        self.assertNotIn("ACTIVE_POSITION_NOT_STREAMED", fault_types)

    def test_current_scanner_reconciliation_failure_is_attributed_to_day(self):
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {},
                "system_integrity_scanner_v1": {
                    "active_root_causes": [{
                        "category": "CAUSAL_HANDOFF_LOSS",
                        "state": "OPEN",
                        "current_vs_historical": "CURRENT",
                        "severity": "CRITICAL",
                        "likely_owner": "canonical lifecycle closure",
                        "first_bad_handoff": "broker-confirmed exit fill -> canonical lifecycle closure",
                        "causal_handoff_integrity_v1": {
                            "lane": "DAY",
                            "first_bad_handoff": "broker-confirmed exit fill -> canonical lifecycle closure",
                        },
                    }],
                },
            },
            worker_state={},
        )
        day = result["truth_production_watchdog"]["lanes"]["DAY"]
        self.assertEqual(result["day_readiness"], "BLOCKED")
        self.assertEqual(day["current_earliest_blocked_stage"], "RECONCILIATION")
        self.assertEqual(day["technical_truth_starvation_status"], "RECONCILIATION_FAILURE")
        self.assertEqual(result["active_faults"][0]["fault_type"], "RECONCILIATION_FAILURE")

    def test_consumed_learning_without_ack_timestamp_does_not_claim_event_time(self):
        event_time = _iso(-10)
        result = self._monitor().run_if_due(
            runtime_state={
                "last_execution_trace": {"last_autopilot_cycle_at": event_time},
                "astra_operating_health_contract_v1": {
                    "truth_to_learning_ledger": [{
                        "lane": "DAY",
                        "consumption_result": "CONSUMED",
                        "learning_acknowledgement_time": None,
                        "cortex_acknowledgement_time": None,
                        "governance_acknowledgement_time": None,
                    }],
                },
            },
            worker_state={},
        )
        day = result["truth_production_watchdog"]["lanes"]["DAY"]
        self.assertEqual(day["last_learning_ingestion_time"], "")
        self.assertEqual(day["stage_status"]["LEARNING"]["observed_at"], "")

    def test_exhausted_recovery_persists_exact_code_repair_package(self):
        monitor = self._monitor()
        runtime = {"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}}
        action = lambda: {"status": "dispatched"}
        monitor.run_if_due(runtime_state=runtime, worker_state={"active_worker_pid": 42}, actions={"REBUILD_CANONICAL_DISCOVERY_STATE": action})
        self._force_due(monitor)
        result = monitor.run_if_due(runtime_state=runtime, worker_state={"active_worker_pid": 42}, actions={"REBUILD_CANONICAL_DISCOVERY_STATE": action})
        package = result["code_repair_packages"][0]
        self.assertEqual(package["fault_code"], "DISCOVERY_LEGACY_BYPASS")
        self.assertEqual(package["owner_file"], "engine/paper_autopilot.py")
        self.assertEqual(package["owner_function"], "_rebuild_equity_candidate_snapshot_v1")
        self.assertEqual(package["worker_pid"], 42)
        self.assertEqual(package["minimal_reproduction_evidence"]["fingerprint"], result["active_faults"][0]["evidence_fingerprint"])
        self.assertEqual(result["autonomous_control_loop"]["state"], "CODE_REPAIR_REQUIRED")

    def test_reconciliation_repair_package_names_live_owner(self):
        monitor = self._monitor()
        issue = {
            "fault_type": "RECONCILIATION_FAILURE",
            "component": "authorized lane exit broker reconciliation",
            "lanes": ["DAY"],
            "evidence": "broker-confirmed exit fill -> canonical lifecycle closure",
            "owner_file": "engine/paper_autopilot.py",
            "owner_function": "PaperAutopilot._refresh_authorized_lane_exit_pending",
            "failing_invariant": "BROKER_FILLED_EXIT_RECONCILES_TO_CANONICAL_LIFECYCLE",
            "expected_contract": "the target lifecycle is reconciled using its own authoritative broker fill identity",
            "smallest_repair_scope": "resolve lifecycle-specific reconciliation without assigning aggregate residuals",
            "earliest_stage": "RECONCILIATION",
            "evidence_fingerprint": "test-fingerprint",
            "relevant_test_owners": ["tests/test_astra_canonical_natural_lifecycle_v1.py"],
        }
        row = {
            "first_seen": "2026-09-01T23:37:01.943163Z",
            "last_seen": "2026-09-01T23:37:01.943163Z",
            "occurrence_count": 1,
            "duration_seconds": 0.0,
            "recovery_attempt_history": [],
            "worker_pid": 42,
        }
        package = monitor._repair_package(issue, row, {})
        self.assertEqual(package["owner_file"], "engine/paper_autopilot.py")
        self.assertEqual(package["owner_function"], "PaperAutopilot._refresh_authorized_lane_exit_pending")

    def test_unchanged_code_repair_evidence_is_not_reinvestigated(self):
        monitor = self._monitor()
        runtime = {"last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"}}
        calls: list[str] = []
        action = lambda: calls.append("repair") or {"status": "dispatched"}
        monitor.run_if_due(runtime_state=runtime, worker_state={}, actions={"REBUILD_CANONICAL_DISCOVERY_STATE": action})
        self._force_due(monitor)
        monitor.run_if_due(runtime_state=runtime, worker_state={}, actions={"REBUILD_CANONICAL_DISCOVERY_STATE": action})
        self._force_due(monitor)
        result = monitor.run_if_due(runtime_state=runtime, worker_state={}, actions={"REBUILD_CANONICAL_DISCOVERY_STATE": action})
        self.assertEqual(calls, ["repair", "repair"])
        self.assertTrue(result["active_faults"][0]["recovery_suppressed"])
        self.assertEqual(result["active_faults"][0]["suppression_reason"], "UNCHANGED_CODE_REPAIR_EVIDENCE")
        self.assertEqual(result["active_faults"][0]["repair_attempt_count"], 2)

    def test_verified_repair_rechecks_and_surfaces_next_blocker(self):
        monitor = self._monitor()
        runtime = {
            "last_execution_trace": {"final_blocker_reason": "legacy_market_evidence_bounded"},
        }

        def rebuild():
            runtime["equity_discovery_rebuild_v1"] = {"candidate_source_available": True}
            runtime["astra_multilane_completion_matrix_v1"] = {
                "generated_at": _iso(-1),
                "lanes": {"SWING": {"stages": {"eligibility": {
                    "status": "FAIL_UNKNOWN_CLOSED",
                    "verification_state": "CURRENT",
                    "first_bad_handoff": "candidate contract -> eligibility gate",
                }}}},
            }
            return {"status": "rebuilt"}

        result = monitor.run_if_due(
            runtime_state=runtime,
            worker_state={},
            actions={"REBUILD_CANONICAL_DISCOVERY_STATE": rebuild},
            refresh_runtime=lambda: runtime,
        )
        self.assertEqual(result["recoveries"][0]["verification_result"], "RECOVERY_SUCCEEDED")
        self.assertEqual(result["autonomous_control_loop"]["next_blocker_by_lane"]["SWING"]["stage"], "QUALIFIED")
        self.assertEqual(result["active_faults"][0]["fault_type"], "ENTRY_FUNNEL_STAGE_BLOCKED")
        self.assertTrue(result["autonomous_control_loop"]["post_repair_truth_path_recheck"])

    def test_upstream_stale_candidate_wait_does_not_create_entry_source_package(self):
        monitor = self._monitor()
        runtime = {
            "last_execution_trace": {},
            "astra_multilane_completion_matrix_v1": {
                "generated_at": _iso(-1),
                "lanes": {"SWING": {
                    "first_blocker": "CANDIDATE_STALE",
                    "stages": {
                        "candidate_freshness": {
                            "status": "LEGITIMATE_WAITING",
                        },
                        "eligibility": {
                            "status": "FAIL_UNKNOWN_CLOSED",
                            "verification_state": "CURRENT",
                            "first_bad_handoff": "candidate contract -> eligibility gate",
                        },
                    },
                }},
            },
        }
        result = monitor.run_if_due(runtime_state=runtime, worker_state={})
        self.assertEqual(result["active_faults"], [])
        self.assertFalse(result["code_repair_required"])
        self.assertEqual(result["lane_readiness"]["SWING"], "TECHNICALLY_READY")

    def test_recurrent_fault_is_persisted_and_scorecard_is_bounded(self):
        monitor = self._monitor()
        runtime = {
            "last_execution_trace": {},
            "astra_multilane_completion_matrix_v1": {
                "generated_at": _iso(-1),
                "lanes": {"SWING": {"stages": {"eligibility": {
                    "status": "FAIL_UNKNOWN_CLOSED",
                    "verification_state": "CURRENT",
                    "first_bad_handoff": "candidate contract -> eligibility gate",
                }}}},
            },
        }
        result = monitor.run_if_due(runtime_state=runtime, worker_state={})
        for _ in range(2):
            self._force_due(monitor)
            result = monitor.run_if_due(runtime_state=runtime, worker_state={})
        fault = result["active_faults"][0]
        self.assertEqual(fault["occurrence_count"], 3)
        self.assertEqual(fault["recurrent_failure"], "RECURRENT_CANONICAL_INTEGRITY_FAILURE")
        self.assertEqual(result["code_repair_packages"][0]["recurrence_count"], 3)
        self.assertEqual(len(result["daily_scorecards"]), 1)
        self.assertEqual(result["daily_scorecard"]["lanes"]["DAY"]["current_readiness"], "TECHNICALLY_READY")
        self.assertEqual(result["daily_scorecard"]["lanes"]["SWING"]["current_readiness"], "DEGRADED")


if __name__ == "__main__":
    unittest.main()
