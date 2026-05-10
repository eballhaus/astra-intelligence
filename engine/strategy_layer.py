from __future__ import annotations

from datetime import UTC, datetime


class StrategyLayer:
    def __init__(self, *args, **kwargs):
        self.stop_loss_pct = float(kwargs.get("stop_loss_pct", 0.025))
        self.take_profit_pct = float(kwargs.get("take_profit_pct", 0.05))

    def run_backtest(self, *args, **kwargs) -> dict:
        return {
            "ok": True,
            "mode": "compatibility_stub",
            "total_trades": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def run_walkforward_validation(self, *args, **kwargs) -> dict:
        return {
            "ok": True,
            "mode": "compatibility_stub",
            "windows": [],
            "summary": {"win_rate": 0.0, "avg_return": 0.0},
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

