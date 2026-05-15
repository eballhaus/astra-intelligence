"""Astra Remote Copilot V1.

Read-only mobile dashboard and lightweight local Q&A. This module uses caller-
provided local state only; it never places trades or calls external services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _rows_from_top_buys(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = payload if isinstance(payload, dict) else {}
    rows = ((data.get("stocks") or {}).get("final") or [])
    if not isinstance(rows, list) or not rows:
        rows = (((data.get("top_action_views") or {}).get("canonical_release_views") or {}).get("stocks_released_hero_buys") or [])
    if not isinstance(rows, list) or not rows:
        rows = (((data.get("top_action_views") or {}).get("canonical_decision_views") or {}).get("stocks_buy_candidates") or [])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append({
            "symbol": symbol,
            "price": row.get("price") or row.get("current_price") or row.get("last_price"),
            "confidence": _to_float(row.get("confidence"), row.get("buy_confidence") or 0.0),
            "buy_quality_score": _to_float(row.get("buy_quality_score"), row.get("trade_quality_score") or row.get("quality_score") or 0.0),
            "grade": row.get("grade") or row.get("buy_grade") or row.get("qualification") or "N/A",
            "reason": row.get("why_this_is_a_buy") or row.get("rationale") or row.get("buy_reason") or "Top ranked current candidate.",
            "timestamp": row.get("timestamp") or row.get("updated_at") or row.get("last_quote_utc") or "",
        })
        if len(out) >= 6:
            break
    return out


def _normalize_positions(rows: Any) -> list[dict[str, Any]]:
    if isinstance(rows, dict):
        rows = rows.get("positions") or rows.get("open_positions") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        if not symbol:
            continue
        out.append({
            "symbol": symbol,
            "status": row.get("status") or row.get("position_status") or "open",
            "entry_price": row.get("entry_price") or row.get("avg_entry_price") or row.get("average_entry_price"),
            "current_price": row.get("current_price") or row.get("price") or row.get("mark_price"),
            "pnl_percent": _to_float(row.get("pnl_percent"), row.get("unrealized_pnl_percent") or 0.0),
            "management_note": row.get("management_note") or row.get("exit_hint") or row.get("rationale") or "Open position monitoring only.",
        })
    return out


class RemoteCopilot:
    """Builds read-only mobile summaries and concise local answers."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "version": VERSION,
            "remote_copilot_status_v1": True,
            "mode": "read_only_mobile_monitoring",
            "read_only": True,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "trading_execution_enabled": False,
            "tailscale_ready": True,
            "ask_astra_enabled": True,
            "mobile_sections": ["top_6_picks", "open_positions", "learning_snapshot", "ask_astra"],
            "advanced_institutional_metrics_on_mobile": False,
            "generated_at": _now_iso(),
        }

    def mobile_dashboard(self, top_buys: dict[str, Any] | None = None, positions: Any = None, learning_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = learning_snapshot if isinstance(learning_snapshot, dict) else {}
        return {
            "enabled": True,
            "version": VERSION,
            "mobile_dashboard_v1": True,
            "mode": "read_only_mobile_monitoring",
            "read_only": True,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "top_6_picks": _rows_from_top_buys(top_buys),
            "open_positions": _normalize_positions(positions),
            "learning_snapshot": {
                "released_wr": _to_float(snap.get("current_engine_released_wr"), 0.0),
                "entry_quality": _to_float(snap.get("entry_quality"), 0.0),
                "buy_list_purity": _to_float(snap.get("buy_list_purity"), 0.0),
                "follow_through_quality": _to_float(snap.get("follow_through_quality"), 0.0),
                "exit_quality": _to_float(snap.get("exit_quality"), 0.0),
                "runtime_stability": _to_float(snap.get("runtime_learning_stability"), 0.0),
                "current_trend": str(snap.get("current_trend") or "unknown"),
                "biggest_weakness": str(snap.get("biggest_weakness") or "insufficient_data"),
                "strongest_area": str(snap.get("strongest_area") or "insufficient_data"),
                "operating_posture": str(snap.get("operating_posture") or "guarded"),
            },
            "ask_astra_examples": [
                "How is Astra performing today?",
                "What is the biggest weakness right now?",
                "How many trades has Astra learned from?",
                "Why is Astra in defensive mode?",
                "What has improved this week?",
            ],
        }

    def answer(self, question: str, mobile_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        q = str(question or "").strip()
        payload = mobile_payload if isinstance(mobile_payload, dict) else {}
        snap = payload.get("learning_snapshot") if isinstance(payload.get("learning_snapshot"), dict) else {}
        top_count = len(payload.get("top_6_picks") or [])
        pos_count = len(payload.get("open_positions") or [])
        trend = str(snap.get("current_trend") or "unknown").replace("_", " ")
        weakness = str(snap.get("biggest_weakness") or "insufficient data").replace("_", " ")
        posture = str(snap.get("operating_posture") or "guarded").replace("_", " ")
        released_wr = _to_float(snap.get("released_wr"), 0.0)
        entry_quality = _to_float(snap.get("entry_quality"), 0.0)
        purity = _to_float(snap.get("buy_list_purity"), 0.0)
        q_lower = q.lower()
        if "weakness" in q_lower:
            answer = f"The biggest current weakness is {weakness}. Entry quality is {entry_quality:.1f} and buy-list purity is {purity:.1f}, so that is where Astra should keep watching pressure first."
        elif "defensive" in q_lower or "mode" in q_lower:
            answer = f"Astra's current posture is {posture}. It stays guarded when learning quality, runtime stability, or follow-through evidence is not strong enough to justify a more aggressive stance."
        elif "learned" in q_lower or "trades" in q_lower:
            answer = f"The mobile snapshot is tracking {pos_count} open positions and {top_count} current top picks. Detailed lifetime trade counts stay in the learning tab, while this view stays intentionally lightweight."
        elif "improved" in q_lower or "week" in q_lower:
            answer = f"The current trend is {trend}. The strongest visible areas are released win rate at {released_wr:.1f}% and buy-list purity at {purity:.1f}."
        else:
            answer = f"Astra is online in read-only mode with {top_count} top stock picks and {pos_count} open positions visible. Released win rate is {released_wr:.1f}%, entry quality is {entry_quality:.1f}, and the current trend is {trend}."
        return {
            "enabled": True,
            "version": VERSION,
            "ask_astra_v1": True,
            "read_only": True,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "question": q,
            "answer": answer,
            "generated_at": _now_iso(),
        }
