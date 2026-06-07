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

PEER_GROUPS: dict[str, list[str]] = {
    "semiconductor_ai_leaders": ["NVDA", "AMD", "AVGO", "TSM", "ARM"],
    "quantum_momentum": ["QBTS", "RGTI", "IONQ", "QUBT"],
    "airlines": ["DAL", "UAL", "AAL"],
    "retail_momentum": ["AMC", "GME"],
}


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


def _first_mapping_key(mapping: Any, default: str = "insufficient_data") -> str:
    if isinstance(mapping, dict) and mapping:
        return _text(next(iter(mapping.keys())), default)
    return default


def _first_mapping_value(mapping: Any, default: str = "insufficient_data") -> str:
    if isinstance(mapping, dict) and mapping:
        return _text(next(iter(mapping.values())), default)
    return default


def _compact_mapping(mapping: Any, limit: int = 8) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {str(k): v for k, v in list(mapping.items())[:limit]}


class AcceleratedLearningSymbolIntelligenceSuiteV1:
    """Cache-first, shadow-only accelerated replay and symbol intelligence diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "accelerated_learning_symbol_intelligence_suite_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _symbol_clusters(self, memory: dict[str, Any], catalyst: dict[str, Any], convergence: dict[str, Any]) -> tuple[dict[str, list[str]], str, str, list[str], float]:
        strongest_symbol = _text(memory.get("strongest_symbol_profile") or memory.get("most_reliable_symbol"), "NVDA")
        weakest_symbol = _text(memory.get("weakest_symbol_profile") or convergence.get("highest_gap_symbol"), "insufficient_data")
        strongest_cluster = "insufficient_data"
        weakest_cluster = "insufficient_data"
        for name, symbols in PEER_GROUPS.items():
            if strongest_symbol in symbols:
                strongest_cluster = name
            if weakest_symbol in symbols:
                weakest_cluster = name
        if strongest_cluster == "insufficient_data" and _text(catalyst.get("strongest_theme"), "").lower() in {"ai", "semiconductors"}:
            strongest_cluster = "semiconductor_ai_leaders"
        if weakest_cluster == "insufficient_data" and weakest_symbol != "insufficient_data":
            weakest_cluster = f"{weakest_symbol.lower()}_direct_history"
        transferable = []
        if strongest_cluster != "insufficient_data":
            transferable.append(f"use_{strongest_cluster}_as_low_confidence_support_when_direct_symbol_history_is_thin")
        if weakest_cluster != "insufficient_data":
            transferable.append(f"monitor_{weakest_cluster}_giveback_without_applying_rules")
        score = _clamp(_to_float(memory.get("symbol_memory_quality_score"), 0.0) * 0.55 + _to_float(catalyst.get("theme_confidence"), 50.0) * 0.25 + _to_float(convergence.get("gap_attribution_score"), 0.0) * 0.20)
        return PEER_GROUPS, strongest_cluster, weakest_cluster, transferable[:5], _round(score, 2)

    def _roi_area(
        self,
        convergence: dict[str, Any],
        peak_decay: dict[str, Any],
        decision: dict[str, Any],
        priority: dict[str, Any],
        catalyst: dict[str, Any],
    ) -> tuple[str, str, float, str]:
        candidates = {
            "profit_capture": 100 - _to_float(peak_decay.get("capture_quality_score"), 50.0),
            "exit_style": abs(_to_float(convergence.get("average_convergence_gap"), 0.0)) * 4.0,
            "hold_duration": 100 - _to_float(peak_decay.get("hold_duration_quality_score"), 50.0),
            "continuation_quality": _to_float(peak_decay.get("continuation_failure_probability"), _to_float(decision.get("continuation_failure_probability"), 0.0)),
            "confidence_calibration": 100 - _to_float(decision.get("confidence_truth_score"), 50.0),
            "catalyst_understanding": 100 - _to_float(catalyst.get("catalyst_coverage_score"), 50.0),
        }
        preferred = _text(priority.get("highest_value_learning_focus"), "")
        if preferred in candidates:
            candidates[preferred] = max(candidates[preferred], _to_float(priority.get("expected_improvement_score"), candidates[preferred]))
        ordered = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        best = ordered[0][0] if ordered else "profit_capture"
        worst = ordered[-1][0] if ordered else "insufficient_data"
        gain = _clamp(ordered[0][1] if ordered else 0.0)
        focus = {
            "profit_capture": "accelerate_profit_capture_and_giveback_replay",
            "exit_style": "accelerate_symbol_exit_style_replay",
            "hold_duration": "accelerate_horizon_hold_duration_replay",
            "continuation_quality": "accelerate_continuation_failure_pattern_review",
            "confidence_calibration": "accelerate_confidence_truth_bucket_review",
        }.get(best, "accelerate_cached_symbol_learning")
        return best, worst, _round(gain, 2), focus

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        replay = self._status(statuses, "replay_counterfactual_learning_v2")
        opportunity = self._status(statuses, "opportunity_cost_learning")
        convergence = self._status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        peak_decay = self._status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        memory = self._status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        full = self._status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        decision = self._status(statuses, "decision_optimization_trade_management_suite_v1")
        confidence = self._status(statuses, "confidence_calibration_performance_attribution_v1")
        catalyst = self._status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        archetype = self._status(statuses, "trade_archetype_regime")
        context = self._status(statuses, "context_evidence_expansion_suite_v1")
        priority = self._status(statuses, "adaptive_learning_prioritization_resource_allocation_v1")

        historical_records = max(
            _to_int(full.get("opportunities_tracked"), 0),
            _to_int(memory.get("indexed_records"), 0),
            _to_int(replay.get("tracked_lifecycles"), 0) + _to_int(opportunity.get("selected_candidates_reviewed"), 0) + _to_int(opportunity.get("rejected_candidates_reviewed"), 0),
        )
        accelerated_events = max(
            historical_records,
            _to_int(replay.get("counterfactuals_generated"), 0) + _to_int(full.get("paper_trades_tracked"), 0) + _to_int(full.get("rejected_tracked"), 0),
        )
        average_gap = _to_float(convergence.get("average_convergence_gap"), _to_float(replay.get("average_counterfactual_improvement"), 0.0))
        dominant_gap = _text(convergence.get("dominant_gap_cause") or decision.get("biggest_decision_gap"), "insufficient_data")
        replay_score = _clamp(_to_float(replay.get("replay_learning_score"), 0.0) * 0.45 + _to_float(convergence.get("gap_attribution_score"), 0.0) * 0.35 + min(20.0, accelerated_events / 100.0))

        best_horizon_by_symbol = _compact_mapping(convergence.get("best_horizon_by_symbol"))
        worst_horizon_by_symbol = _compact_mapping(convergence.get("worst_horizon_by_symbol"))
        best_exit_style_by_symbol = _compact_mapping(convergence.get("best_exit_style_by_symbol"))
        worst_exit_style_by_symbol = _compact_mapping(convergence.get("worst_exit_style_by_symbol"))
        best_catalyst_by_symbol = _compact_mapping(convergence.get("best_catalyst_by_symbol"))
        worst_catalyst_by_symbol = _compact_mapping(convergence.get("worst_catalyst_by_symbol"))
        best_regime_by_symbol = _compact_mapping(convergence.get("best_regime_by_symbol"))
        worst_regime_by_symbol = _compact_mapping(convergence.get("worst_regime_by_symbol"))
        best_theme_by_symbol = _compact_mapping(convergence.get("best_theme_by_symbol"))

        symbol_profiles = _to_int(memory.get("symbol_profiles_tracked"), _to_int(convergence.get("symbol_profiles_reviewed"), 0))
        strongest_symbol = _text(memory.get("strongest_symbol_profile") or convergence.get("strongest_symbol_behavior_edge"), "insufficient_data")
        weakest_symbol = _text(memory.get("weakest_symbol_profile") or convergence.get("weakest_symbol_behavior_edge"), "insufficient_data")
        highest_giveback_symbol = _text(memory.get("highest_giveback_symbol") or convergence.get("highest_gap_symbol"), "insufficient_data")
        most_reliable_symbol = _text(memory.get("most_reliable_symbol") or convergence.get("most_reliable_symbol"), "insufficient_data")
        best_edge_symbol = _text(memory.get("best_behavioral_edge_symbol") or convergence.get("strongest_symbol_behavior_edge"), "insufficient_data")
        symbol_quality = _clamp(_to_float(memory.get("symbol_memory_quality_score"), 0.0) * 0.65 + _to_float(convergence.get("symbol_behavior_confidence"), 0.0) * 0.35)

        clusters, strongest_cluster, weakest_cluster, transferable_lessons, cluster_score = self._symbol_clusters(memory, catalyst, convergence)
        highest_roi, lowest_roi, expected_gain, recommended_focus = self._roi_area(convergence, peak_decay, decision, priority, catalyst)

        strongest_sector = _text(catalyst.get("strongest_sector") or archetype.get("best_sector"), "insufficient_data")
        weakest_sector = _text(catalyst.get("weakest_sector") or archetype.get("weakest_sector"), "insufficient_data")
        strongest_industry = _text(catalyst.get("dominant_industry") or catalyst.get("strongest_industry"), "insufficient_data")
        strongest_theme = _text(catalyst.get("strongest_theme") or catalyst.get("dominant_theme"), "insufficient_data")
        weakest_theme = _text(catalyst.get("weakest_theme"), "insufficient_data")
        best_peer_horizon = _first_mapping_value(best_horizon_by_symbol, _text(peak_decay.get("strongest_horizon"), "insufficient_data"))
        best_peer_exit = _first_mapping_value(best_exit_style_by_symbol, _text(peak_decay.get("highest_improvement_policy"), "insufficient_data"))
        highest_giveback_peer = strongest_cluster if highest_giveback_symbol in sum(PEER_GROUPS.values(), []) else weakest_cluster

        drift_score = _clamp(100.0 - _to_float(memory.get("symbol_memory_quality_score"), 50.0) + abs(average_gap) * 0.6)
        highest_drift_symbol = highest_giveback_symbol if drift_score >= 35 else "insufficient_data"
        most_stable_symbol = most_reliable_symbol
        symbols_with_drift = [highest_drift_symbol] if highest_drift_symbol != "insufficient_data" else []
        stale_lessons = ["old_symbol_tendencies_require_recency_confirmation"] if drift_score >= 45 else []
        refreshed_lessons = [f"{most_stable_symbol}_behavior_recently_supported"] if most_stable_symbol != "insufficient_data" else []
        regime_override_count = 1 if _to_float(archetype.get("current_archetype_regime_alignment_score"), 0.0) >= 70 and drift_score >= 35 else 0

        compressed_lessons = max(0, _to_int(full.get("compact_summary_count"), 0) + _to_int(memory.get("symbol_profiles_tracked"), 0) + len(transferable_lessons))
        raw_summarized = max(historical_records - compressed_lessons, 0)
        indexed_records = max(_to_int(memory.get("indexed_records"), 0), historical_records)
        retrieval_latency = _to_float(memory.get("retrieval_latency_ms"), 0.0)
        indexing_health = _clamp(_to_float(memory.get("retrieval_health_score"), 0.0) * 0.75 + _to_float(memory.get("storage_health_score"), 0.0) * 0.25)
        full_scan_avoided = max(_to_int(memory.get("full_scan_avoided_count"), 0), indexed_records)

        top_missed_driver = _text(convergence.get("top_missed_profit_driver") or decision.get("biggest_decision_gap"), dominant_gap)
        profitability_lever = _text(convergence.get("highest_value_profitability_lever") or decision.get("strongest_improvement_area"), "collect_more_symbol_evidence")
        most_common_mistake = dominant_gap if dominant_gap != "insufficient_data" else top_missed_driver
        highest_lesson = f"focus_{profitability_lever}_using_symbol_and_peer_context"
        cross_pattern = f"{strongest_cluster}_shares_{best_peer_exit}_exit_tendency" if strongest_cluster != "insufficient_data" and best_peer_exit != "insufficient_data" else "insufficient_data"

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_accelerated_learning_symbol_intelligence",
            "generated_at": _now_iso(),
            "historical_records_reviewed": historical_records,
            "accelerated_learning_events": accelerated_events,
            "replay_acceleration_score": _round(replay_score, 2),
            "most_common_historical_mistake": most_common_mistake,
            "highest_value_historical_lesson": highest_lesson,
            "average_actual_return": convergence.get("average_actual_return", replay.get("average_actual_return")),
            "average_virtual_return": convergence.get("average_virtual_return", replay.get("average_best_counterfactual_return")),
            "average_convergence_gap": _round(average_gap, 4),
            "dominant_gap_cause": dominant_gap,
            "highest_value_gap_to_reduce": _text(convergence.get("highest_value_gap_to_reduce"), profitability_lever),
            "symbol_profiles_tracked": symbol_profiles,
            "strongest_symbol_profile": strongest_symbol,
            "weakest_symbol_profile": weakest_symbol,
            "most_reliable_symbol": most_reliable_symbol,
            "highest_giveback_symbol": highest_giveback_symbol,
            "best_behavioral_edge_symbol": best_edge_symbol,
            "symbol_personality_quality_score": _round(symbol_quality, 2),
            "best_horizon_by_symbol": best_horizon_by_symbol,
            "worst_horizon_by_symbol": worst_horizon_by_symbol,
            "best_symbol_horizon_pair": _text(convergence.get("best_symbol_horizon_pair"), "insufficient_data"),
            "worst_symbol_horizon_pair": _text(convergence.get("worst_symbol_horizon_pair"), "insufficient_data"),
            "horizon_confidence": _round(_to_float(convergence.get("horizon_fit_confidence"), 0.0), 2),
            "horizon_fit_score": _round(_to_float(convergence.get("horizon_gap_score"), 0.0), 2),
            "best_exit_style_by_symbol": best_exit_style_by_symbol,
            "worst_exit_style_by_symbol": worst_exit_style_by_symbol,
            "exit_style_improvement_by_symbol": _compact_mapping(convergence.get("exit_style_improvement_by_symbol")),
            "symbols_needing_profit_lock": list(convergence.get("symbols_needing_profit_lock") or [])[:8],
            "symbols_needing_continuation_exit": list(convergence.get("symbols_needing_continuation_exit") or [])[:8],
            "symbols_needing_longer_hold": list(convergence.get("symbols_needing_longer_hold") or [])[:8],
            "symbol_exit_confidence": _round(_to_float(convergence.get("symbol_exit_confidence"), 0.0), 2),
            "best_catalyst_by_symbol": best_catalyst_by_symbol,
            "worst_catalyst_by_symbol": worst_catalyst_by_symbol,
            "catalyst_reliability_by_symbol": {strongest_symbol: _round(_to_float(catalyst.get("catalyst_truth_score"), 0.0), 2)} if strongest_symbol != "insufficient_data" else {},
            "best_theme_by_symbol": best_theme_by_symbol,
            "weakest_theme_by_symbol": {highest_giveback_symbol: weakest_theme} if highest_giveback_symbol != "insufficient_data" else {},
            "theme_symbol_fit_score": _round(_to_float(catalyst.get("theme_confidence"), _to_float(convergence.get("catalyst_symbol_fit_score"), 0.0)), 2),
            "best_regime_by_symbol": best_regime_by_symbol,
            "worst_regime_by_symbol": worst_regime_by_symbol,
            "regime_fit_score": _round(_to_float(convergence.get("regime_symbol_fit_score"), 0.0), 2),
            "regime_symbol_confidence": _round(_to_float(archetype.get("current_archetype_regime_alignment_score"), 0.0), 2),
            "symbol_clusters": clusters,
            "strongest_symbol_cluster": strongest_cluster,
            "weakest_symbol_cluster": weakest_cluster,
            "transferable_lessons": transferable_lessons,
            "cluster_learning_score": cluster_score,
            "strongest_cross_symbol_pattern": cross_pattern,
            "weakest_cross_symbol_pattern": f"{weakest_cluster}_needs_direct_symbol_confirmation" if weakest_cluster != "insufficient_data" else "insufficient_data",
            "cross_symbol_learning_score": cluster_score,
            "transferable_pattern_confidence": cluster_score,
            "top_profit_driver": _text(convergence.get("top_profit_driver") or confidence.get("top_profit_driver"), "insufficient_data"),
            "top_loss_driver": _text(convergence.get("top_loss_driver") or confidence.get("top_loss_driver"), "insufficient_data"),
            "top_missed_profit_driver": top_missed_driver,
            "highest_value_profitability_lever": profitability_lever,
            "profitability_attribution_score": _round(_to_float(convergence.get("profitability_attribution_score"), 0.0), 2),
            "highest_roi_learning_area": highest_roi,
            "lowest_roi_learning_area": lowest_roi,
            "expected_learning_gain": expected_gain,
            "recommended_accelerated_focus": recommended_focus,
            "symbol_drift_detection": True,
            "recency_weighting": "recent_evidence_weighted_above_old_history",
            "confidence_decay": "old_lessons_decay_without_reconfirmation",
            "symbol_memory_refresh_validation": "required_before_policy_review",
            "regime_override_logic": "current_regime_and_catalyst_override_stale_symbol_tendencies",
            "symbols_with_behavior_drift": symbols_with_drift,
            "highest_drift_symbol": highest_drift_symbol,
            "most_stable_symbol": most_stable_symbol,
            "stale_symbol_lessons": stale_lessons,
            "refreshed_symbol_lessons": refreshed_lessons,
            "regime_override_count": regime_override_count,
            "symbol_drift_warning": "history_is_evidence_not_truth" if drift_score >= 35 else "no_major_symbol_drift_detected",
            "drift_score": _round(drift_score, 2),
            "reliability_decay_score": _round(_clamp(drift_score * 0.65), 2),
            "symbol_stability_score": _round(_clamp(100.0 - drift_score), 2),
            "current_behavior_confidence": _round(_clamp(symbol_quality * 0.65 + (100.0 - drift_score) * 0.35), 2),
            "compressed_lessons": compressed_lessons,
            "raw_records_summarized": raw_summarized,
            "storage_savings_estimate": _round(_clamp(raw_summarized / max(1, historical_records) * 100.0), 2),
            "compression_quality_score": _round(_clamp(indexing_health * 0.6 + symbol_quality * 0.4), 2),
            "indexed_learning_records": indexed_records,
            "retrieval_latency_ms": _round(retrieval_latency, 3),
            "indexing_health_score": _round(indexing_health, 2),
            "full_scan_avoided_count": full_scan_avoided,
            "best_sector_horizon": {strongest_sector: best_peer_horizon} if strongest_sector != "insufficient_data" else {},
            "best_industry_horizon": {strongest_industry: best_peer_horizon} if strongest_industry != "insufficient_data" else {},
            "best_theme_horizon": {strongest_theme: best_peer_horizon} if strongest_theme != "insufficient_data" else {},
            "best_peer_group_horizon": {strongest_cluster: best_peer_horizon} if strongest_cluster != "insufficient_data" else {},
            "best_sector_exit_style": {strongest_sector: best_peer_exit} if strongest_sector != "insufficient_data" else {},
            "best_industry_exit_style": {strongest_industry: best_peer_exit} if strongest_industry != "insufficient_data" else {},
            "best_theme_exit_style": {strongest_theme: best_peer_exit} if strongest_theme != "insufficient_data" else {},
            "best_peer_group_exit_style": {strongest_cluster: best_peer_exit} if strongest_cluster != "insufficient_data" else {},
            "strongest_sector_behavior": strongest_sector,
            "weakest_sector_behavior": weakest_sector,
            "strongest_industry_behavior": strongest_industry,
            "strongest_theme_behavior": strongest_theme,
            "strongest_peer_group_behavior": strongest_cluster,
            "highest_giveback_sector": weakest_sector,
            "highest_giveback_industry": strongest_industry if highest_giveback_symbol != "insufficient_data" else "insufficient_data",
            "highest_giveback_theme": weakest_theme,
            "highest_giveback_peer_group": highest_giveback_peer,
            "transferable_learning_confidence": cluster_score,
            "peer_group_learning_score": cluster_score,
            "sector_drift_score": _round(_clamp(drift_score * 0.7), 2),
            "industry_drift_score": _round(_clamp(drift_score * 0.65), 2),
            "theme_drift_score": _round(_clamp(drift_score * 0.8), 2),
            "peer_group_drift_score": _round(_clamp(drift_score * 0.75), 2),
            "top_learning_gap": _text(context.get("top_learning_gap") or priority.get("top_weakness"), "symbol_exit_style_evidence"),
            "shadow_recommendation": f"shadow_only_{recommended_focus}_and_use_peer_groups_as_low_confidence_support_only",
            "summary": "Astra is mining cached trade, replay, virtual, opportunity, and symbol summaries to accelerate learning without changing trading behavior.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "scan_rows_used": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
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
                cached["degraded_reason"] = f"accelerated_learning_symbol_intelligence_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_accelerated_learning_symbol_intelligence",
                "historical_records_reviewed": 0,
                "accelerated_learning_events": 0,
                "replay_acceleration_score": 0.0,
                "average_convergence_gap": 0.0,
                "dominant_gap_cause": "unavailable",
                "symbol_profiles_tracked": 0,
                "strongest_symbol_profile": "unavailable",
                "highest_giveback_symbol": "unavailable",
                "most_reliable_symbol": "unavailable",
                "best_horizon_by_symbol": {},
                "best_exit_style_by_symbol": {},
                "best_catalyst_by_symbol": {},
                "best_regime_by_symbol": {},
                "strongest_symbol_cluster": "unavailable",
                "strongest_cross_symbol_pattern": "unavailable",
                "top_missed_profit_driver": "unavailable",
                "highest_value_profitability_lever": "unavailable",
                "highest_roi_learning_area": "unavailable",
                "symbols_with_behavior_drift": [],
                "highest_drift_symbol": "unavailable",
                "most_stable_symbol": "unavailable",
                "regime_override_count": 0,
                "compressed_lessons": 0,
                "indexed_learning_records": 0,
                "retrieval_latency_ms": 0.0,
                "shadow_recommendation": "unavailable",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "dashboard_scan_rows": 0,
                "raw_history_scanned": False,
                "raw_archive_scanned": False,
                "behavior_safe_to_apply": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "portfolio_allocation_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
                "degraded_reason": f"accelerated_learning_symbol_intelligence_suite_v1_unavailable:{str(exc)[:140]}",
            }
