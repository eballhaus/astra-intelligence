"""Lineage-gated, lane-separated counterfactual exit studies.

No order, exit, threshold, or broker mutation is performed here.  Results are
explicitly shadow simulations and only consume lifecycle rows whose entry
price is broker-confirmed and eligible for loss calibration.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any

LOSS_THRESHOLDS = (-2, -3, -4, -5, -6, -7, -8, -10)
PROFIT_TRIGGERS = (1, 2, 3, 5)
GIVEBACK_RATIOS = (20, 30, 40, 50, 60)
MAX_TAIL_BYTES = 1_500_000
MAX_ROWS = 1200


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _text(value: Any, default: str = "") -> str:
    return str(value if value is not None else default).strip() or default


def _ts(value: Any) -> float:
    try:
        return datetime.fromisoformat(_text(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _lane(row: dict[str, Any]) -> str:
    asset = _text(row.get("asset_class") or row.get("asset_type"), "equity").lower()
    lane = _text(row.get("lane_id") or row.get("lane"), "").upper()
    instrument = _text(row.get("instrument_type"), "").upper()
    horizon = _text(row.get("paper_entry_horizon_style") or row.get("assigned_horizon") or row.get("horizon_style"), "").lower()
    if asset in {"crypto", "cryptocurrency"}:
        return "CRYPTO"
    if instrument == "ETF":
        return "DAY_ETF" if lane == "DAY" or horizon in {"day_trade", "intraday"} else "SWING_ETF"
    return "DAY" if lane == "DAY" or horizon in {"day_trade", "intraday", "scalp"} else "SWING"


def _safety() -> dict[str, Any]:
    return {"paper_only_preserved": True, "alpaca_paper_only_preserved": True, "live_trading_changed": False,
            "broker_live_endpoint_allowed": False, "crypto_live_trading_enabled": False,
            "broker_behavior_changed": False, "entry_behavior_changed": False, "exit_behavior_changed": False,
            "ranking_behavior_changed": False, "thresholds_changed": False, "position_sizing_changed": False,
            "automatic_promotions_enabled": False, "forced_trades_enabled": False, "forced_exits_enabled": False,
            "learned_exits_enabled": False, "automatic_activation_allowed": False, "behavior_safe_to_apply": False,
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0}


def _eligible(row: dict[str, Any]) -> tuple[bool, str]:
    if not bool(row.get("entry_price_verified")):
        return False, "entry_price_unverified"
    if not bool(row.get("loss_calibration_eligible")):
        return False, "loss_calibration_ineligible"
    if bool(row.get("diagnostic_only")):
        return False, "diagnostic_only_lifecycle"
    if _num(row.get("entry_price")) <= 0 or _num(row.get("current_price")) <= 0:
        return False, "invalid_price_path"
    return True, ""


def _read_tail(path: str) -> list[dict[str, Any]]:
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - MAX_TAIL_BYTES))
            text = handle.read().decode("utf-8", "ignore")
        lines = text.splitlines()
        if size > MAX_TAIL_BYTES and lines:
            lines = lines[1:]
        rows: list[dict[str, Any]] = []
        for line in lines[-MAX_ROWS:]:
            try:
                parsed = json.loads(line)
            except Exception:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows
    except Exception:
        return []


def _path_metrics(path: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    entry = _num(path[-1].get("entry_price"))
    returns = [((_num(row.get("current_price")) - entry) / entry * 100.0) for row in path if entry > 0 and _num(row.get("current_price")) > 0]
    final = returns[-1] if returns else 0.0
    peak = max(returns, default=0.0)
    trough = min(returns, default=0.0)
    return entry, final, peak, trough


def _loss_replay(path: list[dict[str, Any]], threshold: float) -> dict[str, Any] | None:
    entry, final, _peak, _trough = _path_metrics(path)
    if entry <= 0:
        return None
    returns = [((_num(row.get("current_price")) - entry) / entry * 100.0) for row in path]
    breach = next((i for i, value in enumerate(returns) if value <= threshold), None)
    if breach is None:
        return None
    after = returns[breach:]
    recovered = any(value > 0 for value in after)
    timestamps = [_ts(row.get("current_timestamp") or row.get("exit_timestamp")) for row in path]
    recovery = next((timestamps[i] - timestamps[breach] for i, value in enumerate(returns[breach:], breach) if value > 0 and timestamps[i] and timestamps[breach]), None)
    return {"threshold": threshold, "actual_final_return": final, "shadow_exit_return": returns[breach],
            "recovered_above_entry": recovered, "recovered_to_profitable_close": final > 0 and recovered,
            "finished_worse": final < returns[breach], "additional_downside": min(after, default=threshold) - returns[breach],
            "time_to_recovery_seconds": recovery, "hold_time_difference_seconds": max(0.0, timestamps[-1] - timestamps[breach]) if timestamps and timestamps[-1] and timestamps[breach] else None}


def _profit_replay(path: list[dict[str, Any]], trigger: float, giveback_ratio: float) -> dict[str, Any] | None:
    entry, final, _peak, _trough = _path_metrics(path)
    if entry <= 0:
        return None
    returns = [((_num(row.get("current_price")) - entry) / entry * 100.0) for row in path]
    peak = 0.0
    for index, value in enumerate(returns):
        peak = max(peak, value)
        if peak >= trigger and peak > 0 and (peak - value) / peak * 100.0 >= giveback_ratio:
            return {"trigger": trigger, "giveback_ratio": giveback_ratio, "peak_profit": peak,
                    "actual_final_return": final, "shadow_exit_return": value,
                    "capture_ratio": value / peak if peak else 0.0, "giveback_from_peak": peak - value}
    return None


def _stats(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_num(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return round(median(values), 4) if values else None


def _counterfactual_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize simulated exits without presenting them as broker outcomes."""
    simulated = [_num(row.get("shadow_exit_return")) for row in rows]
    actual = [_num(row.get("actual_final_return")) for row in rows]
    gains = sum(value for value in simulated if value > 0)
    losses = abs(sum(value for value in simulated if value < 0))
    return {
        "simulated_win_rate": round(sum(value > 0 for value in simulated) / len(simulated) * 100.0, 4) if simulated else None,
        "simulated_profit_factor": round(gains / losses, 4) if losses > 0 else None,
        "simulated_average_return": round(sum(simulated) / len(simulated), 4) if simulated else None,
        "actual_average_return": round(sum(actual) / len(actual), 4) if actual else None,
        "simulated_drawdown": round(min(simulated), 4) if simulated else None,
        "median_hold_time_difference_seconds": _stats(rows, "hold_time_difference_seconds"),
        "counterfactual_return_delta": round(sum(simulated) / len(simulated) - sum(actual) / len(actual), 4) if simulated and actual else None,
    }


def _broker_truth_lifecycle_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Accept only explicitly complete, entry-verified broker truth rows.

    These records can contribute a bounded two-point path when present, but
    never upgrade a reconstructed or advisory entry into calibration evidence.
    """
    output: list[dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        quality = _text(raw.get("truth_quality") or raw.get("evidence_class")).upper()
        if quality not in {"BROKER_CONFIRMED_COMPLETE", "BROKER_TRUTH"}:
            continue
        if not bool(raw.get("entry_price_verified")):
            continue
        entry = _num(raw.get("entry_price") or raw.get("broker_filled_avg_price"))
        exit_price = _num(raw.get("exit_price") or raw.get("current_price"))
        if entry <= 0 or exit_price <= 0:
            continue
        lifecycle_id = _text(raw.get("lifecycle_id") or raw.get("broker_order_id") or raw.get("id"))
        if not lifecycle_id:
            continue
        base = dict(raw)
        base.update({"lifecycle_id": lifecycle_id, "entry_price": entry, "current_price": entry,
                     "loss_calibration_eligible": True, "diagnostic_only": False,
                     "current_timestamp": raw.get("entry_timestamp") or raw.get("timestamp"), "closed": False,
                     "evidence_class": "BROKER_TRUTH"})
        final = dict(base)
        final.update({"current_price": exit_price, "current_timestamp": raw.get("exit_timestamp") or raw.get("closed_at") or raw.get("timestamp"),
                      "closed": True})
        output.extend((base, final))
    return output


def build_shadow_profit_loss_protection_validation_v1(
    lifecycle_rows: list[dict[str, Any]] | None,
    active_positions: list[dict[str, Any]] | None = None,
    broker_truth_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build lane-isolated shadow studies from verified lifecycle snapshots."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exclusions: Counter[str] = Counter()
    seen_broker_lifecycles: set[str] = set()
    source_rows = [dict(row) for row in (lifecycle_rows or []) if isinstance(row, dict)]
    for row in _broker_truth_lifecycle_rows(broker_truth_records):
        lifecycle_id = _text(row.get("lifecycle_id"))
        if lifecycle_id and lifecycle_id not in { _text(existing.get("lifecycle_id")) for existing in source_rows }:
            source_rows.append(row)
            seen_broker_lifecycles.add(lifecycle_id)
    for raw in source_rows:
        if not isinstance(raw, dict):
            exclusions["invalid_row"] += 1
            continue
        lifecycle_id = _text(raw.get("lifecycle_id") or raw.get("position_id"))
        if not lifecycle_id:
            exclusions["missing_lifecycle_identity"] += 1
            continue
        grouped[lifecycle_id].append(dict(raw))
    eligible: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lifecycle_id, path in grouped.items():
        path.sort(key=lambda row: _ts(row.get("current_timestamp") or row.get("generated_at") or row.get("entry_timestamp")))
        valid, reason = _eligible(path[-1])
        if not valid:
            exclusions[reason] += 1
            continue
        eligible[_lane(path[-1])].append({"lifecycle_id": lifecycle_id, "path": path, "latest": path[-1]})
    lane_results: dict[str, Any] = {}
    all_human_candidates: list[dict[str, Any]] = []
    for lane_name, lifecycles in eligible.items():
        completed = [item for item in lifecycles if bool(item["latest"].get("closed"))]
        fixed: dict[str, Any] = {}
        protection: dict[str, Any] = {}
        for threshold in LOSS_THRESHOLDS:
            replays = [result for item in completed if (result := _loss_replay(item["path"], float(threshold))) is not None]
            fixed[str(threshold)] = {"study_only": True, "eligible_trades": len(completed), "crossing_count": len(replays),
                "recovered_above_entry_count": sum(bool(row["recovered_above_entry"]) for row in replays),
                "recovered_to_profitable_close_count": sum(bool(row["recovered_to_profitable_close"]) for row in replays),
                "finished_worse_count": sum(bool(row["finished_worse"]) for row in replays),
                "median_final_return_after_breach": _stats(replays, "actual_final_return"),
                "median_additional_downside": _stats(replays, "additional_downside"),
                "maximum_additional_downside": min([_num(row["additional_downside"]) for row in replays], default=None),
                "median_time_to_recovery_seconds": _stats(replays, "time_to_recovery_seconds"),
                "opportunity_cost_after_breach": _stats(replays, "additional_downside"),
                **_counterfactual_metrics(replays),
                "counterfactual_evidence_class": "SHADOW_COUNTERFACTUAL"}
        for trigger in PROFIT_TRIGGERS:
            for ratio in GIVEBACK_RATIOS:
                replays = [result for item in completed if (result := _profit_replay(item["path"], float(trigger), float(ratio))) is not None]
                protection[f"trigger_{trigger}_giveback_{ratio}"] = {"study_only": True, "eligible_trades": len(completed), "triggered_count": len(replays),
                    "median_peak_profit": _stats(replays, "peak_profit"), "median_shadow_exit_return": _stats(replays, "shadow_exit_return"),
                    "median_actual_final_return": _stats(replays, "actual_final_return"), "median_capture_ratio": _stats(replays, "capture_ratio"),
                    **_counterfactual_metrics(replays), "counterfactual_evidence_class": "SHADOW_COUNTERFACTUAL"}
        symbols = Counter(_text(item["latest"].get("symbol")) for item in completed)
        concentration = (max(symbols.values()) / len(completed)) if completed and symbols else 0.0
        tier = "INSUFFICIENT" if len(completed) < 10 else "EARLY" if len(completed) < 25 else "DEVELOPING" if len(completed) < 50 else "REVIEW_READY" if len(completed) < 100 else "STRONG"
        candidate = {"lane": lane_name, "sample_size": len(completed), "readiness_tier": tier,
                     "symbol_concentration_pct": round(concentration * 100.0, 3),
                     "human_review_candidate": bool(tier in {"REVIEW_READY", "STRONG"} and concentration <= 0.5),
                     "blocker": "symbol_concentration" if concentration > 0.5 else "insufficient_sample" if tier not in {"REVIEW_READY", "STRONG"} else "repeatability_not_yet_verified"}
        if candidate["human_review_candidate"]:
            all_human_candidates.append(candidate)
        lane_results[lane_name] = {"eligible_lifecycles": len(lifecycles), "completed_lifecycles": len(completed), "readiness_tier": tier,
                                   "symbol_concentration_pct": round(concentration * 100.0, 3), "fixed_loss_threshold_results": fixed,
                                   "profit_protection_results": protection, "human_review_assessment": candidate}
    advisories: list[dict[str, Any]] = []
    for position in active_positions or []:
        if not isinstance(position, dict) or not bool(position.get("entry_price_verified")):
            continue
        entry = _num(position.get("entry_price")); current = _num(position.get("current_price"))
        ret = ((current - entry) / entry * 100.0) if entry > 0 and current > 0 else None
        action = "PROTECT_PROFIT" if ret is not None and ret > 0 and _num(position.get("profit_giveback_pct")) > 0 else "WATCH"
        if _text(position.get("thesis_state")).upper() == "THESIS_BROKEN":
            action = "THESIS_BROKEN"
        advisories.append({"position_id": position.get("position_id"), "symbol": position.get("symbol"), "asset_class": position.get("asset_class") or position.get("asset_type"),
                           "lane": _lane(position), "strategy": position.get("strategy_cohort"), "horizon": position.get("canonical_horizon"),
                           "entry_price": entry, "current_price": current or None, "verified_entry": True, "current_return": ret,
                           "MFE": position.get("max_favorable_excursion_pct"), "MAE": position.get("max_adverse_excursion_pct"),
                           "peak_profit": position.get("peak_unrealized_profit_pct"), "giveback": position.get("profit_giveback_pct"),
                           "hold_duration": position.get("hold_seconds"), "return_per_day": position.get("return_per_day"),
                           "thesis_state": position.get("thesis_state") or "unknown", "momentum_state": position.get("momentum_state") or "unknown",
                           "regime_state": position.get("regime_state") or "unknown", "opportunity_cost_state": position.get("opportunity_cost_state") or "unknown",
                           "recommended_advisory_action": action, "confidence": 0.0, "evidence_class": "BROKER_LINKED_REPLAY",
                           "limitations": ["advisory_only_no_order_submission"], "next_review_reason": "verified_entry_lifecycle_review"})
    total_eligible = sum(len(rows) for rows in eligible.values())
    total_completed = sum(int(row.get("completed_lifecycles") or 0) for row in lane_results.values())
    status = "INSUFFICIENT_EVIDENCE" if total_completed < 10 else "EARLY_EVIDENCE"
    thesis_counts = Counter(_text(item["latest"].get("thesis_state") or item["latest"].get("lifecycle_stage") or "unknown").upper()
                           for rows in eligible.values() for item in rows)
    return {"suite": "Shadow Profit/Loss Protection & Threshold Validation V1", "status": status, "generated_at": _now_iso(),
            "eligible_lifecycles": total_eligible, "eligible_complete_lifecycles": total_completed,
            "excluded_lifecycles": sum(exclusions.values()), "exclusion_reasons": dict(exclusions), "lane_results": lane_results,
            "fixed_loss_thresholds_studied": list(LOSS_THRESHOLDS), "profit_protection_structures_studied": {"profit_triggers": list(PROFIT_TRIGGERS), "giveback_ratios": list(GIVEBACK_RATIOS)},
            "thesis_break_results": {"advisory_only": True, "observed_state_counts": dict(thesis_counts), "allowed_actions": ["HOLD", "WATCH", "PROTECT_PROFIT", "CONTROLLED_LOSS_REVIEW", "EXIT_REVIEW", "REPLACE_CANDIDATE", "THESIS_BROKEN", "INSUFFICIENT_EVIDENCE"]},
            "controlled_loss_results": {"optimization_target": ["profit_factor", "average_return", "drawdown", "recovery_rate", "return_per_day", "opportunity_cost"], "automatic_exit": False},
            "counterfactual_results": {"evidence_class": "SHADOW_COUNTERFACTUAL", "realized_profit_claimed": False},
            "position_level_advisories": advisories[:50], "best_observed_candidate": None, "human_review_candidates": all_human_candidates,
            "source_files": ["trade_lifecycle_excursion_v1.jsonl", "broker_truth_records_v1.json", "paper_positions"],
            "broker_truth_lifecycle_rows_used": len(seen_broker_lifecycles), **_safety()}


class ShadowProfitLossProtectionValidationV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.path = os.path.join(self.state_dir, "shadow_profit_loss_protection_validation_v1.json")

    def build(self, lifecycle_rows: list[dict[str, Any]], active_positions: list[dict[str, Any]] | None = None,
              broker_truth_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return build_shadow_profit_loss_protection_validation_v1(lifecycle_rows, active_positions, broker_truth_records)

    def load_snapshot(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}

    def load_bounded_lifecycle_rows(self) -> list[dict[str, Any]]:
        return _read_tail(os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl"))

    def write_snapshot(self, payload: dict[str, Any]) -> None:
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            temp = f"{self.path}.tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(dict(payload or {}), handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            os.replace(temp, self.path)
        except Exception:
            return
