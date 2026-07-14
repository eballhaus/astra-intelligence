"""Compact, append-only paper-lane execution trace ledger.

The paper worker is the only writer.  Dashboard and diagnostic reads consume
the compact summary file, never the broad candidate decision ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


LANES = ("SWING", "DAY", "CRYPTO")
MAX_RECENT_IDS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(parts: Iterable[Any]) -> str:
    payload = "|".join(_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class LaneExecutionTraceLedgerV1:
    """Bounded index over append-only operational traces; never broker truth."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.path = os.path.join(self.state_dir, "lane_execution_trace_v1.jsonl")
        self.summary_path = os.path.join(self.state_dir, "lane_execution_trace_v1.summary.json")

    def _empty_summary(self) -> dict[str, Any]:
        return {
            "version": "v1",
            "generated_at": _now(),
            "total_trace_rows": 0,
            "duplicate_trace_rows_suppressed": 0,
            "recent_trace_ids": [],
            "lanes": {lane: self._empty_lane() for lane in LANES},
        }

    @staticmethod
    def _empty_lane() -> dict[str, Any]:
        return {
            "candidates_seen": 0, "fresh_candidates": 0, "stale_candidates": 0,
            "eligible": 0, "selected": 0, "order_ready": 0,
            "submission_attempted": 0, "submitted": 0, "rejected_by_broker": 0,
            "filled_entries": 0, "open_lane_positions": 0, "exit_orders": 0,
            "filled_exits": 0, "completed_lifecycles": 0, "strict_broker_truths": 0,
            "learning_deliveries": 0, "metadata_failures": 0, "duplicate_attempts": 0,
            "ownership_conflicts": 0, "top_blockers": {},
            "blocked_by_global_capacity": 0, "allowed_by_lane_reserve": 0,
            "blocked_by_lane_reserve": 0, "blocked_by_buying_power": 0,
            "blocked_by_global_risk": 0, "blocked_by_duplicate_exposure": 0,
            "reserve_order_ready_count": 0, "reserve_submission_attempt_count": 0,
            "reserve_commitments_requested": 0, "reserve_commitments_released": 0,
            "reserve_commitments_pending": 0, "false_reserve_exhaustion_contradictions": 0,
        }

    def _read_summary(self) -> dict[str, Any]:
        try:
            with open(self.summary_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("lanes", {})
                for lane in LANES:
                    lane_data = data["lanes"].get(lane)
                    if not isinstance(lane_data, dict):
                        lane_data = {}
                    # Merge newly added counters into summaries written by
                    # older workers without rewriting historical trace rows.
                    for key, default in self._empty_lane().items():
                        lane_data.setdefault(key, default)
                    data["lanes"][lane] = lane_data
                data.setdefault("recent_trace_ids", [])
                return data
        except Exception:
            pass
        return self._empty_summary()

    def _write_summary(self, summary: Mapping[str, Any]) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        temp = f"{self.summary_path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(dict(summary), handle, separators=(",", ":"), ensure_ascii=True)
        os.replace(temp, self.summary_path)

    def record(self, rows: Iterable[Mapping[str, Any]], *, cycle_id: str) -> dict[str, int]:
        """Append unique worker traces and update a bounded daily summary."""
        summary = self._read_summary()
        recent = list(summary.get("recent_trace_ids") or [])[-MAX_RECENT_IDS:]
        known = set(recent)
        appended = suppressed = 0
        records: list[dict[str, Any]] = []
        for source in rows:
            if not isinstance(source, Mapping):
                continue
            lane = _text(source.get("lane_id")).upper()
            if lane not in LANES:
                continue
            candidate_id = _text(source.get("candidate_id"))
            recommendation_id = _text(source.get("recommendation_id"))
            symbol = _text(source.get("symbol")).upper()
            source_fingerprint = _fingerprint((lane, candidate_id, recommendation_id, symbol, source.get("candidate_generated_at")))
            trace_id = _fingerprint((cycle_id, source_fingerprint, source.get("decision_reason"), source.get("order_result")))
            if trace_id in known:
                suppressed += 1
                continue
            blocker = _text(source.get("order_readiness_reason") or source.get("decision_reason") or source.get("final_blocker_reason"))
            record = {
                "trace_id": trace_id, "timestamp_utc": _now(), "cycle_id": _text(cycle_id),
                "lane_id": lane, "candidate_id": candidate_id, "recommendation_id": recommendation_id,
                "symbol": symbol, "canonical_symbol": _text(source.get("canonical_symbol") or symbol).upper(),
                "asset_class": _text(source.get("asset_class") or source.get("asset_type")),
                "candidate_source": _text(source.get("candidate_source")), "candidate_seen": True,
                "freshness_result": _text(source.get("candidate_snapshot_freshness") or source.get("freshness_result")),
                "eligibility_result": "PASS" if source.get("eligible") else "BLOCKED",
                "session_result": "PASS" if source.get("paper_order_submission_allowed") else _text(source.get("session_state") or source.get("market_session_mode") or "BLOCKED"),
                "capital_result": "PASS" if source.get("lane_activation_contract", {}).get("capital_configured", True) else "BLOCKED",
                "risk_result": "PASS" if source.get("eligible") else "NOT_REACHED",
                "duplicate_exposure_result": "BLOCKED" if source.get("duplicate_active_position") else "PASS",
                "selection_result": "SELECTED" if source.get("selected") else "NOT_SELECTED",
                "order_readiness_result": "ORDER_READY" if source.get("order_ready") else "NOT_READY",
                "submission_attempted": bool(source.get("order_attempted")),
                "submission_result": _text(source.get("order_result")),
                "broker_order_id": _text(source.get("broker_order_id")), "entry_fill_id": _text(source.get("entry_fill_id")),
                "position_id": _text(source.get("position_id")), "position_owner": _text(source.get("position_owner")),
                "exit_trigger": _text(source.get("exit_trigger")), "exit_order_id": _text(source.get("exit_order_id")),
                "exit_fill_id": _text(source.get("exit_fill_id")), "truth_id": _text(source.get("truth_id")),
                "truth_status": _text(source.get("truth_status")), "learning_delivery_status": _text(source.get("learning_delivery_status")),
                "exact_blocker": blocker, "source_fingerprint": source_fingerprint,
                "source_record_id": _text(source.get("source_record_id")),
                "ranking_version": _text(source.get("ranking_version")),
                "generated_at": _text(source.get("generated_at") or source.get("candidate_generated_at")),
                "expires_at": _text(source.get("expires_at")),
                "market_session": _text(source.get("market_session_mode") or source.get("session_state")),
                "capital_book_id": _text(source.get("capital_book_id")),
                "capacity_decision": _text(source.get("capacity_decision")),
                "capacity_source": _text(source.get("capacity_source")),
                "capacity_snapshot_id": _text(source.get("capacity_snapshot_id") or source.get("canonical_capacity_snapshot", {}).get("snapshot_id") if isinstance(source.get("canonical_capacity_snapshot"), Mapping) else ""),
                "global_capacity_status": _text(source.get("global_capacity_status")),
                "lane_reserve_status": _text(source.get("lane_reserve_status")),
                "lane_reserve_enabled": bool(source.get("lane_reserve_enabled", False)),
                "lane_reserve_available": bool(source.get("lane_reserve_available", False)),
                "lane_capital_used": source.get("lane_capital_used"),
                "lane_capital_remaining": source.get("lane_capital_remaining"),
                "lane_capital_limit": source.get("lane_capital_limit"),
                "lane_positions_used": source.get("lane_positions_used"),
                "lane_positions_remaining": source.get("lane_positions_remaining"),
                "lane_position_limit": source.get("lane_position_limit"),
                "lane_open_position_count": source.get("lane_open_position_count"),
                "lane_pending_order_count": source.get("lane_pending_order_count"),
                "lane_active_commitment_count": source.get("lane_active_commitment_count"),
                "capacity_blocker": _text(source.get("capacity_blocker")),
                "commitment_id": _text(source.get("commitment_id")),
                "active_commitment_id": _text(source.get("commitment_id")),
                "commitment_state": _text(source.get("commitment_state")),
                "commitment_final_state": _text(source.get("commitment_final_state")),
                "entry_owner": _text(source.get("entry_owner")),
                "exit_owner": _text(source.get("exit_owner") or source.get("exit_policy_owner")),
            }
            records.append(record)
            known.add(trace_id)
            recent.append(trace_id)
            lane_summary = summary["lanes"].setdefault(lane, self._empty_lane())
            lane_summary["candidates_seen"] += 1
            lane_summary["fresh_candidates"] += int(record["freshness_result"].upper() in {"CURRENT", "FRESH"})
            lane_summary["stale_candidates"] += int(record["freshness_result"].upper() == "STALE")
            lane_summary["eligible"] += int(record["eligibility_result"] == "PASS")
            lane_summary["selected"] += int(record["selection_result"] == "SELECTED")
            lane_summary["order_ready"] += int(record["order_readiness_result"] == "ORDER_READY")
            lane_summary["submission_attempted"] += int(record["submission_attempted"])
            lane_summary["submitted"] += int(record["submission_result"].lower() in {"submitted", "accepted"})
            lane_summary["rejected_by_broker"] += int(record["submission_result"].lower() == "rejected")
            lane_summary["filled_entries"] += int(bool(record["entry_fill_id"]))
            lane_summary["open_lane_positions"] += int(bool(record["position_id"]))
            lane_summary["exit_orders"] += int(bool(record["exit_order_id"]))
            lane_summary["filled_exits"] += int(bool(record["exit_fill_id"]))
            lane_summary["completed_lifecycles"] += int(bool(record["entry_fill_id"] and record["exit_fill_id"]))
            lane_summary["strict_broker_truths"] += int(record["truth_status"].upper() == "BROKER_CONFIRMED_COMPLETE")
            lane_summary["learning_deliveries"] += int(record["learning_delivery_status"].upper() in {"DELIVERED", "ACKNOWLEDGED"})
            lane_summary["duplicate_attempts"] += int(record["duplicate_exposure_result"] == "BLOCKED")
            capacity_decision = record["capacity_decision"]
            lane_summary["blocked_by_global_capacity"] += int(capacity_decision == "GLOBAL_CAPACITY_EXHAUSTED")
            lane_summary["allowed_by_lane_reserve"] += int(capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
            lane_summary["blocked_by_lane_reserve"] += int(capacity_decision in {"LANE_RESERVE_EXHAUSTED", "CAPITAL_NOT_CONFIGURED"})
            lane_summary["blocked_by_buying_power"] += int(capacity_decision in {"BUYING_POWER_INSUFFICIENT", "BUYING_POWER_UNAVAILABLE"})
            lane_summary["blocked_by_global_risk"] += int(capacity_decision == "GLOBAL_RISK_BLOCKED")
            lane_summary["blocked_by_duplicate_exposure"] += int(capacity_decision == "DUPLICATE_EXPOSURE_BLOCKED")
            lane_summary["reserve_order_ready_count"] += int(record["order_readiness_result"] == "ORDER_READY" and capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
            lane_summary["reserve_submission_attempt_count"] += int(record["submission_attempted"] and capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
            lane_summary["reserve_commitments_requested"] += int(bool(record["commitment_id"]))
            lane_summary["reserve_commitments_released"] += int(record["commitment_state"] == "RELEASED" or record["commitment_final_state"] == "RELEASED")
            lane_summary["reserve_commitments_pending"] += int(record["commitment_state"] == "CONVERTED_TO_PENDING_ORDER")
            lane_summary["false_reserve_exhaustion_contradictions"] += int(
                capacity_decision == "LANE_RESERVE_EXHAUSTED"
                and bool(record["lane_reserve_enabled"])
                and (record["lane_capital_remaining"] or 0) > 0
                and (record["lane_positions_remaining"] or 0) > 0
                and (record["lane_open_position_count"] or 0) == 0
                and (record["lane_pending_order_count"] or 0) == 0
                and (record["lane_active_commitment_count"] or 0) == 0
            )
            lane_summary["metadata_failures"] += int(not candidate_id or not recommendation_id)
            if blocker:
                blockers = lane_summary.setdefault("top_blockers", {})
                blockers[blocker] = int(blockers.get(blocker, 0)) + 1
            appended += 1
        if records:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")
        summary["total_trace_rows"] = int(summary.get("total_trace_rows", 0)) + appended
        summary["duplicate_trace_rows_suppressed"] = int(summary.get("duplicate_trace_rows_suppressed", 0)) + suppressed
        summary["recent_trace_ids"] = recent[-MAX_RECENT_IDS:]
        summary["generated_at"] = _now()
        self._write_summary(summary)
        return {"appended": appended, "suppressed": suppressed}

    def summary(self) -> dict[str, Any]:
        result = self._read_summary()
        result["ledger_path"] = self.path
        result["bounded_summary_read"] = True
        return result
