"""Adaptive Quote Refresh V1.

Status/planning engine for tiered quote refresh. It never starts loops and never
calls providers; it reports what should refresh and when.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

VERSION = "1.0.0"


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _sym(row: dict[str, Any]) -> str:
    return str((row or {}).get("symbol") or (row or {}).get("ticker") or "").upper().strip()


class AdaptiveQuoteRefreshPlanner:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "planning_only_no_polling_loop"
        self.refresh_tiers = {
            "critical_active_position": "websocket preferred, REST fallback 15-30s max",
            "normal_active_position": "websocket preferred, REST fallback 30-60s",
            "top_6_stable_buy_list": "2-5 minutes during market hours, slower after-hours/weekends",
            "active_universe_200": "15-60 minutes depending on market and budget",
            "broad_universe_7500": "daily/staged/delta-only/background, no frequent live refresh",
            "learning_snapshot": "full 6h, light 15-30m, change-aware",
            "advanced_metrics": "6-12h or source fingerprint change",
        }

    def status(
        self,
        *,
        positions: list[dict[str, Any]] | None = None,
        stable_top_buys: dict[str, Any] | None = None,
        websocket_status: dict[str, Any] | None = None,
        market_status: str = "unknown",
        budget_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        position_rows = [dict(r or {}) for r in list(positions or []) if isinstance(r, dict)]
        stable = stable_top_buys if isinstance(stable_top_buys, dict) else {}
        top_rows = [dict(r or {}) for r in list(stable.get("stable_top_6") or []) if isinstance(r, dict)]
        position_symbols = [_sym(r) for r in position_rows if _sym(r)]
        top_symbols = [_sym(r) for r in top_rows if _sym(r)]
        ws = websocket_status if isinstance(websocket_status, dict) else {}
        ws_symbols = set()
        for value in (ws.get("symbols"), ws.get("configured_symbols"), ws.get("subscribed_symbols")):
            if isinstance(value, list):
                ws_symbols.update(str(x).upper() for x in value if str(x).strip())
        critical = []
        normal = []
        for row in position_rows:
            sym = _sym(row)
            if not sym:
                continue
            risk = float(row.get("sell_trigger_risk") or row.get("risk_score") or 0.0)
            quote_age = float(row.get("quote_age_seconds") or row.get("freshness_seconds") or 999.0)
            if risk >= 70.0 or quote_age > 60.0:
                critical.append(sym)
            else:
                normal.append(sym)
        top_only = [s for s in top_symbols if s not in set(position_symbols)]
        is_open = str(market_status).lower().endswith("open") or str(market_status).lower() == "market open"
        learning_next = _now() + timedelta(minutes=20)
        advanced_next = _now() + timedelta(hours=6)
        planned_requests = []
        for sym in critical:
            planned_requests.append({"provider": "alpaca_iex", "symbol": sym, "data_type": "active_position_quote", "priority": "critical", "estimated_bytes": 1200})
        for sym in normal:
            planned_requests.append({"provider": "alpaca_iex", "symbol": sym, "data_type": "active_position_quote", "priority": "active_position", "estimated_bytes": 900})
        for sym in top_only:
            planned_requests.append({"provider": "alpaca_iex", "symbol": sym, "data_type": "top_6_quote", "priority": "top_6", "estimated_bytes": 700})
        budget = budget_status if isinstance(budget_status, dict) else {}
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "adaptive_refresh_status_v1": True,
            "market_status": market_status,
            "market_is_open": bool(is_open),
            "refresh_tiers": dict(self.refresh_tiers),
            "active_positions_count": len(position_rows),
            "symbols_fast_refresh": critical,
            "symbols_slow_refresh": normal + top_only,
            "top_6_symbols": top_symbols,
            "active_universe_refresh_interval_seconds": 900 if is_open else 3600,
            "broad_universe_refresh_policy": "daily_or_scheduled_delta_only_no_rapid_polling",
            "websocket_symbols": sorted(ws_symbols.intersection(set(position_symbols))),
            "rest_fallback_symbols": [s for s in position_symbols if s not in ws_symbols],
            "websocket_preferred": True,
            "rest_fallback_only_when_stale_or_ws_missing": True,
            "planned_refresh_requests": planned_requests,
            "api_calls_used": 0,
            "calls_blocked": int(budget.get("calls_blocked") or 0),
            "bandwidth_estimate": int(budget.get("bandwidth_estimate") or sum(int(r.get("estimated_bytes") or 0) for r in planned_requests)),
            "next_learning_refresh": learning_next.isoformat().replace("+00:00", "Z"),
            "next_advanced_refresh": advanced_next.isoformat().replace("+00:00", "Z"),
            "ui_snapshot_first": True,
            "broad_universe_rapid_polling_enabled": False,
            "duplicate_provider_calls_allowed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "future_worker_should_execute_only_budget_allowed_requests_off_the_ui_path",
        }
