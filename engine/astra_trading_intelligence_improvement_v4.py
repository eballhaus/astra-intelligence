"""Read-only quality and reliability adapter for Astra Trading Intelligence V4."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v2 import (
    METRIC_MINIMUM,
    SAFETY as V2_SAFETY,
    _metrics,
    _number,
    _read,
    _strict_truths,
)
from engine.astra_trading_intelligence_improvement_v3 import build_trading_intelligence_improvement_suite_v3


VERSION = "1.0.0"
DRIFT_MINIMUM = 10
SAFETY = {
    **V2_SAFETY,
    "execution_behavior_changed": False,
    "automatic_reweighting_authority": False,
    "automatic_drift_response_authority": False,
}


def _original_factors(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return only factors captured in immutable pretrade context."""
    context = row.get("pretrade_context_v1")
    if not isinstance(context, Mapping):
        return {}
    for key in ("factor_contributions", "evidence_factors", "confidence_attribution"):
        values = context.get(key)
        if isinstance(values, Mapping):
            return {str(name): value for name, value in values.items() if value not in (None, "")}
    return {}


def _attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for factor, contribution in _original_factors(row).items():
            groups[factor].append({"row": row, "contribution": _number(contribution)})
    findings = []
    for factor, evidence in sorted(groups.items()):
        outcomes = [item["row"] for item in evidence]
        metrics = _metrics(outcomes)
        positive = [item["contribution"] for item in evidence if item["contribution"] is not None]
        state = "INSUFFICIENT_EVIDENCE"
        if len(outcomes) >= METRIC_MINIMUM and metrics.get("average_return_pct") is not None:
            state = "POSITIVE_ASSOCIATION" if metrics["average_return_pct"] > 0 else "NEGATIVE_ASSOCIATION" if metrics["average_return_pct"] < 0 else "MIXED"
        findings.append({
            "factor": factor,
            "presence_at_prediction_time": len(outcomes),
            "average_captured_contribution": round(sum(positive) / len(positive), 4) if positive else None,
            "association": state,
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
            **metrics,
        })
    return {
        "status": "OBSERVATIONAL" if any(row["association"] != "INSUFFICIENT_EVIDENCE" for row in findings) else "INSUFFICIENT_EVIDENCE",
        "factors": findings,
        "missing_original_attribution_count": len(rows) - len({id(item["row"]) for values in groups.values() for item in values}),
        "post_hoc_reconstruction_used": False,
        "automatic_confidence_adjustment": False,
    }


def _entry_quality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence = []
    for row in rows:
        entry = _number(row.get("entry_price"))
        mfe = _number(row.get("mfe"))
        mae = _number(row.get("mae"))
        if entry is None or (mfe is None and mae is None):
            continue
        status = "ENTRY_EFFICIENT" if mfe is not None and (mae is None or mfe >= abs(mae)) else "ENTRY_POORLY_TIMED"
        evidence.append({
            "symbol": row.get("symbol"), "entry_price": entry, "entry_timestamp": row.get("entry_time"),
            "mfe": mfe, "mae": mae, "time_to_mfe": row.get("time_to_peak"),
            "status": status, "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
        })
    return {
        "status": "OBSERVATIONAL" if len(evidence) >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
        "persisted_entry_excursion_count": len(evidence),
        "entries": evidence[:24],
        "unavailable_reason": None if evidence else "PERSISTED_MFE_MAE_REQUIRED",
        "automatic_entry_adjustment": False,
    }


def _exit_quality(rows: list[dict[str, Any]], shadow: Mapping[str, Any]) -> dict[str, Any]:
    actual = []
    for row in rows:
        exit_price = _number(row.get("exit_price"))
        realized = _number(row.get("realized_return") or row.get("realized_return_pct"))
        mfe = _number(row.get("mfe"))
        if exit_price is None or realized is None or mfe is None:
            continue
        actual.append({
            "symbol": row.get("symbol"), "exit_price": exit_price, "exit_timestamp": row.get("exit_time"),
            "realized_return_pct": realized, "mfe": mfe, "profit_giveback": _number(row.get("profit_giveback")),
            "exit_reason": row.get("exit_reason") or "UNAVAILABLE", "status": "EXIT_EFFECTIVE" if realized >= 0 else "EXIT_REVIEW",
            "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
        })
    return {
        "actual_exit_status": "OBSERVATIONAL" if len(actual) >= METRIC_MINIMUM else "INSUFFICIENT_EVIDENCE",
        "actual_exit_evidence": actual[:24],
        "counterfactual_exit_status": "SHADOW_SUMMARY_ONLY" if shadow.get("completed_shadow_lifecycles") else "INSUFFICIENT_EVIDENCE",
        "counterfactual_exit_evidence_tier": "SHADOW_COUNTERFACTUAL",
        "counterfactual_best_exit_style": shadow.get("best_exit_style") or "UNAVAILABLE",
        "actual_broker_truth_rewritten": False,
        "automatic_exit_adjustment": False,
    }


def _drift(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "INSUFFICIENT_EVIDENCE" if len(rows) < DRIFT_MINIMUM else "OBSERVATIONAL",
        "strict_truth_sample_size": len(rows),
        "minimum_sample_size": DRIFT_MINIMUM,
        "comparison": "recent_vs_reference_not_materialized_without_sufficient_ordered_strict_truth",
        "automatic_strategy_disable": False,
        "automatic_execution_change": False,
    }


def _reliability(rows: list[dict[str, Any]], attribution: Mapping[str, Any]) -> dict[str, Any]:
    factors = attribution.get("factors") if isinstance(attribution.get("factors"), list) else []
    return {
        "status": "OBSERVATIONAL" if any(row.get("association") != "INSUFFICIENT_EVIDENCE" for row in factors) else "INSUFFICIENT_EVIDENCE",
        "source_reliability": [{
            "evidence_category": row.get("factor"), "sample_size": row.get("sample_size"),
            "association": row.get("association"), "evidence_tier": row.get("evidence_tier"),
            "correlation_not_causation": True,
        } for row in factors],
        "original_evidence_rows": sum(1 for row in rows if _original_factors(row)),
        "automatic_reweighting_authority": False,
    }


def build_trading_intelligence_improvement_suite_v4(state_dir: str = "state", query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build V4 entirely from strict truth, V3 context, and shadow cache."""
    state = Path(state_dir)
    strict = _strict_truths(_read(state / "broker_truth_records_v1.json"))
    shadow = _read(state / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json")
    attribution = _attribution(strict)
    v3 = build_trading_intelligence_improvement_suite_v3(state_dir, query)
    return {
        "suite": "ASTRA Trading Intelligence Improvement Suite V4",
        "version": VERSION,
        "status": "OBSERVATIONAL_READY" if strict else "INSUFFICIENT_EVIDENCE",
        "strict_truth_sample_size": len(strict),
        "confidence_attribution": attribution,
        "entry_quality": _entry_quality(strict),
        "exit_effectiveness": _exit_quality(strict, shadow),
        "learning_consistency_and_drift": _drift(strict),
        "evidence_weight_reliability": _reliability(strict, attribution),
        "v1_v2_v3_continuity": {
            "v3_status": v3.get("status"), "knowledge_retrieval_reused": True,
            "full_history_scan_count": v3.get("full_history_scan_count", 0),
            "frozen_lifecycle_modified": False,
        },
        "observability": {
            "owner": "existing Sentinel -> Governance -> Cortex",
            "warnings": ["ORIGINAL_FACTOR_ATTRIBUTION_MISSING", "ENTRY_EXIT_EXCURSION_EVIDENCE_MISSING", "DRIFT_SAMPLE_INSUFFICIENT"],
        },
        **SAFETY,
    }
