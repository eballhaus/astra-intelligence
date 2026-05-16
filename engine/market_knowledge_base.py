"""Market Knowledge Base V1.

Local-only structured market concepts used for explanations and learning context.
This module does not call providers, write files, or change trading behavior.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class MarketKnowledgeBase:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.concepts: dict[str, dict[str, Any]] = {
            "trend_analysis": {
                "principle": "Price direction and persistence help separate continuation setups from mean-reversion risk.",
                "decision_use": "Prefer long exposure when trend alignment supports follow-through.",
                "signals": ["higher_highs", "moving_average_slope", "relative_strength"],
            },
            "support_resistance": {
                "principle": "Prior reaction zones can define favorable entries, invalidation levels, and profit targets.",
                "decision_use": "Avoid chasing far above support unless momentum and catalysts justify it.",
                "signals": ["prior_high_low", "volume_node", "breakout_retest"],
            },
            "momentum": {
                "principle": "Strong relative and absolute momentum can persist when liquidity, volume, and catalysts agree.",
                "decision_use": "Rank candidates higher when momentum is confirmed and not already exhausted.",
                "signals": ["relative_strength", "rate_of_change", "volume_expansion"],
            },
            "volatility": {
                "principle": "Volatility changes position sizing, stop distance, and probability of follow-through.",
                "decision_use": "Reduce size or require stronger confirmation during unstable volatility regimes.",
                "signals": ["atr", "realized_volatility", "gap_risk"],
            },
            "valuation": {
                "principle": "Valuation frames expectation risk, especially when growth assumptions are crowded.",
                "decision_use": "Use valuation as context rather than a short-term timing trigger.",
                "signals": ["multiples", "growth_quality", "margin_profile"],
            },
            "earnings": {
                "principle": "Earnings reset expectations and can create catalysts, gaps, and post-event drift.",
                "decision_use": "Treat pre-earnings exposure and post-earnings confirmation differently.",
                "signals": ["earnings_date", "surprise", "guidance", "estimate_revision"],
            },
            "sector_rotation": {
                "principle": "Capital often clusters into leading sectors as macro and liquidity conditions shift.",
                "decision_use": "Prefer candidates aligned with sector leadership and avoid lagging groups.",
                "signals": ["sector_relative_strength", "breadth", "leadership_concentration"],
            },
            "macro_economics": {
                "principle": "Rates, inflation, credit, currency, and liquidity shape risk appetite and duration sensitivity.",
                "decision_use": "Adapt risk exposure when macro conditions pressure equity multiples or cyclicals.",
                "signals": ["rates", "dollar", "credit_spreads", "inflation"],
            },
            "risk_management": {
                "principle": "Survival and consistency require sizing, stops, diversification, and explicit invalidation.",
                "decision_use": "Never let confidence override portfolio concentration and drawdown controls.",
                "signals": ["max_loss", "position_size", "correlation", "drawdown"],
            },
            "portfolio_construction": {
                "principle": "A good idea can still be a poor portfolio addition if exposures overlap too much.",
                "decision_use": "Balance conviction with sector, factor, and correlation concentration.",
                "signals": ["sector_exposure", "factor_overlap", "cash_buffer"],
            },
            "behavioral_finance": {
                "principle": "Crowding, recency bias, panic, and euphoria alter price behavior around extremes.",
                "decision_use": "Require evidence when sentiment is stretched or reversals become likely.",
                "signals": ["sentiment_extreme", "crowding", "capitulation", "fomo"],
            },
        }

    def status(self) -> dict[str, Any]:
        total = len(self.concepts)
        available = len([v for v in self.concepts.values() if v.get("principle") and v.get("decision_use")])
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_market_knowledge_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "market_knowledge_status_v1": True,
            "concepts_total": total,
            "concepts_available": available,
            "knowledge_coverage_pct": round((available / max(1, total)) * 100.0, 3),
            "concept_names": list(self.concepts.keys()),
            "concepts": self.concepts,
            "confidence_score": round((available / max(1, total)) * 100.0, 3),
            "next_recommended_action": "use_knowledge_base_to_explain_shadow_decisions_without_changing_rankings",
            "changes_live_trading": False,
            "changes_rankings": False,
        }
