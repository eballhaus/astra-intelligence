"""Workstream registry operations for the Multi-Agent OS."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .common import ops_dir, load_yaml, save_yaml, VALID_STATUSES, VALID_MODELS, VALID_RISK_LEVELS


REGISTRY_FILES = {
    "active": "active_workstreams.yaml",
    "completed": "completed_workstreams.yaml",
    "file_ownership": "file_ownership.yaml",
    "contract_ownership": "contract_ownership.yaml",
    "integration_queue": "integration_queue.yaml",
    "model_roles": "model_roles.yaml",
    "rate_policy": "rate_policy.yaml",
    "forbidden_paths": "forbidden_paths.yaml",
}


def load_registry(name: str) -> dict[str, Any]:
    return load_yaml(ops_dir() / REGISTRY_FILES[name])


def save_registry(name: str, payload: dict[str, Any]) -> None:
    save_yaml(ops_dir() / REGISTRY_FILES[name], payload)


def get_active_workstreams() -> list[dict[str, Any]]:
    data = load_registry("active")
    return list(data.get("workstreams", []))


def get_completed_workstreams() -> list[dict[str, Any]]:
    data = load_registry("completed")
    return list(data.get("workstreams", []))


def get_workstream(workstream_id: str) -> dict[str, Any] | None:
    for ws in get_active_workstreams() + get_completed_workstreams():
        if ws.get("id") == workstream_id:
            return ws
    return None


def register_workstream(workstream: dict[str, Any]) -> dict[str, Any]:
    data = load_registry("active")
    workstreams = list(data.get("workstreams", []))
    workstreams = [ws for ws in workstreams if ws.get("id") != workstream.get("id")]
    workstreams.append(workstream)
    data["workstreams"] = workstreams
    save_registry("active", data)
    return {"ok": True, "registered": workstream["id"]}


def update_workstream_status(workstream_id: str, status: str) -> dict[str, Any]:
    data = load_registry("active")
    workstreams = list(data.get("workstreams", []))
    for ws in workstreams:
        if ws.get("id") == workstream_id:
            ws["status"] = status
            break
    else:
        return {"ok": False, "error": "workstream_not_found"}
    data["workstreams"] = workstreams
    save_registry("active", data)
    return {"ok": True, "id": workstream_id, "status": status}


def move_workstream_to_completed(workstream_id: str) -> dict[str, Any]:
    active_data = load_registry("active")
    completed_data = load_registry("completed")
    active_workstreams = list(active_data.get("workstreams", []))
    found = None
    new_active = []
    for ws in active_workstreams:
        if ws.get("id") == workstream_id:
            found = ws
        else:
            new_active.append(ws)
    if found is None:
        return {"ok": False, "error": "workstream_not_found_in_active"}
    found["status"] = "integrated"
    completed_workstreams = list(completed_data.get("workstreams", []))
    completed_workstreams = [ws for ws in completed_workstreams if ws.get("id") != workstream_id]
    completed_workstreams.append(found)
    active_data["workstreams"] = new_active
    completed_data["workstreams"] = completed_workstreams
    save_registry("active", active_data)
    save_registry("completed", completed_data)
    return {"ok": True, "id": workstream_id}


def build_ownership_registry() -> dict[str, Any]:
    """Build file and contract ownership maps from active workstreams."""
    file_map: dict[str, str] = {}
    pattern_map: dict[tuple[str, str], str] = {}
    contract_map: dict[str, str] = {}
    read_only: dict[str, set[str]] = {}

    for ws in get_active_workstreams():
        wid = ws.get("id", "")
        for f in ws.get("owned_files", []):
            file_map[f] = wid
        for p in ws.get("owned_patterns", []):
            pattern_map[(p, wid)] = wid
        for c in ws.get("owned_contracts", []):
            contract_map[c] = wid
        for f in ws.get("read_only_dependencies", []):
            read_only.setdefault(f, set()).add(wid)

    return {
        "files": file_map,
        "patterns": {k: v for k, v in pattern_map.items()},
        "contracts": contract_map,
        "read_only": {k: list(v) for k, v in read_only.items()},
    }


def refresh_ownership_registries() -> dict[str, Any]:
    ownership = build_ownership_registry()
    save_registry("file_ownership", {"registry": ownership["files"]})
    save_registry("contract_ownership", {"registry": ownership["contracts"]})
    return {"ok": True, "files": len(ownership["files"]), "contracts": len(ownership["contracts"])}


def load_model_roles() -> dict[str, Any]:
    return load_registry("model_roles")


def load_rate_policy() -> dict[str, Any]:
    return load_registry("rate_policy")


def load_forbidden_paths() -> dict[str, Any]:
    return load_registry("forbidden_paths")


def load_integration_queue() -> dict[str, Any]:
    return load_registry("integration_queue")


def save_integration_queue(payload: dict[str, Any]) -> None:
    save_registry("integration_queue", payload)
