from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

TRADE_LIFECYCLE_PATH = os.path.join("state", "trade_lifecycle_v1.jsonl")
_LOCK = threading.Lock()
_LATEST_RECORD_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_LATEST_RECORD_CACHE_SIGNATURES: dict[str, tuple[int, int, int]] = {}


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
        # These are observational close-time facts.  They preserve the
        # canonical excursion evidence without participating in exit logic.
        "peak_return_percent": _to_float(data.get("peak_return_percent"), 0.0),
        "drawdown_from_peak_percent": _to_float(data.get("drawdown_from_peak_percent"), 0.0),
        "hold_time_seconds": _to_float(data.get("hold_time_seconds"), 0.0),
        "mfe_evidence_available": bool(data.get("mfe_evidence_available", False)),
        "mae_evidence_available": bool(data.get("mae_evidence_available", False)),
        "exit_quality_score": (
            _to_float(data.get("exit_quality_score"), 0.0)
            if data.get("exit_quality_score") not in (None, "") else None
        ),
        "exit_quality_evidence_available": bool(data.get("exit_quality_evidence_available", False)),
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
        "updated_at": _to_str(data.get("updated_at"), _now_iso()),
    }
    # Lifecycle rows are append-only evidence.  Preserve the canonical lane
    # contract from the paper-entry bridge without using it to drive exits.
    for key, default in (
        ("lane_id", ""),
        ("trade_style", ""),
        ("intended_horizon", ""),
        ("asset_class", ""),
        ("strategy_cohort", ""),
        ("recommendation_id", ""),
        ("candidate_id", ""),
        ("decision_timestamp", ""),
        ("eligibility_timestamp", ""),
        ("selection_timestamp", ""),
        ("expected_max_hold", ""),
        ("same_session_exit_required", False),
        ("overnight_allowed", False),
        ("capital_book_id", ""),
        ("source_ranking_version", ""),
        ("source_policy_version", ""),
        ("entry_order_id", ""),
        ("entry_fill_id", ""),
        ("exit_order_id", ""),
        ("exit_fill_id", ""),
        ("source_client_order_id", ""),
    ):
        if isinstance(default, bool):
            record[key] = bool(data.get(key, default))
        else:
            record[key] = _to_str(data.get(key), default)
    if not record["lifecycle_id"]:
        record["lifecycle_id"] = build_lifecycle_id(record)
    if record["current_price"] <= 0.0 and record["entry_price"] > 0.0:
        record["current_price"] = record["entry_price"]
    return record


def _path_signature(path: str) -> tuple[int, int, int] | None:
    try:
        stat = os.stat(path)
        return (int(stat.st_ino), int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        return None


def _append_record(record: dict[str, Any]) -> None:
    path = os.path.abspath(TRADE_LIFECYCLE_PATH)
    before_signature = _path_signature(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
    cached = _LATEST_RECORD_CACHE.get(path)
    cached_signature = _LATEST_RECORD_CACHE_SIGNATURES.get(path)
    if cached is not None and cached_signature == before_signature:
        lifecycle_id = _to_str(record.get("lifecycle_id"))
        if lifecycle_id:
            cached[lifecycle_id] = dict(record)
        _LATEST_RECORD_CACHE_SIGNATURES[path] = _path_signature(path) or cached_signature
    elif cached is not None:
        _LATEST_RECORD_CACHE.pop(path, None)
        _LATEST_RECORD_CACHE_SIGNATURES.pop(path, None)


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


def _scan_latest_record_map(path: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    if not os.path.exists(path):
        return latest
    try:
        with open(path, "r", encoding="utf-8") as fh:
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


def _latest_record_map() -> dict[str, dict[str, Any]]:
    path = os.path.abspath(TRADE_LIFECYCLE_PATH)
    signature = _path_signature(path)
    cached = _LATEST_RECORD_CACHE.get(path)
    if cached is not None and signature == _LATEST_RECORD_CACHE_SIGNATURES.get(path):
        return cached
    latest = _scan_latest_record_map(path)
    _LATEST_RECORD_CACHE[path] = latest
    _LATEST_RECORD_CACHE_SIGNATURES[path] = _path_signature(path) or signature or (0, 0, 0)
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
