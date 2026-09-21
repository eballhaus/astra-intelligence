import json
from pathlib import Path
from unittest.mock import patch

from scripts import astra_local_historical_gap_runner_v1 as runner


def _health(state_dir, resource_state="RESOURCE_NORMAL"):
    return {"worker_count": 1, "resource_state": resource_state, "last_error": "", "cycle_count": 1, "updated_at": "2026-09-20T00:00:00Z"}


def test_macro_record_fails_closed_without_vintage_availability():
    row = runner._macro_record("CPIAUCSL", {"date": "2026-01-01", "value": "1.2"}, receipt="2026-09-20T00:00:00Z", source_file="fixture")
    assert row["replay_safe"] is False
    assert row["point_in_time_status"] in {"CURRENT_SNAPSHOT_ONLY", "TIMESTAMP_INSUFFICIENT", "PARTIALLY_POINT_IN_TIME"}
    assert row["original_timestamp_fields"]["date"] == "2026-01-01"


def test_micro_record_preserves_event_and_receipt_without_bars():
    row = runner._micro_record("AAPL", "quotes", {"t": "2026-09-19T14:30:01Z", "bp": 100.0, "ap": 100.1, "bs": 2, "as": 3}, receipt="2026-09-20T00:00:00Z", source_file="fixture")
    assert row["provider_event_time"] == "2026-09-19T14:30:01Z"
    assert row["ingested_at"] == "2026-09-20T00:00:00Z"
    assert row["replay_safe"] is False
    assert row["trade_price"] is None


def test_resource_pause_blocks_provider_work(tmp_path):
    with patch.object(runner, "worker_health", return_value=_health(tmp_path, "RESOURCE_MEMORY_PAUSE")):
        result = runner.run_microstructure(state_dir=tmp_path, router=object())
    assert result["status"] == "RESOURCE_BLOCKED"
    assert result["provider_calls"] == 0


def test_macro_uses_only_locally_discovered_series_and_no_provider_when_none(tmp_path):
    with patch.object(runner, "worker_health", return_value=_health(tmp_path)), patch.object(runner, "discover_fred_series", return_value=[]):
        result = runner.run_macro(state_dir=tmp_path, router=object())
    assert result["status"] == "NO_SERIES_IDENTIFIED"
    assert result["provider_calls"] == 0


def test_microstructure_checkpoint_pagination_uses_mocked_router(tmp_path):
    class FakeRouter:
        calls = 0

        def _request(self, provider, url, *, params, headers):
            self.calls += 1
            page = params.get("page_token")
            if page is None:
                return ({"quotes": [{"t": "2026-09-18T14:30:00Z", "bp": 100, "ap": 101}], "next_page_token": "next"}, 200, "", 1.0)
            return ({"quotes": [{"t": "2026-09-18T14:31:00Z", "bp": 100, "ap": 101}]}, 200, "", 1.0)

    with patch.object(runner, "worker_health", return_value=_health(tmp_path)):
        result = runner.run_microstructure(state_dir=tmp_path, symbols=["AAPL"], end="2026-09-18", max_days=1, router=FakeRouter())
    assert result["status"] == "COMPLETE"
    assert result["provider_calls"] == 4
    checkpoints = list((tmp_path / runner.LOCAL_ROOT_NAME / "microstructure" / "checkpoints").glob("*.json"))
    assert checkpoints
    assert all(json.loads(path.read_text())["next_page_token"] is None for path in checkpoints)


def test_microstructure_accepts_symbol_keyed_quotes_and_trades(tmp_path):
    class FakeRouter:
        def _request(self, provider, url, *, params, headers):
            feed = "quotes" if "quotes" in url else "trades"
            row = {"t": "2026-09-18T14:30:00Z", "bp": 100, "ap": 101} if feed == "quotes" else {"t": "2026-09-18T14:30:00Z", "p": 100, "s": 1}
            return ({feed: {"AAPL": [row]}}, 200, "", 1.0)

    with patch.object(runner, "worker_health", return_value=_health(tmp_path)), patch.object(runner.time, "sleep"):
        result = runner.run_microstructure(state_dir=tmp_path, symbols=["AAPL"], end="2026-09-18", max_days=1, router=FakeRouter())
    assert result["status"] == "COMPLETE"
    assert result["records"] == 2


def test_checkpoint_resume_uses_saved_token_not_page_zero(tmp_path):
    checkpoint_dir = tmp_path / runner.LOCAL_ROOT_NAME / "microstructure" / "checkpoints"
    checkpoint_dir.mkdir(parents=True)
    cp = checkpoint_dir / "AAPL_2026-09-18_quotes.json"
    cp.write_text(json.dumps({"status": "SUCCESS", "pages": 1, "records": 1, "next_page_token": "resume-token"}))

    class FakeRouter:
        seen = []

        def _request(self, provider, url, *, params, headers):
            self.seen.append(params.get("page_token"))
            return ({"quotes": {"AAPL": [{"t": "2026-09-18T14:31:00Z", "bp": 100, "ap": 101}]}}, 200, "", 1.0)

    router = FakeRouter()
    with patch.object(runner, "worker_health", return_value=_health(tmp_path)), patch.object(runner.time, "sleep"):
        result = runner.run_microstructure(state_dir=tmp_path, symbols=["AAPL"], end="2026-09-18", max_days=1, router=router)
    assert result["status"] == "COMPLETE"
    assert router.seen[0] == "resume-token"
    assert router.seen[1] is None  # trades has no pre-existing checkpoint


def test_elevated_resource_uses_reduced_pacing(tmp_path):
    class FakeRouter:
        def _request(self, provider, url, *, params, headers):
            return ({"quotes": {"AAPL": [{"t": "2026-09-18T14:30:00Z"}]}}, 200, "", 1.0)

    sleeps = []
    with patch.object(runner, "worker_health", return_value=_health(tmp_path, "RESOURCE_ELEVATED")), patch.object(runner.time, "sleep", side_effect=sleeps.append):
        call = runner._call(FakeRouter(), "ALPACA", "https://example", params={}, state_dir=tmp_path)
    assert call["http_status"] == 200
    assert sleeps == [10]


def test_resource_pause_after_pacing_blocks_before_provider_request(tmp_path):
    class FakeRouter:
        calls = 0

        def _request(self, provider, url, *, params, headers):
            self.calls += 1
            return ({}, 200, "", 1.0)

    health = [_health(tmp_path), _health(tmp_path, "RESOURCE_MEMORY_PAUSE")]
    router = FakeRouter()
    with patch.object(runner, "worker_health", side_effect=health), patch.object(runner.time, "sleep"):
        call = runner._call(router, "ALPACA", "https://example", params={}, state_dir=tmp_path)
    assert call["error"] == "RESOURCE_BLOCKED"
    assert router.calls == 0


def test_news_proof_never_calls_provider(tmp_path):
    root = tmp_path / "historical_context_phase2_v1"
    root.mkdir(parents=True)
    (root / "retained.jsonl").write_text(json.dumps({"source_provider": "FINNHUB", "publication_time": "2026-01-01T00:00:00Z"}) + "\n")
    result = runner.run_news_proof(state_dir=tmp_path)
    assert result["provider_calls"] == 0
    assert result["replay_safe"] is False


def test_analyst_cli_preserves_symbols_once(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update({"command": command, **kwargs})
        return {"status": "AUTHENTICATION_FAILED"}

    monkeypatch.setattr(runner, "run_command", fake_run)
    assert runner.main(["analyst", "--state-dir", str(tmp_path), "--symbols", "AAPL", "MSFT"]) == 0
    assert captured["symbols"] == ["AAPL", "MSFT"]
    assert captured["max_symbols"] == 2
