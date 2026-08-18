import os
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engine.astra_runtime_governance_v1 import (
    RuntimeLimits,
    WorkerLease,
    _future_iso,
    advance_resource_policy,
    canonical_runtime_invariants,
    canonical_worker_state,
    classify_resource_signals,
    read_snapshot,
    rotate_log,
    snapshot_age_seconds,
    worker_lease_integrity,
    write_snapshot,
    worker_liveness,
)


class RuntimeResourceGovernanceTests(unittest.TestCase):
    def test_future_iso_uses_aware_utc_after_timezone_style_change(self):
        now = datetime(2026, 8, 5, 13, 30, tzinfo=UTC)
        self.assertEqual(_future_iso(60, now=now), "2026-08-05T13:31:00Z")

    def test_snapshot_age_seconds_distinguishes_fresh_and_stale_heartbeat(self):
        fresh = {"heartbeat_at": datetime.now(UTC).isoformat().replace("+00:00", "Z")}
        stale = {"heartbeat_at": (datetime.now(UTC) - timedelta(seconds=181)).isoformat().replace("+00:00", "Z")}
        self.assertLess(snapshot_age_seconds(fresh), 2.0)
        self.assertGreater(snapshot_age_seconds(stale), 180.0)

    def test_snapshot_is_atomic_and_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            write_snapshot({"process_role": "PAPER_AUTOPILOT_WORKER", "cycle_state": "IDLE"}, path)
            self.assertEqual(read_snapshot(path)["process_role"], "PAPER_AUTOPILOT_WORKER")

    def test_concurrent_snapshot_writes_use_distinct_atomic_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.json"
            failures: list[Exception] = []

            def publish(writer: int) -> None:
                try:
                    for sequence in range(20):
                        write_snapshot({"writer": writer, "sequence": sequence}, path)
                except Exception as exc:  # Regression guard for the old shared .tmp race.
                    failures.append(exc)

            writers = [threading.Thread(target=publish, args=(index,)) for index in range(4)]
            for writer in writers:
                writer.start()
            for writer in writers:
                writer.join()

            self.assertEqual(failures, [])
            self.assertIn(read_snapshot(path).get("writer"), {0, 1, 2, 3})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

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

    def test_graceful_release_removes_only_its_own_lock_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            lease = WorkerLease(lock)
            self.assertTrue(lease.acquire())
            self.assertTrue(lock.exists())
            lease.release()
            self.assertFalse(lock.exists())

    def test_dead_identity_matching_lease_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            state = Path(directory) / "astra_worker_runtime_state_v1.json"
            lock.write_text('{"pid":999999,"worker_instance_id":"old-instance","worker_generation_id":"old-generation"}', encoding="utf-8")
            write_snapshot({
                "active_worker_present": False,
                "ownership_state": "NO_WORKER_ACTIVE",
                "last_known_worker_instance_id": "old-instance",
                "last_known_worker_generation_id": "old-generation",
            }, state)
            lease = WorkerLease(lock, state_path=state)
            self.assertTrue(lease.acquire())
            self.assertEqual(lease.last_acquire_state, "STALE_LEASE_RECOVERED")
            lease.release()

    def test_live_or_pid_reused_lease_is_never_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            state = Path(directory) / "astra_worker_runtime_state_v1.json"
            lock.write_text('{"pid":41,"worker_instance_id":"old-instance","worker_generation_id":"old-generation"}', encoding="utf-8")
            write_snapshot({
                "active_worker_present": False,
                "ownership_state": "NO_WORKER_ACTIVE",
                "last_known_worker_instance_id": "old-instance",
                "last_known_worker_generation_id": "old-generation",
            }, state)
            lease = WorkerLease(
                lock,
                state_path=state,
                process_lookup=lambda _pid: {"running": True, "command": "unrelated-process"},
            )
            self.assertFalse(lease.acquire())
            self.assertEqual(lease.last_acquire_state, "AMBIGUOUS_OR_LIVE_LOCK_METADATA")
            self.assertTrue(lock.exists())

    def test_ambiguous_state_cannot_clear_dead_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            state = Path(directory) / "astra_worker_runtime_state_v1.json"
            lock.write_text('{"pid":999999,"worker_instance_id":"old-instance","worker_generation_id":"old-generation"}', encoding="utf-8")
            write_snapshot({
                "active_worker_present": True,
                "ownership_state": "SINGLE_WORKER_ACTIVE",
                "active_worker_pid": 999999,
                "worker_instance_id": "different-instance",
                "worker_generation_id": "different-generation",
            }, state)
            lease = WorkerLease(lock, state_path=state)
            self.assertFalse(lease.acquire())
            self.assertEqual(lease.last_acquire_state, "AMBIGUOUS_OR_LIVE_LOCK_METADATA")
            self.assertTrue(lock.exists())

    def test_lease_integrity_distinguishes_dead_stale_from_live_matching_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            state = Path(directory) / "astra_worker_runtime_state_v1.json"
            lock.write_text('{"pid":999999,"worker_instance_id":"old-instance","worker_generation_id":"old-generation"}', encoding="utf-8")
            write_snapshot({
                "active_worker_present": False,
                "ownership_state": "NO_WORKER_ACTIVE",
                "last_known_worker_instance_id": "old-instance",
                "last_known_worker_generation_id": "old-generation",
            }, state)
            dead = worker_lease_integrity(lock, state_path=state)
            self.assertEqual(dead["state"], "STALE_DEAD_LEASE")

            lock.write_text('{"pid":41,"worker_instance_id":"live-instance","worker_generation_id":"live-generation"}', encoding="utf-8")
            write_snapshot({
                "active_worker_present": True,
                "active_worker_pid": 41,
                "worker_instance_id": "live-instance",
                "worker_generation_id": "live-generation",
            }, state)
            live = worker_lease_integrity(
                lock,
                state_path=state,
                process_lookup=lambda _pid: {"running": True, "command": "python -m engine.paper_autopilot_worker"},
            )
            self.assertEqual(live["state"], "ACTIVE_MATCHING_LEASE")

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

    def test_stale_inactive_error_cannot_hide_missing_worker(self):
        state = {
            "process_id": 8123,
            "active_worker_present": False,
            "ownership_state": "NO_WORKER_ACTIVE",
            "worker_terminal_cause": "worker_terminal_exception:RuntimeError",
            "heartbeat_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        }
        result = worker_liveness(state, process={"pid": 8123, "running": False, "command": ""})
        self.assertEqual(result["liveness_state"], "PROCESS_MISSING")
        self.assertFalse(result["active_worker_present"])


if __name__ == "__main__":
    unittest.main()
