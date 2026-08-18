"""Compatibility identity for Astra Sentinel backed by the canonical scanner.

This module has no scheduler, state registry, repair authority, or network
access.  It prevents legacy Sentinel scripts from becoming competing monitors
while retaining their public diagnostic identity in one read-only response.
"""
from __future__ import annotations

from typing import Any


SENTINEL_CANONICAL_OWNER = "PaperAutopilotWorker"
SENTINEL_SCAN_ENGINE = "astra_continuous_system_integrity_scanner_v1"


def sentinel_legacy_inventory_v1() -> list[dict[str, Any]]:
    """Declared audit inventory of pre-existing Sentinel components."""
    return [
        {"module": "engine.__init__", "component": "smart_backup_retention import hook", "purpose": "legacy backup cleanup", "schedule": "import-time (disabled)", "state_files": [], "repair_authority": "PROHIBITED", "status": "DEPRECATED_DISABLED", "reason": "import-time deletion is not worker-owned or reversible"},
        {"module": "core.sentinel.sentinel_v4", "component": "SentinelV4", "purpose": "manual structural policy scan", "schedule": "manual", "state_files": ["state/SENTINEL_POLICY.json", "state/SENTINEL_DEFENSE_LOG.jsonl"], "repair_authority": "NONE", "status": "COMPATIBILITY_DIAGNOSTIC_ONLY"},
        {"module": "core.sentinel.sentinel_v4_2", "component": "SentinelV42", "purpose": "legacy auto-heal", "schedule": "manual", "state_files": ["state/SENTINEL_V42_*"], "repair_authority": "PROHIBITED", "status": "DEPRECATED_PROHIBITED_AUTOREPAIR", "reason": "can quarantine or delete source outside guarded correction policy"},
        {"module": "core.sentinel.sentinel_integration_v2", "component": "SentinelIntegrationV2", "purpose": "legacy recovery daemon", "schedule": "independent 900-second loop (not started)", "state_files": ["state/SENTINEL_*"], "repair_authority": "PROHIBITED", "status": "DEPRECATED_ADAPTED", "reason": "would create a competing scan schedule and issue lifecycle"},
        {"module": "core.sentinel.sentinel_hook", "component": "sentinel_hook", "purpose": "manual file-change structural scan", "schedule": "manual", "state_files": ["state/SENTINEL_HOOK_LOG.jsonl"], "repair_authority": "NONE", "status": "COMPATIBILITY_DIAGNOSTIC_ONLY"},
        {"module": "guardian.guardian_sentinel", "component": "GuardianSentinel", "purpose": "manual startup/hash diagnostic", "schedule": "manual", "state_files": ["sentinel_report.json"], "repair_authority": "NONE", "status": "COMPATIBILITY_DIAGNOSTIC_ONLY"},
        {"module": "scripts/astra_watchdog.py", "component": "AstraWatchdog", "purpose": "service liveness watchdog", "schedule": "service-owned", "state_files": [], "repair_authority": "service restart only", "status": "RETAINED_OPERATIONAL_WATCHDOG", "reason": "not a fact scanner, truth authority, or issue registry"},
        {"module": "sentinel_auto_repair.py", "component": "legacy source auto repair", "purpose": "scripted source modification", "schedule": "manual", "state_files": [], "repair_authority": "PROHIBITED", "status": "DEPRECATED_PROHIBITED_AUTOREPAIR"},
        {"module": "sentinel_local_scan.py", "component": "legacy local scan", "purpose": "recursive local report", "schedule": "manual", "state_files": ["sentinel_report.json"], "repair_authority": "NONE", "status": "DEPRECATED_ADAPTED"},
    ]


def sentinel_integrity_payload_v1(scanner_payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt the committed scanner snapshot without starting a scan or writing state."""
    scanner = dict(scanner_payload or {})
    inventory = sentinel_legacy_inventory_v1()
    corrections = list(scanner.get("safe_corrections_applied") or [])
    roots = list(scanner.get("active_root_causes") or [])
    return {
        "endpoint": "/api/astra_sentinel_integrity_v1",
        "status": scanner.get("status") or "AWAITING_WORKER_SCAN",
        "sentinel_owner": "canonical_worker",
        "sentinel_canonical_owner": SENTINEL_CANONICAL_OWNER,
        "scan_engine": SENTINEL_SCAN_ENGINE,
        "sentinel_scan_engine": SENTINEL_SCAN_ENGINE,
        "light_scan": dict(scanner.get("light_scan") or {}),
        "deep_scan": dict(scanner.get("deep_scan") or {}),
        "targeted_scan": dict(scanner.get("targeted_scan") or {}),
        "resource_protection": dict(scanner.get("resource_protection") or {}),
        "legacy_sentinel_components": inventory,
        "legacy_components_adapted": [row["component"] for row in inventory if row["status"] in {"DEPRECATED_ADAPTED", "COMPATIBILITY_DIAGNOSTIC_ONLY"}],
        "legacy_components_deprecated": [row["component"] for row in inventory if row["status"].startswith("DEPRECATED")],
        "duplicate_scan_paths_removed": ["engine import-time cleanup", "legacy SentinelIntegrationV2 independent schedule"],
        "duplicate_issue_registries_removed": ["legacy Sentinel logs are diagnostic-only; scanner root-cause registry is canonical"],
        "active_root_causes": roots,
        "downstream_symptoms": list(scanner.get("downstream_symptoms") or []),
        "safe_level_1_corrections": [row for row in corrections if row.get("correction_level") == "LEVEL_1"],
        "guarded_level_2_corrections": list(scanner.get("guarded_level_2_corrections") or []),
        "human_level_3_repairs": list(scanner.get("human_repairs_required") or []),
        "legitimate_waiting_states": list(scanner.get("legitimate_waiting_states") or []),
        "causal_handoff_integrity_v1": dict(scanner.get("causal_handoff_integrity_v1") or {}),
        "platform_integrity_monitors_v2": dict(scanner.get("platform_integrity_monitors_v2") or {}),
        "crypto_market_data": dict(scanner.get("crypto_market_data") or {}),
        "governance_summary": dict(scanner.get("governance_summary") or {}),
        "cortex_summary": dict(scanner.get("cortex_summary") or {}),
        "shared_identifiers": {"finding_id": "finding-*", "root_cause_id": "root-*", "governance_issue_id": "root-*", "correction_id": "correction-*", "verification_id": "verification-*"},
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "state_mutations_from_get": 0,
        "get_route_read_only": True,
        "paper_only_preserved": True,
        "behavior_safe_to_apply": False,
    }
