"""Strict registry for non-behavioral, derived-state integrity corrections."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ALLOWED_CORRECTIONS = {
    "REJECT_NONCANONICAL_CLAIM", "BLOCK_NONCANONICAL_PUBLICATION", "INVALIDATE_DERIVED_CACHE",
    "REBUILD_DERIVED_DIAGNOSTIC", "REMOVE_STALE_DERIVED_CACHE_ENTRY", "RESTORE_CANONICAL_METADATA",
    "QUARANTINE_DERIVED_CONSUMER", "RELABEL_DIAGNOSTIC_ONLY", "REOPEN_RECURRENCE",
    "ESCALATE_RECURRENCE", "DEDUPLICATE_DIAGNOSTIC_ISSUES", "CORRECT_DERIVED_ARITHMETIC",
    "BLOCK_FALSE_EXECUTIVE_PASS",
}
GUARDED_LEVEL_2_CORRECTIONS = {
    "SWITCH_TO_REGISTERED_CANONICAL_READER", "RESTORE_DROPPED_CANONICAL_FIELDS",
    "REPAIR_SCHEMA_ALIAS", "CORRECT_DERIVED_ENDPOINT_CALCULATION",
    "QUARANTINE_NONCOMPLIANT_DERIVED_CONSUMER", "REPAIR_EXPLICIT_CONTRACT_WIRING",
}
PROHIBITED_CORRECTIONS = {
    "EDIT_BROKER_FILL", "INVENT_ORDER_ID", "INVENT_FILL_ID", "ALTER_POSITION_STATUS", "CLOSE_POSITION",
    "DELETE_POSITION", "CHANGE_QUANTITY", "REWRITE_BROKER_TRUTH", "REWRITE_LIFECYCLE_EVIDENCE",
    "VERIFY_PROVISIONAL_ENTRY", "PROMOTE_SHADOW_EVIDENCE", "CHANGE_THRESHOLD", "CHANGE_CAPITAL",
    "CHANGE_SIZING", "ACTIVATE_LANE", "PLACE_ORDER", "CANCEL_ORDER", "TRIGGER_EXIT",
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


class SafeCorrectionRegistryV1:
    """Worker-only transaction journal. It cannot mutate broker or lifecycle truth."""
    def __init__(self, state_dir: str | Path = "state") -> None:
        self.path = Path(state_dir) / "astra_safe_correction_transactions_v1.json"

    def load(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return {"schema_version": "1.0.0", "transactions": []}

    def prepare(self, root_cause_id: str, correction_type: str, *, target_component: str, target_artifact: str, before_state: dict[str, Any], after_state: dict[str, Any]) -> dict[str, Any]:
        allowed = correction_type in ALLOWED_CORRECTIONS and correction_type not in PROHIBITED_CORRECTIONS
        digest = hashlib.sha256(json.dumps([root_cause_id, correction_type, target_component, target_artifact], sort_keys=True).encode()).hexdigest()[:16]
        return {"correction_id": f"correction-{digest}", "root_cause_id": root_cause_id, "correction_type": correction_type,
                "target_component": target_component, "target_artifact": target_artifact, "precondition_checks": ["canonical facts current", "nonbehavioral target"],
                "canonical_facts_used": [], "before_state": before_state, "proposed_after_state": after_state,
                "correction_level": "LEVEL_1", "behavioral_change": False, "broker_truth_change": False, "historical_truth_change": False,
                "trading_policy_change": False, "allowed_by_registry": allowed, "dry_run_passed": allowed,
                "applied": False, "verification_state": "PENDING" if allowed else "HUMAN_REPAIR_REQUIRED",
                "rollback_available": True, "created_at": _now()}

    def record(self, transaction: dict[str, Any]) -> dict[str, Any]:
        current = self.load(); rows = [dict(row) for row in current.get("transactions") or [] if isinstance(row, dict)]
        existing = {str(row.get("correction_id")): row for row in rows}
        item = dict(transaction)
        if item.get("allowed_by_registry") and item.get("correction_level") == "LEVEL_1":
            item["applied"] = True  # Registry application is a diagnostic publication decision only.
            item["verification_state"] = "VERIFYING"
        existing[str(item.get("correction_id"))] = item
        payload = {"schema_version": "1.0.0", "generated_at": _now(), "transactions": list(existing.values())[-100:]}
        _atomic(self.path, payload)
        return payload

    def prepare_guarded(
        self, root_cause_id: str, correction_type: str, *, target_component: str,
        target_artifact: str, before_state: dict[str, Any], after_state: dict[str, Any],
        confidence: str, blast_radius: dict[str, Any], dry_run_passed: bool,
    ) -> dict[str, Any]:
        """Create a Level 2 transaction. Application stays caller-owned.

        This generic transaction contract has no access to broker, lifecycle,
        or trading objects.  A caller supplies deterministic in-memory or
        derived-state callbacks to ``apply_guarded`` after Governance/Cortex
        have accepted the same root cause.
        """
        allowed = correction_type in GUARDED_LEVEL_2_CORRECTIONS
        confidence_ok = str(confidence).upper() in {"HIGH", "VERIFIED"}
        radius_ok = bool(blast_radius.get("known")) and bool(blast_radius.get("rollback_available"))
        digest = hashlib.sha256(json.dumps([root_cause_id, correction_type, target_component, target_artifact], sort_keys=True).encode()).hexdigest()[:16]
        return {
            "correction_id": f"correction-{digest}", "verification_id": f"verification-{digest}",
            "root_cause_id": root_cause_id, "correction_type": correction_type,
            "correction_level": "LEVEL_2", "target_component": target_component,
            "target_artifact": target_artifact, "confidence": str(confidence).upper(),
            "blast_radius": dict(blast_radius), "precondition_checks": ["canonical source unambiguous", "nonbehavioral target", "Governance authorization", "Cortex agreement", "canary comparison"],
            "canonical_facts_used": list(blast_radius.get("canonical_facts_used") or []),
            "before_state": dict(before_state), "proposed_after_state": dict(after_state),
            "behavioral_change": False, "broker_truth_change": False, "historical_truth_change": False,
            "trading_policy_change": False, "allowed_by_registry": allowed,
            "dry_run_passed": bool(dry_run_passed), "governance_authorized": False,
            "cortex_agreed": False, "canary_passed": False, "applied": False,
            "verification_state": "PENDING_AUTHORIZATION" if allowed and confidence_ok and radius_ok and dry_run_passed else "HUMAN_REPAIR_REQUIRED",
            "rollback_available": bool(blast_radius.get("rollback_available")), "failure_count": 0,
            "correction_loop_detected": False, "automatic_correction_disabled": False,
            "created_at": _now(),
        }

    def apply_guarded(self, transaction: dict[str, Any], *, governance_authorized: bool, cortex_agreed: bool, canary_passed: bool, apply_callback: Any) -> dict[str, Any]:
        """Apply one deterministic nonbehavioral derived-state repair.

        ``apply_callback`` must be bounded and reversible by a separately
        recorded rollback callback held by the worker.  This registry refuses
        all plans lacking each guard; it never supplies a production repair by
        itself.
        """
        item = dict(transaction)
        guards = bool(item.get("allowed_by_registry")) and bool(item.get("dry_run_passed")) and bool(governance_authorized) and bool(cortex_agreed) and bool(canary_passed) and bool(item.get("rollback_available"))
        item.update({"governance_authorized": bool(governance_authorized), "cortex_agreed": bool(cortex_agreed), "canary_passed": bool(canary_passed)})
        if not guards:
            item["verification_state"] = "HUMAN_REPAIR_REQUIRED"
            return self.record(item)["transactions"][-1]
        try:
            apply_callback()
            item.update({"applied": True, "verification_state": "VERIFYING", "applied_at": _now()})
        except Exception as exc:
            item.update({"applied": False, "verification_state": "HUMAN_REPAIR_REQUIRED", "application_error": str(exc)[:180], "failure_count": int(item.get("failure_count") or 0) + 1})
        return self.record(item)["transactions"][-1]

    def verify_guarded(self, correction_id: str, *, verification_passed: bool, rollback_callback: Any | None = None, max_failures: int = 2) -> dict[str, Any] | None:
        """Advance a Level 2 correction only after later worker observations."""
        current = self.load(); rows = [dict(row) for row in current.get("transactions") or [] if isinstance(row, dict)]
        item = next((row for row in rows if str(row.get("correction_id")) == str(correction_id)), None)
        if item is None:
            return None
        if verification_passed:
            item["verification_state"] = "VERIFIED"
            item["verified_at"] = _now()
        else:
            try:
                if callable(rollback_callback):
                    rollback_callback()
                item["rolled_back_at"] = _now()
            except Exception as exc:
                item["rollback_error"] = str(exc)[:180]
            failures = int(item.get("failure_count") or 0) + 1
            item.update({"failure_count": failures, "verification_state": "HUMAN_REPAIR_REQUIRED" if failures >= max(1, int(max_failures)) else "ROLLBACK_APPLIED", "correction_loop_detected": failures >= max(1, int(max_failures)), "automatic_correction_disabled": failures >= max(1, int(max_failures))})
        return self.record(item)["transactions"][-1]
