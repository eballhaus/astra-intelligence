"""Canonical live data orchestration for ranking and top-buy pipelines."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

from engine.provider_router import ProviderRouter
from engine.ranking_engine import RankingEngine

_router = ProviderRouter()
_ranker = RankingEngine()
_RANKING_META = {
    "skip_reasons_counts": {},
    "provider_attempt_count_by_provider": {},
    "tier1_provider_attempt_count_by_provider": {},
    "fmp_provider_activity": {},
    "rate_limited_providers": [],
    "live_buy_universe_size": 0,
    "live_buy_valid_quote_count": 0,
    "crypto_live_buy_valid_quote_count": 0,
    "final_ranked_count": 0,
    "last_updated_utc": None,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _is_crypto(symbol: str) -> bool:
    return str(symbol or "").upper() in {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"}


def _momentum_and_volatility(price: float, prev_close: float) -> tuple[float, float]:
    if price <= 0 or prev_close <= 0:
        return 0.0, 0.0
    change_pct = ((price / prev_close) - 1.0) * 100.0
    momentum_weight = max(-1.0, min(1.0, change_pct / 10.0))
    volatility_factor = max(0.0, min(8.0, abs(change_pct) * 0.35 + 0.15))
    return momentum_weight, volatility_factor


def _normalize_symbols(symbols: Iterable[str] | None) -> list[str]:
    out = []
    seen = set()
    for raw in symbols or []:
        sym = str(raw or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def fetch_live_data(symbols=None):
    symbol_list = _normalize_symbols(symbols)
    if not symbol_list:
        _RANKING_META.update(
            {
                "skip_reasons_counts": {"no_symbols_supplied": 1},
                "provider_attempt_count_by_provider": {},
                "tier1_provider_attempt_count_by_provider": {},
                "fmp_provider_activity": {},
                "rate_limited_providers": [],
                "live_buy_universe_size": 0,
                "live_buy_valid_quote_count": 0,
                "crypto_live_buy_valid_quote_count": 0,
                "final_ranked_count": 0,
                "last_updated_utc": _now_iso(),
            }
        )
        return []

    now_iso = _now_iso()
    cycle_id = f"live_rank_{int(time.time() // 20)}"
    rows = []
    skip_reasons = defaultdict(int)
    provider_attempts = defaultdict(int)
    tier1_attempts = defaultdict(int)
    provider_activity = defaultdict(int)
    rate_limited = set()
    stock_universe = 0
    stock_valid_quotes = 0
    crypto_valid_quotes = 0
    tier1 = {"FMP", "FINNHUB", "TWELVEDATA", "POLYGON"}

    for sym in symbol_list:
        asset_type = "crypto" if _is_crypto(sym) else "stock"
        if asset_type == "stock":
            stock_universe += 1

        quote = _router.get_quote(
            sym,
            asset_type=asset_type,
            batch_id=cycle_id,
            use_selective_backups=True,
        )
        attempted = [str(p or "").upper() for p in (quote.get("attempted_providers") or []) if str(p or "").strip()]
        for provider in attempted:
            provider_attempts[provider] += 1
            if provider in tier1:
                tier1_attempts[provider] += 1

        provider_used = str(quote.get("provider_used") or "none").upper()
        if provider_used and provider_used != "NONE":
            provider_activity[provider_used] += 1
        reason = str(quote.get("data_unavailable_reason") or "")
        if "rate" in reason.lower() and "limit" in reason.lower():
            if provider_used and provider_used != "NONE":
                rate_limited.add(provider_used)
            if attempted:
                rate_limited.update([p for p in attempted if p])

        price = _safe_float(quote.get("price"), 0.0)
        prev_close = _safe_float(quote.get("prev_close"), 0.0)
        valid_quote = bool(quote.get("valid_quote", False) and price > 0)
        if not valid_quote:
            skip_reasons[reason or "invalid_quote"] += 1
            continue
        if asset_type == "stock":
            stock_valid_quotes += 1
        else:
            crypto_valid_quotes += 1

        momentum_weight, volatility_factor = _momentum_and_volatility(price, prev_close)
        intel = _ranker.evaluate_symbol(
            symbol=sym,
            price=price,
            provider_agreement=_safe_float(quote.get("provider_agreement"), 0.0),
            volatility_factor=volatility_factor,
            momentum_weight=momentum_weight,
        )
        row = dict(intel or {})
        row.update(
            {
                "symbol": sym,
                "asset_type": asset_type,
                "price": price,
                "prev_close": prev_close,
                "change_pct": round(((price / prev_close) - 1.0) * 100.0, 4) if prev_close > 0 else 0.0,
                "provider_used": provider_used.lower() if provider_used and provider_used != "NONE" else "none",
                "provider_agreement": round(_safe_float(quote.get("provider_agreement"), 0.0), 4),
                "quote_quality": str(quote.get("quote_quality") or ("live" if not quote.get("cache_hit") else "cached")),
                "quote_age_seconds": round(_safe_float(quote.get("quote_age_seconds"), 0.0), 2),
                "valid_quote": True,
                "trusted_quote_for_buys": True,
                "live_buy_universe": bool(asset_type == "stock"),
                "data_unavailable_reason": None,
                "provider_attempt_count": int(quote.get("provider_attempt_count", len(attempted)) or 0),
                "provider_success_count": int(quote.get("provider_success_count", 1) or 0),
                "attempted_providers": attempted,
                "action": row.get("action") or row.get("prediction") or "Hold",
                "timestamp": now_iso,
            }
        )
        rows.append(row)

    _RANKING_META.update(
        {
            "skip_reasons_counts": dict(skip_reasons),
            "provider_attempt_count_by_provider": dict(provider_attempts),
            "tier1_provider_attempt_count_by_provider": dict(tier1_attempts),
            "fmp_provider_activity": {
                "attempt_count": int(provider_attempts.get("FMP", 0)),
                "used_count": int(provider_activity.get("FMP", 0)),
                "rate_limited": bool("FMP" in rate_limited),
            },
            "rate_limited_providers": sorted(rate_limited),
            "live_buy_universe_size": int(stock_universe),
            "live_buy_valid_quote_count": int(stock_valid_quotes),
            "crypto_live_buy_valid_quote_count": int(crypto_valid_quotes),
            "final_ranked_count": int(len(rows)),
            "last_updated_utc": now_iso,
        }
    )
    return rows


def get_ranking_snapshot_meta():
    return dict(_RANKING_META)
