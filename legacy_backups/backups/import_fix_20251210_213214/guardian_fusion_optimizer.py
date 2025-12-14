import json
import os
from datetime import datetime


class GuardianFusionOptimizer:
    """
    Guardian Fusion Optimizer
    Dynamically normalizes agent weights, computes confidence deltas,
    and logs all fusion calibration runs for Guardian analysis.
    """

    def __init__(self, log_path="fusion_performance_log.json"):
        self.log_path = log_path
        self.history = self._load_history()

    def _load_history(self):
        if os.path.exists(self.log_path):
            with open(self.log_path, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return []
        return []

    def optimize(self, fusion_output):
        """
        Takes the raw fusion output (signal, confidence, weights)
        and produces a Guardian-optimized result.
        """
        signal = fusion_output.get("signal", 0.0)
        confidence = fusion_output.get("confidence", 0.0)
        weights = fusion_output.get("weights", {})

        # Normalize weights to sum to 1
        total_weight = sum(weights.values()) or 1.0
        normalized_weights = {k: v / total_weight for k, v in weights.items()}

        # Adaptive confidence adjustment
        prev_conf = self.history[-1]["confidence"] if self.history else confidence
        confidence_delta = confidence - prev_conf
        adjusted_conf = max(0.0, min(1.0, confidence + confidence_delta * 0.2))

        # Store results
        optimized = {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "signal": round(signal, 6),
            "confidence": round(adjusted_conf, 6),
            "weights": normalized_weights,
            "confidence_delta": round(confidence_delta, 6),
        }

        # Append to history and persist
        self.history.append(optimized)
        with open(self.log_path, "w") as f:
            json.dump(self.history, f, indent=2)

        print(
            f"[Guardian Fusion Optimizer] ✅ Run logged | Confidence Δ: {confidence_delta:+.6f}"
        )
        return optimized
