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


def _values(rows: list[dict[str, Any]], *keys: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        for key in keys:
            if row.get(key) not in (None, ""):
                out.append(_to_float(row.get(key)))
                break
    return out


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _return_pct(row: dict[str, Any]) -> float:
    return _to_float(row.get("current_or_exit_profit_pct"), _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct")))))


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    hold = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
    if "scalp" in raw or hold < 30:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or hold >= 1440:
        return "swing"
    if "day" in raw or hold < 390:
        return "day_trade"
    return "short_swing"


def _archetype(row: dict[str, Any]) -> str:
    return _text(row.get("trade_archetype") or row.get("archetype") or row.get("setup_type"), "unknown")


def _regime(row: dict[str, Any]) -> str:
    return _text(row.get("market_regime") or row.get("regime") or row.get("session_type"), "unknown")


def _time_window(row: dict[str, Any]) -> str:
    bucket = _text(row.get("session_timing") or row.get("day_learning_session_bucket") or row.get("session_type"), "unknown").lower()
    hold = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
    time_to_peak = _to_float(row.get("time_to_peak_minutes"), _to_float(row.get("time_from_entry_to_peak_minutes"), _to_float(row.get("time_to_mfe_seconds")) / 60.0))
    if "open" in bucket or hold <= 15:
        return "first_15_min"
    if time_to_peak and time_to_peak <= 15:
        return "first_15_min"
    if time_to_peak and time_to_peak <= 30:
        return "first_30_min"
    if time_to_peak and time_to_peak <= 60:
        return "first_60_min"
    if hold <= 30:
        return "first_30_min"
    if hold <= 60:
        return "first_60_min"
    if "lunch" in bucket or "midday" in bucket:
        return "lunch_period"
    if "close" in bucket or "power" in bucket:
        return "power_hour"
    if hold >= 1440:
        return "overnight"
    return "regular_session"


def _group_avg(rows: list[dict[str, Any]], group_key: str, value_key: str, limit: int = 10) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        key = _text(row.get(group_key), "unknown")
        if key == "unknown" or row.get(value_key) in (None, ""):
            continue
        grouped[key].append(_to_float(row.get(value_key)))
    out = {k: round(mean(v), 4) for k, v in grouped.items() if v}
    return dict(sorted(out.items(), key=lambda item: item[1], reverse=True)[:limit])


def _classify_personality(row: dict[str, Any]) -> tuple[str, float]:
    peak = _to_float(row.get("peak_gain_pct"))
    giveback = _to_float(row.get("giveback_pct"))
    ret = _to_float(row.get("current_or_exit_gain_pct"))
    hold = _to_float(row.get("hold_time_minutes"))
    capture = _to_float(row.get("capture_ratio"))
    cont = _to_float(row.get("continuation_quality"), 50.0)
    mae = _to_float(row.get("maximum_adverse_excursion_pct"))
    if peak <= 0.15 and hold < 10:
        return "insufficient_evidence", 30.0
    if peak >= 2.0 and capture < 0.35 and giveback >= 1.0:
        return "spike_and_fade", 78.0
    if ret > 0 and cont >= 70 and capture >= 0.55:
        return "runner", 72.0
    if hold >= 240 and ret > 0 and giveback < max(0.75, peak * 0.35):
        return "slow_grinder", 66.0
    if abs(mae) >= 1.0 and peak >= 0.75 and capture < 0.55:
        return "choppy_mover", 62.0
    if cont < 45 and peak > 0.4:
        return "failed_breakout_risk", 63.0
    if hold >= 1440 and ret >= 0:
        return "overnight_holder", 64.0
    if hold < 30 and giveback >= 0.5:
        return "scalp_only_candidate", 61.0
    return "insufficient_evidence", 40.0


def _partial_exit_variants(peak: float, actual: float, giveback: float) -> dict[str, float]:
    first_threshold = min(max(peak * 0.45, 0.5), peak) if peak > 0 else 0.0
    protected_remaining = max(actual, peak - max(0.35, peak * 0.35))
    severe_exit = max(actual, peak - max(0.5, peak * 0.55))
    return {
        "hold_full_position": actual,
        "sell_25_at_first_profit_threshold": first_threshold * 0.25 + actual * 0.75,
        "sell_50_at_first_profit_threshold": first_threshold * 0.50 + actual * 0.50,
        "sell_75_at_first_profit_threshold": first_threshold * 0.75 + actual * 0.25,
        "protect_remaining_after_peak_decay": protected_remaining,
        "exit_full_after_severe_giveback": severe_exit,
    }


class ExitLearningExpansionSuiteV1:
    """Shadow-only expansion for partial exits, time windows, personality, hold time, and profit decay."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.v3_path = os.path.join(self.state_dir, "adaptive_execution_exit_intelligence_v3.jsonl")
        self.state_path = os.path.join(self.state_dir, "exit_learning_expansion_suite_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.v1_path, self.v2_path, self.profit_path, self.v3_path):
            for row in _tail_jsonl(path):
                symbol = _text(row.get("symbol")).upper()
                lifecycle_id = _text(row.get("lifecycle_id"))
                key = lifecycle_id or f"{symbol}:{_text(row.get('entry_timestamp') or row.get('timestamp'))[:16]}"
                if not key or key == ":":
                    continue
                merged = dict(latest.get(key) or {})
                merged.update(row)
                latest[key] = merged
        return list(latest.values())

    def _derive(self, row: dict[str, Any]) -> dict[str, Any] | None:
        symbol = _text(row.get("symbol")).upper()
        if not symbol:
            return None
        actual = _return_pct(row)
        peak = max(0.0, _to_float(row.get("peak_gain_pct"), _to_float(row.get("peak_unrealized_profit_pct"), _to_float(row.get("max_favorable_excursion_pct")))))
        giveback = max(0.0, _to_float(row.get("giveback_pct"), _to_float(row.get("profit_giveback_pct"), peak - actual)))
        capture = _to_float(row.get("capture_ratio"), _to_float(row.get("profit_capture_ratio"), max(0.0, actual) / peak if peak > 0 else 0.0))
        capture = max(0.0, min(1.0, capture))
        hold = _to_float(row.get("hold_time_minutes"), _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes")))
        cont = _to_float(row.get("continuation_quality"), _to_float(row.get("follow_through_quality_score"), _to_float(row.get("continuation_strength_score"), 50.0)))
        time_to_peak = _to_float(row.get("time_to_peak_minutes"), _to_float(row.get("time_from_entry_to_peak_minutes"), _to_float(row.get("time_to_mfe_seconds")) / 60.0))
        time_after_peak = max(0.0, hold - time_to_peak) if time_to_peak > 0 else 0.0
        variants = _partial_exit_variants(peak, actual, giveback)
        best_variant, best_return = max(variants.items(), key=lambda item: item[1])
        personality, personality_conf = _classify_personality({
            "peak_gain_pct": peak,
            "giveback_pct": giveback,
            "current_or_exit_gain_pct": actual,
            "hold_time_minutes": hold,
            "capture_ratio": capture,
            "continuation_quality": cont,
            "maximum_adverse_excursion_pct": row.get("maximum_adverse_excursion_pct") or row.get("max_adverse_excursion_pct"),
        })
        if personality in {"spike_and_fade", "failed_breakout_risk", "scalp_only_candidate"}:
            style = "protect_profit_earlier"
        elif personality in {"runner", "slow_grinder", "overnight_holder"}:
            style = "hold_longer_supported"
        else:
            style = "balanced_shadow_review"
        protection = _clamp((1.0 - capture) * 80.0 + min(20.0, giveback * 2.0))
        hold_score = _clamp(cont * 0.65 + capture * 35.0 - min(20.0, giveback))
        return {
            "symbol": symbol,
            "lifecycle_id": _text(row.get("lifecycle_id"), symbol),
            "horizon": _horizon(row),
            "archetype": _archetype(row),
            "regime": _regime(row),
            "time_window": _time_window(row),
            "actual_return_pct": _round(actual),
            "peak_gain_pct": _round(peak),
            "giveback_pct": _round(giveback),
            "capture_ratio": _round(capture, 4),
            "hold_minutes": _round(hold, 2),
            "time_to_peak": _round(time_to_peak, 2),
            "time_after_peak_before_decay": _round(time_after_peak, 2),
            "continuation_quality": _round(cont, 2),
            "best_partial_exit_variant": best_variant,
            "partial_exit_profit_delta": _round(best_return - actual),
            "partial_exit_capture_improvement": _round((best_return - actual) / max(peak, 0.01), 4),
            "partial_exit_confidence": _round(_clamp(35.0 + min(30.0, peak * 5.0) + min(25.0, giveback * 2.5) + (10.0 if hold > 30 else 0.0)), 2),
            "partial_exit_recommendation": "shadow_review_partial_protection" if best_variant != "hold_full_position" else "shadow_review_hold_full_position",
            "trade_personality": personality,
            "personality_confidence": _round(personality_conf, 2),
            "personality_best_exit_style": style,
            "personality_giveback_risk": _round(protection, 2),
            "personality_hold_score": _round(hold_score, 2),
            "personality_profit_protection_score": _round(protection, 2),
            "profit_decay_rate": _round(giveback / max(time_after_peak, hold, 1.0), 6),
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

    def _window_stats(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[_text(row.get("time_window"), "unknown")].append(row)
        stats: dict[str, dict[str, Any]] = {}
        for key, items in grouped.items():
            stats[key] = {
                "avg_return": _avg(_values(items, "actual_return_pct")),
                "avg_giveback": _avg(_values(items, "giveback_pct")),
                "avg_capture": _avg(_values(items, "capture_ratio")),
                "count": len(items),
            }
        best = max(stats.items(), key=lambda item: _to_float(item[1].get("avg_return"), -999), default=("insufficient_data", {}))[0]
        weak = min(stats.items(), key=lambda item: _to_float(item[1].get("avg_return"), 999), default=("insufficient_data", {}))[0]
        giveback = max(stats.items(), key=lambda item: _to_float(item[1].get("avg_giveback"), -999), default=("insufficient_data", {}))[0]
        return {"stats": stats, "best_profit_window": best, "weakest_time_window": weak, "highest_giveback_window": giveback}

    def _hold_stats(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        profitable = [row for row in rows if _to_float(row.get("actual_return_pct")) > 0]
        holds = _values(profitable, "hold_minutes")
        best_row = max(profitable, key=lambda row: _to_float(row.get("actual_return_pct")), default={})
        worst_row = min(rows, key=lambda row: _to_float(row.get("actual_return_pct")), default={})
        best_hold = _to_float(best_row.get("hold_minutes"), 0.0)
        label = "insufficient_data"
        if best_hold:
            label = f"{max(5, round(best_hold * 0.5, 1))}_to_{round(best_hold * 1.5, 1)}_minutes"
        hold_too_short = sum(1 for row in rows if _to_float(row.get("hold_minutes")) < max(10.0, _to_float(row.get("time_to_peak"))))
        hold_too_long = sum(1 for row in rows if _to_float(row.get("giveback_pct")) >= 1.0 and _to_float(row.get("hold_minutes")) > _to_float(row.get("time_to_peak")) + 60.0)
        return {
            "avg_profitable_hold_time": _avg(holds),
            "median_profitable_hold_time": _median(holds),
            "best_hold_duration": best_hold if best_hold else None,
            "worst_hold_duration": _to_float(worst_row.get("hold_minutes"), 0.0) if worst_row else None,
            "time_to_peak": _avg(_values(rows, "time_to_peak")),
            "time_after_peak_before_decay": _avg(_values(rows, "time_after_peak_before_decay")),
            "optimal_hold_window": label,
            "best_hold_window": label,
            "hold_too_short_count": hold_too_short,
            "hold_too_long_count": hold_too_long,
            "hold_longer_supported": hold_too_short > hold_too_long,
            "exit_sooner_supported": hold_too_long >= hold_too_short and hold_too_long > 0,
            "holding_time_confidence": _clamp(len(rows) * 1.6),
        }

    def _milestones(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        levels = [1, 2, 3, 5, 8, 10, 15]
        out: dict[str, dict[str, Any]] = {}
        for level in levels:
            touched = [row for row in rows if _to_float(row.get("peak_gain_pct")) >= level]
            continued = [row for row in touched if _to_float(row.get("peak_gain_pct")) >= level * 1.25 and _to_float(row.get("capture_ratio")) >= 0.55]
            stalled = [row for row in touched if _to_float(row.get("peak_gain_pct")) < level * 1.25 and _to_float(row.get("actual_return_pct")) >= 0]
            reversed_rows = [row for row in touched if _to_float(row.get("actual_return_pct")) < 0]
            decayed = [row for row in touched if _to_float(row.get("giveback_pct")) >= max(0.35, level * 0.25)]
            out[f"plus_{level}_pct"] = {
                "continued_higher_count": len(continued),
                "stalled_count": len(stalled),
                "reversed_count": len(reversed_rows),
                "average_gain_after_milestone": _avg(_values(touched, "actual_return_pct")),
                "average_giveback_after_milestone": _avg(_values(touched, "giveback_pct")),
                "average_time_to_decay": _avg(_values(decayed, "time_after_peak_before_decay")),
                "recovery_after_decay_count": sum(1 for row in decayed if _to_float(row.get("actual_return_pct")) > 0),
                "decay_probability": round(len(decayed) / max(1, len(touched)) * 100.0, 4) if touched else None,
                "continuation_probability": round(len(continued) / max(1, len(touched)) * 100.0, 4) if touched else None,
            }
        highest_decay = max(out.items(), key=lambda item: _to_float(item[1].get("decay_probability"), -1), default=("insufficient_data", {}))[0]
        return {"milestone_stats": out, "highest_decay_milestone": highest_decay}

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        rows = [row for row in (self._derive(raw) for raw in self._latest_rows()) if row]
        self._write_rows(rows)
        windows = self._window_stats(rows)
        hold = self._hold_stats(rows)
        milestones = self._milestones(rows)
        personalities = Counter(_text(row.get("trade_personality"), "insufficient_evidence") for row in rows)
        variants = Counter(_text(row.get("best_partial_exit_variant"), "hold_full_position") for row in rows)
        dominant = personalities.most_common(1)[0][0] if personalities else "insufficient_evidence"
        weakest = max(
            personalities.keys(),
            key=lambda p: _avg(_values([row for row in rows if row.get("trade_personality") == p], "capture_ratio")) or 999,
            default="insufficient_evidence",
        ) if personalities else "insufficient_evidence"
        avg_delta = _avg(_values(rows, "partial_exit_profit_delta"))
        avg_capture_improve = _avg(_values(rows, "partial_exit_capture_improvement"))
        continuation_score = _clamp((_avg(_values(rows, "continuation_quality")) or 0.0) * 0.8)
        avg_giveback = _avg(_values(rows, "giveback_pct")) or 0.0
        avg_capture = _avg(_values(rows, "capture_ratio")) or 0.0
        protect_score = _clamp((1.0 - avg_capture) * 70.0 + min(30.0, avg_giveback * 2.5))
        hold_score = _clamp(continuation_score * 0.7 + avg_capture * 30.0)
        decay_risk = _to_float((milestones.get("milestone_stats") or {}).get(milestones.get("highest_decay_milestone"), {}).get("decay_probability"), 0.0)
        if protect_score > hold_score + 8:
            bias = "protect_profit_after_decay"
        elif hold_score > protect_score + 8:
            bias = "hold_runners_longer"
        else:
            bias = "balanced_partial_protection_review"
        recommendation = f"Shadow-only: {bias.replace('_', ' ')}. Study {dominant.replace('_', ' ')} trades and {windows['highest_giveback_window'].replace('_', ' ')} giveback before any human-reviewed policy changes."
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_exit_learning_expansion",
            "tracked_trades": len(rows),
            "best_partial_exit_variant": variants.most_common(1)[0][0] if variants else "insufficient_data",
            "partial_exit_profit_delta": avg_delta,
            "partial_exit_capture_improvement": avg_capture_improve,
            "partial_exit_confidence": _avg(_values(rows, "partial_exit_confidence")),
            "partial_exit_recommendation": "shadow_review_only",
            "first_15_min_return": _avg(_values([r for r in rows if r.get("time_window") == "first_15_min"], "actual_return_pct")),
            "first_30_min_return": _avg(_values([r for r in rows if r.get("time_window") == "first_30_min"], "actual_return_pct")),
            "first_60_min_return": _avg(_values([r for r in rows if r.get("time_window") == "first_60_min"], "actual_return_pct")),
            "lunch_period_return": _avg(_values([r for r in rows if r.get("time_window") == "lunch_period"], "actual_return_pct")),
            "power_hour_return": _avg(_values([r for r in rows if r.get("time_window") == "power_hour"], "actual_return_pct")),
            "overnight_return": _avg(_values([r for r in rows if r.get("time_window") == "overnight"], "actual_return_pct")),
            "time_to_peak": _avg(_values(rows, "time_to_peak")),
            "time_of_peak": windows["best_profit_window"],
            "best_time_window": windows["best_profit_window"],
            "weakest_time_window": windows["weakest_time_window"],
            "time_window_by_horizon": _group_avg(rows, "horizon", "actual_return_pct"),
            "time_window_by_archetype": _group_avg(rows, "archetype", "actual_return_pct"),
            "time_window_by_regime": _group_avg(rows, "regime", "actual_return_pct"),
            "best_profit_window": windows["best_profit_window"],
            "highest_giveback_window": windows["highest_giveback_window"],
            "best_entry_to_exit_window": f"{windows['best_profit_window']}_to_{windows['highest_giveback_window']}",
            "time_of_day_exit_bias": "protect_in_high_giveback_window" if windows["highest_giveback_window"] != "insufficient_data" else "insufficient_data",
            "time_of_day_recommendation": "shadow_only_time_window_review",
            "dominant_trade_personality": dominant,
            "weakest_trade_personality": weakest,
            "trade_personality_distribution": dict(personalities.most_common(10)),
            "personality_best_exit_style": dict(Counter(_text(row.get("personality_best_exit_style"), "insufficient_evidence") for row in rows).most_common(8)),
            "personality_giveback_risk": _group_avg(rows, "trade_personality", "personality_giveback_risk"),
            "personality_hold_score": _group_avg(rows, "trade_personality", "personality_hold_score"),
            "personality_profit_protection_score": _group_avg(rows, "trade_personality", "personality_profit_protection_score"),
            **hold,
            **milestones,
            "profit_decay_risk": _round(decay_risk, 2),
            "continuation_after_profit_score": _round(continuation_score, 2),
            "protect_profit_score": _round(protect_score, 2),
            "hold_longer_score": _round(hold_score, 2),
            "milestone_exit_bias": bias,
            "shadow_exit_learning_recommendation": recommendation,
            "behavior_safe_to_apply": False,
            "human_review_required": True,
            "auto_apply_allowed": False,
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
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "summary": "Astra is studying whether winners should be held, partially protected, or exited sooner based on time of day, trade personality, holding time, and profit decay. This is shadow-only learning and does not change trading behavior yet.",
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
