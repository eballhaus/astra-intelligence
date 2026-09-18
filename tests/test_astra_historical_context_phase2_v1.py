from __future__ import annotations

import json
from pathlib import Path

from scripts.astra_historical_context_phase2_v1 import (
    PIPELINE_NAME,
    STAGES,
    base_state,
    initial_stage_checkpoint,
    safety_fields,
    stage_name,
)


def test_phase2_has_single_ordered_stage_contract(tmp_path: Path):
    state = base_state(tmp_path)
    assert [number for number, _name, _output in STAGES] == list(range(1, 15))
    assert state["pipeline"] == PIPELINE_NAME
    assert state["stage_statuses"]["1"] == "PENDING"
    assert state["current_stage_name"] == stage_name(1)


def test_checkpoint_is_atomic_contract_and_historical_only(tmp_path: Path):
    checkpoint = initial_stage_checkpoint(tmp_path, 4)
    saved = json.loads((tmp_path / "astra_historical_context_phase2_v1_stage_04_progress.json").read_text())
    assert saved["stage_name"] == "OPTIONS_VOLATILITY_HISTORY"
    assert saved["status"] == "PENDING"
    assert saved["historical_replay_only"] is True
    assert saved["execution_authority"] == "DISABLED"
    assert saved["broker_actions_added"] == 0
    assert saved["truth_records_added"] == 0
    assert checkpoint["lookahead_rejected"] is True


def test_safety_contract_cannot_create_natural_records():
    safety = safety_fields()
    assert safety["execution_authority"] == "DISABLED"
    assert safety["live_trading_changed"] is False
    assert safety["broker_actions_added"] == 0
    assert safety["truth_records_added"] == 0
    assert safety["learning_acknowledgements_added"] == 0
    assert safety["capacity_mutations"] == 0


def test_existing_checkpoint_is_reused(tmp_path: Path):
    first = initial_stage_checkpoint(tmp_path, 10)
    first["status"] = "RUNNING"
    first["next_index"] = 50
    (tmp_path / "astra_historical_context_phase2_v1_stage_10_progress.json").write_text(json.dumps(first))
    second = initial_stage_checkpoint(tmp_path, 10)
    assert second["next_index"] == 50
    assert second["status"] == "RUNNING"
