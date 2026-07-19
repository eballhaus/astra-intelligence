from __future__ import annotations

import os
import tempfile
import unittest

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_safe_correction_registry_v1 import SafeCorrectionRegistryV1
from engine.astra_sentinel_integration_v1 import sentinel_integrity_payload_v1, sentinel_legacy_inventory_v1


class SentinelGovernanceCortexCryptoCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.scanner = ContinuousSystemIntegrityScannerV1(self.temp.name)

    def _scan(self, **context):
        return self.scanner.run_if_due(
            worker_state={"process_role": "PAPER_AUTOPILOT_WORKER", "resource_state": "RESOURCE_NORMAL"},
            runtime_state={}, safety={"paper_mode_verified": True}, context=context,
        )

    def test_legacy_sentinel_inventory_has_no_competing_owner(self):
        rows = sentinel_legacy_inventory_v1()
        self.assertTrue(any(row["status"] == "DEPRECATED_DISABLED" for row in rows))
        self.assertTrue(any(row["status"] == "RETAINED_OPERATIONAL_WATCHDOG" for row in rows))
        self.assertFalse(any(row.get("repair_authority") == "ACTIVE" for row in rows))

    def test_sentinel_adapter_uses_one_committed_scanner_snapshot(self):
        snapshot = self._scan()
        before = os.stat(self.scanner.summary_path).st_mtime_ns
        sentinel = sentinel_integrity_payload_v1(self.scanner.snapshot())
        self.assertEqual(before, os.stat(self.scanner.summary_path).st_mtime_ns)
        self.assertEqual(sentinel["sentinel_owner"], "canonical_worker")
        self.assertEqual(sentinel["scan_engine"], "astra_continuous_system_integrity_scanner_v1")
        self.assertEqual(sentinel["provider_calls_used"], 0)
        self.assertFalse(sentinel["behavior_safe_to_apply"])
        self.assertEqual(snapshot["scan_owner"], "canonical_worker")

    def test_provider_absence_is_waiting_not_code_defect(self):
        snapshot = self._scan(crypto_ranking_snapshot={"generated_at": "2026-07-19T00:00:00Z", "crypto_quote_integrity_rows": [{"symbol": "LINK/USD", "quote_received": False, "failure_reason": "FRESH_QUOTE_UNAVAILABLE"}]})
        self.assertEqual(snapshot["crypto_market_data"]["pair_observability"]["LINK/USD"]["quote_observability_state"], "PROVIDER_DATA_UNAVAILABLE")
        self.assertFalse(snapshot["active_root_causes"])
        self.assertTrue(any(row.get("classification") == "PROVIDER_DATA_UNAVAILABLE" for row in snapshot["legitimate_waiting_states"]))

    def test_dropped_provider_bid_ask_is_one_crypto_root_cause(self):
        snapshot = self._scan(crypto_ranking_snapshot={"crypto_quote_integrity_rows": [{"symbol": "LINK/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1, "bid_present": False, "ask_present": False, "spread_present": False}]})
        roots = snapshot["active_root_causes"]
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]["category"], "FIELD_DROPPED_DURING_TRANSFORMATION")
        self.assertEqual(roots[0]["finding_id"].split("-", 1)[0], "finding")
        self.assertEqual(roots[0]["governance_issue_id"], roots[0]["root_cause_id"])

    def test_guarded_level_two_requires_all_guards_and_rolls_back(self):
        registry = SafeCorrectionRegistryV1(self.temp.name)
        state = {"reader": "adapter"}
        transaction = registry.prepare_guarded("root-quote", "SWITCH_TO_REGISTERED_CANONICAL_READER", target_component="derived readiness", target_artifact="derived-only", before_state=dict(state), after_state={"reader": "canonical"}, confidence="VERIFIED", blast_radius={"known": True, "rollback_available": True, "canonical_facts_used": ["CURRENT_QUOTE_BID"]}, dry_run_passed=True)
        applied = registry.apply_guarded(transaction, governance_authorized=True, cortex_agreed=True, canary_passed=True, apply_callback=lambda: state.update(reader="canonical"))
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["verification_state"], "VERIFYING")
        rolled_back = registry.verify_guarded(applied["correction_id"], verification_passed=False, rollback_callback=lambda: state.update(reader="adapter"), max_failures=1)
        self.assertEqual(state["reader"], "adapter")
        self.assertTrue(rolled_back["automatic_correction_disabled"])
        self.assertEqual(rolled_back["verification_state"], "HUMAN_REPAIR_REQUIRED")

    def test_high_load_defers_without_running_scan(self):
        snapshot = self.scanner.run_if_due(worker_state={"process_role": "PAPER_AUTOPILOT_WORKER", "resource_state": "RESOURCE_NORMAL"}, runtime_state={}, safety={}, context={"order_processing_active": True})
        self.assertEqual(snapshot["scan_deferred"], "HIGH_LOAD_BACKOFF")
        self.assertEqual(snapshot["provider_calls_used"], 0)

    def test_crypto_safety_never_changes_execution(self):
        snapshot = self._scan(crypto_ranking_snapshot={"crypto_quote_integrity_rows": [{"symbol": "LTC/USD", "quote_received": True, "provider_bid": 10.0, "provider_ask": 10.1, "bid_present": True, "ask_present": True, "spread_present": True, "volume_available": True, "candidate_persisted": True}]})
        self.assertTrue(snapshot["paper_only_preserved"])
        self.assertFalse(snapshot["entry_behavior_changed"])
        self.assertFalse(snapshot["exit_behavior_changed"])
        self.assertFalse(snapshot["forced_trades_enabled"])


if __name__ == "__main__":
    unittest.main()
