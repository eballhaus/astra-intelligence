"""
Astra Intelligence — Background Performance & Learning Loop
------------------------------------------------------------
Runs continuously in background to:
 - evaluate closed predictions,
 - update performance metrics,
 - and retrain neural agents periodically.
"""

import time
import threading
from performance.performance_logger import PerformanceLogger
from performance.outcome_evaluator import OutcomeEvaluator
from learning.replay_buffer import ReplayBuffer
from learning.continual_trainer import ContinualTrainer
from fetch_core.fetch_unified import (
    fetch_price,
)  # assumes a fetch_price(ticker) helper exists


class BackgroundLoop:
    def __init__(self, interval_minutes=5):
        self.interval = interval_minutes * 60
        self.logger = PerformanceLogger()
        self.evaluator = OutcomeEvaluator()
        self.replay_buffer = ReplayBuffer()
        self.trainer = ContinualTrainer()
        self.running = False

    # ---------- core cycle ----------
    def run_cycle(self):
        open_preds = self.logger.data.get("predictions", {})
        if not open_preds:
            return

        print(f"[BackgroundLoop] Checking {len(open_preds)} open predictions…")
        to_close = []
        for pid, pred in open_preds.items():
            ticker = pred["ticker"]
            try:
                current_price = fetch_price(ticker)
            except Exception as e:
                print(f"⚠️ Fetch failed for {ticker}: {e}")
                continue

            # Simple horizon logic — close after 6 hours
            if (time.time() - pred["timestamp"]) > 6 * 3600:
                outcome = self.evaluator.evaluate(pred, current_price)
                self.logger.close_prediction(pid, outcome)

                # Send to replay buffer
                reward = outcome["return_pct"]
                self.replay_buffer.add_sample(
                    features={},  # your feature set if available
                    action=pred["direction"],
                    reward=reward,
                    new_features={},
                )
                print(
                    f"[BackgroundLoop] Closed {ticker} ({'WIN' if outcome['correct'] else 'LOSS'})"
                )

        # Trigger retrain after every cycle if any trades closed
        if to_close:
            self.trainer.train_recent()

    # ---------- thread control ----------
    def start(self):
        self.running = True
        t = threading.Thread(target=self._loop)
        t.daemon = True
        t.start()
        print(f"[BackgroundLoop] ✅ Started (interval {self.interval/60} min)")

    def stop(self):
        self.running = False
        print("[BackgroundLoop] ⏹ Stopped.")

    def _loop(self):
        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"[BackgroundLoop] ⚠️ Error: {e}")
            time.sleep(self.interval)


if __name__ == "__main__":
    loop = BackgroundLoop(interval_minutes=10)
    loop.start()
    while True:
        time.sleep(60)
