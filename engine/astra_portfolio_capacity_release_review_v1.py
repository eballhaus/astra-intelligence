"""Advisory portfolio congestion and capacity-release review.

The classifier consumes existing position snapshots and never creates an exit
order.  It is intentionally conservative: missing evidence produces
``DATA_INSUFFICIENT`` rather than an inferred release recommendation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


STATES = (
    "KEEP", "WATCH", "PROTECT_PROFIT", "EXIT_REVIEW",
    "CONTROLLED_LOSS_ACCEPTABLE", "THESIS_BROKEN", "REPLACE_CANDIDATE",
    "DATA_INSUFFICIENT",
)

PRIMARY_STATES = (
    "HOLD", "WATCH", "PROTECT_PROFIT", "EXIT_REVIEW", "REPLACE_CANDIDATE",
    "THESIS_BROKEN", "DUST_CLEANUP_REVIEW", "INSUFFICIENT_EVIDENCE",
)


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _age_days(row: Mapping[str, Any]) -> float | None:
    for key in ("position_age_days", "days_held", "age_days"):
        value = _number(row.get(key))
        if value is not None:
            return max(0.0, value)
    raw = _text(row.get("entry_timestamp") or row.get("opened_at") or row.get("created_at"))
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 86400.0)
    except ValueError:
        return None


def classify_position(row: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = dict(row or {})
    # Context is a bounded retrieval overlay.  Fresh broker values remain the
    # position source of truth while lineage and learning fields are consumed
    # only when a concrete symbol-level link was found.
    for key, value in dict(context or {}).items():
        if key not in source or source.get(key) in (None, "", [], {}):
            source[key] = value
    symbol = _text(source.get("symbol") or source.get("ticker")).upper()
    entry = _number(source.get("avg_entry_price") or source.get("entry_price"))
    current = _number(source.get("current_price") or source.get("market_price"))
    age = _age_days(source)
    missing = [key for key, value in (("symbol", symbol), ("entry_price", entry), ("current_price", current)) if value in (None, "") or value == ""]
    reported_return = _number(source.get("unrealized_return_pct"))
    if reported_return is None:
        reported_return = _number(source.get("unrealized_plpc"))
    if reported_return is None and entry not in (None, 0.0) and current is not None:
        reported_return = (current - entry) / entry
    metrics = {
        "position_age_days": round(age, 4) if age is not None else None,
        "unrealized_return_pct": reported_return,
        "unrealized_pnl": _number(source.get("unrealized_pnl")) if source.get("unrealized_pnl") is not None else _number(source.get("unrealized_pl")),
        "return_per_day": _number(source.get("return_per_day")),
        "profit_giveback_pct": _number(source.get("profit_giveback_pct")),
        "opportunity_cost_score": _number(source.get("opportunity_cost_score")),
        "replacement_score": _number(source.get("replacement_score")),
    }
    reasons: list[str] = []
    contradictions: list[str] = []
    state = "DATA_INSUFFICIENT"
    confidence = "low"
    dust_position = _number(source.get("market_value")) is not None and abs(_number(source.get("market_value")) or 0.0) < 0.01
    if not missing:
        thesis = _text(source.get("thesis_state") or source.get("thesis_status")).lower()
        horizon_expired = bool(source.get("horizon_expired")) or _number(source.get("days_beyond_horizon")) is not None and _number(source.get("days_beyond_horizon")) > 0
        duplicate = bool(source.get("duplicate_exposure") or source.get("duplicate_exposure_state") in {"DUPLICATE", "DUPLICATE_EXPOSURE"})
        replacement_fresh = bool(source.get("replacement_fresh") or source.get("replacement_candidate_id"))
        opportunity = metrics["opportunity_cost_score"] or 0.0
        giveback = metrics["profit_giveback_pct"] or 0.0
        ret = metrics["unrealized_return_pct"]
        if dust_position:
            state, confidence = "DATA_INSUFFICIENT", "high"
            reasons.append("DUST_POSITION_REQUIRES_MANUAL_CLEANUP_REVIEW")
        elif "broken" in thesis or thesis in {"damaged", "invalidated"}:
            state, confidence = "THESIS_BROKEN", "high"
            reasons.append("THESIS_BROKEN")
        elif duplicate:
            state, confidence = "REPLACE_CANDIDATE", "medium"
            reasons.append("DUPLICATE_EXPOSURE")
        elif opportunity >= 75.0 and replacement_fresh:
            state, confidence = "REPLACE_CANDIDATE", "medium"
            reasons.extend(("HIGH_OPPORTUNITY_COST", "STRONGER_REPLACEMENT_AVAILABLE"))
        elif horizon_expired:
            state, confidence = "EXIT_REVIEW", "medium"
            reasons.append("HORIZON_EXPIRED")
        elif giveback >= 50.0 and (ret or 0.0) > 0:
            state, confidence = "PROTECT_PROFIT", "medium"
            reasons.append("PROFIT_GIVEBACK")
        elif (ret or 0.0) < 0:
            # A loss alone is not evidence that capital should be abandoned.
            # Keep the position in an advisory watch state until a linked
            # thesis, horizon, recovery, or replacement signal says more.
            recovery = bool(source.get("recent_recovery") or source.get("recovery_in_progress"))
            forward_value = _text(source.get("forward_value_status")).lower()
            loss_support = bool(source.get("controlled_loss_supported"))
            if loss_support and forward_value in {"unfavorable", "negative"} and (horizon_expired or opportunity >= 75.0):
                state, confidence = "EXIT_REVIEW", "medium"
                reasons.append("CONTROLLED_LOSS_FORWARD_VALUE_UNFAVORABLE")
            else:
                state, confidence = "WATCH", "medium" if recovery else "low"
                reasons.append("RECOVERY_IN_PROGRESS" if recovery else "LOSS_REQUIRES_LINKED_FORWARD_EVIDENCE")
                contradictions.append("RECOVERY_MOMENTUM_PRESENT" if recovery else "FORWARD_VALUE_NOT_YET_LINKED")
        elif source.get("momentum_deterioration"):
            state, confidence = "WATCH", "medium"
            reasons.append("MOMENTUM_DETERIORATION")
        else:
            state, confidence = "KEEP", "medium"
            reasons.append("NORMAL_VOLATILITY")
    else:
        reasons.append("INSUFFICIENT_DATA")
    primary_state = {
        "KEEP": "HOLD",
        "CONTROLLED_LOSS_ACCEPTABLE": "WATCH",
        "DATA_INSUFFICIENT": "INSUFFICIENT_EVIDENCE",
    }.get(state, state)
    if dust_position:
        primary_state = "DUST_CLEANUP_REVIEW"
    market_value = _number(source.get("market_value"))
    secondary: list[str] = []
    if primary_state == "HOLD":
        secondary.append("NORMAL_VOLATILITY")
    if bool(source.get("recent_recovery") or source.get("recovery_in_progress")):
        secondary.append("RECOVERY_IN_PROGRESS")
    if bool(source.get("momentum_improving")):
        secondary.append("MOMENTUM_IMPROVING")
    if bool(source.get("momentum_deterioration")) or "MOMENTUM_DETERIORATION" in reasons:
        secondary.append("MOMENTUM_DECAY")
    if (metrics["profit_giveback_pct"] or 0.0) > 0.0 or "PROFIT_GIVEBACK" in reasons:
        secondary.append("PROFIT_GIVEBACK_RISK")
    if "HORIZON_EXPIRED" in reasons or bool(source.get("horizon_expired")):
        secondary.append("HORIZON_EXPIRED")
    if metrics["return_per_day"] is not None and metrics["return_per_day"] < 0.5:
        secondary.append("LOW_RETURN_PER_DAY")
    if (metrics["opportunity_cost_score"] or 0.0) >= 75.0:
        secondary.append("HIGH_OPPORTUNITY_COST")
    if bool(source.get("controlled_loss_supported")):
        secondary.append("CONTROLLED_LOSS_ACCEPTABLE")
    if bool(source.get("catalyst_pending") or str(source.get("catalyst_condition") or "").lower() in {"pending", "upcoming"}):
        secondary.append("CATALYST_PENDING")
    if bool(source.get("regime_mismatch") or source.get("regime_alignment") in {"mismatch", "misaligned"}):
        secondary.append("REGIME_MISMATCH")
    if bool(source.get("concentration_risk") or source.get("correlation_risk")):
        secondary.append("CONCENTRATION_RISK")
    if bool(source.get("stale_thesis") or "STALE_THESIS" in reasons):
        secondary.append("STALE_THESIS")
    missing_evidence = [str(value) for value in (source.get("missing_evidence") or []) if value]
    if missing or missing_evidence:
        secondary.append("MISSING_LIFECYCLE_DATA")

    influence_sources = {
        "ranking": ("ranking_score", "rank", "original_rank"),
        "horizon": ("horizon", "intended_trade_style", "assigned_horizon", "intended_horizon", "horizon_source"),
        "momentum": ("momentum_strength", "relative_strength", "momentum_deterioration"),
        "symbol_behavior": ("symbol_behavior", "symbol_behavior_score", "symbol_profile"),
        "mfe_mae": ("mfe", "mae", "maximum_favorable_excursion", "maximum_adverse_excursion"),
        "profit_giveback": ("profit_giveback_pct", "giveback", "giveback_risk"),
        "return_per_day": ("return_per_day",),
        "opportunity_cost": ("opportunity_cost_score", "opportunity_cost"),
        "historical_similarity": ("historical_similarity", "similarity_score"),
        "replay": ("replay_score", "replay_evidence", "replay_status"),
        "shadow_evidence": ("shadow_evidence", "shadow_score", "shadow_status"),
        "broker_truth": ("symbol", "qty", "avg_entry_price", "current_price", "market_value"),
        "regime": ("regime", "regime_alignment", "market_regime"),
        "sector": ("sector", "sector_alignment", "sector_strength"),
        "catalyst": ("catalyst", "catalyst_condition", "catalyst_decay"),
        "portfolio_concentration": ("concentration_risk", "correlation_risk", "portfolio_weight"),
        "replacement_quality": ("replacement_score", "replacement_candidate_id", "replacement_fresh"),
        "governance": ("governance_finding", "governance_status"),
    }
    influence_attribution = {
        name: ("ACTIVE_CONSUMER" if any(source.get(key) not in (None, "", [], {}) for key in keys) else "MISSING")
        for name, keys in influence_sources.items()
    }
    # Broker truth is the source that made this classification possible; the
    # remaining labels accurately distinguish consumed evidence from absent
    # evidence rather than implying that a dashboard display was consumption.
    influence_attribution["broker_truth"] = "ACTIVE_CONSUMER"
    consumer_acknowledgement = {
        "consumer": "portfolio_capacity_release_review_v1",
        "status": "ACKNOWLEDGED",
        "classification_used_broker_truth": True,
        "influence_attribution": influence_attribution,
        "persisted_evidence_reference": source.get("position_id") or source.get("asset_id") or symbol,
    }
    retrieval = dict(source.get("retrieval") or {})
    evidence_confidence = _number(source.get("evidence_confidence"))
    return {
        "position_id": _text(source.get("position_id")),
        "symbol": symbol,
        "lane_id": _text(source.get("lane_id") or source.get("position_owner")).upper() or "SWING",
        "state": state,
        "primary_state": primary_state if primary_state in PRIMARY_STATES else "INSUFFICIENT_EVIDENCE",
        "secondary_labels": list(dict.fromkeys(secondary)),
        "confidence": confidence,
        "reason_codes": list(dict.fromkeys(reasons)),
        "plain_english_explanation": f"{state.replace('_', ' ').title()} based on available position evidence; no broker action is authorized.",
        "supporting_metrics": metrics,
        "contradicting_evidence": contradictions,
        "human_review_required": state in {"EXIT_REVIEW", "THESIS_BROKEN", "REPLACE_CANDIDATE", "CONTROLLED_LOSS_ACCEPTABLE"},
        "estimated_capacity_released_if_closed": 1 if state in {"EXIT_REVIEW", "THESIS_BROKEN", "REPLACE_CANDIDATE"} else 0,
        "missing_fields": missing,
        "data_quality": "COMPLETE" if not missing else "INCOMPLETE",
        "evidence_class": _text(source.get("evidence_class")) or "BROKER_POSITION_SNAPSHOT_DIAGNOSTIC",
        "lineage": dict(source.get("lineage") or {}),
        "retrieval": retrieval,
        "missing_evidence": missing_evidence,
        "evidence_confidence": evidence_confidence,
        "position_snapshot": {
            "quantity": _number(source.get("qty") or source.get("quantity")),
            "average_entry_price": entry,
            "current_price": current,
            "market_value": market_value,
            "unrealized_pnl": metrics["unrealized_pnl"],
            "unrealized_pnl_pct": metrics["unrealized_return_pct"],
            "todays_pnl": _number(source.get("today_pnl") or source.get("change_today")),
            "entry_timestamp": source.get("entry_timestamp") or source.get("opened_at") or source.get("created_at"),
        },
        "decision_influence": influence_attribution,
        "consumer_acknowledgement": consumer_acknowledgement,
        "automatic_action_authorized": False,
    }

def build_portfolio_release_review(
    rows: Iterable[Mapping[str, Any]] | None = None,
    context_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    context_map = {str(symbol or "").upper(): dict(value or {}) for symbol, value in dict(context_by_symbol or {}).items()}
    reviews = [
        classify_position(
            row,
            context_map.get(_text(row.get("symbol") or row.get("ticker")).upper()),
        )
        for row in (rows or [])
        if isinstance(row, Mapping)
    ]
    counts = {state: sum(1 for row in reviews if row.get("state") == state) for state in STATES}
    primary_counts = {state: sum(1 for row in reviews if row.get("primary_state") == state) for state in PRIMARY_STATES}
    action_queue = {
        "thesis_failures": [row.get("symbol") for row in reviews if row.get("primary_state") == "THESIS_BROKEN"],
        "exit_reviews": [row.get("symbol") for row in reviews if row.get("primary_state") == "EXIT_REVIEW"],
        "replacement_candidates": [row.get("symbol") for row in reviews if row.get("primary_state") == "REPLACE_CANDIDATE"],
        "profit_protection_candidates": [row.get("symbol") for row in reviews if row.get("primary_state") == "PROTECT_PROFIT"],
        "recovery_candidates": [row.get("symbol") for row in reviews if "RECOVERY_IN_PROGRESS" in (row.get("secondary_labels") or [])],
        "strongest_holds": [
            row.get("symbol") for row in sorted(
                (row for row in reviews if row.get("primary_state") == "HOLD"),
                key=lambda row: _number((row.get("position_snapshot") or {}).get("unrealized_pnl_pct")) or -999.0,
                reverse=True,
            )
        ],
        "dust_anomalies": [row.get("symbol") for row in reviews if row.get("primary_state") == "DUST_CLEANUP_REVIEW"],
        "insufficient_evidence": [row.get("symbol") for row in reviews if row.get("primary_state") == "INSUFFICIENT_EVIDENCE"],
    }
    influence_summary = {}
    for name in (reviews[0].get("decision_influence") or {}).keys() if reviews else ():
        influence_summary[name] = sum(
            1 for row in reviews if (row.get("decision_influence") or {}).get(name) == "ACTIVE_CONSUMER"
        )
    meaningful = [row for row in reviews if row.get("primary_state") != "DUST_CLEANUP_REVIEW"]
    secondary_counts: dict[str, int] = {}
    evidence_gap_counts: dict[str, int] = {}
    for row in meaningful:
        for label in row.get("secondary_labels") or []:
            if label == "MISSING_LIFECYCLE_DATA":
                evidence_gap_counts[label] = evidence_gap_counts.get(label, 0) + 1
            else:
                secondary_counts[label] = secondary_counts.get(label, 0) + 1
    dominant_secondary = max(secondary_counts, key=secondary_counts.get) if secondary_counts else None
    dominant_count = secondary_counts.get(dominant_secondary, 0) if dominant_secondary else 0
    blanket_detected = bool(meaningful and dominant_count / len(meaningful) > 0.5)
    retrieval_counts = {
        "complete_lineage": sum(1 for row in meaningful if (row.get("retrieval") or {}).get("coverage") == "COMPLETE_LINEAGE"),
        "partial_lineage": sum(1 for row in meaningful if (row.get("retrieval") or {}).get("coverage") == "PARTIAL_LINEAGE"),
        "broker_only": sum(1 for row in meaningful if (row.get("retrieval") or {}).get("coverage") == "BROKER_ONLY"),
    }
    return {
        "portfolio_capacity_release_review_v1": True,
        "total_positions": len(reviews),
        "positions_by_state": counts,
        "primary_state_counts": primary_counts,
        "classification_table": reviews,
        "review_rows": reviews,
        "action_queue": action_queue,
        "influence_summary": influence_summary,
        "retrieval_coverage": retrieval_counts,
        "differentiation_audit": {
            "meaningful_positions": len(meaningful),
            "secondary_state_counts": secondary_counts,
            "evidence_gap_counts": evidence_gap_counts,
            "dominant_secondary_state": dominant_secondary,
            "dominant_secondary_count": dominant_count,
            "blanket_fallback_detected": blanket_detected,
            "status": "REVIEW_REQUIRED" if blanket_detected else "DIFFERENTIATED_OR_EVIDENCE_LIMITED",
        },
        "estimated_releasable_slots": sum(int(row.get("estimated_capacity_released_if_closed") or 0) for row in reviews),
        "estimated_releasable_capital": None,
        "automatic_action_authorized": False,
        "human_review_required": any(bool(row.get("human_review_required")) for row in reviews),
        "no_exit_orders_submitted": True,
        "source": "existing_cached_position_snapshot",
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }
