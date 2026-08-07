from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WATCHDOG_PATH = Path(__file__).resolve().parents[1] / "scripts" / "astra_watchdog.py"
SPEC = importlib.util.spec_from_file_location("astra_watchdog_recovery_v1", WATCHDOG_PATH)
assert SPEC and SPEC.loader
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


class AstraWatchdogRecoveryTests(unittest.TestCase):
    def test_worker_health_rejects_stale_snapshot_or_wrong_process(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "worker.json"
            state.write_text(json.dumps({"active_worker_present": True, "active_worker_pid": 123, "heartbeat_at": "2020-01-01T00:00:00Z"}), encoding="utf-8")
            with patch.object(watchdog, "WORKER_STATE_PATH", state), patch("subprocess.run") as run:
                run.return_value.stdout = "python unrelated.py"
                process_ok, heartbeat_ok, details = watchdog._worker_health()
            self.assertFalse(process_ok)
            self.assertFalse(heartbeat_ok)
            self.assertEqual(details["pid"], 123)

    def test_targeted_recovery_only_restarts_missing_worker(self):
        healthy = {"backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
        initial = {**healthy, "worker_running": False, "worker_heartbeat": False, "worker": {"reason": "WORKER_STATE_MISSING"}}
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", side_effect=[initial, initial, healthy]), patch.object(watchdog, "_recover_component", return_value=0) as recover, patch.object(watchdog.time, "sleep"):
            result = watchdog.ensure_running(boot_recovery=True)
        self.assertTrue(result["worker_running"])
        self.assertEqual(recover.call_args_list[0].args[0], "worker")
        self.assertEqual(len(recover.call_args_list), 1)

    def test_targeted_recovery_only_restarts_missing_backend(self):
        healthy = {"backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
        initial = {**healthy, "backend_running": False, "backend_health": False}
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", side_effect=[initial, healthy, healthy]), patch.object(watchdog, "_recover_component", return_value=0) as recover, patch.object(watchdog.time, "sleep"):
            result = watchdog.ensure_running()
        self.assertTrue(result["backend_health"])
        self.assertEqual([call.args[0] for call in recover.call_args_list], ["backend"])

    def test_targeted_recovery_only_restarts_missing_frontend(self):
        healthy = {"backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
        initial = {**healthy, "frontend_running": False, "frontend_health": False}
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", side_effect=[initial, healthy, healthy]), patch.object(watchdog, "_recover_component", return_value=0) as recover, patch.object(watchdog.time, "sleep"):
            result = watchdog.ensure_running()
        self.assertTrue(result["frontend_health"])
        self.assertEqual([call.args[0] for call in recover.call_args_list], ["frontend"])

    def test_launchagent_template_uses_venv_and_boot_recovery(self):
        template = (WATCHDOG_PATH.parent / "com.astra.watchdog.plist").read_text(encoding="utf-8")
        self.assertIn("/venv/bin/python", template)
        self.assertIn("--boot-recovery", template)
        self.assertIn("ThrottleInterval", template)
        self.assertIn("Library/Logs/Astra", template)


if __name__ == "__main__":
    unittest.main()
