from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1_000

MEGA_CAP_SYMBOL_FALLBACK = {
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOG",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "BRK.B",
    "BRK-A",
    "LLY",
    "JPM",
    "V",
    "MA",
    "COST",
    "WMT",
    "NFLX",
    "ORCL",
    "XOM",
}


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


def _nonzero_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        out = _to_float(value, 0.0)
        if out != 0.0:
            return out
    return float(default)


def _pct_to_score(value: Any, neutral: float = 45.0, scale: float = 6.0) -> float:
    return _clamp(neutral + (_to_float(value, 0.0) * scale))


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


def _market_cap_bucket(row: dict[str, Any]) -> str:
    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
    raw = _safe_text(
        row.get("candidate_universe_tier")
        or row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization") or row.get("marketCap"), 0.0)
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
    if symbol in MEGA_CAP_SYMBOL_FALLBACK:
        return "mega_cap"
    return "unknown"


def _grade_score(row: dict[str, Any]) -> float:
    direct = _to_float(row.get("grade_percent"), _to_float(row.get("persona_weighted_grade"), -1.0))
    if direct >= 0.0:
        return _clamp(direct)
    return {
        "A+": 97.0,
        "A": 91.0,
        "A-": 86.0,
        "B+": 82.0,
        "B": 76.0,
        "B-": 70.0,
        "C+": 64.0,
        "C": 58.0,
        "D": 38.0,
        "F": 15.0,
    }.get(_safe_text(row.get("grade")).upper(), 55.0)


def _distribution_summary(counter: Counter[str], total: int) -> str:
    if total <= 0:
        return "No candidates available for market-cap distribution."
    parts = [f"{k.replace('_', ' ')} {v}/{total}" for k, v in counter.most_common()]
    return "; ".join(parts) if parts else "No market-cap distribution available."


class OpportunityDiscoveryExpansionV1:
    """Shadow-only discovery enrichment for asymmetric opportunity visibility.

    The suite intentionally does not change production rankings, broker execution,
    provider calls, live trading, exits, or paper safety gates. It only decorates
    candidates with local/snapshot-derived discovery diagnostics and exposes a
    cached status view for the Learning tab.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.fmp_enrichment_cache_path = os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json")
        self._learning_cache: dict[str, Any] | None = None
        self._fmp_context_cache: dict[str, dict[str, Any]] | None = None

    def _learning_scores(self) -> dict[str, dict[str, float]]:
        if self._learning_cache is not None:
            return self._learning_cache
        rows = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=350))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=350))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=300))
        type_totals: Counter[str] = Counter()
        type_wins: Counter[str] = Counter()
        cap_totals: Counter[str] = Counter()
        cap_wins: Counter[str] = Counter()
        momentum_totals: Counter[str] = Counter()
        momentum_wins: Counter[str] = Counter()
        for row in rows[-MAX_ROWS:]:
            r = dict(row or {})
            typ = _safe_text(
                r.get("candidate_opportunity_type")
                or r.get("opportunity_type")
                or r.get("setup_type")
                or r.get("strategy_family"),
                "unknown",
            ).lower().replace(" ", "_")
            cap = _market_cap_bucket(r)
            momentum_sig = _safe_text(r.get("momentum_signature") or r.get("candidate_momentum_signature"), "unknown").lower().replace(" ", "_")
            ret = _nonzero_float(r.get("realized_return_pct"), r.get("return_pct"), r.get("pnl_pct"), default=0.0)
            win_raw = _safe_text(r.get("outcome") or r.get("label") or r.get("target_hit_status")).lower()
            won = ret > 0.0 or any(token in win_raw for token in ("win", "target_hit", "profitable", "success"))
            type_totals[typ] += 1
            cap_totals[cap] += 1
            momentum_totals[momentum_sig] += 1
            if won:
                type_wins[typ] += 1
                cap_wins[cap] += 1
                momentum_wins[momentum_sig] += 1

        def build(totals: Counter[str], wins: Counter[str]) -> dict[str, float]:
            out: dict[str, float] = {}
            for key, total in totals.items():
                if total < 3:
                    out[key] = 50.0
                else:
                    out[key] = _clamp(35.0 + (wins[key] / max(1, total)) * 55.0 + min(10.0, total / 5.0))
            return out

        self._learning_cache = {
            "opportunity_type": build(type_totals, type_wins),
            "market_cap": build(cap_totals, cap_wins),
            "momentum_signature": build(momentum_totals, momentum_wins),
        }
        return self._learning_cache

    def _fmp_context(self) -> dict[str, dict[str, Any]]:
        if self._fmp_context_cache is not None:
            return self._fmp_context_cache
        context: dict[str, dict[str, Any]] = {}
        try:
            with open(self.fmp_enrichment_cache_path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            self._fmp_context_cache = {}
            return self._fmp_context_cache
        if not isinstance(raw, dict):
            self._fmp_context_cache = {}
            return self._fmp_context_cache
        for key, entry in list(raw.items())[:500]:
            if not isinstance(key, str) or "::" not in key or not isinstance(entry, dict):
                continue
            family, symbol = key.split("::", 1)
            symbol = _safe_text(symbol).upper()
            payload = entry.get("payload")
            if not symbol or not isinstance(payload, dict):
                continue
            bucket = context.setdefault(symbol, {"symbol": symbol})
            if family == "profile":
                bucket.update(
                    {
                        "market_cap": payload.get("mktCap") or payload.get("marketCap") or bucket.get("market_cap"),
                        "sector": payload.get("sector") or bucket.get("sector"),
                        "average_volume": payload.get("averageVolume") or payload.get("volAvg") or bucket.get("average_volume"),
                        "current_price": payload.get("price") or bucket.get("current_price"),
                        "change_percent": payload.get("changePercentage") or payload.get("changesPercentage") or bucket.get("change_percent"),
                    }
                )
            elif family == "quote":
                bucket.update(
                    {
                        "current_price": payload.get("price") or bucket.get("current_price"),
                        "change_percent": payload.get("changesPercentage") or payload.get("changePercentage") or bucket.get("change_percent"),
                        "volume": payload.get("volume") or bucket.get("volume"),
                    }
                )
        self._fmp_context_cache = context
        return self._fmp_context_cache

    def _augment_with_local_context(self, row: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        symbol = _safe_text(r.get("symbol") or r.get("ticker")).upper()
        ctx = (self._fmp_context().get(symbol) or {}) if symbol else {}
        if not isinstance(ctx, dict):
            return r
        for key, value in ctx.items():
            if key == "symbol":
                continue
            if r.get(key) in (None, ""):
                r[key] = value
            elif key == "change_percent" and abs(_to_float(value, 0.0)) > abs(_to_float(r.get(key), 0.0)):
                # Prefer the freshest local quote movement when it shows stronger momentum.
                r[key] = value
        return r

    def _local_discovery_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, ctx in list(self._fmp_context().items())[:80]:
            if not isinstance(ctx, dict):
                continue
            row = dict(ctx)
            row["symbol"] = symbol
            row["candidate_discovery_source"] = "local_fmp_enrichment_cache"
            row["confidence"] = 52.0
            row["entry_quality_v3_score"] = 52.0
            row["execution_readiness_score"] = 56.0
            rows.append(row)
        return rows

    def _features(self, row: dict[str, Any]) -> dict[str, float | str | bool | list[str]]:
        r = self._augment_with_local_context(dict(row or {}))
        change_pct = _nonzero_float(
            r.get("change_percent"),
            r.get("change_pct"),
            r.get("pct_change"),
            r.get("day_change_pct"),
            r.get("intraday_change_pct"),
            default=0.0,
        )
        expected_return = _nonzero_float(
            r.get("expected_return_percent"),
            r.get("expected_return_pct"),
            r.get("predicted_profit_percent"),
            r.get("profit_prediction_pct"),
            r.get("expected_move_percent"),
            default=0.0,
        )
        if expected_return == 0.0:
            price = _to_float(r.get("current_price") or r.get("price"), 0.0)
            target = _to_float(r.get("expected_target_mid") or r.get("target_mid") or r.get("target_price"), 0.0)
            if price > 0.0 and target > price:
                expected_return = ((target - price) / price) * 100.0
        rvol = _nonzero_float(r.get("relative_volume"), r.get("rvol"), r.get("relative_volume_ratio"), default=0.0)
        if rvol <= 0.0:
            volume = _to_float(r.get("volume"), 0.0)
            avg_volume = _to_float(r.get("avg_volume") or r.get("average_volume") or r.get("volume_avg_20d"), 0.0)
            if volume > 0.0 and avg_volume > 0.0:
                rvol = volume / avg_volume
        rel_volume_score = _score01(r.get("relative_volume_score"), _clamp(45.0 + max(0.0, rvol - 1.0) * 25.0 if rvol > 0 else 48.0))
        confidence = _score01(r.get("confidence"), _score01(r.get("predicted_win_probability"), 55.0))
        entry_quality = _score01(
            r.get("entry_quality_v3_score"),
            _score01(r.get("entry_quality_v2_score"), _score01(r.get("entry_filter_v2_score"), _score01(r.get("entry_quality"), 55.0))),
        )
        execution = _score01(r.get("execution_readiness_score"), _score01(r.get("order_execution_score"), _score01(r.get("execution_quality_score"), 58.0)))
        avg_volume = _to_float(r.get("avg_volume") or r.get("average_volume") or r.get("volume_avg_20d"), 0.0)
        volume_liquidity_default = 58.0
        if avg_volume >= 50_000_000:
            volume_liquidity_default = 92.0
        elif avg_volume >= 10_000_000:
            volume_liquidity_default = 82.0
        elif avg_volume >= 2_000_000:
            volume_liquidity_default = 70.0
        elif avg_volume >= 500_000:
            volume_liquidity_default = 58.0
        elif 0.0 < avg_volume < 500_000:
            volume_liquidity_default = 42.0
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("data_quality_score"), _score01(r.get("provider_confidence"), volume_liquidity_default)))
        volatility = _score01(r.get("volatility_expansion_score"), _score01(r.get("volatility_score"), _pct_to_score(abs(change_pct), neutral=45.0, scale=4.5)))
        momentum_base = _score01(r.get("momentum_score"), _pct_to_score(max(change_pct, expected_return * 0.55), neutral=45.0, scale=5.0))
        intraday_accel = _score01(
            r.get("intraday_acceleration_score"),
            _clamp((momentum_base * 0.52) + (rel_volume_score * 0.30) + (_pct_to_score(change_pct, 42.0, 4.0) * 0.18)),
        )
        breakout = _score01(
            r.get("breakout_probability_score"),
            _clamp((momentum_base * 0.38) + (entry_quality * 0.24) + (rel_volume_score * 0.22) + (volatility * 0.16)),
        )
        trend = _score01(
            r.get("trend_continuation_score"),
            _clamp((_score01(r.get("astra_score"), _grade_score(r)) * 0.25) + (confidence * 0.25) + (momentum_base * 0.25) + (entry_quality * 0.25)),
        )
        momentum_expansion = _score01(
            r.get("momentum_expansion_score"),
            _clamp((rel_volume_score * 0.24) + (intraday_accel * 0.26) + (breakout * 0.23) + (trend * 0.17) + (volatility * 0.10)),
        )
        reward_to_risk = _to_float(r.get("estimated_reward_to_risk") or r.get("reward_to_risk"), 0.0)
        reward_score = _clamp(45.0 + max(expected_return, 0.0) * 5.0 + min(15.0, max(0.0, reward_to_risk - 1.0) * 7.5))
        asymmetric_reward = _clamp((reward_score * 0.42) + (momentum_expansion * 0.22) + (confidence * 0.18) + (entry_quality * 0.18))
        catalyst_text = _safe_text(r.get("catalyst") or r.get("catalyst_text") or r.get("news_catalyst") or r.get("event_context"))
        earnings_flag = bool(r.get("earnings_proximity") or r.get("earnings_nearby") or r.get("earnings_catalyst") or r.get("days_to_earnings"))
        sector_strength = _score01(r.get("sector_context_score"), _score01(r.get("sector_strength_score"), 50.0))
        market_cap = _market_cap_bucket(r)
        high_vol = volatility >= 72.0 or abs(change_pct) >= 4.5
        unusual_volume = rel_volume_score >= 70.0 or rvol >= 2.0
        momentum_runner = momentum_expansion >= 70.0 and (change_pct >= 2.0 or rel_volume_score >= 72.0)
        breakout_candidate = breakout >= 68.0 and entry_quality >= 52.0
        sector_strength_flag = sector_strength >= 66.0
        catalyst_flag = bool(catalyst_text) or earnings_flag
        reasons: list[str] = []
        if high_vol:
            reasons.append("volatility_expansion")
        if unusual_volume:
            reasons.append("unusual_volume")
        if momentum_runner:
            reasons.append("momentum_runner")
        if breakout_candidate:
            reasons.append("breakout_candidate")
        if catalyst_flag:
            reasons.append("catalyst_or_earnings_context")
        if sector_strength_flag:
            reasons.append("sector_strength")
        if expected_return >= 4.0:
            reasons.append("asymmetric_expected_return")
        if change_pct >= 4.0 and liquidity >= 80.0:
            reasons.append("liquid_large_move_momentum")
        if not reasons:
            reasons.append("standard_quality_candidate")
        opportunity_type = "trend_continuation"
        if catalyst_flag:
            opportunity_type = "earnings_catalyst" if earnings_flag else "catalyst_momentum"
        if unusual_volume and momentum_runner:
            opportunity_type = "unusual_volume_momentum"
        if breakout_candidate:
            opportunity_type = "breakout_candidate"
        if high_vol and momentum_runner and market_cap in {"mid_cap", "small_cap", "micro_cap", "unknown"}:
            opportunity_type = "momentum_runner"
        if change_pct >= 4.0 and liquidity >= 80.0:
            opportunity_type = "liquid_momentum_runner"
        best_horizon = _safe_text(r.get("best_profit_horizon") or r.get("best_horizon_style") or r.get("trade_horizon_style"), "day_trade").lower()
        if best_horizon not in {"scalp", "day_trade", "swing_trade"}:
            if liquidity >= 70.0 and rel_volume_score >= 72.0 and intraday_accel >= 70.0:
                best_horizon = "scalp"
            elif trend >= 68.0 and sector_strength >= 60.0:
                best_horizon = "swing_trade"
            else:
                best_horizon = "day_trade"
        scalp_alignment = _clamp((liquidity * 0.30) + (execution * 0.25) + (rel_volume_score * 0.20) + (intraday_accel * 0.25))
        day_alignment = _clamp((momentum_expansion * 0.30) + (entry_quality * 0.25) + (confidence * 0.20) + (breakout * 0.25))
        swing_alignment = _clamp((trend * 0.34) + (confidence * 0.24) + (sector_strength * 0.18) + (reward_score * 0.24))
        horizon_alignment = {"scalp": scalp_alignment, "day_trade": day_alignment, "swing_trade": swing_alignment}
        inferred_horizon = max(horizon_alignment, key=horizon_alignment.get)
        if best_horizon == "day_trade" and horizon_alignment[inferred_horizon] >= day_alignment + 6.0:
            best_horizon = inferred_horizon
        liquidity_ok = liquidity >= 45.0 and execution >= 45.0
        risk_ok = _score01(r.get("portfolio_risk_score"), 58.0) >= 42.0 and _score01(r.get("drawdown_risk_score"), 35.0) <= 76.0
        confidence_ok = confidence >= 48.0 or (entry_quality >= 62.0 and momentum_expansion >= 68.0)
        high_upside = bool(
            liquidity_ok
            and risk_ok
            and confidence_ok
            and (
                expected_return >= 4.0
                or asymmetric_reward >= 70.0
                or (change_pct >= 4.0 and liquidity >= 80.0 and momentum_expansion >= 55.0)
                or (momentum_runner and breakout >= 66.0 and market_cap in {"mid_cap", "small_cap", "micro_cap", "unknown"})
            )
        )
        multiplier = 1.0
        survival_reason = "neutral_no_shadow_survival_boost"
        if high_upside:
            multiplier = _clamp(1.0 + (asymmetric_reward - 65.0) / 250.0, 1.0, 1.12)
            survival_reason = "high_upside_candidate_with_minimum_liquidity_risk_controls"
        elif not liquidity_ok:
            multiplier = 0.94
            survival_reason = "liquidity_or_execution_floor_not_met"
        elif not risk_ok:
            multiplier = 0.96
            survival_reason = "portfolio_or_drawdown_risk_penalty"
        elif expected_return >= 3.0 and confidence_ok:
            multiplier = 1.02
            survival_reason = "moderate_asymmetric_return_watch_candidate"
        return {
            "change_pct": change_pct,
            "expected_return": expected_return,
            "relative_volume_ratio": rvol,
            "relative_volume_score": rel_volume_score,
            "confidence": confidence,
            "entry_quality": entry_quality,
            "execution": execution,
            "liquidity": liquidity,
            "volatility_expansion_score": volatility,
            "momentum_expansion_score": momentum_expansion,
            "breakout_probability_score": breakout,
            "intraday_acceleration_score": intraday_accel,
            "trend_continuation_score": trend,
            "asymmetric_reward_score": asymmetric_reward,
            "candidate_universe_tier": market_cap,
            "candidate_opportunity_type": opportunity_type,
            "candidate_discovery_reason": ", ".join(reasons),
            "high_volatility": high_vol,
            "momentum_runner": momentum_runner,
            "earnings_catalyst": catalyst_flag,
            "sector_strength": sector_strength_flag,
            "breakout_candidate": breakout_candidate,
            "unusual_volume": unusual_volume,
            "trend_continuation": trend >= 64.0,
            "high_upside_candidate": high_upside,
            "expected_return_survival_multiplier": round(multiplier, 3),
            "survival_boost_reason": survival_reason,
            "best_discovery_horizon": best_horizon,
            "horizon_discovery_alignment": _clamp(horizon_alignment.get(best_horizon, day_alignment)),
            "discovery_horizon_summary": f"{best_horizon.replace('_', ' ')} fit from liquidity, momentum, breakout, trend, and context evidence.",
        }

    def score_row(self, row: dict[str, Any], peer_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        f = self._features(row)
        peer_summary = dict(peer_summary or {})
        cap_counts: Counter[str] = Counter(peer_summary.get("market_cap_counts") or {})
        total = int(peer_summary.get("total") or sum(cap_counts.values()) or 0)
        mega_share = (cap_counts.get("mega_cap", 0) / total) if total > 0 else 0.0
        mid_small_share = (cap_counts.get("mid_cap", 0) + cap_counts.get("small_cap", 0) + cap_counts.get("micro_cap", 0)) / total if total > 0 else 0.0
        cap = str(f["candidate_universe_tier"])
        diversity_score = _clamp(62.0 - max(0.0, mega_share - 0.50) * 42.0 + min(18.0, mid_small_share * 28.0))
        if cap in {"mid_cap", "small_cap", "micro_cap"}:
            diversity_score = _clamp(diversity_score + 8.0)
        mega_concentration = _clamp(mega_share * 100.0)
        mid_small_opportunity = _clamp((_to_float(f["momentum_expansion_score"]) * 0.34) + (_to_float(f["asymmetric_reward_score"]) * 0.38) + (diversity_score * 0.28))
        learning = self._learning_scores()
        opportunity_type = str(f["candidate_opportunity_type"])
        momentum_signature = "momentum_expansion" if _to_float(f["momentum_expansion_score"]) >= 68.0 else "standard_momentum"
        type_learning = _score01((learning.get("opportunity_type") or {}).get(opportunity_type), 50.0)
        cap_learning = _score01((learning.get("market_cap") or {}).get(cap), 50.0)
        momentum_learning = _score01((learning.get("momentum_signature") or {}).get(momentum_signature), 50.0)
        penalties: list[str] = []
        if _to_float(f["liquidity"]) < 45.0:
            penalties.append("liquidity_floor_not_met")
        if _to_float(f["confidence"]) < 45.0:
            penalties.append("confidence_floor_watch_only")
        if _to_float(f["execution"]) < 45.0:
            penalties.append("execution_readiness_floor_not_met")
        if cap == "mega_cap" and mega_share >= 0.75:
            penalties.append("mega_cap_concentration_watch")
        recommendation = "continue_shadow_observation"
        if bool(f["high_upside_candidate"]):
            recommendation = "shadow_expand_high_upside_paper_observation"
        elif penalties:
            recommendation = "observe_but_do_not_expand_until_risk_quality_improves"
        summary = (
            f"{str(f['candidate_opportunity_type']).replace('_', ' ')} in {cap.replace('_', ' ')} tier; "
            f"momentum {float(f['momentum_expansion_score']):.1f}, asymmetric reward {float(f['asymmetric_reward_score']):.1f}, "
            f"horizon {str(f['best_discovery_horizon']).replace('_', ' ')}."
        )
        return {
            **f,
            "discovery_diversity_score": round(diversity_score, 2),
            "market_cap_distribution_summary": peer_summary.get("market_cap_distribution_summary") or _distribution_summary(cap_counts, total),
            "mega_cap_concentration_score": round(mega_concentration, 2),
            "mid_small_opportunity_score": round(mid_small_opportunity, 2),
            "opportunity_type_learning_score": round(type_learning, 2),
            "market_cap_learning_score": round(cap_learning, 2),
            "momentum_signature_learning_score": round(momentum_learning, 2),
            "adaptive_discovery_shadow_recommendation": recommendation,
            "contextual_discovery_penalties": penalties,
            "opportunity_discovery_summary": summary,
            "opportunity_discovery_expansion_v1": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
        }

    def _peer_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        cap_counts = Counter(_market_cap_bucket(r) for r in rows if isinstance(r, dict))
        total = len(rows)
        return {
            "total": total,
            "market_cap_counts": dict(cap_counts),
            "market_cap_distribution_summary": _distribution_summary(cap_counts, total),
        }

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        rows = _candidate_rows(out)
        local_rows = self._local_discovery_rows()
        peer_summary = self._peer_summary(rows + local_rows)
        symbol_scores: dict[str, dict[str, Any]] = {}
        for row in rows[:250]:
            symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
            if not symbol:
                continue
            try:
                symbol_scores[symbol] = self.score_row(row, peer_summary=peer_summary)
            except Exception:
                continue
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            pack_out = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = pack_out.get(section)
                if not isinstance(values, list):
                    continue
                enriched = []
                for row in values:
                    if not isinstance(row, dict):
                        enriched.append(row)
                        continue
                    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
                    score = symbol_scores.get(symbol)
                    enriched.append({**row, **score} if isinstance(score, dict) else dict(row))
                pack_out[section] = enriched
            out[pack_key] = pack_out
        out["opportunity_discovery_expansion_v1"] = True
        out["opportunity_discovery_expansion_summary"] = self.status(rows=rows)
        if _to_float(out.get("high_predicted_profit_candidate_count"), 0.0) <= 0.0:
            out["high_predicted_profit_candidate_count"] = int(out["opportunity_discovery_expansion_summary"].get("high_upside_candidate_count", 0))
        return out

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        existing_symbols = {_safe_text(r.get("symbol") or r.get("ticker")).upper() for r in rows if isinstance(r, dict)}
        for local_row in self._local_discovery_rows():
            symbol = _safe_text(local_row.get("symbol") or local_row.get("ticker")).upper()
            if symbol and symbol not in existing_symbols:
                rows.append(local_row)
                existing_symbols.add(symbol)
        peer_summary = self._peer_summary(rows)
        scored = []
        for row in rows[:250]:
            try:
                scored.append(self.score_row(row, peer_summary=peer_summary))
            except Exception:
                continue
        total = len(scored)
        cap_counts = Counter(str(r.get("candidate_universe_tier") or "unknown") for r in scored)
        type_counts = Counter(str(r.get("candidate_opportunity_type") or "unknown") for r in scored)
        high_upside = [r for r in scored if bool(r.get("high_upside_candidate"))]
        high_predicted_profit = [
            r for r in scored
            if bool(r.get("high_upside_candidate"))
            or str(r.get("candidate_opportunity_type") or "") == "liquid_momentum_runner"
            or _to_float(r.get("asymmetric_reward_score"), 0.0) >= 62.0
        ]
        multipliers = [_to_float(r.get("expected_return_survival_multiplier"), 1.0) for r in scored]
        momentum_count = sum(
            1 for r in scored
            if bool(r.get("momentum_runner"))
            or str(r.get("candidate_opportunity_type") or "") == "liquid_momentum_runner"
            or _to_float(r.get("momentum_expansion_score"), 0.0) >= 68.0
        )
        breakout_count = sum(1 for r in scored if bool(r.get("breakout_candidate")))
        unusual_volume_count = sum(1 for r in scored if bool(r.get("unusual_volume")))
        avg_diversity = mean([_to_float(r.get("discovery_diversity_score"), 0.0) for r in scored]) if scored else 0.0
        avg_momentum = mean([_to_float(r.get("momentum_expansion_score"), 0.0) for r in scored]) if scored else 0.0
        mega_share = (cap_counts.get("mega_cap", 0) / total) if total > 0 else 0.0
        non_mega_count = total - cap_counts.get("mega_cap", 0)
        survival_stats = {
            "average_multiplier": round(mean(multipliers), 3) if multipliers else 1.0,
            "boosted_candidates": int(sum(1 for value in multipliers if value > 1.0)),
            "penalized_candidates": int(sum(1 for value in multipliers if value < 1.0)),
            "high_upside_survivors": int(len(high_upside)),
        }
        summary = (
            f"Evaluated {total} candidates; {len(high_predicted_profit)} high-predicted-profit shadow candidates, "
            f"{momentum_count} momentum candidates, {breakout_count} breakout candidates. "
            f"Market-cap mix: {_distribution_summary(cap_counts, total)}"
        ) if total else "No candidate rows available for opportunity discovery expansion."
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_discovery_only",
            "local_only": True,
            "writes_files": False,
            "opportunity_discovery_expansion_status_v1": True,
            "opportunity_discovery_expansion_v1": True,
            "candidates_evaluated": int(total),
            "market_cap_distribution": dict(cap_counts),
            "market_cap_distribution_summary": _distribution_summary(cap_counts, total),
            "average_discovery_diversity_score": round(avg_diversity, 2),
            "average_momentum_expansion_score": round(avg_momentum, 2),
            "mega_cap_concentration_score": round(mega_share * 100.0, 2),
            "non_mega_candidate_count": int(non_mega_count),
            "momentum_opportunity_count": int(momentum_count),
            "breakout_candidate_count": int(breakout_count),
            "unusual_volume_count": int(unusual_volume_count),
            "top_opportunity_types": [{"type": k, "count": v} for k, v in type_counts.most_common(6)],
            "high_upside_candidate_count": int(len(high_upside)),
            "high_predicted_profit_candidate_count": int(len(high_predicted_profit)),
            "opportunity_survival_statistics": survival_stats,
            "large_cap_bias_detected": bool(total >= 3 and mega_share >= 0.75 and len(high_upside) <= 1),
            "discovery_diversity_score": round(avg_diversity, 2),
            "adaptive_discovery_shadow_recommendation": "expand_mid_small_momentum_observation_shadow" if total and mega_share >= 0.75 else "continue_balanced_shadow_discovery",
            "opportunity_discovery_summary": summary,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "generated_at": _now_iso(),
        }
