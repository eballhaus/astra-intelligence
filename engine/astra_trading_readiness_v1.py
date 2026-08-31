"""Bounded worker-owned readiness checks and non-decision runtime recovery."""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


VERSION = "ASTRA_TRADING_HOURS_INTEGRITY_MONITOR_V1"
RECOVERY_VERSION = "ASTRA_SAFE_RUNTIME_RECOVERY_V1"
LANES = ("DAY", "SCALP", "SWING", "CRYPTO")
_ET = ZoneInfo("America/New_York")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return _dict(value)
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class AstraTradingReadinessV1:
    """Observes committed worker state and retries only explicit plumbing actions."""

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / "astra_trading_readiness_v1.json"

    @staticmethod
    def _session(now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(_ET)
        minutes = current.hour * 60 + current.minute
        weekday = current.weekday() < 5
        equity_open = weekday and (9 * 60 + 30) <= minutes < 16 * 60
        preopen = weekday and (9 * 60 + 20) <= minutes < (9 * 60 + 30)
        return {
            "timezone": "America/New_York",
            "equity_session_open": equity_open,
            "preopen_window": preopen,
            "market_local_time": current.isoformat(),
        }

    @staticmethod
    def _active_observation_symbols(runtime: Mapping[str, Any]) -> set[str]:
        observations = _dict(_dict(runtime.get("active_equity_fmp_observations_v1")).get("observations"))
        return {str(symbol).upper().strip() for symbol in observations if str(symbol).strip()}

    def _issues(self, runtime: Mapping[str, Any], session: Mapping[str, Any]) -> list[dict[str, Any]]:
        trace = _dict(runtime.get("last_execution_trace"))
        market = _dict(_dict(trace.get("legacy_swing_observation")).get("market_activity"))
        source_state = _dict(runtime.get("equity_discovery_rebuild_v1"))
        issues: list[dict[str, Any]] = []
        source_blocker = str(trace.get("final_blocker_reason") or trace.get("cycle_reason") or "")
        equity_source_missing = (
            bool(session.get("equity_session_open"))
            and not bool(source_state.get("candidate_source_available"))
            and source_blocker in {"legacy_market_evidence_bounded", "full_cycle_required_for_equity_candidate_processing"}
        )
        if equity_source_missing:
            issues.append({
                "fault_type": "DISCOVERY_LEGACY_BYPASS",
                "component": "PaperAutopilot.candidate_source",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "CRITICAL",
                "repair_action": "REBUILD_CANONICAL_DISCOVERY_STATE",
                "evidence": source_blocker,
            })

        active_symbols = self._active_observation_symbols(runtime)
        ws = _dict(runtime.get("alpaca_ws_active_position_monitor_v1"))
        actual = {
            str(value).upper().strip()
            for value in (ws.get("subscribed_symbols") or ws.get("active_symbols") or [])
            if str(value).strip()
        }
        missing_ws = sorted(active_symbols - actual)
        if active_symbols and missing_ws:
            issues.append({
                "fault_type": "ACTIVE_POSITION_NOT_STREAMED",
                "component": "AlpacaWS.active_position_subscription",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "HIGH",
                "repair_action": "RECONCILE_WS_SUBSCRIPTIONS",
                "evidence": ",".join(missing_ws[:12]),
            })

        loss = _dict(runtime.get("loss_containment_state_v1"))
        decisions = _dict(loss.get("decisions"))
        timestamp_failures = [
            row for row in decisions.values() if isinstance(row, Mapping)
            and "MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE" in str(row.get("first_causal_blocker") or row.get("reason") or "")
        ]
        if active_symbols and timestamp_failures:
            issues.append({
                "fault_type": "PRODUCER_FRESH_CONSUMER_UNAVAILABLE",
                "component": "PaperAutopilot.management_observation_handoff",
                "lanes": ["DAY", "SCALP", "SWING"],
                "severity": "HIGH",
                "repair_action": "REMATERIALIZE_MANAGEMENT_EVIDENCE",
                "evidence": str(len(timestamp_failures)),
            })

        recovery = _dict(runtime.get("position_lane_horizon_recovery_v1"))
        unresolved_crypto = int(recovery.get("unresolved_horizon_count") or 0)
        crypto_rows = [row for row in (recovery.get("positions") or []) if isinstance(row, Mapping) and str(row.get("asset_type") or row.get("asset_class") or "").lower() in {"crypto", "cryptocurrency"}]
        if crypto_rows and unresolved_crypto:
            issues.append({
                "fault_type": "CRYPTO_HORIZON_PRESENT_BUT_NOT_CONSUMED",
                "component": "PaperAutopilot.position_lane_horizon_recovery",
                "lanes": ["CRYPTO"],
                "severity": "HIGH",
                "repair_action": "RELOAD_CANONICAL_IDENTITY_STATE",
                "evidence": str(unresolved_crypto),
            })
        return issues

    @staticmethod
    def _readiness(issues: list[dict[str, Any]], session: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, str]:
        by_lane = {lane: [] for lane in LANES}
        for issue in issues:
            for lane in issue.get("lanes") or []:
                if lane in by_lane:
                    by_lane[lane].append(issue)
        out: dict[str, str] = {}
        for lane, lane_issues in by_lane.items():
            if any(str(issue.get("severity")) == "CRITICAL" for issue in lane_issues):
                out[lane] = "BLOCKED"
            elif lane_issues:
                out[lane] = "DEGRADED"
            else:
                out[lane] = "TECHNICALLY_READY"
        return out

    def run_if_due(
        self,
        *,
        runtime_state: Mapping[str, Any],
        worker_state: Mapping[str, Any],
        actions: Mapping[str, Callable[[], Mapping[str, Any] | None]] | None = None,
    ) -> dict[str, Any]:
        previous = _read(self.path)
        session = self._session()
        now = time.monotonic()
        interval = 300.0 if bool(session["equity_session_open"]) or bool(session["preopen_window"]) else 900.0
        if previous and now - float(previous.get("scan_monotonic") or 0.0) < interval:
            return {**previous, "due": False, "provider_calls_used": 0, "broker_actions_used": 0}

        actions = dict(actions or {})
        issues = self._issues(runtime_state, session)
        previous_faults = _dict(previous.get("faults"))
        fault_rows: dict[str, dict[str, Any]] = {}
        recoveries: list[dict[str, Any]] = []
        for issue in issues:
            key = f"{issue['fault_type']}:{issue['component']}"
            prior = _dict(previous_faults.get(key))
            count = int(prior.get("occurrence_count") or 0) + 1
            attempts = int(prior.get("repair_attempt_count") or 0)
            result: dict[str, Any] = {}
            action = str(issue.get("repair_action") or "")
            if attempts < 2 and callable(actions.get(action)):
                attempts += 1
                try:
                    result = _dict(actions[action]())
                    verification = "VERIFYING" if result else "FAILED"
                except Exception as exc:
                    result = {"error": str(exc)[:160]}
                    verification = "FAILED"
                recoveries.append({"fault_type": issue["fault_type"], "repair_action": action, "result": result, "verification_result": verification})
            else:
                verification = "CODE_REPAIR_REQUIRED" if attempts >= 2 else "NO_SAFE_ACTION_AVAILABLE"
            fault_rows[key] = {
                **issue,
                "first_seen": prior.get("first_seen") or _now(),
                "last_seen": _now(),
                "occurrence_count": count,
                "repair_attempt_count": attempts,
                "repair_result": result,
                "verification_result": verification,
                "recurrent": count >= 3,
            }

        # Recovery is bounded to one action per fault. Re-evaluate committed
        # runtime state once so a local cache/subscription repair is never
        # reported as healthy without evidence.
        remaining_issues = self._issues(runtime_state, session) if recoveries else issues
        remaining_keys = {
            f"{row['fault_type']}:{row['component']}" for row in remaining_issues
        }
        for key, row in fault_rows.items():
            if key not in remaining_keys and row.get("verification_result") == "VERIFYING":
                row["verification_result"] = "PASSED"
        issues = remaining_issues
        readiness = self._readiness(issues, session, runtime_state)
        equity_fault = any("DAY" in row.get("lanes", []) for row in issues)
        technical_no_trade = bool(session["equity_session_open"] and equity_fault)
        summary = {
            "schema_version": VERSION,
            "recovery_schema_version": RECOVERY_VERSION,
            "generated_at": _now(),
            "scan_monotonic": now,
            "due": True,
            "session": session,
            "trading_integrity_state": "CODE_REPAIR_REQUIRED" if any(row.get("verification_result") == "CODE_REPAIR_REQUIRED" for row in fault_rows.values()) else ("DEGRADED" if issues else "READY"),
            "lane_readiness": readiness,
            "day_readiness": readiness["DAY"],
            "scalp_readiness": readiness["SCALP"],
            "swing_readiness": readiness["SWING"],
            "crypto_readiness": readiness["CRYPTO"],
            "discovery_integrity": "FAULT" if any(row["fault_type"].startswith("DISCOVERY") for row in issues) else "READY",
            "position_management_integrity": "FAULT" if any(row["fault_type"] == "PRODUCER_FRESH_CONSUMER_UNAVAILABLE" for row in issues) else "READY",
            "ws_coverage_integrity": "FAULT" if any(row["fault_type"] == "ACTIVE_POSITION_NOT_STREAMED" for row in issues) else "READY",
            "crypto_lifecycle_integrity": "FAULT" if any(row["fault_type"].startswith("CRYPTO_") for row in issues) else "READY",
            "strict_truth_integrity": "NOT_EXERCISED",
            "technical_no_trade": "TECHNICAL_NO_TRADE" if technical_no_trade else "NATURAL_NO_TRADE_OR_ACTIVITY_PRESENT",
            "faults": fault_rows,
            "active_faults": list(fault_rows.values()),
            "self_heal_attempts": len(recoveries),
            "self_heal_successes": sum(1 for row in recoveries if row.get("verification_result") == "VERIFYING"),
            "recurrent_faults": [row for row in fault_rows.values() if row.get("recurrent")],
            "code_repair_required": any(row.get("verification_result") == "CODE_REPAIR_REQUIRED" for row in fault_rows.values()),
            "recoveries": recoveries,
            "last_full_successful_check": previous.get("last_full_successful_check") if issues else _now(),
            "safe_rollback_capability": "SAFE_ROLLBACK_UNAVAILABLE",
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "paper_only": True,
            "entry_policy_changed": False,
            "exit_policy_changed": False,
            "ranking_changed": False,
            "risk_changed": False,
            "sizing_changed": False,
            "capacity_changed": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        _write(self.path, summary)
        return summary
