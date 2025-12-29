import asyncio
import threading
from astra_dashboard.core.guardian.guardian_v7 import GuardianV7
from astra_dashboard.learning.learning_engine import train_learning_engine as start_learning_cycle
from astra_dashboard.learning.performance_tracker import PerformanceTracker

guardian = GuardianV7()
tracker = PerformanceTracker()


async def background_learning():
    guardian.info("🔁 Astra Learning Manager started.")
    while True:
        try:
            # Run frequent micro-learning cycles
            start_learning_cycle()
            guardian.info("✅ Micro-learning cycle completed successfully.")

            # Save updated learning metrics
        except Exception as e:
            guardian.error(f"Learning cycle error: {e}")
        await asyncio.sleep(900)  # 15 min


def start_background_learning():
    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(background_learning())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    return t
