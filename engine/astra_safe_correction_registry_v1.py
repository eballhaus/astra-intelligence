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
                "behavioral_change": False, "broker_truth_change": False, "historical_truth_change": False,
                "trading_policy_change": False, "allowed_by_registry": allowed, "dry_run_passed": allowed,
                "applied": False, "verification_state": "PENDING" if allowed else "HUMAN_REPAIR_REQUIRED",
                "rollback_available": True, "created_at": _now()}

    def record(self, transaction: dict[str, Any]) -> dict[str, Any]:
        current = self.load(); rows = [dict(row) for row in current.get("transactions") or [] if isinstance(row, dict)]
        existing = {str(row.get("correction_id")): row for row in rows}
        item = dict(transaction)
        if item.get("allowed_by_registry"):
            item["applied"] = True  # Registry application is a diagnostic publication decision only.
            item["verification_state"] = "VERIFYING"
        existing[str(item.get("correction_id"))] = item
        payload = {"schema_version": "1.0.0", "generated_at": _now(), "transactions": list(existing.values())[-100:]}
        _atomic(self.path, payload)
        return payload
