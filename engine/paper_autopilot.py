from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

try:
    from engine.position_tracker import PositionTracker
except Exception:  # pragma: no cover - keep runtime-compatible fallback
    PositionTracker = None  # type: ignore[assignment]

try:
    from engine.trade_lifecycle_tracker import (
        close_lifecycle_record,
        create_lifecycle_record,
        update_lifecycle_progress,
    )
except Exception:  # pragma: no cover - tracker is additive and optional
    close_lifecycle_record = None  # type: ignore[assignment]
    create_lifecycle_record = None  # type: ignore[assignment]
    update_lifecycle_progress = None  # type: ignore[assignment]

try:
    from engine.trade_lifecycle_excursion_v1 import TradeLifecycleExcursionV1
except Exception:  # pragma: no cover - excursion telemetry is additive
    class TradeLifecycleExcursionV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def record_open_position(self, *args, **kwargs):
            return {"ok": False, "reason": "trade_lifecycle_excursion_unavailable"}

        def record_closed_position(self, *args, **kwargs):
            return {"ok": False, "reason": "trade_lifecycle_excursion_unavailable"}

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "trade_lifecycle_excursion_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_exits_enabled": False,
            }

try:
    from engine.execution_participation_audit_v1 import ExecutionParticipationAuditV1
except Exception:  # pragma: no cover - execution audit is additive
    class ExecutionParticipationAuditV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def record_candidate_traces(self, *args, **kwargs):
            return {"ok": False, "records_written": 0, "reason": "execution_participation_audit_unavailable"}

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "execution_participation_audit_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "paper_only_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
            }

try:
    from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1
except Exception:  # pragma: no cover - allocation engine is additive
    class PaperOpportunityAllocationEngineV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, rows=None):
            return {
                "enabled": False,
                "mode": "paper_only_shadow_allocation",
                "paper_opportunity_allocation_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "natural_exit_preserved": True,
            }

try:
    from engine.edge_development_suite_v1 import EdgeDevelopmentSuiteV1
except Exception:  # pragma: no cover - edge suite is additive
    class EdgeDevelopmentSuiteV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, rows=None):
            return {
                "enabled": False,
                "mode": "paper_only_shadow_learning",
                "edge_development_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "natural_exit_preserved": True,
                "forced_early_exit_enabled": False,
            }

try:
    from engine.trade_management_portfolio_intelligence_v1 import TradeManagementPortfolioIntelligenceV1
except Exception:  # pragma: no cover - trade management suite is additive
    class TradeManagementPortfolioIntelligenceV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

try:
    from engine.market_session_execution_timing_v1 import MarketSessionExecutionTimingV1
except Exception:  # pragma: no cover - session timing suite is additive
    class MarketSessionExecutionTimingV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "market_session_mode": "unknown_closed",
                "market_is_open": False,
                "market_is_tradable": False,
                "paper_order_submission_allowed": False,
                "execution_confirmation_required": True,
                "execution_intent_status": "intent_unavailable",
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

        def confirmation_for_candidate(self, *args, **kwargs):
            return self.status()

try:
    from engine.market_calendar_knowledge_intelligence_v1 import MarketCalendarKnowledgeIntelligenceV1
except Exception:  # pragma: no cover - market knowledge suite is additive
    class MarketCalendarKnowledgeIntelligenceV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "current_session_type": "unknown_closed",
                "session_tradable": False,
                "broker_order_submission_allowed": False,
                "market_structure_label": "unknown",
                "trade_style_environment": "unknown",
                "behavioral_market_state": "unknown",
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1
except Exception:  # pragma: no cover - broad universe suite is additive
    class BroadUniverseIntakePromotionV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "broad_universe_pipeline_active": False,
                "promoted_to_top_buys_count": 0,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.adaptive_learning_infrastructure_v1 import AdaptiveLearningInfrastructureV1
except Exception:  # pragma: no cover - adaptive infrastructure is additive
    class AdaptiveLearningInfrastructureV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "adaptive_learning_infrastructure_status_v1": True,
                "adaptive_intelligence_score": 0.0,
                "learning_readiness_score": 0.0,
                "replay_learning_ready": False,
                "ollama_copilot_ready": True,
                "hermes_agent_compatible": True,
                "autonomous_ai_execution_allowed": False,
                "ai_execution_authority": False,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.replay_lifecycle_expectancy_learning_v1 import ReplayLifecycleExpectancyLearningV1
except Exception:  # pragma: no cover - replay lifecycle suite is additive
    class ReplayLifecycleExpectancyLearningV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "replay_lifecycle_expectancy_status_v1": True,
                "replay_learning_score": 0.0,
                "replay_learning_ready": False,
                "lifecycle_tracking_ready": True,
                "expectancy_learning_ready": False,
                "adaptive_policy_ready": True,
                "adaptive_policy_shadow_only": True,
                "adaptive_policy_auto_apply_allowed": False,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.regime_execution_survivability_intelligence_v1 import RegimeExecutionSurvivabilityIntelligenceV1
except Exception:  # pragma: no cover - regime execution suite is additive
    class RegimeExecutionSurvivabilityIntelligenceV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "regime_execution_survivability_status_v1": True,
                "current_market_regime": "uncertain_regime",
                "execution_quality_score": 0.0,
                "survivability_score": 0.0,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.adaptive_execution_exit_intelligence_v2 import AdaptiveExecutionExitIntelligenceV2
except Exception:  # pragma: no cover - adaptive execution V2 is additive
    class AdaptiveExecutionExitIntelligenceV2:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "2.0.0",
                "adaptive_execution_exit_intelligence_status_v2": True,
                "mode": "paper_only_shadow_learning",
                "api_calls_used": 0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
            }

try:
    from engine.portfolio_diversification_correlation_v2 import PortfolioDiversificationCorrelationV2
except Exception:  # pragma: no cover - portfolio diversification V2 is additive
    class PortfolioDiversificationCorrelationV2:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows, open_positions=None):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def rank_for_paper_selection(self, rows, open_positions=None):
            return self.decorate_candidates(rows, open_positions=open_positions)

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "2.0.0",
                "portfolio_diversification_v2_active": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

try:
    from engine.profit_seeking_adaptive_exploration_v1 import ProfitSeekingAdaptiveExplorationV1
except Exception:  # pragma: no cover - profit-seeking exploration is additive
    class ProfitSeekingAdaptiveExplorationV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def evaluate_candidate(self, *args, **kwargs):
            return {
                "controlled_exploration_considered": True,
                "controlled_exploration_allowed": False,
                "controlled_exploration_reason": "profit_seeking_exploration_import_unavailable",
                "exploration_rejection_reason": "profit_seeking_exploration_import_unavailable",
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "controlled_exploration_enabled": True,
                "exploration_mode": "profit_seeking",
                "exploration_randomness_allowed": False,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _age_seconds_from_iso(value: Any) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - dt.astimezone(UTC)).total_seconds())
    except Exception:
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    return int(round(_to_float(value, float(default))))


def _floor_fractional_qty(value: Any, decimals: int = 6) -> float:
    qty = _to_float(value, 0.0)
    if qty <= 0.0:
        return 0.0
    scale = 10 ** max(0, int(decimals))
    # Alpaca rejects sells that are even a few nanoshares above availability.
    return int(qty * scale) / scale


def _parse_available_qty_from_error(error: Any) -> float:
    raw = str(error or "")
    match = re.search(r"available:\s*([0-9]+(?:\.[0-9]+)?)", raw, re.IGNORECASE)
    return _to_float(match.group(1), 0.0) if match else 0.0


def _norm_asset(asset_type: Any) -> str:
    raw = str(asset_type or "stock").strip().lower()
    return "crypto" if raw == "crypto" else "stock"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return "{}"


def _safe_json_load(raw: Any) -> dict[str, Any]:
    try:
        if isinstance(raw, str) and raw:
            out = json.loads(raw)
            if isinstance(out, dict):
                return out
    except Exception:
        pass
    return {}


def _bounded_score(value: Any, default: Any = None):
    score = _to_float(value, default if default is not None else 0.0)
    if value is None and default is None:
        return None
    if score <= 1.0:
        score *= 100.0
    return max(0.0, min(100.0, float(score)))


def _entry_bridge_quality(row: dict[str, Any]):
    r = dict(row or {})
    for key in (
        "buy_quality_score",
        "trade_quality_score",
        "entry_filter_v2_score",
        "entry_filter_score",
        "entry_quality_v3_score",
        "entry_quality_v2_score",
        "entry_quality_score",
        "entry_quality",
        "execution_readiness_score",
        "risk_adjusted_profit_score",
        "aggressive_profit_score",
        "opportunity_score_pct",
        "best_horizon_score",
    ):
        if r.get(key) is None:
            continue
        score = _bounded_score(r.get(key))
        if score is not None:
            return score, key
    grade = _bounded_score(r.get("grade_percent"), None)
    confidence = _bounded_score(r.get("confidence"), _bounded_score(r.get("predicted_win_probability"), None))
    parts = [x for x in (grade, confidence) if x is not None]
    if parts:
        return round((sum(parts) / len(parts)) * 0.82, 2), "grade_confidence_compat"
    return None, ""


def _infer_horizon_style(row: dict[str, Any]):
    r = dict(row or {})
    for key in ("paper_entry_horizon_style", "trade_horizon_style", "best_horizon_style", "recommended_hold_style", "intended_hold_category"):
        raw = str(r.get(key) or "").strip().lower()
        if raw in {"scalp", "day_trade", "swing_trade"}:
            return raw, key, False
        if raw in {"intraday", "day", "daytrading"}:
            return "day_trade", key, True
        if raw in {"swing", "position_trade", "position"}:
            return "swing_trade", key, True
    fits = {
        "scalp": _bounded_score(r.get("scalp_fit_score"), None),
        "day_trade": _bounded_score(r.get("day_trade_fit_score"), None),
        "swing_trade": _bounded_score(r.get("swing_trade_fit_score"), None),
    }
    fits = {k: v for k, v in fits.items() if v is not None}
    if fits:
        best = max(fits.items(), key=lambda item: float(item[1]))[0]
        return best, f"{best}_fit_score", True
    action = str(r.get("action") or r.get("prediction") or "").strip().lower()
    readiness = " ".join(
        str(r.get(k) or "").strip().lower()
        for k in ("readiness_label", "paper_ready_status", "release_status", "buy_eligibility", "canonical_final_state")
    )
    if action in {"buy", "strong buy"} or "paper" in readiness or "watch" in readiness or "soft" in readiness:
        return "day_trade", "paper_entry_safe_default", True
    return "", "", False


def _expected_hold_window(horizon: str) -> str:
    if horizon == "scalp":
        return "15m-60m"
    if horizon == "day_trade":
        return "2h-EOD"
    if horizon == "swing_trade":
        return "1d-10d+"
    return "unknown"


def _normalize_paper_entry_bridge(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row or {})
    score, source = _entry_bridge_quality(r)
    if score is not None:
        r.setdefault("buy_quality_score", round(score, 2))
        r.setdefault("trade_quality_score", round(score, 2))
        r.setdefault("entry_quality_score", round(score, 2))
        r["paper_entry_bridge_score"] = round(score, 2)
        r["paper_entry_bridge_score_source"] = str(source)
        if not str(r.get("buy_quality_tier") or "").strip():
            if score >= 75.0:
                r["buy_quality_tier"] = "strong"
            elif score >= 60.0:
                r["buy_quality_tier"] = "moderate"
            elif score >= 50.0:
                r["buy_quality_tier"] = "qualified"
            else:
                r["buy_quality_tier"] = "weak"
    horizon, horizon_source, inferred = _infer_horizon_style(r)
    if horizon:
        r.setdefault("trade_horizon_style", horizon)
        r.setdefault("best_horizon_style", horizon)
        r["paper_entry_horizon_style"] = horizon
        r["paper_entry_horizon_source"] = horizon_source
        r["paper_entry_horizon_inferred"] = bool(inferred)
    action = str(r.get("action") or r.get("prediction") or "").strip().lower()
    readiness = " ".join(
        str(r.get(k) or "").strip().lower()
        for k in ("readiness_label", "paper_ready_status", "release_status", "buy_eligibility", "canonical_final_state")
    )
    if not str(r.get("buy_eligibility") or "").strip():
        if action in {"buy", "strong buy"}:
            r["buy_eligibility"] = "qualified_buy"
        elif "paper" in readiness or "watch" in readiness or "soft" in readiness:
            r["buy_eligibility"] = "paper_test_eligible"
    r["paper_entry_eligibility_bridge_v1"] = True
    return r


class PaperAutopilotEngine:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args, **kwargs):
        self.db_path = str(db_path or "state/ai_trading_memory.db")
        self.state_path = str(kwargs.get("state_path") or "state/paper_autopilot_state.json")
        self.interval_seconds = max(15, _to_int(kwargs.get("interval_seconds"), 45))
        self.max_stocks = max(1, _to_int(kwargs.get("max_stocks"), 6))
        self.max_crypto = max(0, _to_int(kwargs.get("max_crypto"), 2))
        self.max_new_positions_per_cycle = max(1, _to_int(kwargs.get("max_new_positions_per_cycle"), 2))
        self.configured_max_new_positions_per_cycle = int(self.max_new_positions_per_cycle)
        self.max_closes_per_cycle = max(1, _to_int(kwargs.get("max_closes_per_cycle"), 2))
        self.min_hold_seconds_intraday = max(30, _to_int(kwargs.get("min_hold_seconds_intraday"), 300))
        self.min_hold_seconds_swing = max(120, _to_int(kwargs.get("min_hold_seconds_swing"), 1800))
        self.cooldown_after_close_seconds = max(0, _to_int(kwargs.get("cooldown_after_close_seconds"), 300))
        self.paper_mode = str(kwargs.get("paper_mode") or "intraday").strip().lower() or "intraday"
        self._enabled = bool(kwargs.get("enabled", False))
        self.throughput_expansion_enabled = bool(kwargs.get("throughput_expansion_enabled", False))
        self.soft_candidate_expansion_enabled = bool(kwargs.get("soft_candidate_expansion_enabled", False))
        self.paper_entry_threshold_relief_points = max(0.0, min(12.0, _to_float(kwargs.get("paper_entry_threshold_relief_points"), 0.0)))
        self.paper_learning_capacity_expansion_v1 = bool(self.throughput_expansion_enabled and self.max_stocks >= 12)
        self.paper_learning_capacity_default_target = 12
        self.paper_learning_capacity_upper_bound = 15
        self.horizon_capacity_enabled = str(os.getenv("ASTRA_PAPER_HORIZON_CAPACITY_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        self.horizon_total_capacity = max(1, _to_int(os.getenv("ASTRA_PAPER_HORIZON_TOTAL_CAPACITY"), 20))
        self.horizon_swing_capacity = max(0, _to_int(os.getenv("ASTRA_PAPER_HORIZON_SWING_CAPACITY"), 8))
        self.horizon_day_capacity = max(0, _to_int(os.getenv("ASTRA_PAPER_HORIZON_DAY_CAPACITY"), 8))
        self.horizon_scalp_capacity = max(0, _to_int(os.getenv("ASTRA_PAPER_HORIZON_SCALP_CAPACITY"), 4))
        self.learned_exit_validation_bucket_configured = str(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_BUCKET_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
        self.learned_exit_validation_kill_switch = str(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_KILL_SWITCH", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.learned_exit_validation_max_exits_per_day = max(0, min(5, _to_int(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_MAX_EXITS_PER_DAY"), 5)))
        self.learned_exit_validation_max_exit_pct = max(0.0, min(25.0, _to_float(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_MAX_EXIT_PCT"), 25.0)))
        self.learned_exit_validation_min_confidence = max(0.0, min(100.0, _to_float(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_MIN_CONFIDENCE"), 70.0)))
        self.learned_exit_validation_min_evidence = max(1, _to_int(os.getenv("ASTRA_LEARNED_EXIT_VALIDATION_MIN_EVIDENCE"), 100))

        self.get_top_buys_fn = kwargs.get("get_top_buys_fn") if callable(kwargs.get("get_top_buys_fn")) else None
        self.get_latest_row_fn = kwargs.get("get_latest_row_fn") if callable(kwargs.get("get_latest_row_fn")) else None
        self.trade_intel = kwargs.get("trade_intel")
        self.exit_engine = kwargs.get("exit_engine")
        self.exit_learning = kwargs.get("exit_learning")
        self.alpaca_paper_broker = kwargs.get("alpaca_paper_broker")
        self.live_performance_fn = kwargs.get("live_performance_fn") if callable(kwargs.get("live_performance_fn")) else None
        self.freshness_manager = kwargs.get("freshness_manager")
        self.max_open_positions_total = max(2, _to_int(kwargs.get("max_open_positions_total"), 10))
        self.paper_learning_capacity_default_target = int(self.max_open_positions_total)
        self.paper_learning_capacity_upper_bound = max(
            int(self.max_open_positions_total),
            min(40, _to_int(os.getenv("ASTRA_PAPER_ADAPTIVE_CAPACITY_CEILING"), 40)),
        )
        self._adaptive_learning_capacity_policy: dict[str, Any] = {}
        self.paper_opportunity_allocator = kwargs.get("paper_opportunity_allocator")
        if self.paper_opportunity_allocator is None:
            try:
                self.paper_opportunity_allocator = PaperOpportunityAllocationEngineV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.paper_opportunity_allocator = None
        self.edge_development_suite = kwargs.get("edge_development_suite")
        if self.edge_development_suite is None:
            try:
                self.edge_development_suite = EdgeDevelopmentSuiteV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.edge_development_suite = None
        self.trade_management_portfolio_suite = kwargs.get("trade_management_portfolio_suite")
        if self.trade_management_portfolio_suite is None:
            try:
                self.trade_management_portfolio_suite = TradeManagementPortfolioIntelligenceV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.trade_management_portfolio_suite = None
        self.market_session_timing_suite = kwargs.get("market_session_timing_suite")
        if self.market_session_timing_suite is None:
            try:
                self.market_session_timing_suite = MarketSessionExecutionTimingV1()
            except Exception:
                self.market_session_timing_suite = None
        self.market_calendar_knowledge_suite = kwargs.get("market_calendar_knowledge_suite")
        if self.market_calendar_knowledge_suite is None:
            try:
                self.market_calendar_knowledge_suite = MarketCalendarKnowledgeIntelligenceV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.market_calendar_knowledge_suite = None
        self.broad_universe_intake_promotion_suite = kwargs.get("broad_universe_intake_promotion_suite")
        if self.broad_universe_intake_promotion_suite is None:
            try:
                self.broad_universe_intake_promotion_suite = BroadUniverseIntakePromotionV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.broad_universe_intake_promotion_suite = None
        self.adaptive_learning_infrastructure_suite = kwargs.get("adaptive_learning_infrastructure_suite")
        if self.adaptive_learning_infrastructure_suite is None:
            try:
                self.adaptive_learning_infrastructure_suite = AdaptiveLearningInfrastructureV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.adaptive_learning_infrastructure_suite = None
        self.replay_lifecycle_expectancy_suite = kwargs.get("replay_lifecycle_expectancy_suite")
        if self.replay_lifecycle_expectancy_suite is None:
            try:
                self.replay_lifecycle_expectancy_suite = ReplayLifecycleExpectancyLearningV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.replay_lifecycle_expectancy_suite = None
        self.regime_execution_survivability_suite = kwargs.get("regime_execution_survivability_suite")
        if self.regime_execution_survivability_suite is None:
            try:
                self.regime_execution_survivability_suite = RegimeExecutionSurvivabilityIntelligenceV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.regime_execution_survivability_suite = None
        self.adaptive_execution_exit_v2_suite = kwargs.get("adaptive_execution_exit_v2_suite")
        if self.adaptive_execution_exit_v2_suite is None:
            try:
                self.adaptive_execution_exit_v2_suite = AdaptiveExecutionExitIntelligenceV2(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.adaptive_execution_exit_v2_suite = None
        self.portfolio_diversification_v2_suite = kwargs.get("portfolio_diversification_v2_suite")
        if self.portfolio_diversification_v2_suite is None:
            try:
                self.portfolio_diversification_v2_suite = PortfolioDiversificationCorrelationV2(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.portfolio_diversification_v2_suite = None
        self.profit_seeking_exploration_suite = kwargs.get("profit_seeking_exploration_suite")
        if self.profit_seeking_exploration_suite is None:
            try:
                self.profit_seeking_exploration_suite = ProfitSeekingAdaptiveExplorationV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.profit_seeking_exploration_suite = None
        self.trade_lifecycle_excursion_suite = kwargs.get("trade_lifecycle_excursion_suite")
        if self.trade_lifecycle_excursion_suite is None:
            try:
                self.trade_lifecycle_excursion_suite = TradeLifecycleExcursionV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.trade_lifecycle_excursion_suite = None
        self.execution_participation_audit_suite = kwargs.get("execution_participation_audit_suite")
        if self.execution_participation_audit_suite is None:
            try:
                self.execution_participation_audit_suite = ExecutionParticipationAuditV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.execution_participation_audit_suite = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cycle_lock = threading.Lock()
        self._runtime_state: dict[str, Any] = {
            "last_cycle_utc": "",
            "last_cycle_summary": {},
            "last_execution_trace": {},
            "last_error": "",
            "last_close_by_symbol": {},
            "learned_exit_pending_sells": {},
            "learned_exit_daily": {},
            "learned_exit_rollback": {},
        }

        self._position_tracker = None
        if PositionTracker is not None:
            try:
                self._position_tracker = PositionTracker(db_path=self.db_path)
            except Exception:
                self._position_tracker = None

        self._ensure_schema()
        self._load_state_file()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1.0,
                    entry_price REAL NOT NULL DEFAULT 0.0,
                    exit_price REAL,
                    return_percent REAL,
                    friction_adjusted_return REAL,
                    entry_timestamp TEXT NOT NULL,
                    exit_timestamp TEXT,
                    hold_seconds REAL,
                    source_bucket TEXT,
                    lifecycle_notes TEXT,
                    row_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cols = {
                str(r[1] if isinstance(r, tuple) else r["name"]): True
                for r in (conn.execute("PRAGMA table_info(paper_positions)").fetchall() or [])
            }
            # Backward-safe migration for legacy paper_positions layouts.
            needed = {
                "status": "TEXT NOT NULL DEFAULT 'OPEN'",
                "quantity": "REAL NOT NULL DEFAULT 1.0",
                "entry_price": "REAL NOT NULL DEFAULT 0.0",
                "exit_price": "REAL",
                "return_percent": "REAL",
                "friction_adjusted_return": "REAL",
                "entry_timestamp": "TEXT",
                "exit_timestamp": "TEXT",
                "hold_seconds": "REAL",
                "source_bucket": "TEXT",
                "lifecycle_notes": "TEXT",
                "row_json": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for col, ddl in needed.items():
                if col in cols:
                    continue
                try:
                    conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {ddl}")
                except Exception:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol ON paper_positions(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_asset ON paper_positions(asset_type)")
            conn.commit()

    def _load_state_file(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                if "autopilot_enabled" in payload:
                    self._enabled = bool(payload.get("autopilot_enabled"))
                if isinstance(payload.get("last_close_by_symbol"), dict):
                    self._runtime_state["last_close_by_symbol"] = dict(payload.get("last_close_by_symbol") or {})
                if isinstance(payload.get("learned_exit_pending_sells"), dict):
                    self._runtime_state["learned_exit_pending_sells"] = dict(payload.get("learned_exit_pending_sells") or {})
                if isinstance(payload.get("learned_exit_daily"), dict):
                    self._runtime_state["learned_exit_daily"] = dict(payload.get("learned_exit_daily") or {})
                if isinstance(payload.get("learned_exit_rollback"), dict):
                    self._runtime_state["learned_exit_rollback"] = dict(payload.get("learned_exit_rollback") or {})
                if isinstance(payload.get("adaptive_learning_capacity_policy"), dict):
                    persisted_policy = dict(payload.get("adaptive_learning_capacity_policy") or {})
                    persisted_policy["policy_valid"] = bool(
                        persisted_policy.get("policy_valid")
                        and persisted_policy.get("paper_only_preserved", True)
                        and persisted_policy.get("behavior_safe_to_apply") is False
                        and not persisted_policy.get("broker_behavior_changed", False)
                    )
                    self._adaptive_learning_capacity_policy = persisted_policy
        except Exception:
            return

    def _save_state_file(self):
        payload = {
            "autopilot_enabled": bool(self._enabled),
            "paper_mode": self.paper_mode,
            "last_cycle_utc": self._runtime_state.get("last_cycle_utc") or "",
            "last_close_by_symbol": dict(self._runtime_state.get("last_close_by_symbol") or {}),
            "learned_exit_pending_sells": dict(self._runtime_state.get("learned_exit_pending_sells") or {}),
            "learned_exit_daily": dict(self._runtime_state.get("learned_exit_daily") or {}),
            "learned_exit_rollback": dict(self._runtime_state.get("learned_exit_rollback") or {}),
            "adaptive_learning_capacity_policy": dict(self._adaptive_learning_capacity_policy or {}),
        }
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), ensure_ascii=True)
        except Exception:
            pass

    def _min_hold_seconds(self) -> int:
        return self.min_hold_seconds_swing if self.paper_mode == "swing" else self.min_hold_seconds_intraday

    def _fetch_open_positions(self, asset_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = ["OPEN"]
        where = ["status=?"]
        if asset_type:
            where.append("asset_type=?")
            params.append(_norm_asset(asset_type))
        query = "SELECT * FROM paper_positions WHERE " + " AND ".join(where) + " ORDER BY entry_timestamp ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r or {}) for r in rows]

    def _count_open_position_rows(self) -> int:
        try:
            return int(len(self._fetch_open_positions() or []))
        except Exception:
            return 0

    def _count_open_positions(self) -> dict[str, int]:
        rows = self._fetch_open_positions()
        stock_keys: set[str] = set()
        crypto_keys: set[str] = set()
        for row in rows:
            symbol = str((row or {}).get("symbol") or "").upper().strip()
            asset = _norm_asset((row or {}).get("asset_type") or "stock")
            if not symbol:
                continue
            key = f"{asset}:{symbol}"
            if asset == "crypto":
                crypto_keys.add(key)
            else:
                stock_keys.add(key)
        return {"stock": int(len(stock_keys)), "crypto": int(len(crypto_keys))}

    def _cooldown_active(self, symbol: str) -> bool:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return False
        last_map = dict(self._runtime_state.get("last_close_by_symbol") or {})
        ts = _to_float(last_map.get(sym), 0.0)
        if ts <= 0:
            return False
        return (time.time() - ts) < float(self.cooldown_after_close_seconds)

    def _learned_exit_today_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _learned_exit_daily_state(self) -> dict[str, Any]:
        today = self._learned_exit_today_key()
        daily = dict(self._runtime_state.get("learned_exit_daily") or {})
        state = dict(daily.get(today) or {})
        state.setdefault("used", 0)
        state.setdefault("candidates", 0)
        state.setdefault("rejected", 0)
        state.setdefault("baseline_exits", 0)
        state.setdefault("learned_corrected_exits", 0)
        state.setdefault("by_horizon", {})
        state.setdefault("policies_used", [])
        state.setdefault("rejection_reasons", [])
        state.setdefault("capacity_freed", 0)
        daily[today] = state
        self._runtime_state["learned_exit_daily"] = daily
        return state

    def _update_learned_exit_daily_state(self, state: dict[str, Any]) -> None:
        daily = dict(self._runtime_state.get("learned_exit_daily") or {})
        daily[self._learned_exit_today_key()] = dict(state or {})
        self._runtime_state["learned_exit_daily"] = daily

    def _learned_exit_event_path(self) -> str:
        return os.path.join(os.path.dirname(self.state_path) or "state", "learned_exit_validation_events.jsonl")

    def _append_learned_exit_event(self, event: dict[str, Any]) -> None:
        try:
            payload = {
                "timestamp": _now_iso(),
                "source": "paper_autopilot_learned_exit_validation_bucket",
                **dict(event or {}),
                "paper_only": True,
                "behavior_safe_to_apply": False,
            }
            path = self._learned_exit_event_path()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def _learned_exit_bucket_enabled_runtime(self) -> tuple[bool, str]:
        if not self.learned_exit_validation_bucket_configured:
            return False, "validation_bucket_config_disabled"
        if self.learned_exit_validation_kill_switch:
            return False, "kill_switch_enabled"
        rollback = dict(self._runtime_state.get("learned_exit_rollback") or {})
        if bool(rollback.get("disabled")):
            return False, str(rollback.get("reason") or "auto_rollback_active")
        safety = self._alpaca_safety_snapshot()
        if not bool(safety.get("paper_mode_verified")):
            return False, "paper_mode_not_verified"
        if bool(safety.get("live_endpoint_detected")):
            return False, "live_endpoint_detected"
        if not bool(safety.get("broker_execution_enabled")):
            return False, "broker_execution_not_ready"
        if self.learned_exit_validation_max_exits_per_day <= 0:
            return False, "daily_learned_exit_limit_zero"
        return True, "enabled"

    def _learned_exit_bucket_remaining_today(self) -> int:
        state = self._learned_exit_daily_state()
        return max(0, int(self.learned_exit_validation_max_exits_per_day) - _to_int(state.get("used"), 0))

    def _learned_exit_pending_map(self) -> dict[str, Any]:
        return dict(self._runtime_state.get("learned_exit_pending_sells") or {})

    def _set_learned_exit_pending_map(self, pending: dict[str, Any]) -> None:
        self._runtime_state["learned_exit_pending_sells"] = dict(pending or {})

    def _position_pending_sell(self, symbol: str, position_id: str = "") -> tuple[bool, str]:
        sym = str(symbol or "").upper().strip()
        pid = str(position_id or "").strip()
        pending = self._learned_exit_pending_map()
        for key, row in pending.items():
            if not isinstance(row, dict):
                continue
            if str(row.get("terminal") or "").lower() == "true":
                continue
            if sym and str(row.get("symbol") or "").upper().strip() == sym:
                return True, f"local_pending_sell:{key}"
            if pid and str(row.get("position_id") or "").strip() == pid:
                return True, f"local_pending_sell:{key}"
        return False, ""

    def _broker_pending_sell_exists(self, symbol: str) -> tuple[bool, str]:
        broker = self.alpaca_paper_broker
        sym = str(symbol or "").upper().strip()
        if not sym:
            return False, ""
        if broker is None or not hasattr(broker, "orders"):
            return False, "broker_orders_unavailable"
        try:
            payload = dict(broker.orders(status="open", limit=50) or {})
        except Exception as exc:
            return True, f"broker_open_orders_exception:{str(exc)[:100]}"
        if not bool(payload.get("ok")):
            return True, str(payload.get("error") or "broker_open_orders_fetch_failed")[:140]
        active_statuses = {"new", "accepted", "pending_new", "partially_filled", "held", "accepted_for_bidding", "calculated"}
        for order in list(payload.get("orders") or []):
            if not isinstance(order, dict):
                continue
            if str(order.get("symbol") or "").upper().strip() != sym:
                continue
            if str(order.get("side") or "").lower() != "sell":
                continue
            status = str(order.get("status") or "").lower().strip()
            if not status or status in active_statuses:
                return True, f"broker_pending_sell:{order.get('id') or order.get('client_order_id') or status}"
        return False, ""

    def _total_closed_trades(self) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(1) AS n FROM paper_positions WHERE status='CLOSED'").fetchone()
                return _to_int((dict(row or {})).get("n"), 0)
        except Exception:
            return 0

    def _learned_exit_candidate(self, open_row: dict[str, Any], latest_row: dict[str, Any], broker_position: dict[str, Any]) -> dict[str, Any]:
        symbol = str(open_row.get("symbol") or "").upper().strip()
        pid = str(open_row.get("position_id") or "").strip()
        entry = _to_float(open_row.get("entry_price"), 0.0)
        current = _to_float(latest_row.get("price"), 0.0)
        notes = _safe_json_load(open_row.get("lifecycle_notes"))
        entry_payload = _safe_json_load(open_row.get("row_json"))
        horizon, _, _ = _infer_horizon_style({**entry_payload, **dict(open_row or {})})
        horizon = horizon or "unknown"
        confidence = _to_float(open_row.get("confidence"), _to_float(entry_payload.get("confidence"), _to_float(entry_payload.get("predicted_win_probability"), 0.0)))
        evidence = self._total_closed_trades()
        if entry <= 0.0 or current <= 0.0:
            return {"eligible": False, "reason": "invalid_price"}
        ret = ((current - entry) / entry) * 100.0
        peak = max(_to_float(notes.get("peak_unrealized_pnl_percent"), ret), ret)
        drawdown = max(0.0, peak - ret)
        hold_seconds = _to_float(notes.get("hold_seconds"), _to_float(open_row.get("hold_seconds"), 0.0))
        if evidence < int(self.learned_exit_validation_min_evidence):
            return {"eligible": False, "reason": "insufficient_evidence", "evidence_count": evidence}
        if confidence < float(self.learned_exit_validation_min_confidence):
            return {"eligible": False, "reason": "policy_confidence_below_threshold", "policy_confidence": round(confidence, 3), "evidence_count": evidence}
        policy = ""
        why = ""
        if peak >= 2.0 and drawdown >= 0.8 and ret > 0.0:
            policy = "profit_lock_exit"
            why = "peak_profit_giveback_protection"
        elif peak >= 1.2 and drawdown >= 1.4:
            policy = "continuation_failure_exit"
            why = "drawdown_from_peak_continuation_failure"
        elif horizon == "scalp" and hold_seconds >= 45 * 60 and ret > 0.0:
            policy = "horizon_specific_exit"
            why = "scalp_hold_window_profit_validation"
        elif horizon == "day_trade" and hold_seconds >= 4 * 60 * 60 and ret > 0.0:
            policy = "horizon_specific_exit"
            why = "day_trade_hold_window_profit_validation"
        elif horizon == "swing_trade" and hold_seconds >= 3 * 24 * 60 * 60 and peak > 0.0 and drawdown >= 1.0:
            policy = "catalyst_decay_exit"
            why = "swing_trade_peak_decay_validation"
        if policy not in {"horizon_specific_exit", "profit_lock_exit", "continuation_failure_exit", "catalyst_decay_exit"}:
            return {
                "eligible": False,
                "reason": "no_evidence_backed_learned_exit_signal",
                "return_percent": round(ret, 4),
                "peak_unrealized_pnl_percent": round(peak, 4),
                "drawdown_from_peak_percent": round(drawdown, 4),
                "evidence_count": evidence,
                "policy_confidence": round(confidence, 3),
            }
        broker_available_qty = _to_float(
            broker_position.get("qty_available"),
            _to_float(broker_position.get("qty"), _to_float(open_row.get("quantity"), 0.0)),
        )
        original_requested_qty = round(broker_available_qty, 6) if broker_available_qty > 0.0 else 0.0
        normalized_qty = _floor_fractional_qty(broker_available_qty, 6)
        precision_delta = max(0.0, original_requested_qty - broker_available_qty)
        normalization_applied = bool(original_requested_qty > broker_available_qty or normalized_qty < original_requested_qty)
        if normalized_qty <= 0.0:
            return {"eligible": False, "reason": "broker_confirmed_quantity_required", "evidence_count": evidence}
        return {
            "eligible": True,
            "symbol": symbol,
            "position_id": pid,
            "policy": policy,
            "reason": why,
            "horizon": horizon,
            "evidence_count": evidence,
            "policy_confidence": round(confidence, 3),
            "qty": normalized_qty,
            "original_requested_qty": original_requested_qty,
            "broker_available_qty": round(broker_available_qty, 9),
            "normalized_sell_qty": normalized_qty,
            "normalization_reason": "floor_to_broker_available_fractional_qty" if normalization_applied else "broker_available_qty_safe",
            "precision_delta": round(precision_delta, 12),
            "normalization_applied": normalization_applied,
            "entry_price": round(entry, 6),
            "current_price": round(current, 6),
            "unrealized_pnl_pct": round(ret, 4),
            "peak_unrealized_pnl_percent": round(peak, 4),
            "drawdown_from_peak_percent": round(drawdown, 4),
            "hold_seconds": round(hold_seconds, 2),
            "regime": str(entry_payload.get("regime_context") or entry_payload.get("market_regime") or ""),
            "catalyst": str(entry_payload.get("catalyst") or entry_payload.get("catalyst_type") or entry_payload.get("detected_catalyst") or "unknown_catalyst"),
            "expected_improvement": "reduced_giveback_and_capacity_release",
        }

    def _submit_guarded_learned_exit_sell(
        self,
        open_row: dict[str, Any],
        latest_row: dict[str, Any],
        broker_position: dict[str, Any],
    ) -> dict[str, Any]:
        enabled, reason = self._learned_exit_bucket_enabled_runtime()
        state = self._learned_exit_daily_state()
        if not enabled:
            return {"ok": False, "submitted": False, "reason": reason}
        if self._learned_exit_bucket_remaining_today() <= 0:
            return {"ok": False, "submitted": False, "reason": "daily_learned_exit_bucket_full"}
        state["candidates"] = _to_int(state.get("candidates"), 0) + 1
        self._update_learned_exit_daily_state(state)
        candidate = self._learned_exit_candidate(open_row, latest_row, broker_position)
        if not bool(candidate.get("eligible")):
            state["rejected"] = _to_int(state.get("rejected"), 0) + 1
            reasons = list(state.get("rejection_reasons") or [])
            reasons.append(str(candidate.get("reason") or "candidate_not_eligible"))
            state["rejection_reasons"] = reasons[-20:]
            self._update_learned_exit_daily_state(state)
            self._append_learned_exit_event({"event": "validation_candidate_rejected", **candidate})
            return {"ok": False, "submitted": False, "reason": str(candidate.get("reason") or "candidate_not_eligible"), "candidate": candidate}
        symbol = str(candidate.get("symbol") or "").upper().strip()
        pid = str(candidate.get("position_id") or "").strip()
        local_pending, local_reason = self._position_pending_sell(symbol, pid)
        if local_pending:
            return {"ok": False, "submitted": False, "reason": local_reason}
        broker_pending, broker_reason = self._broker_pending_sell_exists(symbol)
        if broker_pending:
            self._append_learned_exit_event({"event": "validation_candidate_rejected", **candidate, "reason": broker_reason})
            return {"ok": False, "submitted": False, "reason": broker_reason}
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "submit_paper_order"):
            return {"ok": False, "submitted": False, "reason": "alpaca_paper_broker_unavailable"}
        normalized_qty = _to_float(candidate.get("normalized_sell_qty"), _to_float(candidate.get("qty"), 0.0))
        if normalized_qty <= 0.0:
            self._append_learned_exit_event({"event": "validation_candidate_rejected", **candidate, "reason": "normalized_sell_qty_zero"})
            return {"ok": False, "submitted": False, "reason": "normalized_sell_qty_zero", "candidate": candidate}
        client_order_id = f"astra-lexit-{pid[:10] or symbol[:8]}-{self._learned_exit_today_key().replace('-', '')}"[:48]
        order = {
            "symbol": symbol,
            "side": "sell",
            "type": "market",
            "time_in_force": "day",
            "qty": normalized_qty,
            "client_order_id": client_order_id,
            "existing_exit_signal_verified": True,
            "learned_exit_validation_bucket": True,
            "learned_exit_policy": str(candidate.get("policy") or ""),
            "paper_only": True,
            "natural_exit_logic_preserved": True,
        }
        try:
            result = dict(broker.submit_paper_order(order) or {})
        except Exception as exc:
            result = {"ok": False, "error": f"broker_sell_submit_exception:{str(exc)[:120]}"}
        retry_status = "not_needed"
        retry_result: dict[str, Any] = {}
        if not bool(result.get("ok")):
            broker_error = str(result.get("error") or "")[:180]
            available_from_error = _parse_available_qty_from_error(broker_error)
            retry_qty = _floor_fractional_qty(available_from_error, 6)
            if (
                "insufficient qty available" in broker_error.lower()
                and retry_qty > 0.0
                and retry_qty < normalized_qty
            ):
                retry_order = {**order, "qty": retry_qty, "client_order_id": f"{client_order_id[:39]}-r1"}
                retry_candidate = {
                    **candidate,
                    "qty": retry_qty,
                    "normalized_sell_qty": retry_qty,
                    "broker_available_qty": round(available_from_error, 9),
                    "normalization_applied": True,
                    "normalization_reason": "retry_with_broker_error_available_qty",
                    "precision_delta": round(max(0.0, normalized_qty - available_from_error), 12),
                    "retry_status": "RETRY_WITH_NORMALIZED_QTY",
                }
                self._append_learned_exit_event({
                    "event": "sell_submit_rejected",
                    **candidate,
                    "broker_error": broker_error,
                    "retry_status": "RETRY_WITH_NORMALIZED_QTY",
                    "retry_qty": retry_qty,
                })
                try:
                    retry_result = dict(broker.submit_paper_order(retry_order) or {})
                except Exception as exc:
                    retry_result = {"ok": False, "error": f"broker_sell_retry_exception:{str(exc)[:120]}"}
                if bool(retry_result.get("ok")):
                    result = retry_result
                    candidate = retry_candidate
                    retry_status = "retry_submitted"
                else:
                    retry_status = "retry_failed"
                    self._append_learned_exit_event({
                        "event": "sell_submit_rejected",
                        **retry_candidate,
                        "broker_error": str(retry_result.get("error") or "retry_submit_failed")[:180],
                        "retry_status": retry_status,
                    })
                    return {
                        "ok": False,
                        "submitted": False,
                        "reason": str(retry_result.get("error") or broker_error or "sell_submit_failed")[:140],
                        "candidate": retry_candidate,
                    }
            else:
                self._append_learned_exit_event({
                    "event": "sell_submit_rejected",
                    **candidate,
                    "broker_error": broker_error,
                    "retry_status": "blocked_or_not_applicable",
                })
                return {"ok": False, "submitted": False, "reason": str(result.get("error") or "sell_submit_failed")[:140], "candidate": candidate}
        broker_order = dict(result.get("order") or {})
        pending_id = str(broker_order.get("id") or client_order_id)
        pending = self._learned_exit_pending_map()
        pending[pending_id] = {
            **candidate,
            "order_id": str(broker_order.get("id") or ""),
            "client_order_id": client_order_id,
            "submitted_at": _now_iso(),
            "status": str(broker_order.get("status") or "submitted"),
            "terminal": "false",
            "retry_status": retry_status,
        }
        self._set_learned_exit_pending_map(pending)
        self._append_learned_exit_event({
            "event": "sell_submitted_pending_fill",
            **candidate,
            "order_id": broker_order.get("id"),
            "client_order_id": broker_order.get("client_order_id") or client_order_id,
            "order_status": broker_order.get("status"),
            "retry_status": retry_status,
        })
        return {"ok": True, "submitted": True, "pending_order_id": pending_id, "candidate": candidate}

    def _refresh_learned_exit_pending_sells(self) -> dict[str, Any]:
        broker = self.alpaca_paper_broker
        pending = self._learned_exit_pending_map()
        if not pending:
            return {"checked": 0, "filled": 0, "active": 0, "rejected": 0}
        if broker is None or not hasattr(broker, "order"):
            return {"checked": 0, "filled": 0, "active": len(pending), "rejected": 0, "reason": "broker_order_lookup_unavailable"}
        checked = filled = rejected = active = 0
        remaining: dict[str, Any] = {}
        terminal_reject = {"rejected", "canceled", "expired", "stopped", "done_for_day"}
        for key, item in pending.items():
            if not isinstance(item, dict):
                continue
            order_id = str(item.get("order_id") or "").strip()
            if not order_id:
                remaining[key] = item
                active += 1
                continue
            checked += 1
            try:
                payload = dict(broker.order(order_id) or {})
            except Exception as exc:
                remaining[key] = {**item, "last_check_error": f"order_lookup_exception:{str(exc)[:100]}"}
                active += 1
                continue
            if not bool(payload.get("ok")):
                remaining[key] = {**item, "last_check_error": str(payload.get("error") or "order_lookup_failed")[:140]}
                active += 1
                continue
            order = dict(payload.get("order") or {})
            status = str(order.get("status") or item.get("status") or "").lower().strip()
            if status == "filled":
                symbol = str(item.get("symbol") or "").upper().strip()
                pid = str(item.get("position_id") or "").strip()
                open_rows = [r for r in self._fetch_open_positions() if str(r.get("position_id") or "") == pid or str(r.get("symbol") or "").upper().strip() == symbol]
                fill_price = _to_float(order.get("filled_avg_price"), _to_float(item.get("current_price"), 0.0))
                latest = {"symbol": symbol, "price": fill_price, "source": "alpaca_paper_order_fill", "quote_quality": "broker_confirmed_fill", "provider_used": "alpaca_paper", "timestamp": _now_iso()}
                close_result = {"ok": False, "error": "open_position_not_found_for_filled_order"}
                if open_rows:
                    close_result = self._close_position(open_rows[0], latest, f"learned_exit_validation:{item.get('policy')}")
                state = self._learned_exit_daily_state()
                state["used"] = _to_int(state.get("used"), 0) + (1 if close_result.get("ok") else 0)
                state["learned_corrected_exits"] = _to_int(state.get("learned_corrected_exits"), 0) + (1 if close_result.get("ok") else 0)
                by_horizon = dict(state.get("by_horizon") or {})
                horizon = str(item.get("horizon") or "unknown")
                by_horizon[horizon] = _to_int(by_horizon.get(horizon), 0) + (1 if close_result.get("ok") else 0)
                state["by_horizon"] = by_horizon
                policies = list(state.get("policies_used") or [])
                policies.append(str(item.get("policy") or "unknown_policy"))
                state["policies_used"] = policies[-20:]
                state["capacity_freed"] = _to_int(state.get("capacity_freed"), 0) + (1 if close_result.get("ok") else 0)
                self._update_learned_exit_daily_state(state)
                self._append_learned_exit_event({
                    "event": "sell_filled_lifecycle_closed",
                    **item,
                    "filled_avg_price": fill_price,
                    "filled_qty": order.get("filled_qty"),
                    "close_result": close_result,
                    "lesson_type": "learned_corrected_exit_actual_paper",
                    "learning_takeaway": "broker_confirmed_learned_exit_sample_captured" if close_result.get("ok") else "filled_order_without_matching_open_row",
                })
                filled += 1
            elif status in terminal_reject:
                self._append_learned_exit_event({"event": "sell_terminal_not_filled", **item, "order_status": status})
                rejected += 1
            else:
                remaining[key] = {**item, "status": status or "open", "last_checked_at": _now_iso()}
                active += 1
        self._set_learned_exit_pending_map(remaining)
        return {"checked": checked, "filled": filled, "active": active, "rejected": rejected}

    def _learned_exit_runtime_summary(self) -> dict[str, Any]:
        enabled, reason = self._learned_exit_bucket_enabled_runtime()
        state = self._learned_exit_daily_state()
        pending = self._learned_exit_pending_map()
        rollback = dict(self._runtime_state.get("learned_exit_rollback") or {})
        used = _to_int(state.get("used"), 0)
        return {
            "learned_exit_validation_bucket_enabled": bool(enabled),
            "learned_exit_validation_bucket_enabled_reason": reason,
            "learned_exit_validation_bucket_configured": bool(self.learned_exit_validation_bucket_configured),
            "learned_exit_validation_kill_switch": bool(self.learned_exit_validation_kill_switch),
            "learned_exit_duplicate_exit_prevention_verified": True,
            "learned_exit_broker_fill_confirmation_verified": True,
            "learned_exit_validation_runtime_path_enabled": True,
            "paper_sell_route_guarded": True,
            "learned_exits_used_today": used,
            "learned_exits_remaining_today": max(0, int(self.learned_exit_validation_max_exits_per_day) - used),
            "max_learning_corrected_exits_per_day": int(self.learned_exit_validation_max_exits_per_day),
            "max_learning_corrected_exit_pct": round(float(self.learned_exit_validation_max_exit_pct), 3),
            "learned_exit_candidates_today": _to_int(state.get("candidates"), 0),
            "rejected_learned_exit_candidates": _to_int(state.get("rejected"), 0),
            "rejection_reasons": list(state.get("rejection_reasons") or [])[-10:],
            "learned_exits_by_horizon": dict(state.get("by_horizon") or {}),
            "policies_used_today": list(state.get("policies_used") or [])[-8:],
            "current_active_learned_exit_tests": int(len(pending)),
            "baseline_exits_today": _to_int(state.get("baseline_exits"), 0),
            "learned_corrected_exits_today": _to_int(state.get("learned_corrected_exits"), 0),
            "capacity_freed_by_learned_exits": _to_int(state.get("capacity_freed"), 0),
            "rollback_status": "auto_disabled" if bool(rollback.get("disabled")) else "armed",
            "rollback_reason": str(rollback.get("reason") or "none"),
            "rollback_triggered_at": str(rollback.get("triggered_at") or ""),
            "kill_switch_status": "enabled" if self.learned_exit_validation_kill_switch else "disabled",
            "baseline_vs_learned_status": "active_controlled_ab_validation" if enabled else f"disabled:{reason}",
            "learned_bucket_outperforming": False,
        }

    def _collect_candidate_rows(self) -> list[dict[str, Any]]:
        if not self.get_top_buys_fn:
            return []
        try:
            payload = self.get_top_buys_fn() or {}
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []

        def _rows_from(path: list[str]) -> list[dict[str, Any]]:
            cur: Any = payload
            for k in path:
                if not isinstance(cur, dict):
                    return []
                cur = cur.get(k)
            return [dict(x) for x in (cur or []) if isinstance(x, dict)] if isinstance(cur, list) else []

        rows: list[dict[str, Any]] = []
        rows.extend(_rows_from(["stocks", "final"]))
        rows.extend(_rows_from(["top_action_views", "canonical_decision_views", "stocks_buy_candidates"]))
        rows.extend(_rows_from(["stocks", "qualified"]))

        dedup: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            row = _normalize_paper_entry_bridge(row)
            row.setdefault("symbol", sym)
            row.setdefault("asset_type", "stock")
            dedup.append(row)
        if self.edge_development_suite is not None and hasattr(self.edge_development_suite, "decorate_candidates"):
            try:
                dedup = list(self.edge_development_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.trade_management_portfolio_suite is not None and hasattr(self.trade_management_portfolio_suite, "decorate_candidates"):
            try:
                dedup = list(self.trade_management_portfolio_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.adaptive_learning_infrastructure_suite is not None and hasattr(self.adaptive_learning_infrastructure_suite, "decorate_candidates"):
            try:
                dedup = list(self.adaptive_learning_infrastructure_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.replay_lifecycle_expectancy_suite is not None and hasattr(self.replay_lifecycle_expectancy_suite, "decorate_candidates"):
            try:
                dedup = list(self.replay_lifecycle_expectancy_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.regime_execution_survivability_suite is not None and hasattr(self.regime_execution_survivability_suite, "decorate_candidates"):
            try:
                dedup = list(self.regime_execution_survivability_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.adaptive_execution_exit_v2_suite is not None and hasattr(self.adaptive_execution_exit_v2_suite, "decorate_candidates"):
            try:
                dedup = list(self.adaptive_execution_exit_v2_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.market_calendar_knowledge_suite is not None and hasattr(self.market_calendar_knowledge_suite, "decorate_candidates"):
            try:
                dedup = list(self.market_calendar_knowledge_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.broad_universe_intake_promotion_suite is not None and hasattr(self.broad_universe_intake_promotion_suite, "decorate_candidates"):
            try:
                dedup = list(self.broad_universe_intake_promotion_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "decorate_candidates"):
            try:
                dedup = list(self.paper_opportunity_allocator.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.profit_seeking_exploration_suite is not None and hasattr(self.profit_seeking_exploration_suite, "decorate_candidates"):
            try:
                dedup = list(self.profit_seeking_exploration_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.portfolio_diversification_v2_suite is not None and hasattr(self.portfolio_diversification_v2_suite, "rank_for_paper_selection"):
            try:
                return list(self.portfolio_diversification_v2_suite.rank_for_paper_selection(dedup) or dedup)
            except Exception:
                return dedup
        return dedup

    def _entry_commitment_gate_v1(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        row = _normalize_paper_entry_bridge(row)
        eligibility = str(row.get("buy_eligibility") or "").strip().lower()
        tier = str(row.get("buy_quality_tier") or "").strip().lower()
        uncertainty_tier = str(row.get("uncertainty_tier") or "").strip().lower()
        uncertainty_score = _to_float(row.get("uncertainty_score"), 50.0)
        discipline_action = str(row.get("core_decision_discipline_action") or "").strip().lower()
        discipline_tier = str(row.get("core_decision_discipline_tier") or "").strip().lower()
        deploy = str(row.get("hero_deployment_status") or row.get("canonical_final_state") or "").strip().lower()
        quality = _to_float(row.get("buy_quality_score"), _to_float(row.get("trade_quality_score"), 0.0))
        confidence = _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0))
        confidence = confidence if confidence > 1.0 else confidence * 100.0
        follow = str(row.get("follow_through_state") or "").strip().lower()
        entry_edge = _to_float(row.get("entry_edge_score"), 0.0)
        consensus = _to_float(row.get("consensus_strength"), 0.0)
        disagreement = _to_float(row.get("persona_disagreement_index"), 50.0)

        if any(x in uncertainty_tier for x in ("extreme",)):
            return False, "uncertainty_extreme", {"commitment_score": 0.0}
        if any(x in eligibility for x in ("blocked", "reject", "avoid")):
            return False, "eligibility_blocked", {"commitment_score": 0.0}
        if any(x in deploy for x in ("blocked", "rejected")):
            return False, "deployment_blocked", {"commitment_score": 0.0}
        if discipline_action in {"reject", "blocked"}:
            return False, "discipline_reject", {"commitment_score": 0.0}
        if discipline_tier in {"reject"}:
            return False, "discipline_tier_reject", {"commitment_score": 0.0}
        if uncertainty_tier == "high_uncertainty":
            return False, "uncertainty_high", {"commitment_score": 0.0}
        if uncertainty_score >= 74.0:
            return False, "uncertainty_score_high", {"commitment_score": 0.0}

        quality_floor = 44.0 if self.soft_candidate_expansion_enabled else 48.0
        confidence_floor = 49.0 if self.soft_candidate_expansion_enabled else 52.0
        if quality < quality_floor and confidence < confidence_floor:
            return False, "quality_confidence_too_low", {"commitment_score": 0.0}

        positive_signals = 0
        if any(x in eligibility for x in ("qualified", "buy", "paper_ready", "watchlist")):
            positive_signals += 1
        if any(x in tier for x in ("elite", "strong", "moderate", "actionable", "qualified")):
            positive_signals += 1
        if quality >= 55.0:
            positive_signals += 1
        if confidence >= 56.0:
            positive_signals += 1
        if bool(row.get("paper_profit_candidate_eligible", False)) and _to_float(row.get("risk_adjusted_profit_score"), 0.0) >= 58.0:
            positive_signals += 1

        if positive_signals < 2 and not (
            self.soft_candidate_expansion_enabled
            and quality >= quality_floor
            and confidence >= confidence_floor
        ):
            return False, "insufficient_positive_signals", {"commitment_score": 0.0}

        high_uncertainty_quality_floor = 60.0 if self.soft_candidate_expansion_enabled else 64.0
        if any(x in uncertainty_tier for x in ("high",)) and quality < high_uncertainty_quality_floor:
            return False, "high_uncertainty_not_high_quality", {"commitment_score": 0.0}

        commitment_score = (
            (quality * 0.34)
            + (confidence * 0.26)
            + (consensus * 0.12)
            + (max(0.0, 50.0 + (entry_edge * 35.0)) * 0.08)
            + (max(0.0, 100.0 - disagreement) * 0.12)
            + (max(0.0, 100.0 - uncertainty_score) * 0.08)
        )
        if follow in {"strong_follow_through", "healthy_continuation"}:
            commitment_score += 4.0
        elif follow in {"weak_follow_through_risk", "deteriorating"}:
            commitment_score -= 5.0
        if discipline_action in {"release_candidate", "paper_ready", "hold"}:
            commitment_score += 3.0
        if "watchlist" in eligibility:
            commitment_score -= 2.0
        commitment_score = max(0.0, min(100.0, commitment_score))

        base_commitment_floor = max(50.0, 58.0 - self.paper_entry_threshold_relief_points)
        watchlist_commitment_floor = max(56.0, 64.0 - self.paper_entry_threshold_relief_points)
        if commitment_score < base_commitment_floor:
            return False, "entry_commitment_below_threshold", {"commitment_score": round(commitment_score, 2)}
        if commitment_score < watchlist_commitment_floor and "watchlist" in eligibility:
            return False, "watchlist_commitment_not_strong_enough", {"commitment_score": round(commitment_score, 2)}

        return True, "eligible", {
            "commitment_score": round(commitment_score, 2),
            "confidence_at_entry": round(confidence, 2),
            "uncertainty_tier": uncertainty_tier or "unknown",
            "uncertainty_score": round(uncertainty_score, 2),
        }

    def _is_candidate_paper_eligible(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        return self._entry_commitment_gate_v1(row)

    def _alpaca_paper_broker_enabled(self) -> bool:
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "safety_status"):
            return False
        try:
            safety = broker.safety_status()
            return bool(isinstance(safety, dict) and safety.get("broker_execution_enabled"))
        except Exception:
            return False

    def _alpaca_safety_snapshot(self) -> dict[str, Any]:
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "safety_status"):
            return {
                "alpaca_enabled": False,
                "paper_mode_verified": False,
                "broker_execution_enabled": False,
                "safety_reasons": ["alpaca_paper_broker_unavailable"],
            }
        try:
            safety = dict(broker.safety_status() or {})
        except Exception as exc:
            safety = {"safety_reasons": [f"alpaca_safety_status_exception:{str(exc)[:120]}"]}
        return {
            "alpaca_enabled": bool(safety.get("enabled_requested")),
            "paper_mode_verified": bool(safety.get("paper_mode_verified")),
            "broker_execution_enabled": bool(safety.get("broker_execution_enabled")),
            "safety_reasons": list(safety.get("safety_reasons") or []),
            "live_endpoint_detected": bool(safety.get("live_endpoint_detected", False)),
            "live_endpoint_rejected": bool(safety.get("live_endpoint_rejected", True)),
        }

    def _broker_open_symbols_snapshot(self) -> dict[str, Any]:
        safety = self._alpaca_safety_snapshot()
        out = {
            "broker_reconciliation_active": False,
            "broker_positions_fetch_ok": False,
            "broker_open_positions_count": 0,
            "broker_open_symbols": set(),
            "broker_positions_error_sanitized": "",
        }
        if not safety.get("broker_execution_enabled"):
            return out
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "positions"):
            out["broker_reconciliation_active"] = True
            out["broker_positions_error_sanitized"] = "broker_positions_unavailable"
            return out
        out["broker_reconciliation_active"] = True
        try:
            payload = dict(broker.positions() or {})
            if bool(payload.get("ok")):
                symbols = set()
                positions_by_symbol: dict[str, dict[str, Any]] = {}
                for row in list(payload.get("positions") or []):
                    if not isinstance(row, dict):
                        continue
                    sym = str(row.get("symbol") or "").upper().strip()
                    if sym:
                        symbols.add(sym)
                        positions_by_symbol[sym] = dict(row)
                out["broker_positions_fetch_ok"] = True
                out["broker_open_symbols"] = symbols
                out["broker_position_by_symbol"] = positions_by_symbol
                out["broker_open_positions_count"] = int(len(symbols))
            else:
                out["broker_positions_error_sanitized"] = str(payload.get("error") or "broker_positions_fetch_failed")[:180]
        except Exception as exc:
            out["broker_positions_error_sanitized"] = f"broker_positions_exception:{str(exc)[:120]}"
        return out

    def _sanitize_broker_error(self, result: dict[str, Any] | None) -> str:
        if not isinstance(result, dict):
            return ""
        raw = str(
            result.get("broker_error")
            or result.get("open_confirmation_reason")
            or result.get("error")
            or result.get("reason")
            or ""
        ).strip()
        return raw[:180]

    def _merge_latest_quote_for_submission(
        self,
        row: dict[str, Any],
        quote: dict[str, Any] | None,
        entry_price: float,
    ) -> dict[str, Any]:
        submit_row = dict(row or {})
        q = dict(quote or {})
        symbol = str(submit_row.get("symbol") or q.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(submit_row.get("asset_type") or q.get("asset_type") or "stock")
        submit_row["symbol"] = symbol
        submit_row["asset_type"] = asset_type
        submit_row["price"] = entry_price
        submit_row["current_price"] = entry_price
        submit_row["last_price_seen"] = entry_price

        for key in (
            "prev_close",
            "provider_used",
            "source",
            "quote_quality",
            "cache_hit",
            "data_unavailable_reason",
            "quote_timestamp",
            "timestamp",
            "last_snapshot_timestamp",
            "last_updated_utc",
        ):
            if q.get(key) not in (None, ""):
                submit_row[key] = q.get(key)

        quote_ts = (
            submit_row.get("quote_timestamp")
            or submit_row.get("timestamp")
            or submit_row.get("last_snapshot_timestamp")
            or submit_row.get("last_updated_utc")
        )
        age = _age_seconds_from_iso(quote_ts)
        if age is not None:
            submit_row["quote_age_seconds"] = round(age, 3)
            submit_row["freshness_seconds"] = round(age, 3)
        elif str(submit_row.get("quote_quality") or "").lower() == "live":
            submit_row.setdefault("quote_age_seconds", 0.0)
            submit_row.setdefault("freshness_seconds", 0.0)
        elif q and entry_price > 0.0:
            # get_latest_row_fn is invoked immediately before broker preflight. Some
            # runtime/promoted snapshots carry a valid price but no timestamp; mark
            # freshness for this just-fetched local snapshot without relaxing any
            # downstream broker, session, portfolio, or limit gates.
            submit_row.setdefault("quote_quality", "runtime_snapshot")
            submit_row["quote_age_seconds"] = 0.0
            submit_row["freshness_seconds"] = 0.0

        submit_row["latest_quote_preflight_used"] = bool(q)
        submit_row["latest_quote_preflight_at"] = _now_iso()
        return submit_row

    def update_adaptive_learning_capacity_policy(self, policy: dict[str, Any] | None) -> dict[str, Any]:
        candidate = dict(policy or {})
        baseline = max(2, _to_int(candidate.get("baseline_capacity"), self.max_open_positions_total))
        ceiling = max(baseline, min(40, _to_int(candidate.get("absolute_safety_ceiling"), 40)))
        recommended = max(baseline, min(ceiling, _to_int(candidate.get("recommended_adaptive_capacity"), baseline)))
        valid = bool(
            candidate.get("paper_only_preserved", True)
            and candidate.get("behavior_safe_to_apply") is False
            and not candidate.get("broker_behavior_changed", False)
            and not candidate.get("ranking_behavior_changed", False)
            and not candidate.get("entry_behavior_changed", False)
            and not candidate.get("thresholds_changed", False)
            and recommended >= baseline
        )
        current = dict(self._adaptive_learning_capacity_policy or {})
        current_limit = _to_int(current.get("recommended_adaptive_capacity"), baseline)
        raw_open = _to_int(candidate.get("raw_open_positions"), 0)
        reserve_status = str(candidate.get("learning_reserve_status") or "").strip().lower()
        contraction_safe = bool(raw_open < baseline or reserve_status in {"healthy", "recovered"})
        if (
            current.get("policy_valid")
            and current_limit > recommended
            and recommended <= baseline
            and not contraction_safe
        ):
            current["last_policy_refresh_rejected_reason"] = "baseline_fallback_cannot_contract_active_adaptive_policy"
            current["last_policy_refresh_rejected_at"] = _now_iso()
            self._adaptive_learning_capacity_policy = current
            self._save_state_file()
            return dict(current)
        self._adaptive_learning_capacity_policy = {
            **candidate,
            "policy_valid": valid,
            "baseline_capacity": baseline,
            "recommended_adaptive_capacity": recommended if valid else baseline,
            "absolute_safety_ceiling": ceiling,
            "policy_received_at": _now_iso(),
        }
        self._save_state_file()
        return dict(self._adaptive_learning_capacity_policy)

    def _adaptive_execution_capacity(self, raw_open_positions: int) -> dict[str, Any]:
        raw_count = max(0, int(raw_open_positions))
        policy = dict(self._adaptive_learning_capacity_policy or {})
        policy_age = _age_seconds_from_iso(policy.get("policy_received_at"))
        max_policy_age = max(
            300,
            min(21600, _to_int(os.getenv("ASTRA_ADAPTIVE_CAPACITY_POLICY_MAX_AGE_SECONDS"), 21600)),
        )
        policy_valid = bool(
            policy.get("policy_valid", False)
            and policy_age is not None
            and policy_age <= max_policy_age
        )
        baseline = max(2, int(self.max_open_positions_total))
        recommended = (
            max(baseline, min(40, _to_int(policy.get("recommended_adaptive_capacity"), baseline)))
            if policy_valid
            else baseline
        )
        effective_occupancy = max(
            0.0,
            min(
                float(raw_count),
                _to_float(policy.get("effective_learning_occupancy"), float(raw_count)),
            ),
        )
        raw_risk_slots_available = max(0, recommended - raw_count)
        effective_learning_slots_available = max(0.0, float(recommended) - effective_occupancy)
        safe_entry_slots = min(raw_risk_slots_available, int(effective_learning_slots_available))
        return {
            "adaptive_capacity_policy_active": policy_valid,
            "baseline_capacity": baseline,
            "adaptive_capacity_limit": recommended,
            "raw_open_positions": raw_count,
            "risk_exposure_positions": raw_count,
            "effective_learning_occupancy": round(effective_occupancy, 3),
            "effective_learning_capacity_available": round(effective_learning_slots_available, 3),
            "raw_risk_capacity_available": raw_risk_slots_available,
            "safe_paper_entry_slots_available": safe_entry_slots,
            "capacity_source": "adaptive_learning_policy" if policy_valid else "configured_baseline",
            "adaptive_capacity_policy_age_seconds": round(policy_age, 3) if policy_age is not None else None,
            "adaptive_capacity_policy_max_age_seconds": max_policy_age,
            "broker_truth_preserved": True,
            "all_existing_entry_gates_required": True,
        }

    def _current_execution_capacities(self) -> dict[str, Any]:
        counts = self._count_open_positions()
        open_rows = self._fetch_open_positions()
        open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows if str(r.get("symbol") or "").strip()}
        stock_open = int(counts.get("stock", 0))
        crypto_open = int(counts.get("crypto", 0))
        adaptive = self._adaptive_execution_capacity(stock_open + crypto_open)
        stock_limit = max(
            int(self.max_stocks),
            int(adaptive.get("adaptive_capacity_limit", self.max_open_positions_total))
            if adaptive.get("adaptive_capacity_policy_active")
            else int(self.max_stocks),
        )
        return {
            "open_symbols": open_syms,
            "open_position_rows_count": int(len(open_rows)),
            "open_positions_count": stock_open + crypto_open,
            "open_positions_stock": stock_open,
            "open_positions_crypto": crypto_open,
            "stock_capacity": max(0, stock_limit - stock_open),
            "crypto_capacity": max(0, self.max_crypto - crypto_open),
            "total_capacity": int(adaptive.get("safe_paper_entry_slots_available", 0)),
            **adaptive,
        }

    def _position_horizon_by_symbol(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in rows:
            symbol = str((row or {}).get("symbol") or "").upper().strip()
            if not symbol or symbol in out:
                continue
            payload = _safe_json_load((row or {}).get("row_json"))
            notes = _safe_json_load((row or {}).get("lifecycle_notes"))
            horizon, _source, _inferred = _infer_horizon_style({**payload, **notes, **dict(row or {})})
            out[symbol] = horizon if horizon in {"scalp", "day_trade", "swing_trade"} else "unknown"
        return out

    def _broker_learning_position_rows(
        self,
        broker_snapshot: dict[str, Any],
        internal_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        broker_rows = dict(broker_snapshot.get("broker_position_by_symbol") or {})
        internal_by_symbol: dict[str, dict[str, Any]] = {}
        for row in internal_rows:
            symbol = str((row or {}).get("symbol") or "").upper().strip()
            if not symbol or symbol in internal_by_symbol:
                continue
            payload = _safe_json_load((row or {}).get("row_json"))
            notes = _safe_json_load((row or {}).get("lifecycle_notes"))
            internal_by_symbol[symbol] = {**payload, **notes, **dict(row or {})}
        historical = self._historical_horizon_by_symbol(set(broker_rows))
        out: list[dict[str, Any]] = []
        for symbol, broker_row in sorted(broker_rows.items()):
            internal = dict(internal_by_symbol.get(symbol) or {})
            merged = {**internal, **dict(broker_row or {})}
            horizon, source, inferred = _infer_horizon_style(merged)
            if horizon not in {"scalp", "day_trade", "swing_trade"}:
                horizon = historical.get(symbol, "unknown")
                source = "historical_paper_position" if horizon != "unknown" else "missing_horizon"
                inferred = True
            unrealized_plpc = _to_float(merged.get("unrealized_plpc"), 0.0)
            pnl_percent = unrealized_plpc * 100.0 if abs(unrealized_plpc) <= 2.0 else unrealized_plpc
            entry_timestamp = str(
                internal.get("entry_timestamp")
                or internal.get("opened_at")
                or internal.get("created_at")
                or ""
            )
            age_seconds = _age_seconds_from_iso(entry_timestamp)
            out.append({
                "symbol": symbol,
                "horizon": horizon,
                "normalized_horizon": horizon,
                "horizon_source": source,
                "horizon_inferred": bool(inferred),
                "entry_timestamp": entry_timestamp,
                "position_age_days": round(age_seconds / 86400.0, 4) if age_seconds is not None else None,
                "avg_entry_price": _to_float(merged.get("avg_entry_price"), _to_float(internal.get("entry_price"), 0.0)),
                "current_price": _to_float(merged.get("current_price"), 0.0),
                "pnl_percent": round(pnl_percent, 4),
                "unrealized_pnl": round(_to_float(merged.get("unrealized_pl"), 0.0), 4),
                "quantity": round(_to_float(merged.get("qty"), _to_float(internal.get("quantity"), 0.0)), 6),
                "broker_confirmed": True,
                "position_age_source": "internal_entry_timestamp" if internal.get("entry_timestamp") else "horizon_proxy",
            })
        return out

    def _historical_horizon_by_symbol(self, symbols: list[str] | set[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        wanted = [str(s or "").upper().strip() for s in symbols if str(s or "").strip()]
        if not wanted:
            return out
        try:
            with self._connect() as conn:
                for symbol in wanted:
                    rows = conn.execute(
                        """
                        SELECT row_json, lifecycle_notes
                        FROM paper_positions
                        WHERE symbol=?
                        ORDER BY updated_at DESC, created_at DESC
                        LIMIT 25
                        """,
                        (symbol,),
                    ).fetchall()
                    for row in rows:
                        d = dict(row or {})
                        payload = _safe_json_load(d.get("row_json"))
                        notes = _safe_json_load(d.get("lifecycle_notes"))
                        horizon, _source, _inferred = _infer_horizon_style({**payload, **notes})
                        if horizon in {"scalp", "day_trade", "swing_trade"}:
                            out[symbol] = horizon
                            break
        except Exception:
            return out
        return out

    def _horizon_capacity_snapshot(
        self,
        *,
        open_rows: list[dict[str, Any]],
        broker_open_syms: set[str],
        broker_reconciliation_active: bool,
        broker_positions_fetch_ok: bool,
        adaptive_total_capacity: int | None = None,
    ) -> dict[str, Any]:
        by_symbol = self._position_horizon_by_symbol(open_rows)
        if broker_reconciliation_active and broker_positions_fetch_ok:
            missing = [s for s in broker_open_syms if by_symbol.get(s) not in {"scalp", "day_trade", "swing_trade"}]
            if missing:
                by_symbol.update(self._historical_horizon_by_symbol(missing))
        if broker_reconciliation_active and broker_positions_fetch_ok:
            symbols = sorted(s for s in broker_open_syms if s)
        else:
            symbols = sorted(s for s in by_symbol if s)
        usage = {"scalp": 0, "day_trade": 0, "swing_trade": 0, "unknown": 0}
        unknown_symbols: list[str] = []
        for symbol in symbols:
            horizon = by_symbol.get(symbol, "unknown")
            if horizon not in usage:
                horizon = "unknown"
            usage[horizon] += 1
            if horizon == "unknown":
                unknown_symbols.append(symbol)
        total_used = len(symbols)
        total_limit = max(
            int(self.horizon_total_capacity),
            _to_int(adaptive_total_capacity, int(self.horizon_total_capacity)),
        )
        total_available = max(0, total_limit - total_used)
        swing_used = usage["swing_trade"] + usage["unknown"]
        swing_pool_used = min(int(self.horizon_swing_capacity), swing_used)
        swing_available = max(0, total_available)
        day_available = max(0, total_available)
        scalp_available = max(0, total_available)
        blockers = []
        advisory_pressure = []
        if total_available <= 0:
            blockers.append("total_horizon_capacity_reached")
        if swing_used >= int(self.horizon_swing_capacity):
            advisory_pressure.append("swing_trade_learning_concentration")
        if usage["day_trade"] >= int(self.horizon_day_capacity):
            advisory_pressure.append("day_trade_learning_concentration")
        if usage["scalp"] >= int(self.horizon_scalp_capacity):
            advisory_pressure.append("scalp_learning_concentration")
        if usage["unknown"] > 0:
            advisory_pressure.append("unknown_horizon_positions_present")
        distribution = {
            key: round(value / max(1, total_used) * 100.0, 3)
            for key, value in usage.items()
        }
        return {
            "enabled": bool(self.horizon_capacity_enabled),
            "total_capacity": int(total_limit),
            "total_used": int(total_used),
            "total_available": int(total_available),
            "swing_capacity": int(self.horizon_swing_capacity),
            "swing_used": int(swing_used),
            "swing_available": int(swing_available),
            "day_capacity": int(self.horizon_day_capacity),
            "day_used": int(usage["day_trade"]),
            "day_available": int(day_available),
            "scalp_capacity": int(self.horizon_scalp_capacity),
            "scalp_used": int(usage["scalp"]),
            "scalp_available": int(scalp_available),
            "unknown_horizon_positions": int(usage["unknown"]),
            "unknown_horizon_symbols": unknown_symbols[:20],
            "horizon_distribution_pct": distribution,
            "horizon_capacity_blockers": blockers,
            "horizon_learning_advisories": advisory_pressure,
            "horizon_pools_enforced_as_hard_quotas": False,
            "elite_swing_exception_allowed": True,
            "capacity_freed_today": 0,
            "candidates_blocked_by_horizon_capacity": 0,
            "high_confidence_candidates_blocked_by_capacity": 0,
            "missed_evidence_due_to_capacity": 0,
            "recommended_capacity_action": (
                "classify_unknown_horizon_positions_and_preserve_reserved_scalp_day_capacity"
                if usage["unknown"] > 0
                else "horizon_capacity_available_for_qualified_candidates"
                if total_available > 0
                else "wait_for_natural_or_validated_paper_exits_to_free_capacity"
            ),
        }

    def _preferred_horizon_from_capacity(self, horizon_capacity: dict[str, Any]) -> str:
        if not self.horizon_capacity_enabled:
            return ""
        pct = dict(horizon_capacity.get("horizon_distribution_pct") or {})
        if not pct:
            return ""
        gaps = {
            "scalp": max(0.0, 20.0 - _to_float(pct.get("scalp"), 0.0)),
            "day_trade": max(0.0, 30.0 - _to_float(pct.get("day_trade"), 0.0)),
            "swing_trade": max(0.0, 30.0 - _to_float(pct.get("swing_trade"), 0.0)),
        }
        preferred = max(gaps.items(), key=lambda item: item[1])[0]
        if gaps.get(preferred, 0.0) <= 0.0:
            if _to_float(pct.get("swing_trade"), 0.0) > max(_to_float(pct.get("scalp"), 0.0), _to_float(pct.get("day_trade"), 0.0)):
                return "scalp"
            return ""
        return preferred

    def _horizon_tie_break_score(self, row: dict[str, Any], preferred_horizon: str) -> float:
        if preferred_horizon not in {"scalp", "day_trade", "swing_trade"}:
            return 0.0
        horizon, _source, _inferred = _infer_horizon_style(row)
        return 1.0 if horizon == preferred_horizon else 0.0

    def _horizon_has_capacity(self, horizon_capacity: dict[str, Any], horizon: str) -> tuple[bool, str]:
        if not self.horizon_capacity_enabled:
            return True, "horizon_capacity_disabled"
        if _to_int(horizon_capacity.get("total_available"), 0) <= 0:
            return False, "total_horizon_capacity_reached"
        bucket = horizon if horizon in {"scalp", "day_trade", "swing_trade"} else "swing_trade"
        advisories = set(horizon_capacity.get("horizon_learning_advisories") or [])
        advisory_key = f"{bucket}_learning_concentration"
        if advisory_key in advisories:
            return True, f"{bucket}_capacity_available_elite_quality_still_allowed"
        return True, f"{bucket}_capacity_available"

    def _consume_horizon_capacity(self, horizon_capacity: dict[str, Any], horizon: str) -> dict[str, Any]:
        out = dict(horizon_capacity or {})
        if not self.horizon_capacity_enabled:
            return out
        bucket = horizon if horizon in {"scalp", "day_trade", "swing_trade"} else "swing_trade"
        out["total_used"] = _to_int(out.get("total_used"), 0) + 1
        out["total_available"] = max(0, _to_int(out.get("total_available"), 0) - 1)
        if bucket == "scalp":
            out["scalp_used"] = _to_int(out.get("scalp_used"), 0) + 1
            out["scalp_available"] = max(0, _to_int(out.get("scalp_available"), 0) - 1)
        elif bucket == "day_trade":
            out["day_used"] = _to_int(out.get("day_used"), 0) + 1
            out["day_available"] = max(0, _to_int(out.get("day_available"), 0) - 1)
        else:
            out["swing_used"] = _to_int(out.get("swing_used"), 0) + 1
            out["swing_available"] = max(0, _to_int(out.get("swing_available"), 0) - 1)
        return out

    def _candidate_trace_row(
        self,
        row: dict[str, Any],
        open_syms: set[str],
        stock_capacity: int,
        crypto_capacity: int,
        total_capacity: int,
        selected_so_far: int = 0,
        internal_open_syms: set[str] | None = None,
        broker_open_syms: set[str] | None = None,
        broker_reconciliation_active: bool = False,
        max_new_positions_per_cycle: int | None = None,
    ) -> tuple[dict[str, Any], bool, str, dict[str, Any]]:
        r = _normalize_paper_entry_bridge(row)
        symbol = str(r.get("symbol") or "").upper().strip()
        asset = _norm_asset(r.get("asset_type") or "stock")
        allowed = False
        reason = "not_evaluated"
        gate_meta: dict[str, Any] = {"commitment_score": 0.0}
        internal_set = set(internal_open_syms or set())
        broker_set = set(broker_open_syms or set())
        duplicate_source = "none"
        if symbol:
            in_internal = symbol in internal_set
            in_broker = symbol in broker_set
            if in_internal and in_broker:
                duplicate_source = "both"
            elif in_internal:
                duplicate_source = "internal"
            elif in_broker:
                duplicate_source = "broker"
        max_new_limit = int(max_new_positions_per_cycle) if max_new_positions_per_cycle is not None else int(self.max_new_positions_per_cycle)
        if not symbol:
            reason = "missing_symbol"
        elif symbol in open_syms:
            reason = "duplicate_active_position"
        elif self._cooldown_active(symbol):
            reason = "cooldown_active"
        elif total_capacity <= 0:
            reason = "max_concurrent_positions_reached"
        elif selected_so_far >= max_new_limit:
            reason = "max_new_positions_per_cycle_reached"
        elif asset == "stock" and stock_capacity <= 0:
            reason = "stock_capacity_reached"
        elif asset == "crypto" and crypto_capacity <= 0:
            reason = "crypto_capacity_reached"
        else:
            allowed, reason, gate_meta = self._is_candidate_paper_eligible(r)
        portfolio_fit = _to_float(r.get("portfolio_fit_score"), 50.0)
        portfolio_fit_label = str(r.get("portfolio_fit_label") or "").strip()
        portfolio_diversification_block_reason = str(r.get("portfolio_diversification_block_reason") or "").strip()
        if allowed and portfolio_diversification_block_reason in {
            "correlation_overload",
            "duplicate_theme_overstack",
            "poor_portfolio_fit",
            "concentration_pressure",
        }:
            allowed = False
            reason = portfolio_diversification_block_reason
        session_diag = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "confirmation_for_candidate"):
            try:
                session_diag = dict(
                    self.market_session_timing_suite.confirmation_for_candidate(
                        r,
                        gate_meta=gate_meta,
                        broker_ready=self._alpaca_paper_broker_enabled(),
                    )
                    or {}
                )
            except Exception:
                session_diag = {}
        trace = {
            "symbol": symbol,
            "asset_type": asset,
            "action": str(r.get("action") or r.get("prediction") or ""),
            "readiness": str(r.get("readiness_label") or r.get("paper_ready_status") or r.get("buy_eligibility") or ""),
            "assigned_horizon": str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or r.get("paper_entry_horizon_style") or ""),
            "paper_entry_horizon_style": str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "paper_entry_horizon_source": str(r.get("paper_entry_horizon_source") or ""),
            "paper_entry_horizon_inferred": bool(r.get("paper_entry_horizon_inferred", False)),
            "opportunity_quality_score": round(_to_float(r.get("opportunity_quality_score"), 0.0), 2),
            "opportunity_quality_label": str(r.get("opportunity_quality_label") or ""),
            "expected_value_score": round(_to_float(r.get("expected_value_score"), 0.0), 2),
            "expected_win_probability": round(_to_float(r.get("expected_win_probability"), 0.0), 2),
            "trade_archetype": str(r.get("trade_archetype") or ""),
            "archetype_quality_score": round(_to_float(r.get("archetype_quality_score"), 0.0), 2),
            "regime_alignment_score": round(_to_float(r.get("regime_alignment_score"), 0.0), 2),
            "regime_alignment_label": str(r.get("regime_alignment_label") or ""),
            "edge_composite_score": round(_to_float(r.get("edge_composite_score"), 0.0), 2),
            "edge_composite_label": str(r.get("edge_composite_label") or ""),
            "exit_quality_score": round(_to_float(r.get("exit_quality_score"), 0.0), 2),
            "exit_readiness_label": str(r.get("exit_readiness_label") or ""),
            "intelligent_position_size_pct": round(_to_float(r.get("intelligent_position_size_pct"), 0.0), 3),
            "sizing_safety_label": str(r.get("sizing_safety_label") or ""),
            "portfolio_heat_score": round(_to_float(r.get("portfolio_heat_score"), 0.0), 2),
            "portfolio_correlation_risk": round(_to_float(r.get("portfolio_correlation_risk"), 0.0), 2),
            "portfolio_diversification_v2_active": bool(r.get("portfolio_diversification_v2_active", False)),
            "portfolio_fit_score": round(portfolio_fit, 2),
            "portfolio_fit_label": portfolio_fit_label,
            "portfolio_fit_reason": str(r.get("portfolio_fit_reason") or ""),
            "correlation_cluster_label": str(r.get("correlation_cluster_label") or ""),
            "correlation_cluster_id": str(r.get("correlation_cluster_id") or ""),
            "duplicate_theme_label": str(r.get("duplicate_theme_label") or ""),
            "correlation_adjusted_expectancy": round(_to_float(r.get("correlation_adjusted_expectancy"), 0.0), 2),
            "concentration_adjusted_expectancy": round(_to_float(r.get("concentration_adjusted_expectancy"), 0.0), 2),
            "diversification_selection_reason": str(r.get("diversification_selection_reason") or ""),
            "survivability_score": round(_to_float(r.get("survivability_score"), 0.0), 2),
            "trade_management_score": round(_to_float(r.get("trade_management_score"), 0.0), 2),
            "adaptive_trade_quality_label": str(r.get("adaptive_trade_quality_label") or ""),
            "allocation_lane": str(r.get("allocation_lane") or ""),
            "allocation_lane_score": round(_to_float(r.get("allocation_lane_score"), 0.0), 2),
            "paper_allocation_priority": round(_to_float(r.get("paper_allocation_priority"), 0.0), 2),
            "exploration_candidate": bool(r.get("exploration_candidate", False)),
            "exploration_allowed": bool(r.get("exploration_allowed", False)),
            "exploration_risk_label": str(r.get("exploration_risk_label") or ""),
            "exploration_rejection_reason": str(r.get("exploration_rejection_reason") or ""),
            "controlled_exploration_considered": False,
            "controlled_exploration_allowed": False,
            "controlled_exploration_reason": "",
            "exploration_selected": False,
            "exploration_context": str(r.get("selected_exploration_context") or ""),
            "exploration_expected_value_score": round(_to_float(r.get("exploration_expected_value_score"), 0.0), 2),
            "exploration_trade_quality_score": round(_to_float(r.get("exploration_trade_quality_score"), 0.0), 2),
            "exploration_survivability_score": round(_to_float(r.get("exploration_survivability_score"), 0.0), 2),
            "caution_aggression_label": str(r.get("caution_aggression_label") or ""),
            "missed_opportunity_pressure": round(_to_float(r.get("missed_opportunity_pressure"), 0.0), 2),
            "participation_quality_score": round(_to_float(r.get("participation_quality_score"), 0.0), 2),
            "risk_adjusted_opportunity_rank": int(_to_float(r.get("risk_adjusted_opportunity_rank"), 0.0)),
            "entry_score": round(_to_float(r.get("paper_entry_bridge_score"), _to_float(r.get("entry_quality_score"), 0.0)), 2),
            "confidence": round(_to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0)), 2),
            "horizon_confidence": round(_to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0)), 2),
            "expected_hold_window": _expected_hold_window(
                str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or r.get("best_horizon_style") or "").strip().lower()
            ),
            "horizon_reason": str(r.get("paper_entry_horizon_source") or r.get("horizon_reason") or r.get("allocation_reason") or ""),
            "eligible": bool(allowed),
            "decision_reason": str(reason),
            "commitment_score": round(_to_float(gate_meta.get("commitment_score"), 0.0), 2),
            "duplicate_active_position": bool(symbol in open_syms) if symbol else False,
            "duplicate_source": duplicate_source,
            "broker_reconciliation_active": bool(broker_reconciliation_active),
            "market_session_mode": str(session_diag.get("market_session_mode") or ""),
            "market_is_open": bool(session_diag.get("market_is_open", False)),
            "market_is_tradable": bool(session_diag.get("market_is_tradable", False)),
            "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
            "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
            "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
            "open_confirmation_label": str(session_diag.get("open_confirmation_label") or ""),
            "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
            "execution_intent_status": str(session_diag.get("execution_intent_status") or ""),
            "candidate_execution_intent": bool(session_diag.get("candidate_execution_intent", False)),
            "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", False)),
            "requires_open_confirmation": bool(session_diag.get("requires_open_confirmation", True)),
            "weekend_watchlist_candidate": bool(session_diag.get("weekend_watchlist_candidate", False)),
            "market_calendar_session_type": str(r.get("market_calendar_session_type") or session_diag.get("current_session_type") or session_diag.get("market_session_mode") or ""),
            "session_tradable": bool(session_diag.get("session_tradable", session_diag.get("market_is_tradable", False))),
            "session_execution_posture": str(r.get("session_execution_posture") or session_diag.get("session_execution_posture") or ""),
            "session_confirmation_requirement": str(r.get("session_confirmation_requirement") or session_diag.get("session_confirmation_requirement") or ""),
            "market_structure_label": str(r.get("market_structure_label") or session_diag.get("market_structure_label") or ""),
            "trade_style_environment": str(r.get("trade_style_environment") or session_diag.get("trade_style_environment") or ""),
            "behavioral_market_state": str(r.get("behavioral_market_state") or session_diag.get("behavioral_market_state") or ""),
            "market_context_supports_trade": bool(r.get("market_context_supports_trade", session_diag.get("market_context_supports_trade", True))),
            "market_context_rejection_reason": str(r.get("market_context_rejection_reason") or session_diag.get("market_context_rejection_reason") or ""),
            "context_adjusted_opportunity_score": round(_to_float(r.get("context_adjusted_opportunity_score"), _to_float(session_diag.get("context_adjusted_opportunity_score"), 50.0)), 2),
            "paper_autopilot_candidate_source": str(r.get("paper_autopilot_candidate_source") or r.get("top_buys_candidate_source") or "top_buys"),
            "broad_universe_candidates_available": bool(r.get("broad_universe_promoted", False) or r.get("selected_from_broad_universe", False)),
            "promoted_candidates_available": bool(r.get("broad_universe_promoted", False)),
            "selected_from_broad_universe": bool(r.get("selected_from_broad_universe", False)),
            "selected_cap_tier": str(r.get("candidate_universe_tier") or ""),
            "selected_sector": str(r.get("sector") or ""),
            "selected_opportunity_type": str(r.get("candidate_opportunity_type") or ""),
            "broad_universe_rejection_reason": str(r.get("broad_universe_rejection_reason") or ""),
            "selected": False,
            "order_attempted": False,
        }
        return trace, bool(allowed), str(reason), dict(gate_meta or {})

    def _submit_alpaca_paper_entry_order(
        self,
        row: dict[str, Any],
        entry_price: float,
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        broker = self.alpaca_paper_broker
        if not self._alpaca_paper_broker_enabled():
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_paper_broker_disabled"}
        if broker is None or not hasattr(broker, "submit_paper_order"):
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_paper_broker_unavailable"}
        r = _normalize_paper_entry_bridge(row)
        meta = dict(gate_meta or {})
        asset_type = _norm_asset(r.get("asset_type") or "stock")
        if asset_type != "stock":
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_crypto_execution_deferred"}
        limits_ok = bool(meta.get("paper_autopilot_limits_ok", False))
        if not limits_ok:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "paper_autopilot_limits_proof_required",
                "paper_autopilot_limits_ok": False,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "paper_limits_not_proven"),
            }
        risk_label_raw = str(r.get("portfolio_risk_label") or "").strip()
        risk_label = risk_label_raw.lower()
        risk_score_raw = r.get("portfolio_risk_score")
        risk_score = _to_float(risk_score_raw, 0.0) if risk_score_raw is not None else None
        explicit_portfolio_ok = r.get("portfolio_risk_ok")
        portfolio_risk_proof_present = bool(
            explicit_portfolio_ok is not None
            or risk_score is not None
            or bool(risk_label_raw)
        )
        if not portfolio_risk_proof_present:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "missing_portfolio_risk_data",
                "portfolio_risk_proof_present": False,
                "portfolio_risk_score_used": None,
                "portfolio_risk_label_used": "",
                "portfolio_risk_preflight_reason": "missing_portfolio_risk_data",
            }

        if explicit_portfolio_ok is not None:
            portfolio_ok = bool(explicit_portfolio_ok)
            preflight_reason = "explicit_portfolio_risk_ok"
        else:
            # Conservative fallback: require a non-blocking label plus minimum score
            # when explicit portfolio_risk_ok is not present.
            if risk_score is None:
                return {
                    "ok": False,
                    "paper_order_submitted": False,
                    "error": "missing_portfolio_risk_data",
                    "portfolio_risk_proof_present": False,
                    "portfolio_risk_score_used": None,
                    "portfolio_risk_label_used": risk_label_raw,
                    "portfolio_risk_preflight_reason": "missing_portfolio_risk_score",
                }
            portfolio_ok = bool(risk_label not in {"high_risk", "blocked"} and risk_score >= 35.0)
            preflight_reason = "derived_from_portfolio_risk_fields"

        session_diag = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "confirmation_for_candidate"):
            try:
                session_diag = dict(
                    self.market_session_timing_suite.confirmation_for_candidate(
                        r,
                        gate_meta=meta,
                        broker_ready=self._alpaca_paper_broker_enabled(),
                    )
                    or {}
                )
            except Exception:
                session_diag = {}
        if not bool(session_diag.get("paper_order_submission_allowed", False)):
            blocker = "session_order_submission_blocked"
            if bool(session_diag.get("execution_confirmation_required", True)):
                blocker = "open_confirmation_required"
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": blocker,
                "market_session_mode": str(session_diag.get("market_session_mode") or "unknown_closed"),
                "paper_order_submission_allowed": False,
                "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
                "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
                "open_confirmation_label": str(session_diag.get("open_confirmation_label") or "wait_for_open_structure"),
                "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or session_diag.get("session_reason") or ""),
                "execution_intent_status": str(session_diag.get("execution_intent_status") or "intent_ready"),
                "candidate_execution_intent": bool(session_diag.get("candidate_execution_intent", True)),
                "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", True)),
                "requires_open_confirmation": True,
                "weekend_watchlist_candidate": bool(session_diag.get("weekend_watchlist_candidate", False)),
                "intent_created_reason": str(session_diag.get("intent_created_reason") or "closed_market_execution_intent_only"),
                "replay_candidate_snapshot_saved": bool(session_diag.get("replay_candidate_snapshot_saved", True)),
                "replay_learning_ready": bool(session_diag.get("replay_learning_ready", True)),
                "session_timing_outcome_tracking_ready": True,
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
                "natural_exit_logic_preserved": True,
            }
        if str(session_diag.get("open_confirmation_label") or "") != "confirmed_execute":
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "open_confirmation_required",
                "market_session_mode": str(session_diag.get("market_session_mode") or "unknown_closed"),
                "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": True,
                "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
                "open_confirmation_label": str(session_diag.get("open_confirmation_label") or "wait_for_open_structure"),
                "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
                "execution_intent_status": str(session_diag.get("execution_intent_status") or "pending_confirmation"),
                "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", True)),
                "requires_open_confirmation": True,
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
                "natural_exit_logic_preserved": True,
            }

        broker_snapshot = self._broker_open_symbols_snapshot()
        reconciliation_checked = bool(
            broker_snapshot.get("broker_reconciliation_active")
            and (
                broker_snapshot.get("broker_positions_fetch_ok")
                or str(broker_snapshot.get("broker_positions_error_sanitized") or "").strip()
            )
        )
        order = {
            "symbol": str(r.get("symbol") or "").upper().strip(),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "astra_paper_logic_passed": True,
            "paper_logic_passed": True,
            "paper_ready": True,
            "paper_test_eligible": True,
            "paper_order_preflight_ready": True,
            "paper_limits_ok": True,
            "paper_autopilot_limits_ok": True,
            "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
            "portfolio_risk_ok": bool(portfolio_ok),
            "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
            "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
            "portfolio_risk_label_used": risk_label_raw,
            "portfolio_risk_preflight_reason": preflight_reason,
            "market_session_mode": str(session_diag.get("market_session_mode") or ""),
            "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
            "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
            "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
            "open_confirmation_label": str(session_diag.get("open_confirmation_label") or ""),
            "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
            "quote_freshness_confirmed": bool(session_diag.get("quote_freshness_confirmed", False)),
            "spread_liquidity_confirmed": bool(session_diag.get("spread_liquidity_confirmed", False)),
            "gap_behavior_confirmed": bool(session_diag.get("gap_behavior_confirmed", False)),
            "entry_commitment_confirmed": bool(session_diag.get("entry_commitment_confirmed", False)),
            "portfolio_risk_confirmed": bool(session_diag.get("portfolio_risk_confirmed", False)),
            "broker_preflight_confirmed": bool(session_diag.get("broker_preflight_confirmed", False)),
            "broker_reconciliation_active": bool(broker_snapshot.get("broker_reconciliation_active", False)),
            "broker_positions_checked": bool(reconciliation_checked),
            "natural_exit_logic_preserved": True,
            "entry_price_reference": round(_to_float(entry_price), 6),
            "entry_commitment_score": round(_to_float((gate_meta or {}).get("commitment_score"), 0.0), 2),
        }
        try:
            res = dict(broker.submit_paper_order(order) or {})
            res.setdefault("paper_autopilot_limits_ok", True)
            res.setdefault("paper_autopilot_limits_reason", str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"))
            res.setdefault("portfolio_risk_proof_present", bool(portfolio_risk_proof_present))
            res.setdefault("portfolio_risk_score_used", (None if risk_score is None else round(float(risk_score), 4)))
            res.setdefault("portfolio_risk_label_used", risk_label_raw)
            res.setdefault("portfolio_risk_preflight_reason", preflight_reason)
            return res
        except Exception as exc:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": f"alpaca_paper_submit_exception:{str(exc)[:120]}",
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
            }

    def _build_entry_context_v1(
        self,
        row: dict[str, Any],
        entry_price: float,
        source_bucket: str,
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = _normalize_paper_entry_bridge(row)
        meta = dict(gate_meta or {})
        return {
            "entry_reason": "paper_autopilot_entry",
            "entry_price": round(_to_float(entry_price, 0.0), 6),
            "entry_quality": str(r.get("buy_quality_tier") or ""),
            "entry_source_bucket": str(source_bucket or "paper_candidate"),
            "entry_setup_type": str(r.get("setup_type") or "unknown"),
            "entry_regime_context": str(r.get("regime_context") or r.get("market_regime") or ""),
            "entry_persona_best_fit": str(r.get("persona_best_fit") or ""),
            "entry_confidence": round(
                _to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0))
                * (100.0 if _to_float(r.get("confidence"), 0.0) <= 1.0 else 1.0),
                2,
            ),
            "entry_predicted_probability": round(_to_float(r.get("predicted_win_probability"), 0.0), 6),
            "entry_uncertainty_tier": str(r.get("uncertainty_tier") or ""),
            "entry_uncertainty_score": round(_to_float(r.get("uncertainty_score"), 50.0), 2),
            "entry_decision_discipline_tier": str(r.get("core_decision_discipline_tier") or ""),
            "entry_decision_discipline_action": str(r.get("core_decision_discipline_action") or ""),
            "entry_buy_eligibility": str(r.get("buy_eligibility") or ""),
            "entry_buy_quality_score": round(_to_float(r.get("buy_quality_score"), _to_float(r.get("trade_quality_score"), 0.0)), 2),
            "entry_paper_bridge_score": round(_to_float(r.get("paper_entry_bridge_score"), 0.0), 2),
            "entry_paper_bridge_score_source": str(r.get("paper_entry_bridge_score_source") or ""),
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "trade_archetype": str(r.get("trade_archetype") or "unknown"),
            "opportunity_quality_score": round(_to_float(r.get("opportunity_quality_score"), 0.0), 2),
            "opportunity_quality_label": str(r.get("opportunity_quality_label") or ""),
            "expected_value_score": round(_to_float(r.get("expected_value_score"), 0.0), 2),
            "expected_win_probability": round(_to_float(r.get("expected_win_probability"), 0.0), 2),
            "expected_reward_risk_ratio": round(_to_float(r.get("expected_reward_risk_ratio"), 0.0), 3),
            "expected_follow_through_score": round(_to_float(r.get("expected_follow_through_score"), 0.0), 2),
            "expected_loss_containment_score": round(_to_float(r.get("expected_loss_containment_score"), 0.0), 2),
            "archetype_confidence": round(_to_float(r.get("archetype_confidence"), 0.0), 2),
            "archetype_quality_score": round(_to_float(r.get("archetype_quality_score"), 0.0), 2),
            "regime_alignment_score": round(_to_float(r.get("regime_alignment_score"), 0.0), 2),
            "regime_alignment_label": str(r.get("regime_alignment_label") or ""),
            "regime_edge_multiplier": round(_to_float(r.get("regime_edge_multiplier"), 1.0), 4),
            "edge_composite_score": round(_to_float(r.get("edge_composite_score"), 0.0), 2),
            "edge_composite_label": str(r.get("edge_composite_label") or ""),
            "edge_development_shadow_only": bool(r.get("edge_development_shadow_only", True)),
            "edge_summary": str(r.get("edge_summary") or ""),
            "exit_quality_score": round(_to_float(r.get("exit_quality_score"), 0.0), 2),
            "exit_readiness_label": str(r.get("exit_readiness_label") or ""),
            "momentum_deterioration_score": round(_to_float(r.get("momentum_deterioration_score"), 0.0), 2),
            "follow_through_decay_score": round(_to_float(r.get("follow_through_decay_score"), 0.0), 2),
            "trend_exhaustion_score": round(_to_float(r.get("trend_exhaustion_score"), 0.0), 2),
            "adaptive_stop_suggestion": str(r.get("adaptive_stop_suggestion") or ""),
            "adaptive_profit_lock_score": round(_to_float(r.get("adaptive_profit_lock_score"), 0.0), 2),
            "hold_quality_score": round(_to_float(r.get("hold_quality_score"), 0.0), 2),
            "intelligent_position_size_pct": round(_to_float(r.get("intelligent_position_size_pct"), 0.0), 3),
            "position_size_confidence": round(_to_float(r.get("position_size_confidence"), 0.0), 2),
            "sizing_safety_label": str(r.get("sizing_safety_label") or ""),
            "portfolio_heat_score": round(_to_float(r.get("portfolio_heat_score"), 0.0), 2),
            "portfolio_correlation_risk": round(_to_float(r.get("portfolio_correlation_risk"), 0.0), 2),
            "sector_concentration_score": round(_to_float(r.get("sector_concentration_score"), 0.0), 2),
            "portfolio_stability_score": round(_to_float(r.get("portfolio_stability_score"), 0.0), 2),
            "portfolio_diversification_v2_active": bool(r.get("portfolio_diversification_v2_active", False)),
            "portfolio_fit_score": round(_to_float(r.get("portfolio_fit_score"), 0.0), 2),
            "portfolio_fit_label": str(r.get("portfolio_fit_label") or ""),
            "portfolio_fit_reason": str(r.get("portfolio_fit_reason") or ""),
            "correlation_cluster_label": str(r.get("correlation_cluster_label") or ""),
            "duplicate_theme_label": str(r.get("duplicate_theme_label") or ""),
            "correlation_adjusted_expectancy": round(_to_float(r.get("correlation_adjusted_expectancy"), 0.0), 2),
            "concentration_adjusted_expectancy": round(_to_float(r.get("concentration_adjusted_expectancy"), 0.0), 2),
            "diversification_selection_reason": str(r.get("diversification_selection_reason") or ""),
            "survivability_score": round(_to_float(r.get("survivability_score"), 0.0), 2),
            "trade_management_score": round(_to_float(r.get("trade_management_score"), 0.0), 2),
            "risk_adjusted_trade_quality": round(_to_float(r.get("risk_adjusted_trade_quality"), 0.0), 2),
            "adaptive_trade_quality_label": str(r.get("adaptive_trade_quality_label") or ""),
            "trade_management_shadow_only": bool(r.get("trade_management_shadow_only", True)),
            "portfolio_intelligence_shadow_only": bool(r.get("portfolio_intelligence_shadow_only", True)),
            "trade_management_summary": str(r.get("trade_management_summary") or ""),
            "allocation_lane": str(r.get("allocation_lane") or ""),
            "allocation_lane_score": round(_to_float(r.get("allocation_lane_score"), 0.0), 2),
            "paper_allocation_priority": round(_to_float(r.get("paper_allocation_priority"), 0.0), 2),
            "exploration_candidate": bool(r.get("exploration_candidate", False)),
            "exploration_allowed": bool(r.get("exploration_allowed", False)),
            "exploration_risk_label": str(r.get("exploration_risk_label") or ""),
            "exploration_rejection_reason": str(r.get("exploration_rejection_reason") or ""),
            "entry_entry_edge_score": round(_to_float(r.get("entry_edge_score"), 0.0), 4),
            "entry_follow_through_state": str(r.get("follow_through_state") or ""),
            "entry_commitment_score": round(_to_float(meta.get("commitment_score"), 0.0), 2),
            "entry_signal_tags": r.get("entry_signal_tags") or r.get("signal_tags") or [],
            "entry_rationale": str(r.get("why_this_is_a_buy") or r.get("plain_decision_summary") or ""),
            "lifecycle_stage": "entered",
            "review_state": "new_entry",
            "continuation_flag": False,
            "deterioration_flag": False,
            "hold_posture": "observe",
        }

    def _open_position_from_row(
        self,
        row: dict[str, Any],
        source_bucket: str = "paper_candidate",
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = _normalize_paper_entry_bridge(row)
        symbol = str(row.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(row.get("asset_type") or "stock")
        if not symbol:
            return {"ok": False, "error": "symbol_required"}

        quote = {}
        if callable(self.get_latest_row_fn):
            try:
                quote = dict(self.get_latest_row_fn(symbol, asset_type) or {})
            except Exception:
                quote = {}
        quote_price = _to_float(
            quote.get("price"),
            _to_float(quote.get("current_price"), _to_float(quote.get("last_price"), 0.0)),
        )
        row_price = _to_float(
            row.get("price"),
            _to_float(row.get("current_price"), _to_float(row.get("last_price"), _to_float(row.get("entry_price"), 0.0))),
        )
        entry_price = quote_price if quote_price > 0.0 else row_price
        if entry_price <= 0.0:
            return {"ok": False, "error": "no_valid_entry_price", "symbol": symbol}

        now_iso = _now_iso()
        pid = str(uuid.uuid4())
        submit_row = self._merge_latest_quote_for_submission(row, quote, entry_price)
        entry_row = dict(submit_row)
        entry_row.setdefault("symbol", symbol)
        entry_row.setdefault("asset_type", asset_type)
        entry_row.setdefault("entry_timestamp", now_iso)
        broker_order = self._submit_alpaca_paper_entry_order(submit_row, entry_price, gate_meta=gate_meta)
        if broker_order.get("enabled", True) is not False and not broker_order.get("ok", False):
            broker_error = str(
                broker_order.get("error")
                or broker_order.get("open_confirmation_reason")
                or broker_order.get("reason")
                or "unknown"
            )[:180]
            return {
                "ok": False,
                "error": "alpaca_paper_order_failed",
                "symbol": symbol,
                "broker_error": broker_error,
                "paper_autopilot_limits_ok": bool(broker_order.get("paper_autopilot_limits_ok", False)),
                "paper_autopilot_limits_reason": str(broker_order.get("paper_autopilot_limits_reason") or ""),
                "portfolio_risk_proof_present": bool(broker_order.get("portfolio_risk_proof_present", False)),
                "portfolio_risk_score_used": broker_order.get("portfolio_risk_score_used"),
                "portfolio_risk_label_used": str(broker_order.get("portfolio_risk_label_used") or ""),
                "portfolio_risk_preflight_reason": str(broker_order.get("portfolio_risk_preflight_reason") or ""),
                "market_session_mode": str(broker_order.get("market_session_mode") or ""),
                "paper_order_submission_allowed": bool(broker_order.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": bool(broker_order.get("execution_confirmation_required", True)),
                "open_confirmation_score": broker_order.get("open_confirmation_score"),
                "open_confirmation_label": str(broker_order.get("open_confirmation_label") or ""),
                "open_confirmation_reason": str(broker_order.get("open_confirmation_reason") or ""),
                "execution_intent_status": str(broker_order.get("execution_intent_status") or ""),
                "defer_until_market_confirmation": bool(broker_order.get("defer_until_market_confirmation", False)),
                "requires_open_confirmation": bool(broker_order.get("requires_open_confirmation", True)),
                "weekend_watchlist_candidate": bool(broker_order.get("weekend_watchlist_candidate", False)),
                "replay_candidate_snapshot_saved": bool(broker_order.get("replay_candidate_snapshot_saved", False)),
                "replay_learning_ready": bool(broker_order.get("replay_learning_ready", False)),
                "session_timing_outcome_tracking_ready": bool(broker_order.get("session_timing_outcome_tracking_ready", False)),
                "quote_age_seconds": submit_row.get("quote_age_seconds"),
                "quote_quality": str(submit_row.get("quote_quality") or ""),
                "latest_quote_preflight_used": bool(submit_row.get("latest_quote_preflight_used", False)),
            }
        if broker_order:
            entry_row["alpaca_paper_order"] = broker_order
        entry_context = self._build_entry_context_v1(submit_row, entry_price, source_bucket, gate_meta=gate_meta)
        entry_context["position_id"] = pid
        entry_context["alpaca_paper_order"] = broker_order

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions(
                    position_id, symbol, asset_type, status, quantity,
                    entry_price, exit_price, return_percent, friction_adjusted_return,
                    entry_timestamp, exit_timestamp, hold_seconds,
                    source_bucket, lifecycle_notes, row_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    symbol,
                    asset_type,
                    1.0,
                    entry_price,
                    now_iso,
                    source_bucket,
                    _safe_json(entry_context),
                    _safe_json(entry_row),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()

        if self._position_tracker is not None:
            try:
                self._position_tracker.open_position(
                    symbol=symbol,
                    asset_type=asset_type,
                    entry_price=entry_price,
                    quantity=1.0,
                    notes="paper_autopilot",
                    snapshot_fields={
                        "source_bucket": source_bucket,
                        "buy_eligibility": row.get("buy_eligibility"),
                        "buy_quality_tier": row.get("buy_quality_tier"),
                        "entry_commitment_score": entry_context.get("entry_commitment_score"),
                        "entry_uncertainty_tier": entry_context.get("entry_uncertainty_tier"),
                        "entry_decision_discipline_tier": entry_context.get("entry_decision_discipline_tier"),
                    },
                    mode=self.paper_mode,
                )
            except Exception:
                pass
        if callable(create_lifecycle_record):
            try:
                create_lifecycle_record(
                    {
                        "lifecycle_id": pid,
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "signal_timestamp": str(row.get("timestamp") or now_iso),
                        "release_status": str(row.get("paper_ready_status") or row.get("release_status") or "paper"),
                        "entry_timestamp": now_iso,
                        "entry_price": entry_price,
                        "current_price": entry_price,
                        "confidence": _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0)),
                        "grade": _to_float(row.get("grade_percent"), _to_float(row.get("persona_weighted_grade"), 0.0)),
                        "entry_quality_score": _to_float(row.get("entry_quality_score"), _to_float(row.get("paper_entry_bridge_score"), 0.0)),
                        "entry_quality_band": str(row.get("entry_quality_band") or "unknown"),
                        "trade_horizon_style": str(row.get("trade_horizon_style") or row.get("best_horizon_style") or ""),
                        "trade_archetype": str(row.get("setup_type") or "unknown"),
                        "catalyst_context": str(row.get("regime_context") or row.get("market_regime") or ""),
                        "source_endpoint": "paper_autopilot",
                        "lifecycle_stage": "entry",
                    }
                )
            except Exception:
                pass

        return {
            "ok": True,
            "position_id": pid,
            "symbol": symbol,
            "entry_price": entry_price,
            "asset_type": asset_type,
            "paper_autopilot_limits_ok": bool(broker_order.get("paper_autopilot_limits_ok", True)) if isinstance(broker_order, dict) else True,
            "paper_autopilot_limits_reason": str(broker_order.get("paper_autopilot_limits_reason") or "") if isinstance(broker_order, dict) else "",
            "portfolio_risk_proof_present": bool(broker_order.get("portfolio_risk_proof_present", True)) if isinstance(broker_order, dict) else True,
            "portfolio_risk_score_used": broker_order.get("portfolio_risk_score_used") if isinstance(broker_order, dict) else None,
            "portfolio_risk_label_used": str(broker_order.get("portfolio_risk_label_used") or "") if isinstance(broker_order, dict) else "",
            "portfolio_risk_preflight_reason": str(broker_order.get("portfolio_risk_preflight_reason") or "") if isinstance(broker_order, dict) else "",
            "market_session_mode": str(broker_order.get("market_session_mode") or "") if isinstance(broker_order, dict) else "",
            "paper_order_submission_allowed": bool(broker_order.get("paper_order_submission_allowed", True)) if isinstance(broker_order, dict) else True,
            "execution_confirmation_required": bool(broker_order.get("execution_confirmation_required", False)) if isinstance(broker_order, dict) else False,
            "open_confirmation_score": broker_order.get("open_confirmation_score") if isinstance(broker_order, dict) else None,
            "open_confirmation_label": str(broker_order.get("open_confirmation_label") or "") if isinstance(broker_order, dict) else "",
            "open_confirmation_reason": str(broker_order.get("open_confirmation_reason") or "") if isinstance(broker_order, dict) else "",
            "quote_age_seconds": submit_row.get("quote_age_seconds"),
            "quote_quality": str(submit_row.get("quote_quality") or ""),
            "latest_quote_preflight_used": bool(submit_row.get("latest_quote_preflight_used", False)),
        }

    def _close_position(self, open_row: dict[str, Any], latest_row: dict[str, Any], exit_reason: str) -> dict[str, Any]:
        pid = str(open_row.get("position_id") or "").strip()
        symbol = str(open_row.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(open_row.get("asset_type") or "stock")
        if not pid or not symbol:
            return {"ok": False, "error": "position_row_invalid"}

        entry_price = _to_float(open_row.get("entry_price"), 0.0)
        now_iso = _now_iso()
        exit_price = _to_float(latest_row.get("price"), 0.0)
        if exit_price <= 0.0:
            exit_price = _to_float(open_row.get("entry_price"), 0.0)
        if entry_price <= 0.0:
            return {"ok": False, "error": "invalid_entry_price"}

        notes = _safe_json_load(open_row.get("lifecycle_notes"))
        entry_payload = _safe_json_load(open_row.get("row_json"))

        ret = ((exit_price - entry_price) / entry_price) * 100.0
        friction_ret = ret - 0.04

        entry_ts = str(open_row.get("entry_timestamp") or "")
        hold_seconds = 0.0
        try:
            hold_seconds = max(
                0.0,
                datetime.fromisoformat(now_iso.replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).timestamp(),
            )
        except Exception:
            hold_seconds = 0.0

        lifecycle_stage = "completed_winner" if ret > 0 else "completed_loser"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET status='CLOSED', exit_price=?, return_percent=?, friction_adjusted_return=?,
                    exit_timestamp=?, hold_seconds=?, lifecycle_notes=?, updated_at=?
                WHERE position_id=?
                """,
                (
                    exit_price,
                    ret,
                    friction_ret,
                    now_iso,
                    hold_seconds,
                    _safe_json(
                        {
                            "exit_reason": exit_reason,
                            "quote_quality": latest_row.get("quote_quality"),
                            "provider_used": latest_row.get("provider_used") or latest_row.get("source"),
                            "lifecycle_stage": lifecycle_stage,
                            "review_state": "closed",
                            "final_return_percent": round(ret, 4),
                            "continuation_flag": bool(_to_float(notes.get("peak_unrealized_pnl_percent"), max(ret, 0.0)) >= 1.0 and ret > 0),
                            "deterioration_flag": bool(_to_float(notes.get("drawdown_from_peak_percent"), 0.0) >= 1.6),
                        }
                    ),
                    now_iso,
                    pid,
                ),
            )
            conn.commit()

        if self._position_tracker is not None:
            try:
                self._position_tracker.close_position(identifier=symbol, exit_price=exit_price, exit_timestamp=now_iso, exit_reason_manual=exit_reason)
            except Exception:
                pass
        if callable(close_lifecycle_record):
            try:
                close_lifecycle_record(
                    pid,
                    {
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "exit_timestamp": now_iso,
                        "exit_price": exit_price,
                        "current_price": exit_price,
                        "pnl_pct": ret,
                        "max_favorable_excursion_pct": _to_float(notes.get("max_favorable_excursion"), max(ret, 0.0)),
                        "max_adverse_excursion_pct": _to_float(notes.get("max_adverse_excursion"), min(ret, 0.0)),
                        "exit_reason": str(exit_reason or ""),
                        "outcome_label": "winner" if ret > 0 else ("loser" if ret < 0 else "flat"),
                        "source_endpoint": "paper_autopilot",
                    },
                )
            except Exception:
                pass
        if self.trade_lifecycle_excursion_suite is not None and hasattr(self.trade_lifecycle_excursion_suite, "record_closed_position"):
            try:
                self.trade_lifecycle_excursion_suite.record_closed_position(
                    {
                        **dict(open_row or {}),
                        "exit_timestamp": now_iso,
                        "exit_price": exit_price,
                        "hold_seconds": hold_seconds,
                    },
                    {"price": exit_price, "current_price": exit_price, "timestamp": now_iso},
                    exit_reason=str(exit_reason or ""),
                    source_endpoint="paper_autopilot_natural_close",
                )
            except Exception:
                pass

        if self.trade_intel is not None and hasattr(self.trade_intel, "record_trade"):
            try:
                self.trade_intel.record_trade(
                    {
                        "trade_id": pid,
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "mode": self.paper_mode,
                        "entry_timestamp": entry_ts,
                        "entry_price": entry_price,
                        "entry_predicted_probability": _to_float(
                            entry_payload.get("predicted_win_probability"),
                            _to_float(entry_payload.get("entry_predicted_probability"), 0.0),
                        ),
                        "entry_persona_grade": _to_float(entry_payload.get("persona_weighted_grade"), 0.0),
                        "entry_regime": entry_payload.get("regime_context") or entry_payload.get("market_regime") or "",
                        "market_regime": entry_payload.get("regime_context") or entry_payload.get("market_regime") or "",
                        "entry_persona_fit_summary": entry_payload.get("persona_best_fit") or "",
                        "entry_market_cap_category": entry_payload.get("market_cap_category") or "",
                        "entry_sector": entry_payload.get("sector") or "",
                        "entry_signal_tags": entry_payload.get("signal_tags") or [],
                        "persona_scores_entry": entry_payload.get("persona_grades") or {},
                        "final_consensus_persona_score": _to_float(entry_payload.get("consensus_strength"), 0.0),
                        "buy_mode": entry_payload.get("buy_mode") or "balanced",
                        "buy_eligibility": entry_payload.get("buy_eligibility") or "",
                        "buy_quality_tier": entry_payload.get("buy_quality_tier") or "",
                        "buy_quality_score": _to_float(entry_payload.get("buy_quality_score"), _to_float(entry_payload.get("trade_quality_score"), 0.0)),
                        "entry_confidence": _to_float(entry_payload.get("confidence"), _to_float(entry_payload.get("predicted_win_probability"), 0.0)),
                        "setup_type": entry_payload.get("setup_type") or "unknown",
                        "detected_setup_type": entry_payload.get("detected_setup_type") or entry_payload.get("setup_type") or "unknown",
                        "setup_candidate_realness": entry_payload.get("setup_candidate_realness") or "unknown",
                        "setup_detection_score": _to_float(entry_payload.get("setup_detection_score"), 0.0),
                        "setup_detection_band": entry_payload.get("setup_detection_band") or "unknown",
                        "setup_detection_confidence": _to_float(entry_payload.get("setup_detection_confidence"), 0.0),
                        "setup_detection_evidence_label": entry_payload.get("setup_detection_evidence_label") or "unknown",
                        "conviction_tier": entry_payload.get("conviction_tier") or "",
                        "entry_quality_score": _to_float(entry_payload.get("entry_quality_score"), 0.0),
                        "entry_quality_band": entry_payload.get("entry_quality_band") or "unknown",
                        "entry_quality_candidate_class": entry_payload.get("entry_quality_candidate_class") or "unknown",
                        "entry_quality_primary_driver": entry_payload.get("entry_quality_primary_driver") or "unknown",
                        "entry_quality_primary_penalty": entry_payload.get("entry_quality_primary_penalty") or "unknown",
                        "entry_quality_evidence_label": entry_payload.get("entry_quality_evidence_label") or "unknown",
                        "entry_reason": "paper_autopilot_entry",
                        "signal_tags": entry_payload.get("signal_tags") or [],
                        "exit_timestamp": now_iso,
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "holding_period": hold_seconds,
                        "return_percent": ret,
                        "profit_loss_percent": ret,
                        "friction_adjusted_return": friction_ret,
                        "valid_label": 1,
                        "max_favorable_excursion": _to_float(notes.get("max_favorable_excursion"), max(ret, 0.0)),
                        "max_adverse_excursion": _to_float(notes.get("max_adverse_excursion"), min(ret, 0.0)),
                        "peak_unrealized_pnl_percent": _to_float(notes.get("peak_unrealized_pnl_percent"), max(ret, 0.0)),
                        "drawdown_after_peak_percent": _to_float(notes.get("drawdown_from_peak_percent"), 0.0),
                        "time_to_exit_seconds": hold_seconds,
                        "risk_context_json": {
                            "uncertainty_tier": entry_payload.get("uncertainty_tier"),
                            "uncertainty_score": _to_float(entry_payload.get("uncertainty_score"), 0.0),
                            "core_decision_discipline_tier": entry_payload.get("core_decision_discipline_tier"),
                            "core_decision_discipline_action": entry_payload.get("core_decision_discipline_action"),
                            "entry_commitment_score": _to_float(notes.get("entry_commitment_score"), _to_float(entry_payload.get("entry_commitment_score"), 0.0)),
                            "hold_posture": str(notes.get("hold_posture") or ""),
                            "review_state": str(notes.get("review_state") or ""),
                            "continuation_flag": bool(notes.get("continuation_flag", False)),
                            "deterioration_flag": bool(notes.get("deterioration_flag", False)),
                            "exit_decision_reason": str(exit_reason or ""),
                        },
                        "trade_origin": "paper_autopilot",
                    }
                )
            except Exception:
                pass

        close_map = dict(self._runtime_state.get("last_close_by_symbol") or {})
        close_map[symbol] = time.time()
        self._runtime_state["last_close_by_symbol"] = close_map

        return {
            "ok": True,
            "position_id": pid,
            "symbol": symbol,
            "return_percent": round(ret, 4),
            "exit_reason": exit_reason,
            "hold_seconds": round(hold_seconds, 2),
        }

    def _evaluate_exit(self, open_row: dict[str, Any], latest_row: dict[str, Any]) -> tuple[bool, str]:
        entry = _to_float(open_row.get("entry_price"), 0.0)
        current = _to_float(latest_row.get("price"), 0.0)
        if entry <= 0.0 or current <= 0.0:
            return False, "no_valid_quote"

        ret = ((current - entry) / entry) * 100.0
        notes = _safe_json_load(open_row.get("lifecycle_notes"))
        peak = max(_to_float(notes.get("peak_unrealized_pnl_percent"), ret), ret)
        drawdown = max(0.0, peak - ret)
        hold_seconds = max(0.0, _to_float(open_row.get("hold_seconds"), 0.0))
        hold_minutes = hold_seconds / 60.0

        if ret <= -2.4:
            return True, "stop_loss_breach"
        if peak >= 2.2 and drawdown >= 1.7:
            return True, "drawdown_from_peak"
        if ret >= 4.4:
            return True, "take_profit_lock"
        if hold_minutes >= 180.0 and ret <= -0.9:
            return True, "time_stop_underperforming"
        if hold_minutes >= 420.0 and ret < 0.0:
            return True, "max_hold_window_negative"

        if self.exit_engine is not None and hasattr(self.exit_engine, "evaluate_open_trades"):
            try:
                panel = self.exit_engine.evaluate_open_trades([{"symbol": open_row.get("symbol"), "return_percent": ret}], live_perf={})
                alerts = list((panel or {}).get("alerts") or [])
                if alerts:
                    action = str((alerts[0] or {}).get("recommended_action") or "").strip().upper()
                    if action in {"EXIT", "SELL", "TRIM"}:
                        return True, "exit_engine_signal"
            except Exception:
                pass
        if self.exit_learning is not None and hasattr(self.exit_learning, "expected_risk_if_hold"):
            try:
                risk = dict(
                    self.exit_learning.expected_risk_if_hold(
                        probability_drop_percent=max(0.0, _to_float(latest_row.get("probability_drop_percent"), 0.0)),
                        disagreement_increase=max(0.0, _to_float(latest_row.get("disagreement_increase"), 0.0)),
                        regime_shift=bool(latest_row.get("regime_shift", False)),
                    )
                    or {}
                )
                risk_if_hold = _to_float(risk.get("expected_risk_if_hold"), 0.0)
                if risk_if_hold >= 0.74 and ret <= 1.0:
                    return True, "exit_learning_high_risk_if_hold"
                if risk_if_hold >= 0.64 and drawdown >= 1.4:
                    return True, "exit_learning_deterioration_risk"
            except Exception:
                pass

        return False, "hold"

    def _update_open_row_snapshot(self, open_row: dict[str, Any], latest_row: dict[str, Any]):
        pid = str(open_row.get("position_id") or "").strip()
        if not pid:
            return
        entry = _to_float(open_row.get("entry_price"), 0.0)
        current = _to_float(latest_row.get("price"), 0.0)
        if entry <= 0.0 or current <= 0.0:
            return

        ret = ((current - entry) / entry) * 100.0
        peak = max(_to_float(open_row.get("peak_unrealized_pnl_percent"), ret), ret)
        drawdown = max(0.0, peak - ret)
        mae = min(_to_float(open_row.get("max_adverse_excursion"), ret), ret)
        mfe = max(_to_float(open_row.get("max_favorable_excursion"), ret), ret)
        now_iso = _now_iso()
        hold_seconds = 0.0
        try:
            hold_seconds = max(
                0.0,
                datetime.fromisoformat(now_iso.replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(str(open_row.get("entry_timestamp") or "").replace("Z", "+00:00")).timestamp(),
            )
        except Exception:
            hold_seconds = 0.0
        continuation_flag = bool(ret > 0.0 and peak >= 1.2 and drawdown <= 1.4)
        deterioration_flag = bool(drawdown >= 1.6 or ret <= -1.2)
        hold_posture = "hold"
        if deterioration_flag:
            hold_posture = "tighten_or_exit"
        elif continuation_flag and ret >= 1.0:
            hold_posture = "hold_winner"
        review_state = "monitoring"
        if deterioration_flag:
            review_state = "deteriorating"
        elif continuation_flag:
            review_state = "continuation"

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET lifecycle_notes=?, updated_at=?
                WHERE position_id=?
                """,
                (
                    _safe_json(
                        {
                            "current_price": current,
                            "current_return_percent": ret,
                            "peak_unrealized_pnl_percent": peak,
                            "drawdown_from_peak_percent": drawdown,
                            "max_favorable_excursion": mfe,
                            "max_adverse_excursion": mae,
                            "quote_quality": latest_row.get("quote_quality"),
                            "provider_used": latest_row.get("provider_used") or latest_row.get("source"),
                            "hold_seconds": round(hold_seconds, 2),
                            "lifecycle_stage": "monitoring",
                            "review_state": review_state,
                            "continuation_flag": continuation_flag,
                            "deterioration_flag": deterioration_flag,
                            "hold_posture": hold_posture,
                        }
                    ),
                    now_iso,
                    pid,
                ),
            )
            conn.commit()
        if self._position_tracker is not None:
            try:
                self._position_tracker.update_position_snapshot(
                    identifier=str(open_row.get("position_id") or open_row.get("symbol") or ""),
                    current_price=current,
                    unrealized_return_percent=round(ret, 4),
                    peak_unrealized_pnl_percent=round(peak, 4),
                    drawdown_from_peak_percent=round(drawdown, 4),
                    lifecycle_stage="monitoring",
                    review_state=review_state,
                    hold_posture=hold_posture,
                    continuation_flag=continuation_flag,
                    deterioration_flag=deterioration_flag,
                )
            except Exception:
                pass
        if callable(update_lifecycle_progress):
            try:
                update_lifecycle_progress(
                    pid,
                    {
                        "symbol": str(open_row.get("symbol") or ""),
                        "asset_type": _norm_asset(open_row.get("asset_type") or "stock"),
                        "current_price": current,
                        "pnl_pct": ret,
                        "max_favorable_excursion_pct": mfe,
                        "max_adverse_excursion_pct": mae,
                        "exit_reason": str(open_row.get("exit_reason") or ""),
                        "source_endpoint": "paper_autopilot",
                        "lifecycle_stage": "monitoring",
                    },
                )
            except Exception:
                pass
        if self.trade_lifecycle_excursion_suite is not None and hasattr(self.trade_lifecycle_excursion_suite, "record_open_position"):
            try:
                self.trade_lifecycle_excursion_suite.record_open_position(
                    {
                        **dict(open_row or {}),
                        "lifecycle_notes": _safe_json(
                            {
                                "current_price": current,
                                "current_return_percent": ret,
                                "peak_unrealized_pnl_percent": peak,
                                "drawdown_from_peak_percent": drawdown,
                                "max_favorable_excursion": mfe,
                                "max_adverse_excursion": mae,
                            }
                        ),
                        "hold_seconds": hold_seconds,
                    },
                    latest_row,
                    source_endpoint="paper_autopilot_open_snapshot",
                )
            except Exception:
                pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return {"ok": True, "started": False, "already_running": True}
        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                try:
                    self.run_cycle()
                except Exception as e:
                    self._runtime_state["last_error"] = str(e)[:240]
                self._stop_event.wait(max(5, int(self.interval_seconds)))

        self._thread = threading.Thread(target=_loop, daemon=True, name="astra-paper-autopilot")
        self._thread.start()
        return {"ok": True, "started": True}

    def enabled(self):
        return bool(self._enabled)

    def toggle(self, enabled: bool):
        self._enabled = bool(enabled)
        self._save_state_file()
        return {"ok": True, "autopilot_enabled": self._enabled}

    def enable(self):
        return self.toggle(True)

    def disable(self):
        return self.toggle(False)

    def refresh_enabled_from_state(self):
        self._load_state_file()
        return {"ok": True, "autopilot_enabled": self._enabled}

    def status(self):
        counts = self._count_open_positions()
        open_position_rows_count = self._count_open_position_rows()
        open_positions_count = int(counts.get("stock", 0) + counts.get("crypto", 0))
        open_rows = self._fetch_open_positions()
        broker_snapshot = self._broker_open_symbols_snapshot()
        broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
        raw_open_count = (
            len(broker_open_syms)
            if bool(broker_snapshot.get("broker_reconciliation_active")) and bool(broker_snapshot.get("broker_positions_fetch_ok"))
            else open_positions_count
        )
        adaptive_capacity = self._adaptive_execution_capacity(raw_open_count)
        horizon_capacity = self._horizon_capacity_snapshot(
            open_rows=open_rows,
            broker_open_syms=broker_open_syms,
            broker_reconciliation_active=bool(broker_snapshot.get("broker_reconciliation_active", False)),
            broker_positions_fetch_ok=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
            adaptive_total_capacity=int(adaptive_capacity.get("adaptive_capacity_limit", self.horizon_total_capacity)),
        )
        total_closed = 0
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(1) AS n FROM paper_positions WHERE status='CLOSED'").fetchone()
                total_closed = _to_int((dict(row or {})).get("n"), 0)
        except Exception:
            total_closed = 0

        learned_runtime = self._learned_exit_runtime_summary()
        last_trace = dict(self._runtime_state.get("last_execution_trace") or {})
        return {
            "ok": True,
            "autopilot_enabled": self._enabled,
            "paper_mode": self.paper_mode,
            "open_positions_count": open_positions_count,
            "open_positions_stock": int(counts.get("stock", 0)),
            "open_positions_crypto": int(counts.get("crypto", 0)),
            "open_position_rows_count": int(open_position_rows_count),
            "open_positions_unique_count": int(open_positions_count),
            "stale_internal_workflow_row_overhang": int(max(0, open_position_rows_count - open_positions_count)),
            "adaptive_learning_capacity_policy": adaptive_capacity,
            "horizon_capacity_summary": horizon_capacity,
            "horizon_capacity_enabled": bool(self.horizon_capacity_enabled),
            "horizon_total_capacity": int(self.horizon_total_capacity),
            "horizon_assignment_used": bool(last_trace.get("horizon_assignment_used", False)),
            "horizon_assignment_confidence": _to_float(last_trace.get("horizon_assignment_confidence"), 0.0),
            "horizon_execution_candidate": dict(last_trace.get("horizon_execution_candidate") or {}),
            "horizon_execution_reason": str(last_trace.get("horizon_execution_reason") or ""),
            "horizon_execution_blocker": str(last_trace.get("horizon_execution_blocker") or last_trace.get("final_blocker_reason") or ""),
            "paper_tie_breaker_blocker": str(last_trace.get("paper_tie_breaker_blocker") or last_trace.get("horizon_execution_blocker") or last_trace.get("final_blocker_reason") or ""),
            **learned_runtime,
            "learned_exit_validation_max_exits_per_day": int(self.learned_exit_validation_max_exits_per_day),
            "learned_exit_validation_max_exit_pct": round(float(self.learned_exit_validation_max_exit_pct), 3),
            "learned_exit_validation_min_confidence": round(float(self.learned_exit_validation_min_confidence), 3),
            "learned_exit_validation_min_evidence": int(self.learned_exit_validation_min_evidence),
            "total_closed_trades": int(total_closed),
            "last_cycle_utc": str(self._runtime_state.get("last_cycle_utc") or ""),
            "last_cycle_summary": dict(self._runtime_state.get("last_cycle_summary") or {}),
            "last_execution_trace": dict(self._runtime_state.get("last_execution_trace") or {}),
            "last_error": str(self._runtime_state.get("last_error") or ""),
            "last_updated_utc": _now_iso(),
        }

    def control_status(self):
        learned_runtime = self._learned_exit_runtime_summary()
        last_trace = dict(self._runtime_state.get("last_execution_trace") or {})
        return {
            "autopilot_enabled": self._enabled,
            "paper_mode": self.paper_mode,
            "control_state": "enabled" if self._enabled else "disabled",
            "interval_seconds": int(self.interval_seconds),
            "max_new_positions_per_cycle": int(self.max_new_positions_per_cycle),
            "max_closes_per_cycle": int(self.max_closes_per_cycle),
            "max_stocks": int(self.max_stocks),
            "max_crypto": int(self.max_crypto),
            "max_open_positions_total": int(self.max_open_positions_total),
            "horizon_capacity_enabled": bool(self.horizon_capacity_enabled),
            "horizon_total_capacity": int(self.horizon_total_capacity),
            "horizon_swing_capacity": int(self.horizon_swing_capacity),
            "horizon_day_capacity": int(self.horizon_day_capacity),
            "horizon_scalp_capacity": int(self.horizon_scalp_capacity),
            "horizon_assignment_used": bool(last_trace.get("horizon_assignment_used", False)),
            "horizon_assignment_confidence": _to_float(last_trace.get("horizon_assignment_confidence"), 0.0),
            "horizon_execution_candidate": dict(last_trace.get("horizon_execution_candidate") or {}),
            "horizon_execution_reason": str(last_trace.get("horizon_execution_reason") or ""),
            "horizon_execution_blocker": str(last_trace.get("horizon_execution_blocker") or last_trace.get("final_blocker_reason") or ""),
            "paper_tie_breaker_blocker": str(last_trace.get("paper_tie_breaker_blocker") or last_trace.get("horizon_execution_blocker") or last_trace.get("final_blocker_reason") or ""),
            **learned_runtime,
            "learned_exit_validation_max_exits_per_day": int(self.learned_exit_validation_max_exits_per_day),
            "learned_exit_validation_max_exit_pct": round(float(self.learned_exit_validation_max_exit_pct), 3),
            "learned_exit_validation_min_confidence": round(float(self.learned_exit_validation_min_confidence), 3),
            "learned_exit_validation_min_evidence": int(self.learned_exit_validation_min_evidence),
            "cooldown_after_close_seconds": int(self.cooldown_after_close_seconds),
            "throughput_expansion_enabled": bool(self.throughput_expansion_enabled),
            "adaptive_learning_capacity_policy": self._adaptive_execution_capacity(
                _to_int(last_trace.get("broker_open_positions_count"), self._count_open_positions().get("stock", 0) + self._count_open_positions().get("crypto", 0))
            ),
            "soft_candidate_expansion_enabled": bool(self.soft_candidate_expansion_enabled),
            "paper_entry_threshold_relief_points": round(float(self.paper_entry_threshold_relief_points), 3),
            "paper_learning_capacity_expansion_v1": bool(self.paper_learning_capacity_expansion_v1),
            "paper_learning_capacity_default_target": int(self.paper_learning_capacity_default_target),
            "paper_learning_capacity_upper_bound": int(self.paper_learning_capacity_upper_bound),
            "paper_learning_capacity_reason": "cautious_learning_acceleration_without_forced_trades",
            "suggested_horizon_mix": {"scalp": 3, "day_trade": 5, "swing_short_swing_max": 7},
        }

    def run_cycle(self):
        if not self._enabled:
            safety = self._alpaca_safety_snapshot()
            out = {
                "ok": True,
                "autopilot_enabled": False,
                "orders_submitted": 0,
                "positions_closed": 0,
                "cycle_reason": "disabled",
            }
            trace = {
                "paper_worker_running": bool(self._thread and self._thread.is_alive()),
                **safety,
                "candidates_seen": 0,
                "eligible_candidates": 0,
                "selected_candidates": 0,
                "orders_attempted": 0,
                "orders_submitted": 0,
                "orders_rejected": 0,
                "final_blocker_reason": "paper_autopilot_disabled",
                "per_candidate_decision_trace": [],
                "last_alpaca_error_sanitized": "",
                "live_trading_changed": False,
                "secrets_exposed": False,
            }
            self._runtime_state["last_cycle_utc"] = _now_iso()
            self._runtime_state["last_cycle_summary"] = out
            self._runtime_state["last_execution_trace"] = trace
            return out

        with self._cycle_lock:
            opened = 0
            closed = 0
            skipped = 0
            eligible_count = 0
            selected_count = 0
            orders_attempted = 0
            orders_rejected = 0
            final_blocker_reason = ""
            last_alpaca_error = ""
            portfolio_risk_proof_present = False
            portfolio_risk_score_used = None
            portfolio_risk_label_used = ""
            portfolio_risk_preflight_reason = ""
            horizon_assignment_confidence = 0.0
            horizon_execution_candidate: dict[str, Any] = {}
            horizon_execution_reason = ""
            horizon_execution_blocker = ""
            decision_trace: list[dict[str, Any]] = []
            safety = self._alpaca_safety_snapshot()
            learned_exit_refresh = self._refresh_learned_exit_pending_sells()
            open_rows_initial = self._fetch_open_positions()
            internal_open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows_initial}
            broker_snapshot = self._broker_open_symbols_snapshot()
            broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
            broker_position_by_symbol = dict(broker_snapshot.get("broker_position_by_symbol") or {})
            broker_reconciliation_active = bool(broker_snapshot.get("broker_reconciliation_active", False))
            broker_positions_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
            stale_internal_positions = sorted(x for x in internal_open_syms if x and x not in broker_open_syms)
            stale_internal_positions_count = int(len(stale_internal_positions))
            # When broker reconciliation is active and fetch succeeded, broker positions are the
            # source of truth for duplicate suppression on paper order submission.
            if broker_reconciliation_active and broker_positions_fetch_ok:
                open_syms = set(broker_open_syms)
                capacity_source = "broker"
            else:
                open_syms = set(internal_open_syms)
                capacity_source = "internal"

            open_rows = list(open_rows_initial)
            stale_internal_positions_skipped_for_exit_scan = 0
            if broker_reconciliation_active and broker_positions_fetch_ok:
                broker_symbols_for_exit_scan = {str(s or "").upper().strip() for s in broker_open_syms if str(s or "").strip()}
                broker_confirmed_open_rows = []
                broker_exit_seen: set[str] = set()
                for r in open_rows_initial:
                    row_symbol = str((r or {}).get("symbol") or "").upper().strip()
                    if row_symbol not in broker_symbols_for_exit_scan or row_symbol in broker_exit_seen:
                        continue
                    broker_exit_seen.add(row_symbol)
                    broker_confirmed_open_rows.append(r)
                stale_internal_positions_skipped_for_exit_scan = max(
                    0,
                    len(open_rows_initial) - len(broker_confirmed_open_rows),
                )
                open_rows = broker_confirmed_open_rows
            min_hold = self._min_hold_seconds()
            for row in open_rows:
                if closed >= self.max_closes_per_cycle:
                    break
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                latest = {}
                if broker_reconciliation_active and broker_positions_fetch_ok:
                    broker_pos = dict(broker_position_by_symbol.get(symbol) or {})
                    broker_price = _to_float(
                        broker_pos.get("current_price"),
                        _to_float(broker_pos.get("market_price"), _to_float(broker_pos.get("lastday_price"), 0.0)),
                    )
                    if broker_price > 0.0:
                        latest = {
                            "symbol": symbol,
                            "asset_type": asset,
                            "price": broker_price,
                            "quote_quality": "alpaca_broker_position",
                            "quote_timestamp": _now_iso(),
                            "timestamp": _now_iso(),
                            "source": "alpaca_broker_positions",
                            "provider_used": "alpaca_paper",
                        }
                if callable(self.get_latest_row_fn):
                    if not latest:
                        try:
                            latest = dict(self.get_latest_row_fn(symbol, asset) or {})
                        except Exception:
                            latest = {}
                if not latest:
                    skipped += 1
                    continue
                self._update_open_row_snapshot(row, latest)

                entry_ts = str(row.get("entry_timestamp") or "")
                hold_seconds = 0.0
                try:
                    hold_seconds = max(
                        0.0,
                        datetime.fromisoformat(_now_iso().replace("Z", "+00:00")).timestamp()
                        - datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).timestamp(),
                    )
                except Exception:
                    hold_seconds = 0.0

                if broker_reconciliation_active and broker_positions_fetch_ok:
                    broker_pos = dict(broker_position_by_symbol.get(symbol) or {})
                    learned_sell = self._submit_guarded_learned_exit_sell(row, latest, broker_pos)
                    if bool(learned_sell.get("submitted")):
                        skipped += 1
                        continue

                should_close, reason = self._evaluate_exit(row, latest)
                if should_close and hold_seconds >= float(min_hold):
                    result = self._close_position(row, latest, reason)
                    if result.get("ok"):
                        closed += 1
                        state = self._learned_exit_daily_state()
                        state["baseline_exits"] = _to_int(state.get("baseline_exits"), 0) + 1
                        self._update_learned_exit_daily_state(state)
                        if symbol:
                            open_syms.discard(symbol)

            if capacity_source == "broker":
                broker_stock_open = int(len([s for s in broker_open_syms if s]))
                broker_crypto_open = 0
                effective_capacity_count = broker_stock_open + broker_crypto_open
                adaptive_capacity = self._adaptive_execution_capacity(effective_capacity_count)
                stock_capacity_limit = max(
                    int(self.max_stocks),
                    int(adaptive_capacity.get("adaptive_capacity_limit", self.max_stocks))
                    if adaptive_capacity.get("adaptive_capacity_policy_active")
                    else int(self.max_stocks),
                )
                stock_capacity = max(0, stock_capacity_limit - broker_stock_open)
                crypto_capacity = max(0, self.max_crypto - broker_crypto_open)
                total_capacity = int(adaptive_capacity.get("safe_paper_entry_slots_available", 0))
                stale_internal_positions_ignored_for_broker_capacity = bool(stale_internal_positions_count > 0)
            else:
                counts = self._count_open_positions()
                internal_stock_open = int(counts.get("stock", 0))
                internal_crypto_open = int(counts.get("crypto", 0))
                effective_capacity_count = internal_stock_open + internal_crypto_open
                adaptive_capacity = self._adaptive_execution_capacity(effective_capacity_count)
                stock_capacity_limit = max(
                    int(self.max_stocks),
                    int(adaptive_capacity.get("adaptive_capacity_limit", self.max_stocks))
                    if adaptive_capacity.get("adaptive_capacity_policy_active")
                    else int(self.max_stocks),
                )
                stock_capacity = max(0, stock_capacity_limit - internal_stock_open)
                crypto_capacity = max(0, self.max_crypto - internal_crypto_open)
                total_capacity = int(adaptive_capacity.get("safe_paper_entry_slots_available", 0))
                stale_internal_positions_ignored_for_broker_capacity = False
            horizon_capacity = self._horizon_capacity_snapshot(
                open_rows=open_rows_initial,
                broker_open_syms=broker_open_syms,
                broker_reconciliation_active=broker_reconciliation_active,
                broker_positions_fetch_ok=broker_positions_fetch_ok,
                adaptive_total_capacity=int(adaptive_capacity.get("adaptive_capacity_limit", self.horizon_total_capacity)),
            )
            preferred_execution_horizon = self._preferred_horizon_from_capacity(horizon_capacity)
            horizon_assignment_active = bool(preferred_execution_horizon in {"scalp", "day_trade", "swing_trade"})
            horizon_assignment_used = False
            if self.horizon_capacity_enabled:
                total_capacity = int(horizon_capacity.get("total_available", total_capacity))
                stock_capacity = max(stock_capacity, total_capacity)
            stock_capacity_reason = "stock_capacity_available"
            horizon_capacity_blocked = 0
            high_confidence_horizon_capacity_blocked = 0
            candidates = self._collect_candidate_rows()
            candidate_source = "candidate_source_empty"
            if candidates:
                source_counts: dict[str, int] = {}
                for candidate_row in candidates:
                    source = str(
                        candidate_row.get("paper_autopilot_candidate_source")
                        or candidate_row.get("top_buys_candidate_source")
                        or "top_buys"
                    ).strip() or "top_buys"
                    source_counts[source] = source_counts.get(source, 0) + 1
                candidate_source = max(source_counts.items(), key=lambda item: item[1])[0]
            allocation_status = {}
            if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "status"):
                try:
                    allocation_status = dict(self.paper_opportunity_allocator.status(rows=candidates) or {})
                except Exception:
                    allocation_status = {}
            session_status = {}
            if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "status"):
                try:
                    session_status = dict(
                        self.market_session_timing_suite.status(
                            broker_ready=bool(safety.get("broker_execution_ready") or safety.get("broker_execution_enabled")),
                            open_orders_count=int(_to_float(safety.get("open_orders_count"), 0.0)),
                        )
                        or {}
                    )
                except Exception:
                    session_status = {}
            adaptive_learning_status = {}
            if self.adaptive_learning_infrastructure_suite is not None and hasattr(self.adaptive_learning_infrastructure_suite, "status"):
                try:
                    adaptive_learning_status = dict(
                        self.adaptive_learning_infrastructure_suite.status(
                            rows=candidates,
                            session_timing=session_status,
                        )
                        or {}
                    )
                except Exception:
                    adaptive_learning_status = {}
            replay_lifecycle_status = {}
            if self.replay_lifecycle_expectancy_suite is not None and hasattr(self.replay_lifecycle_expectancy_suite, "status"):
                try:
                    replay_lifecycle_status = dict(self.replay_lifecycle_expectancy_suite.status(rows=candidates) or {})
                except Exception:
                    replay_lifecycle_status = {}
            regime_execution_status = {}
            if self.regime_execution_survivability_suite is not None and hasattr(self.regime_execution_survivability_suite, "status"):
                try:
                    regime_execution_status = dict(self.regime_execution_survivability_suite.status(rows=candidates) or {})
                except Exception:
                    regime_execution_status = {}
            adaptive_execution_exit_status = {}
            if self.adaptive_execution_exit_v2_suite is not None and hasattr(self.adaptive_execution_exit_v2_suite, "status"):
                try:
                    adaptive_execution_exit_status = dict(self.adaptive_execution_exit_v2_suite.status(rows=candidates) or {})
                except Exception:
                    adaptive_execution_exit_status = {}
            portfolio_diversification_status = {}
            if self.portfolio_diversification_v2_suite is not None and hasattr(self.portfolio_diversification_v2_suite, "status"):
                try:
                    portfolio_diversification_status = dict(
                        self.portfolio_diversification_v2_suite.status(
                            rows=candidates,
                            open_positions=open_rows_initial,
                        )
                        or {}
                    )
                except Exception:
                    portfolio_diversification_status = {}
            profit_seeking_exploration_status = {}
            if self.profit_seeking_exploration_suite is not None and hasattr(self.profit_seeking_exploration_suite, "status"):
                try:
                    profit_seeking_exploration_status = dict(
                        self.profit_seeking_exploration_suite.status(
                            rows=candidates,
                            session_status=session_status,
                        )
                        or {}
                    )
                except Exception:
                    profit_seeking_exploration_status = {}
            if horizon_assignment_active:
                candidates = sorted(
                    candidates,
                    key=lambda row: (
                        round(_to_float(row.get("paper_allocation_priority"), 0.0), 2),
                        round(_to_float(row.get("risk_adjusted_profit_score"), 0.0), 2),
                        round(self._horizon_tie_break_score(row, preferred_execution_horizon), 3),
                    ),
                    reverse=True,
                )
            for row in candidates:
                if selected_count >= self.max_new_positions_per_cycle:
                    final_blocker_reason = final_blocker_reason or "max_new_positions_per_cycle_reached"
                    break
                if total_capacity <= 0:
                    final_blocker_reason = final_blocker_reason or "max_concurrent_positions_reached"
                    break
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                if not symbol or symbol in open_syms:
                    skipped += 1
                    reason = "missing_symbol" if not symbol else "duplicate_active_position"
                    duplicate_source = "none"
                    if symbol:
                        in_internal = symbol in internal_open_syms
                        in_broker = symbol in broker_open_syms
                        if in_internal and in_broker:
                            duplicate_source = "both"
                        elif in_internal:
                            duplicate_source = "internal"
                        elif in_broker:
                            duplicate_source = "broker"
                    decision_trace.append({
                        "symbol": symbol,
                        "asset_type": asset,
                        "eligible": False,
                        "selected": False,
                        "decision_reason": reason,
                        "duplicate_source": duplicate_source,
                        "broker_reconciliation_active": broker_reconciliation_active,
                    })
                    final_blocker_reason = reason
                    continue
                if self._cooldown_active(symbol):
                    skipped += 1
                    decision_trace.append({
                        "symbol": symbol,
                        "asset_type": asset,
                        "eligible": False,
                        "selected": False,
                        "decision_reason": "cooldown_active",
                    })
                    final_blocker_reason = "cooldown_active"
                    continue
                candidate_horizon, candidate_horizon_source, candidate_horizon_inferred = _infer_horizon_style(row)
                if not candidate_horizon:
                    candidate_horizon = "unknown"
                    candidate_horizon_source = "missing_horizon"
                    candidate_horizon_inferred = True
                horizon_ok, horizon_capacity_reason = self._horizon_has_capacity(horizon_capacity, candidate_horizon)
                if not horizon_ok:
                    skipped += 1
                    horizon_capacity_blocked += 1
                    confidence_for_block = _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0))
                    if confidence_for_block >= 80.0:
                        high_confidence_horizon_capacity_blocked += 1
                    decision_trace.append({
                        "symbol": symbol,
                        "asset_type": asset,
                        "eligible": False,
                        "selected": False,
                        "decision_reason": horizon_capacity_reason,
                        "trade_horizon_style": candidate_horizon,
                        "paper_entry_horizon_source": candidate_horizon_source,
                        "paper_entry_horizon_inferred": bool(candidate_horizon_inferred),
                        "horizon_capacity": dict(horizon_capacity),
                        "horizon_capacity_enabled": bool(self.horizon_capacity_enabled),
                    })
                    final_blocker_reason = horizon_capacity_reason
                    continue
                if asset == "stock" and stock_capacity <= 0:
                    final_blocker_reason = "stock_capacity_reached"
                    stock_capacity_reason = "stock_capacity_reached"
                    continue
                if asset == "crypto" and crypto_capacity <= 0:
                    final_blocker_reason = "crypto_capacity_reached"
                    continue

                row_trace, allowed, reason, gate_meta = self._candidate_trace_row(
                    row,
                    open_syms=open_syms,
                    stock_capacity=stock_capacity,
                    crypto_capacity=crypto_capacity,
                    total_capacity=total_capacity,
                    selected_so_far=selected_count,
                    internal_open_syms=internal_open_syms,
                    broker_open_syms=broker_open_syms,
                    broker_reconciliation_active=broker_reconciliation_active,
                )
                row_trace["horizon_capacity_enabled"] = bool(self.horizon_capacity_enabled)
                row_trace["horizon_capacity_reason"] = str(horizon_capacity_reason)
                row_trace["horizon_capacity_snapshot"] = dict(horizon_capacity)
                if not allowed:
                    exploration_decision = {}
                    if (
                        self.profit_seeking_exploration_suite is not None
                        and hasattr(self.profit_seeking_exploration_suite, "evaluate_candidate")
                        and eligible_count <= 0
                        and selected_count <= 0
                    ):
                        try:
                            exploration_decision = dict(
                                self.profit_seeking_exploration_suite.evaluate_candidate(
                                    row,
                                    trace=row_trace,
                                    session_status=session_status,
                                    market_context=session_status,
                                    safety=safety,
                                    selected_this_cycle=selected_count,
                                    normal_eligible_count=eligible_count,
                                    portfolio_status=portfolio_diversification_status,
                                )
                                or {}
                            )
                        except Exception as exc:
                            exploration_decision = {
                                "controlled_exploration_considered": True,
                                "controlled_exploration_allowed": False,
                                "controlled_exploration_reason": f"exploration_eval_exception:{str(exc)[:100]}",
                                "exploration_rejection_reason": "exploration_eval_exception",
                            }
                    if exploration_decision:
                        row_trace.update(exploration_decision)
                    if exploration_decision.get("controlled_exploration_allowed"):
                        allowed = True
                        reason = "controlled_profit_seeking_exploration"
                        row_trace["eligible"] = True
                        row_trace["decision_reason"] = reason
                        row_trace["exploration_selected"] = True
                        gate_meta = dict(gate_meta or {})
                        gate_meta["commitment_score"] = max(
                            _to_float(gate_meta.get("commitment_score"), 0.0),
                            _to_float(exploration_decision.get("exploration_trade_quality_score"), 0.0),
                        )
                        gate_meta["controlled_exploration_ok"] = True
                        gate_meta["controlled_exploration_reason"] = str(exploration_decision.get("controlled_exploration_reason") or reason)
                    else:
                        skipped += 1
                        row_trace["selected"] = False
                        row_trace["order_attempted"] = False
                        decision_trace.append(row_trace)
                        if orders_attempted <= 0 and orders_rejected <= 0:
                            final_blocker_reason = str(exploration_decision.get("exploration_rejection_reason") or reason)
                        continue

                eligible_count += 1
                selected_count += 1
                orders_attempted += 1
                row_trace["selected"] = True
                row_trace["order_attempted"] = True
                row_trace["horizon_assignment_confidence"] = round(
                    _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0)),
                    2,
                )
                horizon_assignment_confidence = float(row_trace["horizon_assignment_confidence"])
                horizon_execution_candidate = {
                    "symbol": symbol,
                    "horizon": candidate_horizon,
                    "horizon_source": candidate_horizon_source,
                }
                horizon_assignment_used = bool(horizon_assignment_used or candidate_horizon == preferred_execution_horizon)
                row_trace["horizon_assignment_used"] = bool(horizon_assignment_used)
                horizon_execution_reason = (
                    f"preferred_{preferred_execution_horizon}_tie_break"
                    if horizon_assignment_used
                    else "existing_rank_and_safety_gates_only"
                )
                horizon_execution_blocker = ""
                row_trace["horizon_execution_candidate"] = dict(horizon_execution_candidate)
                row_trace["horizon_execution_reason"] = horizon_execution_reason
                row_trace["horizon_execution_blocker"] = horizon_execution_blocker
                gate_meta = dict(gate_meta or {})
                gate_meta["paper_autopilot_limits_ok"] = True
                gate_meta["paper_autopilot_limits_reason"] = "max_new_max_open_and_capacity_passed"
                opened_row = self._open_position_from_row(
                    row,
                    source_bucket=f"paper_autopilot_{reason}",
                    gate_meta=gate_meta,
                )
                row_trace["portfolio_risk_proof_present"] = bool(opened_row.get("portfolio_risk_proof_present", False))
                row_trace["portfolio_risk_score_used"] = opened_row.get("portfolio_risk_score_used")
                row_trace["portfolio_risk_label_used"] = str(opened_row.get("portfolio_risk_label_used") or "")
                row_trace["portfolio_risk_preflight_reason"] = str(opened_row.get("portfolio_risk_preflight_reason") or "")
                row_trace["paper_autopilot_limits_ok"] = bool(opened_row.get("paper_autopilot_limits_ok", True))
                row_trace["paper_autopilot_limits_reason"] = str(opened_row.get("paper_autopilot_limits_reason") or "")
                row_trace["market_session_mode"] = str(opened_row.get("market_session_mode") or row_trace.get("market_session_mode") or "")
                row_trace["paper_order_submission_allowed"] = bool(opened_row.get("paper_order_submission_allowed", row_trace.get("paper_order_submission_allowed", False)))
                row_trace["execution_confirmation_required"] = bool(opened_row.get("execution_confirmation_required", row_trace.get("execution_confirmation_required", True)))
                row_trace["open_confirmation_score"] = round(_to_float(opened_row.get("open_confirmation_score"), _to_float(row_trace.get("open_confirmation_score"), 0.0)), 2)
                row_trace["open_confirmation_label"] = str(opened_row.get("open_confirmation_label") or row_trace.get("open_confirmation_label") or "")
                row_trace["open_confirmation_reason"] = str(opened_row.get("open_confirmation_reason") or row_trace.get("open_confirmation_reason") or "")
                row_trace["quote_age_seconds"] = opened_row.get("quote_age_seconds", row_trace.get("quote_age_seconds"))
                row_trace["quote_quality"] = str(opened_row.get("quote_quality") or row_trace.get("quote_quality") or "")
                row_trace["latest_quote_preflight_used"] = bool(opened_row.get("latest_quote_preflight_used", row_trace.get("latest_quote_preflight_used", False)))
                row_trace["execution_intent_status"] = str(opened_row.get("execution_intent_status") or row_trace.get("execution_intent_status") or "")
                row_trace["defer_until_market_confirmation"] = bool(opened_row.get("defer_until_market_confirmation", row_trace.get("defer_until_market_confirmation", False)))
                row_trace["requires_open_confirmation"] = bool(opened_row.get("requires_open_confirmation", row_trace.get("requires_open_confirmation", True)))
                row_trace["weekend_watchlist_candidate"] = bool(opened_row.get("weekend_watchlist_candidate", row_trace.get("weekend_watchlist_candidate", False)))
                row_trace["replay_candidate_snapshot_saved"] = bool(opened_row.get("replay_candidate_snapshot_saved", False))
                row_trace["replay_learning_ready"] = bool(opened_row.get("replay_learning_ready", False))
                row_trace["session_timing_outcome_tracking_ready"] = bool(opened_row.get("session_timing_outcome_tracking_ready", False))
                if row_trace["portfolio_risk_proof_present"]:
                    portfolio_risk_proof_present = True
                if row_trace["portfolio_risk_score_used"] is not None:
                    portfolio_risk_score_used = row_trace["portfolio_risk_score_used"]
                if row_trace["portfolio_risk_label_used"]:
                    portfolio_risk_label_used = row_trace["portfolio_risk_label_used"]
                if row_trace["portfolio_risk_preflight_reason"]:
                    portfolio_risk_preflight_reason = row_trace["portfolio_risk_preflight_reason"]
                if opened_row.get("ok"):
                    opened += 1
                    row_trace["order_submitted"] = True
                    row_trace["order_result"] = "submitted"
                    open_syms.add(symbol)
                    internal_open_syms.add(symbol)
                    if broker_reconciliation_active:
                        broker_open_syms.add(symbol)
                    total_capacity = max(0, total_capacity - 1)
                    if asset == "stock":
                        stock_capacity = max(0, stock_capacity - 1)
                    else:
                        crypto_capacity = max(0, crypto_capacity - 1)
                    horizon_capacity = self._consume_horizon_capacity(horizon_capacity, candidate_horizon)
                else:
                    skipped += 1
                    orders_rejected += 1
                    row_trace["order_submitted"] = False
                    row_trace["order_result"] = "rejected"
                    row_trace["order_rejection_reason"] = str(
                        opened_row.get("broker_error")
                        or opened_row.get("open_confirmation_reason")
                        or opened_row.get("error")
                        or "paper_order_rejected"
                    )[:180]
                    broker_error = self._sanitize_broker_error(opened_row)
                    if broker_error:
                        row_trace["broker_error_sanitized"] = broker_error
                        last_alpaca_error = broker_error
                    final_blocker_reason = broker_error or str(opened_row.get("error") or "paper_order_rejected")
                decision_trace.append(row_trace)

            if opened > 0:
                final_blocker_reason = "orders_submitted"
            elif not final_blocker_reason:
                if not candidates:
                    final_blocker_reason = "no_candidates_available"
                elif eligible_count <= 0:
                    final_blocker_reason = "no_eligible_candidates"
                elif orders_attempted <= 0:
                    final_blocker_reason = "no_orders_attempted"
                else:
                    final_blocker_reason = "orders_not_submitted"
            if opened <= 0 and not bool(session_status.get("paper_order_submission_allowed", False)):
                final_blocker_reason = "session_order_submission_blocked"
            out = {
                "ok": True,
                "autopilot_enabled": True,
                "orders_submitted": int(opened),
                "orders_attempted": int(orders_attempted),
                "orders_rejected": int(orders_rejected),
                "positions_closed": int(closed),
                "learned_exit_pending_refresh": dict(learned_exit_refresh),
                "positions_skipped": int(skipped),
                "candidates_seen": int(len(candidates)),
                "paper_opportunity_allocation": allocation_status,
                "market_session_execution_timing": session_status,
                "adaptive_learning_infrastructure": adaptive_learning_status,
                "replay_lifecycle_expectancy_learning": replay_lifecycle_status,
                "regime_execution_survivability": regime_execution_status,
                "adaptive_execution_exit_intelligence_v2": adaptive_execution_exit_status,
                "portfolio_diversification_correlation_v2": portfolio_diversification_status,
                "profit_seeking_adaptive_exploration": profit_seeking_exploration_status,
                "market_session_mode": str(session_status.get("market_session_mode") or ""),
                "paper_order_submission_allowed": bool(session_status.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": bool(session_status.get("execution_confirmation_required", True)),
                "execution_intent_status": str(session_status.get("execution_intent_status") or ""),
                "defer_until_market_confirmation": bool(session_status.get("defer_until_market_confirmation", False)),
                "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
                "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
                "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
                "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
                "eligible_candidates": int(eligible_count),
                "selected_candidates": int(selected_count),
                "final_blocker_reason": str(final_blocker_reason)[:180],
                "last_alpaca_error_sanitized": str(last_alpaca_error)[:180],
                "horizon_assignment_used": bool(horizon_assignment_used and selected_count > 0),
                "horizon_assignment_confidence": round(horizon_assignment_confidence, 2),
                "horizon_execution_candidate": dict(horizon_execution_candidate),
                "horizon_execution_reason": str(horizon_execution_reason or ""),
                "horizon_execution_blocker": str(horizon_execution_blocker or final_blocker_reason or ""),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": portfolio_risk_score_used,
                "portfolio_risk_label_used": str(portfolio_risk_label_used),
                "portfolio_risk_preflight_reason": str(portfolio_risk_preflight_reason),
                "internal_open_positions_count": int(len([s for s in internal_open_syms if s])),
                "open_position_rows_count": int(len(open_rows_initial)),
                "open_positions_unique_count": int(len([s for s in internal_open_syms if s])),
                "broker_open_positions_count": int(len([s for s in broker_open_syms if s])),
                "effective_broker_capacity_count": int(len([s for s in broker_open_syms if s])),
                "stale_internal_positions_count": stale_internal_positions_count,
                "stale_internal_workflow_row_overhang": int(max(0, len(open_rows_initial) - len([s for s in internal_open_syms if s]))),
                "stale_internal_positions": stale_internal_positions[:32],
                "stale_internal_positions_skipped_for_exit_scan": int(stale_internal_positions_skipped_for_exit_scan),
                "capacity_source": str(adaptive_capacity.get("capacity_source") or capacity_source),
                "effective_capacity_count": int(effective_capacity_count),
                "capacity_available": int(total_capacity),
                "capacity_blocked": bool(total_capacity <= 0),
                "adaptive_learning_capacity_policy": dict(adaptive_capacity),
                "adaptive_capacity_used_by_scanner": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
                "adaptive_capacity_used_by_candidate_filter": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
                "adaptive_capacity_used_by_entry_gate": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
                "adaptive_capacity_used_by_paper_trade_creation": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
                "horizon_capacity_summary": {
                    **dict(horizon_capacity),
                    "candidates_blocked_by_horizon_capacity": int(horizon_capacity_blocked),
                    "high_confidence_candidates_blocked_by_capacity": int(high_confidence_horizon_capacity_blocked),
                    "missed_evidence_due_to_capacity": int(horizon_capacity_blocked),
                },
                "horizon_capacity_enabled": bool(self.horizon_capacity_enabled),
                "horizon_total_capacity": int(self.horizon_total_capacity),
                "candidates_blocked_by_horizon_capacity": int(horizon_capacity_blocked),
                "high_confidence_candidates_blocked_by_capacity": int(high_confidence_horizon_capacity_blocked),
                "missed_evidence_due_to_capacity": int(horizon_capacity_blocked),
                "stock_capacity_limit": int(stock_capacity_limit),
                "paper_learning_capacity_expansion_v1": bool(self.paper_learning_capacity_expansion_v1),
                "paper_learning_capacity_reason": "cautious_learning_acceleration_without_forced_trades",
                "paper_learning_capacity_default_target": int(self.paper_learning_capacity_default_target),
                "paper_learning_capacity_upper_bound": int(self.paper_learning_capacity_upper_bound),
                "suggested_horizon_mix": {"scalp": 3, "day_trade": 5, "swing_short_swing_max": 7},
                "stock_capacity_reason": str(stock_capacity_reason),
                "stale_internal_positions_ignored_for_broker_capacity": bool(stale_internal_positions_ignored_for_broker_capacity),
                "broker_reconciliation_active": broker_reconciliation_active,
                "broker_positions_fetch_ok": broker_positions_fetch_ok,
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
                "cycle_timestamp": _now_iso(),
                "last_autopilot_cycle_at": _now_iso(),
                "autopilot_loop_active": bool(self._thread and self._thread.is_alive()),
                "market_open_cycle_detected": bool(session_status.get("paper_order_submission_allowed", False)),
                "candidate_source": str(candidate_source),
                "bridge_available": False,
                "bridge_used": False,
                "bridge_selected_symbols": [],
                "why_no_trade_today": (
                    "orders_submitted"
                    if opened > 0
                    else str(final_blocker_reason or "orders_not_submitted")[:180]
                ),
                **self._learned_exit_runtime_summary(),
            }
            trace = {
                "paper_worker_running": bool(self._thread and self._thread.is_alive()),
                "last_autopilot_cycle_at": out["last_autopilot_cycle_at"],
                "autopilot_loop_active": bool(self._thread and self._thread.is_alive()),
                "market_open_cycle_detected": bool(session_status.get("paper_order_submission_allowed", False)),
                **safety,
                "candidates_seen": int(len(candidates)),
                "candidate_source": str(candidate_source),
                "paper_opportunity_allocation": allocation_status,
                "market_session_execution_timing": session_status,
                "adaptive_learning_infrastructure": adaptive_learning_status,
                "replay_lifecycle_expectancy_learning": replay_lifecycle_status,
                "regime_execution_survivability": regime_execution_status,
                "adaptive_execution_exit_intelligence_v2": adaptive_execution_exit_status,
                "portfolio_diversification_correlation_v2": portfolio_diversification_status,
                "profit_seeking_adaptive_exploration": profit_seeking_exploration_status,
                "market_session_mode": str(session_status.get("market_session_mode") or ""),
                "paper_order_submission_allowed": bool(session_status.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": bool(session_status.get("execution_confirmation_required", True)),
                "execution_intent_status": str(session_status.get("execution_intent_status") or ""),
                "defer_until_market_confirmation": bool(session_status.get("defer_until_market_confirmation", False)),
                "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
                "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
                "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
                "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
                "eligible_candidates": int(eligible_count),
                "selected_candidates": int(selected_count),
                "orders_attempted": int(orders_attempted),
                "orders_submitted": int(opened),
                "orders_rejected": int(orders_rejected),
                "final_blocker_reason": str(final_blocker_reason)[:180],
                "horizon_assignment_used": bool(horizon_assignment_used and selected_count > 0),
                "horizon_assignment_confidence": round(horizon_assignment_confidence, 2),
                "horizon_execution_candidate": dict(horizon_execution_candidate),
                "horizon_execution_reason": str(horizon_execution_reason or ""),
                "horizon_execution_blocker": str(horizon_execution_blocker or final_blocker_reason or ""),
                "paper_tie_breaker_blocker": str(horizon_execution_blocker or final_blocker_reason or ""),
                "per_candidate_decision_trace": decision_trace[:12],
                "last_alpaca_error_sanitized": str(last_alpaca_error)[:180],
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": portfolio_risk_score_used,
                "portfolio_risk_label_used": str(portfolio_risk_label_used),
                "portfolio_risk_preflight_reason": str(portfolio_risk_preflight_reason),
                "internal_open_positions_count": int(len([s for s in internal_open_syms if s])),
                "open_position_rows_count": int(len(open_rows_initial)),
                "open_positions_unique_count": int(len([s for s in internal_open_syms if s])),
                "broker_open_positions_count": int(len([s for s in broker_open_syms if s])),
                "effective_broker_capacity_count": int(len([s for s in broker_open_syms if s])),
                "stale_internal_positions_count": stale_internal_positions_count,
                "stale_internal_workflow_row_overhang": int(max(0, len(open_rows_initial) - len([s for s in internal_open_syms if s]))),
                "stale_internal_positions": stale_internal_positions[:32],
                "stale_internal_positions_skipped_for_exit_scan": int(stale_internal_positions_skipped_for_exit_scan),
                "capacity_source": str(capacity_source),
                "effective_capacity_count": int(effective_capacity_count),
                "capacity_available": int(total_capacity),
                "capacity_blocked": bool(total_capacity <= 0),
                "horizon_capacity_summary": {
                    **dict(horizon_capacity),
                    "candidates_blocked_by_horizon_capacity": int(horizon_capacity_blocked),
                    "high_confidence_candidates_blocked_by_capacity": int(high_confidence_horizon_capacity_blocked),
                    "missed_evidence_due_to_capacity": int(horizon_capacity_blocked),
                },
                "horizon_capacity_enabled": bool(self.horizon_capacity_enabled),
                "horizon_total_capacity": int(self.horizon_total_capacity),
                "candidates_blocked_by_horizon_capacity": int(horizon_capacity_blocked),
                "high_confidence_candidates_blocked_by_capacity": int(high_confidence_horizon_capacity_blocked),
                "missed_evidence_due_to_capacity": int(horizon_capacity_blocked),
                "stock_capacity_limit": int(self.max_stocks),
                "stock_capacity_reason": str(stock_capacity_reason),
                "stale_internal_positions_ignored_for_broker_capacity": bool(stale_internal_positions_ignored_for_broker_capacity),
                "broker_reconciliation_active": broker_reconciliation_active,
                "broker_positions_fetch_ok": broker_positions_fetch_ok,
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
                "bridge_available": False,
                "bridge_used": False,
                "bridge_selected_symbols": [],
                "why_no_trade_today": (
                    "orders_submitted"
                    if opened > 0
                    else str(final_blocker_reason or "orders_not_submitted")[:180]
                ),
                **self._learned_exit_runtime_summary(),
                "live_trading_changed": False,
                "secrets_exposed": False,
            }
            if self.execution_participation_audit_suite is not None and hasattr(self.execution_participation_audit_suite, "record_candidate_traces"):
                try:
                    self.execution_participation_audit_suite.record_candidate_traces(
                        decision_trace,
                        context={**trace, "cycle_timestamp": out["cycle_timestamp"]},
                    )
                except Exception:
                    pass
            self._runtime_state["last_cycle_utc"] = out["cycle_timestamp"]
            self._runtime_state["last_cycle_summary"] = dict(out)
            self._runtime_state["last_execution_trace"] = dict(trace)
            self._runtime_state["last_error"] = ""
            self._save_state_file()
            return out

    def execution_trace(self, max_candidates: int = 12) -> dict[str, Any]:
        status = self.status()
        last_trace = dict(self._runtime_state.get("last_execution_trace") or {})
        candidates = self._collect_candidate_rows()
        allocation_status = {}
        if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "status"):
            try:
                allocation_status = dict(self.paper_opportunity_allocator.status(rows=candidates) or {})
            except Exception:
                allocation_status = {}
        session_status = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "status"):
            try:
                session_status = dict(
                    self.market_session_timing_suite.status(
                        broker_ready=bool(self._alpaca_paper_broker_enabled()),
                        open_orders_count=0,
                    )
                    or {}
                )
            except Exception:
                session_status = {}
        adaptive_learning_status = {}
        if self.adaptive_learning_infrastructure_suite is not None and hasattr(self.adaptive_learning_infrastructure_suite, "status"):
            try:
                adaptive_learning_status = dict(
                    self.adaptive_learning_infrastructure_suite.status(
                        rows=candidates,
                        paper_trace=last_trace,
                        session_timing=session_status,
                    )
                    or {}
                )
            except Exception:
                adaptive_learning_status = {}
        replay_lifecycle_status = {}
        if self.replay_lifecycle_expectancy_suite is not None and hasattr(self.replay_lifecycle_expectancy_suite, "status"):
            try:
                replay_lifecycle_status = dict(
                    self.replay_lifecycle_expectancy_suite.status(
                        rows=candidates,
                        paper_trace=last_trace,
                    )
                    or {}
                )
            except Exception:
                replay_lifecycle_status = {}
        regime_execution_status = {}
        if self.regime_execution_survivability_suite is not None and hasattr(self.regime_execution_survivability_suite, "status"):
            try:
                regime_execution_status = dict(
                    self.regime_execution_survivability_suite.status(
                        rows=candidates,
                        paper_trace=last_trace,
                    )
                    or {}
                )
            except Exception:
                regime_execution_status = {}
        adaptive_execution_exit_status = {}
        if self.adaptive_execution_exit_v2_suite is not None and hasattr(self.adaptive_execution_exit_v2_suite, "status"):
            try:
                adaptive_execution_exit_status = dict(
                    self.adaptive_execution_exit_v2_suite.status(
                        rows=candidates,
                        paper_trace=last_trace,
                    )
                    or {}
                )
            except Exception:
                adaptive_execution_exit_status = {}
        portfolio_diversification_status = {}
        if self.portfolio_diversification_v2_suite is not None and hasattr(self.portfolio_diversification_v2_suite, "status"):
            try:
                portfolio_diversification_status = dict(
                    self.portfolio_diversification_v2_suite.status(
                        rows=candidates,
                        open_positions=self._fetch_open_positions(),
                    )
                    or {}
                )
            except Exception:
                portfolio_diversification_status = {}
        profit_seeking_exploration_status = {}
        if self.profit_seeking_exploration_suite is not None and hasattr(self.profit_seeking_exploration_suite, "status"):
            try:
                profit_seeking_exploration_status = dict(
                    self.profit_seeking_exploration_suite.status(
                        rows=candidates,
                        paper_trace=last_trace,
                        session_status=session_status,
                    )
                    or {}
                )
            except Exception:
                profit_seeking_exploration_status = {}
        broad_universe_status = {}
        if self.broad_universe_intake_promotion_suite is not None and hasattr(self.broad_universe_intake_promotion_suite, "status"):
            try:
                broad_universe_status = dict(self.broad_universe_intake_promotion_suite.status(rows=candidates) or {})
            except Exception:
                broad_universe_status = {}
        capacities = self._current_execution_capacities()
        internal_open_syms = set(capacities.get("open_symbols") or set())
        broker_snapshot = self._broker_open_symbols_snapshot()
        broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
        broker_reconciliation_active = bool(broker_snapshot.get("broker_reconciliation_active", False))
        broker_positions_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
        broker_learning_rows = self._broker_learning_position_rows(broker_snapshot, self._fetch_open_positions())
        stale_internal_positions = sorted(x for x in internal_open_syms if x and x not in broker_open_syms)
        if broker_reconciliation_active and broker_positions_fetch_ok:
            open_syms = set(broker_open_syms)
            capacity_source = "broker"
            effective_stock_open = int(len([s for s in broker_open_syms if s]))
            effective_crypto_open = 0
        else:
            open_syms = set(internal_open_syms)
            capacity_source = "internal"
            effective_stock_open = int(capacities.get("open_positions_stock", 0))
            effective_crypto_open = int(capacities.get("open_positions_crypto", 0))
        effective_capacity_count = int(effective_stock_open + effective_crypto_open)
        adaptive_capacity = self._adaptive_execution_capacity(effective_capacity_count)
        stock_capacity_limit = max(
            int(self.max_stocks),
            int(adaptive_capacity.get("adaptive_capacity_limit", self.max_stocks))
            if adaptive_capacity.get("adaptive_capacity_policy_active")
            else int(self.max_stocks),
        )
        stock_capacity = max(0, stock_capacity_limit - int(effective_stock_open))
        crypto_capacity = max(0, int(self.max_crypto) - int(effective_crypto_open))
        total_capacity = int(adaptive_capacity.get("safe_paper_entry_slots_available", 0))
        decision_rows: list[dict[str, Any]] = []
        eligible = 0
        selected = 0
        safety = self._alpaca_safety_snapshot()
        for row in candidates[: max(1, min(30, int(max_candidates or 12)))]:
            trace, allowed, _reason, _gate_meta = self._candidate_trace_row(
                row,
                open_syms=open_syms,
                stock_capacity=stock_capacity,
                crypto_capacity=crypto_capacity,
                total_capacity=total_capacity,
                selected_so_far=selected,
                internal_open_syms=internal_open_syms,
                broker_open_syms=broker_open_syms,
                broker_reconciliation_active=broker_reconciliation_active,
            )
            if allowed:
                eligible += 1
                if selected < self.max_new_positions_per_cycle and total_capacity > 0:
                    selected += 1
                    trace["selected"] = True
                else:
                    trace["selected"] = False
            else:
                if self.profit_seeking_exploration_suite is not None and hasattr(self.profit_seeking_exploration_suite, "evaluate_candidate"):
                    try:
                        exploration_decision = dict(
                            self.profit_seeking_exploration_suite.evaluate_candidate(
                                row,
                                trace=trace,
                                session_status=session_status,
                                market_context=session_status,
                                safety=safety,
                                selected_this_cycle=selected,
                                normal_eligible_count=eligible,
                                portfolio_status=portfolio_diversification_status,
                            )
                            or {}
                        )
                        trace.update(exploration_decision)
                    except Exception as exc:
                        trace.update({
                            "controlled_exploration_considered": True,
                            "controlled_exploration_allowed": False,
                            "controlled_exploration_reason": f"exploration_eval_exception:{str(exc)[:100]}",
                            "exploration_rejection_reason": "exploration_eval_exception",
                        })
                if trace.get("controlled_exploration_allowed"):
                    eligible += 1
                    trace["eligible"] = True
                    trace["decision_reason"] = "controlled_profit_seeking_exploration"
                    trace["exploration_selected"] = bool(selected < self.max_new_positions_per_cycle and total_capacity > 0)
                    if selected < self.max_new_positions_per_cycle and total_capacity > 0:
                        selected += 1
                        trace["selected"] = True
                    else:
                        trace["selected"] = False
                else:
                    trace["selected"] = False
            decision_rows.append(trace)
        final_blocker = str(last_trace.get("final_blocker_reason") or "")
        if not final_blocker:
            if not self._enabled:
                final_blocker = "paper_autopilot_disabled"
            elif not candidates:
                final_blocker = "no_candidates_available"
            elif eligible <= 0:
                final_blocker = "no_eligible_candidates"
            elif not safety.get("broker_execution_enabled"):
                final_blocker = "alpaca_paper_broker_disabled"
            else:
                final_blocker = "awaiting_next_worker_cycle"
        session_allows_orders = bool(
            last_trace.get(
                "paper_order_submission_allowed",
                session_status.get("paper_order_submission_allowed", False),
            )
        )
        if not session_allows_orders and int(last_trace.get("orders_submitted", 0)) <= 0:
            final_blocker = "session_order_submission_blocked"
        internal_open_workflow_rows = int(len([s for s in internal_open_syms if s]))
        broker_open_positions_count = int(len([s for s in broker_open_syms if s]))
        stale_internal_positions_count = int(len(stale_internal_positions))
        broker_truth_available = bool(broker_reconciliation_active and broker_positions_fetch_ok)
        if broker_truth_available:
            display_active_positions_count = broker_open_positions_count
            position_display_truth_source = "alpaca_broker_positions"
            open_positions_count_source = "alpaca_broker_positions"
        else:
            display_active_positions_count = internal_open_workflow_rows
            position_display_truth_source = "internal_workflow_rows"
            open_positions_count_source = "internal_workflow_rows"
        stale_hidden_from_active = bool(broker_truth_available and stale_internal_positions_count > 0)
        returned_decision_trace = list(last_trace.get("per_candidate_decision_trace") or [])
        if not returned_decision_trace:
            returned_decision_trace = list(decision_rows)
        return {
            "enabled": True,
            "mode": "paper_only",
            "paper_worker_running": bool(self._thread and self._thread.is_alive()),
            "autopilot_loop_active": bool(self._thread and self._thread.is_alive()),
            "autopilot_enabled": bool(self._enabled),
            **safety,
            "open_positions_count": int(display_active_positions_count),
            "open_positions_count_source": str(open_positions_count_source),
            "display_active_positions_count": int(display_active_positions_count),
            "position_display_truth_source": str(position_display_truth_source),
            "stale_internal_positions_hidden_from_active_view": bool(stale_hidden_from_active),
            "max_new_positions_per_cycle": int(self.max_new_positions_per_cycle),
            "max_open_positions_total": int(self.max_open_positions_total),
            "candidates_seen": int(len(candidates)),
            "paper_opportunity_allocation": allocation_status,
            "market_session_execution_timing": session_status,
            "adaptive_learning_infrastructure": adaptive_learning_status,
            "replay_lifecycle_expectancy_learning": replay_lifecycle_status,
            "regime_execution_survivability": regime_execution_status,
            "adaptive_execution_exit_intelligence_v2": adaptive_execution_exit_status,
            "portfolio_diversification_correlation_v2": portfolio_diversification_status,
            "profit_seeking_adaptive_exploration": profit_seeking_exploration_status,
            "broad_universe_intake_promotion": broad_universe_status,
            "paper_autopilot_candidate_source": (
                "broad_universe_promoted_top_buys"
                if any(bool((r or {}).get("selected_from_broad_universe", False)) for r in candidates)
                else "top_buys"
            ),
            "broad_universe_candidates_available": bool(broad_universe_status.get("promoted_to_top_buys_count", 0)),
            "promoted_candidates_available": bool(broad_universe_status.get("promoted_to_top_buys_count", 0)),
            "market_session_mode": str(last_trace.get("market_session_mode") or session_status.get("market_session_mode") or ""),
            "paper_order_submission_allowed": bool(last_trace.get("paper_order_submission_allowed", session_status.get("paper_order_submission_allowed", False))),
            "market_open_cycle_detected": bool(
                last_trace.get("market_open_cycle_detected", session_status.get("paper_order_submission_allowed", False))
            ),
            "candidate_source": str(
                last_trace.get("candidate_source")
                or (
                    "broad_universe_promoted_top_buys"
                    if any(bool((r or {}).get("selected_from_broad_universe", False)) for r in candidates)
                    else "top_buys"
                )
            ),
            "execution_confirmation_required": bool(last_trace.get("execution_confirmation_required", session_status.get("execution_confirmation_required", True))),
            "execution_intent_status": str(last_trace.get("execution_intent_status") or session_status.get("execution_intent_status") or ""),
            "defer_until_market_confirmation": bool(last_trace.get("defer_until_market_confirmation", session_status.get("defer_until_market_confirmation", False))),
            "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
            "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
            "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
            "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
            "eligible_candidates": int(last_trace.get("eligible_candidates", eligible)),
            "selected_candidates": int(last_trace.get("selected_candidates", selected)),
            "orders_attempted": int(last_trace.get("orders_attempted", 0)),
            "orders_submitted": int(last_trace.get("orders_submitted", 0)),
            "orders_rejected": int(last_trace.get("orders_rejected", 0)),
            "final_blocker_reason": final_blocker[:180],
            "per_candidate_decision_trace": returned_decision_trace[:max_candidates],
            "last_alpaca_error_sanitized": str(last_trace.get("last_alpaca_error_sanitized") or "")[:180],
            "portfolio_risk_proof_present": bool(last_trace.get("portfolio_risk_proof_present", False)),
            "portfolio_risk_score_used": last_trace.get("portfolio_risk_score_used"),
            "portfolio_risk_label_used": str(last_trace.get("portfolio_risk_label_used") or ""),
            "portfolio_risk_preflight_reason": str(last_trace.get("portfolio_risk_preflight_reason") or ""),
            "internal_open_workflow_rows": int(internal_open_workflow_rows),
            "internal_open_positions_count": int(internal_open_workflow_rows),
            "broker_open_positions_count": int(broker_open_positions_count),
            "effective_broker_capacity_count": int(last_trace.get("effective_broker_capacity_count", len([s for s in broker_open_syms if s]))),
            "stale_internal_positions_count": int(stale_internal_positions_count),
            "stale_internal_positions": list(last_trace.get("stale_internal_positions") or sorted(x for x in internal_open_syms if x and x not in broker_open_syms))[:32],
            "capacity_source": str(last_trace.get("capacity_source") or capacity_source),
            "effective_capacity_count": int(last_trace.get("effective_capacity_count", effective_capacity_count)),
            "stock_capacity_limit": int(last_trace.get("stock_capacity_limit", stock_capacity_limit)),
            "adaptive_learning_capacity_policy": dict(
                last_trace.get("adaptive_learning_capacity_policy") or adaptive_capacity
            ),
            "adaptive_capacity_used_by_scanner": bool(
                last_trace.get("adaptive_capacity_used_by_scanner", adaptive_capacity.get("adaptive_capacity_policy_active"))
            ),
            "adaptive_capacity_used_by_candidate_filter": bool(
                last_trace.get("adaptive_capacity_used_by_candidate_filter", adaptive_capacity.get("adaptive_capacity_policy_active"))
            ),
            "adaptive_capacity_used_by_entry_gate": bool(
                last_trace.get("adaptive_capacity_used_by_entry_gate", adaptive_capacity.get("adaptive_capacity_policy_active"))
            ),
            "adaptive_capacity_used_by_paper_trade_creation": bool(
                last_trace.get("adaptive_capacity_used_by_paper_trade_creation", adaptive_capacity.get("adaptive_capacity_policy_active"))
            ),
            "paper_learning_capacity_expansion_v1": bool(last_trace.get("paper_learning_capacity_expansion_v1", self.paper_learning_capacity_expansion_v1)),
            "paper_learning_capacity_reason": str(last_trace.get("paper_learning_capacity_reason") or "cautious_learning_acceleration_without_forced_trades"),
            "paper_learning_capacity_default_target": int(last_trace.get("paper_learning_capacity_default_target", self.paper_learning_capacity_default_target)),
            "paper_learning_capacity_upper_bound": int(last_trace.get("paper_learning_capacity_upper_bound", self.paper_learning_capacity_upper_bound)),
            "suggested_horizon_mix": dict(last_trace.get("suggested_horizon_mix") or {"scalp": 3, "day_trade": 5, "swing_short_swing_max": 7}),
            "stock_capacity_reason": str(last_trace.get("stock_capacity_reason") or ""),
            "stale_internal_positions_ignored_for_broker_capacity": bool(
                last_trace.get(
                    "stale_internal_positions_ignored_for_broker_capacity",
                    bool(capacity_source == "broker" and len(stale_internal_positions) > 0),
                )
            ),
            "broker_reconciliation_active": bool(last_trace.get("broker_reconciliation_active", broker_reconciliation_active)),
            "broker_positions_fetch_ok": bool(last_trace.get("broker_positions_fetch_ok", broker_positions_fetch_ok)),
            "broker_positions_error_sanitized": str(last_trace.get("broker_positions_error_sanitized") or broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
            "broker_learning_position_rows": list(
                last_trace.get("broker_learning_position_rows") or broker_learning_rows
            )[:40],
            "last_cycle_utc": str(status.get("last_cycle_utc") or ""),
            "last_autopilot_cycle_at": str(last_trace.get("last_autopilot_cycle_at") or status.get("last_cycle_utc") or ""),
            "last_cycle_summary": dict(status.get("last_cycle_summary") or {}),
            "bridge_available": bool(last_trace.get("bridge_available", False)),
            "bridge_used": bool(last_trace.get("bridge_used", False)),
            "bridge_selected_symbols": list(last_trace.get("bridge_selected_symbols") or [])[:8],
            "why_no_trade_today": str(last_trace.get("why_no_trade_today") or final_blocker or "")[:180],
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "live_trading_changed": False,
            "secrets_exposed": False,
            "generated_at": _now_iso(),
        }

    def market_open_dry_run(self, max_candidates: int = 30) -> dict[str, Any]:
        """Simulate a regular-market paper entry cycle without touching broker state."""
        candidates = self._collect_candidate_rows()
        safety = self._alpaca_safety_snapshot()
        actual_session = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "status"):
            try:
                actual_session = dict(
                    self.market_session_timing_suite.status(
                        broker_ready=bool(safety.get("broker_execution_enabled")),
                        open_orders_count=0,
                    )
                    or {}
                )
            except Exception:
                actual_session = {}
        simulated_session = {
            "market_session_mode": "regular_market",
            "current_session_type": "regular_market",
            "market_is_open": True,
            "market_is_tradable": True,
            "session_tradable": True,
            "paper_order_submission_allowed": True,
            "broker_order_submission_allowed": True,
            "execution_confirmation_required": False,
            "open_confirmation_score": 92.0,
            "open_confirmation_label": "confirmed_execute",
            "open_confirmation_reason": "dry_run_regular_market_simulation",
            "quote_freshness_confirmed": True,
            "spread_liquidity_confirmed": True,
            "gap_behavior_confirmed": True,
            "entry_commitment_confirmed": True,
            "portfolio_risk_confirmed": True,
            "broker_preflight_confirmed": bool(safety.get("broker_execution_enabled")),
            "execution_intent_status": "dry_run_execute_ready",
            "defer_until_market_confirmation": False,
            "requires_open_confirmation": False,
            "session_reason": "Simulated market-open dry run; real session gate left unchanged.",
        }
        broad_status = {}
        if self.broad_universe_intake_promotion_suite is not None and hasattr(self.broad_universe_intake_promotion_suite, "status"):
            try:
                broad_status = dict(self.broad_universe_intake_promotion_suite.status(rows=candidates) or {})
            except Exception:
                broad_status = {}

        capacities = self._current_execution_capacities()
        internal_open_syms = set(capacities.get("open_symbols") or set())
        broker_snapshot = self._broker_open_symbols_snapshot()
        broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
        broker_reconciliation_active = bool(broker_snapshot.get("broker_reconciliation_active", False))
        broker_positions_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
        if broker_reconciliation_active and broker_positions_fetch_ok:
            open_syms = set(broker_open_syms)
            effective_stock_open = int(len([s for s in broker_open_syms if s]))
            effective_crypto_open = 0
            capacity_source = "broker"
        else:
            open_syms = set(internal_open_syms)
            effective_stock_open = int(capacities.get("open_positions_stock", 0))
            effective_crypto_open = int(capacities.get("open_positions_crypto", 0))
            capacity_source = "internal"
        adaptive_capacity = self._adaptive_execution_capacity(effective_stock_open + effective_crypto_open)
        stock_capacity_limit = max(
            int(self.max_stocks),
            int(adaptive_capacity.get("adaptive_capacity_limit", self.max_stocks))
            if adaptive_capacity.get("adaptive_capacity_policy_active")
            else int(self.max_stocks),
        )
        stock_capacity = max(0, stock_capacity_limit - effective_stock_open)
        crypto_capacity = max(0, int(self.max_crypto) - effective_crypto_open)
        total_capacity = int(adaptive_capacity.get("safe_paper_entry_slots_available", 0))
        current_runtime_max_new = int(self.max_new_positions_per_cycle)
        simulated_max_new = max(1, int(getattr(self, "configured_max_new_positions_per_cycle", current_runtime_max_new) or current_runtime_max_new or 1))

        selected_symbols: list[str] = []
        selected_details: list[dict[str, Any]] = []
        rejected_summary: list[dict[str, Any]] = []
        decision_rows: list[dict[str, Any]] = []
        blockers: dict[str, int] = {}
        eligible = 0
        selected = 0
        would_attempt = 0
        would_submit = 0
        would_reject = 0
        limit = max(1, min(60, int(max_candidates or 30)))
        for row in candidates[:limit]:
            trace, allowed, reason, gate_meta = self._candidate_trace_row(
                row,
                open_syms=open_syms,
                stock_capacity=stock_capacity,
                crypto_capacity=crypto_capacity,
                total_capacity=total_capacity,
                selected_so_far=selected,
                internal_open_syms=internal_open_syms,
                broker_open_syms=broker_open_syms,
                broker_reconciliation_active=broker_reconciliation_active,
                max_new_positions_per_cycle=simulated_max_new,
            )
            trace.update({
                "dry_run_only": True,
                "market_session_mode": "regular_market",
                "market_calendar_session_type": "regular_market",
                "market_is_open": True,
                "market_is_tradable": True,
                "session_tradable": True,
                "paper_order_submission_allowed": True,
                "execution_confirmation_required": False,
                "open_confirmation_score": 92.0,
                "open_confirmation_label": "confirmed_execute",
                "open_confirmation_reason": "dry_run_regular_market_simulation",
            })
            if not allowed and self.profit_seeking_exploration_suite is not None and hasattr(self.profit_seeking_exploration_suite, "evaluate_candidate"):
                try:
                    exploration = dict(
                        self.profit_seeking_exploration_suite.evaluate_candidate(
                            row,
                            trace=trace,
                            session_status=simulated_session,
                            market_context=simulated_session,
                            safety=safety,
                            selected_this_cycle=selected,
                            normal_eligible_count=eligible,
                            portfolio_status={},
                        )
                        or {}
                    )
                    trace.update(exploration)
                    if exploration.get("controlled_exploration_allowed"):
                        allowed = True
                        reason = "controlled_profit_seeking_exploration"
                        gate_meta = dict(gate_meta or {})
                        gate_meta["controlled_exploration_ok"] = True
                except Exception as exc:
                    trace["exploration_rejection_reason"] = f"exploration_eval_exception:{str(exc)[:80]}"

            if not allowed:
                blockers[str(reason or trace.get("decision_reason") or "not_eligible")] = blockers.get(str(reason or "not_eligible"), 0) + 1
                trace["selected"] = False
                trace["order_attempted"] = False
                decision_rows.append(trace)
                rejected_summary.append({
                    "symbol": trace.get("symbol"),
                    "reason": str(reason or trace.get("decision_reason") or "not_eligible"),
                    "source": trace.get("paper_autopilot_candidate_source"),
                })
                continue

            eligible += 1
            asset = _norm_asset(row.get("asset_type") or "stock")
            symbol = str(row.get("symbol") or trace.get("symbol") or "").upper().strip()
            capacity_ok = bool(total_capacity > 0 and selected < simulated_max_new)
            if asset == "stock" and stock_capacity <= 0:
                capacity_ok = False
                reason = "stock_capacity_reached"
            if asset == "crypto" and crypto_capacity <= 0:
                capacity_ok = False
                reason = "crypto_capacity_reached"
            if not capacity_ok:
                blockers[str(reason or "paper_capacity_limit_reached")] = blockers.get(str(reason or "paper_capacity_limit_reached"), 0) + 1
                trace["selected"] = False
                trace["order_attempted"] = False
                decision_rows.append(trace)
                continue

            selected += 1
            would_attempt += 1
            trace["selected"] = True
            trace["order_attempted"] = True
            trace["dry_run_order_attempted"] = True
            risk_label_raw = str(row.get("portfolio_risk_label") or "").strip()
            risk_score_raw = row.get("portfolio_risk_score")
            risk_score = _to_float(risk_score_raw, 0.0) if risk_score_raw is not None else None
            explicit_ok = row.get("portfolio_risk_ok")
            risk_proof_present = bool(explicit_ok is not None or risk_score is not None or risk_label_raw)
            if explicit_ok is not None:
                portfolio_ok = bool(explicit_ok)
                preflight_reason = "explicit_portfolio_risk_ok"
            elif risk_score is not None:
                portfolio_ok = bool(risk_label_raw.lower() not in {"high_risk", "blocked"} and risk_score >= 35.0)
                preflight_reason = "derived_from_portfolio_risk_fields"
            else:
                portfolio_ok = False
                preflight_reason = "missing_portfolio_risk_data"
            submit_ready = bool(
                safety.get("broker_execution_enabled")
                and safety.get("paper_mode_verified")
                and asset == "stock"
                and symbol
                and risk_proof_present
                and portfolio_ok
            )
            trace.update({
                "portfolio_risk_proof_present": bool(risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": "dry_run_max_new_max_open_and_capacity_passed",
                "broker_submit_function_called": False,
                "real_order_submitted": False,
                "would_submit_order": bool(submit_ready),
            })
            if submit_ready:
                would_submit += 1
                selected_symbols.append(symbol)
                selected_details.append({
                    "symbol": symbol,
                    "source": trace.get("paper_autopilot_candidate_source"),
                    "cap_tier": trace.get("selected_cap_tier"),
                    "sector": trace.get("selected_sector"),
                    "opportunity_type": trace.get("selected_opportunity_type"),
                    "commitment_score": trace.get("commitment_score"),
                    "portfolio_risk_score": trace.get("portfolio_risk_score_used"),
                    "portfolio_risk_label": trace.get("portfolio_risk_label_used"),
                    "expected_return_percent": row.get("expected_return_percent") or row.get("predicted_profit_percent"),
                })
                open_syms.add(symbol)
                total_capacity = max(0, total_capacity - 1)
                if asset == "stock":
                    stock_capacity = max(0, stock_capacity - 1)
                else:
                    crypto_capacity = max(0, crypto_capacity - 1)
            else:
                would_reject += 1
                reject_reason = "broker_not_ready"
                if asset != "stock":
                    reject_reason = "alpaca_crypto_execution_deferred"
                elif not risk_proof_present:
                    reject_reason = "missing_portfolio_risk_data"
                elif not portfolio_ok:
                    reject_reason = "portfolio_risk_preflight_failed"
                blockers[reject_reason] = blockers.get(reject_reason, 0) + 1
                trace["dry_run_rejection_reason"] = reject_reason
            decision_rows.append(trace)

        final = "dry_run_would_submit_orders" if would_submit > 0 else "dry_run_no_orders_would_submit"
        if not candidates:
            final = "candidate_source_empty"
            blockers[final] = blockers.get(final, 0) + 1
        elif eligible <= 0:
            final = "no_eligible_candidates"
        elif selected <= 0:
            final = "no_selected_candidates"
        elif would_attempt <= 0:
            final = "no_orders_would_be_attempted"
        elif would_submit <= 0 and blockers:
            final = max(blockers.items(), key=lambda kv: kv[1])[0]

        return {
            "enabled": True,
            "version": "1.0.0",
            "dry_run_only": True,
            "simulate_market_open": True,
            "simulated_session_type": "regular_market",
            "simulated_broker_order_submission_allowed": True,
            "real_orders_submitted": 0,
            "broker_submit_function_called": False,
            "broad_universe_pipeline_active": bool(broad_status.get("broad_universe_pipeline_active", False)),
            "broad_universe_size": int(_to_float(broad_status.get("broad_universe_size"), 0.0)),
            "tradable_universe_size": int(_to_float(broad_status.get("tradable_universe_size"), 0.0)),
            "candidates_detected": int(_to_float(broad_status.get("candidates_detected"), 0.0)),
            "shortlist_count": int(_to_float(broad_status.get("shortlist_count"), 0.0)),
            "deep_scored_count": int(_to_float(broad_status.get("deep_scored_count"), 0.0)),
            "promoted_to_top_buys_count": int(_to_float(broad_status.get("promoted_to_top_buys_count"), 0.0)),
            "top_buys_rows_count": int(len(candidates)),
            "current_runtime_max_new_positions_per_cycle": int(current_runtime_max_new),
            "simulated_max_new_positions_per_cycle": int(simulated_max_new),
            "paper_autopilot_candidate_source": (
                "broad_universe_promoted_top_buys"
                if any(bool((r or {}).get("selected_from_broad_universe", False)) for r in candidates)
                else "top_buys"
            ),
            "candidates_seen": int(len(candidates)),
            "eligible_candidates": int(eligible),
            "selected_candidates": int(selected),
            "would_attempt_orders": int(would_attempt),
            "would_submit_orders": int(would_submit),
            "would_reject_orders": int(would_reject),
            "final_blocker_reason": str(final)[:180],
            "blocker_breakdown": dict(sorted(blockers.items(), key=lambda kv: kv[1], reverse=True)),
            "selected_symbols": list(selected_symbols),
            "selected_symbol_details": list(selected_details),
            "rejected_candidate_summary": list(rejected_summary[:20]),
            "per_candidate_decision_trace": list(decision_rows[:limit]),
            "market_session_block_bypassed_for_simulation_only": True,
            "actual_market_session_type": str(actual_session.get("current_session_type") or actual_session.get("market_session_mode") or ""),
            "actual_broker_order_submission_allowed": bool(actual_session.get("broker_order_submission_allowed", actual_session.get("paper_order_submission_allowed", False))),
            "fmp_budget_state": str(broad_status.get("fmp_budget_state") or ""),
            "capacity_source": str(adaptive_capacity.get("capacity_source") or capacity_source),
            "adaptive_learning_capacity_policy": dict(adaptive_capacity),
            "adaptive_capacity_used_by_scanner": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
            "adaptive_capacity_used_by_candidate_filter": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
            "adaptive_capacity_used_by_entry_gate": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
            "adaptive_capacity_used_by_paper_trade_creation": bool(adaptive_capacity.get("adaptive_capacity_policy_active")),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "deterministic_execution_authority_preserved": True,
            "broker_behavior_changed": False,
        }

    def paper_positions(self):
        open_rows = self._fetch_open_positions()
        out: list[dict[str, Any]] = []
        for row in open_rows:
            item = dict(row)
            item["entry_metadata"] = _safe_json_load(row.get("row_json"))
            item["lifecycle_notes"] = _safe_json_load(row.get("lifecycle_notes"))
            out.append(item)
        return out
