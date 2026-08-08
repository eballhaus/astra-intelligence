"""V8 bounded historical-evidence mining and passive knowledge distillation.

This module deliberately consumes only compact summary indexes and the capped
strict-truth view already used by V2-V7.  It never opens raw JSONL evidence
stores, invokes providers/brokers, or changes trading behavior.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v2 import _field, _metrics, _number, _read, _return, _strict_truths, _text
from engine.astra_trading_intelligence_improvement_v4 import build_trading_intelligence_improvement_suite_v4


VERSION = "1.0.0"
MAX_INDEXES = 12
MAX_BUCKETS_PER_DIMENSION = 24
MAX_PATTERN_CANDIDATES = 64
MAX_INTERACTIONS = 24
MAX_DIMENSIONS_PER_INTERACTION = 3
MIN_PATTERN_SAMPLE = 5
REPEATABLE_SAMPLE = 12
LESSON_REGISTRY = "historical_evidence_distilled_lessons_v1.json"
INDEX_NAMES = (
    "candidate_decision_ledger_v1.jsonl.summary_index.json",
    "outcome_labels_v1.jsonl.summary_index.json",
    "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json",
    "trade_memory_similarity_v1.jsonl.summary_index.json",
    "market_context_learning_suite_v1.jsonl.summary_index.json",
    "replay_counterfactual_learning_v2.jsonl.summary_index.json",
    "exit_learning_expansion_suite_v1.jsonl.summary_index.json",
    "adaptive_execution_exit_intelligence_v3.jsonl.summary_index.json",
    "trade_lifecycle_excursion_v2.jsonl.summary_index.json",
    "opportunity_cost_learning_v1.jsonl.summary_index.json",
)
DIMENSIONS = (
    "symbol", "asset_class", "lane", "horizon", "regime", "archetype", "catalyst",
    "confidence_bucket", "candidate_rank_bucket", "momentum_state", "volatility_context",
    "liquidity_context", "trend", "risk_state", "rejection_reason", "exit_reason",
)
SAFETY = {
    "advisory_only": True,
    "execution_behavior_changed": False,
    "ranking_behavior_changed": False,
    "sizing_behavior_changed": False,
    "capital_behavior_changed": False,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "provider_calls_added": 0,
    "llm_calls_added": 0,
    "automatic_adaptation_authority": False,
    "frozen_lifecycle_modified": False,
    "full_history_scan_count": 0,
    "state_mutations_from_status": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tier_for_index(name: str) -> str:
    return "SHADOW_COUNTERFACTUAL" if any(token in name for token in ("shadow", "replay")) else "INDEXED_HISTORICAL_OBSERVATIONAL"


def _key(*values: Any) -> str:
    text = "|".join(str(value) for value in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _coverage_count(index: Mapping[str, Any]) -> int:
    for key in ("record_count", "records_indexed", "source_line_count_estimate", "line_count", "observation_count"):
        value = _number(index.get(key))
        if value is not None and value >= 0:
            return int(value)
    dimensions = index.get("dimension_counts")
    if not isinstance(dimensions, Mapping):
        return 0
    counts = []
    for values in dimensions.values():
        if isinstance(values, Mapping):
            counts.append(sum(int(_number(value) or 0) for value in values.values()))
    return max(counts, default=0)


def _bucket_metrics(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    sample = _number(value.get("sample_size") or value.get("count") or value.get("outcome_count"))
    average = _number(value.get("average_return_pct") or value.get("expectancy_pct") or value.get("mean_return_pct") or value.get("average_return"))
    wins = _number(value.get("win_count") or value.get("wins"))
    losses = _number(value.get("loss_count") or value.get("losses"))
    if sample is None:
        if wins is not None or losses is not None:
            sample = int((wins or 0) + (losses or 0))
        else:
            return None
    return {
        "sample_size": int(sample), "outcome_count": int(sample), "average_return_pct": round(average, 5) if average is not None else None,
        "expectancy_pct": round(average, 5) if average is not None else None,
        "win_count": int(wins or 0), "loss_count": int(losses or 0),
        "win_rate_pct": round((wins or 0) * 100 / sample, 3) if sample and wins is not None else None,
        "profit_factor": _number(value.get("profit_factor")),
    }


def _outcome_dimensions(index: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("outcome_by_dimension", "dimension_outcomes", "bucket_outcomes", "outcome_buckets"):
        value = index.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _state(metrics: Mapping[str, Any], tier: str) -> str:
    sample, average = int(metrics.get("sample_size") or 0), metrics.get("average_return_pct")
    if sample < MIN_PATTERN_SAMPLE or average is None:
        return "INSUFFICIENT_EVIDENCE"
    if abs(float(average)) < 0.01 and int(metrics.get("win_count") or 0) and int(metrics.get("loss_count") or 0):
        return "CONTRADICTORY_PATTERN"
    if sample >= REPEATABLE_SAMPLE and tier == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH":
        return "REPEATABLE_PATTERN"
    return "EARLY_PATTERN"


def _pattern(dimensions: list[str], context: Mapping[str, str], metrics: Mapping[str, Any], tier: str, source: str, coverage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    state = _state(metrics, tier)
    return {
        "pattern_id": f"pattern:{_key(tier, source, sorted(context.items()))}", "dimensions": dimensions,
        "context": dict(context), "evidence_tier": tier, "source": source,
        "sample_size": int(metrics.get("sample_size") or 0), "outcome_count": int(metrics.get("outcome_count") or 0),
        "win_loss_distribution": {"wins": int(metrics.get("win_count") or 0), "losses": int(metrics.get("loss_count") or 0)},
        "average_return_pct": metrics.get("average_return_pct"), "expectancy_pct": metrics.get("expectancy_pct"),
        "profit_factor": metrics.get("profit_factor"), "consistency": state,
        "context_specificity": len(dimensions), "supporting_evidence": [source], "contradictory_evidence": [],
        "time_coverage": dict(coverage or {}), "freshness": "INDEXED_SNAPSHOT", "confidence_state": state,
        "correlation_not_causation": True,
    }


def _strict_patterns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    field_keys = {
        "symbol": ("symbol",), "asset_class": ("asset_class", "instrument_type"), "lane": ("lane_id", "lane"),
        "horizon": ("paper_entry_horizon_style", "intended_horizon", "horizon"),
        "regime": ("market_regime", "regime", "regime_context"), "archetype": ("strategy_archetype", "archetype", "setup_type"),
        "catalyst": ("catalyst", "catalyst_state", "catalyst_type"), "momentum_state": ("momentum_state",),
        "risk_state": ("risk_state",), "exit_reason": ("exit_reason",),
    }
    for row in rows:
        for dimension, keys in field_keys.items():
            value = _field(row, *keys)
            if value != "UNAVAILABLE":
                grouped[(dimension, value)].append(row)
    output = []
    for (dimension, value), items in sorted(grouped.items()):
        output.append(_pattern([dimension], {dimension: value}, _metrics(items), "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", "broker_truth_records_v1"))
    return output


def _indexed_patterns(indexes: list[tuple[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name, index in indexes:
        coverage = {key: index.get(key) for key in ("first_timestamp", "last_timestamp", "generated_at") if index.get(key)}
        for dimension, buckets in _outcome_dimensions(index).items():
            if not isinstance(buckets, Mapping):
                continue
            for value, raw in list(sorted(buckets.items(), key=lambda item: str(item[0])))[:MAX_BUCKETS_PER_DIMENSION]:
                metrics = _bucket_metrics(raw)
                if metrics:
                    output.append(_pattern([str(dimension)], {str(dimension): _text(value)}, metrics, _tier_for_index(name), name, coverage))
    return output


def _interactions(rows: list[dict[str, Any]], singles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Screen by already-observed strict dimensions, then evaluate at most pairs.
    usable = [row for row in singles if row.get("sample_size", 0) >= MIN_PATTERN_SAMPLE and row.get("average_return_pct") is not None][:MAX_INTERACTIONS]
    allowed = {str(row["dimensions"][0]) for row in usable if row.get("dimensions")}
    if len(allowed) < 2:
        return []
    keys = {
        "symbol": ("symbol",), "lane": ("lane_id", "lane"), "horizon": ("horizon", "intended_horizon"),
        "regime": ("regime", "market_regime"), "archetype": ("archetype", "strategy_archetype"),
        "momentum_state": ("momentum_state",),
    }
    dimensions = [key for key in keys if key in allowed][:MAX_DIMENSIONS_PER_INTERACTION + 1]
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = {dim: _field(row, *keys[dim]) for dim in dimensions}
        for left_index, left in enumerate(dimensions):
            for right in dimensions[left_index + 1:]:
                if values[left] != "UNAVAILABLE" and values[right] != "UNAVAILABLE":
                    grouped[(left, values[left], right, values[right])].append(row)
    baseline = {(p["dimensions"][0], next(iter(p["context"].values()))): p for p in singles if p.get("dimensions") and len(p["dimensions"]) == 1}
    output = []
    for (left, left_value, right, right_value), items in sorted(grouped.items()):
        metrics = _metrics(items)
        if int(metrics.get("sample_size") or 0) < MIN_PATTERN_SAMPLE or metrics.get("average_return_pct") is None:
            continue
        components = [baseline.get((left, left_value)), baseline.get((right, right_value))]
        component_values = [p.get("average_return_pct") for p in components if p and p.get("average_return_pct") is not None]
        incremental = float(metrics["average_return_pct"]) - sum(component_values) / len(component_values) if component_values else None
        quality = "REPEATABLE_INTERACTION" if len(items) >= REPEATABLE_SAMPLE and incremental is not None and abs(incremental) >= 0.25 else "POSSIBLE_INTERACTION" if incremental is not None and abs(incremental) >= 0.25 else "NO_INCREMENTAL_VALUE"
        item = _pattern([left, right], {left: left_value, right: right_value}, metrics, "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH", "bounded_strict_truth_interaction")
        item.update({"interaction_state": quality, "incremental_discrimination_pct_points": round(incremental, 5) if incremental is not None else None, "max_dimensions": MAX_DIMENSIONS_PER_INTERACTION})
        output.append(item)
        if len(output) >= MAX_INTERACTIONS:
            break
    return output


def _redundancy(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = []
    by_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pattern in patterns:
        if pattern.get("average_return_pct") is not None and pattern.get("confidence_state") != "INSUFFICIENT_EVIDENCE":
            by_context[str(pattern.get("context"))].append(pattern)
    for context, rows in sorted(by_context.items()):
        if len(rows) < 2:
            continue
        values = [float(row["average_return_pct"]) for row in rows]
        classification = "REDUNDANT" if max(values) - min(values) < 0.1 and min(int(row["sample_size"]) for row in rows) >= REPEATABLE_SAMPLE else "CONTEXT_DEPENDENT"
        findings.append({"finding_id": f"redundancy:{_key(context)}", "classification": classification, "pattern_ids": [row["pattern_id"] for row in rows], "automatic_removal": False, "requires_v7_validation": True})
    return findings[:MAX_INTERACTIONS]


def _lessons(patterns: list[dict[str, Any]], drift: Mapping[str, Any]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}
    drifted = str(drift.get("status") or "").upper() not in {"OBSERVATIONAL", "LOW", "PASS", ""}
    for pattern in patterns:
        if pattern.get("confidence_state") == "INSUFFICIENT_EVIDENCE":
            continue
        context = tuple(sorted((str(k), str(v)) for k, v in (pattern.get("context") or {}).items()))
        key = (str(pattern.get("evidence_tier")), context)
        lesson = merged.setdefault(key, {
            "lesson_id": f"lesson:{_key(key)}", "created_at": _now(), "updated_at": _now(), "evidence_tier": pattern.get("evidence_tier"),
            "source_pattern_ids": [], "applicable_context": dict(context), "sample_size": 0,
            "strict_truth_support_count": 0, "shadow_support_count": 0, "historical_observation_count": 0,
            "contradictory_evidence": [], "retrieval_keys": dict(context), "promotion_readiness": "V7_REQUIRED", "automatic_apply_allowed": False,
        })
        lesson["source_pattern_ids"].append(pattern["pattern_id"])
        lesson["sample_size"] = max(lesson["sample_size"], int(pattern.get("sample_size") or 0))
        if pattern.get("evidence_tier") == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH":
            lesson["strict_truth_support_count"] += int(pattern.get("sample_size") or 0)
        elif pattern.get("evidence_tier") == "SHADOW_COUNTERFACTUAL":
            lesson["shadow_support_count"] += int(pattern.get("sample_size") or 0)
        else:
            lesson["historical_observation_count"] += int(pattern.get("sample_size") or 0)
    output = []
    for lesson in merged.values():
        if drifted:
            state, stability = "DRIFTING", "DRIFTING"
        elif lesson["strict_truth_support_count"] >= REPEATABLE_SAMPLE:
            state, stability = "REPEATABLE_KNOWLEDGE", "STABLE"
        elif lesson["strict_truth_support_count"] >= MIN_PATTERN_SAMPLE:
            state, stability = "STRICT_TRUTH_EARLY", "EARLY"
        elif lesson["shadow_support_count"] >= MIN_PATTERN_SAMPLE:
            state, stability = "SHADOW_SUPPORTED", "EARLY"
        else:
            state, stability = "DISCOVERY_ONLY", "EARLY"
        lesson.update({"state": state, "stability_drift_state": stability, "lesson_statement": f"Observed relationship for {lesson['applicable_context']} remains {state}; correlation is not causation."})
        output.append(lesson)
    return sorted(output, key=lambda item: (-int(item["sample_size"]), item["lesson_id"]))[:MAX_PATTERN_CANDIDATES]


def _persist_registry(state: Path, lessons: list[dict[str, Any]]) -> bool:
    path = state / LESSON_REGISTRY
    path.write_text(json.dumps({"version": VERSION, "updated_at": _now(), "lessons": lessons}, sort_keys=True), encoding="utf-8")
    return True


def build_historical_evidence_mining_knowledge_distillation_v1(
    state_dir: str = "state", query: Mapping[str, Any] | None = None, *, persist_lessons: bool = False, drift_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mine bounded index snapshots; persistence is opt-in and never used by the API."""
    state = Path(state_dir)
    query = query or {}
    indexes = [(name, _read(state / "storage_summary_indexes" / name)) for name in INDEX_NAMES[:MAX_INDEXES]]
    indexes = [(name, value) for name, value in indexes if value]
    strict_rows = _strict_truths(_read(state / "broker_truth_records_v1.json"))
    v4 = build_trading_intelligence_improvement_suite_v4(state_dir, query)
    drift = dict(drift_override or (v4.get("learning_consistency_and_drift") or {}))
    patterns = (_strict_patterns(strict_rows) + _indexed_patterns(indexes))[:MAX_PATTERN_CANDIDATES]
    interactions = _interactions(strict_rows, [item for item in patterns if item.get("evidence_tier") == "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH"])
    lessons = _lessons(patterns, drift)
    persisted = _persist_registry(state, lessons) if persist_lessons else False
    indexed_count = sum(_coverage_count(index) for _, index in indexes)
    coverage = {
        "indexed_historical_observations_available": indexed_count,
        "summary_indexes_mined": [name for name, _ in indexes], "evidence_domains_mined": sorted({dimension for pattern in patterns for dimension in pattern.get("dimensions", [])}),
        "unused_indexed_evidence_domains": [name for name, _ in indexes if not _outcome_dimensions(_)],
        "pattern_count": len(patterns), "interaction_count": len(interactions), "distilled_lesson_count": len(lessons),
        "strict_supported_lesson_count": sum(item["strict_truth_support_count"] > 0 for item in lessons),
        "shadow_supported_lesson_count": sum(item["shadow_support_count"] > 0 for item in lessons),
        "stale_or_drifting_lesson_count": sum(item["state"] in {"DRIFTING", "RETIRED"} for item in lessons), "full_history_scan_count": 0,
    }
    cortex_ready = [item for item in lessons if item["state"] == "REPEATABLE_KNOWLEDGE" and item["promotion_readiness"] == "V7_REQUIRED"]
    return {
        "suite": "ASTRA Historical Evidence Mining & Knowledge Distillation V8", "version": VERSION,
        "status": "OBSERVATIONAL_READY" if indexes or strict_rows else "INSUFFICIENT_EVIDENCE",
        "historical_pattern_mining": {"patterns": patterns, "strict_truth_rows_considered": len(strict_rows), "raw_records_read": 0, "full_history_scan_count": 0},
        "multi_factor_interaction_discovery": {"interactions": interactions, "max_dimensions": MAX_DIMENSIONS_PER_INTERACTION, "max_interactions": MAX_INTERACTIONS, "combinatorial_search_prevented": True},
        "evidence_redundancy_low_value_detection": {"findings": _redundancy(patterns), "automatic_evidence_removal": False, "tiny_sample_defaults_to": "UNPROVEN"},
        "knowledge_distillation_lesson_registry": {"lessons": lessons, "registry_path": str(state / LESSON_REGISTRY), "persisted": persisted, "deduplicated": True, "read_only_status_path": not persist_lessons},
        "knowledge_validation_drift_cortex_handoff": {"drift": drift, "cortex_ready_lessons": cortex_ready, "v7_required_for_adaptation": True, "automatic_adaptation": False},
        "learning_coverage": coverage,
        "incremental_mining": {"mode": "SUMMARY_INDEX_SNAPSHOT_INCREMENTAL", "last_mined_index_snapshot": max((str(index.get("generated_at") or "") for _, index in indexes), default=""), "new_raw_records_read": 0, "work_budget": {"max_indexes": MAX_INDEXES, "max_patterns": MAX_PATTERN_CANDIDATES, "max_interactions": MAX_INTERACTIONS}},
        "v1_v7_continuity": {"knowledge_retrieval_reused": True, "v4_drift_reused": True, "v7_adaptation_required": True, "frozen_lifecycle_modified": False, "full_history_scan_count": 0},
        **SAFETY,
    }
