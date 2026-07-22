"""Acceptance ledger validation."""
from __future__ import annotations

from typing import Any


def validate_ledger(workstream: dict[str, Any]) -> dict[str, Any]:
    criteria = workstream.get("acceptance_criteria", [])
    if not isinstance(criteria, list):
        return {"valid": False, "errors": ["acceptance_criteria_must_be_list"]}

    errors: list[str] = []
    pass_count = 0
    fail_count = 0
    not_evaluated_count = 0
    blocked_count = 0

    for c in criteria:
        status = c.get("status", "NOT_EVALUATED")
        evidence = c.get("evidence") or []
        blocker = c.get("external_blocker")
        remaining = c.get("controllable_work_remaining") or []

        if status == "PASS":
            if not evidence:
                errors.append(f"PASS_without_evidence:{c.get('id')}")
            pass_count += 1
        elif status == "BLOCKED":
            if not blocker:
                errors.append(f"BLOCKED_without_external_reason:{c.get('id')}")
            blocked_count += 1
        elif status == "FAIL":
            fail_count += 1
        elif status == "NOT_EVALUATED":
            not_evaluated_count += 1

        if remaining:
            errors.append(f"controllable_work_remaining:{c.get('id')}:{'|'.join(remaining)}")

    status = workstream.get("status", "")
    if status == "implementation_complete" and (fail_count > 0 or not_evaluated_count > 0):
        errors.append("implementation_complete_with_incomplete_criteria")

    if status == "integration_ready":
        integration = workstream.get("integration", {})
        if integration.get("requires_independent_review") and workstream.get("review_status") != "passed":
            errors.append("integration_ready_without_required_review")

    return {
        "valid": not errors,
        "errors": errors,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "blocked_count": blocked_count,
        "not_evaluated_count": not_evaluated_count,
        "total": len(criteria),
    }


def can_finish(workstream: dict[str, Any]) -> dict[str, Any]:
    """Validate that a workstream may be marked implementation_complete."""
    errors: list[str] = []

    ledger = validate_ledger(workstream)
    if not ledger["valid"]:
        errors.extend(ledger["errors"])

    if workstream.get("status") not in {"active", "review_required", "review_failed"}:
        errors.append(f"cannot_finish_from_status:{workstream.get('status')}")

    return {
        "can_finish": not errors,
        "errors": errors,
        "ledger": ledger,
    }


def update_criterion_status(
    workstream: dict[str, Any],
    criterion_id: str,
    status: str,
    evidence: list[dict[str, Any]] | None = None,
    external_blocker: str | None = None,
) -> dict[str, Any]:
    criteria = workstream.get("acceptance_criteria", [])
    for c in criteria:
        if c.get("id") == criterion_id:
            c["status"] = status
            if evidence is not None:
                c["evidence"] = evidence
            if external_blocker is not None:
                c["external_blocker"] = external_blocker
            return {"ok": True, "criterion": criterion_id, "status": status}
    return {"ok": False, "error": "criterion_not_found"}
