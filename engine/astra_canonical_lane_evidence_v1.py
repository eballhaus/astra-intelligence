"""Canonical, current-data evidence for equity SCALP and SWING lanes.

This module is deliberately evidence-only.  It does not qualify candidates,
select opportunities, authorize orders, or write trading truth.  Every derived
value is computed from the supplied current quote, canonical timestamp, and
completed-bar evidence, with an explicit provenance record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any, Mapping

from engine.astra_canonical_market_timestamp_v1 import (
    SOURCE_QUOTE,
    canonical_market_timestamp_v1,
    provider_future_timestamp_tolerance_seconds_v1,
)


VERSION = "1.0.0"
AUTHORITY_CLASS = "PRETRADE_CANONICAL_EVIDENCE"
SCALP_QUOTE_MAX_AGE_SECONDS = 20.0
SCALP_STRUCTURE_MIN_BARS = 4
SWING_STRUCTURE_MIN_BARS = 20
SCALP_TIMEFRAMES = {"5MIN", "15MIN", "1HOUR", "5M", "15M", "1H"}
SWING_TIMEFRAMES = {"1DAY", "1D", "1HOUR", "1H"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _field(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, "", {}, []):
            return value
    return None


def _score(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(_clamp(number), 3)


def _provenance(
    *,
    source_system: str,
    source_timestamp: str | None,
    input_fields: list[str],
    timeframe: str | None = None,
    lookback: int | None = None,
    source_field: str | None = None,
) -> dict[str, Any]:
    return {
        "source_system": source_system,
        "source_timestamp": source_timestamp,
        "source_timestamp_state": "AVAILABLE" if source_timestamp else "UNAVAILABLE",
        "input_fields": list(input_fields),
        "timeframe": timeframe,
        "lookback_bars": lookback,
        "source_field": source_field,
        "producer_version": VERSION,
        "authority_class": AUTHORITY_CLASS,
    }


def _quote_timestamp(row: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    record = dict(row or {})
    tolerance = provider_future_timestamp_tolerance_seconds_v1(record, source_type=SOURCE_QUOTE)
    return canonical_market_timestamp_v1(
        record,
        now=now,
        source_type=SOURCE_QUOTE,
        max_age_seconds=SCALP_QUOTE_MAX_AGE_SECONDS,
        future_tolerance_seconds=tolerance,
    )


def _valid_bars(
    row: Mapping[str, Any],
    *,
    now: datetime,
    allowed_timeframes: set[str],
    minimum: int,
    evidence_key: str = "bar_evidence",
    bars_key: str = "completed_bars",
    timeframe_key: str = "bar_timeframe",
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    evidence = row.get(evidence_key) if isinstance(row.get(evidence_key), Mapping) else {}
    raw_bars = row.get(bars_key) or evidence.get("completed_bars")
    resolution = _text(row.get(timeframe_key) or evidence.get("resolution")).upper()
    # Preserve the established generic completed-bar contract for fixtures and
    # existing producers that provide one bar set. A dedicated swing set wins
    # when present, allowing 15-minute risk bars and 1-hour swing bars to
    # coexist without changing either lane's requirements.
    if not raw_bars and bars_key != "completed_bars":
        generic_evidence = row.get("bar_evidence") if isinstance(row.get("bar_evidence"), Mapping) else {}
        raw_bars = row.get("completed_bars") or generic_evidence.get("completed_bars")
        if not resolution:
            resolution = _text(row.get("bar_timeframe") or generic_evidence.get("resolution")).upper()
    if resolution not in allowed_timeframes or not isinstance(raw_bars, list):
        return [], resolution or None, None

    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for raw in raw_bars:
        if not isinstance(raw, Mapping) or raw.get("is_complete") is not True:
            return [], resolution, None
        stamp = _timestamp(_field(raw, "provider_native_timestamp", "timestamp", "bar_timestamp"))
        if stamp is None or stamp > now:
            return [], resolution, None
        values = {key: _number(raw.get(key)) for key in ("open", "high", "low", "close", "volume")}
        if any(values[key] is None for key in ("open", "high", "low", "close")):
            return [], resolution, None
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
            return [], resolution, None
        parsed.append((stamp, {**dict(raw), **values, "_timestamp": stamp}))

    parsed.sort(key=lambda item: item[0])
    if len(parsed) < minimum or any(left[0] >= right[0] for left, right in zip(parsed, parsed[1:])):
        return [], resolution, None
    bars = [item[1] for item in parsed]
    return bars, resolution, _iso(parsed[-1][0])


def _returns(bars: list[dict[str, Any]]) -> list[float]:
    values = [float(bar["close"]) for bar in bars]
    return [((right / left) - 1.0) * 100.0 if left else 0.0 for left, right in zip(values, values[1:])]


def _structure(bars: list[dict[str, Any]], *, timeframe: str, minimum: int, state_name: str) -> tuple[dict[str, Any] | None, float | None, float | None]:
    if len(bars) < minimum:
        return None, None, None
    returns = _returns(bars)
    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in returns]
    net = sum(returns)
    direction = "UP" if net > 0 else "DOWN" if net < 0 else "FLAT"
    persistence = abs(sum(signs)) / max(1, len(signs)) * 100.0
    efficiency = abs(net) / max(0.000001, sum(abs(value) for value in returns)) * 100.0
    higher = sum(
        1 for left, right in zip(bars, bars[1:])
        if right["high"] > left["high"] and right["low"] > left["low"]
    )
    lower = sum(
        1 for left, right in zip(bars, bars[1:])
        if right["high"] < left["high"] and right["low"] < left["low"]
    )
    structure_consistency = max(higher, lower) / max(1, len(bars) - 1) * 100.0
    trend_quality = (persistence + efficiency + structure_consistency) / 3.0
    if direction == "UP" and higher >= lower and higher > 0:
        state = "UPTREND"
    elif direction == "DOWN" and lower > higher and lower > 0:
        state = "DOWNTREND"
    elif direction == "FLAT":
        state = "RANGE"
    else:
        state = "MIXED"
    structure = {
        "schema_version": "astra_multi_day_structure_v1" if state_name == "multi_day" else "astra_intraday_structure_v1",
        "state": state,
        "direction": direction,
        "lookback_bars": len(bars),
        "timeframe": timeframe,
        "last_completed_timestamp": _iso(bars[-1]["_timestamp"]),
        "net_return_pct": round(net, 6),
        "directional_persistence_pct": round(persistence, 6),
        "trend_efficiency_pct": round(efficiency, 6),
        "structure_consistency_pct": round(structure_consistency, 6),
        "no_future_bars": True,
    }
    return structure, round(persistence, 3), round(trend_quality, 3)


def _volatility_score(row: Mapping[str, Any], bars: list[dict[str, Any]], last_timestamp: str | None) -> tuple[float | None, dict[str, Any] | None]:
    direct = _score(_field(row, "atr_percentile", "volatility_percentile"))
    if direct is not None:
        return direct, _provenance(
            source_system="current_point_in_time_volatility_context",
            source_timestamp=last_timestamp,
            input_fields=["atr_percentile"],
            source_field="atr_percentile",
        )
    ranges: list[float] = []
    for bar in bars:
        close = float(bar["close"])
        if close <= 0:
            continue
        ranges.append((float(bar["high"]) - float(bar["low"])) / close * 100.0)
    if not ranges:
        return None, None
    latest = ranges[-1]
    percentile = sum(1 for value in ranges if value <= latest) / len(ranges) * 100.0
    return round(percentile, 3), _provenance(
        source_system="current_completed_bars",
        source_timestamp=last_timestamp,
        input_fields=["high", "low", "close"],
        timeframe=_text(row.get("bar_timeframe") or (row.get("bar_evidence") or {}).get("resolution")),
        lookback=len(ranges),
        source_field="completed_bars.range_percentile",
    )


def build_lane_evidence_v1(row: Mapping[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Build current SCALP/SWING evidence without producing execution authority."""
    source = dict(row or {})
    current = now or datetime.now(timezone.utc)
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    symbol = _text(source.get("symbol") or source.get("ticker")).upper()
    quote = _quote_timestamp(source, current)
    quote_stamp = quote.get("market_observation_timestamp")
    raw_evidence: dict[str, Any] = {"symbol": symbol}
    derived: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    missing: dict[str, list[str]] = {"SCALP": [], "SWING": []}

    price = _number(_field(source, "price", "current_price"))
    bid = _number(_field(source, "bid", "bid_price"))
    ask = _number(_field(source, "ask", "ask_price"))
    raw_evidence.update({"price": price, "bid": bid, "ask": ask, "quote_timestamp": quote_stamp})
    if price is not None and price > 0 and bid is not None and ask is not None and 0 < bid <= ask:
        spread_pct = _number(_field(source, "spread_pct", "bid_ask_spread_pct"))
        if spread_pct is None:
            spread_pct = ((ask - bid) / ((ask + bid) / 2.0)) * 100.0
        category = "ACCEPTABLE" if spread_pct <= 1.0 else "THIN" if spread_pct <= 2.0 else "POOR"
        spread_score = {"ACCEPTABLE": 100.0, "THIN": 50.0, "POOR": 0.0}[category]
        derived.update({"spread_pct": round(spread_pct, 6), "spread_quality_state": category, "spread_quality_score": spread_score})
        provenance["spread_quality_score"] = _provenance(
            source_system="astra_unified_position_lifecycle_v1.spread_policy",
            source_timestamp=quote_stamp,
            input_fields=["bid", "ask", "price"],
            source_field="spread_pct",
        )
    else:
        missing["SCALP"].append("spread_quality_score")

    if quote.get("freshness_status") == "FRESH" and quote.get("age_seconds") is not None:
        age = float(quote["age_seconds"])
        freshness_score = round(_clamp((1.0 - (age / SCALP_QUOTE_MAX_AGE_SECONDS)) * 100.0), 3)
        derived["freshness_quality_score"] = freshness_score
        provenance["freshness_quality_score"] = _provenance(
            source_system="astra_canonical_market_timestamp_v1",
            source_timestamp=quote_stamp,
            input_fields=["provider_native_timestamp", "quote_age_seconds", "freshness_status"],
            source_field="age_seconds",
        )
    else:
        missing["SCALP"].append("freshness_quality_score")

    scalp_bars, scalp_timeframe, scalp_last = _valid_bars(
        source, now=current, allowed_timeframes=SCALP_TIMEFRAMES, minimum=SCALP_STRUCTURE_MIN_BARS
    )
    scalp_structure, _, _ = _structure(
        scalp_bars, timeframe=scalp_timeframe or "", minimum=SCALP_STRUCTURE_MIN_BARS, state_name="intraday"
    )
    if scalp_structure:
        derived["scalp_intraday_structure_v1"] = scalp_structure
        provenance["scalp_intraday_structure_v1"] = _provenance(
            source_system="astra_canonical_lane_evidence_v1.completed_bars",
            source_timestamp=scalp_last,
            input_fields=["completed_bars", "is_complete", "open", "high", "low", "close"],
            timeframe=scalp_timeframe,
            lookback=len(scalp_bars),
            source_field="completed_bars",
        )

    scalp_inputs = {
        key: _score(source.get(key))
        for key in (
            "liquidity_score", "relative_volume_score", "intraday_acceleration_score",
            "momentum_expansion_score", "spread_quality_score", "freshness_quality_score",
        )
    }
    scalp_inputs["spread_quality_score"] = _score(derived.get("spread_quality_score"),)
    scalp_inputs["freshness_quality_score"] = _score(derived.get("freshness_quality_score"),)
    scalp_missing = [key for key, value in scalp_inputs.items() if value is None]
    if scalp_structure is None:
        scalp_missing.append("scalp_intraday_structure_v1")
    if scalp_missing:
        missing["SCALP"].extend(key for key in scalp_missing if key not in missing["SCALP"])
    else:
        fit = round(mean(scalp_inputs.values()), 3)
        derived["scalp_fit_score"] = fit
        derived["scalp_horizon_evidence_v1"] = {
            "horizon": "SCALP",
            "expected_hold_window": "15m-60m",
            "same_session": True,
            "timeframe": scalp_timeframe,
            "lookback_bars": len(scalp_bars),
            "last_completed_timestamp": scalp_last,
        }
        fit_inputs = list(scalp_inputs)
        provenance["scalp_fit_score"] = _provenance(
            source_system="astra_canonical_lane_evidence_v1.scalp_fit",
            source_timestamp=scalp_last or quote_stamp,
            input_fields=fit_inputs + ["scalp_intraday_structure_v1"],
            timeframe=scalp_timeframe,
            lookback=len(scalp_bars),
        )
        provenance["scalp_horizon_evidence_v1"] = dict(provenance["scalp_fit_score"])

    swing_bars, swing_timeframe, swing_last = _valid_bars(
        source,
        now=current,
        allowed_timeframes=SWING_TIMEFRAMES,
        minimum=SWING_STRUCTURE_MIN_BARS,
        evidence_key="swing_bar_evidence",
        bars_key="swing_completed_bars",
        timeframe_key="swing_bar_timeframe",
    )
    swing_structure, persistence, trend_quality = _structure(
        swing_bars, timeframe=swing_timeframe or "", minimum=SWING_STRUCTURE_MIN_BARS, state_name="multi_day"
    )
    if swing_structure:
        derived["multi_day_structure_v1"] = swing_structure
        derived["trend_persistence_score"] = persistence
        derived["trend_quality_score"] = trend_quality
        structure_provenance = _provenance(
            source_system="astra_canonical_lane_evidence_v1.completed_bars",
            source_timestamp=swing_last,
            input_fields=["completed_bars", "is_complete", "high", "low", "close"],
            timeframe=swing_timeframe,
            lookback=len(swing_bars),
            source_field="completed_bars",
        )
        provenance.update({
            "multi_day_structure_v1": structure_provenance,
            "trend_persistence_score": dict(structure_provenance),
            "trend_quality_score": dict(structure_provenance),
        })

    volatility_score, volatility_provenance = _volatility_score(source, swing_bars, swing_last)
    if volatility_score is not None:
        derived["volatility_score"] = volatility_score
        provenance["volatility_score"] = volatility_provenance or {}
    else:
        missing["SWING"].append("volatility_score")

    swing_required = {
        "trend_persistence_score": derived.get("trend_persistence_score"),
        "trend_quality_score": derived.get("trend_quality_score"),
        "volatility_score": derived.get("volatility_score"),
        "market_regime": _field(source, "market_regime", "regime"),
        "sector": source.get("sector"),
        "multi_day_structure_v1": derived.get("multi_day_structure_v1"),
    }
    swing_missing = [key for key, value in swing_required.items() if value in (None, "", {}, [])]
    missing["SWING"].extend(key for key in swing_missing if key not in missing["SWING"])
    if not swing_missing:
        swing_fit = round(mean(float(swing_required[key]) for key in ("trend_persistence_score", "trend_quality_score", "volatility_score")), 3)
        derived["swing_fit_score"] = swing_fit
        derived["swing_horizon_evidence_v1"] = {
            "horizon": "SWING",
            "expected_hold_window": "multi-day",
            "timeframe": swing_timeframe,
            "lookback_bars": len(swing_bars),
            "last_completed_timestamp": swing_last,
            "market_regime": swing_required["market_regime"],
            "sector": swing_required["sector"],
        }
        fit_provenance = _provenance(
            source_system="astra_canonical_lane_evidence_v1.swing_fit",
            source_timestamp=swing_last,
            input_fields=list(swing_required),
            timeframe=swing_timeframe,
            lookback=len(swing_bars),
        )
        provenance["swing_fit_score"] = fit_provenance
        provenance["swing_horizon_evidence_v1"] = dict(fit_provenance)

    contract = {
        "schema_version": "astra_lane_evidence_v1",
        "producer_version": VERSION,
        "authority_class": AUTHORITY_CLASS,
        "symbol": symbol,
        "raw_evidence": raw_evidence,
        "derived_evidence": derived,
        "sufficiency": {
            "SCALP": {"state": "COMPLETE" if not missing["SCALP"] else "PARTIAL", "missing_fields": list(dict.fromkeys(missing["SCALP"]))},
            "SWING": {"state": "COMPLETE" if not missing["SWING"] else "PARTIAL", "missing_fields": list(dict.fromkeys(missing["SWING"]))},
        },
        "provenance": provenance,
        "observation_authority": False,
        "executable_evidence": False,
        "candidate_evidence_fabricated": False,
    }
    return contract
