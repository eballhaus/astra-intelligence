"""Production-path coverage for the worker-owned legacy retirement queue."""
from __future__ import annotations

import json
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
            broker.reconstruct_open_position_provenance.return_value = {
                "positions": [
                    {
                        "symbol": "LOSS",
                        "earliest_still_open_fill_timestamp": "2026-06-01T12:00:00Z",
                        "quantity_coverage_complete": True,
                        "entry_provenance_status": "BROKER_FILL_HISTORY_CONFIRMED",
                        "broker_order_ids": ["entry-loss"],
                    },
                    {
                        "symbol": "DUST",
                        "earliest_still_open_fill_timestamp": "2026-06-01T12:00:00Z",
                        "quantity_coverage_complete": True,
                        "entry_provenance_status": "BROKER_FILL_HISTORY_CONFIRMED",
                        "broker_order_ids": ["entry-dust"],
                    },
                ]
            }
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
            self.assertEqual(result["broker_read_calls_used"], 1)
            self.assertEqual(result["queue_length"], 2)
            self.assertEqual(result["unclassified_positions"], [])
            queue = {row["symbol"]: row for row in result["queue"]}
            self.assertEqual(queue["LOSS"]["first_causal_blocker"], "ORIGINAL_THESIS_UNAVAILABLE")
            self.assertEqual(queue["LOSS"]["exact_sellable_quantity"], 2.5)
            self.assertEqual(queue["DUST"]["first_causal_blocker"], "DUST_POSITION_NOT_TRADABLE")
            self.assertEqual(queue["DUST"]["exact_sellable_quantity"], 0.0)
            self.assertEqual(load_legacy_retirement_queue_v1(directory), result["queue"])
            self.assertEqual(broker.method_calls[0][0], "reconstruct_open_position_provenance")

            # Restart preserves the bounded broker-fill provenance cache, so
            # the normal worker does not rescan history on every restart.
            engine._save_state_file()
            restarted_broker = Mock()
            restarted = PaperAutopilotEngine(
                db_path=str(Path(directory) / "memory.db"),
                state_path=str(Path(directory) / "paper_autopilot_state.json"),
                alpaca_paper_broker=restarted_broker,
            )
            cached = restarted._legacy_retirement_review_phase(positions)
            self.assertEqual(cached["broker_read_calls_used"], 0)
            restarted_broker.reconstruct_open_position_provenance.assert_not_called()

    def test_missing_provenance_keeps_every_broker_position_visible_and_blocks_retirement(self):
        with tempfile.TemporaryDirectory(prefix="astra_legacy_retirement_") as directory:
            broker = Mock()
            broker.reconstruct_open_position_provenance.side_effect = RuntimeError("history unavailable")
            engine = PaperAutopilotEngine(
                db_path=str(Path(directory) / "memory.db"),
                state_path=str(Path(directory) / "paper_autopilot_state.json"),
                alpaca_paper_broker=broker,
            )
            result = engine._legacy_retirement_review_phase({
                "UNKNOWN": {"symbol": "UNKNOWN", "position_id": "broker-unknown", "qty": 1.0},
            })
            self.assertEqual(result["positions_considered"], 1)
            self.assertEqual(result["queue_length"], 0)
            self.assertEqual(result["entry_provenance_status"], "BROKER_FILL_PROVENANCE_UNAVAILABLE")
            self.assertEqual(result["unclassified_positions"][0]["first_causal_blocker"], "BROKER_ENTRY_PROVENANCE_UNAVAILABLE")
            with open(Path(directory) / "astra_legacy_retirement_queue_v1.json", encoding="utf-8") as handle:
                persisted = json.load(handle)
            self.assertEqual(persisted["unclassified_positions"][0]["symbol"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
