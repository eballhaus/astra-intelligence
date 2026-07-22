"""Unified position advisory: deterministic arbitration between Loss Containment,
Profit Protection, peak memory, thesis, and momentum into one canonical recommendation.

This module is advisory-only. It does not submit orders or authorize execution.
"""
from __future__ import annotations

from typing import Any, Mapping

UNIFIED_PRECEDENCE = [
    "DATA_INCOMPLETE_FAIL_CLOSED",
    "UNRESOLVED_FAIL_CLOSED",
    "HARD_BOUNDARY_BREACH",
    "THESIS_BROKEN",
    "MANDATORY_REVIEW",
    "EXIT_REVIEW",
    "PROTECT_PROFIT",
    "RECOVERY_WATCH",
    "WATCH",
    "HOLD",
]


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def unified_position_recommendation(
    loss_containment: Mapping[str, Any] | None = None,
    profit_protection: Mapping[str, Any] | None = None,
    peak_memory_entry: Mapping[str, Any] | None = None,
    ownership: str = "UNKNOWN",
    thesis_broken: bool = False,
    support_failed: bool = False,
    stale_evidence: bool = False,
    unresolved: bool = False,
) -> dict[str, Any]:
    """Produce one canonical advisory recommendation per position.

    Uses deterministic precedence: fail-closed → hard loss → thesis → mandatory review
    → exit review → protect profit → recovery watch → watch → hold.
    """
    lc = dict(loss_containment or {})
    pp = dict(profit_protection or {})
    peak = dict(peak_memory_entry or {})

    recommendation = "HOLD"
    rationale_parts: list[str] = []
    state = "HEALTHY"
    confidence = 0.65

    if unresolved or ownership == "UNRESOLVED_FAIL_CLOSED":
        recommendation = "DATA_INCOMPLETE_FAIL_CLOSED"
        rationale_parts.append("unresolved_ownership")
        state = "UNRESOLVED_FAIL_CLOSED"
        confidence = 0.95
    elif stale_evidence:
        recommendation = "DATA_INCOMPLETE_FAIL_CLOSED"
        rationale_parts.append("stale_critical_evidence")
        state = "UNRESOLVED_FAIL_CLOSED"
        confidence = 0.95
    elif "HARD_BOUNDARY_BREACH" in _text(lc.get("threshold_state")).upper():
        recommendation = "HARD_BOUNDARY_BREACH"
        rationale_parts.append(f"hard_loss_boundary: {_text(lc.get('canonical_recommendation'))}")
        state = "HARD_BOUNDARY_BREACH"
        confidence = 0.95
    elif thesis_broken:
        recommendation = "THESIS_BROKEN"
        rationale_parts.append("thesis_explicitly_broken")
        state = "THESIS_BROKEN"
        confidence = 0.85
    elif "THESIS_BROKEN" in _text(pp.get("profit_state")).upper():
        recommendation = "THESIS_BROKEN"
        rationale_parts.append("profit_protection_thesis_broken")
        state = "THESIS_BROKEN"
        confidence = 0.85
    elif "MANDATORY_REVIEW" in _text(lc.get("threshold_state")).upper():
        recommendation = "EXIT_REVIEW"
        rationale_parts.append("mandatory_loss_review")
        state = "MANDATORY_REVIEW"
        confidence = 0.80
    elif "EXIT_REVIEW" in _text(pp.get("profit_state")).upper():
        recommendation = "EXIT_REVIEW"
        rationale_parts.append(f"profit_exit_review: {_text(pp.get('human_readable_reason'))}")
        state = "EXIT_REVIEW"
        confidence = 0.80
    elif "PROTECT_PROFIT" in _text(pp.get("profit_state")).upper():
        recommendation = "PROTECT_PROFIT"
        rationale_parts.append(f"profit_protection: {_text(pp.get('human_readable_reason'))}")
        state = "PROTECT_PROFIT"
        confidence = 0.70
    elif "LOSS_CONTAINMENT_PRIORITY" in _text(pp.get("profit_state")).upper():
        recommendation = "HOLD"
        rationale_parts.append("loss_containment_deferred_to")
        state = "WATCH"
        confidence = 0.60
    elif support_failed:
        recommendation = "WATCH"
        rationale_parts.append("support_failure_watch")
        state = "WATCH"
        confidence = 0.60
    else:
        current_return = _num(peak.get("current_return_pct"), 0.0)
        giveback = peak.get("giveback_ratio")
        if giveback is not None and isinstance(giveback, (int, float)) and giveback > 0.50:
            recommendation = "EXIT_REVIEW"
            rationale_parts.append(f"severe_giveback: {giveback:.2f}")
            state = "EXIT_REVIEW"
            confidence = 0.75
        elif current_return < -20.0:
            recommendation = "EXIT_REVIEW"
            rationale_parts.append(f"severe_loss: {current_return:.1f}%")
            state = "EXIT_REVIEW"
            confidence = 0.80
        elif current_return < -10.0:
            recommendation = "WATCH"
            rationale_parts.append(f"moderate_loss: {current_return:.1f}%")
            state = "WATCH"
            confidence = 0.65
        else:
            recommendation = "HOLD"
            rationale_parts.append("position_within_tolerance")
            state = "HEALTHY"
            confidence = 0.65

    return {
        "canonical_recommendation": recommendation,
        "unified_state": state,
        "unified_rationale": "; ".join(rationale_parts) or "no_determining_evidence",
        "confidence": round(confidence, 4),
        "advisory_only": True,
        "execution_authorized": False,
        "evidence_completeness": "incomplete" if (stale_evidence or unresolved) else "sufficient",
    }
