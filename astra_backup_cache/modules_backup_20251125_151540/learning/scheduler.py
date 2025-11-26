"""
scheduler.py — Phase-90

Background training scheduler for Astra Intelligence.
Supports:
 • timed training loops (every X minutes)
 • condition-based training (buffer size threshold)
 • daily training routines

Used by Learning Center + background agent.
"""

import time
from datetime import datetime, timedelta


class LearningScheduler:
    def __init__(self, trainer, buffer, guardian=None):
        """
        trainer: ContinualTrainer instance
        buffer: ReplayBuffer instance
        guardian: optional GuardianV3 for safety
        """
        self.trainer = trainer
        self.buffer = buffer
        self.guardian = guardian

        self.last_train_time = None
        self.interval_minutes = 30     # default every 30 minutes
        self.min_buffer_samples = 50   # minimum samples required

    # -------------------------------------------------------------
    # SAFE WRAPPER
    # -------------------------------------------------------------
    def safe(self, func, *args, **kwargs):
        if self.guardian:
            return self.guardian.safe_run(func, *args, **kwargs)
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    # -------------------------------------------------------------
    # CORE SCHEDULE CHECKER
    # -------------------------------------------------------------
    def should_train(self):
        """
        Returns True if:
         • enough buffer samples exist
         • it's been interval_minutes since last run
        """
        size = self.safe(self.buffer.size) or 0
        if size < self.min_buffer_samples:
            return False

        now = datetime.utcnow()

        if self.last_train_time is None:
            return True

        delta = now - self.last_train_time
        if delta >= timedelta(minutes=self.interval_minutes):
            return True

        return False

    # -------------------------------------------------------------
    # TRAINING EXECUTOR
    # -------------------------------------------------------------
    def run_if_due(self):
        """
        Run training ONLY if the system decides it's time.
        """
        if not self.should_train():
            return {"trained": False, "reason": "Not due or insufficient samples"}

        out = self.safe(self.trainer.train_step)
        self.last_train_time = datetime.utcnow()

        return {
            "trained": bool(out),
            "timestamp": str(self.last_train_time),
        }

    # -------------------------------------------------------------
    # FORCE TRAINING
    # -------------------------------------------------------------
    def force_train(self):
        """
        Manual / emergency “train now”.
        """
        out = self.safe(self.trainer.train_step)
        self.last_train_time = datetime.utcnow()

        return {
            "trained": bool(out),
            "timestamp": str(self.last_train_time),
            "reason": "Manual"
        }

    # -------------------------------------------------------------
    # DAILY SCHEDULE (RUN AT MIDNIGHT UTC)
    # -------------------------------------------------------------
    def run_daily(self):
        """
        Use in future daemon:
         • At midnight UTC each day
         • Perform full retraining
        """
        now = datetime.utcnow()
        if now.hour == 0 and now.minute < 5:
            return self.force_train()

        return {"trained": False, "reason": "Not daily window"}
