from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PerformanceOptimizationPlanner:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.cache_paths = [
            "runtime_top_buys_snapshot.json",
            "learning_insights_last_good.json",
            "fmp_enrichment_cache_v1.json",
            "market_data_warehouse_manifest_v1.json",
        ]

    def _file_info(self, name: str) -> dict[str, Any]:
        path = os.path.join(self.state_dir, name)
        exists = os.path.exists(path)
        age = None
        if exists:
            try:
                age = max(0.0, datetime.now(UTC).timestamp() - os.path.getmtime(path))
            except Exception:
                age = None
        return {"path": path, "exists": exists, "age_seconds": round(age, 3) if age is not None else None, "bytes": os.path.getsize(path) if exists else 0}

    def status(self) -> dict[str, Any]:
        caches = {name: self._file_info(name) for name in self.cache_paths}
        existing = len([v for v in caches.values() if v.get("exists")])
        hit_estimate = round((existing / max(1, len(caches))) * 100.0, 3)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "performance_optimization_planning_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "performance_optimization_status_v1": True,
            "endpoint_load_time_policy": "prefer_runtime_snapshots_and_lazy_heavy_work",
            "cache_hit_rate_estimate": hit_estimate,
            "cache_inventory": caches,
            "refresh_cadence_recommendations": {
                "rankings": "snapshot_first_then_background_refresh",
                "top_buys": "runtime_snapshot_first",
                "learning": "fast_snapshot_default_lazy_advanced_metrics",
                "broad_collection": "governed_small_delta_batches_only",
            },
            "worker_efficiency_recommendations": ["dedupe_jobs_by_request_key", "batch_compatible_fmp_tasks", "precompute_slow_status_payloads"],
            "precompute_priorities": ["top_buys_runtime_snapshot", "rankings_runtime_snapshot", "learning_snapshot_fast_v1"],
            "lazy_load_opportunities": ["institutional_status_panels", "long_replay_reports", "warehouse_manifest_details"],
            "confidence_score": round(min(95.0, 45.0 + existing * 10.0), 3),
            "next_recommended_action": "precompute_snapshot_payloads_before adding any heavier dashboard reads",
        }
