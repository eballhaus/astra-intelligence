from __future__ import annotations

import calendar
import json
import os
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
FMP_MONTHLY_BANDWIDTH_GB = float(os.getenv("FMP_MONTHLY_BANDWIDTH_GB", "50"))
FMP_TARGET_UTILIZATION_LOW = float(os.getenv("FMP_TARGET_UTILIZATION_LOW", "0.75"))
FMP_TARGET_UTILIZATION_HIGH = float(os.getenv("FMP_TARGET_UTILIZATION_HIGH", "0.80"))
FMP_HARD_SAFETY_CEILING = float(os.getenv("FMP_HARD_SAFETY_CEILING", "0.88"))
MAX_TAIL_BYTES = 2_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _tail_text(path: str, max_bytes: int = MAX_TAIL_BYTES) -> str:
    if not os.path.exists(path):
        return ""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if not isinstance(pack, dict):
            continue
        for section in ("final", "qualified", "watchlist", "fill"):
            values = pack.get(section)
            if isinstance(values, list):
                rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _safe_text(row.get("symbol")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


class AdaptiveMarketIntakeFmpBudgetSuiteV1:
    """Local-only FMP utilization and intake recommendation layer.

    This suite never calls providers and never starts workers. It reads local
    usage/governor/snapshot files, then recommends bounded exploration intensity.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.fmp_usage_path = os.path.join(self.state_dir, "fmp_usage_state.json")
        self.api_governor_path = os.path.join(self.state_dir, "api_usage_governor.json")
        self.fmp_efficiency_manifest_path = os.path.join(self.state_dir, "fmp_efficiency_manifest_v1.json")
        self.fmp_cache_index_path = os.path.join(self.state_dir, "fmp_cache_index.json")
        self.runtime_health_path = os.path.join(self.state_dir, "runtime_health.log")
        self.backend_log_path = os.path.join(self.state_dir, "backend.log")

    def status(
        self,
        top_buys_payload: dict[str, Any] | None = None,
        observation_payload: dict[str, Any] | None = None,
        execution_payload: dict[str, Any] | None = None,
        multi_horizon_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._status(
                top_buys_payload=top_buys_payload or {},
                observation_payload=observation_payload or {},
                execution_payload=execution_payload or {},
                multi_horizon_payload=multi_horizon_payload or {},
            )
        except Exception as exc:
            return self._fallback(f"adaptive_market_intake_status_unavailable: {str(exc)[:140]}")

    def _status(
        self,
        top_buys_payload: dict[str, Any],
        observation_payload: dict[str, Any],
        execution_payload: dict[str, Any],
        multi_horizon_payload: dict[str, Any],
    ) -> dict[str, Any]:
        fmp_usage = _read_json(self.fmp_usage_path)
        governor = _read_json(self.api_governor_path)
        manifest = _read_json(self.fmp_efficiency_manifest_path)
        cache_index = _read_json(self.fmp_cache_index_path)
        smart_budget_enabled = str(os.getenv("ASTRA_FMP_SMART_BUDGET_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        emergency_disable_explicit = "ASTRA_TEMP_FMP_REST_DISABLED" in os.environ
        emergency_conserve_active = bool(
            str(os.getenv("ASTRA_TEMP_FMP_REST_DISABLED", "0" if smart_budget_enabled else "1")).strip().lower()
            in {"1", "true", "yes", "on"}
            and emergency_disable_explicit
        )
        now = _now()
        _, days_in_month = calendar.monthrange(now.year, now.month)
        days_remaining = max(1, days_in_month - now.day + 1)

        limit_gb = max(1.0, _to_float(os.getenv("FMP_MONTHLY_BANDWIDTH_GB"), FMP_MONTHLY_BANDWIDTH_GB))
        low_target_pct = _clamp(_to_float(os.getenv("FMP_TARGET_UTILIZATION_LOW"), FMP_TARGET_UTILIZATION_LOW) * 100.0)
        high_target_pct = _clamp(_to_float(os.getenv("FMP_TARGET_UTILIZATION_HIGH"), FMP_TARGET_UTILIZATION_HIGH) * 100.0)
        hard_ceiling_pct = _clamp(_to_float(os.getenv("FMP_HARD_SAFETY_CEILING"), FMP_HARD_SAFETY_CEILING) * 100.0)
        low_target_gb = limit_gb * (low_target_pct / 100.0)
        high_target_gb = limit_gb * (high_target_pct / 100.0)
        hard_ceiling_gb = limit_gb * (hard_ceiling_pct / 100.0)

        usage_total_gb = _to_float(fmp_usage.get("fmp_estimated_used_total_gb"), 0.0)
        manifest_total_gb = _to_float(manifest.get("total_bytes_estimated"), 0.0) / (1024.0 ** 3)
        used_gb = max(usage_total_gb, manifest_total_gb)
        current_utilization_pct = _clamp((used_gb / max(0.000001, limit_gb)) * 100.0)
        remaining_gb = max(0.0, limit_gb - used_gb)
        target_remaining_gb = max(0.0, high_target_gb - used_gb)
        recommended_daily_budget_gb = max(0.0, target_remaining_gb / float(days_remaining))

        provider_rows = list(governor.get("provider_rows") or []) if isinstance(governor.get("provider_rows"), list) else []
        provider_seen = len(provider_rows)
        degraded_count = _to_int((governor.get("provider_health_summary") or {}).get("degraded_count"), 0)
        healthy_count = _to_int((governor.get("provider_health_summary") or {}).get("healthy_count"), 0)
        fmp_hard_stop = bool(governor.get("fmp_hard_stop_active") or governor.get("fmp_emergency_stop_active"))
        fmp_warning = bool(governor.get("fmp_warning_active"))
        fmp_allowed = bool(governor.get("fmp_rest_governor_allowed", True))
        fmp_refresh_allowed_now = bool(governor.get("fmp_refresh_allowed_now", fmp_allowed))
        fmp_refresh_block_reason = _safe_text(governor.get("fmp_refresh_block_reason"), "none" if fmp_refresh_allowed_now else "unknown")
        blocked_calls = _to_int(fmp_usage.get("fmp_blocked_calls_today"), _to_int(governor.get("fmp_blocked_calls_today"), 0))
        cache_hit_rate = _to_float(fmp_usage.get("fmp_cache_hit_rate"), _to_float(governor.get("fmp_cache_hit_rate"), 0.0))
        runtime = self._runtime_health()

        provider_pressure = bool(
            fmp_hard_stop
            or current_utilization_pct >= hard_ceiling_pct
            or not fmp_allowed
            or (provider_seen > 0 and degraded_count >= max(3, provider_seen // 2 + 1))
            or blocked_calls > 1000
        )
        runtime_protection = bool(provider_pressure or runtime["timeout_storm_detected"] or runtime["lock_wait_timeout_detected"])

        rows = _candidate_rows(top_buys_payload)
        diversity = self._candidate_diversity(rows)
        learning_pressure = self._learning_pressure(observation_payload, execution_payload, multi_horizon_payload, diversity)
        intake_mode = self._intake_mode(current_utilization_pct, low_target_pct, high_target_pct, hard_ceiling_pct, provider_pressure, fmp_warning)
        intensity = self._refresh_intensity(intake_mode, runtime_protection, learning_pressure)
        multipliers = self._multipliers(intake_mode, runtime_protection, learning_pressure, diversity)

        recommended_slices = self._recommended_slices(intake_mode, runtime_protection, diversity, learning_pressure)
        reasons, brakes = self._reasons_brakes(intake_mode, provider_pressure, runtime, learning_pressure, diversity, cache_hit_rate)
        daily_budget_label = round(recommended_daily_budget_gb, 3)
        summary = (
            f"FMP usage is {current_utilization_pct:.3f}% of a {limit_gb:.1f} GB monthly allowance "
            f"(target {low_target_pct:.0f}-{high_target_pct:.0f}%). Mode={intake_mode}; "
            f"recommend {intensity.replace('_', ' ')} with rotating slices, no hot-path blocking."
        )

        return {
            "enabled": True,
            "version": VERSION,
            "mode": "adaptive_cached_recommendation",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "uncontrolled_api_loops_enabled": False,
            "adaptive_market_intake_fmp_budget_status_v1": True,
            "generated_at": _now_iso(),
            "bandwidth_source": "local_estimate",
            "fmp_smart_budget_enabled": bool(smart_budget_enabled),
            "fmp_rest_conserve_mode": bool(emergency_conserve_active or not fmp_allowed),
            "fmp_refresh_allowed_now": bool(fmp_refresh_allowed_now),
            "fmp_refresh_block_reason": str(fmp_refresh_block_reason),
            "monthly_bandwidth_limit_gb": round(limit_gb, 3),
            "current_monthly_bandwidth_used_gb": round(used_gb, 6),
            "current_utilization_pct": round(current_utilization_pct, 4),
            "target_utilization_low_pct": round(low_target_pct, 3),
            "target_utilization_high_pct": round(high_target_pct, 3),
            "hard_safety_ceiling_pct": round(hard_ceiling_pct, 3),
            "target_monthly_bandwidth_low_gb": round(low_target_gb, 3),
            "target_monthly_bandwidth_high_gb": round(high_target_gb, 3),
            "hard_safety_ceiling_gb": round(hard_ceiling_gb, 3),
            "remaining_bandwidth_gb": round(remaining_gb, 6),
            "days_remaining_in_cycle": int(days_remaining),
            "recommended_daily_bandwidth_budget_gb": daily_budget_label,
            "adaptive_intake_mode": intake_mode,
            "intake_mode": intake_mode,
            "recommended_refresh_intensity": intensity,
            "recommended_quote_refresh_multiplier": multipliers["quote"],
            "recommended_exploration_multiplier": multipliers["exploration"],
            "recommended_small_mid_cap_scan_multiplier": multipliers["small_mid_cap"],
            "recommended_intraday_rescan_multiplier": multipliers["intraday"],
            "recommended_context_refresh_multiplier": multipliers["context"],
            "runtime_protection_active": runtime_protection,
            "provider_pressure_detected": provider_pressure,
            "provider_health_summary": {
                "healthy_count": healthy_count,
                "degraded_count": degraded_count,
                "providers_seen": provider_seen,
                "fmp_rest_governor_allowed": fmp_allowed,
                "fmp_smart_budget_enabled": bool(smart_budget_enabled),
                "fmp_refresh_allowed_now": bool(fmp_refresh_allowed_now),
                "fmp_refresh_block_reason": str(fmp_refresh_block_reason),
                "fmp_hard_stop_active": fmp_hard_stop,
                "fmp_warning_active": fmp_warning,
                "fmp_blocked_calls_today": blocked_calls,
            },
            "runtime_health_summary": runtime,
            "cache_hit_rate_pct": round(cache_hit_rate, 3),
            "cache_entries_estimate": _to_int(cache_index.get("entries_estimate"), 0),
            "candidate_diversity_score": round(diversity["candidate_diversity_score"], 3),
            "candidate_symbols_evaluated": int(diversity["candidate_symbols_evaluated"]),
            "candidate_sector_count": int(diversity["sector_count"]),
            "candidate_market_cap_bucket_count": int(diversity["market_cap_bucket_count"]),
            "learning_pressure_score": round(learning_pressure, 3),
            "recommended_rotating_slices": recommended_slices,
            "intake_reasons": reasons,
            "intake_brakes": brakes,
            "intake_summary": summary,
            "next_recommended_action": "use_governed_rotating_market_intake_only_outside_rankings_top_buys_hot_paths",
        }

    def _runtime_health(self) -> dict[str, Any]:
        health_tail = _tail_text(self.runtime_health_path, max_bytes=200_000).lower()
        backend_tail = _tail_text(self.backend_log_path, max_bytes=500_000).lower()
        bad_terms = ("traceback", "exception", "lock_wait_timeout")
        error_count = sum(backend_tail.count(term) for term in bad_terms)
        timeout_count = backend_tail.count("timeout")
        backend_down = "backend=down" in health_tail or "frontend=down" in health_tail
        return {
            "backend_frontend_recently_up": not backend_down,
            "recent_error_term_count": int(error_count),
            "recent_timeout_count": int(timeout_count),
            "timeout_storm_detected": bool(timeout_count >= 25),
            "lock_wait_timeout_detected": "lock_wait_timeout" in backend_tail,
            "runtime_health_source": "local_runtime_logs",
        }

    def _candidate_diversity(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        symbols = {_safe_text(r.get("symbol")).upper() for r in rows if _safe_text(r.get("symbol"))}
        sectors = {
            _safe_text(r.get("sector") or r.get("sector_context_label") or r.get("sector_name")).lower()
            for r in rows
            if _safe_text(r.get("sector") or r.get("sector_context_label") or r.get("sector_name"))
        }
        caps = {
            _safe_text(r.get("market_cap_bucket") or r.get("market_cap_context_label") or r.get("cap_bucket")).lower()
            for r in rows
            if _safe_text(r.get("market_cap_bucket") or r.get("market_cap_context_label") or r.get("cap_bucket"))
        }
        diversity_score = _clamp(min(len(symbols), 30) * 1.8 + min(len(sectors), 8) * 5.0 + min(len(caps), 5) * 4.0)
        if len(symbols) <= 6:
            diversity_score = min(diversity_score, 52.0)
        return {
            "candidate_symbols_evaluated": len(symbols),
            "sector_count": len(sectors),
            "market_cap_bucket_count": len(caps),
            "candidate_diversity_score": diversity_score,
        }

    def _learning_pressure(self, obs: dict[str, Any], execution: dict[str, Any], multi: dict[str, Any], diversity: dict[str, Any]) -> float:
        closed = _to_float(obs.get("trades_closed_today"), 0.0)
        labels = _to_float(obs.get("labels_created_today"), 0.0)
        observation_score = _to_float(obs.get("observation_completion_score"), 0.0)
        entry_util = _to_float(execution.get("entry_utilization_score"), 0.0)
        context = _to_float(execution.get("market_knowledge_score"), 0.0)
        horizon_score = _to_float(multi.get("multi_horizon_learning_score"), 0.0)
        diversity_score = _to_float(diversity.get("candidate_diversity_score"), 0.0)
        pressure = 0.0
        if closed < 3:
            pressure += 22.0
        if labels < 10:
            pressure += 18.0
        pressure += max(0.0, 70.0 - observation_score) * 0.18
        pressure += max(0.0, 60.0 - entry_util) * 0.12
        pressure += max(0.0, 60.0 - context) * 0.14
        pressure += max(0.0, 70.0 - horizon_score) * 0.10
        pressure += max(0.0, 65.0 - diversity_score) * 0.16
        return _clamp(pressure)

    def _intake_mode(self, utilization: float, low: float, high: float, ceiling: float, pressure: bool, warning: bool) -> str:
        if pressure:
            return "provider_pressure_pause"
        if utilization >= ceiling or warning:
            return "over_limit_risk"
        if utilization >= high:
            return "approaching_limit"
        if utilization >= low:
            return "on_target"
        return "under_utilizing"

    def _refresh_intensity(self, mode: str, runtime_protection: bool, learning_pressure: float) -> str:
        if runtime_protection or mode == "provider_pressure_pause":
            return "paused_runtime_protection"
        if mode in {"over_limit_risk", "approaching_limit"}:
            return "reduced_cache_first"
        if mode == "on_target":
            return "maintain_cache_first"
        if learning_pressure >= 55:
            return "controlled_expansion_high_learning_need"
        return "controlled_expansion"

    def _multipliers(self, mode: str, runtime_protection: bool, learning_pressure: float, diversity: dict[str, Any]) -> dict[str, float]:
        if runtime_protection or mode == "provider_pressure_pause":
            base = {"quote": 0.5, "exploration": 0.4, "small_mid_cap": 0.4, "intraday": 0.4, "context": 0.6}
        elif mode in {"over_limit_risk", "approaching_limit"}:
            base = {"quote": 0.75, "exploration": 0.65, "small_mid_cap": 0.65, "intraday": 0.7, "context": 0.75}
        elif mode == "on_target":
            base = {"quote": 1.0, "exploration": 1.0, "small_mid_cap": 1.0, "intraday": 1.0, "context": 1.0}
        else:
            boost = 0.25 if learning_pressure >= 55 else 0.0
            diversity_gap = 0.20 if _to_float(diversity.get("candidate_diversity_score"), 0.0) < 55 else 0.0
            base = {
                "quote": 1.15 + boost * 0.4,
                "exploration": 1.55 + boost + diversity_gap,
                "small_mid_cap": 1.60 + boost + diversity_gap,
                "intraday": 1.35 + boost * 0.8,
                "context": 1.45 + boost * 0.8,
            }
        return {k: round(_clamp(v, 0.0, 2.5), 3) for k, v in base.items()}

    def _recommended_slices(self, mode: str, runtime_protection: bool, diversity: dict[str, Any], learning_pressure: float) -> list[str]:
        if runtime_protection or mode == "provider_pressure_pause":
            return ["pause_expansion", "serve_cached_snapshots", "monitor_provider_health"]
        slices = ["high_priority_active_candidates", "stale_cache_symbols", "under_sampled_symbols"]
        if mode == "under_utilizing":
            slices.extend(["recent_movers", "sector_leaders", "small_mid_momentum_list", "multi_horizon_candidates"])
        if learning_pressure >= 55:
            slices.append("context_confidence_gaps")
        if _to_float(diversity.get("candidate_diversity_score"), 0.0) < 55:
            slices.append("candidate_diversity_refresh")
        return list(dict.fromkeys(slices))[:10]

    def _reasons_brakes(self, mode: str, pressure: bool, runtime: dict[str, Any], learning_pressure: float, diversity: dict[str, Any], cache_hit_rate: float) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        brakes: list[str] = []
        if mode == "under_utilizing":
            reasons.append("fmp_bandwidth_under_target")
        if learning_pressure >= 55:
            reasons.append("learning_evidence_needs_more_market_observations")
        if _to_float(diversity.get("candidate_diversity_score"), 0.0) < 55:
            reasons.append("candidate_diversity_can_improve")
        if cache_hit_rate < 35:
            reasons.append("cache_hit_rate_low_enough_to_prioritize_stale_cache_refresh")
        if pressure:
            brakes.append("provider_pressure_detected")
        if bool(runtime.get("timeout_storm_detected")):
            brakes.append("runtime_timeout_storm_detected")
        if bool(runtime.get("lock_wait_timeout_detected")):
            brakes.append("lock_wait_timeout_detected")
        return list(dict.fromkeys(reasons))[:8], list(dict.fromkeys(brakes))[:8]

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "adaptive_cached_recommendation",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "uncontrolled_api_loops_enabled": False,
            "adaptive_market_intake_fmp_budget_status_v1": True,
            "bandwidth_source": "local_estimate",
            "monthly_bandwidth_limit_gb": round(FMP_MONTHLY_BANDWIDTH_GB, 3),
            "current_monthly_bandwidth_used_gb": 0.0,
            "current_utilization_pct": 0.0,
            "target_utilization_low_pct": round(FMP_TARGET_UTILIZATION_LOW * 100.0, 3),
            "target_utilization_high_pct": round(FMP_TARGET_UTILIZATION_HIGH * 100.0, 3),
            "remaining_bandwidth_gb": round(FMP_MONTHLY_BANDWIDTH_GB, 3),
            "recommended_daily_bandwidth_budget_gb": 0.0,
            "adaptive_intake_mode": "provider_pressure_pause",
            "intake_mode": "provider_pressure_pause",
            "recommended_refresh_intensity": "paused_runtime_protection",
            "recommended_quote_refresh_multiplier": 0.0,
            "recommended_exploration_multiplier": 0.0,
            "recommended_small_mid_cap_scan_multiplier": 0.0,
            "recommended_intraday_rescan_multiplier": 0.0,
            "recommended_context_refresh_multiplier": 0.0,
            "runtime_protection_active": True,
            "provider_pressure_detected": True,
            "intake_summary": reason,
        }
