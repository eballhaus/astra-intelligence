from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.paper_autopilot import PaperAutopilotEngine
from engine.paper_opportunity_allocation_engine_v1 import (
    PaperOpportunityAllocationEngineV1,
    select_equity_risk_refresh_candidates_v1,
)


def _bars(now: datetime, count: int, step_minutes: int) -> list[dict]:
    rows = []
    for index in range(count):
        stamp = now - timedelta(minutes=step_minutes * (count - index + 1))
        close = 100.0 + index
        rows.append({
            "provider_native_timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "open": close - 0.25,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100_000 + index,
            "is_complete": True,
        })
    return rows


def _fixture_state(tmp_path: Path, *, fresh: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    phase_dir = tmp_path / "historical_context_phase2_v1"
    phase_dir.mkdir()
    regime = {
        "symbol": "ENRICH",
        "feature": "deterministic_regime_label",
        "value": "TRENDING",
        "source_timestamp": int(now.timestamp()),
    }
    (phase_dir / "regime_features_v1.jsonl").write_text(json.dumps(regime) + "\n")
    (phase_dir / "historical_feature_store_v1.jsonl").write_text(json.dumps(regime) + "\n")
    (phase_dir / "volatility_context_v1.jsonl").write_text(
        json.dumps({
            "symbol": "ENRICH",
            "feature": "realized_volatility_20d_pct",
            "value": 3.5,
            "source_timestamp": int(now.timestamp()),
        }) + "\n"
    )
    (tmp_path / "fmp_enrichment_cache_v1.json").write_text(json.dumps({
        "profile::ENRICH": {
            "ts": time.time(),
            "payload": {"averageVolume": 500_000, "sector": "technology"},
        }
    }))
    quote_time = now if fresh else now - timedelta(minutes=10)
    current = {
        "symbol": "ENRICH",
        "quote_execution_eligible": True,
        "price": 124.0,
        "current_price": 124.0,
        "bid": 123.9,
        "ask": 124.1,
        "quote_timestamp": quote_time.isoformat().replace("+00:00", "Z"),
        "completed_bar_timestamp": _bars(now, 8, 15)[-1]["provider_native_timestamp"],
        "bar_evidence": {
            "provider": "ALPACA_PAPER_BROKER",
            "resolution": "15Min",
            "completed_bars": _bars(now, 8, 15),
        },
        "swing_bar_evidence": {
            "provider": "ALPACA_PAPER_BROKER",
            "resolution": "1Hour",
            "completed_bars": _bars(now, 24, 60),
        },
    }
    (tmp_path / "paper_autopilot_state.json").write_text(json.dumps({
        "equity_risk_envelopes_snapshot_v1": {
            "status": "CURRENT",
            "valid_until_epoch": time.time() + 60,
            "rows": [current],
        }
    }))
    return {
        "symbol": "ENRICH",
        "price": 124.0,
        "bid": 123.9,
        "ask": 124.1,
        "change_percent": 3.0,
        "volume": 2_000_000,
        "provider_native_timestamp": quote_time.isoformat().replace("+00:00", "Z"),
        "observation_authority": False,
        "executable_evidence": False,
    }


def test_bounded_authoritative_enrichment_builds_scalp_and_swing_rows(tmp_path: Path):
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))

    result = allocator.authoritative_broad_lane_candidates_v1([_fixture_state(tmp_path)])

    assert result["enrichment_attempted"] == {"SCALP": 1, "SWING": 1}
    assert result["enrichment_complete"] == {"SCALP": 1, "SWING": 1}
    assert len(result["rows"]) == 2
    assert {(row["symbol"], row["lane_id"]) for row in result["rows"]} == {
        ("ENRICH", "SCALP"),
        ("ENRICH", "SWING"),
    }
    for row in result["rows"]:
        assert row["lane_feature_enrichment_authoritative"] is True
        assert row["observation_authority"] is False
        assert row["executable_evidence"] is False
        assert row["candidate_evidence_fabricated"] is False
        assert "qualified" not in row
        assert "eligible" not in row
    assert result["rows"][0]["lane_feature_provenance_v1"]


def test_incomplete_or_stale_evidence_fails_closed(tmp_path: Path):
    row = _fixture_state(tmp_path, fresh=False)
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))

    result = allocator.authoritative_broad_lane_candidates_v1([row])

    assert result["rows"] == []
    assert result["enrichment_complete"] == {"SCALP": 0, "SWING": 0}
    assert result["enrichment_incomplete"]["SCALP"] == 1
    assert result["enrichment_incomplete"]["SWING"] == 1
    assert result["candidate_evidence_fabricated"] is False


def test_current_observer_replaces_stale_broad_quote_for_freshness(tmp_path: Path):
    row = _fixture_state(tmp_path, fresh=False)
    now = datetime.now(timezone.utc)
    current = json.loads((tmp_path / "paper_autopilot_state.json").read_text())
    risk_row = current["equity_risk_envelopes_snapshot_v1"]["rows"][0]
    risk_row["quote_timestamp"] = now.isoformat().replace("+00:00", "Z")
    current["equity_risk_envelopes_snapshot_v1"]["status"] = "CURRENT"
    (tmp_path / "paper_autopilot_state.json").write_text(json.dumps(current))

    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    result = allocator.authoritative_broad_lane_candidates_v1([row])

    assert result["enrichment_complete"] == {"SCALP": 1, "SWING": 1}
    assert {item["provider_native_timestamp"] for item in result["rows"]} == {risk_row["quote_timestamp"]}
    assert all(
        item["lane_feature_provenance_v1"]["provider_native_timestamp"]
        == "worker_equity_risk_observer"
        for item in result["rows"]
    )


def test_enrichment_budget_is_bounded(tmp_path: Path):
    row = _fixture_state(tmp_path)
    allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))

    result = allocator.authoritative_broad_lane_candidates_v1([row, row, row], max_symbols=1)

    assert result["observations_considered"] == 1
    assert result["shortlist_limit"] == 1
    assert result["bounded"] is True
    assert result["enrichment_attempted"] == {"SCALP": 1, "SWING": 1}


def test_worker_boundary_keeps_existing_qualification_owner(tmp_path: Path):
    row = _fixture_state(tmp_path)
    engine = PaperAutopilotEngine.__new__(PaperAutopilotEngine)
    engine.paper_opportunity_allocator = PaperOpportunityAllocationEngineV1(state_dir=str(tmp_path))
    engine._runtime_state = {
        "authoritative_lane_feature_source_v1": {
            "rows": [{**row, "authoritative_lane_enrichment_requested": True}],
            "observations_considered": 1,
            "shortlist_limit": 12,
        }
    }

    candidates, summary = engine._append_authoritative_broad_lane_candidates_v1([])

    assert len(candidates) == 2
    assert summary["status"] == "COMPLETE"
    assert all(row["lane_feature_enrichment_authoritative"] is True for row in candidates)
    assert all(row["observation_authority"] is False for row in candidates)
    assert all("qualified" not in row and "eligible" not in row for row in candidates)


def test_lane_enrichment_bypasses_risk_cache_for_new_and_stale_symbols():
    candidates = [
        {"symbol": "NEW", "authoritative_lane_enrichment_requested": True},
        {"symbol": "STALE", "authoritative_lane_enrichment_requested": True},
        {"symbol": "ORDINARY_NEW"},
        {"symbol": "ORDINARY_CACHED", "candidate_id": "cand-1"},
    ]
    previous_rows = [
        {"symbol": "STALE", "quote_timestamp": "2026-09-23T19:30:00Z"},
        {"symbol": "ORDINARY_CACHED", "quote_timestamp": "2026-09-23T19:30:00Z"},
    ]

    refresh, reusable = select_equity_risk_refresh_candidates_v1(candidates, previous_rows)

    assert [row["symbol"] for row in refresh] == ["NEW", "STALE"]
    assert [row["symbol"] for row in reusable] == ["ORDINARY_CACHED"]
    assert reusable[0]["candidate_id"] == "cand-1"
