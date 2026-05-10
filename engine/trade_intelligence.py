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


def _decision_bucket(row: dict[str, Any]) -> str:
    eligibility = str(row.get("buy_eligibility") or "").strip().lower()
    tier = str(row.get("buy_quality_tier") or "").strip().lower()
    merged = f"{eligibility} {tier}"
    if any(x in merged for x in ("block", "reject", "avoid", "non_trade")):
        return "blocked"
    if any(x in merged for x in ("watch", "monitor", "observe")):
        return "watchlist"
    if any(x in merged for x in ("qualified", "soft_buy", "released", "paper_ready", "strong_buy", "buy")):
        return "promoted"
    return "unclassified"


def _to_percent(value: Any) -> float:
    raw = _to_float(value, 0.0)
    if raw <= 1.0:
        raw *= 100.0
    return max(0.0, min(100.0, raw))


def _decision_process_score(row: dict[str, Any]) -> tuple[float, list[str]]:
    setup_type = str(row.get("setup_type") or "").strip().lower()
    buy_eligibility = str(row.get("buy_eligibility") or "").strip().lower()
    buy_quality_tier = str(row.get("buy_quality_tier") or "").strip().lower()

    predicted_prob = _to_percent(row.get("entry_predicted_probability"))
    confidence = _to_percent(row.get("entry_confidence"))
    persona_consensus = _to_percent(
        row.get("final_consensus_persona_score")
        if row.get("final_consensus_persona_score") not in (None, "")
        else row.get("entry_persona_grade")
    )
    quality_score = _to_percent(row.get("buy_quality_score"))
    label_valid = bool(_is_valid_label(row))

    setup_penalty = 0.0
    reasons: list[str] = []
    if setup_type in {"", "unknown", "fallback_unclear", "unclassified_setup"}:
        setup_penalty = 12.0
        reasons.append("setup_clarity_weak")
    if predicted_prob < 55.0:
        reasons.append("entry_confirmation_weak")
    if persona_consensus < 52.0:
        reasons.append("persona_consensus_weak")
    if quality_score < 52.0:
        reasons.append("quality_signal_weak")

    eligibility_bonus = 0.0
    if any(x in buy_eligibility for x in ("qualified", "soft_buy", "buy")):
        eligibility_bonus = 4.0
    elif any(x in buy_eligibility for x in ("watch", "monitor")):
        eligibility_bonus = -2.0
    elif any(x in buy_eligibility for x in ("block", "reject", "avoid")):
        eligibility_bonus = -8.0

    tier_bonus = 0.0
    if any(x in buy_quality_tier for x in ("elite", "strong")):
        tier_bonus = 5.0
    elif any(x in buy_quality_tier for x in ("weak", "low", "poor")):
        tier_bonus = -5.0

    label_penalty = 0.0 if label_valid else 8.0
    if not label_valid:
        reasons.append("label_confidence_weak")

    score = max(
        0.0,
        min(
            100.0,
            (predicted_prob * 0.30)
            + (persona_consensus * 0.23)
            + (quality_score * 0.27)
            + (confidence * 0.14)
            + 8.0
            + eligibility_bonus
            + tier_bonus
            - setup_penalty
            - label_penalty,
        ),
    )
    return round(score, 2), list(dict.fromkeys(reasons))


def _decision_quality_label(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    process_score, reasons = _decision_process_score(row)
    good_decision = bool(process_score >= 58.0)
    ret = _to_float(row.get("return_percent"), 0.0)
    good_outcome = bool(ret > 0.0)
    if good_decision and good_outcome:
        label = "good_decision_good_outcome"
    elif good_decision and (not good_outcome):
        label = "good_decision_bad_outcome"
    elif (not good_decision) and good_outcome:
        label = "bad_decision_good_outcome"
    else:
        label = "bad_decision_bad_outcome"
    return label, {
        "decision_process_score": float(process_score),
        "good_decision": bool(good_decision),
        "good_outcome": bool(good_outcome),
        "decision_quality_reasons": reasons,
    }


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
                    detected_setup_type TEXT,
                    setup_candidate_realness TEXT,
                    setup_detection_score REAL,
                    setup_detection_band TEXT,
                    setup_detection_confidence REAL,
                    setup_detection_evidence_label TEXT,
                    entry_reason TEXT,
                    signal_tags TEXT,
                    conviction_tier TEXT,
                    entry_quality_score REAL,
                    entry_quality_band TEXT,
                    entry_quality_candidate_class TEXT,
                    entry_quality_primary_driver TEXT,
                    entry_quality_primary_penalty TEXT,
                    entry_quality_evidence_label TEXT,
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
            # Backward-safe schema migration for older local DBs.
            try:
                cols = {
                    str(r[1] if isinstance(r, tuple) else r["name"]): True
                    for r in (conn.execute("PRAGMA table_info(trade_journal)").fetchall() or [])
                }
            except Exception:
                cols = {}
            needed = {
                "entry_persona_fit_summary": "TEXT",
                "created_at": "TEXT",
                "last_updated_at": "TEXT",
                "detected_setup_type": "TEXT",
                "setup_candidate_realness": "TEXT",
                "setup_detection_score": "REAL",
                "setup_detection_band": "TEXT",
                "setup_detection_confidence": "REAL",
                "setup_detection_evidence_label": "TEXT",
                "conviction_tier": "TEXT",
                "entry_quality_score": "REAL",
                "entry_quality_band": "TEXT",
                "entry_quality_candidate_class": "TEXT",
                "entry_quality_primary_driver": "TEXT",
                "entry_quality_primary_penalty": "TEXT",
                "entry_quality_evidence_label": "TEXT",
            }
            for col, ddl in needed.items():
                if col in cols:
                    continue
                try:
                    conn.execute(f"ALTER TABLE trade_journal ADD COLUMN {col} {ddl}")
                except Exception:
                    pass
            # Compatibility bridge for older historical rows.
            if "entry_persona_fit_summary" in needed:
                try:
                    conn.execute(
                        """
                        UPDATE trade_journal
                        SET entry_persona_fit_summary = COALESCE(NULLIF(entry_persona_fit_summary, ''), persona_fit_summary, entry_persona_best_fit, '')
                        WHERE COALESCE(entry_persona_fit_summary, '') = ''
                        """
                    )
                except Exception:
                    pass
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
            "detected_setup_type": str(
                row.get("detected_setup_type")
                or row.get("entry_detected_setup_type")
                or row.get("setup_type")
                or setup_type
                or "unknown"
            ),
            "setup_candidate_realness": str(
                row.get("setup_candidate_realness")
                or row.get("entry_setup_candidate_realness")
                or "unknown"
            ),
            "setup_detection_score": _to_float(
                row.get("setup_detection_score"),
                _to_float(row.get("entry_setup_detection_score"), 0.0),
            ),
            "setup_detection_band": str(
                row.get("setup_detection_band")
                or row.get("entry_setup_detection_band")
                or "unknown"
            ),
            "setup_detection_confidence": _to_float(
                row.get("setup_detection_confidence"),
                _to_float(row.get("entry_setup_detection_confidence"), 0.0),
            ),
            "setup_detection_evidence_label": str(
                row.get("setup_detection_evidence_label")
                or row.get("entry_setup_detection_evidence_label")
                or "unknown"
            ),
            "entry_reason": str(row.get("entry_reason") or ""),
            "signal_tags": _json_dump(signal_tags),
            "conviction_tier": str(row.get("conviction_tier") or row.get("entry_conviction_tier") or ""),
            "entry_quality_score": _to_float(
                row.get("entry_quality_score"),
                _to_float(row.get("entry_entry_quality_score"), 0.0),
            ),
            "entry_quality_band": str(
                row.get("entry_quality_band")
                or row.get("entry_entry_quality_band")
                or "unknown"
            ),
            "entry_quality_candidate_class": str(
                row.get("entry_quality_candidate_class")
                or row.get("entry_entry_quality_candidate_class")
                or "unknown"
            ),
            "entry_quality_primary_driver": str(
                row.get("entry_quality_primary_driver")
                or row.get("entry_entry_quality_primary_driver")
                or "unknown"
            ),
            "entry_quality_primary_penalty": str(
                row.get("entry_quality_primary_penalty")
                or row.get("entry_entry_quality_primary_penalty")
                or "unknown"
            ),
            "entry_quality_evidence_label": str(
                row.get("entry_quality_evidence_label")
                or row.get("entry_entry_quality_evidence_label")
                or "unknown"
            ),
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

    def _counterfactual_panel(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = {
            "promoted": [],
            "blocked": [],
            "watchlist": [],
            "unclassified": [],
        }
        for row in rows:
            buckets.setdefault(_decision_bucket(row), []).append(row)

        promoted_stats = self._cohort_stats(buckets.get("promoted") or [])
        blocked_stats = self._cohort_stats(buckets.get("blocked") or [])
        watchlist_stats = self._cohort_stats(buckets.get("watchlist") or [])
        unclassified_stats = self._cohort_stats(buckets.get("unclassified") or [])
        promoted_n = int(promoted_stats.get("trade_count", 0))
        blocked_n = int(blocked_stats.get("trade_count", 0))
        watchlist_n = int(watchlist_stats.get("trade_count", 0))
        confidence = min(
            100.0,
            ((promoted_n + blocked_n + watchlist_n) / 220.0) * 100.0,
        )
        return {
            "promoted": promoted_stats,
            "blocked": blocked_stats,
            "watchlist": watchlist_stats,
            "unclassified": unclassified_stats,
            "promoted_vs_blocked_gap": {
                "win_rate_gap": round(
                    _to_float(promoted_stats.get("win_rate"), 0.0) - _to_float(blocked_stats.get("win_rate"), 0.0),
                    2,
                ),
                "avg_return_gap": round(
                    _to_float(promoted_stats.get("avg_return"), 0.0) - _to_float(blocked_stats.get("avg_return"), 0.0),
                    4,
                ),
                "winsorized_avg_return_gap": round(
                    _to_float(promoted_stats.get("winsorized_avg_return"), 0.0)
                    - _to_float(blocked_stats.get("winsorized_avg_return"), 0.0),
                    4,
                ),
            },
            "evidence_confidence_percent": round(confidence, 2),
            "sample_sizes": {
                "promoted": promoted_n,
                "blocked": blocked_n,
                "watchlist": watchlist_n,
                "unclassified": int(unclassified_stats.get("trade_count", 0)),
            },
        }

    def _decision_quality_panel(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        counts = {
            "good_decision_good_outcome": 0,
            "good_decision_bad_outcome": 0,
            "bad_decision_good_outcome": 0,
            "bad_decision_bad_outcome": 0,
        }
        score_values: list[float] = []
        by_label_returns: dict[str, list[float]] = {k: [] for k in counts.keys()}
        weak_reasons: dict[str, int] = {}
        for row in rows:
            label, meta = _decision_quality_label(row)
            if label not in counts:
                continue
            counts[label] = int(counts.get(label, 0)) + 1
            score_values.append(_to_float(meta.get("decision_process_score"), 0.0))
            by_label_returns[label].append(_to_float(row.get("return_percent"), 0.0))
            if not bool(meta.get("good_decision", False)):
                for rsn in list(meta.get("decision_quality_reasons") or []):
                    key = str(rsn or "unknown").strip().lower() or "unknown"
                    weak_reasons[key] = int(weak_reasons.get(key, 0)) + 1

        n = max(1, sum(counts.values()))
        avg_score = round(sum(score_values) / max(1, len(score_values)), 2) if score_values else 0.0
        outcome_blindness = round((float(counts["bad_decision_good_outcome"]) / float(n)) * 100.0, 2)
        process_miss_rate = round((float(counts["good_decision_bad_outcome"]) / float(n)) * 100.0, 2)

        label_stats = {}
        for key, vals in by_label_returns.items():
            label_stats[key] = {
                "count": int(len(vals)),
                "avg_return": round(sum(vals) / max(1, len(vals)), 4) if vals else 0.0,
                "win_rate": round((len([x for x in vals if x > 0]) / max(1, len(vals))) * 100.0, 2) if vals else 0.0,
            }

        weak_reason_rows = [
            {"reason": k, "count": int(v)}
            for k, v in sorted(weak_reasons.items(), key=lambda kv: kv[1], reverse=True)
        ][:8]

        return {
            "enabled": True,
            "counts": counts,
            "rates_percent": {
                k: round((float(v) / float(n)) * 100.0, 2)
                for k, v in counts.items()
            },
            "average_decision_process_score": avg_score,
            "outcome_blindness_rate_percent": outcome_blindness,
            "process_miss_rate_percent": process_miss_rate,
            "label_performance": label_stats,
            "top_weak_decision_reasons": weak_reason_rows,
            "sample_size": int(sum(counts.values())),
            "evidence_confidence_percent": round(min(100.0, (float(sum(counts.values())) / 260.0) * 100.0), 2),
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
        counterfactual = self._counterfactual_panel(rows)
        decision_quality = self._decision_quality_panel(rows)

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
            "context_population": {
                "setup_type_population_rate_percent": _pop_rate("setup_type"),
                "regime_population_rate_percent": _pop_rate("market_regime"),
                "persona_population_rate_percent": _pop_rate("entry_persona_fit_summary"),
                "signal_tags_population_rate_percent": _pop_rate("signal_tags"),
                "buy_eligibility_population_rate_percent": _pop_rate("buy_eligibility"),
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
            "counterfactual_learning": counterfactual,
            "decision_quality_v1": decision_quality,
            "trade_path_quality": trade_path_quality,
            "last_updated_utc": _utc_now_iso(),
        }
