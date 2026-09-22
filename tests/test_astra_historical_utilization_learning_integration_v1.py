from __future__ import annotations

import json

from engine.astra_incremental_historical_learning_governor_v1 import (
    run_incremental_historical_learning_cycle_v1,
)
from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
from engine.astra_storage_cache_attribution_learning_efficiency_v1 import TARGET_COLD_FILES


HEALTHY = {"worker_health": "HEALTHY", "resource_state": "RESOURCE_NORMAL"}


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_previously_unregistered_learning_store_reaches_canonical_teacher(tmp_path):
    source = "adaptive_execution_exit_intelligence_v3.jsonl"
    _write_jsonl(tmp_path / source, [{
        "event_id": "exit-1",
        "symbol": "AAPL",
        "horizon": "DAY",
        "regime": "RISK_ON",
        "exit_type": "PROFIT_PROTECTION",
        "realized_return_pct": 1.25,
        "validated": True,
    }])
    (tmp_path / "storage_summary_indexes").mkdir()

    result = run_incremental_historical_learning_cycle_v1(
        str(tmp_path), resource_facts=HEALTHY, max_rows=10, max_bytes=4096,
    )

    assert result["partitions_processed"][0]["source"] == source
    assert result["partitions_processed"][0]["rows_examined"] == 1
    assert result["canonical_handoffs"]["compression"]["owner"] == "Knowledge Compression Engine V1"
    assert result["canonical_handoffs"]["teacher"]["owner"] == "Teacher Layer V1"
    assert result["broker_actions_added"] == 0
    assert result["execution_behavior_changed"] is False


def test_all_canonical_learning_targets_fit_manifest_reference_contract(tmp_path):
    for source in TARGET_COLD_FILES:
        _write_jsonl(tmp_path / source, [{"symbol": "AAPL"}])
    references = AstraKnowledgeWarehouseV1(state_dir=str(tmp_path)).source_references(
        allowed_paths=set(TARGET_COLD_FILES),
        max_sources=len(TARGET_COLD_FILES),
    )
    assert {row["path"] for row in references} == set(TARGET_COLD_FILES)
    assert all("rows" not in row for row in references)


def test_utilization_registry_distinguishes_stored_from_consumed(tmp_path):
    archive = tmp_path / "historical_context_phase2_v1/local_gap_runner_v1/historical-news/archive"
    archive.mkdir(parents=True)
    (archive / "index.sqlite3").write_bytes(b"sqlite-placeholder")
    _write_jsonl(tmp_path / "trade_archetype_regime_intelligence_v1.jsonl", [{"symbol": "AAPL"}])

    report = AstraKnowledgeWarehouseV1(state_dir=str(tmp_path)).historical_utilization_registry()
    rows = {row["dataset_family"]: row for row in report["rows"]}

    assert rows["trade_archetype_regime"]["utilization_status"] == "ACTIVE"
    assert rows["trade_archetype_regime"]["retrievable"] is True
    assert rows["trade_archetype_regime"]["reaches_teacher"] is True
    assert rows["historical_news_catalysts"]["utilization_status"] == "STORED_NOT_CONSUMED"
    assert rows["historical_news_catalysts"]["indexed"] is True
    assert rows["historical_news_catalysts"]["data_actually_consumed"] is False
    assert report["raw_archives_opened"] == 0
    assert report["full_history_scan_used"] is False


def test_provider_blocked_archive_fails_closed(tmp_path):
    report = AstraKnowledgeWarehouseV1(state_dir=str(tmp_path)).historical_utilization_registry({
        "analyst": {"status": "ENTITLEMENT_BLOCKED"},
    })
    analyst = next(row for row in report["rows"] if row["dataset_family"] == "analyst_revisions")
    assert analyst["utilization_status"] == "PROVIDER_BLOCKED"
    assert analyst["retrievable"] is False
    assert analyst["reaches_teacher"] is False
    assert analyst["data_actually_consumed"] is False


def test_historical_availability_never_claims_natural_truth_or_influence(tmp_path):
    _write_jsonl(tmp_path / "trade_lifecycle_excursion_v2.jsonl", [{
        "lifecycle_id": "life-1",
        "symbol": "AAPL",
        "realized_return_pct": 0.5,
    }])
    report = AstraKnowledgeWarehouseV1(state_dir=str(tmp_path)).historical_utilization_registry()
    row = next(item for item in report["rows"] if item["dataset_family"] == "trade_lifecycle_excursion")
    assert row["utilization_status"] == "ACTIVE"
    assert row["data_actually_consumed"] is False
    assert report["historical_evidence_natural_truth_eligible"] is False
    assert report["broker_calls_used"] == 0
    assert report["provider_calls_used"] == 0
