from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 3_000_000
MAX_ROWS = 1_500

DEFAULT_WEIGHT_PROFILE = {
    "expected_return_percent": 0.30,
    "probability_confidence": 0.25,
    "entry_quality": 0.15,
    "execution_readiness": 0.10,
    "liquidity_quality": 0.08,
    "volatility_adjusted_reward": 0.05,
    "horizon_fit": 0.04,
    "portfolio_risk_control": 0.03,
}

SCALP_WEIGHT_PROFILE = {
    "expected_return_percent": 0.18,
    "probability_confidence": 0.18,
    "entry_quality": 0.22,
    "execution_readiness": 0.18,
    "liquidity_quality": 0.14,
    "volatility_adjusted_reward": 0.03,
    "horizon_fit": 0.05,
    "portfolio_risk_control": 0.02,
}

DAY_TRADE_WEIGHT_PROFILE = {
    "expected_return_percent": 0.28,
    "probability_confidence": 0.22,
    "entry_quality": 0.17,
    "execution_readiness": 0.12,
    "liquidity_quality": 0.08,
    "volatility_adjusted_reward": 0.05,
    "horizon_fit": 0.05,
    "portfolio_risk_control": 0.03,
}

SWING_TRADE_WEIGHT_PROFILE = {
    "expected_return_percent": 0.31,
    "probability_confidence": 0.28,
    "entry_quality": 0.12,
    "execution_readiness": 0.06,
    "liquidity_quality": 0.05,
    "volatility_adjusted_reward": 0.07,
    "horizon_fit": 0.06,
    "portfolio_risk_control": 0.05,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score01(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _pct_to_score(value: float) -> float:
    # 0% is neutral-ish, 5% is strong, 10%+ is elite, but never blindly decisive.
    return _clamp(45.0 + (_to_float(value, 0.0) * 5.5))


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


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _safe_text(
        row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000:
        return "mega_cap"
    if "large" in raw or cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (0.0 < cap < 300_000_000):
        return "micro_cap"
    return "unknown"


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
        symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


def _grade_score(row: dict[str, Any]) -> float:
    score = _to_float(row.get("grade_percent"), _to_float(row.get("persona_weighted_grade"), -1.0))
    if score >= 0.0:
        return _clamp(score)
    return {
        "A+": 97.0,
        "A": 91.0,
        "A-": 86.0,
        "B+": 82.0,
        "B": 76.0,
        "B-": 70.0,
        "C": 58.0,
        "D": 38.0,
        "F": 15.0,
    }.get(_safe_text(row.get("grade")).upper(), 55.0)


class DynamicOpportunityWeightingProfitOptimizationV1:
    """Shadow/paper-only profitability weighting.

    This module deliberately does not alter production rankings, live trading,
    broker mode, providers, or exits. It only decorates cached/local candidates
    and reports review recommendations.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")

    def _features(self, row: dict[str, Any]) -> dict[str, float]:
        r = dict(row or {})
        expected_return = _to_float(
            r.get("expected_return_percent"),
            _to_float(
                r.get("expected_return_pct"),
                _to_float(
                    r.get("predicted_profit_percent"),
                    _to_float(r.get("profit_prediction_pct"), _to_float(r.get("expected_move_percent"), 0.0)),
                ),
            ),
        )
        if expected_return == 0.0:
            price = _to_float(r.get("current_price"), _to_float(r.get("price"), 0.0))
            target = _to_float(r.get("expected_target_mid"), _to_float(r.get("target_mid"), _to_float(r.get("expected_target_high"), 0.0)))
            if price > 0.0 and target > price:
                expected_return = ((target - price) / price) * 100.0
        confidence = _score01(r.get("confidence"), _score01(r.get("predicted_win_probability"), 55.0))
        entry_quality = _score01(
            r.get("entry_quality_v3_score"),
            _score01(r.get("entry_quality_v2_score"), _score01(r.get("entry_filter_v2_score"), 55.0)),
        )
        execution = _score01(
            r.get("execution_readiness_score"),
            _score01(r.get("order_execution_score"), _score01(r.get("execution_quality_score"), 58.0)),
        )
        liquidity = _score01(
            r.get("liquidity_score"),
            _score01(r.get("data_quality_score"), _score01(r.get("provider_confidence"), 58.0)),
        )
        horizon_style = _safe_text(r.get("best_profit_horizon") or r.get("best_horizon_style") or r.get("trade_horizon_style"), "day_trade").lower()
        horizon_fit = _score01(
            r.get("best_horizon_score"),
            max(
                _score01(r.get("scalp_fit_score"), 50.0),
                _score01(r.get("day_trade_fit_score"), 50.0),
                _score01(r.get("swing_trade_fit_score"), 50.0),
            ),
        )
        if horizon_style == "scalp":
            horizon_fit = _score01(r.get("scalp_fit_score"), horizon_fit)
        elif horizon_style == "swing_trade":
            horizon_fit = _score01(r.get("swing_trade_fit_score"), horizon_fit)
        else:
            horizon_fit = _score01(r.get("day_trade_fit_score"), horizon_fit)
        portfolio_control = _score01(
            r.get("portfolio_risk_score"),
            100.0 - max(_score01(r.get("drawdown_risk_score"), 35.0), _score01(r.get("correlation_risk_score"), 35.0)),
        )
        reward_to_risk = _to_float(r.get("estimated_reward_to_risk"), 0.0)
        if reward_to_risk <= 0.0:
            price = _to_float(r.get("current_price"), _to_float(r.get("price"), 0.0))
            stop = _to_float(r.get("stop_loss"), _to_float(r.get("stop"), 0.0))
            if price > 0.0 and stop > 0.0 and expected_return > 0.0:
                risk_pct = max(0.2, ((price - stop) / price) * 100.0)
                reward_to_risk = expected_return / risk_pct
        volatility = _score01(r.get("volatility_score"), _score01(r.get("atr_percentile"), 50.0))
        volatility_adjusted_reward = _clamp((reward_to_risk * 25.0) + _pct_to_score(expected_return) * 0.40 - max(0.0, volatility - 72.0) * 0.35)
        return {
            "expected_return_percent": round(expected_return, 4),
            "expected_return_score": _pct_to_score(expected_return),
            "probability_confidence": confidence,
            "entry_quality": entry_quality,
            "execution_readiness": execution,
            "liquidity_quality": liquidity,
            "volatility_adjusted_reward": volatility_adjusted_reward,
            "horizon_fit": horizon_fit,
            "portfolio_risk_control": portfolio_control,
        }

    def _weighted_score(self, features: dict[str, float], weights: dict[str, float]) -> float:
        score = 0.0
        for key, weight in weights.items():
            score += _to_float(features.get("expected_return_score" if key == "expected_return_percent" else key), 50.0) * float(weight)
        return _clamp(score)

    def _row_profile_scores(self, row: dict[str, Any]) -> dict[str, Any]:
        features = self._features(row)
        profile_scores = {
            "scalp": self._weighted_score(features, SCALP_WEIGHT_PROFILE),
            "day_trade": self._weighted_score(features, DAY_TRADE_WEIGHT_PROFILE),
            "swing_trade": self._weighted_score(features, SWING_TRADE_WEIGHT_PROFILE),
        }
        best_horizon = max(profile_scores.items(), key=lambda item: float(item[1]))[0]
        aggressive_profit_score = self._weighted_score(features, DEFAULT_WEIGHT_PROFILE)
        risk_penalty = 0.0
        risk_penalty += max(0.0, 55.0 - features["liquidity_quality"]) * 0.18
        risk_penalty += max(0.0, 55.0 - features["entry_quality"]) * 0.16
        risk_penalty += max(0.0, 55.0 - features["portfolio_risk_control"]) * 0.22
        risk_penalty += max(0.0, 50.0 - features["probability_confidence"]) * 0.20
        risk_adjusted_profit_score = _clamp((aggressive_profit_score * 0.72) + (profile_scores[best_horizon] * 0.28) - risk_penalty)
        high_profit = bool(features["expected_return_percent"] >= 4.0 or features["expected_return_score"] >= 72.0 or aggressive_profit_score >= 72.0)
        paper_ok = bool(
            high_profit
            and risk_adjusted_profit_score >= 58.0
            and features["probability_confidence"] >= 52.0
            and features["entry_quality"] >= 52.0
            and features["execution_readiness"] >= 45.0
            and features["liquidity_quality"] >= 45.0
            and features["portfolio_risk_control"] >= 42.0
        )
        rejection = ""
        if high_profit and not paper_ok:
            checks = [
                (features["probability_confidence"] < 52.0, "confidence_below_profit_gate"),
                (features["entry_quality"] < 52.0, "entry_quality_below_profit_gate"),
                (features["execution_readiness"] < 45.0, "execution_readiness_below_profit_gate"),
                (features["liquidity_quality"] < 45.0, "liquidity_below_profit_gate"),
                (features["portfolio_risk_control"] < 42.0, "portfolio_risk_control_below_profit_gate"),
                (risk_adjusted_profit_score < 58.0, "risk_adjusted_score_below_profit_gate"),
            ]
            rejection = next((reason for failed, reason in checks if failed), "profit_gate_not_satisfied")
        label = "elite_profit_candidate" if risk_adjusted_profit_score >= 82 else "strong_profit_candidate" if risk_adjusted_profit_score >= 70 else "paper_test_candidate" if risk_adjusted_profit_score >= 58 else "watch_profit_candidate"
        summary = (
            f"Shadow profit score {risk_adjusted_profit_score:.1f} using {best_horizon.replace('_', ' ')} profile; "
            f"expected return {features['expected_return_percent']:.2f}%, confidence {features['probability_confidence']:.1f}, "
            f"entry {features['entry_quality']:.1f}, liquidity {features['liquidity_quality']:.1f}."
        )
        return {
            **features,
            "aggressive_profit_score": round(aggressive_profit_score, 3),
            "risk_adjusted_profit_score": round(risk_adjusted_profit_score, 3),
            "best_profit_horizon": best_horizon,
            "profit_optimization_label": label,
            "profit_optimization_summary": summary,
            "profit_horizon_profile_scores": {k: round(v, 3) for k, v in profile_scores.items()},
            "high_profit_candidate": bool(high_profit),
            "paper_profit_candidate_eligible": bool(paper_ok),
            "profit_weighting_rejection_reason": rejection,
        }

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row or {})
        scored = self._row_profile_scores(out)
        if out.get("predicted_profit_percent") is None:
            out["predicted_profit_percent"] = round(_to_float(scored.get("expected_return_percent"), 0.0), 4)
        if out.get("expected_return_percent") is None:
            out["expected_return_percent"] = round(_to_float(scored.get("expected_return_percent"), 0.0), 4)
        out.update(scored)
        out["dynamic_opportunity_weighting_v1"] = True
        out["dynamic_profit_shadow_only"] = True
        out["api_calls_used"] = 0
        return out

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            next_pack = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                rows = next_pack.get(section)
                if not isinstance(rows, list):
                    continue
                next_pack[section] = [self.score_row(dict(row)) if isinstance(row, dict) else row for row in rows]
            out[pack_key] = next_pack
        rows = _candidate_rows(out)
        out["dynamic_opportunity_weighting_v1"] = True
        out["dynamic_opportunity_weighting_summary"] = self.status(rows=rows)
        out["api_calls_used"] = int(_to_float(out.get("api_calls_used"), 0.0))
        return out

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        try:
            raw_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
            scored = [self.score_row(r) for r in raw_rows[:80]]
            return self._status_from_scored(scored)
        except Exception as exc:
            return self._fallback(f"dynamic_opportunity_weighting_unavailable: {str(exc)[:140]}")

    def _status_from_scored(self, scored: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(scored))
        avg_aggressive = sum(_to_float(r.get("aggressive_profit_score"), 0.0) for r in scored) / n
        avg_risk_adj = sum(_to_float(r.get("risk_adjusted_profit_score"), 0.0) for r in scored) / n
        high_profit = [r for r in scored if bool(r.get("high_profit_candidate"))]
        high_approved = [r for r in high_profit if bool(r.get("paper_profit_candidate_eligible"))]
        high_blocked = [r for r in high_profit if not bool(r.get("paper_profit_candidate_eligible"))]
        cap_counts = Counter(_market_cap_bucket(r) for r in scored)
        large_cap_count = int(cap_counts.get("mega_cap", 0) + cap_counts.get("large_cap", 0))
        mid_cap_count = int(cap_counts.get("mid_cap", 0))
        small_cap_count = int(cap_counts.get("small_cap", 0) + cap_counts.get("micro_cap", 0))
        unknown_cap_count = int(cap_counts.get("unknown", 0))
        approved_caps = Counter(_market_cap_bucket(r) for r in high_approved)
        high_profit_small_mid = sum(1 for r in high_profit if _market_cap_bucket(r) in {"mid_cap", "small_cap", "micro_cap"})
        large_share = large_cap_count / n
        large_cap_bias = bool(large_share >= 0.67 and (small_cap_count + mid_cap_count > 0 or high_profit_small_mid > 0))
        diversity_buckets = sum(1 for _, count in cap_counts.items() if count > 0)
        candidate_diversity_score = _clamp((diversity_buckets / 5.0) * 70.0 + min(30.0, (small_cap_count + mid_cap_count) * 5.0))
        rejection_counts = Counter(_safe_text(r.get("profit_weighting_rejection_reason"), "none") for r in high_blocked)
        top_rejections = [
            {"reason": reason, "count": int(count)}
            for reason, count in rejection_counts.most_common(5)
            if reason and reason != "none"
        ]
        review = self._review_weights()
        funnel_summary = (
            f"Evaluated {len(scored)} cached candidates; {len(high_profit)} high-profit candidates, "
            f"{len(high_approved)} paper-approved, {len(high_blocked)} blocked by risk/quality gates. "
            f"Large-cap share {large_share * 100:.1f}%."
        )
        if large_cap_bias:
            funnel_summary += " Shadow audit detects possible large-cap bias; inspect mid/small-cap high-upside rejects."
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_paper_only",
            "local_only": True,
            "writes_files": False,
            "current_weight_profile": dict(DEFAULT_WEIGHT_PROFILE),
            "scalp_weight_profile": dict(SCALP_WEIGHT_PROFILE),
            "day_trade_weight_profile": dict(DAY_TRADE_WEIGHT_PROFILE),
            "swing_trade_weight_profile": dict(SWING_TRADE_WEIGHT_PROFILE),
            "average_aggressive_profit_score": round(avg_aggressive, 3),
            "average_risk_adjusted_profit_score": round(avg_risk_adj, 3),
            "high_predicted_profit_candidate_count": int(len(high_profit)),
            "high_profit_approved_count": int(len(high_approved)),
            "high_profit_blocked_count": int(len(high_blocked)),
            "large_cap_candidate_count": large_cap_count,
            "mid_cap_candidate_count": mid_cap_count,
            "small_cap_candidate_count": small_cap_count,
            "unknown_cap_candidate_count": unknown_cap_count,
            "top_high_profit_rejection_reasons": top_rejections,
            "candidate_diversity_score": round(candidate_diversity_score, 3),
            "large_cap_bias_detected": large_cap_bias,
            "large_cap_high_profit_approved_count": int(approved_caps.get("mega_cap", 0) + approved_caps.get("large_cap", 0)),
            "small_mid_high_profit_candidate_count": int(high_profit_small_mid),
            "opportunity_funnel_summary": funnel_summary,
            "recommended_weight_adjustments": review["recommended_weight_adjustments"],
            "weight_adjustment_reason": review["weight_adjustment_reason"],
            "weight_confidence": review["weight_confidence"],
            "current_weight_review_sample_size": review["sample_size"],
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "natural_exit_preserved": True,
            "alpaca_paper_only_preserved": True,
            "generated_at": _now_iso(),
        }

    def _review_weights(self) -> dict[str, Any]:
        rows = _tail_jsonl(self.labels_path, max_rows=900, max_bytes=2_000_000) + _tail_jsonl(self.lifecycle_path, max_rows=600, max_bytes=1_500_000)
        usable: list[dict[str, Any]] = []
        for row in rows[-1200:]:
            if not isinstance(row, dict):
                continue
            ret = _to_float(row.get("realized_return_pct"), _to_float(row.get("return_percent"), _to_float(row.get("pnl_pct"), 0.0)))
            label = _safe_text(row.get("outcome_label") or row.get("label")).lower()
            if ret != 0.0 or any(x in label for x in ("win", "loss", "winner", "loser")):
                scored = self._row_profile_scores(row)
                scored["realized_return_pct"] = ret
                scored["won"] = bool(ret > 0.0 or "win" in label or "winner" in label)
                usable.append(scored)
        sample = len(usable)
        if sample < 25:
            return {
                "recommended_weight_adjustments": {
                    "expected_return_percent": "hold_shadow_weight",
                    "probability_confidence": "hold_shadow_weight",
                    "entry_quality": "hold_shadow_weight",
                },
                "weight_adjustment_reason": "insufficient_completed_paper_outcomes_for_weight_review",
                "weight_confidence": "low",
                "sample_size": sample,
            }
        winners = [r for r in usable if bool(r.get("won"))]
        losers = [r for r in usable if not bool(r.get("won"))]
        def avg(key: str, group: list[dict[str, Any]]) -> float:
            return mean([_to_float(r.get(key), 0.0) for r in group]) if group else 0.0
        expected_gap = avg("expected_return_percent", winners) - avg("expected_return_percent", losers)
        confidence_gap = avg("probability_confidence", winners) - avg("probability_confidence", losers)
        entry_gap = avg("entry_quality", winners) - avg("entry_quality", losers)
        adjustments: dict[str, str] = {}
        if expected_gap < -0.5:
            adjustments["expected_return_percent"] = "slightly_reduce_until_high_profit_predictions_validate"
        elif expected_gap > 0.75:
            adjustments["expected_return_percent"] = "maintain_or_slightly_increase_shadow_weight"
        else:
            adjustments["expected_return_percent"] = "hold_shadow_weight"
        if confidence_gap < -2.0:
            adjustments["probability_confidence"] = "review_confidence_truthfulness_too_loose"
        elif confidence_gap > 2.0:
            adjustments["probability_confidence"] = "maintain_confidence_weight"
        else:
            adjustments["probability_confidence"] = "hold_shadow_weight"
        if entry_gap > 2.0:
            adjustments["entry_quality"] = "consider_increasing_entry_quality_weight_in_shadow"
        elif entry_gap < -2.0:
            adjustments["entry_quality"] = "review_entry_quality_calibration"
        else:
            adjustments["entry_quality"] = "hold_shadow_weight"
        return {
            "recommended_weight_adjustments": adjustments,
            "weight_adjustment_reason": (
                f"Outcome review sample={sample}; expected_return winner/loser gap={expected_gap:.2f}, "
                f"confidence gap={confidence_gap:.2f}, entry gap={entry_gap:.2f}."
            ),
            "weight_confidence": "medium" if sample >= 75 else "low",
            "sample_size": sample,
        }

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "shadow_paper_only",
            "local_only": True,
            "writes_files": False,
            "current_weight_profile": dict(DEFAULT_WEIGHT_PROFILE),
            "scalp_weight_profile": dict(SCALP_WEIGHT_PROFILE),
            "day_trade_weight_profile": dict(DAY_TRADE_WEIGHT_PROFILE),
            "swing_trade_weight_profile": dict(SWING_TRADE_WEIGHT_PROFILE),
            "average_aggressive_profit_score": 0.0,
            "average_risk_adjusted_profit_score": 0.0,
            "high_predicted_profit_candidate_count": 0,
            "high_profit_approved_count": 0,
            "high_profit_blocked_count": 0,
            "large_cap_bias_detected": False,
            "candidate_diversity_score": 0.0,
            "recommended_weight_adjustments": {},
            "weight_adjustment_reason": reason,
            "weight_confidence": "low",
            "opportunity_funnel_summary": reason,
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "natural_exit_preserved": True,
        }
