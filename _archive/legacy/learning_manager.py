from learning.learning_engine import learning_signal
import json, os
from datetime import datetime, timezone
from learning.learning_engine import LearningEngine

def start_background_learning(test_mode=False):
    """Runs a single learning update and logs metrics to state/learning_metrics.json"""
    # Run the learning signal or training step
    metrics = learning_signal()

    # Ensure metrics is always a dictionary
    if not isinstance(metrics, dict):
        metrics = {"avg_reward": float(metrics)}

    # Add timestamp
    metrics["timestamp"] = datetime.now(timezone.utc).isoformat()

    metrics_path = os.path.join("state", "learning_metrics.json")

    # Load existing data if present
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    else:
        existing = []

    # Convert single dict to list if needed
    if isinstance(existing, dict):
        existing = [existing]

    # Append and trim to last 25 cycles
    existing.append(metrics)
    existing = existing[-25:]

    # Save updated list
    with open(metrics_path, "w") as f:
        json.dump(existing, f, indent=2)

    print("[Astra LearningManager] ✅ Logged new metrics cycle")

if __name__ == "__main__":
    start_background_learning(test_mode=True)
