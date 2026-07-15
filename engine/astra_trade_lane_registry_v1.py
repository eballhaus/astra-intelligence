"""Canonical, advisory trade-lane metadata for Astra paper learning.

This module intentionally carries identity and learning context only.  It does
not score candidates, reserve capacity, submit orders, or alter lifecycle
rules.  The paper-autopilot entry bridge uses it to persist a stable lane
contract before an existing paper-order path is invoked.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping

try:
    from engine.intelligence_quality_common_v1 import CachedDiagnosticModule
except Exception:  # pragma: no cover - standalone diagnostic fallback
    CachedDiagnosticModule = object  # type: ignore


LANE_SWING = "SWING"
LANE_DAY = "DAY"
LANE_CRYPTO = "CRYPTO"
VALID_LANES = {LANE_SWING, LANE_DAY, LANE_CRYPTO}

# Instrument classification is deliberately independent from the execution
# lane.  This is Astra's existing canonical ETF registry, not a ticker-name
# heuristic. Explicit broker or upstream security metadata always wins.
CANONICAL_ETF_SYMBOL_REGISTRY = {
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI",
    "XLP", "XLU", "XLB", "XLC", "SMH", "SOXX", "ARKK",
}
# Backward-compatible public name retained for existing consumers.
KNOWN_ETF_SYMBOLS = CANONICAL_ETF_SYMBOL_REGISTRY

CONTRACT_FIELDS = (
    "lane_id",
    "trade_style",
    "intended_horizon",
    "asset_class",
    "instrument_type",
    "strategy_cohort",
    "recommendation_id",
    "candidate_id",
    "decision_timestamp",
    "eligibility_timestamp",
    "selection_timestamp",
    "expected_max_hold",
    "same_session_exit_required",
    "overnight_allowed",
    "capital_book_id",
    "position_owner",
    "exit_policy_owner",
    "source_ranking_version",
    "source_policy_version",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalized_asset_class(row: Mapping[str, Any]) -> str:
    raw = _text(_first(row, "asset_class", "asset_type", "market"))
    raw = raw.lower().replace("-", "_").replace(" ", "_")
    if raw in {"crypto", "cryptocurrency", "digital_asset", "digitalasset"}:
        return "crypto"
    return "equity"


def _instrument_type(row: Mapping[str, Any], asset_class: str) -> str:
    """Return a cohort label without turning ETFs into a fourth trade lane."""
    explicit = _text(_first(row, "instrument_type", "security_type", "product_type", "asset_type", "asset_class")).upper()
    if asset_class == "crypto":
        return "CRYPTO"
    if explicit in {"ETF", "FUND", "EXCHANGE_TRADED_FUND"}:
        return "ETF"
    symbol = _text(_first(row, "symbol", "ticker")).upper()
    return "ETF" if symbol in CANONICAL_ETF_SYMBOL_REGISTRY else "EQUITY"


def _asset_classification_source(row: Mapping[str, Any], asset_class: str, instrument_type: str) -> str:
    """Keep ETF attribution deterministic and explainable across lanes."""
    if asset_class == "crypto":
        return _text(_first(row, "asset_classification_source", "asset_metadata_source")) or "candidate_or_broker_crypto_metadata"
    explicit = _text(_first(row, "instrument_type", "security_type", "product_type", "asset_type")).upper()
    if explicit in {"ETF", "FUND", "EXCHANGE_TRADED_FUND"}:
        return "candidate_or_broker_asset_metadata"
    symbol = _text(_first(row, "symbol", "ticker")).upper()
    if instrument_type == "ETF" and symbol in CANONICAL_ETF_SYMBOL_REGISTRY:
        return "existing_canonical_etf_registry"
    return _text(_first(row, "asset_classification_source", "asset_metadata_source")) or "candidate_equity_metadata"


def _normalized_style(row: Mapping[str, Any]) -> str:
    raw = _text(
        _first(
            row,
            "trade_style",
            "paper_entry_horizon_style",
            "trade_horizon_style",
            "best_horizon_style",
            "horizon_style",
            "horizon",
            "intended_horizon",
        )
    ).lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    if "scalp" in raw:
        return "scalp"
    if raw in {"day", "day_trade", "intraday", "same_session", "eod"} or "intraday" in raw:
        return "day_trade"
    if "crypto" in raw:
        return "crypto"
    return "swing_trade"


def _cohort(row: Mapping[str, Any], asset_class: str, style: str, instrument_type: str = "EQUITY") -> str:
    if style == "scalp":
        return "SCALP"
    if asset_class == "crypto":
        return "CRYPTO_SEPARATE"
    if instrument_type == "ETF":
        return "ETF_INTRADAY" if style == "day_trade" else "ETF_SWING"
    descriptor = " ".join(
        _text(_first(row, key)).lower()
        for key in ("archetype", "setup", "strategy", "catalyst", "theme")
    )
    if "breakout" in descriptor:
        return "BREAKOUT"
    if "momentum" in descriptor:
        return "EQUITY_MOMENTUM"
    if "earn" in descriptor:
        return "EARNINGS_CONTINUATION"
    return "EQUITY_DAY" if style == "day_trade" else "EQUITY_SWING"


def _timestamp(value: Any, default: str) -> str:
    return _text(value) or default


def apply_trade_lane_contract(
    row: Mapping[str, Any], *, legacy: bool = False, now: str | None = None
) -> Dict[str, Any]:
    """Return a copy with the immutable, execution-neutral lane contract.

    Explicit valid lane fields are retained for legacy records.  New candidate
    and entry rows are classified from their already-selected horizon metadata;
    this helper never changes candidate eligibility or ordering.
    """

    result: Dict[str, Any] = deepcopy(dict(row))
    timestamp = now or datetime.now(timezone.utc).isoformat()
    asset_class = _normalized_asset_class(result)
    instrument_type = _instrument_type(result, asset_class)
    asset_classification_source = _asset_classification_source(result, asset_class, instrument_type)
    style = _normalized_style(result)
    explicit_lane = _text(result.get("lane_id")).upper()

    if asset_class == "crypto":
        lane = LANE_CRYPTO
        style = "crypto" if style == "swing_trade" else style
    elif explicit_lane in VALID_LANES and not (explicit_lane == LANE_CRYPTO and asset_class != "crypto"):
        lane = explicit_lane
    elif style in {"scalp", "day_trade"}:
        lane = LANE_DAY
    else:
        lane = LANE_SWING

    if lane == LANE_CRYPTO:
        intended_horizon = _text(_first(result, "intended_horizon", "horizon")) or "crypto_multi_horizon"
        capital_book = "paper_crypto_separate"
        same_session_exit_required = False
        overnight_allowed = True
    elif lane == LANE_DAY:
        intended_horizon = "scalp" if style == "scalp" else "day_trade"
        capital_book = "paper_day_learning"
        # This is informational.  Existing exit controls remain the sole owner
        # of any actual close decision.
        same_session_exit_required = True
        overnight_allowed = False
    else:
        intended_horizon = _text(_first(result, "intended_horizon", "horizon")) or "swing_trade"
        capital_book = "paper_swing"
        same_session_exit_required = False
        overnight_allowed = True

    result.update(
        {
            "lane_id": lane,
            "trade_style": style,
            "intended_horizon": intended_horizon,
            "asset_class": asset_class,
            # ``asset_class`` remains the broker-compatible market class;
            # ``asset_type`` is the performance cohort requested by the
            # multi-lane operational reports.
            "asset_type": "crypto" if asset_class == "crypto" else instrument_type,
            "instrument_type": instrument_type,
            "asset_classification_source": asset_classification_source,
            "strategy_cohort": _text(result.get("strategy_cohort")) or _cohort(result, asset_class, style, instrument_type),
            "recommendation_id": _text(_first(result, "recommendation_id", "canonical_recommendation_id")),
            "candidate_id": _text(_first(result, "candidate_id", "decision_id", "opportunity_id")),
            "decision_timestamp": _timestamp(
                _first(result, "decision_timestamp", "recommendation_timestamp", "timestamp"), timestamp
            ),
            "eligibility_timestamp": _timestamp(
                _first(result, "eligibility_timestamp", "decision_timestamp", "timestamp"), timestamp
            ),
            "selection_timestamp": _timestamp(
                _first(result, "selection_timestamp", "decision_timestamp", "timestamp"), timestamp
            ),
            "expected_max_hold": _text(_first(result, "expected_max_hold", "expected_hold_window"))
            or ("same_session" if lane == LANE_DAY else "multi_session"),
            "same_session_exit_required": same_session_exit_required,
            "overnight_allowed": overnight_allowed,
            "capital_book_id": capital_book,
            # Future paper entries carry explicit owners.  Legacy rows remain
            # intentionally unowned so no lane worker can manage them.
            "position_owner": "" if legacy else lane,
            "exit_policy_owner": "" if legacy else lane,
            "source_ranking_version": _text(
                _first(result, "source_ranking_version", "ranking_version", "rankings_version")
            )
            or "existing_ranking",
            "source_policy_version": _text(_first(result, "source_policy_version", "policy_version"))
            or "existing_policy",
            "lane_assignment_source": "LEGACY_INFERRED" if legacy else "PRETRADE_EXPLICIT",
            "lane_assignment_confidence": 60 if legacy else 100,
            "lane_contract_version": "v1",
        }
    )
    return result


def lane_counts(rows: Iterable[Mapping[str, Any]], *, legacy: bool = False) -> Dict[str, int]:
    counts = {LANE_DAY: 0, LANE_SWING: 0, LANE_CRYPTO: 0}
    for row in rows:
        lane = apply_trade_lane_contract(row, legacy=legacy).get("lane_id")
        if lane in counts:
            counts[lane] += 1
    return counts


def safety_fields() -> Dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "paper_mode_verified": True,
        "broker_live_endpoint_allowed": False,
        "automatic_promotion_enabled": False,
        "learned_exit_execution_enabled": False,
        "human_review_required": True,
        "paper_entry_behavior_unchanged": True,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
    }


class AstraTradeLaneRegistryV1(CachedDiagnosticModule):
    """Cache-first registry summary; never creates or gates paper trades."""

    module_name = "astra_trade_lane_registry_v1"

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        candidates: List[Mapping[str, Any]] = list(statuses.get("pladeu_candidate_rows") or [])[:300]
        positions: List[Mapping[str, Any]] = list(statuses.get("pladeu_open_positions") or [])[:100]
        return {
            "suite": "Astra Trade Lane Registry V1",
            "status": "ok",
            "contract_version": "v1",
            "contract_fields": list(CONTRACT_FIELDS),
            "candidate_lane_counts": lane_counts(candidates),
            "open_position_lane_counts": lane_counts(positions, legacy=True),
            "lane_definitions": {
                LANE_DAY: "Equity and ETF intraday learning lane; scalp is a strategy cohort within DAY.",
                LANE_SWING: "Multi-session equity or ETF learning lane.",
                LANE_CRYPTO: "Separate crypto evidence lane; never pooled with equity capital.",
            },
            "allocation_lane_distinct_from_trade_lane": True,
            "registry_action": "metadata_only",
            **safety_fields(),
        }
