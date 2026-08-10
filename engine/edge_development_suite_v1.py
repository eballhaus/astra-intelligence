from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900
MIN_EV_CALIBRATION_SAMPLES = 20
STRICT_TRUTH_REGISTRY = "broker_truth_records_v1.json"
EV_STANDARD_DEVIATIONS = 2.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score01(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _first_number(row: dict[str, Any], keys: tuple[str, ...], default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


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


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if not isinstance(pack, dict):
            continue
        for section in ("final", "qualified", "watchlist", "fill"):
            values = pack.get(section)
            if isinstance(values, list):
                rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


def _quality_label(score: float) -> str:
    if score >= 85.0:
        return "elite"
    if score >= 74.0:
        return "strong"
    if score >= 60.0:
        return "acceptable"
    if score >= 45.0:
        return "weak"
    return "poor"


def _edge_label(score: float) -> str:
    if score >= 85.0:
        return "elite_edge"
    if score >= 74.0:
        return "strong_edge"
    if score >= 58.0:
        return "moderate_edge"
    return "weak_edge"


def _regime_label(score: float) -> str:
    if score >= 78.0:
        return "highly_aligned"
    if score >= 62.0:
        return "aligned"
    if score >= 46.0:
        return "neutral"
    return "misaligned"


def _strict_broker_truth(row: dict[str, Any]) -> bool:
    """Exact strict-truth predicate reused from the official contract.

    Mirror of astra_multilane_activation_v2.strict_broker_truth to keep the
    join bounded and independent of runtime wiring.
    """
    evidence = _safe_text(row.get("evidence_class") or row.get("truth_quality"), "").upper()
    dust_safe = dict(row.get("canonical_dust_safe_closure") or {})
    closure_proven = bool(
        row.get("broker_residual_zero_confirmed")
        or row.get("broker_zero_confirmed")
        or (
            dust_safe.get("status") == "VERIFIED_CANONICAL_DUST_SAFE_CLOSURE"
            and dust_safe.get("identity_verified") is True
            and dust_safe.get("full_exit_fill_verified") is True
            and bool(dict(dust_safe.get("dust_classification") or {}).get("is_dust"))
        )
    )
    return bool(
        evidence == "BROKER_CONFIRMED_COMPLETE"
        and _safe_text(row.get("entry_fill_id") or row.get("entry_order_fill_id"))
        and _safe_text(row.get("exit_fill_id") or row.get("exit_order_fill_id"))
        and _safe_text(row.get("entry_order_id") or row.get("broker_order_id"))
        and _safe_text(row.get("exit_order_id"))
        and _safe_text(row.get("lifecycle_id"))
        and closure_proven
    )


def _read_strict_truth_registry(state_dir: str) -> list[dict[str, Any]]:
    path = os.path.join(state_dir, STRICT_TRUTH_REGISTRY)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            registry = json.load(handle)
        rows = list(registry.get("records") or []) if isinstance(registry, dict) else []
    except Exception:
        return []
    return [dict(row) for row in rows if isinstance(row, dict) and _strict_broker_truth(row)]


def _closed_outcome_attribution(strict: dict[str, Any]) -> dict[str, Any]:
    entry_price = _to_float(strict.get("entry_price"), 0.0)
    exit_price = _to_float(strict.get("exit_price"), 0.0)
    realized_return = _to_float(strict.get("realized_return"), _to_float(strict.get("realized_return_pct"), 0.0))
    dollar = strict.get("realized_pnl")
    if dollar is None and entry_price > 0.0 and exit_price > 0.0:
        quantity = _to_float(strict.get("filled_qty") or strict.get("exit_filled_quantity") or strict.get("quantity"), 0.0)
        if quantity > 0.0:
            dollar = round((exit_price - entry_price) * quantity, 4)
    return {
        "realized_return_pct": round(realized_return, 4),
        "realized_pnl": _to_float(dollar, 0.0) if dollar is not None else None,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": _to_float(strict.get("filled_qty") or strict.get("exit_filled_quantity") or strict.get("quantity"), 0.0),
        "symbol": _safe_text(strict.get("symbol")).upper(),
        "lane_id": _safe_text(strict.get("lane_id")).upper(),
        "entry_timestamp": _safe_text(strict.get("entry_time") or strict.get("entry_timestamp")),
        "exit_timestamp": _safe_text(strict.get("exit_time") or strict.get("exit_timestamp")),
        "outcome": "WIN" if realized_return > 1e-9 else "LOSS" if realized_return < -1e-9 else "BREAKEVEN",
    }


def _exact_identity_match(candidate: dict[str, Any], strict_index: dict[str, Any]) -> dict[str, Any] | None:
    """Match only on exact immutable identifiers, in fixed preference order."""
    for key, aliases in (
        ("candidate_id", ("candidate_id", "decision_id")),
        ("recommendation_id", ("recommendation_id",)),
        ("selection_id", ("selection_id",)),
        ("lifecycle_id", ("lifecycle_id",)),
    ):
        candidate_value = ""
        for alias in aliases:
            candidate_value = _safe_text(candidate.get(alias))
            if candidate_value:
                break
        if not candidate_value:
            continue
        for strict_key in (key, *aliases):
            hit = strict_index.get(f"{strict_key}:{candidate_value}")
            if hit is not None:
                return hit
    return None


class EdgeDevelopmentSuiteV1:
    """Paper-only shadow edge, expectancy, archetype, and regime diagnostics.

    The suite only decorates local/snapshot candidates and exposes status
    diagnostics. It never changes live trading, broker mode, provider routing,
    production weights, forced exits, or Alpaca paper safety gates.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._learning_cache: dict[str, Any] | None = None

    def _candidate_ledger_rows(self) -> list[dict[str, Any]]:
        return _tail_jsonl(self.ledger_path, max_rows=300)

    def _learning_hooks(self) -> dict[str, Any]:
        if self._learning_cache is not None:
            return self._learning_cache
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=300))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=300))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        archetype_returns: dict[str, list[float]] = defaultdict(list)
        regime_returns: dict[str, list[float]] = defaultdict(list)
        for row in rows[-MAX_ROWS:]:
            r = dict(row or {})
            archetype = _safe_text(
                r.get("trade_archetype")
                or r.get("entry_trade_archetype")
                or r.get("setup_type")
                or r.get("entry_setup_type"),
                "unknown",
            ).lower().replace(" ", "_")
            regime = _safe_text(
                r.get("market_regime")
                or r.get("entry_regime_context")
                or r.get("regime_context"),
                "unknown",
            ).lower().replace(" ", "_")
            ret = _first_number(r, ("realized_return_pct", "return_pct", "return_percent", "pnl_pct"), 0.0)
            if archetype:
                archetype_returns[archetype].append(ret)
            if regime:
                regime_returns[regime].append(ret)

        def _summary(values: list[float]) -> dict[str, Any]:
            sample = len(values)
            if sample <= 0:
                return {"sample_size": 0, "win_rate": None, "average_return_pct": None, "quality_score": 50.0}
            wins = sum(1 for v in values if v > 0.0)
            avg = mean(values)
            quality = _clamp(45.0 + (wins / max(1, sample)) * 35.0 + max(-12.0, min(18.0, avg * 4.0)))
            return {
                "sample_size": int(sample),
                "win_rate": round((wins / max(1, sample)) * 100.0, 2),
                "average_return_pct": round(avg, 4),
                "quality_score": round(quality, 2),
            }

        archetypes = {k: _summary(v) for k, v in archetype_returns.items()}
        regimes = {k: _summary(v) for k, v in regime_returns.items()}
        best_archetype = max(archetypes.items(), key=lambda kv: (_to_float(kv[1].get("quality_score"), 0.0), _to_float(kv[1].get("sample_size"), 0.0)), default=("insufficient_data", {}))[0]
        best_regime = max(regimes.items(), key=lambda kv: (_to_float(kv[1].get("quality_score"), 0.0), _to_float(kv[1].get("sample_size"), 0.0)), default=("insufficient_data", {}))[0]
        self._learning_cache = {
            "sample_size": int(len(rows)),
            "archetype_outcome_quality": archetypes,
            "regime_outcome_quality": regimes,
            "best_learned_archetype": best_archetype,
            "best_learned_regime": best_regime,
        }
        return self._learning_cache

    def _base_features(self, row: dict[str, Any]) -> dict[str, float | str]:
        r = dict(row or {})
        expected_return = _first_number(
            r,
            ("predicted_profit_percent", "expected_return_percent", "expected_return_pct", "expected_move_percent", "profit_prediction_pct"),
            0.0,
        )
        confidence = _score01(r.get("confidence"), _score01(r.get("predicted_win_probability"), 54.0))
        entry_quality = _score01(
            r.get("entry_quality_v3_score"),
            _score01(r.get("entry_quality_v2_score"), _score01(r.get("entry_filter_v2_score"), _score01(r.get("entry_quality_score"), 52.0))),
        )
        trend = _score01(r.get("trend_continuation_score"), _score01(r.get("trend_quality_score"), _score01(r.get("timeframe_alignment_score"), 52.0)))
        momentum = _score01(r.get("momentum_expansion_score"), _score01(r.get("momentum_score"), _score01(r.get("relative_strength_score"), 50.0)))
        breakout = _score01(r.get("breakout_probability_score"), _score01(r.get("breakout_cleanliness_score"), 50.0))
        volatility = _score01(r.get("volatility_expansion_score"), _score01(r.get("volatility_score"), 50.0))
        follow = _score01(r.get("expected_follow_through_score"), _score01(r.get("entry_followthrough_quality_score"), _score01(r.get("follow_through_probability"), 52.0)))
        relative_strength = _score01(r.get("relative_strength_score"), _score01(r.get("rank_persistence_score"), 50.0))
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("data_quality_score"), 58.0))
        execution = _score01(r.get("execution_readiness_score"), _score01(r.get("order_execution_score"), 56.0))
        portfolio_risk = _score01(r.get("portfolio_risk_score"), 58.0)
        drawdown_risk = _score01(r.get("drawdown_risk_score"), 35.0)
        asymmetry = _score01(
            r.get("asymmetric_reward_score"),
            _clamp(48.0 + max(0.0, expected_return) * 5.0 + max(0.0, _to_float(r.get("estimated_reward_to_risk"), 0.0) - 1.0) * 11.0),
        )
        downside = _clamp((portfolio_risk * 0.45) + ((100.0 - drawdown_risk) * 0.32) + (liquidity * 0.13) + (execution * 0.10))
        horizon = _safe_text(r.get("best_horizon_style") or r.get("trade_horizon_style") or r.get("best_discovery_horizon"), "day_trade").lower().replace(" ", "_")
        regime = _safe_text(r.get("market_regime") or r.get("regime_context") or r.get("current_regime"), "unknown").lower().replace(" ", "_")
        return {
            "expected_return": expected_return,
            "confidence": confidence,
            "entry_quality": entry_quality,
            "trend": trend,
            "momentum": momentum,
            "breakout": breakout,
            "volatility": volatility,
            "follow": follow,
            "relative_strength": relative_strength,
            "liquidity": liquidity,
            "execution": execution,
            "portfolio_risk": portfolio_risk,
            "drawdown_risk": drawdown_risk,
            "asymmetry": asymmetry,
            "downside": downside,
            "horizon": horizon,
            "regime": regime,
        }

    def _classify_archetype(self, row: dict[str, Any], f: dict[str, float | str]) -> tuple[str, float, float]:
        text = " ".join(
            _safe_text(row.get(k)).lower()
            for k in ("candidate_opportunity_type", "candidate_discovery_reason", "setup_type", "why_this_is_a_buy", "plain_decision_summary")
        )
        momentum = _to_float(f.get("momentum"), 50.0)
        breakout = _to_float(f.get("breakout"), 50.0)
        volatility = _to_float(f.get("volatility"), 50.0)
        trend = _to_float(f.get("trend"), 50.0)
        follow = _to_float(f.get("follow"), 50.0)
        if "gap" in text and ("go" in text or momentum >= 68.0):
            archetype = "gap_and_go"
            confidence = _clamp((momentum * 0.42) + (breakout * 0.22) + (follow * 0.20) + (volatility * 0.16))
        elif breakout >= 66.0 or "breakout" in text:
            archetype = "breakout_continuation"
            confidence = _clamp((breakout * 0.42) + (momentum * 0.24) + (trend * 0.18) + (follow * 0.16))
        elif volatility >= 68.0 and breakout >= 58.0:
            archetype = "volatility_squeeze_breakout"
            confidence = _clamp((volatility * 0.40) + (breakout * 0.30) + (momentum * 0.18) + (follow * 0.12))
        elif momentum >= 66.0 or "momentum" in text:
            archetype = "momentum_expansion"
            confidence = _clamp((momentum * 0.45) + (follow * 0.22) + (trend * 0.18) + (volatility * 0.15))
        elif "pullback" in text and trend >= 55.0:
            archetype = "pullback_continuation"
            confidence = _clamp((trend * 0.36) + (follow * 0.26) + (_to_float(f.get("entry_quality"), 52.0) * 0.22) + (_to_float(f.get("downside"), 55.0) * 0.16))
        elif "reclaim" in text or (trend >= 58.0 and follow >= 58.0 and breakout < 58.0):
            archetype = "trend_reclaim"
            confidence = _clamp((trend * 0.38) + (follow * 0.28) + (_to_float(f.get("relative_strength"), 50.0) * 0.18) + (_to_float(f.get("downside"), 55.0) * 0.16))
        elif "reversal" in text or "failed breakdown" in text:
            archetype = "failed_breakdown_reversal"
            confidence = _clamp((follow * 0.34) + (_to_float(f.get("downside"), 55.0) * 0.28) + (momentum * 0.20) + (trend * 0.18))
        elif trend < 42.0 and momentum < 45.0 and breakout < 45.0:
            archetype = "weak_structure"
            confidence = _clamp(100.0 - ((trend + momentum + breakout) / 3.0))
        elif abs(momentum - 50.0) < 8.0 and abs(trend - 50.0) < 10.0:
            archetype = "range_chop"
            confidence = 55.0
        else:
            archetype = "unknown"
            confidence = 45.0
        quality = _clamp((_to_float(f.get("follow"), 50.0) * 0.32) + (_to_float(f.get("momentum"), 50.0) * 0.22) + (_to_float(f.get("trend"), 50.0) * 0.20) + (_to_float(f.get("entry_quality"), 52.0) * 0.16) + (_to_float(f.get("downside"), 55.0) * 0.10))
        if archetype in {"weak_structure", "range_chop"}:
            quality = _clamp(quality - 16.0)
        elif archetype == "unknown":
            quality = _clamp(quality - 6.0)
        return archetype, round(confidence, 2), round(quality, 2)

    def _regime_alignment(self, archetype: str, f: dict[str, float | str]) -> tuple[float, str, float]:
        regime = str(f.get("regime") or "unknown")
        momentum_setup = archetype in {"breakout_continuation", "momentum_expansion", "gap_and_go", "volatility_squeeze_breakout"}
        swing_setup = str(f.get("horizon") or "") == "swing_trade"
        base = 58.0
        if any(token in regime for token in ("bull", "risk_on", "momentum", "uptrend")):
            base += 12.0 if momentum_setup else 6.0
        elif any(token in regime for token in ("bear", "risk_off", "defensive")):
            base -= 10.0 if momentum_setup else 2.0
            if archetype in {"pullback_continuation", "trend_reclaim"}:
                base += 4.0
        elif any(token in regime for token in ("high_vol", "volatile", "volatility")):
            base += 7.0 if archetype in {"volatility_squeeze_breakout", "momentum_expansion"} else -4.0
        elif any(token in regime for token in ("chop", "range", "sideways")):
            base -= 9.0 if momentum_setup else 2.0
        if swing_setup and any(token in regime for token in ("bull", "uptrend", "sector_strength")):
            base += 4.0
        score = _clamp(base + (_to_float(f.get("trend"), 50.0) - 50.0) * 0.10 + (_to_float(f.get("follow"), 50.0) - 50.0) * 0.08)
        multiplier = round(max(0.94, min(1.06, 0.94 + (score / 100.0) * 0.12)), 4)
        return round(score, 2), _regime_label(score), multiplier

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        f = self._base_features(r)
        opportunity_quality = _clamp(
            (_to_float(f.get("trend"), 50.0) * 0.13)
            + (_to_float(f.get("momentum"), 50.0) * 0.14)
            + (_to_float(f.get("breakout"), 50.0) * 0.12)
            + (_to_float(f.get("volatility"), 50.0) * 0.08)
            + (_to_float(f.get("follow"), 50.0) * 0.16)
            + (_to_float(f.get("relative_strength"), 50.0) * 0.10)
            + (_to_float(f.get("downside"), 55.0) * 0.13)
            + (_to_float(f.get("liquidity"), 58.0) * 0.07)
            + (_to_float(f.get("asymmetry"), 50.0) * 0.07)
        )
        archetype, archetype_confidence, archetype_quality = self._classify_archetype(r, f)
        regime_score, regime_label, regime_multiplier = self._regime_alignment(archetype, f)
        reward_risk = _to_float(r.get("estimated_reward_to_risk"), 0.0)
        if reward_risk <= 0.0:
            reward_risk = 0.75 + (_to_float(f.get("asymmetry"), 50.0) / 100.0) * 2.75
        reward_risk = max(0.35, min(5.0, reward_risk))
        win_prob = _clamp(
            30.0
            + (_to_float(f.get("confidence"), 54.0) * 0.22)
            + (_to_float(f.get("entry_quality"), 52.0) * 0.16)
            + (opportunity_quality * 0.14)
            + (_to_float(f.get("follow"), 52.0) * 0.13)
            + (archetype_quality * 0.11)
            + (regime_score * 0.08)
            + (_to_float(f.get("downside"), 55.0) * 0.06)
            - 35.0,
            25.0,
            82.0,
        )
        avg_reward = max(0.4, min(6.0, reward_risk))
        avg_loss = max(0.5, min(2.2, 1.05 + max(0.0, 55.0 - _to_float(f.get("downside"), 55.0)) / 100.0))
        expected_value_ratio = (win_prob / 100.0 * avg_reward) - ((1.0 - (win_prob / 100.0)) * avg_loss)
        expected_value_score = _clamp(50.0 + expected_value_ratio * 18.0)
        loss_containment = _clamp((_to_float(f.get("downside"), 55.0) * 0.58) + (_to_float(f.get("portfolio_risk"), 58.0) * 0.22) + (_to_float(f.get("liquidity"), 58.0) * 0.20))
        edge_composite = _clamp(
            (
                (opportunity_quality * 0.26)
                + (expected_value_score * 0.22)
                + (archetype_quality * 0.16)
                + (regime_score * 0.12)
                + (_to_float(f.get("entry_quality"), 52.0) * 0.10)
                + (_to_float(f.get("confidence"), 54.0) * 0.08)
                + (_to_float(f.get("follow"), 52.0) * 0.06)
            )
            * regime_multiplier
        )
        summary = (
            f"{_edge_label(edge_composite).replace('_', ' ')} from {archetype.replace('_', ' ')}; "
            f"quality {opportunity_quality:.1f}, EV {expected_value_score:.1f}, regime {regime_label.replace('_', ' ')}."
        )
        return {
            "opportunity_quality_score": round(opportunity_quality, 2),
            "opportunity_quality_label": _quality_label(opportunity_quality),
            "expected_value_score": round(expected_value_score, 2),
            "expected_value_ratio": round(expected_value_ratio, 4),
            "expected_win_probability": round(win_prob, 2),
            "expected_reward_risk_ratio": round(reward_risk, 3),
            "expected_follow_through_score": round(_to_float(f.get("follow"), 52.0), 2),
            "expected_loss_containment_score": round(loss_containment, 2),
            "trade_archetype": archetype,
            "archetype_confidence": archetype_confidence,
            "archetype_quality_score": archetype_quality,
            "regime_alignment_score": regime_score,
            "regime_alignment_label": regime_label,
            "regime_edge_multiplier": regime_multiplier,
            "edge_composite_score": round(edge_composite, 2),
            "edge_composite_label": _edge_label(edge_composite),
            "edge_development_shadow_only": True,
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "edge_learning_hooks": {
                "tracks_archetype_outcome_quality": True,
                "tracks_expectancy_accuracy": True,
                "tracks_follow_through_success": True,
                "tracks_regime_archetype_pairing": True,
                "tracks_edge_score_vs_realized_outcome": True,
            },
            "edge_summary": summary,
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in list(rows or [])[:120]:
            if not isinstance(row, dict):
                continue
            r = dict(row)
            try:
                r.update(self.score_row(r))
            except Exception:
                r.update(
                    {
                        "opportunity_quality_score": 50.0,
                        "opportunity_quality_label": "acceptable",
                        "expected_value_score": 50.0,
                        "trade_archetype": "unknown",
                        "archetype_confidence": 0.0,
                        "archetype_quality_score": 50.0,
                        "regime_alignment_score": 50.0,
                        "regime_alignment_label": "neutral",
                        "regime_edge_multiplier": 1.0,
                        "edge_composite_score": 50.0,
                        "edge_composite_label": "moderate_edge",
                        "edge_development_shadow_only": True,
                        "auto_promotion_allowed": False,
                        "human_review_required": True,
                        "edge_summary": "Edge scoring used neutral fallback because candidate fields were incomplete.",
                    }
                )
            out.append(r)
        return out

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            new_pack = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = new_pack.get(section)
                if isinstance(values, list):
                    new_pack[section] = self.decorate_candidates([dict(v) for v in values if isinstance(v, dict)])
            out[pack_key] = new_pack
        rows = _candidate_rows(out)
        out["edge_development_suite_v1"] = True
        out["edge_development_summary"] = self.status(rows=rows)
        return out

    def strict_outcome_join_v1(self, candidate_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Exact-identity join of candidate decisions to strict closed outcomes.

        Only exact immutable identifiers (candidate_id, recommendation_id,
        selection_id, lifecycle_id) are matched, in fixed preference order.
        No timestamp or price proximity is ever used. A candidate with no
        exact match is reported as UNLINKED, never approximated.
        """
        strict_rows = _read_strict_truth_registry(self.state_dir)
        index: dict[str, dict[str, Any]] = {}
        for strict in strict_rows:
            for key in ("candidate_id", "recommendation_id", "selection_id", "lifecycle_id"):
                value = _safe_text(strict.get(key))
                if value:
                    index[f"{key}:{value}"] = strict
        candidates = [dict(row) for row in (candidate_rows or self._candidate_ledger_rows())]
        linked: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []
        for candidate in candidates[:MAX_ROWS]:
            match = _exact_identity_match(candidate, index)
            if match is None:
                unlinked.append({"candidate_id": candidate.get("candidate_id") or "", "symbol": _safe_text(candidate.get("symbol")), "linkage_status": "UNLINKED", "linkage_method": "EXACT_IDENTITY_NO_MATCH"})
                continue
            linked.append({
                "candidate_id": _safe_text(candidate.get("candidate_id") or candidate.get("decision_id")),
                "recommendation_id": _safe_text(candidate.get("recommendation_id")),
                "selection_id": _safe_text(candidate.get("selection_id")),
                "lifecycle_id": _safe_text(match.get("lifecycle_id")),
                "linkage_status": "LINKED",
                "linkage_method": "EXACT_IDENTITY",
                "decision_action": _safe_text(candidate.get("action") or candidate.get("final_action")),
                "decision_grade": _safe_text(candidate.get("grade")),
                "decision_confidence": _to_float(candidate.get("grade_percent") or candidate.get("confidence"), 0.0),
                "expected_value_score": _to_float(candidate.get("expected_value_score") or candidate.get("average_expectancy"), _to_float(candidate.get("average_expected_value_score"), 0.0)),
                "expected_value_ratio": _to_float(candidate.get("expected_value_ratio"), 0.0),
                "expected_win_probability": _to_float(candidate.get("expected_win_probability"), 0.0),
                "expected_reward_risk_ratio": _to_float(candidate.get("expected_reward_risk_ratio"), 0.0),
                "symbol": _safe_text(match.get("symbol")).upper(),
                **_closed_outcome_attribution(match),
            })
        return {
            "strict_outcome_join_v1": True,
            "candidates_reviewed": len(candidates),
            "linked_candidate_count": len(linked),
            "unlinked_candidate_count": len(unlinked),
            "strict_outcome_pool_size": len(strict_rows),
            "bounded_sample_only": True,
            "exact_identity_only": True,
            "fuzzy_matching_used": False,
            "linked_candidates": linked,
            "unlinked_candidates": unlinked,
            "behavior_safe_to_apply": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "api_calls_used": 0,
        }

    def calibrate_expected_value_vs_outcomes(self, joined_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Observational calibration of EV predictions against strict outcomes.

        Consumes only exact-linked candidate rows that carry both a predicted
        expected value (expected_value_score / expected_value_ratio /
        expected_win_probability) and a strict realized outcome. Fails closed
        when the linked sample is below MIN_EV_CALIBRATION_SAMPLES and never
        changes ranking, EV formulas, entries, or broker behavior.
        """
        joined = joined_rows if isinstance(joined_rows, list) else []
        sample: list[dict[str, Any]] = []
        for row in joined:
            expected = _to_float(row.get("expected_value_score") or row.get("expected_expectancy") or row.get("average_expectancy"), 0.0)
            if expected <= 0.0:
                continue
            realized = _to_float(row.get("realized_return_pct"), 0.0)
            realized_pnl = row.get("realized_pnl")
            if realized_pnl is None and "realized_return" in row:
                realized_pnl = _to_float(row.get("realized_return"), 0.0)
            if realized_pnl is None:
                continue
            sample.append({"expected_value_score": round(expected, 4), "expected_value_ratio": round(_to_float(row.get("expected_value_ratio"), 0.0), 4), "expected_win_probability": round(_to_float(row.get("expected_win_probability"), 0.0), 2), "realized_return_pct": round(realized, 6), "realized_pnl": _to_float(realized_pnl, 0.0)})
        sample_count = len(sample)
        insufficient = sample_count < MIN_EV_CALIBRATION_SAMPLES
        if insufficient or not sample:
            return {
                "ev_calibration_v1": True,
                "calibration_status": "INSUFFICIENT_STRICT_OUTCOME_SAMPLE",
                "ev_calibration_observational_only": True,
                "sample_count": sample_count,
                "minimum_sample_required": MIN_EV_CALIBRATION_SAMPLES,
                "rankings_changed": False,
                "ev_formula_changed": False,
                "behavior_safe_to_apply": False,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "api_calls_used": 0,
            }
        wins = [row for row in sample if row["realized_return_pct"] > 0.0]
        losses = [row for row in sample if row["realized_return_pct"] < 0.0]
        avg_predicted_ev = mean(row["expected_value_score"] for row in sample)
        avg_realized = mean(row["realized_return_pct"] for row in sample)
        win_rate = (len(wins) / sample_count) * 100.0
        gross_profit = sum(row["realized_return_pct"] for row in wins)
        gross_loss = abs(sum(row["realized_return_pct"] for row in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (gross_profit if gross_profit > 0 else None)
        predicted = [row["expected_win_probability"] for row in sample]
        actual_binary = [1 if row["realized_return_pct"] > 0.0 else 0 for row in sample]
        brier = mean((p - a) ** 2 for p, a in zip(predicted, actual_binary))
        calibration_error = round(brier ** 0.5 * 100.0, 4)
        sorted_sample = sorted(sample, key=lambda row: row["expected_value_score"])
        monotonic = True
        for index in range(1, len(sorted_sample)):
            if sorted_sample[index]["realized_return_pct"] + 0.5 < sorted_sample[index - 1]["realized_return_pct"]:
                monotonic = False
                break
        event_pct = sum(1 for row in sample if row["expected_value_score"] >= 70.0) / sample_count * 100.0
        return {
            "ev_calibration_v1": True,
            "calibration_status": "OBSERVATIONAL_PASS",
            "ev_calibration_observational_only": True,
            "sample_count": sample_count,
            "minimum_sample_required": MIN_EV_CALIBRATION_SAMPLES,
            "average_predicted_expected_value_score": round(avg_predicted_ev, 4),
            "average_realized_return_pct": round(avg_realized, 6),
            "realized_win_rate_pct": round(win_rate, 4),
            "realized_profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
            "mean_brier_score": round(brier, 6),
            "ev_calibration_error_pct": calibration_error,
            "monotonic_ev_to_outcome": monotonic,
            "high_confidence_event_pct": round(event_pct, 4),
            "sample": sample,
            "rankings_changed": False,
            "ev_formula_changed": False,
            "behavior_safe_to_apply": False,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "api_calls_used": 0,
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        decorated = self.decorate_candidates(rows or [])
        count = len(decorated)
        archetypes = Counter(_safe_text(r.get("trade_archetype"), "unknown") for r in decorated)
        opp_labels = Counter(_safe_text(r.get("opportunity_quality_label"), "unknown") for r in decorated)
        edge_labels = Counter(_safe_text(r.get("edge_composite_label"), "unknown") for r in decorated)
        regime_labels = Counter(_safe_text(r.get("regime_alignment_label"), "unknown") for r in decorated)
        avg_opp = mean([_to_float(r.get("opportunity_quality_score"), 0.0) for r in decorated]) if decorated else 0.0
        avg_ev = mean([_to_float(r.get("expected_value_score"), 0.0) for r in decorated]) if decorated else 0.0
        avg_win = mean([_to_float(r.get("expected_win_probability"), 0.0) for r in decorated]) if decorated else 0.0
        avg_rr = mean([_to_float(r.get("expected_reward_risk_ratio"), 0.0) for r in decorated]) if decorated else 0.0
        regime_top = max(
            decorated,
            key=lambda r: _to_float(r.get("regime_alignment_score"), 0.0),
            default={},
        )
        best_current = max(
            decorated,
            key=lambda r: (_to_float(r.get("edge_composite_score"), 0.0), _to_float(r.get("archetype_quality_score"), 0.0)),
            default={},
        )
        learning = self._learning_hooks()
        try:
            strict_join = self.strict_outcome_join_v1(candidate_rows=list(rows or []))
        except Exception:
            strict_join = {"strict_outcome_join_v1": True, "candidates_reviewed": 0, "linked_candidate_count": 0, "unlinked_candidate_count": 0, "linkage_status": "UNAVAILABLE"}
        try:
            calibration = self.calibrate_expected_value_vs_outcomes(strict_join.get("linked_candidates") or [])
        except Exception:
            calibration = {"ev_calibration_v1": True, "calibration_status": "UNAVAILABLE"}
        summary = (
            f"Evaluated {count} candidates; best current archetype "
            f"{_safe_text(best_current.get('trade_archetype'), 'insufficient_data').replace('_', ' ')}; "
            f"average opportunity quality {avg_opp:.1f}."
            if count
            else "Waiting for top-buy candidates to evaluate edge and archetype quality."
        )
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning",
            "edge_development_status_v1": True,
            "edge_development_shadow_only": True,
            "candidates_evaluated": int(count),
            "archetype_distribution": dict(archetypes),
            "opportunity_quality_distribution": dict(opp_labels),
            "average_opportunity_quality": round(avg_opp, 2),
            "average_expectancy": round(avg_ev, 2),
            "average_expected_value_score": round(avg_ev, 2),
            "average_expected_win_probability": round(avg_win, 2),
            "average_expected_reward_risk_ratio": round(avg_rr, 3),
            "best_current_archetype": _safe_text(best_current.get("trade_archetype"), "insufficient_data"),
            "best_learned_archetype": _safe_text(learning.get("best_learned_archetype"), "insufficient_data"),
            "strongest_regime_alignment": _safe_text(regime_top.get("regime_alignment_label"), "insufficient_data"),
            "strongest_regime_symbol": _safe_text(regime_top.get("symbol"), ""),
            "regime_alignment_distribution": dict(regime_labels),
            "regime_alignment_summary": "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in regime_labels.most_common()) or "waiting for regime candidates",
            "edge_distribution": dict(edge_labels),
            "edge_summary": summary,
            "archetype_outcome_quality": learning.get("archetype_outcome_quality", {}),
            "regime_outcome_quality": learning.get("regime_outcome_quality", {}),
            "learning_hook_sample_size": int(_to_float(learning.get("sample_size"), 0.0)),
            "candidate_to_strict_outcome_join_v1": strict_join,
            "ev_calibration_vs_outcomes_v1": calibration,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "updated_at": _now_iso(),
        }
