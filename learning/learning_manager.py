"""
learning_manager.py — Astra Learning Manager
Handles background micro-learning cycles for NeuralAgent retraining.
"""

import asyncio
import threading
from core.guardian.guardian_v7 import GuardianV7
from learning.learning_engine import train_learning_engine as start_learning_cycle
from learning.performance_tracker import PerformanceTracker

guardian = GuardianV7()
tracker = PerformanceTracker()


async def background_learning():
    guardian.info("🔁 Astra Learning Manager started.")
    while True:
        try:
            # Run frequent micro-learning cycles
            start_learning_cycle()
            guardian.info("✅ Micro-learning cycle completed successfully.")
        except Exception as e:
            guardian.error(f"Learning cycle error: {e}")
        await asyncio.sleep(900)  # 15 minutes


def start_background_learning():
    """Start the learning loop in a background thread."""
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(background_learning())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    return t
