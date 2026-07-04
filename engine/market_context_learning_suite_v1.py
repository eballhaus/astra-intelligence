from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

try:
    from engine.context_capture_utils_v1 import enrich_context_row
except Exception:  # pragma: no cover - context writes should remain best-effort
    def enrich_context_row(row, *, source_file):
        return row

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800
CACHE_TTL_SECONDS = 10.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
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


def _read_json(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _values(rows: list[dict[str, Any]], *keys: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        for key in keys:
            if row.get(key) not in (None, ""):
                out.append(_to_float(row.get(key)))
                break
    return out


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker")).upper()


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("current_or_exit_profit_pct"),
        _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct")))),
    )


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    hold = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes") or row.get("hold_time_minutes"))
    if "scalp" in raw or hold < 30:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or hold >= 1440:
        return "swing"
    if "day" in raw or hold < 390:
        return "day_trade"
    return "short_swing"


def _group_avg(rows: list[dict[str, Any]], group_key: str, value_key: str, limit: int = 12) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = _text(row.get(group_key), "unknown")
        if key == "unknown" or row.get(value_key) in (None, ""):
            continue
        grouped[key].append(_to_float(row.get(value_key)))
    out = {k: round(mean(v), 4) for k, v in grouped.items() if v}
    return dict(sorted(out.items(), key=lambda item: item[1], reverse=True)[:limit])


def _best_key(rows: list[dict[str, Any]], group_key: str, value_key: str, *, reverse: bool = True) -> str:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = _text(row.get(group_key), "unknown")
        if key == "unknown" or row.get(value_key) in (None, ""):
            continue
        grouped[key].append(_to_float(row.get(value_key)))
    if not grouped:
        return "insufficient_data"
    return sorted(grouped.items(), key=lambda item: mean(item[1]), reverse=reverse)[0][0]


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("rows", "top_buys", "stable_top_6", "promoted_candidates"):
        values = payload.get(key)
        if isinstance(values, list):
            rows.extend([dict(v) for v in values if isinstance(v, dict)])
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if isinstance(pack, dict):
            for section in ("final", "qualified", "watchlist", "fill"):
                values = pack.get(section)
                if isinstance(values, list):
                    rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = _symbol(row)
        if sym:
            merged = dict(dedup.get(sym) or {})
            merged.update(row)
            dedup[sym] = merged
    return list(dedup.values())


def _classify_catalyst(row: dict[str, Any]) -> tuple[str, float, float]:
    text = " ".join(
        _text(row.get(k)).lower()
        for k in (
            "catalyst_type", "catalyst", "news_catalyst", "event_context", "catalyst_context",
            "catalyst_context_label", "opportunity_type", "trade_archetype", "archetype", "summary",
        )
        if row.get(k) not in (None, "")
    )
    score = _to_float(row.get("catalyst_strength_score"), _to_float(row.get("catalyst_context_score"), 50.0))
    mapping = [
        ("earnings", ("earnings", "eps", "revenue")),
        ("guidance", ("guidance", "outlook", "forecast")),
        ("analyst_upgrade", ("upgrade", "raised target", "buy rating")),
        ("analyst_downgrade", ("downgrade", "lowered target", "sell rating")),
        ("FDA_or_regulatory", ("fda", "regulatory", "approval", "clinical", "trial")),
        ("contract_award", ("contract", "award", "deal", "partnership")),
        ("merger_acquisition", ("merger", "acquisition", "takeover", "buyout")),
        ("sector_sympathy", ("sector", "sympathy", "semiconductor", "ai theme", "theme")),
        ("retail_social_momentum", ("retail", "social", "meme", "reddit", "short squeeze")),
        ("macro_news", ("macro", "fed", "rates", "inflation", "jobs", "cpi")),
    ]
    for label, tokens in mapping:
        if any(token in text for token in tokens):
            return label, _clamp(score + 18.0), _clamp(58.0 + score * 0.35)
    if text:
        if "no_local_catalyst" in text or "no detected" in text:
            return "no_detected_catalyst", _clamp(score), 48.0
        return "unknown_catalyst", _clamp(score), 42.0
    return "no_detected_catalyst", 40.0, 35.0


def _classify_premarket(row: dict[str, Any]) -> tuple[str, float, float, float, str]:
    change = _to_float(row.get("premarket_price_change_pct"), _to_float(row.get("premarket_change_pct"), _to_float(row.get("change_percent"), _to_float(row.get("change_pct")))))
    gap = _to_float(row.get("premarket_gap_pct"), _to_float(row.get("gap_pct"), change))
    rvol = _to_float(row.get("relative_premarket_volume"), _to_float(row.get("relative_volume_ratio"), _to_float(row.get("relative_volume"))))
    momentum = _to_float(row.get("momentum_score"), _to_float(row.get("entry_timing_score"), _to_float(row.get("opportunity_score_pct"), 50.0)))
    sector = _to_float(row.get("sector_strength_score"), _to_float(row.get("sector_context_score"), 50.0))
    volatility = abs(change) + _to_float(row.get("premarket_volatility"), _to_float(row.get("volatility_score"), 0.0)) * 0.05
    if abs(change) < 0.35 and rvol < 1.1 and momentum < 55:
        profile = "weak_premarket" if change < 0 else "no_clear_signal"
    elif change >= 3.0 and rvol >= 1.5 and momentum >= 65:
        profile = "gap_and_go"
    elif change >= 1.25 and momentum >= 62:
        profile = "momentum_gapper"
    elif abs(gap) >= 4.0 and (momentum < 60 or sector < 50):
        profile = "gap_and_fade_risk"
    elif change >= 0.3 and rvol < 1.5 and sector >= 55:
        profile = "quiet_accumulation"
    elif change <= -1.0:
        profile = "weak_premarket"
    else:
        profile = "no_clear_signal"
    continuation = _clamp(45.0 + momentum * 0.30 + max(0.0, change) * 5.0 + max(0.0, rvol - 1.0) * 7.0 + (sector - 50.0) * 0.22)
    gap_risk = _clamp(abs(gap) * 9.0 + volatility * 2.2 + max(0.0, 55.0 - momentum) * 0.35)
    giveback = _clamp(gap_risk * 0.58 + max(0.0, 70.0 - continuation) * 0.42)
    if profile in {"gap_and_go", "momentum_gapper"} and continuation >= 68:
        likely = "day_trade"
    elif profile == "quiet_accumulation":
        likely = "short_swing"
    elif profile in {"gap_and_fade_risk", "weak_premarket"}:
        likely = "scalp"
    else:
        likely = "day_trade"
    return profile, _clamp(momentum), _round(gap_risk, 2), _round(giveback, 2), likely


def _classify_after_hours(row: dict[str, Any]) -> tuple[str, float, float, float, str]:
    ah_change = _to_float(row.get("after_hours_price_change_pct"), _to_float(row.get("after_hours_change_pct"), _to_float(row.get("overnight_return"))))
    ah_rvol = _to_float(row.get("after_hours_relative_volume"), _to_float(row.get("relative_volume_ratio"), _to_float(row.get("relative_volume"))))
    catalyst, catalyst_strength, _ = _classify_catalyst(row)
    continuation = _to_float(row.get("continuation_quality"), _to_float(row.get("follow_through_quality_score"), _to_float(row.get("continuation_strength_score"), 50.0)))
    if abs(ah_change) < 0.35 and ah_rvol < 1.2:
        profile = "quiet_after_hours"
    elif ah_change >= 2.0 and catalyst in {"earnings", "guidance", "analyst_upgrade", "contract_award"}:
        profile = "positive_catalyst_reaction"
    elif ah_change <= -2.0 and catalyst in {"earnings", "guidance", "analyst_downgrade", "FDA_or_regulatory"}:
        profile = "negative_catalyst_reaction"
    elif ah_change >= 1.0:
        profile = "overnight_momentum_build"
    elif ah_change <= -1.0:
        profile = "overnight_fade_risk"
    else:
        profile = "no_clear_after_hours_signal"
    momentum = _clamp(45.0 + max(0.0, ah_change) * 8.0 + max(0.0, ah_rvol - 1.0) * 8.0 + catalyst_strength * 0.20)
    fade = _clamp(abs(ah_change) * 7.5 + max(0.0, 55.0 - continuation) * 0.55 + (18.0 if profile in {"overnight_fade_risk", "negative_catalyst_reaction"} else 0.0))
    run = _clamp(momentum * 0.62 + continuation * 0.28 + max(0.0, ah_change) * 2.0)
    if run >= fade + 10:
        bias = "next_day_continuation_watch"
    elif fade >= run + 8:
        bias = "next_day_gap_and_fade_watch"
    else:
        bias = "balanced_next_day_watch"
    return profile, _round(momentum, 2), _round(run, 2), _round(fade, 2), bias


class MarketContextLearningSuiteV1:
    """Shadow-only premarket, catalyst, and after-hours context diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0
        self.state_path = os.path.join(self.state_dir, "market_context_learning_suite_v1.jsonl")

    def _top_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for name in (
            "top_buys_snapshot.json", "top_buys_cache.json", "top_buys_last_real_payload.json",
            "snapshots/stable_top_buys_v1.json", "broad_universe_intake_promotion_v1.json",
        ):
            payload = _read_json(os.path.join(self.state_dir, name))
            if payload:
                payloads.append(payload)
        return payloads

    def _source_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for payload in self._top_payloads():
            for row in _candidate_rows(payload):
                sym = _symbol(row)
                if not sym:
                    continue
                merged = dict(latest.get(sym) or {})
                merged.update(row)
                latest[sym] = merged
        for name in (
            "trade_lifecycle_excursion_v2.jsonl", "trade_lifecycle_excursion_v1.jsonl",
            "adaptive_profit_capture_intelligence_v1.jsonl", "adaptive_execution_exit_intelligence_v3.jsonl",
            "exit_learning_expansion_suite_v1.jsonl", "trade_archetype_regime_intelligence_v1.jsonl",
            "replay_counterfactual_learning_v2.jsonl", "opportunity_cost_learning_v1.jsonl",
            "candidate_decision_ledger_v1.jsonl", "execution_suppression_audit_v1.jsonl",
        ):
            for row in _tail_jsonl(os.path.join(self.state_dir, name), max_rows=420):
                sym = _symbol(row)
                if not sym:
                    continue
                merged = dict(latest.get(sym) or {})
                merged.update(row)
                latest[sym] = merged
        return list(latest.values())[-MAX_ROWS:]

    def _derive(self, row: dict[str, Any]) -> dict[str, Any] | None:
        sym = _symbol(row)
        if not sym:
            return None
        catalyst, catalyst_strength, catalyst_conf = _classify_catalyst(row)
        pre_profile, pre_momentum, gap_risk, pre_giveback, likely_horizon = _classify_premarket(row)
        ah_profile, overnight_momentum, gap_run, gap_fade, next_day_bias = _classify_after_hours(row)
        actual = _return_pct(row)
        giveback = _to_float(row.get("profit_giveback_pct"), _to_float(row.get("giveback_pct")))
        capture = _to_float(row.get("profit_capture_ratio"), _to_float(row.get("capture_ratio")))
        continuation = _to_float(row.get("continuation_quality"), _to_float(row.get("follow_through_quality_score"), _to_float(row.get("continuation_strength_score"), 50.0)))
        horizon = _horizon(row)
        context_conf = _clamp((catalyst_conf * 0.30) + (pre_momentum * 0.22) + (overnight_momentum * 0.18) + (continuation * 0.18) + 12.0)
        high_giveback_context = "premarket_gap_risk" if gap_risk >= max(gap_fade, pre_giveback) else "after_hours_gap_fade_risk"
        if catalyst in {"earnings", "guidance"} and ah_profile in {"positive_catalyst_reaction", "negative_catalyst_reaction"}:
            horizon_hint = "short_swing"
        elif likely_horizon == "scalp" or gap_fade >= 65:
            horizon_hint = "scalp"
        elif pre_profile in {"gap_and_go", "momentum_gapper"}:
            horizon_hint = "day_trade"
        else:
            horizon_hint = horizon if horizon != "unknown" else likely_horizon
        return {
            "symbol": sym,
            "premarket_price_change_pct": _round(_to_float(row.get("premarket_price_change_pct"), _to_float(row.get("change_percent"), _to_float(row.get("change_pct"))))),
            "premarket_gap_pct": _round(_to_float(row.get("premarket_gap_pct"), _to_float(row.get("gap_pct"), _to_float(row.get("change_percent"), _to_float(row.get("change_pct")))))),
            "premarket_volume": _to_float(row.get("premarket_volume"), _to_float(row.get("volume"))),
            "relative_premarket_volume": _round(_to_float(row.get("relative_premarket_volume"), _to_float(row.get("relative_volume_ratio"), _to_float(row.get("relative_volume"))))),
            "premarket_high": row.get("premarket_high") or row.get("high"),
            "premarket_low": row.get("premarket_low") or row.get("low"),
            "premarket_trend_direction": "up" if _to_float(row.get("change_percent"), _to_float(row.get("change_pct"))) > 0 else "down" if _to_float(row.get("change_percent"), _to_float(row.get("change_pct"))) < 0 else "flat",
            "premarket_volatility": _round(abs(_to_float(row.get("change_percent"), _to_float(row.get("change_pct"))))),
            "market_index_direction": _text(row.get("market_index_direction") or row.get("market_context_label"), "unknown"),
            "sector_strength": _round(_to_float(row.get("sector_strength_score"), _to_float(row.get("sector_context_score"), 50.0))),
            "prior_day_close_behavior": _text(row.get("prior_day_close_behavior") or row.get("pullback_vs_breakdown_label"), "unknown"),
            "premarket_profile": pre_profile,
            "likely_horizon": horizon_hint,
            "premarket_momentum_score": _round(pre_momentum, 2),
            "gap_risk_score": _round(gap_risk, 2),
            "premarket_continuation_probability": _round(_clamp(100.0 - pre_giveback + pre_momentum * 0.18), 2),
            "premarket_giveback_risk": _round(pre_giveback, 2),
            "catalyst_type": catalyst,
            "catalyst_confidence": _round(catalyst_conf, 2),
            "catalyst_strength_score": _round(catalyst_strength, 2),
            "after_hours_price_change_pct": _round(_to_float(row.get("after_hours_price_change_pct"), _to_float(row.get("after_hours_change_pct"), _to_float(row.get("overnight_return"))))),
            "after_hours_volume": _to_float(row.get("after_hours_volume"), 0.0),
            "after_hours_relative_volume": _round(_to_float(row.get("after_hours_relative_volume"), _to_float(row.get("relative_volume_ratio"), _to_float(row.get("relative_volume"))))),
            "after_hours_profile": ah_profile,
            "overnight_momentum_score": overnight_momentum,
            "gap_and_run_probability": gap_run,
            "gap_and_fade_probability": gap_fade,
            "next_day_bias": next_day_bias,
            "after_hours_context_confidence": _round(_clamp(35.0 + overnight_momentum * 0.35 + catalyst_conf * 0.25), 2),
            "context_confidence": _round(context_conf, 2),
            "current_or_exit_return_pct": _round(actual),
            "profit_giveback_pct": _round(giveback),
            "profit_capture_ratio": _round(capture, 4),
            "continuation_quality": _round(continuation, 2),
            "hold_duration_minutes": _round(_to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes") or row.get("hold_time_minutes")), 2),
            "horizon_style": horizon,
            "trade_archetype": _text(row.get("trade_archetype") or row.get("archetype"), "unknown"),
            "market_regime": _text(row.get("market_regime") or row.get("regime"), "unknown"),
            "highest_giveback_context": high_giveback_context,
            "source_endpoint": "market_context_learning_suite_v1",
            "behavior_safe_to_apply": False,
            "generated_at": _now_iso(),
        }

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 60.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-160:]:
                    enriched = enrich_context_row(row, source_file="market_context_learning_suite_v1.jsonl")
                    handle.write(json.dumps(enriched, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        rows = [r for r in (self._derive(raw) for raw in self._source_rows()) if r]
        self._write_rows(rows)
        pre_counts = Counter(_text(r.get("premarket_profile"), "insufficient_data") for r in rows)
        cat_counts = Counter(_text(r.get("catalyst_type"), "unknown_catalyst") for r in rows)
        ah_counts = Counter(_text(r.get("after_hours_profile"), "insufficient_data") for r in rows)
        strongest_pre = _best_key(rows, "premarket_profile", "current_or_exit_return_pct")
        weakest_pre = _best_key(rows, "premarket_profile", "current_or_exit_return_pct", reverse=False)
        strongest_cat = _best_key(rows, "catalyst_type", "current_or_exit_return_pct")
        weakest_cat = _best_key(rows, "catalyst_type", "current_or_exit_return_pct", reverse=False)
        strongest_ah = _best_key(rows, "after_hours_profile", "current_or_exit_return_pct")
        highest_gap_fade = _best_key(rows, "after_hours_profile", "gap_and_fade_probability")
        best_horizon = _best_key(rows, "likely_horizon", "current_or_exit_return_pct")
        highest_giveback_context = _best_key(rows, "highest_giveback_context", "profit_giveback_pct")
        avg_continuation = _avg(_values(rows, "premarket_continuation_probability"))
        avg_gap_fade = _avg(_values(rows, "gap_and_fade_probability"))
        avg_gap_risk = _avg(_values(rows, "gap_risk_score"))
        avg_conf = _avg(_values(rows, "context_confidence")) or 0.0
        if not rows:
            recommendation = "Shadow-only: collect premarket, catalyst, and after-hours evidence before making context conclusions."
        elif (avg_gap_fade or 0.0) >= 65.0 or (avg_gap_risk or 0.0) >= 65.0:
            recommendation = "Shadow-only: monitor gap-and-fade contexts for shorter horizon and profit-protection review; do not auto-apply."
        elif (avg_continuation or 0.0) >= 65.0:
            recommendation = "Shadow-only: current context evidence leans continuation-friendly; compare against actual hold-time and giveback outcomes."
        else:
            recommendation = "Shadow-only: context evidence is mixed; keep horizon and exit recommendations human-reviewed."
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_market_context_learning",
            "tracked_symbols": len({_text(r.get("symbol")) for r in rows if r.get("symbol")}),
            "tracked_trades": len(rows),
            "context_records": len(rows),
            "premarket_profile_distribution": dict(pre_counts.most_common(10)),
            "catalyst_type_distribution": dict(cat_counts.most_common(10)),
            "after_hours_profile_distribution": dict(ah_counts.most_common(10)),
            "strongest_premarket_profile": strongest_pre,
            "weakest_premarket_profile": weakest_pre,
            "dominant_catalyst_type": cat_counts.most_common(1)[0][0] if cat_counts else "insufficient_data",
            "strongest_catalyst_type": strongest_cat,
            "weakest_catalyst_type": weakest_cat,
            "strongest_after_hours_profile": strongest_ah,
            "highest_gap_fade_risk_profile": highest_gap_fade,
            "best_context_horizon": best_horizon,
            "highest_giveback_context": highest_giveback_context,
            "context_confidence": _round(avg_conf, 2),
            "premarket_momentum_score": _avg(_values(rows, "premarket_momentum_score")),
            "gap_risk_score": avg_gap_risk,
            "premarket_continuation_probability": avg_continuation,
            "premarket_giveback_risk": _avg(_values(rows, "premarket_giveback_risk")),
            "overnight_momentum_score": _avg(_values(rows, "overnight_momentum_score")),
            "gap_and_run_probability": _avg(_values(rows, "gap_and_run_probability")),
            "gap_and_fade_probability": avg_gap_fade,
            "historical_expectancy_by_catalyst": _group_avg(rows, "catalyst_type", "current_or_exit_return_pct"),
            "average_hold_duration_by_catalyst": _group_avg(rows, "catalyst_type", "hold_duration_minutes"),
            "giveback_risk_by_catalyst": _group_avg(rows, "catalyst_type", "profit_giveback_pct"),
            "best_horizon_by_catalyst": dict(Counter(f"{r.get('catalyst_type')}:{r.get('likely_horizon')}" for r in rows).most_common(12)),
            "profile_samples": rows[-20:],
            "shadow_context_recommendation": recommendation,
            "summary": "Astra is studying what happened before the market opened, after the market closed, and what catalyst may be driving each move. This is shadow-only and does not change trading behavior yet.",
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "thresholds_changed": False,
            "position_sizing_changed": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
