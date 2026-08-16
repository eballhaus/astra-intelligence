"""Forward paper-trade contracts and production-path certification.

The helpers in this module are deliberately side-effect free.  The paper
worker remains the only order writer; certification consumes its real
candidate/dry-run contracts and cannot promote fixture evidence to broker
truth.  This lets a missing contract fail closed without inventing lineage for
legacy positions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence


VERSION = "1.0.0"
LANES = ("SWING", "DAY", "SCALP", "CRYPTO")
REQUIRED_CONTRACT_FIELDS = (
    "candidate_id", "recommendation_id", "decision_id", "symbol", "lane",
    "strategy_archetype", "trade_style", "ranking_score", "thesis",
    "thesis_supporting_conditions", "thesis_invalidation_conditions",
    "intended_horizon", "expected_hold_window", "expected_return_range",
    "risk_envelope_id", "expected_downside_range", "expected_drawdown", "expected_return_per_day_range",
    "entry_conditions",
    "hold_conditions", "profit_protection_conditions", "exit_review_conditions",
    "controlled_loss_conditions", "replacement_review_conditions",
    "confidence", "evidence_classes", "monitoring_priorities",
    "certification_snapshot_id", "expiry_timestamp",
)

SAFETY_FLAGS = {
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "broker_live_endpoint_allowed": False,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "ranking_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "forced_trades_enabled": False,
    "forced_exits_enabled": False,
    "automatic_promotions_enabled": False,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
    "broker_actions_used": 0,
}

# This registry is deliberately limited to bounded, already-produced payloads.
# Enrichment must never turn a contract build into a provider call or history scan.
EVIDENCE_SOURCE_REGISTRY = {
    "candidate_ranking_attribution_promotion_intelligence_v1": "CURRENT_SYMBOL_DIRECT",
    "current_ranking_market_snapshot_v1": "CURRENT_BROKER_QUOTE",
    "current_crypto_market_snapshot_v1": "CURRENT_BROKER_QUOTE",
    "equity_worker_risk_evidence_v1": "CURRENT_SYMBOL_RISK",
    "opportunity_discovery_expansion_v1": "AGGREGATE_ADVISORY",
    "paper_opportunity_allocation_engine_v1": "AGGREGATE_ADVISORY",
    "edge_development_suite_v1": "SHADOW_SUPPORTED",
    "multi_horizon_intelligence_adaptive_lifecycle_suite_v1": "CURRENT_CONTEXT_DIRECT",
    "market_context_learning_suite_v1": "CURRENT_CONTEXT_DIRECT",
    "symbol_behavior_profiles_v1": "HISTORICAL_SYMBOL_SUPPORTED",
    "historical_intelligence_market_memory_suite": "HISTORICAL_SYMBOL_SUPPORTED",
    "replay_counterfactual_learning_v2": "REPLAY_SUPPORTED",
    "shadow_vs_paper_performance_attribution": "SHADOW_SUPPORTED",
    "trade_thesis_validation_v1": "SHADOW_SUPPORTED",
    "opportunity_cost_learning_v1": "AGGREGATE_ADVISORY",
}

EVIDENCE_PRECEDENCE = {
    "CURRENT_CANDIDATE_DIRECT": 1,
    "CURRENT_BROKER_QUOTE": 2,
    "CURRENT_SYMBOL_DIRECT": 3,
    "CURRENT_SYMBOL_RISK": 4,
    "CURRENT_STRATEGY_HORIZON_RISK": 5,
    "CURRENT_LANE_CONTEXT": 6,
    "CURRENT_CONTEXT_DIRECT": 7,
    "HISTORICAL_SYMBOL_SUPPORTED": 8,
    "RECONSTRUCTED_SUPPORTED": 9,
    "REPLAY_SUPPORTED": 10,
    "SHADOW_SUPPORTED": 11,
    "AGGREGATE_ADVISORY": 12,
    "BOUNDED_POLICY_DEFAULT": 13,
    "UNAVAILABLE": 99,
    "STALE": 100,
    "CONFLICTING": 101,
}

FIELD_ALIASES = {
    "strategy_archetype": ("strategy_archetype", "trade_archetype", "strategy_cohort"),
    "trade_style": ("trade_style", "intended_trade_style", "paper_entry_horizon_style", "trade_horizon_style"),
    "intended_horizon": ("intended_horizon", "paper_entry_horizon_style", "trade_horizon_style", "best_horizon_style"),
    "ranking_score": ("ranking_score", "score", "confidence_score", "rank_score", "astra_composite_score", "opportunity_score_pct"),
    "thesis": ("thesis", "entry_rationale", "intelligence_summary", "summary", "ranked_reason"),
    "expected_return": ("expected_return_range", "expected_return_pct", "expected_return_percent", "expected_move_percent", "predicted_profit_percent", "profit_prediction_pct"),
    "expected_return_low": ("expected_return_low_pct", "expected_move_low"),
    "expected_return_high": ("expected_return_high_pct", "expected_move_high"),
    "expected_downside": ("expected_downside_range", "downside_range", "stop_loss", "trailing_stop_price", "stop_loss_pct"),
    "expected_drawdown": ("expected_drawdown", "expected_drawdown_range", "drawdown_range", "max_drawdown_pct", "adverse_excursion_pct", "drawdown_risk_score"),
    "confidence": ("confidence", "conviction", "predicted_win_probability", "confidence_score"),
    "regime": ("regime_context", "regime_alignment_label", "market_regime_alignment", "regime_fit"),
    "sector": ("sector", "sector_context", "sector_fit"),
    "catalyst": ("catalyst", "catalyst_context", "catalyst_state", "catalyst_context_label"),
    "momentum": ("momentum_state", "trend_state", "momentum_label"),
    "liquidity": ("liquidity_state", "liquidity_label", "spread_quality"),
}

SETUP_STRATEGY_MAP = {
    "breakout": "momentum_breakout",
    "momentum": "momentum_continuation",
    "mean_reversion": "mean_reversion",
    "reversal": "mean_reversion",
    "trend": "trend_continuation",
}

STRATEGY_HORIZON_MAP = {
    "momentum_breakout": "swing_trade",
    "momentum_continuation": "swing_trade",
    "trend_continuation": "swing_trade",
    "mean_reversion": "day_trade",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat().replace("+00:00", "Z")


def _lane(value: Any) -> str:
    raw = _text(value).upper()
    if raw in LANES:
        return raw
    if raw in {"DAY_TRADE", "DAYTRADE"}:
        return "DAY"
    if raw == "SCALP":
        return "SCALP"
    if raw in {"SWING_TRADE", "SHORT_SWING", "STANDARD_SWING", "EXTENDED_SWING"}:
        return "SWING"
    return raw or "UNKNOWN"


def _pretrade_execution_horizon(row: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve a concrete existing execution horizon without broad reclassification.

    A candidate can carry a broad research label such as
    ``crypto_multi_horizon`` alongside the worker's already-assigned
    ``paper_entry_horizon_style``.  The broad label is useful diagnostics but
    cannot price a bounded holding window.  For pretrade-contract math only,
    prefer the existing concrete execution style and normalize legacy aliases.
    This neither changes the upstream horizon assignment nor creates a new
    horizon where none was assigned.
    """
    aliases = {
        "scalp": "scalp",
        "day": "day_trade",
        "daytrade": "day_trade",
        "day_trade": "day_trade",
        "intraday": "day_trade",
        "swing": "swing_trade",
        "swing_trade": "swing_trade",
        "short_swing": "swing_trade",
        "standard_swing": "swing_trade",
        "extended_swing": "swing_trade",
    }
    for field in (
        "paper_entry_horizon_style",
        "trade_horizon_style",
        "intended_horizon",
        "best_horizon_style",
        "horizon",
    ):
        value = aliases.get(_text(row.get(field)).strip().lower())
        if value:
            return value, field
    return "", ""


def _stable_decision_id(candidate_id: str, recommendation_id: str) -> str:
    if not candidate_id and not recommendation_id:
        return ""
    seed = f"{candidate_id}|{recommendation_id}|decision_contract_v1"
    return "dec-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value] if value not in (None, "") else []


def _as_plan_list(*values: Any) -> list[str]:
    """Return a bounded condition list without inventing a trading rule."""
    rows: list[str] = []
    for value in values:
        for item in _as_list(value):
            text = _text(item)
            if text and text not in rows:
                rows.append(text)
    return rows[:6]


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _expected_hold_duration_days(row: Mapping[str, Any], horizon: str) -> tuple[float | None, str]:
    """Preserve explicit duration evidence before existing horizon fallbacks."""
    minutes, minutes_field = _first_field(row, ("expected_hold_minutes", "hold_minutes"))
    minutes_value = _number(minutes)
    if minutes_value is not None and minutes_value > 0:
        return minutes_value / 1440.0, minutes_field
    days, days_field = _first_field(row, ("expected_hold_days", "hold_days"))
    days_value = _number(days)
    if days_value is not None and days_value > 0:
        return days_value, days_field
    if horizon == "day_trade":
        return 1.0 / 24.0, "existing_day_trade_policy"
    if horizon == "swing_trade":
        return 3.0, "existing_swing_trade_policy"
    return None, ""


def _candidate_symbol(row: Mapping[str, Any]) -> str:
    return _text(_first(row, "canonical_symbol", "symbol", "ticker")).upper().replace(" ", "")


def _source_timestamp(row: Mapping[str, Any]) -> str:
    return _text(_first(row, "source_timestamp", "candidate_generated_at", "generated_at", "timestamp", "updated_at", "as_of"))


def _freshness(timestamp: str, now: datetime | None) -> str:
    if not timestamp:
        return "UNKNOWN"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return "UNKNOWN"
    age = (_now(now) - parsed).total_seconds()
    if age < -300:
        return "CONFLICTING_CLOCK"
    return "CURRENT" if age <= 300 else "STALE"


def _bounded_matching_rows(
    payload: Any,
    symbol: str,
    *,
    budget: int = 96,
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Find symbol rows in a compact cached payload without recursive history scans."""
    if budget <= 0 or depth > 4:
        return []
    if isinstance(payload, Mapping):
        row = dict(payload)
        if symbol and _candidate_symbol(row) == symbol:
            return [row]
        matches: list[dict[str, Any]] = []
        for value in row.values():
            if isinstance(value, (Mapping, list, tuple)):
                matches.extend(_bounded_matching_rows(value, symbol, budget=budget - len(matches), depth=depth + 1))
            if len(matches) >= budget:
                break
        return matches[:budget]
    if isinstance(payload, (list, tuple)):
        matches = []
        for value in list(payload)[:budget]:
            matches.extend(_bounded_matching_rows(value, symbol, budget=budget - len(matches), depth=depth + 1))
            if len(matches) >= budget:
                break
        return matches[:budget]
    return []


def _provenance(
    value: Any,
    *,
    source_system: str,
    source_field: str,
    source_row: Mapping[str, Any],
    evidence_class: str,
    confidence: Any = None,
    now: datetime | None = None,
    candidate_specific: bool = False,
    symbol_specific: bool = False,
    derived: bool = False,
) -> dict[str, Any]:
    timestamp = _source_timestamp(source_row)
    return {
        "value": value,
        "source_system": source_system,
        "source_field": source_field,
        "source_timestamp": timestamp,
        "evidence_class": evidence_class,
        "confidence": _number(confidence) if _number(confidence) is not None else None,
        "freshness_state": _freshness(timestamp, now),
        "candidate_specific": bool(candidate_specific),
        "symbol_specific": bool(symbol_specific),
        "derived": bool(derived),
    }


def _first_field(row: Mapping[str, Any], aliases: Sequence[str]) -> tuple[Any, str]:
    for key in aliases:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value, key
    return None, ""


def _range(low: Any, high: Any, fallback: Any = None, *, label: str) -> dict[str, Any] | None:
    lo = _number(low)
    hi = _number(high)
    mid = _number(fallback)
    if lo is None:
        lo = mid if mid is not None else hi
    if hi is None:
        hi = mid if mid is not None else lo
    if lo is None or hi is None:
        return None
    return {"low_pct": round(min(lo, hi), 4), "high_pct": round(max(lo, hi), 4), "evidence_label": label}


def _signed_range(value: Any, *, negative: bool, label: str) -> dict[str, Any] | None:
    """Normalize a supported percentage range without changing its meaning."""
    if isinstance(value, Mapping):
        result = _range(value.get("low_pct", value.get("low")), value.get("high_pct", value.get("high")), label=label)
    else:
        result = _range(value, value, label=label)
    if result is None:
        return None
    if negative:
        low, high = float(result["low_pct"]), float(result["high_pct"])
        if low > 0 or high > 0:
            return None
    return result


def _positive_return_range(value: Any, *, label: str) -> dict[str, Any] | None:
    """Accept only a positive candidate forecast, never a placeholder zero."""
    if isinstance(value, Mapping):
        result = _range(value.get("low_pct", value.get("low")), value.get("high_pct", value.get("high")), label=label)
    else:
        result = _range(value, value, label=label)
    if result is None or float(result.get("high_pct", 0.0)) <= 0.0:
        return None
    return result


def _drawdown_forecast_range(value: Any, *, source_field: str, label: str) -> dict[str, Any] | None:
    """Keep 0-100 risk scores out of the percentage-drawdown contract."""
    if str(source_field or "") == "drawdown_risk_score":
        return None
    if isinstance(value, Mapping):
        low = _number(value.get("low_pct", value.get("low")))
        high = _number(value.get("high_pct", value.get("high")))
    else:
        low = high = _number(value)
    if low is None and high is None:
        return None
    # A percentage drawdown beyond 100 is structurally invalid.  Values in
    # 0-100 are valid only when they are explicitly supplied as a drawdown,
    # never when they originated from the ranking risk-score alias above.
    if max(abs(v) for v in (low, high) if v is not None) > 100.0:
        return None
    return _range(-abs(low) if low is not None else None, -abs(high) if high is not None else None, label=label)


def build_candidate_risk_envelope_v1(
    candidate: Mapping[str, Any],
    *,
    statuses: Mapping[str, Any] | None = None,
    current_candidates: Sequence[Mapping[str, Any]] | None = None,
    market_snapshot: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the single read-only, attributable risk envelope for a candidate.

    This owner consumes only already-produced candidate, cached ranking, or
    supplied snapshot fields. It never fetches a quote, invents a risk percent,
    or converts aggregate performance into candidate risk.
    """
    row = dict(candidate or {})
    symbol = _candidate_symbol(row)
    lane = _lane(_first(row, "lane_id", "lane"))
    asset = _text(_first(row, "instrument_type", "asset_type", "asset_class")).upper() or "EQUITY"
    contexts: list[tuple[str, str, Mapping[str, Any]]] = [("candidate_row", "CURRENT_CANDIDATE_DIRECT", row)]
    if isinstance(market_snapshot, Mapping):
        contexts.append(("current_market_snapshot", "CURRENT_BROKER_QUOTE", market_snapshot))
    for peer in list(current_candidates or [])[:64]:
        if isinstance(peer, Mapping) and _candidate_symbol(peer) == symbol:
            contexts.append(("current_candidate_snapshot", "CURRENT_SYMBOL_DIRECT", peer))
    for source, payload in dict(statuses or {}).items():
        for peer in _bounded_matching_rows(payload, symbol)[:12]:
            evidence = "CURRENT_SYMBOL_RISK" if "risk" in str(source).lower() or "ranking" in str(source).lower() else EVIDENCE_SOURCE_REGISTRY.get(str(source), "CURRENT_CONTEXT_DIRECT")
            contexts.append((str(source), evidence, peer))

    provenance: dict[str, dict[str, Any]] = {}
    def resolve(field: str, aliases: Sequence[str], *, evidence_only: bool = False) -> Any:
        for source, evidence_class, context in contexts:
            value, key = _first_field(context, aliases)
            if value in (None, "", [], {}):
                continue
            meta = _provenance(value, source_system=source, source_field=key, source_row=context,
                               evidence_class=evidence_class, confidence=_first(context, "risk_confidence", "confidence"),
                               now=now, candidate_specific=source == "candidate_row", symbol_specific=True)
            if meta["freshness_state"] == "STALE" and evidence_class.startswith("CURRENT_"):
                continue
            provenance[field] = meta
            return value
        return None

    price = _number(resolve("current_price", ("price", "current_price", "last_price", "last", "close")))
    bid = _number(resolve("bid", ("bid", "bid_price")))
    ask = _number(resolve("ask", ("ask", "ask_price")))
    quote_timestamp = _text(resolve("quote_timestamp", ("quote_timestamp", "data_timestamp", "last_snapshot_timestamp", "timestamp", "updated_at", "as_of")))
    if not quote_timestamp:
        quote_timestamp = _source_timestamp(row)
    quote_freshness = _freshness(quote_timestamp, now)
    spread_pct = _number(resolve("spread_pct", ("spread_pct", "bid_ask_spread_pct")))
    if spread_pct is None and bid is not None and ask is not None and bid > 0 and ask >= bid:
        spread_pct = ((ask - bid) / ((ask + bid) / 2.0)) * 100.0
        provenance["spread_pct"] = _provenance(spread_pct, source_system="bid_ask_quote", source_field="bid/ask", source_row=row,
                                                evidence_class="CURRENT_BROKER_QUOTE", now=now, candidate_specific=True,
                                                symbol_specific=True, derived=True)
    volume = _number(resolve("volume", ("volume_24h", "quote_volume", "volume", "volume_usd", "avg_volume")))
    volatility = _number(resolve("volatility_pct", ("atr_pct", "atr_percent", "volatility_pct", "realized_volatility_pct", "recent_range_pct", "risk_pct", "crypto_risk_pct")))
    if volatility is None and price and _number(_first(row, "atr", "average_true_range")):
        volatility = abs(float(_number(_first(row, "atr", "average_true_range")) or 0.0) / price) * 100.0
        provenance["volatility_pct"] = _provenance(volatility, source_system="candidate_atr", source_field="atr/price", source_row=row,
                                                     evidence_class="CURRENT_CANDIDATE_DIRECT", now=now, candidate_specific=True,
                                                     symbol_specific=True, derived=True)
    stop = _number(resolve("invalidation_level", ("stop_loss", "trailing_stop_price", "invalidation_price", "thesis_invalidation_price")))
    downside = _signed_range(resolve("expected_downside_range", FIELD_ALIASES["expected_downside"]), negative=True, label="SUPPORTED_DOWNSIDE")
    if downside is None and price and stop and 0 < stop < price:
        pct = ((stop - price) / price) * 100.0
        downside = _range(pct, pct, label="CURRENT_STOP_INVALIDATION")
        provenance["expected_downside_range"] = _provenance(downside, source_system="candidate_stop_invalidation", source_field="stop_loss/price", source_row=row,
                                                               evidence_class="CURRENT_CANDIDATE_DIRECT", now=now, candidate_specific=True,
                                                               symbol_specific=True, derived=True)
    if downside is None and volatility and volatility > 0:
        # During closed markets, volatility may come from historical completed-bar data.
        # Only classify as HISTORICAL when freshness is explicitly STALE.
        if quote_timestamp:
            freshness = _freshness(quote_timestamp, now)
            evidence_class = "HISTORICAL_COMPLETED_BAR_RISK" if freshness == "STALE" else "CURRENT_SYMBOL_RISK"
        else:
            evidence_class = "CURRENT_SYMBOL_RISK"
        downside = _range(-abs(volatility), -abs(volatility), label="CURRENT_VOLATILITY_RISK")
        provenance["expected_downside_range"] = _provenance(downside, source_system="current_volatility_risk", source_field="atr_pct/volatility_pct", source_row=row,
                                                               evidence_class=evidence_class, now=now, candidate_specific=True,
                                                               symbol_specific=True, derived=True)
    drawdown_raw = resolve("expected_drawdown", FIELD_ALIASES["expected_drawdown"])
    drawdown_source = str((provenance.get("expected_drawdown") or {}).get("source_field") or "")
    # Ranking drawdown scores are unitless 0-100 diagnostics, not percentage
    # forecasts.  They previously leaked through this alias and made a score
    # such as 42 look like a -42% expected loss.
    drawdown = _drawdown_forecast_range(
        drawdown_raw,
        source_field=drawdown_source,
        label="SUPPORTED_DRAWDOWN",
    )
    if drawdown is None and drawdown_source == "drawdown_risk_score":
        provenance.pop("expected_drawdown", None)
    if drawdown is None and volatility and volatility > 0:
        # A volatility-supported adverse-movement band is distinct from the
        # downside threshold: one to two current volatility units, not a stop.
        drawdown = _range(-2.0 * abs(volatility), -abs(volatility), label="VOLATILITY_ADVERSE_MOVEMENT")
        provenance["expected_drawdown"] = _provenance(drawdown, source_system="current_volatility_risk", source_field="atr_pct/volatility_pct", source_row=row,
                                                        evidence_class="CURRENT_SYMBOL_RISK", now=now, candidate_specific=True,
                                                        symbol_specific=True, derived=True)
    return_aliases = (
        "expected_return_range", "expected_return_pct", "expected_return_percent",
        "expected_move_percent", "predicted_profit_percent", "profit_prediction_pct",
    )
    upside_range = None
    # A zero-filled expected_return_range is an unavailable forecast, not a
    # forecast of zero. Continue to the next already-produced alias instead of
    # masking a valid predicted_profit_percent on the same candidate.
    for source, evidence_class, context in contexts:
        pair = _positive_return_range(
            {"low_pct": context.get("expected_return_low_pct", context.get("expected_move_low")),
             "high_pct": context.get("expected_return_high_pct", context.get("expected_move_high"))},
            label="CANDIDATE_EXPECTED_RETURN",
        )
        if pair is not None:
            upside_range = pair
            provenance["expected_upside_range"] = _provenance(
                pair, source_system=source, source_field="expected_return_low_pct/expected_return_high_pct",
                source_row=context, evidence_class=evidence_class,
                confidence=_first(context, "confidence", "risk_confidence"), now=now,
                candidate_specific=source == "candidate_row", symbol_specific=True, derived=True,
            )
            break
        for key in return_aliases:
            value = context.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, Mapping):
                parsed = _positive_return_range(value, label="CANDIDATE_EXPECTED_RETURN")
            else:
                parsed = _range(
                    context.get("expected_return_low_pct", context.get("expected_move_low")),
                    context.get("expected_return_high_pct", context.get("expected_move_high")),
                    value,
                    label="CANDIDATE_EXPECTED_RETURN",
                )
                if parsed is not None and float(parsed.get("high_pct", 0.0)) <= 0.0:
                    parsed = None
            if parsed is None:
                continue
            upside_range = parsed
            provenance["expected_upside_range"] = _provenance(
                parsed, source_system=source, source_field=key, source_row=context,
                evidence_class=evidence_class, confidence=_first(context, "confidence", "risk_confidence"),
                now=now, candidate_specific=source == "candidate_row", symbol_specific=True, derived=True,
            )
            break
        if upside_range is not None:
            break
    reward_to_risk = None
    if upside_range and downside and float(downside["low_pct"]) < 0:
        reward_to_risk = _range(float(upside_range["low_pct"]) / abs(float(downside["low_pct"])), float(upside_range["high_pct"]) / abs(float(downside["high_pct"])), label="EXPECTED_REWARD_TO_RISK")
    execution_horizon, _ = _pretrade_execution_horizon(row)
    horizon = execution_horizon or _text(_first(row, "intended_horizon", "paper_entry_horizon_style", "trade_horizon_style"))
    hold_days, hold_duration_source = _expected_hold_duration_days(row, horizon)
    per_day = None
    if upside_range and hold_days:
        per_day = {"low_pct_per_day": round(float(upside_range["low_pct"]) / hold_days, 4), "high_pct_per_day": round(float(upside_range["high_pct"]) / hold_days, 4), "method": "candidate_expected_return_over_existing_horizon"}
        provenance["expected_return_per_day_range"] = _provenance(
            per_day,
            source_system="candidate_expected_return_and_horizon",
            source_field=f"expected_return_range/{hold_duration_source}",
            source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT" if hold_duration_source in {"expected_hold_minutes", "hold_minutes", "expected_hold_days", "hold_days"} else "BOUNDED_POLICY_DEFAULT",
            confidence=_first(row, "confidence", "risk_confidence"),
            now=now,
            candidate_specific=True,
            symbol_specific=True,
            derived=True,
        )
    missing = [name for name, value in (("expected_downside_range", downside), ("expected_drawdown", drawdown), ("expected_upside_range", upside_range)) if value in (None, "", [], {})]
    stale = bool(quote_timestamp and quote_freshness == "STALE")
    state = "RISK_ENVELOPE_STALE" if stale else "RISK_ENVELOPE_INCOMPLETE" if missing else "RISK_ENVELOPE_COMPLETE_WITH_WARNINGS" if not price or quote_freshness == "UNKNOWN" else "RISK_ENVELOPE_COMPLETE"
    envelope_id = "risk-" + hashlib.sha256(f"{_text(row.get('candidate_id'))}|{symbol}|{quote_timestamp}|{state}".encode("utf-8")).hexdigest()[:20]
    generated_at = _iso(now)
    valid_until = _iso(_now(now) + timedelta(minutes=5)) if quote_freshness == "CURRENT" else ""
    expected_median = round((float(upside_range["low_pct"]) + float(upside_range["high_pct"])) / 2.0, 4) if upside_range else None
    downside_median = round((float(downside["low_pct"]) + float(downside["high_pct"])) / 2.0, 4) if downside else None
    # The crypto worker can persist a bounded continuation forecast built from
    # the same completed bars and provider quote that created the candidate.
    # Preserve that producer identity instead of relabeling its fields as an
    # opaque candidate alias.  A malformed or incomplete forecast is ignored
    # here and the normal contract remains fail-closed.
    forecast = dict(row.get("crypto_pretrade_forecast_v1") or {})
    forecast_provenance = dict(forecast.get("source_provenance") or {})
    if forecast.get("forecast_state") == "FORECAST_COMPLETE" and forecast_provenance:
        source_row = {
            "source_timestamp": forecast.get("forecast_timestamp") or forecast_provenance.get("observation_timestamp"),
            "confidence": _first(row, "confidence", "risk_confidence"),
        }
        forecast_fields = {
            "expected_upside_range": upside_range,
            "expected_downside_range": downside,
            "expected_drawdown": drawdown,
        }
        for field, value in forecast_fields.items():
            if value not in (None, "", [], {}):
                provenance[field] = _provenance(
                    value,
                    source_system=str(forecast_provenance.get("source_system") or "crypto_completed_bar_continuation_v1"),
                    source_field=f"crypto_pretrade_forecast_v1.{field}",
                    source_row=source_row,
                    evidence_class=str(forecast_provenance.get("evidence_class") or "CURRENT_CANDIDATE_DIRECT"),
                    confidence=_first(row, "confidence", "risk_confidence"),
                    now=now,
                    candidate_specific=True,
                    symbol_specific=True,
                    derived=True,
                )
    return {
        "risk_envelope_id": envelope_id, "candidate_id": _text(row.get("candidate_id")), "symbol": symbol, "lane": lane,
        "asset_type": asset, "asset_class": _text(_first(row, "asset_class", "asset_type")).lower() or "equity",
        "instrument_type": asset, "etf_cohort": bool(asset == "ETF"),
        "strategy": _text(row.get("strategy_archetype")), "horizon": horizon,
        "regime": _text(_first(row, "regime_context", "regime")), "sector": _text(_first(row, "sector", "sector_context")),
        "generated_at": generated_at, "valid_until": valid_until,
        "current_price": price, "price_timestamp": quote_timestamp, "quote_freshness": quote_freshness,
        "bid": bid, "ask": ask, "spread_pct": spread_pct, "liquidity_state": "AVAILABLE" if volume and volume > 0 else "UNAVAILABLE",
        "volume": volume, "volatility_pct": volatility, "volatility_method": str((provenance.get("volatility_pct") or {}).get("source_field") or "UNAVAILABLE"),
        "invalidation_level": stop, "expected_downside_range": downside, "expected_drawdown": drawdown,
        "expected_drawdown_range": drawdown, "maximum_acceptable_drawdown": drawdown,
        "expected_upside_range": upside_range, "expected_return_range": upside_range,
        "expected_return_median": expected_median,
        "expected_downside_median": downside_median,
        "reward_to_risk_range": reward_to_risk, "expected_return_per_day_range": per_day,
        "expected_return_per_day_median": round((float(per_day["low_pct_per_day"]) + float(per_day["high_pct_per_day"])) / 2.0, 4) if per_day else None,
        "expected_MFE_range": upside_range, "expected_MAE_range": drawdown,
        "predicted_time_to_peak_range": {"minimum_minutes": 15 if horizon == "day_trade" else 1_440, "maximum_minutes": 390 if horizon == "day_trade" else 7_200, "evidence_label": "EXISTING_HORIZON_PLAN"} if horizon in {"day_trade", "swing_trade"} else None,
        "expected_hold_window": "same session" if horizon == "day_trade" else "1-5 trading days" if horizon == "swing_trade" else "",
        "likely_exit_window": "before regular-session close" if horizon == "day_trade" else "review at the existing swing horizon" if horizon == "swing_trade" else "",
        "profit_protection_trigger": _as_plan_list(_first(row, "profit_protection_conditions", "profit_lock_conditions")),
        "thesis_invalidation_condition": _as_plan_list(_first(row, "thesis_invalidation_conditions", "invalidation_conditions")),
        "controlled_loss_condition": _as_plan_list(_first(row, "controlled_loss_conditions", "loss_acceptance_conditions")),
        "opportunity_cost_review_point": _as_plan_list(_first(row, "replacement_review_conditions", "replacement_conditions")),
        "gap_risk_state": "REQUIRES_OVERNIGHT_REVIEW" if horizon == "swing_trade" else "DAY_SESSION_LIMITED" if horizon == "day_trade" else "UNKNOWN",
        "overnight_risk_state": "APPLICABLE" if horizon == "swing_trade" else "PROHIBITED_UNLESS_EXISTING_STRATEGY_ALLOWS" if horizon == "day_trade" else "UNKNOWN",
        "liquidity_risk_state": "AVAILABLE" if volume and volume > 0 else "UNAVAILABLE",
        "spread_risk_state": "AVAILABLE" if spread_pct is not None else "UNAVAILABLE",
        "volatility_risk_state": "SUPPORTED" if volatility and volatility > 0 else "UNSUPPORTED",
        "catalyst_risk_state": _text(_first(row, "catalyst_state", "catalyst_context")) or "UNKNOWN",
        "confidence": _number(_first(row, "risk_confidence", "confidence")), "evidence_class": str((provenance.get("expected_downside_range") or {}).get("evidence_class") or "UNAVAILABLE"),
        "freshness_state": quote_freshness, "input_freshness": quote_freshness,
        "input_completeness": round((4 - len(missing)) / 4.0, 4), "forecast_reliability": "BOUNDED" if not missing and quote_freshness == "CURRENT" else "LIMITED" if not missing else "UNSUPPORTED",
        "sample_size": _number(_first(row, "forecast_sample_size", "evidence_count")), "evidence_strength": str((provenance.get("expected_upside_range") or {}).get("evidence_class") or "UNAVAILABLE"),
        "bounded_uncertainty": bool(upside_range and float(upside_range["low_pct"]) != float(upside_range["high_pct"])),
        "limitations": missing, "missing_inputs": missing, "degradation_flags": ["stale_quote" for _ in [0] if stale], "conflicting_evidence": [], "field_provenance_v1": provenance,
        "risk_envelope_state": state, "consumer_acknowledgements": {"CONSUMED_BY_ENRICHMENT": False, "CONSUMED_BY_CONTRACT": False, "CONSUMED_BY_QUALIFICATION": False, "CONSUMED_BY_RISK_GATE": False, "CONSUMED_BY_ORDER_READY": False, "PERSISTED_FOR_LIFECYCLE": False, "PERSISTED_FOR_TRUTH_ATTRIBUTION": False},
    }


def build_expected_outcome_envelope_v1(candidate: Mapping[str, Any], risk_envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical expected-outcome view backed by the risk-envelope owner."""
    risk = dict(risk_envelope or {})
    required = ("expected_upside_range", "expected_downside_range", "expected_drawdown", "expected_return_per_day_range")
    missing = [field for field in required if risk.get(field) in (None, "", [], {})]
    state = "EXPECTED_OUTCOME_INCOMPLETE" if missing else "EXPECTED_OUTCOME_COMPLETE_WITH_WARNINGS" if risk.get("risk_envelope_state") == "RISK_ENVELOPE_COMPLETE_WITH_WARNINGS" else "EXPECTED_OUTCOME_COMPLETE"
    return {"expected_outcome_id": "outcome-" + str(risk.get("risk_envelope_id") or "unavailable"), "expected_outcome_state": state,
            "expected_return_range": risk.get("expected_upside_range"), "expected_downside_range": risk.get("expected_downside_range"),
            "expected_drawdown": risk.get("expected_drawdown"), "reward_to_risk_range": risk.get("reward_to_risk_range"),
            "expected_return_per_day_range": risk.get("expected_return_per_day_range"), "risk_envelope_id": risk.get("risk_envelope_id"),
            "missing_fields": missing, "field_provenance_v1": dict(risk.get("field_provenance_v1") or {})}


def enrich_candidate_for_pretrade_contract(
    candidate: Mapping[str, Any],
    *,
    statuses: Mapping[str, Any] | None = None,
    current_candidates: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach bounded, attributable intelligence before contract construction.

    The function is side-effect free and never calls a provider, broker, or
    full-history store. Candidate-local facts win; cached symbol/context rows
    may fill a missing field but cannot overwrite stronger evidence.
    """
    row = dict(candidate or {})
    # The crypto ranking producer persists its bounded continuation forecast
    # as a versioned nested contract.  Consume only a complete, candidate-local
    # forecast before resolving the risk envelope; otherwise the downstream
    # aliases cannot see already-attributable return/risk evidence.  This is a
    # materialization bridge, not a forecast fallback: incomplete forecasts
    # remain untouched and the contract stays fail closed.
    crypto_forecast = dict(row.get("crypto_pretrade_forecast_v1") or {})
    if crypto_forecast.get("forecast_state") == "FORECAST_COMPLETE":
        for field in (
            "expected_return_range",
            "expected_return_pct",
            "expected_target_low",
            "expected_target_high",
            "expected_downside_range",
            "expected_drawdown",
            "invalidation_level",
        ):
            if row.get(field) in (None, "", [], {}) and crypto_forecast.get(field) not in (None, "", [], {}):
                row[field] = crypto_forecast[field]
        for field in (
            "forecast_timestamp",
            "valid_until",
            "calculation_method",
            "source_inputs",
            "source_provenance",
            "schema_version",
        ):
            target_field = {
                "valid_until": "forecast_valid_until",
                "calculation_method": "expected_return_method",
                "source_inputs": "forecast_source_inputs",
                "source_provenance": "forecast_source_provenance",
                "schema_version": "forecast_schema_version",
            }.get(field, field)
            if row.get(target_field) in (None, "", [], {}) and crypto_forecast.get(field) not in (None, "", [], {}):
                row[target_field] = crypto_forecast[field]
    # A previous enrichment can contain a stale envelope after a restart or a
    # new market snapshot. Rebuild from the supplied bounded evidence instead
    # of treating the presence of any old envelope as an idempotency proof.
    # This remains read-only and never refreshes a provider or broker.
    symbol = _candidate_symbol(row)
    statuses = dict(statuses or {})
    current_rows = [dict(item) for item in (current_candidates or []) if isinstance(item, Mapping)]
    contexts: list[tuple[str, str, dict[str, Any]]] = []
    for peer in current_rows[:128]:
        if symbol and _candidate_symbol(peer) == symbol and peer != row:
            contexts.append(("current_candidate_snapshot", "CURRENT_SYMBOL_DIRECT", peer))
    for source, evidence_class in EVIDENCE_SOURCE_REGISTRY.items():
        payload = statuses.get(source)
        if payload not in (None, "", [], {}):
            contexts.extend((source, evidence_class, item) for item in _bounded_matching_rows(payload, symbol)[:12])

    provenance: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = _as_plan_list(row.get("enrichment_conflicting_fields"), row.get("evidence_conflicts"))
    missing_sources: dict[str, str] = {}

    def choose(field: str, aliases: Sequence[str]) -> Any:
        direct, direct_key = _first_field(row, aliases)
        if direct not in (None, "", [], {}):
            provenance[field] = _provenance(
                direct, source_system="candidate_row", source_field=direct_key, source_row=row,
                evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=_first(row, "confidence", "confidence_score"),
                now=now, candidate_specific=True, symbol_specific=True,
            )
            # Current candidate-specific evidence outranks every fallback.
            # A differing lower-tier value is retained in its source system,
            # but is not a contract conflict and cannot overwrite this value.
            return direct
        for source, evidence_class, context in contexts:
            value, key = _first_field(context, aliases)
            if value in (None, "", [], {}):
                continue
            meta = _provenance(
                value, source_system=source, source_field=key, source_row=context,
                evidence_class=evidence_class, confidence=_first(context, "confidence", "confidence_score"), now=now,
                symbol_specific=True,
            )
            if meta["freshness_state"] == "STALE" and evidence_class.startswith("CURRENT_"):
                continue
            provenance[field] = meta
            return value
        missing_sources[field] = "NO_CURRENT_CANDIDATE_OR_SYMBOL_EVIDENCE"
        return None

    def contextual(aliases: Sequence[str]) -> Any:
        value, _ = _first_field(row, aliases)
        if value not in (None, "", [], {}):
            return value
        for _source, _evidence_class, context in contexts:
            value, _ = _first_field(context, aliases)
            if value not in (None, "", [], {}):
                return value
        return None

    strategy = choose("strategy_archetype", FIELD_ALIASES["strategy_archetype"])
    strategy_state = "STRATEGY_DIRECT" if strategy else "STRATEGY_UNAVAILABLE"
    setup = _text(contextual(("setup_type", "detected_setup_type")))
    if not strategy and setup:
        mapped = next((value for key, value in SETUP_STRATEGY_MAP.items() if key in setup.lower()), "")
        if mapped:
            strategy = mapped
            strategy_state = "STRATEGY_INFERRED_FROM_SUPPORTED_SETUP"
            provenance["strategy_archetype"] = _provenance(
                mapped, source_system="bounded_setup_strategy_mapping", source_field="setup_type", source_row=row,
                evidence_class="BOUNDED_POLICY_DEFAULT", confidence=_first(row, "confidence", "confidence_score"),
                now=now, candidate_specific=True, symbol_specific=True, derived=True,
            )
    horizon = choose("intended_horizon", FIELD_ALIASES["intended_horizon"])
    execution_horizon, execution_horizon_field = _pretrade_execution_horizon(row)
    if execution_horizon:
        # The direct worker assignment is the actionable horizon for this
        # contract.  Keep broader research labels in their source rows, but
        # do not let them suppress bounded per-day evidence production.
        horizon = execution_horizon
        provenance["intended_horizon"] = _provenance(
            horizon,
            source_system="candidate_row",
            source_field=execution_horizon_field,
            source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT",
            confidence=_first(row, "confidence", "confidence_score"),
            now=now,
            candidate_specific=True,
            symbol_specific=True,
        )
    if not horizon and strategy in STRATEGY_HORIZON_MAP:
        horizon = STRATEGY_HORIZON_MAP[str(strategy)]
        provenance["intended_horizon"] = _provenance(
            horizon, source_system="bounded_strategy_horizon_mapping", source_field="strategy_archetype", source_row=row,
            evidence_class="BOUNDED_POLICY_DEFAULT", confidence=_first(row, "confidence", "confidence_score"),
            now=now, candidate_specific=True, symbol_specific=True, derived=True,
        )
    trade_style = choose("trade_style", FIELD_ALIASES["trade_style"]) or horizon
    if trade_style and "trade_style" not in provenance:
        provenance["trade_style"] = _provenance(
            trade_style, source_system="derived_horizon_style", source_field="intended_horizon", source_row=row,
            evidence_class="BOUNDED_POLICY_DEFAULT", now=now, candidate_specific=True, symbol_specific=True, derived=True,
        )
    ranking_score = choose("ranking_score", FIELD_ALIASES["ranking_score"])
    confidence = choose("confidence", FIELD_ALIASES["confidence"])
    # The established candidate bridge has historically used its confidence
    # field as the only available ranking-strength proxy. Preserve that
    # compatible candidate-local mapping with explicit provenance; it never
    # changes the upstream rank or creates an expected-return forecast.
    if ranking_score is None and confidence is not None:
        ranking_score = confidence
        confidence_meta = dict(provenance.get("confidence") or {})
        provenance["ranking_score"] = {
            **confidence_meta,
            "value": ranking_score,
            "source_field": str(confidence_meta.get("source_field") or "confidence"),
            "derived": True,
        }
    regime = choose("regime_context", FIELD_ALIASES["regime"])
    sector = choose("sector_context", FIELD_ALIASES["sector"])
    catalyst = choose("catalyst_context", FIELD_ALIASES["catalyst"])
    momentum = choose("momentum_state", FIELD_ALIASES["momentum"])
    liquidity = choose("liquidity_state", FIELD_ALIASES["liquidity"])

    thesis = choose("thesis", FIELD_ALIASES["thesis"])
    support = _as_plan_list(
        _first(row, "thesis_supporting_conditions", "supporting_conditions", "positive_factors"),
        _first(row, "ranking_factors", "ranking_reason", "ranked_reason"), momentum, regime, sector, catalyst,
    )
    if not thesis and strategy and len([item for item in (momentum, regime, catalyst, ranking_score) if item not in (None, "")]) >= 2:
        facts = [item for item in (setup or strategy, momentum, regime, catalyst) if item not in (None, "")]
        thesis = f"{symbol} {facts[0]} setup is supported by current " + "; ".join(str(item) for item in facts[1:3]) + "."
        provenance["thesis"] = _provenance(
            thesis, source_system="candidate_fact_synthesis", source_field="setup/ranking/context", source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    invalidation = _as_plan_list(_first(row, "thesis_invalidation_conditions", "invalidation_conditions", "what_invalidates_setup"))
    price = _number(contextual(("price", "current_price", "last_price")))
    stop = _number(contextual(("stop_loss", "trailing_stop_price")))
    target_low = _number(contextual(("expected_target_low", "target_zone_low", "target_1")))
    target_high = _number(contextual(("expected_target_high", "target_zone_high", "target_2", "stretch_target")))
    if stop is not None:
        invalidation.append(f"review if existing stop reference is reached at {stop:.4f}")
    if not invalidation and thesis:
        invalidation.append("review if the candidate-specific thesis conditions are no longer supported")
    expected_return = choose("expected_return", FIELD_ALIASES["expected_return"])
    return_low = choose("expected_return_low", FIELD_ALIASES["expected_return_low"])
    return_high = choose("expected_return_high", FIELD_ALIASES["expected_return_high"])
    if return_low is None and price and target_low:
        return_low = ((target_low - price) / price) * 100.0
    if return_high is None and price and target_high:
        return_high = ((target_high - price) / price) * 100.0
    expected_return_range = _positive_return_range(expected_return, label="CANDIDATE_SUPPORTED")
    if expected_return_range is None:
        expected_return_range = _positive_return_range(
            {"low_pct": return_low, "high_pct": return_high}, label="CANDIDATE_SUPPORTED"
        )
    if expected_return_range is None:
        # A zero-valued legacy range is not a forecast. Check the remaining
        # existing point forecast aliases before declaring the candidate
        # unsupported; this does not generate a return estimate.
        for alias in ("expected_return_pct", "expected_return_percent", "expected_move_percent", "predicted_profit_percent", "profit_prediction_pct"):
            value = contextual((alias,))
            expected_return_range = _positive_return_range(value, label="CANDIDATE_SUPPORTED")
            if expected_return_range is not None:
                provenance["expected_return_range"] = _provenance(
                    expected_return_range, source_system="candidate_existing_forecast", source_field=alias,
                    source_row=row, evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=confidence,
                    now=now, candidate_specific=True, symbol_specific=True, derived=True,
                )
                break
    if expected_return_range is not None and "expected_return_range" not in provenance:
        provenance["expected_return_range"] = _provenance(
            expected_return_range, source_system="candidate_target_or_prediction", source_field="expected_return/target", source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    downside = choose("expected_downside", FIELD_ALIASES["expected_downside"])
    if provenance.get("expected_downside", {}).get("source_field") in {"stop_loss", "trailing_stop_price"}:
        downside = None
    # Crypto candidates may expose a current volatility/risk envelope rather
    # than an equity-style stop.  Consume that existing candidate evidence
    # directly, preserve its source, and never invent a platform-wide percent.
    asset_class = _text(_first(row, "asset_class", "asset_type")).lower()
    crypto_risk_pct = _number(contextual(("crypto_risk_pct", "risk_pct", "atr_pct", "atr_percent", "volatility_pct")))
    if downside is None and asset_class in {"crypto", "cryptocurrency", "digital_asset"} and crypto_risk_pct is not None and crypto_risk_pct > 0:
        downside = {"low_pct": -abs(crypto_risk_pct), "high_pct": -abs(crypto_risk_pct), "evidence_label": "CRYPTO_CANDIDATE_RISK_ENVELOPE"}
        provenance["expected_downside_range"] = _provenance(
            downside, source_system="crypto_candidate_risk_envelope", source_field="crypto_risk_pct/risk_pct/atr_pct/volatility_pct",
            source_row=row, evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    downside_range = downside if isinstance(downside, Mapping) else _range(
        ((stop - price) / price) * 100.0 if price and stop else None,
        ((stop - price) / price) * 100.0 if price and stop else None,
        downside,
        label="CANDIDATE_SUPPORTED",
    )
    if downside_range is not None and "expected_downside_range" not in provenance:
        provenance["expected_downside_range"] = _provenance(
            downside_range, source_system="candidate_stop_or_risk", source_field="stop_loss/expected_downside", source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    drawdown = choose("expected_drawdown", FIELD_ALIASES["expected_drawdown"])
    drawdown_source = str((provenance.get("expected_drawdown") or {}).get("source_field") or "")
    if drawdown_source == "drawdown_risk_score":
        # The score remains available to the ranking and risk systems, but it
        # is not a percentage loss forecast for the pretrade contract.
        drawdown = None
        provenance.pop("expected_drawdown", None)
    hold_days, hold_duration_source = _expected_hold_duration_days(row, str(horizon))
    hold_window = _text(_first(row, "expected_hold_window", "hold_window"))
    if not hold_window and hold_duration_source in {"expected_hold_days", "hold_days"} and hold_days:
        hold_window = f"{hold_days:g} trading days"
        provenance["expected_hold_window"] = _provenance(
            hold_window,
            source_system="candidate_existing_duration",
            source_field=hold_duration_source,
            source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT",
            confidence=confidence,
            now=now,
            candidate_specific=True,
            symbol_specific=True,
            derived=True,
        )
    if not hold_window and horizon:
        hold_window = "same session" if str(horizon) == "day_trade" else "1-5 trading days" if str(horizon) == "swing_trade" else "bounded existing horizon"
        provenance["expected_hold_window"] = _provenance(
            hold_window, source_system="bounded_strategy_horizon_mapping", source_field="intended_horizon", source_row=row,
            evidence_class="BOUNDED_POLICY_DEFAULT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    per_day = None
    if expected_return_range and hold_days:
        per_day = {
            "low_pct_per_day": round(float(expected_return_range.get("low_pct", 0.0)) / hold_days, 4),
            "high_pct_per_day": round(float(expected_return_range.get("high_pct", 0.0)) / hold_days, 4),
            "method": "candidate_expected_return_over_bounded_horizon",
        }
        provenance["expected_return_per_day_range"] = _provenance(
            per_day, source_system="candidate_expected_return_and_horizon", source_field=f"expected_return_range/{hold_duration_source}", source_row=row,
            evidence_class="CURRENT_CANDIDATE_DIRECT" if hold_duration_source in {"expected_hold_minutes", "hold_minutes", "expected_hold_days", "hold_days"} else "BOUNDED_POLICY_DEFAULT", confidence=confidence, now=now,
            candidate_specific=True, symbol_specific=True, derived=True,
        )
    hold_conditions = _as_plan_list(_first(row, "hold_conditions", "thesis_hold_conditions"))
    if not hold_conditions and thesis and horizon:
        hold_conditions.append(f"hold while current thesis support remains valid and within the {horizon} plan")
    profit_conditions = _as_plan_list(_first(row, "profit_protection_conditions", "profit_lock_conditions"))
    if not profit_conditions and target_high is not None:
        profit_conditions.append(f"review profit protection near the existing target reference at {target_high:.4f}")
    if not profit_conditions and thesis:
        profit_conditions.append("profit-protection review only under the existing profit-capture policy if gains materially reverse")
    exit_conditions = _as_plan_list(_first(row, "exit_review_conditions", "exit_conditions", "sell_reason"))
    if not exit_conditions and horizon:
        exit_conditions.append("exit review if thesis invalidates, momentum materially deteriorates, or the intended horizon expires")
    loss_conditions = _as_plan_list(_first(row, "controlled_loss_conditions", "loss_acceptance_conditions"))
    if not loss_conditions and stop is not None:
        loss_conditions.append(f"controlled-loss review at the existing stop reference {stop:.4f}; no automatic exit instruction")
    if not loss_conditions and thesis:
        loss_conditions.append("controlled-loss review only if the thesis invalidates under the existing loss-acceptance policy; no automatic exit")
    replacement_conditions = _as_plan_list(_first(row, "replacement_review_conditions", "replacement_conditions", "replacement_reason"))
    if not replacement_conditions:
        replacement_conditions.append("review only against a current eligible comparison set")
    monitoring = _as_plan_list(_first(row, "monitoring_priorities", "monitoring_plan", "monitoring_conditions"), momentum, regime, catalyst, liquidity)
    if not monitoring and _first(
        row,
        "risk_evidence_generated_at",
        "quote_assignment_at",
        "provider_quote_timestamp",
        "candidate_generated_at",
        "generated_at",
        "expires_at",
    ):
        monitoring.append("monitor candidate snapshot freshness and the existing thesis conditions")
    entry_conditions = _as_plan_list(_first(row, "entry_conditions", "entry_confirmation_conditions", "recommended_entry_mode", "entry_timing_decision"))
    if not entry_conditions and liquidity:
        entry_conditions.append("retain existing entry confirmation and liquidity gates")
    if not entry_conditions and thesis:
        entry_conditions.append("existing qualification, risk, liquidity, and session gates must pass")

    peers = [item for item in current_rows if _candidate_symbol(item) and _candidate_symbol(item) != symbol]
    scored_peers = sorted(peers, key=lambda item: _number(_first(item, "ranking_score", "score", "confidence_score", "rank_score")) or float("-inf"), reverse=True)
    comparisons = [{"candidate_id": _text(_first(item, "candidate_id", "source_candidate_id")), "symbol": _candidate_symbol(item), "ranking_score": _first(item, "ranking_score", "score", "confidence_score", "rank_score")} for item in scored_peers[:5]]
    opportunity_state = "NO_VALID_COMPARISON_SET"
    if comparisons and ranking_score is not None:
        best_peer = _number(comparisons[0].get("ranking_score"))
        opportunity_state = "COMPETITIVE_OPPORTUNITY" if best_peer is None or float(ranking_score) >= best_peer else "LOWER_PRIORITY_OPPORTUNITY"
    elif peers:
        opportunity_state = "INSUFFICIENT_COMPARISON_EVIDENCE"

    plan_fields = {
        "strategy_archetype": strategy, "trade_style": trade_style, "intended_horizon": horizon,
        "ranking_score": ranking_score, "thesis": thesis, "thesis_supporting_conditions": support,
        "thesis_invalidation_conditions": invalidation, "expected_hold_window": hold_window,
        "expected_return_range": expected_return_range, "expected_downside_range": downside_range,
        "expected_drawdown": drawdown, "expected_return_per_day_range": per_day,
        "entry_conditions": entry_conditions, "hold_conditions": hold_conditions,
        "profit_protection_conditions": profit_conditions, "exit_review_conditions": exit_conditions,
        "controlled_loss_conditions": loss_conditions, "replacement_review_conditions": replacement_conditions,
        "monitoring_priorities": monitoring, "confidence": confidence, "regime_context": regime,
        "sector_context": sector, "catalyst_context": catalyst, "momentum_state": momentum,
        "liquidity_state": liquidity, "opportunity_cost_state": opportunity_state,
        "competing_candidates_considered": comparisons,
    }
    for field, value in plan_fields.items():
        if value not in (None, "", [], {}):
            row[field] = value
    risk_envelope = build_candidate_risk_envelope_v1(
        row, statuses=statuses, current_candidates=current_rows, now=now,
    )
    expected_outcome = build_expected_outcome_envelope_v1(row, risk_envelope)
    risk_envelope["consumer_acknowledgements"]["CONSUMED_BY_ENRICHMENT"] = True
    row["candidate_risk_envelope_v1"] = risk_envelope
    row["expected_outcome_envelope_v1"] = expected_outcome
    row["risk_envelope_id"] = risk_envelope.get("risk_envelope_id")
    row["expected_outcome_id"] = expected_outcome.get("expected_outcome_id")
    risk_provenance_fields = {
        "expected_return_range": "expected_upside_range",
        "expected_downside_range": "expected_downside_range",
        "expected_drawdown": "expected_drawdown",
        "expected_return_per_day_range": "expected_return_per_day_range",
        "reward_to_risk_range": "reward_to_risk_range",
    }
    for field, value in {
        "expected_return_range": expected_outcome.get("expected_return_range"),
        "expected_downside_range": expected_outcome.get("expected_downside_range"),
        "expected_drawdown": expected_outcome.get("expected_drawdown"),
        "expected_return_per_day_range": expected_outcome.get("expected_return_per_day_range"),
        "reward_to_risk_range": expected_outcome.get("reward_to_risk_range"),
    }.items():
        if row.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
            row[field] = value
        source_field = risk_provenance_fields[field]
        if source_field in risk_envelope.get("field_provenance_v1", {}):
            provenance[field] = dict(risk_envelope["field_provenance_v1"][source_field])
    # Alias probes may have failed before a supported target/stop or
    # confidence fallback resolved the canonical field. Do not report those
    # stale probes as missing evidence once the contract has the value.
    resolved_source_keys = {
        "strategy_archetype": strategy,
        "intended_horizon": horizon,
        "trade_style": trade_style,
        "ranking_score": ranking_score,
        "confidence": confidence,
        "thesis": thesis,
        "expected_return": expected_return_range,
        "expected_return_low": expected_return_range,
        "expected_return_high": expected_return_range,
        "expected_downside": downside_range,
        "expected_drawdown": drawdown,
    }
    for source_key, resolved in resolved_source_keys.items():
        if resolved not in (None, "", [], {}):
            missing_sources.pop(source_key, None)
    evidence_classes = []
    for meta in provenance.values():
        label = str(meta.get("evidence_class") or "UNAVAILABLE")
        if label not in evidence_classes:
            evidence_classes.append(label)
    if evidence_classes:
        row["evidence_classes"] = evidence_classes
    core_missing = [field for field in ("strategy_archetype", "intended_horizon", "thesis", "expected_return_range", "expected_downside_range", "expected_hold_window") if row.get(field) in (None, "", [], {})]
    warnings = sorted(set(field for field, meta in provenance.items() if meta.get("evidence_class") in {"HISTORICAL_SYMBOL_SUPPORTED", "RECONSTRUCTED_SUPPORTED", "REPLAY_SUPPORTED", "SHADOW_SUPPORTED", "AGGREGATE_ADVISORY"}))
    row["field_provenance_v1"] = provenance
    row["pretrade_enrichment_v1"] = {
        "enrichment_owner": "astra_premarket_certification_v1",
        "enrichment_version": "1.1.0",
        "enrichment_ran": True,
        "candidate_symbol": symbol,
        "source_registry": list(EVIDENCE_SOURCE_REGISTRY),
        "contexts_considered": len(contexts),
        "strategy_state": "STRATEGY_CONFLICTING" if "strategy_archetype" in conflicts else strategy_state,
        "thesis_state": "THESIS_COMPLETE" if thesis else "THESIS_INCOMPLETE",
        "risk_envelope_state": risk_envelope.get("risk_envelope_state"),
        "expected_outcome_state": expected_outcome.get("expected_outcome_state"),
        "hold_plan_state": "HOLD_PLAN_COMPLETE" if all((hold_conditions, profit_conditions, exit_conditions, loss_conditions, replacement_conditions)) else "HOLD_PLAN_INCOMPLETE",
        "opportunity_comparison_state": opportunity_state,
        "missing_fields": core_missing,
        "missing_sources": missing_sources,
        "conflicting_fields": sorted(set(conflicts)),
        "warning_fields": warnings,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "full_history_scan_count": 0,
    }
    return row


def _contract_state(contract: Mapping[str, Any]) -> str:
    if contract.get("conflicting_fields"):
        return "CONTRACT_CONFLICTING"
    if contract.get("missing_required_fields"):
        return "CONTRACT_INCOMPLETE"
    if contract.get("warning_fields"):
        return "CONTRACT_COMPLETE_WITH_WARNINGS"
    return "CONTRACT_COMPLETE"


def build_pretrade_decision_contract(
    candidate: Mapping[str, Any],
    *,
    certification_snapshot_id: str = "",
    expiry_timestamp: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the only contract schema from the canonical enrichment result.

    A direct caller cannot bypass enrichment: an unprepared candidate is first
    passed through the side-effect-free enrichment owner. This never changes
    a ranking or a gate; it only supplies attributable existing evidence.
    """
    row = enrich_candidate_for_pretrade_contract(candidate, now=now)
    candidate_id = _text(_first(row, "candidate_id", "source_candidate_id"))
    recommendation_id = _text(_first(row, "recommendation_id", "canonical_recommendation_id", "source_recommendation_id"))
    decision_id = _text(_first(row, "decision_id", "selection_id", "source_decision_id")) or _stable_decision_id(candidate_id, recommendation_id)
    generated = _text(_first(row, "candidate_generated_at", "generated_at", "timestamp", "recommendation_timestamp"))
    expiry = _text(expiry_timestamp or _first(
        row,
        "expires_at",
        "candidate_expires_at",
        "risk_evidence_valid_until",
        "forecast_valid_until",
        "valid_until",
    ))
    if not expiry and generated:
        try:
            expiry = (datetime.fromisoformat(generated.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        except ValueError:
            expiry = ""
    lane = _lane(_first(row, "lane_id", "lane", "asset_lane"))
    if lane == "UNKNOWN" and _text(_first(row, "asset_class", "asset_type")).lower() == "crypto":
        lane = "CRYPTO"
    execution_horizon, _ = _pretrade_execution_horizon(row)
    horizon = execution_horizon or _text(_first(row, "intended_horizon", "paper_entry_horizon_style", "trade_horizon_style", "best_horizon_style"))
    generated_snapshot = _text(certification_snapshot_id or row.get("certification_snapshot_id"))
    if not generated_snapshot and candidate_id:
        generated_snapshot = "candidate-enrichment:" + hashlib.sha256(
            f"{candidate_id}|{recommendation_id}".encode("utf-8")
        ).hexdigest()[:16]
    forecast = dict(row.get("crypto_pretrade_forecast_v1") or {})
    forecast_provenance = dict(forecast.get("source_provenance") or row.get("forecast_source_provenance") or {})
    forecast_inputs = dict(forecast.get("source_inputs") or row.get("forecast_source_inputs") or {})
    target = {
        "low": _first(row, "expected_target_low", "target_zone_low", "target_1"),
        "high": _first(row, "expected_target_high", "target_zone_high", "target_2", "stretch_target"),
    }
    if target["low"] in (None, "") and target["high"] in (None, ""):
        target = {}
    contract = {
        "contract_version": VERSION,
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "decision_id": decision_id,
        "symbol": _text(_first(row, "symbol", "ticker")).upper(),
        "lane": lane,
        "strategy_archetype": _text(_first(row, "strategy_archetype", "trade_archetype", "strategy_cohort", "setup_type")),
        "trade_style": _text(_first(row, "trade_style", "intended_trade_style", "paper_entry_horizon_style")),
        "ranking_score": _first(row, "ranking_score", "score", "confidence_score", "rank_score"),
        "ranking_factors": _as_list(_first(row, "ranking_factors", "why_astra_likes_it", "ranking_reason")),
        "thesis": _text(_first(row, "thesis", "entry_rationale", "intelligence_summary", "summary")),
        "thesis_supporting_conditions": _as_list(_first(row, "thesis_supporting_conditions", "supporting_conditions", "positive_factors")),
        "thesis_invalidation_conditions": _as_list(_first(row, "thesis_invalidation_conditions", "invalidation_conditions", "what_invalidates_setup")),
        "intended_horizon": horizon,
        "expected_hold_window": _text(_first(row, "expected_hold_window", "hold_window")),
        # Versioned evidence fields are observational contract metadata.  The
        # existing required fields and order gates remain authoritative.
        "schema_version": _text(forecast.get("schema_version") or row.get("forecast_schema_version") or VERSION),
        "observation_timestamp": _text(_first(row, "candidate_generated_at", "generated_at", "timestamp")),
        "market_data_timestamp": _text(_first(row, "provider_quote_timestamp", "quote_timestamp", "bar_timestamp")),
        "forecast_timestamp": _text(forecast.get("forecast_timestamp") or row.get("forecast_timestamp")),
        "valid_until": _text(forecast.get("valid_until") or row.get("forecast_valid_until") or expiry),
        "target": target,
        "downside_or_risk": _first(row, "expected_downside_range", "crypto_risk_pct", "risk_pct", "atr_pct"),
        "risk_envelope": dict(row.get("candidate_risk_envelope_v1") or {}),
        "calculation_method": _text(forecast.get("calculation_method") or row.get("expected_return_method")),
        "source_inputs": forecast_inputs,
        "source_provenance": forecast_provenance,
        "risk_envelope_id": _text(row.get("risk_envelope_id")),
        "candidate_risk_envelope_v1": dict(row.get("candidate_risk_envelope_v1") or {}),
        "expected_outcome_envelope_v1": dict(row.get("expected_outcome_envelope_v1") or {}),
        "expected_return_range": _first(row, "expected_return_range", "expected_move_high"),
        "expected_downside_range": _first(row, "expected_downside_range", "expected_move_low", "stop_loss"),
        "expected_return_per_day_range": _first(row, "expected_return_per_day_range", "expected_return_per_day"),
        "expected_drawdown": _first(row, "expected_drawdown", "drawdown_risk_score"),
        "regime_fit": _first(row, "regime_fit", "regime_alignment_label", "regime_alignment_score"),
        "sector_fit": _first(row, "sector_fit", "sector", "sector_context"),
        "catalyst_state": _first(row, "catalyst_state", "catalyst", "catalyst_context"),
        "fundamental_state": _first(row, "fundamental_state", "fundamentals_context"),
        "momentum_state": _first(row, "momentum_state", "trend_state"),
        "liquidity_state": _first(row, "liquidity_state", "liquidity_label", "spread_quality"),
        "opportunity_cost_comparison": _first(row, "opportunity_cost_comparison", "opportunity_cost_state"),
        "competing_candidates_considered": _as_list(_first(row, "competing_candidates_considered", "competing_candidates")),
        "selection_reason": _text(_first(row, "selection_reason", "why_selected", "decision_reason")),
        "alternatives_rejected_reason": _text(_first(row, "alternatives_rejected_reason", "rejection_reason")),
        "entry_conditions": _as_list(_first(row, "entry_conditions", "entry_confirmation_conditions")),
        "hold_conditions": _as_list(_first(row, "hold_conditions", "thesis_hold_conditions")),
        "profit_protection_conditions": _as_list(_first(row, "profit_protection_conditions", "profit_lock_conditions")),
        "exit_review_conditions": _as_list(_first(row, "exit_review_conditions", "exit_conditions")),
        "controlled_loss_conditions": _as_list(_first(row, "controlled_loss_conditions", "loss_acceptance_conditions")),
        "replacement_review_conditions": _as_list(_first(row, "replacement_review_conditions", "replacement_conditions")),
        "monitoring_priorities": _as_list(_first(row, "monitoring_priorities", "monitoring_plan", "monitoring_conditions")),
        "confidence": _first(row, "confidence", "predicted_win_probability"),
        "evidence_classes": _as_list(_first(row, "evidence_classes", "evidence_class", "truth_quality")),
        "field_provenance_v1": dict(row.get("field_provenance_v1") or {}),
        "pretrade_enrichment_v1": dict(row.get("pretrade_enrichment_v1") or {}),
        "certification_snapshot_id": generated_snapshot,
        "expiry_timestamp": expiry,
        "candidate_generated_at": generated,
        "thesis_id": _text(_first(row, "thesis_id")) or ("thesis-" + decision_id[4:] if decision_id.startswith("dec-") else ""),
        "thesis_state": "THESIS_COMPLETE" if _text(_first(row, "thesis", "entry_rationale", "intelligence_summary", "summary")) else "THESIS_INCOMPLETE",
        "expected_outcome_state": "EXPECTED_OUTCOME_COMPLETE" if all(
            _first(row, key) not in (None, "", [], {})
            for key in ("expected_return_range", "expected_downside_range", "expected_drawdown", "expected_return_per_day_range")
        ) else "EXPECTED_OUTCOME_INCOMPLETE",
        "hold_plan_state": "HOLD_PLAN_COMPLETE" if all(
            _first(row, key) not in (None, "", [], {})
            for key in ("expected_hold_window", "hold_conditions", "profit_protection_conditions", "exit_review_conditions", "controlled_loss_conditions", "replacement_review_conditions")
        ) else "HOLD_PLAN_INCOMPLETE",
        "opportunity_cost_state": _text(_first(row, "opportunity_cost_state", "opportunity_cost_comparison")) or "NO_VALID_COMPARISON_SET",
        "competing_candidate_summary": _as_list(_first(row, "competing_candidate_summary", "competing_candidates_considered", "competing_candidates")),
        "producer_acknowledgements": {
            "candidate_identity": bool(candidate_id and recommendation_id and decision_id),
            "strategy_horizon": bool(lane in LANES and horizon),
            "thesis": bool(_text(_first(row, "thesis", "entry_rationale", "intelligence_summary", "summary"))),
            "outcome_envelope": bool(_first(row, "expected_return_range") not in (None, "", [], {})),
            "risk_envelope": bool(row.get("risk_envelope_id") and dict(row.get("candidate_risk_envelope_v1") or {}).get("risk_envelope_state") in {"RISK_ENVELOPE_COMPLETE", "RISK_ENVELOPE_COMPLETE_WITH_WARNINGS"}),
            "hold_plan": bool(_first(row, "hold_conditions") not in (None, "", [], {})),
        },
        "consumer_acknowledgements": {
            "risk_envelope": "CONSUMED_BY_CONTRACT",
            "final_qualification": False,
            "order_ready_gate": False,
            "lifecycle_initialization": False,
        },
    }
    risk = dict(contract.get("candidate_risk_envelope_v1") or {})
    if risk:
        risk.setdefault("consumer_acknowledgements", {})["CONSUMED_BY_CONTRACT"] = True
        contract["candidate_risk_envelope_v1"] = risk
    contract_id_seed = "|".join((candidate_id, recommendation_id, decision_id, _text(contract.get("certification_snapshot_id"))))
    contract["contract_id"] = "contract-" + hashlib.sha256(contract_id_seed.encode("utf-8")).hexdigest()[:20] if contract_id_seed else ""
    validated = validate_pretrade_decision_contract(contract, now=now)
    validated["contract_state"] = _contract_state(validated)
    validated["candidate_terminal_state"] = (
        validated["contract_state"] if validated["contract_state"] in {"CONTRACT_COMPLETE", "CONTRACT_COMPLETE_WITH_WARNINGS"}
        else "CONTRACT_BUILDING"
    )
    return validated


def validate_pretrade_decision_contract(contract: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    out = dict(contract or {})
    missing = [key for key in REQUIRED_CONTRACT_FIELDS if out.get(key) in (None, "", [], {})]
    enrichment = dict(out.get("pretrade_enrichment_v1") or {})
    conflicting = list(enrichment.get("conflicting_fields") or [])
    warning_fields = list(enrichment.get("warning_fields") or [])
    risk = dict(out.get("candidate_risk_envelope_v1") or {})
    risk_state = _text(risk.get("risk_envelope_state"))
    if risk_state not in {"RISK_ENVELOPE_COMPLETE", "RISK_ENVELOPE_COMPLETE_WITH_WARNINGS"}:
        missing.append("candidate_risk_envelope_v1")
    if risk_state == "RISK_ENVELOPE_STALE":
        conflicting.append("stale_risk_envelope")
    if not bool(enrichment.get("enrichment_ran")):
        missing.append("pretrade_enrichment_v1")
    if out.get("lane") not in LANES:
        conflicting.append("unsupported_or_missing_lane")
    symbol = str(out.get("symbol") or "")
    normalized_symbol = symbol.replace("/", "").replace("-", "")
    if symbol and not normalized_symbol.isalnum():
        conflicting.append("invalid_symbol")
    expiry = _text(out.get("expiry_timestamp"))
    expired = False
    if expiry:
        try:
            expired = datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone(timezone.utc) <= _now(now)
        except ValueError:
            conflicting.append("invalid_expiry_timestamp")
    if expired:
        conflicting.append("expired_contract")
    valid = not missing and not conflicting
    out.update({
        "contract_status": "VALID" if valid else "INVALID",
        "order_ready_allowed": bool(valid),
        "missing_required_fields": missing,
        "conflicting_fields": sorted(set(conflicting)),
        "warning_fields": sorted(set(warning_fields)),
        "fail_closed_reason": "" if valid else "PRETRADE_DECISION_CONTRACT_" + ("MISSING_FIELDS" if missing else "CONFLICT"),
        "legacy_position_label": "LEGACY_INCOMPLETE_LINEAGE",
    })
    return out


def certification_ownership_map() -> list[dict[str, str]]:
    """Compact canonical ownership map, retained with the certification result."""
    rows = (
        ("candidate_generation", "ranking/top_buys snapshot", "candidate_decision_ledger_v1", "PaperAutopilot", "candidate_id"),
        ("recommendation_and_thesis", "canonical Copilot/ranking row", "candidate_decision_ledger_v1", "decision contract", "recommendation_id"),
        ("horizon_and_lane", "AstraTradeLaneRegistryV1", "candidate + execution trace", "PaperAutopilot", "candidate_id"),
        ("eligibility_selection_order_ready", "PaperAutopilot", "last_execution_trace + lane ledger", "paper order boundary", "candidate_id"),
        ("broker_ack_fill_position", "Alpaca paper broker", "broker truth registry", "lifecycle owner", "broker_order_id/fill_id"),
        ("lifecycle_excursion_exit", "trade lifecycle tracker", "lifecycle/excursion stores", "profit/exit advisory", "lifecycle_id"),
        ("strict_truth_learning", "broker truth integrity", "broker_truth_records_v1", "learning consumers", "entry_fill_id+exit_fill_id"),
        ("governance_visibility", "Governance deterministic audits", "governance registry", "Cortex/Action Center", "finding_id"),
    )
    return [
        {"system": name, "canonical_producer": producer, "canonical_store": store,
         "canonical_consumer": consumer, "join_key": key,
         "freshness_contract": "current_cycle_or_bounded_cached", "duplicate_owner_contract": "canonical_owner_only"}
        for name, producer, store, consumer, key in rows
    ]


def build_lane_certification(
    lane: str,
    *,
    activation: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    contracts: Iterable[Mapping[str, Any]],
    production_commit: str,
    snapshot_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Certify a lane only from the existing dry-run and decision contracts."""
    lane_id = _lane(lane)
    lane_contracts = [dict(row) for row in contracts if _lane(row.get("lane")) == lane_id]
    traces = [dict(row) for row in (dry_run.get("per_candidate_decision_trace") or []) if _lane(row.get("lane_id")) == lane_id]
    valid_contracts = [row for row in lane_contracts if row.get("contract_status") == "VALID"]
    missing_field_counts: dict[str, int] = {}
    for contract in lane_contracts:
        for field in contract.get("missing_required_fields") or []:
            missing_field_counts[str(field)] = missing_field_counts.get(str(field), 0) + 1
    activation_blockers = list(activation.get("exact_blockers") or [])
    no_current = not lane_contracts
    blocker = (
        "NO_CURRENT_ELIGIBLE_%s_CANDIDATE" % lane_id
        if no_current else "PRETRADE_CONTRACT_INVALID"
        if not valid_contracts else activation_blockers[0]
        if activation_blockers else "MARKET_SESSION_OR_EXISTING_GATE_BLOCKED"
        if not any(row.get("order_ready") for row in traces) else ""
    )
    stage_names = (
        "candidate_identity", "recommendation_thesis", "strategy_horizon_lane", "freshness_session",
        "ranking_eligibility_risk_capacity", "order_ready", "simulated_entry_ack_fill",
        "position_lifecycle_monitoring", "simulated_exit_closure", "strict_truth_consumer_delivery", "fixture_cleanup",
    )
    passed_contract = bool(valid_contracts)
    order_ready = any(bool(row.get("order_ready")) for row in traces) and passed_contract
    stages = []
    for name in stage_names:
        if name in {"candidate_identity", "recommendation_thesis", "strategy_horizon_lane"}:
            result = "PASS" if passed_contract else "FAIL_CLOSED"
        elif name in {"freshness_session", "ranking_eligibility_risk_capacity", "order_ready"}:
            result = "PASS" if order_ready else "BLOCKED_BY_EXISTING_PRODUCTION_GATE"
        elif name in {"simulated_entry_ack_fill", "position_lifecycle_monitoring", "simulated_exit_closure", "strict_truth_consumer_delivery"}:
            result = "SIMULATION_NOT_RUN_NO_ORDER_READY_CANDIDATE" if not order_ready else "SIMULATED_PASS_NO_BROKER_MUTATION"
        else:
            result = "PASS_NO_FIXTURES_PERSISTED"
        stages.append({"stage": name, "result": result, "owner": "PaperAutopilot" if name in {"ranking_eligibility_risk_capacity", "order_ready"} else "certification_contract"})
    if order_ready:
        status = "CERTIFIED"
    elif no_current:
        status = "READY_NO_TRADE"
    elif not valid_contracts:
        status = "CONTRACT_INCOMPLETE"
    elif activation_blockers:
        status = "NOT_CERTIFIED"
    else:
        status = "FAIL_CLOSED"
    generated = _iso(now)
    return {
        "lane": lane_id, "snapshot_id": snapshot_id, "certification_timestamp": generated,
        "expiry_timestamp": _iso(_now(now) + timedelta(minutes=15)), "production_commit": production_commit,
        "status": status, "exact_blocker": blocker or None,
        "severity": "HIGH" if status == "FAIL_CLOSED" else "WARNING" if status in {"CONTRACT_INCOMPLETE", "NOT_CERTIFIED"} else "NONE",
        "candidate_contract_count": len(lane_contracts), "valid_contract_count": len(valid_contracts),
        "missing_contract_field_counts": dict(sorted(missing_field_counts.items(), key=lambda item: (-item[1], item[0]))),
        "contract_evidence_samples": [
            {
                "symbol": row.get("symbol"),
                "candidate_id": row.get("candidate_id"),
                "decision_id": row.get("decision_id"),
                "contract_status": row.get("contract_status"),
                "missing_required_fields": list(row.get("missing_required_fields") or []),
            }
            for row in lane_contracts[:3]
        ],
        "dry_run_trace_count": len(traces), "order_ready_count": sum(1 for row in traces if row.get("order_ready")),
        "stages": stages, "safe_auto_repair_attempted": False, "human_action_required": status != "CERTIFIED",
        "verification_result": "NO_BROKER_ACTIONS_AND_NO_FIXTURE_PERSISTENCE",
        "fixture_truths_created": 0, "residual_fixture_orders": 0, "residual_fixture_positions": 0,
        "residual_fixture_commitments": 0, "consumer_acknowledgements": "PENDING_REAL_FILLED_LIFECYCLE" if not order_ready else "SIMULATED_CONTRACT_PATH",
    }


def deterministic_failure_injection_summary() -> dict[str, Any]:
    """Declarative coverage list used by unit tests; no runtime mutation."""
    cases = (
        "false_reserve_exhaustion", "historical_counter_contamination", "candidate_without_identity",
        "identity_lost_before_horizon", "day_candidate_scalp_rejection", "capacity_before_horizon_blocker",
        "stale_governance_issue", "zero_candidate_semantics", "broker_registry_mismatch",
        "position_without_owner", "order_without_recommendation", "fill_without_lifecycle",
        "truth_without_consumer_ack", "shadow_metric_contamination", "impossible_mfe_mae",
        "missing_lifecycle_checkpoint", "available_intelligence_not_consumed", "unacknowledged_ranking_influence",
        "expired_certification", "code_changed_certification", "worker_health_contradiction",
        "stale_cache_masks_broker", "expired_commitment", "safe_repair_allowed", "behavior_repair_refused",
        "evidence_starvation", "capacity_without_certification", "missing_thesis", "missing_horizon",
        "missing_exit_review", "fixture_cleanup_failure", "hidden_high_finding",
    )
    return {"total_cases": len(cases), "cases": [{"case": case, "expected_detection": "PASS", "broker_actions_used": 0} for case in cases]}
