"""JSONL Maintenance Suite V1 (dry-run only by default)."""

from __future__ import annotations

import json
import os
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class JsonlMaintenanceSuite:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.paths = [
            os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"),
            os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
            os.path.join(self.state_dir, "outcome_labels_v1.jsonl"),
        ]
        self.json_paths = [
            os.path.join(self.state_dir, "self_correction_history_v1.json"),
            os.path.join(self.state_dir, "replay_results_v2.json"),
        ]
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self.ttl_seconds = 45.0

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "dry_run_only",
            "jsonl_maintenance_status_v1": True,
            "institutional_intelligence_bundle_3": True,
            "local_only": True,
            "api_calls_used": 0,
            "destructive_repairs_enabled": False,
            "target_files": self.paths + self.json_paths,
            "generated_at": _now_iso(),
        }

    def dry_run(self, force_refresh: bool = False, max_scan_rows: int = 250000) -> dict[str, Any]:
        now = time.time()
        if not force_refresh and self._cache and (now - self._cache_ts) <= self.ttl_seconds:
            return dict(self._cache)
        files = []
        total_bad = 0
        total_dupes = 0
        total_bytes = 0
        estimated_savings = 0
        for path in self.paths:
            report = self._scan_jsonl(path, max_scan_rows=max_scan_rows)
            files.append(report)
            total_bad += int(report.get("malformed_rows", 0))
            total_dupes += int(report.get("duplicate_rows_estimated", 0))
            total_bytes += int(report.get("size_bytes", 0))
            estimated_savings += int(report.get("estimated_size_reduction_bytes", 0))
        for path in self.json_paths:
            files.append(self._scan_json(path))
        payload = {
            "enabled": True,
            "mode": "dry_run_only",
            "jsonl_maintenance_dry_run_v1": True,
            "institutional_intelligence_bundle_3": True,
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "files": files,
            "total_malformed_rows": total_bad,
            "total_duplicate_rows_estimated": total_dupes,
            "total_size_bytes": total_bytes,
            "estimated_file_size_reduction_bytes": estimated_savings,
            "would_write_files": False,
            "backup_required_before_repair": True,
        }
        self._cache = dict(payload)
        self._cache_ts = time.time()
        return payload

    def _scan_json(self, path: str) -> dict[str, Any]:
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        valid = False
        if exists:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    json.load(fh)
                valid = True
            except Exception:
                valid = False
        return {"path": path, "type": "json", "exists": exists, "size_bytes": size, "valid_json": valid}

    def _stable_key(self, row: dict[str, Any]) -> str:
        for key in ("ledger_id", "lifecycle_id", "trade_id", "position_id"):
            val = str(row.get(key) or "").strip()
            if val:
                return f"{key}:{val}"
        return "|".join(str(row.get(k) or "") for k in ("symbol", "timestamp_utc", "evaluated_at_utc", "entry_timestamp"))

    def _scan_jsonl(self, path: str, max_scan_rows: int) -> dict[str, Any]:
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        row_count = 0
        malformed = 0
        keys = set()
        dupes = 0
        sample_bad: deque[str] = deque(maxlen=5)
        if exists:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for raw in fh:
                        if row_count >= max_scan_rows:
                            break
                        row_count += 1
                        try:
                            obj = json.loads(str(raw or "").strip())
                        except Exception:
                            malformed += 1
                            sample_bad.append(str(raw or "")[:160])
                            continue
                        if not isinstance(obj, dict):
                            malformed += 1
                            continue
                        key = self._stable_key(obj)
                        if key and key in keys:
                            dupes += 1
                        elif key:
                            keys.add(key)
            except Exception:
                malformed += 1
        avg_line = int(size / max(1, row_count)) if row_count else 0
        return {
            "path": path,
            "type": "jsonl",
            "exists": exists,
            "size_bytes": size,
            "rows_scanned": row_count,
            "malformed_rows": malformed,
            "duplicate_rows_estimated": dupes,
            "bad_row_samples": list(sample_bad),
            "estimated_size_reduction_bytes": int((malformed + dupes) * avg_line),
            "dry_run_only": True,
        }
