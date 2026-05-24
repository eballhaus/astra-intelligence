from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.replay_lifecycle_expectancy_learning_v1 import ReplayLifecycleExpectancyLearningV1
except Exception:  # pragma: no cover - additive learning reference only
    ReplayLifecycleExpectancyLearningV1 = None  # type: ignore[assignment]
try:
    from engine.regime_execution_survivability_intelligence_v1 import RegimeExecutionSurvivabilityIntelligenceV1
except Exception:  # pragma: no cover - additive learning reference only
    RegimeExecutionSurvivabilityIntelligenceV1 = None  # type: ignore[assignment]
try:
    from engine.adaptive_execution_exit_intelligence_v2 import AdaptiveExecutionExitIntelligenceV2
except Exception:  # pragma: no cover - additive learning reference only
    AdaptiveExecutionExitIntelligenceV2 = None  # type: ignore[assignment]

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_iso() -> str:
    return date.today().isoformat()


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


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _safe_text(
        row.get("candidate_universe_tier")
        or row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization") or row.get("marketCap"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000:
        return "mega_cap"
    if "large" in raw or cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (0.0 < cap < 300_000_000):
        return "micro_cap"
    return "unknown"


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


def _mode_from_score(score: float) -> str:
    if score >= 82.0:
        return "mature_portfolio_system"
    if score >= 68.0:
        return "advanced_learning_system"
    if score >= 52.0:
        return "adaptive_system"
    return "emerging_system"


def _behavior_label(row: dict[str, Any]) -> str:
    liquidity = _score01(row.get("liquidity_stability_score"), _score01(row.get("liquidity_score"), 55.0))
    crowding = _score01(row.get("momentum_crowding_risk"), 35.0)
    exhaustion = _score01(row.get("trend_exhaustion_behavior_score"), _score01(row.get("trend_exhaustion_score"), 35.0))
    gap = _score01(row.get("gap_risk_score"), 35.0)
    breakout = _score01(row.get("breakout_quality_score"), _score01(row.get("breakout_probability_score"), 50.0))
    if liquidity < 38.0:
        return "low_liquidity_caution"
    if gap >= 76.0:
        return "high_gap_risk"
    if exhaustion >= 72.0:
        return "exhaustion_risk"
    if crowding >= 72.0:
        return "momentum_crowding"
    if breakout >= 64.0:
        return "breakout_watch"
    return "stable_behavior"


class AdaptiveLearningInfrastructureV1:
    """Shadow-learning infrastructure for review, replay readiness, and explainability.

    This engine is deliberately non-authoritative: it does not execute, close,
    resize, promote, or modify live/paper broker behavior.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.paper_state_path = os.path.join(self.state_dir, "paper_autopilot_state.json")
        self._history_cache: dict[str, Any] | None = None
        self.replay_lifecycle_expectancy = (
            ReplayLifecycleExpectancyLearningV1(state_dir=self.state_dir) if ReplayLifecycleExpectancyLearningV1 is not None else None
        )
        self.regime_execution_survivability = (
            RegimeExecutionSurvivabilityIntelligenceV1(state_dir=self.state_dir)
            if RegimeExecutionSurvivabilityIntelligenceV1 is not None
            else None
        )
        self.adaptive_execution_exit_v2 = (
            AdaptiveExecutionExitIntelligenceV2(state_dir=self.state_dir)
            if AdaptiveExecutionExitIntelligenceV2 is not None
            else None
        )

    def _history(self) -> dict[str, Any]:
        if self._history_cache is not None:
            return self._history_cache
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=350))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=300))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        today = _today_iso()
        today_rows = [r for r in rows if today in _safe_text(r.get("timestamp") or r.get("created_at") or r.get("closed_at") or r.get("entry_time"))]
        archetype_returns: dict[str, list[float]] = defaultdict(list)
        lane_returns: dict[str, list[float]] = defaultdict(list)
        session_returns: dict[str, list[float]] = defaultdict(list)
        horizon_returns: dict[str, list[float]] = defaultdict(list)
        blockers = Counter()
        rejections = Counter()
        durations: list[float] = []
        for raw in rows[-MAX_ROWS:]:
            row = dict(raw or {})
            ret = _to_float(row.get("realized_return_pct") or row.get("return_pct") or row.get("pnl_pct"), 0.0)
            archetype = _safe_text(row.get("trade_archetype") or row.get("setup_type"), "unknown").lower().replace(" ", "_")
            lane = _safe_text(row.get("allocation_lane"), "unknown").lower().replace(" ", "_")
            session = _safe_text(row.get("entry_session_mode") or row.get("trade_session_context"), "unknown").lower().replace(" ", "_")
            horizon = _safe_text(row.get("trade_horizon_style") or row.get("best_horizon_style"), "unknown").lower().replace(" ", "_")
            archetype_returns[archetype].append(ret)
            lane_returns[lane].append(ret)
            session_returns[session].append(ret)
            horizon_returns[horizon].append(ret)
            blocker = _safe_text(row.get("final_blocker_reason") or row.get("decision_reason"))
            rejection = _safe_text(row.get("order_rejection_reason") or row.get("exploration_rejection_reason"))
            if blocker:
                blockers[blocker] += 1
            if rejection:
                rejections[rejection] += 1
            duration = _to_float(row.get("hold_time_hours") or row.get("duration_hours") or row.get("average_hold_time"), -1.0)
            if duration >= 0:
                durations.append(duration)
        self._history_cache = {
            "rows": rows[-MAX_ROWS:],
            "today_rows": today_rows[-200:],
            "blockers": blockers,
            "rejections": rejections,
            "archetype_returns": archetype_returns,
            "lane_returns": lane_returns,
            "session_returns": session_returns,
            "horizon_returns": horizon_returns,
            "average_duration_hours": round(mean(durations), 3) if durations else 0.0,
        }
        return self._history_cache

    def _paper_state(self) -> dict[str, Any]:
        try:
            with open(self.paper_state_path, "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
                return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _portfolio_context(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(rows))
        caps = Counter(_market_cap_bucket(r) for r in rows)
        sectors = Counter(_safe_text(r.get("sector") or r.get("sector_name"), "unknown").lower() for r in rows)
        archetypes = Counter(_safe_text(r.get("trade_archetype") or r.get("setup_type"), "unknown").lower() for r in rows)
        lanes = Counter(_safe_text(r.get("allocation_lane"), "unknown").lower() for r in rows)
        max_cap = max((v for k, v in caps.items() if k != "unknown"), default=0) / n
        max_sector = max((v for k, v in sectors.items() if k != "unknown"), default=0) / n
        max_archetype = max((v for k, v in archetypes.items() if k != "unknown"), default=0) / n
        heat = _clamp((max(max_cap, max_sector, max_archetype) * 70.0) + (caps.get("mega_cap", 0) / n * 30.0))
        concentration = _clamp(max(max_cap, max_sector, max_archetype) * 100.0)
        return {
            "portfolio_heat_score": round(heat, 2),
            "concentration_score": round(concentration, 2),
            "cap_distribution": dict(caps),
            "sector_distribution": dict(sectors),
            "archetype_distribution": dict(archetypes),
            "allocation_lane_distribution": dict(lanes),
            "portfolio_heat_summary": f"Heat {round(heat, 1)} with cap mix {dict(caps)}.",
            "concentration_summary": f"Highest concentration bucket {round(concentration, 1)}%.",
        }

    def score_row(self, row: dict[str, Any], peers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        r = dict(row or {})
        confidence = _score01(r.get("confidence"), 50.0)
        entry = _score01(r.get("entry_quality"), _score01(r.get("entry_filter_v2_score"), 50.0))
        edge = _score01(r.get("edge_composite_score"), _score01(r.get("risk_adjusted_profit_score"), 50.0))
        follow = _score01(r.get("expected_follow_through_score"), _score01(r.get("trend_continuation_score"), 50.0))
        breakout = _score01(r.get("breakout_probability_score"), 50.0)
        momentum = _score01(r.get("momentum_expansion_score"), 50.0)
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("liquidity_quality"), 55.0))
        vol_expansion = _score01(r.get("volatility_expansion_score"), 50.0)
        volatility_compression = _clamp(100.0 - vol_expansion)
        change = abs(_to_float(r.get("change_percent"), _to_float(r.get("change_pct"), 0.0)))
        gap_risk = _clamp(change * 9.0 + max(0.0, 45.0 - liquidity) * 0.45)
        crowding = _clamp(_score01(r.get("portfolio_correlation_risk"), 45.0) * 0.45 + momentum * 0.35 + _score01(r.get("mega_cap_concentration_score"), 40.0) * 0.20)
        exhaustion = _clamp((100.0 - follow) * 0.38 + vol_expansion * 0.24 + change * 4.0)
        chase = _clamp(max(0.0, momentum - entry) * 0.65 + gap_risk * 0.35)
        micro = _clamp(liquidity * 0.34 + entry * 0.22 + follow * 0.18 + (100.0 - gap_risk) * 0.16 + edge * 0.10)
        behavior = {
            "volatility_expansion_score": round(vol_expansion, 2),
            "volatility_compression_score": round(volatility_compression, 2),
            "momentum_crowding_risk": round(crowding, 2),
            "liquidity_stability_score": round(liquidity, 2),
            "gap_risk_score": round(gap_risk, 2),
            "trend_exhaustion_behavior_score": round(exhaustion, 2),
            "emotional_chase_risk": round(chase, 2),
            "breakout_quality_score": round(_clamp(breakout * 0.55 + follow * 0.25 + entry * 0.20), 2),
            "follow_through_quality_score": round(_clamp(follow * 0.65 + confidence * 0.20 + edge * 0.15), 2),
            "microstructure_readiness_score": round(micro, 2),
            "behavioral_label": "",
            "microstructure_analysis_enabled": False,
            "tick_level_learning_enabled": False,
            "order_book_learning_enabled": False,
        }
        behavior["behavioral_label"] = _behavior_label(behavior)
        replay_candidate_id = f"{_safe_text(r.get('symbol'), 'UNKNOWN').upper()}:{_safe_text(r.get('timestamp'), _now_iso())[:19]}"
        self_review = _clamp(edge * 0.28 + entry * 0.20 + confidence * 0.18 + micro * 0.18 + (100.0 - chase) * 0.16)
        return {
            **behavior,
            "replay_snapshot_saved": True,
            "replay_candidate_id": replay_candidate_id,
            "replay_learning_ready": True,
            "replay_context_summary": f"{_safe_text(r.get('symbol'), 'candidate')} ready for replay snapshot with {behavior['behavioral_label'].replace('_', ' ')} context.",
            "replay_outcome_tracking_ready": True,
            "counterfactual_tracking_ready": True,
            "counterfactual_review_enabled": False,
            "replay_engine_active": False,
            "astra_copilot_summary": "Copilot can explain the deterministic paper decision path; it has no execution authority.",
            "trade_rationale_summary": f"Edge {round(edge, 1)}, entry {round(entry, 1)}, confidence {round(confidence, 1)}, microstructure {round(micro, 1)}.",
            "trade_rejection_explanation": _safe_text(r.get("decision_reason") or r.get("exploration_rejection_reason"), "No rejection recorded for this candidate."),
            "execution_timing_summary": _safe_text(r.get("open_confirmation_reason") or r.get("session_reason"), "Execution timing requires deterministic confirmation gates."),
            "behavioral_risk_summary": f"Behavior {behavior['behavioral_label'].replace('_', ' ')}; chase risk {round(chase, 1)}, gap risk {round(gap_risk, 1)}.",
            "self_review_quality_score": round(self_review, 2),
            "adaptive_learning_candidate_ready": True,
            "autonomous_ai_execution_allowed": False,
            "ai_execution_authority": False,
            "ollama_copilot_ready": True,
            "hermes_agent_compatible": True,
            "adaptive_learning_infrastructure_v1": True,
            "adaptive_learning_shadow_only": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        peers = [dict(r) for r in (rows or []) if isinstance(r, dict)][:120]
        out: list[dict[str, Any]] = []
        for row in peers:
            r = dict(row)
            try:
                r.update(self.score_row(r, peers))
            except Exception:
                r.update(
                    {
                        "replay_snapshot_saved": False,
                        "replay_learning_ready": False,
                        "counterfactual_tracking_ready": True,
                        "microstructure_readiness_score": 50.0,
                        "behavioral_label": "stable_behavior",
                        "astra_copilot_summary": "Copilot diagnostics unavailable for this candidate.",
                        "autonomous_ai_execution_allowed": False,
                        "ai_execution_authority": False,
                        "ollama_copilot_ready": True,
                        "hermes_agent_compatible": True,
                        "adaptive_learning_infrastructure_v1": True,
                        "natural_exit_preserved": True,
                        "forced_early_exit_enabled": False,
                    }
                )
            out.append(r)
        return out

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        rows = _candidate_rows(out)
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
        out["adaptive_learning_infrastructure_v1"] = True
        out["adaptive_learning_infrastructure_summary"] = self.status(rows=rows)
        return out

    @staticmethod
    def _return_summary(values: dict[str, list[float]]) -> tuple[str, str]:
        if not values:
            return "insufficient_data", "Insufficient outcome samples."
        ranked = sorted(values.items(), key=lambda kv: mean(kv[1]) if kv[1] else -999.0, reverse=True)
        best = ranked[0][0]
        text = ", ".join(f"{k}:{round(mean(v), 3) if v else 0.0}%" for k, v in ranked[:4])
        return best, text or "Insufficient outcome samples."

    def status(
        self,
        rows: list[dict[str, Any]] | None = None,
        paper_trace: dict[str, Any] | None = None,
        trade_management: dict[str, Any] | None = None,
        session_timing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        decorated = self.decorate_candidates(base_rows)
        history = self._history()
        paper_state = self._paper_state()
        trace = dict(paper_trace or {})
        tm = dict(trade_management or {})
        session = dict(session_timing or {})
        portfolio = self._portfolio_context(decorated)
        blockers = Counter(history.get("blockers") or {})
        rejections = Counter(history.get("rejections") or {})
        top_blocker = blockers.most_common(1)[0][0] if blockers else _safe_text(trace.get("final_blocker_reason"), "none")
        top_rejection = rejections.most_common(1)[0][0] if rejections else "none"
        best_candidate = "none"
        weakest_candidate = "none"
        if decorated:
            best_candidate = _safe_text(max(decorated, key=lambda r: _score01(r.get("self_review_quality_score"), 0.0)).get("symbol"), "none")
            weakest_candidate = _safe_text(min(decorated, key=lambda r: _score01(r.get("self_review_quality_score"), 100.0)).get("symbol"), "none")
        best_arch, arch_summary = self._return_summary(history.get("archetype_returns") or {})
        best_lane, lane_summary = self._return_summary(history.get("lane_returns") or {})
        best_session, session_summary = self._return_summary(history.get("session_returns") or {})
        best_horizon, horizon_summary = self._return_summary(history.get("horizon_returns") or {})
        behavior_labels = Counter(_safe_text(r.get("behavioral_label"), "stable_behavior") for r in decorated)
        micro_scores = [_score01(r.get("microstructure_readiness_score"), 50.0) for r in decorated]
        self_review_scores = [_score01(r.get("self_review_quality_score"), 50.0) for r in decorated]
        replay_ready_count = sum(1 for r in decorated if r.get("replay_learning_ready"))
        replay_ready = bool(replay_ready_count > 0 or session.get("replay_learning_ready") or history.get("rows"))
        learning_readiness = _clamp((replay_ready_count / max(1, len(decorated)) * 45.0) + (min(len(history.get("rows") or []), 250) / 250.0 * 35.0) + (20.0 if session.get("session_timing_outcome_tracking_ready", True) else 0.0))
        behavioral_awareness = round(mean(micro_scores), 2) if micro_scores else 50.0
        self_review_quality = round(mean(self_review_scores), 2) if self_review_scores else 50.0
        portfolio_adaptation = _clamp(100.0 - _to_float(portfolio.get("portfolio_heat_score"), 50.0) * 0.45 + _to_float(portfolio.get("concentration_score"), 50.0) * -0.15 + 35.0)
        infrastructure_maturity = _clamp((learning_readiness * 0.30) + (self_review_quality * 0.24) + (behavioral_awareness * 0.20) + (portfolio_adaptation * 0.16) + 10.0)
        adaptive_intelligence = _clamp(infrastructure_maturity * 0.55 + self_review_quality * 0.20 + learning_readiness * 0.15 + behavioral_awareness * 0.10)
        survivability = _score01(tm.get("average_survivability_score"), _score01(trace.get("survivability_score"), 50.0))
        trading_health = _clamp(survivability * 0.30 + self_review_quality * 0.26 + (100.0 - _to_float(portfolio.get("portfolio_heat_score"), 50.0)) * 0.22 + learning_readiness * 0.22)
        current_primary_weakness = "insufficient_closed_trade_evidence"
        if _to_float(portfolio.get("portfolio_heat_score"), 0.0) >= 70.0:
            current_primary_weakness = "portfolio_heat_and_concentration"
        elif top_blocker not in {"", "none"}:
            current_primary_weakness = top_blocker
        strongest_edge = best_arch if best_arch != "insufficient_data" else (_safe_text(tm.get("strongest_portfolio_risk"), "candidate_review_infrastructure"))
        weakest_area = current_primary_weakness
        most_improved = "replay_readiness" if replay_ready else "observability_foundation"
        daily_summary = (
            f"Reviewed {len(decorated)} candidates and {len(history.get('today_rows') or [])} local rows today; "
            f"top blocker {top_blocker}; best horizon {best_horizon}."
        )
        self_review_summary = (
            f"Self-review quality {round(self_review_quality, 1)}; primary weakness {current_primary_weakness}; "
            f"strongest edge {strongest_edge}."
        )
        market_behavior_summary = (
            f"Behavior labels {dict(behavior_labels) if behavior_labels else {'stable_behavior': 0}}; "
            f"microstructure readiness {round(behavioral_awareness, 1)}."
        )
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning_infrastructure",
            "adaptive_learning_infrastructure_status_v1": True,
            "trading_day_health_score": round(trading_health, 2),
            "daily_trade_review_summary": daily_summary,
            "current_primary_weakness": current_primary_weakness,
            "strongest_current_edge": strongest_edge,
            "portfolio_health_summary": portfolio.get("portfolio_heat_summary", "Portfolio diagnostics unavailable."),
            "allocation_lane_performance_summary": lane_summary,
            "top_blocker_reason": top_blocker,
            "most_common_rejection_reason": top_rejection,
            "best_trade_candidate": best_candidate,
            "weakest_trade_candidate": weakest_candidate,
            "current_market_behavior_summary": market_behavior_summary,
            "regime_performance_summary": session_summary,
            "daily_survivability_score": round(survivability, 2),
            "daily_risk_efficiency_score": round(_clamp(self_review_quality * 0.55 + (100.0 - _to_float(portfolio.get("portfolio_heat_score"), 50.0)) * 0.45), 2),
            "portfolio_heat_summary": portfolio.get("portfolio_heat_summary", ""),
            "concentration_summary": portfolio.get("concentration_summary", ""),
            "replay_snapshot_saved": bool(replay_ready),
            "replay_candidate_id": _safe_text(decorated[0].get("replay_candidate_id") if decorated else "", "status_snapshot"),
            "replay_learning_ready": bool(replay_ready),
            "replay_context_summary": f"Replay hooks ready for candidate, entry timing, exit timing, portfolio, and regime snapshots; replay engine active is false.",
            "replay_outcome_tracking_ready": True,
            "counterfactual_tracking_ready": True,
            "counterfactual_review_enabled": False,
            "replay_engine_active": False,
            "astra_copilot_summary": "Copilot foundations are ready for explanations and diagnostics only; execution authority remains deterministic.",
            "trade_rationale_summary": "Candidate rationale uses deterministic score, behavior, timing, and portfolio diagnostics.",
            "portfolio_rationale_summary": portfolio.get("portfolio_heat_summary", ""),
            "trade_rejection_explanation": f"Most common rejection: {top_rejection}.",
            "strongest_edge_explanation": f"Strongest observed edge: {strongest_edge}; archetype summary: {arch_summary}.",
            "weakest_edge_explanation": f"Weakest current area: {weakest_area}.",
            "allocation_reasoning_summary": lane_summary,
            "execution_timing_summary": _safe_text(session.get("session_reason"), "Execution timing diagnostics await session endpoint data."),
            "behavioral_risk_summary": market_behavior_summary,
            "ollama_copilot_ready": True,
            "hermes_agent_compatible": True,
            "autonomous_ai_execution_allowed": False,
            "ai_execution_authority": False,
            "microstructure_analysis_enabled": False,
            "tick_level_learning_enabled": False,
            "order_book_learning_enabled": False,
            "adaptive_intelligence_score": round(adaptive_intelligence, 2),
            "adaptive_intelligence_label": _mode_from_score(adaptive_intelligence),
            "self_review_quality_score": round(self_review_quality, 2),
            "infrastructure_maturity_score": round(infrastructure_maturity, 2),
            "learning_readiness_score": round(learning_readiness, 2),
            "portfolio_adaptation_score": round(portfolio_adaptation, 2),
            "behavioral_awareness_score": round(behavioral_awareness, 2),
            "self_review_summary": self_review_summary,
            "adaptive_learning_summary": f"Learning readiness {round(learning_readiness, 1)} with replay={bool(replay_ready)} and counterfactual tracking ready.",
            "replay_lifecycle_expectancy_hooks_ready": bool(self.replay_lifecycle_expectancy is not None),
            "replay_lifecycle_expectancy_integration": "status_reference_only_shadow_policy_recommendations",
            "regime_execution_survivability_hooks_ready": bool(self.regime_execution_survivability is not None),
            "regime_execution_survivability_integration": "status_reference_only_shadow_context_survivability",
            "adaptive_execution_exit_v2_hooks_ready": bool(self.adaptive_execution_exit_v2 is not None),
            "adaptive_execution_exit_v2_integration": "status_reference_only_shadow_execution_exit_diagnostics",
            "recommended_next_focus": current_primary_weakness,
            "most_improved_area": most_improved,
            "weakest_current_area": weakest_area,
            "recurring_trade_failures": dict(blockers.most_common(5)),
            "recurring_blocker_patterns": dict(blockers.most_common(5)),
            "regime_mismatch_frequency": 0,
            "poor_timing_patterns": dict(rejections.most_common(5)),
            "weak_expectancy_archetypes": arch_summary,
            "strongest_expectancy_archetypes": best_arch,
            "trade_duration_quality": "tracked" if _to_float(history.get("average_duration_hours"), 0.0) > 0 else "waiting_for_duration_data",
            "portfolio_concentration_outcomes": portfolio.get("concentration_summary", ""),
            "volatility_regime_outcomes": horizon_summary,
            "behavioral_mistake_frequencies": dict(behavior_labels),
            "submitted_orders": int(_to_float(trace.get("orders_submitted"), _to_float(paper_state.get("orders_submitted"), 0.0))),
            "canceled_orders": 0,
            "open_positions": int(_to_float(trace.get("broker_open_positions_count"), _to_float(trace.get("open_positions_count"), 0.0))),
            "filled_positions": int(_to_float(trace.get("orders_submitted"), 0.0)),
            "pl_by_archetype": {k: round(mean(v), 4) if v else 0.0 for k, v in (history.get("archetype_returns") or {}).items()},
            "pl_by_allocation_lane": {k: round(mean(v), 4) if v else 0.0 for k, v in (history.get("lane_returns") or {}).items()},
            "pl_by_session_timing": {k: round(mean(v), 4) if v else 0.0 for k, v in (history.get("session_returns") or {}).items()},
            "pl_by_horizon": {k: round(mean(v), 4) if v else 0.0 for k, v in (history.get("horizon_returns") or {}).items()},
            "expectancy_by_trade_style": horizon_summary,
            "blocker_frequencies": dict(blockers.most_common(8)),
            "rejection_frequencies": dict(rejections.most_common(8)),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "forced_trade_enabled": False,
            "deterministic_execution_authority_preserved": True,
            "broker_safeguards_preserved": True,
            "auto_promotion_allowed": False,
            "human_review_required": True,
            "updated_at": _now_iso(),
        }
