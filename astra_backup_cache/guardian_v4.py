"""
GuardianV4 – Adaptive Defense Layer
----------------------------------------------------
Purpose:
- Monitors signals or data for problems
- Assigns a "risk level" to each signal
- Logs results safely to a file
- Can isolate (pause) a part of the system if needed
"""

import os
import json
import time
import hashlib
import traceback
from datetime import datetime, timezone

# Optional AI helper (if available)
try:
    from astra_modules.agents.neural_agent import NeuralAgent
except ImportError:
    NeuralAgent = None


# ==========================================================
# Helper: Merkle Hash (keeps log history secure)
# ==========================================================
def merkle_hash(events):
    """Create a single secure hash from all log events."""
    if not events:
        return hashlib.sha256(b"EMPTY").hexdigest()

    layer = [hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest() for e in events]
    while len(layer) > 1:
        next_layer = []
        for i in range(0, len(layer), 2):
            a = layer[i]
            b = layer[i + 1] if i + 1 < len(layer) else a
            next_layer.append(hashlib.sha256((a + b).encode()).hexdigest())
        layer = next_layer
    return layer[0]


# ==========================================================
# Core Defense Engine
# ==========================================================
class DefenseCoreV4:
    """Main decision-maker for risk analysis."""

    def __init__(self):
        self.risk_index = 0.0
        self.policy_agent = NeuralAgent() if NeuralAgent else None

    def analyze(self, signal):
        """Assign a risk score to the input signal (0 = safe, 1 = risky)."""
        base_risk = 0.5

        if isinstance(signal, (int, float)):
            base_risk = min(1.0, max(0.0, abs(signal) / 10.0))
        elif isinstance(signal, dict) and signal:
            values = [v for v in signal.values() if isinstance(v, (int, float))]
            if values:
                base_risk = sum(values) / (len(values) * 10 + 1)

        # Adjust risk slightly using AI if available
        if self.policy_agent:
            try:
                adjustment = self.policy_agent.evaluate(signal)
                base_risk = (base_risk + adjustment) / 2
            except Exception:
                pass

        # Smooth out the risk trend
        self.risk_index = (self.risk_index * 0.9) + (base_risk * 0.1)
        return base_risk

    def decide(self, risk):
        """Return an action name based on risk level."""
        if risk < 0.3:
            return "ALLOW"
        elif risk < 0.7:
            return "MONITOR"
        else:
            return "ISOLATE"


# ==========================================================
# Snapshot + Rollback System
# ==========================================================
class IsolationManager:
    """Keeps backup copies of system states so we can roll back."""

    def __init__(self):
        self.snapshots = {}

    def snapshot(self, key, state):
        """Save a copy of some data for recovery."""
        self.snapshots[key] = (time.time(), state)

    def restore(self, key):
        """Load a previously saved copy."""
        if key in self.snapshots:
            _, state = self.snapshots[key]
            return state
        return None


# ==========================================================
# Secure Event Log (Audit)
# ==========================================================
class AuditLedger:
    """Writes all events (decisions, errors, etc.) to a secure JSON file."""

    def __init__(self, log_path="guardian_audit.json"):
        self.log_path = log_path
        self.events = []

        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "events" in data:
                        self.events = data["events"]
                    elif isinstance(data, list):
                        self.events = data
            except Exception:
                self.events = []

    def record(self, event_type, payload):
        """Save one event entry to the log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "payload": payload,
            "hash": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        }
        self.events.append(entry)
        self.commit()

    def commit(self):
        """Write everything to disk safely."""
        root = merkle_hash(self.events)
        with open(self.log_path, "w") as f:
            json.dump({"root": root, "events": self.events}, f, indent=2)


# ==========================================================
# Threat Analyzer
# ==========================================================
class ThreatAnalyzer:
    """Connects risk analysis + audit logging."""

    def __init__(self, core, audit):
        self.core = core
        self.audit = audit

    def process(self, signal):
        """Evaluate a signal, log it, and return the result."""
        risk = self.core.analyze(signal)
        action = self.core.decide(risk)
        self.audit.record("analysis", {"risk": risk, "action": action})
        return action, risk


# ==========================================================
# GuardianV4 Main System
# ==========================================================
class GuardianV4:
    """Main Guardian system that coordinates everything."""

    def __init__(self):
        self.core = DefenseCoreV4()
        self.audit = AuditLedger()
        self.isolation = IsolationManager()
        self.analyzer = ThreatAnalyzer(self.core, self.audit)

    def run_safe(self, func, *args, **kwargs):
        """Run a function safely. If it crashes, log the error."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            tb = traceback.format_exc()
            self.audit.record("error", {"exception": str(e), "traceback": tb})
            self.isolation.snapshot("last_failure", {"error": str(e), "traceback": tb})
            return None

    def evaluate_signal(self, signal):
        """Take a signal and decide how risky it is."""
        action, risk = self.analyzer.process(signal)
        if action == "ISOLATE":
            self.isolation.snapshot("isolation_event", signal)
        return {"action": action, "risk": risk}

    def broadcast_health(self):
        """Return a short health summary for dashboards."""
        return {
            "risk_index": round(self.core.risk_index, 3),
            "event_count": len(self.audit.events),
            "latest_action": self.audit.events[-1]["payload"]["action"]
            if self.audit.events else "N/A",
        }


# ==========================================================
# Create the shared Guardian instance
# ==========================================================
guardian = GuardianV4()
