"""Bounded, read-only market-hours observations for existing paper lanes.

The existing PaperAutopilot worker owns execution. This module only records
its trace after a cycle; it never calls a provider, broker, allocator, or
order method. Dashboard GETs read the latest compact report without executing
an audit or mutating broker state.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract


MAX_REPORTS = 96
REPORT_FILE = "automated_market_hours_multilane_audit_v1.json"
SCHEDULE_ET = ((9, 40), (12, 0), (15, 15))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _scheduled_slot_et(now: datetime) -> str:
    """Return the exact ET audit slot, not merely its calendar date."""
    if (now.hour, now.minute) not in SCHEDULE_ET:
        return ""
    return now.strftime("%Y-%m-%dT%H:%M")


def _asset_bucket(row: Mapping[str, Any]) -> str:
    identity = apply_trade_lane_contract(row, legacy=False)
    lane = _text(identity.get("lane_id") or row.get("lane_id")).upper() or "UNKNOWN"
    # PaperAutopilot's execution asset is deliberately ``stock`` for ETFs;
    # performance grouping must use the immutable instrument cohort first.
    asset = _text(identity.get("instrument_type") or row.get("instrument_type") or row.get("asset_type") or row.get("asset_class")).upper()
    if lane == "CRYPTO" or asset == "CRYPTO":
        return "CRYPTO"
    return f"{lane}_{'ETF' if asset == 'ETF' else 'EQUITY'}"


def blocker_class(reason: Any) -> str:
    value = _text(reason).upper()
    if not value or value in {"NO_CURRENT_SIGNAL", "NO_CANDIDATES_AVAILABLE"}:
        return "NO_WORTHWHILE_OPPORTUNITY"
    if "CONTRACT" in value or "ENRICH" in value:
        return "CONTRACT_INCOMPLETE"
    if "QUOTE" in value or "STALE" in value or "FRESHNESS" in value:
        return "STALE_MARKET_DATA"
    if "DOWNSIDE" in value or "DRAWDOWN" in value or "RISK_ENVELOPE" in value:
        return "MISSING_RISK_ENVELOPE"
    if "SESSION" in value or "MARKET" in value:
        return "SESSION_CLOSED"
    if "DUPLICATE" in value:
        return "DUPLICATE_EXPOSURE"
    if "CAPACITY" in value or "CONCURRENT" in value:
        return "CAPACITY_BLOCKED"
    if "RESERVE" in value or "CAPITAL" in value:
        return "RESERVE_BLOCKED"
    if "ELIGIB" in value or "PAIR" in value or "TRADABLE" in value:
        return "BROKER_INELIGIBLE"
    if "SUBMISSION" in value or "REJECT" in value:
        return "ORDER_SUBMISSION_FAILED"
    if "ACK" in value:
        return "BROKER_ACK_PENDING"
    if "QUALIF" in value or "CONFIDENCE" in value or "LIQUID" in value:
        return "QUALIFICATION_FAILED"
    if "SELECT" in value or "TIE_BREAK" in value:
        return "NOT_SELECTED"
    if "POLICY" in value:
        return "HUMAN_POLICY_REQUIRED"
    return "TECHNICAL_PIPELINE_FAILURE"


def build_audit(trace: Mapping[str, Any] | None, *, trigger: str = "read_only_refresh") -> dict[str, Any]:
    """Build one bounded report from a worker-owned trace without side effects."""
    trace = dict(trace or {})
    rows = [dict(row) for row in (trace.get("per_candidate_decision_trace") or []) if isinstance(row, Mapping)][:200]
    candidate_rows = []
    counts: dict[str, Counter[str]] = {}
    for row in rows:
        identity = apply_trade_lane_contract(row, legacy=False)
        bucket = _asset_bucket(row)
        counter = counts.setdefault(bucket, Counter())
        contract = dict(row.get("pretrade_decision_contract") or {})
        risk = dict(contract.get("candidate_risk_envelope_v1") or row.get("candidate_risk_envelope_v1") or {})
        contract_state = _text(row.get("pretrade_decision_contract_state") or contract.get("contract_state") or "CONTRACT_INCOMPLETE")
        downstream_blocker = _text(row.get("order_readiness_reason") or row.get("decision_reason") or row.get("capacity_blocker") or trace.get("final_blocker_reason"))
        missing = _text((contract.get("missing_required_fields") or [""])[0])
        # A fail-closed contract is necessarily earlier than capacity,
        # duplicate, or session gates. Surface the true first stop rather than
        # a downstream branch that happened to inspect the row first.
        if contract_state == "CONTRACT_INCOMPLETE":
            first = f"CONTRACT_INCOMPLETE:{missing or 'REQUIRED_PLAN_EVIDENCE'}"
            last_stage = "CONTRACT_INCOMPLETE"
        elif contract_state == "CONTRACT_CONFLICTING":
            first = "CONTRACT_CONFLICTING"
            last_stage = "CONTRACT_CONFLICTING"
        else:
            first = downstream_blocker
            last_stage = "LIFECYCLE_COMPLETE" if row.get("exit_fill_id") else "FILLED" if row.get("entry_fill_id") else "ORDER_ACKNOWLEDGED" if row.get("broker_order_id") else "ORDER_SUBMITTED" if row.get("order_submitted") else "ORDER_READY" if row.get("order_ready") else "SELECTED" if row.get("selected") else "QUALIFIED" if row.get("eligible") else "CONTRACT_COMPLETE"
        counter["candidates_generated"] += 1
        counter[f"contract_{contract_state}"] += 1
        counter[f"risk_{_text(risk.get('risk_envelope_state') or 'RISK_ENVELOPE_INCOMPLETE')}"] += 1
        counter["qualified"] += int(bool(row.get("eligible")))
        counter["selected"] += int(bool(row.get("selected")))
        counter["order_ready"] += int(bool(row.get("order_ready")))
        counter["orders_submitted"] += int(bool(row.get("order_submitted")))
        counter["acknowledged"] += int(bool(row.get("broker_order_id")))
        counter["fills"] += int(bool(row.get("entry_fill_id")))
        counter["completed_lifecycles"] += int(bool(row.get("entry_fill_id") and row.get("exit_fill_id")))
        canonical_lane_id = _text(identity.get("lane_id") or row.get("lane_id")).upper()
        candidate_rows.append({
            "candidate_id": _text(row.get("candidate_id")), "symbol": _text(row.get("symbol")).upper(),
            # Keep both names for existing Action Center consumers while making
            # the authoritative lane join key explicit for lineage consumers.
            "lane": canonical_lane_id, "lane_id": canonical_lane_id,
            "asset_type": _text(identity.get("instrument_type") or row.get("instrument_type") or row.get("asset_type")),
            "asset_classification_source": _text(identity.get("asset_classification_source")),
            "risk_envelope_id": _text(risk.get("risk_envelope_id") or row.get("risk_envelope_id")),
            "risk_envelope_state": _text(risk.get("risk_envelope_state") or "RISK_ENVELOPE_INCOMPLETE"),
            "expected_downside_source": _text((risk.get("field_provenance_v1") or {}).get("expected_downside_range", {}).get("source_system")),
            "expected_drawdown_source": _text((risk.get("field_provenance_v1") or {}).get("expected_drawdown", {}).get("source_system")),
            "quote_freshness": _text(risk.get("quote_freshness")),
            "volatility_source": _text(risk.get("volatility_method")),
            "spread_state": "AVAILABLE" if risk.get("spread_pct") is not None else "UNAVAILABLE",
            "liquidity_state": _text(risk.get("liquidity_state")),
            "last_completed_stage": last_stage, "contract_state": contract_state,
            "first_blocker": first, "blocker_class": blocker_class(first),
            "downstream_blocker_observed": downstream_blocker,
            "blocker_owner": "PaperAutopilot", "blocker_kind": "market_opportunity" if blocker_class(first) == "NO_WORTHWHILE_OPPORTUNITY" else "technical_or_gate",
            "actual_value": first, "required_value": "existing qualification and execution gate", "timestamp": _text(row.get("generated_at") or trace.get("last_autopilot_cycle_at")),
            "safe_auto_repair_possible": False,
        })
    return {
        "endpoint": "/api/automated_market_hours_multilane_audit_v1", "audit_owner": "PaperAutopilot.existing_worker_cycle",
        "generated_at": _now(), "trigger": trigger, "session_state": _text(trace.get("market_session_mode") or "UNKNOWN"),
        "candidate_rows": candidate_rows, "counts_by_lane_asset": {key: dict(value) for key, value in counts.items()},
        "selected_candidate": next((row.get("candidate_id") for row in candidate_rows if row.get("last_completed_stage") in {"ORDER_READY", "ORDER_SUBMITTED", "ORDER_ACKNOWLEDGED", "FILLED"}), ""),
        "exact_first_blocker": _text(trace.get("final_blocker_reason")) or (candidate_rows[0]["first_blocker"] if candidate_rows else "NO_WORTHWHILE_OPPORTUNITY"),
        "orders_submitted": int(trace.get("orders_submitted") or 0), "broker_acknowledgements": sum(1 for row in candidate_rows if row["last_completed_stage"] in {"ORDER_ACKNOWLEDGED", "FILLED", "LIFECYCLE_COMPLETE"}),
        "fills": sum(1 for row in candidate_rows if row["last_completed_stage"] in {"FILLED", "LIFECYCLE_COMPLETE"}),
        "completed_lifecycles": sum(1 for row in candidate_rows if row["last_completed_stage"] == "LIFECYCLE_COMPLETE"),
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "full_history_scan_count": 0,
        "read_only": True, "paper_only_preserved": True, "broker_live_endpoint_allowed": False,
    }


class MarketHoursAuditRegistry:
    def __init__(self, state_dir: str = "state") -> None:
        self.path = os.path.join(state_dir, REPORT_FILE)

    def _read(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else {"reports": []}
        except Exception:
            return {"reports": []}

    def latest(self) -> dict[str, Any]:
        reports = list(self._read().get("reports") or [])
        return dict(reports[-1]) if reports else {
            "endpoint": "/api/automated_market_hours_multilane_audit_v1", "status": "AUDIT_AWAITING_FIRST_WORKER_CYCLE",
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "full_history_scan_count": 0,
        }

    def should_record(self, trace: Mapping[str, Any]) -> str:
        prior = self.latest()
        if not prior.get("generated_at"):
            return "backend_restart_or_first_worker_cycle"
        et_now = datetime.now(ZoneInfo("America/New_York"))
        scheduled_slot = _scheduled_slot_et(et_now)
        # Record each configured market-hours slot once. A daily marker would
        # incorrectly suppress the noon and 15:15 audits after the 09:40 run.
        if scheduled_slot and _text(prior.get("scheduled_slot_et")) != scheduled_slot:
            return "scheduled_market_hours_audit"
        rows = trace.get("per_candidate_decision_trace") or []
        if any(isinstance(row, Mapping) and bool(row.get("order_ready")) for row in rows):
            return "order_ready_observed"
        if any(isinstance(row, Mapping) and _text(row.get("order_result")).lower() == "rejected" for row in rows):
            return "order_blocked_observed"
        return ""

    def record_if_due(self, trace: Mapping[str, Any]) -> dict[str, Any] | None:
        trigger = self.should_record(trace)
        if not trigger:
            return None
        return self.record(trace, trigger=trigger)

    def record(self, trace: Mapping[str, Any] | None, *, trigger: str) -> dict[str, Any]:
        """Persist a bounded observation; callers must already own scheduling."""
        report = build_audit(trace, trigger=trigger)
        et_now = datetime.now(ZoneInfo("America/New_York"))
        report["scheduled_date_et"] = et_now.date().isoformat()
        report["scheduled_slot_et"] = _scheduled_slot_et(et_now)
        data = self._read()
        reports = list(data.get("reports") or [])[-(MAX_REPORTS - 1):]
        reports.append(report)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temporary = f"{self.path}.tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"version": "v1", "reports": reports}, handle, separators=(",", ":"), ensure_ascii=True)
        os.replace(temporary, self.path)
        return report
