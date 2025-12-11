"""
guardian/guardian_engine.py
──────────────────────────────────────────────────────────────────
Astra Intelligence — Guardian Engine
Phase 2.6: Learning Scheduler Integration

Purpose:
The Guardian Engine supervises Astra's core background processes —
ensuring safety, uptime, and coordination between learning systems,
forecasting, and replay modules.

Now integrates:
- LearningScheduler (for continual training)
- ForecastEngine (for prediction monitoring)
- ReplayBuffer (as shared memory for learning)
- Health checks, safe start/stop, and fault isolation

Version: v2.6.0
Author: Astra Intelligence Team
"""

import json
import time
import traceback
from datetime import datetime
from typing import Any, Dict

from astra_core.guardian.scheduler import LearningScheduler
from astra_core.learning.continual_trainer import ContinualTrainer
from astra_core.learning.replay_buffer import ReplayBuffer


class GuardianEngine:
    """
    Oversees Astra’s background learning systems and ensures stable operation.

    Responsibilities:
    - Starts and supervises the continual learning scheduler
    - Performs health checks and recovery
    - Exposes system metrics for external dashboards
    - Handles clean shutdown and failure recovery
    """

    def __init__(
        self,
        auto_start: bool = True,
        scheduler_interval: int = 600,
        max_failures: int = 3,
    ):
        """
        Initialize GuardianEngine and its subsystems.

        Args:
            auto_start: Whether to start the scheduler immediately
            scheduler_interval: Seconds between training cycles
            max_failures: Consecutive failure threshold before alerting
        """
        self.start_time = datetime.now()
        self.scheduler_interval = scheduler_interval
        self.max_failures = max_failures
        self.auto_start = auto_start

        # Initialize learning subsystems
        self.replay_buffer = ReplayBuffer()
        self.trainer = ContinualTrainer()
        self.scheduler = LearningScheduler(
            trainer=self.trainer,
            buffer=self.replay_buffer,
            interval_seconds=self.scheduler_interval,
            max_failures=self.max_failures,
            log_callback=self._log,
        )

        self.running = False
        if self.auto_start:
            self.start()

    # ──────────────────────────────────────────────
    # CORE CONTROL
    # ──────────────────────────────────────────────
    def start(self):
        """Start Guardian and all supervised processes."""
        if self.running:
            self._log("GuardianEngine already running.", "WARNING")
            return False

        self.running = True
        self._log("🚀 Guardian Engine starting subsystems...")

        # Start continual learning scheduler
        try:
            started = self.scheduler.start()
            if started:
                self._log("✅ LearningScheduler started successfully.")
            else:
                self._log("⚠️ LearningScheduler already active.", "WARNING")
        except Exception as e:
            self._log(f"Failed to start scheduler: {e}", "ERROR")
            traceback.print_exc()
            self.running = False
            return False

        return True

    def stop(self):
        """Stop all background systems gracefully."""
        if not self.running:
            self._log("GuardianEngine already stopped.", "INFO")
            return False

        self._log("🛑 Stopping Guardian subsystems...")
        try:
            if self.scheduler:
                self.scheduler.stop()
                self._log("Scheduler stopped.")
        except Exception as e:
            self._log(f"Error stopping scheduler: {e}", "ERROR")

        self.running = False
        self._log("GuardianEngine stopped cleanly.")
        return True

    # ──────────────────────────────────────────────
    # MONITORING & HEALTH
    # ──────────────────────────────────────────────
    def check_health(self) -> Dict[str, Any]:
        """
        Perform a full health check of Guardian systems.

        Returns:
            Health status dictionary.
        """
        try:
            scheduler_health = self.scheduler.get_health_status()
            trainer_status = self.trainer.get_status()
            metrics = self.scheduler.get_metrics()

            health = {
                "guardian_running": self.running,
                "system_start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "scheduler_health": scheduler_health,
                "trainer_status": trainer_status,
                "scheduler_metrics": metrics,
            }

            self._log(f"📊 Health check:\n{json.dumps(health, indent=2)}")
            return health

        except Exception as e:
            self._log(f"Health check failed: {e}", "ERROR")
            traceback.print_exc()
            return {
                "guardian_running": self.running,
                "error": str(e),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def is_healthy(self) -> bool:
        """Simple boolean health signal for top-level monitor."""
        if not self.running:
            return False
        return self.scheduler.is_healthy()

    def run_guardian_loop(self, check_interval: int = 300):
        """
        Run Guardian’s main supervisory loop.
        Periodically checks subsystem health and restarts scheduler if needed.
        """
        self._log("Guardian Engine main loop active.")
        try:
            while self.running:
                if not self.scheduler.is_healthy():
                    self._log(
                        "⚠️ Scheduler unhealthy — attempting restart.", "WARNING")
                    self.scheduler.stop()
                    time.sleep(3)
                    self.scheduler.start()

                time.sleep(check_interval)

        except KeyboardInterrupt:
            self._log("Guardian loop interrupted.", "WARNING")
            self.stop()
        except Exception as e:
            self._log(f"Guardian loop error: {e}", "ERROR")
            traceback.print_exc()
            self.stop()

    # ──────────────────────────────────────────────
    # LOGGING
    # ──────────────────────────────────────────────
    def _log(self, message: str, level: str = "INFO"):
        """Unified logger for Guardian and subsystems."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix}[{timestamp}][GuardianEngine] {message}")

    def __repr__(self):
        state = "RUNNING" if self.running else "STOPPED"
        return f"<GuardianEngine [{state}] interval={self.scheduler_interval}s>"


"""
guardian/guardian_engine.py
──────────────────────────────────────────────────────────────────
Astra Intelligence — Guardian Engine
Phase 2.6: Learning Scheduler Integration

Purpose:
The Guardian Engine supervises Astra's core background processes —
ensuring safety, uptime, and coordination between learning systems,
forecasting, and replay modules.

Now integrates:
- LearningScheduler (for continual training)
- ForecastEngine (for prediction monitoring)
- ReplayBuffer (as shared memory for learning)
- Health checks, safe start/stop, and fault isolation

Version: v2.6.0
Author: Astra Intelligence Team
"""


class GuardianEngine:
    """
    Oversees Astra’s background learning systems and ensures stable operation.

    Responsibilities:
    - Starts and supervises the continual learning scheduler
    - Performs health checks and recovery
    - Exposes system metrics for external dashboards
    - Handles clean shutdown and failure recovery
    """

    def __init__(
        self,
        auto_start: bool = True,
        scheduler_interval: int = 600,
        max_failures: int = 3,
    ):
        """
        Initialize GuardianEngine and its subsystems.

        Args:
            auto_start: Whether to start the scheduler immediately
            scheduler_interval: Seconds between training cycles
            max_failures: Consecutive failure threshold before alerting
        """
        self.start_time = datetime.now()
        self.scheduler_interval = scheduler_interval
        self.max_failures = max_failures
        self.auto_start = auto_start

        # Initialize learning subsystems
        self.replay_buffer = ReplayBuffer()
        self.trainer = ContinualTrainer()
        self.scheduler = LearningScheduler(
            trainer=self.trainer,
            buffer=self.replay_buffer,
            interval_seconds=self.scheduler_interval,
            max_failures=self.max_failures,
            log_callback=self._log,
        )

        self.running = False
        if self.auto_start:
            self.start()

    # ──────────────────────────────────────────────
    # CORE CONTROL
    # ──────────────────────────────────────────────
    def start(self):
        """Start Guardian and all supervised processes."""
        if self.running:
            self._log("GuardianEngine already running.", "WARNING")
            return False

        self.running = True
        self._log("🚀 Guardian Engine starting subsystems...")

        # Start continual learning scheduler
        try:
            started = self.scheduler.start()
            if started:
                self._log("✅ LearningScheduler started successfully.")
            else:
                self._log("⚠️ LearningScheduler already active.", "WARNING")
        except Exception as e:
            self._log(f"Failed to start scheduler: {e}", "ERROR")
            traceback.print_exc()
            self.running = False
            return False

        return True

    def stop(self):
        """Stop all background systems gracefully."""
        if not self.running:
            self._log("GuardianEngine already stopped.", "INFO")
            return False

        self._log("🛑 Stopping Guardian subsystems...")
        try:
            if self.scheduler:
                self.scheduler.stop()
                self._log("Scheduler stopped.")
        except Exception as e:
            self._log(f"Error stopping scheduler: {e}", "ERROR")

        self.running = False
        self._log("GuardianEngine stopped cleanly.")
        return True

    # ──────────────────────────────────────────────
    # MONITORING & HEALTH
    # ──────────────────────────────────────────────
    def check_health(self) -> Dict[str, Any]:
        """
        Perform a full health check of Guardian systems.

        Returns:
            Health status dictionary.
        """
        try:
            scheduler_health = self.scheduler.get_health_status()
            trainer_status = self.trainer.get_status()
            metrics = self.scheduler.get_metrics()

            health = {
                "guardian_running": self.running,
                "system_start_time": self.start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "scheduler_health": scheduler_health,
                "trainer_status": trainer_status,
                "scheduler_metrics": metrics,
            }

            self._log(f"📊 Health check:\n{json.dumps(health, indent=2)}")
            return health

        except Exception as e:
            self._log(f"Health check failed: {e}", "ERROR")
            traceback.print_exc()
            return {
                "guardian_running": self.running,
                "error": str(e),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

    def is_healthy(self) -> bool:
        """Simple boolean health signal for top-level monitor."""
        if not self.running:
            return False
        return self.scheduler.is_healthy()

    def run_guardian_loop(self, check_interval: int = 300):
        """
        Run Guardian’s main supervisory loop.
        Periodically checks subsystem health and restarts scheduler if needed.
        """
        self._log("Guardian Engine main loop active.")
        try:
            while self.running:
                if not self.scheduler.is_healthy():
                    self._log(
                        "⚠️ Scheduler unhealthy — attempting restart.", "WARNING")
                    self.scheduler.stop()
                    time.sleep(3)
                    self.scheduler.start()

                time.sleep(check_interval)

        except KeyboardInterrupt:
            self._log("Guardian loop interrupted.", "WARNING")
            self.stop()
        except Exception as e:
            self._log(f"Guardian loop error: {e}", "ERROR")
            traceback.print_exc()
            self.stop()

    # ──────────────────────────────────────────────
    # LOGGING
    # ──────────────────────────────────────────────
    def _log(self, message: str, level: str = "INFO"):
        """Unified logger for Guardian and subsystems."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix}[{timestamp}][GuardianEngine] {message}")

    def __repr__(self):
        state = "RUNNING" if self.running else "STOPPED"
        return f"<GuardianEngine [{state}] interval={self.scheduler_interval}s>"
