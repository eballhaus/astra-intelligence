from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)


IMPORTANCE = {
    "panic_exit": "critical",
    "profit_capture": "critical",
    "giveback_reduction": "critical",
    "exit_quality": "critical",
    "horizon_selection": "high",
    "horizon_accuracy": "high",
    "market_regime_behavior": "high",
    "confidence_calibration": "high",
    "symbol_behavior": "medium",
    "speculative_asset_behavior": "medium",
    "portfolio_fit": "medium",
}

CADENCE = {
    "critical": "daily",
    "high": "every_3_days",
    "medium": "weekly",
    "low": "monthly",
}


def _safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "shadow_safe": True,
        "cache_first": True,
        "advisory_only": True,
        "rollback_aware": True,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "automatic_shadow_promotion_enabled": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "thresholds_changed": False,
        "confidence_scoring_changed": False,
        "shadow_logic_changed": False,
        "paper_execution_changed": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "provider_ownership_changed": False,
        "provider_polling_changed": False,
        "aios_behavior_changed": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _age_days(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400.0)
    except Exception:
        try:
            dt = datetime.fromisoformat(f"{raw}T00:00:00+00:00")
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
        except Exception:
            return 0.0


def _score(value: Any, default: float = 0.0) -> float:
    return rounded(clamp(first(value, default)), 3)


def _readiness(score: float) -> str:
    if score >= 85:
        return "institutional_ready"
    if score >= 70:
        return "mature"
    if score >= 50:
        return "developing"
    if score >= 25:
        return "warming_up"
    return "early"


class AstraIntelligenceMaturationSuiteV1(CachedDiagnosticModule):
    """Coordinates existing memory, executive UX, maturity, and learning governance."""

    module_name = "astra_intelligence_maturation_suite_v1"
    mode = "paper_only_shadow_safe_intelligence_maturation_advisory"

    def _fallback(self, reason: str = "insufficient_evidence", **extra: Any) -> dict[str, Any]:
        out = super()._fallback(reason, **extra)
        out.update(_safe_flags())
        return out

    def _memory_governance(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        persistence = dict(tier2.get("learning_persistence_engine_v1") or {})
        memory = status_value(statuses, "long_term_memory_symbol_retrieval_suite_v1")
        historical = status_value(statuses, "historical_intelligence_market_memory_suite_v1")
        lessons = []
        retrieval = _score(memory.get("retrieval_health_score"))
        memory_quality = _score(first(memory.get("symbol_memory_quality_score"), historical.get("market_memory_quality_score"), 0.0))
        for row in (persistence.get("lesson_rows") or [])[:30]:
            if not isinstance(row, dict):
                continue
            category = text(row.get("lesson_category"), "unknown")
            importance = IMPORTANCE.get(category, "low")
            retention = _score(first(row.get("persistence_score"), persistence.get("lesson_retention_score"), 0.0))
            decay = _score(first(row.get("decay_risk"), 100.0 - retention))
            lesson_age = _age_days(row.get("first_seen"))
            reinforcement_age = _age_days(row.get("last_seen"))
            importance_weight = {"critical": 100.0, "high": 78.0, "medium": 55.0, "low": 30.0}[importance]
            priority = clamp(importance_weight * 0.55 + decay * 0.35 + min(10.0, reinforcement_age))
            staleness = clamp(reinforcement_age * 7.0 + decay * 0.35)
            confidence = clamp(to_float(row.get("confidence"), 0.0) * 0.65 + retrieval * 0.20 + memory_quality * 0.15)
            lessons.append({
                "lesson_id": row.get("lesson_id"),
                "lesson_category": category,
                "lesson_summary": row.get("lesson_summary"),
                "importance": importance,
                "memory_importance_score": rounded(importance_weight, 3),
                "memory_retention_score": rounded(retention, 3),
                "memory_decay_risk": rounded(decay, 3),
                "memory_reinforcement_priority": rounded(priority, 3),
                "memory_staleness": rounded(staleness, 3),
                "lesson_age_days": rounded(lesson_age, 2),
                "lesson_reinforcement_age_days": rounded(reinforcement_age, 2),
                "memory_confidence": rounded(confidence, 3),
                "retrieval_health": rounded(retrieval, 3),
                "recommended_cadence": CADENCE[importance],
                "status": row.get("status"),
            })
        lessons.sort(key=lambda row: row["memory_reinforcement_priority"], reverse=True)
        critical = [row for row in lessons if row["importance"] == "critical"]
        at_risk = [row for row in lessons if row["memory_decay_risk"] >= 55 or row["memory_staleness"] >= 55]
        governance_score = clamp(
            to_float(persistence.get("lesson_retention_score"), 0.0) * 0.45
            + retrieval * 0.25
            + memory_quality * 0.20
            + max(0.0, 100.0 - to_float(memory.get("memory_pressure_score"), 0.0)) * 0.10
        )
        return {
            "module": "Astra Unified Memory Governance Engine V1",
            "status": "ok" if lessons or memory else "insufficient_evidence",
            "memory_rows": lessons,
            "critical_lessons": critical[:8],
            "at_risk_lessons": at_risk[:8],
            "reinforcement_schedule": [
                {"importance": importance, "cadence": cadence, "lesson_count": sum(1 for row in lessons if row["importance"] == importance)}
                for importance, cadence in CADENCE.items()
            ],
            "memory_decay_prevention_status": "needs_reinforcement" if at_risk else "stable",
            "memory_governance_score": rounded(governance_score, 3),
            "recommended_memory_focus": text(first((lessons[0] if lessons else {}).get("lesson_category"), persistence.get("recommended_reinforcement_focus"), "collect_more_memory_evidence")),
            "retrieval_health": retrieval,
            "memory_quality_score": memory_quality,
            "heavy_reinforcement_jobs_started": False,
            **_safe_flags(),
        }

    def _executive_experience(self, statuses: dict[str, Any]) -> dict[str, Any]:
        tier1b = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        ask = status_value(statuses, "ask_astra_local_ai_status_v1")
        market = status_value(statuses, "market_breadth_index_intelligence_v1")
        summary = dict(tier2.get("executive_summary") or {})
        departments = list((tier1b.get("executive_intelligence_layer_v1") or {}).get("departments") or [])
        plain = {
            "what_is_happening": f"Astra is operating in a {text(first(market.get('current_index_regime'), 'selective'), 'selective').replace('_', ' ')} market context.",
            "why_it_matters": f"The main performance constraint is {text(summary.get('persistent_weakness'), 'profit capture').replace('_', ' ')}.",
            "what_should_i_do": f"Keep decisions evidence-led and {text(summary.get('recommended_focus'), 'review the strongest opportunities').replace('_', ' ')}.",
            "what_needs_attention": f"Watch {text(summary.get('profit_leak'), 'giveback').replace('_', ' ')} and {text(summary.get('repeated_mistake'), 'repeated mistakes').replace('_', ' ')}.",
            "what_changed": "Tier 3 now coordinates memory, maturity, Copilot, and executive explanations through one cached truth path.",
        }
        copilot_actions = list(copilot.get("top_actions") or [])
        copilot_consistency = 100.0 if copilot_actions else 45.0
        ask_quality = clamp(
            (70.0 if ask.get("structured_fallback_available", True) else 35.0)
            + (20.0 if ask.get("ollama_reachable") else 0.0)
            + (10.0 if ask.get("selected_model") else 0.0)
        )
        market_status = "last_known_good_or_graceful_fallback" if market else "warming_up"
        score = clamp(
            (100.0 if tier1b else 35.0) * 0.25
            + (100.0 if tier2 else 35.0) * 0.25
            + copilot_consistency * 0.20
            + ask_quality * 0.15
            + (85.0 if market else 40.0) * 0.15
        )
        return {
            "module": "Astra Information Architecture & Executive Experience Suite V1",
            "status": "ok",
            "executive_language_engine_v1": {
                "plain_english_summary": plain,
                "technical_scores_hidden_from_default_executive_view": True,
                "raw_diagnostics_preserved_in_learning_center": True,
            },
            "ask_astra_v2": {
                "quality_score": rounded(ask_quality, 3),
                "context_first": True,
                "user_triggered_only": True,
                "main_card_model_details_hidden": True,
                "technical_status_available_in_advanced_diagnostics": True,
                "answer_sections": ["Direct answer", "Why it matters", "What Astra is watching", "What to do next"],
            },
            "unified_copilot_engine_v1": {
                "consistency_score": rounded(copilot_consistency, 3),
                "single_source": "astra_copilot_suite_v1.top_actions",
                "action_count": len(copilot_actions),
                "ordering_shared_across_dashboard_mobile_and_copilot": True,
                "action_categories": ["Buy Now", "Strong Candidate", "Watch", "Manage Position", "Exit Candidate"],
            },
            "opportunity_narrative_engine_v1": {
                "executive_fields": ["Primary Driver", "Catalyst / Theme", "Market Fit", "Expected Horizon", "Main Risk", "Why Astra Likes It", "What Would Invalidate It"],
                "raw_ranking_explanations_hidden_by_default": True,
            },
            "executive_market_context_refinement_v1": {
                "symbols": ["SPY", "QQQ", "IWM", "DIA", "VIX", "BTC"],
                "main_visible_labels": ["Trend", "Leadership", "Participation", "Risk Appetite", "Volatility"],
                "astra_score_is_primary_visible_metric": False,
                "last_known_good_cache_preferred": True,
                "market_context_status": market_status,
            },
            "executive_decision_summary_engine_v2": {
                "today_posture": "Selective and evidence-led.",
                "best_opportunity": text(first((copilot_actions[0] if copilot_actions else {}).get("symbol"), "warming_up")),
                "biggest_weakness": text(summary.get("persistent_weakness"), "profit_capture"),
                "biggest_risk": f"{text(summary.get('profit_leak'), 'giveback')} and {text(summary.get('repeated_mistake'), 'overfiltering')}",
                "tomorrows_focus": text(summary.get("recommended_focus"), "reinforce_high_value_lessons"),
            },
            "executive_experience_score": rounded(score, 3),
            "department_count": len(departments),
            **_safe_flags(),
        }

    def _maturity_gate(self, statuses: dict[str, Any], memory: dict[str, Any], experience: dict[str, Any]) -> dict[str, Any]:
        recovery = status_value(statuses, "astra_recovery_center_v1")
        tier1a = status_value(statuses, "astra_learning_preservation_capacity_v1")
        tier1b = status_value(statuses, "astra_truth_controlled_evolution_executive_v1")
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        foundation = status_value(statuses, "astra_trading_intelligence_foundation_v1")
        portfolio = status_value(statuses, "portfolio_health_summary")
        market = status_value(statuses, "market_breadth_index_intelligence_v1")
        copilot = status_value(statuses, "astra_copilot_suite_v1")
        ask = dict(experience.get("ask_astra_v2") or {})
        categories = {
            "Infrastructure": (100.0 if to_int(status_value(statuses, "unified_learning_diagnostics_v1").get("failed_sources_count"), 0) == 0 else 45.0, "failed sources"),
            "Recovery": (to_float(recovery.get("recovery_health_score"), 55.0), "recovery confidence"),
            "Truth Layer": (100.0 if (tier1b.get("executive_snapshot_truth_reconciliation_v1") or {}).get("status") == "PASS" else 55.0, "closed paper evidence"),
            "Learning Throughput": (to_float((tier1a.get("learning_throughput_preservation_engine_v1") or {}).get("learning_throughput_score"), 45.0), "fresh evidence flow"),
            "Trading Intelligence": (to_float((foundation.get("executive_trading_snapshot_v1") or {}).get("overall_trading_intelligence_score"), 55.0), "lifecycle evidence"),
            "Profit Optimization": (to_float((tier2.get("profit_optimization_engine_v1") or {}).get("profit_capture_score"), 0.0), "profit capture"),
            "Memory Governance": (to_float(memory.get("memory_governance_score"), 0.0), "lesson decay"),
            "Shadow / Controlled Evolution": (65.0 if (tier1b.get("shadow_paper_controlled_evolution_bridge_v1") or {}).get("status") == "candidate" else 45.0, "promotion evidence"),
            "Portfolio Intelligence": (to_float(portfolio.get("portfolio_health_score"), 55.0), "portfolio evidence"),
            "Market Context": (to_float(market.get("index_confidence_score"), 45.0), "market context confidence"),
            "Executive Experience": (to_float(experience.get("executive_experience_score"), 0.0), "executive clarity"),
            "Ask Astra": (to_float(ask.get("quality_score"), 0.0), "context quality"),
        }
        rows = []
        for name, (score, gap) in categories.items():
            score = clamp(score)
            rows.append({
                "category": name,
                "score": rounded(score, 3),
                "status": "healthy" if score >= 70 else "developing" if score >= 45 else "needs_attention",
                "confidence": rounded(clamp(score * 0.75 + (15.0 if statuses else 0.0)), 3),
                "top_gap": gap if score < 70 else "none",
                "readiness_label": _readiness(score),
            })
        overall = sum(row["score"] for row in rows) / max(1, len(rows))
        weakest = min(rows, key=lambda row: row["score"])
        return {
            "module": "Trading Maturity Gate V1",
            "status": "ok",
            "category_rows": rows,
            "overall_astra_maturity_score": rounded(overall, 3),
            "maturity_label": _readiness(overall),
            "top_maturity_gap": weakest["category"],
            "next_best_maturity_focus": weakest["top_gap"],
            "future_upgrade_readiness": "advisory_review_only" if overall >= 70 else "continue_maturation",
            "automatic_behavior_enablement_allowed": False,
            **_safe_flags(),
        }

    def _learning_governance(self, statuses: dict[str, Any], memory: dict[str, Any]) -> dict[str, Any]:
        tier2 = status_value(statuses, "astra_performance_optimization_suite_v1")
        correction = dict(tier2.get("performance_correction_engine_v1") or {})
        persistence = dict(tier2.get("learning_persistence_engine_v1") or {})
        repeated = dict(tier2.get("repeated_mistake_detector_v1") or {})
        bridge = dict(status_value(statuses, "astra_truth_controlled_evolution_executive_v1").get("shadow_paper_controlled_evolution_bridge_v1") or {})
        weakness_map = {row.get("weakness"): row for row in correction.get("weakness_rows") or [] if isinstance(row, dict)}
        signals = {
            "overfiltering": to_float((weakness_map.get("overfiltering") or {}).get("severity"), 0.0),
            "underlearning": to_float((weakness_map.get("underlearning") or {}).get("severity"), 0.0),
            "overconfidence": to_float(status_value(statuses, "conviction_calibration_engine_v1").get("overconfidence_score"), 0.0),
            "underconfidence": to_float(status_value(statuses, "conviction_calibration_engine_v1").get("underconfidence_score"), 0.0),
            "learning_efficiency": to_float(persistence.get("learning_persistence_score"), 0.0),
            "resource_allocation": 100.0 - to_float(status_value(statuses, "adaptive_learning_prioritization_resource_allocation_v1").get("resource_pressure_score"), 0.0),
            "weakness_persistence": to_float(first((correction.get("persistent_weaknesses") or [{}])[0].get("severity") if correction.get("persistent_weaknesses") else 0.0, 0.0)),
            "lesson_decay": to_float(memory.get("memory_decay_prevention_status") == "needs_reinforcement" and persistence.get("lesson_decay_risk") or 0.0, 0.0),
            "evidence_starvation": to_float((weakness_map.get("underlearning") or {}).get("severity"), 0.0),
            "promotion_candidate_quality": to_float((bridge.get("promotion_candidate") or {}).get("promotion_confidence"), 0.0),
        }
        risk_keys = ("overfiltering", "underlearning", "overconfidence", "underconfidence", "weakness_persistence", "lesson_decay", "evidence_starvation")
        strength_keys = ("learning_efficiency", "resource_allocation", "promotion_candidate_quality")
        top_risk = max(risk_keys, key=lambda key: signals[key])
        top_strength = max(strength_keys, key=lambda key: signals[key])
        governance_score = clamp(
            sum(signals[key] for key in strength_keys) / len(strength_keys) * 0.55
            + (100.0 - sum(signals[key] for key in risk_keys) / len(risk_keys)) * 0.45
        )
        return {
            "module": "Autonomous Learning Governance V1",
            "status": "ok",
            "governance_signals": {key: rounded(value, 3) for key, value in signals.items()},
            "governance_score": rounded(governance_score, 3),
            "learning_governance_status": "healthy" if governance_score >= 70 else "developing" if governance_score >= 45 else "needs_attention",
            "top_governance_risk": top_risk,
            "top_governance_strength": top_strength,
            "recommended_governance_focus": f"reduce_{top_risk}",
            "critical_repeated_mistake_count": len(repeated.get("critical_repeated_mistakes") or []),
            "priority_recommendations_only": True,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        memory = self._memory_governance(statuses)
        experience = self._executive_experience(statuses)
        maturity = self._maturity_gate(statuses, memory, experience)
        governance = self._learning_governance(statuses, memory)
        summary = {
            "memory_governance": memory.get("memory_governance_score"),
            "executive_experience": experience.get("executive_experience_score"),
            "maturity_score": maturity.get("overall_astra_maturity_score"),
            "maturity_label": maturity.get("maturity_label"),
            "learning_governance": governance.get("governance_score"),
            "ask_astra_quality": (experience.get("ask_astra_v2") or {}).get("quality_score"),
            "copilot_consistency": (experience.get("unified_copilot_engine_v1") or {}).get("consistency_score"),
            "market_context_status": (experience.get("executive_market_context_refinement_v1") or {}).get("market_context_status"),
            "recommended_focus": maturity.get("next_best_maturity_focus"),
        }
        return with_safety({
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 3 - Intelligence Maturation & Executive Experience Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "unified_memory_governance_v1": memory,
            "information_architecture_executive_experience_v1": experience,
            "trading_maturity_gate_v1": maturity,
            "autonomous_learning_governance_v1": governance,
            "executive_summary": summary,
            "bounded_cached_sources_only": True,
            "full_history_scan_performed": False,
            "dashboard_endpoint_count_added": 0,
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        })
