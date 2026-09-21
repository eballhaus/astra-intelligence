"""Focused regression tests for worker-side observation snapshot retention."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from engine.alpaca_ws_monitor import AlpacaWSMonitor
from engine.paper_autopilot import PaperAutopilotEngine, _compact_runtime_execution_trace_v1
from engine.paper_autopilot_worker import PaperAutopilotWorker


def _broad_row(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "bid": 100.0,
        "ask": 100.1,
        "price": 100.05,
        "trade_price": 100.05,
        "spread": 0.1,
        "open": 99.0,
        "high": 101.0,
        "low": 98.5,
        "close": 100.05,
        "volume": 12345,
        "change_percent": 1.2,
        "trade_size": 10,
        "provider": "ALPACA_SIP_BROAD_SNAPSHOT",
        "provider_used": "ALPACA_SIP_BROAD_SNAPSHOT",
        "provider_provenance": "ALPACA_SIP_BATCH_SNAPSHOT",
        "provider_native_timestamp": "2026-09-20T13:00:00Z",
        "provider_native_timestamp_kind": "PROVIDER_EVENT_TIME",
        "receive_timestamp": 1789995600.0,
        "last_checked_at": "2026-09-20T13:00:00Z",
        "market_event_at": "2026-09-20T13:00:00Z",
        "market_event_age_seconds": 0.2,
        "quote_age_seconds": 0.2,
        "freshness_state": "CURRENT",
        "execution_freshness_state": "CURRENT",
        "discovery_observation_state": "CURRENT",
        "large_unused_payload": "not retained by the monitor projection",
    }


def test_broad_monitor_projection_is_compact_and_bounded():
    monitor = AlpacaWSMonitor()
    rows = [_broad_row(f"SYM{i:04d}") for i in range(600)]
    full_bytes = len(json.dumps(rows, separators=(",", ":")))

    with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False):
        for _ in range(8):
            result = monitor.publish_broad_discovery_observations(rows)
            assert result["observation_count"] == 600
            status = monitor.status()

    projected = status["broad_discovery_observations"]
    assert len(projected) == 16
    assert status["broad_discovery_observation_count"] == 600
    assert status["broad_discovery_projection"] == "status_sample_v1"
    assert "provider_native_timestamp" in projected["SYM0000"]
    assert projected["SYM0000"]["freshness_state"] == "CURRENT"
    assert "open" not in projected["SYM0000"]
    assert "large_unused_payload" not in projected["SYM0000"]
    assert len(json.dumps(projected, separators=(",", ":"))) < full_bytes
    assert len(monitor._broad_discovery_observations) == 16
    assert monitor._broad_discovery_observation_count == 600


def test_memory_telemetry_reports_observation_bound_and_allocator_signal():
    truth = {"broker_truth_records_v1": [{"truth_id": "truth-1"}]}
    monitor = AlpacaWSMonitor()
    with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "worker"}, clear=False):
        monitor.publish_broad_discovery_observations([_broad_row(f"A{i:03d}") for i in range(32)])
        monitor_status = monitor.status()
    runtime = {
        **copy.deepcopy(truth),
        "alpaca_ws_active_position_monitor_v1": monitor_status,
    }
    autopilot = SimpleNamespace(_runtime_state=runtime)
    with patch("engine.paper_autopilot_worker.read_snapshot", return_value={}):
        worker = PaperAutopilotWorker(autopilot)

    counts = worker._resource_memory_owner_counts()
    assert counts["alpaca_ws_broad_discovery_rows"] == 32
    assert counts["alpaca_ws_broad_discovery_status_sample_rows"] == 16
    assert counts["alpaca_ws_broad_discovery_projection_compact"] == 1
    assert runtime["broker_truth_records_v1"] == truth["broker_truth_records_v1"]

    allocation_counter = {"value": 0}

    def allocated_blocks() -> int:
        allocation_counter["value"] += 40_000
        return 1_000_000 + allocation_counter["value"]

    with patch("engine.paper_autopilot_worker.sys.getallocatedblocks", side_effect=allocated_blocks):
        telemetry = None
        for memory_mb in (500, 550, 600, 650):
            telemetry = worker._record_resource_memory_telemetry({
                "worker_process": {"memory_mb": memory_mb},
                "resource_state": "RESOURCE_NORMAL",
            })

    assert telemetry is not None
    assert telemetry["python_allocated_blocks_delta_recent_window"] > 100_000
    assert telemetry["allocator_growth_signal"] == "SUSTAINED_PYTHON_BLOCK_GROWTH"
    assert telemetry["owner_counts"]["alpaca_ws_broad_discovery_rows"] == 32
    assert runtime["broker_truth_records_v1"] == truth["broker_truth_records_v1"]


def test_canary_checkpoint_does_not_duplicate_canonical_evidence_payloads():
    market = {"activation-a": {"HISTORICAL_BARS": {"record_id": "bar-a", "bars": [{"c": 10.0}]}}}
    fmp = {"activation-a": {"record_id": "fmp-a", "normalized_fields": {"sector": "Technology"}}}
    with tempfile.TemporaryDirectory() as state_dir:
        engine = object.__new__(PaperAutopilotEngine)
        engine.state_path = os.path.join(state_dir, "paper_autopilot_state.json")
        engine.paper_mode = True
        engine._enabled = False
        engine._adaptive_learning_capacity_policy = {}
        engine._runtime_state = {
            "legacy_swing_market_evidence": market,
            "legacy_swing_market_activity": {"cycle_state": "CYCLE_COMPLETE"},
            "legacy_swing_fmp_evidence": fmp,
            "legacy_swing_fmp_activity": {"request_count": 1},
            "legacy_swing_canary": {
                "market_records": market,
                "market_activity": {"cycle_state": "CYCLE_COMPLETE"},
                "fmp_records": fmp,
                "fmp_activity": {"request_count": 1},
                "reviews": {},
            },
        }
        engine._save_state_file(worker_owned=True)
        saved = json.loads(open(engine.state_path, encoding="utf-8").read())

    assert saved["legacy_swing_market_evidence"] == market
    assert saved["legacy_swing_fmp_evidence"] == fmp
    canary = saved["legacy_swing_canary"]
    assert "market_records" not in canary
    assert "fmp_records" not in canary
    assert canary["market_records_store"] == "legacy_swing_market_evidence"
    assert canary["fmp_records_store"] == "legacy_swing_fmp_evidence"


def test_runtime_candidate_trace_compacts_reconstructable_full_contracts():
    fat = {
        "candidate_id": "cand-1",
        "symbol": "AAPL",
        "lane_id": "DAY",
        "eligible": False,
        "decision_reason": "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
        "pretrade_decision_contract_v1": {
            "contract_state": "CONTRACT_INCOMPLETE",
            "contract_status": "INVALID",
            "missing_required_fields": ["expected_return_range"],
            "full_forecast_payload": {"large": "x" * 100_000},
        },
        "candidate_decision_evidence_v1": {
            "forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE",
            "equity_pretrade_forecast_v1": {"large": "x" * 100_000},
        },
        "eligibility_gate_attribution_v1": {
            "candidate_id": "cand-1",
            "first_failing_gate": {"code": "FORECAST", "detail": "missing"},
        },
        "large_derived_snapshot": {"payload": ["x"] * 100_000},
    }
    compact = _compact_runtime_execution_trace_v1({"per_candidate_decision_trace": [fat]})
    row = compact["per_candidate_decision_trace"][0]

    assert len(json.dumps(compact, separators=(",", ":"))) < 20_000
    assert row["candidate_id"] == "cand-1"
    assert row["pretrade_decision_contract_v1"]["missing_required_fields"] == ["expected_return_range"]
    assert "full_forecast_payload" not in row["pretrade_decision_contract_v1"]
    assert "candidate_decision_evidence_v1" in row
    assert "large_derived_snapshot" not in row
    assert compact["runtime_trace_storage_v1"]["retention_limit"] == 200
    assert compact["runtime_trace_storage_v1"]["reconstructable"] is True


def test_save_state_compacts_runtime_trace_without_changing_canonical_truth():
    truth = {"broker_truth_records_v1": [{"truth_id": "truth-1", "status": "BROKER_CONFIRMED_COMPLETE"}]}
    fat = {
        "candidate_id": "cand-2",
        "symbol": "MSFT",
        "lane_id": "DAY",
        "eligible": True,
        "pretrade_decision_contract_v1": {"contract_state": "CONTRACT_COMPLETE", "full": "x" * 50_000},
    }
    with tempfile.TemporaryDirectory() as state_dir:
        engine = object.__new__(PaperAutopilotEngine)
        engine.state_path = os.path.join(state_dir, "paper_autopilot_state.json")
        engine.paper_mode = True
        engine._enabled = False
        engine._adaptive_learning_capacity_policy = {}
        engine._runtime_state = {**truth, "last_execution_trace": {"per_candidate_decision_trace": [fat]}}
        engine._save_state_file(worker_owned=True)
        saved = json.loads(open(engine.state_path, encoding="utf-8").read())

    assert engine._runtime_state["broker_truth_records_v1"] == truth["broker_truth_records_v1"]
    saved_row = saved["last_execution_trace"]["per_candidate_decision_trace"][0]
    assert saved_row["candidate_id"] == "cand-2"
    assert "full" not in saved_row["pretrade_decision_contract_v1"]
    assert saved["last_execution_trace"]["runtime_trace_storage_v1"]["retained_item_count"] == 1
