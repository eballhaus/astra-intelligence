"""Broad FMP Collection Planner V1.

Planning/governance only. This module does not call FMP, write market data, or
enable broad collection workers.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


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
        self.collection_enabled = False
        self.allowed_fmp_roles = [
            "historical_ohlcv",
            "fundamentals",
            "financial_ratios",
            "earnings_calendar_and_history",
            "sector_industry_classification",
            "company_profile",
            "replay_counterfactual_enrichment",
        ]

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
        stock_etf = [r for r in candidates if str(r.get("asset_type")) in {"stock", "etf", "equity"}][:12]
        crypto = [r for r in candidates if str(r.get("asset_type")) == "crypto"][:6]
        if not crypto:
            crypto = [{"symbol": "BTCUSD", "asset_type": "crypto"}, {"symbol": "ETHUSD", "asset_type": "crypto"}]
        batches = [
            {
                "batch_id": "liquid_stock_etf_history_v1",
                "asset_types": ["stock", "etf"],
                "symbols": [r["symbol"] for r in stock_etf],
                "data_types": ["historical_ohlcv"],
                "provider": "financial_modeling_prep",
                "estimated_calls": max(1, min(12, len(stock_etf))),
                "estimated_bandwidth_kb": 2048,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
            {
                "batch_id": "liquid_stock_etf_fundamentals_v1",
                "asset_types": ["stock", "etf"],
                "symbols": [r["symbol"] for r in stock_etf[:8]],
                "data_types": ["fundamentals", "ratios", "company_profile", "sector_industry"],
                "provider": "financial_modeling_prep",
                "estimated_calls": max(1, min(16, len(stock_etf[:8]) * 2)),
                "estimated_bandwidth_kb": 1536,
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
                "estimated_calls": max(1, min(6, len(crypto))),
                "estimated_bandwidth_kb": 1024,
                "overlap_safe": True,
                "blocked_live_quote_overlap": True,
            },
        ]
        return batches

    def _summary(self) -> tuple[list[dict[str, Any]], int, float]:
        batches = self._planned_batches()
        planned_calls = sum(_to_int(b.get("estimated_calls"), 0) for b in batches)
        bandwidth = sum(_to_float(b.get("estimated_bandwidth_kb"), 0.0) for b in batches)
        return batches, int(planned_calls), round(float(bandwidth), 3)

    def status(self) -> dict[str, Any]:
        allowed, blocked_reason, optimizer = self._quota_gate()
        batches, planned_calls, bandwidth = self._summary()
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "planning_only",
            "local_only": True,
            "writes_files": False,
            "collection_enabled": False,
            "api_calls_used": 0,
            "planned_calls": planned_calls,
            "estimated_bandwidth": bandwidth,
            "blocked_reason": "" if allowed else blocked_reason,
            "next_recommended_action": "review_plan_and_enable_explicit_worker_later" if allowed else "keep_collection_disabled_and_use_cache_first_plan",
            "broad_fmp_collection_status_v1": True,
            "allowed_fmp_non_overlap_roles": list(self.allowed_fmp_roles),
            "fmp_duplicate_live_quote_blocked": True,
            "alpaca_iex_live_quote_ownership": True,
            "optimizer_snapshot": optimizer,
            "planned_batch_count": len(batches),
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
