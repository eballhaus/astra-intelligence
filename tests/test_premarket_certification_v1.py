from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from engine.astra_premarket_certification_v1 import (
    build_lane_certification,
    build_pretrade_decision_contract,
    build_runtime_certification_v1,
    current_runtime_revision,
    deterministic_failure_injection_summary,
    runtime_module_identity_v1,
)
from engine.paper_autopilot import normalize_operational_candidate
import server_extend


def qualifying_candidate(**overrides):
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    candidate = {
        "candidate_id": "cand-test", "recommendation_id": "rec-test", "symbol": "TEST",
        "lane_id": "SWING", "strategy_archetype": "momentum_breakout", "trade_style": "swing_trade",
        "score": 82.0, "ranking_factors": ["momentum"], "thesis": "Momentum remains supported.",
        "thesis_supporting_conditions": ["trend"], "thesis_invalidation_conditions": ["trend_break"],
        "intended_horizon": "swing_trade", "expected_hold_window": "1d-5d",
        "expected_return_range": {"low": 1.0, "high": 3.0}, "expected_downside_range": {"low": -2.0, "high": -1.0},
        "expected_drawdown": -2.0, "expected_return_per_day_range": {"low": 0.2, "high": 0.6},
        "entry_conditions": ["session_confirmed"], "hold_conditions": ["thesis_intact"],
        "profit_protection_conditions": ["giveback"], "exit_review_conditions": ["horizon_expired"],
        "controlled_loss_conditions": ["thesis_broken"], "replacement_review_conditions": ["better_eligible_candidate"],
        "monitoring_priorities": ["thesis_and_horizon"],
        "confidence": 82.0, "evidence_classes": ["REPLAY_SUPPORTED"],
        "certification_snapshot_id": "premarket-test", "expires_at": future,
    }
    candidate.update(overrides)
    return candidate


class PreMarketCertificationContractTests(unittest.TestCase):
    @staticmethod
    def _runtime_fixture(**overrides):
        now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
        stamp = now.isoformat().replace("+00:00", "Z")
        worker = {
            "active_worker_present": True, "active_worker_pid": 20,
            "last_known_worker_pid": 19, "process_role": "PAPER_AUTOPILOT_WORKER",
            "heartbeat_at": stamp, "cycle_count": 12, "cycle_state": "COMPLETE",
            "last_cycle_completed_at": stamp, "resource_state": "RESOURCE_NORMAL",
            "runtime_revision": "rev-1", "worker_revision": "rev-1",
        }
        readiness = {
            "generated_at": stamp,
            "session": {"equity_session_open": False, "preopen_window": False, "check_phase": "CRYPTO_CONTINUOUS_CHECK"},
            "discovery_integrity": "READY", "position_management_integrity": "READY",
            "strict_truth_integrity": "READY", "crypto_lifecycle_integrity": "READY",
            "active_faults": [], "recoveries": [], "truth_production_watchdog": {"lanes": {}},
        }
        runtime = {
            "active_equity_fmp_observations_v1": {"canonical_active_equity_symbols": [], "observations": {}},
            "crypto_operational_integrity_readiness_v1": {"status": "PAPER_READY"},
            "last_evidence_capacity_snapshot": {},
        }
        backend = {"ok": True, "runtime_revision": "rev-1"}
        return now, worker, runtime, readiness, backend, overrides

    def test_current_runtime_certifies_without_production_mutation(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertEqual(result["certification_state"], "TECHNICALLY_CERTIFIED")
        self.assertTrue(result["runtime_certified"])
        self.assertTrue(result["restart_survivability_certified"])
        self.assertEqual(result["production_truths_created"], 0)
        self.assertEqual(result["broker_orders_created"], 0)
        self.assertFalse(result["production_state_mutated"])

    def test_revision_mismatch_is_not_ready(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        worker["runtime_revision"] = "old-rev"
        worker["worker_revision"] = "old-rev"
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", now=now,
        )
        self.assertEqual(result["revision_status"], "RUNTIME_REVISION_MISMATCH")
        self.assertFalse(result["runtime_certified"])
        self.assertNotEqual(result["certification_state"], "TECHNICALLY_CERTIFIED")

    def test_current_governance_module_identity_is_canonical(self):
        identity = runtime_module_identity_v1(
            canonical_repo_root=Path(__file__).resolve().parents[1],
            reported_revision=current_runtime_revision(),
        )
        self.assertEqual(identity["status"], "MATCHED")
        self.assertTrue(identity["module_path_matches"])
        self.assertTrue(identity["source_hash_matches"])
        self.assertEqual(identity["loaded_invariants_code_names"], ["_integer"])

    def test_revision_match_alone_cannot_hide_wrong_loaded_module(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        identity = {
            "status": "RUNTIME_SOURCE_IDENTITY_MISMATCH",
            "failure_reason": "MODULE_PATH_NONCANONICAL",
        }
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", runtime_identity=identity, now=now,
        )
        self.assertFalse(result["runtime_certified"])
        self.assertFalse(result["checks"]["runtime"]["passed"])
        self.assertIn("MODULE_PATH_NONCANONICAL", result["next_recheck_reason"])
        self.assertNotEqual(result["certification_state"], "TECHNICALLY_CERTIFIED")

    def test_duplicate_source_path_is_detected_even_with_matching_revision(self):
        identity = runtime_module_identity_v1(
            canonical_repo_root=Path(__file__).resolve().parents[1],
            reported_revision=current_runtime_revision(),
            module=SimpleNamespace(__file__="/tmp/astra-duplicate/engine/astra_continuous_governance_v1.py"),
        )
        self.assertEqual(identity["status"], "RUNTIME_SOURCE_IDENTITY_MISMATCH")
        self.assertIn("MODULE_PATH_NONCANONICAL", identity["failure_reason"])
        self.assertIn("MODULE_SOURCE_HASH_MISMATCH", identity["failure_reason"])

    def test_natural_no_opportunity_is_not_a_code_repair(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        readiness["truth_production_watchdog"] = {"lanes": {"DAY": {"technical_truth_starvation_status": "NATURAL_NO_QUALIFYING_ENTRY"}}}
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertEqual(result["certification_state"], "NATURAL_WAIT")
        self.assertEqual(result["current_code_repair_required"], [])
        self.assertTrue(result["entry_funnel_certified"])

    def test_insufficient_candidate_evidence_does_not_become_entry_code_fault(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        readiness["active_faults"] = [{
            "fault_type": "ENTRY_FUNNEL_STAGE_BLOCKED", "classification": "INSUFFICIENT_EVIDENCE",
            "lanes": ["DAY"], "earliest_stage": "QUALIFIED",
        }]
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertTrue(result["entry_funnel_certified"])
        self.assertEqual(result["current_code_repair_required"], [])

    def test_current_code_fault_is_separate_from_historical_packages(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        readiness["active_faults"] = [{
            "fault_type": "RUNTIME_REVISION_MISMATCH", "classification": "CODE_REPAIR_REQUIRED",
            "lanes": ["DAY"], "earliest_stage": "RUNTIME", "owner_file": "engine/start.py",
            "owner_function": "start", "verification_result": "CODE_REPAIR_REQUIRED",
        }]
        readiness["code_repair_packages"] = [{"fault_code": "OLD_HISTORICAL_FAULT"}]
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertEqual(result["certification_state"], "CODE_REPAIR_REQUIRED")
        self.assertEqual(len(result["current_code_repair_required"]), 1)
        self.assertEqual(result["current_code_repair_required"][0]["fault_type"], "RUNTIME_REVISION_MISMATCH")

    def test_external_fault_is_not_promoted_to_code_repair(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        readiness["active_faults"] = [{
            "fault_type": "RECONCILIATION_FAILURE", "classification": "BROKER_EXTERNAL",
            "lanes": ["DAY"], "earliest_stage": "RECONCILIATION",
        }]
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertEqual(result["certification_state"], "DEGRADED_EXTERNAL")
        self.assertEqual(result["current_code_repair_required"], [])
        self.assertEqual(result["current_external_blockers"][0]["classification"], "BROKER_EXTERNAL")

    def test_fresh_active_observation_and_restart_are_required(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        stamp = now.isoformat().replace("+00:00", "Z")
        runtime["active_equity_fmp_observations_v1"] = {
            "canonical_active_equity_symbols": ["GEHC"],
            "observations": {"GEHC": {"symbol": "GEHC", "provider_native_timestamp": stamp}},
        }
        runtime["alpaca_ws_active_position_monitor_v1"] = {
            "transport_health": "HEALTHY", "auth_state": "AUTHENTICATED",
            "subscription_state": "SUBSCRIBED", "subscribed_symbols": ["GEHC"],
            "messages_received": 1,
        }
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertTrue(result["observation_certified"])
        self.assertTrue(result["management_certified"])
        self.assertTrue(result["restart_survivability_certified"])

    def test_crypto_certification_does_not_depend_on_equity_observation(self):
        now, worker, runtime, readiness, backend, _ = self._runtime_fixture()
        runtime["active_equity_fmp_observations_v1"] = {"canonical_active_equity_symbols": ["GEHC"], "observations": {}}
        result = build_runtime_certification_v1(
            worker_state=worker, runtime_state=runtime, readiness=readiness,
            backend_health=backend, expected_revision="rev-1", worker_revision="rev-1",
            backend_revision="rev-1", now=now,
        )
        self.assertTrue(result["crypto_path_certified"])
        self.assertFalse(result["checks"]["observation"]["equity_evidence_expected"])
    def test_complete_contract_is_order_ready_eligible(self):
        contract = build_pretrade_decision_contract(qualifying_candidate())
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["order_ready_allowed"])

    def test_existing_ranking_evidence_is_normalized_into_a_complete_forward_plan(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        normalized = normalize_operational_candidate({
            "symbol": "PLAN", "asset_class": "equity", "action": "buy", "confidence": 82.0,
            "astra_composite_score": 73.0, "paper_entry_horizon_style": "day_trade",
            "summary": "PLAN is ranked from the existing candidate snapshot.",
            "ranked_reason": "Existing probability-adjusted ranking evidence.",
            "expected_return_low_pct": 2.0, "expected_return_high_pct": 6.0,
            "expected_return_pct": 4.0, "price": 100.0, "stop_loss": 96.0,
            "expected_target_low": 102.0, "expected_target_high": 106.0,
            "drawdown_risk_score": 25.0, "atr_pct": 1.5, "recommended_entry_mode": "wait_for_confirmation",
            "sell_reason": "no_confirmed_exit_signal", "candidate_generated_at": future,
            "expires_at": future, "certification_snapshot_id": "premarket-test",
        })
        contract = build_pretrade_decision_contract(normalized)
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["candidate_id"])
        self.assertTrue(contract["expected_return_range"])
        self.assertTrue(contract["hold_conditions"])
        self.assertIn("CURRENT_CANDIDATE_DIRECT", contract["evidence_classes"])

    def test_missing_thesis_fails_closed(self):
        contract = build_pretrade_decision_contract(qualifying_candidate(thesis=""))
        self.assertEqual(contract["contract_status"], "INVALID")
        self.assertIn("thesis", contract["missing_required_fields"])
        self.assertFalse(contract["order_ready_allowed"])

    def test_missing_horizon_fails_closed(self):
        contract = build_pretrade_decision_contract(qualifying_candidate(
            intended_horizon="", paper_entry_horizon_style="", trade_style="", strategy_archetype="unsupported_strategy",
        ))
        self.assertIn("intended_horizon", contract["missing_required_fields"])

    def test_expired_contract_fails_closed(self):
        expired = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        contract = build_pretrade_decision_contract(qualifying_candidate(expires_at=expired))
        self.assertIn("expired_contract", contract["conflicting_fields"])

    def test_empty_lane_reports_ready_no_trade_without_fixture_truth(self):
        result = build_lane_certification(
            "DAY", activation={"exact_blockers": ["LANE_NOT_ENABLED"]}, dry_run={}, contracts=[],
            production_commit="test", snapshot_id="snapshot",
        )
        self.assertEqual(result["status"], "READY_NO_TRADE")
        self.assertEqual(result["exact_blocker"], "NO_CURRENT_ELIGIBLE_DAY_CANDIDATE")
        self.assertEqual(result["fixture_truths_created"], 0)
        self.assertEqual(result["residual_fixture_orders"], 0)

    def test_lane_certification_attributes_missing_contract_evidence(self):
        contract = build_pretrade_decision_contract({"symbol": "NVDA", "lane": "DAY"})
        result = build_lane_certification(
            "DAY", activation={}, dry_run={"per_candidate_decision_trace": []}, contracts=[contract],
            production_commit="test", snapshot_id="snapshot",
        )
        self.assertEqual(result["status"], "CONTRACT_INCOMPLETE")
        self.assertGreater(result["missing_contract_field_counts"].get("thesis", 0), 0)
        self.assertEqual(result["contract_evidence_samples"][0]["symbol"], "NVDA")

    def test_failure_injection_coverage_is_complete_and_non_mutating(self):
        coverage = deterministic_failure_injection_summary()
        self.assertEqual(coverage["total_cases"], 32)
        self.assertTrue(all(row["broker_actions_used"] == 0 for row in coverage["cases"]))

    def test_cold_status_cache_uses_existing_read_only_paper_safety_fallback(self):
        fallback = {
            "paper_mode_verified": True,
            "broker_live_endpoint_allowed": False,
            "broker_execution_enabled": True,
            "broker_actions_used": 0,
        }
        with patch.object(server_extend, "_cached_alpaca_paper_status_payload", return_value={}), patch.object(
            server_extend, "_alpaca_paper_status_fast_fallback_v1", return_value=fallback
        ) as fast_fallback:
            snapshot = server_extend._pretrade_certification_broker_snapshot_v1()
        self.assertTrue(snapshot["paper_mode_verified"])
        self.assertFalse(snapshot["broker_live_endpoint_allowed"])
        self.assertEqual(snapshot["broker_actions_used"], 0)
        fast_fallback.assert_called_once_with("pretrade_certification_status_cache_cold")


if __name__ == "__main__":
    unittest.main()
