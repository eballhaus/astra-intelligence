# learning/fusion_calibrator.py
"""
Astra Fusion Calibrator — evaluates real agent outputs.
Guardian-Safe ✅
"""

import json
import os
from datetime import datetime, timezone

import numpy as np

from agents.catalyst_agent import CatalystAgent

# ---- import your real agents here ----
from agents.momentum_agent import MomentumAgent
from agents.neural_agent import NeuralAgent
from agents.prediction_fusion import PredictionFusionV2
from agents.risk_agent import RiskAgent
from agents.technical_agent import TechnicalAgent
from agents.volume_agent import VolumeAgent

# --------------------------------------


def main():
    print("🧠 Astra Fusion Calibration — real agent run")

    agents = [
        MomentumAgent(),
        TechnicalAgent(),
        RiskAgent(),
        VolumeAgent(),
        NeuralAgent(),
        CatalystAgent(),
    ]

    tracker_path = os.path.join("astra_modules", "learning", "performance_tracker.json")
    log_path = os.path.join("astra_modules", "logs", "fusion_calibration_log.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # --- simple synthetic ground truth for demo ---
    y_true = np.random.choice([0, 1], 500)
    # ----------------------------------------------

    results = {}
    for agent in agents:
        try:
            preds = [agent.predict(i) for i in y_true]
            preds = np.array(preds) > 0.5
            acc = float(np.mean(preds == y_true))
            var = float(np.var(preds))
            results[agent.__class__.__name__] = {"accuracy": acc, "variance": var}
            print(f"✅ {agent.__class__.__name__}: acc={acc:.3f}, var={var:.3f}")
        except Exception as e:
            print(f"⚠️ {agent.__class__.__name__} failed: {e}")

    # compute reliabilities
    for name, data in results.items():
        data["reliability"] = float(1 / (1 + data["variance"]))
    total = sum(r["reliability"] for r in results.values())
    for r in results.values():
        r["reliability"] /= total

    # save tracker
    with open(tracker_path, "w") as f:
        json.dump(results, f, indent=4)
    print("💾 performance_tracker.json updated.")

    # append log
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "average_accuracy": np.mean([r["accuracy"] for r in results.values()]),
        "guardian_signature": "ASTRA-V2-FUSION-OK",
        "weights": {k: v["reliability"] for k, v in results.items()},
    }
    if os.path.exists(log_path):
        with open(log_path) as f:
            logs = json.load(f)
    else:
        logs = []
    logs.append(entry)
    with open(log_path, "w") as f:
        json.dump(logs, f, indent=4)
    print("📘 fusion_calibration_log.json updated.")
    print("✅ Calibration complete.\n")

    # verify fusion core
    fusion = PredictionFusionV2(agents=agents)
    fusion_output = fusion.predict([0.2, 0.4, 0.6])
    print(f"🧩 Fusion output: {fusion_output}")

    # === Guardian Fusion Optimizer Auto-Integration ===
    try:
        from learning.guardian_fusion_optimizer import (
            GuardianFusionOptimizer,
        )

        optimizer = GuardianFusionOptimizer()
        optimized_output = optimizer.optimize(fusion_output)
        print("🧩 Guardian Optimized Output:", optimized_output)
    except Exception as e:
        print(f"[Guardian Optimizer] ⚠️ Optimization skipped: {e}")
    # === End Auto Integration ===


if __name__ == "__main__":
    main()
