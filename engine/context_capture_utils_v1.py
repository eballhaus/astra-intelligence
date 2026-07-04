from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unknown_label(raw: Any) -> bool:
    label = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return not label or label in {"unknown", "unknown_catalyst", "uncertain_regime", "none", "no_detected_catalyst"} or label.startswith("unknown_")


def canonical_catalyst(raw: Any) -> tuple[str, str, float]:
    label = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if _unknown_label(label):
        return "unknown", "unknown_or_missing", 0.0
    mapping = (
        ("analyst_upgrade", ("analyst_upgrade", "upgrade", "upgraded")),
        ("analyst_downgrade", ("analyst_downgrade", "downgrade", "downgraded")),
        ("earnings", ("earnings", "earn", "eps")),
        ("guidance", ("guidance", "raised_guidance", "lowered_guidance")),
        ("sector_rotation", ("sector_rotation", "rotation", "sector")),
        ("rate_policy", ("rate_policy", "fed", "rate", "rates")),
        ("inflation_data", ("inflation", "cpi", "ppi")),
        ("employment_data", ("employment", "jobs", "payroll", "unemployment")),
        ("macro_event", ("macro", "fomc", "treasury", "risk_off", "risk_on")),
        ("technical_breakout", ("breakout", "technical_breakout")),
        ("technical_reversal", ("reversal", "technical_reversal")),
        ("momentum_continuation", ("momentum_continuation", "continuation", "momentum")),
        ("mean_reversion", ("mean_reversion", "reversion", "range_rotation")),
        ("news_event", ("news", "headline")),
        ("volume_spike", ("volume_spike", "unusual_volume", "volume")),
        ("volatility_event", ("volatility", "high_volatility", "vix")),
    )
    for canonical, tokens in mapping:
        if any(token in label for token in tokens):
            return canonical, "inferred_from_existing_field", 55.0
    return "unknown", "unmapped_existing_field", 15.0


def canonical_regime(raw: Any) -> tuple[str, str, float]:
    label = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if _unknown_label(label):
        return "unknown", "unknown_or_missing", 0.0
    mapping = (
        ("risk_on", ("risk_on", "growth_supportive")),
        ("risk_off", ("risk_off", "defensive", "stress")),
        ("high_volatility", ("high_volatility", "opening_volatility", "range_high_vol")),
        ("low_volatility", ("low_volatility", "range_low_vol", "volatility_controlled")),
        ("momentum_market", ("momentum_market", "momentum_expansion", "momentum_continuation", "breakout_continuation")),
        ("mean_reversion_market", ("mean_reversion", "range_chop", "sideways")),
        ("sector_rotation", ("sector_rotation", "rotation")),
        ("inflation_pressure", ("inflation_pressure", "inflation")),
        ("disinflation", ("disinflation",)),
        ("rising_rates", ("rising_rates", "rate_pressure")),
        ("falling_rates", ("falling_rates",)),
        ("bull", ("bull", "bullish", "uptrend")),
        ("bear", ("bear", "bearish", "downtrend")),
        ("sideways", ("sideways", "neutral", "regular_market", "premarket")),
    )
    for canonical, tokens in mapping:
        if any(token in label for token in tokens):
            return canonical, "inferred_from_existing_field", 55.0
    return "unknown", "unmapped_existing_field", 15.0


def enrich_context_row(row: dict[str, Any], *, source_file: str) -> dict[str, Any]:
    """Add context metadata for learning records without inventing labels or changing behavior."""
    if not isinstance(row, dict):
        return row
    enriched = dict(row)
    raw_catalyst = (
        enriched.get("catalyst_label")
        or enriched.get("catalyst_type")
        or enriched.get("dominant_catalyst_type")
        or enriched.get("catalyst")
        or enriched.get("catalyst_theme")
        or enriched.get("theme")
        or ("earnings" if bool(enriched.get("earnings_flag", False)) else "")
    )
    raw_regime = (
        enriched.get("regime_label")
        or enriched.get("market_regime")
        or enriched.get("regime_context")
        or enriched.get("entry_regime_context")
        or enriched.get("regime")
        or enriched.get("session_type")
    )
    catalyst_label, catalyst_source, catalyst_confidence = canonical_catalyst(raw_catalyst)
    regime_label, regime_source, regime_confidence = canonical_regime(raw_regime)
    unknown_reasons = []
    if catalyst_label == "unknown":
        unknown_reasons.append("missing_or_insufficient_catalyst_context")
    if regime_label == "unknown":
        unknown_reasons.append("missing_or_insufficient_regime_context")
    enriched.setdefault("catalyst_label", catalyst_label)
    enriched.setdefault("catalyst_confidence", round(float(catalyst_confidence), 3))
    enriched.setdefault("regime_label", regime_label)
    enriched.setdefault("regime_confidence", round(float(regime_confidence), 3))
    enriched.setdefault("context_source", f"{source_file}:context_capture_utils_v1")
    enriched.setdefault("context_capture_timestamp", _now_iso())
    enriched.setdefault("capture_timestamp", enriched.get("context_capture_timestamp"))
    enriched.setdefault("unknown_reason_code", ";".join(unknown_reasons) if unknown_reasons else "context_captured")
    enriched.setdefault("context_capture_engine_v1", True)
    enriched.setdefault("context_capture_behavior_safe_to_apply", False)
    enriched.setdefault("context_capture_label_policy", "existing_fields_only_no_fabrication")
    enriched.setdefault("catalyst_label_source", catalyst_source)
    enriched.setdefault("regime_label_source", regime_source)
    return enriched
