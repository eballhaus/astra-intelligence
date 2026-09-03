from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from engine.astra_historical_truth_certification_v1 import (
    AstraHistoricalTruthCertificationV1,
    build_code_repair_required_package,
    build_historical_truth_certification_v1,
    certification_trigger_allowed,
    certify_lifecycle,
    runtime_repair_action_allowed,
)


def _truth(lifecycle_id: str = "life-1", lane: str = "DAY", **extra):
    row = {
        "evidence_class": "BROKER_CONFIRMED_COMPLETE",
        "truth_quality": "BROKER_CONFIRMED_COMPLETE",
        "truth_state": "BROKER_TRUTH_CONFIRMED",
        "natural_trade_label": f"NATURAL_PAPER_{lane}_EQUITY",
        "paper_mode_verified": True,
        "lifecycle_id": lifecycle_id,
        "lane_id": lane,
        "symbol": "ABC",
        "entry_order_id": f"entry-order-{lifecycle_id}",
        "entry_fill_id": f"entry-fill-{lifecycle_id}",
        "entry_timestamp": "2026-08-20T13:00:00Z",
        "entry_price": 100.0,
        "entry_quantity": 1.0,
        "exit_order_id": f"exit-order-{lifecycle_id}",
        "exit_fill_id": f"exit-fill-{lifecycle_id}",
        "exit_timestamp": "2026-08-20T14:00:00Z",
        "exit_price": 101.0,
        "exit_filled_quantity": 1.0,
        "broker_residual_zero_confirmed": True,
        "learning_acknowledged": True,
        "realized_return": 1.0,
    }
    row.update(extra)
    return row


class HistoricalTruthCertificationTests(unittest.TestCase):
    def _learning_db(self, root: Path, lifecycle_id: str) -> None:
        conn = sqlite3.connect(root / "ai_trading_memory.db")
        conn.execute("CREATE TABLE trade_journal (trade_id TEXT PRIMARY KEY, lifecycle_id TEXT, lane_id TEXT, symbol TEXT)")
        conn.execute("INSERT INTO trade_journal VALUES (?,?,?,?)", (lifecycle_id, lifecycle_id, "DAY", "ABC"))
        conn.commit()
        conn.close()

    def test_valid_historical_day_lifecycle_certifies_and_reads_learning_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            truth = _truth()
            (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": [truth]}), encoding="utf-8")
            self._learning_db(root, "life-1")
            result = build_historical_truth_certification_v1(root, current_commit="test", persist=True)
            self.assertEqual(result["lanes"]["DAY"]["status"], "CERTIFIED")
            self.assertEqual(result["lanes"]["DAY"]["natural_truths_certified"], 1)
            self.assertEqual(result["certifications"][0]["learning_ack_status"], "ACKNOWLEDGED")
            self.assertEqual(result["safety"]["production_truth_rows_created"], 0)
            self.assertEqual(result["safety"]["production_learning_rows_created"], 0)
            self.assertTrue((root / "astra_historical_truth_certification_v1.json").exists())

    def test_missing_learning_ack_is_explicit_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = certify_lifecycle(_truth(), state_dir=root, learning_rows={})
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORICAL_EVIDENCE")
        self.assertEqual(result["first_failing_stage"], "learning_acknowledgment")
        self.assertEqual(result["learning_ack_status"], "NOT_OBSERVED")

    def test_stale_management_observation_fails_closed_and_preserves_native_time_contract(self):
        row = _truth(
            management_evidence={
                "provider": "alpaca",
                "lifecycle_id": "life-1",
                "provider_native_timestamp": "2026-08-20T13:59:00Z",
                "receive_timestamp": "2026-08-20T13:59:01Z",
                "freshness_state": "STALE",
            }
        )
        result = certify_lifecycle(row, learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["first_failing_stage"], "management_evidence")
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORICAL_EVIDENCE")
        stage = result["certification_stage_results"][1]
        self.assertTrue(stage["evidence"]["provider_native_timestamp_present"])
        self.assertTrue(stage["evidence"]["receive_timestamp_present"])

    def test_ambiguous_residual_remains_explicitly_blocked(self):
        row = _truth(
            broker_residual_zero_confirmed=False,
            reconciliation_status="EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION",
        )
        result = certify_lifecycle(row, learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["status"], "EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION")
        self.assertEqual(result["first_failing_stage"], "reconciliation")

    def test_replay_never_counts_as_truth_or_learning(self):
        row = _truth(source="replay_counterfactual_learning_v2", natural_trade_label="NATURAL_PAPER_DAY_EQUITY")
        result = certify_lifecycle(row, source_evidence_type="REPLAY_COUNTERFACTUAL", learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["status"], "INSUFFICIENT_HISTORICAL_EVIDENCE")
        self.assertEqual(result["classification"], "REPLAY_NOT_PRODUCTION_EVIDENCE")
        self.assertEqual(result["learning_ack_status"], "NOT_OBSERVED")

    def test_fixture_certifies_technical_path_without_production_truth(self):
        row = _truth(
            lifecycle_id="fixture-scalp",
            lane="SCALP",
            source="technical_path_fixture",
            natural_trade_label="",
            management_evidence={
                "provider": "fixture-recorded-contract",
                "lifecycle_id": "fixture-scalp",
                "provider_native_timestamp": "2026-08-20T13:59:00Z",
                "receive_timestamp": "2026-08-20T13:59:01Z",
                "freshness_state": "CURRENT",
            },
        )
        result = certify_lifecycle(row, source_evidence_type="TECHNICAL_PATH_FIXTURE")
        self.assertEqual(result["status"], "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING")
        self.assertEqual(result["natural_truth_status"], "NATURAL_TRUTH_PENDING")
        self.assertEqual(result["learning_ack_status"], "CONTRACT_ONLY_NO_PRODUCTION_WRITE")

    def test_swing_and_crypto_fixtures_are_lane_specific_and_nonproduction(self):
        fixtures = {}
        for lane in ("SWING", "CRYPTO"):
            fixtures[lane] = [_truth(
                lifecycle_id=f"fixture-{lane.lower()}",
                lane=lane,
                source="technical_path_fixture",
                natural_trade_label="",
                management_evidence={
                    "provider": "fixture-recorded-contract",
                    "lifecycle_id": f"fixture-{lane.lower()}",
                    "provider_native_timestamp": "2026-08-20T13:59:00Z",
                    "receive_timestamp": "2026-08-20T13:59:01Z",
                    "freshness_state": "CURRENT",
                },
            )]
        with tempfile.TemporaryDirectory() as directory:
            result = build_historical_truth_certification_v1(directory, fixtures=fixtures, persist=False)
        for lane in ("SWING", "CRYPTO"):
            self.assertEqual(result["lanes"][lane]["status"], "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING")
            self.assertEqual(result["lanes"][lane]["natural_truths_certified"], 0)
            self.assertEqual(result["lanes"][lane]["technical_path_certifications"], 1)

    def test_certification_trigger_model_is_bounded_and_explicit(self):
        self.assertTrue(certification_trigger_allowed("EXPLICIT_MANUAL_REQUEST"))
        self.assertTrue(certification_trigger_allowed("TRUTH_STARVATION"))
        self.assertFalse(certification_trigger_allowed("EVERY_WORKER_CYCLE"))
        self.assertTrue(AstraHistoricalTruthCertificationV1("state").should_run("CODE_REPAIR_DEPLOYED"))

    def test_missing_entry_or_exit_identity_fails_closed(self):
        entry_missing = _truth(entry_fill_id="")
        result = certify_lifecycle(entry_missing, learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["first_failing_stage"], "entry_identity")
        exit_missing = _truth(exit_fill_id="")
        result = certify_lifecycle(exit_missing, learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["first_failing_stage"], "exit_evidence")

    def test_wrong_reconciliation_identity_fails_closed(self):
        row = _truth(reconciliation={"lifecycle_id": "different-life", "exit_fill_id": "different-fill"})
        result = certify_lifecycle(row, learning_rows={"life-1": {"trade_id": "life-1"}})
        self.assertEqual(result["first_failing_stage"], "reconciliation")
        self.assertEqual(result["certification_stage_results"][3]["failure"], "RECONCILIATION_IDENTITY_MISMATCH")

    def test_runtime_repair_is_limited_and_source_defect_is_package_only(self):
        self.assertTrue(runtime_repair_action_allowed("RECONNECT_ALPACA_WS"))
        self.assertFalse(runtime_repair_action_allowed("EDIT_SOURCE"))
        package = build_code_repair_required_package(
            fault_code="CERTIFICATION_CONTRACT_FAILURE",
            lane="SWING",
            lifecycle_id="life-2",
            first_failing_stage="reconciliation",
            failing_invariant="TARGET_LIFECYCLE_RECONCILES",
            expected_contract="target lifecycle identity is preserved",
            actual_contract="fill identity is mismatched",
            evidence_fingerprint="fp-1",
            owner_file="engine/paper_autopilot.py",
            owner_function="reconcile_position",
            smallest_repair_scope="preserve lifecycle identity in reconciliation mapping",
            relevant_test_owners=["tests/test_broker_truth_reconciliation_contract.py"],
            current_commit="test",
        )
        self.assertEqual(package["status"], "CODE_REPAIR_REQUIRED")
        self.assertFalse(package["source_code_self_modification"])

    def test_no_duplicate_production_mutation_and_lane_specific_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broker_truth_records_v1.json").write_text(json.dumps({"records": [_truth()]}), encoding="utf-8")
            result = AstraHistoricalTruthCertificationV1(root).certify(persist=False)
        self.assertEqual(set(result["lanes"]), {"DAY", "SCALP", "SWING", "CRYPTO"})
        self.assertFalse(result["learning_contract"]["production_write_attempted"])
        self.assertEqual(result["safety"]["broker_actions_used"], 0)
        self.assertEqual(result["readiness_integration"]["trade_authority"], False)


if __name__ == "__main__":
    unittest.main()
