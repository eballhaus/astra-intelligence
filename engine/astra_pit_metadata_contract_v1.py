"""Canonical point-in-time metadata for historical Astra evidence.

This module is pure and read-only. It normalizes one record at a time without
rewriting the source record and keeps replay admission fail-closed whenever
availability cannot be proven.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Any, Mapping


SCHEMA_VERSION = "astra_pit_metadata_v1"
POINT_IN_TIME_STATUSES = (
    "POINT_IN_TIME_SAFE",
    "PARTIALLY_POINT_IN_TIME",
    "CURRENT_SNAPSHOT_ONLY",
    "TIMESTAMP_INSUFFICIENT",
    "UNKNOWN",
)
LOOKAHEAD_RISKS = ("NONE", "LOW", "MODERATE", "HIGH", "UNKNOWN")


class UnsafeReplayRecord(ValueError):
    """Raised when a record cannot be admitted as contemporaneously known."""


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _timestamp(value: Any) -> tuple[int | None, str | None, str]:
    """Parse a timestamp and retain its original textual representation."""
    original = _text(value)
    if not original:
        return None, None, "unknown"
    try:
        number = float(original)
        if math.isfinite(number):
            if number > 10_000_000_000:
                number /= 1000.0
            return int(number), original, "second"
    except (TypeError, ValueError):
        pass
    raw = original.replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None, original, "unknown"
    precision = "day" if len(original) == 10 else "second"
    if parsed.tzinfo is None:
        if precision == "day":
            return int(parsed.replace(tzinfo=UTC).timestamp()), original, precision
        return None, original, precision
    return int(parsed.astimezone(UTC).timestamp()), original, precision


def _iso(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def _first_timestamp(record: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[int | None, str | None, str]:
    for key in keys:
        if record.get(key) not in (None, ""):
            parsed = _timestamp(record.get(key))
            if parsed[0] is not None or parsed[1] is not None:
                return parsed
    return None, None, "unknown"


def _precision(*values: str) -> str:
    order = {"unknown": 0, "day": 1, "second": 2, "minute": 3}
    return max(values, key=lambda item: order.get(item, 0), default="unknown")


def _record_id(record: Mapping[str, Any], dataset_type: str, source_file: str) -> str:
    existing = _text(record.get("record_id") or record.get("source_record_id"))
    if existing:
        return existing
    identity = {
        "dataset_type": dataset_type,
        "source_file": source_file,
        "symbol": record.get("symbol") or record.get("ticker") or record.get("canonical_pair"),
        "event_time": record.get("event_time") or record.get("timestamp") or record.get("ts") or record.get("date"),
        "source": record.get("source") or record.get("provider"),
    }
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]
    return f"pit:{dataset_type}:{digest}"


def _source_fields(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "timestamp", "ts", "date", "datetime", "provider_native_timestamp", "event_time",
        "bar_end_time", "bar_timestamp", "publication_time", "published_at", "publishedAt", "publishedDate",
        "acceptedDate", "fillingDate", "filing_timestamp", "period", "period_end", "observation_date", "effective_date",
        "announcement_date", "retrieved_at", "ingested_at", "stored_at", "as_of_timestamp",
        "vintage_date", "vintage_timestamp", "realtime_start", "release_time",
    )
    return {key: record[key] for key in keys if key in record}


def _dataset_mapping(record: Mapping[str, Any], dataset_type: str, context: Mapping[str, Any]) -> dict[str, Any]:
    dataset = _text(dataset_type).lower()
    if dataset in {"market_bar", "equity_bar", "crypto_bar", "etf_bar"}:
        event, event_raw, event_precision = _first_timestamp(record, ("bar_end_time", "event_time", "timestamp", "ts", "date", "datetime"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_native_timestamp", "provider_observed_time", "timestamp", "ts"))
        available, _, available_precision = _first_timestamp(record, ("available_to_astra_time", "bar_completed_at", "completed_at", "as_of_timestamp"))
        if available is None and bool(context.get("completed_bar_proven")) and event is not None:
            available = event
            available_precision = event_precision
        method = "market_bar_timestamp_and_completed_bar_contract"
        event_key = "bar end/timestamp"
    elif dataset in {"sec_filing", "fundamentals"}:
        event, event_raw, event_precision = _first_timestamp(record, ("period_end", "period", "event_time", "date"))
        publication, _, publication_precision = _first_timestamp(record, ("publication_time", "acceptedDate", "fillingDate", "filing_timestamp", "published_at"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "retrieved_at"))
        available = publication
        available_precision = publication_precision
        method = "period_end_separated_from_filing_publication"
        event_key = "period_end"
    elif dataset == "earnings":
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "earnings_date", "date", "period_end"))
        publication, _, publication_precision = _first_timestamp(record, ("publication_time", "published_at", "publishedDate", "release_time", "acceptedDate"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "retrieved_at"))
        available = publication
        available_precision = publication_precision
        method = "earnings_event_separated_from_release_time"
        event_key = "earnings event date"
    elif dataset in {"macro", "fred"}:
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "reference_date", "observation_date", "date", "period"))
        publication, _, publication_precision = _first_timestamp(record, ("publication_time", "release_time", "vintage_timestamp", "vintage_date", "realtime_start"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "retrieved_at"))
        available = publication
        available_precision = publication_precision
        method = "macro_reference_period_separated_from_release_or_vintage"
        event_key = "reference period"
    elif dataset in {"corporate_action", "split", "dividend", "symbol_change", "delisting"}:
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "effective_date", "date"))
        publication, _, publication_precision = _first_timestamp(record, ("publication_time", "announcement_timestamp", "announcement_date", "filing_timestamp"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "retrieved_at"))
        available = publication
        available_precision = publication_precision
        method = "corporate_action_effective_date_separated_from_announcement"
        event_key = "effective date"
    elif dataset in {"news", "catalyst"}:
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "event_timestamp", "date"))
        publication, _, publication_precision = _first_timestamp(record, ("publication_time", "published_at", "publishedAt", "provider_native_timestamp"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "retrieved_at"))
        available = publication
        available_precision = publication_precision
        method = "news_event_separated_from_publication_timestamp"
        event_key = "event timestamp"
    elif dataset in {"feature_snapshot", "forecast", "historical_feature"}:
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "source_timestamp", "timestamp", "as_of_timestamp"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "source_timestamp"))
        available, _, available_precision = _first_timestamp(record, ("available_to_astra_time", "as_of_timestamp"))
        method = "source_as_of_timestamp_only"
        event_key = "source/as-of timestamp"
    else:
        event, event_raw, event_precision = _first_timestamp(record, ("event_time", "timestamp", "ts", "date"))
        observed, _, observed_precision = _first_timestamp(record, ("provider_observed_time", "provider_native_timestamp", "retrieved_at"))
        available, _, available_precision = _first_timestamp(record, ("available_to_astra_time", "as_of_timestamp"))
        method = "generic_explicit_timestamp_fields_only"
        event_key = "explicit event timestamp"
    return {
        "event": event,
        "event_raw": event_raw,
        "event_precision": event_precision,
        "observed": observed,
        "observed_precision": observed_precision,
        "available": available,
        "available_precision": available_precision,
        "publication": locals().get("publication"),
        "publication_precision": locals().get("publication_precision", "unknown"),
        "method": method,
        "event_key": event_key,
    }


def normalize_historical_record(
    record: Mapping[str, Any],
    *,
    dataset_type: str,
    source_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return canonical PIT metadata while preserving raw source fields."""
    context = dict(source_context or {})
    raw = dict(record)
    mapping = _dataset_mapping(raw, dataset_type, context)
    source_file = _text(raw.get("source_file") or context.get("source_file"))
    source_provider = _text(raw.get("source_provider") or raw.get("provider") or raw.get("source")) or None
    source_endpoint = _text(raw.get("source_endpoint") or context.get("source_endpoint")) or None
    ingested, _, ingested_precision = _first_timestamp(raw, ("ingested_at", "retrieved_at", "provider_observed_time"))
    stored, _, stored_precision = _first_timestamp(raw, ("stored_at", "ingested_at"))
    event = mapping["event"]
    available = mapping["available"]
    publication = mapping["publication"]
    if event is None:
        status = "UNKNOWN" if not _source_fields(raw) else "TIMESTAMP_INSUFFICIENT"
        reason = "no deterministic event timestamp" if status == "UNKNOWN" else "timestamp field present but unparsable or timezone-naive"
        risk = "UNKNOWN"
    elif available is None:
        status = "CURRENT_SNAPSHOT_ONLY" if context.get("current_snapshot_only") else "TIMESTAMP_INSUFFICIENT"
        reason = "availability/publication time is not provable; event time is not a substitute"
        risk = "HIGH" if status == "CURRENT_SNAPSHOT_ONLY" else "UNKNOWN"
    elif available < event and not context.get("allow_availability_before_event"):
        status = "PARTIALLY_POINT_IN_TIME"
        reason = "availability precedes event time; source contract needs review"
        risk = "HIGH"
    elif mapping["event_precision"] == "day" and mapping["available_precision"] == "day":
        status = "PARTIALLY_POINT_IN_TIME"
        reason = "date precision is insufficient to prove intraday availability order"
        risk = "MODERATE"
    else:
        status = "POINT_IN_TIME_SAFE"
        reason = "event and availability timestamps are explicit and chronologically ordered"
        risk = "LOW" if publication is None else "NONE"
    replay_safe = status == "POINT_IN_TIME_SAFE" and bool(context.get("replay_contract_valid", True))
    if context.get("validated_archive") and event is not None and available is not None and status != "POINT_IN_TIME_SAFE":
        replay_safe = False
    if dataset_type.lower() in {"news", "catalyst"} and not context.get("_historical_gate_internal") and (
        raw.get("historical_news_contract") or (source_provider or "").upper() == "FINNHUB"
    ):
        gate = historical_news_evidence_gate(raw, raw.get("available_to_astra_time"))
        replay_safe = gate["replay_allowed"] and bool(context.get("replay_contract_valid", True))
        status = "POINT_IN_TIME_SAFE" if replay_safe else "PARTIALLY_POINT_IN_TIME"
        reason = gate["reason"]
        risk = "NONE" if replay_safe else "HIGH"
        available = _timestamp(raw.get("available_to_astra_time"))[0]
        mapping["observed"] = _timestamp(raw.get("provider_observed_time"))[0]
    if dataset_type.lower() in {"macro", "fred"}:
        vintage, _, vintage_precision = _first_timestamp(raw, ("vintage_timestamp", "realtime_start", "vintage_date"))
        if context.get("current_snapshot_only") or vintage is None or mapping["available_precision"] != "second":
            replay_safe = False
            status = "CURRENT_SNAPSHOT_ONLY" if context.get("current_snapshot_only") or vintage is None else "PARTIALLY_POINT_IN_TIME"
            reason = "REJECTED: a historical vintage and precise availability are required; current revised values cannot be backdated"
            risk = "HIGH"
    symbol = _text(raw.get("symbol") or raw.get("ticker") or raw.get("canonical_pair")) or None
    asset_class = _text(raw.get("asset_class") or raw.get("asset_type")) or None
    return {
        **({key: raw.get(key) for key in ("historical_news_contract", "article_id", "version_id", "raw_hash", "availability_proof", "raw_provenance", "temporal_contradiction")}
           if raw.get("historical_news_contract") and not context.get("_historical_gate_internal") else {}),
        "schema_version": SCHEMA_VERSION,
        "record_id": _record_id(raw, _text(dataset_type).lower(), source_file),
        "dataset_type": _text(dataset_type).lower(),
        "symbol": symbol,
        "asset_class": asset_class,
        "event_time": _iso(event),
        "publication_time": raw.get("publication_time") if raw.get("historical_news_contract") else _iso(publication),
        "historical_source_available_time": raw.get("historical_source_available_time"),
        "provider_observed_time": _iso(mapping["observed"]),
        "available_to_astra_time": raw.get("available_to_astra_time") if raw.get("historical_news_contract") else _iso(available),
        "ingested_at": _iso(ingested),
        "stored_at": _iso(stored),
        "source_provider": source_provider,
        "source_endpoint": source_endpoint,
        "source_record_id": _text(raw.get("source_record_id") or raw.get("record_id")) or None,
        "source_file": source_file or None,
        "source_provenance": raw.get("source_provenance") or raw.get("provenance") or context.get("source_provenance") or {},
        "timezone": _text(raw.get("timezone")) or ("UTC" if mapping["event_precision"] == "second" else None),
        "timestamp_precision": _precision(mapping["event_precision"], mapping["observed_precision"], mapping["available_precision"], ingested_precision, stored_precision),
        "point_in_time_status": status,
        "lookahead_risk": risk,
        "replay_safe": replay_safe,
        "replay_safe_reason": reason if replay_safe else f"REJECTED: {reason}",
        "normalization_method": mapping["method"],
        "normalization_confidence": "HIGH" if status == "POINT_IN_TIME_SAFE" else "MEDIUM" if status == "PARTIALLY_POINT_IN_TIME" else "LOW",
        "original_timestamp_fields": _source_fields(raw),
    }


def replay_readiness(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return an explicit admission decision for historical causal use."""
    normalized = dict(record)
    safe = normalized.get("replay_safe") is True and normalized.get("point_in_time_status") == "POINT_IN_TIME_SAFE"
    if safe and normalized.get("historical_news_contract"):
        safe = historical_news_evidence_gate(normalized, normalized.get("available_to_astra_time"))["replay_allowed"]
    return {
        "replay_allowed": safe,
        "record_id": normalized.get("record_id"),
        "point_in_time_status": normalized.get("point_in_time_status", "UNKNOWN"),
        "lookahead_risk": normalized.get("lookahead_risk", "UNKNOWN"),
        "reason": "PIT metadata proves availability" if safe else normalized.get("replay_safe_reason") or "PIT metadata is missing or unsafe",
    }


def require_replay_safe(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fail closed rather than admitting an unsafe historical record."""
    decision = replay_readiness(record)
    if not decision["replay_allowed"]:
        raise UnsafeReplayRecord(f"{decision.get('record_id') or 'record'}: {decision['reason']}")
    return record


def historical_news_evidence_gate(record: Mapping[str, Any], cutoff: Any, *, basis: str = "historical_source") -> dict[str, Any]:
    """HISTORICAL_NEWS_EVIDENCE_GATE: additional evidence, then canonical admission.

    SEC accession acceptance is the existing approved source basis. Other news
    requires a separately verified, version-bound evidence artifact. A caller's
    replay_safe flag or publication timestamp alone is never evidence.
    """
    publication, _, precision = _timestamp(record.get("publication_time"))
    available, _, ap = _timestamp(record.get("historical_source_available_time"))
    receipt, _, rp = _timestamp(record.get("available_to_astra_time"))
    limit, _, cp = _timestamp(cutoff)
    proof = record.get("availability_proof")
    proof = proof if isinstance(proof, Mapping) else {}
    identity = record.get("article_id") or record.get("source_record_id")
    version = record.get("version_id")
    sec = (record.get("source_provider") == "SEC_EDGAR" and proof.get("basis") == "SEC_ACCEPTANCE"
           and proof.get("accession") == identity and proof.get("acceptance_time") == record.get("publication_time"))
    # No generic provider proof validator has been established yet. Fail closed
    # until such a validator is implemented in this canonical owner.
    raw = record.get("raw_provenance")
    raw = raw if isinstance(raw, Mapping) else {}
    raw_digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    proven = (sec and proof.get("raw_hash") == record.get("raw_hash") == raw_digest
              and raw.get("accessionNumber") == identity
              and _timestamp(raw.get("acceptanceDateTime"))[0] == publication)
    def exact(value):
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return stamp.timestamp() if stamp.tzinfo else None
        except (ValueError, TypeError, OverflowError):
            return None
    publication, available, receipt, limit = (
            exact(record.get("publication_time")), exact(record.get("historical_source_available_time")),
            exact(record.get("available_to_astra_time")), exact(cutoff))
    expected_version = hashlib.sha256(json.dumps(["SEC_EDGAR", identity, raw_digest], separators=(",", ":")).encode()).hexdigest()
    proven = proven and version == expected_version and exact(raw.get("acceptanceDateTime")) == publication
    valid = bool(proven and identity and version and record.get("raw_hash") and publication is not None
                 and available is not None and receipt is not None and limit is not None
                 and precision == ap == rp == cp == "second" and publication <= available <= receipt
                 and not record.get("temporal_contradiction") and basis in {"historical_source", "actual_astra"})
    if not valid:
        return {"gate": "HISTORICAL_NEWS_EVIDENCE_GATE", "replay_allowed": False,
                "reason": "REJECTED: historical availability/version evidence or cutoff is insufficient"}
    admission = normalize_historical_record(
        {**record, "event_time": record.get("publication_time")}, dataset_type="catalyst",
        source_context={"replay_contract_valid": valid, "_historical_gate_internal": True})
    allowed = valid and replay_readiness(admission)["replay_allowed"] and limit >= (receipt if basis == "actual_astra" else available)
    return {"gate": "HISTORICAL_NEWS_EVIDENCE_GATE", "replay_allowed": bool(allowed),
            "reason": "version-bound SEC acceptance and canonical PIT admission" if allowed else "REJECTED: historical availability/version evidence or cutoff is insufficient"}
