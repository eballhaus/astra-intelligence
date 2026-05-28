from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 12.0
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900
CHART_POINTS = 80


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        if not math.isfinite(out):
            return float(default)
        return out
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _score(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _text(value: Any, default: str = "") -> str:
    s = str(value if value is not None else default).strip()
    return s or str(default)


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            if value is None or value == "":
                continue
            out = float(value)
            if math.isfinite(out):
                return out
        except Exception:
            continue
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


def _timestamp(row: dict[str, Any], index: int) -> str:
    for key in ("closed_at", "exit_timestamp", "exit_time", "updated_at", "timestamp", "ts", "created_at", "entry_timestamp"):
        value = row.get(key)
        if value:
            return _text(value)[:32]
    return f"sample_{index + 1}"


def _return_pct(row: dict[str, Any]) -> float:
    return _first_float(
        row.get("realized_return_pct"),
        row.get("return_pct"),
        row.get("return_percent"),
        row.get("pnl_pct"),
        row.get("profit_pct"),
        default=0.0,
    )


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
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
        symbol = _text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


def _metric(value: Any, *, label: str | None = None, evidence_count: int = 0, maturity: str | None = None, explanation: str = "") -> dict[str, Any]:
    has_value = value is not None and value != ""
    numeric = None
    if has_value:
        try:
            numeric = float(value)
            if not math.isfinite(numeric):
                numeric = None
        except Exception:
            numeric = None
    mature = maturity or ("healthy" if evidence_count > 0 and numeric is not None else "insufficient_evidence")
    if numeric is None and mature in {"healthy", "degraded"}:
        mature = "insufficient_evidence"
    return {
        "value": round(numeric, 4) if numeric is not None else None,
        "label": label or mature,
        "evidence_count": int(max(0, evidence_count)),
        "maturity": mature,
        "explanation": explanation or _maturity_explanation(mature),
    }


def _maturity_explanation(maturity: str) -> str:
    mapping = {
        "warming_up": "Astra is collecting enough observations for this metric.",
        "insufficient_closed_trades": "Waiting for enough naturally closed paper trades.",
        "awaiting_replay_data": "Waiting for enough replay-reviewed trades.",
        "awaiting_lifecycle_outcomes": "Waiting for complete lifecycle outcomes.",
        "insufficient_evidence": "Not enough evidence for a truthful numeric claim yet.",
        "stale_last_known_good": "Using last-known-good data while fresh diagnostics rebuild.",
        "healthy": "Evidence is sufficient and the metric is current.",
        "degraded": "Metric is available but source quality is degraded.",
    }
    return mapping.get(str(maturity), "Metric is being monitored.")


def _profit_factor(returns: list[float]) -> float | None:
    wins = [v for v in returns if v > 0]
    losses = [abs(v) for v in returns if v < 0]
    if not returns or not losses:
        return None if not wins else round(sum(wins), 4)
    return round(sum(wins) / max(1e-9, sum(losses)), 4)


def _rolling(values: list[float], window: int = 20) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1): i + 1]
        out.append(round(mean(chunk), 4) if chunk else 0.0)
    return out


class UnifiedLearningDiagnosticsV1:
    """Fast, cached, maturity-aware Learning tab control-tower snapshot."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def build(self, sources: dict[str, Any] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        sources = dict(sources or {})
        failed_sources: list[str] = []
        try:
            payload = self._build_uncached(sources, failed_sources)
        except Exception as exc:
            if self._cache:
                payload = dict(self._cache)
                payload["stale_cache"] = True
                payload["degraded_reason"] = f"unified_rebuild_failed_last_known_good_used: {str(exc)[:140]}"
            else:
                payload = self._fallback(str(exc))
        payload["cache_hit"] = False
        payload["cache_age_seconds"] = 0.0
        payload["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        payload["api_calls_used"] = 0
        payload["failed_sources"] = failed_sources
        payload["failed_sources_count"] = len(failed_sources)
        self._cache = dict(payload)
        self._cache_ts = now
        return payload

    def _rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for name, limit in (
            ("trade_lifecycle_excursion_v1.jsonl", 360),
            ("trade_lifecycle_v1.jsonl", 320),
            ("outcome_labels_v1.jsonl", 280),
            ("candidate_decision_ledger_v1.jsonl", 220),
            ("paper_trade_journal.jsonl", 180),
        ):
            rows.extend(_tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit))
        return rows[-MAX_ROWS:]

    def _build_uncached(self, sources: dict[str, Any], failed_sources: list[str]) -> dict[str, Any]:
        top_payload = dict(sources.get("top_buys") or {})
        learning_fast = dict(sources.get("learning_snapshot_fast") or {})
        paper = dict(sources.get("paper_performance") or {})
        statuses = {k: v for k, v in dict(sources.get("statuses") or {}).items() if isinstance(v, dict)}
        candidate_rows = _candidate_rows(top_payload)
        history_rows = self._rows()
        closed_rows = [r for r in history_rows if _return_pct(r) != 0 or r.get("closed_at") or r.get("exit_timestamp")]
        returns = [_return_pct(r) for r in closed_rows]
        evidence_count = len(closed_rows)
        maturity = self._evidence_maturity(evidence_count, statuses)
        perf = self._performance_summary(learning_fast, paper, statuses, returns, evidence_count, maturity)
        execution = self._execution_quality_summary(learning_fast, statuses, candidate_rows, evidence_count, maturity)
        portfolio = self._portfolio_health_summary(statuses, candidate_rows, maturity)
        learning = self._learning_maturity_summary(statuses, paper, evidence_count, maturity)
        regime = self._regime_context_summary(statuses, candidate_rows, history_rows, maturity)
        system = self._system_health_summary(sources, statuses, learning_fast)
        executive = self._executive_snapshot(perf, execution, portfolio, learning, regime, system, candidate_rows, evidence_count)
        charts = self._master_charts(history_rows, candidate_rows, statuses)
        advanced = self._advanced_statuses(statuses, sources)
        adaptive_v2 = self._adaptive_execution_exit_summary(statuses.get("adaptive_execution_exit_intelligence_v2") or {})
        diversification_v2 = self._portfolio_diversification_summary(statuses.get("portfolio_diversification_correlation_v2") or {})
        mobile_compaction = self._mobile_runtime_compaction_summary(statuses.get("mobile_runtime_compaction") or {})
        profit_exploration = self._profit_seeking_exploration_summary(statuses.get("profit_seeking_adaptive_exploration") or {})
        market_calendar_knowledge = self._market_calendar_knowledge_summary(statuses.get("market_calendar_knowledge") or {})
        broad_universe = self._broad_universe_intake_summary(statuses.get("broad_universe_intake_promotion") or {})
        trade_lifecycle_excursion = self._trade_lifecycle_excursion_summary(statuses.get("trade_lifecycle_excursion") or {})
        execution_participation_audit = self._execution_participation_audit_summary(statuses.get("execution_participation_audit") or {})
        stale = self._stale_status(sources, system)
        return {
            "ok": True,
            "enabled": True,
            "version": VERSION,
            "mode": "unified_learning_snapshot",
            "generated_at": _now_iso(),
            "executive_snapshot": executive,
            "master_charts": charts,
            "performance_summary": perf,
            "execution_quality_summary": execution,
            "portfolio_health_summary": portfolio,
            "portfolio_diversification_correlation_v2": diversification_v2,
            "mobile_runtime_compaction": mobile_compaction,
            "profit_seeking_adaptive_exploration": profit_exploration,
            "market_calendar_knowledge": market_calendar_knowledge,
            "broad_universe_intake_promotion": broad_universe,
            "trade_lifecycle_excursion": trade_lifecycle_excursion,
            "execution_participation_audit": execution_participation_audit,
            "learning_maturity_summary": learning,
            "regime_context_summary": regime,
            "adaptive_execution_exit_intelligence_v2": adaptive_v2,
            "adaptive_execution_intelligence": adaptive_v2.get("adaptive_execution_intelligence", {}),
            "exit_intelligence_v2": adaptive_v2.get("exit_intelligence_v2", {}),
            "regime_adaptive_trading": adaptive_v2.get("regime_adaptive_trading", {}),
            "lifecycle_adaptation": adaptive_v2.get("lifecycle_adaptation", {}),
            "profitability_improvement_diagnostics": adaptive_v2.get("profitability_improvement_diagnostics", {}),
            "system_health_summary": system,
            "advanced_panel_links": advanced,
            "advanced_panel_statuses": advanced,
            "stale_data_status": stale,
            "evidence_maturity_status": maturity,
            "future_suite_integration_contract": self._integration_contract(),
            "frontend_endpoint_policy": {
                "initial_learning_tab_endpoint_count": 1,
                "initial_endpoint": "/api/unified_learning_diagnostics_v1",
                "advanced_diagnostics_lazy_load": True,
                "legacy_initial_endpoint_storm_removed": True,
            },
            "stale_cache": False,
            "degraded_reason": system.get("degraded_reason") or "",
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "broker_behavior_changed": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _evidence_maturity(self, evidence_count: int, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        replay_ready = bool(replay.get("replay_learning_ready"))
        lifecycle_ready = bool(replay.get("lifecycle_tracking_ready"))
        expectancy_ready = bool(replay.get("expectancy_learning_ready"))
        if evidence_count <= 0:
            label = "insufficient_closed_trades"
        elif evidence_count < 20:
            label = "warming_up"
        elif not replay_ready:
            label = "awaiting_replay_data"
        elif not lifecycle_ready:
            label = "awaiting_lifecycle_outcomes"
        else:
            label = "healthy" if expectancy_ready or evidence_count >= 50 else "warming_up"
        return {
            "label": label,
            "evidence_count": evidence_count,
            "closed_trade_count": evidence_count,
            "replay_ready": replay_ready,
            "lifecycle_ready": lifecycle_ready,
            "expectancy_ready": expectancy_ready,
            "explanation": _maturity_explanation(label),
        }

    def _performance_summary(self, learning_fast: dict[str, Any], paper: dict[str, Any], statuses: dict[str, dict[str, Any]], returns: list[float], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        paper_combined = dict(paper.get("combined") or paper.get("paper_outcome_summary", {}).get("combined") or {})
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        edge = statuses.get("edge_development") or {}
        closed = max(evidence_count, _to_int(paper_combined.get("valid_closed"), 0), _to_int(paper.get("closed_trades_count"), 0))
        metric_maturity = "healthy" if closed >= 20 else ("warming_up" if closed > 0 else "insufficient_closed_trades")
        released_wr = _first_float(learning_fast.get("current_engine_released_wr"), paper_combined.get("win_rate"), paper.get("win_rate"), default=0.0)
        pf = _first_float(replay.get("expectancy_profit_factor"), default=0.0)
        pf_value = pf if pf > 0 else _profit_factor(returns)
        avg_return = _first_float(replay.get("expectancy_avg_return"), paper_combined.get("avg_return"), paper.get("avg_return"), default=0.0)
        expectancy = _first_float(replay.get("expectancy_score"), edge.get("average_expected_value_score"), default=0.0)
        buy_purity = _first_float(learning_fast.get("buy_list_purity"), default=0.0)
        mature = metric_maturity if closed > 0 else maturity.get("label", "insufficient_evidence")
        return {
            "released_win_rate": _metric(released_wr if closed > 0 else None, evidence_count=closed, maturity=mature, explanation="Win rate for released/current-engine paper outcomes."),
            "profit_factor": _metric(pf_value, evidence_count=closed, maturity=mature if pf_value is not None else "insufficient_closed_trades", explanation="Gross winners divided by gross losers where closed outcomes exist."),
            "expectancy_score": _metric(expectancy if closed > 0 or expectancy > 0 else None, evidence_count=closed, maturity=mature, explanation="Outcome-weighted expectancy quality score."),
            "average_return": _metric(avg_return if closed > 0 else None, evidence_count=closed, maturity=mature, explanation="Average realized paper return from available outcomes."),
            "buy_list_purity": _metric(buy_purity if buy_purity > 0 else None, evidence_count=max(closed, 0), maturity="healthy" if buy_purity > 0 else maturity.get("label", "insufficient_evidence"), explanation="Cleanliness of the promoted buy list."),
            "closed_trade_count": closed,
        }

    def _execution_quality_summary(self, learning_fast: dict[str, Any], statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        tm = statuses.get("trade_management_portfolio") or {}
        edge = statuses.get("edge_development") or {}
        mature = "healthy" if evidence_count > 0 or rows else maturity.get("label", "insufficient_evidence")
        entry = _first_float(learning_fast.get("entry_quality"), regime.get("entry_timing_quality"), tm.get("average_entry_quality_shadow"), default=0.0)
        exit_q = _first_float(learning_fast.get("exit_quality"), regime.get("exit_timing_quality"), tm.get("average_exit_quality_score"), default=0.0)
        follow = _first_float(learning_fast.get("follow_through_quality"), regime.get("follow_through_probability"), edge.get("average_expected_follow_through_score"), default=0.0)
        truth = _first_float(edge.get("average_expected_win_probability"), default=0.0)
        return {
            "entry_quality": _metric(entry if entry > 0 else None, evidence_count=evidence_count, maturity=mature, explanation="Entry timing and quality from current learning summaries."),
            "exit_quality": _metric(exit_q if exit_q > 0 else None, evidence_count=evidence_count, maturity=mature, explanation="Exit timing quality without forcing exits."),
            "follow_through_quality": _metric(follow if follow > 0 else None, evidence_count=max(evidence_count, len(rows)), maturity=mature, explanation="Likelihood that entries continue after trigger."),
            "confidence_truthfulness": _metric(truth if truth > 0 else None, evidence_count=evidence_count, maturity=mature if truth > 0 else "insufficient_evidence", explanation="How calibrated confidence appears versus observed outcomes."),
            "execution_quality_score": _metric(_first_float(regime.get("execution_quality_score"), default=0.0) or None, evidence_count=max(evidence_count, len(rows)), maturity=mature),
        }

    def _portfolio_health_summary(self, statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        tm = statuses.get("trade_management_portfolio") or {}
        risk = statuses.get("portfolio_risk_intelligence") or {}
        div = statuses.get("portfolio_diversification_correlation_v2") or {}
        mature = "healthy" if rows else maturity.get("label", "insufficient_evidence")
        survivability = _first_float(div.get("portfolio_survivability"), regime.get("portfolio_survivability_score"), tm.get("portfolio_stability_score"), risk.get("average_portfolio_risk_score"), default=0.0)
        concentration = _first_float(div.get("concentration_risk"), regime.get("portfolio_concentration_risk"), tm.get("sector_concentration_score"), risk.get("highest_concentration_risk"), default=0.0)
        correlation = _first_float(div.get("correlation_risk"), regime.get("portfolio_correlation_risk"), tm.get("portfolio_correlation_risk"), risk.get("highest_correlation_risk"), default=0.0)
        heat = _first_float(tm.get("portfolio_heat_score"), risk.get("average_portfolio_risk_score"), default=0.0)
        return {
            "portfolio_survivability": _metric(survivability if survivability > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Portfolio-level durability and survivability score."),
            "concentration_risk": _metric(concentration if concentration > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Risk from clustered symbols/sectors/archetypes."),
            "correlation_risk": _metric(correlation if correlation > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Risk from correlated candidates or positions."),
            "portfolio_heat": _metric(heat if heat > 0 else None, evidence_count=len(rows), maturity=mature, explanation="Aggregate pressure from open/selected risk."),
            "diversification_quality": _metric(div.get("diversification_quality"), evidence_count=len(rows), maturity=_text(div.get("maturity"), mature), explanation="Quality of current sector/cap/archetype/horizon balance."),
            "portfolio_fit_quality": _metric(div.get("portfolio_fit_quality"), evidence_count=len(rows), maturity=_text(div.get("maturity"), mature), explanation="Average paper candidate fit after concentration/correlation pressure."),
            "largest_cluster": _text(div.get("largest_cluster"), "unknown_cluster"),
            "top_duplicate_theme": _text(div.get("top_duplicate_theme"), "unknown"),
            "current_portfolio_balance_label": _text(div.get("current_portfolio_balance_label"), "warming_up"),
            "portfolio_balance_summary": _text(regime.get("portfolio_balance_summary") or tm.get("portfolio_risk_summary"), "Waiting for portfolio diagnostics."),
        }

    def _learning_maturity_summary(self, statuses: dict[str, dict[str, Any]], paper: dict[str, Any], evidence_count: int, maturity: dict[str, Any]) -> dict[str, Any]:
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        adaptive = statuses.get("adaptive_learning_infrastructure") or {}
        coverage = _first_float(replay.get("lifecycle_tracking_quality_score"), paper.get("completed_trade_coverage_pct"), default=0.0)
        return {
            "replay_maturity": _metric(replay.get("replay_learning_maturity_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("replay_learning_ready") else "awaiting_replay_data"),
            "lifecycle_maturity": _metric(replay.get("lifecycle_tracking_quality_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("lifecycle_tracking_ready") else "awaiting_lifecycle_outcomes"),
            "expectancy_maturity": _metric(replay.get("expectancy_learning_maturity_score"), evidence_count=evidence_count, maturity="healthy" if replay.get("expectancy_learning_ready") else maturity.get("label", "insufficient_evidence")),
            "closed_trade_coverage": _metric(coverage if coverage > 0 else None, evidence_count=evidence_count, maturity=maturity.get("label", "insufficient_evidence")),
            "adaptive_confidence": _metric(adaptive.get("learning_readiness_score"), evidence_count=evidence_count, maturity=maturity.get("label", "insufficient_evidence")),
            "learning_loop_summary": _text(replay.get("learning_loop_summary") or adaptive.get("adaptive_learning_summary"), maturity.get("explanation")),
        }

    def _regime_context_summary(self, statuses: dict[str, dict[str, Any]], rows: list[dict[str, Any]], history: list[dict[str, Any]], maturity: dict[str, Any]) -> dict[str, Any]:
        regime = statuses.get("regime_execution_survivability") or {}
        edge = statuses.get("edge_development") or {}
        current = _text(regime.get("current_market_regime"), "uncertain_regime")
        best_arch = _text(edge.get("best_current_archetype") or regime.get("strongest_survivability_archetype"), "insufficient_data")
        posture = _text((statuses.get("market_session_execution_timing") or {}).get("open_confirmation_label"), "guarded")
        return {
            "current_regime": current,
            "regime_alignment": _metric(regime.get("regime_trade_alignment_score"), evidence_count=max(len(rows), len(history)), maturity="healthy" if rows else maturity.get("label", "insufficient_evidence")),
            "best_archetype": best_arch,
            "operating_posture": posture,
            "strongest_regime": _text(regime.get("strongest_regime"), "insufficient_data"),
            "weakest_regime": _text(regime.get("weakest_regime"), "insufficient_data"),
            "regime_behavior_summary": _text(regime.get("regime_behavior_summary"), "Waiting for regime evidence."),
        }

    def _adaptive_execution_exit_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_learning"),
            "maturity": _text(data.get("maturity"), "insufficient_lifecycle_data"),
            "evidence_count": _to_int(data.get("evidence_count"), 0),
            "execution_posture": _text(data.get("execution_posture"), "confirmation_required"),
            "exit_quality": data.get("exit_quality"),
            "continuation_quality": data.get("continuation_quality"),
            "chase_risk": data.get("chase_risk"),
            "adaptive_profitability": data.get("adaptive_profitability"),
            "lifecycle_stability": data.get("lifecycle_stability"),
            "strongest_adaptive_behavior": _text(data.get("strongest_adaptive_behavior"), "insufficient_data"),
            "biggest_weakness": _text(data.get("biggest_weakness"), "insufficient_lifecycle_data"),
            "summary": _text(data.get("summary"), "Adaptive execution and exit diagnostics are warming up."),
            "adaptive_execution_intelligence": dict(data.get("execution_timing_diagnostics") or {}),
            "exit_intelligence_v2": dict(data.get("adaptive_exit_diagnostics") or {}),
            "regime_adaptive_trading": dict(data.get("regime_adaptation_diagnostics") or {}),
            "lifecycle_adaptation": dict(data.get("lifecycle_adaptation_diagnostics") or {}),
            "profitability_improvement_diagnostics": dict(data.get("profitability_improvement_diagnostics") or {}),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "stale": bool(data.get("stale") or data.get("stale_cache")),
            "degraded_reason": _text(data.get("degraded_reason"), ""),
            "live_trading_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _mobile_runtime_compaction_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_display_compaction"),
            "mobile_runtime_compaction_active": bool(data.get("mobile_runtime_compaction_active", False)),
            "true_broker_active_positions": data.get("true_broker_active_positions"),
            "internal_open_workflow_rows": _to_int(data.get("internal_open_workflow_rows"), 0),
            "stale_internal_positions": _to_int(data.get("stale_internal_positions"), 0),
            "display_active_positions_count": _to_int(data.get("display_active_positions_count"), 0),
            "active_positions_preview_limit": _to_int(data.get("active_positions_preview_limit"), 5),
            "recent_orders_preview_limit": _to_int(data.get("recent_orders_preview_limit"), 5),
            "canceled_orders_compacted_count": _to_int(data.get("canceled_orders_compacted_count"), 0),
            "stale_rows_hidden_count": _to_int(data.get("stale_rows_hidden_count"), 0),
            "learning_fast_path_active": bool(data.get("learning_fast_path_active", False)),
            "canceled_order_scan_skipped": bool(data.get("canceled_order_scan_skipped", True)),
            "learning_payload_compacted": bool(data.get("learning_payload_compacted", False)),
            "mobile_payload_compacted": bool(data.get("mobile_payload_compacted", False)),
            "full_history_preserved": bool(data.get("full_history_preserved", True)),
            "replay_learning_preserved": bool(data.get("replay_learning_preserved", True)),
            "summary": _text(data.get("summary"), "Mobile runtime compaction diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _profit_seeking_exploration_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_calibration"),
            "controlled_exploration_enabled": bool(data.get("controlled_exploration_enabled", True)),
            "exploration_mode": _text(data.get("exploration_mode"), "profit_seeking"),
            "exploration_randomness_allowed": bool(data.get("exploration_randomness_allowed", False)),
            "participation_quality_score": data.get("participation_quality_score"),
            "caution_aggression_balance_score": data.get("caution_aggression_balance_score"),
            "caution_aggression_label": _text(data.get("caution_aggression_label"), "insufficient_evidence"),
            "over_cautious_risk": data.get("over_cautious_risk"),
            "under_cautious_risk": data.get("under_cautious_risk"),
            "missed_opportunity_pressure": data.get("missed_opportunity_pressure"),
            "learning_diversity_score": data.get("learning_diversity_score"),
            "exploration_trades_allowed_today": _to_int(data.get("exploration_trades_allowed_today"), _to_int(data.get("exploration_max_new_trades_per_day"), 0)),
            "exploration_trades_used_today": _to_int(data.get("exploration_trades_used_today"), 0),
            "underexplored_contexts": list(data.get("underexplored_contexts") or [])[:8],
            "overexplored_contexts": list(data.get("overexplored_contexts") or [])[:8],
            "exploration_allocation_pct": _to_float(data.get("exploration_allocation_pct"), 0.0),
            "exploitation_allocation_pct": _to_float(data.get("exploitation_allocation_pct"), 100.0),
            "exploration_decay_active": bool(data.get("exploration_decay_active", True)),
            "exploration_decay_reason": _text(data.get("exploration_decay_reason"), "warming_up"),
            "adaptive_exploration_recommendation": _text(data.get("adaptive_exploration_recommendation"), "maintain_bounded_profit_seeking_exploration"),
            "summary": _text(data.get("summary"), "Profit-seeking exploration diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _market_calendar_knowledge_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "market_calendar_available": bool(data.get("market_calendar_available", False)),
            "market_calendar_source": _text(data.get("market_calendar_source"), "local_estimate"),
            "market_calendar_cache_hit": bool(data.get("market_calendar_cache_hit", False)),
            "market_calendar_stale": bool(data.get("market_calendar_stale", False)),
            "current_session_type": _text(data.get("current_session_type") or data.get("market_session_mode"), "unknown_closed"),
            "session_tradable": bool(data.get("session_tradable") or data.get("market_is_tradable")),
            "broker_order_submission_allowed": bool(data.get("broker_order_submission_allowed") or data.get("paper_order_submission_allowed")),
            "next_market_open": _text(data.get("next_market_open")),
            "next_market_close": _text(data.get("next_market_close")),
            "holiday_name": _text(data.get("holiday_name")),
            "is_market_holiday": bool(data.get("is_market_holiday", False)),
            "is_early_close": bool(data.get("is_early_close", False)),
            "early_close_time": _text(data.get("early_close_time")),
            "minutes_until_open": data.get("minutes_until_open"),
            "minutes_until_close": data.get("minutes_until_close"),
            "session_risk_label": _text(data.get("session_risk_label"), "unknown"),
            "session_risk_score": data.get("session_risk_score"),
            "session_execution_posture": _text(data.get("session_execution_posture"), "observe_only_execution_intent"),
            "session_confirmation_requirement": _text(data.get("session_confirmation_requirement"), "market_open_confirmation_required"),
            "market_structure_label": _text(data.get("market_structure_label"), "unknown"),
            "trade_style_environment": _text(data.get("trade_style_environment"), "unknown"),
            "behavioral_market_state": _text(data.get("behavioral_market_state"), "unknown"),
            "market_context_summary": _text(data.get("market_context_summary"), "Market context diagnostics are warming up."),
            "market_knowledge_confidence": data.get("market_knowledge_confidence"),
            "market_context_supports_exploration": bool(data.get("market_context_supports_exploration", False)),
            "exploration_context_quality": data.get("exploration_context_quality"),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _broad_universe_intake_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_candidate_promotion"),
            "broad_universe_pipeline_active": bool(data.get("broad_universe_pipeline_active", False)),
            "broad_universe_size": _to_int(data.get("broad_universe_size"), 0),
            "tradable_universe_size": _to_int(data.get("tradable_universe_size"), 0),
            "universe_source": _text(data.get("universe_source"), "local_cache"),
            "universe_cache_hit": bool(data.get("universe_cache_hit", False)),
            "universe_stale": bool(data.get("universe_stale", False)),
            "scan_slice_size": _to_int(data.get("scan_slice_size"), 0),
            "scan_slice_index": _to_int(data.get("scan_slice_index"), 0),
            "scan_slice_total": _to_int(data.get("scan_slice_total"), 0),
            "symbols_scanned_this_cycle": _to_int(data.get("symbols_scanned_this_cycle"), 0),
            "symbols_scanned_today": _to_int(data.get("symbols_scanned_today"), 0),
            "universe_coverage_today_pct": _to_float(data.get("universe_coverage_today_pct"), 0.0),
            "candidates_detected": _to_int(data.get("candidates_detected"), 0),
            "lightweight_scored_count": _to_int(data.get("lightweight_scored_count"), 0),
            "shortlist_count": _to_int(data.get("shortlist_count"), 0),
            "deep_scored_count": _to_int(data.get("deep_scored_count"), 0),
            "promoted_to_top_buys_count": _to_int(data.get("promoted_to_top_buys_count"), 0),
            "promoted_symbols": list(data.get("promoted_symbols") or [])[:20],
            "promoted_cap_distribution": dict(data.get("promoted_cap_distribution") or {}),
            "promoted_sector_distribution": dict(data.get("promoted_sector_distribution") or {}),
            "fmp_usage_pct": _to_float(data.get("fmp_usage_pct"), 0.0),
            "fmp_bandwidth_used_gb": _to_float(data.get("fmp_bandwidth_used_gb"), 0.0),
            "fmp_bandwidth_limit_gb": _to_float(data.get("fmp_bandwidth_limit_gb"), 50.0),
            "fmp_budget_state": _text(data.get("fmp_budget_state"), "degraded_unknown_usage"),
            "current_learning_bias": _text(data.get("current_learning_bias"), "warming_up"),
            "next_scan_focus": _text(data.get("next_scan_focus"), "quality_rotation"),
            "learning_diversity_improved": bool(data.get("learning_diversity_improved", False)),
            "summary": _text(
                data.get("summary"),
                f"Broad universe scanned {_to_int(data.get('symbols_scanned_this_cycle'), 0)} symbols and promoted {_to_int(data.get('promoted_to_top_buys_count'), 0)} bounded candidates.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
        }

    def _trade_lifecycle_excursion_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        tracked_total = _to_int(data.get("total_tracked_lifecycles"), 0)
        maturity = _text(data.get("maturity"), "warming_up" if tracked_total else "awaiting_lifecycle_outcomes")
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_lifecycle_observability"),
            "maturity": maturity,
            "tracked_active_trades": _to_int(data.get("tracked_active_trades"), 0),
            "tracked_closed_trades": _to_int(data.get("tracked_closed_trades"), 0),
            "total_tracked_lifecycles": tracked_total,
            "average_mfe_pct": data.get("average_mfe_pct"),
            "average_mae_pct": data.get("average_mae_pct"),
            "average_profit_giveback_pct": data.get("average_profit_giveback_pct"),
            "average_hold_duration_minutes": data.get("average_hold_duration_minutes"),
            "follow_through_quality_score": data.get("follow_through_quality_score"),
            "exit_quality_score": data.get("exit_quality_score"),
            "profit_capture_quality": data.get("profit_capture_quality"),
            "exit_label_distribution": dict(data.get("exit_label_distribution") or {}),
            "follow_through_distribution": dict(data.get("follow_through_distribution") or {}),
            "strongest_follow_through_context": _text(data.get("strongest_follow_through_context"), "insufficient_evidence"),
            "weakest_follow_through_context": _text(data.get("weakest_follow_through_context"), "insufficient_evidence"),
            "premature_exit_count": _to_int(data.get("premature_exit_count"), 0),
            "overstayed_exit_count": _to_int(data.get("overstayed_exit_count"), 0),
            "learning_ready": bool(data.get("learning_ready", False)),
            "summary": _text(
                data.get("summary"),
                "Trade lifecycle excursion telemetry is waiting for active or naturally closed paper trades.",
            ),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
        }

    def _execution_participation_audit_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "1.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_audit"),
            "participation_label": _text(data.get("participation_label"), "insufficient_evidence"),
            "candidates_seen": _to_int(data.get("candidates_seen"), 0),
            "candidates_promoted": _to_int(data.get("candidates_promoted"), 0),
            "candidates_deep_scored": _to_int(data.get("candidates_deep_scored"), 0),
            "candidates_execution_reviewed": _to_int(data.get("candidates_execution_reviewed"), 0),
            "candidates_portfolio_rejected": _to_int(data.get("candidates_portfolio_rejected"), 0),
            "candidates_timing_rejected": _to_int(data.get("candidates_timing_rejected"), 0),
            "candidates_correlation_rejected": _to_int(data.get("candidates_correlation_rejected"), 0),
            "candidates_confirmation_rejected": _to_int(data.get("candidates_confirmation_rejected"), 0),
            "candidates_exploration_rejected": _to_int(data.get("candidates_exploration_rejected"), 0),
            "candidates_position_limit_rejected": _to_int(data.get("candidates_position_limit_rejected"), 0),
            "candidates_submitted": _to_int(data.get("candidates_submitted"), 0),
            "candidates_filled": _to_int(data.get("candidates_filled"), 0),
            "eligible_candidates": _to_int(data.get("eligible_candidates"), 0),
            "orders_attempted": _to_int(data.get("orders_attempted"), 0),
            "orders_rejected": _to_int(data.get("orders_rejected"), 0),
            "participation_efficiency_score": _to_float(data.get("participation_efficiency_score"), 0.0),
            "participation_suppression_score": _to_float(data.get("participation_suppression_score"), 0.0),
            "missed_opportunity_pressure": _to_float(data.get("missed_opportunity_pressure"), 0.0),
            "overprotection_risk": _to_float(data.get("overprotection_risk"), 0.0),
            "underparticipation_risk": _to_float(data.get("underparticipation_risk"), 0.0),
            "execution_conversion_rate": _to_float(data.get("execution_conversion_rate"), 0.0),
            "eligible_to_submitted_rate": _to_float(data.get("eligible_to_submitted_rate"), 0.0),
            "submitted_to_filled_rate": _to_float(data.get("submitted_to_filled_rate"), 0.0),
            "market_opportunity_capture_rate": _to_float(data.get("market_opportunity_capture_rate"), 0.0),
            "missed_follow_through_pct": _to_float(data.get("missed_follow_through_pct"), 0.0),
            "missed_profit_capture_pct": _to_float(data.get("missed_profit_capture_pct"), 0.0),
            "missed_breakout_count": _to_int(data.get("missed_breakout_count"), 0),
            "missed_continuation_count": _to_int(data.get("missed_continuation_count"), 0),
            "missed_high_expectancy_candidates": _to_int(data.get("missed_high_expectancy_candidates"), 0),
            "top_rejection_reasons": dict(data.get("top_rejection_reasons") or {}),
            "rejection_stage_counts": dict(data.get("rejection_stage_counts") or {}),
            "final_blocker_reason": _text(data.get("final_blocker_reason"), "none"),
            "summary": _text(data.get("summary"), "Execution participation audit is collecting suppression evidence."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "paper_only_preserved": bool(data.get("paper_only_preserved", True)),
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": bool(data.get("forced_trades_enabled", False)),
            "forced_exits_enabled": bool(data.get("forced_exits_enabled", False)),
        }

    def _portfolio_diversification_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        return {
            "enabled": bool(data.get("enabled", False)),
            "version": _text(data.get("version"), "2.0.0"),
            "mode": _text(data.get("mode"), "paper_only_shadow_diversification"),
            "maturity": _text(data.get("maturity"), "warming_up"),
            "portfolio_diversification_v2_active": bool(data.get("portfolio_diversification_v2_active", True)),
            "average_portfolio_fit_score": data.get("average_portfolio_fit_score"),
            "average_diversification_quality_score": data.get("average_diversification_quality_score"),
            "average_correlation_pressure_score": data.get("average_correlation_pressure_score"),
            "average_concentration_pressure_score": data.get("average_concentration_pressure_score"),
            "largest_cluster": _text(data.get("largest_cluster"), "unknown_cluster"),
            "largest_cluster_count": _to_int(data.get("largest_cluster_count"), 0),
            "top_duplicate_theme": _text(data.get("top_duplicate_theme"), "unknown"),
            "mega_cap_concentration_pct": _to_float(data.get("mega_cap_concentration_pct"), 0.0),
            "non_mega_quality_candidates": _to_int(data.get("non_mega_quality_candidates"), 0),
            "candidates_penalized_for_correlation": _to_int(data.get("candidates_penalized_for_correlation"), 0),
            "candidates_boosted_for_diversification": _to_int(data.get("candidates_boosted_for_diversification"), 0),
            "elite_candidates_survived_penalty": _to_int(data.get("elite_candidates_survived_penalty"), 0),
            "current_portfolio_balance_label": _text(data.get("current_portfolio_balance_label"), "warming_up"),
            "candidate_cluster_summary": dict(data.get("candidate_cluster_summary") or {}),
            "summary": _text(data.get("summary"), "Portfolio diversification diagnostics are warming up."),
            "api_calls_used": _to_int(data.get("api_calls_used"), 0),
            "cache_hit": bool(data.get("cache_hit", False)),
            "build_ms": _to_float(data.get("build_ms"), 0.0),
            "stale": bool(data.get("stale") or data.get("stale_cache")),
            "degraded_reason": _text(data.get("degraded_reason"), ""),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": bool(data.get("alpaca_paper_only_preserved", True)),
            "natural_exit_preserved": bool(data.get("natural_exit_preserved", True)),
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }

    def _system_health_summary(self, sources: dict[str, Any], statuses: dict[str, dict[str, Any]], learning_fast: dict[str, Any]) -> dict[str, Any]:
        failed = [k for k, v in statuses.items() if isinstance(v, dict) and v.get("enabled") is False and v.get("degraded_reason")]
        runtime = _first_float(learning_fast.get("runtime_learning_stability"), (statuses.get("adaptive_learning_infrastructure") or {}).get("trading_day_health_score"), default=0.0)
        provider_health = 100.0
        data_quality = _first_float((statuses.get("adaptive_learning_infrastructure") or {}).get("learning_readiness_score"), default=0.0)
        integrity = _first_float((statuses.get("adaptive_learning_infrastructure") or {}).get("infrastructure_maturity_score"), runtime, default=0.0)
        refresh = 100.0 if not failed else max(0.0, 100.0 - len(failed) * 12.0)
        degraded_reason = ""
        if failed:
            degraded_reason = f"{len(failed)} advanced diagnostics degraded"
        return {
            "runtime_integrity": _metric(integrity if integrity > 0 else None, evidence_count=1, maturity="healthy" if not failed else "degraded"),
            "data_quality": _metric(data_quality if data_quality > 0 else None, evidence_count=1, maturity="healthy" if data_quality > 0 else "warming_up"),
            "provider_health": _metric(provider_health, evidence_count=1, maturity="healthy", explanation="Unified diagnostics used cached/local data only."),
            "learning_refresh_integrity": _metric(refresh, evidence_count=1, maturity="healthy" if not failed else "degraded"),
            "degraded_reason": degraded_reason,
        }

    def _executive_snapshot(self, perf: dict[str, Any], execution: dict[str, Any], portfolio: dict[str, Any], learning: dict[str, Any], regime: dict[str, Any], system: dict[str, Any], rows: list[dict[str, Any]], evidence_count: int) -> dict[str, Any]:
        weakness_candidates = []
        for name, summary, key in (
            ("entry_quality", execution, "entry_quality"),
            ("exit_quality", execution, "exit_quality"),
            ("follow_through", execution, "follow_through_quality"),
            ("portfolio_survivability", portfolio, "portfolio_survivability"),
            ("replay_maturity", learning, "replay_maturity"),
        ):
            metric = summary.get(key) or {}
            value = metric.get("value")
            if value is not None:
                weakness_candidates.append((float(value), name))
        main_weakness = min(weakness_candidates)[1] if weakness_candidates else "insufficient_evidence"
        strongest = max(weakness_candidates)[1] if weakness_candidates else "warming_up"
        if main_weakness == "portfolio_survivability":
            next_focus = "reduce concentration and correlation before expanding exposure"
        elif main_weakness in {"entry_quality", "follow_through"}:
            next_focus = "tighten entry confirmation and follow-through validation"
        elif main_weakness == "exit_quality":
            next_focus = "review natural exit timing and profit giveback patterns"
        else:
            next_focus = "collect more naturally closed and replay-reviewed paper outcomes"
        evidence_label = "healthy" if evidence_count >= 50 else ("warming_up" if evidence_count > 0 else "insufficient_closed_trades")
        confidence_label = "high" if evidence_count >= 100 else ("medium" if evidence_count >= 30 else "low")
        primary_blocker = "none"
        if evidence_label != "healthy":
            primary_blocker = evidence_label
        elif (portfolio.get("concentration_risk") or {}).get("value", 0) and (portfolio.get("concentration_risk") or {}).get("value", 0) >= 75:
            primary_blocker = "portfolio_concentration_risk"
        return {
            "core_performance": {k: perf[k] for k in ("released_win_rate", "profit_factor", "expectancy_score", "average_return", "buy_list_purity")},
            "execution_quality": {k: execution[k] for k in ("entry_quality", "exit_quality", "follow_through_quality", "confidence_truthfulness")},
            "market_intelligence": {
                "current_regime": regime.get("current_regime"),
                "regime_alignment": regime.get("regime_alignment"),
                "best_archetype": regime.get("best_archetype"),
                "operating_posture": regime.get("operating_posture"),
            },
            "portfolio_health": {k: portfolio[k] for k in ("portfolio_survivability", "concentration_risk", "correlation_risk", "portfolio_heat")},
            "learning_status": {k: learning[k] for k in ("replay_maturity", "lifecycle_maturity", "expectancy_maturity", "closed_trade_coverage", "adaptive_confidence")},
            "system_health": {k: system[k] for k in ("runtime_integrity", "data_quality", "provider_health", "learning_refresh_integrity")},
            "main_current_weakness": main_weakness,
            "strongest_current_area": strongest,
            "next_best_focus": next_focus,
            "primary_blocker_reason": primary_blocker,
            "confidence_label": confidence_label,
            "evidence_label": evidence_label,
            "candidate_count": len(rows),
            "closed_trade_count": evidence_count,
        }

    def _master_charts(self, history_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        rows = history_rows[-CHART_POINTS:]
        returns = [_return_pct(r) for r in rows]
        timestamps = [_timestamp(r, i) for i, r in enumerate(rows)]
        equity: list[float] = []
        eq = 100.0
        peak = 100.0
        drawdown: list[float] = []
        for ret in returns:
            eq *= 1.0 + (ret / 100.0)
            peak = max(peak, eq)
            equity.append(round(eq, 4))
            drawdown.append(round(((eq - peak) / peak) * 100.0, 4) if peak else 0.0)
        rolling_exp = _rolling(returns, 20)
        rolling_wr: list[float] = []
        rolling_pf: list[float] = []
        for i in range(len(returns)):
            chunk = returns[max(0, i - 19): i + 1]
            rolling_wr.append(round(sum(1 for v in chunk if v > 0) / max(1, len(chunk)) * 100.0, 2))
            rolling_pf.append(_profit_factor(chunk) or 0.0)
        entry = [_score(r.get("entry_quality") or r.get("entry_timing_quality"), 50.0) for r in rows]
        follow = [_score(r.get("follow_through_quality_score") or r.get("follow_through_probability"), 50.0) for r in rows]
        exit_q = [_score(r.get("exit_quality_score") or r.get("exit_timing_quality"), 50.0) for r in rows]
        giveback = [_clamp(_to_float(r.get("profit_giveback") or r.get("profit_giveback_pct") or r.get("missed_profit_pct"), 0.0), 0.0, 100.0) for r in rows]
        weak_follow = [100.0 - v for v in follow]
        regime = statuses.get("regime_execution_survivability") or {}
        portfolio = statuses.get("trade_management_portfolio") or {}
        div = statuses.get("portfolio_diversification_correlation_v2") or {}
        replay = statuses.get("replay_lifecycle_expectancy") or {}
        adaptive_v2 = statuses.get("adaptive_execution_exit_intelligence_v2") or {}
        adaptive_exit = dict(adaptive_v2.get("adaptive_exit_diagnostics") or {})
        adaptive_exec = dict(adaptive_v2.get("execution_timing_diagnostics") or {})
        adaptive_lifecycle = dict(adaptive_v2.get("lifecycle_adaptation_diagnostics") or {})
        adaptive_profit = dict(adaptive_v2.get("profitability_improvement_diagnostics") or {})
        heat = _score(portfolio.get("portfolio_heat_score"), 50.0)
        concentration = _score(div.get("concentration_risk"), _score(regime.get("portfolio_concentration_risk"), 50.0))
        correlation = _score(div.get("correlation_risk"), _score(regime.get("portfolio_correlation_risk"), 50.0))
        survivability = _score(div.get("portfolio_survivability"), _score(regime.get("portfolio_survivability_score"), 50.0))
        diversification = _score(div.get("diversification_quality"), max(0.0, 100.0 - concentration))
        portfolio_fit = _score(div.get("portfolio_fit_quality"), 50.0)
        cluster_pressure = _score(div.get("average_correlation_pressure_score"), correlation)
        timeline_len = max(1, len(timestamps))
        heat_series = [round(heat, 2)] * timeline_len
        concentration_series = [round(concentration, 2)] * timeline_len
        correlation_series = [round(correlation, 2)] * timeline_len
        survivability_series = [round(survivability, 2)] * timeline_len
        diversification_series = [round(diversification, 2)] * timeline_len
        portfolio_fit_series = [round(portfolio_fit, 2)] * timeline_len
        cluster_pressure_series = [round(cluster_pressure, 2)] * timeline_len
        maturity_series = [round(_score(replay.get("replay_learning_maturity_score"), 0.0), 2)] * timeline_len
        lifecycle_series = [round(_score(replay.get("lifecycle_tracking_quality_score"), 0.0), 2)] * timeline_len
        expectancy_series = [round(_score(replay.get("expectancy_learning_maturity_score"), 0.0), 2)] * timeline_len
        coverage_series = [round(_score(replay.get("lifecycle_tracking_quality_score"), 0.0), 2)] * timeline_len
        adaptive_series = [round(_score((statuses.get("adaptive_learning_infrastructure") or {}).get("learning_readiness_score"), 0.0), 2)] * timeline_len
        adaptive_giveback_series = [round(_score((adaptive_exit.get("profit_giveback_pressure") or {}).get("value"), 0.0), 2)] * timeline_len
        adaptive_continuation_series = [round(_score(adaptive_v2.get("continuation_quality"), _score((adaptive_exit.get("continuation_strength") or {}).get("value"), 50.0)), 2)] * timeline_len
        adaptive_hold_series = [round(_score((adaptive_exit.get("adaptive_hold_quality") or {}).get("value"), _score((adaptive_lifecycle.get("hold_quality") or {}).get("value"), 50.0)), 2)] * timeline_len
        regime_expectancy_series = [round(_score((adaptive_profit.get("regime_adjusted_expectancy") or {}).get("value"), 50.0), 2)] * timeline_len
        execution_timing_series = [round(_score((adaptive_exec.get("execution_timing_quality") or {}).get("value"), 50.0), 2)] * timeline_len
        matrix: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for r in history_rows[-MAX_ROWS:]:
            reg = _text(r.get("current_market_regime") or r.get("market_regime") or r.get("regime_context"), "unknown")
            arch = _text(r.get("trade_archetype") or r.get("setup_type"), "unknown")
            bucket = matrix[reg].setdefault(arch, {"sample_size": 0, "returns": []})
            bucket["sample_size"] += 1
            bucket["returns"].append(_return_pct(r))
        heatmap = {}
        for reg, arches in matrix.items():
            heatmap[reg] = {}
            for arch, vals in arches.items():
                rets = vals.get("returns") or []
                heatmap[reg][arch] = {
                    "sample_size": len(rets),
                    "expectancy": round(mean(rets), 4) if rets else None,
                    "win_rate": round(sum(1 for v in rets if v > 0) / max(1, len(rets)) * 100.0, 2) if rets else None,
                    "profit_factor": _profit_factor(rets),
                }
        return {
            "equity_curve_drawdown_upgrade_timeline": {
                "timestamps": timestamps,
                "equity_values": equity,
                "drawdown_values": drawdown,
                "upgrade_markers": [],
                "regime_markers": [_text(regime.get("current_market_regime"), "uncertain_regime")],
                "portfolio_heat_markers": heat_series,
            },
            "rolling_expectancy_profit_factor_win_rate": {
                "timestamps": timestamps,
                "rolling_expectancy": rolling_exp,
                "rolling_profit_factor": rolling_pf,
                "rolling_win_rate": rolling_wr,
                "regime_markers": [_text(regime.get("current_market_regime"), "uncertain_regime")],
            },
            "entry_followthrough_exit_quality": {
                "timestamps": timestamps,
                "entry_quality": entry,
                "follow_through_quality": follow,
                "exit_quality": exit_q,
                "profit_giveback": giveback,
                "weak_follow_through_rate": weak_follow,
            },
            "portfolio_survivability": {
                "timestamps": timestamps,
                "portfolio_survivability": survivability_series,
                "concentration_risk": concentration_series,
                "correlation_risk": correlation_series,
                "portfolio_heat": heat_series,
                "diversification_quality": diversification_series,
                "portfolio_fit_quality": portfolio_fit_series,
                "cluster_pressure": cluster_pressure_series,
            },
            "portfolio_diversification_correlation_v2_trends": {
                "timestamps": timestamps,
                "diversification_quality_trend": diversification_series,
                "correlation_risk_trend": correlation_series,
                "concentration_risk_trend": concentration_series,
                "portfolio_fit_trend": portfolio_fit_series,
                "cluster_pressure_trend": cluster_pressure_series,
            },
            "learning_maturity_timeline": {
                "timestamps": timestamps,
                "replay_maturity": maturity_series,
                "lifecycle_maturity": lifecycle_series,
                "expectancy_maturity": expectancy_series,
                "closed_trade_coverage": coverage_series,
                "adaptive_confidence": adaptive_series,
            },
            "adaptive_execution_exit_v2_trends": {
                "timestamps": timestamps,
                "profit_giveback_trend": adaptive_giveback_series,
                "continuation_quality_trend": adaptive_continuation_series,
                "adaptive_hold_quality_trend": adaptive_hold_series,
                "regime_adjusted_expectancy_trend": regime_expectancy_series,
                "execution_timing_trend": execution_timing_series,
            },
            "regime_archetype_performance_heatmap": {
                "regime_archetype_matrix": heatmap,
                "expectancy_by_regime": {k: round(mean([cell.get("expectancy") or 0 for cell in v.values()]), 4) for k, v in heatmap.items()},
                "win_rate_by_archetype": self._aggregate_heatmap(heatmap, "win_rate"),
                "profit_factor_by_archetype": self._aggregate_heatmap(heatmap, "profit_factor"),
                "sample_size_by_cell": {reg: {arch: cell.get("sample_size", 0) for arch, cell in arches.items()} for reg, arches in heatmap.items()},
            },
        }

    @staticmethod
    def _aggregate_heatmap(heatmap: dict[str, dict[str, dict[str, Any]]], key: str) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for arches in heatmap.values():
            for arch, cell in arches.items():
                value = cell.get(key)
                if value is not None:
                    grouped[arch].append(float(value))
        return {arch: round(mean(values), 4) for arch, values in grouped.items() if values}

    def _advanced_statuses(self, statuses: dict[str, dict[str, Any]], sources: dict[str, Any]) -> dict[str, Any]:
        names = [
            "learning_snapshot", "paper_performance", "top_buys", "edge_development", "trade_management_portfolio",
            "adaptive_learning_infrastructure", "replay_lifecycle_expectancy", "regime_execution_survivability",
            "adaptive_execution_exit_intelligence_v2", "market_session_execution_timing", "paper_opportunity_allocation",
            "portfolio_diversification_correlation_v2", "profit_seeking_adaptive_exploration", "mobile_runtime_compaction",
            "market_calendar_knowledge", "broad_universe_intake_promotion", "trade_lifecycle_excursion",
            "execution_participation_audit",
            "alpaca_paper_broker", "horizon_performance_dashboard",
        ]
        out = {}
        for name in names:
            payload = statuses.get(name) or sources.get(name) or {}
            out[name] = {
                "status": "available" if isinstance(payload, dict) and payload else "not_loaded",
                "maturity": _text((payload or {}).get("maturity") or (payload or {}).get("mode"), "summary_only"),
                "primary_metric": _first((payload or {}).get("primary_metric"), (payload or {}).get("score"), (payload or {}).get("enabled"), default=None),
                "blocker": _text((payload or {}).get("degraded_reason") or (payload or {}).get("final_blocker_reason"), "none"),
                "api_calls_used": _to_int((payload or {}).get("api_calls_used"), 0),
                "stale": bool((payload or {}).get("stale") or (payload or {}).get("stale_cache")),
                "endpoint": self._endpoint_for(name),
            }
        return out

    @staticmethod
    def _endpoint_for(name: str) -> str:
        mapping = {
            "learning_snapshot": "/api/learning_snapshot_fast_v1",
            "paper_performance": "/api/paper_performance",
            "top_buys": "/api/top_buys?buy_mode=balanced",
            "edge_development": "/api/edge_development_status_v1",
            "trade_management_portfolio": "/api/trade_management_portfolio_status_v1",
            "adaptive_learning_infrastructure": "/api/adaptive_learning_infrastructure_status_v1",
            "replay_lifecycle_expectancy": "/api/replay_lifecycle_expectancy_status_v1",
            "regime_execution_survivability": "/api/regime_execution_survivability_status_v1",
            "adaptive_execution_exit_intelligence_v2": "/api/adaptive_execution_exit_intelligence_status_v2",
            "portfolio_diversification_correlation_v2": "/api/portfolio_diversification_correlation_status_v2",
            "profit_seeking_adaptive_exploration": "/api/profit_seeking_adaptive_exploration_status_v1",
            "market_calendar_knowledge": "/api/market_calendar_knowledge_status_v1",
            "broad_universe_intake_promotion": "/api/broad_universe_intake_status_v1",
            "trade_lifecycle_excursion": "/api/trade_lifecycle_excursion_status_v1",
            "execution_participation_audit": "/api/execution_participation_audit_status_v1",
            "mobile_runtime_compaction": "/api/mobile_runtime_compaction_status_v1",
            "market_session_execution_timing": "/api/market_session_execution_timing_status_v1",
            "paper_opportunity_allocation": "/api/paper_opportunity_allocation_status_v1",
            "alpaca_paper_broker": "/api/alpaca_paper_status_v1",
            "horizon_performance_dashboard": "/api/horizon_performance_dashboard_v1",
        }
        return mapping.get(name, "")

    def _stale_status(self, sources: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
        stale_sources = []
        for name, payload in sources.items():
            if isinstance(payload, dict) and (payload.get("stale") or payload.get("stale_cache") or payload.get("learning_payload_stale")):
                stale_sources.append(name)
        return {
            "stale": bool(stale_sources),
            "stale_sources": stale_sources,
            "last_known_good_used": bool(stale_sources),
            "stale_age_seconds": _to_float(sources.get("stale_age_seconds"), 0.0),
            "message": "Learning snapshot is using last-known-good data because some advanced diagnostics timed out." if stale_sources else "Unified learning snapshot is current enough for display.",
            "degraded_reason": system.get("degraded_reason") or "",
        }

    @staticmethod
    def _integration_contract() -> dict[str, Any]:
        return {
            "use_unified_learning_adapter": True,
            "avoid_frontend_endpoint_spam": True,
            "advanced_panels_lazy_load": True,
            "required_summary_fields": ["status", "maturity", "primary_metric", "blocker", "api_calls_used", "stale"],
            "endpoint_policy": "new endpoints allowed for debugging, but Learning tab should prefer unified snapshot",
        }

    def _fallback(self, reason: str) -> dict[str, Any]:
        maturity = {"label": "degraded", "evidence_count": 0, "explanation": f"Unified diagnostics fallback: {reason[:140]}"}
        empty_metric = _metric(None, evidence_count=0, maturity="insufficient_evidence")
        return {
            "ok": False,
            "enabled": True,
            "version": VERSION,
            "generated_at": _now_iso(),
            "executive_snapshot": {
                "core_performance": {k: empty_metric for k in ("released_win_rate", "profit_factor", "expectancy_score", "average_return", "buy_list_purity")},
                "execution_quality": {k: empty_metric for k in ("entry_quality", "exit_quality", "follow_through_quality", "confidence_truthfulness")},
                "market_intelligence": {"current_regime": "uncertain_regime", "regime_alignment": empty_metric, "best_archetype": "insufficient_data", "operating_posture": "guarded"},
                "portfolio_health": {k: empty_metric for k in ("portfolio_survivability", "concentration_risk", "correlation_risk", "portfolio_heat")},
                "learning_status": {k: empty_metric for k in ("replay_maturity", "lifecycle_maturity", "expectancy_maturity", "closed_trade_coverage", "adaptive_confidence")},
                "system_health": {k: empty_metric for k in ("runtime_integrity", "data_quality", "provider_health", "learning_refresh_integrity")},
                "main_current_weakness": "degraded",
                "strongest_current_area": "unknown",
                "next_best_focus": "restore unified diagnostics",
                "primary_blocker_reason": reason[:140],
                "confidence_label": "low",
                "evidence_label": "degraded",
            },
            "master_charts": self._empty_charts(),
            "performance_summary": {},
            "execution_quality_summary": {},
            "portfolio_health_summary": {},
            "learning_maturity_summary": {},
            "regime_context_summary": {},
            "system_health_summary": {},
            "advanced_panel_links": {},
            "stale_data_status": {"stale": True, "message": "Unified diagnostics fallback is active.", "degraded_reason": reason[:160]},
            "evidence_maturity_status": maturity,
            "future_suite_integration_contract": self._integration_contract(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        }

    @staticmethod
    def _empty_charts() -> dict[str, Any]:
        base = {"timestamps": [], "insufficient_data": True}
        return {
            "equity_curve_drawdown_upgrade_timeline": {**base, "equity_values": [], "drawdown_values": [], "upgrade_markers": [], "regime_markers": [], "portfolio_heat_markers": []},
            "rolling_expectancy_profit_factor_win_rate": {**base, "rolling_expectancy": [], "rolling_profit_factor": [], "rolling_win_rate": [], "regime_markers": []},
            "entry_followthrough_exit_quality": {**base, "entry_quality": [], "follow_through_quality": [], "exit_quality": [], "profit_giveback": [], "weak_follow_through_rate": []},
            "portfolio_survivability": {**base, "portfolio_survivability": [], "concentration_risk": [], "correlation_risk": [], "portfolio_heat": [], "diversification_quality": []},
            "learning_maturity_timeline": {**base, "replay_maturity": [], "lifecycle_maturity": [], "expectancy_maturity": [], "closed_trade_coverage": [], "adaptive_confidence": []},
            "regime_archetype_performance_heatmap": {"regime_archetype_matrix": {}, "expectancy_by_regime": {}, "win_rate_by_archetype": {}, "profit_factor_by_archetype": {}, "sample_size_by_cell": {}},
        }
