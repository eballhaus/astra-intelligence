from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.astra_historical_learning_supervisor_v1 import claim_pid, run_once


class _Runner:
    def wake_once(self):
        return {
            "status": "DEFERRED_RESOURCE_GOVERNOR",
            "resource_decision": {"decision": "DEFER", "reason": "RESOURCE_MEMORY_PAUSE"},
            "source_progress": {"backlog_bytes": 12, "sources_in_progress": 1},
            "cycles_invoked": 0,
        }


class HistoricalLearningSupervisorV1Tests(unittest.TestCase):
    def test_single_owner_writes_bounded_status_and_preserves_defer(self):
        root = Path(tempfile.mkdtemp())
        result = run_once(state_dir=root, pid_path=root / "owner.pid", status_path=root / "status.json", runner=_Runner())
        payload = json.loads((root / "status.json").read_text())
        self.assertEqual(result["status"], "DEFERRED_RESOURCE_GOVERNOR")
        self.assertEqual(payload["resource_decision"]["reason"], "RESOURCE_MEMORY_PAUSE")
        self.assertEqual(payload["source_progress"]["backlog_bytes"], 12)
        self.assertFalse(payload["safety"]["execution_behavior_changed"])

    def test_existing_live_owner_blocks_duplicate(self):
        root = Path(tempfile.mkdtemp())
        pid = root / "owner.pid"
        self.assertTrue(claim_pid(pid))
        result = run_once(state_dir=root, pid_path=pid, status_path=root / "status.json", runner=_Runner())
        self.assertEqual(result["status"], "SKIP_ALREADY_RUNNING")
        pid.unlink()


if __name__ == "__main__":
    unittest.main()
