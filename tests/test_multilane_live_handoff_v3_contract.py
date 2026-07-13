import pathlib
import tempfile
import unittest

from engine.astra_multilane_activation_v2 import lane_handoff_proof
from engine.paper_autopilot import PaperAutopilotEngine, _normalize_paper_entry_bridge


class MultilaneLiveHandoffV3ContractTests(unittest.TestCase):
    def test_snapshot_identity_is_stable_and_lane_scoped(self):
        source = {
            "symbol": "SPY",
            "paper_entry_horizon_style": "day_trade",
            "timestamp": "2026-07-13T01:00:00Z",
            "paper_autopilot_candidate_source": "top_buys_runtime_snapshot",
        }
        first = _normalize_paper_entry_bridge(source)
        second = _normalize_paper_entry_bridge(source)
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["recommendation_id"], second["recommendation_id"])
        self.assertTrue(first["candidate_source"])
        self.assertTrue(first["candidate_generated_at"])
        self.assertEqual(first["instrument_type"], "ETF")
        swing = _normalize_paper_entry_bridge({**source, "paper_entry_horizon_style": "swing_trade"})
        self.assertNotEqual(first["candidate_id"], swing["candidate_id"])

    def test_market_closed_day_trace_proves_handoff_without_order_submission(self):
        trace = {
            "lane_id": "DAY", "symbol": "COST", "candidate_id": "cand-1",
            "recommendation_id": "rec-1", "candidate_source": "top_buys_runtime_snapshot",
            "selection_id": "sel-1", "capital_book_id": "paper_day_learning",
            "submit_order": False, "broker_actions_used": 0,
        }
        proof = lane_handoff_proof(
            "DAY", [trace], {"capital_configured": True, "capital_book_id": "paper_day_learning"}, session="overnight_learning"
        )
        self.assertTrue(proof["proven"])
        self.assertTrue(proof["market_session_trace_proven"])
        self.assertEqual(proof["order_readiness_state"], "BLOCKED_MARKET_SESSION")

    def test_rejected_candidate_still_has_authoritative_dry_run_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"))
            payload = engine.operational_dry_run([{
                "symbol": "BTC/USD", "asset_class": "crypto", "asset_type": "crypto",
                "paper_entry_horizon_style": "crypto_24_7", "candidate_source": "crypto_rankings_cache",
                "source_snapshot_id": "crypto-snapshot-1", "candidate_generated_at": "2026-07-13T01:00:00Z",
                "paper_ready_status": "watch_only",
            }])
        self.assertEqual(payload["trace_owner"], "PaperAutopilot.operational_dry_run")
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertFalse(payload["submit_order"])
        self.assertEqual(len(payload["per_candidate_decision_trace"]), 1)
        trace = payload["per_candidate_decision_trace"][0]
        self.assertTrue(trace["candidate_id"])
        self.assertTrue(trace["recommendation_id"])
        self.assertEqual(trace["lane_id"], "CRYPTO")
        self.assertEqual(trace["capital_book_id"], "paper_crypto_separate")


if __name__ == "__main__":
    unittest.main()
