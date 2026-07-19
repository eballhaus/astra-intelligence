import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from engine.astra_multilane_activation_v2 import (
    adaptive_throughput,
    day_regular_session_allowed,
    lane_capital_status,
    lane_handoff_proof,
    operational_freshness,
    strict_broker_truth,
)
from engine.paper_autopilot import PaperAutopilotEngine


class MultilaneActivationV2ContractTests(unittest.TestCase):
    def test_operational_freshness_is_separate_from_quote_freshness(self):
        fresh = operational_freshness(43, {"ASTRA_OPERATIONAL_CANDIDATE_MAX_AGE_SECONDS": "300"})
        stale = operational_freshness(301, {"ASTRA_OPERATIONAL_CANDIDATE_MAX_AGE_SECONDS": "300"})
        self.assertEqual(fresh["candidate_snapshot_freshness"], "CURRENT")
        self.assertEqual(stale["candidate_snapshot_freshness"], "STALE")
        self.assertTrue(fresh["final_quote_freshness_separate"])

    def test_capital_requires_valid_configured_limit_inside_approval(self):
        self.assertEqual(lane_capital_status("DAY", {"ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000"})["capital_configuration_status"], "PASS")
        self.assertEqual(lane_capital_status("DAY", {"ASTRA_DAY_LANE_CAPITAL_LIMIT": "15001"})["capital_configuration_status"], "CAPITAL_LIMIT_EXCEEDS_APPROVAL")
        self.assertEqual(lane_capital_status("CRYPTO", {"ASTRA_CRYPTO_PAPER_CAPITAL_LIMIT": "0"})["capital_configuration_status"], "CAPITAL_CONFIGURATION_INVALID")

    def test_day_handoff_requires_authoritative_trace_and_regular_session(self):
        capital = lane_capital_status("DAY", {"ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000"})
        trace = [{
            "lane_id": "DAY", "symbol": "NVDA", "candidate_id": "c1", "selected": True,
            "order_ready": True, "submit_order": False, "broker_actions_used": 0,
            "capital_book_id": "paper_day_learning", "same_session_exit_required": True,
            "overnight_allowed": False,
        }]
        self.assertTrue(lane_handoff_proof("DAY", trace, capital, session="regular_hours")["proven"])
        self.assertFalse(lane_handoff_proof("DAY", trace, capital, session="after_hours")["proven"])
        self.assertTrue(day_regular_session_allowed("regular_hours"))
        self.assertFalse(day_regular_session_allowed("pre_market"))

    def test_strict_truth_needs_real_paired_fill_and_lifecycle_lineage(self):
        row = {
            "truth_quality": "BROKER_CONFIRMED_COMPLETE", "entry_order_id": "bo", "entry_fill_id": "bf",
            "exit_order_id": "so", "exit_fill_id": "sf", "lifecycle_id": "l1",
        }
        self.assertTrue(strict_broker_truth(row))
        self.assertFalse(strict_broker_truth({k: v for k, v in row.items() if k != "exit_fill_id"}))

    def test_adaptive_throughput_never_exceeds_approved_envelope(self):
        rows = [{
            "lane_id": "DAY", "truth_quality": "BROKER_CONFIRMED_COMPLETE", "entry_order_id": f"b{i}",
            "entry_fill_id": f"bf{i}", "exit_order_id": f"s{i}", "exit_fill_id": f"sf{i}", "lifecycle_id": f"l{i}",
        } for i in range(20)]
        payload = adaptive_throughput("DAY", rows)
        self.assertEqual(payload["adaptive_level"], 3)
        self.assertEqual(payload["max_open_positions_current"], 3)
        self.assertEqual(payload["max_completed_trades_current"], 8)
        self.assertFalse(payload["automatic_expansion_above_approved_ceiling"])

    def test_strict_truth_is_persisted_only_after_paired_lane_fill_fixture(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"ASTRA_DAY_LANE_CAPITAL_LIMIT": "15000"}, clear=False):
            root = pathlib.Path(tmp)
            (root / "broker_truth_records_v1.json").write_text('{"records": []}', encoding="utf-8")
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            result = engine._persist_strict_lane_truth(
                {
                    "lane_id": "DAY", "symbol": "NVDA", "asset_type": "stock", "position_id": "l1",
                    "entry_order_id": "bo", "entry_fill_id": "bf", "entry_timestamp": "2026-01-01T00:00:00Z",
                    "entry_price": 100, "broker_filled_avg_price": 100, "entry_price_verified": True,
                    "entry_price_source": "alpaca_paper_order.filled_avg_price",
                    "entry_price_evidence_class": "BROKER_CONFIRMED_FILL", "quantity": 1,
                },
                {"exit_order_id": "so", "exit_fill_id": "sf", "filled_at": "2026-01-01T01:00:00Z"},
                exit_price=101, return_percent=1, hold_seconds=3600, exit_reason="fixture",
            )
            self.assertTrue(result["persisted"])
            self.assertFalse(engine._persist_strict_lane_truth(
                {"lane_id": "DAY", "symbol": "NVDA", "asset_type": "stock", "position_id": "l1", "entry_order_id": "bo", "entry_fill_id": "bf", "entry_price": 100, "quantity": 1},
                {"exit_order_id": "so", "exit_fill_id": "sf", "filled_at": "2026-01-01T01:00:00Z"},
                exit_price=101, return_percent=1, hold_seconds=3600, exit_reason="fixture",
            )["persisted"])


if __name__ == "__main__":
    unittest.main()
