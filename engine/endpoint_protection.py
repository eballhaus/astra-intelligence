"""Endpoint Protection & Precompute Planner V1.

Read-only planner for hot endpoint protection. It does not alter endpoint logic.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class EndpointProtectionPlanner:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "planning_only"
        self.protected_endpoints = [
            ("/api/rankings", "runtime_top_buys_snapshot.json", 15.0),
            ("/api/top_buys", "runtime_top_buys_snapshot.json", 15.0),
            ("/api/learning_snapshot_fast_v1", "learning_insights_last_good.json", 5.0),
        ]

    def _age_seconds(self, filename: str) -> float | None:
        path = os.path.join(self.state_dir, filename)
        try:
            return max(0.0, datetime.now(UTC).timestamp() - os.path.getmtime(path))
        except Exception:
            return None

    def status(self) -> dict[str, Any]:
        endpoint_rows = []
        recommended_jobs = []
        total_savings = 0.0
        max_risk = "low"
        for endpoint, cache_file, timeout_budget in self.protected_endpoints:
            age = self._age_seconds(cache_file)
            cache_ready = age is not None
            risk = "low" if cache_ready and age <= 180 else ("medium" if cache_ready else "high")
            if risk == "high":
                max_risk = "high"
            elif risk == "medium" and max_risk != "high":
                max_risk = "medium"
            savings = timeout_budget * (0.65 if cache_ready else 0.25)
            total_savings += savings
            job_id = endpoint.strip("/").replace("/", "_") + "_precompute"
            endpoint_rows.append(
                {
                    "endpoint": endpoint,
                    "cache_file": cache_file,
                    "cache_ready": cache_ready,
                    "cache_age_seconds": round(age, 3) if age is not None else None,
                    "timeout_budget_seconds": timeout_budget,
                    "timeout_risk_level": risk,
                    "estimated_savings_seconds": round(savings, 3),
                    "recommended_precompute_job": job_id,
                }
            )
            recommended_jobs.append(
                {
                    "job_id": job_id,
                    "endpoint": endpoint,
                    "enabled": False,
                    "reason": "planning_only_no_precompute_worker_started",
                    "estimated_runtime_seconds": min(timeout_budget, 8.0),
                }
            )
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "planned_jobs": recommended_jobs,
            "estimated_runtime_seconds": round(sum(float(j.get("estimated_runtime_seconds") or 0.0) for j in recommended_jobs), 3),
            "next_recommended_action": "precompute_hot_snapshots_only_when_worker_is_explicitly_enabled",
            "protected_endpoints": endpoint_rows,
            "estimated_savings": {"seconds_per_full_hot_path_cycle": round(total_savings, 3)},
            "recommended_precompute_jobs": recommended_jobs,
            "timeout_risk_level": max_risk,
            "uncontrolled_precompute_enabled": False,
            "generated_at": _now_iso(),
            "endpoint_protection_status_v1": True,
        }
