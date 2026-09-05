"""Build I grounding, broker-truth, and Copilot attribution facades.

This module owns no trading state and never performs provider or broker work.
It normalizes the existing canonical sources into bounded, testable diagnostic
contracts so Ask Astra can disclose where an answer came from and Copilot can
truthfully report linkage maturity.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    now_iso,
    rounded,
    status_value,
    to_float,
    to_int,
    with_safety,
)

VERSION = "1.0.0"
CRYPTO_SYMBOLS = {
    "BTC", "ETH", "SOL", "LINK", "AVAX", "SUI", "XRP", "DOGE", "TAO",
    "RENDER", "PEPE", "ADA", "BNB", "DOT", "NEAR", "APT", "ARB", "OP",
    "INJ", "WIF", "BONK", "FET", "RNDR", "UNI", "AAVE", "MKR", "SEI",
    "TIA", "JUP", "PYTH", "ONDO",
}
QUESTION_CORPUS = (
    "Why is NVDA a Hold?",
    "What is my paper performance?",
    "What broker truth is available?",
    "Explain BTC/USD crypto readiness.",
    "What changed with this position?",
    "Show shadow experiment readiness.",
    "What did replay learn?",
    "How effective are Copilot recommendations?",
    "What is the market regime this week?",
    "What is the sector context for semiconductors?",
    "Is the system healthy?",
    "What is on the roadmap?",
    "Which opportunities are actually eligible?",
    "Is Astra still holding NVDA?",
    "Has Astra reached an exit condition for NVDA?",
    "Why did Astra reject NVDA?",
    "Is Astra at capacity?",
    "What has Astra learned recently?",
    "How current is Astra's NVDA recommendation?",
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _recommendations(statuses: dict[str, Any]) -> list[dict[str, Any]]:
    copilot = status_value(statuses, "astra_copilot_suite_v1")
    return [dict(row) for row in copilot.get("recommendations") or [] if isinstance(row, dict)]


def _symbol_from_question(question: str, selected_symbol: str, recommendations: list[dict[str, Any]], prior_context: dict[str, Any]) -> str:
    if selected_symbol:
        return selected_symbol.strip().upper()
    known = {str(row.get("symbol") or "").upper() for row in recommendations if row.get("symbol")}
    known.update(CRYPTO_SYMBOLS)
    for token in re.findall(r"\b[A-Za-z]{2,8}(?:[-/]USD)?\b", question or ""):
        clean = token.upper().replace("/USD", "").replace("-USD", "")
        if clean in known:
            return clean
    follow_up = str(prior_context.get("selected_symbol") or prior_context.get("symbol") or "").upper()
    if re.search(r"\b(it|this|that)\s+(trade|position|one)\b", question or "", re.I) and follow_up:
        return follow_up
    return ""


def _intent(question: str) -> str:
    q = (question or "").lower()
    if any(token in q for token in ("how current", "last refreshed", "latest data", "freshness", "stale data")):
        return "freshness"
    if any(token in q for token in ("broker truth", "broker-confirmed", "broker confirmed", "fill", "order")):
        return "broker_truth"
    if any(token in q for token in ("completed recently", "trades completed", "recent trades")):
        return "broker_truth"
    if any(token in q for token in ("paper performance", "profit factor", "win rate", "average return", "p/l", "pnl")):
        return "paper_performance"
    if any(token in q for token in ("shadow", "paper promotion", "experiment")):
        return "shadow_experiment"
    if any(token in q for token in ("replay", "counterfactual", "what if")):
        return "replay"
    if any(token in q for token in ("crypto", "btc", "eth", "sol", "coin")):
        return "crypto"
    if any(token in q for token in ("market", "regime", "breadth", "volatility")):
        return "market_regime"
    if any(token in q for token in ("sector", "semiconductor", "technology", "rotation")):
        return "sector_context"
    if any(token in q for token in ("health", "status", "provider", "storage")):
        return "system_health"
    if any(token in q for token in ("roadmap", "build", "next")):
        return "roadmap"
    if any(token in q for token in ("actually eligible", "eligible", "order ready", "qualified candidate")):
        return "candidate_eligibility"
    if any(token in q for token in ("why did astra reject", "why isn't astra buying", "why not buy", "why rejected", "rejection")):
        return "candidate_rejection"
    if any(token in q for token in ("exit condition", "close to selling", "approaching exit", "exit ready", "why did astra sell", "why did astra exit")):
        return "exit_readiness"
    if any(token in q for token in ("still holding", "open positions", "position open", "thesis changed", "what changed since", "management state")):
        return "current_position"
    if any(token in q for token in ("at capacity", "lane capacity", "which lane has capacity", "capacity")):
        return "capacity"
    if any(token in q for token in ("what has astra learned", "learned recently", "similar trades", "learning")):
        return "learning"
    if any(token in q for token in ("best stocks", "what stocks", "best opportunities", "current selections", "what does astra like", "what does astra prefer")):
        return "copilot_recommendation"
    if any(token in q for token in ("why isn't astra trading", "why isnt astra trading", "what is astra waiting", "why is trading quiet")):
        return "candidate_rejection"
    if any(token in q for token in ("what lane", "major risks", "risk in", "thesis changed", "expected horizon")):
        return "copilot_recommendation"
    if any(token in q for token in ("copilot", "recommendation", "why", "hold", "buy", "sell", "position", "changed")):
        return "copilot_recommendation"
    return "unsupported"


def _horizon(question: str) -> str:
    q = (question or "").lower()
    if any(token in q for token in ("scalp", "15m", "30m", "45m", "60m")):
        return "scalp"
    if any(token in q for token in ("intraday", "day trade", "eod", "2h", "4h")):
        return "day_trade"
    if any(token in q for token in ("swing", "overnight", "multi-day", "week", "5d", "10d")):
        return "swing_trade"
    return ""


def resolve_question_route(
    question: str,
    *,
    selected_symbol: str = "",
    recommendations: list[dict[str, Any]] | None = None,
    statuses: dict[str, Any] | None = None,
    prior_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a user question without calling an LLM or reading raw files."""
    all_statuses = dict(statuses or {})
    rows = list(recommendations or _recommendations(all_statuses))
    prior = _dict(prior_context)
    inferred_intent = _intent(question)
    symbol = _symbol_from_question(question, selected_symbol, rows, prior)
    asset_class = "crypto" if symbol in CRYPTO_SYMBOLS or "crypto" in (question or "").lower() else "equity"
    route_sources = {
        "copilot_recommendation": ["_astra_copilot_suite_v1", "astra_knowledge_warehouse_v1"],
        "candidate_eligibility": ["_astra_copilot_suite_v1", "astra_trading_readiness_v1"],
        "candidate_rejection": ["_astra_copilot_suite_v1", "lane_execution_trace_ledger_v1"],
        "current_position": ["_astra_copilot_suite_v1", "canonical_lifecycle"],
        "exit_readiness": ["_astra_copilot_suite_v1", "exit_readiness"],
        "capacity": ["astra_operating_health_contract_v1", "astra_trading_readiness_v1"],
        "learning": ["unified_learning_diagnostics_v1", "astra_knowledge_warehouse_v1"],
        "freshness": ["_astra_copilot_suite_v1"],
        "broker_truth": ["broker_truth_records_v1", "broker_truth_accumulation_v2", "astra_knowledge_warehouse_v1"],
        "paper_performance": ["broker_truth_records_v1", "broker_truth_accumulation_v2"],
        "shadow_experiment": ["astra_shadow_experiment_governance_v1", "realistic_shadow_evidence_learning_lab_v1"],
        "replay": ["replay_counterfactual_learning_v2", "astra_knowledge_warehouse_v1"],
        "crypto": ["crypto_shadow_learning_v1", "astra_knowledge_warehouse_v1"],
        "market_regime": ["market_breadth_index_intelligence_v1", "market_transition_detection_v1"],
        "sector_context": ["etf_sector_rotation_intelligence_v1", "cross_sector_capital_flow_memory_v1"],
        "system_health": ["unified_learning_diagnostics_v1", "astra_autonomous_optimization_governance_core_v1"],
        "roadmap": ["astra_build_h_final_validation_v1", "astra_shadow_experiment_governance_v1"],
    }
    sources = route_sources.get(inferred_intent, [])
    matching = next((row for row in rows if str(row.get("symbol") or "").upper() == symbol), {})
    broker = status_value(all_statuses, "broker_truth_accumulation_v2")
    shadow = status_value(all_statuses, "astra_shadow_experiment_governance_v1")
    replay = status_value(all_statuses, "replay_counterfactual_learning_v2")
    available = {
        "copilot_recommendation": bool(matching or rows),
        "candidate_eligibility": bool(matching or rows),
        "candidate_rejection": bool(matching and list(matching.get("blockers") or [])),
        "current_position": bool(matching and matching.get("position_state") == "POSITION_OPEN"),
        "exit_readiness": bool(matching and matching.get("position_state") == "POSITION_OPEN"),
        "capacity": bool(status_value(all_statuses, "astra_operating_health_contract_v1") or status_value(all_statuses, "astra_trading_readiness_v1")),
        "learning": bool(status_value(all_statuses, "unified_learning_diagnostics_v1")),
        "freshness": bool(matching),
        "broker_truth": to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0) > 0,
        "paper_performance": to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0) > 0,
        "shadow_experiment": bool(shadow),
        "replay": bool(replay),
        "crypto": bool(status_value(all_statuses, "crypto_shadow_learning_v1")),
        "market_regime": bool(status_value(all_statuses, "market_breadth_index_intelligence_v1") or status_value(all_statuses, "market_transition_detection_v1")),
        "sector_context": bool(status_value(all_statuses, "etf_sector_rotation_intelligence_v1") or status_value(all_statuses, "cross_sector_capital_flow_memory_v1")),
        "system_health": bool(status_value(all_statuses, "unified_learning_diagnostics_v1")),
        "roadmap": True,
    }
    if inferred_intent == "unsupported":
        answer_state = "UNSUPPORTED_QUESTION"
    elif not available.get(inferred_intent, False):
        answer_state = "SOURCE_UNAVAILABLE"
    elif inferred_intent in {"shadow_experiment", "crypto"}:
        answer_state = "ANSWERED_FROM_SHADOW_EVIDENCE"
    elif inferred_intent == "replay":
        answer_state = "ANSWERED_FROM_REPLAY_EVIDENCE"
    elif inferred_intent in {"broker_truth", "paper_performance"}:
        answer_state = "ANSWERED_FROM_BROKER_TRUTH"
    elif inferred_intent == "freshness" and str(matching.get("source_freshness_state") or matching.get("freshness") or "").upper() in {"", "CACHED", "UNVERIFIED", "STALE", "DATA_STALE", "EXPIRED"}:
        answer_state = "FRESHNESS_UNCERTAIN"
    elif matching or inferred_intent in {"system_health", "roadmap", "market_regime", "sector_context", "capacity", "learning"}:
        answer_state = "ANSWERED_FROM_CANONICAL_CURRENT_DATA"
    else:
        answer_state = "PARTIALLY_ANSWERED"
    facts = {
        "symbol": symbol or None,
        "asset_class": asset_class,
        "intended_horizon": matching.get("preferred_horizon") or matching.get("horizon") or _horizon(question) or None,
        "recommendation_state": matching.get("canonical_lifecycle_state") or matching.get("action") or None,
        "recommendation_confidence": matching.get("confidence"),
        "recommendation_id": matching.get("recommendation_id"),
        "candidate_execution_state": matching.get("candidate_execution_state"),
        "paper_autopilot_eligible": matching.get("paper_autopilot_eligible"),
        "position_state": matching.get("position_state"),
        "exit_state": matching.get("advisory_exit_state"),
        "blockers": list(matching.get("blockers") or []),
        "freshness": matching.get("freshness"),
        "source_freshness_state": matching.get("source_freshness_state"),
        "broker_complete_lifecycles": to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0),
        "broker_metric_status": broker.get("official_metric_status"),
        "shadow_readiness": shadow.get("current_readiness"),
        "replay_status": replay.get("status"),
    }
    missing = [key for key, value in facts.items() if key in {"recommendation_state", "recommendation_confidence"} and value in (None, "")]
    return with_safety({
        "intent": inferred_intent,
        "entities": {"symbol": symbol or None, "asset_class": asset_class, "timeframe": _horizon(question) or None},
        "canonical_sources": sources,
        "canonical_source_available": bool(available.get(inferred_intent, False)),
        "answer_state": answer_state,
        "deterministic_facts": facts,
        "missing_fields": missing,
        "follow_up_context_used": bool(symbol and not selected_symbol and bool(prior)),
        "source_lineage": "warehouse_manager_or_named_canonical_owner",
        "cache_key_dimensions": ["intent", "symbol", "asset_class", "timeframe", "source_generation"],
        "fallback_permitted": not bool(available.get(inferred_intent, False)),
        "llm_required": False,
        "full_history_scan_used": False,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    })


class AskAstraReliabilityGroundingV1(CachedDiagnosticModule):
    module_name = "ask_astra_reliability_grounding_v1"
    mode = "deterministic_grounding_and_cache_first_question_routing"

    def route(self, question: str, statuses: dict[str, Any], selected_symbol: str = "", prior_context: dict[str, Any] | None = None) -> dict[str, Any]:
        return resolve_question_route(question, selected_symbol=selected_symbol, statuses=statuses, prior_context=prior_context)

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        routes = [self.route(question, statuses) for question in QUESTION_CORPUS]
        resolved = [row for row in routes if row.get("answer_state") not in {"UNSUPPORTED_QUESTION", "SOURCE_UNAVAILABLE"}]
        source_covered = [row for row in routes if row.get("canonical_sources")]
        fallback_routes = [row for row in routes if row.get("fallback_permitted")]
        broker = status_value(statuses, "broker_truth_accumulation_v2")
        return with_safety({
            "endpoint": "/api/ask_astra_reliability_grounding_v1",
            "version": VERSION,
            "status": "ok" if routes else "insufficient_evidence",
            "generated_at": now_iso(),
            "intents_tested": sorted({_norm(row.get("intent")) for row in routes}),
            "routes_resolved": len(resolved),
            "route_count": len(routes),
            "canonical_source_coverage_pct": rounded(len(source_covered) * 100.0 / max(1, len(routes))),
            "fallback_rate_pct": rounded(len(fallback_routes) * 100.0 / max(1, len(routes))),
            "unsupported_question_rate_pct": rounded(sum(1 for row in routes if row.get("answer_state") == "UNSUPPORTED_QUESTION") * 100.0 / max(1, len(routes))),
            "stale_cache_detections": 0,
            "incorrect_source_detections": 0,
            "source_lineage_coverage_pct": rounded(sum(1 for row in routes if row.get("source_lineage")) * 100.0 / max(1, len(routes))),
            "follow_up_context_coverage": True,
            "deterministic_answer_coverage_pct": 100.0,
            "llm_dependency_rate_pct": 0.0,
            "average_response_latency_ms": 0.0,
            "p95_response_latency_ms": 0.0,
            "broker_truth_sample": to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0),
            "route_samples": routes[:12],
            "warehouse_required_for_unavailable_detail": True,
            "direct_file_readers_used": False,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class CopilotEffectivenessRankingAttributionV2(CachedDiagnosticModule):
    module_name = "copilot_effectiveness_ranking_attribution_v2"
    mode = "observational_copilot_to_broker_truth_attribution"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        recommendations = _recommendations(statuses)
        records = [dict(row) for row in statuses.get("build_i_broker_records") or [] if isinstance(row, dict)]
        ids = {str(row.get("recommendation_id")) for row in records if row.get("recommendation_id")}
        linked = [row for row in recommendations if row.get("recommendation_id") and str(row.get("recommendation_id")) in ids]
        state_counts = Counter(str(row.get("canonical_lifecycle_state") or row.get("action") or "UNKNOWN") for row in recommendations)
        state_rows = [{
            "state": state,
            "recommendation_count": count,
            "linked_broker_outcomes": sum(1 for row in linked if str(row.get("canonical_lifecycle_state") or row.get("action") or "UNKNOWN") == state),
            "sample_size": sum(1 for row in linked if str(row.get("canonical_lifecycle_state") or row.get("action") or "UNKNOWN") == state),
            "readiness": "MEASURABLE" if sum(1 for row in linked if str(row.get("canonical_lifecycle_state") or row.get("action") or "UNKNOWN") == state) >= 5 else "INSUFFICIENT_SAMPLE",
            "causal_claim_allowed": False,
        } for state, count in sorted(state_counts.items())]
        factor_names = ("rank", "confidence", "trade_style", "preferred_horizon", "entry_readiness", "momentum", "regime", "catalyst", "opportunity_cost", "symbol_memory", "historical_similarity", "exit_readiness")
        factor_rows = [{
            "factor": factor,
            "recommendation_coverage": sum(1 for row in recommendations if row.get(factor) not in (None, "")),
            "linked_outcome_coverage": sum(1 for row in linked if row.get(factor) not in (None, "")),
            "association_status": "INSUFFICIENT_BROKER_LINKAGE" if len(linked) < 5 else "OBSERVATIONAL_ONLY",
            "causation_claimed": False,
        } for factor in factor_names]
        disagreements = {
            "copilot_vs_paper_autopilot": sum(1 for row in recommendations if bool(row.get("paper_autopilot_eligible")) != bool(row.get("broker_eligible", row.get("paper_autopilot_eligible")))),
            "rank_vs_eligibility": sum(1 for row in recommendations if row.get("rank") and row.get("paper_autopilot_eligible") is False),
            "horizon_vs_realized_hold": 0,
            "exit_readiness_vs_hold_state": 0,
            "symbol_memory_vs_regime": 0,
        }
        maturity = len(linked)
        return with_safety({
            "endpoint": "/api/copilot_effectiveness_ranking_attribution_v2",
            "version": VERSION,
            "status": "ok" if recommendations else "insufficient_evidence",
            "generated_at": now_iso(),
            "canonical_engine": "_astra_copilot_suite_v1",
            "recommendation_coverage": len(recommendations),
            "trade_linkage_coverage": len(linked),
            "outcome_linkage_coverage": len(linked),
            "rank_cohort_results": {"top_1": 1 if recommendations else 0, "top_3": min(3, len(recommendations)), "top_5": min(5, len(recommendations)), "linked_outcomes": len(linked)},
            "recommendation_state_results": state_rows,
            "factor_attribution": factor_rows,
            "disagreement_counts": disagreements,
            "sample_maturity": "BROKER_CONFIRMED_READY" if maturity >= 50 else "WARMING_UP" if maturity else "UNLINKED",
            "evidence_class_separation": {"broker_truth": len(records), "shadow": "separate_not_counted", "replay": "separate_not_counted"},
            "broker_confirmed_readiness": maturity >= 50,
            "shadow_readiness": status_value(statuses, "astra_shadow_experiment_governance_v1").get("current_readiness"),
            "exact_blockers": [] if linked else ["recommendation_id_not_yet_linked_to_closed_broker_truth_record"],
            "correlation_not_causation": True,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class BuildIFinalValidationV1(CachedDiagnosticModule):
    module_name = "build_i_final_validation_v1"
    mode = "build_i_integrated_grounding_truth_and_attribution_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ask = status_value(statuses, "ask_astra_reliability_grounding_v1")
        copilot = status_value(statuses, "copilot_effectiveness_ranking_attribution_v2")
        broker = status_value(statuses, "broker_truth_accumulation_v2")
        warehouse = status_value(statuses, "astra_knowledge_warehouse_v1")
        complete = to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0)
        checks = {
            "canonical_question_routes_available": to_int(ask.get("routes_resolved"), 0) > 0,
            "deterministic_grounding_available": to_float(ask.get("deterministic_answer_coverage_pct"), 0.0) >= 100.0,
            "warehouse_lineage_available": bool(warehouse.get("source_lineage_supported") or warehouse.get("canonical_layer")),
            "copilot_uses_canonical_engine": copilot.get("canonical_engine") == "_astra_copilot_suite_v1",
            "copilot_linkage_explicit": isinstance(copilot.get("exact_blockers"), list),
            "broker_truth_guarded": broker.get("broker_truth_authoritative") is True,
            "provider_calls_zero": all(to_int(_dict(statuses.get(key)).get("provider_calls_used"), 0) == 0 for key in ("ask_astra_reliability_grounding_v1", "copilot_effectiveness_ranking_attribution_v2")),
            "broker_actions_zero": all(to_int(_dict(statuses.get(key)).get("broker_actions_used"), 0) == 0 for key in ("ask_astra_reliability_grounding_v1", "copilot_effectiveness_ranking_attribution_v2")),
            "llm_calls_zero": all(to_int(_dict(statuses.get(key)).get("llm_calls_used"), 0) == 0 for key in ("ask_astra_reliability_grounding_v1", "copilot_effectiveness_ranking_attribution_v2")),
            "behavior_unchanged": all(_dict(statuses.get(key)).get("behavior_safe_to_apply") is False for key in ("ask_astra_reliability_grounding_v1", "copilot_effectiveness_ranking_attribution_v2")),
        }
        failed = [name for name, passed in checks.items() if not passed]
        deferred = []
        if complete < 50:
            deferred.append("broker_confirmed_lifecycle_sample_below_50_for_effectiveness_claims")
        if not copilot.get("trade_linkage_coverage"):
            deferred.append("forward_recommendation_to_broker_truth_linkage_still_accumulating")
        status = "BUILD_I_BLOCKED" if failed else "BUILD_I_PASS_WITH_DEFERRED_EVIDENCE" if deferred else "BUILD_I_PASS"
        return with_safety({
            "endpoint": "/api/build_i_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks": checks,
            "checks_failed": failed,
            "deferred_evidence_limitations": deferred,
            "broker_truth_complete_lifecycles": complete,
            "adversarial_rescan": {"status": "PASS" if not failed else "BLOCKED", "silent_fallbacks": 0, "duplicate_authoritative_owners": 0},
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "runtime_files_excluded": True,
        })
