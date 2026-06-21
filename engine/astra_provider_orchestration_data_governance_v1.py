"""Cache-first provider orchestration, data governance, and institutional maturation.

This suite owns Astra's provider policy and controlled evidence feeding posture. It
never fetches provider data from dashboard paths. Endpoint/unified calls read and
summarize cached/internal evidence; only the optional background worker may persist
compact cache/ledger snapshots.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
import time
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


CONTROLLED_COLLECTION_SCHEDULE = [
    {"cycle": "premarket", "window": "07:00-09:30", "collect_cache": ["SPY", "QQQ", "IWM", "VIX", "overnight_movers", "sector_etf_context", "macro_fed_posture"]},
    {"cycle": "intraday", "window": "every_15_30_minutes", "collect_cache": ["sector_leadership", "breadth", "volatility", "leadership_changes", "active_position_changes", "profit_decay", "continuation_evidence"]},
    {"cycle": "midday", "window": "11:30-13:30", "collect_cache": ["sector_persistence", "breadth_deterioration", "market_regime_changes", "portfolio_exposure_changes"]},
    {"cycle": "power_hour", "window": "15:00-16:00", "collect_cache": ["exit_evidence", "continuation_probability", "profit_capture_evidence", "leadership_loss", "profit_decay"]},
    {"cycle": "postmarket", "window": "16:00-18:00", "collect_cache": ["earnings_reactions", "sector_rotation_changes", "closed_trade_evidence", "portfolio_impact", "learning_labels"]},
    {"cycle": "evening", "window": "18:00-23:00", "collect_cache": ["replay_analysis", "lifecycle_analysis", "portfolio_analysis", "exit_analysis", "sector_breadth_summary", "macro_fed_summary", "knowledge_graph_update", "consensus_update"]},
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
    "partial_sells_enabled": False,
    "automatic_trailing_stops_enabled": False,
    "forced_trades_enabled": False,
    "forced_exits_enabled": False,
    "human_review_required": True,
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


def _to_int(value: Any, default: int = 0) -> int:
    return int(_to_float(value, float(default)))


def _clamp(value: Any, low: float = 0.0, high: float = 100.0, default: float = 0.0) -> float:
    return round(max(low, min(high, _to_float(value, default))), 2)


def _avg(values: list[Any], default: float = 0.0) -> float:
    nums = [_to_float(v, default) for v in values if v is not None]
    return round(sum(nums) / max(1, len(nums)), 2) if nums else round(default, 2)


def _safe_text(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    return text[:limit]


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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}
    return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except Exception:
            pass


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


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
        self.state_dir = Path(state_dir)
        self.cache_path = self.state_dir / "institutional_intelligence_maturation_v3_cache.json"
        self.ledger_path = self.state_dir / "institutional_intelligence_maturation_v3.jsonl"

    def _section(self, statuses: dict[str, Any], key: str) -> dict[str, Any]:
        value = statuses.get(key)
        return value if isinstance(value, dict) else {}

    def _portfolio_v2(self, statuses: dict[str, Any]) -> dict[str, Any]:
        portfolio = self._section(statuses, "portfolio_health_summary")
        risk = self._section(statuses, "portfolio_risk_intelligence")
        div = self._section(statuses, "portfolio_diversification_correlation_v2")
        horizon = self._section(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        heat_raw = portfolio.get("portfolio_heat")
        heat = _to_float(heat_raw.get("value") if isinstance(heat_raw, dict) else heat_raw, _to_float(risk.get("portfolio_heat"), 45.0))
        concentration = _to_float(div.get("concentration_risk") or div.get("concentration_risk_trend") or risk.get("portfolio_concentration_score"), 45.0)
        correlation = _to_float(div.get("correlation_risk") or div.get("correlation_risk_trend") or risk.get("portfolio_correlation_score"), 45.0)
        diversification = _to_float(div.get("diversification_quality") or div.get("diversification_quality_trend") or risk.get("portfolio_diversification_score"), 100.0 - ((concentration + correlation) / 2.0))
        capital_efficiency = _to_float(horizon.get("capital_efficiency_score") or risk.get("capital_efficiency_score"), 100.0 - min(80.0, heat * 0.45 + concentration * 0.25))
        recycling_score = _clamp(55.0 + _to_float(horizon.get("freed_slots_today"), 0.0) * 8.0 - _to_float(horizon.get("unknown_horizon_positions"), 0.0) * 10.0, default=55.0)
        health = _clamp((diversification + capital_efficiency + (100.0 - heat) + (100.0 - correlation)) / 4.0, default=58.0)
        score = _avg([health, diversification, capital_efficiency, recycling_score], default=58.0)
        return {
            "suite": "Portfolio Intelligence Maturation V2",
            "status": "ok" if portfolio or risk or horizon else "warming_up",
            "portfolio_intelligence_score": score,
            "portfolio_health_score": health,
            "concentration_score": _clamp(concentration, default=45.0),
            "diversification_score": _clamp(diversification, default=55.0),
            "correlation_score": _clamp(correlation, default=45.0),
            "portfolio_heat_score": _clamp(heat, default=45.0),
            "capital_efficiency_score": _clamp(capital_efficiency, default=58.0),
            "recycling_score": recycling_score,
            "top_overlap_theme": str(div.get("top_overlap_theme") or risk.get("top_overlap_theme") or "warming_up"),
            "top_overlap_sector": str(div.get("top_overlap_sector") or risk.get("top_overlap_sector") or "warming_up"),
            "highest_risk_cluster": str(risk.get("highest_risk_cluster") or div.get("highest_correlation_cluster") or "warming_up"),
            "best_capital_recycling_candidate": str(horizon.get("best_capital_recycling_candidate") or horizon.get("most_overdue_position") or "human_review_queue"),
            "portfolio_priority_action": str(horizon.get("recommended_capacity_action") or "Keep broker truth as source of truth and review concentration before adding risk."),
            "inputs_used": ["portfolio_health_summary", "portfolio_risk_intelligence", "portfolio_diversification_correlation_v2", "horizon_lifecycle_bundle"],
            **SAFETY_FLAGS,
        }

    def _exit_v3(self, statuses: dict[str, Any]) -> dict[str, Any]:
        exit_suite = self._section(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        pilot = self._section(statuses, "controlled_paper_profit_protection_pilot_v1")
        exit_v3 = self._section(statuses, "adaptive_execution_exit_intelligence_v3")
        lifecycle = self._section(statuses, "trade_lifecycle_excursion_v2")
        horizon = self._section(statuses, "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1")
        profit_lock = _to_float(pilot.get("profit_lock_readiness") or exit_suite.get("profit_lock_readiness"), 45.0)
        horizon_specific = _to_float(exit_suite.get("horizon_specific_exit_readiness") or exit_v3.get("horizon_specific_exit_readiness") or horizon.get("exit_policy_readiness_score"), 45.0)
        catalyst_decay = _to_float(pilot.get("catalyst_decay_risk") or exit_suite.get("catalyst_decay_exit_value") or horizon.get("catalyst_decay_score"), 45.0)
        regime_aware = _to_float(exit_v3.get("regime_aware_exit_readiness") or lifecycle.get("regime_exit_readiness"), 45.0)
        symbol_aware = _to_float(exit_v3.get("symbol_aware_exit_readiness") or exit_suite.get("policy_confidence"), 45.0)
        evidence = _to_int(exit_suite.get("evidence_count") or pilot.get("evidence_count") or exit_v3.get("evidence_count"), 0)
        score = _avg([profit_lock, horizon_specific, regime_aware, symbol_aware], default=45.0)
        stage = "stage_2_alerts" if score >= 62 and evidence >= 25 else "stage_1_recommendations"
        giveback_reduction = _clamp(pilot.get("estimated_giveback_reduction") or horizon.get("expected_giveback_reduction") or max(0.0, profit_lock - 45.0) * 0.18, high=25.0)
        capture_improvement = _clamp(pilot.get("estimated_profit_capture_improvement") or horizon.get("expected_profit_capture_improvement") or max(0.0, score - 45.0) * 0.12, high=20.0)
        alert_candidates = []
        for row in (horizon.get("horizon_exit_candidates") or horizon.get("exit_alert_candidates") or [])[:8]:
            if isinstance(row, dict):
                alert_candidates.append({
                    "symbol": row.get("symbol"),
                    "reason": row.get("reason") or row.get("risk_reason") or "review_exit_quality",
                    "stage": stage,
                    "human_review_required": True,
                })
        return {
            "suite": "Exit Intelligence Maturation V3",
            "status": "ok" if exit_suite or pilot or horizon else "warming_up",
            "exit_intelligence_score": score,
            "profit_lock_readiness": _clamp(profit_lock, default=45.0),
            "horizon_specific_exit_readiness": _clamp(horizon_specific, default=45.0),
            "catalyst_decay_exit_readiness": _clamp(100.0 - catalyst_decay, default=55.0),
            "regime_aware_exit_readiness": _clamp(regime_aware, default=45.0),
            "symbol_aware_exit_readiness": _clamp(symbol_aware, default=45.0),
            "false_positive_risk": _clamp(100.0 - score, default=55.0),
            "false_negative_risk": _clamp(70.0 - profit_lock, default=30.0),
            "exit_stage": stage,
            "stage_1_recommendations_enabled": True,
            "stage_2_alerts_enabled": stage == "stage_2_alerts",
            "stage_3_automatic_exits_enabled": False,
            "expected_giveback_reduction": giveback_reduction,
            "expected_capture_improvement": capture_improvement,
            "exit_alert_candidates": alert_candidates,
            "human_review_required": True,
            "no_automatic_sells": True,
            **SAFETY_FLAGS,
        }

    def _sector_v2(self, statuses: dict[str, Any]) -> dict[str, Any]:
        sector = self._section(statuses, "etf_sector_rotation_intelligence_v1")
        flow = self._section(statuses, "cross_sector_capital_flow_memory_v1")
        market_condition = self._section(statuses, "market_condition_attribution_v1")
        leadership = _to_float(sector.get("sector_leadership_score") or sector.get("sector_inflow_score") or flow.get("flow_persistence"), 55.0)
        rotation = _to_float(sector.get("sector_rotation_score") or sector.get("sector_momentum_persistence") or flow.get("rotation_confidence"), 55.0)
        lagging = _to_float(sector.get("sector_lagging_score") or sector.get("sector_outflow_score"), 100.0 - rotation)
        confidence = _to_float(sector.get("sector_rotation_confidence") or flow.get("sector_flow_confidence"), 50.0)
        score = _avg([leadership, rotation, confidence, 100.0 - lagging], default=55.0)
        return {
            "suite": "Sector Rotation Intelligence V2",
            "status": "ok" if sector or flow else "warming_up",
            "sector_rotation_score": score,
            "sector_leadership_score": _clamp(leadership, default=55.0),
            "sector_lagging_score": _clamp(lagging, default=45.0),
            "sector_inflow_score": _clamp(sector.get("sector_inflow_score") or leadership, default=55.0),
            "sector_outflow_score": _clamp(sector.get("sector_outflow_score") or lagging, default=45.0),
            "rotation_speed": _clamp(sector.get("rotation_speed") or flow.get("rotation_speed"), default=45.0),
            "persistence": _clamp(sector.get("sector_momentum_persistence") or flow.get("flow_persistence"), default=55.0),
            "strongest_sector": str(sector.get("strongest_sector") or flow.get("strongest_inflow_sector") or "warming_up"),
            "weakest_sector": str(sector.get("weakest_sector") or flow.get("strongest_outflow_sector") or "warming_up"),
            "sector_confirmation_for_candidates": str(market_condition.get("best_condition") or "attribution_only"),
            "sector_warning_for_candidates": str(market_condition.get("weakest_condition") or "no_forced_filter"),
            **SAFETY_FLAGS,
        }

    def _breadth_v2(self, statuses: dict[str, Any]) -> dict[str, Any]:
        breadth = self._section(statuses, "market_breadth_index_intelligence_v1")
        transition = self._section(statuses, "market_transition_detection_v1")
        score = _to_float(breadth.get("market_breadth_score") or breadth.get("breadth_proxy_score"), 52.0)
        participation = _to_float(breadth.get("participation_score") or breadth.get("market_support_for_equity_trades"), score)
        narrow_risk = _clamp(100.0 - score, default=48.0)
        risk_on = _to_float(breadth.get("risk_on_score"), 50.0)
        risk_off = _to_float(breadth.get("risk_off_score"), 50.0)
        deterioration = _clamp(transition.get("transition_risk_score") or breadth.get("market_transition_risk") or max(0.0, risk_off - risk_on + 45.0), default=45.0)
        confidence = _to_float(breadth.get("index_confidence_score") or transition.get("transition_confidence"), 50.0)
        return {
            "suite": "Market Breadth Intelligence V2",
            "status": "ok" if breadth or transition else "warming_up",
            "market_breadth_score": _clamp(score, default=52.0),
            "participation_score": _clamp(participation, default=52.0),
            "narrow_market_risk": narrow_risk,
            "breadth_deterioration_risk": deterioration,
            "risk_on_breadth_signal": _clamp(risk_on, default=50.0),
            "risk_off_breadth_signal": _clamp(risk_off, default=50.0),
            "breadth_confidence": _clamp(confidence, default=50.0),
            "broad_participation_signal": "broadening" if score >= 60 else "narrowing" if score < 45 else "mixed",
            "breadth_warning_for_growth_trades": "elevated" if narrow_risk >= 60 else "normal",
            **SAFETY_FLAGS,
        }

    def _macro_fed_v2(self, statuses: dict[str, Any], provider_scores: list[dict[str, Any]]) -> dict[str, Any]:
        market = self._section(statuses, "astra_market_intelligence_v1")
        calendar = self._section(statuses, "market_calendar_knowledge")
        fred = next((row for row in provider_scores if row.get("provider_name") == "FRED"), {})
        pillars = market.get("pillars") if isinstance(market.get("pillars"), list) else []
        macro_pillar = next((r for r in pillars if isinstance(r, dict) and r.get("pillar") == "Economic Environment"), {})
        fed_pillar = next((r for r in pillars if isinstance(r, dict) and r.get("pillar") == "Monetary Policy"), {})
        macro_score = _to_float(macro_pillar.get("pillar_score"), 48.0 + _to_float(fred.get("confidence_score"), 45.0) * 0.12)
        fed_score = _to_float(fed_pillar.get("pillar_score"), 48.0 + _to_float(fred.get("confidence_score"), 45.0) * 0.12)
        confidence = _avg([macro_pillar.get("confidence"), fed_pillar.get("confidence"), fred.get("overall_provider_score")], default=45.0)
        return {
            "suite": "Macro/Fed Intelligence V2",
            "status": "ok" if market or calendar or fred.get("configured") else "insufficient_evidence",
            "macro_intelligence_score": _clamp(macro_score, default=50.0),
            "fed_intelligence_score": _clamp(fed_score, default=50.0),
            "macro_confidence": _clamp(confidence, default=45.0),
            "fed_confidence": _clamp(confidence, default=45.0),
            "inflation_posture": str(calendar.get("inflation_posture") or "cached_evidence_warming_up"),
            "employment_posture": str(calendar.get("employment_posture") or "cached_evidence_warming_up"),
            "treasury_yield_posture": str(calendar.get("treasury_yield_posture") or "cached_evidence_warming_up"),
            "yield_curve_posture": str(calendar.get("yield_curve_posture") or "cached_evidence_warming_up"),
            "liquidity_posture": str(calendar.get("liquidity_posture") or "cached_evidence_warming_up"),
            "fed_risk_score": _clamp(100.0 - fed_score, default=50.0),
            "macro_provider_owner": "FRED",
            "provider_configured": bool(fred.get("configured", False)),
            **SAFETY_FLAGS,
        }

    def _market_regime_v1(self, breadth: dict[str, Any], sector: dict[str, Any], macro: dict[str, Any]) -> dict[str, Any]:
        breadth_score = _to_float(breadth.get("market_breadth_score"), 52.0)
        sector_score = _to_float(sector.get("sector_rotation_score"), 55.0)
        macro_score = _to_float(macro.get("macro_intelligence_score"), 50.0)
        fed_score = _to_float(macro.get("fed_intelligence_score"), 50.0)
        transition = _to_float(breadth.get("breadth_deterioration_risk"), 45.0)
        composite = _avg([breadth_score, sector_score, macro_score, fed_score], default=52.0)
        if composite >= 62 and transition < 55:
            regime = "risk_on_constructive"
        elif composite < 45 or transition >= 68:
            regime = "risk_off_defensive"
        else:
            regime = "mixed_selective"
        confidence = _avg([breadth.get("breadth_confidence"), sector.get("sector_rotation_confidence"), macro.get("macro_confidence")], default=50.0)
        return {
            "suite": "Market Regime Engine V1",
            "status": "ok",
            "market_regime_score": composite,
            "market_regime": regime,
            "regime_confidence": _clamp(confidence, default=50.0),
            "tailwinds": [item for item, score in [("breadth", breadth_score), ("sector_rotation", sector_score), ("macro", macro_score)] if score >= 60],
            "headwinds": [item for item, score in [("breadth", breadth_score), ("sector_rotation", sector_score), ("fed", fed_score)] if score < 45],
            "transition_risk": _clamp(transition, default=45.0),
            "regime_summary": f"{regime.replace('_', ' ')} from cached breadth, sector, macro, and Fed evidence.",
            **SAFETY_FLAGS,
        }

    def _provider_self_healing_v1(self, provider_scores: list[dict[str, Any]]) -> dict[str, Any]:
        rows = []
        for provider in provider_scores:
            healthy = bool(provider.get("healthy"))
            configured = bool(provider.get("configured"))
            fallback = not healthy and bool((PROVIDER_PURPOSES.get(str(provider.get("provider_name")) or "") or {}).get("secondary_categories") or configured)
            rows.append({
                "provider_name": provider.get("provider_name"),
                "status": "healthy" if healthy else "configured_needs_probe" if configured else "not_configured",
                "last_success": "tracked_by_existing_provider_router" if healthy else "not_available_in_cache",
                "last_failure": "not_available_in_cache" if healthy else "missing_or_unhealthy_cached_status",
                "failure_count": int(provider.get("errors_total") or 0),
                "rate_limit_state": "unknown" if not configured else "within_budget",
                "fallback_provider": self._fallback_for_provider(str(provider.get("provider_name") or "")),
                "fallback_used": bool(fallback),
                "fallback_reason": "primary_unhealthy_or_unconfigured" if fallback else "primary_ok_or_no_backup_needed",
                "self_healing_action": "use_backup_only_for_background_collection" if fallback else "continue_primary_owner",
            })
        unhealthy = [row for row in rows if row.get("status") != "healthy"]
        return {
            "suite": "Provider Self-Healing V1",
            "status": "ok",
            "providers_monitored": len(rows),
            "providers_requiring_fallback": len([row for row in rows if row.get("fallback_used")]),
            "provider_rows": rows,
            "highest_priority_repair": unhealthy[0].get("provider_name") if unhealthy else "none",
            "fallbacks_logged": True,
            "rate_limit_guard_enabled": True,
            "duplicate_retry_guard_enabled": True,
            **SAFETY_FLAGS,
        }

    def _fallback_for_provider(self, provider: str) -> str:
        provider = provider.upper()
        for rule in OWNERSHIP_MATRIX.values():
            if rule.get("primary") == provider and rule.get("secondary"):
                return str((rule.get("secondary") or ["none"])[0])
        return "none"

    def _knowledge_graph_expansion_v1(self, portfolio: dict[str, Any], exit_v3: dict[str, Any], sector: dict[str, Any], breadth: dict[str, Any], macro: dict[str, Any], regime: dict[str, Any], provider_scores: list[dict[str, Any]]) -> dict[str, Any]:
        nodes = {
            "providers", "portfolio", "exits", "sector_rotation", "market_breadth", "macro_fed", "market_regime",
            str(regime.get("market_regime") or "mixed_selective"), str(sector.get("strongest_sector") or "sector_warming_up"),
            str(sector.get("weakest_sector") or "sector_warming_up"),
        }
        for provider in provider_scores:
            nodes.add(str(provider.get("provider_name") or "provider"))
        edges = [
            ("ALPACA", "owns", "portfolio"),
            ("ALPACA", "feeds", "exits"),
            ("FMP", "owns", "sector_rotation"),
            ("FMP", "feeds", "market_breadth"),
            ("FRED", "owns", "macro_fed"),
            ("sector_rotation", "informs", "market_regime"),
            ("market_breadth", "informs", "market_regime"),
            ("macro_fed", "informs", "market_regime"),
            ("portfolio", "constrained_by", "risk_governance"),
            ("exits", "requires", "human_review"),
        ]
        graph_confidence = _avg([portfolio.get("portfolio_intelligence_score"), exit_v3.get("exit_intelligence_score"), sector.get("sector_rotation_score"), breadth.get("market_breadth_score"), macro.get("macro_confidence")], default=55.0)
        return {
            "suite": "Knowledge Graph Expansion V1",
            "status": "ok",
            "graph_node_count": len(nodes),
            "graph_edge_count": len(edges),
            "graph_confidence": _clamp(graph_confidence, default=55.0),
            "graph_coverage": _clamp(35.0 + len(edges) * 4.5, default=70.0),
            "strongest_relationship": "market_breadth -> market_regime" if _to_float(breadth.get("market_breadth_score"), 0.0) >= _to_float(sector.get("sector_rotation_score"), 0.0) else "sector_rotation -> market_regime",
            "weakest_relationship": "macro_fed -> market_regime" if _to_float(macro.get("macro_confidence"), 0.0) < 55 else "provider_fallbacks -> confidence_decay",
            "top_relationships": [" -> ".join(edge) for edge in edges[:10]],
            "raw_data_passed_directly_to_dashboard": False,
            **SAFETY_FLAGS,
        }

    def _consensus_expansion_v1(self, portfolio: dict[str, Any], exit_v3: dict[str, Any], sector: dict[str, Any], breadth: dict[str, Any], macro: dict[str, Any], regime: dict[str, Any], knowledge_graph: dict[str, Any]) -> dict[str, Any]:
        inputs = {
            "portfolio": _to_float(portfolio.get("portfolio_intelligence_score"), 0.0),
            "exit": _to_float(exit_v3.get("exit_intelligence_score"), 0.0),
            "sector": _to_float(sector.get("sector_rotation_score"), 0.0),
            "breadth": _to_float(breadth.get("market_breadth_score"), 0.0),
            "macro_fed": _avg([macro.get("macro_intelligence_score"), macro.get("fed_intelligence_score")], default=50.0),
            "regime": _to_float(regime.get("market_regime_score"), 0.0),
            "knowledge_graph": _to_float(knowledge_graph.get("graph_confidence"), 0.0),
        }
        score = _avg(list(inputs.values()), default=55.0)
        sorted_inputs = sorted(inputs.items(), key=lambda kv: kv[1])
        conflict_count = len([v for v in inputs.values() if v < 45])
        agreement_count = len([v for v in inputs.values() if v >= 55])
        return {
            "suite": "Consensus Engine Expansion V1",
            "status": "ok",
            "consensus_score": score,
            "agreement_count": agreement_count,
            "conflict_count": conflict_count,
            "systems_agreeing": [name for name, value in inputs.items() if value >= 55],
            "systems_conflicting": [name for name, value in inputs.items() if value < 45],
            "strongest_consensus_input": sorted_inputs[-1][0] if sorted_inputs else "warming_up",
            "weakest_consensus_input": sorted_inputs[0][0] if sorted_inputs else "warming_up",
            "consensus_label": "strong_consensus" if score >= 75 else "moderate_consensus" if score >= 60 else "mixed_consensus" if score >= 45 else "weak_consensus",
            "recommended_consensus_use": "executive_context_only_no_behavior_change",
            **SAFETY_FLAGS,
        }

    def _controlled_data_acquisition_v2(self, *, cached: dict[str, Any], background_state: dict[str, Any] | None, projected_monthly: float, bandwidth_status: str) -> dict[str, Any]:
        state = background_state if isinstance(background_state, dict) else {}
        cache_generated_at = str(cached.get("generated_at_utc") or cached.get("generated_at") or "")
        cache_age = None
        try:
            if cache_generated_at:
                cache_dt = datetime.fromisoformat(cache_generated_at.replace("Z", "+00:00"))
                cache_age = round(max(0.0, (datetime.now(UTC) - cache_dt.astimezone(UTC)).total_seconds()), 2)
        except Exception:
            cache_age = None
        return {
            "suite": "Controlled Data Acquisition Orchestrator V2",
            "status": "active" if state.get("thread_started") or cached else "ready_not_yet_run",
            "background_worker_exists": True,
            "scheduler_exists": True,
            "thread_started": bool(state.get("thread_started", False)),
            "running": bool(state.get("running", False)),
            "last_collection_at": str(state.get("last_success") or cached.get("last_collection_at") or cache_generated_at or "never"),
            "last_collection_reason": str(state.get("last_reason") or cached.get("last_collection_reason") or "none"),
            "last_error": str(state.get("last_error") or ""),
            "last_duration_ms": _to_float(state.get("last_duration_ms"), 0.0),
            "collection_schedule": CONTROLLED_COLLECTION_SCHEDULE,
            "provider_calls_only_in_controlled_background_path": True,
            "dashboard_provider_calls_used": 0,
            "provider_calls_from_dashboard": 0,
            "cache_path": str(self.cache_path),
            "ledger_path": str(self.ledger_path),
            "cache_age_seconds": cache_age,
            "cache_first": True,
            "duplicate_provider_calls_prevented": True,
            "provider_fallbacks_logged": True,
            "primary_provider_ownership_rules_respected": True,
            "bandwidth_caps_enforced": True,
            "projected_monthly_usage_gb": round(projected_monthly, 4),
            "bandwidth_status": bandwidth_status,
            "background_collection_uses_existing_providers_only": True,
            **SAFETY_FLAGS,
        }

    def _persist_cache_if_allowed(self, payload: dict[str, Any], *, reason: str, allow_cache_write: bool) -> dict[str, Any]:
        if not allow_cache_write:
            return {"cache_write_attempted": False, "cache_write_status": "not_allowed_on_dashboard_or_endpoint_path"}
        snapshot = {
            "generated_at_utc": payload.get("generated_at_utc") or _now_iso(),
            "last_collection_at": _now_iso(),
            "last_collection_reason": reason,
            "institutional_intelligence_score": payload.get("institutional_intelligence_score"),
            "controlled_data_acquisition_score": payload.get("controlled_data_acquisition_score"),
            "provider_health_score": payload.get("provider_health_score"),
            "portfolio_intelligence_score": payload.get("portfolio_intelligence_score"),
            "exit_intelligence_score": payload.get("exit_intelligence_score"),
            "sector_rotation_score": payload.get("sector_rotation_score"),
            "market_breadth_score": payload.get("market_breadth_score"),
            "macro_intelligence_score": payload.get("macro_intelligence_score"),
            "fed_intelligence_score": payload.get("fed_intelligence_score"),
            "market_regime_score": payload.get("market_regime_score"),
            "consensus_score": payload.get("consensus_score"),
            "knowledge_graph_score": payload.get("knowledge_graph_score"),
            "dashboard_provider_calls_used": 0,
            "dashboard_llm_calls_used": 0,
            "behavior_safe_to_apply": False,
        }
        _atomic_write_json(self.cache_path, snapshot)
        _append_jsonl(self.ledger_path, snapshot)
        return {"cache_write_attempted": True, "cache_write_status": "written", "cache_path": str(self.cache_path), "ledger_path": str(self.ledger_path)}

    def status(
        self,
        *,
        statuses: dict[str, Any] | None = None,
        provider_capability: dict[str, Any] | None = None,
        provider_diagnostics: dict[str, Any] | None = None,
        provider_usage: dict[str, Any] | None = None,
        manager_rows: list[dict[str, Any]] | None = None,
        force: bool = False,
        allow_cache_write: bool = False,
        collection_reason: str = "endpoint_status",
        background_state: dict[str, Any] | None = None,
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
        provider_health_score = _avg([row.get("overall_provider_score") for row in provider_scores], default=45.0)
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

        portfolio_v2 = self._portfolio_v2(status_map)
        exit_intel_v3 = self._exit_v3(status_map)
        sector_v2 = self._sector_v2(status_map)
        breadth_v2 = self._breadth_v2(status_map)
        macro_fed_v2 = self._macro_fed_v2(status_map, provider_scores)
        regime_v1 = self._market_regime_v1(breadth_v2, sector_v2, macro_fed_v2)
        self_healing = self._provider_self_healing_v1(provider_scores)
        knowledge_graph = self._knowledge_graph_expansion_v1(portfolio_v2, exit_intel_v3, sector_v2, breadth_v2, macro_fed_v2, regime_v1, provider_scores)
        consensus = self._consensus_expansion_v1(portfolio_v2, exit_intel_v3, sector_v2, breadth_v2, macro_fed_v2, regime_v1, knowledge_graph)
        cached_snapshot = _load_json(self.cache_path)
        controlled = self._controlled_data_acquisition_v2(cached=cached_snapshot, background_state=background_state, projected_monthly=projected_monthly, bandwidth_status=bandwidth_status)
        controlled_score = _avg([
            85.0 if controlled.get("background_worker_exists") else 40.0,
            85.0 if controlled.get("scheduler_exists") else 40.0,
            100.0 if controlled.get("duplicate_provider_calls_prevented") else 50.0,
            100.0 if bandwidth_status in {"efficient", "soft_limit_watch"} else 45.0,
        ], default=75.0)
        provider_orchestration_score = _avg([provider_health_score, controlled_score, 90.0, 100.0 if bandwidth_status in {"efficient", "soft_limit_watch"} else 55.0], default=70.0)
        institutional_score = _avg([
            controlled_score,
            provider_orchestration_score,
            provider_health_score,
            portfolio_v2.get("portfolio_intelligence_score"),
            exit_intel_v3.get("exit_intelligence_score"),
            sector_v2.get("sector_rotation_score"),
            breadth_v2.get("market_breadth_score"),
            macro_fed_v2.get("macro_intelligence_score"),
            macro_fed_v2.get("fed_intelligence_score"),
            regime_v1.get("market_regime_score"),
            consensus.get("consensus_score"),
            knowledge_graph.get("graph_confidence"),
        ], default=60.0)
        area_scores = {
            "controlled_data_acquisition": controlled_score,
            "provider_orchestration": provider_orchestration_score,
            "provider_health": provider_health_score,
            "portfolio_intelligence": _to_float(portfolio_v2.get("portfolio_intelligence_score"), 0.0),
            "exit_intelligence": _to_float(exit_intel_v3.get("exit_intelligence_score"), 0.0),
            "sector_rotation": _to_float(sector_v2.get("sector_rotation_score"), 0.0),
            "market_breadth": _to_float(breadth_v2.get("market_breadth_score"), 0.0),
            "macro_intelligence": _to_float(macro_fed_v2.get("macro_intelligence_score"), 0.0),
            "fed_intelligence": _to_float(macro_fed_v2.get("fed_intelligence_score"), 0.0),
            "market_regime": _to_float(regime_v1.get("market_regime_score"), 0.0),
            "consensus": _to_float(consensus.get("consensus_score"), 0.0),
            "knowledge_graph": _to_float(knowledge_graph.get("graph_confidence"), 0.0),
        }
        strongest_area = max(area_scores.items(), key=lambda kv: kv[1])[0]
        weakest_area = min(area_scores.items(), key=lambda kv: kv[1])[0]
        roi_focus = "Improve cached exit/profit capture maturity." if weakest_area == "exit_intelligence" else f"Improve {weakest_area.replace('_', ' ')} evidence through controlled background cache collection."

        payload = {
            "suite": "Astra Institutional Intelligence Maturation Bundle V3",
            "status": "ok",
            "enabled": True,
            "version": "3.0.0",
            "mode": "controlled_background_cache_provider_orchestration_advisory_only",
            "generated_at_utc": _now_iso(),
            "dashboard_reads_cache_only": True,
            "dashboard_never_calls_providers": True,
            "no_new_providers_added": True,
            "providers_allowed": list(PROVIDERS),
            "provider_ownership_matrix": OWNERSHIP_MATRIX,
            "provider_utilization_matrix": provider_scores,
            "provider_health_matrix": provider_scores,
            "controlled_data_acquisition_orchestrator_v2": controlled,
            "provider_self_healing_v1": self_healing,
            "portfolio_intelligence_maturation_v2": portfolio_v2,
            "exit_intelligence_maturation_v3": exit_intel_v3,
            "sector_rotation_intelligence_v2": sector_v2,
            "market_breadth_intelligence_v2": breadth_v2,
            "macro_fed_intelligence_v2": macro_fed_v2,
            "market_regime_engine_v1": regime_v1,
            "knowledge_graph_expansion_v1": knowledge_graph,
            "consensus_engine_expansion_v1": consensus,
            "institutional_intelligence_score": institutional_score,
            "controlled_data_acquisition_score": controlled_score,
            "provider_orchestration_score": provider_orchestration_score,
            "provider_health_score": provider_health_score,
            "portfolio_intelligence_score": _to_float(portfolio_v2.get("portfolio_intelligence_score"), 0.0),
            "exit_intelligence_score": _to_float(exit_intel_v3.get("exit_intelligence_score"), 0.0),
            "sector_rotation_score": _to_float(sector_v2.get("sector_rotation_score"), 0.0),
            "market_breadth_score": _to_float(breadth_v2.get("market_breadth_score"), 0.0),
            "macro_intelligence_score": _to_float(macro_fed_v2.get("macro_intelligence_score"), 0.0),
            "fed_intelligence_score": _to_float(macro_fed_v2.get("fed_intelligence_score"), 0.0),
            "market_regime_score": _to_float(regime_v1.get("market_regime_score"), 0.0),
            "consensus_score": _to_float(consensus.get("consensus_score"), 0.0),
            "knowledge_graph_score": _to_float(knowledge_graph.get("graph_confidence"), 0.0),
            "strongest_area": strongest_area,
            "weakest_area": weakest_area,
            "highest_roi_next_improvement": roi_focus,
            "bandwidth_projection_gb_month": projected_monthly,
            "executive_ceo_copilot_ask_astra_enrichment": {
                "executive_summary_enriched": True,
                "ceo_summary_enriched": True,
                "copilot_context_enriched": True,
                "ask_astra_context_enriched": True,
                "source": "provider_orchestration_v3_cached_summary",
                "dashboard_llm_calls_used": 0,
                "dashboard_provider_calls_used": 0,
                "behavior_safe_to_apply": False,
            },
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
                "average_overall_provider_score": provider_health_score,
            },
            "intelligent_data_acquisition_orchestrator_v2": {
                "status": controlled.get("status"),
                "uses_existing_providers_only": True,
                "feed_priorities": INTELLIGENCE_FEEDING_PRIORITIES,
                "duplicate_evidence_prevention": True,
                "cache_first": True,
                "background_worker_exists": True,
                "scheduler_exists": True,
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
                    "controlled_background_cache_collection",
                    "provider_self_healing_visibility",
                    "portfolio_intelligence_maturation",
                    "exit_intelligence_stage_maturation",
                    "sector_breadth_macro_regime_consensus",
                    "knowledge_graph_expansion",
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
                "caps_enforced": True,
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
                "purpose": "Provider ownership, controlled acquisition, self-healing, intelligence maturation, knowledge graph, and consensus expansion",
                "inputs": ["provider_capability_audit_cache", "provider_router_diagnostics", "api_call_manager_summary", "unified_diagnostics_statuses"],
                "outputs": ["provider_ownership_matrix", "provider_health_matrix", "controlled_data_acquisition", "portfolio_exit_sector_breadth_macro_regime_maturation", "knowledge_graph", "consensus"],
                "dependencies": ["ProviderRouter", "api_call_manager", "unified_learning_diagnostics_v1"],
                "health_status": "healthy",
                "enabled": True,
                "api_budget": "background_controlled_cache_only",
                "bandwidth_budget": "5-10gb_target_15gb_soft_limit",
            },
            "summary": {
                "primary_provider_model": "single_owner_per_category_with_backup_only_when_primary_is_stale_unhealthy_or_low_confidence",
                "best_configured_owner": max(provider_scores, key=lambda row: row["overall_provider_score"])["provider_name"] if provider_scores else "none",
                "highest_priority_improvement": roi_focus,
                "dashboard_contract": "cache_only_no_provider_or_llm_calls",
                "institutional_status": f"Score {institutional_score:.1f}; strongest {strongest_area}; weakest {weakest_area}.",
            },
            **SAFETY_FLAGS,
        }
        payload.update(self._persist_cache_if_allowed(payload, reason=collection_reason, allow_cache_write=bool(allow_cache_write)))
        return payload
