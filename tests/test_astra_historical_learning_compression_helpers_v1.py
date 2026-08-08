from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.astra_historical_learning_compression_helpers_v1 import (
    adaptive_throughput_v1,
    profile_and_compress_partition_v1,
    warehouse_partition_references_v1,
)


SOURCE = {
    "source_identity": "candidate_decision_ledger",
    "path": "candidate_decision_ledger_v1.jsonl",
    "source_snapshot": "fixture:1",
}


def row(*, record_id: str | None = None, tier: str = "shadow", outcome: float | None = 1.25, symbol: str = "ABC") -> dict:
    result = {
        "symbol": symbol,
        "lane": "DAY",
        "horizon": "DAY",
        "regime": "RISK_ON",
        "archetype": "BREAKOUT",
    }
    if record_id:
        result["id"] = record_id
    if outcome is not None:
        result["realized_return_pct"] = outcome
    if tier == "strict":
        result["truth_state"] = "STRICT_TRUTH"
    elif tier == "operational":
        result["validated"] = True
    else:
        result["shadow"] = True
    return result


class HistoricalLearningCompressionHelpersV1Tests(unittest.TestCase):
    def test_equivalent_rows_compress_but_retain_raw_equivalent_count(self):
        result = profile_and_compress_partition_v1(SOURCE, "p1", [row(), row(), row()])
        self.assertEqual(result["partition_profile"]["profile_state"], "REDUNDANT_HEAVY")
        self.assertEqual(len(result["packets"]), 1)
        self.assertEqual(result["packets"][0]["raw_equivalent_count"], 3)
        self.assertEqual(result["representative_rows"][0]["_v10_compression_weight"], 3)
        self.assertEqual(result["compression_ratio"], 3.0)

    def test_non_equivalent_rows_do_not_merge(self):
        result = profile_and_compress_partition_v1(SOURCE, "p1", [row(outcome=1.0), row(outcome=-1.0)])
        self.assertEqual(len(result["packets"]), 2)
        self.assertEqual(result["compression_ratio"], 1.0)

    def test_evidence_tiers_are_never_compressed_together(self):
        result = profile_and_compress_partition_v1(SOURCE, "p1", [row(tier="strict"), row(tier="shadow")])
        self.assertEqual(len(result["packets"]), 2)
        tiers = {next(iter(packet["evidence_tier_counts"])) for packet in result["packets"]}
        self.assertIn("BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", tiers)
        self.assertIn("SHADOW_COUNTERFACTUAL", tiers)

    def test_packet_provenance_and_canonical_handoffs_are_preserved(self):
        result = profile_and_compress_partition_v1(SOURCE, "p1", [row(record_id="obs-1"), row(record_id="obs-1")])
        packet = result["packets"][0]
        self.assertEqual(packet["warehouse_source_identity"], "candidate_decision_ledger")
        self.assertEqual(packet["provenance_references"], ["obs-1", "obs-1"])
        self.assertEqual(result["canonical_compression_handoff"]["owner"], "Knowledge Compression Engine V1")
        self.assertEqual(result["canonical_teacher_handoff"]["owner"], "Teacher Layer V1")
        self.assertFalse(result["canonical_teacher_handoff"]["persisted"])

    def test_pending_outcome_links_later_without_duplicate_packet(self):
        first = profile_and_compress_partition_v1(SOURCE, "p1", [row(record_id="later", outcome=None)])
        self.assertIn("later", first["updated_registry"]["pending_outcomes"])
        second = profile_and_compress_partition_v1(SOURCE, "p2", [row(record_id="later", outcome=2.0)], first["updated_registry"])
        self.assertNotIn("later", second["updated_registry"]["pending_outcomes"])
        self.assertEqual(len(second["updated_registry"]["packets"]), 1)
        packet = next(iter(second["updated_registry"]["packets"].values()))
        self.assertEqual(packet["source_partition_ids"], ["p1", "p2"])

    def test_warehouse_manager_is_the_only_source_locator(self):
        root = Path(tempfile.mkdtemp())
        (root / "candidate_decision_ledger_v1.jsonl").write_text(json.dumps(row()) + "\n")
        references = warehouse_partition_references_v1(str(root), {"candidate_decision_ledger_v1.jsonl", "unknown.jsonl"})
        self.assertEqual([item["path"] for item in references], ["candidate_decision_ledger_v1.jsonl"])
        self.assertEqual(references[0]["source_identity"], "candidate_decision_ledger")

    def test_throughput_only_increases_after_healthy_checkpoints_and_pauses_for_trading(self):
        self.assertEqual(adaptive_throughput_v1({"healthy_successful_cycles": 0}, {"resource_state": "RESOURCE_NORMAL"})["mode"], "CONSERVATIVE")
        self.assertEqual(adaptive_throughput_v1({"healthy_successful_cycles": 3}, {"resource_state": "RESOURCE_NORMAL"})["mode"], "NORMAL")
        self.assertEqual(adaptive_throughput_v1({"healthy_successful_cycles": 6}, {"resource_state": "RESOURCE_NORMAL"})["mode"], "ACCELERATED")
        self.assertEqual(adaptive_throughput_v1({"healthy_successful_cycles": 9}, {"trading_priority_active": True})["mode"], "PAUSED")

    def test_safety_contract_has_no_external_or_execution_side_effects(self):
        result = profile_and_compress_partition_v1(SOURCE, "p1", [row()])
        self.assertEqual(result["full_history_scan_count"], 0)
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)
        self.assertEqual(result["llm_calls_added"], 0)
        self.assertFalse(result["execution_behavior_changed"])
        self.assertFalse(result["frozen_lifecycle_modified"])


if __name__ == "__main__":
    unittest.main()
