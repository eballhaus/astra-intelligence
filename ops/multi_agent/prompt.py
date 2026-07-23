"""Prompt generation for assigned models."""
from __future__ import annotations

from typing import Any

from .registry import get_workstream


def generate_prompt(workstream_id: str, *, model: str | None = None) -> dict[str, Any]:
    ws = get_workstream(workstream_id)
    if ws is None:
        return {"ok": False, "error": "workstream_not_found"}

    target_model = model or ws.get("primary_model", "kimi")
    model_name = _model_display_name(target_model)
    instruction = _model_instruction(target_model)

    prompt = f"""# Astra Upgrade

{instruction}

## Task

- **ID:** {ws.get('id')}
- **Title:** {ws.get('title')}
- **Risk level:** {ws.get('risk_level')}
- **Worktree:** {ws.get('worktree')}
- **Branch:** {ws.get('branch')}
- **Base commit:** {ws.get('base_commit')}

## Ownership

**Owned files:**
{chr(10).join(f"- {f}" for f in ws.get('owned_files', [])) or "- (none)"}

**Owned patterns:**
{chr(10).join(f"- {p}" for p in ws.get('owned_patterns', [])) or "- (none)"}

**Owned canonical contracts:**
{chr(10).join(f"- {c}" for c in ws.get('owned_contracts', [])) or "- (none)"}

**Read-only dependencies:**
{chr(10).join(f"- {d}" for d in ws.get('read_only_dependencies', [])) or "- (none)"}

**Forbidden files:**
{chr(10).join(f"- {f}" for f in ws.get('forbidden_files', [])) or "- (none specified)"}

## Dependencies

**Depends on:** {', '.join(ws.get('depends_on', [])) or 'none'}
**Blocks:** {', '.join(ws.get('blocks', [])) or 'none'}

## Acceptance criteria

{chr(10).join(f"- **{c.get('id')}** [{c.get('status')}] {c.get('description')}" for c in ws.get('acceptance_criteria', [])) or "- (none)"}

## Rate constraints

- Maximum default model: {ws.get('rate_policy', {}).get('maximum_default_model', 'kimi')}
- Full suite required: {ws.get('rate_policy', {}).get('full_suite_required', False)}
- Escalation allowed: {ws.get('rate_policy', {}).get('escalation_allowed', True)}

## Integration restrictions

- Requires independent review: {ws.get('integration', {}).get('requires_independent_review', False)}
- Requires full suite at integration: {ws.get('integration', {}).get('requires_full_suite_at_integration', False)}
- Runtime restart expected: {ws.get('integration', {}).get('runtime_restart_expected', False)}

## Completion loop

1. Inspect existing architecture.
2. Design minimal integration.
3. Implement in the assigned worktree only.
4. Run focused tests.
5. Run safety tests and scans.
6. Validate acceptance ledger.
7. Produce final report.

Do not:
- modify the live Astra checkout;
- start, stop, or restart Astra;
- submit broker orders;
- merge or push to `main` without explicit authorization;
- modify files outside the owned files and read-only dependencies.
"""

    return {
        "ok": True,
        "workstream_id": workstream_id,
        "target_model": target_model,
        "target_model_name": model_name,
        "prompt": prompt,
    }


def _model_display_name(model: str) -> str:
    names = {
        "deepseek-flash": "DeepSeek Flash",
        "kimi": "Kimi K2.7 Code",
        "deepseek-pro": "DeepSeek Pro",
        "codex": "Codex",
    }
    return names.get(model, model)


def _model_instruction(model: str) -> str:
    if model == "deepseek-flash":
        return "Use DeepSeek Flash."
    if model == "deepseek-pro":
        return "Use DeepSeek Pro."
    if model == "codex":
        return "Use Codex for this hardest cross-system or final integration task."
    return "Use Kimi K2.7 Code for this implementation."
