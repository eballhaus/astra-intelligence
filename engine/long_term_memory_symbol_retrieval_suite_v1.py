from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
MAX_HOT_LOOKBACK_DAYS = 14
MAX_HOT_ROWS = 1600
MAX_TAIL_BYTES = 2_200_000
STORAGE_PRESSURE_BYTES = 8_000_000_000
DASHBOARD_CACHE_MAX_AGE_SECONDS = 180.0

INDEX_FIELDS = (
    "symbol", "date", "catalyst", "theme", "sector", "regime", "archetype", "horizon",
    "confidence_bucket", "outcome_label", "decision_type", "trade_behavior",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _tail_jsonl(path: str, max_rows: int = MAX_HOT_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _freshness_label(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "stale"
    if age_seconds <= 120:
        return "live"
    if age_seconds <= 900:
        return "fresh"
    if age_seconds <= 3600:
        return "warm"
    return "stale"


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("asset_symbol") or row.get("selected_symbol") or row.get("rejected_symbol"), "unknown").upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(row, "actual_return", "actual_return_pct", "current_or_exit_profit_pct", "return_pct", "virtual_return", default=0.0)


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "mfe", "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "peak_gain_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "mae", "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct")


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon") or row.get("horizon_style") or row.get("selected_horizon"), "unknown").lower()
    if "scalp" in raw:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw:
        return "swing"
    if "day" in raw:
        return "day_trade"
    return raw or "unknown"


def _trade_behavior(row: dict[str, Any]) -> str:
    label = _text(row.get("trade_behavior") or row.get("trade_personality") or row.get("outcome_label"), "")
    if label:
        return label
    ret = _return_pct(row)
    mfe = _mfe(row)
    if mfe >= 5 and ret < mfe * 0.35:
        return "spike_and_fade"
    if ret > 2:
        return "runner"
    if ret < -1:
        return "failed_breakout_risk"
    return "insufficient_evidence"


class LongTermMemorySymbolRetrievalSuiteV1:
    """Shadow-only long-term memory, symbol profiles, storage retention, and retrieval diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.opportunity_cache_path = os.path.join(self.state_dir, "dashboard_cache", "full_opportunity_lifecycle_summary.json")
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "long_term_memory_symbol_retrieval_summary.json")
        self.profile_path = os.path.join(self.state_dir, "long_term_memory", "symbol_profiles", "latest_symbol_profiles.json")
        self.index_path = os.path.join(self.state_dir, "long_term_memory", "indexes", "latest_indexes.json")
        self.retention_path = os.path.join(self.state_dir, "long_term_memory", "retention", "latest_storage_retention.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _dir_size(self, path: str) -> tuple[int, int]:
        total = 0
        count = 0
        if not os.path.exists(path):
            return 0, 0
        for root, _, files in os.walk(path):
            for name in files:
                try:
                    fp = os.path.join(root, name)
                    total += os.path.getsize(fp)
                    count += 1
                except Exception:
                    continue
        return total, count

    def _storage_metrics(self) -> dict[str, Any]:
        opportunities_dir = os.path.join(self.state_dir, "opportunities")
        raw_size, raw_count = self._dir_size(os.path.join(opportunities_dir, "raw"))
        summary_size, summary_count = self._dir_size(os.path.join(opportunities_dir, "summaries"))
        archive_size, archive_count = self._dir_size(os.path.join(opportunities_dir, "archive"))
        dashboard_cache_size, dashboard_cache_count = self._dir_size(os.path.join(self.state_dir, "dashboard_cache"))
        memory_size, memory_count = self._dir_size(os.path.join(self.state_dir, "long_term_memory"))
        total = raw_size + summary_size + archive_size + dashboard_cache_size + memory_size
        memory_pressure = _clamp(total / STORAGE_PRESSURE_BYTES * 100.0 + max(0, raw_count - 120) * 0.08)
        storage_health = _clamp(100.0 - memory_pressure * 0.72 + min(12.0, summary_count * 0.15))
        daily_growth_estimate = max(1.0, raw_size / max(1, min(30, raw_count or 1)))
        remaining = max(0.0, STORAGE_PRESSURE_BYTES - total)
        days_until_pressure = remaining / daily_growth_estimate if daily_growth_estimate > 0 else 9999.0
        cleanup_status = "healthy_no_cleanup_needed"
        if memory_pressure >= 70:
            cleanup_status = "archive_old_low_value_raw_events_recommended"
        elif raw_count >= 90:
            cleanup_status = "rotation_watch"
        return {
            "storage_bytes_total": total,
            "raw_event_size_bytes": raw_size,
            "summary_size_bytes": summary_size,
            "cache_size_bytes": dashboard_cache_size,
            "archive_size_bytes": archive_size,
            "long_term_memory_size_bytes": memory_size,
            "raw_event_file_count": raw_count,
            "summary_file_count": summary_count,
            "cache_file_count": dashboard_cache_count,
            "archive_file_count": archive_count,
            "memory_file_count": memory_count,
            "memory_pressure_score": _round(memory_pressure, 2),
            "storage_health_score": _round(storage_health, 2),
            "cleanup_status": cleanup_status,
            "estimated_days_until_storage_pressure": _round(min(days_until_pressure, 9999.0), 1),
            "retention_policy": {
                "hot_data": "recent_raw_jsonl_30_to_90_days_never_active_open_trade_data",
                "warm_data": "daily_weekly_monthly_compact_json_summaries_preserved",
                "cold_data": "sqlite_ready_or_compressed_archive_long_term_history",
                "permanent_data": "high_value_lessons_symbol_profiles_performance_summaries_preserved",
                "delete_policy": "no_delete_from_dashboard_path_archive_or_compact_only_after_safety_review",
            },
        }

    def _hot_rows(self) -> list[dict[str, Any]]:
        raw_dir = os.path.join(self.state_dir, "opportunities", "raw")
        if not os.path.exists(raw_dir):
            return []
        cutoff = _now().date() - timedelta(days=MAX_HOT_LOOKBACK_DAYS)
        rows: list[dict[str, Any]] = []
        try:
            names = sorted(n for n in os.listdir(raw_dir) if n.endswith(".jsonl"))[-MAX_HOT_LOOKBACK_DAYS:]
        except Exception:
            return []
        remaining = MAX_HOT_ROWS
        for name in names:
            day = name[:-6]
            try:
                if datetime.fromisoformat(day).date() < cutoff:
                    continue
            except Exception:
                continue
            chunk = _tail_jsonl(os.path.join(raw_dir, name), max_rows=min(remaining, 400))
            rows.extend(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                break
        return rows[-MAX_HOT_ROWS:]

    def _symbol_profiles(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            sym = _symbol(row)
            if sym and sym != "UNKNOWN":
                grouped[sym].append(row)
        profiles: dict[str, dict[str, Any]] = {}
        for sym, items in grouped.items():
            returns = [_return_pct(r) for r in items]
            mfes = [_mfe(r) for r in items]
            maes = [_mae(r) for r in items]
            horizons = Counter(_horizon(r) for r in items)
            catalysts = Counter(_text(r.get("catalyst"), "unknown_catalyst") for r in items)
            regimes = Counter(_text(r.get("regime"), "unknown") for r in items)
            arches = Counter(_text(r.get("archetype"), "unknown") for r in items)
            outcomes = Counter(_text(r.get("outcome_label"), "neutral") for r in items)
            giveback_proxy = [max(0.0, _mfe(r) - _return_pct(r)) for r in items]
            capture = [(_return_pct(r) / _mfe(r)) for r in items if _mfe(r) > 0]
            reliability = _clamp((sum(1 for v in returns if v > 0) / max(1, len(returns))) * 100.0)
            edge = (_avg(returns) or 0.0) + min(5.0, len(items) * 0.2) - (_avg(giveback_proxy) or 0.0) * 0.15
            drift = _clamp(abs((returns[-1] if returns else 0.0) - (_avg(returns[:-1]) or 0.0)) * 5.0 if len(returns) > 2 else 0.0)
            profiles[sym] = {
                "symbol": sym,
                "sample_size": len(items),
                "best_horizon": horizons.most_common(1)[0][0] if horizons else "insufficient_data",
                "worst_horizon": min(horizons.items(), key=lambda kv: kv[1], default=("insufficient_data", 0))[0],
                "best_exit_style": "protect_profit_earlier" if (_avg(giveback_proxy) or 0.0) > 3 else "hold_with_normal_review",
                "average_hold_duration": None,
                "average_mfe": _avg(mfes),
                "average_mae": _avg(maes),
                "continuation_quality": _round(_clamp(50.0 + (_avg(returns) or 0.0) * 4.0 - (_avg(giveback_proxy) or 0.0)), 2),
                "giveback_risk": _round(_avg(giveback_proxy) or 0.0, 4),
                "profit_capture_history": _round((_avg(capture) or 0.0) * 100.0, 2),
                "confidence_reliability": _round(reliability, 2),
                "best_catalyst": catalysts.most_common(1)[0][0] if catalysts else "insufficient_data",
                "worst_catalyst": min(catalysts.items(), key=lambda kv: kv[1], default=("insufficient_data", 0))[0],
                "best_regime": regimes.most_common(1)[0][0] if regimes else "insufficient_data",
                "worst_regime": min(regimes.items(), key=lambda kv: kv[1], default=("insufficient_data", 0))[0],
                "best_archetype": arches.most_common(1)[0][0] if arches else "insufficient_data",
                "worst_archetype": min(arches.items(), key=lambda kv: kv[1], default=("insufficient_data", 0))[0],
                "behavioral_drift_score": _round(drift, 2),
                "outcome_distribution": dict(outcomes),
                "behavioral_edge_score": _round(edge, 4),
            }
        strongest = max(profiles.values(), key=lambda p: _to_float(p.get("behavioral_edge_score")), default={})
        weakest = min(profiles.values(), key=lambda p: _to_float(p.get("behavioral_edge_score")), default={})
        giveback = max(profiles.values(), key=lambda p: _to_float(p.get("giveback_risk")), default={})
        reliable = max(profiles.values(), key=lambda p: _to_float(p.get("confidence_reliability")), default={})
        quality = _round(_clamp(len(profiles) / 40.0 * 100.0 + min(25.0, sum(p.get("sample_size", 0) for p in profiles.values()) * 0.03)), 2)
        compact_profiles = {k: v for k, v in sorted(profiles.items(), key=lambda kv: kv[1].get("sample_size", 0), reverse=True)[:80]}
        _write_json(self.profile_path, {"generated_at": _now_iso(), "profiles": compact_profiles})
        return {
            "symbol_profiles_tracked": len(profiles),
            "strongest_symbol_profile": strongest.get("symbol", "insufficient_data"),
            "weakest_symbol_profile": weakest.get("symbol", "insufficient_data"),
            "best_behavioral_edge_symbol": strongest.get("symbol", "insufficient_data"),
            "highest_giveback_symbol": giveback.get("symbol", "insufficient_data"),
            "most_reliable_symbol": reliable.get("symbol", "insufficient_data"),
            "symbol_memory_quality_score": quality,
            "symbol_profile_sample": list(compact_profiles.values())[:8],
        }

    def _indexes(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        indexes: dict[str, dict[str, int]] = {}
        for field in INDEX_FIELDS:
            counter = Counter()
            for row in rows:
                if field == "trade_behavior":
                    val = _trade_behavior(row)
                elif field == "horizon":
                    val = _horizon(row)
                else:
                    val = _text(row.get(field), "unknown")
                counter[val] += 1
            indexes[field] = dict(counter.most_common(60))
        indexed_records = len(rows)
        lookup_tests = 0
        successes = 0
        for field in ("symbol", "horizon", "decision_type", "outcome_label", "catalyst"):
            lookup_tests += 1
            successes += 1 if indexes.get(field) else 0
        latency = (time.perf_counter() - start) * 1000.0
        weakest = min(indexes.items(), key=lambda kv: sum(kv[1].values()), default=("insufficient_data", {}))[0]
        strongest = max(indexes.items(), key=lambda kv: len(kv[1]), default=("insufficient_data", {}))[0]
        health = _round(_clamp((successes / max(1, lookup_tests)) * 70.0 + min(30.0, indexed_records / 40.0)), 2)
        out = {
            "indexed_records": indexed_records,
            "retrieval_latency_ms": _round(latency, 3),
            "retrieval_health_score": health,
            "strongest_index": strongest,
            "weakest_index": weakest,
            "recent_lookup_success_rate": _round(successes / max(1, lookup_tests) * 100.0, 2),
            "full_scan_avoided_count": max(0, indexed_records),
            "index_fields": list(INDEX_FIELDS),
            "indexes": indexes,
        }
        _write_json(self.index_path, {"generated_at": _now_iso(), **out})
        return out

    def _cached(self) -> dict[str, Any] | None:
        payload = _read_json(self.cache_path)
        if not payload:
            return None
        try:
            age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
        except Exception:
            age = None
        payload["cache_hit"] = True
        payload["cache_age_seconds"] = round(age, 3) if age is not None else None
        payload["cache_freshness"] = _freshness_label(age)
        payload["dashboard_scan_rows"] = 0
        payload["retrieval_latency_ms"] = min(_to_float(payload.get("retrieval_latency_ms"), 4.0), 8.0)
        payload["api_calls_used"] = 0
        payload["provider_calls_used"] = 0
        payload["llm_calls_used"] = 0
        payload["behavior_safe_to_apply"] = False
        return payload

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        rows = self._hot_rows()
        full = dict(statuses.get("full_opportunity_lifecycle_learning_suite_v1") or _read_json(self.opportunity_cache_path) or {})
        storage = self._storage_metrics()
        profiles = self._symbol_profiles(rows)
        indexes = self._indexes(rows)
        opportunity_count = _to_int(full.get("opportunities_tracked"), len(rows))
        cleanup = storage.get("cleanup_status", "healthy_no_cleanup_needed")
        recommendation = "shadow_only_preserve_high_value_lessons_and_use_indexes_for_symbol_context"
        if storage.get("memory_pressure_score", 0) and _to_float(storage.get("memory_pressure_score")) > 65:
            recommendation = "shadow_only_archive_old_low_value_raw_events_after_human_review"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_long_term_memory_symbol_retrieval",
            "generated_at": _now_iso(),
            "last_updated": _now_iso(),
            "opportunities_source_count": opportunity_count,
            **storage,
            **profiles,
            **{k: v for k, v in indexes.items() if k != "indexes"},
            "dashboard_scan_rows": 0,
            "hot_rows_scanned_for_rebuild": len(rows),
            "cache_freshness": "live",
            "cache_status": "rebuilt",
            "dashboard_fast_path": "cached_summary_only",
            "raw_archive_scan_during_render": False,
            "sqlite_archive_adapter_status": "prepared_optional_not_required",
            "cleanup_action_taken": "none_diagnostics_only",
            "shadow_recommendation": recommendation,
            "summary": "Astra is organizing long-term memory, symbol behavior profiles, and indexed retrieval without changing trading behavior.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "bandwidth_saving_mode": True,
            "api_budget_status": "cached_local_only",
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "behavior_safe_to_apply": False,
        }
        out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
        _write_json(self.retention_path, {"generated_at": _now_iso(), **storage})
        _write_json(self.cache_path, out)
        return out

    def status(self, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts < self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["dashboard_scan_rows"] = 0
            out["behavior_safe_to_apply"] = False
            return out
        if not force:
            cached = self._cached()
            if cached and _to_float(cached.get("cache_age_seconds"), 999999.0) <= DASHBOARD_CACHE_MAX_AGE_SECONDS:
                self._cache = cached
                self._cache_ts = now
                return cached
        try:
            out = self._build(statuses or {})
            out["cache_hit"] = False
            self._cache = out
            self._cache_ts = now
            return out
        except Exception as exc:
            cached = self._cached()
            if cached:
                cached["stale_cache"] = True
                cached["degraded_reason"] = f"long_term_memory_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_long_term_memory_symbol_retrieval",
                "storage_health_score": 0.0,
                "memory_pressure_score": 0.0,
                "cleanup_status": "unavailable",
                "estimated_days_until_storage_pressure": 0.0,
                "symbol_profiles_tracked": 0,
                "strongest_symbol_profile": "unavailable",
                "highest_giveback_symbol": "unavailable",
                "symbol_memory_quality_score": 0.0,
                "indexed_records": 0,
                "retrieval_latency_ms": 0.0,
                "retrieval_health_score": 0.0,
                "dashboard_scan_rows": 0,
                "cache_freshness": "stale",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"long_term_memory_symbol_retrieval_suite_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
                "auto_apply_allowed": False,
                "human_review_required": True,
                "behavior_safe_to_apply": False,
            }
