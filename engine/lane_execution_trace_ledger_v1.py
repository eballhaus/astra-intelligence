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
        }

    def _read_summary(self) -> dict[str, Any]:
        try:
            with open(self.summary_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                data.setdefault("lanes", {})
                for lane in LANES:
                    data["lanes"].setdefault(lane, self._empty_lane())
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
                "symbol": symbol, "asset_class": _text(source.get("asset_class") or source.get("asset_type")),
                "candidate_source": _text(source.get("candidate_source")), "candidate_seen": True,
                "freshness_result": _text(source.get("candidate_snapshot_freshness") or source.get("freshness_result")),
                "eligibility_result": "PASS" if source.get("eligible") else "BLOCKED",
                "session_result": "PASS" if source.get("paper_order_submission_allowed") else _text(source.get("market_session_mode") or "BLOCKED"),
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
            lane_summary["duplicate_attempts"] += int(record["duplicate_exposure_result"] == "BLOCKED")
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
