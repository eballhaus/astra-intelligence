"""Validation logic for workstreams, ownership, and forbidden paths."""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .common import (
    ops_dir,
    repo_root,
    normalize_path,
    path_matches_pattern,
    VALID_STATUSES,
    VALID_MODELS,
    VALID_RISK_LEVELS,
    VALID_STATUS_TRANSITIONS,
    REQUIRED_WORKSTREAM_FIELDS,
)
from .registry import (
    get_active_workstreams,
    get_workstream,
    build_ownership_registry,
    load_forbidden_paths,
)


LIVE_CHECKOUT = "/Users/eric/Desktop/astra-intelligence-clean"


def validate_workstream_schema(workstream: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_WORKSTREAM_FIELDS:
        if field not in workstream:
            errors.append(f"missing_required_field:{field}")
    if workstream.get("status") not in VALID_STATUSES:
        errors.append(f"invalid_status:{workstream.get('status')}")
    if workstream.get("primary_model") not in VALID_MODELS:
        errors.append(f"invalid_primary_model:{workstream.get('primary_model')}")
    if workstream.get("risk_level") not in VALID_RISK_LEVELS:
        errors.append(f"invalid_risk_level:{workstream.get('risk_level')}")
    review_model = workstream.get("review_model")
    if review_model is not None and review_model not in VALID_MODELS:
        errors.append(f"invalid_review_model:{review_model}")
    integrator_model = workstream.get("integrator_model")
    if integrator_model is not None and integrator_model not in VALID_MODELS:
        errors.append(f"invalid_integrator_model:{integrator_model}")

    criteria = workstream.get("acceptance_criteria") or []
    if not isinstance(criteria, list):
        errors.append("acceptance_criteria_must_be_list")
    else:
        seen_ids: set[str] = set()
        for c in criteria:
            cid = c.get("id") if isinstance(c, dict) else None
            if not cid:
                errors.append("acceptance_criterion_missing_id")
            elif cid in seen_ids:
                errors.append(f"duplicate_criterion_id:{cid}")
            else:
                seen_ids.add(cid)
            if isinstance(c, dict) and c.get("status") not in {
                "PASS", "BLOCKED", "FAIL", "NOT_EVALUATED", None,
            }:
                errors.append(f"invalid_criterion_status:{c.get('status')}")

    owned_files = workstream.get("owned_files") or []
    if not isinstance(owned_files, list):
        errors.append("owned_files_must_be_list")
    owned_patterns = workstream.get("owned_patterns") or []
    if not isinstance(owned_patterns, list):
        errors.append("owned_patterns_must_be_list")
    owned_contracts = workstream.get("owned_contracts") or []
    if not isinstance(owned_contracts, list):
        errors.append("owned_contracts_must_be_list")

    return errors


def validate_forbidden_paths(workstream: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    forbidden = load_forbidden_paths()
    patterns = [item.get("pattern", "") for item in forbidden.get("forbidden_paths", [])]
    task_type = "normal"

    for f in workstream.get("owned_files", []):
        normalized = normalize_path(f)
        for pattern in patterns:
            if path_matches_pattern(normalized, pattern) or path_matches_pattern(f, pattern):
                errors.append(f"forbidden_path:{f}")
                break

    for p in workstream.get("owned_patterns", []):
        for pattern in patterns:
            if pattern.startswith("^"):
                if re.search(pattern, p):
                    errors.append(f"forbidden_pattern:{p}")
                    break
            elif "state/" in p or "diagnostics/" in p or ".env" in p or "logs/" in p:
                errors.append(f"forbidden_pattern:{p}")
                break

    worktree = workstream.get("worktree", "")
    if worktree == LIVE_CHECKOUT and task_type != "integration":
        errors.append("forbidden_worktree:live_checkout")

    return errors


def validate_ownership(workstream: dict[str, Any]) -> list[str]:
    """Check that the workstream does not conflict with other active workstreams."""
    errors: list[str] = []
    wid = workstream.get("id", "")
    owned_files = [normalize_path(f) for f in workstream.get("owned_files", [])]
    owned_patterns = workstream.get("owned_patterns", [])
    owned_contracts = workstream.get("owned_contracts", [])

    # Duplicate ownership within workstream.
    seen_files: set[str] = set()
    for f in owned_files:
        if f in seen_files:
            errors.append(f"duplicate_owned_file:{f}")
        seen_files.add(f)

    seen_contracts: set[str] = set()
    for c in owned_contracts:
        if c in seen_contracts:
            errors.append(f"duplicate_owned_contract:{c}")
        seen_contracts.add(c)

    for other in get_active_workstreams():
        if other.get("id") == wid:
            continue
        other_files = [normalize_path(f) for f in other.get("owned_files", [])]
        other_patterns = other.get("owned_patterns", [])
        other_contracts = other.get("owned_contracts", [])

        # Exact file conflicts.
        for f in owned_files:
            if f in other_files:
                errors.append(f"file_conflict:{f}:owner={other.get('id')}")

        # File vs pattern conflicts.
        for f in owned_files:
            for p in other_patterns:
                if path_matches_pattern(f, p):
                    errors.append(f"file_pattern_conflict:{f}:pattern={p}:owner={other.get('id')}")

        # Pattern vs file and pattern conflicts.
        for p in owned_patterns:
            for f2 in other_files:
                if path_matches_pattern(f2, p):
                    errors.append(f"pattern_file_conflict:{p}:file={f2}:owner={other.get('id')}")
            for p2 in other_patterns:
                if _patterns_overlap(p, p2):
                    errors.append(f"pattern_pattern_conflict:{p}:existing={p2}:owner={other.get('id')}")

        # Contract conflicts.
        for c in owned_contracts:
            if c in other_contracts:
                errors.append(f"contract_conflict:{c}:owner={other.get('id')}")

    return errors


def _patterns_overlap(a: str, b: str) -> bool:
    """Heuristic overlap check for two glob-ish patterns.

    Returns True if one pattern is a prefix/subset of the other.
    """
    a_norm = a.strip().rstrip("/")
    b_norm = b.strip().rstrip("/")
    if a_norm == b_norm:
        return True
    if a_norm.startswith(b_norm + "/") or b_norm.startswith(a_norm + "/"):
        return True
    return False


def validate_dependencies(workstream: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for dep_id in workstream.get("depends_on", []):
        dep = get_workstream(dep_id)
        if dep is None:
            errors.append(f"missing_dependency:{dep_id}")
        elif dep.get("status") not in {"integrated", "integrating"}:
            errors.append(f"incomplete_dependency:{dep_id}:status={dep.get('status')}")

    seen: set[str] = set()
    stack = [workstream.get("id")]
    while stack:
        current_id = stack.pop()
        if current_id in seen:
            errors.append("circular_dependency")
            break
        seen.add(current_id)
        current = get_workstream(current_id)
        if current:
            for dep_id in current.get("depends_on", []):
                stack.append(dep_id)
    return errors


def validate_status_transition(workstream_id: str, new_status: str) -> list[str]:
    ws = get_workstream(workstream_id)
    if ws is None:
        return ["workstream_not_found"]
    current = ws.get("status", "proposed")
    allowed = VALID_STATUS_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        return [f"invalid_status_transition:{current}->{new_status}"]
    return []


def validate_worktree(workstream: dict[str, Any]) -> dict[str, Any]:
    """Validate worktree existence, branch, cleanliness, and base commit.

    Uses read-only Git commands only.
    """
    path = workstream.get("worktree", "")
    expected_branch = workstream.get("branch", "")
    expected_commit = workstream.get("base_commit", "")
    wid = workstream.get("id", "")

    result = {
        "worktree_exists": False,
        "is_git_worktree": False,
        "branch_matches": False,
        "head_matches_base": False,
        "clean": False,
        "not_live_checkout": path != LIVE_CHECKOUT,
        "not_duplicate_assignment": True,
        "stale_base": False,
        "errors": [],
    }

    if not path or not os.path.isdir(path):
        result["errors"].append("worktree_does_not_exist")
        return result
    result["worktree_exists"] = True

    git_dir = os.path.join(path, ".git")
    if not os.path.exists(git_dir) and not os.path.isfile(git_dir):
        result["errors"].append("not_a_git_worktree")
        return result
    result["is_git_worktree"] = True

    try:
        actual_branch = subprocess.check_output(
            ["git", "-C", path, "branch", "--show-current"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        result["branch_matches"] = actual_branch == expected_branch
        if not result["branch_matches"]:
            result["errors"].append(f"branch_mismatch:expected={expected_branch}:actual={actual_branch}")

        head = subprocess.check_output(
            ["git", "-C", path, "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        result["head_matches_base"] = head == expected_commit
        if not result["head_matches_base"]:
            result["errors"].append(f"commit_mismatch:expected={expected_commit}:actual={head}")

        status = subprocess.check_output(
            ["git", "-C", path, "status", "--short"],
            text=True,
            stderr=subprocess.PIPE,
        ).strip()
        result["clean"] = not status
        if not result["clean"]:
            result["errors"].append("worktree_dirty")

        # Stale base check against origin/main.
        try:
            merge_base = subprocess.check_output(
                ["git", "-C", path, "merge-base", "HEAD", "origin/main"],
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
            origin_main = subprocess.check_output(
                ["git", "-C", path, "rev-parse", "origin/main"],
                text=True,
                stderr=subprocess.PIPE,
            ).strip()
            result["stale_base"] = merge_base != origin_main
            if result["stale_base"]:
                result["errors"].append("stale_base:REBASE_OR_REFRESH_REQUIRED")
        except subprocess.CalledProcessError:
            result["errors"].append("cannot_determine_stale_base")

    except subprocess.CalledProcessError as exc:
        result["errors"].append(f"git_command_failed:{exc.stderr.strip()[:120]}")

    # Duplicate worktree/branch assignment across active workstreams.
    for other in get_active_workstreams():
        if other.get("id") == wid:
            continue
        if other.get("worktree") == path:
            result["not_duplicate_assignment"] = False
            result["errors"].append(f"duplicate_worktree_assignment:{other.get('id')}")
        if other.get("branch") == expected_branch:
            result["not_duplicate_assignment"] = False
            result["errors"].append(f"duplicate_branch_assignment:{other.get('id')}")

    return result


def validate_workstream(workstream: dict[str, Any], *, include_worktree: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    errors.extend(validate_workstream_schema(workstream))
    errors.extend(validate_forbidden_paths(workstream))
    errors.extend(validate_ownership(workstream))
    errors.extend(validate_dependencies(workstream))

    worktree_result = None
    if include_worktree:
        worktree_result = validate_worktree(workstream)
        errors.extend(worktree_result.get("errors", []))

    return {
        "valid": not errors,
        "workstream_id": workstream.get("id"),
        "errors": errors,
        "worktree": worktree_result,
    }


def can_start(workstream_id: str) -> dict[str, Any]:
    ws = get_workstream(workstream_id)
    if ws is None:
        return {"ok": False, "errors": ["workstream_not_found"]}
    if ws.get("status") != "validated":
        return {"ok": False, "errors": [f"status_not_validated:{ws.get('status')}"]}
    return validate_workstream(ws, include_worktree=True)
