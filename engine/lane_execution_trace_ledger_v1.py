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
MAX_RECENT_DECISION_SNAPSHOT_IDS = 500
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


def _exact_blocker(source: Mapping[str, Any]) -> str:
    """Prefer the terminal order rejection without changing earlier gates."""
    # A partial worker turn intentionally evaluates evidence without reaching
    # the submission boundary.  Once its gates pass, it is waiting for the
    # canonical full cycle, not blocked by the stale observation that a final
    # hot refresh has already replaced.
    if bool(source.get("partial_cycle_observation_only")) and bool(source.get("eligible")):
        return "CANDIDATE_ELIGIBLE_AWAITING_FULL_CYCLE"
    for field in (
        "order_rejection_reason",
        "order_submission_rejection_reason",
        "broker_rejection_reason",
    ):
        value = _text(source.get(field))
        if value:
            return value
    return _text(
        source.get("order_readiness_reason")
        or source.get("decision_reason")
        or source.get("final_blocker_reason")
    )


def _decision_state(source: Mapping[str, Any], blocker: str) -> str:
    """Classify the observed worker result without changing any entry gate."""
    explicit = _text(source.get("candidate_decision") or source.get("decision"))
    if explicit.upper() in {"ACCEPTED", "REJECTED", "BLOCKED", "DEFERRED"}:
        return explicit.upper()
    if bool(source.get("partial_cycle_observation_only")) and bool(source.get("eligible")):
        return "DEFERRED"
    if bool(source.get("order_ready")) or bool(source.get("order_attempted")):
        return "ACCEPTED"
    if blocker or not bool(source.get("eligible")):
        return "BLOCKED"
    return "DEFERRED"


def _decision_snapshot_id(source: Mapping[str, Any], state: str, blocker: str) -> str:
    """Keep one immutable snapshot per candidate decision state, not per cycle."""
    return "decision:" + _fingerprint((
        source.get("candidate_id") or source.get("recommendation_id") or source.get("candidate_fingerprint"),
        source.get("symbol"), source.get("lane_id"), source.get("candidate_generated_at") or source.get("generated_at"),
        source.get("source_snapshot_id") or source.get("source_record_id"), state, blocker,
    ))


def _decision_snapshot(source: Mapping[str, Any], record: Mapping[str, Any], state: str, blocker: str) -> dict[str, Any]:
    """Copy bounded decision-time facts only; later outcomes live in outcome labels."""
    evidence = source.get("candidate_decision_evidence_v1")
    evidence = dict(evidence) if isinstance(evidence, Mapping) else {}
    lifecycle_id = _text(source.get("lifecycle_id") or record.get("lifecycle_id"))
    position_id = _text(source.get("position_id") or record.get("position_id"))
    truth_id = _text(source.get("truth_id") or record.get("truth_id"))
    if lifecycle_id and (position_id or truth_id):
        linkage = "EXACTLY_LINKED"
    elif lifecycle_id or position_id or truth_id:
        linkage = "PARTIALLY_LINKED"
    else:
        linkage = "UNLINKED"
    snapshot_id = _decision_snapshot_id(source, state, blocker)
    return {
        "schema_version": "astra_candidate_decision_snapshot_v1",
        "candidate_decision_snapshot_id": snapshot_id,
        "ledger_id": snapshot_id,
        "immutable_decision_snapshot": True,
        "decision_timestamp": _text(record.get("timestamp_utc")),
        "candidate_id": _text(record.get("candidate_id")) or None,
        "recommendation_id": _text(record.get("recommendation_id")) or None,
        "selection_id": _text(source.get("selection_id")) or None,
        "symbol": _text(record.get("symbol")) or None,
        "canonical_symbol": _text(record.get("canonical_symbol")) or None,
        "asset_class": _text(record.get("asset_class")) or None,
        "asset_type": _text(source.get("asset_type") or record.get("asset_class")) or None,
        "lane_id": _text(record.get("lane_id")) or None,
        "horizon": _text(source.get("paper_entry_horizon_style") or source.get("trade_horizon_style") or source.get("intended_horizon")) or None,
        "decision": state,
        "first_causal_blocker": blocker or None,
        "decision_reason": _text(source.get("decision_reason")) or None,
        "candidate_rank": evidence.get("candidate_rank"),
        "candidate_score": evidence.get("candidate_score"),
        "qualification_score": evidence.get("qualification_score"),
        "forecast_state": evidence.get("forecast_state"),
        "forecast_evidence_status": evidence.get("forecast_evidence_status"),
        "commitment_state": evidence.get("commitment_state"),
        "commitment_score": evidence.get("commitment_score"),
        "momentum_state": evidence.get("momentum_state"),
        "momentum_score": evidence.get("momentum_score"),
        "regime": evidence.get("regime"),
        "regime_alignment": evidence.get("regime_alignment"),
        "entry_quality": evidence.get("entry_quality"),
        "expected_return": evidence.get("expected_return"),
        "expected_hold": evidence.get("expected_hold"),
        "risk_contract_status": evidence.get("risk_contract_status"),
        "freshness_status": evidence.get("freshness_status"),
        "quote_timestamp": evidence.get("quote_timestamp"),
        "bar_timestamp": evidence.get("bar_timestamp"),
        "duplicate_exposure_state": evidence.get("duplicate_exposure_state") or source.get("duplicate_exposure_state"),
        "capacity_state": evidence.get("capacity_state") or source.get("capacity_decision"),
        "capital_state": evidence.get("capital_state") or source.get("capital_book_id"),
        "session_state": evidence.get("session_state") or source.get("session_state") or source.get("market_session_mode"),
        "crypto_gate_evidence": dict(evidence.get("crypto_gate_evidence") or {}),
        "source_ids": dict(evidence.get("source_ids") or {}),
        "price_at_decision": evidence.get("price_at_decision"),
        "lifecycle_id": lifecycle_id or None,
        "position_id": position_id or None,
        "entry_order_id": _text(source.get("broker_order_id") or record.get("broker_order_id")) or None,
        "entry_fill_id": _text(source.get("entry_fill_id") or record.get("entry_fill_id")) or None,
        "truth_id": truth_id or None,
        "trade_linkage_status": linkage,
        "later_outcome_state": "NOT_ATTACHED",
        "later_outcome_owner": "outcome_labels_v1.jsonl",
        "evidence_class": "DECISION_TIME_OBSERVATION",
        "missing_values_are_unavailable": True,
    }


class LaneExecutionTraceLedgerV1:
    """Bounded index over append-only operational traces; never broker truth."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.path = os.path.join(self.state_dir, "lane_execution_trace_v1.jsonl")
        self.summary_path = os.path.join(self.state_dir, "lane_execution_trace_v1.summary.json")
        # This is the existing canonical candidate ledger. The worker adds
        # compact decision snapshots; it does not create a second store.
        self.candidate_decision_ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")

    def _empty_summary(self) -> dict[str, Any]:
        return {
            "version": "v1",
            "generated_at": _now(),
            "total_trace_rows": 0,
            "duplicate_trace_rows_suppressed": 0,
            "recent_trace_ids": [],
            "recent_decision_snapshot_ids": [],
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
            "decision_snapshots": 0, "decision_accepted": 0, "decision_rejected": 0,
            "decision_blocked": 0, "decision_deferred": 0, "decision_exact_trade_links": 0,
            "decision_unresolved_links": 0,
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
                data.setdefault("recent_decision_snapshot_ids", [])
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
        snapshot = record.get("candidate_decision_snapshot_v1")
        if bool(record.get("candidate_decision_snapshot_recorded")) and isinstance(snapshot, Mapping):
            decision = _text(snapshot.get("decision")).upper()
            summary["decision_snapshots"] += 1
            summary["decision_accepted"] += int(decision == "ACCEPTED")
            summary["decision_rejected"] += int(decision == "REJECTED")
            summary["decision_blocked"] += int(decision == "BLOCKED")
            summary["decision_deferred"] += int(decision == "DEFERRED")
            summary["decision_exact_trade_links"] += int(snapshot.get("trade_linkage_status") == "EXACTLY_LINKED")
            summary["decision_unresolved_links"] += int(snapshot.get("trade_linkage_status") in {"PARTIALLY_LINKED", "UNLINKED"})
        blocker = _text(record.get("exact_blocker"))
        if blocker:
            blockers = summary.setdefault("top_blockers", {})
            blockers[blocker] = int(blockers.get(blocker, 0)) + 1

    @staticmethod
    def _increment_reconciled_entry_fill(summary: dict[str, Any]) -> None:
        """Count a broker-confirmed fill without re-counting its candidate."""
        summary["filled_entries"] += 1
        summary["open_lane_positions"] += 1

    def _write_summary(self, summary: Mapping[str, Any]) -> None:
        os.makedirs(self.state_dir, exist_ok=True)
        temp = f"{self.summary_path}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(dict(summary), handle, separators=(",", ":"), ensure_ascii=True)
        os.replace(temp, self.summary_path)

    def record(self, rows: Iterable[Mapping[str, Any]], *, cycle_id: str) -> dict[str, Any]:
        """Append unique worker traces and update a bounded daily summary."""
        summary = self._read_summary()
        recent = list(summary.get("recent_trace_ids") or [])[-MAX_RECENT_IDS:]
        known = set(recent)
        recent_decisions = list(summary.get("recent_decision_snapshot_ids") or [])[-MAX_RECENT_DECISION_SNAPSHOT_IDS:]
        known_decisions = set(recent_decisions)
        appended = suppressed = snapshots_written = snapshots_deduped = 0
        records: list[dict[str, Any]] = []
        decision_rows: list[dict[str, Any]] = []
        decision_by_lane: dict[str, int] = {lane: 0 for lane in LANES}
        decision_by_state: dict[str, int] = {state: 0 for state in ("ACCEPTED", "REJECTED", "BLOCKED", "DEFERRED")}
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
            blocker = _exact_blocker(source)
            decision_evidence = source.get("candidate_decision_evidence_v1")
            decision_evidence = dict(decision_evidence) if isinstance(decision_evidence, Mapping) else {}
            record = {
                "trace_id": trace_id, "timestamp_utc": _now(), "cycle_id": _text(cycle_id),
                "lane_id": lane, "candidate_id": candidate_id, "recommendation_id": recommendation_id,
                "symbol": symbol, "canonical_symbol": _text(source.get("canonical_symbol") or symbol).upper(),
                "asset_class": _text(source.get("asset_class") or source.get("asset_type")),
                "instrument_type": _text(source.get("instrument_type")),
                "candidate_source": _text(source.get("candidate_source")), "candidate_seen": True,
                "freshness_result": _text(
                    decision_evidence.get("freshness_status")
                    or source.get("candidate_snapshot_freshness")
                    or source.get("freshness_result")
                ),
                "eligibility_result": "PASS" if source.get("eligible") else "BLOCKED",
                "session_result": "PASS" if source.get("paper_order_submission_allowed") else _text(source.get("session_state") or source.get("market_session_mode") or "BLOCKED"),
                "capital_result": "PASS" if source.get("lane_activation_contract", {}).get("capital_configured", True) else "BLOCKED",
                "risk_result": "PASS" if source.get("eligible") else "NOT_REACHED",
                "duplicate_exposure_result": "BLOCKED" if source.get("duplicate_active_position") else "PASS",
                "selection_result": "SELECTED" if source.get("selected") else "NOT_SELECTED",
                "order_readiness_result": "ORDER_READY" if source.get("order_ready") else "NOT_READY",
                "submission_attempted": bool(source.get("order_attempted")),
                "submission_result": _text(source.get("order_result")),
                "order_rejection_reason": _text(source.get("order_rejection_reason")),
                "broker_error_sanitized": _text(source.get("broker_error_sanitized")),
                "broker_order_id": _text(source.get("broker_order_id")), "entry_fill_id": _text(source.get("entry_fill_id")),
                "position_id": _text(source.get("position_id")), "position_owner": _text(source.get("position_owner")),
                "lifecycle_id": _text(source.get("lifecycle_id")),
                "exit_trigger": _text(source.get("exit_trigger")), "exit_order_id": _text(source.get("exit_order_id")),
                "exit_fill_id": _text(source.get("exit_fill_id")), "truth_id": _text(source.get("truth_id")),
                "truth_status": _text(source.get("truth_status")), "learning_delivery_status": _text(source.get("learning_delivery_status")),
                "exact_blocker": blocker, "source_fingerprint": source_fingerprint,
                "partial_cycle_observation_only": bool(source.get("partial_cycle_observation_only")),
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
                "crypto_final_quote_refresh_attempted": bool(source.get("crypto_final_quote_refresh_attempted", False)),
                "crypto_final_quote_refresh_attempt_count": source.get("crypto_final_quote_refresh_attempt_count"),
                "crypto_final_quote_refresh_result": _text(source.get("crypto_final_quote_refresh_result")),
                "crypto_final_refresh_quote_timestamp": _text(source.get("crypto_final_refresh_quote_timestamp")),
                "crypto_final_refresh_quote_age_seconds": source.get("crypto_final_refresh_quote_age_seconds"),
                "hot_candidate_quote_refresh_lane": _text(source.get("hot_candidate_quote_refresh_lane")),
                "hot_candidate_quote_refresh_attempted": bool(source.get("hot_candidate_quote_refresh_attempted", False)),
                "hot_candidate_quote_refresh_attempt_count": source.get("hot_candidate_quote_refresh_attempt_count"),
                "hot_candidate_quote_refresh_result": _text(source.get("hot_candidate_quote_refresh_result")),
                "hot_candidate_quote_refresh_cache_bypass_requested": bool(source.get("hot_candidate_quote_refresh_cache_bypass_requested", False)),
                # Blocker-specific detail is produced by the worker and is
                # retained only in this existing bounded lane trace.
                "entry_commitment_trace_v1": dict(source.get("entry_commitment_trace_v1") or {}),
                "pretrade_contract_missing_fields_trace_v1": dict(source.get("pretrade_contract_missing_fields_trace_v1") or {}),
                "crypto_inner_freshness_trace_v1": dict(source.get("crypto_inner_freshness_trace_v1") or {}),
            }
            decision_state = _decision_state(source, blocker)
            snapshot = _decision_snapshot(source, record, decision_state, blocker)
            record["candidate_decision_snapshot_v1"] = snapshot
            snapshot_id = str(snapshot["candidate_decision_snapshot_id"])
            if snapshot_id not in known_decisions:
                # Retain compatibility fields for existing outcome labels while
                # keeping the immutable contract nested and self-contained.
                decision_rows.append({
                    **snapshot,
                    "timestamp_utc": snapshot["decision_timestamp"],
                    "canonical_state": decision_state.lower(),
                    "decision_status": decision_state,
                    "action": decision_state.lower(),
                    "final_action": decision_state.lower(),
                    "was_released": decision_state == "ACCEPTED",
                    "was_paper_ready": decision_state == "ACCEPTED",
                    "was_blocked": decision_state in {"REJECTED", "BLOCKED"},
                    "was_watchlist": decision_state == "DEFERRED",
                    "candidate_decision_snapshot_v1": dict(snapshot),
                })
                known_decisions.add(snapshot_id)
                recent_decisions.append(snapshot_id)
                snapshots_written += 1
                decision_by_lane[lane] = int(decision_by_lane.get(lane, 0)) + 1
                decision_by_state[decision_state] = int(decision_by_state.get(decision_state, 0)) + 1
                record["candidate_decision_snapshot_recorded"] = True
            else:
                snapshots_deduped += 1
                record["candidate_decision_snapshot_recorded"] = False
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
        if decision_rows:
            # Appending immutable records is observational. A write failure
            # must not affect the worker's trading result.
            try:
                os.makedirs(self.state_dir, exist_ok=True)
                with open(self.candidate_decision_ledger_path, "a", encoding="utf-8") as handle:
                    for decision in decision_rows:
                        handle.write(json.dumps(decision, separators=(",", ":"), ensure_ascii=True) + "\n")
            except OSError:
                # Keep the trace record; the summary reports only successful
                # writes, and no candidate outcome is inferred from failure.
                snapshots_deduped += snapshots_written
                snapshots_written = 0
        summary["total_trace_rows"] = int(summary.get("total_trace_rows", 0)) + appended
        summary["duplicate_trace_rows_suppressed"] = int(summary.get("duplicate_trace_rows_suppressed", 0)) + suppressed
        summary["recent_trace_ids"] = recent[-MAX_RECENT_IDS:]
        summary["recent_decision_snapshot_ids"] = recent_decisions[-MAX_RECENT_DECISION_SNAPSHOT_IDS:]
        summary["daily_buckets"] = {
            day: summary["daily_buckets"][day]
            for day in sorted(summary.get("daily_buckets", {}))[-MAX_DAILY_BUCKETS:]
        }
        summary["generated_at"] = _now()
        self._write_summary(summary)
        today_lanes = dict((summary.get("daily_buckets", {}).get(_now()[:10], {}) or {}).get("lanes", {}) or {})
        by_lane_today = {
            lane: int(dict(today_lanes.get(lane) or {}).get("decision_snapshots", 0))
            for lane in LANES
        }
        snapshots_today = sum(by_lane_today.values())
        return {
            "appended": appended,
            "suppressed": suppressed,
            "candidate_decision_evidence_v1": {
                "schema_version": "astra_candidate_decision_evidence_v1",
                "snapshots_written": snapshots_written,
                "snapshots_deduped": snapshots_deduped,
                "snapshots_today": snapshots_today,
                "accepted": int(decision_by_state["ACCEPTED"]),
                "rejected": int(decision_by_state["REJECTED"]),
                "blocked": int(decision_by_state["BLOCKED"]),
                "deferred": int(decision_by_state["DEFERRED"]),
                "by_lane": by_lane_today,
                "by_lane_current_cycle": {lane: int(decision_by_lane.get(lane, 0)) for lane in LANES},
                "later_outcomes_linked": 0,
                "exact_trade_links": sum(1 for row in decision_rows if row.get("trade_linkage_status") == "EXACTLY_LINKED"),
                "unresolved_links": sum(1 for row in decision_rows if row.get("trade_linkage_status") != "EXACTLY_LINKED"),
                "outcome_owner": "outcome_labels_v1.jsonl",
                "full_history_scan_count": 0,
                "provider_calls": 0,
                "broker_calls": 0,
                "llm_calls": 0,
            },
        }

    def record_reconciled_entry_fill(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Append the exact broker-fill transition produced after acknowledgement.

        A normal candidate trace is emitted at submission time, before a broker
        acknowledgement becomes a fill.  Reconciliation must therefore add a
        distinct, idempotent lifecycle event rather than replaying the candidate
        and inflating funnel counters or decision evidence.
        """
        lane = _text(row.get("lane_id")).upper()
        position_id = _text(row.get("position_id"))
        entry_fill_id = _text(row.get("entry_fill_id"))
        if lane not in LANES or not position_id or not entry_fill_id:
            return {"appended": 0, "suppressed": 0, "reason": "INCOMPLETE_EXACT_ENTRY_FILL_IDENTITY"}
        summary = self._read_summary()
        recent = list(summary.get("recent_trace_ids") or [])[-MAX_RECENT_IDS:]
        trace_id = "entry_fill_reconciled:" + _fingerprint((lane, position_id, entry_fill_id))
        if trace_id in set(recent):
            summary["duplicate_trace_rows_suppressed"] = int(summary.get("duplicate_trace_rows_suppressed", 0)) + 1
            summary["generated_at"] = _now()
            self._write_summary(summary)
            return {"appended": 0, "suppressed": 1, "trace_id": trace_id}
        symbol = _text(row.get("symbol")).upper()
        asset_class = _text(row.get("asset_class") or row.get("asset_type"))
        instrument_type = _text(row.get("instrument_type"))
        timestamp = _text(row.get("entry_filled_at") or row.get("entry_timestamp")) or _now()
        record = {
            "trace_id": trace_id,
            "timestamp_utc": timestamp,
            "event_type": "BROKER_ENTRY_FILL_RECONCILED",
            "lane_id": lane,
            "candidate_id": _text(row.get("candidate_id") or row.get("source_candidate_id")),
            "recommendation_id": _text(row.get("recommendation_id") or row.get("source_recommendation_id")),
            "symbol": symbol,
            "canonical_symbol": _text(row.get("canonical_symbol") or symbol).upper(),
            "asset_class": asset_class,
            "instrument_type": instrument_type,
            "position_id": position_id,
            "lifecycle_id": _text(row.get("lifecycle_id") or row.get("source_lifecycle_id") or position_id),
            "broker_order_id": _text(row.get("entry_order_id") or row.get("source_broker_order_id")),
            "entry_fill_id": entry_fill_id,
            "entry_filled_at": _text(row.get("entry_filled_at")),
            "entry_price_evidence_class": _text(row.get("entry_price_evidence_class")),
            "entry_price_verified": bool(row.get("entry_price_verified")),
            "candidate_seen": False,
            "reconciled_from_pending_entry": _text(row.get("prior_status")).upper() == "PENDING_ENTRY",
        }
        os.makedirs(self.state_dir, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True) + "\n")
        lane_summary = summary["lanes"].setdefault(lane, self._empty_lane())
        self._increment_reconciled_entry_fill(lane_summary)
        cohort = _cohort_id(lane, asset_class, instrument_type)
        cohort_summary = summary["cohorts"].setdefault(cohort, self._empty_lane())
        self._increment_reconciled_entry_fill(cohort_summary)
        day = timestamp[:10]
        bucket = summary.setdefault("daily_buckets", {}).setdefault(day, self._empty_bucket())
        self._increment_reconciled_entry_fill(bucket["lanes"].setdefault(lane, self._empty_lane()))
        self._increment_reconciled_entry_fill(bucket["cohorts"].setdefault(cohort, self._empty_lane()))
        summary["total_trace_rows"] = int(summary.get("total_trace_rows", 0)) + 1
        summary["recent_trace_ids"] = (recent + [trace_id])[-MAX_RECENT_IDS:]
        summary["daily_buckets"] = {
            day: summary["daily_buckets"][day]
            for day in sorted(summary.get("daily_buckets", {}))[-MAX_DAILY_BUCKETS:]
        }
        summary["generated_at"] = _now()
        self._write_summary(summary)
        return {"appended": 1, "suppressed": 0, "trace_id": trace_id}

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
