from __future__ import annotations

import tempfile
import unittest

from engine.astra_operating_health_contract_v1 import AstraOperatingHealthContractV1


class OperatingHealthContractTests(unittest.TestCase):
    def test_strict_truth_is_consumed_once_and_lane_truth_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            contract = AstraOperatingHealthContractV1(root)
            payload = contract.build(
                multilane={"lanes": {"CRYPTO": {"current_stage": "lifecycle_closure", "first_blocker": "", "candidate_count": 1, "paper_order_intents": 0}}},
                worker_state={}, continuous={"status": "PASS"}, sentinel={"status": "PASS"}, cortex={"status": "PASS"},
                truth_records=[{"strict_broker_truth": True, "truth_id": "truth-1", "lifecycle_id": "life-1", "lane": "CRYPTO", "symbol": "BTC/USD", "entry_fill_id": "in", "exit_fill_id": "out"}],
                learning_records=[{"truth_id": "truth-1"}],
            )
            self.assertEqual(payload["lanes"]["CRYPTO"]["strict_truth_count"], 1)
            self.assertEqual(payload["lanes"]["CRYPTO"]["truths_consumed_by_learning"], 1)
            self.assertTrue(payload["lanes"]["CRYPTO"]["cortex_acknowledged"])
            self.assertEqual(payload["truth_to_learning_ledger"][0]["final_state"], "CONSUMED")

    def test_open_or_partial_records_are_not_counted_as_strict_truth(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={},
                truth_records=[{"lifecycle_id": "open", "lane": "DAY", "symbol": "AAPL", "entry_fill_id": "in"}],
            )
            self.assertEqual(payload["strict_truth_total"], 0)

    def test_scalp_is_a_canonical_operating_health_lane(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"SCALP": {"current_stage": "position_monitoring", "first_blocker": "MARKET_CLOSED"}}},
                worker_state={}, continuous={}, sentinel={},
            )
            self.assertIn("SCALP", payload["lanes"])
            self.assertEqual(payload["lanes"]["SCALP"]["current_lifecycle_stage"], "position_monitoring")

    def test_valid_duplicate_exposure_is_not_misclassified_as_a_software_defect(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"SCALP": {
                    "first_blocker": "duplicate_active_position",
                    "first_blocker_validity": "VALID_SAFETY_REJECTION",
                }}},
                worker_state={}, continuous={}, sentinel={},
            )
            scalp = payload["lanes"]["SCALP"]
            self.assertEqual(scalp["blocker_validity"], "VALID_SAFETY_REJECTION")
            self.assertEqual(scalp["waiting_state"], "LEGITIMATE_WAIT")

    def test_stale_provider_timestamp_is_a_legitimate_market_data_wait(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"SWING": {
                    "first_blocker": "CANDIDATE_STALE",
                    "first_blocker_validity": "VALID_MARKET_DATA_LIMITATION",
                }}},
                worker_state={}, continuous={}, sentinel={},
            )
            swing = payload["lanes"]["SWING"]
            self.assertEqual(swing["blocker_validity"], "VALID_MARKET_DATA_LIMITATION")
            self.assertEqual(swing["waiting_state"], "LEGITIMATE_WAIT")

    def test_authoritative_crypto_reserve_exhaustion_is_a_valid_capacity_wait(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"CRYPTO": {"first_blocker": "capacity_concentration"}}},
                worker_state={}, continuous={}, sentinel={},
                canonical_capacity_facts={"CRYPTO": {
                    "authority_current": True, "allowed": False,
                    "capacity_decision": "LANE_RESERVE_EXHAUSTED",
                    "lane_reserve_status": "LANE_RESERVE_EXHAUSTED",
                    "reserve_available": False, "positions_used": 2, "positions_remaining": 0,
                }},
            )
            crypto = payload["lanes"]["CRYPTO"]
            self.assertEqual(crypto["blocker_validity"], "VALID_CAPACITY_WAIT")
            self.assertEqual(crypto["waiting_state"], "LEGITIMATE_WAIT")

    def test_capacity_gate_remains_fail_closed_when_authority_is_allowed_or_ambiguous(self):
        with tempfile.TemporaryDirectory() as root:
            contract = AstraOperatingHealthContractV1(root)
            allowed = contract.build(
                multilane={"lanes": {"CRYPTO": {"first_blocker": "capacity_concentration"}}},
                worker_state={}, continuous={}, sentinel={},
                canonical_capacity_facts={"CRYPTO": {"authority_current": True, "allowed": True, "capacity_decision": "AVAILABLE"}},
            )
            unavailable = contract.build(
                multilane={"lanes": {"CRYPTO": {"first_blocker": "capacity_concentration"}}},
                worker_state={}, continuous={}, sentinel={},
                canonical_capacity_facts={"CRYPTO": {"authority_current": False, "allowed": False, "capacity_decision": "LANE_RESERVE_EXHAUSTED"}},
            )
            self.assertEqual(allowed["lanes"]["CRYPTO"]["blocker_validity"], "UNCLASSIFIED_FAIL_CLOSED")
            self.assertEqual(unavailable["lanes"]["CRYPTO"]["blocker_validity"], "UNCLASSIFIED_FAIL_CLOSED")

    def test_high_sentinel_root_prevents_false_control_plane_agreement(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"SWING": {"first_blocker": "CANDIDATE_TIMESTAMP_STALE"}}}, worker_state={}, continuous={"status": "PASS"},
                sentinel={"status": "WARNING", "active_root_causes": [{"severity": "HIGH", "category": "MARKET_DATA_STALE"}]},
            )
            self.assertEqual(payload["status"], "WARNING")
            self.assertFalse(payload["control_plane_agreement"])
            self.assertEqual(payload["lanes"]["SWING"]["waiting_state"], "LEGITIMATE_WAIT")

    def test_snapshot_is_read_only_and_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).snapshot()
            self.assertEqual(payload["status"], "AWAITING_WORKER_SNAPSHOT")
            self.assertTrue(payload["get_route_read_only"])
            self.assertEqual(payload["provider_calls_used"], 0)
            self.assertFalse(payload["behavior_safe_to_apply"])

    def test_handoff_ledger_uses_existing_timestamps_and_marks_missing_stages_unobserved(self):
        with tempfile.TemporaryDirectory() as root:
            truth = {
                "evidence_class": "BROKER_CONFIRMED_COMPLETE", "stable_key": "strict:in:out",
                "lifecycle_id": "life-1", "lane_id": "DAY", "symbol": "AAPL",
                "entry_fill_id": "in", "exit_fill_id": "out", "created_at": "2026-08-09T12:00:00Z",
                "learning_acknowledged": True,
            }
            learning = {
                "lifecycle_id": "life-1", "lesson_id": "lesson-1",
                "acknowledged_at": "2026-08-09T12:00:10Z",
                "created_at": "2026-08-09T12:00:20Z",
                "teacher_handoff_complete": True,
            }
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={},
                truth_records=[truth], learning_records=[learning],
            )
            ledger = payload["truth_to_learning_ledger"][0]
            stages = {row["stage"]: row for row in ledger["stages"]}
            self.assertEqual(payload["lanes"]["DAY"]["strict_truth_count"], 1)
            self.assertEqual(stages["learning_acknowledged"]["latency_from_previous_seconds"], 10.0)
            self.assertEqual(stages["canonical_lesson_compressed"]["latency_from_previous_seconds"], 10.0)
            self.assertEqual(stages["teacher_handoff"]["status"], "ACKNOWLEDGED_TIMESTAMP_UNOBSERVED")
            self.assertEqual(ledger["first_delayed_or_unobserved_handoff"], "teacher_handoff")
            self.assertEqual(stages["memory_index_available"]["status"], "UNKNOWN_UNOBSERVED")

    def test_authoritative_trade_journal_ack_clears_learning_wait_without_lesson_application(self):
        with tempfile.TemporaryDirectory() as root:
            truth = {
                "evidence_class": "BROKER_CONFIRMED_COMPLETE", "stable_key": "strict:in:out",
                "lifecycle_id": "life-1", "lane_id": "DAY", "symbol": "AAPL",
                "entry_fill_id": "in", "exit_fill_id": "out", "created_at": "2026-08-09T12:00:00Z",
            }
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={},
                truth_records=[truth], learning_records=[{
                    "truth_id": "strict:in:out", "lifecycle_id": "life-1", "lane_id": "DAY",
                    "consumption_result": "CONSUMED", "consumer": "TradeIntelligenceEngine.record_trade",
                    "source": "trade_journal", "provenance": "broker_truth_records_v1 -> trade_journal",
                }],
            )
            self.assertEqual(payload["lanes"]["DAY"]["truths_consumed_by_learning"], 1)
            self.assertEqual(payload["truth_to_learning_ledger"][0]["final_state"], "CONSUMED")
            self.assertEqual(payload["truth_to_learning_ledger"][0]["consumer"], "canonical_lifecycle_learning")

    def test_learning_utilization_uses_existing_records_without_claiming_missing_outcomes(self):
        with tempfile.TemporaryDirectory() as root:
            truth = {
                "evidence_class": "BROKER_CONFIRMED_COMPLETE", "stable_key": "strict:in:out",
                "lifecycle_id": "life-1", "lane_id": "DAY", "symbol": "AAPL",
                "entry_fill_id": "in", "exit_fill_id": "out", "created_at": "2026-08-09T12:00:00Z",
            }
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={}, truth_records=[truth],
                learning_records=[{
                    "truth_id": "strict:in:out", "lesson_id": "lesson-1",
                    "lesson_retrieved": True, "lesson_retrieved_at": "2026-08-09T12:01:00Z",
                    "lesson_applied": True, "lesson_applied_at": "2026-08-09T12:02:00Z",
                    "later_outcome_linked": True, "later_outcome_linked_at": "2026-08-09T12:03:00Z",
                    "effectiveness_evaluated": True, "effectiveness_evaluated_at": "2026-08-09T12:04:00Z",
                }],
            )
            ledger = payload["truth_to_learning_ledger"][0]
            self.assertEqual(ledger["utilization_state"], "EFFECTIVENESS_EVALUATED")
            self.assertEqual(payload["learning_utilization_summary"]["states"]["EFFECTIVENESS_EVALUATED"], 1)


if __name__ == "__main__":
    unittest.main()
