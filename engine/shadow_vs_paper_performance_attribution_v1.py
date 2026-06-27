from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.1.0"
CACHE_TTL_SECONDS = 20.0
CANONICAL_CACHE_TTL_SECONDS = 300.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800
MAX_CANONICAL_SCAN_ROWS = 425_000
ROLLING_WINDOWS = (20, 50, 100)
ATTRIBUTION_SOURCES = (
    "candidate_ranking_influence",
    "buy_purity_influence",
    "opportunity_cost_influence",
    "profit_protection_pilot",
    "catalyst_lifecycle_intelligence",
    "catalyst_decay_intelligence",
    "cross_sector_capital_flow_memory",
)
BUILD_COHORTS = (
    "legacy_astra",
    "pre_shadow_astra",
    "historical_memory_astra",
    "catalyst_intelligence_astra",
    "current_astra",
)
MINIMUM_PF_SAMPLE_SIZE = 20
MINIMUM_SHADOW_SAMPLE_SIZE = 20
MINIMUM_LIFECYCLE_COUNT = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _round(value: Any, digits: int = 3) -> float:
    return round(_to_float(value), digits)


def _round_or_none(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(_to_float(value), digits)


def _text(value: Any, default: str = "insufficient_data") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


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


def _iter_jsonl(path: str, max_rows: int = MAX_CANONICAL_SCAN_ROWS):
    if not os.path.exists(path):
        return
    count = 0
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if count >= max_rows:
                    break
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    count += 1
                    yield parsed
    except Exception:
        return


def _status(statuses: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    value = statuses.get(key) or {}
    return dict(value) if isinstance(value, dict) else {}


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (dict, list)) and not value:
            continue
        return value
    return default


def _ratio_to_pct(value: Any) -> float:
    ratio = _to_float(value, 0.0)
    if ratio <= 1.5:
        ratio *= 100.0
    return ratio


def _profit_factor(returns: list[float]) -> float | None:
    non_zero = [value for value in returns if abs(value) > 1e-9]
    if not non_zero:
        return None
    gains = sum(value for value in non_zero if value > 0)
    losses = abs(sum(value for value in non_zero if value < 0))
    if losses <= 0:
        return round(gains, 4) if gains > 0 else 0.0
    return round(gains / losses, 4)


def _avg(values: list[float]) -> float | None:
    vals = [value for value in values if math.isfinite(value)]
    return round(mean(vals), 4) if vals else None


def _paper_return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("current_or_exit_profit_pct"),
        _to_float(
            row.get("current_return_pct"),
            _to_float(row.get("continuation_after_entry_pct"), _to_float(row.get("actual_return_pct"))),
        ),
    )


def _shadow_return_pct(row: dict[str, Any]) -> float:
    return _to_float(
        row.get("best_counterfactual_return"),
        _to_float(row.get("counterfactual_return_pct"), _to_float(row.get("best_virtual_return"), _to_float(row.get("best_replay_return")))),
    )


def _row_return_pct(row: dict[str, Any]) -> float | None:
    for key in (
        "realized_return_pct",
        "current_or_exit_profit_pct",
        "actual_return_pct",
        "return_pct",
        "current_return_pct",
        "continuation_after_entry_pct",
        "pnl_pct",
        "profit_pct",
        "pnl",
        "realized_pnl",
        "profit_loss",
        "return",
    ):
        if row.get(key) in (None, ""):
            continue
        try:
            value = float(str(row.get(key)).strip().replace("%", ""))
            return value if math.isfinite(value) else None
        except Exception:
            continue
    return None


def _infer_horizon(row: dict[str, Any]) -> str:
    raw = _text(
        _first(
            row.get("paper_entry_horizon_style"),
            row.get("horizon"),
            row.get("horizon_style"),
            row.get("assigned_horizon"),
            row.get("best_horizon"),
            row.get("expected_horizon"),
            row.get("market_regime"),
            row.get("exit_context_label"),
            default="",
        ),
        "",
    ).lower()
    if "scalp" in raw or raw in {"15m", "30m", "45m", "60m"}:
        return "scalp"
    if "day" in raw or "intraday" in raw or raw in {"2h", "4h", "eod"}:
        return "day_trade"
    if "swing" in raw or "multi_day" in raw or "overnight" in raw:
        return "swing_trade"
    minutes = _to_float(_first(row.get("expected_hold_duration_minutes"), row.get("day_learning_horizon_minutes"), default=0.0), 0.0)
    if minutes > 0:
        if minutes <= 60:
            return "scalp"
        if minutes <= 390:
            return "day_trade"
        return "swing_trade"
    return "unknown"


class ShadowVsPaperPerformanceAttributionV1:
    """Reconciled paper-vs-shadow observational attribution.

    Paper metrics are anchored to the same canonical performance source that
    Unified Learning Diagnostics uses. Shadow metrics are verified only from
    bounded replay/counterfactual rows when enough evidence exists.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.cache_path = os.path.join(self.state_dir, "dashboard_cache", "shadow_vs_paper_performance_attribution_v1.json")
        self.lifecycle_v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.lifecycle_v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.lifecycle_core_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.outcome_labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.candidate_ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.profit_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.archetype_path = os.path.join(self.state_dir, "trade_archetype_regime_intelligence_v1.jsonl")
        self.replay_path = os.path.join(self.state_dir, "replay_counterfactual_learning_v2.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _source_signature(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name, path in (
            ("candidate_decision_ledger_v1", self.candidate_ledger_path),
            ("trade_lifecycle_excursion_v2", self.lifecycle_v2_path),
            ("trade_lifecycle_v1", self.lifecycle_core_path),
            ("replay_counterfactual_learning_v2", self.replay_path),
        ):
            try:
                stat = os.stat(path)
                out[name] = {"size": int(stat.st_size), "mtime": round(float(stat.st_mtime), 3)}
            except Exception:
                out[name] = {"size": 0, "mtime": 0.0}
        return out

    def _cached_canonical(self) -> dict[str, Any]:
        cached = _read_json(self.cache_path)
        if not cached:
            return {}
        signature_match = cached.get("canonical_source_signature") == self._source_signature()
        try:
            age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
        except Exception:
            age = 999999.0
        # The underlying state files are append-only and can change while the
        # dashboard is rendering. A fresh canonical cache is safer than forcing
        # repeated multi-hundred-MB scans on every diagnostics request.
        if not signature_match and age > CANONICAL_CACHE_TTL_SECONDS:
            return {}
        return cached

    def _candidate_ledger_truth(self) -> dict[str, Any]:
        cached = self._cached_canonical()
        if cached.get("candidate_decision_record_count"):
            return {
                "candidate_ledger_source": cached.get("candidate_ledger_source", "candidate_decision_ledger_v1"),
                "candidate_decision_record_count": _to_int(cached.get("candidate_decision_record_count"), 0),
                "candidate_paper_ready_count": _to_int(cached.get("candidate_paper_ready_count"), 0),
                "candidate_released_count": _to_int(cached.get("candidate_released_count"), 0),
                "candidate_day_learning_count": _to_int(cached.get("candidate_day_learning_count"), 0),
                "candidate_day_learning_horizon_counts": dict(cached.get("candidate_day_learning_horizon_counts") or {}),
                "candidate_action_counts": dict(cached.get("candidate_action_counts") or {}),
                "candidate_horizon_source_note": cached.get("candidate_horizon_source_note"),
            }
        record_count = 0
        paper_ready = 0
        released = 0
        day_candidates = 0
        day_horizon_counts: dict[str, int] = {}
        actions: dict[str, int] = {}
        for row in _iter_jsonl(self.candidate_ledger_path):
            record_count += 1
            action = _text(row.get("action"), "unknown")
            actions[action] = actions.get(action, 0) + 1
            if bool(row.get("was_paper_ready")) or _text(row.get("canonical_state"), "") == "paper_ready":
                paper_ready += 1
            if bool(row.get("was_released")):
                released += 1
            if bool(row.get("day_learning_candidate")):
                day_candidates += 1
            minutes = row.get("day_learning_horizon_minutes")
            if minutes not in (None, ""):
                key = _text(minutes, "unknown")
                day_horizon_counts[key] = day_horizon_counts.get(key, 0) + 1
        return {
            "candidate_ledger_source": "candidate_decision_ledger_v1",
            "candidate_decision_record_count": record_count,
            "candidate_paper_ready_count": paper_ready,
            "candidate_released_count": released,
            "candidate_day_learning_count": day_candidates,
            "candidate_day_learning_horizon_counts": day_horizon_counts,
            "candidate_action_counts": actions,
            "candidate_horizon_source_note": "candidate ledger stores day-learning horizon fields; full scalp/day/swing distribution is reconciled from lifecycle evidence",
        }

    def _lifecycle_truth(self) -> dict[str, Any]:
        cached = self._cached_canonical()
        if cached.get("canonical_closed_trade_count"):
            return {
                "canonical_lifecycle_source": cached.get("canonical_lifecycle_source", "trade_lifecycle_excursion_v2"),
                "canonical_lifecycle_source_counts": dict(cached.get("canonical_lifecycle_source_counts") or {}),
                "canonical_lifecycle_rows_scanned": _to_int(cached.get("canonical_lifecycle_rows_scanned"), 0),
                "canonical_lifecycle_scan_cap": _to_int(cached.get("canonical_lifecycle_scan_cap"), MAX_CANONICAL_SCAN_ROWS),
                "canonical_closed_trade_count": _to_int(cached.get("canonical_closed_trade_count"), 0),
                "canonical_win_count": _to_int(cached.get("canonical_win_count"), 0),
                "canonical_loss_count": _to_int(cached.get("canonical_loss_count"), 0),
                "canonical_breakeven_count": _to_int(cached.get("canonical_breakeven_count"), 0),
                "canonical_gross_profit": _to_float(cached.get("canonical_gross_profit"), 0.0),
                "canonical_gross_loss": _to_float(cached.get("canonical_gross_loss"), 0.0),
                "canonical_profit_factor": cached.get("canonical_profit_factor"),
                "canonical_win_rate": cached.get("canonical_win_rate"),
                "canonical_average_return": cached.get("canonical_average_return"),
                "canonical_return_sample": [],
                "lifecycle_horizon_counts": dict(cached.get("lifecycle_horizon_counts") or {}),
                "closed_lifecycle_evidence_reconciled": bool(cached.get("closed_lifecycle_evidence_reconciled")),
            }
        returns: list[float] = []
        closed_count = 0
        win_count = 0
        loss_count = 0
        breakeven_count = 0
        gross_profit = 0.0
        gross_loss = 0.0
        horizon_counts = {"scalp": 0, "day_trade": 0, "swing_trade": 0, "unknown": 0}
        source_counts: dict[str, int] = {}
        rows_scanned = 0
        # V2 carries the richest horizon and excursion data. Core lifecycle is
        # used only when V2 has no usable return-bearing rows.
        for source_name, path in (
            ("trade_lifecycle_excursion_v2", self.lifecycle_v2_path),
            ("trade_lifecycle_v1", self.lifecycle_core_path),
        ):
            local_rows = 0
            for row in _iter_jsonl(path):
                local_rows += 1
                rows_scanned += 1
                ret = _row_return_pct(row)
                if ret is None:
                    continue
                returns.append(ret)
                closed_count += 1
                horizon = _infer_horizon(row)
                if horizon not in horizon_counts:
                    horizon = "unknown"
                horizon_counts[horizon] += 1
                if ret > 0:
                    win_count += 1
                    gross_profit += ret
                elif ret < 0:
                    loss_count += 1
                    gross_loss += abs(ret)
                else:
                    breakeven_count += 1
            if local_rows:
                source_counts[source_name] = local_rows
            if returns and source_name == "trade_lifecycle_excursion_v2":
                break
        pf = _profit_factor(returns)
        avg_return = _avg(returns)
        win_rate = round((win_count / max(1, win_count + loss_count + breakeven_count)) * 100.0, 4) if closed_count else None
        return {
            "canonical_lifecycle_source": "trade_lifecycle_excursion_v2" if source_counts.get("trade_lifecycle_excursion_v2") else "trade_lifecycle_v1",
            "canonical_lifecycle_source_counts": source_counts,
            "canonical_lifecycle_rows_scanned": rows_scanned,
            "canonical_lifecycle_scan_cap": MAX_CANONICAL_SCAN_ROWS,
            "canonical_closed_trade_count": closed_count,
            "canonical_win_count": win_count,
            "canonical_loss_count": loss_count,
            "canonical_breakeven_count": breakeven_count,
            "canonical_gross_profit": round(gross_profit, 4),
            "canonical_gross_loss": round(gross_loss, 4),
            "canonical_profit_factor": _round_or_none(pf, 4),
            "canonical_win_rate": _round_or_none(win_rate, 4),
            "canonical_average_return": _round_or_none(avg_return, 4),
            "canonical_return_sample": returns,
            "lifecycle_horizon_counts": horizon_counts,
            "closed_lifecycle_evidence_reconciled": bool(closed_count > 0 and (win_count > 0 or loss_count > 0)),
        }

    def _shadow_lifecycle_truth(self) -> dict[str, Any]:
        cached = self._cached_canonical()
        if cached.get("canonical_shadow_actual_return_count"):
            return {
                "canonical_shadow_source": cached.get("canonical_shadow_source", "replay_counterfactual_learning_v2"),
                "canonical_shadow_rows_scanned": _to_int(cached.get("canonical_shadow_rows_scanned"), 0),
                "canonical_shadow_scan_cap": _to_int(cached.get("canonical_shadow_scan_cap"), MAX_CANONICAL_SCAN_ROWS),
                "canonical_shadow_return_count": _to_int(cached.get("canonical_shadow_return_count"), 0),
                "canonical_shadow_win_count": _to_int(cached.get("canonical_shadow_win_count"), 0),
                "canonical_shadow_loss_count": _to_int(cached.get("canonical_shadow_loss_count"), 0),
                "canonical_shadow_breakeven_count": _to_int(cached.get("canonical_shadow_breakeven_count"), 0),
                "canonical_shadow_gross_profit": _to_float(cached.get("canonical_shadow_gross_profit"), 0.0),
                "canonical_shadow_gross_loss": _to_float(cached.get("canonical_shadow_gross_loss"), 0.0),
                "canonical_shadow_profit_factor": cached.get("canonical_shadow_profit_factor"),
                "canonical_shadow_average_return": cached.get("canonical_shadow_average_return"),
                "canonical_shadow_actual_return_count": _to_int(cached.get("canonical_shadow_actual_return_count"), 0),
                "canonical_shadow_actual_win_count": _to_int(cached.get("canonical_shadow_actual_win_count"), 0),
                "canonical_shadow_actual_loss_count": _to_int(cached.get("canonical_shadow_actual_loss_count"), 0),
                "canonical_shadow_actual_gross_profit": _to_float(cached.get("canonical_shadow_actual_gross_profit"), 0.0),
                "canonical_shadow_actual_gross_loss": _to_float(cached.get("canonical_shadow_actual_gross_loss"), 0.0),
                "canonical_shadow_actual_profit_factor": cached.get("canonical_shadow_actual_profit_factor"),
                "canonical_shadow_returns": [],
                "shadow_loss_bearing_sample_verified": bool(cached.get("shadow_loss_bearing_sample_verified")),
            }
        returns: list[float] = []
        actual_returns: list[float] = []
        wins = 0
        losses = 0
        breakeven = 0
        gross_profit = 0.0
        gross_loss = 0.0
        actual_wins = 0
        actual_losses = 0
        actual_gross_profit = 0.0
        actual_gross_loss = 0.0
        rows = 0
        for row in _iter_jsonl(self.replay_path):
            rows += 1
            actual = _row_return_pct({"actual_return_pct": row.get("actual_return_pct")})
            if actual is not None and abs(actual) > 1e-9:
                actual_returns.append(actual)
                if actual > 0:
                    actual_wins += 1
                    actual_gross_profit += actual
                elif actual < 0:
                    actual_losses += 1
                    actual_gross_loss += abs(actual)
            ret = _shadow_return_pct(row)
            if abs(ret) <= 1e-9:
                breakeven += 1
                continue
            returns.append(ret)
            if ret > 0:
                wins += 1
                gross_profit += ret
            elif ret < 0:
                losses += 1
                gross_loss += abs(ret)
        return {
            "canonical_shadow_source": "replay_counterfactual_learning_v2",
            "canonical_shadow_rows_scanned": rows,
            "canonical_shadow_scan_cap": MAX_CANONICAL_SCAN_ROWS,
            "canonical_shadow_return_count": len(returns),
            "canonical_shadow_win_count": wins,
            "canonical_shadow_loss_count": losses,
            "canonical_shadow_breakeven_count": breakeven,
            "canonical_shadow_gross_profit": round(gross_profit, 4),
            "canonical_shadow_gross_loss": round(gross_loss, 4),
            "canonical_shadow_profit_factor": _round_or_none(_profit_factor(returns), 4),
            "canonical_shadow_average_return": _round_or_none(_avg(returns), 4),
            "canonical_shadow_actual_return_count": len(actual_returns),
            "canonical_shadow_actual_win_count": actual_wins,
            "canonical_shadow_actual_loss_count": actual_losses,
            "canonical_shadow_actual_gross_profit": round(actual_gross_profit, 4),
            "canonical_shadow_actual_gross_loss": round(actual_gross_loss, 4),
            "canonical_shadow_actual_profit_factor": _round_or_none(_profit_factor(actual_returns), 4),
            "canonical_shadow_returns": returns,
            "shadow_loss_bearing_sample_verified": bool((losses > 0 and gross_loss > 0) or (actual_losses > 0 and actual_gross_loss > 0)),
        }

    def _advanced_learning_status(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        advanced = _status(statuses, "advanced_learning_intelligence")
        has_core = bool(advanced) and all(advanced.get(key) not in (None, "") for key in ("released_win_rate", "profit_factor", "average_return"))
        if has_core:
            return advanced
        try:
            from engine.advanced_learning_intelligence_v1 import AdvancedLearningIntelligenceV1

            return dict(AdvancedLearningIntelligenceV1(state_dir=self.state_dir).status(force=False) or {})
        except Exception:
            return advanced

    def _paper_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.lifecycle_v1_path, self.lifecycle_v2_path, self.profit_path, self.archetype_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                symbol = _text(row.get("symbol")).upper()
                key = lifecycle_id or f"{symbol}:{_text(row.get('entry_timestamp') or row.get('timestamp'))[:16]}"
                if not key or key == ":":
                    continue
                merged = dict(latest.get(key) or {})
                merged.update(row)
                latest[key] = merged
        return list(latest.values())

    def _replay_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _tail_jsonl(self.replay_path):
            lifecycle_id = _text(row.get("lifecycle_id"))
            symbol = _text(row.get("symbol")).upper()
            key = lifecycle_id or f"{symbol}:{_text(row.get('timestamp'))[:16]}"
            if not key or key == ":":
                continue
            merged = dict(latest.get(key) or {})
            merged.update(row)
            latest[key] = merged
        return list(latest.values())

    def _paper_canonical(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        broker = _status(statuses, "alpaca_paper_broker")
        broker_truth = dict(broker.get("broker_truth_metrics") or {})
        lifecycle = _status(statuses, "trade_lifecycle_excursion_v2")
        lifecycle_truth = self._lifecycle_truth()
        candidate_truth = self._candidate_ledger_truth()

        returns_all = [_to_float(row.get("realized_return_pct"), 0.0) for row in (broker_truth.get("closed_trade_rows") or []) if isinstance(row, dict)]
        non_zero_returns = [value for value in returns_all if abs(value) > 1e-9]
        canonical_returns = list(lifecycle_truth.get("canonical_return_sample") or [])
        if not non_zero_returns and canonical_returns:
            non_zero_returns = [value for value in canonical_returns if abs(value) > 1e-9]
        raw_pf = broker_truth.get("true_paper_pf")
        avg_return_raw = _avg(non_zero_returns)
        paper_profit_factor_verified = _first(broker_truth.get("true_paper_pf"), lifecycle_truth.get("canonical_profit_factor"))
        paper_win_rate = _first(broker_truth.get("true_paper_win_rate"), lifecycle_truth.get("canonical_win_rate"))
        paper_avg_return = _first(broker_truth.get("true_paper_avg_return"), lifecycle_truth.get("canonical_average_return"))
        canonical_source = _text(
            broker_truth.get("true_paper_metric_source") if _to_int(broker_truth.get("true_paper_closed_trade_count"), 0) > 0 else lifecycle_truth.get("canonical_lifecycle_source"),
            "trade_lifecycle_excursion_v2",
        )
        canonical_closed_trade_count = max(
            _to_int(broker_truth.get("true_paper_closed_trade_count"), 0),
            _to_int(lifecycle_truth.get("canonical_closed_trade_count"), 0),
        )
        paper_profit_capture = broker_truth.get("true_paper_profit_capture")
        paper_exit_quality = broker_truth.get("true_paper_exit_quality")
        metric_trust_level = _text(
            broker_truth.get("true_paper_metric_trust_level"),
            "lifecycle_reconciled_closed_trade_evidence" if canonical_closed_trade_count > 0 else "insufficient_broker_confirmed_evidence",
        )

        return {
            "canonical_performance_source": canonical_source,
            "canonical_closed_trade_count": int(canonical_closed_trade_count),
            "paper_rows_reviewed": max(_to_int(broker_truth.get("closed_orders_reviewed"), 0), _to_int(lifecycle_truth.get("canonical_lifecycle_rows_scanned"), 0)),
            "paper_returns_count": len(non_zero_returns),
            "paper_returns": non_zero_returns,
            "paper_gross_profit": _to_float(_first(broker_truth.get("paper_gross_profit"), lifecycle_truth.get("canonical_gross_profit")), 0.0),
            "paper_gross_loss": _to_float(_first(broker_truth.get("paper_gross_loss"), lifecycle_truth.get("canonical_gross_loss")), 0.0),
            "winning_trade_count": max(_to_int(broker_truth.get("winning_trade_count"), 0), _to_int(lifecycle_truth.get("canonical_win_count"), 0)),
            "losing_trade_count": max(_to_int(broker_truth.get("losing_trade_count"), 0), _to_int(lifecycle_truth.get("canonical_loss_count"), 0)),
            "breakeven_trade_count": max(_to_int(broker_truth.get("breakeven_trade_count"), 0), _to_int(lifecycle_truth.get("canonical_breakeven_count"), 0)),
            "paper_profit_factor_raw": _round_or_none(_first(raw_pf, lifecycle_truth.get("canonical_profit_factor")), 4),
            "paper_profit_factor_verified": _round_or_none(paper_profit_factor_verified, 4),
            "paper_profit_factor": _round_or_none(paper_profit_factor_verified, 4),
            "paper_win_rate": _round_or_none(paper_win_rate, 4),
            "paper_avg_return": _round_or_none(paper_avg_return, 4),
            "paper_avg_mfe": _round_or_none(_first(lifecycle.get("average_mfe_pct"), lifecycle.get("average_MFE")), 4),
            "paper_avg_mae": _round_or_none(_first(lifecycle.get("average_mae_pct"), lifecycle.get("average_MAE")), 4),
            "paper_profit_capture": _round_or_none(paper_profit_capture, 4),
            "paper_exit_quality": _round_or_none(paper_exit_quality, 4),
            "paper_profit_factor_available": canonical_closed_trade_count >= MINIMUM_PF_SAMPLE_SIZE and paper_profit_factor_verified is not None,
            "paper_profit_factor_status": "PASS" if canonical_closed_trade_count >= MINIMUM_PF_SAMPLE_SIZE and paper_profit_factor_verified is not None else "INSUFFICIENT_EVIDENCE",
            "paper_trade_count": int(canonical_closed_trade_count),
            "unified_profit_factor_reference": _round_or_none(paper_profit_factor_verified, 4),
            "unified_average_return_reference": _round_or_none(paper_avg_return, 4),
            "paper_metric_trust_level": metric_trust_level,
            "paper_metric_confidence": _to_float(broker_truth.get("true_paper_metric_confidence"), 0.0),
            "paper_pf_scope": _text(broker_truth.get("pf_scope"), "broker_confirmed_paper_closed_trades"),
            "paper_pf_dataset_owner": _text(broker_truth.get("pf_dataset_owner"), "alpaca_paper_broker"),
            "truth_reconciliation_status": "PASS" if canonical_closed_trade_count > 0 else "INSUFFICIENT_EVIDENCE",
            "broker_truth_closed_trade_count": _to_int(broker_truth.get("true_paper_closed_trade_count"), 0),
            "broker_truth_matches_lifecycle_truth": bool(
                _to_int(broker_truth.get("true_paper_closed_trade_count"), 0) in {0, canonical_closed_trade_count}
            ),
            "lifecycle_truth_used_as_canonical_fallback": bool(_to_int(broker_truth.get("true_paper_closed_trade_count"), 0) <= 0 and canonical_closed_trade_count > 0),
            **{key: value for key, value in lifecycle_truth.items() if key != "canonical_return_sample"},
            **candidate_truth,
        }

    def _shadow_metrics(self, statuses: dict[str, dict[str, Any]], paper: dict[str, Any]) -> dict[str, Any]:
        replay_status = _status(statuses, "replay_counterfactual_learning_v2")
        shadow_lab = _status(statuses, "realistic_shadow_evidence_learning_lab_v1")
        convergence = _status(statuses, "virtual_paper_convergence_symbol_attribution_v1")
        shadow_truth = self._shadow_lifecycle_truth()
        rows = self._replay_rows()
        returns_all = [_shadow_return_pct(row) for row in rows if _text(row.get("symbol"), "")]
        non_zero_returns = [value for value in returns_all if abs(value) > 1e-9]
        if len(non_zero_returns) < MINIMUM_SHADOW_SAMPLE_SIZE:
            non_zero_returns = [value for value in (shadow_truth.get("canonical_shadow_returns") or []) if abs(value) > 1e-9]
        wins = [value for value in non_zero_returns if value > 0]
        losses = [value for value in non_zero_returns if value < 0]
        shadow_gross_profit = round(sum(wins), 4)
        shadow_gross_loss = round(abs(sum(losses)), 4)
        observed_loss_count = max(len(losses), _to_int(shadow_truth.get("canonical_shadow_actual_loss_count"), 0))
        observed_win_count = max(len(wins), _to_int(shadow_truth.get("canonical_shadow_actual_win_count"), 0))
        observed_trade_count = max(len(non_zero_returns), _to_int(shadow_truth.get("canonical_shadow_actual_return_count"), 0))
        raw_pf = _profit_factor(non_zero_returns)
        verified_available = (
            len(non_zero_returns) >= MINIMUM_SHADOW_SAMPLE_SIZE
            and max(len(rows), _to_int(shadow_lab.get("completed_shadow_lifecycles"), 0)) >= MINIMUM_LIFECYCLE_COUNT
            and len(wins) > 0
            and len(losses) > 0
        )
        verified_pf = raw_pf if verified_available else None
        shadow_win_rate = round((len(wins) / len(non_zero_returns)) * 100.0, 4) if non_zero_returns else None
        shadow_avg_return = _avg(non_zero_returns)
        shadow_profit_capture = _ratio_to_pct(_first(shadow_lab.get("shadow_capture_ratio"), default=0.0))
        shadow_exit_quality = _to_float(
            _first(
                convergence.get("policy_improvement_confidence"),
                shadow_lab.get("policy_confidence"),
                default=0.0,
            ),
            0.0,
        )
        return {
            "recommendations_reviewed": max(
                _to_int(shadow_lab.get("realism_weighted_learning_events"), 0),
                _to_int(shadow_lab.get("shadow_learning_events"), 0),
                len(rows),
            ),
            "shadow_trade_count": observed_trade_count,
            "shadow_best_path_trade_count": len(non_zero_returns),
            "shadow_completed_lifecycle_count": max(_to_int(shadow_lab.get("completed_shadow_lifecycles"), 0), len(rows), _to_int(shadow_truth.get("canonical_shadow_return_count"), 0)),
            "shadow_winning_trade_count": observed_win_count,
            "shadow_best_path_winning_trade_count": len(wins),
            "shadow_losing_trade_count": observed_loss_count,
            "shadow_best_path_losing_trade_count": len(losses),
            "shadow_actual_losing_trade_count": _to_int(shadow_truth.get("canonical_shadow_actual_loss_count"), 0),
            "shadow_breakeven_trade_count": max(0, len(returns_all) - len(non_zero_returns)),
            "shadow_rows_reviewed": len(rows),
            "shadow_returns": non_zero_returns,
            "shadow_gross_profit": shadow_gross_profit,
            "shadow_gross_loss": shadow_gross_loss,
            "shadow_profit_factor_raw": _round_or_none(raw_pf, 4),
            "shadow_profit_factor_verified": _round_or_none(verified_pf, 4),
            "shadow_profit_factor": _round_or_none(verified_pf, 4),
            "shadow_win_rate": _round_or_none(shadow_win_rate, 4),
            "shadow_avg_return": _round_or_none(
                _first(shadow_avg_return, replay_status.get("average_best_counterfactual_return"), convergence.get("average_virtual_return")),
                4,
            ),
            "shadow_avg_mfe": _round_or_none(shadow_lab.get("shadow_avg_MFE"), 4),
            "shadow_avg_mae": _round_or_none(shadow_lab.get("shadow_avg_MAE"), 4),
            "shadow_profit_capture": _round_or_none(shadow_profit_capture, 4),
            "shadow_exit_quality": _round_or_none(shadow_exit_quality, 4),
            "shadow_profit_factor_available": verified_available and verified_pf is not None,
            "shadow_profit_factor_status": "PASS" if verified_available and verified_pf is not None else "INSUFFICIENT_EVIDENCE",
            "shadow_pf_blocker": (
                "needs_loss_bearing_shadow_sample"
                if len(non_zero_returns) >= MINIMUM_SHADOW_SAMPLE_SIZE and len(losses) <= 0
                else "needs_more_shadow_evidence"
            ) if not verified_available else "none",
            "minimum_shadow_sample_size": MINIMUM_SHADOW_SAMPLE_SIZE,
            "minimum_lifecycle_count": MINIMUM_LIFECYCLE_COUNT,
            **{key: value for key, value in shadow_truth.items() if key != "canonical_shadow_returns"},
        }

    def _rolling_windows(self, paper_returns: list[float], shadow_returns: list[float]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for window in ROLLING_WINDOWS:
            paper_chunk = paper_returns[-window:]
            shadow_chunk = shadow_returns[-window:]
            paper_available = len(paper_chunk) >= min(window, MINIMUM_PF_SAMPLE_SIZE)
            shadow_available = (
                len(shadow_chunk) >= min(window, MINIMUM_SHADOW_SAMPLE_SIZE)
                and any(value > 0 for value in shadow_chunk)
                and any(value < 0 for value in shadow_chunk)
            )
            out[f"rolling_{window}_paper_pf"] = _round_or_none(_profit_factor(paper_chunk), 4) if paper_available else None
            out[f"rolling_{window}_paper_pf_status"] = "PASS" if paper_available else "INSUFFICIENT_EVIDENCE"
            out[f"rolling_{window}_shadow_pf"] = _round_or_none(_profit_factor(shadow_chunk), 4) if shadow_available else None
            out[f"rolling_{window}_shadow_pf_status"] = "PASS" if shadow_available else "INSUFFICIENT_EVIDENCE"
        out["lifetime_paper_pf"] = _round_or_none(_profit_factor(paper_returns), 4) if len(paper_returns) >= MINIMUM_PF_SAMPLE_SIZE else None
        out["lifetime_paper_pf_status"] = "PASS" if len(paper_returns) >= MINIMUM_PF_SAMPLE_SIZE else "INSUFFICIENT_EVIDENCE"
        lifetime_shadow_available = (
            len(shadow_returns) >= MINIMUM_SHADOW_SAMPLE_SIZE
            and any(value > 0 for value in shadow_returns)
            and any(value < 0 for value in shadow_returns)
        )
        out["lifetime_shadow_pf"] = _round_or_none(_profit_factor(shadow_returns), 4) if lifetime_shadow_available else None
        out["lifetime_shadow_pf_status"] = "PASS" if lifetime_shadow_available else "INSUFFICIENT_EVIDENCE"
        return out

    def _comparison(self, paper: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
        paper_pf = paper.get("paper_profit_factor_verified")
        shadow_pf = shadow.get("shadow_profit_factor_verified")
        paper_wr = paper.get("paper_win_rate")
        shadow_wr = shadow.get("shadow_win_rate")
        paper_avg = paper.get("paper_avg_return")
        shadow_avg = shadow.get("shadow_avg_return")
        paper_capture = paper.get("paper_profit_capture")
        shadow_capture = shadow.get("shadow_profit_capture")
        paper_exit = paper.get("paper_exit_quality")
        shadow_exit = shadow.get("shadow_exit_quality")

        comparison_available = paper_pf is not None and shadow_pf is not None
        pf_delta = (_to_float(shadow_pf, 0.0) - _to_float(paper_pf, 0.0)) if comparison_available else None
        wr_delta = (_to_float(shadow_wr, 0.0) - _to_float(paper_wr, 0.0)) if comparison_available else None
        avg_return_delta = (_to_float(shadow_avg, 0.0) - _to_float(paper_avg, 0.0)) if comparison_available else None
        capture_delta = (_to_float(shadow_capture, 0.0) - _to_float(paper_capture, 0.0)) if comparison_available else None
        exit_delta = (_to_float(shadow_exit, 0.0) - _to_float(paper_exit, 0.0)) if comparison_available else None
        return {
            "shadow_outperformance_pct": _round(max(0.0, _to_float(pf_delta, 0.0)) * 100.0, 3) if comparison_available else None,
            "shadow_underperformance_pct": _round(max(0.0, -_to_float(pf_delta, 0.0)) * 100.0, 3) if comparison_available else None,
            "profit_factor_delta": _round_or_none(pf_delta, 4),
            "win_rate_delta": _round_or_none(wr_delta, 4),
            "avg_return_delta": _round_or_none(avg_return_delta, 4),
            "profit_capture_delta": _round_or_none(capture_delta, 4),
            "exit_quality_delta": _round_or_none(exit_delta, 4),
            "comparison_available": comparison_available,
        }

    def _shadow_alpha(self, statuses: dict[str, dict[str, Any]], comparison: dict[str, Any], shadow: dict[str, Any]) -> dict[str, Any]:
        shadow_correction = _status(statuses, "shadow_correction_validation_attribution_v1")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        if not comparison.get("comparison_available"):
            return {
                "shadow_alpha_available": False,
                "shadow_alpha_score": None,
                "shadow_alpha_confidence": 0.0,
                "shadow_alpha_status": "INSUFFICIENT_EVIDENCE",
            }
        pf_delta = _to_float(comparison.get("profit_factor_delta"), 0.0)
        capture_delta = _to_float(comparison.get("profit_capture_delta"), 0.0)
        wr_delta = _to_float(comparison.get("win_rate_delta"), 0.0)
        exit_delta = _to_float(comparison.get("exit_quality_delta"), 0.0)
        score = _clamp(max(0.0, pf_delta) * 40.0 + max(0.0, capture_delta) * 0.15 + max(0.0, wr_delta) * 0.20 + max(0.0, exit_delta) * 0.10)
        confidence = _clamp(
            _to_float(shadow_correction.get("confidence_score"), 0.0) * 0.55
            + _to_float(protection.get("confidence_score"), 0.0) * 0.25
            + min(100.0, _to_int(shadow.get("shadow_trade_count"), 0) * 2.0) * 0.20
        )
        available = confidence >= 40.0 and _to_int(shadow.get("shadow_trade_count"), 0) >= MINIMUM_SHADOW_SAMPLE_SIZE
        return {
            "shadow_alpha_available": available,
            "shadow_alpha_score": _round_or_none(score, 3) if available else None,
            "shadow_alpha_confidence": _round(confidence, 3),
            "shadow_alpha_status": "PASS" if available else "INSUFFICIENT_EVIDENCE",
        }

    def _source_attribution(self, statuses: dict[str, dict[str, Any]], alpha: dict[str, Any]) -> list[dict[str, Any]]:
        shadow = _status(statuses, "shadow_correction_validation_attribution_v1")
        protection = _status(statuses, "controlled_paper_profit_protection_pilot_v1")
        lifecycle = _status(statuses, "catalyst_lifecycle_intelligence_v1")
        decay = _status(statuses, "catalyst_persistence_decay_curves_v2")
        flow = _status(statuses, "cross_sector_capital_flow_memory_v1")
        alpha_score = _to_float(alpha.get("shadow_alpha_score"), 0.0) if alpha.get("shadow_alpha_available") else 0.0

        def _row(name: str, reviewed: Any, validated: Any, confidence: Any, multiplier: float) -> dict[str, Any]:
            reviewed_i = max(0, _to_int(reviewed, 0))
            validated_i = max(0, min(reviewed_i, _to_int(validated, 0)))
            rejected_i = max(0, reviewed_i - validated_i)
            est_return = max(0.0, alpha_score * multiplier * 0.01) if alpha_score > 0 else 0.0
            est_pf = max(0.0, alpha_score * multiplier * 0.006) if alpha_score > 0 else 0.0
            return {
                "source": name,
                "recommendations_reviewed": reviewed_i,
                "recommendations_validated": validated_i,
                "recommendations_rejected": rejected_i,
                "estimated_return_delta": _round(est_return, 4),
                "estimated_profit_factor_delta": _round(est_pf, 4),
                "confidence_score": _round(confidence, 3),
            }

        categories = {row.get("category"): row for row in (shadow.get("validation_categories") or []) if isinstance(row, dict)}
        return [
            _row("candidate_ranking_influence", categories.get("candidate_ranking", {}).get("evidence_count"), categories.get("candidate_ranking", {}).get("validation_count"), categories.get("candidate_ranking", {}).get("confidence_score"), 0.18),
            _row("buy_purity_influence", categories.get("buy_purity", {}).get("evidence_count"), categories.get("buy_purity", {}).get("validation_count"), categories.get("buy_purity", {}).get("confidence_score"), 0.16),
            _row("opportunity_cost_influence", categories.get("opportunity_cost", {}).get("evidence_count"), categories.get("opportunity_cost", {}).get("validation_count"), categories.get("opportunity_cost", {}).get("confidence_score"), 0.15),
            _row("profit_protection_pilot", protection.get("recommendation_count"), protection.get("validated_profit_lock_events"), protection.get("confidence_score"), 0.17),
            _row("catalyst_lifecycle_intelligence", lifecycle.get("evidence_count"), lifecycle.get("evidence_count"), lifecycle.get("catalyst_lifecycle_confidence"), 0.12),
            _row("catalyst_decay_intelligence", decay.get("catalysts_tracked"), decay.get("catalysts_tracked"), decay.get("catalyst_decay_confidence"), 0.12),
            _row("cross_sector_capital_flow_memory", flow.get("evidence_count"), flow.get("evidence_count"), flow.get("sector_flow_confidence"), 0.10),
        ]

    def _cohorts(self, paper: dict[str, Any]) -> dict[str, Any]:
        current_pf = paper.get("paper_profit_factor_verified")
        current_avg = paper.get("paper_avg_return")
        current_capture = paper.get("paper_profit_capture")
        current_count = _to_int(paper.get("canonical_closed_trade_count"), 0)
        current_confidence = 100.0 if paper.get("paper_profit_factor_available") else min(35.0, current_count * 1.5)
        rows = []
        for cohort in BUILD_COHORTS:
            if cohort == "current_astra":
                rows.append({
                    "cohort": cohort,
                    "available": current_pf is not None,
                    "cohort_trade_count": current_count,
                    "cohort_profit_factor_verified": _round_or_none(current_pf, 4),
                    "cohort_avg_return": _round_or_none(current_avg, 4),
                    "cohort_profit_capture": _round_or_none(current_capture, 4),
                    "cohort_confidence": _round(current_confidence, 3),
                    "cohort_status": "PASS" if current_pf is not None else "INSUFFICIENT_EVIDENCE",
                    "cohort_mapping_source": "canonical_current_astra_only",
                })
            else:
                rows.append({
                    "cohort": cohort,
                    "available": False,
                    "cohort_trade_count": 0,
                    "cohort_profit_factor_verified": None,
                    "cohort_avg_return": None,
                    "cohort_profit_capture": None,
                    "cohort_confidence": 0.0,
                    "cohort_status": "INSUFFICIENT_EVIDENCE",
                    "cohort_mapping_source": "historical_build_split_unavailable_do_not_mix_with_current_astra",
                })
        return {
            "build_cohort_comparison": rows,
            "cohort_profit_factor": {row["cohort"]: row["cohort_profit_factor_verified"] for row in rows},
            "cohort_avg_return": {row["cohort"]: row["cohort_avg_return"] for row in rows},
            "cohort_profit_capture": {row["cohort"]: row["cohort_profit_capture"] for row in rows},
            "cohort_trade_count": {row["cohort"]: row["cohort_trade_count"] for row in rows},
            "cohort_profit_factor_verified": {row["cohort"]: row["cohort_profit_factor_verified"] for row in rows},
            "cohort_confidence": {row["cohort"]: row["cohort_confidence"] for row in rows},
        }

    def _reconciliation(self, paper: dict[str, Any], shadow: dict[str, Any], cohorts: dict[str, Any]) -> dict[str, Any]:
        verified_pf = paper.get("paper_profit_factor_verified")
        raw_pf = paper.get("paper_profit_factor_raw")
        verified_avg = paper.get("paper_avg_return")
        raw_returns = paper.get("paper_returns") or []
        raw_avg = _avg(raw_returns)
        paper_pf_matches = verified_pf is not None and (raw_pf is None or abs(_to_float(verified_pf, 0.0) - _to_float(raw_pf, 0.0)) <= 0.0001)
        paper_returns_match = verified_avg is not None and (raw_avg is None or abs(_to_float(verified_avg, 0.0) - _to_float(raw_avg, 0.0)) <= 0.0001)
        evidence_matches = _to_int(paper.get("canonical_closed_trade_count"), 0) >= _to_int(paper.get("paper_returns_count"), 0)
        current_pf = (cohorts.get("cohort_profit_factor_verified") or {}).get("current_astra")
        current_count = (cohorts.get("cohort_trade_count") or {}).get("current_astra")
        cohort_matches = current_pf == verified_pf and _to_int(current_count, 0) == _to_int(paper.get("canonical_closed_trade_count"), 0)
        if paper_pf_matches and paper_returns_match and evidence_matches and cohort_matches:
            status = "PASS"
        elif not paper.get("paper_profit_factor_available"):
            status = "INSUFFICIENT_EVIDENCE"
        else:
            status = "WARNING"
        if not shadow.get("shadow_profit_factor_available") and status == "PASS":
            shadow_status = "INSUFFICIENT_EVIDENCE"
        else:
            shadow_status = shadow.get("shadow_profit_factor_status", "INSUFFICIENT_EVIDENCE")
        return {
            "paper_pf_matches_unified": bool(paper_pf_matches),
            "paper_returns_match_unified": bool(paper_returns_match),
            "evidence_matches_unified": bool(evidence_matches),
            "cohort_matches_unified": bool(cohort_matches),
            "overall_reconciliation_status": status,
            "reconciliation_status": status,
            "paper_reconciliation_status": "PASS" if paper_pf_matches and paper_returns_match and evidence_matches else "WARNING",
            "shadow_reconciliation_status": shadow_status,
            "insufficient_evidence": not bool(shadow.get("shadow_profit_factor_available")) or not bool(paper.get("paper_profit_factor_available")),
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        start = time.perf_counter()
        paper = self._paper_canonical(statuses)
        shadow = self._shadow_metrics(statuses, paper)
        rolling = self._rolling_windows(paper.get("paper_returns") or [], shadow.get("shadow_returns") or [])
        comparison = self._comparison(paper, shadow)
        alpha = self._shadow_alpha(statuses, comparison, shadow)
        sources = self._source_attribution(statuses, alpha)
        cohorts = self._cohorts(paper)
        reconciliation = self._reconciliation(paper, shadow, cohorts)

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only_vs_paper_performance_attribution",
            "generated_at": _now_iso(),
            "minimum_pf_sample_size": MINIMUM_PF_SAMPLE_SIZE,
            "minimum_shadow_sample_size": MINIMUM_SHADOW_SAMPLE_SIZE,
            "minimum_lifecycle_count": MINIMUM_LIFECYCLE_COUNT,
            "canonical_source_signature": self._source_signature(),
            "trade_count": _to_int(paper.get("canonical_closed_trade_count"), 0),
            **paper,
            **shadow,
            **comparison,
            **rolling,
            **alpha,
            **cohorts,
            **reconciliation,
            "source_attribution": sources,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "dashboard_scan_rows": 0,
            "raw_archive_scanned": False,
            "raw_history_scanned": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "forced_exits_enabled": False,
            "forced_trades_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "thresholds_changed": False,
            "behavior_safe_to_apply": False,
            "shadow_recommendation": "Use shadow-vs-paper attribution as reconciled observational evidence only; require sufficient verified shadow lifecycle evidence before trusting PF comparisons.",
            "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
        }
        out.pop("paper_returns", None)
        out.pop("shadow_returns", None)
        _write_json(self.cache_path, out)
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = _round(now - self._cache_ts, 3)
            out["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
            return out
        if not force:
            disk = _read_json(self.cache_path)
            if disk:
                try:
                    age = max(0.0, time.time() - os.path.getmtime(self.cache_path))
                except Exception:
                    age = 999999.0
                if age <= self.ttl_seconds:
                    disk["cache_hit"] = True
                    disk["cache_age_seconds"] = _round(age, 3)
                    disk["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
                    self._cache = dict(disk)
                    self._cache_ts = now - age
                    return disk
        try:
            out = self._build(dict(statuses or {}))
        except Exception as exc:
            out = {
                "enabled": False,
                "version": VERSION,
                "mode": "shadow_only_vs_paper_performance_attribution",
                "degraded_reason": f"shadow_vs_paper_performance_attribution_unavailable:{str(exc)[:140]}",
                "canonical_performance_source": "unavailable",
                "canonical_closed_trade_count": 0,
                "paper_profit_factor_verified": None,
                "shadow_profit_factor_verified": None,
                "shadow_alpha_available": False,
                "shadow_alpha_score": None,
                "shadow_alpha_confidence": 0.0,
                "overall_reconciliation_status": "WARNING",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "forced_exits_enabled": False,
                "forced_trades_enabled": False,
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "entry_behavior_changed": False,
                "exit_behavior_changed": False,
                "position_sizing_changed": False,
                "portfolio_allocation_changed": False,
                "thresholds_changed": False,
                "behavior_safe_to_apply": False,
                "build_ms": _round((time.perf_counter() - start) * 1000.0, 3),
            }
        self._cache = dict(out)
        self._cache_ts = time.time()
        return out
