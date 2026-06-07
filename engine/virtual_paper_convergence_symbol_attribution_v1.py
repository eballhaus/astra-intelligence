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


def _text(value: Any, default: str = "") -> str:
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


def _top_key(payload: dict[str, Any], key: str, default: str = "insufficient_data") -> str:
    value = payload.get(key)
    if isinstance(value, dict):
        ranked = sorted(value.items(), key=lambda item: _to_float(item[1], 0.0), reverse=True)
        return _text(ranked[0][0], default) if ranked else default
    return _text(value, default)


class VirtualPaperConvergenceSymbolAttributionV1:
    """Shadow-only convergence, gap attribution, and symbol behavior diagnostics from cached summaries."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "virtual_paper_convergence_symbol_attribution_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    def _gap_cause(
        self,
        convergence_gap: float,
        capture_ratio: float,
        giveback: float,
        continuation_failure: float,
        confidence_power: float,
        horizon_quality: float,
        catalyst_decay: float,
        memory_quality: float,
    ) -> tuple[str, str, float, str]:
        candidates = {
            "profit_giveback": max(0.0, giveback * 2.2 + (55.0 - capture_ratio * 100.0) * 0.55),
            "exit_timing": max(0.0, convergence_gap * 2.5 + (60.0 - capture_ratio * 100.0) * 0.45),
            "hold_duration": max(0.0, 60.0 - horizon_quality),
            "continuation_failure": continuation_failure,
            "confidence_error": max(0.0, 65.0 - confidence_power),
            "catalyst_decay": max(0.0, 60.0 - catalyst_decay),
            "symbol_behavior_mismatch": max(0.0, 65.0 - memory_quality),
        }
        ordered = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        primary = ordered[0][0] if ordered else "insufficient_evidence"
        secondary = ordered[1][0] if len(ordered) > 1 else "insufficient_evidence"
        confidence = _clamp((ordered[0][1] if ordered else 0.0) * 0.8 + min(25.0, abs(convergence_gap)))
        repeated = primary if confidence >= 45 else "insufficient_evidence"
        return primary, secondary, _round(confidence, 2), repeated

    def _policy_attribution(self, peak_decay: dict[str, Any], decision: dict[str, Any], confidence: dict[str, Any]) -> tuple[str, str, float, float, str]:
        policy_stats = dict(peak_decay.get("policy_stats") or decision.get("virtual_exit_policy_stats") or {})
        if policy_stats:
            strongest = max(policy_stats.items(), key=lambda item: _to_float(item[1].get("average_improvement_delta"), -999.0))[0]
            weakest = min(policy_stats.items(), key=lambda item: _to_float(item[1].get("average_improvement_delta"), 999.0))[0]
            best_delta = _to_float(policy_stats.get(strongest, {}).get("average_improvement_delta"), 0.0)
            sample_size = _to_float(policy_stats.get(strongest, {}).get("sample_size"), 0.0)
            confidence_score = _clamp(min(70.0, sample_size) + min(30.0, abs(best_delta) * 5.0))
        else:
            strongest = _text(peak_decay.get("highest_improvement_policy") or decision.get("highest_improvement_policy"), "insufficient_data")
            weakest = _text(peak_decay.get("weakest_policy") or decision.get("worst_virtual_exit_policy"), "insufficient_data")
            confidence_score = _to_float(peak_decay.get("policy_confidence"), _to_float(confidence.get("confidence_predictive_power"), 0.0))
        readiness = _text(peak_decay.get("closest_exit_policy_to_readiness") or decision.get("top_exit_learning_focus"), strongest)
        score = _clamp(confidence_score * 0.65 + _to_float(peak_decay.get("readiness_score"), 0.0) * 0.35)
        return strongest, weakest, _round(confidence_score, 2), _round(score, 2), readiness

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        replay = self._status(statuses, "replay_counterfactual_learning_v2")
        peak_decay = self._status(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        decision = self._status(statuses, "decision_optimization_trade_management_suite_v1")
        memory = self._status(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        full = self._status(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        confidence = self._status(statuses, "confidence_calibration_performance_attribution_v1")
        catalyst = self._status(statuses, "catalyst_theme_narrative_capital_flow_intelligence_v2")
        context = self._status(statuses, "context_evidence_expansion_suite_v1")
        archetype = self._status(statuses, "trade_archetype_regime")

        tracked_trades = max(
            _to_int(replay.get("tracked_lifecycles"), 0),
            _to_int(peak_decay.get("tracked_trades"), 0),
            _to_int(decision.get("tracked_trades"), 0),
            _to_int(full.get("paper_trades_tracked"), 0),
        )
        symbol_profiles = _to_int(memory.get("symbol_profiles_tracked"), 0)
        average_actual = _to_float(replay.get("average_actual_return"), _to_float(decision.get("average_actual_result"), 0.0))
        average_virtual = _to_float(
            replay.get("average_best_counterfactual_return"),
            average_actual + _to_float(replay.get("average_counterfactual_improvement"), 0.0),
        )
        average_gap = _round(average_virtual - average_actual, 4)
        missed_profit_pct = max(0.0, average_gap)
        virtual_outperformance_rate = _clamp(_to_float(decision.get("virtual_outperformance_rate"), 0.0) or (65.0 if average_gap > 0 else 0.0))
        convergence_quality = _clamp(100.0 - abs(average_gap) * 4.0)
        capture_ratio = _to_float(peak_decay.get("average_capture_ratio"), 0.0)
        giveback = _to_float(peak_decay.get("average_giveback_pct"), 0.0)
        continuation_failure = _to_float(peak_decay.get("continuation_failure_probability"), _to_float(decision.get("continuation_failure_probability"), 0.0))
        horizon_quality = _to_float(peak_decay.get("hold_duration_quality_score"), _to_float(decision.get("horizon_exit_quality_score"), 50.0))
        catalyst_decay = _to_float(catalyst.get("catalyst_decay_learning_score"), 50.0)
        memory_quality = _to_float(memory.get("symbol_memory_quality_score"), 50.0)
        confidence_power = _to_float(confidence.get("confidence_predictive_power"), _to_float(decision.get("predictive_power"), 50.0))
        primary_gap, secondary_gap, gap_confidence, repeated_gap = self._gap_cause(
            average_gap,
            capture_ratio,
            giveback,
            continuation_failure,
            confidence_power,
            horizon_quality,
            catalyst_decay,
            memory_quality,
        )
        highest_gap_symbol = _text(
            peak_decay.get("highest_giveback_trade")
            or memory.get("highest_giveback_symbol")
            or confidence.get("top_loss_driver")
            or "insufficient_data",
            "insufficient_data",
        )
        smallest_gap_symbol = _text(memory.get("most_reliable_symbol") or peak_decay.get("best_capture_trade") or "insufficient_data", "insufficient_data")
        best_horizon_by_symbol = {smallest_gap_symbol: _text(peak_decay.get("strongest_horizon"), "insufficient_data")} if smallest_gap_symbol != "insufficient_data" else {}
        worst_horizon_by_symbol = {highest_gap_symbol: _text(peak_decay.get("weakest_horizon"), "insufficient_data")} if highest_gap_symbol != "insufficient_data" else {}
        best_exit_style_by_symbol = {
            highest_gap_symbol: _text(peak_decay.get("highest_improvement_policy"), "profit_lock_exit")
        } if highest_gap_symbol != "insufficient_data" else {}
        symbols_needing_profit_lock = [highest_gap_symbol] if primary_gap in {"profit_giveback", "exit_timing"} and highest_gap_symbol != "insufficient_data" else []
        symbols_needing_continuation_exit = [highest_gap_symbol] if primary_gap == "continuation_failure" and highest_gap_symbol != "insufficient_data" else []
        symbols_needing_longer_hold = [smallest_gap_symbol] if primary_gap == "hold_duration" and smallest_gap_symbol != "insufficient_data" else []
        strongest_policy, weakest_policy, policy_conf, policy_score, closest_policy = self._policy_attribution(peak_decay, decision, confidence)
        top_missed_profit_driver = primary_gap
        highest_value_lever = {
            "profit_giveback": "profit_lock_exit_review",
            "exit_timing": "peak_decay_exit_review",
            "hold_duration": "horizon_specific_hold_review",
            "continuation_failure": "continuation_failure_exit_review",
            "catalyst_decay": "catalyst_aware_hold_review",
            "symbol_behavior_mismatch": "symbol_specific_exit_review",
            "confidence_error": "confidence_truth_review",
        }.get(primary_gap, "collect_more_convergence_evidence")
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_virtual_paper_convergence_symbol_attribution",
            "generated_at": _now_iso(),
            "tracked_trades": tracked_trades,
            "symbol_profiles_reviewed": symbol_profiles,
            "average_actual_return": _round(average_actual, 4),
            "average_virtual_return": _round(average_virtual, 4),
            "average_convergence_gap": average_gap,
            "missed_profit_pct": _round(missed_profit_pct, 4),
            "missed_profit_dollars": 0.0,
            "gap_severity": "high" if average_gap >= 8 else "medium" if average_gap >= 3 else "low",
            "convergence_quality_score": _round(convergence_quality, 2),
            "virtual_outperformance_rate": _round(virtual_outperformance_rate, 2),
            "largest_convergence_gap_symbol": highest_gap_symbol,
            "smallest_convergence_gap_symbol": smallest_gap_symbol,
            "dominant_gap_cause": primary_gap,
            "primary_gap_cause": primary_gap,
            "secondary_gap_cause": secondary_gap,
            "gap_cause_confidence": gap_confidence,
            "repeated_gap_pattern": repeated_gap,
            "gap_attribution_score": gap_confidence,
            "strongest_gap_pattern": primary_gap,
            "weakest_gap_pattern": secondary_gap,
            "gap_attribution_confidence": gap_confidence,
            "highest_value_gap_to_reduce": highest_value_lever,
            "strongest_symbol_behavior_edge": _text(memory.get("best_behavioral_edge_symbol") or memory.get("strongest_symbol_profile"), "insufficient_data"),
            "weakest_symbol_behavior_edge": _text(memory.get("weakest_symbol_profile"), "insufficient_data"),
            "highest_gap_symbol": highest_gap_symbol,
            "most_reliable_symbol": _text(memory.get("most_reliable_symbol") or confidence.get("top_profit_driver"), "insufficient_data"),
            "least_reliable_symbol": _text(memory.get("weakest_symbol_profile") or confidence.get("top_loss_driver"), "insufficient_data"),
            "symbol_behavior_confidence": _round(memory_quality, 2),
            "best_symbol_horizon_pair": f"{smallest_gap_symbol}+{_text(peak_decay.get('strongest_horizon'), 'unknown')}" if smallest_gap_symbol != "insufficient_data" else "insufficient_data",
            "worst_symbol_horizon_pair": f"{highest_gap_symbol}+{_text(peak_decay.get('weakest_horizon'), 'unknown')}" if highest_gap_symbol != "insufficient_data" else "insufficient_data",
            "best_horizon_by_symbol": best_horizon_by_symbol,
            "worst_horizon_by_symbol": worst_horizon_by_symbol,
            "horizon_gap_score": _round(_clamp(100.0 - horizon_quality), 2),
            "horizon_fit_confidence": _round(horizon_quality, 2),
            "best_exit_style_by_symbol": best_exit_style_by_symbol,
            "worst_exit_style_by_symbol": {highest_gap_symbol: weakest_policy} if highest_gap_symbol != "insufficient_data" else {},
            "exit_style_improvement_by_symbol": {highest_gap_symbol: _round(average_gap, 4)} if highest_gap_symbol != "insufficient_data" else {},
            "symbol_exit_confidence": policy_conf,
            "symbols_needing_profit_lock": symbols_needing_profit_lock,
            "symbols_needing_continuation_exit": symbols_needing_continuation_exit,
            "symbols_needing_longer_hold": symbols_needing_longer_hold,
            "best_regime_by_symbol": {smallest_gap_symbol: _text(archetype.get("best_regime"), "insufficient_data")} if smallest_gap_symbol != "insufficient_data" else {},
            "worst_regime_by_symbol": {highest_gap_symbol: _text(archetype.get("weakest_regime"), "insufficient_data")} if highest_gap_symbol != "insufficient_data" else {},
            "best_catalyst_by_symbol": {smallest_gap_symbol: _text(catalyst.get("strongest_catalyst_type"), "insufficient_data")} if smallest_gap_symbol != "insufficient_data" else {},
            "worst_catalyst_by_symbol": {highest_gap_symbol: _text(catalyst.get("weakest_catalyst_type"), "insufficient_data")} if highest_gap_symbol != "insufficient_data" else {},
            "best_theme_by_symbol": {smallest_gap_symbol: _text(catalyst.get("strongest_theme"), "insufficient_data")} if smallest_gap_symbol != "insufficient_data" else {},
            "catalyst_symbol_fit_score": _round(_to_float(catalyst.get("catalyst_truth_score"), 0.0), 2),
            "regime_symbol_fit_score": _round(_to_float(archetype.get("current_archetype_regime_alignment_score"), 0.0), 2),
            "top_profit_driver": _text(confidence.get("top_profit_driver") or memory.get("most_reliable_symbol"), "insufficient_data"),
            "top_loss_driver": _text(confidence.get("top_loss_driver") or highest_gap_symbol, "insufficient_data"),
            "top_missed_profit_driver": top_missed_profit_driver,
            "profitability_attribution_score": _round(_clamp(gap_confidence * 0.5 + convergence_quality * 0.25 + memory_quality * 0.25), 2),
            "highest_value_profitability_lever": highest_value_lever,
            "strongest_virtual_policy": strongest_policy,
            "weakest_virtual_policy": weakest_policy,
            "policy_improvement_confidence": policy_conf,
            "policy_attribution_score": policy_score,
            "closest_policy_to_future_review": closest_policy,
            "context_gap_inputs": {
                "dominant_catalyst": _text(catalyst.get("dominant_catalyst") or catalyst.get("dominant_catalyst_type"), "insufficient_data"),
                "dominant_theme": _text(catalyst.get("dominant_theme"), "insufficient_data"),
                "market_context_gap": _text(context.get("top_learning_gap"), "insufficient_data"),
            },
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "shadow_recommendation": f"shadow_only_reduce_{primary_gap}_gap_with_{highest_value_lever}_evidence_before_any_policy_review",
            "summary": "Astra is comparing actual paper outcomes with virtual/replay alternatives and attributing the gap without changing trading behavior.",
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "bandwidth_saving_mode": True,
            "cache_status": "rebuilt",
            "cache_freshness": "live",
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
                cached["degraded_reason"] = f"virtual_paper_convergence_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_virtual_paper_convergence_symbol_attribution",
                "tracked_trades": 0,
                "symbol_profiles_reviewed": 0,
                "average_actual_return": 0.0,
                "average_virtual_return": 0.0,
                "average_convergence_gap": 0.0,
                "convergence_quality_score": 0.0,
                "virtual_outperformance_rate": 0.0,
                "dominant_gap_cause": "unavailable",
                "highest_value_gap_to_reduce": "unavailable",
                "largest_convergence_gap_symbol": "unavailable",
                "strongest_symbol_behavior_edge": "unavailable",
                "weakest_symbol_behavior_edge": "unavailable",
                "highest_gap_symbol": "unavailable",
                "most_reliable_symbol": "unavailable",
                "best_symbol_horizon_pair": "unavailable",
                "worst_symbol_horizon_pair": "unavailable",
                "best_exit_style_by_symbol": {},
                "symbols_needing_profit_lock": [],
                "symbols_needing_continuation_exit": [],
                "best_regime_by_symbol": {},
                "best_catalyst_by_symbol": {},
                "top_missed_profit_driver": "unavailable",
                "highest_value_profitability_lever": "unavailable",
                "strongest_virtual_policy": "unavailable",
                "closest_policy_to_future_review": "unavailable",
                "policy_improvement_confidence": 0.0,
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"virtual_paper_convergence_symbol_attribution_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "behavior_safe_to_apply": False,
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
            }
