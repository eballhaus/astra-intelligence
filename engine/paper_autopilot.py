from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

try:
    from engine.position_tracker import PositionTracker
except Exception:  # pragma: no cover - keep runtime-compatible fallback
    PositionTracker = None  # type: ignore[assignment]


def _now_iso() -> str:
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


def _norm_asset(asset_type: Any) -> str:
    raw = str(asset_type or "stock").strip().lower()
    return "crypto" if raw == "crypto" else "stock"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        return "{}"


def _safe_json_load(raw: Any) -> dict[str, Any]:
    try:
        if isinstance(raw, str) and raw:
            out = json.loads(raw)
            if isinstance(out, dict):
                return out
    except Exception:
        pass
    return {}


class PaperAutopilotEngine:
    def __init__(self, db_path: str = "state/ai_trading_memory.db", *args, **kwargs):
        self.db_path = str(db_path or "state/ai_trading_memory.db")
        self.state_path = str(kwargs.get("state_path") or "state/paper_autopilot_state.json")
        self.interval_seconds = max(15, _to_int(kwargs.get("interval_seconds"), 45))
        self.max_stocks = max(1, _to_int(kwargs.get("max_stocks"), 6))
        self.max_crypto = max(0, _to_int(kwargs.get("max_crypto"), 2))
        self.max_new_positions_per_cycle = max(1, _to_int(kwargs.get("max_new_positions_per_cycle"), 2))
        self.max_closes_per_cycle = max(1, _to_int(kwargs.get("max_closes_per_cycle"), 2))
        self.min_hold_seconds_intraday = max(30, _to_int(kwargs.get("min_hold_seconds_intraday"), 300))
        self.min_hold_seconds_swing = max(120, _to_int(kwargs.get("min_hold_seconds_swing"), 1800))
        self.cooldown_after_close_seconds = max(0, _to_int(kwargs.get("cooldown_after_close_seconds"), 300))
        self.paper_mode = str(kwargs.get("paper_mode") or "intraday").strip().lower() or "intraday"
        self._enabled = bool(kwargs.get("enabled", False))

        self.get_top_buys_fn = kwargs.get("get_top_buys_fn") if callable(kwargs.get("get_top_buys_fn")) else None
        self.get_latest_row_fn = kwargs.get("get_latest_row_fn") if callable(kwargs.get("get_latest_row_fn")) else None
        self.trade_intel = kwargs.get("trade_intel")
        self.exit_engine = kwargs.get("exit_engine")
        self.exit_learning = kwargs.get("exit_learning")
        self.live_performance_fn = kwargs.get("live_performance_fn") if callable(kwargs.get("live_performance_fn")) else None
        self.freshness_manager = kwargs.get("freshness_manager")
        self.max_open_positions_total = max(2, _to_int(kwargs.get("max_open_positions_total"), 10))

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cycle_lock = threading.Lock()
        self._runtime_state: dict[str, Any] = {
            "last_cycle_utc": "",
            "last_cycle_summary": {},
            "last_error": "",
            "last_close_by_symbol": {},
        }

        self._position_tracker = None
        if PositionTracker is not None:
            try:
                self._position_tracker = PositionTracker(db_path=self.db_path)
            except Exception:
                self._position_tracker = None

        self._ensure_schema()
        self._load_state_file()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 1.0,
                    entry_price REAL NOT NULL DEFAULT 0.0,
                    exit_price REAL,
                    return_percent REAL,
                    friction_adjusted_return REAL,
                    entry_timestamp TEXT NOT NULL,
                    exit_timestamp TEXT,
                    hold_seconds REAL,
                    source_bucket TEXT,
                    lifecycle_notes TEXT,
                    row_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cols = {
                str(r[1] if isinstance(r, tuple) else r["name"]): True
                for r in (conn.execute("PRAGMA table_info(paper_positions)").fetchall() or [])
            }
            # Backward-safe migration for legacy paper_positions layouts.
            needed = {
                "status": "TEXT NOT NULL DEFAULT 'OPEN'",
                "quantity": "REAL NOT NULL DEFAULT 1.0",
                "entry_price": "REAL NOT NULL DEFAULT 0.0",
                "exit_price": "REAL",
                "return_percent": "REAL",
                "friction_adjusted_return": "REAL",
                "entry_timestamp": "TEXT",
                "exit_timestamp": "TEXT",
                "hold_seconds": "REAL",
                "source_bucket": "TEXT",
                "lifecycle_notes": "TEXT",
                "row_json": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            }
            for col, ddl in needed.items():
                if col in cols:
                    continue
                try:
                    conn.execute(f"ALTER TABLE paper_positions ADD COLUMN {col} {ddl}")
                except Exception:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_status ON paper_positions(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_symbol ON paper_positions(symbol)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_positions_asset ON paper_positions(asset_type)")
            conn.commit()

    def _load_state_file(self):
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                if "autopilot_enabled" in payload:
                    self._enabled = bool(payload.get("autopilot_enabled"))
                if isinstance(payload.get("last_close_by_symbol"), dict):
                    self._runtime_state["last_close_by_symbol"] = dict(payload.get("last_close_by_symbol") or {})
        except Exception:
            return

    def _save_state_file(self):
        payload = {
            "autopilot_enabled": bool(self._enabled),
            "paper_mode": self.paper_mode,
            "last_cycle_utc": self._runtime_state.get("last_cycle_utc") or "",
            "last_close_by_symbol": dict(self._runtime_state.get("last_close_by_symbol") or {}),
        }
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), ensure_ascii=True)
        except Exception:
            pass

    def _min_hold_seconds(self) -> int:
        return self.min_hold_seconds_swing if self.paper_mode == "swing" else self.min_hold_seconds_intraday

    def _fetch_open_positions(self, asset_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = ["OPEN"]
        where = ["status=?"]
        if asset_type:
            where.append("asset_type=?")
            params.append(_norm_asset(asset_type))
        query = "SELECT * FROM paper_positions WHERE " + " AND ".join(where) + " ORDER BY entry_timestamp ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r or {}) for r in rows]

    def _count_open_positions(self) -> dict[str, int]:
        rows = self._fetch_open_positions()
        stock_n = 0
        crypto_n = 0
        for row in rows:
            asset = _norm_asset((row or {}).get("asset_type") or "stock")
            if asset == "crypto":
                crypto_n += 1
            else:
                stock_n += 1
        return {"stock": int(stock_n), "crypto": int(crypto_n)}

    def _cooldown_active(self, symbol: str) -> bool:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return False
        last_map = dict(self._runtime_state.get("last_close_by_symbol") or {})
        ts = _to_float(last_map.get(sym), 0.0)
        if ts <= 0:
            return False
        return (time.time() - ts) < float(self.cooldown_after_close_seconds)

    def _collect_candidate_rows(self) -> list[dict[str, Any]]:
        if not self.get_top_buys_fn:
            return []
        try:
            payload = self.get_top_buys_fn() or {}
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []

        def _rows_from(path: list[str]) -> list[dict[str, Any]]:
            cur: Any = payload
            for k in path:
                if not isinstance(cur, dict):
                    return []
                cur = cur.get(k)
            return [dict(x) for x in (cur or []) if isinstance(x, dict)] if isinstance(cur, list) else []

        rows: list[dict[str, Any]] = []
        rows.extend(_rows_from(["stocks", "final"]))
        rows.extend(_rows_from(["top_action_views", "canonical_decision_views", "stocks_buy_candidates"]))
        rows.extend(_rows_from(["stocks", "qualified"]))

        dedup: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            sym = str(row.get("symbol") or "").upper().strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            row.setdefault("symbol", sym)
            row.setdefault("asset_type", "stock")
            dedup.append(row)
        return dedup

    def _entry_commitment_gate_v1(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        eligibility = str(row.get("buy_eligibility") or "").strip().lower()
        tier = str(row.get("buy_quality_tier") or "").strip().lower()
        uncertainty_tier = str(row.get("uncertainty_tier") or "").strip().lower()
        uncertainty_score = _to_float(row.get("uncertainty_score"), 50.0)
        discipline_action = str(row.get("core_decision_discipline_action") or "").strip().lower()
        discipline_tier = str(row.get("core_decision_discipline_tier") or "").strip().lower()
        deploy = str(row.get("hero_deployment_status") or row.get("canonical_final_state") or "").strip().lower()
        quality = _to_float(row.get("buy_quality_score"), _to_float(row.get("trade_quality_score"), 0.0))
        confidence = _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0))
        confidence = confidence if confidence > 1.0 else confidence * 100.0
        follow = str(row.get("follow_through_state") or "").strip().lower()
        entry_edge = _to_float(row.get("entry_edge_score"), 0.0)
        consensus = _to_float(row.get("consensus_strength"), 0.0)
        disagreement = _to_float(row.get("persona_disagreement_index"), 50.0)

        if any(x in uncertainty_tier for x in ("extreme",)):
            return False, "uncertainty_extreme", {"commitment_score": 0.0}
        if any(x in eligibility for x in ("blocked", "reject", "avoid")):
            return False, "eligibility_blocked", {"commitment_score": 0.0}
        if any(x in deploy for x in ("blocked", "rejected")):
            return False, "deployment_blocked", {"commitment_score": 0.0}
        if discipline_action in {"reject", "blocked"}:
            return False, "discipline_reject", {"commitment_score": 0.0}
        if discipline_tier in {"reject"}:
            return False, "discipline_tier_reject", {"commitment_score": 0.0}
        if uncertainty_tier == "high_uncertainty":
            return False, "uncertainty_high", {"commitment_score": 0.0}
        if uncertainty_score >= 74.0:
            return False, "uncertainty_score_high", {"commitment_score": 0.0}

        if quality < 48.0 and confidence < 52.0:
            return False, "quality_confidence_too_low", {"commitment_score": 0.0}

        positive_signals = 0
        if any(x in eligibility for x in ("qualified", "buy", "paper_ready", "watchlist")):
            positive_signals += 1
        if any(x in tier for x in ("elite", "strong", "moderate", "actionable", "qualified")):
            positive_signals += 1
        if quality >= 55.0:
            positive_signals += 1
        if confidence >= 56.0:
            positive_signals += 1

        if positive_signals < 2:
            return False, "insufficient_positive_signals", {"commitment_score": 0.0}

        if any(x in uncertainty_tier for x in ("high",)) and quality < 64.0:
            return False, "high_uncertainty_not_high_quality", {"commitment_score": 0.0}

        commitment_score = (
            (quality * 0.34)
            + (confidence * 0.26)
            + (consensus * 0.12)
            + (max(0.0, 50.0 + (entry_edge * 35.0)) * 0.08)
            + (max(0.0, 100.0 - disagreement) * 0.12)
            + (max(0.0, 100.0 - uncertainty_score) * 0.08)
        )
        if follow in {"strong_follow_through", "healthy_continuation"}:
            commitment_score += 4.0
        elif follow in {"weak_follow_through_risk", "deteriorating"}:
            commitment_score -= 5.0
        if discipline_action in {"release_candidate", "paper_ready", "hold"}:
            commitment_score += 3.0
        if "watchlist" in eligibility:
            commitment_score -= 2.0
        commitment_score = max(0.0, min(100.0, commitment_score))

        if commitment_score < 58.0:
            return False, "entry_commitment_below_threshold", {"commitment_score": round(commitment_score, 2)}
        if commitment_score < 64.0 and "watchlist" in eligibility:
            return False, "watchlist_commitment_not_strong_enough", {"commitment_score": round(commitment_score, 2)}

        return True, "eligible", {
            "commitment_score": round(commitment_score, 2),
            "confidence_at_entry": round(confidence, 2),
            "uncertainty_tier": uncertainty_tier or "unknown",
            "uncertainty_score": round(uncertainty_score, 2),
        }

    def _is_candidate_paper_eligible(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        return self._entry_commitment_gate_v1(row)

    def _build_entry_context_v1(
        self,
        row: dict[str, Any],
        entry_price: float,
        source_bucket: str,
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = dict(row or {})
        meta = dict(gate_meta or {})
        return {
            "entry_reason": "paper_autopilot_entry",
            "entry_price": round(_to_float(entry_price, 0.0), 6),
            "entry_quality": str(r.get("buy_quality_tier") or ""),
            "entry_source_bucket": str(source_bucket or "paper_candidate"),
            "entry_setup_type": str(r.get("setup_type") or "unknown"),
            "entry_regime_context": str(r.get("regime_context") or r.get("market_regime") or ""),
            "entry_persona_best_fit": str(r.get("persona_best_fit") or ""),
            "entry_confidence": round(
                _to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0))
                * (100.0 if _to_float(r.get("confidence"), 0.0) <= 1.0 else 1.0),
                2,
            ),
            "entry_predicted_probability": round(_to_float(r.get("predicted_win_probability"), 0.0), 6),
            "entry_uncertainty_tier": str(r.get("uncertainty_tier") or ""),
            "entry_uncertainty_score": round(_to_float(r.get("uncertainty_score"), 50.0), 2),
            "entry_decision_discipline_tier": str(r.get("core_decision_discipline_tier") or ""),
            "entry_decision_discipline_action": str(r.get("core_decision_discipline_action") or ""),
            "entry_buy_eligibility": str(r.get("buy_eligibility") or ""),
            "entry_buy_quality_score": round(_to_float(r.get("buy_quality_score"), _to_float(r.get("trade_quality_score"), 0.0)), 2),
            "entry_entry_edge_score": round(_to_float(r.get("entry_edge_score"), 0.0), 4),
            "entry_follow_through_state": str(r.get("follow_through_state") or ""),
            "entry_commitment_score": round(_to_float(meta.get("commitment_score"), 0.0), 2),
            "entry_signal_tags": r.get("entry_signal_tags") or r.get("signal_tags") or [],
            "entry_rationale": str(r.get("why_this_is_a_buy") or r.get("plain_decision_summary") or ""),
            "lifecycle_stage": "entered",
            "review_state": "new_entry",
            "continuation_flag": False,
            "deterioration_flag": False,
            "hold_posture": "observe",
        }

    def _open_position_from_row(
        self,
        row: dict[str, Any],
        source_bucket: str = "paper_candidate",
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        symbol = str(row.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(row.get("asset_type") or "stock")
        if not symbol:
            return {"ok": False, "error": "symbol_required"}

        quote = {}
        if callable(self.get_latest_row_fn):
            try:
                quote = dict(self.get_latest_row_fn(symbol, asset_type) or {})
            except Exception:
                quote = {}
        entry_price = _to_float(quote.get("price"), _to_float(row.get("price"), 0.0))
        if entry_price <= 0.0:
            return {"ok": False, "error": "no_valid_entry_price", "symbol": symbol}

        now_iso = _now_iso()
        pid = str(uuid.uuid4())
        entry_row = dict(row)
        entry_row.setdefault("symbol", symbol)
        entry_row.setdefault("asset_type", asset_type)
        entry_row.setdefault("entry_timestamp", now_iso)
        entry_context = self._build_entry_context_v1(row, entry_price, source_bucket, gate_meta=gate_meta)
        entry_context["position_id"] = pid

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO paper_positions(
                    position_id, symbol, asset_type, status, quantity,
                    entry_price, exit_price, return_percent, friction_adjusted_return,
                    entry_timestamp, exit_timestamp, hold_seconds,
                    source_bucket, lifecycle_notes, row_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'OPEN', ?, ?, NULL, NULL, NULL, ?, NULL, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    pid,
                    symbol,
                    asset_type,
                    1.0,
                    entry_price,
                    now_iso,
                    source_bucket,
                    _safe_json(entry_context),
                    _safe_json(entry_row),
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()

        if self._position_tracker is not None:
            try:
                self._position_tracker.open_position(
                    symbol=symbol,
                    asset_type=asset_type,
                    entry_price=entry_price,
                    quantity=1.0,
                    notes="paper_autopilot",
                    snapshot_fields={
                        "source_bucket": source_bucket,
                        "buy_eligibility": row.get("buy_eligibility"),
                        "buy_quality_tier": row.get("buy_quality_tier"),
                        "entry_commitment_score": entry_context.get("entry_commitment_score"),
                        "entry_uncertainty_tier": entry_context.get("entry_uncertainty_tier"),
                        "entry_decision_discipline_tier": entry_context.get("entry_decision_discipline_tier"),
                    },
                    mode=self.paper_mode,
                )
            except Exception:
                pass

        return {"ok": True, "position_id": pid, "symbol": symbol, "entry_price": entry_price, "asset_type": asset_type}

    def _close_position(self, open_row: dict[str, Any], latest_row: dict[str, Any], exit_reason: str) -> dict[str, Any]:
        pid = str(open_row.get("position_id") or "").strip()
        symbol = str(open_row.get("symbol") or "").upper().strip()
        asset_type = _norm_asset(open_row.get("asset_type") or "stock")
        if not pid or not symbol:
            return {"ok": False, "error": "position_row_invalid"}

        entry_price = _to_float(open_row.get("entry_price"), 0.0)
        now_iso = _now_iso()
        exit_price = _to_float(latest_row.get("price"), 0.0)
        if exit_price <= 0.0:
            exit_price = _to_float(open_row.get("entry_price"), 0.0)
        if entry_price <= 0.0:
            return {"ok": False, "error": "invalid_entry_price"}

        notes = _safe_json_load(open_row.get("lifecycle_notes"))
        entry_payload = _safe_json_load(open_row.get("row_json"))

        ret = ((exit_price - entry_price) / entry_price) * 100.0
        friction_ret = ret - 0.04

        entry_ts = str(open_row.get("entry_timestamp") or "")
        hold_seconds = 0.0
        try:
            hold_seconds = max(
                0.0,
                datetime.fromisoformat(now_iso.replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).timestamp(),
            )
        except Exception:
            hold_seconds = 0.0

        lifecycle_stage = "completed_winner" if ret > 0 else "completed_loser"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET status='CLOSED', exit_price=?, return_percent=?, friction_adjusted_return=?,
                    exit_timestamp=?, hold_seconds=?, lifecycle_notes=?, updated_at=?
                WHERE position_id=?
                """,
                (
                    exit_price,
                    ret,
                    friction_ret,
                    now_iso,
                    hold_seconds,
                    _safe_json(
                        {
                            "exit_reason": exit_reason,
                            "quote_quality": latest_row.get("quote_quality"),
                            "provider_used": latest_row.get("provider_used") or latest_row.get("source"),
                            "lifecycle_stage": lifecycle_stage,
                            "review_state": "closed",
                            "final_return_percent": round(ret, 4),
                            "continuation_flag": bool(_to_float(notes.get("peak_unrealized_pnl_percent"), max(ret, 0.0)) >= 1.0 and ret > 0),
                            "deterioration_flag": bool(_to_float(notes.get("drawdown_from_peak_percent"), 0.0) >= 1.6),
                        }
                    ),
                    now_iso,
                    pid,
                ),
            )
            conn.commit()

        if self._position_tracker is not None:
            try:
                self._position_tracker.close_position(identifier=symbol, exit_price=exit_price, exit_timestamp=now_iso, exit_reason_manual=exit_reason)
            except Exception:
                pass

        if self.trade_intel is not None and hasattr(self.trade_intel, "record_trade"):
            try:
                self.trade_intel.record_trade(
                    {
                        "trade_id": pid,
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "mode": self.paper_mode,
                        "entry_timestamp": entry_ts,
                        "entry_price": entry_price,
                        "entry_predicted_probability": _to_float(
                            entry_payload.get("predicted_win_probability"),
                            _to_float(entry_payload.get("entry_predicted_probability"), 0.0),
                        ),
                        "entry_persona_grade": _to_float(entry_payload.get("persona_weighted_grade"), 0.0),
                        "entry_regime": entry_payload.get("regime_context") or entry_payload.get("market_regime") or "",
                        "market_regime": entry_payload.get("regime_context") or entry_payload.get("market_regime") or "",
                        "entry_persona_fit_summary": entry_payload.get("persona_best_fit") or "",
                        "entry_market_cap_category": entry_payload.get("market_cap_category") or "",
                        "entry_sector": entry_payload.get("sector") or "",
                        "entry_signal_tags": entry_payload.get("signal_tags") or [],
                        "persona_scores_entry": entry_payload.get("persona_grades") or {},
                        "final_consensus_persona_score": _to_float(entry_payload.get("consensus_strength"), 0.0),
                        "buy_mode": entry_payload.get("buy_mode") or "balanced",
                        "buy_eligibility": entry_payload.get("buy_eligibility") or "",
                        "buy_quality_tier": entry_payload.get("buy_quality_tier") or "",
                        "buy_quality_score": _to_float(entry_payload.get("buy_quality_score"), _to_float(entry_payload.get("trade_quality_score"), 0.0)),
                        "entry_confidence": _to_float(entry_payload.get("confidence"), _to_float(entry_payload.get("predicted_win_probability"), 0.0)),
                        "setup_type": entry_payload.get("setup_type") or "unknown",
                        "detected_setup_type": entry_payload.get("detected_setup_type") or entry_payload.get("setup_type") or "unknown",
                        "setup_candidate_realness": entry_payload.get("setup_candidate_realness") or "unknown",
                        "setup_detection_score": _to_float(entry_payload.get("setup_detection_score"), 0.0),
                        "setup_detection_band": entry_payload.get("setup_detection_band") or "unknown",
                        "setup_detection_confidence": _to_float(entry_payload.get("setup_detection_confidence"), 0.0),
                        "setup_detection_evidence_label": entry_payload.get("setup_detection_evidence_label") or "unknown",
                        "conviction_tier": entry_payload.get("conviction_tier") or "",
                        "entry_quality_score": _to_float(entry_payload.get("entry_quality_score"), 0.0),
                        "entry_quality_band": entry_payload.get("entry_quality_band") or "unknown",
                        "entry_quality_candidate_class": entry_payload.get("entry_quality_candidate_class") or "unknown",
                        "entry_quality_primary_driver": entry_payload.get("entry_quality_primary_driver") or "unknown",
                        "entry_quality_primary_penalty": entry_payload.get("entry_quality_primary_penalty") or "unknown",
                        "entry_quality_evidence_label": entry_payload.get("entry_quality_evidence_label") or "unknown",
                        "entry_reason": "paper_autopilot_entry",
                        "signal_tags": entry_payload.get("signal_tags") or [],
                        "exit_timestamp": now_iso,
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "holding_period": hold_seconds,
                        "return_percent": ret,
                        "profit_loss_percent": ret,
                        "friction_adjusted_return": friction_ret,
                        "valid_label": 1,
                        "max_favorable_excursion": _to_float(notes.get("max_favorable_excursion"), max(ret, 0.0)),
                        "max_adverse_excursion": _to_float(notes.get("max_adverse_excursion"), min(ret, 0.0)),
                        "peak_unrealized_pnl_percent": _to_float(notes.get("peak_unrealized_pnl_percent"), max(ret, 0.0)),
                        "drawdown_after_peak_percent": _to_float(notes.get("drawdown_from_peak_percent"), 0.0),
                        "time_to_exit_seconds": hold_seconds,
                        "risk_context_json": {
                            "uncertainty_tier": entry_payload.get("uncertainty_tier"),
                            "uncertainty_score": _to_float(entry_payload.get("uncertainty_score"), 0.0),
                            "core_decision_discipline_tier": entry_payload.get("core_decision_discipline_tier"),
                            "core_decision_discipline_action": entry_payload.get("core_decision_discipline_action"),
                            "entry_commitment_score": _to_float(notes.get("entry_commitment_score"), _to_float(entry_payload.get("entry_commitment_score"), 0.0)),
                            "hold_posture": str(notes.get("hold_posture") or ""),
                            "review_state": str(notes.get("review_state") or ""),
                            "continuation_flag": bool(notes.get("continuation_flag", False)),
                            "deterioration_flag": bool(notes.get("deterioration_flag", False)),
                            "exit_decision_reason": str(exit_reason or ""),
                        },
                        "trade_origin": "paper_autopilot",
                    }
                )
            except Exception:
                pass

        close_map = dict(self._runtime_state.get("last_close_by_symbol") or {})
        close_map[symbol] = time.time()
        self._runtime_state["last_close_by_symbol"] = close_map

        return {
            "ok": True,
            "position_id": pid,
            "symbol": symbol,
            "return_percent": round(ret, 4),
            "exit_reason": exit_reason,
            "hold_seconds": round(hold_seconds, 2),
        }

    def _evaluate_exit(self, open_row: dict[str, Any], latest_row: dict[str, Any]) -> tuple[bool, str]:
        entry = _to_float(open_row.get("entry_price"), 0.0)
        current = _to_float(latest_row.get("price"), 0.0)
        if entry <= 0.0 or current <= 0.0:
            return False, "no_valid_quote"

        ret = ((current - entry) / entry) * 100.0
        notes = _safe_json_load(open_row.get("lifecycle_notes"))
        peak = max(_to_float(notes.get("peak_unrealized_pnl_percent"), ret), ret)
        drawdown = max(0.0, peak - ret)
        hold_seconds = max(0.0, _to_float(open_row.get("hold_seconds"), 0.0))
        hold_minutes = hold_seconds / 60.0

        if ret <= -2.4:
            return True, "stop_loss_breach"
        if peak >= 2.2 and drawdown >= 1.7:
            return True, "drawdown_from_peak"
        if ret >= 4.4:
            return True, "take_profit_lock"
        if hold_minutes >= 180.0 and ret <= -0.9:
            return True, "time_stop_underperforming"
        if hold_minutes >= 420.0 and ret < 0.0:
            return True, "max_hold_window_negative"

        if self.exit_engine is not None and hasattr(self.exit_engine, "evaluate_open_trades"):
            try:
                panel = self.exit_engine.evaluate_open_trades([{"symbol": open_row.get("symbol"), "return_percent": ret}], live_perf={})
                alerts = list((panel or {}).get("alerts") or [])
                if alerts:
                    action = str((alerts[0] or {}).get("recommended_action") or "").strip().upper()
                    if action in {"EXIT", "SELL", "TRIM"}:
                        return True, "exit_engine_signal"
            except Exception:
                pass
        if self.exit_learning is not None and hasattr(self.exit_learning, "expected_risk_if_hold"):
            try:
                risk = dict(
                    self.exit_learning.expected_risk_if_hold(
                        probability_drop_percent=max(0.0, _to_float(latest_row.get("probability_drop_percent"), 0.0)),
                        disagreement_increase=max(0.0, _to_float(latest_row.get("disagreement_increase"), 0.0)),
                        regime_shift=bool(latest_row.get("regime_shift", False)),
                    )
                    or {}
                )
                risk_if_hold = _to_float(risk.get("expected_risk_if_hold"), 0.0)
                if risk_if_hold >= 0.74 and ret <= 1.0:
                    return True, "exit_learning_high_risk_if_hold"
                if risk_if_hold >= 0.64 and drawdown >= 1.4:
                    return True, "exit_learning_deterioration_risk"
            except Exception:
                pass

        return False, "hold"

    def _update_open_row_snapshot(self, open_row: dict[str, Any], latest_row: dict[str, Any]):
        pid = str(open_row.get("position_id") or "").strip()
        if not pid:
            return
        entry = _to_float(open_row.get("entry_price"), 0.0)
        current = _to_float(latest_row.get("price"), 0.0)
        if entry <= 0.0 or current <= 0.0:
            return

        ret = ((current - entry) / entry) * 100.0
        peak = max(_to_float(open_row.get("peak_unrealized_pnl_percent"), ret), ret)
        drawdown = max(0.0, peak - ret)
        mae = min(_to_float(open_row.get("max_adverse_excursion"), ret), ret)
        mfe = max(_to_float(open_row.get("max_favorable_excursion"), ret), ret)
        now_iso = _now_iso()
        hold_seconds = 0.0
        try:
            hold_seconds = max(
                0.0,
                datetime.fromisoformat(now_iso.replace("Z", "+00:00")).timestamp()
                - datetime.fromisoformat(str(open_row.get("entry_timestamp") or "").replace("Z", "+00:00")).timestamp(),
            )
        except Exception:
            hold_seconds = 0.0
        continuation_flag = bool(ret > 0.0 and peak >= 1.2 and drawdown <= 1.4)
        deterioration_flag = bool(drawdown >= 1.6 or ret <= -1.2)
        hold_posture = "hold"
        if deterioration_flag:
            hold_posture = "tighten_or_exit"
        elif continuation_flag and ret >= 1.0:
            hold_posture = "hold_winner"
        review_state = "monitoring"
        if deterioration_flag:
            review_state = "deteriorating"
        elif continuation_flag:
            review_state = "continuation"

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE paper_positions
                SET lifecycle_notes=?, updated_at=?
                WHERE position_id=?
                """,
                (
                    _safe_json(
                        {
                            "current_price": current,
                            "current_return_percent": ret,
                            "peak_unrealized_pnl_percent": peak,
                            "drawdown_from_peak_percent": drawdown,
                            "max_favorable_excursion": mfe,
                            "max_adverse_excursion": mae,
                            "quote_quality": latest_row.get("quote_quality"),
                            "provider_used": latest_row.get("provider_used") or latest_row.get("source"),
                            "hold_seconds": round(hold_seconds, 2),
                            "lifecycle_stage": "monitoring",
                            "review_state": review_state,
                            "continuation_flag": continuation_flag,
                            "deterioration_flag": deterioration_flag,
                            "hold_posture": hold_posture,
                        }
                    ),
                    now_iso,
                    pid,
                ),
            )
            conn.commit()
        if self._position_tracker is not None:
            try:
                self._position_tracker.update_position_snapshot(
                    identifier=str(open_row.get("position_id") or open_row.get("symbol") or ""),
                    current_price=current,
                    unrealized_return_percent=round(ret, 4),
                    peak_unrealized_pnl_percent=round(peak, 4),
                    drawdown_from_peak_percent=round(drawdown, 4),
                    lifecycle_stage="monitoring",
                    review_state=review_state,
                    hold_posture=hold_posture,
                    continuation_flag=continuation_flag,
                    deterioration_flag=deterioration_flag,
                )
            except Exception:
                pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return {"ok": True, "started": False, "already_running": True}
        self._stop_event.clear()

        def _loop():
            while not self._stop_event.is_set():
                try:
                    self.run_cycle()
                except Exception as e:
                    self._runtime_state["last_error"] = str(e)[:240]
                self._stop_event.wait(max(5, int(self.interval_seconds)))

        self._thread = threading.Thread(target=_loop, daemon=True, name="astra-paper-autopilot")
        self._thread.start()
        return {"ok": True, "started": True}

    def enabled(self):
        return bool(self._enabled)

    def toggle(self, enabled: bool):
        self._enabled = bool(enabled)
        self._save_state_file()
        return {"ok": True, "autopilot_enabled": self._enabled}

    def enable(self):
        return self.toggle(True)

    def disable(self):
        return self.toggle(False)

    def refresh_enabled_from_state(self):
        self._load_state_file()
        return {"ok": True, "autopilot_enabled": self._enabled}

    def status(self):
        counts = self._count_open_positions()
        total_closed = 0
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(1) AS n FROM paper_positions WHERE status='CLOSED'").fetchone()
                total_closed = _to_int((dict(row or {})).get("n"), 0)
        except Exception:
            total_closed = 0

        return {
            "ok": True,
            "autopilot_enabled": self._enabled,
            "paper_mode": self.paper_mode,
            "open_positions_count": int(counts.get("stock", 0) + counts.get("crypto", 0)),
            "open_positions_stock": int(counts.get("stock", 0)),
            "open_positions_crypto": int(counts.get("crypto", 0)),
            "total_closed_trades": int(total_closed),
            "last_cycle_utc": str(self._runtime_state.get("last_cycle_utc") or ""),
            "last_cycle_summary": dict(self._runtime_state.get("last_cycle_summary") or {}),
            "last_error": str(self._runtime_state.get("last_error") or ""),
            "last_updated_utc": _now_iso(),
        }

    def control_status(self):
        return {
            "autopilot_enabled": self._enabled,
            "paper_mode": self.paper_mode,
            "control_state": "enabled" if self._enabled else "disabled",
            "interval_seconds": int(self.interval_seconds),
            "max_new_positions_per_cycle": int(self.max_new_positions_per_cycle),
            "max_closes_per_cycle": int(self.max_closes_per_cycle),
        }

    def run_cycle(self):
        if not self._enabled:
            out = {
                "ok": True,
                "autopilot_enabled": False,
                "orders_submitted": 0,
                "positions_closed": 0,
                "cycle_reason": "disabled",
            }
            self._runtime_state["last_cycle_utc"] = _now_iso()
            self._runtime_state["last_cycle_summary"] = out
            return out

        with self._cycle_lock:
            opened = 0
            closed = 0
            skipped = 0
            open_syms = {str(r.get("symbol") or "").upper().strip() for r in self._fetch_open_positions()}

            open_rows = self._fetch_open_positions()
            min_hold = self._min_hold_seconds()
            for row in open_rows:
                if closed >= self.max_closes_per_cycle:
                    break
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                latest = {}
                if callable(self.get_latest_row_fn):
                    try:
                        latest = dict(self.get_latest_row_fn(symbol, asset) or {})
                    except Exception:
                        latest = {}
                if not latest:
                    skipped += 1
                    continue
                self._update_open_row_snapshot(row, latest)

                entry_ts = str(row.get("entry_timestamp") or "")
                hold_seconds = 0.0
                try:
                    hold_seconds = max(
                        0.0,
                        datetime.fromisoformat(_now_iso().replace("Z", "+00:00")).timestamp()
                        - datetime.fromisoformat(entry_ts.replace("Z", "+00:00")).timestamp(),
                    )
                except Exception:
                    hold_seconds = 0.0

                should_close, reason = self._evaluate_exit(row, latest)
                if should_close and hold_seconds >= float(min_hold):
                    result = self._close_position(row, latest, reason)
                    if result.get("ok"):
                        closed += 1
                        if symbol:
                            open_syms.discard(symbol)

            counts = self._count_open_positions()
            stock_capacity = max(0, self.max_stocks - int(counts.get("stock", 0)))
            crypto_capacity = max(0, self.max_crypto - int(counts.get("crypto", 0)))
            total_capacity = max(0, self.max_open_positions_total - (int(counts.get("stock", 0)) + int(counts.get("crypto", 0))))
            candidates = self._collect_candidate_rows()
            for row in candidates:
                if opened >= self.max_new_positions_per_cycle:
                    break
                if total_capacity <= 0:
                    break
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                if not symbol or symbol in open_syms:
                    skipped += 1
                    continue
                if self._cooldown_active(symbol):
                    skipped += 1
                    continue
                if asset == "stock" and stock_capacity <= 0:
                    continue
                if asset == "crypto" and crypto_capacity <= 0:
                    continue

                allowed, reason, gate_meta = self._is_candidate_paper_eligible(row)
                if not allowed:
                    skipped += 1
                    continue

                opened_row = self._open_position_from_row(
                    row,
                    source_bucket=f"paper_autopilot_{reason}",
                    gate_meta=gate_meta,
                )
                if opened_row.get("ok"):
                    opened += 1
                    open_syms.add(symbol)
                    total_capacity = max(0, total_capacity - 1)
                    if asset == "stock":
                        stock_capacity = max(0, stock_capacity - 1)
                    else:
                        crypto_capacity = max(0, crypto_capacity - 1)
                else:
                    skipped += 1

            out = {
                "ok": True,
                "autopilot_enabled": True,
                "orders_submitted": int(opened),
                "positions_closed": int(closed),
                "positions_skipped": int(skipped),
                "cycle_timestamp": _now_iso(),
            }
            self._runtime_state["last_cycle_utc"] = out["cycle_timestamp"]
            self._runtime_state["last_cycle_summary"] = dict(out)
            self._runtime_state["last_error"] = ""
            self._save_state_file()
            return out

    def paper_positions(self):
        open_rows = self._fetch_open_positions()
        out: list[dict[str, Any]] = []
        for row in open_rows:
            item = dict(row)
            item["entry_metadata"] = _safe_json_load(row.get("row_json"))
            item["lifecycle_notes"] = _safe_json_load(row.get("lifecycle_notes"))
            out.append(item)
        return out
