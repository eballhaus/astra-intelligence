"""Advisory-only triage for current broker positions with legacy metadata gaps."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_legacy_position_risk_triage_v1"
RECOMMENDATIONS = frozenset({"HOLD", "WATCH", "PROTECT_CAPITAL", "EXIT_REVIEW", "THESIS_BROKEN", "REPLACE_CANDIDATE"})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _legacy_symbols(recovery: Mapping[str, Any]) -> set[str]:
    return {
        _text(row.get("symbol")).upper()
        for row in recovery.get("positions") or []
        if isinstance(row, Mapping)
        and (
            _text(row.get("lane_status")).upper() != "RESOLVED"
            or _text(row.get("horizon_status")).upper() != "RESOLVED"
        )
        and _text(row.get("metadata_generation")).upper() != "V1_MANDATORY"
    }


def triage_legacy_position_v1(
    position: Mapping[str, Any],
    *,
    fmp_context: Mapping[str, Any] | None = None,
    replacement: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an explainable non-executing recommendation from current facts."""
    row = dict(position or {})
    fmp = dict(fmp_context or {})
    completeness = dict(evidence or {})
    fields = dict(fmp.get("normalized_fields") or {})
    symbol = _text(row.get("symbol")).upper()
    return_pct = _number(row.get("unrealized_plpc"), _number(row.get("unrealized_return_pct"), _number(row.get("return_pct"), 0.0) / 100.0))
    if abs(return_pct) > 1.0:
        return_pct /= 100.0
    momentum = _text(completeness.get("momentum_status") or row.get("momentum_state") or row.get("momentum")) or "UNAVAILABLE"
    thesis = _text(row.get("thesis_state")) or "ORIGINAL_THESIS_UNAVAILABLE"
    catalyst = _text(row.get("catalyst_state")) or ("CURRENT_CATALYST_NEUTRAL" if completeness.get("catalyst_status") in {"FRESH", "AGING"} else "NO_CURRENT_CATALYST_EVIDENCE")
    opportunity = _text(row.get("opportunity_cost_state")) or _text(completeness.get("opportunity_cost_status")) or "UNAVAILABLE"
    replacement_state = _text((replacement or {}).get("state")) or "UNAVAILABLE"
    missing = []
    if str(fmp.get("response_state") or "").upper() != "SUCCESS" and completeness.get("fundamentals_status") not in {"FRESH", "AGING"}:
        missing.append(_text(completeness.get("first_missing_producer")) or "FMP_CONTEXT_UNAVAILABLE")
    if momentum in {"UNAVAILABLE", "MISSING", "STALE"}:
        missing.append("MOMENTUM_EVIDENCE_UNAVAILABLE" if momentum != "STALE" else "MOMENTUM_EVIDENCE_STALE")
    broken = thesis.upper() in {"BROKEN", "INVALIDATED"} or catalyst.upper() in {"BROKEN", "NEGATIVE_CATALYST"}
    deteriorating = momentum.upper() in {"DETERIORATING", "WEAK", "NEGATIVE"}
    replacement_superior = replacement_state.upper() in {"SUPERIOR", "ELIGIBLE_SUPERIOR"}
    if broken:
        recommendation, blocker = "THESIS_BROKEN", "THESIS_OR_CATALYST_INVALIDATED"
    elif replacement_superior and (deteriorating or return_pct < 0):
        recommendation, blocker = "REPLACE_CANDIDATE", "SUPERIOR_REPLACEMENT_EVIDENCE"
    elif return_pct <= -0.08 and deteriorating:
        recommendation, blocker = "EXIT_REVIEW", "MATERIAL_LOSS_WITH_MOMENTUM_DETERIORATION"
    elif return_pct <= -0.04 and (deteriorating or opportunity.upper() == "HIGH"):
        recommendation, blocker = "PROTECT_CAPITAL", "LOSS_RISK_REQUIRES_MANUAL_REVIEW"
    elif missing or deteriorating or opportunity.upper() == "HIGH":
        recommendation, blocker = "WATCH", missing[0] if missing else "RISK_OR_OPPORTUNITY_REVIEW_REQUIRED"
    else:
        recommendation, blocker = "HOLD", "CURRENT_EVIDENCE_STABLE"
    confidence = "HIGH" if not missing and (fields or momentum != "UNAVAILABLE") else "LOW" if len(missing) > 1 else "MODERATE"
    return {
        "symbol": symbol,
        "generated_at": _now(),
        "recommendation": recommendation,
        "confidence": confidence,
        "decision_status": "INSUFFICIENT_EVIDENCE" if missing else "EVALUATED",
        "evidence_used": {
            "loss_severity": round(return_pct * 100.0, 3),
            "momentum_state": momentum,
            "thesis_state": thesis,
            "catalyst_state": catalyst,
            "position_age_state": _text(row.get("position_age_state") or completeness.get("position_age_status")) or "UNAVAILABLE",
            "liquidity_state": _text(row.get("liquidity_state") or completeness.get("liquidity_status")) or "UNAVAILABLE",
            "profit_giveback_state": _text(row.get("profit_giveback_state")) or "UNAVAILABLE",
            "opportunity_cost_state": opportunity,
            "replacement_state": replacement_state,
            "market_regime_state": _text(row.get("market_regime_state") or completeness.get("market_regime_status")) or "UNAVAILABLE",
            "fmp_profile_fields": sorted(fields),
        },
        "evidence_missing": missing,
        "provider_sources": ["FMP"] if fields else [],
        "first_causal_blocker": blocker,
        "plain_english_reason": f"{recommendation}: {blocker.lower().replace('_', ' ')}.",
        "advisory_only": True,
        "execution_authority": "DISABLED",
        "broker_actions_used": 0,
    }


def build_legacy_position_risk_triage_v1(
    broker_positions: Mapping[str, Mapping[str, Any]],
    recovery: Mapping[str, Any],
    *,
    fmp_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    position_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    legacy = _legacy_symbols(recovery)
    evidence_by_symbol = {
        _text(record.get("symbol")).upper(): dict(record)
        for record in (fmp_evidence or {}).values()
        if isinstance(record, Mapping) and _text(record.get("symbol"))
    }
    completeness_by_symbol = {
        _text(record.get("symbol")).upper(): dict(record)
        for record in (position_evidence or {}).values()
        if isinstance(record, Mapping) and _text(record.get("symbol"))
    }
    positions = [
        triage_legacy_position_v1(
            dict(raw or {}, symbol=_text((raw or {}).get("symbol") or symbol)),
            fmp_context=evidence_by_symbol.get(_text(symbol).upper()),
            evidence=completeness_by_symbol.get(_text(symbol).upper()),
        )
        for symbol, raw in sorted(broker_positions.items())
        if _text(symbol).upper() in legacy
    ]
    counts = {name.lower(): sum(row.get("recommendation") == name for row in positions) for name in RECOMMENDATIONS}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "broker_position_count": len(broker_positions),
        "legacy_position_count": len(legacy),
        "triaged_count": len(positions),
        **{f"{key}_count": int(value) for key, value in counts.items()},
        "insufficient_evidence_count": sum(row.get("decision_status") == "INSUFFICIENT_EVIDENCE" for row in positions),
        "FMP_evidence_used_count": sum(bool(row.get("provider_sources")) for row in positions),
        "positions": positions,
        "execution_authority": "DISABLED",
        "advisory_only": True,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "paper_only_preserved": True,
    }


def save_legacy_position_risk_triage_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_legacy_position_risk_triage_v1.json", payload)


def load_legacy_position_risk_triage_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try:
        payload = json.loads((Path(state_dir) / "astra_legacy_position_risk_triage_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
