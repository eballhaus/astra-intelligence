from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_200_000
MAX_ROWS = 2200
POLICIES = (
    "continuation_failure_exit",
    "catalyst_decay_exit",
    "trailing_profit_exit",
    "profit_lock_exit",
    "fixed_hold_duration_exit",
    "volatility_based_exit",
    "archetype_specific_exit",
    "horizon_specific_exit",
)


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


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
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


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    except Exception:
        return


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if not values:
        return None
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("asset_symbol") or row.get("selected_symbol") or row.get("rejected_symbol"), "unknown").upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(row, "current_or_exit_profit_pct", "actual_return_pct", "realized_return_pct", "current_return_pct", "exit_gain_pct", "return_pct", "selected_return_pct", default=0.0)


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "peak_gain_pct", "average_mfe_pct", "later_mfe", "mfe_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct", "average_mae_pct", "later_mae", "mae_pct")


def _giveback(row: dict[str, Any]) -> float:
    return _value(row, "profit_giveback_pct", "giveback_from_peak_pct", "current_giveback_pct", "average_profit_giveback_pct")


def _capture(row: dict[str, Any]) -> float:
    raw = _value(row, "profit_capture_ratio", "capture_ratio", "average_profit_capture_ratio", default=-1.0)
    if raw >= 0:
        return _clamp(raw / 100.0 if raw > 1.5 else raw, 0.0, 1.25)
    peak = _mfe(row)
    return _clamp(_return_pct(row) / peak, 0.0, 1.25) if peak > 0 else 0.0


def _hold_minutes(row: dict[str, Any]) -> float:
    return _value(row, "hold_duration_minutes", "actual_hold_duration_minutes", "hold_time_minutes", "average_hold_duration_minutes")


def _confidence(row: dict[str, Any]) -> float | None:
    for key in ("confidence", "confidence_score", "entry_confidence", "conviction_score", "opportunity_confidence", "selection_confidence", "confidence_pct"):
        if row.get(key) not in (None, ""):
            val = _to_float(row.get(key))
            if 0 < val <= 1.5:
                val *= 100.0
            return _clamp(val)
    return None


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown_confidence"
    val = _clamp(value)
    if val >= 95:
        return "95_to_100"
    if val >= 90:
        return "90_to_94"
    if val >= 85:
        return "85_to_89"
    if val >= 80:
        return "80_to_84"
    if val >= 70:
        return "70_to_79"
    return "below_70"


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("recommended_horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    hold = _hold_minutes(row)
    if "scalp" in raw or (0 < hold < 30):
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or hold >= 1440:
        return "swing"
    if "day" in raw or (0 < hold < 390):
        return "day_trade"
    return "unknown"


def _archetype(row: dict[str, Any]) -> str:
    return _text(row.get("trade_archetype") or row.get("archetype") or row.get("setup_type") or row.get("opportunity_type"), "unknown")


def _regime(row: dict[str, Any]) -> str:
    return _text(row.get("market_regime") or row.get("regime") or row.get("session_type"), "unknown")


def _catalyst(row: dict[str, Any]) -> str:
    return _text(row.get("primary_catalyst") or row.get("catalyst_type") or row.get("dominant_catalyst") or row.get("dominant_catalyst_type"), "unknown_catalyst")


def _is_closed(row: dict[str, Any]) -> bool:
    status = _text(row.get("status") or row.get("lifecycle_status") or row.get("position_status"), "").lower()
    return bool(row.get("exit_timestamp") or row.get("exit_price") or row.get("closed_at") or row.get("exit_label") or status in {"closed", "exited", "complete", "completed"})


def _normalize_trade(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    sym = _symbol(row)
    if not sym or sym == "UNKNOWN":
        return None
    peak = _mfe(row)
    ret = _return_pct(row)
    giveback = _giveback(row)
    capture = _capture(row)
    continuation = _value(row, "continuation_strength_score", "follow_through_quality_score", "follow_through_score", "continuation_after_entry_pct", default=50.0)
    return {
        "symbol": sym,
        "source": source,
        "return_pct": ret,
        "mfe": peak,
        "mae": _mae(row),
        "giveback": giveback,
        "capture_ratio": capture,
        "hold_minutes": _hold_minutes(row),
        "confidence": _confidence(row),
        "confidence_bucket": _confidence_bucket(_confidence(row)),
        "horizon": _horizon(row),
        "archetype": _archetype(row),
        "regime": _regime(row),
        "catalyst": _catalyst(row),
        "trade_personality": _text(row.get("trade_personality") or row.get("continuation_pattern_label"), "unknown"),
        "continuation_quality": _clamp(continuation),
        "closed": _is_closed(row),
        "timestamp": _text(row.get("generated_at") or row.get("timestamp") or row.get("current_timestamp") or row.get("entry_timestamp"), ""),
    }


class DecisionOptimizationTradeManagementSuiteV1:
    """Shadow-only decision optimization and trade-management diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.state_path = os.path.join(self.state_dir, "decision_optimization_trade_management_suite_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _rows(self, name: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit)

    def _trade_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for source, rows in (
            ("lifecycle_v2", self._rows("trade_lifecycle_excursion_v2.jsonl", 900)),
            ("lifecycle_v1", self._rows("trade_lifecycle_excursion_v1.jsonl", 500)),
            ("profit_capture", self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 700)),
            ("v3", self._rows("adaptive_execution_exit_intelligence_v3.jsonl", 400)),
            ("exit_learning", self._rows("exit_learning_expansion_suite_v1.jsonl", 400)),
        ):
            for row in rows:
                item = _normalize_trade(row, source)
                if not item:
                    continue
                key = f"{item['symbol']}:{_text(row.get('lifecycle_id') or row.get('entry_timestamp') or row.get('timestamp'))[:24]}"
                merged = dict(latest.get(key) or {})
                merged.update(item)
                latest[key] = merged
        return list(latest.values())[-MAX_ROWS:]

    def _opportunity_rows(self) -> list[dict[str, Any]]:
        rows = self._rows("opportunity_cost_learning_v1.jsonl", 700)
        if not rows:
            rows = []
        return rows[-700:]

    def _simulate_policy(self, trade: dict[str, Any], policy: str) -> float:
        actual = _to_float(trade.get("return_pct"))
        peak = max(0.0, _to_float(trade.get("mfe")))
        mae = abs(min(0.0, _to_float(trade.get("mae")))) or abs(_to_float(trade.get("mae")))
        giveback = max(0.0, _to_float(trade.get("giveback")))
        capture = _to_float(trade.get("capture_ratio"), 0.0)
        continuation = _to_float(trade.get("continuation_quality"), 50.0)
        hold = _to_float(trade.get("hold_minutes"))
        horizon = _text(trade.get("horizon"), "unknown")
        arch = _text(trade.get("archetype"), "unknown")
        catalyst = _text(trade.get("catalyst"), "unknown_catalyst")
        if peak <= 0:
            return actual
        if policy == "continuation_failure_exit":
            if continuation < 45:
                return max(actual, peak * 0.55 - mae * 0.10)
            return actual
        if policy == "catalyst_decay_exit":
            decay_pressure = 0.35 if catalyst in {"unknown_catalyst", "no_detected_catalyst"} else 0.22
            return max(actual, peak * (1.0 - decay_pressure)) if giveback >= peak * decay_pressure else actual
        if policy == "trailing_profit_exit":
            trail = 0.28 if peak < 5 else 0.22
            return max(actual, peak * (1.0 - trail)) if giveback > peak * trail else actual
        if policy == "profit_lock_exit":
            lock = 0.50 if peak >= 2.0 else 0.35
            return max(actual, peak * lock)
        if policy == "fixed_hold_duration_exit":
            if horizon == "scalp" and hold > 45:
                return max(actual, peak * 0.58)
            if horizon == "day_trade" and hold > 240:
                return max(actual, peak * 0.62)
            if hold > 1440 and capture < 0.45:
                return max(actual, peak * 0.52)
            return actual
        if policy == "volatility_based_exit":
            if mae >= max(1.2, peak * 0.6):
                return max(actual, peak * 0.45)
            return actual
        if policy == "archetype_specific_exit":
            if "breakout" in arch and continuation < 50:
                return max(actual, peak * 0.55)
            if "runner" in arch or "momentum" in arch:
                return max(actual, peak * 0.65 if continuation < 55 else actual)
            return actual
        if policy == "horizon_specific_exit":
            targets = {"scalp": 0.60, "day_trade": 0.65, "short_swing": 0.58, "swing": 0.52}
            target = targets.get(horizon, 0.55)
            return max(actual, peak * target) if capture < target else actual
        return actual

    def _exit_policy_simulation(self, trades: list[dict[str, Any]]) -> dict[str, Any]:
        completed = [t for t in trades if t.get("closed") or _to_float(t.get("return_pct")) != 0]
        actual_returns = [_to_float(t.get("return_pct")) for t in completed]
        policy_stats: dict[str, dict[str, Any]] = {}
        for policy in POLICIES:
            simulated = [self._simulate_policy(t, policy) for t in completed]
            deltas = [s - a for s, a in zip(simulated, actual_returns)]
            policy_stats[policy] = {
                "sample_size": len(simulated),
                "average_actual_result": _avg(actual_returns),
                "average_simulated_result": _avg(simulated),
                "average_improvement_delta": _avg(deltas),
                "win_rate_impact": _round((sum(1 for v in simulated if v > 0) - sum(1 for v in actual_returns if v > 0)) / max(1, len(simulated)) * 100.0, 4) if simulated else 0.0,
                "profit_factor_impact": _round((_profit_factor(simulated) or 0.0) - (_profit_factor(actual_returns) or 0.0), 4),
                "reliability_score": _round(_clamp(sum(1 for d in deltas if d >= 0) / max(1, len(deltas)) * 100.0), 2),
            }
        best = max(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("average_simulated_result")), default=("insufficient_data", {}))[0]
        worst = min(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("average_simulated_result")), default=("insufficient_data", {}))[0]
        improve = max(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("average_improvement_delta")), default=("insufficient_data", {}))[0]
        reliable = max(policy_stats.items(), key=lambda kv: _to_float(kv[1].get("reliability_score")), default=("insufficient_data", {}))[0]
        return {
            "completed_lifecycles_reviewed": len(completed),
            "actual_average_result": _avg(actual_returns),
            "virtual_exit_policy_stats": policy_stats,
            "best_virtual_exit_policy": best,
            "worst_virtual_exit_policy": worst,
            "highest_improvement_policy": improve,
            "most_reliable_policy": reliable,
        }

    def _continuation_failure(self, trades: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        catalyst_v2 = statuses.get("catalyst_theme_narrative_capital_flow_intelligence_v2") or {}
        values = []
        signal_scores: dict[str, list[float]] = defaultdict(list)
        for trade in trades:
            continuation = _to_float(trade.get("continuation_quality"), 50.0)
            giveback = _to_float(trade.get("giveback"))
            capture = _to_float(trade.get("capture_ratio"), 0.0)
            peak = _to_float(trade.get("mfe"))
            ret = _to_float(trade.get("return_pct"))
            momentum_decay = _clamp(70.0 - continuation)
            volume_decay = _clamp(giveback * 3.0 + max(0.0, peak - ret) * 2.0)
            sector_weakness = 45.0 if _text(trade.get("regime")) in {"risk_off", "bearish_trend"} else 25.0
            theme_weakness = _to_float(catalyst_v2.get("unknown_catalyst_rate"), 50.0) * 0.45
            leadership_loss = 55.0 if _text(trade.get("symbol")) != _text(catalyst_v2.get("market_leader"), "") and catalyst_v2 else 25.0
            volatility_deterioration = _clamp(abs(_to_float(trade.get("mae"))) * 6.0)
            catalyst_exhaustion = _to_float(catalyst_v2.get("catalyst_decay_learning_score"), 0.0)
            narrative_breakdown = _clamp(100.0 - _to_float(catalyst_v2.get("capital_flow_confidence"), 45.0))
            row_scores = {
                "momentum_decay": momentum_decay,
                "volume_decay": volume_decay,
                "sector_weakness": sector_weakness,
                "theme_weakness": theme_weakness,
                "leadership_loss": leadership_loss,
                "volatility_deterioration": volatility_deterioration,
                "catalyst_exhaustion": catalyst_exhaustion,
                "narrative_breakdown": narrative_breakdown,
            }
            for key, score in row_scores.items():
                signal_scores[key].append(score)
            values.append(_clamp(mean(row_scores.values()) * 0.7 + max(0.0, 0.55 - capture) * 35.0))
        avg_signals = {k: _round(_avg(v) or 0.0, 2) for k, v in signal_scores.items()}
        strongest = max(avg_signals.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        weakest = min(avg_signals.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        prob = _round(_avg(values) or 0.0, 2)
        return {
            "continuation_failure_probability": prob,
            "strongest_failure_signal": strongest,
            "weakest_failure_signal": weakest,
            "failure_signal_scores": avg_signals,
            "average_failure_lead_time": "shadow_estimated_from_peak_decay_and_hold_duration",
            "average_failure_lead_time_minutes": _round(_avg([max(5.0, _to_float(t.get("hold_minutes")) * 0.22) for t in trades if _to_float(t.get("hold_minutes")) > 0]) or 0.0, 2),
            "continuation_quality_score": _round(_clamp(100.0 - prob), 2),
        }

    def _opportunity_cost(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "rejected_candidates_reviewed": 0,
                "rejection_accuracy": 0.0,
                "missed_winner_rate": 0.0,
                "avoided_loser_rate": 0.0,
                "decision_quality_score": 0.0,
                "strongest_rejection_reason": "insufficient_data",
                "weakest_rejection_reason": "insufficient_data",
                "top_missed_opportunities": [],
                "recurring_rejection_mistakes": [],
                "recurring_rejection_successes": [],
            }
        missed = [r for r in rows if bool(r.get("missed_better_candidate_flag")) or _to_float(r.get("opportunity_cost_pct")) > 0.35]
        correct = [r for r in rows if bool(r.get("correct_selection_flag")) or _to_float(r.get("opportunity_cost_pct")) <= 0.0]
        avoided = [r for r in rows if _to_float(r.get("rejected_return_pct")) <= 0.0]
        reasons: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            reason = _text(row.get("rejection_reason") or row.get("suppression_reason") or row.get("same_archetype") or row.get("ranking_improvement_recommendation"), "unknown")
            reasons[reason].append(_to_float(row.get("opportunity_cost_pct")))
        reason_avg = {k: _avg(v) or 0.0 for k, v in reasons.items()}
        strongest = min(reason_avg.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        weakest = max(reason_avg.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        top_missed = sorted(rows, key=lambda r: _to_float(r.get("opportunity_cost_pct")), reverse=True)[:8]
        return {
            "rejected_candidates_reviewed": len(rows),
            "rejection_accuracy": _round(len(correct) / max(1, len(rows)) * 100.0, 2),
            "missed_winner_rate": _round(len(missed) / max(1, len(rows)) * 100.0, 2),
            "avoided_loser_rate": _round(len(avoided) / max(1, len(rows)) * 100.0, 2),
            "decision_quality_score": _round(_clamp(len(correct) / max(1, len(rows)) * 100.0 - len(missed) / max(1, len(rows)) * 25.0), 2),
            "strongest_rejection_reason": strongest,
            "weakest_rejection_reason": weakest,
            "top_missed_opportunities": [
                {
                    "symbol": _text(r.get("rejected_symbol") or r.get("symbol"), "unknown").upper(),
                    "opportunity_cost_pct": _round(r.get("opportunity_cost_pct")),
                    "selected_symbol": _text(r.get("selected_symbol"), "unknown").upper(),
                }
                for r in top_missed
            ],
            "recurring_rejection_mistakes": [k for k, _ in sorted(reason_avg.items(), key=lambda kv: kv[1], reverse=True)[:5]],
            "recurring_rejection_successes": [k for k, _ in sorted(reason_avg.items(), key=lambda kv: kv[1])[:5]],
            "average_opportunity_cost": _avg([_to_float(r.get("opportunity_cost_pct")) for r in rows]),
            "highest_opportunity_cost": _round(max((_to_float(r.get("opportunity_cost_pct")) for r in rows), default=0.0), 4),
        }

    def _confidence_truth(self, trades: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        confidence_status = statuses.get("confidence_calibration_performance_attribution_v1") or {}
        buckets: dict[str, list[float]] = defaultdict(list)
        dims: dict[str, dict[str, list[float]]] = {"archetype": defaultdict(list), "regime": defaultdict(list), "horizon": defaultdict(list), "catalyst": defaultdict(list), "trade_personality": defaultdict(list)}
        for trade in trades:
            ret = _to_float(trade.get("return_pct"))
            buckets[_text(trade.get("confidence_bucket"), "unknown_confidence")].append(ret)
            for dim in dims:
                dims[dim][_text(trade.get(dim), "unknown")].append(ret)
        bucket_avg = {k: _avg(v) or 0.0 for k, v in buckets.items()}
        ordered_buckets = ["below_70", "70_to_79", "80_to_84", "85_to_89", "90_to_94", "95_to_100"]
        monotonic_pairs = 0
        checked_pairs = 0
        previous = None
        for bucket in ordered_buckets:
            if bucket not in bucket_avg:
                continue
            if previous is not None:
                checked_pairs += 1
                if bucket_avg[bucket] >= previous:
                    monotonic_pairs += 1
            previous = bucket_avg[bucket]
        monotonicity = _round(monotonic_pairs / max(1, checked_pairs) * 100.0, 2) if checked_pairs else _to_float(confidence_status.get("return_monotonicity"), 0.0)
        best = max(bucket_avg.items(), key=lambda kv: kv[1], default=(_text(confidence_status.get("best_confidence_bucket"), "insufficient_data"), 0.0))[0]
        worst = min(bucket_avg.items(), key=lambda kv: kv[1], default=(_text(confidence_status.get("worst_confidence_bucket"), "insufficient_data"), 0.0))[0]
        predictive = _to_float(confidence_status.get("confidence_predictive_power"), monotonicity)
        truth = _round(_clamp((predictive * 0.45) + (monotonicity * 0.35) + min(20.0, len(trades) * 0.04)), 2)
        return {
            "confidence_truth_score": truth,
            "predictive_power": _round(predictive, 2),
            "sizing_readiness_score": _round(_to_float(confidence_status.get("sizing_readiness_score"), truth * 0.55), 2),
            "confidence_reliability": "monotonic" if monotonicity >= 70 else "mixed" if monotonicity >= 45 else "not_yet_reliable",
            "best_confidence_bucket": best,
            "worst_confidence_bucket": worst,
            "confidence_bucket_outcomes": bucket_avg,
            "confidence_monotonicity": monotonicity,
            "confidence_by_archetype": {k: _avg(v) for k, v in dims["archetype"].items() if v},
            "confidence_by_regime": {k: _avg(v) for k, v in dims["regime"].items() if v},
            "confidence_by_horizon": {k: _avg(v) for k, v in dims["horizon"].items() if v},
            "confidence_by_catalyst": {k: _avg(v) for k, v in dims["catalyst"].items() if v},
            "confidence_by_trade_personality": {k: _avg(v) for k, v in dims["trade_personality"].items() if v},
            "higher_confidence_produces_better_outcomes": bool(monotonicity >= 70),
            "confidence_weighted_sizing_may_eventually_be_justified": bool(monotonicity >= 75 and len(trades) >= 80 and predictive >= 65),
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        trades = self._trade_rows()
        opportunity = self._opportunity_rows()
        exit_sim = self._exit_policy_simulation(trades)
        continuation = self._continuation_failure(trades, statuses)
        opportunity_diag = self._opportunity_cost(opportunity)
        confidence = self._confidence_truth(trades, statuses)
        gap_scores = {
            "hold_duration_optimization": abs(_to_float((exit_sim.get("virtual_exit_policy_stats") or {}).get("fixed_hold_duration_exit", {}).get("average_improvement_delta"), 0.0)),
            "profit_capture_optimization": abs(_to_float((exit_sim.get("virtual_exit_policy_stats") or {}).get("profit_lock_exit", {}).get("average_improvement_delta"), 0.0)),
            "continuation_failure_detection": _to_float(continuation.get("continuation_failure_probability"), 0.0),
            "opportunity_cost_analysis": abs(_to_float(opportunity_diag.get("highest_opportunity_cost"), 0.0)),
            "confidence_truth_calibration": 100.0 - _to_float(confidence.get("confidence_truth_score"), 0.0),
        }
        biggest_gap = max(gap_scores.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        strongest_improvement = exit_sim.get("highest_improvement_policy", "insufficient_data")
        shadow = f"shadow_only_focus_on_{biggest_gap}; review_{strongest_improvement}_before_any_human_approved_policy_change"
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_decision_optimization_trade_management",
            "generated_at": _now_iso(),
            "evidence_count": len(trades) + len(opportunity),
            "tracked_trades": len(trades),
            "opportunity_rows_reviewed": len(opportunity),
            **exit_sim,
            **continuation,
            **opportunity_diag,
            **confidence,
            "biggest_decision_gap": biggest_gap,
            "strongest_improvement_area": strongest_improvement,
            "highest_opportunity_cost": opportunity_diag.get("highest_opportunity_cost"),
            "top_exit_learning_focus": exit_sim.get("highest_improvement_policy"),
            "confidence_calibration_status": confidence.get("confidence_reliability"),
            "decision_gap_scores": {k: _round(v, 2) for k, v in gap_scores.items()},
            "trade_management_intelligence_score": _round(_clamp((_to_float(confidence.get("confidence_truth_score")) * 0.25) + (_to_float(opportunity_diag.get("decision_quality_score")) * 0.25) + (_to_float(continuation.get("continuation_quality_score")) * 0.25) + min(25.0, len(trades) * 0.02)), 2),
            "shadow_recommendation": shadow,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "behavior_safe_to_apply": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "cache_hit": False,
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
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
        }
        return out

    def _write_summary(self, out: dict[str, Any]) -> None:
        now = time.time()
        if now - self._last_write < 180.0:
            return
        self._last_write = now
        _append_jsonl(self.state_path, {k: out.get(k) for k in (
            "generated_at", "evidence_count", "best_virtual_exit_policy", "highest_improvement_policy",
            "continuation_failure_probability", "decision_quality_score", "confidence_truth_score",
            "biggest_decision_gap", "shadow_recommendation", "behavior_safe_to_apply",
        )})

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if self._cache is not None and not force and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            return cached
        try:
            out = self._build({k: dict(v) for k, v in dict(statuses or {}).items() if isinstance(v, dict)})
            self._write_summary(out)
            self._cache = dict(out)
            self._cache_ts = now
            return out
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_decision_optimization_trade_management",
                "evidence_count": 0,
                "tracked_trades": 0,
                "best_virtual_exit_policy": "insufficient_data",
                "worst_virtual_exit_policy": "insufficient_data",
                "highest_improvement_policy": "insufficient_data",
                "most_reliable_policy": "insufficient_data",
                "continuation_failure_probability": 0.0,
                "strongest_failure_signal": "insufficient_data",
                "weakest_failure_signal": "insufficient_data",
                "continuation_quality_score": 0.0,
                "rejection_accuracy": 0.0,
                "missed_winner_rate": 0.0,
                "avoided_loser_rate": 0.0,
                "decision_quality_score": 0.0,
                "confidence_truth_score": 0.0,
                "predictive_power": 0.0,
                "sizing_readiness_score": 0.0,
                "confidence_reliability": "unavailable",
                "biggest_decision_gap": "unavailable",
                "strongest_improvement_area": "unavailable",
                "top_exit_learning_focus": "unavailable",
                "confidence_calibration_status": "unavailable",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"decision_optimization_trade_management_suite_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "build_ms": 0.0,
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
