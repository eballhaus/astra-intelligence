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

RELEASE_STATES = ("EXIT_REVIEW", "THESIS_BROKEN", "REPLACE_CANDIDATE")


def _releasable_capital_facts(reviews: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure real releasable capital from broker-derived market values.

    Only positions already in a release-review state contribute.  Missing
    market value keeps the estimate UNKNOWN rather than fabricating a dollar
    figure; no ceiling, allocation, or capacity rule is applied here.
    """
    components: list[dict[str, Any]] = []
    actual: list[float] = []
    for row in reviews:
        if row.get("primary_state") not in RELEASE_STATES:
            continue
        symbol = _text(row.get("symbol"))
        market_value = _number((row.get("position_snapshot") or {}).get("market_value"))
        item = {"symbol": symbol, "release_state": row.get("primary_state"), "market_value": market_value}
        components.append(item)
        if market_value is not None and market_value >= 0.0:
            actual.append(market_value)
    if not components:
        return {
            "estimated_releasable_capital": None,
            "releasable_capital_status": "UNKNOWN_NO_RELEASE_CANDIDATES",
            "releasable_capital_basis": "no_position_recommended_for_release_review",
            "releasable_capital_components": [],
        }
    if not actual:
        return {
            "estimated_releasable_capital": None,
            "releasable_capital_status": "UNKNOWN_MARKET_VALUE_MISSING",
            "releasable_capital_basis": "release_candidates_without_broker_market_value",
            "releasable_capital_components": components[:20],
        }
    return {
        "estimated_releasable_capital": round(sum(actual), 2),
        "releasable_capital_status": "OBSERVATIONAL_BROKER_DERIVED",
        "releasable_capital_basis": "sum_of_real_broker_position_market_values_for_release_candidates",
        "releasable_capital_components": components[:20],
    }


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def reconstruct_position_lineage(
    broker_row: Mapping[str, Any],
    candidate_rows: Iterable[Mapping[str, Any]],
    *,
    timestamp_window_seconds: float = 300.0,
) -> dict[str, Any]:
    """Return an exact lineage match or an explicit, non-invented blocker.

    Historical candidate ledgers are not broker truth.  A row is therefore
    linked only when an authoritative identifier is unique, or when a single
    same-symbol record falls inside a deliberately tight timestamp window.
    """
    broker = dict(broker_row or {})
    symbol = _text(broker.get("symbol")).upper()
    candidates = [dict(row) for row in candidate_rows if isinstance(row, Mapping)]
    key_groups = (
        ("broker_order_id", ("broker_order_id", "order_id"), "BROKER_LINKED_EXACT"),
        ("client_order_id", ("client_order_id",), "IDENTIFIER_LINKED_HIGH_CONFIDENCE"),
        ("fill_id", ("fill_id",), "IDENTIFIER_LINKED_HIGH_CONFIDENCE"),
        ("recommendation_id", ("recommendation_id",), "IDENTIFIER_LINKED_HIGH_CONFIDENCE"),
        ("candidate_id", ("candidate_id", "decision_id"), "IDENTIFIER_LINKED_HIGH_CONFIDENCE"),
        ("lifecycle_id", ("lifecycle_id",), "IDENTIFIER_LINKED_HIGH_CONFIDENCE"),
    )
    for broker_key, candidate_keys, confidence in key_groups:
        target = _text(broker.get(broker_key))
        if not target:
            continue
        matches = [
            row for row in candidates
            if any(_text(row.get(key)) == target for key in candidate_keys)
        ]
        if len(matches) == 1:
            return {
                "status": "LINKED",
                "record": matches[0],
                "reconstruction_method": broker_key,
                "reconstruction_confidence": confidence,
                "ambiguity_count": 0,
                "conflicting_candidate_count": 0,
            }
        if len(matches) > 1:
            return {
                "status": "AMBIGUOUS_REJECTED",
                "record": None,
                "reconstruction_method": broker_key,
                "reconstruction_confidence": "AMBIGUOUS_REJECTED",
                "ambiguity_count": len(matches),
                "conflicting_candidate_count": len(matches),
            }

    entry_time = _timestamp(broker.get("entry_timestamp") or broker.get("filled_at") or broker.get("broker_timestamp"))
    if symbol and entry_time:
        matches = []
        for row in candidates:
            if _text(row.get("symbol") or row.get("ticker")).upper() != symbol:
                continue
            candidate_time = _timestamp(row.get("timestamp_utc") or row.get("timestamp") or row.get("generated_at"))
            if candidate_time and abs((candidate_time - entry_time).total_seconds()) <= timestamp_window_seconds:
                matches.append(row)
        if len(matches) == 1:
            return {
                "status": "LINKED",
                "record": matches[0],
                "reconstruction_method": "symbol_tightly_bounded_timestamp",
                "reconstruction_confidence": "TIMESTAMP_LINKED_HIGH_CONFIDENCE",
                "ambiguity_count": 0,
                "conflicting_candidate_count": 0,
            }
        if len(matches) > 1:
            return {
                "status": "AMBIGUOUS_REJECTED",
                "record": None,
                "reconstruction_method": "symbol_tightly_bounded_timestamp",
                "reconstruction_confidence": "AMBIGUOUS_REJECTED",
                "ambiguity_count": len(matches),
                "conflicting_candidate_count": len(matches),
            }
    return {
        "status": "NOT_RECOVERABLE",
        "record": None,
        "reconstruction_method": "no_unique_identifier_or_timestamp_match",
        "reconstruction_confidence": "NOT_RECOVERABLE",
        "ambiguity_count": 0,
        "conflicting_candidate_count": 0,
    }


def validate_excursion_record(
    record: Mapping[str, Any],
    *,
    entry_price: Any,
    current_price: Any,
) -> dict[str, Any]:
    """Normalize a lifecycle excursion record and quarantine impossible rows."""
    row = dict(record or {})
    entry = _number(entry_price)
    current = _number(current_price)
    def first_numeric(*keys: str) -> float | None:
        for key in keys:
            if key in row and row.get(key) not in (None, ""):
                return _number(row.get(key))
        return None

    mfe = first_numeric("max_favorable_excursion_pct", "mfe_pct", "mfe")
    mae = first_numeric("max_adverse_excursion_pct", "mae_pct", "mae")
    peak = _number(row.get("peak_unrealized_profit_pct"))
    giveback = first_numeric("profit_giveback_pct", "giveback")
    capture = first_numeric("profit_capture_ratio", "capture_ratio")
    record_entry = _number(row.get("entry_price"))
    record_current = _number(row.get("current_price") or row.get("last_price_seen"))
    current_return = ((current - entry) / entry * 100.0) if entry and current is not None else None
    errors: list[str] = []
    if entry is None or entry <= 0 or current is None:
        return {"status": "INSUFFICIENT_PRICE_HISTORY", "errors": ["missing_broker_entry_or_current_price"]}
    if record_entry is not None and abs(record_entry - entry) / entry > 0.015:
        errors.append("entry_price_mismatch")
    if record_current is not None and abs(record_current - current) / max(abs(current), 0.01) > 0.20:
        errors.append("stale_or_mismatched_current_price")
    if mfe is None or mae is None:
        return {"status": "PARTIAL_EXCURSION", "errors": errors + ["mfe_or_mae_missing"]}
    if mae > 0:
        errors.append("mae_positive_for_long_position")
    if current_return is not None and mfe + 0.0001 < current_return:
        errors.append("mfe_below_current_return")
    if giveback is not None and giveback < 0:
        errors.append("negative_giveback")
    if capture is not None and not 0.0 <= capture <= 1.0001:
        errors.append("capture_ratio_out_of_range")
    if errors:
        return {"status": "QUARANTINED_IMPOSSIBLE_EXCURSION", "errors": errors}
    peak = max(peak if peak is not None else mfe, mfe, current_return or 0.0)
    giveback = max(0.0, giveback if giveback is not None else peak - max(0.0, current_return or 0.0))
    return {
        "status": "BROKER_AND_MARKET_OBSERVED",
        "errors": [],
        "mfe_pct": round(mfe, 4),
        "mae_pct": round(mae, 4),
        "peak_unrealized_profit_pct": round(peak, 4),
        "current_return_pct": round(current_return, 4) if current_return is not None else None,
        "giveback_pct": round(giveback, 4),
        "capture_ratio": round(capture if capture is not None else (max(0.0, current_return or 0.0) / peak if peak > 0 else 0.0), 4),
        "time_to_mfe_seconds": _number(row.get("time_to_mfe_seconds")),
        "time_to_mae_seconds": _number(row.get("time_to_mae_seconds")),
        "source_lifecycle_id": _text(row.get("lifecycle_id")) or None,
    }


def replacement_analysis(
    position: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare only already-eligible cached candidates; never creates an order."""
    symbol = _text(position.get("symbol")).upper()
    eligible = []
    for raw in candidates:
        row = dict(raw or {})
        candidate_symbol = _text(row.get("symbol") or row.get("ticker")).upper()
        qualification = _text(row.get("qualification")).lower()
        is_eligible = bool(row.get("eligible") or row.get("paper_eligible") or row.get("selected")) or qualification in {"paper_ready", "paper_ready_candidate", "released_buy"}
        if candidate_symbol and candidate_symbol != symbol and is_eligible:
            eligible.append(row)
    if not eligible:
        return {"replacement_state": "NO_ELIGIBLE_REPLACEMENT", "candidate": None, "confidence": 0.0, "reason": "no_current_candidate_passed_existing_eligibility_and_safety_gates"}
    incumbent_return = _number(position.get("return_per_day")) or 0.0
    def score(row: Mapping[str, Any]) -> float:
        return (_number(row.get("expected_return_per_day")) or 0.0) + (_number(row.get("confidence")) or 0.0) / 100.0
    best = max(eligible, key=score)
    advantage = score(best) - incumbent_return
    state = "REPLACEMENT_ADVANTAGE_HIGH" if advantage >= 2.0 else "REPLACEMENT_ADVANTAGE_MODERATE" if advantage >= 0.75 else "REPLACEMENT_ADVANTAGE_LOW"
    return {
        "replacement_state": state,
        "candidate": {"symbol": _text(best.get("symbol") or best.get("ticker")).upper(), "confidence": _number(best.get("confidence")), "rank": best.get("rank"), "score": best.get("score")},
        "confidence": min(80.0, max(20.0, (_number(best.get("confidence")) or 0.0))),
        "reason": "comparison_uses_existing_eligible_cached_candidate_only",
        "expected_advantage": round(advantage, 4),
    }


def fallback_concentration_audit(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    meaningful = [dict(row) for row in rows if _text(row.get("primary_state")) != "DUST_CLEANUP_REVIEW"]
    counts: dict[str, int] = {}
    for row in meaningful:
        state = _text(row.get("primary_state")) or "INSUFFICIENT_EVIDENCE"
        counts[state] = counts.get(state, 0) + 1
    dominant = max(counts, key=counts.get) if counts else None
    dominant_count = counts.get(dominant, 0) if dominant else 0
    return {
        "primary_state_counts": counts,
        "dominant_primary_state": dominant,
        "dominant_primary_state_count": dominant_count,
        "blanket_fallback_detected": bool(meaningful and dominant_count / len(meaningful) > 0.5),
        "meaningful_positions": len(meaningful),
    }


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
    horizon_expired = bool(source.get("horizon_expired")) or (
        _number(source.get("days_beyond_horizon")) is not None and _number(source.get("days_beyond_horizon")) > 0
    )
    if not missing:
        thesis = _text(source.get("thesis_state") or source.get("thesis_status")).lower()
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
        elif bool(source.get("profit_protection_trigger")) or (giveback >= 50.0 and (ret or 0.0) > 0):
            state, confidence = "PROTECT_PROFIT", "medium"
            reasons.append("PROFIT_GIVEBACK_AND_WEAKENING_CONTINUATION" if bool(source.get("profit_protection_trigger")) else "PROFIT_GIVEBACK")
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
    if (metrics["profit_giveback_pct"] or 0.0) > 0.0 or any(reason.startswith("PROFIT_GIVEBACK") for reason in reasons):
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
        "original_recommendation": source.get("original_recommendation_id") or (source.get("lineage") or {}).get("original_recommendation_id"),
        "original_rank": source.get("original_rank") or (source.get("lineage") or {}).get("original_rank"),
        "original_thesis": source.get("original_thesis") or (source.get("lineage") or {}).get("original_thesis"),
        "thesis_status": source.get("thesis_state") or "ORIGINAL_THESIS_NOT_RECOVERABLE",
        "intended_horizon": source.get("intended_horizon") or source.get("intended_trade_style"),
        "horizon_status": source.get("horizon_status") or ("HORIZON_EXPIRED" if horizon_expired else "WITHIN_OBSERVED_WINDOW"),
        "mfe_pct": _number(source.get("mfe")),
        "mae_pct": _number(source.get("mae")),
        "giveback_pct": metrics["profit_giveback_pct"],
        "return_per_day": metrics["return_per_day"],
        "opportunity_cost_state": source.get("opportunity_cost_state") or "INSUFFICIENT_COMPARISON_EVIDENCE",
        "replacement_state": (source.get("replacement_analysis") or {}).get("replacement_state") or "INSUFFICIENT_REPLACEMENT_EVIDENCE",
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
    primary_concentration = fallback_concentration_audit(reviews)
    releasable_capital_facts = _releasable_capital_facts(reviews)
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
            "primary_state_concentration": primary_concentration,
            "primary_state_concentration_explained_by": "missing_forward_and_excursion_evidence" if primary_concentration.get("blanket_fallback_detected") else "evidence_supported_or_not_concentrated",
            "status": "REVIEW_REQUIRED" if blanket_detected or primary_concentration.get("blanket_fallback_detected") else "DIFFERENTIATED_OR_EVIDENCE_LIMITED",
        },
        "estimated_releasable_slots": sum(int(row.get("estimated_capacity_released_if_closed") or 0) for row in reviews),
        **releasable_capital_facts,
        "automatic_action_authorized": False,
        "human_review_required": any(bool(row.get("human_review_required")) for row in reviews),
        "no_exit_orders_submitted": True,
        "source": "existing_cached_position_snapshot",
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }
