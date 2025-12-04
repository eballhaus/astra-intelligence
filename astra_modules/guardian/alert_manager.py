"""
guardian/alert_manager.py
───────────────────────────────────────────────────────────────
Astra Intelligence — Guardian Predictive Alert Layer (Phase 2.9-C)

Monitors TelemetryHub output and GuardianEngine health in real time.
Generates proactive alerts and triggers optional recovery hooks.
"""

import os, json, time, traceback
from datetime import datetime
from typing import Callable, Dict, Any, Optional

TELEMETRY_PATH = os.path.join(os.getcwd(), "logs", "telemetry_latest.json")
ALERT_LOG_PATH = os.path.join(os.getcwd(), "logs", "guardian_alerts.jsonl")

class GuardianAlertManager:
    """Predictive alert engine monitoring Guardian telemetry snapshots."""

    def __init__(
        self,
        restart_callback: Optional[Callable[[], None]] = None,
        notify_callback: Optional[Callable[[str, str], None]] = None,
        check_interval: int = 60,
        loss_drift_threshold: float = 0.005,
        success_rate_threshold: float = 0.8,
        heartbeat_stale_seconds: int = 600
    ):
        self.restart_callback = restart_callback
        self.notify_callback = notify_callback
        self.interval = check_interval
        self.loss_drift_threshold = loss_drift_threshold
        self.success_rate_threshold = success_rate_threshold
        self.heartbeat_stale_seconds = heartbeat_stale_seconds
        self.history = []  # rolling loss values
        self.last_timestamp = None
        self.running = False

    # ------------------------------------------------------------------
    def _read_telemetry(self) -> Optional[Dict[str, Any]]:
        """Safely read latest telemetry snapshot."""
        try:
            if not os.path.exists(TELEMETRY_PATH):
                return None
            with open(TELEMETRY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            traceback.print_exc()
            return None

    # ------------------------------------------------------------------
    def _log_alert(self, level: str, message: str, telemetry: Optional[Dict[str, Any]] = None):
        """Append alert to log file and optional notification callback."""
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "message": message,
            "telemetry": telemetry or {},
        }
        os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)
        with open(ALERT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        if self.notify_callback:
            try:
                self.notify_callback(level, message)
            except Exception:
                traceback.print_exc()

        print(f"[GuardianAlert] {level}: {message}")

    # ------------------------------------------------------------------
    def _detect_anomalies(self, telemetry: Dict[str, Any]) -> None:
        """Apply heuristic rules on telemetry snapshot."""
        try:
            if not telemetry:
                self._log_alert("warning", "No telemetry data available.")
                return

            ts_str = telemetry.get("timestamp")
            success_rate = telemetry.get("success_rate", 1.0)
            avg_loss = telemetry.get("avg_loss", 0.0)
            self.history.append(avg_loss)
            if len(self.history) > 20:
                self.history.pop(0)

            # 1️⃣ Success rate decay
            if success_rate < self.success_rate_threshold:
                self._log_alert(
                    "warning",
                    f"Low success rate detected ({success_rate:.2f}) below {self.success_rate_threshold}.",
                    telemetry,
                )

            # 2️⃣ Loss drift (increasing average loss over window)
            if len(self.history) >= 5:
                recent_avg = sum(self.history[-5:]) / 5
                past_avg = sum(self.history[:5]) / 5 if len(self.history) > 10 else recent_avg
                if recent_avg - past_avg > self.loss_drift_threshold:
                    self._log_alert(
                        "warning",
                        f"Loss drift detected: Δ={recent_avg - past_avg:.5f} (threshold {self.loss_drift_threshold}).",
                        telemetry,
                    )

            # 3️⃣ Heartbeat stale detection
            if ts_str:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                delta = (datetime.now() - ts).total_seconds()
                if delta > self.heartbeat_stale_seconds:
                    self._log_alert(
                        "error",
                        f"Telemetry heartbeat stale ({delta:.1f}s). Possible scheduler freeze.",
                        telemetry,
                    )
                    if self.restart_callback:
                        self._log_alert("info", "Attempting auto-restart via callback.")
                        try:
                            self.restart_callback()
                        except Exception:
                            traceback.print_exc()

        except Exception as e:
            self._log_alert("error", f"Anomaly detection failed: {e}")

    # ------------------------------------------------------------------
    def run_forever(self):
        """Main monitoring loop."""
        self.running = True
        self._log_alert("info", "Guardian Predictive Alert Manager started.")
        while self.running:
            telemetry = self._read_telemetry()
            self._detect_anomalies(telemetry)
            time.sleep(self.interval)

    def stop(self):
        """Gracefully stop monitoring loop."""
        self.running = False
        self._log_alert("info", "Guardian Predictive Alert Manager stopped.")
