from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_JSONL_ROWS = 2_000
MAX_TAIL_BYTES = 4_000_000
STYLES = ("scalp", "day_trade", "swing_trade")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _parse_dt(value: Any) -> datetime | None:
    raw = _safe_text(value)
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _safe_json_load(raw: Any) -> dict[str, Any]:
    try:
        if isinstance(raw, str) and raw:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(raw, dict):
            return dict(raw)
    except Exception:
        pass
    return {}


def _tail_jsonl(path: str, max_rows: int = MAX_JSONL_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
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


def _style_from_payload(row: dict[str, Any]) -> str:
    row_json = _safe_json_load(row.get("row_json"))
    notes = _safe_json_load(row.get("lifecycle_notes"))
    for source in (row, row_json, notes):
        raw = _safe_text(
            source.get("trade_horizon_style")
            or source.get("best_horizon_style")
            or source.get("paper_horizon_style")
            or source.get("mode")
            or source.get("paper_mode")
        ).lower().replace("-", "_").replace(" ", "_")
        if raw in STYLES:
            return raw
        if raw in {"day", "intraday"}:
            return "day_trade"
        if raw == "swing":
            return "swing_trade"
    hold_seconds = _to_float(row.get("hold_seconds"), 0.0)
    if hold_seconds > 0:
        if hold_seconds < 3600:
            return "scalp"
        if hold_seconds <= 7 * 3600:
            return "day_trade"
        return "swing_trade"
    source_bucket = _safe_text(row.get("source_bucket")).lower()
    if "scalp" in source_bucket:
        return "scalp"
    if "swing" in source_bucket:
        return "swing_trade"
    return "day_trade"


def _is_today(value: Any, today: str) -> bool:
    dt = _parse_dt(value)
    return bool(dt and dt.date().isoformat() == today)


class HorizonPerformanceDashboardV1:
    """Read-only scalp/day/swing paper performance dashboard.

    Uses bounded local paper/lifecycle rows only. It does not alter exits, orders,
    rankings, or broker behavior.
    """

    def __init__(self, state_dir: str = "state", db_path: str | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.db_path = str(db_path or os.path.join(self.state_dir, "ai_trading_memory.db"))
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")

    def _paper_rows(self, limit: int = 1200) -> list[dict[str, Any]]:
        if not os.path.exists(self.db_path):
            return []
        try:
            conn = sqlite3.connect(self.db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=1500")
            try:
                rows = conn.execute(
                    """
                    SELECT * FROM paper_positions
                    ORDER BY COALESCE(updated_at, created_at, entry_timestamp) DESC
                    LIMIT ?
                    """,
                    (max(1, min(2000, int(limit))),),
                ).fetchall()
            finally:
                conn.close()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _lifecycle_rows(self) -> list[dict[str, Any]]:
        return _tail_jsonl(self.lifecycle_path)

    def _quality_from_lifecycle(self, symbol: str, style: str, key: str) -> float:
        rows = [r for r in self._lifecycle_rows() if _safe_text(r.get("symbol")).upper() == symbol.upper()]
        vals = []
        for row in rows[-200:]:
            if _style_from_payload(row) != style:
                continue
            v = _to_float(row.get(key), -1.0)
            if v >= 0:
                vals.append(v)
        return mean(vals) if vals else 0.0

    def _metrics_for_style(self, style: str, rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
        style_rows = [r for r in rows if _style_from_payload(r) == style]
        open_rows = [r for r in style_rows if _safe_text(r.get("status")).upper() == "OPEN"]
        closed_rows = [r for r in style_rows if _safe_text(r.get("status")).upper() == "CLOSED"]
        entries_today = [r for r in style_rows if _is_today(r.get("entry_timestamp") or r.get("created_at"), today)]
        exits_today = [r for r in closed_rows if _is_today(r.get("exit_timestamp") or r.get("updated_at"), today)]
        returns = [_to_float(r.get("return_percent"), 0.0) for r in closed_rows]
        wins = [v for v in returns if v > 0]
        losses = [v for v in returns if v < 0]
        hold_hours = [_to_float(r.get("hold_seconds"), 0.0) / 3600.0 for r in closed_rows if _to_float(r.get("hold_seconds"), 0.0) > 0]
        symbol_perf: dict[str, list[float]] = {}
        setup_perf: dict[str, list[float]] = {}
        rejected_orders = 0
        partial_fills = 0
        natural_exit_count = 0
        forced_exit_count = 0
        slippage_vals = []
        fill_quality_vals = []
        entry_quality_vals = []
        exit_quality_vals = []
        for row in style_rows:
            row_json = _safe_json_load(row.get("row_json"))
            notes = _safe_json_load(row.get("lifecycle_notes"))
            sym = _safe_text(row.get("symbol")).upper()
            setup = _safe_text(row_json.get("setup_type") or notes.get("entry_setup_type"), "unknown")
            ret = _to_float(row.get("return_percent"), 0.0)
            if _safe_text(row.get("status")).upper() == "CLOSED":
                symbol_perf.setdefault(sym or "UNKNOWN", []).append(ret)
                setup_perf.setdefault(setup, []).append(ret)
                reason = _safe_text(notes.get("exit_reason") or row.get("exit_reason")).lower()
                if "forced_early" in reason or "artificial" in reason:
                    forced_exit_count += 1
                else:
                    natural_exit_count += 1
            if "reject" in _safe_text(notes.get("broker_order_status") or row_json.get("broker_order_status")).lower():
                rejected_orders += 1
            if "partial" in _safe_text(notes.get("broker_fill_status") or row_json.get("broker_fill_status")).lower():
                partial_fills += 1
            slip = _to_float(notes.get("slippage_bps") or row_json.get("slippage_bps"), float("nan"))
            if slip == slip:
                slippage_vals.append(slip)
            fillq = _to_float(notes.get("broker_fill_quality") or row_json.get("broker_fill_quality"), float("nan"))
            if fillq == fillq:
                fill_quality_vals.append(fillq)
            eq = _to_float(row_json.get("entry_quality_score") or notes.get("entry_quality_score"), float("nan"))
            if eq == eq:
                entry_quality_vals.append(eq)
            xq = _to_float(notes.get("exit_quality_score") or row_json.get("exit_quality_score"), float("nan"))
            if xq == xq:
                exit_quality_vals.append(xq)
        best_symbol = max(symbol_perf.items(), key=lambda kv: mean(kv[1]))[0] if symbol_perf else "n/a"
        weakest_symbol = min(symbol_perf.items(), key=lambda kv: mean(kv[1]))[0] if symbol_perf else "n/a"
        best_setup = max(setup_perf.items(), key=lambda kv: mean(kv[1]))[0] if setup_perf else "n/a"
        weakest_setup = min(setup_perf.items(), key=lambda kv: mean(kv[1]))[0] if setup_perf else "n/a"
        profit_factor = (sum(wins) / abs(sum(losses))) if losses else (sum(wins) if wins else 0.0)
        avg_return = mean(returns) if returns else 0.0
        win_rate = (len(wins) / len(returns) * 100.0) if returns else 0.0
        return {
            "entries_today": len(entries_today),
            "exits_today": len(exits_today),
            "open_positions": len(open_rows),
            "win_rate": round(win_rate, 3),
            "average_return_pct": round(avg_return, 4),
            "profit_factor": round(profit_factor, 4),
            "average_hold_time": round(mean(hold_hours), 3) if hold_hours else 0.0,
            "average_hold_time_hours": round(mean(hold_hours), 3) if hold_hours else 0.0,
            "entry_quality": round(mean(entry_quality_vals), 3) if entry_quality_vals else 0.0,
            "exit_quality": round(mean(exit_quality_vals), 3) if exit_quality_vals else 0.0,
            "best_symbol": best_symbol,
            "weakest_symbol": weakest_symbol,
            "best_setup": best_setup,
            "weakest_setup": weakest_setup,
            "broker_fill_quality": round(mean(fill_quality_vals), 3) if fill_quality_vals else 100.0,
            "average_slippage_bps": round(mean(slippage_vals), 3) if slippage_vals else 0.0,
            "rejected_orders": rejected_orders,
            "partial_fills": partial_fills,
            "natural_exit_count": natural_exit_count,
            "forced_exit_count": forced_exit_count,
            "sample_size": len(style_rows),
            "closed_sample_size": len(closed_rows),
        }

    def status(self) -> dict[str, Any]:
        try:
            rows = self._paper_rows()
            today = _now().date().isoformat()
            style_metrics = {style: self._metrics_for_style(style, rows, today) for style in STYLES}
            def strength(item: tuple[str, dict[str, Any]]) -> float:
                m = item[1]
                return _to_float(m.get("win_rate"), 0.0) * 0.45 + max(0.0, _to_float(m.get("average_return_pct"), 0.0) + 5.0) * 5.0 + _to_float(m.get("entry_quality"), 0.0) * 0.20
            best = max(style_metrics.items(), key=strength)[0] if style_metrics else "day_trade"
            weakest = min(style_metrics.items(), key=strength)[0] if style_metrics else "scalp"
            forced_total = sum(int(m.get("forced_exit_count") or 0) for m in style_metrics.values())
            natural_total = sum(int(m.get("natural_exit_count") or 0) for m in style_metrics.values())
            summary = (
                f"Best current paper horizon is {best.replace('_', ' ')}; weakest is {weakest.replace('_', ' ')}. "
                f"Natural exits tracked: {natural_total}; artificial forced exits: {forced_total}."
            )
            return {
                "enabled": True,
                "version": VERSION,
                "mode": "paper_only_dashboard",
                "local_only": True,
                "writes_files": False,
                "scalp": style_metrics.get("scalp", {}),
                "day_trade": style_metrics.get("day_trade", {}),
                "swing_trade": style_metrics.get("swing_trade", {}),
                "best_current_horizon": best,
                "weakest_current_horizon": weakest,
                "overall_horizon_summary": summary,
                "natural_exit_preserved": True,
                "forced_early_exit_enabled": False,
                "artificial_max_hold_exit_enabled": False,
                "api_calls_used": 0,
                "live_trading_changed": False,
                "broker_execution_changed": False,
                "generated_at": _now_iso(),
            }
        except Exception as exc:
            return self._fallback(f"horizon_performance_dashboard_unavailable: {str(exc)[:140]}")

    def _fallback(self, reason: str) -> dict[str, Any]:
        empty = {
            "entries_today": 0,
            "exits_today": 0,
            "open_positions": 0,
            "win_rate": 0.0,
            "average_return_pct": 0.0,
            "profit_factor": 0.0,
            "average_hold_time": 0.0,
            "entry_quality": 0.0,
            "exit_quality": 0.0,
            "best_symbol": "n/a",
            "weakest_symbol": "n/a",
            "best_setup": "n/a",
            "weakest_setup": "n/a",
            "broker_fill_quality": 100.0,
            "average_slippage_bps": 0.0,
            "rejected_orders": 0,
            "partial_fills": 0,
            "natural_exit_count": 0,
            "forced_exit_count": 0,
        }
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "paper_only_dashboard",
            "local_only": True,
            "writes_files": False,
            "scalp": dict(empty),
            "day_trade": dict(empty),
            "swing_trade": dict(empty),
            "best_current_horizon": "day_trade",
            "weakest_current_horizon": "scalp",
            "overall_horizon_summary": reason,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "artificial_max_hold_exit_enabled": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "generated_at": _now_iso(),
        }
