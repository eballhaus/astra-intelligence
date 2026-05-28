from __future__ import annotations

import json
import math
import os
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 1_500_000
MAX_ROWS = 1600
CACHE_TTL_SECONDS = 8.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
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
        except Exception:
            continue
    return rows


def _stage_for_reason(reason: str, trace: dict[str, Any]) -> str:
    reason_l = _text(reason).lower()
    if bool(trace.get("order_submitted")):
        return "submitted"
    if bool(trace.get("order_attempted")):
        return "broker_preflight"
    if any(x in reason_l for x in ("session", "market_closed", "holiday", "confirmation", "open_confirmation", "timing")):
        return "timing"
    if any(x in reason_l for x in ("correlation", "duplicate_theme", "concentration", "portfolio_fit")):
        return "correlation"
    if any(x in reason_l for x in ("portfolio", "risk")):
        return "portfolio"
    if any(x in reason_l for x in ("capacity", "max_new", "max_concurrent", "duplicate_active_position", "cooldown")):
        return "position"
    if any(x in reason_l for x in ("exploration", "quality_floor", "survivability_floor")):
        return "exploration"
    if any(x in reason_l for x in ("commitment", "eligibility", "confidence", "quality", "entry")):
        return "entry_confirmation"
    return "execution_review"


def _passed_stage(stage: str, reason: str, trace: dict[str, Any]) -> bool:
    if bool(trace.get("order_submitted")) or bool(trace.get("order_attempted")) or bool(trace.get("selected")):
        return True
    return _stage_for_reason(reason, trace) != stage


def _build_record(trace: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    reason = _text(
        trace.get("order_rejection_reason")
        or trace.get("exploration_rejection_reason")
        or trace.get("market_context_rejection_reason")
        or trace.get("broad_universe_rejection_reason")
        or trace.get("decision_reason")
        or context.get("final_blocker_reason"),
        "none",
    )
    stage = _stage_for_reason(reason, trace)
    selected = bool(trace.get("selected", False))
    attempted = bool(trace.get("order_attempted", False))
    submitted = bool(trace.get("order_submitted", False))
    final_decision = "submitted" if submitted else ("attempted_rejected" if attempted else ("selected_not_attempted" if selected else "suppressed"))
    return {
        "enabled": True,
        "version": VERSION,
        "symbol": _text(trace.get("symbol")).upper(),
        "timestamp": _now_iso(),
        "candidate_source": _text(trace.get("paper_autopilot_candidate_source") or context.get("paper_autopilot_candidate_source"), "top_buys"),
        "promoted_status": "promoted" if bool(trace.get("promoted_candidates_available") or trace.get("selected_from_broad_universe")) else "unknown",
        "market_regime": _text(trace.get("market_regime") or trace.get("regime_alignment_label") or context.get("market_session_mode"), "unknown"),
        "session_type": _text(trace.get("market_calendar_session_type") or trace.get("market_session_mode") or context.get("market_session_mode"), "unknown"),
        "allocation_lane": _text(trace.get("allocation_lane"), "unknown"),
        "confidence": round(_to_float(trace.get("confidence"), 0.0), 4),
        "expectancy": round(_to_float(trace.get("expected_value_score") or trace.get("risk_adjusted_profit_score"), 0.0), 4),
        "survivability": round(_to_float(trace.get("survivability_score"), 0.0), 4),
        "diversification_score": round(_to_float(trace.get("portfolio_fit_score"), 0.0), 4),
        "exploration_status": "selected" if bool(trace.get("exploration_selected")) else ("allowed" if bool(trace.get("exploration_allowed")) else "not_selected"),
        "final_execution_decision": final_decision,
        "rejection_stage": stage if final_decision != "submitted" else "none",
        "rejection_reason": reason if final_decision != "submitted" else "none",
        "suppression_reason": reason if final_decision == "suppressed" else "none",
        "broker_submission_attempted": attempted,
        "broker_submission_allowed": bool(trace.get("paper_order_submission_allowed", context.get("paper_order_submission_allowed", False))),
        "passed_market_checks": bool(trace.get("market_is_tradable", trace.get("session_tradable", context.get("paper_order_submission_allowed", False)))) and stage != "timing",
        "passed_portfolio_checks": _passed_stage("portfolio", reason, trace),
        "passed_timing_checks": _passed_stage("timing", reason, trace),
        "passed_exploration_checks": _passed_stage("exploration", reason, trace),
        "passed_position_checks": _passed_stage("position", reason, trace),
        "passed_correlation_checks": _passed_stage("correlation", reason, trace),
        "passed_concentration_checks": not any(x in reason.lower() for x in ("concentration", "overstack")),
        "passed_entry_confirmation": _passed_stage("entry_confirmation", reason, trace),
        "execution_chain_stage_reached": stage if final_decision != "submitted" else "submitted",
        "eligible": bool(trace.get("eligible", False)),
        "selected": selected,
        "order_attempted": attempted,
        "order_submitted": submitted,
        "follow_through_probability": round(_to_float(trace.get("follow_through_probability"), 0.0), 4),
        "breakout_probability_score": round(_to_float(trace.get("breakout_probability_score"), 0.0), 4),
        "context_adjusted_opportunity_score": round(_to_float(trace.get("context_adjusted_opportunity_score"), 0.0), 4),
        "api_calls_used": 0,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "paper_only_preserved": True,
        "natural_exit_preserved": True,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
    }


class ExecutionParticipationAuditV1:
    """Append-only, shadow-only audit for paper execution suppression."""

    def __init__(self, state_dir: str = "state", state_path: str | None = None, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.state_path = str(state_path or os.path.join(self.state_dir, "execution_suppression_audit_v1.jsonl"))
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def record_candidate_traces(self, traces: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = dict(context or {})
        records = [_build_record(dict(t or {}), context) for t in (traces or []) if isinstance(t, dict)]
        if not records:
            return {"ok": True, "records_written": 0}
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
            self._cache = None
            return {"ok": True, "records_written": len(records)}
        except Exception as exc:
            return {"ok": False, "records_written": 0, "error": str(exc)[:120]}

    def _status_from_rows(self, rows: list[dict[str, Any]], paper_trace: dict[str, Any] | None = None) -> dict[str, Any]:
        paper_trace = dict(paper_trace or {})
        recent = rows[-MAX_ROWS:]
        stage_counts = Counter(_text(r.get("rejection_stage"), "none") for r in recent if _text(r.get("rejection_stage"), "none") != "none")
        reason_counts = Counter(_text(r.get("rejection_reason"), "none") for r in recent if _text(r.get("rejection_reason"), "none") != "none")
        reviewed = len(recent)
        eligible = sum(1 for r in recent if bool(r.get("eligible")))
        submitted = sum(1 for r in recent if bool(r.get("order_submitted")))
        attempted = sum(1 for r in recent if bool(r.get("order_attempted")))
        filled = sum(1 for r in recent if _text(r.get("order_result")).lower() == "filled")
        promoted = sum(1 for r in recent if _text(r.get("promoted_status")) == "promoted")
        high_expectancy_rejected = [
            r for r in recent
            if not bool(r.get("order_submitted"))
            and (_to_float(r.get("expectancy"), 0.0) >= 70.0 or _to_float(r.get("context_adjusted_opportunity_score"), 0.0) >= 70.0)
        ]
        missed_breakout = sum(1 for r in high_expectancy_rejected if _to_float(r.get("breakout_probability_score"), 0.0) >= 65.0)
        missed_continuation = sum(1 for r in high_expectancy_rejected if _to_float(r.get("follow_through_probability"), 0.0) >= 60.0)
        conversion = (submitted / reviewed * 100.0) if reviewed else 0.0
        eligible_to_submitted = (submitted / eligible * 100.0) if eligible else 0.0
        submitted_to_filled = (filled / submitted * 100.0) if submitted else 0.0
        suppression = 100.0 - conversion if reviewed else 0.0
        broker_allowed = bool(paper_trace.get("paper_order_submission_allowed", False))
        broker_ready = bool(paper_trace.get("broker_execution_enabled") or paper_trace.get("paper_mode_verified"))
        session_blocked = bool(reviewed > 0 and not broker_allowed and stage_counts.get("timing", 0) >= max(1, reviewed * 0.7))
        opportunity_pressure = min(100.0, len(high_expectancy_rejected) * 6.0 + max(0.0, eligible - submitted) * 8.0)
        overprotection = min(100.0, opportunity_pressure + (25.0 if broker_allowed and broker_ready and eligible > submitted else 0.0))
        underparticipation = min(100.0, max(0.0, 60.0 - eligible_to_submitted) + (20.0 if reviewed >= 10 and submitted == 0 else 0.0))
        if session_blocked:
            overprotection = 0.0
            underparticipation = 0.0
            opportunity_pressure = 0.0
        efficiency = max(0.0, min(100.0, (eligible_to_submitted * 0.45) + (conversion * 0.35) + (100.0 - min(100.0, opportunity_pressure)) * 0.20))
        label = "insufficient_evidence"
        if reviewed >= 5:
            if session_blocked:
                label = "session_blocked_observation_only"
            elif overprotection >= 65.0 or underparticipation >= 65.0:
                label = "overprotective_underparticipating"
            elif efficiency >= 55.0:
                label = "balanced_participation"
            else:
                label = "underparticipating"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_audit",
            "execution_participation_audit_status_v1": True,
            "participation_label": label,
            "candidates_seen": _to_int(paper_trace.get("candidates_seen"), reviewed),
            "candidates_promoted": _to_int((paper_trace.get("broad_universe_intake_promotion") or {}).get("promoted_to_top_buys_count"), promoted),
            "candidates_deep_scored": _to_int((paper_trace.get("broad_universe_intake_promotion") or {}).get("deep_scored_count"), promoted),
            "candidates_execution_reviewed": reviewed,
            "candidates_portfolio_rejected": int(stage_counts.get("portfolio", 0)),
            "candidates_timing_rejected": int(stage_counts.get("timing", 0)),
            "candidates_correlation_rejected": int(stage_counts.get("correlation", 0)),
            "candidates_confirmation_rejected": int(stage_counts.get("entry_confirmation", 0)),
            "candidates_exploration_rejected": int(stage_counts.get("exploration", 0)),
            "candidates_position_limit_rejected": int(stage_counts.get("position", 0)),
            "candidates_submitted": _to_int(paper_trace.get("orders_submitted"), submitted),
            "candidates_filled": int(filled),
            "eligible_candidates": _to_int(paper_trace.get("eligible_candidates"), eligible),
            "orders_attempted": _to_int(paper_trace.get("orders_attempted"), attempted),
            "orders_rejected": _to_int(paper_trace.get("orders_rejected"), max(0, attempted - submitted)),
            "participation_efficiency_score": round(efficiency, 2),
            "participation_suppression_score": round(suppression, 2),
            "missed_opportunity_pressure": round(opportunity_pressure, 2),
            "overprotection_risk": round(overprotection, 2),
            "underparticipation_risk": round(underparticipation, 2),
            "execution_conversion_rate": round(conversion, 2),
            "eligible_to_submitted_rate": round(eligible_to_submitted, 2),
            "submitted_to_filled_rate": round(submitted_to_filled, 2),
            "market_opportunity_capture_rate": round(eligible_to_submitted, 2),
            "missed_follow_through_pct": round(mean([_to_float(r.get("follow_through_probability"), 0.0) for r in high_expectancy_rejected]), 2) if high_expectancy_rejected else 0.0,
            "missed_profit_capture_pct": round(mean([_to_float(r.get("expectancy"), 0.0) for r in high_expectancy_rejected]), 2) if high_expectancy_rejected else 0.0,
            "missed_breakout_count": int(missed_breakout),
            "missed_continuation_count": int(missed_continuation),
            "missed_high_expectancy_candidates": int(len(high_expectancy_rejected)),
            "top_rejection_reasons": dict(reason_counts.most_common(8)),
            "rejection_stage_counts": dict(stage_counts),
            "final_blocker_reason": _text(paper_trace.get("final_blocker_reason"), "none"),
            "summary": f"Reviewed {reviewed} execution decisions; submitted {submitted}; top suppression reason {reason_counts.most_common(1)[0][0] if reason_counts else 'none'}.",
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def status(self, paper_trace: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        paper_trace = dict(paper_trace or {})
        rows = _tail_jsonl(self.state_path)
        if not rows:
            trace_rows = [
                _build_record(dict(t or {}), paper_trace)
                for t in list(paper_trace.get("per_candidate_decision_trace") or [])
                if isinstance(t, dict)
            ]
            rows = trace_rows
        out = self._status_from_rows(rows, paper_trace=paper_trace)
        out["cache_hit"] = False
        out["cache_age_seconds"] = 0.0
        out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(out)
        self._cache_ts = now
        return out
