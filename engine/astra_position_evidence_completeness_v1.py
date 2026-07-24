"""Worker-owned evidence completeness for current canonical broker positions.

This module deliberately projects existing cached evidence.  It never refreshes a
provider, mutates broker truth, or invents thesis, lane, or horizon metadata.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_position_evidence_completeness_v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _age_seconds(value: Any, now: datetime) -> float | None:
    try:
        observed = datetime.fromisoformat(_text(value).replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError):
        return None
    return max(0.0, (now - observed).total_seconds())


def _status(record: Mapping[str, Any], *, timestamp: str, fresh_seconds: int, aging_seconds: int) -> tuple[str, float | None]:
    row = dict(record or {})
    if not row:
        return "MISSING", None
    state = _text(row.get("response_state")).upper()
    if state not in {"SUCCESS", "STALE_PRIOR_USED"}:
        return ("EXTERNALLY_UNAVAILABLE" if state in {"EMPTY_RESPONSE", "UNSUPPORTED_ENDPOINT"} else "PRODUCER_FAILED"), None
    age = _age_seconds(row.get(timestamp) or row.get("received_at") or row.get("response_at"), datetime.now(UTC))
    if age is None:
        return "PRODUCER_FAILED", None
    if age <= fresh_seconds and _text(row.get("freshness_state")).upper() == "CURRENT":
        return "FRESH", age
    if age <= aging_seconds:
        return "AGING", age
    return "STALE", age


def _by_symbol(records: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _identifier, raw in (records or {}).items():
        bundle = dict(raw or {})
        symbol = ""
        for item in bundle.values():
            if isinstance(item, Mapping) and _text(item.get("symbol")):
                symbol = _text(item.get("symbol")).upper()
                break
        if symbol:
            result[symbol] = bundle
    return result


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def build_position_evidence_completeness_v1(
    broker_positions: Mapping[str, Mapping[str, Any]],
    recovery: Mapping[str, Any],
    *,
    market_evidence: Mapping[str, Any] | None = None,
    fmp_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return exactly one evidence availability row for every broker-open symbol."""
    recovery_by_symbol = {_text(row.get("symbol")).upper(): dict(row) for row in recovery.get("positions") or [] if isinstance(row, Mapping)}
    market_by_symbol = _by_symbol(market_evidence or {})
    fmp_by_symbol = {
        _text(row.get("symbol")).upper(): dict(row)
        for row in (fmp_evidence or {}).values()
        if isinstance(row, Mapping) and _text(row.get("symbol"))
    }
    rows: list[dict[str, Any]] = []
    for symbol, raw_position in sorted((broker_positions or {}).items()):
        position = dict(raw_position or {})
        symbol = _text(position.get("symbol") or symbol).upper()
        bundle = market_by_symbol.get(symbol, {})
        quote = dict(bundle.get("LATEST_QUOTE") or {})
        bars = dict(bundle.get("HISTORICAL_BARS") or bundle.get("HISTORICAL_BARS_ALPACA") or {})
        fmp = dict(fmp_by_symbol.get(symbol) or {})
        auxiliary = dict(fmp.get("auxiliary_context") or {})
        quote_status, quote_age = _status(quote, timestamp="quote_timestamp", fresh_seconds=90, aging_seconds=15 * 60)
        bar_status, bar_age = _status(bars, timestamp="last_bar_at", fresh_seconds=6 * 60 * 60, aging_seconds=2 * 24 * 60 * 60)
        fmp_status, _fmp_age = _status(fmp, timestamp="response_at", fresh_seconds=6 * 60 * 60, aging_seconds=7 * 24 * 60 * 60)
        earnings_status, _earnings_age = _status(dict(auxiliary.get("earnings") or {}), timestamp="response_at", fresh_seconds=6 * 60 * 60, aging_seconds=7 * 24 * 60 * 60)
        catalyst_status, _catalyst_age = _status(dict(auxiliary.get("news_catalyst") or {}), timestamp="response_at", fresh_seconds=15 * 60, aging_seconds=6 * 60 * 60)
        closes = [_number(item.get("close"), 0.0) for item in bars.get("bars") or [] if isinstance(item, Mapping)]
        momentum = "MISSING"
        if bar_status in {"FRESH", "AGING"} and len(closes) >= 2 and closes[0] > 0:
            change = (closes[-1] - closes[0]) / closes[0]
            momentum = "IMPROVING" if change > 0.01 else "DETERIORATING" if change < -0.01 else "STABLE"
        recovery_row = recovery_by_symbol.get(symbol, {})
        missing_producer = ""
        if not bundle:
            missing_producer = "OPEN_POSITION_EVIDENCE_REGISTRATION_MISSING"
        elif quote_status in {"MISSING", "PRODUCER_FAILED", "EXTERNALLY_UNAVAILABLE"}:
            missing_producer = "CURRENT_QUOTE_PRODUCER_UNAVAILABLE"
        elif bar_status in {"MISSING", "PRODUCER_FAILED", "EXTERNALLY_UNAVAILABLE"}:
            missing_producer = "COMPLETED_BAR_PRODUCER_UNAVAILABLE"
        elif fmp_status in {"MISSING", "PRODUCER_FAILED", "EXTERNALLY_UNAVAILABLE"}:
            missing_producer = "FUNDAMENTAL_CATALYST_PRODUCER_UNAVAILABLE"
        elif quote_status == "STALE":
            missing_producer = "CURRENT_QUOTE_EVIDENCE_STALE"
        elif bar_status == "STALE":
            missing_producer = "COMPLETED_BAR_EVIDENCE_STALE"
        completeness = sum(value in {"FRESH", "AGING"} for value in (quote_status, bar_status, fmp_status)) / 3.0
        fmp_assigned = bool(fmp.get("record_id") and fmp.get("normalized_fields"))
        fmp_consumed = bool(fmp.get("consumer_acknowledged"))
        fmp_status = "ASSIGNED_NOT_CONSUMED" if fmp_assigned and not fmp_consumed else fmp_status
        rows.append({
            "symbol": symbol,
            "broker_position_present": True,
            "legacy_status": "LEGACY" if _text(recovery_row.get("metadata_generation")).upper() != "V1_MANDATORY" else "V1_MANDATORY",
            "canonical_lane_status": _text(recovery_row.get("lane_status")) or "UNAVAILABLE",
            "canonical_horizon_status": _text(recovery_row.get("horizon_status")) or "UNAVAILABLE",
            "quote_status": quote_status, "quote_source": quote.get("provider"), "quote_evidence_at": quote.get("quote_timestamp") or quote.get("received_at"), "quote_age_seconds": quote_age,
            "completed_bar_status": bar_status, "completed_bar_source": bars.get("provider"), "completed_bar_evidence_at": bars.get("last_bar_at") or bars.get("received_at"), "completed_bar_age_seconds": bar_age,
            "momentum_status": momentum, "momentum_source": bars.get("provider") if momentum != "MISSING" else None,
            "liquidity_status": "FRESH" if quote_status == "FRESH" and _number(quote.get("bid")) > 0 and _number(quote.get("ask")) >= _number(quote.get("bid")) else "MISSING",
            "spread_status": "FRESH" if quote_status == "FRESH" and _number(quote.get("bid")) > 0 and _number(quote.get("ask")) >= _number(quote.get("bid")) else "MISSING",
            "volume_status": "FRESH" if bar_status in {"FRESH", "AGING"} and any(_number(item.get("volume")) > 0 for item in bars.get("bars") or [] if isinstance(item, Mapping)) else "MISSING",
            "earnings_status": earnings_status, "earnings_source": (auxiliary.get("earnings") or {}).get("provider"),
            "catalyst_status": catalyst_status, "catalyst_source": (auxiliary.get("news_catalyst") or {}).get("provider"),
            "fundamentals_status": fmp_status,
            "sector_status": "FRESH" if fmp_status in {"FRESH", "AGING"} and fmp.get("normalized_fields") else "MISSING",
            "market_regime_status": "NOT_APPLICABLE", "profit_giveback_status": "NOT_APPLICABLE",
            "position_age_status": "EXTERNALLY_UNAVAILABLE",
            "opportunity_cost_status": "NO_ELIGIBLE_REPLACEMENT",
            "replacement_candidate_status": "NO_ELIGIBLE_REPLACEMENT",
            "evidence_completeness_score": round(completeness, 3),
            "evidence_confidence": "HIGH" if completeness == 1 else "MODERATE" if completeness >= 0.5 else "LOW",
            "first_missing_producer": missing_producer,
            "first_failed_consumer": "",
            "first_causal_blocker": missing_producer or "EVIDENCE_CURRENT",
        })
    return {
        "schema_version": SCHEMA_VERSION, "generated_at": _now(), "broker_position_count": len(broker_positions or {}),
        "positions": rows, "positions_represented": len(rows),
        "fresh_quote_count": sum(row["quote_status"] == "FRESH" for row in rows),
        "fresh_completed_bar_count": sum(row["completed_bar_status"] == "FRESH" for row in rows),
        "momentum_available_count": sum(row["momentum_status"] != "MISSING" for row in rows),
        "fundamentals_available_count": sum(row["fundamentals_status"] in {"FRESH", "AGING"} for row in rows),
        "earnings_available_count": sum(row["earnings_status"] in {"FRESH", "AGING"} for row in rows),
        "catalyst_available_count": sum(row["catalyst_status"] in {"FRESH", "AGING"} for row in rows),
        "opportunity_cost_available_count": sum(row["opportunity_cost_status"] != "MISSING" for row in rows),
        "replacement_available_count": sum(row["replacement_candidate_status"] != "MISSING" for row in rows),
        "first_missing_producer_count": sum(bool(row["first_missing_producer"]) for row in rows),
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
        "state_mutations_from_get": 0, "paper_only_preserved": True, "advisory_only": True,
    }


def save_position_evidence_completeness_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_position_evidence_completeness_v1.json", payload)


def load_position_evidence_completeness_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try:
        payload = json.loads((Path(state_dir) / "astra_position_evidence_completeness_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
