"""Read-only V5 evidence-capture readiness surface for future strict truths."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v2 import SAFETY as V2_SAFETY, _read, _strict_truths
from engine.astra_trading_intelligence_improvement_v4 import build_trading_intelligence_improvement_suite_v4


VERSION = "1.0.0"
SAFETY = {
    **V2_SAFETY,
    "execution_behavior_changed": False,
    "historical_truths_modified": False,
    "provider_calls_added": 0,
    "broker_calls_used": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
}


def _context(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("pretrade_context_v1")
    return dict(value) if isinstance(value, Mapping) else {}


def _available(context: Mapping[str, Any], *keys: str) -> bool:
    return any(context.get(key) not in (None, "", [], {}) for key in keys)


def _original_prediction_verified(context: Mapping[str, Any]) -> bool:
    """Require a captured prediction, not an inferred historical identifier."""
    return (
        _available(context, "contract_id", "entry_contract_id", "thesis_id")
        and _available(context, "thesis", "entry_rationale", "predicted_direction", "direction")
    )


def _provenance(row: Mapping[str, Any]) -> dict[str, Any]:
    context = _context(row)
    if _original_prediction_verified(context):
        state = "ORIGINAL_CAPTURE_VERIFIED"
    elif _available(context, "thesis", "entry_rationale", "predicted_direction", "direction", "thesis_id", "contract_id", "entry_contract_id"):
        state = "PARTIAL_ORIGINAL_CONTEXT"
    else:
        state = "UNAVAILABLE"
    return {
        "lifecycle_id": row.get("lifecycle_id"),
        "symbol": row.get("symbol"),
        "state": state,
        "candidate_id": context.get("candidate_id") or "UNAVAILABLE",
        "thesis_id": context.get("thesis_id") or "UNAVAILABLE",
        "contract_id": context.get("contract_id") or context.get("entry_contract_id") or "UNAVAILABLE",
        "prediction_timestamp": context.get("observation_timestamp") or context.get("candidate_generated_at") or "UNAVAILABLE",
    }


def _completeness(row: Mapping[str, Any]) -> dict[str, Any]:
    context = _context(row)
    fields = {
        "candidate_identity": _available(context, "candidate_id"),
        "pretrade_context": bool(context),
        "original_thesis": _available(context, "thesis", "entry_rationale", "thesis_id"),
        "original_confidence": _available(context, "confidence", "predicted_win_probability"),
        "lane_horizon": _available(context, "lane", "lane_id", "intended_horizon", "paper_entry_horizon_style"),
        "entry_broker_fill": bool(row.get("entry_fill_id")),
        "excursion_evidence": row.get("mfe") not in (None, "") or row.get("mae") not in (None, ""),
        "exit_reason": bool(row.get("exit_reason")),
        "exit_broker_fill": bool(row.get("exit_fill_id")),
        "broker_reconciliation": bool(row.get("broker_residual_zero_confirmed") or row.get("canonical_dust_safe_closure")),
        "canonical_closure": str(row.get("truth_state") or "").upper() in {"STRICT_TRUTH", "BROKER_TRUTH_CONFIRMED", "BROKER_CONFIRMED_COMPLETE", "COMPLETE"},
        "strict_truth": bool(row.get("stable_key")),
        "learning_acknowledgement": bool(row.get("learning_acknowledged")),
    }
    present = sum(fields.values())
    readiness = (
        "LEARNING_COMPLETE" if present == len(fields)
        else "STRICT_TRUTH_COMPLETE" if fields["canonical_closure"] and fields["strict_truth"] and fields["learning_acknowledgement"]
        else "TRUTH_READY" if fields["entry_broker_fill"] and fields["exit_broker_fill"] and fields["broker_reconciliation"]
        else "EVIDENCE_PARTIAL" if present
        else "EVIDENCE_INCOMPLETE"
    )
    return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "evidence_state": readiness, "availability": fields, "present_dimensions": present, "total_dimensions": len(fields)}


def _ledger(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = _context(row)
    mapping = {
        "momentum": ("momentum_state",), "trend": ("trend_state",), "volume": ("volume_state",),
        "volatility": ("volatility_context",), "regime": ("market_regime", "regime_fit"),
        "sector_context": ("sector_fit",), "catalyst": ("catalyst", "catalyst_state"),
        "archetype": ("strategy_archetype",), "liquidity": ("liquidity_state",),
        "risk": ("risk_envelope", "candidate_risk_envelope_v1"), "market_context": ("market_data_timestamp",),
        "thesis": ("thesis", "entry_rationale"), "ranking": ("ranking_factors",),
        "supporting_evidence": ("supporting_evidence",), "opposing_evidence": ("opposing_evidence",),
        "opportunity_cost": ("opportunity_cost_context",), "historical_similarity": ("historical_similarity",),
    }
    return [{
        "category": category, "available": _available(context, *keys),
        "evidence_state": next((context[key] for key in keys if context.get(key) not in (None, "", [], {})), "UNAVAILABLE"),
        "timestamp": context.get("observation_timestamp") or context.get("candidate_generated_at") or "UNAVAILABLE",
        "source_owner": context.get("contract_id") or context.get("certification_snapshot_id") or "UNAVAILABLE",
        "predecision_only": True,
    } for category, keys in mapping.items()]


def build_trading_intelligence_improvement_suite_v5(state_dir: str = "state", query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    state = Path(state_dir)
    truths = _strict_truths(_read(state / "broker_truth_records_v1.json"))
    completeness = [_completeness(row) for row in truths[:100]]
    ledgers = [{"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "entries": _ledger(row)} for row in truths[:100]]
    provenance = [_provenance(row) for row in truths[:100]]
    v4 = build_trading_intelligence_improvement_suite_v4(state_dir, query)
    context_rows = sum(bool(_context(row)) for row in truths)
    excursion_rows = sum(bool(item["availability"]["excursion_evidence"]) for item in completeness)
    provenance_rows = sum(item["state"] == "ORIGINAL_CAPTURE_VERIFIED" for item in provenance)
    return {
        "suite": "ASTRA Trading Intelligence Improvement Suite V5", "version": VERSION,
        "status": "CAPTURE_READY" if truths else "INSUFFICIENT_EVIDENCE", "strict_truth_count": len(truths),
        "pretrade_context_capture": {"captured_strict_truths": context_rows, "future_capture_owner": "astra_premarket_certification_v1 -> build_pretrade_truth_context_v1", "immutable_original_context": True, "execution_effect": "NONE"},
        "excursion_capture": {"captured_strict_truths": excursion_rows, "future_capture_owner": "PaperAutopilot._update_open_row_snapshot", "incremental_persistence": "row_json passive evidence snapshot", "strict_truth_copy_owner": "PaperAutopilot._persist_strict_broker_truth", "historical_rows_reconstructed": False},
        "thesis_prediction_provenance": {"lifecycles": provenance, "original_capture_verified": provenance_rows, "partial_or_unavailable": len(truths) - provenance_rows, "historical_truths_retrofitted": False},
        "lifecycle_evidence_completeness": {"lifecycles": completeness, "strict_truth_authority_unchanged": True},
        "decision_evidence_attribution_ledger": {"ledgers": ledgers, "future_capture_only": True, "automatic_reweighting": False},
        "v1_v4_continuity": {"v4_status": v4.get("status"), "frozen_lifecycle_modified": False, "full_history_scan_count": 0},
        "warnings": ["PRETRADE_CONTEXT_UNAVAILABLE", "EXCURSION_EVIDENCE_INCOMPLETE", "PREDICTION_PROVENANCE_MISSING", "EVIDENCE_LEDGER_INCOMPLETE"],
        **SAFETY,
    }
