from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    out: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                out.append(row)
        except Exception:
            continue
    return out


def _bucket(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(row.get(key))
        if value and value.lower() not in {"unknown", "none", "n/a"}:
            return value
    return "unknown"


_REAL_LATER_RETURN_KEYS = (
    "subsequent_return",
    "subsequent_return_pct",
    "later_return_after_rejection",
    "rejected_later_return_pct",
    "hypothetical_return",
    "realized_return_pct",
)


def _proven_missed_candidate(row: dict[str, Any]) -> bool:
    """Keep proxy-quality and legacy flags out of missed-opportunity counts."""
    classification = _text(row.get("rejected_candidate_outcome_classification")).upper()
    tier = _text(row.get("rejected_return_evidence_tier")).upper()
    if classification:
        return classification == "MISSED_OPPORTUNITY" and tier == "REAL_LATER_PRICE"
    reasons = " ".join(str(row.get(key) or "") for key in (
        "blocked_reasons", "rejection_reason", "suppression_reason", "final_blocker_reason",
    )).lower()
    if bool(row.get("safety_blocker") or row.get("liquidity_blocker") or row.get("stale_evidence") or row.get("duplicate_exposure")):
        return False
    if any(token in reasons for token in ("safety", "liquidity", "stale", "duplicate")):
        return False
    later = next((row.get(key) for key in _REAL_LATER_RETURN_KEYS if row.get(key) not in (None, "")), None)
    if later is None:
        return False
    return _to_float(later) > _to_float(row.get("selected_return_pct")) + 0.35


class BlindSpotDetectionV1:
    """Shadow-only blind-spot diagnostics from lifecycle and opportunity-cost evidence."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.opportunity_path = os.path.join(self.state_dir, "opportunity_cost_learning_v1.jsonl")
        self.audit_path = os.path.join(self.state_dir, "execution_suppression_audit_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _selected_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _tail_jsonl(self.lifecycle_path, max_rows=900):
            symbol = _text(row.get("symbol")).upper()
            if symbol:
                latest[symbol] = row
        return list(latest.values())

    def _rejected_rows(self) -> list[dict[str, Any]]:
        rows = _tail_jsonl(self.opportunity_path, max_rows=700)
        rows.extend(_tail_jsonl(self.audit_path, max_rows=500))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=500))
        return [row for row in rows if _text(row.get("symbol") or row.get("rejected_symbol"))]

    @staticmethod
    def _distribution(rows: list[dict[str, Any]], key_names: tuple[str, ...]) -> Counter:
        counter: Counter = Counter()
        for row in rows:
            value = _bucket(row, *key_names)
            if value != "unknown":
                counter[value] += 1
        return counter

    @staticmethod
    def _bias(selected: Counter, rejected: Counter, *, under: bool) -> list[str]:
        total_selected = max(1, sum(selected.values()))
        total_rejected = max(1, sum(rejected.values()))
        values: list[tuple[float, str]] = []
        for key in set(selected) | set(rejected):
            selected_pct = selected.get(key, 0) / total_selected
            rejected_pct = rejected.get(key, 0) / total_rejected
            delta = rejected_pct - selected_pct
            if under and delta > 0.04:
                values.append((delta, key))
            if not under and -delta > 0.04:
                values.append((-delta, key))
        return [key for _, key in sorted(values, reverse=True)[:6]]

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        selected = self._selected_rows()
        rejected = self._rejected_rows()
        missed = [row for row in rejected if _proven_missed_candidate(row)]
        selected_sector = self._distribution(selected, ("sector", "same_sector"))
        rejected_sector = self._distribution(rejected, ("same_sector", "sector"))
        selected_arch = self._distribution(selected, ("trade_archetype", "same_archetype", "setup_type"))
        rejected_arch = self._distribution(rejected, ("same_archetype", "trade_archetype", "setup_type"))
        selected_cap = self._distribution(selected, ("cap_tier", "same_cap_tier", "cap_bucket"))
        rejected_cap = self._distribution(rejected, ("same_cap_tier", "cap_tier", "cap_bucket"))
        selected_horizon = self._distribution(selected, ("horizon_style", "same_horizon_style"))
        rejected_horizon = self._distribution(rejected, ("same_horizon_style", "horizon_style"))
        selected_regime = self._distribution(selected, ("market_regime", "same_regime", "regime"))
        rejected_regime = self._distribution(rejected, ("same_regime", "market_regime", "regime"))
        missed_symbols = Counter(_text(row.get("rejected_symbol") or row.get("symbol")).upper() for row in missed if _text(row.get("rejected_symbol") or row.get("symbol")))
        under_sectors = self._bias(selected_sector, rejected_sector, under=True)
        over_sectors = self._bias(selected_sector, rejected_sector, under=False)
        under_arch = self._bias(selected_arch, rejected_arch, under=True)
        cap_bias = self._bias(selected_cap, rejected_cap, under=True) or self._bias(selected_cap, rejected_cap, under=False)
        horizon_bias = self._bias(selected_horizon, rejected_horizon, under=True) or self._bias(selected_horizon, rejected_horizon, under=False)
        regime_blind = self._bias(selected_regime, rejected_regime, under=True)
        score = min(100.0, len(missed) * 1.2 + len(under_sectors) * 8.0 + len(under_arch) * 7.0 + len(regime_blind) * 6.0)
        candidates = {
            "missed_high_performers": len(missed),
            "underselected_sector": under_sectors[0] if under_sectors else "",
            "underselected_archetype": under_arch[0] if under_arch else "",
            "cap_tier_bias": cap_bias[0] if cap_bias else "",
            "horizon_bias": horizon_bias[0] if horizon_bias else "",
            "regime_blind_spot": regime_blind[0] if regime_blind else "",
        }
        strongest = next((f"{k}:{v}" for k, v in candidates.items() if v), "insufficient_evidence")
        recommendation = "continue_shadow_monitoring"
        if len(missed) >= 10:
            recommendation = "review_missed_high_performing_candidates_before_tuning"
        elif under_sectors or under_arch:
            recommendation = "collect_more_evidence_in_underselected_contexts"
        out = {
            "enabled": True,
            "version": VERSION,
            "blind_spot_score": round(score, 4),
            "missed_opportunity_count": len(missed),
            "top_missed_symbols": [symbol for symbol, _ in missed_symbols.most_common(10)],
            "underselected_sectors": under_sectors,
            "overselected_sectors": over_sectors,
            "underselected_archetypes": under_arch,
            "cap_tier_bias": cap_bias[0] if cap_bias else "insufficient_evidence",
            "horizon_bias": horizon_bias[0] if horizon_bias else "insufficient_evidence",
            "regime_blind_spots": regime_blind,
            "strongest_blind_spot": strongest,
            "recommendation": recommendation,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "broker_behavior_changed": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
