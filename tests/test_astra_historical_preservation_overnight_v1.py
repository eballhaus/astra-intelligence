import json

import scripts.astra_historical_preservation_overnight_v1 as supervisor


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_five_minute_scope_uses_existing_core_manifest_without_new_symbols():
    scope = supervisor.five_minute_scope()

    assert scope["approved_scope_found"] is True
    assert scope["symbol_count"] == 100
    assert scope["symbols"][:3] == ["AAPL", "MSFT", "NVDA"]
    assert scope["selection_source"] == "existing_100_symbol_intraday_core_manifest"


def test_five_minute_command_is_bounded_and_explicit():
    command = supervisor.five_minute_command_args()

    assert "--symbols" in command and command[command.index("--symbols") + 1] == "100"
    assert "--lookback-days" in command and command[command.index("--lookback-days") + 1] == "365"
    assert "--window-days" in command and command[command.index("--window-days") + 1] == "45"
    assert "--timeframe" in command and command[command.index("--timeframe") + 1] == "5Min"
    assert "--calls-per-minute" in command and command[command.index("--calls-per-minute") + 1] == "25"


def test_stage3_verification_requires_clean_complete_artifacts(monkeypatch, tmp_path):
    checkpoint = tmp_path / "5min_progress.json"
    validation = tmp_path / "5min_validation.json"
    summary = tmp_path / "5min_summary.json"
    monkeypatch.setattr(supervisor, "FIVE_MINUTE_CHECKPOINT", checkpoint)
    monkeypatch.setattr(supervisor, "FIVE_MINUTE_VALIDATION", validation)
    monkeypatch.setattr(supervisor, "FIVE_MINUTE_SUMMARY", summary)
    scope = {"symbol_count": 1}
    _write(checkpoint, {
        "status": "COMPLETE",
        "manifest_symbols": ["AAPL"],
        "updated_at": "2026-09-17T00:00:00Z",
        "per_symbol": {"AAPL": {"windows_completed": ["2026-01-01:2026-02-14"]}},
        "windows_completed": 1,
        "total_api_calls": 1,
        "rows_inserted": 10,
        "total_payload_bytes": 100,
        "summary": {"status": "COMPLETE"},
        "errors": [],
    })
    _write(validation, {"status": "COMPLETE"})

    assert supervisor.stage3_verified(scope) == (True, "ok")


def test_stage4_crypto_scope_does_not_start_an_unapproved_job():
    scope = supervisor.stage4_crypto_scope()

    assert scope["status"] == "STAGE_4_REQUIRES_SCOPE_APPROVAL"
    assert scope["approved_scope_found"] is False
    assert scope["api_calls_started"] is False


def test_worker_health_ignores_process_inspection_commands(monkeypatch, tmp_path):
    state = tmp_path / "worker.json"
    _write(state, {"active_worker_pid": 42, "cycle_count": 7, "resource_state": "RESOURCE_NORMAL"})
    monkeypatch.setattr(supervisor, "WORKER_STATE", state)
    monkeypatch.setattr(supervisor, "ps_rows", lambda: [
        (42, "python -B -m engine.paper_autopilot_worker"),
        (99, "zsh -lc ps -axo pid=,command= | rg paper_autopilot_worker"),
    ])
    monkeypatch.setattr(supervisor, "backend_status", lambda: 200)

    health = supervisor.worker_health()

    assert health["worker_count"] == 1
    assert health["snapshot_worker_count"] == 1
