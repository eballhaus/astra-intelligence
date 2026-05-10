from __future__ import annotations

import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    return int(round(_to_float(value, float(default))))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    txt = str(value or "").strip().lower()
    return txt in {"1", "true", "yes", "y", "on"}


def _norm_reason(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _reason_tokens(raw: Any) -> list[str]:
    txt = _norm_reason(raw)
    if not txt:
        return []
    pieces = re.split(r"[^a-z0-9_]+", txt)
    out: list[str] = []
    for token in pieces:
        token = token.strip("_")
        if len(token) < 3:
            continue
        out.append(token)
    return out


class ExitLearningEngine:
    """
    Exit Learning V2
    - Conservative, evidence-gated learning from closed trade outcomes.
    - Backward-compatible interface for existing server callers.
    """

    def __init__(
        self,
        db_path: str = "state/ai_trading_memory.db",
        ttl_seconds: int = 30,
        min_samples: int = 20,
    ):
        self.db_path = str(db_path or "state/ai_trading_memory.db")
        self.ttl_seconds = max(5, _to_int(ttl_seconds, 30))
        self.min_samples = max(10, _to_int(min_samples, 20))
        self._cache: dict[str, Any] = {"ts": 0.0, "summary": None}

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
        finally:
            conn.close()

    def _fetch_closed_rows(self, limit: int = 1800) -> list[dict[str, Any]]:
        n = max(50, min(5000, _to_int(limit, 1800)))
        query = """
            SELECT
                return_percent,
                friction_adjusted_return,
                exit_reason,
                drawdown_after_peak_percent,
                peak_unrealized_pnl_percent,
                max_favorable_excursion,
                time_to_exit_seconds,
                valid_label
            FROM trade_journal
            WHERE exit_timestamp IS NOT NULL
              AND return_percent IS NOT NULL
            ORDER BY exit_timestamp DESC
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(query, [n]).fetchall()
            return [dict(r or {}) for r in rows]
        except Exception:
            return []

    def _summarize(self) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get("summary")
        if cached and (now - _to_float(self._cache.get("ts"), 0.0)) <= float(self.ttl_seconds):
            return dict(cached)

        rows = self._fetch_closed_rows(limit=1800)
        sample_size = len(rows)
        if sample_size <= 0:
            summary = {
                "sample_size": 0,
                "evidence_strength": 0.0,
                "early_failure_rate": 0.0,
                "deterioration_rate": 0.0,
                "missed_profit_rate": 0.0,
                "hold_quality_rate": 0.0,
                "avg_return": 0.0,
                "avg_drawdown_from_peak": 0.0,
                "avg_missed_profit_gap": 0.0,
                "loss_condition_counts": {},
            }
            self._cache = {"ts": now, "summary": summary}
            return summary

        early_fail = 0
        deterioration = 0
        missed_profit = 0
        hold_quality = 0
        loss_conditions: dict[str, int] = {}
        valid_rows = 0
        sum_returns = 0.0
        sum_drawdown = 0.0
        drawdown_n = 0
        missed_gap_total = 0.0
        missed_gap_n = 0

        for row in rows:
            valid_label = _to_int(row.get("valid_label"), 1)
            ret = _to_float(row.get("return_percent"), 0.0)
            if valid_label <= 0:
                # Invalid labels still contribute weakly to failure pressure.
                ret = min(ret, 0.0)
            valid_rows += 1
            sum_returns += ret
            reason = _norm_reason(row.get("exit_reason"))
            dd = max(0.0, _to_float(row.get("drawdown_after_peak_percent"), 0.0))
            if dd > 0:
                sum_drawdown += dd
                drawdown_n += 1
            peak = max(
                _to_float(row.get("peak_unrealized_pnl_percent"), 0.0),
                _to_float(row.get("max_favorable_excursion"), 0.0),
                ret,
            )
            tte = max(0.0, _to_float(row.get("time_to_exit_seconds"), 0.0))

            is_early_fail = (
                ret <= -1.0
                or ("stop" in reason and "loss" in reason)
                or any(k in reason for k in ("invalidation", "breakdown", "failed"))
                or (tte > 0 and tte <= 3600 and ret < 0)
            )
            if is_early_fail:
                early_fail += 1

            is_deterioration = (
                any(k in reason for k in ("deterior", "overhold", "late", "drag"))
                or (dd >= 2.0 and ret <= 0.0)
            )
            if is_deterioration:
                deterioration += 1

            capture_ratio = (ret / peak) if peak > 0 else 0.0
            is_missed_profit = peak >= 2.0 and (peak - ret) >= 1.5 and ret >= 0.0
            if is_missed_profit:
                missed_profit += 1
                missed_gap_total += max(0.0, peak - ret)
                missed_gap_n += 1

            is_hold_quality = ret > 0.0 and capture_ratio >= 0.55 and dd <= 1.8
            if is_hold_quality:
                hold_quality += 1

            if ret < 0.0:
                tokens = _reason_tokens(reason)
                if not tokens:
                    loss_conditions["loss_unlabeled"] = loss_conditions.get("loss_unlabeled", 0) + 1
                else:
                    base = "_".join(tokens[:3])
                    if len(base) > 48:
                        base = base[:48]
                    loss_conditions[base] = loss_conditions.get(base, 0) + 1
                if dd >= 2.0:
                    loss_conditions["high_drawdown_after_peak"] = loss_conditions.get("high_drawdown_after_peak", 0) + 1
                if tte > 0 and tte <= 3600:
                    loss_conditions["rapid_failure"] = loss_conditions.get("rapid_failure", 0) + 1

        n = float(max(1, valid_rows))
        evidence_strength = _clamp(sample_size / 240.0, 0.0, 1.0)
        summary = {
            "sample_size": int(sample_size),
            "evidence_strength": round(evidence_strength, 4),
            "early_failure_rate": round(early_fail / n, 4),
            "deterioration_rate": round(deterioration / n, 4),
            "missed_profit_rate": round(missed_profit / n, 4),
            "hold_quality_rate": round(hold_quality / n, 4),
            "avg_return": round(sum_returns / n, 4),
            "avg_drawdown_from_peak": round((sum_drawdown / float(max(1, drawdown_n))), 4),
            "avg_missed_profit_gap": round((missed_gap_total / float(max(1, missed_gap_n))), 4),
            "loss_condition_counts": loss_conditions,
        }
        self._cache = {"ts": now, "summary": summary}
        return summary

    def learned_thresholds(self) -> dict:
        summary = self._summarize()
        n = _to_int(summary.get("sample_size"), 0)
        evidence = _to_float(summary.get("evidence_strength"), 0.0)
        early_fail = _to_float(summary.get("early_failure_rate"), 0.0)
        deterioration = _to_float(summary.get("deterioration_rate"), 0.0)
        missed_profit = _to_float(summary.get("missed_profit_rate"), 0.0)
        hold_quality = _to_float(summary.get("hold_quality_rate"), 0.0)

        if n < self.min_samples:
            return {
                "stop_loss_pct": 0.025,
                "take_profit_pct": 0.05,
                "probability_drop_sellwatch_threshold": 8.0,
                "disagreement_sellwatch_threshold": 0.18,
                "confidence": round(evidence, 4),
                "sample_size": int(n),
                "early_exit_warning": False,
                "missed_profit_pressure": 0.0,
                "hold_quality_estimate": round(hold_quality, 4),
                "reasons": ["insufficient_exit_evidence"],
            }

        risk_pressure = _clamp((early_fail * 0.55) + (deterioration * 0.45), 0.0, 1.0)
        profit_pressure = _clamp(missed_profit, 0.0, 1.0)
        hold_support = _clamp(hold_quality, 0.0, 1.0)

        stop_loss_pct = _clamp(0.025 - (risk_pressure * 0.006) + (hold_support * 0.0015), 0.020, 0.032)
        take_profit_pct = _clamp(0.050 - (risk_pressure * 0.010) + (profit_pressure * 0.012), 0.040, 0.080)
        probability_drop_sellwatch_threshold = _clamp(8.0 - (risk_pressure * 1.6) + (hold_support * 0.7), 6.0, 10.0)
        disagreement_sellwatch_threshold = _clamp(0.18 - (risk_pressure * 0.04) + (hold_support * 0.02), 0.12, 0.24)

        reasons: list[str] = []
        if risk_pressure >= 0.45:
            reasons.append("tighten_loss_protection_from_failure_pressure")
        if profit_pressure >= 0.35:
            reasons.append("increase_profit_capture_pressure")
        if hold_support >= 0.45:
            reasons.append("allow_measured_hold_extension_on_quality")
        if not reasons:
            reasons.append("balanced_exit_policy")

        return {
            "stop_loss_pct": round(stop_loss_pct, 4),
            "take_profit_pct": round(take_profit_pct, 4),
            "probability_drop_sellwatch_threshold": round(probability_drop_sellwatch_threshold, 2),
            "disagreement_sellwatch_threshold": round(disagreement_sellwatch_threshold, 4),
            "confidence": round(evidence, 4),
            "sample_size": int(n),
            "early_exit_warning": bool(risk_pressure >= 0.58),
            "missed_profit_pressure": round(profit_pressure, 4),
            "hold_quality_estimate": round(hold_support, 4),
            "learned_thresholds": {
                "risk_pressure": round(risk_pressure, 4),
                "profit_pressure": round(profit_pressure, 4),
                "hold_support": round(hold_support, 4),
            },
            "reasons": reasons,
        }

    def expected_risk_if_hold(self, *args, **kwargs) -> dict:
        summary = self._summarize()
        n = _to_int(summary.get("sample_size"), 0)
        evidence = _to_float(summary.get("evidence_strength"), 0.0)
        early_fail = _to_float(summary.get("early_failure_rate"), 0.0)
        deterioration = _to_float(summary.get("deterioration_rate"), 0.0)
        hold_quality = _to_float(summary.get("hold_quality_rate"), 0.0)
        missed_profit = _to_float(summary.get("missed_profit_rate"), 0.0)

        probability_drop_percent = _to_float(kwargs.get("probability_drop_percent"), 0.0)
        disagreement_increase = _to_float(kwargs.get("disagreement_increase"), 0.0)
        regime_shift = _as_bool(kwargs.get("regime_shift"))

        prob_component = _clamp(probability_drop_percent / 12.0, 0.0, 1.0)
        disagreement_component = _clamp(disagreement_increase / 0.25, 0.0, 1.0)
        regime_component = 1.0 if regime_shift else 0.0
        historical_component = _clamp((early_fail * 0.5) + (deterioration * 0.3) + ((1.0 - hold_quality) * 0.2), 0.0, 1.0)

        expected = _clamp(
            (historical_component * 0.5)
            + (prob_component * 0.35)
            + (disagreement_component * 0.1)
            + (regime_component * 0.05),
            0.0,
            1.0,
        )
        if n < self.min_samples:
            expected = _clamp((prob_component * 0.6) + (disagreement_component * 0.3) + (regime_component * 0.1), 0.0, 1.0)

        reasons: list[str] = []
        if prob_component >= 0.5:
            reasons.append("probability_drop_elevated")
        if disagreement_component >= 0.5:
            reasons.append("persona_disagreement_rising")
        if regime_component > 0:
            reasons.append("regime_shift_detected")
        if historical_component >= 0.45 and n >= self.min_samples:
            reasons.append("historical_deterioration_pressure")
        if missed_profit >= 0.35 and expected < 0.45:
            reasons.append("missed_profit_pressure_supports_selective_holds")
        if not reasons:
            reasons.append("no_material_exit_risk_signal")

        return {
            "expected_risk_if_hold": round(expected, 4),
            "risk_score": round(expected, 4),
            "confidence": round(evidence, 4),
            "sample_size": int(n),
            "early_exit_warning": bool(expected >= 0.62 and n >= self.min_samples),
            "missed_profit_pressure": round(_clamp(missed_profit, 0.0, 1.0), 4),
            "hold_quality_estimate": round(_clamp(hold_quality, 0.0, 1.0), 4),
            "loss_conditions": self.loss_conditions(),
            "reasons": reasons,
        }

    def loss_conditions(self) -> dict:
        summary = self._summarize()
        n = max(1, _to_int(summary.get("sample_size"), 0))
        counts = dict(summary.get("loss_condition_counts") or {})
        ordered = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
        top_conditions = [
            {
                "condition": str(name),
                "count": int(ct),
                "share_percent": round((int(ct) / float(n)) * 100.0, 2),
            }
            for name, ct in ordered[:8]
        ]
        return {
            "conditions": [str(x.get("condition")) for x in top_conditions],
            "top_conditions": top_conditions,
            "sample_size": int(summary.get("sample_size", 0)),
            "avg_drawdown_from_peak": round(_to_float(summary.get("avg_drawdown_from_peak"), 0.0), 4),
            "avg_missed_profit_gap": round(_to_float(summary.get("avg_missed_profit_gap"), 0.0), 4),
        }
