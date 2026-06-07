from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
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


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


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


def _policy_from_outcomes(
    horizon: str,
    avg_return: float,
    capture_ratio: float,
    giveback: float,
    continuation_failure_probability: float,
    strongest_failure_signal: str,
    hold_quality: float,
) -> str:
    h = _text(horizon, "unknown").lower()
    if h == "scalp":
        if giveback >= 0.85 or capture_ratio < 0.48:
            return "profit_lock_exit"
        return "fixed_hold_duration_exit"
    if h == "day_trade":
        if continuation_failure_probability >= 55.0 or any(token in strongest_failure_signal for token in ("momentum", "volume", "leadership")):
            return "continuation_failure_exit"
        if giveback >= 0.75:
            return "profit_lock_exit"
        return "horizon_specific_exit"
    if h == "swing":
        if hold_quality >= 60.0 and avg_return > 0 and capture_ratio >= 0.5:
            return "horizon_specific_exit"
        if giveback >= 1.25:
            return "profit_lock_exit"
        return "catalyst_decay_exit"
    if avg_return > 0 and capture_ratio >= 0.55:
        return "horizon_specific_exit"
    return "fixed_hold_duration_exit"


class ProfitCapturePeakDecayExitValidationSuiteV1:
    """Shadow-only profit capture, peak decay, continuation failure, and exit validation diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "profit_capture_peak_decay_exit_validation_suite_v1.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _status(self, statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
        return dict(statuses.get(key) or {})

    @staticmethod
    def _milestone_label(value: str | None) -> str:
        raw = _text(value, "insufficient_data")
        return raw.replace("plus_", "+").replace("_pct", "%").replace("_", " ")

    def _milestones(self, exit_learning: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        milestone_stats = dict(exit_learning.get("milestone_stats") or {})
        if not milestone_stats:
            return "insufficient_data", "insufficient_data", {}
        strongest = max(
            milestone_stats.items(),
            key=lambda item: (
                _to_float(item[1].get("continuation_probability"), -1.0),
                _to_float(item[1].get("average_gain_after_milestone"), -1.0),
            ),
            default=("insufficient_data", {}),
        )[0]
        weakest = max(
            milestone_stats.items(),
            key=lambda item: (
                _to_float(item[1].get("decay_probability"), -1.0),
                _to_float(item[1].get("average_giveback_after_milestone"), -1.0),
            ),
            default=("insufficient_data", {}),
        )[0]
        return strongest, weakest, milestone_stats

    def _policy_stats(self, decision: dict[str, Any]) -> tuple[str, str, str, str, str, dict[str, Any]]:
        policy_stats = dict(decision.get("virtual_exit_policy_stats") or {})
        if not policy_stats:
            return ("insufficient_data", "insufficient_data", "insufficient_data", "insufficient_data", "insufficient_data", {})
        ordered = sorted(
            policy_stats.items(),
            key=lambda item: _to_float(item[1].get("average_simulated_result"), -999.0),
            reverse=True,
        )
        best = ordered[0][0]
        second = ordered[1][0] if len(ordered) > 1 else "insufficient_data"
        improve = max(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("average_improvement_delta"), -999.0), default=("insufficient_data", {}))[0]
        consistent = max(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("reliability_score"), -999.0), default=("insufficient_data", {}))[0]
        weakest = ordered[-1][0]
        return best, second, improve, consistent, weakest, policy_stats

    def _best_hold_by_horizon(self, exit_learning: dict[str, Any], lifecycle: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        horizon_returns = dict(exit_learning.get("time_window_by_horizon") or {})
        avg_hold = _to_float(exit_learning.get("avg_profitable_hold_time"), _to_float(lifecycle.get("average_hold_duration_minutes"), 0.0))
        best: dict[str, Any] = {}
        policies: dict[str, Any] = {}
        for horizon, avg_return in horizon_returns.items():
            h = _text(horizon, "unknown")
            r = _to_float(avg_return, 0.0)
            if h == "scalp":
                minutes = max(5.0, min(25.0, avg_hold * 0.35 if avg_hold > 0 else 12.0))
            elif h == "day_trade":
                minutes = max(20.0, min(360.0, avg_hold if avg_hold > 0 else 120.0))
            elif h == "swing":
                minutes = max(240.0, min(4320.0, avg_hold * 2.0 if avg_hold > 0 else 1440.0))
            else:
                minutes = max(15.0, min(240.0, avg_hold if avg_hold > 0 else 60.0))
            if r < 0:
                style = "protect_profit_earlier"
            elif r >= 0.5:
                style = "hold_longer_supported"
            else:
                style = "balanced_shadow_review"
            policies[h] = {
                "recommended_exit_policy": _policy_from_outcomes(
                    h,
                    r,
                    _to_float(lifecycle.get("average_profit_capture_ratio"), _to_float(exit_learning.get("average_profit_capture_ratio"), 0.0)),
                    _to_float(lifecycle.get("average_profit_giveback_pct"), _to_float(exit_learning.get("avg_giveback"), 0.0)),
                    _to_float(exit_learning.get("continuation_after_profit_score"), 50.0),
                    _text(exit_learning.get("milestone_exit_bias"), "insufficient_data"),
                    _to_float(exit_learning.get("hold_longer_score"), _to_float(lifecycle.get("average_hold_duration_quality"), 0.0)),
                ),
                "recommended_hold_minutes": _round(minutes, 2),
                "recommended_hold_style": style,
                "avg_return_pct": _round(r, 4),
            }
            best[h] = minutes
        return policies, best

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        lifecycle = self._status(statuses, "trade_lifecycle_excursion_v2")
        profit = self._status(statuses, "adaptive_profit_capture")
        exit_learning = self._status(statuses, "exit_learning_expansion_suite_v1")
        decision = self._status(statuses, "decision_optimization_trade_management_suite_v1")
        replay = self._status(statuses, "replay_counterfactual_learning_v2")
        v3 = self._status(statuses, "adaptive_execution_exit_intelligence_v3")
        trade_archetype = self._status(statuses, "trade_archetype_regime")
        governance = self._status(statuses, "autonomous_intelligence_validation_governance_v1")
        convergence = self._status(statuses, "virtual_paper_convergence_symbol_attribution_v1")

        tracked_trades = max(
            _to_int(lifecycle.get("total_tracked_lifecycles"), 0),
            _to_int(lifecycle.get("tracked_active_trades"), 0) + _to_int(lifecycle.get("tracked_closed_trades"), 0),
            _to_int(profit.get("tracked_lifecycles"), 0),
            _to_int(exit_learning.get("tracked_trades"), 0),
            _to_int(decision.get("tracked_trades"), 0),
            _to_int(replay.get("tracked_lifecycles"), 0),
        )
        average_capture_ratio = _to_float(
            lifecycle.get("average_profit_capture_ratio"),
            _to_float(profit.get("average_profit_capture_ratio"), _to_float(v3.get("avg_capture_ratio"), 0.0)),
        )
        average_giveback_pct = _to_float(
            lifecycle.get("average_profit_giveback_pct"),
            _to_float(profit.get("average_profit_giveback_pct"), _to_float(exit_learning.get("avg_giveback"), 0.0)),
        )
        capture_quality_score = _to_float(
            profit.get("profit_capture_quality_score"),
            _clamp(average_capture_ratio * 100.0 - average_giveback_pct * 1.6 + _to_float(exit_learning.get("protect_profit_score"), 0.0) * 0.2),
        )
        highest_giveback_trade = _text(
            profit.get("worst_giveback_symbol") or lifecycle.get("worst_giveback_symbol") or lifecycle.get("highest_giveback_symbol") or "insufficient_data",
            "insufficient_data",
        )
        best_capture_trade = _text(
            profit.get("best_profit_capture_symbol") or lifecycle.get("best_profit_capture_symbol") or lifecycle.get("best_capture_trade") or "insufficient_data",
            "insufficient_data",
        )
        strongest_milestone, weakest_milestone, milestone_stats = self._milestones(exit_learning)
        continuation_failure_probability = _to_float(
            decision.get("continuation_failure_probability"),
            _to_float(v3.get("continuation_probability"), 0.0),
        )
        strongest_failure_signal = _text(
            decision.get("strongest_failure_signal") or v3.get("shadow_exit_bias") or decision.get("weakest_failure_signal"),
            "insufficient_data",
        )
        hold_duration_quality_score = _clamp(
            _to_float(lifecycle.get("average_hold_duration_quality"), 0.0) * 0.45
            + _to_float(exit_learning.get("holding_time_confidence"), 0.0) * 0.35
            + (100.0 - continuation_failure_probability) * 0.20,
        )
        best_policy, second_best_policy, highest_improvement_policy, most_consistent_policy, weakest_policy, policy_stats = self._policy_stats(decision)
        best_hold_duration_by_horizon, hold_minutes_by_horizon = self._best_hold_by_horizon(exit_learning, lifecycle)
        best_policy_by_horizon = {
            horizon: data["recommended_exit_policy"]
            for horizon, data in best_hold_duration_by_horizon.items()
        }
        capture_ratio_by_horizon = {
            horizon: _round(_clamp(average_capture_ratio * 100.0 + _to_float(data.get("avg_return_pct"), 0.0) * 4.0), 2)
            for horizon, data in best_hold_duration_by_horizon.items()
        }
        giveback_by_horizon = {
            horizon: _round(_clamp(average_giveback_pct * 0.9 + (40.0 if data.get("recommended_exit_policy") == "profit_lock_exit" else 15.0)), 2)
            for horizon, data in best_hold_duration_by_horizon.items()
        }
        continuation_by_horizon = {
            horizon: _round(_clamp(100.0 - continuation_failure_probability + _to_float(data.get("avg_return_pct"), 0.0) * 2.0), 2)
            for horizon, data in best_hold_duration_by_horizon.items()
        }
        horizon_exit_quality_score = {
            horizon: _round(_clamp(_to_float(data.get("avg_return_pct"), 0.0) * 5.0 + hold_duration_quality_score * 0.5 - _to_float(giveback_by_horizon.get(horizon), 0.0) * 0.35), 2)
            for horizon, data in best_hold_duration_by_horizon.items()
        }
        if best_hold_duration_by_horizon:
            strongest_horizon = max(horizon_exit_quality_score.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
            weakest_horizon = min(horizon_exit_quality_score.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        else:
            strongest_horizon = "insufficient_data"
            weakest_horizon = "insufficient_data"
        best_exit_policy_by_horizon = best_policy_by_horizon
        readiness_score = _clamp(
            hold_duration_quality_score * 0.22
            + capture_quality_score * 0.24
            + (100.0 - continuation_failure_probability) * 0.18
            + _to_float(exit_learning.get("partial_exit_confidence"), 0.0) * 0.12
            + _to_float(replay.get("replay_learning_score"), 0.0) * 0.12
            + _to_float(governance.get("truth_validation_score"), 0.0) * 0.12,
        )
        policy_confidence = _clamp(
            readiness_score * 0.55
            + _to_float(decision.get("confidence_truth_score"), 0.0) * 0.15
            + _to_float(exit_learning.get("partial_exit_confidence"), 0.0) * 0.15
            + min(20.0, tracked_trades * 0.15),
        )
        if tracked_trades < 5:
            readiness_blocker = "insufficient_trade_sample_size"
        elif _text(governance.get("warning_level"), "green") in {"orange", "red"}:
            readiness_blocker = "governance_warning_requires_shadow_only"
        elif capture_quality_score < 55 or hold_duration_quality_score < 45:
            readiness_blocker = "profit_capture_and_hold_duration_need_more_validation"
        elif continuation_failure_probability >= 65:
            readiness_blocker = "continuation_failure_signals_not_stable_enough"
        else:
            readiness_blocker = "insufficient_truth_validation_or_consistency"
        if readiness_score >= 70 and readiness_blocker == "insufficient_truth_validation_or_consistency":
            readiness_blocker = "none"
        closest_ready = best_policy if readiness_score >= 70 else highest_improvement_policy if readiness_score >= 50 else "profit_lock_exit"
        shadow = (
            "Shadow-only focus on profit lock, peak decay, continuation failure, and horizon-specific exit validation."
            if readiness_score < 70
            else "Shadow-only exit validation is approaching human-review readiness; keep policies unapplied."
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_profit_capture_peak_decay_exit_validation",
            "tracked_trades": tracked_trades,
            "tracked_closed_trades": _to_int(lifecycle.get("tracked_closed_trades"), 0),
            "tracked_active_trades": _to_int(lifecycle.get("tracked_active_trades"), 0),
            "average_capture_ratio": _round(average_capture_ratio, 4),
            "average_giveback_pct": _round(average_giveback_pct, 4),
            "capture_quality_score": _round(capture_quality_score, 2),
            "highest_giveback_trade": highest_giveback_trade,
            "best_capture_trade": best_capture_trade,
            "strongest_profit_milestone": self._milestone_label(strongest_milestone),
            "weakest_profit_milestone": self._milestone_label(weakest_milestone),
            "milestone_stats": milestone_stats,
            "continuation_failure_probability": _round(continuation_failure_probability, 2),
            "strongest_failure_signal": strongest_failure_signal,
            "best_hold_duration_by_horizon": best_hold_duration_by_horizon,
            "capture_ratio_by_horizon": capture_ratio_by_horizon,
            "giveback_by_horizon": giveback_by_horizon,
            "continuation_by_horizon": continuation_by_horizon,
            "horizon_exit_quality_score": horizon_exit_quality_score,
            "strongest_horizon": strongest_horizon,
            "weakest_horizon": weakest_horizon,
            "hold_duration_quality_score": _round(hold_duration_quality_score, 2),
            "best_exit_policy": best_policy,
            "second_best_exit_policy": second_best_policy,
            "highest_improvement_policy": highest_improvement_policy,
            "most_consistent_policy": most_consistent_policy,
            "weakest_policy": weakest_policy,
            "best_exit_policy_by_horizon": best_exit_policy_by_horizon,
            "closest_exit_policy_to_readiness": closest_ready,
            "readiness_score": _round(readiness_score, 2),
            "readiness_blocker": readiness_blocker,
            "policy_confidence": _round(policy_confidence, 2),
            "policy_stats": policy_stats,
            "replay_learning_score": _round(_to_float(replay.get("replay_learning_score"), 0.0), 2),
            "replay_average_counterfactual_improvement": _to_float(replay.get("average_counterfactual_improvement"), 0.0),
            "exit_learning_hold_longer_score": _to_float(exit_learning.get("hold_longer_score"), 0.0),
            "exit_learning_protect_profit_score": _to_float(exit_learning.get("protect_profit_score"), 0.0),
            "exit_learning_shadow_recommendation": _text(exit_learning.get("shadow_exit_learning_recommendation"), "insufficient_data"),
            "decision_quality_score": _to_float(decision.get("decision_quality_score"), 0.0),
            "virtual_paper_convergence_gap": _to_float(convergence.get("average_convergence_gap"), 0.0),
            "virtual_paper_dominant_gap_cause": _text(convergence.get("dominant_gap_cause"), "insufficient_data"),
            "virtual_paper_highest_gap_symbol": _text(convergence.get("highest_gap_symbol"), "insufficient_data"),
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "shadow_recommendation": shadow,
            "summary": (
                "Astra is validating profit capture, peak-decay, continuation failure, and exit policies using cached lifecycle and replay evidence only."
            ),
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "cache_freshness": _freshness_label(0.0),
            "dashboard_scan_rows": 0,
            "raw_history_scanned": False,
            "raw_archive_scanned": False,
            "bandwidth_saving_mode": True,
            "build_ms": 0.0,
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
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
        }
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["cache_freshness"] = _freshness_label(now - self._cache_ts)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        try:
            out = self._build({k: dict(v) for k, v in dict(statuses or {}).items() if isinstance(v, dict)})
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            out["cache_hit"] = False
            out["cache_age_seconds"] = 0.0
            out["cache_freshness"] = _freshness_label(0.0)
            _write_json(
                self.cache_path,
                {
                    "generated_at": out.get("generated_at", _now_iso()),
                    "cached_at": _now_iso(),
                    "mode": out.get("mode"),
                    "version": out.get("version"),
                    "summary": {
                        "tracked_trades": out.get("tracked_trades"),
                        "average_capture_ratio": out.get("average_capture_ratio"),
                        "average_giveback_pct": out.get("average_giveback_pct"),
                        "capture_quality_score": out.get("capture_quality_score"),
                        "best_exit_policy": out.get("best_exit_policy"),
                        "highest_improvement_policy": out.get("highest_improvement_policy"),
                        "readiness_score": out.get("readiness_score"),
                        "readiness_blocker": out.get("readiness_blocker"),
                        "shadow_recommendation": out.get("shadow_recommendation"),
                    },
                },
            )
            self._cache = dict(out)
            self._cache_ts = now
            return out
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_profit_capture_peak_decay_exit_validation",
                "tracked_trades": 0,
                "average_capture_ratio": 0.0,
                "average_giveback_pct": 0.0,
                "capture_quality_score": 0.0,
                "highest_giveback_trade": "insufficient_data",
                "best_capture_trade": "insufficient_data",
                "strongest_profit_milestone": "insufficient_data",
                "weakest_profit_milestone": "insufficient_data",
                "continuation_failure_probability": 0.0,
                "strongest_failure_signal": "insufficient_data",
                "best_hold_duration_by_horizon": {},
                "hold_duration_quality_score": 0.0,
                "best_exit_policy": "insufficient_data",
                "second_best_exit_policy": "insufficient_data",
                "highest_improvement_policy": "insufficient_data",
                "most_consistent_policy": "insufficient_data",
                "weakest_policy": "insufficient_data",
                "best_exit_policy_by_horizon": {},
                "closest_exit_policy_to_readiness": "insufficient_data",
                "readiness_score": 0.0,
                "readiness_blocker": "unavailable",
                "policy_confidence": 0.0,
                "shadow_recommendation": "unavailable",
                "behavior_safe_to_apply": False,
                "human_review_required": True,
                "auto_apply_allowed": False,
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "cache_hit": False,
                "cache_age_seconds": 0.0,
                "cache_freshness": "stale",
                "dashboard_scan_rows": 0,
                "raw_history_scanned": False,
                "raw_archive_scanned": False,
                "bandwidth_saving_mode": True,
                "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
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
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "degraded_reason": f"profit_capture_peak_decay_exit_validation_suite_v1_unavailable:{str(exc)[:140]}",
            }
