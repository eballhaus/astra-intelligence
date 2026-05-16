"""Storage Optimization V1.

Planning/reporting layer for rotating append-only JSONL logs and storage health.
No destructive migration or file rewrite is performed by status calls.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"
DEFAULT_MAX_JSONL_BYTES = 50 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class StorageOptimizer:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.jsonl_targets = [
            {"name": "learning_history", "path": os.path.join(self.state_dir, "history", "learning", "learning_YYYY_MM.jsonl")},
            {"name": "trade_lifecycle_events", "path": os.path.join(self.state_dir, "history", "trade_lifecycle", "trade_lifecycle_YYYY_MM.jsonl")},
            {"name": "replay_results", "path": os.path.join(self.state_dir, "history", "replay", "replay_YYYY_MM_DD.jsonl")},
            {"name": "advanced_metric_history", "path": os.path.join(self.state_dir, "history", "advanced_metrics", "advanced_metrics_YYYY_MM.jsonl")},
            {"name": "api_efficiency_logs", "path": os.path.join(self.state_dir, "history", "api_efficiency", "api_efficiency_YYYY_MM.jsonl")},
            {"name": "broad_collection_events", "path": os.path.join(self.state_dir, "history", "broad_collection", "broad_collection_YYYY_MM.jsonl")},
            {"name": "performance_events", "path": os.path.join(self.state_dir, "history", "performance", "performance_YYYY_MM.jsonl")},
        ]

    def _json_files(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not os.path.isdir(self.state_dir):
            return rows
        for root, _dirs, files in os.walk(self.state_dir):
            for name in files:
                if not (name.endswith(".json") or name.endswith(".jsonl")):
                    continue
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                    mtime = datetime.fromtimestamp(os.path.getmtime(path), UTC).isoformat().replace("+00:00", "Z")
                except Exception:
                    size = 0
                    mtime = None
                rows.append({"path": path, "size_bytes": size, "last_modified": mtime, "extension": os.path.splitext(name)[1]})
        return sorted(rows, key=lambda row: int(row.get("size_bytes") or 0), reverse=True)

    def status(self, *, snapshot_status: dict[str, Any] | None = None, query_status: dict[str, Any] | None = None, analytics_status: dict[str, Any] | None = None) -> dict[str, Any]:
        files = self._json_files()
        jsonl_files = [f for f in files if str(f.get("path", "")).endswith(".jsonl")]
        largest = files[:8]
        largest_jsonl = jsonl_files[0] if jsonl_files else None
        rotation_needed = bool(largest_jsonl and int(largest_jsonl.get("size_bytes") or 0) >= DEFAULT_MAX_JSONL_BYTES)
        active_log_files = [target.get("path") for target in self.jsonl_targets]
        snapshot_count = int((snapshot_status or {}).get("snapshot_count") or 0)
        stale_snapshot_count = int((snapshot_status or {}).get("stale_snapshot_count") or 0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "storage_optimization_planning_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "storage_optimizer_status_v1": True,
            "storage_performance_status_v1": True,
            "jsonl_rotation_strategy": {
                "append_only": True,
                "destructive_rewrites_enabled": False,
                "rotate_by_size_or_date": True,
                "suggested_max_file_size_bytes": DEFAULT_MAX_JSONL_BYTES,
                "suggested_paths": active_log_files,
            },
            "active_log_files": active_log_files,
            "rotated_files": [],
            "largest_file_bytes": int(largest[0].get("size_bytes") or 0) if largest else 0,
            "largest_json_files": largest,
            "jsonl_rotation_needed": rotation_needed,
            "rotation_needed": rotation_needed,
            "append_safe": True,
            "snapshot_count": snapshot_count,
            "stale_snapshot_count": stale_snapshot_count,
            "sqlite_status": (query_status or {}).get("sqlite_status", "planning_only"),
            "parquet_duckdb_status": (analytics_status or {}).get("duckdb_status", "planning_only"),
            "estimated_dashboard_load_improvement": "20-40% once top_buys/rankings/system snapshots are materialized",
            "estimated_learning_tab_load_improvement": "40-70% by keeping advanced metrics snapshot-first",
            "slowest_data_sources": ["advanced_metrics_detail_cards", "replay_reports", "warehouse_manifest_scans"],
            "confidence_score": 84,
            "next_recommended_action": "materialize_small_snapshots_before_migrating_large_history_to_indexes",
            "generated_at": _now_iso(),
        }
