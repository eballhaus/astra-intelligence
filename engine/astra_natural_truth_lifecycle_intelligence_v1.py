"""Bounded lifecycle/truth/learning intelligence over canonical Astra state.

This module is an observational integration adapter.  It does not own a
position, lifecycle, strict-truth, learning, lesson, or shadow store.  It
joins already-produced canonical records so readiness and human diagnostics
can explain lifecycle continuity without mutating production evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from engine.astra_multilane_activation_v2 import is_natural_paper_truth, strict_broker_truth


VERSION = "1.0.0"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
MAX_POSITIONS = 80
MAX_TRUTHS = 250
MAX_LESSONS = 100


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any, limit: int = MAX_POSITIONS) -> list[dict[str, Any]]:
    return [dict(row) for row in list(value or [])[:limit] if isinstance(row, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat().replace("+00:00", "Z")


def _timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _age_seconds(value: Any, now: datetime) -> float | None:
    parsed = _timestamp(value)
    return round(max(0.0, (now - parsed).total_seconds()), 3) if parsed else None


def _lane(row: Mapping[str, Any]) -> str:
    lane = _upper(row.get("lane") or row.get("lane_id") or row.get("original_lane") or row.get("recovered_lane"))
    return lane if lane in LANES else ""


def _symbol(row: Mapping[str, Any]) -> str:
    return _upper(row.get("symbol") or row.get("canonical_symbol") or row.get("ticker")).replace(" ", "")


def _lifecycle_id(row: Mapping[str, Any]) -> str:
    return _text(
        row.get("canonical_lifecycle_id")
        or row.get("lifecycle_id")
        or row.get("source_lifecycle_id")
        or row.get("canonical_position_id")
        or row.get("position_id")
    )


def _position_key(row: Mapping[str, Any]) -> str:
    identity = _lifecycle_id(row)
    return identity or f"unresolved:{_symbol(row)}:{_upper(row.get('asset_class') or row.get('asset_type'))}"


def _identity_candidates(row: Mapping[str, Any]) -> set[str]:
    return {
        _text(row.get(key))
        for key in (
            "canonical_lifecycle_id", "lifecycle_id", "source_lifecycle_id",
            "canonical_position_id", "position_id", "entry_fill_id", "candidate_id",
        )
        if _text(row.get(key))
    }


def _merge_position_rows(runtime: Mapping[str, Any], open_positions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Join by canonical identity first and symbol only when identity is absent."""
    recovery = _dict(runtime.get("position_lane_horizon_recovery_v1"))
    recovery_rows = _rows(recovery.get("positions"), MAX_POSITIONS)
    capacity_rows = _rows(open_positions, MAX_POSITIONS)
    if not capacity_rows:
        capacity = _dict(runtime.get("last_evidence_capacity_snapshot"))
        capacity_rows = _rows(capacity.get("position_rows_for_read_only_consumers"), MAX_POSITIONS)
    exit_rows = _rows(_dict(runtime.get("position_exit_readiness_v1")).get("positions"), MAX_POSITIONS)
    advisory_rows = _rows(_dict(runtime.get("unified_position_advisory_v1")).get("positions"), MAX_POSITIONS)

    by_identity: dict[str, dict[str, Any]] = {}
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for source_rows in (recovery_rows, capacity_rows, exit_rows, advisory_rows):
        for row in source_rows:
            symbol = _symbol(row)
            if not symbol:
                continue
            identity = _lifecycle_id(row)
            target = by_identity.setdefault(identity, {}) if identity else {}
            if not identity:
                # Unidentified rows are merged only into their source row.  A
                # symbol is never allowed to manufacture lifecycle ownership.
                target = dict(row)
                by_symbol.setdefault(symbol, []).append(target)
            else:
                target.update({key: value for key, value in row.items() if value not in (None, "", [], {})})
    merged: list[dict[str, Any]] = []
    for row in capacity_rows or recovery_rows:
        symbol = _symbol(row)
        if not symbol:
            continue
        identity = _lifecycle_id(row)
        target = dict(by_identity.get(identity) or {}) if identity else dict(row)
        if identity:
            target.update({key: value for key, value in row.items() if value not in (None, "", [], {})})
        else:
            # Add the uniquely matching recovered identity only when the
            # recovery owner proves exactly one match for this symbol.
            candidates = [item for item in recovery_rows if _symbol(item) == symbol and _lifecycle_id(item)]
            if len(candidates) == 1:
                target.update(candidates[0])
            target.update({key: value for key, value in row.items() if value not in (None, "", [], {})})
        merged.append(target)
    if not merged:
        merged = [dict(row) for row in recovery_rows]
    unique: dict[str, dict[str, Any]] = {}
    for row in merged:
        unique.setdefault(_position_key(row), row)
    return list(unique.values())[:MAX_POSITIONS]


def _observation_map(runtime: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for precedence, key in enumerate(("active_equity_fmp_observations_v1", "alpaca_ws_active_position_monitor_v1")):
        payload = _dict(runtime.get(key))
        observations = payload.get("observations") if isinstance(payload.get("observations"), Mapping) else payload
        for symbol, row in _dict(observations).items():
            if isinstance(row, Mapping) and _symbol({"symbol": symbol}):
                candidates.append((precedence, {"symbol": symbol, **dict(row), "observation_source": key}))
    crypto = _dict(runtime.get("crypto_quote_handoffs_v1"))
    if not crypto:
        crypto = _dict(_dict(runtime.get("crypto_rankings_snapshot_v1")).get("crypto_quote_handoffs_v1"))
    for symbol, row in crypto.items():
        if isinstance(row, Mapping):
            candidates.append((2, {"symbol": symbol, **dict(row), "observation_source": "crypto_quote_handoffs_v1"}))
    result: dict[str, dict[str, Any]] = {}
    for _, row in candidates:
        symbol = _symbol(row)
        if not symbol:
            continue
        existing = result.get(symbol)
        existing_time = _timestamp(existing.get("provider_native_timestamp")) if existing else None
        current_time = _timestamp(row.get("provider_native_timestamp"))
        if existing is None or (current_time and (existing_time is None or current_time > existing_time)):
            result[symbol] = row
    return result


def _truth_key(row: Mapping[str, Any]) -> str:
    return _text(row.get("lifecycle_id") or row.get("truth_id") or row.get("stable_key"))


def _truth_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in list(rows or [])[:MAX_TRUTHS] if isinstance(row, Mapping)]


def _truth_is_strict(row: Mapping[str, Any]) -> bool:
    try:
        return bool(strict_broker_truth(row) and is_natural_paper_truth(row))
    except Exception:
        return False


def _learning_ids(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    identifiers: set[str] = set()
    for row in rows:
        identifiers.update(_identity_candidates(row))
        identifiers.update({
            _text(row.get("truth_id")), _text(row.get("broker_truth_id")),
            _text(row.get("stable_key")),
        } - {""})
    return identifiers


def build_truth_quality_assessment_v1(row: Mapping[str, Any]) -> dict[str, Any]:
    """Describe learning richness without changing binary strict-truth validity."""
    existing = _dict(row.get("truth_quality_score_v1"))
    if existing:
        grade = _text(existing.get("grade")) or "PARTIAL_CONTEXT"
        return {
            "status": "OBSERVED_CANONICAL_QUALITY",
            "grade": grade,
            "score": existing.get("score"),
            "components": dict(existing.get("components") or {}),
            "missing_or_unavailable": list(existing.get("missing_or_unavailable") or []),
            "strict_truth_validity_unchanged": True,
        }
    context = _dict(row.get("pretrade_context_v1"))
    observation = _dict(row.get("observational_learning_v1"))
    components = {
        "entry_context": bool(context),
        "management_history": bool(observation or row.get("management_events")),
        "exit_evidence": bool(_text(row.get("exit_fill_id")) and _text(row.get("exit_timestamp"))),
        "regime_context": bool(context.get("market_regime") or context.get("regime")),
        "provenance": bool(_text(row.get("lifecycle_id")) and _text(row.get("entry_fill_id"))),
    }
    available = sum(bool(value) for value in components.values())
    grade = "FULL_CONTEXT" if available == len(components) else "PARTIAL_CONTEXT" if available >= 2 else "MINIMAL_STRICT_TRUTH"
    return {
        "status": "DERIVED_LEARNING_RICHNESS_ONLY",
        "grade": grade,
        "score": None,
        "components": components,
        "missing_or_unavailable": [key for key, value in components.items() if not value],
        "strict_truth_validity_unchanged": True,
    }


def build_lesson_evidence_gate_v1(
    *, lessons: Iterable[Mapping[str, Any]] = (), truth_records: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return an advisory, lane-aware evidence gate; never promotes a lesson."""
    truths = [row for row in _truth_rows(truth_records) if _truth_is_strict(row)]
    truth_by_lesson: dict[str, list[dict[str, Any]]] = {}
    for truth in truths:
        for lesson_id in (_text(truth.get("lesson_id")), _text(truth.get("canonical_lesson_id"))):
            if lesson_id:
                truth_by_lesson.setdefault(lesson_id, []).append(truth)
    evaluations: list[dict[str, Any]] = []
    for lesson in _rows(lessons, MAX_LESSONS):
        lesson_id = _text(lesson.get("lesson_id"))
        if not lesson_id:
            continue
        supporting = truth_by_lesson.get(lesson_id, [])
        lanes = sorted({_lane(row) for row in supporting if _lane(row)})
        contradictions = [_text(value) for value in list(lesson.get("contradictory_lesson_ids") or []) if _text(value)]
        if not supporting:
            promotion = "OBSERVATION"
        elif contradictions:
            promotion = "REQUIRE_MORE_EVIDENCE"
        elif len(supporting) < 3:
            promotion = "EVIDENCE_ACCUMULATING"
        elif bool(lesson.get("shadow_supported")):
            promotion = "SHADOW_SUPPORTED"
        else:
            promotion = "EVIDENCE_ACCUMULATING"
        evaluations.append({
            "lesson_id": lesson_id,
            "supporting_strict_truth_count": len(supporting),
            "contradictory_lesson_ids": contradictions,
            "applicable_lanes": lanes,
            "lane_scope": "CROSS_LANE_CANDIDATE" if len(lanes) > 1 else "LANE_SPECIFIC" if lanes else "UNPROVEN",
            "promotion_state": promotion,
            "low_sample_confidence_guard": len(supporting) < 3,
            "execution_authority": "NONE",
            "automatic_promotion": False,
        })
    return {
        "owner": "canonical_lifecycle_lessons_v1 + contextual learning applicability",
        "status": "OBSERVATION_ONLY" if not evaluations else "EVIDENCE_GATED_ADVISORY",
        "evaluations": evaluations,
        "strict_truth_source_only": True,
        "shadow_can_support_but_cannot_promote": True,
        "execution_authority": "NONE",
    }


def _stage_timestamps(readiness: Mapping[str, Any], lane: str) -> dict[str, Any]:
    row = _dict(_dict(readiness.get("truth_production_watchdog")).get("lanes", {}).get(lane))
    return {key: row.get(key) for key in (
        "last_discovery_time", "last_candidate_time", "last_finalist_time", "last_qualified_time",
        "last_order_ready_time", "last_fill_time", "last_management_evaluation_time",
        "last_exit_evaluation_time", "last_exit_time", "last_reconciliation_time",
        "last_strict_truth_time", "last_learning_ingestion_time",
    )}


def _active_faults(readiness: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _rows(readiness.get("active_faults"), 40)


def _fault_for(row: Mapping[str, Any], faults: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    symbol, lifecycle, lane = _symbol(row), _lifecycle_id(row), _lane(row)
    matches = []
    for fault in faults:
        lanes = {_upper(value) for value in list(fault.get("lanes") or [])}
        if (_text(fault.get("lifecycle_id")) and _text(fault.get("lifecycle_id")) == lifecycle) or (
            _upper(fault.get("symbol")) == symbol and symbol
        ) or (lane and lane in lanes):
            matches.append(dict(fault))
    return matches[0] if matches else {}


def _wait_classification(fault: Mapping[str, Any], *, completed: bool, identity_missing: bool) -> str:
    if completed:
        return "COMPLETED"
    classification = _upper(fault.get("classification"))
    if classification in {"BROKER_EXTERNAL", "PROVIDER_EXTERNAL", "DEGRADED_EXTERNAL"} or identity_missing:
        return "EXTERNAL_WAIT"
    if classification in {"CODE_REPAIR_REQUIRED", "RUNTIME_REPAIR_IN_PROGRESS"}:
        return classification
    return "NATURAL_WAIT"


def _lifecycle_stage(row: Mapping[str, Any], management: Mapping[str, Any], observation: Mapping[str, Any], fault: Mapping[str, Any], truth: Mapping[str, Any], readiness: Mapping[str, Any]) -> tuple[str, str, str]:
    if truth:
        return "STRICT_TRUTH", "LEARNING_ACKNOWLEDGED", "COMPLETED"
    if _upper(fault.get("earliest_stage")) in {"RECONCILIATION", "STRICT_TRUTH", "LEARNING"}:
        stage = _upper(fault.get("earliest_stage"))
        return stage, "STRICT_TRUTH" if stage == "RECONCILIATION" else "LEARNING", _wait_classification(fault, completed=False, identity_missing=False)
    if not _lifecycle_id(row) or not _text(row.get("entry_fill_id")):
        return "POSITION_IDENTITY", "OBSERVATION", "EXTERNAL_WAIT"
    native = _text(observation.get("provider_native_timestamp"))
    freshness = _upper(observation.get("freshness_state") or observation.get("freshness"))
    if not native or freshness in {"STALE", "EXPIRED", "UNAVAILABLE", "MISSING"}:
        return "OBSERVATION", "MANAGEMENT", _wait_classification(fault, completed=False, identity_missing=False)
    lane = _lane(row)
    watchdog = _dict(_dict(readiness.get("truth_production_watchdog")).get("lanes")).get(lane)
    if not _text(_dict(watchdog).get("last_management_evaluation_time")):
        return "MANAGEMENT", "NATURAL_EXIT", _wait_classification(fault, completed=False, identity_missing=False)
    return "NATURAL_EXIT", "EXIT_FILLED", _wait_classification(fault, completed=False, identity_missing=False)


def _pre_exit_assurance(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "lifecycle_id": _lifecycle_id(row),
        "lane": _lane(row),
        "entry_fill_id": _text(row.get("entry_fill_id")),
        "position_owner": _text(row.get("position_owner") or row.get("lifecycle_owner")),
        "original_quantity": row.get("original_quantity") or row.get("entry_quantity") or row.get("qty") or row.get("quantity"),
        "broker_relationship": _text(row.get("entry_order_id") or row.get("broker_order_id") or row.get("entry_fill_id")),
    }
    missing = [key for key, value in required.items() if value in (None, "", [], {})]
    identity_status = _upper(row.get("canonical_identity_status") or row.get("lane_recovery_status"))
    if identity_status in {"AMBIGUOUS", "CONFLICT", "UNAVAILABLE"} or missing:
        status = "AMBIGUOUS" if identity_status in {"AMBIGUOUS", "CONFLICT"} else "INSUFFICIENT_EVIDENCE"
    else:
        status = "PASS"
    return {
        "status": status,
        "required_fields_present": sorted(key for key in required if key not in missing),
        "missing_fields": missing,
        "mutation_performed": False,
        "broker_aggregate_assignment": False,
    }


def _quality_and_attribution(truth: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    quality = build_truth_quality_assessment_v1(truth)
    observation = _dict(truth.get("observational_learning_v1"))
    existing = _text(
        truth.get("outcome_attribution")
        or truth.get("attribution_label")
        or observation.get("diagnostic_classification")
        or observation.get("thesis_outcome")
    )
    return quality, {
        "status": "OBSERVED_CANONICAL_ATTRIBUTION" if existing else "DATA_INSUFFICIENT_FOR_ATTRIBUTION",
        "label": existing or None,
        "source": "canonical_truth_observational_learning" if existing else None,
        "strategy_mutation": False,
    }


def _scorecard(
    lane: str,
    readiness: Mapping[str, Any],
    runtime: Mapping[str, Any],
    lifecycle_rows: list[Mapping[str, Any]],
    truths: list[Mapping[str, Any]],
    learning_ids: set[str],
) -> dict[str, Any]:
    matrix = _dict(runtime.get("multilane_completion_matrix") or runtime.get("astra_multilane_completion_matrix_v1"))
    matrix_lane = _dict(_dict(matrix.get("lanes")).get(lane))
    watchdog = _dict(_dict(readiness.get("truth_production_watchdog")).get("lanes")).get(lane)
    watchdog = _dict(watchdog)
    lane_rows = [row for row in lifecycle_rows if _lane(row) == lane]
    lane_truths = [row for row in truths if _lane(row) == lane]
    lifecycle_faults = [
        _dict(row.get("current_fault")) for row in lane_rows
        if _dict(row.get("current_fault"))
    ]
    external_lifecycle_fault = any(
        _upper(row.get("classification")) in {"BROKER_EXTERNAL", "PROVIDER_EXTERNAL", "DEGRADED_EXTERNAL"}
        for row in lifecycle_faults
    )
    technical_lifecycle_fault = any(
        _upper(row.get("classification")) not in {"BROKER_EXTERNAL", "PROVIDER_EXTERNAL", "DEGRADED_EXTERNAL", "NATURAL_WAIT", ""}
        for row in lifecycle_faults
    )
    last = _stage_timestamps(readiness, lane)
    def value(*keys: str) -> Any:
        for key in keys:
            if matrix_lane.get(key) not in (None, ""):
                return matrix_lane.get(key)
        return None
    truth_blocker = _text(watchdog.get("current_earliest_blocker") or watchdog.get("technical_truth_starvation_status")) or None
    truth_starvation = _text(watchdog.get("technical_truth_starvation_status")) or "UNKNOWN_TRUTH_STARVATION"
    # Entry capacity/eligibility can explain zero new entries, but cannot
    # turn an otherwise healthy open lifecycle into technical truth starvation.
    if lane_rows and not technical_lifecycle_fault and not external_lifecycle_fault:
        truth_blocker = "NATURAL_OPEN_POSITION"
        truth_starvation = "NATURAL_OPEN_POSITION"
    return {
        "lane": lane,
        "candidates": value("candidate_count", "candidates_seen"),
        "finalists": value("finalist_count", "finalists"),
        "qualified": value("qualified_count", "eligible_candidate_count"),
        "eligible": value("eligible_candidate_count", "eligible"),
        "order_ready": value("order_ready_count", "paper_order_intents"),
        "entries": value("filled_entries", "entries"),
        "open_positions": len(lane_rows),
        "managed_positions": sum(1 for row in lane_rows if _text(row.get("management_evaluation_time")) or _upper(row.get("management_state")) not in {"", "UNKNOWN", "UNAVAILABLE"}),
        "natural_exits": value("filled_exits", "exited"),
        "reconciled_completions": len(lane_truths),
        "strict_truths": len(lane_truths),
        "learning_acknowledgements": sum(1 for row in lane_truths if _truth_key(row) in learning_ids or bool(row.get("learning_acknowledged"))),
        "current_truth_blocker": truth_blocker,
        "technical_readiness": _text(watchdog.get("technical_readiness")) or "NOT_PROVEN",
        "truth_starvation_status": truth_starvation,
        "last_successful_stages": {
            "discovery": last.get("last_discovery_time"), "candidate": last.get("last_candidate_time"),
            "finalist": last.get("last_finalist_time"), "qualified": last.get("last_qualified_time"),
            "order_ready": last.get("last_order_ready_time"), "fill": last.get("last_fill_time"),
            "management": last.get("last_management_evaluation_time"), "exit": last.get("last_exit_time"),
            "reconciliation": last.get("last_reconciliation_time"), "truth": last.get("last_strict_truth_time"),
            "learning": last.get("last_learning_ingestion_time"),
        },
    }


def build_natural_truth_lifecycle_intelligence_v1(
    *,
    runtime_state: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    truth_records: Iterable[Mapping[str, Any]] = (),
    learning_records: Iterable[Mapping[str, Any]] = (),
    open_positions: Iterable[Mapping[str, Any]] = (),
    historical_certification: Mapping[str, Any] | None = None,
    current_commit: str = "UNAVAILABLE",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a bounded, read-only continuity view from existing state owners."""
    runtime = _dict(runtime_state)
    ready = _dict(readiness)
    current = _now(now)
    truths = _truth_rows(truth_records)
    strict_truths = [row for row in truths if _truth_is_strict(row)]
    learning_rows = _rows(learning_records, MAX_TRUTHS)
    learning_ids = _learning_ids(learning_rows)
    for row in strict_truths:
        if bool(row.get("learning_acknowledged")):
            learning_ids.update(_identity_candidates(row))
            learning_ids.add(_truth_key(row))
    lifecycle_rows = _merge_position_rows(runtime, open_positions)
    observations = _observation_map(runtime)
    fault_rows = _active_faults(ready)
    truth_by_lifecycle = {_truth_key(row): row for row in strict_truths if _truth_key(row)}
    lifecycle_state: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    attribution_rows: list[dict[str, Any]] = []
    for row in lifecycle_rows:
        symbol, lifecycle = _symbol(row), _lifecycle_id(row)
        observation = dict(observations.get(symbol) or {})
        truth = dict(truth_by_lifecycle.get(lifecycle) or {})
        fault = _fault_for(row, fault_rows)
        management = next((item for item in _rows(_dict(runtime.get("position_exit_readiness_v1")).get("positions")) if _symbol(item) == symbol and (_lifecycle_id(item) == lifecycle or not _lifecycle_id(item))), {})
        current_stage, expected_next, wait = _lifecycle_stage(row, management, observation, fault, truth, ready)
        identity_missing = not lifecycle or not _text(row.get("entry_fill_id"))
        wait = _wait_classification(fault, completed=bool(truth), identity_missing=identity_missing) if not truth else "COMPLETED"
        continuity = {
            "lifecycle_id": lifecycle or None,
            "lane": _lane(row) or None,
            "symbol": symbol or None,
            "candidate_id": _text(row.get("candidate_id")) or None,
            "entry_qualification_identity": _text(row.get("candidate_id") or row.get("entry_order_id")) or None,
            "pretrade_thesis_identity": _text(row.get("thesis_id") or row.get("entry_metadata_generation")) or None,
            "entry_order_id": _text(row.get("entry_order_id")) or None,
            "entry_fill_id": _text(row.get("entry_fill_id")) or None,
            "original_quantity": row.get("original_quantity") or row.get("entry_quantity") or row.get("qty") or row.get("quantity"),
            "current_reconciled_quantity": row.get("current_reconciled_quantity") or row.get("qty") or row.get("quantity"),
            "active_management_state": _text(management.get("recommendation") or management.get("exit_readiness_state") or row.get("management_state")) or None,
            "expected_horizon": _text(row.get("horizon") or row.get("original_horizon") or row.get("recovered_horizon")) or None,
            "exit_readiness_state": _text(management.get("exit_readiness_state")) or None,
            "exit_order_id": _text(row.get("exit_order_id")) or None,
            "exit_fill_id": _text(row.get("exit_fill_id")) or None,
            "reconciliation_state": _text(row.get("reconciliation_state") or row.get("reconciliation_status")) or None,
            "strict_truth_state": "CERTIFIED" if truth else "PENDING",
            "learning_acknowledgement_state": "ACKNOWLEDGED" if truth and (_truth_key(truth) in learning_ids or truth.get("learning_acknowledged")) else "PENDING",
            "current_stage": current_stage,
            "expected_next_stage": expected_next,
            "wait_classification": wait,
            "current_fault": {key: fault.get(key) for key in ("fault_type", "classification", "earliest_stage", "failing_invariant", "owner_file", "owner_function") if fault.get(key) not in (None, "")},
            "observation": {
                "provider": _text(observation.get("provider") or observation.get("provenance")) or None,
                "provider_native_timestamp": _text(observation.get("provider_native_timestamp")) or None,
                "receive_timestamp": _text(observation.get("receive_timestamp") or observation.get("received_at")) or None,
                "freshness_state": _upper(observation.get("freshness_state") or observation.get("freshness")) or "UNAVAILABLE",
                "age_seconds": _age_seconds(observation.get("provider_native_timestamp"), current),
                "source": _text(observation.get("observation_source")) or None,
            },
            "pre_exit_reconciliation_assurance": _pre_exit_assurance(row),
            "position_identity_status": _text(row.get("canonical_identity_status") or row.get("lane_recovery_status")) or "UNAVAILABLE",
            "provenance": {
                "position_source": "position_lane_horizon_recovery_v1 + broker_reconciled_capacity_snapshot",
                "management_source": "astra_position_exit_readiness_v1",
                "truth_source": "broker_truth_records_v1" if truth else None,
                "learning_source": "astra_operating_health_contract_v1" if _truth_key(truth) in learning_ids else None,
            },
        }
        lifecycle_state.append(continuity)
        if truth:
            quality, attribution = _quality_and_attribution(truth)
            quality_rows.append({"lifecycle_id": lifecycle, "lane": _lane(truth), "symbol": symbol, **quality})
            attribution_rows.append({"lifecycle_id": lifecycle, "lane": _lane(truth), "symbol": symbol, **attribution})

    strict_ids = {_truth_key(row) for row in strict_truths if _truth_key(row)}
    active_blockers = [row for row in fault_rows if _upper(row.get("earliest_stage")) in {"RECONCILIATION", "STRICT_TRUTH"} and _text(row.get("lifecycle_id"))]
    explicit_blocked_ids = {
        _text(row.get("lifecycle_id")) for row in active_blockers
        if _upper(row.get("classification")) in {"BROKER_EXTERNAL", "PROVIDER_EXTERNAL", "DEGRADED_EXTERNAL"}
        and ("BROKER" in _upper(row.get("failing_invariant")) or "BROKER" in _upper(row.get("evidence")) or _upper(row.get("fault_type")) == "RECONCILIATION_FAILURE")
    }
    completed_ids = strict_ids | explicit_blocked_ids
    acknowledged_ids = {_truth_key(row) for row in strict_truths if _truth_key(row) in learning_ids or bool(row.get("learning_acknowledged"))}
    explicit_learning_blocker_ids = {
        _text(row.get("lifecycle_id")) for row in fault_rows
        if _text(row.get("lifecycle_id")) in strict_ids and "LEARNING" in _upper(row.get("fault_type"))
    }
    truth_gaps = max(0, len(completed_ids) - len(strict_ids) - len(explicit_blocked_ids))
    learning_gaps = max(0, len(strict_ids) - len(acknowledged_ids) - len(explicit_learning_blocker_ids))
    truth_accounting = {
        "completed_lifecycle_count": len(completed_ids),
        "strict_truth_count": len(strict_ids),
        "explicitly_blocked_completion_count": len(explicit_blocked_ids),
        "learning_acknowledged_count": len(acknowledged_ids),
        "explicit_learning_blocker_count": len(explicit_learning_blocker_ids),
        "unexplained_gaps": truth_gaps + learning_gaps,
        "strict_truth_gaps": truth_gaps,
        "learning_handoff_gaps": learning_gaps,
        "invariant": "broker-confirmed completed lifecycles = strict truths + explicitly blocked completions; strict truths = learning acknowledgements + explicit learning blockers",
        "source": "bounded broker_truth_records_v1 + current readiness faults + operating health learning ledger",
        "status": "PASS" if truth_gaps + learning_gaps == 0 else "UNEXPLAINED_GAP",
    }
    lessons = _rows(runtime.get("canonical_lifecycle_lessons_v1"), MAX_LESSONS)
    shadow = {
        "owner": "astra_shadow_exit_intelligence_v1 and existing replay/counterfactual modules",
        "available": bool(runtime.get("shadow_exit_intelligence_v1") or runtime.get("shadow_exit_analysis_outputs_v1")),
        "evaluation_count": len(_rows(_dict(runtime.get("shadow_exit_intelligence_v1")).get("evaluations"), MAX_POSITIONS)),
        "broker_truth_separate": True,
        "execution_authority": "DISABLED",
        "promoted_to_broker_truth": False,
    }
    lane_rows = {lane: _scorecard(lane, ready, runtime, lifecycle_state, strict_truths, learning_ids) for lane in LANES}
    historical = _dict(historical_certification)
    historical_summary = {
        "status": _text(historical.get("status")) or "NOT_RUN",
        "current_commit": _text(historical.get("current_commit")) or None,
        "truth_accounting_integrity": _dict(historical.get("truth_accounting_integrity")),
        "learning_contract": _dict(historical.get("learning_contract")),
        "production_write": False,
    }
    return {
        "schema_version": "ASTRA_NATURAL_TRUTH_LIFECYCLE_INTELLIGENCE_V1",
        "version": VERSION,
        "generated_at": _iso(current),
        "current_commit": _text(current_commit) or "UNAVAILABLE",
        "mode": "PAPER_ONLY_READ_ONLY_DERIVED_VIEW",
        "owner": "canonical lifecycle/truth/learning owners; integration adapter only",
        "current_lifecycle_state": lifecycle_state,
        "lane_truth_starvation_scorecard": lane_rows,
        "truth_accounting_integrity": truth_accounting,
        "truth_quality_assessments": quality_rows[:MAX_TRUTHS],
        "outcome_attribution": attribution_rows[:MAX_TRUTHS],
        "shadow_counterfactual_status": shadow,
        "lesson_evidence_gate": build_lesson_evidence_gate_v1(lessons=lessons, truth_records=truths),
        "regime_context": {
            "source": "canonical pretrade_context_v1 / existing regime owners",
            "truths_with_regime": sum(bool(_dict(row.get("pretrade_context_v1")).get("market_regime") or _dict(row.get("pretrade_context_v1")).get("regime")) for row in strict_truths),
            "unsupported_regime_fabrication": False,
        },
        "provenance_contract": {
            "current_decision_to_raw_evidence": "existing candidate/lesson/lifecycle/truth/Warehouse owners",
            "drill_down_ids": [_truth_key(row) for row in strict_truths if _truth_key(row)][:MAX_TRUTHS],
            "warehouse_owner": "AstraKnowledgeWarehouseV1",
            "compression_owner": "existing Librarian/Knowledge Compression Engine",
            "teacher_owner": "existing Teacher",
            "cortex_owner": "existing Cortex",
        },
        "historical_certification": historical_summary,
        "safety": {
            "paper_only": True,
            "read_only": True,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "production_truths_created": 0,
            "learning_rows_created": 0,
            "shadow_promoted_to_truth": False,
            "strategy_changed": False,
            "entry_policy_changed": False,
            "exit_policy_changed": False,
            "risk_sizing_capacity_changed": False,
            "mutation_performed": False,
        },
    }


__all__ = [
    "build_lesson_evidence_gate_v1",
    "build_natural_truth_lifecycle_intelligence_v1",
    "build_truth_quality_assessment_v1",
]
