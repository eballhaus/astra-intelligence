# Astra Performance System — tab_performance.py
"""
Astra Intelligence — Performance Dashboard Tab
----------------------------------------------
Displays key metrics: accuracy, returns, profit factor, Sharpe-like score,
and recent trade table.
"""

from performance.accuracy_engine import AccuracyEngine
from performance.performance_logger import PerformanceLogger


def render_performance_tab():
    logger = PerformanceLogger()
    engine = AccuracyEngine()

    history = logger.data.get("history", [])
    summary = engine.summarize(history)

    print("=== Astra Performance Summary ===")
    for k, v in summary.items():
        print(f"{k:15}: {v}")
    print("\nRecent Trades (last 5):")
    for trade in history[-5:]:
        print(
            f"{trade['ticker']} | {trade['direction']} | "
            f"{round(trade['return_pct']*100,2)}% | {'WIN' if trade['correct'] else 'LOSS'}"
        )


if __name__ == "__main__":
    render_performance_tab()
