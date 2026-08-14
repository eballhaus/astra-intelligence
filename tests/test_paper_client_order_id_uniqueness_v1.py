"""PAPER client-order IDs must be unique without weakening broker safeguards."""
from __future__ import annotations

import re
import tempfile
import unittest

from engine.paper_autopilot import PaperAutopilotEngine, _paper_broker_client_order_id


def _row(**extra):
    return {
        "symbol": "NVDA",
        "asset_type": "stock",
        "lane_id": "DAY",
        "recommendation_id": "rec-1",
        "decision_id": "decision-1",
        "eligibility_evaluation_id": "eligibility-1",
        "candidate_id": "candidate-1",
        **extra,
    }


class PaperClientOrderIdUniquenessTests(unittest.TestCase):
    def test_same_candidate_gets_fresh_ids_for_distinct_submissions(self):
        first = _paper_broker_client_order_id(_row(), side="buy", purpose="entry")
        second = _paper_broker_client_order_id(_row(), side="buy", purpose="entry")
        self.assertNotEqual(first, second)

    def test_lane_and_asset_namespaces_cannot_collide(self):
        ids = {
            _paper_broker_client_order_id(_row(lane_id="DAY"), side="buy", purpose="entry"),
            _paper_broker_client_order_id(_row(lane_id="SCALP"), side="buy", purpose="entry"),
            _paper_broker_client_order_id(_row(lane_id="SWING"), side="buy", purpose="entry"),
            _paper_broker_client_order_id(_row(symbol="BTC/USD", asset_type="crypto", lane_id="CRYPTO"), side="buy", purpose="entry"),
        }
        self.assertEqual(len(ids), 4)

    def test_entry_and_exit_are_distinct_and_broker_safe(self):
        entry = _paper_broker_client_order_id(_row(), side="buy", purpose="entry")
        exit_id = _paper_broker_client_order_id(_row(position_id="position-1"), side="sell", purpose="native_exit")
        self.assertNotEqual(entry, exit_id)
        for client_order_id in (entry, exit_id):
            self.assertLessEqual(len(client_order_id), 48)
            self.assertRegex(client_order_id, re.compile(r"^[A-Za-z0-9-]+$"))
            self.assertTrue(client_order_id.startswith("astra-"))

    def test_id_generation_does_not_enable_broker_or_live_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = PaperAutopilotEngine(
                db_path=f"{directory}/paper.db", state_path=f"{directory}/state.json", enabled=False,
            )
            self.assertFalse(engine._alpaca_paper_broker_enabled())
        self.assertTrue(_paper_broker_client_order_id(_row(), side="buy", purpose="entry"))


if __name__ == "__main__":
    unittest.main()
