"""Bounded worker-owned readiness checks and non-decision runtime recovery."""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


VERSION = "ASTRA_TRADING_HOURS_INTEGRITY_MONITOR_V1"
RECOVERY_VERSION = "ASTRA_SAFE_RUNTIME_RECOVERY_V1"
TRUTH_WATCHDOG_VERSION = "ASTRA_ALL_LANE_TRUTH_PRODUCTION_WATCHDOG_V2"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
TRUTH_PATH_STAGES = (
    "DISCOVERY",
    "CANDIDATE",
    "SHORTLIST",
    "FINALIST",
    "QUALIFIED",
    "ORDER_READY",
    "ENTRY_SUBMITTED",
    "ENTRY_FILLED",
    "OBSERVATION",
    "MANAGEMENT",
    "NATURAL_EXIT",
    "EXIT_READINESS",
    "EXIT_AUTHORITY",
    "EXIT_FILLED",
    "RECONCILIATION",
    "STRICT_TRUTH",
    "LEARNING",
)
_MATRIX_STAGE_MAP = {
    "market_data": "DISCOVERY",
    "candidate_discovery": "CANDIDATE",
    "candidate_freshness": "CANDIDATE",
    "eligibility": "QUALIFIED",
    "order_ready": "ORDER_READY",
    "paper_order": "ENTRY_SUBMITTED",
    "entry_fill": "ENTRY_FILLED",
    "position_monitoring": "MANAGEMENT",
    "exit_readiness": "EXIT_READINESS",
    "exit_order": "EXIT_AUTHORITY",
    "exit_fill": "EXIT_FILLED",
    "broker_reconciliation": "RECONCILIATION",
    "complete_broker_truth": "STRICT_TRUTH",
    "learning_consumption": "LEARNING",
}
_ET = ZoneInfo("America/New_York")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (value or []) if isinstance(row, Mapping)]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _lane(value: Any) -> str:
    lane = _text(value).upper()
    return lane if lane in LANES else ""


def _truthy(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() in {"1", "true", "yes", "ready", "qualified", "selected", "filled"}


def _event_time(*values: Any) -> str:
    """Return an existing event timestamp; never substitute monitor time."""
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return _dict(value)
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class AstraTradingReadinessV1:
    """Observes committed worker state and retries only explicit plumbing actions."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "astra_trading_readiness_v1.json"

    @staticmethod
    def _session(now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(_ET)
        minutes = current.hour * 60 + current.minute
        weekday = current.weekday() < 5
        equity_open = weekday and (9 * 60 + 30) <= minutes < 16 * 60
        preopen = weekday and (9 * 60 + 20) <= minutes < (9 * 60 + 30)
        phase = "CRYPTO_CONTINUOUS_CHECK"
        if preopen:
            phase = "PREOPEN_TRADING_READINESS"
        elif weekday and (9 * 60 + 35) <= minutes < (9 * 60 + 40):
            phase = "POST_OPEN_DISCOVERY_VERIFICATION"
        elif weekday and (12 * 60) <= minutes < (12 * 60 + 5):
            phase = "MIDDAY_INTEGRITY_CHECK"
        elif weekday and (15 * 60 + 50) <= minutes < 16 * 60:
            phase = "NEAR_CLOSE_INTEGRITY_CHECK"
        elif weekday and (16 * 60) <= minutes < (16 * 60 + 10):
            phase = "POST_CLOSE_LANE_ACCOUNTING"
        elif equity_open:
            phase = "TRADING_HOURS_INTEGRITY_CHECK"
        return {
            "timezone": "America/New_York",
            "equity_session_open": equity_open,
            "preopen_window": preopen,
            "market_local_time": current.isoformat(),
            "check_phase": phase,
        }

    @staticmethod
    def _active_observation_symbols(runtime: Mapping[str, Any]) -> set[str]:
        state = _dict(runtime.get("active_equity_fmp_observations_v1"))
        observations = _dict(state.get("observations"))
        symbols = {str(symbol).upper().strip() for symbol in observations if str(symbol).strip()}
        symbols.update(
            str(symbol).upper().strip()
            for symbol in (state.get("canonical_active_equity_symbols") or [])
            if str(symbol).strip()
        )
        return symbols

    @staticmethod
    def _position_rows(runtime: Mapping[str, Any]) -> list[dict[str, Any]]:
        capacity = _dict(runtime.get("last_evidence_capacity_snapshot"))
        recovery = _dict(runtime.get("position_lane_horizon_recovery_v1"))
        rows = _rows(capacity.get("position_rows_for_read_only_consumers"))
        rows.extend(_rows(recovery.get("positions")))
        dedup: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = _text(row.get("symbol")).upper()
            identity = _text(row.get("canonical_position_id") or row.get("lifecycle_id") or row.get("position_id"))
            key = f"{symbol}:{identity}".strip(":")
            if key:
                dedup[key] = row
        return list(dedup.values())

    @staticmethod
    def _lane_from_row(row: Mapping[str, Any]) -> str:
        return _lane(row.get("lane_id") or row.get("lane") or row.get("horizon_lane") or row.get("strategy_lane"))

    def _completion_matrix(self, runtime: Mapping[str, Any]) -> dict[str, Any]:
        matrix = _dict(runtime.get("multilane_completion_matrix"))
        if not matrix:
            matrix = _dict(runtime.get("astra_multilane_completion_matrix_v1"))
        if not matrix:
            matrix = _read(self.state_dir / "astra_multilane_completion_matrix_v1.json")
        return matrix

    @staticmethod
    def _stage_record(
        status: str = "NOT_PROVEN",
        *,
        blocker: str = "",
        source: str = "",
        observed_at: str = "",
    ) -> dict[str, str]:
        return {
            "status": status,
            "blocker": blocker,
            "source": source,
            "observed_at": observed_at,
        }

    @staticmethod
    def _matrix_stage_record(info: Mapping[str, Any], matrix_time: str) -> dict[str, str]:
        status = _text(info.get("status") or info.get("status_classification")).upper()
        blocker = _text(
            info.get("first_bad_handoff")
            or info.get("upstream_blocker")
            or info.get("insufficient_evidence_reason")
            or info.get("legitimate_waiting_reason")
        )
        if status in {"PASS", "READY", "COMPLETED", "CURRENT"}:
            mapped = "PROVEN_READY"
        elif status in {"CURRENTLY_ACTIVE", "ACTIVE", "IN_PROGRESS"}:
            mapped = "CURRENTLY_ACTIVE"
        elif status in {"LEGITIMATE_WAITING", "LEGITIMATE_WAITING_STATE", "NATURAL_WAITING", "NATURAL_WAIT"}:
            mapped = "NATURAL_WAIT"
        elif status.startswith("FAIL") or status in {"ERROR", "TECHNICAL_BLOCKED"}:
            mapped = "TECHNICAL_BLOCKED"
        elif status == "INSUFFICIENT_EVIDENCE":
            mapped = "NATURAL_WAIT" if blocker else "NOT_PROVEN"
        else:
            mapped = "NOT_PROVEN"
        return AstraTradingReadinessV1._stage_record(
            mapped,
            blocker=blocker,
            source="astra_multilane_completion_matrix_v1",
            observed_at=matrix_time,
        )

    @staticmethod
    def _set_stage(
        stages: dict[str, dict[str, str]],
        stage: str,
        status: str,
        *,
        blocker: str = "",
        source: str = "",
        observed_at: str = "",
    ) -> None:
        if stage in stages:
            stages[stage] = AstraTradingReadinessV1._stage_record(
                status,
                blocker=blocker,
                source=source,
                observed_at=observed_at,
            )

    def _stage_ledger(self, runtime: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Record bounded stage evidence without inventing event timestamps."""
        prior = _dict(previous.get("truth_production_watchdog"))
        prior_lanes = _dict(prior.get("lanes"))
        trace = _dict(runtime.get("last_execution_trace"))
        partial = _dict(_dict(runtime.get("last_cycle_summary")).get("partial_candidate_microphase"))
        trace_time = _event_time(
            trace.get("last_autopilot_cycle_at"),
            trace.get("generated_at"),
            runtime.get("last_cycle_utc"),
            runtime.get("last_full_cycle_at"),
            runtime.get("worker_cycle_completed_at"),
        )
        partial_time = _event_time(partial.get("completed_at"), partial.get("generated_at"), trace_time)
        matrix = self._completion_matrix(runtime)
        matrix_time = _event_time(matrix.get("generated_at"))
        lanes: dict[str, dict[str, Any]] = {}
        for lane in LANES:
            old = _dict(prior_lanes.get(lane))
            # Records written before the source-timestamp contract cannot be
            # trusted as event history because the old monitor used check time.
            if not isinstance(old.get("stage_status"), Mapping):
                old = {}
            stage_status = {stage: self._stage_record() for stage in TRUTH_PATH_STAGES}
            lane_matrix = _dict(_dict(matrix.get("lanes")).get(lane))
            matrix_stages = _dict(lane_matrix.get("stages"))
            for matrix_stage, watchdog_stage in _MATRIX_STAGE_MAP.items():
                info = _dict(matrix_stages.get(matrix_stage))
                if info:
                    stage_status[watchdog_stage] = self._matrix_stage_record(info, matrix_time)
            matrix_blocked = [
                (stage, item)
                for stage, item in stage_status.items()
                if item.get("status") == "TECHNICAL_BLOCKED"
            ]
            lanes[lane] = {
                "last_discovery_time": _text(old.get("last_discovery_time")),
                "last_candidate_time": _text(old.get("last_candidate_time")),
                "last_finalist_time": _text(old.get("last_finalist_time")),
                "last_qualified_time": _text(old.get("last_qualified_time")),
                "last_order_ready_time": _text(old.get("last_order_ready_time")),
                "last_fill_time": _text(old.get("last_fill_time")),
                "last_management_evaluation_time": _text(old.get("last_management_evaluation_time")),
                "last_exit_evaluation_time": _text(old.get("last_exit_evaluation_time")),
                "last_exit_time": _text(old.get("last_exit_time")),
                "last_reconciliation_time": _text(old.get("last_reconciliation_time")),
                "last_strict_truth_time": _text(old.get("last_strict_truth_time")),
                "last_learning_ingestion_time": _text(old.get("last_learning_ingestion_time")),
                "current_open_positions": 0,
                "technical_readiness": "TECHNICALLY_READY",
                "current_earliest_blocked_stage": "",
                "current_earliest_blocker": "",
                "technical_no_trade_status": "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT",
                "technical_truth_starvation_status": "NATURAL_NO_QUALIFYING_ENTRY",
                "truth_starvation_duration_seconds": old.get("truth_starvation_duration_seconds"),
                "stage_status": stage_status,
                "matrix_earliest_blocked_stage": matrix_blocked[0][0] if matrix_blocked else "",
                "matrix_earliest_blocker": matrix_blocked[0][1].get("blocker", "") if matrix_blocked else "",
            }

        decisions = _rows(trace.get("per_candidate_decision_trace"))
        partial_lane = _lane(partial.get("target_lane"))
        for row in decisions:
            lane = self._lane_from_row(row) or partial_lane
            if not lane:
                continue
            state = lanes[lane]
            observed_at = _event_time(row.get("observed_at"), row.get("timestamp"), row.get("created_at"), trace_time)
            if observed_at:
                state["last_discovery_time"] = observed_at
                state["last_candidate_time"] = observed_at
                self._set_stage(state["stage_status"], "DISCOVERY", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
                self._set_stage(state["stage_status"], "CANDIDATE", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
            if _truthy(row.get("shortlisted")) or _truthy(row.get("is_shortlisted")):
                self._set_stage(state["stage_status"], "SHORTLIST", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
            if _truthy(row.get("finalist")) or _truthy(row.get("is_finalist")):
                if observed_at:
                    state["last_finalist_time"] = observed_at
                self._set_stage(state["stage_status"], "FINALIST", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
            if _truthy(row.get("qualified")) or _truthy(row.get("qualification_passed")):
                if observed_at:
                    state["last_qualified_time"] = observed_at
                self._set_stage(state["stage_status"], "QUALIFIED", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
            if _truthy(row.get("order_ready")) or _text(row.get("stage")).upper() == "ORDER_READY":
                if observed_at:
                    state["last_order_ready_time"] = observed_at
                self._set_stage(state["stage_status"], "ORDER_READY", "PROVEN_READY", source="candidate_decision_trace", observed_at=observed_at)
            if _truthy(row.get("selected")) or _truthy(row.get("selected_for_entry")):
                self._set_stage(state["stage_status"], "ENTRY_SUBMITTED", "CURRENTLY_ACTIVE", source="candidate_decision_trace", observed_at=observed_at)

        funnel = _dict(runtime.get("lane_ranked_entry_funnel_v1"))
        for lane in LANES:
            lane_funnel = _dict(funnel.get(lane) or funnel.get(lane.lower()))
            if not lane_funnel:
                continue
            funnel_time = _event_time(
                lane_funnel.get("updated_at"),
                lane_funnel.get("generated_at"),
                lane_funnel.get("as_of"),
                trace_time,
            )
            if int(lane_funnel.get("discovered") or lane_funnel.get("candidate_count") or 0) > 0:
                if funnel_time:
                    lanes[lane]["last_discovery_time"] = funnel_time
                    lanes[lane]["last_candidate_time"] = funnel_time
                self._set_stage(lanes[lane]["stage_status"], "DISCOVERY", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)
                self._set_stage(lanes[lane]["stage_status"], "CANDIDATE", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)
            if int(lane_funnel.get("shortlisted") or lane_funnel.get("shortlist_count") or 0) > 0:
                self._set_stage(lanes[lane]["stage_status"], "SHORTLIST", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)
            if int(lane_funnel.get("finalists") or lane_funnel.get("finalist_count") or 0) > 0:
                if funnel_time:
                    lanes[lane]["last_finalist_time"] = funnel_time
                self._set_stage(lanes[lane]["stage_status"], "FINALIST", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)
            if int(lane_funnel.get("qualified") or lane_funnel.get("qualified_count") or 0) > 0:
                if funnel_time:
                    lanes[lane]["last_qualified_time"] = funnel_time
                self._set_stage(lanes[lane]["stage_status"], "QUALIFIED", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)
            if int(lane_funnel.get("order_ready") or lane_funnel.get("order_ready_count") or 0) > 0:
                if funnel_time:
                    lanes[lane]["last_order_ready_time"] = funnel_time
                self._set_stage(lanes[lane]["stage_status"], "ORDER_READY", "PROVEN_READY", source="lane_ranked_entry_funnel_v1", observed_at=funnel_time)

        partial_count = int(partial.get("candidates_evaluated") or partial.get("candidate_rows_loaded") or 0)
        if partial_lane and partial.get("microphase_completed") and partial_count > 0:
            if partial_time:
                lanes[partial_lane]["last_discovery_time"] = partial_time
                lanes[partial_lane]["last_candidate_time"] = partial_time
            self._set_stage(lanes[partial_lane]["stage_status"], "DISCOVERY", "PROVEN_READY", source="partial_candidate_microphase", observed_at=partial_time)
            self._set_stage(lanes[partial_lane]["stage_status"], "CANDIDATE", "PROVEN_READY", source="partial_candidate_microphase", observed_at=partial_time)

        positions = self._position_rows(runtime)
        for row in positions:
            lane = self._lane_from_row(row)
            if not lane:
                continue
            lanes[lane]["current_open_positions"] += 1
            observed_at = _event_time(
                row.get("management_evaluation_time"),
                row.get("evaluated_at"),
                row.get("updated_at"),
                row.get("as_of"),
                trace_time,
            )
            if observed_at:
                lanes[lane]["last_management_evaluation_time"] = observed_at
                lanes[lane]["last_exit_evaluation_time"] = observed_at
            self._set_stage(lanes[lane]["stage_status"], "ENTRY_FILLED", "PROVEN_READY", source="canonical_position_state", observed_at=observed_at)
            self._set_stage(lanes[lane]["stage_status"], "NATURAL_EXIT", "NATURAL_WAIT", blocker="open_position_wait", source="canonical_position_state", observed_at=observed_at)

        readiness = _dict(runtime.get("position_exit_readiness_v1"))
        advisory = _dict(runtime.get("unified_position_advisory_v1"))
        for row in _rows(readiness.get("positions")) + _rows(advisory.get("positions")):
            lane = self._lane_from_row(row)
            if not lane:
                continue
            observed_at = _event_time(
                row.get("evaluated_at"),
                row.get("evaluation_time"),
                row.get("updated_at"),
                row.get("generated_at"),
                trace_time,
            )
            if observed_at:
                lanes[lane]["last_management_evaluation_time"] = observed_at
                lanes[lane]["last_exit_evaluation_time"] = observed_at
            self._set_stage(lanes[lane]["stage_status"], "OBSERVATION", "CURRENTLY_ACTIVE", source="position_exit_readiness_v1", observed_at=observed_at)
            self._set_stage(lanes[lane]["stage_status"], "MANAGEMENT", "CURRENTLY_ACTIVE", source="position_exit_readiness_v1", observed_at=observed_at)
            self._set_stage(lanes[lane]["stage_status"], "EXIT_READINESS", "CURRENTLY_ACTIVE", source="position_exit_readiness_v1", observed_at=observed_at)

        capacity = _dict(runtime.get("last_evidence_capacity_snapshot"))
        reconciliation_at = _event_time(capacity.get("generated_at"), capacity.get("reconciled_at"))
        if reconciliation_at:
            for lane in LANES:
                lanes[lane]["last_reconciliation_time"] = reconciliation_at
                self._set_stage(lanes[lane]["stage_status"], "RECONCILIATION", "PROVEN_READY", source="capacity_reconciliation", observed_at=reconciliation_at)

        truth_rows = _rows(runtime.get("broker_truth_records_v1"))
        for row in truth_rows:
            lane = self._lane_from_row(row)
            if not lane:
                continue
            observed_at = _event_time(row.get("closed_at"), row.get("exit_filled_at"), row.get("created_at"))
            if observed_at:
                lanes[lane]["last_fill_time"] = observed_at
                lanes[lane]["last_exit_time"] = observed_at
                lanes[lane]["last_strict_truth_time"] = observed_at
            self._set_stage(lanes[lane]["stage_status"], "EXIT_FILLED", "PROVEN_READY", source="broker_truth_records_v1", observed_at=observed_at)
            self._set_stage(lanes[lane]["stage_status"], "RECONCILIATION", "PROVEN_READY", source="broker_truth_records_v1", observed_at=observed_at)
            self._set_stage(lanes[lane]["stage_status"], "STRICT_TRUTH", "PROVEN_READY", source="broker_truth_records_v1", observed_at=observed_at)

        operating_health = _dict(runtime.get("astra_operating_health_contract_v1"))
        learning_ledger = _rows(operating_health.get("truth_to_learning_ledger"))
        if learning_ledger:
            # A consumed ledger row without an acknowledgement timestamp is
            # still consumed, but it does not prove when ingestion occurred.
            for lane in LANES:
                lanes[lane]["last_learning_ingestion_time"] = ""
            for row in learning_ledger:
                if _text(row.get("consumption_result")).upper() != "CONSUMED":
                    continue
                lane = self._lane_from_row(row)
                if lane:
                    acknowledged_at = _event_time(
                        row.get("learning_acknowledgement_time"),
                        row.get("cortex_acknowledgement_time"),
                        row.get("governance_acknowledgement_time"),
                    )
                    lanes[lane]["last_learning_ingestion_time"] = acknowledged_at
                    self._set_stage(lanes[lane]["stage_status"], "LEARNING", "PROVEN_READY", source="truth_to_learning_ledger", observed_at=acknowledged_at)
        else:
            learning_rows = _rows(runtime.get("canonical_lifecycle_lessons_v1"))
            for row in learning_rows:
                lane = self._lane_from_row(row)
                if lane:
                    acknowledged_at = _event_time(row.get("created_at"), row.get("ingested_at"))
                    lanes[lane]["last_learning_ingestion_time"] = acknowledged_at
                    self._set_stage(lanes[lane]["stage_status"], "LEARNING", "PROVEN_READY", source="canonical_lifecycle_lessons_v1", observed_at=acknowledged_at)
            for row in truth_rows:
                lane = self._lane_from_row(row)
                if lane and _truthy(row.get("learning_acknowledged")):
                    acknowledged_at = _event_time(row.get("learning_acknowledged_at"), row.get("updated_at"))
                    lanes[lane]["last_learning_ingestion_time"] = acknowledged_at
                    self._set_stage(lanes[lane]["stage_status"], "LEARNING", "PROVEN_READY", source="broker_truth_records_v1", observed_at=acknowledged_at)
        return lanes

    @staticmethod
    def _truth_starvation_cause(lane: str, stage: Mapping[str, Any], issues: list[dict[str, Any]]) -> tuple[str, str]:
        lane_issues = [row for row in issues if lane in (row.get("lanes") or [])]
        issue_stage_order = {
            "DISCOVERY": 0,
            "CANDIDATE": 1,
            "QUALIFIED": 2,
            "ORDER_READY": 3,
            "OBSERVATION": 4,
            "MANAGEMENT": 5,
            "EXIT_READINESS": 6,
            "RECONCILIATION": 7,
            "STRICT_TRUTH": 8,
            "LEARNING": 9,
        }
        technical_issues = []
        for issue in lane_issues:
            fault = _text(issue.get("fault_type")).upper()
            if fault == "STRICT_TRUTH_LEARNING_HANDOFF_FAILURE":
                category, issue_stage = "LEARNING_HANDOFF_FAILURE", "LEARNING"
            elif fault in {"CAUSAL_HANDOFF_LOSS", "RECONCILIATION_FAILURE"}:
                category, issue_stage = "RECONCILIATION_FAILURE", "RECONCILIATION"
            elif fault == "PRODUCER_FRESH_CONSUMER_UNAVAILABLE" or fault in {"ACTIVE_POSITION_NOT_STREAMED", "WS_TRANSPORT_UNHEALTHY"}:
                category, issue_stage = "MARKET_OBSERVATION_FAILURE", "OBSERVATION"
            elif fault.startswith("CRYPTO_"):
                category, issue_stage = "POSITION_IDENTITY_FAILURE", "OBSERVATION"
            elif fault.startswith("DISCOVERY") or fault in {"BACKEND_UNHEALTHY", "ENTRY_FUNNEL_STAGE_BLOCKED"}:
                matrix_stage = _text(issue.get("component")).rsplit(".", 1)[-1]
                issue_stage = _MATRIX_STAGE_MAP.get(matrix_stage, "QUALIFIED") if fault == "ENTRY_FUNNEL_STAGE_BLOCKED" else "DISCOVERY"
                category = "ENTRY_PIPELINE_TECHNICAL_FAILURE"
            elif fault == "WORKER_CYCLE_BOUNDARY_EXCEEDED":
                category, issue_stage = "MANAGEMENT_TECHNICAL_FAILURE", "MANAGEMENT"
            else:
                continue
            technical_issues.append((issue_stage_order.get(issue_stage, 99), category, issue_stage, issue))
        if technical_issues:
            _, category, issue_stage, _ = min(technical_issues, key=lambda item: item[0])
            return category, issue_stage
        matrix_stage = _text(stage.get("matrix_earliest_blocked_stage"))
        if matrix_stage:
            if matrix_stage in {"RECONCILIATION"}:
                return "RECONCILIATION_FAILURE", matrix_stage
            if matrix_stage in {"OBSERVATION", "MANAGEMENT", "EXIT_READINESS"}:
                return "MARKET_OBSERVATION_FAILURE", matrix_stage
            if matrix_stage in {"STRICT_TRUTH"}:
                return "STRICT_TRUTH_PROMOTION_FAILURE", matrix_stage
            if matrix_stage in {"LEARNING"}:
                return "LEARNING_HANDOFF_FAILURE", matrix_stage
            return "ENTRY_PIPELINE_TECHNICAL_FAILURE", matrix_stage
        if int(stage.get("current_open_positions") or 0) > 0:
            return "NATURAL_OPEN_POSITION", "NATURAL_EXIT"
        if _text(stage.get("last_qualified_time")):
            return "NATURAL_NO_EXIT_SIGNAL", "NATURAL_EXIT"
        return "NATURAL_NO_QUALIFYING_ENTRY", "QUALIFICATION"

    def _issues(self, runtime: Mapping[str, Any], session: Mapping[str, Any]) -> list[dict[str, Any]]:
        trace = _dict(runtime.get("last_execution_trace"))
        market = _dict(_dict(trace.get("legacy_swing_observation")).get("market_activity"))
        source_state = _dict(runtime.get("equity_discovery_rebuild_v1"))
        worker_state = _dict(runtime.get("_worker_state"))
        issues: list[dict[str, Any]] = []

        # The completion matrix and integrity scanner are existing diagnostic
        # owners.  Surface only current, explicit failures here so a lane
        # cannot remain green when its own recorded stage is broken.
        matrix = self._completion_matrix(runtime)
        for lane, lane_matrix in _dict(matrix.get("lanes")).items():
            lane_name = _lane(lane)
            if not lane_name:
                continue
            for matrix_stage, info_value in _dict(lane_matrix.get("stages")).items():
                info = _dict(info_value)
                status = _text(info.get("status") or info.get("status_classification")).upper()
                if not (status.startswith("FAIL") and _text(info.get("verification_state")).upper() == "CURRENT"):
                    continue
                issues.append({
                    "fault_type": "ENTRY_FUNNEL_STAGE_BLOCKED",
                    "component": f"completion_matrix.{lane_name}.{matrix_stage}",
                    "lanes": [lane_name],
                    "severity": "HIGH",
                    "repair_action": "",
                    "evidence": _text(
                        info.get("first_bad_handoff")
                        or info.get("upstream_blocker")
                        or info.get("insufficient_evidence_reason")
                        or status
                    ),
                })

        scanner = _dict(runtime.get("system_integrity_scanner_v1"))
        for root in _rows(scanner.get("active_root_causes")):
            category = _text(root.get("category")).upper()
            state = _text(root.get("state")).upper()
            current = _text(root.get("current_vs_historical")).upper()
            if state in {"RESOLVED", "CLOSED"} or current not in {"", "CURRENT"}:
                continue
            causal = _dict(root.get("causal_handoff_integrity_v1"))
            if category == "CAUSAL_HANDOFF_LOSS":
                lane = _lane(causal.get("lane") or root.get("lane"))
                issues.append({
                    "fault_type": "RECONCILIATION_FAILURE",
                    "component": _text(root.get("likely_owner") or causal.get("consumer")) or "canonical_lifecycle_closure",
                    "lanes": [lane] if lane else list(LANES),
                    "severity": _text(root.get("severity")).upper() or "HIGH",
                    "repair_action": "",
                    "evidence": _text(root.get("first_bad_handoff") or causal.get("first_bad_handoff") or root.get("finding_id")),
                })
            elif category == "CYCLE_WITHIN_BOUNDS":
                issues.append({
                    "fault_type": "WORKER_CYCLE_BOUNDARY_EXCEEDED",
                    "component": _text(root.get("likely_owner")) or "canonical_worker_cycle",
                    "lanes": list(LANES),
                    "severity": _text(root.get("severity")).upper() or "HIGH",
                    "repair_action": "",
                    "evidence": _text(root.get("smallest_safe_repair") or root.get("finding_id") or "cycle_limit_exceeded"),
                })

        source_blocker = str(trace.get("final_blocker_reason") or trace.get("cycle_reason") or "")
        equity_source_missing = (
            bool(session.get("equity_session_open"))
            and not bool(source_state.get("candidate_source_available"))
            and source_blocker in {"legacy_market_evidence_bounded", "full_cycle_required_for_equity_candidate_processing"}
        )
        if equity_source_missing:
            issues.append({
                "fault_type": "DISCOVERY_LEGACY_BYPASS",
                "component": "PaperAutopilot.candidate_source",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "CRITICAL",
                "repair_action": "REBUILD_CANONICAL_DISCOVERY_STATE",
                "evidence": source_blocker,
            })

        active_symbols = self._active_observation_symbols(runtime)
        ws = _dict(runtime.get("alpaca_ws_active_position_monitor_v1"))
        actual = {
            str(value).upper().strip()
            for value in (ws.get("subscribed_symbols") or ws.get("active_symbols") or [])
            if str(value).strip()
        }
        missing_ws = sorted(active_symbols - actual)
        if active_symbols and missing_ws:
            issues.append({
                "fault_type": "ACTIVE_POSITION_NOT_STREAMED",
                "component": "AlpacaWS.active_position_subscription",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "HIGH",
                "repair_action": "RECONCILE_WS_SUBSCRIPTIONS",
                "evidence": ",".join(missing_ws[:12]),
            })

        ws_stats = _dict(ws.get("stats"))
        ws_transport = _text(ws.get("transport_health")).upper()
        ws_storm = (
            int(ws_stats.get("errors") or 0) >= 3
            and int(ws_stats.get("reconnects") or 0) >= 3
            and int(ws_stats.get("messages_received") or 0) == 0
        )
        if active_symbols and (ws_transport == "UNHEALTHY" or ws_storm):
            issues.append({
                "fault_type": "WS_TRANSPORT_UNHEALTHY",
                "component": "AlpacaWS.transport",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "HIGH",
                "repair_action": "RECONNECT_ALPACA_WS",
                "evidence": _text(ws_stats.get("last_error")) or ws_transport or "reconnect_storm",
            })

        resource = _dict(worker_state.get("resource"))
        backend_latency_present = "backend_health_latency_ms" in resource
        backend_unhealthy = (
            (backend_latency_present and resource.get("backend_health_latency_ms") is None)
            or worker_state.get("backend_health") is False
            or worker_state.get("backend_http_status") not in (None, 200, "200")
        )
        if backend_unhealthy:
            issues.append({
                "fault_type": "BACKEND_UNHEALTHY",
                "component": "backend_health_probe",
                "lanes": list(LANES),
                "severity": "HIGH",
                "repair_action": "",
                "evidence": "backend_health_probe_failed",
            })

        decision_sets = (
            _dict(_dict(runtime.get("loss_containment_state_v1")).get("decisions")),
            _dict(_dict(runtime.get("profit_protection_state_v1")).get("decisions")),
        )
        timestamp_failures = []
        for decisions in decision_sets:
            for row in decisions.values():
                if not isinstance(row, Mapping):
                    continue
                symbol = _text(row.get("symbol")).upper()
                if active_symbols and symbol not in active_symbols:
                    continue
                blockers = {str(blocker) for blocker in (row.get("exact_blockers") or [])}
                if (
                    "MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE" in str(row.get("first_causal_blocker") or row.get("reason") or "")
                    or "MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE" in blockers
                ):
                    timestamp_failures.append(row)
        if active_symbols and timestamp_failures:
            issues.append({
                "fault_type": "PRODUCER_FRESH_CONSUMER_UNAVAILABLE",
                "component": "PaperAutopilot.management_observation_handoff",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "HIGH",
                "repair_action": "REMATERIALIZE_MANAGEMENT_EVIDENCE",
                "evidence": str(len(timestamp_failures)),
            })

        recovery = _dict(runtime.get("position_lane_horizon_recovery_v1"))
        capacity_rows = _rows(
            _dict(runtime.get("last_evidence_capacity_snapshot")).get("position_rows_for_read_only_consumers")
        )
        canonical_crypto_symbols = {
            _text(row.get("symbol")).upper().replace("/", "").replace("-", "").replace("_", "")
            for row in capacity_rows
            if str(row.get("asset_type") or row.get("asset_class") or "").lower() in {"crypto", "cryptocurrency"}
            and not _truthy(row.get("is_dust"))
            and str(row.get("classification") or "").upper() not in {"BROKER_DUST_MONITORED", "BROKER_DUST", "DUST"}
            and _text(row.get("symbol"))
        }
        crypto_rows = [
            row for row in (recovery.get("positions") or [])
            if isinstance(row, Mapping)
            and str(row.get("asset_type") or row.get("asset_class") or "").lower() in {"crypto", "cryptocurrency"}
            and (
                not capacity_rows
                or _text(row.get("symbol")).upper().replace("/", "").replace("-", "").replace("_", "") in canonical_crypto_symbols
            )
        ]
        unresolved_crypto = sum(
            1 for row in crypto_rows
            if str(row.get("horizon_status") or row.get("horizon_evidence_status") or "").upper() in {"UNRESOLVED", "UNAVAILABLE", "MISSING"}
        )
        if crypto_rows and unresolved_crypto:
            issues.append({
                "fault_type": "CRYPTO_HORIZON_PRESENT_BUT_NOT_CONSUMED",
                "component": "PaperAutopilot.position_lane_horizon_recovery",
                "lanes": ["CRYPTO"],
                "severity": "HIGH",
                "repair_action": "RELOAD_CANONICAL_IDENTITY_STATE",
                "evidence": str(unresolved_crypto),
            })
        operating_health = _dict(runtime.get("astra_operating_health_contract_v1"))
        learning_ledger = _rows(operating_health.get("truth_to_learning_ledger"))
        if learning_ledger:
            unacknowledged = [
                row for row in learning_ledger
                if _text(row.get("consumption_result")).upper() not in {"CONSUMED", "ACKNOWLEDGED"}
            ]
        else:
            strict_truths = _rows(runtime.get("broker_truth_records_v1"))
            unacknowledged = [
                row for row in strict_truths
                if not _truthy(row.get("learning_acknowledged"))
            ]
        if unacknowledged:
            affected = sorted({self._lane_from_row(row) for row in unacknowledged if self._lane_from_row(row)}) or list(LANES)
            issues.append({
                "fault_type": "STRICT_TRUTH_LEARNING_HANDOFF_FAILURE",
                "component": "PaperAutopilot.strict_truth_learning_handoff",
                "lanes": affected,
                "severity": "HIGH",
                "repair_action": "",
                "evidence": str(len(unacknowledged)),
            })
        return issues

    @staticmethod
    def _readiness(issues: list[dict[str, Any]], session: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, str]:
        by_lane = {lane: [] for lane in LANES}
        for issue in issues:
            for lane in issue.get("lanes") or []:
                if lane in by_lane:
                    by_lane[lane].append(issue)
        out: dict[str, str] = {}
        for lane, lane_issues in by_lane.items():
            if any(str(issue.get("severity")) == "CRITICAL" for issue in lane_issues):
                out[lane] = "BLOCKED"
            elif lane_issues:
                out[lane] = "DEGRADED"
            else:
                out[lane] = "TECHNICALLY_READY"
        return out

    def run_if_due(
        self,
        *,
        runtime_state: Mapping[str, Any],
        worker_state: Mapping[str, Any],
        actions: Mapping[str, Callable[[], Mapping[str, Any] | None]] | None = None,
        refresh_runtime: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        previous = _read(self.path)
        session = self._session()
        now = time.monotonic()
        check_phase = str(session.get("check_phase") or "")
        scheduled_equity_phase = check_phase in {
            "PREOPEN_TRADING_READINESS",
            "POST_OPEN_DISCOVERY_VERIFICATION",
            "MIDDAY_INTEGRITY_CHECK",
            "NEAR_CLOSE_INTEGRITY_CHECK",
            "POST_CLOSE_LANE_ACCOUNTING",
        }
        interval = 300.0 if bool(session["equity_session_open"]) or bool(session["preopen_window"]) or scheduled_equity_phase else 900.0
        # A newly deployed watchdog schema must certify immediately rather
        # than inherit an old interval that contains no truth-stage evidence.
        previous_watchdog = _dict(previous.get("truth_production_watchdog"))
        watchdog_migrated = (
            _text(previous_watchdog.get("schema_version")) == TRUTH_WATCHDOG_VERSION
            and all(isinstance(_dict(_dict(previous_watchdog.get("lanes")).get(lane)).get("stage_status"), Mapping) for lane in LANES)
        )
        if previous and previous_watchdog and watchdog_migrated and now - float(previous.get("scan_monotonic") or 0.0) < interval:
            return {**previous, "due": False, "provider_calls_used": 0, "broker_actions_used": 0}

        actions = dict(actions or {})
        observed_runtime = dict(runtime_state)
        observed_runtime["_worker_state"] = dict(worker_state or {})
        issues = self._issues(observed_runtime, session)
        previous_faults = _dict(previous.get("faults"))
        fault_rows: dict[str, dict[str, Any]] = {}
        recoveries: list[dict[str, Any]] = []
        for issue in issues:
            key = f"{issue['fault_type']}:{issue['component']}"
            prior = _dict(previous_faults.get(key))
            count = int(prior.get("occurrence_count") or 0) + 1
            attempts = int(prior.get("repair_attempt_count") or 0)
            result: dict[str, Any] = {}
            action = str(issue.get("repair_action") or "")
            if attempts < 2 and callable(actions.get(action)):
                attempts += 1
                try:
                    result = _dict(actions[action]())
                    verification = "ACTION_DISPATCHED" if result else "RECOVERY_FAILED"
                except Exception as exc:
                    result = {"error": str(exc)[:160]}
                    verification = "RECOVERY_FAILED"
                recoveries.append({"fault_type": issue["fault_type"], "component": issue["component"], "repair_action": action, "result": result, "verification_result": verification})
            else:
                verification = "CODE_REPAIR_REQUIRED" if attempts >= 2 or not action else "NO_SAFE_ACTION_AVAILABLE"
            fault_rows[key] = {
                **issue,
                "first_seen": prior.get("first_seen") or _now(),
                "last_seen": _now(),
                "occurrence_count": count,
                "repair_attempt_count": attempts,
                "repair_result": result,
                "verification_result": verification,
                "recurrent": count >= 3,
            }

        # Recovery is bounded to one action plus one retry per fault.
        # Re-evaluate a fresh committed runtime snapshot so dispatch alone is
        # never reported as a successful repair.
        if recoveries and callable(refresh_runtime):
            try:
                refreshed_runtime = refresh_runtime()
                if isinstance(refreshed_runtime, Mapping):
                    observed_runtime = dict(refreshed_runtime)
                    observed_runtime["_worker_state"] = dict(worker_state or {})
            except Exception:
                # A failed refresh cannot manufacture a healthy verification;
                # retain the pre-action snapshot and leave recovery pending.
                pass
        remaining_issues = self._issues(observed_runtime, session) if recoveries else issues
        remaining_keys = {
            f"{row['fault_type']}:{row['component']}" for row in remaining_issues
        }
        for recovery in recoveries:
            key = f"{recovery.get('fault_type')}:{recovery.get('component')}"
            if key not in remaining_keys and recovery.get("verification_result") == "ACTION_DISPATCHED":
                recovery["verification_result"] = "RECOVERY_SUCCEEDED"
            elif key in remaining_keys and recovery.get("verification_result") == "ACTION_DISPATCHED":
                recovery["verification_result"] = "RECOVERY_VERIFYING"
        for key, row in fault_rows.items():
            if key not in remaining_keys and row.get("verification_result") in {"ACTION_DISPATCHED", "RECOVERY_VERIFYING"}:
                row["verification_result"] = "RECOVERY_SUCCEEDED"
            elif key in remaining_keys and row.get("verification_result") == "ACTION_DISPATCHED":
                row["verification_result"] = "RECOVERY_VERIFYING"
            if key in remaining_keys and int(row.get("repair_attempt_count") or 0) >= 2 and row.get("verification_result") == "RECOVERY_VERIFYING":
                row["verification_result"] = "CODE_REPAIR_REQUIRED"
                for recovery in recoveries:
                    if f"{recovery.get('fault_type')}:{recovery.get('component')}" == key:
                        recovery["verification_result"] = "RECOVERY_FAILED"
        issues = remaining_issues
        active_faults = [row for key, row in fault_rows.items() if key in remaining_keys]
        readiness = self._readiness(issues, session, runtime_state)
        stages = self._stage_ledger(runtime_state, previous)
        natural_causes = {
            "NATURAL_NO_QUALIFYING_ENTRY",
            "NATURAL_OPEN_POSITION",
            "NATURAL_NO_EXIT_SIGNAL",
            "CAPACITY_LEGITIMATELY_FULL",
        }
        for lane, stage in stages.items():
            cause, earliest = self._truth_starvation_cause(lane, stage, issues)
            stage["technical_readiness"] = readiness[lane]
            stage["current_earliest_blocked_stage"] = earliest
            stage["technical_truth_starvation_status"] = cause
            lane_issues = [row for row in issues if lane in (row.get("lanes") or [])]
            matching_issue = next(
                (
                    row for row in lane_issues
                    if _text(row.get("fault_type")).upper() in {
                        "DISCOVERY_LEGACY_BYPASS",
                        "ENTRY_FUNNEL_STAGE_BLOCKED",
                        "WORKER_CYCLE_BOUNDARY_EXCEEDED",
                        "PRODUCER_FRESH_CONSUMER_UNAVAILABLE",
                        "ACTIVE_POSITION_NOT_STREAMED",
                        "WS_TRANSPORT_UNHEALTHY",
                        "BACKEND_UNHEALTHY",
                        "RECONCILIATION_FAILURE",
                        "CRYPTO_HORIZON_PRESENT_BUT_NOT_CONSUMED",
                        "STRICT_TRUTH_LEARNING_HANDOFF_FAILURE",
                    }
                ),
                None,
            )
            if cause not in natural_causes:
                stage["technical_no_trade_status"] = "TECHNICAL_NO_TRADE"
                stage_status = _dict(stage.get("stage_status")).get(earliest)
                if isinstance(stage_status, dict):
                    stage_status.update({
                        "status": "TECHNICAL_BLOCKED",
                        "blocker": _text(
                            (matching_issue or {}).get("evidence")
                            or stage_status.get("blocker")
                            or stage.get("matrix_earliest_blocker")
                            or cause
                        ),
                        "source": _text((matching_issue or {}).get("component") or stage_status.get("source") or "readiness_watchdog"),
                    })
                stage["current_earliest_blocker"] = _text(
                    (matching_issue or {}).get("evidence")
                    or stage.get("matrix_earliest_blocker")
                    or cause
                )
            else:
                stage["technical_no_trade_status"] = "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT"
        technical_no_trade = any(
            stage.get("technical_no_trade_status") == "TECHNICAL_NO_TRADE"
            for stage in stages.values()
        ) and bool(session["equity_session_open"] or session.get("check_phase") == "CRYPTO_CONTINUOUS_CHECK")
        summary = {
            "schema_version": VERSION,
            "recovery_schema_version": RECOVERY_VERSION,
            "generated_at": _now(),
            "scan_monotonic": now,
            "due": True,
            "session": session,
            "trading_integrity_state": "CODE_REPAIR_REQUIRED" if any(row.get("verification_result") == "CODE_REPAIR_REQUIRED" for row in fault_rows.values()) else ("DEGRADED" if issues else "READY"),
            "lane_readiness": readiness,
            "day_readiness": readiness["DAY"],
            "scalp_readiness": readiness["SCALP"],
            "swing_readiness": readiness["SWING"],
            "crypto_readiness": readiness["CRYPTO"],
            "discovery_integrity": "FAULT" if any(row["fault_type"].startswith("DISCOVERY") for row in issues) else "READY",
            "position_management_integrity": "FAULT" if any(row["fault_type"] == "PRODUCER_FRESH_CONSUMER_UNAVAILABLE" for row in issues) else "READY",
            "ws_coverage_integrity": "FAULT" if any(row["fault_type"] == "ACTIVE_POSITION_NOT_STREAMED" for row in issues) else "READY",
            "crypto_lifecycle_integrity": "FAULT" if any(row["fault_type"].startswith("CRYPTO_") for row in issues) else "READY",
            "strict_truth_integrity": "FAULT" if any(row["fault_type"] == "STRICT_TRUTH_LEARNING_HANDOFF_FAILURE" for row in issues) else "READY",
            "technical_no_trade": "TECHNICAL_NO_TRADE" if technical_no_trade else "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT",
            "truth_production_watchdog": {
                "schema_version": TRUTH_WATCHDOG_VERSION,
                "generated_at": _now(),
                "lanes": stages,
                "crypto_continuous_check_active": True,
                "equity_check_phase": str(session.get("check_phase") or ""),
                "diagnoses_are_non_decisioning": True,
            },
            "faults": fault_rows,
            "active_faults": active_faults,
            "self_heal_attempts": len(recoveries),
            "self_heal_successes": sum(1 for row in recoveries if row.get("verification_result") == "RECOVERY_SUCCEEDED"),
            "recurrent_faults": [row for row in active_faults if row.get("recurrent")],
            "code_repair_required": any(row.get("verification_result") == "CODE_REPAIR_REQUIRED" for row in active_faults),
            "recoveries": recoveries,
            "last_full_successful_check": previous.get("last_full_successful_check") if issues else _now(),
            "safe_rollback_capability": "SAFE_ROLLBACK_UNAVAILABLE",
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "paper_only": True,
            "entry_policy_changed": False,
            "exit_policy_changed": False,
            "ranking_changed": False,
            "risk_changed": False,
            "sizing_changed": False,
            "capacity_changed": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        _write(self.path, summary)
        return summary
