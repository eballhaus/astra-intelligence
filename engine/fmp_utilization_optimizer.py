"""FMP Utilization Optimizer V1 (recommendation/plan mode only)."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class FmpUtilizationOptimizer:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.usage_path = os.path.join(self.state_dir, "fmp_usage_state.json")
        self.eff_manifest_path = os.path.join(self.state_dir, "fmp_efficiency_manifest_v1.json")
        self.cache_path = os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json")
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self.ttl_seconds = 45.0
        self.target_usage_pct = 60.0
        self.safety_reserve_pct = 40.0

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def status(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            if not force_refresh and self._cache and (now - self._cache_ts) <= self.ttl_seconds:
                return dict(self._cache)
        usage = self._read_json(self.usage_path)
        manifest = self._read_json(self.eff_manifest_path)
        cache = self._read_json(self.cache_path)
        bytes_est = _to_float(manifest.get("total_bytes_estimated"), _to_float(usage.get("estimated_fmp_bytes_today"), 0.0))
        calls = _to_float(manifest.get("total_fmp_calls_tracked"), _to_float(usage.get("fmp_calls_today"), 0.0))
        daily_cap = max(bytes_est, _to_float(usage.get("daily_byte_soft_cap"), _to_float(usage.get("daily_estimated_byte_soft_cap"), 1_000_000.0)), 1.0)
        usage_pct = min(100.0, (bytes_est / daily_cap) * 100.0)
        remaining_to_target = max(0.0, self.target_usage_pct - usage_pct)
        emergency_cutoff = usage_pct >= self.target_usage_pct
        payload = {
            "enabled": True,
            "mode": "recommendation_plan_only",
            "fmp_utilization_status_v1": True,
            "institutional_intelligence_bundle_3": True,
            "local_only": True,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "target_usage_pct": self.target_usage_pct,
            "safety_reserve_pct": self.safety_reserve_pct,
            "current_usage_pct_estimated": round(usage_pct, 3),
            "remaining_to_target_pct": round(remaining_to_target, 3),
            "total_fmp_calls_tracked": int(calls),
            "total_bytes_estimated": int(bytes_est),
            "cache_entries_estimated": len(cache) if isinstance(cache, dict) else 0,
            "emergency_cutoff_active": bool(emergency_cutoff),
            "hot_path_expansion_allowed": False,
            "live_provider_call_increase_allowed": False,
            "endpoint_budgets_by_priority": {
                "profile": "low_byte_cache_first",
                "ratios_key_metrics": "medium_priority_cache_first",
                "analyst_estimates_price_targets": "opportunistic_cache_first",
                "earnings_calendar": "low_frequency_only",
                "news_catalyst_context": "strict_symbol_ttl_only",
                "institutional_insider_context": "disabled_until_cost_verified",
            },
            "recommendation": "hold_usage" if emergency_cutoff else "cache_first_controlled_enrichment_only",
        }
        with self._lock:
            self._cache = dict(payload)
            self._cache_ts = time.time()
        return payload

    def plan(self) -> dict[str, Any]:
        status = self.status()
        actions = [
            "keep rankings/top_buys hot path cache-only",
            "use profile and ratios only through governed enrichment jobs",
            "avoid repeated symbol/context calls inside TTL",
            "stop all optional FMP expansion at 60 percent target usage",
        ]
        if status.get("emergency_cutoff_active"):
            actions = ["pause optional FMP enrichment until usage drops below target"]
        return {
            **status,
            "fmp_utilization_plan_v1": True,
            "institutional_intelligence_bundle_3": True,
            "planned_actions": actions,
            "would_increase_calls_now": False,
        }
