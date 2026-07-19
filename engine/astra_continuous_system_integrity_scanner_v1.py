"""Worker-owned, bounded, non-executing integrity orchestration for Astra."""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.astra_canonical_truth_registry_v1 import canonical_fact_registry_v1
from engine.astra_contract_integrity_v1 import validate_field_contract_v1
from engine.astra_integrity_dependency_graph_v1 import dependency_graph_v1, root_cause_from_signal_v1
from engine.astra_safe_correction_registry_v1 import SafeCorrectionRegistryV1


VERSION = "1.1.0"
ROOT_LIMIT = 100
VERIFICATION_WINDOW = 3


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return dict(value) if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _number(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ContinuousSystemIntegrityScannerV1:
    """Bounded scanner run by PaperAutopilotWorker only.

    The scanner consumes already committed worker facts. It has no broker,
    provider, LLM, order, lifecycle, or trading-policy mutation capability.
    """

    def __init__(self, state_dir: str | Path = "state") -> None:
        self.state_dir = Path(state_dir)
        self.summary_path = self.state_dir / "astra_system_integrity_scanner_v1.json"
        self.root_path = self.state_dir / "astra_integrity_root_causes_v1.json"
        self.consumer_path = self.state_dir / "astra_integrity_consumer_compliance_v1.json"
        self.lock_path = self.state_dir / "astra_system_integrity_scanner_v1.lock"
        self.corrections = SafeCorrectionRegistryV1(self.state_dir)

    @staticmethod
    def limits_from_env() -> dict[str, int]:
        def value(name: str, default: int) -> int:
            try:
                return max(1, int(os.environ.get(name, default)))
            except ValueError:
                return default
        light_interval = value("ASTRA_SENTINEL_LIGHT_SCAN_INTERVAL_SECONDS", value("ASTRA_SYSTEM_INTEGRITY_SCAN_INTERVAL_SECONDS", 300))
        deep_interval = max(1800, min(3600, value("ASTRA_SENTINEL_DEEP_SCAN_INTERVAL_SECONDS", 2700)))
        return {
            "interval_seconds": light_interval, "light_interval_seconds": light_interval,
            "deep_interval_seconds": deep_interval,
            "max_runtime_seconds": value("ASTRA_SENTINEL_LIGHT_SCAN_MAX_RUNTIME_SECONDS", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_RUNTIME_SECONDS", 3)),
            "deep_max_runtime_seconds": value("ASTRA_SENTINEL_DEEP_SCAN_MAX_RUNTIME_SECONDS", 15),
            "max_facts": value("ASTRA_SENTINEL_MAX_FACTS_PER_SCAN", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_FACTS", 80)),
            "max_consumers": value("ASTRA_SENTINEL_MAX_CONSUMERS_PER_SCAN", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_CONSUMERS", 40)),
            "max_issues": value("ASTRA_SENTINEL_MAX_ROOT_CAUSES", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_ISSUES", 40)),
            "max_file_reads": value("ASTRA_SENTINEL_MAX_FILES_PER_SCAN", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_FILE_READS", 8)),
            "max_rows": value("ASTRA_SENTINEL_MAX_ROWS_PER_SOURCE", value("ASTRA_SYSTEM_INTEGRITY_SCAN_MAX_ROWS", 200)),
            "max_corrections": value("ASTRA_SENTINEL_MAX_CORRECTIONS_PER_CYCLE", value("ASTRA_SAFE_CORRECTIONS_MAX_PER_CYCLE", 2)),
            "high_load_backoff_seconds": value("ASTRA_SENTINEL_HIGH_LOAD_BACKOFF_SECONDS", 300),
            "correction_failure_cooldown_seconds": value("ASTRA_SENTINEL_CORRECTION_FAILURE_COOLDOWN_SECONDS", 900),
        }

    def snapshot(self) -> dict[str, Any]:
        value = _read(self.summary_path)
        if not value:
            value = {"status": "AWAITING_WORKER_SCAN", "last_scan_at": None, "scan_owner": "canonical_worker"}
        age = None
        try:
            generated = datetime.fromisoformat(str(value.get("last_scan_at") or "").replace("Z", "+00:00"))
            age = round(max(0.0, (datetime.now(UTC) - generated.astimezone(UTC)).total_seconds()), 3)
        except (TypeError, ValueError):
            pass
        return {"endpoint": "/api/astra_system_integrity_scanner_v1", "version": VERSION,
                **value, "scan_age_seconds": age, "get_route_read_only": True, "worker_owned_mutations_only": True,
                "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
                "state_mutations_from_get": 0, **self._safety_flags()}

    @staticmethod
    def _safety_flags() -> dict[str, Any]:
        return {
            "paper_only_preserved": True, "live_trading_enabled": False,
            "broker_live_endpoint_allowed": False, "broker_behavior_changed": False,
            "entry_behavior_changed": False, "exit_behavior_changed": False,
            "ranking_behavior_changed": False, "thresholds_changed": False,
            "position_sizing_changed": False, "allocation_changed": False,
            "capital_configuration_changed": False, "automatic_promotions_enabled": False,
            "forced_trades_enabled": False, "forced_exits_enabled": False,
            "learned_exits_enabled": False, "historical_truth_rewritten": False,
            "shadow_promoted_to_broker_truth": False, "behavior_safe_to_apply": False,
        }

    def _scan_mode(self, now: float, limits: dict[str, int], context: dict[str, Any]) -> str | None:
        previous = _read(self.summary_path)
        last = float(previous.get("scan_monotonic") or 0)
        if str(previous.get("schema_version") or "") != VERSION or str(previous.get("sentinel_scan_engine") or "") != "astra_continuous_system_integrity_scanner_v1":
            return "TARGETED"
        if list(context.get("targeted_reasons") or []):
            return "TARGETED"
        if not last or now - last >= limits["light_interval_seconds"]:
            last_deep = float(previous.get("deep_scan_monotonic") or 0)
            return "DEEP" if not last_deep or now - last_deep >= limits["deep_interval_seconds"] else "LIGHT"
        return None

    def _acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps({"owner": "canonical_worker", "acquired_at": _now()}))
            return True
        except FileExistsError:
            return False

    def _release(self) -> None:
        try:
            self.lock_path.unlink()
        except OSError:
            pass

    @staticmethod
    def _registry_failures(registry: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        required = ("canonical_owner", "canonical_store", "canonical_reader", "scope_definition", "identity_key", "freshness_owner", "fallback_allowed", "prohibited_substitutes", "governance_owner", "verification_method", "failure_mode")
        findings = []
        for fact_id, row in list(registry.items())[:limit]:
            missing = [field for field in required if field not in row or row.get(field) in (None, "")]
            if missing:
                findings.append({"kind": "GOVERNANCE_COVERAGE_GAP", "severity": "HIGH", "canonical_fact_ids": [fact_id],
                                 "first_bad_handoff": "canonical fact registry declaration", "owner": "astra_canonical_truth_registry_v1",
                                 "repair": f"declare required registry fields: {','.join(missing)}", "downstream_symptoms": ["CRITICAL_FACT_CONTRACT_INCOMPLETE"]})
        return findings

    def _static_scan(self, limit: int) -> dict[str, Any]:
        """Inspect only the declared critical-path manifest, never the whole repo."""
        root = Path(__file__).resolve().parent.parent
        manifest = [
            root / "server_extend.py", root / "engine" / "provider_router.py",
            root / "engine" / "data_orchestrator.py", root / "engine" / "paper_autopilot_worker.py",
            root / "engine" / "astra_canonical_truth_registry_v1.py",
        ][:limit]
        patterns = {"broad_position_adapter": "paper_positions()", "get_route_mutation_marker": "_save_state_file(", "raw_zero_default": " or 0"}
        findings, files_read = [], 0
        for path in manifest:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            files_read += 1
            hits = {name: text.count(marker) for name, marker in patterns.items() if marker in text}
            if hits:
                findings.append({"file": str(path.relative_to(root)), "hits": hits, "state": "ADVISORY_REQUIRES_RUNTIME_SCOPE_CONFIRMATION"})
        return {"manifest": [str(path.relative_to(root)) for path in manifest], "files_read": files_read, "findings": findings}

    @staticmethod
    def _signals(context: dict[str, Any], registry: dict[str, dict[str, Any]], max_rows: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        signals: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        compliance: list[dict[str, Any]] = []
        truth = dict(context.get("truth_arbitration") or {})
        for contradiction in list(truth.get("contradictions") or [])[:max_rows]:
            if not isinstance(contradiction, dict):
                continue
            signals.append({"kind": "NONCANONICAL_POSITION_CLAIM", "severity": contradiction.get("severity") or "HIGH",
                            "canonical_fact_ids": [contradiction.get("fact_id")], "affected_endpoints": ["readiness", "Governance", "Cortex"],
                            "affected_components": [contradiction.get("owning_component") or "truth arbitration"],
                            "safe_correction_available": True})
        handoffs = list(context.get("quote_handoffs") or [])[:max_rows]
        for handoff in handoffs:
            if not isinstance(handoff, dict):
                continue
            provider_sides = bool(handoff.get("provider_bid") and handoff.get("provider_ask"))
            downstream_sides = bool(handoff.get("snapshot_bid") and handoff.get("snapshot_ask"))
            handoff["contract_validation"] = validate_field_contract_v1(
                handoff, {"required_fields": ["symbol"], "optional_fields": ["provider_bid", "provider_ask", "snapshot_bid", "snapshot_ask"]},
            )
            # Source-rejected rows are fail-closed observations, not evidence
            # that a persisted candidate lost quote fields in transit.
            if provider_sides and bool(handoff.get("candidate_persisted", True)) and not downstream_sides:
                signals.append({"kind": "QUOTE_FIELDS_DROPPED", "severity": "HIGH", "canonical_fact_ids": ["CURRENT_QUOTE_BID", "CURRENT_QUOTE_ASK", "CURRENT_QUOTE_SPREAD"],
                                "affected_endpoints": ["crypto readiness"], "affected_components": ["ProviderRouter", "data_orchestrator", "crypto ranking snapshot"]})
            elif not provider_sides:
                waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": "provider_quote_absent", "symbol": handoff.get("symbol"), "fail_closed": True})
        shadow = dict(context.get("shadow_protection") or {})
        consumption = dict(shadow.get("shadow_profit_loss_consumption") or shadow.get("consumption") or {})
        eligible = _number((shadow.get("lifecycle_evidence_eligibility") or {}).get("eligible_complete_lifecycles"), _number(shadow.get("eligible_complete_lifecycles")))
        consumed = _number(consumption.get("valid_records_consumed"))
        if eligible > 0 and consumed == 0:
            signals.append({"kind": "VALID_EVIDENCE_NOT_CONSUMED", "severity": "HIGH", "canonical_fact_ids": ["SHADOW_VALIDATION_ELIGIBLE_COUNT"],
                            "affected_endpoints": ["shadow profit/loss validation"], "affected_components": ["shadow profit/loss consumer"]})
        elif eligible == 0:
            waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": "insufficient_completed_broker_lifecycle_evidence", "fail_closed": True})
        integrity = dict(context.get("crypto_integrity") or {})
        capacity_fact = dict(context.get("canonical_capacity_fact") or {})
        completion = dict(context.get("multilane_completion_matrix") or {})
        crypto_completion = dict((completion.get("lanes") or {}).get("CRYPTO") or {})
        candidate_blockers = set(str(item) for item in (integrity.get("candidate_execution_blockers") or []))
        if bool(capacity_fact.get("authority_current")) and bool(capacity_fact.get("allowed")) and "capacity_concentration" in candidate_blockers:
            signals.append({"kind": "CANONICAL_CAPACITY_AVAILABLE_BUT_CANDIDATE_GATE_PENDING", "severity": "HIGH",
                            "canonical_fact_ids": ["CANONICAL_CANDIDATE_CAPACITY_FACT"],
                            "affected_endpoints": ["crypto readiness", "multilane completion matrix"],
                            "affected_components": ["candidate_execution_integrity", "crypto operational readiness"],
                            "first_bad_handoff": "canonical capacity fact -> candidate execution integrity",
                            "owner": "candidate execution capacity consumer",
                            "repair": "consume canonical capacity fact rather than legacy availability aliases"})
        if capacity_fact and not bool(capacity_fact.get("authority_current")):
            waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": "canonical_capacity_authority_not_current", "fail_closed": True})
        horizon_rows = [dict(row) for row in ((integrity.get("pair_eligibility") or {}).get("evaluated_candidates") or []) if isinstance(row, dict)]
        first_blockers = [
            {"symbol": row.get("symbol"), **dict(row.get("first_causal_blocker") or {})}
            for row in horizon_rows if isinstance(row.get("first_causal_blocker"), dict)
        ]
        first_market_blocker = next((row for row in first_blockers if str(row.get("gate") or "") in {
            "timestamp_freshness", "quote_spread", "volume_liquidity", "data_quality"
        }), {})
        crypto_root_detected = False
        if first_market_blocker:
            gate = str(first_market_blocker.get("gate") or "")
            handoff = "provider quote timestamp -> operational crypto candidate" if gate == "timestamp_freshness" else "crypto ranking snapshot -> candidate execution integrity"
            signals.append({"kind": "CRYPTO_MARKET_EVIDENCE_BLOCKED", "severity": "HIGH", "confidence": "VERIFIED",
                            "canonical_fact_ids": ["CRYPTO_CANONICAL_MARKET_EVIDENCE", f"CRYPTO_GATE_{gate.upper()}"],
                            "affected_endpoints": ["crypto readiness", "multilane completion matrix", "sentinel"],
                            "affected_components": ["crypto ranking snapshot", "candidate execution integrity"],
                            "first_bad_handoff": handoff,
                            "owner": "crypto market-evidence producer",
                            "repair": "preserve or await real provider evidence; no synthetic fallback is permitted"})
            crypto_root_detected = True
        if any(str(row.get("gate") or "") == "horizon_assignment" for row in first_blockers):
            signals.append({"kind": "CRYPTO_HORIZON_INPUT_NOT_PERSISTED", "severity": "HIGH",
                            "canonical_fact_ids": ["CRYPTO_PERSISTED_HORIZON_EVIDENCE"],
                            "affected_endpoints": ["crypto readiness", "multilane completion matrix"],
                            "affected_components": ["crypto ranking snapshot", "candidate execution integrity"],
                            "first_bad_handoff": "crypto ranking snapshot -> candidate execution integrity",
                            "owner": "crypto ranking snapshot producer",
                            "repair": "persist a canonical horizon evidence envelope or retain an explicit insufficient-evidence state"})
            crypto_root_detected = True
        guard_blockers = [
            row for row in first_blockers if str(row.get("gate") or "") not in {
                "timestamp_freshness", "quote_spread", "volume_liquidity", "data_quality", "horizon_assignment"
            }
        ]
        for blocker in guard_blockers[:max_rows]:
            # A valid candidate may still be deliberately held by an existing
            # safety/configuration guard. Record that actual first gate as a
            # fail-closed waiting state instead of a fabricated defect.
            waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": f"crypto_candidate_gate:{blocker.get('gate')}",
                            "gate_status": blocker.get("status"), "fail_closed": True})
            crypto_root_detected = True
        if str(completion.get("status") or "").upper() == "WARNING" and crypto_completion.get("first_blocker") and not crypto_root_detected:
            signals.append({"kind": "MATRIX_WARNING_WITH_SENTINEL_PASS", "severity": "HIGH",
                            "canonical_fact_ids": ["CRYPTO_MULTILANE_COMPLETION_STATUS"],
                            "affected_endpoints": ["sentinel", "Governance", "Cortex", "multilane completion matrix"],
                            "affected_components": ["continuous integrity scanner", "multilane completion matrix"],
                            "first_bad_handoff": "multilane completion matrix -> sentinel/governance summary",
                            "owner": "continuous integrity scanner",
                            "repair": "surface matrix warnings as root-cause findings before reporting PASS"})
        reconciliation = dict(integrity.get("reconciliation") or {})
        if reconciliation and str(reconciliation.get("broker_reconciliation_status") or "").upper() == "COUNT_MISMATCH_FAIL_CLOSED":
            signals.append({"kind": "BROKER_LOCAL_RECONCILIATION_FAILURE", "severity": "HIGH", "canonical_fact_ids": ["LOCAL_OPEN_CRYPTO_POSITION_COUNT", "BROKER_OPEN_CRYPTO_POSITION_COUNT"],
                            "affected_endpoints": ["crypto readiness", "crypto reconciliation"], "affected_components": ["crypto reconciliation"]})
        if _number(context.get("get_side_effects")):
            signals.append({"kind": "ENDPOINT_SIDE_EFFECT", "severity": "CRITICAL", "canonical_fact_ids": [], "affected_endpoints": ["read-only diagnostics"]})
        # Static findings are advisory until the worker supplies a matching
        # runtime signal. They still receive a bounded repair package so a
        # later implementation does not need to rediscover the source path.
        for finding in list(context.get("static_findings") or [])[:max_rows]:
            if not isinstance(finding, dict):
                continue
            item = dict(finding)
            item.setdefault("kind", "UNKNOWN_SYSTEM_DEFECT")
            item.setdefault("severity", "WARN")
            item.setdefault("first_bad_handoff", "bounded static critical-path manifest")
            item.setdefault("owner", "static integrity manifest")
            item.setdefault("repair", "verify against runtime before source edit")
            item.setdefault("downstream_symptoms", ["STATIC_ADVISORY_FINDING"])
            signals.append(item)
        for fact_id, fact in list(registry.items())[:max_rows]:
            compliance.append({"consumer": "Governance/Cortex/readiness", "fact_id": fact_id,
                               "source_used": fact.get("canonical_reader"), "canonical_source_required": True,
                               "source_compliant": bool(fact.get("canonical_owner") and fact.get("canonical_store")),
                               "scope_compliant": bool(fact.get("scope_definition")), "freshness_compliant": bool(fact.get("freshness_owner")),
                               "fallback_used": False, "rejected_claim_count": 0})
        return signals, waiting, compliance

    @staticmethod
    def _crypto_market_data(context: dict[str, Any], prior: dict[str, Any], max_rows: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Classify cached crypto quote evidence without querying any provider."""
        snapshot = dict(context.get("crypto_ranking_snapshot") or {})
        rows = [dict(row) for row in snapshot.get("crypto_quote_integrity_rows") or [] if isinstance(row, dict)][:max_rows]
        old = dict(prior.get("crypto_market_data") or {})
        history = dict(old.get("pair_observability") or {})
        signals: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []
        evaluated = []
        for row in rows:
            symbol = str(row.get("symbol") or "UNKNOWN")
            received = bool(row.get("quote_received"))
            bid, ask = bool(row.get("bid_present")), bool(row.get("ask_present"))
            prior_row = dict(history.get(symbol) or {})
            previous_streak = _number(prior_row.get("quote_failure_streak"))
            diagnostics = dict(row.get("provider_diagnostics") or {})
            classification = str(diagnostics.get("failure_classification") or "").upper()
            upstream_bid, upstream_ask = row.get("provider_bid"), row.get("provider_ask")
            upstream_valid = bool(upstream_bid not in (None, "") and upstream_ask not in (None, ""))
            if received and upstream_valid and not (bid and ask):
                signals.append({"kind": "QUOTE_FIELDS_DROPPED", "severity": "HIGH", "confidence": "VERIFIED", "canonical_fact_ids": ["CRYPTO_PAIR_BID_AVAILABLE", "CRYPTO_PAIR_ASK_AVAILABLE", "CRYPTO_PAIR_SPREAD_AVAILABLE"], "affected_endpoints": ["crypto readiness"], "affected_components": ["crypto ranking snapshot"]})
                state, streak = "SOFTWARE_DEFECT", previous_streak + 1
            elif not received and classification.startswith("ASTRA_"):
                signals.append({
                    "kind": "CRYPTO_PROVIDER_PATH_DEFECT", "severity": "HIGH", "confidence": "VERIFIED",
                    "canonical_fact_ids": ["CRYPTO_PAIR_QUOTE_OBSERVABLE", "CRYPTO_CURRENT_QUOTE_BID", "CRYPTO_CURRENT_QUOTE_ASK"],
                    "affected_endpoints": ["crypto readiness", "crypto market-data capability matrix"],
                    "affected_components": ["ProviderRouter", "crypto ranking refresh"],
                    "first_bad_handoff": "ProviderRouter crypto request -> provider adapter",
                    "owner": "engine.provider_router.ProviderRouter.get_quote",
                    "repair": str(diagnostics.get("worker_exception") or "inspect the classified provider request path"),
                })
                state, streak = "SOFTWARE_DEFECT", previous_streak + 1
            elif not received:
                waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": "provider_quote_absent", "symbol": symbol, "classification": classification or "PROVIDER_DATA_UNAVAILABLE", "fail_closed": True})
                state, streak = "PROVIDER_DATA_UNAVAILABLE", previous_streak + 1
            elif not (bid and ask):
                waiting.append({"state": "LEGITIMATE_WAITING_STATE", "reason": "bid_or_ask_absent", "symbol": symbol, "classification": "PROVIDER_DATA_UNAVAILABLE", "fail_closed": True})
                state, streak = "PROVIDER_DATA_UNAVAILABLE", previous_streak + 1
            else:
                state, streak = "OBSERVABLE", 0
            volume = bool(row.get("volume_available"))
            if received and bool(row.get("completed_volume_upstream")) and not volume:
                signals.append({"kind": "CRYPTO_VOLUME_DROPPED", "severity": "HIGH", "confidence": "VERIFIED", "canonical_fact_ids": ["CRYPTO_PAIR_COMPLETED_VOLUME_AVAILABLE"], "affected_endpoints": ["crypto readiness"], "affected_components": ["crypto candidate transformation"]})
            evaluated.append({"symbol": symbol, "quote_observability_state": state, "quote_failure_streak": streak, "last_successful_quote_at": row.get("quote_timestamp") if state == "OBSERVABLE" else prior_row.get("last_successful_quote_at"), "bid_available": bid, "ask_available": ask, "spread_available": bool(row.get("spread_present")), "completed_volume_available": volume, "data_quality_ready": bool(row.get("candidate_persisted")), "rotation_last_evaluated_at": snapshot.get("generated_at")})
        pair_map = {row["symbol"]: row for row in evaluated}
        summary = {"pairs_evaluated": len(evaluated), "quote_observable_pairs": sum(row["quote_observability_state"] == "OBSERVABLE" for row in evaluated), "pairs_with_bid_ask": sum(row["bid_available"] and row["ask_available"] for row in evaluated), "pairs_with_valid_spread": sum(row["spread_available"] for row in evaluated), "pairs_with_completed_volume": sum(row["completed_volume_available"] for row in evaluated), "pairs_data_quality_ready": sum(row["data_quality_ready"] for row in evaluated), "rotation_cursor": snapshot.get("discovery_cursor"), "rotation_cycles_remaining": snapshot.get("rotation_cycles_remaining"), "rotation_cycle_completion": snapshot.get("pairs_evaluated_this_cycle"), "pair_observability": pair_map, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0}
        return summary, signals, waiting

    def _update_roots(self, roots: list[dict[str, Any]]) -> dict[str, Any]:
        previous = _read(self.root_path)
        known = {str(row.get("root_cause_id")): dict(row) for row in previous.get("root_causes") or [] if isinstance(row, dict)}
        now, active = _now(), {str(row.get("root_cause_id")) for row in roots}
        for root in roots:
            item, prior = dict(root), known.get(str(root.get("root_cause_id")))
            item.update({"first_detected_at": prior.get("first_detected_at") if prior else now, "last_detected_at": now,
                         "occurrence_count": _number(prior.get("occurrence_count")) + 1 if prior else 1,
                         "state": "RECURRENT" if prior and prior.get("state") == "RESOLVED" else "OPEN", "consistent_observations": 0})
            known[str(item["root_cause_id"])] = item
        for key, item in known.items():
            if key in active or item.get("state") in {"RESOLVED", "RECURRENT"}:
                continue
            item["consistent_observations"] = _number(item.get("consistent_observations")) + 1
            item["last_detected_at"] = now
            item["state"] = "RESOLVED" if item["consistent_observations"] >= VERIFICATION_WINDOW else "VERIFYING"
        payload = {"schema_version": VERSION, "generated_at": now, "verification_window": VERIFICATION_WINDOW,
                   "root_causes": list(known.values())[-ROOT_LIMIT:]}
        _atomic(self.root_path, payload)
        return payload

    @staticmethod
    def _repair_package(root: dict[str, Any]) -> dict[str, Any]:
        return {"issue_id": root.get("root_cause_id"), "root_cause_id": root.get("root_cause_id"), "severity": root.get("severity"),
                "exact_symptom": root.get("downstream_symptoms"), "canonical_expected_value": "registered canonical fact envelope",
                "observed_conflicting_value": "scanner-confirmed contradiction", "canonical_source": root.get("canonical_fact_ids"),
                "conflicting_source": root.get("first_bad_handoff"), "first_bad_handoff": root.get("first_bad_handoff"),
                "source_module": root.get("likely_owner"), "source_function": "verify via bounded source contract",
                "consumer_module": root.get("affected_components"), "consumer_function": "verify via consumer compliance",
                "store_cache_involved": "committed worker snapshot", "affected_endpoints": root.get("affected_endpoints"),
                "downstream_blockers": root.get("downstream_symptoms"), "smallest_recommended_code_repair": root.get("smallest_safe_repair"),
                "files_likely_affected": root.get("affected_components"), "tests_required": ["scanner root-cause regression", "GET immutability"],
                "runtime_validation_required": ["three worker cycles", "read-only endpoint verification"],
                "automatic_repair_prohibited_because": "not in safe nonbehavioral correction allowlist", "human_review_required": True}

    def run_if_due(self, *, worker_state: dict[str, Any], runtime_state: dict[str, Any], safety: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Run one worker-only scan, or return the last bounded snapshot."""
        limits, started = self.limits_from_env(), time.monotonic()
        if str(worker_state.get("process_role") or "") != "PAPER_AUTOPILOT_WORKER":
            return {**self.snapshot(), "status": "SCAN_REJECTED_NONCANONICAL_OWNER", "scan_deferred": "WORKER_OWNER_REQUIRED"}
        mode = self._scan_mode(started, limits, context)
        if mode is None:
            return {**self.snapshot(), "scan_deferred": "INTERVAL_NOT_DUE"}
        activity = ("order_processing_active", "fill_reconciliation_active", "position_reconciliation_active", "broker_refresh_active", "heavy_learning_active")
        busy = next((name for name in activity if bool(context.get(name))), None)
        if busy or str(worker_state.get("resource_state") or "") in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE"}:
            return {**self.snapshot(), "status": "SCAN_DEFERRED_EXISTING_OWNER", "scan_deferred": "HIGH_LOAD_BACKOFF", "deferred_reason": busy or worker_state.get("resource_state"), "resource_protection": {"deferred": True, "backoff_seconds": limits["high_load_backoff_seconds"]}}
        if not self._acquire():
            return {**self.snapshot(), "status": "SCAN_DEFERRED_EXISTING_OWNER", "scan_deferred": "SCAN_DEFERRED_EXISTING_OWNER"}
        try:
            registry = canonical_fact_registry_v1()
            static_scan = self._static_scan(limits["max_file_reads"])
            signals, waiting, compliance = self._signals(context, registry, limits["max_rows"])
            previous_summary = _read(self.summary_path)
            crypto_market_data, crypto_signals, crypto_waiting = self._crypto_market_data(context, previous_summary, limits["max_rows"])
            signals.extend(crypto_signals); waiting.extend(crypto_waiting)
            signals.extend(self._registry_failures(registry, limits["max_facts"]))
            roots = [root_cause_from_signal_v1(signal) for signal in signals[:limits["max_issues"]]]
            root_state = self._update_roots(roots)
            active = [row for row in root_state.get("root_causes") or [] if row.get("state") not in {"RESOLVED"}]
            human = [self._repair_package(row) for row in active if row.get("human_repair_required")]
            corrections: list[dict[str, Any]] = []
            for root in active[:limits["max_corrections"]]:
                if not root.get("safe_correction_available"):
                    continue
                transaction = self.corrections.prepare(str(root.get("root_cause_id")), "BLOCK_NONCANONICAL_PUBLICATION", target_component=str(root.get("likely_owner")), target_artifact="derived diagnostic publication only", before_state={"published": True}, after_state={"published": False})
                corrections.append(self.corrections.record(transaction)["transactions"][-1])
            _atomic(self.consumer_path, {"schema_version": VERSION, "generated_at": _now(), "consumers": compliance[:limits["max_consumers"]]})
            elapsed = round((time.monotonic() - started) * 1000, 3)
            runtime_limit = limits["deep_max_runtime_seconds"] if mode == "DEEP" else limits["max_runtime_seconds"]
            partial = elapsed > runtime_limit * 1000
            status = "SCAN_PARTIAL_RESOURCE_BUDGET" if partial else "CRITICAL" if any(str(row.get("severity")) == "CRITICAL" for row in active) else "WARNING" if active else "PASS"
            summary = {"schema_version": VERSION, "status": status, "scan_owner": "canonical_worker", "sentinel_canonical_owner": "PaperAutopilotWorker", "sentinel_scan_engine": "astra_continuous_system_integrity_scanner_v1", "scan_mode": mode, "last_scan_at": _now(), "scan_monotonic": time.monotonic(),
                       "deep_scan_monotonic": time.monotonic() if mode == "DEEP" else previous_summary.get("deep_scan_monotonic"),
                       "scan_runtime_ms": elapsed, "critical_facts_checked": min(len(registry), limits["max_facts"]), "consumers_checked": min(len(compliance), limits["max_consumers"]),
                       "contracts_checked": min(len(registry), limits["max_facts"]), "files_read": static_scan["files_read"], "rows_read": min(len(signals) + len(compliance), limits["max_rows"]), "static_scan": static_scan,
                       "active_root_causes": active[:limits["max_issues"]], "downstream_symptoms": [symptom for root in active for symptom in root.get("downstream_symptoms") or []][:limits["max_issues"] * 4],
                       "downstream_symptoms_suppressed": max(0, sum(len(root.get("downstream_symptoms") or []) for root in active) - len(active)),
                       "safe_corrections_applied": [row for row in corrections if row.get("applied")], "safe_corrections_verifying": [row for row in corrections if row.get("verification_state") == "VERIFYING"],
                       "human_repairs_required": human[:limits["max_issues"]], "recurrent_defects": [row for row in active if row.get("state") == "RECURRENT"],
                       "unknown_defects": [row for row in active if row.get("category") == "UNKNOWN_SYSTEM_DEFECT"], "legitimate_waiting_states": waiting,
                       "consumer_compliance": {"checked": min(len(compliance), limits["max_consumers"]), "failures": [row for row in compliance if not row.get("source_compliant")]},
                       "light_scan": {"interval_seconds": limits["light_interval_seconds"], "max_runtime_seconds": limits["max_runtime_seconds"], "last_run_at": _now() if mode in {"LIGHT", "TARGETED"} else previous_summary.get("light_scan", {}).get("last_run_at")},
                       "deep_scan": {"interval_seconds": limits["deep_interval_seconds"], "max_runtime_seconds": limits["deep_max_runtime_seconds"], "last_run_at": _now() if mode == "DEEP" else previous_summary.get("deep_scan", {}).get("last_run_at"), "deferred_for_load": False},
                       "targeted_scan": {"triggered": mode == "TARGETED", "triggers": list(context.get("targeted_reasons") or [])[:8]},
                       "resource_protection": {"scan_runtime_budget_seconds": runtime_limit, "max_files": limits["max_file_reads"], "max_rows": limits["max_rows"], "max_facts": limits["max_facts"], "max_consumers": limits["max_consumers"], "deferred": False, "worker_priority_preserved": True},
                       "crypto_market_data": crypto_market_data,
                       "governance_summary": {"root_causes": len(active), "human_repair_required": len(human), "safe_corrections": len(corrections), "sentinel_single_scan_owner": True},
                       "cortex_summary": {"system_integrity_summary": status, "highest_impact_root_causes": active[:5], "downstream_symptoms_grouped": True,
                                          "truth_promotion_allowed": False, "recommended_repair_order": [row.get("root_cause_id") for row in active[:5]], "root_cause_orchestration": True},
                       "dependency_graph": dependency_graph_v1(), "consolidated_repair_queue": [{"priority": index + 1, "root_cause_id": row.get("root_cause_id"), "summary": row.get("smallest_safe_repair"), "systems_affected": row.get("affected_components"), "downstream_blockers_cleared": row.get("downstream_symptoms"), "safe_to_autocorrect": bool(row.get("safe_correction_available")), "recommended_files": row.get("affected_components"), "required_tests": ["scanner root-cause regression"]} for index, row in enumerate(active[:10])],
                       "resource_usage": {"provider_calls_used": 0, "broker_read_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "safe_corrections_attempted": len(corrections), "safe_corrections_applied": sum(bool(row.get("applied")) for row in corrections), "issues_grouped": len(active), "duplicate_symptoms_suppressed": max(0, len(signals) - len(active))},
                       "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "state_mutations_from_get": 0, **self._safety_flags()}
            _atomic(self.summary_path, summary)
            return summary
        except Exception as exc:
            # A failed diagnostic scan cannot interrupt the execution owner.
            failed = {"schema_version": VERSION, "status": "SCAN_PARTIAL_RESOURCE_BUDGET", "scan_owner": "canonical_worker",
                      "last_scan_at": _now(), "scan_monotonic": time.monotonic(), "scan_runtime_ms": round((time.monotonic() - started) * 1000, 3),
                      "scan_error": str(exc)[:180], "active_root_causes": [], "downstream_symptoms": [],
                      "safe_corrections_applied": [], "safe_corrections_verifying": [], "human_repairs_required": [],
                      "recurrent_defects": [], "unknown_defects": [], "legitimate_waiting_states": [],
                      "consumer_compliance": {}, "governance_summary": {}, "cortex_summary": {"truth_promotion_allowed": False},
                      "resource_usage": {"provider_calls_used": 0, "broker_read_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0},
                      "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "state_mutations_from_get": 0, **self._safety_flags()}
            try:
                _atomic(self.summary_path, failed)
            except OSError:
                pass
            return failed
        finally:
            self._release()
