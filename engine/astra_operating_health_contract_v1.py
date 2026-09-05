"""Worker-produced, read-only operating health for the canonical paper lanes.

This contract composes already committed worker evidence.  It never contacts a
provider or broker, starts a scan, or changes a candidate, order, or position.
Its small truth-to-learning ledger makes missing acknowledgement handoffs
visible without treating open positions or order attempts as completed truths.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "1.0.0"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
MAX_LEDGER_ROWS = 200
LATENCY_DELAY_SECONDS = 300.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any, default: str = "") -> str:
    return str(value or "").strip() or default


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _timestamp(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _epoch(value: Any) -> float | None:
    stamp = _timestamp(value)
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _record_identity(row: dict[str, Any]) -> set[str]:
    return {
        value for value in (
            _text(row.get("truth_id")), _text(row.get("broker_truth_id")),
            _text(row.get("lifecycle_id")), _text(row.get("stable_key")),
        ) if value
    }


def _first_timestamp(row: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _timestamp(row.get(key))
        if value:
            return value
    return None


def _safety() -> dict[str, Any]:
    return {
        "paper_only_preserved": True, "alpaca_paper_only_preserved": True,
        "behavior_safe_to_apply": False, "live_trading_changed": False,
        "broker_behavior_changed": False, "entry_behavior_changed": False,
        "exit_behavior_changed": False, "ranking_behavior_changed": False,
        "position_sizing_changed": False, "portfolio_allocation_changed": False,
        "thresholds_changed": False, "forced_trades_enabled": False,
        "forced_exits_enabled": False, "learned_exits_enabled": False,
        "shadow_execution_enabled": False, "automatic_promotions_enabled": False,
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
    }


class AstraOperatingHealthContractV1:
    """Single bounded summary written only by ``PaperAutopilotWorker``."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "astra_operating_health_contract_v1.json"

    def snapshot(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return _dict(data)
        except (OSError, ValueError, TypeError):
            return {
                "endpoint": "/api/astra_operating_health_contract_v1",
                "status": "AWAITING_WORKER_SNAPSHOT", "lanes": {},
                "get_route_read_only": True, "worker_owned_mutations_only": True,
                **_safety(),
            }

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    @staticmethod
    def _strict_truths(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        required = ("lifecycle_id", "entry_fill_id", "exit_fill_id", "symbol")
        return [
            row for row in records
            if bool(row.get("strict_broker_truth")) or (
                _text(row.get("evidence_class") or row.get("truth_quality")).upper() == "BROKER_CONFIRMED_COMPLETE"
                and all(_text(row.get(key)) for key in required)
                and bool(_text(row.get("lane") or row.get("lane_id")))
            )
        ]

    @staticmethod
    def _handoff_ledger_row(truth: dict[str, Any], learning: list[dict[str, Any]]) -> dict[str, Any]:
        """Expose observed handoffs without turning missing timestamps into facts."""
        truth_ids = _record_identity(truth)
        related = [row for row in learning if truth_ids & _record_identity(row)]
        related.sort(key=lambda row: _epoch(_first_timestamp(row, "created_at", "timestamp", "recorded_at")) or float("inf"))
        learned = related[0] if related else {}
        persisted_at = _first_timestamp(truth, "persisted_at", "created_at", "updated_at")
        acknowledgement_at = _first_timestamp(
            truth, "learning_acknowledged_at"
        ) or _first_timestamp(learned, "learning_acknowledged_at", "acknowledged_at", "recorded_at")
        lesson_at = _first_timestamp(learned, "canonical_lesson_created_at", "lesson_created_at", "created_at") if learned.get("lesson_id") else None
        teacher_at = _first_timestamp(learned, "teacher_handoff_at", "teacher_acknowledged_at", "taught_at")
        memory_at = _first_timestamp(learned, "memory_indexed_at", "indexed_at", "memory_available_at")
        cortex_at = _first_timestamp(truth, "cortex_acknowledged_at") or _first_timestamp(learned, "cortex_acknowledged_at")
        retrieval_at = _first_timestamp(learned, "lesson_retrieved_at", "retrieved_at", "retrieval_at")
        application_at = _first_timestamp(learned, "lesson_applied_at", "applied_at", "application_at")
        outcome_at = _first_timestamp(learned, "later_outcome_linked_at", "outcome_linked_at")
        effectiveness_at = _first_timestamp(learned, "effectiveness_evaluated_at", "effectiveness_at")
        stage_defs = (
            ("strict_truth_persisted", persisted_at, True),
            ("learning_acknowledged", acknowledgement_at, bool(truth.get("learning_acknowledged") or related)),
            ("canonical_lesson_compressed", lesson_at, bool(learned.get("lesson_id"))),
            ("teacher_handoff", teacher_at, bool(learned.get("teacher_handoff_complete"))),
            ("memory_index_available", memory_at, bool(learned.get("memory_index_available"))),
            ("cortex_acknowledged", cortex_at, bool(truth.get("cortex_acknowledged") or learned.get("cortex_acknowledged"))),
            ("lesson_retrieved", retrieval_at, bool(learned.get("lesson_retrieved") or learned.get("retrieved"))),
            ("lesson_applied", application_at, bool(learned.get("lesson_applied") or learned.get("used_in_reasoning") or learned.get("used_in_experiment"))),
            ("later_outcome_linked", outcome_at, bool(learned.get("later_outcome_linked") or learned.get("outcome_linked"))),
            ("effectiveness_evaluated", effectiveness_at, bool(learned.get("effectiveness_evaluated"))),
        )
        stages: list[dict[str, Any]] = []
        previous_epoch = _epoch(persisted_at)
        first_gap = None
        last_observed_epoch = previous_epoch
        for name, stamp, known_complete in stage_defs:
            current_epoch = _epoch(stamp)
            if stamp and current_epoch is not None:
                latency = None if name == "strict_truth_persisted" or previous_epoch is None else round(max(0.0, current_epoch - previous_epoch), 3)
                state = "OBSERVED_DELAYED" if latency is not None and latency > LATENCY_DELAY_SECONDS else "OBSERVED"
                if state == "OBSERVED_DELAYED" and first_gap is None:
                    first_gap = name
                stages.append({"stage": name, "status": state, "timestamp": stamp, "latency_from_previous_seconds": latency})
                previous_epoch = current_epoch
                last_observed_epoch = current_epoch
            else:
                state = "ACKNOWLEDGED_TIMESTAMP_UNOBSERVED" if known_complete else "UNKNOWN_UNOBSERVED"
                stages.append({"stage": name, "status": state, "timestamp": None, "latency_from_previous_seconds": None})
                if first_gap is None:
                    first_gap = name
        total_latency = None
        if _epoch(persisted_at) is not None and last_observed_epoch is not None and last_observed_epoch >= _epoch(persisted_at):
            total_latency = round(last_observed_epoch - _epoch(persisted_at), 3)
        truth_id = _text(truth.get("truth_id") or truth.get("stable_key") or truth.get("lifecycle_id"))
        observed_stages = {row["stage"] for row in stages if str(row.get("status") or "").startswith("OBSERVED")}
        utilization_state = (
            "EFFECTIVENESS_EVALUATED" if "effectiveness_evaluated" in observed_stages else
            "OUTCOME_LINKED" if "later_outcome_linked" in observed_stages else
            "LESSON_APPLIED" if "lesson_applied" in observed_stages else
            "LESSON_RETRIEVED" if "lesson_retrieved" in observed_stages else
            "CONNECTED_NOT_YET_RETRIEVED"
        )
        return {
            "truth_id": truth_id,
            "lane": _text(truth.get("lane") or truth.get("lane_id")).upper(),
            "symbol": _text(truth.get("symbol")).upper(),
            "lifecycle_id": truth.get("lifecycle_id"),
            "stages": stages,
            "related_learning_record_count": len(related),
            "first_delayed_or_unobserved_handoff": first_gap or "NONE_OBSERVED",
            "total_observed_latency_seconds": total_latency,
            "latency_observability": "PARTIAL" if first_gap else "COMPLETE",
            "utilization_state": utilization_state,
        }

    def build(
        self,
        *,
        multilane: dict[str, Any],
        worker_state: dict[str, Any],
        continuous: dict[str, Any],
        sentinel: dict[str, Any],
        cortex: dict[str, Any] | None = None,
        truth_records: list[dict[str, Any]] | None = None,
        learning_records: list[dict[str, Any]] | None = None,
        canonical_capacity_facts: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        matrix = _dict(multilane)
        truths = self._strict_truths([_dict(row) for row in (truth_records or [])])
        learning = [_dict(row) for row in (learning_records or [])]
        learned_ids = set().union(*(_record_identity(row) for row in learning)) if learning else set()
        capacity_facts = _dict(canonical_capacity_facts)
        lanes: dict[str, Any] = {}
        for lane in LANES:
            row = _dict(_dict(matrix.get("lanes")).get(lane))
            capacity_fact = _dict(capacity_facts.get(lane))
            lane_truths = [truth for truth in truths if _text(truth.get("lane") or truth.get("lane_id")).upper() == lane]
            consumed = [truth for truth in lane_truths if _record_identity(truth) & learned_ids]
            blocker = _text(row.get("first_blocker"), "CANDIDATE_OBSERVATION_PENDING")
            valid_wait = blocker in {
                "CANDIDATE_OBSERVATION_PENDING", "NO_CURRENT_MARKET_OPPORTUNITY", "MARKET_CLOSED",
                "lane_activation", "PENDING_LANE_ACTIVATION", "CANDIDATE_TIMESTAMP_STALE",
                "CANDIDATE_ELIGIBLE_AWAITING_FULL_CYCLE",
            } or _text(row.get("first_blocker_validity")) in {
                "VALID_SAFETY_REJECTION",
                "VALID_STRATEGY_REJECTION",
                "VALID_SCHEDULING_WAIT",
                "VALID_MARKET_DATA_LIMITATION",
            }
            capacity_exhausted = (
                bool(capacity_fact.get("authority_current"))
                and not bool(capacity_fact.get("allowed"))
                and _text(capacity_fact.get("capacity_decision")) == "LANE_RESERVE_EXHAUSTED"
                and _text(capacity_fact.get("lane_reserve_status")) == "LANE_RESERVE_EXHAUSTED"
                and not bool(capacity_fact.get("reserve_available"))
                and blocker == "capacity_concentration"
            )
            if capacity_exhausted:
                blocker_validity = "VALID_CAPACITY_WAIT"
                waiting_state = "LEGITIMATE_WAIT"
            else:
                blocker_validity = row.get("first_blocker_validity") or ("VALID_SAFETY_WAIT" if valid_wait else "UNCLASSIFIED_FAIL_CLOSED")
                waiting_state = "LEGITIMATE_WAIT" if valid_wait else "DEFECT_OR_UNCLASSIFIED"
            lanes[lane] = {
                "lane": lane, "current_lifecycle_stage": row.get("current_stage") or "candidate_discovery",
                "first_causal_blocker": blocker, "blocker_source": "astra_multilane_completion_matrix_v1",
                "blocker_validity": blocker_validity,
                "waiting_state": waiting_state,
                "capacity_fact_provenance": {
                    "authority_current": bool(capacity_fact.get("authority_current")),
                    "capacity_decision": _text(capacity_fact.get("capacity_decision")) or None,
                    "drill_down_ref": f"canonical_capacity_facts.{lane}",
                } if capacity_fact else None,
                "candidate_count": _number(row.get("candidate_count")),
                "fresh_candidate_count": _number(row.get("fresh_candidate_count")),
                "eligible_candidate_count": _number(row.get("eligible_candidate_count")),
                "order_ready_count": _number(row.get("paper_order_intents")),
                "broker_confirmed_active_positions": _number(row.get("broker_confirmed_active_positions") or row.get("active_positions")),
                "managed_capacity_positions": _number(row.get("managed_capacity_positions")),
                "legacy_unlinked_positions_excluded": _number(row.get("legacy_unlinked_positions_excluded_from_learning_capacity")),
                "strict_truth_count": len(lane_truths), "truths_awaiting_learning": len(lane_truths) - len(consumed),
                "truths_consumed_by_learning": len(consumed),
                "cortex_acknowledged": bool(consumed), "governance_acknowledged": bool(consumed),
                "candidate_observation_state": row.get("candidate_observation_state"),
            }
        root_causes = list(_dict(sentinel).get("active_root_causes") or [])
        campaign = _dict(_dict(continuous).get("current_campaign"))
        control_agree = not any(str(root.get("severity") or "").upper() in {"CRITICAL", "HIGH"} for root in root_causes)
        status = "PASS" if control_agree else "WARNING"
        ledger = []
        for truth in truths[-MAX_LEDGER_ROWS:]:
            truth_id = _text(truth.get("truth_id") or truth.get("stable_key") or truth.get("lifecycle_id"))
            consumed = bool(_record_identity(truth) & learned_ids)
            handoff = self._handoff_ledger_row(truth, learning)
            handoff_times = {row["stage"]: row.get("timestamp") for row in handoff.get("stages", [])}
            handoff.update({
                "evidence_registration_time": truth.get("evidence_registered_at"),
                "consumer": "canonical_lifecycle_learning",
                "consumption_result": "CONSUMED" if consumed else "AWAITING_LEARNING",
                "learning_acknowledgement_time": handoff_times.get("learning_acknowledged") if consumed else None,
                "cortex_acknowledgement_time": handoff_times.get("cortex_acknowledged") if consumed else None,
                "governance_acknowledgement_time": truth.get("governance_acknowledged_at") if consumed else None,
                "failure_reason": None if consumed else "awaiting_authoritative_learning_consumer",
                "retry_status": "NO_AUTOMATIC_RETRY",
                "final_state": "CONSUMED" if consumed else "PERSISTED_AWAITING_CONSUMPTION",
            })
            ledger.append(handoff)
        utilization_states = {
            state: sum(1 for row in ledger if row.get("utilization_state") == state)
            for state in (
                "CONNECTED_NOT_YET_RETRIEVED", "LESSON_RETRIEVED", "LESSON_APPLIED",
                "OUTCOME_LINKED", "EFFECTIVENESS_EVALUATED",
            )
        }
        return {
            "endpoint": "/api/astra_operating_health_contract_v1", "suite": "Astra Operating Health Contract V1",
            "version": VERSION, "generated_at": _now(), "status": status, "lanes": lanes,
            "strict_truth_total": len(truths), "truths_consumed_by_learning_total": sum(1 for truth in truths if _record_identity(truth) & learned_ids),
            "truth_to_learning_ledger": ledger, "truth_to_learning_ledger_bounded": True,
            "learning_utilization_summary": {
                "bounded": True,
                "truths_tracked": len(ledger),
                "states": utilization_states,
                "natural_effectiveness_evidence_required": True,
            },
            "sentinel_status": _dict(sentinel).get("status"), "governance_status": _dict(continuous).get("status"),
            "cortex_status": _dict(cortex).get("status"), "control_plane_agreement": control_agree,
            "control_plane_disagreement_reason": None if control_agree else "sentinel_has_high_or_critical_root_cause; governance remains fail-closed for execution",
            "governance_first_causal_blocker": campaign.get("first_causal_blocker"),
            "monitoring_coverage": "BOUNDED_WORKER_COMMITTED", "get_route_read_only": True,
            "worker_owned_mutations_only": True, **_safety(),
        }
