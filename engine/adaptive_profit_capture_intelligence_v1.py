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
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1500


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
    text = str(value if value is not None else default).strip()
    return text or str(default)


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


def _capture_label(capture_ratio: float, peak: float, closed: bool) -> str:
    if not closed:
        return "still_open_learning"
    if peak <= 0.05:
        return "no_profit_available"
    if capture_ratio >= 0.80:
        return "excellent_capture"
    if capture_ratio >= 0.60:
        return "good_capture"
    if capture_ratio >= 0.40:
        return "acceptable_capture"
    if capture_ratio >= 0.20:
        return "weak_capture"
    return "severe_giveback"


def _giveback_label(giveback: float, peak: float) -> str:
    if peak <= 0.05:
        return "no_profit_available"
    ratio = giveback / peak if peak > 0 else 0.0
    if ratio < 0.20 and giveback < 0.35:
        return "no_action_needed"
    if ratio < 0.40:
        return "monitor_profit_giveback"
    if ratio < 0.65:
        return "profit_capture_watch"
    return "high_giveback_watch"


def _giveback_pattern(row: dict[str, Any], peak: float, giveback: float, capture_ratio: float, time_to_peak: float) -> str:
    follow_label = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")).lower()
    sector = _text(row.get("sector"), "unknown").lower()
    regime = _text(row.get("market_regime"), "unknown").lower()
    mae = _to_float(row.get("max_adverse_excursion_pct"))
    hold_minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
    if giveback <= 0.25 or peak <= 0.25:
        return "minimal_giveback"
    if time_to_peak > 0 and time_to_peak <= 30 and giveback >= 0.75:
        return "fast_spike"
    if "failed" in follow_label or "stalled" in follow_label:
        return "failed_continuation"
    if mae <= -1.5 and giveback >= 0.75:
        return "volatility_reversal"
    if capture_ratio < 0.25 and peak >= 1.5:
        return "high_volatility_exhaustion"
    if "risk_off" in regime or "bear" in regime:
        return "market_regime_shift"
    if sector not in {"", "unknown"} and giveback >= 1.0:
        return "sector_fade"
    if hold_minutes >= 300 and giveback >= 0.75:
        return "slow_grind"
    return "profit_decay"


def _context_key(row: dict[str, Any]) -> str:
    return (
        f"{_text(row.get('sector'), 'unknown')}:"
        f"{_text(row.get('cap_tier'), 'unknown')}:"
        f"{_text(row.get('horizon_style'), 'unknown')}"
    )


class AdaptiveProfitCaptureIntelligenceV1:
    """Profit-capture learning derived from paper lifecycle evidence.

    This module is diagnostic-only. It never submits orders, closes positions,
    changes thresholds, or mutates broker state.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.v1_path, self.v2_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                if lifecycle_id:
                    latest[lifecycle_id] = row
        return list(latest.values())

    def _derive_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        lifecycle_id = _text(row.get("lifecycle_id"))
        symbol = _text(row.get("symbol")).upper()
        if not lifecycle_id or not symbol:
            return None
        closed = bool(row.get("closed"))
        peak = max(0.0, _to_float(row.get("peak_unrealized_profit_pct"), _to_float(row.get("max_favorable_excursion_pct"))))
        current_profit = _to_float(
            row.get("current_or_exit_profit_pct"),
            _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"))),
        )
        missed = max(0.0, peak - current_profit)
        giveback = max(0.0, _to_float(row.get("profit_giveback_pct"), missed))
        capture_ratio = _to_float(row.get("profit_capture_ratio"), (max(0.0, current_profit) / peak if peak > 0 else 0.0))
        capture_ratio = max(0.0, min(1.0, capture_ratio))
        time_to_peak = _to_float(row.get("time_to_continuation_minutes"), _to_float(row.get("time_to_mfe_seconds")) / 60.0)
        hold_minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
        time_after_peak = max(0.0, hold_minutes - time_to_peak) if time_to_peak > 0 else 0.0
        decay_velocity = giveback / max(time_after_peak, hold_minutes, 1.0)
        retention_score = _clamp(capture_ratio * 100.0)
        penalty = min(35.0, giveback * 4.0) + min(20.0, decay_velocity * 50.0)
        quality = _clamp(retention_score - penalty + (10.0 if peak >= 1.0 and capture_ratio >= 0.6 else 0.0))
        label = _capture_label(capture_ratio, peak, closed)
        pattern = _giveback_pattern(row, peak, giveback, capture_ratio, time_to_peak)
        watch_label = _giveback_label(giveback, peak)
        continuation_healthy = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")) in {
            "strong_continuation",
            "moderate_continuation",
            "strong_follow_through",
            "moderate_follow_through",
        }
        attention = 0.0 if closed else _clamp((giveback / max(peak, 0.25)) * 70.0 + max(0.0, -current_profit) * 8.0 + decay_velocity * 100.0)
        if not closed and continuation_healthy and attention < 35:
            watch_label = "continuation_still_healthy"
        reason = (
            "Active trade has meaningful peak profit and visible giveback."
            if not closed and attention >= 45
            else "Active trade remains under watch-only profit-capture learning."
            if not closed
            else f"Closed trade classified as {label}."
        )
        return {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "timestamp": _text(row.get("timestamp") or row.get("last_update_timestamp") or row.get("current_timestamp") or _now_iso()),
            "closed": closed,
            "peak_unrealized_profit_pct": _round(peak),
            "current_or_exit_profit_pct": _round(current_profit),
            "profit_capture_ratio": _round(capture_ratio, 4),
            "missed_profit_pct": _round(missed),
            "profit_giveback_pct": _round(giveback),
            "giveback_from_peak_pct": _round((giveback / peak) * 100.0 if peak > 0 else 0.0),
            "time_from_entry_to_peak_minutes": _round(time_to_peak, 2),
            "time_from_peak_to_giveback_minutes": _round(time_after_peak, 2),
            "profit_decay_velocity": _round(decay_velocity, 6),
            "profit_retention_score": _round(retention_score, 2),
            "profit_capture_quality_score": _round(quality, 2),
            "profit_capture_label": label,
            "giveback_severity_label": watch_label,
            "giveback_pattern": pattern,
            "current_unrealized_profit_pct": _round(current_profit),
            "current_giveback_pct": _round(giveback),
            "profit_protection_attention_score": _round(attention, 2),
            "continuation_still_healthy": bool(continuation_healthy),
            "profit_capture_watch_reason": reason,
            "sector": _text(row.get("sector"), "unknown"),
            "cap_tier": _text(row.get("cap_tier"), "unknown"),
            "trade_archetype": _text(row.get("trade_archetype"), "unknown"),
            "horizon_style": _text(row.get("horizon_style"), "unknown"),
            "market_regime": _text(row.get("market_regime"), "unknown"),
            "session_type": _text(row.get("session_type"), "unknown"),
            "allocation_lane": _text(row.get("allocation_lane"), "unknown"),
            "generated_at": _now_iso(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
        }

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 45.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-80:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
        return round(mean(vals), 4) if vals else None

    @staticmethod
    def _group_average(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            key = _text(row.get(group_key), "unknown")
            if row.get(value_key) not in (None, ""):
                grouped[key].append(_to_float(row.get(value_key)))
        return {key: round(mean(values), 4) for key, values in grouped.items() if values}

    @staticmethod
    def _best_group(rows: list[dict[str, Any]], key: str, value_key: str, *, reverse: bool) -> str:
        grouped = AdaptiveProfitCaptureIntelligenceV1._group_average(rows, key, value_key)
        if not grouped:
            return "insufficient_data"
        return sorted(grouped.items(), key=lambda item: item[1], reverse=reverse)[0][0]

    def status(self, open_positions: list[dict[str, Any]] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        derived = [row for row in (self._derive_row(raw) for raw in self._latest_rows()) if row]
        active_rows = [row for row in derived if not row.get("closed")]
        if open_positions is not None:
            active_symbols = {_text(row.get("symbol")).upper() for row in open_positions if isinstance(row, dict)}
            if active_symbols:
                active_rows = [row for row in active_rows if row.get("symbol") in active_symbols]
        active_by_symbol: dict[str, dict[str, Any]] = {}
        for row in active_rows:
            symbol = _text(row.get("symbol")).upper()
            previous = active_by_symbol.get(symbol)
            if not previous or _text(row.get("timestamp")) >= _text(previous.get("timestamp")):
                active_by_symbol[symbol] = row
        active = list(active_by_symbol.values())
        closed = [row for row in derived if row.get("closed")]
        summary_rows = active + closed
        self._write_rows(summary_rows)

        capture_dist = Counter(_text(row.get("profit_capture_label"), "insufficient_data") for row in summary_rows)
        pattern_counts = Counter(_text(row.get("giveback_pattern"), "unknown") for row in summary_rows)
        high_giveback = [
            row for row in summary_rows
            if _text(row.get("profit_capture_label")) in {"weak_capture", "severe_giveback"}
            or _text(row.get("giveback_severity_label")) in {"profit_capture_watch", "high_giveback_watch"}
        ]
        open_watchlist = [
            {
                "symbol": row.get("symbol"),
                "current_unrealized_profit_pct": row.get("current_unrealized_profit_pct"),
                "peak_unrealized_profit_pct": row.get("peak_unrealized_profit_pct"),
                "current_giveback_pct": row.get("current_giveback_pct"),
                "giveback_severity_label": row.get("giveback_severity_label"),
                "profit_protection_attention_score": row.get("profit_protection_attention_score"),
                "continuation_still_healthy": row.get("continuation_still_healthy"),
                "profit_capture_watch_reason": row.get("profit_capture_watch_reason"),
            }
            for row in sorted(active, key=lambda item: _to_float(item.get("profit_protection_attention_score")), reverse=True)[:12]
        ]
        avg_capture = self._avg(summary_rows, "profit_capture_ratio")
        avg_giveback = self._avg(summary_rows, "profit_giveback_pct")
        avg_missed = self._avg(summary_rows, "missed_profit_pct")
        avg_retention = self._avg(summary_rows, "profit_retention_score")
        avg_quality = self._avg(summary_rows, "profit_capture_quality_score")
        worst_symbol = max(summary_rows, key=lambda row: _to_float(row.get("profit_giveback_pct")), default={}).get("symbol", "insufficient_data")
        recommendation = "insufficient_data"
        reason = "Waiting for more lifecycle profit-capture evidence."
        if len(summary_rows) >= 5:
            if len(high_giveback) >= max(2, int(len(summary_rows) * 0.25)):
                recommendation = "monitor_peak_decay_for_context"
                reason = "Meaningful peak profits are being surrendered often enough to require watch-only review."
            elif (avg_capture or 0.0) < 0.45:
                recommendation = "improve_continuation_confirmation"
                reason = "Average retained profit is below the acceptable capture band."
            elif (avg_capture or 0.0) >= 0.65:
                recommendation = "allow_more_patience_for_context"
                reason = "Profit capture is holding up in current evidence; avoid overreactive future tuning."
            else:
                recommendation = "tighten_profit_review_for_context"
                reason = "Capture is acceptable but giveback remains visible; keep shadow review focused."

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_profit_capture_learning",
            "tracked_lifecycles": len(summary_rows),
            "active_trades_reviewed": len(active),
            "closed_trades_reviewed": len(closed),
            "average_profit_capture_ratio": avg_capture,
            "average_profit_giveback_pct": avg_giveback,
            "average_missed_profit_pct": avg_missed,
            "average_profit_retention_score": avg_retention,
            "profit_capture_quality_score": avg_quality,
            "high_giveback_trade_count": len(high_giveback),
            "excellent_capture_count": int(capture_dist.get("excellent_capture", 0)),
            "weak_capture_count": int(capture_dist.get("weak_capture", 0)),
            "severe_giveback_count": int(capture_dist.get("severe_giveback", 0)),
            "profit_capture_label_distribution": dict(capture_dist),
            "best_profit_capture_context": self._best_group(summary_rows, "sector", "profit_capture_ratio", reverse=True),
            "weakest_profit_capture_context": self._best_group(summary_rows, "sector", "profit_capture_ratio", reverse=False),
            "best_profit_capture_symbol": self._best_group(summary_rows, "symbol", "profit_capture_ratio", reverse=True),
            "worst_profit_capture_symbol": self._best_group(summary_rows, "symbol", "profit_capture_ratio", reverse=False),
            "best_profit_capture_archetype": self._best_group(summary_rows, "trade_archetype", "profit_capture_ratio", reverse=True),
            "worst_profit_capture_archetype": self._best_group(summary_rows, "trade_archetype", "profit_capture_ratio", reverse=False),
            "worst_giveback_symbol": worst_symbol,
            "top_giveback_patterns": dict(pattern_counts.most_common(6)),
            "most_common_giveback_pattern": pattern_counts.most_common(1)[0][0] if pattern_counts else "insufficient_data",
            "high_giveback_symbols": [row.get("symbol") for row in sorted(high_giveback, key=lambda item: _to_float(item.get("profit_giveback_pct")), reverse=True)[:8]],
            "high_giveback_archetypes": dict(Counter(_text(row.get("trade_archetype"), "unknown") for row in high_giveback).most_common(6)),
            "high_giveback_contexts": dict(Counter(_context_key(row) for row in high_giveback).most_common(6)),
            "profit_capture_by_horizon": self._group_average(summary_rows, "horizon_style", "profit_capture_ratio"),
            "profit_capture_by_regime": self._group_average(summary_rows, "market_regime", "profit_capture_ratio"),
            "profit_capture_by_sector": self._group_average(summary_rows, "sector", "profit_capture_ratio"),
            "open_position_watchlist": open_watchlist,
            "open_position_watchlist_count": len(open_watchlist),
            "profit_capture_recommendation": recommendation,
            "profit_capture_reason": reason,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "summary": (
                f"Reviewed {len(summary_rows)} paper lifecycles for profit retention, giveback, and peak-decay behavior."
            ),
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
