"""
astra_prime.py — Phase-90
Astra’s central intelligence layer:
- Orchestrates all agents
- Extracts unified feature/state bundles
- Routes data to NeuralAgent + PaperTrader
- Supports hybrid learning and multi-agent scoring
"""

class AstraPrime:
    def __init__(self, agents, replay_buffer=None, paper_trader=None):
        """
        agents = {
            "momentum": MomentumAgent(),
            "volume": VolumeAgent(),
            "risk": RiskAgent(),
            "psychology": PsychologyAgent(),
            "catalyst": CatalystAgent(),
            "technical": TechnicalAgent(),
            "neural": NeuralAgent(),
        }
        """

        self.agents = agents
        self.replay_buffer = replay_buffer
        self.paper_trader = paper_trader

        # Phase-90 Weighting System
        self.weights = {
            "momentum": 0.20,
            "volume": 0.15,
            "risk": 0.10,
            "psychology": 0.10,
            "catalyst": 0.10,
            "technical": 0.15,
            "neural": 0.20
        }

    # -----------------------------------------------------------
    # Safe agent compute
    # -----------------------------------------------------------
    def safe_compute(self, agent, agent_name, data):
        try:
            result = agent.compute(data)

            # Risk agent returns (score, risk_level, reasoning)
            if agent_name == "risk":
                score, risk_level, reasoning = result
                return {
                    "score": score,
                    "risk_level": risk_level,
                    "reasoning": reasoning
                }

            # All other agents return (score, reasoning)
            score, reasoning = result
            return {"score": score, "reasoning": reasoning}

        except Exception as e:
            return {
                "score": 50,
                "reasoning": f"{agent_name} failed: {e}"
            }

    # -----------------------------------------------------------
    # Phase-90 Data Aggregation
    # -----------------------------------------------------------
    def aggregate(self, data_bundle):
        outputs = {}
        weighted_sum = 0
        total_weight = 0

        for name, agent in self.agents.items():
            agent_data = data_bundle.get(name)
            out = self.safe_compute(agent, name, agent_data)
            outputs[name] = out

            w = self.weights.get(name, 0)
            weighted_sum += out["score"] * w
            total_weight += w

        final_score = weighted_sum / total_weight if total_weight else 50
        final_score = max(0, min(100, final_score))

        # Convert numeric → grade
        grade = (
            "A+" if final_score >= 90 else
            "A"  if final_score >= 80 else
            "B"  if final_score >= 70 else
            "C"  if final_score >= 60 else
            "D"
        )

        # -------------------------------------------------------
        # Learning / Replay Buffer Integration
        # -------------------------------------------------------
        if self.paper_trader:
            self.paper_trader.open_trade(
                symbol=data_bundle.get("symbol", ""),
                price=data_bundle.get("current_price", 0),
                direction="long",
                meta={
                    "state": data_bundle,   #  Phase-90 state object
                    "prediction": final_score,
                    "grade": grade
                }
            )

        if self.replay_buffer:
            self.replay_buffer.add(
                state=data_bundle,
                prediction=final_score,
                outcome=None  # updated when trade closes
            )

        return {
            "final_score": final_score,
            "grade": grade,
            "agent_details": outputs
        }
