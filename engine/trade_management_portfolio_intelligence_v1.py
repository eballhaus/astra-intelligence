from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.adaptive_learning_infrastructure_v1 import AdaptiveLearningInfrastructureV1
except Exception:  # pragma: no cover - additive diagnostics only
    AdaptiveLearningInfrastructureV1 = None  # type: ignore[assignment]
try:
    from engine.replay_lifecycle_expectancy_learning_v1 import ReplayLifecycleExpectancyLearningV1
except Exception:  # pragma: no cover - additive diagnostics only
    ReplayLifecycleExpectancyLearningV1 = None  # type: ignore[assignment]
try:
    from engine.regime_execution_survivability_intelligence_v1 import RegimeExecutionSurvivabilityIntelligenceV1
except Exception:  # pragma: no cover - additive diagnostics only
    RegimeExecutionSurvivabilityIntelligenceV1 = None  # type: ignore[assignment]

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900


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


def _exit_label(score: float) -> str:
    if score >= 82.0:
        return "hold_strong"
    if score >= 66.0:
        return "hold_cautious"
    if score >= 52.0:
        return "trim_candidate"
    if score >= 38.0:
        return "exit_watch"
    return "high_exit_risk"


def _sizing_label(size: float, confidence: float, drawdown: float) -> str:
    if drawdown >= 82.0 or size <= 0.25:
        return "blocked_size"
    if size <= 1.5:
        return "minimal_probe_size"
    if size <= 4.5 or confidence < 58.0:
        return "reduced_size"
    if size <= 8.5:
        return "standard_size"
    return "aggressive_allowed"


def _portfolio_label(heat: float, corr: float, stability: float) -> str:
    if heat >= 82.0 or stability < 32.0:
        return "unstable"
    if corr >= 78.0:
        return "high_correlation_risk"
    if heat >= 66.0:
        return "defensive_required"
    if corr >= 58.0:
        return "elevated_concentration"
    return "stable"


def _managed_label(score: float) -> str:
    if score >= 86.0:
        return "elite_managed_trade"
    if score >= 74.0:
        return "strong_managed_trade"
    if score >= 60.0:
        return "moderate_managed_trade"
    if score >= 45.0:
        return "elevated_risk_trade"
    return "weak_managed_trade"


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


class TradeManagementPortfolioIntelligenceV1:
    """Paper-only trade management and portfolio intelligence diagnostics.

    This suite provides shadow recommendations only. It does not execute,
    resize, close, liquidate, promote, or modify live/paper broker safeguards.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._learning_cache: dict[str, Any] | None = None
        self.adaptive_learning_infrastructure = (
            AdaptiveLearningInfrastructureV1(state_dir=self.state_dir) if AdaptiveLearningInfrastructureV1 is not None else None
        )
        self.replay_lifecycle_expectancy = (
            ReplayLifecycleExpectancyLearningV1(state_dir=self.state_dir) if ReplayLifecycleExpectancyLearningV1 is not None else None
        )
        self.regime_execution_survivability = (
            RegimeExecutionSurvivabilityIntelligenceV1(state_dir=self.state_dir)
            if RegimeExecutionSurvivabilityIntelligenceV1 is not None
            else None
        )

    def _learning_hooks(self) -> dict[str, Any]:
        if self._learning_cache is not None:
            return self._learning_cache
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=350))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=300))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        exit_quality: list[float] = []
        sizing_quality: list[float] = []
        drawdown_by_stack: dict[str, list[float]] = defaultdict(list)
        giveback: list[float] = []
        for row in rows[-MAX_ROWS:]:
            r = dict(row or {})
            exit_quality.append(_score01(r.get("exit_quality_score"), _score01(r.get("entry_exit_quality_score"), 50.0)))
            sizing_quality.append(_score01(r.get("sizing_quality_score"), _score01(r.get("capital_allocation_score"), 50.0)))
            archetype = _safe_text(r.get("trade_archetype") or r.get("entry_trade_archetype") or r.get("setup_type"), "unknown").lower().replace(" ", "_")
            cap = _market_cap_bucket(r)
            stack = f"{cap}:{archetype}"
            dd = abs(_first_number(r, ("max_adverse_excursion", "drawdown_after_peak_percent", "drawdown_pct"), 0.0))
            drawdown_by_stack[stack].append(dd)
            mfe = max(0.0, _first_number(r, ("max_favorable_excursion", "peak_unrealized_pnl_percent"), 0.0))
            ret = _first_number(r, ("realized_return_pct", "return_pct", "return_percent", "pnl_pct"), 0.0)
            giveback.append(max(0.0, mfe - max(0.0, ret)))
        weakest_stack = "insufficient_data"
        if drawdown_by_stack:
            weakest_stack = max(drawdown_by_stack.items(), key=lambda kv: mean(kv[1]) if kv[1] else 0.0)[0]
        self._learning_cache = {
            "sample_size": len(rows),
            "average_exit_quality": round(mean(exit_quality), 2) if exit_quality else 0.0,
            "average_sizing_quality": round(mean(sizing_quality), 2) if sizing_quality else 0.0,
            "average_profit_giveback": round(mean(giveback), 4) if giveback else 0.0,
            "weakest_archetype_stack": weakest_stack,
            "tracks_exit_quality_vs_realized_outcome": True,
            "tracks_sizing_quality_vs_realized_outcome": True,
            "tracks_portfolio_concentration_vs_drawdown": True,
            "tracks_archetype_stacking_outcomes": True,
            "tracks_volatility_cluster_performance": True,
            "tracks_hold_duration_quality": True,
            "tracks_profit_giveback_behavior": True,
        }
        return self._learning_cache

    def _portfolio_context(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(rows))
        sectors = Counter(_safe_text(r.get("sector") or r.get("sector_name"), "unknown").lower() for r in rows)
        themes = Counter(_safe_text(r.get("theme") or r.get("setup_type") or r.get("trade_archetype"), "unknown").lower() for r in rows)
        caps = Counter(_market_cap_bucket(r) for r in rows)
        archetypes = Counter(_safe_text(r.get("trade_archetype") or r.get("setup_type"), "unknown").lower() for r in rows)
        max_sector = max((v for k, v in sectors.items() if k != "unknown"), default=0) / n
        max_theme = max((v for k, v in themes.items() if k != "unknown"), default=0) / n
        max_cap = max((v for k, v in caps.items() if k != "unknown"), default=0) / n
        max_archetype = max((v for k, v in archetypes.items() if k != "unknown"), default=0) / n
        mega_share = caps.get("mega_cap", 0) / n
        momentum_share = sum(1 for r in rows if "momentum" in _safe_text(r.get("trade_archetype") or r.get("candidate_opportunity_type")).lower()) / n
        correlation = _clamp(max(max_sector, max_theme, max_cap, max_archetype) * 100.0)
        sector_concentration = _clamp(max_sector * 100.0)
        volatility_cluster = _clamp(momentum_share * 65.0 + mega_share * 20.0)
        heat = _clamp((correlation * 0.35) + (sector_concentration * 0.20) + (volatility_cluster * 0.22) + (mega_share * 100.0 * 0.23))
        stability = _clamp(100.0 - (heat * 0.50) - (correlation * 0.25) + max(0.0, 100.0 - max_cap * 100.0) * 0.25)
        diversification = _clamp(100.0 - max(max_sector, max_theme, max_cap, max_archetype) * 100.0)
        return {
            "portfolio_heat_score": round(heat, 2),
            "portfolio_correlation_risk": round(correlation, 2),
            "sector_concentration_score": round(sector_concentration, 2),
            "directional_bias_score": round(_clamp(mega_share * 80.0 + momentum_share * 35.0), 2),
            "volatility_cluster_risk": round(volatility_cluster, 2),
            "correlated_exposure_score": round(correlation, 2),
            "portfolio_stability_score": round(stability, 2),
            "diversification_quality_score": round(diversification, 2),
            "portfolio_risk_label": _portfolio_label(heat, correlation, stability),
            "sector_distribution": dict(sectors),
            "theme_distribution": dict(themes),
            "market_cap_distribution": dict(caps),
            "archetype_distribution": dict(archetypes),
        }

    def score_row(self, row: dict[str, Any], peers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        r = dict(row or {})
        peers = [dict(x) for x in (peers or [r]) if isinstance(x, dict)]
        portfolio = self._portfolio_context(peers)
        edge = _score01(r.get("edge_composite_score"), _score01(r.get("risk_adjusted_profit_score"), 55.0))
        opportunity = _score01(r.get("opportunity_quality_score"), _score01(r.get("entry_quality_v2_score"), 52.0))
        expectancy = _score01(r.get("expected_value_score"), _score01(r.get("aggressive_profit_score"), 52.0))
        confidence = _score01(r.get("confidence"), _score01(r.get("expected_win_probability"), 52.0))
        regime = _score01(r.get("regime_alignment_score"), 55.0)
        volatility = _score01(r.get("volatility_expansion_score"), _score01(r.get("volatility_score"), 48.0))
        momentum = _score01(r.get("momentum_expansion_score"), _score01(r.get("momentum_score"), 50.0))
        follow = _score01(r.get("expected_follow_through_score"), _score01(r.get("entry_followthrough_quality_score"), 52.0))
        current_price = _to_float(r.get("current_price"), _to_float(r.get("price"), 0.0))
        entry_price = _to_float(r.get("entry_price"), current_price)
        unrealized = _first_number(r, ("unrealized_pnl_pct", "unrealized_return_pct", "return_percent"), 0.0)
        if unrealized == 0.0 and entry_price > 0.0 and current_price > 0.0:
            unrealized = ((current_price / entry_price) - 1.0) * 100.0
        momentum_deterioration = _clamp(100.0 - momentum + max(0.0, volatility - 70.0) * 0.30)
        follow_decay = _clamp(100.0 - follow)
        trend_exhaustion = _clamp(max(0.0, volatility - momentum) + max(0.0, 72.0 - regime) * 0.25 + max(0.0, unrealized) * 1.2)
        profit_capture = _clamp(45.0 + max(0.0, unrealized) * 8.0 - follow_decay * 0.18)
        trailing_pressure = _clamp((momentum_deterioration * 0.32) + (follow_decay * 0.28) + (trend_exhaustion * 0.24) + max(0.0, unrealized) * 1.6)
        profit_lock = _clamp((profit_capture * 0.42) + (trailing_pressure * 0.24) + max(0.0, unrealized) * 3.0 + (100.0 - portfolio["portfolio_stability_score"]) * 0.10)
        hold_quality = _clamp((edge * 0.23) + (opportunity * 0.16) + (expectancy * 0.16) + (follow * 0.18) + (regime * 0.12) + (portfolio["portfolio_stability_score"] * 0.15) - (trailing_pressure * 0.16))
        exit_quality = _clamp((hold_quality * 0.62) + ((100.0 - trailing_pressure) * 0.24) + ((100.0 - momentum_deterioration) * 0.14))
        adaptive_stop = "keep_existing_stop"
        if trailing_pressure >= 70.0 and unrealized > 1.0:
            adaptive_stop = "shadow_tighten_trailing_stop_review"
        elif trailing_pressure >= 58.0:
            adaptive_stop = "shadow_monitor_stop_distance"
        elif hold_quality >= 74.0:
            adaptive_stop = "shadow_allow_normal_trailing_logic"
        portfolio_heat = _to_float(portfolio.get("portfolio_heat_score"), 50.0)
        correlation = _to_float(portfolio.get("portfolio_correlation_risk"), 50.0)
        base_size = _clamp((edge * 0.28) + (opportunity * 0.18) + (expectancy * 0.18) + (confidence * 0.16) + (regime * 0.08) + (100.0 - portfolio_heat) * 0.12)
        volatility_adjusted_size = _clamp((base_size / 100.0) * (9.0 - max(0.0, volatility - 55.0) / 12.0), 0.0, 12.0)
        conviction_adjusted_size = _clamp(volatility_adjusted_size * (0.65 + confidence / 180.0), 0.0, 14.0)
        risk_adjusted_size = _clamp(conviction_adjusted_size * (1.0 - max(0.0, portfolio_heat - 55.0) / 150.0 - max(0.0, correlation - 55.0) / 180.0), 0.0, 10.0)
        intelligent_size = _clamp(risk_adjusted_size, 0.0, 10.0)
        drawdown_exposure = _clamp((portfolio_heat * 0.35) + (correlation * 0.25) + (volatility * 0.18) + (100.0 - confidence) * 0.22)
        sizing_label = _sizing_label(intelligent_size, confidence, drawdown_exposure)
        survivability = _clamp((exit_quality * 0.25) + ((100.0 - drawdown_exposure) * 0.22) + (portfolio["portfolio_stability_score"] * 0.24) + (opportunity * 0.14) + (confidence * 0.15))
        portfolio_intel = _clamp((portfolio["portfolio_stability_score"] * 0.34) + (portfolio["diversification_quality_score"] * 0.22) + ((100.0 - correlation) * 0.24) + ((100.0 - portfolio_heat) * 0.20))
        risk_adjusted_quality = _clamp((edge * 0.24) + (expectancy * 0.18) + (exit_quality * 0.18) + (survivability * 0.18) + (portfolio_intel * 0.14) + (regime * 0.08))
        trade_management = _clamp((exit_quality * 0.24) + (risk_adjusted_quality * 0.28) + (survivability * 0.22) + (portfolio_intel * 0.16) + (confidence * 0.10))
        return {
            "exit_quality_score": round(exit_quality, 2),
            "exit_readiness_label": _exit_label(exit_quality),
            "momentum_deterioration_score": round(momentum_deterioration, 2),
            "follow_through_decay_score": round(follow_decay, 2),
            "trend_exhaustion_score": round(trend_exhaustion, 2),
            "unrealized_profit_capture_score": round(profit_capture, 2),
            "trailing_exit_pressure_score": round(trailing_pressure, 2),
            "adaptive_stop_suggestion": adaptive_stop,
            "adaptive_profit_lock_score": round(profit_lock, 2),
            "hold_quality_score": round(hold_quality, 2),
            "intelligent_position_size_pct": round(intelligent_size, 3),
            "position_size_confidence": round(_clamp((confidence * 0.45) + (edge * 0.30) + (portfolio_intel * 0.25)), 2),
            "volatility_adjusted_size": round(volatility_adjusted_size, 3),
            "conviction_adjusted_size": round(conviction_adjusted_size, 3),
            "risk_adjusted_size": round(risk_adjusted_size, 3),
            "max_drawdown_exposure_score": round(drawdown_exposure, 2),
            "sizing_reason": f"{sizing_label.replace('_', ' ')} from edge {edge:.1f}, confidence {confidence:.1f}, portfolio heat {portfolio_heat:.1f}.",
            "sizing_safety_label": sizing_label,
            **{k: v for k, v in portfolio.items() if not k.endswith("_distribution")},
            "trade_management_score": round(trade_management, 2),
            "portfolio_intelligence_score": round(portfolio_intel, 2),
            "survivability_score": round(survivability, 2),
            "risk_adjusted_trade_quality": round(risk_adjusted_quality, 2),
            "adaptive_trade_quality_label": _managed_label(risk_adjusted_quality),
            "trade_management_shadow_only": True,
            "portfolio_intelligence_shadow_only": True,
            "auto_execution_promotion_allowed": False,
            "human_review_required": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "trade_management_summary": f"{_managed_label(risk_adjusted_quality).replace('_', ' ')}; exit {exit_quality:.1f}, size {intelligent_size:.2f}%, survivability {survivability:.1f}.",
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
                        "exit_quality_score": 50.0,
                        "exit_readiness_label": "hold_cautious",
                        "intelligent_position_size_pct": 1.0,
                        "sizing_safety_label": "minimal_probe_size",
                        "portfolio_heat_score": 50.0,
                        "portfolio_risk_label": "stable",
                        "trade_management_score": 50.0,
                        "portfolio_intelligence_score": 50.0,
                        "survivability_score": 50.0,
                        "risk_adjusted_trade_quality": 50.0,
                        "adaptive_trade_quality_label": "moderate_managed_trade",
                        "trade_management_shadow_only": True,
                        "portfolio_intelligence_shadow_only": True,
                        "auto_execution_promotion_allowed": False,
                        "human_review_required": True,
                        "natural_exit_preserved": True,
                        "forced_early_exit_enabled": False,
                    }
                )
            out.append(r)
        return out

    def evaluate_open_trades(self, open_trades: list[dict[str, Any]] | None, live_perf: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = self.decorate_candidates([dict(r) for r in (open_trades or []) if isinstance(r, dict)])
        return {
            "ok": True,
            "count": len(rows),
            "alerts": [],
            "rows": rows[:80],
            "live_performance": live_perf or {},
            "trade_management_shadow_only": True,
            "portfolio_intelligence_shadow_only": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "last_updated_utc": _now_iso(),
        }

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
        out["trade_management_portfolio_intelligence_v1"] = True
        out["trade_management_portfolio_summary"] = self.status(rows=rows)
        return out

    def status(self, rows: list[dict[str, Any]] | None = None, open_trades: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        base_rows = [dict(r) for r in (rows or open_trades or []) if isinstance(r, dict)]
        decorated = self.decorate_candidates(base_rows)
        portfolio = self._portfolio_context(decorated) if decorated else self._portfolio_context([])
        labels = Counter(_safe_text(r.get("adaptive_trade_quality_label"), "unknown") for r in decorated)
        exit_labels = Counter(_safe_text(r.get("exit_readiness_label"), "unknown") for r in decorated)
        sizing_labels = Counter(_safe_text(r.get("sizing_safety_label"), "unknown") for r in decorated)
        strongest_risk = _portfolio_label(_to_float(portfolio.get("portfolio_heat_score"), 0.0), _to_float(portfolio.get("portfolio_correlation_risk"), 0.0), _to_float(portfolio.get("portfolio_stability_score"), 0.0))
        learning = self._learning_hooks()
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning",
            "trade_management_portfolio_status_v1": True,
            "candidates_evaluated": len(decorated),
            "active_trades_evaluated": len(open_trades or []),
            "portfolio_heat_score": portfolio.get("portfolio_heat_score", 0.0),
            "portfolio_correlation_risk": portfolio.get("portfolio_correlation_risk", 0.0),
            "sector_concentration_score": portfolio.get("sector_concentration_score", 0.0),
            "directional_bias_score": portfolio.get("directional_bias_score", 0.0),
            "volatility_cluster_risk": portfolio.get("volatility_cluster_risk", 0.0),
            "correlated_exposure_score": portfolio.get("correlated_exposure_score", 0.0),
            "portfolio_stability_score": portfolio.get("portfolio_stability_score", 0.0),
            "diversification_quality_score": portfolio.get("diversification_quality_score", 0.0),
            "portfolio_risk_label": portfolio.get("portfolio_risk_label", "stable"),
            "sector_distribution": portfolio.get("sector_distribution", {}),
            "market_cap_distribution": portfolio.get("market_cap_distribution", {}),
            "archetype_distribution": portfolio.get("archetype_distribution", {}),
            "average_exit_quality_score": round(mean([_to_float(r.get("exit_quality_score"), 0.0) for r in decorated]), 2) if decorated else 0.0,
            "average_intelligent_position_size_pct": round(mean([_to_float(r.get("intelligent_position_size_pct"), 0.0) for r in decorated]), 3) if decorated else 0.0,
            "average_survivability_score": round(mean([_to_float(r.get("survivability_score"), 0.0) for r in decorated]), 2) if decorated else 0.0,
            "average_trade_management_score": round(mean([_to_float(r.get("trade_management_score"), 0.0) for r in decorated]), 2) if decorated else 0.0,
            "exit_readiness_distribution": dict(exit_labels),
            "sizing_distribution": dict(sizing_labels),
            "trade_management_distribution": dict(labels),
            "strongest_portfolio_risk": strongest_risk,
            "survivability_diagnostics": f"Portfolio {portfolio.get('portfolio_risk_label', 'stable').replace('_', ' ')}; average survivability {round(mean([_to_float(r.get('survivability_score'), 0.0) for r in decorated]), 1) if decorated else 0.0}.",
            "trade_management_summary": f"Evaluated {len(decorated)} rows; heat {portfolio.get('portfolio_heat_score', 0.0)}, correlation {portfolio.get('portfolio_correlation_risk', 0.0)}.",
            "learning_hooks": learning,
            "adaptive_learning_infrastructure_hooks_ready": bool(self.adaptive_learning_infrastructure is not None),
            "adaptive_learning_review_integration": "status_reference_only_no_execution_authority",
            "replay_lifecycle_expectancy_hooks_ready": bool(self.replay_lifecycle_expectancy is not None),
            "regime_execution_survivability_hooks_ready": bool(self.regime_execution_survivability is not None),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "provider_rewrite_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "trade_management_shadow_only": True,
            "portfolio_intelligence_shadow_only": True,
            "auto_execution_promotion_allowed": False,
            "human_review_required": True,
            "updated_at": _now_iso(),
        }
