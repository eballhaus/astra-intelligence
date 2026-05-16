"""Broad FMP Collection Planner V1.

Planning/governance only. This module does not call FMP, write market data, or
enable broad collection workers.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.1.0"
BROAD_UNIVERSE_TARGET_COUNT = 7500
ACTIVE_UNIVERSE_TARGET_COUNT = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


class BroadFmpCollectionPlanner:
    """Builds staged, quota-aware FMP collection plans without executing them."""

    def __init__(self, state_dir: str = "state", fmp_optimizer: Any | None = None, orchestration_engine: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.fmp_optimizer = fmp_optimizer
        self.orchestration_engine = orchestration_engine
        self.universe_path = os.path.join("astra_dashboard", "universe", "universe_cache.json")
        self.warehouse_manifest_path = os.path.join(self.state_dir, "market_data_warehouse_manifest_v1.json")
        self.fmp_cache_path = os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json")
        self.collection_enabled = True
        self.small_batch_limit = 25
        self.broad_universe_target_count = BROAD_UNIVERSE_TARGET_COUNT
        self.active_universe_target_count = ACTIVE_UNIVERSE_TARGET_COUNT
        self.allowed_fmp_roles = [
            "historical_ohlcv",
            "fundamentals",
            "financial_ratios",
            "earnings_calendar_and_history",
            "sector_industry_classification",
            "company_profile",
            "replay_counterfactual_enrichment",
            "broad_universe_discovery",
        ]

    def _collection_progress(self) -> dict[str, Any]:
        manifest = self._read_json(self.warehouse_manifest_path)
        symbols = manifest.get("symbols") if isinstance(manifest.get("symbols"), dict) else {}
        rows = list(symbols.values()) if isinstance(symbols, dict) else []
        history = 0
        fundamentals = 0
        earnings = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            data_types = row.get("data_types_available") or row.get("data_types") or []
            if isinstance(data_types, str):
                data_types = [data_types]
            data_type_text = " ".join(str(v).lower() for v in data_types)
            history += 1 if "history" in data_type_text or "ohlcv" in data_type_text else 0
            fundamentals += 1 if "fundamental" in data_type_text or "ratio" in data_type_text else 0
            earnings += 1 if "earning" in data_type_text else 0
        return {
            "symbols_processed": len(rows),
            "history_collected": history,
            "fundamentals_collected": fundamentals,
            "earnings_collected": earnings,
            "bandwidth_used": 0,
            "calls_used": 0,
        }

    def _coverage_fields(self, collected_count: int, active_current_count: int) -> dict[str, Any]:
        target = max(1, int(self.broad_universe_target_count))
        collected = max(0, int(collected_count))
        return {
            "broad_universe_target_count": int(self.broad_universe_target_count),
            "broad_universe_collected_count": collected,
            "active_universe_target_count": int(self.active_universe_target_count),
            "active_universe_current_count": max(0, int(active_current_count)),
            "collection_progress_pct": round(min(100.0, (collected / target) * 100.0), 3),
            "target_coverage": {
                "large_caps": {"target_symbols": 1500, "priority": 1},
                "mid_caps": {"target_symbols": 2000, "priority": 2},
                "small_caps": {"target_symbols": 2500, "priority": 3},
                "etfs": {"target_symbols": 1000, "priority": 4},
                "crypto_where_supported": {"target_symbols": 500, "priority": 5},
            },
        }

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _optimizer_status(self) -> dict[str, Any]:
        if self.fmp_optimizer is None:
            return {
                "enabled": False,
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_unavailable",
            }
        try:
            payload = self.fmp_optimizer.status()
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            return {
                "enabled": False,
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_error",
                "error": f"fmp_optimizer_unavailable: {exc}",
            }

    def _quota_gate(self) -> tuple[bool, str, dict[str, Any]]:
        status = self._optimizer_status()
        usage = _to_float(status.get("current_usage_pct_estimated"), 0.0)
        hard_stop = bool(status.get("hard_stop_active")) or bool(status.get("emergency_cutoff_active")) or usage >= 80.0
        soft_throttle = bool(status.get("soft_throttle_active")) or usage >= 70.0
        if hard_stop:
            return False, "fmp_optimizer_hard_stop_or_denial", status
        if soft_throttle:
            return False, "fmp_optimizer_soft_throttle_active", status
        if not self.collection_enabled:
            return False, "broad_collection_disabled_by_default", status
        return True, "", status

    def _controlled_enablement_state(self, optimizer: dict[str, Any]) -> dict[str, Any]:
        usage = _to_float(optimizer.get("current_usage_pct_estimated"), 0.0)
        hard_stop = bool(optimizer.get("hard_stop_active")) or bool(optimizer.get("emergency_cutoff_active")) or usage >= 80.0
        soft_throttle = bool(optimizer.get("soft_throttle_active")) or usage >= 70.0
        optimizer_allows = not hard_stop and not soft_throttle
        return {
            "controlled_enablement_available": bool(optimizer_allows),
            "controlled_enablement_active": True,
            "enablement_requires_explicit_operator_action": False,
            "small_batch_limit": int(self.small_batch_limit),
            "uncontrolled_bulk_collection_enabled": False,
            "quota_governed_by": "FmpUtilizationOptimizer",
            "target_utilization_pct": 70.0,
            "soft_throttle_above_pct": 70.0,
            "hard_stop_above_pct": 80.0,
            "minimum_reserve_pct": 20.0,
            "optimizer_allows_controlled_collection": bool(optimizer_allows),
        }

    def _symbol_candidates(self) -> list[dict[str, Any]]:
        universe = self._read_json(self.universe_path)
        symbols: list[dict[str, Any]] = []
        raw = universe.get("symbols") or universe.get("stocks") or universe.get("universe") or []
        if isinstance(raw, dict):
            raw = list(raw.values())
        for item in raw:
            if isinstance(item, str):
                symbol = item.strip().upper()
                asset_type = "stock"
                volume = 0.0
            elif isinstance(item, dict):
                symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
                asset_type = str(item.get("asset_type") or item.get("type") or "stock").lower()
                volume = _to_float(item.get("volume"), _to_float(item.get("avg_volume"), 0.0))
            else:
                continue
            if not symbol:
                continue
            symbols.append({"symbol": symbol, "asset_type": asset_type, "liquidity_score": min(100.0, volume / 1_000_000.0)})
        if not symbols:
            symbols = [
                {"symbol": "AAPL", "asset_type": "stock", "liquidity_score": 100.0},
                {"symbol": "NVDA", "asset_type": "stock", "liquidity_score": 100.0},
                {"symbol": "MSFT", "asset_type": "stock", "liquidity_score": 100.0},
                {"symbol": "SPY", "asset_type": "etf", "liquidity_score": 100.0},
                {"symbol": "QQQ", "asset_type": "etf", "liquidity_score": 100.0},
                {"symbol": "BTCUSD", "asset_type": "crypto", "liquidity_score": 100.0},
            ]
        return sorted(symbols, key=lambda row: _to_float(row.get("liquidity_score"), 0.0), reverse=True)[:60]

    def _planned_batches(self) -> list[dict[str, Any]]:
        candidates = self._symbol_candidates()
        stock_etf = [r for r in candidates if str(r.get("asset_type")) in {"stock", "etf", "equity"}][: self.small_batch_limit]
        crypto = [r for r in candidates if str(r.get("asset_type")) == "crypto"][: min(10, self.small_batch_limit)]
        if not crypto:
            crypto = [{"symbol": "BTCUSD", "asset_type": "crypto"}, {"symbol": "ETHUSD", "asset_type": "crypto"}]
        batches = [
            {
                "batch_id": "broad_universe_discovery_v1",
                "asset_types": ["stock", "etf", "crypto"],
                "symbols": [],
                "data_types": ["broad_universe_discovery", "liquidity_screen", "sector_industry"],
                "provider": "financial_modeling_prep",
                "estimated_calls": 3,
                "estimated_bandwidth_kb": 768,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
                "batch_scope": "discover_target_4000_to_10000_symbols_without_live_quotes",
            },
            {
                "batch_id": "liquid_stock_etf_history_v1",
                "asset_types": ["stock", "etf"],
                "symbols": [r["symbol"] for r in stock_etf],
                "data_types": ["historical_ohlcv"],
                "provider": "financial_modeling_prep",
                "estimated_calls": max(1, min(self.small_batch_limit, len(stock_etf))),
                "estimated_bandwidth_kb": 4096,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
            {
                "batch_id": "liquid_stock_etf_fundamentals_v1",
                "asset_types": ["stock", "etf"],
                "symbols": [r["symbol"] for r in stock_etf[:8]],
                "data_types": ["fundamentals", "ratios", "company_profile", "sector_industry"],
                "provider": "financial_modeling_prep",
                "estimated_calls": max(1, min(self.small_batch_limit, len(stock_etf[:8]) * 2)),
                "estimated_bandwidth_kb": 3072,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
            {
                "batch_id": "earnings_catalyst_calendar_v1",
                "asset_types": ["stock", "etf"],
                "symbols": [r["symbol"] for r in stock_etf[:12]],
                "data_types": ["earnings_calendar", "earnings_history"],
                "provider": "financial_modeling_prep",
                "estimated_calls": 2,
                "estimated_bandwidth_kb": 512,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
            {
                "batch_id": "crypto_history_v1",
                "asset_types": ["crypto"],
                "symbols": [r["symbol"] for r in crypto],
                "data_types": ["historical_ohlcv", "replay_counterfactual_data"],
                "provider": "financial_modeling_prep_where_supported",
                "estimated_calls": max(1, min(10, len(crypto))),
                "estimated_bandwidth_kb": 1024,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
        ]
        return batches

    def broad_universe_funnel(self) -> dict[str, Any]:
        candidates = self._symbol_candidates()
        scored: list[dict[str, Any]] = []
        rejected_reason_counts: dict[str, int] = {
            "missing_symbol": 0,
            "unsupported_asset_type": 0,
            "low_liquidity": 0,
            "insufficient_data_completeness": 0,
        }
        for row in candidates:
            symbol = str(row.get("symbol") or "").strip().upper()
            asset_type = str(row.get("asset_type") or "stock").lower()
            if not symbol:
                rejected_reason_counts["missing_symbol"] += 1
                continue
            if asset_type not in {"stock", "equity", "etf", "crypto"}:
                rejected_reason_counts["unsupported_asset_type"] += 1
                continue
            liquidity = _to_float(row.get("liquidity_score"), 0.0)
            if liquidity < 1.0 and len(candidates) > 20:
                rejected_reason_counts["low_liquidity"] += 1
                continue
            data_completeness = 50.0 + min(25.0, liquidity / 4.0)
            score = (
                min(100.0, liquidity) * 0.25
                + data_completeness * 0.20
                + 55.0 * 0.15  # volatility readiness placeholder from metadata only
                + 55.0 * 0.15  # momentum readiness placeholder from metadata only
                + 55.0 * 0.10  # sector leadership placeholder from metadata only
                + 50.0 * 0.10  # catalyst/earnings relevance placeholder from metadata only
                + 80.0 * 0.05  # provider reliability, gated by optimizer/overlap policy
            )
            scored.append(
                {
                    "symbol": symbol,
                    "asset_type": "stock" if asset_type == "equity" else asset_type,
                    "active_universe_score": round(score, 3),
                    "selection_reasons": [
                        "liquidity_ranked",
                        "metadata_complete_enough_for_staged_collection",
                        "non_overlap_fmp_data_needed",
                        "eligible_for_active_universe_planning",
                    ],
                    "funnel_inputs": {
                        "liquidity": round(liquidity, 3),
                        "volume": "metadata_or_future_feature",
                        "price_validity": "planned_cache_first_check",
                        "volatility": "planned_feature",
                        "momentum": "planned_feature",
                        "sector_leadership": "planned_feature",
                        "catalyst_earnings_relevance": "planned_feature",
                        "data_completeness": round(data_completeness, 3),
                        "feature_availability": "planned_feature_store",
                        "provider_reliability": "optimizer_and_provider_policy_guarded",
                    },
                }
            )
        scored = sorted(scored, key=lambda r: _to_float(r.get("active_universe_score"), 0.0), reverse=True)
        selected = scored[: self.active_universe_target_count]
        allowed, blocked_reason, optimizer = self._quota_gate()
        progress = self._collection_progress()
        return {
            "enabled": True,
            "version": VERSION,
            "broad_universe_funnel_status_v1": True,
            "mode": "controlled_staged_planning",
            "local_only": True,
            "writes_files": False,
            "collection_enabled": True,
            "api_calls_used": 0,
            "planned_calls": self._summary()[1],
            "estimated_bandwidth": self._summary()[2],
            "quota_state": optimizer,
            "blocked_reason": "" if allowed else blocked_reason,
            **self._coverage_fields(progress.get("symbols_processed", 0), len(selected)),
            "broad_candidates_count": int(self.broad_universe_target_count),
            "active_universe_candidates_count": len(scored),
            "selected_active_universe_count": len(selected),
            "selection_reasons": [
                "liquidity",
                "volume",
                "price_validity",
                "volatility",
                "momentum",
                "sector_leadership",
                "catalyst_earnings_relevance",
                "data_completeness",
                "feature_availability",
                "provider_reliability",
            ],
            "rejected_reason_counts": rejected_reason_counts,
            "selected_active_universe_sample": selected[:25],
            "does_not_replace_live_rankings": True,
            "next_recommended_action": "use_funnel_output_to_prepare_active_universe_manifest_after_governed_collection",
        }

    def _summary(self) -> tuple[list[dict[str, Any]], int, float]:
        batches = self._planned_batches()
        planned_calls = sum(_to_int(b.get("estimated_calls"), 0) for b in batches)
        bandwidth = sum(_to_float(b.get("estimated_bandwidth_kb"), 0.0) for b in batches)
        return batches, int(planned_calls), round(float(bandwidth), 3)

    def status(self) -> dict[str, Any]:
        allowed, blocked_reason, optimizer = self._quota_gate()
        batches, planned_calls, bandwidth = self._summary()
        progress = self._collection_progress()
        enablement = self._controlled_enablement_state(optimizer)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "controlled_staged_planning",
            "local_only": True,
            "writes_files": False,
            "collection_enabled": True,
            "api_calls_used": 0,
            "planned_calls": planned_calls,
            "estimated_bandwidth": bandwidth,
            "blocked_reason": "" if allowed else blocked_reason,
            "next_recommended_action": "run_next_small_cache_first_batch_when_worker_is_explicitly_invoked" if allowed else "hold_collection_until_optimizer_allows",
            "broad_fmp_collection_status_v1": True,
            "allowed_fmp_non_overlap_roles": list(self.allowed_fmp_roles),
            "fmp_duplicate_live_quote_blocked": True,
            "alpaca_iex_live_quote_ownership": True,
            "optimizer_snapshot": optimizer,
            "planned_batch_count": len(batches),
            "quota_state": optimizer,
            "execution_allowed_now": bool(allowed),
            "full_broad_collection_target_enabled": True,
            "controlled_staged_collection_only": True,
            "no_uncontrolled_worker_loop": True,
            "no_immediate_bulk_collection": True,
            "fmp_live_quote_overlap_blocked": True,
            "api_efficiency_controls": {
                "delta_only_refresh_required": True,
                "batch_endpoint_preferred": True,
                "smart_ttl_policy_required": True,
                "deduplication_request_keys_required": True,
                "synthetic_replay_uses_existing_stored_data_only": True,
            },
            "target_architecture": "4000_to_10000_broad_symbols_to_200_active_universe_to_ranked_candidates_to_top_6",
            **self._coverage_fields(progress.get("symbols_processed", 0), len(self._symbol_candidates())),
            **progress,
            **enablement,
        }

    def plan(self) -> dict[str, Any]:
        allowed, blocked_reason, optimizer = self._quota_gate()
        batches, planned_calls, bandwidth = self._summary()
        return {
            **self.status(),
            "broad_fmp_collection_plan_v1": True,
            "execution_allowed_now": bool(allowed),
            "blocked_reason": "" if allowed else blocked_reason,
            "planned_batches": batches,
            "planned_calls": planned_calls,
            "estimated_bandwidth": bandwidth,
            "optimizer_snapshot": optimizer,
            "cache_first_checks": {
                "warehouse_manifest_exists": os.path.exists(self.warehouse_manifest_path),
                "fmp_enrichment_cache_exists": os.path.exists(self.fmp_cache_path),
            },
        }
