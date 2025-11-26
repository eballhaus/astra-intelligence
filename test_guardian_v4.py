"""
GuardianV4 Validation Harness
----------------------------------------------------
Runs synthetic anomaly signals through the GuardianV4
defense system and prints live risk + action outputs.
"""

import random
import time
from astra_modules.guardian.guardian_v4 import guardian


def generate_signal():
    """Create a fake signal with numeric volatility."""
    return {
        "volatility": random.uniform(0.0, 12.0),
        "latency": random.uniform(0.0, 8.0),
        "drawdown": random.uniform(-5.0, 5.0),
        "throughput": random.uniform(0.0, 10.0),
    }


def run_guardian_test(iterations: int = 10, delay: float = 0.5):
    print("\n🧠  Starting GuardianV4 Adaptive Defense Test")
    print("--------------------------------------------------\n")

    for i in range(iterations):
        signal = generate_signal()
        result = guardian.evaluate_signal(signal)
        print(
            f"[{i+1:02d}] Signal={signal} -> "
            f"Risk={result['risk']:.3f} | Action={result['action']}"
        )
        time.sleep(delay)

    print("\n--------------------------------------------------")
    print("Final Health Snapshot:")
    print(guardian.broadcast_health())
    print("--------------------------------------------------\n")


if __name__ == "__main__":
    run_guardian_test()
