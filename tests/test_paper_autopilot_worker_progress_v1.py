"""Regression coverage for isolated-worker progress ownership."""
from __future__ import annotations

import unittest
import threading
import time
from pathlib import Path
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
    def test_publish_persists_canonical_autopilot_enable_state(self):
        autopilot = _Autopilot()
        writes: list[dict] = []
        with patch("engine.paper_autopilot_worker.read_snapshot", return_value={}), patch(
            "engine.paper_autopilot_worker.write_snapshot", side_effect=lambda payload: writes.append(dict(payload)) or 0.0
        ), patch("engine.paper_autopilot_worker.resource_snapshot", return_value={"resource_state": "RESOURCE_NORMAL", "worker_process": {}}):
            worker = PaperAutopilotWorker(autopilot)
            worker._publish()

        self.assertTrue(writes)
        self.assertTrue(writes[-1]["autopilot_enabled"])

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

    def test_active_cycle_heartbeat_publishes_engine_phase_without_running_autopilot(self):
        autopilot = _Autopilot()
        autopilot._runtime_state["worker_cycle_phase"] = "legacy_retirement_quote_refresh"
        writes: list[dict] = []
        snapshot = {
            "worker_generation_id": "generation-test",
            "active_worker_present": True,
            "cycle_id": "cycle-test",
        }
        with patch("engine.paper_autopilot_worker.read_snapshot", return_value=snapshot), patch(
            "engine.paper_autopilot_worker.write_snapshot", side_effect=lambda payload: writes.append(dict(payload)) or 0.0
        ), patch("engine.paper_autopilot_worker.ACTIVE_CYCLE_HEARTBEAT_SECONDS", 0.01):
            worker = PaperAutopilotWorker(autopilot)
            worker.lease.generation_id = "generation-test"
            worker.lease.instance_id = "instance-test"
            stop = threading.Event()
            thread = threading.Thread(
                target=worker._publish_active_cycle_heartbeat,
                kwargs={"cycle_id": "cycle-test", "cycle_started_monotonic": time.monotonic(), "stop_event": stop},
            )
            thread.start()
            time.sleep(0.04)
            stop.set()
            thread.join(timeout=1.0)

        self.assertTrue(writes)
        self.assertTrue(all(item["cycle_state"] == "ACTIVE_BOUNDED" for item in writes))
        self.assertTrue(all(item["cycle_heartbeat_phase"] == "legacy_retirement_quote_refresh" for item in writes))
        self.assertEqual(autopilot.run_calls, 0)

    def test_canonical_worker_launcher_clears_only_codex_sandbox_network_flag(self):
        script = (Path(__file__).resolve().parents[1] / "start_astra_persistent.sh").read_text(encoding="utf-8")
        worker_launch = next(
            line for line in script.splitlines()
            if "-B -m engine.paper_autopilot_worker" in line
        )
        self.assertIn("env -u CODEX_SANDBOX_NETWORK_DISABLED", worker_launch)
        self.assertIn("ASTRA_PROCESS_ROLE=worker", worker_launch)
        self.assertNotIn("APCA_API_BASE_URL=", worker_launch)


if __name__ == "__main__":
    unittest.main()
