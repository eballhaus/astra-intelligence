import threading
import asyncio
import datetime
from core.guardian.guardian_v7 import GuardianV7
from learning.learning_engine import start_learning_cycle
from learning.performance_tracker import PerformanceTracker

guardian = GuardianV7()
tracker = PerformanceTracker()

async def background_learning():








def start_background_learning():
    import asyncio
    import threading

    def run_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(background_learning())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    return t
