from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.portfolio_diversification_correlation_v2 import PortfolioDiversificationCorrelationV2
except Exception:  # pragma: no cover - additive diagnostics only
    PortfolioDiversificationCorrelationV2 = None  # type: ignore[assignment]

VERSION = "2.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900
CACHE_TTL_SECONDS = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


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


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(row.get("realized_return_pct") or row.get("return_pct") or row.get("return_percent") or row.get("pnl_pct"), 0.0)


def _regime(row: dict[str, Any]) -> str:
    raw = _safe_text(row.get("current_market_regime") or row.get("market_regime") or row.get("regime_context") or row.get("regime_behavior")).lower()
    if any(x in raw for x in ("risk_off", "panic", "bear")):
        return "risk_off"
    if any(x in raw for x in ("risk_on", "bull", "trend")):
        return "trend"
    if "volatile" in raw or "breakout" in raw:
        return "volatile_breakout"
    if "crowd" in raw or "exhaust" in raw or "momentum" in raw:
        return "crowded_momentum"
    if "range" in raw or "choppy" in raw or "mean" in raw:
        return "ranging"
    if "neutral" in raw:
        return "neutral"
    return "uncertain"


def _maturity(evidence: int) -> str:
    if evidence <= 0:
        return "awaiting_closed_trade_evidence"
    if evidence < 20:
        return "warming_up"
    if evidence < 50:
        return "replay_accumulating"
    return "healthy"


def _metric(value: float | None, evidence: int, explanation: str) -> dict[str, Any]:
    maturity = _maturity(evidence) if value is None else ("healthy" if evidence >= 20 else _maturity(evidence))
    return {
        "value": round(float(value), 2) if value is not None else None,
        "maturity": maturity,
        "evidence_count": int(max(0, evidence)),
        "explanation": explanation,
    }


def _exit_classification(continuation: float, degradation: float, giveback: float, exhaustion: float, profit_protection: float) -> str:
    if continuation >= 78.0 and degradation < 35.0:
        return "high_conviction_hold"
    if continuation >= 66.0 and giveback < 45.0:
        return "healthy_continuation"
    if profit_protection >= 72.0 and giveback >= 55.0:
        return "protect_profit_candidate"
    if exhaustion >= 70.0:
        return "exhaustion_candidate"
    if degradation >= 70.0:
        return "weakening_structure"
    if giveback >= 62.0:
        return "trim_candidate"
    if continuation < 42.0:
        return "continuation_under_review"
    return "early_exit_candidate" if degradation >= 55.0 else "healthy_continuation"


def _execution_classification(timing: float, breakout: float, exhaustion: float, chase: float, patience: float) -> str:
    if timing >= 78.0 and breakout >= 66.0 and chase < 35.0:
        return "high_quality_confirmation"
    if exhaustion >= 70.0:
        return "exhaustion_risk_candidate"
    if chase >= 68.0:
        return "late_momentum_candidate"
    if breakout < 42.0:
        return "weak_breakout_candidate"
    if patience >= 66.0:
        return "patience_preferred"
    if timing >= 65.0:
        return "immediate_entry_candidate"
    if breakout >= 55.0:
        return "delayed_confirmation_candidate"
    return "confirmation_required"


def _lifecycle_state(stability: float, continuation: float, deterioration: float, invalidation: float, patience: float) -> str:
    if invalidation >= 72.0:
        return "invalidation_candidate"
    if deterioration >= 70.0:
        return "continuation_breakdown"
    if stability < 42.0:
        return "weakening_trade"
    if deterioration >= 55.0:
        return "early_warning"
    if patience >= 70.0 and continuation >= 60.0:
        return "patient_hold_candidate"
    if deterioration >= 48.0:
        return "fast_review_candidate"
    if invalidation >= 55.0:
        return "escalation_candidate"
    return "healthy_progression"


class AdaptiveExecutionExitIntelligenceV2:
    """Paper-only shadow diagnostics for adaptive execution and exits.

    This engine never places orders, changes thresholds, or closes trades. It
    annotates candidates and summarizes local/cached evidence for review.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self.portfolio_diversification_v2 = (
            PortfolioDiversificationCorrelationV2(state_dir=self.state_dir)
            if PortfolioDiversificationCorrelationV2 is not None
            else None
        )

    def _history(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=350))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=300))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        return rows[-MAX_ROWS:]

    def score_candidate(self, row: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        confidence = _score(r.get("confidence"), 50.0)
        entry = _score(r.get("entry_quality") or r.get("entry_filter_v2_score"), 50.0)
        follow = _score(r.get("follow_through_quality_score") or r.get("follow_through_probability"), 50.0)
        momentum = _score(r.get("momentum_expansion_score") or r.get("intraday_acceleration_score"), 50.0)
        breakout = _score(r.get("breakout_quality_score") or r.get("breakout_probability_score"), 50.0)
        liquidity = _score(r.get("liquidity_score") or r.get("liquidity_stability_score"), 55.0)
        volatility = _score(r.get("volatility_expansion_score"), 50.0)
        regime = _regime(r)
        portfolio_heat = _score(r.get("portfolio_heat_score") or r.get("portfolio_risk_score"), 35.0)
        survivability = _score(r.get("survivability_score") or r.get("portfolio_survivability_score"), 55.0)
        profit_capture = _score(r.get("profit_retention_quality") or r.get("unrealized_profit_capture_score"), 55.0)
        giveback_raw = _to_float(r.get("profit_giveback") or r.get("missed_profit_pct") or r.get("drawdown_after_peak"), 0.0)
        giveback = _clamp(giveback_raw * 8.0 if giveback_raw <= 12.0 else giveback_raw)
        exhaustion = _clamp(max(0.0, momentum - follow) * 0.75 + max(0.0, volatility - liquidity) * 0.40 + max(0.0, portfolio_heat - 60.0) * 0.25)
        chase = _score(r.get("chase_risk_score"), _clamp(max(0.0, momentum - entry) * 0.82 + max(0.0, volatility - 65.0) * 0.40))
        weak_follow = _clamp(100.0 - follow + max(0.0, chase - 55.0) * 0.35)
        continuation = _clamp(follow * 0.34 + momentum * 0.20 + breakout * 0.18 + confidence * 0.16 + liquidity * 0.12 - exhaustion * 0.16)
        degradation = _clamp(weak_follow * 0.34 + exhaustion * 0.24 + max(0.0, portfolio_heat - 55.0) * 0.20 + max(0.0, 55.0 - liquidity) * 0.22)
        continuation_decay = _clamp(degradation * 0.55 + max(0.0, 55.0 - follow) * 0.45)
        profit_protection = _clamp(profit_capture * 0.35 + (100.0 - giveback) * 0.25 + survivability * 0.20 + (100.0 - degradation) * 0.20)
        hold_quality = _clamp(continuation * 0.42 + survivability * 0.23 + profit_protection * 0.20 + confidence * 0.15)
        premature_exit_risk = _clamp(max(0.0, continuation - degradation) * 0.55 + max(0.0, 70.0 - giveback) * 0.20)
        overstaying_risk = _clamp(degradation * 0.48 + exhaustion * 0.32 + giveback * 0.20)
        exit_efficiency = _clamp(profit_protection * 0.36 + hold_quality * 0.28 + (100.0 - overstaying_risk) * 0.22 + (100.0 - premature_exit_risk) * 0.14)
        if regime == "trend":
            regime_follow = _clamp(continuation + 8.0)
            patience = _clamp(hold_quality + 8.0)
            posture = "trend_following_patience"
        elif regime == "ranging":
            regime_follow = _clamp(continuation - 8.0)
            patience = _clamp(58.0 + (100.0 - breakout) * 0.20)
            posture = "confirmation_first_range_control"
        elif regime == "volatile_breakout":
            regime_follow = _clamp(continuation + 2.0)
            patience = _clamp(hold_quality - 5.0)
            posture = "tight_survivability_review"
        elif regime == "crowded_momentum":
            regime_follow = _clamp(continuation - 10.0)
            patience = _clamp(65.0 + chase * 0.20)
            posture = "anti_chase_confirmation"
        elif regime == "risk_off":
            regime_follow = _clamp(continuation - 14.0)
            patience = _clamp(70.0 + portfolio_heat * 0.10)
            posture = "defensive_selective_mode"
        else:
            regime_follow = continuation
            patience = _clamp(55.0 + max(0.0, 55.0 - entry) * 0.20)
            posture = "cautious_selective_mode"
        regime_chase = _clamp(chase + (10.0 if regime in {"crowded_momentum", "risk_off", "uncertain"} else 0.0))
        regime_alignment = _clamp(regime_follow * 0.34 + (100.0 - regime_chase) * 0.24 + survivability * 0.22 + confidence * 0.20)
        execution_timing = _clamp(entry * 0.28 + breakout * 0.23 + liquidity * 0.16 + confidence * 0.15 + (100.0 - chase) * 0.18)
        breakout_exhaustion = _clamp(exhaustion * 0.65 + max(0.0, breakout - follow) * 0.35)
        weak_liquidity = _clamp(100.0 - liquidity)
        momentum_extension = _clamp(chase * 0.50 + exhaustion * 0.35 + volatility * 0.15)
        continuation_confirmation = _clamp(follow * 0.42 + breakout * 0.24 + confidence * 0.18 + liquidity * 0.16)
        delayed_confirmation = _clamp(patience * 0.45 + (100.0 - chase) * 0.25 + breakout * 0.15 + liquidity * 0.15)
        execution_patience = _clamp(patience * 0.52 + (100.0 - chase) * 0.28 + survivability * 0.20)
        conviction_timing = _clamp(confidence * 0.35 + entry * 0.30 + continuation_confirmation * 0.20 + (100.0 - momentum_extension) * 0.15)
        entry_realism = _clamp(execution_timing * 0.38 + continuation_confirmation * 0.22 + liquidity * 0.18 + (100.0 - weak_liquidity) * 0.12 + (100.0 - breakout_exhaustion) * 0.10)
        deterioration_velocity = _clamp(degradation * 0.55 + continuation_decay * 0.30 + exhaustion * 0.15)
        lifecycle_stability = _clamp(hold_quality * 0.35 + survivability * 0.25 + (100.0 - deterioration_velocity) * 0.25 + profit_protection * 0.15)
        escalation = _clamp(deterioration_velocity * 0.42 + overstaying_risk * 0.28 + weak_liquidity * 0.16 + portfolio_heat * 0.14)
        invalidation = _clamp(degradation * 0.46 + weak_follow * 0.24 + exhaustion * 0.20 + max(0.0, 50.0 - liquidity) * 0.10)
        lifecycle_survivability = _clamp(lifecycle_stability * 0.48 + survivability * 0.32 + (100.0 - escalation) * 0.20)
        continuation_reliability = _clamp(continuation * 0.55 + (100.0 - continuation_decay) * 0.25 + confidence * 0.20)
        expected_capture = _clamp(profit_protection * 0.42 + exit_efficiency * 0.28 + continuation_reliability * 0.18 + (100.0 - giveback) * 0.12)
        expectancy_survival = _clamp(survivability * 0.38 + lifecycle_survivability * 0.32 + regime_alignment * 0.16 + (100.0 - weak_liquidity) * 0.14)
        continuation_expectancy = _clamp(continuation * 0.44 + follow * 0.24 + regime_follow * 0.18 + confidence * 0.14)
        execution_expectancy = _clamp(entry_realism * 0.38 + execution_timing * 0.26 + (100.0 - chase) * 0.20 + liquidity * 0.16)
        regime_expectancy = _clamp(regime_alignment * 0.45 + regime_follow * 0.25 + (100.0 - regime_chase) * 0.15 + survivability * 0.15)
        adaptive_profitability = _clamp(expected_capture * 0.26 + expectancy_survival * 0.24 + continuation_expectancy * 0.20 + execution_expectancy * 0.16 + regime_expectancy * 0.14)
        review_urgency = _clamp(escalation * 0.45 + invalidation * 0.35 + overstaying_risk * 0.20)
        return {
            "adaptive_execution_exit_v2": True,
            "adaptive_execution_exit_shadow_only": True,
            "paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exit_enabled": False,
            "forced_trade_enabled": False,
            "continuation_strength": round(continuation, 2),
            "profit_protection_quality": round(profit_protection, 2),
            "profit_giveback_pressure": round(giveback, 2),
            "weak_follow_through_risk": round(weak_follow, 2),
            "degradation_probability": round(degradation, 2),
            "adaptive_hold_quality": round(hold_quality, 2),
            "continuation_decay_risk": round(continuation_decay, 2),
            "exit_efficiency_score": round(exit_efficiency, 2),
            "premature_exit_risk": round(premature_exit_risk, 2),
            "overstaying_risk": round(overstaying_risk, 2),
            "adaptive_exit_classification": _exit_classification(continuation, degradation, giveback, exhaustion, profit_protection),
            "volatility_aware_trailing_concept": "wider_review_band" if volatility >= 68.0 and continuation >= 58.0 else "standard_review_band",
            "continuation_aware_hold_pressure": round(_clamp(continuation - degradation + 50.0), 2),
            "weakening_follow_through_pressure": round(weak_follow, 2),
            "anti_panic_selling_protection": bool(continuation >= 62.0 and degradation < 50.0),
            "adaptive_patience_diagnostics": "patience_preferred" if patience >= 65.0 else "normal_review",
            "adaptive_review_urgency": round(review_urgency, 2),
            "current_regime_behavior": regime,
            "adaptive_behavior_reason": f"{regime} posture balances continuation {round(continuation,1)}, chase {round(chase,1)}, and survivability {round(survivability,1)}.",
            "regime_execution_posture": posture,
            "regime_confidence": round(_clamp(confidence * 0.35 + len(_safe_text(regime)) * 3.0 + 35.0), 2),
            "regime_adaptive_score": round(regime_alignment, 2),
            "regime_behavior_alignment": round(regime_alignment, 2),
            "regime_trade_compatibility": round(regime_alignment, 2),
            "regime_execution_quality": round(_clamp(execution_timing * 0.55 + regime_alignment * 0.45), 2),
            "regime_follow_through_expectation": round(regime_follow, 2),
            "regime_chase_risk": round(regime_chase, 2),
            "regime_patience_score": round(patience, 2),
            "regime_hold_expectation": round(_clamp((regime_follow + patience + hold_quality) / 3.0), 2),
            "regime_profit_capture_quality": round(_clamp(expected_capture * 0.60 + regime_alignment * 0.40), 2),
            "regime_survivability_pressure": round(_clamp(100.0 - expectancy_survival), 2),
            "execution_timing_quality": round(execution_timing, 2),
            "breakout_confirmation_quality": round(breakout, 2),
            "breakout_exhaustion_risk": round(breakout_exhaustion, 2),
            "weak_liquidity_risk": round(weak_liquidity, 2),
            "momentum_extension_risk": round(momentum_extension, 2),
            "continuation_confirmation_quality": round(continuation_confirmation, 2),
            "delayed_confirmation_quality": round(delayed_confirmation, 2),
            "execution_patience_quality": round(execution_patience, 2),
            "conviction_timing_quality": round(conviction_timing, 2),
            "entry_realism_score": round(entry_realism, 2),
            "contextual_execution_classification": _execution_classification(execution_timing, breakout, breakout_exhaustion, chase, patience),
            "hold_quality": round(hold_quality, 2),
            "lifecycle_stability": round(lifecycle_stability, 2),
            "continuation_health": round(continuation, 2),
            "deterioration_velocity": round(deterioration_velocity, 2),
            "adaptive_hold_patience": round(patience, 2),
            "escalation_risk": round(escalation, 2),
            "lifecycle_survivability": round(lifecycle_survivability, 2),
            "continuation_reliability": round(continuation_reliability, 2),
            "invalidation_pressure": round(invalidation, 2),
            "adaptive_lifecycle_state": _lifecycle_state(lifecycle_stability, continuation, deterioration_velocity, invalidation, patience),
            "expected_profit_capture_quality": round(expected_capture, 2),
            "expectancy_survivability_score": round(expectancy_survival, 2),
            "continuation_adjusted_expectancy": round(continuation_expectancy, 2),
            "execution_aware_expectancy": round(execution_expectancy, 2),
            "regime_adjusted_expectancy": round(regime_expectancy, 2),
            "adaptive_expectancy_adjustment": round(_clamp(adaptive_profitability - 50.0, -50.0, 50.0), 2),
            "adaptive_profitability_score": round(adaptive_profitability, 2),
            "profit_capture_quality_diagnostics": f"Capture {round(expected_capture,1)}, giveback pressure {round(giveback,1)}, exit efficiency {round(exit_efficiency,1)}.",
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in [dict(r) for r in (rows or []) if isinstance(r, dict)][:160]:
            try:
                row.update(self.score_candidate(row))
            except Exception:
                row.update({
                    "adaptive_execution_exit_v2": True,
                    "adaptive_execution_exit_shadow_only": True,
                    "adaptive_exit_classification": "continuation_under_review",
                    "contextual_execution_classification": "confirmation_required",
                    "adaptive_lifecycle_state": "early_warning",
                    "natural_exit_preserved": True,
                    "forced_exit_enabled": False,
                    "forced_trade_enabled": False,
                })
            out.append(row)
        return out

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        rows = _candidate_rows(out)
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            new_pack = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = new_pack.get(section)
                if isinstance(values, list):
                    new_pack[section] = self.decorate_candidates([dict(v) for v in values if isinstance(v, dict)])
            out[pack_key] = new_pack
        out["adaptive_execution_exit_intelligence_v2"] = True
        out["adaptive_execution_exit_summary_v2"] = self.status(rows=rows)
        return out

    def status(self, rows: list[dict[str, Any]] | None = None, force: bool = False, **_: Any) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        candidate_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        history = self._history()
        evidence = len([r for r in history if _return_pct(r) != 0 or r.get("closed_at") or r.get("exit_timestamp")])
        decorated = self.decorate_candidates(candidate_rows or history[-120:])
        maturity = _maturity(evidence)
        def avg(key: str, default: float | None = None) -> float | None:
            vals: list[float] = []
            for r in decorated:
                raw = r.get(key)
                if raw in (None, ""):
                    continue
                try:
                    vals.append(float(raw))
                except Exception:
                    continue
            if not vals:
                return default
            return round(mean(vals), 2)
        exit_counts = Counter(_safe_text(r.get("adaptive_exit_classification"), "continuation_under_review") for r in decorated)
        exec_counts = Counter(_safe_text(r.get("contextual_execution_classification"), "confirmation_required") for r in decorated)
        life_counts = Counter(_safe_text(r.get("adaptive_lifecycle_state"), "early_warning") for r in decorated)
        regime_counts = Counter(_safe_text(r.get("current_regime_behavior"), "uncertain") for r in decorated)
        adaptive_profitability = avg("adaptive_profitability_score", None)
        strongest = (exit_counts.most_common(1)[0][0] if exit_counts else "insufficient_data")
        weakest_metric = min(
            [
                (avg("continuation_strength", 50.0) or 50.0, "continuation_quality"),
                (100.0 - (avg("chase_risk_score", avg("regime_chase_risk", 50.0)) or 50.0), "chase_control"),
                (avg("exit_efficiency_score", 50.0) or 50.0, "exit_efficiency"),
                (avg("lifecycle_stability", 50.0) or 50.0, "lifecycle_stability"),
            ],
            key=lambda item: item[0],
        )[1]
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning",
            "adaptive_execution_exit_intelligence_status_v2": True,
            "maturity": maturity,
            "evidence_count": evidence,
            "candidates_evaluated": len(decorated),
            "execution_timing_diagnostics": {
                "execution_timing_quality": _metric(avg("execution_timing_quality", None), evidence, "Quality of current entry timing discipline."),
                "breakout_confirmation_quality": _metric(avg("breakout_confirmation_quality", None), evidence, "Cleanliness of breakout confirmation."),
                "breakout_exhaustion_risk": _metric(avg("breakout_exhaustion_risk", None), evidence, "Risk that breakout signal is exhausted."),
                "weak_liquidity_risk": _metric(avg("weak_liquidity_risk", None), evidence, "Execution realism risk from weak liquidity."),
                "momentum_extension_risk": _metric(avg("momentum_extension_risk", None), evidence, "Risk of chasing extended momentum."),
                "continuation_confirmation_quality": _metric(avg("continuation_confirmation_quality", None), evidence, "Confirmation quality before paper entries."),
                "delayed_confirmation_quality": _metric(avg("delayed_confirmation_quality", None), evidence, "Quality of waiting for cleaner confirmation."),
                "execution_patience_quality": _metric(avg("execution_patience_quality", None), evidence, "Patience quality in weaker conditions."),
                "conviction_timing_quality": _metric(avg("conviction_timing_quality", None), evidence, "Alignment between conviction and timing."),
                "entry_realism_score": _metric(avg("entry_realism_score", None), evidence, "Realistic entry quality after execution constraints."),
                "classification_distribution": dict(exec_counts),
            },
            "adaptive_exit_diagnostics": {
                "continuation_strength": _metric(avg("continuation_strength", None), evidence, "Strength of post-entry continuation."),
                "profit_protection_quality": _metric(avg("profit_protection_quality", None), evidence, "Ability to protect open profit without forced exits."),
                "profit_giveback_pressure": _metric(avg("profit_giveback_pressure", None), evidence, "Pressure from profit giveback."),
                "weak_follow_through_risk": _metric(avg("weak_follow_through_risk", None), evidence, "Risk of weak continuation after entry."),
                "degradation_probability": _metric(avg("degradation_probability", None), evidence, "Probability that trade structure is degrading."),
                "adaptive_hold_quality": _metric(avg("adaptive_hold_quality", None), evidence, "Quality of holding when continuation remains healthy."),
                "continuation_decay_risk": _metric(avg("continuation_decay_risk", None), evidence, "Risk that continuation is decaying."),
                "exit_efficiency_score": _metric(avg("exit_efficiency_score", None), evidence, "Shadow score for efficient natural exit review."),
                "premature_exit_risk": _metric(avg("premature_exit_risk", None), evidence, "Risk of exiting healthy trades too early."),
                "overstaying_risk": _metric(avg("overstaying_risk", None), evidence, "Risk of overstaying weakening trades."),
                "classification_distribution": dict(exit_counts),
            },
            "regime_adaptation_diagnostics": {
                "current_regime_behavior": regime_counts.most_common(1)[0][0] if regime_counts else "uncertain",
                "adaptive_behavior_reason": "Regime posture adjusts patience, chase control, and survivability review in shadow mode only.",
                "regime_execution_posture": Counter(_safe_text(r.get("regime_execution_posture"), "cautious_selective_mode") for r in decorated).most_common(1)[0][0] if decorated else "cautious_selective_mode",
                "regime_confidence": _metric(avg("regime_confidence", None), evidence, "Confidence in current regime-adaptive behavior."),
                "regime_adaptive_score": _metric(avg("regime_adaptive_score", None), evidence, "Overall regime behavior alignment."),
                "regime_chase_risk": _metric(avg("regime_chase_risk", None), evidence, "Chase risk under current regime."),
                "regime_patience_score": _metric(avg("regime_patience_score", None), evidence, "Patience expected by current regime."),
            },
            "lifecycle_adaptation_diagnostics": {
                "adaptive_review_urgency": _metric(avg("adaptive_review_urgency", None), evidence, "How urgently positions should be reviewed, not auto-exited."),
                "hold_quality": _metric(avg("hold_quality", None), evidence, "Quality of maintaining the trade."),
                "lifecycle_stability": _metric(avg("lifecycle_stability", None), evidence, "Lifecycle stability during the trade."),
                "continuation_health": _metric(avg("continuation_health", None), evidence, "Current continuation health."),
                "deterioration_velocity": _metric(avg("deterioration_velocity", None), evidence, "Speed of trade deterioration."),
                "adaptive_hold_patience": _metric(avg("adaptive_hold_patience", None), evidence, "Recommended patience level in shadow review."),
                "escalation_risk": _metric(avg("escalation_risk", None), evidence, "Risk of needing elevated review."),
                "lifecycle_survivability": _metric(avg("lifecycle_survivability", None), evidence, "Trade lifecycle survivability."),
                "continuation_reliability": _metric(avg("continuation_reliability", None), evidence, "Reliability of continuation evidence."),
                "invalidation_pressure": _metric(avg("invalidation_pressure", None), evidence, "Pressure toward normal deterministic invalidation."),
                "state_distribution": dict(life_counts),
            },
            "profitability_improvement_diagnostics": {
                "expected_profit_capture_quality": _metric(avg("expected_profit_capture_quality", None), evidence, "Expected quality of natural profit capture."),
                "expectancy_survivability_score": _metric(avg("expectancy_survivability_score", None), evidence, "Survivability-aware expectancy."),
                "continuation_adjusted_expectancy": _metric(avg("continuation_adjusted_expectancy", None), evidence, "Continuation-aware expectancy."),
                "execution_aware_expectancy": _metric(avg("execution_aware_expectancy", None), evidence, "Execution-aware expectancy."),
                "regime_adjusted_expectancy": _metric(avg("regime_adjusted_expectancy", None), evidence, "Regime-adjusted expectancy."),
                "adaptive_profitability_score": _metric(adaptive_profitability, evidence, "Composite shadow profitability score."),
            },
            "execution_posture": Counter(_safe_text(r.get("contextual_execution_classification"), "confirmation_required") for r in decorated).most_common(1)[0][0] if decorated else "confirmation_required",
            "exit_quality": avg("exit_efficiency_score", None),
            "continuation_quality": avg("continuation_strength", None),
            "chase_risk": avg("regime_chase_risk", None),
            "adaptive_profitability": adaptive_profitability,
            "lifecycle_stability": avg("lifecycle_stability", None),
            "strongest_adaptive_behavior": strongest,
            "biggest_weakness": weakest_metric,
            "summary": f"Posture {strongest}; weakest area {weakest_metric}; adaptive profitability {round(adaptive_profitability,1) if adaptive_profitability is not None else 'insufficient evidence'}.",
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "stale": False,
            "degraded_reason": "" if decorated else "waiting_for_candidate_or_lifecycle_data",
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": True,
            "deterministic_execution_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "provider_rewrite_changed": False,
            "portfolio_diversification_v2_hooks_ready": bool(self.portfolio_diversification_v2 is not None),
        }
        out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(out)
        self._cache_ts = now
        return out
