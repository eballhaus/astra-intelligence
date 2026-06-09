from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

VERSION = "1.0.0"
PAPER_BASE = "https://paper-api.alpaca.markets"
CACHE_FILE = "market_calendar_knowledge_cache_v1.json"
STATUS_TTL_SECONDS = 30.0
CALENDAR_CACHE_MAX_AGE_SECONDS = 20 * 60 * 60
MAX_ROWS = 180


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


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


def _bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _observed_fixed(year: int, month: int, day: int) -> date:
    actual = date(year, month, day)
    if actual.weekday() == 5:
        return actual - timedelta(days=1)
    if actual.weekday() == 6:
        return actual + timedelta(days=1)
    return actual


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + (nth - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def _easter_date(year: int) -> date:
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


_HOLIDAY_NAMES = {
    "new_years_day": "New Year's Day",
    "martin_luther_king_jr_day": "Martin Luther King Jr. Day",
    "presidents_day": "Presidents' Day",
    "good_friday": "Good Friday",
    "memorial_day": "Memorial Day",
    "juneteenth": "Juneteenth",
    "independence_day": "Independence Day",
    "labor_day": "Labor Day",
    "thanksgiving": "Thanksgiving Day",
    "christmas": "Christmas Day",
}


def _holiday_map(year: int) -> dict[date, str]:
    return {
        _observed_fixed(year, 1, 1): _HOLIDAY_NAMES["new_years_day"],
        _nth_weekday(year, 1, 0, 3): _HOLIDAY_NAMES["martin_luther_king_jr_day"],
        _nth_weekday(year, 2, 0, 3): _HOLIDAY_NAMES["presidents_day"],
        _easter_date(year) - timedelta(days=2): _HOLIDAY_NAMES["good_friday"],
        _last_weekday(year, 5, 0): _HOLIDAY_NAMES["memorial_day"],
        _observed_fixed(year, 6, 19): _HOLIDAY_NAMES["juneteenth"],
        _observed_fixed(year, 7, 4): _HOLIDAY_NAMES["independence_day"],
        _nth_weekday(year, 9, 0, 1): _HOLIDAY_NAMES["labor_day"],
        _nth_weekday(year, 11, 3, 4): _HOLIDAY_NAMES["thanksgiving"],
        _observed_fixed(year, 12, 25): _HOLIDAY_NAMES["christmas"],
    }


def _early_close_time(day: date) -> dtime | None:
    # Common NYSE early-close heuristics used only as fallback when Alpaca calendar is unavailable.
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    independence = date(day.year, 7, 4)
    christmas = date(day.year, 12, 25)
    if day == thanksgiving + timedelta(days=1):
        return dtime(13, 0)
    if independence.weekday() in {1, 2, 3, 4} and day == independence - timedelta(days=1):
        return dtime(13, 0)
    if christmas.weekday() in {1, 2, 3, 4} and day == christmas - timedelta(days=1):
        return dtime(13, 0)
    return None


def _parse_iso_dt(value: Any, tz: timezone | Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        if "T" in text:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt.astimezone(tz)
    except Exception:
        pass
    return None


def _parse_hhmm(value: Any, default: dtime) -> dtime:
    text = _text(value)
    if not text:
        return default
    try:
        parts = text.split(":")
        hh = max(0, min(23, int(parts[0])))
        mm = max(0, min(59, int(parts[1]) if len(parts) > 1 else 0))
        return dtime(hh, mm)
    except Exception:
        return default


class MarketCalendarKnowledgeIntelligenceV1:
    """Cached market-calendar truth and local market-context intelligence.

    Alpaca calendar is used as the preferred source when credentials and paper safety
    allow it. Unified diagnostics can request cached/local-only behavior so the
    Learning tab never depends on live broker/provider calls.
    """

    def __init__(self, state_dir: str = "state", timezone_name: str = "America/New_York", ttl_seconds: float = STATUS_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.timezone_name = str(timezone_name or "America/New_York")
        self.ttl_seconds = float(ttl_seconds or STATUS_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, CACHE_FILE)
        self._status_cache: dict[str, Any] | None = None
        self._status_cache_ts = 0.0

    def _tz(self):
        try:
            return ZoneInfo(self.timezone_name) if ZoneInfo is not None else timezone.utc
        except Exception:
            return timezone.utc

    def _et_now(self, now_utc: datetime | None = None) -> datetime:
        now = now_utc or _now_utc()
        return now.astimezone(self._tz())

    def _market_should_be_open_now(self, now_et: datetime) -> bool:
        day = now_et.date()
        if day.weekday() >= 5 or day in _holiday_map(day.year):
            return False
        local_row = self._local_market_day(day)
        if local_row is None:
            return False
        open_time = _parse_hhmm(local_row.get("open"), dtime(9, 30))
        close_time = _parse_hhmm(local_row.get("close"), dtime(16, 0))
        return bool(open_time <= now_et.time() < close_time)

    def _env(self) -> dict[str, str]:
        base = _text(os.getenv("APCA_API_BASE_URL") or os.getenv("ALPACA_BASE_URL") or PAPER_BASE).rstrip("/")
        pairs = (
            ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY"),
            ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
            ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET"),
            ("ALPACA_API_KEY", "APCA_API_SECRET_KEY"),
            ("APCA_API_KEY_ID", "ALPACA_SECRET_KEY"),
        )
        key = secret = ""
        for key_name, secret_name in pairs:
            key = _text(os.getenv(key_name))
            secret = _text(os.getenv(secret_name))
            if key and secret:
                break
        return {
            "base_url": base,
            "key": key,
            "secret": secret,
            "mode": _text(os.getenv("ALPACA_TRADING_MODE"), "paper").lower(),
            "enabled": str(_bool_env("ASTRA_ENABLE_ALPACA_PAPER", False)).lower(),
        }

    def _calendar_fetch_allowed(self) -> tuple[bool, str]:
        env = self._env()
        base = env["base_url"].lower().rstrip("/")
        paper_endpoint = "paper-api.alpaca.markets" in base
        live_endpoint = "api.alpaca.markets" in base and "paper-api.alpaca.markets" not in base
        if not _bool_env("ASTRA_ENABLE_ALPACA_PAPER", False):
            return False, "alpaca_paper_disabled_calendar_fallback"
        if env["mode"] != "paper":
            return False, "alpaca_trading_mode_not_paper_calendar_fallback"
        if not paper_endpoint or live_endpoint:
            return False, "alpaca_paper_endpoint_not_verified_calendar_fallback"
        if not env["key"] or not env["secret"]:
            return False, "missing_alpaca_credentials_calendar_fallback"
        return True, "alpaca_calendar_allowed"

    def _read_cache(self) -> dict[str, Any]:
        try:
            with open(self.cache_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_cache(self, payload: dict[str, Any]) -> None:
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self.cache_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def _calendar_rows_from_cache(self) -> tuple[list[dict[str, Any]], str, bool, bool, float]:
        cache = self._read_cache()
        rows = cache.get("calendar") if isinstance(cache.get("calendar"), list) else []
        fetched_at = _text(cache.get("fetched_at"))
        age = 999999.0
        if fetched_at:
            try:
                dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                age = max(0.0, (_now_utc() - dt.astimezone(timezone.utc)).total_seconds())
            except Exception:
                age = 999999.0
        source = _text(cache.get("source"), "local_estimate")
        hit = bool(rows)
        stale = bool(age > CALENDAR_CACHE_MAX_AGE_SECONDS)
        return [dict(r) for r in rows if isinstance(r, dict)], source, hit, stale, age

    def _fetch_alpaca_calendar(self, start: date, end: date) -> tuple[list[dict[str, Any]], str, int]:
        allowed, reason = self._calendar_fetch_allowed()
        if not allowed:
            return [], reason, 0
        env = self._env()
        base = env["base_url"].rstrip("/")
        if base.endswith("/v2"):
            url = base + "/calendar"
        else:
            url = base + "/v2/calendar"
        url += "?" + urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        req = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": env["key"],
                "APCA-API-SECRET-KEY": env["secret"],
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            data = json.loads(raw) if raw else []
            rows = [dict(r) for r in data if isinstance(r, dict)] if isinstance(data, list) else []
            if rows:
                self._write_cache({"source": "alpaca_calendar", "fetched_at": _now_iso(), "calendar": rows})
            return rows, "alpaca_calendar", 1
        except urllib.error.HTTPError as exc:
            return [], f"alpaca_calendar_http_{exc.code}_fallback", 1
        except Exception as exc:
            return [], f"alpaca_calendar_unavailable_fallback:{str(exc)[:90]}", 1

    def _local_market_day(self, day: date) -> dict[str, Any] | None:
        holidays = _holiday_map(day.year)
        if day.weekday() >= 5 or day in holidays:
            return None
        close = _early_close_time(day) or dtime(16, 0)
        return {"date": day.isoformat(), "open": "09:30", "close": close.strftime("%H:%M"), "source": "local_estimate"}

    def _calendar_for_window(self, today: date, allow_live_fetch: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cached_rows, cache_source, cache_hit, cache_stale, cache_age = self._calendar_rows_from_cache()
        api_calls = 0
        source = cache_source
        rows = cached_rows
        degraded = ""
        if allow_live_fetch and (not cache_hit or cache_stale):
            fetched, source, calls = self._fetch_alpaca_calendar(today - timedelta(days=7), today + timedelta(days=14))
            api_calls += calls
            if fetched:
                rows = fetched
                cache_hit = False
                cache_stale = False
                cache_age = 0.0
            elif rows:
                degraded = source
                source = cache_source
            else:
                degraded = source
        if not rows:
            rows = [r for i in range(-7, 15) if (r := self._local_market_day(today + timedelta(days=i))) is not None]
            source = "local_estimate"
            cache_hit = False
            cache_stale = False
        else:
            existing_days = set()
            for row in rows:
                try:
                    existing_days.add(date.fromisoformat(_text(row.get("date"))))
                except Exception:
                    continue
            for i in range(-7, 15):
                day = today + timedelta(days=i)
                if day in existing_days:
                    continue
                local_row = self._local_market_day(day)
                if local_row is not None:
                    rows.append(local_row)
        return rows, {
            "market_calendar_source": source,
            "market_calendar_cache_hit": cache_hit,
            "market_calendar_stale": bool(cache_stale),
            "market_calendar_cache_age_seconds": round(cache_age, 2),
            "api_calls_used": api_calls,
            "degraded_reason": degraded,
        }

    def _row_date(self, row: dict[str, Any]) -> date | None:
        try:
            return date.fromisoformat(_text(row.get("date")))
        except Exception:
            return None

    def _row_dt(self, row: dict[str, Any], key: str, fallback_time: dtime) -> datetime | None:
        tz = self._tz()
        parsed = _parse_iso_dt(row.get(key), tz)
        if parsed is not None:
            return parsed
        day = self._row_date(row)
        if day is None:
            return None
        raw = _text(row.get(key))
        try:
            parts = raw.split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            return datetime.combine(day, dtime(hh, mm), tzinfo=tz)
        except Exception:
            return datetime.combine(day, fallback_time, tzinfo=tz)

    def _session_from_calendar(self, rows: list[dict[str, Any]], now_et: datetime) -> dict[str, Any]:
        today = now_et.date()
        by_day = {self._row_date(r): r for r in rows if self._row_date(r) is not None}
        today_row = by_day.get(today)
        holidays = _holiday_map(today.year)
        holiday_name = holidays.get(today, "")
        is_weekend = today.weekday() >= 5
        is_holiday = bool((holiday_name and today_row is None) or (not is_weekend and today_row is None and today in holidays))
        if today_row:
            open_dt = self._row_dt(today_row, "open", dtime(9, 30)) or datetime.combine(today, dtime(9, 30), tzinfo=self._tz())
            close_dt = self._row_dt(today_row, "close", dtime(16, 0)) or datetime.combine(today, dtime(16, 0), tzinfo=self._tz())
        else:
            open_dt = datetime.combine(today, dtime(9, 30), tzinfo=self._tz())
            close_dt = datetime.combine(today, dtime(16, 0), tzinfo=self._tz())
        early = bool(today_row and close_dt.time() < dtime(16, 0))
        mode = "unknown_closed"
        if is_weekend:
            mode = "weekend_closed"
        elif is_holiday:
            mode = "holiday_closed"
        elif today_row:
            if now_et < open_dt:
                mode = "premarket" if now_et.time() >= dtime(4, 0) else "pre_open"
            elif open_dt <= now_et < close_dt:
                minutes_since = (now_et - open_dt).total_seconds() / 60.0
                minutes_until_close = (close_dt - now_et).total_seconds() / 60.0
                if early:
                    mode = "early_close_session"
                elif minutes_since <= 5:
                    mode = "opening_volatility_window"
                elif minutes_since <= 30:
                    mode = "opening_volatility_window"
                elif minutes_until_close <= 30:
                    mode = "closing_risk_window"
                elif dtime(11, 30) <= now_et.time() <= dtime(13, 45):
                    mode = "midday_lull"
                else:
                    mode = "regular_market"
            elif now_et.time() < dtime(20, 0):
                mode = "after_hours"
            else:
                mode = "overnight"
        future_days = sorted(d for d in by_day.keys() if d and d >= today)
        next_open_dt = None
        next_close_dt = None
        for day in future_days:
            row = by_day.get(day) or {}
            odt = self._row_dt(row, "open", dtime(9, 30))
            cdt = self._row_dt(row, "close", dtime(16, 0))
            if odt and cdt and (day > today or now_et < cdt):
                if day == today and now_et >= odt:
                    next_open_dt = odt
                else:
                    next_open_dt = odt
                next_close_dt = cdt
                break
        if next_open_dt is None:
            probe = today + timedelta(days=1)
            while probe.weekday() >= 5 or probe in _holiday_map(probe.year):
                probe += timedelta(days=1)
            next_open_dt = datetime.combine(probe, dtime(9, 30), tzinfo=self._tz())
            next_close_dt = datetime.combine(probe, dtime(16, 0), tzinfo=self._tz())
        minutes_until_open = (next_open_dt - now_et).total_seconds() / 60.0 if next_open_dt else None
        minutes_until_close = (close_dt - now_et).total_seconds() / 60.0 if today_row else None
        minutes_since_open = (now_et - open_dt).total_seconds() / 60.0 if today_row and now_et >= open_dt else None
        prev_day = today - timedelta(days=1)
        next_day = today + timedelta(days=1)
        post_holiday = bool(prev_day in _holiday_map(prev_day.year))
        pre_holiday = bool(next_day in _holiday_map(next_day.year))
        tradable_modes = {"regular_market", "opening_volatility_window", "midday_lull", "closing_risk_window", "early_close_session"}
        session_tradable = bool(mode in tradable_modes and today_row is not None)
        broker_allowed = bool(session_tradable and mode not in {"closing_risk_window"})
        risk_score = self._session_risk(mode, early, pre_holiday, post_holiday)
        return {
            "current_session_type": mode,
            "market_session_mode": mode,
            "session_tradable": bool(session_tradable),
            "market_is_open": bool(session_tradable),
            "market_is_tradable": bool(session_tradable),
            "broker_order_submission_allowed": bool(broker_allowed),
            "paper_order_submission_allowed": bool(broker_allowed),
            "order_queueing_allowed": False,
            "execution_confirmation_required": True,
            "session_risk_score": risk_score,
            "session_risk_label": self._risk_label(risk_score),
            "holiday_name": holiday_name,
            "is_market_holiday": bool(is_holiday),
            "is_early_close": bool(early),
            "early_close_time": close_dt.isoformat() if early else "",
            "next_market_open": next_open_dt.isoformat() if next_open_dt else "",
            "next_market_close": next_close_dt.isoformat() if next_close_dt else "",
            "minutes_until_open": None if minutes_until_open is None else round(minutes_until_open, 2),
            "minutes_until_close": None if minutes_until_close is None else round(minutes_until_close, 2),
            "minutes_since_open": None if minutes_since_open is None else round(minutes_since_open, 2),
            "post_holiday_session": bool(post_holiday),
            "pre_holiday_session": bool(pre_holiday),
            "session_reason": self._session_reason(mode, holiday_name, early),
            "session_timestamp_et": now_et.isoformat(),
        }

    def _session_risk(self, mode: str, early: bool, pre_holiday: bool, post_holiday: bool) -> float:
        base = {
            "regular_market": 28.0,
            "midday_lull": 44.0,
            "opening_volatility_window": 68.0,
            "closing_risk_window": 72.0,
            "early_close_session": 70.0,
            "premarket": 78.0,
            "after_hours": 82.0,
            "pre_open": 75.0,
            "overnight": 85.0,
            "weekend_closed": 100.0,
            "holiday_closed": 100.0,
            "unknown_closed": 90.0,
        }.get(mode, 75.0)
        if early:
            base += 8.0
        if pre_holiday or post_holiday:
            base += 6.0
        return round(_clamp(base), 2)

    def _risk_label(self, risk: float) -> str:
        if risk >= 90:
            return "closed_or_untradable"
        if risk >= 70:
            return "high_session_risk"
        if risk >= 50:
            return "elevated_session_risk"
        return "normal_session_risk"

    def _session_reason(self, mode: str, holiday_name: str, early: bool) -> str:
        if mode == "holiday_closed":
            return f"US equities market is closed for {holiday_name or 'a market holiday'}; observation and learning only."
        if mode == "weekend_closed":
            return "US equities market is closed for the weekend; observation and learning only."
        if mode == "early_close_session":
            return "Early-close session; paper entries require extra confirmation and liquidity caution."
        if mode == "opening_volatility_window":
            return "Opening volatility window; require confirmation against gaps and fakeouts."
        if mode == "midday_lull":
            return "Midday lull; reduce weak breakout aggression and prefer cleaner confirmation."
        if mode == "closing_risk_window":
            return "Final 30 minutes; avoid weak new entries and prioritize review discipline."
        if mode in {"premarket", "after_hours", "overnight", "pre_open"}:
            return "Extended/closed session; Astra may observe but should wait for tradable confirmation."
        return "Regular market session; existing paper safety gates and confirmation still apply."

    def _session_behavior(self, session: dict[str, Any]) -> dict[str, Any]:
        mode = _text(session.get("current_session_type"), "unknown_closed")
        risk = _to_float(session.get("session_risk_score"), 75.0)
        if mode in {"weekend_closed", "holiday_closed", "unknown_closed", "after_hours", "overnight", "pre_open"}:
            posture = "observe_only_execution_intent"
            confirm = "market_open_confirmation_required"
            aggressiveness = "blocked"
        elif mode == "premarket":
            posture = "premarket_liquidity_caution"
            confirm = "strong_confirmation_required"
            aggressiveness = "very_low"
        elif mode == "opening_volatility_window":
            posture = "gap_and_fakeout_confirmation"
            confirm = "opening_structure_confirmation_required"
            aggressiveness = "selective"
        elif mode == "midday_lull":
            posture = "midday_confirmation_first"
            confirm = "clean_continuation_required"
            aggressiveness = "low_selective"
        elif mode == "closing_risk_window":
            posture = "closing_risk_review_first"
            confirm = "avoid_weak_new_entries"
            aggressiveness = "low"
        elif mode == "early_close_session":
            posture = "early_close_liquidity_caution"
            confirm = "strong_confirmation_required"
            aggressiveness = "low_selective"
        else:
            posture = "regular_market_selective_execution"
            confirm = "normal_confirmation_required"
            aggressiveness = "balanced_selective"
        return {
            "session_execution_posture": posture,
            "session_entry_aggressiveness": aggressiveness,
            "session_confirmation_requirement": confirm,
            "session_liquidity_caution": round(_clamp(risk * 0.85), 2),
            "session_gap_risk": round(_clamp(risk + (12.0 if mode in {"opening_volatility_window", "post_holiday_session"} else 0.0)), 2),
            "session_false_breakout_risk": round(_clamp(risk + (14.0 if mode in {"opening_volatility_window", "midday_lull"} else 0.0)), 2),
            "session_profit_capture_bias": "protect_and_review" if mode in {"closing_risk_window", "early_close_session"} else "normal_profit_capture",
            "session_trade_permission_reason": _text(session.get("session_reason"), "session status available"),
        }

    def _knowledge(self, rows: list[dict[str, Any]], session: dict[str, Any]) -> dict[str, Any]:
        sample = [dict(r) for r in rows[:MAX_ROWS] if isinstance(r, dict)]
        if not sample:
            sample = []
        avg = lambda key, default=50.0: sum(_score(r.get(key), default) for r in sample) / max(1, len(sample))
        momentum = avg("momentum_expansion_score", avg("follow_through_probability", 50.0))
        breakout = avg("breakout_probability_score", avg("breakout_quality_score", 50.0))
        volatility = avg("volatility_expansion_score", avg("volatility_expansion_score", 50.0))
        liquidity = avg("liquidity_score", avg("execution_readiness_score", 55.0))
        correlation = avg("correlation_pressure_score", avg("portfolio_correlation_risk", 50.0))
        concentration = avg("portfolio_concentration_pressure", avg("portfolio_concentration_risk", 50.0))
        chase = avg("chase_risk_score", avg("momentum_extension_risk", 40.0))
        regime_counts = Counter(_text(r.get("current_market_regime") or r.get("current_regime_behavior"), "uncertain_regime") for r in sample)
        tiers = Counter(_text(r.get("candidate_universe_tier") or r.get("market_cap_tier"), "unknown") for r in sample)
        sectors = Counter(_text(r.get("sector") or r.get("sector_context_label"), "unknown") for r in sample)
        themes = Counter(_text(r.get("theme_context_label") or r.get("correlation_cluster_label") or r.get("opportunity_family"), "unknown") for r in sample)
        mode = _text(session.get("current_session_type"), "unknown_closed")
        risk = _to_float(session.get("session_risk_score"), 75.0)
        if risk >= 85:
            structure = "closed_observation_only"
        elif momentum >= 62 and volatility >= 55 and liquidity >= 48:
            structure = "momentum_continuation"
        elif breakout >= 62 and chase < 55:
            structure = "breakout_watch"
        elif correlation >= 70 or concentration >= 75:
            structure = "crowded_correlation_risk"
        elif volatility <= 42:
            structure = "volatility_compression"
        else:
            structure = "choppy_selective"
        market_score = _clamp((momentum * 0.22) + (breakout * 0.18) + (liquidity * 0.20) + ((100.0 - risk) * 0.20) + ((100.0 - chase) * 0.10) + ((100.0 - correlation) * 0.10))
        scalp = _clamp(liquidity * 0.40 + momentum * 0.24 + (100.0 - risk) * 0.20 + (100.0 - chase) * 0.16)
        day = _clamp(momentum * 0.30 + breakout * 0.22 + liquidity * 0.18 + (100.0 - risk) * 0.18 + volatility * 0.12)
        swing = _clamp((100.0 - chase) * 0.24 + (100.0 - correlation) * 0.20 + breakout * 0.18 + momentum * 0.18 + (100.0 - risk) * 0.20)
        mean_rev = _clamp((100.0 - momentum) * 0.25 + (100.0 - breakout) * 0.25 + (100.0 - risk) * 0.25 + liquidity * 0.25)
        rotation = _clamp((100.0 - concentration) * 0.22 + (100.0 - correlation) * 0.22 + momentum * 0.20 + liquidity * 0.18 + (100.0 - risk) * 0.18)
        style_scores = {"scalp": scalp, "day_trade": day, "swing_trade": swing, "mean_reversion": mean_rev, "rotation": rotation}
        best_style = max(style_scores.items(), key=lambda kv: kv[1])[0]
        top_tier = tiers.most_common(1)[0][0] if tiers else "unknown"
        top_sector = sectors.most_common(1)[0][0] if sectors else "unknown"
        top_theme = themes.most_common(1)[0][0] if themes else "unknown"
        behavioral = self._behavioral_state(momentum, chase, volatility, risk, breakout)
        confidence = _clamp(45.0 + min(35.0, len(sample) * 3.5) + (10.0 if session.get("market_calendar_available") else 0.0))
        return {
            "market_structure_label": structure,
            "market_structure_score": round(market_score, 2),
            "trade_style_environment": best_style,
            "scalp_environment_score": round(scalp, 2),
            "day_trade_environment_score": round(day, 2),
            "swing_environment_score": round(swing, 2),
            "breakout_environment_score": round(_clamp(breakout * 0.55 + (100.0 - chase) * 0.25 + liquidity * 0.20), 2),
            "mean_reversion_environment_score": round(mean_rev, 2),
            "momentum_environment_score": round(_clamp(momentum * 0.55 + liquidity * 0.20 + (100.0 - chase) * 0.25), 2),
            "rotation_environment_score": round(rotation, 2),
            "sector_context_label": top_sector,
            "theme_context_label": top_theme,
            "cap_context_label": top_tier,
            "sector_rotation_pressure": round(_clamp(100.0 - rotation), 2),
            "theme_crowding_pressure": round(_clamp(correlation * 0.55 + concentration * 0.45), 2),
            "cap_tier_opportunity_context": "mega_cap_crowding_watch" if "mega" in top_tier and concentration >= 65 else "balanced_cap_context",
            "sector_style_fit": f"{top_sector}:{best_style}",
            "theme_risk_reason": "theme_crowding_watch" if correlation >= 68 else "theme_pressure_normal",
            **behavioral,
            "market_context_summary": f"Session {mode}; structure {structure}; best style {best_style}; behavioral state {behavioral['behavioral_market_state']}.",
            "market_knowledge_confidence": round(confidence, 2),
            "current_market_regime": regime_counts.most_common(1)[0][0] if regime_counts else "uncertain_regime",
        }

    def _behavioral_state(self, momentum: float, chase: float, volatility: float, risk: float, breakout: float) -> dict[str, Any]:
        fomo = _clamp(momentum * 0.45 + chase * 0.35 + volatility * 0.20)
        panic = _clamp(risk * 0.45 + volatility * 0.35 + (100.0 - momentum) * 0.20)
        exhaustion = _clamp(chase * 0.45 + momentum * 0.25 + volatility * 0.18 + risk * 0.12)
        profit_take = _clamp(exhaustion * 0.55 + risk * 0.25 + breakout * 0.20)
        weak = _clamp((100.0 - momentum) * 0.40 + (100.0 - breakout) * 0.30 + risk * 0.30)
        squeeze = _clamp(momentum * 0.35 + volatility * 0.35 + breakout * 0.30)
        if panic >= 75:
            state = "panic_pressure"
        elif exhaustion >= 70:
            state = "exhaustion_risk"
        elif fomo >= 68:
            state = "fomo_risk"
        elif weak >= 68:
            state = "weak_conviction_rally"
        elif squeeze >= 68:
            state = "squeeze_risk"
        elif profit_take >= 66:
            state = "profit_taking_pressure"
        else:
            state = "stable_behavior"
        return {
            "behavioral_market_state": state,
            "behavioral_risk_score": round(_clamp(max(fomo, panic, exhaustion, weak) * 0.75 + risk * 0.25), 2),
            "fomo_risk": round(fomo, 2),
            "panic_risk": round(panic, 2),
            "exhaustion_risk": round(exhaustion, 2),
            "profit_taking_pressure": round(profit_take, 2),
            "weak_conviction_risk": round(weak, 2),
            "squeeze_context_score": round(squeeze, 2),
            "behavioral_context_summary": f"{state.replace('_', ' ')} with fomo {round(fomo,1)}, exhaustion {round(exhaustion,1)}, panic {round(panic,1)}.",
        }

    def _exploration_context(self, session: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
        tradable = bool(session.get("broker_order_submission_allowed") or session.get("paper_order_submission_allowed"))
        structure = _text(knowledge.get("market_structure_label"), "unknown")
        behavior = _text(knowledge.get("behavioral_market_state"), "stable_behavior")
        risk = _to_float(session.get("session_risk_score"), 75.0)
        market_score = _to_float(knowledge.get("market_structure_score"), 50.0)
        behavior_risk = _to_float(knowledge.get("behavioral_risk_score"), 50.0)
        quality = _clamp(market_score * 0.50 + (100.0 - risk) * 0.30 + (100.0 - behavior_risk) * 0.20)
        supports = bool(tradable and quality >= 42.0 and behavior not in {"panic_pressure", "exhaustion_risk"})
        reason = "market_context_supports_bounded_exploration" if supports else "market_context_requires_wait_or_stronger_confirmation"
        if structure in {"choppy_selective", "closed_observation_only"}:
            reason = "market_structure_limits_exploration_aggression"
        return {
            "market_context_supports_exploration": supports,
            "market_context_supports_trade": supports,
            "exploration_context_quality": round(quality, 2),
            "exploration_session_reason": _text(session.get("session_reason"), "session context available"),
            "exploration_market_knowledge_reason": reason,
            "context_adjusted_exploration_score": round(quality, 2),
            "context_adjusted_opportunity_score": round(quality, 2),
            "market_context_rejection_reason": "" if supports else reason,
        }

    def status(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        allow_live_fetch: bool = False,
        force: bool = False,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and not allow_live_fetch and self._status_cache is not None and now - self._status_cache_ts <= self.ttl_seconds:
            cached = dict(self._status_cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._status_cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        now_et = self._et_now(now_utc)
        cal_rows, meta = self._calendar_for_window(now_et.date(), allow_live_fetch=allow_live_fetch)
        session = self._session_from_calendar(cal_rows, now_et)
        session["market_calendar_available"] = bool(cal_rows)
        session.update(meta)
        session_now_utc = (now_utc or _now_utc()).astimezone(timezone.utc)
        session_now_et = session_now_utc.astimezone(self._tz())
        session_cache_age_seconds = _to_float(meta.get("market_calendar_cache_age_seconds"), 0.0)
        session_is_stale = bool(meta.get("market_calendar_stale")) or bool(session_cache_age_seconds >= CALENDAR_CACHE_MAX_AGE_SECONDS)
        market_should_be_open_now = bool(self._market_should_be_open_now(now_et))
        if session_is_stale:
            session["session_is_stale"] = True
            session["session_cache_age_seconds"] = round(session_cache_age_seconds, 2)
            session["session_now_utc"] = session_now_utc.isoformat().replace("+00:00", "Z")
            session["session_now_et"] = session_now_et.isoformat()
            session["session_source"] = _text(meta.get("market_calendar_source"), "local_estimate")
            session["market_should_be_open_now"] = bool(market_should_be_open_now)
            session["session_block_reason"] = "stale_session_cache"
            session["session_block_validated"] = bool(session.get("paper_order_submission_allowed", False) == market_should_be_open_now)
        else:
            session["session_is_stale"] = False
            session["session_cache_age_seconds"] = round(session_cache_age_seconds, 2)
            session["session_now_utc"] = session_now_utc.isoformat().replace("+00:00", "Z")
            session["session_now_et"] = session_now_et.isoformat()
            session["session_source"] = _text(meta.get("market_calendar_source"), "local_estimate")
            session["market_should_be_open_now"] = bool(market_should_be_open_now)
            session["session_block_reason"] = "none" if session.get("paper_order_submission_allowed", False) else _text(session.get("session_reason"), "market_closed")
            session["session_block_validated"] = bool(session.get("paper_order_submission_allowed", False) == market_should_be_open_now)
        behavior = self._session_behavior(session)
        knowledge = self._knowledge([dict(r) for r in (rows or []) if isinstance(r, dict)], session)
        exploration = self._exploration_context(session, knowledge)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_context_intelligence",
            "market_calendar_available": bool(cal_rows),
            **session,
            **behavior,
            **knowledge,
            **exploration,
            "market_calendar_knowledge_status_v1": True,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "api_calls_used": int(meta.get("api_calls_used", 0)),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "deterministic_execution_authority_preserved": True,
            "provider_rewrite_changed": False,
            "generated_at": _now_iso(),
        }
        if not allow_live_fetch:
            self._status_cache = dict(out)
            self._status_cache_ts = now
        return out

    def decorate_candidate(self, row: dict[str, Any] | None, status: dict[str, Any] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        ctx = dict(status or self.status(rows=[out], allow_live_fetch=False))
        keys = (
            "current_session_type", "market_session_mode", "session_tradable", "session_execution_posture",
            "session_confirmation_requirement", "market_structure_label", "trade_style_environment",
            "behavioral_market_state", "market_context_supports_trade", "market_context_rejection_reason",
            "context_adjusted_opportunity_score", "market_context_supports_exploration",
            "exploration_context_quality", "exploration_market_knowledge_reason",
        )
        for key in keys:
            if key in ctx:
                out[key if key != "current_session_type" else "market_calendar_session_type"] = ctx[key]
        out["market_calendar_session_type"] = _text(ctx.get("current_session_type"), _text(out.get("market_calendar_session_type"), "unknown_closed"))
        return out

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        base = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        if not base:
            return []
        ctx = self.status(rows=base, allow_live_fetch=False)
        return [self.decorate_candidate(row, status=ctx) for row in base[:MAX_ROWS]]

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        rows: list[dict[str, Any]] = []
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            for section in ("final", "qualified", "watchlist", "fill"):
                values = pack.get(section)
                if isinstance(values, list):
                    rows.extend([dict(v) for v in values if isinstance(v, dict)])
        summary = self.status(rows=rows, allow_live_fetch=False)
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            new_pack = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = new_pack.get(section)
                if isinstance(values, list):
                    new_pack[section] = [self.decorate_candidate(dict(v), status=summary) for v in values if isinstance(v, dict)]
            out[pack_key] = new_pack
        out["market_calendar_knowledge_intelligence_v1"] = True
        out["market_calendar_knowledge_summary_v1"] = summary
        return out
