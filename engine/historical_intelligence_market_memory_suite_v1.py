from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
DEFAULT_MONTHLY_LIMIT_GB = 50.0
NORMAL_TARGET_GB = 40.0
WARNING_GB = 40.0
HARD_CEILING_GB = 44.0
EMERGENCY_RESERVE_GB = 6.0


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


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


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


def _status(statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        return value
    return default


class HistoricalIntelligenceMarketMemorySuiteV1:
    """Shadow-only historical intelligence and FMP bandwidth governance summary.

    This suite intentionally performs no provider calls. It consumes cached suite
    summaries and local FMP usage estimates, then writes a compact dashboard cache.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "historical_intelligence_market_memory_suite_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _fmp_budget(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        fmp = _status(statuses, "adaptive_market_intake_fmp_budget_status_v1")
        usage = _read_json(os.path.join(self.state_dir, "fmp_usage_state.json"))
        manifest = _read_json(os.path.join(self.state_dir, "fmp_efficiency_manifest_v1.json"))
        limit = max(1.0, _to_float(os.getenv("FMP_MONTHLY_BANDWIDTH_GB"), DEFAULT_MONTHLY_LIMIT_GB))
        used = max(
            _to_float(fmp.get("current_monthly_bandwidth_used_gb"), 0.0),
            _to_float(fmp.get("fmp_monthly_bandwidth_used_gb"), 0.0),
            _to_float(usage.get("fmp_estimated_used_total_gb"), 0.0),
            _to_float(manifest.get("total_bytes_estimated"), 0.0) / (1024.0 ** 3),
        )
        now = _now()
        days_in_month = 31
        if now.month in {4, 6, 9, 11}:
            days_in_month = 30
        elif now.month == 2:
            days_in_month = 29 if now.year % 4 == 0 else 28
        days_remaining = max(1, days_in_month - now.day + 1)
        remaining_under_hard = max(0.0, HARD_CEILING_GB - used)
        remaining_under_limit = max(0.0, limit - used)
        daily_safe = max(0.0, min(remaining_under_hard, max(0.0, NORMAL_TARGET_GB - used)) / float(days_remaining))
        usage_pct = _clamp((used / max(0.000001, limit)) * 100.0)
        warning = bool(used >= WARNING_GB or fmp.get("fmp_warning_active"))
        hard_stop = bool(used >= HARD_CEILING_GB or fmp.get("fmp_hard_stop_active") or fmp.get("runtime_protection_active"))
        projected = used + daily_safe * days_remaining
        expansion_allowed = bool(not hard_stop and used < HARD_CEILING_GB and daily_safe > 0.0)
        block_reason = "none"
        if hard_stop:
            block_reason = "fmp_hard_ceiling_or_runtime_protection_active"
        elif warning:
            block_reason = "warning_level_active_phase0_or_cache_only"
        elif daily_safe <= 0:
            block_reason = "no_safe_daily_bandwidth_remaining"
        return {
            "fmp_monthly_bandwidth_limit_gb": _round(limit, 3),
            "fmp_monthly_bandwidth_used_gb": _round(used, 6),
            "fmp_remaining_bandwidth_gb": _round(remaining_under_limit, 6),
            "fmp_daily_safe_budget_gb": _round(daily_safe, 6),
            "fmp_usage_pct": _round(usage_pct, 4),
            "fmp_warning_level_active": warning,
            "fmp_hard_stop_active": hard_stop,
            "fmp_expansion_allowed": expansion_allowed,
            "fmp_expansion_block_reason": block_reason,
            "projected_month_end_usage_gb": _round(projected, 6),
            "emergency_reserve_gb": EMERGENCY_RESERVE_GB,
            "hard_safety_ceiling_gb": HARD_CEILING_GB,
        }

    def _storage(self) -> dict[str, Any]:
        cache_dir = os.path.join(self.state_dir, "dashboard_cache")
        memory_dir = os.path.join(self.state_dir, "long_term_memory")
        total = 0
        count = 0
        for root_dir in (cache_dir, memory_dir):
            if not os.path.exists(root_dir):
                continue
            for root, _, files in os.walk(root_dir):
                for name in files:
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                        count += 1
                    except Exception:
                        continue
        pressure = _clamp(total / 8_000_000_000 * 100.0 + max(0, count - 500) * 0.02)
        return {
            "storage_pressure_score": _round(pressure, 3),
            "memory_pressure_score": _round(min(100.0, pressure * 0.85), 3),
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        fmp = self._fmp_budget(statuses)
        storage = self._storage()
        accelerated = _status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        memory = _status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        catalyst = _status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        market = _status(statuses, "market_context_learning_suite_v1")
        shadow = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        full = _status(statuses, "full_opportunity_lifecycle_learning_suite_v1")

        observed_symbols = max(
            _to_int(memory.get("symbol_profiles_tracked"), 0),
            _to_int(accelerated.get("symbol_profiles_tracked"), 0),
            _to_int(full.get("opportunities_tracked"), 0) // 4,
            0,
        )
        rotating_universe = min(1000, max(250, observed_symbols + _to_int(shadow.get("eligible_shadow_trades"), 0)))
        phase = "phase_0_diagnostics_only"
        if fmp["fmp_expansion_allowed"] and fmp["fmp_monthly_bandwidth_used_gb"] < 37.5:
            phase = "phase_1_high_value_symbols_daily_summaries"
        if fmp["fmp_warning_level_active"]:
            phase = "phase_0_warning_cache_only"
        if fmp["fmp_hard_stop_active"]:
            phase = "phase_0_hard_stop"

        symbols_selected = rotating_universe if phase.startswith("phase_1") else min(500, rotating_universe)
        symbols_completed = 0 if phase.startswith("phase_0") else min(symbols_selected, _to_int(memory.get("indexed_records"), 0))
        symbols_deferred = max(0, symbols_selected - symbols_completed)
        estimated_cost = _round(symbols_selected * 0.00035, 6)
        actual_used = 0.0
        catalyst_coverage = _clamp(_first(catalyst.get("catalyst_coverage_score"), market.get("catalyst_coverage_score"), default=0.0))
        unknown_rate = _clamp(_first(catalyst.get("unknown_catalyst_rate"), market.get("unknown_catalyst_rate"), default=100.0))
        memory_records = max(
            _to_int(memory.get("indexed_records"), 0),
            _to_int(accelerated.get("indexed_learning_records"), 0),
            _to_int(full.get("compact_summary_count"), 0),
        )
        market_quality = _clamp(
            _to_float(memory.get("symbol_memory_quality_score"), 0.0) * 0.35
            + _to_float(accelerated.get("symbol_personality_quality_score"), 0.0) * 0.25
            + catalyst_coverage * 0.20
            + max(0.0, 100.0 - unknown_rate) * 0.20
        )
        lesson_quality = _clamp(
            market_quality * 0.55
            + _to_float(shadow.get("evidence_quality_score"), 0.0) * 0.25
            + _to_float(catalyst.get("catalyst_truth_score"), 0.0) * 0.20
        )
        peer_group_score = _to_float(accelerated.get("peer_group_learning_score"), 0.0)
        regimes_detected = len([x for x in [
            catalyst.get("dominant_theme"),
            market.get("dominant_regime"),
            accelerated.get("best_regime_by_symbol"),
        ] if x])
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_historical_intelligence_market_memory",
            "generated_at": _now_iso(),
            "historical_phase": phase,
            "symbols_selected": int(symbols_selected),
            "symbols_completed": int(symbols_completed),
            "symbols_deferred": int(symbols_deferred),
            "compressed_market_memory_records": int(memory_records),
            "raw_records_discarded_after_summary": max(0, _to_int(accelerated.get("raw_records_summarized"), 0)),
            "storage_saved_estimate": _round(_to_float(accelerated.get("storage_savings_estimate"), 0.0), 3),
            "symbol_profiles_created": 0,
            "symbol_profiles_updated": _to_int(memory.get("symbol_profiles_tracked"), _to_int(accelerated.get("symbol_profiles_tracked"), 0)),
            "strongest_symbol_memory": _text(memory.get("strongest_symbol_profile") or accelerated.get("strongest_symbol_profile")),
            "weakest_symbol_memory": _text(memory.get("weakest_symbol_profile") or accelerated.get("weakest_symbol_profile")),
            "highest_giveback_symbol": _text(memory.get("highest_giveback_symbol") or accelerated.get("highest_giveback_symbol")),
            "most_stable_symbol": _text(accelerated.get("most_stable_symbol")),
            "highest_drift_symbol": _text(accelerated.get("highest_drift_symbol")),
            "peer_groups_created": len(accelerated.get("symbol_clusters") or {}) or 4,
            "peer_group_memory_quality": _round(peer_group_score, 3),
            "strongest_peer_group": _text(accelerated.get("strongest_peer_group_behavior") or accelerated.get("strongest_symbol_cluster")),
            "weakest_peer_group": _text(accelerated.get("weakest_symbol_cluster")),
            "transfer_confidence_score": _round(_to_float(accelerated.get("transferable_learning_confidence"), peer_group_score), 3),
            "regimes_detected": int(max(1, regimes_detected)),
            "regime_memory_records": int(max(0, _to_int(accelerated.get("regime_override_count"), 0) + regimes_detected)),
            "strongest_regime_edge": _text(_first(accelerated.get("best_regime_by_symbol"), market.get("dominant_regime"), default="insufficient_data")),
            "weakest_regime_edge": _text(accelerated.get("worst_regime_by_symbol")),
            "current_regime_match_score": _round(_to_float(market.get("market_context_confidence"), _to_float(catalyst.get("theme_confidence"), 0.0)), 3),
            "catalyst_records_created": _to_int(catalyst.get("catalyst_records"), _to_int(catalyst.get("evidence_count"), 0)),
            "catalyst_coverage_score": _round(catalyst_coverage, 3),
            "unknown_catalyst_rate": _round(unknown_rate, 3),
            "catalyst_decay_score": _round(_to_float(catalyst.get("catalyst_decay_learning_score"), 0.0), 3),
            "strongest_catalyst_memory": _text(catalyst.get("strongest_catalyst_type") or catalyst.get("dominant_catalyst")),
            "weakest_catalyst_memory": _text(catalyst.get("weakest_catalyst_type")),
            "catalyst_half_life_records": _to_int(catalyst.get("catalyst_records"), 0),
            "historical_replays_completed": _to_int(accelerated.get("accelerated_learning_events"), _to_int(shadow.get("virtual_paths_created"), 0)),
            "historical_replay_score": _round(_to_float(accelerated.get("replay_acceleration_score"), _to_float(shadow.get("virtual_path_quality_score"), 0.0)), 3),
            "best_historical_horizon": _text(_first(accelerated.get("best_horizon_by_symbol"), shadow.get("best_horizon"), default="insufficient_data")),
            "best_historical_exit_style": _text(_first(accelerated.get("best_exit_style_by_symbol"), shadow.get("best_exit_style"), default="insufficient_data")),
            "worst_historical_failure_pattern": _text(shadow.get("top_failure_pattern")),
            "replay_transfer_confidence": _round(_to_float(accelerated.get("transferable_pattern_confidence"), peer_group_score), 3),
            "historical_lesson_quality_score": _round(lesson_quality, 3),
            "stale_lessons": _to_int(memory.get("stale_lessons"), 0),
            "decayed_lessons": _to_int(accelerated.get("stale_symbol_lessons"), 0),
            "reinforced_lessons": _to_int(memory.get("reinforced_lessons"), 0),
            "drift_warnings": list(accelerated.get("symbols_with_behavior_drift") or [])[:10],
            "current_behavior_override_count": _to_int(accelerated.get("regime_override_count"), 0),
            "market_memory_quality_score": _round(market_quality, 3),
            "rotating_universe_size": int(rotating_universe),
            "symbols_scanned_today": 0,
            "candidate_diversity_score": _round(_to_float(fmp.get("candidate_diversity_score"), _to_float(accelerated.get("cross_symbol_learning_score"), 0.0)), 3),
            "sector_coverage_score": _round(_to_float(catalyst.get("sector_rotation_score"), _to_float(fmp.get("sector_coverage_score"), 0.0)), 3),
            "under_sampled_sector_count": _to_int(fmp.get("under_sampled_sector_count"), 0),
            "discovery_bandwidth_used_gb": 0.0,
            "estimated_bandwidth_cost_gb": estimated_cost,
            "actual_bandwidth_used_gb": actual_used,
            "expansion_safe": bool(fmp["fmp_expansion_allowed"] and estimated_cost <= fmp["fmp_daily_safe_budget_gb"]),
            "fmp_websocket_configured": bool(os.getenv("FMP_WEBSOCKET_URL") or os.getenv("FMP_WEBSOCKET_ENABLED")),
            "fmp_websocket_allowed": False,
            "fmp_websocket_plan_unknown": not bool(os.getenv("FMP_WEBSOCKET_URL") or os.getenv("FMP_WEBSOCKET_ENABLED")),
            "fmp_websocket_recommended_use": "future_active_position_and_shadow_price_path_monitoring_only",
            **fmp,
            **storage,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_provider_calls": 0,
            "learning_tab_provider_calls": 0,
            "live_trading_changed": False,
            "paper_execution_behavior_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "alpaca_paper_only_preserved": True,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": (
                "Run phase 0/1 compressed historical memory only; preserve FMP reserve and keep dashboard cache-only."
                if fmp["fmp_expansion_allowed"]
                else f"Keep historical expansion paused: {fmp['fmp_expansion_block_reason']}."
            ),
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
        }
        _write_json(self.cache_path, out)
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = _round(now - self._cache_ts, 3)
            out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
            return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try:
                    age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
                except Exception:
                    age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True
                    disk["cache_age_seconds"] = _round(age, 3)
                    disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
                    self._cache = dict(disk)
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "shadow_only_historical_intelligence_market_memory",
                "historical_phase": "degraded",
                "fmp_hard_stop_active": True,
                "fmp_expansion_allowed": False,
                "fmp_expansion_block_reason": f"historical_intelligence_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "dashboard_scan_rows": 0,
                "raw_archive_scanned": False,
                "raw_history_scanned": False,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = now
        return out
