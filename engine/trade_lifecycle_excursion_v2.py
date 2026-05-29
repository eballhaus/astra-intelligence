from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "2.0.0"
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


def _hold_bucket(minutes: float) -> str:
    if minutes < 30:
        return "scalp_under_30_min"
    if minutes < 240:
        return "day_trade_30_min_to_4_hr"
    if minutes < 1440:
        return "full_day_trade"
    if minutes < 4320:
        return "overnight_swing"
    return "multi_day_swing"


def _expected_hold_minutes(row: dict[str, Any]) -> float:
    horizon = _text(row.get("horizon_style"), "unknown").lower()
    archetype = _text(row.get("trade_archetype"), "unknown").lower()
    if "scalp" in horizon or "scalp" in archetype:
        return 20.0
    if "swing" in horizon or "multi" in horizon:
        return 1440.0
    if "overnight" in horizon:
        return 720.0
    if "day" in horizon or "breakout" in archetype or "momentum" in archetype:
        return 180.0
    return 120.0


def _ideal_hold_range(expected: float) -> str:
    low = max(5.0, expected * 0.35)
    high = max(low + 5.0, expected * 1.75)
    return f"{round(low, 1)}_to_{round(high, 1)}_minutes"


def _hold_quality(actual: float, expected: float, closed: bool) -> tuple[float, float, float, str]:
    if actual < 10 and not closed:
        return 50.0, 8.0, 0.0, "too_early_to_judge"
    ratio = actual / expected if expected > 0 else 1.0
    mismatch = abs(1.0 - min(ratio, 2.5) / 1.0)
    quality = _clamp(100.0 - mismatch * 42.0, 0.0, 100.0)
    early_risk = _clamp((0.75 - ratio) * 100.0 if ratio < 0.75 else 0.0)
    overstay_risk = _clamp((ratio - 1.8) * 55.0 if ratio > 1.8 else 0.0)
    if not closed and ratio < 0.45:
        label = "duration_learning_needed"
    elif early_risk >= 35:
        label = "possible_premature_exit" if closed else "duration_learning_needed"
    elif overstay_risk >= 35:
        label = "possible_overstay"
    elif quality >= 68:
        label = "healthy_hold"
    else:
        label = "duration_mismatch"
    return round(quality, 2), round(early_risk, 2), round(overstay_risk, 2), label


def _giveback_label(giveback: float, peak: float) -> str:
    if peak <= 0.05:
        return "no_profit_to_protect"
    ratio = giveback / peak if peak > 0 else 0.0
    if giveback <= 0.15 or ratio <= 0.15:
        return "minimal_giveback"
    if giveback <= 0.45 or ratio <= 0.35:
        return "acceptable_giveback"
    if giveback <= 1.0 or ratio <= 0.65:
        return "elevated_giveback"
    return "severe_giveback"


def _continuation_label(row: dict[str, Any], current_return: float, mfe: float, mae: float, hold_minutes: float, decay: float) -> str:
    if hold_minutes < 5:
        return "insufficient_time"
    if current_return >= 1.25 and mfe >= 1.5 and decay < 35:
        return "strong_continuation"
    if current_return >= 0.45 and mfe >= 0.75 and decay < 55:
        return "moderate_continuation"
    if current_return <= -0.8 or mae <= -1.2:
        return "failed_continuation"
    if mfe < 0.35 and hold_minutes >= 20:
        return "stalled_after_entry"
    if mfe >= 0.75 and abs(mae) >= 0.9:
        return "volatile_but_surviving"
    return "weak_continuation"


def _exit_timing_label(row: dict[str, Any]) -> str:
    if not bool(row.get("closed")):
        return "insufficient_exit_data"
    raw = _text(row.get("exit_classification"), "unknown_exit")
    mapping = {
        "profit_protection_exit": "profit_protection_exit",
        "stop_loss_exit": "stop_loss_exit",
        "momentum_decay_exit": "momentum_decay_exit",
        "premature_exit": "premature_exit",
        "overstayed_exit": "overstayed_exit",
        "healthy_continuation_exit": "efficient_exit",
        "invalidation_exit": "stop_loss_exit",
    }
    return mapping.get(raw, "acceptable_exit" if _to_float(row.get("exit_quality_score")) >= 55 else "insufficient_exit_data")


def _learning_recommendation(exit_label: str, giveback_label: str, continuation_label: str, hold_label: str) -> str:
    if giveback_label in {"elevated_giveback", "severe_giveback"}:
        return "review_profit_protection_timing_shadow_only"
    if continuation_label in {"failed_continuation", "stalled_after_entry"}:
        return "study_weak_follow_through_context_shadow_only"
    if hold_label in {"possible_premature_exit", "duration_mismatch"}:
        return "collect_hold_duration_evidence_shadow_only"
    if exit_label in {"efficient_exit", "profit_protection_exit"}:
        return "preserve_current_natural_exit_evidence"
    return "continue_collecting_lifecycle_evidence"


class TradeLifecycleExcursionV2:
    """Derived lifecycle learning for hold duration, giveback, continuation, and exits.

    V2 is observational only. It reads V1 lifecycle telemetry, writes compact
    learning snapshots, and never submits orders, changes exits, or mutates broker state.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_snapshot_write = 0.0

    def _latest_v1_records(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _tail_jsonl(self.v1_path):
            lifecycle_id = _text(row.get("lifecycle_id"))
            if lifecycle_id:
                latest[lifecycle_id] = row
        return list(latest.values())

    def _append_snapshots(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_snapshot_write < 45.0:
            return
        self._last_snapshot_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-80:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def _derive_record(self, row: dict[str, Any]) -> dict[str, Any]:
        closed = bool(row.get("closed"))
        mfe = _to_float(row.get("max_favorable_excursion_pct"))
        mae = _to_float(row.get("max_adverse_excursion_pct"))
        peak = _to_float(row.get("peak_unrealized_profit_pct"), max(0.0, mfe))
        current_profit = _to_float(row.get("current_return_pct"), _to_float(row.get("post_entry_continuation_pct")))
        giveback = max(0.0, _to_float(row.get("profit_giveback_pct"), max(0.0, peak - current_profit)))
        capture_ratio = _to_float(row.get("profit_capture_ratio"), (max(0.0, current_profit) / peak if peak > 0 else 0.0))
        hold_minutes = _to_float(row.get("hold_duration_minutes"), _to_float(row.get("hold_duration_seconds")) / 60.0)
        expected = _expected_hold_minutes(row)
        hold_quality, early_risk, overstay_risk, hold_label = _hold_quality(hold_minutes, expected, closed)
        time_to_mfe = _to_float(row.get("time_to_mfe_seconds")) / 60.0
        giveback_after_mfe = max(0.0, hold_minutes - time_to_mfe) if time_to_mfe > 0 else 0.0
        giveback_velocity = giveback / max(giveback_after_mfe, hold_minutes, 1.0)
        continuation_strength = _clamp(row.get("continuation_strength"), 50.0)
        continuation_decay = _clamp(row.get("continuation_decay_score"), giveback * 12.0)
        follow_score = _clamp(row.get("follow_through_score"), 50.0)
        continuation_label = _continuation_label(row, current_profit, mfe, mae, hold_minutes, continuation_decay)
        failure_risk = _clamp(100.0 - follow_score + continuation_decay * 0.35)
        exit_label = _exit_timing_label(row)
        exit_quality = None if row.get("exit_quality_score") in (None, "") else _to_float(row.get("exit_quality_score"), 0.0)
        if exit_quality is None or (not closed and exit_quality == 0.0):
            exit_quality = None
        exit_efficiency = row.get("exit_efficiency_score") if closed else None
        giveback_label = _giveback_label(giveback, peak)
        record = {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": _text(row.get("lifecycle_id")),
            "symbol": _text(row.get("symbol")).upper(),
            "timestamp": _text(row.get("last_update_timestamp") or row.get("current_timestamp") or row.get("generated_at") or _now_iso()),
            "entry_timestamp": _text(row.get("entry_timestamp")),
            "entry_price": _round(row.get("entry_price")),
            "current_price": _round(row.get("current_price")),
            "exit_price": row.get("exit_price") if closed else None,
            "closed": closed,
            "max_favorable_excursion_pct": _round(mfe),
            "max_adverse_excursion_pct": _round(mae),
            "peak_unrealized_profit_pct": _round(peak),
            "current_or_exit_profit_pct": _round(current_profit),
            "profit_giveback_pct": _round(giveback),
            "profit_capture_ratio": _round(capture_ratio, 4),
            "giveback_severity_label": giveback_label,
            "giveback_velocity": _round(giveback_velocity, 6),
            "giveback_after_mfe_minutes": _round(giveback_after_mfe, 2),
            "expected_hold_duration_minutes": _round(expected, 2),
            "actual_hold_duration_minutes": _round(hold_minutes, 2),
            "hold_duration_minutes": _round(hold_minutes, 2),
            "hold_duration_quality_score": hold_quality,
            "hold_duration_bucket": _hold_bucket(hold_minutes),
            "hold_duration_vs_expected": _round(hold_minutes - expected, 2),
            "early_exit_risk_score": early_risk,
            "overstaying_risk_score": overstay_risk,
            "ideal_hold_range_label": _ideal_hold_range(expected),
            "hold_duration_label": hold_label,
            "continuation_after_entry_pct": _round(current_profit),
            "continuation_strength_score": _round(continuation_strength, 2),
            "continuation_decay_score": _round(continuation_decay, 2),
            "follow_through_quality_score": _round(follow_score, 2),
            "follow_through_failure_risk": _round(failure_risk, 2),
            "follow_through_label": continuation_label,
            "continuation_pattern_label": continuation_label,
            "time_to_continuation_minutes": _round(time_to_mfe, 2) if mfe > 0 else None,
            "time_to_stall_minutes": _round(hold_minutes, 2) if continuation_label == "stalled_after_entry" else None,
            "exit_quality_score": _round(exit_quality, 2) if exit_quality is not None else None,
            "exit_efficiency_score": _round(exit_efficiency, 2) if exit_efficiency is not None else None,
            "exit_timing_label": exit_label,
            "exit_label": exit_label,
            "missed_profit_pct": _round(max(0.0, giveback if closed else 0.0)),
            "avoided_loss_pct": _round(row.get("avoidable_loss_pct")),
            "exit_context_label": f"{_text(row.get('sector'), 'unknown')}:{_text(row.get('market_regime'), 'unknown')}:{exit_label}",
            "exit_learning_recommendation": _learning_recommendation(exit_label, giveback_label, continuation_label, hold_label),
            "horizon_style": _text(row.get("horizon_style"), "unknown"),
            "trade_archetype": _text(row.get("trade_archetype"), "unknown"),
            "sector": _text(row.get("sector"), "unknown"),
            "cap_tier": _text(row.get("cap_tier"), "unknown"),
            "market_regime": _text(row.get("market_regime"), "unknown"),
            "session_type": _text(row.get("session_type") or row.get("entry_session_mode"), "unknown"),
            "generated_at": _now_iso(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
        }
        return record

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str, *, closed_only: bool = False) -> float | None:
        source = [r for r in rows if (not closed_only or r.get("closed"))]
        vals = [_to_float(r.get(key)) for r in source if r.get(key) not in (None, "")]
        return round(mean(vals), 4) if vals else None

    @staticmethod
    def _best_context(rows: list[dict[str, Any]], key: str, score_key: str, reverse: bool = True) -> str:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            context = _text(row.get(key), "unknown")
            if context == "unknown":
                context = f"{_text(row.get('sector'), 'unknown')}:{_text(row.get('cap_tier'), 'unknown')}:{_text(row.get('horizon_style'), 'unknown')}"
            if row.get(score_key) not in (None, ""):
                grouped[context].append(_to_float(row.get(score_key)))
        ranked = sorted(((mean(values), ctx) for ctx, values in grouped.items() if values), reverse=reverse)
        return ranked[0][1] if ranked else "insufficient_evidence"

    def status(self, open_positions: list[dict[str, Any]] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        v1_rows = self._latest_v1_records()
        records = [self._derive_record(row) for row in v1_rows]
        active_candidates = [r for r in records if not r.get("closed")]
        if open_positions is not None:
            active_symbols = {_text(r.get("symbol")).upper() for r in open_positions if isinstance(r, dict)}
            if active_symbols:
                active_candidates = [r for r in active_candidates if _text(r.get("symbol")).upper() in active_symbols]
        active_by_symbol: dict[str, dict[str, Any]] = {}
        for row in active_candidates:
            symbol = _text(row.get("symbol")).upper()
            if not symbol:
                continue
            current_ts = _text(row.get("timestamp") or row.get("generated_at"))
            previous_ts = _text((active_by_symbol.get(symbol) or {}).get("timestamp") or (active_by_symbol.get(symbol) or {}).get("generated_at"))
            if symbol not in active_by_symbol or current_ts >= previous_ts:
                active_by_symbol[symbol] = row
        active = list(active_by_symbol.values())
        closed = [r for r in records if r.get("closed")]
        summary_records = active + closed
        self._append_snapshots(summary_records)

        exit_dist = Counter(_text(r.get("exit_label"), "insufficient_exit_data") for r in closed)
        follow_dist = Counter(_text(r.get("follow_through_label"), "insufficient_time") for r in summary_records)
        high_giveback = [r for r in summary_records if _text(r.get("giveback_severity_label")) in {"elevated_giveback", "severe_giveback"}]
        evidence_count = len(summary_records)
        closed_count = len(closed)
        learning_ready = bool(evidence_count >= 5 or closed_count >= 2)
        maturity = "healthy" if learning_ready else ("warming_up" if evidence_count else "awaiting_lifecycle_outcomes")
        best_profit_symbol = max(summary_records, key=lambda r: _to_float(r.get("profit_capture_ratio")), default={}).get("symbol", "insufficient_evidence")
        worst_giveback_symbol = max(summary_records, key=lambda r: _to_float(r.get("profit_giveback_pct")), default={}).get("symbol", "insufficient_evidence")
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_lifecycle_learning_v2",
            "trade_lifecycle_excursion_v2_status": True,
            "tracked_active_trades": len(active),
            "tracked_closed_trades": closed_count,
            "total_tracked_lifecycles": evidence_count,
            "average_mfe_pct": self._avg(summary_records, "max_favorable_excursion_pct"),
            "average_mae_pct": self._avg(summary_records, "max_adverse_excursion_pct"),
            "average_profit_giveback_pct": self._avg(summary_records, "profit_giveback_pct"),
            "average_profit_capture_ratio": self._avg(summary_records, "profit_capture_ratio"),
            "average_giveback_after_mfe": self._avg(summary_records, "giveback_after_mfe_minutes"),
            "average_hold_duration_minutes": self._avg(summary_records, "hold_duration_minutes"),
            "average_hold_duration_quality": self._avg(summary_records, "hold_duration_quality_score"),
            "average_exit_quality": self._avg(summary_records, "exit_quality_score", closed_only=True),
            "average_exit_efficiency": self._avg(summary_records, "exit_efficiency_score", closed_only=True),
            "average_follow_through_quality": self._avg(summary_records, "follow_through_quality_score"),
            "high_giveback_trade_count": len(high_giveback),
            "premature_exit_count": int(exit_dist.get("premature_exit", 0)),
            "overstayed_exit_count": int(exit_dist.get("overstayed_exit", 0)),
            "stop_loss_exit_count": int(exit_dist.get("stop_loss_exit", 0)),
            "profit_protection_exit_count": int(exit_dist.get("profit_protection_exit", 0)),
            "exit_label_distribution": dict(exit_dist),
            "follow_through_distribution": dict(follow_dist),
            "best_follow_through_context": self._best_context(summary_records, "sector", "follow_through_quality_score", True),
            "weakest_follow_through_context": self._best_context(summary_records, "sector", "follow_through_quality_score", False),
            "best_hold_duration_context": self._best_context(summary_records, "horizon_style", "hold_duration_quality_score", True),
            "weakest_hold_duration_context": self._best_context(summary_records, "horizon_style", "hold_duration_quality_score", False),
            "best_profit_capture_context": self._best_context(summary_records, "sector", "profit_capture_ratio", True),
            "weakest_profit_capture_context": self._best_context(summary_records, "sector", "profit_capture_ratio", False),
            "strongest_continuation_archetype": self._best_context(summary_records, "trade_archetype", "continuation_strength_score", True),
            "weakest_continuation_archetype": self._best_context(summary_records, "trade_archetype", "continuation_strength_score", False),
            "symbols_with_best_continuation": [r.get("symbol") for r in sorted(summary_records, key=lambda r: _to_float(r.get("continuation_strength_score")), reverse=True)[:5]],
            "symbols_with_worst_giveback": [r.get("symbol") for r in sorted(summary_records, key=lambda r: _to_float(r.get("profit_giveback_pct")), reverse=True)[:5]],
            "best_profit_capture_symbol": best_profit_symbol,
            "worst_giveback_symbol": worst_giveback_symbol,
            "learning_readiness": "ready" if learning_ready else maturity,
            "learning_ready": learning_ready,
            "maturity": maturity,
            "summary": (
                f"V2 is deriving hold-duration, giveback, continuation, and exit-quality learning from "
                f"{len(active)} active and {closed_count} naturally closed paper lifecycles."
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
