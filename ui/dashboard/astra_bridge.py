"""
AstraBridge – Phase-104
-----------------------
Collects, normalizes, and streams intelligence from all active Astra agents
into the dashboard layer. Works with or without Guardian/AstraPrime.

Usage:
    from ui.dashboard.astra_bridge import AstraBridge
    data = AstraBridge().collect(symbols=["AAPL", "TSLA"])
"""

import datetime
import json
from astra_modules.agents import (
    momentum_agent,
    technical_agent,
    volume_agent,
    risk_agent,
    psychology_agent,
    catalyst_agent,
    neural_agent,
)


class AstraBridge:
    """Unified data interface between agents and dashboard."""

    def __init__(self, guardian=None):
        self.guardian = guardian
        self.agent_classes = {
            "MomentumAgent": momentum_agent.MomentumAgent,
            "TechnicalAgent": technical_agent.TechnicalAgent,
            "VolumeAgent": volume_agent.VolumeAgent,
            "RiskAgent": risk_agent.RiskAgent,
            "PsychologyAgent": psychology_agent.PsychologyAgent,
            "CatalystAgent": catalyst_agent.CatalystAgent,
            "NeuralAgent": neural_agent.NeuralAgent,
        }

    def _safe_log(self, msg):
        if self.guardian is not None:
            try:
                self.guardian._write_log(msg)
            except Exception:
                pass

    def collect(self, symbols=None):
        if symbols is None:
            symbols = ["AAPL"]

        results = {}
        timestamp = datetime.datetime.now(datetime.UTC).isoformat()

        for symbol in symbols:
            results[symbol] = {}
            for name, cls in self.agent_classes.items():
                try:
                    agent = cls(self.guardian) if name == "NeuralAgent" else cls()
                    output = agent.analyze(symbol)
                    results[symbol][name] = output
                except Exception as e:
                    results[symbol][name] = {"score": 0.0, "insight": f"{name} failed: {e}"}
                    self._safe_log(f"⚠️ {name} error: {e}")

        results["timestamp"] = timestamp
        return results

    def collect_json(self, symbols=None):
        data = self.collect(symbols)
        return json.dumps(data, indent=2)


if __name__ == "__main__":
    bridge = AstraBridge()
    print(bridge.collect_json(["AAPL", "TSLA"]))
