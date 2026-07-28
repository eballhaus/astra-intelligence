"""Canonical market timestamp helper.

Prefers provider-native timestamps embedded in market data (observation_timestamp,
market_timestamp, quote_timestamp, etc.) over Python `now()` so that every
risk decision is anchored to the actual moment the provider observed the market.

Falls back to the current UTC time only when no provider-native timestamp is
available, and flags the fallback so consumers know provenance is approximate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_market_timestamp_v1"


# Ordered list of provider-native timestamp fields to inspect.  Earlier entries
# are stronger provenance for the market observation itself.
_PROVIDER_NATIVE_FIELDS = (
    "observation_timestamp",
    "market_timestamp",
    "quote_timestamp",
    "trade_timestamp",
    "last_trade_timestamp",
    "bar_timestamp",
    "timestamp",
    "updated_at",
    "last_update_ts",
    "created_at",
)


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _parse_iso(value: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def canonical_market_timestamp_v1(
    record: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a canonical market timestamp from provider-native fields.

    Returns a dict with:
      - provider_native_timestamp: the provider-supplied ISO timestamp, or None
      - canonical_timestamp: the resolved timestamp (provider-native or fallback)
      - provenance: "provider_native" or "python_fallback"
      - source_field: which field supplied the provider-native timestamp
      - fallback_reason: present when falling back to now()
    """
    row = dict(record or {})
    native: str | None = None
    source_field: str | None = None

    for field in _PROVIDER_NATIVE_FIELDS:
        value = row.get(field)
        if value in (None, "", "None", "null"):
            continue
        text = _text(value)
        if _parse_iso(text) is not None:
            native = text
            source_field = field
            break

    if native:
        return {
            "schema_version": SCHEMA_VERSION,
            "provider_native_timestamp": native,
            "canonical_timestamp": native,
            "provenance": "provider_native",
            "source_field": source_field,
            "fallback_reason": None,
        }

    fallback = _iso(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider_native_timestamp": None,
        "canonical_timestamp": fallback,
        "provenance": "python_fallback",
        "source_field": None,
        "fallback_reason": "no_provider_native_timestamp_field_available",
    }


def canonical_market_timestamp_iso_v1(
    record: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> str:
    """Convenience wrapper returning only the canonical ISO timestamp."""
    return canonical_market_timestamp_v1(record, now)["canonical_timestamp"]
