from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

VERSION = "1.0.0"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score01(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


class MarketSessionExecutionTimingV1:
    """Paper-only market session and execution confirmation guard.

    This suite blocks new paper broker submissions during closed-market windows,
    but still allows ranking, monitoring, learning, and execution intent.
    """

    def __init__(self, timezone_name: str = "America/New_York", market_calendar_knowledge_suite: Any | None = None) -> None:
        self.timezone_name = str(timezone_name or "America/New_York")
        self.market_calendar_knowledge_suite = market_calendar_knowledge_suite

    def _et_now(self, now_utc: datetime | None = None) -> datetime:
        now = now_utc or _now_utc()
        try:
            tz = ZoneInfo(self.timezone_name) if ZoneInfo is not None else timezone.utc
            return now.astimezone(tz)
        except Exception:
            return now

    @staticmethod
    def _observed_fixed(year: int, month: int, day: int) -> date:
        actual = date(year, month, day)
        if actual.weekday() == 5:
            return actual - timedelta(days=1)
        if actual.weekday() == 6:
            return actual + timedelta(days=1)
        return actual

    @staticmethod
    def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + (nth - 1) * 7)

    @staticmethod
    def _last_weekday(year: int, month: int, weekday: int) -> date:
        last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        offset = (last.weekday() - weekday) % 7
        return last - timedelta(days=offset)

    @staticmethod
    def _easter_date(year: int) -> date:
        # Meeus/Jones/Butcher algorithm; used only for local Good Friday detection.
        a = year % 19
        b = year // 100
        c = year % 100
        d = b // 4
        e = b % 4
        f = (b + 8) // 25
        g = (b - f + 1) // 3
        h = (19 * a + b - d - g + 15) % 30
        i = c // 4
        k = c % 4
        l = (32 + 2 * e + 2 * i - h - k) % 7
        m = (a + 11 * h + 22 * l) // 451
        month = (h + l - 7 * m + 114) // 31
        day = ((h + l - 7 * m + 114) % 31) + 1
        return date(year, month, day)

    def _is_market_holiday(self, day: date) -> bool:
        year = day.year
        holidays = {
            self._observed_fixed(year, 1, 1),   # New Year's Day
            self._nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
            self._nth_weekday(year, 2, 0, 3),   # Presidents' Day
            self._easter_date(year) - timedelta(days=2),  # Good Friday
            self._last_weekday(year, 5, 0),     # Memorial Day
            self._observed_fixed(year, 6, 19),  # Juneteenth
            self._observed_fixed(year, 7, 4),   # Independence Day
            self._nth_weekday(year, 9, 0, 1),   # Labor Day
            self._nth_weekday(year, 11, 3, 4),  # Thanksgiving
            self._observed_fixed(year, 12, 25), # Christmas
        }
        return day in holidays

    def session_status(self, now_utc: datetime | None = None) -> dict[str, Any]:
        if self.market_calendar_knowledge_suite is not None and hasattr(self.market_calendar_knowledge_suite, "status"):
            try:
                ctx = dict(self.market_calendar_knowledge_suite.status(allow_live_fetch=False, now_utc=now_utc) or {})
                if ctx:
                    return {
                        "enabled": True,
                        "version": VERSION,
                        "market_session_mode": _safe_text(ctx.get("current_session_type") or ctx.get("market_session_mode"), "unknown_closed"),
                        "market_is_open": bool(ctx.get("session_tradable") or ctx.get("market_is_open")),
                        "market_is_tradable": bool(ctx.get("session_tradable") or ctx.get("market_is_tradable")),
                        "paper_order_submission_allowed": bool(ctx.get("broker_order_submission_allowed") or ctx.get("paper_order_submission_allowed")),
                        "order_queueing_allowed": False,
                        "execution_confirmation_required": True,
                        "session_reason": _safe_text(ctx.get("session_reason"), "Market calendar context available."),
                        "session_timestamp_et": _safe_text(ctx.get("session_timestamp_et")),
                        "live_trading_changed": False,
                        "alpaca_paper_only_preserved": True,
                        "natural_exit_preserved": True,
                        **{k: v for k, v in ctx.items() if k not in {"enabled", "version", "api_calls_used"}},
                    }
            except Exception:
                pass
        et = self._et_now(now_utc)
        weekday = et.weekday()
        current = et.time()
        market_is_open = False
        market_is_tradable = False
        order_queueing_allowed = False
        execution_confirmation_required = True
        if weekday >= 5:
            mode = "weekend_closed"
            reason = "US equities market is closed for the weekend; ranking and learning may continue, but paper market orders are blocked."
        elif self._is_market_holiday(et.date()):
            mode = "holiday_closed"
            reason = "US equities market is closed for a market holiday; ranking and learning may continue, but paper market orders are blocked."
        elif time(9, 30) <= current < time(16, 0):
            mode = "regular_market"
            market_is_open = True
            market_is_tradable = True
            order_queueing_allowed = False
            execution_confirmation_required = True
            reason = "Regular market session; fresh confirmation required before paper order submission."
        elif time(4, 0) <= current < time(9, 30):
            mode = "premarket"
            market_is_tradable = False
            reason = "Premarket session; Astra may monitor but should wait for open structure before paper market orders."
        elif time(16, 0) <= current < time(20, 0):
            mode = "after_hours"
            market_is_tradable = False
            reason = "After-hours session; new paper market orders are deferred until fresh confirmation."
        else:
            mode = "unknown_closed"
            reason = "Closed-market window; new paper orders are blocked until tradable confirmation."
        paper_allowed = bool(market_is_open and market_is_tradable)
        return {
            "enabled": True,
            "version": VERSION,
            "market_session_mode": mode,
            "market_is_open": bool(market_is_open),
            "market_is_tradable": bool(market_is_tradable),
            "paper_order_submission_allowed": bool(paper_allowed),
            "order_queueing_allowed": bool(order_queueing_allowed),
            "execution_confirmation_required": bool(execution_confirmation_required),
            "session_reason": reason,
            "session_timestamp_et": et.isoformat(),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        }

    def confirmation_for_candidate(
        self,
        candidate: dict[str, Any] | None,
        gate_meta: dict[str, Any] | None = None,
        broker_ready: bool = False,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        row = dict(candidate or {})
        meta = dict(gate_meta or {})
        session = self.session_status(now_utc=now_utc)
        confidence = _score01(row.get("confidence"), _score01(row.get("expected_win_probability"), 50.0))
        entry = _score01(row.get("paper_entry_bridge_score"), _score01(row.get("entry_filter_v2_score"), 50.0))
        liquidity = _score01(row.get("liquidity_score"), _score01(row.get("data_quality_score"), 50.0))
        portfolio_ok = bool(row.get("portfolio_risk_ok", False) or _score01(row.get("portfolio_risk_score"), 50.0) >= 35.0)
        quote_age = _to_float(row.get("quote_age_seconds"), _to_float(row.get("freshness_seconds"), 9999.0))
        quote_ok = bool(quote_age <= 90.0 or _safe_text(row.get("quote_quality")).lower() == "live")
        spread_ok = bool(liquidity >= 45.0)
        gap_ok = bool(abs(_to_float(row.get("change_percent"), _to_float(row.get("change_pct"), 0.0))) <= 8.0)
        commitment = _to_float(meta.get("commitment_score"), 0.0)
        entry_ok = bool(commitment >= 50.0 or (confidence >= 72.0 and entry >= 50.0))
        score = _clamp((confidence * 0.20) + (entry * 0.20) + (liquidity * 0.16) + (100.0 if quote_ok else 20.0) * 0.16 + (100.0 if gap_ok else 25.0) * 0.10 + (100.0 if portfolio_ok else 20.0) * 0.10 + (100.0 if broker_ready else 0.0) * 0.08)
        if not session["paper_order_submission_allowed"]:
            label = "wait_for_open_structure"
            reason = session["session_reason"]
        elif not quote_ok:
            label = "reject_stale_signal"
            reason = "Quote freshness is not confirmed for paper order submission."
        elif score >= 72.0 and entry_ok and portfolio_ok and broker_ready:
            label = "confirmed_execute"
            reason = "Session, quote freshness, entry commitment, portfolio risk, and broker preflight are confirmed."
        elif score >= 52.0:
            label = "wait_for_open_structure"
            reason = "Candidate needs fresh open structure confirmation before paper order submission."
        else:
            label = "watch_only"
            reason = "Candidate remains watch-only until confirmation quality improves."
        return {
            **session,
            "open_confirmation_score": round(score, 2),
            "open_confirmation_label": label,
            "open_confirmation_reason": reason,
            "quote_freshness_confirmed": bool(quote_ok),
            "spread_liquidity_confirmed": bool(spread_ok),
            "gap_behavior_confirmed": bool(gap_ok),
            "entry_commitment_confirmed": bool(entry_ok),
            "portfolio_risk_confirmed": bool(portfolio_ok),
            "broker_preflight_confirmed": bool(broker_ready),
            "execution_intent_status": "intent_ready" if not session["paper_order_submission_allowed"] else ("confirmed" if label == "confirmed_execute" else "pending_confirmation"),
            "candidate_execution_intent": bool(not session["paper_order_submission_allowed"] and confidence >= 45.0),
            "defer_until_market_confirmation": bool(not session["paper_order_submission_allowed"]),
            "requires_open_confirmation": True,
            "weekend_watchlist_candidate": bool(session["market_session_mode"] == "weekend_closed" and confidence >= 45.0),
            "intent_created_reason": "closed_market_execution_intent_only" if not session["paper_order_submission_allowed"] else "",
            "replay_candidate_snapshot_saved": bool(confidence >= 45.0),
            "replay_learning_ready": bool(confidence >= 45.0),
            "replay_snapshot_reason": "candidate_session_context_ready_for_future_replay",
            "session_timing_outcome_tracking_ready": True,
            "trade_session_context": session["market_session_mode"],
            "entry_session_mode": session["market_session_mode"],
            "intended_execution_session": "next_regular_market_confirmation" if not session["paper_order_submission_allowed"] else "regular_market",
            "session_timing_learning_tag": f"{session['market_session_mode']}_paper_intent",
            "microstructure_analysis_enabled": False,
            "counterfactual_review_enabled": False,
        }

    def _stale_order_diagnostics(self, orders: list[dict[str, Any]] | None, session: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(o) for o in (orders or []) if isinstance(o, dict)]
        stale_symbols: list[str] = []
        weekend_symbols: list[str] = []
        stale_count = 0
        weekend_count = 0
        mode = str(session.get("market_session_mode") or "")
        for order in rows:
            symbol = _safe_text(order.get("symbol")).upper()
            status = _safe_text(order.get("status")).lower()
            tif = _safe_text(order.get("time_in_force")).lower()
            if status in {"new", "accepted", "pending_new", "held", "open"} and tif in {"day", ""}:
                stale_count += 1
                if symbol:
                    stale_symbols.append(symbol)
            if mode == "weekend_closed" and status in {"new", "accepted", "pending_new", "held", "open"}:
                weekend_count += 1
                if symbol:
                    weekend_symbols.append(symbol)
        reason = "no_stale_open_orders_detected"
        if weekend_count > 0:
            reason = "weekend_queued_paper_orders_need_manual_review"
        elif stale_count > 0:
            reason = "stale_day_open_orders_need_manual_review"
        return {
            "open_orders_count": len(rows),
            "stale_open_orders_count": int(stale_count),
            "weekend_queued_orders_count": int(weekend_count),
            "stale_order_symbols": sorted(set(stale_symbols + weekend_symbols))[:30],
            "stale_order_reason": reason,
            "cancel_stale_orders_recommended": bool(stale_count > 0 or weekend_count > 0),
            "auto_cancel_stale_paper_orders": False,
        }

    def decorate_candidate(self, row: dict[str, Any] | None, gate_meta: dict[str, Any] | None = None, broker_ready: bool = False) -> dict[str, Any]:
        out = dict(row or {})
        out.update(self.confirmation_for_candidate(out, gate_meta=gate_meta, broker_ready=broker_ready))
        return out

    def status(
        self,
        candidate: dict[str, Any] | None = None,
        gate_meta: dict[str, Any] | None = None,
        broker_ready: bool = False,
        open_orders: list[dict[str, Any]] | None = None,
        open_orders_count: int | None = None,
    ) -> dict[str, Any]:
        confirmation = self.confirmation_for_candidate(candidate or {}, gate_meta=gate_meta or {}, broker_ready=broker_ready)
        orders = [dict(o) for o in (open_orders or []) if isinstance(o, dict)]
        if open_orders_count is not None and not orders:
            orders = [{} for _ in range(max(0, int(open_orders_count or 0)))]
        stale = self._stale_order_diagnostics(orders, confirmation)
        recommended = "create_execution_intent_and_wait_for_open_confirmation"
        if confirmation["paper_order_submission_allowed"] and confirmation["open_confirmation_label"] == "confirmed_execute":
            recommended = "paper_order_submission_allowed_after_existing_safety_gates"
        elif stale["cancel_stale_orders_recommended"]:
            recommended = "manual_review_stale_paper_orders_before_next_session"
        return {
            **confirmation,
            **stale,
            "enabled": True,
            "version": VERSION,
            "recommended_action": recommended,
            "analysis_ranking_continues": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "forced_trade_enabled": False,
        }
