"""Knowledge-Aware Explanation Engine V1."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class KnowledgeAwareExplanationEngine:
    def __init__(self, state_dir: str = "state", knowledge_base: Any | None = None, scenario_library: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.knowledge_base = knowledge_base
        self.scenario_library = scenario_library

    def _concepts(self) -> dict[str, Any]:
        try:
            concepts = getattr(self.knowledge_base, "concepts", {})
            return concepts if isinstance(concepts, dict) else {}
        except Exception:
            return {}

    def explain_setup(self, setup: str = "quality_momentum") -> dict[str, Any]:
        concepts = self._concepts()
        momentum = concepts.get("momentum", {}) if isinstance(concepts.get("momentum"), dict) else {}
        risk = concepts.get("risk_management", {}) if isinstance(concepts.get("risk_management"), dict) else {}
        sector = concepts.get("sector_rotation", {}) if isinstance(concepts.get("sector_rotation"), dict) else {}
        return {
            "setup": setup,
            "why_it_can_work": f"{setup} can work when price confirmation, liquidity, and follow-through align with the prevailing regime.",
            "why_astra_may_prefer_it": "Astra should prefer it when momentum, entry quality, sector leadership, and risk controls agree.",
            "why_astra_may_avoid_it": "Astra should avoid it when volatility is unstable, the move is extended, or portfolio concentration is already high.",
            "supporting_market_principles": [
                momentum.get("principle", "Momentum can persist when confirmed by volume and relative strength."),
                sector.get("principle", "Sector leadership improves odds when capital rotates into the group."),
                risk.get("principle", "Risk controls keep a good setup from becoming a poor portfolio decision."),
            ],
        }

    def status(self) -> dict[str, Any]:
        concepts = self._concepts()
        scenarios = []
        try:
            scenarios = list(getattr(self.scenario_library, "scenarios", []) or [])
        except Exception:
            scenarios = []
        examples = [self.explain_setup("quality_momentum"), self.explain_setup("earnings_revision_leader"), self.explain_setup("defensive_relative_strength")]
        coverage = min(100.0, (len(concepts) / 11.0) * 70.0 + (len(scenarios) / 6.0) * 30.0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_knowledge_aware_explanation_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "knowledge_explainer_status_v1": True,
            "explanation_types": ["why_setup_works", "why_astra_prefers_it", "why_astra_avoids_it", "supporting_market_principles"],
            "concepts_available": len(concepts),
            "scenario_contexts_available": len(scenarios),
            "sample_explanations": examples,
            "confidence_score": round(coverage, 3),
            "next_recommended_action": "use_explanations_for_dashboard_and_ask_astra_context_without_live_strategy_changes",
            "changes_live_trading": False,
            "changes_rankings": False,
        }
