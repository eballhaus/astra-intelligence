"""
guardian/scheduler.py
──────────────────────────────────────────────────────────────────
Astra Intelligence — Guardian Learning Scheduler
Phase 2.5: Automated Continual Learning Orchestration

Purpose:
Controls periodic retraining of Astra's ContinualTrainer using
the ReplayBuffer, ensuring safe, incremental updates with
Guardian supervision.

Features:
- Background threading for non-blocking operation
- Exponential backoff on repeated failures
- Health monitoring and metrics tracking
- Responsive shutdown with event signaling
- Pre-flight buffer size checks with adaptive threshold

Module Version: v1.3.0
Author: Astra Intelligence Team
"""

import json
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from astra_core.learning.continual_trainer import ContinualTrainer
from astra_core.learning.replay_buffer import ReplayBuffer


# ──────────────────────────────────────────────────────────────
# METRICS CLASS
# ──────────────────────────────────────────────────────────────
@dataclass
class SchedulerMetrics:
    """Tracks scheduler performance over time."""

    total_cycles: int = 0
    successful_cycles: int = 0
    failed_cycles: int = 0
    skipped_cycles: int = 0
    recent_losses: List[float] = field(default_factory=list)
    last_success_time: Optional[str] = None
    start_time: Optional[str] = None

    def success_rate(self) -> float:
        completed = self.successful_cycles + self.failed_cycles
        return self.successful_cycles / completed if completed else 0.0

    def average_loss(self) -> float:
        return (
            sum(self.recent_losses) / len(self.recent_losses)
            if self.recent_losses
            else 0.0
        )

    def record_loss(self, loss: Optional[float], max_records: int = 50):
        """Add a new loss to history (trimmed to recent window)."""
        if loss is not None:
            self.recent_losses.append(float(loss))
            if len(self.recent_losses) > max_records:
                self.recent_losses.pop(0)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize all metrics for logging or monitoring."""
        return {
            "total_cycles": self.total_cycles,
            "successful_cycles": self.successful_cycles,
            "failed_cycles": self.failed_cycles,
            "skipped_cycles": self.skipped_cycles,
            "success_rate": round(self.success_rate(), 3),
            "average_loss": round(self.average_loss(), 6),
            "last_success_time": self.last_success_time,
            "start_time": self.start_time,
        }


# ──────────────────────────────────────────────────────────────
# SCHEDULER CLASS
# ──────────────────────────────────────────────────────────────
class LearningScheduler:
    """
    Oversees scheduled continual training sessions.

    Runs the ContinualTrainer periodically in a background thread,
    under Guardian supervision. Handles cooldowns, rate limits,
    exponential backoff, and graceful failure recovery.
    """

    def __init__(
        self,
        trainer: ContinualTrainer,
        buffer: ReplayBuffer,
        interval_seconds: int = 600,  # default = 10 minutes
        max_failures: int = 3,
        max_backoff_seconds: int = 3600,  # Max 1 hour
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        self.trainer = trainer
        self.buffer = buffer
        self.interval = interval_seconds
        self.max_failures = max_failures
        self.max_backoff = max_backoff_seconds
        self.log = log_callback or self._default_log

        # State tracking
        self.fail_count = 0
        self.running = False
        self.backoff_multiplier = 1.0
        self.last_heartbeat: Optional[datetime] = None

        # Thread control
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        # Metrics
        self.metrics = SchedulerMetrics()
        self.metrics.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ──────────────────────────────────────────────────────────────
    # LOGGING
    # ──────────────────────────────────────────────────────────────
    def _default_log(self, message: str, level: str = "INFO") -> None:
        prefix = f"[{level}]" if level != "INFO" else ""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"{prefix}[{timestamp}][LearningScheduler] {message}")

    # ──────────────────────────────────────────────────────────────
    # CONTROL
    # ──────────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Start scheduler in a background thread."""
        if self.running:
            self.log("Scheduler already running", "WARNING")
            return False

        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._run_loop, daemon=True, name="AstraLearningScheduler"
        )
        self.thread.start()
        self.log("✅ Scheduler started in background thread")
        return True

    def stop(self) -> None:
        """Stop the scheduler and wake up any cooldown wait."""
        if not self.running:
            self.log("Scheduler already stopped", "INFO")
            return

        self.running = False
        self.stop_event.set()
        self.log("🛑 Scheduler stop signal sent", "WARNING")

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5.0)
            if self.thread.is_alive():
                self.log("Thread did not terminate within timeout", "WARNING")
            else:
                self.log("Scheduler thread terminated cleanly")

    # ──────────────────────────────────────────────────────────────
    # CORE LOOP
    # ──────────────────────────────────────────────────────────────
    def _run_loop(self) -> None:
        """Main continual training loop."""
        self.log("Continual training loop active.")
        try:
            while self.running:
                self._run_cycle()
                if self.running:
                    self._cooldown()
        except Exception as e:
            self.log(f"Fatal scheduler error: {e}", "ERROR")
            traceback.print_exc()
        finally:
            self.running = False
            self.log("Scheduler loop terminated.")

    def _run_cycle(self) -> None:
        """Execute a single training cycle."""
        self.last_heartbeat = datetime.now()
        self.metrics.total_cycles += 1
        timestamp = self.last_heartbeat.strftime("%H:%M:%S")
        self.log(f"─── Training Cycle #{self.metrics.total_cycles} at {timestamp} ───")

        try:
            # Pre-flight buffer validation (require 80% of batch size)
            buffer_size = self._get_buffer_size()
            required_size = max(1, int(self.trainer.batch_size * 0.8))
            if buffer_size < required_size:
                self.log(
                    f"Skipping cycle: insufficient samples ({buffer_size}/{required_size})",
                    "INFO",
                )
                self.metrics.skipped_cycles += 1
                return

            self.log(f"Buffer OK: {buffer_size} samples. Beginning training.")
            success = self.trainer.train(self.buffer)

            if success:
                self._handle_success()
            else:
                self._handle_failure("Trainer returned False")

        except Exception as e:
            self._handle_failure(f"Exception: {e}")
            traceback.print_exc()

    def _get_buffer_size(self) -> int:
        """Safely determine replay buffer size."""
        try:
            if hasattr(self.buffer, "buffer"):
                return len(self.buffer.buffer)
            elif hasattr(self.buffer, "__len__"):
                return len(self.buffer)
            return 0
        except Exception as e:
            self.log(f"Error checking buffer size: {e}", "ERROR")
            return 0

    # ──────────────────────────────────────────────────────────────
    # HANDLERS
    # ──────────────────────────────────────────────────────────────
    def _handle_success(self) -> None:
        """Process successful training results."""
        self.fail_count = 0
        self.backoff_multiplier = 1.0
        self.metrics.successful_cycles += 1
        self.metrics.last_success_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self.log("✅ Training cycle completed successfully")

        try:
            status = self.trainer.get_status()
            self.log(f"Model Status:\n{json.dumps(status, indent=2)}")

            last_loss = status.get("last_loss") if isinstance(status, dict) else None
            self.metrics.record_loss(last_loss)
        except Exception as e:
            self.log(f"Error retrieving trainer status: {e}", "WARNING")

    def _handle_failure(self, reason: str) -> None:
        """Handle failed training cycles with exponential backoff."""
        self.fail_count += 1
        self.metrics.failed_cycles += 1
        self.log(
            f"❌ Training failed: {reason} ({self.fail_count}/{self.max_failures})",
            "WARNING",
        )

        if self.fail_count >= self.max_failures:
            self.backoff_multiplier = min(
                self.backoff_multiplier * 2,
                self.max_backoff / self.interval,
            )
            self.log(
                f"⚠️  Exponential backoff applied: {self.backoff_multiplier:.1f}x",
                "WARNING",
            )

            if self.backoff_multiplier >= (self.max_backoff / self.interval):
                self.log(
                    "⛔ Maximum backoff reached. Investigation recommended.", "ERROR"
                )

    def _cooldown(self) -> None:
        """Cooldown between cycles with immediate stop support."""
        actual_interval = int(self.interval * self.backoff_multiplier)
        self.log(f"💤 Cooling down for {actual_interval} seconds...")
        self.stop_event.wait(timeout=actual_interval)
        if not self.running:
            self.log("Cooldown interrupted by shutdown signal.")

    # ──────────────────────────────────────────────────────────────
    # HEALTH & METRICS
    # ──────────────────────────────────────────────────────────────
    def is_healthy(self) -> bool:
        """Return True if scheduler heartbeat is recent."""
        if not self.running:
            return True
        if self.last_heartbeat is None:
            return False

        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        max_expected = (self.interval * self.backoff_multiplier * 2) + 30
        return elapsed < max_expected

    def get_health_status(self) -> Dict[str, Any]:
        """Return detailed scheduler health information."""
        elapsed = None
        if self.last_heartbeat:
            elapsed = (datetime.now() - self.last_heartbeat).total_seconds()

        return {
            "running": self.running,
            "healthy": self.is_healthy(),
            "consecutive_failures": self.fail_count,
            "backoff_multiplier": round(self.backoff_multiplier, 2),
            "last_heartbeat": (
                self.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S")
                if self.last_heartbeat
                else None
            ),
            "seconds_since_heartbeat": elapsed,
            "thread_alive": self.thread.is_alive() if self.thread else False,
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Return combined performance and health metrics."""
        return {
            **self.metrics.to_dict(),
            "currently_running": self.running,
            "health_status": self.get_health_status(),
        }

    def reset_metrics(self) -> None:
        """Reset metrics while preserving start time."""
        old_start = self.metrics.start_time
        self.metrics = SchedulerMetrics()
        self.metrics.start_time = old_start
        self.log("Metrics reset")

    def __repr__(self) -> str:
        status = "RUNNING" if self.running else "STOPPED"
        return f"<LearningScheduler [{status}] interval={self.interval}s failures={self.fail_count}/{self.max_failures}>"
