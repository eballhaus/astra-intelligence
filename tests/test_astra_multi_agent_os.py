"""Tests for the Astra Multi-Agent Operating System."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import ops.multi_agent.ledger as ledger
import ops.multi_agent.prompt as prompt
import ops.multi_agent.queue as queue
import ops.multi_agent.routing as routing
import ops.multi_agent.validator as validator
from ops.multi_agent.common import load_yaml, save_yaml
from ops.multi_agent.registry import (
    get_workstream,
    load_registry,
    register_workstream,
    save_registry,
)


LIVE_CHECKOUT = "/Users/eric/Desktop/astra-intelligence-clean"


@pytest.fixture
def temp_ops(monkeypatch, tmp_path):
    """Provide an isolated git repository with an ops/multi_agent directory."""
    repo = tmp_path / "repo"
    ops = repo / "ops" / "multi_agent"
    ops.mkdir(parents=True)
    real_ops = Path(__file__).resolve().parents[1] / "ops" / "multi_agent"
    for path in real_ops.glob("*.yaml"):
        shutil.copy(path, ops)
    # Initialise the repo so worktree validation can check the repository root.
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    monkeypatch.setattr("ops.multi_agent.common.repo_root", lambda: repo)
    monkeypatch.setattr("ops.multi_agent.registry.ops_dir", lambda: ops)
    monkeypatch.setattr("ops.multi_agent.validator.repo_root", lambda: repo)
    return repo


def _base_workstream(**overrides):
    ws = {
        "schema_version": "1.0.0",
        "id": "test-ws",
        "title": "Test workstream",
        "status": "active",
        "risk_level": "medium",
        "primary_model": "kimi",
        "branch": "feature/test",
        "worktree": "/tmp/nonexistent-worktree",
        "base_branch": "main",
        "base_commit": "0" * 40,
        "acceptance_criteria": [],
        "owned_files": [],
        "owned_patterns": [],
        "owned_contracts": [],
        "read_only_dependencies": [],
        "forbidden_files": [],
        "depends_on": [],
        "blocks": [],
        "rate_policy": {
            "estimated_context": "medium",
            "estimated_output": "medium",
            "full_suite_required": False,
            "escalation_allowed": True,
            "maximum_default_model": "kimi",
        },
        "integration": {
            "order": 100,
            "requires_independent_review": False,
            "requires_full_suite_at_integration": False,
            "runtime_restart_expected": False,
        },
    }
    ws.update(overrides)
    return ws


def test_schema_required_fields(temp_ops):
    ws = _base_workstream()
    del ws["title"]
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("missing_required_field:title" in e for e in result["errors"])


def test_schema_invalid_status_model_risk(temp_ops):
    ws = _base_workstream(status="unknown", primary_model="gpt-5", risk_level="extreme")
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("invalid_status" in e for e in result["errors"])
    assert any("invalid_primary_model" in e for e in result["errors"])
    assert any("invalid_risk_level" in e for e in result["errors"])


def test_schema_criteria_validation(temp_ops):
    ws = _base_workstream(acceptance_criteria=[
        {"id": "c1", "status": "PASS", "description": "ok"},
        {"id": "c1", "status": "PASS", "description": "dup"},
        {"id": "bad", "status": "WEIRD", "description": "bad"},
    ])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("duplicate_criterion_id:c1" in e for e in result["errors"])
    assert any("invalid_criterion_status" in e for e in result["errors"])


def test_forbidden_paths_live_checkout(temp_ops):
    ws = _base_workstream(worktree=LIVE_CHECKOUT, owned_files=["src/foo.py"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_worktree:live_checkout" in e for e in result["errors"])


def test_forbidden_paths_patterns(temp_ops):
    ws = _base_workstream(owned_patterns=["state/positions.json"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_pattern" in e for e in result["errors"])


def test_ownership_file_conflict(temp_ops):
    a = _base_workstream(id="ws-a", owned_files=["src/shared.py"])
    b = _base_workstream(id="ws-b", owned_files=["src/shared.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("file_conflict:src/shared.py:owner=ws-a" in e for e in result["errors"])


def test_ownership_pattern_conflict(temp_ops):
    a = _base_workstream(id="ws-a", owned_patterns=["src/**/*.py"])
    b = _base_workstream(id="ws-b", owned_files=["src/module.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("file_pattern_conflict" in e for e in result["errors"])


def test_ownership_contract_conflict(temp_ops):
    a = _base_workstream(id="ws-a", owned_contracts=["broker_submission"])
    b = _base_workstream(id="ws-b", owned_contracts=["broker_submission"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("contract_conflict:broker_submission:owner=ws-a" in e for e in result["errors"])


def test_dependency_missing(temp_ops):
    ws = _base_workstream(id="ws-dep", depends_on=["missing-ws"])
    register_workstream(ws)
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("missing_dependency:missing-ws" in e for e in result["errors"])


def test_dependency_incomplete(temp_ops):
    dep = _base_workstream(id="ws-dep-base", status="active")
    ws = _base_workstream(id="ws-dep-child", depends_on=["ws-dep-base"])
    register_workstream(dep)
    register_workstream(ws)
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("incomplete_dependency:ws-dep-base" in e for e in result["errors"])


def test_dependency_circular(temp_ops):
    a = _base_workstream(id="ws-a", depends_on=["ws-b"])
    b = _base_workstream(id="ws-b", depends_on=["ws-a"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(a, include_worktree=False)
    assert not result["valid"]
    assert any("circular_dependency" in e for e in result["errors"])


def _make_worktree(repo, branch="feature/test", push_origin=True):
    """Create a bare origin, push main, and add a worktree from repo."""
    origin = repo.parent / "origin.git"
    if not origin.exists():
        subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    remotes = subprocess.run(["git", "remote"], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()
    if "origin" not in remotes.splitlines():
        subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo, check=True, capture_output=True)

    wt = repo.parent / f"wt-{branch.replace('/', '-')}"
    subprocess.run(["git", "worktree", "add", "-b", branch, str(wt)], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, text=True, capture_output=True, check=True).stdout.strip()
    return wt, head


def test_worktree_validation(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(worktree=str(wt), branch="feature/test", base_commit=head)
    result = validator.validate_workstream(ws, include_worktree=True)
    assert result["valid"], result["errors"]
    assert result["worktree"]["worktree_exists"]
    assert result["worktree"]["branch_matches"]
    assert result["worktree"]["head_matches_base"]
    assert result["worktree"]["clean"]
    assert not result["worktree"]["stale_base"]

    (wt / "dirty.txt").write_text("x\n")
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("worktree_dirty" in e for e in result["errors"])


def test_worktree_duplicate_assignment(temp_ops):
    wt, head = _make_worktree(temp_ops)
    a = _base_workstream(id="ws-a", worktree=str(wt), branch="feature/test", base_commit=head)
    register_workstream(a)
    result_a = validator.validate_workstream(a, include_worktree=True)
    assert result_a["valid"], result_a["errors"]

    b = _base_workstream(id="ws-b", worktree=str(wt), branch="feature/test", base_commit=head)
    register_workstream(b)
    result_b = validator.validate_workstream(b, include_worktree=True)
    assert not result_b["valid"]
    assert any("duplicate_worktree_assignment" in e for e in result_b["errors"])
    assert any("duplicate_branch_assignment" in e for e in result_b["errors"])


def test_routing_low_risk_review(temp_ops):
    task = {
        "risk_level": "low",
        "complexity": "low",
        "task_type": "review",
        "touches_runtime": False,
        "touches_broker": False,
        "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-flash"


def test_routing_high_risk(temp_ops):
    task = {
        "risk_level": "high",
        "complexity": "medium",
        "task_type": "implementation",
        "touches_runtime": False,
        "touches_broker": False,
        "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"


def test_routing_cross_system(temp_ops):
    task = {
        "risk_level": "medium",
        "complexity": "medium",
        "task_type": "implementation",
        "touches_runtime": False,
        "touches_broker": False,
        "touches_canonical": False,
        "cross_system": True,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "codex"


def test_routing_rate_cap(temp_ops):
    task = {
        "risk_level": "high",
        "complexity": "medium",
        "task_type": "implementation",
        "touches_runtime": False,
        "touches_broker": False,
        "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"


def test_ledger_pass_requires_evidence(temp_ops):
    ws = _base_workstream(acceptance_criteria=[
        {"id": "c1", "status": "PASS", "description": "done"},
    ])
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("PASS_without_evidence:c1" in e for e in result["errors"])


def test_ledger_blocked_requires_reason(temp_ops):
    ws = _base_workstream(acceptance_criteria=[
        {"id": "c1", "status": "BLOCKED", "description": "blocked"},
    ])
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("BLOCKED_without_external_reason:c1" in e for e in result["errors"])


def test_ledger_fail_prevents_completion(temp_ops):
    ws = _base_workstream(
        status="implementation_complete",
        acceptance_criteria=[
            {"id": "c1", "status": "FAIL", "description": "bad"},
        ],
    )
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("implementation_complete_with_incomplete_criteria" in e for e in result["errors"])


def test_ledger_controllable_work_remaining(temp_ops):
    ws = _base_workstream(acceptance_criteria=[
        {"id": "c1", "status": "PASS", "description": "done", "evidence": [{"file": "x"}], "controllable_work_remaining": ["fix"]},
    ])
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("controllable_work_remaining:c1" in e for e in result["errors"])


def test_ledger_can_finish(temp_ops):
    ws = _base_workstream(
        status="active",
        acceptance_criteria=[
            {"id": "c1", "status": "PASS", "description": "done", "evidence": [{"file": "x"}]},
            {"id": "c2", "status": "BLOCKED", "description": "ext", "external_blocker": "dependency"},
        ],
    )
    result = ledger.can_finish(ws)
    assert result["can_finish"]


def test_queue_add_ready(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(
        id="ready-ws",
        status="review_passed",
        review_status="passed",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
        acceptance_criteria=[
            {"id": "c1", "status": "PASS", "description": "done", "evidence": [{"file": "x"}]},
        ],
    )
    register_workstream(ws)
    result = queue.add_to_queue("ready-ws")
    assert result["ok"]
    assert result["queue_position"] == 1


def test_queue_rejects_not_ready(temp_ops):
    ws = _base_workstream(id="not-ready-ws", status="active")
    register_workstream(ws)
    result = queue.add_to_queue("not-ready-ws")
    assert not result["ok"]
    assert any("status_not_review_passed" in e for e in result["errors"])


def test_queue_ordering(temp_ops):
    wt200, head200 = _make_worktree(temp_ops, branch="feature/order-200")
    wt50, head50 = _make_worktree(temp_ops, branch="feature/order-50")
    a = _base_workstream(
        id="order-200", status="review_passed", review_status="passed",
        worktree=str(wt200), branch="feature/order-200", base_commit=head200,
        integration={"order": 200},
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    b = _base_workstream(
        id="order-50", status="review_passed", review_status="passed",
        worktree=str(wt50), branch="feature/order-50", base_commit=head50,
        integration={"order": 50},
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    register_workstream(a)
    register_workstream(b)
    queue.add_to_queue("order-200")
    queue.add_to_queue("order-50")
    status = queue.get_queue_status()
    ids = [i["id"] for i in status["queue"]]
    assert ids == ["order-50", "order-200"]


def test_prompt_generation(temp_ops):
    ws = _base_workstream(
        id="prompt-ws",
        title="Prompt test",
        owned_files=["src/a.py"],
        owned_contracts=["broker_submission"],
        forbidden_files=["src/live.py"],
    )
    register_workstream(ws)
    result = prompt.generate_prompt("prompt-ws")
    assert result["ok"]
    assert "Prompt test" in result["prompt"]
    assert "src/a.py" in result["prompt"]
    assert "broker_submission" in result["prompt"]
    assert "src/live.py" in result["prompt"]
    assert "Do not" in result["prompt"]


def test_prompt_deepseek_instruction(temp_ops):
    ws = _base_workstream(id="deep-prompt", primary_model="deepseek-pro")
    register_workstream(ws)
    result = prompt.generate_prompt("deep-prompt")
    assert result["ok"]
    assert "DeepSeek Pro" in result["prompt"]


@pytest.mark.parametrize("script", [
    "astra_agent_register.py",
    "astra_agent_validate.py",
    "astra_agent_status.py",
    "astra_agent_prompt.py",
    "astra_agent_finish.py",
    "astra_agent_review.py",
    "astra_integration_queue.py",
    "astra_agent_lock_check.py",
])
def test_script_help_runs(script):
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(repo / "scripts" / script), "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_scripts_executable():
    repo = Path(__file__).resolve().parents[1]
    for script in repo.glob("scripts/astra_*.py"):
        assert os.access(script, os.X_OK), f"{script.name} is not executable"


def test_runtime_isolation_no_live_checkout():
    assert validator.LIVE_CHECKOUT == LIVE_CHECKOUT


def test_runtime_isolation_no_restart_in_scripts():
    repo = Path(__file__).resolve().parents[1]
    for script in repo.glob("scripts/astra_*.py"):
        text = script.read_text()
        assert "restart" not in text.lower(), f"{script.name} contains restart"
        assert "broker" not in text.lower() or "submission" not in text.lower(), f"{script.name} may submit broker orders"


def test_no_forbidden_live_files_in_owned_files(temp_ops):
    ws = _base_workstream(owned_files=["config/secrets.env", "logs/audit.log"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_path" in e for e in result["errors"])


def test_status_transition_invalid(temp_ops):
    ws = _base_workstream(id="tx-ws", status="proposed")
    register_workstream(ws)
    errors = validator.validate_status_transition("tx-ws", "integrated")
    assert errors
    assert any("invalid_status_transition" in e for e in errors)


# ---------------------------------------------------------------------------
# Additional high-value safety tests
# ---------------------------------------------------------------------------


def test_forbidden_path_normalized_dot_env(temp_ops):
    ws = _base_workstream(owned_files=["./.env"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_path" in e for e in result["errors"])


def test_forbidden_path_parent_traversal(temp_ops):
    ws = _base_workstream(owned_files=["engine/../.env"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_path" in e for e in result["errors"])


def test_forbidden_path_double_slash(temp_ops):
    ws = _base_workstream(owned_files=["state//test.json"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_path" in e for e in result["errors"])


def test_forbidden_path_absolute_live_checkout(temp_ops):
    ws = _base_workstream(worktree=LIVE_CHECKOUT)
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_worktree:live_checkout" in e for e in result["errors"])


def test_forbidden_path_case_variant(temp_ops):
    ws = _base_workstream(owned_files=["State/test.json"])
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_path" in e for e in result["errors"])


def test_forbidden_path_symlinked_live_checkout(temp_ops, tmp_path):
    link = tmp_path / "live_link"
    link.symlink_to(LIVE_CHECKOUT)
    ws = _base_workstream(worktree=str(link))
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("forbidden_worktree:live_checkout" in e for e in result["errors"])


def test_ownership_parent_directory_vs_file(temp_ops):
    a = _base_workstream(id="ws-a", owned_patterns=["src/"])
    b = _base_workstream(id="ws-b", owned_files=["src/module.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("file_pattern_conflict" in e for e in result["errors"])


def test_ownership_glob_glob_overlap(temp_ops):
    a = _base_workstream(id="ws-a", owned_patterns=["src/**/*.py"])
    b = _base_workstream(id="ws-b", owned_patterns=["src/*_test.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("pattern_pattern_conflict" in e for e in result["errors"])


def test_ownership_normalized_variant(temp_ops):
    a = _base_workstream(id="ws-a", owned_files=["src/foo.py"])
    b = _base_workstream(id="ws-b", owned_files=["./src/foo.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("file_conflict:src/foo.py" in e for e in result["errors"])


def test_ownership_case_variant_no_conflict(temp_ops):
    a = _base_workstream(id="ws-a", owned_files=["src/Foo.py"])
    b = _base_workstream(id="ws-b", owned_files=["src/foo.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert result["valid"], result["errors"]


def test_ownership_uncertain_overlap_fails_closed(temp_ops):
    a = _base_workstream(id="ws-a", owned_patterns=["src/**/*.py"])
    b = _base_workstream(id="ws-b", owned_patterns=["src/**/*.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("pattern_pattern_conflict" in e for e in result["errors"])


def test_read_only_dependency_not_owned(temp_ops):
    ws = _base_workstream(
        id="ws-ro",
        owned_files=["src/shared.py"],
        read_only_dependencies=["src/shared.py"],
    )
    register_workstream(ws)
    result = validator.validate_workstream(ws, include_worktree=False)
    assert not result["valid"]
    assert any("read_only_dependency_claimed_as_owned" in e for e in result["errors"])


def test_contract_failed_status_releases_ownership(temp_ops):
    a = _base_workstream(id="ws-a", status="failed", owned_files=["src/shared.py"])
    b = _base_workstream(id="ws-b", owned_files=["src/shared.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert result["valid"], result["errors"]


def test_contract_cancelled_status_releases_ownership(temp_ops):
    a = _base_workstream(id="ws-a", status="cancelled", owned_files=["src/shared.py"])
    b = _base_workstream(id="ws-b", owned_files=["src/shared.py"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert result["valid"], result["errors"]


def test_contract_duplicate_active_rejected(temp_ops):
    a = _base_workstream(id="ws-a", owned_contracts=["broker_submission"])
    b = _base_workstream(id="ws-b", owned_contracts=["broker_submission"])
    register_workstream(a)
    register_workstream(b)
    result = validator.validate_workstream(b, include_worktree=False)
    assert not result["valid"]
    assert any("contract_conflict:broker_submission:owner=ws-a" in e for e in result["errors"])


def test_worktree_wrong_branch(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(worktree=str(wt), branch="feature/wrong", base_commit=head)
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("branch_mismatch" in e for e in result["errors"])


def test_worktree_unknown_base(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(worktree=str(wt), branch="feature/test", base_commit="0" * 40)
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("unknown_base_commit" in e for e in result["errors"])


def test_worktree_stale_base(temp_ops):
    wt, head = _make_worktree(temp_ops)
    # Advance origin/main with a new commit.
    (temp_ops / "new.txt").write_text("advance\n")
    subprocess.run(["git", "add", "new.txt"], cwd=temp_ops, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "advance"], cwd=temp_ops, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=temp_ops, check=True, capture_output=True)
    ws = _base_workstream(worktree=str(wt), branch="feature/test", base_commit=head)
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("stale_base" in e for e in result["errors"])


def test_worktree_wrong_repository(temp_ops, tmp_path):
    wrong = tmp_path / "wrong_repo"
    wrong.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=wrong, check=True, capture_output=True)
    (wrong / "file.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=wrong, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=wrong, check=True, capture_output=True)
    ws = _base_workstream(worktree=str(wrong), branch="main", base_commit="0" * 40)
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("wrong_repository" in e for e in result["errors"])


def test_worktree_symlinked_live_checkout(temp_ops, tmp_path):
    link = tmp_path / "live_link"
    link.symlink_to(LIVE_CHECKOUT)
    ws = _base_workstream(worktree=str(link))
    result = validator.validate_workstream(ws, include_worktree=True)
    assert not result["valid"]
    assert any("forbidden_worktree:live_checkout" in e for e in result["errors"])


def test_ledger_blocked_with_controllable_work(temp_ops):
    ws = _base_workstream(
        status="active",
        acceptance_criteria=[
            {"id": "c1", "status": "BLOCKED", "external_blocker": "api", "controllable_work_remaining": ["fix"]},
        ],
    )
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("controllable_work_remaining:c1" in e for e in result["errors"])


def test_ledger_not_evaluated_blocks_completion(temp_ops):
    ws = _base_workstream(
        status="implementation_complete",
        acceptance_criteria=[
            {"id": "c1", "status": "NOT_EVALUATED", "description": "pending"},
        ],
    )
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("implementation_complete_with_incomplete_criteria" in e for e in result["errors"])


def test_ledger_narrative_cannot_override(temp_ops):
    ws = _base_workstream(
        id="narrative",
        status="review_passed",
        review_status="passed",
        acceptance_criteria=[
            {"id": "c1", "status": "FAIL", "description": "bad"},
        ],
    )
    register_workstream(ws)
    result = ledger.can_finish(ws)
    assert not result["can_finish"]
    assert any("FAIL" in e for e in result["errors"])


def test_ledger_evidence_type_enforced(temp_ops):
    ws = _base_workstream(
        acceptance_criteria=[
            {"id": "c1", "status": "PASS", "evidence": ["bad_string"]},
        ],
    )
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("evidence_entry_0_not_dict" in e for e in result["errors"])


def test_ledger_evidence_source_enforced(temp_ops):
    ws = _base_workstream(
        acceptance_criteria=[
            {"id": "c1", "status": "PASS", "evidence": [{"file": "x", "source": "bogus"}]},
        ],
    )
    result = ledger.validate_ledger(ws)
    assert not result["valid"]
    assert any("evidence_entry_0_invalid_source" in e for e in result["errors"])


def test_routing_contained_implementation_kimi(temp_ops):
    task = {
        "risk_level": "low", "complexity": "low", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": False, "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "kimi"
    assert result["primary_reason"]


def test_routing_paper_autopilot_broker_pro(temp_ops):
    task = {
        "risk_level": "low", "complexity": "medium", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": False, "touches_canonical": False,
        "touches_paper_autopilot": True, "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"
    assert "paper_autopilot" in result["primary_reason"]


def test_routing_capital_pro(temp_ops):
    task = {
        "risk_level": "low", "complexity": "medium", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": False, "touches_canonical": False,
        "touches_capital": True, "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"


def test_routing_codex_fallback(temp_ops):
    task = {
        "risk_level": "medium", "complexity": "medium", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": False, "touches_canonical": False,
        "cross_system": True, "codex_available": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"
    assert result["fallback_from"] == "codex"


def test_routing_safety_overrides_rate_cap(temp_ops):
    task = {
        "risk_level": "low", "complexity": "medium", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": True, "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"


def test_routing_escalation_reason(temp_ops):
    task = {
        "risk_level": "high", "complexity": "medium", "task_type": "implementation",
        "touches_runtime": False, "touches_broker": False, "touches_canonical": False,
        "cross_system": False,
    }
    result = routing.recommend_model(task)
    assert result["recommended_model"] == "deepseek-pro"
    assert result["primary_reason"]


def test_prompt_flash_exact(temp_ops):
    ws = _base_workstream(id="flash-prompt", primary_model="deepseek-flash")
    register_workstream(ws)
    result = prompt.generate_prompt("flash-prompt")
    assert result["ok"]
    assert "Use DeepSeek Flash." in result["prompt"]


def test_prompt_pro_exact(temp_ops):
    ws = _base_workstream(id="pro-prompt", primary_model="deepseek-pro")
    register_workstream(ws)
    result = prompt.generate_prompt("pro-prompt")
    assert result["ok"]
    assert "Use DeepSeek Pro." in result["prompt"]


def test_prompt_kimi_named(temp_ops):
    ws = _base_workstream(id="kimi-prompt", primary_model="kimi")
    register_workstream(ws)
    result = prompt.generate_prompt("kimi-prompt")
    assert result["ok"]
    assert "Use Kimi K2.7 Code" in result["prompt"]


def test_prompt_codex_named(temp_ops):
    ws = _base_workstream(id="codex-prompt", primary_model="codex")
    register_workstream(ws)
    result = prompt.generate_prompt("codex-prompt")
    assert result["ok"]
    assert "Use Codex" in result["prompt"]


def test_prompt_includes_branch_worktree_base(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(
        id="ctx-prompt",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
    )
    register_workstream(ws)
    result = prompt.generate_prompt("ctx-prompt")
    assert result["ok"]
    assert str(wt) in result["prompt"]
    assert "feature/test" in result["prompt"]
    assert head in result["prompt"]


def test_prompt_includes_forbidden_paths(temp_ops):
    ws = _base_workstream(
        id="forbidden-prompt",
        forbidden_files=["src/never_touch.py"],
    )
    register_workstream(ws)
    result = prompt.generate_prompt("forbidden-prompt")
    assert result["ok"]
    assert "src/never_touch.py" in result["prompt"]


def test_prompt_includes_acceptance_criteria(temp_ops):
    ws = _base_workstream(
        id="criteria-prompt",
        acceptance_criteria=[
            {"id": "C1", "status": "PASS", "description": "done", "evidence": [{"file": "x"}]},
        ],
    )
    register_workstream(ws)
    result = prompt.generate_prompt("criteria-prompt")
    assert result["ok"]
    assert "C1" in result["prompt"]
    assert "done" in result["prompt"]


def test_prompt_no_main_merge_authority(temp_ops):
    ws = _base_workstream(id="no-merge-prompt")
    register_workstream(ws)
    result = prompt.generate_prompt("no-merge-prompt")
    assert result["ok"]
    assert "merge or push to `main` without explicit authorization" in result["prompt"]


def test_prompt_no_restart_authority(temp_ops):
    ws = _base_workstream(id="no-restart-prompt")
    register_workstream(ws)
    result = prompt.generate_prompt("no-restart-prompt")
    assert result["ok"]
    assert "restart Astra" in result["prompt"]


def test_queue_high_risk_requires_review(temp_ops):
    wt, head = _make_worktree(temp_ops)
    ws = _base_workstream(
        id="hr-ws",
        status="review_passed",
        risk_level="high",
        review_status="pending",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    register_workstream(ws)
    result = queue.add_to_queue("hr-ws")
    assert not result["ok"]
    assert any("independent_review_required" in e for e in result["errors"])


def test_queue_failed_review_blocks(temp_ops):
    ws = _base_workstream(
        id="failed-review",
        status="review_failed",
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    register_workstream(ws)
    result = queue.add_to_queue("failed-review")
    assert not result["ok"]
    assert any("status_not_review_passed" in e for e in result["errors"])


def test_queue_stale_base_blocks(temp_ops):
    wt, head = _make_worktree(temp_ops)
    (temp_ops / "advance.txt").write_text("x\n")
    subprocess.run(["git", "add", "advance.txt"], cwd=temp_ops, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "advance"], cwd=temp_ops, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=temp_ops, check=True, capture_output=True)
    ws = _base_workstream(
        id="stale-ws",
        status="review_passed",
        review_status="passed",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    register_workstream(ws)
    result = queue.add_to_queue("stale-ws")
    assert not result["ok"]
    assert any("stale_base" in e for e in result["errors"])


def test_queue_ownership_conflict_blocks(temp_ops):
    wt, head = _make_worktree(temp_ops)
    a = _base_workstream(
        id="owner-a",
        status="review_passed",
        review_status="passed",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
        owned_files=["src/x.py"],
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    b = _base_workstream(
        id="owner-b",
        status="review_passed",
        review_status="passed",
        worktree=str(wt),
        branch="feature/test",
        base_commit=head,
        owned_files=["src/x.py"],
        acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
    )
    register_workstream(a)
    register_workstream(b)
    result = queue.add_to_queue("owner-b")
    assert not result["ok"]
    assert any("file_conflict" in e for e in result["errors"])


def test_queue_one_integrator_enforced(temp_ops):
    wt1, head1 = _make_worktree(temp_ops, branch="feature/one")
    wt2, head2 = _make_worktree(temp_ops, branch="feature/two")
    for idx, (wt, head, wid) in enumerate([(wt1, head1, "ws-one"), (wt2, head2, "ws-two")], start=1):
        ws = _base_workstream(
            id=wid,
            status="review_passed",
            review_status="passed",
            worktree=str(wt),
            branch=f"feature/{wid.split('-')[1]}",
            base_commit=head,
            integration={"order": idx},
            acceptance_criteria=[{"id": "c1", "status": "PASS", "evidence": [{}]}],
        )
        register_workstream(ws)
        queue.add_to_queue(wid)
    first = queue.set_current_integrating("ws-one")
    assert first["ok"]
    second = queue.set_current_integrating("ws-two")
    assert not second["ok"]
    assert "integrator_already_assigned" in second["error"]


def test_queue_no_automatic_merge_push_restart(temp_ops):
    repo = Path(__file__).resolve().parents[1]
    for path in [repo / "ops/multi_agent/queue.py", repo / "scripts/astra_integration_queue.py"]:
        text = path.read_text()
        assert "git push" not in text.lower(), f"{path.name} contains git push"
        assert "git merge" not in text.lower(), f"{path.name} contains git merge"
        assert "subprocess.run" not in text.lower(), f"{path.name} uses subprocess.run"
        assert "subprocess.Popen" not in text.lower(), f"{path.name} uses subprocess.Popen"
        assert "os.system" not in text.lower(), f"{path.name} uses os.system"
        assert "restart_astra" not in text.lower(), f"{path.name} contains restart_astra"
