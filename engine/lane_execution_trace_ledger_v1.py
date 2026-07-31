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


LANES = ("SWING", "DAY", "SCALP", "CRYPTO")
MAX_RECENT_IDS = 500
MAX_DAILY_BUCKETS = 31
COHORTS = ("SWING_EQUITY", "DAY_EQUITY", "DAY_ETF", "SWING_ETF", "SCALP", "CRYPTO")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fingerprint(parts: Iterable[Any]) -> str:
    payload = "|".join(_text(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cohort_id(lane: str, asset_class: Any, instrument_type: Any) -> str:
    """Keep ETFs as a cohort inside the existing equity lanes."""
    lane = _text(lane).upper()
    if lane == "CRYPTO" or _text(asset_class).lower() == "crypto":
        return "CRYPTO"
    suffix = "ETF" if _text(instrument_type).upper() == "ETF" else "EQUITY"
    if lane == "SCALP":
        return "SCALP"
    return f"{lane}_{suffix}" if lane in {"DAY", "SWING"} else "SWING_EQUITY"


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
            "cohorts": {cohort: self._empty_lane() for cohort in COHORTS},
            # Bounded worker-maintained counters make throughput windows
            # observable without scanning the append-only trace file on GET.
            "daily_buckets": {},
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
                data.setdefault("cohorts", {})
                for lane in LANES:
                    lane_data = data["lanes"].get(lane)
                    if not isinstance(lane_data, dict):
                        lane_data = {}
                    # Merge newly added counters into summaries written by
                    # older workers without rewriting historical trace rows.
                    for key, default in self._empty_lane().items():
                        lane_data.setdefault(key, default)
                    # This counter is appended once per trace row and never
                    # decremented, so it is a historical conversion count,
                    # not current pending broker/order occupancy.  Preserve
                    # the legacy key for readers while publishing an explicit
                    # non-authoritative label for new diagnostics.
                    lane_data["reserve_commitments_converted_to_pending_order_lifetime"] = int(
                        lane_data.get("reserve_commitments_pending") or 0
                    )
                    lane_data["reserve_commitments_pending_is_current_occupancy"] = False
                    data["lanes"][lane] = lane_data
                for cohort in COHORTS:
                    cohort_data = data["cohorts"].get(cohort)
                    if not isinstance(cohort_data, dict):
                        cohort_data = {}
                    for key, default in self._empty_lane().items():
                        cohort_data.setdefault(key, default)
                    data["cohorts"][cohort] = cohort_data
                buckets = data.get("daily_buckets")
                if not isinstance(buckets, dict):
                    buckets = {}
                normalized_buckets: dict[str, dict[str, Any]] = {}
                for day, bucket in sorted(buckets.items())[-MAX_DAILY_BUCKETS:]:
                    if not isinstance(bucket, dict):
                        continue
                    normalized_buckets[str(day)] = self._normalize_bucket(bucket)
                data["daily_buckets"] = normalized_buckets
                data.setdefault("recent_trace_ids", [])
                return data
        except Exception:
            pass
        return self._empty_summary()

    def _empty_bucket(self) -> dict[str, Any]:
        return {
            "lanes": {lane: self._empty_lane() for lane in LANES},
            "cohorts": {cohort: self._empty_lane() for cohort in COHORTS},
        }

    def _normalize_bucket(self, bucket: Mapping[str, Any]) -> dict[str, Any]:
        result = self._empty_bucket()
        for group in ("lanes", "cohorts"):
            source = bucket.get(group)
            if not isinstance(source, Mapping):
                continue
            for key, defaults in result[group].items():
                values = source.get(key)
                if not isinstance(values, Mapping):
                    continue
                merged = dict(defaults)
                for metric, default in defaults.items():
                    value = values.get(metric, default)
                    merged[metric] = dict(value) if metric == "top_blockers" and isinstance(value, Mapping) else value
                result[group][key] = merged
        return result

    @staticmethod
    def _increment(summary: dict[str, Any], record: Mapping[str, Any]) -> None:
        """Increment one bounded aggregate from a canonical worker trace."""
        summary["candidates_seen"] += 1
        summary["fresh_candidates"] += int(_text(record.get("freshness_result")).upper() in {"CURRENT", "FRESH"})
        summary["stale_candidates"] += int(_text(record.get("freshness_result")).upper() == "STALE")
        summary["eligible"] += int(record.get("eligibility_result") == "PASS")
        summary["selected"] += int(record.get("selection_result") == "SELECTED")
        summary["order_ready"] += int(record.get("order_readiness_result") == "ORDER_READY")
        summary["submission_attempted"] += int(bool(record.get("submission_attempted")))
        summary["submitted"] += int(_text(record.get("submission_result")).lower() in {"submitted", "accepted"})
        summary["rejected_by_broker"] += int(_text(record.get("submission_result")).lower() == "rejected")
        summary["filled_entries"] += int(bool(_text(record.get("entry_fill_id"))))
        summary["open_lane_positions"] += int(bool(_text(record.get("position_id"))))
        summary["exit_orders"] += int(bool(_text(record.get("exit_order_id"))))
        summary["filled_exits"] += int(bool(_text(record.get("exit_fill_id"))))
        summary["completed_lifecycles"] += int(bool(_text(record.get("entry_fill_id")) and _text(record.get("exit_fill_id"))))
        summary["strict_broker_truths"] += int(_text(record.get("truth_status")).upper() == "BROKER_CONFIRMED_COMPLETE")
        summary["learning_deliveries"] += int(_text(record.get("learning_delivery_status")).upper() in {"DELIVERED", "ACKNOWLEDGED"})
        summary["duplicate_attempts"] += int(record.get("duplicate_exposure_result") == "BLOCKED")
        capacity_decision = _text(record.get("capacity_decision"))
        summary["blocked_by_global_capacity"] += int(capacity_decision == "GLOBAL_CAPACITY_EXHAUSTED")
        summary["allowed_by_lane_reserve"] += int(capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
        summary["blocked_by_lane_reserve"] += int(capacity_decision in {"LANE_RESERVE_EXHAUSTED", "CAPITAL_NOT_CONFIGURED"})
        summary["blocked_by_buying_power"] += int(capacity_decision in {"BUYING_POWER_INSUFFICIENT", "BUYING_POWER_UNAVAILABLE"})
        summary["blocked_by_global_risk"] += int(capacity_decision == "GLOBAL_RISK_BLOCKED")
        summary["blocked_by_duplicate_exposure"] += int(capacity_decision == "DUPLICATE_EXPOSURE_BLOCKED")
        summary["reserve_order_ready_count"] += int(record.get("order_readiness_result") == "ORDER_READY" and capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
        summary["reserve_submission_attempt_count"] += int(bool(record.get("submission_attempted")) and capacity_decision == "AVAILABLE_FROM_LANE_RESERVE")
        summary["reserve_commitments_requested"] += int(bool(_text(record.get("commitment_id"))))
        summary["reserve_commitments_released"] += int(_text(record.get("commitment_state")) == "RELEASED" or _text(record.get("commitment_final_state")) == "RELEASED")
        summary["reserve_commitments_pending"] += int(_text(record.get("commitment_state")) == "CONVERTED_TO_PENDING_ORDER")
        summary["false_reserve_exhaustion_contradictions"] += int(
            capacity_decision == "LANE_RESERVE_EXHAUSTED"
            and bool(record.get("lane_reserve_enabled"))
            and (record.get("lane_capital_remaining") or 0) > 0
            and (record.get("lane_positions_remaining") or 0) > 0
            and (record.get("lane_open_position_count") or 0) == 0
            and (record.get("lane_pending_order_count") or 0) == 0
            and (record.get("lane_active_commitment_count") or 0) == 0
        )
        summary["metadata_failures"] += int(not _text(record.get("candidate_id")) or not _text(record.get("recommendation_id")))
        blocker = _text(record.get("exact_blocker"))
        if blocker:
            blockers = summary.setdefault("top_blockers", {})
            blockers[blocker] = int(blockers.get(blocker, 0)) + 1

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
                "instrument_type": _text(source.get("instrument_type")),
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
            self._increment(lane_summary, record)
            cohort = _cohort_id(lane, record["asset_class"], record["instrument_type"])
            cohort_summary = summary["cohorts"].setdefault(cohort, self._empty_lane())
            self._increment(cohort_summary, record)
            day = _text(record["timestamp_utc"])[:10]
            bucket = summary.setdefault("daily_buckets", {}).setdefault(day, self._empty_bucket())
            self._increment(bucket["lanes"].setdefault(lane, self._empty_lane()), record)
            self._increment(bucket["cohorts"].setdefault(cohort, self._empty_lane()), record)
            appended += 1
        if records:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")
        summary["total_trace_rows"] = int(summary.get("total_trace_rows", 0)) + appended
        summary["duplicate_trace_rows_suppressed"] = int(summary.get("duplicate_trace_rows_suppressed", 0)) + suppressed
        summary["recent_trace_ids"] = recent[-MAX_RECENT_IDS:]
        summary["daily_buckets"] = {
            day: summary["daily_buckets"][day]
            for day in sorted(summary.get("daily_buckets", {}))[-MAX_DAILY_BUCKETS:]
        }
        summary["generated_at"] = _now()
        self._write_summary(summary)
        return {"appended": appended, "suppressed": suppressed}

    def summary(self) -> dict[str, Any]:
        result = self._read_summary()
        result["ledger_path"] = self.path
        result["bounded_summary_read"] = True
        return result

    def window_summary(self, *, days: int = 7, now: datetime | None = None) -> dict[str, Any]:
        """Return today and rolling aggregates from the compact worker index."""
        result = self._read_summary()
        today = (now or datetime.now(timezone.utc)).date().isoformat()
        keys = [key for key in sorted(result.get("daily_buckets", {})) if key <= today][-max(1, int(days)):]

        def aggregate(group: str, identifier: str) -> dict[str, Any]:
            values = self._empty_lane()
            for day in keys:
                bucket = result.get("daily_buckets", {}).get(day, {})
                row = bucket.get(group, {}).get(identifier, {}) if isinstance(bucket, Mapping) else {}
                for metric, default in self._empty_lane().items():
                    if metric == "top_blockers":
                        for blocker, count in (row.get(metric, {}) or {}).items():
                            values[metric][blocker] = int(values[metric].get(blocker, 0)) + int(count or 0)
                    else:
                        values[metric] += int(row.get(metric, 0) or 0)
            return values

        return {
            "today": today,
            "window_days": len(keys),
            "history_status": "WARMING_UP" if not keys else "AVAILABLE",
            "lanes": {lane: aggregate("lanes", lane) for lane in LANES},
            "cohorts": {cohort: aggregate("cohorts", cohort) for cohort in COHORTS},
            "bounded_summary_read": True,
            "full_history_scan_count": 0,
        }
