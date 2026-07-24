from __future__ import annotations

import json
import hashlib
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from engine.candidate_execution_integrity_v1 import candidate_execution_integrity
from engine.runtime_environment import load_runtime_environment
from engine.astra_evidence_accumulation_capacity_v1 import (
    build_capacity_snapshot,
    candidate_capacity_decision,
    canonical_candidate_capacity_fact,
)
from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_swing_direct_confirmation_v1,
    build_legacy_swing_direct_evidence_coverage_v1,
    build_legacy_swing_forward_value_v1,
    build_legacy_swing_opportunity_cost_v1,
    build_legacy_swing_profit_capture_v1,
    build_legacy_swing_horizon_record_v1,
    legacy_swing_horizon_daily_contract_v1,
    build_legacy_swing_canary_pre_submit_v1,
    build_legacy_swing_required_evidence_v1,
    build_legacy_forward_baseline_v1,
    build_position_management_overlay_v1,
    build_position_resolution_inventory_v1,
    build_legacy_migration_approval_v1,
    build_legacy_migration_manifest_v1,
    legacy_migration_position_identifier_v1,
    build_position_shadow_twin_v1,
    build_unified_position_lifecycle_decision_v1,
    estimate_legacy_provisional_horizon_v1,
    evaluate_legacy_swing_canary_eligibility_v1,
    legacy_swing_canary_configuration_v1,
    legacy_swing_writer_adapter_contract_v1,
    select_legacy_swing_canary_candidate_v1,
)
from engine.astra_legacy_quarantine_v1 import (
    bounded_legacy_quarantine_review_v1,
    build_position_attribution_summary_v1,
    ensure_fail_closed_canary_control_v1,
    resolve_canonical_lifecycle_decision_v1,
    resolve_canonical_position_ownership_v1,
)
from engine.astra_loss_containment_engine_v1 import (
    load_loss_containment_state_v1,
    run_loss_containment_review_v1,
    save_loss_containment_state_v1,
)
from engine.astra_canonical_position_snapshot_v1 import (
    build_canonical_position_snapshot,
    snapshot_to_loss_containment_rows,
    snapshot_to_broker_position_by_symbol,
)
from engine.astra_position_peak_memory_v1 import (
    build_peak_memory,
    load_peak_memory,
    save_peak_memory,
)
from engine.astra_profit_protection_giveback_v1 import (
    load_profit_protection_state_v1,
    run_profit_protection_review_v1,
    save_profit_protection_state_v1,
)


_LEGACY_MIGRATION_SOURCE_COMMIT_V1 = "e1e30e0739387be274e4e717cf7c7239b42d7890"
from engine.provider_router import ProviderRouter
try:
    from engine.astra_premarket_certification_v1 import (
        build_pretrade_decision_contract,
        enrich_candidate_for_pretrade_contract,
    )
except Exception:  # pragma: no cover - a missing contract library must fail closed
    def build_pretrade_decision_contract(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "contract_status": "INVALID",
            "order_ready_allowed": False,
            "missing_required_fields": ["pretrade_contract_library"],
            "fail_closed_reason": "PRETRADE_DECISION_CONTRACT_UNAVAILABLE",
        }

    def enrich_candidate_for_pretrade_contract(row: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return dict(row or {})

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
        natural_paper_trade_label,
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

    def natural_paper_trade_label(_row: dict[str, Any]) -> str:
        return ""

try:
    from engine.astra_multilane_market_hours_audit_v1 import MarketHoursAuditRegistry
except Exception:  # pragma: no cover - audit persistence must never affect execution
    MarketHoursAuditRegistry = None  # type: ignore[assignment]

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


def _entry_price_pct_difference(provisional: Any, canonical: Any) -> float | None:
    provisional_value = _to_float(provisional, 0.0)
    canonical_value = _to_float(canonical, 0.0)
    if provisional_value <= 0.0 or canonical_value <= 0.0:
        return None
    return round(abs(canonical_value - provisional_value) / provisional_value * 100.0, 6)


def _broker_order_payloads_v1(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized order containers without accepting non-broker prices."""
    raw = dict(result or {})
    payloads: list[dict[str, Any]] = []
    for candidate in (raw, raw.get("order"), raw.get("broker_order"), raw.get("data")):
        if isinstance(candidate, dict):
            payload = dict(candidate)
            if payload not in payloads:
                payloads.append(payload)
    return payloads


def resolve_canonical_entry_price_lineage_v1(
    *,
    symbol: Any,
    provisional_entry_price: Any,
    candidate_entry_price: Any = None,
    broker_order_result: dict[str, Any] | None = None,
    broker_position: dict[str, Any] | None = None,
    expected_broker_order_id: Any = None,
    expected_client_order_id: Any = None,
    paper_broker_context: bool = True,
) -> dict[str, Any]:
    """Resolve entry-price evidence without inferring a fill from a quote.

    Position-average fallback requires explicit order/client lineage.  Matching
    only by symbol would silently pair unrelated lots and is intentionally not
    accepted as broker truth.
    """
    normalized_symbol = str(symbol or "").upper().strip()
    provisional = _to_float(provisional_entry_price, 0.0)
    candidate = _to_float(candidate_entry_price, 0.0)
    expected_order = str(expected_broker_order_id or "").strip()
    expected_client = str(expected_client_order_id or "").strip()
    base = {
        "canonical_entry_price": None,
        "provisional_entry_price": provisional if provisional > 0.0 else None,
        "broker_filled_avg_price": None,
        "entry_price_source": "ENTRY_PRICE_UNAVAILABLE",
        "entry_price_evidence_class": "ENTRY_PRICE_UNAVAILABLE",
        "entry_price_verified": False,
        "entry_price_provisional": False,
        "entry_price_lineage_status": "ENTRY_PRICE_UNAVAILABLE",
        "entry_price_lineage_reason": "no_valid_submission_or_broker_fill_price",
        "entry_order_id": expected_order,
        "source_client_order_id": expected_client,
        "entry_fill_id": "",
        "entry_filled_at": "",
        "entry_slippage_pct": None,
        "entry_price_mismatch_pct": None,
        "entry_price_mismatch_over_5pct": False,
        "entry_price_mismatch_over_20pct": False,
        "entry_price_mismatch_over_50pct": False,
    }
    for order in _broker_order_payloads_v1(broker_order_result):
        status = str(order.get("status") or order.get("order_status") or "").lower().strip()
        order_symbol = str(order.get("symbol") or normalized_symbol).upper().strip()
        order_id = str(order.get("id") or order.get("broker_order_id") or expected_order).strip()
        client_id = str(order.get("client_order_id") or expected_client).strip()
        paper_flag = order.get("paper_mode_verified")
        if status != "filled" or not paper_broker_context or paper_flag is False:
            continue
        if not normalized_symbol or order_symbol != normalized_symbol:
            continue
        filled_price = _to_float(order.get("filled_avg_price"), 0.0)
        if filled_price <= 0.0:
            continue
        fill_time = str(order.get("filled_at") or "").strip()
        fill_id = str(order.get("fill_id") or order.get("execution_id") or (f"{order_id}:{fill_time}" if order_id and fill_time else "")).strip()
        mismatch = _entry_price_pct_difference(provisional, filled_price)
        return {
            **base,
            "canonical_entry_price": filled_price,
            "broker_filled_avg_price": filled_price,
            "entry_price_source": "alpaca_paper_order.filled_avg_price",
            "entry_price_evidence_class": "BROKER_CONFIRMED_FILL",
            "entry_price_verified": True,
            "entry_price_lineage_status": "BROKER_CONFIRMED_FILL",
            "entry_price_lineage_reason": "filled_alpaca_paper_order_matches_symbol",
            "entry_order_id": order_id,
            "source_client_order_id": client_id,
            "entry_fill_id": fill_id,
            "entry_filled_at": fill_time,
            "entry_slippage_pct": round(((filled_price - provisional) / provisional) * 100.0, 6) if provisional > 0.0 else None,
            "entry_price_mismatch_pct": mismatch,
            "entry_price_mismatch_over_5pct": bool(mismatch is not None and mismatch > 5.0),
            "entry_price_mismatch_over_20pct": bool(mismatch is not None and mismatch > 20.0),
            "entry_price_mismatch_over_50pct": bool(mismatch is not None and mismatch > 50.0),
        }

    position = dict(broker_position or {})
    position_symbol = str(position.get("symbol") or "").upper().strip()
    position_order = str(position.get("entry_order_id") or position.get("source_broker_order_id") or position.get("broker_order_id") or "").strip()
    position_client = str(position.get("source_client_order_id") or position.get("client_order_id") or "").strip()
    linked = bool((expected_order and position_order == expected_order) or (expected_client and position_client == expected_client))
    position_paper_flag = position.get("paper_mode_verified")
    position_price = _to_float(position.get("avg_entry_price"), 0.0)
    if paper_broker_context and position_paper_flag is not False and normalized_symbol and position_symbol == normalized_symbol and linked and position_price > 0.0:
        mismatch = _entry_price_pct_difference(provisional, position_price)
        return {
            **base,
            "canonical_entry_price": position_price,
            "broker_filled_avg_price": position_price,
            "entry_price_source": "alpaca_paper_position.avg_entry_price",
            "entry_price_evidence_class": "BROKER_CONFIRMED_POSITION",
            "entry_price_verified": True,
            "entry_price_lineage_status": "BROKER_CONFIRMED_POSITION",
            "entry_price_lineage_reason": "linked_broker_position_avg_entry_price",
            "entry_order_id": expected_order or position_order,
            "source_client_order_id": expected_client or position_client,
            "entry_price_mismatch_pct": mismatch,
            "entry_price_mismatch_over_5pct": bool(mismatch is not None and mismatch > 5.0),
            "entry_price_mismatch_over_20pct": bool(mismatch is not None and mismatch > 20.0),
            "entry_price_mismatch_over_50pct": bool(mismatch is not None and mismatch > 50.0),
        }
    if provisional > 0.0:
        return {
            **base,
            "canonical_entry_price": provisional,
            "entry_price_source": "latest_submission_quote",
            "entry_price_evidence_class": "PROVISIONAL_RUNTIME_QUOTE",
            "entry_price_provisional": True,
            "entry_price_lineage_status": "PROVISIONAL_AWAITING_BROKER_FILL",
            "entry_price_lineage_reason": "broker_fill_not_confirmed_at_position_creation",
        }
    if candidate > 0.0:
        return {
            **base,
            "canonical_entry_price": candidate,
            "provisional_entry_price": candidate,
            "entry_price_source": "candidate_row_price",
            "entry_price_evidence_class": "UNVERIFIED_CANDIDATE_PRICE",
            "entry_price_provisional": True,
            "entry_price_lineage_status": "UNVERIFIED_CANDIDATE_PRICE",
            "entry_price_lineage_reason": "submission_quote_unavailable",
        }
    return base


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
    decision_id = str(r.get("decision_id") or r.get("source_decision_id") or selection_id or "").strip()
    return {
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "decision_id": decision_id,
        "candidate_source": source,
        "candidate_generated_at": generated_at,
        "source_snapshot_id": snapshot_id,
        "selection_id": selection_id,
    }


def _as_plan_list(*values: Any) -> list[str]:
    """Return bounded, non-empty operational plan items from existing evidence."""
    out: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            out.extend(str(item).strip() for item in value if str(item or "").strip())
        elif str(value or "").strip():
            out.append(str(value).strip())
    return out[:6]


def _format_percent_range(low: Any, high: Any, fallback: Any = None) -> dict[str, Any] | None:
    low_value = _pick_first_number(low, fallback)
    high_value = _pick_first_number(high, fallback)
    if low_value is None and high_value is None:
        return None
    if low_value is None:
        low_value = high_value
    if high_value is None:
        high_value = low_value
    return {
        "low_pct": round(float(low_value), 4),
        "high_pct": round(float(high_value), 4),
        "evidence_label": "PROVISIONAL",
    }


def _forward_contract_plan_from_existing_evidence(row: dict[str, Any]) -> dict[str, Any]:
    """Complete contract fields only from existing candidate evidence.

    This is deliberately a normalization bridge, not a second ranking or
    strategy engine.  It preserves the upstream score and recommendation while
    making its existing expected-return, stop, target, horizon, and evidence
    fields consumable at the pre-trade contract boundary.
    """
    r = dict(row or {})
    horizon = str(r.get("paper_entry_horizon_style") or r.get("intended_horizon") or "").strip()
    price = _pick_first_number(r.get("price"), r.get("current_price"), r.get("last_price"))
    stop = _pick_first_number(r.get("stop_loss"), r.get("trailing_stop_price"))
    target_low = _pick_first_number(r.get("expected_target_low"), r.get("target_zone_low"), r.get("target_1"))
    target_high = _pick_first_number(r.get("expected_target_high"), r.get("target_zone_high"), r.get("target_2"), r.get("stretch_target"))
    return_low = _pick_first_number(r.get("expected_return_low_pct"), r.get("expected_move_low"))
    return_high = _pick_first_number(r.get("expected_return_high_pct"), r.get("expected_move_high"))
    return_mid = _pick_first_number(r.get("expected_return_pct"), r.get("expected_move_percent"))
    if return_low is None and price and target_low:
        return_low = ((target_low - price) / price) * 100.0
    if return_high is None and price and target_high:
        return_high = ((target_high - price) / price) * 100.0
    expected_return = _format_percent_range(return_low, return_high, return_mid)
    if expected_return and _to_float(expected_return.get("high_pct"), 0.0) <= 0.0:
        # A zero-filled legacy output is absence of a forecast, not a valid
        # zero-return prediction. Leave it for the canonical risk-envelope
        # owner to fail closed or consume another existing forecast alias.
        expected_return = None
    downside_pct = ((stop - price) / price) * 100.0 if price and stop else None
    expected_downside = _format_percent_range(downside_pct, downside_pct)
    hold_days = max(1.0 / 24.0, _expected_hold_minutes(horizon) / 1440.0)
    per_day = None
    if expected_return:
        per_day = {
            "low_pct_per_day": round(float(expected_return["low_pct"]) / hold_days, 4),
            "high_pct_per_day": round(float(expected_return["high_pct"]) / hold_days, 4),
            "method": "existing_expected_return_over_existing_horizon",
            "evidence_label": "PROVISIONAL",
        }
    summary = _pick_first_text(r.get("thesis"), r.get("entry_rationale"), r.get("intelligence_summary"), r.get("summary"), r.get("ranked_reason"))
    strategy = _pick_first_text(
        r.get("strategy_archetype"), r.get("trade_archetype"), r.get("strategy_cohort"),
        r.get("detected_setup_type"), r.get("setup_type"), r.get("expected_return_method"),
    )
    ranking_score = _pick_first_number(
        r.get("ranking_score"), r.get("score"), r.get("confidence_score"), r.get("rank_score"),
        r.get("astra_composite_score"), r.get("opportunity_score_pct"), r.get("confidence"),
    )
    evidence = _as_plan_list(r.get("evidence_classes"), r.get("evidence_class"), r.get("truth_quality"))
    if not evidence and (summary or ranking_score is not None or expected_return):
        evidence = ["PROVISIONAL"]
        if r.get("expected_return_method"):
            evidence.append("RECONSTRUCTED_SUPPORTED")
    support = _as_plan_list(
        r.get("thesis_supporting_conditions"), r.get("supporting_conditions"), r.get("positive_factors"),
        r.get("ranked_reason"), r.get("expected_return_method"), r.get("context_summary"),
    )
    invalidation = _as_plan_list(r.get("thesis_invalidation_conditions"), r.get("invalidation_conditions"), r.get("what_invalidates_setup"))
    if stop is not None:
        invalidation.append(f"existing stop reference reached at {stop:.4f}")
    entry_conditions = _as_plan_list(
        r.get("entry_conditions"), r.get("entry_confirmation_conditions"), r.get("recommended_entry_mode"),
        r.get("entry_quality_summary_v2"), r.get("entry_timing_decision"),
    )
    hold_conditions = _as_plan_list(r.get("hold_conditions"), r.get("thesis_hold_conditions"), r.get("trend_state"), r.get("market_regime_alignment"))
    if horizon:
        hold_conditions.append(f"hold only within existing {horizon} plan")
    profit_protection = _as_plan_list(r.get("profit_protection_conditions"), r.get("profit_lock_conditions"))
    if target_high is not None:
        profit_protection.append(f"review existing target reference at {target_high:.4f}")
    exit_review = _as_plan_list(r.get("exit_review_conditions"), r.get("exit_conditions"), r.get("sell_reason"))
    if target_low is not None:
        exit_review.append(f"review existing target zone from {target_low:.4f}")
    controlled_loss = _as_plan_list(r.get("controlled_loss_conditions"), r.get("loss_acceptance_conditions"))
    if stop is not None:
        controlled_loss.append(f"review existing stop reference at {stop:.4f}")
    replacement = _as_plan_list(r.get("replacement_review_conditions"), r.get("replacement_conditions"), r.get("replacement_reason"))
    if not replacement:
        replacement.append("review only against current eligible comparison set")
    monitoring = _as_plan_list(r.get("monitoring_priorities"), r.get("monitoring_plan"), r.get("monitoring_conditions"), r.get("trend_state"), r.get("catalyst_context_label"), r.get("data_quality_score"))
    if not monitoring and _pick_first_text(r.get("candidate_generated_at"), r.get("generated_at"), r.get("expires_at")):
        monitoring.append("monitor existing candidate snapshot freshness before entry")
    plan = {
        "strategy_archetype": strategy,
        "trade_style": _pick_first_text(r.get("trade_style"), r.get("intended_trade_style"), horizon),
        "ranking_score": ranking_score,
        "thesis": summary,
        "thesis_supporting_conditions": support,
        "thesis_invalidation_conditions": invalidation,
        "expected_return_range": expected_return,
        "expected_downside_range": expected_downside,
        # drawdown_risk_score is a unitless ranking diagnostic. It must not be
        # relabeled as an expected percentage drawdown in the order contract.
        "expected_drawdown": _pick_first_number(r.get("expected_drawdown")),
        "expected_return_per_day_range": per_day,
        "entry_conditions": entry_conditions,
        "hold_conditions": hold_conditions,
        "profit_protection_conditions": profit_protection,
        "exit_review_conditions": exit_review,
        "controlled_loss_conditions": controlled_loss,
        "replacement_review_conditions": replacement,
        "monitoring_priorities": monitoring,
        "evidence_classes": evidence,
        "thesis_evidence_label": "PROVISIONAL" if summary else "INSUFFICIENT_EVIDENCE",
        "expected_outcome_evidence_label": "PROVISIONAL" if expected_return else "INSUFFICIENT_EVIDENCE",
    }
    return {key: value for key, value in plan.items() if value not in (None, "", [], {})}


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
    is_crypto = str(r.get("asset_class") or r.get("asset_type") or "").strip().lower() in {"crypto", "cryptocurrency"}
    horizon, horizon_source, inferred = _infer_horizon_style(r)
    # Crypto candidates must carry the worker-persisted horizon evidence.  The
    # generic compatibility default is useful for older equity rows but must
    # never silently turn a crypto observation into a day-trade contract.
    if is_crypto and str(r.get("horizon_evidence_status") or "") != "PERSISTED_CANONICAL":
        horizon, horizon_source, inferred = "", "", False
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
    # Enrichment and contract capture are owned by
    # astra_premarket_certification_v1 after this normalization boundary. That
    # keeps PaperAutopilot and certification on one evidence/preference path.
    return r


_ELIGIBILITY_GATE_MAP_V1 = {
    "candidate_freshness_not_ready": ("CANDIDATE_STALE", "MISSING_INPUT_DEFECT", "existing cached candidate producer"),
    "candidate_source_not_ready": ("CANDIDATE_STALE", "MISSING_INPUT_DEFECT", "existing cached candidate producer"),
    "no_current_cached_crypto_ranking_signal": ("CANDIDATE_STALE", "MISSING_INPUT_DEFECT", "existing cached crypto ranking producer"),
    "pretrade_decision_contract_missing_fields": ("CONTRACT_INCOMPLETE", "MISSING_INPUT_DEFECT", "pretrade decision contract"),
    "missing_symbol": ("CONTRACT_INCOMPLETE", "MISSING_INPUT_DEFECT", "candidate normalization contract"),
    "duplicate_active_position": ("DUPLICATE_EXPOSURE", "VALID_SAFETY_REJECTION", "PaperAutopilot duplicate exposure gate"),
    "cooldown_active": ("RISK_REJECTED", "VALID_SAFETY_REJECTION", "PaperAutopilot cooldown gate"),
    "max_concurrent_positions_reached": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "canonical capacity authority"),
    "max_new_positions_per_cycle_reached": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "PaperAutopilot bounded cycle gate"),
    "stock_capacity_reached": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "canonical capacity authority"),
    "crypto_capacity_reached": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "canonical capacity authority"),
    "broker_state_stale": ("CAPACITY_EXHAUSTED", "CAPACITY_AUTHORITY_DEFECT", "PaperAutopilot broker reconciliation"),
    "global_capacity_exhausted": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "canonical capacity authority"),
    "lane_reserve_exhausted": ("CAPACITY_EXHAUSTED", "VALID_SAFETY_REJECTION", "canonical capacity authority"),
    "capital_not_configured": ("CAPITAL_NOT_READY", "VALID_SAFETY_REJECTION", "existing lane capital configuration"),
    "buying_power_unavailable": ("CAPITAL_NOT_READY", "MISSING_INPUT_DEFECT", "paper broker account snapshot"),
    "buying_power_insufficient": ("CAPITAL_NOT_READY", "VALID_SAFETY_REJECTION", "paper broker account snapshot"),
    "uncertainty_extreme": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "uncertainty_high": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "uncertainty_score_high": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "eligibility_blocked": ("RANKING_BELOW_THRESHOLD", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "deployment_blocked": ("RANKING_BELOW_THRESHOLD", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "discipline_reject": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "discipline_tier_reject": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "quality_confidence_too_low": ("CONFIDENCE_BELOW_THRESHOLD", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "insufficient_positive_signals": ("RANKING_BELOW_THRESHOLD", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "high_uncertainty_not_high_quality": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "entry_commitment_below_threshold": ("CONFIDENCE_BELOW_THRESHOLD", "VALID_STRATEGY_REJECTION", "PaperAutopilot commitment gate"),
    "pretrade_decision_contract_invalid": ("CONTRACT_INCOMPLETE", "MISSING_INPUT_DEFECT", "pretrade decision contract"),
    "correlation_overload": ("RISK_REJECTED", "VALID_SAFETY_REJECTION", "portfolio diversification gate"),
    "duplicate_theme_overstack": ("DUPLICATE_EXPOSURE", "VALID_SAFETY_REJECTION", "portfolio diversification gate"),
    "poor_portfolio_fit": ("RISK_REJECTED", "VALID_STRATEGY_REJECTION", "portfolio diversification gate"),
    "concentration_pressure": ("RISK_REJECTED", "VALID_SAFETY_REJECTION", "portfolio diversification gate"),
    "crypto_scalp_shadow_only": ("HORIZON_MISSING", "VALID_STRATEGY_REJECTION", "crypto lane policy"),
}


def _eligibility_gate_code_v1(reason: Any) -> tuple[str, str, str]:
    """Classify existing gate results without changing their evaluation order."""
    raw = str(reason or "").strip().lower()
    if raw in _ELIGIBILITY_GATE_MAP_V1:
        return _ELIGIBILITY_GATE_MAP_V1[raw]
    if "session" in raw or "market_closed" in raw:
        return ("MARKET_SESSION_CLOSED", "VALID_MARKET_SESSION_WAIT", "existing market-session gate")
    if "quote" in raw:
        return ("QUOTE_MISSING", "MISSING_INPUT_DEFECT", "existing quote evidence gate")
    if "bar" in raw:
        return ("BAR_MISSING", "MISSING_INPUT_DEFECT", "existing bar evidence gate")
    if "spread" in raw:
        return ("SPREAD_TOO_WIDE", "VALID_SAFETY_REJECTION", "existing liquidity gate")
    if "volume" in raw or "liquidity" in raw:
        return ("LIQUIDITY_NOT_READY", "VALID_SAFETY_REJECTION", "existing liquidity gate")
    if "unsupported" in raw or "capability" in raw:
        return ("BROKER_ASSET_UNSUPPORTED", "VALID_SAFETY_REJECTION", "paper broker capability gate")
    if "stale" in raw or "freshness" in raw:
        return ("CANDIDATE_STALE", "STALE_INPUT_DEFECT", "existing candidate freshness gate")
    if "horizon" in raw:
        return ("HORIZON_MISSING", "INCORRECT_METADATA_DEFECT", "trade lane contract")
    if "strategy" in raw:
        return ("STRATEGY_MISSING", "INCORRECT_METADATA_DEFECT", "trade lane contract")
    if "lane" in raw:
        return ("LANE_IDENTITY_MISSING", "INCORRECT_METADATA_DEFECT", "trade lane contract")
    if "contract" in raw:
        return ("CONTRACT_INCOMPLETE", "MISSING_INPUT_DEFECT", "pretrade decision contract")
    return ("UNKNOWN_FAIL_CLOSED", "UNKNOWN_FAIL_CLOSED", "PaperAutopilot eligibility gate")


def _eligibility_gate_attribution_v1(
    row: Mapping[str, Any], *, reason: Any, allowed: bool,
    gate_meta: Mapping[str, Any] | None = None,
    activation: Mapping[str, Any] | None = None,
    session: Mapping[str, Any] | None = None,
    capacity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a complete, read-only explanation from the existing gate result."""
    candidate = dict(row or {})
    meta = dict(gate_meta or {})
    activation = dict(activation or {})
    session = dict(session or {})
    capacity = dict(capacity or {})
    code, validity, owner = _eligibility_gate_code_v1(reason)
    required = {
        "CONFIDENCE_BELOW_THRESHOLD": "existing commitment confidence/quality floor",
        "CAPACITY_EXHAUSTED": "fresh broker-authoritative capacity",
        "CONTRACT_INCOMPLETE": "complete existing pretrade decision contract",
        "CANDIDATE_STALE": "current cached candidate evidence",
        "DUPLICATE_EXPOSURE": "no broker-confirmed duplicate exposure",
        "MARKET_SESSION_CLOSED": "existing market session eligibility",
    }.get(code, "existing gate requirement")
    inputs = {
        "ranking_score": candidate.get("score") or candidate.get("ranking_score"),
        "confidence_score": candidate.get("confidence") or candidate.get("predicted_win_probability"),
        "commitment_score": meta.get("commitment_score"),
        "freshness_age_seconds": candidate.get("candidate_age_seconds") or candidate.get("quote_age_seconds"),
        "market_session": session.get("market_session_mode") or candidate.get("market_session_mode"),
        "liquidity_state": candidate.get("liquidity_state") or candidate.get("liquidity_status"),
        "spread_state": candidate.get("spread_state") or candidate.get("spread_pct"),
        "volume_state": candidate.get("volume_state") or candidate.get("volume_24h") or candidate.get("volume"),
        "capital_state": capacity.get("capacity_decision"),
        "risk_state": candidate.get("portfolio_risk_label") or candidate.get("risk_label"),
        "duplicate_exposure_state": "DUPLICATE" if candidate.get("duplicate_active_position") else "CHECKED_BY_WORKER",
        "contract_completeness_state": str((candidate.get("pretrade_decision_contract_v1") or {}).get("contract_status") or candidate.get("pretrade_decision_contract_status") or "UNKNOWN"),
        "broker_eligibility_state": activation.get("execution_enabled"),
    }
    first = {
        "code": "PASS" if allowed else code,
        "owner": "PaperAutopilot" if allowed else owner,
        "input_value": "eligible" if allowed else str(reason or "unknown"),
        "required_value": "existing gates pass" if allowed else required,
        "validity": "PASS" if allowed else validity,
    }
    downstream = [] if allowed else [first]
    for blocker in list(capacity.get("exact_blockers") or []):
        blocker_code, blocker_validity, blocker_owner = _eligibility_gate_code_v1(blocker)
        candidate_gate = {
            "code": blocker_code,
            "owner": blocker_owner,
            "input_value": str(blocker),
            "required_value": "fresh broker-authoritative capacity",
            "validity": blocker_validity,
        }
        if candidate_gate not in downstream:
            downstream.append(candidate_gate)
    return {
        "schema": "astra_eligibility_gate_attribution_v1",
        "candidate_id": str(candidate.get("candidate_id") or candidate.get("recommendation_id") or ""),
        "symbol": str(candidate.get("symbol") or "").upper(),
        "asset_class": str(candidate.get("asset_class") or candidate.get("asset_type") or ""),
        "lane": str(candidate.get("lane_id") or "").upper(),
        "etf_cohort": str(candidate.get("instrument_type") or "").upper() == "ETF",
        "strategy": str(candidate.get("strategy_archetype") or candidate.get("trade_archetype") or ""),
        "horizon": str(candidate.get("paper_entry_horizon_style") or candidate.get("trade_horizon_style") or ""),
        "generated_at": str(candidate.get("candidate_generated_at") or candidate.get("generated_at") or ""),
        "evidence_timestamp": str(candidate.get("quote_timestamp") or candidate.get("source_timestamp") or ""),
        "gate_inputs": inputs,
        "eligibility_result": "ELIGIBLE" if allowed else "REJECTED",
        "first_failing_gate": first,
        "all_failing_gates": downstream,
    }


def _execution_trace_event(row: dict[str, Any], **values: Any) -> dict[str, Any]:
    """Keep blocked candidate traces on the same canonical lineage path.

    The worker used to create abbreviated early-rejection rows.  Those rows
    were useful to an in-memory UI but could not be attributed or persisted by
    the bounded lane ledger because their lane and stable identifiers were
    absent.  This is observational-only metadata enrichment.
    """
    normalized = enrich_candidate_for_pretrade_contract(_normalize_paper_entry_bridge(row))
    normalized["pretrade_decision_contract_v1"] = build_pretrade_decision_contract(normalized)
    trace = {
        "symbol": str(normalized.get("symbol") or "").upper().strip(),
        "canonical_symbol": str(normalized.get("canonical_symbol") or "").upper().strip(),
        "asset_type": _norm_asset(normalized.get("asset_type") or normalized.get("asset_class") or "stock"),
        "asset_class": str(normalized.get("asset_class") or ""),
        "instrument_type": str(normalized.get("instrument_type") or ""),
        "asset_classification_source": str(normalized.get("asset_classification_source") or ""),
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
        "pretrade_decision_contract": dict(normalized.get("pretrade_decision_contract_v1") or {}),
        "pretrade_decision_contract_status": str((normalized.get("pretrade_decision_contract_v1") or {}).get("contract_status") or "INVALID"),
    }
    trace.update(values)
    trace["eligibility_gate_attribution_v1"] = _eligibility_gate_attribution_v1(
        normalized,
        reason=trace.get("decision_reason") or trace.get("reason"),
        allowed=bool(trace.get("eligible") or trace.get("allowed")),
        gate_meta=trace.get("gate_meta"),
        activation=trace.get("lane_activation_contract"),
        session=trace.get("session_confirmation") or trace.get("session_diag"),
        capacity=trace.get("capacity_decision") if isinstance(trace.get("capacity_decision"), Mapping) else {},
    )
    return trace


def normalize_operational_candidate(row: dict[str, Any]) -> dict[str, Any]:
    """Public, side-effect-free canonical candidate enrichment for readers."""
    return _normalize_paper_entry_bridge(row)


class PaperAutopilotEngine:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args, **kwargs):
        self.db_path = str(db_path or "state/ai_trading_memory.db")
        self.state_path = str(kwargs.get("state_path") or "state/paper_autopilot_state.json")
        self.loss_containment_state_path = str(
            kwargs.get("loss_containment_state_path")
            or os.path.join(os.path.dirname(self.state_path) or "state", "loss_containment_state_v1.json")
        )
        self.peak_memory_state_path = str(
            kwargs.get("peak_memory_state_path")
            or os.path.join(os.path.dirname(self.state_path) or "state", "position_peak_memory_v1.json")
        )
        self.profit_protection_state_path = str(
            kwargs.get("profit_protection_state_path")
            or os.path.join(os.path.dirname(self.state_path) or "state", "profit_protection_state_v1.json")
        )
        self.get_crypto_candidate_rows_fn = kwargs.get("get_crypto_candidate_rows_fn")
        # Snapshot refresh is worker-owned; API readers only consume the
        # persisted output through the existing candidate adapter.
        self.refresh_crypto_rankings_fn = kwargs.get("refresh_crypto_rankings_fn")
        self.refresh_equity_risk_envelopes_fn = kwargs.get("refresh_equity_risk_envelopes_fn")
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
        self._legacy_swing_market_broker = kwargs.get("legacy_swing_market_broker") or self.alpaca_paper_broker
        self._legacy_swing_fmp_router = kwargs.get("legacy_swing_fmp_router")
        if self._legacy_swing_fmp_router is None:
            self._legacy_swing_fmp_router = ProviderRouter()
        self._legacy_swing_fmp_fetcher = kwargs.get("legacy_swing_fmp_fetcher") or getattr(
            self._legacy_swing_fmp_router, "fetch_fmp_profile_context", None
        )
        self._legacy_swing_fmp_historical_fetcher = kwargs.get("legacy_swing_fmp_historical_fetcher") or getattr(
            self._legacy_swing_fmp_router, "fetch_fmp_historical_bars", None
        )
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
            "legacy_forward_activations": {},
            "legacy_swing_canary": {},
            # These keys mirror the durable canary bundle.  Keeping the
            # canonical market records explicit avoids a restart depending on
            # an incidental nested fallback.
            "legacy_swing_market_evidence": {},
            "legacy_swing_market_activity": {},
            "legacy_swing_exit_lifecycle": {},
            # The unified lifecycle owner persists a conservative management
            # overlay here; this is not a second position store.
            "position_resolution_reviews": {},
            # One-time approval data is persisted in the existing canonical
            # worker state, never in a parallel migration store.
            "legacy_migration_manifest_v1": {},
            "legacy_migration_approval_v1": {},
            "legacy_migration_application_v1": {},
            # Liveness is worker-owned.  Read-only endpoints consume these
            # fields and must never manufacture a heartbeat by doing broker I/O.
            "worker_generation_id": "",
            "worker_heartbeat_at": "",
            "worker_cycle_started_at": "",
            "worker_cycle_completed_at": "",
            "worker_cycle_phase": "not_started",
            "worker_cycle_count": 0,
            "worker_cycle_error": "",
            "evidence_reserve_entry_timestamps": {"DAY": [], "CRYPTO": []},
            "lane_reserve_commitments": {"DAY": {}, "CRYPTO": {}},
            "lane_reserve_commitment_stats": {
                "requested": 0, "released": 0, "expired": 0,
                "converted_to_pending_order": 0, "converted_to_open_position": 0,
            },
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
                "provisional_entry_price": "REAL",
                "broker_filled_avg_price": "REAL",
                "entry_price_source": "TEXT",
                "entry_price_evidence_class": "TEXT",
                "entry_price_verified": "INTEGER NOT NULL DEFAULT 0",
                "entry_price_provisional": "INTEGER NOT NULL DEFAULT 1",
                "entry_price_lineage_status": "TEXT",
                "entry_price_lineage_reason": "TEXT",
                "entry_filled_at": "TEXT",
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
                if isinstance(payload.get("legacy_forward_activations"), dict):
                    self._runtime_state["legacy_forward_activations"] = dict(payload.get("legacy_forward_activations") or {})
                if isinstance(payload.get("legacy_swing_canary"), dict):
                    self._runtime_state["legacy_swing_canary"] = dict(payload.get("legacy_swing_canary") or {})
                nested_canary = dict(self._runtime_state.get("legacy_swing_canary") or {})
                if isinstance(payload.get("legacy_swing_market_evidence"), dict):
                    self._runtime_state["legacy_swing_market_evidence"] = dict(payload.get("legacy_swing_market_evidence") or {})
                elif isinstance(nested_canary.get("market_records"), dict):
                    self._runtime_state["legacy_swing_market_evidence"] = dict(nested_canary.get("market_records") or {})
                if isinstance(payload.get("legacy_swing_market_activity"), dict):
                    self._runtime_state["legacy_swing_market_activity"] = dict(payload.get("legacy_swing_market_activity") or {})
                elif isinstance(nested_canary.get("market_activity"), dict):
                    self._runtime_state["legacy_swing_market_activity"] = dict(nested_canary.get("market_activity") or {})
                if isinstance(payload.get("legacy_swing_exit_lifecycle"), dict):
                    self._runtime_state["legacy_swing_exit_lifecycle"] = dict(payload.get("legacy_swing_exit_lifecycle") or {})
                if isinstance(payload.get("position_resolution_reviews"), dict):
                    self._runtime_state["position_resolution_reviews"] = dict(payload.get("position_resolution_reviews") or {})
                if isinstance(payload.get("loss_containment_state_v1"), dict):
                    self._runtime_state["loss_containment_state_v1"] = dict(payload.get("loss_containment_state_v1") or {})
                if isinstance(payload.get("profit_protection_state_v1"), dict):
                    self._runtime_state["profit_protection_state_v1"] = dict(payload.get("profit_protection_state_v1") or {})
                for key in (
                    "legacy_migration_manifest_v1",
                    "legacy_migration_approval_v1",
                    "legacy_migration_application_v1",
                ):
                    if isinstance(payload.get(key), dict):
                        self._runtime_state[key] = dict(payload.get(key) or {})
                if isinstance(payload.get("evidence_reserve_entry_timestamps"), dict):
                    self._runtime_state["evidence_reserve_entry_timestamps"] = {
                        lane: list(payload.get("evidence_reserve_entry_timestamps", {}).get(lane) or [])[-32:]
                        for lane in ("DAY", "CRYPTO")
                    }
                if isinstance(payload.get("lane_reserve_commitments"), dict):
                    self._runtime_state["lane_reserve_commitments"] = {
                        lane: dict(payload.get("lane_reserve_commitments", {}).get(lane) or {})
                        for lane in ("DAY", "CRYPTO")
                    }
                if isinstance(payload.get("lane_reserve_commitment_stats"), dict):
                    self._runtime_state["lane_reserve_commitment_stats"].update(
                        dict(payload.get("lane_reserve_commitment_stats") or {})
                    )
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
                if isinstance(payload.get("last_evidence_capacity_snapshot"), dict):
                    self._runtime_state["last_evidence_capacity_snapshot"] = dict(payload.get("last_evidence_capacity_snapshot") or {})
                if isinstance(payload.get("crypto_rankings_snapshot_v1"), dict):
                    self._runtime_state["crypto_rankings_snapshot_v1"] = dict(payload.get("crypto_rankings_snapshot_v1") or {})
                if isinstance(payload.get("equity_risk_envelopes_snapshot_v1"), dict):
                    self._runtime_state["equity_risk_envelopes_snapshot_v1"] = dict(payload.get("equity_risk_envelopes_snapshot_v1") or {})
                if isinstance(payload.get("truth_arbitration_v1"), dict):
                    self._runtime_state["truth_arbitration_v1"] = dict(payload.get("truth_arbitration_v1") or {})
                if isinstance(payload.get("system_integrity_scanner_v1"), dict):
                    self._runtime_state["system_integrity_scanner_v1"] = dict(payload.get("system_integrity_scanner_v1") or {})
                if payload.get("last_cycle_utc"):
                    self._runtime_state["last_cycle_utc"] = str(payload.get("last_cycle_utc") or "")
                for key in (
                    "worker_generation_id", "worker_heartbeat_at", "worker_cycle_started_at",
                    "worker_cycle_completed_at", "worker_cycle_phase", "worker_cycle_count", "worker_cycle_error",
                ):
                    if key in payload:
                        self._runtime_state[key] = payload.get(key)
        except Exception:
            return

    def _save_state_file(self):
        payload = {
            "autopilot_enabled": bool(getattr(self, "_enabled", False)),
            "paper_mode": self.paper_mode,
            "last_cycle_utc": self._runtime_state.get("last_cycle_utc") or "",
            "worker_generation_id": str(self._runtime_state.get("worker_generation_id") or ""),
            "worker_heartbeat_at": str(self._runtime_state.get("worker_heartbeat_at") or ""),
            "worker_cycle_started_at": str(self._runtime_state.get("worker_cycle_started_at") or ""),
            "worker_cycle_completed_at": str(self._runtime_state.get("worker_cycle_completed_at") or ""),
            "worker_cycle_phase": str(self._runtime_state.get("worker_cycle_phase") or "not_started"),
            "worker_cycle_count": _to_int(self._runtime_state.get("worker_cycle_count"), 0),
            "worker_cycle_error": str(self._runtime_state.get("worker_cycle_error") or ""),
            "last_close_by_symbol": dict(self._runtime_state.get("last_close_by_symbol") or {}),
            "learned_exit_pending_sells": dict(self._runtime_state.get("learned_exit_pending_sells") or {}),
            "learned_exit_daily": dict(self._runtime_state.get("learned_exit_daily") or {}),
            "learned_exit_rollback": dict(self._runtime_state.get("learned_exit_rollback") or {}),
            "authorized_lane_exit_pending": dict(self._runtime_state.get("authorized_lane_exit_pending") or {}),
            "legacy_forward_activations": dict(self._runtime_state.get("legacy_forward_activations") or {}),
            "legacy_swing_canary": dict(self._runtime_state.get("legacy_swing_canary") or {}),
            "legacy_swing_market_evidence": dict(self._runtime_state.get("legacy_swing_market_evidence") or {}),
            "legacy_swing_market_activity": dict(self._runtime_state.get("legacy_swing_market_activity") or {}),
            "legacy_swing_exit_lifecycle": dict(self._runtime_state.get("legacy_swing_exit_lifecycle") or {}),
            "position_resolution_reviews": dict(self._runtime_state.get("position_resolution_reviews") or {}),
            "loss_containment_state_v1": dict(self._runtime_state.get("loss_containment_state_v1") or {}),
            "profit_protection_state_v1": dict(self._runtime_state.get("profit_protection_state_v1") or {}),
            "legacy_migration_manifest_v1": dict(self._runtime_state.get("legacy_migration_manifest_v1") or {}),
            "legacy_migration_approval_v1": dict(self._runtime_state.get("legacy_migration_approval_v1") or {}),
            "legacy_migration_application_v1": dict(self._runtime_state.get("legacy_migration_application_v1") or {}),
            "evidence_reserve_entry_timestamps": {
                lane: list((self._runtime_state.get("evidence_reserve_entry_timestamps") or {}).get(lane) or [])[-32:]
                for lane in ("DAY", "CRYPTO")
            },
            "lane_reserve_commitments": {
                lane: dict((self._runtime_state.get("lane_reserve_commitments") or {}).get(lane) or {})
                for lane in ("DAY", "CRYPTO")
            },
            "lane_reserve_commitment_stats": dict(self._runtime_state.get("lane_reserve_commitment_stats") or {}),
            "adaptive_learning_capacity_policy": dict(self._adaptive_learning_capacity_policy or {}),
            "last_evidence_capacity_snapshot": dict(self._runtime_state.get("last_evidence_capacity_snapshot") or {}),
            "crypto_rankings_snapshot_v1": dict(self._runtime_state.get("crypto_rankings_snapshot_v1") or {}),
            "equity_risk_envelopes_snapshot_v1": dict(self._runtime_state.get("equity_risk_envelopes_snapshot_v1") or {}),
            "truth_arbitration_v1": dict(self._runtime_state.get("truth_arbitration_v1") or {}),
            "system_integrity_scanner_v1": dict(self._runtime_state.get("system_integrity_scanner_v1") or {}),
            "last_execution_trace": {
                **dict(self._runtime_state.get("last_execution_trace") or {}),
                "per_candidate_decision_trace": list(
                    (self._runtime_state.get("last_execution_trace") or {}).get("per_candidate_decision_trace") or []
                )[:200],
            },
        }
        try:
            temporary_path = f"{self.state_path}.{os.getpid()}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), ensure_ascii=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.state_path)
        except Exception:
            pass

    def _note_worker_progress(self, phase: str, *, error: str = "") -> None:
        """Publish in-memory progress without invoking providers or the database."""
        self._runtime_state["worker_heartbeat_at"] = _now_iso()
        self._runtime_state["worker_cycle_phase"] = str(phase or "unknown")[:96]
        if error:
            self._runtime_state["worker_cycle_error"] = str(error)[:240]

    def worker_liveness_status(self) -> dict[str, Any]:
        """Return worker-owned liveness without status-path broker reads."""
        return {
            "running": bool(getattr(self, "_thread", None) and self._thread.is_alive()),
            "worker_generation_id": str(self._runtime_state.get("worker_generation_id") or ""),
            "worker_heartbeat_at": str(self._runtime_state.get("worker_heartbeat_at") or ""),
            "worker_cycle_started_at": str(self._runtime_state.get("worker_cycle_started_at") or ""),
            "worker_cycle_completed_at": str(self._runtime_state.get("worker_cycle_completed_at") or self._runtime_state.get("last_cycle_utc") or ""),
            "worker_cycle_phase": str(self._runtime_state.get("worker_cycle_phase") or "not_started"),
            "worker_cycle_count": _to_int(self._runtime_state.get("worker_cycle_count"), 0),
            "worker_cycle_error": str(self._runtime_state.get("worker_cycle_error") or self._runtime_state.get("last_error") or ""),
            "last_cycle_utc": str(self._runtime_state.get("last_cycle_utc") or ""),
            "interval_seconds": int(getattr(self, "interval_seconds", 45)),
            "autopilot_enabled": bool(getattr(self, "_enabled", False)),
        }

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

    def _legacy_swing_canary_execution_guard(self, pre_submit: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """Fail closed before the shared writer can see an active SWING canary."""
        pre = dict(pre_submit or {})
        cfg = dict(config or {})
        safety = self._alpaca_safety_snapshot()
        state = dict(getattr(self, "_runtime_state", {}).get("legacy_swing_canary_execution") or {})
        today = datetime.now(UTC).date().isoformat()
        pending = self._authorized_lane_exit_pending_map()
        active = [row for row in pending.values() if isinstance(row, dict) and bool(row.get("legacy_swing_canary_adapter_v1"))]
        submissions = dict(state.get("submissions_by_day") or {})
        actions = set(state.get("action_ids") or [])
        clients = set(state.get("client_order_ids") or [])
        failures = []
        if not bool(cfg.get("enabled")) or bool(cfg.get("kill_switch")):
            failures.append("CANARY_DISABLED_OR_KILL_SWITCH_ACTIVE")
        if not bool(safety.get("paper_mode_verified")) or bool(safety.get("live_endpoint_detected")):
            failures.append("PAPER_ONLY_BROKER_BOUNDARY_REQUIRED")
        # Runtime isolation adds a system-health authorization independent of
        # policy configuration.  Keep pre-existing broker-boundary failures
        # first so diagnostics preserve their precise root cause.
        if str(os.getenv("ASTRA_RUNTIME_CANARY_AUTHORIZED", "0")).strip().lower() not in {"1", "true", "yes", "on"}:
            failures.append("CANARY_RUNTIME_BLOCKED_PREFLIGHT")
        if int(state.get("broker_rejections") or 0) >= int(cfg.get("rejection_limit") or 2):
            failures.append("REJECTION_LIMIT_FAIL_CLOSED")
        if len(active) >= int(cfg.get("max_active_exit_orders") or 1):
            failures.append("MAX_ACTIVE_EXIT_ORDERS_REACHED")
        if int(submissions.get(today) or 0) >= int(cfg.get("max_exit_submissions_per_day") or 1):
            failures.append("MAX_EXIT_SUBMISSIONS_PER_DAY_REACHED")
        if str(pre.get("action_id") or "") in actions or str(pre.get("client_order_id") or "") in clients:
            failures.append("DUPLICATE_IDEMPOTENCY_KEY")
        return {"approved": not failures, "failures": failures, "today": today, "active_orders": len(active), "submissions_today": int(submissions.get(today) or 0), "broker_actions": 0}

    def legacy_swing_canary_writer_pre_submit(self, pre_submit: dict[str, Any], broker_position: dict[str, Any]) -> dict[str, Any]:
        """Map the canonical disabled-canary handoff into the existing writer.

        This is intentionally a pre-submit adapter.  It always invokes the
        existing writer boundary, but the writer stops before broker submission
        while the canonical policy is disabled and its kill switch is active.
        """
        pre = dict(pre_submit or {})
        broker = dict(broker_position or {})
        config = legacy_swing_canary_configuration_v1()
        required = (
            "pre_submit_state", "policy_id", "position_id", "activation_id", "symbol", "lane",
            "classification", "action_id", "client_order_id", "idempotency_key", "proposed_quantity",
            "proposed_notional", "technical_eligibility", "governance_state", "lineage_state",
        )
        missing = [key for key in required if pre.get(key) in (None, "")]
        if (
            missing
            or pre.get("pre_submit_state") != "LEGACY_SWING_CANARY_PRE_SUBMIT_READY"
            or pre.get("policy_id") != config.get("policy_id")
            or str(pre.get("lane") or "").upper() != "SWING"
            or not bool(pre.get("technical_eligibility"))
            or pre.get("governance_state") != "PASS"
            or pre.get("lineage_state") != "COMPLETE"
        ):
            return {
                "adapter_state": "ADAPTER_MAPPING_INVALID", "writer_state": "POLICY_BLOCKED",
                "broker_submission_blocked": True, "broker_actions": 0,
                "reason": "CANONICAL_PRE_SUBMIT_FIELDS_REQUIRED", "missing_fields": missing,
            }
        expected_execution_authorization = bool(config.get("enabled")) and not bool(config.get("kill_switch"))
        if bool(pre.get("execution_authorized")) != expected_execution_authorization:
            return {
                "adapter_state": "ADAPTER_MAPPING_INVALID", "writer_state": "EXECUTION_NOT_AUTHORIZED",
                "broker_submission_blocked": True, "broker_actions": 0,
                "reason": "EXECUTION_AUTHORIZATION_DOES_NOT_MATCH_CANARY_STATE",
            }
        price = _to_float(pre.get("quote_price"), 0.0)
        available = _to_float(broker.get("qty_available"), _to_float(broker.get("qty"), _to_float(pre.get("quantity_available"), 0.0)))
        requested = _to_float(pre.get("proposed_quantity"), 0.0)
        normalized = _normalize_paper_sell_qty(requested, available, 6)
        normalized_notional = round(_to_float(normalized.get("normalized_sell_qty"), 0.0) * price, 6)
        legacy_book_notional = _to_float(pre.get("legacy_book_notional"), 0.0)
        max_book_notional = round(legacy_book_notional * _to_float(config.get("max_legacy_book_percentage_per_cycle"), 0.0), 6)
        cap_failures = []
        if normalized_notional > _to_float(config.get("max_canary_notional_usd"), 0.0):
            cap_failures.append("CANARY_NOTIONAL_LIMIT_EXCEEDED")
        if legacy_book_notional <= 0.0 or normalized_notional > max_book_notional:
            cap_failures.append("LEGACY_BOOK_PERCENTAGE_LIMIT_EXCEEDED")
        if not bool(normalized.get("sell_safe_to_submit")):
            cap_failures.append("DUST_OR_UNAVAILABLE_QUANTITY")
        if cap_failures:
            return {
                "adapter_state": "ADAPTER_MAPPING_INVALID", "writer_state": "POLICY_BLOCKED",
                "broker_submission_blocked": True, "broker_actions": 0, "reason": cap_failures[0],
                "cap_failures": cap_failures, "normalized": normalized,
            }
        guard = self._legacy_swing_canary_execution_guard(pre, config)
        if bool(config.get("enabled")) and not bool(config.get("kill_switch")) and not guard.get("approved"):
            return {
                "adapter_state": "ADAPTER_MAPPING_VALID", "writer_state": "POLICY_BLOCKED",
                "broker_submission_blocked": True, "broker_actions": 0,
                "reason": (guard.get("failures") or ["CANARY_GUARD_BLOCKED"])[0], "guard": guard,
                "normalized": normalized,
            }
        open_row = {
            "legacy_swing_canary_adapter_v1": True,
            "legacy_swing_canary_pre_submit": pre,
            "lane_id": "SWING", "symbol": str(pre.get("symbol") or "").upper(),
            "position_id": str(pre.get("position_id") or ""), "quantity": requested,
            "client_order_id": str(pre.get("client_order_id") or ""),
            "action_id": str(pre.get("action_id") or ""), "idempotency_key": str(pre.get("idempotency_key") or ""),
            "paper_only": True, "execution_authorized": bool(pre.get("execution_authorized")),
            "legacy_swing_canary_guard_approved": True,
            "legacy_book_notional": legacy_book_notional, "max_canary_notional_usd": config.get("max_canary_notional_usd"),
            "max_legacy_book_percentage_per_cycle": config.get("max_legacy_book_percentage_per_cycle"),
        }
        writer = self._submit_authorized_lane_exit(open_row, broker, str(pre.get("classification") or ""))
        if writer.get("submitted"):
            state = dict(getattr(self, "_runtime_state", {}).get("legacy_swing_canary_execution") or {})
            submissions = dict(state.get("submissions_by_day") or {})
            submissions[guard["today"]] = int(submissions.get(guard["today"]) or 0) + 1
            state.update({"submissions_by_day": submissions, "action_ids": sorted(set(state.get("action_ids") or []) | {str(pre.get("action_id") or "")}), "client_order_ids": sorted(set(state.get("client_order_ids") or []) | {str(pre.get("client_order_id") or "")})})
            self._runtime_state["legacy_swing_canary_execution"] = state
        return {
            "adapter_state": "ADAPTER_MAPPING_VALID", "writer_state": writer.get("writer_state") or "WRITER_PATH_CONNECTED",
            "writer_result": writer, "normalized": normalized, "normalized_notional": normalized_notional,
            "legacy_book_notional": legacy_book_notional, "max_legacy_book_notional": max_book_notional,
            "execution_authorized": bool(pre.get("execution_authorized")), "canary_enabled": bool(config.get("enabled")),
            "kill_switch_active": bool(config.get("kill_switch")), "broker_submission_blocked": not bool(writer.get("submitted")),
            "broker_actions": 1 if writer.get("submitted") else 0, "guard": guard,
        }

    def _authorized_lane_exit_contract(self, open_row: dict[str, Any]) -> dict[str, Any]:
        """Authorize only explicit DAY/CRYPTO owners with a real entry fill."""
        lane = str(open_row.get("lane_id") or "").upper().strip()
        if lane == "SWING" and bool(open_row.get("legacy_swing_canary_adapter_v1")):
            pre = dict(open_row.get("legacy_swing_canary_pre_submit") or {})
            config = legacy_swing_canary_configuration_v1()
            canonical = (
                pre.get("pre_submit_state") == "LEGACY_SWING_CANARY_PRE_SUBMIT_READY"
                and pre.get("policy_id") == "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1"
                and bool(pre.get("execution_authorized")) == (bool(config.get("enabled")) and not bool(config.get("kill_switch")))
                and str(open_row.get("action_id") or "") == str(pre.get("action_id") or "")
                and str(open_row.get("client_order_id") or "") == str(pre.get("client_order_id") or "")
                and str(open_row.get("idempotency_key") or "") == str(pre.get("idempotency_key") or "")
            )
            if not canonical:
                return {"authorized": False, "status": "UNRESOLVED", "reason": "LEGACY_CANARY_ADAPTER_CONTRACT_INVALID"}
            if bool(config.get("enabled")) and not bool(config.get("kill_switch")) and bool(open_row.get("legacy_swing_canary_guard_approved")):
                safety = self._alpaca_safety_snapshot()
                if not bool(safety.get("paper_mode_verified")) or bool(safety.get("live_endpoint_detected")):
                    return {"authorized": False, "status": "UNRESOLVED", "reason": "PAPER_ONLY_BROKER_BOUNDARY_REQUIRED"}
                if self.alpaca_paper_broker is None or not hasattr(self.alpaca_paper_broker, "submit_paper_order"):
                    return {"authorized": False, "status": "WORKER_UNAVAILABLE", "reason": "ALPACA_PAPER_BROKER_UNAVAILABLE"}
                return {"authorized": True, "status": "LEGACY_CANARY_AUTHORIZED", "lane_id": "SWING", "paper_mode_verified": True, "broker_live_endpoint_allowed": False, "position_owner": "LEGACY_SWING_CANARY", "exit_policy_owner": "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1"}
            return {
                "authorized": False, "status": "WRITER_PATH_CONNECTED", "reason": "EXECUTION_NOT_AUTHORIZED",
                "writer_path_connected": True, "canary_disabled": True, "kill_switch_active": True,
                "broker_submission_blocked": True, "lane_id": "SWING", "paper_mode_verified": True,
                "broker_live_endpoint_allowed": False,
            }
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
            if contract.get("writer_path_connected"):
                available = _to_float(broker_position.get("qty_available"), _to_float(broker_position.get("qty"), _to_float(open_row.get("quantity"), 0.0)))
                normalized = _normalize_paper_sell_qty(_to_float(open_row.get("quantity"), available), available, 6)
                return {
                    "ok": False, "submitted": False, "reason": "BROKER_SUBMISSION_BLOCKED",
                    "writer_state": "WRITER_PATH_CONNECTED", "canary_state": "CANARY_DISABLED",
                    "kill_switch_state": "KILL_SWITCH_ACTIVE", "execution_state": "EXECUTION_NOT_AUTHORIZED",
                    "broker_submission_blocked": True, "broker_actions": 0, "contract": contract, **normalized,
                }
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
        client_order_id = str(open_row.get("client_order_id") or f"astra-{lane.lower()}-exit-{position_id[:18] or symbol[:16]}")[:48]
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
            "submitted_at": _now_iso(), "contract": contract, "legacy_swing_canary_adapter_v1": bool(open_row.get("legacy_swing_canary_adapter_v1")), **normalized,
        }
        self._runtime_state["authorized_lane_exit_pending"] = pending_map
        return {"ok": True, "submitted": True, "pending_order_id": pending_id, "contract": contract, **normalized}

    def _record_legacy_swing_exit_broker_update(self, item: dict[str, Any], order: dict[str, Any], broker_position: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist authoritative legacy canary order/fill lineage; never infers a broker fill."""
        lifecycle = dict(self._runtime_state.get("legacy_swing_exit_lifecycle") or {})
        orders = dict(lifecycle.get("orders") or {})
        fills = dict(lifecycle.get("fills") or {})
        reconciliations = dict(lifecycle.get("reconciliations") or {})
        closures = dict(lifecycle.get("closures") or {})
        truths = dict(lifecycle.get("truths") or {})
        releases = dict(lifecycle.get("capacity_releases") or {})
        effectiveness = dict(lifecycle.get("effectiveness") or {})
        action_id = str(item.get("action_id") or item.get("legacy_swing_canary_pre_submit", {}).get("action_id") or "")
        order_id = str(order.get("id") or item.get("order_id") or "")
        status = str(order.get("status") or "UNKNOWN").upper()
        submitted_qty = _to_float(item.get("normalized_sell_qty"), _to_float(item.get("quantity"), 0.0))
        filled_qty = _to_float(order.get("filled_qty"), _to_float(order.get("filled_quantity"), 0.0))
        remaining_qty = max(0.0, submitted_qty - filled_qty)
        key = action_id or order_id
        order_record = {
            "broker_order_id": order_id, "client_order_id": item.get("client_order_id"), "action_id": action_id,
            "position_id": item.get("position_id"), "symbol": item.get("symbol"), "submitted_quantity": submitted_qty,
            "accepted_quantity": submitted_qty if status in {"ACCEPTED", "NEW", "PARTIALLY_FILLED", "FILLED"} else 0.0,
            "filled_quantity": filled_qty, "remaining_quantity": remaining_qty, "average_fill_price": _to_float(order.get("filled_avg_price"), 0.0),
            "order_status": status, "submitted_at": item.get("submitted_at"), "accepted_at": order.get("accepted_at") or order.get("submitted_at"),
            "last_update_at": _now_iso(), "filled_at": order.get("filled_at"), "rejected_at": order.get("rejected_at"),
            "canceled_at": order.get("canceled_at"), "rejection_reason": order.get("reject_reason") or order.get("reason"),
        }
        orders[key] = order_record
        terminal = status in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
        if status in {"PARTIALLY_FILLED", "FILLED"} and filled_qty > 0:
            fill_id = str(order.get("fill_id") or order.get("execution_id") or f"{order_id}:{order.get('filled_at') or filled_qty}")
            fills[fill_id] = {"fill_id": fill_id, "broker_order_id": order_id, "client_order_id": item.get("client_order_id"), "action_id": action_id,
                              "position_id": item.get("position_id"), "symbol": item.get("symbol"), "fill_timestamp": order.get("filled_at") or _now_iso(),
                              "fill_quantity": filled_qty, "fill_price": _to_float(order.get("filled_avg_price"), 0.0), "cumulative_filled_quantity": filled_qty,
                              "remaining_quantity": remaining_qty, "source": "authoritative_paper_broker_order"}
        broker_qty = _to_float((broker_position or {}).get("qty"), _to_float((broker_position or {}).get("quantity"), 0.0))
        reconciliation_state = "RECONCILED_OPEN"
        if status == "FILLED":
            reconciliation_state = "RECONCILED_CLOSED" if broker_qty <= 1e-9 else "RECONCILED_PARTIAL"
        elif status == "PARTIALLY_FILLED":
            reconciliation_state = "RECONCILED_PARTIAL"
        elif status in {"REJECTED", "CANCELED", "EXPIRED"}:
            reconciliation_state = "RECONCILED_OPEN"
        reconciliations[key] = {"reconciliation_id": f"legacy-reconciliation:{key}", "position_id": item.get("position_id"),
                                "activation_id": item.get("legacy_swing_canary_pre_submit", {}).get("activation_id"), "action_id": action_id,
                                "broker_order_id": order_id, "expected_quantity": submitted_qty, "submitted_quantity": submitted_qty,
                                "filled_quantity": filled_qty, "broker_remaining_quantity": broker_qty, "astra_position_quantity": broker_qty,
                                "reconciliation_state": reconciliation_state, "reconciliation_reason": status, "reconciled_at": _now_iso()}
        closure = None
        if reconciliation_state == "RECONCILED_CLOSED" and status == "FILLED" and filled_qty <= submitted_qty + 1e-9:
            activation_id = item.get("legacy_swing_canary_pre_submit", {}).get("activation_id")
            closure_id = f"legacy-closure:{activation_id or key}"
            closure = closures.setdefault(closure_id, {"lifecycle_closure_id": closure_id, "position_id": item.get("position_id"), "activation_id": activation_id,
                "action_id": action_id, "broker_order_id": order_id, "symbol": item.get("symbol"), "lane": "SWING", "exit_quantity": filled_qty,
                "average_exit_price": _to_float(order.get("filled_avg_price"), 0.0), "closure_state": "CLOSED_CONFIRMED", "closure_reason": "AUTHORITATIVE_BROKER_FILL_RECONCILED", "closed_at": _now_iso()})
            entry_fill_id = str(item.get("entry_fill_id") or "")
            entry_order_id = str(item.get("entry_order_id") or "")
            if entry_fill_id and entry_order_id:
                truth_id = f"legacy-truth:{closure_id}"
                truths.setdefault(truth_id, {"truth_id": truth_id, "lifecycle_closure_id": closure_id, "position_id": item.get("position_id"), "activation_id": activation_id,
                    "action_id": action_id, "broker_order_id": order_id, "symbol": item.get("symbol"), "lane": "SWING", "truth_class": "BROKER_CONFIRMED",
                    "entry_truth": entry_fill_id, "exit_truth": str(order.get("fill_id") or order_id), "quantity_truth": filled_qty, "created_at": _now_iso()})
                release_id = f"legacy-capacity:{closure_id}"
                releases.setdefault(release_id, {"capacity_release_id": release_id, "position_id": item.get("position_id"), "activation_id": activation_id,
                    "lifecycle_closure_id": closure_id, "truth_id": truth_id, "released_quantity": filled_qty,
                    "released_notional": round(filled_qty * _to_float(order.get("filled_avg_price"), 0.0), 6), "released_at": _now_iso(), "release_reason": "AUTHORITATIVE_CLOSED_BROKER_TRUTH"})
                effectiveness_id = f"legacy-effectiveness:{closure_id}"
                effectiveness.setdefault(effectiveness_id, {"effectiveness_id": effectiveness_id, "lifecycle_closure_id": closure_id, "truth_id": truth_id,
                    "position_id": item.get("position_id"), "activation_id": activation_id, "symbol": item.get("symbol"), "lane": "SWING",
                    "initial_effectiveness_state": "NEUTRAL_INITIAL_RESULT", "evaluation_pending": True,
                    "next_evaluation_at": (datetime.now(UTC) + timedelta(days=1)).isoformat().replace("+00:00", "Z")})
        lifecycle.update({"orders": orders, "fills": fills, "reconciliations": reconciliations, "closures": closures, "truths": truths, "capacity_releases": releases, "effectiveness": effectiveness, "last_updated_at": _now_iso()})
        self._runtime_state["legacy_swing_exit_lifecycle"] = lifecycle
        return {"terminal": terminal, "order_status": status, "reconciliation_state": reconciliation_state, "closure": closure, "truth_created": bool(closure and any(row.get("lifecycle_closure_id") == closure.get("lifecycle_closure_id") for row in truths.values()))}

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
            if bool(item.get("legacy_swing_canary_adapter_v1")):
                matching = [row for row in self._fetch_open_positions() if str(row.get("position_id") or "") == str(item.get("position_id") or "")]
                result = self._record_legacy_swing_exit_broker_update(item, order, matching[0] if matching else None)
                if not result.get("terminal"):
                    remaining[key] = {**item, "last_checked_at": _now_iso(), "last_order_status": order.get("status")}
                elif str(order.get("status") or "").lower() == "filled" and result.get("reconciliation_state") != "RECONCILED_CLOSED":
                    remaining[key] = {**item, "last_checked_at": _now_iso(), "last_order_status": order.get("status")}
                filled += 1 if result.get("closure") else 0
                continue
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

    def _refresh_legacy_forward_activations(self, broker_positions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Persist forward-only legacy baselines from the normal worker cycle."""
        registry = dict(self._runtime_state.get("legacy_forward_activations") or {})
        created = reused = 0
        for symbol, raw in broker_positions.items():
            row = dict(raw or {})
            row.setdefault("symbol", symbol)
            key = str(row.get("asset_id") or row.get("position_id") or symbol).upper()
            if not key:
                continue
            if key in registry:
                registry[key]["last_observed_at"] = _now_iso()
                reused += 1
                continue
            row["legacy_activation_timestamp"] = _now_iso()
            baseline = build_legacy_forward_baseline_v1(row)
            if baseline.get("baseline_state") == "NOT_APPLICABLE":
                continue
            horizon = estimate_legacy_provisional_horizon_v1(row, baseline)
            twin = build_position_shadow_twin_v1(row, baseline, horizon)
            registry[key] = {**baseline, "activation_id": baseline.get("baseline_id"), "provisional_horizon": horizon, "shadow_twin": twin, "created_at": _now_iso(), "last_observed_at": _now_iso(), "registry_version": 1}
            created += 1
        self._runtime_state["legacy_forward_activations"] = registry
        return {"ACTIVATION_WORKER_CALLED": True, "ACTIVATION_RECORD_CREATED": created, "ACTIVATION_RECORD_REUSED": reused, "records": len(registry)}

    @staticmethod
    def _legacy_swing_fmp_is_current(record: dict[str, Any], now: datetime) -> bool:
        if str(record.get("response_state") or "").upper() != "SUCCESS":
            return False
        try:
            value = str(record.get("as_of") or record.get("response_at") or "").replace("Z", "+00:00")
            observed = datetime.fromisoformat(value).astimezone(UTC)
        except (TypeError, ValueError):
            return False
        return (now - observed).total_seconds() <= 6 * 60 * 60

    def _refresh_legacy_swing_fmp_evidence(self, registry: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """Refresh bounded FMP profile context from the normal non-GET worker.

        FMP supplies forward monitoring context only.  The worker retains a
        prior valid record after a failed refresh and persists every attempt as
        a secret-free activity record so diagnostics never confuse configured
        code with a consumed provider source.
        """
        now = datetime.now(UTC)
        now_iso = now.isoformat().replace("+00:00", "Z")
        records = {
            key: dict(value or {})
            for key, value in dict(self._runtime_state.get("legacy_swing_fmp_evidence") or {}).items()
            if isinstance(value, dict) and value.get("record_id") and value.get("symbol")
        }
        prior_activity = dict(self._runtime_state.get("legacy_swing_fmp_activity") or {})
        activity = {
            "schema_version": "legacy_swing_fmp_activity_v1",
            "provider": "FMP",
            "worker_owner": "PaperAutopilot._refresh_legacy_swing_fmp_evidence",
            "worker_invoked": True,
            "last_attempt_at": prior_activity.get("last_attempt_at"),
            "last_success_at": prior_activity.get("last_success_at"),
            "next_refresh_at": prior_activity.get("next_refresh_at"),
            "request_count": int(prior_activity.get("request_count") or 0),
            "success_count": int(prior_activity.get("success_count") or 0),
            "failure_count": int(prior_activity.get("failure_count") or 0),
            "retry_count": int(prior_activity.get("retry_count") or 0),
            "latest_endpoint_family": prior_activity.get("latest_endpoint_family") or "company_profile",
            "latest_error_category": prior_activity.get("latest_error_category") or "",
            "symbols_requiring_fmp": 0,
            "symbols_requested": [],
            "requests_attempted_this_cycle": 0,
            "requests_succeeded_this_cycle": 0,
            "requests_failed_this_cycle": 0,
            "max_symbols_per_cycle": 5,
            "broker_actions": 0,
        }
        attempted = 0
        for activation_id, raw in sorted(registry.items()):
            record = dict(raw or {})
            symbol = str(record.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            previous = dict(records.get(activation_id) or {})
            if self._legacy_swing_fmp_is_current(previous, now):
                continue
            activity["symbols_requiring_fmp"] += 1
            retry_at = str(previous.get("next_retry_at") or "")
            if retry_at:
                try:
                    if datetime.fromisoformat(retry_at.replace("Z", "+00:00")).astimezone(UTC) > now:
                        continue
                except (TypeError, ValueError):
                    pass
            if attempted >= int(activity["max_symbols_per_cycle"]):
                continue
            attempted += 1
            activity["symbols_requested"].append(symbol)
            activity["requests_attempted_this_cycle"] += 1
            activity["request_count"] += 1
            activity["last_attempt_at"] = now_iso
            response = (
                dict(self._legacy_swing_fmp_fetcher(symbol) or {})
                if callable(self._legacy_swing_fmp_fetcher)
                else {"provider": "FMP", "endpoint_family": "company_profile", "symbol": symbol,
                      "response_state": "PROVIDER_UNAVAILABLE", "error_category": "fmp_client_unavailable"}
            )
            state = str(response.get("response_state") or "PROVIDER_ERROR").upper()
            success = state == "SUCCESS" and bool(response.get("normalized_fields"))
            retry_count = int(previous.get("retry_count") or 0) + (0 if success else 1)
            backoff_minutes = 60 if retry_count >= 2 else 15
            fmp_record = {
                "schema_version": "legacy_swing_fmp_evidence_v1",
                "record_id": f"legacy-fmp:company-profile:{activation_id}",
                "activity_id": f"legacy-fmp-activity:{activation_id}:{now.date().isoformat()}",
                "provider": "FMP", "endpoint_family": str(response.get("endpoint_family") or "company_profile"),
                "request_id": f"legacy-fmp-request:{activation_id}:{now.strftime('%Y%m%d%H')}",
                "symbol": symbol, "position_id": record.get("position_id") or record.get("baseline_id"),
                "activation_id": record.get("activation_id") or activation_id,
                "requested_at": response.get("requested_at") or now_iso,
                "response_at": response.get("response_at") or now_iso,
                "as_of": response.get("response_at") or now_iso,
                "http_status": int(response.get("http_status") or 0),
                "authentication_state": response.get("authentication_state") or "UNVERIFIED",
                "entitlement_state": response.get("entitlement_state") or "UNVERIFIED",
                "response_state": state,
                "records_received": int(response.get("records_received") or 0),
                "records_valid": int(response.get("records_valid") or 0),
                "records_stored": int(success),
                "freshness_state": "CURRENT" if success else "UNAVAILABLE",
                "quality_state": "VALID" if success else "INVALID",
                "normalized_fields": dict(response.get("normalized_fields") or {}),
                "error_category": str(response.get("error_category") or ""),
                "retry_count": retry_count,
                "next_retry_at": (now + timedelta(minutes=backoff_minutes)).isoformat().replace("+00:00", "Z") if not success else None,
                "last_success_at": response.get("response_at") if success else previous.get("last_success_at"),
                "consumer_acknowledged": False,
                "influence_state": "UNAVAILABLE" if not success else "NEUTRAL",
                "broker_actions": 0,
            }
            # Preserve last valid context when a refresh fails; the failed
            # attempt remains visible through activity/error metadata.
            if not success and str(previous.get("response_state") or "").upper() == "SUCCESS" and previous.get("normalized_fields"):
                fmp_record["normalized_fields"] = dict(previous.get("normalized_fields") or {})
                fmp_record["freshness_state"] = "STALE"
                fmp_record["quality_state"] = "STALE_PRIOR_USED"
                fmp_record["response_state"] = "STALE_PRIOR_USED"
            records[activation_id] = fmp_record
            record["fmp_evidence"] = fmp_record
            registry[activation_id] = record
            activity["latest_endpoint_family"] = fmp_record["endpoint_family"]
            activity["latest_error_category"] = fmp_record["error_category"]
            if success:
                activity["success_count"] += 1
                activity["requests_succeeded_this_cycle"] += 1
                activity["last_success_at"] = fmp_record["response_at"]
                activity["next_refresh_at"] = (now + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
            else:
                activity["failure_count"] += 1
                activity["requests_failed_this_cycle"] += 1
                activity["retry_count"] = retry_count
                activity["next_refresh_at"] = fmp_record["next_retry_at"]
        self._runtime_state["legacy_swing_fmp_evidence"] = records
        self._runtime_state["legacy_swing_fmp_activity"] = activity
        return records, activity

    @staticmethod
    def _legacy_swing_market_record_current(record: dict[str, Any], now: datetime, max_age_seconds: int) -> bool:
        if str(record.get("response_state") or "").upper() != "SUCCESS" or str(record.get("freshness_state") or "").upper() != "CURRENT":
            return False
        family = str(record.get("request_family") or "").upper()
        quality = str(record.get("quality_state") or "").upper()
        if family == "HISTORICAL_BARS" and str(record.get("timeframe") or "") not in {"1Hour", "1Day"}:
            return False
        if family == "HISTORICAL_BARS" and (int(record.get("records_valid") or 0) < 5 or quality in {"CURRENT_INSUFFICIENT", "STALE_INSUFFICIENT", "EMPTY", "INVALID", "PROVIDER_FAILED"}):
            return False
        if family != "HISTORICAL_BARS" and quality in {"INVALID", "INVALID_SPREAD", "EMPTY", "PROVIDER_FAILED"}:
            return False
        try:
            observed = datetime.fromisoformat(str(record.get("received_at") or "").replace("Z", "+00:00")).astimezone(UTC)
        except (TypeError, ValueError):
            return False
        return (now - observed).total_seconds() <= max_age_seconds

    @staticmethod
    def _legacy_swing_market_quality_rank(record: dict[str, Any]) -> int:
        """Return the canonical replacement rank without treating errors as evidence."""
        family = str(record.get("request_family") or "").upper()
        quality = str(record.get("quality_state") or "").upper()
        freshness = str(record.get("freshness_state") or "").upper()
        valid = int(record.get("records_valid") or 0)
        if quality == "CURRENT_SUFFICIENT":
            return 5
        if quality == "STALE_SUFFICIENT":
            return 4
        if quality == "CURRENT_INSUFFICIENT":
            return 3
        if quality == "STALE_INSUFFICIENT":
            return 2
        # Backward-compatible ranking for records written before the explicit
        # precedence schema existed.
        if str(record.get("response_state") or "").upper() == "SUCCESS":
            sufficient = valid >= 5 if family == "HISTORICAL_BARS" else valid >= 1
            if sufficient:
                return 5 if freshness == "CURRENT" else 4 if freshness == "STALE" else 0
            return 3 if freshness == "CURRENT" else 2 if freshness == "STALE" else 0
        return 0

    @classmethod
    def _legacy_swing_market_mark_stale_if_due(cls, record: dict[str, Any], now: datetime, max_age_seconds: int) -> dict[str, Any]:
        """Retain prior valid evidence, but never present it as current once expired."""
        prior = dict(record or {})
        if not prior or cls._legacy_swing_market_record_current(prior, now, max_age_seconds):
            return prior
        rank = cls._legacy_swing_market_quality_rank(prior)
        if rank == 5:
            prior["freshness_state"] = "STALE"
            prior["quality_state"] = "STALE_SUFFICIENT"
        elif rank == 3:
            prior["freshness_state"] = "STALE"
            prior["quality_state"] = "STALE_INSUFFICIENT"
        return prior

    @classmethod
    def _legacy_swing_market_prefer_record(
        cls,
        previous: dict[str, Any],
        candidate: dict[str, Any],
        now: datetime,
        max_age_seconds: int,
    ) -> dict[str, Any]:
        """Preserve a better prior record when a refresh is lower quality.

        A successful HTTP response with no/invalid bars is not newer evidence.
        The refresh attempt remains observable through source_state and the
        scheduler fields while the canonical bar lineage remains intact.
        """
        prior = cls._legacy_swing_market_mark_stale_if_due(previous, now, max_age_seconds)
        if cls._legacy_swing_market_quality_rank(prior) <= cls._legacy_swing_market_quality_rank(candidate):
            candidate["replacement_reason"] = "ACCEPTED_EQUAL_OR_HIGHER_QUALITY"
            candidate["supersedes_record_id"] = prior.get("record_id") or None
            return candidate
        preserved = dict(prior)
        preserved.update({
            "last_attempt_at": candidate.get("requested_at"),
            "latest_request_id": candidate.get("request_id"),
            "source_state": candidate.get("response_state"),
            "latest_source_error": candidate.get("source_error"),
            "http_status": candidate.get("http_status"),
            "retry_count": candidate.get("retry_count"),
            "next_refresh_at": candidate.get("next_refresh_at"),
            "replacement_reason": "LOWER_QUALITY_REJECTED_PRESERVED_PRIOR",
            "supersedes_record_id": candidate.get("record_id"),
            "records_stored": 1,
        })
        return preserved

    @staticmethod
    def _legacy_swing_daily_request_contract(now: datetime, contract: dict[str, Any]) -> dict[str, Any]:
        """Build a bounded completed-session daily request, never a default window."""
        eastern = now.astimezone(ZoneInfo("America/New_York"))
        session_complete = eastern.weekday() >= 5 or (eastern.hour, eastern.minute) >= (16, 15)
        # Before the regular close, exclude the incomplete provider daily bar.
        end_local = eastern if session_complete else eastern.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
        required = max(15, int(contract.get("minimum_completed_bars") or 15))
        preferred = max(required, int(contract.get("preferred_completed_bars") or required))
        requested_days = max(int(contract.get("minimum_calendar_lookback_days") or 31), required + 23)
        start_local = end_local - timedelta(days=requested_days)
        return {
            "start": start_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "end": end_local.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "limit": min(60, max(required + 5, preferred + 2)),
            "feed": "iex", "adjustment": "raw", "sort": "asc", "max_pages": 2,
            "requested_completed_sessions": required, "requested_calendar_days": requested_days,
            "current_session_complete": session_complete,
        }

    @staticmethod
    def _normalize_legacy_swing_bar_response(
        response: dict[str, Any], *, provider: str, family: str, activation_id: str,
        position_id: str | None, symbol: str, now: datetime, timeframe: str = "1Hour",
    ) -> dict[str, Any]:
        """Normalize one provider-native hourly batch without merging providers."""
        raw_bars = list(response.get("bars") or [])
        seen, bars = set(), []
        excluded_incomplete_daily = 0
        for item in raw_bars:
            row = dict(item or {}) if isinstance(item, dict) else {}
            timestamp = str(row.get("t") or row.get("timestamp") or row.get("date") or "")
            o = _to_float(row.get("o") or row.get("open"), 0.0)
            h = _to_float(row.get("h") or row.get("high"), 0.0)
            l = _to_float(row.get("l") or row.get("low"), 0.0)
            c = _to_float(row.get("c") or row.get("close"), 0.0)
            volume_raw = row.get("v") if row.get("v") is not None else row.get("volume")
            volume = _to_float(volume_raw, 0.0)
            if not timestamp or timestamp in seen or min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h) or volume < 0:
                continue
            seen.add(timestamp)
            try:
                local = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York"))
                # Provider timestamps identify the bar close.  A 16:00 ET
                # hourly timestamp is the completed 15:00-16:00 regular bar.
                session_type = "REGULAR_SESSION" if local.weekday() < 5 and ((local.hour > 9 or (local.hour == 9 and local.minute >= 30)) and local.hour <= 16) else "PRE_MARKET" if local.hour < 9 or (local.hour == 9 and local.minute < 30) else "AFTER_HOURS"
            except (TypeError, ValueError):
                continue
            if timeframe == "1Day":
                market_now = now.astimezone(ZoneInfo("America/New_York"))
                if local.date() == market_now.date() and market_now.weekday() < 5 and (market_now.hour, market_now.minute) < (16, 15):
                    excluded_incomplete_daily += 1
                    continue
            fingerprint = hashlib.sha256(f"{symbol}|{timeframe}|{timestamp}|{session_type}|{o:.8f}|{h:.8f}|{l:.8f}|{c:.8f}|{volume:.4f}".encode("utf-8")).hexdigest()[:24]
            bars.append({"bar_id": f"legacy-bar:{fingerprint}", "bar_fingerprint": fingerprint, "timestamp": timestamp, "session_type": session_type, "open": o, "high": h, "low": l, "close": c, "volume": volume, "provider": provider, "provider_adjustment_state": "UNKNOWN"})
        bars.sort(key=lambda item: item["timestamp"])
        # Legacy momentum is regular-session hourly evidence.  Preserve any
        # extended-hours bars in native provenance, never mix them into it.
        regular = [bar for bar in bars if bar["session_type"] == "REGULAR_SESSION"]
        usable = bars if timeframe == "1Day" else (regular if regular else bars)
        received = len(raw_bars)
        valid = len(usable)
        source_state = str(response.get("response_state") or "PROVIDER_ERROR").upper()
        if source_state == "SUCCESS" and valid:
            quality = "CURRENT_SUFFICIENT" if valid >= 5 else "CURRENT_INSUFFICIENT"
            state = "SUCCESS"
        elif source_state == "SUCCESS" and excluded_incomplete_daily == received:
            quality, state = "CURRENT_INSUFFICIENT", "SUCCESS"
        elif source_state == "EMPTY_RESPONSE" or not received:
            quality, state = "EMPTY", "EMPTY_RESPONSE"
        else:
            quality, state = "INVALID", "MALFORMED_RESPONSE"
        now_iso = now.isoformat().replace("+00:00", "Z")
        record_id = f"legacy-market:{family.lower()}:{provider.lower()}:{activation_id}"
        return {
            "schema_version": "legacy_swing_multi_provider_bar_batch_v1", "record_id": record_id,
            "request_id": str(response.get("request_id") or f"legacy-market-request:{family.lower()}:{provider.lower()}:{activation_id}:{now.strftime('%Y%m%d%H%M%S')}") ,
            "request_family": family, "provider": provider, "activation_id": activation_id, "position_id": position_id,
            "symbol": symbol, "asset_class": "equity", "lane": "SWING", "timeframe": timeframe,
            "session_scope": "REGULAR_SESSION" if regular else "DAILY_COMPLETED_BARS" if timeframe == "1Day" else "UNKNOWN_SESSION", "requested_at": response.get("requested_at") or now_iso,
            "received_at": response.get("response_at") or now_iso, "response_state": state, "source_state": source_state,
            "http_status": int(response.get("http_status") or 0), "bars": usable, "bars_received": received,
            "records_received": int(response.get("records_received") or received), "records_valid": valid,
            "records_stored": int(state == "SUCCESS" and valid > 0), "first_bar_at": usable[0]["timestamp"] if usable else None,
            "last_bar_at": usable[-1]["timestamp"] if usable else None, "lookback_start": usable[0]["timestamp"] if usable else None,
            "lookback_end": usable[-1]["timestamp"] if usable else None, "missing_intervals": [],
            "freshness_state": "CURRENT" if state == "SUCCESS" and valid else "UNAVAILABLE", "quality_state": quality,
            "source_error": str(response.get("error") or response.get("error_category") or ("incomplete_current_session_excluded" if excluded_incomplete_daily and not valid else "" if state == "SUCCESS" else state.lower()))[:180],
            "retry_count": 0, "next_refresh_at": (now + timedelta(hours=6 if quality == "CURRENT_SUFFICIENT" else 0.25)).isoformat().replace("+00:00", "Z"),
            "canonical_owner": False, "candidate_record_ids": [], "deduplicated_record_ids": [], "broker_actions": 0,
            "requested_start": response.get("requested_start"), "requested_end": response.get("requested_end"),
            "requested_limit": response.get("requested_limit"), "requested_feed": response.get("requested_feed"),
            "requested_adjustment": response.get("requested_adjustment"), "requested_sort": response.get("requested_sort"),
            "pagination_state": response.get("pagination_state") or "NOT_REQUIRED", "pages_consumed": int(response.get("pages_consumed") or 0),
            "next_page_token_present": bool(response.get("next_page_token_present")), "response_truncated": bool(response.get("response_truncated")),
            "excluded_incomplete_daily": excluded_incomplete_daily,
        }

    @staticmethod
    def _compare_legacy_swing_bar_batches(alpaca: dict[str, Any], fmp: dict[str, Any]) -> dict[str, Any]:
        """Compare only overlapping normalized bars; never choose by direction."""
        left = {str(bar.get("timestamp")): bar for bar in list(alpaca.get("bars") or [])}
        right = {str(bar.get("timestamp")): bar for bar in list(fmp.get("bars") or [])}
        overlap = sorted(set(left) & set(right))
        if not overlap:
            return {"comparison_state": "INSUFFICIENT_COMPARISON", "overlapping_bar_count": 0, "comparison_confidence": 0.0}
        variances = [abs(_to_float(left[key].get("close")) - _to_float(right[key].get("close"))) / max(0.000001, _to_float(left[key].get("close"))) for key in overlap]
        maximum = max(variances or [0.0])
        state = "PROVIDERS_AGREE" if maximum <= 0.0025 else "MINOR_ACCEPTABLE_VARIANCE" if maximum <= 0.01 else "MATERIAL_PRICE_CONFLICT"
        return {"comparison_state": state, "overlapping_bar_count": len(overlap), "price_variance_statistics": {"max_relative_variance": round(maximum, 8)}, "comparison_confidence": round(max(0.0, 1.0 - maximum), 4)}

    def _refresh_legacy_swing_broker_market_evidence(self, registry: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, Any]]:
        """Acquire bounded, read-only Alpaca market evidence in the normal worker."""
        now = datetime.now(UTC)
        now_iso = now.isoformat().replace("+00:00", "Z")
        runtime_canary = dict(self._runtime_state.get("legacy_swing_canary") or {})
        raw_store = dict(self._runtime_state.get("legacy_swing_market_evidence") or runtime_canary.get("market_records") or {})
        records: dict[str, dict[str, dict[str, Any]]] = {}
        for activation_id, raw in raw_store.items():
            bundle = dict(raw or {})
            valid = {family: dict(value or {}) for family, value in bundle.items() if family in {"HISTORICAL_BARS", "HISTORICAL_BARS_ALPACA", "HISTORICAL_BARS_FMP", "HISTORICAL_BARS_DAILY", "HISTORICAL_BARS_ROUTING", "LATEST_QUOTE", "ASSET_METADATA"} and isinstance(value, dict) and value.get("record_id")}
            for family, market_record in valid.items():
                market_record.setdefault("activation_id", activation_id)
                market_record.setdefault("position_id", (dict(registry.get(activation_id) or {})).get("position_id"))
                # Upgrade records written by the v1 worker without changing
                # their evidence payload or lineage.  Empty responses were
                # formerly represented as INVALID, which made an external
                # provider limitation look like a canonical data corruption.
                state = str(market_record.get("response_state") or "").upper()
                quality = str(market_record.get("quality_state") or "").upper()
                freshness = str(market_record.get("freshness_state") or "").upper()
                if family in {"HISTORICAL_BARS", "HISTORICAL_BARS_ALPACA", "HISTORICAL_BARS_FMP", "HISTORICAL_BARS_DAILY"}:
                    if state == "EMPTY_RESPONSE" or (
                        not list(market_record.get("bars") or [])
                        and int(market_record.get("records_received") or market_record.get("bars_received") or 0) == 0
                        and str(market_record.get("source_error") or market_record.get("latest_source_error") or "").lower() == "empty_response"
                    ):
                        market_record["quality_state"] = "EMPTY"
                        if not market_record.get("source_error"):
                            market_record["source_error"] = "empty_response"
                    elif state == "SUCCESS" and quality in {"VALID", "INSUFFICIENT"}:
                        sufficient = int(market_record.get("records_valid") or 0) >= 5
                        market_record["quality_state"] = ("CURRENT_SUFFICIENT" if sufficient else "CURRENT_INSUFFICIENT") if freshness == "CURRENT" else ("STALE_SUFFICIENT" if sufficient else "STALE_INSUFFICIENT")
                elif state == "SUCCESS" and quality == "VALID":
                    market_record["quality_state"] = "CURRENT_SUFFICIENT" if freshness == "CURRENT" else "STALE_SUFFICIENT"
            if valid:
                records[activation_id] = valid
        prior = dict(self._runtime_state.get("legacy_swing_market_activity") or runtime_canary.get("market_activity") or {})
        prior_scheduler = dict(prior.get("scheduler") or {})
        cycle_started_monotonic = time.monotonic()
        activity = {
            "schema_version": "legacy_swing_broker_market_activity_v2",
            "provider": "ALPACA_MARKET_DATA",
            "worker_owner": "PaperAutopilot._refresh_legacy_swing_broker_market_evidence",
            "worker_invoked": True,
            # The isolated runtime may temporarily reduce this existing
            # acquisition loop to one symbol under elevated host pressure.
            "max_symbols_per_cycle": min(6, max(1, int(getattr(self, "max_stocks", 6) or 6))),
            "maximum_provider_requests_per_cycle": 12,
            "maximum_pages_per_symbol": 2,
            "maximum_cycle_elapsed_seconds": 45,
            "maximum_retry_attempts_per_symbol_per_cycle": 1,
            "maximum_downstream_rebuilds_per_cycle": 3,
            "worker_cycle_id": f"legacy-market:{now.strftime('%Y%m%d%H%M%S')}",
            "started_at": now_iso,
            "last_checkpoint_at": now_iso,
            "completed_at": None,
            "elapsed_seconds": 0.0,
            "cycle_state": "REQUEST_PENDING",
            "exact_stop_reason": "",
            "symbols_attempted": [],
            "symbols_completed": [],
            "symbols_deferred": [],
            "provider_requests_this_cycle": 0,
            "pages_consumed_this_cycle": 0,
            "records_persisted_this_cycle": 0,
            "symbols_requiring": 0,
            "symbols_requested": [],
            "broker_order_actions": 0,
            "cache_hits": int(prior.get("cache_hits") or 0),
            "cache_misses": int(prior.get("cache_misses") or 0),
            "alpaca_requests_avoided": int(prior.get("alpaca_requests_avoided") or 0),
            "fmp_requests_avoided": int(prior.get("fmp_requests_avoided") or 0),
            "duplicate_requests_suppressed": int(prior.get("duplicate_requests_suppressed") or 0),
            "budget_deferred_symbols": list(prior.get("budget_deferred_symbols") or []),
            "families": {},
            "next_symbol_cursor": int(prior.get("next_symbol_cursor") or prior_scheduler.get("round_robin_cursor") or 0),
            "priority_policy": "priority_desc_starvation_boost_then_persisted_round_robin",
            "scheduler": {
                "round_robin_cursor": int(prior.get("next_symbol_cursor") or prior_scheduler.get("round_robin_cursor") or 0),
                "priority_queue": [],
                "last_processed_symbol": prior_scheduler.get("last_processed_symbol"),
                "last_cycle_at": now_iso,
                "next_cycle_at": (now + timedelta(seconds=45)).isoformat().replace("+00:00", "Z"),
                "per_symbol": dict(prior_scheduler.get("per_symbol") or {}),
                "worker_generation_id": f"paper-autopilot:{os.getpid()}",
                "worker_heartbeat_at": now_iso,
            },
        }
        for family in ("HISTORICAL_BARS", "FMP_HISTORICAL_BARS", "LATEST_QUOTE", "ASSET_METADATA"):
            old = dict((prior.get("families") or {}).get(family) or {})
            activity["families"][family] = {"request_family": family, "request_count": int(old.get("request_count") or 0), "success_count": int(old.get("success_count") or 0), "failure_count": int(old.get("failure_count") or 0), "last_attempt_at": old.get("last_attempt_at"), "last_success_at": old.get("last_success_at"), "next_refresh_at": old.get("next_refresh_at"), "latest_error_category": old.get("latest_error_category") or ""}
        broker = getattr(self, "_legacy_swing_market_broker", None)
        requested_symbols = 0
        config = {
            "HISTORICAL_BARS": ("historical_bars", 6 * 60 * 60),
            "LATEST_QUOTE": ("latest_quote", 90),
            "ASSET_METADATA": ("asset_metadata", 24 * 60 * 60),
        }
        # Rotate the bounded acquisition budget.  A lexical loop would keep
        # refreshing the first symbols whenever quote freshness expires.
        registry_items = sorted(registry.items())
        if registry_items:
            cursor = int(activity["next_symbol_cursor"]) % len(registry_items)
            rotated = [(index, activation_id, raw) for index, (activation_id, raw) in enumerate(registry_items[cursor:] + registry_items[:cursor])]
            # Priority advances deteriorating or incomplete direct evidence,
            # while starvation boosts and the persisted rotation prevent a
            # permanently high-priority set from starving later symbols.
            def scheduling_priority(item: tuple[int, str, dict[str, Any]]) -> int:
                _sequence, activation_id, raw = item
                prior_symbol = dict(activity["scheduler"]["per_symbol"].get(activation_id) or {})
                return int(dict(raw or {}).get("refresh_priority") or 0) + min(80, int(prior_symbol.get("starvation_cycles") or 0) * 20)
            ordered_items = sorted(rotated, key=lambda item: -scheduling_priority(item))
            activity["scheduler"]["priority_queue"] = [activation_id for _sequence, activation_id, _raw in ordered_items]
            # A bounded three-symbol budget needs multiple cycles to service
            # the legacy universe.  Starvation is therefore measured against
            # two complete round-robin passes, not a fixed small cycle count.
            activity["scheduler"]["starvation_cycle_limit"] = max(
                4,
                int(math.ceil(len(registry_items) / max(1, int(activity["max_symbols_per_cycle"])))) * 2,
            )
        else:
            ordered_items = []
        last_processed_original_index: int | None = None
        processed_activation_ids: set[str] = set()
        for _sequence_index, (rotated_index, activation_id, raw) in enumerate(ordered_items):
            if time.monotonic() - cycle_started_monotonic >= float(activity["maximum_cycle_elapsed_seconds"]):
                activity["cycle_state"] = "CYCLE_PARTIAL_TIME_LIMIT"
                activity["exact_stop_reason"] = "maximum_cycle_elapsed_seconds"
                break
            record = dict(raw or {})
            symbol = str(record.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            bundle = dict(records.get(activation_id) or {})
            missing = [family for family, (_method, age) in config.items() if not self._legacy_swing_market_record_current(dict(bundle.get(family) or {}), now, age)]
            # A few current hourly bars are useful short-term context, but
            # they never satisfy the independent daily SWING contract.  Keep
            # the hourly cache and refresh only the daily series when needed.
            provisional = dict(record.get("provisional_horizon") or {})
            daily_contract = legacy_swing_horizon_daily_contract_v1(provisional.get("provisional_horizon"))
            daily_record = dict(bundle.get("HISTORICAL_BARS_DAILY") or {})
            daily_current_sufficient = (
                self._legacy_swing_market_record_current(daily_record, now, config["HISTORICAL_BARS"][1])
                and daily_record.get("timeframe") == "1Day"
                and int(daily_record.get("records_valid") or 0) >= int(daily_contract["minimum_completed_bars"])
                and str(daily_record.get("quality_state") or "") == "CURRENT_SUFFICIENT"
            )
            if not daily_current_sufficient and "HISTORICAL_BARS" not in missing:
                missing.insert(0, "HISTORICAL_BARS")
            if not missing:
                activity["cache_hits"] += 1
                activity["alpaca_requests_avoided"] += 1
                activity["fmp_requests_avoided"] += 1
                continue
            activity["cache_misses"] += 1
            activity["symbols_requiring"] += 1
            if requested_symbols >= int(activity["max_symbols_per_cycle"]):
                activity["cycle_state"] = "CYCLE_PARTIAL_BUDGET"
                activity["exact_stop_reason"] = "maximum_symbols_per_cycle"
                activity["symbols_deferred"].append(symbol)
                continue
            requested_symbols += 1
            activity["symbols_attempted"].append(symbol)
            last_processed_original_index = (cursor + rotated_index) % len(registry_items)
            processed_activation_ids.add(activation_id)
            activity["symbols_requested"].append(symbol)
            for family in missing:
                if activity["provider_requests_this_cycle"] >= int(activity["maximum_provider_requests_per_cycle"]):
                    activity["cycle_state"] = "CYCLE_PARTIAL_PROVIDER_LIMIT"
                    activity["exact_stop_reason"] = "maximum_provider_requests_per_cycle"
                    activity["symbols_deferred"].append(symbol)
                    break
                method_name, _age = config[family]
                self._note_worker_progress(f"market_data:{family}:{symbol}")
                family_activity = activity["families"][family]
                historical_daily_only = family == "HISTORICAL_BARS" and self._legacy_swing_market_record_current(dict(bundle.get("HISTORICAL_BARS") or {}), now, config[family][1])
                if not historical_daily_only:
                    family_activity["request_count"] += 1
                    activity["provider_requests_this_cycle"] += 1
                    family_activity["last_attempt_at"] = now_iso
                    if broker is not None and callable(getattr(broker, method_name, None)):
                        response = dict(getattr(broker, method_name)(symbol, timeframe="1Hour", limit=20) or {}) if family == "HISTORICAL_BARS" else dict(getattr(broker, method_name)(symbol) or {})
                    else:
                        response = {"response_state": "UNSUPPORTED_ENDPOINT", "error": "broker_market_data_method_unavailable"}
                else:
                    response = {}
                if family == "HISTORICAL_BARS":
                    previous = dict(bundle.get("HISTORICAL_BARS") or {})
                    if historical_daily_only:
                        alpaca = dict(bundle.get("HISTORICAL_BARS_ALPACA") or previous)
                        fallback_required = True
                    else:
                        alpaca = self._normalize_legacy_swing_bar_response(
                            response, provider="ALPACA_MARKET_DATA", family="HISTORICAL_BARS",
                            activation_id=activation_id, position_id=record.get("position_id"), symbol=symbol, now=now,
                        )
                        alpaca["retry_count"] = int(dict(bundle.get("HISTORICAL_BARS_ALPACA") or {}).get("retry_count") or 0) + (0 if alpaca.get("quality_state") == "CURRENT_SUFFICIENT" else 1)
                        bundle["HISTORICAL_BARS_ALPACA"] = alpaca
                        fallback_required = alpaca.get("quality_state") != "CURRENT_SUFFICIENT"
                    fmp: dict[str, Any] = {}
                    daily: dict[str, Any] = {}
                    comparison: dict[str, Any] = {}
                    # The daily contract is the certified recovery path for
                    # provisional legacy-SWING horizons.  Persist it before
                    # attempting an optional FMP hourly fallback, whose
                    # provider latency must not delay canonical progress.
                    if (
                        fallback_required
                        and activity["provider_requests_this_cycle"] < int(activity["maximum_provider_requests_per_cycle"])
                        and broker is not None
                        and callable(getattr(broker, "historical_bars", None))
                    ):
                        self._note_worker_progress(f"market_data:HISTORICAL_BARS_DAILY:{symbol}")
                        provisional = dict(record.get("provisional_horizon") or {})
                        daily_contract = legacy_swing_horizon_daily_contract_v1(provisional.get("provisional_horizon"))
                        daily_request = self._legacy_swing_daily_request_contract(now, daily_contract)
                        family_activity["request_count"] += 1
                        family_activity["last_attempt_at"] = now_iso
                        daily_response = dict(broker.historical_bars(symbol, timeframe="1Day", **daily_request) or {})
                        activity["provider_requests_this_cycle"] += 1
                        daily = self._normalize_legacy_swing_bar_response(
                            daily_response, provider="ALPACA_MARKET_DATA", family="HISTORICAL_BARS",
                            activation_id=activation_id, position_id=record.get("position_id"), symbol=symbol, now=now, timeframe="1Day",
                        )
                        daily["horizon_contract"] = daily_contract
                        daily["required_completed_bars"] = daily_contract["minimum_completed_bars"]
                        daily["requested_completed_sessions"] = daily_request["requested_completed_sessions"]
                        daily["requested_calendar_days"] = daily_request["requested_calendar_days"]
                        daily["requested_session_scope"] = "REGULAR_SESSION_COMPLETED_ONLY"
                        if int(daily.get("records_valid") or 0) < int(daily_contract["minimum_completed_bars"]):
                            daily["quality_state"] = "CURRENT_INSUFFICIENT" if daily.get("freshness_state") == "CURRENT" else "STALE_INSUFFICIENT"
                        daily["momentum_contract"] = "LEGACY_SWING_DAILY"
                        bundle["HISTORICAL_BARS_DAILY"] = daily
                        activity["pages_consumed_this_cycle"] += int(daily.get("pages_consumed") or 0)
                    if (
                        fallback_required
                        and daily.get("quality_state") != "CURRENT_SUFFICIENT"
                        and activity["provider_requests_this_cycle"] < int(activity["maximum_provider_requests_per_cycle"])
                    ):
                        fallback_activity = activity["families"]["FMP_HISTORICAL_BARS"]
                        fallback_activity["request_count"] += 1
                        activity["provider_requests_this_cycle"] += 1
                        fallback_activity["last_attempt_at"] = now_iso
                        self._note_worker_progress(f"market_data:FMP_HISTORICAL_BARS:{symbol}")
                        fmp_response = (
                            dict(self._legacy_swing_fmp_historical_fetcher(symbol, timeframe="1Hour", limit=20) or {})
                            if callable(getattr(self, "_legacy_swing_fmp_historical_fetcher", None))
                            else {"response_state": "UNSUPPORTED_ENDPOINT", "error_category": "fmp_historical_client_unavailable"}
                        )
                        fmp = self._normalize_legacy_swing_bar_response(
                            fmp_response, provider="FMP_HISTORICAL_PRICES", family="HISTORICAL_BARS",
                            activation_id=activation_id, position_id=record.get("position_id"), symbol=symbol, now=now,
                        )
                        fmp["request_id"] = str(fmp_response.get("request_id") or fmp["request_id"])
                        fmp["retry_count"] = int(dict(bundle.get("HISTORICAL_BARS_FMP") or {}).get("retry_count") or 0) + (0 if fmp.get("quality_state") == "CURRENT_SUFFICIENT" else 1)
                        bundle["HISTORICAL_BARS_FMP"] = fmp
                        fallback_activity["latest_error_category"] = fmp.get("source_error") or ""
                        fallback_activity["next_refresh_at"] = fmp.get("next_refresh_at")
                        if fmp.get("quality_state") == "CURRENT_SUFFICIENT":
                            fallback_activity["success_count"] += 1; fallback_activity["last_success_at"] = now_iso
                        else:
                            fallback_activity["failure_count"] += 1
                        if str(fmp_response.get("response_state") or "").upper() == "BUDGET_BLOCKED":
                            activity["budget_deferred_symbols"] = sorted(set(activity["budget_deferred_symbols"] + [symbol]))
                        if alpaca.get("records_valid") and fmp.get("records_valid"):
                            comparison = self._compare_legacy_swing_bar_batches(alpaca, fmp)
                    selected = alpaca
                    routing_state = "ALPACA_PRIMARY_ACCEPTED"
                    if fallback_required:
                        if comparison.get("comparison_state") in {"MATERIAL_PRICE_CONFLICT", "TIMESTAMP_CONFLICT", "ADJUSTMENT_CONFLICT", "SESSION_SCOPE_CONFLICT"}:
                            selected = dict(alpaca)
                            selected.update({"quality_state": "CONFLICT_BLOCKED", "freshness_state": "UNAVAILABLE", "response_state": "CONFLICT_BLOCKED", "source_error": "material_provider_conflict"})
                            routing_state = "PROVIDER_CONFLICT_BLOCKED"
                        elif daily.get("quality_state") == "CURRENT_SUFFICIENT":
                            selected = dict(daily)
                            routing_state = "ALPACA_DAILY_FALLBACK_ACCEPTED"
                        elif fmp.get("quality_state") == "CURRENT_SUFFICIENT":
                            selected = dict(fmp)
                            routing_state = "FMP_FALLBACK_ACCEPTED"
                        elif daily.get("quality_state") == "CURRENT_INSUFFICIENT":
                            selected = dict(daily)
                            routing_state = "ALPACA_DAILY_FALLBACK_INSUFFICIENT"
                        elif alpaca.get("quality_state") == "CURRENT_INSUFFICIENT":
                            routing_state = "FMP_FALLBACK_INSUFFICIENT"
                        elif alpaca.get("quality_state") == "EMPTY":
                            routing_state = "BOTH_PROVIDERS_UNAVAILABLE"
                        else:
                            routing_state = "FMP_FALLBACK_FAILED"
                    else:
                        activity["fmp_requests_avoided"] += 1
                    selected = dict(selected)
                    selected.update({
                        "record_id": f"legacy-market:historical_bars:{activation_id}", "canonical_owner": True,
                        "canonical_provider": selected.get("provider"), "candidate_record_ids": [value.get("record_id") for value in (alpaca, daily, fmp) if value.get("record_id")],
                        "provider_comparison": comparison, "provider_comparison_state": comparison.get("comparison_state") or ("PRIMARY_INSUFFICIENT_FALLBACK_ACCEPTED" if selected.get("provider") == "FMP_HISTORICAL_PRICES" else "NOT_REQUIRED"),
                        "fallback_used": bool(selected.get("provider") == "FMP_HISTORICAL_PRICES"), "routing_state": routing_state,
                        "momentum_contract": "LEGACY_SWING_DAILY" if selected.get("timeframe") == "1Day" else "LEGACY_SWING_HOURLY",
                    })
                    canonical = self._legacy_swing_market_prefer_record(previous, selected, now, config[family][1])
                    bundle["HISTORICAL_BARS"] = canonical
                    bundle["HISTORICAL_BARS_ROUTING"] = {
                        "schema_version": "legacy_swing_bar_routing_v1", "record_id": f"legacy-market-routing:{activation_id}",
                        "routing_id": f"legacy-bar-routing:{activation_id}:{now.strftime('%Y%m%d%H')}", "symbol": symbol,
                        "position_id": record.get("position_id"), "activation_id": activation_id, "timeframe": "1Hour", "as_of": now_iso,
                        "alpaca_request_id": alpaca.get("request_id"), "alpaca_record_id": alpaca.get("record_id"), "alpaca_quality_state": alpaca.get("quality_state"),
                        "fallback_required": fallback_required, "fallback_reason": "ALPACA_NOT_CURRENT_SUFFICIENT" if fallback_required else "", "fmp_request_id": fmp.get("request_id"),
                        "fmp_record_id": fmp.get("record_id"), "fmp_quality_state": fmp.get("quality_state"), "comparison_id": f"legacy-bar-comparison:{activation_id}:{now.strftime('%Y%m%d%H')}" if comparison else None,
                        "comparison_state": comparison.get("comparison_state") or "NOT_REQUIRED", "canonical_record_id": canonical.get("record_id"), "canonical_provider": canonical.get("canonical_provider") or canonical.get("provider"),
                        "routing_state": routing_state, "routing_reason": canonical.get("replacement_reason"), "next_refresh_at": canonical.get("next_refresh_at"), "retry_count": canonical.get("retry_count") or 0,
                    }
                    family_activity["latest_error_category"] = alpaca.get("source_error") or ""
                    family_activity["next_refresh_at"] = canonical.get("next_refresh_at")
                    if alpaca.get("quality_state") == "CURRENT_SUFFICIENT":
                        family_activity["success_count"] += 1; family_activity["last_success_at"] = now_iso
                    else:
                        family_activity["failure_count"] += 1
                    continue
                state = str(response.get("response_state") or "PROVIDER_ERROR").upper()
                payload: dict[str, Any] = {}
                quality, valid_count = "INVALID", 0
                if family == "HISTORICAL_BARS" and state == "EMPTY_RESPONSE":
                    quality = "EMPTY"
                    payload = {"timeframe": "1Hour", "bars": [], "bars_received": 0, "first_bar_at": None, "last_bar_at": None, "missing_intervals": []}
                elif family == "HISTORICAL_BARS" and state == "SUCCESS":
                    seen, bars = set(), []
                    for item in list(response.get("bars") or []):
                        row = dict(item or {}) if isinstance(item, dict) else {}
                        ts = str(row.get("t") or row.get("timestamp") or "")
                        o, h, l, c, v = (_to_float(row.get("o") or row.get("open"), 0.0), _to_float(row.get("h") or row.get("high"), 0.0), _to_float(row.get("l") or row.get("low"), 0.0), _to_float(row.get("c") or row.get("close"), 0.0), _to_float(row.get("v") or row.get("volume"), 0.0))
                        if not ts or ts in seen or min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h) or v < 0:
                            continue
                        seen.add(ts); bars.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})
                    bars.sort(key=lambda item: item["timestamp"])
                    payload = {"timeframe": "1Hour", "bars": bars, "bars_received": len(list(response.get("bars") or [])), "first_bar_at": bars[0]["timestamp"] if bars else None, "last_bar_at": bars[-1]["timestamp"] if bars else None, "missing_intervals": []}
                    valid_count = len(bars)
                    raw_bar_count = len(list(response.get("bars") or []))
                    quality = "CURRENT_SUFFICIENT" if valid_count >= 5 else "CURRENT_INSUFFICIENT" if valid_count else "INVALID" if raw_bar_count else "EMPTY"
                    state = "SUCCESS" if bars else "MALFORMED_RESPONSE" if raw_bar_count else "EMPTY_RESPONSE"
                elif family == "LATEST_QUOTE" and state == "SUCCESS":
                    quote = dict(response.get("quote") or {})
                    bid, ask = _to_float(quote.get("bp") or quote.get("bid_price"), 0.0), _to_float(quote.get("ap") or quote.get("ask_price"), 0.0)
                    if bid > 0 and ask >= bid:
                        payload = {"bid": bid, "ask": ask, "mid": round((bid + ask) / 2.0, 8), "last": _to_float(quote.get("ap") or quote.get("ask_price"), 0.0), "quote_timestamp": quote.get("t") or quote.get("timestamp")}
                        valid_count, quality = 1, "CURRENT_SUFFICIENT"
                    else:
                        state, quality = "MALFORMED_RESPONSE", "INVALID_SPREAD"
                elif family == "ASSET_METADATA" and state == "SUCCESS":
                    asset = dict(response.get("asset") or {})
                    if asset.get("symbol") and str(asset.get("symbol") or "").upper() == symbol:
                        payload = {"tradable": bool(asset.get("tradable")), "fractionable": bool(asset.get("fractionable")), "shortable": asset.get("shortable"), "status": asset.get("status"), "exchange": asset.get("exchange"), "market": asset.get("asset_class")}
                        valid_count, quality = 1, "CURRENT_SUFFICIENT"
                    else:
                        state, quality = "MALFORMED_RESPONSE", "SYMBOL_MISMATCH"
                success = state == "SUCCESS" and valid_count > 0
                previous = dict(bundle.get(family) or {})
                refresh_delay = config[family][1] if quality == "CURRENT_SUFFICIENT" else 15 * 60
                source_error = str(response.get("error") or ("" if success else state.lower()))[:180]
                candidate = {"schema_version": "legacy_swing_broker_market_record_v2", "record_id": f"legacy-market:{family.lower()}:{activation_id}", "request_id": f"legacy-market-request:{family.lower()}:{activation_id}:{now.strftime('%Y%m%d%H%M%S')}", "request_family": family, "provider": "ALPACA_MARKET_DATA" if family != "ASSET_METADATA" else "ALPACA_PAPER_BROKER", "activation_id": activation_id, "position_id": record.get("position_id"), "symbol": symbol, "asset_class": "equity", "lane": "SWING", "lookback_start": payload.get("first_bar_at"), "lookback_end": payload.get("last_bar_at"), "requested_at": now_iso, "received_at": now_iso, "response_state": state, "source_state": state, "http_status": int(response.get("http_status") or 0), "records_received": int((payload.get("bars_received") or 0) if family == "HISTORICAL_BARS" else (1 if response.get("ok") else 0)), "records_valid": valid_count, "records_stored": int(success), "freshness_state": "CURRENT" if success else "UNAVAILABLE", "quality_state": quality, "source_error": source_error, "retry_count": int(previous.get("retry_count") or 0) + (0 if success else 1), "next_refresh_at": (now + timedelta(seconds=refresh_delay)).isoformat().replace("+00:00", "Z"), "replacement_reason": "INITIAL_OR_REPLACEMENT_CANDIDATE", "supersedes_record_id": previous.get("record_id") or None, **payload}
                market_record = self._legacy_swing_market_prefer_record(previous, candidate, now, config[family][1])
                bundle[family] = market_record
                family_activity["latest_error_category"] = market_record["source_error"]
                if success:
                    family_activity["success_count"] += 1; family_activity["last_success_at"] = now_iso
                else:
                    family_activity["failure_count"] += 1
                family_activity["next_refresh_at"] = market_record["next_refresh_at"]
            records[activation_id] = bundle
            # This is a scheduling acknowledgement, not evidence.  It keeps
            # an unprocessed bounded backlog visible across worker restarts.
            record["market_evidence_next_refresh_at"] = min(
                str((dict(bundle.get(family) or {})).get("next_refresh_at") or now_iso)
                for family in missing
            )
            schedule_row = dict(activity["scheduler"]["per_symbol"].get(activation_id) or {})
            schedule_row.update({
                "symbol": symbol,
                "last_attempt_at": now_iso,
                "last_success_at": now_iso if any(str(dict(bundle.get(family) or {}).get("freshness_state") or "") == "CURRENT" for family in missing) else schedule_row.get("last_success_at"),
                "next_refresh_at": record["market_evidence_next_refresh_at"],
                "retry_count": max(int(dict(bundle.get(family) or {}).get("retry_count") or 0) for family in missing),
                "starvation_cycles": 0,
            })
            activity["scheduler"]["per_symbol"][activation_id] = schedule_row
            registry[activation_id] = record
            # Persist each bounded symbol result.  A later slow provider call
            # or restart cannot discard an already validated bar batch.
            self._runtime_state["legacy_swing_market_evidence"] = records
            self._runtime_state["legacy_swing_market_activity"] = activity
            activity["symbols_completed"].append(symbol)
            activity["records_persisted_this_cycle"] += 1
            activity["last_checkpoint_at"] = _now_iso()
            activity["elapsed_seconds"] = round(time.monotonic() - cycle_started_monotonic, 3)
            if getattr(self, "state_path", None):
                self._save_state_file()
            if activity["cycle_state"] == "CYCLE_PARTIAL_PROVIDER_LIMIT":
                break
        for activation_id, raw in registry_items:
            if activation_id in processed_activation_ids:
                continue
            bundle = dict(records.get(activation_id) or {})
            if not any(not self._legacy_swing_market_record_current(dict(bundle.get(family) or {}), now, age) for family, (_method, age) in config.items()):
                continue
            schedule_row = dict(activity["scheduler"]["per_symbol"].get(activation_id) or {})
            schedule_row.update({
                "symbol": str(dict(raw or {}).get("symbol") or "").upper(),
                "starvation_cycles": int(schedule_row.get("starvation_cycles") or 0) + 1,
            })
            activity["scheduler"]["per_symbol"][activation_id] = schedule_row
        if registry_items and last_processed_original_index is not None:
            activity["next_symbol_cursor"] = (last_processed_original_index + 1) % len(registry_items)
            activity["scheduler"]["round_robin_cursor"] = activity["next_symbol_cursor"]
            activity["scheduler"]["last_processed_symbol"] = str(registry_items[last_processed_original_index][1].get("symbol") or "").upper()
        self._runtime_state["legacy_swing_market_evidence"] = records
        self._runtime_state["legacy_swing_market_activity"] = activity
        activity["elapsed_seconds"] = round(time.monotonic() - cycle_started_monotonic, 3)
        activity["completed_at"] = _now_iso()
        if not activity["cycle_state"] or activity["cycle_state"] == "REQUEST_PENDING":
            activity["cycle_state"] = "CYCLE_COMPLETE" if requested_symbols else "CYCLE_NO_DUE_WORK"
        # Cursor and deferred state must survive even a partial cycle that
        # finished immediately after its last checkpoint.
        if getattr(self, "state_path", None):
            self._save_state_file()
        return records, activity

    def _refresh_legacy_swing_canary_pre_submit(self, broker_positions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Persist disabled-canary reviews without invoking an order or writer.

        This is deliberately part of the normal PaperAutopilot worker, rather
        than a GET route.  The configuration has both an off switch and an
        active kill switch, so it records technical readiness only.
        """
        config = legacy_swing_canary_configuration_v1()
        safety = self._alpaca_safety_snapshot()
        registry = dict(self._runtime_state.get("legacy_forward_activations") or {})
        legacy_symbols = {str((dict(record or {})).get("symbol") or "").upper() for record in registry.values()}
        legacy_book_notional = sum(abs(_to_float(dict(position or {}).get("market_value"), 0.0)) for symbol, position in broker_positions.items() if str(symbol or "").upper() in legacy_symbols)
        # Market evidence persists one bounded symbol at a time.  Refresh it
        # before contextual FMP work so slow profile calls cannot delay the
        # direct historical evidence required for momentum.
        market_records, market_activity = self._refresh_legacy_swing_broker_market_evidence(registry)
        # A partial market cycle is a deliberate cooperative yield point.
        # Reuse committed FMP context rather than serializing another bounded
        # provider loop behind a due daily-bar request.
        if str(market_activity.get("cycle_state") or "").startswith("CYCLE_PARTIAL"):
            fmp_records = {
                key: dict(value or {})
                for key, value in dict(self._runtime_state.get("legacy_swing_fmp_evidence") or {}).items()
                if isinstance(value, dict)
            }
            fmp_activity = dict(self._runtime_state.get("legacy_swing_fmp_activity") or {})
        else:
            fmp_records, fmp_activity = self._refresh_legacy_swing_fmp_evidence(registry)
        reviews: dict[str, dict[str, Any]] = {}
        candidates: list[dict[str, Any]] = []
        reviewed = exit_reviews = 0
        for activation_id, persisted in registry.items():
            record = dict(persisted or {})
            symbol = str(record.get("symbol") or "").upper().strip()
            broker = dict(broker_positions.get(symbol) or {})
            if not broker:
                continue
            # Overlay immutable activation fields; the decision then consumes
            # persisted context instead of reconstructing a fictional entry.
            row = {
                **broker,
                "symbol": symbol,
                "legacy_activation_timestamp": record.get("legacy_activation_timestamp"),
                "legacy_activation_price": record.get("activation_price"),
                "legacy_activation_unrealized_return_pct": record.get("activation_unrealized_return_pct"),
                "paper_mode_verified": bool(safety.get("paper_mode_verified")),
                "live_endpoint_allowed": bool(safety.get("live_endpoint_detected")),
                "fmp_thesis_context": dict(fmp_records.get(activation_id) or record.get("fmp_evidence") or {}),
                "broker_bar_record": dict((market_records.get(activation_id) or {}).get("HISTORICAL_BARS") or {}),
                "broker_quote_record": dict((market_records.get(activation_id) or {}).get("LATEST_QUOTE") or {}),
                "broker_asset_record": dict((market_records.get(activation_id) or {}).get("ASSET_METADATA") or {}),
                "legacy_book_notional": legacy_book_notional,
            }
            if row["broker_bar_record"].get("freshness_state") == "CURRENT":
                row["recent_price_path"] = [item.get("close") for item in list(row["broker_bar_record"].get("bars") or [])]
            if row["broker_quote_record"].get("freshness_state") == "CURRENT":
                row.update({key: row["broker_quote_record"].get(key) for key in ("bid", "ask")})
            if row["broker_asset_record"].get("freshness_state") == "CURRENT":
                row["tradable"] = row["broker_asset_record"].get("tradable")
            horizon_record = build_legacy_swing_horizon_record_v1(row, record)
            row["legacy_swing_horizon_record"] = horizon_record
            required_evidence = build_legacy_swing_required_evidence_v1(row, record)
            coverage = build_legacy_swing_direct_evidence_coverage_v1(row, record, required_evidence)
            row["direct_evidence_coverage"] = coverage
            row["refresh_priority"] = coverage.get("refresh_priority")
            for evidence_type, evidence_row in required_evidence.items():
                if evidence_row.get("status") == "CURRENT":
                    if evidence_type == "MOMENTUM":
                        row["momentum_state"] = evidence_row.get("short_term_direction")
                    elif evidence_type == "THESIS_STATE":
                        row["thesis_state"] = evidence_row.get("thesis_state")
                    elif evidence_type == "LIQUIDITY":
                        row["liquidity_state"] = evidence_row.get("liquidity_state")
            previous = str(record.get("current_classification") or "")
            decision = build_unified_position_lifecycle_decision_v1(
                row, current_market_evidence=row, lifecycle_plan=record, evidence_context={"shadow_evidence": record.get("shadow_twin")}
            )
            decision["required_evidence"] = required_evidence
            forward_value = build_legacy_swing_forward_value_v1(row, decision, coverage)
            opportunity_cost = build_legacy_swing_opportunity_cost_v1(coverage, forward_value, record)
            profit_capture = build_legacy_swing_profit_capture_v1(row, coverage)
            decision.update({"direct_evidence_coverage": coverage, "forward_value": forward_value, "opportunity_cost_assessment": opportunity_cost, "profit_capture_assessment": profit_capture})
            for evidence_row in required_evidence.values():
                evidence_row["consumer_acknowledged"] = True
                evidence_row["acknowledgement_state"] = "CONSUMED_BY_UNIFIED_DECISION"
                evidence_row["classification_before"] = previous or None
                evidence_row["classification_after"] = decision.get("classification")
                evidence_row["classification_influence"] = "BLOCKING" if evidence_row.get("status") != "CURRENT" and decision.get("classification") == "INSUFFICIENT_EVIDENCE" else "NEUTRAL"
                evidence_row["influence_reason"] = decision.get("classification_reason")
                if evidence_row.get("evidence_type") == "THESIS_STATE":
                    fmp_record = dict(row.get("fmp_thesis_context") or {})
                    if not fmp_record.get("record_id"):
                        continue
                    fmp_record["consumer_acknowledged"] = True
                    fmp_record["consumer"] = "build_legacy_swing_required_evidence_v1"
                    fmp_record["consumed_at"] = _now_iso()
                    fmp_record["acknowledgement_state"] = "CONSUMED_BY_UNIFIED_DECISION"
                    fmp_record["influence_state"] = evidence_row["classification_influence"]
                    fmp_record["classification_before"] = previous or None
                    fmp_record["classification_after"] = decision.get("classification")
                    fmp_record["influence_reason"] = decision.get("classification_reason")
                    fmp_records[activation_id] = fmp_record
                    record["fmp_evidence"] = fmp_record
                if evidence_row.get("evidence_type") == "MOMENTUM":
                    market_record = dict((market_records.get(activation_id) or {}).get("HISTORICAL_BARS") or {})
                    if market_record.get("record_id"):
                        market_record.update({"consumer_acknowledged": True, "consumer": "build_legacy_swing_required_evidence_v1", "consumed_at": _now_iso(), "acknowledgement_state": "CONSUMED_BY_UNIFIED_DECISION", "influence_state": evidence_row["classification_influence"]})
                        market_records.setdefault(activation_id, {})["HISTORICAL_BARS"] = market_record
                if evidence_row.get("evidence_type") == "LIQUIDITY":
                    for family in ("LATEST_QUOTE", "ASSET_METADATA"):
                        market_record = dict((market_records.get(activation_id) or {}).get(family) or {})
                        if market_record.get("record_id"):
                            market_record.update({"consumer_acknowledged": True, "consumer": "build_legacy_swing_required_evidence_v1", "consumed_at": _now_iso(), "acknowledgement_state": "CONSUMED_BY_UNIFIED_DECISION", "influence_state": evidence_row["classification_influence"]})
                            market_records.setdefault(activation_id, {})[family] = market_record
            current = str(decision.get("classification") or "INSUFFICIENT_EVIDENCE")
            is_exit_review = current == "EXIT_REVIEW"
            if is_exit_review:
                exit_reviews += 1
            escalation = int(record.get("escalation_count") or 0) + (1 if is_exit_review and previous == current else 0)
            confirmation = build_legacy_swing_direct_confirmation_v1(row, decision, required_evidence)
            direct_confidence = float(confirmation.get("confirmation_confidence") or 0.0)
            direct_confirmed = str(confirmation.get("confirmation_state") or "").upper().startswith("CONFIRMED_")
            decision["current_direct_confirmation"] = direct_confirmed
            decision["direct_confirmation_confidence"] = direct_confidence
            decision["direct_confirmation"] = confirmation
            eligibility = evaluate_legacy_swing_canary_eligibility_v1(row, decision, config)
            daily = dict((market_records.get(activation_id) or {}).get("HISTORICAL_BARS_DAILY") or {})
            daily_required = int((horizon_record.get("required_bar_contract") or {}).get("minimum_completed_bars") or 0)
            daily_available = int(daily.get("records_valid") or 0)
            daily_state = "DAILY_SUFFICIENT" if daily.get("quality_state") == "CURRENT_SUFFICIENT" and daily_available >= daily_required else "DAILY_CURRENT_INSUFFICIENT" if daily else "DAILY_AWAITING_REFRESH"
            evidence_gap = {"schema_version": "legacy_swing_evidence_gap_v1", "evidence_gap_id": f"legacy-gap:{activation_id}", "position_id": decision.get("position_id"), "activation_id": activation_id, "symbol": symbol, "lane": "SWING", "horizon": horizon_record.get("effective_horizon"), "as_of": _now_iso(),
                            "required_evidence": ["MOMENTUM", "THESIS_STATE", "LIQUIDITY", "DIRECT_CONFIRMATION"], "available_evidence": [name for name, item in required_evidence.items() if item.get("status") == "CURRENT"],
                            "missing_evidence": [name for name, item in required_evidence.items() if item.get("status") != "CURRENT"], "stale_evidence": [], "conflicting_evidence": [], "insufficient_evidence": ["DAILY_BARS"] if daily_state != "DAILY_SUFFICIENT" else [],
                            "daily_bars_required": daily_required, "daily_bars_available": daily_available, "daily_bar_shortfall": max(0, daily_required - daily_available), "current_thesis_required": True, "current_quote_required": True, "current_liquidity_required": True, "direct_confirmation_required": True,
                            "decision_readiness_state": "MOMENTUM_GAP" if daily_state != "DAILY_SUFFICIENT" else "MULTIPLE_GAPS" if not coverage.get("required_evidence_complete") else "DECISION_READY", "readiness_percentage": coverage.get("coverage_percentage"),
                            "highest_priority_gap": "DAILY_BARS" if daily_state != "DAILY_SUFFICIENT" else (coverage.get("missing_evidence") or [None])[0], "priority_reason": "HORIZON_DAILY_CONTRACT_SHORTFALL" if daily_state != "DAILY_SUFFICIENT" else "OTHER_REQUIRED_EVIDENCE", "next_safe_action": "REQUEST_N_MORE_COMPLETED_DAILY_SESSIONS" if daily_state != "DAILY_SUFFICIENT" else "REBUILD_DIRECT_CONFIRMATION", "next_refresh_at": daily.get("next_refresh_at") or coverage.get("next_refresh_at")}
            review = {
                "activation_id": record.get("activation_id") or activation_id,
                "position_id": decision.get("position_id"), "symbol": symbol,
                "last_review_at": _now_iso(), "next_review_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "review_reason": "EXIT_REVIEW_ESCALATION" if is_exit_review else "NORMAL_WORKER_REASSESSMENT",
                "escalation_count": escalation, "previous_classification": previous or None,
                "current_classification": current, "current_blocker": eligibility.get("exact_blocker") or decision.get("exact_blocker"),
                "required_next_evidence": ",".join(decision.get("evidence_missing") or []) or ("CURRENT_DIRECT_CONFIRMATION" if not direct_confirmed else "CANARY_CANDIDATE_GATE"),
                "direct_confirmation_id": confirmation.get("confirmation_id"),
                "direct_confirmation_state": confirmation.get("confirmation_state"),
                "direct_confirmation_confidence": direct_confidence,
                "confirmation_blocker": None if direct_confirmed else confirmation.get("confirmation_reason"),
                "last_confirmation_attempt_at": confirmation.get("as_of"),
                "last_confirmation_success_at": confirmation.get("as_of") if direct_confirmed else None,
                "next_confirmation_at": confirmation.get("next_confirmation_at"),
                "confirmation_retry_count": int(confirmation.get("retry_count") or 0),
                "classification_confidence": decision.get("classification_confidence"),
                "classification_reason": decision.get("classification_reason"),
                "classification_components": dict(decision.get("classification_components") or {}),
                "classification_transition_reason": "INITIAL_CLASSIFICATION" if not previous else "EVIDENCE_REAFFIRMED" if previous == current else f"{previous}_TO_{current}:{decision.get('classification_reason')}",
                "required_evidence": required_evidence,
                "direct_evidence_coverage": coverage,
                "horizon_record": horizon_record, "daily_backlog": {"daily_state": daily_state, "contract_id": (horizon_record.get("required_bar_contract") or {}).get("contract_id"), "required_completed_bars": daily_required, "bars_validated": daily_available, "shortfall": max(0, daily_required - daily_available), "next_refresh_at": daily.get("next_refresh_at")}, "evidence_gap": evidence_gap,
                "forward_value": forward_value,
                "opportunity_cost": opportunity_cost,
                "profit_capture": profit_capture,
                "refresh_priority": coverage.get("refresh_priority"),
                "priority_reason": "DIRECT_EVIDENCE_INCOMPLETE" if not coverage.get("required_evidence_complete") else "CURRENT_EVIDENCE_REUSE",
                "direct_confirmation": confirmation,
                "decision": decision, "eligibility": eligibility,
                "acknowledgements": {
                    "CANARY_CONFIGURATION_CONSUMED_BY_WORKER": True,
                    "REASSESSMENT_PERSISTED_BY_NON_GET_WORKER": True,
                    "TECHNICAL_ELIGIBILITY_EVALUATED": True,
                    "DIRECT_CONFIRMATION_PERSISTED_BY_NON_GET_WORKER": True,
                    "EXECUTION_GATED_BY_CURRENT_CANARY_POLICY": True,
                },
            }
            record.update(review)
            registry[activation_id] = record
            reviews[activation_id] = review
            candidates.append({
                "position_id": decision.get("position_id"), "symbol": symbol,
                "technical_eligibility": eligibility.get("technical_eligibility"),
                "decision": decision, "eligibility": eligibility,
            })
            reviewed += 1
        selection = select_legacy_swing_canary_candidate_v1(candidates)
        selected = dict(selection.get("selected_candidate") or {})
        pre_submit = None
        adapter_result = None
        if selected:
            activation_id = next((key for key, value in reviews.items() if str(value.get("position_id") or "") == str(selected.get("position_id") or "")), "")
            review = dict(reviews.get(activation_id) or {})
            broker = dict(broker_positions.get(str(review.get("symbol") or "").upper()) or {})
            pre_submit = build_legacy_swing_canary_pre_submit_v1(
                position=broker, lifecycle_decision=dict(review.get("decision") or {}),
                eligibility=dict(review.get("eligibility") or {}), selection=selection, configuration=config,
            )
            if pre_submit and bool(config.get("enabled")) and not bool(config.get("kill_switch")):
                adapter_result = self.legacy_swing_canary_writer_pre_submit(pre_submit, broker)
        self._runtime_state["legacy_forward_activations"] = registry
        self._runtime_state["legacy_swing_market_evidence"] = market_records
        self._runtime_state["legacy_swing_canary"] = {
            "configuration": config, "reviews": reviews, "selection": selection,
            "pre_submit": pre_submit, "writer_adapter_contract": legacy_swing_writer_adapter_contract_v1(),
            "writer_adapter_result": adapter_result,
            "last_refresh_at": _now_iso(), "broker_actions": 0, "natural_orders": 0, "fixture_orders": 0,
            "worker_acknowledgement": "CANARY_CONFIGURATION_CONSUMED_BY_WORKER",
            "fmp_activity": fmp_activity,
            "fmp_records": fmp_records,
            "market_activity": market_activity,
            "market_records": market_records,
            "direct_confirmations": {key: dict(value.get("direct_confirmation") or {}) for key, value in reviews.items()},
        }
        return {
            "CANARY_CONFIGURATION_CONSUMED_BY_WORKER": True, "reviewed": reviewed,
            "exit_reviews": exit_reviews, "technically_eligible": len(selection.get("technically_eligible_candidates") or []),
            "selected": bool(selected), "execution_authorized": False, "broker_actions": 0,
            "market_activity": market_activity,
        }

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
        entry_verified = bool(open_row.get("entry_price_verified"))
        broker_entry_price = _to_float(open_row.get("broker_filled_avg_price"), 0.0)
        if not entry_verified or broker_entry_price <= 0.0 or not entry_order_id or not entry_fill_id:
            return {
                "persisted": False,
                "reason": "broker_confirmed_entry_price_required",
                "entry_price_verified": entry_verified,
                "entry_order_id_present": bool(entry_order_id),
                "entry_fill_id_present": bool(entry_fill_id),
            }
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
            "entry_price": broker_entry_price,
            "entry_price_source": str(open_row.get("entry_price_source") or ""),
            "entry_price_evidence_class": str(open_row.get("entry_price_evidence_class") or ""),
            "entry_price_verified": True,
            "exit_price": float(exit_price), "quantity": _to_float(open_row.get("quantity"), 0.0),
            "realized_return": round(float(return_percent), 6), "hold_duration": round(float(hold_seconds), 3),
            "return_per_hour": round(float(return_percent) / max(hold_seconds / 3600.0, 1e-9), 6),
            # These fields are carried only when the live lifecycle has
            # actually recorded them; unknown remains unknown.
            "mfe": _safe_json_load(open_row.get("row_json")).get("max_favorable_excursion_pct"),
            "mae": _safe_json_load(open_row.get("row_json")).get("max_adverse_excursion_pct"),
            "time_to_peak": _safe_json_load(open_row.get("row_json")).get("time_to_peak"),
            "profit_giveback": _safe_json_load(open_row.get("row_json")).get("profit_giveback_pct"),
            "exit_reason": str(exit_reason or ""), "paper_mode_verified": True,
            "official_metric_eligible": False, "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        record["natural_trade_label"] = natural_paper_trade_label(record)
        record["truth_state"] = "BROKER_TRUTH_CONFIRMED"
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

    def _crypto_execution_integrity_gate(self, row: dict[str, Any], *, capacity_snapshot: Mapping[str, Any] | None = None, duplicate_pending: bool = False, reconciliation_ok: bool = False) -> tuple[bool, str, dict[str, Any]]:
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
            capacity_fact=canonical_candidate_capacity_fact(
                capacity_snapshot,
                lane_id="CRYPTO",
                symbol=str(row.get("symbol") or row.get("ticker") or ""),
            ),
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
            "broker_pending_orders": [],
            "broker_orders_fetch_ok": False,
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
        if broker is not None and hasattr(broker, "orders"):
            try:
                orders_payload = dict(broker.orders() or {})
                if bool(orders_payload.get("ok")):
                    out["broker_pending_orders"] = [
                        dict(row) for row in list(orders_payload.get("orders") or [])
                        if isinstance(row, dict)
                        and str(row.get("status") or row.get("order_status") or "").lower()
                        in {"new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled", "pending_replace"}
                    ]
                    out["broker_orders_fetch_ok"] = True
            except Exception:
                # Positions remain the broker truth source. Missing order data
                # only prevents an in-flight order from claiming extra capacity.
                pass
        return out

    def _reconcile_entry_price_lineage_v1(self, broker_snapshot: dict[str, Any]) -> dict[str, Any]:
        """Replace a stored provisional price only with ID-linked paper fill evidence.

        This is worker-only reconciliation: it never creates a position, does
        not alter an order, and never matches an entry by symbol alone.
        """
        broker = self.alpaca_paper_broker
        position_by_symbol = dict((broker_snapshot or {}).get("broker_position_by_symbol") or {})
        with self._connect() as conn:
            rows = [dict(row or {}) for row in conn.execute(
                """
                SELECT * FROM paper_positions
                WHERE status='OPEN' AND COALESCE(entry_price_verified, 0)=0
                ORDER BY entry_timestamp ASC LIMIT 12
                """
            ).fetchall()]
        reviewed = repaired = awaiting = broker_reads = 0
        mismatch_rows: list[dict[str, Any]] = []
        for row in rows:
            reviewed += 1
            symbol = str(row.get("symbol") or "").upper().strip()
            entry_order_id = str(row.get("entry_order_id") or row.get("source_broker_order_id") or "").strip()
            client_order_id = str(row.get("source_client_order_id") or "").strip()
            order_result: dict[str, Any] = {}
            if entry_order_id and broker is not None and hasattr(broker, "order"):
                try:
                    broker_reads += 1
                    order_result = dict(broker.order(entry_order_id) or {})
                except Exception:
                    order_result = {}
            lineage = resolve_canonical_entry_price_lineage_v1(
                symbol=symbol,
                provisional_entry_price=row.get("provisional_entry_price") or row.get("entry_price"),
                candidate_entry_price=_safe_json_load(row.get("row_json")).get("price"),
                broker_order_result=order_result,
                broker_position=dict(position_by_symbol.get(symbol) or {}),
                expected_broker_order_id=entry_order_id,
                expected_client_order_id=client_order_id,
                paper_broker_context=bool((broker_snapshot or {}).get("broker_reconciliation_active")),
            )
            if not bool(lineage.get("entry_price_verified")):
                awaiting += 1
                continue
            notes = _safe_json_load(row.get("lifecycle_notes"))
            notes["entry_price_lineage_reconciliation_v1"] = {
                "reconciled_at": _now_iso(),
                "repair_action": "BROKER_FILL_REPLACED_PROVISIONAL_CANONICAL_ENTRY_PRICE",
                "entry_price_source": lineage.get("entry_price_source"),
                "entry_price_evidence_class": lineage.get("entry_price_evidence_class"),
                "entry_price_mismatch_pct": lineage.get("entry_price_mismatch_pct"),
            }
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE paper_positions
                    SET entry_price=?,
                        provisional_entry_price=CASE WHEN provisional_entry_price IS NULL OR provisional_entry_price<=0 THEN ? ELSE provisional_entry_price END,
                        broker_filled_avg_price=?, entry_price_source=?, entry_price_evidence_class=?,
                        entry_price_verified=1, entry_price_provisional=0,
                        entry_price_lineage_status=?, entry_price_lineage_reason=?,
                        entry_order_id=?, source_broker_order_id=?, source_client_order_id=?,
                        entry_fill_id=?, entry_filled_at=?, lifecycle_notes=?, updated_at=?
                    WHERE position_id=? AND COALESCE(entry_price_verified, 0)=0
                    """,
                    (
                        lineage.get("canonical_entry_price"), lineage.get("provisional_entry_price"),
                        lineage.get("broker_filled_avg_price"), lineage.get("entry_price_source"),
                        lineage.get("entry_price_evidence_class"), lineage.get("entry_price_lineage_status"),
                        lineage.get("entry_price_lineage_reason"), lineage.get("entry_order_id") or entry_order_id,
                        lineage.get("entry_order_id") or entry_order_id, lineage.get("source_client_order_id") or client_order_id,
                        lineage.get("entry_fill_id") or row.get("entry_fill_id"), lineage.get("entry_filled_at") or row.get("entry_filled_at"),
                        _safe_json(notes), _now_iso(), row.get("position_id"),
                    ),
                )
                conn.commit()
            if int(cursor.rowcount or 0) <= 0:
                continue
            repaired += 1
            if lineage.get("entry_price_mismatch_pct") is not None:
                mismatch_rows.append({
                    "position_id": row.get("position_id"), "symbol": symbol,
                    "provisional_entry_price": lineage.get("provisional_entry_price"),
                    "broker_filled_avg_price": lineage.get("broker_filled_avg_price"),
                    "mismatch_pct": lineage.get("entry_price_mismatch_pct"),
                    "repair_action": "BROKER_FILL_REPLACED_PROVISIONAL_CANONICAL_ENTRY_PRICE",
                })
        return {
            "status": "REPAIRED" if repaired else "AWAITING_BROKER_FILL",
            "reviewed": reviewed, "repaired": repaired, "awaiting": awaiting,
            "broker_reads": broker_reads, "mismatches": mismatch_rows[:12],
            "broker_actions_used": 0, "provider_calls_used": 0, "llm_calls_used": 0,
            "paper_only_preserved": True, "behavior_safe_to_apply": False,
        }

    def entry_price_lineage_dry_run_audit_v1(self, max_rows: int = 250) -> dict[str, Any]:
        """Compare stored entry prices with ID-linked broker truth without applying repairs."""
        cap = max(1, min(int(max_rows or 250), 500))
        with self._connect() as conn:
            positions = [dict(row or {}) for row in conn.execute(
                "SELECT * FROM paper_positions ORDER BY updated_at DESC LIMIT ?", (cap,)
            ).fetchall()]
        registry = self._trade_state_load_json("broker_truth_records_v1.json")
        truth_rows = [dict(row or {}) for row in (registry.get("records") or []) if isinstance(row, dict)][-1200:]
        by_order: dict[str, list[dict[str, Any]]] = {}
        by_fill: dict[str, list[dict[str, Any]]] = {}
        by_client: dict[str, list[dict[str, Any]]] = {}
        for truth in truth_rows:
            for key, index in ((truth.get("entry_order_id") or truth.get("broker_order_id"), by_order), (truth.get("entry_fill_id") or truth.get("fill_id"), by_fill), (truth.get("source_client_order_id") or truth.get("client_order_id"), by_client)):
                text = str(key or "").strip()
                if text:
                    index.setdefault(text, []).append(truth)
        lifecycle_path = os.path.join(os.path.dirname(self.db_path) or "state", "trade_lifecycle_excursion_v1.jsonl")
        lifecycle_by_id: dict[str, dict[str, Any]] = {}
        try:
            with open(lifecycle_path, "rb") as handle:
                handle.seek(max(0, os.path.getsize(lifecycle_path) - 1_500_000))
                lines = handle.read().decode("utf-8", "ignore").splitlines()[-1200:]
            for line in lines:
                parsed = json.loads(line)
                if isinstance(parsed, dict) and str(parsed.get("lifecycle_id") or "").strip():
                    lifecycle_by_id[str(parsed.get("lifecycle_id"))] = parsed
        except Exception:
            lifecycle_by_id = {}
        matches: list[dict[str, Any]] = []
        exact = timestamp_only = unmatched = 0
        for position in positions:
            order_id = str(position.get("entry_order_id") or position.get("source_broker_order_id") or "").strip()
            fill_id = str(position.get("entry_fill_id") or "").strip()
            client_id = str(position.get("source_client_order_id") or "").strip()
            candidates = by_order.get(order_id) or by_fill.get(fill_id) or by_client.get(client_id) or []
            match = candidates[0] if len(candidates) == 1 else {}
            match_kind = "broker_order_id" if match and by_order.get(order_id) else "fill_id" if match and by_fill.get(fill_id) else "client_order_id" if match else "unmatched"
            if match:
                exact += 1
            else:
                unmatched += 1
            stored = _to_float(position.get("entry_price"), 0.0)
            broker_price = _to_float(match.get("entry_price"), _to_float(match.get("filled_avg_price"), 0.0)) if match else 0.0
            mismatch = _entry_price_pct_difference(stored, broker_price)
            lifecycle = lifecycle_by_id.get(str(position.get("position_id") or ""), {})
            matches.append({
                "position_id": position.get("position_id"), "symbol": position.get("symbol"),
                "match_kind": match_kind, "exact_id_linked": bool(match), "timestamp_only_diagnostic_match": False,
                "original_entry_price": stored or None, "broker_fill_price": broker_price or None,
                "mismatch_pct": mismatch, "entry_price_verified": bool(position.get("entry_price_verified")),
                "eligible_for_safe_repair": bool(match and broker_price > 0.0 and not bool(position.get("entry_price_verified"))),
                "proposed_repair_action": "REQUIRES_WORKER_BROKER_FILL_RECONCILIATION" if match and broker_price > 0.0 else "NO_AUTOMATIC_REPAIR",
                "reason": "exact_identifier_linked_broker_truth" if match else "strong_broker_identifier_match_required",
                "lifecycle_metrics_would_need_reconstruction": bool(lifecycle and not bool(lifecycle.get("entry_price_verified"))),
            })
        return {
            "endpoint": "/api/broker_entry_price_lineage_repair_v1",
            "status": "DRY_RUN_COMPLETE", "historical_state_modified": False, "apply_mode_available": False,
            "records_reviewed": len(positions), "exact_id_linked_matches": exact,
            "timestamp_only_diagnostic_matches": timestamp_only, "unmatched_records": unmatched,
            "records": matches[:cap], "broker_truth_records_reviewed": len(truth_rows),
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
            "paper_only_preserved": True, "alpaca_paper_only_preserved": True,
            "behavior_safe_to_apply": False, "live_trading_changed": False,
            "broker_behavior_changed": False, "entry_behavior_changed": False,
            "ranking_behavior_changed": False, "thresholds_changed": False,
        }

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

    def _apply_approved_legacy_migration_v1(
        self,
        resolution_rows: list[dict[str, Any]],
        refreshed_reviews: dict[str, dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        """Consume the explicit one-time approval for the frozen 37-position set.

        This is deliberately invoked only by the normal reconciliation worker.
        It neither reads a provider nor changes broker state; it annotates the
        existing lifecycle overlay so the canonical capacity authority can
        distinguish active slots from fully risk-included legacy exposure.
        """
        manifest = dict(self._runtime_state.get("legacy_migration_manifest_v1") or {})
        approval = dict(self._runtime_state.get("legacy_migration_approval_v1") or {})
        application = dict(self._runtime_state.get("legacy_migration_application_v1") or {})
        now = datetime.now(UTC)
        if not manifest:
            manifest = build_legacy_migration_manifest_v1(
                resolution_rows,
                source_commit=_LEGACY_MIGRATION_SOURCE_COMMIT_V1,
                now=now,
            )
            if int(manifest.get("position_count") or 0) != 37:
                manifest["approval_status"] = "FAILED_COUNT_MISMATCH"
                manifest["exact_blocker"] = "AUDITED_LEGACY_MANIFEST_COUNT_NOT_37"
            self._runtime_state["legacy_migration_manifest_v1"] = manifest
        if not approval and manifest.get("approval_status") != "FAILED_COUNT_MISMATCH":
            # The task's explicit one-time migration authorization is recorded
            # verbatim as a durable, non-reusable approval event.
            approval = build_legacy_migration_approval_v1(
                manifest,
                approved_by="human_authorization_one_time_legacy_migration_v1",
                now=now,
            )
            self._runtime_state["legacy_migration_approval_v1"] = approval
        if not approval:
            return resolution_rows, refreshed_reviews
        if (
            approval.get("migration_manifest_id") != manifest.get("migration_manifest_id")
            or int(approval.get("approved_position_count") or 0) != int(manifest.get("position_count") or 0)
            or not bool(approval.get("full_risk_inclusion_required"))
            or not bool(approval.get("active_slot_exclusion_allowed"))
            or bool(approval.get("new_entries_allowed"))
            or bool(approval.get("averaging_down_allowed"))
            or bool(approval.get("replacement_inside_cohort_allowed"))
        ):
            approval["approval_status"] = "REJECTED_FAIL_CLOSED"
            approval["exact_blocker"] = "MIGRATION_APPROVAL_INTEGRITY_INVALID"
            self._runtime_state["legacy_migration_approval_v1"] = approval
            return resolution_rows, refreshed_reviews

        current_by_position = {
            str(row.get("position_id") or row.get("asset_id") or "").upper(): dict(row)
            for row in resolution_rows
            if str(row.get("position_id") or row.get("asset_id") or "")
        }
        current_by_symbol = {
            str(row.get("symbol") or "").upper(): dict(row)
            for row in resolution_rows
            if str(row.get("symbol") or "").strip()
        }
        outcomes: list[dict[str, Any]] = []
        approved_by_position: dict[str, dict[str, Any]] = {}
        for expected in list(manifest.get("position_identifiers") or []):
            expected_row = dict(expected or {})
            position_id = str(expected_row.get("position_id") or "")
            position_key = position_id.upper()
            symbol = str(expected_row.get("symbol") or "").upper()
            current = current_by_position.get(position_key)
            outcome = "MATCHED_OPEN_POSITION"
            if current is None:
                current = current_by_symbol.get(symbol)
                outcome = "ALREADY_CLOSED" if current is None else "SYMBOL_MISMATCH"
            if current is not None and outcome == "MATCHED_OPEN_POSITION":
                current_id = legacy_migration_position_identifier_v1(current)
                if current_id.get("broker_position_fingerprint") != expected_row.get("broker_position_fingerprint"):
                    outcome = "QUANTITY_CHANGED"
            if outcome == "MATCHED_OPEN_POSITION":
                approved_by_position[position_key] = current
            outcomes.append({
                "position_id": position_id,
                "symbol": symbol,
                "outcome": outcome,
                "expected_fingerprint": expected_row.get("broker_position_fingerprint"),
            })

        migrated_ids = set(approved_by_position)
        updated_rows: list[dict[str, Any]] = []
        updated_reviews = dict(refreshed_reviews)
        for row in resolution_rows:
            position_id = str(row.get("position_id") or row.get("asset_id") or "")
            position_key = position_id.upper()
            if position_key not in migrated_ids:
                updated_rows.append(row)
                continue
            prior = dict(updated_reviews.get(position_key) or {})
            applied = {
                **prior,
                "management_cohort": "LEGACY_POSITION_RESOLUTION",
                "legacy_migration_approved": True,
                "legacy_migration_approval_id": approval.get("approval_id"),
                "legacy_migration_manifest_id": manifest.get("migration_manifest_id"),
                "legacy_migration_state": "APPLIED",
                "legacy_resolution_approved": True,
                "legacy_resolution_approval_id": approval.get("approval_id"),
                "legacy_slot_exclusion_approved": True,
                "active_slot_exclusion": True,
                "full_risk_included": True,
                "decreasing_only": True,
                "no_new_legacy_entries": True,
            }
            updated_reviews[position_key] = applied
            overlay = build_position_management_overlay_v1(row, prior_review=applied, now=now)
            updated_rows.append({**row, **overlay})

        application = {
            "schema_version": "astra_legacy_migration_application_v1",
            "migration_manifest_id": manifest.get("migration_manifest_id"),
            "approval_id": approval.get("approval_id"),
            "applied_at": _now_iso(),
            "positions_matched": sum(1 for row in outcomes if row["outcome"] == "MATCHED_OPEN_POSITION"),
            "positions_already_closed": sum(1 for row in outcomes if row["outcome"] == "ALREADY_CLOSED"),
            "positions_mismatched": sum(1 for row in outcomes if row["outcome"] in {"QUANTITY_CHANGED", "SYMBOL_MISMATCH", "POSITION_NOT_FOUND"}),
            "positions_ambiguous": sum(1 for row in outcomes if row["outcome"] == "AMBIGUOUS_FAIL_CLOSED"),
            "positions_successfully_migrated": len(migrated_ids),
            "outcomes": outcomes,
            "full_risk_inclusion_required": True,
            "active_slot_exclusion_allowed": True,
            "decreasing_only": True,
        }
        already_closed = approval.get("approval_status") == "APPLIED_AND_CLOSED"
        approval.update({
            "approval_status": "APPLIED_AND_CLOSED",
            "consumed_once": True,
            "consumed_at": approval.get("consumed_at") or _now_iso(),
            "expires_after_application": True,
            "application_summary": {
                key: application[key]
                for key in ("positions_matched", "positions_already_closed", "positions_mismatched", "positions_ambiguous", "positions_successfully_migrated")
            },
        })
        if already_closed:
            application["recovery_state"] = "EXISTING_MANIFEST_OVERLAY_RESTORED"
            application["recovered_at"] = _now_iso()
        manifest["approval_status"] = "APPLIED_AND_CLOSED"
        self._runtime_state["legacy_migration_manifest_v1"] = manifest
        self._runtime_state["legacy_migration_approval_v1"] = approval
        self._runtime_state["legacy_migration_application_v1"] = application
        return updated_rows, updated_reviews

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
        prior_reviews = dict(self._runtime_state.get("position_resolution_reviews") or {})
        resolution_rows: list[dict[str, Any]] = []
        refreshed_reviews: dict[str, dict[str, Any]] = {}
        for position in positions:
            key = str(position.get("asset_id") or position.get("position_id") or position.get("symbol") or "").upper()
            overlay = build_position_management_overlay_v1(position, prior_review=dict(prior_reviews.get(key) or {}))
            enriched = {**position, **overlay}
            resolution_rows.append(enriched)
            if key:
                refreshed_reviews[key] = overlay
        if broker_payload.get("broker_positions_fetch_ok"):
            # Broker reconciliation is authoritative for which positions are
            # still active.  Retain only reviews for current broker positions.
            self._runtime_state["position_resolution_reviews"] = refreshed_reviews
            resolution_rows, refreshed_reviews = self._apply_approved_legacy_migration_v1(
                resolution_rows,
                refreshed_reviews,
            )
            self._runtime_state["position_resolution_reviews"] = refreshed_reviews
        positions = resolution_rows
        internal_by_symbol = {
            str(row.get("symbol") or "").upper().strip(): dict(row)
            for row in open_rows
            if str(row.get("symbol") or "").strip()
        }
        pending_orders: list[dict[str, Any]] = []
        for broker_order in list(broker_payload.get("broker_pending_orders") or []):
            if not isinstance(broker_order, dict):
                continue
            symbol = str(broker_order.get("symbol") or "").upper().strip()
            internal = dict(internal_by_symbol.get(symbol) or {})
            pending_orders.append({**internal, **broker_order})
        commitment_rows = self._active_lane_reserve_commitments()
        snapshot = build_capacity_snapshot(
            broker_snapshot=broker_payload,
            account_snapshot=account,
            open_positions=positions,
            global_position_limit=self.max_open_positions_total,
            global_risk_allowed=True,
            lane_entry_counts=self._evidence_reserve_entry_counts(),
            pending_orders=pending_orders,
            active_commitments=commitment_rows,
        )
        snapshot["current_commitment_snapshot"] = self._lane_reserve_commitment_snapshot()
        snapshot["pending_order_snapshot"] = {
            "broker_pending_orders": len(pending_orders),
            "broker_orders_fetch_ok": bool(broker_payload.get("broker_orders_fetch_ok")),
        }
        snapshot["broker_positions_fetch_ok"] = bool(broker_payload.get("broker_positions_fetch_ok"))
        snapshot["broker_positions_error_sanitized"] = str(broker_payload.get("broker_positions_error_sanitized") or "")[:180]
        snapshot["broker_orders_fetch_ok"] = bool(broker_payload.get("broker_orders_fetch_ok"))
        # Read-only lane and lifecycle diagnostics need the same committed
        # broker position view that capacity used.  Keep only non-secret,
        # execution-relevant fields so a GET route can reconcile its display
        # without performing another broker read.
        safe_position_fields = (
            "symbol", "qty", "quantity", "market_value", "current_price", "lastday_price",
            "avg_entry_price", "asset_class", "asset_type", "lane_id", "position_owner",
            "lifecycle_id", "candidate_id", "recommendation_id", "entry_fill_id",
            "entry_order_fill_id", "entry_timestamp", "unrealized_plpc",
            "classification", "classification_reason", "lifecycle_owner", "exit_owner",
            "capacity_owner", "truth_owner", "original_lane", "original_strategy",
            "original_horizon", "management_cohort", "decreasing_only",
            "legacy_resolution_approval_required", "legacy_resolution_approved",
            "legacy_resolution_approval_id", "active_slot_exclusion_eligible",
            "active_slot_exclusion_approved", "full_risk_included", "current_thesis",
            "legacy_migration_approved", "legacy_migration_approval_id",
            "legacy_migration_manifest_id", "legacy_migration_state", "active_slot_exclusion",
            "day_horizon_drift_decision", "day_horizon_drift_reason", "day_close_root_cause",
            "day_contract_failure_attribution_v1", "day_deadline_expired", "day_pre_close_review_state",
            "day_hard_deadline_at", "day_exit_or_conversion_state",
            "exit_readiness_state", "position_age_days", "last_review_at", "next_review_at",
            "review_state", "hold_exception_state",
        )
        snapshot["position_rows_for_read_only_consumers"] = [
            {key: row.get(key) for key in safe_position_fields if row.get(key) not in (None, "")}
            for row in positions[:100]
        ]
        snapshot["position_resolution_inventory_v1"] = build_position_resolution_inventory_v1(
            positions,
            prior_reviews_by_position=refreshed_reviews,
        )
        snapshot["position_resolution_reviews_owner"] = "engine.astra_unified_position_lifecycle_v1"
        snapshot["legacy_migration_manifest_v1"] = {
            key: value
            for key, value in dict(self._runtime_state.get("legacy_migration_manifest_v1") or {}).items()
            if key != "position_identifiers"
        }
        snapshot["legacy_migration_manifest_position_count"] = len(
            list((self._runtime_state.get("legacy_migration_manifest_v1") or {}).get("position_identifiers") or [])
        )
        snapshot["legacy_migration_approval_v1"] = {
            key: value
            for key, value in dict(self._runtime_state.get("legacy_migration_approval_v1") or {}).items()
            if key != "approved_position_identifiers"
        }
        snapshot["legacy_migration_application_v1"] = dict(
            self._runtime_state.get("legacy_migration_application_v1") or {}
        )
        snapshot["position_rows_source"] = "worker_broker_reconciliation"
        snapshot["position_rows_secret_free"] = True
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

    def _lane_reserve_commitment_ttl_seconds(self) -> int:
        return max(15, min(300, _to_int(os.getenv("ASTRA_LANE_RESERVE_COMMITMENT_TTL_SECONDS"), 90)))

    def _active_lane_reserve_commitments(self) -> list[dict[str, Any]]:
        """Return live in-flight commitments and expire abandoned worker holds."""
        now = datetime.now(UTC)
        active: list[dict[str, Any]] = []
        commitments = self._runtime_state.setdefault("lane_reserve_commitments", {"DAY": {}, "CRYPTO": {}})
        stats = self._runtime_state.setdefault("lane_reserve_commitment_stats", {})
        for lane in ("DAY", "CRYPTO"):
            lane_rows = commitments.setdefault(lane, {})
            for commitment_id, record in list(lane_rows.items()):
                row = dict(record or {})
                state = str(row.get("commitment_state") or "").upper()
                expires_at = str(row.get("expires_at") or "")
                try:
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=UTC)
                    expired = expiry.astimezone(UTC) <= now
                except (TypeError, ValueError):
                    expired = True
                if state in {"REQUESTED", "HELD", "CONVERTED_TO_PENDING_ORDER"} and expired:
                    row.update({"commitment_state": "EXPIRED", "state": "EXPIRED", "released_at": _now_iso(), "release_reason": "commitment_ttl_expired"})
                    lane_rows[commitment_id] = row
                    stats["expired"] = _to_int(stats.get("expired"), 0) + 1
                    continue
                if state in {"REQUESTED", "HELD", "CONVERTED_TO_PENDING_ORDER"}:
                    active.append(row)
        return active

    def _lane_reserve_commitment_snapshot(self) -> dict[str, Any]:
        active = self._active_lane_reserve_commitments()
        by_lane = {lane: [row for row in active if str(row.get("lane_id") or "").upper() == lane] for lane in ("DAY", "CRYPTO")}
        return {
            "commitment_state_owner": "PaperAutopilot",
            "active_commitments": len(active),
            "by_lane": {lane.lower(): len(rows) for lane, rows in by_lane.items()},
            "records": [dict(row) for row in active][:8],
            "stats": dict(self._runtime_state.get("lane_reserve_commitment_stats") or {}),
        }

    def _request_lane_reserve_commitment(
        self,
        row: dict[str, Any],
        capacity_snapshot: dict[str, Any],
        *,
        cycle_id: str,
    ) -> dict[str, Any]:
        """Hold a DAY/CRYPTO reserve only at final selection, never at review."""
        lane = str(row.get("lane_id") or "").upper()
        if lane not in {"DAY", "CRYPTO"}:
            return {"required": False, "commitment_state": "NOT_REQUIRED", "allowed": True}
        decision = candidate_capacity_decision(
            capacity_snapshot,
            lane_id=lane,
            symbol=str(row.get("symbol") or ""),
            open_symbols=set(),
        )
        if not decision.get("allowed"):
            return {"required": True, "commitment_state": "REJECTED", "allowed": False, "reason": decision.get("capacity_decision"), "capacity_decision": decision}
        candidate_id = str(row.get("candidate_id") or row.get("recommendation_id") or row.get("symbol") or "unknown")
        commitment_id = hashlib.sha256(f"{cycle_id}|{lane}|{candidate_id}".encode("utf-8")).hexdigest()[:24]
        commitments = self._runtime_state.setdefault("lane_reserve_commitments", {"DAY": {}, "CRYPTO": {}})
        lane_rows = commitments.setdefault(lane, {})
        existing = dict(lane_rows.get(commitment_id) or {})
        if existing and str(existing.get("commitment_state") or "").upper() in {"REQUESTED", "HELD", "CONVERTED_TO_PENDING_ORDER"}:
            return {"required": True, "commitment_state": str(existing.get("commitment_state")), "allowed": True, "commitment_id": commitment_id, "record": existing, "idempotent": True}
        active_count = len([item for item in self._active_lane_reserve_commitments() if str(item.get("lane_id") or "").upper() == lane])
        lane_view = dict((capacity_snapshot.get("lanes") or {}).get(lane.lower()) or {})
        remaining = _to_int(lane_view.get("positions_remaining"), 0) - active_count
        if remaining <= 0:
            return {"required": True, "commitment_state": "REJECTED", "allowed": False, "reason": "LANE_RESERVE_EXHAUSTED", "capacity_decision": decision}
        now = datetime.now(UTC)
        record = {
            "commitment_id": commitment_id,
            "lane_id": lane,
            "symbol": str(row.get("symbol") or "").upper(),
            "candidate_id": str(row.get("candidate_id") or ""),
            "recommendation_id": str(row.get("recommendation_id") or ""),
            "cycle_id": cycle_id,
            "commitment_state": "HELD",
            "state": "HELD",
            "reason": "final_selected_candidate",
            "source_fingerprint": str(row.get("candidate_fingerprint") or candidate_id),
            "created_at": _now_iso(),
            "requested_at": _now_iso(),
            "expires_at": (now + timedelta(seconds=self._lane_reserve_commitment_ttl_seconds())).isoformat().replace("+00:00", "Z"),
            "capacity_snapshot_id": capacity_snapshot.get("snapshot_id"),
        }
        lane_rows[commitment_id] = record
        stats = self._runtime_state.setdefault("lane_reserve_commitment_stats", {})
        stats["requested"] = _to_int(stats.get("requested"), 0) + 1
        return {"required": True, "commitment_state": "HELD", "allowed": True, "commitment_id": commitment_id, "record": record, "idempotent": False}

    def _release_lane_reserve_commitment(self, lane: str, commitment_id: str, reason: str) -> None:
        lane_rows = (self._runtime_state.setdefault("lane_reserve_commitments", {"DAY": {}, "CRYPTO": {}}).get(str(lane).upper()) or {})
        if not commitment_id or commitment_id not in lane_rows:
            return
        record = dict(lane_rows.get(commitment_id) or {})
        record.update({"commitment_state": "RELEASED", "state": "RELEASED", "released_at": _now_iso(), "release_reason": str(reason)[:160]})
        lane_rows[commitment_id] = record
        stats = self._runtime_state.setdefault("lane_reserve_commitment_stats", {})
        stats["released"] = _to_int(stats.get("released"), 0) + 1

    def _convert_lane_reserve_commitment(self, lane: str, commitment_id: str, state: str, broker_order_id: str = "") -> None:
        lane_rows = (self._runtime_state.setdefault("lane_reserve_commitments", {"DAY": {}, "CRYPTO": {}}).get(str(lane).upper()) or {})
        if not commitment_id or commitment_id not in lane_rows:
            return
        record = dict(lane_rows.get(commitment_id) or {})
        record.update({"commitment_state": state, "state": state, "converted_at": _now_iso(), "broker_order_id": str(broker_order_id or "")})
        lane_rows[commitment_id] = record
        stats = self._runtime_state.setdefault("lane_reserve_commitment_stats", {})
        stats["converted_to_pending_order" if state == "CONVERTED_TO_PENDING_ORDER" else "converted_to_open_position"] = _to_int(
            stats.get("converted_to_pending_order" if state == "CONVERTED_TO_PENDING_ORDER" else "converted_to_open_position"), 0
        ) + 1

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
        capacity_snapshot: Mapping[str, Any] | None = None,
        current_candidates: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], bool, str, dict[str, Any]]:
        r = _normalize_paper_entry_bridge(row)
        r = enrich_candidate_for_pretrade_contract(r, current_candidates=current_candidates)
        certification = dict(self._runtime_state.get("pre_market_certification_v1") or {})
        r["pretrade_decision_contract_v1"] = build_pretrade_decision_contract(
            r,
            certification_snapshot_id=str(certification.get("snapshot_id") or ""),
            expiry_timestamp=str(certification.get("expiry_timestamp") or ""),
        )
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
        contract = dict(r.get("pretrade_decision_contract_v1") or {})
        if allowed and not bool(contract.get("order_ready_allowed")):
            allowed = False
            reason = str(contract.get("fail_closed_reason") or "PRETRADE_DECISION_CONTRACT_INVALID")
        contract.setdefault("consumer_acknowledgements", {})["final_qualification"] = True
        contract["consumer_acknowledgements"]["final_qualification_status"] = (
            "CONSUMED" if allowed else "REJECTED_WITH_EXACT_BLOCKER"
        )
        if allowed:
            contract["candidate_terminal_state"] = "QUALIFIED"
        elif contract.get("contract_state") == "CONTRACT_COMPLETE":
            contract["candidate_terminal_state"] = "REJECTED"
        risk_envelope = dict(contract.get("candidate_risk_envelope_v1") or {})
        if risk_envelope:
            acknowledgements = risk_envelope.setdefault("consumer_acknowledgements", {})
            acknowledgements["CONSUMED_BY_QUALIFICATION"] = True
            acknowledgements["CONSUMED_BY_RISK_GATE"] = True
            acknowledgements["CONSUMED_BY_ORDER_READY"] = bool(allowed)
            contract["candidate_risk_envelope_v1"] = risk_envelope
        r["pretrade_decision_contract_v1"] = contract
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
            horizon = str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or "").strip()
            crypto_data_ok, crypto_data_reason, crypto_data_meta = self._crypto_execution_data_gate(r)
            integrity_ok, integrity_reason, integrity_meta = self._crypto_execution_integrity_gate(
                r,
                capacity_snapshot=capacity_snapshot,
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
            "decision_id": str(r.get("decision_id") or ""),
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
            "lane_reserve_enabled": bool((capacity_decision or {}).get("reserve_enabled", False)),
            "lane_reserve_available": bool((capacity_decision or {}).get("reserve_available", False)),
            "lane_capital_used": (capacity_decision or {}).get("capital_used"),
            "lane_capital_remaining": (capacity_decision or {}).get("capital_remaining"),
            "lane_capital_limit": (capacity_decision or {}).get("configured_capital_limit"),
            "lane_positions_used": (capacity_decision or {}).get("positions_used"),
            "lane_positions_remaining": (capacity_decision or {}).get("positions_remaining"),
            "lane_position_limit": (capacity_decision or {}).get("configured_position_limit"),
            "lane_open_position_count": (capacity_decision or {}).get("open_position_count", 0),
            "lane_pending_order_count": (capacity_decision or {}).get("pending_order_count", 0),
            "lane_active_commitment_count": (capacity_decision or {}).get("active_commitment_count", 0),
            "active_commitment_id": "",
            "capacity_blocker": str(((capacity_decision or {}).get("exact_blockers") or [""])[0] or ""),
            "confidence": round(_to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0)), 2),
            "horizon_confidence": round(_to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0)), 2),
            "expected_hold_window": _expected_hold_window(
                str(r.get("paper_entry_horizon_style") or r.get("trade_horizon_style") or r.get("best_horizon_style") or "").strip().lower()
            ),
            "horizon_reason": str(r.get("paper_entry_horizon_source") or r.get("horizon_reason") or r.get("allocation_reason") or ""),
            "pretrade_decision_contract_status": str(contract.get("contract_status") or "INVALID"),
            "pretrade_decision_contract_state": str(contract.get("contract_state") or "CONTRACT_INCOMPLETE"),
            "candidate_terminal_state": str(contract.get("candidate_terminal_state") or "CONTRACT_BUILDING"),
            "pretrade_decision_contract_missing_fields": list(contract.get("missing_required_fields") or []),
            "pretrade_decision_contract_conflicts": list(contract.get("conflicting_fields") or []),
            # Keep incomplete contracts actionable without inventing the
            # required forecasts. This identifies the existing repair path.
            "contract_failure_attribution_v1": {
                "schema_version": "astra_contract_failure_attribution_v1",
                "candidate_id": str(r.get("candidate_id") or ""),
                "lane": str(r.get("lane_id") or ""),
                "symbol": symbol,
                "missing_fields": list(contract.get("missing_required_fields") or []),
                "stale_fields": list(contract.get("stale_required_fields") or []),
                "invalid_fields": list(contract.get("conflicting_fields") or []),
                "producer": "engine.astra_premarket_certification_v1.build_pretrade_decision_contract",
                "store": "PaperAutopilot.last_execution_trace.per_candidate_decision_trace",
                "consumer": "PaperAutopilot._candidate_trace_row",
                "schema_version_source": str(contract.get("schema_version") or ""),
                "freshness": str(r.get("candidate_snapshot_freshness") or "MISSING"),
                "failure_state": str(contract.get("contract_state") or "CONTRACT_INCOMPLETE"),
                "repair_owner": "existing candidate risk-envelope and pretrade-contract producer",
            },
            "risk_envelope_id": str(risk_envelope.get("risk_envelope_id") or ""),
            "risk_envelope_state": str(risk_envelope.get("risk_envelope_state") or "RISK_ENVELOPE_INCOMPLETE"),
            "expected_outcome_state": str((contract.get("expected_outcome_envelope_v1") or {}).get("expected_outcome_state") or "EXPECTED_OUTCOME_INCOMPLETE"),
            "risk_envelope_consumer_acknowledgements": dict(risk_envelope.get("consumer_acknowledgements") or {}),
            "pretrade_decision_contract": contract,
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
        trace["eligibility_gate_attribution_v1"] = _eligibility_gate_attribution_v1(
            r,
            reason=reason,
            allowed=bool(allowed),
            gate_meta=gate_meta,
            activation=activation,
            session=session_diag,
            capacity=capacity_decision,
        )
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
                capacity_snapshot=dict(self._runtime_state.get("last_evidence_capacity_snapshot") or {}),
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
        entry_price_lineage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = _normalize_paper_entry_bridge(row)
        meta = dict(gate_meta or {})
        attribution = _paper_attribution_metadata(r)
        lineage = dict(entry_price_lineage or {})
        return {
            "entry_reason": "paper_autopilot_entry",
            "recommendation_id": attribution["recommendation_id"],
            "decision_id": attribution["decision_id"],
            "eligibility_evaluation_id": attribution["eligibility_evaluation_id"],
            "candidate_id": attribution["candidate_id"],
            "attribution_status": "captured_from_canonical_candidate" if any(attribution.values()) else "not_present_on_candidate",
            "entry_price": round(_to_float(entry_price, 0.0), 6),
            "entry_price_reference": round(_to_float(lineage.get("provisional_entry_price"), _to_float(entry_price, 0.0)), 6),
            "provisional_entry_price": lineage.get("provisional_entry_price"),
            "canonical_entry_price": lineage.get("canonical_entry_price", entry_price),
            "broker_filled_avg_price": lineage.get("broker_filled_avg_price"),
            "entry_slippage_pct": lineage.get("entry_slippage_pct"),
            "entry_price_source": str(lineage.get("entry_price_source") or "ENTRY_PRICE_UNAVAILABLE"),
            "entry_price_evidence_class": str(lineage.get("entry_price_evidence_class") or "ENTRY_PRICE_UNAVAILABLE"),
            "entry_price_verified": bool(lineage.get("entry_price_verified", False)),
            "entry_price_provisional": bool(lineage.get("entry_price_provisional", False)),
            "entry_price_lineage_status": str(lineage.get("entry_price_lineage_status") or "ENTRY_PRICE_UNAVAILABLE"),
            "entry_price_lineage_reason": str(lineage.get("entry_price_lineage_reason") or ""),
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
        entry_price_lineage = resolve_canonical_entry_price_lineage_v1(
            symbol=symbol,
            provisional_entry_price=entry_price,
            candidate_entry_price=row_price,
            broker_order_result=broker_order,
            expected_broker_order_id=source_broker_order_id,
            expected_client_order_id=source_client_order_id,
            paper_broker_context=True,
        )
        canonical_entry_price = _to_float(entry_price_lineage.get("canonical_entry_price"), 0.0)
        if canonical_entry_price <= 0.0:
            return {"ok": False, "error": "entry_price_lineage_unavailable", "symbol": symbol}
        entry_price = canonical_entry_price
        source_broker_order_id = str(entry_price_lineage.get("entry_order_id") or source_broker_order_id).strip()
        source_client_order_id = str(entry_price_lineage.get("source_client_order_id") or source_client_order_id).strip()
        entry_filled_at = str(entry_price_lineage.get("entry_filled_at") or "").strip()
        entry_fill_id = str(entry_price_lineage.get("entry_fill_id") or "").strip()
        entry_context = self._build_entry_context_v1(
            submit_row,
            entry_price,
            source_bucket,
            gate_meta=gate_meta,
            entry_price_lineage=entry_price_lineage,
        )
        entry_context["position_id"] = pid
        entry_context["alpaca_paper_order"] = broker_order
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
                    entry_order_id=?, entry_fill_id=?, entry_filled_at=?,
                    provisional_entry_price=?, broker_filled_avg_price=?,
                    entry_price_source=?, entry_price_evidence_class=?,
                    entry_price_verified=?, entry_price_provisional=?,
                    entry_price_lineage_status=?, entry_price_lineage_reason=?
                WHERE position_id=?
                """,
                (
                    str(entry_row.get("lane_id") or ""),
                    str(entry_row.get("capital_book_id") or ""),
                    str(entry_row.get("position_owner") or ""),
                    str(entry_row.get("exit_policy_owner") or ""),
                    source_broker_order_id,
                    entry_fill_id,
                    entry_filled_at or None,
                    entry_price_lineage.get("provisional_entry_price"),
                    entry_price_lineage.get("broker_filled_avg_price"),
                    entry_price_lineage.get("entry_price_source"),
                    entry_price_lineage.get("entry_price_evidence_class"),
                    1 if bool(entry_price_lineage.get("entry_price_verified")) else 0,
                    1 if bool(entry_price_lineage.get("entry_price_provisional")) else 0,
                    entry_price_lineage.get("entry_price_lineage_status"),
                    entry_price_lineage.get("entry_price_lineage_reason"),
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
                        "provisional_entry_price": entry_price_lineage.get("provisional_entry_price"),
                        "broker_filled_avg_price": entry_price_lineage.get("broker_filled_avg_price"),
                        "entry_price_source": entry_price_lineage.get("entry_price_source"),
                        "entry_price_evidence_class": entry_price_lineage.get("entry_price_evidence_class"),
                        "entry_price_verified": bool(entry_price_lineage.get("entry_price_verified")),
                        "entry_price_provisional": bool(entry_price_lineage.get("entry_price_provisional")),
                        "entry_price_lineage_status": entry_price_lineage.get("entry_price_lineage_status"),
                        "entry_price_lineage_reason": entry_price_lineage.get("entry_price_lineage_reason"),
                        "entry_order_id": source_broker_order_id,
                        "entry_fill_id": entry_fill_id,
                        "source_client_order_id": source_client_order_id,
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
            "provisional_entry_price": entry_price_lineage.get("provisional_entry_price"),
            "broker_filled_avg_price": entry_price_lineage.get("broker_filled_avg_price"),
            "entry_price_source": entry_price_lineage.get("entry_price_source"),
            "entry_price_evidence_class": entry_price_lineage.get("entry_price_evidence_class"),
            "entry_price_verified": bool(entry_price_lineage.get("entry_price_verified")),
            "entry_price_lineage_status": entry_price_lineage.get("entry_price_lineage_status"),
            "asset_type": asset_type,
            "broker_order_id": source_broker_order_id,
            "entry_fill_id": entry_fill_id,
            "broker_order_status": str(broker_order_payload.get("status") or ""),
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
        self._runtime_state["worker_generation_id"] = f"paper-autopilot:{os.getpid()}:{int(time.time())}"
        self._note_worker_progress("starting")

        def _loop():
            while not self._stop_event.is_set():
                cycle_started_at = _now_iso()
                self._runtime_state["worker_cycle_started_at"] = cycle_started_at
                self._runtime_state["worker_cycle_error"] = ""
                self._note_worker_progress("cycle_start")
                try:
                    self.run_cycle()
                except Exception as e:
                    self._runtime_state["last_error"] = str(e)[:240]
                    self._note_worker_progress("cycle_failed", error=str(e))
                else:
                    self._runtime_state["worker_cycle_completed_at"] = _now_iso()
                    self._runtime_state["worker_cycle_count"] = _to_int(self._runtime_state.get("worker_cycle_count"), 0) + 1
                    self._note_worker_progress("cycle_completed")
                    # A complete cycle is the only point that advances the
                    # durable heartbeat.  This prevents GET traffic from
                    # masking a stalled worker after a restart.
                    self._save_state_file()
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

    def _load_loss_containment_state(self) -> dict[str, Any]:
        return load_loss_containment_state_v1(self.loss_containment_state_path)

    def _save_loss_containment_state(self, state: dict[str, Any] | None = None) -> None:
        payload = dict(state or self._runtime_state.get("loss_containment_state_v1") or {})
        save_loss_containment_state_v1(self.loss_containment_state_path, payload)

    def _loss_containment_review_phase(
        self,
        open_rows: list[dict[str, Any]] | None = None,
        broker_position_by_symbol: dict[str, dict[str, Any]] | None = None,
        latest_price_by_symbol: dict[str, dict[str, Any]] | None = None,
        max_positions: int = 100,
        broker_fetch_succeeded: bool | None = None,
    ) -> dict[str, Any]:
        """Bounded advisory loss-containment review without order submission.

        Produces canonical loss-containment decisions per position, lane
        summaries, and durable shadow records. Execution is never authorized.

        Broker positions are authoritative for current open-position existence.
        When broker snapshot is available and caller did not explicitly provide
        rows, always build canonical rows from broker positions (authoritative),
        regardless of DB state.

        broker_fetch_succeeded: True if broker fetch completed (may be empty).
        """
        has_explicit_rows = open_rows is not None
        rows = list(open_rows or self._fetch_open_positions() or [])
        broker_positions = dict(broker_position_by_symbol or {})
        latest_prices = dict(latest_price_by_symbol or {})
        prior_state = self._load_loss_containment_state()

        # Authoritative broker truth: When broker fetch succeeded (even if
        # empty), use canonical snapshot. Broker positions define the
        # authoritative current open-position set.
        broker_available = broker_fetch_succeeded or bool(broker_positions)
        if not has_explicit_rows and broker_available:
            canonical_snapshot = build_canonical_position_snapshot(broker_positions)
            broker_rows = snapshot_to_loss_containment_rows(canonical_snapshot)
            if broker_rows:
                rows = broker_rows  # Broker truth overrides any stale DB rows
                # Stale decision eviction: Only retain prior decisions for
                # positions that exist in current broker snapshot.
                current_symbols = set(broker_positions.keys())
                prior_decisions = dict(prior_state.get("decisions") or {})
                filtered_decisions = {
                    pid: d for pid, d in prior_decisions.items()
                    if isinstance(d, dict) and d.get("symbol") in current_symbols
                }
                prior_state = {**prior_state, "decisions": filtered_decisions}

        ownership_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = _pick_first_text(row.get("position_id"), row.get("asset_id"), row.get("symbol"))
            ownership_map[pid] = resolve_canonical_position_ownership_v1(row)

        result = run_loss_containment_review_v1(
            rows,
            ownership_map=ownership_map,
            broker_positions=broker_positions,
            latest_price_by_symbol=latest_prices,
            prior_state=prior_state,
            max_positions=max_positions,
        )
        self._runtime_state["loss_containment_review_v1"] = {
            "positions_evaluated": result.get("positions_evaluated", 0),
            "max_positions": result.get("max_positions", 1),
            "metrics": result.get("metrics", {}),
            "lane_summaries": result.get("lane_summaries", {}),
            "execution_authorized": result.get("execution_authorized", False),
            "paper_action_ready": result.get("paper_action_ready", False),
            "broker_submission_allowed": result.get("broker_submission_allowed", False),
            "advisory_only": result.get("advisory_only", True),
            "as_of": result.get("generated_timestamp"),
        }
        self._runtime_state["loss_containment_state_v1"] = result.get("state", {})
        self._save_loss_containment_state(result.get("state", {}))
        return result

    def _load_profit_protection_state(self) -> dict[str, Any]:
        return load_profit_protection_state_v1(self.profit_protection_state_path)

    def _save_profit_protection_state(self, state: dict[str, Any] | None = None) -> None:
        payload = dict(state or self._runtime_state.get("profit_protection_state_v1") or {})
        save_profit_protection_state_v1(self.profit_protection_state_path, payload)

    def _profit_protection_review_phase(
        self,
        open_rows: list[dict[str, Any]] | None = None,
        broker_position_by_symbol: dict[str, dict[str, Any]] | None = None,
        max_positions: int = 100,
        broker_fetch_succeeded: bool | None = None,
    ) -> dict[str, Any]:
        """Bounded advisory profit-protection review without order submission.

        Consumes loss-containment decisions by position ID for precedence.

        Broker positions are authoritative for current open-position existence.
        """
        has_explicit_rows = open_rows is not None
        rows = list(open_rows or self._fetch_open_positions() or [])
        broker_positions = dict(broker_position_by_symbol or {})
        prior_state = self._load_profit_protection_state()

        broker_available = broker_fetch_succeeded or bool(broker_positions)
        if not has_explicit_rows and broker_available:
            canonical_snapshot = build_canonical_position_snapshot(broker_positions)
            broker_rows = snapshot_to_loss_containment_rows(canonical_snapshot)
            if broker_rows:
                rows = broker_rows  # Broker truth overrides any stale DB rows
                # Stale decision eviction for profit protection too
                current_symbols = set(broker_positions.keys())
                prior_decisions = dict(prior_state.get("decisions") or {})
                filtered_decisions = {
                    pid: d for pid, d in prior_decisions.items()
                    if isinstance(d, dict) and d.get("symbol") in current_symbols
                }
                prior_state = {**prior_state, "decisions": filtered_decisions}

        ownership_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = _pick_first_text(row.get("position_id"), row.get("asset_id"), row.get("symbol"))
            ownership_map[pid] = resolve_canonical_position_ownership_v1(row)

        lc_state = self._runtime_state.get("loss_containment_state_v1") or {}
        lc_decisions = dict(lc_state.get("decisions") or {})

        result = run_profit_protection_review_v1(
            rows,
            ownership_map=ownership_map,
            broker_positions=broker_positions,
            loss_containment_decisions=lc_decisions,
            prior_state=prior_state,
            max_positions=max_positions,
        )
        self._runtime_state["profit_protection_review_v1"] = {
            "positions_evaluated": result.get("positions_evaluated", 0),
            "max_positions": result.get("max_positions", 1),
            "metrics": result.get("metrics", {}),
            "lane_summaries": result.get("lane_summaries", {}),
            "execution_authorized": result.get("execution_authorized", False),
            "paper_action_ready": result.get("paper_action_ready", False),
            "broker_submission_allowed": result.get("broker_submission_allowed", False),
            "advisory_only": result.get("advisory_only", True),
            "as_of": result.get("generated_timestamp"),
        }
        self._runtime_state["profit_protection_state_v1"] = result.get("state", {})
        self._save_profit_protection_state(result.get("state", {}))
        return result

    def _bounded_legacy_quarantine_review_phase(
        self,
        open_rows: list[dict[str, Any]] | None = None,
        broker_position_by_symbol: dict[str, dict[str, Any]] | None = None,
        max_reviews: int = 1,
    ) -> dict[str, Any]:
        """Bounded, worker-owned legacy quarantine review without order submission.

        Produces canonical ownership, a single lifecycle decision, and a
        broker-neutral exit-readiness contract per reviewed position. The
        canary remains disabled; execution_authorized is always False.
        """
        rows = list(open_rows or self._fetch_open_positions() or [])
        broker_positions = dict(broker_position_by_symbol or {})
        prior_reviews = dict(self._runtime_state.get("legacy_quarantine_reviews_v1") or {})
        market_session = {}
        if self.market_session_timing_suite is not None:
            try:
                market_session = dict(self.market_session_timing_suite.status() or {})
            except Exception:
                market_session = {}
        pending_map = dict(self._runtime_state.get("authorized_lane_exit_pending") or {})
        result = bounded_legacy_quarantine_review_v1(
            rows,
            broker_positions=broker_positions,
            pending_map=pending_map,
            market_session=market_session,
            max_reviews=max_reviews,
            prior_reviews=prior_reviews,
        )
        # Store by position_id for idempotent review; never overwrite activation ts.
        stored: dict[str, Any] = {}
        for item in result.get("reviewed", []) or []:
            pid = str(item.get("position_id") or "").strip()
            if not pid:
                continue
            prior = dict(prior_reviews.get(pid) or {})
            if prior.get("activation_timestamp") and not item.get("activation_timestamp"):
                item["activation_timestamp"] = prior["activation_timestamp"]
            stored[pid] = item
        self._runtime_state["legacy_quarantine_reviews_v1"] = stored
        self._runtime_state["legacy_quarantine_review_summary_v1"] = {
            "reviewed_count": result.get("reviewed_count", 0),
            "max_reviews": result.get("max_reviews", 1),
            "execution_authorized": result.get("execution_authorized", False),
            "canary_enabled": result.get("canary_enabled", False),
            "kill_switch_active": result.get("kill_switch_active", True),
            "as_of": result.get("as_of"),
        }
        self._runtime_state["legacy_quarantine_attribution_summary_v1"] = build_position_attribution_summary_v1(
            rows,
            broker_positions=broker_positions,
        )
        self._runtime_state["legacy_canary_control_v1"] = ensure_fail_closed_canary_control_v1()
        return result

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
        legacy_canary = dict(self._runtime_state.get("legacy_swing_canary") or {})
        legacy_canary_control = dict(self._runtime_state.get("legacy_canary_control_v1") or {})
        if not legacy_canary_control:
            legacy_canary_control = {
                "schema_version": "legacy_swing_canary_control_v1",
                "activation_state": "DISABLED_FAIL_CLOSED",
                "enabled": False,
                "kill_switch": True,
                "readiness_state": "NOT_READY",
                "execution_authorized": False,
                "source": "in_memory_fail_closed_default",
            }
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
            "legacy_swing_canary": {
                "configuration": dict(legacy_canary.get("configuration") or legacy_swing_canary_configuration_v1()),
                "worker_acknowledgement": legacy_canary.get("worker_acknowledgement"),
                "reviews_count": len(dict(legacy_canary.get("reviews") or {})),
                "technically_eligible_count": len(dict(legacy_canary.get("selection") or {}).get("technically_eligible_candidates") or []),
                "broker_actions": int(legacy_canary.get("broker_actions") or 0),
            },
            "legacy_quarantine_review_v1": dict(self._runtime_state.get("legacy_quarantine_review_summary_v1") or {}),
            "legacy_quarantine_attribution_summary_v1": dict(self._runtime_state.get("legacy_quarantine_attribution_summary_v1") or {}),
            "loss_containment_review_v1": dict(self._runtime_state.get("loss_containment_review_v1") or {}),
            "profit_protection_review_v1": dict(self._runtime_state.get("profit_protection_review_v1") or {}),
            "legacy_canary_control_v1": legacy_canary_control,
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
                # Control status is intentionally broker/provider/database
                # free.  The last completed worker trace is sufficient for a
                # configuration view and cannot block a read-only endpoint.
                _to_int(last_trace.get("broker_open_positions_count"), 0)
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
            # Evidence acquisition must remain worker-owned even when the
            # global order worker is disabled.  This calls only the existing
            # legacy-SWING read/normalization path; it never enters submission.
            legacy_refresh: dict[str, Any] = {}
            try:
                self._note_worker_progress("legacy_swing_observation")
                broker_snapshot = self._broker_open_symbols_snapshot()
                broker_positions = dict(broker_snapshot.get("broker_position_by_symbol") or {})
                legacy_refresh = self._refresh_legacy_swing_canary_pre_submit(broker_positions)
            except Exception as exc:
                legacy_refresh = {"observation_state": "FAILED", "error": str(exc)[:180]}
            try:
                self._note_worker_progress("legacy_quarantine_review")
                quarantine_review = self._bounded_legacy_quarantine_review_phase(
                    open_rows=self._fetch_open_positions(),
                    broker_position_by_symbol=broker_positions,
                    max_reviews=1,
                )
            except Exception as exc:
                quarantine_review = {"observation_state": "FAILED", "error": str(exc)[:180]}
            loss_containment_review: dict[str, Any] = {}
            try:
                self._note_worker_progress("loss_containment_review")
                broker_snapshot = self._broker_open_symbols_snapshot()
                loss_containment_review = self._loss_containment_review_phase(
                    open_rows=self._fetch_open_positions(),
                    broker_position_by_symbol=dict(broker_snapshot.get("broker_position_by_symbol") or {}),
                    max_positions=100,
                    broker_fetch_succeeded=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
                )
            except Exception as exc:
                loss_containment_review = {"observation_state": "FAILED", "error": str(exc)[:180]}
            safety = self._alpaca_safety_snapshot()
            out = {
                "ok": True,
                "autopilot_enabled": False,
                "orders_submitted": 0,
                "positions_closed": 0,
                "cycle_reason": "disabled",
                "legacy_swing_observation": legacy_refresh,
                "legacy_quarantine_review_v1": quarantine_review,
                "loss_containment_review_v1": loss_containment_review,
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
                "legacy_swing_observation": legacy_refresh,
                "legacy_quarantine_review_v1": quarantine_review,
                "loss_containment_review_v1": loss_containment_review,
            }
            self._runtime_state["last_cycle_utc"] = _now_iso()
            self._runtime_state["last_cycle_summary"] = out
            self._runtime_state["last_execution_trace"] = trace
            return out

        with self._cycle_lock:
            cycle_id = _now_iso()
            # Keep legacy market evidence ahead of generic preflight work.
            # This is the same bounded worker-owned refresh and has no order
            # submission path; the later position-aware pass reuses its cache.
            legacy_canary_refresh: dict[str, Any] = {}
            try:
                self._note_worker_progress("legacy_market_evidence_preflight")
                legacy_canary_refresh = self._refresh_legacy_swing_canary_pre_submit({})
                self._save_state_file()
            except Exception as exc:
                legacy_canary_refresh = {"observation_state": "FAILED", "error": str(exc)[:180]}
            market_cycle = dict(legacy_canary_refresh.get("market_activity") or {})
            if str(market_cycle.get("cycle_state") or "").startswith("CYCLE_PARTIAL"):
                # Keep the bounded cursor cooperative while still publishing
                # the read-only broker truth that capacity diagnostics need.
                # No entry, exit, or order path is reached from this branch.
                self._note_worker_progress("bounded_broker_reconciliation")
                safety = self._alpaca_safety_snapshot()
                broker_snapshot = self._broker_open_symbols_snapshot()
                evidence_capacity_snapshot = self._evidence_capacity_snapshot_v1(
                    broker_snapshot,
                    self._fetch_open_positions(),
                    safety,
                )
                crypto_refresh: dict[str, Any] = {}
                if callable(self.refresh_crypto_rankings_fn):
                    try:
                        self._note_worker_progress("crypto_ranking_refresh")
                        crypto_refresh = dict(self.refresh_crypto_rankings_fn() or {})
                    except Exception as exc:
                        crypto_refresh = {
                            "status": "FAILED_FAIL_CLOSED",
                            "exact_blocker": f"crypto_ranking_refresh_exception:{str(exc)[:120]}",
                        }
                equity_risk_refresh: dict[str, Any] = {}
                if callable(self.refresh_equity_risk_envelopes_fn):
                    try:
                        self._note_worker_progress("equity_risk_envelope_refresh")
                        equity_risk_refresh = dict(self.refresh_equity_risk_envelopes_fn() or {})
                    except Exception as exc:
                        equity_risk_refresh = {
                            "status": "FAILED_FAIL_CLOSED",
                            "exact_blocker": f"equity_risk_envelope_refresh_exception:{str(exc)[:120]}",
                        }
                loss_containment_review_partial: dict[str, Any] = {}
                try:
                    self._note_worker_progress("loss_containment_review")
                    broker_position_by_symbol = dict(broker_snapshot.get("broker_position_by_symbol") or {})
                    loss_containment_review_partial = self._loss_containment_review_phase(
                        broker_position_by_symbol=broker_position_by_symbol,
                        max_positions=100,
                        broker_fetch_succeeded=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
                    )
                except Exception as exc:
                    loss_containment_review_partial = {"observation_state": "FAILED", "error": str(exc)[:180]}
                profit_protection_review_partial: dict[str, Any] = {}
                try:
                    self._note_worker_progress("profit_protection_review")
                    broker_position_by_symbol = dict(broker_snapshot.get("broker_position_by_symbol") or {})
                    profit_protection_review_partial = self._profit_protection_review_phase(
                        broker_position_by_symbol=broker_position_by_symbol,
                        max_positions=100,
                        broker_fetch_succeeded=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
                    )
                except Exception as exc:
                    profit_protection_review_partial = {"observation_state": "FAILED", "error": str(exc)[:180]}
                # Update peak memory from broker snapshot
                peak_memory_update: dict[str, Any] = {}
                try:
                    peak_memory_update = build_peak_memory(
                        dict(broker_snapshot.get("broker_position_by_symbol") or {}),
                        prior_state=load_peak_memory(self.peak_memory_state_path),
                    )
                    save_peak_memory(self.peak_memory_state_path, peak_memory_update)
                except Exception:
                    peak_memory_update = {"positions_tracked": 0, "error": "peak_memory_exception"}
                # Bounded candidate-processing microphase using canonical sources
                partial_candidate_results: dict[str, Any] = {}
                try:
                    import time as _time
                    _t0 = _time.monotonic()
                    self._note_worker_progress("partial_candidate_microphase")
                    lane_cursor = _to_int(self._runtime_state.get("partial_candidate_lane_cursor"), 0)
                    rotating_lanes = ["DAY", "SWING", "CRYPTO"]
                    target_lane = rotating_lanes[lane_cursor % len(rotating_lanes)]
                    self._runtime_state["partial_candidate_lane_cursor"] = (lane_cursor + 1) % max(1, len(rotating_lanes))

                    candidate_rows: list[dict[str, Any]] = []
                    candidate_source_name = ""
                    candidate_source_count = 0
                    provider_calls_added = 0
                    snapshot_freshness_str = "SNAPSHOT_MISSING"

                    # CRYPTO: use already-fetched crypto_rankings_snapshot_v1
                    if target_lane == "CRYPTO":
                        cr = dict(crypto_refresh or {})
                        cr_rows = list(cr.get("rows") or [])
                        if not cr_rows:
                            cr_state = dict(self._runtime_state.get("crypto_rankings_snapshot_v1") or {})
                            cr_rows = list(cr_state.get("rows") or [])
                        if cr_rows:
                            candidate_source_name = "crypto_rankings_snapshot_v1"
                            candidate_source_count = len(cr_rows)
                            snapshot_freshness_str = "SNAPSHOT_CURRENT" if cr.get("status") == "CURRENT" else "SNAPSHOT_STALE"
                            for row in cr_rows[:5]:
                                if isinstance(row, dict):
                                    r = dict(row)
                                    r.setdefault("lane_id", "CRYPTO")
                                    r.setdefault("asset_class", "crypto")
                                    candidate_rows.append(r)
                    # DAY/SWING: collect equity candidates from cached snapshot
                    else:
                        try:
                            equity_rows = self._collect_candidate_rows()
                            for row in (equity_rows or []):
                                if not isinstance(row, dict):
                                    continue
                                asset_class = _text(row.get("asset_class") or row.get("asset_type")).lower()
                                if asset_class in ("crypto", "cryptocurrency"):
                                    continue
                                lane = _text(row.get("lane_id") or row.get("lane")).upper()
                                horizon = _text(
                                    row.get("paper_entry_horizon_style")
                                    or row.get("assigned_horizon")
                                    or row.get("intended_horizon")
                                ).lower()
                                if target_lane == "DAY" and (lane == "DAY" or horizon in ("scalp", "day_trade", "day", "intraday")):
                                    if len(candidate_rows) < 5:
                                        r = dict(row)
                                        r.setdefault("lane_id", "DAY")
                                        candidate_rows.append(r)
                                elif target_lane == "SWING" and (lane == "SWING" or horizon in ("swing_trade", "swing", "position_trade")):
                                    if len(candidate_rows) < 5:
                                        r = dict(row)
                                        r.setdefault("lane_id", "SWING")
                                        candidate_rows.append(r)
                            candidate_source_name = "equity_top_buys_cached"
                            candidate_source_count = len(equity_rows) if equity_rows else 0
                            snapshot_freshness_str = "SNAPSHOT_CURRENT"
                        except Exception:
                            candidate_source_name = "equity_candidate_requires_full_cycle"
                            candidate_source_count = 0
                            snapshot_freshness_str = "SNAPSHOT_MISSING"

                    # Apply actual candidate gating (bounded)
                    candidate_input_count = len(candidate_rows)
                    evaluated_count = 0
                    fresh_count = 0
                    eligible_count = 0
                    order_ready_count = 0
                    first_blocker = "no_canonical_prospective_candidates"
                    blocker_reason = ""

                    broker_positions = dict(broker_snapshot.get("broker_position_by_symbol") or {})

                    for row in candidate_rows:
                        evaluated_count += 1
                        row_blocker = ""

                        # Freshness gate - inline timestamp age check
                        ts = _text(row.get("quote_timestamp") or row.get("generated_at"))
                        age = None
                        if ts:
                            try:
                                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=UTC)
                                age = max(0.0, (datetime.now(UTC).astimezone(UTC) - dt).total_seconds() / 60.0)
                            except Exception:
                                age = None
                        if age is None or age > 15.0:
                            row_blocker = row_blocker or "CANDIDATE_TIMESTAMP_STALE"
                        else:
                            fresh_count += 1

                        # Lane assignment validation
                        row_lane = _text(row.get("lane_id") or row.get("lane")).upper()
                        if row_lane not in ("DAY", "SWING", "CRYPTO"):
                            row_blocker = row_blocker or "LANE_MISSING"

                        # Symbol validation
                        sym = _text(row.get("symbol")).upper()
                        if not sym:
                            row_blocker = row_blocker or "SYMBOL_MISSING"

                        # Basic eligibility
                        if not row_blocker:
                            eligible_count += 1
                        first_blocker = row_blocker or first_blocker
                        blocker_reason = blocker_reason or _text(row.get("exact_blocker") or row.get("reason"))
                        if not row_blocker:
                            order_ready_count = eligible_count  # bounded: if eligible, considered ORDER_READY candidate

                    if blocker_reason == "no_canonical_prospective_candidates" and candidate_input_count > 0:
                        blocker_reason = f"{target_lane}_candidates_evaluated_but_all_blocked"
                    if not candidate_rows and target_lane != "CRYPTO":
                        first_blocker = "EQUITY_CANDIDATE_SOURCE_NOT_IN_PARTIAL_CYCLE"
                        blocker_reason = "full_cycle_required_for_equity_candidate_processing"
                    elif not candidate_rows and target_lane == "CRYPTO":
                        first_blocker = "NO_CANONICAL_CRYPTO_CANDIDATES"
                        blocker_reason = "crypto_rankings_snapshot_empty"

                    elapsed_ms = round((_time.monotonic() - _t0) * 1000)

                    partial_candidate_results = {
                        "microphase_scheduled": True,
                        "microphase_started": True,
                        "microphase_completed": True,
                        "target_lane": target_lane,
                        "lane_cursor_before": lane_cursor,
                        "lane_cursor_after": self._runtime_state["partial_candidate_lane_cursor"],
                        "candidate_source_name": candidate_source_name,
                        "candidate_source_count": candidate_source_count,
                        "candidate_snapshot_freshness": snapshot_freshness_str,
                        "candidate_rows_loaded": candidate_input_count,
                        "candidates_input": candidate_input_count,
                        "candidates_evaluated": evaluated_count,
                        "fresh": fresh_count,
                        "eligible": eligible_count,
                        "selected": eligible_count,
                        "order_ready": order_ready_count,
                        "first_causal_blocker": first_blocker,
                        "exact_blocker_reason": blocker_reason,
                        "provider_calls_added": provider_calls_added,
                        "broker_positions_consulted": True,
                        "broker_positions_used_as_candidate_input": False,
                        "same_cycle_duplicate_prevented": True,
                        "elapsed_ms": elapsed_ms,
                    }
                except Exception as exc:
                    partial_candidate_results = {"microphase_failed": True, "error": str(exc)[:180]}
                # Phase rotation: track partial cycle streak
                partial_streak = _to_int(self._runtime_state.get("partial_cycle_streak"), 0) + 1
                self._runtime_state["partial_cycle_streak"] = partial_streak
                self._runtime_state["last_full_cycle_at"] = self._runtime_state.get("last_full_cycle_at") or _now_iso()
                self._runtime_state["last_cycle_utc"] = _now_iso()
                self._runtime_state["last_cycle_summary"] = {
                    "ok": True, "orders_submitted": 0, "positions_closed": 0,
                    "cycle_reason": "legacy_market_evidence_bounded",
                    "legacy_swing_observation": legacy_canary_refresh,
                    "broker_reconciliation_active": bool(broker_snapshot.get("broker_reconciliation_active")),
                    "broker_positions_fetch_ok": bool(broker_snapshot.get("broker_positions_fetch_ok")),
                    "crypto_ranking_refresh": crypto_refresh,
                    "equity_risk_envelope_refresh": equity_risk_refresh,
                    "loss_containment_review_v1": loss_containment_review_partial,
                    "profit_protection_review_v1": profit_protection_review_partial,
                    "partial_cycle_streak": partial_streak,
                    "partial_candidate_microphase": partial_candidate_results,
                }
                self._runtime_state["last_execution_trace"] = {
                    "paper_worker_running": bool(self._thread and self._thread.is_alive()),
                    "candidates_seen": 0, "eligible_candidates": 0, "selected_candidates": 0,
                    "orders_attempted": 0, "orders_submitted": 0, "orders_rejected": 0,
                    "final_blocker_reason": "legacy_market_evidence_bounded",
                    "per_candidate_decision_trace": [], "legacy_swing_observation": legacy_canary_refresh,
                    "broker_reconciliation_active": bool(broker_snapshot.get("broker_reconciliation_active")),
                    "broker_positions_fetch_ok": bool(broker_snapshot.get("broker_positions_fetch_ok")),
                    "broker_open_positions_count": int(_to_int(broker_snapshot.get("broker_open_positions_count"), 0)),
                    "evidence_accumulation_capacity_v1": evidence_capacity_snapshot,
                    "crypto_ranking_refresh": crypto_refresh,
                    "equity_risk_envelope_refresh": equity_risk_refresh,
                    "loss_containment_review_v1": loss_containment_review_partial,
                    "profit_protection_review_v1": profit_protection_review_partial,
                    "live_trading_changed": False, "secrets_exposed": False,
                }
                self._note_worker_progress("legacy_market_evidence_checkpoint")
                self._save_state_file()
                return dict(self._runtime_state["last_cycle_summary"])
            self._note_worker_progress("safety_preflight")
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
            open_rows_initial = self._fetch_open_positions()
            internal_open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows_initial}
            self._note_worker_progress("broker_position_snapshot")
            broker_snapshot = self._broker_open_symbols_snapshot()
            broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
            broker_position_by_symbol = dict(broker_snapshot.get("broker_position_by_symbol") or {})
            self._note_worker_progress("entry_price_lineage_reconciliation")
            entry_price_lineage_refresh = self._reconcile_entry_price_lineage_v1(broker_snapshot)
            legacy_activation_refresh = self._refresh_legacy_forward_activations(broker_position_by_symbol)
            self._note_worker_progress("legacy_market_evidence")
            legacy_canary_refresh = self._refresh_legacy_swing_canary_pre_submit(broker_position_by_symbol)
            try:
                self._note_worker_progress("legacy_quarantine_review")
                quarantine_review = self._bounded_legacy_quarantine_review_phase(
                    open_rows=open_rows_initial,
                    broker_position_by_symbol=broker_position_by_symbol,
                    max_reviews=1,
                )
            except Exception as exc:
                quarantine_review = {"observation_state": "FAILED", "error": str(exc)[:180]}
            loss_containment_review: dict[str, Any] = {}
            try:
                self._note_worker_progress("loss_containment_review")
                latest_price_by_symbol: dict[str, dict[str, Any]] = {}
                for symbol, broker_pos in broker_position_by_symbol.items():
                    bp = dict(broker_pos or {})
                    price = _to_float(
                        bp.get("current_price"),
                        _to_float(bp.get("market_price"), _to_float(bp.get("lastday_price"), 0.0)),
                    )
                    if price > 0.0:
                        latest_price_by_symbol[str(symbol).upper()] = {
                            "symbol": str(symbol).upper(),
                            "price": price,
                            "timestamp": _now_iso(),
                            "source": "alpaca_broker_positions",
                            "provider_used": "alpaca_paper",
                        }
                loss_containment_review = self._loss_containment_review_phase(
                    open_rows=open_rows_initial,
                    broker_position_by_symbol=broker_position_by_symbol,
                    latest_price_by_symbol=latest_price_by_symbol,
                    max_positions=100,
                    broker_fetch_succeeded=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
                )
            except Exception as exc:
                loss_containment_review = {"observation_state": "FAILED", "error": str(exc)[:180]}
            profit_protection_review: dict[str, Any] = {}
            try:
                self._note_worker_progress("profit_protection_review")
                profit_protection_review = self._profit_protection_review_phase(
                    open_rows=open_rows_initial,
                    broker_position_by_symbol=broker_position_by_symbol,
                    max_positions=100,
                    broker_fetch_succeeded=bool(broker_snapshot.get("broker_positions_fetch_ok", False)),
                )
            except Exception as exc:
                profit_protection_review = {"observation_state": "FAILED", "error": str(exc)[:180]}
            # Market evidence is a restart-stable worker product.  Persist it
            # before the broader candidate scan, which may take longer than a
            # bounded provider refresh cycle.
            self._save_state_file()
            self._note_worker_progress("pending_exit_reconciliation")
            learned_exit_refresh = self._refresh_learned_exit_pending_sells()
            authorized_lane_exit_refresh = self._refresh_authorized_lane_exit_pending()
            self._note_worker_progress("open_position_review")
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
            broker_position_review_rows = [
                dict(row) for row in (evidence_capacity_snapshot.get("position_rows_for_read_only_consumers") or [])
                if isinstance(row, dict)
            ]
            # Normalize every worker-cycle observation before any early gate
            # can reject it.  The ranking and eligibility values are retained;
            # this only gives every candidate a stable operational lineage.
            self._note_worker_progress("candidate_collection")
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
                    early_symbol = str(row.get("symbol") or "").upper().strip()
                    early_asset = _norm_asset(row.get("asset_type") or "stock")
                    early_lane = str(row.get("lane_id") or ("CRYPTO" if early_asset == "crypto" else "SWING")).upper()
                    early_capacity = candidate_capacity_decision(
                        evidence_capacity_snapshot,
                        lane_id=early_lane,
                        symbol=early_symbol,
                        open_symbols=open_syms,
                    )
                    final_blocker_reason = final_blocker_reason or "max_new_positions_per_cycle_reached"
                    skipped += 1
                    decision_trace.append(_execution_trace_event(
                        row, eligible=False, selected=False,
                        decision_reason="max_new_positions_per_cycle_reached",
                        capacity_decision=early_capacity.get("capacity_decision"),
                        capacity_source=early_capacity.get("capacity_source"),
                        capacity_snapshot_id=early_capacity.get("snapshot_id"),
                        global_capacity_status=early_capacity.get("global_capacity_status"),
                        lane_reserve_status=early_capacity.get("lane_reserve_status"),
                        lane_reserve_enabled=early_capacity.get("reserve_enabled"),
                        lane_reserve_available=early_capacity.get("reserve_available"),
                        lane_capital_limit=early_capacity.get("configured_capital_limit"),
                        lane_capital_used=early_capacity.get("capital_used"),
                        lane_capital_remaining=early_capacity.get("capital_remaining"),
                        lane_position_limit=early_capacity.get("configured_position_limit"),
                        lane_positions_used=early_capacity.get("positions_used"),
                        lane_positions_remaining=early_capacity.get("positions_remaining"),
                        lane_open_position_count=early_capacity.get("open_position_count", 0),
                        lane_pending_order_count=early_capacity.get("pending_order_count", 0),
                        lane_active_commitment_count=early_capacity.get("active_commitment_count", 0),
                        capacity_blocker="max_new_positions_per_cycle_reached",
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
                capacity_snapshot=evidence_capacity_snapshot,
                current_candidates=candidates,
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
                commitment = self._request_lane_reserve_commitment(
                    row,
                    evidence_capacity_snapshot,
                    cycle_id=cycle_id,
                )
                row_trace["commitment_id"] = str(commitment.get("commitment_id") or "")
                row_trace["active_commitment_id"] = row_trace["commitment_id"]
                row_trace["commitment_state"] = str(commitment.get("commitment_state") or "NOT_REQUIRED")
                row_trace["commitment_reason"] = str(commitment.get("reason") or "")
                if not commitment.get("allowed"):
                    skipped += 1
                    row_trace["selected"] = False
                    row_trace["order_attempted"] = False
                    row_trace["decision_reason"] = "NOT_FINAL_SELECTED_CANDIDATE"
                    row_trace["capacity_blocker"] = str(commitment.get("reason") or "LANE_RESERVE_EXHAUSTED")
                    decision_trace.append(row_trace)
                    final_blocker_reason = row_trace["capacity_blocker"]
                    continue
                selected_count += 1
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
                    if commitment.get("commitment_id"):
                        committed_state = "CONVERTED_TO_OPEN_POSITION" if opened_row.get("entry_fill_id") else "CONVERTED_TO_PENDING_ORDER"
                        self._convert_lane_reserve_commitment(
                            candidate_lane,
                            str(commitment.get("commitment_id")),
                            committed_state,
                            str(opened_row.get("broker_order_id") or ""),
                        )
                        row_trace["commitment_state"] = committed_state
                    if asset != "crypto":
                        horizon_capacity = self._consume_horizon_capacity(horizon_capacity, candidate_horizon)
                else:
                    if commitment.get("commitment_id"):
                        self._release_lane_reserve_commitment(
                            candidate_lane,
                            str(commitment.get("commitment_id")),
                            str(opened_row.get("broker_error") or opened_row.get("error") or "submission_rejected"),
                        )
                        row_trace["commitment_state"] = "RELEASED"
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
                "broker_positions_fetch_ok": bool(broker_positions_fetch_ok),
                "entry_price_lineage_reconciliation": entry_price_lineage_refresh,
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
                "broker_orders_fetch_ok": bool(broker_snapshot.get("broker_orders_fetch_ok")),
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
                "legacy_quarantine_review_v1": dict(quarantine_review or {}),
                "loss_containment_review_v1": dict(loss_containment_review or {}),
                "profit_protection_review_v1": dict(profit_protection_review or {}),
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
                "legacy_quarantine_review_v1": dict(quarantine_review or {}),
                "loss_containment_review_v1": dict(loss_containment_review or {}),
                "profit_protection_review_v1": dict(profit_protection_review or {}),
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
            # Reuse the worker as the existing scheduler. The audit observes
            # a completed trace only and has no broker/provider side effects.
            if MarketHoursAuditRegistry is not None:
                try:
                    audit = MarketHoursAuditRegistry(os.path.dirname(self.db_path) or "state").record_if_due(trace)
                    if audit:
                        self._runtime_state["automated_market_hours_multilane_audit_v1"] = audit
                except Exception:
                    pass
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
                capacity_snapshot=canonical_capacity,
                current_candidates=candidates,
            )
            if capacity_decision:
                trace["canonical_capacity_snapshot"] = canonical_capacity
            trace["dry_run_only"] = True
            trace["submit_order"] = False
            trace["broker_actions_used"] = 0
            trace["broker_reconciliation_deferred_to_execution"] = True
            if allowed:
                eligible += 1
                reserve_allowed = bool(
                    capacity_decision
                    and capacity_decision.get("capacity_decision") in {"AVAILABLE", "AVAILABLE_FROM_LANE_RESERVE"}
                )
                if selected < self.max_new_positions_per_cycle and (total_capacity > 0 or reserve_allowed):
                    commitment = self._request_lane_reserve_commitment(
                        row,
                        canonical_capacity,
                        cycle_id=f"dry_run:{_now_iso()}",
                    ) if canonical_capacity else {"required": False, "allowed": True, "commitment_state": "NOT_REQUIRED"}
                    trace["commitment_id"] = str(commitment.get("commitment_id") or "")
                    trace["commitment_state"] = str(commitment.get("commitment_state") or "NOT_REQUIRED")
                    if commitment.get("allowed"):
                        selected += 1
                        trace["selected"] = True
                        trace["selection_reason"] = "existing_paper_autopilot_gates_passed"
                    else:
                        trace["selected"] = False
                        trace["selection_reason"] = "NOT_FINAL_SELECTED_CANDIDATE"
                        trace["commitment_reason"] = str(commitment.get("reason") or "LANE_RESERVE_EXHAUSTED")
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
            contract = dict(trace.get("pretrade_decision_contract") or {})
            contract.setdefault("consumer_acknowledgements", {})["order_ready_gate"] = True
            contract["consumer_acknowledgements"]["order_ready_status"] = (
                "CONSUMED_ORDER_READY" if trace["order_ready"] else "CONSUMED_BLOCKED"
            )
            if trace["order_ready"]:
                contract["candidate_terminal_state"] = "ORDER_READY"
            elif trace.get("selected"):
                contract["candidate_terminal_state"] = "SELECTED"
            trace["pretrade_decision_contract"] = contract
            trace["candidate_terminal_state"] = str(contract.get("candidate_terminal_state") or trace.get("candidate_terminal_state") or "CONTRACT_BUILDING")
            if not trace["order_ready"]:
                blockers[trace["order_readiness_reason"]] = blockers.get(trace["order_readiness_reason"], 0) + 1
            if trace.get("commitment_id"):
                # Dry-run verifies the real reservation boundary but never
                # leaves occupancy behind or reaches a broker order path.
                self._release_lane_reserve_commitment(
                    lane,
                    str(trace.get("commitment_id")),
                    "dry_run_complete_no_broker_submission",
                )
                trace["commitment_final_state"] = "RELEASED"
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
                current_candidates=candidates,
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
                current_candidates=candidates,
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
