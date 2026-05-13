"""Learning Data Quality Monitor V1 (diagnostic-only, local-only)."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso_ts(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


class LearningDataQualityMonitor:
    """Diagnostic monitor for learning-data quality/freshness."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.candidate_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.outcome_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.replay_results_path = os.path.join(self.state_dir, "replay_results_v2.json")
        self._lock = threading.Lock()
        self._cache_payload: dict[str, Any] | None = None
        self._cache_ts = 0.0
        try:
            self.cache_ttl_seconds = max(
                15.0, min(300.0, float(os.getenv("ASTRA_LEARNING_QUALITY_TTL_SECONDS", "45")))
            )
        except Exception:
            self.cache_ttl_seconds = 45.0
        try:
            self.max_rows_per_file = max(
                200, min(20000, int(float(os.getenv("ASTRA_LEARNING_QUALITY_MAX_ROWS", "5000"))))
            )
        except Exception:
            self.max_rows_per_file = 5000

    def status(self) -> dict[str, Any]:
        with self._lock:
            cache_ready = bool(self._cache_payload)
            cache_age = (time.time() - self._cache_ts) if self._cache_ts > 0 else None
        return {
            "enabled": True,
            "mode": "diagnostic",
            "local_only": True,
            "api_calls_used": 0,
            "cache_ttl_seconds": int(self.cache_ttl_seconds),
            "cache_ready": cache_ready,
            "cache_age_seconds": round(max(0.0, cache_age), 3) if cache_age is not None else None,
            "max_rows_per_file": int(self.max_rows_per_file),
            "sources": {
                "trade_lifecycle_v1": self.lifecycle_path,
                "candidate_decision_ledger_v1": self.candidate_path,
                "outcome_labels_v1": self.outcome_path,
                "replay_results_v2": self.replay_results_path,
            },
            "generated_at": _now_iso(),
        }

    def report(self, policy_compare_payload: dict[str, Any] | None = None, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if (
                not force_refresh
                and self._cache_payload is not None
                and (now - self._cache_ts) <= self.cache_ttl_seconds
            ):
                return dict(self._cache_payload)

        payload = self._build_report(policy_compare_payload=policy_compare_payload or {})
        with self._lock:
            self._cache_payload = dict(payload)
            self._cache_ts = time.time()
        return payload

    def _read_jsonl_capped(self, path: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not os.path.exists(path):
            return rows
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    s = str(raw or "").strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        if len(rows) > self.max_rows_per_file:
            rows = rows[-self.max_rows_per_file :]
        return rows

    def _count_recent(self, rows: list[dict[str, Any]], ts_keys: tuple[str, ...], hours: int) -> int:
        if not rows:
            return 0
        now = datetime.now(UTC)
        cutoff = now.timestamp() - (hours * 3600)
        count = 0
        for row in rows:
            ts = None
            for key in ts_keys:
                ts = _parse_iso_ts(row.get(key))
                if ts is not None:
                    break
            if ts is None:
                continue
            if ts.timestamp() >= cutoff:
                count += 1
        return count

    def _load_replay_rows_available(self) -> int:
        if not os.path.exists(self.replay_results_path):
            return 0
        try:
            with open(self.replay_results_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return max(
                    _to_int(data.get("source_row_count"), 0),
                    _to_int(data.get("rows_evaluated"), 0),
                    _to_int(data.get("sample_count"), 0),
                )
        except Exception:
            return 0
        return 0

    def _build_report(self, policy_compare_payload: dict[str, Any]) -> dict[str, Any]:
        lifecycle_rows = self._read_jsonl_capped(self.lifecycle_path)
        candidate_rows = self._read_jsonl_capped(self.candidate_path)
        outcome_rows = self._read_jsonl_capped(self.outcome_path)

        lifecycle_1h = self._count_recent(lifecycle_rows, ("updated_at", "entry_timestamp", "signal_timestamp"), 1)
        lifecycle_6h = self._count_recent(lifecycle_rows, ("updated_at", "entry_timestamp", "signal_timestamp"), 6)
        lifecycle_24h = self._count_recent(lifecycle_rows, ("updated_at", "entry_timestamp", "signal_timestamp"), 24)

        candidate_1h = self._count_recent(candidate_rows, ("timestamp", "created_at", "entry_timestamp"), 1)
        candidate_6h = self._count_recent(candidate_rows, ("timestamp", "created_at", "entry_timestamp"), 6)
        candidate_24h = self._count_recent(candidate_rows, ("timestamp", "created_at", "entry_timestamp"), 24)

        outcome_1h = self._count_recent(outcome_rows, ("timestamp", "updated_at", "entry_timestamp"), 1)
        outcome_6h = self._count_recent(outcome_rows, ("timestamp", "updated_at", "entry_timestamp"), 6)
        outcome_24h = self._count_recent(outcome_rows, ("timestamp", "updated_at", "entry_timestamp"), 24)

        closed_trade_count_24h = 0
        open_trade_count = 0
        entry_quality_label_count = 0
        good_entry_count = 0
        bad_entry_count = 0
        for row in lifecycle_rows:
            stage = str(row.get("lifecycle_stage") or "").lower()
            exit_ts = str(row.get("exit_timestamp") or "").strip()
            if stage.startswith("closed") or exit_ts:
                ts = _parse_iso_ts(row.get("updated_at")) or _parse_iso_ts(exit_ts)
                if ts and (datetime.now(UTC).timestamp() - ts.timestamp()) <= 86400:
                    closed_trade_count_24h += 1
            else:
                open_trade_count += 1
            eq = row.get("entry_quality_score")
            if eq is not None:
                entry_quality_label_count += 1
                eq_f = _to_float(eq, 0.0)
                if eq_f >= 60.0:
                    good_entry_count += 1
                elif eq_f > 0:
                    bad_entry_count += 1

        replay_learning_rows_available = self._load_replay_rows_available()
        policy_compare_usable_samples = 0
        if isinstance(policy_compare_payload, dict):
            metrics = policy_compare_payload.get("metrics_by_policy")
            if isinstance(metrics, dict):
                current = metrics.get("current_policy")
                if isinstance(current, dict):
                    policy_compare_usable_samples = _to_int(current.get("sample_count"), 0)

        freshness_score = 0.0
        if lifecycle_24h > 0:
            freshness_score += 25.0
        if candidate_24h > 0:
            freshness_score += 25.0
        if outcome_24h > 0:
            freshness_score += 25.0
        if closed_trade_count_24h > 0 or open_trade_count > 0:
            freshness_score += 25.0

        blockers: list[str] = []
        if lifecycle_24h == 0:
            blockers.append("no_recent_lifecycle_rows_24h")
        if candidate_24h == 0:
            blockers.append("no_recent_candidate_rows_24h")
        if outcome_24h == 0:
            blockers.append("no_recent_outcome_labels_24h")
        if entry_quality_label_count == 0:
            blockers.append("no_entry_quality_labels_detected")
        if policy_compare_usable_samples < 20:
            blockers.append("policy_compare_samples_low")
        if replay_learning_rows_available <= 0:
            blockers.append("replay_learning_rows_unavailable")

        pipeline_health = freshness_score
        if blockers:
            pipeline_health = max(0.0, pipeline_health - min(50.0, float(len(blockers) * 8)))
        pipeline_health = round(max(0.0, min(100.0, pipeline_health)), 2)

        recommendation = "healthy_learning_collection"
        if lifecycle_24h == 0:
            recommendation = "needs_lifecycle_fix"
        elif outcome_24h == 0:
            recommendation = "needs_label_fix"
        elif freshness_score < 35.0:
            recommendation = "insufficient_runtime"
        elif blockers:
            recommendation = "continue_collecting"

        return {
            "enabled": True,
            "mode": "diagnostic",
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "freshness_windows": {"1h": True, "6h": True, "24h": True},
            "new_lifecycle_rows_1h": int(lifecycle_1h),
            "new_lifecycle_rows_6h": int(lifecycle_6h),
            "new_lifecycle_rows_24h": int(lifecycle_24h),
            "new_candidate_rows_1h": int(candidate_1h),
            "new_candidate_rows_6h": int(candidate_6h),
            "new_candidate_rows_24h": int(candidate_24h),
            "new_outcome_labels_1h": int(outcome_1h),
            "new_outcome_labels_6h": int(outcome_6h),
            "new_outcome_labels_24h": int(outcome_24h),
            "closed_trade_count_24h": int(closed_trade_count_24h),
            "open_trade_count": int(open_trade_count),
            "entry_quality_label_count": int(entry_quality_label_count),
            "good_entry_count": int(good_entry_count),
            "bad_entry_count": int(bad_entry_count),
            "replay_learning_rows_available": int(replay_learning_rows_available),
            "policy_compare_usable_samples": int(policy_compare_usable_samples),
            "learning_data_freshness_score": round(max(0.0, min(100.0, freshness_score)), 2),
            "learning_pipeline_health_score": pipeline_health,
            "blockers": blockers,
            "recommendation": recommendation,
            "row_caps": {
                "max_rows_per_file": int(self.max_rows_per_file),
            },
            "source_counts": {
                "lifecycle_rows_loaded": int(len(lifecycle_rows)),
                "candidate_rows_loaded": int(len(candidate_rows)),
                "outcome_rows_loaded": int(len(outcome_rows)),
            },
        }
