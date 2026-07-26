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
LANES = ("DAY", "SWING", "CRYPTO")
MAX_LEDGER_ROWS = 200


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
        required = ("lifecycle_id", "entry_fill_id", "exit_fill_id", "symbol", "lane")
        return [row for row in records if bool(row.get("strict_broker_truth")) or all(_text(row.get(key)) for key in required)]

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
    ) -> dict[str, Any]:
        matrix = _dict(multilane)
        truths = self._strict_truths([_dict(row) for row in (truth_records or [])])
        learning = [_dict(row) for row in (learning_records or [])]
        learned_ids = {
            _text(row.get("truth_id") or row.get("broker_truth_id") or row.get("lifecycle_id"))
            for row in learning if _text(row.get("truth_id") or row.get("broker_truth_id") or row.get("lifecycle_id"))
        }
        lanes: dict[str, Any] = {}
        for lane in LANES:
            row = _dict(_dict(matrix.get("lanes")).get(lane))
            lane_truths = [truth for truth in truths if _text(truth.get("lane")).upper() == lane]
            consumed = [truth for truth in lane_truths if _text(truth.get("truth_id") or truth.get("lifecycle_id")) in learned_ids]
            blocker = _text(row.get("first_blocker"), "CANDIDATE_OBSERVATION_PENDING")
            valid_wait = blocker in {
                "CANDIDATE_OBSERVATION_PENDING", "NO_CURRENT_MARKET_OPPORTUNITY", "MARKET_CLOSED",
                "lane_activation", "PENDING_LANE_ACTIVATION", "CANDIDATE_TIMESTAMP_STALE",
                "CANDIDATE_ELIGIBLE_AWAITING_FULL_CYCLE",
            } or _text(row.get("first_blocker_validity")) in {"VALID_STRATEGY_REJECTION", "VALID_SCHEDULING_WAIT"}
            lanes[lane] = {
                "lane": lane, "current_lifecycle_stage": row.get("current_stage") or "candidate_discovery",
                "first_causal_blocker": blocker, "blocker_source": "astra_multilane_completion_matrix_v1",
                "blocker_validity": row.get("first_blocker_validity") or ("VALID_SAFETY_WAIT" if valid_wait else "UNCLASSIFIED_FAIL_CLOSED"),
                "waiting_state": "LEGITIMATE_WAIT" if valid_wait else "DEFECT_OR_UNCLASSIFIED",
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
            truth_id = _text(truth.get("truth_id") or truth.get("lifecycle_id"))
            consumed = truth_id in learned_ids
            ledger.append({
                "truth_id": truth_id, "lane": _text(truth.get("lane")).upper(), "symbol": _text(truth.get("symbol")).upper(),
                "lifecycle_id": truth.get("lifecycle_id"), "persisted_at": truth.get("persisted_at") or truth.get("created_at"),
                "evidence_registration_time": truth.get("evidence_registered_at"), "consumer": "canonical_lifecycle_learning",
                "consumption_result": "CONSUMED" if consumed else "AWAITING_LEARNING",
                "learning_acknowledgement_time": truth.get("learning_acknowledged_at") if consumed else None,
                "cortex_acknowledgement_time": truth.get("cortex_acknowledged_at") if consumed else None,
                "governance_acknowledgement_time": truth.get("governance_acknowledged_at") if consumed else None,
                "failure_reason": None if consumed else "awaiting_authoritative_learning_consumer", "retry_status": "NO_AUTOMATIC_RETRY",
                "final_state": "CONSUMED" if consumed else "PERSISTED_AWAITING_CONSUMPTION",
            })
        return {
            "endpoint": "/api/astra_operating_health_contract_v1", "suite": "Astra Operating Health Contract V1",
            "version": VERSION, "generated_at": _now(), "status": status, "lanes": lanes,
            "strict_truth_total": len(truths), "truths_consumed_by_learning_total": len(learned_ids & {_text(t.get("truth_id") or t.get("lifecycle_id")) for t in truths}),
            "truth_to_learning_ledger": ledger, "truth_to_learning_ledger_bounded": True,
            "sentinel_status": _dict(sentinel).get("status"), "governance_status": _dict(continuous).get("status"),
            "cortex_status": _dict(cortex).get("status"), "control_plane_agreement": control_agree,
            "control_plane_disagreement_reason": None if control_agree else "sentinel_has_high_or_critical_root_cause; governance remains fail-closed for execution",
            "governance_first_causal_blocker": campaign.get("first_causal_blocker"),
            "monitoring_coverage": "BOUNDED_WORKER_COMMITTED", "get_route_read_only": True,
            "worker_owned_mutations_only": True, **_safety(),
        }
