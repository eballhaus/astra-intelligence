import os
import tempfile
import unittest
from pathlib import Path

from engine.astra_runtime_governance_v1 import (
    RuntimeLimits,
    WorkerLease,
    canonical_runtime_invariants,
    canonical_worker_state,
    read_snapshot,
    rotate_log,
    write_snapshot,
)


class RuntimeResourceGovernanceTests(unittest.TestCase):
    def test_snapshot_is_atomic_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            write_snapshot({"process_role": "PAPER_AUTOPILOT_WORKER", "cycle_state": "IDLE"}, path)
            self.assertEqual(read_snapshot(path)["process_role"], "PAPER_AUTOPILOT_WORKER")

    def test_duplicate_worker_lease_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            first = WorkerLease(lock)
            second = WorkerLease(lock)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()

    def test_log_rotation_retains_recent_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.log"
            path.write_text("x" * 32, encoding="utf-8")
            result = rotate_log(path, max_bytes=16, generations=2)
            self.assertTrue(result["rotated"])
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            self.assertTrue((Path(directory) / "worker.log.1").exists())

    def test_limits_are_conservative(self):
        limits = RuntimeLimits.from_env()
        self.assertLessEqual(limits.maximum_symbols_per_cycle, 3)
        self.assertLessEqual(limits.maximum_provider_requests_per_cycle, 12)
        self.assertLessEqual(limits.maximum_cycle_elapsed_seconds, 20)

    def test_partial_state_is_rejected_without_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            path.write_text('{"worker_generation_id":', encoding="utf-8")
            self.assertEqual(canonical_worker_state(path), {})

    def test_stale_or_reused_pid_fails_canonical_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            write_snapshot(
                {
                    "process_role": "PAPER_AUTOPILOT_WORKER",
                    "process_id": 999999,
                    "worker_instance_id": "old",
                    "worker_generation_id": "old-generation",
                    "cycle_id": "cycle-1",
                    "cycle_state": "COMPLETE",
                    "cycle_elapsed_seconds": 1.0,
                    "limits": RuntimeLimits().__dict__,
                },
                path,
            )
            invariants = canonical_runtime_invariants(canonical_worker_state(path))
            self.assertEqual(invariants["ONE_CANONICAL_WORKER"]["state"], "FAIL")

    def test_no_momentum_is_explicitly_awaiting_progress(self):
        state = {
            "process_role": "PAPER_AUTOPILOT_WORKER",
            "process_id": 999999,
            "worker_instance_id": "test",
            "worker_generation_id": "test-generation",
            "cycle_id": "cycle-1",
            "cycle_state": "COMPLETE",
            "cycle_elapsed_seconds": 1.0,
            "limits": RuntimeLimits().__dict__,
            "heartbeat_age_seconds": 0.0,
            "updated_at": "2026-01-01T00:00:00Z",
        }
        invariants = canonical_runtime_invariants(state)
        self.assertEqual(invariants["SUFFICIENT_BARS_BUILD_MOMENTUM"]["state"], "AWAITING_BOUNDED_PROGRESS")
        self.assertEqual(invariants["MOMENTUM_IS_ACKNOWLEDGED"]["state"], "AWAITING_BOUNDED_PROGRESS")


if __name__ == "__main__":
    unittest.main()
