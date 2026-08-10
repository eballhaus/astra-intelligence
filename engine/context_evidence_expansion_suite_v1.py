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
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800

CATALYST_TYPES = (
    "earnings",
    "guidance",
    "analyst_upgrade",
    "analyst_downgrade",
    "FDA_or_regulatory",
    "contract_award",
    "merger_acquisition",
    "sector_sympathy",
    "retail_social_momentum",
    "macro_news",
    "commodity_related",
    "rate_policy_related",
    "unknown_catalyst",
    "no_detected_catalyst",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


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
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        return


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("selected_symbol") or row.get("rejected_symbol"), "unknown").upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(row, "current_or_exit_profit_pct", "actual_return_pct", "later_return_after_rejection", "rejected_return_pct", "return_pct", "current_return_pct")


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "later_mfe", "mfe_pct", "peak_gain_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct", "later_mae", "mae_pct")


def _giveback(row: dict[str, Any]) -> float:
    return _value(row, "profit_giveback_pct", "current_giveback_pct", "giveback_from_peak_pct", "average_profit_giveback_pct")


def _is_open(row: dict[str, Any]) -> bool:
    if row.get("exit_timestamp") or row.get("exit_price") or row.get("closed_at"):
        return False
    if bool(row.get("closed")):
        return False
    status = _text(row.get("status") or row.get("lifecycle_status") or row.get("position_status"), "open").lower()
    return status not in {"closed", "exited", "complete", "completed", "filled_closed"}


def _top_symbol(rows: list[dict[str, Any]], keys: tuple[str, ...], *, reverse: bool = True, default: str = "insufficient_data") -> str:
    scored: list[tuple[float, str]] = []
    for row in rows:
        sym = _symbol(row)
        if not sym or sym == "UNKNOWN":
            continue
        scored.append((_value(row, *keys), sym))
    if not scored:
        return default
    scored.sort(reverse=reverse)
    return scored[0][1]


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("selected_horizon") or row.get("recommended_horizon"), "unknown").lower()
    if "scalp" in raw:
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw:
        return "swing"
    if "day" in raw:
        return "day_trade"
    hold = _value(row, "hold_duration_minutes", "actual_hold_duration_minutes")
    if hold and hold < 30:
        return "scalp"
    if hold and hold < 390:
        return "day_trade"
    if hold and hold < 1440:
        return "short_swing"
    return "unknown"


def _safe_catalyst(raw: Any) -> str:
    value = _text(raw, "unknown_catalyst").lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "fda": "FDA_or_regulatory",
        "regulatory": "FDA_or_regulatory",
        "merger": "merger_acquisition",
        "acquisition": "merger_acquisition",
        "retail_momentum": "retail_social_momentum",
        "social": "retail_social_momentum",
        "commodity": "commodity_related",
        "rates": "rate_policy_related",
        "rate_policy": "rate_policy_related",
    }
    mapped = aliases.get(value, value)
    for item in CATALYST_TYPES:
        if str(mapped).lower() == item.lower():
            return item
    return "unknown_catalyst" if value not in {"none", "no_detected_catalyst"} else "no_detected_catalyst"


class ContextEvidenceExpansionSuiteV1:
    """Shadow-only open-trade, rejected-candidate, and catalyst evidence expansion."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.state_path = os.path.join(self.state_dir, "context_evidence_expansion_suite_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _rows(self, name: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit)

    def _collect_rows(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 720) + self._rows("trade_lifecycle_excursion_v1.jsonl", 360),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 620),
            "audit": self._rows("execution_suppression_audit_v1.jsonl", 720),
            "candidate": self._rows("candidate_decision_ledger_v1.jsonl", 520),
            "opportunity_cost": self._rows("opportunity_cost_learning_v1.jsonl", 620),
            "market_context": self._rows("market_context_learning_suite_v1.jsonl", 620),
            "archetype_regime": self._rows("trade_archetype_regime_intelligence_v1.jsonl", 360),
        }

    def _open_trade_learning(self, rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        active = [r for r in rows["lifecycle"] if _is_open(r)]
        if not active:
            active = [r for r in rows["profit_capture"] if _is_open(r)]
        gain_values = [_return_pct(r) for r in active]
        giveback_values = [_giveback(r) for r in active]
        continuation_values = [_value(r, "continuation_strength_score", "follow_through_quality_score", "follow_through_score") for r in active]
        capture_values = [_value(r, "profit_capture_ratio", "capture_ratio") for r in active]
        decay_values = [_value(r, "profit_decay_velocity", "current_giveback_pct", "profit_giveback_pct") for r in active]
        horizons = Counter(_horizon(r) for r in active if _horizon(r) != "unknown")
        strongest = _top_symbol(active, ("current_or_exit_profit_pct", "current_unrealized_profit_pct", "peak_unrealized_profit_pct", "max_favorable_excursion_pct"))
        weakest = _top_symbol(active, ("current_or_exit_profit_pct", "current_unrealized_profit_pct", "max_adverse_excursion_pct"), reverse=False)
        highest_decay = _top_symbol(active, ("profit_decay_velocity", "current_giveback_pct", "profit_giveback_pct"))
        highest_giveback = _top_symbol(active, ("current_giveback_pct", "profit_giveback_pct", "giveback_from_peak_pct"))
        confidence = _clamp(25.0 + len(active) * 7.0 + min(25.0, (_avg(continuation_values) or 0.0) * 0.2))
        return {
            "active_trades_tracked": len(active),
            "active_trade_symbols": [_symbol(r) for r in active[:12] if _symbol(r) != "UNKNOWN"],
            "strongest_open_trade": strongest,
            "weakest_open_trade": weakest,
            "highest_profit_decay_symbol": highest_decay,
            "highest_giveback_symbol": highest_giveback,
            "best_open_trade_horizon": horizons.most_common(1)[0][0] if horizons else "insufficient_data",
            "open_trade_continuation_score": _round(_avg(continuation_values) or 0.0, 2),
            "open_trade_profit_capture_score": _round((_avg(capture_values) or 0.0) * 100.0, 2),
            "average_open_trade_gain_pct": _avg(gain_values),
            "average_open_trade_giveback_pct": _avg(giveback_values),
            "average_profit_decay": _avg(decay_values),
            "open_trade_learning_confidence": _round(confidence, 2),
            "open_trade_shadow_recommendation": "monitor_open_trade_mfe_mae_giveback_and_continuation_without_exit_actions" if active else "collect_open_trade_evidence_when_positions_are_active",
            "open_trade_behavior_safe_to_apply": False,
        }

    def _rejected_candidate_learning(self, rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        rejected: list[dict[str, Any]] = []
        for row in rows["opportunity_cost"]:
            sym = _text(row.get("rejected_symbol"), "")
            if sym:
                item = dict(row)
                item["symbol"] = sym
                if _text(item.get("rejected_return_evidence_tier")) == "REAL_LATER_PRICE":
                    item["later_return_after_rejection"] = _value(row, "rejected_return_pct", "later_return_after_rejection")
                else:
                    item["later_return_after_rejection"] = row.get("later_return_after_rejection")
                rejected.append(item)
        for row in rows["audit"] + rows["candidate"]:
            decision = _text(row.get("final_execution_decision") or row.get("decision") or row.get("rejection_reason") or row.get("suppression_reason"), "").lower()
            if any(part in decision for part in ("reject", "blocked", "skipped", "not_selected", "suppression")):
                rejected.append(dict(row))
        reviewed = len(rejected)
        missed = [r for r in rejected if _value(r, "later_return_after_rejection", "rejected_return_pct", "missed_follow_through_pct") > 2.0 or bool(r.get("missed_better_candidate_flag"))]
        avoided = [r for r in rejected if _value(r, "later_return_after_rejection", "rejected_return_pct") < -1.0 or bool(r.get("correct_selection_flag"))]
        correct = [r for r in rejected if bool(r.get("rejection_correct")) or r in avoided]
        reason_counter = Counter(_text(r.get("rejection_reason") or r.get("suppression_reason") or r.get("final_blocker_reason"), "unknown") for r in rejected)
        opportunity_costs = [_value(r, "opportunity_cost_pct", "missed_profit_capture_pct") for r in rejected]
        correct_total = min(reviewed, len({id(r) for r in correct + avoided}))
        accuracy = round(correct_total / max(1, reviewed) * 100.0, 4) if reviewed else 0.0
        biggest_missed = _top_symbol(missed, ("later_return_after_rejection", "rejected_return_pct", "opportunity_cost_pct"))
        best_correct = _top_symbol(avoided, ("later_return_after_rejection", "rejected_return_pct"), reverse=False)
        confidence = _clamp(20.0 + min(45.0, reviewed * 0.08) + min(25.0, len(rows["opportunity_cost"]) * 0.08))
        return {
            "rejected_candidates_reviewed": reviewed,
            "correct_rejections": correct_total,
            "missed_winners": len(missed),
            "avoided_losers": len(avoided),
            "rejection_accuracy": accuracy,
            "biggest_missed_symbol": biggest_missed,
            "best_correct_rejection": best_correct,
            "worst_rejection_reason": reason_counter.most_common(1)[0][0] if reason_counter else "insufficient_data",
            "rejection_reason_distribution": dict(reason_counter.most_common(8)),
            "average_opportunity_cost_contribution": _avg(opportunity_costs),
            "rejection_learning_score": _round(_clamp(accuracy * 0.55 + min(45.0, reviewed * 0.02)), 2),
            "rejected_candidate_learning_confidence": _round(confidence, 2),
            "rejected_candidate_shadow_recommendation": "study_rejected_candidate_outcomes_without_loosening_gates_or_rankings",
            "rejected_candidate_behavior_safe_to_apply": False,
        }

    def _catalyst_learning(self, rows: dict[str, list[dict[str, Any]]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        market_status = statuses.get("market_context_learning_suite_v1") or {}
        for row in rows["market_context"] + rows["candidate"] + rows["lifecycle"]:
            raw = row.get("catalyst_type") or row.get("dominant_catalyst_type") or row.get("catalyst")
            if raw is None and row not in rows["market_context"]:
                continue
            item = dict(row)
            item["catalyst_type"] = _safe_catalyst(raw)
            records.append(item)
        status_dist = market_status.get("catalyst_type_distribution") or {}
        for catalyst, count in status_dist.items():
            for _ in range(min(50, _to_int(count, 0))):
                records.append({"symbol": "AGGREGATED", "catalyst_type": _safe_catalyst(catalyst), "catalyst_confidence": market_status.get("context_confidence")})
        catalyst_counter = Counter(_safe_catalyst(r.get("catalyst_type")) for r in records)
        known = sum(count for catalyst, count in catalyst_counter.items() if catalyst not in {"unknown_catalyst", "no_detected_catalyst"})
        total = sum(catalyst_counter.values())
        unknown = catalyst_counter.get("unknown_catalyst", 0) + catalyst_counter.get("no_detected_catalyst", 0)
        unknown_rate = round(unknown / max(1, total) * 100.0, 4) if total else 100.0
        grouped_returns: dict[str, list[float]] = defaultdict(list)
        grouped_giveback: dict[str, list[float]] = defaultdict(list)
        grouped_hold: dict[str, list[float]] = defaultdict(list)
        grouped_continuation: dict[str, list[float]] = defaultdict(list)
        grouped_horizon: dict[str, Counter[str]] = defaultdict(Counter)
        for row in records:
            catalyst = _safe_catalyst(row.get("catalyst_type"))
            grouped_returns[catalyst].append(_return_pct(row))
            grouped_giveback[catalyst].append(_giveback(row))
            grouped_hold[catalyst].append(_value(row, "hold_duration_minutes", "average_hold_duration_by_catalyst"))
            grouped_continuation[catalyst].append(_value(row, "premarket_continuation_probability", "continuation_strength_score", "follow_through_quality_score"))
            horizon = _horizon(row)
            if horizon != "unknown":
                grouped_horizon[catalyst][horizon] += 1
        avg_return = {k: _avg(v) or 0.0 for k, v in grouped_returns.items() if v}
        avg_giveback = {k: _avg(v) or 0.0 for k, v in grouped_giveback.items() if v}
        best_catalyst = max(avg_return.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        weakest_catalyst = min(avg_return.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        highest_giveback = max(avg_giveback.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        dominant = catalyst_counter.most_common(1)[0][0] if catalyst_counter else _text(market_status.get("dominant_catalyst_type"), "insufficient_data")
        best_horizon_by_catalyst = {k: (counter.most_common(1)[0][0] if counter else "insufficient_data") for k, counter in grouped_horizon.items()}
        best_catalyst_horizon = best_horizon_by_catalyst.get(best_catalyst, _text(market_status.get("best_context_horizon"), "insufficient_data"))
        coverage = _clamp((known / max(1, total)) * 100.0 if total else 0.0)
        confidence = _clamp(20.0 + min(45.0, total * 0.15) + coverage * 0.25)
        return {
            "catalyst_records": total,
            "dominant_catalyst_type": dominant,
            "strongest_catalyst_type": _text(market_status.get("strongest_catalyst_type"), best_catalyst) if market_status.get("strongest_catalyst_type") else best_catalyst,
            "weakest_catalyst_type": _text(market_status.get("weakest_catalyst_type"), weakest_catalyst) if market_status.get("weakest_catalyst_type") else weakest_catalyst,
            "unknown_catalyst_rate": unknown_rate,
            "catalyst_coverage_score": _round(coverage, 2),
            "best_catalyst_horizon": best_catalyst_horizon,
            "highest_giveback_catalyst": highest_giveback,
            "catalyst_distribution": dict(catalyst_counter.most_common(10)),
            "best_horizon_by_catalyst": best_horizon_by_catalyst,
            "avg_giveback_by_catalyst": {k: _round(v, 4) for k, v in avg_giveback.items()},
            "avg_hold_duration_by_catalyst": {k: _round(_avg(v) or 0.0, 4) for k, v in grouped_hold.items() if v},
            "continuation_probability_by_catalyst": {k: _round(_avg(v) or 0.0, 4) for k, v in grouped_continuation.items() if v},
            "catalyst_learning_confidence": _round(confidence, 2),
            "catalyst_shadow_recommendation": "reduce_unknown_catalyst_rate_using_cached_context_sources_only" if unknown_rate >= 50.0 else "continue_catalyst_context_tracking_shadow_only",
            "catalyst_behavior_safe_to_apply": False,
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        started = time.perf_counter()
        rows = self._collect_rows()
        open_learning = self._open_trade_learning(rows)
        rejected_learning = self._rejected_candidate_learning(rows)
        catalyst_learning = self._catalyst_learning(rows, statuses)
        evidence_count = sum(len(v) for v in rows.values())
        gaps = {
            "open_trade_learning": 100.0 - _to_float(open_learning.get("open_trade_learning_confidence"), 0.0),
            "rejected_candidate_learning": 100.0 - _to_float(rejected_learning.get("rejected_candidate_learning_confidence"), 0.0),
            "catalyst_learning": 100.0 - _to_float(catalyst_learning.get("catalyst_learning_confidence"), 0.0),
            "unknown_catalyst_reduction": _to_float(catalyst_learning.get("unknown_catalyst_rate"), 100.0),
        }
        top_gap = max(gaps.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        recommendation_map = {
            "open_trade_learning": "collect_more_active_trade_mfe_mae_profit_decay_and_continuation_evidence",
            "rejected_candidate_learning": "expand_rejected_candidate_outcome_matching_without_loosening_gates",
            "catalyst_learning": "increase_cached_catalyst_context_coverage_without_live_scraping",
            "unknown_catalyst_reduction": "reduce_unknown_catalyst_classifications_using_cached_context_sources",
        }
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_context_evidence_expansion",
            "generated_at": _now_iso(),
            "evidence_count": evidence_count,
            **open_learning,
            **rejected_learning,
            **catalyst_learning,
            "top_learning_gap": top_gap,
            "learning_gap_scores": {k: _round(v, 2) for k, v in gaps.items()},
            "shadow_recommendation": recommendation_map.get(top_gap, "continue_context_evidence_collection_shadow_only"),
            "summary": "Astra is learning from active trades before they close, rejected candidates it did not select, and catalysts that may explain why stocks are moving. No trading behavior is changed.",
            "behavior_safe_to_apply": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "cache_hit": False,
            "build_ms": _round((time.perf_counter() - started) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
        }
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        if self._cache and not force and (time.time() - self._cache_ts) < self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            return cached
        try:
            out = self._build(dict(statuses or {}))
            if time.time() - self._last_write >= 300.0:
                _append_jsonl(
                    self.state_path,
                    {
                        "timestamp": out.get("generated_at"),
                        "evidence_count": out.get("evidence_count"),
                        "active_trades_tracked": out.get("active_trades_tracked"),
                        "rejected_candidates_reviewed": out.get("rejected_candidates_reviewed"),
                        "catalyst_records": out.get("catalyst_records"),
                        "top_learning_gap": out.get("top_learning_gap"),
                        "shadow_recommendation": out.get("shadow_recommendation"),
                        "behavior_safe_to_apply": False,
                    },
                )
                self._last_write = time.time()
            self._cache = dict(out)
            self._cache_ts = time.time()
            return out
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_context_evidence_expansion",
                "evidence_count": 0,
                "active_trades_tracked": 0,
                "rejected_candidates_reviewed": 0,
                "catalyst_records": 0,
                "strongest_open_trade": "insufficient_data",
                "weakest_open_trade": "insufficient_data",
                "highest_profit_decay_symbol": "insufficient_data",
                "rejection_accuracy": 0.0,
                "missed_winners": 0,
                "avoided_losers": 0,
                "biggest_missed_symbol": "insufficient_data",
                "dominant_catalyst_type": "insufficient_data",
                "unknown_catalyst_rate": 100.0,
                "catalyst_coverage_score": 0.0,
                "best_catalyst_horizon": "insufficient_data",
                "open_trade_learning_confidence": 0.0,
                "rejected_candidate_learning_confidence": 0.0,
                "catalyst_learning_confidence": 0.0,
                "top_learning_gap": "unavailable",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"context_evidence_expansion_suite_v1_unavailable:{str(exc)[:140]}",
                "behavior_safe_to_apply": False,
                "api_calls_used": 0,
                "build_ms": 0.0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
            }
