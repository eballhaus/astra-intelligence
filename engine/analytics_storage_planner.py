"""Parquet/DuckDB Analytics Planning Layer V1."""
from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class AnalyticsStoragePlanner:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.candidate_datasets = [
            "large_historical_ohlcv",
            "broad_market_research_tables",
            "replay_farm_results",
            "multi_brain_replay_outputs",
            "long_term_feature_history",
        ]

    def status(self) -> dict[str, Any]:
        duckdb_available = importlib.util.find_spec("duckdb") is not None
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "parquet_duckdb_analytics_planning_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "analytics_storage_plan_v1": True,
            "parquet_planned": True,
            "duckdb_available": duckdb_available,
            "duckdb_status": "available_for_future_local_analytics" if duckdb_available else "not_installed_optional_dependency",
            "candidate_datasets": self.candidate_datasets,
            "partition_strategy": {
                "dataset": True,
                "symbol": True,
                "year_month": True,
                "asset_type": True,
            },
            "planned_base_path": f"{self.state_dir}/analytics/parquet",
            "estimated_analytics_speedup": "10-100x for large replay and OHLCV scans after parquet materialization",
            "migration_mode": "planning_only_no_immediate_data_migration",
            "confidence_score": 78 if not duckdb_available else 86,
            "next_recommended_action": "keep_json_snapshots_for_ui_and_use_parquet_duckdb_only_for_large_offline_analytics",
            "generated_at": _now_iso(),
        }
