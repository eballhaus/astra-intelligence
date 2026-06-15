from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    evidence_count_from,
    first,
    now_iso,
    rounded,
    safe_average,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

MAX_POSITION_ROWS = 30
SCALP_OVERDUE_HOURS = 1.5
DAY_OVERDUE_HOURS = 10.0
SWING_OVERDUE_HOURS = 120.0
UNKNOWN_REVIEW_HOURS = 24.0


def _parse_dt(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _hours_since(value: Any, now: datetime) -> float | None:
    parsed = _parse_dt(value)
    if not parsed:
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600.0)


def _pct(value: Any, default: float = 0.0) -> float:
    out = to_float(value, default)
    if -1.25 <= out <= 1.25 and out != 0:
        out *= 100.0
    return out


def _symbol(row: dict[str, Any]) -> str:
    return text(first(row.get("symbol"), row.get("ticker"), row.get("asset"), default="UNKNOWN"), "UNKNOWN").upper()


def _normalize_horizon(value: Any) -> str:
    raw = text(value, "unknown").lower().replace("-", "_").replace(" ", "_")
    if raw in {"scalp", "scalping", "15m", "30m", "45m", "60m", "intraday_scalp"}:
        return "scalp"
    if raw in {"day", "daytrade", "day_trade", "intraday", "2h", "4h", "eod", "same_day"}:
        return "day_trade"
    if raw in {"swing", "swing_trade", "1d", "2d", "3d", "5d", "10d", "multi_day", "overnight"}:
        return "swing_trade"
    return "unknown"


def _overdue_limit(horizon: str) -> float:
    if horizon == "scalp":
        return SCALP_OVERDUE_HOURS
    if horizon == "day_trade":
        return DAY_OVERDUE_HOURS
    if horizon == "swing_trade":
        return SWING_OVERDUE_HOURS
    return UNKNOWN_REVIEW_HOURS


def _list_payloads(payload: dict[str, Any], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _list_payloads(value, keys)
            if nested:
                return nested
    return []


class TradeLifecycleAuditTruthHorizonIntegritySuiteV1(CachedDiagnosticModule):
    """Advisory paper-position lifecycle audit.

    This suite reads cached diagnostics only. It explains active paper holds,
    compares current hold decisions to shadow lifecycle evidence, and flags
    whether a future horizon-integrity review layer is needed. It never writes
    to broker, paper execution, ranking, entry, exit, sizing, or allocation state.
    """

    module_name = "trade_lifecycle_audit_truth_horizon_integrity_suite_v1"
    mode = "paper_only_lifecycle_truth_validation_advisory"

    def _active_positions(self, statuses: dict[str, Any]) -> tuple[list[dict[str, Any]], str, int, int]:
        mobile = status_value(statuses, "mobile_runtime_compaction")
        broker = status_value(statuses, "alpaca_paper_broker")
        paper_status = status_value(statuses, "alpaca_paper_status_v1")
        autopilot = status_value(statuses, "paper_autopilot")
        throughput = status_value(statuses, "paper_throughput_exit_validation_catalyst_intelligence_v1")

        source_candidates = [
            ("mobile_runtime_compaction.desktop_positions_preview", mobile, ("desktop_positions_preview", "true_broker_positions_preview", "positions", "open_positions", "active_positions")),
            ("alpaca_paper_broker.positions", broker, ("positions", "open_positions", "active_positions", "broker_positions")),
            ("alpaca_paper_status_v1.positions", paper_status, ("positions", "open_positions", "active_positions")),
            ("paper_autopilot.positions", autopilot, ("positions", "open_positions", "active_positions", "open_rows")),
        ]
        rows: list[dict[str, Any]] = []
        source = "none"
        for name, payload, keys in source_candidates:
            rows = _list_payloads(payload, keys)
            if rows:
                source = name
                break

        broker_count = max(
            to_int(mobile.get("true_broker_active_positions"), 0),
            to_int(throughput.get("broker_confirmed_positions"), 0),
            to_int(broker.get("broker_open_positions_count"), 0),
            to_int(broker.get("open_positions_count"), 0),
            to_int(paper_status.get("open_positions_count"), 0),
        )
        stale_rows = max(
            to_int(mobile.get("stale_internal_positions"), 0),
            to_int(throughput.get("stale_internal_rows"), 0),
            to_int(throughput.get("stale_internal_position_rows"), 0),
        )
        return rows[:MAX_POSITION_ROWS], source, broker_count, stale_rows

    def _row_context(self, statuses: dict[str, Any]) -> dict[str, Any]:
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        peak = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = status_value(statuses, "catalyst_persistence_decay_curves_v2")
        sector = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        regime = status_value(statuses, "market_condition_attribution_v1")
        market = status_value(statuses, "market_breadth_index_intelligence_v1")
        learned_exit = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        optimizer = status_value(statuses, "profit_optimization_context_intelligence_suite_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_excursion_v2")
        return {
            "base_continuation": clamp(first(peak.get("continuation_probability"), profit.get("continuation_failure_probability"), default=50.0)),
            "base_catalyst_decay": clamp(first(decay.get("catalyst_decay_risk"), decay.get("catalyst_decay_readiness"), profit.get("catalyst_decay_risk"), default=45.0)),
            "base_sector_support": clamp(first(sector.get("sector_support_for_current_positions"), sector.get("sector_rotation_confidence"), market.get("market_support_for_equity_trades"), default=50.0)),
            "base_regime_support": clamp(first(regime.get("condition_confidence_score"), market.get("market_support_for_momentum_trades"), default=50.0)),
            "base_giveback_risk": clamp(first(profit.get("giveback_risk_score"), peak.get("giveback_risk_score"), default=45.0)),
            "base_profit_capture": clamp(first(profit.get("profit_capture_score"), peak.get("capture_quality_score"), lifecycle.get("profit_capture_score"), default=50.0)),
            "best_exit_candidate": text(first(optimizer.get("best_exit_candidate"), learned_exit.get("best_learned_exit_policy"), peak.get("best_exit_policy"), default="natural_exit")),
            "learned_exit_enabled": bool(learned_exit.get("learned_exit_bucket_enabled", False)),
        }

    def _position_row(self, row: dict[str, Any], ctx: dict[str, Any], now: datetime) -> dict[str, Any]:
        symbol = _symbol(row)
        opened = first(row.get("opened_at"), row.get("entry_timestamp"), row.get("entry_timestamp_utc"), row.get("created_at"), row.get("timestamp"), default="")
        hold_hours = _hours_since(opened, now)
        raw_horizon = first(row.get("original_horizon"), row.get("horizon"), row.get("trade_horizon"), row.get("horizon_label"), row.get("source_bucket"), default="unknown")
        horizon = _normalize_horizon(raw_horizon)
        overdue_limit = _overdue_limit(horizon)
        elapsed = hold_hours if hold_hours is not None else 0.0
        overdue = bool(hold_hours is not None and elapsed > overdue_limit)
        pnl_pct = _pct(first(row.get("pnl_percent"), row.get("unrealized_pnl_percent"), row.get("return_percent"), row.get("unrealized_plpc"), row.get("change_pct"), default=0.0))
        pnl_dollars = to_float(first(row.get("pnl"), row.get("unrealized_pnl"), row.get("unrealized_pl"), row.get("market_value_change"), default=0.0), 0.0)
        confidence = clamp(first(row.get("confidence"), row.get("buy_quality_score"), row.get("score"), default=55.0))

        continuation = clamp(ctx["base_continuation"] + confidence * 0.10 + max(-12.0, min(12.0, pnl_pct * 0.8)) - (18.0 if overdue else 0.0))
        catalyst_decay = clamp(ctx["base_catalyst_decay"] + (12.0 if overdue else 0.0) + max(0.0, -pnl_pct * 0.6))
        catalyst_status = "decaying" if catalyst_decay >= 65 else "supported" if catalyst_decay <= 40 else "mixed"
        sector_support = clamp(ctx["base_sector_support"] + (confidence - 50.0) * 0.08)
        regime_support = clamp(ctx["base_regime_support"] - (8.0 if overdue else 0.0))
        giveback_risk = clamp(ctx["base_giveback_risk"] + max(0.0, pnl_pct) * 1.1 + (12.0 if overdue else 0.0))
        profit_capture = clamp(ctx["base_profit_capture"] - max(0.0, giveback_risk - 60.0) * 0.35)
        sell_confidence = clamp((100.0 - continuation) * 0.34 + catalyst_decay * 0.24 + giveback_risk * 0.24 + (100.0 - regime_support) * 0.18)
        exit_readiness = clamp(sell_confidence * 0.55 + giveback_risk * 0.25 + catalyst_decay * 0.20)

        if sell_confidence >= 70 and giveback_risk >= 65:
            exit_blocker = "awaiting_profit_protection_or_natural_exit_confirmation"
            ideal_action = "profit_protect_review"
        elif sell_confidence >= 68:
            exit_blocker = "sell_review_ready_but_no_forced_exit_allowed"
            ideal_action = "sell_review"
        elif horizon == "unknown":
            exit_blocker = "unknown_original_horizon_requires_review"
            ideal_action = "convert_horizon_review"
        elif overdue and horizon == "scalp":
            exit_blocker = "scalp_hold_overdue_requires_day_trade_review"
            ideal_action = "convert_to_day_trade_review"
        elif overdue and horizon == "day_trade":
            exit_blocker = "day_trade_hold_overdue_requires_swing_review"
            ideal_action = "convert_to_swing_review"
        elif continuation >= 58 and sector_support >= 45 and regime_support >= 45:
            exit_blocker = "continuation_and_context_still_support_hold"
            ideal_action = "hold"
        else:
            exit_blocker = "natural_exit_rules_not_satisfied"
            ideal_action = "hold_review"

        correctly_holding = bool(ideal_action == "hold" and sell_confidence < 62)
        should_have_sold = bool(ideal_action == "sell_review")
        should_have_converted = bool(ideal_action.startswith("convert_"))
        should_have_profit_protected = bool(ideal_action == "profit_protect_review")
        would_repurchase = bool(confidence >= 70 and continuation >= 55 and sell_confidence < 55)
        replay_same = bool(would_repurchase and not should_have_sold and not should_have_profit_protected)

        why = self._why_holding(
            horizon=horizon,
            overdue=overdue,
            continuation=continuation,
            catalyst_status=catalyst_status,
            sector_support=sector_support,
            regime_support=regime_support,
            sell_confidence=sell_confidence,
            giveback_risk=giveback_risk,
            exit_blocker=exit_blocker,
        )
        truth_explanation = self._truth_explanation(ideal_action, correctly_holding, sell_confidence, giveback_risk, horizon, overdue)
        return {
            "symbol": symbol,
            "opened_at": text(opened, "unknown"),
            "original_horizon": text(raw_horizon, "unknown"),
            "normalized_horizon": horizon,
            "elapsed_hold_hours": rounded(elapsed, 2) if hold_hours is not None else None,
            "elapsed_hold_days": rounded(elapsed / 24.0, 2) if hold_hours is not None else None,
            "pnl_percent": rounded(pnl_pct, 3),
            "pnl_dollars": rounded(pnl_dollars, 2),
            "continuation_probability": rounded(continuation, 3),
            "catalyst_status": catalyst_status,
            "catalyst_decay_risk": rounded(catalyst_decay, 3),
            "sector_support": rounded(sector_support, 3),
            "regime_support": rounded(regime_support, 3),
            "sell_confidence": rounded(sell_confidence, 3),
            "exit_readiness": rounded(exit_readiness, 3),
            "giveback_risk": rounded(giveback_risk, 3),
            "profit_capture_score": rounded(profit_capture, 3),
            "exit_blocker": exit_blocker,
            "why_still_holding": why,
            "actual_decision": "hold",
            "ideal_action": ideal_action,
            "correctly_holding": correctly_holding,
            "should_have_sold": should_have_sold,
            "should_have_converted_horizon": should_have_converted,
            "should_have_profit_protected": should_have_profit_protected,
            "would_repurchase_today": would_repurchase,
            "same_decision_if_replayed_today": replay_same,
            "truth_confidence": rounded(clamp(abs(sell_confidence - 50.0) * 1.4 + min(35.0, elapsed / 8.0) + confidence * 0.15), 3),
            "truth_explanation": truth_explanation,
        }

    @staticmethod
    def _why_holding(**kwargs: Any) -> str:
        if kwargs["exit_blocker"] == "continuation_and_context_still_support_hold":
            return "Astra is still holding because continuation, sector support, and regime support remain acceptable while sell confidence is not high enough for a natural exit review."
        if kwargs["horizon"] == "unknown":
            return "Astra can see the paper position, but the original horizon is unknown, so this hold needs a horizon review rather than an automatic sell."
        if kwargs["sell_confidence"] >= 68:
            return "Sell-review evidence is elevated, but this diagnostic is advisory only and does not force paper exits."
        if kwargs["giveback_risk"] >= 70:
            return "The position is still open because natural exit rules have not fired, but giveback risk is high enough to require profit-protection review."
        if kwargs["overdue"]:
            return "The position has exceeded its expected horizon window, so Astra should review whether the thesis converted rather than assuming the original horizon still applies."
        return "The position is still holding because no cached lifecycle signal shows enough sell confidence to override the current natural-exit guardrails."

    @staticmethod
    def _truth_explanation(action: str, correct: bool, sell_confidence: float, giveback_risk: float, horizon: str, overdue: bool) -> str:
        if correct:
            return "Current hold appears consistent with cached continuation and context evidence."
        if action == "profit_protect_review":
            return "Profit-protection review is favored because sell confidence and giveback risk are both elevated."
        if action == "sell_review":
            return "Sell review is favored by the truth audit, but no autonomous sell behavior is enabled."
        if action.startswith("convert_"):
            return f"The {horizon} horizon appears overdue, so the safest diagnostic action is horizon-conversion review before any sell decision."
        if overdue:
            return "Hold is not automatically wrong, but elapsed time is beyond the expected window and requires review."
        return "Current evidence is mixed; keep natural exits preserved and collect more lifecycle evidence."

    def _summary(self, rows: list[dict[str, Any]], broker_count: int, stale_rows: int, source: str) -> dict[str, Any]:
        count = max(len(rows), broker_count)
        holds = [to_float(row.get("elapsed_hold_hours"), 0.0) for row in rows if row.get("elapsed_hold_hours") is not None]
        overdue = [row for row in rows if row.get("should_have_converted_horizon") or row.get("should_have_sold") or row.get("should_have_profit_protected")]
        blocker_counts: dict[str, int] = {}
        horizon_counts: dict[str, int] = {}
        for row in rows:
            blocker_counts[text(row.get("exit_blocker"), "unknown")] = blocker_counts.get(text(row.get("exit_blocker"), "unknown"), 0) + 1
            horizon_counts[text(row.get("normalized_horizon"), "unknown")] = horizon_counts.get(text(row.get("normalized_horizon"), "unknown"), 0) + 1
        biggest_blocker = max(blocker_counts.items(), key=lambda item: item[1])[0] if blocker_counts else "insufficient_position_detail"
        dominant_horizon = max(horizon_counts.items(), key=lambda item: item[1])[0] if horizon_counts else "unknown"
        most_overdue = max(rows, key=lambda r: to_float(r.get("elapsed_hold_hours"), 0.0) - _overdue_limit(text(r.get("normalized_horizon"), "unknown")), default={})
        most_profitable = max(rows, key=lambda r: to_float(r.get("pnl_percent"), -999.0), default={})
        highest_giveback = max(rows, key=lambda r: to_float(r.get("giveback_risk"), 0.0), default={})
        oldest = max(rows, key=lambda r: to_float(r.get("elapsed_hold_hours"), 0.0), default={})
        overdue_pct = round((len(overdue) / max(1, len(rows))) * 100.0, 3) if rows else 0.0
        repurchase_pct = round((len([r for r in rows if r.get("would_repurchase_today")]) / max(1, len(rows))) * 100.0, 3) if rows else 0.0
        replay_same_count = len([r for r in rows if r.get("same_decision_if_replayed_today")])
        unknown_pct = round((horizon_counts.get("unknown", 0) / max(1, len(rows))) * 100.0, 3) if rows else 0.0
        non_swing_overdue = len([r for r in rows if r.get("normalized_horizon") in {"scalp", "day_trade"} and (r.get("should_have_converted_horizon") or False)])
        horizon_integrity_needed = bool(rows and (unknown_pct >= 25.0 or overdue_pct >= 35.0 or non_swing_overdue >= 2))
        return {
            "active_position_source": source,
            "total_active_positions": int(count),
            "position_rows_audited": int(len(rows)),
            "broker_confirmed_positions": int(broker_count),
            "stale_internal_rows": int(stale_rows),
            "average_hold_hours": rounded(safe_average(holds), 3),
            "average_hold_days": rounded(safe_average(holds) / 24.0, 3) if holds else 0.0,
            "oldest_position": text(oldest.get("symbol"), "insufficient_data"),
            "oldest_position_hold_hours": rounded(oldest.get("elapsed_hold_hours"), 3),
            "most_overdue_position": text(most_overdue.get("symbol"), "insufficient_data"),
            "most_profitable_position": text(most_profitable.get("symbol"), "insufficient_data"),
            "most_profitable_position_pct": rounded(most_profitable.get("pnl_percent"), 3),
            "highest_giveback_risk_position": text(highest_giveback.get("symbol"), "insufficient_data"),
            "highest_giveback_risk": rounded(highest_giveback.get("giveback_risk"), 3),
            "biggest_exit_blocker": biggest_blocker,
            "dominant_hold_reason": biggest_blocker,
            "dominant_active_horizon": dominant_horizon,
            "horizon_distribution": horizon_counts,
            "active_overdue_pct": overdue_pct,
            "would_repurchase_today_pct": repurchase_pct,
            "same_decision_if_replayed_today_count": int(replay_same_count),
            "horizon_integrity_needed": horizon_integrity_needed,
            "horizon_integrity_reason": "unknown_or_overdue_horizon_pressure" if horizon_integrity_needed else "current_horizon_integrity_sufficient_for_advisory_mode",
        }

    def _answers(self, rows: list[dict[str, Any]], summary: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        pf = to_float(status_value(statuses, "shadow_vs_paper_performance_attribution_v1").get("paper_profit_factor_verified"), 2.60)
        horizon_counts = dict(summary.get("horizon_distribution") or {})
        total = max(1, sum(to_int(v, 0) for v in horizon_counts.values()))
        contribution = {
            "scalp_pct": rounded(horizon_counts.get("scalp", 0) * 100.0 / total, 3),
            "day_trade_pct": rounded(horizon_counts.get("day_trade", 0) * 100.0 / total, 3),
            "swing_trade_pct": rounded((horizon_counts.get("swing_trade", 0) + horizon_counts.get("unknown", 0)) * 100.0 / total, 3),
            "basis": f"active_position_horizon_mix_against_pf_{rounded(pf, 3)}",
        }
        overdue_pct = to_float(summary.get("active_overdue_pct"), 0.0)
        avg_hold = to_float(summary.get("average_hold_hours"), 0.0)
        too_long = overdue_pct >= 35.0 or avg_hold > 72.0
        drifting = bool(summary.get("horizon_integrity_needed"))
        profit = status_value(statuses, "controlled_paper_profit_protection_pilot_v1")
        peak = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        return {
            "is_astra_holding_everything_too_long": "yes_review_required" if too_long else "not_proven_from_cached_evidence",
            "intentionally_holding_or_drifting": "drifting_or_horizon_intent_unclear" if drifting else "mostly_intentional_or_natural_exit_guardrail_driven",
            "unintentionally_swing_system": bool((summary.get("dominant_active_horizon") in {"swing_trade", "unknown"}) and avg_hold >= 24.0),
            "pf_contribution_by_horizon_pct": contribution,
            "biggest_contributor_to_weak_exit_quality": "delayed_profit_protection_and_natural_exit_confirmation" if rows else "insufficient_position_detail",
            "biggest_contributor_to_weak_profit_capture": text(first(profit.get("strongest_profit_protection_pattern"), peak.get("strongest_failure_signal"), default="profit_giveback_after_peak")),
            "biggest_contributor_to_giveback": text(summary.get("highest_giveback_risk_position"), "insufficient_position_detail"),
            "percent_active_overdue": rounded(overdue_pct, 3),
            "percent_astra_would_repurchase_today": rounded(summary.get("would_repurchase_today_pct"), 3),
            "same_decisions_if_replayed_today": to_int(summary.get("same_decision_if_replayed_today_count"), 0),
            "horizon_integrity_needed": bool(summary.get("horizon_integrity_needed")),
            "would_horizon_integrity_improve_or_hurt_pf_2_60": "likely_improve_pf_if_kept_advisory_and_review_only" if summary.get("horizon_integrity_needed") else "neutral_until_more_overdue_or_unknown_horizon_evidence",
            "single_highest_roi_fix": "add_review_only_horizon_integrity_and_profit_protection_visibility" if summary.get("horizon_integrity_needed") else "continue_profit_capture_truth_audit_before_any_behavior_change",
            "safest_next_implementation": "review_to_convert_to_sell_diagnostics_only_no_forced_sells",
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        now = datetime.now(timezone.utc)
        raw_positions, source, broker_count, stale_rows = self._active_positions(statuses)
        ctx = self._row_context(statuses)
        rows = [self._position_row(row, ctx, now) for row in raw_positions]
        summary = self._summary(rows, broker_count, stale_rows, source)
        answers = self._answers(rows, summary, statuses)
        horizon_rows = []
        if summary.get("horizon_integrity_needed"):
            for row in rows:
                if row.get("should_have_converted_horizon") or row.get("normalized_horizon") == "unknown":
                    next_step = "review"
                    if row.get("normalized_horizon") == "scalp":
                        next_step = "review_for_day_trade_conversion"
                    elif row.get("normalized_horizon") == "day_trade":
                        next_step = "review_for_swing_trade_conversion"
                    elif row.get("normalized_horizon") == "swing_trade":
                        next_step = "review_for_sell_or_profit_protection"
                    horizon_rows.append({
                        "symbol": row.get("symbol"),
                        "current_horizon": row.get("normalized_horizon"),
                        "elapsed_hold_hours": row.get("elapsed_hold_hours"),
                        "allowed_flow": "review_to_convert_to_sell_only",
                        "next_review_step": next_step,
                        "sell_forced": False,
                    })
        status = "ok" if rows or broker_count else "insufficient_evidence"
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Trade Lifecycle Audit, Truth Validation & Conditional Horizon Integrity Suite V1",
            "status": status,
            "mode": self.mode,
            "generated_at": now_iso(),
            "evidence_count": evidence_count_from(statuses),
            "trade_lifecycle_audit_suite_v1": summary,
            "trade_lifecycle_truth_audit_v1": {
                "truth_rows": rows[:MAX_POSITION_ROWS],
                "correctly_holding_count": len([r for r in rows if r.get("correctly_holding")]),
                "should_have_sold_count": len([r for r in rows if r.get("should_have_sold")]),
                "should_have_converted_horizon_count": len([r for r in rows if r.get("should_have_converted_horizon")]),
                "should_have_profit_protected_count": len([r for r in rows if r.get("should_have_profit_protected")]),
                "average_truth_confidence": rounded(safe_average([r.get("truth_confidence") for r in rows]), 3),
            },
            "horizon_integrity_conversion_intelligence_v1": {
                "enabled": bool(summary.get("horizon_integrity_needed")),
                "status": "needed" if summary.get("horizon_integrity_needed") else "not_needed",
                "review_convert_sell_only": True,
                "never_force_sells": True,
                "scalp_to_swing_direct_conversion_allowed": False,
                "conversion_rows": horizon_rows[:MAX_POSITION_ROWS],
                "reason": text(summary.get("horizon_integrity_reason")),
            },
            "position_audit_rows": rows[:MAX_POSITION_ROWS],
            "truth_validation_rows": rows[:MAX_POSITION_ROWS],
            "final_report_answers": answers,
            "total_active_positions": summary.get("total_active_positions"),
            "average_hold_duration_hours": summary.get("average_hold_hours"),
            "oldest_position": summary.get("oldest_position"),
            "most_overdue_position": summary.get("most_overdue_position"),
            "most_profitable_position": summary.get("most_profitable_position"),
            "highest_giveback_risk_position": summary.get("highest_giveback_risk_position"),
            "biggest_exit_blocker": summary.get("biggest_exit_blocker"),
            "dominant_hold_reason": summary.get("dominant_hold_reason"),
            "horizon_integrity_needed": bool(summary.get("horizon_integrity_needed")),
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "shadow_only": True,
            "advisory_only": True,
            "diagnostics_only": True,
            "auto_apply": False,
            "auto_apply_allowed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "sell_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "thresholds_changed": False,
            "paper_execution_changed": False,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "behavior_safe_to_apply": False,
        }
        return with_safety(out)
