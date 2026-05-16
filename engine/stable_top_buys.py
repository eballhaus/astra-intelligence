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
        quality = _f(row.get("buy_quality_score"), _f(row.get("trade_quality_score"), _f(row.get("grade_percent"), 0.0)))
        confidence = _f(row.get("confidence"), _f(row.get("predicted_win_probability"), 0.0))
        conv10 = _f(row.get("rolling_conviction_10r"), _f(row.get("conviction_display_score"), quality))
        conv5 = _f(row.get("rolling_conviction_5r"), conv10)
        conv20 = _f(row.get("rolling_conviction_20r"), conv10)
        entry_v3 = _f(row.get("entry_quality_v3_score"), _f(row.get("entry_quality_v2_score"), _f(row.get("entry_quality_score"), 50.0)))
        psychology = _f(row.get("psychology_score"), 60.0)
        consensus = _f(row.get("multi_brain_score"), 50.0)
        grade_bonus = {"A": 5.0, "B": 2.5, "C": 0.0, "D": -4.0, "F": -8.0}.get(str(row.get("grade") or "").upper()[:1], 0.0)
        score = (
            conv10 * 0.26
            + conv5 * 0.10
            + conv20 * 0.12
            + quality * 0.18
            + confidence * 0.12
            + entry_v3 * 0.10
            + psychology * 0.05
            + consensus * 0.07
            + grade_bonus
        )
        return round(max(0.0, min(110.0, score)), 3)

    def _normalize_display_fields(self, row: dict[str, Any], *, score: float, state: str, first_seen: float, age: float, retained: bool, replacement_reason: str = "") -> dict[str, Any]:
        out = dict(row or {})
        price = _first_present(out, ("current_price", "price", "live_price", "last_price", "close", "mark_price"))
        if price is not None:
            out["current_price"] = price
            out["price"] = _first_present(out, ("price", "current_price")) or price
        stop = _first_present(out, ("stop_loss", "stop", "stop_price", "invalidation_level"))
        if stop is not None:
            out["stop_loss"] = stop
        out["rolling_conviction_5r"] = _first_present(out, ("rolling_conviction_5r", "conviction_5r", "five_r_conviction"))
        out["rolling_conviction_10r"] = _first_present(out, ("rolling_conviction_10r", "conviction_display_score", "conviction_10r", "ten_r_conviction"))
        out["rolling_conviction_20r"] = _first_present(out, ("rolling_conviction_20r", "conviction_20r", "twenty_r_conviction"))
        out["expected_move"] = _first_present(out, ("expected_move", "profit_prediction_usd", "expected_move_dollars", "expected_move_usd", "predicted_profit_dollars"))
        out["expected_move_percent"] = _first_present(out, ("expected_move_percent", "expected_move_pct", "profit_prediction_pct", "predicted_return_pct"))
        out["stable_layer_state"] = state
        out["stable_display_state"] = state
        out["stable_retained"] = bool(retained)
        out["stable_since"] = datetime.fromtimestamp(first_seen, UTC).isoformat().replace("+00:00", "Z")
        out["stable_first_seen_ts"] = first_seen
        out["stable_last_seen_ts"] = time.time()
        out["stable_age_seconds"] = round(age, 2)
        out["stability_score"] = score
        out["stable_composite_score"] = score
        out["astra_composite_score"] = round(max(0.0, min(100.0, score)), 3)
        out["replacement_reason"] = replacement_reason
        out["pending_challenger"] = False
        return out

    def _hard_invalid_reason(self, row: dict[str, Any]) -> str:
        if not row:
            return "missing_candidate"
        if row.get("valid_quote") is False or row.get("trusted_quote_for_buys") is False:
            return "invalid_or_untrusted_quote"
        confidence = _f(row.get("confidence"), 0.0)
        if confidence and confidence < self.hard_confidence_floor:
            return "confidence_below_hard_floor"
        state = str(row.get("canonical_final_state") or row.get("top_buy_action") or row.get("prediction") or row.get("action") or "").lower()
        if any(token in state for token in ("avoid", "blocked", "reject")):
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
        if score < self.min_quality_floor + 8:
            return "needs_confirmation"
        if age_seconds < self.min_hold_seconds and score < self.min_quality_floor + 14:
            return "watch_closely"
        if str(row.get("recommended_entry_mode") or "").lower() in {"paper_only", "wait_for_confirmation"}:
            return "paper_only"
        return "stable"

    def select(self, raw_payload: dict[str, Any] | None, *, buy_mode: str = "balanced") -> dict[str, Any]:
        now = time.time()
        payload = dict(raw_payload or {})
        raw_rows = list(((payload.get("stocks") or {}).get("final") or []) or [])
        qualified = list(((payload.get("stocks") or {}).get("qualified") or []) or [])
        watchlist = list(((payload.get("stocks") or {}).get("watchlist") or []) or [])
        candidates_by_symbol: dict[str, dict[str, Any]] = {}
        for row in raw_rows + qualified + watchlist:
            if not isinstance(row, dict):
                continue
            sym = _symbol(row)
            if not sym:
                continue
            enriched = dict(row)
            enriched["stable_composite_score"] = self._score(enriched)
            old = candidates_by_symbol.get(sym)
            if not old or _f(enriched.get("stable_composite_score"), 0.0) > _f(old.get("stable_composite_score"), 0.0):
                candidates_by_symbol[sym] = enriched
        candidates = sorted(candidates_by_symbol.values(), key=lambda r: _f(r.get("stable_composite_score"), 0.0), reverse=True)
        state = self._load()
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
            current = candidates_by_symbol.get(sym, prior)
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

        stable = sorted(stable, key=lambda r: _f(r.get("stable_composite_score"), 0.0), reverse=True)[:6]
        state_out = {
            "enabled": True,
            "version": VERSION,
            "mode": "stable_top_6_presentation_layer",
            "local_only": True,
            "writes_files": True,
            "api_calls_used": 0,
            "stable_top_buys_v1": True,
            "stable_top_6": stable,
            "raw_candidates_count": len(candidates),
            "stable_count": len(stable),
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
            "adaptive_policy_mode": "shadow_only",
            "live_trading_changed": False,
            "rankings_top_buys_strategy_changed": False,
            "next_recommended_action": "display_stable_top_6_and_allow_raw_top_buys_to_continue_running_independently",
            "challenger_counts": {k: v for k, v in challenger_counts.items() if v > 0},
        }
        self._write(state_out)
        return dict(state_out)
