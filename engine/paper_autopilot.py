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

try:
    from engine.trade_lifecycle_tracker import (
        close_lifecycle_record,
        create_lifecycle_record,
        update_lifecycle_progress,
    )
except Exception:  # pragma: no cover - tracker is additive and optional
    close_lifecycle_record = None  # type: ignore[assignment]
    create_lifecycle_record = None  # type: ignore[assignment]
    update_lifecycle_progress = None  # type: ignore[assignment]

try:
    from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1
except Exception:  # pragma: no cover - allocation engine is additive
    class PaperOpportunityAllocationEngineV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, rows=None):
            return {
                "enabled": False,
                "mode": "paper_only_shadow_allocation",
                "paper_opportunity_allocation_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "natural_exit_preserved": True,
            }

try:
    from engine.edge_development_suite_v1 import EdgeDevelopmentSuiteV1
except Exception:  # pragma: no cover - edge suite is additive
    class EdgeDevelopmentSuiteV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

        def status(self, rows=None):
            return {
                "enabled": False,
                "mode": "paper_only_shadow_learning",
                "edge_development_status_v1": True,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "natural_exit_preserved": True,
                "forced_early_exit_enabled": False,
            }

try:
    from engine.trade_management_portfolio_intelligence_v1 import TradeManagementPortfolioIntelligenceV1
except Exception:  # pragma: no cover - trade management suite is additive
    class TradeManagementPortfolioIntelligenceV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def decorate_candidates(self, rows):
            return [dict(r) for r in (rows or []) if isinstance(r, dict)]

try:
    from engine.market_session_execution_timing_v1 import MarketSessionExecutionTimingV1
except Exception:  # pragma: no cover - session timing suite is additive
    class MarketSessionExecutionTimingV1:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            pass

        def status(self, *args, **kwargs):
            return {
                "enabled": False,
                "version": "1.0.0",
                "market_session_mode": "unknown_closed",
                "market_is_open": False,
                "market_is_tradable": False,
                "paper_order_submission_allowed": False,
                "execution_confirmation_required": True,
                "execution_intent_status": "intent_unavailable",
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
            }

        def confirmation_for_candidate(self, *args, **kwargs):
            return self.status()


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


def _bounded_score(value: Any, default: Any = None):
    score = _to_float(value, default if default is not None else 0.0)
    if value is None and default is None:
        return None
    if score <= 1.0:
        score *= 100.0
    return max(0.0, min(100.0, float(score)))


def _entry_bridge_quality(row: dict[str, Any]):
    r = dict(row or {})
    for key in (
        "buy_quality_score",
        "trade_quality_score",
        "entry_filter_v2_score",
        "entry_filter_score",
        "entry_quality_v3_score",
        "entry_quality_v2_score",
        "entry_quality_score",
        "entry_quality",
        "execution_readiness_score",
        "risk_adjusted_profit_score",
        "aggressive_profit_score",
        "opportunity_score_pct",
        "best_horizon_score",
    ):
        if r.get(key) is None:
            continue
        score = _bounded_score(r.get(key))
        if score is not None:
            return score, key
    grade = _bounded_score(r.get("grade_percent"), None)
    confidence = _bounded_score(r.get("confidence"), _bounded_score(r.get("predicted_win_probability"), None))
    parts = [x for x in (grade, confidence) if x is not None]
    if parts:
        return round((sum(parts) / len(parts)) * 0.82, 2), "grade_confidence_compat"
    return None, ""


def _infer_horizon_style(row: dict[str, Any]):
    r = dict(row or {})
    for key in ("trade_horizon_style", "best_horizon_style", "recommended_hold_style", "intended_hold_category"):
        raw = str(r.get(key) or "").strip().lower()
        if raw in {"scalp", "day_trade", "swing_trade"}:
            return raw, key, False
        if raw in {"intraday", "day", "daytrading"}:
            return "day_trade", key, True
        if raw in {"swing", "position_trade", "position"}:
            return "swing_trade", key, True
    fits = {
        "scalp": _bounded_score(r.get("scalp_fit_score"), None),
        "day_trade": _bounded_score(r.get("day_trade_fit_score"), None),
        "swing_trade": _bounded_score(r.get("swing_trade_fit_score"), None),
    }
    fits = {k: v for k, v in fits.items() if v is not None}
    if fits:
        best = max(fits.items(), key=lambda item: float(item[1]))[0]
        return best, f"{best}_fit_score", True
    action = str(r.get("action") or r.get("prediction") or "").strip().lower()
    readiness = " ".join(
        str(r.get(k) or "").strip().lower()
        for k in ("readiness_label", "paper_ready_status", "release_status", "buy_eligibility", "canonical_final_state")
    )
    if action in {"buy", "strong buy"} or "paper" in readiness or "watch" in readiness or "soft" in readiness:
        return "day_trade", "paper_entry_safe_default", True
    return "", "", False


def _normalize_paper_entry_bridge(row: dict[str, Any]) -> dict[str, Any]:
    r = dict(row or {})
    score, source = _entry_bridge_quality(r)
    if score is not None:
        r.setdefault("buy_quality_score", round(score, 2))
        r.setdefault("trade_quality_score", round(score, 2))
        r.setdefault("entry_quality_score", round(score, 2))
        r["paper_entry_bridge_score"] = round(score, 2)
        r["paper_entry_bridge_score_source"] = str(source)
        if not str(r.get("buy_quality_tier") or "").strip():
            if score >= 75.0:
                r["buy_quality_tier"] = "strong"
            elif score >= 60.0:
                r["buy_quality_tier"] = "moderate"
            elif score >= 50.0:
                r["buy_quality_tier"] = "qualified"
            else:
                r["buy_quality_tier"] = "weak"
    horizon, horizon_source, inferred = _infer_horizon_style(r)
    if horizon:
        r.setdefault("trade_horizon_style", horizon)
        r.setdefault("best_horizon_style", horizon)
        r["paper_entry_horizon_style"] = horizon
        r["paper_entry_horizon_source"] = horizon_source
        r["paper_entry_horizon_inferred"] = bool(inferred)
    action = str(r.get("action") or r.get("prediction") or "").strip().lower()
    readiness = " ".join(
        str(r.get(k) or "").strip().lower()
        for k in ("readiness_label", "paper_ready_status", "release_status", "buy_eligibility", "canonical_final_state")
    )
    if not str(r.get("buy_eligibility") or "").strip():
        if action in {"buy", "strong buy"}:
            r["buy_eligibility"] = "qualified_buy"
        elif "paper" in readiness or "watch" in readiness or "soft" in readiness:
            r["buy_eligibility"] = "paper_test_eligible"
    r["paper_entry_eligibility_bridge_v1"] = True
    return r


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
        self.throughput_expansion_enabled = bool(kwargs.get("throughput_expansion_enabled", False))
        self.soft_candidate_expansion_enabled = bool(kwargs.get("soft_candidate_expansion_enabled", False))
        self.paper_entry_threshold_relief_points = max(0.0, min(12.0, _to_float(kwargs.get("paper_entry_threshold_relief_points"), 0.0)))

        self.get_top_buys_fn = kwargs.get("get_top_buys_fn") if callable(kwargs.get("get_top_buys_fn")) else None
        self.get_latest_row_fn = kwargs.get("get_latest_row_fn") if callable(kwargs.get("get_latest_row_fn")) else None
        self.trade_intel = kwargs.get("trade_intel")
        self.exit_engine = kwargs.get("exit_engine")
        self.exit_learning = kwargs.get("exit_learning")
        self.alpaca_paper_broker = kwargs.get("alpaca_paper_broker")
        self.live_performance_fn = kwargs.get("live_performance_fn") if callable(kwargs.get("live_performance_fn")) else None
        self.freshness_manager = kwargs.get("freshness_manager")
        self.max_open_positions_total = max(2, _to_int(kwargs.get("max_open_positions_total"), 10))
        self.paper_opportunity_allocator = kwargs.get("paper_opportunity_allocator")
        if self.paper_opportunity_allocator is None:
            try:
                self.paper_opportunity_allocator = PaperOpportunityAllocationEngineV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.paper_opportunity_allocator = None
        self.edge_development_suite = kwargs.get("edge_development_suite")
        if self.edge_development_suite is None:
            try:
                self.edge_development_suite = EdgeDevelopmentSuiteV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.edge_development_suite = None
        self.trade_management_portfolio_suite = kwargs.get("trade_management_portfolio_suite")
        if self.trade_management_portfolio_suite is None:
            try:
                self.trade_management_portfolio_suite = TradeManagementPortfolioIntelligenceV1(
                    state_dir=os.path.dirname(self.state_path) or "state"
                )
            except Exception:
                self.trade_management_portfolio_suite = None
        self.market_session_timing_suite = kwargs.get("market_session_timing_suite")
        if self.market_session_timing_suite is None:
            try:
                self.market_session_timing_suite = MarketSessionExecutionTimingV1()
            except Exception:
                self.market_session_timing_suite = None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._cycle_lock = threading.Lock()
        self._runtime_state: dict[str, Any] = {
            "last_cycle_utc": "",
            "last_cycle_summary": {},
            "last_execution_trace": {},
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
            row = _normalize_paper_entry_bridge(row)
            row.setdefault("symbol", sym)
            row.setdefault("asset_type", "stock")
            dedup.append(row)
        if self.edge_development_suite is not None and hasattr(self.edge_development_suite, "decorate_candidates"):
            try:
                dedup = list(self.edge_development_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.trade_management_portfolio_suite is not None and hasattr(self.trade_management_portfolio_suite, "decorate_candidates"):
            try:
                dedup = list(self.trade_management_portfolio_suite.decorate_candidates(dedup) or dedup)
            except Exception:
                pass
        if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "decorate_candidates"):
            try:
                return list(self.paper_opportunity_allocator.decorate_candidates(dedup) or dedup)
            except Exception:
                return dedup
        return dedup

    def _entry_commitment_gate_v1(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        row = _normalize_paper_entry_bridge(row)
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

        quality_floor = 44.0 if self.soft_candidate_expansion_enabled else 48.0
        confidence_floor = 49.0 if self.soft_candidate_expansion_enabled else 52.0
        if quality < quality_floor and confidence < confidence_floor:
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
        if bool(row.get("paper_profit_candidate_eligible", False)) and _to_float(row.get("risk_adjusted_profit_score"), 0.0) >= 58.0:
            positive_signals += 1

        if positive_signals < 2 and not (
            self.soft_candidate_expansion_enabled
            and quality >= quality_floor
            and confidence >= confidence_floor
        ):
            return False, "insufficient_positive_signals", {"commitment_score": 0.0}

        high_uncertainty_quality_floor = 60.0 if self.soft_candidate_expansion_enabled else 64.0
        if any(x in uncertainty_tier for x in ("high",)) and quality < high_uncertainty_quality_floor:
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

        base_commitment_floor = max(50.0, 58.0 - self.paper_entry_threshold_relief_points)
        watchlist_commitment_floor = max(56.0, 64.0 - self.paper_entry_threshold_relief_points)
        if commitment_score < base_commitment_floor:
            return False, "entry_commitment_below_threshold", {"commitment_score": round(commitment_score, 2)}
        if commitment_score < watchlist_commitment_floor and "watchlist" in eligibility:
            return False, "watchlist_commitment_not_strong_enough", {"commitment_score": round(commitment_score, 2)}

        return True, "eligible", {
            "commitment_score": round(commitment_score, 2),
            "confidence_at_entry": round(confidence, 2),
            "uncertainty_tier": uncertainty_tier or "unknown",
            "uncertainty_score": round(uncertainty_score, 2),
        }

    def _is_candidate_paper_eligible(self, row: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        return self._entry_commitment_gate_v1(row)

    def _alpaca_paper_broker_enabled(self) -> bool:
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "safety_status"):
            return False
        try:
            safety = broker.safety_status()
            return bool(isinstance(safety, dict) and safety.get("broker_execution_enabled"))
        except Exception:
            return False

    def _alpaca_safety_snapshot(self) -> dict[str, Any]:
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "safety_status"):
            return {
                "alpaca_enabled": False,
                "paper_mode_verified": False,
                "broker_execution_enabled": False,
                "safety_reasons": ["alpaca_paper_broker_unavailable"],
            }
        try:
            safety = dict(broker.safety_status() or {})
        except Exception as exc:
            safety = {"safety_reasons": [f"alpaca_safety_status_exception:{str(exc)[:120]}"]}
        return {
            "alpaca_enabled": bool(safety.get("enabled_requested")),
            "paper_mode_verified": bool(safety.get("paper_mode_verified")),
            "broker_execution_enabled": bool(safety.get("broker_execution_enabled")),
            "safety_reasons": list(safety.get("safety_reasons") or []),
            "live_endpoint_detected": bool(safety.get("live_endpoint_detected", False)),
            "live_endpoint_rejected": bool(safety.get("live_endpoint_rejected", True)),
        }

    def _broker_open_symbols_snapshot(self) -> dict[str, Any]:
        safety = self._alpaca_safety_snapshot()
        out = {
            "broker_reconciliation_active": False,
            "broker_positions_fetch_ok": False,
            "broker_open_positions_count": 0,
            "broker_open_symbols": set(),
            "broker_positions_error_sanitized": "",
        }
        if not safety.get("broker_execution_enabled"):
            return out
        broker = self.alpaca_paper_broker
        if broker is None or not hasattr(broker, "positions"):
            out["broker_reconciliation_active"] = True
            out["broker_positions_error_sanitized"] = "broker_positions_unavailable"
            return out
        out["broker_reconciliation_active"] = True
        try:
            payload = dict(broker.positions() or {})
            if bool(payload.get("ok")):
                symbols = set()
                for row in list(payload.get("positions") or []):
                    if not isinstance(row, dict):
                        continue
                    sym = str(row.get("symbol") or "").upper().strip()
                    if sym:
                        symbols.add(sym)
                out["broker_positions_fetch_ok"] = True
                out["broker_open_symbols"] = symbols
                out["broker_open_positions_count"] = int(len(symbols))
            else:
                out["broker_positions_error_sanitized"] = str(payload.get("error") or "broker_positions_fetch_failed")[:180]
        except Exception as exc:
            out["broker_positions_error_sanitized"] = f"broker_positions_exception:{str(exc)[:120]}"
        return out

    def _sanitize_broker_error(self, result: dict[str, Any] | None) -> str:
        if not isinstance(result, dict):
            return ""
        raw = str(result.get("broker_error") or result.get("error") or result.get("reason") or "").strip()
        return raw[:180]

    def _current_execution_capacities(self) -> dict[str, Any]:
        counts = self._count_open_positions()
        open_rows = self._fetch_open_positions()
        open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows}
        stock_open = int(counts.get("stock", 0))
        crypto_open = int(counts.get("crypto", 0))
        return {
            "open_symbols": open_syms,
            "open_positions_count": stock_open + crypto_open,
            "open_positions_stock": stock_open,
            "open_positions_crypto": crypto_open,
            "stock_capacity": max(0, self.max_stocks - stock_open),
            "crypto_capacity": max(0, self.max_crypto - crypto_open),
            "total_capacity": max(0, self.max_open_positions_total - (stock_open + crypto_open)),
        }

    def _candidate_trace_row(
        self,
        row: dict[str, Any],
        open_syms: set[str],
        stock_capacity: int,
        crypto_capacity: int,
        total_capacity: int,
        selected_so_far: int = 0,
        internal_open_syms: set[str] | None = None,
        broker_open_syms: set[str] | None = None,
        broker_reconciliation_active: bool = False,
    ) -> tuple[dict[str, Any], bool, str, dict[str, Any]]:
        r = _normalize_paper_entry_bridge(row)
        symbol = str(r.get("symbol") or "").upper().strip()
        asset = _norm_asset(r.get("asset_type") or "stock")
        allowed = False
        reason = "not_evaluated"
        gate_meta: dict[str, Any] = {"commitment_score": 0.0}
        internal_set = set(internal_open_syms or set())
        broker_set = set(broker_open_syms or set())
        duplicate_source = "none"
        if symbol:
            in_internal = symbol in internal_set
            in_broker = symbol in broker_set
            if in_internal and in_broker:
                duplicate_source = "both"
            elif in_internal:
                duplicate_source = "internal"
            elif in_broker:
                duplicate_source = "broker"
        if not symbol:
            reason = "missing_symbol"
        elif symbol in open_syms:
            reason = "duplicate_active_position"
        elif self._cooldown_active(symbol):
            reason = "cooldown_active"
        elif total_capacity <= 0:
            reason = "max_concurrent_positions_reached"
        elif selected_so_far >= self.max_new_positions_per_cycle:
            reason = "max_new_positions_per_cycle_reached"
        elif asset == "stock" and stock_capacity <= 0:
            reason = "stock_capacity_reached"
        elif asset == "crypto" and crypto_capacity <= 0:
            reason = "crypto_capacity_reached"
        else:
            allowed, reason, gate_meta = self._is_candidate_paper_eligible(r)
        session_diag = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "confirmation_for_candidate"):
            try:
                session_diag = dict(
                    self.market_session_timing_suite.confirmation_for_candidate(
                        r,
                        gate_meta=gate_meta,
                        broker_ready=self._alpaca_paper_broker_enabled(),
                    )
                    or {}
                )
            except Exception:
                session_diag = {}
        trace = {
            "symbol": symbol,
            "asset_type": asset,
            "action": str(r.get("action") or r.get("prediction") or ""),
            "readiness": str(r.get("readiness_label") or r.get("paper_ready_status") or r.get("buy_eligibility") or ""),
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "opportunity_quality_score": round(_to_float(r.get("opportunity_quality_score"), 0.0), 2),
            "opportunity_quality_label": str(r.get("opportunity_quality_label") or ""),
            "expected_value_score": round(_to_float(r.get("expected_value_score"), 0.0), 2),
            "expected_win_probability": round(_to_float(r.get("expected_win_probability"), 0.0), 2),
            "trade_archetype": str(r.get("trade_archetype") or ""),
            "archetype_quality_score": round(_to_float(r.get("archetype_quality_score"), 0.0), 2),
            "regime_alignment_score": round(_to_float(r.get("regime_alignment_score"), 0.0), 2),
            "regime_alignment_label": str(r.get("regime_alignment_label") or ""),
            "edge_composite_score": round(_to_float(r.get("edge_composite_score"), 0.0), 2),
            "edge_composite_label": str(r.get("edge_composite_label") or ""),
            "exit_quality_score": round(_to_float(r.get("exit_quality_score"), 0.0), 2),
            "exit_readiness_label": str(r.get("exit_readiness_label") or ""),
            "intelligent_position_size_pct": round(_to_float(r.get("intelligent_position_size_pct"), 0.0), 3),
            "sizing_safety_label": str(r.get("sizing_safety_label") or ""),
            "portfolio_heat_score": round(_to_float(r.get("portfolio_heat_score"), 0.0), 2),
            "portfolio_correlation_risk": round(_to_float(r.get("portfolio_correlation_risk"), 0.0), 2),
            "survivability_score": round(_to_float(r.get("survivability_score"), 0.0), 2),
            "trade_management_score": round(_to_float(r.get("trade_management_score"), 0.0), 2),
            "adaptive_trade_quality_label": str(r.get("adaptive_trade_quality_label") or ""),
            "allocation_lane": str(r.get("allocation_lane") or ""),
            "allocation_lane_score": round(_to_float(r.get("allocation_lane_score"), 0.0), 2),
            "paper_allocation_priority": round(_to_float(r.get("paper_allocation_priority"), 0.0), 2),
            "exploration_candidate": bool(r.get("exploration_candidate", False)),
            "exploration_allowed": bool(r.get("exploration_allowed", False)),
            "exploration_risk_label": str(r.get("exploration_risk_label") or ""),
            "exploration_rejection_reason": str(r.get("exploration_rejection_reason") or ""),
            "risk_adjusted_opportunity_rank": int(_to_float(r.get("risk_adjusted_opportunity_rank"), 0.0)),
            "entry_score": round(_to_float(r.get("paper_entry_bridge_score"), _to_float(r.get("entry_quality_score"), 0.0)), 2),
            "confidence": round(_to_float(r.get("confidence"), _to_float(r.get("predicted_win_probability"), 0.0)), 2),
            "eligible": bool(allowed),
            "decision_reason": str(reason),
            "commitment_score": round(_to_float(gate_meta.get("commitment_score"), 0.0), 2),
            "duplicate_active_position": bool(symbol in open_syms) if symbol else False,
            "duplicate_source": duplicate_source,
            "broker_reconciliation_active": bool(broker_reconciliation_active),
            "market_session_mode": str(session_diag.get("market_session_mode") or ""),
            "market_is_open": bool(session_diag.get("market_is_open", False)),
            "market_is_tradable": bool(session_diag.get("market_is_tradable", False)),
            "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
            "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
            "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
            "open_confirmation_label": str(session_diag.get("open_confirmation_label") or ""),
            "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
            "execution_intent_status": str(session_diag.get("execution_intent_status") or ""),
            "candidate_execution_intent": bool(session_diag.get("candidate_execution_intent", False)),
            "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", False)),
            "requires_open_confirmation": bool(session_diag.get("requires_open_confirmation", True)),
            "weekend_watchlist_candidate": bool(session_diag.get("weekend_watchlist_candidate", False)),
            "selected": False,
            "order_attempted": False,
        }
        return trace, bool(allowed), str(reason), dict(gate_meta or {})

    def _submit_alpaca_paper_entry_order(
        self,
        row: dict[str, Any],
        entry_price: float,
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        broker = self.alpaca_paper_broker
        if not self._alpaca_paper_broker_enabled():
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_paper_broker_disabled"}
        if broker is None or not hasattr(broker, "submit_paper_order"):
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_paper_broker_unavailable"}
        r = _normalize_paper_entry_bridge(row)
        meta = dict(gate_meta or {})
        asset_type = _norm_asset(r.get("asset_type") or "stock")
        if asset_type != "stock":
            return {"enabled": False, "paper_order_submitted": False, "reason": "alpaca_crypto_execution_deferred"}
        limits_ok = bool(meta.get("paper_autopilot_limits_ok", False))
        if not limits_ok:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "paper_autopilot_limits_proof_required",
                "paper_autopilot_limits_ok": False,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "paper_limits_not_proven"),
            }
        risk_label_raw = str(r.get("portfolio_risk_label") or "").strip()
        risk_label = risk_label_raw.lower()
        risk_score_raw = r.get("portfolio_risk_score")
        risk_score = _to_float(risk_score_raw, 0.0) if risk_score_raw is not None else None
        explicit_portfolio_ok = r.get("portfolio_risk_ok")
        portfolio_risk_proof_present = bool(
            explicit_portfolio_ok is not None
            or risk_score is not None
            or bool(risk_label_raw)
        )
        if not portfolio_risk_proof_present:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "missing_portfolio_risk_data",
                "portfolio_risk_proof_present": False,
                "portfolio_risk_score_used": None,
                "portfolio_risk_label_used": "",
                "portfolio_risk_preflight_reason": "missing_portfolio_risk_data",
            }

        if explicit_portfolio_ok is not None:
            portfolio_ok = bool(explicit_portfolio_ok)
            preflight_reason = "explicit_portfolio_risk_ok"
        else:
            # Conservative fallback: require a non-blocking label plus minimum score
            # when explicit portfolio_risk_ok is not present.
            if risk_score is None:
                return {
                    "ok": False,
                    "paper_order_submitted": False,
                    "error": "missing_portfolio_risk_data",
                    "portfolio_risk_proof_present": False,
                    "portfolio_risk_score_used": None,
                    "portfolio_risk_label_used": risk_label_raw,
                    "portfolio_risk_preflight_reason": "missing_portfolio_risk_score",
                }
            portfolio_ok = bool(risk_label not in {"high_risk", "blocked"} and risk_score >= 35.0)
            preflight_reason = "derived_from_portfolio_risk_fields"

        session_diag = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "confirmation_for_candidate"):
            try:
                session_diag = dict(
                    self.market_session_timing_suite.confirmation_for_candidate(
                        r,
                        gate_meta=meta,
                        broker_ready=self._alpaca_paper_broker_enabled(),
                    )
                    or {}
                )
            except Exception:
                session_diag = {}
        if not bool(session_diag.get("paper_order_submission_allowed", False)):
            blocker = "session_order_submission_blocked"
            if bool(session_diag.get("execution_confirmation_required", True)):
                blocker = "open_confirmation_required"
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": blocker,
                "market_session_mode": str(session_diag.get("market_session_mode") or "unknown_closed"),
                "paper_order_submission_allowed": False,
                "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
                "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
                "open_confirmation_label": str(session_diag.get("open_confirmation_label") or "wait_for_open_structure"),
                "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or session_diag.get("session_reason") or ""),
                "execution_intent_status": str(session_diag.get("execution_intent_status") or "intent_ready"),
                "candidate_execution_intent": bool(session_diag.get("candidate_execution_intent", True)),
                "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", True)),
                "requires_open_confirmation": True,
                "weekend_watchlist_candidate": bool(session_diag.get("weekend_watchlist_candidate", False)),
                "intent_created_reason": str(session_diag.get("intent_created_reason") or "closed_market_execution_intent_only"),
                "replay_candidate_snapshot_saved": bool(session_diag.get("replay_candidate_snapshot_saved", True)),
                "replay_learning_ready": bool(session_diag.get("replay_learning_ready", True)),
                "session_timing_outcome_tracking_ready": True,
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
                "natural_exit_logic_preserved": True,
            }
        if str(session_diag.get("open_confirmation_label") or "") != "confirmed_execute":
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": "open_confirmation_required",
                "market_session_mode": str(session_diag.get("market_session_mode") or "unknown_closed"),
                "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": True,
                "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
                "open_confirmation_label": str(session_diag.get("open_confirmation_label") or "wait_for_open_structure"),
                "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
                "execution_intent_status": str(session_diag.get("execution_intent_status") or "pending_confirmation"),
                "defer_until_market_confirmation": bool(session_diag.get("defer_until_market_confirmation", True)),
                "requires_open_confirmation": True,
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
                "natural_exit_logic_preserved": True,
            }

        broker_snapshot = self._broker_open_symbols_snapshot()
        reconciliation_checked = bool(
            broker_snapshot.get("broker_reconciliation_active")
            and (
                broker_snapshot.get("broker_positions_fetch_ok")
                or str(broker_snapshot.get("broker_positions_error_sanitized") or "").strip()
            )
        )
        order = {
            "symbol": str(r.get("symbol") or "").upper().strip(),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "astra_paper_logic_passed": True,
            "paper_logic_passed": True,
            "paper_ready": True,
            "paper_test_eligible": True,
            "paper_order_preflight_ready": True,
            "paper_limits_ok": True,
            "paper_autopilot_limits_ok": True,
            "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
            "portfolio_risk_ok": bool(portfolio_ok),
            "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
            "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
            "portfolio_risk_label_used": risk_label_raw,
            "portfolio_risk_preflight_reason": preflight_reason,
            "market_session_mode": str(session_diag.get("market_session_mode") or ""),
            "paper_order_submission_allowed": bool(session_diag.get("paper_order_submission_allowed", False)),
            "execution_confirmation_required": bool(session_diag.get("execution_confirmation_required", True)),
            "open_confirmation_score": round(_to_float(session_diag.get("open_confirmation_score"), 0.0), 2),
            "open_confirmation_label": str(session_diag.get("open_confirmation_label") or ""),
            "open_confirmation_reason": str(session_diag.get("open_confirmation_reason") or ""),
            "quote_freshness_confirmed": bool(session_diag.get("quote_freshness_confirmed", False)),
            "spread_liquidity_confirmed": bool(session_diag.get("spread_liquidity_confirmed", False)),
            "gap_behavior_confirmed": bool(session_diag.get("gap_behavior_confirmed", False)),
            "entry_commitment_confirmed": bool(session_diag.get("entry_commitment_confirmed", False)),
            "portfolio_risk_confirmed": bool(session_diag.get("portfolio_risk_confirmed", False)),
            "broker_preflight_confirmed": bool(session_diag.get("broker_preflight_confirmed", False)),
            "broker_reconciliation_active": bool(broker_snapshot.get("broker_reconciliation_active", False)),
            "broker_positions_checked": bool(reconciliation_checked),
            "natural_exit_logic_preserved": True,
            "entry_price_reference": round(_to_float(entry_price), 6),
            "entry_commitment_score": round(_to_float((gate_meta or {}).get("commitment_score"), 0.0), 2),
        }
        try:
            res = dict(broker.submit_paper_order(order) or {})
            res.setdefault("paper_autopilot_limits_ok", True)
            res.setdefault("paper_autopilot_limits_reason", str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"))
            res.setdefault("portfolio_risk_proof_present", bool(portfolio_risk_proof_present))
            res.setdefault("portfolio_risk_score_used", (None if risk_score is None else round(float(risk_score), 4)))
            res.setdefault("portfolio_risk_label_used", risk_label_raw)
            res.setdefault("portfolio_risk_preflight_reason", preflight_reason)
            return res
        except Exception as exc:
            return {
                "ok": False,
                "paper_order_submitted": False,
                "error": f"alpaca_paper_submit_exception:{str(exc)[:120]}",
                "paper_autopilot_limits_ok": True,
                "paper_autopilot_limits_reason": str(meta.get("paper_autopilot_limits_reason") or "cycle_limits_passed"),
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": (None if risk_score is None else round(float(risk_score), 4)),
                "portfolio_risk_label_used": risk_label_raw,
                "portfolio_risk_preflight_reason": preflight_reason,
            }

    def _build_entry_context_v1(
        self,
        row: dict[str, Any],
        entry_price: float,
        source_bucket: str,
        gate_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        r = _normalize_paper_entry_bridge(row)
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
            "entry_paper_bridge_score": round(_to_float(r.get("paper_entry_bridge_score"), 0.0), 2),
            "entry_paper_bridge_score_source": str(r.get("paper_entry_bridge_score_source") or ""),
            "trade_horizon_style": str(r.get("trade_horizon_style") or r.get("best_horizon_style") or ""),
            "trade_archetype": str(r.get("trade_archetype") or "unknown"),
            "opportunity_quality_score": round(_to_float(r.get("opportunity_quality_score"), 0.0), 2),
            "opportunity_quality_label": str(r.get("opportunity_quality_label") or ""),
            "expected_value_score": round(_to_float(r.get("expected_value_score"), 0.0), 2),
            "expected_win_probability": round(_to_float(r.get("expected_win_probability"), 0.0), 2),
            "expected_reward_risk_ratio": round(_to_float(r.get("expected_reward_risk_ratio"), 0.0), 3),
            "expected_follow_through_score": round(_to_float(r.get("expected_follow_through_score"), 0.0), 2),
            "expected_loss_containment_score": round(_to_float(r.get("expected_loss_containment_score"), 0.0), 2),
            "archetype_confidence": round(_to_float(r.get("archetype_confidence"), 0.0), 2),
            "archetype_quality_score": round(_to_float(r.get("archetype_quality_score"), 0.0), 2),
            "regime_alignment_score": round(_to_float(r.get("regime_alignment_score"), 0.0), 2),
            "regime_alignment_label": str(r.get("regime_alignment_label") or ""),
            "regime_edge_multiplier": round(_to_float(r.get("regime_edge_multiplier"), 1.0), 4),
            "edge_composite_score": round(_to_float(r.get("edge_composite_score"), 0.0), 2),
            "edge_composite_label": str(r.get("edge_composite_label") or ""),
            "edge_development_shadow_only": bool(r.get("edge_development_shadow_only", True)),
            "edge_summary": str(r.get("edge_summary") or ""),
            "exit_quality_score": round(_to_float(r.get("exit_quality_score"), 0.0), 2),
            "exit_readiness_label": str(r.get("exit_readiness_label") or ""),
            "momentum_deterioration_score": round(_to_float(r.get("momentum_deterioration_score"), 0.0), 2),
            "follow_through_decay_score": round(_to_float(r.get("follow_through_decay_score"), 0.0), 2),
            "trend_exhaustion_score": round(_to_float(r.get("trend_exhaustion_score"), 0.0), 2),
            "adaptive_stop_suggestion": str(r.get("adaptive_stop_suggestion") or ""),
            "adaptive_profit_lock_score": round(_to_float(r.get("adaptive_profit_lock_score"), 0.0), 2),
            "hold_quality_score": round(_to_float(r.get("hold_quality_score"), 0.0), 2),
            "intelligent_position_size_pct": round(_to_float(r.get("intelligent_position_size_pct"), 0.0), 3),
            "position_size_confidence": round(_to_float(r.get("position_size_confidence"), 0.0), 2),
            "sizing_safety_label": str(r.get("sizing_safety_label") or ""),
            "portfolio_heat_score": round(_to_float(r.get("portfolio_heat_score"), 0.0), 2),
            "portfolio_correlation_risk": round(_to_float(r.get("portfolio_correlation_risk"), 0.0), 2),
            "sector_concentration_score": round(_to_float(r.get("sector_concentration_score"), 0.0), 2),
            "portfolio_stability_score": round(_to_float(r.get("portfolio_stability_score"), 0.0), 2),
            "survivability_score": round(_to_float(r.get("survivability_score"), 0.0), 2),
            "trade_management_score": round(_to_float(r.get("trade_management_score"), 0.0), 2),
            "risk_adjusted_trade_quality": round(_to_float(r.get("risk_adjusted_trade_quality"), 0.0), 2),
            "adaptive_trade_quality_label": str(r.get("adaptive_trade_quality_label") or ""),
            "trade_management_shadow_only": bool(r.get("trade_management_shadow_only", True)),
            "portfolio_intelligence_shadow_only": bool(r.get("portfolio_intelligence_shadow_only", True)),
            "trade_management_summary": str(r.get("trade_management_summary") or ""),
            "allocation_lane": str(r.get("allocation_lane") or ""),
            "allocation_lane_score": round(_to_float(r.get("allocation_lane_score"), 0.0), 2),
            "paper_allocation_priority": round(_to_float(r.get("paper_allocation_priority"), 0.0), 2),
            "exploration_candidate": bool(r.get("exploration_candidate", False)),
            "exploration_allowed": bool(r.get("exploration_allowed", False)),
            "exploration_risk_label": str(r.get("exploration_risk_label") or ""),
            "exploration_rejection_reason": str(r.get("exploration_rejection_reason") or ""),
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
        row = _normalize_paper_entry_bridge(row)
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
        broker_order = self._submit_alpaca_paper_entry_order(row, entry_price, gate_meta=gate_meta)
        if broker_order.get("enabled", True) is not False and not broker_order.get("ok", False):
            return {
                "ok": False,
                "error": "alpaca_paper_order_failed",
                "symbol": symbol,
                "broker_error": str(broker_order.get("error") or broker_order.get("reason") or "unknown")[:160],
            }
        if broker_order:
            entry_row["alpaca_paper_order"] = broker_order
        entry_context = self._build_entry_context_v1(row, entry_price, source_bucket, gate_meta=gate_meta)
        entry_context["position_id"] = pid
        entry_context["alpaca_paper_order"] = broker_order

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
        if callable(create_lifecycle_record):
            try:
                create_lifecycle_record(
                    {
                        "lifecycle_id": pid,
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "signal_timestamp": str(row.get("timestamp") or now_iso),
                        "release_status": str(row.get("paper_ready_status") or row.get("release_status") or "paper"),
                        "entry_timestamp": now_iso,
                        "entry_price": entry_price,
                        "current_price": entry_price,
                        "confidence": _to_float(row.get("confidence"), _to_float(row.get("predicted_win_probability"), 0.0)),
                        "grade": _to_float(row.get("grade_percent"), _to_float(row.get("persona_weighted_grade"), 0.0)),
                        "entry_quality_score": _to_float(row.get("entry_quality_score"), _to_float(row.get("paper_entry_bridge_score"), 0.0)),
                        "entry_quality_band": str(row.get("entry_quality_band") or "unknown"),
                        "trade_horizon_style": str(row.get("trade_horizon_style") or row.get("best_horizon_style") or ""),
                        "trade_archetype": str(row.get("setup_type") or "unknown"),
                        "catalyst_context": str(row.get("regime_context") or row.get("market_regime") or ""),
                        "source_endpoint": "paper_autopilot",
                        "lifecycle_stage": "entry",
                    }
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
        if callable(close_lifecycle_record):
            try:
                close_lifecycle_record(
                    pid,
                    {
                        "symbol": symbol,
                        "asset_type": asset_type,
                        "exit_timestamp": now_iso,
                        "exit_price": exit_price,
                        "current_price": exit_price,
                        "pnl_pct": ret,
                        "max_favorable_excursion_pct": _to_float(notes.get("max_favorable_excursion"), max(ret, 0.0)),
                        "max_adverse_excursion_pct": _to_float(notes.get("max_adverse_excursion"), min(ret, 0.0)),
                        "exit_reason": str(exit_reason or ""),
                        "outcome_label": "winner" if ret > 0 else ("loser" if ret < 0 else "flat"),
                        "source_endpoint": "paper_autopilot",
                    },
                )
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
        if callable(update_lifecycle_progress):
            try:
                update_lifecycle_progress(
                    pid,
                    {
                        "symbol": str(open_row.get("symbol") or ""),
                        "asset_type": _norm_asset(open_row.get("asset_type") or "stock"),
                        "current_price": current,
                        "pnl_pct": ret,
                        "max_favorable_excursion_pct": mfe,
                        "max_adverse_excursion_pct": mae,
                        "exit_reason": str(open_row.get("exit_reason") or ""),
                        "source_endpoint": "paper_autopilot",
                        "lifecycle_stage": "monitoring",
                    },
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
            "last_execution_trace": dict(self._runtime_state.get("last_execution_trace") or {}),
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
            "max_stocks": int(self.max_stocks),
            "max_crypto": int(self.max_crypto),
            "max_open_positions_total": int(self.max_open_positions_total),
            "cooldown_after_close_seconds": int(self.cooldown_after_close_seconds),
            "throughput_expansion_enabled": bool(self.throughput_expansion_enabled),
            "soft_candidate_expansion_enabled": bool(self.soft_candidate_expansion_enabled),
            "paper_entry_threshold_relief_points": round(float(self.paper_entry_threshold_relief_points), 3),
        }

    def run_cycle(self):
        if not self._enabled:
            safety = self._alpaca_safety_snapshot()
            out = {
                "ok": True,
                "autopilot_enabled": False,
                "orders_submitted": 0,
                "positions_closed": 0,
                "cycle_reason": "disabled",
            }
            trace = {
                "paper_worker_running": bool(self._thread and self._thread.is_alive()),
                **safety,
                "candidates_seen": 0,
                "eligible_candidates": 0,
                "selected_candidates": 0,
                "orders_attempted": 0,
                "orders_submitted": 0,
                "orders_rejected": 0,
                "final_blocker_reason": "paper_autopilot_disabled",
                "per_candidate_decision_trace": [],
                "last_alpaca_error_sanitized": "",
                "live_trading_changed": False,
                "secrets_exposed": False,
            }
            self._runtime_state["last_cycle_utc"] = _now_iso()
            self._runtime_state["last_cycle_summary"] = out
            self._runtime_state["last_execution_trace"] = trace
            return out

        with self._cycle_lock:
            opened = 0
            closed = 0
            skipped = 0
            eligible_count = 0
            selected_count = 0
            orders_attempted = 0
            orders_rejected = 0
            final_blocker_reason = ""
            last_alpaca_error = ""
            portfolio_risk_proof_present = False
            portfolio_risk_score_used = None
            portfolio_risk_label_used = ""
            portfolio_risk_preflight_reason = ""
            decision_trace: list[dict[str, Any]] = []
            safety = self._alpaca_safety_snapshot()
            open_rows_initial = self._fetch_open_positions()
            internal_open_syms = {str(r.get("symbol") or "").upper().strip() for r in open_rows_initial}
            broker_snapshot = self._broker_open_symbols_snapshot()
            broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
            broker_reconciliation_active = bool(broker_snapshot.get("broker_reconciliation_active", False))
            broker_positions_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
            stale_internal_positions = sorted(x for x in internal_open_syms if x and x not in broker_open_syms)
            stale_internal_positions_count = int(len(stale_internal_positions))
            # When broker reconciliation is active and fetch succeeded, broker positions are the
            # source of truth for duplicate suppression on paper order submission.
            if broker_reconciliation_active and broker_positions_fetch_ok:
                open_syms = set(broker_open_syms)
                capacity_source = "broker"
            else:
                open_syms = set(internal_open_syms)
                capacity_source = "internal"

            open_rows = list(open_rows_initial)
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

            if capacity_source == "broker":
                broker_stock_open = int(len([s for s in broker_open_syms if s]))
                broker_crypto_open = 0
                effective_capacity_count = broker_stock_open + broker_crypto_open
                stock_capacity = max(0, self.max_stocks - broker_stock_open)
                crypto_capacity = max(0, self.max_crypto - broker_crypto_open)
                total_capacity = max(0, self.max_open_positions_total - effective_capacity_count)
                stale_internal_positions_ignored_for_broker_capacity = bool(stale_internal_positions_count > 0)
            else:
                counts = self._count_open_positions()
                internal_stock_open = int(counts.get("stock", 0))
                internal_crypto_open = int(counts.get("crypto", 0))
                effective_capacity_count = internal_stock_open + internal_crypto_open
                stock_capacity = max(0, self.max_stocks - internal_stock_open)
                crypto_capacity = max(0, self.max_crypto - internal_crypto_open)
                total_capacity = max(0, self.max_open_positions_total - effective_capacity_count)
                stale_internal_positions_ignored_for_broker_capacity = False
            stock_capacity_reason = "stock_capacity_available"
            candidates = self._collect_candidate_rows()
            allocation_status = {}
            if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "status"):
                try:
                    allocation_status = dict(self.paper_opportunity_allocator.status(rows=candidates) or {})
                except Exception:
                    allocation_status = {}
            session_status = {}
            if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "status"):
                try:
                    session_status = dict(
                        self.market_session_timing_suite.status(
                            broker_ready=bool(safety.get("broker_execution_ready") or safety.get("broker_execution_enabled")),
                            open_orders_count=int(_to_float(safety.get("open_orders_count"), 0.0)),
                        )
                        or {}
                    )
                except Exception:
                    session_status = {}
            for row in candidates:
                if opened >= self.max_new_positions_per_cycle:
                    final_blocker_reason = final_blocker_reason or "max_new_positions_per_cycle_reached"
                    break
                if total_capacity <= 0:
                    final_blocker_reason = final_blocker_reason or "max_concurrent_positions_reached"
                    break
                symbol = str(row.get("symbol") or "").upper().strip()
                asset = _norm_asset(row.get("asset_type") or "stock")
                if not symbol or symbol in open_syms:
                    skipped += 1
                    reason = "missing_symbol" if not symbol else "duplicate_active_position"
                    duplicate_source = "none"
                    if symbol:
                        in_internal = symbol in internal_open_syms
                        in_broker = symbol in broker_open_syms
                        if in_internal and in_broker:
                            duplicate_source = "both"
                        elif in_internal:
                            duplicate_source = "internal"
                        elif in_broker:
                            duplicate_source = "broker"
                    decision_trace.append({
                        "symbol": symbol,
                        "asset_type": asset,
                        "eligible": False,
                        "selected": False,
                        "decision_reason": reason,
                        "duplicate_source": duplicate_source,
                        "broker_reconciliation_active": broker_reconciliation_active,
                    })
                    final_blocker_reason = reason
                    continue
                if self._cooldown_active(symbol):
                    skipped += 1
                    decision_trace.append({
                        "symbol": symbol,
                        "asset_type": asset,
                        "eligible": False,
                        "selected": False,
                        "decision_reason": "cooldown_active",
                    })
                    final_blocker_reason = "cooldown_active"
                    continue
                if asset == "stock" and stock_capacity <= 0:
                    final_blocker_reason = "stock_capacity_reached"
                    stock_capacity_reason = "stock_capacity_reached"
                    continue
                if asset == "crypto" and crypto_capacity <= 0:
                    final_blocker_reason = "crypto_capacity_reached"
                    continue

                row_trace, allowed, reason, gate_meta = self._candidate_trace_row(
                    row,
                    open_syms=open_syms,
                    stock_capacity=stock_capacity,
                    crypto_capacity=crypto_capacity,
                    total_capacity=total_capacity,
                    selected_so_far=selected_count,
                    internal_open_syms=internal_open_syms,
                    broker_open_syms=broker_open_syms,
                    broker_reconciliation_active=broker_reconciliation_active,
                )
                if not allowed:
                    skipped += 1
                    row_trace["selected"] = False
                    row_trace["order_attempted"] = False
                    decision_trace.append(row_trace)
                    final_blocker_reason = str(reason)
                    continue

                eligible_count += 1
                selected_count += 1
                orders_attempted += 1
                row_trace["selected"] = True
                row_trace["order_attempted"] = True
                gate_meta = dict(gate_meta or {})
                gate_meta["paper_autopilot_limits_ok"] = True
                gate_meta["paper_autopilot_limits_reason"] = "max_new_max_open_and_capacity_passed"
                opened_row = self._open_position_from_row(
                    row,
                    source_bucket=f"paper_autopilot_{reason}",
                    gate_meta=gate_meta,
                )
                row_trace["portfolio_risk_proof_present"] = bool(opened_row.get("portfolio_risk_proof_present", False))
                row_trace["portfolio_risk_score_used"] = opened_row.get("portfolio_risk_score_used")
                row_trace["portfolio_risk_label_used"] = str(opened_row.get("portfolio_risk_label_used") or "")
                row_trace["portfolio_risk_preflight_reason"] = str(opened_row.get("portfolio_risk_preflight_reason") or "")
                row_trace["paper_autopilot_limits_ok"] = bool(opened_row.get("paper_autopilot_limits_ok", True))
                row_trace["paper_autopilot_limits_reason"] = str(opened_row.get("paper_autopilot_limits_reason") or "")
                row_trace["market_session_mode"] = str(opened_row.get("market_session_mode") or row_trace.get("market_session_mode") or "")
                row_trace["paper_order_submission_allowed"] = bool(opened_row.get("paper_order_submission_allowed", row_trace.get("paper_order_submission_allowed", False)))
                row_trace["execution_confirmation_required"] = bool(opened_row.get("execution_confirmation_required", row_trace.get("execution_confirmation_required", True)))
                row_trace["open_confirmation_score"] = round(_to_float(opened_row.get("open_confirmation_score"), _to_float(row_trace.get("open_confirmation_score"), 0.0)), 2)
                row_trace["open_confirmation_label"] = str(opened_row.get("open_confirmation_label") or row_trace.get("open_confirmation_label") or "")
                row_trace["open_confirmation_reason"] = str(opened_row.get("open_confirmation_reason") or row_trace.get("open_confirmation_reason") or "")
                row_trace["execution_intent_status"] = str(opened_row.get("execution_intent_status") or row_trace.get("execution_intent_status") or "")
                row_trace["defer_until_market_confirmation"] = bool(opened_row.get("defer_until_market_confirmation", row_trace.get("defer_until_market_confirmation", False)))
                row_trace["requires_open_confirmation"] = bool(opened_row.get("requires_open_confirmation", row_trace.get("requires_open_confirmation", True)))
                row_trace["weekend_watchlist_candidate"] = bool(opened_row.get("weekend_watchlist_candidate", row_trace.get("weekend_watchlist_candidate", False)))
                row_trace["replay_candidate_snapshot_saved"] = bool(opened_row.get("replay_candidate_snapshot_saved", False))
                row_trace["replay_learning_ready"] = bool(opened_row.get("replay_learning_ready", False))
                row_trace["session_timing_outcome_tracking_ready"] = bool(opened_row.get("session_timing_outcome_tracking_ready", False))
                if row_trace["portfolio_risk_proof_present"]:
                    portfolio_risk_proof_present = True
                if row_trace["portfolio_risk_score_used"] is not None:
                    portfolio_risk_score_used = row_trace["portfolio_risk_score_used"]
                if row_trace["portfolio_risk_label_used"]:
                    portfolio_risk_label_used = row_trace["portfolio_risk_label_used"]
                if row_trace["portfolio_risk_preflight_reason"]:
                    portfolio_risk_preflight_reason = row_trace["portfolio_risk_preflight_reason"]
                if opened_row.get("ok"):
                    opened += 1
                    row_trace["order_submitted"] = True
                    row_trace["order_result"] = "submitted"
                    open_syms.add(symbol)
                    internal_open_syms.add(symbol)
                    if broker_reconciliation_active:
                        broker_open_syms.add(symbol)
                    total_capacity = max(0, total_capacity - 1)
                    if asset == "stock":
                        stock_capacity = max(0, stock_capacity - 1)
                    else:
                        crypto_capacity = max(0, crypto_capacity - 1)
                else:
                    skipped += 1
                    orders_rejected += 1
                    row_trace["order_submitted"] = False
                    row_trace["order_result"] = "rejected"
                    row_trace["order_rejection_reason"] = str(opened_row.get("error") or "paper_order_rejected")[:160]
                    broker_error = self._sanitize_broker_error(opened_row)
                    if broker_error:
                        row_trace["broker_error_sanitized"] = broker_error
                        last_alpaca_error = broker_error
                    final_blocker_reason = broker_error or str(opened_row.get("error") or "paper_order_rejected")
                decision_trace.append(row_trace)

            if not final_blocker_reason:
                if opened > 0:
                    final_blocker_reason = "orders_submitted"
                elif not candidates:
                    final_blocker_reason = "no_candidates_available"
                elif eligible_count <= 0:
                    final_blocker_reason = "no_eligible_candidates"
                elif orders_attempted <= 0:
                    final_blocker_reason = "no_orders_attempted"
                else:
                    final_blocker_reason = "orders_not_submitted"
            if opened <= 0 and not bool(session_status.get("paper_order_submission_allowed", False)):
                final_blocker_reason = "session_order_submission_blocked"
            out = {
                "ok": True,
                "autopilot_enabled": True,
                "orders_submitted": int(opened),
                "orders_attempted": int(orders_attempted),
                "orders_rejected": int(orders_rejected),
                "positions_closed": int(closed),
                "positions_skipped": int(skipped),
                "candidates_seen": int(len(candidates)),
                "paper_opportunity_allocation": allocation_status,
                "market_session_execution_timing": session_status,
                "market_session_mode": str(session_status.get("market_session_mode") or ""),
                "paper_order_submission_allowed": bool(session_status.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": bool(session_status.get("execution_confirmation_required", True)),
                "execution_intent_status": str(session_status.get("execution_intent_status") or ""),
                "defer_until_market_confirmation": bool(session_status.get("defer_until_market_confirmation", False)),
                "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
                "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
                "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
                "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
                "eligible_candidates": int(eligible_count),
                "selected_candidates": int(selected_count),
                "final_blocker_reason": str(final_blocker_reason)[:180],
                "last_alpaca_error_sanitized": str(last_alpaca_error)[:180],
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": portfolio_risk_score_used,
                "portfolio_risk_label_used": str(portfolio_risk_label_used),
                "portfolio_risk_preflight_reason": str(portfolio_risk_preflight_reason),
                "internal_open_positions_count": int(len([s for s in internal_open_syms if s])),
                "broker_open_positions_count": int(len([s for s in broker_open_syms if s])),
                "effective_broker_capacity_count": int(len([s for s in broker_open_syms if s])),
                "stale_internal_positions_count": stale_internal_positions_count,
                "stale_internal_positions": stale_internal_positions[:32],
                "capacity_source": str(capacity_source),
                "effective_capacity_count": int(effective_capacity_count),
                "stock_capacity_limit": int(self.max_stocks),
                "stock_capacity_reason": str(stock_capacity_reason),
                "stale_internal_positions_ignored_for_broker_capacity": bool(stale_internal_positions_ignored_for_broker_capacity),
                "broker_reconciliation_active": broker_reconciliation_active,
                "broker_positions_fetch_ok": broker_positions_fetch_ok,
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
                "cycle_timestamp": _now_iso(),
            }
            trace = {
                "paper_worker_running": bool(self._thread and self._thread.is_alive()),
                **safety,
                "candidates_seen": int(len(candidates)),
                "paper_opportunity_allocation": allocation_status,
                "market_session_execution_timing": session_status,
                "market_session_mode": str(session_status.get("market_session_mode") or ""),
                "paper_order_submission_allowed": bool(session_status.get("paper_order_submission_allowed", False)),
                "execution_confirmation_required": bool(session_status.get("execution_confirmation_required", True)),
                "execution_intent_status": str(session_status.get("execution_intent_status") or ""),
                "defer_until_market_confirmation": bool(session_status.get("defer_until_market_confirmation", False)),
                "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
                "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
                "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
                "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
                "eligible_candidates": int(eligible_count),
                "selected_candidates": int(selected_count),
                "orders_attempted": int(orders_attempted),
                "orders_submitted": int(opened),
                "orders_rejected": int(orders_rejected),
                "final_blocker_reason": str(final_blocker_reason)[:180],
                "per_candidate_decision_trace": decision_trace[:12],
                "last_alpaca_error_sanitized": str(last_alpaca_error)[:180],
                "portfolio_risk_proof_present": bool(portfolio_risk_proof_present),
                "portfolio_risk_score_used": portfolio_risk_score_used,
                "portfolio_risk_label_used": str(portfolio_risk_label_used),
                "portfolio_risk_preflight_reason": str(portfolio_risk_preflight_reason),
                "internal_open_positions_count": int(len([s for s in internal_open_syms if s])),
                "broker_open_positions_count": int(len([s for s in broker_open_syms if s])),
                "effective_broker_capacity_count": int(len([s for s in broker_open_syms if s])),
                "stale_internal_positions_count": stale_internal_positions_count,
                "stale_internal_positions": stale_internal_positions[:32],
                "capacity_source": str(capacity_source),
                "effective_capacity_count": int(effective_capacity_count),
                "stock_capacity_limit": int(self.max_stocks),
                "stock_capacity_reason": str(stock_capacity_reason),
                "stale_internal_positions_ignored_for_broker_capacity": bool(stale_internal_positions_ignored_for_broker_capacity),
                "broker_reconciliation_active": broker_reconciliation_active,
                "broker_positions_fetch_ok": broker_positions_fetch_ok,
                "broker_positions_error_sanitized": str(broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
                "live_trading_changed": False,
                "secrets_exposed": False,
            }
            self._runtime_state["last_cycle_utc"] = out["cycle_timestamp"]
            self._runtime_state["last_cycle_summary"] = dict(out)
            self._runtime_state["last_execution_trace"] = dict(trace)
            self._runtime_state["last_error"] = ""
            self._save_state_file()
            return out

    def execution_trace(self, max_candidates: int = 12) -> dict[str, Any]:
        status = self.status()
        last_trace = dict(self._runtime_state.get("last_execution_trace") or {})
        candidates = self._collect_candidate_rows()
        allocation_status = {}
        if self.paper_opportunity_allocator is not None and hasattr(self.paper_opportunity_allocator, "status"):
            try:
                allocation_status = dict(self.paper_opportunity_allocator.status(rows=candidates) or {})
            except Exception:
                allocation_status = {}
        session_status = {}
        if self.market_session_timing_suite is not None and hasattr(self.market_session_timing_suite, "status"):
            try:
                session_status = dict(
                    self.market_session_timing_suite.status(
                        broker_ready=bool(self._alpaca_paper_broker_enabled()),
                        open_orders_count=0,
                    )
                    or {}
                )
            except Exception:
                session_status = {}
        capacities = self._current_execution_capacities()
        internal_open_syms = set(capacities.get("open_symbols") or set())
        broker_snapshot = self._broker_open_symbols_snapshot()
        broker_open_syms = set(broker_snapshot.get("broker_open_symbols") or set())
        broker_reconciliation_active = bool(broker_snapshot.get("broker_reconciliation_active", False))
        broker_positions_fetch_ok = bool(broker_snapshot.get("broker_positions_fetch_ok", False))
        stale_internal_positions = sorted(x for x in internal_open_syms if x and x not in broker_open_syms)
        if broker_reconciliation_active and broker_positions_fetch_ok:
            open_syms = set(broker_open_syms)
            capacity_source = "broker"
            effective_stock_open = int(len([s for s in broker_open_syms if s]))
            effective_crypto_open = 0
        else:
            open_syms = set(internal_open_syms)
            capacity_source = "internal"
            effective_stock_open = int(capacities.get("open_positions_stock", 0))
            effective_crypto_open = int(capacities.get("open_positions_crypto", 0))
        effective_capacity_count = int(effective_stock_open + effective_crypto_open)
        stock_capacity = max(0, int(self.max_stocks) - int(effective_stock_open))
        crypto_capacity = max(0, int(self.max_crypto) - int(effective_crypto_open))
        total_capacity = max(0, int(self.max_open_positions_total) - int(effective_capacity_count))
        decision_rows: list[dict[str, Any]] = []
        eligible = 0
        selected = 0
        for row in candidates[: max(1, min(30, int(max_candidates or 12)))]:
            trace, allowed, _reason, _gate_meta = self._candidate_trace_row(
                row,
                open_syms=open_syms,
                stock_capacity=stock_capacity,
                crypto_capacity=crypto_capacity,
                total_capacity=total_capacity,
                selected_so_far=selected,
                internal_open_syms=internal_open_syms,
                broker_open_syms=broker_open_syms,
                broker_reconciliation_active=broker_reconciliation_active,
            )
            if allowed:
                eligible += 1
                if selected < self.max_new_positions_per_cycle and total_capacity > 0:
                    selected += 1
                    trace["selected"] = True
                else:
                    trace["selected"] = False
            else:
                trace["selected"] = False
            decision_rows.append(trace)
        safety = self._alpaca_safety_snapshot()
        final_blocker = str(last_trace.get("final_blocker_reason") or "")
        if not final_blocker:
            if not self._enabled:
                final_blocker = "paper_autopilot_disabled"
            elif not candidates:
                final_blocker = "no_candidates_available"
            elif eligible <= 0:
                final_blocker = "no_eligible_candidates"
            elif not safety.get("broker_execution_enabled"):
                final_blocker = "alpaca_paper_broker_disabled"
            else:
                final_blocker = "awaiting_next_worker_cycle"
        session_allows_orders = bool(
            last_trace.get(
                "paper_order_submission_allowed",
                session_status.get("paper_order_submission_allowed", False),
            )
        )
        if not session_allows_orders and int(last_trace.get("orders_submitted", 0)) <= 0:
            final_blocker = "session_order_submission_blocked"
        return {
            "enabled": True,
            "mode": "paper_only",
            "paper_worker_running": bool(self._thread and self._thread.is_alive()),
            "autopilot_enabled": bool(self._enabled),
            **safety,
            "open_positions_count": int(status.get("open_positions_count", capacities.get("open_positions_count", 0))),
            "max_new_positions_per_cycle": int(self.max_new_positions_per_cycle),
            "max_open_positions_total": int(self.max_open_positions_total),
            "candidates_seen": int(len(candidates)),
            "paper_opportunity_allocation": allocation_status,
            "market_session_execution_timing": session_status,
            "market_session_mode": str(last_trace.get("market_session_mode") or session_status.get("market_session_mode") or ""),
            "paper_order_submission_allowed": bool(last_trace.get("paper_order_submission_allowed", session_status.get("paper_order_submission_allowed", False))),
            "execution_confirmation_required": bool(last_trace.get("execution_confirmation_required", session_status.get("execution_confirmation_required", True))),
            "execution_intent_status": str(last_trace.get("execution_intent_status") or session_status.get("execution_intent_status") or ""),
            "defer_until_market_confirmation": bool(last_trace.get("defer_until_market_confirmation", session_status.get("defer_until_market_confirmation", False))),
            "allocation_lane_counts": dict(allocation_status.get("lane_counts") or {}),
            "valid_exploration_candidates": int(_to_float(allocation_status.get("valid_exploration_candidates"), 0.0)),
            "high_upside_candidates_approved": int(_to_float(allocation_status.get("high_upside_candidates_approved"), 0.0)),
            "high_upside_candidates_rejected": int(_to_float(allocation_status.get("high_upside_candidates_rejected"), 0.0)),
            "eligible_candidates": int(last_trace.get("eligible_candidates", eligible)),
            "selected_candidates": int(last_trace.get("selected_candidates", selected)),
            "orders_attempted": int(last_trace.get("orders_attempted", 0)),
            "orders_submitted": int(last_trace.get("orders_submitted", 0)),
            "orders_rejected": int(last_trace.get("orders_rejected", 0)),
            "final_blocker_reason": final_blocker[:180],
            "per_candidate_decision_trace": list(last_trace.get("per_candidate_decision_trace") or decision_rows)[:max_candidates],
            "last_alpaca_error_sanitized": str(last_trace.get("last_alpaca_error_sanitized") or "")[:180],
            "portfolio_risk_proof_present": bool(last_trace.get("portfolio_risk_proof_present", False)),
            "portfolio_risk_score_used": last_trace.get("portfolio_risk_score_used"),
            "portfolio_risk_label_used": str(last_trace.get("portfolio_risk_label_used") or ""),
            "portfolio_risk_preflight_reason": str(last_trace.get("portfolio_risk_preflight_reason") or ""),
            "internal_open_positions_count": int(last_trace.get("internal_open_positions_count", len([s for s in internal_open_syms if s]))),
            "broker_open_positions_count": int(last_trace.get("broker_open_positions_count", len([s for s in broker_open_syms if s]))),
            "effective_broker_capacity_count": int(last_trace.get("effective_broker_capacity_count", len([s for s in broker_open_syms if s]))),
            "stale_internal_positions_count": int(last_trace.get("stale_internal_positions_count", len(stale_internal_positions))),
            "stale_internal_positions": list(last_trace.get("stale_internal_positions") or sorted(x for x in internal_open_syms if x and x not in broker_open_syms))[:32],
            "capacity_source": str(last_trace.get("capacity_source") or capacity_source),
            "effective_capacity_count": int(last_trace.get("effective_capacity_count", effective_capacity_count)),
            "stock_capacity_limit": int(last_trace.get("stock_capacity_limit", self.max_stocks)),
            "stock_capacity_reason": str(last_trace.get("stock_capacity_reason") or ""),
            "stale_internal_positions_ignored_for_broker_capacity": bool(
                last_trace.get(
                    "stale_internal_positions_ignored_for_broker_capacity",
                    bool(capacity_source == "broker" and len(stale_internal_positions) > 0),
                )
            ),
            "broker_reconciliation_active": bool(last_trace.get("broker_reconciliation_active", broker_reconciliation_active)),
            "broker_positions_fetch_ok": bool(last_trace.get("broker_positions_fetch_ok", broker_positions_fetch_ok)),
            "broker_positions_error_sanitized": str(last_trace.get("broker_positions_error_sanitized") or broker_snapshot.get("broker_positions_error_sanitized") or "")[:180],
            "last_cycle_utc": str(status.get("last_cycle_utc") or ""),
            "last_cycle_summary": dict(status.get("last_cycle_summary") or {}),
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "live_trading_changed": False,
            "secrets_exposed": False,
            "generated_at": _now_iso(),
        }

    def paper_positions(self):
        open_rows = self._fetch_open_positions()
        out: list[dict[str, Any]] = []
        for row in open_rows:
            item = dict(row)
            item["entry_metadata"] = _safe_json_load(row.get("row_json"))
            item["lifecycle_notes"] = _safe_json_load(row.get("lifecycle_notes"))
            out.append(item)
        return out
