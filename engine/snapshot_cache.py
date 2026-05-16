"""Snapshot Cache Registry V1.

Small, UI-first snapshot registry with safe read helpers and optional atomic
write support. Status calls are read-only and never trigger heavy computation.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _age_seconds(path: str) -> float | None:
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        return None


class SnapshotCacheRegistry:
    """Registry for small JSON snapshots used by dashboard hot paths."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.snapshot_dir = os.path.join(self.state_dir, "snapshots")
        self.snapshots = [
            {
                "snapshot_name": "top_buys",
                "path": os.path.join(self.snapshot_dir, "top_buys_snapshot.json"),
                "freshness_ttl_seconds": 30,
                "source_endpoint": "/api/top_buys?buy_mode=balanced",
            },
            {
                "snapshot_name": "rankings",
                "path": os.path.join(self.snapshot_dir, "rankings_snapshot.json"),
                "freshness_ttl_seconds": 45,
                "source_endpoint": "/api/rankings",
            },
            {
                "snapshot_name": "learning_snapshot",
                "path": os.path.join(self.snapshot_dir, "learning_snapshot.json"),
                "freshness_ttl_seconds": 120,
                "source_endpoint": "/api/learning_snapshot_fast_v1",
            },
            {
                "snapshot_name": "advanced_metrics",
                "path": os.path.join(self.snapshot_dir, "advanced_metrics_snapshot.json"),
                "freshness_ttl_seconds": 300,
                "source_endpoint": "/api/advanced_metrics_snapshot_v1",
            },
            {
                "snapshot_name": "accelerated_learning",
                "path": os.path.join(self.snapshot_dir, "accelerated_learning_snapshot.json"),
                "freshness_ttl_seconds": 900,
                "source_endpoint": "/api/accelerated_learning_status_v1",
            },
            {
                "snapshot_name": "market_data_orchestration",
                "path": os.path.join(self.snapshot_dir, "market_data_orchestration_snapshot.json"),
                "freshness_ttl_seconds": 900,
                "source_endpoint": "/api/market_data_orchestration_status_v1",
            },
            {
                "snapshot_name": "trade_lifecycle",
                "path": os.path.join(self.snapshot_dir, "trade_lifecycle_snapshot.json"),
                "freshness_ttl_seconds": 600,
                "source_endpoint": "/api/trade_lifecycle_status_v1",
            },
            {
                "snapshot_name": "system_status",
                "path": os.path.join(self.snapshot_dir, "system_status_snapshot.json"),
                "freshness_ttl_seconds": 30,
                "source_endpoint": "/api/health",
            },
            {
                "snapshot_name": "performance_status",
                "path": os.path.join(self.snapshot_dir, "performance_snapshot.json"),
                "freshness_ttl_seconds": 300,
                "source_endpoint": "/api/performance_optimization_status_v1",
            },
        ]

    def _entry_status(self, entry: dict[str, Any]) -> dict[str, Any]:
        path = str(entry.get("path") or "")
        exists = bool(path and os.path.exists(path))
        age = _age_seconds(path) if exists else None
        ttl = float(entry.get("freshness_ttl_seconds") or 0)
        if not exists:
            status = "missing"
        elif age is not None and age <= ttl:
            status = "fresh"
        else:
            status = "stale"
        last_updated = None
        if exists:
            try:
                last_updated = datetime.fromtimestamp(os.path.getmtime(path), UTC).isoformat().replace("+00:00", "Z")
            except Exception:
                last_updated = None
        return {
            "snapshot_name": entry.get("snapshot_name"),
            "path": path,
            "last_updated": last_updated,
            "size_bytes": os.path.getsize(path) if exists else 0,
            "freshness_ttl_seconds": int(ttl),
            "status": status,
            "snapshot_age_seconds": round(age, 3) if age is not None else None,
            "last_error": None,
            "source_endpoint": entry.get("source_endpoint"),
        }

    def read_snapshot(self, snapshot_name: str) -> dict[str, Any] | None:
        entry = next((s for s in self.snapshots if s.get("snapshot_name") == snapshot_name), None)
        if not entry:
            return None
        path = str(entry.get("path") or "")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                age = _age_seconds(path)
                payload.setdefault("snapshot_age_seconds", round(age or 0.0, 3))
                payload.setdefault("freshness_status", self._entry_status(entry).get("status"))
                payload.setdefault("source", "snapshot_cache_file")
                return payload
        except Exception:
            return None
        return None

    def atomic_write_snapshot(self, snapshot_name: str, payload: dict[str, Any]) -> bool:
        """Safe helper for future schedulers; not called by status endpoints."""
        entry = next((s for s in self.snapshots if s.get("snapshot_name") == snapshot_name), None)
        if not entry or not isinstance(payload, dict):
            return False
        os.makedirs(self.snapshot_dir, exist_ok=True)
        path = str(entry.get("path") or "")
        fd, tmp_path = tempfile.mkstemp(prefix=f".{snapshot_name}.", suffix=".tmp", dir=self.snapshot_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, path)
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False

    def status(self) -> dict[str, Any]:
        entries = [self._entry_status(entry) for entry in self.snapshots]
        advanced_card_dir = os.path.join(self.snapshot_dir, "advanced_metrics_cards")
        advanced_card_snapshots = []
        if os.path.isdir(advanced_card_dir):
            for name in sorted(os.listdir(advanced_card_dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(advanced_card_dir, name)
                advanced_card_snapshots.append({
                    "snapshot_name": name[:-5],
                    "path": path,
                    "size_bytes": os.path.getsize(path) if os.path.exists(path) else 0,
                    "snapshot_age_seconds": round(_age_seconds(path) or 0.0, 3),
                    "status": "available",
                    "source_endpoint": "/api/advanced_metrics_snapshot_v1",
                })
        stale = [e for e in entries if e.get("status") == "stale"]
        missing = [e for e in entries if e.get("status") == "missing"]
        fresh = [e for e in entries if e.get("status") == "fresh"]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "snapshot_first_registry_planning",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "snapshot_cache_status_v1": True,
            "snapshot_count": len(entries),
            "advanced_card_snapshot_count": len(advanced_card_snapshots),
            "advanced_card_snapshots": advanced_card_snapshots,
            "fresh_snapshot_count": len(fresh),
            "stale_snapshot_count": len(stale),
            "missing_snapshot_count": len(missing),
            "snapshot_categories": [e.get("snapshot_name") for e in entries],
            "snapshots": entries,
            "atomic_write_supported": True,
            "ui_read_policy": "prefer_small_snapshot_then_stale_snapshot_then_runtime_cache_then_bounded_seed",
            "confidence_score": 82,
            "next_recommended_action": "wire_existing_safe_schedulers_to_atomically_refresh_small_ui_snapshots",
            "generated_at": _now_iso(),
        }
