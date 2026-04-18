"""
Minimal, runtime-safe Trade Intelligence engine reconstruction.

This module intentionally keeps scope narrow:
- Preserve expected public interface used by server_extend.py callers.
- Provide conservative analytics over trade_journal rows.
- Avoid policy/ranking/entry/exit behavior changes.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    return int(round(_to_float(value, float(default))))


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return "{}"


def _winsorized_avg(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    lo_idx = int(max(0, (n - 1) * 0.05))
    hi_idx = int(min(n - 1, (n - 1) * 0.95))
    lo = ordered[lo_idx]
    hi = ordered[hi_idx]
    clipped = [min(hi, max(lo, v)) for v in ordered]
    return sum(clipped) / float(max(1, len(clipped)))


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)


def _is_valid_label(row: dict[str, Any]) -> bool:
    raw = row.get("valid_label")
    if raw is None or raw == "":
        # Historical rows may not include explicit labels; treat as usable.
        return True
    return bool(_to_int(raw, 0))


def _normalize_key(raw: Any, unknown: str = "unknown") -> str:
    txt = str(raw or "").strip().lower()
    if txt in {"", "none", "null"}:
        return unknown
    return txt


class TradeIntelligenceEngine:
    def __init__(self, db_path: str | None = None):
        state_dir = os.path.join(os.getcwd(), "state")
        os.makedirs(state_dir, exist_ok=True)
        self.db_path = db_path or os.path.join(state_dir, "ai_trading_memory.db")
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_id TEXT UNIQUE,
                    symbol TEXT,
                    asset_type TEXT,
                    mode TEXT,
                    entry_timestamp TEXT,
                    entry_price REAL,
                    entry_predicted_probability REAL,
                    entry_persona_grade REAL,
                    entry_regime TEXT,
                    market_regime TEXT,
                    entry_persona_fit_summary TEXT,
                    entry_market_cap_category TEXT,
                    entry_sector TEXT,
                    entry_signal_tags TEXT,
                    persona_scores_entry TEXT,
                    final_consensus_persona_score REAL,
                    buy_mode TEXT,
                    buy_eligibility TEXT,
                    buy_quality_tier TEXT,
                    buy_quality_score REAL,
                    entry_confidence REAL,
                    setup_type TEXT,
                    entry_reason TEXT,
                    signal_tags TEXT,
                    exit_timestamp TEXT,
                    exit_price REAL,
                    exit_reason TEXT,
                    holding_period REAL,
                    return_percent REAL,
                    profit_loss_percent REAL,
                    friction_adjusted_return REAL,
                    valid_label INTEGER,
                    invalid_reason TEXT,
                    max_favorable_excursion REAL,
                    max_adverse_excursion REAL,
                    peak_unrealized_pnl_percent REAL,
                    drawdown_after_peak_percent REAL,
                    time_to_peak_seconds REAL,
                    time_to_exit_seconds REAL,
                    risk_context_json TEXT,
                    trade_origin TEXT,
                    created_at TEXT,
                    last_updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_replay_trades (
                    trade_id TEXT PRIMARY KEY,
                    valid_label INTEGER DEFAULT 0,
                    invalid_reason TEXT DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_exit_ts ON trade_journal(exit_timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_origin_exit ON trade_journal(trade_origin, exit_timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol)")
            conn.commit()

    def record_trade(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = dict(payload or {})
        now_iso = _utc_now_iso()
        trade_id = str(row.get("trade_id") or "").strip()
        symbol = str(row.get("symbol") or "").strip().upper()
        asset_type = "crypto" if str(row.get("asset_type") or "").strip().lower() == "crypto" else "stock"
        signal_tags = row.get("signal_tags")
        if signal_tags is None:
            signal_tags = row.get("entry_signal_tags")
        setup_type = str(row.get("setup_type") or "").strip().lower()
        if not setup_type:
            if isinstance(signal_tags, list) and signal_tags:
                setup_type = _normalize_key(signal_tags[0])
            elif isinstance(signal_tags, str) and signal_tags.strip():
                setup_type = _normalize_key(signal_tags.split(",")[0])
            else:
                setup_type = "unknown"
        values = {
            "trade_id": trade_id if trade_id else None,
            "symbol": symbol,
            "asset_type": asset_type,
            "mode": str(row.get("mode") or "intraday"),
            "entry_timestamp": row.get("entry_timestamp"),
            "entry_price": _to_float(row.get("entry_price"), 0.0),
            "entry_predicted_probability": _to_float(row.get("entry_predicted_probability"), 0.0),
            "entry_persona_grade": _to_float(row.get("entry_persona_grade"), 0.0),
            "entry_regime": str(row.get("entry_regime") or ""),
            "market_regime": str(row.get("market_regime") or row.get("entry_regime") or ""),
            "entry_persona_fit_summary": str(row.get("entry_persona_fit_summary") or ""),
            "entry_market_cap_category": str(row.get("entry_market_cap_category") or ""),
            "entry_sector": str(row.get("entry_sector") or ""),
            "entry_signal_tags": _json_dump(row.get("entry_signal_tags") if row.get("entry_signal_tags") is not None else signal_tags),
            "persona_scores_entry": _json_dump(row.get("persona_scores_entry")),
            "final_consensus_persona_score": _to_float(row.get("final_consensus_persona_score"), 0.0),
            "buy_mode": str(row.get("buy_mode") or "balanced"),
            "buy_eligibility": str(row.get("buy_eligibility") or ""),
            "buy_quality_tier": str(row.get("buy_quality_tier") or ""),
            "buy_quality_score": _to_float(row.get("buy_quality_score"), 0.0),
            "entry_confidence": _to_float(row.get("entry_confidence"), 0.0),
            "setup_type": setup_type,
            "entry_reason": str(row.get("entry_reason") or ""),
            "signal_tags": _json_dump(signal_tags),
            "exit_timestamp": row.get("exit_timestamp"),
            "exit_price": _to_float(row.get("exit_price"), 0.0),
            "exit_reason": str(row.get("exit_reason") or ""),
            "holding_period": _to_float(row.get("holding_period"), 0.0),
            "return_percent": _to_float(row.get("return_percent"), _to_float(row.get("profit_loss_percent"), 0.0)),
            "profit_loss_percent": _to_float(row.get("profit_loss_percent"), _to_float(row.get("return_percent"), 0.0)),
            "friction_adjusted_return": _to_float(row.get("friction_adjusted_return"), _to_float(row.get("return_percent"), 0.0)),
            "valid_label": _to_int(row.get("valid_label"), 1),
            "invalid_reason": str(row.get("invalid_reason") or ""),
            "max_favorable_excursion": _to_float(row.get("max_favorable_excursion"), 0.0),
            "max_adverse_excursion": _to_float(row.get("max_adverse_excursion"), 0.0),
            "peak_unrealized_pnl_percent": _to_float(row.get("peak_unrealized_pnl_percent"), 0.0),
            "drawdown_after_peak_percent": _to_float(row.get("drawdown_after_peak_percent"), 0.0),
            "time_to_peak_seconds": _to_float(row.get("time_to_peak_seconds"), 0.0),
            "time_to_exit_seconds": _to_float(row.get("time_to_exit_seconds"), 0.0),
            "risk_context_json": _json_dump(row.get("risk_context_json")),
            "trade_origin": str(row.get("trade_origin") or "manual"),
            "created_at": str(row.get("created_at") or now_iso),
            "last_updated_at": now_iso,
        }
        columns = list(values.keys())
        placeholders = ",".join(["?"] * len(columns))
        updates = ",".join([f"{c}=excluded.{c}" for c in columns if c not in {"trade_id", "created_at"}])
        with self._connect() as conn:
            if values["trade_id"]:
                conn.execute(
                    f"""
                    INSERT INTO trade_journal ({",".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(trade_id) DO UPDATE SET {updates}
                    """,
                    [values[c] for c in columns],
                )
            else:
                conn.execute(
                    f"INSERT INTO trade_journal ({','.join(columns)}) VALUES ({placeholders})",
                    [values[c] for c in columns],
                )
            conn.commit()
        return {"ok": True, "trade_id": values["trade_id"] or "", "symbol": symbol, "saved": True}

    def _fetch_closed_rows(self, limit: int, trade_origin: str | None = None) -> list[dict[str, Any]]:
        n = max(1, min(5000, int(limit or 400)))
        params: list[Any] = []
        where = [
            "exit_timestamp IS NOT NULL",
            "return_percent IS NOT NULL",
        ]
        if trade_origin:
            where.append("trade_origin=?")
            params.append(str(trade_origin))
        query = f"""
            SELECT *
            FROM trade_journal
            WHERE {" AND ".join(where)}
            ORDER BY exit_timestamp DESC
            LIMIT ?
        """
        params.append(n)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r or {}) for r in rows]

    def _compute_feedback(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        sample_size = 0
        good_entries = 0
        bad_entries = 0
        early_exits = 0
        late_exits = 0
        missed_cases = 0
        missed_values: list[float] = []

        for row in rows:
            if not _is_valid_label(row):
                # Invalid labels are counted conservatively as bad entries.
                bad_entries += 1
            ret = _to_float(row.get("return_percent"), 0.0)
            sample_size += 1
            if ret > 0 and _is_valid_label(row):
                good_entries += 1
            else:
                bad_entries += 1

            reason = _normalize_key(row.get("exit_reason"), "")
            if any(k in reason for k in ("early", "premature", "quick", "fast_exit")):
                early_exits += 1
            if any(k in reason for k in ("late", "overhold", "held_too_long", "deterioration", "drag")):
                late_exits += 1

            mfe = _to_float(row.get("max_favorable_excursion"), 0.0)
            peak = _to_float(row.get("peak_unrealized_pnl_percent"), 0.0)
            cap = max(mfe, peak)
            if cap > (ret + 1.25):
                missed_cases += 1
                missed_values.append(max(0.0, cap - ret))

        avg_missed = round(sum(missed_values) / max(1, len(missed_values)), 4) if missed_values else 0.0
        return {
            "sample_size": int(sample_size),
            "good_entries": int(good_entries),
            "bad_entries": int(max(0, bad_entries)),
            "early_exits": int(early_exits),
            "late_exits": int(late_exits),
            "missed_profit_cases": int(missed_cases),
            "missed_profit_avg_percent": float(avg_missed),
            "avg_missed_profit_percent": float(avg_missed),
        }

    def compute_decision_feedback(self, limit: int = 400, trade_origin: str | None = None) -> dict[str, Any]:
        rows = self._fetch_closed_rows(limit=limit, trade_origin=trade_origin)
        out = self._compute_feedback(rows)
        out["trade_origin"] = str(trade_origin or "all")
        return out

    def compute_decision_feedback_segments(self, limit: int = 900, trade_origin: str | None = None) -> dict[str, Any]:
        rows = self._fetch_closed_rows(limit=limit, trade_origin=trade_origin)
        buckets: dict[str, dict[str, list[dict[str, Any]]]] = {
            "by_regime": {},
            "by_persona": {},
            "by_cap_bucket": {},
            "by_setup_type": {},
            "by_sector": {},
        }
        for row in rows:
            mappings = {
                "by_regime": _normalize_key(row.get("market_regime") or row.get("entry_regime")),
                "by_persona": _normalize_key(row.get("entry_persona_fit_summary")),
                "by_cap_bucket": _normalize_key(row.get("entry_market_cap_category")),
                "by_setup_type": _normalize_key(row.get("setup_type")),
                "by_sector": _normalize_key(row.get("entry_sector")),
            }
            for segment, key in mappings.items():
                buckets[segment].setdefault(key, []).append(row)

        out: dict[str, Any] = {}
        for segment, segment_map in buckets.items():
            packed: dict[str, Any] = {}
            for key, seg_rows in segment_map.items():
                packed[key] = self._compute_feedback(seg_rows)
            out[segment] = packed
        out["trade_origin"] = str(trade_origin or "all")
        return out

    def _cohort_stats(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "trade_count": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "median_return": 0.0,
                "winsorized_avg_return": 0.0,
            }
        rets = [_to_float(r.get("return_percent"), 0.0) for r in rows]
        wins = len([x for x in rets if x > 0])
        losses = len([x for x in rets if x <= 0])
        n = len(rets)
        return {
            "trade_count": int(n),
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": round((wins / float(max(1, n))) * 100.0, 2),
            "avg_return": round(sum(rets) / float(max(1, n)), 4),
            "median_return": round(_median(rets), 4),
            "winsorized_avg_return": round(_winsorized_avg(rets), 4),
        }

    def compute_paper_cohort_trends(
        self,
        cohort_size: int = 75,
        limit: int = 1200,
        trade_origin: str | None = None,
    ) -> dict[str, Any]:
        rows = self._fetch_closed_rows(limit=limit, trade_origin=trade_origin)
        csize = max(10, min(250, int(cohort_size or 75)))
        recent_rows = rows[:csize]
        prior_rows = rows[csize : (csize * 2)]
        recent = self._cohort_stats(recent_rows)
        prior = self._cohort_stats(prior_rows)
        delta = {
            "win_rate": round(_to_float(recent.get("win_rate")) - _to_float(prior.get("win_rate")), 2),
            "avg_return": round(_to_float(recent.get("avg_return")) - _to_float(prior.get("avg_return")), 4),
            "median_return": round(_to_float(recent.get("median_return")) - _to_float(prior.get("median_return")), 4),
            "winsorized_avg_return": round(
                _to_float(recent.get("winsorized_avg_return")) - _to_float(prior.get("winsorized_avg_return")),
                4,
            ),
        }
        trend = "mixed"
        if _to_float(delta.get("winsorized_avg_return")) > 0.15 and _to_float(delta.get("win_rate")) >= 2.0:
            trend = "improving"
        elif _to_float(delta.get("winsorized_avg_return")) < -0.15 and _to_float(delta.get("win_rate")) <= -2.0:
            trend = "worsening"
        return {
            "cohort_size": int(csize),
            "total_trades_considered": int(len(rows)),
            "recent": recent,
            "prior": prior,
            "delta": delta,
            "overall_trend": trend,
            "trade_origin": str(trade_origin or "all"),
        }

    def diagnostics(self) -> dict[str, Any]:
        decision_feedback = self.compute_decision_feedback(limit=600, trade_origin="paper_autopilot")
        if _to_int(decision_feedback.get("sample_size"), 0) <= 0:
            decision_feedback = self.compute_decision_feedback(limit=800, trade_origin=None)
        segments = self.compute_decision_feedback_segments(limit=1400, trade_origin="paper_autopilot")
        if not any(isinstance(v, dict) and v for k, v in segments.items() if k.startswith("by_")):
            segments = self.compute_decision_feedback_segments(limit=1800, trade_origin=None)
        cohort = self.compute_paper_cohort_trends(cohort_size=75, limit=1200, trade_origin="paper_autopilot")
        if _to_int((cohort.get("recent") or {}).get("trade_count"), 0) <= 0:
            cohort = self.compute_paper_cohort_trends(cohort_size=75, limit=1200, trade_origin=None)

        rows = self._fetch_closed_rows(limit=2400, trade_origin=None)
        combined = self._cohort_stats(rows)

        hard_rows = [r for r in rows if str(r.get("buy_eligibility") or "").upper() == "QUALIFIED"]
        soft_rows = [r for r in rows if str(r.get("buy_eligibility") or "").upper() != "QUALIFIED"]
        hard_perf = self._cohort_stats(hard_rows)
        soft_perf = self._cohort_stats(soft_rows)

        with self._connect() as conn:
            open_row = conn.execute(
                "SELECT COUNT(1) AS n FROM trade_journal WHERE exit_timestamp IS NULL OR exit_timestamp=''"
            ).fetchone()
            open_count = _to_int((dict(open_row or {})).get("n"), 0)

        closed_total = max(1, len(rows))
        def _pop_rate(field: str) -> float:
            present = len([r for r in rows if r.get(field) not in (None, "", "null")])
            return round((present / float(closed_total)) * 100.0, 2)

        trade_path_quality = {
            "closed_journal": {
                "closed_trade_count": int(len(rows)),
                "mfe_population_rate_percent": _pop_rate("max_favorable_excursion"),
                "mae_population_rate_percent": _pop_rate("max_adverse_excursion"),
                "peak_population_rate_percent": _pop_rate("peak_unrealized_pnl_percent"),
                "drawdown_population_rate_percent": _pop_rate("drawdown_after_peak_percent"),
                "time_to_peak_population_rate_percent": _pop_rate("time_to_peak_seconds"),
                "time_to_exit_population_rate_percent": _pop_rate("time_to_exit_seconds"),
            },
            "open_positions": {
                "open_trade_count": int(open_count),
            },
        }

        return {
            "db_path": self.db_path,
            "decision_feedback": decision_feedback,
            "decision_feedback_segments": segments,
            "paper_outcome_summary": {
                "combined": {
                    **combined,
                    "valid_closed": int(combined.get("trade_count", 0)),
                    "hard_buy_performance": hard_perf,
                    "soft_buy_performance": soft_perf,
                    "hard_vs_soft_delta_avg_return": round(
                        _to_float(hard_perf.get("avg_return")) - _to_float(soft_perf.get("avg_return")),
                        4,
                    ),
                    "hard_vs_soft_delta_winsorized_avg_return": round(
                        _to_float(hard_perf.get("winsorized_avg_return")) - _to_float(soft_perf.get("winsorized_avg_return")),
                        4,
                    ),
                }
            },
            "paper_cohort_trends": cohort,
            "trade_path_quality": trade_path_quality,
            "last_updated_utc": _utc_now_iso(),
        }
