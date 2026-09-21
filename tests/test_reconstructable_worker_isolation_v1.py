from __future__ import annotations

import json
from pathlib import Path

import engine.reconstructable_worker_isolation_v1 as isolation


def _row(symbol: str = "TEST") -> dict:
    return {
        "symbol": symbol,
        "price": 100.0,
        "quote_age_seconds": 1.0,
        "freshness_state": "CURRENT",
        "execution_freshness_state": "CURRENT",
        "observation_authority": False,
        "executable_evidence": False,
    }


def test_isolated_result_matches_bounded_allocator_contract(tmp_path: Path):
    from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1

    rows = [_row()]
    direct = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path)).evaluate_broad_observations_v1(rows, max_observations=1)
    isolated = isolation.run_broad_observation_evaluation_v1(
        rows,
        state_dir=str(tmp_path),
        resource_state="RESOURCE_NORMAL",
    )

    for key in ("observations_considered", "evaluations_attempted", "eligible", "promoted", "missing_evidence"):
        assert isolated[key] == direct[key]
    assert isolated["promoted_rows"] == direct["promoted_rows"]
    assert isolated["status"] == "SUCCESS"
    assert isolated["evaluation_only"] is True
    assert isolated["execution_authority"] is False
    assert isolated["broker_authority"] is False
    assert isolated["truth_authority"] is False
    assert isolated["policy_authority"] is False
    assert isolated["learning_ack_authority"] is False
    assert isolated["paper_only"] is True


def test_ipc_input_is_bounded_and_child_does_not_write_rank_state(tmp_path: Path):
    result = isolation.run_broad_observation_evaluation_v1(
        [_row(str(index)) for index in range(400)],
        state_dir=str(tmp_path),
        resource_state="RESOURCE_ELEVATED",
    )

    assert result["status"] == "SUCCESS"
    assert result["ipc_input_rows"] == isolation.MAX_INPUT_ROWS
    assert result["ipc_input_bytes"] <= isolation.MAX_IPC_BYTES
    assert not (tmp_path / "lane_ranked_entry_funnel_v1.json").exists()
    assert not (tmp_path / "paper_opportunity_allocation_rank_state_v1.json").exists()


def test_memory_pause_blocks_without_launching_child(monkeypatch):
    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("child must not start while memory-paused")

    monkeypatch.setattr(isolation.subprocess, "Popen", fail_if_started)
    result = isolation.run_broad_observation_evaluation_v1(
        [_row()],
        state_dir="state",
        resource_state="RESOURCE_MEMORY_PAUSE",
    )

    assert result["status"] == "BLOCKED"
    assert result["promoted_rows"] == []
    assert result["paper_only"] is True


def test_elevated_mode_is_allowed_but_reduced():
    result = isolation.run_broad_observation_evaluation_v1(
        [_row()],
        state_dir="state",
        resource_state="RESOURCE_ELEVATED",
    )
    assert result["status"] == "SUCCESS"
    assert result["mode"] == "REDUCED"


def test_timeout_fails_closed(monkeypatch):
    class TimeoutProcess:
        pid = 123
        returncode = None

        def communicate(self, input=None, timeout=None):
            raise isolation.subprocess.TimeoutExpired("test", timeout)

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(isolation.subprocess, "Popen", lambda *_args, **_kwargs: TimeoutProcess())
    result = isolation.run_broad_observation_evaluation_v1(
        [_row()],
        state_dir="state",
        resource_state="RESOURCE_NORMAL",
        timeout_seconds=1,
    )
    assert result["status"] == "FAILED_SAFE"
    assert result["failure_reason"] == "subprocess_timeout"
    assert result["promoted_rows"] == []


def test_repeated_runs_return_only_bounded_outputs(tmp_path: Path):
    results = [
        isolation.run_broad_observation_evaluation_v1(
            [_row(str(index)) for index in range(20)],
            state_dir=str(tmp_path),
            resource_state="RESOURCE_NORMAL",
        )
        for _ in range(3)
    ]
    assert all(len(result["promoted_rows"]) <= isolation.MAX_OUTPUT_ROWS for result in results)
    assert all(result["ipc_input_rows"] == 20 for result in results)
    assert all(result["isolated_subprocess"] is True for result in results)
