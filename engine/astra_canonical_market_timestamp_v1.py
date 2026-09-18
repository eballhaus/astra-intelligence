"""Strict provider-native market-observation timestamp contract.

Retrieval and record timestamps document when Astra received or persisted a
payload.  They are never evidence that the market was observed at that time.
Risk engines consume this contract so missing market time fails closed instead
of becoming artificially fresh at the next worker cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_canonical_market_timestamp_v1"

SOURCE_QUOTE = "QUOTE"
SOURCE_TRADE = "TRADE"
SOURCE_COMPLETED_BAR = "COMPLETED_BAR"
SOURCE_BROKER_POSITION_SNAPSHOT = "BROKER_POSITION_SNAPSHOT"
SOURCE_CACHE = "CACHE"

# Alpaca IEX native quote timestamps have been observed a few milliseconds
# ahead of Astra's receipt clock.  This is only a bounded quote-ingestion
# tolerance; the default canonical contract remains zero-tolerance.
ALPACA_EQUITY_FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 0.25

_SOURCE_FIELDS = {
    SOURCE_QUOTE: ("provider_quote_timestamp", "provider_native_timestamp", "quote_timestamp", "observation_timestamp", "market_timestamp"),
    SOURCE_TRADE: ("provider_trade_timestamp", "trade_timestamp", "last_trade_timestamp", "observation_timestamp", "market_timestamp"),
    SOURCE_COMPLETED_BAR: ("provider_bar_timestamp", "bar_timestamp", "completed_bar_timestamp", "observation_timestamp"),
    # A cache may retain an already-validated observation, but must never turn
    # its own refresh time into a market timestamp.
    SOURCE_CACHE: ("market_observation_timestamp", "provider_native_timestamp", "original_observation_timestamp"),
    SOURCE_BROKER_POSITION_SNAPSHOT: (),
}


def _iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    return current.isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_iso(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _infer_source_type(row: Mapping[str, Any]) -> str:
    explicit = _text(row.get("market_source_type") or row.get("source_type")).upper()
    if explicit in _SOURCE_FIELDS:
        return explicit
    if any(_text(row.get(field)) for field in _SOURCE_FIELDS[SOURCE_QUOTE]):
        return SOURCE_QUOTE
    if any(_text(row.get(field)) for field in _SOURCE_FIELDS[SOURCE_TRADE]):
        return SOURCE_TRADE
    if any(_text(row.get(field)) for field in _SOURCE_FIELDS[SOURCE_COMPLETED_BAR]):
        return SOURCE_COMPLETED_BAR
    return SOURCE_BROKER_POSITION_SNAPSHOT


def provider_future_timestamp_tolerance_seconds_v1(
    record: Mapping[str, Any] | None,
    *,
    source_type: str | None = None,
    asset_type: str | None = None,
) -> float:
    """Return the measured, provider-scoped future timestamp tolerance.

    Only live Alpaca equity quotes use this receipt-clock jitter allowance.
    Other providers, source types, and crypto retain the strict default.
    """
    row = dict(record or {})
    kind = _text(source_type or row.get("market_source_type") or row.get("source_type")).upper() or _infer_source_type(row)
    if kind != SOURCE_QUOTE:
        return 0.0
    asset = _text(asset_type or row.get("asset_type") or row.get("asset_class") or row.get("instrument_type")).lower()
    provider = _text(
        row.get("provider_used")
        or row.get("provider_name")
        or row.get("quote_source")
        or row.get("provider")
    ).upper()
    if asset in {"stock", "equity", "etf"} and provider in {"ALPACA", "ALPACA_MARKET_DATA", "ALPACA_SIP", "ALPACA_IEX"}:
        return ALPACA_EQUITY_FUTURE_TIMESTAMP_TOLERANCE_SECONDS
    return 0.0


def canonical_market_timestamp_v1(
    record: Mapping[str, Any] | None,
    now: datetime | None = None,
    *,
    source_type: str | None = None,
    max_age_seconds: float | None = None,
    future_tolerance_seconds: float = 0.0,
) -> dict[str, Any]:
    """Return strict observation provenance for a market-evidence record.

    ``now`` is intentionally used only for retrieval/generated fields and
    validity checks.  It can never populate ``market_observation_timestamp``.
    Generic record fields (``timestamp``, ``updated_at``, ``created_at``) are
    deliberately absent from the accepted field map.
    """
    row = dict(record or {})
    kind = _text(source_type or row.get("market_source_type") or row.get("source_type")).upper() or _infer_source_type(row)
    current = now or datetime.now(timezone.utc)
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    retrieval = _text(row.get("retrieval_timestamp") or row.get("retrieved_at") or row.get("fetched_at")) or _iso(current)
    generated = _text(row.get("generated_at")) or _iso(current)
    created = _text(row.get("record_created_at") or row.get("created_at"))

    observation: str | None = None
    field: str | None = None
    parsed: datetime | None = None
    for candidate in _SOURCE_FIELDS.get(kind, ()):
        value = _text(row.get(candidate))
        if not value:
            continue
        parsed_value = _parse_iso(value)
        if parsed_value is None:
            # An explicitly supplied native field with invalid content must not
            # silently fall through to another generic timestamp.
            return _result(kind, None, candidate, retrieval, generated, created, "INVALID", False, "INVALID_PROVIDER_NATIVE_TIMESTAMP")
        observation, field, parsed = value, candidate, parsed_value
        break

    if observation is None:
        return _result(kind, None, None, retrieval, generated, created, "UNAVAILABLE", False, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")
    tolerance = max(0.0, float(future_tolerance_seconds or 0.0))
    future_offset_seconds = (parsed - current).total_seconds() if parsed else None
    if future_offset_seconds is not None and future_offset_seconds > tolerance:
        return _result(
            kind,
            observation,
            field,
            retrieval,
            generated,
            created,
            "INVALID",
            False,
            "FUTURE_PROVIDER_NATIVE_TIMESTAMP",
            None,
            future_offset_seconds=future_offset_seconds,
            future_tolerance_seconds=tolerance,
        )
    age_seconds = max(0.0, (current - parsed).total_seconds()) if parsed else None
    if max_age_seconds is not None and age_seconds is not None and age_seconds > float(max_age_seconds):
        return _result(
            kind,
            observation,
            field,
            retrieval,
            generated,
            created,
            "STALE",
            False,
            "STALE_PROVIDER_NATIVE_TIMESTAMP",
            age_seconds,
            future_offset_seconds=future_offset_seconds,
            future_tolerance_seconds=tolerance,
        )
    executable = kind in {SOURCE_QUOTE, SOURCE_TRADE}
    return _result(
        kind,
        observation,
        field,
        retrieval,
        generated,
        created,
        "FRESH",
        executable,
        None,
        age_seconds,
        future_offset_seconds=future_offset_seconds,
        future_tolerance_seconds=tolerance,
    )


def _result(
    source_type: str,
    observation: str | None,
    field: str | None,
    retrieval: str,
    generated: str,
    created: str,
    freshness: str,
    executable: bool,
    blocker: str | None,
    age_seconds: float | None = None,
    *,
    future_offset_seconds: float | None = None,
    future_tolerance_seconds: float = 0.0,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_type": source_type,
        "market_observation_timestamp": observation,
        "provider_native_timestamp": observation,
        "canonical_timestamp": observation,
        "retrieval_timestamp": retrieval,
        "generated_at": generated,
        "record_created_at": created or None,
        "provenance": "provider_native" if observation else "unavailable",
        "source_field": field,
        "freshness_status": freshness,
        "executable_freshness": bool(executable and freshness == "FRESH"),
        "market_observation_unavailable": observation is None,
        "first_causal_blocker": blocker,
        "age_seconds": age_seconds,
        "future_offset_seconds": future_offset_seconds,
        "future_tolerance_seconds": float(future_tolerance_seconds or 0.0),
        "future_timestamp_tolerated": bool(
            future_offset_seconds is not None
            and future_offset_seconds > 0.0
            and future_offset_seconds <= float(future_tolerance_seconds or 0.0)
        ),
    }


def canonical_market_timestamp_iso_v1(record: Mapping[str, Any] | None, now: datetime | None = None, **kwargs: Any) -> str:
    """Compatibility helper; unavailable observation time is represented by ''."""
    return str(canonical_market_timestamp_v1(record, now, **kwargs).get("market_observation_timestamp") or "")
