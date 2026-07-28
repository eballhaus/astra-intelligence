"""Read-only canonical-fact arbitration and worker-owned contradiction history."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any
from engine.astra_canonical_ownership_contract_v1 import is_broker_linked_active_position


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _id(fact_id: str, kind: str, source: str) -> str:
    return "truth-" + hashlib.sha1(f"{fact_id}|{kind}|{source}".encode()).hexdigest()[:16]


def read_canonical_open_crypto_positions(db_path: str, limit: int = 200) -> list[dict[str, Any]]:
    """Read only current crypto rows from the canonical local position table."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM paper_positions WHERE status='OPEN' AND asset_type='crypto' LIMIT ?", (max(1, min(500, int(limit))),)).fetchall()
        finally:
            conn.close()
        return [row for row in (dict(item) for item in rows) if is_broker_linked_active_position(row, allow_dust=True)]
    except Exception:
        return []


def arbitrate_truth_claims_v1(claims: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in claims:
        if isinstance(raw, dict) and raw.get("fact_id"):
            grouped.setdefault(str(raw["fact_id"]), []).append(dict(raw))
    facts, contradictions = {}, []
    for fact_id, rows in grouped.items():
        canonical_rows = [row for row in rows if bool(row.get("canonical"))]
        if len(canonical_rows) != 1:
            contradictions.append({"contradiction_id": _id(fact_id, "CANONICAL_OWNER_AMBIGUOUS", "registry"), "fact_id": fact_id,
                "contradiction_type": "CANONICAL_OWNER_AMBIGUOUS", "severity": "HIGH", "canonical_claim": None,
                "conflicting_claims": rows, "root_cause_hint": "missing or duplicate canonical claim", "owning_component": "truth registry",
                "recommended_repair": "declare exactly one canonical owner", "automatic_repair_allowed": False,
                "human_review_required": True, "fail_closed_state": True, "verification_required": True})
            continue
        canonical = canonical_rows[0]
        facts[fact_id] = canonical
        for row in rows:
            if row is canonical:
                continue
            same_value = row.get("value") == canonical.get("value")
            same_scope = str(row.get("claimed_scope") or row.get("scope") or "") == str(canonical.get("scope") or "")
            if same_value and same_scope:
                continue
            if str(row.get("source_type") or "").lower() in {"adapter", "diagnostic", "reconstructed"} and not same_value:
                kind = "NONCANONICAL_SOURCE_OVERRIDE"
            elif not same_scope:
                kind = "SCOPE_MISMATCH"
            else:
                kind = "VALUE_CONTRADICTION"
            source = str(row.get("source_owner") or row.get("source_reader") or "unknown")
            contradictions.append({"contradiction_id": _id(fact_id, kind, source), "fact_id": fact_id, "contradiction_type": kind,
                "severity": "HIGH", "canonical_claim": canonical, "conflicting_claims": [row],
                "root_cause_hint": "noncanonical reconstructed or diagnostic rows treated as current active state" if kind == "NONCANONICAL_SOURCE_OVERRIDE" else "claims use incompatible semantic scopes",
                "owning_component": "crypto reconciliation / completion endpoint", "recommended_repair": "consume the registered canonical reader and retain the other claim as diagnostic-only",
                "automatic_repair_allowed": False, "human_review_required": True, "fail_closed_state": True, "verification_required": True})
    return {"critical_facts": facts, "contradictions": contradictions,
            "status": "WARNING" if contradictions else "PASS", "canonical_value_priority": "canonical claim only; never vote, merge, or average"}


class TruthContradictionRegistryV1:
    """Worker-only bounded contradiction history. API readers never call observe."""
    def __init__(self, state_dir: str = "state") -> None:
        self.path = os.path.join(state_dir, "astra_governance_contradictions_v1.json")

    def load(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return dict(value) if isinstance(value, dict) else {"issues": []}
        except Exception:
            return {"issues": []}

    def observe(self, contradictions: list[dict[str, Any]], verification_window: int = 3) -> dict[str, Any]:
        current = self.load()
        by_id = {str(row.get("contradiction_id")): dict(row) for row in current.get("issues") or [] if isinstance(row, dict)}
        now, active_ids = _now(), {str(row.get("contradiction_id")) for row in contradictions}
        for raw in contradictions:
            item = dict(raw); key = str(item["contradiction_id"]); previous = by_id.get(key)
            item.update({"first_detected_at": previous.get("first_detected_at") if previous else now, "last_detected_at": now,
                         "occurrence_count": int(previous.get("occurrence_count") or 0) + 1 if previous else 1,
                         "state": "RECURRENT" if previous and previous.get("state") == "RESOLVED" else "OPEN",
                         "consistent_observations": 0})
            by_id[key] = item
        for key, item in by_id.items():
            if key in active_ids or item.get("state") in {"RESOLVED", "RECURRENT"}:
                continue
            item["consistent_observations"] = int(item.get("consistent_observations") or 0) + 1
            item["last_detected_at"] = now
            item["state"] = "RESOLVED" if item["consistent_observations"] >= verification_window else "VERIFYING"
        payload = {"generated_at": now, "verification_window": verification_window, "issues": list(by_id.values())[-200:]}
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            temp = self.path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            os.replace(temp, self.path)
        except Exception:
            pass
        return payload


def cortex_truth_summary_v1(arbitration: dict[str, Any]) -> dict[str, Any]:
    facts = dict(arbitration.get("critical_facts") or {})
    rejected = list(arbitration.get("contradictions") or [])
    return {"cortex_truth_summary": "Canonical facts retained; noncanonical claims are diagnostic-only." if not rejected else "A conflicting noncanonical claim was rejected in favor of the registered canonical fact.",
            "canonical_facts_used": sorted(facts), "rejected_claims": rejected, "unresolved_contradictions": len(rejected),
            "confidence": 1.0 if not rejected else 0.8, "human_review_required": bool(rejected), "truth_promotion_allowed": False}
