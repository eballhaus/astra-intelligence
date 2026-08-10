"""Read-only cross-context learning adapter for Astra Trading Intelligence V3.

V3 consumes V1/V2 contracts and existing summary indexes.  It deliberately
does not infer missing entry-time context or grant any execution authority.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v2 import (
    METRIC_MINIMUM,
    SAFETY as V2_SAFETY,
    _field,
    _metrics,
    _number,
    _read,
    _strict_truths,
    _text,
    build_trading_intelligence_improvement_suite_v2,
)


VERSION = "1.0.0"
MAX_CONTEXT_GROUPS = 24
SAFETY = {
    **V2_SAFETY,
    "automatic_horizon_authority": False,
    "automatic_archetype_authority": False,
    "automatic_calibration_authority": False,
    "automatic_rejection_policy_authority": False,
}


def _index_counts(index: Mapping[str, Any], dimension: str) -> dict[str, int]:
    values = (index.get("dimension_counts") or {}).get(dimension)
    return {str(key): int(_number(value) or 0) for key, value in values.items()} if isinstance(values, Mapping) else {}


def _bounded_groups(rows: list[dict[str, Any]], dimensions: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(_field(row, *dimension.split("|")) for dimension in dimensions)
        groups[key].append(row)
    output = []
    for key, group in groups.items():
        metrics = _metrics(group)
        sample = len(group)
        output.append({
            "context": dict(zip(dimensions, key)),
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
            "status": "OBSERVATIONAL" if sample >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
            "automatic_action_eligible": False,
            **metrics,
        })
    return sorted(output, key=lambda item: (-int(item["sample_size"]), str(item["context"])))[:MAX_CONTEXT_GROUPS]


def _horizon(rows: list[dict[str, Any]], shadow: Mapping[str, Any]) -> dict[str, Any]:
    profiles = _bounded_groups(rows, ("lane_id", "paper_entry_horizon_style|intended_horizon|horizon"))
    horizon_counts = defaultdict(int)
    for item in profiles:
        horizon_counts[item["context"]["paper_entry_horizon_style|intended_horizon|horizon"]] += item["sample_size"]
    comparison = {
        "actual_strict_truth_comparisons": profiles,
        "shadow_counterfactual_status": "UNAVAILABLE_WITHOUT_CANDIDATE_LEVEL_HORIZON_COUNTERFACTUALS",
        "shadow_best_horizon_summary": shadow.get("best_horizon") or "UNAVAILABLE",
        "horizon_counts": dict(sorted(horizon_counts.items())),
        "preferred_horizon_conclusion": "INSUFFICIENT_EVIDENCE" if len(rows) < METRIC_MINIMUM else "OBSERVATIONAL_ONLY",
        "horizon_assignment_owner": "EXISTING_LANE_AND_HORIZON_OWNERSHIP",
        "automatic_horizon_authority": False,
    }
    return comparison


def _archetype(rows: list[dict[str, Any]], index: Mapping[str, Any]) -> dict[str, Any]:
    captured = [row for row in rows if _field(row, "archetype", "setup_type", fallback="UNAVAILABLE") != "UNAVAILABLE"]
    return {
        "status": "OBSERVATIONAL" if len(captured) >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
        "strict_truth_context_captured": len(captured),
        "profiles": _bounded_groups(captured, ("archetype|setup_type", "lane_id", "market_regime|regime|regime_context")),
        "existing_taxonomy_source": "trade_archetype_regime_intelligence_v1",
        "existing_taxonomy_counts": _index_counts(index, "archetype"),
        "automatic_archetype_authority": False,
    }


def _catalyst(rows: list[dict[str, Any]], index: Mapping[str, Any]) -> dict[str, Any]:
    captured = [row for row in rows if _field(row, "catalyst", "catalyst_type", "catalyst_category", fallback="UNAVAILABLE") != "UNAVAILABLE"]
    return {
        "status": "OBSERVATIONAL" if len(captured) >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
        "strict_truth_context_captured": len(captured),
        "profiles": _bounded_groups(captured, ("catalyst|catalyst_type|catalyst_category", "lane_id", "paper_entry_horizon_style|intended_horizon|horizon")),
        "existing_catalyst_summary_counts": _index_counts(index, "catalyst"),
        "post_hoc_reconstruction_used": False,
        "automatic_catalyst_authority": False,
    }


def _confidence_bucket(row: Mapping[str, Any]) -> str:
    value = _number((_field(row, "confidence", fallback="") or ""))
    if value is None:
        context = row.get("pretrade_context_v1") if isinstance(row.get("pretrade_context_v1"), Mapping) else {}
        value = _number(context.get("confidence") or context.get("predicted_win_probability"))
    if value is None:
        return "UNAVAILABLE"
    value = value * 100 if 0 < value <= 1 else value
    return "HIGH" if value >= 80 else "MEDIUM" if value >= 60 else "LOW"


def _calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    staged = {
        "global": rows,
        "lane": rows,
        "regime": [row for row in rows if _field(row, "market_regime", "regime", "regime_context") != "UNAVAILABLE"],
        "symbol": rows,
        "rich_context": [row for row in rows if all(_field(row, *keys) != "UNAVAILABLE" for keys in (("market_regime", "regime", "regime_context"), ("archetype", "setup_type"), ("catalyst", "catalyst_type")))],
    }
    result = {}
    for level, values in staged.items():
        if level == "global":
            groups = {"GLOBAL": values}
        elif level == "lane":
            groups = defaultdict(list)
            for row in values:
                groups[_field(row, "lane_id")].append(row)
        elif level == "regime":
            groups = defaultdict(list)
            for row in values:
                groups[_field(row, "market_regime", "regime", "regime_context")].append(row)
        elif level == "symbol":
            groups = defaultdict(list)
            for row in values:
                groups[_field(row, "symbol")].append(row)
        else:
            groups = {"RICH_CONTEXT": values}
        result[level] = [{
            "context": name,
            "confidence_bucket": _confidence_bucket(group[0]) if group else "UNAVAILABLE",
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
            "status": "OBSERVATIONAL" if len(group) >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
            "conclusion": "UNAVAILABLE_ORIGINAL_DIRECTION_MISSING",
            **_metrics(group),
        } for name, group in sorted(groups.items())][:MAX_CONTEXT_GROUPS]
    return {
        "staged_aggregation": result,
        "anti_overfitting_policy": "global_then_lane_then_regime_then_symbol_then_rich_context_when_each_has_sufficient_strict_truth",
        "automatic_threshold_change": False,
    }


_REAL_LATER_RETURN_KEYS = (
    "subsequent_return", "subsequent_return_pct", "later_return_after_rejection",
    "rejected_later_return_pct", "hypothetical_return",
)


def _real_rejection_outcome(row: Mapping[str, Any]) -> tuple[float | None, str]:
    """Return (real_later_return, evidence_key) only for real later-price evidence.

    A quality-score proxy (``rejected_return_pct`` without a real price path) is
    deliberately excluded so classification never fabricates an outcome.
    """
    for key in _REAL_LATER_RETURN_KEYS:
        value = _number(row.get(key))
        if value is not None:
            return value, key
    return None, ""


def _classify_rejection(row: Mapping[str, Any]) -> str:
    """Keep a safety-protected rejection ambiguous even after a later rise."""
    if row.get("safety_blocker") or row.get("liquidity_blocker") or row.get("stale_evidence") or row.get("duplicate_exposure"):
        return "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED"
    outcome, _ = _real_rejection_outcome(row)
    if outcome is None:
        return "INSUFFICIENT_EVIDENCE"
    return "MISSED_OPPORTUNITY" if outcome > 0 else "CORRECT_REJECTION" if outcome < 0 else "AMBIGUOUS"


def _tail_jsonl(path: Path, max_rows: int = 400, max_bytes: int = 1_200_000) -> list[dict[str, Any]]:
    """Read only the bounded tail of a JSONL store; never a full history scan."""
    if not path.is_file():
        return []
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except OSError:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except ValueError:
            continue
    return rows


def _ledger_candidates(path: Path) -> list[dict[str, Any]]:
    """Bounded rejected-candidate rows that already carry real later-price evidence."""
    rejected = []
    for row in _tail_jsonl(path):
        if isinstance(row, Mapping):
            symbol = _text(row.get("symbol"))
            if not symbol:
                continue
            outcome, key = _real_rejection_outcome(row)
            if outcome is None:
                continue
            blocks = str(row.get("blocked_reasons") or "")
            safety_blocker = bool(
                row.get("safety_blocker")
                or any(token in blocks.lower() for token in ("safety", "liquidity", "stale", "duplicate"))
            )
            rejected.append({
                "candidate_id": row.get("candidate_id") or row.get("ledger_id") or "UNAVAILABLE",
                "symbol": symbol,
                "subsequent_return": outcome,
                "rejection_later_price_key": key,
                "safety_blocker": safety_blocker,
            })
    return rejected[: MAX_CONTEXT_GROUPS * 2]


def _missed_opportunity(index: Mapping[str, Any], shadow: Mapping[str, Any], ledger_candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    raw = shadow.get("candidate_lessons")
    candidates = raw if isinstance(raw, list) else []
    shape_mismatch = raw is not None and not isinstance(raw, list)
    classified = []
    for row in candidates[:MAX_CONTEXT_GROUPS]:
        if not isinstance(row, Mapping):
            continue
        classified.append({
            "candidate_id": row.get("candidate_id") or "UNAVAILABLE",
            "symbol": _text(row.get("symbol")),
            "classification": _classify_rejection(row),
            "evidence_tier": "SHADOW_COUNTERFACTUAL",
            "automatic_entry_authority": False,
        })
    for row in ledger_candidates[:MAX_CONTEXT_GROUPS]:
        classified.append({
            "candidate_id": row.get("candidate_id") or "UNAVAILABLE",
            "symbol": _text(row.get("symbol")),
            "classification": _classify_rejection(row),
            "evidence_tier": "REJECTION_LEDGER_LATER_PRICE",
            "rejection_later_price_key": row.get("rejection_later_price_key") or "UNAVAILABLE",
            "automatic_entry_authority": False,
        })
    usable = [row for row in classified if row["classification"] not in {"INSUFFICIENT_EVIDENCE", "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED"}]
    return {
        "status": "OBSERVATIONAL" if usable else "INSUFFICIENT_EVIDENCE",
        "candidate_ledger_summary_counts": _index_counts(index, "symbol"),
        "candidate_ledger_rejection_context_counts": _index_counts(index, "regime"),
        "classified_shadow_rejections": classified,
        "candidate_level_shadow_outcomes": len(usable),
        "candidate_lessons_shape_mismatch_detected": shape_mismatch,
        "rejected_candidate_later_price_evidence_count": len(ledger_candidates),
        "safety_rejection_preserved_when_price_rises": True,
        "automatic_rejection_policy_authority": False,
    }


def build_trading_intelligence_improvement_suite_v3(state_dir: str = "state", query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build V3 from bounded strict truth, V2 context, and summary indexes."""
    state = Path(state_dir)
    v2 = build_trading_intelligence_improvement_suite_v2(state_dir, query)
    strict = _strict_truths(_read(state / "broker_truth_records_v1.json"))
    shadow = _read(state / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json")
    archetype_index = _read(state / "storage_summary_indexes" / "trade_archetype_regime_intelligence_v1.jsonl.summary_index.json")
    candidate_index = _read(state / "storage_summary_indexes" / "candidate_decision_ledger_v1.jsonl.summary_index.json")
    result = {
        "suite": "ASTRA Trading Intelligence Improvement Suite V3",
        "version": VERSION,
        "status": "OBSERVATIONAL_READY" if strict else "INSUFFICIENT_EVIDENCE",
        "strict_truth_sample_size": len(strict),
        "shadow_sample_size": int(_number(shadow.get("completed_shadow_lifecycles")) or 0),
        "cross_lane_horizon_intelligence": _horizon(strict, shadow),
        "trade_archetype_intelligence": _archetype(strict, archetype_index),
        "catalyst_intelligence": _catalyst(strict, archetype_index),
        "contextual_prediction_calibration": _calibration(strict),
        "missed_opportunity_rejected_candidate_intelligence": _missed_opportunity(
            candidate_index,
            shadow,
            _ledger_candidates(state / "candidate_decision_ledger_v1.jsonl"),
        ),
        "v1_v2_continuity": {
            "v1_status": v2.get("v1_integration", {}).get("status"),
            "v2_status": v2.get("status"),
            "knowledge_retrieval_reused": True,
            "knowledge_retrieval": v2.get("knowledge_retrieval"),
            "frozen_lifecycle_modified": False,
        },
        "observability": {
            "owner": "existing Sentinel -> Governance -> Cortex",
            "health_facts": [
                "STRICT_TRUTH_CONTEXT_INCOMPLETE" if len(strict) and any(_field(row, "archetype", "setup_type") == "UNAVAILABLE" for row in strict) else None,
                "CATALYST_CAPTURE_MISSING_ON_STRICT_TRUTH" if len(strict) and not any(_field(row, "catalyst", "catalyst_type") != "UNAVAILABLE" for row in strict) else None,
                "CONTEXTUAL_CALIBRATION_SAMPLE_INSUFFICIENT" if len(strict) < METRIC_MINIMUM else None,
            ],
        },
        **SAFETY,
    }
    return result
