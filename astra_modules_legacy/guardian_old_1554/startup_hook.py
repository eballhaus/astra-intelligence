"""
🧩 Guardian Startup Hook
───────────────────────────────────────────────────────────────
Ensures GuardianV6 initializes before any Astra Intelligence system starts.
Runs self-checks, dependency verification, and launches the GuardianEngine.

Enhancements in v2.9.0:
- Integrated GuardianEngine (continual learning scheduler)
- Integrated ForecastEngine feedback loop
- Added live heartbeat telemetry logging
- Added TelemetryHub for JSON-based export
- Auto-heal & structured logging
- Clean shutdown handling

Author: Astra Intelligence Team
Version: v2.9.0
"""

import importlib
import os
import sys
import traceback
from datetime import datetime

# ============================================================
# 🧭 PATH CONFIGURATION
# ============================================================

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ============================================================
# 🧠 GUARDIAN CORE IMPORT
# ============================================================

try:
    from astra_core.guardian.guardian_v6 import guardian
except Exception as e:
    raise ImportError(f"Failed to import guardian_v7: {e}") from e

# ============================================================
# 🔧 ENGINE IMPORTS
# ============================================================

try:
    from astra_core.forecast.forecast_engine import ForecastEngine
    from astra_core.guardian.guardian_v6 import guardian
except ImportError as e:
    guardian_v7.guardian.log(
        f"⚠️ Optional engine modules not found: {e}", level="warning"
    )
    GuardianEngine = None
    ForecastEngine = None

# ============================================================
# 📡 TELEMETRY IMPORT
# ============================================================

try:
    from astra_core.guardian.guardian_v6 import guardian

    telemetry = TelemetryHub()
    guardian_v7.guardian.log("📡 TelemetryHub initialized successfully.")
except Exception as e:
    telemetry = None
    guardian_v7.guardian.log(
        f"⚠️ TelemetryHub not available: {e}", level="warning")

# ============================================================
# 🚀 INITIALIZATION FUNCTIONS
# ============================================================


def initialize_guardian():
    """Initialize GuardianV6 and perform startup checks."""
    try:
        guardian_instance = guardian_v7
        guardian_v7.guardian.log(
            "🔐 Guardian Startup Hook initialized successfully.")
        guardian_v7.guardian.log(
            f"📁 Guardian root directory: {guardian_v7.root_dir}")
        guardian_v7.guardian.log(
            f"🧩 Guardian log file: {guardian_v7.GUARDIAN_LOG_PATH}"
        )
        return guardian_instance
    except Exception as e:
        raise ImportError(f"Failed to initialize guardian_v7: {e}") from e


# ============================================================
# 🧩 DEPENDENCY CHECK
# ============================================================


def verify_core_modules():
    """Verify that Astra core dependencies are available before runtime."""
    modules = [
        "astra_core.fetch_core.fetch_unified",
        "astra_core.ui.dashboard.dashboard_data",
        "astra_core.ui.dashboard.dashboard_chart",
        "astra_core.guardian.guardian_v7",
    ]
    missing = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            guardian_v7.guardian.log(f"✅ Verified module: {mod}")
        except Exception as e:
            guardian_v7.guardian.log(
                f"🚨 Missing or failed module: {mod} ({e})", level="error"
            )
            missing.append(mod)
    if missing:
        guardian_v7.guardian.log(
            f"⚠️ Some modules failed verification: {missing}", level="warning"
        )
    else:
        guardian_v7.guardian.log("🟢 All core modules verified successfully.")


# ============================================================
# 🩺 STARTUP DIAGNOSTICS
# ============================================================


def run_startup_diagnostics():
    """Run Guardian-level system diagnostics at startup."""
    guardian_v7.guardian.log("🩺 Running Guardian startup diagnostics...")
    try:
        verify_core_modules()
        guardian_v7.guardian.log(
            "🧠 Guardian startup diagnostics completed successfully."
        )
        return True
    except Exception as e:
        guardian_v7.guardian.log(
            f"❌ Guardian diagnostics failed: {e}", level="error")
        traceback.print_exc()
        return False


# ============================================================
# 🧩 ASTRA SYSTEM BOOTSTRAP
# ============================================================

guardian_engine = None
forecast_engine = None
_running = False


def start_astra_system(heartbeat_interval: int = 300):
    """
    Initialize GuardianEngine and ForecastEngine for full Astra runtime.

    Args:
        heartbeat_interval: Seconds between heartbeat telemetry logs
    """
    global guardian_engine, forecast_engine, _running

    guardian_v7.guardian.log(
        "🚀 Starting Astra Intelligence background systems...")

    try:
        # Initialize ForecastEngine if available
        if ForecastEngine:
            forecast_engine = ForecastEngine()
            guardian_v7.guardian.log("✅ ForecastEngine initialized.")
        else:
            guardian_v7.guardian.log(
                "⚠️ ForecastEngine not available, skipping.", level="warning"
            )

        # Initialize GuardianEngine if available
        if GuardianEngine:
            guardian_engine = GuardianEngine(auto_start=True)
            guardian_v7.guardian.log("✅ GuardianEngine started successfully.")
        else:
            guardian_v7.guardian.log(
                "⚠️ GuardianEngine not available, skipping.", level="warning"
            )

        # Optional feedback loop connection
        if (
            forecast_engine
            and guardian_engine
            and hasattr(guardian_engine.trainer, "record_forecast")
        ):
            guardian_v7.guardian.log(
                "🔄 Linking ForecastEngine → ContinualTrainer feedback loop..."
            )
            forecast_engine.record_forecast_hook = (
                guardian_engine.trainer.record_forecast
            )

        # ============================================================
        # 🧠 GUARDIAN ALERT MANAGER (Phase 2.9-C)
        # ============================================================
        try:
            import threading
            import time

            from astra_core.guardian.guardian_v6 import guardian

            def restart_guardian():
                guardian_v7.guardian.log(
                    "♻️ Restarting GuardianEngine via AlertManager..."
                )
                if guardian_engine:
                    guardian_engine.stop()
                    time.sleep(3)
                    guardian_engine.start()

            alert_manager = GuardianAlertManager(
                restart_callback=restart_guardian,
                notify_callback=lambda lvl, msg: guardian_v7.guardian.log(
                    f"[Alert {lvl.upper()}] {msg}"
                ),
                check_interval=90,  # every 1.5 min
                success_rate_threshold=0.85,
            )

            threading.Thread(
                target=alert_manager.run_forever,
                daemon=True,
                name="GuardianAlertThread",
            ).start()

            guardian_v7.guardian.log(
                "🧠 GuardianAlertManager running in background.")
        except Exception as alert_err:
            guardian_v7.guardian.log(
                f"⚠️ Failed to start AlertManager: {alert_err}", level="warning"
            )
        # ============================================================

        _running = True
        guardian_v7.guardian.log("🟢 Astra Intelligence runtime is now active.")
        guardian_v7.guardian.log(
            "──────────────────────────────────────────────")
        guardian_v7.guardian.log("Press Ctrl+C to stop the system.")
        guardian_v7.guardian.log(
            "──────────────────────────────────────────────")

        # Persistent health and telemetry loop
        last_heartbeat = 0
        while _running:
            now = time.time()

            # Periodic telemetry output
            if now - last_heartbeat >= heartbeat_interval:
                last_heartbeat = now
                emit_heartbeat_summary()

            # Auto-heal GuardianEngine if unhealthy
            if guardian_engine and not guardian_engine.is_healthy():
                guardian_v7.guardian.log(
                    "⚠️ GuardianEngine unhealthy — restarting...", level="warning"
                )
                guardian_engine.stop()
                time.sleep(5)
                guardian_engine.start()

            time.sleep(5)  # Main loop tick frequency

    except KeyboardInterrupt:
        guardian_v7.guardian.log(
            "🛑 Shutdown signal received.", level="warning")
        shutdown_astra_system()
    except Exception as e:
        guardian_v7.guardian.log(
            f"❌ Fatal error in startup_hook: {e}", level="error")
        traceback.print_exc()
        shutdown_astra_system()


# ============================================================
# 🩺 HEARTBEAT TELEMETRY
# ============================================================


def emit_heartbeat_summary():
    """Emit a live summary of Guardian system health and performance metrics."""
    global guardian_engine

    try:
        if not guardian_engine:
            guardian_v7.guardian.log(
                "⚙️ Heartbeat skipped (GuardianEngine not initialized)."
            )
            return

        health = guardian_engine.check_health()
        summary = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "guardian_running": guardian_engine.running,
            "scheduler_health": health.get("scheduler_health", {}),
            "trainer_status": health.get("trainer_status", {}),
            "total_cycles": health.get("scheduler_metrics", {}).get("total_cycles"),
            "success_rate": health.get("scheduler_metrics", {}).get("success_rate"),
            "avg_loss": health.get("scheduler_metrics", {}).get("average_recent_loss"),
        }

        guardian_v7.guardian.log("💓 Guardian Heartbeat Telemetry:")
        guardian_v7.guardian.log(str(summary))

        # 🔄 Record to telemetry hub (Phase 2.9-A)
        if telemetry:
            telemetry.record(summary)
        else:
            guardian_v7.guardian.log(
                "⚠️ TelemetryHub not initialized — skipping export.", level="warning"
            )

    except Exception as e:
        guardian_v7.guardian.log(
            f"⚠️ Heartbeat telemetry failed: {e}", level="warning")
        traceback.print_exc()


# ============================================================
# 🔻 CLEAN SHUTDOWN
# ============================================================


def shutdown_astra_system():
    """Safely shut down all Astra systems."""
    global guardian_engine, _running

    guardian_v7.guardian.log("🧩 Initiating clean shutdown...")
    try:
        _running = False
        if guardian_engine:
            guardian_engine.stop()
            guardian_v7.guardian.log("✅ GuardianEngine stopped.")
    except Exception as e:
        guardian_v7.guardian.log(
            f"⚠️ Error during shutdown: {e}", level="warning")
        traceback.print_exc()

    guardian_v7.guardian.log("🟢 Astra Intelligence shutdown complete.")


# ============================================================
# 🧩 ENTRY POINT
# ============================================================

if __name__ == "__main__":
    guardian = initialize_guardian()
    guardian.guardian.log(
        "🚀 Guardian Startup Hook executing from main context.")
    diagnostics_passed = run_startup_diagnostics()

    if diagnostics_passed:
        # For testing, reduce heartbeat interval to 30 seconds
        start_astra_system(heartbeat_interval=300)
    else:
        guardian.guardian.log(
            "❌ Diagnostics failed — startup aborted.", level="error")
