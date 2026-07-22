"""Integration queue logic."""
from __future__ import annotations

from typing import Any

from .registry import load_integration_queue, save_integration_queue, get_workstream
from .ledger import validate_ledger


INTEGRATION_STATUSES = {
    "READY",
    "WAITING_FOR_REVIEW",
    "WAITING_FOR_DEPENDENCY",
    "STALE_BASE",
    "OWNERSHIP_CONFLICT",
    "NOT_SAFE_FOR_INTEGRATION",
}


def get_integration_status(workstream_id: str) -> dict[str, Any]:
    ws = get_workstream(workstream_id)
    if ws is None:
        return {"status": "NOT_SAFE_FOR_INTEGRATION", "errors": ["workstream_not_found"]}

    errors: list[str] = []

    if ws.get("status") != "review_passed":
        errors.append(f"status_not_review_passed:{ws.get('status')}")
        return {"status": "WAITING_FOR_REVIEW", "errors": errors}

    ledger = validate_ledger(ws)
    if not ledger["valid"]:
        errors.extend(ledger["errors"])
        return {"status": "NOT_SAFE_FOR_INTEGRATION", "errors": errors}

    integration = ws.get("integration", {})
    if integration.get("requires_independent_review") and ws.get("review_status") != "passed":
        errors.append("independent_review_required")
        return {"status": "WAITING_FOR_REVIEW", "errors": errors}

    if integration.get("requires_full_suite_at_integration") and not ws.get("full_suite_passed"):
        errors.append("full_suite_required")

    return {"status": "READY" if not errors else "NOT_SAFE_FOR_INTEGRATION", "errors": errors}


def add_to_queue(workstream_id: str) -> dict[str, Any]:
    status = get_integration_status(workstream_id)
    if status["status"] != "READY":
        return {"ok": False, "status": status["status"], "errors": status["errors"]}

    queue_data = load_integration_queue()
    queue = list(queue_data.get("queue", []))
    for item in queue:
        if item.get("id") == workstream_id:
            return {"ok": False, "error": "already_in_queue"}

    ws = get_workstream(workstream_id)
    integration = ws.get("integration", {}) if ws else {}
    queue.append({
        "id": workstream_id,
        "branch": ws.get("branch") if ws else None,
        "commit": ws.get("base_commit") if ws else None,
        "risk_level": ws.get("risk_level") if ws else None,
        "review_status": ws.get("review_status") if ws else None,
        "integration_status": "queued",
        "integration_order": integration.get("order", 100),
        "requires_full_suite": integration.get("requires_full_suite_at_integration", False),
        "requires_runtime_verification": integration.get("runtime_restart_expected", False),
        "requires_restart": integration.get("runtime_restart_expected", False),
        "blocked_by": [],
    })
    queue.sort(key=lambda x: x["integration_order"])
    queue_data["queue"] = queue
    save_integration_queue(queue_data)
    return {"ok": True, "id": workstream_id, "queue_position": len(queue)}


def remove_from_queue(workstream_id: str) -> dict[str, Any]:
    queue_data = load_integration_queue()
    queue = [item for item in queue_data.get("queue", []) if item.get("id") != workstream_id]
    if len(queue) == len(queue_data.get("queue", [])):
        return {"ok": False, "error": "not_in_queue"}
    queue_data["queue"] = queue
    save_integration_queue(queue_data)
    return {"ok": True, "id": workstream_id}


def get_queue_status() -> dict[str, Any]:
    queue_data = load_integration_queue()
    return {
        "integrator": queue_data.get("integrator"),
        "current": queue_data.get("current"),
        "queue": queue_data.get("queue", []),
        "history": queue_data.get("history", []),
    }


def set_current_integrating(workstream_id: str) -> dict[str, Any]:
    queue_data = load_integration_queue()
    queue = list(queue_data.get("queue", []))
    current = None
    for item in queue:
        if item.get("id") == workstream_id:
            current = item
            item["integration_status"] = "integrating"
            break
    if current is None:
        return {"ok": False, "error": "not_in_queue"}
    queue_data["current"] = current
    queue_data["queue"] = queue
    save_integration_queue(queue_data)
    return {"ok": True, "id": workstream_id}


def complete_integration(workstream_id: str, success: bool = True) -> dict[str, Any]:
    queue_data = load_integration_queue()
    queue = [item for item in queue_data.get("queue", []) if item.get("id") != workstream_id]
    current = queue_data.get("current")
    if current and current.get("id") == workstream_id:
        current["integration_status"] = "integrated" if success else "failed"
        history = list(queue_data.get("history", []))
        history.append(current)
        queue_data["history"] = history
    queue_data["current"] = None
    queue_data["queue"] = queue
    save_integration_queue(queue_data)
    return {"ok": True, "id": workstream_id, "success": success}
