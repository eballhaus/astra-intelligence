"""
Minimal, runtime-safe Conditional Learning Ledger reconstruction.

This module is intentionally conservative:
- Preserves the expected public interface consumed by server_extend.py.
- Produces stable, bounded learning payloads.
- Avoids broad policy rewrites or aggressive multiplier behavior.
"""

from __future__ import annotations

import json
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
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    return int(round(_to_float(value, float(default))))


def _safe_json_load(path: str, default: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _safe_json_dump(path: str, payload: Any) -> None:
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"), ensure_ascii=True)
    except Exception:
        # Non-fatal persistence path.
        return


def _winsorized_avg(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    lo_idx = int(max(0, (n - 1) * 0.05))
    hi_idx = int(min(n - 1, (n - 1) * 0.95))
    lo = ordered[lo_idx]
    hi = ordered[hi_idx]
    clipped = [min(hi, max(lo, v)) for v in ordered]
    return sum(clipped) / float(max(1, len(clipped)))


def _decision_bucket(row: dict[str, Any]) -> str:
    eligibility = str(row.get("buy_eligibility") or "").strip().lower()
    tier = str(row.get("buy_quality_tier") or "").strip().lower()
    merged = f"{eligibility} {tier}"
    if any(x in merged for x in ("block", "reject", "avoid", "non_trade")):
        return "blocked"
    if any(x in merged for x in ("watch", "monitor", "observe")):
        return "watchlist"
    if any(x in merged for x in ("qualified", "soft_buy", "released", "paper_ready", "strong_buy", "buy")):
        return "promoted"
    return "unclassified"


def _to_percent(value: Any) -> float:
    raw = _to_float(value, 0.0)
    if raw <= 1.0:
        raw *= 100.0
    return max(0.0, min(100.0, raw))


def _decision_process_score(row: dict[str, Any]) -> float:
    setup_type = str(row.get("detected_setup_type") or row.get("setup_type") or "").strip().lower()
    prob = _to_percent(row.get("entry_predicted_probability"))
    confidence = _to_percent(row.get("entry_confidence"))
    consensus = _to_percent(row.get("final_consensus_persona_score"))
    eligibility = str(row.get("buy_eligibility") or "").strip().lower()
    tier = str(row.get("buy_quality_tier") or "").strip().lower()
    setup_pen = 12.0 if setup_type in {"", "unknown", "fallback_unclear", "unclassified_setup"} else 0.0
    eligibility_adj = 4.0 if any(x in eligibility for x in ("qualified", "soft_buy", "buy")) else -3.0 if any(x in eligibility for x in ("watch", "monitor")) else -8.0 if any(x in eligibility for x in ("block", "reject", "avoid")) else 0.0
    tier_adj = 4.0 if any(x in tier for x in ("elite", "strong")) else -4.0 if any(x in tier for x in ("weak", "low", "poor")) else 0.0
    return round(
        max(
            0.0,
            min(
                100.0,
                (prob * 0.36) + (consensus * 0.28) + (confidence * 0.22) + 8.0 + eligibility_adj + tier_adj - setup_pen,
            ),
        ),
        2,
    )


def _decision_quality_label(row: dict[str, Any]) -> tuple[str, float]:
    score = _decision_process_score(row)
    good_decision = bool(score >= 58.0)
    good_outcome = bool(_to_float(row.get("return_percent"), 0.0) > 0.0)
    if good_decision and good_outcome:
        return "good_decision_good_outcome", score
    if good_decision and (not good_outcome):
        return "good_decision_bad_outcome", score
    if (not good_decision) and good_outcome:
        return "bad_decision_good_outcome", score
    return "bad_decision_bad_outcome", score


class ConditionalLearningLedger:
    def __init__(
        self,
        db_path: str,
        universe_path: str,
        state_path: str,
        ttl_seconds: int = 20,
        min_segment_samples: int = 30,
    ):
        self.db_path = db_path
        self.universe_path = universe_path
        self.state_path = state_path
        self.ttl_seconds = max(5, int(ttl_seconds or 20))
        self.min_segment_samples = max(10, int(min_segment_samples or 30))
        self._cache: dict[str, Any] = {"ts": 0.0, "payload": None}
        self._universe_cache = _safe_json_load(self.universe_path, {})

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _default_payload(self, message: str = "Insufficient learning data.") -> dict[str, Any]:
        return {
            "generated_at": _utc_now_iso(),
            "insufficient_data": True,
            "message": str(message),
            "totals": {
                "combined": {"trade_count": 0, "valid_trade_count": 0, "win_rate": 0.0, "avg_return": 0.0, "avg_friction_return": 0.0, "median_return": 0.0, "winsorized_avg_return": 0.0},
                "live_paper": {"trade_count": 0, "valid_trade_count": 0, "win_rate": 0.0, "avg_return": 0.0, "avg_friction_return": 0.0, "median_return": 0.0, "winsorized_avg_return": 0.0},
                "replay_paper": {"trade_count": 0, "valid_trade_count": 0, "win_rate": 0.0, "avg_return": 0.0, "avg_friction_return": 0.0, "median_return": 0.0, "winsorized_avg_return": 0.0},
                "hard_buy": {"trade_count": 0, "valid_trade_count": 0, "win_rate": 0.0, "avg_return": 0.0, "avg_friction_return": 0.0, "median_return": 0.0, "winsorized_avg_return": 0.0},
                "soft_buy": {"trade_count": 0, "valid_trade_count": 0, "win_rate": 0.0, "avg_return": 0.0, "avg_friction_return": 0.0, "median_return": 0.0, "winsorized_avg_return": 0.0},
                "hard_vs_soft_delta_avg_return": 0.0,
                "hard_vs_soft_delta_winsorized_avg_return": 0.0,
                "source_contribution": {"live_paper_share_percent": 0.0, "replay_paper_share_percent": 0.0},
            },
            "segments": {
                "by_signal_tag": {},
                "by_buy_mode": {},
                "by_regime": {},
                "by_persona": {},
                "by_setup_type": {},
                "by_setup_regime": {},
                "by_persona_regime": {},
                "by_conviction_tier": {},
                "by_setup_realness": {},
                "by_entry_quality_band": {},
            },
            "adaptive_weights": {
                "persona_weights": {},
                "signal_tag_weights": {},
                "signal_combo_weights": {},
                "regime_weights": {},
            },
            "buy_quality_policy": {
                "action": "keep",
                "soft_buy_multiplier": 1.0,
                "reason": "insufficient_data",
                "min_samples_required": 40,
            },
            "regime_policy_hints": {},
            "setup_policy_hints": {},
            "persona_policy_hints": {},
            "entry_quality_hints": {"sample_size": 0, "good_entry_rate_percent": 0.0, "bad_entry_rate_percent": 0.0, "entry_edge_score": 0.0, "entry_quality_trend": "unknown", "regime_entry_multipliers": {}, "setup_entry_multipliers": {}, "persona_entry_multipliers": {}},
            "decision_quality_v1": {
                "enabled": True,
                "counts": {
                    "good_decision_good_outcome": 0,
                    "good_decision_bad_outcome": 0,
                    "bad_decision_good_outcome": 0,
                    "bad_decision_bad_outcome": 0,
                },
                "rates_percent": {
                    "good_decision_good_outcome": 0.0,
                    "good_decision_bad_outcome": 0.0,
                    "bad_decision_good_outcome": 0.0,
                    "bad_decision_bad_outcome": 0.0,
                },
                "average_decision_process_score": 0.0,
                "outcome_blindness_rate_percent": 0.0,
                "process_miss_rate_percent": 0.0,
                "sample_size": 0,
                "evidence_confidence_percent": 0.0,
            },
            "learning_wiring_v1": {
                "enabled": True,
                "replay_setup_label_coverage_percent": 0.0,
                "replay_rows_with_setup_labels": 0,
                "replay_rows_with_setup": 0,
                "contextual_evidence_rows": 0,
                "setup_regime_policy_count": 0,
                "persona_regime_policy_count": 0,
                "conviction_mapping_count": 0,
                "candidate_realness_mapping_count": 0,
                "setup_type_counts": {},
                "setup_type_win_rates": {},
                "candidate_realness_distribution": {},
                "entry_quality_band_distribution": {},
            },
        }

    def _safe_rows(self, limit: int = 3000) -> list[dict[str, Any]]:
        n = max(100, min(10000, int(limit)))
        try:
            with self._connect() as conn:
                try:
                    cols = {
                        str(r[1] if isinstance(r, tuple) else r["name"]): True
                        for r in (conn.execute("PRAGMA table_info(trade_journal)").fetchall() or [])
                    }
                except Exception:
                    cols = {}
                if "entry_persona_fit_summary" in cols:
                    persona_expr = "entry_persona_fit_summary"
                elif "persona_fit_summary" in cols:
                    persona_expr = "persona_fit_summary AS entry_persona_fit_summary"
                elif "entry_persona_best_fit" in cols:
                    persona_expr = "entry_persona_best_fit AS entry_persona_fit_summary"
                else:
                    persona_expr = "'' AS entry_persona_fit_summary"
                if "detected_setup_type" in cols:
                    setup_detected_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(detected_setup_type),'')<>'' THEN LOWER(detected_setup_type) "
                        "WHEN COALESCE(TRIM(setup_type),'')<>'' THEN LOWER(setup_type) "
                        "ELSE 'fallback_unclear' END AS detected_setup_type"
                    )
                else:
                    setup_detected_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(setup_type),'')<>'' THEN LOWER(setup_type) "
                        "ELSE 'fallback_unclear' END AS detected_setup_type"
                    )
                if "setup_candidate_realness" in cols:
                    setup_realness_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(setup_candidate_realness),'')<>'' THEN LOWER(setup_candidate_realness) "
                        "WHEN UPPER(COALESCE(buy_eligibility,'')) IN ('WATCHLIST','BLOCKED') THEN 'fallback' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'thin_real' "
                        "WHEN UPPER(COALESCE(buy_eligibility,'')) IN ('QUALIFIED','STRONG_BUY') THEN 'real' "
                        "ELSE 'degraded' END AS setup_candidate_realness"
                    )
                else:
                    setup_realness_expr = (
                        "CASE "
                        "WHEN UPPER(COALESCE(buy_eligibility,'')) IN ('WATCHLIST','BLOCKED') THEN 'fallback' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'thin_real' "
                        "WHEN UPPER(COALESCE(buy_eligibility,'')) IN ('QUALIFIED','STRONG_BUY') THEN 'real' "
                        "ELSE 'degraded' END AS setup_candidate_realness"
                    )
                setup_score_expr = "COALESCE(setup_detection_score, 0.0) AS setup_detection_score" if "setup_detection_score" in cols else "0.0 AS setup_detection_score"
                if "setup_detection_band" in cols:
                    setup_band_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(setup_detection_band),'')<>'' THEN LOWER(setup_detection_band) "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'moderate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'weak' "
                        "ELSE 'poor' END AS setup_detection_band"
                    )
                else:
                    setup_band_expr = (
                        "CASE "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'moderate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'weak' "
                        "ELSE 'poor' END AS setup_detection_band"
                    )
                setup_conf_expr = "COALESCE(setup_detection_confidence, 0.0) AS setup_detection_confidence" if "setup_detection_confidence" in cols else "0.0 AS setup_detection_confidence"
                if "setup_detection_evidence_label" in cols:
                    setup_evidence_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(setup_detection_evidence_label),'')<>'' THEN LOWER(setup_detection_evidence_label) "
                        "ELSE 'insufficient' END AS setup_detection_evidence_label"
                    )
                else:
                    setup_evidence_expr = "'insufficient' AS setup_detection_evidence_label"
                conviction_tier_expr = "conviction_tier" if "conviction_tier" in cols else "'' AS conviction_tier"
                eq_score_expr = "entry_quality_score" if "entry_quality_score" in cols else "0.0 AS entry_quality_score"
                if "entry_quality_band" in cols:
                    eq_band_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(entry_quality_band),'')<>'' THEN LOWER(entry_quality_band) "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'moderate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'weak' "
                        "ELSE 'poor' END AS entry_quality_band"
                    )
                else:
                    eq_band_expr = (
                        "CASE "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'moderate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'weak' "
                        "ELSE 'poor' END AS entry_quality_band"
                    )
                if "entry_quality_candidate_class" in cols:
                    eq_class_expr = (
                        "CASE "
                        "WHEN COALESCE(TRIM(entry_quality_candidate_class),'')<>'' THEN LOWER(entry_quality_candidate_class) "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'real_candidate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'real_but_thin' "
                        "ELSE 'fallback_recovery' END AS entry_quality_candidate_class"
                    )
                else:
                    eq_class_expr = (
                        "CASE "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='QUALIFIED' THEN 'real_candidate' "
                        "WHEN UPPER(COALESCE(buy_eligibility,''))='SOFT_BUY' THEN 'real_but_thin' "
                        "ELSE 'fallback_recovery' END AS entry_quality_candidate_class"
                    )
                eq_driver_expr = "COALESCE(NULLIF(TRIM(entry_quality_primary_driver),''), 'none') AS entry_quality_primary_driver" if "entry_quality_primary_driver" in cols else "'none' AS entry_quality_primary_driver"
                eq_penalty_expr = "COALESCE(NULLIF(TRIM(entry_quality_primary_penalty),''), 'missing_evidence_penalty') AS entry_quality_primary_penalty" if "entry_quality_primary_penalty" in cols else "'missing_evidence_penalty' AS entry_quality_primary_penalty"
                eq_evidence_expr = "COALESCE(NULLIF(TRIM(entry_quality_evidence_label),''), 'insufficient') AS entry_quality_evidence_label" if "entry_quality_evidence_label" in cols else "'insufficient' AS entry_quality_evidence_label"

                query = f"""
                    SELECT
                        trade_id,
                        symbol,
                        return_percent,
                        friction_adjusted_return,
                        trade_origin,
                        buy_eligibility,
                        buy_quality_tier,
                        buy_mode,
                        market_regime,
                        {persona_expr},
                        setup_type,
                        {setup_detected_expr},
                        {setup_realness_expr},
                        {setup_score_expr},
                        {setup_band_expr},
                        {setup_conf_expr},
                        {setup_evidence_expr},
                        {conviction_tier_expr},
                        {eq_score_expr},
                        {eq_band_expr},
                        {eq_class_expr},
                        {eq_driver_expr},
                        {eq_penalty_expr},
                        {eq_evidence_expr},
                        entry_predicted_probability,
                        entry_confidence,
                        final_consensus_persona_score,
                        signal_tags,
                        valid_label,
                        entry_timestamp,
                        exit_timestamp
                    FROM trade_journal
                    WHERE exit_timestamp IS NOT NULL
                      AND return_percent IS NOT NULL
                    ORDER BY exit_timestamp DESC
                    LIMIT ?
                """
                rows = conn.execute(query, (n,)).fetchall()
            return [dict(r or {}) for r in rows]
        except Exception:
            return []

    def _counterfactual_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = {
            "promoted": [],
            "blocked": [],
            "watchlist": [],
            "unclassified": [],
        }
        for row in rows:
            buckets.setdefault(_decision_bucket(row), []).append(row)
        promoted = self._stats_from_rows(buckets.get("promoted") or [])
        blocked = self._stats_from_rows(buckets.get("blocked") or [])
        watchlist = self._stats_from_rows(buckets.get("watchlist") or [])
        return {
            "promoted": promoted,
            "blocked": blocked,
            "watchlist": watchlist,
            "promoted_vs_blocked_gap": {
                "win_rate_gap": round(_to_float(promoted.get("win_rate"), 0.0) - _to_float(blocked.get("win_rate"), 0.0), 2),
                "avg_return_gap": round(_to_float(promoted.get("avg_return"), 0.0) - _to_float(blocked.get("avg_return"), 0.0), 4),
                "winsorized_avg_return_gap": round(
                    _to_float(promoted.get("winsorized_avg_return"), 0.0) - _to_float(blocked.get("winsorized_avg_return"), 0.0),
                    4,
                ),
            },
            "sample_sizes": {
                "promoted": int(promoted.get("trade_count", 0)),
                "blocked": int(blocked.get("trade_count", 0)),
                "watchlist": int(watchlist.get("trade_count", 0)),
                "unclassified": int(len(buckets.get("unclassified") or [])),
            },
        }

    def _decision_quality_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        counts = {
            "good_decision_good_outcome": 0,
            "good_decision_bad_outcome": 0,
            "bad_decision_good_outcome": 0,
            "bad_decision_bad_outcome": 0,
        }
        score_values: list[float] = []
        for row in rows:
            label, score = _decision_quality_label(row)
            counts[label] = int(counts.get(label, 0)) + 1
            score_values.append(float(score))
        total = max(1, sum(counts.values()))
        return {
            "enabled": True,
            "counts": counts,
            "rates_percent": {k: round((float(v) / float(total)) * 100.0, 2) for k, v in counts.items()},
            "average_decision_process_score": round(sum(score_values) / max(1, len(score_values)), 2) if score_values else 0.0,
            "outcome_blindness_rate_percent": round((float(counts["bad_decision_good_outcome"]) / float(total)) * 100.0, 2),
            "process_miss_rate_percent": round((float(counts["good_decision_bad_outcome"]) / float(total)) * 100.0, 2),
            "sample_size": int(sum(counts.values())),
            "evidence_confidence_percent": round(min(100.0, (float(sum(counts.values())) / 260.0) * 100.0), 2),
        }

    def _stats_from_rows(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {
                "trade_count": 0,
                "valid_trade_count": 0,
                "win_rate": 0.0,
                "avg_return": 0.0,
                "avg_friction_return": 0.0,
                "median_return": 0.0,
                "winsorized_avg_return": 0.0,
            }
        rets = [_to_float(r.get("return_percent"), 0.0) for r in rows]
        friction = [_to_float(r.get("friction_adjusted_return"), _to_float(r.get("return_percent"), 0.0)) for r in rows]
        wins = len([x for x in rets if x > 0])
        n = len(rows)
        ordered = sorted(rets)
        median = ordered[n // 2] if n % 2 else (ordered[(n // 2) - 1] + ordered[n // 2]) / 2.0
        return {
            "trade_count": int(n),
            "valid_trade_count": int(n),
            "win_rate": round((wins / float(max(1, n))) * 100.0, 2),
            "avg_return": round(sum(rets) / float(max(1, n)), 4),
            "avg_friction_return": round(sum(friction) / float(max(1, n)), 4),
            "median_return": round(float(median), 4),
            "winsorized_avg_return": round(_winsorized_avg(rets), 4),
        }

    def _build_segments(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        by_signal_tag: dict[str, list[dict[str, Any]]] = {}
        by_buy_mode: dict[str, list[dict[str, Any]]] = {}
        by_regime: dict[str, list[dict[str, Any]]] = {}
        by_persona: dict[str, list[dict[str, Any]]] = {}
        by_setup_type: dict[str, list[dict[str, Any]]] = {}
        by_setup_regime: dict[str, list[dict[str, Any]]] = {}
        by_persona_regime: dict[str, list[dict[str, Any]]] = {}
        by_conviction_tier: dict[str, list[dict[str, Any]]] = {}
        by_setup_realness: dict[str, list[dict[str, Any]]] = {}
        by_entry_quality_band: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            sig_val = row.get("signal_tags")
            tags: list[str] = []
            if isinstance(sig_val, str):
                s = sig_val.strip()
                if s.startswith("[") and s.endswith("]"):
                    try:
                        parsed = json.loads(s)
                        if isinstance(parsed, list):
                            tags = [str(t).strip().lower() for t in parsed if str(t).strip()]
                    except Exception:
                        tags = [x.strip().lower() for x in s.split(",") if x.strip()]
                else:
                    tags = [x.strip().lower() for x in s.split(",") if x.strip()]
            elif isinstance(sig_val, list):
                tags = [str(t).strip().lower() for t in sig_val if str(t).strip()]
            for t in tags[:5]:
                by_signal_tag.setdefault(t, []).append(row)

            mode = str(row.get("buy_mode") or "balanced").strip().lower() or "balanced"
            regime = str(row.get("market_regime") or "unknown").strip().lower() or "unknown"
            persona = str(row.get("entry_persona_fit_summary") or "unknown").strip().lower() or "unknown"
            setup = str(row.get("detected_setup_type") or row.get("setup_type") or "unknown").strip().lower() or "unknown"
            conviction = str(row.get("conviction_tier") or "unknown").strip().lower() or "unknown"
            setup_realness = str(row.get("setup_candidate_realness") or "unknown").strip().lower() or "unknown"
            entry_quality_band = str(row.get("entry_quality_band") or "unknown").strip().lower() or "unknown"
            by_buy_mode.setdefault(mode, []).append(row)
            by_regime.setdefault(regime, []).append(row)
            by_persona.setdefault(persona, []).append(row)
            by_setup_type.setdefault(setup, []).append(row)
            by_setup_regime.setdefault(f"{setup}|{regime}", []).append(row)
            by_persona_regime.setdefault(f"{persona}|{regime}", []).append(row)
            by_conviction_tier.setdefault(conviction, []).append(row)
            by_setup_realness.setdefault(setup_realness, []).append(row)
            by_entry_quality_band.setdefault(entry_quality_band, []).append(row)

        def _pack(seg_map: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key, seg_rows in seg_map.items():
                if len(seg_rows) < self.min_segment_samples:
                    continue
                out[key] = self._stats_from_rows(seg_rows)
            return out

        return {
            "by_signal_tag": _pack(by_signal_tag),
            "by_buy_mode": _pack(by_buy_mode),
            "by_regime": _pack(by_regime),
            "by_persona": _pack(by_persona),
            "by_setup_type": _pack(by_setup_type),
            "by_setup_regime": _pack(by_setup_regime),
            "by_persona_regime": _pack(by_persona_regime),
            "by_conviction_tier": _pack(by_conviction_tier),
            "by_setup_realness": _pack(by_setup_realness),
            "by_entry_quality_band": _pack(by_entry_quality_band),
        }

    def _derive_weights(self, segments: dict[str, Any]) -> dict[str, Any]:
        persona_weights: dict[str, float] = {}
        regime_weights: dict[str, float] = {}
        signal_tag_weights: dict[str, float] = {}

        for key, stats in (segments.get("by_persona") or {}).items():
            win_rate = _to_float((stats or {}).get("win_rate"), 50.0)
            persona_weights[str(key)] = round(max(0.9, min(1.1, 1.0 + ((win_rate - 50.0) / 500.0))), 4)
        for key, stats in (segments.get("by_regime") or {}).items():
            wr = _to_float((stats or {}).get("winsorized_avg_return"), 0.0)
            regime_weights[str(key)] = round(max(0.9, min(1.1, 1.0 + (wr / 40.0))), 4)
        for key, stats in (segments.get("by_signal_tag") or {}).items():
            wr = _to_float((stats or {}).get("winsorized_avg_return"), 0.0)
            signal_tag_weights[str(key)] = round(max(0.9, min(1.1, 1.0 + (wr / 35.0))), 4)

        return {
            "persona_weights": persona_weights,
            "signal_tag_weights": signal_tag_weights,
            "signal_combo_weights": {},
            "regime_weights": regime_weights,
        }

    def _build_payload(self) -> dict[str, Any]:
        rows = self._safe_rows(limit=8000)
        if not rows:
            payload = self._default_payload("Insufficient learning data.")
            payload["generated_at"] = _utc_now_iso()
            return payload

        live_rows = [r for r in rows if str(r.get("trade_origin") or "").strip().lower() == "paper_autopilot"]
        replay_rows = [r for r in rows if str(r.get("trade_origin") or "").strip().lower() == "paper_replay"]
        hard_rows = [r for r in rows if str(r.get("buy_eligibility") or "").strip().upper() == "QUALIFIED"]
        soft_rows = [r for r in rows if str(r.get("buy_eligibility") or "").strip().upper() != "QUALIFIED"]

        combined = self._stats_from_rows(rows)
        live_stats = self._stats_from_rows(live_rows)
        replay_stats = self._stats_from_rows(replay_rows)
        hard_stats = self._stats_from_rows(hard_rows)
        soft_stats = self._stats_from_rows(soft_rows)

        segments = self._build_segments(rows)
        adaptive_weights = self._derive_weights(segments)
        counterfactual = self._counterfactual_from_rows(rows)
        decision_quality = self._decision_quality_from_rows(rows)

        total_valid = max(1.0, float(_to_int(combined.get("valid_trade_count"), 0)))
        live_share = (_to_float(live_stats.get("valid_trade_count"), 0.0) / total_valid) * 100.0
        replay_share = (_to_float(replay_stats.get("valid_trade_count"), 0.0) / total_valid) * 100.0
        hard_vs_soft_delta_avg = _to_float(hard_stats.get("avg_return"), 0.0) - _to_float(soft_stats.get("avg_return"), 0.0)
        hard_vs_soft_delta_w = _to_float(hard_stats.get("winsorized_avg_return"), 0.0) - _to_float(soft_stats.get("winsorized_avg_return"), 0.0)

        soft_action = "keep"
        soft_mult = 1.0
        if _to_int(soft_stats.get("valid_trade_count"), 0) >= 40 and hard_vs_soft_delta_w > 0.35:
            soft_action = "downweight"
            soft_mult = 0.96
        elif _to_int(soft_stats.get("valid_trade_count"), 0) >= 40 and hard_vs_soft_delta_w < -0.25:
            soft_action = "favor_soft"
            soft_mult = 1.02

        by_regime = segments.get("by_regime") or {}
        by_setup = segments.get("by_setup_type") or {}
        by_persona = segments.get("by_persona") or {}
        regime_hints = {}
        setup_hints = {}
        persona_hints = {}
        for key, stats in by_regime.items():
            regime_hints[str(key)] = {"multiplier": round(max(0.92, min(1.08, 1.0 + (_to_float((stats or {}).get("winsorized_avg_return"), 0.0) / 45.0))), 4)}
        for key, stats in by_setup.items():
            setup_hints[str(key)] = {"multiplier": round(max(0.92, min(1.08, 1.0 + (_to_float((stats or {}).get("winsorized_avg_return"), 0.0) / 45.0))), 4)}
        for key, stats in by_persona.items():
            persona_hints[str(key)] = {"multiplier": round(max(0.92, min(1.08, 1.0 + ((_to_float((stats or {}).get("win_rate"), 50.0) - 50.0) / 500.0))), 4)}

        entry_edge = 0.0
        if _to_int(combined.get("valid_trade_count"), 0) > 0:
            good_entries = int(round((_to_float(combined.get("win_rate"), 0.0) / 100.0) * _to_float(combined.get("valid_trade_count"), 0.0)))
            bad_entries = max(0, _to_int(combined.get("valid_trade_count"), 0) - good_entries)
            entry_edge = (good_entries - bad_entries) / max(1.0, _to_float(combined.get("valid_trade_count"), 1.0))

        timestamp_rows = [r for r in rows if str(r.get("exit_timestamp") or "").strip()]
        newest_ts = str((timestamp_rows[0] or {}).get("exit_timestamp") or "") if timestamp_rows else ""
        oldest_ts = str((timestamp_rows[-1] or {}).get("exit_timestamp") or "") if timestamp_rows else ""
        unique_symbols = len({str(r.get("symbol") or "").upper() for r in rows if str(r.get("symbol") or "").strip()})
        active_recent = rows[:1200]
        symbol_activity: dict[str, int] = {}
        for r in active_recent:
            sym = str(r.get("symbol") or "").upper().strip()
            if not sym:
                continue
            symbol_activity[sym] = int(symbol_activity.get(sym, 0)) + 1
        parallel_symbols = len([s for s, n in symbol_activity.items() if n >= 2])
        context_quality = {
            "setup_type_population_rate_percent": round(
                (
                    len(
                        [
                            r
                            for r in rows
                            if str(r.get("detected_setup_type") or r.get("setup_type") or "").strip()
                        ]
                    )
                    / max(1.0, float(len(rows)))
                )
                * 100.0,
                2,
            ),
            "regime_population_rate_percent": round(
                (len([r for r in rows if str(r.get("market_regime") or "").strip()]) / max(1.0, float(len(rows)))) * 100.0,
                2,
            ),
            "persona_population_rate_percent": round(
                (len([r for r in rows if str(r.get("entry_persona_fit_summary") or "").strip()]) / max(1.0, float(len(rows)))) * 100.0,
                2,
            ),
            "buy_eligibility_population_rate_percent": round(
                (len([r for r in rows if str(r.get("buy_eligibility") or "").strip()]) / max(1.0, float(len(rows)))) * 100.0,
                2,
            ),
        }
        setup_type_counts: dict[str, int] = {}
        setup_type_returns: dict[str, list[float]] = {}
        candidate_realness_distribution: dict[str, int] = {}
        entry_quality_band_distribution: dict[str, int] = {}
        for r in rows:
            setup_key = str(r.get("detected_setup_type") or r.get("setup_type") or "unknown").strip().lower() or "unknown"
            setup_type_counts[setup_key] = int(setup_type_counts.get(setup_key, 0)) + 1
            setup_type_returns.setdefault(setup_key, []).append(_to_float(r.get("return_percent"), 0.0))
            real_key = str(r.get("setup_candidate_realness") or "unknown").strip().lower() or "unknown"
            candidate_realness_distribution[real_key] = int(candidate_realness_distribution.get(real_key, 0)) + 1
            eq_key = str(r.get("entry_quality_band") or "unknown").strip().lower() or "unknown"
            entry_quality_band_distribution[eq_key] = int(entry_quality_band_distribution.get(eq_key, 0)) + 1

        setup_type_win_rates: dict[str, float] = {}
        for k, vals in setup_type_returns.items():
            if len(vals) < self.min_segment_samples:
                continue
            setup_type_win_rates[str(k)] = round(
                (len([x for x in vals if x > 0.0]) / max(1, len(vals))) * 100.0,
                2,
            )
        replay_rows_with_setup = [
            r for r in replay_rows if str(r.get("detected_setup_type") or r.get("setup_type") or "").strip()
        ]
        replay_rows_with_labels = [
            r
            for r in replay_rows
            if str(r.get("setup_candidate_realness") or "").strip()
            and str(r.get("entry_quality_band") or "").strip()
        ]
        replay_setup_label_coverage = round(
            (float(len(replay_rows_with_labels)) / max(1.0, float(len(replay_rows_with_setup)))) * 100.0,
            2,
        )
        contextual_evidence_rows = len(
            [
                r
                for r in rows
                if str(r.get("detected_setup_type") or r.get("setup_type") or "").strip()
                and str(r.get("market_regime") or "").strip()
                and str(r.get("entry_persona_fit_summary") or "").strip()
                and _to_float(r.get("entry_quality_score"), 0.0) > 0.0
            ]
        )
        setup_regime_policy_count = int(len(segments.get("by_setup_regime") or {}))
        persona_regime_policy_count = int(len(segments.get("by_persona_regime") or {}))
        conviction_mapping_count = int(len(segments.get("by_conviction_tier") or {}))
        candidate_realness_mapping_count = int(len(segments.get("by_setup_realness") or {}))

        payload = self._default_payload("Learning insights active.")
        payload.update(
            {
                "generated_at": _utc_now_iso(),
                "insufficient_data": bool(_to_int(combined.get("valid_trade_count"), 0) < 30),
                "message": "Learning insights active." if _to_int(combined.get("valid_trade_count"), 0) >= 30 else "Insufficient learning data.",
                "totals": {
                    "combined": combined,
                    "live_paper": live_stats,
                    "replay_paper": replay_stats,
                    "hard_buy": hard_stats,
                    "soft_buy": soft_stats,
                    "hard_vs_soft_delta_avg_return": round(hard_vs_soft_delta_avg, 4),
                    "hard_vs_soft_delta_winsorized_avg_return": round(hard_vs_soft_delta_w, 4),
                    "source_contribution": {
                        "live_paper_share_percent": round(max(0.0, min(100.0, live_share)), 2),
                        "replay_paper_share_percent": round(max(0.0, min(100.0, replay_share)), 2),
                    },
                    "raw_closed_trades": int(len(rows)),
                    "valid_trades": int(_to_int(combined.get("valid_trade_count"), 0)),
                    "invalid_trades": int(max(0, len(rows) - _to_int(combined.get("valid_trade_count"), 0))),
                    "invalid_reason_counts": {},
                },
                "segments": segments,
                "adaptive_weights": adaptive_weights,
                "buy_quality_policy": {
                    "action": soft_action,
                    "soft_buy_multiplier": round(soft_mult, 4),
                    "reason": "hard_vs_soft_outcome_delta",
                    "winsorized_return_delta": round(hard_vs_soft_delta_w, 4),
                    "win_rate_delta": round(_to_float(hard_stats.get("win_rate"), 0.0) - _to_float(soft_stats.get("win_rate"), 0.0), 2),
                    "hard_trade_count": _to_int(hard_stats.get("valid_trade_count"), 0),
                    "soft_trade_count": _to_int(soft_stats.get("valid_trade_count"), 0),
                    "min_samples_required": 40,
                },
                "regime_policy_hints": regime_hints,
                "setup_policy_hints": setup_hints,
                "persona_policy_hints": persona_hints,
                "entry_quality_hints": {
                    "sample_size": _to_int(combined.get("valid_trade_count"), 0),
                    "good_entry_rate_percent": round(max(0.0, min(100.0, _to_float(combined.get("win_rate"), 0.0))), 2),
                    "bad_entry_rate_percent": round(max(0.0, min(100.0, 100.0 - _to_float(combined.get("win_rate"), 0.0))), 2),
                    "entry_edge_score": round(entry_edge, 4),
                    "entry_quality_trend": "improving" if entry_edge > 0.08 else ("weak" if entry_edge < -0.08 else "mixed"),
                    "regime_entry_multipliers": {k: _to_float((v or {}).get("multiplier"), 1.0) for k, v in regime_hints.items()},
                    "setup_entry_multipliers": {k: _to_float((v or {}).get("multiplier"), 1.0) for k, v in setup_hints.items()},
                    "persona_entry_multipliers": {k: _to_float((v or {}).get("multiplier"), 1.0) for k, v in persona_hints.items()},
                },
                "counterfactual_learning": counterfactual,
                "decision_quality_v1": decision_quality,
                "learning_quality": {
                    "sample_size": int(_to_int(combined.get("valid_trade_count"), 0)),
                    "replay_sample_size": int(_to_int(replay_stats.get("valid_trade_count"), 0)),
                    "quality_score": round(min(100.0, max(0.0, (_to_float(combined.get("win_rate"), 0.0) * 0.55) + (min(100.0, len(rows) / 120.0) * 0.45))), 2),
                    "maturity": "high" if len(rows) >= 4000 else ("medium" if len(rows) >= 1200 else "low"),
                    "label_coverage": {
                        "valid_labeled_count": int(_to_int(combined.get("valid_trade_count"), 0)),
                        "raw_closed_trades": int(len(rows)),
                        "coverage_percent": round((float(_to_int(combined.get("valid_trade_count"), 0)) / max(1.0, float(len(rows)))) * 100.0, 2),
                    },
                    "path_coverage": {
                        "live_paper_share_percent": round(max(0.0, min(100.0, live_share)), 2),
                        "replay_paper_share_percent": round(max(0.0, min(100.0, replay_share)), 2),
                    },
                },
                "contextual_execution_refinement": {
                    "execution_evidence_count": int(_to_int(combined.get("valid_trade_count"), 0)),
                    "contextual_evidence_rows": int(contextual_evidence_rows),
                    "entry_context_count": int(len(segments.get("by_setup_type") or {})),
                    "hold_context_count": int(len(segments.get("by_regime") or {})),
                    "exit_context_count": int(len(segments.get("by_persona") or {})),
                    "soft_suppression_context_count": int(len([k for k in (segments.get("by_buy_mode") or {}).keys() if "soft" in str(k)])),
                    "conviction_support_context_count": int(len(segments.get("by_signal_tag") or {})),
                    "setup_regime_policy_count": int(setup_regime_policy_count),
                    "persona_regime_policy_count": int(persona_regime_policy_count),
                    "conviction_mapping_count": int(conviction_mapping_count),
                    "recommended_execution_posture": "balanced",
                    "execution_refinement_score": round(min(100.0, max(0.0, (_to_float(combined.get("win_rate"), 0.0) * 0.5) + (min(100.0, len(rows) / 160.0) * 0.5))), 2),
                    "top_wait_contexts": [],
                    "top_immediate_contexts": [],
                },
                "policy_adaptation": {
                    "entry_edge_score": round(entry_edge, 4),
                    "contextual_execution_evidence_count": int(_to_int(combined.get("valid_trade_count"), 0)),
                    "hard_vs_soft_action": soft_action,
                    "soft_buy_multiplier": round(soft_mult, 4),
                },
                "learning_wiring_v1": {
                    "enabled": True,
                    "replay_setup_label_coverage_percent": replay_setup_label_coverage,
                    "replay_rows_with_setup_labels": int(len(replay_rows_with_labels)),
                    "replay_rows_with_setup": int(len(replay_rows_with_setup)),
                    "contextual_evidence_rows": int(contextual_evidence_rows),
                    "setup_regime_policy_count": int(setup_regime_policy_count),
                    "persona_regime_policy_count": int(persona_regime_policy_count),
                    "conviction_mapping_count": int(conviction_mapping_count),
                    "candidate_realness_mapping_count": int(candidate_realness_mapping_count),
                    "setup_type_counts": setup_type_counts,
                    "setup_type_win_rates": setup_type_win_rates,
                    "candidate_realness_distribution": candidate_realness_distribution,
                    "entry_quality_band_distribution": entry_quality_band_distribution,
                },
                "learning_acceleration_v1": {
                    "enabled": True,
                    "historical_trade_memory": {
                        "rows_considered": int(len(rows)),
                        "oldest_exit_timestamp": oldest_ts,
                        "newest_exit_timestamp": newest_ts,
                        "unique_symbols": int(unique_symbols),
                        "memory_depth_tier": (
                            "deep"
                            if len(rows) >= 4500
                            else "moderate"
                            if len(rows) >= 1500
                            else "early"
                        ),
                    },
                    "simultaneous_evidence": {
                        "recent_rows_considered": int(len(active_recent)),
                        "symbols_with_multiple_closed_trades_recent": int(parallel_symbols),
                        "symbol_activity_sample_size": int(len(symbol_activity)),
                        "parallel_evidence_score": round(min(100.0, (parallel_symbols / 18.0) * 100.0), 2),
                    },
                    "learning_data_quality": context_quality,
                },
            }
        )
        return payload

    def insights(self) -> dict[str, Any]:
        now = time.time()
        cached = self._cache.get("payload")
        ts = float(self._cache.get("ts", 0.0))
        if isinstance(cached, dict) and cached and (now - ts) <= self.ttl_seconds:
            return dict(cached)

        try:
            payload = self._build_payload()
            self._cache["payload"] = dict(payload)
            self._cache["ts"] = now
            _safe_json_dump(self.state_path, payload)
            return payload
        except Exception:
            # Conservative fallback to last persisted state if available.
            persisted = _safe_json_load(self.state_path, {})
            if isinstance(persisted, dict) and persisted:
                persisted.setdefault("insufficient_data", True)
                persisted.setdefault("message", "Learning ledger using persisted fallback.")
                return persisted
            return self._default_payload("Learning ledger unavailable.")

    def adjustment_for_row(self, row: dict[str, Any], buy_mode: str | None = None) -> dict[str, Any]:
        row = row if isinstance(row, dict) else {}
        insights = self.insights()
        mult = 1.0
        reasons: list[str] = []

        # Base buy-mode policy
        bq = insights.get("buy_quality_policy") if isinstance(insights.get("buy_quality_policy"), dict) else {}
        action = str((bq or {}).get("action") or "keep").strip().lower()
        soft_mult = _to_float((bq or {}).get("soft_buy_multiplier"), 1.0)

        is_soft = str(row.get("buy_eligibility") or "").strip().upper() == "SOFT_BUY"
        mode = str(buy_mode or row.get("buy_mode") or "balanced").strip().lower()
        if is_soft and action in {"downweight", "heavy_penalty", "suppress_when_hard_exists"}:
            mult *= max(0.9, min(1.02, soft_mult))
            reasons.append(f"soft_buy_policy:{action}")
        elif is_soft and action == "favor_soft":
            mult *= max(0.98, min(1.06, soft_mult))
            reasons.append("soft_buy_policy:favor_soft")
        else:
            reasons.append("soft_buy_policy:keep")

        # Segment/context multipliers (bounded and conservative)
        regime = str(row.get("regime_context") or row.get("market_regime") or "unknown").strip().lower()
        setup = str(row.get("setup_type") or "unknown").strip().lower()
        persona = str(row.get("persona_best_fit") or row.get("entry_persona_fit_summary") or "unknown").strip().lower()

        reg_h = insights.get("regime_policy_hints") if isinstance(insights.get("regime_policy_hints"), dict) else {}
        set_h = insights.get("setup_policy_hints") if isinstance(insights.get("setup_policy_hints"), dict) else {}
        per_h = insights.get("persona_policy_hints") if isinstance(insights.get("persona_policy_hints"), dict) else {}
        reg_m = _to_float(((reg_h.get(regime) or {}).get("multiplier")), 1.0)
        set_m = _to_float(((set_h.get(setup) or {}).get("multiplier")), 1.0)
        per_m = _to_float(((per_h.get(persona) or {}).get("multiplier")), 1.0)

        context_mult = (reg_m * set_m * per_m) ** (1.0 / 3.0)
        context_mult = max(0.95, min(1.05, context_mult))
        mult *= context_mult
        reasons.append(f"context:{regime}|{setup}|{persona}")

        # Light mode sensitivity
        if mode in {"conservative", "safe"}:
            mult *= 0.99
            reasons.append("buy_mode:conservative")
        elif mode in {"aggressive", "adaptive"}:
            mult *= 1.005
            reasons.append("buy_mode:adaptive")

        # Final bound keeps behavior stable.
        mult = max(0.9, min(1.08, mult))
        return {
            "multiplier": round(mult, 4),
            "reasons": reasons[:6],
        }
