from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 1_500_000
MAX_ROWS = 700
QUALITY_FLOOR = 42.0
SURVIVABILITY_FLOOR = 45.0
EXPECTED_VALUE_FLOOR = 48.0
MAX_NEW_TRADES_PER_DAY = 4
MAX_NEW_TRADES_PER_CYCLE = 1
MAX_RISK_PER_TRADE = 0.02
MAX_PORTFOLIO_HEAT = 82.0
MAX_CORRELATION_PRESSURE = 88.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_prefix() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _score(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if 0.0 < out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _text(value: Any, default: str = "") -> str:
    s = str(value if value is not None else default).strip()
    return s or str(default)


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


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


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker")).upper()


def _field_text(row: dict[str, Any], *keys: str, default: str = "unknown") -> str:
    for key in keys:
        value = _text(row.get(key))
        if value:
            return value.lower().replace(" ", "_")[:80]
    return default


class ProfitSeekingAdaptiveExplorationV1:
    """Paper-only controlled exploration and caution/aggression calibration."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _history_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, limit in (
            ("trade_lifecycle_v1.jsonl", 220),
            ("outcome_labels_v1.jsonl", 220),
            ("paper_trade_journal.jsonl", 180),
            ("candidate_decision_ledger_v1.jsonl", 120),
        ):
            rows.extend(_tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit))
        return rows[-MAX_ROWS:]

    def _exploration_used_today(self) -> int:
        db_path = os.path.join(self.state_dir, "paper_autopilot.db")
        if not os.path.exists(db_path):
            return 0
        try:
            conn = sqlite3.connect(db_path, timeout=0.15)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT COUNT(1) AS n FROM paper_positions WHERE source_bucket LIKE ? AND entry_timestamp LIKE ?",
                    ("%controlled_exploration%", f"{_today_prefix()}%"),
                ).fetchone()
                return int(row["n"] if row else 0)
            finally:
                conn.close()
        except Exception:
            return 0

    def _context_key(self, row: dict[str, Any]) -> str:
        parts = [
            _field_text(row, "sector", "sector_name"),
            _field_text(row, "candidate_universe_tier", "market_cap_bucket", "market_cap_tier"),
            _field_text(row, "trade_archetype", "candidate_opportunity_type", "setup_type"),
            _field_text(row, "best_horizon_style", "trade_horizon_style"),
            _field_text(row, "correlation_cluster_id", "correlation_cluster_label"),
        ]
        return ":".join(parts)

    def _context_counts(self, rows: list[dict[str, Any]], history: list[dict[str, Any]]) -> Counter:
        counts: Counter = Counter()
        for row in history:
            counts[self._context_key(row)] += 1
        for row in rows:
            key = self._context_key(row)
            counts.setdefault(key, 0)
        return counts

    def _candidate_scores(self, row: dict[str, Any], trace: dict[str, Any] | None = None) -> dict[str, float]:
        t = dict(trace or {})
        expected_value = _score(_first(row.get("expected_value_score"), row.get("risk_adjusted_profit_score"), row.get("aggressive_profit_score"), t.get("expected_value_score"), default=50.0))
        profit = _score(_first(row.get("risk_adjusted_profit_score"), row.get("aggressive_profit_score"), row.get("diversification_adjusted_opportunity_score"), row.get("paper_allocation_priority"), default=expected_value))
        entry = _score(_first(row.get("paper_entry_bridge_score"), row.get("entry_quality_score"), row.get("entry_quality_v3"), row.get("entry_score"), t.get("entry_score"), default=50.0))
        confidence = _score(_first(row.get("confidence"), row.get("predicted_win_probability"), t.get("confidence"), default=50.0))
        survivability = _score(_first(row.get("survivability_score"), row.get("trade_durability_score"), row.get("portfolio_fit_score"), t.get("survivability_score"), default=50.0))
        execution = _score(_first(row.get("execution_readiness_score"), row.get("execution_quality_score"), row.get("entry_realism_score"), default=55.0))
        portfolio_fit = _score(_first(row.get("portfolio_fit_score"), t.get("portfolio_fit_score"), default=50.0))
        quality = _clamp((expected_value * 0.25) + (profit * 0.24) + (entry * 0.18) + (confidence * 0.13) + (execution * 0.10) + (portfolio_fit * 0.10))
        heat = _score(_first(row.get("portfolio_heat_score"), t.get("portfolio_heat_score"), default=35.0))
        corr = _score(_first(row.get("correlation_pressure_score"), row.get("portfolio_correlation_risk"), t.get("portfolio_correlation_risk"), default=50.0))
        return {
            "exploration_expected_value_score": round(expected_value, 2),
            "exploration_profit_intent_score": round(profit, 2),
            "exploration_trade_quality_score": round(quality, 2),
            "exploration_survivability_score": round(survivability, 2),
            "exploration_entry_quality_score": round(entry, 2),
            "exploration_confidence_score": round(confidence, 2),
            "exploration_execution_score": round(execution, 2),
            "portfolio_heat_score": round(heat, 2),
            "correlation_pressure_score": round(corr, 2),
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        base = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        if not base:
            return []
        history = self._history_rows()
        counts = self._context_counts(base, history)
        nonzero = [v for v in counts.values() if v > 0]
        median_count = sorted(nonzero)[len(nonzero) // 2] if nonzero else 0
        out = []
        for row in base:
            item = dict(row)
            scores = self._candidate_scores(item)
            key = self._context_key(item)
            evidence = int(counts.get(key, 0))
            under = evidence <= max(1, median_count // 2)
            over = evidence >= max(8, median_count * 2) if median_count else False
            item.update(scores)
            item["controlled_exploration_enabled"] = True
            item["exploration_mode"] = "profit_seeking"
            item["exploration_randomness_allowed"] = False
            item["selected_exploration_context"] = key
            item["exploration_context_reason"] = "underexplored_quality_context" if under else ("overexplored_context" if over else "balanced_context")
            item["context_evidence_gap"] = max(0, 5 - evidence)
            item["exploration_profit_rationale"] = self._profit_rationale(item, scores)
            out.append(item)
        return out

    def _profit_rationale(self, row: dict[str, Any], scores: dict[str, float]) -> str:
        symbol = _symbol(row) or "candidate"
        return (
            f"{symbol} is considered only if EV {scores['exploration_expected_value_score']:.1f}, "
            f"quality {scores['exploration_trade_quality_score']:.1f}, and survivability "
            f"{scores['exploration_survivability_score']:.1f} remain above exploration floors."
        )

    def evaluate_candidate(
        self,
        row: dict[str, Any],
        *,
        trace: dict[str, Any] | None = None,
        session_status: dict[str, Any] | None = None,
        market_context: dict[str, Any] | None = None,
        safety: dict[str, Any] | None = None,
        selected_today: int | None = None,
        selected_this_cycle: int = 0,
        normal_eligible_count: int = 0,
        portfolio_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item = dict(row or {})
        trace = dict(trace or {})
        session = dict(session_status or {})
        context_status = dict(market_context or {})
        if not context_status:
            context_status = session
        safety = dict(safety or {})
        portfolio = dict(portfolio_status or {})
        scores = self._candidate_scores(item, trace=trace)
        used_today = self._exploration_used_today() if selected_today is None else int(selected_today)
        context = self._context_key(item)
        session_allowed = bool(session.get("paper_order_submission_allowed") or trace.get("paper_order_submission_allowed"))
        market_open = bool(session.get("market_is_open") or trace.get("market_is_open") or session.get("market_is_tradable") or trace.get("market_is_tradable"))
        broker_ready = bool(safety.get("broker_execution_enabled") or safety.get("broker_execution_ready"))
        action = _text(_first(item.get("action"), item.get("prediction"), trace.get("action"), default="")).lower()
        readiness = " ".join(
            _text(_first(item.get(k), trace.get(k), default="")).lower()
            for k in ("buy_eligibility", "readiness", "readiness_label", "canonical_final_state", "hero_deployment_status")
        )
        random_allowed = False
        reason = "controlled_profit_seeking_exploration_passed"
        allowed = True
        if not market_open or not session_allowed:
            allowed, reason = False, _text(context_status.get("current_session_type"), "market_closed") if str(context_status.get("current_session_type") or "").endswith("_closed") else "market_closed"
        elif not broker_ready:
            allowed, reason = False, "broker_not_ready"
        elif context_status and not bool(context_status.get("market_context_supports_exploration", True)) and _to_float(context_status.get("context_adjusted_exploration_score"), 50.0) < 35.0:
            allowed, reason = False, "poor_market_structure"
        elif action not in {"buy", "strong buy"} and not any(x in readiness for x in ("paper", "buy", "watch", "eligible")):
            allowed, reason = False, "quality_floor_failed"
        elif normal_eligible_count > 0:
            allowed, reason = False, "normal_gate_candidate_available"
        elif selected_this_cycle >= MAX_NEW_TRADES_PER_CYCLE:
            allowed, reason = False, "exploration_cycle_limit_reached"
        elif used_today >= MAX_NEW_TRADES_PER_DAY:
            allowed, reason = False, "exploration_daily_limit_reached"
        elif scores["exploration_expected_value_score"] < EXPECTED_VALUE_FLOOR:
            allowed, reason = False, "quality_floor_failed"
        elif scores["exploration_trade_quality_score"] < QUALITY_FLOOR:
            allowed, reason = False, "quality_floor_failed"
        elif scores["exploration_survivability_score"] < SURVIVABILITY_FLOOR:
            allowed, reason = False, "survivability_floor_failed"
        elif scores["portfolio_heat_score"] > MAX_PORTFOLIO_HEAT:
            allowed, reason = False, "portfolio_heat_too_high"
        elif scores["correlation_pressure_score"] > MAX_CORRELATION_PRESSURE and not self._elite_override(item, scores):
            allowed, reason = False, "correlation_pressure_too_high"
        elif str(trace.get("duplicate_source") or "none") in {"broker", "both"}:
            allowed, reason = False, "duplicate_active_broker_position"
        label = self._caution_label([], [], used_today=used_today, open_market=market_open)
        return {
            "controlled_exploration_considered": True,
            "controlled_exploration_allowed": bool(allowed),
            "controlled_exploration_reason": reason,
            "exploration_selected": bool(allowed),
            "exploration_rejection_reason": "" if allowed else reason,
            "exploration_context": context,
            "selected_exploration_context": context,
            "exploration_context_reason": _text(item.get("exploration_context_reason"), "controlled_profit_seeking_second_look"),
            "exploration_profit_rationale": self._profit_rationale(item, scores),
            "market_context_supports_exploration": bool(context_status.get("market_context_supports_exploration", allowed)),
            "exploration_context_quality": round(_to_float(context_status.get("exploration_context_quality"), _to_float(context_status.get("context_adjusted_exploration_score"), 50.0)), 2),
            "exploration_session_reason": _text(context_status.get("exploration_session_reason") or context_status.get("session_reason"), ""),
            "exploration_market_knowledge_reason": _text(context_status.get("exploration_market_knowledge_reason"), ""),
            "context_adjusted_exploration_score": round(_to_float(context_status.get("context_adjusted_exploration_score"), 50.0), 2),
            "exploration_randomness_allowed": random_allowed,
            "exploration_quality_floor": QUALITY_FLOOR,
            "exploration_survivability_floor": SURVIVABILITY_FLOOR,
            "exploration_expected_value_floor": EXPECTED_VALUE_FLOOR,
            "exploration_max_new_trades_per_day": MAX_NEW_TRADES_PER_DAY,
            "exploration_max_new_trades_per_cycle": MAX_NEW_TRADES_PER_CYCLE,
            "exploration_max_risk_per_trade": MAX_RISK_PER_TRADE,
            "exploration_max_portfolio_heat": MAX_PORTFOLIO_HEAT,
            "exploration_max_correlation_pressure": MAX_CORRELATION_PRESSURE,
            "caution_aggression_label": label,
            "missed_opportunity_pressure": self._missed_pressure(normal_eligible_count, used_today, market_open),
            "participation_quality_score": self._participation_quality(used_today, market_open, scores),
            **scores,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        }

    def _elite_override(self, row: dict[str, Any], scores: dict[str, float]) -> bool:
        return bool(
            _score(row.get("edge_composite_score"), 0.0) >= 78.0
            and scores.get("exploration_expected_value_score", 0.0) >= 68.0
            and scores.get("exploration_survivability_score", 0.0) >= 62.0
        )

    def _missed_pressure(self, normal_eligible_count: int, used_today: int, open_market: bool) -> float:
        if not open_market:
            return 0.0
        pressure = 35.0 if normal_eligible_count <= 0 else 12.0
        if used_today <= 0:
            pressure += 25.0
        return round(_clamp(pressure), 2)

    def _participation_quality(self, used_today: int, open_market: bool, scores: dict[str, float] | None = None) -> float:
        base = 55.0 if open_market else 50.0
        if open_market and used_today <= 0:
            base -= 10.0
        if scores:
            base = (base * 0.45) + (scores.get("exploration_trade_quality_score", 50.0) * 0.35) + (scores.get("exploration_survivability_score", 50.0) * 0.20)
        return round(_clamp(base), 2)

    def _caution_label(self, rows: list[dict[str, Any]], history: list[dict[str, Any]], *, used_today: int, open_market: bool) -> str:
        weak_pressure = 0.0
        if history:
            losses = sum(1 for r in history[-80:] if _to_float(_first(r.get("return_pct"), r.get("return_percent"), r.get("realized_return_pct"), default=0.0), 0.0) < -0.75)
            weak_pressure = min(100.0, losses * 2.5)
        if not open_market:
            return "balanced_selective"
        if used_today <= 0 and rows:
            return "too_cautious"
        if weak_pressure >= 45.0:
            return "too_aggressive"
        return "balanced_selective"

    def status(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        paper_trace: dict[str, Any] | None = None,
        session_status: dict[str, Any] | None = None,
        market_context: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        base_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        decorated = self.decorate_candidates(base_rows)
        history = self._history_rows()
        counts = self._context_counts(decorated, history)
        under = [k for k, v in counts.items() if v <= 2][:8]
        over = [k for k, v in counts.items() if v >= 10][:8]
        used_today = self._exploration_used_today()
        trace = dict(paper_trace or {})
        session = dict(session_status or {})
        context_status = dict(market_context or session)
        market_open = bool(session.get("market_is_open") or trace.get("market_is_open") or session.get("paper_order_submission_allowed") or trace.get("paper_order_submission_allowed"))
        avg_quality = sum(_to_float(r.get("exploration_trade_quality_score"), 0.0) for r in decorated) / max(1, len(decorated))
        avg_survive = sum(_to_float(r.get("exploration_survivability_score"), 0.0) for r in decorated) / max(1, len(decorated))
        normal_selected = _to_int(trace.get("selected_candidates"), 0)
        candidates_seen = max(len(decorated), _to_int(trace.get("candidates_seen"), 0))
        missed = self._missed_pressure(normal_selected, used_today, market_open) if candidates_seen else 0.0
        weak_trade_pressure = max(0.0, 55.0 - avg_quality) if decorated else 0.0
        balance = round(_clamp(100.0 - abs(missed - weak_trade_pressure)), 2)
        label = self._caution_label(decorated, history, used_today=used_today, open_market=market_open)
        evidence = len(history)
        diversity = round(_clamp((len(counts) / max(1, len(decorated))) * 70.0 + min(30.0, evidence / 10.0)), 2) if decorated else 0.0
        exploration_alloc = 18.0
        decay_reason = "insufficient_evidence_allows_small_controlled_exploration"
        if evidence >= 80 and avg_quality >= 62.0:
            exploration_alloc = 10.0
            decay_reason = "evidence_maturing_shift_toward_exploitation"
        elif weak_trade_pressure >= 30.0:
            exploration_alloc = 8.0
            decay_reason = "weak_trade_pressure_reduces_exploration"
        elif label == "too_cautious":
            exploration_alloc = 22.0
            decay_reason = "under_trading_pressure_allows_modest_exploration"
        payload = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_calibration",
            "controlled_exploration_enabled": True,
            "exploration_mode": "profit_seeking",
            "exploration_randomness_allowed": False,
            "exploration_quality_floor": QUALITY_FLOOR,
            "exploration_survivability_floor": SURVIVABILITY_FLOOR,
            "exploration_expected_value_floor": EXPECTED_VALUE_FLOOR,
            "exploration_max_new_trades_per_day": MAX_NEW_TRADES_PER_DAY,
            "exploration_max_new_trades_per_cycle": MAX_NEW_TRADES_PER_CYCLE,
            "exploration_max_risk_per_trade": MAX_RISK_PER_TRADE,
            "exploration_max_portfolio_heat": MAX_PORTFOLIO_HEAT,
            "exploration_max_correlation_pressure": MAX_CORRELATION_PRESSURE,
            "exploration_trades_allowed_today": MAX_NEW_TRADES_PER_DAY,
            "exploration_trades_used_today": int(used_today),
            "learning_diversity_score": diversity,
            "underexplored_contexts": under,
            "overexplored_contexts": over,
            "context_evidence_gap": max(0, min(20, len(under))),
            "exploration_decay_active": True,
            "exploration_decay_reason": decay_reason,
            "exploration_confidence_by_context": {k: min(100.0, v * 8.0) for k, v in counts.most_common(8)},
            "exploration_allocation_pct": round(exploration_alloc, 2),
            "exploitation_allocation_pct": round(100.0 - exploration_alloc, 2),
            "exploration_to_exploitation_transition_score": round(_clamp(evidence / 1.2), 2),
            "caution_aggression_balance_score": balance,
            "caution_aggression_label": label,
            "over_cautious_risk": round(missed, 2),
            "under_cautious_risk": round(weak_trade_pressure, 2),
            "missed_opportunity_pressure": round(missed, 2),
            "weak_trade_pressure": round(weak_trade_pressure, 2),
            "participation_quality_score": self._participation_quality(used_today, market_open, {"exploration_trade_quality_score": avg_quality, "exploration_survivability_score": avg_survive}),
            "learning_participation_score": round(_clamp((diversity * 0.35) + (balance * 0.35) + (avg_quality * 0.30)), 2),
            "adaptive_exploration_recommendation": self._recommendation(label, missed, weak_trade_pressure),
            "summary": self._summary(label, used_today, under, over, market_open),
            "market_context_supports_exploration": bool(context_status.get("market_context_supports_exploration", market_open)),
            "exploration_context_quality": round(_to_float(context_status.get("exploration_context_quality"), _to_float(context_status.get("context_adjusted_exploration_score"), 50.0)), 2),
            "exploration_session_reason": _text(context_status.get("exploration_session_reason") or context_status.get("session_reason"), ""),
            "exploration_market_knowledge_reason": _text(context_status.get("exploration_market_knowledge_reason"), ""),
            "context_adjusted_exploration_score": round(_to_float(context_status.get("context_adjusted_exploration_score"), 50.0), 2),
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "deterministic_execution_authority_preserved": True,
            "generated_at": _now_iso(),
        }
        self._cache = dict(payload)
        self._cache_ts = now
        return payload

    def _recommendation(self, label: str, missed: float, weak: float) -> str:
        if label == "too_cautious" or missed > 55.0:
            return "allow_one_bounded_profit_seeking_exploration_when_market_open_and_normal_gates_overblock"
        if label == "too_aggressive" or weak > 45.0:
            return "reduce_exploration_and_raise_confirmation_quality_until_outcomes_stabilize"
        return "maintain_balanced_selective_exploration_with_profit_and_survivability_floors"

    def _summary(self, label: str, used_today: int, under: list[str], over: list[str], market_open: bool) -> str:
        session = "open-market calibration" if market_open else "watch-only calibration while market is closed"
        return (
            f"Profit-seeking exploration is {session}; caution/aggression is {label.replace('_', ' ')}; "
            f"{used_today}/{MAX_NEW_TRADES_PER_DAY} exploration trades used today; "
            f"underexplored contexts {len(under)}, overexplored contexts {len(over)}."
        )
