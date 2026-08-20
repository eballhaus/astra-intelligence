"""Evidence-consumption, lesson quality, and learning-velocity diagnostics.

The module only credits explicit consumption/influence fields.  A status being
present in a unified payload is deliberately not treated as evidence consumed.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from statistics import median
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    now_iso,
    read_json,
    rounded,
    tail_jsonl,
    to_float,
    to_int,
    with_safety,
)
from engine.learning_return_integrity_v1 import audit_learning_return_rows, official_broker_confirmed_rows

VERSION = "1.1.0"
MAX_LEARNING_LINKAGE_ROWS = 120
CANONICAL_LANES = ("DAY", "SCALP", "SWING", "CRYPTO")

EVIDENCE_SPECS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("broker_truth", ("alpaca_paper_broker", "broker_truth_accumulation_v2", "canonical_outcome_audit_v1"), ("Performance", "Governance", "Cortex")),
    ("incomplete_broker_lifecycle", ("trade_lifecycle_audit_truth_horizon_integrity_suite_v1",), ("Lifecycle", "Cortex")),
    ("canonical_outcomes", ("shadow_vs_paper_performance_attribution_v1", "canonical_outcome_audit_v1"), ("Performance", "Learning")),
    ("shadow", ("realistic_shadow_evidence_learning_lab_v1", "shadow_vs_paper_performance_attribution_v1"), ("Shadow", "Copilot")),
    ("replay", ("replay_counterfactual_learning_v2", "ranking_tournament_engine_v1", "exit_tournament_engine_v1"), ("Replay", "Shadow")),
    ("counterfactual", ("replay_counterfactual_learning_v2", "opportunity_cost_learning"), ("Opportunity Cost", "Shadow")),
    ("provider_context", ("market_context_learning_suite_v1", "context_evidence_expansion_suite_v1"), ("Market Intelligence", "Copilot")),
    ("symbol_memory", ("long_term_memory_symbol_retrieval_suite_v1", "symbol_intelligence_behavioral_memory_v1"), ("Symbol Intelligence", "Copilot")),
    ("regime", ("market_transition_detection_v1", "market_condition_attribution_v1", "market_regime_similarity_engine_v1"), ("Regime", "Governance")),
    ("archetype", ("trade_archetype_regime", "trade_family_intelligence_v1"), ("Trade Intelligence", "Copilot")),
    ("catalyst", ("catalyst_lifecycle_intelligence_v1", "catalyst_persistence_decay_curves_v2"), ("Catalyst", "Copilot")),
    ("sector", ("cross_sector_capital_flow_memory_v1", "etf_sector_rotation_intelligence_v1"), ("Market Intelligence", "Ranking Diagnostics")),
    ("breadth", ("market_breadth_index_intelligence_v1",), ("Market Intelligence", "Regime")),
    ("opportunity_cost", ("opportunity_cost_learning",), ("Opportunity Cost", "Ranking Diagnostics")),
    ("historical_similarity", ("long_term_memory_symbol_retrieval_suite_v1", "market_regime_similarity_engine_v1"), ("Historical Similarity", "Copilot")),
    ("trade_style", ("trade_style_intelligence_audit_v1", "trade_family_intelligence_v1"), ("Trade Intelligence", "Learning")),
    ("horizon", ("multi_horizon_intelligence_adaptive_lifecycle_suite_v1", "horizon_performance_dashboard"), ("Horizon Intelligence", "Learning")),
    ("entry_readiness", ("equity_horizon_qualification_completion_v2", "astra_trading_intelligence_foundation_v1"), ("Entry Readiness", "Copilot")),
    ("exit_readiness", ("exit_readiness_diagnostics_v1", "profit_capture_peak_decay_exit_validation_suite_v1"), ("Exit Readiness", "Copilot")),
)


def _first_number(payloads: list[dict[str, Any]], keys: tuple[str, ...]) -> int:
    for payload in payloads:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return int(value)
    return 0


def _rows(value: Any, *, limit: int = MAX_LEARNING_LINKAGE_ROWS) -> list[dict[str, Any]]:
    """Read only compact in-memory/status rows; never expand a raw history."""
    if isinstance(value, dict):
        for key in ("records", "rows", "lessons", "events", "entries"):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value[:limit] if isinstance(row, dict)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _ids(row: dict[str, Any], *keys: str) -> set[str]:
    values: set[str] = set()
    for key in keys:
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            values.update(_text(item) for item in value if _text(item))
        elif _text(value):
            values.add(_text(value))
    return values


def _first_identity(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        values = _ids(row, key)
        if values:
            return sorted(values)[0]
    return ""


def _timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("applied_at", "timestamp", "timestamp_utc", "created_at", "truth_timestamp", "exit_timestamp", "completed_at"):
        raw = _text(row.get(key))
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _return_pct(row: dict[str, Any]) -> float | None:
    for key in ("realized_return", "return_pct", "actual_return_pct", "current_or_exit_profit_pct", "exit_gain_pct"):
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _lane(row: dict[str, Any]) -> str:
    raw = _text(row.get("lane") or row.get("lane_id") or row.get("horizon") or row.get("horizon_style")).upper()
    if "SCALP" in raw:
        return "SCALP"
    if "CRYPTO" in raw:
        return "CRYPTO"
    if "SWING" in raw:
        return "SWING"
    if "DAY" in raw:
        return "DAY"
    return "UNCLASSIFIED"


def _application_state(row: dict[str, Any]) -> str:
    raw = _text(row.get("lesson_application_state") or row.get("application_state") or row.get("lesson_influence_state")).upper()
    if raw in {"LESSON_APPLIED", "APPLIED"}:
        return "LESSON_APPLIED"
    if raw in {"LESSON_RETRIEVED", "RETRIEVED", "ASSOCIATED"}:
        return "LESSON_RETRIEVED"
    if raw in {"LESSON_NOT_APPLICABLE", "NOT_APPLICABLE"}:
        return "LESSON_NOT_APPLICABLE"
    return "APPLICATION_NOT_PROVEN"


def _outcome_effect(application: dict[str, Any], truth: dict[str, Any]) -> str:
    explicit = _text(application.get("outcome_effect") or application.get("effectiveness_outcome")).upper()
    if explicit in {"IMPROVED", "WORSENED", "NEUTRAL", "UNCLEAR"}:
        return "NEUTRAL_OR_UNCLEAR" if explicit in {"NEUTRAL", "UNCLEAR"} else explicit
    baseline = application.get("baseline_return_pct")
    actual = _return_pct(truth)
    try:
        if baseline is not None and actual is not None:
            return "IMPROVED" if actual > float(baseline) else "WORSENED" if actual < float(baseline) else "NEUTRAL_OR_UNCLEAR"
    except (TypeError, ValueError):
        pass
    return "NEUTRAL_OR_UNCLEAR"


def _lesson_effectiveness_state(stats: dict[str, Any]) -> str:
    linked = to_int(stats.get("canonical_outcomes"), 0)
    improved = to_int(stats.get("improved_outcomes"), 0)
    worsened = to_int(stats.get("worsened_outcomes"), 0)
    if to_int(stats.get("applications_proven"), 0) == 0:
        return "NOT_APPLIED"
    if linked == 0:
        return "INSUFFICIENT_CANONICAL_EVIDENCE"
    if linked < 3:
        return "PROMISING" if improved > worsened else "MIXED" if improved and worsened else "INSUFFICIENT_CANONICAL_EVIDENCE"
    if improved >= 2 and worsened == 0:
        return "EFFECTIVE"
    if worsened > improved:
        return "UNDERPERFORMING"
    if improved > worsened:
        return "PROMISING"
    return "CONTRADICTORY" if worsened else "MIXED"


def build_canonical_lesson_outcome_linkage_v1(
    *,
    lessons: list[dict[str, Any]],
    truths: list[dict[str, Any]],
    application_events: list[dict[str, Any]],
    max_rows: int = MAX_LEARNING_LINKAGE_ROWS,
) -> dict[str, Any]:
    """Link only explicit lesson applications to later official broker truth.

    Advisory lesson attachment is intentionally retained as retrieval evidence,
    never upgraded into application or broker-confirmed effectiveness.
    """
    bounded_lessons = _rows(lessons, limit=max_rows)
    bounded_events = _rows(application_events, limit=max_rows)
    bounded_truths = _rows(truths, limit=max_rows)
    official_truths = official_broker_confirmed_rows(bounded_truths, max_rows=max_rows)
    lesson_ids = _ids({"lesson_ids": [row.get("lesson_id") for row in bounded_lessons]}, "lesson_ids")
    for event in bounded_events:
        lesson_ids.update(_ids(event, "lesson_id", "canonical_lesson_id", "canonical_lesson_ids", "lesson_ids"))
    lesson_stats: dict[str, dict[str, Any]] = {
        lesson_id: {
            "lesson_id": lesson_id,
            "availability": "LESSON_EXISTED",
            "applications_proven": 0,
            "retrievals_proven": 0,
            "linked_outcomes": 0,
            "canonical_outcomes": 0,
            "shadow_supported_outcomes": 0,
            "replay_supported_outcomes": 0,
            "improved_outcomes": 0,
            "worsened_outcomes": 0,
            "neutral_or_unclear_outcomes": 0,
            "first_applied_at": None,
            "most_recent_applied_at": None,
            "last_evaluated_at": now_iso(),
            "context": [],
            "supporting_truth_ids": [],
        }
        for lesson_id in sorted(lesson_ids)
    }
    truth_by_identity: dict[str, list[dict[str, Any]]] = {}
    for truth in official_truths:
        for identity in _ids(truth, "truth_id", "broker_truth_id", "lifecycle_id", "position_id", "candidate_id"):
            truth_by_identity.setdefault(identity, []).append(truth)

    linked_keys: set[tuple[str, str]] = set()
    links: list[dict[str, Any]] = []
    for event in bounded_events:
        state = _application_state(event)
        event_lessons = _ids(event, "lesson_id", "canonical_lesson_id", "canonical_lesson_ids", "lesson_ids")
        for lesson_id in event_lessons:
            stats = lesson_stats.setdefault(lesson_id, {"lesson_id": lesson_id, "availability": "APPLICATION_NOT_PROVEN", "applications_proven": 0, "retrievals_proven": 0, "linked_outcomes": 0, "canonical_outcomes": 0, "shadow_supported_outcomes": 0, "replay_supported_outcomes": 0, "improved_outcomes": 0, "worsened_outcomes": 0, "neutral_or_unclear_outcomes": 0, "first_applied_at": None, "most_recent_applied_at": None, "last_evaluated_at": now_iso(), "context": [], "supporting_truth_ids": []})
            if state == "LESSON_RETRIEVED":
                stats["retrievals_proven"] += 1
                stats["availability"] = "LESSON_RETRIEVED"
                continue
            if state != "LESSON_APPLIED":
                continue
            stats["applications_proven"] += 1
            stats["availability"] = "LESSON_APPLIED"
            applied_at = _timestamp(event)
            stamp = applied_at.isoformat().replace("+00:00", "Z") if applied_at else None
            if not stats["first_applied_at"] or (stamp and stamp < stats["first_applied_at"]):
                stats["first_applied_at"] = stamp
            if stamp and (not stats["most_recent_applied_at"] or stamp > stats["most_recent_applied_at"]):
                stats["most_recent_applied_at"] = stamp
            identities = _ids(event, "truth_id", "broker_truth_id", "lifecycle_id", "position_id", "candidate_id")
            candidates = [truth for identity in identities for truth in truth_by_identity.get(identity, [])]
            for truth in candidates:
                truth_time = _timestamp(truth)
                if applied_at and truth_time and truth_time < applied_at:
                    continue
                truth_id = _first_identity(truth, "truth_id", "broker_truth_id", "lifecycle_id")
                key = (lesson_id, truth_id)
                if not truth_id or key in linked_keys:
                    continue
                linked_keys.add(key)
                effect = _outcome_effect(event, truth)
                stats["linked_outcomes"] += 1
                stats["canonical_outcomes"] += 1
                stats[f"{effect.lower() if effect != 'NEUTRAL_OR_UNCLEAR' else 'neutral_or_unclear'}_outcomes"] += 1
                stats["supporting_truth_ids"] = (stats["supporting_truth_ids"] + [truth_id])[:12]
                context = {key: truth.get(key) for key in ("lane", "lane_id", "horizon", "horizon_style", "regime", "symbol") if truth.get(key) is not None}
                if context and context not in stats["context"]:
                    stats["context"] = (stats["context"] + [context])[:8]
                links.append({"lesson_id": lesson_id, "truth_id": truth_id, "lifecycle_id": truth.get("lifecycle_id"), "candidate_id": truth.get("candidate_id"), "outcome_effect": effect, "evidence_class": "BROKER_CONFIRMED_CANONICAL"})

    for stats in lesson_stats.values():
        stats["evidence_status"] = _lesson_effectiveness_state(stats)
    return {
        "version": "1.0.0",
        "canonical_linkage_contract": "explicit_lesson_application_to_later_broker_confirmed_truth",
        "lessons": list(lesson_stats.values())[:max_rows],
        "links": links[:max_rows],
        "linked_outcomes": len(links),
        "explicit_application_events": sum(1 for event in bounded_events if _application_state(event) == "LESSON_APPLIED"),
        "retrieval_only_events": sum(1 for event in bounded_events if _application_state(event) == "LESSON_RETRIEVED"),
        "canonical_truths_examined": len(official_truths),
        "input_records_examined": len(bounded_lessons) + len(bounded_events) + len(bounded_truths),
        "skipped_or_unlinked_count": max(0, len(bounded_events) - len(links)),
        "full_history_scan_count": 0,
        "index_first_bounded_processing": True,
        "shadow_or_replay_never_promoted": True,
    }


def _cohort_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [value for row in rows if (value := _return_pct(row)) is not None]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    def average(key: str) -> float | None:
        values = [to_float(row.get(key)) for row in rows if row.get(key) is not None]
        return rounded(sum(values) / len(values)) if values else None
    return {
        "truth_count": len(rows),
        "win_rate": rounded(len(winners) * 100.0 / len(returns)) if returns else None,
        "profit_factor": rounded(gross_profit / gross_loss) if gross_loss else (rounded(gross_profit) if gross_profit else None),
        "average_return": rounded(sum(returns) / len(returns)) if returns else None,
        "median_return": rounded(median(returns)) if returns else None,
        "average_winner": rounded(sum(winners) / len(winners)) if winners else None,
        "average_loser": rounded(sum(losers) / len(losers)) if losers else None,
        "average_mfe": average("mfe_pct"),
        "average_mae": average("mae_pct"),
        "average_profit_capture_ratio": average("capture_ratio"),
        "average_giveback": average("giveback_pct"),
        "average_hold_duration": average("hold_duration"),
    }


def _progression_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: _timestamp(row) or datetime.min.replace(tzinfo=timezone.utc))
    if len(ordered) < 3:
        return {"status": "INSUFFICIENT_EVIDENCE", "truth_count": len(ordered), "evidence_caveat": "at_least_three_chronological_canonical_truths_required"}
    size, remainder = divmod(len(ordered), 3)
    counts = [size + (1 if index < remainder else 0) for index in range(3)]
    start = 0
    cohorts: dict[str, dict[str, Any]] = {}
    for name, count in zip(("EARLY", "MIDDLE", "RECENT"), counts):
        part = ordered[start:start + count]
        start += count
        cohorts[name] = _cohort_metrics(part)
    early, recent = cohorts["EARLY"], cohorts["RECENT"]
    if to_int(early.get("truth_count"), 0) < 2 or to_int(recent.get("truth_count"), 0) < 2:
        status = "INSUFFICIENT_EVIDENCE"
        delta = None
    else:
        delta = rounded(to_float(recent.get("median_return")) - to_float(early.get("median_return")))
        status = "IMPROVING" if delta > 0 else "DETERIORATING" if delta < 0 else "FLAT_OR_MIXED"
    return {"status": status, "truth_count": len(ordered), "recent_vs_early_median_return_delta": delta, "cohorts": cohorts, "evidence_caveat": "chronological descriptive comparison; no policy promotion"}


def build_truth_progression_v1(truths: list[dict[str, Any]], *, max_rows: int = MAX_LEARNING_LINKAGE_ROWS) -> dict[str, Any]:
    bounded = _rows(truths, limit=max_rows)
    integrity = audit_learning_return_rows(bounded, max_rows=max_rows)
    official = official_broker_confirmed_rows(bounded, max_rows=max_rows)
    by_lane = {lane: _progression_for_rows([row for row in official if _lane(row) == lane]) for lane in CANONICAL_LANES}
    overall = _progression_for_rows(official)
    overall["return_integrity"] = integrity
    return {
        "official_truth_source": "BROKER_CONFIRMED_CANONICAL_ONLY",
        "overall": overall,
        "by_lane": by_lane,
        "is_astra_improving": "YES" if overall.get("status") == "IMPROVING" else "NO" if overall.get("status") == "DETERIORATING" else "MIXED" if overall.get("status") == "FLAT_OR_MIXED" else "INSUFFICIENT_EVIDENCE",
        "input_records_examined": len(bounded),
        "full_history_scan_count": 0,
        "index_first_bounded_processing": True,
    }


def build_lesson_mistake_recurrence_v1(
    recurrence_events: list[dict[str, Any]], linkage: dict[str, Any], *, max_rows: int = MAX_LEARNING_LINKAGE_ROWS
) -> dict[str, Any]:
    links = _rows(linkage.get("links"), limit=max_rows)
    applied_truths_by_lesson: dict[str, set[str]] = {}
    for link in links:
        applied_truths_by_lesson.setdefault(_text(link.get("lesson_id")), set()).update(_ids(link, "truth_id", "lifecycle_id", "candidate_id"))
    rows: list[dict[str, Any]] = []
    for event in _rows(recurrence_events, limit=max_rows):
        lesson_id = _first_identity(event, "prior_lesson_id", "lesson_id", "canonical_lesson_id")
        event_ids = _ids(event, "truth_id", "broker_truth_id", "lifecycle_id", "candidate_id")
        recurring = bool(event.get("recurrence") or event.get("is_recurrence") or to_int(event.get("recurrence_count"), 0) > 1)
        applied = bool(lesson_id and event_ids.intersection(applied_truths_by_lesson.get(lesson_id, set())))
        if not lesson_id:
            classification = "FIRST_OBSERVED"
        elif not applied:
            classification = "LESSON_CREATED_NOT_YET_APPLIED"
        elif recurring:
            classification = "RECURRENCE_AFTER_LESSON"
        else:
            classification = "LESSON_APPLIED_NO_RECURRENCE_YET"
        rows.append({
            "pattern_id": event.get("pattern_id") or event.get("mistake_id") or event.get("signature"),
            "prior_lesson_id": lesson_id or None,
            "prior_application_proven": applied,
            "classification": classification,
            "recurrence_count_before_lesson": to_int(event.get("recurrence_count_before_lesson")),
            "recurrence_count_after_lesson": to_int(event.get("recurrence_count_after_lesson")),
            "improved_later": event.get("improved_later"),
            "latest_outcome": event.get("latest_outcome"),
            "supporting_ids": sorted(event_ids)[:6],
        })
    return {
        "owner": "self_correction_controller",
        "records": rows,
        "recurrence_after_lesson_count": sum(1 for row in rows if row["classification"] == "RECURRENCE_AFTER_LESSON"),
        "input_records_examined": len(_rows(recurrence_events, limit=max_rows)),
        "full_history_scan_count": 0,
        "index_first_bounded_processing": True,
    }


class AstraIntelligenceEffectivenessLearningVelocityV1(CachedDiagnosticModule):
    module_name = "astra_intelligence_effectiveness_learning_velocity_v1"
    mode = "shadow_analysis_evidence_consumption_and_learning_velocity"

    def _linkage_inputs(self, statuses: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Use existing compact stores and bounded ledger tails, never raw history."""
        lessons = _rows(statuses.get("canonical_lifecycle_lessons_v1"))
        if not lessons:
            lessons = tail_jsonl(os.path.join(self.state_dir, "canonical_lifecycle_lessons_v1.jsonl"), max_rows=MAX_LEARNING_LINKAGE_ROWS)
        truths = _rows(statuses.get("broker_truth_records_v1"))
        if not truths:
            truths = _rows(read_json(os.path.join(self.state_dir, "broker_truth_records_v1.json")))
        applications = _rows(statuses.get("lesson_application_events_v1"))
        if not applications:
            # Existing candidate attachment is advisory retrieval evidence only.
            for row in tail_jsonl(os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"), max_rows=MAX_LEARNING_LINKAGE_ROWS):
                lesson_ids = list(_ids(row, "canonical_lesson_ids", "lesson_ids"))
                if lesson_ids:
                    applications.append({
                        "lesson_ids": lesson_ids,
                        "lesson_application_state": "LESSON_RETRIEVED",
                        "candidate_id": row.get("candidate_id"),
                        "lifecycle_id": row.get("lifecycle_id"),
                        "timestamp": row.get("timestamp") or row.get("timestamp_utc"),
                        "source": "candidate_decision_ledger_advisory_attachment",
                    })
        recurrences = _rows(statuses.get("lesson_recurrence_events_v1"))
        return lessons, truths, applications, recurrences

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        evidence_rows: list[dict[str, Any]] = []
        total_available = total_indexed = total_retrieved = total_consumed = total_influenced = 0
        for evidence_class, keys, consumers in EVIDENCE_SPECS:
            payloads = [dict(statuses.get(key) or {}) for key in keys if isinstance(statuses.get(key), dict)]
            available = _first_number(payloads, ("evidence_count", "supporting_evidence_count", "observation_count", "tracked_records", "canonical_closed_trade_count", "shadow_opportunities"))
            indexed = _first_number(payloads, ("indexed_records", "indexed_evidence_count", "retrieval_indexed_count"))
            retrieved = _first_number(payloads, ("retrieved_count", "lessons_retrieved", "retrieval_count", "evidence_retrieved"))
            consumed = _first_number(payloads, ("consumed_count", "evidence_consumed", "lessons_consumed", "recommendations_influenced"))
            influenced = _first_number(payloads, ("influenced_decisions", "recommendations_influenced", "decision_fields_influenced"))
            if available and not indexed:
                indexed_status = "not_proven"
            else:
                indexed_status = "indexed" if indexed > 0 else "not_proven"
            consumption_status = "consumed" if consumed > 0 else "available_not_proven" if available > 0 else "not_available"
            evidence_rows.append({
                "evidence_class": evidence_class,
                "intended_consumers": list(consumers),
                "available": available,
                "indexed": indexed,
                "retrieved": retrieved,
                "consumed": consumed,
                "decision_influenced": influenced,
                "indexed_status": indexed_status,
                "consumption_status": consumption_status,
                "passive_presence_excluded": True,
                "source_keys": list(keys),
            })
            total_available += available
            total_indexed += indexed
            total_retrieved += retrieved
            total_consumed += consumed
            total_influenced += influenced

        quality = dict(statuses.get("evidence_quality_scoring_v1") or {})
        librarian = dict(statuses.get("astra_tier2a_librarian_executive_truth_layer_v1") or {})
        retention = dict(statuses.get("learning_acceleration_retention_suite_v1") or {})
        shadow = dict(statuses.get("realistic_shadow_evidence_learning_lab_v1") or {})
        backlog = _first_number([retention, shadow], ("backlog_count", "learning_backlog_count", "pending_lessons", "pending_items"))
        lesson_count = _first_number([librarian], ("lessons_organized", "lesson_count", "lessons"))
        validated = _first_number([librarian, retention], ("validated_lessons", "lessons_validated", "validated_count"))
        contradicted = _first_number([librarian, retention], ("contradicted_lessons", "lessons_contradicted", "contradicted_count"))
        expired = _first_number([librarian, retention], ("expired_lessons", "lessons_expired", "expired_count"))
        velocity = _first_number([retention, shadow], ("processing_throughput", "learning_velocity", "lessons_created_today", "completed_lifecycles"))
        consumption_ratio = rounded(total_consumed * 100.0 / max(1, total_available), 3)
        influence_ratio = rounded(total_influenced * 100.0 / max(1, total_consumed), 3)
        status = "ok" if total_available > 0 else "insufficient_evidence"
        lessons, truths, applications, recurrences = self._linkage_inputs(statuses)
        lesson_outcome_linkage = build_canonical_lesson_outcome_linkage_v1(
            lessons=lessons,
            truths=truths,
            application_events=applications,
        )
        truth_progression = build_truth_progression_v1(truths)
        mistake_recurrence = build_lesson_mistake_recurrence_v1(recurrences, lesson_outcome_linkage)
        lesson_effectiveness_rows = list(lesson_outcome_linkage.get("lessons") or [])
        lesson_effectiveness_summary = {
            "linked_outcomes": lesson_outcome_linkage.get("linked_outcomes", 0),
            "improved_outcomes": sum(to_int(row.get("improved_outcomes")) for row in lesson_effectiveness_rows),
            "worsened_outcomes": sum(to_int(row.get("worsened_outcomes")) for row in lesson_effectiveness_rows),
            "effective_lessons": sum(1 for row in lesson_effectiveness_rows if row.get("evidence_status") == "EFFECTIVE"),
            "underperforming_lessons": sum(1 for row in lesson_effectiveness_rows if row.get("evidence_status") == "UNDERPERFORMING"),
            "not_measurable_until_outcome_linkage": not bool(lesson_outcome_linkage.get("linked_outcomes")),
            "official_evidence_only": True,
        }
        return with_safety({
            "endpoint": "/api/astra_intelligence_effectiveness_learning_velocity_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "evidence_chain": evidence_rows,
            "evidence_available": total_available,
            "evidence_indexed": total_indexed,
            "evidence_retrieved": total_retrieved,
            "evidence_consumed": total_consumed,
            "decision_fields_influenced": total_influenced,
            "evidence_consumption_ratio": consumption_ratio,
            "influence_trace_coverage_pct": influence_ratio,
            "passive_presence_excluded": True,
            "consumer_coverage": {row["evidence_class"]: row["intended_consumers"] for row in evidence_rows},
            "missing_consumers": [row["evidence_class"] for row in evidence_rows if row["available"] and not row["consumed"]],
            "stale_consumers": [],
            "outdated_schema_consumers": [],
            "lesson_quality": {
                "raw_evidence_count": to_int(quality.get("raw_evidence_count"), total_available),
                "weighted_evidence_count": quality.get("weighted_evidence_count"),
                "average_evidence_quality": quality.get("average_evidence_quality"),
                "quality_bucket": quality.get("quality_bucket") or "insufficient_evidence",
                "quality_source": "evidence_quality_scoring_v1",
            },
            "lesson_state_counts": {
                "lessons": lesson_count,
                "validated_advisory_lessons": validated,
                "contradicted": contradicted,
                "expired": expired,
            },
            "learning_velocity": {
                "raw_observations_created": total_available,
                "canonical_outcomes_created": _first_number([statuses.get("shadow_vs_paper_performance_attribution_v1") or {}], ("canonical_closed_trade_count", "paper_trade_count")),
                "lessons_created": lesson_count,
                "lessons_validated": validated,
                "lessons_contradicted": contradicted,
                "lessons_expired": expired,
                "lessons_retrieved": total_retrieved,
                "lessons_consumed": total_consumed,
                "recommendations_influenced": total_influenced,
                "processing_throughput": velocity,
            },
            "canonical_lesson_outcome_linkage_v1": lesson_outcome_linkage,
            "lesson_effectiveness_v1": lesson_effectiveness_summary,
            "truth_progression_v1": truth_progression,
            "mistake_recurrence_lesson_linkage_v1": mistake_recurrence,
            "learning_loop_summary_v1": {
                "is_astra_improving": truth_progression.get("is_astra_improving"),
                "why": {
                    "newer_truths_vs_older": (truth_progression.get("overall") or {}).get("status"),
                    "effective_lessons": lesson_effectiveness_summary["effective_lessons"],
                    "underperforming_lessons": lesson_effectiveness_summary["underperforming_lessons"],
                    "recurrence_after_proven_application": mistake_recurrence.get("recurrence_after_lesson_count", 0),
                    "canonical_truth_sample_size": (truth_progression.get("overall") or {}).get("truth_count", 0),
                },
                "advisory_only": True,
                "automatic_policy_promotion": False,
            },
            "bounded_processing": {
                "input_records_examined": lesson_outcome_linkage.get("input_records_examined", 0) + truth_progression.get("input_records_examined", 0),
                "canonical_link_count": lesson_outcome_linkage.get("linked_outcomes", 0),
                "skipped_unlinked_count": lesson_outcome_linkage.get("skipped_or_unlinked_count", 0),
                "full_history_scan_count": 0,
                "index_first": True,
            },
            "backlog_governance": {
                "backlog_count": backlog,
                "backlog_age": retention.get("backlog_age") or retention.get("oldest_backlog_age"),
                "stale_backlog": retention.get("stale_backlog") or retention.get("stale_backlog_count"),
                "categories": ["awaiting_canonical_outcome", "awaiting_broker_truth", "awaiting_consumer", "awaiting_sample_size", "awaiting_human_review", "contradicted", "expired"],
                "priority_policy": "decision_impact_evidence_maturity_consumer_gap_age_safety",
            },
            "effectiveness_scorecard": {
                "evidence_utilization": consumption_ratio,
                "consumer_coverage": rounded(sum(1 for row in evidence_rows if row["consumed"]) * 100.0 / max(1, len(evidence_rows)), 3),
                "lesson_quality": quality.get("average_evidence_quality"),
                "knowledge_freshness": quality.get("recency") or "not_measured",
                "retrieval_latency": (statuses.get("astra_knowledge_warehouse_v1") or {}).get("latency_ms") or "not_measured",
                "influence_trace_coverage": influence_ratio,
                "broker_truth_confirmation": (statuses.get("shadow_vs_paper_performance_attribution_v1") or {}).get("canonical_closed_trade_count", 0),
                "shadow_experiment_health": shadow.get("status") or "not_measured",
                "contradiction_rate": rounded(contradicted * 100.0 / max(1, lesson_count), 3),
                "learning_velocity": velocity,
                "backlog_health": "measured" if backlog else "not_proven",
                "promotion_readiness": "disabled_by_policy",
                "storage_index_health": (statuses.get("astra_knowledge_warehouse_v1") or {}).get("index_coverage_pct"),
            },
            "promotion_enabled": False,
            "automatic_promotions_enabled": False,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "broker_calls_used": 0,
            "llm_calls_used": 0,
        })
