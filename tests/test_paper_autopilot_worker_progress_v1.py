"""Regression coverage for isolated-worker progress ownership."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.paper_autopilot_worker import PaperAutopilotWorker


class _Autopilot:
    def __init__(self) -> None:
        self._enabled = True
        self.max_stocks = 4
        self._runtime_state = {}
        self.progress: list[dict] = []
        self.run_calls = 0

    def refresh_control_state_from_disk(self):
        return {"ok": True, "autopilot_enabled": True, "control_state_sync": "SYNCHRONIZED"}

    def record_external_worker_progress(self, **payload):
        self.progress.append(dict(payload))

    def run_cycle(self):
        self.run_calls += 1
        return {"legacy_swing_observation": {"market_activity": {"scheduler": {}}}}


class PaperAutopilotWorkerProgressTests(unittest.TestCase):
    def test_bounded_cycle_persists_engine_start_and_completion_progress(self):
        autopilot = _Autopilot()
        with patch("engine.paper_autopilot_worker.read_snapshot", return_value={}), patch(
            "engine.paper_autopilot_worker.write_snapshot", return_value=0.0
        ):
            worker = PaperAutopilotWorker(autopilot)
            worker._sample_resource = lambda: (
                {"resource_state": "RESOURCE_NORMAL", "resource_reason": "healthy"},
                {"resume_mode": "RESUME_NORMAL_BOUNDED"},
            )
            worker._publish = lambda **_kwargs: {}
            worker._run_continuous_governance = lambda: {}
            worker._evidence_summary = lambda: {}
            worker._bounded_cycle()

        self.assertEqual(autopilot.run_calls, 1)
        self.assertEqual([item["phase"] for item in autopilot.progress], [
            "external_cycle_active",
            "external_cycle_completed",
        ])
        self.assertTrue(all(bool(item["persist"]) for item in autopilot.progress))
        self.assertEqual(autopilot.progress[-1]["cycle_count"], 1)

    def test_resource_pause_records_a_persisted_engine_phase(self):
        autopilot = _Autopilot()
        with patch("engine.paper_autopilot_worker.read_snapshot", return_value={}), patch(
            "engine.paper_autopilot_worker.write_snapshot", return_value=0.0
        ):
            worker = PaperAutopilotWorker(autopilot)
            worker._sample_resource = lambda: (
                {"resource_state": "RESOURCE_HIGH_PAUSE", "resource_reason": "host_load"},
                {"resume_mode": "RESUME_NORMAL_BOUNDED"},
            )
            worker._publish = lambda **_kwargs: {}
            worker._run_continuous_governance = lambda: {}
            worker._bounded_cycle()

        self.assertEqual(autopilot.run_calls, 0)
        self.assertEqual(autopilot.progress[-1]["phase"], "external_cycle_resource_paused")
        self.assertTrue(autopilot.progress[-1]["persist"])


if __name__ == "__main__":
    unittest.main()
