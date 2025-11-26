"""
Astra 7.0 - Performance & Learning Tracker
------------------------------------------
Lightweight event logger so Astra can learn over time.

Stores a rolling history of prediction events in:
    asra_learning.json   (project root)

Used for:
- accuracy tracking
- learning curves
- future reinforcement logic
"""

import json
from pathlib import Path
from datetime import datetime


MEMORY_FILE = "astra_learning.json"
MAX_EVENTS = 2000  # cap to avoid unbounded growth


# -----------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------

def _get_memory_path() -> Path:
    """
    Resolve the JSON file location at the project root
    (same level as app.py).
    """
    # __file__ = .../astra_modules/learning/performance_tracker.py
    # parents[2] -> project root (.. / ..)
    root = Path(__file__).resolve().parents[2]
    return root / MEMORY_FILE


def _load_memory() -> dict:
    path = _get_memory_path()
    if not path.exists():
        return {"events": []}

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if "events" not in data or not isinstance(data["events"], list):
            data["events"] = []
        return data
    except Exception as e:
        print(f"[performance_tracker] load failed: {e}")
        return {"events": []}


def _save_memory(data: dict) -> None:
    path = _get_memory_path()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[performance_tracker] save failed: {e}")


# -----------------------------------------------------------
# Public API
# -----------------------------------------------------------

def record_performance(
    ticker: str,
    mode: str,
    prediction: str,
    confidence: float | int | None,
    actual_outcome: str | None = None,
    profit_pct: float | None = None,
) -> None:
    """
    Append a performance/learning event.

    mode:
        e.g. "scan", "hybrid_swing", "hybrid_day", "forecast"

    prediction:
        "BUY" / "SELL" / "HOLD" (or other labels later)

    actual_outcome:
        e.g. "BUY", "SELL", "HOLD" when you later verify result
        (can be None at first)

    This is intentionally VERY lightweight.
    """
    data = _load_memory()
    events = data.get("events", [])

    evt = {
        "ts": datetime.utcnow().isoformat(),
        "ticker": str(ticker).upper(),
        "mode": str(mode),
        "prediction": str(prediction),
        "confidence": float(confidence) if confidence is not None else None,
        "outcome": actual_outcome,
        "profit_pct": profit_pct,
    }

    events.append(evt)

    # keep only last MAX_EVENTS
    if len(events) > MAX_EVENTS:
        events = events[-MAX_EVENTS:]

    data["events"] = events
    _save_memory(data)


def get_accuracy_stats(window: int = 200) -> dict:
    """
    Returns a high-level summary:

    {
      "total": total_events,
      "with_outcome": n_with_outcome,
      "correct": n_correct,
      "accuracy": float or None
    }
    """
    data = _load_memory()
    events = data.get("events", [])

    if not events:
        return {
            "total": 0,
            "with_outcome": 0,
            "correct": 0,
            "accuracy": None,
        }

    # last `window` events that actually have an outcome
    with_outcome = [e for e in events if e.get("outcome") is not None][-window:]
    n_with_outcome = len(with_outcome)

    if n_with_outcome == 0:
        return {
            "total": len(events),
            "with_outcome": 0,
            "correct": 0,
            "accuracy": None,
        }

    correct = sum(1 for e in with_outcome if e.get("outcome") == e.get("prediction"))
    accuracy = correct / n_with_outcome if n_with_outcome else None

    return {
        "total": len(events),
        "with_outcome": n_with_outcome,
        "correct": correct,
        "accuracy": accuracy,
    }


def get_learning_curve_points(window: int = 200) -> list[dict]:
    """
    Returns data for plotting Astra's improvement over time.

    Output:
        [
          {"index": 1, "accuracy": 0.50},
          {"index": 2, "accuracy": 0.60},
          ...
        ]
    """
    data = _load_memory()
    events = [e for e in data.get("events", []) if e.get("outcome") is not None]

    if not events:
        return []

    events = events[-window:]
    points = []
    correct = 0

    for i, e in enumerate(events, start=1):
        if e.get("outcome") == e.get("prediction"):
            correct += 1
        points.append({
            "index": i,
            "accuracy": correct / i
        })

    return points
