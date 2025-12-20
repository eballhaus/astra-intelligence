# ============================================================
# === ASTRA PRIME — Meta-Persona Funnel (v2) ================
# ============================================================
"""
AstraPrime (v2)
Unified orchestrator for all Astra personas:
- Combines signals from all agents
- Applies weighting logic
- Outputs final ranked predictions
- Designed for compatibility with dashboard live data
"""

import time
import datetime
import random

from agents.personas.momentum_agent import MomentumAgent
from agents.personas.technical_agent import TechnicalAgent
from agents.personas.volume_agent import VolumeAgent
from agents.personas.risk_agent import RiskAgent
from agents.personas.psychology_agent import PsychologyAgent
from agents.personas.catalyst_agent import CatalystAgent
from agents.personas.neural_agent import NeuralAgent
from agents.personas.main_agent import MainAgent

class GuardianStub:
    def _write_log(self, msg): print(f"[GuardianStub] {msg}")
    def log(self, msg): print(f"[GuardianStub:LOG] {msg}")

class AstraPrime:
    """Meta-persona that fuses all agent signals into final predictions."""

    def __init__(self):
        self.guardian = GuardianStub()

        # --- Initialize personas ---
        self.momentum = MomentumAgent()
        self.technical = TechnicalAgent()
        self.volume = VolumeAgent()
        self.risk = RiskAgent()
        self.psychology = PsychologyAgent()
        self.catalyst = CatalystAgent()
        self.neural = NeuralAgent(guardian=self.guardian)

        self.agents = {
            "momentum": self.momentum,
            "technical": self.technical,
            "volume": self.volume,
            "risk": self.risk,
            "psychology": self.psychology,
            "catalyst": self.catalyst,
            "neural": self.neural
        }

        self.main = MainAgent(self.agents)

        self._last_prediction = {}
        self._prediction_interval = {"day": 1800, "swing": 14400}

    def smart_predict(self, symbol, mode="day"):
        now = time.time()
        last = self._last_prediction.get(symbol, 0)
        if now - last < self._prediction_interval.get(mode, 1800):
            return None
        self._last_prediction[symbol] = now
        return self.analyze([symbol])[0]

    def analyze(self, symbols):
        results = []
        self.guardian.log(f"🚀 AstraPrime analyzing {len(symbols)} assets...")
        for symbol in symbols:
            m = self.momentum.analyze(symbol)
            t = self.technical.analyze(symbol)
            v = self.volume.analyze(symbol)
            r = self.risk.analyze(symbol)
            p = self.psychology.analyze(symbol)
            c = self.catalyst.analyze(symbol)
            n = self.neural.analyze(symbol)

            weights = {"momentum": 0.18, "technical": 0.18, "volume": 0.15,
                       "risk": 0.12, "psychology": 0.12, "catalyst": 0.15, "neural": 0.10}

            score = (m["score"] * weights["momentum"]
                    + t["score"] * weights["technical"]
                    + v["score"] * weights["volume"]
                    + r["score"] * weights["risk"]
                    + p["score"] * weights["psychology"]
                    + c["score"] * weights["catalyst"]
                    + n["score"] * weights["neural"])

            conf = round(score * 100, 2)
            grade = self._grade_from_conf(conf)

            results.append({
                "symbol": symbol,
                "grade": grade,
                "confidence": conf,
                "predicted_target": round(random.uniform(100, 500), 2),
                "stop_loss": round(random.uniform(80, 99), 2),
                "prediction_date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
                "comment": n.get("insight", "Optimized multi-agent signal alignment."),
                "timestamp": datetime.datetime.utcnow().isoformat()
            })

        results = sorted(results, key=lambda x: x["confidence"], reverse=True)
        return results

    def _grade_from_conf(self, conf):
        if conf >= 90: return "A+"
        elif conf >= 80: return "A"
        elif conf >= 70: return "B"
        elif conf >= 60: return "C"
        else: return "D"

astra_prime = AstraPrime()
