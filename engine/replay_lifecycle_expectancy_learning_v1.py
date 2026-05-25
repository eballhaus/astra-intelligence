from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Any

try:
    from engine.regime_execution_survivability_intelligence_v1 import RegimeExecutionSurvivabilityIntelligenceV1
except Exception:  # pragma: no cover - additive diagnostics only
    RegimeExecutionSurvivabilityIntelligenceV1 = None  # type: ignore[assignment]
try:
    from engine.adaptive_execution_exit_intelligence_v2 import AdaptiveExecutionExitIntelligenceV2
except Exception:  # pragma: no cover - additive diagnostics only
    AdaptiveExecutionExitIntelligenceV2 = None  # type: ignore[assignment]
try:
    from engine.portfolio_diversification_correlation_v2 import PortfolioDiversificationCorrelationV2
except Exception:  # pragma: no cover - additive diagnostics only
    PortfolioDiversificationCorrelationV2 = None  # type: ignore[assignment]

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1000


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


def _hours_between(start: Any, end: Any) -> float:
    try:
        s = datetime.fromisoformat(_safe_text(start).replace("Z", "+00:00"))
        e = datetime.fromisoformat(_safe_text(end).replace("Z", "+00:00"))
        return max(0.0, (e - s).total_seconds() / 3600.0)
    except Exception:
        return 0.0


def _stage(row: dict[str, Any]) -> str:
    raw = _safe_text(row.get("lifecycle_stage") or row.get("status") or row.get("state")).lower()
    if raw in {"closed", "replay_reviewed", "partial_exit", "active_position", "filled", "accepted", "submitted"}:
        return raw
    if row.get("closed_at") or row.get("exit_timestamp") or row.get("exit_time"):
        return "closed"
    if row.get("filled_at") or row.get("entry_fill_price") or row.get("avg_entry_price"):
        return "filled"
    if row.get("submitted_at") or row.get("order_id"):
        return "submitted"
    if row.get("candidate_execution_intent") or row.get("execution_intent_status"):
        return "execution_intent"
    return "candidate"


def _expectancy_label(score: float) -> str:
    if score >= 82.0:
        return "elite_expectancy"
    if score >= 68.0:
        return "strong_expectancy"
    if score >= 48.0:
        return "neutral_expectancy"
    if score >= 32.0:
        return "weak_expectancy"
    return "avoid_expectancy"


def _maturity_label(score: float) -> str:
    if score >= 82.0:
        return "advanced_adaptive_system"
    if score >= 64.0:
        return "developing_adaptive_system"
    if score >= 44.0:
        return "emerging_adaptive_system"
    return "early_learning_system"


class ReplayLifecycleExpectancyLearningV1:
    """Paper-only replay, lifecycle, and expectancy learning diagnostics.

    The suite reads bounded local artifacts and produces conservative
    shadow-only recommendations. It never executes, exits, or mutates policy.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.paper_state_path = os.path.join(self.state_dir, "paper_autopilot_state.json")
        self._cache: dict[str, Any] | None = None
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
        self.portfolio_diversification_v2 = (
            PortfolioDiversificationCorrelationV2(state_dir=self.state_dir)
            if PortfolioDiversificationCorrelationV2 is not None
            else None
        )

    def _rows(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return list(self._cache.get("rows") or [])
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=400))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=350))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        self._cache = {"rows": rows[-MAX_ROWS:]}
        return rows[-MAX_ROWS:]

    @staticmethod
    def _return_pct(row: dict[str, Any]) -> float:
        return _to_float(
            row.get("realized_return_pct")
            or row.get("return_pct")
            or row.get("return_percent")
            or row.get("pnl_pct"),
            0.0,
        )

    @staticmethod
    def _group_key(row: dict[str, Any], key: str) -> str:
        if key == "archetype":
            return _safe_text(row.get("trade_archetype") or row.get("setup_type"), "unknown").lower().replace(" ", "_")
        if key == "allocation_lane":
            return _safe_text(row.get("allocation_lane"), "unknown").lower().replace(" ", "_")
        if key == "market_regime":
            return _safe_text(row.get("regime_context") or row.get("market_regime"), "unknown").lower().replace(" ", "_")
        if key == "session_timing":
            return _safe_text(row.get("entry_session_mode") or row.get("trade_session_context"), "unknown").lower().replace(" ", "_")
        if key == "volatility_regime":
            vol = _score01(row.get("volatility_expansion_score"), 50.0)
            if vol >= 70.0:
                return "high_volatility"
            if vol <= 35.0:
                return "low_volatility"
            return "normal_volatility"
        if key == "horizon":
            return _safe_text(row.get("trade_horizon_style") or row.get("best_horizon_style"), "unknown").lower().replace(" ", "_")
        if key == "trade_management_label":
            return _safe_text(row.get("adaptive_trade_quality_label"), "unknown").lower().replace(" ", "_")
        if key == "behavioral_label":
            return _safe_text(row.get("behavioral_label"), "unknown").lower().replace(" ", "_")
        return "unknown"

    def _expectancy_stats(self, rows: list[dict[str, Any]], group_key: str = "archetype") -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            grouped[self._group_key(row, group_key)].append(self._return_pct(row))
        out: dict[str, dict[str, Any]] = {}
        for key, values in grouped.items():
            if not values:
                continue
            wins = [v for v in values if v > 0]
            losses = [abs(v) for v in values if v < 0]
            gross_win = sum(wins)
            gross_loss = sum(losses)
            win_rate = (len(wins) / max(1, len(values))) * 100.0
            avg_return = mean(values)
            profit_factor = gross_win / gross_loss if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
            consistency = _clamp(100.0 - (pstdev(values) * 80.0 if len(values) > 1 else 30.0))
            score = _clamp(45.0 + avg_return * 12.0 + (win_rate - 50.0) * 0.35 + min(profit_factor, 3.0) * 8.0 + consistency * 0.18)
            out[key] = {
                "sample_size": len(values),
                "win_rate": round(win_rate, 2),
                "avg_return": round(avg_return, 4),
                "profit_factor": round(profit_factor, 4),
                "consistency": round(consistency, 2),
                "score": round(score, 2),
                "label": _expectancy_label(score),
            }
        return out

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        symbol = _safe_text(r.get("symbol") or r.get("ticker"), "UNKNOWN").upper()
        ret = self._return_pct(r)
        mfa = max(0.0, _to_float(r.get("max_favorable_excursion") or r.get("peak_unrealized_pnl_percent"), max(ret, 0.0)))
        mae = abs(_to_float(r.get("max_adverse_excursion") or r.get("drawdown_pct"), min(ret, 0.0)))
        giveback = max(0.0, mfa - max(0.0, ret))
        entry_quality = _score01(r.get("entry_quality"), _score01(r.get("entry_filter_v2_score"), 50.0))
        exit_quality = _score01(r.get("exit_quality_score"), 50.0)
        hold_hours = _to_float(r.get("hold_time_hours") or r.get("duration_hours"), 0.0)
        if hold_hours <= 0:
            hold_hours = _hours_between(r.get("entry_timestamp") or r.get("entry_time"), r.get("exit_timestamp") or r.get("exit_time") or r.get("closed_at"))
        hold_quality = _clamp(62.0 + min(25.0, hold_hours * 2.0) - giveback * 8.0 - mae * 4.0)
        timing_quality = _clamp(entry_quality * 0.45 + exit_quality * 0.25 + hold_quality * 0.20 + (100.0 - min(100.0, giveback * 12.0)) * 0.10)
        outcome_quality = _clamp(50.0 + ret * 10.0 + min(mfa, 10.0) * 2.0 - mae * 4.0 - giveback * 3.0)
        trade_quality = _clamp(outcome_quality * 0.42 + timing_quality * 0.33 + hold_quality * 0.25)
        if outcome_quality >= 75.0:
            label = "strong_replay_outcome"
        elif outcome_quality >= 58.0:
            label = "acceptable_replay_outcome"
        elif timing_quality < 42.0:
            label = "poor_timing_detected"
        elif hold_quality < 42.0:
            label = "poor_hold_quality"
        elif giveback > max(2.0, mfa * 0.45):
            label = "premature_exit_detected"
        else:
            label = "weak_replay_outcome"
        lifecycle_stage = _stage(r)
        lifecycle_id = _safe_text(r.get("lifecycle_id") or r.get("trade_id") or f"{symbol}:{_safe_text(r.get('timestamp'), _now_iso())[:19]}")
        return {
            "replay_learning_score": round(_clamp(outcome_quality * 0.45 + trade_quality * 0.35 + timing_quality * 0.20), 2),
            "replay_confidence": round(_clamp(45.0 + min(35.0, hold_hours * 2.0) + (15.0 if lifecycle_stage in {"closed", "replay_reviewed"} else 0.0)), 2),
            "replay_outcome_quality": round(outcome_quality, 2),
            "replay_trade_quality": round(trade_quality, 2),
            "replay_outcome_label": label,
            "replay_recommendation": "review_and_learn_shadow_only" if lifecycle_stage in {"closed", "replay_reviewed"} else "track_until_natural_exit",
            "replay_improvement_reason": f"Return {round(ret, 3)}%, MFE {round(mfa, 3)}%, MAE {round(mae, 3)}%, giveback {round(giveback, 3)}%.",
            "intended_entry": r.get("intended_entry") or r.get("entry_intent_price") or r.get("price"),
            "actual_entry": r.get("actual_entry") or r.get("entry_price") or r.get("avg_entry_price"),
            "intended_exit": r.get("intended_exit") or r.get("target") or r.get("target_price"),
            "actual_exit": r.get("actual_exit") or r.get("exit_price"),
            "realized_outcome": ret,
            "estimated_better_alternative_path": "hold_to_mfe_or_reduce_giveback" if giveback > 0 else "entry_and_exit_path_reasonable",
            "estimated_worse_alternative_path": "larger_loss_if_mae_not_contained" if mae > 0 else "insufficient_adverse_path_data",
            "replay_counterfactual_summary": f"Better path estimate: reduce giveback {round(giveback, 3)}%; worse path estimate: adverse excursion {round(mae, 3)}%.",
            "replay_hold_duration_quality": round(hold_quality, 2),
            "replay_timing_quality": round(timing_quality, 2),
            "lifecycle_id": lifecycle_id,
            "lifecycle_stage": lifecycle_stage,
            "lifecycle_duration_minutes": round(hold_hours * 60.0, 2),
            "lifecycle_hold_quality": round(hold_quality, 2),
            "lifecycle_exit_quality": round(exit_quality, 2),
            "lifecycle_profit_efficiency": round(_clamp((ret / max(0.01, mfa)) * 100.0 if mfa > 0 else (65.0 if ret >= 0 else 35.0)), 2),
            "lifecycle_risk_efficiency": round(_clamp(100.0 - mae * 8.0 + max(0.0, ret) * 2.0), 2),
            "replay_lifecycle_expectancy_learning_v1": True,
            "adaptive_policy_shadow_only": True,
            "adaptive_policy_auto_apply_allowed": False,
            "human_review_required": True,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in [dict(r) for r in (rows or []) if isinstance(r, dict)][:120]:
            try:
                row.update(self.score_row(row))
            except Exception:
                row.update(
                    {
                        "replay_learning_score": 50.0,
                        "replay_outcome_label": "weak_replay_outcome",
                        "lifecycle_stage": "candidate",
                        "expectancy_score": 50.0,
                        "adaptive_policy_shadow_only": True,
                        "adaptive_policy_auto_apply_allowed": False,
                        "human_review_required": True,
                        "natural_exit_preserved": True,
                        "forced_early_exit_enabled": False,
                    }
                )
            out.append(row)
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
        out["replay_lifecycle_expectancy_learning_v1"] = True
        out["replay_lifecycle_expectancy_summary"] = self.status(rows=rows)
        return out

    def _policy_recommendation(self, expectancy: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> tuple[str, str, str]:
        weak = sorted(expectancy.items(), key=lambda kv: kv[1].get("score", 50.0))
        strong = sorted(expectancy.items(), key=lambda kv: kv[1].get("score", 50.0), reverse=True)
        concentration = Counter(_safe_text(r.get("candidate_universe_tier"), "unknown") for r in rows)
        total = max(1, len(rows))
        mega_share = concentration.get("mega_cap", 0) / total
        if mega_share > 0.75:
            return "slightly_reduce_concentration", f"Mega-cap candidate share is {round(mega_share * 100, 1)}%; keep change shadow-only.", "conservative_shadow_review"
        if weak and weak[0][1].get("score", 50.0) < 38.0:
            return "reduce_weak_archetype_weight", f"Weakest archetype {weak[0][0]} has score {weak[0][1].get('score')}.", "conservative_shadow_review"
        if strong and strong[0][1].get("score", 50.0) > 68.0:
            return "increase_high_expectancy_weight", f"Strongest archetype {strong[0][0]} has score {strong[0][1].get('score')}.", "conservative_shadow_review"
        return "tighten_entry_confirmation", "Outcome evidence is still thin; prefer confirmation quality over expansion.", "conservative_shadow_review"

    def status(self, rows: list[dict[str, Any]] | None = None, paper_trace: dict[str, Any] | None = None) -> dict[str, Any]:
        candidate_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        history = self._rows()
        combined = (candidate_rows + history)[-MAX_ROWS:]
        decorated = self.decorate_candidates(combined)
        completed = [r for r in decorated if _stage(r) in {"closed", "replay_reviewed"} or self._return_pct(r) != 0.0]
        expectancy = self._expectancy_stats(completed or decorated, "archetype")
        expectancy_by_lane = self._expectancy_stats(completed or decorated, "allocation_lane")
        expectancy_by_horizon = self._expectancy_stats(completed or decorated, "horizon")
        sorted_exp = sorted(expectancy.items(), key=lambda kv: kv[1].get("score", 50.0), reverse=True)
        top_arch = sorted_exp[0][0] if sorted_exp else "insufficient_data"
        weak_arch = sorted_exp[-1][0] if sorted_exp else "insufficient_data"
        stable_arch = max(expectancy.items(), key=lambda kv: kv[1].get("consistency", 0.0))[0] if expectancy else "insufficient_data"
        unstable_arch = min(expectancy.items(), key=lambda kv: kv[1].get("consistency", 100.0))[0] if expectancy else "insufficient_data"
        replay_scores = [_score01(r.get("replay_learning_score"), 50.0) for r in decorated]
        lifecycle_scores = [_score01(r.get("lifecycle_hold_quality"), 50.0) for r in decorated]
        expectancy_scores = [v.get("score", 50.0) for v in expectancy.values()] or [50.0]
        sample_size = len(completed)
        win_values = [self._return_pct(r) for r in completed]
        wins = [v for v in win_values if v > 0]
        losses = [abs(v) for v in win_values if v < 0]
        win_rate = (len(wins) / max(1, len(win_values))) * 100.0 if win_values else 0.0
        avg_return = mean(win_values) if win_values else 0.0
        profit_factor = sum(wins) / sum(losses) if sum(losses) > 0 else (sum(wins) if wins else 0.0)
        consistency = _clamp(100.0 - (pstdev(win_values) * 80.0 if len(win_values) > 1 else 45.0))
        expectancy_score = _clamp(45.0 + avg_return * 12.0 + (win_rate - 50.0) * 0.30 + min(profit_factor, 3.0) * 8.0 + consistency * 0.18)
        policy_rec, policy_reason, policy_label = self._policy_recommendation(expectancy, candidate_rows)
        policy_conf = _clamp(min(sample_size, 150) / 150.0 * 55.0 + len(expectancy) * 5.0 + 20.0)
        replay_maturity = _clamp((mean(replay_scores) if replay_scores else 50.0) * 0.45 + min(len(decorated), 200) / 200.0 * 35.0 + 20.0)
        lifecycle_quality = _clamp((mean(lifecycle_scores) if lifecycle_scores else 50.0) * 0.55 + min(len(history), 250) / 250.0 * 35.0 + 10.0)
        expectancy_maturity = _clamp(expectancy_score * 0.50 + min(sample_size, 150) / 150.0 * 40.0 + 10.0)
        policy_readiness = _clamp(policy_conf * 0.55 + expectancy_maturity * 0.35 + 10.0)
        adaptive_maturity = _clamp(replay_maturity * 0.28 + lifecycle_quality * 0.24 + expectancy_maturity * 0.28 + policy_readiness * 0.20)
        replay_label = "acceptable_replay_outcome"
        if decorated:
            replay_label = Counter(_safe_text(r.get("replay_outcome_label"), "weak_replay_outcome") for r in decorated).most_common(1)[0][0]
        strongest_signal = f"{top_arch}:{round(expectancy.get(top_arch, {}).get('score', expectancy_score), 1)}"
        weakest_signal = f"{weak_arch}:{round(expectancy.get(weak_arch, {}).get('score', expectancy_score), 1)}"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_learning",
            "replay_lifecycle_expectancy_status_v1": True,
            "replay_learning_score": round(mean(replay_scores), 2) if replay_scores else 50.0,
            "replay_confidence": round(_clamp(min(len(decorated), 180) / 180.0 * 60.0 + 30.0), 2),
            "replay_outcome_quality": round(mean([_score01(r.get("replay_outcome_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "replay_trade_quality": round(mean([_score01(r.get("replay_trade_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "replay_outcome_label": replay_label,
            "replay_recommendation": "continue_shadow_replay_learning",
            "replay_improvement_reason": "Compare intended path, actual lifecycle path, and MFE/MAE counterfactuals without forcing exits.",
            "replay_counterfactual_summary": "Counterfactuals estimate better path from MFE/giveback and worse path from adverse excursion; no tick replay active yet.",
            "replay_hold_duration_quality": round(mean(lifecycle_scores), 2) if lifecycle_scores else 50.0,
            "replay_timing_quality": round(mean([_score01(r.get("replay_timing_quality"), 50.0) for r in decorated]), 2) if decorated else 50.0,
            "replay_learning_ready": bool(decorated or history),
            "lifecycle_tracking_ready": True,
            "lifecycle_stage_distribution": dict(Counter(_safe_text(r.get("lifecycle_stage"), "candidate") for r in decorated)),
            "lifecycle_tracking_quality_score": round(lifecycle_quality, 2),
            "lifecycle_summary": f"Tracked {len(decorated)} rows across lifecycle stages; completed sample {sample_size}.",
            "expectancy_learning_ready": bool(expectancy),
            "expectancy_score": round(expectancy_score, 2),
            "expectancy_confidence": round(_clamp(min(sample_size, 150) / 150.0 * 70.0 + 20.0), 2),
            "expectancy_sample_size": int(sample_size),
            "expectancy_profit_factor": round(profit_factor, 4),
            "expectancy_win_rate": round(win_rate, 2),
            "expectancy_avg_return": round(avg_return, 4),
            "expectancy_survivability": round(_clamp(consistency * 0.6 + expectancy_score * 0.4), 2),
            "expectancy_consistency": round(consistency, 2),
            "expectancy_label": _expectancy_label(expectancy_score),
            "expectancy_by_archetype": expectancy,
            "expectancy_by_allocation_lane": expectancy_by_lane,
            "expectancy_by_horizon": expectancy_by_horizon,
            "top_expectancy_archetype": top_arch,
            "weakest_expectancy_archetype": weak_arch,
            "most_stable_archetype": stable_arch,
            "most_unstable_archetype": unstable_arch,
            "adaptive_policy_ready": True,
            "regime_execution_survivability_hooks_ready": bool(self.regime_execution_survivability is not None),
            "adaptive_execution_exit_v2_hooks_ready": bool(self.adaptive_execution_exit_v2 is not None),
            "portfolio_diversification_v2_hooks_ready": bool(self.portfolio_diversification_v2 is not None),
            "adaptive_policy_score": round(policy_readiness, 2),
            "adaptive_policy_confidence": round(policy_conf, 2),
            "adaptive_policy_recommendation": policy_rec,
            "current_policy_recommendation": policy_rec,
            "adaptive_policy_reason": policy_reason,
            "current_policy_reason": policy_reason,
            "adaptive_policy_safety_label": policy_label,
            "adaptive_policy_shadow_only": True,
            "adaptive_policy_auto_apply_allowed": False,
            "human_review_required": True,
            "learning_loop_summary": f"Replay/lifecycle/expectancy loop ready; strongest signal {strongest_signal}, weakest signal {weakest_signal}.",
            "strongest_learning_signal": strongest_signal,
            "weakest_learning_signal": weakest_signal,
            "highest_expectancy_condition": top_arch,
            "weakest_expectancy_condition": weak_arch,
            "most_improved_archetype": stable_arch,
            "worst_recent_archetype": weak_arch,
            "adaptive_learning_direction": policy_rec,
            "recurring_failures": dict(Counter(_safe_text(r.get("replay_outcome_label"), "unknown") for r in decorated).most_common(6)),
            "recurring_winners": dict(Counter(self._group_key(r, "archetype") for r in completed if self._return_pct(r) > 0).most_common(6)),
            "repeat_bad_timing": dict(Counter(self._group_key(r, "session_timing") for r in decorated if _score01(r.get("replay_timing_quality"), 50.0) < 45.0).most_common(6)),
            "repeat_successful_timing": dict(Counter(self._group_key(r, "session_timing") for r in completed if self._return_pct(r) > 0).most_common(6)),
            "recurring_concentration_issues": dict(Counter(_safe_text(r.get("candidate_universe_tier"), "unknown") for r in candidate_rows).most_common(6)),
            "regime_mismatch_frequency": 0,
            "volatility_mismatch_frequency": 0,
            "adaptive_learning_maturity_score": round(adaptive_maturity, 2),
            "replay_learning_maturity_score": round(replay_maturity, 2),
            "expectancy_learning_maturity_score": round(expectancy_maturity, 2),
            "adaptive_policy_readiness_score": round(policy_readiness, 2),
            "adaptive_learning_maturity_label": _maturity_label(adaptive_maturity),
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
            "autonomous_ai_execution_allowed": False,
            "ai_execution_authority": False,
            "updated_at": _now_iso(),
        }
