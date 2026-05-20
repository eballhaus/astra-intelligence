from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 4_000_000
MAX_ROWS = 2_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


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


def _row_time(row: dict[str, Any]) -> datetime | None:
    for key in (
        "updated_at",
        "timestamp_utc",
        "evaluated_at_utc",
        "entry_timestamp",
        "entry_timestamp_utc",
        "opened_at",
        "exit_timestamp",
        "exit_timestamp_utc",
        "closed_at",
    ):
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt
    return None


def _is_today(row: dict[str, Any], today: str) -> bool:
    dt = _row_time(row)
    return bool(dt and dt.date().isoformat() == today)


def _field_is_today(row: dict[str, Any], today: str, keys: tuple[str, ...]) -> bool:
    for key in keys:
        dt = _parse_dt(row.get(key))
        if dt is not None:
            return dt.date().isoformat() == today
    return False


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


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _avg(rows: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    vals = [_to_float(r.get(key), float("nan")) for r in rows if isinstance(r, dict)]
    vals = [v for v in vals if v == v]
    return mean(vals) if vals else default


def _label(score: float) -> str:
    if score >= 80:
        return "strong"
    if score >= 65:
        return "healthy"
    if score >= 45:
        return "watch"
    return "needs_attention"


class MultiHorizonPaperTradingLearningSuiteV1:
    """Shadow-only paper learning diagnostics for scalp/day/swing styles.

    The suite is deliberately read-only. It classifies candidates and recent local
    paper observations, but it never forces exits, changes production rankings, or
    writes provider/trading state.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.stable_top_buys_path = os.path.join(self.state_dir, "snapshots", "stable_top_buys_v1.json")

    def classify_candidate(self, row: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        confidence = _to_float(r.get("confidence"), 55.0)
        entry_quality = _to_float(r.get("entry_quality_v3_score"), _to_float(r.get("entry_quality_score"), _to_float(r.get("entry_filter_v2_score"), 50.0)))
        execution = _to_float(r.get("execution_readiness_score"), _to_float(r.get("order_execution_score"), _to_float(r.get("liquidity_score"), 58.0)))
        liquidity = _to_float(r.get("liquidity_score"), _to_float(r.get("live_quality_score"), _to_float(r.get("data_quality_score"), 58.0)))
        intraday = _to_float(r.get("intraday_score"), _to_float(r.get("day_trade_score"), _to_float(r.get("momentum_score"), 50.0)))
        momentum = _to_float(r.get("momentum_score"), _to_float(r.get("small_mid_momentum_score"), intraday))
        expected_return = _to_float(r.get("expected_return_pct"), _to_float(r.get("predicted_profit_percent"), _to_float(r.get("expected_move_percent"), 0.0)))
        opportunity = _to_float(r.get("opportunity_score_pct"), _to_float(r.get("profit_priority_score"), _to_float(r.get("astra_score"), 55.0)))
        context = _to_float(r.get("context_score"), _to_float(r.get("profitability_context_score"), 50.0))
        portfolio_heat = _to_float(r.get("portfolio_heat_score"), _to_float(r.get("drawdown_risk_score"), 35.0))
        spread_risk = _to_float(r.get("spread_slippage_risk"), _to_float(r.get("slippage_risk_score"), max(0.0, 70.0 - liquidity)))
        catalyst = _to_float(r.get("catalyst_context_score"), 50.0)
        volatility = _to_float(r.get("volatility_score"), _to_float(r.get("atr_percentile"), 50.0))
        rank_stability = _to_float(r.get("rank_stability_10r"), _to_float(r.get("rank_stability_score"), 50.0))

        scalp_fit = _clamp(
            liquidity * 0.26
            + execution * 0.24
            + intraday * 0.20
            + momentum * 0.14
            + confidence * 0.10
            + catalyst * 0.06
            - spread_risk * 0.18
            - max(0.0, portfolio_heat - 65.0) * 0.18
        )
        day_fit = _clamp(
            entry_quality * 0.22
            + intraday * 0.19
            + confidence * 0.17
            + opportunity * 0.16
            + momentum * 0.12
            + catalyst * 0.08
            + liquidity * 0.06
            - spread_risk * 0.08
        )
        swing_fit = _clamp(
            max(0.0, min(100.0, expected_return * 5.0 + 45.0)) * 0.22
            + context * 0.20
            + opportunity * 0.18
            + rank_stability * 0.15
            + confidence * 0.12
            + entry_quality * 0.08
            + max(0.0, 100.0 - volatility * 0.35) * 0.05
            - max(0.0, portfolio_heat - 70.0) * 0.12
        )
        fits = {"scalp": scalp_fit, "day_trade": day_fit, "swing_trade": swing_fit}
        best_style = max(fits.items(), key=lambda kv: kv[1])[0]
        best_score = fits[best_style]
        spread = max(fits.values()) - min(fits.values())
        confidence_score = _clamp(45.0 + spread * 0.80)
        hold_category = {
            "scalp": "minutes_to_under_1h",
            "day_trade": "same_day_30m_to_7h",
            "swing_trade": "multi_day",
        }.get(best_style, "unknown")
        reasons = self._candidate_reasons(best_style, scalp_fit, day_fit, swing_fit, liquidity, execution, expected_return, context)
        penalties = self._candidate_penalties(liquidity, spread_risk, portfolio_heat, confidence, entry_quality)
        summary = (
            f"Best paper horizon is {best_style.replace('_', ' ')} at {best_score:.1f}; "
            f"scalp {scalp_fit:.1f}, day {day_fit:.1f}, swing {swing_fit:.1f}."
        )
        return {
            "trade_horizon_style": best_style,
            "trade_horizon_confidence": round(confidence_score, 3),
            "intended_hold_category": hold_category,
            "horizon_classification_reason": "; ".join(reasons[:3]) or "neutral_local_candidate_profile",
            "scalp_fit_score": round(scalp_fit, 3),
            "day_trade_fit_score": round(day_fit, 3),
            "swing_trade_fit_score": round(swing_fit, 3),
            "best_horizon_style": best_style,
            "best_horizon_score": round(best_score, 3),
            "horizon_style_summary": summary,
            "multi_horizon_candidate_reasons": reasons[:6],
            "multi_horizon_candidate_penalties": penalties[:6],
        }

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            for section in ("final", "qualified", "watchlist", "fill"):
                rows = pack.get(section)
                if not isinstance(rows, list):
                    continue
                updated = []
                for row in rows:
                    if not isinstance(row, dict):
                        updated.append(row)
                        continue
                    rr = dict(row)
                    rr.update(self.classify_candidate(rr))
                    updated.append(rr)
                pack[section] = updated
        out["multi_horizon_paper_trading_suite_v1"] = True
        out["multi_horizon_paper_trading_shadow_only"] = True
        out["multi_horizon_paper_trading_summary"] = self.status(rows=self._candidate_rows(out))
        return out

    def status(
        self,
        rows: list[dict[str, Any]] | None = None,
        observation_payload: dict[str, Any] | None = None,
        throughput_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._status(rows=rows, observation_payload=observation_payload or {}, throughput_payload=throughput_payload or {})
        except Exception as exc:
            return self._fallback(f"multi_horizon_paper_trading_unavailable: {str(exc)[:140]}")

    def _candidate_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for pack_key in ("stocks", "crypto"):
            pack = payload.get(pack_key)
            if not isinstance(pack, dict):
                continue
            for section in ("final", "qualified", "watchlist"):
                values = pack.get(section)
                if isinstance(values, list):
                    rows.extend([dict(v) for v in values if isinstance(v, dict)])
        dedup: dict[str, dict[str, Any]] = {}
        for row in rows:
            sym = _safe_text(row.get("symbol")).upper()
            if sym and sym not in dedup:
                dedup[sym] = row
        return list(dedup.values())

    def _load_default_rows(self) -> list[dict[str, Any]]:
        stable = _load_json(self.stable_top_buys_path)
        rows = stable.get("stable_top_6") if isinstance(stable, dict) else []
        return [dict(r) for r in rows if isinstance(r, dict)]

    def _status(self, rows: list[dict[str, Any]] | None, observation_payload: dict[str, Any], throughput_payload: dict[str, Any]) -> dict[str, Any]:
        today = _now().date().isoformat()
        candidate_rows = [dict(r) for r in (rows if rows is not None else self._load_default_rows()) if isinstance(r, dict)]
        lifecycle = _tail_jsonl(self.lifecycle_path)
        labels = _tail_jsonl(self.labels_path)
        ledger = _tail_jsonl(self.ledger_path, max_rows=1_000, max_bytes=2_000_000)
        lifecycle_today = [r for r in lifecycle if _is_today(r, today)]
        labels_today = [r for r in labels if _is_today(r, today)]
        ledger_today = [r for r in ledger if _is_today(r, today)]

        style_counts = {
            "scalp": {"entries": 0, "closures": 0, "labels": 0},
            "day_trade": {"entries": 0, "closures": 0, "labels": 0},
            "swing_trade": {"entries": 0, "closures": 0, "labels": 0},
        }
        for row in lifecycle:
            style = self._style_from_row(row)
            if _field_is_today(row, today, ("entry_timestamp", "entry_timestamp_utc", "opened_at")):
                style_counts[style]["entries"] += 1
            if _field_is_today(row, today, ("exit_timestamp", "exit_timestamp_utc", "closed_at")):
                style_counts[style]["closures"] += 1
        for row in labels_today:
            style = self._style_from_row(row)
            if _safe_text(row.get("outcome_label")) or _safe_text(row.get("label")):
                style_counts[style]["labels"] += 1

        classified = [self.classify_candidate(row) for row in candidate_rows[:50]]
        style_scores = {
            "scalp": mean([_to_float(r.get("scalp_fit_score"), 50.0) for r in classified]) if classified else 50.0,
            "day_trade": mean([_to_float(r.get("day_trade_fit_score"), 50.0) for r in classified]) if classified else 50.0,
            "swing_trade": mean([_to_float(r.get("swing_trade_fit_score"), 50.0) for r in classified]) if classified else 50.0,
        }
        best_current_horizon = max(style_scores.items(), key=lambda kv: kv[1])[0]
        weakest_current_horizon = min(style_scores.items(), key=lambda kv: kv[1])[0]

        perf = self._style_performance(labels_today + lifecycle_today + ledger_today)
        entries_total = sum(v["entries"] for v in style_counts.values())
        closures_total = sum(v["closures"] for v in style_counts.values())
        labels_total = sum(v["labels"] for v in style_counts.values())
        observation_score = _to_float(observation_payload.get("observation_completion_score"), 0.0)
        throughput_score = _to_float(observation_payload.get("learning_throughput_score"), 0.0)
        natural_flow_score = _clamp((closures_total * 18.0) + (labels_total * 0.70) + observation_score * 0.45)
        horizon_balance_score = _clamp(100.0 - self._style_imbalance_penalty(style_counts))
        candidate_quality_score = _clamp(mean(style_scores.values()))
        multi_horizon_score = _clamp(
            candidate_quality_score * 0.30
            + natural_flow_score * 0.24
            + horizon_balance_score * 0.18
            + observation_score * 0.16
            + throughput_score * 0.12
        )

        current_phase = self._current_phase(observation_payload, throughput_payload, entries_total, labels_total, multi_horizon_score)
        recommended_next_phase = self._recommended_next_phase(current_phase, observation_payload, multi_horizon_score, closures_total, labels_total)
        targets = self._phase_targets(current_phase)
        reasons, penalties = self._reasons_penalties(candidate_quality_score, natural_flow_score, horizon_balance_score, closures_total, labels_total, current_phase)

        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "promotion_allowed": False,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "artificial_max_hold_exit_enabled": False,
            "multi_horizon_paper_trading_status_v1": True,
            "generated_at": _now_iso(),
            "source_files": [self.lifecycle_path, self.labels_path, self.ledger_path, self.stable_top_buys_path],
            "max_rows_per_file": MAX_ROWS,
            "max_tail_bytes": MAX_TAIL_BYTES,
            "current_learning_phase": current_phase,
            "recommended_next_phase": recommended_next_phase,
            "suggested_scalp_trades_per_day": targets["scalp"],
            "suggested_day_trades_per_day": targets["day_trade"],
            "suggested_swing_trades_per_day": targets["swing_trade"],
            "suggested_total_paper_trades_per_day": targets["total"],
            "scalp_entries_today": int(style_counts["scalp"]["entries"]),
            "day_trade_entries_today": int(style_counts["day_trade"]["entries"]),
            "swing_trade_entries_today": int(style_counts["swing_trade"]["entries"]),
            "scalp_closures_today": int(style_counts["scalp"]["closures"]),
            "day_trade_closures_today": int(style_counts["day_trade"]["closures"]),
            "swing_trade_closures_today": int(style_counts["swing_trade"]["closures"]),
            "scalp_labels_today": int(style_counts["scalp"]["labels"]),
            "day_trade_labels_today": int(style_counts["day_trade"]["labels"]),
            "swing_trade_labels_today": int(style_counts["swing_trade"]["labels"]),
            "best_current_horizon": best_current_horizon,
            "weakest_current_horizon": weakest_current_horizon,
            "scalp_win_rate": perf["scalp"].get("win_rate"),
            "day_trade_win_rate": perf["day_trade"].get("win_rate"),
            "swing_trade_win_rate": perf["swing_trade"].get("win_rate"),
            "scalp_entry_quality": perf["scalp"].get("entry_quality"),
            "day_trade_entry_quality": perf["day_trade"].get("entry_quality"),
            "swing_trade_entry_quality": perf["swing_trade"].get("entry_quality"),
            "scalp_exit_quality": perf["scalp"].get("exit_quality"),
            "day_trade_exit_quality": perf["day_trade"].get("exit_quality"),
            "swing_trade_exit_quality": perf["swing_trade"].get("exit_quality"),
            "candidate_horizon_scores": {k: round(v, 3) for k, v in style_scores.items()},
            "candidates_evaluated": int(len(candidate_rows)),
            "multi_horizon_learning_score": round(multi_horizon_score, 3),
            "multi_horizon_learning_label": _label(multi_horizon_score),
            "multi_horizon_reasons": reasons,
            "multi_horizon_penalties": penalties,
            "multi_horizon_summary": (
                f"Phase {current_phase.replace('_', ' ')} targets {targets['total']} paper trades/day "
                f"({targets['scalp']} scalp, {targets['day_trade']} day, {targets['swing_trade']} swing). "
                f"Best current horizon is {best_current_horizon.replace('_', ' ')}; exits remain natural."
            ),
            "next_recommended_action": "track_horizon_labels_without_forcing_exits_or_changing_live_trading",
        }

    def _style_from_row(self, row: dict[str, Any]) -> str:
        raw = _safe_text(
            row.get("trade_horizon_style")
            or row.get("best_horizon_style")
            or row.get("paper_trade_style")
            or row.get("intended_hold_category")
            or row.get("recommended_hold_style")
        ).lower()
        if "scalp" in raw or "under_1h" in raw:
            return "scalp"
        if "swing" in raw or "multi_day" in raw or "position" in raw:
            return "swing_trade"
        if "day" in raw or "intraday" in raw or "same_day" in raw:
            return "day_trade"
        hours = self._duration_hours(row)
        if hours is not None:
            if hours < 1.0:
                return "scalp"
            if hours <= 9.0:
                return "day_trade"
            return "swing_trade"
        session = _safe_text(row.get("session_type") or row.get("market_session") or row.get("setup_type")).lower()
        if any(x in session for x in ("open", "vwap", "gap", "intraday", "breakout")):
            return "day_trade"
        return "day_trade"

    def _duration_hours(self, row: dict[str, Any]) -> float | None:
        entry = _parse_dt(row.get("entry_timestamp") or row.get("entry_timestamp_utc") or row.get("opened_at"))
        exit_dt = _parse_dt(row.get("exit_timestamp") or row.get("exit_timestamp_utc") or row.get("closed_at"))
        if entry is None or exit_dt is None or exit_dt < entry:
            return None
        return (exit_dt - entry).total_seconds() / 3600.0

    def _has_text(self, row: dict[str, Any], needles: tuple[str, ...]) -> bool:
        hay = " ".join(
            _safe_text(row.get(k)).lower()
            for k in ("lifecycle_stage", "status", "action", "exit_reason", "outcome_label", "release_status", "qualification")
        )
        return any(n in hay for n in needles)

    def _style_performance(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for style in ("scalp", "day_trade", "swing_trade"):
            style_rows = [r for r in rows if self._style_from_row(r) == style]
            wins = 0
            losses = 0
            entry_vals: list[float] = []
            exit_vals: list[float] = []
            for row in style_rows:
                label = _safe_text(row.get("outcome_label") or row.get("label") or row.get("result")).lower()
                ret = _to_float(row.get("realized_return_pct"), _to_float(row.get("pnl_percent"), float("nan")))
                if any(x in label for x in ("win", "clean_win", "target_hit", "strong_follow")) or (ret == ret and ret > 0):
                    wins += 1
                elif any(x in label for x in ("loss", "fast_loss", "bad_entry", "stop")) or (ret == ret and ret < 0):
                    losses += 1
                ev = _to_float(row.get("entry_quality_score"), _to_float(row.get("entry_quality_v3_score"), float("nan")))
                xv = _to_float(row.get("exit_quality_score"), float("nan"))
                if ev == ev:
                    entry_vals.append(ev)
                if xv == xv:
                    exit_vals.append(xv)
            sample = wins + losses
            out[style] = {
                "sample_size": int(len(style_rows)),
                "win_rate": round((wins / sample) * 100.0, 3) if sample else None,
                "entry_quality": round(mean(entry_vals), 3) if entry_vals else None,
                "exit_quality": round(mean(exit_vals), 3) if exit_vals else None,
            }
        return out

    def _style_imbalance_penalty(self, counts: dict[str, dict[str, int]]) -> float:
        vals = [counts[s]["entries"] + counts[s]["labels"] for s in ("scalp", "day_trade", "swing_trade")]
        total = sum(vals)
        if total <= 0:
            return 45.0
        max_share = max(vals) / max(1, total)
        return _clamp((max_share - 0.50) * 120.0, 0.0, 60.0)

    def _current_phase(self, obs: dict[str, Any], throughput: dict[str, Any], entries: int, labels: int, score: float) -> str:
        phase_hint = _safe_text(throughput.get("current_learning_phase") or obs.get("current_learning_phase")).lower()
        if phase_hint in {"phase_1_foundation", "phase_2_accelerated_learning", "phase_3_institutional_scale"}:
            return phase_hint
        completion = _to_float(obs.get("observation_completion_score"), 0.0)
        if score >= 78 and completion >= 75 and labels >= 20:
            return "phase_2_accelerated_learning"
        return "phase_1_foundation"

    def _recommended_next_phase(self, phase: str, obs: dict[str, Any], score: float, closures: int, labels: int) -> str:
        completion = _to_float(obs.get("observation_completion_score"), 0.0)
        stability = _to_float(obs.get("observation_intelligence_score"), score)
        if phase == "phase_1_foundation":
            if score >= 68 and completion >= 60 and closures >= 2 and labels >= 6:
                return "phase_2_accelerated_learning"
            return "remain_phase_1_foundation"
        if phase == "phase_2_accelerated_learning":
            if score >= 82 and completion >= 78 and stability >= 75 and closures >= 8 and labels >= 20:
                return "phase_3_institutional_scale"
            return "remain_phase_2_accelerated_learning"
        return "remain_phase_3_institutional_scale"

    def _phase_targets(self, phase: str) -> dict[str, str]:
        if phase == "phase_3_institutional_scale":
            return {"scalp": "10-20", "day_trade": "10-20", "swing_trade": "5-10", "total": "25-50"}
        if phase == "phase_2_accelerated_learning":
            return {"scalp": "5-10", "day_trade": "8-15", "swing_trade": "3-7", "total": "16-32"}
        return {"scalp": "0-2", "day_trade": "5-10", "swing_trade": "2-5", "total": "7-17"}

    def _candidate_reasons(self, style: str, scalp: float, day: float, swing: float, liquidity: float, execution: float, expected_return: float, context: float) -> list[str]:
        reasons = [f"{style}_fit_leads"]
        if liquidity >= 70:
            reasons.append("liquidity_supports_faster_horizons")
        if execution >= 65:
            reasons.append("execution_readiness_supportive")
        if expected_return >= 5:
            reasons.append("expected_return_supports_longer_hold")
        if context >= 60:
            reasons.append("context_supports_hold_thesis")
        if max(scalp, day, swing) - min(scalp, day, swing) < 8:
            reasons.append("horizon_fit_is_balanced")
        return reasons[:6]

    def _candidate_penalties(self, liquidity: float, spread_risk: float, portfolio_heat: float, confidence: float, entry_quality: float) -> list[str]:
        penalties: list[str] = []
        if liquidity < 45:
            penalties.append("liquidity_limits_scalp_fit")
        if spread_risk >= 45:
            penalties.append("spread_slippage_risk_penalizes_fast_trading")
        if portfolio_heat >= 75:
            penalties.append("portfolio_heat_limits_expansion")
        if confidence < 50:
            penalties.append("confidence_below_paper_expansion_target")
        if entry_quality < 45:
            penalties.append("entry_quality_limits_horizon_confidence")
        return penalties[:6]

    def _reasons_penalties(self, candidate_score: float, flow_score: float, balance_score: float, closures: int, labels: int, phase: str) -> tuple[list[str], list[str]]:
        reasons: list[str] = []
        penalties: list[str] = []
        if candidate_score >= 55:
            reasons.append("candidate_horizon_fit_available")
        else:
            penalties.append("candidate_horizon_fit_needs_stronger_evidence")
        if flow_score >= 45:
            reasons.append("natural_observation_flow_detected")
        else:
            penalties.append("limited_natural_closures_or_labels_today")
        if balance_score >= 55:
            reasons.append("style_coverage_not_overly_concentrated")
        else:
            penalties.append("style_learning_skewed_to_one_horizon")
        if closures <= 0:
            penalties.append("no_natural_closures_detected_today")
        if labels <= 0:
            penalties.append("no_horizon_labels_detected_today")
        if phase == "phase_1_foundation":
            reasons.append("foundation_phase_prevents_overload")
        return list(dict.fromkeys(reasons))[:8], list(dict.fromkeys(penalties))[:8]

    def _fallback(self, reason: str) -> dict[str, Any]:
        return {
            "enabled": False,
            "version": VERSION,
            "mode": "paper_only_shadow",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "promotion_allowed": False,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "artificial_max_hold_exit_enabled": False,
            "multi_horizon_paper_trading_status_v1": True,
            "current_learning_phase": "phase_1_foundation",
            "recommended_next_phase": "remain_phase_1_foundation",
            "suggested_scalp_trades_per_day": "0-2",
            "suggested_day_trades_per_day": "5-10",
            "suggested_swing_trades_per_day": "2-5",
            "suggested_total_paper_trades_per_day": "7-17",
            "scalp_entries_today": 0,
            "day_trade_entries_today": 0,
            "swing_trade_entries_today": 0,
            "scalp_closures_today": 0,
            "day_trade_closures_today": 0,
            "swing_trade_closures_today": 0,
            "best_current_horizon": "day_trade",
            "weakest_current_horizon": "scalp",
            "multi_horizon_learning_score": 0.0,
            "multi_horizon_learning_label": "needs_attention",
            "multi_horizon_summary": reason,
        }
