from __future__ import annotations

import unittest
import time

from engine.paper_autopilot import PaperAutopilotEngine


class CycleEfficiencyTests(unittest.TestCase):
    def test_governance_diagnostic_result_is_reused_within_bounded_interval(self):
        worker = object.__new__(__import__(
            "engine.paper_autopilot_worker",
            fromlist=["PaperAutopilotWorker"],
        ).PaperAutopilotWorker)
        worker.autopilot = type("Autopilot", (), {"_runtime_state": {}})()
        worker._governance_last_run_monotonic = time.monotonic()
        worker._governance_min_interval_seconds = 30.0
        worker._governance_last_result = {"status": "PASS_CACHED", "provider_calls_used": 4}

        result = worker._run_continuous_governance()

        self.assertEqual(result["status"], "PASS_CACHED")
        self.assertEqual(result["scan_deferred"], "DIAGNOSTIC_CADENCE")
        self.assertEqual(result["provider_calls_used"], 0)
        self.assertEqual(result["broker_actions_used"], 0)

    def test_due_day_close_can_reuse_cycle_open_rows_without_a_second_store_read(self):
        engine = object.__new__(PaperAutopilotEngine)
        engine._runtime_state = {}
        engine._fetch_open_positions = lambda: (_ for _ in ()).throw(AssertionError("unexpected store read"))
        engine._native_lane_exit_session_status = lambda: {
            "paper_order_submission_allowed": False,
            "market_session_mode": "CLOSED",
        }
        engine._lane_forced_exit_reason = lambda _row: ""

        result = engine._run_due_day_lane_close_stage(
            {},
            open_rows=[{"position_id": "DINO", "symbol": "DINO", "lane_id": "DAY"}],
        )

        self.assertEqual(result["reviewed"], 0)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["blocked"], 0)


if __name__ == "__main__":
    unittest.main()
