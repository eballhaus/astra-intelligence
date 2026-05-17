"""API Budget Guard V1.

Planning/status layer only. It tracks intended refresh pressure from local
snapshots and blocks duplicate or high-pressure refresh plans without making
provider calls.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {} if default is None else default


def _file_age(path: str) -> float | None:
    try:
        return max(0.0, time.time() - os.path.getmtime(path))
    except Exception:
        return None


class ApiBudgetGuard:
    def __init__(self, state_dir: str = "state", *, fmp_optimizer: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.fmp_optimizer = fmp_optimizer
        self.mode = "planning_guard_only"
        self.default_symbol_ttl = {
            "active_position_quote": 15,
            "normal_position_quote": 30,
            "top_6_quote": 120,
            "active_universe_quote": 900,
            "broad_universe_quote": 86400,
            "learning_snapshot": 21600,
            "advanced_metrics": 21600,
        }

    def _fmp_state(self) -> dict[str, Any]:
        if self.fmp_optimizer is not None:
            try:
                status = self.fmp_optimizer.status()
                if isinstance(status, dict):
                    return status
            except Exception:
                pass
        return _read_json(os.path.join(self.state_dir, "fmp_usage_state.json"), default={}) or {}

    def status(self, *, planned_requests: list[dict[str, Any]] | None = None, market_status: str = "unknown") -> dict[str, Any]:
        planned = [r for r in list(planned_requests or []) if isinstance(r, dict)]
        seen: set[tuple[str, str, str]] = set()
        allowed: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        fmp_state = self._fmp_state()
        hard_stop = bool(fmp_state.get("hard_stop_active") or fmp_state.get("fmp_hard_stop_active"))
        soft_throttle = bool(fmp_state.get("soft_throttle_active") or fmp_state.get("fmp_soft_throttle_active"))
        pressure = "normal"
        if hard_stop:
            pressure = "hard_stop"
        elif soft_throttle:
            pressure = "soft_throttle"
        for req in planned:
            provider = str(req.get("provider") or "unknown").lower()
            symbol = str(req.get("symbol") or "*").upper()
            data_type = str(req.get("data_type") or "quote").lower()
            key = (provider, symbol, data_type)
            reason = ""
            if key in seen:
                reason = "duplicate_symbol_data_type_window"
            elif provider == "fmp" and hard_stop:
                reason = "fmp_optimizer_hard_stop"
            elif provider == "fmp" and data_type in {"live_quote", "quote"} and bool(req.get("alpaca_iex_owned", False)):
                reason = "fmp_alpaca_live_quote_overlap_prevented"
            elif soft_throttle and str(req.get("priority") or "").lower() not in {"critical", "active_position"}:
                reason = "budget_pressure_soft_throttle"
            if reason:
                b = dict(req)
                b["blocked_reason"] = reason
                blocked.append(b)
            else:
                allowed.append(dict(req))
                seen.add(key)
        est_bytes = sum(int(float(r.get("estimated_bytes") or 1200)) for r in allowed)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "market_status": market_status,
            "api_budget_guard_status_v1": True,
            "api_calls_used": 0,
            "planned_calls": len(planned),
            "allowed_planned_calls": len(allowed),
            "calls_blocked": len(blocked),
            "blocked_requests": blocked[:50],
            "allowed_requests": allowed[:50],
            "bandwidth_estimate": est_bytes,
            "estimated_bandwidth_bytes": est_bytes,
            "budget_pressure": pressure,
            "cache_hit_rate": None,
            "duplicate_call_prevention_enabled": True,
            "fmp_optimizer_respected": True,
            "provider_overlap_prevention_active": True,
            "default_symbol_ttl_seconds": dict(self.default_symbol_ttl),
            "generated_at": _now_iso(),
            "next_recommended_action": "execute_only_allowed_refreshes_in_future_worker_and_keep_ui_snapshot_first",
        }
