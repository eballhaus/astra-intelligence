"""Canonical, non-executing shadow exit lifecycle foundation.

This owner schedules observations of real positions without altering broker truth,
orders, realised performance, or advisory authority.  Advanced outcome maths is
intentionally delegated through the versioned Kimi module contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_exit_intelligence_v1"
EVALUATION_FILE = "astra_shadow_exit_intelligence_v1.json"
OBSERVATION_FILE = "astra_shadow_exit_observations_v1.json"
DIAGNOSTIC_FILE = "astra_shadow_exit_diagnostics_v1.json"
HANDOFF_FILE = "astra_shadow_exit_module_handoff_v1.json"
MAX_EVALUATIONS = 600
MAX_OBSERVATIONS = 3000
BASELINE_STRATEGIES = (
    "CONTINUE_HOLD", "EXIT_NOW", "EXIT_AFTER_CONFIRMATION", "PROTECT_PROFIT", "PROTECT_ON_BOUNCE",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else fallback
    except (TypeError, ValueError):
        return fallback


def _text(value: Any) -> str:
    return str(value or "").strip()


def _digest(*values: Any) -> str:
    raw = "|".join(_text(value) for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, Mapping) else {}
    except (OSError, ValueError):
        return {}


def shadow_position_identity_v1(position: Mapping[str, Any], recovery: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create a stable exact identity; only legacy positions may use a fingerprint."""
    recovery = dict(recovery or {})
    symbol = _text(position.get("symbol")).upper()
    asset_class = _text(position.get("asset_class") or position.get("asset_type") or "equity").lower()
    linked = {name: _text(position.get(name) or recovery.get(name)) for name in
              ("broker_position_id", "position_id", "lifecycle_id", "entry_fill_id", "astra_order_id", "candidate_id")}
    # The recovery owner may have the authoritative active lifecycle ID even
    # when the broker-normalized row intentionally omits Astra metadata.
    if not linked["lifecycle_id"] and _text(recovery.get("lane_source")) == "ACTIVE_POSITION_LIFECYCLE":
        linked["lifecycle_id"] = _text(recovery.get("lane_source_id"))
    entry_timestamp = _text(position.get("entry_timestamp") or position.get("opened_at") or recovery.get("entry_timestamp"))
    entry_price = _number(position.get("avg_entry_price") or position.get("average_entry_price") or position.get("entry_price"))
    quantity = _number(position.get("qty") or position.get("quantity"))
    lane = _text(recovery.get("lane") or position.get("lane") or "UNAVAILABLE").upper()
    horizon = _text(recovery.get("horizon") or position.get("horizon") or "UNAVAILABLE")
    has_exact = any(linked[name] for name in ("broker_position_id", "position_id", "lifecycle_id", "entry_fill_id", "astra_order_id"))
    legacy = not has_exact and lane == "UNAVAILABLE" and horizon == "UNAVAILABLE"
    if has_exact:
        source = next(name.upper() for name in ("broker_position_id", "position_id", "lifecycle_id", "entry_fill_id", "astra_order_id", "candidate_id") if linked[name])
        identity = f"shadow-pos:{source}:{_digest(asset_class, linked[source.lower()], entry_timestamp, entry_price, quantity)}"
        confidence, legacy_status = "CANONICAL", "ASTRA_MANAGED"
    elif legacy:
        source = "BOUNDED_LEGACY_FINGERPRINT"
        identity = f"shadow-legacy:{_digest(symbol, asset_class, entry_timestamp, entry_price, quantity)}"
        confidence, legacy_status = "BOUNDED", "LEGACY"
    else:
        source, identity, confidence, legacy_status = "IDENTITY_UNAVAILABLE", "", "NONE", "UNKNOWN"
    return {
        "position_identity": identity, "position_identity_version": "v1", "symbol": symbol, "asset_class": asset_class,
        "broker_position_id": linked["broker_position_id"] or linked["position_id"] or None,
        "lifecycle_id": linked["lifecycle_id"] or None, "entry_fill_id": linked["entry_fill_id"] or None,
        "astra_order_id": linked["astra_order_id"] or None, "candidate_id": linked["candidate_id"] or None,
        "entry_timestamp": entry_timestamp or None, "entry_price": entry_price or None, "quantity_at_evaluation": quantity,
        "legacy_status": legacy_status, "identity_source": source, "identity_confidence": confidence,
        "lane": lane, "lane_status": "RESOLVED" if lane != "UNAVAILABLE" else "UNAVAILABLE",
        "horizon": horizon, "horizon_status": "RESOLVED" if horizon != "UNAVAILABLE" else "UNAVAILABLE",
    }


def observation_windows_v1(identity: Mapping[str, Any]) -> list[str]:
    lane, horizon = _text(identity.get("lane")).upper(), _text(identity.get("horizon")).lower()
    if identity.get("legacy_status") == "LEGACY": return ["1h", "close", "1d", "3d", "5d"]
    if lane == "CRYPTO": return ["1h", "4h", "12h", "1d", "3d"]
    if lane == "SWING": return ["1d", "3d", "5d", "10d"]
    if lane == "DAY" and horizon in {"scalp", "intraday"}: return ["5m", "15m", "30m", "1h", "close"]
    return ["30m", "1h", "close"]


def _target(signal_at: datetime, window: str) -> datetime:
    units = {"5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "30m": timedelta(minutes=30), "1h": timedelta(hours=1), "4h": timedelta(hours=4), "12h": timedelta(hours=12), "1d": timedelta(days=1), "3d": timedelta(days=3), "5d": timedelta(days=5), "10d": timedelta(days=10)}
    if window != "close": return signal_at + units[window]
    close = signal_at.replace(hour=20, minute=0, second=0, microsecond=0)
    return close if close > signal_at else close + timedelta(days=1)


def _strategy_eligibility(strategy: str, exit_row: Mapping[str, Any]) -> tuple[bool, str]:
    recommendation = _text(exit_row.get("recommendation")).upper()
    if strategy == "CONTINUE_HOLD": return True, "HOLD_BENCHMARK_REQUIRED"
    if strategy == "EXIT_NOW": return recommendation in {"EXIT_REVIEW", "THESIS_BROKEN", "PROTECT_CAPITAL"}, "EXIT_REVIEW_SIGNAL_REQUIRED"
    if strategy == "EXIT_AFTER_CONFIRMATION": return recommendation in {"WATCH", "EXIT_REVIEW", "PROTECT_CAPITAL"}, "CONFIRMATION_SIGNAL_REQUIRED"
    if strategy == "PROTECT_PROFIT": return _text(exit_row.get("profit_protection_state")).upper() not in {"", "UNAVAILABLE"}, "PROFIT_PROTECTION_EVIDENCE_REQUIRED"
    if strategy == "PROTECT_ON_BOUNCE": return recommendation in {"WATCH", "PROTECT_CAPITAL", "EXIT_REVIEW"}, "RISK_REVIEW_SIGNAL_REQUIRED"
    return False, "UNSUPPORTED_STRATEGY"


def _position_rows(rows: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(str(symbol).upper(), dict(value or {})) for symbol, value in sorted((rows or {}).items()) if isinstance(value, Mapping)]


def run_shadow_exit_cycle_v1(
    broker_positions: Mapping[str, Mapping[str, Any]], *, recovery: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None, exit_readiness: Mapping[str, Any] | None = None,
    previous: Mapping[str, Any] | None = None, now: datetime | None = None, max_new_evaluations: int = 200,
) -> dict[str, dict[str, Any]]:
    """Pure worker-owned cycle. It reads cached evidence only and never calls a broker/provider."""
    now = now or _now(); now_iso = _iso(now); prior = dict(previous or {})
    recoveries = {_text(x.get("symbol")).upper(): dict(x) for x in (recovery or {}).get("positions", []) if isinstance(x, Mapping)}
    evidence_by_symbol = {_text(x.get("symbol")).upper(): dict(x) for x in (evidence or {}).get("positions", []) if isinstance(x, Mapping)}
    exits = {_text(x.get("symbol")).upper(): dict(x) for x in (exit_readiness or {}).get("positions", []) if isinstance(x, Mapping)}
    evaluations = {str(x.get("shadow_evaluation_id")): dict(x) for x in prior.get("evaluations", []) if isinstance(x, Mapping)}
    observations = {str(x.get("shadow_observation_id")): dict(x) for x in prior.get("observations", []) if isinstance(x, Mapping)}
    # A regenerated advisory timestamp is not a new shadow signal. Retain one
    # active evaluation per exact identity/strategy/signal until it finalizes.
    active_keys = {
        (_text(row.get("position_identity")), _text(row.get("shadow_strategy")), _text(row.get("exit_signal_type")))
        for row in evaluations.values() if row.get("evaluation_status") in {"ACTIVE", "PARTIALLY_OBSERVED", "EXTERNALLY_BLOCKED"}
    }
    active_identities, created, deduplicated, considered, eligible = set(), 0, 0, 0, 0
    for symbol, position in _position_rows(broker_positions):
        considered += 1; identity = shadow_position_identity_v1(position, recoveries.get(symbol)); active_identities.add(identity.get("position_identity"))
        evidence_row, exit_row = evidence_by_symbol.get(symbol, {}), exits.get(symbol, {})
        price = _number(position.get("current_price") or position.get("market_price") or evidence_row.get("current_price"))
        if not identity.get("position_identity") or price <= 0:
            continue
        eligible += 1
        signal_at = _parse(exit_row.get("generated_at")) or now
        epoch = signal_at.replace(minute=(signal_at.minute // 15) * 15, second=0, microsecond=0)
        for strategy in BASELINE_STRATEGIES:
            strategy_ok, reason = _strategy_eligibility(strategy, exit_row)
            evaluation_id = f"shadow-eval:{_digest(identity['position_identity'], strategy, _iso(epoch))}"
            signal_key = (identity["position_identity"], strategy, _text(exit_row.get("recommendation") or "NOT_EVALUATED"))
            if evaluation_id in evaluations or signal_key in active_keys:
                deduplicated += 1; continue
            if created >= max_new_evaluations: continue
            status = "ACTIVE" if strategy_ok else "EXTERNALLY_BLOCKED"
            blocker = "" if strategy_ok else reason
            evaluation = {**identity, "shadow_evaluation_id": evaluation_id, "schema_version": SCHEMA_VERSION, "generated_at": now_iso,
                "market_evidence_at": evidence_row.get("quote_evidence_at") or evidence_row.get("completed_bar_evidence_at"),
                "current_price": price, "market_value_basis": _number(position.get("market_value")),
                "unrealized_return": _number(position.get("unrealized_plpc") or position.get("unrealized_return")),
                "position_age": position.get("position_age_days"), "exit_signal_type": exit_row.get("recommendation") or "NOT_EVALUATED",
                "exit_signal_source": "astra_position_exit_readiness_v1", "shadow_strategy": strategy, "strategy_eligibility": "ELIGIBLE" if strategy_ok else "INELIGIBLE",
                "strategy_reason": reason, "strategy_parameters": {"signal_epoch": _iso(epoch), "advisory_only": True},
                "shadow_reference_price": price, "shadow_reference_timestamp": now_iso, "provider": evidence_row.get("quote_source") or "CACHED_POSITION_EVIDENCE",
                "price_age": evidence_row.get("quote_age_seconds"), "evidence_status": evidence_row.get("quote_status") or "MISSING",
                "first_causal_blocker": blocker, "evaluation_status": status, "required_observation_windows": observation_windows_v1(identity),
                "completed_observation_windows": [], "pending_observation_windows": observation_windows_v1(identity) if strategy_ok else [],
                "expiration_at": _iso(now + timedelta(days=14)), "hold_price_at_signal": price, "hold_price_at_window": None,
                "hold_return_from_signal": None, "maximum_favorable_excursion_after_signal": 0.0, "maximum_adverse_excursion_after_signal": 0.0,
                "actual_position_still_open": True, "actual_exit_timestamp": None, "actual_exit_price": None, "actual_realized_result": None,
                "shadow_only": True, "execution_authority": "DISABLED", "promotion_status": "NOT_PROMOTED"}
            evaluations[evaluation_id] = evaluation; active_keys.add(signal_key); created += 1
            if strategy_ok:
                for window in evaluation["required_observation_windows"]:
                    observation_id = f"shadow-observation:{_digest(evaluation_id, window)}"
                    observations[observation_id] = {"shadow_observation_id": observation_id, "shadow_evaluation_id": evaluation_id,
                        "position_identity": identity["position_identity"], "strategy": strategy, "observation_window": window,
                        "target_timestamp": _iso(_target(signal_at, window)), "actual_observation_timestamp": None, "market_price": None,
                        "provider": None, "market_evidence_at": None, "price_age": None, "observation_status": "PENDING",
                        "first_causal_blocker": "FUTURE_WINDOW_PENDING", "created_at": now_iso, "updated_at": now_iso,
                        "shadow_only": True, "execution_authority": "DISABLED", "promotion_status": "NOT_PROMOTED"}
    for evaluation in evaluations.values():
        if evaluation.get("evaluation_status") in {"ACTIVE", "PARTIALLY_OBSERVED"} and evaluation.get("position_identity") not in active_identities:
            evaluation.update({"evaluation_status": "CANCELED_POSITION_IDENTITY_CHANGED", "first_causal_blocker": "POSITION_IDENTITY_NO_LONGER_OPEN", "actual_position_still_open": False, "updated_at": now_iso})
    due = completed = 0
    symbol_by_identity = {shadow_position_identity_v1(pos, recoveries.get(sym)).get("position_identity"): (sym, pos) for sym, pos in _position_rows(broker_positions)}
    for observation in observations.values():
        if observation.get("observation_status") != "PENDING" or (_parse(observation.get("target_timestamp")) or now) > now: continue
        due += 1; pair = symbol_by_identity.get(observation.get("position_identity")); evaluation = evaluations.get(observation.get("shadow_evaluation_id"))
        if not pair or not evaluation:
            observation.update({"observation_status": "CANCELED_IDENTITY_CHANGED", "first_causal_blocker": "POSITION_IDENTITY_NO_LONGER_OPEN", "updated_at": now_iso}); continue
        symbol, position = pair; evidence_row = evidence_by_symbol.get(symbol, {}); price = _number(position.get("current_price") or evidence_row.get("current_price"))
        if price <= 0 or evidence_row.get("quote_status") == "STALE":
            observation.update({"observation_status": "STALE_EVIDENCE_REJECTED", "first_causal_blocker": "CURRENT_QUOTE_EVIDENCE_STALE", "updated_at": now_iso}); continue
        observation.update({"observation_status": "COMPLETED", "actual_observation_timestamp": now_iso, "market_price": price,
                            "provider": evidence_row.get("quote_source") or "CACHED_POSITION_EVIDENCE", "market_evidence_at": evidence_row.get("quote_evidence_at"),
                            "price_age": evidence_row.get("quote_age_seconds"), "first_causal_blocker": "", "updated_at": now_iso}); completed += 1
        reference = _number(evaluation.get("hold_price_at_signal")); result = (price / reference - 1.0) if reference > 0 else None
        evaluation["hold_price_at_window"] = price; evaluation["hold_return_from_signal"] = result
        evaluation["maximum_favorable_excursion_after_signal"] = max(_number(evaluation.get("maximum_favorable_excursion_after_signal")), result or 0.0)
        evaluation["maximum_adverse_excursion_after_signal"] = min(_number(evaluation.get("maximum_adverse_excursion_after_signal")), result or 0.0)
        done = [x.get("observation_window") for x in observations.values() if x.get("shadow_evaluation_id") == evaluation.get("shadow_evaluation_id") and x.get("observation_status") == "COMPLETED"]
        evaluation["completed_observation_windows"] = sorted(done); evaluation["pending_observation_windows"] = [x for x in evaluation.get("required_observation_windows", []) if x not in done]
        evaluation["evaluation_status"] = "PARTIALLY_OBSERVED" if done else "ACTIVE"
    # Migrate any prior timestamp-epoch duplicates deterministically. Completed
    # and terminal records are retained; only competing active rows collapse.
    ordered_all = sorted(evaluations.values(), key=lambda x: _text(x.get("generated_at")), reverse=True)
    seen_current: set[tuple[str, str, str]] = set(); ordered_evaluations = []
    for row in ordered_all:
        key = (_text(row.get("position_identity")), _text(row.get("shadow_strategy")), _text(row.get("exit_signal_type")))
        if row.get("evaluation_status") in {"ACTIVE", "PARTIALLY_OBSERVED", "EXTERNALLY_BLOCKED"} and key in seen_current:
            continue
        if row.get("evaluation_status") in {"ACTIVE", "PARTIALLY_OBSERVED", "EXTERNALLY_BLOCKED"}: seen_current.add(key)
        ordered_evaluations.append(row)
        if len(ordered_evaluations) >= MAX_EVALUATIONS: break
    kept = {x["shadow_evaluation_id"] for x in ordered_evaluations}; ordered_observations = [x for x in observations.values() if x.get("shadow_evaluation_id") in kept]
    ordered_observations.sort(key=lambda x: _text(x.get("created_at")), reverse=True); ordered_observations = ordered_observations[:MAX_OBSERVATIONS]
    counts = {status: sum(1 for x in ordered_evaluations if x.get("evaluation_status") == status) for status in ("ACTIVE", "PARTIALLY_OBSERVED", "COMPLETED", "EXPIRED_INSUFFICIENT_DATA", "EXTERNALLY_BLOCKED")}
    diagnostics = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso, "positions_considered": considered, "positions_eligible": eligible,
        "positions_ineligible": considered - eligible, "evaluations_created": created, "evaluations_deduplicated": deduplicated,
        "active_evaluations": counts["ACTIVE"], "partially_observed_evaluations": counts["PARTIALLY_OBSERVED"], "completed_evaluations": counts["COMPLETED"],
        "expired_evaluations": counts["EXPIRED_INSUFFICIENT_DATA"], "externally_blocked_evaluations": counts["EXTERNALLY_BLOCKED"],
        "pending_observations": sum(1 for x in ordered_observations if x.get("observation_status") == "PENDING"), "due_observations": due,
        "completed_observations": sum(1 for x in ordered_observations if x.get("observation_status") == "COMPLETED"),
        "stale_rejected_observations": sum(1 for x in ordered_observations if x.get("observation_status") == "STALE_EVIDENCE_REJECTED"),
        "externally_blocked_observations": sum(1 for x in ordered_observations if x.get("observation_status") == "EXTERNALLY_BLOCKED"),
        "identity_conflicts": 0, "reopened_symbol_events": 0, "quantity_change_events": 0, "real_closure_reconciliations": 0,
        "provider_requests": 0, "provider_cache_hits": 0, "provider_blockers": [], "freshness_blockers": ["CURRENT_QUOTE_EVIDENCE_STALE"] if any(x.get("observation_status") == "STALE_EVIDENCE_REJECTED" for x in ordered_observations) else [],
        "exit_readiness_handoffs": eligible, "unified_advisory_handoffs": eligible, "copilot_handoffs": eligible,
        "analysis_module_inputs_emitted": len(ordered_evaluations), "analysis_module_outputs_consumed": 0,
        "first_causal_blockers": sorted({str(x.get("first_causal_blocker")) for x in ordered_evaluations if x.get("first_causal_blocker")}),
        "execution_authority": "DISABLED", "shadow_only": True, "promotion_status": "NOT_PROMOTED"}
    state = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso, "evaluations": ordered_evaluations, "position_count": considered,
             "execution_authority": "DISABLED", "shadow_only": True, "promotion_status": "NOT_PROMOTED"}
    observation_state = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso, "observations": ordered_observations,
                         "execution_authority": "DISABLED", "shadow_only": True, "promotion_status": "NOT_PROMOTED"}
    handoff = {"schema_version": SCHEMA_VERSION, "generated_at": now_iso, "contract_version": "astra_shadow_exit_module_contract_v1",
               "inputs": [{"shadow_evaluation_id": x["shadow_evaluation_id"], "position_identity": x["position_identity"], "strategy": x["shadow_strategy"], "hold_benchmark": {k: x.get(k) for k in ("hold_price_at_signal", "hold_price_at_window", "hold_return_from_signal", "maximum_favorable_excursion_after_signal", "maximum_adverse_excursion_after_signal")}} for x in ordered_evaluations],
               "outputs_consumed": [], "execution_authority": "DISABLED", "shadow_only": True, "promotion_status": "NOT_PROMOTED"}
    return {"state": state, "observations": observation_state, "diagnostics": diagnostics, "handoff": handoff}


def save_shadow_exit_cycle_v1(cycle: Mapping[str, Mapping[str, Any]], state_dir: str | Path = "state") -> None:
    root = Path(state_dir); _atomic_write(root / EVALUATION_FILE, cycle["state"]); _atomic_write(root / OBSERVATION_FILE, cycle["observations"])
    _atomic_write(root / DIAGNOSTIC_FILE, cycle["diagnostics"]); _atomic_write(root / HANDOFF_FILE, cycle["handoff"])


def load_shadow_exit_state_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    root = Path(state_dir); state = _load(root / EVALUATION_FILE); state["observations"] = _load(root / OBSERVATION_FILE).get("observations", [])
    return state


def shadow_handoff_by_symbol_v1(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in state.get("evaluations", []):
        if not isinstance(row, Mapping): continue
        symbol = _text(row.get("symbol")).upper(); current = result.setdefault(symbol, {"shadow_evaluation_status": "NOT_EVALUATED", "shadow_active_strategies": [], "shadow_completed_outcome_count": 0, "shadow_pending_observation_count": 0, "shadow_signal_support": "INSUFFICIENT_SAMPLE", "shadow_signal_confidence": "INSUFFICIENT_SAMPLE", "shadow_sample_size": 0, "shadow_expected_benefit": None, "shadow_regret_risk": None, "shadow_promotion_status": "NOT_PROMOTED", "shadow_first_causal_blocker": ""})
        current["shadow_sample_size"] += 1
        if row.get("evaluation_status") in {"ACTIVE", "PARTIALLY_OBSERVED"}: current["shadow_active_strategies"].append(row.get("shadow_strategy")); current["shadow_evaluation_status"] = row.get("evaluation_status")
        if row.get("evaluation_status") == "PARTIALLY_OBSERVED": current["shadow_completed_outcome_count"] += len(row.get("completed_observation_windows") or [])
        current["shadow_pending_observation_count"] += len(row.get("pending_observation_windows") or [])
        current["shadow_first_causal_blocker"] = current["shadow_first_causal_blocker"] or row.get("first_causal_blocker") or "PENDING_OBSERVATION"
    return result
