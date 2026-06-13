from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 20.0
MAX_JSONL_ROWS = 200
MAX_JSONL_BYTES = 1_000_000


SAFETY_FLAGS: dict[str, Any] = {
    "behavior_safe_to_apply": False,
    "shadow_analysis_mode": True,
    "advisory_only": True,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "ranking_behavior_changed": False,
    "promotion_logic_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "paper_execution_changed": False,
    "api_calls_used": 0,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(to_float(value, default))
    except Exception:
        return int(default)


def clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, to_float(value, low)))


def rounded(value: Any, digits: int = 3) -> float:
    return round(to_float(value), digits)


def text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        return value
    return default


def status_value(statuses: dict[str, Any], key: str) -> dict[str, Any]:
    value = (statuses or {}).get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def with_safety(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload or {})
    out.update(SAFETY_FLAGS)
    return out


def read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def tail_jsonl(path: str, max_rows: int = MAX_JSONL_ROWS, max_bytes: int = MAX_JSONL_BYTES) -> list[dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return []
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            if size > max_bytes:
                handle.seek(max(0, size - max_bytes))
                handle.readline()
            raw = handle.read().decode("utf-8", errors="ignore")
        rows: list[dict[str, Any]] = []
        for line in raw.splitlines()[-max_rows:]:
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    rows.append(parsed)
            except Exception:
                continue
        return rows
    except Exception:
        return []


def append_jsonl_if_new(path: str, payload: dict[str, Any], key: str = "snapshot_key") -> bool:
    try:
        last_rows = tail_jsonl(path, max_rows=1, max_bytes=64_000)
        if last_rows and key and last_rows[-1].get(key) == payload.get(key):
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        return True
    except Exception:
        return False


class CachedDiagnosticModule:
    module_name = "diagnostic_module"
    mode = "shadow_analysis"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", f"{self.module_name}.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _fallback(self, reason: str = "insufficient_evidence", **extra: Any) -> dict[str, Any]:
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "degraded_reason": reason,
        }
        payload.update(extra)
        return with_safety(payload)

    def _cached(self, force: bool) -> dict[str, Any] | None:
        now = time.time()
        if not force and self._cache and now - self._cache_ts <= self.ttl_seconds:
            return dict(self._cache)
        if not force:
            cached = read_json(self.cache_path)
            if cached:
                self._cache = dict(cached)
                self._cache_ts = now
                return dict(cached)
        return None

    def _store(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = with_safety(payload)
        self._cache = dict(out)
        self._cache_ts = time.time()
        write_json(self.cache_path, out)
        return out

    def status(self, statuses: dict[str, Any] | None = None, force: bool = False) -> dict[str, Any]:
        cached = self._cached(force)
        if cached is not None:
            return with_safety(cached)
        try:
            return self._store(self._build(dict(statuses or {})))
        except Exception as exc:
            return self._fallback(f"{self.module_name}_failed:{str(exc)[:140]}")

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


def evidence_count_from(statuses: dict[str, Any]) -> int:
    perf = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
    ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
    unified = status_value(statuses, "unified_learning_diagnostics_v1")
    return max(
        to_int(perf.get("canonical_closed_trade_count"), 0),
        to_int(perf.get("paper_trade_count"), 0),
        to_int(ranking.get("evidence_count"), 0),
        to_int(unified.get("evidence_count"), 0),
    )


def pick_max(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    try:
        return max(rows, key=lambda row: to_float(row.get(key), 0.0))
    except Exception:
        return {}


def pick_min(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    try:
        return min(rows, key=lambda row: to_float(row.get(key), 0.0))
    except Exception:
        return {}


def safe_average(values: list[Any], default: float = 0.0) -> float:
    nums = [to_float(value, default) for value in values if value is not None]
    return sum(nums) / max(1, len(nums)) if nums else float(default)


def status_score(statuses: dict[str, Any], key: str, fields: list[str], default: float = 50.0) -> float:
    payload = status_value(statuses, key)
    for field in fields:
        if field in payload:
            return clamp(payload.get(field), 0.0, 100.0)
    return float(default)


def module_row(
    statuses: dict[str, Any],
    name: str,
    key: str,
    evidence_fields: list[str],
    contribution_fields: list[str],
    capture_fields: list[str] | None = None,
    priority_hint: str = "monitor",
) -> dict[str, Any]:
    payload = status_value(statuses, key)
    evidence = max([to_int(payload.get(field), 0) for field in evidence_fields] + [0])
    contribution = status_score(statuses, key, contribution_fields, 50.0)
    capture = status_score(statuses, key, capture_fields or contribution_fields, contribution)
    evidence_weight = min(20.0, evidence / 100.0)
    confidence = clamp(contribution * 0.65 + capture * 0.20 + evidence_weight)
    return {
        "subsystem_name": name,
        "status_key": key,
        "evidence_count": int(evidence),
        "estimated_pf_contribution": rounded(contribution * 0.018, 4),
        "estimated_ranking_contribution": rounded(status_score(statuses, key, ["ranking_quality_score", "ranking_predictive_power", *contribution_fields], contribution) * 0.1, 3),
        "estimated_buy_purity_contribution": rounded(status_score(statuses, key, ["buy_purity", "buy_purity_score", *contribution_fields], contribution) * 0.1, 3),
        "estimated_capture_contribution": rounded(capture * 0.1, 3),
        "confidence_level": rounded(confidence, 3),
        "status": "ok" if evidence > 0 or contribution > 0 else "insufficient_evidence",
        "recommended_priority": priority_hint,
    }


def endpoint_safe(payload: dict[str, Any], marker: str) -> dict[str, Any]:
    out = with_safety(dict(payload or {}))
    out[marker] = True
    return out

