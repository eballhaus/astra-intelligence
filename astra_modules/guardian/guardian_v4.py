"""
guardian_v3.py → GuardianV4
----------------------------------------------------
Astra Phase-90 / GuardianV4: Adaptive Defense Layer
----------------------------------------------------
Features:
- AI-driven defense engine (rule + policy hybrid)
- Merkle-based audit ledger for integrity
- Isolation & rollback subsystem (self-healing)
- Unified Defense Interface (GuardianAPI)
- Backward compatibility (GuardianV3Compat)
"""

import os
import json
import time
import hashlib
import traceback
from datetime import datetime
import pandas as pd

# Optional connection to NeuralAgent micro-models
try:
    from astra_modules.agents.neural_agent import NeuralAgent
except ImportError:
    NeuralAgent = None


# ==========================================================
# UTILITY HELPERS
# ==========================================================

def merkle_hash(events):
    """Compute a Merkle root hash for audit logs."""
    if not events:
        return hashlib.sha256(b"EMPTY").hexdigest()
    layer = [hashlib.sha256(json.dumps(e, sort_keys=True).encode()).hexdigest() for e in events]
    while len(layer) > 1:
        nxt = []
        for i in range(0, len(layer), 2):
            a = layer[i]
            b = layer[i + 1] if i + 1 < len(layer) else a
            nxt.append(hashlib.sha256((a + b).encode()).hexdigest())
        layer = nxt
    return layer[0]


# ==========================================================
# CORE DEFENSE ENGINE
# ==========================================================

class DefenseCoreV4:
    """Hybrid static + AI policy defense engine."""

    def __init__(self):
        self.threat_count = 0
        self.risk_index = 0.0
        self.policy_agent = NeuralAgent() if NeuralAgent else None

    def analyze(self, signal):
        """Assign dynamic risk score from signal."""
        base_risk = 0.5
        if isinstance(signal, (int, float)):
            base_risk = min(1.0, max(0.0, abs(signal) / 10.0))
        elif isinstance(signal, dict):
            base_risk = sum(v for v in signal.values() if isinstance(v, (int, float))) / (len(signal) * 10 + 1)

        if self.policy_agent:
            try:
                policy_adj = self.policy_agent.evaluate(signal)
                base_risk = min(1.0, max(0.0, (base_risk + policy_adj) / 2))
            except Exception:
                pass

        self.risk_index = (self.risk_index * 0.9) + (base_risk * 0.1)
        return base_risk

    def decide(self, risk_score):
        """Determine action tier based on risk."""
        if risk_score < 0.3:
            return "ALLOW"
        elif risk_score < 0.7:
            return "MONITOR"
        else:
            return "ISOLATE"


# ==========================================================
# ISOLATION + ROLLBACK
# ==========================================================

class IsolationManager:
    """Manages sandbox and rollback recovery states."""

    def __init__(self):
        self.snapshots = {}

    def snapshot(self, key, state):
        """Save snapshot for recovery."""
        self.snapshots[key] = (time.time(), state)

    def restore(self, key):
        """Restore from snapshot."""
        if key in self.snapshots:
            _, state = self.snapshots[key]
            return state
        return None


# ==========================================================
# AUDIT LEDGER
# ==========================================================

class AuditLedger:
    """Merkle-audited immutable log for forensic integrity."""

    def __init__(self, log_path="guardian_audit.json"):
        self.log_path = log_path
        self.events = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    self.events = json.lo
