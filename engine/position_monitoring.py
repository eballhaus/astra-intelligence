"""Position Monitoring V1.

Read-only position risk tiering for adaptive quote refresh planning.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

try:
    from engine.exit_averaging_engine import ExitAveragingEngine
except Exception:  # pragma: no cover
    ExitAveragingEngine = None  # type: ignore[assignment]

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _sym(row: dict[str, Any]) -> str:
    return str((row or {}).get("symbol") or (row or {}).get("ticker") or "").upper().strip()


class PositionMonitoringPlanner:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "read_only_monitoring_plan"
        self.exit_engine = ExitAveragingEngine(state_dir=self.state_dir) if ExitAveragingEngine else None

    def status(self, *, positions: list[dict[str, Any]] | None = None, websocket_status: dict[str, Any] | None = None, market_status: str = "unknown") -> dict[str, Any]:
        rows = [dict(r or {}) for r in list(positions or []) if isinstance(r, dict)]
        ws_symbols = set()
        ws = websocket_status if isinstance(websocket_status, dict) else {}
        for value in (ws.get("symbols"), ws.get("configured_symbols"), ws.get("subscribed_symbols")):
            if isinstance(value, list):
                ws_symbols.update(str(x).upper() for x in value if str(x).strip())
        critical: list[str] = []
        normal: list[str] = []
        details: list[dict[str, Any]] = []
        for row in rows:
            symbol = _sym(row)
            if not symbol:
                continue
            price = _f(row.get("current_price"), _f(row.get("price"), _f(row.get("mark_price"), 0.0)))
            stop = _f(row.get("stop_loss"), _f(row.get("stop"), 0.0))
            target = _f(row.get("target_price"), _f(row.get("take_profit"), 0.0))
            distance_stop_pct = ((price - stop) / price * 100.0) if price > 0 and stop > 0 else None
            distance_target_pct = ((target - price) / price * 100.0) if price > 0 and target > 0 else None
            sell_risk = _f(row.get("sell_trigger_risk"), _f(row.get("risk_score"), 0.0))
            near_stop = distance_stop_pct is not None and distance_stop_pct <= 2.5
            near_target = distance_target_pct is not None and distance_target_pct <= 3.0
            is_critical = bool(near_stop or near_target or sell_risk >= 70.0)
            exit_status = {}
            try:
                if self.exit_engine:
                    exit_status = self.exit_engine.score_row(row) or {}
            except Exception as exc:
                exit_status = {"exit_score_available": False, "exit_unavailable_reason": str(exc)[:160]}
            (critical if is_critical else normal).append(symbol)
            details.append({
                "symbol": symbol,
                "tier": "critical_active_position" if is_critical else "normal_active_position",
                "distance_to_stop_pct": round(distance_stop_pct, 3) if distance_stop_pct is not None else None,
                "distance_to_target_pct": round(distance_target_pct, 3) if distance_target_pct is not None else None,
                "sell_trigger_risk": round(sell_risk, 3),
                "quote_freshness": row.get("quote_freshness") or row.get("quote_age_seconds"),
                "last_quote_source": row.get("quote_source") or row.get("provider_used") or row.get("last_quote_source") or "snapshot",
                "websocket_preferred": symbol in ws_symbols,
                "rest_fallback_allowed": symbol not in ws_symbols,
                "exit_score": exit_status.get("exit_score"),
                "averaged_exit_score": exit_status.get("averaged_exit_score"),
                "exit_confirmation_count": exit_status.get("exit_confirmation_count"),
                "pullback_vs_breakdown_label": exit_status.get("pullback_vs_breakdown_label"),
                "trailing_stop_price": exit_status.get("trailing_stop_price"),
                "profit_protection_status": exit_status.get("profit_protection_status"),
                "recommended_sell_zone": exit_status.get("recommended_sell_zone"),
                "sell_reason": exit_status.get("sell_reason"),
                "target_progress_pct": exit_status.get("target_progress_pct"),
            })
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "position_monitoring_status_v1": True,
            "market_status": market_status,
            "active_positions_count": len(rows),
            "symbols_fast_refresh": critical,
            "symbols_slow_refresh": normal,
            "critical_active_position_symbols": critical,
            "normal_active_position_symbols": normal,
            "websocket_symbols": sorted(ws_symbols.intersection(set(critical + normal))),
            "rest_fallback_symbols": [s for s in critical + normal if s not in ws_symbols],
            "api_calls_used": 0,
            "calls_blocked": 0,
            "bandwidth_estimate": 0,
            "monitoring_details": details,
            "next_learning_refresh": None,
            "next_advanced_refresh": None,
            "generated_at": _now_iso(),
            "next_recommended_action": "prioritize_critical_position_quotes_without_touching_broker_execution",
        }
