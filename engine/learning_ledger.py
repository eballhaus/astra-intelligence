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
        }

    def _safe_rows(self, limit: int = 3000) -> list[dict[str, Any]]:
        n = max(100, min(10000, int(limit)))
        query = """
            SELECT
                trade_id,
                symbol,
                return_percent,
                friction_adjusted_return,
                trade_origin,
                buy_eligibility,
                buy_mode,
                market_regime,
                entry_persona_fit_summary,
                setup_type,
                signal_tags,
                valid_label,
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
            setup = str(row.get("setup_type") or "unknown").strip().lower() or "unknown"
            by_buy_mode.setdefault(mode, []).append(row)
            by_regime.setdefault(regime, []).append(row)
            by_persona.setdefault(persona, []).append(row)
            by_setup_type.setdefault(setup, []).append(row)

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
        rows = self._safe_rows(limit=3000)
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

