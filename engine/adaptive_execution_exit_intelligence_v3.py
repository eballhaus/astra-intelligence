from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

VERSION = "3.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800
CACHE_TTL_SECONDS = 8.0


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


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"), 0.0)
    if "scalp" in raw or minutes < 30:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or minutes >= 1440:
        return "swing"
    if "day" in raw or minutes < 390:
        return "day_trade"
    return "short_swing"


def _archetype(row: dict[str, Any]) -> str:
    return _text(row.get("trade_archetype") or row.get("archetype") or row.get("setup_type"), "unknown")


def _regime(row: dict[str, Any]) -> str:
    return _text(row.get("market_regime") or row.get("regime") or row.get("session_type"), "unknown")


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("current_or_exit_profit_pct"),
        _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct")))),
    )


def _profit_factor(returns: list[float]) -> float | None:
    gains = sum(v for v in returns if v > 0)
    losses = abs(sum(v for v in returns if v < 0))
    if not returns:
        return None
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _group_average(rows: list[dict[str, Any]], group_key: str, value_key: str, limit: int = 10) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        group = _text(row.get(group_key), "unknown")
        if group == "unknown":
            continue
        if row.get(value_key) not in (None, ""):
            grouped[group].append(_to_float(row.get(value_key)))
    out = {k: round(mean(v), 4) for k, v in grouped.items() if v}
    return dict(sorted(out.items(), key=lambda item: item[1], reverse=True)[:limit])


def _best_context(rows: list[dict[str, Any]], key: str, metric: str, *, reverse: bool = True) -> str:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        ctx = _text(row.get(key), "unknown")
        if ctx == "unknown" or row.get(metric) in (None, ""):
            continue
        grouped[ctx].append(_to_float(row.get(metric)))
    if not grouped:
        return "insufficient_data"
    return sorted(grouped.items(), key=lambda item: mean(item[1]), reverse=reverse)[0][0]


def _profit_status(peak: float, current: float, giveback: float, capture_ratio: float, closed: bool, hold_minutes: float) -> str:
    if peak <= 0.05:
        return "insufficient_evidence"
    if capture_ratio >= 0.75 and giveback <= max(0.35, peak * 0.25):
        return "healthy_capture"
    if not closed and giveback <= max(0.6, peak * 0.35):
        return "normal_pullback"
    if capture_ratio < 0.25 and peak >= 1.0:
        return "severe_giveback"
    if giveback >= max(1.0, peak * 0.45):
        return "giveback_warning"
    if closed and capture_ratio < 0.35 and hold_minutes > 180:
        return "held_too_long_possible"
    if closed and peak > current and capture_ratio > 0.75 and hold_minutes < 30:
        return "exited_too_early_possible"
    return "normal_pullback"


def _recommendation(row: dict[str, Any]) -> tuple[str, str, float]:
    capture = _to_float(row.get("capture_ratio"))
    giveback = _to_float(row.get("giveback_pct"))
    peak = _to_float(row.get("peak_gain_pct"))
    continuation = _to_float(row.get("continuation_quality"), 50.0)
    status = _text(row.get("profit_protection_status"), "insufficient_evidence")
    if status == "severe_giveback" or (peak >= 1.0 and capture < 0.30):
        return "protect_profit_earlier", "Meaningful peak profit was retained poorly; review profit protection timing in this context.", 72.0
    if status == "giveback_warning":
        return "partial_profit_protection_candidate", "Giveback crossed the warning band after favorable excursion.", 64.0
    if continuation >= 70 and capture < 0.55:
        return "strong_continuation_increase_future_hold_confidence", "Continuation quality was strong but retained profit was modest.", 58.0
    if continuation < 45 and peak >= 0.75:
        return "weak_continuation_reduce_future_confidence", "Trade produced profit but follow-through weakened after entry.", 56.0
    if status == "normal_pullback":
        return "normal_volatility_do_not_overreact", "Giveback is within the current normal pullback band.", 52.0
    if status == "healthy_capture":
        return "hold_longer_supported", "Capture quality is healthy and continuation did not require early protection.", 54.0
    return "insufficient_evidence", "Not enough profit/hold/continuation evidence for a context-specific exit recommendation.", 35.0


class AdaptiveExecutionExitIntelligenceV3:
    """Shadow-only profit capture, horizon profitability, and exit learning diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "adaptive_execution_exit_intelligence_v3.jsonl")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.v1_path, self.v2_path, self.profit_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                symbol = _text(row.get("symbol")).upper()
                key = lifecycle_id or f"{symbol}:{_text(row.get('entry_timestamp') or row.get('timestamp'))[:16]}"
                if not key or key == ":":
                    continue
                merged = dict(latest.get(key) or {})
                merged.update(row)
                latest[key] = merged
        return list(latest.values())

    def _derive_trade(self, row: dict[str, Any]) -> dict[str, Any] | None:
        symbol = _text(row.get("symbol")).upper()
        lifecycle_id = _text(row.get("lifecycle_id"), symbol)
        if not symbol:
            return None
        entry = _to_float(row.get("entry_price"))
        current_price = _to_float(row.get("current_price") or row.get("last_price_seen"))
        peak_price = _to_float(row.get("best_price_seen"))
        closed = bool(row.get("closed") or row.get("exit_timestamp") or row.get("exit_price"))
        current_gain = _return_pct(row)
        peak_gain = max(0.0, _to_float(row.get("peak_unrealized_profit_pct"), _to_float(row.get("max_favorable_excursion_pct"))))
        giveback = max(0.0, _to_float(row.get("profit_giveback_pct"), peak_gain - current_gain))
        capture_ratio = _to_float(row.get("profit_capture_ratio"), max(0.0, current_gain) / peak_gain if peak_gain > 0 else 0.0)
        capture_ratio = max(0.0, min(1.0, capture_ratio))
        hold = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
        continuation = _to_float(row.get("follow_through_quality_score"), _to_float(row.get("continuation_strength_score"), _to_float(row.get("follow_through_score"), 50.0)))
        exit_quality = _to_float(row.get("exit_quality_score"), _to_float(row.get("exit_efficiency_score"), 50.0))
        status = _profit_status(peak_gain, current_gain, giveback, capture_ratio, closed, hold)
        horizon = _horizon(row)
        archetype = _archetype(row)
        regime = _regime(row)
        rec, reason, confidence = _recommendation({
            "capture_ratio": capture_ratio,
            "giveback_pct": giveback,
            "peak_gain_pct": peak_gain,
            "continuation_quality": continuation,
            "profit_protection_status": status,
        })
        time_to_peak = _to_float(row.get("time_from_entry_to_peak_minutes"), _to_float(row.get("time_to_mfe_seconds")) / 60.0)
        time_after_peak = max(0.0, hold - time_to_peak) if time_to_peak > 0 else 0.0
        peak_decay = giveback / max(time_after_peak, hold, 1.0)
        return {
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "horizon_label": horizon,
            "archetype_label": archetype,
            "regime_label": regime,
            "trade_type": _text(row.get("trade_type") or row.get("allocation_lane"), "paper_equity"),
            "volatility_context": _text(row.get("volatility_regime") or row.get("volatility_profile"), "unknown"),
            "confidence_bucket": _text(row.get("confidence_bucket") or row.get("confidence_label"), "unknown"),
            "entry_price": _round(entry),
            "current_price": _round(current_price),
            "peak_price_after_entry": _round(peak_price),
            "maximum_favorable_excursion_pct": _round(peak_gain),
            "maximum_adverse_excursion_pct": _round(row.get("max_adverse_excursion_pct")),
            "current_or_exit_gain_pct": _round(current_gain),
            "current_gain_pct": _round(current_gain if not closed else 0.0),
            "exit_gain_pct": _round(current_gain if closed else 0.0),
            "peak_gain_pct": _round(peak_gain),
            "giveback_pct": _round(giveback),
            "capture_ratio": _round(capture_ratio, 4),
            "capture_pct": _round(capture_ratio * 100.0, 2),
            "hold_time_minutes": _round(hold, 2),
            "continuation_quality": _round(continuation, 2),
            "exit_quality": _round(exit_quality, 2),
            "profit_retention_quality": _round(capture_ratio * 100.0, 2),
            "profit_protection_status": status,
            "closed": closed,
            "time_to_peak_minutes": _round(time_to_peak, 2),
            "time_from_peak_to_exit_minutes": _round(time_after_peak, 2),
            "peak_decay_rate": _round(peak_decay, 6),
            "shadow_exit_recommendation": rec,
            "shadow_exit_reason": reason,
            "shadow_exit_confidence": _round(confidence, 2),
            "behavior_safe_to_apply": False,
            "generated_at": _now_iso(),
        }

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 45.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-120:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def _horizon_stats(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_text(row.get("horizon_label"), "unknown")].append(row)
        out: dict[str, dict[str, Any]] = {}
        for horizon, items in grouped.items():
            returns = _values(items, "current_or_exit_gain_pct")
            wins = [v for v in returns if v > 0]
            out[horizon] = {
                "trade_count": len(items),
                "win_rate": round(len(wins) / len(returns) * 100.0, 4) if returns else None,
                "profit_factor": _profit_factor(returns),
                "avg_return": _avg(returns),
                "median_return": _median(returns),
                "avg_hold_time": _avg(_values(items, "hold_time_minutes")),
                "avg_peak_gain": _avg(_values(items, "peak_gain_pct")),
                "avg_giveback": _avg(_values(items, "giveback_pct")),
                "capture_ratio": _avg(_values(items, "capture_ratio")),
                "expectancy": _avg(returns),
                "drawdown_pressure": abs(_avg([v for v in returns if v < 0]) or 0.0),
                "best_archetype": _best_context(items, "archetype_label", "current_or_exit_gain_pct", reverse=True),
                "worst_archetype": _best_context(items, "archetype_label", "current_or_exit_gain_pct", reverse=False),
                "best_regime": _best_context(items, "regime_label", "current_or_exit_gain_pct", reverse=True),
                "worst_regime": _best_context(items, "regime_label", "current_or_exit_gain_pct", reverse=False),
                "confidence_quality": _avg(_values(items, "shadow_exit_confidence")),
            }
        return out

    def _recommendation_summary(self, rows: list[dict[str, Any]], horizon_stats: dict[str, dict[str, Any]]) -> tuple[str, str, str, str]:
        if not rows:
            return "insufficient_data", "insufficient_data", "insufficient_data", "Collect more lifecycle evidence."
        most_profitable = max(horizon_stats.items(), key=lambda item: _to_float(item[1].get("avg_return"), -999.0), default=("insufficient_data", {}))[0]
        safest = min(horizon_stats.items(), key=lambda item: _to_float(item[1].get("drawdown_pressure"), 999.0), default=("insufficient_data", {}))[0]
        giveback = max(horizon_stats.items(), key=lambda item: _to_float(item[1].get("avg_giveback"), -999.0), default=("insufficient_data", {}))[0]
        rec_counts = Counter(_text(row.get("shadow_exit_recommendation"), "insufficient_evidence") for row in rows)
        top_rec = rec_counts.most_common(1)[0][0] if rec_counts else "insufficient_data"
        text = f"Shadow-only: emphasize study of {most_profitable} profitability, {safest} survivability, and {giveback} giveback before any future human-reviewed policy changes."
        if top_rec == "protect_profit_earlier":
            text = "Shadow-only: profit protection timing deserves review in high-giveback contexts; no automatic exits enabled."
        return most_profitable, safest, giveback, text

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        rows = [row for row in (self._derive_trade(raw) for raw in self._latest_rows()) if row]
        self._write_rows(rows)
        closed = [row for row in rows if bool(row.get("closed"))]
        open_rows = [row for row in rows if not bool(row.get("closed"))]
        peak_vals = _values(rows, "peak_gain_pct")
        current_vals = _values(open_rows, "current_or_exit_gain_pct")
        exit_vals = _values(closed, "current_or_exit_gain_pct")
        giveback_vals = _values(rows, "giveback_pct")
        capture_vals = _values(rows, "capture_ratio")
        horizon_stats = self._horizon_stats(rows)
        most_profitable, safest, highest_giveback_horizon, horizon_rec = self._recommendation_summary(rows, horizon_stats)
        highest_frequency = max(horizon_stats.items(), key=lambda item: _to_int(item[1].get("trade_count")), default=("insufficient_data", {}))[0]
        risk_adjusted = max(horizon_stats.items(), key=lambda item: _to_float(item[1].get("avg_return"), -999.0) - _to_float(item[1].get("drawdown_pressure"), 0.0), default=("insufficient_data", {}))[0]
        continued_after_profit = sum(1 for row in rows if _to_float(row.get("peak_gain_pct")) > 0.25 and _to_float(row.get("current_or_exit_gain_pct")) > 0 and _to_float(row.get("capture_ratio")) >= 0.55)
        faded_after_profit = sum(1 for row in rows if _to_float(row.get("peak_gain_pct")) > 0.25 and _to_float(row.get("giveback_pct")) > max(0.35, _to_float(row.get("peak_gain_pct")) * 0.35))
        reversed_after_profit = sum(1 for row in rows if _to_float(row.get("peak_gain_pct")) > 0.25 and _to_float(row.get("current_or_exit_gain_pct")) < 0)
        continuation_probability = round(continued_after_profit / max(1, continued_after_profit + faded_after_profit + reversed_after_profit) * 100.0, 4) if rows else None
        protect_profit_score = _clamp((_avg(giveback_vals) or 0.0) * 3.0 + (100.0 - ((_avg(capture_vals) or 0.0) * 100.0)) * 0.55)
        hold_longer_score = _clamp((continuation_probability or 0.0) * 0.55 + (_avg(_values(rows, "continuation_quality")) or 0.0) * 0.35)
        shadow_bias = "protect_profit" if protect_profit_score >= hold_longer_score + 8 else ("hold_longer" if hold_longer_score >= protect_profit_score + 8 else "balanced_review")
        recommendations = []
        for row in sorted(rows, key=lambda r: _to_float(r.get("shadow_exit_confidence")), reverse=True)[:20]:
            recommendations.append({
                "symbol": row.get("symbol"),
                "recommendation": row.get("shadow_exit_recommendation"),
                "reason": row.get("shadow_exit_reason"),
                "evidence_count": len(rows),
                "confidence": row.get("shadow_exit_confidence"),
                "horizon": row.get("horizon_label"),
                "archetype": row.get("archetype_label"),
                "regime": row.get("regime_label"),
                "behavior_safe_to_apply": False,
            })
        best_capture = sorted(rows, key=lambda r: _to_float(r.get("capture_ratio")), reverse=True)[:8]
        worst_giveback = sorted(rows, key=lambda r: _to_float(r.get("giveback_pct")), reverse=True)[:8]
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_exit_learning",
            "tracked_trades": len(rows),
            "closed_trades_reviewed": len(closed),
            "open_trades_reviewed": len(open_rows),
            "profit_capture_score": _round((_avg(capture_vals) or 0.0) * 100.0, 2) if capture_vals else None,
            "avg_peak_gain": _avg(peak_vals),
            "avg_exit_gain": _avg(exit_vals),
            "avg_current_gain": _avg(current_vals),
            "avg_giveback": _avg(giveback_vals),
            "median_giveback": _median(giveback_vals),
            "avg_capture_ratio": _avg(capture_vals),
            "capture_ratio": _avg(capture_vals),
            "capture_ratio_by_horizon": _group_average(rows, "horizon_label", "capture_ratio"),
            "capture_ratio_by_archetype": _group_average(rows, "archetype_label", "capture_ratio"),
            "capture_ratio_by_regime": _group_average(rows, "regime_label", "capture_ratio"),
            "worst_giveback_symbols": [_text(row.get("symbol"), "unknown") for row in worst_giveback],
            "best_capture_symbols": [_text(row.get("symbol"), "unknown") for row in best_capture],
            "open_vs_closed_capture": {
                "open": _avg(_values(open_rows, "capture_ratio")),
                "closed": _avg(_values(closed, "capture_ratio")),
            },
            "profit_protection_trades": rows[-80:],
            "strongest_exit_context": _best_context(rows, "archetype_label", "exit_quality", reverse=True),
            "weakest_exit_context": _best_context(rows, "archetype_label", "exit_quality", reverse=False),
            "biggest_giveback_context": _best_context(rows, "archetype_label", "giveback_pct", reverse=True),
            "best_profit_retention_context": _best_context(rows, "archetype_label", "capture_ratio", reverse=True),
            "protect_gains_sooner_context": _best_context([r for r in rows if _text(r.get("shadow_exit_recommendation")) in {"protect_profit_earlier", "partial_profit_protection_candidate"}], "archetype_label", "giveback_pct", reverse=True),
            "hold_longer_context": _best_context([r for r in rows if _text(r.get("shadow_exit_recommendation")) in {"hold_longer_supported", "strong_continuation_increase_future_hold_confidence"}], "archetype_label", "continuation_quality", reverse=True),
            "horizon_profitability": horizon_stats,
            "most_profitable_horizon": most_profitable,
            "safest_horizon": safest,
            "highest_frequency_horizon": highest_frequency,
            "highest_giveback_horizon": highest_giveback_horizon,
            "best_risk_adjusted_horizon": risk_adjusted,
            "horizon_allocation_recommendation": horizon_rec,
            "continued_after_profit_count": continued_after_profit,
            "faded_after_profit_count": faded_after_profit,
            "reversed_after_profit_count": reversed_after_profit,
            "average_time_to_peak": _avg(_values(rows, "time_to_peak_minutes")),
            "average_time_from_peak_to_exit": _avg(_values(rows, "time_from_peak_to_exit_minutes")),
            "peak_decay_rate": _avg(_values(rows, "peak_decay_rate")),
            "continuation_after_1h": _avg([_to_float(row.get("continuation_quality")) for row in rows if _to_float(row.get("hold_time_minutes")) >= 60.0]),
            "continuation_after_1d": _avg([_to_float(row.get("continuation_quality")) for row in rows if _to_float(row.get("hold_time_minutes")) >= 1440.0]),
            "continuation_after_3d": _avg([_to_float(row.get("continuation_quality")) for row in rows if _to_float(row.get("hold_time_minutes")) >= 4320.0]),
            "continuation_by_archetype": _group_average(rows, "archetype_label", "continuation_quality"),
            "continuation_by_horizon": _group_average(rows, "horizon_label", "continuation_quality"),
            "continuation_by_regime": _group_average(rows, "regime_label", "continuation_quality"),
            "continuation_probability": continuation_probability,
            "peak_decay_risk": _clamp((_avg(_values(rows, "peak_decay_rate")) or 0.0) * 100.0 + (100.0 - (continuation_probability or 0.0)) * 0.45),
            "hold_longer_score": _round(hold_longer_score, 2),
            "protect_profit_score": _round(protect_profit_score, 2),
            "shadow_exit_bias": shadow_bias,
            "shadow_exit_recommendations": recommendations,
            "shadow_only_recommendation": horizon_rec,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "behavior_safe_to_apply": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "automatic_profit_taking_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "summary": "Astra is finding profitable trades, but some winners are giving back profit before exit. V3 studies which contexts deserve patience versus earlier profit review. No trading behavior is changed.",
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
