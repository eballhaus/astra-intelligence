"""
metrics_engine_v2.py – Phase 2.6 Metrics Engine
------------------------------------------------
Computes trading performance metrics from realized trade exits only.

✅ Reads:
    - paper_trades.json (open trades)
    - trade_history.json (closed trades with realized P/L)
✅ Writes:
    - performance_metrics.json (append-only)
"""

import json, os, time
from datetime import datetime

DATA_PATH = "data"
PAPER_TRADES_FILE = os.path.join(DATA_PATH, "paper_trades.json")
TRADE_HISTORY_FILE = os.path.join(DATA_PATH, "trade_history.json")
METRICS_FILE = os.path.join(DATA_PATH, "performance_metrics.json")

def safe_load(path):
    """Safely load JSON file if it exists."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []

def append_metrics(data):
    """Append new metrics snapshot to metrics file."""
    existing = safe_load(METRICS_FILE)
    if not isinstance(existing, list):
        existing = []
    existing.append(data)
    with open(METRICS_FILE, "w") as f:
        json.dump(existing, f, indent=2)

def run_metrics_engine():
    """Compute Phase 2.6 metrics from realized exits only."""
    try:
        trade_history = safe_load(TRADE_HISTORY_FILE)
        paper_trades = safe_load(PAPER_TRADES_FILE)
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        total_trades = len(paper_trades)
        realized = [t for t in trade_history if "pnl" in t]

        if not realized:
            data = {
                "timestamp": timestamp,
                "total_trades": total_trades,
                "realized_trades": 0,
                "status": "insufficient data"
            }
            append_metrics(data)
            print("[MetricsEngine] No realized trades yet – metrics placeholder written.")
            return

        pnl_values = [t["pnl"] for t in realized if isinstance(t.get("pnl"), (int, float))]
        wins = [p for p in pnl_values if p > 0]
        losses = [p for p in pnl_values if p < 0]

        win_rate = len(wins) / len(pnl_values) if pnl_values else 0
        loss_rate = len(losses) / len(pnl_values) if pnl_values else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        expectancy = (avg_win * win_rate) + (avg_loss * loss_rate)

        metrics_snapshot = {
            "timestamp": timestamp,
            "total_trades": total_trades,
            "realized_trades": len(realized),
            "win_rate": round(win_rate, 3),
            "loss_rate": round(loss_rate, 3),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "expectancy": round(expectancy, 4),
            "status": "active"
        }

        append_metrics(metrics_snapshot)
        print(f"[MetricsEngine] Metrics updated at {timestamp} ✅")

    except Exception as e:
        print(f"[MetricsEngine] Error: {e}")

if __name__ == "__main__":
    run_metrics_engine()
