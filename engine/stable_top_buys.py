"""Stable Top 6 Selection Layer V1.

Presentation-only hysteresis layer for Astra's displayed Top 6. It consumes
already-built top_buys rows, keeps a small stable shortlist, and never changes
raw ranking/top_buys strategy or live trading behavior.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any

try:
    from engine.expected_return_engine import ExpectedReturnEngine
    from engine.exit_averaging_engine import ExitAveragingEngine
    from engine.opportunity_scoring_engine import OpportunityScoringEngine
    from engine.target_zone_engine import TargetZoneEngine
    from engine.context_search_profitability_suite_v1 import ContextSearchProfitabilitySuiteV1
    from engine.portfolio_risk_intelligence_suite_v1 import PortfolioRiskIntelligenceSuiteV1
except Exception:  # pragma: no cover - fail-safe imports for runtime resilience
    ExpectedReturnEngine = None  # type: ignore[assignment]
    ExitAveragingEngine = None  # type: ignore[assignment]
    OpportunityScoringEngine = None  # type: ignore[assignment]
    TargetZoneEngine = None  # type: ignore[assignment]
    ContextSearchProfitabilitySuiteV1 = None  # type: ignore[assignment]
    PortfolioRiskIntelligenceSuiteV1 = None  # type: ignore[assignment]

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _symbol(row: dict[str, Any]) -> str:
    return str((row or {}).get("symbol") or (row or {}).get("ticker") or "").upper().strip()


def _first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _grade_score(row: dict[str, Any]) -> float:
    explicit = _f(row.get("grade_percent"), -1.0)
    if explicit >= 0:
        return max(0.0, min(100.0, explicit))
    grade = str(row.get("grade") or row.get("buy_grade") or "").upper()[:1]
    return {"A": 92.0, "B": 78.0, "C": 62.0, "D": 42.0, "F": 18.0}.get(grade, 50.0)


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _norm_text(row.get("market_cap_category") or row.get("market_cap_bucket") or row.get("cap_bucket") or row.get("market_cap_group"))
    if "large" in raw or "mega" in raw:
        return "large_cap"
    if "mid" in raw:
        return "mid_cap"
    if "small" in raw or "micro" in raw:
        return "small_cap"
    return "unknown_cap"


class StableTopBuysSelector:
    def __init__(
        self,
        state_dir: str = "state",
        *,
        min_hold_seconds: int = 420,
        challenger_margin_required: float = 6.0,
        consecutive_refreshes_required: int = 2,
        min_quality_floor: float = 42.0,
        hard_confidence_floor: float = 35.0,
    ) -> None:
        self.state_dir = str(state_dir or "state")
        self.snapshot_path = os.path.join(self.state_dir, "snapshots", "stable_top_buys_v1.json")
        self.min_hold_seconds = int(max(60, min_hold_seconds))
        self.challenger_margin_required = float(max(1.0, challenger_margin_required))
        self.consecutive_refreshes_required = int(max(1, consecutive_refreshes_required))
        self.min_quality_floor = float(max(0.0, min_quality_floor))
        self.hard_confidence_floor = float(max(0.0, hard_confidence_floor))
        self._state: dict[str, Any] | None = None
        self.expected_return_engine = ExpectedReturnEngine(state_dir=self.state_dir) if ExpectedReturnEngine else None
        self.opportunity_scoring_engine = OpportunityScoringEngine(state_dir=self.state_dir) if OpportunityScoringEngine else None
        self.target_zone_engine = TargetZoneEngine(state_dir=self.state_dir) if TargetZoneEngine else None
        self.exit_averaging_engine = ExitAveragingEngine(state_dir=self.state_dir) if ExitAveragingEngine else None
        self.context_profitability_suite = ContextSearchProfitabilitySuiteV1(state_dir=self.state_dir) if ContextSearchProfitabilitySuiteV1 else None
        self.portfolio_risk_intelligence_suite = PortfolioRiskIntelligenceSuiteV1(state_dir=self.state_dir) if PortfolioRiskIntelligenceSuiteV1 else None

    def _load(self) -> dict[str, Any]:
        if self._state is not None:
            return dict(self._state)
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._state = data if isinstance(data, dict) else {}
        except Exception:
            self._state = {}
        return dict(self._state or {})

    def _write(self, state: dict[str, Any]) -> None:
        self._state = dict(state or {})
        try:
            os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".stable_top_buys.", suffix=".tmp", dir=os.path.dirname(self.snapshot_path))
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, sort_keys=True, separators=(",", ":"), default=str)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.snapshot_path)
        except Exception:
            # Snapshot persistence is helpful but not required for safe operation.
            pass

    def _score(self, row: dict[str, Any]) -> float:
        quality = _f(row.get("buy_quality_score"), _f(row.get("trade_quality_score"), _f(row.get("quality_score"), _grade_score(row))))
        confidence = _f(row.get("confidence"), _f(row.get("predicted_win_probability"), 0.0))
        conv10 = _f(row.get("conviction_10r"), _f(row.get("rolling_conviction_10r"), _f(row.get("conviction_display_score"), quality)))
        conv5 = _f(row.get("conviction_5r"), _f(row.get("rolling_conviction_5r"), conv10))
        conv20 = _f(row.get("conviction_20r"), _f(row.get("rolling_conviction_20r"), conv10))
        entry_v3 = _f(row.get("entry_quality_v3_score"), _f(row.get("entry_quality_v2_score"), _f(row.get("entry_quality_score"), 50.0)))
        psychology = _f(row.get("psychology_score"), 60.0)
        consensus = _f(row.get("multi_brain_agreement"), _f(row.get("multi_brain_score"), 50.0))
        grade_pct = _grade_score(row)
        regime = _f(row.get("market_regime_alignment"), 50.0)
        stop_score = _f(row.get("distance_from_stop_score"), _f(row.get("reward_risk_quality"), 50.0))
        persistence = _f(row.get("persistence_score"), 50.0)
        readiness_bonus = self._readiness_bonus(row)
        fallback_penalty = 8.0 if bool(row.get("fallback_watch_candidate") or row.get("dashboard_fallback_candidate")) else 0.0
        opportunity = _f(row.get("profit_priority_score"), _f(row.get("opportunity_score_pct"), 0.0))
        opportunity_component = opportunity if opportunity > 0 else (
            grade_pct * 0.17
            + conv10 * 0.18
            + quality * 0.13
            + confidence * 0.12
            + entry_v3 * 0.11
            + consensus * 0.08
            + psychology * 0.06
            + regime * 0.05
            + stop_score * 0.04
            + persistence * 0.06
            + conv5 * 0.03
            + conv20 * 0.03
        )
        score = (
            opportunity_component * 0.52
            + grade_pct * 0.08
            + conv10 * 0.12
            + quality * 0.06
            + confidence * 0.06
            + entry_v3 * 0.06
            + persistence * 0.06
            + readiness_bonus
            - fallback_penalty
        )
        return round(max(0.0, min(110.0, score)), 3)

    def _apply_profit_opportunity_fields(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row or {})
        try:
            if self.expected_return_engine:
                out.update(self.expected_return_engine.score_row(out) or {})
        except Exception as exc:
            out.setdefault("expected_return_available", False)
            out.setdefault("expected_return_unavailable_reason", f"expected_return_error: {exc}"[:160])
        try:
            if self.target_zone_engine:
                out.update(self.target_zone_engine.score_row(out) or {})
        except Exception as exc:
            out.setdefault("target_zone_available", False)
            out.setdefault("target_unavailable_reason", f"target_zone_error: {exc}"[:160])
        try:
            if self.opportunity_scoring_engine:
                out.update(self.opportunity_scoring_engine.score_row(out) or {})
        except Exception as exc:
            out.setdefault("opportunity_grade", "Watch")
            out.setdefault("opportunity_score_pct", None)
            out.setdefault("opportunity_error", str(exc)[:160])
        try:
            if self.exit_averaging_engine:
                out.update(self.exit_averaging_engine.score_row(out) or {})
        except Exception as exc:
            out.setdefault("exit_score_available", False)
            out.setdefault("exit_unavailable_reason", f"exit_averaging_error: {exc}"[:160])
        try:
            if self.context_profitability_suite:
                out.update(self.context_profitability_suite.score_row(out) or {})
        except Exception as exc:
            out.setdefault("context_search_profitability_suite_v1", False)
            out.setdefault("context_summary", f"context_profitability_unavailable: {exc}"[:160])
        try:
            if self.portfolio_risk_intelligence_suite:
                out.update(self.portfolio_risk_intelligence_suite.score_row(out) or {})
        except Exception as exc:
            out.setdefault("portfolio_risk_intelligence_suite_v1", False)
            out.setdefault("portfolio_risk_summary", f"portfolio_risk_intelligence_unavailable: {exc}"[:160])
        out["paper_trade_learning_fields_shadow"] = {
            "opportunity_score_at_entry": out.get("opportunity_score_pct"),
            "expected_return_pct_at_entry": out.get("expected_return_pct"),
            "target_zone_at_entry": out.get("target_zone_display"),
            "stop_at_entry": _first_present(out, ("stop_loss", "stop", "stop_price")),
            "exit_score_at_exit": out.get("exit_score"),
            "target_hit_status": out.get("target_hit_status"),
            "premature_exit_flag": False,
            "late_exit_flag": False,
            "missed_profit_flag": False,
            "realized_return_pct": None,
            "realized_R_multiple": None,
            "target_accuracy_score": None,
            "exit_quality_score": None,
            "mode": "shadow_paper_learning_schema",
        }
        return out

    def _readiness_bonus(self, row: dict[str, Any]) -> float:
        text = " ".join(
            _norm_text(row.get(k))
            for k in (
                "top_buy_action",
                "action",
                "prediction",
                "canonical_final_state",
                "canonical_release_state",
                "hero_deployment_status",
                "recommended_entry_mode",
                "buy_eligibility",
            )
        )
        if "strong_buy" in text:
            return 7.0
        if "released_buy" in text or "buy_candidate" in text or "soft_buy" in text:
            return 5.0
        if "paper_ready" in text or "paper_only" in text:
            return 3.0
        if "needs_confirmation" in text or "wait_for_confirmation" in text:
            return 1.0
        return 0.0

    def _direction_kind(self, row: dict[str, Any]) -> str:
        text = " ".join(
            _norm_text(row.get(k))
            for k in (
                "top_buy_action",
                "action",
                "prediction",
                "canonical_final_state",
                "canonical_release_state",
                "hero_deployment_status",
                "hero_card_deployment_label",
                "recommended_entry_mode",
                "buy_eligibility",
                "final_action",
            )
        )
        if any(token in text for token in ("avoid", "blocked", "reject", "sell", "short")):
            return "sell_or_blocked"
        if any(token in text for token in ("buy", "long", "paper_ready", "paper_only", "soft_buy", "released_buy", "wait_for_confirmation")):
            return "buy"
        if "hold" in text or "watchlist" in text or "monitor" in text:
            return "hold"
        return "informational"

    def _data_quality_reason(self, row: dict[str, Any]) -> str:
        if not _symbol(row):
            return "missing_symbol"
        price = _first_present(row, ("current_price", "price", "live_price", "last_price", "close", "mark_price"))
        if price is None or _f(price, 0.0) <= 0:
            return "missing_or_invalid_price"
        if row.get("valid_quote") is False or row.get("trusted_quote_for_buys") is False:
            return "invalid_or_untrusted_quote"
        if not str(row.get("grade") or row.get("buy_grade") or row.get("grade_percent") or "").strip():
            return "missing_grade"
        if _first_present(row, ("confidence", "buy_confidence", "predicted_win_probability")) is None:
            return "missing_confidence"
        if _first_present(row, ("conviction_10r", "rolling_conviction_10r", "conviction_display_score")) is None:
            return "missing_10r_conviction"
        return ""

    def _normalize_display_fields(self, row: dict[str, Any], *, score: float, state: str, first_seen: float, age: float, retained: bool, replacement_reason: str = "") -> dict[str, Any]:
        out = self._apply_profit_opportunity_fields(dict(row or {}))
        price = _first_present(out, ("current_price", "price", "live_price", "last_price", "close", "mark_price"))
        if price is not None:
            out["current_price"] = price
            out["price"] = _first_present(out, ("price", "current_price")) or price
        stop = _first_present(out, ("stop_loss", "stop", "stop_price", "invalidation_level"))
        if stop is not None:
            out["stop_loss"] = stop
        conv5 = _first_present(out, ("conviction_5r", "rolling_conviction_5r", "five_r_conviction"))
        conv10 = _first_present(out, ("conviction_10r", "rolling_conviction_10r", "conviction_display_score", "ten_r_conviction"))
        conv20 = _first_present(out, ("conviction_20r", "rolling_conviction_20r", "twenty_r_conviction"))
        out["conviction_5r"] = conv5
        out["conviction_10r"] = conv10
        out["conviction_20r"] = conv20
        out["rolling_conviction_5r"] = conv5
        out["rolling_conviction_10r"] = conv10
        out["rolling_conviction_20r"] = conv20
        out["conviction_display_score"] = conv10
        out["expected_move"] = _first_present(out, ("expected_move", "profit_prediction_usd", "expected_move_dollars", "expected_move_usd", "predicted_profit_dollars"))
        out["expected_move_percent"] = _first_present(out, ("expected_move_percent", "expected_move_pct", "profit_prediction_pct", "predicted_return_pct"))
        if _f(out.get("expected_move"), 0.0) == 0.0 and _f(out.get("expected_move_percent"), 0.0) == 0.0:
            out["expected_move"] = None
            out["expected_move_percent"] = None
        out["top_6_rank"] = int(out.get("top_6_rank") or 0)
        out["readiness_label"] = self._readiness_label(out, state)
        out["action_label"] = self._action_label(out)
        out["fallback_watch_candidate"] = bool(out.get("fallback_watch_candidate", False))
        out["stable_layer_state"] = state
        out["stable_display_state"] = state
        out["stable_retained"] = bool(retained)
        out["stable_since"] = datetime.fromtimestamp(first_seen, UTC).isoformat().replace("+00:00", "Z")
        out["stable_first_seen_ts"] = first_seen
        out["stable_last_seen_ts"] = time.time()
        out["stable_age_seconds"] = round(age, 2)
        profit_score = _f(out.get("profit_priority_score"), _f(out.get("opportunity_score_pct"), score))
        out["stability_score"] = score
        out["stable_composite_score"] = score
        out["astra_composite_score"] = round(max(0.0, min(100.0, score)), 3)
        out["profit_priority_score"] = round(max(0.0, min(100.0, profit_score)), 3)
        out["replacement_reason"] = replacement_reason
        out["pending_challenger"] = False
        return out

    def _action_label(self, row: dict[str, Any]) -> str:
        kind = self._direction_kind(row)
        if kind == "buy":
            return "Buy"
        if kind == "hold":
            return "Hold"
        if kind == "sell_or_blocked":
            return "Blocked"
        return "Informational"

    def _readiness_label(self, row: dict[str, Any], state: str = "") -> str:
        text = " ".join(_norm_text(row.get(k)) for k in ("top_buy_action", "buy_eligibility", "hero_deployment_status", "recommended_entry_mode", "canonical_final_state"))
        if bool(row.get("fallback_watch_candidate")):
            return "Fallback Watch Candidate"
        if "strong_buy" in text or _grade_score(row) >= 85 and _f(row.get("conviction_10r"), _f(row.get("rolling_conviction_10r"), 0.0)) >= 75:
            return "Strong Buy"
        if "paper" in text or "paper" in _norm_text(state):
            return "Paper Ready"
        if "confirmation" in text or "confirmation" in _norm_text(state):
            return "Needs Confirmation"
        return "Buy"

    def _hard_invalid_reason(self, row: dict[str, Any]) -> str:
        if not row:
            return "missing_candidate"
        if row.get("valid_quote") is False or row.get("trusted_quote_for_buys") is False:
            return "invalid_or_untrusted_quote"
        confidence = _f(row.get("confidence"), 0.0)
        if confidence and confidence < self.hard_confidence_floor:
            return "confidence_below_hard_floor"
        state = str(row.get("canonical_final_state") or row.get("top_buy_action") or row.get("prediction") or row.get("action") or "").lower()
        if any(token in state for token in ("avoid", "blocked", "reject", "sell", "short")):
            return "canonical_state_blocked_or_avoid"
        price = _f(row.get("price"), _f(row.get("current_price"), 0.0))
        stop = _f(row.get("stop_loss"), _f(row.get("stop"), 0.0))
        if price > 0 and stop > 0 and price <= stop:
            return "stop_or_invalidation_level_breached"
        risk = str(row.get("risk_state") or row.get("risk_status") or "").lower()
        if any(token in risk for token in ("unacceptable", "halt", "invalid")):
            return "risk_state_unacceptable"
        return ""

    def _display_state(self, row: dict[str, Any], score: float, age_seconds: float) -> str:
        if bool(row.get("fallback_watch_candidate")):
            return "fallback_watch_candidate"
        if score < self.min_quality_floor + 8:
            return "needs_confirmation"
        if age_seconds < self.min_hold_seconds and score < self.min_quality_floor + 14:
            return "watch_closely"
        if str(row.get("recommended_entry_mode") or "").lower() in {"paper_only", "wait_for_confirmation"}:
            return "paper_only"
        return "stable"

    def _build_candidates(self, raw_rows: list[dict[str, Any]], qualified: list[dict[str, Any]], watchlist: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        buy_by_symbol: dict[str, dict[str, Any]] = {}
        hold_by_symbol: dict[str, dict[str, Any]] = {}
        counts = {
            "excluded_sell_count": 0,
            "excluded_hold_count": 0,
            "excluded_blocked_count": 0,
            "excluded_invalid_count": 0,
            "qualified_buy_candidates_count": 0,
            "hold_fallback_candidates_count": 0,
        }
        for row in raw_rows + qualified + watchlist:
            if not isinstance(row, dict):
                continue
            sym = _symbol(row)
            enriched = self._apply_profit_opportunity_fields(dict(row))
            quality_reason = self._data_quality_reason(enriched)
            direction = self._direction_kind(enriched)
            if quality_reason:
                counts["excluded_invalid_count"] += 1
                continue
            if direction == "sell_or_blocked":
                if any(token in " ".join(_norm_text(enriched.get(k)) for k in ("canonical_final_state", "top_buy_action", "action", "prediction")) for token in ("blocked", "avoid", "reject")):
                    counts["excluded_blocked_count"] += 1
                else:
                    counts["excluded_sell_count"] += 1
                continue
            enriched["candidate_direction_kind"] = direction
            enriched["stable_composite_score"] = self._score(enriched)
            if direction == "buy":
                old = buy_by_symbol.get(sym)
                if not old or _f(enriched.get("stable_composite_score"), 0.0) > _f(old.get("stable_composite_score"), 0.0):
                    buy_by_symbol[sym] = enriched
            elif direction == "hold":
                counts["excluded_hold_count"] += 1
                hold = dict(enriched)
                hold["fallback_watch_candidate"] = True
                old = hold_by_symbol.get(sym)
                if not old or _f(hold.get("stable_composite_score"), 0.0) > _f(old.get("stable_composite_score"), 0.0):
                    hold_by_symbol[sym] = hold
            else:
                counts["excluded_invalid_count"] += 1
        buys = list(buy_by_symbol.values())
        holds = [r for sym, r in hold_by_symbol.items() if sym not in buy_by_symbol]
        counts["qualified_buy_candidates_count"] = len(buys)
        counts["hold_fallback_candidates_count"] = len(holds)
        candidates = buys + (holds if len(buys) < 6 else [])
        return candidates, counts

    def _update_rank_memory(self, candidates: list[dict[str, Any]], prior_memory: dict[str, Any], now: float) -> dict[str, Any]:
        memory = {str(k).upper(): dict(v or {}) for k, v in dict(prior_memory or {}).items() if isinstance(v, dict)}
        prelim = sorted(candidates, key=lambda r: _f(r.get("stable_composite_score"), 0.0), reverse=True)
        seen = set()
        for idx, row in enumerate(prelim, start=1):
            sym = _symbol(row)
            if not sym:
                continue
            seen.add(sym)
            rec = dict(memory.get(sym) or {})
            last_ts = _f(rec.get("last_seen_ts"), now)
            elapsed = max(0.0, min(300.0, now - last_ts))
            prior_rank = int(_f(rec.get("last_rank"), idx))
            if prior_rank == 1:
                rec["time_at_rank_1_seconds"] = _f(rec.get("time_at_rank_1_seconds"), 0.0) + elapsed
            if prior_rank <= 3:
                rec["time_in_top_3_seconds"] = _f(rec.get("time_in_top_3_seconds"), 0.0) + elapsed
            if prior_rank <= 6:
                rec["time_in_top_6_seconds"] = _f(rec.get("time_in_top_6_seconds"), 0.0) + elapsed
            rec["rank_samples"] = int(_f(rec.get("rank_samples"), 0.0)) + 1
            rec["rank_sum"] = _f(rec.get("rank_sum"), 0.0) + float(idx)
            rec["average_rank"] = round(_f(rec.get("rank_sum"), 0.0) / max(1, int(_f(rec.get("rank_samples"), 1))), 3)
            rec["average_rank_10r"] = rec["average_rank"]
            rec["consecutive_top_3_refreshes"] = int(_f(rec.get("consecutive_top_3_refreshes"), 0.0)) + 1 if idx <= 3 else 0
            rec["consecutive_top_6_refreshes"] = int(_f(rec.get("consecutive_top_6_refreshes"), 0.0)) + 1 if idx <= 6 else 0
            rec["last_rank"] = idx
            rec["last_seen_ts"] = now
            rec["rank_stability_score"] = round(max(0.0, min(100.0, 105.0 - (rec["average_rank"] * 11.0) + min(20.0, rec["consecutive_top_6_refreshes"] * 2.5))), 3)
            rec["persistence_score"] = round(max(0.0, min(100.0, (rec["rank_stability_score"] * 0.65) + min(35.0, _f(rec.get("time_in_top_6_seconds"), 0.0) / 90.0))), 3)
            memory[sym] = rec
        for sym, rec in list(memory.items()):
            if sym not in seen and now - _f(rec.get("last_seen_ts"), now) > 3600:
                memory.pop(sym, None)
        for row in candidates:
            sym = _symbol(row)
            rec = memory.get(sym, {})
            row.update({
                "average_rank": rec.get("average_rank"),
                "average_rank_10r": rec.get("average_rank_10r"),
                "time_at_rank_1_seconds": round(_f(rec.get("time_at_rank_1_seconds"), 0.0), 2),
                "time_in_top_3_seconds": round(_f(rec.get("time_in_top_3_seconds"), 0.0), 2),
                "time_in_top_6_seconds": round(_f(rec.get("time_in_top_6_seconds"), 0.0), 2),
                "rank_stability_score": rec.get("rank_stability_score"),
                "persistence_score": rec.get("persistence_score"),
                "consecutive_top_3_refreshes": int(_f(rec.get("consecutive_top_3_refreshes"), 0.0)),
                "consecutive_top_6_refreshes": int(_f(rec.get("consecutive_top_6_refreshes"), 0.0)),
            })
            row["stable_composite_score"] = self._score(row)
        return memory

    def _sort_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda r: (
                1 if self._direction_kind(r) == "buy" else 0,
                _f(r.get("profit_priority_score"), _f(r.get("opportunity_score_pct"), 0.0)),
                _f(r.get("expected_return_pct"), 0.0),
                _f(r.get("stable_composite_score"), 0.0),
                _grade_score(r),
                _f(r.get("conviction_10r"), _f(r.get("rolling_conviction_10r"), 0.0)),
                _f(r.get("persistence_score"), 0.0),
            ),
            reverse=True,
        )

    def select(self, raw_payload: dict[str, Any] | None, *, buy_mode: str = "balanced") -> dict[str, Any]:
        now = time.time()
        payload = dict(raw_payload or {})
        raw_rows = list(((payload.get("stocks") or {}).get("final") or []) or [])
        qualified = list(((payload.get("stocks") or {}).get("qualified") or []) or [])
        watchlist = list(((payload.get("stocks") or {}).get("watchlist") or []) or [])
        state = self._load()
        raw_candidates, filter_counts = self._build_candidates(raw_rows, qualified, watchlist)
        rank_memory = self._update_rank_memory(raw_candidates, dict(state.get("rank_memory") or {}), now)
        candidates = self._sort_candidates(raw_candidates)
        candidates_by_symbol = {_symbol(r): dict(r) for r in candidates if _symbol(r)}
        prior_rows = list(state.get("stable_top_6") or [])
        prior_by_symbol = {_symbol(r): dict(r) for r in prior_rows if isinstance(r, dict) and _symbol(r)}
        challenger_counts = dict(state.get("challenger_counts") or {})
        retained: list[str] = []
        invalidated: list[dict[str, str]] = []
        stable: list[dict[str, Any]] = []

        for prior in prior_rows:
            if not isinstance(prior, dict):
                continue
            sym = _symbol(prior)
            if not sym:
                continue
            current = candidates_by_symbol.get(sym)
            if current is None:
                invalidated.append({"symbol": sym, "reason": "not_buy_candidate_or_no_longer_qualified"})
                continue
            reason = self._hard_invalid_reason(current)
            if reason:
                invalidated.append({"symbol": sym, "reason": reason})
                continue
            first_seen = _f(prior.get("stable_first_seen_ts"), now)
            age = max(0.0, now - first_seen)
            score = self._score(current)
            if score >= self.min_quality_floor or age < self.min_hold_seconds:
                state_label = self._display_state(current, score, age)
                out = self._normalize_display_fields(current, score=score, state=state_label, first_seen=first_seen, age=age, retained=True)
                stable.append(out)
                retained.append(sym)
            else:
                invalidated.append({"symbol": sym, "reason": "below_quality_floor_after_hold_window"})

        stable_symbols = {_symbol(r) for r in stable}
        pending_challengers: list[dict[str, Any]] = []
        replaced_symbols: list[str] = []

        def weakest_index() -> int:
            if not stable:
                return -1
            return min(range(len(stable)), key=lambda i: _f(stable[i].get("stable_composite_score"), 0.0))

        for challenger in candidates:
            sym = _symbol(challenger)
            if not sym or sym in stable_symbols:
                continue
            reason = self._hard_invalid_reason(challenger)
            if reason:
                continue
            score = self._score(challenger)
            challenger["stable_composite_score"] = score
            if len(stable) < 6:
                out = self._normalize_display_fields(challenger, score=score, state="new_fill", first_seen=now, age=0.0, retained=False, replacement_reason="fill_open_slot")
                stable.append(out)
                stable_symbols.add(sym)
                replaced_symbols.append(sym)
                continue
            idx = weakest_index()
            weakest = stable[idx]
            weakest_score = _f(weakest.get("stable_composite_score"), 0.0)
            margin = score - weakest_score
            count = int(challenger_counts.get(sym, 0)) + 1 if margin >= self.challenger_margin_required else 0
            challenger_counts[sym] = count
            if margin >= self.challenger_margin_required and count >= self.consecutive_refreshes_required:
                removed = _symbol(weakest)
                out = self._normalize_display_fields(challenger, score=score, state="challenger_promoted", first_seen=now, age=0.0, retained=False, replacement_reason=f"beat_{removed}_by_{round(margin, 3)}")
                stable[idx] = out
                stable_symbols.discard(removed)
                stable_symbols.add(sym)
                replaced_symbols.append(f"{removed}->{sym}" if removed else sym)
            else:
                pending_challengers.append({"symbol": sym, "stable_composite_score": score, "margin_vs_weakest": round(margin, 3), "consecutive_refreshes": count})

        stable = self._sort_candidates(stable)[:6]
        for idx, row in enumerate(stable, start=1):
            row["top_6_rank"] = idx
            row["expected_profit_rank"] = idx
            row["ranked_reason"] = (
                "Ranked #1 because it has the strongest probability-adjusted mix of expected return, 10R conviction, entry quality, confidence, and rank persistence."
                if idx == 1
                else "Ranked by probability-adjusted expected return, 10R conviction, entry quality, confidence, quality, and persistence."
            )
        avg_astra = sum(_f(r.get("astra_composite_score"), _f(r.get("stable_composite_score"), 0.0)) for r in stable) / max(1, len(stable))
        avg_10r = sum(_f(r.get("conviction_10r"), _f(r.get("rolling_conviction_10r"), 0.0)) for r in stable) / max(1, len(stable))
        avg_conf = sum(_f(r.get("confidence"), 0.0) for r in stable) / max(1, len(stable))
        avg_opp = sum(_f(r.get("opportunity_score_pct"), 0.0) for r in stable) / max(1, len(stable))
        avg_return = sum(_f(r.get("expected_return_pct"), 0.0) for r in stable) / max(1, len(stable))
        cap_counts = {"large_cap_count": 0, "mid_cap_count": 0, "small_cap_count": 0, "unknown_cap_count": 0}
        for row in stable:
            bucket = _market_cap_bucket(row)
            cap_counts[f"{bucket}_count"] = int(cap_counts.get(f"{bucket}_count", 0)) + 1
        state_out = {
            "enabled": True,
            "version": VERSION,
            "mode": "stable_top_6_presentation_layer",
            "local_only": True,
            "writes_files": True,
            "api_calls_used": 0,
            "stable_top_buys_v1": True,
            "stable_top_6": stable,
            "raw_candidates_count": len(raw_rows) + len(qualified) + len(watchlist),
            "ranked_candidates_count": len(candidates),
            "qualified_buy_candidates_count": int(filter_counts.get("qualified_buy_candidates_count", 0)),
            "excluded_sell_count": int(filter_counts.get("excluded_sell_count", 0)),
            "excluded_hold_count": int(filter_counts.get("excluded_hold_count", 0)),
            "excluded_blocked_count": int(filter_counts.get("excluded_blocked_count", 0)),
            "excluded_invalid_count": int(filter_counts.get("excluded_invalid_count", 0)),
            "stable_count": len(stable),
            "stable_top_6_count": len(stable),
            "stocks_final_count": len(stable),
            "replaced_symbols": replaced_symbols,
            "retained_symbols": retained,
            "pending_challengers": pending_challengers[:12],
            "invalidated_symbols": invalidated,
            "stability_mode": "hysteresis_min_hold_challenger_confirmation",
            "refresh_timestamp": _now_iso(),
            "refresh_ts": now,
            "min_hold_seconds": self.min_hold_seconds,
            "challenger_margin_required": self.challenger_margin_required,
            "consecutive_refreshes_required": self.consecutive_refreshes_required,
            "min_quality_floor": self.min_quality_floor,
            "hard_confidence_floor": self.hard_confidence_floor,
            "buy_mode": str(buy_mode or "balanced"),
            "raw_top_buys_stage": payload.get("top_buys_stage"),
            "raw_payload_source": payload.get("top_buys_payload_source"),
            "rank_persistence_enabled": True,
            "average_astra_score": round(avg_astra, 3),
            "average_10r_conviction": round(avg_10r, 3),
            "average_confidence": round(avg_conf, 3),
            "average_opportunity_score_pct": round(avg_opp, 3),
            "average_expected_return_pct": round(avg_return, 3),
            "best_opportunity_symbol": _symbol(stable[0]) if stable else "",
            "market_cap_breakdown": dict(cap_counts),
            "top_6_buy_only_filter_enabled": True,
            "hold_fallback_used": bool(any(r.get("fallback_watch_candidate") for r in stable)),
            "ranking_formula": "expected_return_25 + 10r_20 + entry_v3_15 + confidence_10 + grade_astra_10 + rank_persistence_10 + multi_brain_5 + psychology_5",
            "profit_maximizing_opportunity_engine_v1": True,
            "expected_return_engine_v1": True,
            "target_zone_engine_v1": True,
            "exit_averaging_engine_v1": True,
            "adaptive_policy_mode": "shadow_only",
            "live_trading_changed": False,
            "rankings_top_buys_strategy_changed": False,
            "next_recommended_action": "display_stable_top_6_and_allow_raw_top_buys_to_continue_running_independently",
            "challenger_counts": {k: v for k, v in challenger_counts.items() if v > 0},
            "rank_memory": rank_memory,
        }
        self._write(state_out)
        return dict(state_out)
