"""Cache Refresh Scheduler V1.

Advisory-only cadence planner for hot-path caches and metadata catalogs.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


class CacheRefreshScheduler:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "advisory_only"
        self.sources = {
            "rankings": ("runtime_top_buys_snapshot.json", 120),
            "top_buys": ("runtime_top_buys_snapshot.json", 90),
            "learning_snapshot": ("learning_insights_last_good.json", 300),
            "advanced_metrics": (os.path.join("snapshots", "advanced_metrics_cards"), 300),
            "feature_store": ("feature_store_manifest_v1.json", 1800),
            "market_warehouse": ("market_data_warehouse_manifest_v1.json", 3600),
        }

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _mtime_iso(self, path: str) -> str:
        try:
            return datetime.fromtimestamp(os.path.getmtime(path), UTC).isoformat().replace("+00:00", "Z")
        except Exception:
            return ""

    def _age_seconds(self, path: str) -> float | None:
        try:
            return max(0.0, datetime.now(UTC).timestamp() - os.path.getmtime(path))
        except Exception:
            return None

    def _last_refresh(self, cache_name: str, path: str) -> str:
        payload = self._read_json(path)
        for key in ("updated_at", "generated_at", "last_updated_utc", "backend_time_utc"):
            parsed = _parse_ts(payload.get(key))
            if parsed is not None:
                return parsed.isoformat().replace("+00:00", "Z")
        return self._mtime_iso(path)

    def status(self) -> dict[str, Any]:
        jobs = []
        for name, (filename, interval) in self.sources.items():
            path = os.path.join(self.state_dir, filename)
            age = self._age_seconds(path)
            exists = os.path.exists(path)
            overdue = bool(age is None or age > interval)
            jobs.append(
                {
                    "cache_name": name,
                    "target_interval_seconds": int(interval),
                    "last_refresh_ts": self._last_refresh(name, path),
                    "age_seconds": round(age, 3) if age is not None else None,
                    "overdue": overdue,
                    "cache_hit_opportunity": "high" if exists and not overdue else ("medium" if exists else "low"),
                    "source_path": path,
                }
            )
        overdue_jobs = [j for j in jobs if bool(j.get("overdue"))]
        planned_jobs = [
            {
                "job_id": f"{j['cache_name']}_advisory_refresh",
                "enabled": False,
                "reason": "advisory_only_no_worker_started",
                "target_interval_seconds": j["target_interval_seconds"],
            }
            for j in jobs
        ]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "planned_jobs": planned_jobs,
            "estimated_runtime_seconds": round(len(overdue_jobs) * 4.0, 3),
            "next_recommended_action": "use_overdue_list_for_future_explicit_refresh_worker",
            "target_intervals": {j["cache_name"]: j["target_interval_seconds"] for j in jobs},
            "cache_status": jobs,
            "overdue_jobs": overdue_jobs,
            "cache_hit_opportunities": {j["cache_name"]: j["cache_hit_opportunity"] for j in jobs},
            "generated_at": _now_iso(),
            "cache_refresh_scheduler_status_v1": True,
        }
