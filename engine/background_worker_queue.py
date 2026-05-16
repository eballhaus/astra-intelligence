"""Background Worker Queue V1.

Planning/control layer only. It does not start worker loops or execute jobs.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class BackgroundWorkerQueue:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "planning_only"
        self.job_specs = [
            ("rankings_refresh", 8.0, "precompute rankings cache from existing snapshot/fetch path"),
            ("top_buys_refresh", 6.0, "precompute top_buys runtime snapshot"),
            ("learning_refresh", 12.0, "refresh learning snapshot and last-good summary"),
            ("advanced_metrics_precompute", 20.0, "change-aware precompute of Learning Tab advanced diagnostic cards"),
            ("feature_refresh", 10.0, "update feature-store metadata after governed collection"),
            ("warehouse_refresh", 9.0, "refresh local market warehouse metadata"),
            ("replay_refresh", 18.0, "refresh replay/counterfactual metadata"),
        ]

    def _path_exists(self, name: str) -> bool:
        return os.path.exists(os.path.join(self.state_dir, name))

    def status(self) -> dict[str, Any]:
        jobs = []
        for job_id, runtime, purpose in self.job_specs:
            enabled = job_id in {"rankings_refresh", "top_buys_refresh", "learning_refresh", "advanced_metrics_precompute"}
            blocked_reason = "" if enabled else "requires_explicit_background_enable"
            if job_id in {"feature_refresh", "warehouse_refresh"} and not self._path_exists("market_data_warehouse_manifest_v1.json"):
                blocked_reason = "warehouse_manifest_not_populated"
            jobs.append(
                {
                    "job_id": job_id,
                    "enabled": bool(enabled),
                    "purpose": purpose,
                    "estimated_runtime_seconds": runtime,
                    "execution_mode": "planned_only",
                    "blocked_reason": blocked_reason,
                }
            )
        enabled_jobs = [j for j in jobs if bool(j.get("enabled"))]
        blocked_jobs = [j for j in jobs if not bool(j.get("enabled")) or j.get("blocked_reason")]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "planned_jobs": jobs,
            "queue_depth": len(jobs),
            "enabled_jobs": enabled_jobs,
            "blocked_jobs": blocked_jobs,
            "estimated_runtime_seconds": round(sum(float(j.get("estimated_runtime_seconds") or 0.0) for j in enabled_jobs), 3),
            "next_recommended_action": "keep_workers_planned_until_explicit_enable",
            "uncontrolled_background_execution_enabled": False,
            "generated_at": _now_iso(),
            "background_worker_queue_status_v1": True,
        }
