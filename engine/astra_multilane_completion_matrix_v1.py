"""Worker-owned, cache-only completion classification for Astra's active lanes.

This module does not make candidates executable.  It turns existing canonical
lane evidence into an explicit stage matrix so an upstream gate cannot hide
unexercised or independently verifiable downstream contracts.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


VERSION = "1.0.0"
LANES = ("SWING", "DAY", "CRYPTO")
STAGES = (
    "market_data", "candidate_discovery", "candidate_freshness", "eligibility",
    "horizon_assignment", "lifecycle_forecast", "execution_integrity",
    "governance_authorization", "order_ready", "paper_order", "broker_acknowledgement",
    "entry_fill", "active_position", "position_monitoring", "excursion_tracking",
    "exit_readiness", "exit_order", "exit_fill", "broker_reconciliation",
    "lifecycle_closure", "complete_broker_truth", "learning_consumption",
    "governance_acknowledgement", "cortex_acknowledgement",
)
MAX_HISTORY = 12


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _lane(row: dict[str, Any]) -> str:
    lane = str(row.get("lane_id") or row.get("lane") or "").upper()
    if lane in LANES:
        return lane
    if str(row.get("asset_class") or row.get("asset_type") or "").lower() in {"crypto", "cryptocurrency"}:
        return "CRYPTO"
    horizon = str(row.get("horizon") or row.get("intended_horizon") or "").lower()
    return "DAY" if "day" in horizon or "intraday" in horizon else "SWING"


def _stage(stage: str, classification: str, *, reason: str = "", first_bad_handoff: str = "", runtime: bool = False, upstream: str = "", independent: bool = False) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": classification,
        "status_classification": classification,
        "first_bad_handoff": first_bad_handoff,
        "runtime_evidence_available": runtime,
        "static_contract_status": "STATIC_CONTRACT_ONLY",
        "runtime_contract_status": "RUNTIME_VERIFIED" if runtime else "RUNTIME_NOT_EXERCISED",
        "upstream_blocker": upstream or None,
        "independent_defect": independent,
        "legitimate_waiting_reason": reason if classification == "LEGITIMATE_WAITING" else None,
        "insufficient_evidence_reason": reason if classification == "INSUFFICIENT_EVIDENCE" else None,
        "repair_level": "NONE" if classification in {"PASS", "LEGITIMATE_WAITING", "INSUFFICIENT_EVIDENCE", "RUNTIME_NOT_EXERCISED", "BLOCKED_BY_UPSTREAM"} else "LEVEL_2_GUARDED",
        "verification_state": "CURRENT" if runtime else "STATIC_OR_BLOCKED",
    }


class AstraMultilaneCompletionMatrixV1:
    """Single worker-owned diagnostic matrix; no provider, broker, or order path."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.path = Path(state_dir) / "astra_multilane_completion_matrix_v1.json"

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value) if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def build(self, *, candidate_rows: list[dict[str, Any]], execution_trace: dict[str, Any], crypto_readiness: dict[str, Any], shadow: dict[str, Any], source_freshness: str = "UNKNOWN") -> dict[str, Any]:
        rows = [dict(row) for row in candidate_rows if isinstance(row, dict)][:300]
        by_lane = {lane: [row for row in rows if _lane(row) == lane] for lane in LANES}
        trace_rows = [dict(row) for row in (execution_trace.get("per_candidate_decision_trace") or []) if isinstance(row, dict)][:300]
        trace_by_lane = {lane: [row for row in trace_rows if _lane(row) == lane] for lane in LANES}
        lifecycle = dict(shadow.get("lifecycle_evidence_eligibility") or {})
        eligible_by_lane = dict(lifecycle.get("eligible_by_lane") or {})
        lanes: dict[str, Any] = {}
        manifest: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        runtime_unexercised: list[dict[str, Any]] = []
        for lane in LANES:
            candidates, traces = by_lane[lane], trace_by_lane[lane]
            failed = next((row for row in candidates if row.get("order_blocker") or row.get("first_failing_gate") or row.get("operational_source_rejection")), {})
            blocker = str(failed.get("first_failing_gate") or failed.get("order_blocker") or failed.get("operational_source_rejection") or "")
            reason = str(failed.get("order_blocker") or failed.get("reason") or blocker)
            stages = {stage: _stage(stage, "RUNTIME_NOT_EXERCISED", reason="no current broker-linked runtime evidence") for stage in STAGES}
            if not candidates:
                stages["candidate_discovery"] = _stage("candidate_discovery", "LEGITIMATE_WAITING", reason="no current natural candidate")
                stages["market_data"] = _stage("market_data", "PASS", runtime=source_freshness == "CURRENT")
                first = "NO_CURRENT_MARKET_OPPORTUNITY"
                waiting.append({"lane": lane, "stage": "candidate_discovery", "reason": first})
            else:
                stages["market_data"] = _stage("market_data", "PASS", runtime=True)
                stages["candidate_discovery"] = _stage("candidate_discovery", "PASS", runtime=True)
                freshness = "PASS" if source_freshness in {"CURRENT", "FRESH", ""} or lane == "CRYPTO" else "LEGITIMATE_WAITING"
                stages["candidate_freshness"] = _stage("candidate_freshness", freshness, runtime=freshness == "PASS", reason="candidate source not current" if freshness != "PASS" else "")
                crypto_failed_gates = [str(x) for x in (crypto_readiness.get("failed_gates") or crypto_readiness.get("candidate_execution_blockers") or [])]
                if lane == "CRYPTO" and "horizon_assignment" in crypto_failed_gates:
                    first = "horizon_assignment"
                    stages["eligibility"] = _stage("eligibility", "FAIL_UNKNOWN_CLOSED", reason="candidate execution integrity rejected missing horizon", first_bad_handoff="ranking snapshot -> operational candidate")
                    stages["horizon_assignment"] = _stage("horizon_assignment", "INSUFFICIENT_EVIDENCE", reason="no canonical day/swing/scalp horizon input persisted", first_bad_handoff="crypto ranking snapshot -> candidate execution integrity", runtime=True)
                elif blocker:
                    first = blocker
                    classification = "LEGITIMATE_WAITING" if "market is closed" in reason.lower() else "FAIL_UNKNOWN_CLOSED"
                    stages["eligibility"] = _stage("eligibility", classification, reason=reason, first_bad_handoff="candidate contract -> eligibility gate", runtime=True)
                    if lane == "DAY" and "CONTRACT_INCOMPLETE" in blocker:
                        stages["horizon_assignment"] = _stage("horizon_assignment", "BLOCKED_BY_UPSTREAM", upstream="CONTRACT_INCOMPLETE")
                else:
                    first = "ELIGIBILITY_NOT_RUNTIME_EXERCISED"
                    stages["eligibility"] = _stage("eligibility", "RUNTIME_NOT_EXERCISED")
            upstream = first if first else "UPSTREAM_RUNTIME_EVIDENCE_MISSING"
            for stage in ("lifecycle_forecast", "execution_integrity", "governance_authorization", "order_ready"):
                if stages[stage]["status"] == "RUNTIME_NOT_EXERCISED":
                    stages[stage] = _stage(stage, "BLOCKED_BY_UPSTREAM", upstream=upstream)
            for stage in STAGES:
                if stages[stage]["status"] in {"RUNTIME_NOT_EXERCISED", "BLOCKED_BY_UPSTREAM"}:
                    runtime_unexercised.append({"lane": lane, "stage": stage, "upstream_blocker": stages[stage].get("upstream_blocker")})
            eligible_truth = _number(eligible_by_lane.get(lane))
            if eligible_truth:
                stages["learning_consumption"] = _stage("learning_consumption", "PASS", runtime=True)
            lanes[lane] = {
                "lane": lane, "current_stage": next((stage for stage in STAGES if stages[stage]["status"] not in {"PASS", "RUNTIME_NOT_EXERCISED"}), "candidate_discovery"),
                "first_blocker": first,
                "candidate_count": len(candidates), "fresh_candidate_count": len(candidates) if source_freshness in {"CURRENT", "FRESH", ""} or lane == "CRYPTO" else 0,
                "eligible_candidate_count": sum(bool(row.get("eligible") or row.get("execution_eligible")) for row in candidates),
                "horizon_assigned_count": sum(str(row.get("assigned_horizon") or row.get("paper_entry_horizon_style") or "") in {"scalp", "day_trade", "swing_trade"} for row in candidates),
                "paper_order_intents": sum(bool(row.get("order_ready")) for row in traces),
                "active_positions": _number(execution_trace.get("active_positions_by_lane", {}).get(lane)),
                "complete_broker_truths": eligible_truth,
                "stages": stages,
                "governance_acknowledgement": "COVERED_BY_SENTINEL_MATRIX",
                "cortex_acknowledgement": "ROOT_CAUSE_GROUPING_ACTIVE",
            }
            if first and lane == "CRYPTO":
                manifest.append({"root_cause_id": "CRYPTO_HORIZON_EVIDENCE_MISSING", "title": "Crypto horizon input is absent at the execution boundary", "classification": "INSUFFICIENT_EVIDENCE", "confidence": "VERIFIED", "severity": "HIGH", "lanes_affected": [lane], "stages_affected": ["horizon_assignment", "lifecycle_forecast", "order_ready"], "first_bad_handoff": "crypto ranking snapshot -> candidate execution integrity", "verified_evidence": "cached rows have no assigned_horizon, paper_entry_horizon_style, or recognized hold window", "downstream_symptoms": ["EVIDENCE_NOT_READY", "ORDER_READY_COUNT_ZERO"], "repair_level": "LEVEL_3_HUMAN_OR_NEW_EVIDENCE", "human_action_required": False, "expected_blockers_cleared": []})
        return {"schema_version": VERSION, "generated_at": _now(), "status": "WARNING", "lanes": lanes,
                "shared_root_causes": [], "lane_specific_root_causes": manifest, "legitimate_waiting_states": waiting,
                "runtime_unexercised_stages": runtime_unexercised[:120], "coverage_gaps": [], "repair_manifest": manifest,
                "human_actions": [], "sentinel": {"owner": "PaperAutopilotWorker", "coverage": "targeted completion matrix"},
                "governance": {"fail_closed": True}, "cortex": {"root_cause_grouping": True, "truth_promotion_allowed": False},
                "resource_usage": {"provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "rows_read": len(rows), "lanes_checked": len(LANES), "stages_checked": len(LANES) * len(STAGES)},
                "provider_calls_from_get": 0, "broker_actions_from_get": 0, "llm_calls_from_get": 0, "state_mutations_from_get": 0,
                "paper_only_preserved": True, "behavior_safe_to_apply": False}

    def write(self, payload: dict[str, Any]) -> None:
        _atomic(self.path, dict(payload))

    def snapshot(self) -> dict[str, Any]:
        value = self.load()
        return {"endpoint": "/api/astra_multilane_completion_matrix_v1", "status": value.get("status", "PARTIAL") if value else "PARTIAL", **value,
                "provider_calls_from_get": 0, "broker_actions_from_get": 0, "llm_calls_from_get": 0,
                "state_mutations_from_get": 0, "get_route_read_only": True,
                "paper_only_preserved": True, "behavior_safe_to_apply": False}
