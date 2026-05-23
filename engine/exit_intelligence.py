from __future__ import annotations

from datetime import UTC, datetime

try:
    from engine.trade_management_portfolio_intelligence_v1 import TradeManagementPortfolioIntelligenceV1
except Exception:  # pragma: no cover - additive shadow diagnostics
    TradeManagementPortfolioIntelligenceV1 = None  # type: ignore[assignment]


class ExitIntelligenceEngine:
    def __init__(self, *args, **kwargs):
        state_dir = str(kwargs.get("state_dir") or "state")
        self.trade_management_suite = kwargs.get("trade_management_suite")
        if self.trade_management_suite is None and TradeManagementPortfolioIntelligenceV1 is not None:
            try:
                self.trade_management_suite = TradeManagementPortfolioIntelligenceV1(state_dir=state_dir)
            except Exception:
                self.trade_management_suite = None

    def evaluate_open_trades(self, open_trades, live_perf=None) -> dict:
        rows = list(open_trades or [])
        if self.trade_management_suite is not None and hasattr(self.trade_management_suite, "evaluate_open_trades"):
            try:
                out = dict(self.trade_management_suite.evaluate_open_trades(rows, live_perf=live_perf or {}) or {})
                out.setdefault("ok", True)
                out.setdefault("count", len(rows))
                out.setdefault("alerts", [])
                out.setdefault("live_performance", live_perf or {})
                out.setdefault("last_updated_utc", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
                return out
            except Exception:
                pass
        return {
            "ok": True,
            "count": len(rows),
            "alerts": [],
            "live_performance": live_perf or {},
            "trade_management_shadow_only": True,
            "portfolio_intelligence_shadow_only": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
