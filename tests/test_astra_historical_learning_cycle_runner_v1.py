from __future__ import annotations

import fcntl
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.astra_historical_learning_cycle_runner import (
    LOCK_FILE,
    STATUS_FILE,
    HistoricalLearningCycleRunnerV1,
    compact_cycle_result,
)


RUN = {"resource_decision": {"decision": "RUN", "reason": "BOUNDED_BACKGROUND_WINDOW"}, "throughput": {"mode": "CONSERVATIVE"}}
DEFER = {"resource_decision": {"decision": "DEFER", "reason": "RESOURCE_HIGH_PAUSE"}, "throughput": {"mode": "PAUSED"}}


class HistoricalLearningCycleRunnerV1Tests(unittest.TestCase):
    def _root(self) -> Path:
        return Path(tempfile.mkdtemp())

    def test_wakeup_invokes_exactly_one_unparameterized_v10_cycle(self):
        calls: list[tuple[tuple, dict]] = []

        def cycle(*args, **kwargs):
            calls.append((args, kwargs))
            return {"status": "COMPLETE", "partitions_processed": [{"rows_examined": 4}]}

        runner = HistoricalLearningCycleRunnerV1(str(self._root()), status_builder=lambda *_: RUN, cycle_runner=cycle)
        result = runner.wake_once({"worker_health": "HEALTHY"})
        self.assertEqual(result["cycles_invoked"], 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("max_rows", calls[0][1])
        self.assertNotIn("max_bytes", calls[0][1])

    def test_defer_and_pause_do_no_mining(self):
        calls: list[object] = []
        runner = HistoricalLearningCycleRunnerV1(str(self._root()), status_builder=lambda *_: DEFER, cycle_runner=lambda *_args, **_kwargs: calls.append(True))
        result = runner.wake_once()
        self.assertEqual(result["status"], "DEFERRED_RESOURCE_GOVERNOR")
        self.assertEqual(result["cycles_invoked"], 0)
        self.assertEqual(calls, [])

    def test_nonblocking_lock_prevents_overlapping_work(self):
        root = self._root()
        lock_path = root / LOCK_FILE
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            runner = HistoricalLearningCycleRunnerV1(str(root), status_builder=lambda *_: RUN, cycle_runner=lambda *_args, **_kwargs: self.fail("must not run"))
            result = runner.wake_once()
        self.assertEqual(result["status"], "SKIP_ALREADY_RUNNING")

    def test_error_is_recorded_without_internal_retry_loop(self):
        calls: list[object] = []

        def cycle(*_args, **_kwargs):
            calls.append(True)
            return {"status": "ERROR", "reason": "BOUNDED_FAILURE"}

        runner = HistoricalLearningCycleRunnerV1(str(self._root()), status_builder=lambda *_: RUN, cycle_runner=cycle)
        result = runner.wake_once()
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(len(calls), 1)

    def test_interval_is_configurable_and_status_is_operational_only(self):
        root = self._root()
        with patch.dict(os.environ, {"ASTRA_HISTORICAL_LEARNING_INTERVAL_SECONDS": "420"}):
            runner = HistoricalLearningCycleRunnerV1(str(root), status_builder=lambda *_: DEFER)
        self.assertEqual(runner.interval_seconds, 420.0)
        runner.wake_once()
        payload = json.loads((root / STATUS_FILE).read_text())
        self.assertEqual(payload["runner_status"], "DEFERRED_RESOURCE_GOVERNOR")
        self.assertTrue(payload["v10_authority_preserved"])
        self.assertFalse(payload["execution_behavior_changed"])
        self.assertNotIn("cycle", payload["last_cycle_result"])

    def test_compact_log_summary_omits_large_governor_payload(self):
        compact = compact_cycle_result({
            "status": "READY", "cycles_invoked": 1, "throughput": {"mode": "CONSERVATIVE"},
            "cycle": {"partitions_processed": [{"partition_id": "p1", "source": "source", "rows_examined": 2, "bytes_read": 3, "outcome_linked_count": 2, "aggregate_updates": 5, "duration_seconds": 0.1}], "large": ["x"] * 100},
        })
        self.assertEqual(compact["partition_id"], "p1")
        self.assertNotIn("cycle", compact)

    def test_safety_contract_has_no_external_calls_or_lifecycle_change(self):
        runner = HistoricalLearningCycleRunnerV1(str(self._root()), status_builder=lambda *_: DEFER)
        result = runner.wake_once()
        self.assertEqual(result["provider_calls_added"], 0)
        self.assertEqual(result["broker_calls_added"], 0)
        self.assertEqual(result["broker_actions_added"], 0)
        self.assertEqual(result["llm_calls_added"], 0)
        self.assertFalse(result["execution_behavior_changed"])
        self.assertFalse(result["frozen_lifecycle_modified"])


if __name__ == "__main__":
    unittest.main()
