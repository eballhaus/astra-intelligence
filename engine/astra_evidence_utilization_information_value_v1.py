"""V9 read-only evidence utilization and information-value reporting.

V9 consumes V4/V5/V8 summary contracts only.  It deliberately does not refresh
indexes, read raw JSONL history, call external services, or alter execution.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from engine.astra_historical_evidence_mining_knowledge_distillation_v1 import (
    build_historical_evidence_mining_knowledge_distillation_v1,
)
from engine.astra_trading_intelligence_improvement_v4 import (
    build_trading_intelligence_improvement_suite_v4,
)
from engine.astra_trading_intelligence_improvement_v5 import (
    build_trading_intelligence_improvement_suite_v5,
)


VERSION = "1.0.0"
MAX_DIMENSION_REPORTS = 32
MAX_PRIORITY_ITEMS = 24
V5_CATEGORY_DIMENSIONS = {
    "momentum": ("momentum_state",),
    "trend": ("trend",),
    "volume": ("liquidity_context",),
    "volatility": ("volatility_context",),
    "regime": ("regime",),
    "catalyst": ("catalyst",),
    "archetype": ("archetype",),
    "liquidity": ("liquidity_context",),
    "risk": ("risk_state",),
    "ranking": ("candidate_rank_bucket",),
}
SAFETY = {
    "read_only_status": True,
    "producer_refreshes_triggered": 0,
    "full_history_scan_count": 0,
    "execution_behavior_changed": False,
    "ranking_behavior_changed": False,
    "confidence_behavior_changed": False,
    "sizing_behavior_changed": False,
    "capital_behavior_changed": False,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "provider_calls_added": 0,
    "llm_calls_added": 0,
    "automatic_adaptation_authority": False,
    "frozen_lifecycle_modified": False,
}


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage(v5: Mapping[str, Any]) -> tuple[int, dict[str, int]]:
    """Return strict-truth attribution availability without inventing joins."""
    usage: dict[str, int] = defaultdict(int)
    ledgers = ((v5.get("decision_evidence_attribution_ledger") or {}).get("ledgers") or [])
    for ledger in ledgers if isinstance(ledgers, list) else []:
        for entry in ledger.get("entries") or []:
            if not isinstance(entry, Mapping) or not entry.get("available"):
                continue
            for dimension in V5_CATEGORY_DIMENSIONS.get(str(entry.get("category") or ""), ()):
                usage[dimension] += 1
    return len(ledgers) if isinstance(ledgers, list) else 0, dict(usage)


def _patterns_by_dimension(v8: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pattern in ((v8.get("historical_pattern_mining") or {}).get("patterns") or []):
        if not isinstance(pattern, Mapping):
            continue
        for dimension in pattern.get("dimensions") or []:
            grouped[str(dimension)].append(dict(pattern))
    return grouped


def _value_state(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "UNPROVEN"
    states = {str(pattern.get("confidence_state") or "") for pattern in patterns}
    strict_repeatable = any(
        pattern.get("evidence_tier") == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH"
        and pattern.get("confidence_state") == "REPEATABLE_PATTERN"
        for pattern in patterns
    )
    if strict_repeatable:
        return "HIGH_VALUE_CANDIDATE"
    if "CONTRADICTORY_PATTERN" in states:
        return "CONTRADICTORY"
    if "EARLY_PATTERN" in states:
        return "POSSIBLE_VALUE"
    return "UNPROVEN"


def _utilization_state(linked: bool, usage_count: int, value_state: str) -> str:
    if not linked:
        return "INDEXED_NOT_OUTCOME_LINKED"
    if not usage_count:
        return "OUTCOME_LINKED_NOT_USED"
    if value_state == "LOW_INFORMATION_VALUE":
        return "GRADED_LOW_VALUE"
    if value_state in {"USEFUL", "HIGH_VALUE_CANDIDATE", "POSSIBLE_VALUE"}:
        return "GRADED_USEFUL"
    return "USED_NOT_YET_GRADED"


def _reliability(v4: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = ((v4.get("evidence_weight_reliability") or {}).get("source_reliability") or [])
    return {
        str(row.get("evidence_category")): dict(row)
        for row in rows if isinstance(row, Mapping) and row.get("evidence_category")
    }


def _dimension_reports(v8: Mapping[str, Any], v5: Mapping[str, Any], v4: Mapping[str, Any]) -> list[dict[str, Any]]:
    coverage = v8.get("learning_coverage") or {}
    linked = {str(item) for item in coverage.get("dimensions_outcome_linked") or []}
    unavailable = {str(item) for item in coverage.get("dimensions_outcome_unavailable") or []}
    ledger_count, usage = _usage(v5)
    patterns = _patterns_by_dimension(v8)
    reliability = _reliability(v4)
    names = sorted(linked | unavailable | set(usage) | set(patterns))[:MAX_DIMENSION_REPORTS]
    reports = []
    for name in names:
        matching = patterns.get(name, [])
        state = _value_state(matching) if name in linked else "UNPROVEN"
        usage_count = usage.get(name, 0)
        reports.append({
            "dimension": name,
            "outcome_linked": name in linked,
            "outcome_linkage_available": name in linked,
            "outcome_pattern_support_record_equivalents": sum(_integer(item.get("sample_size")) for item in matching),
            "strict_pattern_support": sum(_integer(item.get("sample_size")) for item in matching if item.get("evidence_tier") == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH"),
            "shadow_pattern_support": sum(_integer(item.get("sample_size")) for item in matching if item.get("evidence_tier") == "SHADOW_COUNTERFACTUAL"),
            "decision_attribution_available_lifecycles": usage_count,
            "decision_attribution_lifecycle_denominator": ledger_count,
            "decision_utilization_rate_pct": round(usage_count * 100 / ledger_count, 3) if ledger_count else None,
            "information_value_state": state,
            "v4_reliability": reliability.get(name, {"association": "UNAVAILABLE", "evidence_tier": "UNAVAILABLE"}),
            "utilization_state": _utilization_state(name in linked, usage_count, state),
            "overlapping_summary_counts_not_unique_events": True,
            "requires_v7_for_adaptation": True,
        })
    return reports


def _unused_candidates(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A candidate needs strict-repeatable value and demonstrably zero captured use.
    return [{
        "evidence_category": report["dimension"],
        "status": "AVAILABLE_BUT_UNUSED",
        "observed_information_value_state": report["information_value_state"],
        "decision_utilization_rate_pct": report["decision_utilization_rate_pct"],
        "recommended_action": "SHADOW_TEST",
        "requires_v7_for_adaptation": True,
        "correlation_not_causation": True,
    } for report in reports if report["information_value_state"] == "HIGH_VALUE_CANDIDATE" and not report["decision_attribution_available_lifecycles"]]


def _priority_items(v8: Mapping[str, Any]) -> list[dict[str, Any]]:
    priority = {"V7_HANDOFF_CANDIDATE": 0, "VALIDATION_PRIORITY": 1, "LEARN_MORE": 2, "MONITOR": 3}
    rows = []
    for pattern in ((v8.get("historical_pattern_mining") or {}).get("patterns") or []):
        confidence = str(pattern.get("confidence_state") or "INSUFFICIENT_EVIDENCE")
        if pattern.get("evidence_tier") == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH" and confidence == "REPEATABLE_PATTERN":
            state = "V7_HANDOFF_CANDIDATE"
        elif confidence == "CONTRADICTORY_PATTERN":
            state = "VALIDATION_PRIORITY"
        elif confidence == "EARLY_PATTERN":
            state = "LEARN_MORE"
        else:
            state = "MONITOR"
        rows.append({
            "pattern_id": pattern.get("pattern_id"), "teaching_priority": state,
            "evidence_tier": pattern.get("evidence_tier"), "sample_size": _integer(pattern.get("sample_size")),
            "context": dict(pattern.get("context") or {}), "requires_v7_for_adaptation": True,
        })
    return sorted(rows, key=lambda item: (priority[item["teaching_priority"]], -item["sample_size"], str(item["pattern_id"])))[:MAX_PRIORITY_ITEMS]


def build_evidence_utilization_information_value_v1(
    state_dir: str = "state", query: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize V8.1 aggregates and V4/V5 attribution without changing them."""
    query = query or {}
    v8 = build_historical_evidence_mining_knowledge_distillation_v1(state_dir, query)
    v4 = build_trading_intelligence_improvement_suite_v4(state_dir, query)
    v5 = build_trading_intelligence_improvement_suite_v5(state_dir, query)
    coverage = dict(v8.get("learning_coverage") or {})
    reports = _dimension_reports(v8, v5, v4)
    unused = _unused_candidates(reports)
    priorities = _priority_items(v8)
    indexed = _integer(coverage.get("indexed_historical_observations_available"))
    linked = _integer(coverage.get("outcome_linked_observations"))
    linkable = _integer(coverage.get("outcome_linkable_observations"))
    lessons = ((v8.get("knowledge_distillation_lesson_registry") or {}).get("lessons") or [])
    v7_candidates = [item for item in priorities if item["teaching_priority"] == "V7_HANDOFF_CANDIDATE"]
    return {
        "suite": "ASTRA Evidence Utilization & Information Value V9", "version": VERSION,
        "status": "OBSERVATIONAL_READY" if indexed else "INSUFFICIENT_EVIDENCE",
        "v8_1_linkage_refresh": {
            "status": "CONSUMED_EXISTING_SUMMARY_SNAPSHOT", "refreshes_triggered_by_v9": 0,
            "outcome_linkable_observations": linkable, "outcome_linked_observations": linked,
            "outcome_aggregate_count": _integer(coverage.get("outcome_aggregate_count")),
            "normal_status_full_history_scan_count": 0,
        },
        "evidence_utilization_coverage": {
            "indexed_record_equivalents": indexed,
            "unique_market_event_count": "UNAVAILABLE_OVERLAPPING_SUMMARY_INDEXES",
            "outcome_linked_observations": linked,
            "outcome_linkage_coverage_pct": coverage.get("outcome_linkage_coverage_pct"),
            "strict_truth_decision_attribution_lifecycles": _usage(v5)[0],
            "distilled_lesson_count": len(lessons),
            "dimensions": reports,
            "denominator_note": "Indexed totals are overlapping record-equivalents; no cross-index unique-event utilization rate is inferred.",
        },
        "information_value": {
            "findings": reports,
            "outcomes_required_for_value": True,
            "frequency_alone_is_not_profitability_evidence": True,
            "v4_reliability_status": v4.get("status"),
            "automatic_reweighting": False,
        },
        "unused_high_value_evidence": {
            "candidates": unused,
            "requires_value_and_low_utilization": True,
            "automatic_weight_change": False,
        },
        "learning_teaching_priority": {"items": priorities, "bounded": True, "max_items": MAX_PRIORITY_ITEMS},
        "v7_cortex_handoff": {
            "candidates": v7_candidates, "v7_required_for_adaptation": True,
            "cortex_authority_required": True, "automatic_adaptation": False,
            "reason_no_candidate": "NO_REPEATABLE_STRICT_TRUTH_PATTERN" if not v7_candidates else None,
        },
        "continuity": {
            "v4_reliability_reused": True, "v5_attribution_ledger_reused": True,
            "v8_outcome_aggregates_reused": True, "v7_adaptation_gate_preserved": True,
            "state_dir": str(Path(state_dir)),
        },
        **SAFETY,
    }
