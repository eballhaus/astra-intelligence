from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1800
DAILY_WRITE_INTERVAL_SECONDS = 120.0

CONFIDENCE_BUCKETS = (
    "95_to_100",
    "90_to_94",
    "85_to_89",
    "80_to_84",
    "70_to_79",
    "below_70",
    "unknown_confidence",
)
GRADE_BUCKETS = ("A", "B", "C", "D/F", "unknown")
HORIZONS = ("scalp", "day_trade", "short_swing", "swing", "unknown")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


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


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


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


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    except Exception:
        return


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(median(values), 4) if values else None


def _profit_factor(returns: list[float]) -> float | None:
    gains = sum(v for v in returns if v > 0)
    losses = abs(sum(v for v in returns if v < 0))
    if gains <= 0 and losses <= 0:
        return None
    if losses <= 0:
        return round(gains, 4) if gains > 0 else None
    return round(gains / losses, 4)


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("asset_symbol"), "unknown").upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(
        row,
        "current_or_exit_profit_pct",
        "actual_return_pct",
        "realized_return_pct",
        "current_return_pct",
        "exit_gain_pct",
        "return_pct",
        "pnl_pct",
        default=0.0,
    )


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "peak_gain_pct", "average_mfe_pct", "mfe_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct", "average_mae_pct", "mae_pct")


def _giveback(row: dict[str, Any]) -> float:
    return _value(row, "profit_giveback_pct", "giveback_from_peak_pct", "current_giveback_pct", "average_profit_giveback_pct")


def _capture_ratio(row: dict[str, Any]) -> float:
    raw = _value(row, "profit_capture_ratio", "capture_ratio", "average_profit_capture_ratio", default=-1.0)
    if raw < 0:
        peak = _mfe(row)
        ret = _return_pct(row)
        if peak > 0:
            return _clamp(ret / peak, 0.0, 1.25)
        return 0.0
    if raw > 1.5:
        return _clamp(raw / 100.0, 0.0, 1.25)
    return _clamp(raw, 0.0, 1.25)


def _hold_minutes(row: dict[str, Any]) -> float:
    return _value(row, "hold_duration_minutes", "actual_hold_duration_minutes", "hold_time_minutes", "average_hold_duration_minutes")


def _confidence(row: dict[str, Any]) -> float | None:
    for key in (
        "confidence",
        "confidence_score",
        "entry_confidence",
        "conviction_score",
        "opportunity_confidence",
        "selection_confidence",
        "counterfactual_confidence",
        "market_knowledge_confidence",
        "confidence_pct",
    ):
        if row.get(key) not in (None, ""):
            val = _to_float(row.get(key))
            if 0.0 < val <= 1.5:
                val *= 100.0
            return _clamp(val)
    return None


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown_confidence"
    val = _clamp(value)
    if val >= 95:
        return "95_to_100"
    if val >= 90:
        return "90_to_94"
    if val >= 85:
        return "85_to_89"
    if val >= 80:
        return "80_to_84"
    if val >= 70:
        return "70_to_79"
    return "below_70"


def _grade(row: dict[str, Any], confidence: float | None) -> str:
    raw = _text(row.get("grade") or row.get("letter_grade") or row.get("candidate_grade") or row.get("quality_grade"), "").upper()
    if raw.startswith("A"):
        return "A"
    if raw.startswith("B"):
        return "B"
    if raw.startswith("C"):
        return "C"
    if raw.startswith("D") or raw.startswith("F"):
        return "D/F"
    if confidence is None:
        return "unknown"
    if confidence >= 90:
        return "A"
    if confidence >= 80:
        return "B"
    if confidence >= 70:
        return "C"
    return "D/F"


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("recommended_horizon") or row.get("hold_duration_bucket"), "").lower()
    hold = _hold_minutes(row)
    if "scalp" in raw or (hold and hold < 30):
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if raw in {"swing", "multi_day_swing", "overnight_swing"} or (hold and hold >= 1440):
        return "swing"
    if "day" in raw or (hold and hold < 390):
        return "day_trade"
    if "swing" in raw:
        return "short_swing"
    return "unknown"


def _normalized_trade(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    symbol = _symbol(row)
    if not symbol or symbol == "UNKNOWN":
        return None
    conf = _confidence(row)
    ret = _return_pct(row)
    out = {
        "symbol": symbol,
        "source": source,
        "return_pct": ret,
        "confidence": conf,
        "confidence_bucket": _confidence_bucket(conf),
        "grade": _grade(row, conf),
        "horizon": _horizon(row),
        "archetype": _text(row.get("trade_archetype") or row.get("archetype") or row.get("selected_opportunity_type"), "unknown"),
        "regime": _text(row.get("market_regime") or row.get("regime") or row.get("session_type"), "unknown"),
        "sector": _text(row.get("sector") or row.get("sector_context_label"), "unknown"),
        "cap_tier": _text(row.get("cap_tier") or row.get("market_cap_tier") or row.get("market_cap_bucket"), "unknown"),
        "mfe": _mfe(row),
        "mae": _mae(row),
        "giveback": _giveback(row),
        "capture_ratio": _capture_ratio(row),
        "hold_minutes": _hold_minutes(row),
        "timestamp": _text(row.get("generated_at") or row.get("timestamp") or row.get("current_timestamp") or row.get("entry_timestamp"), ""),
    }
    return out


def _strict_broker_truth(row: dict[str, Any]) -> bool:
    """Return only complete, current broker truths for calibration.

    Calibration must never promote replay, shadow, or legacy reconstruction
    outcomes into the broker-confirmed sample simply because they have a
    confidence-shaped field.
    """
    quality = _text(row.get("evidence_class") or row.get("truth_quality")).upper()
    source = _text(row.get("source") or row.get("source_bucket") or row.get("ownership_status")).upper()
    return (
        quality == "BROKER_CONFIRMED_COMPLETE"
        and bool(_text(row.get("entry_fill_id")))
        and bool(_text(row.get("exit_fill_id")))
        and not any(token in source for token in ("LEGACY", "RECONSTRUCT", "HISTORICAL", "SHADOW", "REPLAY"))
    )


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = f"{row.get('symbol')}|{row.get('timestamp') or row.get('source')}|{row.get('return_pct')}"
        current = best.get(key)
        if current is None or (row.get("source") == "lifecycle" and current.get("source") != "lifecycle"):
            best[key] = row
    return list(best.values())[-MAX_ROWS:]


def _bucket_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [_to_float(r.get("return_pct")) for r in rows]
    positives = [r for r in rows if _to_float(r.get("return_pct")) > 0]
    best = max(rows, key=lambda r: _to_float(r.get("return_pct")), default={})
    worst = min(rows, key=lambda r: _to_float(r.get("return_pct")), default={})
    avg_return = _avg(returns)
    avg_mfe = _avg([_to_float(r.get("mfe")) for r in rows])
    avg_mae = _avg([_to_float(r.get("mae")) for r in rows])
    avg_giveback = _avg([_to_float(r.get("giveback")) for r in rows])
    avg_capture = _avg([_to_float(r.get("capture_ratio")) for r in rows])
    win_rate = round(len(positives) / max(1, len(rows)) * 100.0, 4) if rows else 0.0
    truth = 0.0
    if rows:
        truth = _clamp(35.0 + max(-20.0, min(35.0, (avg_return or 0.0) * 4.0)) + (win_rate - 50.0) * 0.35 + (_to_float(avg_capture) * 15.0))
    return {
        "trade_count": len(rows),
        "win_rate": win_rate,
        "avg_return": avg_return,
        "median_return": _median(returns),
        "profit_factor": _profit_factor(returns),
        "avg_mfe": avg_mfe,
        "avg_mae": avg_mae,
        "avg_giveback": avg_giveback,
        "avg_capture_ratio": avg_capture,
        "avg_hold_time": _avg([_to_float(r.get("hold_minutes")) for r in rows]),
        "best_symbol": best.get("symbol", "insufficient_data"),
        "worst_symbol": worst.get("symbol", "insufficient_data"),
        "confidence_truth_score": round(truth, 4),
    }


def _group(rows: list[dict[str, Any]], key: str, buckets: tuple[str, ...] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_text(row.get(key), "unknown")].append(row)
    out: dict[str, dict[str, Any]] = {}
    for bucket in buckets or tuple(sorted(grouped.keys())):
        out[bucket] = _bucket_summary(grouped.get(bucket, []))
    return out


def _best_worst(summary: dict[str, dict[str, Any]], score_key: str = "avg_return") -> tuple[str, str]:
    eligible = [(k, v) for k, v in summary.items() if _to_int(v.get("trade_count"), 0) > 0]
    if not eligible:
        return "insufficient_data", "insufficient_data"
    def score(item: tuple[str, dict[str, Any]]) -> float:
        payload = item[1]
        if payload.get(score_key) is None:
            return -999999.0
        return _to_float(payload.get(score_key))
    best = max(eligible, key=score)[0]
    worst = min(eligible, key=score)[0]
    return best, worst


def _attribution(rows: list[dict[str, Any]], key: str, limit: int = 8) -> dict[str, float]:
    grouped: dict[str, float] = defaultdict(float)
    for row in rows:
        label = _text(row.get(key), "unknown")
        if not label:
            label = "unknown"
        grouped[label] += _to_float(row.get("return_pct"))
    ordered = sorted(grouped.items(), key=lambda item: item[1], reverse=True)[:limit]
    return {k: round(v, 4) for k, v in ordered}


def _top_label(grouped: dict[str, float], positive: bool = True) -> str:
    if not grouped:
        return "insufficient_data"
    return (max if positive else min)(grouped.items(), key=lambda item: item[1])[0]


def _monotonicity(values: list[float]) -> float:
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return 0.0
    comparisons = 0
    good = 0
    for left, right in zip(vals, vals[1:]):
        comparisons += 1
        if left >= right:
            good += 1
    return round(good / max(1, comparisons) * 100.0, 4)


class ConfidenceCalibrationPerformanceAttributionV1:
    """Shadow-only confidence, grade, attribution, and daily paper performance diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_daily_write = 0.0
        self.state_path = os.path.join(self.state_dir, "confidence_calibration_performance_attribution_v1.jsonl")
        self.daily_state_path = os.path.join(self.state_dir, "confidence_calibration_daily_portfolio_v1.jsonl")

    def _rows(self, name: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit)

    def _strict_truth_calibration_rows(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Join completed broker truth to its immutable entry-time confidence.

        The strict registry is the canonical owner of complete paper outcomes.
        We deliberately reject a record without pretrade confidence instead of
        deriving confidence from its closed result.
        """
        path = os.path.join(self.state_dir, "broker_truth_records_v1.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                registry = json.load(handle)
            records = list(registry.get("records") or []) if isinstance(registry, dict) else []
        except Exception:
            records = []

        rows: list[dict[str, Any]] = []
        strict_seen = linked = missing_prediction = missing_outcome = 0
        unlinked_ids: list[str] = []
        for raw in records[-MAX_ROWS:]:
            if not isinstance(raw, dict) or not _strict_broker_truth(raw):
                continue
            strict_seen += 1
            context = raw.get("pretrade_context_v1")
            context = dict(context) if isinstance(context, dict) else {}
            confidence = _confidence(context)
            outcome = raw.get("realized_return")
            if outcome in (None, ""):
                outcome = raw.get("return_percent")
            truth_id = _text(raw.get("stable_key") or raw.get("lifecycle_id"))
            prediction_id = _text(
                context.get("candidate_id") or context.get("recommendation_id")
                or context.get("selection_id") or context.get("decision_id")
                or context.get("entry_contract_id") or raw.get("candidate_id")
                or raw.get("recommendation_id") or raw.get("selection_id")
            )
            if confidence is None or not prediction_id:
                missing_prediction += 1
                if truth_id:
                    unlinked_ids.append(truth_id)
                continue
            if outcome in (None, ""):
                missing_outcome += 1
                if truth_id:
                    unlinked_ids.append(truth_id)
                continue
            normalized = _normalized_trade({
                **raw,
                **context,
                "confidence": confidence,
                "realized_return_pct": outcome,
                "timestamp": raw.get("exit_time") or raw.get("created_at"),
            }, "strict_broker_truth")
            if normalized is None:
                missing_outcome += 1
                continue
            normalized.update({
                "truth_id": truth_id,
                "prediction_id": prediction_id,
                "prediction_timestamp": context.get("observation_timestamp") or context.get("forecast_timestamp") or context.get("market_data_timestamp"),
                "outcome_timestamp": raw.get("exit_time") or raw.get("created_at"),
                "linkage_status": "LINKED_PRE_OUTCOME_PREDICTION_TO_STRICT_BROKER_TRUTH",
            })
            rows.append(normalized)
            linked += 1
        return rows, {
            "calibration_evidence_source": "broker_truth_records_v1.strict_broker_confirmed_complete",
            "strict_truth_records_seen": strict_seen,
            "strict_truth_records_linked": linked,
            "strict_truth_records_missing_pre_outcome_prediction": missing_prediction,
            "strict_truth_records_missing_closed_outcome": missing_outcome,
            "unlinked_truth_ids": unlinked_ids[:20],
            "closed_outcome_linkage_status": (
                "LINKED" if linked else "INSUFFICIENT_EVIDENCE" if strict_seen == 0 else "PARTIAL"
            ),
            "closed_outcome_linkage_fail_closed": True,
        }

    def _collect_trades(self) -> list[dict[str, Any]]:
        sources = {
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 700) + self._rows("trade_lifecycle_excursion_v1.jsonl", 360),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 700),
            "archetype_regime": self._rows("trade_archetype_regime_intelligence_v1.jsonl", 420),
            "replay": self._rows("replay_counterfactual_learning_v2.jsonl", 420),
            "paper_journal": self._rows("paper_trade_journal.jsonl", 260),
        }
        normalized: list[dict[str, Any]] = []
        for source, rows in sources.items():
            for row in rows:
                trade = _normalized_trade(row, source)
                if trade:
                    normalized.append(trade)
        return _dedupe(normalized)

    def _confidence_horizon_matrix(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        matrix: dict[str, dict[str, dict[str, Any]]] = {}
        pairs: list[tuple[str, dict[str, Any]]] = []
        for bucket in CONFIDENCE_BUCKETS:
            matrix[bucket] = {}
            for horizon in HORIZONS:
                subset = [r for r in rows if r.get("confidence_bucket") == bucket and r.get("horizon") == horizon]
                summary = _bucket_summary(subset)
                matrix[bucket][horizon] = summary
                if summary["trade_count"]:
                    pairs.append((f"{bucket}+{horizon}", summary))
        if pairs:
            best = max(pairs, key=lambda item: _to_float(item[1].get("avg_return"), -9999.0))[0]
            worst = min(pairs, key=lambda item: _to_float(item[1].get("avg_return"), 9999.0))[0]
        else:
            best = worst = "insufficient_data"
        return {
            "confidence_bucket_by_horizon": matrix,
            "avg_return_by_confidence_and_horizon": {pair: summary.get("avg_return") for pair, summary in pairs[:20]},
            "win_rate_by_confidence_and_horizon": {pair: summary.get("win_rate") for pair, summary in pairs[:20]},
            "profit_factor_by_confidence_and_horizon": {pair: summary.get("profit_factor") for pair, summary in pairs[:20]},
            "best_confidence_horizon_pair": best,
            "worst_confidence_horizon_pair": worst,
        }

    def _sizing_readiness(self, confidence_summary: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
        ordered_returns = [
            _to_float((confidence_summary.get(bucket) or {}).get("avg_return"), 0.0)
            for bucket in CONFIDENCE_BUCKETS[:-1]
            if (confidence_summary.get(bucket) or {}).get("avg_return") is not None
        ]
        ordered_truth = [
            _to_float((confidence_summary.get(bucket) or {}).get("confidence_truth_score"), 0.0)
            for bucket in CONFIDENCE_BUCKETS[:-1]
            if (confidence_summary.get(bucket) or {}).get("confidence_truth_score") is not None
        ]
        sample_size_by_bucket = {bucket: _to_int((confidence_summary.get(bucket) or {}).get("trade_count"), 0) for bucket in CONFIDENCE_BUCKETS}
        min_bucket_sample = min([v for k, v in sample_size_by_bucket.items() if k != "unknown_confidence"] or [0])
        return_mono = _monotonicity(ordered_returns)
        risk_mono = _monotonicity(ordered_truth)
        consistency = _clamp(sum(1 for v in sample_size_by_bucket.values() if v >= 5) / max(1, len(CONFIDENCE_BUCKETS)) * 100.0)
        drawdown_by_bucket = {bucket: _round((confidence_summary.get(bucket) or {}).get("avg_mae"), 4) for bucket in CONFIDENCE_BUCKETS}
        predictive = _clamp((return_mono * 0.45) + (risk_mono * 0.35) + (consistency * 0.20))
        score = _clamp(predictive * 0.7 + min(30.0, len(rows) / 2.0))
        ready = bool(score >= 85.0 and min_bucket_sample >= 20 and return_mono >= 75.0 and risk_mono >= 70.0)
        reason = "strong_bucket_evidence_required_before_any_sizing_change"
        if not rows:
            reason = "no_trade_evidence_available"
        elif min_bucket_sample < 20:
            reason = "minimum_evidence_needed_per_confidence_bucket"
        elif return_mono < 75.0:
            reason = "returns_are_not_monotonic_by_confidence_yet"
        elif risk_mono < 70.0:
            reason = "risk_adjusted_results_are_not_monotonic_yet"
        return {
            "confidence_predictive_power": _round(predictive, 2),
            "sample_size_by_bucket": sample_size_by_bucket,
            "bucket_consistency": _round(consistency, 2),
            "return_monotonicity": _round(return_mono, 2),
            "risk_adjusted_monotonicity": _round(risk_mono, 2),
            "drawdown_by_bucket": drawdown_by_bucket,
            "sizing_readiness_score": _round(score, 2),
            "ready_for_confidence_weighted_sizing": False if not ready else False,
            "recommended_future_sizing_policy_shadow_only": "review_confidence_weighted_sizing_only_after_monotonic_multi_bucket_evidence",
            "reason_not_ready": reason,
            "minimum_evidence_needed": "at_least_20_broker_confirmed_outcomes_per_confidence_bucket_with_monotonic_return_and_drawdown_behavior",
        }

    def _daily_performance(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        broker = dict(statuses.get("alpaca_paper_broker") or statuses.get("alpaca_paper_status") or {})
        equity = _to_float(broker.get("equity"), _to_float(broker.get("account_equity"), _to_float(broker.get("portfolio_value"), 0.0)))
        last_equity = _to_float(broker.get("last_equity"), _to_float(broker.get("previous_equity"), 0.0))
        portfolio_value = _to_float(broker.get("portfolio_value"), equity)
        long_market_value = _to_float(broker.get("long_market_value"), _to_float(broker.get("market_value"), 0.0))
        cash = _to_float(broker.get("cash"), _to_float(broker.get("buying_power"), 0.0))
        daily_pnl = _to_float(broker.get("daily_pnl"), 0.0)
        if daily_pnl == 0.0 and equity and last_equity:
            daily_pnl = equity - last_equity
        daily_return_pct = _to_float(broker.get("daily_return_pct"), 0.0)
        if daily_return_pct == 0.0 and daily_pnl and last_equity:
            daily_return_pct = daily_pnl / last_equity * 100.0
        snapshot_available = bool(equity or portfolio_value or daily_pnl or daily_return_pct)
        if snapshot_available and time.time() - self._last_daily_write >= DAILY_WRITE_INTERVAL_SECONDS:
            _append_jsonl(
                self.daily_state_path,
                {
                    "date": _today_key(),
                    "timestamp": _now_iso(),
                    "equity": equity,
                    "last_equity": last_equity,
                    "portfolio_value": portfolio_value,
                    "long_market_value": long_market_value,
                    "cash": cash,
                    "daily_pnl": daily_pnl,
                    "daily_return_pct": daily_return_pct,
                    "source": "alpaca_paper_status_cached_fields",
                },
            )
            self._last_daily_write = time.time()
        rows = _tail_jsonl(self.daily_state_path, max_rows=240)
        by_day: dict[str, dict[str, Any]] = {}
        for row in rows:
            day = _text(row.get("date"), "")[:10]
            if day:
                by_day[day] = row
        if snapshot_available:
            by_day[_today_key()] = {"daily_return_pct": daily_return_pct, "daily_pnl": daily_pnl, "date": _today_key()}
        returns = [_to_float(row.get("daily_return_pct")) for _, row in sorted(by_day.items())]
        positive = sum(1 for value in returns if value > 0.02)
        negative = sum(1 for value in returns if value < -0.02)
        flat = max(0, len(returns) - positive - negative)
        current_return = daily_return_pct if snapshot_available else (returns[-1] if returns else 0.0)
        current_pnl = daily_pnl if snapshot_available else _to_float((list(by_day.values())[-1] if by_day else {}).get("daily_pnl"), 0.0)
        best_day = max(by_day.items(), key=lambda item: _to_float(item[1].get("daily_return_pct")), default=("insufficient_data", {}))
        worst_day = min(by_day.items(), key=lambda item: _to_float(item[1].get("daily_return_pct")), default=("insufficient_data", {}))
        status = "positive" if current_return > 0.02 else "negative" if current_return < -0.02 else "flat_or_unavailable"
        daily_positive_rate = round(positive / max(1, positive + negative + flat) * 100.0, 4) if returns else 0.0
        return {
            "equity": _round(equity, 4),
            "last_equity": _round(last_equity, 4),
            "portfolio_value": _round(portfolio_value, 4),
            "long_market_value": _round(long_market_value, 4),
            "cash": _round(cash, 4),
            "daily_pnl": _round(current_pnl, 4),
            "daily_return_pct": _round(current_return, 4),
            "positive_days": positive,
            "negative_days": negative,
            "flat_days": flat,
            "daily_positive_rate": daily_positive_rate,
            "avg_daily_return": _avg(returns) if returns else None,
            "rolling_5_day_return": _round(sum(returns[-5:]), 4) if returns else 0.0,
            "rolling_20_day_return": _round(sum(returns[-20:]), 4) if returns else 0.0,
            "best_day": {"date": best_day[0], "return_pct": _round(best_day[1].get("daily_return_pct"), 4)},
            "worst_day": {"date": worst_day[0], "return_pct": _round(worst_day[1].get("daily_return_pct"), 4)},
            "current_day_return": _round(current_return, 4),
            "current_day_pnl": _round(current_pnl, 4),
            "daily_profitability_score": _round(_clamp(50.0 + current_return * 8.0 + (daily_positive_rate - 50.0) * 0.4), 2),
            "current_day_status": status,
            "rolling_performance_summary": f"{len(returns)} daily snapshots tracked; current day is {status.replace('_', ' ')}.",
            "daily_snapshot_source": "alpaca_paper_status_cached_fields" if snapshot_available else "insufficient_alpaca_account_fields",
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        started = time.perf_counter()
        # Broker-confirmed, entry-time-linked outcomes are the calibration
        # sample. Mixed lifecycle/replay rows remain a diagnostic context only.
        rows, linkage = self._strict_truth_calibration_rows()
        diagnostic_context_rows = self._collect_trades()
        confidence_summary = _group(rows, "confidence_bucket", CONFIDENCE_BUCKETS)
        grade_summary = _group(rows, "grade", GRADE_BUCKETS)
        best_conf_bucket, worst_conf_bucket = _best_worst(confidence_summary, "avg_return")
        best_grade, weakest_grade = _best_worst(grade_summary, "avg_return")
        matrix = self._confidence_horizon_matrix(rows)
        sizing = self._sizing_readiness(confidence_summary, rows)
        profit_by_symbol = _attribution(rows, "symbol", 12)
        profit_by_horizon = _attribution(rows, "horizon")
        profit_by_archetype = _attribution(rows, "archetype")
        profit_by_regime = _attribution(rows, "regime")
        profit_by_confidence_bucket = _attribution(rows, "confidence_bucket")
        profit_by_grade = _attribution(rows, "grade")
        profit_by_market_cap_tier = _attribution(rows, "cap_tier")
        profit_by_sector = _attribution(rows, "sector")
        total_abs = sum(abs(_to_float(v)) for v in profit_by_symbol.values())
        largest_winner = _top_label(profit_by_symbol, True)
        largest_loser = _top_label(profit_by_symbol, False)
        largest_winner_contribution = _to_float(profit_by_symbol.get(largest_winner), 0.0)
        concentration = abs(largest_winner_contribution) / max(0.0001, total_abs) * 100.0 if total_abs else 0.0
        confidence_calibration_score = _round(sizing["confidence_predictive_power"], 2)
        grade_predictive_power = _round(_clamp((_to_float((grade_summary.get("A") or {}).get("avg_return")) - _to_float((grade_summary.get("D/F") or {}).get("avg_return"))) * 7.0 + 50.0), 2)
        daily = self._daily_performance(statuses)
        recommendation = "keep_confidence_and_grade_sizing_shadow_only_until_bucket_evidence_is_monotonic_and_broad"
        if confidence_calibration_score >= 70 and len(rows) >= 50:
            recommendation = "confidence_is_becoming_predictive_but_position_sizing_changes_still_require_human_review"
        if confidence_calibration_score < 45 and len(rows) >= 20:
            recommendation = "confidence_scores_need_recalibration_before_they_can_inform_future_sizing"
        out = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if rows else "insufficient_evidence",
            "mode": "paper_only_confidence_calibration_performance_attribution",
            "generated_at": _now_iso(),
            "evidence_count": len(rows),
            "diagnostic_context_evidence_count": len(diagnostic_context_rows),
            "diagnostic_context_sources": "lifecycle_profit_capture_archetype_replay_paper_journal_non_authoritative",
            **linkage,
            "confidence_bucket_stats": confidence_summary,
            "grade_bucket_stats": grade_summary,
            "best_confidence_bucket": best_conf_bucket,
            "worst_confidence_bucket": worst_conf_bucket,
            "confidence_calibration_score": confidence_calibration_score,
            "confidence_predictive_power": sizing["confidence_predictive_power"],
            "confidence_sizing_readiness": sizing["sizing_readiness_score"],
            "best_grade": best_grade,
            "weakest_grade": weakest_grade,
            "grade_predictive_power": grade_predictive_power,
            "grade_calibration_score": grade_predictive_power,
            **matrix,
            **sizing,
            "profit_by_symbol": profit_by_symbol,
            "profit_by_horizon": profit_by_horizon,
            "profit_by_archetype": profit_by_archetype,
            "profit_by_regime": profit_by_regime,
            "profit_by_confidence_bucket": profit_by_confidence_bucket,
            "profit_by_grade": profit_by_grade,
            "profit_by_market_cap_tier": profit_by_market_cap_tier,
            "profit_by_sector": profit_by_sector,
            "largest_winner_contribution": _round(largest_winner_contribution, 4),
            "largest_loser_contribution": _round(profit_by_symbol.get(largest_loser), 4),
            "concentration_of_profit": _round(concentration, 2),
            "top_profit_driver": largest_winner,
            "top_loss_driver": largest_loser,
            "healthiest_profit_source": _top_label(profit_by_horizon, True),
            "most_fragile_profit_source": _top_label(profit_by_horizon, False),
            "concentration_warning": "profit_concentrated_in_one_symbol" if concentration >= 45.0 else "no_major_profit_concentration_detected",
            **daily,
            "shadow_recommendation": recommendation,
            "summary": "Astra calibrates entry-time confidence only against linked, broker-confirmed completed paper truths. Unlinked or non-broker evidence remains diagnostic context and cannot grade calibration.",
            "behavior_safe_to_apply": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "cache_hit": False,
            "build_ms": _round((time.perf_counter() - started) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        return out

    def status(self, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        if self._cache and not force and (time.time() - self._cache_ts) < self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            return cached
        try:
            out = self._build(dict(statuses or {}))
            if time.time() - self._last_daily_write >= 300.0:
                _append_jsonl(
                    self.state_path,
                    {
                        "timestamp": out.get("generated_at"),
                        "evidence_count": out.get("evidence_count"),
                        "confidence_calibration_score": out.get("confidence_calibration_score"),
                        "confidence_predictive_power": out.get("confidence_predictive_power"),
                        "sizing_readiness_score": out.get("sizing_readiness_score"),
                        "top_profit_driver": out.get("top_profit_driver"),
                        "current_day_return": out.get("current_day_return"),
                        "behavior_safe_to_apply": False,
                    },
                )
            self._cache = dict(out)
            self._cache_ts = time.time()
            return out
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "status": "insufficient_evidence",
                "mode": "paper_only_confidence_calibration_performance_attribution",
                "evidence_count": 0,
                "diagnostic_context_evidence_count": 0,
                "calibration_evidence_source": "broker_truth_records_v1.strict_broker_confirmed_complete",
                "strict_truth_records_seen": 0,
                "strict_truth_records_linked": 0,
                "strict_truth_records_missing_pre_outcome_prediction": 0,
                "strict_truth_records_missing_closed_outcome": 0,
                "unlinked_truth_ids": [],
                "closed_outcome_linkage_status": "INSUFFICIENT_EVIDENCE",
                "closed_outcome_linkage_fail_closed": True,
                "best_confidence_bucket": "insufficient_data",
                "worst_confidence_bucket": "insufficient_data",
                "confidence_calibration_score": 0.0,
                "confidence_predictive_power": 0.0,
                "confidence_sizing_readiness": 0.0,
                "best_grade": "insufficient_data",
                "grade_predictive_power": 0.0,
                "best_confidence_horizon_pair": "insufficient_data",
                "worst_confidence_horizon_pair": "insufficient_data",
                "sizing_readiness_score": 0.0,
                "ready_for_confidence_weighted_sizing": False,
                "top_profit_driver": "insufficient_data",
                "top_loss_driver": "insufficient_data",
                "daily_positive_rate": 0.0,
                "current_day_return": 0.0,
                "current_day_status": "unavailable",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"confidence_calibration_performance_attribution_unavailable:{str(exc)[:140]}",
                "behavior_safe_to_apply": False,
                "auto_apply_allowed": False,
                "human_review_required": True,
                "api_calls_used": 0,
                "build_ms": 0.0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
            }
