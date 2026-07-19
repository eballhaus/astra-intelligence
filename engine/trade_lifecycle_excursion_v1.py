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
MAX_TAIL_BYTES = 1_500_000
MAX_ROWS = 1200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _safe_json_load(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _parse_ts(value: Any) -> float:
    text = _to_text(value)
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _pct(current: float, entry: float) -> float:
    if entry <= 0.0 or current <= 0.0:
        return 0.0
    return ((current - entry) / entry) * 100.0


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


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


def _hold_bucket(seconds: float) -> str:
    minutes = max(0.0, seconds / 60.0)
    if minutes < 5:
        return "under_5_min"
    if minutes < 15:
        return "5_to_15_min"
    if minutes < 30:
        return "15_to_30_min"
    if minutes < 60:
        return "30_to_60_min"
    if minutes < 240:
        return "1_to_4_hours"
    if minutes < 1440:
        return "intraday_full_session"
    return "multi_day_swing"


def _follow_label(ret: float, mfe: float, mae: float, hold_seconds: float, velocity: float) -> str:
    if hold_seconds < 300:
        return "insufficient_time"
    if ret >= 1.5 and mfe >= 1.5 and velocity >= 0:
        return "strong_follow_through"
    if ret >= 0.5 and mfe >= 0.75:
        return "moderate_follow_through"
    if ret <= -1.0 or mae <= -1.4:
        return "failed_follow_through"
    return "weak_follow_through"


def _trade_behavior(ret: float, mfe: float, mae: float, hold_seconds: float) -> str:
    if hold_seconds < 900 and ret >= 0.75:
        return "immediate_follow_through"
    if ret <= -1.0 and hold_seconds < 1800:
        return "early_failure"
    if mfe >= 1.0 and abs(mae) >= 1.0:
        return "volatile_but_surviving"
    if ret > 0.2 and mfe >= 0.75:
        return "healthy_continuation"
    if mfe < 0.35 and hold_seconds >= 900:
        return "stalled_after_entry"
    if ret > 0 and hold_seconds >= 1800:
        return "slow_grinder"
    return "weakening_continuation"


def _exit_classification(exit_reason: str, ret: float, peak: float, giveback: float, hold_seconds: float, capture_ratio: float) -> str:
    reason = _to_text(exit_reason).lower()
    if "stop" in reason or ret <= -2.0:
        return "stop_loss_exit"
    if "invalid" in reason:
        return "invalidation_exit"
    if "decay" in reason or "deterioration" in reason or "drawdown" in reason:
        return "momentum_decay_exit"
    if "end_of_day" in reason or "eod" in reason:
        return "end_of_day_exit"
    if "volatility" in reason:
        return "volatility_exit"
    if ret > 0 and capture_ratio >= 0.72:
        return "profit_protection_exit"
    if peak >= 1.2 and giveback >= max(0.8, peak * 0.55):
        return "overstayed_exit"
    if hold_seconds < 900 and peak >= 1.0 and ret < peak * 0.35:
        return "premature_exit"
    if ret > 0 and peak >= 0.75:
        return "healthy_continuation_exit"
    return "unknown_exit"


class TradeLifecycleExcursionV1:
    """Append-only paper lifecycle telemetry for MFE/MAE, hold-time, and exit labels.

    This class is intentionally observational. It never submits orders, cancels orders,
    changes exits, or mutates broker state.
    """

    def __init__(self, state_dir: str = "state", state_path: str | None = None, ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.state_path = str(state_path or os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl"))
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write_by_lifecycle: dict[str, float] = {}

    def _latest_by_lifecycle(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _tail_jsonl(self.state_path):
            lifecycle_id = _to_text(row.get("lifecycle_id"))
            if lifecycle_id:
                latest[lifecycle_id] = row
        return latest

    def _append(self, row: dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def _row_identity(self, row: dict[str, Any]) -> tuple[str, str, str]:
        symbol = _to_text(row.get("symbol")).upper()
        entry_ts = _to_text(row.get("entry_timestamp") or row.get("created_at") or row.get("timestamp") or _now_iso())
        lifecycle_id = _to_text(row.get("lifecycle_id") or row.get("position_id") or row.get("trade_id") or f"{symbol}:{entry_ts}")
        return lifecycle_id, symbol, entry_ts

    def _build_record(
        self,
        paper_row: dict[str, Any],
        latest_row: dict[str, Any] | None = None,
        *,
        closed: bool = False,
        exit_reason: str = "",
        source_endpoint: str = "paper_autopilot",
    ) -> dict[str, Any] | None:
        latest_row = dict(latest_row or {})
        notes = _safe_json_load(paper_row.get("lifecycle_notes"))
        entry_payload = _safe_json_load(paper_row.get("row_json"))
        lifecycle_id, symbol, entry_ts = self._row_identity(paper_row)
        if not symbol:
            return None

        entry_price = _to_float(paper_row.get("entry_price"), _to_float(entry_payload.get("entry_price"), 0.0))
        entry_price_verified = bool(
            paper_row.get("entry_price_verified")
            if paper_row.get("entry_price_verified") is not None
            else entry_payload.get("entry_price_verified", False)
        )
        entry_price_source = _to_text(
            paper_row.get("entry_price_source") or entry_payload.get("entry_price_source"),
            "ENTRY_PRICE_UNAVAILABLE",
        )
        entry_price_evidence_class = _to_text(
            paper_row.get("entry_price_evidence_class") or entry_payload.get("entry_price_evidence_class"),
            "ENTRY_PRICE_UNAVAILABLE",
        )
        entry_price_lineage_status = _to_text(
            paper_row.get("entry_price_lineage_status") or entry_payload.get("entry_price_lineage_status"),
            "ENTRY_PRICE_UNAVAILABLE",
        )
        entry_price_lineage_reason = _to_text(
            paper_row.get("entry_price_lineage_reason") or entry_payload.get("entry_price_lineage_reason"),
            "entry_price_lineage_not_recorded",
        )
        provisional_entry_price = _to_float(
            paper_row.get("provisional_entry_price"),
            _to_float(entry_payload.get("provisional_entry_price"), 0.0),
        )
        broker_filled_avg_price = _to_float(
            paper_row.get("broker_filled_avg_price"),
            _to_float(entry_payload.get("broker_filled_avg_price"), 0.0),
        )
        current_price = _to_float(
            latest_row.get("price"),
            _to_float(
                latest_row.get("current_price"),
                _to_float(paper_row.get("exit_price"), _to_float(notes.get("current_price"), entry_price)),
            ),
        )
        if entry_price <= 0.0 or current_price <= 0.0:
            return None

        now_iso = _now_iso()
        current_ts = _to_text(latest_row.get("timestamp") or latest_row.get("current_timestamp") or now_iso)
        exit_ts = _to_text(paper_row.get("exit_timestamp") or (current_ts if closed else ""))
        entry_epoch = _parse_ts(entry_ts)
        current_epoch = _parse_ts(exit_ts or current_ts or now_iso) or time.time()
        hold_seconds = max(0.0, current_epoch - entry_epoch) if entry_epoch > 0 else _to_float(paper_row.get("hold_seconds"), 0.0)

        previous = self._latest_by_lifecycle().get(lifecycle_id, {})
        best_price = max(
            _to_float(previous.get("best_price_seen"), entry_price),
            _to_float(notes.get("best_price_seen"), entry_price),
            _to_float(notes.get("current_price"), entry_price),
            current_price,
            entry_price,
        )
        worst_price = min(
            _to_float(previous.get("worst_price_seen"), entry_price),
            _to_float(notes.get("worst_price_seen"), entry_price),
            _to_float(notes.get("current_price"), entry_price),
            current_price,
            entry_price,
        )
        current_return = _pct(current_price, entry_price)
        mfe = max(_to_float(previous.get("max_favorable_excursion_pct"), _pct(best_price, entry_price)), _pct(best_price, entry_price), current_return)
        mae = min(_to_float(previous.get("max_adverse_excursion_pct"), _pct(worst_price, entry_price)), _pct(worst_price, entry_price), current_return)
        peak = max(0.0, mfe)
        giveback = max(0.0, peak - current_return)
        previous_ts = _parse_ts(previous.get("last_update_timestamp") or entry_ts) or entry_epoch
        elapsed_since_previous = max(1.0, current_epoch - previous_ts) if current_epoch > 0 else 1.0
        previous_return = _to_float(previous.get("current_return_pct"), _pct(entry_price, entry_price))
        continuation_velocity = (current_return - previous_return) / elapsed_since_previous * 60.0
        adverse_velocity = min(0.0, continuation_velocity)

        if mfe > _to_float(previous.get("max_favorable_excursion_pct"), -999.0):
            time_to_mfe = hold_seconds
        else:
            time_to_mfe = _to_float(previous.get("time_to_mfe_seconds"), 0.0)
        if mae < _to_float(previous.get("max_adverse_excursion_pct"), 999.0):
            time_to_mae = hold_seconds
        else:
            time_to_mae = _to_float(previous.get("time_to_mae_seconds"), 0.0)

        follow_label = _follow_label(current_return, mfe, mae, hold_seconds, continuation_velocity)
        behavior = _trade_behavior(current_return, mfe, mae, hold_seconds)
        capture_ratio = (max(0.0, current_return) / peak) if peak > 0.0 else 0.0
        exit_label = "unknown_exit"
        exit_quality = 0.0
        exit_efficiency = 0.0
        missed_profit = 0.0
        avoidable_loss = 0.0
        explanation = "Trade remains active; exit classification will be assigned when it closes naturally."
        if closed:
            exit_label = _exit_classification(exit_reason, current_return, peak, giveback, hold_seconds, capture_ratio)
            missed_profit = giveback
            avoidable_loss = max(0.0, abs(current_return) - abs(mae)) if current_return < 0 else 0.0
            exit_quality = max(0.0, min(100.0, (capture_ratio * 70.0) + (20.0 if current_return > 0 else 0.0) + (10.0 if giveback <= 0.5 else 0.0)))
            exit_efficiency = max(0.0, min(100.0, exit_quality - max(0.0, giveback * 3.0)))
            explanation = f"{exit_label} from natural close reason '{_to_text(exit_reason, 'unknown')}'."

        return {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "asset_type": _to_text(paper_row.get("asset_type") or entry_payload.get("asset_type"), "stock"),
            "entry_timestamp": entry_ts,
            "entry_price": _round(entry_price),
            "provisional_entry_price": _round(provisional_entry_price) if provisional_entry_price > 0.0 else None,
            "broker_filled_avg_price": _round(broker_filled_avg_price) if broker_filled_avg_price > 0.0 else None,
            "entry_price_source": entry_price_source,
            "entry_price_evidence_class": entry_price_evidence_class,
            "entry_price_verified": entry_price_verified,
            "entry_price_lineage_status": entry_price_lineage_status,
            "entry_price_lineage_reason": entry_price_lineage_reason,
            "entry_order_id": _to_text(paper_row.get("entry_order_id") or paper_row.get("source_broker_order_id") or entry_payload.get("entry_order_id")),
            "entry_fill_id": _to_text(paper_row.get("entry_fill_id") or entry_payload.get("entry_fill_id")),
            "source_client_order_id": _to_text(paper_row.get("source_client_order_id") or entry_payload.get("source_client_order_id")),
            "official_metric_eligible": entry_price_verified,
            "loss_calibration_eligible": entry_price_verified,
            "lifecycle_learning_eligible": entry_price_verified,
            "diagnostic_only": not entry_price_verified,
            "diagnostic_only_reason": "broker_confirmed_entry_price_required" if not entry_price_verified else "",
            "current_timestamp": current_ts,
            "current_price": _round(current_price),
            "current_return_pct": _round(current_return),
            "exit_timestamp": exit_ts if closed else "",
            "exit_price": _round(current_price) if closed else None,
            "max_favorable_excursion_pct": _round(mfe),
            "max_adverse_excursion_pct": _round(mae),
            "time_to_mfe_seconds": _round(time_to_mfe, 2),
            "time_to_mae_seconds": _round(time_to_mae, 2),
            "peak_unrealized_profit_pct": _round(peak),
            "worst_unrealized_drawdown_pct": _round(mae),
            "profit_giveback_pct": _round(giveback),
            "post_entry_continuation_pct": _round(current_return),
            "continuation_velocity": _round(continuation_velocity, 6),
            "adverse_velocity": _round(adverse_velocity, 6),
            "best_price_seen": _round(best_price),
            "worst_price_seen": _round(worst_price),
            "last_price_seen": _round(current_price),
            "last_update_timestamp": now_iso,
            "hold_duration_seconds": _round(hold_seconds, 2),
            "hold_duration_minutes": _round(hold_seconds / 60.0, 2),
            "hold_duration_bucket": _hold_bucket(hold_seconds),
            "time_in_trade_health_label": behavior,
            "early_trade_behavior": behavior if hold_seconds < 1800 else "",
            "mid_trade_behavior": behavior if 1800 <= hold_seconds < 14400 else "",
            "late_trade_behavior": behavior if hold_seconds >= 14400 else "",
            "follow_through_score": _round(max(0.0, min(100.0, 50.0 + current_return * 10.0 + max(0.0, mfe) * 4.0 + mae * 3.0)), 2),
            "follow_through_label": follow_label,
            "continuation_strength": _round(max(0.0, min(100.0, 50.0 + continuation_velocity * 18.0 + max(0.0, current_return) * 8.0)), 2),
            "continuation_decay_score": _round(max(0.0, min(100.0, giveback * 12.0 + max(0.0, -continuation_velocity) * 20.0)), 2),
            "failed_continuation_flag": follow_label == "failed_follow_through",
            "clean_continuation_flag": follow_label in {"strong_follow_through", "moderate_follow_through"} and giveback <= 0.7,
            "continuation_after_entry_pct": _round(current_return),
            "exit_classification": exit_label,
            "exit_quality_score": _round(exit_quality, 2),
            "exit_efficiency_score": _round(exit_efficiency, 2),
            "profit_capture_ratio": _round(capture_ratio, 4),
            "missed_profit_pct": _round(missed_profit),
            "avoidable_loss_pct": _round(avoidable_loss),
            "exit_reason_explanation": explanation,
            "trade_archetype": _to_text(entry_payload.get("trade_archetype") or entry_payload.get("setup_type") or paper_row.get("trade_archetype"), "unknown"),
            "horizon_style": _to_text(entry_payload.get("trade_horizon_style") or entry_payload.get("best_horizon_style") or paper_row.get("trade_horizon_style"), "unknown"),
            "market_regime": _to_text(entry_payload.get("current_market_regime") or entry_payload.get("market_regime") or entry_payload.get("regime_context"), "unknown"),
            "sector": _to_text(entry_payload.get("sector") or paper_row.get("sector"), "unknown"),
            "cap_tier": _to_text(entry_payload.get("candidate_universe_tier") or entry_payload.get("market_cap_category") or paper_row.get("cap_tier"), "unknown"),
            "source_endpoint": _to_text(source_endpoint, "paper_autopilot"),
            "generated_at": now_iso,
            "closed": bool(closed),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
        }

    def record_open_position(self, paper_row: dict[str, Any], latest_row: dict[str, Any] | None = None, *, source_endpoint: str = "paper_autopilot") -> dict[str, Any]:
        record = self._build_record(paper_row, latest_row, closed=False, source_endpoint=source_endpoint)
        if not record:
            return {"ok": False, "reason": "record_unavailable"}
        lifecycle_id = _to_text(record.get("lifecycle_id"))
        now = time.time()
        if lifecycle_id and now - self._last_write_by_lifecycle.get(lifecycle_id, 0.0) < 20.0:
            return {"ok": True, "throttled": True, "record": record}
        self._last_write_by_lifecycle[lifecycle_id] = now
        self._append(record)
        self._cache = None
        return {"ok": True, "record": record}

    def record_closed_position(self, paper_row: dict[str, Any], latest_row: dict[str, Any] | None = None, *, exit_reason: str = "", source_endpoint: str = "paper_autopilot") -> dict[str, Any]:
        record = self._build_record(paper_row, latest_row, closed=True, exit_reason=exit_reason, source_endpoint=source_endpoint)
        if not record:
            return {"ok": False, "reason": "record_unavailable"}
        self._append(record)
        self._cache = None
        return {"ok": True, "record": record}

    def status(self, open_positions: list[dict[str, Any]] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        rows = _tail_jsonl(self.state_path)
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            lifecycle_id = _to_text(row.get("lifecycle_id"))
            if lifecycle_id:
                latest[lifecycle_id] = row
        records = list(latest.values())
        active = [r for r in records if not r.get("closed")]
        closed = [r for r in records if r.get("closed")]
        if open_positions is not None:
            active_symbols = {_to_text(r.get("symbol")).upper() for r in open_positions if isinstance(r, dict)}
            if active_symbols:
                active = [r for r in active if _to_text(r.get("symbol")).upper() in active_symbols]

        def avg(key: str, source: list[dict[str, Any]] | None = None) -> float | None:
            vals = [_to_float(r.get(key), 0.0) for r in (source or records) if r.get(key) not in (None, "")]
            return round(mean(vals), 4) if vals else None

        exit_dist = Counter(_to_text(r.get("exit_classification"), "unknown_exit") for r in closed)
        follow_dist = Counter(_to_text(r.get("follow_through_label"), "insufficient_time") for r in records)
        contexts: dict[str, list[float]] = defaultdict(list)
        for r in records:
            key = f"{_to_text(r.get('sector'), 'unknown')}:{_to_text(r.get('cap_tier'), 'unknown')}:{_to_text(r.get('horizon_style'), 'unknown')}"
            contexts[key].append(_to_float(r.get("follow_through_score"), 0.0))
        ranked_contexts = sorted(
            ((mean(v), k) for k, v in contexts.items() if v),
            key=lambda item: item[0],
            reverse=True,
        )
        evidence_count = len(records)
        closed_count = len(closed)
        learning_ready = bool(closed_count >= 3 or evidence_count >= 8)
        maturity = "healthy" if learning_ready else ("warming_up" if evidence_count else "awaiting_lifecycle_outcomes")
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_lifecycle_observability",
            "trade_lifecycle_excursion_status_v1": True,
            "tracked_active_trades": int(len(active)),
            "tracked_closed_trades": int(closed_count),
            "total_tracked_lifecycles": int(evidence_count),
            "average_mfe_pct": avg("max_favorable_excursion_pct"),
            "average_mae_pct": avg("max_adverse_excursion_pct"),
            "average_profit_giveback_pct": avg("profit_giveback_pct"),
            "average_hold_duration_minutes": avg("hold_duration_minutes"),
            "follow_through_quality_score": avg("follow_through_score"),
            "exit_quality_score": avg("exit_quality_score", closed),
            "profit_capture_quality": avg("profit_capture_ratio", closed),
            "exit_label_distribution": dict(exit_dist),
            "follow_through_distribution": dict(follow_dist),
            "strongest_follow_through_context": ranked_contexts[0][1] if ranked_contexts else "insufficient_evidence",
            "weakest_follow_through_context": ranked_contexts[-1][1] if ranked_contexts else "insufficient_evidence",
            "premature_exit_count": int(exit_dist.get("premature_exit", 0)),
            "overstayed_exit_count": int(exit_dist.get("overstayed_exit", 0)),
            "learning_ready": learning_ready,
            "maturity": maturity,
            "summary": (
                f"Tracking {len(active)} active and {closed_count} closed paper lifecycles for excursion, hold-time, "
                "follow-through, and natural exit labeling."
            ),
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "broker_behavior_changed": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
