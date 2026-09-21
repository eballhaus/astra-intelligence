import json

from scripts import astra_overnight_historical_supervisor_v1 as supervisor


def _gate(allowed=True, state="RESOURCE_NORMAL"):
    return {"allowed": allowed, "mode": "NORMAL" if allowed else "BLOCKED", "resource_state": state, "worker_count": 1, "reason": ""}


def test_supervisor_waits_without_launching_child_when_worker_paused(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(supervisor, "resource_gate", lambda state_dir: _gate(False, "RESOURCE_MEMORY_PAUSE"))
    result = supervisor.run_once(state_dir=tmp_path, status_path=tmp_path / "status.json", log_path=tmp_path / "history.log", launch_child=lambda *args: launches.append(args))
    assert result["status"] == "WAITING_FOR_RESOURCES"
    assert launches == []
    assert json.loads((tmp_path / "status.json").read_text())["status"] == "WAITING_FOR_RESOURCES"


def test_supervisor_runs_one_child_at_a_time_and_resumes_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "resource_gate", lambda state_dir: _gate())
    launches = []

    def launch(lane, state_dir, log_path, poll_seconds):
        launches.append(lane)
        return {"status": "COMPLETE"}

    result = supervisor.run_once(state_dir=tmp_path, status_path=tmp_path / "status.json", log_path=tmp_path / "history.log", launch_child=launch)
    assert result["status"] == "COMPLETE"
    assert launches == ["news-proof", "macro", "analyst", "microstructure"]
    checkpoint = json.loads((tmp_path / supervisor.SUPERVISOR_ROOT / supervisor.CHECKPOINT_NAME).read_text())
    assert checkpoint["completed_lanes"] == sorted(supervisor.LANES)

    launches.clear()
    result = supervisor.run_once(state_dir=tmp_path, status_path=tmp_path / "status.json", log_path=tmp_path / "history.log", launch_child=launch)
    assert result["status"] == "COMPLETE"
    assert launches == []


def test_runner_command_has_one_state_dir_and_preserves_resume_lane():
    command = supervisor._runner_command("microstructure", supervisor.STATE_ROOT)
    assert command.count("--state-dir") == 1
    assert command[command.index("--state-dir") + 1] == str(supervisor.STATE_ROOT)
    assert command[command.index("microstructure")] == "microstructure"


def test_supervisor_does_not_mark_provider_failure_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "resource_gate", lambda state_dir: _gate())
    result = supervisor.run_once(
        state_dir=tmp_path,
        status_path=tmp_path / "status.json",
        log_path=tmp_path / "history.log",
        launch_child=lambda *args: {"status": "AUTHENTICATION_FAILED"},
    )
    assert result["status"] == "WAITING_FOR_PROVIDER"
    checkpoint = tmp_path / supervisor.SUPERVISOR_ROOT / supervisor.CHECKPOINT_NAME
    assert not checkpoint.exists()
