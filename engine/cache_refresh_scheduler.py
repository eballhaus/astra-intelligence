"""Cache Refresh Scheduler V1.

Advisory-only cadence planner for hot-path caches and metadata catalogs.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _path_age_seconds(path: str) -> float | None:
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        return None


def _path_mtime_iso(path: str) -> str:
    try:
        return _iso(datetime.fromtimestamp(os.path.getmtime(path), UTC))
    except Exception:
        return ""


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


class LearningFreshnessPlanner:
    """Advisory-only learning and advanced diagnostics refresh schedule."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "change_aware_schedule_planning"
        self.full_learning_interval = 6 * 3600
        self.light_learning_interval = 20 * 60
        self.advanced_interval = 6 * 3600

    def status(self, *, market_status: str = "unknown") -> dict[str, Any]:
        learning_path = os.path.join(self.state_dir, "learning_insights_last_good.json")
        advanced_dir = os.path.join(self.state_dir, "snapshots", "advanced_metrics_cards")
        learning_age = _path_age_seconds(learning_path)
        advanced_age = _path_age_seconds(advanced_dir)
        now = datetime.now(UTC)
        next_full = now + timedelta(seconds=max(60, self.full_learning_interval - (learning_age or self.full_learning_interval)))
        next_light = now + timedelta(seconds=max(60, self.light_learning_interval - (learning_age or self.light_learning_interval)))
        next_adv = now + timedelta(seconds=max(60, self.advanced_interval - (advanced_age or self.advanced_interval)))
        data_changed = False
        try:
            source_paths = (
                os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
                os.path.join(self.state_dir, "outcome_labels_v1.jsonl"),
            )
            data_changed = any(
                (_path_age_seconds(path) is not None and (_path_age_seconds(path) or 0) < 1800)
                for path in source_paths
            )
        except Exception:
            data_changed = False
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "learning_freshness_status_v1": True,
            "market_status": market_status,
            "active_positions_count": 0,
            "symbols_fast_refresh": [],
            "symbols_slow_refresh": [],
            "websocket_symbols": [],
            "rest_fallback_symbols": [],
            "api_calls_used": 0,
            "calls_blocked": 0,
            "bandwidth_estimate": 0,
            "full_learning_refresh_interval_seconds": self.full_learning_interval,
            "light_learning_status_interval_seconds": self.light_learning_interval,
            "advanced_metrics_refresh_interval_seconds": self.advanced_interval,
            "last_learning_refresh": _path_mtime_iso(learning_path),
            "last_learning_age_seconds": round(learning_age, 3) if learning_age is not None else None,
            "last_advanced_refresh": _path_mtime_iso(advanced_dir),
            "last_advanced_age_seconds": round(advanced_age, 3) if advanced_age is not None else None,
            "next_learning_refresh": _iso(next_full),
            "next_light_learning_refresh": _iso(next_light),
            "next_advanced_refresh": _iso(next_adv),
            "data_changed_since_last_rebuild": bool(data_changed),
            "replay_jobs_preferred_window": "idle_off_hours_weekends",
            "tab_switch_full_reload_prevented": True,
            "heavy_metrics_rebuild_on_tab_switch": False,
            "generated_at": _iso(now),
            "next_recommended_action": "keep_learning_tab_memory_cache_until_ttl_or_manual_refresh",
        }
