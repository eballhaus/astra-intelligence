from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1500


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


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


class OpportunityCostLearningV1:
    """Shadow-only selected-vs-rejected opportunity-cost learning."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.audit_path = os.path.join(self.state_dir, "execution_suppression_audit_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "opportunity_cost_learning_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _selected_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in _tail_jsonl(self.lifecycle_path):
            symbol = _text(row.get("symbol")).upper()
            if symbol:
                latest[symbol] = row
        return list(latest.values())

    def _rejected_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in _tail_jsonl(self.ledger_path, max_rows=900):
            symbol = _text(row.get("symbol")).upper()
            if not symbol:
                continue
            selected = bool(row.get("paper_trade_opened") or row.get("was_released"))
            paper_ready = bool(row.get("was_paper_ready") or _text(row.get("decision_status")) == "paper_ready")
            action = _text(row.get("final_action") or row.get("action")).lower()
            if not selected and (paper_ready or action == "buy"):
                rows.append(row)
        for row in _tail_jsonl(self.audit_path, max_rows=700):
            if not bool(row.get("order_submitted")) and _text(row.get("symbol")):
                rows.append(row)
        dedup: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = _text(row.get("symbol")).upper()
            ts = _text(row.get("timestamp") or row.get("timestamp_utc"))
            key = f"{symbol}:{ts[:16]}"
            dedup[key] = row
        return list(dedup.values())[-600:]

    @staticmethod
    def _selected_return(row: dict[str, Any]) -> float:
        return _to_float(row.get("current_or_exit_profit_pct") or row.get("current_return_pct") or row.get("continuation_after_entry_pct"))

    @staticmethod
    def _rejected_proxy_return(row: dict[str, Any]) -> float:
        if row.get("realized_return_pct") not in (None, ""):
            return _to_float(row.get("realized_return_pct"))
        quality = _to_float(row.get("grade_percent") or row.get("confidence") or row.get("expectancy") or row.get("context_adjusted_opportunity_score"))
        live_quality = _to_float(row.get("live_quality_score") or row.get("data_quality_score"))
        penalty = 0.0
        if _text(row.get("rejection_reason") or row.get("suppression_reason")):
            penalty += 0.35
        if _text(row.get("session_type")) in {"weekend_closed", "holiday_closed"}:
            penalty += 0.25
        return round(((quality - 70.0) / 18.0) + ((live_quality - 80.0) / 80.0) - penalty, 4)

    _REAL_LATER_RETURN_KEYS = (
        "subsequent_return", "subsequent_return_pct", "later_return_after_rejection",
        "rejected_later_return_pct", "hypothetical_return", "realized_return_pct",
    )

    @staticmethod
    def _real_rejection_outcome(row: dict[str, Any]) -> tuple[float | None, str]:
        for key in OpportunityCostLearningV1._REAL_LATER_RETURN_KEYS:
            value = row.get(key)
            if value not in (None, ""):
                try:
                    return float(value), key
                except Exception:
                    continue
        return None, ""

    @staticmethod
    def _rejected_return_and_tier(row: dict[str, Any]) -> tuple[float, str, str]:
        """Rejected-candidate return preferring real later-price evidence.

        Returns (return_pct, evidence_tier, evidence_key).  The quality-score
        proxy is used only as a fallback so classification can remain fail-closed.
        """
        real, key = OpportunityCostLearningV1._real_rejection_outcome(row)
        if real is not None:
            return round(real, 4), "REAL_LATER_PRICE", key
        return OpportunityCostLearningV1._rejected_proxy_return(row), "QUALITY_PROXY", ""

    @staticmethod
    def _safety_blocked(row: dict[str, Any]) -> bool:
        reasons = " ".join(
            str(row.get(_key) or "")
            for _key in ("blocked_reasons", "rejection_reason", "suppression_reason", "final_blocker_reason")
        ).lower()
        return bool(row.get("safety_blocker") or row.get("liquidity_blocker") or row.get("stale_evidence") or row.get("duplicate_exposure")
                    or any(token in reasons for token in ("safety", "liquidity", "stale", "duplicate")))

    @staticmethod
    def _classify_rejection(row: dict[str, Any], rejected_return: float, evidence_tier: str) -> str:
        if OpportunityCostLearningV1._safety_blocked(row):
            return "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED"
        if evidence_tier != "REAL_LATER_PRICE":
            return "INSUFFICIENT_EVIDENCE"
        if rejected_return > 0:
            return "MISSED_OPPORTUNITY"
        if rejected_return < 0:
            return "CORRECT_REJECTION"
        return "AMBIGUOUS"

    def _derive_rows(self) -> list[dict[str, Any]]:
        selected = self._selected_rows()
        rejected = self._rejected_rows()
        if not selected or not rejected:
            return []
        selected_by_symbol = { _text(row.get("symbol")).upper(): row for row in selected }
        avg_selected = mean([self._selected_return(row) for row in selected]) if selected else 0.0
        out: list[dict[str, Any]] = []
        for rej in rejected[-500:]:
            rejected_symbol = _text(rej.get("symbol")).upper()
            rejected_return, rejected_tier, rejected_key = self._rejected_return_and_tier(rej)
            best_selected = max(selected, key=lambda row: self._selected_return(row), default={})
            matched = selected_by_symbol.get(rejected_symbol) or best_selected
            selected_symbol = _text(matched.get("symbol"), "portfolio_selected").upper()
            selected_return = self._selected_return(matched) if matched else avg_selected
            opportunity_cost = rejected_return - selected_return
            rejection_classification = self._classify_rejection(rej, rejected_return, rejected_tier)
            # A quality proxy is useful for triage but cannot establish that
            # Astra missed a better candidate or made a correct rejection.
            missed = (
                rejection_classification == "MISSED_OPPORTUNITY"
                and opportunity_cost > 0.35
            )
            correct = (
                rejection_classification == "CORRECT_REJECTION"
                and opportunity_cost <= 0.0
            )
            ranking_quality = _clamp(70.0 - max(0.0, opportunity_cost) * 12.0 + (10.0 if correct else 0.0))
            promotion_quality = _clamp(_to_float(rej.get("grade_percent") or rej.get("confidence"), 60.0))
            selection_efficiency = _clamp(100.0 - max(0.0, opportunity_cost) * 15.0)
            out.append({
                "enabled": True,
                "version": VERSION,
                "timestamp": _text(rej.get("timestamp") or rej.get("timestamp_utc") or _now_iso()),
                "selected_symbol": selected_symbol,
                "rejected_symbol": rejected_symbol,
                "selected_return_pct": _round(selected_return),
                "rejected_return_pct": _round(rejected_return),
                "rejected_return_evidence_tier": rejected_tier,
                "rejected_return_evidence_key": rejected_key,
                "rejected_candidate_outcome_classification": rejection_classification,
                "comparison_evidence_status": (
                    "REAL_LATER_PRICE" if rejected_tier == "REAL_LATER_PRICE" else "INSUFFICIENT_LATER_OUTCOME"
                ),
                "opportunity_cost_pct": _round(opportunity_cost),
                "missed_better_candidate_flag": bool(missed),
                "correct_selection_flag": bool(correct),
                "ranking_quality_score": _round(ranking_quality, 2),
                "promotion_quality_score": _round(promotion_quality, 2),
                "selection_efficiency_score": _round(selection_efficiency, 2),
                "same_archetype": _text(rej.get("setup_type") or rej.get("trade_archetype"), "unknown"),
                "same_regime": _text(rej.get("regime") or rej.get("market_regime"), "unknown"),
                "same_sector": _text(rej.get("sector"), "unknown"),
                "same_cap_tier": _text(rej.get("cap_tier") or rej.get("cap_bucket"), "unknown"),
                "same_horizon_style": _text(rej.get("horizon_style") or rej.get("day_learning_session_bucket"), "unknown"),
                "generated_at": _now_iso(),
                "api_calls_used": 0,
                "live_trading_changed": False,
                "alpaca_paper_only_preserved": True,
                "forced_trades_enabled": False,
            })
        return out

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 45.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-120:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
        return round(mean(vals), 4) if vals else None

    @staticmethod
    def _median(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
        return round(median(vals), 4) if vals else None

    @staticmethod
    def _gap_row(rows: list[dict[str, Any]], *, positive: bool) -> dict[str, Any]:
        if not rows:
            return {}
        return max(rows, key=lambda row: _to_float(row.get("opportunity_cost_pct"))) if positive else min(rows, key=lambda row: _to_float(row.get("opportunity_cost_pct")))

    def _outlier_symbols(self, rows: list[dict[str, Any]]) -> list[str]:
        med = self._median(rows, "opportunity_cost_pct")
        if med is None:
            return []
        threshold = max(50.0, abs(med) * 2.0)
        ranked = sorted(rows, key=lambda row: abs(_to_float(row.get("opportunity_cost_pct")) - med), reverse=True)
        out: list[str] = []
        for row in ranked[:8]:
            gap = _to_float(row.get("opportunity_cost_pct"))
            if abs(gap - med) >= threshold or abs(gap) >= 100.0:
                symbol = _text(row.get("rejected_symbol") or row.get("selected_symbol"), "unknown").upper()
                if symbol not in out:
                    out.append(symbol)
        return out

    def status(self, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out
        selected = self._selected_rows()
        rejected = self._rejected_rows()
        rows = self._derive_rows()
        self._write_rows(rows)
        missed = [row for row in rows if row.get("missed_better_candidate_flag")]
        correct = [row for row in rows if row.get("correct_selection_flag")]
        classification_counts = {
            "MISSED_OPPORTUNITY": sum(1 for row in rows if row.get("rejected_candidate_outcome_classification") == "MISSED_OPPORTUNITY"),
            "CORRECT_REJECTION": sum(1 for row in rows if row.get("rejected_candidate_outcome_classification") == "CORRECT_REJECTION"),
            "AMBIGUOUS": sum(1 for row in rows if row.get("rejected_candidate_outcome_classification") == "AMBIGUOUS"),
            "INSUFFICIENT_EVIDENCE": sum(1 for row in rows if row.get("rejected_candidate_outcome_classification") == "INSUFFICIENT_EVIDENCE"),
            "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED": sum(1 for row in rows if row.get("rejected_candidate_outcome_classification") == "AMBIGUOUS_SAFETY_BLOCKER_PRESERVED"),
        }
        best_selected = max(selected, key=self._selected_return, default={})
        worst_selected = min(selected, key=self._selected_return, default={})
        best_rejected = max(rows, key=lambda row: _to_float(row.get("rejected_return_pct")), default={})
        missed_best = max(missed, key=lambda row: _to_float(row.get("opportunity_cost_pct")), default={})
        avg_cost = self._avg(rows, "opportunity_cost_pct")
        avg_selected_return = self._avg(rows, "selected_return_pct")
        avg_rejected_return = self._avg(rows, "rejected_return_pct")
        median_cost = self._median(rows, "opportunity_cost_pct")
        largest_positive = self._gap_row(rows, positive=True)
        largest_negative = self._gap_row(rows, positive=False)
        selection_quality = self._avg(rows, "selection_efficiency_score")
        ranking_quality = self._avg(rows, "ranking_quality_score")
        recommendation = "insufficient_data"
        if rows:
            recommendation = "review_candidate_suppression_vs_selected" if len(missed) > len(correct) else "preserve_current_selection_bias"
        calculation_method = (
            "opportunity_cost_pct = rejected_return_pct - selected_return_pct; rejected_return_pct uses real later-price "
            "evidence (subsequent_return, later_return_after_rejection, rejected_later_return_pct, hypothetical_return, "
            "realized_return_pct) when present, otherwise the proxy ((quality - 70)/18)+((live_quality - 80)/80)-penalty; "
            "selected_return_pct uses same-symbol selected lifecycle if available, otherwise best selected lifecycle return."
        )
        out = {
            "enabled": True,
            "version": VERSION,
            "selected_candidates_reviewed": len(selected),
            "rejected_candidates_reviewed": len(rejected),
            "average_opportunity_cost": avg_cost,
            "avg_selected_return": avg_selected_return,
            "avg_rejected_return": avg_rejected_return,
            "median_opportunity_cost": median_cost,
            "largest_positive_gap": _round(largest_positive.get("opportunity_cost_pct")) if largest_positive else None,
            "largest_negative_gap": _round(largest_negative.get("opportunity_cost_pct")) if largest_negative else None,
            "largest_positive_gap_symbol": _text(largest_positive.get("rejected_symbol"), "insufficient_data"),
            "largest_negative_gap_symbol": _text(largest_negative.get("rejected_symbol"), "insufficient_data"),
            "outlier_symbols": self._outlier_symbols(rows),
            "calculation_method": calculation_method,
            "missed_opportunity_count": len(missed),
            "correct_selection_count": len(correct),
            "rejected_candidate_outcome_classification_counts": classification_counts,
            "selection_quality_score": selection_quality,
            "ranking_quality_score": ranking_quality,
            "best_selected_symbol": _text(best_selected.get("symbol"), "insufficient_data"),
            "worst_selected_symbol": _text(worst_selected.get("symbol"), "insufficient_data"),
            "best_rejected_symbol": _text(best_rejected.get("rejected_symbol"), "insufficient_data"),
            "missed_best_symbol": _text(missed_best.get("rejected_symbol"), "insufficient_data"),
            "ranking_improvement_recommendation": recommendation,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
