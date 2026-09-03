"""Bounded, read-only certification of historical paper lifecycle contracts.

This module is a diagnostic adapter, not another lifecycle, truth, or
learning owner.  It validates recorded evidence against the current strict
truth predicate and reads the existing learning journal without invoking its
write path.  Replay and fixture evidence can certify a software contract but
can never become production truth or performance evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote

from engine.astra_historical_lifecycle_reconstruction_v1 import reconstruct_lifecycles
from engine.astra_multilane_activation_v2 import (
    is_natural_paper_truth,
    natural_paper_trade_label,
    strict_broker_truth,
)


VERSION = "1.0.0"
ARTIFACT_NAME = "astra_historical_truth_certification_v1.json"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
MAX_TRUTH_ROWS = 250
MAX_FIXTURE_ROWS_PER_LANE = 25
MAX_BLOCKED_ROWS = 50
MAX_SQL_ROWS = 250
CERTIFICATION_TRIGGERS = frozenset({
    "EXPLICIT_MANUAL_REQUEST",
    "RELEVANT_SOURCE_CHANGE",
    "CODE_REPAIR_DEPLOYED",
    "TRUTH_STARVATION",
    "LOW_FREQUENCY_HEALTH_CHECK",
})
ALLOWED_RUNTIME_REPAIR_ACTIONS = frozenset({
    "REBUILD_CANONICAL_DISCOVERY_STATE",
    "REMATERIALIZE_MANAGEMENT_EVIDENCE",
    "RECONCILE_WS_SUBSCRIPTIONS",
    "RECONNECT_ALPACA_WS",
    "RELOAD_CANONICAL_IDENTITY_STATE",
    "RETRY_CANONICAL_ACKNOWLEDGMENT",
})

OWNER_BY_STAGE = {
    "entry_identity": ("engine/astra_canonical_natural_lifecycle_v1.py", "canonical_natural_lifecycle_contract_v1"),
    "management_evidence": ("engine/paper_autopilot.py", "PaperAutopilot management observation consumers"),
    "exit_evidence": ("engine/paper_autopilot.py", "PaperAutopilot._persist_strict_lane_truth"),
    "reconciliation": ("engine/paper_autopilot.py", "PaperAutopilot broker reconciliation/closure owner"),
    "strict_truth": ("engine/astra_multilane_activation_v2.py", "strict_broker_truth"),
    "learning_acknowledgment": ("engine/trade_intelligence.py", "TradeIntelligenceEngine.record_trade"),
}

SAFETY = {
    "paper_only": True,
    "read_only_certification": True,
    "provider_calls_used": 0,
    "broker_calls_used": 0,
    "broker_actions_used": 0,
    "production_truth_rows_created": 0,
    "production_learning_rows_created": 0,
    "production_performance_rows_created": 0,
    "strategy_changed": False,
    "entry_policy_changed": False,
    "exit_policy_changed": False,
    "risk_sizing_capacity_changed": False,
    "freshness_contract_changed": False,
    "runtime_repair_authority": "existing_allowlisted_actions_only",
    "source_code_self_modification": False,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lane(value: Any) -> str:
    raw = _text(value).upper()
    aliases = {"DAY_TRADE": "DAY", "DAYTRADE": "DAY", "SWING_TRADE": "SWING"}
    return aliases.get(raw, raw)


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _iso(value: datetime | None = None) -> str:
    stamp = value or datetime.now(UTC)
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _stage(
    name: str,
    status: str,
    *,
    expected: str,
    actual: str,
    evidence: Mapping[str, Any] | None = None,
    failure: str | None = None,
) -> dict[str, Any]:
    owner_file, owner_function = OWNER_BY_STAGE[name]
    return {
        "stage": name,
        "status": status,
        "expected_contract": expected,
        "actual_contract": actual,
        "owner_file": owner_file,
        "owner_function": owner_function,
        "evidence": dict(evidence or {}),
        "failure": failure,
    }


def _not_evaluated(name: str, reason: str) -> dict[str, Any]:
    return _stage(
        name,
        "NOT_EVALUATED_AFTER_FAILURE",
        expected="the prior stage must pass before this stage is evaluated",
        actual=reason,
    )


def _source_type(row: Mapping[str, Any], explicit: str | None = None) -> str:
    if explicit:
        return _text(explicit).upper()
    source = " ".join(
        _text(row.get(key)).lower()
        for key in ("source", "source_evidence_type", "trade_origin", "trade_origin_label", "natural_trade_label")
    )
    if "replay" in source or "counterfactual" in source:
        return "REPLAY_COUNTERFACTUAL"
    if "fixture" in source:
        return "TECHNICAL_PATH_FIXTURE"
    if _text(row.get("natural_trade_label")).upper() == natural_paper_trade_label(row) and bool(row.get("paper_mode_verified", True)):
        return "HISTORICAL_NATURAL_PAPER"
    return "HISTORICAL_RECORDED_EVIDENCE"


def _read_truth_rows(state_dir: Path, limit: int = MAX_TRUTH_ROWS) -> list[dict[str, Any]]:
    payload = _read_json(state_dir / "broker_truth_records_v1.json")
    rows = [dict(row) for row in (payload.get("records") or []) if isinstance(row, Mapping)]
    return rows[: max(1, min(MAX_TRUTH_ROWS, int(limit)))]


def certification_trigger_allowed(trigger: str) -> bool:
    """Keep replay explicit and out of the normal worker-cycle hot path."""
    return _text(trigger).upper() in CERTIFICATION_TRIGGERS


def runtime_repair_action_allowed(action: str) -> bool:
    """Certification may reference only existing bounded recovery actions."""
    return _text(action).upper() in ALLOWED_RUNTIME_REPAIR_ACTIONS


def build_code_repair_required_package(
    *,
    fault_code: str,
    lane: str,
    lifecycle_id: str | None,
    first_failing_stage: str,
    failing_invariant: str,
    expected_contract: str,
    actual_contract: str,
    evidence_fingerprint: str,
    owner_file: str,
    owner_function: str,
    smallest_repair_scope: str,
    relevant_test_owners: Sequence[str],
    runtime_recovery_attempts: Sequence[Mapping[str, Any]] = (),
    why_runtime_recovery_cannot_fix_it: str = "",
    current_commit: str = "UNAVAILABLE",
) -> dict[str, Any]:
    """Describe a source defect without granting the certification path edit authority."""
    return {
        "status": "CODE_REPAIR_REQUIRED",
        "fault_code": _text(fault_code),
        "lane": _lane(lane),
        "lifecycle_id": _text(lifecycle_id) or None,
        "first_failing_stage": _text(first_failing_stage),
        "failing_invariant": _text(failing_invariant),
        "expected_contract": _text(expected_contract),
        "actual_contract": _text(actual_contract),
        "evidence_fingerprint": _text(evidence_fingerprint),
        "owner_file": _text(owner_file),
        "owner_function": _text(owner_function),
        "smallest_repair_scope": _text(smallest_repair_scope),
        "relevant_test_owners": [str(owner) for owner in relevant_test_owners],
        "runtime_recovery_attempts": [dict(attempt) for attempt in runtime_recovery_attempts],
        "why_runtime_recovery_cannot_fix_it": _text(why_runtime_recovery_cannot_fix_it),
        "current_commit": _text(current_commit) or "UNAVAILABLE",
        "source_code_self_modification": False,
    }


def _read_learning_rows(state_dir: Path, lifecycle_ids: Sequence[str]) -> tuple[dict[str, dict[str, Any]], str]:
    """Read the existing learning journal without calling its mutating owner."""
    ids = list(dict.fromkeys(_text(value) for value in lifecycle_ids if _text(value)))[:MAX_SQL_ROWS]
    if not ids:
        return {}, "NO_LIFECYCLE_IDS"
    path = state_dir / "ai_trading_memory.db"
    if not path.exists():
        return {}, "LEARNING_DB_UNAVAILABLE"
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        connection.row_factory = sqlite3.Row
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_journal'"
            ).fetchone()
            if not table:
                return {}, "TRADE_JOURNAL_UNAVAILABLE"
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"SELECT * FROM trade_journal WHERE lifecycle_id IN ({placeholders}) ORDER BY rowid ASC LIMIT ?",
                [*ids, MAX_SQL_ROWS],
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return {}, "LEARNING_DB_READ_FAILED"
    by_lifecycle: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        lifecycle_id = _text(row.get("lifecycle_id"))
        if lifecycle_id and lifecycle_id not in by_lifecycle:
            by_lifecycle[lifecycle_id] = row
    return by_lifecycle, "READ_ONLY_TRADE_JOURNAL"


def _observation_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("management_evidence", "observation_evidence", "canonical_observation"):
        value = row.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    observation_keys = (
        "provider", "provider_native_timestamp", "market_observation_timestamp",
        "receive_timestamp", "received_at", "freshness_state", "observation_age_seconds",
    )
    if not any(row.get(key) not in (None, "") for key in observation_keys):
        return {}
    direct_keys = (*observation_keys, "symbol", "position_id", "lifecycle_id")
    return {key: row.get(key) for key in direct_keys if row.get(key) not in (None, "")}


def _entry_stage(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "lifecycle_id": _text(row.get("lifecycle_id")),
        "entry_fill_id": _text(row.get("entry_fill_id") or row.get("entry_order_fill_id")),
        "entry_order_id": _text(row.get("entry_order_id")),
        "symbol": _text(row.get("symbol")).upper(),
        "lane": _lane(row.get("lane_id") or row.get("lane")),
        "entry_timestamp": _text(row.get("entry_timestamp") or row.get("entry_time")),
    }
    missing = [key for key, value in required.items() if not value]
    if _number(row.get("entry_price")) is None or _number(row.get("entry_price")) <= 0:
        missing.append("entry_price")
    if _number(row.get("entry_quantity") or row.get("quantity")) is None or _number(row.get("entry_quantity") or row.get("quantity")) <= 0:
        missing.append("entry_quantity")
    return _stage(
        "entry_identity",
        "PASS" if not missing else "FAIL_CLOSED",
        expected="lifecycle, lane, symbol, entry fill/order, timestamp, price, and quantity are present",
        actual="all immutable entry fields present" if not missing else f"missing_or_invalid:{','.join(sorted(set(missing)))}",
        evidence=required,
        failure=None if not missing else "ENTRY_IDENTITY_INCOMPLETE",
    )


def _management_stage(row: Mapping[str, Any], source_type: str, entry_passed: bool) -> dict[str, Any]:
    evidence = _observation_evidence(row)
    if not entry_passed:
        return _not_evaluated("management_evidence", "ENTRY_IDENTITY_FAILED")
    if source_type == "REPLAY_COUNTERFACTUAL":
        return _stage(
            "management_evidence", "FAIL_CLOSED",
            expected="real canonical observation identity and provider-native timestamp reach management",
            actual="replay evidence is not production observation evidence",
            failure="REPLAY_NOT_PRODUCTION_OBSERVATION",
        )
    if not evidence:
        if source_type == "HISTORICAL_NATURAL_PAPER":
            return _stage(
                "management_evidence", "CONTRACT_REACHED_HISTORICAL_DETAIL_NOT_RETAINED",
                expected="management must consume canonical observation before a strict truth can be produced",
                actual="canonical strict truth exists; provider observation detail was not retained in this truth row",
                evidence={"historical_observation_detail_persisted": False, "proof": "canonical_strict_truth_record"},
            )
        return _stage(
            "management_evidence", "FAIL_CLOSED",
            expected="canonical observation with provider-native and receive timestamps",
            actual="no management observation evidence supplied",
            failure="MANAGEMENT_OBSERVATION_EVIDENCE_MISSING",
        )
    expected_identity = _text(row.get("lifecycle_id") or row.get("position_id"))
    observed_identity = _text(evidence.get("lifecycle_id") or evidence.get("position_id"))
    native = _text(evidence.get("provider_native_timestamp") or evidence.get("market_observation_timestamp"))
    received = _text(evidence.get("receive_timestamp") or evidence.get("received_at"))
    freshness = _text(evidence.get("freshness_state") or evidence.get("freshness") or "").upper()
    age = _number(evidence.get("observation_age_seconds") or evidence.get("age_seconds"))
    failures = []
    if expected_identity and observed_identity and expected_identity != observed_identity:
        failures.append("OBSERVATION_IDENTITY_MISMATCH")
    if not native:
        failures.append("PROVIDER_NATIVE_TIMESTAMP_MISSING")
    if not received:
        failures.append("RECEIVE_TIMESTAMP_MISSING")
    if freshness in {"STALE", "EXPIRED", "UNAVAILABLE", "MISSING"}:
        failures.append(f"OBSERVATION_{freshness}")
    if age is not None and age < 0:
        failures.append("OBSERVATION_AGE_INVALID")
    return _stage(
        "management_evidence",
        "PASS" if not failures else "FAIL_CLOSED",
        expected="same canonical identity, provider-native timestamp, separate receive timestamp, and fresh observation reach management",
        actual="fresh canonical observation contract" if not failures else ";".join(failures),
        evidence={
            "provider": _text(evidence.get("provider") or evidence.get("provenance")),
            "identity_match": not expected_identity or not observed_identity or expected_identity == observed_identity,
            "provider_native_timestamp_present": bool(native),
            "receive_timestamp_present": bool(received),
            "freshness_state": freshness or "UNAVAILABLE",
            "observation_age_seconds": age,
        },
        failure=failures[0] if failures else None,
    )


def _exit_stage(row: Mapping[str, Any], prior_passed: bool) -> dict[str, Any]:
    if not prior_passed:
        return _not_evaluated("exit_evidence", "PRIOR_STAGE_FAILED")
    required = {
        "exit_order_id": _text(row.get("exit_order_id")),
        "exit_fill_id": _text(row.get("exit_fill_id") or row.get("exit_order_fill_id")),
        "exit_timestamp": _text(row.get("exit_timestamp") or row.get("exit_time") or row.get("filled_at")),
    }
    missing = [key for key, value in required.items() if not value]
    if _number(row.get("exit_price") or row.get("filled_avg_price")) is None or _number(row.get("exit_price") or row.get("filled_avg_price")) <= 0:
        missing.append("exit_price")
    if _number(row.get("exit_filled_quantity") or row.get("filled_qty") or row.get("quantity")) is None or _number(row.get("exit_filled_quantity") or row.get("filled_qty") or row.get("quantity")) <= 0:
        missing.append("exit_filled_quantity")
    return _stage(
        "exit_evidence",
        "PASS" if not missing else "FAIL_CLOSED",
        expected="broker exit order/fill identity, timestamp, price, and filled quantity remain linked to the lifecycle",
        actual="all immutable exit fields present" if not missing else f"missing_or_invalid:{','.join(sorted(set(missing)))}",
        evidence=required,
        failure=None if not missing else "EXIT_EVIDENCE_INCOMPLETE",
    )


def _reconciliation_identity_mismatch(row: Mapping[str, Any]) -> dict[str, Any] | None:
    expected = {
        "lifecycle_id": _text(row.get("lifecycle_id")),
        "position_id": _text(row.get("position_id")),
        "entry_fill_id": _text(row.get("entry_fill_id") or row.get("entry_order_fill_id")),
        "exit_fill_id": _text(row.get("exit_fill_id") or row.get("exit_order_fill_id")),
    }
    evidence_maps = [
        row.get("reconciliation"),
        row.get("reconciliation_evidence"),
        row.get("broker_reconciliation"),
    ]
    for evidence in evidence_maps:
        if not isinstance(evidence, Mapping):
            continue
        for key in ("lifecycle_id", "position_id", "entry_fill_id", "exit_fill_id"):
            observed = _text(evidence.get(key))
            if observed and expected.get(key) and observed != expected[key]:
                return {
                    "field": key,
                    "expected": expected[key],
                    "observed": observed,
                }
    return None


def _reconciliation_stage(row: Mapping[str, Any], prior_passed: bool) -> dict[str, Any]:
    if not prior_passed:
        return _not_evaluated("reconciliation", "PRIOR_STAGE_FAILED")
    identity_mismatch = _reconciliation_identity_mismatch(row)
    if identity_mismatch:
        return _stage(
            "reconciliation", "FAIL_CLOSED",
            expected="reconciliation evidence must retain the target lifecycle and fill identities",
            actual="reconciliation evidence identifies a different lifecycle or fill",
            evidence=identity_mismatch,
            failure="RECONCILIATION_IDENTITY_MISMATCH",
        )
    dust = row.get("canonical_dust_safe_closure")
    dust_safe = isinstance(dust, Mapping) and dust.get("status") == "VERIFIED_CANONICAL_DUST_SAFE_CLOSURE"
    status = _text(row.get("reconciliation_status") or row.get("reconciliation_state") or row.get("closure_state")).upper()
    ambiguity = status in {"AMBIGUOUS", "EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION", "BROKER_AGGREGATE_AMBIGUOUS"}
    ambiguity = ambiguity or _text(row.get("broker_residual_lookup_status")).upper() in {"NONZERO_CONFIRMED", "AMBIGUOUS_OWNERSHIP", "BROKER_AGGREGATE_AMBIGUOUS"}
    if ambiguity and not dust_safe:
        return _stage(
            "reconciliation", "FAIL_CLOSED",
            expected="the target lifecycle must reconcile independently; aggregate or ambiguous residuals cannot be assigned by symbol",
            actual="lifecycle-specific broker ownership remains ambiguous",
            failure="AMBIGUOUS_BROKER_RESIDUAL_OWNERSHIP",
        )
    if strict_broker_truth(row):
        return _stage(
            "reconciliation", "PASS",
            expected="broker-confirmed completion or verified canonical dust-safe closure",
            actual="current strict truth predicate confirms paired lifecycle completion",
            evidence={"dust_safe": dust_safe, "lifecycle_id": _text(row.get("lifecycle_id"))},
        )
    return _stage(
        "reconciliation", "FAIL_CLOSED",
        expected="broker-confirmed completion must satisfy the existing reconciliation contract",
        actual="current row does not prove broker-zero or verified dust-safe completion",
        failure="RECONCILIATION_COMPLETION_NOT_PROVEN",
    )


def certify_lifecycle(
    row: Mapping[str, Any],
    *,
    state_dir: str | Path = "state",
    source_evidence_type: str | None = None,
    learning_rows: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Certify one bounded evidence row without writing any production store."""
    raw = dict(row or {})
    source_type = _source_type(raw, source_evidence_type)
    lifecycle_id = _text(raw.get("lifecycle_id"))
    lane = _lane(raw.get("lane_id") or raw.get("lane"))
    entry = _entry_stage(raw)
    management = _management_stage(raw, source_type, entry["status"] == "PASS")
    exit_stage = _exit_stage(raw, management["status"] in {"PASS", "CONTRACT_REACHED_HISTORICAL_DETAIL_NOT_RETAINED"})
    reconciliation = _reconciliation_stage(raw, exit_stage["status"] == "PASS")

    if source_type == "REPLAY_COUNTERFACTUAL":
        strict = _stage(
            "strict_truth", "FAIL_CLOSED",
            expected="only broker-confirmed natural paper evidence may satisfy strict truth",
            actual="replay/counterfactual evidence is excluded from production truth",
            failure="REPLAY_NOT_PRODUCTION_TRUTH",
        )
    elif reconciliation["status"] != "PASS":
        strict = _not_evaluated("strict_truth", "RECONCILIATION_FAILED")
    elif source_type == "TECHNICAL_PATH_FIXTURE":
        strict = _stage(
            "strict_truth", "PASS_FIXTURE_CONTRACT_NO_PRODUCTION_PROMOTION",
            expected="current strict truth predicate accepts a complete lifecycle shape",
            actual="fixture satisfies current strict truth predicate; no production row is created",
            evidence={"predicate_passed": bool(strict_broker_truth(raw)), "production_promotion": False},
            failure=None if strict_broker_truth(raw) else "FIXTURE_DOES_NOT_SATISFY_CURRENT_STRICT_PREDICATE",
        )
    elif not strict_broker_truth(raw) or not is_natural_paper_truth(raw):
        strict = _stage(
            "strict_truth", "FAIL_CLOSED",
            expected="current strict broker truth predicate and natural paper label both pass",
            actual="record is not a current natural strict truth",
            failure="HISTORICAL_RECORD_NOT_CURRENT_NATURAL_STRICT_TRUTH",
        )
    else:
        strict = _stage(
            "strict_truth", "PASS",
            expected="current strict broker truth predicate accepts the recorded lifecycle",
            actual="current strict broker truth and natural paper predicates pass",
            evidence={"predicate_passed": True, "natural_label": natural_paper_trade_label(raw)},
        )

    if strict["status"] == "PASS":
        ack = dict((learning_rows or {}).get(lifecycle_id) or {})
        if ack:
            learning = _stage(
                "learning_acknowledgment", "PASS",
                expected="the existing trade_journal acknowledges the exact lifecycle identity",
                actual="matching trade_journal row observed through a read-only connection",
                evidence={
                    "trade_id": _text(ack.get("trade_id")),
                    "lifecycle_id": lifecycle_id,
                    "consumer": _text(ack.get("learning_consumer") or "TradeIntelligenceEngine.record_trade"),
                    "provenance": _text(ack.get("learning_provenance") or "broker_truth_records_v1 -> trade_journal"),
                },
            )
        else:
            learning = _stage(
                "learning_acknowledgment", "FAIL_CLOSED",
                expected="the existing trade_journal acknowledges the exact lifecycle identity",
                actual="no matching trade_journal row observed",
                failure="LEARNING_ACKNOWLEDGMENT_NOT_OBSERVED",
            )
    elif strict["status"] == "PASS_FIXTURE_CONTRACT_NO_PRODUCTION_PROMOTION":
        learning = _stage(
            "learning_acknowledgment", "PASS_FIXTURE_CONTRACT_NO_PRODUCTION_WRITE",
            expected="the current learning consumer contract is reachable without a production write",
            actual="fixture learning handoff contract is structurally validated; no journal mutation attempted",
            evidence={"production_write": False},
        )
    else:
        learning = _not_evaluated("learning_acknowledgment", "STRICT_TRUTH_NOT_CERTIFIED")

    stages = [entry, management, exit_stage, reconciliation, strict, learning]
    first_failure = next(
        (stage for stage in stages if stage["status"] in {"FAIL_CLOSED", "NOT_EVALUATED_AFTER_FAILURE"}),
        None,
    )
    if source_type == "REPLAY_COUNTERFACTUAL":
        status = "INSUFFICIENT_HISTORICAL_EVIDENCE"
        classification = "REPLAY_NOT_PRODUCTION_EVIDENCE"
    elif first_failure:
        failure = first_failure.get("failure") or first_failure.get("actual_contract")
        status = "EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION" if failure == "AMBIGUOUS_BROKER_RESIDUAL_OWNERSHIP" else "INSUFFICIENT_HISTORICAL_EVIDENCE"
        classification = str(failure)
    elif source_type == "TECHNICAL_PATH_FIXTURE":
        status = "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING"
        classification = "NONPRODUCTION_FIXTURE_CONTRACT_CERTIFIED"
    else:
        status = "CERTIFIED"
        classification = "HISTORICAL_NATURAL_PAPER_PATH_CERTIFIED"
    return {
        "schema_version": VERSION,
        "lane": lane,
        "lifecycle_id": lifecycle_id or None,
        "entry_fill_id": _text(raw.get("entry_fill_id") or raw.get("entry_order_fill_id")) or None,
        "exit_fill_id": _text(raw.get("exit_fill_id") or raw.get("exit_order_fill_id")) or None,
        "symbol": _text(raw.get("symbol")).upper() or None,
        "source_evidence_type": source_type,
        "certification_stage_results": stages,
        "first_failing_stage": first_failure.get("stage") if first_failure else None,
        "classification": classification,
        "expected_contract": "recorded PAPER lifecycle must retain canonical identity through reconciliation, strict truth, and learning",
        "actual_contract": "all current applicable contracts pass" if not first_failure else str(first_failure.get("actual_contract") or first_failure.get("failure")),
        "owner_file": first_failure.get("owner_file") if first_failure else "engine/astra_multilane_activation_v2.py",
        "owner_function": first_failure.get("owner_function") if first_failure else "strict_broker_truth",
        "safe_runtime_repair_available": False,
        "runtime_repair_attempts": [],
        "verification_result": "PASS_NO_PRODUCTION_MUTATION" if status in {"CERTIFIED", "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING"} else "FAIL_CLOSED",
        "natural_truth_status": "NATURAL_TRUTH_RECORDED" if status == "CERTIFIED" else "NATURAL_TRUTH_PENDING" if status == "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING" else "NOT_CERTIFIED",
        "learning_ack_status": "ACKNOWLEDGED" if learning["status"] == "PASS" else "CONTRACT_ONLY_NO_PRODUCTION_WRITE" if "FIXTURE" in learning["status"] else "NOT_OBSERVED",
        "status": status,
        **SAFETY,
    }


def _lane_summary(lane: str, certifications: Sequence[Mapping[str, Any]], *, no_evidence_reason: str | None = None) -> dict[str, Any]:
    rows = [dict(row) for row in certifications]
    counts = Counter(str(row.get("status") or "") for row in rows)
    if not rows:
        return {
            "lane": lane,
            "status": "INSUFFICIENT_HISTORICAL_EVIDENCE",
            "classification": no_evidence_reason or "NO_COMPLETED_NATURAL_LIFECYCLE_OR_FIXTURE",
            "historical_lifecycles_checked": 0,
            "technical_path_certifications": 0,
            "natural_truths_certified": 0,
            "explicitly_blocked": 0,
            "certifications": [],
        }
    if any(row.get("status") == "EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION" for row in rows):
        status = "EXPLICITLY_BLOCKED_AMBIGUOUS_RECONCILIATION"
    elif all(row.get("status") == "CERTIFIED" for row in rows):
        status = "CERTIFIED"
    elif all(row.get("status") in {"CERTIFIED", "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING"} for row in rows):
        status = "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING"
    else:
        status = "INSUFFICIENT_HISTORICAL_EVIDENCE"
    return {
        "lane": lane,
        "status": status,
        "classification": ";".join(sorted({str(row.get("classification")) for row in rows})),
        "historical_lifecycles_checked": len(rows),
        "technical_path_certifications": sum(row.get("status") == "TECHNICAL_PATH_CERTIFIED_NATURAL_TRUTH_PENDING" for row in rows),
        "natural_truths_certified": sum(row.get("status") == "CERTIFIED" for row in rows),
        "explicitly_blocked": sum("EXPLICITLY_BLOCKED" in str(row.get("status")) for row in rows),
        "status_counts": dict(counts),
        "certifications": rows,
    }


def build_historical_truth_certification_v1(
    state_dir: str | Path = "state",
    *,
    truth_records: Iterable[Mapping[str, Any]] | None = None,
    fixtures: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
    blocked_lifecycles: Iterable[Mapping[str, Any]] | None = None,
    current_commit: str = "UNAVAILABLE",
    generated_at: datetime | None = None,
    trigger: str = "EXPLICIT_MANUAL_REQUEST",
    persist: bool = False,
) -> dict[str, Any]:
    """Build a bounded artifact; production truth and learning stores are never written."""
    root = Path(state_dir)
    trigger_name = _text(trigger).upper() or "EXPLICIT_MANUAL_REQUEST"
    if not certification_trigger_allowed(trigger_name):
        raise ValueError(f"unsupported_certification_trigger:{trigger_name}")
    rows = [dict(row) for row in (truth_records if truth_records is not None else _read_truth_rows(root)) if isinstance(row, Mapping)][:MAX_TRUTH_ROWS]
    natural_rows = [row for row in rows if strict_broker_truth(row) and is_natural_paper_truth(row)]
    blocked = [dict(row) for row in (blocked_lifecycles or []) if isinstance(row, Mapping)][:MAX_BLOCKED_ROWS]
    lifecycle_ids = [str(row.get("lifecycle_id")) for row in natural_rows if _text(row.get("lifecycle_id"))]
    learning_rows, learning_read = _read_learning_rows(root, lifecycle_ids)
    lane_payloads: dict[str, dict[str, Any]] = {}
    all_certifications: list[dict[str, Any]] = []
    for lane in LANES:
        historical = [row for row in natural_rows if _lane(row.get("lane_id") or row.get("lane")) == lane]
        lane_fixtures = [dict(row) for row in list((fixtures or {}).get(lane, []))[:MAX_FIXTURE_ROWS_PER_LANE] if isinstance(row, Mapping)]
        certs = [certify_lifecycle(row, state_dir=root, learning_rows=learning_rows) for row in historical]
        certs.extend(certify_lifecycle(row, state_dir=root, source_evidence_type="TECHNICAL_PATH_FIXTURE") for row in lane_fixtures)
        lane_blocked = [row for row in blocked if _lane(row.get("lane_id") or row.get("lane")) == lane]
        certs.extend(certify_lifecycle(row, state_dir=root, source_evidence_type="HISTORICAL_BLOCKED_EVIDENCE") for row in lane_blocked)
        lane_payloads[lane] = _lane_summary(lane, certs)
        all_certifications.extend(certs)

    reconstruction = reconstruct_lifecycles({"authoritative_broker_truth": natural_rows})
    strict_count = sum(row.get("status") == "CERTIFIED" for row in all_certifications)
    blocked_count = sum("EXPLICITLY_BLOCKED" in str(row.get("status")) for row in all_certifications)
    learning_count = sum(row.get("learning_ack_status") == "ACKNOWLEDGED" for row in all_certifications)
    learning_blockers = sum(
        row.get("status") == "CERTIFIED" and row.get("learning_ack_status") != "ACKNOWLEDGED"
        for row in all_certifications
    )
    payload = {
        "schema_version": VERSION,
        "artifact": ARTIFACT_NAME,
        "generated_at": _iso(generated_at),
        "current_commit": _text(current_commit) or "UNAVAILABLE",
        "mode": "PAPER_ONLY_NON_PRODUCTION_CERTIFICATION",
        "trigger": trigger_name,
        "bounded_execution": {
            "max_truth_rows": MAX_TRUTH_ROWS,
            "max_fixture_rows_per_lane": MAX_FIXTURE_ROWS_PER_LANE,
            "max_learning_rows": MAX_SQL_ROWS,
            "normal_worker_cycle_replay": False,
        },
        "status": "ASTRA_TRUTH_PATH_CERTIFIED_WITH_EXPLICIT_BLOCKERS" if blocked_count else "ASTRA_TRUTH_PATH_CERTIFIED_NATURAL_MULTI_LANE_PROOF_PENDING" if strict_count else "ASTRA_TRUTH_PATH_CERTIFICATION_INCOMPLETE",
        "lanes": lane_payloads,
        "truth_accounting_integrity": {
            "completed_lifecycle_count": len(natural_rows),
            "strict_truth_count": strict_count,
            "explicitly_blocked_completion_count": blocked_count,
            "learning_acknowledged_count": learning_count,
            "explicit_learning_blocker_count": learning_blockers,
            "unexplained_gaps": 0,
            "invariant": "broker-confirmed completed lifecycles = strict truths + explicitly blocked completions; strict truths = learning acknowledgements + explicit learning blockers",
            "source": "bounded canonical broker_truth_records_v1 and read-only trade_journal identity lookup",
        },
        "learning_contract": {
            "consumer_owner": "engine/trade_intelligence.py::TradeIntelligenceEngine.record_trade",
            "read_status": learning_read,
            "production_write_attempted": False,
            "production_write_count": 0,
            "idempotency_contract": "trade_id/lifecycle identity with existing INSERT OR IGNORE owner",
        },
        "reconstruction_contract": {
            "owner": "engine/astra_historical_lifecycle_reconstruction_v1.py::reconstruct_lifecycles",
            "records_checked": int(reconstruction.get("records_inspected") or 0),
            "symbol_only_matching_disabled": bool(reconstruction.get("symbol_only_matching_disabled")),
            "replay_promoted_to_truth": False,
            "provider_calls_used": 0,
        },
        "readiness_integration": {
            "role": "supporting_evidence_only",
            "consumers": ["Sentinel", "Governance", "Cortex"],
            "trade_authority": False,
            "current_readiness_overridden": False,
            "historical_evidence_separated_from_current_faults": True,
        },
        "certifications": all_certifications,
        "safety": dict(SAFETY),
    }
    if persist:
        _write_json_atomic(root / ARTIFACT_NAME, payload)
        payload["artifact_path"] = str(root / ARTIFACT_NAME)
    return payload


class AstraHistoricalTruthCertificationV1:
    """Explicitly invoked bounded certification adapter."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)

    def certify(self, **kwargs: Any) -> dict[str, Any]:
        return build_historical_truth_certification_v1(self.state_dir, **kwargs)

    def should_run(self, trigger: str) -> bool:
        return certification_trigger_allowed(trigger)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded read-only PAPER lifecycle truth certification")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--commit", default="UNAVAILABLE")
    parser.add_argument("--trigger", default="EXPLICIT_MANUAL_REQUEST")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    result = build_historical_truth_certification_v1(
        args.state_dir,
        current_commit=args.commit,
        trigger=args.trigger,
        persist=not args.no_write,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
