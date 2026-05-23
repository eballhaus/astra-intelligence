from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1000


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
    return _to_float(row.get("realized_return_pct") or row.get("return_pct") or row.get("pnl_pct"), 0.0)


def _regime_label(row: dict[str, Any]) -> str:
    explicit = _safe_text(row.get("current_market_regime") or row.get("market_regime") or row.get("regime_context")).lower()
    known = {
        "momentum_expansion",
        "momentum_exhaustion",
        "trending_bull",
        "trending_bear",
        "choppy_mean_reversion",
        "volatility_expansion",
        "volatility_compression",
        "panic_risk_off",
        "liquidity_compression",
        "rotational_market",
        "uncertain_regime",
    }
    for label in known:
        if label in explicit:
            return label
    momentum = _score01(row.get("momentum_expansion_score"), 50.0)
    trend = _score01(row.get("trend_continuation_score"), 50.0)
    volatility = _score01(row.get("volatility_expansion_score"), 50.0)
    liquidity = _score01(row.get("liquidity_score"), _score01(row.get("liquidity_stability_score"), 55.0))
    change = _to_float(row.get("change_percent"), _to_float(row.get("change_pct"), 0.0))
    exhaustion = _score01(row.get("trend_exhaustion_score"), _score01(row.get("trend_exhaustion_behavior_score"), 35.0))
    if liquidity < 35.0:
        return "liquidity_compression"
    if change <= -4.0 and volatility >= 70.0:
        return "panic_risk_off"
    if volatility >= 72.0 and momentum >= 58.0:
        return "volatility_expansion"
    if momentum >= 66.0 and trend >= 62.0:
        return "momentum_expansion"
    if exhaustion >= 70.0:
        return "momentum_exhaustion"
    if change >= 0.8 and trend >= 58.0:
        return "trending_bull"
    if change <= -0.8 and trend <= 45.0:
        return "trending_bear"
    if volatility <= 35.0:
        return "volatility_compression"
    if abs(change) <= 0.7 and trend < 55.0:
        return "choppy_mean_reversion"
    return "uncertain_regime"


def _execution_label(score: float, chase: float, breakout_failure: float, follow: float) -> str:
    if chase >= 72.0:
        return "chase_risk"
    if breakout_failure >= 72.0:
        return "fake_breakout_risk"
    if follow < 38.0:
        return "low_follow_through_probability"
    if score >= 84.0:
        return "elite_execution"
    if score >= 70.0:
        return "strong_execution"
    if score >= 52.0:
        return "acceptable_execution"
    return "weak_execution"


def _portfolio_label(score: float, concentration: float, volatility_stack: float) -> str:
    if score >= 74.0 and concentration < 45.0:
        return "healthy_portfolio"
    if concentration >= 82.0:
        return "overexposed_portfolio"
    if volatility_stack >= 72.0:
        return "volatility_stack_risk"
    if concentration >= 62.0:
        return "concentration_risk"
    if score < 45.0:
        return "elevated_heat"
    return "balanced_portfolio"


def _survivability_label(score: float, instability: float, profit_retention: float) -> str:
    if instability >= 75.0:
        return "high_instability_risk"
    if profit_retention < 38.0:
        return "weak_profit_retention"
    if score >= 84.0:
        return "elite_survivability"
    if score >= 70.0:
        return "strong_survivability"
    if score >= 52.0:
        return "acceptable_survivability"
    return "fragile_trade"


def _context_label(score: float) -> str:
    if score >= 82.0:
        return "mature_survivability_system"
    if score >= 66.0:
        return "advanced_context_system"
    if score >= 48.0:
        return "adaptive_context_system"
    return "emerging_context_system"


class RegimeExecutionSurvivabilityIntelligenceV1:
    """Shadow-only regime, execution, portfolio, and survivability diagnostics."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._cache: dict[str, Any] | None = None

    def _history(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return list(self._cache.get("rows") or [])
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=400))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=350))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        self._cache = {"rows": rows[-MAX_ROWS:]}
        return rows[-MAX_ROWS:]

    @staticmethod
    def _portfolio_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(rows))
        sectors = Counter(_safe_text(r.get("sector") or r.get("sector_name"), "unknown").lower() for r in rows)
        caps = Counter(_safe_text(r.get("candidate_universe_tier") or r.get("market_cap_bucket"), "unknown").lower() for r in rows)
        archetypes = Counter(_safe_text(r.get("trade_archetype") or r.get("setup_type"), "unknown").lower() for r in rows)
        regimes = Counter(_regime_label(r) for r in rows)
        max_sector = max((v for k, v in sectors.items() if k != "unknown"), default=0) / n
        max_cap = max((v for k, v in caps.items() if k != "unknown"), default=0) / n
        max_archetype = max((v for k, v in archetypes.items() if k != "unknown"), default=0) / n
        concentration = _clamp(max(max_sector, max_cap, max_archetype) * 100.0)
        correlation = _clamp(concentration * 0.65 + max(0.0, caps.get("mega_cap", 0) / n * 100.0) * 0.35)
        momentum_stack = sum(1 for r in rows if "momentum" in _safe_text(r.get("trade_archetype") or r.get("candidate_opportunity_type")).lower()) / n
        volatility_stack = _clamp(momentum_stack * 55.0 + mean([_score01(r.get("volatility_expansion_score"), 50.0) for r in rows]) * 0.45 if rows else 50.0)
        drawdown = _clamp(correlation * 0.35 + volatility_stack * 0.35 + concentration * 0.30)
        stability = _clamp(100.0 - drawdown * 0.58 + max(0.0, 100.0 - concentration) * 0.22)
        survivability = _clamp(stability * 0.45 + (100.0 - correlation) * 0.25 + (100.0 - volatility_stack) * 0.20 + 10.0)
        heat_eff = _clamp(survivability - drawdown * 0.25 + 20.0)
        return {
            "portfolio_survivability_score": round(survivability, 2),
            "portfolio_concentration_risk": round(concentration, 2),
            "portfolio_correlation_risk": round(correlation, 2),
            "portfolio_volatility_stack_risk": round(volatility_stack, 2),
            "portfolio_drawdown_risk": round(drawdown, 2),
            "portfolio_heat_efficiency": round(heat_eff, 2),
            "portfolio_stability_score": round(stability, 2),
            "portfolio_adaptation_score": round(_clamp(survivability * 0.55 + heat_eff * 0.25 + (100.0 - concentration) * 0.20), 2),
            "portfolio_diversification_quality": round(_clamp(100.0 - concentration), 2),
            "portfolio_label": _portfolio_label(survivability, concentration, volatility_stack),
            "portfolio_balance_summary": f"Cap mix {dict(caps)}; regime mix {dict(regimes)}.",
            "portfolio_risk_compression_summary": f"Concentration {round(concentration, 1)}, correlation {round(correlation, 1)}, volatility stack {round(volatility_stack, 1)}.",
        }

    def score_row(self, row: dict[str, Any], peers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        r = dict(row or {})
        peers = [dict(x) for x in (peers or [r]) if isinstance(x, dict)][:120]
        regime = _regime_label(r)
        confidence = _score01(r.get("confidence"), 50.0)
        entry = _score01(r.get("entry_quality"), _score01(r.get("entry_filter_v2_score"), 50.0))
        exit_q = _score01(r.get("exit_quality_score"), 50.0)
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("liquidity_stability_score"), 55.0))
        momentum = _score01(r.get("momentum_expansion_score"), 50.0)
        trend = _score01(r.get("trend_continuation_score"), 50.0)
        breakout = _score01(r.get("breakout_probability_score"), _score01(r.get("breakout_quality_score"), 50.0))
        volatility = _score01(r.get("volatility_expansion_score"), 50.0)
        follow = _score01(r.get("expected_follow_through_score"), _score01(r.get("follow_through_quality_score"), 50.0))
        change = abs(_to_float(r.get("change_percent"), _to_float(r.get("change_pct"), 0.0)))
        chase = _clamp(max(0.0, momentum - entry) * 0.75 + change * 5.0 + max(0.0, volatility - 72.0) * 0.30)
        breakout_failure = _clamp((100.0 - follow) * 0.45 + max(0.0, volatility - liquidity) * 0.30 + max(0.0, chase - 50.0) * 0.25)
        slippage = _clamp(max(0.0, 65.0 - liquidity) * 0.70 + volatility * 0.18 + change * 3.0)
        spread = _clamp(max(0.0, 70.0 - liquidity) * 0.85 + volatility * 0.10)
        pullback = _clamp(entry * 0.45 + (100.0 - chase) * 0.25 + trend * 0.20 + liquidity * 0.10)
        execution = _clamp(entry * 0.26 + follow * 0.22 + liquidity * 0.18 + breakout * 0.14 + (100.0 - chase) * 0.12 + (100.0 - slippage) * 0.08)
        execution_eff = _clamp(execution * 0.70 + (100.0 - spread) * 0.15 + (100.0 - breakout_failure) * 0.15)
        regime_risk = _clamp(chase * 0.28 + volatility * 0.24 + max(0.0, 55.0 - liquidity) * 0.28 + breakout_failure * 0.20)
        regime_alignment = _clamp(confidence * 0.18 + trend * 0.18 + follow * 0.20 + liquidity * 0.16 + (100.0 - regime_risk) * 0.28)
        regime_score = _clamp(regime_alignment * 0.65 + confidence * 0.20 + execution * 0.15)
        portfolio = self._portfolio_context(peers)
        mae = abs(_to_float(r.get("max_adverse_excursion") or r.get("drawdown_pct"), 0.0))
        mfe = max(0.0, _to_float(r.get("max_favorable_excursion") or r.get("peak_unrealized_pnl_percent"), 0.0))
        ret = _return_pct(r)
        giveback = max(0.0, mfe - max(0.0, ret))
        drawdown_resistance = _clamp(100.0 - mae * 8.0 + liquidity * 0.12 + entry * 0.10)
        volatility_survival = _clamp(100.0 - volatility * 0.45 + follow * 0.25 + liquidity * 0.20)
        adverse_resilience = _clamp(100.0 - mae * 9.0 + exit_q * 0.18)
        profit_retention = _clamp(100.0 - giveback * 12.0 + max(0.0, ret) * 2.0)
        durability = _clamp(follow * 0.28 + drawdown_resistance * 0.24 + volatility_survival * 0.20 + profit_retention * 0.18 + liquidity * 0.10)
        instability = _clamp((100.0 - durability) * 0.45 + chase * 0.25 + volatility * 0.18 + breakout_failure * 0.12)
        risk_compression = _clamp((100.0 - mae * 8.0) * 0.35 + (100.0 - slippage) * 0.20 + (100.0 - portfolio["portfolio_drawdown_risk"]) * 0.25 + entry * 0.20)
        survivability = _clamp(durability * 0.42 + risk_compression * 0.26 + portfolio["portfolio_survivability_score"] * 0.18 + execution * 0.14)
        return {
            "regime_score": round(regime_score, 2),
            "regime_confidence": round(_clamp(confidence * 0.35 + len(peers) / 12.0 * 25.0 + 35.0), 2),
            "current_market_regime": regime,
            "regime_stability_score": round(_clamp(100.0 - regime_risk * 0.55 + trend * 0.20), 2),
            "regime_risk_score": round(regime_risk, 2),
            "regime_behavior_summary": f"{regime.replace('_', ' ')} with risk {round(regime_risk, 1)} and alignment {round(regime_alignment, 1)}.",
            "regime_trade_alignment_score": round(regime_alignment, 2),
            "execution_quality_score": round(execution, 2),
            "entry_timing_quality": round(entry, 2),
            "exit_timing_quality": round(exit_q, 2),
            "breakout_quality_score": round(breakout, 2),
            "breakout_failure_risk": round(breakout_failure, 2),
            "chase_risk_score": round(chase, 2),
            "slippage_risk_score": round(slippage, 2),
            "spread_risk_score": round(spread, 2),
            "pullback_entry_quality": round(pullback, 2),
            "follow_through_probability": round(follow, 2),
            "execution_efficiency_score": round(execution_eff, 2),
            "execution_quality_label": _execution_label(execution, chase, breakout_failure, follow),
            **portfolio,
            "survivability_score": round(survivability, 2),
            "risk_compression_score": round(risk_compression, 2),
            "drawdown_resistance_score": round(drawdown_resistance, 2),
            "volatility_survival_score": round(volatility_survival, 2),
            "adverse_excursion_resilience": round(adverse_resilience, 2),
            "profit_retention_quality": round(profit_retention, 2),
            "trade_durability_score": round(durability, 2),
            "instability_risk_score": round(instability, 2),
            "survivability_label": _survivability_label(survivability, instability, profit_retention),
            "regime_execution_alignment": round(_clamp(regime_alignment * 0.55 + execution * 0.45), 2),
            "adaptive_execution_summary": f"Execution {round(execution, 1)}, chase risk {round(chase, 1)}, survivability {round(survivability, 1)}.",
            "regime_execution_survivability_intelligence_v1": True,
            "regime_execution_shadow_only": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        peers = [dict(r) for r in (rows or []) if isinstance(r, dict)][:120]
        out: list[dict[str, Any]] = []
        for row in peers:
            r = dict(row)
            try:
                r.update(self.score_row(r, peers))
            except Exception:
                r.update(
                    {
                        "current_market_regime": "uncertain_regime",
                        "execution_quality_score": 50.0,
                        "portfolio_survivability_score": 50.0,
                        "survivability_score": 50.0,
                        "risk_compression_score": 50.0,
                        "regime_execution_survivability_intelligence_v1": True,
                        "regime_execution_shadow_only": True,
                        "natural_exit_preserved": True,
                        "forced_early_exit_enabled": False,
                    }
                )
            out.append(r)
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
        out["regime_execution_survivability_intelligence_v1"] = True
        out["regime_execution_survivability_summary"] = self.status(rows=rows)
        return out

    @staticmethod
    def _group_expectancy(rows: list[dict[str, Any]], key_fn) -> dict[str, dict[str, float]]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            grouped[key_fn(row)].append(_return_pct(row))
        out: dict[str, dict[str, float]] = {}
        for key, values in grouped.items():
            wins = [v for v in values if v > 0]
            losses = [abs(v) for v in values if v < 0]
            pf = sum(wins) / sum(losses) if sum(losses) > 0 else (sum(wins) if wins else 0.0)
            out[key] = {
                "sample_size": float(len(values)),
                "win_rate": round(len(wins) / max(1, len(values)) * 100.0, 2),
                "avg_return": round(mean(values), 4),
                "profit_factor": round(pf, 4),
                "survivability": round(_clamp(55.0 + mean(values) * 10.0 - (pstdev(values) * 40.0 if len(values) > 1 else 10.0)), 2),
            }
        return out

    def status(self, rows: list[dict[str, Any]] | None = None, paper_trace: dict[str, Any] | None = None) -> dict[str, Any]:
        candidate_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        history = self._history()
        combined = (candidate_rows + history)[-MAX_ROWS:]
        decorated = self.decorate_candidates(candidate_rows or combined)
        history_decorated = self.decorate_candidates(history[-MAX_ROWS:])
        regime_stats = self._group_expectancy(history_decorated or decorated, lambda r: _safe_text(r.get("current_market_regime") or _regime_label(r), "uncertain_regime"))
        if regime_stats:
            strongest_regime = max(regime_stats.items(), key=lambda kv: kv[1].get("avg_return", -999.0))[0]
            weakest_regime = min(regime_stats.items(), key=lambda kv: kv[1].get("avg_return", 999.0))[0]
        else:
            strongest_regime = "insufficient_data"
            weakest_regime = "insufficient_data"
        current_regime = Counter(_safe_text(r.get("current_market_regime"), "uncertain_regime") for r in decorated).most_common(1)[0][0] if decorated else "uncertain_regime"
        exec_scores = [_score01(r.get("execution_quality_score"), 50.0) for r in decorated]
        survivability_scores = [_score01(r.get("survivability_score"), 50.0) for r in decorated]
        chase_scores = [_score01(r.get("chase_risk_score"), 50.0) for r in decorated]
        breakout_scores = [_score01(r.get("breakout_quality_score"), 50.0) for r in decorated]
        follow_scores = [_score01(r.get("follow_through_probability"), 50.0) for r in decorated]
        portfolio = self._portfolio_context(decorated)
        regimes = Counter(_safe_text(r.get("current_market_regime"), "uncertain_regime") for r in decorated)
        regime_conf = _clamp(max(regimes.values(), default=0) / max(1, len(decorated)) * 55.0 + min(len(history), 250) / 250.0 * 30.0 + 15.0)
        execution_quality = mean(exec_scores) if exec_scores else 50.0
        survivability_score = mean(survivability_scores) if survivability_scores else 50.0
        chase_risk = mean(chase_scores) if chase_scores else 50.0
        breakout_quality = mean(breakout_scores) if breakout_scores else 50.0
        follow = mean(follow_scores) if follow_scores else 50.0
        regime_intel = _clamp(regime_conf * 0.28 + (100.0 - mean([_score01(r.get("regime_risk_score"), 50.0) for r in decorated]) if decorated else 50.0) * 0.22 + execution_quality * 0.25 + survivability_score * 0.25)
        exec_intel = _clamp(execution_quality * 0.55 + breakout_quality * 0.20 + follow * 0.15 + (100.0 - chase_risk) * 0.10)
        survival_intel = _clamp(survivability_score * 0.55 + mean([_score01(r.get("risk_compression_score"), 50.0) for r in decorated]) * 0.25 + portfolio["portfolio_survivability_score"] * 0.20) if decorated else 50.0
        portfolio_maturity = _clamp(portfolio["portfolio_adaptation_score"] * 0.65 + portfolio["portfolio_diversification_quality"] * 0.20 + (100.0 - portfolio["portfolio_drawdown_risk"]) * 0.15)
        context_awareness = _clamp(regime_intel * 0.30 + exec_intel * 0.24 + survival_intel * 0.26 + portfolio_maturity * 0.20)
        env_stats = self._group_expectancy(history_decorated or decorated, lambda r: f"{_safe_text(r.get('current_market_regime') or _regime_label(r))}:{_safe_text(r.get('execution_quality_label'), 'unknown')}")
        arch_stats = self._group_expectancy(history_decorated or decorated, lambda r: _safe_text(r.get("trade_archetype") or r.get("setup_type"), "unknown").lower().replace(" ", "_"))
        strongest_env = max(env_stats.items(), key=lambda kv: kv[1].get("avg_return", -999.0))[0] if env_stats else "insufficient_data"
        weakest_env = min(env_stats.items(), key=lambda kv: kv[1].get("avg_return", 999.0))[0] if env_stats else "insufficient_data"
        strongest_arch = max(arch_stats.items(), key=lambda kv: kv[1].get("survivability", -999.0))[0] if arch_stats else "insufficient_data"
        weakest_arch = min(arch_stats.items(), key=lambda kv: kv[1].get("survivability", 999.0))[0] if arch_stats else "insufficient_data"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning",
            "regime_execution_survivability_status_v1": True,
            "adaptive_regime_intelligence_score": round(regime_intel, 2),
            "execution_intelligence_score": round(exec_intel, 2),
            "survivability_intelligence_score": round(survival_intel, 2),
            "portfolio_adaptation_maturity_score": round(portfolio_maturity, 2),
            "market_context_awareness_score": round(context_awareness, 2),
            "market_context_awareness_label": _context_label(context_awareness),
            "regime_score": round(mean([_score01(r.get("regime_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "regime_confidence": round(regime_conf, 2),
            "current_market_regime": current_regime,
            "regime_stability_score": round(mean([_score01(r.get("regime_stability_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "regime_risk_score": round(mean([_score01(r.get("regime_risk_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "regime_behavior_summary": f"Current regime {current_regime.replace('_', ' ')}; confidence {round(regime_conf, 1)}.",
            "regime_trade_alignment_score": round(mean([_score01(r.get("regime_trade_alignment_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "strongest_regime": strongest_regime,
            "weakest_regime": weakest_regime,
            "regime_profitability_summary": {k: v for k, v in list(regime_stats.items())[:8]},
            "regime_risk_summary": f"Strongest regime {strongest_regime}; weakest regime {weakest_regime}.",
            "execution_quality_score": round(execution_quality, 2),
            "entry_timing_quality": round(mean([_score01(r.get("entry_timing_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "exit_timing_quality": round(mean([_score01(r.get("exit_timing_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "breakout_quality_score": round(breakout_quality, 2),
            "breakout_failure_risk": round(mean([_score01(r.get("breakout_failure_risk"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "chase_risk_score": round(chase_risk, 2),
            "slippage_risk_score": round(mean([_score01(r.get("slippage_risk_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "spread_risk_score": round(mean([_score01(r.get("spread_risk_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "pullback_entry_quality": round(mean([_score01(r.get("pullback_entry_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "follow_through_probability": round(follow, 2),
            "execution_efficiency_score": round(mean([_score01(r.get("execution_efficiency_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            **portfolio,
            "survivability_score": round(survivability_score, 2),
            "risk_compression_score": round(mean([_score01(r.get("risk_compression_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "drawdown_resistance_score": round(mean([_score01(r.get("drawdown_resistance_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "volatility_survival_score": round(mean([_score01(r.get("volatility_survival_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "adverse_excursion_resilience": round(mean([_score01(r.get("adverse_excursion_resilience"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "profit_retention_quality": round(mean([_score01(r.get("profit_retention_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "trade_durability_score": round(mean([_score01(r.get("trade_durability_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "instability_risk_score": round(mean([_score01(r.get("instability_risk_score"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "strongest_execution_environment": strongest_env,
            "weakest_execution_environment": weakest_env,
            "strongest_survivability_archetype": strongest_arch,
            "weakest_survivability_archetype": weakest_arch,
            "regime_execution_alignment": round(mean([_score01(r.get("regime_execution_alignment"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "adaptive_execution_summary": f"Regime {current_regime}; execution {round(execution_quality, 1)}, chase risk {round(chase_risk, 1)}, survivability {round(survivability_score, 1)}.",
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "forced_trade_enabled": False,
            "deterministic_execution_authority_preserved": True,
            "broker_safeguards_preserved": True,
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "updated_at": _now_iso(),
        }
