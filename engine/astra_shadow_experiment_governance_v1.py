"""Governed shadow experiment contract and promotion-readiness diagnostics."""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, now_iso, rounded, to_float, to_int, with_safety

VERSION = "1.0.0"
READINESS_STATES = (
    "RESEARCH_ONLY",
    "EARLY_SIGNAL",
    "REPEATABILITY_PENDING",
    "REGIME_DIVERSITY_PENDING",
    "RISK_REVIEW_PENDING",
    "GUARDED_REVIEW_READY",
    "PAPER_VALIDATION_READY",
    "HUMAN_APPROVAL_REQUIRED",
    "REJECTED",
    "EXPIRED",
)

EXPERIMENT_FIELDS = (
    "experiment_id", "hypothesis", "current_production_paper_baseline", "proposed_change",
    "affected_subsystem", "affected_asset_class", "affected_trade_style", "affected_horizon",
    "affected_regime_or_archetype", "simulated_entry_or_exit_behavior", "expected_benefit",
    "possible_harm", "start_date", "minimum_sample_size", "target_sample_size",
    "success_criteria", "failure_criteria", "stop_conditions", "realistic_execution_assumptions",
    "evidence_sources", "current_state",
)


def experiment_contract(**values: Any) -> dict[str, Any]:
    """Return a normalized diagnostic contract without persisting or applying it."""
    out = {key: values.get(key) for key in EXPERIMENT_FIELDS}
    out["current_state"] = out.get("current_state") or "RESEARCH_ONLY"
    out["automatic_promotion"] = False
    out["human_approval_required"] = True
    out["paper_execution_changed"] = False
    return out


class AstraShadowExperimentGovernanceV1(CachedDiagnosticModule):
    module_name = "astra_shadow_experiment_governance_v1"
    mode = "shadow_only_governed_experiment_readiness"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        shadow = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        comparison = dict(statuses.get("shadow_vs_paper_performance_attribution_v1") or {})
        correction = dict(statuses.get("shadow_correction_validation_attribution_v1") or {})
        replay = dict(statuses.get("replay_counterfactual_learning_v2") or {})
        sample = max(
            to_int(shadow.get("completed_lifecycles"), 0),
            to_int(shadow.get("shadow_completed_lifecycles"), 0),
            to_int(comparison.get("shadow_completed_lifecycle_count"), 0),
        )
        baseline_count = max(to_int(comparison.get("canonical_closed_trade_count"), 0), to_int(comparison.get("paper_trade_count"), 0))
        repeatability = comparison.get("shadow_alpha_confidence") or comparison.get("shadow_confidence")
        repeatability_score = to_float(repeatability, 0.0)
        regime_diversity = to_float(shadow.get("regime_diversity_score"), 0.0)
        drawdown_review = comparison.get("drawdown") is not None or comparison.get("paper_drawdown") is not None
        if sample <= 0:
            readiness = "RESEARCH_ONLY"
        elif sample < 20:
            readiness = "EARLY_SIGNAL"
        elif repeatability_score < 60:
            readiness = "REPEATABILITY_PENDING"
        elif regime_diversity < 40:
            readiness = "REGIME_DIVERSITY_PENDING"
        elif not drawdown_review:
            readiness = "RISK_REVIEW_PENDING"
        else:
            readiness = "GUARDED_REVIEW_READY"
        return with_safety({
            "endpoint": "/api/astra_shadow_experiment_governance_v1",
            "version": VERSION,
            "status": "ok" if sample > 0 else "insufficient_evidence",
            "generated_at": now_iso(),
            "experiment_contract_schema": list(EXPERIMENT_FIELDS),
            "active_experiments": to_int(shadow.get("active_experiments"), 0),
            "completed_experiments": to_int(shadow.get("completed_experiments"), 0),
            "shadow_observations": to_int(shadow.get("shadow_opportunities"), 0),
            "shadow_lifecycles": sample,
            "exact_paper_baseline_required": True,
            "baseline_coverage": {"paper_closed_trade_count": baseline_count, "baseline_available": baseline_count > 0, "source": "canonical broker-confirmed paper metrics"},
            "repeatability_score": rounded(repeatability_score, 3),
            "regime_diversity_score": rounded(regime_diversity, 3),
            "drawdown_reviewed": drawdown_review,
            "opportunity_cost_reviewed": comparison.get("opportunity_cost_reduction") is not None or bool(statuses.get("opportunity_cost_learning")),
            "counterfactual_disagreements": to_int(replay.get("disagreements"), 0) + to_int(correction.get("disagreements"), 0),
            "current_readiness": readiness,
            "readiness_states": list(READINESS_STATES),
            "promotion_stages": {
                "stage_0": "shadow_only",
                "stage_1": "advisory",
                "stage_2": "5_percent_paper_micro_test_requires_human_approval",
                "stage_3": "10_to_25_percent_expansion_requires_human_approval",
                "stage_4": "paper_default_not_enabled",
                "stage_5": "permanent_adoption_requires_human_approval",
            },
            "current_stage": 0,
            "promotion_candidates": [],
            "automatic_promotion": False,
            "automatic_promotions_enabled": False,
            "human_approval_required": True,
            "stop_conditions_enforced": True,
            "equity_crypto_separation": True,
            "replay_is_not_paper_truth": True,
            "shadow_is_not_paper_truth": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
        })
