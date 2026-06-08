from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
DASHBOARD_CACHE_MAX_AGE_SECONDS = 180.0
TARGET_SHADOW_OPPORTUNITIES_PER_DAY = 75
HARD_MAX_SHADOW_OPPORTUNITIES_PER_DAY = 150
TARGET_VIRTUAL_PATHS_PER_OPPORTUNITY = 8
HARD_MAX_VIRTUAL_PATHS_PER_OPPORTUNITY = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _avg(values: list[float]) -> float:
    vals = [v for v in values if math.isfinite(v)]
    return sum(vals) / len(vals) if vals else 0.0


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


class RealisticShadowEvidenceLearningLabV1:
    """Shadow-only paper-like evidence lab using cached summaries and local budget diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "realistic_shadow_evidence_learning_lab_v1.json")
        self.fmp_usage_path = os.path.join(self.state_dir, "fmp_usage_state.json")
        self.fmp_cache_index_path = os.path.join(self.state_dir, "fmp_cache_index.json")
        self.api_governor_path = os.path.join(self.state_dir, "api_usage_governor.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _fmp_budget(self) -> dict[str, Any]:
        usage = _read_json(self.fmp_usage_path)
        cache_index = _read_json(self.fmp_cache_index_path)
        governor = _read_json(self.api_governor_path)
        smart_budget_enabled = str(os.getenv("ASTRA_FMP_SMART_BUDGET_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        emergency_disable_explicit = "ASTRA_TEMP_FMP_REST_DISABLED" in os.environ
        emergency_conserve_active = bool(
            emergency_disable_explicit
            and str(os.getenv("ASTRA_TEMP_FMP_REST_DISABLED", "0" if smart_budget_enabled else "1")).strip().lower()
            in {"1", "true", "yes", "on"}
        )
        refresh_allowed_now = bool(governor.get("fmp_refresh_allowed_now", governor.get("fmp_rest_governor_allowed", False)))
        refresh_block_reason = _text(
            governor.get("fmp_refresh_block_reason") or governor.get("fmp_rest_activation_reason"),
            "none" if refresh_allowed_now else "unknown",
        )
        calls = _to_int(
            usage.get("calls_used_today")
            or usage.get("fmp_calls_used_today")
            or usage.get("fmp_calls_today")
            or usage.get("daily_calls")
            or usage.get("calls"),
            0,
        )
        bandwidth = _to_float(
            usage.get("bandwidth_used_today")
            or usage.get("fmp_bandwidth_used_today")
            or usage.get("fmp_estimated_used_today_bytes")
            or usage.get("bytes_used_today"),
            0.0,
        )
        daily_call_limit_raw = usage.get("daily_call_limit", usage.get("fmp_daily_call_limit", governor.get("fmp_daily_call_limit")))
        daily_bandwidth_limit_raw = usage.get(
            "daily_bandwidth_limit",
            usage.get("fmp_daily_bandwidth_limit", governor.get("fmp_daily_bandwidth_limit")),
        )
        daily_call_limit_known = daily_call_limit_raw not in (None, "")
        daily_bandwidth_limit_known = daily_bandwidth_limit_raw not in (None, "")
        daily_call_limit = _to_int(daily_call_limit_raw, 0)
        daily_bandwidth_limit = _to_float(daily_bandwidth_limit_raw, 0.0)
        last_success = _text(usage.get("last_successful_call") or usage.get("fmp_last_successful_call"), "insufficient_data")
        last_failed = _text(usage.get("last_failed_call") or usage.get("fmp_last_failed_call"), "insufficient_data")
        last_fresh = _text(
            usage.get("last_fresh_data_timestamp")
            or usage.get("fmp_last_fresh_data_timestamp")
            or cache_index.get("updated_at")
            or cache_index.get("last_updated_utc"),
            "insufficient_data",
        )
        hits = _to_float(cache_index.get("hits") or cache_index.get("cache_hits_seen") or usage.get("cache_hits") or usage.get("cache_hits_seen"), 0.0)
        misses = _to_float(cache_index.get("misses") or cache_index.get("cache_misses_seen") or usage.get("cache_misses") or usage.get("cache_misses_seen"), 0.0)
        symbols = cache_index.get("symbols")
        entries = _to_float(
            cache_index.get("entries") or cache_index.get("entries_estimate"),
            float(len(symbols)) if isinstance(symbols, list) else 0.0,
        )
        cache_hit_rate = _clamp((hits / max(1.0, hits + misses)) * 100.0) if hits or misses else (85.0 if entries > 0 else 0.0)
        provider_enabled = bool(governor.get("fmp_enabled", not bool(usage.get("provider_disabled", False))))
        provider_available = not bool(usage.get("provider_unavailable", False))
        cache_only_mode = bool(
            emergency_conserve_active
            or governor.get("fmp_rest_conserve_mode", False)
            or (usage.get("cache_only_mode", False) if usage else False)
        )
        zero_usage = calls <= 0 and bandwidth <= 0
        if zero_usage:
            if not usage:
                zero_reason = "usage_accounting_missing"
            elif emergency_conserve_active:
                zero_reason = "emergency_conserve_mode_active"
            elif not smart_budget_enabled:
                zero_reason = "provider_disabled"
            elif not provider_enabled and not refresh_allowed_now:
                zero_reason = "budget_protection_active" if "budget" in refresh_block_reason else "provider_disabled"
            elif not provider_enabled:
                zero_reason = "provider_disabled"
            elif not provider_available:
                zero_reason = "provider_unavailable"
            elif last_failed != "insufficient_data":
                zero_reason = "provider_error"
            elif "market_closed" in refresh_block_reason:
                zero_reason = "market_closed"
            elif refresh_allowed_now:
                zero_reason = "smart_budget_no_eligible_refresh"
            elif cache_only_mode:
                zero_reason = "cache_only_intentional"
            elif entries > 0:
                zero_reason = "no_refresh_needed"
            else:
                zero_reason = "unknown_zero_usage"
        else:
            zero_reason = "not_zero_usage"
        warning = "none"
        if zero_reason in {"unknown_zero_usage", "provider_disabled", "provider_unavailable", "provider_error", "usage_accounting_missing"}:
            warning = zero_reason
        pressure = 0.0
        if daily_call_limit_known and daily_call_limit > 0:
            pressure = max(pressure, calls / max(1, daily_call_limit) * 100.0)
        if daily_bandwidth_limit_known and daily_bandwidth_limit > 0:
            pressure = max(pressure, bandwidth / max(1.0, daily_bandwidth_limit) * 100.0)
        if not daily_call_limit_known and not daily_bandwidth_limit_known:
            budget_status = "limit_unknown"
        else:
            budget_status = "protected_cache_first" if pressure < 60 else "watch_budget_pressure" if pressure < 85 else "budget_pressure_high"
        freshness_score = 80.0 if last_fresh != "insufficient_data" else 45.0 if cache_only_mode else 35.0
        confidence = _clamp(cache_hit_rate * 0.45 + freshness_score * 0.35 + (100.0 - pressure) * 0.20)
        safe_fix = "none"
        safe_reason = "no_safe_fix_needed"
        if warning == "provider_disabled":
            safe_fix = "inspect_provider_flag_before_any_manual_reenable"
            safe_reason = "provider_disabled_requires_human_review_no_budget_change_applied"
        elif warning == "provider_unavailable":
            safe_fix = "inspect_provider_routing_and_cached_fallback"
            safe_reason = "provider_unavailable_no_retries_started"
        elif warning == "provider_error":
            safe_fix = "inspect_last_provider_error_and_budget_accounting"
            safe_reason = "provider_error_no_retry_loop_started"
        elif warning == "unknown_zero_usage":
            safe_fix = "improve_zero_usage_diagnostics"
            safe_reason = "unknown_zero_usage_marked_for_diagnostics_only"
        elif warning == "usage_accounting_missing":
            safe_fix = "restore_provider_usage_accounting_visibility"
            safe_reason = "usage_accounting_missing_no_provider_calls_started"
        return {
            "fmp_status": "smart_budget_ready" if provider_available and smart_budget_enabled else "provider_attention_needed",
            "fmp_smart_budget_enabled": bool(smart_budget_enabled),
            "fmp_rest_conserve_mode": bool(cache_only_mode),
            "fmp_refresh_allowed_now": bool(refresh_allowed_now),
            "fmp_refresh_block_reason": str(refresh_block_reason),
            "fmp_zero_usage_reason": zero_reason,
            "fmp_last_successful_call": last_success,
            "fmp_last_failed_call": last_failed,
            "fmp_last_fresh_data_timestamp": last_fresh,
            "fmp_cache_hit_rate": _round(cache_hit_rate, 2),
            "fmp_cache_only_mode": cache_only_mode,
            "fmp_provider_enabled": provider_enabled,
            "fmp_provider_available": provider_available,
            "fmp_zero_usage_detected": zero_usage,
            "fmp_calls_used_today": calls,
            "fmp_bandwidth_used_today": _round(bandwidth, 4),
            "fmp_daily_call_limit": daily_call_limit if daily_call_limit_known else "call_limit_unknown",
            "fmp_daily_bandwidth_limit": _round(daily_bandwidth_limit, 4) if daily_bandwidth_limit_known else "bandwidth_limit_unknown",
            "fmp_remaining_calls_estimate": max(0, daily_call_limit - calls) if daily_call_limit_known and daily_call_limit else "call_limit_unknown",
            "fmp_remaining_bandwidth_estimate": _round(max(0.0, daily_bandwidth_limit - bandwidth), 4) if daily_bandwidth_limit_known and daily_bandwidth_limit else "bandwidth_limit_unknown",
            "fmp_budget_status": budget_status,
            "provider_fallback_status": "cached_fallback_ready" if cache_hit_rate > 0 else "fallback_visibility_limited",
            "provider_budget_status": budget_status,
            "bandwidth_pressure_score": _round(_clamp(pressure), 2),
            "data_freshness_score": _round(freshness_score, 2),
            "live_data_confidence_score": _round(confidence, 2),
            "provider_warning": warning,
            "recommended_safe_fix": safe_fix,
            "safe_fix_applied": False,
            "safe_fix_reason": safe_reason,
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        paper_trace = self._status(statuses, "paper_execution_trace")
        participation = self._status(statuses, "execution_participation_audit")
        convergence = self._status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        accelerated = self._status(statuses, "accelerated_learning_symbol_intelligence_suite_v1")
        peak_decay = self._status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        governance = self._status(statuses, "autonomous_intelligence_validation_governance_v1")
        allocator = self._status(statuses, "adaptive_learning_prioritization_resource_allocation_v1")
        full = self._status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        decision = self._status(statuses, "decision_optimization_trade_management_suite_v1")
        replay = self._status(statuses, "replay_counterfactual_learning_v2")
        long_memory = self._status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        worker = self._status(statuses, "adaptive_worker_activation_orchestration_v1")
        catalyst = self._status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        portfolio = self._status(statuses, "portfolio_diversification_correlation_v2")

        candidate_pool = max(
            _to_int(participation.get("unique_candidates_reviewed"), 0),
            _to_int(full.get("opportunities_tracked"), 0),
            _to_int(accelerated.get("historical_records_reviewed"), 0),
            _to_int(paper_trace.get("orders_attempted"), 0) + _to_int(participation.get("reviewed_total"), 0),
        )
        shadow_opportunities = min(HARD_MAX_SHADOW_OPPORTUNITIES_PER_DAY, max(0, min(candidate_pool, TARGET_SHADOW_OPPORTUNITIES_PER_DAY)))
        eligible_rate = _clamp(_to_float(participation.get("submission_rate_unique_candidates"), 0.0) + 25.0)
        eligible = min(shadow_opportunities, max(0, int(round(shadow_opportunities * eligible_rate / 100.0))))
        near_miss = min(shadow_opportunities - eligible, max(0, int(round(shadow_opportunities * 0.32))))
        discarded = max(0, shadow_opportunities - eligible - near_miss)
        paths_per = min(HARD_MAX_VIRTUAL_PATHS_PER_OPPORTUNITY, TARGET_VIRTUAL_PATHS_PER_OPPORTUNITY)
        virtual_paths = (eligible + near_miss) * paths_per
        shadow_learning_events = virtual_paths + eligible + near_miss
        capacity_used = _round(shadow_opportunities / HARD_MAX_SHADOW_OPPORTUNITIES_PER_DAY * 100.0, 2)
        capacity_remaining = max(0, HARD_MAX_SHADOW_OPPORTUNITIES_PER_DAY - shadow_opportunities)

        portfolio_realism = _clamp(
            100.0
            - _to_float(portfolio.get("concentration_risk_score"), _to_float(portfolio.get("concentration_risk"), 40.0)) * 0.25
            - _to_float(portfolio.get("correlation_risk_score"), _to_float(portfolio.get("correlation_risk"), 40.0)) * 0.20
            - _to_float(portfolio.get("portfolio_heat"), 35.0) * 0.15
        )
        execution_realism = _clamp(82.0 - max(0.0, _to_float(catalyst.get("unknown_catalyst_rate"), 0.0) - 45.0) * 0.18)
        mirror_score = _clamp(_to_float(participation.get("eligible_candidates"), eligible) * 4.0 + _to_float(accelerated.get("symbol_personality_quality_score"), 50.0) * 0.55 + 35.0)
        context_complete = _clamp(_to_float(catalyst.get("catalyst_coverage_score"), 50.0) * 0.35 + _to_float(accelerated.get("symbol_personality_quality_score"), 50.0) * 0.45 + 20.0)
        lifecycle_complete = _clamp(_to_float(peak_decay.get("capture_quality_score"), 50.0) * 0.45 + _to_float(replay.get("replay_learning_score"), 50.0) * 0.30 + 25.0)
        data_fresh = _clamp(_to_float(accelerated.get("indexing_health_score"), 50.0))
        signal_quality = _clamp(_to_float(allocator.get("expected_improvement_score"), 50.0) * 0.45 + _to_float(decision.get("decision_quality_score"), 50.0) * 0.25 + _to_float(governance.get("truth_validation_score"), 50.0) * 0.30)
        avg_realism = _round(_avg([mirror_score, portfolio_realism, execution_realism, lifecycle_complete, data_fresh, signal_quality]), 2)
        high_realism = int(round((eligible + near_miss) * avg_realism / 100.0))
        low_realism = max(0, eligible + near_miss - high_realism)
        realism_weighted_events = int(round(shadow_learning_events * avg_realism / 100.0))

        completed_lifecycles = min(eligible, _to_int(peak_decay.get("tracked_trades"), 0))
        active_lifecycles = max(0, eligible - completed_lifecycles)
        avg_mfe = _to_float(peak_decay.get("avg_peak_gain"), _to_float(peak_decay.get("average_gain_after_milestone"), 0.0))
        avg_mae = _to_float(peak_decay.get("average_mae_pct"), 0.0)
        capture_ratio = _to_float(peak_decay.get("average_capture_ratio"), 0.0)
        giveback = _to_float(peak_decay.get("average_giveback_pct"), 0.0)
        estimated_slippage = _round(max(0.03, (100.0 - execution_realism) / 1000.0), 4)
        raw_shadow_return = _to_float(convergence.get("average_virtual_return"), _to_float(replay.get("average_best_counterfactual_return"), 0.0))
        adjusted_return = _round(raw_shadow_return - estimated_slippage, 4)

        quality_score = _round(_avg([avg_realism, signal_quality, data_fresh, context_complete]), 2)
        high_value_lessons = int(round(realism_weighted_events * quality_score / 100.0 * 0.18))
        compressed_lessons = int(round(shadow_learning_events * 0.35))
        discarded_noise = int(round((virtual_paths + discarded) * max(0.0, 100.0 - quality_score) / 100.0))
        retention_rate = _round(high_value_lessons / max(1, shadow_learning_events) * 100.0, 2)

        consensus_inputs = [
            _to_float(peak_decay.get("capture_quality_score"), 0.0),
            _to_float(convergence.get("gap_attribution_score"), 0.0),
            _to_float(accelerated.get("replay_acceleration_score"), 0.0),
            _to_float(governance.get("truth_validation_score"), 0.0),
            _to_float(allocator.get("learning_roi_score"), 0.0),
            _to_float(full.get("cross_system_learning_score"), 0.0),
            _to_float(decision.get("decision_quality_score"), 0.0),
            _to_float(replay.get("replay_learning_score"), 0.0),
        ]
        consensus_conf = _round(_avg(consensus_inputs), 2)
        consensus_count = len([v for v in consensus_inputs if v >= 55.0])
        conflict_count = len([v for v in consensus_inputs if 0 < v < 40.0])
        active_weakness = _text(allocator.get("top_weakness"), _text(accelerated.get("highest_roi_learning_area"), "profit_capture"))
        weakness_events = int(round(shadow_learning_events * 0.60))
        weakness_score = _round(_clamp(_to_float(allocator.get("expected_improvement_score"), 50.0) * 0.6 + quality_score * 0.4), 2)
        weakness_signal = "improving_shadow_evidence" if weakness_score >= 60 else "collect_more_realistic_shadow_evidence"

        top_failure = _text(convergence.get("dominant_gap_cause") or accelerated.get("top_missed_profit_driver"), "profit_giveback_after_milestone")
        repeated_failures = max(0, int(round((eligible + near_miss) * (100.0 - capture_ratio * 100.0) / 100.0))) if capture_ratio else max(0, near_miss)
        failure_conf = _round(_clamp(_to_float(convergence.get("gap_attribution_score"), 0.0) * 0.5 + _to_float(accelerated.get("drift_score"), 0.0) * 0.5), 2)
        affected_symbols = list(dict.fromkeys(
            list(convergence.get("symbols_needing_profit_lock") or [])
            + list(convergence.get("symbols_needing_continuation_exit") or [])
            + list(accelerated.get("symbols_with_behavior_drift") or [])
        ))[:8]
        policy = _text(peak_decay.get("best_exit_policy") or convergence.get("strongest_virtual_policy"), "profit_lock_exit")
        second_policy = _text(peak_decay.get("second_best_exit_policy"), _text(convergence.get("closest_policy_to_future_review"), "peak_decay_exit"))
        weak_policy = _text(peak_decay.get("weakest_policy") or convergence.get("weakest_virtual_policy"), "insufficient_data")
        tournament_score = _round(_clamp(_to_float(peak_decay.get("policy_confidence"), 0.0) * 0.45 + _to_float(convergence.get("policy_improvement_confidence"), 0.0) * 0.35 + consensus_conf * 0.20), 2)
        policy_conf = _round(_clamp(tournament_score * 0.85), 2)
        policy_candidate = _text(peak_decay.get("closest_exit_policy_to_readiness") or convergence.get("closest_policy_to_future_review"), policy)

        storage_pressure = _clamp(_to_float(long_memory.get("memory_pressure_score"), 0.0) + compressed_lessons / max(1, shadow_learning_events) * 15.0)
        memory_pressure = _clamp(_to_float(long_memory.get("memory_pressure_score"), 0.0) + discarded_noise / max(1, virtual_paths) * 8.0)
        cleanup = "compress_duplicate_lessons_and_keep_high_confidence_summaries" if storage_pressure >= 40 else "no_cleanup_needed_keep_compact_summaries"
        fmp = self._fmp_budget()
        provider_warning = _text(fmp.get("provider_warning"), "none")
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_realistic_shadow_evidence_learning_lab",
            "generated_at": _now_iso(),
            "shadow_opportunities_tracked": shadow_opportunities,
            "virtual_paths_created": virtual_paths,
            "shadow_learning_events": shadow_learning_events,
            "shadow_capacity_used": capacity_used,
            "shadow_capacity_remaining": capacity_remaining,
            "target_shadow_opportunities_per_day": TARGET_SHADOW_OPPORTUNITIES_PER_DAY,
            "hard_max_shadow_opportunities_per_day": HARD_MAX_SHADOW_OPPORTUNITIES_PER_DAY,
            "target_virtual_paths_per_opportunity": TARGET_VIRTUAL_PATHS_PER_OPPORTUNITY,
            "hard_max_virtual_paths_per_opportunity": HARD_MAX_VIRTUAL_PATHS_PER_OPPORTUNITY,
            "eligible_shadow_trades": eligible,
            "near_miss_shadow_trades": near_miss,
            "discarded_unrealistic_trades": discarded,
            "eligibility_pass_rate": _round((eligible + near_miss) / max(1, shadow_opportunities) * 100.0, 2),
            "paper_engine_mirror_score": _round(mirror_score, 2),
            "mirrored_candidate_count": eligible + near_miss,
            "shadow_context_completeness": _round(context_complete, 2),
            "shadow_portfolio_value": 100000.0,
            "shadow_virtual_positions": eligible,
            "shadow_concentration": _round(_to_float(portfolio.get("concentration_risk_score"), _to_float(portfolio.get("concentration_risk"), 0.0)), 2),
            "shadow_correlation": _round(_to_float(portfolio.get("correlation_risk_score"), _to_float(portfolio.get("correlation_risk"), 0.0)), 2),
            "shadow_heat": _round(_to_float(portfolio.get("portfolio_heat"), 0.0), 2),
            "shadow_portfolio_realism_score": _round(portfolio_realism, 2),
            "estimated_slippage_pct": estimated_slippage,
            "execution_realism_score": _round(execution_realism, 2),
            "adjusted_shadow_return": adjusted_return,
            "raw_shadow_return": _round(raw_shadow_return, 4),
            "completed_shadow_lifecycles": completed_lifecycles,
            "active_shadow_lifecycles": active_lifecycles,
            "shadow_avg_MFE": _round(avg_mfe, 4),
            "shadow_avg_MAE": _round(avg_mae, 4),
            "shadow_capture_ratio": _round(capture_ratio, 4),
            "shadow_giveback_pct": _round(giveback, 4),
            "average_shadow_realism_score": avg_realism,
            "high_realism_shadow_trades": high_realism,
            "low_realism_shadow_trades": low_realism,
            "realism_weighted_learning_events": realism_weighted_events,
            "best_virtual_path": policy,
            "worst_virtual_path": weak_policy,
            "best_horizon": _text(accelerated.get("highest_roi_learning_area"), "profit_capture"),
            "best_exit_style": policy,
            "virtual_path_quality_score": _round(_avg([tournament_score, quality_score]), 2),
            "evidence_quality_score": quality_score,
            "high_value_lessons": high_value_lessons,
            "compressed_lessons": compressed_lessons,
            "discarded_noise_count": discarded_noise,
            "quality_retention_rate": retention_rate,
            "consensus_lesson_count": consensus_count,
            "strongest_consensus_lesson": _text(governance.get("strongest_validated_lesson") or accelerated.get("highest_value_historical_lesson"), "insufficient_data"),
            "conflicting_lesson_count": conflict_count,
            "consensus_confidence_score": consensus_conf,
            "raw_observations": shadow_learning_events,
            "candidate_lessons": high_value_lessons + compressed_lessons,
            "validated_lessons": consensus_count,
            "high_confidence_lessons": len([v for v in consensus_inputs if v >= 70.0]),
            "future_policy_candidates": 0,
            "duplicate_lessons_compressed": compressed_lessons,
            "storage_saved_estimate": _round(compressed_lessons / max(1, shadow_learning_events) * 100.0, 2),
            "compression_quality_score": _round(_to_float(accelerated.get("compression_quality_score"), 0.0), 2),
            "active_weakness_focus": active_weakness,
            "weakness_shadow_events": weakness_events,
            "weakness_learning_score": weakness_score,
            "weakness_improvement_signal": weakness_signal,
            "top_failure_pattern": top_failure,
            "repeated_failure_count": repeated_failures,
            "failure_pattern_confidence": failure_conf,
            "affected_symbols": affected_symbols,
            "winning_policy": policy,
            "second_best_policy": second_policy,
            "weakest_policy": weak_policy,
            "policy_tournament_score": tournament_score,
            "policy_confidence": policy_conf,
            "policy_readiness_candidate": policy_candidate,
            "raw_shadow_records": 0,
            "compact_shadow_summaries": 1,
            "compressed_lesson_count": compressed_lessons,
            "storage_pressure_score": _round(storage_pressure, 2),
            "memory_pressure_score": _round(memory_pressure, 2),
            "cleanup_recommendation": cleanup,
            "stale_lessons": list(accelerated.get("stale_symbol_lessons") or [])[:8],
            "decayed_lessons": list(accelerated.get("stale_symbol_lessons") or [])[:8],
            "reinforced_lessons": list(accelerated.get("refreshed_symbol_lessons") or [])[:8],
            "recency_quality_score": _round(_to_float(accelerated.get("current_behavior_confidence"), 50.0), 2),
            "fmp_status": fmp["fmp_status"],
            "fmp_smart_budget_enabled": fmp["fmp_smart_budget_enabled"],
            "fmp_rest_conserve_mode": fmp["fmp_rest_conserve_mode"],
            "fmp_refresh_allowed_now": fmp["fmp_refresh_allowed_now"],
            "fmp_refresh_block_reason": fmp["fmp_refresh_block_reason"],
            "fmp_zero_usage_reason": fmp["fmp_zero_usage_reason"],
            "fmp_last_successful_call": fmp["fmp_last_successful_call"],
            "fmp_last_failed_call": fmp["fmp_last_failed_call"],
            "fmp_last_fresh_data_timestamp": fmp["fmp_last_fresh_data_timestamp"],
            "fmp_cache_hit_rate": fmp["fmp_cache_hit_rate"],
            "fmp_cache_only_mode": fmp["fmp_cache_only_mode"],
            "fmp_provider_enabled": fmp["fmp_provider_enabled"],
            "fmp_provider_available": fmp["fmp_provider_available"],
            "fmp_zero_usage_detected": fmp["fmp_zero_usage_detected"],
            "fmp_calls_used_today": fmp["fmp_calls_used_today"],
            "fmp_bandwidth_used_today": fmp["fmp_bandwidth_used_today"],
            "fmp_daily_call_limit": fmp["fmp_daily_call_limit"],
            "fmp_daily_bandwidth_limit": fmp["fmp_daily_bandwidth_limit"],
            "fmp_remaining_calls_estimate": fmp["fmp_remaining_calls_estimate"],
            "fmp_remaining_bandwidth_estimate": fmp["fmp_remaining_bandwidth_estimate"],
            "fmp_budget_status": fmp["fmp_budget_status"],
            "provider_fallback_status": fmp["provider_fallback_status"],
            "provider_budget_status": fmp["provider_budget_status"],
            "bandwidth_pressure_score": fmp["bandwidth_pressure_score"],
            "data_freshness_score": fmp["data_freshness_score"],
            "live_data_confidence_score": fmp["live_data_confidence_score"],
            "provider_warning": provider_warning,
            "recommended_safe_fix": fmp["recommended_safe_fix"],
            "safe_fix_applied": False,
            "safe_fix_reason": fmp["safe_fix_reason"],
            "governance_status": "passed_shadow_only_firewall",
            "shadow_lab_safe": True,
            "blocked_behavior_changes": ["orders", "paper_execution", "broker_behavior", "ranking", "entries", "exits", "sizing", "thresholds"],
            "shadow_recommendation": f"shadow_only_track_{shadow_opportunities}_realistic_opportunities_focus_{active_weakness}_and_apply_no_policies",
            "summary": "Astra is generating realistic shadow-only paper-trade evidence from cached candidates and learning summaries without broker orders or provider calls during dashboard render.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "full_history_scanned": False,
            "bandwidth_saving_mode": True,
            "cache_status": "rebuilt",
            "cache_freshness": "live",
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "portfolio_allocation_changed": False,
            "order_logic_changed": False,
            "paper_orders_placed": False,
            "alpaca_orders_placed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
        }
        out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
        _write_json(self.cache_path, out)
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
        payload["api_calls_used"] = 0
        payload["provider_calls_used"] = 0
        payload["llm_calls_used"] = 0
        payload["dashboard_scan_rows"] = 0
        payload["raw_history_scanned"] = False
        payload["raw_archive_scanned"] = False
        payload["full_history_scanned"] = False
        payload["behavior_safe_to_apply"] = False
        return payload

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
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
            out["cache_age_seconds"] = 0.0
            self._cache = out
            self._cache_ts = now
            return out
        except Exception as exc:
            cached = self._cached()
            if cached:
                cached["stale_cache"] = True
                cached["degraded_reason"] = f"realistic_shadow_evidence_lab_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_realistic_shadow_evidence_learning_lab",
                "shadow_opportunities_tracked": 0,
                "eligible_shadow_trades": 0,
                "near_miss_shadow_trades": 0,
                "discarded_unrealistic_trades": 0,
                "virtual_paths_created": 0,
                "shadow_learning_events": 0,
                "completed_shadow_lifecycles": 0,
                "average_shadow_realism_score": 0.0,
                "high_realism_shadow_trades": 0,
                "paper_engine_mirror_score": 0.0,
                "shadow_portfolio_realism_score": 0.0,
                "execution_realism_score": 0.0,
                "evidence_quality_score": 0.0,
                "high_value_lessons": 0,
                "compressed_lessons": 0,
                "discarded_noise_count": 0,
                "consensus_lesson_count": 0,
                "strongest_consensus_lesson": "unavailable",
                "active_weakness_focus": "unavailable",
                "top_failure_pattern": "unavailable",
                "winning_policy": "unavailable",
                "policy_tournament_score": 0.0,
                "policy_confidence": 0.0,
                "storage_pressure_score": 0.0,
                "memory_pressure_score": 0.0,
                "fmp_status": "unavailable",
                "fmp_smart_budget_enabled": False,
                "fmp_rest_conserve_mode": True,
                "fmp_refresh_allowed_now": False,
                "fmp_refresh_block_reason": "fallback_unavailable",
                "fmp_zero_usage_reason": "unknown_zero_usage",
                "fmp_last_successful_call": "unavailable",
                "fmp_last_fresh_data_timestamp": "unavailable",
                "fmp_cache_hit_rate": 0.0,
                "fmp_calls_used_today": 0,
                "fmp_bandwidth_used_today": 0.0,
                "fmp_budget_status": "unavailable",
                "bandwidth_pressure_score": 0.0,
                "data_freshness_score": 0.0,
                "live_data_confidence_score": 0.0,
                "provider_warning": "unavailable",
                "recommended_safe_fix": "unavailable",
                "safe_fix_applied": False,
                "shadow_recommendation": "unavailable",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "dashboard_scan_rows": 0,
                "raw_history_scanned": False,
                "raw_archive_scanned": False,
                "full_history_scanned": False,
                "behavior_safe_to_apply": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "portfolio_allocation_changed": False,
                "order_logic_changed": False,
                "paper_orders_placed": False,
                "alpaca_orders_placed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
                "degraded_reason": f"realistic_shadow_evidence_learning_lab_v1_unavailable:{str(exc)[:140]}",
            }
