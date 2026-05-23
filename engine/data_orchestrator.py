"""Canonical live data orchestration for ranking and top-buy pipelines."""

from __future__ import annotations

import time
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import UTC, datetime
from typing import Iterable

from engine.provider_router import ProviderRouter
from engine.ranking_engine import RankingEngine
try:
    from engine.edge_development_suite_v1 import EdgeDevelopmentSuiteV1
except Exception:  # pragma: no cover - additive shadow decorator
    EdgeDevelopmentSuiteV1 = None  # type: ignore[assignment]
try:
    from engine.trade_management_portfolio_intelligence_v1 import TradeManagementPortfolioIntelligenceV1
except Exception:  # pragma: no cover - additive shadow decorator
    TradeManagementPortfolioIntelligenceV1 = None  # type: ignore[assignment]
try:
    from engine.adaptive_learning_infrastructure_v1 import AdaptiveLearningInfrastructureV1
except Exception:  # pragma: no cover - additive shadow decorator
    AdaptiveLearningInfrastructureV1 = None  # type: ignore[assignment]

_router = ProviderRouter()
_ranker = RankingEngine()
_edge_development_suite = EdgeDevelopmentSuiteV1(state_dir="state") if EdgeDevelopmentSuiteV1 is not None else None
_trade_management_portfolio_suite = (
    TradeManagementPortfolioIntelligenceV1(state_dir="state") if TradeManagementPortfolioIntelligenceV1 is not None else None
)
_adaptive_learning_infrastructure_suite = (
    AdaptiveLearningInfrastructureV1(state_dir="state") if AdaptiveLearningInfrastructureV1 is not None else None
)
_TEMP_STRATEGY_ENABLED = str(os.getenv("ASTRA_TEMP_PROVIDER_STRATEGY_V1", "1")).strip().lower() in {"1", "true", "yes", "on"}
_TEMP_FMP_REST_DISABLED = str(os.getenv("ASTRA_TEMP_FMP_REST_DISABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
_TEMP_FMP_WS_MONITOR_ONLY = str(os.getenv("ASTRA_TEMP_FMP_WEBSOCKET_MONITOR_ONLY", "1")).strip().lower() in {"1", "true", "yes", "on"}
try:
    _TEMP_DISCOVERY_CACHE_AGE = max(10.0, float(os.getenv("ASTRA_TEMP_DISCOVERY_CACHE_MAX_AGE_SECONDS", "45")))
except Exception:
    _TEMP_DISCOVERY_CACHE_AGE = 45.0
try:
    _RANKING_FETCH_WORKERS = max(1, min(8, int(float(os.getenv("ASTRA_RANKING_FETCH_WORKERS", "6")))))
except Exception:
    _RANKING_FETCH_WORKERS = 6
try:
    _RANKING_FETCH_DEADLINE_SECONDS = max(3.0, min(18.0, float(os.getenv("ASTRA_RANKING_FETCH_DEADLINE_SECONDS", "10"))))
except Exception:
    _RANKING_FETCH_DEADLINE_SECONDS = 10.0
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
    "provider_role_policy": {},
    "provider_success_count_by_provider": {},
    "provider_success_rate_by_provider": {},
    "provider_attempt_count": 0,
    "provider_success_count": 0,
    "fmp_operating_mode": "conserve_rest",
    "fmp_conserve_mode_active": True,
    "fmp_rest_hard_limit_enabled": True,
    "fmp_websocket_allowed": True,
    "fmp_websocket_shortlist_only": True,
    "broad_discovery_reduced_in_conserve_mode": True,
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


def _quote_to_rank_row(sym: str, quote: dict, asset_type: str, now_iso: str) -> tuple[dict | None, dict]:
    attempted = [str(p or "").upper() for p in (quote.get("attempted_providers") or []) if str(p or "").strip()]
    provider_used = str(quote.get("provider_used") or "none").upper()
    reason = str(quote.get("data_unavailable_reason") or "")
    price = _safe_float(quote.get("price"), 0.0)
    prev_close = _safe_float(quote.get("prev_close"), 0.0)
    valid_quote = bool(quote.get("valid_quote", False) and price > 0)
    meta = {
        "symbol": sym,
        "asset_type": asset_type,
        "attempted": attempted,
        "provider_used": provider_used,
        "reason": reason,
        "valid_quote": valid_quote,
    }
    if not valid_quote:
        return None, meta

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
            "previous_close": _safe_float(quote.get("previous_close"), prev_close),
            "open": _safe_float(quote.get("open"), 0.0),
            "high": _safe_float(quote.get("high"), 0.0),
            "low": _safe_float(quote.get("low"), 0.0),
            "volume": _safe_float(quote.get("volume"), 0.0),
            "change": _safe_float(quote.get("change"), 0.0),
            "change_percent": _safe_float(quote.get("change_percent"), 0.0),
            "change_pct": round(((price / prev_close) - 1.0) * 100.0, 4) if prev_close > 0 else 0.0,
            "provider_used": provider_used.lower() if provider_used and provider_used != "NONE" else "none",
            "provider_agreement": round(_safe_float(quote.get("provider_agreement"), 0.0), 4),
            "provider_name": str(quote.get("provider_name") or provider_used),
            "provider_confidence": _safe_float(quote.get("provider_confidence"), 0.0),
            "data_quality_score": _safe_float(quote.get("data_quality_score"), 0.0),
            "quote_quality": str(quote.get("quote_quality") or ("live" if not quote.get("cache_hit") else "cached")),
            "quote_age_seconds": round(_safe_float(quote.get("quote_age_seconds"), 0.0), 2),
            "freshness_seconds": round(_safe_float(quote.get("freshness_seconds"), _safe_float(quote.get("quote_age_seconds"), 0.0)), 2),
            "quote_timestamp": quote.get("quote_timestamp"),
            "quote_enriched": bool(quote.get("quote_enriched", False)),
            "quote_enrichment_sources": list(quote.get("quote_enrichment_sources") or []),
            "enriched_previous_close_source": str(quote.get("enriched_previous_close_source") or ""),
            "enriched_volume_source": str(quote.get("enriched_volume_source") or ""),
            "enriched_history_source": str(quote.get("enriched_history_source") or ""),
            "enriched_signal_ready": bool(quote.get("enriched_signal_ready", False)),
            "enriched_signal_limitations": list(quote.get("enriched_signal_limitations") or []),
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
    return row, meta


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
    provider_success = defaultdict(int)
    rate_limited = set()
    stock_universe = 0
    stock_valid_quotes = 0
    crypto_valid_quotes = 0
    tier1 = {"FMP", "FINNHUB", "TWELVEDATA", "POLYGON"}

    def _fetch_symbol(sym: str) -> tuple[dict | None, dict]:
        asset_type = "crypto" if _is_crypto(sym) else "stock"
        quote = _router.get_quote(
            sym,
            asset_type=asset_type,
            batch_id=cycle_id,
            use_selective_backups=False,
            cache_max_age_seconds=_TEMP_DISCOVERY_CACHE_AGE if _TEMP_STRATEGY_ENABLED else None,
        )
        return _quote_to_rank_row(sym, quote, asset_type, now_iso)

    def _record_result(row: dict | None, meta: dict) -> None:
        nonlocal stock_universe, stock_valid_quotes, crypto_valid_quotes
        asset_type = str(meta.get("asset_type") or "stock")
        if asset_type == "stock":
            stock_universe += 1
        attempted = list(meta.get("attempted") or [])
        provider_used = str(meta.get("provider_used") or "none").upper()
        reason = str(meta.get("reason") or "")
        valid_quote = bool(meta.get("valid_quote", False))
        for provider in attempted:
            provider_attempts[provider] += 1
            if provider in tier1:
                tier1_attempts[provider] += 1

        if provider_used and provider_used != "NONE":
            provider_activity[provider_used] += 1
        if "rate" in reason.lower() and "limit" in reason.lower():
            if provider_used and provider_used != "NONE":
                rate_limited.add(provider_used)
            if attempted:
                rate_limited.update([p for p in attempted if p])

        if not valid_quote:
            skip_reasons[reason or "invalid_quote"] += 1
            return
        if provider_used and provider_used != "NONE":
            provider_success[provider_used] += 1
        if asset_type == "stock":
            stock_valid_quotes += 1
        else:
            crypto_valid_quotes += 1

        if row:
            rows.append(row)

    worker_count = min(_RANKING_FETCH_WORKERS, max(1, len(symbol_list)))
    pool = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="astra-rank-quote")
    futures = {pool.submit(_fetch_symbol, sym): sym for sym in symbol_list}
    try:
        for fut in as_completed(futures, timeout=_RANKING_FETCH_DEADLINE_SECONDS):
            try:
                row, meta = fut.result(timeout=0.05)
            except Exception as exc:
                sym = futures.get(fut, "")
                meta = {
                    "symbol": sym,
                    "asset_type": "crypto" if _is_crypto(sym) else "stock",
                    "attempted": [],
                    "provider_used": "NONE",
                    "reason": f"quote_fetch_exception:{str(exc)[:80]}",
                    "valid_quote": False,
                }
                row = None
            _record_result(row, meta)
    except TimeoutError:
        for fut, sym in futures.items():
            if fut.done():
                continue
            fut.cancel()
            _record_result(
                None,
                {
                    "symbol": sym,
                    "asset_type": "crypto" if _is_crypto(sym) else "stock",
                    "attempted": [],
                    "provider_used": "NONE",
                    "reason": "ranking_fetch_deadline_exceeded",
                    "valid_quote": False,
                },
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if _edge_development_suite is not None and hasattr(_edge_development_suite, "decorate_candidates"):
        try:
            rows = list(_edge_development_suite.decorate_candidates(rows) or rows)
        except Exception:
            pass
    if _trade_management_portfolio_suite is not None and hasattr(_trade_management_portfolio_suite, "decorate_candidates"):
        try:
            rows = list(_trade_management_portfolio_suite.decorate_candidates(rows) or rows)
        except Exception:
            pass
    if _adaptive_learning_infrastructure_suite is not None and hasattr(_adaptive_learning_infrastructure_suite, "decorate_candidates"):
        try:
            rows = list(_adaptive_learning_infrastructure_suite.decorate_candidates(rows) or rows)
        except Exception:
            pass

    provider_success_rate = {}
    for provider_name, attempts in provider_attempts.items():
        provider_success_rate[provider_name] = round(
            (int(provider_success.get(provider_name, 0)) / max(1, int(attempts))) * 100.0,
            4,
        )
    diag = _router.diagnostics() if hasattr(_router, "diagnostics") else {}
    role_policy = dict(diag.get("provider_role_matrix") or {})
    _RANKING_META.update(
        {
            "skip_reasons_counts": dict(skip_reasons),
            "provider_attempt_count_by_provider": dict(provider_attempts),
            "tier1_provider_attempt_count_by_provider": dict(tier1_attempts),
            "provider_success_count_by_provider": dict(provider_success),
            "provider_success_rate_by_provider": dict(provider_success_rate),
            "provider_attempt_count": int(sum(provider_attempts.values())),
            "provider_success_count": int(sum(provider_success.values())),
            "fmp_provider_activity": {
                "attempt_count": int(provider_attempts.get("FMP", 0)),
                "used_count": int(provider_activity.get("FMP", 0)),
                "rate_limited": bool("FMP" in rate_limited),
            },
            "provider_role_policy": role_policy,
            "fmp_operating_mode": "temporary_conserve_rest" if (_TEMP_STRATEGY_ENABLED and _TEMP_FMP_REST_DISABLED) else "normal",
            "fmp_conserve_mode_active": bool(_TEMP_STRATEGY_ENABLED and _TEMP_FMP_REST_DISABLED),
            "fmp_rest_hard_limit_enabled": bool(_TEMP_STRATEGY_ENABLED and _TEMP_FMP_REST_DISABLED),
            "fmp_websocket_allowed": bool(_TEMP_STRATEGY_ENABLED and _TEMP_FMP_WS_MONITOR_ONLY),
            "fmp_websocket_shortlist_only": bool(_TEMP_STRATEGY_ENABLED and _TEMP_FMP_WS_MONITOR_ONLY),
            "broad_discovery_reduced_in_conserve_mode": bool(_TEMP_STRATEGY_ENABLED),
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
