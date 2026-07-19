"""Pure, bounded contracts for integrity scans; never an execution gate owner."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _iso_age_seconds(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(text).astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def validate_field_contract_v1(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Validate declared fields without converting or filling missing data."""
    required = list(contract.get("required_fields") or [])
    aliases = dict(contract.get("aliases") or {})
    types = dict(contract.get("field_types") or {})
    missing, invalid, resolved = [], [], {}
    for field in required:
        value = row.get(field)
        if value is None:
            for alias in aliases.get(field, []):
                if row.get(alias) is not None:
                    value = row.get(alias)
                    break
        resolved[field] = value
        if value is None or value == "":
            missing.append(field)
        elif field in types and not isinstance(value, types[field]):
            invalid.append(field)
    provenance = list(contract.get("provenance_required") or [])
    timestamps = list(contract.get("timestamp_required") or [])
    identity = list(contract.get("identity_required") or [])
    missing_provenance = [field for field in provenance if not row.get(field)]
    missing_timestamps = [field for field in timestamps if not row.get(field)]
    missing_identity = [field for field in identity if not row.get(field)]
    return {
        "contract_version": "1.0.0", "valid": not any((missing, invalid, missing_provenance, missing_timestamps, missing_identity)),
        "missing_fields": missing, "invalid_fields": invalid, "missing_provenance": missing_provenance,
        "missing_timestamps": missing_timestamps, "missing_identity": missing_identity,
        "resolved_fields": resolved,
    }


def validate_scope_contract_v1(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    checks = {key: str(row.get(key) or "").upper() == str(value).upper() for key, value in dict(contract).items() if value not in (None, "")}
    return {"valid": all(checks.values()), "checks": checks, "scope_mismatches": [key for key, passed in checks.items() if not passed]}


def validate_freshness_contract_v1(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    field = str(contract.get("source_timestamp") or "")
    maximum = float(contract.get("maximum_age_seconds") or 0)
    age = _iso_age_seconds(row.get(field)) if field else None
    current = age is not None and (maximum <= 0 or age <= maximum)
    return {"valid": current, "source_timestamp": row.get(field), "age_seconds": age,
            "maximum_age_seconds": maximum, "freshness_owner": contract.get("freshness_owner"),
            "stale_behavior": contract.get("stale_behavior") or "FAIL_CLOSED"}


def consumer_acknowledgement_v1(
    consumer: str, fields_consumed: list[str], *, canonical_source_acknowledged: bool,
    fallback_used: bool = False, rejected_fields: list[str] | None = None,
) -> dict[str, Any]:
    return {"consumer": consumer, "contract_version": "1.0.0", "fields_consumed": list(fields_consumed),
            "canonical_source_acknowledged": bool(canonical_source_acknowledged), "fallback_used": bool(fallback_used),
            "rejected_fields": list(rejected_fields or []), "source_compliant": bool(canonical_source_acknowledged) and not fallback_used}
