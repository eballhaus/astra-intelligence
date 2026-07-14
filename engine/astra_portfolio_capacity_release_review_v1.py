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


def classify_position(row: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(row or {})
    symbol = _text(source.get("symbol") or source.get("ticker")).upper()
    entry = _number(source.get("avg_entry_price") or source.get("entry_price"))
    current = _number(source.get("current_price") or source.get("market_price"))
    age = _age_days(source)
    missing = [key for key, value in (("symbol", symbol), ("entry_price", entry), ("current_price", current)) if value in (None, "") or value == ""]
    metrics = {
        "position_age_days": round(age, 4) if age is not None else None,
        "unrealized_return_pct": _number(source.get("unrealized_return_pct") or source.get("unrealized_plpc")),
        "unrealized_pnl": _number(source.get("unrealized_pnl") or source.get("unrealized_pl")),
        "return_per_day": _number(source.get("return_per_day")),
        "profit_giveback_pct": _number(source.get("profit_giveback_pct")),
        "opportunity_cost_score": _number(source.get("opportunity_cost_score")),
        "replacement_score": _number(source.get("replacement_score")),
    }
    reasons: list[str] = []
    contradictions: list[str] = []
    state = "DATA_INSUFFICIENT"
    confidence = "low"
    if not missing:
        thesis = _text(source.get("thesis_state") or source.get("thesis_status")).lower()
        horizon_expired = bool(source.get("horizon_expired")) or _number(source.get("days_beyond_horizon")) is not None and _number(source.get("days_beyond_horizon")) > 0
        duplicate = bool(source.get("duplicate_exposure") or source.get("duplicate_exposure_state") in {"DUPLICATE", "DUPLICATE_EXPOSURE"})
        replacement_fresh = bool(source.get("replacement_fresh") or source.get("replacement_candidate_id"))
        opportunity = metrics["opportunity_cost_score"] or 0.0
        giveback = metrics["profit_giveback_pct"] or 0.0
        ret = metrics["unrealized_return_pct"]
        if "broken" in thesis or thesis in {"damaged", "invalidated"}:
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
            state, confidence = "CONTROLLED_LOSS_ACCEPTABLE", "low"
            reasons.append("LOSS_STABILIZING" if source.get("loss_stabilization_state") else "INSUFFICIENT_DATA")
            contradictions.append("RECOVERY_MOMENTUM_PRESENT" if source.get("recent_recovery") else "NO_RECOVERY_EVIDENCE")
        elif source.get("momentum_deterioration"):
            state, confidence = "WATCH", "medium"
            reasons.append("MOMENTUM_DETERIORATION")
        else:
            state, confidence = "KEEP", "medium"
            reasons.append("NORMAL_VOLATILITY")
    else:
        reasons.append("INSUFFICIENT_DATA")
    return {
        "position_id": _text(source.get("position_id")),
        "symbol": symbol,
        "lane_id": _text(source.get("lane_id") or source.get("position_owner")).upper() or "SWING",
        "state": state,
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
        "automatic_action_authorized": False,
    }

def build_portfolio_release_review(rows: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    reviews = [classify_position(row) for row in (rows or []) if isinstance(row, Mapping)]
    counts = {state: sum(1 for row in reviews if row.get("state") == state) for state in STATES}
    return {
        "portfolio_capacity_release_review_v1": True,
        "total_positions": len(reviews),
        "positions_by_state": counts,
        "review_rows": reviews,
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
