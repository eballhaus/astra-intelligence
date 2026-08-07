from __future__ import annotations

import importlib.util
import json
import subprocess
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
        healthy = {"managed_components": ["backend", "worker", "frontend"], "backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
        initial = {**healthy, "worker_running": False, "worker_heartbeat": False, "worker": {"reason": "WORKER_STATE_MISSING"}}
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", side_effect=[initial, initial, healthy]), patch.object(watchdog, "_recover_component", return_value=0) as recover, patch.object(watchdog.time, "sleep"):
            result = watchdog.ensure_running(boot_recovery=True)
        self.assertTrue(result["worker_running"])
        self.assertEqual(recover.call_args_list[0].args[0], "worker")
        self.assertEqual(len(recover.call_args_list), 1)

    def test_targeted_recovery_only_restarts_missing_backend(self):
        healthy = {"managed_components": ["backend", "worker", "frontend"], "backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
        initial = {**healthy, "backend_running": False, "backend_health": False}
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", side_effect=[initial, healthy, healthy]), patch.object(watchdog, "_recover_component", return_value=0) as recover, patch.object(watchdog.time, "sleep"):
            result = watchdog.ensure_running()
        self.assertTrue(result["backend_health"])
        self.assertEqual([call.args[0] for call in recover.call_args_list], ["backend"])

    def test_targeted_recovery_only_restarts_missing_frontend(self):
        healthy = {"managed_components": ["backend", "worker", "frontend"], "backend_running": True, "backend_health": True, "frontend_running": True, "frontend_health": True, "worker_running": True, "worker_heartbeat": True, "worker": {"pid": 10}}
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

    def test_boot_daemon_template_and_helpers_are_login_independent(self):
        scripts = WATCHDOG_PATH.parent
        template = (scripts / "com.astra.boot-watchdog.plist").read_text(encoding="utf-8")
        self.assertIn("com.astra.boot-watchdog", template)
        self.assertIn("<key>UserName</key>", template)
        self.assertIn("<string>eric</string>", template)
        self.assertIn("/venv/bin/python", template)
        self.assertIn("--boot-recovery", template)
        self.assertIn("/Library/Logs/Astra", template)
        self.assertIn("<key>RunAtLoad</key>", template)
        self.assertIn("<key>KeepAlive</key>", template)
        install = scripts / "install_astra_launch_daemon.sh"
        result = subprocess.run(["bash", str(install), "--dry-run"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GUI LaunchAgent is disabled", result.stdout)
        self.assertIn("launchctl bootstrap system", install.read_text(encoding="utf-8"))

    def test_boot_daemon_owns_only_backend_and_worker(self):
        with patch.dict("os.environ", {"ASTRA_WATCHDOG_COMPONENTS": "backend,worker"}, clear=False), patch.object(watchdog, "_port_listening", return_value=True), patch.object(watchdog, "_http_ok", return_value=True), patch.object(watchdog, "_worker_health", return_value=(True, True, {"pid": 1})):
            status = watchdog.check_once()
        self.assertEqual(status["managed_components"], ["backend", "worker"])
        self.assertFalse(status["frontend_running"])

    def test_boot_runtime_sync_migrates_to_shared_canonical_state_and_credential_source(self):
        scripts = WATCHDOG_PATH.parent
        sync = scripts / "sync_astra_boot_runtime.sh"
        content = sync.read_text(encoding="utf-8")
        self.assertIn('/Users/Shared/AstraRuntime', content)
        self.assertIn('CANONICAL_STATE_ROOT', content)
        self.assertIn('desktop_state_pre_migration_', content)
        self.assertIn('symlink_to_shared_canonical_state', content)
        self.assertIn('credential migration verification failed', content)
        self.assertIn('rsync -a --checksum --dry-run', content)
        self.assertIn("--exclude 'state'", content)
        result = subprocess.run(["bash", str(sync), "--dry-run", "--adopt-state"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_state_root_mismatch_suppresses_recovery(self):
        status = {
            "managed_components": ["backend", "worker"],
            "backend_running": True,
            "backend_health": True,
            "worker_running": False,
            "worker_heartbeat": False,
            "worker": {"reason": "WORKER_STATE_MISSING"},
            "state_root_matches": False,
            "state_root": {"canonical_state_root": "/canonical", "boot_state_root": "/stale", "state_root_matches": False},
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(watchdog, "RECOVERY_STATE_PATH", Path(directory) / "recovery.json"), patch.object(watchdog, "check_once", return_value=status), patch.object(watchdog, "_recover_component") as recover:
            result = watchdog.ensure_running(boot_recovery=True)
        self.assertFalse(result["state_root_matches"])
        recover.assert_not_called()

    def test_boot_daemon_declares_shared_canonical_state_and_env_paths(self):
        template = (WATCHDOG_PATH.parent / "com.astra.boot-watchdog.plist").read_text(encoding="utf-8")
        self.assertIn("ASTRA_STATE_ROOT", template)
        self.assertIn("ASTRA_ENV_FILE", template)
        self.assertIn("/Users/Shared/AstraRuntime/state", template)
        self.assertNotIn("/Users/eric/Desktop/astra-intelligence-clean/state", template)

    def test_boot_launcher_does_not_depend_on_tmux_or_frontend(self):
        launcher = (WATCHDOG_PATH.parent / "astra_boot_start.sh").read_text(encoding="utf-8")
        self.assertNotIn("tmux", launcher)
        self.assertIn('COMPONENT="${ASTRA_START_COMPONENT:-}"', launcher)
        self.assertIn('"${COMPONENT}" != "backend" && "${COMPONENT}" != "worker"', launcher)


if __name__ == "__main__":
    unittest.main()
