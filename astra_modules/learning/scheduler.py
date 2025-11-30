"""
Astra Intelligence - Learning Scheduler
---------------------------------------
Autonomous background scheduler that manages Astra’s continual learning cycle.

Responsibilities:
• Runs background retraining on a fixed interval (default 60 minutes)
• Triggers continual trainer (neural updates)
• Runs learning engine (correlation + weight adjustment)
• Updates performance tracker
• Logs all events safely without interrupting the main dashboard
• Self-recovers from API or data interruptions

This module runs continuously in the background once Astra is launched.
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Optional

from astra_modules.learning.continual_trainer import ContinualTrainer
from astra_modules.learning.learning_engine import train_learning_engine
from astra_modules.learning.replay_buffer import ReplayBuffer
from astra_modules.learning.performance_tracker import PerformanceTracker


class LearningScheduler:
    """
    Background learning controller for Astra.
    Runs periodic training sessions to keep neural and weight models updated.
    """

    def __init__(self, interval_minutes: int = 60, min_new_samples: int = 10):
        self.interval_minutes = interval_minutes
        self.min_new_samples = min_new_samples
        self.last_run: Optional[datetime] = None
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.performance_tracker = PerformanceTracker()
        self.replay_buffer = ReplayBuffer()

    # === Scheduler State ===
    def should_train(self) -> bool:
        """Check whether it’s time for the next training session."""
        now = datetime.utcnow()

        if self.last_run is None:
            return True

        elapsed = (now - self.last_run).total_seconds() / 60
        if elapsed >= self.interval_minutes:
            return True

        # Optional: also check replay buffer for new samples
        if len(self.replay_buffer) >= self.min_new_samples:
            return True

        return False

    def mark_run(self):
        """Record the timestamp of the last training cycle."""
        self.last_run = datetime.utcnow()

    # === Core Learning Cycle ===
    def run_learning_cycle(self):
        """Execute a full learning cycle safely."""
        try:
            print(f"[Astra Learning] 🚀 Starting learning cycle at {datetime.utcnow().isoformat()}")

            # 1️⃣ Train neural model incrementally
            trainer = ContinualTrainer()
            trainer.train(self.replay_buffer)

            # 2️⃣ Update correlation and weighting models
            train_learning_engine()

            # 3️⃣ Evaluate current learning performance
            stats = self.performance_tracker.get_recent_stats()
            accuracy = stats.get("accuracy", 0)
            win_rate = stats.get("win_rate", 0)
            print(f"[Astra Learning] Accuracy: {accuracy:.2%} | Win Rate: {win_rate:.2%}")

            # 4️⃣ Update state
            self.mark_run()
            print(f"[Astra Learning] ✅ Cycle completed successfully at {self.last_run.isoformat()}")

        except Exception as e:
            print(f"[Astra Learning] ⚠️ Learning cycle failed: {e}")

    # === Thread Management ===
    def _background_loop(self):
        """Internal background thread loop for continuous operation."""
        self.is_running = True
        print(f"[Astra Learning] Background scheduler started. Interval: {self.interval_minutes} min")

        while self.is_running:
            try:
                if self.should_train():
                    self.run_learning_cycle()
                time.sleep(60)  # check every minute
            except Exception as e:
                print(f"[Astra Learning] ⚠️ Scheduler loop error: {e}")
                time.sleep(300)

    def start(self):
        """Start the learning scheduler in a background thread."""
        if self.thread and self.thread.is_alive():
            print("[Astra Learning] Scheduler is already running.")
            return

        self.thread = threading.Thread(target=self._background_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the background scheduler safely."""
        print("[Astra Learning] Scheduler stopping...")
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[Astra Learning] Scheduler stopped.")


# === Entry Point ===
if __name__ == "__main__":
    """
    Running this file directly will launch Astra’s autonomous learning scheduler.
    It will run indefinitely, checking every minute for training conditions.
    """
    scheduler = LearningScheduler(interval_minutes=60)
    scheduler.start()

    try:
        while True:
            time.sleep(300)
    except KeyboardInterrupt:
        scheduler.stop()
