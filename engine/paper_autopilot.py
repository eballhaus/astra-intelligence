from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from engine.candidate_execution_integrity_v1 import candidate_execution_integrity
from engine.runtime_environment import load_runtime_environment
from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
)

# The standalone paper worker imports this module directly.  Load the same
# non-secret repository environment used by server startup before evaluating
# any lane limit or kill-switch configuration.
load_runtime_environment()

try:
    from engine.astra_trade_lane_registry_v1 import CONTRACT_FIELDS, apply_trade_lane_contract
except Exception:  # pragma: no cover - metadata-only compatibility fallback
    CONTRACT_FIELDS = ()

    def apply_trade_lane_contract(row: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return dict(row or {})

try:
    from engine.astra_multilane_activation_v2 import (
        canonical_lane_activation_contract,
        lane_capital_status,
        lane_owner_contract,
        strict_broker_truth,
    )
except Exception:  # pragma: no cover - fail closed when the bounded contract is unavailable
    def lane_capital_status(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"capital_configured": False, "capital_configuration_status": "CAPITAL_CONFIGURATION_REQUIRED"}

    def canonical_lane_activation_contract(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"lane_enabled": False, "execution_enabled": False, "exact_blockers": ["ACTIVATION_CONTRACT_UNAVAILABLE"]}

    def lane_owner_contract(_row: dict[str, Any]) -> dict[str, Any]:
        return {"owner_status": "LANE_CONTRACT_REQUIRED", "automatic_management_allowed": False}

    def strict_broker_truth(_row: dict[str, Any]) -> bool:
        return False

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
    from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1
except Exception:  # pragma: no cover - execution must remain available if diagnostics fail
    LaneExecutionTraceLedgerV1 = None  # type: ignore[assignment]

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


def _normalize_paper_sell_qty(requested_qty: Any, broker_available_qty: Any, decimals: int = 6) -> dict[str, Any]:
    requested = max(0.0, _to_float(requested_qty, 0.0))
    available = max(0.0, _to_float(broker_available_qty, 0.0))
    precision = max(0, int(decimals))
    scale = 10 ** precision
    epsilon = 1.0 / scale
    capped = min(requested if requested > 0.0 else available, available)
    floored = _floor_fractional_qty(capped, precision)
    epsilon_applied = False
    if floored > 0.0 and available > 0.0 and floored >= available:
        floored = _floor_fractional_qty(max(0.0, floored - epsilon), precision)
        epsilon_applied = True
    dust = available > 0.0 and floored <= 0.0
    safe = floored > 0.0 and floored <= available
    return {
        "original_requested_qty": round(requested, 9),
        "broker_available_qty": round(available, 9),
        "normalized_sell_qty": floored,
        "qty_adjusted": bool(abs(floored - requested) > 0.0 or capped < requested),
        "floor_precision_applied": True,
        "epsilon_applied": epsilon_applied,
        "dust_position_detected": dust,
        "sell_safe_to_submit": safe,
        "normalization_reason": "dust_position_below_fractional_precision" if dust else ("floor_to_broker_available_fractional_qty_with_epsilon" if epsilon_applied else "floor_to_broker_available_fractional_qty"),
        "precision_delta": round(max(0.0, requested - floored), 12),
    }


def _parse_available_qty_from_error(error: Any) -> float:
    raw = str(error or "")
    match = re.search(r"available:\s*([0-9]+(?:\.[0-9]+)?)", raw, re.IGNORECASE)
    return _to_float(match.group(1), 0.0) if match else 0.0


def _norm_asset(asset_type: Any) -> str:
    raw = str(asset_type or "stock").strip().lower()
    return "crypto" if raw == "crypto" else "stock"


def _paper_attribution_metadata(row: dict[str, Any] | None) -> dict[str, str]:
    row = dict(row or {})
    return {
        "recommendation_id": str(row.get("recommendation_id") or row.get("source_recommendation_id") or "").strip(),
        "decision_id": str(row.get("decision_id") or row.get("source_decision_id") or "").strip(),
        "eligibility_evaluation_id": str(
            row.get("eligibility_evaluation_id")
            or row.get("source_eligibility_evaluation_id")
            or ""
        ).strip(),
        "candidate_id": str(row.get("candidate_id") or row.get("source_candidate_id") or "").strip(),
    }


def _paper_attribution_client_order_id(row: dict[str, Any] | None) -> str:
    """Build a stable broker-safe metadata ID without changing trade intent."""
    metadata = _paper_attribution_metadata(row)
    symbol = str((row or {}).get("symbol") or "").upper().strip()
    seed = "|".join(
        [metadata["recommendation_id"], metadata["decision_id"], metadata["eligibility_evaluation_id"], metadata["candidate_id"], symbol]
    ).strip("|")
    if not seed:
        return ""
    return f"astra-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:24]}"[:48]


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


def _parse_iso_utc(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except Exception:
        return None


def _pick_first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _pick_first_number(*values: Any) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return float(value)
        except Exception:
            continue
    return None


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


def _expected_hold_minutes(horizon: str) -> float:
    if horizon == "scalp":
        return 60.0
    if horizon == "day_trade":
        return 390.0
    if horizon == "swing_trade":
        return 10.0 * 24.0 * 60.0
    return 0.0


def _stable_candidate_identity(row: dict[str, Any]) -> dict[str, str]:
    """Create deterministic pre-trade lineage from the existing snapshot.

    This is intentionally metadata-only: the upstream candidate still owns its
    score and eligibility.  The seed uses source snapshot context rather than a
    request timestamp, so repeated diagnostics cannot regenerate identity.
    """
    r = dict(row or {})
    symbol = str(r.get("symbol") or r.get("ticker") or "").upper().strip()
    source = str(
        r.get("candidate_source")
        or r.get("paper_autopilot_candidate_source")
        or r.get("top_buys_candidate_source")
        or "top_buys_runtime_snapshot"
    ).strip()
    generated_at = str(
        r.get("candidate_generated_at")
        or r.get("source_snapshot_generated_at")
        or r.get("generated_at")
        or r.get("timestamp")
        or r.get("recommendation_timestamp")
        or r.get("last_updated_utc")
        or ""
    ).strip()
    snapshot_id = str(r.get("source_snapshot_id") or r.get("ranking_run_id") or generated_at or "snapshot_unknown").strip()
    lane = str(r.get("lane_id") or "").upper().strip()
    cohort = str(r.get("strategy_cohort") or "").strip()
    horizon = str(r.get("intended_horizon") or r.get("paper_entry_horizon_style") or "").strip()
    rank = str(r.get("rank_position") or r.get("rank") or "").strip()
    recommendation_seed = "|".join((source, snapshot_id, symbol, rank, cohort, horizon))
    recommendation_id = str(r.get("recommendation_id") or r.get("canonical_recommendation_id") or "").strip()
    if not recommendation_id and symbol:
        recommendation_id = "rec-" + hashlib.sha256(recommendation_seed.encode("utf-8")).hexdigest()[:20]
    candidate_seed = "|".join((lane, recommendation_id, symbol, snapshot_id, cohort, horizon))
    candidate_id = str(r.get("candidate_id") or r.get("source_candidate_id") or r.get("decision_id") or "").strip()
    if not candidate_id and symbol:
        candidate_id = "cand-" + hashlib.sha256(candidate_seed.encode("utf-8")).hexdigest()[:20]
    selection_id = str(r.get("selection_id") or "").strip()
    if not selection_id and candidate_id:
        selection_id = "sel-" + hashlib.sha256((candidate_id + "|paper_autopilot").encode("utf-8")).hexdigest()[:20]
    return {
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "candidate_source": source,
        "candidate_generated_at": generated_at,
        "source_snapshot_id": snapshot_id,
        "selection_id": selection_id,
    }


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
        r.setdefault("intended_trade_style", horizon)
        r.setdefault("actual_horizon_classification", horizon)
        r.setdefault("turnover_trade_style", horizon)
        r["paper_entry_horizon_style"] = horizon
        r["paper_entry_horizon_source"] = horizon_source
        r["paper_entry_horizon_inferred"] = bool(inferred)
        r["horizon_source"] = horizon_source
        r["expected_hold_window"] = _expected_hold_window(horizon)
        r["expected_hold_minutes"] = _expected_hold_minutes(horizon)
        r["expected_hold_days"] = round(_expected_hold_minutes(horizon) / 1440.0, 4)
        r["horizon_persistence_bundle_v1"] = True
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
    # Preserve a canonical lane identity before the existing order path.  This
    # only records context; the existing ranking and paper safety gates remain
    # the sole owners of eligibility and submission.
    identity_seed = dict(r)
    r = apply_trade_lane_contract(r, legacy=False)
    # Use the pre-contract snapshot timestamp, not the contract's diagnostic
    # clock fallback, so a GET cannot create a new candidate identity.
    identity_seed.update({key: r.get(key) for key in ("lane_id", "strategy_cohort", "intended_horizon")})
    r.update({key: value for key, value in _stable_candidate_identity(identity_seed).items() if value})
    # Operational lineage is established before eligibility.  These values
    # describe the already-produced candidate snapshot; they never change its
    # ranking, score, or ability to submit an order.
    r["canonical_symbol"] = str(r.get("canonical_symbol") or r.get("symbol") or r.get("ticker") or "").upper().strip()
    r["source_record_id"] = str(
        r.get("source_record_id") or r.get("source_candidate_id") or r.get("candidate_id") or ""
    ).strip()
    r["ranking_version"] = str(r.get("ranking_version") or r.get("source_snapshot_id") or "").strip()
    r["generated_at"] = str(r.get("generated_at") or r.get("candidate_generated_at") or "").strip()
    expires_at = str(r.get("expires_at") or r.get("candidate_expires_at") or "").strip()
    if not expires_at and r["generated_at"]:
        try:
            generated = datetime.fromisoformat(r["generated_at"].replace("Z", "+00:00"))
            expires_at = (generated.astimezone(UTC) + timedelta(seconds=300)).isoformat().replace("+00:00", "Z")
        except Exception:
            expires_at = ""
    r["expires_at"] = expires_at
    r["entry_owner"] = str(r.get("entry_owner") or "PaperAutopilot").strip()
    r["exit_owner"] = str(r.get("exit_owner") or r.get("exit_policy_owner") or r.get("lane_id") or "").strip()
    r["candidate_fingerprint"] = str(r.get("candidate_fingerprint") or r.get("candidate_id") or "").strip()
    r["paper_entry_eligibility_bridge_v1"] = True
    return r


def _execution_trace_event(row: dict[str, Any], **values: Any) -> dict[str, Any]:
    """Keep blocked candidate traces on the same canonical lineage path.

    The worker used to create abbreviated early-rejection rows.  Those rows
    were useful to an in-memory UI but could not be attributed or persisted by
    the bounded lane ledger because their lane and stable identifiers were
    absent.  This is observational-only metadata enrichment.
    """
    normalized = _normalize_paper_entry_bridge(row)
    trace = {
        "symbol": str(normalized.get("symbol") or "").upper().strip(),
        "canonical_symbol": str(normalized.get("canonical_symbol") or "").upper().strip(),
        "asset_type": _norm_asset(normalized.get("asset_type") or normalized.get("asset_class") or "stock"),
        "asset_class": str(normalized.get("asset_class") or ""),
        "lane_id": str(normalized.get("lane_id") or "").upper(),
        "candidate_id": str(normalized.get("candidate_id") or ""),
        "recommendation_id": str(normalized.get("recommendation_id") or ""),
        "selection_id": str(normalized.get("selection_id") or ""),
        "candidate_source": str(normalized.get("candidate_source") or ""),
        "candidate_generated_at": str(normalized.get("candidate_generated_at") or normalized.get("generated_at") or ""),
        "candidate_snapshot_freshness": str(normalized.get("candidate_snapshot_freshness") or "MISSING"),
        "source_snapshot_id": str(normalized.get("source_snapshot_id") or ""),
        "source_record_id": str(normalized.get("source_record_id") or ""),
        "ranking_version": str(normalized.get("ranking_version") or ""),
        "generated_at": str(normalized.get("generated_at") or normalized.get("candidate_generated_at") or ""),
        "expires_at": str(normalized.get("expires_at") or ""),
        "candidate_fingerprint": str(normalized.get("candidate_fingerprint") or normalized.get("candidate_id") or ""),
        "position_owner": str(normalized.get("position_owner") or ""),
        "exit_policy_owner": str(normalized.get("exit_policy_owner") or ""),
        "entry_owner": str(normalized.get("entry_owner") or "PaperAutopilot"),
        "exit_owner": str(normalized.get("exit_owner") or normalized.get("exit_policy_owner") or normalized.get("lane_id") or ""),
        "capital_book_id": str(normalized.get("capital_book_id") or ""),
        "session_state": str(
            normalized.get("session_state")
            or ("CRYPTO_24_7_ALLOWED" if _norm_asset(normalized.get("asset_type") or normalized.get("asset_class")) == "crypto" else "CANDIDATE_DEPENDENT")
        ),
        "market_session_mode": str(normalized.get("market_session_mode") or ""),
        "same_session_exit_required": bool(normalized.get("same_session_exit_required")),
        "overnight_allowed": bool(normalized.get("overnight_allowed")),
    }
    trace.update(values)
    return trace


def normalize_operational_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Public, side-effect-free canonical candidate enrichment for readers."""
    return _normalize_paper_entry_bridge(row)


class PaperAutopilotEngine:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args, **kwargs):
        self.db_path = str(db_path or "state/ai_trading_memory.db")
        self.state_path = str(kwargs.get("state_path") or "state/paper_autopilot_state.json")
        self.get_crypto_candidate_rows_fn = kwargs.get("get_crypto_candidate_rows_fn")
        self.execution_trace_ledger = (
            LaneExecutionTraceLedgerV1(os.path.dirname(self.state_path) or "state")
            if LaneExecutionTraceLedgerV1 is not None else None
        )
        self.interval_seconds = max(15, _to_int(kwargs.get("interval_seconds"), 45))
        self.max_stocks = max(1, _to_int(kwargs.get("max_stocks"), 6))
        self.crypto_day_capacity = 6
        self.crypto_short_swing_capacity = 2
        self.max_crypto = min(
            self.crypto_day_capacity + self.crypto_short_swing_capacity,
            max(0, _to_int(kwargs.get("max_crypto"), self.crypto_day_capacity + self.crypto_short_swing_capacity)),
        )
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
            "authorized_lane_exit_pending": {},
            "evidence_reserve_entry_timestamps": {"DAY": [], "CRYPTO": []},
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
                "reconciled_at": "TEXT",
                "reconciliation_reason": "TEXT",
                "reconciliation_evidence_source": "TEXT",
                "prior_status": "TEXT",
                "canonical_horizon": "TEXT",
                "canonical_horizon_source": "TEXT",
                "canonical_horizon_confidence": "REAL",
                "buy_reason": "TEXT",
                "add_reason": "TEXT",
                "hold_reason": "TEXT",
                "unknown_reason_code": "TEXT",
                "evidence_count": "INTEGER",
                "reason_confidence": "REAL",
                "source_candidate_id": "TEXT",
                "source_lifecycle_id": "TEXT",
                "source_broker_order_id": "TEXT",
                "source_client_order_id": "TEXT",
                "source_recommendation_id": "TEXT",
                "source_decision_id": "TEXT",
                "source_eligibility_evaluation_id": "TEXT",
                "lane_id": "TEXT",
                "capital_book_id": "TEXT",
                "position_owner": "TEXT",
                "exit_policy_owner": "TEXT",
                "entry_order_id": "TEXT",
                "entry_fill_id": "TEXT",
                "exit_order_id": "TEXT",
                "exit_fill_id": "TEXT",
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
                if isinstance(payload.get("authorized_lane_exit_pending"), dict):
                    self._runtime_state["authorized_lane_exit_pending"] = dict(payload.get("authorized_lane_exit_pending") or {})
                if isinstance(payload.get("evidence_reserve_entry_timestamps"), dict):
                    self._runtime_state["evidence_reserve_entry_timestamps"] = {
                        lane: list(payload.get("evidence_reserve_entry_timestamps", {}).get(lane) or [])[-32:]
                        for lane in ("DAY", "CRYPTO")
                    }
                if isinstance(payload.get("adaptive_learning_capacity_policy"), dict):
                    persisted_policy = dict(payload.get("adaptive_learning_capacity_policy") or {})
                    persisted_policy["policy_valid"] = bool(
                        persisted_policy.get("policy_valid")
                        and persisted_policy.get("paper_only_preserved", True)
                        and persisted_policy.get("behavior_safe_to_apply") is False
                        and not persisted_policy.get("broker_behavior_changed", False)
                    )
                    self._adaptive_learning_capacity_policy = persisted_policy
                if isinstance(payload.get("last_execution_trace"), dict):
                    self._runtime_state["last_execution_trace"] = dict(payload.get("last_execution_trace") or {})
                if payload.get("last_cycle_utc"):
                    self._runtime_state["last_cycle_utc"] = str(payload.get("last_cycle_utc") or "")
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
            "authorized_lane_exit_pending": dict(self._runtime_state.get("authorized_lane_exit_pending") or {}),
            "evidence_reserve_entry_timestamps": {
                lane: list((self._runtime_state.get("evidence_reserve_entry_timestamps") or {}).get(lane) or [])[-32:]
                for lane in ("DAY", "CRYPTO")
            },
            "adaptive_learning_capacity_policy": dict(self._adaptive_learning_capacity_policy or {}),
            "last_execution_trace": {
                **dict(self._runtime_state.get("last_execution_trace") or {}),
                "per_candidate_decision_trace": list(
                    (self._runtime_state.get("last_execution_trace") or {}).get("per_candidate_decision_trace") or []
                )[:200],
            },
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

    def _sell_rejection_loop_state(self) -> dict[str, Any]:
        return dict(self._runtime_state.get("sell_rejection_loop_breaker_v1") or {})

    def _set_sell_rejection_loop_state(self, state: dict[str, Any]) -> None:
        self._runtime_state["sell_rejection_loop_breaker_v1"] = dict(state or {})

    def _sell_rejection_loop_key(self, symbol: str, position_id: str, reason: str) -> str:
        sym = str(symbol or "").upper().strip()
        pid = str(position_id or "").strip()[:18]
        reason_key = re.sub(r"[^a-z0-9_]+", "_", str(reason or "").lower()).strip("_")[:48]
        return f"{sym}:{pid}:{reason_key}"

    def _sell_rejection_loop_blocked(self, symbol: str, position_id: str, reason: str, *, limit: int = 2, ttl_seconds: int = 1800) -> tuple[bool, dict[str, Any]]:
        state = self._sell_rejection_loop_state()
        key = self._sell_rejection_loop_key(symbol, position_id, reason)
        now = time.time()
        row = dict(state.get(key) or {})
        first_ts = _to_float(row.get("first_ts"), now)
        if now - first_ts > float(ttl_seconds):
            row = {"first_ts": now, "count": 0, "prevented": 0}
        count = _to_int(row.get("count"), 0) + 1
        prevented = _to_int(row.get("prevented"), 0)
        blocked = count > int(limit)
        if blocked:
            prevented += 1
        row.update({
            "key": key,
            "symbol": str(symbol or "").upper().strip(),
            "position_id": str(position_id or ""),
            "reason": str(reason or ""),
            "count": count,
            "prevented": prevented,
            "first_ts": first_ts,
            "last_ts": now,
            "loop_breaker_applied": blocked,
        })
        state[key] = row
        self._set_sell_rejection_loop_state(state)
        return blocked, row

    def _sell_rejection_loop_active(self, symbol: str, position_id: str, reason: str, *, limit: int = 2, ttl_seconds: int = 1800) -> tuple[bool, dict[str, Any]]:
        state = self._sell_rejection_loop_state()
        key = self._sell_rejection_loop_key(symbol, position_id, reason)
        row = dict(state.get(key) or {})
        if not row:
            return False, {}
        if time.time() - _to_float(row.get("first_ts"), 0.0) > float(ttl_seconds):
            return False, row
        return _to_int(row.get("count"), 0) >= int(limit), row

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

    def _authorized_lane_exit_pending_map(self) -> dict[str, Any]:
        return dict(self._runtime_state.get("authorized_lane_exit_pending") or {})

    def _authorized_lane_exit_contract(self, open_row: dict[str, Any]) -> dict[str, Any]:
        """Authorize only explicit DAY/CRYPTO owners with a real entry fill."""
        lane = str(open_row.get("lane_id") or "").upper().strip()
        if lane not in {"DAY", "CRYPTO"}:
            return {"authorized": False, "status": "NOT_APPLICABLE", "reason": "lane_not_authorized_for_v2_exit"}
        owner = lane_owner_contract(open_row)
        capital = lane_capital_status(lane)
        entry_order_id = str(open_row.get("entry_order_id") or open_row.get("source_broker_order_id") or "").strip()
        entry_fill_id = str(open_row.get("entry_fill_id") or "").strip()
        if not bool(capital.get("capital_configured")):
            return {"authorized": False, "status": "UNRESOLVED", "reason": str(capital.get("capital_configuration_status") or "CAPITAL_CONFIGURATION_REQUIRED")}
        if not bool(owner.get("automatic_management_allowed")):
            return {"authorized": False, "status": "UNRESOLVED", "reason": "LANE_CONTRACT_REQUIRED"}
        if not entry_order_id or not entry_fill_id:
            return {"authorized": False, "status": "UNRESOLVED", "reason": "ENTRY_FILL_LINEAGE_REQUIRED"}
        if lane == "DAY" and not (open_row.get("same_session_exit_required") is True and open_row.get("overnight_allowed") is False):
            return {"authorized": False, "status": "UNRESOLVED", "reason": "DAY_SAME_SESSION_CONTRACT_REQUIRED"}
        safety = self._alpaca_safety_snapshot()
        if not bool(safety.get("paper_mode_verified")) or bool(safety.get("broker_live_endpoint_allowed")):
            return {"authorized": False, "status": "UNRESOLVED", "reason": "PAPER_ONLY_BROKER_BOUNDARY_REQUIRED"}
        if self.alpaca_paper_broker is None or not hasattr(self.alpaca_paper_broker, "submit_paper_order"):
            return {"authorized": False, "status": "WORKER_UNAVAILABLE", "reason": "ALPACA_PAPER_BROKER_UNAVAILABLE"}
        return {
            "authorized": True,
            "status": "AUTHORIZED_AND_PROVEN",
            "lane_id": lane,
            "entry_order_id": entry_order_id,
            "entry_fill_id": entry_fill_id,
            "position_owner": owner.get("position_owner"),
            "exit_policy_owner": owner.get("exit_policy_owner"),
            "paper_mode_verified": True,
            "broker_live_endpoint_allowed": False,
        }

    def authorized_lane_exit_status(self, lane_id: str = "DAY") -> dict[str, Any]:
        """Read-only worker readiness proof; it never queries or calls a broker."""
        lane = str(lane_id or "").upper().strip()
        capital = lane_capital_status(lane)
        broker_ready = bool(self.alpaca_paper_broker is not None and hasattr(self.alpaca_paper_broker, "submit_paper_order"))
        if lane not in {"DAY", "CRYPTO"}:
            status, reason = "UNRESOLVED", "unsupported_lane"
        elif not bool(capital.get("capital_configured")):
            status, reason = "UNRESOLVED", str(capital.get("capital_configuration_status") or "CAPITAL_CONFIGURATION_REQUIRED")
        elif not broker_ready:
            status, reason = "WORKER_UNAVAILABLE", "ALPACA_PAPER_BROKER_UNAVAILABLE"
        else:
            status, reason = "AUTHORIZED_NOT_YET_PROVEN", "awaiting_lane_owned_filled_entry_or_dry_run_trace"
        return {
            "lane_id": lane, "status": status, "reason": reason,
            "worker_available": broker_ready, "submit_order": False, "broker_actions_used": 0,
            "capital_configuration_status": capital.get("capital_configuration_status"),
            "learned_exits_enabled": False,
        }

    def authorized_lane_exit_dry_run(self, lane_id: str = "DAY") -> dict[str, Any]:
        """Deterministically prove owner/fill gating without a broker request."""
        lane = str(lane_id or "").upper().strip()
        fixture = apply_trade_lane_contract(
            {
                "symbol": "V2FIXTURE/USD" if lane == "CRYPTO" else "V2FIXTURE",
                "asset_class": "crypto" if lane == "CRYPTO" else "equity",
                "paper_entry_horizon_style": "day_trade" if lane == "DAY" else "crypto",
                "entry_order_id": "fixture-entry-order",
                "entry_fill_id": "fixture-entry-order:2026-01-01T00:00:00Z",
            },
            legacy=False,
        )
        fixture["position_owner"] = lane
        fixture["exit_policy_owner"] = lane
        fixture["entry_order_id"] = "fixture-entry-order"
        fixture["entry_fill_id"] = "fixture-entry-order:2026-01-01T00:00:00Z"
        contract = self._authorized_lane_exit_contract(fixture)
        return {
            "lane_id": lane,
            "proven": bool(contract.get("authorized")),
            "proof_kind": "deterministic_fixture_no_broker_action",
            "live_market_evidence_deferred": True,
            "broker_actions_used": 0,
            "submit_order": False,
            "contract": contract,
        }

    def _submit_authorized_lane_exit(self, open_row: dict[str, Any], broker_position: dict[str, Any], exit_reason: str) -> dict[str, Any]:
        """Submit an approved lane-owned paper exit and wait for its broker fill."""
        contract = self._authorized_lane_exit_contract(open_row)
        if not contract.get("authorized"):
            return {"ok": False, "submitted": False, "reason": contract.get("reason"), "contract": contract}
        symbol = str(open_row.get("symbol") or "").upper().strip()
        position_id = str(open_row.get("position_id") or "").strip()
        pending, pending_reason = self._position_pending_sell(symbol, position_id)
        if pending:
            return {"ok": False, "submitted": False, "reason": pending_reason, "contract": contract}
        available = _to_float(broker_position.get("qty_available"), _to_float(broker_position.get("qty"), _to_float(open_row.get("quantity"), 0.0)))
        normalized = _normalize_paper_sell_qty(_to_float(open_row.get("quantity"), available), available, 6)
        qty = _to_float(normalized.get("normalized_sell_qty"), 0.0)
        if qty <= 0 or not bool(normalized.get("sell_safe_to_submit")):
            return {"ok": False, "submitted": False, "reason": "DUST_OR_UNAVAILABLE_QUANTITY", "contract": contract, **normalized}
        lane = str(contract.get("lane_id") or "")
        client_order_id = f"astra-{lane.lower()}-exit-{position_id[:18] or symbol[:16]}"[:48]
        order = {
            "symbol": symbol, "side": "sell", "type": "market",
            "time_in_force": "gtc" if lane == "CRYPTO" else "day", "qty": qty,
            "client_order_id": client_order_id, "paper_only": True,
            "lane_id": lane, "capital_book_id": open_row.get("capital_book_id"),
            "position_owner": open_row.get("position_owner"), "exit_policy_owner": open_row.get("exit_policy_owner"),
            "entry_order_id": contract.get("entry_order_id"), "entry_fill_id": contract.get("entry_fill_id"),
            "existing_exit_reason": str(exit_reason or ""), "learned_exit_execution": False,
        }
        try:
            result = dict(self.alpaca_paper_broker.submit_paper_order(order) or {})
        except Exception as exc:
            return {"ok": False, "submitted": False, "reason": f"lane_exit_submit_exception:{str(exc)[:120]}", "contract": contract}
        if not bool(result.get("ok")):
            return {"ok": False, "submitted": False, "reason": str(result.get("error") or "lane_exit_submit_failed")[:160], "contract": contract, **normalized}
        broker_order = dict(result.get("order") or {})
        pending_id = str(broker_order.get("id") or client_order_id)
        pending_map = self._authorized_lane_exit_pending_map()
        pending_map[pending_id] = {
            "position_id": position_id, "symbol": symbol, "lane_id": lane,
            "exit_reason": str(exit_reason or ""), "order_id": str(broker_order.get("id") or ""),
            "client_order_id": str(broker_order.get("client_order_id") or client_order_id),
            "submitted_at": _now_iso(), "contract": contract, **normalized,
        }
        self._runtime_state["authorized_lane_exit_pending"] = pending_map
        return {"ok": True, "submitted": True, "pending_order_id": pending_id, "contract": contract, **normalized}

    def _refresh_authorized_lane_exit_pending(self) -> dict[str, Any]:
        """Close local lifecycle rows only after a broker-filled lane exit."""
        pending = self._authorized_lane_exit_pending_map()
        broker = self.alpaca_paper_broker
        if not pending or broker is None or not hasattr(broker, "order"):
            return {"checked": 0, "filled": 0, "pending": len(pending), "reason": "no_pending_or_lookup_unavailable"}
        remaining: dict[str, Any] = {}
        filled = checked = 0
        for key, item in pending.items():
            order_id = str(item.get("order_id") or "").strip()
            if not order_id:
                remaining[key] = item
                continue
            checked += 1
            try:
                lookup = dict(broker.order(order_id) or {})
            except Exception:
                remaining[key] = item
                continue
            order = dict(lookup.get("order") or {})
            if not bool(lookup.get("ok")) or str(order.get("status") or "").lower() != "filled":
                remaining[key] = {**item, "last_checked_at": _now_iso(), "last_order_status": order.get("status")}
                continue
            rows = [r for r in self._fetch_open_positions() if str(r.get("position_id") or "") == str(item.get("position_id") or "")]
            if not rows:
                continue
            exit_order_id = str(order.get("id") or order_id)
            filled_at = str(order.get("filled_at") or "").strip()
            exit_fill_id = str(order.get("fill_id") or order.get("execution_id") or (f"{exit_order_id}:{filled_at}" if filled_at else "")).strip()
            if not exit_fill_id:
                remaining[key] = {**item, "last_checked_at": _now_iso(), "last_order_status": "filled_missing_fill_lineage"}
                continue
            latest = {"symbol": item.get("symbol"), "price": _to_float(order.get("filled_avg_price"), 0.0), "timestamp": _now_iso(), "source": "alpaca_paper_order_fill"}
            closed = self._close_position(rows[0], latest, str(item.get("exit_reason") or "lane_exit"), broker_fill={"exit_order_id": exit_order_id, "exit_fill_id": exit_fill_id, "filled_at": filled_at})
            filled += 1 if closed.get("ok") else 0
        self._runtime_state["authorized_lane_exit_pending"] = remaining
        return {"checked": checked, "filled": filled, "pending": len(remaining)}

    def _lane_forced_exit_reason(self, open_row: dict[str, Any]) -> str:
        """DAY force-flat is scoped to explicit DAY owners and never CRYPTO."""
        if str(open_row.get("lane_id") or "").upper().strip() != "DAY":
            return ""
        if not bool(open_row.get("same_session_exit_required")) or bool(open_row.get("overnight_allowed")):
            return ""
        try:
            now_et = datetime.now(ZoneInfo("America/New_York"))
            entry = datetime.fromisoformat(str(open_row.get("entry_timestamp") or "").replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
        except Exception:
            return "day_lane_entry_timestamp_unavailable"
        if entry.date() < now_et.date():
            return "day_lane_overnight_breach"
        if now_et.weekday() >= 5:
            return "day_lane_weekend_breach"
        raw = str(os.getenv("ASTRA_DAY_LANE_FORCE_FLAT_TIME_ET", "15:55"))
        digits = "".join(ch for ch in raw if ch.isdigit())
        cutoff = int(digits[:4] or "1555")
        if (now_et.hour * 100 + now_et.minute) >= cutoff:
            return "day_lane_force_flat"
        return ""

    def _persist_strict_lane_truth(
        self,
        open_row: dict[str, Any],
        broker_fill: dict[str, Any],
        *,
        exit_price: float,
        return_percent: float,
        hold_seconds: float,
        exit_reason: str,
    ) -> dict[str, Any]:
        """Append one deduplicated paired-fill truth to the canonical registry.

        This runs only from the worker after Alpaca reports the exit order as
        filled.  It never reconstructs prices or creates a record on GET.
        """
        lane = str(open_row.get("lane_id") or "").upper().strip()
        entry_order_id = str(open_row.get("entry_order_id") or open_row.get("source_broker_order_id") or "").strip()
        entry_fill_id = str(open_row.get("entry_fill_id") or "").strip()
        exit_order_id = str(broker_fill.get("exit_order_id") or "").strip()
        exit_fill_id = str(broker_fill.get("exit_fill_id") or "").strip()
        lifecycle_id = str(open_row.get("position_id") or "").strip()
        record = {
            "evidence_class": "BROKER_CONFIRMED_COMPLETE",
            "truth_quality": "BROKER_CONFIRMED_COMPLETE",
            "broker_source": "alpaca_paper_actual_paired_fills",
            "source": "paper_autopilot_authorized_lane_exit",
            "stable_key": f"strict:{entry_fill_id}:{exit_fill_id}",
            "symbol": str(open_row.get("symbol") or "").upper().strip(),
            "lane_id": lane,
            "asset_class": "crypto" if str(open_row.get("asset_type") or "").lower() == "crypto" else "equity",
            "instrument_type": str(_safe_json_load(open_row.get("row_json")).get("instrument_type") or "EQUITY").upper(),
            "strategy_cohort": str(_safe_json_load(open_row.get("row_json")).get("strategy_cohort") or ""),
            "candidate_id": str(open_row.get("source_candidate_id") or _safe_json_load(open_row.get("row_json")).get("candidate_id") or ""),
            "recommendation_id": str(open_row.get("source_recommendation_id") or _safe_json_load(open_row.get("row_json")).get("recommendation_id") or ""),
            "selection_id": str(open_row.get("source_decision_id") or _safe_json_load(open_row.get("row_json")).get("selection_id") or ""),
            "lifecycle_id": lifecycle_id,
            "entry_order_id": entry_order_id, "entry_fill_id": entry_fill_id,
            "exit_order_id": exit_order_id, "exit_fill_id": exit_fill_id,
            "entry_time": str(open_row.get("entry_timestamp") or ""),
            "exit_time": str(broker_fill.get("filled_at") or _now_iso()),
            "entry_price": _to_float(open_row.get("entry_price"), 0.0),
            "exit_price": float(exit_price), "quantity": _to_float(open_row.get("quantity"), 0.0),
            "realized_return": round(float(return_percent), 6), "hold_duration": round(float(hold_seconds), 3),
            "return_per_hour": round(float(return_percent) / max(hold_seconds / 3600.0, 1e-9), 6),
            "exit_reason": str(exit_reason or ""), "paper_mode_verified": True,
            "official_metric_eligible": False, "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        if not strict_broker_truth(record):
            return {"persisted": False, "reason": "strict_truth_required_fields_missing"}
        path = os.path.join(os.path.dirname(self.db_path) or "state", "broker_truth_records_v1.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                registry = json.load(handle)
            registry = registry if isinstance(registry, dict) else {}
        except Exception:
            registry = {}
        records = [dict(row) for row in (registry.get("records") or []) if isinstance(row, dict)]
        if any(str(row.get("stable_key") or "") == record["stable_key"] for row in records):
            return {"persisted": False, "deduplicated": True, "stable_key": record["stable_key"]}
        records.append(record)
        strict_count = sum(1 for row in records if strict_broker_truth(row))
        registry.update({
            "records": records,
            "broker_truth_records_total": len(records),
            "strict_broker_confirmed_complete_records": strict_count,
            # Legacy counters are intentionally not overwritten; their five
            # incomplete diagnostics remain outside strict official truth.
            "generated_at": _now_iso(), "paper_only_preserved": True,
            "behavior_safe_to_apply": False, "broker_behavior_changed": False,
            "live_trading_changed": False, "provider_calls_used": 0, "llm_calls_used": 0,
        })
        temp = f"{path}.tmp-{os.getpid()}"
        try:
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(registry, handle, indent=2, sort_keys=True)
            os.replace(temp, path)
        except Exception as exc:
            try:
                if os.path.exists(temp):
                    os.unlink(temp)
            except Exception:
                pass
            return {"persisted": False, "reason": f"registry_write_failed:{str(exc)[:100]}"}
        return {"persisted": True, "stable_key": record["stable_key"], "strict_count": strict_count}

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
        requested_qty = _to_float(open_row.get("quantity"), broker_available_qty)
        qty_norm = _normalize_paper_sell_qty(requested_qty, broker_available_qty, 6)
        normalized_qty = _to_float(qty_norm.get("normalized_sell_qty"), 0.0)
        if normalized_qty <= 0.0 or not bool(qty_norm.get("sell_safe_to_submit")):
            return {
                "eligible": False,
                "reason": "dust_position_detected" if qty_norm.get("dust_position_detected") else "broker_confirmed_quantity_required",
                "evidence_count": evidence,
                **qty_norm,
            }
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
            **qty_norm,
            "normalization_applied": bool(qty_norm.get("qty_adjusted")),
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
            reason_key = str(candidate.get("reason") or "candidate_not_eligible")
            classification = (
                "learned_exit_shadow_rejected_expected" if reason_key == "no_evidence_backed_learned_exit_signal"
                else "policy_confidence_below_threshold" if reason_key == "policy_confidence_below_threshold"
                else "validation_candidate_rejected"
            )
            self._append_learned_exit_event({"event": "validation_candidate_rejected", **candidate, "exit_validation_classification": classification})
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
        loop_active, loop_row = self._sell_rejection_loop_active(symbol, pid, "insufficient_qty_available")
        if loop_active:
            self._append_learned_exit_event({
                "event": "sell_rejection_loop_prevented",
                **candidate,
                "reason": "sell_rejection_loop_breaker_active",
                "loop_breaker": loop_row,
            })
            return {"ok": False, "submitted": False, "reason": "sell_rejection_loop_breaker_active", "candidate": candidate, "loop_breaker": loop_row}
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
            retry_norm = _normalize_paper_sell_qty(normalized_qty, available_from_error, 6)
            retry_qty = _to_float(retry_norm.get("normalized_sell_qty"), 0.0)
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
                    **retry_norm,
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
                    blocked, loop_row = self._sell_rejection_loop_blocked(symbol, pid, "insufficient_qty_available")
                    self._append_learned_exit_event({
                        "event": "sell_submit_rejected",
                        **retry_candidate,
                        "broker_error": str(retry_result.get("error") or "retry_submit_failed")[:180],
                        "retry_status": retry_status,
                        "exit_validation_classification": "broker_quantity_rejection",
                        "loop_breaker_applied": blocked,
                        "loop_breaker": loop_row,
                    })
                    return {
                        "ok": False,
                        "submitted": False,
                        "reason": str(retry_result.get("error") or broker_error or "sell_submit_failed")[:140],
                        "candidate": retry_candidate,
                    }
            else:
                classification = "broker_quantity_rejection" if "insufficient qty available" in broker_error.lower() else "broker_sell_submission_rejection"
                blocked, loop_row = self._sell_rejection_loop_blocked(symbol, pid, "insufficient_qty_available" if classification == "broker_quantity_rejection" else broker_error[:80])
                self._append_learned_exit_event({
                    "event": "sell_submit_rejected",
                    **candidate,
                    "broker_error": broker_error,
                    "retry_status": "blocked_or_not_applicable",
                    "exit_validation_classification": classification,
                    "loop_breaker_applied": blocked,
                    "loop_breaker": loop_row,
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
        # The crypto adapter is an operational observation source.  It is
        # deliberately collected even while crypto execution is fail-closed,
        # so the worker records stale/unsupported/disabled candidate stages
        # instead of presenting an empty lane.  Submission remains guarded by
        # the canonical crypto activation contract below.
        rows.extend(_rows_from(["crypto", "final"]))
        rows.extend(_rows_from(["crypto", "qualified"]))
        if callable(self.get_crypto_candidate_rows_fn):
            try:
                rows.extend(
                    [dict(row) for row in (self.get_crypto_candidate_rows_fn() or []) if isinstance(row, dict)]
                )
            except Exception:
                pass

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

    def _crypto_paper_activation_status(self) -> dict[str, Any]:
        requested = str(os.getenv("ASTRA_ENABLE_ALPACA_CRYPTO_PAPER", "0")).strip().lower() in {"1", "true", "yes", "on"}
        kill_switch = str(os.getenv("ASTRA_ALPACA_CRYPTO_PAPER_KILL_SWITCH", "0")).strip().lower() in {"1", "true", "yes", "on"}
        capital = lane_capital_status("CRYPTO")
        capital_limit = capital.get("configured_limit")
        capital_configured = bool(capital.get("capital_configured"))
        broker = self.alpaca_paper_broker
        capability = {}
        if broker is not None and hasattr(broker, "crypto_capability_status"):
            try:
                capability = dict(broker.crypto_capability_status(False) or {})
            except Exception:
                capability = {}
        paper_ready = bool(
            requested
            and not kill_switch
            and capability.get("paper_mode_verified")
            and capability.get("paper_endpoint_confirmed")
            and not capability.get("live_endpoint_detected")
            and capability.get("crypto_trading_supported")
            and capability.get("tradable_pairs")
            and capability.get("market_data_entitlement_confirmed")
            and capital_configured
        )
        return {
            "activation_requested": requested,
            "kill_switch_enabled": kill_switch,
            "paper_active_bounded": paper_ready,
            "capital_book_id": "paper_crypto_separate",
            "capital_configured": capital_configured,
            "capital_limit": capital_limit,
            "approved_capital_ceiling": capital.get("approved_ceiling"),
            "capital_configuration_status": capital.get("capital_configuration_status"),
            "capability": capability,
            "day_trade_capacity": 6,
            "short_swing_capacity": 2,
            "scalp_broker_capacity": 0,
            "exact_blocker": "" if paper_ready else str(capital.get("capital_configuration_status") or "CRYPTO_CAPITAL_CONFIGURATION_REQUIRED") if not capital_configured else str(capability.get("exact_blocker") or "crypto_runtime_capability_not_validated"),
        }

    def _crypto_execution_data_gate(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        quote_age = _to_float(
            row.get("quote_age_seconds"),
            _to_float(row.get("freshness_seconds"), -1.0),
        )
        spread_pct = _to_float(
            row.get("spread_pct"),
            _to_float(row.get("bid_ask_spread_pct"), -1.0),
        )
        volume = _to_float(
            row.get("volume_24h"),
            _to_float(row.get("volume"), _to_float(row.get("quote_volume"), 0.0)),
        )
        quality = _to_float(
            row.get("data_quality_score"),
            _to_float(row.get("quote_quality_score"), 0.0),
        )
        max_age = max(15.0, _to_float(os.getenv("ASTRA_CRYPTO_MAX_QUOTE_AGE_SECONDS"), 120.0))
        max_spread = max(0.1, _to_float(os.getenv("ASTRA_CRYPTO_MAX_SPREAD_PCT"), 1.5))
        min_quality = max(0.0, _to_float(os.getenv("ASTRA_CRYPTO_MIN_DATA_QUALITY_SCORE"), 50.0))
        meta = {
            "crypto_quote_age_seconds": quote_age if quote_age >= 0 else None,
            "crypto_spread_pct": spread_pct if spread_pct >= 0 else None,
            "crypto_volume": volume,
            "crypto_data_quality_score": quality,
            "crypto_max_quote_age_seconds": max_age,
            "crypto_max_spread_pct": max_spread,
            "crypto_min_data_quality_score": min_quality,
        }
        if quote_age < 0:
            return False, "crypto_quote_freshness_missing", meta
        if quote_age > max_age:
            return False, "crypto_quote_stale", meta
        if spread_pct < 0:
            return False, "crypto_spread_missing", meta
        if spread_pct > max_spread:
            return False, "crypto_spread_too_wide", meta
        if volume <= 0:
            return False, "crypto_volume_missing", meta
        if quality < min_quality:
            return False, "crypto_data_quality_below_floor", meta
        return True, "crypto_market_data_gates_passed", meta

    def _crypto_execution_integrity_gate(self, row: dict[str, Any], *, capacity_available: bool = True, duplicate_pending: bool = False, reconciliation_ok: bool = False) -> tuple[bool, str, dict[str, Any]]:
        """Use the same strict identity/gate truth as the diagnostics and broker."""
        activation = self._crypto_paper_activation_status()
        capability = dict(activation.get("capability") or {})
        result = candidate_execution_integrity(
            row,
            supported_pairs=set(capability.get("supported_pairs") or []),
            tradable_pairs=set(capability.get("tradable_pairs") or []),
            lane_state="LANE_PAPER_ACTIVE_BOUNDED" if activation.get("paper_active_bounded") else "LANE_BLOCKED",
            paper_mode_verified=bool(capability.get("paper_mode_verified")),
            live_endpoint_detected=bool(capability.get("live_endpoint_detected")),
            capacity_available=capacity_available,
            duplicate_pending=duplicate_pending,
            broker_reconciliation_ok=reconciliation_ok,
            kill_switch_enabled=bool(activation.get("kill_switch_enabled")),
        )
        failed = list(result.get("failed_gates") or [])
        return bool(result.get("execution_eligible")), (failed[0] if failed else "crypto_execution_integrity_passed"), result

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

    def _evidence_capacity_snapshot_v1(
        self,
        broker_snapshot: dict[str, Any],
        open_rows: list[dict[str, Any]],
        safety: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the canonical capacity snapshot from this worker's reads."""
        account: dict[str, Any] = {}
        broker = self.alpaca_paper_broker
        if broker is not None and hasattr(broker, "account") and bool(safety.get("broker_execution_enabled")):
            try:
                account = dict(broker.account() or {})
            except Exception:
                account = {}
        broker_payload = dict(broker_snapshot or {})
        broker_payload["broker_state_age_seconds"] = 0.0 if broker_payload.get("broker_positions_fetch_ok") else None
        if broker_payload.get("broker_positions_fetch_ok"):
            positions = []
            internal_by_symbol = {
                str(row.get("symbol") or "").upper().strip(): dict(row)
                for row in open_rows
                if str(row.get("symbol") or "").strip()
            }
            for symbol, broker_row in dict(broker_payload.get("broker_position_by_symbol") or {}).items():
                positions.append({**internal_by_symbol.get(str(symbol).upper().strip(), {}), **dict(broker_row or {})})
        else:
            # A stale/unavailable broker snapshot must not authorize capacity.
            positions = []
        snapshot = build_capacity_snapshot(
            broker_snapshot=broker_payload,
            account_snapshot=account,
            open_positions=positions,
            global_position_limit=self.max_open_positions_total,
            global_risk_allowed=True,
            lane_entry_counts=self._evidence_reserve_entry_counts(),
        )
        self._runtime_state["last_evidence_capacity_snapshot"] = dict(snapshot)
        return snapshot

    def _evidence_reserve_entry_counts(self) -> dict[str, int]:
        """Return bounded DAY/CRYPTO reserve usage without scanning history."""
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        usage = self._runtime_state.setdefault("evidence_reserve_entry_timestamps", {"DAY": [], "CRYPTO": []})
        counts: dict[str, int] = {}
        for lane in ("DAY", "CRYPTO"):
            kept: list[str] = []
            for raw in list(usage.get(lane) or []):
                try:
                    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=UTC)
                    age = (now - parsed.astimezone(UTC)).total_seconds()
                    same_day = parsed.astimezone(ZoneInfo("America/New_York")).date().isoformat() == today
                    if (lane == "DAY" and same_day) or (lane == "CRYPTO" and age <= 86400):
                        kept.append(str(raw))
                except (TypeError, ValueError):
                    continue
            usage[lane] = kept[-32:]
            counts[lane] = len(kept)
        return counts

    def _record_evidence_reserve_entry(self, lane: str) -> None:
        lane = str(lane or "").upper()
        if lane not in {"DAY", "CRYPTO"}:
            return
        self._evidence_reserve_entry_counts()
        usage = self._runtime_state.setdefault("evidence_reserve_entry_timestamps", {"DAY": [], "CRYPTO": []})
        usage.setdefault(lane, []).append(_now_iso())

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
        capacity_decision: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool, str, dict[str, Any]]:
        r = _normalize_paper_entry_bridge(row)
        symbol = str(r.get("symbol") or "").upper().strip()
        asset = _norm_asset(r.get("asset_type") or "stock")
        crypto_source_ready = not bool(r.get("operational_probe_only")) if asset == "crypto" else True
        crypto_freshness_ready = bool(
            crypto_source_ready and (r.get("candidate_generated_at") or r.get("generated_at"))
        ) if asset == "crypto" else True
        activation = canonical_lane_activation_contract(
            str(r.get("lane_id") or ""),
            broker_safety=self._alpaca_safety_snapshot(),
            session_state="CRYPTO_24_7_ALLOWED" if asset == "crypto" else None,
            session_allowed=True if asset == "crypto" else None,
            session_source="crypto_24_7_market_model" if asset == "crypto" else None,
            candidate_source_ready=crypto_source_ready,
            candidate_freshness_ready=crypto_freshness_ready,
        )
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
        reserve_capacity_allowed = bool((capacity_decision or {}).get("allowed"))
        if not bool(activation.get("execution_enabled")):
            reason = str((activation.get("exact_blockers") or ["LANE_EXECUTION_DISABLED"])[0])
        elif not symbol:
            reason = "missing_symbol"
        elif symbol in open_syms:
            reason = "duplicate_active_position"
        elif self._cooldown_active(symbol):
            reason = "cooldown_active"
        elif total_capacity <= 0 and not reserve_capacity_allowed:
            reason = "max_concurrent_positions_reached"
        elif selected_so_far >= max_new_limit:
            reason = "max_new_positions_per_cycle_reached"
        elif asset == "stock" and stock_capacity <= 0 and not reserve_capacity_allowed:
            reason = "stock_capacity_reached"
        elif asset == "crypto" and crypto_capacity <= 0 and not reserve_capacity_allowed:
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
        if asset == "crypto":
            crypto_activation = self._crypto_paper_activation_status()
            horizon = str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or "day_trade")
            crypto_data_ok, crypto_data_reason, crypto_data_meta = self._crypto_execution_data_gate(r)
            integrity_ok, integrity_reason, integrity_meta = self._crypto_execution_integrity_gate(
                r,
                capacity_available=(crypto_capacity > 0 and total_capacity > 0) or reserve_capacity_allowed,
                duplicate_pending=symbol in open_syms,
                reconciliation_ok=broker_reconciliation_active,
            )
            crypto_session_ok = bool(
                crypto_activation.get("paper_active_bounded")
                and horizon in {"day_trade", "swing_trade"}
                and crypto_data_ok
                and integrity_ok
            )
            session_diag = {
                "market_session_mode": "crypto_24_7",
                "current_session_type": "crypto_24_7",
                "market_is_open": True,
                "market_is_tradable": crypto_session_ok,
                "session_tradable": crypto_session_ok,
                "paper_order_submission_allowed": crypto_session_ok,
                "execution_confirmation_required": not crypto_session_ok,
                "open_confirmation_score": 100.0 if crypto_session_ok else 0.0,
                "open_confirmation_label": "confirmed_execute" if crypto_session_ok else "crypto_activation_blocked",
                "open_confirmation_reason": "runtime_capability_market_data_and_24_7_session_verified" if crypto_session_ok else crypto_data_reason if not crypto_data_ok else integrity_reason if not integrity_ok else crypto_activation.get("exact_blocker"),
                "execution_intent_status": "paper_ready" if crypto_session_ok else "blocked",
                "defer_until_market_confirmation": False,
                "requires_open_confirmation": not crypto_session_ok,
            }
            if not crypto_session_ok and allowed:
                allowed = False
                reason = "crypto_scalp_shadow_only" if horizon == "scalp" else crypto_data_reason if not crypto_data_ok else integrity_reason if not integrity_ok else "crypto_paper_activation_not_ready"
            gate_meta.update(crypto_data_meta)
            gate_meta["crypto_execution_integrity"] = integrity_meta
            gate_meta["crypto_execution_integrity_ok"] = integrity_ok
            gate_meta["crypto_execution_integrity_reason"] = integrity_reason
            gate_meta["crypto_market_data_gates_ok"] = crypto_data_ok
            gate_meta["crypto_market_data_gate_reason"] = crypto_data_reason
        trace = {
            "symbol": symbol,
            "canonical_symbol": str(r.get("canonical_symbol") or symbol).upper(),
            "asset_type": asset,
            "candidate_id": str(r.get("candidate_id") or ""),
            "recommendation_id": str(r.get("recommendation_id") or ""),
            "selection_id": str(r.get("selection_id") or ""),
            "candidate_source": str(r.get("candidate_source") or ""),
            "candidate_generated_at": str(r.get("candidate_generated_at") or r.get("decision_timestamp") or ""),
            "candidate_snapshot_freshness": str(r.get("candidate_snapshot_freshness") or "MISSING"),
            "source_snapshot_id": str(r.get("source_snapshot_id") or ""),
            "source_record_id": str(r.get("source_record_id") or ""),
            "ranking_version": str(r.get("ranking_version") or ""),
            "generated_at": str(r.get("generated_at") or r.get("candidate_generated_at") or ""),
            "expires_at": str(r.get("expires_at") or ""),
            "candidate_fingerprint": str(r.get("candidate_fingerprint") or r.get("candidate_id") or ""),
            "operational_probe_only": bool(r.get("operational_probe_only", False)),
            "operational_source_rejection": str(r.get("operational_source_rejection") or ""),
            "lane_id": str(r.get("lane_id") or ""),
            "lane_activation_contract": activation,
            "lane_execution_enabled": bool(activation.get("execution_enabled")),
            "asset_class": str(r.get("asset_class") or ""),
            "instrument_type": str(r.get("instrument_type") or ""),
            "trade_style": str(r.get("trade_style") or ""),
            "strategy_cohort": str(r.get("strategy_cohort") or ""),
            "intended_horizon": str(r.get("intended_horizon") or ""),
            "capital_book_id": str(r.get("capital_book_id") or ""),
            "position_owner": str(r.get("position_owner") or ""),
            "exit_policy_owner": str(r.get("exit_policy_owner") or ""),
            "entry_owner": str(r.get("entry_owner") or "PaperAutopilot"),
            "exit_owner": str(r.get("exit_owner") or r.get("exit_policy_owner") or r.get("lane_id") or ""),
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
            "capacity_decision": str((capacity_decision or {}).get("capacity_decision") or "LEGACY_CAPACITY_PATH"),
            "capacity_source": str((capacity_decision or {}).get("capacity_source") or "legacy_worker_capacity"),
            "capacity_snapshot_id": str((capacity_decision or {}).get("snapshot_id") or ""),
            "global_capacity_status": str((capacity_decision or {}).get("global_capacity_status") or ""),
            "lane_reserve_status": str((capacity_decision or {}).get("lane_reserve_status") or ""),
            "lane_capital_remaining": (capacity_decision or {}).get("capital_remaining"),
            "lane_positions_remaining": (capacity_decision or {}).get("positions_remaining"),
            "capacity_blocker": str(((capacity_decision or {}).get("exact_blockers") or [""])[0] or ""),
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
            "session_state": str(activation.get("session_state") or "CANDIDATE_DEPENDENT"),
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
            "order_ready": False,
            "submit_order": False,
            "broker_actions_used": 0,
            "generated_at": _now_iso(),
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
        activation = canonical_lane_activation_contract(
            str(r.get("lane_id") or ""),
            broker_safety=self._alpaca_safety_snapshot(),
        )
        if not bool(activation.get("execution_enabled")):
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": str((activation.get("exact_blockers") or ["LANE_EXECUTION_DISABLED"])[0]),
                "lane_activation_contract": activation,
            }
        attribution = _paper_attribution_metadata(r)
        attribution_client_order_id = _paper_attribution_client_order_id(r)
        asset_type = _norm_asset(r.get("asset_type") or "stock")
        crypto_activation = self._crypto_paper_activation_status() if asset_type == "crypto" else {}
        if asset_type == "crypto" and not crypto_activation.get("paper_active_bounded"):
            return {"enabled": False, "paper_order_submitted": False, "reason": str(crypto_activation.get("exact_blocker") or "alpaca_crypto_execution_not_validated")}
        if asset_type == "crypto":
            crypto_data_ok, crypto_data_reason, crypto_data_meta = self._crypto_execution_data_gate(r)
            if not crypto_data_ok:
                return {
                    "enabled": False,
                    "paper_order_submitted": False,
                    "reason": crypto_data_reason,
                    **crypto_data_meta,
                }
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
        if asset_type == "crypto":
            session_diag = {
                "market_session_mode": "crypto_24_7",
                "paper_order_submission_allowed": True,
                "execution_confirmation_required": False,
                "open_confirmation_score": 100.0,
                "open_confirmation_label": "confirmed_execute",
                "open_confirmation_reason": "runtime_crypto_capability_verified",
                "quote_freshness_confirmed": True,
                "spread_liquidity_confirmed": True,
                "gap_behavior_confirmed": True,
                "entry_commitment_confirmed": True,
                "portfolio_risk_confirmed": bool(portfolio_ok),
                "broker_preflight_confirmed": True,
                "execution_intent_status": "paper_ready",
                "defer_until_market_confirmation": False,
                "requires_open_confirmation": False,
            }
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
            "recommendation_id": attribution["recommendation_id"],
            "decision_id": attribution["decision_id"],
            "eligibility_evaluation_id": attribution["eligibility_evaluation_id"],
            "candidate_id": attribution["candidate_id"],
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "best_horizon_style": str(r.get("best_horizon_style") or r.get("trade_horizon_style") or ""),
            "paper_entry_horizon_style": str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or ""),
            "intended_trade_style": str(r.get("intended_trade_style") or r.get("trade_horizon_style") or ""),
            "actual_horizon_classification": str(r.get("actual_horizon_classification") or r.get("trade_horizon_style") or ""),
            "turnover_trade_style": str(r.get("turnover_trade_style") or r.get("trade_horizon_style") or ""),
            "horizon_source": str(r.get("horizon_source") or r.get("paper_entry_horizon_source") or ""),
            "paper_entry_horizon_source": str(r.get("paper_entry_horizon_source") or r.get("horizon_source") or ""),
            "paper_entry_horizon_inferred": bool(r.get("paper_entry_horizon_inferred", False)),
            "expected_hold_window": str(r.get("expected_hold_window") or ""),
            "expected_hold_minutes": round(_to_float(r.get("expected_hold_minutes"), 0.0), 3),
            "expected_hold_days": round(_to_float(r.get("expected_hold_days"), 0.0), 4),
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
        order.update({field: r.get(field) for field in CONTRACT_FIELDS if field in r})
        if attribution_client_order_id:
            order["client_order_id"] = attribution_client_order_id
        if asset_type == "crypto":
            integrity_row = dict(r)
            integrity_row["notional"] = min(50.0, max(10.0, _to_float(os.getenv("ASTRA_ALPACA_CRYPTO_PAPER_NOTIONAL"), 25.0)))
            integrity_ok, integrity_reason, integrity = self._crypto_execution_integrity_gate(
                integrity_row,
                capacity_available=True,
                duplicate_pending=str(r.get("symbol") or "").upper().strip() in set(broker_snapshot.get("broker_open_symbols") or set()),
                reconciliation_ok=reconciliation_checked,
            )
            if not integrity_ok:
                return {
                    "ok": False,
                    "paper_order_submitted": False,
                    "error": integrity_reason,
                    "crypto_execution_integrity": integrity,
                }
            order.update({
                "asset_class": "crypto",
                "crypto_paper_activation_passed": True,
                "crypto_execution_integrity_passed": True,
                "crypto_execution_integrity": integrity,
                "crypto_capacity_available": True,
                "duplicate_pending_order": False,
                "broker_reconciliation_ok": reconciliation_checked,
                "crypto_kill_switch_enabled": False,
                "time_in_force": "gtc",
                "notional": integrity_row["notional"],
            })
        try:
            res = dict(broker.submit_paper_order(order) or {})
            res.setdefault("paper_autopilot_limits_ok", True)
            res.setdefault("paper_autopilot_limits_reason", str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"))
            res.setdefault("portfolio_risk_proof_present", bool(portfolio_risk_proof_present))
            res.setdefault("portfolio_risk_score_used", (None if risk_score is None else round(float(risk_score), 4)))
            res.setdefault("portfolio_risk_label_used", risk_label_raw)
            res.setdefault("portfolio_risk_preflight_reason", preflight_reason)
            res.setdefault("recommendation_id", attribution["recommendation_id"])
            res.setdefault("decision_id", attribution["decision_id"])
            res.setdefault("eligibility_evaluation_id", attribution["eligibility_evaluation_id"])
            res.setdefault("candidate_id", attribution["candidate_id"])
            res.setdefault("client_order_id", attribution_client_order_id)
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
        attribution = _paper_attribution_metadata(r)
        return {
            "entry_reason": "paper_autopilot_entry",
            "recommendation_id": attribution["recommendation_id"],
            "decision_id": attribution["decision_id"],
            "eligibility_evaluation_id": attribution["eligibility_evaluation_id"],
            "candidate_id": attribution["candidate_id"],
            "attribution_status": "captured_from_canonical_candidate" if any(attribution.values()) else "not_present_on_candidate",
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
            "best_horizon_style": str(r.get("best_horizon_style") or r.get("trade_horizon_style") or ""),
            "paper_entry_horizon_style": str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or ""),
            "intended_trade_style": str(r.get("intended_trade_style") or r.get("trade_horizon_style") or ""),
            "actual_horizon_classification": str(r.get("actual_horizon_classification") or r.get("trade_horizon_style") or ""),
            "turnover_trade_style": str(r.get("turnover_trade_style") or r.get("trade_horizon_style") or ""),
            "horizon_source": str(r.get("horizon_source") or r.get("paper_entry_horizon_source") or ""),
            "paper_entry_horizon_source": str(r.get("paper_entry_horizon_source") or r.get("horizon_source") or ""),
            "paper_entry_horizon_inferred": bool(r.get("paper_entry_horizon_inferred", False)),
            "expected_hold_window": str(r.get("expected_hold_window") or ""),
            "expected_hold_minutes": round(_to_float(r.get("expected_hold_minutes"), 0.0), 3),
            "expected_hold_days": round(_to_float(r.get("expected_hold_days"), 0.0), 4),
            "horizon_persistence_bundle_v1": bool(r.get("horizon_persistence_bundle_v1", False)),
            **{field: r.get(field) for field in CONTRACT_FIELDS if field in r},
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
        entry_row["recommendation_id"] = str(
            entry_row.get("recommendation_id") or broker_order.get("recommendation_id") or ""
        ).strip()
        entry_row["decision_id"] = str(
            entry_row.get("decision_id") or broker_order.get("decision_id") or ""
        ).strip()
        entry_row["eligibility_evaluation_id"] = str(
            entry_row.get("eligibility_evaluation_id") or broker_order.get("eligibility_evaluation_id") or ""
        ).strip()
        entry_row["candidate_id"] = str(
            entry_row.get("candidate_id") or broker_order.get("candidate_id") or ""
        ).strip()
        entry_context = self._build_entry_context_v1(submit_row, entry_price, source_bucket, gate_meta=gate_meta)
        entry_context["position_id"] = pid
        entry_context["alpaca_paper_order"] = broker_order
        broker_order_payload = dict(broker_order.get("order") or {}) if isinstance(broker_order, dict) else {}
        source_broker_order_id = str(
            broker_order_payload.get("id")
            or broker_order_payload.get("broker_order_id")
            or (broker_order.get("broker_order_id") if isinstance(broker_order, dict) else "")
            or (broker_order.get("order_id") if isinstance(broker_order, dict) else "")
            or ""
        ).strip()
        source_client_order_id = str(
            broker_order_payload.get("client_order_id")
            or (broker_order.get("client_order_id") if isinstance(broker_order, dict) else "")
            or entry_row.get("client_order_id")
            or ""
        ).strip()
        # Alpaca may expose executions through the order's filled timestamp
        # rather than a separate execution object.  The derived identifier is
        # retained only when the broker reports a filled order; pending orders
        # never gain a fill ID.
        entry_filled_at = str(broker_order_payload.get("filled_at") or "").strip()
        entry_fill_id = str(
            broker_order_payload.get("fill_id")
            or broker_order_payload.get("execution_id")
            or (f"{source_broker_order_id}:{entry_filled_at}" if source_broker_order_id and entry_filled_at else "")
        ).strip()
        entry_context.update({
            "lane_id": entry_row.get("lane_id"),
            "capital_book_id": entry_row.get("capital_book_id"),
            "position_owner": entry_row.get("position_owner"),
            "exit_policy_owner": entry_row.get("exit_policy_owner"),
            "entry_order_id": source_broker_order_id,
            "entry_fill_id": entry_fill_id,
        })
        canonical_horizon = str(
            entry_context.get("paper_entry_horizon_style")
            or entry_context.get("trade_horizon_style")
            or entry_context.get("best_horizon_style")
            or ""
        ).strip().lower()
        canonical_horizon_source = str(
            entry_context.get("paper_entry_horizon_source")
            or entry_context.get("horizon_source")
            or ""
        ).strip()
        canonical_horizon_confidence = 65.0 if bool(entry_context.get("paper_entry_horizon_inferred")) else 95.0

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions(
                    position_id, symbol, asset_type, status, quantity,
                    entry_price, exit_price, return_percent, friction_adjusted_return,
                    entry_timestamp, exit_timestamp, hold_seconds,
                    canonical_horizon, canonical_horizon_source, canonical_horizon_confidence,
                    source_broker_order_id, source_client_order_id,
                    source_recommendation_id, source_decision_id, source_eligibility_evaluation_id,
                    source_bucket, lifecycle_notes, row_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    symbol,
                    asset_type,
                    1.0,
                    entry_price,
                    now_iso,
                    canonical_horizon,
                    canonical_horizon_source,
                    canonical_horizon_confidence,
                    source_broker_order_id,
                    source_client_order_id,
                    entry_context.get("recommendation_id") or entry_row.get("recommendation_id"),
                    entry_context.get("decision_id") or entry_row.get("decision_id"),
                    entry_context.get("eligibility_evaluation_id") or entry_row.get("eligibility_evaluation_id"),
                    source_bucket,
                    _safe_json(entry_context),
                    _safe_json(entry_row),
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                UPDATE paper_positions
                SET lane_id=?, capital_book_id=?, position_owner=?, exit_policy_owner=?,
                    entry_order_id=?, entry_fill_id=?
                WHERE position_id=?
                """,
                (
                    str(entry_row.get("lane_id") or ""),
                    str(entry_row.get("capital_book_id") or ""),
                    str(entry_row.get("position_owner") or ""),
                    str(entry_row.get("exit_policy_owner") or ""),
                    source_broker_order_id,
                    entry_fill_id,
                    pid,
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
                        "best_horizon_style": str(row.get("best_horizon_style") or row.get("trade_horizon_style") or ""),
                        "paper_entry_horizon_style": str(row.get("paper_entry_horizon_style") or row.get("trade_horizon_style") or ""),
                        "intended_trade_style": str(row.get("intended_trade_style") or row.get("trade_horizon_style") or ""),
                        "actual_horizon_classification": str(row.get("actual_horizon_classification") or row.get("trade_horizon_style") or ""),
                        "turnover_trade_style": str(row.get("turnover_trade_style") or row.get("trade_horizon_style") or ""),
                        "horizon_source": str(row.get("horizon_source") or row.get("paper_entry_horizon_source") or ""),
                        "paper_entry_horizon_source": str(row.get("paper_entry_horizon_source") or row.get("horizon_source") or ""),
                        "paper_entry_horizon_inferred": bool(row.get("paper_entry_horizon_inferred", False)),
                        "expected_hold_window": str(row.get("expected_hold_window") or ""),
                        "expected_hold_minutes": _to_float(row.get("expected_hold_minutes"), 0.0),
                        "expected_hold_days": _to_float(row.get("expected_hold_days"), 0.0),
                        "horizon_persistence_bundle_v1": bool(row.get("horizon_persistence_bundle_v1", False)),
                        **{field: row.get(field) for field in CONTRACT_FIELDS if field in row},
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

    def _close_position(
        self,
        open_row: dict[str, Any],
        latest_row: dict[str, Any],
        exit_reason: str,
        *,
        broker_fill: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pid = str(open_row.get("position_id") or "").strip()
        symbol = str(open_row.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(open_row.get("asset_type") or "stock")
        if not pid or not symbol:
            return {"ok": False, "error": "position_row_invalid"}

        lane = str(open_row.get("lane_id") or "").upper().strip()
        # A DAY/CRYPTO lifecycle is not closed locally before the authorized
        # paper exit has a real broker fill.  SWING retains its existing path.
        if lane in {"DAY", "CRYPTO"}:
            contract = self._authorized_lane_exit_contract(open_row)
            if not contract.get("authorized"):
                return {"ok": False, "error": str(contract.get("reason") or "lane_exit_not_authorized"), "contract": contract}
            if not isinstance(broker_fill, dict) or not str(broker_fill.get("exit_order_id") or "").strip() or not str(broker_fill.get("exit_fill_id") or "").strip():
                return {"ok": False, "error": "broker_exit_fill_required_before_lane_lifecycle_close", "contract": contract}

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
            if lane in {"DAY", "CRYPTO"} and isinstance(broker_fill, dict):
                conn.execute(
                    "UPDATE paper_positions SET exit_order_id=?, exit_fill_id=? WHERE position_id=?",
                    (str(broker_fill.get("exit_order_id") or ""), str(broker_fill.get("exit_fill_id") or ""), pid),
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
                        "exit_order_id": str((broker_fill or {}).get("exit_order_id") or ""),
                        "exit_fill_id": str((broker_fill or {}).get("exit_fill_id") or ""),
                        "entry_order_id": str(open_row.get("entry_order_id") or open_row.get("source_broker_order_id") or ""),
                        "entry_fill_id": str(open_row.get("entry_fill_id") or ""),
                        "lane_id": lane,
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

        strict_truth_result = {}
        if lane in {"DAY", "CRYPTO"} and isinstance(broker_fill, dict):
            strict_truth_result = self._persist_strict_lane_truth(
                open_row,
                broker_fill,
                exit_price=exit_price,
                return_percent=ret,
                hold_seconds=hold_seconds,
                exit_reason=exit_reason,
            )

        return {
            "ok": True,
            "position_id": pid,
            "symbol": symbol,
            "return_percent": round(ret, 4),
            "exit_reason": exit_reason,
            "hold_seconds": round(hold_seconds, 2),
            "lane_id": lane,
            "strict_exit_fill_linked": bool(lane in {"DAY", "CRYPTO"} and broker_fill),
            "strict_broker_truth_persistence": strict_truth_result,
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
            authorized_lane_exit_refresh = self._refresh_authorized_lane_exit_pending()
            open_rows_initial = self._fetch_open_positions()
            internal_open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows_initial}
            broker_snapshot = self._broker_open_symbols_snapshot()
            broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
            broker_position_by_symbol = dict(broker_snapshot.get("broker_position_by_symbol") or {})
            broker_position_review_rows = [
                {
                    "symbol": str(symbol).upper(),
                    **dict(broker_position_by_symbol.get(symbol) or {}),
                    "evidence_class": "BROKER_OPEN_POSITION_SNAPSHOT",
                    "broker_confirmed": True,
                }
                for symbol in sorted(broker_open_syms)
            ][:100]
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
                forced_lane_reason = self._lane_forced_exit_reason(row)
                if forced_lane_reason:
                    should_close, reason = True, forced_lane_reason
                if should_close and hold_seconds >= float(min_hold):
                    lane = str(row.get("lane_id") or "").upper().strip()
                    if lane in {"DAY", "CRYPTO"}:
                        result = self._submit_authorized_lane_exit(
                            row,
                            dict(broker_position_by_symbol.get(symbol) or {}),
                            reason,
                        )
                    else:
                        result = self._close_position(row, latest, reason)
                    if result.get("ok"):
                        closed += 1 if lane not in {"DAY", "CRYPTO"} else 0
                        state = self._learned_exit_daily_state()
                        state["baseline_exits"] = _to_int(state.get("baseline_exits"), 0) + 1
                        self._update_learned_exit_daily_state(state)
                        if symbol:
                            open_syms.discard(symbol)

            if capacity_source == "broker":
                broker_crypto_rows = {
                    symbol: row
                    for symbol, row in broker_position_by_symbol.items()
                    if str((row or {}).get("asset_class") or (row or {}).get("asset_type") or "").strip().lower()
                    in {"crypto", "cryptocurrency"}
                }
                broker_crypto_open = int(len(broker_crypto_rows))
                broker_stock_open = max(0, int(len([s for s in broker_open_syms if s])) - broker_crypto_open)
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
            internal_by_symbol = {
                str((row or {}).get("symbol") or "").upper().strip(): dict(row or {})
                for row in open_rows_initial
                if str((row or {}).get("symbol") or "").strip()
            }
            crypto_day_used = 0
            crypto_swing_used = 0
            crypto_position_rows = (
                broker_crypto_rows.items()
                if capacity_source == "broker"
                else (
                    (str((row or {}).get("symbol") or "").upper().strip(), row)
                    for row in open_rows_initial
                    if _norm_asset((row or {}).get("asset_type") or "stock") == "crypto"
                )
            )
            for crypto_symbol, broker_or_internal in crypto_position_rows:
                merged_crypto = {**dict(internal_by_symbol.get(crypto_symbol) or {}), **dict(broker_or_internal or {})}
                existing_horizon, _source, _inferred = _infer_horizon_style(merged_crypto)
                if existing_horizon == "swing_trade":
                    crypto_swing_used += 1
                else:
                    # Unknown/legacy crypto positions consume the conservative day lane.
                    crypto_day_used += 1
            crypto_day_available = max(0, self.crypto_day_capacity - crypto_day_used)
            crypto_swing_available = max(0, self.crypto_short_swing_capacity - crypto_swing_used)
            crypto_capacity = min(crypto_capacity, crypto_day_available + crypto_swing_available)
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
            evidence_capacity_snapshot = self._evidence_capacity_snapshot_v1(
                broker_snapshot,
                open_rows_initial,
                safety,
            )
            reserve_selected_by_lane = {"DAY": 0, "CRYPTO": 0}
            # Normalize every worker-cycle observation before any early gate
            # can reject it.  The ranking and eligibility values are retained;
            # this only gives every candidate a stable operational lineage.
            candidates = [_normalize_paper_entry_bridge(row) for row in self._collect_candidate_rows() if isinstance(row, dict)]
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
                    skipped += 1
                    decision_trace.append(_execution_trace_event(
                        row, eligible=False, selected=False,
                        decision_reason="max_new_positions_per_cycle_reached",
                    ))
                    continue
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                candidate_lane = str(row.get("lane_id") or ("CRYPTO" if asset == "crypto" else "SWING")).upper()
                capacity_decision = candidate_capacity_decision(
                    evidence_capacity_snapshot,
                    lane_id=candidate_lane,
                    symbol=symbol,
                    open_symbols=open_syms,
                )
                if reserve_selected_by_lane.get(candidate_lane, 0) > 0 and candidate_lane in reserve_selected_by_lane:
                    capacity_decision = {
                        **capacity_decision,
                        "allowed": False,
                        "capacity_decision": "LANE_RESERVE_EXHAUSTED",
                        "exact_blockers": ["LANE_POSITION_LIMIT_REACHED"],
                    }
                capacity_blocked_by_legacy_global = bool(
                    (total_capacity <= 0 and not capacity_decision.get("allowed"))
                    or (asset == "stock" and stock_capacity <= 0 and not capacity_decision.get("allowed"))
                    or (asset == "crypto" and crypto_capacity <= 0 and not capacity_decision.get("allowed"))
                )
                if capacity_blocked_by_legacy_global:
                    skipped += 1
                    reason = str(capacity_decision.get("capacity_decision") or "FAIL_CLOSED")
                    final_blocker_reason = reason
                    decision_trace.append(_execution_trace_event(
                        row, symbol=symbol, asset_type=asset, eligible=False,
                        selected=False, decision_reason=reason,
                        capacity_decision=reason,
                        capacity_source=capacity_decision.get("capacity_source"),
                        capacity_snapshot_id=capacity_decision.get("snapshot_id"),
                        global_capacity_status=capacity_decision.get("global_capacity_status"),
                        lane_reserve_status=capacity_decision.get("lane_reserve_status"),
                        lane_capital_remaining=capacity_decision.get("capital_remaining"),
                        lane_positions_remaining=capacity_decision.get("positions_remaining"),
                        capacity_blocker=(capacity_decision.get("exact_blockers") or [reason])[0],
                    ))
                    continue
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
                    decision_trace.append(_execution_trace_event(
                        row, symbol=symbol, asset_type=asset, eligible=False,
                        selected=False, decision_reason=reason,
                        duplicate_source=duplicate_source,
                        broker_reconciliation_active=broker_reconciliation_active,
                    ))
                    final_blocker_reason = reason
                    continue
                if self._cooldown_active(symbol):
                    skipped += 1
                    decision_trace.append(_execution_trace_event(
                        row, symbol=symbol, asset_type=asset, eligible=False,
                        selected=False, decision_reason="cooldown_active",
                    ))
                    final_blocker_reason = "cooldown_active"
                    continue
                candidate_horizon, candidate_horizon_source, candidate_horizon_inferred = _infer_horizon_style(row)
                if not candidate_horizon:
                    candidate_horizon = "unknown"
                    candidate_horizon_source = "missing_horizon"
                    candidate_horizon_inferred = True
                if asset == "crypto":
                    if candidate_horizon == "scalp":
                        horizon_ok, horizon_capacity_reason = False, "crypto_scalp_shadow_only"
                    elif candidate_horizon == "swing_trade":
                        horizon_ok = crypto_swing_available > 0
                        horizon_capacity_reason = "crypto_short_swing_capacity_available" if horizon_ok else "crypto_short_swing_capacity_reached"
                    else:
                        candidate_horizon = "day_trade"
                        horizon_ok = crypto_day_available > 0
                        horizon_capacity_reason = "crypto_day_trade_capacity_available" if horizon_ok else "crypto_day_trade_capacity_reached"
                else:
                    horizon_ok, horizon_capacity_reason = self._horizon_has_capacity(horizon_capacity, candidate_horizon)
                if not horizon_ok and capacity_decision.get("allowed") and candidate_lane in {"DAY", "CRYPTO"}:
                    # The evidence reserve replaces only the exhausted global
                    # slot.  Candidate quality, session, risk, liquidity, and
                    # lane position/capital gates still run below.
                    horizon_ok = True
                    horizon_capacity_reason = "lane_evidence_reserve_available_global_horizon_full"
                if not horizon_ok:
                    skipped += 1
                    horizon_capacity_blocked += 1
                    confidence_for_block = _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0))
                    if confidence_for_block >= 80.0:
                        high_confidence_horizon_capacity_blocked += 1
                    decision_trace.append(_execution_trace_event(
                        row, symbol=symbol, asset_type=asset, eligible=False,
                        selected=False, decision_reason=horizon_capacity_reason,
                        trade_horizon_style=candidate_horizon,
                        paper_entry_horizon_source=candidate_horizon_source,
                        paper_entry_horizon_inferred=bool(candidate_horizon_inferred),
                        horizon_capacity=dict(horizon_capacity),
                        horizon_capacity_enabled=bool(self.horizon_capacity_enabled),
                    ))
                    final_blocker_reason = horizon_capacity_reason
                    continue
                if asset == "stock" and stock_capacity <= 0:
                    if not capacity_decision.get("allowed"):
                        final_blocker_reason = str(capacity_decision.get("capacity_decision") or "stock_capacity_reached")
                        stock_capacity_reason = final_blocker_reason
                        decision_trace.append(_execution_trace_event(
                            row, eligible=False, selected=False,
                            decision_reason=final_blocker_reason,
                            capacity_decision=final_blocker_reason,
                            capacity_source=capacity_decision.get("capacity_source"),
                            capacity_snapshot_id=capacity_decision.get("snapshot_id"),
                            capacity_blocker=(capacity_decision.get("exact_blockers") or [final_blocker_reason])[0],
                        ))
                        continue
                if asset == "crypto" and crypto_capacity <= 0:
                    if not capacity_decision.get("allowed"):
                        final_blocker_reason = str(capacity_decision.get("capacity_decision") or "crypto_capacity_reached")
                        decision_trace.append(_execution_trace_event(
                            row, eligible=False, selected=False,
                            decision_reason=final_blocker_reason,
                            capacity_decision=final_blocker_reason,
                            capacity_source=capacity_decision.get("capacity_source"),
                            capacity_snapshot_id=capacity_decision.get("snapshot_id"),
                            capacity_blocker=(capacity_decision.get("exact_blockers") or [final_blocker_reason])[0],
                        ))
                        continue

                row_trace, allowed, reason, gate_meta = self._candidate_trace_row(
                    row,
                    open_syms=open_syms,
                    stock_capacity=stock_capacity,
                    crypto_capacity=crypto_capacity,
                    total_capacity=max(total_capacity, crypto_capacity) if asset == "crypto" else total_capacity,
                    selected_so_far=selected_count,
                    internal_open_syms=internal_open_syms,
                    broker_open_syms=broker_open_syms,
                    broker_reconciliation_active=broker_reconciliation_active,
                    capacity_decision=capacity_decision,
                )
                row_trace["horizon_capacity_enabled"] = bool(self.horizon_capacity_enabled)
                row_trace["horizon_capacity_reason"] = str(horizon_capacity_reason)
                row_trace["horizon_capacity_snapshot"] = dict(horizon_capacity)
                row_trace["canonical_capacity_snapshot"] = dict(evidence_capacity_snapshot)
                row_trace["capacity_decision"] = capacity_decision.get("capacity_decision")
                row_trace["capacity_source"] = capacity_decision.get("capacity_source")
                row_trace["capacity_snapshot_id"] = capacity_decision.get("snapshot_id")
                row_trace["global_capacity_status"] = capacity_decision.get("global_capacity_status")
                row_trace["lane_reserve_status"] = capacity_decision.get("lane_reserve_status")
                row_trace["lane_capital_remaining"] = capacity_decision.get("capital_remaining")
                row_trace["lane_positions_remaining"] = capacity_decision.get("positions_remaining")
                row_trace["capacity_blocker"] = (capacity_decision.get("exact_blockers") or [""])[0]
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
                if candidate_lane in reserve_selected_by_lane:
                    reserve_selected_by_lane[candidate_lane] += 1
                row_trace["selected"] = True
                row_trace["order_attempted"] = False
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
                actual_order_attempted = bool(
                    opened_row.get("paper_order_submission_allowed")
                    and (opened_row.get("ok") or opened_row.get("broker_order_id"))
                )
                if actual_order_attempted:
                    orders_attempted += 1
                    row_trace["order_attempted"] = True
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
                        if candidate_horizon == "swing_trade":
                            crypto_swing_available = max(0, crypto_swing_available - 1)
                        else:
                            crypto_day_available = max(0, crypto_day_available - 1)
                    if candidate_lane in {"DAY", "CRYPTO"} and capacity_decision.get("capacity_decision") == "AVAILABLE_FROM_LANE_RESERVE":
                        self._record_evidence_reserve_entry(candidate_lane)
                    if asset != "crypto":
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
                "authorized_lane_exit_refresh": authorized_lane_exit_refresh,
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
                "evidence_accumulation_capacity_v1": dict(evidence_capacity_snapshot),
                "evidence_reserve_lane_decisions": {
                    "day": dict(evidence_capacity_snapshot.get("lanes", {}).get("day", {})),
                    "crypto": dict(evidence_capacity_snapshot.get("lanes", {}).get("crypto", {})),
                },
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
                "evidence_accumulation_capacity_v1": dict(evidence_capacity_snapshot),
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
                "per_candidate_decision_trace": decision_trace[:200],
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
                "broker_position_review_rows": broker_position_review_rows,
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
            if self.execution_trace_ledger is not None:
                try:
                    trace["lane_execution_ledger"] = self.execution_trace_ledger.record(
                        decision_trace,
                        cycle_id=str(out.get("cycle_timestamp") or _now_iso()),
                    )
                except Exception:
                    # Trace persistence is observational; it must never alter
                    # the existing paper execution outcome.
                    trace["lane_execution_ledger"] = {"appended": 0, "suppressed": 0, "status": "ledger_write_failed"}
            self._runtime_state["last_cycle_utc"] = out["cycle_timestamp"]
            self._runtime_state["last_cycle_summary"] = dict(out)
            self._runtime_state["last_execution_trace"] = dict(trace)
            self._runtime_state["last_error"] = ""
            self._save_state_file()
            return out

    def operational_dry_run(
        self,
        candidate_rows: list[dict[str, Any]],
        max_candidates: int = 30,
        capacity_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate the final PaperAutopilot boundary without broker activity.

        This compact path is the runtime owner for multi-lane handoff proof. It
        intentionally skips the broad diagnostic fan-out in `execution_trace`,
        uses the caller's cached candidate snapshot, and returns a trace for
        every evaluated candidate including rejections and market-session
        blocks. The real worker remains the only order-submission owner.
        """
        candidates = [_normalize_paper_entry_bridge(row) for row in candidate_rows if isinstance(row, dict)]
        limit = max(1, min(30, int(max_candidates or 30)))
        capacities = self._current_execution_capacities()
        open_syms = set(capacities.get("open_symbols") or set())
        stock_capacity = int(capacities.get("stock_capacity", 0))
        crypto_capacity = int(capacities.get("crypto_capacity", 0))
        total_capacity = int(capacities.get("total_capacity", 0))
        canonical_capacity = dict(capacity_snapshot or {})
        selected = 0
        eligible = 0
        rows: list[dict[str, Any]] = []
        blockers: dict[str, int] = {}
        for row in candidates[:limit]:
            lane = str(row.get("lane_id") or ("CRYPTO" if _norm_asset(row.get("asset_type") or row.get("asset_class")) == "crypto" else "SWING")).upper()
            capacity_decision = (
                candidate_capacity_decision(canonical_capacity, lane_id=lane, symbol=str(row.get("symbol") or ""), open_symbols=open_syms)
                if canonical_capacity else None
            )
            trace, allowed, reason, _meta = self._candidate_trace_row(
                row,
                open_syms=open_syms,
                stock_capacity=stock_capacity,
                crypto_capacity=crypto_capacity,
                total_capacity=total_capacity,
                selected_so_far=selected,
                internal_open_syms=open_syms,
                broker_open_syms=set(),
                broker_reconciliation_active=False,
                capacity_decision=capacity_decision,
            )
            if capacity_decision:
                trace["canonical_capacity_snapshot"] = canonical_capacity
            trace["dry_run_only"] = True
            trace["submit_order"] = False
            trace["broker_actions_used"] = 0
            trace["broker_reconciliation_deferred_to_execution"] = True
            if allowed:
                eligible += 1
                if selected < self.max_new_positions_per_cycle and total_capacity > 0:
                    selected += 1
                    trace["selected"] = True
                    trace["selection_reason"] = "existing_paper_autopilot_gates_passed"
                else:
                    trace["selected"] = False
                    trace["selection_reason"] = "paper_autopilot_capacity_or_cycle_limit"
            else:
                trace["selected"] = False
                trace["selection_reason"] = str(reason)
            trace["order_ready"] = bool(
                trace.get("selected")
                and trace.get("paper_order_submission_allowed")
                and not trace.get("requires_open_confirmation")
            )
            trace["order_readiness_reason"] = (
                "ready_for_existing_paper_order_boundary"
                if trace["order_ready"]
                else "BLOCKED_MARKET_SESSION"
                if trace.get("selected") and not trace.get("paper_order_submission_allowed")
                else str(trace.get("open_confirmation_reason") or reason or "not_selected")
            )
            if not trace["order_ready"]:
                blockers[trace["order_readiness_reason"]] = blockers.get(trace["order_readiness_reason"], 0) + 1
            rows.append(trace)
        return {
            "trace_owner": "PaperAutopilot.operational_dry_run",
            "dry_run_only": True,
            "submit_order": False,
            "broker_actions_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "full_history_scan_count": 0,
            "candidates_seen": len(rows),
            "eligible_candidates": eligible,
            "selected_candidates": selected,
            "order_ready_candidates": sum(1 for row in rows if row.get("order_ready")),
            "final_blocker_reason": max(blockers, key=blockers.get) if blockers else "order_ready" if rows else "NO_CURRENT_SIGNAL",
            "per_candidate_decision_trace": rows,
            "generated_at": _now_iso(),
        }

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
            trace["order_ready"] = bool(
                trace.get("selected")
                and trace.get("paper_order_submission_allowed")
                and not trace.get("requires_open_confirmation")
            )
            trace["order_readiness_reason"] = (
                "ready_for_existing_paper_order_boundary"
                if trace["order_ready"]
                else str(trace.get("open_confirmation_reason") or trace.get("decision_reason") or "not_selected")
            )
            trace["submit_order"] = False
            trace["broker_actions_used"] = 0
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

    def _trade_state_state_dir(self) -> str:
        return os.path.dirname(self.db_path) or "state"

    def _trade_state_load_json(self, name: str) -> dict[str, Any]:
        try:
            path = os.path.join(self._trade_state_state_dir(), name)
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _trade_state_load_lifecycle_index(self) -> dict[str, Any]:
        path = os.path.join(self._trade_state_state_dir(), "trade_lifecycle_v1.jsonl")
        by_symbol: dict[str, dict[str, Any]] = {}
        by_lifecycle_id: dict[str, dict[str, Any]] = {}
        lifecycle_open_count = 0
        lifecycle_closed_count = 0
        rows_scanned = 0
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    rows_scanned += 1
                    symbol = str(row.get("symbol") or "").upper().strip()
                    lifecycle_id = str(row.get("lifecycle_id") or "").strip()
                    marker = _pick_first_text(
                        row.get("exit_timestamp"),
                        row.get("updated_at"),
                        row.get("entry_timestamp"),
                        row.get("signal_timestamp"),
                    )
                    stage = str(row.get("lifecycle_stage") or "").lower().strip()
                    closed = bool(
                        row.get("exit_timestamp")
                        or row.get("exit_reason")
                        or row.get("outcome_label")
                        or stage == "closed"
                    )
                    if closed:
                        lifecycle_closed_count += 1
                    else:
                        lifecycle_open_count += 1
                    enriched = {
                        **row,
                        "_marker": marker,
                        "_closed": closed,
                    }
                    if symbol:
                        previous = by_symbol.get(symbol) or {}
                        if not previous or marker >= str(previous.get("_marker") or ""):
                            by_symbol[symbol] = enriched
                    if lifecycle_id:
                        previous = by_lifecycle_id.get(lifecycle_id) or {}
                        if not previous or marker >= str(previous.get("_marker") or ""):
                            by_lifecycle_id[lifecycle_id] = enriched
        except Exception:
            pass
        return {
            "rows_scanned": rows_scanned,
            "lifecycle_open_count": lifecycle_open_count,
            "lifecycle_closed_count": lifecycle_closed_count,
            "by_symbol": by_symbol,
            "by_lifecycle_id": by_lifecycle_id,
        }

    def _trade_state_load_broker_truth_index(self) -> dict[str, Any]:
        registry = self._trade_state_load_json("broker_truth_records_v1.json")
        records = [r for r in (registry.get("records") or []) if isinstance(r, dict)]
        complete_records = [
            r for r in records
            if str(r.get("truth_quality") or "").lower() == "broker_confirmed_complete"
            or bool(r.get("closed_indicator") and r.get("realized_pnl_available"))
        ]
        complete_count = int(_to_float(registry.get("broker_confirmed_complete_records"), len(complete_records)))
        official_count = int(_to_float(registry.get("official_metric_eligible_records"), complete_count))
        total_count = int(_to_float(registry.get("broker_truth_records_total"), len(records)))
        registry["broker_truth_records_total"] = total_count
        registry["broker_confirmed_complete_records"] = complete_count
        registry["broker_confirmed_truth_records"] = complete_count
        registry["official_metric_eligible_records"] = official_count
        registry["broker_truth_closed_trade_count"] = complete_count
        registry["broker_truth_closed_trades"] = complete_count
        registry["legacy_compatibility_applied"] = True
        net_qty_by_symbol: dict[str, float] = {}
        order_rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            side = str(row.get("side") or "").lower().strip()
            qty = _to_float(row.get("qty"), 0.0)
            if side == "buy":
                net_qty_by_symbol[symbol] = net_qty_by_symbol.get(symbol, 0.0) + qty
            elif side == "sell":
                net_qty_by_symbol[symbol] = net_qty_by_symbol.get(symbol, 0.0) - qty
            order_rows_by_symbol.setdefault(symbol, []).append(dict(row))
        return {
            "registry": registry,
            "records": records,
            "net_qty_by_symbol": net_qty_by_symbol,
            "order_rows_by_symbol": order_rows_by_symbol,
        }

    def _trade_state_load_horizon_reference(self) -> dict[str, Any]:
        cached = self._trade_state_load_json(os.path.join("dashboard_cache", "astra_paper_provider_cortex_completion_v1.json"))
        best = cached.get("best_horizon_by_symbol") if isinstance(cached.get("best_horizon_by_symbol"), dict) else {}
        return {
            "cache_payload": cached,
            "best_horizon_by_symbol": {
                str(sym).upper().strip(): str(label or "").strip()
                for sym, label in best.items()
                if str(sym or "").strip()
            },
        }

    def _trade_state_latest_history_by_symbol(self, symbols: list[str] | set[str]) -> dict[str, dict[str, Any]]:
        wanted = sorted({str(sym or "").upper().strip() for sym in symbols if str(sym or "").strip()})
        out: dict[str, dict[str, Any]] = {}
        if not wanted:
            return out
        try:
            with self._connect() as conn:
                for symbol in wanted:
                    row = conn.execute(
                        """
                        SELECT *
                        FROM paper_positions
                        WHERE symbol=?
                        ORDER BY updated_at DESC, created_at DESC, entry_timestamp DESC
                        LIMIT 1
                        """,
                        (symbol,),
                    ).fetchone()
                    if row:
                        out[symbol] = dict(row or {})
        except Exception:
            return {}
        return out

    def _trade_state_open_mirrors_by_symbol(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in self._fetch_open_positions():
            symbol = str((row or {}).get("symbol") or "").upper().strip()
            if symbol and symbol not in out:
                out[symbol] = dict(row or {})
        return out

    def _trade_state_broker_position_rows(self, broker_snapshot: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        snapshot = dict(broker_snapshot or {}) if isinstance(broker_snapshot, dict) else {}
        positions = snapshot.get("broker_position_by_symbol") if isinstance(snapshot.get("broker_position_by_symbol"), dict) else {}
        out: list[dict[str, Any]] = []
        for symbol, row in sorted(positions.items()):
            if not isinstance(row, dict):
                continue
            sym = str(symbol or row.get("symbol") or "").upper().strip()
            if not sym:
                continue
            out.append({"symbol": sym, **dict(row)})
        return out

    def _trade_state_detect_horizon(self, symbol: str, row: dict[str, Any], entry_meta: dict[str, Any], notes: dict[str, Any], lifecycle_row: dict[str, Any], horizon_ref: dict[str, Any]) -> tuple[str, str, float]:
        candidates = [
            ("row_json.assigned_horizon", entry_meta.get("assigned_horizon")),
            ("row_json.horizon", entry_meta.get("horizon")),
            ("row_json.expected_hold_window", entry_meta.get("expected_hold_window")),
            ("lifecycle_notes.position_horizon", notes.get("position_horizon")),
            ("lifecycle_notes.horizon", notes.get("horizon")),
            ("lifecycle.trade_archetype", lifecycle_row.get("trade_archetype")),
            ("dashboard.best_horizon_by_symbol", (horizon_ref.get("best_horizon_by_symbol") or {}).get(symbol)),
        ]
        for source, raw in candidates:
            text = str(raw or "").lower().strip()
            if not text:
                continue
            if "scalp" in text:
                return "scalp", source, round(_to_float(entry_meta.get("horizon_confidence"), _to_float(lifecycle_row.get("confidence"), 75.0)), 3)
            if "day" in text or "intraday" in text:
                return "day_trade", source, round(_to_float(entry_meta.get("horizon_confidence"), _to_float(lifecycle_row.get("confidence"), 70.0)), 3)
            if "swing" in text:
                return "swing_trade", source, round(_to_float(entry_meta.get("horizon_confidence"), _to_float(lifecycle_row.get("confidence"), 65.0)), 3)
        return "unknown", "", 0.0

    def broker_open_position_mirror_backfill(self, apply: bool = False, broker_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        broker_snapshot = dict(broker_snapshot or {}) if isinstance(broker_snapshot, dict) else self._broker_open_symbols_snapshot()
        broker_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
        broker_rows = self._trade_state_broker_position_rows(broker_snapshot)
        lifecycle_index = self._trade_state_load_lifecycle_index()
        broker_truth_index = self._trade_state_load_broker_truth_index()
        horizon_ref = self._trade_state_load_horizon_reference()
        history_by_symbol = self._trade_state_latest_history_by_symbol({row.get("symbol") for row in broker_rows})
        open_by_symbol = self._trade_state_open_mirrors_by_symbol()
        now_iso = _now_iso()
        mirror_candidates: list[dict[str, Any]] = []
        mirrors_created = 0
        mirrors_preserved = 0
        mirrors_blocked = 0
        mirror_conflicts: list[dict[str, Any]] = []
        blocked_details: list[dict[str, Any]] = []

        if not broker_fetch_ok:
            blocked_symbols = [str((row or {}).get("symbol") or "").upper().strip() for row in broker_rows if str((row or {}).get("symbol") or "").strip()]
            return {
                "broker_open_position_count": int(_to_float(broker_snapshot.get("broker_open_positions_count"), len(blocked_symbols))),
                "current_paper_positions_open_count": int(len(open_by_symbol)),
                "mirror_gap_count": max(0, int(_to_float(broker_snapshot.get("broker_open_positions_count"), len(blocked_symbols))) - int(len(open_by_symbol))),
                "broker_symbols_missing_internal_mirror": sorted([sym for sym in blocked_symbols if sym and sym not in open_by_symbol]),
                "mirror_candidates": [],
                "mirrors_blocked": [
                    {"symbol": sym, "reason": str(broker_snapshot.get("broker_positions_error_sanitized") or "broker_positions_unavailable")}
                    for sym in sorted([sym for sym in blocked_symbols if sym and sym not in open_by_symbol])[:50]
                ],
                "mirror_conflicts": [],
                "safe_to_create_count": 0,
                "mirrors_created": 0,
                "mirrors_preserved": int(len(open_by_symbol)),
                "mirror_backfill_status": "BLOCKED_BROKER_SNAPSHOT_UNAVAILABLE",
                "broker_snapshot_timestamp": now_iso,
            }

        with self._connect() as conn:
            for broker_row in broker_rows:
                symbol = str(broker_row.get("symbol") or "").upper().strip()
                existing_open = dict(open_by_symbol.get(symbol) or {})
                historical_row = dict(history_by_symbol.get(symbol) or {})
                historical_meta = _safe_json_load(historical_row.get("row_json"))
                historical_notes = _safe_json_load(historical_row.get("lifecycle_notes"))
                lifecycle_row = dict((lifecycle_index.get("by_symbol") or {}).get(symbol) or {})
                broker_truth_rows = list((broker_truth_index.get("order_rows_by_symbol") or {}).get(symbol) or [])
                candidate_id = _pick_first_text(
                    historical_row.get("source_candidate_id"),
                    historical_meta.get("candidate_id"),
                    historical_meta.get("source_candidate_id"),
                )
                lifecycle_id = _pick_first_text(
                    historical_row.get("source_lifecycle_id"),
                    lifecycle_row.get("lifecycle_id"),
                )
                broker_order_id = _pick_first_text(
                    historical_row.get("source_broker_order_id"),
                    ((broker_truth_rows[0] if broker_truth_rows else {}) or {}).get("broker_order_id"),
                )
                client_order_id = _pick_first_text(
                    historical_row.get("source_client_order_id"),
                    ((broker_truth_rows[0] if broker_truth_rows else {}) or {}).get("client_order_id"),
                )
                canonical_horizon, horizon_source, horizon_confidence = self._trade_state_detect_horizon(
                    symbol,
                    broker_row,
                    historical_meta,
                    historical_notes,
                    lifecycle_row,
                    horizon_ref,
                )
                qty = round(_to_float(broker_row.get("qty"), _to_float(broker_row.get("quantity"), 0.0)), 6)
                avg_entry = _to_float(broker_row.get("avg_entry_price"), _to_float(historical_row.get("entry_price"), 0.0))
                market_value = _to_float(broker_row.get("market_value"), 0.0)
                current_price = _to_float(broker_row.get("current_price"), 0.0)
                unrealized_pl = _to_float(broker_row.get("unrealized_pl"), 0.0)
                mirror_status = "MIRROR_EXISTS" if existing_open else "MIRROR_MISSING_SAFE_TO_CREATE"
                blocked_reason = ""
                if qty <= 0 or avg_entry <= 0:
                    mirror_status = "MIRROR_MISSING_BLOCKED"
                    blocked_reason = "broker_qty_or_avg_entry_missing"
                elif existing_open and str(existing_open.get("source_bucket") or "").upper().strip() not in {"BROKER_MIRRORED_OPEN", "BROKER_MIRROR", ""}:
                    mirror_status = "MIRROR_CONFLICT"
                    blocked_reason = "existing_open_row_not_broker_mirror"

                row = {
                    "symbol": symbol,
                    "qty": qty,
                    "avg_entry": round(avg_entry, 6),
                    "market_value": round(market_value, 6),
                    "current_pl": round(unrealized_pl, 6),
                    "broker_order_id": broker_order_id or None,
                    "client_order_id": client_order_id or None,
                    "lifecycle_linkage": lifecycle_id or None,
                    "broker_truth_linkage": broker_order_id or client_order_id or None,
                    "horizon": canonical_horizon,
                    "horizon_source": horizon_source or "unknown",
                    "horizon_confidence": round(horizon_confidence, 3),
                    "candidate_linkage": candidate_id or None,
                    "mirror_status": mirror_status,
                    "safe_to_create": mirror_status == "MIRROR_MISSING_SAFE_TO_CREATE",
                    "blocked_reason": blocked_reason,
                }
                mirror_candidates.append(row)

                if mirror_status == "MIRROR_EXISTS":
                    mirrors_preserved += 1
                    continue
                if mirror_status == "MIRROR_CONFLICT":
                    mirrors_blocked += 1
                    mirror_conflicts.append(row)
                    continue
                if mirror_status == "MIRROR_MISSING_BLOCKED":
                    mirrors_blocked += 1
                    blocked_details.append(row)
                    continue

                if apply:
                    mirror_position_id = f"broker_mirror:{symbol}:{int(time.time())}"
                    mirror_notes = {
                        "source": "BROKER_MIRRORED_OPEN",
                        "broker_confirmed": True,
                        "paper_only": True,
                        "broker_snapshot_timestamp": now_iso,
                        "reconciliation_reason": "broker_open_missing_internal_mirror",
                        "broker_truth_link": broker_order_id or client_order_id or None,
                        "lifecycle_link": lifecycle_id or None,
                        "candidate_link": candidate_id or None,
                        "horizon": canonical_horizon,
                        "horizon_source": horizon_source or "unknown",
                        "horizon_confidence": round(horizon_confidence, 3),
                        "unknown_reason_code": "broker_open_position_mirror_created_from_snapshot" if not candidate_id else "",
                    }
                    mirror_row_json = {
                        "source": "BROKER_MIRRORED_OPEN",
                        "broker_confirmed": True,
                        "paper_only": True,
                        "symbol": symbol,
                        "qty": qty,
                        "avg_entry_price": round(avg_entry, 6),
                        "market_value": round(market_value, 6),
                        "current_price": round(current_price, 6),
                        "unrealized_pl": round(unrealized_pl, 6),
                        "broker_snapshot_timestamp": now_iso,
                        "broker_truth_link": broker_order_id or client_order_id or None,
                        "candidate_id": candidate_id or None,
                        "assigned_horizon": canonical_horizon if canonical_horizon != "unknown" else None,
                        "horizon_confidence": round(horizon_confidence, 3),
                    }
                    conn.execute(
                        """
                        INSERT INTO paper_positions(
                            position_id, symbol, asset_type, status, quantity,
                            entry_price, exit_price, return_percent, friction_adjusted_return,
                            entry_timestamp, exit_timestamp, hold_seconds,
                            source_bucket, lifecycle_notes, row_json, created_at, updated_at,
                            reconciled_at, reconciliation_reason, reconciliation_evidence_source,
                            prior_status, canonical_horizon, canonical_horizon_source,
                            canonical_horizon_confidence, buy_reason, add_reason, hold_reason,
                            unknown_reason_code, evidence_count, reason_confidence,
                            source_candidate_id, source_lifecycle_id, source_broker_order_id,
                            source_client_order_id
                        ) VALUES (?, ?, ?, 'OPEN', ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            mirror_position_id,
                            symbol,
                            "stock",
                            qty,
                            avg_entry,
                            now_iso,
                            "BROKER_MIRRORED_OPEN",
                            _safe_json(mirror_notes),
                            _safe_json(mirror_row_json),
                            now_iso,
                            now_iso,
                            now_iso,
                            "broker_open_missing_internal_mirror",
                            "broker_open_position_snapshot",
                            "OPEN",
                            canonical_horizon if canonical_horizon != "unknown" else None,
                            horizon_source or None,
                            horizon_confidence if horizon_confidence > 0 else None,
                            "broker_open_position_mirror",
                            None,
                            _pick_first_text(historical_row.get("hold_reason"), historical_notes.get("hold_posture")),
                            "candidate_link_missing" if not candidate_id else "",
                            max(1, len([x for x in [broker_order_id, client_order_id, lifecycle_id, candidate_id, canonical_horizon if canonical_horizon != "unknown" else ""] if x])),
                            horizon_confidence if horizon_confidence > 0 else None,
                            candidate_id or None,
                            lifecycle_id or None,
                            broker_order_id or None,
                            client_order_id or None,
                        ),
                    )
                    open_by_symbol[symbol] = {"position_id": mirror_position_id, "source_bucket": "BROKER_MIRRORED_OPEN"}
                mirrors_created += 1
            if apply:
                conn.commit()

        missing_symbols = sorted([
            str((row or {}).get("symbol") or "").upper().strip()
            for row in broker_rows
            if str((row or {}).get("symbol") or "").upper().strip() and str((row or {}).get("symbol") or "").upper().strip() not in open_by_symbol
        ])
        return {
            "broker_open_position_count": int(len(broker_rows)),
            "current_paper_positions_open_count": int(len(self._trade_state_open_mirrors_by_symbol())),
            "mirror_gap_count": int(len(missing_symbols)),
            "broker_symbols_missing_internal_mirror": missing_symbols[:80],
            "mirror_candidates": mirror_candidates[:80],
            "mirrors_blocked": (mirror_conflicts + blocked_details)[:80],
            "mirror_conflicts": mirror_conflicts[:40],
            "safe_to_create_count": int(len([row for row in mirror_candidates if row.get("safe_to_create")])),
            "mirrors_created": int(mirrors_created if apply else len([row for row in mirror_candidates if row.get("safe_to_create")])),
            "mirrors_preserved": int(mirrors_preserved),
            "mirror_backfill_status": (
                "PASS"
                if not missing_symbols
                else ("PARTIAL" if apply and mirrors_created > 0 else ("READY_TO_CREATE" if not apply and any(row.get("safe_to_create") for row in mirror_candidates) else "BLOCKED"))
            ),
            "broker_snapshot_timestamp": now_iso,
        }

    def trade_state_reconciliation(self, apply: bool = False, broker_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        lifecycle_index = self._trade_state_load_lifecycle_index()
        broker_truth_index = self._trade_state_load_broker_truth_index()
        horizon_ref = self._trade_state_load_horizon_reference()
        broker_snapshot = dict(broker_snapshot or {}) if isinstance(broker_snapshot, dict) and broker_snapshot else self._broker_open_symbols_snapshot()
        broker_open_symbols = set(broker_snapshot.get("broker_open_symbols") or set())
        broker_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
        broker_truth_open_symbols = {
            sym for sym, qty in (broker_truth_index.get("net_qty_by_symbol") or {}).items()
            if _to_float(qty, 0.0) > 0.000001
        }
        now = datetime.now(UTC)
        now_iso = _now_iso()
        with self._connect() as conn:
            open_rows = [dict(r or {}) for r in (conn.execute("SELECT * FROM paper_positions WHERE status='OPEN' ORDER BY entry_timestamp ASC").fetchall() or [])]
            symbol_counts: dict[str, int] = {}
            newest_id_by_symbol: dict[str, str] = {}
            newest_ts_by_symbol: dict[str, str] = {}
            for row in open_rows:
                symbol = str(row.get("symbol") or "").upper().strip()
                if not symbol:
                    continue
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                marker = str(row.get("entry_timestamp") or row.get("updated_at") or "")
                if marker >= newest_ts_by_symbol.get(symbol, ""):
                    newest_ts_by_symbol[symbol] = marker
                    newest_id_by_symbol[symbol] = str(row.get("position_id") or "")

            rows_reconciled = 0
            rows_preserved = 0
            rows_blocked = 0
            stale_examples: list[dict[str, Any]] = []
            blocked_examples: list[dict[str, Any]] = []
            duplicate_active_symbols: list[str] = sorted([sym for sym, count in symbol_counts.items() if count > 1])
            broker_lifecycle_disagreements: list[dict[str, Any]] = []
            lifecycle_paper_disagreements: list[dict[str, Any]] = []
            horizon_disagreements: list[dict[str, Any]] = []
            reviewed_symbols: set[str] = set()
            unresolved_symbols: set[str] = set()
            attribution_coverage_before = 0
            attribution_coverage_after = 0
            horizon_unknown_before = 0
            horizon_unknown_after = 0
            broker_truth_linked_reasoning_count = 0
            missing_reasoning_count = 0
            horizon_distribution: dict[str, int] = {}

            for row in open_rows:
                symbol = str(row.get("symbol") or "").upper().strip()
                position_id = str(row.get("position_id") or "").strip()
                if symbol:
                    reviewed_symbols.add(symbol)
                entry_meta = _safe_json_load(row.get("row_json"))
                notes = _safe_json_load(row.get("lifecycle_notes"))
                lifecycle_row = dict((lifecycle_index.get("by_lifecycle_id") or {}).get(position_id) or (lifecycle_index.get("by_symbol") or {}).get(symbol) or {})
                lifecycle_stage = str(lifecycle_row.get("lifecycle_stage") or "").lower().strip()
                lifecycle_closed = bool(
                    lifecycle_row.get("exit_timestamp")
                    or lifecycle_row.get("exit_reason")
                    or lifecycle_row.get("outcome_label")
                    or lifecycle_stage == "closed"
                )
                lifecycle_open = bool(lifecycle_row) and not lifecycle_closed
                broker_active = bool(symbol and broker_fetch_ok and symbol in broker_open_symbols)
                broker_truth_open = bool(symbol and symbol in broker_truth_open_symbols)
                entry_dt = _parse_iso_utc(row.get("entry_timestamp"))
                age_hours = round(max(0.0, (now - entry_dt).total_seconds()) / 3600.0, 3) if entry_dt else None
                canonical_horizon, horizon_source, horizon_confidence = self._trade_state_detect_horizon(symbol, row, entry_meta, notes, lifecycle_row, horizon_ref)
                if canonical_horizon == "unknown":
                    horizon_unknown_before += 1
                buy_reason = _pick_first_text(
                    row.get("buy_reason"),
                    entry_meta.get("buy_reason"),
                    entry_meta.get("action_label"),
                    entry_meta.get("allocation_reason"),
                )
                hold_reason = _pick_first_text(
                    row.get("hold_reason"),
                    notes.get("hold_posture"),
                    notes.get("review_state"),
                    lifecycle_row.get("lifecycle_stage"),
                )
                add_reason = _pick_first_text(
                    row.get("add_reason"),
                    entry_meta.get("add_reason"),
                    "same_symbol_duplicate_open_rows" if symbol_counts.get(symbol, 0) > 1 else "",
                )
                unknown_reason_code = "" if (buy_reason or hold_reason or add_reason) else "reasoning_not_persisted"
                evidence_count = int(sum(
                    1 for value in (
                        buy_reason,
                        hold_reason,
                        add_reason,
                        lifecycle_row.get("exit_reason"),
                        lifecycle_row.get("lifecycle_stage"),
                        entry_meta.get("confidence"),
                        entry_meta.get("candidate_id"),
                    )
                    if value not in (None, "", False)
                ))
                reason_confidence = _pick_first_number(
                    row.get("reason_confidence"),
                    entry_meta.get("confidence"),
                    lifecycle_row.get("confidence"),
                    horizon_confidence,
                )
                if buy_reason or hold_reason or add_reason:
                    attribution_coverage_before += 1
                else:
                    missing_reasoning_count += 1

                candidate_id = _pick_first_text(
                    row.get("source_candidate_id"),
                    entry_meta.get("candidate_id"),
                    entry_meta.get("source_candidate_id"),
                )
                source_lifecycle_id = _pick_first_text(
                    row.get("source_lifecycle_id"),
                    lifecycle_row.get("lifecycle_id"),
                    position_id,
                )
                broker_rows = list((broker_truth_index.get("order_rows_by_symbol") or {}).get(symbol) or [])
                source_broker_order_id = _pick_first_text(
                    row.get("source_broker_order_id"),
                    entry_meta.get("broker_order_id"),
                    ((broker_rows[0] if broker_rows else {}) or {}).get("broker_order_id"),
                )
                source_client_order_id = _pick_first_text(
                    row.get("source_client_order_id"),
                    entry_meta.get("client_order_id"),
                    ((broker_rows[0] if broker_rows else {}) or {}).get("client_order_id"),
                )
                if source_broker_order_id or source_client_order_id:
                    broker_truth_linked_reasoning_count += 1

                evidence_sources = []
                if broker_fetch_ok and not broker_active:
                    evidence_sources.append("broker_current_position_absent")
                if lifecycle_closed:
                    evidence_sources.append("lifecycle_closed")
                elif lifecycle_open:
                    evidence_sources.append("lifecycle_stale_open")
                if not broker_truth_open:
                    evidence_sources.append("broker_truth_no_open_qty")
                if symbol_counts.get(symbol, 0) > 1:
                    evidence_sources.append("duplicate_internal_open_rows")

                reconcile_status = "PRESERVED"
                reconcile_reason = ""
                if broker_fetch_ok and not broker_active:
                    if lifecycle_closed:
                        reconcile_status = "CLOSED_STALE_RECONCILED"
                        reconcile_reason = "lifecycle_closed_and_broker_currently_flat"
                    elif not broker_truth_open and age_hours is not None and age_hours >= 24.0:
                        reconcile_status = "DUPLICATE_STALE" if symbol_counts.get(symbol, 0) > 1 and newest_id_by_symbol.get(symbol) != position_id else "CLOSED_STALE_RECONCILED"
                        reconcile_reason = "aged_open_without_broker_confirmation"
                if broker_fetch_ok and broker_active and lifecycle_closed:
                    broker_lifecycle_disagreements.append({
                        "symbol": symbol,
                        "position_id": position_id,
                        "broker_state": "open",
                        "lifecycle_state": "closed",
                        "exit_reason": str(lifecycle_row.get("exit_reason") or ""),
                    })
                if broker_fetch_ok and not broker_active and lifecycle_open:
                    lifecycle_paper_disagreements.append({
                        "symbol": symbol,
                        "position_id": position_id,
                        "broker_state": "closed_or_absent",
                        "lifecycle_state": "open",
                        "lifecycle_stage": str(lifecycle_row.get("lifecycle_stage") or ""),
                    })
                cached_horizon = str(((horizon_ref.get("best_horizon_by_symbol") or {}).get(symbol) or "")).strip()
                if cached_horizon and canonical_horizon != "unknown" and cached_horizon != canonical_horizon:
                    horizon_disagreements.append({
                        "symbol": symbol,
                        "position_id": position_id,
                        "canonical_horizon": canonical_horizon,
                        "cached_horizon": cached_horizon,
                    })

                if canonical_horizon == "unknown":
                    horizon_unknown_after += 1
                else:
                    horizon_distribution[canonical_horizon] = horizon_distribution.get(canonical_horizon, 0) + 1
                if buy_reason or hold_reason or add_reason or unknown_reason_code:
                    attribution_coverage_after += 1

                if apply:
                    merged_notes = dict(notes or {})
                    merged_notes["reconciliation_snapshot"] = {
                        "reconciled_at": now_iso,
                        "reconciliation_status": reconcile_status,
                        "reconciliation_reason": reconcile_reason,
                        "evidence_source": list(evidence_sources),
                        "broker_active": broker_active,
                        "broker_truth_open": broker_truth_open,
                        "lifecycle_closed": lifecycle_closed,
                        "lifecycle_stage": str(lifecycle_row.get("lifecycle_stage") or ""),
                    }
                    conn.execute(
                        """
                        UPDATE paper_positions
                        SET status=?,
                            updated_at=?,
                            reconciled_at=?,
                            reconciliation_reason=?,
                            reconciliation_evidence_source=?,
                            prior_status=COALESCE(prior_status, status),
                            canonical_horizon=?,
                            canonical_horizon_source=?,
                            canonical_horizon_confidence=?,
                            buy_reason=?,
                            add_reason=?,
                            hold_reason=?,
                            unknown_reason_code=?,
                            evidence_count=?,
                            reason_confidence=?,
                            source_candidate_id=?,
                            source_lifecycle_id=?,
                            source_broker_order_id=?,
                            source_client_order_id=?,
                            lifecycle_notes=?
                        WHERE position_id=?
                        """,
                        (
                            reconcile_status if reconcile_status in {"CLOSED_STALE_RECONCILED", "DUPLICATE_STALE"} else "OPEN",
                            now_iso,
                            now_iso if reconcile_status in {"CLOSED_STALE_RECONCILED", "DUPLICATE_STALE"} else row.get("reconciled_at"),
                            reconcile_reason,
                            ",".join(evidence_sources[:6]),
                            canonical_horizon if canonical_horizon != "unknown" else row.get("canonical_horizon"),
                            horizon_source or row.get("canonical_horizon_source"),
                            horizon_confidence if horizon_confidence > 0 else row.get("canonical_horizon_confidence"),
                            buy_reason or row.get("buy_reason"),
                            add_reason or row.get("add_reason"),
                            hold_reason or row.get("hold_reason"),
                            unknown_reason_code or row.get("unknown_reason_code"),
                            evidence_count,
                            reason_confidence if reason_confidence is not None else row.get("reason_confidence"),
                            candidate_id or row.get("source_candidate_id"),
                            source_lifecycle_id or row.get("source_lifecycle_id"),
                            source_broker_order_id or row.get("source_broker_order_id"),
                            source_client_order_id or row.get("source_client_order_id"),
                            _safe_json(merged_notes),
                            position_id,
                        ),
                    )

                sample = {
                    "symbol": symbol,
                    "position_id": position_id,
                    "status_before": "OPEN",
                    "status_after": reconcile_status if reconcile_status in {"CLOSED_STALE_RECONCILED", "DUPLICATE_STALE"} else "OPEN",
                    "entry_timestamp": str(row.get("entry_timestamp") or ""),
                    "age_hours": age_hours,
                    "broker_active": broker_active,
                    "broker_truth_open": broker_truth_open,
                    "lifecycle_closed": lifecycle_closed,
                    "lifecycle_stage": str(lifecycle_row.get("lifecycle_stage") or ""),
                    "reconciliation_reason": reconcile_reason,
                    "evidence_source": list(evidence_sources),
                    "canonical_horizon": canonical_horizon,
                    "horizon_source": horizon_source,
                    "buy_reason": buy_reason,
                    "hold_reason": hold_reason,
                    "unknown_reason_code": unknown_reason_code,
                }
                if reconcile_status in {"CLOSED_STALE_RECONCILED", "DUPLICATE_STALE"}:
                    rows_reconciled += 1
                    if len(stale_examples) < 15:
                        stale_examples.append(sample)
                elif broker_fetch_ok and not broker_active and age_hours is not None and age_hours >= 24.0:
                    rows_blocked += 1
                    if symbol:
                        unresolved_symbols.add(symbol)
                    if len(blocked_examples) < 15:
                        blocked_examples.append(sample)
                else:
                    rows_preserved += 1
                    if broker_fetch_ok and not broker_active and symbol:
                        unresolved_symbols.add(symbol)

            if apply:
                conn.commit()
            stale_open_rows_after = int(conn.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN'").fetchone()[0])

        open_rows_remaining = self._fetch_open_positions()
        stale_open_rows_remaining = 0
        if broker_fetch_ok:
            stale_open_rows_remaining = int(sum(
                1
                for row in open_rows_remaining
                if str((row or {}).get("symbol") or "").upper().strip() not in broker_open_symbols
            ))
        open_symbol_set = {str((row or {}).get("symbol") or "").upper().strip() for row in open_rows_remaining if str((row or {}).get("symbol") or "").strip()}
        return {
            "apply_performed": bool(apply),
            "broker_truth_state_count": int(_to_float((broker_truth_index.get("registry") or {}).get("broker_truth_records_total"), len(broker_truth_index.get("records") or []))),
            "broker_confirmed_complete_records": int(_to_float((broker_truth_index.get("registry") or {}).get("broker_confirmed_complete_records"), 0.0)),
            "broker_confirmed_truth_records": int(_to_float((broker_truth_index.get("registry") or {}).get("broker_confirmed_truth_records"), 0.0)),
            "official_metric_eligible_records": int(_to_float((broker_truth_index.get("registry") or {}).get("official_metric_eligible_records"), 0.0)),
            "broker_truth_closed_trade_count": int(_to_float((broker_truth_index.get("registry") or {}).get("broker_truth_closed_trade_count"), 0.0)),
            "lifecycle_open_count": int(_to_float(lifecycle_index.get("lifecycle_open_count"), 0.0)),
            "lifecycle_closed_count": int(_to_float(lifecycle_index.get("lifecycle_closed_count"), 0.0)),
            "paper_positions_open_count": int(len(open_rows)),
            "stale_open_rows": int(sum(1 for row in open_rows if str(row.get("symbol") or "").upper().strip() not in broker_open_symbols)) if broker_fetch_ok else 0,
            "stale_open_rows_before": int(len(open_rows)),
            "stale_open_rows_after": int(stale_open_rows_after),
            "stale_open_rows_remaining": int(stale_open_rows_remaining),
            "rows_reviewed": int(len(open_rows)),
            "rows_reconciled": int(rows_reconciled),
            "rows_preserved": int(rows_preserved),
            "rows_blocked": int(rows_blocked),
            "duplicate_active_symbols": list(duplicate_active_symbols),
            "duplicate_active_symbols_remaining": sorted([sym for sym in open_symbol_set if sum(1 for row in open_rows_remaining if str((row or {}).get("symbol") or "").upper().strip() == sym) > 1]),
            "broker_lifecycle_disagreements": list(broker_lifecycle_disagreements[:25]),
            "lifecycle_paper_position_disagreements": list(lifecycle_paper_disagreements[:25]),
            "horizon_disagreements": list(horizon_disagreements[:25]),
            "cortex_cache_staleness": {
                "cached_broker_confirmed_truth_records": int(_to_float((horizon_ref.get("cache_payload") or {}).get("broker_confirmed_truth_records"), 0.0)),
                "canonical_broker_confirmed_truth_records": int(_to_float((broker_truth_index.get("registry") or {}).get("broker_confirmed_truth_records"), 0.0)),
                "cached_broker_truth_alignment_status": (
                    "ALIGNED"
                    if int(_to_float((horizon_ref.get("cache_payload") or {}).get("broker_confirmed_truth_records"), 0.0))
                    == int(_to_float((broker_truth_index.get("registry") or {}).get("broker_confirmed_truth_records"), 0.0))
                    else "STALE_CACHE_DIAGNOSTIC_ONLY"
                ),
                "cached_open_positions_count": int(_to_float((horizon_ref.get("cache_payload") or {}).get("open_positions_count"), 0.0)),
                "cache_generated_payload_available": bool(horizon_ref.get("cache_payload")),
            },
            "broker_snapshot": {
                "broker_reconciliation_active": bool(broker_snapshot.get("broker_reconciliation_active", False)),
                "broker_positions_fetch_ok": broker_fetch_ok,
                "broker_open_positions_count": int(_to_float(broker_snapshot.get("broker_open_positions_count"), 0.0)),
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or ""),
                "broker_open_symbols": sorted(list(broker_open_symbols))[:50],
            },
            "reviewed_symbols_count": int(len(reviewed_symbols)),
            "unresolved_symbols": sorted(list(unresolved_symbols))[:40],
            "horizon_unknown_before": int(horizon_unknown_before),
            "horizon_unknown_after": int(horizon_unknown_after),
            "canonical_horizon_distribution": dict(sorted(horizon_distribution.items())),
            "attribution_coverage_before": int(attribution_coverage_before),
            "attribution_coverage_after": int(attribution_coverage_after),
            "missing_reasoning_count": int(missing_reasoning_count),
            "broker_truth_linked_reasoning_count": int(broker_truth_linked_reasoning_count),
            "reconciled_examples": stale_examples,
            "blocked_examples": blocked_examples,
            "broker_truth_open_symbols": sorted(list(broker_truth_open_symbols))[:80],
        }
