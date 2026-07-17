import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.astra_runtime_governance_v1 import (
    RuntimeLimits,
    WorkerLease,
    advance_resource_policy,
    canonical_runtime_invariants,
    canonical_worker_state,
    classify_resource_signals,
    read_snapshot,
    rotate_log,
    write_snapshot,
    worker_liveness,
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
        self.assertEqual(invariants["SUFFICIENT_BARS_BUILD_MOMENTUM"]["state"], "AWAITING_SAMPLES")
        self.assertEqual(invariants["MOMENTUM_IS_ACKNOWLEDGED"]["state"], "AWAITING_SAMPLES")

    def _signals(self, **overrides):
        data = {
            "logical_cpu_count": 6,
            "host_load_1m": 4.3,
            "host_load_5m": 4.9,
            "host_load_15m": 5.0,
            "cpu_idle_percent": 51.0,
            "memory_pressure_state": "normal",
            "available_memory_mb": 20 * 1024,
            "backend_health_latency_ms": 25.0,
            "worker_process": {"memory_mb": 120.0},
        }
        data.update(overrides)
        return data

    def test_six_cpu_healthy_baseline_is_not_saturated(self):
        sample = classify_resource_signals(self._signals(), require_complete=True)
        self.assertAlmostEqual(sample["normalized_load_1m"], 4.3 / 6, places=3)
        self.assertEqual(sample["resource_candidate_state"], "RESOURCE_NORMAL")

    def test_high_load_with_healthy_idle_is_elevated_not_pause(self):
        sample = classify_resource_signals(self._signals(host_load_1m=7.2, cpu_idle_percent=52.0), require_complete=True)
        self.assertEqual(sample["resource_candidate_state"], "RESOURCE_ELEVATED")

    def test_single_high_sample_reduces_before_pause(self):
        sample = classify_resource_signals(self._signals(host_load_1m=7.2, cpu_idle_percent=10.0), require_complete=True)
        policy = advance_resource_policy({}, sample)
        self.assertEqual(policy["resource_state"], "RESOURCE_ELEVATED")
        self.assertEqual(policy["consecutive_high_samples"], 1)

    def test_sustained_high_samples_pause(self):
        sample = classify_resource_signals(self._signals(host_load_1m=7.2, cpu_idle_percent=10.0), require_complete=True)
        policy = {}
        for _ in range(RuntimeLimits().sustained_high_samples_required):
            policy = advance_resource_policy(policy, sample)
        self.assertEqual(policy["resource_state"], "RESOURCE_HIGH_PAUSE")
        self.assertEqual(policy["resource_decision"], "PAUSE")

    def test_memory_and_latency_fail_safe(self):
        memory = classify_resource_signals(self._signals(memory_pressure_state="high"), require_complete=True)
        self.assertEqual(advance_resource_policy({}, memory)["resource_state"], "RESOURCE_MEMORY_PAUSE")
        latency = classify_resource_signals(self._signals(backend_health_latency_ms=2000.0), require_complete=True)
        policy = {}
        for _ in range(RuntimeLimits().sustained_high_samples_required):
            policy = advance_resource_policy(policy, latency)
        self.assertEqual(policy["resource_state"], "RESOURCE_API_LATENCY_PAUSE")

    def test_missing_required_signals_fail_closed(self):
        sample = classify_resource_signals(self._signals(cpu_idle_percent=None), require_complete=True)
        self.assertEqual(sample["resource_candidate_state"], "RESOURCE_UNKNOWN_FAIL_CLOSED")
        self.assertEqual(advance_resource_policy({}, sample)["resource_state"], "RESOURCE_UNKNOWN_FAIL_CLOSED")

    def test_recovery_requires_cooldown_and_healthy_hysteresis(self):
        now = datetime.now(UTC)
        unsafe = classify_resource_signals(self._signals(host_load_1m=7.2, cpu_idle_percent=10.0), require_complete=True)
        policy = {}
        for _ in range(RuntimeLimits().sustained_high_samples_required):
            policy = advance_resource_policy(policy, unsafe, now=now)
        healthy = classify_resource_signals(self._signals(), require_complete=True)
        policy = advance_resource_policy(policy, healthy, now=now)
        self.assertEqual(policy["resource_state"], "RESOURCE_RECOVERY_COOLDOWN")
        resumed_at = now + timedelta(seconds=RuntimeLimits().recovery_cooldown_seconds + 1)
        for _ in range(RuntimeLimits().healthy_samples_required):
            policy = advance_resource_policy(policy, healthy, now=resumed_at)
        self.assertEqual(policy["resource_state"], "RESOURCE_NORMAL")
        self.assertEqual(policy["resume_mode"], "RESUME_ONE_SYMBOL")

    def test_missing_or_reused_worker_is_historical_not_active(self):
        state = {
            "process_id": 8123,
            "worker_instance_id": "old-worker",
            "worker_generation_id": "old-generation",
            "heartbeat_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "limits": RuntimeLimits().__dict__,
            "ownership_state": "SINGLE_WORKER_ACTIVE",
        }
        missing = worker_liveness(state, process={"pid": 8123, "running": False, "command": ""})
        self.assertFalse(missing["active_worker_present"])
        self.assertEqual(missing["liveness_state"], "PROCESS_MISSING")
        reused = worker_liveness(state, process={"pid": 8123, "running": True, "command": "unrelated-process"})
        self.assertFalse(reused["active_worker_present"])
        self.assertEqual(reused["liveness_state"], "PID_REUSED")

    def test_clean_stop_retains_only_last_known_worker(self):
        state = {
            "process_id": 8123,
            "worker_instance_id": "old-worker",
            "worker_generation_id": "old-generation",
            "active_worker_present": False,
            "last_known_worker_pid": 8123,
            "last_known_worker_generation_id": "old-generation",
            "last_known_worker_exit_reason": "worker_stopped",
        }
        result = worker_liveness(state, process={"pid": 8123, "running": False, "command": ""})
        self.assertEqual(result["liveness_state"], "STOPPED_CLEANLY")
        self.assertIsNone(result["active_worker_pid"])
        self.assertEqual(result["last_known_worker_pid"], 8123)


if __name__ == "__main__":
    unittest.main()
