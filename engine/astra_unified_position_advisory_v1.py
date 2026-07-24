"""Canonical advisory arbitration plus worker-owned current-position projection.

The original ``unified_position_recommendation`` remains the only policy
arbiter.  The V1 projection below persists its output for every current broker
position; it does not add an execution path or a second recommendation policy.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_unified_position_advisory_v1"
UNIFIED_PRECEDENCE = [
    "DATA_INCOMPLETE_FAIL_CLOSED", "UNRESOLVED_FAIL_CLOSED", "HARD_BOUNDARY_BREACH",
    "THESIS_BROKEN", "MANDATORY_REVIEW", "EXIT_REVIEW", "PROTECT_PROFIT",
    "RECOVERY_WATCH", "WATCH", "HOLD",
]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
    """Original deterministic policy arbiter; always advisory-only."""
    lc, pp, peak = dict(loss_containment or {}), dict(profit_protection or {}), dict(peak_memory_entry or {})
    recommendation, rationale, state, confidence = "HOLD", [], "HEALTHY", 0.65
    if unresolved or ownership == "UNRESOLVED_FAIL_CLOSED":
        recommendation, rationale, state, confidence = "DATA_INCOMPLETE_FAIL_CLOSED", ["unresolved_ownership"], "UNRESOLVED_FAIL_CLOSED", 0.95
    elif stale_evidence:
        recommendation, rationale, state, confidence = "DATA_INCOMPLETE_FAIL_CLOSED", ["stale_critical_evidence"], "UNRESOLVED_FAIL_CLOSED", 0.95
    elif "HARD_BOUNDARY_BREACH" in _text(lc.get("threshold_state")).upper():
        recommendation, rationale, state, confidence = "HARD_BOUNDARY_BREACH", [f"hard_loss_boundary: {_text(lc.get('canonical_recommendation'))}"], "HARD_BOUNDARY_BREACH", 0.95
    elif thesis_broken or "THESIS_BROKEN" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "THESIS_BROKEN", ["thesis_explicitly_broken"], "THESIS_BROKEN", 0.85
    elif "MANDATORY_REVIEW" in _text(lc.get("threshold_state")).upper() or "EXIT_REVIEW" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "EXIT_REVIEW", ["existing_protection_review"], "MANDATORY_REVIEW", 0.80
    elif "PROTECT_PROFIT" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "PROTECT_PROFIT", ["profit_protection"], "PROTECT_PROFIT", 0.70
    elif support_failed:
        recommendation, rationale, state, confidence = "WATCH", ["support_failure_watch"], "WATCH", 0.60
    else:
        current_return = _num(peak.get("current_return_pct"), 0.0)
        giveback = peak.get("giveback_ratio")
        if isinstance(giveback, (int, float)) and giveback > 0.50:
            recommendation, rationale, state, confidence = "EXIT_REVIEW", [f"severe_giveback: {giveback:.2f}"], "EXIT_REVIEW", 0.75
        elif current_return < -20.0:
            recommendation, rationale, state, confidence = "EXIT_REVIEW", [f"severe_loss: {current_return:.1f}%"], "EXIT_REVIEW", 0.80
        elif current_return < -10.0:
            recommendation, rationale, state, confidence = "WATCH", [f"moderate_loss: {current_return:.1f}%"], "WATCH", 0.65
        else:
            rationale = ["position_within_tolerance"]
    return {"canonical_recommendation": recommendation, "unified_state": state, "unified_rationale": "; ".join(rationale),
            "confidence": round(confidence, 4), "advisory_only": True, "execution_authorized": False,
            "evidence_completeness": "incomplete" if (stale_evidence or unresolved) else "sufficient"}


def _index(rows: list[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {_text(row.get("symbol")).upper(): dict(row) for row in rows or [] if isinstance(row, Mapping) and _text(row.get("symbol"))}


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def build_unified_position_advisory_v1(
    broker_positions: Mapping[str, Mapping[str, Any]], *, evidence: Mapping[str, Any], triage: Mapping[str, Any],
    loss_containment: Mapping[str, Any] | None = None, profit_protection: Mapping[str, Any] | None = None,
    exit_readiness: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_by_symbol = _index(list(evidence.get("positions") or []))
    triage_by_symbol = _index(list(triage.get("positions") or []))
    loss_by_symbol = _index(list((loss_containment or {}).get("decisions", {}).values()))
    profit_by_symbol = _index(list((profit_protection or {}).get("decisions", {}).values()))
    exit_by_symbol = _index(list((exit_readiness or {}).get("positions") or []))
    rows = []
    for symbol in sorted(broker_positions or {}):
        evidence_row, triage_row = evidence_by_symbol.get(symbol, {}), triage_by_symbol.get(symbol, {})
        loss, profit = loss_by_symbol.get(symbol, {}), profit_by_symbol.get(symbol, {})
        legacy = bool(triage_row)
        policy = unified_position_recommendation(
            loss, profit, ownership="UNRESOLVED_FAIL_CLOSED" if evidence_row.get("canonical_lane_status") != "RESOLVED" and not legacy else "KNOWN",
            stale_evidence=evidence_row.get("quote_status") == "STALE" or evidence_row.get("completed_bar_status") == "STALE",
        )
        exit_row = exit_by_symbol.get(symbol, {})
        recommendation = _text(exit_row.get("recommendation")) or _text(triage_row.get("recommendation")) or _text(policy.get("canonical_recommendation")) or "WATCH"
        blocker = _text(exit_row.get("first_causal_blocker")) or _text(triage_row.get("first_causal_blocker")) or _text(evidence_row.get("first_causal_blocker")) or _text((loss.get("exact_blockers") or [""])[0]) or "EVIDENCE_UNAVAILABLE"
        confidence = _text(triage_row.get("confidence")) or _text(loss.get("confidence")) or _text(evidence_row.get("evidence_confidence")) or "LOW"
        rows.append({
            "symbol": symbol, "final_advisory": recommendation, "confidence": confidence,
            "priority": "HIGH" if recommendation in {"EXIT_REVIEW", "THESIS_BROKEN", "PROTECT_CAPITAL"} else "MEDIUM" if recommendation == "WATCH" else "LOW",
            "primary_reason": _text(triage_row.get("plain_english_reason")) or _text(loss.get("human_readable_reason")) or blocker,
            "supporting_reasons": [blocker], "evidence_used": triage_row.get("evidence_used") or {},
            "evidence_missing": triage_row.get("evidence_missing") or ([blocker] if blocker != "EVIDENCE_CURRENT" else []),
            "first_causal_blocker": blocker, "source_components": [name for name, row in (("position_evidence_completeness_v1", evidence_row), ("legacy_position_risk_triage_v1", triage_row), ("exit_readiness", exit_row), ("loss_containment", loss), ("profit_protection", profit)) if row],
            "legacy_position": legacy, "loss_containment_state": loss.get("canonical_recommendation"), "profit_protection_state": profit.get("canonical_recommendation") or profit.get("profit_state"),
            "generated_at": _now(), "execution_authority": "DISABLED", "advisory_only": True,
        })
    return {"schema_version": SCHEMA_VERSION, "generated_at": _now(), "broker_position_count": len(broker_positions or {}), "advisory_count": len(rows), "positions": rows,
            "silent_drop_count": max(0, len(broker_positions or {}) - len(rows)), "execution_authority": "DISABLED", "advisory_only": True,
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "state_mutations_from_get": 0, "paper_only_preserved": True}


def build_position_exit_readiness_v1(
    broker_positions: Mapping[str, Mapping[str, Any]], *, evidence: Mapping[str, Any], triage: Mapping[str, Any],
    loss_containment: Mapping[str, Any] | None = None, profit_protection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist the existing advisory policy inputs for every broker position.

    This is not an order authorization state machine.  It records whether the
    existing human-review recommendation has current evidence and keeps the
    first missing producer visible to the later unified advisory.
    """
    evidence_by_symbol = _index(list(evidence.get("positions") or []))
    triage_by_symbol = _index(list(triage.get("positions") or []))
    loss_by_symbol = _index(list((loss_containment or {}).get("decisions", {}).values()))
    profit_by_symbol = _index(list((profit_protection or {}).get("decisions", {}).values()))
    rows = []
    for symbol in sorted(broker_positions or {}):
        item, legacy, loss, profit = evidence_by_symbol.get(symbol, {}), triage_by_symbol.get(symbol, {}), loss_by_symbol.get(symbol, {}), profit_by_symbol.get(symbol, {})
        policy = unified_position_recommendation(loss, profit, ownership="KNOWN", stale_evidence=item.get("quote_status") == "STALE" or item.get("completed_bar_status") == "STALE")
        recommendation = _text(legacy.get("recommendation")) or _text(policy.get("canonical_recommendation")) or "WATCH"
        blocker = _text(legacy.get("first_causal_blocker")) or _text(item.get("first_causal_blocker")) or "EVIDENCE_UNAVAILABLE"
        rows.append({
            "symbol": symbol, "exit_readiness_state": "EVIDENCE_INCOMPLETE" if blocker != "EVIDENCE_CURRENT" else "ADVISORY_READY",
            "recommendation": recommendation, "confidence": _text(legacy.get("confidence")) or _text(policy.get("confidence")) or "LOW",
            "urgency": "HIGH" if recommendation in {"EXIT_REVIEW", "THESIS_BROKEN", "PROTECT_CAPITAL"} else "MEDIUM" if recommendation == "WATCH" else "LOW",
            "forward_value_state": _text(item.get("opportunity_cost_status")) or "MISSING", "risk_state": _text(loss.get("canonical_recommendation")) or "UNAVAILABLE",
            "profit_protection_state": _text(profit.get("canonical_recommendation") or profit.get("profit_state")) or "UNAVAILABLE",
            "legacy_triage_state": _text(legacy.get("recommendation")) or "NOT_APPLICABLE", "opportunity_cost_state": _text(item.get("opportunity_cost_status")) or "MISSING",
            "replacement_state": _text(item.get("replacement_candidate_status")) or "MISSING", "evidence_used": legacy.get("evidence_used") or {},
            "evidence_missing": legacy.get("evidence_missing") or ([blocker] if blocker != "EVIDENCE_CURRENT" else []), "first_causal_blocker": blocker,
            "plain_english_reason": _text(legacy.get("plain_english_reason")) or blocker.lower().replace("_", " "),
            "execution_authority": "DISABLED", "advisory_only": True,
        })
    return {"schema_version": "astra_position_exit_readiness_v1", "generated_at": _now(), "broker_position_count": len(broker_positions or {}),
            "positions_reviewed": len(rows), "positions": rows, "silent_drop_count": max(0, len(broker_positions or {}) - len(rows)),
            "execution_authority": "DISABLED", "advisory_only": True, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
            "state_mutations_from_get": 0, "paper_only_preserved": True}


def save_position_exit_readiness_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_position_exit_readiness_v1.json", payload)


def load_position_exit_readiness_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try: payload = json.loads((Path(state_dir) / "astra_position_exit_readiness_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return dict(payload) if isinstance(payload, dict) else {}


def save_unified_position_advisory_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_unified_position_advisory_v1.json", payload)


def load_unified_position_advisory_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try: payload = json.loads((Path(state_dir) / "astra_unified_position_advisory_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return dict(payload) if isinstance(payload, dict) else {}
