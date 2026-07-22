"""Model routing and rate-policy logic."""
from __future__ import annotations

from typing import Any

from .registry import load_model_roles, load_rate_policy


MODEL_ORDER = ["deepseek-flash", "kimi", "deepseek-pro", "codex"]


def recommend_model(task: dict[str, Any]) -> dict[str, Any]:
    """Recommend a model for a task based on risk, complexity, and rate policy."""
    risk = task.get("risk_level", "medium")
    complexity = task.get("complexity", "medium")
    touches_runtime = task.get("touches_runtime", False)
    touches_broker = task.get("touches_broker", False)
    touches_canonical = task.get("touches_canonical", False)
    cross_system = task.get("cross_system", False)
    task_type = task.get("task_type", "implementation")

    roles = load_model_roles()
    rate_policy = load_rate_policy()
    models = roles.get("models", {})

    # Determine the appropriate rate policy.
    if risk == "critical" or cross_system or complexity == "critical":
        policy_key = "critical"
    elif risk == "high" or touches_broker or touches_runtime or touches_canonical:
        policy_key = "high_risk"
    else:
        policy_key = "default"

    policy = rate_policy.get("policies", {}).get(policy_key, {})
    max_tier = policy.get("max_model_tier", "kimi")

    # Start with the cheapest model that fits the task constraints.
    if risk == "critical" or cross_system or complexity == "critical":
        recommended = "codex"
        reason = "critical_or_cross_system_task_recommends_codex"
    elif touches_broker or touches_runtime or touches_canonical or risk == "high":
        recommended = "deepseek-pro"
        reason = "broker_runtime_or_canonical_ownership_requires_deepseek_pro"
    elif risk == "low" and task_type in {"review", "audit", "diff_review", "test_validation"}:
        recommended = "deepseek-flash"
        reason = "small_review_or_audit_routes_to_deepseek_flash"
    else:
        recommended = "kimi"
        reason = "contained_implementation_routes_to_kimi"

    # Escalation: if recommended model is unavailable, fall back.
    fallback = None
    if recommended == "codex" and not task.get("codex_available", True):
        fallback = "deepseek-pro"
        reason = "codex_unavailable_falls_back_to_deepseek_pro"

    final = fallback or recommended

    # Enforce max_model_tier cap.
    if MODEL_ORDER.index(final) > MODEL_ORDER.index(max_tier):
        final = max_tier
        reason = f"rate_policy_max_tier_caps_model_at_{max_tier}"

    return {
        "recommended_model": final,
        "recommended_model_name": models.get(final, {}).get("name", final),
        "primary_reason": reason,
        "escalation_allowed": policy.get("escalation_allowed", True),
        "independent_review_required": policy.get("independent_review_required", False),
        "full_suite_required": policy.get("full_suite_required", False),
        "fallback_from": fallback,
    }


def compare_rate_cost(a: str, b: str) -> int:
    """Return negative if a is cheaper than b."""
    rate_policy = load_rate_policy()
    rates = rate_policy.get("model_rates_relative", {})
    return rates.get(a, 0) - rates.get(b, 0)
