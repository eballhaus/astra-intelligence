"""Cache-first provider orchestration and data governance diagnostics.

This suite does not fetch data. It describes the canonical provider ownership,
freshness windows, anti-overlap rules, and bandwidth posture Astra should use
when existing workers acquire data.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any


PROVIDERS = (
    "FMP",
    "ALPACA",
    "FRED",
    "FINNHUB",
    "POLYGON",
    "TWELVEDATA",
    "ALPHAVANTAGE",
    "EODHD",
    "MORALIS",
    "NASDAQ",
    "SIMFIN",
    "DATAJOCKEY",
)


OWNERSHIP_MATRIX: dict[str, dict[str, Any]] = {
    "historical_prices": {"primary": "FMP", "secondary": ["FINNHUB"], "frequency": "daily"},
    "fundamentals": {"primary": "FMP", "secondary": ["ALPHAVANTAGE", "SIMFIN"], "frequency": "daily"},
    "financial_statements": {"primary": "FMP", "secondary": ["SIMFIN"], "frequency": "daily"},
    "earnings": {"primary": "FMP", "secondary": ["FINNHUB"], "frequency": "daily"},
    "company_profiles": {"primary": "FMP", "secondary": ["FINNHUB"], "frequency": "daily"},
    "sector_classifications": {"primary": "FMP", "secondary": ["NASDAQ"], "frequency": "daily"},
    "positions": {"primary": "ALPACA", "secondary": [], "frequency": "1-5m"},
    "orders": {"primary": "ALPACA", "secondary": [], "frequency": "1-5m"},
    "executions": {"primary": "ALPACA", "secondary": [], "frequency": "1-5m"},
    "account_truth": {"primary": "ALPACA", "secondary": [], "frequency": "1-5m"},
    "paper_pl": {"primary": "ALPACA", "secondary": [], "frequency": "1-5m"},
    "macro_regime": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "fed_intelligence": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "treasury_yields": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "inflation": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "unemployment": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "gdp": {"primary": "FRED", "secondary": [], "frequency": "daily"},
    "news": {"primary": "FINNHUB", "secondary": [], "frequency": "15-30m"},
    "catalysts": {"primary": "FINNHUB", "secondary": [], "frequency": "15-30m"},
    "sentiment": {"primary": "FINNHUB", "secondary": [], "frequency": "15-30m"},
    "insider_activity": {"primary": "FINNHUB", "secondary": [], "frequency": "daily"},
    "crypto_context": {"primary": "MORALIS", "secondary": [], "frequency": "15-30m"},
    "quote_validation": {"primary": "FMP", "secondary": ["POLYGON", "TWELVEDATA", "EODHD"], "frequency": "15-30m"},
    "end_of_day_validation": {"primary": "EODHD", "secondary": ["FMP"], "frequency": "daily"},
    "fundamentals_validation": {"primary": "ALPHAVANTAGE", "secondary": ["SIMFIN"], "frequency": "weekly"},
}


PROVIDER_PURPOSES: dict[str, dict[str, Any]] = {
    "FMP": {
        "primary_categories": [
            "historical_prices",
            "fundamentals",
            "financial_statements",
            "earnings",
            "company_profiles",
            "sector_classifications",
        ],
        "forbidden_categories": ["positions", "orders", "executions", "account_truth", "paper_pl"],
    },
    "ALPACA": {
        "primary_categories": ["positions", "orders", "executions", "account_truth", "paper_pl"],
        "forbidden_categories": ["market_breadth", "market_intelligence", "sector_rotation", "macro_regime"],
    },
    "FRED": {
        "primary_categories": ["macro_regime", "fed_intelligence", "treasury_yields", "inflation", "unemployment", "gdp"],
        "forbidden_categories": ["positions", "orders", "executions", "broker_truth"],
    },
    "FINNHUB": {
        "primary_categories": ["news", "catalysts", "sentiment", "insider_activity"],
        "forbidden_categories": ["broker_truth", "orders", "positions"],
    },
    "MORALIS": {
        "primary_categories": ["crypto_context"],
        "forbidden_categories": ["stock_orders", "stock_positions", "broker_truth"],
    },
    "POLYGON": {"primary_categories": [], "secondary_categories": ["quote_validation"]},
    "TWELVEDATA": {"primary_categories": [], "secondary_categories": ["quote_validation", "volume_validation"]},
    "EODHD": {"primary_categories": [], "secondary_categories": ["end_of_day_validation", "quote_validation"]},
    "ALPHAVANTAGE": {"primary_categories": [], "secondary_categories": ["fundamentals_validation"]},
    "NASDAQ": {"primary_categories": [], "secondary_categories": ["sector_classification_support"]},
    "SIMFIN": {"primary_categories": [], "secondary_categories": ["specialized_fundamentals"]},
    "DATAJOCKEY": {"primary_categories": [], "secondary_categories": ["specialized_data_if_present"]},
}


INTELLIGENCE_FEEDING_PRIORITIES = [
    {"system": "portfolio_intelligence", "priority": 1, "primary_owner": "ALPACA", "feed": "broker truth plus cached performance"},
    {"system": "exit_intelligence", "priority": 2, "primary_owner": "ALPACA", "feed": "paper outcomes plus cached lifecycle evidence"},
    {"system": "sector_rotation", "priority": 3, "primary_owner": "FMP", "feed": "cached sector classifications and ETF context"},
    {"system": "market_breadth", "priority": 4, "primary_owner": "FMP", "feed": "cached index and breadth context"},
    {"system": "macro_fed_intelligence", "priority": 5, "primary_owner": "FRED", "feed": "cached macro and Fed series"},
]


SAFETY_FLAGS = {
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "ranking_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "paper_execution_changed": False,
    "automatic_exits_enabled": False,
    "automatic_promotions_enabled": False,
    "dashboard_provider_calls_used": 0,
    "dashboard_llm_calls_used": 0,
    "api_calls_used": 0,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _key_present(provider: str) -> bool:
    p = str(provider or "").upper()
    env_map = {
        "FMP": ["FMP_API_KEY"],
        "ALPACA": ["APCA_API_KEY_ID", "ALPACA_API_KEY", "ALPACA_API_KEY_ID"],
        "FRED": ["FRED_API_KEY"],
        "FINNHUB": ["FINNHUB_API_KEY"],
        "POLYGON": ["POLYGON_API_KEY"],
        "TWELVEDATA": ["TWELVEDATA_API_KEY"],
        "ALPHAVANTAGE": ["ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY"],
        "EODHD": ["EODHD_API_KEY"],
        "MORALIS": ["MORALIS_API_KEY"],
        "NASDAQ": ["NASDAQ_API_KEY"],
        "SIMFIN": ["SIMFIN_API_KEY"],
        "DATAJOCKEY": ["DATAJOCKEY_API_KEY"],
    }
    return any(bool(str(os.getenv(name, "")).strip()) for name in env_map.get(p, []))


def _score_provider(provider: str, capability_item: dict[str, Any], manager_item: dict[str, Any]) -> dict[str, Any]:
    p = str(provider or "").upper()
    calls = _to_float(manager_item.get("calls"), _to_float(capability_item.get("calls_total"), 0.0))
    errors = _to_float(manager_item.get("errors"), 0.0)
    key = bool(capability_item.get("key_present", False) or _key_present(p))
    enabled = bool(capability_item.get("enabled", False) or key)
    healthy = bool(manager_item.get("healthy", False))
    status = str(capability_item.get("last_status") or "skipped").lower()
    freshness_seconds = _to_float(((capability_item.get("freshness") or {}).get("data_freshness_seconds")), 999999.0)
    health_score = 70.0 if healthy else (55.0 if status in {"success", "partial"} else (35.0 if enabled else 15.0))
    freshness_score = 100.0 if freshness_seconds <= 300 else (75.0 if freshness_seconds <= 1800 else (45.0 if freshness_seconds < 999999 else 20.0))
    availability_score = 85.0 if key and enabled else (45.0 if enabled else 20.0)
    utilization_score = max(0.0, min(100.0, 100.0 - min(100.0, calls * 2.0)))
    trust_score = {
        "ALPACA": 95.0,
        "FMP": 88.0,
        "FRED": 90.0,
        "FINNHUB": 82.0,
        "MORALIS": 72.0,
        "POLYGON": 70.0,
        "TWELVEDATA": 68.0,
        "EODHD": 66.0,
        "ALPHAVANTAGE": 64.0,
        "NASDAQ": 55.0,
        "SIMFIN": 58.0,
        "DATAJOCKEY": 45.0,
    }.get(p, 50.0)
    dependency_score = 55.0 if p in {"FMP", "ALPACA", "FRED", "FINNHUB"} else 35.0
    confidence_score = round((health_score * 0.22) + (freshness_score * 0.18) + (availability_score * 0.2) + (trust_score * 0.25) + (utilization_score * 0.15), 2)
    overall = round((confidence_score * 0.7) + (dependency_score * 0.3), 2)
    return {
        "provider_name": p,
        "installed": True,
        "configured": bool(key),
        "enabled": bool(enabled),
        "api_key_present": bool(key),
        "healthy": bool(healthy or status in {"success", "partial"}),
        "health_score": round(health_score, 2),
        "confidence_score": confidence_score,
        "freshness_score": round(freshness_score, 2),
        "trust_score": round(trust_score, 2),
        "utilization_score": round(utilization_score, 2),
        "availability_score": round(availability_score, 2),
        "dependency_score": round(dependency_score, 2),
        "overall_provider_score": overall,
        "calls_total": int(calls),
        "errors_total": int(errors),
        "primary_categories": list((PROVIDER_PURPOSES.get(p) or {}).get("primary_categories") or []),
        "secondary_categories": list((PROVIDER_PURPOSES.get(p) or {}).get("secondary_categories") or []),
        "forbidden_categories": list((PROVIDER_PURPOSES.get(p) or {}).get("forbidden_categories") or []),
    }


class AstraProviderOrchestrationDataGovernanceV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = state_dir

    def status(
        self,
        *,
        statuses: dict[str, Any] | None = None,
        provider_capability: dict[str, Any] | None = None,
        provider_diagnostics: dict[str, Any] | None = None,
        provider_usage: dict[str, Any] | None = None,
        manager_rows: list[dict[str, Any]] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        del force
        status_map = dict(statuses or {})
        capability = dict(provider_capability or status_map.get("provider_capability_audit") or {})
        diagnostics = dict(provider_diagnostics or status_map.get("provider_diagnostics") or {})
        usage = dict(provider_usage or {})
        manager_map = {
            str((row or {}).get("provider", "")).upper(): dict(row or {})
            for row in list(manager_rows or [])
            if isinstance(row, dict)
        }
        capability_map = {
            str((row or {}).get("provider_name", "")).upper(): dict(row or {})
            for row in list(capability.get("provider_items") or [])
            if isinstance(row, dict)
        }

        provider_scores = [
            _score_provider(provider, capability_map.get(provider, {}), manager_map.get(provider, {}))
            for provider in PROVIDERS
        ]
        providers_configured = sum(1 for row in provider_scores if row["configured"])
        providers_healthy = sum(1 for row in provider_scores if row["healthy"])
        overlap_rules = [
            {
                "category": category,
                "primary_owner": rule["primary"],
                "secondary_owner": list(rule.get("secondary") or []),
                "rule": "primary_success_suppresses_backups",
                "backup_allowed_when": [
                    "provider_unavailable",
                    "provider_stale",
                    "provider_unhealthy",
                    "provider_rate_limited",
                    "provider_confidence_below_threshold",
                    "provider_missing_data",
                ],
                "duplicate_pull_allowed": False,
            }
            for category, rule in OWNERSHIP_MATRIX.items()
        ]
        target_monthly_gb = {"target_low_gb": 5.0, "target_high_gb": 10.0, "soft_limit_gb": 15.0, "warning_gb": 25.0, "throttle_gb": 35.0, "emergency_stop_gb": 45.0}
        used_gb = _to_float(usage.get("estimated_used_today_gb"), _to_float(usage.get("fmp_estimated_used_today_gb"), 0.0))
        projected_monthly = round(used_gb * 30.0, 4)
        if projected_monthly >= target_monthly_gb["emergency_stop_gb"]:
            bandwidth_status = "emergency_stop_required"
        elif projected_monthly >= target_monthly_gb["throttle_gb"]:
            bandwidth_status = "throttle_required"
        elif projected_monthly >= target_monthly_gb["warning_gb"]:
            bandwidth_status = "warning"
        elif projected_monthly >= target_monthly_gb["soft_limit_gb"]:
            bandwidth_status = "soft_limit_watch"
        else:
            bandwidth_status = "efficient"

        fmp_score = next((row for row in provider_scores if row["provider_name"] == "FMP"), {})
        fred_score = next((row for row in provider_scores if row["provider_name"] == "FRED"), {})
        finnhub_score = next((row for row in provider_scores if row["provider_name"] == "FINNHUB"), {})
        alpaca_score = next((row for row in provider_scores if row["provider_name"] == "ALPACA"), {})
        moralis_score = next((row for row in provider_scores if row["provider_name"] == "MORALIS"), {})

        return {
            "suite": "Astra Intelligent Provider Orchestration & Data Governance Suite V1",
            "status": "ok",
            "enabled": True,
            "version": "1.0.0",
            "mode": "cache_first_provider_orchestration_governance",
            "generated_at_utc": _now_iso(),
            "dashboard_reads_cache_only": True,
            "no_new_providers_added": True,
            "provider_ownership_matrix": OWNERSHIP_MATRIX,
            "provider_utilization_matrix": provider_scores,
            "provider_health_matrix": provider_scores,
            "anti_overlap_engine": {
                "enabled": True,
                "duplicate_quote_pulls_allowed": False,
                "duplicate_earnings_pulls_allowed": False,
                "duplicate_macro_pulls_allowed": False,
                "duplicate_fundamentals_pulls_allowed": False,
                "duplicate_news_pulls_allowed": False,
                "duplicate_sector_pulls_allowed": False,
                "primary_success_suppresses_backups": True,
                "rules": overlap_rules,
            },
            "data_freshness_engine": {
                "real_time_1_5m": ["positions", "orders", "paper_pl", "open_trades"],
                "intraday_15_30m": ["quotes", "volatility", "market_breadth", "sector_leadership", "risk_appetite"],
                "daily": ["fundamentals", "earnings", "macro", "fed", "market_pillars"],
                "weekly": ["correlations", "archetypes", "deep_learning", "historical_intelligence", "knowledge_graph_optimization"],
                "dashboard_direct_provider_calls_allowed": False,
            },
            "provider_confidence_engine": {
                "providers_scored": len(provider_scores),
                "providers_configured": providers_configured,
                "providers_healthy": providers_healthy,
                "average_overall_provider_score": round(sum(row["overall_provider_score"] for row in provider_scores) / max(1, len(provider_scores)), 2),
            },
            "intelligent_data_acquisition_orchestrator_v2": {
                "status": "active_policy_only",
                "uses_existing_providers_only": True,
                "feed_priorities": INTELLIGENCE_FEEDING_PRIORITIES,
                "duplicate_evidence_prevention": True,
                "cache_first": True,
            },
            "cio_intelligence_maturation": {
                "portfolio_intelligence_owner": "ALPACA",
                "exit_intelligence_owner": "ALPACA",
                "sector_rotation_owner": "FMP",
                "market_breadth_owner": "FMP",
                "macro_intelligence_owner": "FRED",
                "fed_intelligence_owner": "FRED",
                "news_catalyst_owner": "FINNHUB",
                "crypto_context_owner": "MORALIS",
                "weaknesses_improved": [
                    "provider_ownership_clarity",
                    "duplicate_provider_pull_suppression_policy",
                    "provider_confidence_scoring",
                    "cio_data_owner_visibility",
                    "dashboard_cache_only_contract",
                ],
            },
            "bandwidth_governance": {
                **target_monthly_gb,
                "target_utilization_pct": "20-40",
                "reserve_pct": "60-80",
                "estimated_used_today_gb": round(used_gb, 6),
                "projected_monthly_usage_gb": projected_monthly,
                "bandwidth_status": bandwidth_status,
                "aggressive_consumption_allowed": False,
                "efficiency_first": True,
            },
            "provider_owner_readiness": {
                "fmp_ready_for_core_market_data": bool(fmp_score.get("configured", False)),
                "alpaca_ready_for_broker_truth": bool(alpaca_score.get("configured", False)),
                "fred_ready_for_macro": bool(fred_score.get("configured", False)),
                "finnhub_ready_for_news_catalysts": bool(finnhub_score.get("configured", False)),
                "moralis_ready_for_crypto_context": bool(moralis_score.get("configured", False)),
            },
            "registered_system": {
                "system_name": "astra_provider_orchestration_data_governance_v1",
                "owner": "Astra Resource Manager / CIO Intelligence",
                "purpose": "Provider ownership, freshness, overlap, confidence, and bandwidth governance",
                "inputs": ["provider_capability_audit_cache", "provider_router_diagnostics", "api_call_manager_summary"],
                "outputs": ["provider_ownership_matrix", "provider_health_matrix", "bandwidth_governance", "cio_intelligence_maturation"],
                "dependencies": ["ProviderRouter", "api_call_manager", "unified_learning_diagnostics_v1"],
                "health_status": "healthy",
                "enabled": True,
                "api_budget": "cache_only_diagnostics",
                "bandwidth_budget": "5-10gb_target_15gb_soft_limit",
            },
            "summary": {
                "primary_provider_model": "single_owner_per_category_with_backup_only_validation",
                "best_configured_owner": max(provider_scores, key=lambda row: row["overall_provider_score"])["provider_name"] if provider_scores else "none",
                "highest_priority_improvement": "feed CIO intelligence from canonical owners without duplicate provider pulls",
                "dashboard_contract": "cache_only_no_provider_or_llm_calls",
            },
            **SAFETY_FLAGS,
        }
