from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.profit_seeking_adaptive_exploration_v1 import ProfitSeekingAdaptiveExplorationV1
except Exception:  # pragma: no cover - additive hook
    ProfitSeekingAdaptiveExplorationV1 = None  # type: ignore[assignment]

try:
    from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract
except Exception:  # pragma: no cover - allocation works without metadata enrichment
    def apply_trade_lane_contract(row: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return dict(row or {})

try:
    from engine.astra_multilane_activation_v2 import canonical_lane_activation_contract
except Exception:  # pragma: no cover - fail closed if the shared owner is unavailable
    def canonical_lane_activation_contract(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "lane_enabled": False,
            "execution_enabled": False,
            "activation_contract_consistent": False,
            "exact_blockers": ["ACTIVATION_CONTRACT_UNAVAILABLE"],
        }

VERSION = "1.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 1_000
CORE_TARGET = 0.55
MOMENTUM_TARGET = 0.30
EXPLORATION_TARGET = 0.15
RANKED_ENTRY_LANES = ("SCALP", "DAY", "SWING")
LANE_SHORTLIST_LIMIT = 40
LANE_FINALIST_LIMIT = 10
LANE_HISTORY_LIMITS = {"SCALP": 3, "DAY": 5, "SWING": 8}
MAX_RANK_STATE_SYMBOLS_PER_LANE = 80

MEGA_CAP_SYMBOL_FALLBACK = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "AVGO", "BRK.B",
    "BRK-A", "LLY", "JPM", "V", "MA", "COST", "WMT", "NFLX", "ORCL", "XOM",
}


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


def _market_cap_bucket(row: dict[str, Any]) -> str:
    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
    raw = _safe_text(
        row.get("candidate_universe_tier")
        or row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization") or row.get("marketCap"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000 or symbol in MEGA_CAP_SYMBOL_FALLBACK:
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


class PaperOpportunityAllocationEngineV1:
    """Paper-only lane allocation and exploration scorer.

    This engine only decorates and orders paper candidates. It does not change
    live trading, broker mode, exits, provider logic, or safety gates.
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self.ranked_entry_state_path = os.path.join(self.state_dir, "paper_opportunity_allocation_rank_state_v1.json")
        self.ranked_entry_cohort_path = os.path.join(self.state_dir, "lane_ranked_entry_funnel_v1.json")
        self._outcome_cache: dict[str, Any] | None = None
        self.profit_seeking_exploration = (
            ProfitSeekingAdaptiveExplorationV1(state_dir=self.state_dir) if ProfitSeekingAdaptiveExplorationV1 is not None else None
        )

    @staticmethod
    def _real_percent(row: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = row.get(key)
            if value in (None, ""):
                continue
            try:
                return float(str(value).replace("%", "").strip())
            except Exception:
                continue
        return None

    @staticmethod
    def _optional_score(row: dict[str, Any], *keys: str) -> tuple[float | None, str]:
        for key in keys:
            if row.get(key) not in (None, ""):
                return _score01(row.get(key)), key
        return None, ""

    @staticmethod
    def _candidate_lane(row: dict[str, Any]) -> str:
        if _safe_text(row.get("asset_type") or row.get("asset_class")).lower() in {"crypto", "cryptocurrency"}:
            return ""
        lane = _safe_text(row.get("lane_id") or row.get("lane")).upper()
        if lane in RANKED_ENTRY_LANES:
            return lane
        horizon = _safe_text(row.get("best_horizon_style") or row.get("trade_horizon_style")).lower()
        return {"scalp": "SCALP", "day_trade": "DAY", "swing_trade": "SWING"}.get(horizon, "")

    def _load_rank_state(self) -> dict[str, Any]:
        try:
            with open(self.ranked_entry_state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_rank_state(self, payload: dict[str, Any]) -> None:
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            temp_path = f"{self.ranked_entry_state_path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
            os.replace(temp_path, self.ranked_entry_state_path)
        except OSError:
            pass

    def _ranked_entry_cohort(self) -> dict[str, Any]:
        try:
            with open(self.ranked_entry_cohort_path, "r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if isinstance(existing, dict) and existing.get("change_id") == "LANE_RANKED_ENTRY_FUNNEL_V1":
                return existing
        except Exception:
            pass
        marker = {
            "change_id": "LANE_RANKED_ENTRY_FUNNEL_V1",
            "activated_at": _now_iso(),
            "scope": list(RANKED_ENTRY_LANES),
            "measurement_checkpoints": [10, 20, 30],
            "mode": "paper_only_soft_ranking_evidence",
        }
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            with open(self.ranked_entry_cohort_path, "w", encoding="utf-8") as handle:
                json.dump(marker, handle, separators=(",", ":"), sort_keys=True)
        except OSError:
            pass
        return marker

    def _features(self, row: dict[str, Any]) -> dict[str, float | str | bool]:
        r = dict(row or {})
        predicted_profit = _first_number(r, ("predicted_profit_percent", "expected_return_percent", "expected_return_pct", "profit_prediction_pct", "expected_move_percent"), 0.0)
        confidence = _score01(r.get("confidence"), _score01(r.get("predicted_win_probability"), 52.0))
        entry_quality = _score01(
            r.get("entry_quality_v3_score"),
            _score01(r.get("entry_quality_v2_score"), _score01(r.get("entry_filter_v2_score"), _score01(r.get("entry_quality_score"), 52.0))),
        )
        aggressive_profit = _score01(r.get("aggressive_profit_score"), _clamp(45.0 + max(0.0, predicted_profit) * 6.0))
        risk_adjusted_profit = _score01(
            r.get("risk_adjusted_profit_score"),
            _clamp((aggressive_profit * 0.32) + (confidence * 0.28) + (entry_quality * 0.24) + (_score01(r.get("portfolio_risk_score"), 58.0) * 0.16)),
        )
        momentum = _score01(r.get("momentum_expansion_score"), _score01(r.get("momentum_score"), 50.0))
        breakout = _score01(r.get("breakout_probability_score"), 50.0)
        accel = _score01(r.get("intraday_acceleration_score"), 50.0)
        volatility = _score01(r.get("volatility_expansion_score"), _score01(r.get("volatility_score"), 50.0))
        liquidity = _score01(r.get("liquidity_score"), _score01(r.get("data_quality_score"), 58.0))
        execution = _score01(r.get("execution_readiness_score"), _score01(r.get("order_execution_score"), 58.0))
        portfolio_risk = _score01(r.get("portfolio_risk_score"), 58.0)
        drawdown_risk = _score01(r.get("drawdown_risk_score"), 35.0)
        cap = _market_cap_bucket(r)
        high_upside = bool(r.get("high_upside_candidate")) or predicted_profit >= 4.0 or aggressive_profit >= 68.0
        opportunity_type = _safe_text(r.get("candidate_opportunity_type") or r.get("candidate_discovery_reason")).lower()
        momentum_candidate = (
            bool(r.get("momentum_runner"))
            or "momentum" in opportunity_type
            or "breakout" in opportunity_type
            or momentum >= 58.0
            or breakout >= 62.0
            or accel >= 62.0
            or bool(r.get("unusual_volume"))
        )
        risk_minimums = bool(confidence >= 48.0 and entry_quality >= 44.0 and liquidity >= 42.0 and execution >= 42.0 and portfolio_risk >= 35.0 and drawdown_risk <= 82.0)
        exploration_allowed = bool(risk_minimums and high_upside and cap in {"mid_cap", "small_cap", "micro_cap", "unknown"})
        if risk_minimums and high_upside and cap == "mega_cap" and momentum_candidate:
            exploration_allowed = True
        if not risk_minimums:
            rejection = "risk_quality_minimums_not_met"
        elif not high_upside and not momentum_candidate:
            rejection = "not_high_upside_or_momentum"
        elif cap in {"mega_cap", "large_cap"} and not momentum_candidate:
            rejection = "not_exploration_tier"
        else:
            rejection = ""
        if exploration_allowed and high_upside and cap in {"mid_cap", "small_cap", "micro_cap", "unknown"}:
            lane = "high_upside_exploration"
            lane_score = _clamp((risk_adjusted_profit * 0.34) + (aggressive_profit * 0.28) + (momentum * 0.18) + (liquidity * 0.10) + (execution * 0.10))
            reason = "controlled high-upside paper exploration with risk minimums satisfied"
        elif momentum_candidate:
            lane = "momentum_opportunity"
            lane_score = _clamp((risk_adjusted_profit * 0.34) + (momentum * 0.24) + (breakout * 0.16) + (accel * 0.12) + (liquidity * 0.14))
            reason = "momentum/breakout paper lane candidate"
        else:
            lane = "core_quality"
            lane_score = _clamp((risk_adjusted_profit * 0.44) + (confidence * 0.22) + (entry_quality * 0.18) + (liquidity * 0.08) + (portfolio_risk * 0.08))
            reason = "core risk-adjusted paper quality lane"
        risk_label = "controlled"
        if not risk_minimums:
            risk_label = "blocked_quality_risk"
        elif drawdown_risk >= 68.0 or liquidity < 50.0:
            risk_label = "elevated_watch"
        elif exploration_allowed:
            risk_label = "controlled_exploration"
        priority = _clamp((lane_score * 0.58) + (risk_adjusted_profit * 0.28) + (aggressive_profit * 0.14))
        if lane == "high_upside_exploration":
            priority = _clamp(priority + 4.0)
        elif lane == "momentum_opportunity":
            priority = _clamp(priority + 2.0)
        horizon = _safe_text(r.get("best_horizon_style") or r.get("trade_horizon_style") or r.get("best_discovery_horizon"), "day_trade")
        return {
            "predicted_profit_percent": round(predicted_profit, 4),
            "confidence": confidence,
            "entry_quality": entry_quality,
            "aggressive_profit_score": aggressive_profit,
            "risk_adjusted_profit_score": risk_adjusted_profit,
            "momentum_expansion_score": momentum,
            "breakout_probability_score": breakout,
            "volatility_expansion_score": volatility,
            "liquidity_score": liquidity,
            "execution_readiness_score": execution,
            "portfolio_risk_score": portfolio_risk,
            "candidate_universe_tier": cap,
            "best_horizon_style": horizon,
            "allocation_lane": lane,
            "allocation_lane_score": round(lane_score, 2),
            "allocation_reason": reason,
            "exploration_candidate": bool(lane in {"momentum_opportunity", "high_upside_exploration"}),
            "exploration_risk_label": risk_label,
            "exploration_allowed": bool(exploration_allowed or (lane == "momentum_opportunity" and risk_minimums)),
            "exploration_rejection_reason": rejection,
            "risk_adjusted_opportunity_rank": 0,
            "paper_allocation_priority": round(priority, 2),
        }

    def _relative_strength_evidence(
        self,
        row: dict[str, Any],
        *,
        market_return_pct: float | None,
        sector_return_pct: float | None,
    ) -> dict[str, Any]:
        symbol_return = self._real_percent(
            row,
            "relative_return_pct",
            "change_percent",
            "changesPercentage",
            "changePercentage",
            "intraday_change_pct",
            "day_change_pct",
        )
        if symbol_return is None or market_return_pct is None:
            market_score, market_state, market_delta = None, "UNAVAILABLE", None
        else:
            market_delta = round(symbol_return - market_return_pct, 4)
            market_score = round(_clamp(50.0 + (market_delta * 10.0)), 3)
            market_state = "AVAILABLE"
        if symbol_return is None or sector_return_pct is None:
            sector_score, sector_state, sector_delta = None, "UNAVAILABLE", None
        else:
            sector_delta = round(symbol_return - sector_return_pct, 4)
            sector_score = round(_clamp(50.0 + (sector_delta * 10.0)), 3)
            sector_state = "AVAILABLE"
        return {
            "relative_strength_market_score": market_score,
            "relative_strength_market_delta_pct": market_delta,
            "relative_strength_sector_score": sector_score,
            "relative_strength_sector_delta_pct": sector_delta,
            "relative_strength_state": "AVAILABLE" if market_state == "AVAILABLE" else "UNAVAILABLE",
            "relative_strength_sector_state": sector_state,
        }

    def _lane_soft_evidence(
        self,
        row: dict[str, Any],
        lane: str,
        relative_strength: dict[str, Any],
    ) -> dict[str, Any]:
        rvol, rvol_source = self._optional_score(row, "relative_volume_score", "rvol_score")
        if rvol is None:
            current_volume = _to_float(row.get("volume"), 0.0)
            average_volume = _to_float(row.get("average_volume") or row.get("averageVolume") or row.get("volAvg"), 0.0)
            if current_volume > 0.0 and average_volume > 0.0:
                ratio = current_volume / average_volume
                rvol = round(_clamp(50.0 + (min(3.0, max(0.0, ratio)) - 1.0) * 25.0), 3)
                rvol_source = "volume_over_average_volume"
        extension, extension_source = self._optional_score(
            row,
            "entry_extension_quality_score",
            "entry_extension_score",
            "pullback_quality_score",
        )
        if extension is None:
            chase_risk, chase_source = self._optional_score(row, "entry_extension_risk_score", "chase_risk_score")
            if chase_risk is not None:
                extension, extension_source = round(100.0 - chase_risk, 3), f"inverse_{chase_source}"
        spread, spread_source = self._optional_score(row, "spread_quality_score", "execution_quality_score")
        freshness, freshness_source = self._optional_score(row, "freshness_quality_score", "quote_freshness_score")
        relative_strength_score = relative_strength.get("relative_strength_market_score")
        if lane == "SCALP":
            lane_fit, lane_fit_source = self._optional_score(row, "scalp_fit_score", "short_horizon_fit_score")
            signals = [
                self._optional_score(row, "intraday_acceleration_score", "momentum_expansion_score", "momentum_score")[0],
                rvol, spread, freshness, extension,
            ]
        elif lane == "DAY":
            lane_fit, lane_fit_source = self._optional_score(row, "day_trade_fit_score", "intraday_fit_score")
            signals = [
                self._optional_score(row, "trend_quality_score", "momentum_expansion_score", "momentum_score")[0],
                rvol, relative_strength_score, extension, freshness,
            ]
        else:
            lane_fit, lane_fit_source = self._optional_score(row, "swing_trade_fit_score", "swing_fit_score", "multi_day_fit_score")
            signals = [
                self._optional_score(row, "trend_persistence_score", "trend_quality_score", "momentum_score")[0],
                relative_strength_score, extension,
                self._optional_score(row, "expected_return_score", "risk_reward_score", "risk_adjusted_profit_score")[0],
            ]
        available = [float(value) for value in signals if value is not None]
        soft_mean = round(mean(available), 3) if available else None
        # A small neutral-centered adjustment keeps the established allocator
        # primary while allowing lane-fit evidence to resolve close candidates.
        adjustment_inputs = [value for value in (lane_fit, soft_mean) if value is not None]
        adjustment = round(_clamp((mean(adjustment_inputs) - 50.0) * 0.06, -3.0, 3.0), 3) if adjustment_inputs else 0.0
        return {
            "lane_fit_score": lane_fit,
            "lane_fit_score_source": lane_fit_source,
            "lane_soft_evidence_score": soft_mean,
            "lane_soft_evidence_count": len(available),
            "lane_soft_ranking_adjustment": adjustment,
            "relative_volume_score": rvol,
            "relative_volume_source": rvol_source or "UNAVAILABLE",
            "entry_extension_quality_score": extension,
            "entry_extension_source": extension_source or "UNAVAILABLE",
            "spread_quality_score": spread,
            "spread_quality_source": spread_source or "UNAVAILABLE",
            "freshness_quality_score": freshness,
            "freshness_quality_source": freshness_source or "UNAVAILABLE",
        }

    def _ranked_entry_decorations(self, decorated: list[dict[str, Any]]) -> list[dict[str, Any]]:
        market_return = None
        for row in decorated:
            if _safe_text(row.get("symbol")).upper() == "SPY":
                market_return = self._real_percent(row, "change_percent", "changesPercentage", "changePercentage")
                break
        sector_returns: dict[str, list[float]] = defaultdict(list)
        for row in decorated:
            sector = _safe_text(row.get("sector")).lower()
            value = self._real_percent(row, "change_percent", "changesPercentage", "changePercentage")
            if sector and value is not None:
                sector_returns[sector].append(value)
        sector_benchmarks = {
            sector: mean(values) for sector, values in sector_returns.items() if len(values) >= 2
        }
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        passthrough: list[dict[str, Any]] = []
        for row in decorated:
            lane = self._candidate_lane(row)
            if lane not in RANKED_ENTRY_LANES:
                passthrough.append(row)
                continue
            sector = _safe_text(row.get("sector")).lower()
            relative_strength = self._relative_strength_evidence(
                row,
                market_return_pct=market_return,
                sector_return_pct=sector_benchmarks.get(sector),
            )
            soft = self._lane_soft_evidence(row, lane, relative_strength)
            base_priority = _to_float(row.get("paper_allocation_priority"), 0.0)
            enriched = {
                **row,
                **relative_strength,
                **soft,
                "lane_ranked_entry_funnel_v1": True,
                "lane_ranked_entry_lane": lane,
                "base_paper_allocation_priority": round(base_priority, 3),
                "lane_ranked_entry_score": round(base_priority + _to_float(soft.get("lane_soft_ranking_adjustment"), 0.0), 3),
            }
            grouped[lane].append(enriched)

        state = self._load_rank_state()
        lane_state = dict(state.get("lanes") or {})
        epoch_seconds = max(60, min(900, int(float(os.getenv("ASTRA_DISCOVERY_ROTATION_SECONDS", "300")))))
        epoch = int(datetime.now(timezone.utc).timestamp() // epoch_seconds)
        result: list[dict[str, Any]] = list(passthrough)
        for lane, rows in grouped.items():
            prior_symbols = dict((lane_state.get(lane) or {}).get("symbols") or {})
            for row in rows:
                history = list((prior_symbols.get(_safe_text(row.get("symbol")).upper()) or {}).get("history") or [])
                recent = [entry for entry in history if isinstance(entry, dict)][-LANE_HISTORY_LIMITS[lane]:]
                prior_avg = mean([_to_float(entry.get("rank"), 0.0) for entry in recent]) if recent else None
                stability = 0.0
                if prior_avg is not None and prior_avg <= 5.0:
                    stability = 0.75
                elif prior_avg is not None and prior_avg <= 10.0:
                    stability = 0.35
                row["rank_persistence_observations"] = len(recent)
                row["rank_recent_average"] = round(prior_avg, 3) if prior_avg is not None else None
                row["rank_stability_adjustment"] = stability
                row["lane_ranked_entry_score"] = round(_to_float(row.get("lane_ranked_entry_score"), 0.0) + stability, 3)
            rows.sort(key=lambda row: (_to_float(row.get("lane_ranked_entry_score"), 0.0), _to_float(row.get("base_paper_allocation_priority"), 0.0)), reverse=True)
            next_symbols: dict[str, Any] = {}
            for rank, row in enumerate(rows[:LANE_SHORTLIST_LIMIT], start=1):
                symbol = _safe_text(row.get("symbol")).upper()
                prior = dict(prior_symbols.get(symbol) or {})
                history = [entry for entry in (prior.get("history") or []) if isinstance(entry, dict)]
                if not history or int(_to_float(history[-1].get("epoch"), -1)) != epoch:
                    history.append({"epoch": epoch, "rank": rank, "score": _to_float(row.get("lane_ranked_entry_score"), 0.0)})
                else:
                    history[-1] = {"epoch": epoch, "rank": rank, "score": _to_float(row.get("lane_ranked_entry_score"), 0.0)}
                history = history[-LANE_HISTORY_LIMITS[lane]:]
                ranks = [_to_float(item.get("rank"), 0.0) for item in history]
                current_state = "NEW_CANDIDATE" if len(history) < 2 else "STABLE_LEADER" if mean(ranks) <= 5.0 else "STABLE_CONTENDER" if mean(ranks) <= 10.0 else "FADING_CANDIDATE" if rank > mean(ranks) + 3.0 else "RISING_CANDIDATE"
                row["lane_shortlist_rank"] = rank
                row["lane_finalist_rank"] = rank if rank <= LANE_FINALIST_LIMIT else None
                row["lane_finalist"] = bool(rank <= LANE_FINALIST_LIMIT)
                row["rank_persistence_state"] = current_state
                row["finalist_is_not_execution_authority"] = True
                # Existing PaperAutopilot ordering consumes this canonical
                # priority. The bounded adjustment is ranking-only and does
                # not alter any qualification or execution gate.
                row["paper_allocation_priority"] = _to_float(row.get("lane_ranked_entry_score"), 0.0)
                next_symbols[symbol] = {"history": history, "last_seen_epoch": epoch}
            lane_state[lane] = {"symbols": dict(list(next_symbols.items())[:MAX_RANK_STATE_SYMBOLS_PER_LANE]), "last_epoch": epoch}
            result.extend(rows)
        state = {"version": VERSION, "lanes": lane_state, "updated_at": _now_iso(), "bounded": True}
        self._write_rank_state(state)
        return result

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = self._features(row)
        out["paper_opportunity_allocation_engine_v1"] = True
        out["api_calls_used"] = 0
        out["live_trading_changed"] = False
        return out

    def decorate_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        decorated: list[dict[str, Any]] = []
        for row in rows[:300]:
            if not isinstance(row, dict):
                continue
            lane_row = apply_trade_lane_contract(row, legacy=False)
            scored = self.score_row(lane_row)
            decorated.append({**lane_row, **scored})
        decorated = self._ranked_entry_decorations(decorated)
        decorated.sort(
            key=lambda r: (
                _to_float(r.get("paper_allocation_priority"), 0.0),
                _to_float(r.get("risk_adjusted_profit_score"), 0.0),
            ),
            reverse=True,
        )
        for idx, row in enumerate(decorated, start=1):
            row["risk_adjusted_opportunity_rank"] = idx
        return decorated

    def day_lane_governance(
        self,
        rows: list[dict[str, Any]] | None = None,
        open_positions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Explain DAY-lane diversity without selecting, blocking, or trading.

        The existing allocation engine remains authoritative for candidate
        decoration.  This view keeps quality-first selection intact and reports
        what existing duplicate/concentration rules would need to review.
        """
        decorated = self.decorate_candidates([dict(row) for row in (rows or []) if isinstance(row, dict)])
        day_rows = [row for row in decorated if str(row.get("lane_id") or "").upper() == "DAY"]
        positions = [apply_trade_lane_contract(row, legacy=True) for row in (open_positions or []) if isinstance(row, dict)]
        open_symbols = {str(row.get("symbol") or row.get("ticker") or "").upper() for row in positions}
        rejected: Counter[str] = Counter()
        eligible: list[dict[str, Any]] = []
        selected: list[dict[str, Any]] = []
        for row in day_rows:
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            if symbol and symbol in open_symbols:
                rejected["DUPLICATE_SYMBOL_CROSS_LANE"] += 1
                continue
            if not bool(row.get("exploration_allowed", True)):
                rejected[str(row.get("exploration_rejection_reason") or "QUALITY_FILTER_REJECTED").upper()] += 1
                continue
            eligible.append(row)
            if bool(row.get("selected") or row.get("paper_ready")):
                selected.append(row)
        breakdown = lambda key: dict(Counter(str(row.get(key) or "UNCLASSIFIED") for row in eligible))
        controls = {
            "one_symbol": 1,
            "one_sector": int(os.getenv("ASTRA_DAY_LANE_SECTOR_CEILING", "2") or 2),
            "one_industry": int(os.getenv("ASTRA_DAY_LANE_INDUSTRY_CEILING", "2") or 2),
            "one_strategy_cohort": int(os.getenv("ASTRA_DAY_LANE_COHORT_CEILING", "2") or 2),
            "one_correlation_cluster": int(os.getenv("ASTRA_DAY_LANE_CLUSTER_CEILING", "2") or 2),
            "one_etf_theme": int(os.getenv("ASTRA_DAY_LANE_ETF_THEME_CEILING", "1") or 1),
            "one_source_model": int(os.getenv("ASTRA_DAY_LANE_SOURCE_MODEL_CEILING", "2") or 2),
        }
        # The multi-lane contract is the sole DAY activation authority.  This
        # allocator only reports the contract; PaperAutopilot still owns every
        # real eligibility, session, and broker submission gate.
        activation = canonical_lane_activation_contract("DAY", os.environ)
        return {
            "day_lane_enabled": bool(activation.get("lane_enabled")),
            "day_lane_execution_enabled": bool(activation.get("execution_enabled")),
            "day_lane_activation_contract": activation,
            "capital_book_id": "paper_day_learning",
            "candidate_supply": len(day_rows),
            "eligible_candidate_supply": len(eligible),
            "selected_candidates": len(selected),
            "completed_entries": 0,
            "completed_lifecycles": 0,
            "rejected_candidates": int(sum(rejected.values())),
            "rejection_reasons": dict(rejected),
            "breakdown": {
                "strategy_cohort": breakdown("strategy_cohort"),
                "symbol": breakdown("symbol"),
                "sector": breakdown("sector"),
                "industry": breakdown("industry"),
                "asset_class": breakdown("asset_class"),
                "regime": breakdown("market_regime"),
                "catalyst": breakdown("catalyst"),
                "volatility": breakdown("volatility_bucket"),
                "liquidity": breakdown("liquidity_bucket"),
                "correlation_cluster": breakdown("correlation_cluster_label"),
                "source_ranking_version": breakdown("source_ranking_version"),
            },
            "diversity_ceilings": controls,
            "quality_over_mechanical_diversity": True,
            "ceiling_is_not_a_quota": True,
            "zero_qualifying_trades_valid": True,
            "cross_lane_exact_symbol_check": True,
            "same_session_close_posture": "advisory_only_existing_governance_retained",
            "rollback": {"available": True, "switch": "ASTRA_DAY_LANE_PILOT_ENABLED"},
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "behavior_safe_to_apply": False,
            "paper_only_preserved": True,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
        }

    def _outcome_stats(self) -> dict[str, Any]:
        if self._outcome_cache is not None:
            return self._outcome_cache
        rows = []
        rows.extend(_tail_jsonl(self.lifecycle_path, 400))
        rows.extend(_tail_jsonl(self.labels_path, 400))
        by_lane: dict[str, list[float]] = defaultdict(list)
        wins: Counter[str] = Counter()
        totals: Counter[str] = Counter()
        horizon_lane: Counter[str] = Counter()
        for raw in rows[-MAX_ROWS:]:
            if not isinstance(raw, dict):
                continue
            lane = _safe_text(raw.get("allocation_lane") or raw.get("paper_allocation_lane"), "unknown")
            if lane == "unknown":
                continue
            ret = _first_number(raw, ("realized_return_pct", "return_percent", "return_pct", "pnl_pct"), 0.0)
            by_lane[lane].append(ret)
            totals[lane] += 1
            if ret > 0:
                wins[lane] += 1
            horizon = _safe_text(raw.get("trade_horizon_style") or raw.get("best_horizon_style"), "unknown")
            horizon_lane[f"{horizon}:{lane}"] += 1
        result: dict[str, Any] = {"lanes": {}, "horizon_lane_counts": dict(horizon_lane)}
        for lane in ("core_quality", "momentum_opportunity", "high_upside_exploration"):
            vals = by_lane.get(lane, [])
            result["lanes"][lane] = {
                "sample_size": int(totals.get(lane, 0)),
                "win_rate": round((wins.get(lane, 0) / max(1, totals.get(lane, 0))) * 100.0, 2) if totals.get(lane, 0) else None,
                "average_return_pct": round(mean(vals), 4) if vals else None,
                "profit_factor": None,
            }
        self._outcome_cache = result
        return result

    def recommended_weights(self) -> dict[str, Any]:
        stats = self._outcome_stats().get("lanes", {})
        sample_total = sum(int((stats.get(lane) or {}).get("sample_size") or 0) for lane in stats)
        if sample_total < 12:
            return {
                "recommended_core_lane_weight": 0.55,
                "recommended_momentum_lane_weight": 0.30,
                "recommended_exploration_lane_weight": 0.15,
                "allocation_adjustment_reason": "insufficient_lane_outcome_samples_keep_default_targets",
                "allocation_confidence": "low",
            }
        scores = {}
        for lane, base in (("core_quality", 0.55), ("momentum_opportunity", 0.30), ("high_upside_exploration", 0.15)):
            item = stats.get(lane) or {}
            wr = _to_float(item.get("win_rate"), 50.0)
            avg = _to_float(item.get("average_return_pct"), 0.0)
            scores[lane] = max(0.05, base + ((wr - 50.0) / 500.0) + (avg / 80.0))
        total = sum(scores.values()) or 1.0
        core = _clamp(scores["core_quality"] / total, 0.40, 0.70)
        momentum = _clamp(scores["momentum_opportunity"] / total, 0.15, 0.45)
        exploration = _clamp(1.0 - core - momentum, 0.05, 0.25)
        return {
            "recommended_core_lane_weight": round(core, 3),
            "recommended_momentum_lane_weight": round(momentum, 3),
            "recommended_exploration_lane_weight": round(exploration, 3),
            "allocation_adjustment_reason": "lane_outcome_weighting_shadow_review",
            "allocation_confidence": "medium" if sample_total >= 30 else "low",
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        decorated = self.decorate_candidates([dict(r) for r in (rows or []) if isinstance(r, dict)])
        lanes = Counter(str(r.get("allocation_lane") or "unknown") for r in decorated)
        cap_counts = Counter(str(r.get("candidate_universe_tier") or _market_cap_bucket(r)) for r in decorated)
        high_reviewed = [
            r for r in decorated
            if bool(r.get("high_upside_candidate"))
            or bool(r.get("exploration_candidate"))
            or _to_float(r.get("predicted_profit_percent"), 0.0) >= 4.0
            or _to_float(r.get("aggressive_profit_score"), 0.0) >= 68.0
        ]
        approved = [r for r in high_reviewed if bool(r.get("exploration_allowed"))]
        rejected = [r for r in high_reviewed if not bool(r.get("exploration_allowed"))]
        rejection_counts = Counter(str(r.get("exploration_rejection_reason") or "not_rejected") for r in rejected)
        total = len(decorated)
        mega = cap_counts.get("mega_cap", 0)
        rec = self.recommended_weights()
        summary = (
            f"Paper allocation lanes: core {lanes.get('core_quality', 0)}, momentum {lanes.get('momentum_opportunity', 0)}, "
            f"exploration {lanes.get('high_upside_exploration', 0)}. Valid exploration candidates {len(approved)}; "
            f"mega-cap concentration {(mega / max(1, total)) * 100.0:.1f}%."
        ) if total else "No paper candidates available for allocation review."
        ranked_entry_funnel: dict[str, dict[str, Any]] = {}
        for lane in RANKED_ENTRY_LANES:
            lane_rows = [row for row in decorated if str(row.get("lane_ranked_entry_lane") or "") == lane]
            shortlisted = [row for row in lane_rows if row.get("lane_shortlist_rank") is not None]
            finalists = [row for row in lane_rows if bool(row.get("lane_finalist"))]
            qualified = [row for row in finalists if bool(row.get("qualified") or row.get("eligible"))]
            selected = [row for row in finalists if bool(row.get("selected"))]
            order_ready = [row for row in finalists if bool(row.get("order_ready"))]
            ranked_entry_funnel[lane] = {
                "discovered": len(lane_rows),
                "lane_eligible": len(lane_rows),
                "shortlisted": len(shortlisted),
                "deep_ranked": len(shortlisted),
                "finalists": len(finalists),
                "qualified": len(qualified),
                "selected": len(selected),
                "order_ready": len(order_ready),
                "starvation_signal": "HEALTHY_DISCOVERY_NO_FINALIST" if lane_rows and not finalists else "NO_LANE_CANDIDATES" if not lane_rows else "NONE",
            }
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_allocation",
            "paper_opportunity_allocation_status_v1": True,
            "core_lane_target_pct": round(CORE_TARGET * 100.0, 1),
            "momentum_lane_target_pct": round(MOMENTUM_TARGET * 100.0, 1),
            "exploration_lane_target_pct": round(EXPLORATION_TARGET * 100.0, 1),
            "current_core_lane_count": int(lanes.get("core_quality", 0)),
            "current_momentum_lane_count": int(lanes.get("momentum_opportunity", 0)),
            "current_exploration_lane_count": int(lanes.get("high_upside_exploration", 0)),
            "valid_exploration_candidates": int(len(approved)),
            "high_upside_candidates_reviewed": int(len(high_reviewed)),
            "high_upside_candidates_approved": int(len(approved)),
            "high_upside_candidates_rejected": int(len(rejected)),
            "top_exploration_rejection_reasons": [{"reason": k, "count": v} for k, v in rejection_counts.most_common(5)],
            "mega_cap_concentration_pct": round((mega / max(1, total)) * 100.0, 2) if total else 0.0,
            "non_mega_candidate_count": int(total - mega),
            "lane_counts": dict(lanes),
            "lane_ranked_entry_funnel_v1": {
                "enabled": True,
                "shortlist_limit": LANE_SHORTLIST_LIMIT,
                "finalist_limit": LANE_FINALIST_LIMIT,
                "lanes": ranked_entry_funnel,
                "prospective_cohort": self._ranked_entry_cohort(),
                "ranking_only": True,
                "hard_gate_changes": False,
            },
            "day_lane_governance_v1": self.day_lane_governance(rows=decorated),
            "market_cap_distribution": dict(cap_counts),
            "allocation_summary": summary,
            **rec,
            "lane_outcome_stats": self._outcome_stats().get("lanes", {}),
            "profit_seeking_adaptive_exploration_hooks_ready": bool(self.profit_seeking_exploration is not None),
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_live_behavior_changed": False,
            "natural_exit_preserved": True,
            "forced_early_exit_enabled": False,
            "alpaca_paper_only_preserved": True,
            "generated_at": _now_iso(),
        }

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            pack_out = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = pack_out.get(section)
                if not isinstance(values, list):
                    continue
                pack_out[section] = self.decorate_candidates([dict(v) for v in values if isinstance(v, dict)])
            out[pack_key] = pack_out
        rows = _candidate_rows(out)
        out["paper_opportunity_allocation_engine_v1"] = True
        out["paper_opportunity_allocation_summary"] = self.status(rows=rows)
        return out
