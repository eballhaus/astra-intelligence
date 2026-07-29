"""Production-path coverage for the worker-owned legacy retirement queue."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from engine.astra_legacy_retirement_workflow_v1 import load_legacy_retirement_queue_v1
from engine.paper_autopilot import PaperAutopilotEngine


class LegacyRetirementWorkerPhaseTests(unittest.TestCase):
    def test_worker_persists_advisory_queue_without_broker_or_order_actions(self):
        with tempfile.TemporaryDirectory(prefix="astra_legacy_retirement_") as directory:
            broker = Mock()
            engine = PaperAutopilotEngine(
                db_path=str(Path(directory) / "memory.db"),
                state_path=str(Path(directory) / "paper_autopilot_state.json"),
                alpaca_paper_broker=broker,
            )
            positions = {
                "LOSS": {
                    "symbol": "LOSS", "position_id": "broker-loss", "qty": 2.5,
                    "market_value": 50.0, "unrealized_pl": -25.0,
                    "unrealized_plpc": -0.3333,
                    "entry_timestamp": "2026-06-01T12:00:00Z",
                },
                "DUST": {
                    "symbol": "DUST", "position_id": "broker-dust", "qty": 0.00001,
                    "market_value": 0.001, "entry_timestamp": "2026-06-01T12:00:00Z",
                },
            }

            result = engine._legacy_retirement_review_phase(positions)

            self.assertEqual(result["producer"], "PaperAutopilot._legacy_retirement_review_phase")
            self.assertEqual(result["execution_authority"], "DISABLED")
            self.assertEqual(result["broker_actions_used"], 0)
            self.assertEqual(result["queue_length"], 2)
            queue = {row["symbol"]: row for row in result["queue"]}
            self.assertEqual(queue["LOSS"]["first_causal_blocker"], "ORIGINAL_THESIS_UNAVAILABLE")
            self.assertEqual(queue["LOSS"]["exact_sellable_quantity"], 2.5)
            self.assertEqual(queue["DUST"]["first_causal_blocker"], "DUST_POSITION_NOT_TRADABLE")
            self.assertEqual(queue["DUST"]["exact_sellable_quantity"], 0.0)
            self.assertEqual(load_legacy_retirement_queue_v1(directory), result["queue"])
            broker.mock_calls = []
            self.assertEqual(broker.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
