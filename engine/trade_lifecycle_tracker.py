from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

TRADE_LIFECYCLE_PATH = os.path.join("state", "trade_lifecycle_v1.jsonl")
_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_str(value: Any, default: str = "") -> str:
    out = str(value or default).strip()
    return out if out else str(default)


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_record(data: dict[str, Any]) -> dict[str, Any]:
    record = {
        "lifecycle_id": _to_str(data.get("lifecycle_id")),
        "symbol": _to_str(data.get("symbol")).upper(),
        "asset_type": _to_str(data.get("asset_type"), "stock").lower(),
        "signal_timestamp": _to_str(data.get("signal_timestamp")),
        "release_status": _to_str(data.get("release_status")),
        "entry_timestamp": _to_str(data.get("entry_timestamp")),
        "entry_price": _to_float(data.get("entry_price"), 0.0),
        "current_price": _to_float(data.get("current_price"), 0.0),
        "exit_timestamp": _to_str(data.get("exit_timestamp")),
        "exit_price": _to_float(data.get("exit_price"), 0.0),
        "pnl_pct": _to_float(data.get("pnl_pct"), 0.0),
        "max_favorable_excursion_pct": _to_float(data.get("max_favorable_excursion_pct"), 0.0),
        "max_adverse_excursion_pct": _to_float(data.get("max_adverse_excursion_pct"), 0.0),
        "confidence": _to_float(data.get("confidence"), 0.0),
        "grade": _to_float(data.get("grade"), 0.0),
        "entry_quality_score": _to_float(data.get("entry_quality_score"), 0.0),
        "entry_quality_band": _to_str(data.get("entry_quality_band"), "unknown"),
        "trade_archetype": _to_str(data.get("trade_archetype")),
        "catalyst_context": _to_str(data.get("catalyst_context")),
        "exit_reason": _to_str(data.get("exit_reason")),
        "outcome_label": _to_str(data.get("outcome_label")),
        "source_endpoint": _to_str(data.get("source_endpoint")),
        "lifecycle_stage": _to_str(data.get("lifecycle_stage"), "signal"),
        "learning_acceleration_priority": _to_float(data.get("learning_acceleration_priority"), 0.0),
        "counterfactual_review_needed": bool(data.get("counterfactual_review_needed", False)),
        "target_accuracy_score": _to_float(data.get("target_accuracy_score"), 0.0),
        "exit_quality_score": _to_float(data.get("exit_quality_score"), 0.0),
        "realized_r_multiple": _to_float(data.get("realized_r_multiple"), 0.0),
        "missed_profit_flag": bool(data.get("missed_profit_flag", False)),
        "premature_exit_flag": bool(data.get("premature_exit_flag", False)),
        "late_exit_flag": bool(data.get("late_exit_flag", False)),
        "scale_in_shadow_signal": _to_str(data.get("scale_in_shadow_signal")),
        "scale_out_shadow_signal": _to_str(data.get("scale_out_shadow_signal")),
        "memory_segment_key": _to_str(data.get("memory_segment_key")),
        "updated_at": _to_str(data.get("updated_at"), _now_iso()),
    }
    if not record["lifecycle_id"]:
        record["lifecycle_id"] = build_lifecycle_id(record)
    if record["current_price"] <= 0.0 and record["entry_price"] > 0.0:
        record["current_price"] = record["entry_price"]
    return record


def _append_record(record: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(TRADE_LIFECYCLE_PATH) or ".", exist_ok=True)
    with open(TRADE_LIFECYCLE_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")


def build_lifecycle_id(data: dict[str, Any]) -> str:
    token = "|".join(
        [
            _to_str(data.get("symbol")).upper(),
            _to_str(data.get("signal_timestamp")),
            _to_str(data.get("entry_timestamp")),
            _to_str(data.get("source_endpoint")),
            _to_str(data.get("trade_archetype")),
        ]
    )
    return "tlc_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def create_lifecycle_record(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        rec = _normalize_record(_safe_dict(data))
        rec["lifecycle_stage"] = _to_str(data.get("lifecycle_stage"), "entry")
        rec["updated_at"] = _now_iso()
        _append_record(rec)
        return rec


def _latest_record_map() -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not os.path.exists(TRADE_LIFECYCLE_PATH):
        return latest
    try:
        with open(TRADE_LIFECYCLE_PATH, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict):
                    continue
                rid = _to_str(row.get("lifecycle_id"))
                if rid:
                    latest[rid] = row
    except Exception:
        return latest
    return latest


def update_lifecycle_progress(lifecycle_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        latest = _latest_record_map().get(_to_str(lifecycle_id), {})
        merged = dict(latest)
        merged.update(_safe_dict(updates))
        merged["lifecycle_id"] = _to_str(lifecycle_id) or _to_str(merged.get("lifecycle_id"))
        merged["updated_at"] = _now_iso()
        rec = _normalize_record(merged)
        _append_record(rec)
        return rec


def close_lifecycle_record(lifecycle_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    closure = dict(_safe_dict(updates))
    closure.setdefault("lifecycle_stage", "closed")
    return update_lifecycle_progress(lifecycle_id, closure)


def load_recent_lifecycle_records(limit: int = 200) -> list[dict[str, Any]]:
    with _LOCK:
        latest = _latest_record_map()
    rows = list(latest.values())
    rows.sort(key=lambda r: _to_str(r.get("updated_at")), reverse=True)
    return rows[: max(1, int(limit))]


def summarize_lifecycle_metrics(limit: int = 500) -> dict[str, Any]:
    rows = load_recent_lifecycle_records(limit=limit)
    total = len(rows)
    closed = [r for r in rows if _to_str(r.get("lifecycle_stage")).startswith("closed") or _to_str(r.get("exit_timestamp"))]
    open_rows = [r for r in rows if r not in closed]
    winners = [r for r in closed if _to_float(r.get("pnl_pct"), 0.0) > 0.0]
    losers = [r for r in closed if _to_float(r.get("pnl_pct"), 0.0) < 0.0]
    avg_pnl = sum(_to_float(r.get("pnl_pct"), 0.0) for r in closed) / max(1, len(closed))
    return {
        "enabled": True,
        "state_path": TRADE_LIFECYCLE_PATH,
        "total_trades_tracked": total,
        "open_trades": len(open_rows),
        "closed_trades": len(closed),
        "winners": len(winners),
        "losers": len(losers),
        "win_rate_pct": round((len(winners) / max(1, len(closed))) * 100.0, 2),
        "avg_closed_pnl_pct": round(avg_pnl, 4),
        "last_updated_at": _now_iso(),
    }

class LifecycleAutoTrackingEngine:
    """Local-only lifecycle quality report; no broker interaction or writes."""

    version = "1.0.0"

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")

    def _parse_ts(self, value: Any):
        raw = _to_str(value)
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    def _all_rows(self, limit: int = 5000) -> list[dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        rows: list[dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return rows[-max(1, int(limit)):]

    def status(self) -> dict[str, Any]:
        rows = self._all_rows()
        stage_counts: dict[str, int] = {"entry": 0, "add_reduce": 0, "stop_update": 0, "exit": 0, "post_trade_review": 0}
        closed: list[dict[str, Any]] = []
        quality_scores: list[float] = []
        hold_minutes: list[float] = []
        mfe_values: list[float] = []
        mae_values: list[float] = []
        capture_values: list[float] = []
        drawdown_after_peak: list[float] = []
        for row in rows:
            stage = _to_str(row.get("lifecycle_stage") or row.get("status"), "entry").lower()
            if "add" in stage or "reduce" in stage:
                stage_counts["add_reduce"] += 1
            elif "stop" in stage:
                stage_counts["stop_update"] += 1
            elif "exit" in stage or "closed" in stage:
                stage_counts["exit"] += 1
            elif "review" in stage:
                stage_counts["post_trade_review"] += 1
            else:
                stage_counts["entry"] += 1
            if _to_str(row.get("exit_timestamp")) or stage.startswith("closed") or "exit" in stage:
                closed.append(row)
            entry = self._parse_ts(row.get("entry_timestamp") or row.get("signal_timestamp"))
            exit_ts = self._parse_ts(row.get("exit_timestamp") or row.get("updated_at"))
            if entry is not None and exit_ts is not None:
                hold_minutes.append(max(0.0, (exit_ts.timestamp() - entry.timestamp()) / 60.0))
            mfe = _to_float(row.get("max_favorable_excursion_pct"), 0.0)
            mae = _to_float(row.get("max_adverse_excursion_pct"), 0.0)
            pnl = _to_float(row.get("pnl_pct"), _to_float(row.get("return_pct"), 0.0))
            mfe_values.append(mfe)
            mae_values.append(mae)
            drawdown_after_peak.append(max(0.0, mfe - pnl))
            if abs(mfe) > 0.01:
                capture_values.append(max(0.0, min(2.0, pnl / max(0.01, mfe))))
            quality_scores.append(_to_float(row.get("entry_quality_score"), _to_float(row.get("grade"), 0.0)))
        def avg(values: list[float]) -> float:
            return round(sum(values) / max(1, len(values)), 6) if values else 0.0
        workflow_quality = min(100.0, (len(closed) / max(1, len(rows))) * 60.0 + avg(quality_scores) * 0.4) if rows else 0.0
        confidence = min(95.0, 30.0 + min(50.0, len(closed) * 2.0))
        return {
            "enabled": True,
            "version": self.version,
            "mode": "local_lifecycle_auto_tracking_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "trade_lifecycle_status_v1": True,
            "broker_interaction": False,
            "live_order_execution_enabled": False,
            "total_lifecycle_rows": len(rows),
            "closed_trade_count": len(closed),
            "stage_counts": stage_counts,
            "hold_time_minutes_avg": avg(hold_minutes),
            "max_favorable_excursion_avg": avg(mfe_values),
            "max_adverse_excursion_avg": avg(mae_values),
            "drawdown_after_peak_avg": avg(drawdown_after_peak),
            "capture_ratio_avg": avg(capture_values),
            "entry_to_exit_workflow_quality": round(workflow_quality, 3),
            "confidence_score": round(confidence, 3),
            "planning_only_if_data_insufficient": len(closed) < 30,
            "next_recommended_action": "continue_tracking_full_lifecycle_events_without_broker_interaction" if len(closed) < 30 else "review_capture_ratio_and_workflow_quality_before_policy_changes",
        }
