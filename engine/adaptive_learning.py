from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _norm_key(value: Any, default: str = "unknown") -> str:
    txt = str(value or "").strip().lower()
    if txt in {"", "none", "null"}:
        return default
    return txt


class AdaptiveLearningEngine:
    """
    Adaptive Learning V2 (conservative, evidence-gated).

    Purpose:
    - Provide bounded adaptive adjustments for ranking confidence and score realism.
    - Use closed trade outcomes from trade_journal when available.
    - Stay near-neutral with sparse evidence to avoid overfit/instability.
    """

    def __init__(self, *args, **kwargs):
        state_dir = os.path.join(os.getcwd(), "state")
        os.makedirs(state_dir, exist_ok=True)
        self.db_path = str(kwargs.get("db_path") or os.path.join(state_dir, "ai_trading_memory.db"))
        self.ttl_seconds = max(8, int(kwargs.get("ttl_seconds") or 25))
        self.max_confidence_adjustment = _clip(
            _to_float(kwargs.get("max_confidence_adjustment"), 4.0),
            1.5,
            6.0,
        )
        self.max_weight_delta = _clip(
            _to_float(kwargs.get("max_weight_delta"), 0.08),
            0.03,
            0.12,
        )
        self._created_utc = _utc_now_iso()
        self._cache: dict[str, Any] = {"ts": 0.0, "summary": {}}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _fetch_closed_rows(self, limit: int = 1600) -> list[dict[str, Any]]:
        n = max(100, min(5000, int(limit or 1600)))
        query = """
            SELECT
                return_percent,
                friction_adjusted_return,
                market_regime,
                setup_type,
                entry_persona_fit_summary,
                exit_timestamp
            FROM trade_journal
            WHERE exit_timestamp IS NOT NULL
              AND return_percent IS NOT NULL
            ORDER BY exit_timestamp DESC
            LIMIT ?
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(query, (n,)).fetchall()
            return [dict(r or {}) for r in rows]
        except Exception:
            return []

    def _stats_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "sample_size": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "avg_friction_return": 0.0,
            }
        returns = [_to_float(r.get("return_percent"), 0.0) for r in rows]
        friction = [
            _to_float(r.get("friction_adjusted_return"), _to_float(r.get("return_percent"), 0.0))
            for r in rows
        ]
        wins = len([x for x in returns if x > 0.0])
        n = len(rows)
        return {
            "sample_size": int(n),
            "win_rate": round((wins / float(max(1, n))) * 100.0, 2),
            "avg_return": round(sum(returns) / float(max(1, n)), 4),
            "avg_friction_return": round(sum(friction) / float(max(1, n)), 4),
        }

    def _segment_stats(self, rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = _norm_key(row.get(field))
            buckets.setdefault(key, []).append(row)
        out: dict[str, dict[str, Any]] = {}
        for key, group in buckets.items():
            out[key] = self._stats_from_rows(group)
        return out

    def _build_summary(self) -> dict[str, Any]:
        rows = self._fetch_closed_rows(limit=1600)
        global_stats = self._stats_from_rows(rows)
        if global_stats.get("sample_size", 0) <= 0:
            return {
                "ok": True,
                "mode": "insufficient_data",
                "global": global_stats,
                "by_regime": {},
                "by_setup_type": {},
                "by_persona": {},
                "last_updated_utc": _utc_now_iso(),
            }
        return {
            "ok": True,
            "mode": "active",
            "global": global_stats,
            "by_regime": self._segment_stats(rows, "market_regime"),
            "by_setup_type": self._segment_stats(rows, "setup_type"),
            "by_persona": self._segment_stats(rows, "entry_persona_fit_summary"),
            "last_updated_utc": _utc_now_iso(),
        }

    def _summary(self) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get("summary")
        ts = _to_float(self._cache.get("ts"), 0.0)
        if isinstance(cached, dict) and cached and (now - ts) <= float(self.ttl_seconds):
            return dict(cached)
        summary = self._build_summary()
        self._cache["summary"] = dict(summary)
        self._cache["ts"] = now
        return summary

    def learning_status(self) -> dict:
        summary = self._summary()
        global_stats = dict(summary.get("global") or {})
        return {
            "ok": True,
            "engine": "adaptive_learning",
            "mode": str(summary.get("mode") or "insufficient_data"),
            "created_utc": self._created_utc,
            "last_updated_utc": str(summary.get("last_updated_utc") or _utc_now_iso()),
            "db_path": self.db_path,
            "sample_size": int(global_stats.get("sample_size", 0) or 0),
            "win_rate": _to_float(global_stats.get("win_rate"), 0.0),
            "avg_return": _to_float(global_stats.get("avg_return"), 0.0),
            "avg_friction_return": _to_float(global_stats.get("avg_friction_return"), 0.0),
            "adaptive_weights": {
                "max_confidence_adjustment": float(self.max_confidence_adjustment),
                "max_weight_delta": float(self.max_weight_delta),
            },
        }

    def _edge_signal(self, stats: dict[str, Any], baseline: dict[str, Any]) -> float:
        """
        Returns bounded edge signal in [-1, 1]:
        >0 means stronger-than-baseline cohort,
        <0 means weaker-than-baseline cohort.
        """
        wr = _to_float(stats.get("win_rate"), 0.0)
        avg_ret = _to_float(stats.get("avg_return"), 0.0)
        base_wr = _to_float(baseline.get("win_rate"), 0.0)
        base_ret = _to_float(baseline.get("avg_return"), 0.0)
        wr_delta = (wr - base_wr) / 18.0
        ret_delta = (avg_ret - base_ret) / 1.5
        edge = (wr_delta * 0.58) + (ret_delta * 0.42)
        return _clip(edge, -1.0, 1.0)

    def get_adaptive_adjustments(
        self,
        base_confidence: float = 0.0,
        timeframe_alignment_score: float = 50.0,
        volatility_factor: float = 0.0,
        walkforward_stability_score: float = 50.0,
        regime_context: str | None = None,
        setup_type: str | None = None,
        persona_best_fit: str | None = None,
        **kwargs,
    ) -> dict[str, Any]:
        summary = self._summary()
        global_stats = dict(summary.get("global") or {})
        by_regime = dict(summary.get("by_regime") or {})
        by_setup = dict(summary.get("by_setup_type") or {})
        by_persona = dict(summary.get("by_persona") or {})

        regime_key = _norm_key(regime_context)
        setup_key = _norm_key(setup_type)
        persona_key = _norm_key(persona_best_fit)
        regime_stats = dict(by_regime.get(regime_key) or {})
        setup_stats = dict(by_setup.get(setup_key) or {})
        persona_stats = dict(by_persona.get(persona_key) or {})

        global_n = int(global_stats.get("sample_size", 0) or 0)
        regime_n = int(regime_stats.get("sample_size", 0) or 0)
        setup_n = int(setup_stats.get("sample_size", 0) or 0)
        persona_n = int(persona_stats.get("sample_size", 0) or 0)

        regime_edge = self._edge_signal(regime_stats, global_stats) if regime_n > 0 else 0.0
        setup_edge = self._edge_signal(setup_stats, global_stats) if setup_n > 0 else 0.0
        persona_edge = self._edge_signal(persona_stats, global_stats) if persona_n > 0 else 0.0

        regime_ev = _clip(regime_n / 140.0, 0.0, 1.0)
        setup_ev = _clip(setup_n / 120.0, 0.0, 1.0)
        persona_ev = _clip(persona_n / 120.0, 0.0, 1.0)
        global_ev = _clip(global_n / 180.0, 0.0, 1.0)

        # Weighted by both segment relevance and evidence depth.
        edge_composite = (
            (regime_edge * regime_ev * 0.48)
            + (setup_edge * setup_ev * 0.28)
            + (persona_edge * persona_ev * 0.24)
        )
        evidence_confidence = _clip(
            (global_ev * 0.45) + (regime_ev * 0.30) + (setup_ev * 0.15) + (persona_ev * 0.10),
            0.0,
            1.0,
        )

        # Safety dampers: high volatility / weak walkforward reduce adaptive influence.
        vol = _clip(_to_float(volatility_factor, 0.0), 0.0, 100.0)
        tf = _clip(_to_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        wf = _clip(_to_float(walkforward_stability_score, 50.0), 0.0, 100.0)
        risk_damper = _clip(
            1.0
            - (max(0.0, vol - 70.0) / 220.0)
            - (max(0.0, 45.0 - wf) / 180.0),
            0.72,
            1.0,
        )
        adaptive_strength = evidence_confidence * risk_damper

        bounded_edge = _clip(edge_composite, -1.0, 1.0) * adaptive_strength

        confidence_delta = _clip(
            bounded_edge * float(self.max_confidence_adjustment),
            -float(self.max_confidence_adjustment),
            float(self.max_confidence_adjustment),
        )

        # Conservative factor weights around neutral.
        confidence_w = _clip(1.0 + (bounded_edge * self.max_weight_delta * 0.95), 0.92, 1.08)
        tf_w = _clip(1.0 + (bounded_edge * self.max_weight_delta * 0.80), 0.93, 1.07)
        vol_w = _clip(1.0 + (bounded_edge * self.max_weight_delta * 0.65), 0.94, 1.06)
        wf_w = _clip(1.0 + (bounded_edge * self.max_weight_delta * 0.75), 0.93, 1.07)

        adaptive_weight_score = _clip(
            100.0 + (bounded_edge * 10.0),
            92.0,
            108.0,
        )

        weak_pattern_suppression = _clip(max(0.0, -bounded_edge) * 100.0, 0.0, 100.0)
        strong_pattern_reinforcement = _clip(max(0.0, bounded_edge) * 100.0, 0.0, 100.0)

        reasons: list[str] = []
        if global_n < 40:
            reasons.append("insufficient_global_evidence_near_neutral")
        if regime_n < 25:
            reasons.append("regime_evidence_thin")
        if setup_n < 20:
            reasons.append("setup_evidence_thin")
        if persona_n < 20:
            reasons.append("persona_evidence_thin")
        if weak_pattern_suppression >= 25.0:
            reasons.append("weak_pattern_suppression_active")
        if strong_pattern_reinforcement >= 25.0:
            reasons.append("strong_pattern_reinforcement_active")
        if vol >= 72.0:
            reasons.append("high_volatility_damper_applied")
        if wf <= 45.0:
            reasons.append("walkforward_stability_damper_applied")
        if not reasons:
            reasons.append("adaptive_learning_neutral")

        confidence_raw = _to_float(base_confidence, 0.0)
        projected_conf = _clip(confidence_raw + confidence_delta, 0.0, 100.0)

        return {
            "learning_confidence_adjustment": round(confidence_delta, 4),
            "adaptive_weight_score": round(adaptive_weight_score, 4),
            "regime_context": regime_key,
            "adaptive_weights_applied": {
                "confidence": round(confidence_w, 4),
                "timeframe_alignment": round(tf_w, 4),
                "volatility": round(vol_w, 4),
                "walkforward_stability": round(wf_w, 4),
            },
            "weak_pattern_suppression": round(weak_pattern_suppression, 4),
            "strong_pattern_reinforcement": round(strong_pattern_reinforcement, 4),
            "evidence_confidence": round(evidence_confidence, 4),
            "evidence_counts": {
                "global": int(global_n),
                "regime": int(regime_n),
                "setup_type": int(setup_n),
                "persona": int(persona_n),
            },
            "edge_diagnostics": {
                "regime_edge": round(regime_edge, 4),
                "setup_edge": round(setup_edge, 4),
                "persona_edge": round(persona_edge, 4),
                "composite_edge": round(edge_composite, 4),
                "bounded_edge": round(bounded_edge, 4),
                "adaptive_strength": round(adaptive_strength, 4),
                "risk_damper": round(risk_damper, 4),
            },
            "projected_confidence": round(projected_conf, 4),
            "explainability": {
                "regime_key": regime_key,
                "setup_key": setup_key,
                "persona_key": persona_key,
                "reasons": reasons[:8],
            },
        }
