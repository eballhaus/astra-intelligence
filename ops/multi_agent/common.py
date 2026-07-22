"""Common utilities for the Astra Multi-Agent Operating System."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any


OPS_DIR = Path("ops/multi_agent")


def repo_root() -> Path:
    """Return the repository root by finding the .git directory upward."""
    start = Path.cwd()
    for path in [start] + list(start.parents):
        if (path / ".git").exists():
            return path
    raise RuntimeError("Not inside a Git repository")


def ops_dir() -> Path:
    return repo_root() / OPS_DIR


def load_yaml(path: Path) -> Any:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, payload: Any) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, default_flow_style=False, sort_keys=False)


def normalize_path(value: str) -> str:
    """Normalize a path string for comparison."""
    return os.path.normpath(value.strip()).lstrip("/")


def path_matches_pattern(file_path: str, pattern: str) -> bool:
    """Check if a file path matches a glob-ish or regex pattern.

    Supports exact match, glob patterns with * and **, and regex patterns
    starting with ^.
    """
    file_path = normalize_path(file_path)
    pattern = pattern.strip()
    if pattern.startswith("^"):
        return bool(re.search(pattern, file_path))
    if pattern.endswith("/"):
        pattern = pattern.rstrip("/") + "/**"
    return _glob_match(file_path, pattern)


def _glob_match(file_path: str, pattern: str) -> bool:
    path_parts = file_path.split("/")
    pat_parts = pattern.split("/")

    def part_match(name: str, pat: str) -> bool:
        if pat == "**":
            return True
        if "*" in pat or "?" in pat or "[" in pat:
            regex = "^" + re.escape(pat).replace(r"\*", "[^/]*").replace(r"\?", ".").replace(r"\[", "[").replace(r"\]", "]") + "$"
            return bool(re.match(regex, name))
        return name == pat

    def match_parts(pp: list[str], sp: list[str]) -> bool:
        if not pp:
            return not sp
        if pp[0] == "**":
            for i in range(len(sp) + 1):
                if match_parts(pp[1:], sp[i:]):
                    return True
            return False
        if not sp:
            return False
        if part_match(sp[0], pp[0]):
            return match_parts(pp[1:], sp[1:])
        return False

    return match_parts(pat_parts, path_parts)


def fail(message: str, code: int = 1) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    sys.exit(code)


VALID_STATUSES = {
    "proposed",
    "validated",
    "active",
    "implementation_complete",
    "review_required",
    "review_failed",
    "review_passed",
    "integration_ready",
    "integrating",
    "integrated",
    "blocked",
    "failed",
    "cancelled",
}

VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"validated", "active", "blocked", "cancelled"},
    "validated": {"active", "blocked", "cancelled"},
    "active": {"implementation_complete", "blocked", "failed", "cancelled"},
    "implementation_complete": {"review_required", "blocked", "failed", "cancelled"},
    "review_required": {"review_failed", "review_passed", "blocked", "cancelled"},
    "review_failed": {"active", "blocked", "failed", "cancelled"},
    "review_passed": {"integration_ready", "blocked", "cancelled"},
    "integration_ready": {"integrating", "blocked", "cancelled"},
    "integrating": {"integrated", "blocked", "failed", "cancelled"},
    "integrated": set(),
    "blocked": {"active", "cancelled"},
    "failed": {"proposed", "cancelled"},
    "cancelled": set(),
}

VALID_MODELS = {"deepseek-flash", "kimi", "deepseek-pro", "codex"}
VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}

REQUIRED_WORKSTREAM_FIELDS = {
    "schema_version",
    "id",
    "title",
    "status",
    "risk_level",
    "primary_model",
    "branch",
    "worktree",
    "base_branch",
    "base_commit",
    "acceptance_criteria",
}
