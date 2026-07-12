"""Evidence-consumption, lesson quality, and learning-velocity diagnostics.

The module only credits explicit consumption/influence fields.  A status being
present in a unified payload is deliberately not treated as evidence consumed.
"""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, clamp, now_iso, rounded, to_int, with_safety

VERSION = "1.0.0"

EVIDENCE_SPECS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("broker_truth", ("alpaca_paper_broker", "broker_truth_accumulation_v2", "canonical_outcome_audit_v1"), ("Performance", "Governance", "Cortex")),
    ("incomplete_broker_lifecycle", ("trade_lifecycle_audit_truth_horizon_integrity_suite_v1",), ("Lifecycle", "Cortex")),
    ("canonical_outcomes", ("shadow_vs_paper_performance_attribution_v1", "canonical_outcome_audit_v1"), ("Performance", "Learning")),
    ("shadow", ("realistic_shadow_evidence_learning_lab_v1", "shadow_vs_paper_performance_attribution_v1"), ("Shadow", "Copilot")),
    ("replay", ("replay_counterfactual_learning_v2", "ranking_tournament_engine_v1", "exit_tournament_engine_v1"), ("Replay", "Shadow")),
    ("counterfactual", ("replay_counterfactual_learning_v2", "opportunity_cost_learning"), ("Opportunity Cost", "Shadow")),
    ("provider_context", ("market_context_learning_suite_v1", "context_evidence_expansion_suite_v1"), ("Market Intelligence", "Copilot")),
    ("symbol_memory", ("long_term_memory_symbol_retrieval_suite_v1", "symbol_intelligence_behavioral_memory_v1"), ("Symbol Intelligence", "Copilot")),
    ("regime", ("market_transition_detection_v1", "market_condition_attribution_v1", "market_regime_similarity_engine_v1"), ("Regime", "Governance")),
    ("archetype", ("trade_archetype_regime", "trade_family_intelligence_v1"), ("Trade Intelligence", "Copilot")),
    ("catalyst", ("catalyst_lifecycle_intelligence_v1", "catalyst_persistence_decay_curves_v2"), ("Catalyst", "Copilot")),
    ("sector", ("cross_sector_capital_flow_memory_v1", "etf_sector_rotation_intelligence_v1"), ("Market Intelligence", "Ranking Diagnostics")),
    ("breadth", ("market_breadth_index_intelligence_v1",), ("Market Intelligence", "Regime")),
    ("opportunity_cost", ("opportunity_cost_learning",), ("Opportunity Cost", "Ranking Diagnostics")),
    ("historical_similarity", ("long_term_memory_symbol_retrieval_suite_v1", "market_regime_similarity_engine_v1"), ("Historical Similarity", "Copilot")),
    ("trade_style", ("trade_style_intelligence_audit_v1", "trade_family_intelligence_v1"), ("Trade Intelligence", "Learning")),
    ("horizon", ("multi_horizon_intelligence_adaptive_lifecycle_suite_v1", "horizon_performance_dashboard"), ("Horizon Intelligence", "Learning")),
    ("entry_readiness", ("equity_horizon_qualification_completion_v2", "astra_trading_intelligence_foundation_v1"), ("Entry Readiness", "Copilot")),
    ("exit_readiness", ("exit_readiness_diagnostics_v1", "profit_capture_peak_decay_exit_validation_suite_v1"), ("Exit Readiness", "Copilot")),
)


def _first_number(payloads: list[dict[str, Any]], keys: tuple[str, ...]) -> int:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
    return 0


class AstraIntelligenceEffectivenessLearningVelocityV1(CachedDiagnosticModule):
    module_name = "astra_intelligence_effectiveness_learning_velocity_v1"
    mode = "shadow_analysis_evidence_consumption_and_learning_velocity"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        evidence_rows: list[dict[str, Any]] = []
        total_available = total_indexed = total_retrieved = total_consumed = total_influenced = 0
        for evidence_class, keys, consumers in EVIDENCE_SPECS:
            payloads = [dict(statuses.get(key) or {}) for key in keys if isinstance(statuses.get(key), dict)]
            available = _first_number(payloads, ("evidence_count", "supporting_evidence_count", "observation_count", "tracked_records", "canonical_closed_trade_count", "shadow_opportunities"))
            indexed = _first_number(payloads, ("indexed_records", "indexed_evidence_count", "retrieval_indexed_count"))
            retrieved = _first_number(payloads, ("retrieved_count", "lessons_retrieved", "retrieval_count", "evidence_retrieved"))
            consumed = _first_number(payloads, ("consumed_count", "evidence_consumed", "lessons_consumed", "recommendations_influenced"))
            influenced = _first_number(payloads, ("influenced_decisions", "recommendations_influenced", "decision_fields_influenced"))
            if available and not indexed:
                indexed_status = "not_proven"
            else:
                indexed_status = "indexed" if indexed > 0 else "not_proven"
            consumption_status = "consumed" if consumed > 0 else "available_not_proven" if available > 0 else "not_available"
            evidence_rows.append({
                "evidence_class": evidence_class,
                "intended_consumers": list(consumers),
                "available": available,
                "indexed": indexed,
                "retrieved": retrieved,
                "consumed": consumed,
                "decision_influenced": influenced,
                "indexed_status": indexed_status,
                "consumption_status": consumption_status,
                "passive_presence_excluded": True,
                "source_keys": list(keys),
            })
            total_available += available
            total_indexed += indexed
            total_retrieved += retrieved
            total_consumed += consumed
            total_influenced += influenced

        quality = dict(statuses.get("evidence_quality_scoring_v1") or {})
        librarian = dict(statuses.get("astra_tier2a_librarian_executive_truth_layer_v1") or {})
        retention = dict(statuses.get("learning_acceleration_retention_suite_v1") or {})
        shadow = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        backlog = _first_number([retention, shadow], ("backlog_count", "learning_backlog_count", "pending_lessons", "pending_items"))
        lesson_count = _first_number([librarian], ("lessons_organized", "lesson_count", "lessons"))
        validated = _first_number([librarian, retention], ("validated_lessons", "lessons_validated", "validated_count"))
        contradicted = _first_number([librarian, retention], ("contradicted_lessons", "lessons_contradicted", "contradicted_count"))
        expired = _first_number([librarian, retention], ("expired_lessons", "lessons_expired", "expired_count"))
        velocity = _first_number([retention, shadow], ("processing_throughput", "learning_velocity", "lessons_created_today", "completed_lifecycles"))
        consumption_ratio = rounded(total_consumed * 100.0 / max(1, total_available), 3)
        influence_ratio = rounded(total_influenced * 100.0 / max(1, total_consumed), 3)
        status = "ok" if total_available > 0 else "insufficient_evidence"
        return with_safety({
            "endpoint": "/api/astra_intelligence_effectiveness_learning_velocity_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "evidence_chain": evidence_rows,
            "evidence_available": total_available,
            "evidence_indexed": total_indexed,
            "evidence_retrieved": total_retrieved,
            "evidence_consumed": total_consumed,
            "decision_fields_influenced": total_influenced,
            "evidence_consumption_ratio": consumption_ratio,
            "influence_trace_coverage_pct": influence_ratio,
            "passive_presence_excluded": True,
            "consumer_coverage": {row["evidence_class"]: row["intended_consumers"] for row in evidence_rows},
            "missing_consumers": [row["evidence_class"] for row in evidence_rows if row["available"] and not row["consumed"]],
            "stale_consumers": [],
            "outdated_schema_consumers": [],
            "lesson_quality": {
                "raw_evidence_count": to_int(quality.get("raw_evidence_count"), total_available),
                "weighted_evidence_count": quality.get("weighted_evidence_count"),
                "average_evidence_quality": quality.get("average_evidence_quality"),
                "quality_bucket": quality.get("quality_bucket") or "insufficient_evidence",
                "quality_source": "evidence_quality_scoring_v1",
            },
            "lesson_state_counts": {
                "lessons": lesson_count,
                "validated_advisory_lessons": validated,
                "contradicted": contradicted,
                "expired": expired,
            },
            "learning_velocity": {
                "raw_observations_created": total_available,
                "canonical_outcomes_created": _first_number([statuses.get("shadow_vs_paper_performance_attribution_v1") or {}], ("canonical_closed_trade_count", "paper_trade_count")),
                "lessons_created": lesson_count,
                "lessons_validated": validated,
                "lessons_contradicted": contradicted,
                "lessons_expired": expired,
                "lessons_retrieved": total_retrieved,
                "lessons_consumed": total_consumed,
                "recommendations_influenced": total_influenced,
                "processing_throughput": velocity,
            },
            "backlog_governance": {
                "backlog_count": backlog,
                "backlog_age": retention.get("backlog_age") or retention.get("oldest_backlog_age"),
                "stale_backlog": retention.get("stale_backlog") or retention.get("stale_backlog_count"),
                "categories": ["awaiting_canonical_outcome", "awaiting_broker_truth", "awaiting_consumer", "awaiting_sample_size", "awaiting_human_review", "contradicted", "expired"],
                "priority_policy": "decision_impact_evidence_maturity_consumer_gap_age_safety",
            },
            "effectiveness_scorecard": {
                "evidence_utilization": consumption_ratio,
                "consumer_coverage": rounded(sum(1 for row in evidence_rows if row["consumed"]) * 100.0 / max(1, len(evidence_rows)), 3),
                "lesson_quality": quality.get("average_evidence_quality"),
                "knowledge_freshness": quality.get("recency") or "not_measured",
                "retrieval_latency": (statuses.get("astra_knowledge_warehouse_v1") or {}).get("latency_ms") or "not_measured",
                "influence_trace_coverage": influence_ratio,
                "broker_truth_confirmation": (statuses.get("shadow_vs_paper_performance_attribution_v1") or {}).get("canonical_closed_trade_count", 0),
                "shadow_experiment_health": shadow.get("status") or "not_measured",
                "contradiction_rate": rounded(contradicted * 100.0 / max(1, lesson_count), 3),
                "learning_velocity": velocity,
                "backlog_health": "measured" if backlog else "not_proven",
                "promotion_readiness": "disabled_by_policy",
                "storage_index_health": (statuses.get("astra_knowledge_warehouse_v1") or {}).get("index_coverage_pct"),
            },
            "promotion_enabled": False,
            "automatic_promotions_enabled": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
        })
