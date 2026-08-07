"""Read-only metadata for the runtime-certified natural lifecycle contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "contracts" / "astra_canonical_natural_lifecycle_v1.json"
REQUIRED_STATUS = "FROZEN_PROTECTED_RUNTIME_CERTIFIED"


def canonical_natural_lifecycle_contract_v1() -> dict[str, Any]:
    """Return the source-controlled freeze certificate without runtime I/O."""
    try:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"status": "MANIFEST_UNAVAILABLE", "contract_name": "ASTRA_CANONICAL_NATURAL_LIFECYCLE_V1"}
    contract = dict(payload) if isinstance(payload, dict) else {}
    contract["manifest_path"] = str(MANIFEST_PATH.relative_to(ROOT))
    contract["freeze_enforced"] = contract.get("status") == REQUIRED_STATUS
    contract["provider_calls_used"] = 0
    contract["broker_actions_used"] = 0
    contract["behavior_safe_to_apply"] = False
    return contract
