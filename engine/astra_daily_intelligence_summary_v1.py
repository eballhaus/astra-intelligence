"""Compact read-only daily aggregation of existing Astra canonical outputs."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


VERSION = "1.0.0"
CANONICAL_LANES = ("DAY", "SCALP", "SWING", "CRYPTO")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def bundle1_statuses_with_canonical_truths(
    statuses: dict[str, Any] | None, canonical_truths: list[dict[str, Any]] | None
) -> dict[str, Any]:
    """Give Bundle 1 the same strict truth cohort used by the daily summary."""
    merged = _dict(statuses)
    merged["broker_truth_records_v1"] = _rows(canonical_truths)
    return merged


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    return int(_number(value) or 0)


def _lane(row: dict[str, Any]) -> str:
    lane = _text(row.get("lane_id") or row.get("lane") or row.get("allocation_lane")).upper()
    return lane if lane in CANONICAL_LANES else "OTHER"


def _timestamp(row: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        value = _text(row.get(key))
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _truth_id(row: dict[str, Any]) -> str:
    return _text(row.get("truth_id") or row.get("broker_truth_id") or row.get("lifecycle_id") or row.get("stable_key"))


def _dedupe_truths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        deduped[_truth_id(row) or f"row-{index}"] = row
    return list(deduped.values())


def _return(row: dict[str, Any]) -> float | None:
    for key in ("realized_return_pct", "realized_return", "return_pct", "actual_return_pct"):
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _today(timestamp: datetime | None, report_date: str, zone: ZoneInfo) -> bool:
    return bool(timestamp and timestamp.astimezone(zone).date().isoformat() == report_date)


def _count(values: list[float], predicate) -> int:
    return sum(1 for value in values if predicate(value))


def _truth_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _return(row)) is not None]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    gross_profit, gross_loss = sum(winners), abs(sum(losers))
    return {
        "trades_closed_today": len(rows),
        "winners_today": len(winners),
        "losers_today": len(losers),
        "breakeven_today": _count(returns, lambda value: value == 0),
        "today_realized_return": round(sum(returns), 6) if returns else None,
        "today_win_rate": round(len(winners) * 100.0 / len(returns), 6) if returns else None,
        "today_profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else (round(gross_profit, 6) if gross_profit else None),
        "today_average_return": round(sum(returns) / len(returns), 6) if returns else None,
        "today_median_return": round(median(returns), 6) if returns else None,
    }


def _canonical_profitability_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the supplied canonical strict-truth cohort for reporting."""
    returns = [value for row in rows if (value := _return(row)) is not None]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    gross_profit, gross_loss = sum(winners), abs(sum(losers))
    average_winner = sum(winners) / len(winners) if winners else None
    average_loser = sum(losers) / len(losers) if losers else None
    return {
        "sample_size": len(rows),
        "win_rate": round(len(winners) * 100.0 / len(returns), 6) if returns else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else (round(gross_profit, 6) if gross_profit else None),
        "average_return": round(sum(returns) / len(returns), 6) if returns else None,
        "median_return": round(median(returns), 6) if returns else None,
        "average_winner": round(average_winner, 6) if average_winner is not None else None,
        "average_loser": round(average_loser, 6) if average_loser is not None else None,
        "payoff_ratio": round(average_winner / abs(average_loser), 6) if average_winner is not None and average_loser not in (None, 0) else None,
        "best_trade_return": round(max(returns), 6) if returns else None,
        "worst_trade_return": round(min(returns), 6) if returns else None,
    }


def _average_numeric(rows: list[dict[str, Any]], *keys: str) -> float | None:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _number(row.get(key))
            if value is not None:
                values.append(value)
                break
    return round(sum(values) / len(values), 6) if values else None


def _source_timestamp(source: dict[str, Any]) -> datetime | None:
    return _timestamp(source, "generated_at", "updated_at", "timestamp", "heartbeat_at")


def _learning_context_status(summary: dict[str, Any]) -> str:
    if bool(summary.get("cross_lane_leakage_detected")) or bool(summary.get("regime_leakage_detected")) or _int(summary.get("contradictions_unresolved")):
        return "DEGRADED"
    if _int(summary.get("lessons_evaluated")) == 0:
        return "INSUFFICIENT_EVIDENCE"
    if _int(summary.get("generalization_not_proven")) or _int(summary.get("context_mismatches")):
        return "CAUTION"
    return "HEALTHY"


def _issue_rows(control_plane: dict[str, Any]) -> list[dict[str, Any]]:
    roots = _rows(control_plane.get("active_root_causes") or control_plane.get("root_causes"))
    out = []
    for root in roots:
        severity = _text(root.get("severity")).upper()
        current = _text(root.get("current_vs_historical") or root.get("state") or "CURRENT").upper()
        if severity not in {"HIGH", "CRITICAL"} or current in {"HISTORICAL", "CLOSED", "RESOLVED"}:
            continue
        out.append({
            "severity": severity,
            "symbol_or_component": root.get("symbol") or root.get("component") or root.get("lane"),
            "root_cause": root.get("root_cause_id") or root.get("category"),
            "first_causal_blocker": root.get("first_bad_handoff") or root.get("first_causal_blocker"),
            "legitimate_fail_closed": bool(root.get("legitimate_fail_closed")),
            "software_defect_status": root.get("classification") or root.get("software_defect_status") or "UNCLASSIFIED",
        })
    return out[:12]


def build_astra_daily_intelligence_summary_v1(
    *,
    canonical_truths: list[dict[str, Any]],
    bundle1: dict[str, Any],
    bundle2: dict[str, Any],
    operating_health: dict[str, Any],
    worker_state: dict[str, Any] | None = None,
    control_plane: dict[str, Any] | None = None,
    provider_health: dict[str, Any] | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    open_position_lanes: tuple[str, ...] | list[str] | None = None,
    open_position_scope: str = "EXACT_BROKER_ACTIVE",
    noncanonical_or_legacy_records: list[dict[str, Any]] | None = None,
    secondary_truth_counts: dict[str, Any] | None = None,
    dependency_files_read: int = 0,
    timezone_name: str = "America/New_York",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate only compact canonical outputs; no raw-store or network work."""
    started = time.perf_counter()
    zone = ZoneInfo(timezone_name)
    current = now.astimezone(zone) if now else datetime.now(zone)
    report_date = current.date().isoformat()
    truths = _dedupe_truths(_rows(canonical_truths))
    noncanonical = _rows(noncanonical_or_legacy_records)
    bundle1, bundle2 = _dict(bundle1), _dict(bundle2)
    health, worker = _dict(operating_health), _dict(worker_state)
    control, providers = _dict(control_plane), _dict(provider_health)
    progression = _dict(bundle1.get("truth_progression_v1"))
    overall = _dict(progression.get("overall"))
    linkage = _dict(bundle1.get("canonical_lesson_outcome_linkage_v1"))
    effectiveness = _dict(bundle1.get("lesson_effectiveness_v1"))
    recurrence = _dict(bundle1.get("mistake_recurrence_lesson_linkage_v1"))
    contextual = _dict(bundle1.get("contextual_learning_summary_v1"))
    official_b2 = _dict(bundle2)
    worker_trace = _dict(worker.get("last_execution_trace"))
    decision_capture = _dict(worker_trace.get("candidate_decision_evidence_v1"))
    if not decision_capture:
        decision_capture = _dict(_dict(worker_trace.get("lane_execution_ledger")).get("candidate_decision_evidence_v1"))

    closed_today = [row for row in truths if _today(_timestamp(row, "exit_timestamp", "exit_time", "exit_filled_at", "created_at"), report_date, zone)]
    entered_today = [row for row in truths if _today(_timestamp(row, "entry_timestamp", "entry_time", "entry_filled_at"), report_date, zone)]
    truth_today = [row for row in truths if _today(_timestamp(row, "created_at", "persisted_at", "exit_timestamp", "exit_time"), report_date, zone)]
    today_metrics = _truth_metrics(closed_today)
    canonical_profitability = _canonical_profitability_metrics(truths)
    truths_by_lane = {lane: sum(1 for row in truths if _lane(row) == lane) for lane in (*CANONICAL_LANES, "OTHER")}
    today_truths_by_lane = {lane: sum(1 for row in truth_today if _lane(row) == lane) for lane in (*CANONICAL_LANES, "OTHER")}

    canonical_count = len(truths)
    contracts = []
    comparison_counts = {
        **_dict(secondary_truth_counts),
        "operating_health.strict_truth_total": health.get("strict_truth_total"),
        "bundle1.truth_progression_v1.overall.truth_count": overall.get("truth_count"),
        "bundle2.completed_broker_truth_sample_size": official_b2.get("completed_broker_truth_sample_size"),
    }
    for source, value in comparison_counts.items():
        if _number(value) is None:
            continue
        count = _int(value)
        if count != canonical_count:
            contracts.append({
                "status": "CONTRACT_DISAGREEMENT", "field": "total_canonical_truths",
                "canonical_value": canonical_count, "conflicting_value": count,
                "canonical_owner": "canonical_broker_truth_registry", "conflicting_source": source,
            })

    positions_supplied = open_positions is not None
    positions = _rows(open_positions)
    position_lanes = {
        _text(lane).upper()
        for lane in (open_position_lanes or CANONICAL_LANES)
        if _text(lane).upper() in CANONICAL_LANES
    }
    position_scope = _text(open_position_scope) or "EXACT_BROKER_ACTIVE"
    active_positions = [row for row in positions if bool(row.get("broker_confirmed", True)) and not bool(row.get("advisory_only"))]
    pending_positions = [
        row for row in positions
        if _text(row.get("reconciliation_state")).upper()
        not in {"", "OPEN", "CLOSED", "BROKER_ZERO_CONFIRMED"}
    ]
    active_positions_by_lane = {
        lane: sum(1 for row in active_positions if _lane(row) == lane)
        for lane in CANONICAL_LANES
    }

    lanes_source = _dict(health.get("lanes"))
    lanes = {}
    for lane in CANONICAL_LANES:
        source = _dict(lanes_source.get(lane))
        active = active_positions_by_lane[lane]
        monitor_active = _int(source.get("broker_confirmed_active_positions"))
        lane_positions_supplied = positions_supplied and lane in position_lanes
        scope_difference = position_scope == "CANONICAL_MANAGED_LIFECYCLES"
        if lane_positions_supplied and monitor_active != active and not scope_difference:
            contracts.append({
                "status": "CONTRACT_DISAGREEMENT", "field": f"{lane}.broker_confirmed_active_positions",
                "canonical_value": active, "conflicting_value": monitor_active,
                "canonical_owner": "current_open_broker_positions", "conflicting_source": "operating_health.lanes",
            })
        first_blocker = source.get("first_causal_blocker")
        if active:
            readiness = "ACTIVE"
        elif source.get("waiting_state") == "LEGITIMATE_WAIT":
            readiness = "WAITING_NATURAL_EVIDENCE"
        elif _text(source.get("blocker_validity")).startswith("VALID"):
            readiness = "NORMAL_SCHEDULING_WAIT"
        elif first_blocker:
            readiness = "INSUFFICIENT_EVIDENCE"
        else:
            readiness = "INSUFFICIENT_EVIDENCE"
        lanes[lane] = {
            "status": source.get("waiting_state") or "INSUFFICIENT_EVIDENCE",
            "open_positions": active,
            "lane_monitor_active_count": monitor_active,
            "lane_monitor_position_count_status": (
                "ALIGNED" if lane_positions_supplied and monitor_active == active
                else "DIFFERENT_SCOPE_RAW_BROKER_VS_MANAGED" if lane_positions_supplied and scope_difference
                else "CONTRACT_DISAGREEMENT" if lane_positions_supplied
                else "UNVERIFIED_COMPACT_POSITION_LIST_UNAVAILABLE"
            ),
            "entries_today": sum(1 for row in entered_today if _lane(row) == lane),
            "exits_today": sum(1 for row in closed_today if _lane(row) == lane),
            "truths_today": today_truths_by_lane[lane],
            "total_truths": truths_by_lane[lane],
            "deepest_stage_today": source.get("current_lifecycle_stage") or "UNAVAILABLE",
            "first_causal_blocker": first_blocker,
            "data_state": source.get("candidate_observation_state") or "UNAVAILABLE",
            "execution_state": source.get("waiting_state") or "UNAVAILABLE",
            "truth_readiness": readiness,
        }

    bounded_positions = [{
        "symbol": row.get("symbol"), "lane": _lane(row), "lifecycle_id": row.get("lifecycle_id") or row.get("position_id"),
        "entry_time": row.get("entry_timestamp") or row.get("entry_time"), "entry_price": row.get("entry_price"),
        "current_or_last_trustworthy_return": row.get("current_return_pct") or row.get("realized_return_pct"),
        "hold_duration": row.get("hold_duration") or row.get("hold_duration_minutes"), "momentum_state": row.get("momentum_state"),
        "thesis_state": row.get("thesis_state"), "exit_readiness": row.get("exit_readiness"), "attention_level": row.get("attention_level"),
        "first_blocker": row.get("first_blocker"), "reconciliation_state": row.get("reconciliation_state"),
    } for row in active_positions[:12]]
    issues = _issue_rows(control)
    critical = sum(row["severity"] == "CRITICAL" for row in issues)
    high = sum(row["severity"] == "HIGH" for row in issues)
    system_health = "BROKEN" if critical else "DEGRADED" if high or health.get("control_plane_agreement") is False else "HEALTHY"
    profitability = progression.get("is_astra_improving") or "INSUFFICIENT_EVIDENCE"
    learning_status = bundle1.get("learning_loop_summary_v1", {}).get("is_astra_improving") if isinstance(bundle1.get("learning_loop_summary_v1"), dict) else None
    learning_status = learning_status or "NOT_YET_MEASURABLE"
    truth_status = "HEALTHY" if len(truth_today) else "SLOW" if truths else "BLOCKED"
    dependencies = {"bundle1": bundle1, "bundle2": bundle2, "operating_health": health, "worker": worker, "control_plane": control, "provider_health": providers}
    timestamps = [stamp for source in dependencies.values() if (stamp := _source_timestamp(source))]
    oldest = min(timestamps) if timestamps else None
    freshness = round(max(0.0, (current.astimezone(timezone.utc) - oldest).total_seconds()), 3) if oldest else None
    stale = [name for name, source in dependencies.items() if not _source_timestamp(source)]

    headline = f"{canonical_count} canonical truths; DAY={truths_by_lane['DAY']}; SCALP={truths_by_lane['SCALP']}; CRYPTO={truths_by_lane['CRYPTO']}."
    primary_concern = issues[0].get("root_cause") if issues else "no current high/critical control-plane issue"
    return {
        "endpoint": "/api/astra_daily_intelligence_summary_v1", "version": VERSION,
        "generated_at": _iso(current.astimezone(timezone.utc)), "report_date": report_date, "timezone": timezone_name,
        "status": system_health, "data_freshness": {"oldest_dependency_generated_at": _iso(oldest), "freshness_seconds": freshness, "stale_dependencies": stale},
        "truth_contract_status": "ALIGNED" if not contracts else "CONTRACT_DISAGREEMENT",
        "canonical_truth_total": canonical_count,
        "truths_by_lane": truths_by_lane,
        "noncanonical_or_legacy_records": {"count": len(noncanonical), "symbols": sorted({_text(row.get("symbol")).upper() for row in noncanonical if _text(row.get("symbol"))})[:12], "official_metrics_excluded": True},
        "today_at_a_glance": {"trades_entered_today": len(entered_today), "new_canonical_truths_today": len(_dedupe_truths(truth_today)), "total_canonical_truths": canonical_count, "truths_by_lane": truths_by_lane, "current_open_broker_positions": len(active_positions), "reconciliation_pending_count": len(pending_positions), "learning_pending_count": max(0, canonical_count - _int(health.get("truths_consumed_by_learning_total"))), "today_realized_pnl_dollars": None, **today_metrics},
        "current_canonical_profitability": {
            **canonical_profitability,
            "winsorized_return": None,
            "average_hold_duration": _average_numeric(truths, "hold_duration", "hold_duration_seconds"),
            "MFE": _average_numeric(truths, "mfe", "mfe_pct", "maximum_favorable_excursion_pct"),
            "MAE": _average_numeric(truths, "mae", "mae_pct", "maximum_adverse_excursion_pct"),
            "profit_capture": official_b2.get("average_profit_capture_pct"),
            "giveback": official_b2.get("average_profit_giveback_from_peak_pct"),
            "return_per_hour": official_b2.get("average_return_per_hour"),
            "return_per_day": official_b2.get("average_realized_return_per_day"),
            "entry_quality": None,
            "exit_quality": None,
            "official_truth_source": progression.get("official_truth_source"),
        },
        "bundle1": {"is_astra_improving": progression.get("is_astra_improving"), "progression_status": overall.get("status"), "early_cohort": _dict(overall.get("cohorts")).get("EARLY", {}), "middle_cohort": _dict(overall.get("cohorts")).get("MIDDLE", {}), "recent_cohort": _dict(overall.get("cohorts")).get("RECENT", {}), "lesson_effectiveness": {"lessons_tracked": len(_rows(linkage.get("lessons"))), "lesson_applied_count": linkage.get("explicit_application_events"), "lessons_with_linked_outcomes": linkage.get("linked_outcomes"), "improved_outcomes": effectiveness.get("improved_outcomes"), "worsened_outcomes": effectiveness.get("worsened_outcomes"), "neutral_outcomes": None, "effective_lessons": effectiveness.get("effective_lessons"), "promising_lessons": None, "mixed_lessons": None, "underperforming_lessons": effectiveness.get("underperforming_lessons"), "insufficient_evidence_lessons": None}, "mistake_recurrence": {"recurrence_after_lesson": recurrence.get("recurrence_after_lesson_count"), "recurrence_reduced": None, "recurrence_persistent": None, "not_yet_measurable": not bool(linkage.get("linked_outcomes"))}},
        "bundle2": {"official_truths_eligible_for_attribution": official_b2.get("completed_broker_truth_sample_size"), "official_truths_attributed": official_b2.get("completed_broker_truth_sample_size"), "winners_attributed": official_b2.get("profitable_trade_count"), "losers_attributed": official_b2.get("losing_trade_count"), "top_success_drivers": official_b2.get("top_success_drivers") or [], "top_failure_drivers": official_b2.get("top_failure_drivers") or [], "loss_anatomy": {"controlled": official_b2.get("controlled_loss_count"), "partly_preventable": official_b2.get("partly_preventable_loss_count"), "preventable": official_b2.get("preventable_loss_count"), "not_proven": official_b2.get("losses_not_proven_count")}, "return_per_time": {"average_return_per_hour": official_b2.get("average_return_per_hour"), "median_return_per_hour": official_b2.get("median_return_per_hour"), "average_return_per_day": official_b2.get("average_realized_return_per_day"), "average_hold_duration": None, "overhold_count": None}},
        "bundle3": {**contextual, "learning_context_status": _learning_context_status(contextual)},
        "candidate_evidence_capture": {
            "snapshots_today": decision_capture.get("snapshots_today", decision_capture.get("snapshots_written")),
            "accepted": decision_capture.get("accepted"),
            "rejected": decision_capture.get("rejected"),
            "blocked": decision_capture.get("blocked"),
            "deferred": decision_capture.get("deferred"),
            "later_outcomes_linked": decision_capture.get("later_outcomes_linked"),
            "exact_trade_links": decision_capture.get("exact_trade_links"),
            "unresolved_links": decision_capture.get("unresolved_links"),
            "by_lane": _dict(decision_capture.get("by_lane")),
            "outcome_owner": decision_capture.get("outcome_owner") or "outcome_labels_v1.jsonl",
            "full_history_scan_count": decision_capture.get("full_history_scan_count", 0),
        },
        "lanes": lanes,
        "current_open_positions": {"broker_confirmed_active": bounded_positions, "reconciliation_pending": [{"symbol": row.get("symbol"), "lifecycle_id": row.get("lifecycle_id") or row.get("position_id"), "reconciliation_state": row.get("reconciliation_state")} for row in pending_positions[:12]], "advisory_only": [], "detail_state": "AVAILABLE" if positions else "UNAVAILABLE_FROM_COMPACT_INPUT", "position_scope": position_scope, "position_lanes": sorted(position_lanes)},
        "control_plane": {"sentinel_status": health.get("sentinel_status") or control.get("status"), "governance_status": health.get("governance_status"), "cortex_status": health.get("cortex_status"), "control_plane_agreement": health.get("control_plane_agreement"), "active_root_causes": issues},
        "provider_data_health": {"equities": _dict(providers.get("equities")), "crypto": _dict(providers.get("crypto")), "source_status": providers.get("status") or "UNAVAILABLE_FROM_CACHE"},
        "daily_activity": {"completed_today": [{"symbol": row.get("symbol"), "lane": _lane(row), "entry_time": row.get("entry_timestamp") or row.get("entry_time"), "entry_price": row.get("entry_price"), "exit_time": row.get("exit_timestamp") or row.get("exit_time"), "exit_price": row.get("exit_price"), "status": "CLOSED", "realized_return": _return(row), "exit_reason": row.get("exit_reason"), "broker_confirmed": True, "canonical_truth_completed": True, "learning_acknowledged": row.get("learning_acknowledged")} for row in closed_today[:24]], "opened_today_still_open": [], "prior_day_still_open": [], "filled_awaiting_reconciliation": []},
        "executive_flags": {"system_health": system_health, "profitability_status": profitability, "learning_status": learning_status, "truth_production_status": truth_status, "fast_truth_status": {"SCALP": lanes["SCALP"]["truth_readiness"], "CRYPTO": lanes["CRYPTO"]["truth_readiness"]}, "current_issue_count": len(issues), "critical_issue_count": critical, "high_issue_count": high},
        "plain_english": {"headline": headline, "primary_positive": "canonical broker-truth and learning summaries are aggregated without raw-store rescans", "primary_concern": primary_concern, "next_natural_proof_needed": "next broker-confirmed lifecycle truth with learning acknowledgement"},
        "contract_disagreements": contracts,
        "efficiency": {"dependency_files_read": max(0, int(dependency_files_read)), "records_examined": len(truths), "large_file_full_scans": 0, "provider_calls": 0, "broker_calls": 0, "llm_calls": 0, "generation_ms": round((time.perf_counter() - started) * 1000.0, 3)},
        "paper_only_preserved": True, "reporting_only": True, "execution_authority": "NONE", "trading_behavior_changed": False,
    }
