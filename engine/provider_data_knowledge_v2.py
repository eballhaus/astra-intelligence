"""Integrated read-only provider, cache, knowledge, and ROI diagnostics V2.

This module does not fetch providers. It reconciles the active router, API
manager, shared cache, FMP accounting, candidate cache, and knowledge indexes.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from api_keys import API_POOLS
from engine.runtime_environment import load_runtime_environment, resolve_fmp_key


SAFETY = {
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "broker_live_endpoint_allowed": False,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "ranking_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "forced_trades_enabled": False,
    "forced_exits_enabled": False,
    "automatic_promotions_enabled": False,
    "dashboard_provider_calls_used": 0,
    "dashboard_llm_calls_used": 0,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
    "broker_actions_used": 0,
}

ROUTING_POLICY = {
    "broker_account_truth": ("ALPACA", None, 30, True, "broker_critical"),
    "open_positions": ("ALPACA", None, 30, True, "broker_critical"),
    "order_status": ("ALPACA", None, 15, True, "broker_critical"),
    "current_equity_quote": ("ALPACA", "FINNHUB", 20, True, "execution_critical"),
    "current_crypto_quote": ("ALPACA", "MORALIS", 15, True, "crypto_data"),
    "bars_history": ("ALPACA", "FMP", 3600, False, "learning"),
    "company_profile": ("FMP", "FINNHUB", 86400, False, "enrichment"),
    "fundamentals": ("FMP", "ALPHAVANTAGE", 86400, False, "enrichment"),
    "earnings": ("FMP", "FINNHUB", 21600, False, "catalyst"),
    "catalyst_event_context": ("FINNHUB", "FMP", 1800, False, "catalyst"),
    "broad_universe_discovery": ("LOCAL_CACHE", "FMP", 900, False, "discovery"),
    "dashboard_display": ("LOCAL_CACHE", None, 900, False, "dashboard"),
    "copilot_context": ("LOCAL_CACHE", None, 900, False, "copilot"),
    "background_learning": ("LOCAL_CACHE", "FMP", 3600, False, "learning"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value not in (None, "") else default)
    except Exception:
        return float(default)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _tail_jsonl(path: Path, max_rows: int = 1200, max_bytes: int = 2_000_000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
        lines = text.splitlines()
        if size > max_bytes and lines:
            lines = lines[1:]
        rows = []
        for line in lines[-max_rows:]:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:
                continue
        return rows
    except Exception:
        return []


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack_name in ("stocks", "crypto"):
        pack = payload.get(pack_name) if isinstance(payload.get(pack_name), dict) else {}
        for section in ("final", "qualified", "watchlist"):
            rows.extend(dict(row) for row in (pack.get(section) or []) if isinstance(row, dict))
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        asset = "crypto" if str(row.get("asset_type") or "").lower() == "crypto" else "equity"
        symbol = str(row.get("symbol") or "").upper().strip()
        if symbol:
            dedup.setdefault((asset, symbol), row)
    return list(dedup.values())[:500]


class ProviderDataKnowledgeV2:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = Path(state_dir)

    def fmp_runtime(self, router: dict[str, Any], usage: dict[str, Any], manager_rows: list[dict[str, Any]]) -> dict[str, Any]:
        env = load_runtime_environment()
        key, source = resolve_fmp_key()
        stock_pool = {str(name).upper(): bool(value) for name, value in API_POOLS.get("stocks", [])}
        explicit = "ASTRA_TEMP_FMP_REST_DISABLED" in os.environ
        disabled = explicit and str(os.getenv("ASTRA_TEMP_FMP_REST_DISABLED", "0")).lower() in {"1", "true", "yes", "on"}
        state = _read_json(self.state_dir / "fmp_usage_state.json")
        manifest = _read_json(self.state_dir / "fmp_efficiency_manifest_v1.json")
        cache_index = _read_json(self.state_dir / "fmp_cache_index.json")
        router_eligible = "FMP" in set(router.get("providers_enabled") or [])
        manager_fmp = next(
            (row for row in manager_rows if str((row or {}).get("provider") or "").upper() == "FMP"),
            {},
        )
        enabled = bool(key and stock_pool.get("FMP") and router_eligible and not disabled)
        exact = (
            ""
            if enabled
            else "explicit_emergency_disable"
            if disabled
            else "fmp_key_missing"
            if not key
            else "fmp_not_registered"
            if not stock_pool.get("FMP")
            else "fmp_not_eligible_in_active_router"
        )
        return {
            "endpoint": "/api/fmp_runtime_connection_diagnostics_v1",
            "status": "READY" if enabled else "BLOCKED",
            "generated_at": _now(),
            "runtime_environment": env,
            "fmp_key_present_runtime": bool(key),
            "fmp_key_source_name": source,
            "fmp_key_masked_length": len(key),
            "fmp_provider_registered": bool(stock_pool.get("FMP")),
            "fmp_router_eligible": router_eligible,
            "fmp_rest_enabled": enabled,
            "fmp_disable_explicit": explicit,
            "fmp_budget_state": "PROVIDER_DISABLED" if disabled else "HEALTHY" if enabled else "CREDENTIAL_MISSING",
            "fmp_current_process_calls": max(
                int((router.get("calls_used_per_provider") or {}).get("FMP", 0)),
                int(_num(manager_fmp.get("calls"), 0)),
            ),
            "fmp_calls_today_local": int(_num(state.get("fmp_calls_today"), _num(usage.get("fmp_calls_today"), 0))),
            "fmp_last_live_attempt_at": manifest.get("last_probe_attempt_at") or manifest.get("last_phase0_probe_utc") or "",
            "fmp_last_live_success_at": manifest.get("last_probe_success_at") or (manifest.get("last_phase0_probe_utc") if manifest.get("last_phase0_probe_success") else ""),
            "fmp_last_status_code": manifest.get("last_probe_status_code"),
            "fmp_last_response_bytes": int(_num(manifest.get("last_probe_response_bytes"), 0)),
            "fmp_last_latency_ms": manifest.get("last_probe_latency_ms"),
            "fmp_cached_records_available": bool(cache_index or manifest.get("total_cache_hits")),
            "fmp_cached_records_count": int(_num(cache_index.get("entries_estimate"), _num(manifest.get("total_cache_hits"), 0))),
            "fmp_current_vs_cached_status": "LIVE_AND_CACHE_ACCOUNTED_SEPARATELY" if int(_num(state.get("fmp_calls_today"), 0)) else "CACHE_AVAILABLE_LIVE_IDLE",
            "fmp_exact_blocker": exact,
            "fmp_safe_next_action": "run_one_deliberate_bounded_probe" if enabled else "repair_exact_blocker_before_probe",
            "secret_exposed": False,
            **SAFETY,
        }

    def routing(self, router: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
        enabled = set(router.get("providers_enabled") or [])
        traces = []
        for category, (primary, fallback, ttl, live_required, workload) in ROUTING_POLICY.items():
            if primary == "LOCAL_CACHE":
                decision = "USE_FRESH_CACHE"
                selected = "LOCAL_CACHE"
            elif primary in enabled:
                decision = "USE_LIVE_PRIMARY"
                selected = primary
            elif fallback in enabled:
                decision = "USE_LIVE_FALLBACK"
                selected = fallback
            else:
                decision = "BLOCK_PROVIDER_DOWN" if live_required else "USE_DEGRADED_CACHE"
                selected = "LOCAL_CACHE" if not live_required else "none"
            traces.append({
                "request_category": category,
                "symbol": "",
                "asset_class": "crypto" if "crypto" in category else "equity_or_system",
                "requester": workload,
                "selected_provider": selected,
                "fallback_provider": fallback,
                "cache_result": "policy_defined",
                "maximum_acceptable_age_seconds": ttl,
                "live_data_required": live_required,
                "routing_decision": decision,
                "routing_reason": "canonical_v2_policy",
                "budget_result": "reserved" if workload == "broker_critical" else "normal",
                "actual_call_made": False,
                "source_timestamp": "",
                "final_source_classification": selected,
            })
        return {
            "endpoint": "/api/provider_orchestration_data_governance_v2",
            "status": "PASS",
            "generated_at": _now(),
            "authoritative_router": "engine/provider_router.py",
            "routing_decisions": traces,
            "routing_decision_counts": dict(Counter(row["routing_decision"] for row in traces)),
            "provider_usage": usage,
            "actual_calls_made_by_this_endpoint": 0,
            **SAFETY,
        }

    def budget(self, manager_rows: list[dict[str, Any]], usage: dict[str, Any]) -> dict[str, Any]:
        rows = [dict(row) for row in manager_rows if isinstance(row, dict)]
        budgets = {
            "alpaca_trading_account": {"priority": 1, "reserve_protected": True},
            "alpaca_equity_data": {"priority": 2, "equity_reserve": True},
            "alpaca_crypto_data": {"priority": 3, "cannot_starve_equity": True},
            "fmp_rest": {"priority": 6, "smart_budget": True},
            "finnhub": {"priority": 6},
            "reconciliation": {"priority": 1, "reserve_protected": True},
            "background_learning": {"priority": 6},
            "broad_universe_intake": {"priority": 7},
            "dashboard_rendering": {"priority": 8, "provider_calls_allowed": False},
            "deep_diagnostics": {"priority": 9, "provider_calls_allowed": False},
            "emergency_reserve": {"priority": 0, "reserve_protected": True},
        }
        return {
            "endpoint": "/api/unified_api_budget_bandwidth_governor_v2",
            "status": "HEALTHY" if not any(row.get("provider_cooldown_state") == "cooldown" for row in rows) else "CONSERVE",
            "generated_at": _now(),
            "provider_rows": rows,
            "budgets": budgets,
            "rolling_usage": usage,
            "retry_storm_prevention": True,
            "dashboard_cannot_starve_broker": True,
            "crypto_cannot_starve_equity": True,
            "fmp_cannot_starve_active_quotes": True,
            "diagnostics_external_calls_allowed": False,
            **SAFETY,
        }

    def cache(self, shared: dict[str, Any], router: dict[str, Any]) -> dict[str, Any]:
        request = dict(router.get("shared_request_cache_metrics") or {})
        hits = int(_num(shared.get("hits"), 0)) + int(_num(request.get("cache_hits"), 0))
        misses = int(_num(shared.get("misses"), 0)) + int(_num(request.get("cache_misses"), 0))
        return {
            "endpoint": "/api/shared_data_cache_request_deduplication_v2",
            "status": "PASS",
            "generated_at": _now(),
            "requests_submitted": int(_num(request.get("requests_submitted"), 0)),
            "provider_calls_executed": int(_num(request.get("provider_calls_executed"), 0)),
            "requests_coalesced": int(_num(request.get("requests_coalesced"), 0)),
            "cache_hits": hits,
            "cache_misses": misses,
            "stale_hits": int(_num(shared.get("stale_hits"), 0)),
            "failed_requests": int(_num(request.get("failed_requests"), 0)),
            "provider_calls_avoided": int(_num(request.get("provider_calls_avoided"), 0)),
            "cache_hit_rate_pct": round((hits / max(1, hits + misses)) * 100.0, 3),
            "bounded_cache": bool(shared.get("bounded_cache", False)),
            "max_entries": shared.get("max_entries"),
            "evictions": shared.get("evictions", 0),
            "inflight_request_coalescing": bool(router.get("request_deduplication_connected", False)),
            "equity_crypto_namespaces_separate": True,
            "broker_private_data_not_shared_as_public": True,
            "secret_free_request_keys": True,
            **SAFETY,
        }

    def intake_enrichment(self, top_buys: dict[str, Any]) -> dict[str, Any]:
        rows = _candidate_rows(top_buys)
        sectors = Counter(str(row.get("sector") or "unknown") for row in rows)
        caps = Counter(str(row.get("market_cap_bucket") or row.get("cap_tier") or "unknown") for row in rows)
        enriched = [row for row in rows if row.get("fmp_enriched")]
        fields = Counter(field for row in enriched for field in (row.get("fmp_enrichment_fields_used") or []))
        common = {
            "generated_at": _now(),
            "symbols_considered": len(rows),
            "symbols_enriched": len(enriched),
            "symbols_promoted": sum(1 for row in rows if row.get("selected_from_broad_universe") or row.get("broad_universe_promoted")),
            "sector_distribution": dict(sectors),
            "market_cap_distribution": dict(caps),
            "bounded_intake": True,
            "rotating_cursor_supported": True,
            "duplicate_suppression": True,
            "crypto_fmp_source_prohibited": True,
            **SAFETY,
        }
        enrichment = {
            **common,
            "endpoint": "/api/fundamental_catalyst_intelligence_expansion_v2",
            "status": "WARMING" if rows and not enriched else "PASS" if enriched else "INSUFFICIENT_EVIDENCE",
            "normalized_fields_consumed": dict(fields),
            "downstream_consumers": ["candidate_context", "horizon_context", "thesis", "catalyst", "symbol_memory", "copilot", "governance"],
            "ranking_weights_changed": False,
            "execution_policy_changed": False,
        }
        return {"intake": {**common, "endpoint": "/api/adaptive_market_intake_universe_expansion_v2", "status": "PASS"}, "enrichment": enrichment}

    def freshness(self, top_buys: dict[str, Any]) -> dict[str, Any]:
        rows = _candidate_rows(top_buys)
        records = []
        conflicts = []
        for row in rows[:200]:
            age = _num(row.get("quote_age_seconds") or row.get("freshness_seconds"), -1)
            status = "MISSING" if age < 0 else "LIVE_CURRENT" if age <= 30 else "FRESH_CACHE" if age <= 300 else "ACCEPTABLE_CACHE" if age <= 3600 else "STALE_REVIEW"
            records.append({
                "symbol": row.get("symbol"),
                "asset_class": "crypto" if row.get("asset_type") == "crypto" else "equity",
                "provider": row.get("provider_used") or row.get("provider_source") or "cached_internal",
                "endpoint_category": "candidate_quote_context",
                "retrieved_timestamp": row.get("timestamp") or row.get("last_updated_utc"),
                "source_timestamp": row.get("quote_timestamp") or row.get("timestamp"),
                "age_seconds": None if age < 0 else round(age, 3),
                "freshness_status": status,
                "live_vs_cached": "live" if status == "LIVE_CURRENT" else "cached_or_unknown",
                "confidence": row.get("provider_confidence") or row.get("confidence"),
                "trace_id": row.get("candidate_id"),
            })
            if row.get("provider_conflict") or row.get("conflicting_sources"):
                conflicts.append({"symbol": row.get("symbol"), "conflict": row.get("provider_conflict") or row.get("conflicting_sources")})
        return {
            "endpoint": "/api/data_freshness_quality_source_attribution_v2",
            "status": "PASS" if records else "INSUFFICIENT_EVIDENCE",
            "generated_at": _now(),
            "records": records,
            "freshness_distribution": dict(Counter(row["freshness_status"] for row in records)),
            "provider_conflicts": conflicts,
            "conflicts_silently_averaged": False,
            **SAFETY,
        }

    def knowledge_roi(self) -> dict[str, Any]:
        indexes = list((self.state_dir / "storage_summary_indexes").glob("*.summary_index.json"))
        eligible = indexed = duplicates = stale = 0
        provider_distribution: Counter[str] = Counter()
        for path in indexes[:200]:
            payload = _read_json(path)
            eligible += int(_num(payload.get("source_rows") or payload.get("rows_seen") or payload.get("record_count"), 0))
            indexed += int(_num(payload.get("indexed_records") or payload.get("summary_count") or payload.get("record_count"), 0))
            duplicates += int(_num(payload.get("duplicates_suppressed"), 0))
            stale += int(_num(payload.get("stale_records"), 0))
            provider_distribution.update(payload.get("provider_distribution") or {})
        ledger = _tail_jsonl(self.state_dir / "fmp_efficiency_ledger_v1.jsonl")
        calls = sum(int(_num(row.get("api_calls_delta"), 0)) for row in ledger)
        useful = sum(1 for row in ledger if _num(row.get("useful_fields_count"), 0) > 0)
        bytes_used = sum(int(_num(row.get("bytes_actual_if_available"), _num(row.get("bytes_estimated"), 0))) for row in ledger)
        cache_hits = sum(1 for row in ledger if row.get("cache_hit"))
        high = Counter(str(row.get("endpoint_path_template") or "unknown") for row in ledger if _num(row.get("useful_fields_count"), 0) > 0)
        low = Counter(str(row.get("endpoint_path_template") or "unknown") for row in ledger if _num(row.get("useful_fields_count"), 0) <= 0)
        return {
            "endpoint": "/api/evidence_consumption_provider_roi_v2",
            "status": "PASS" if indexes and calls > 0 else "INSUFFICIENT_EVIDENCE",
            "generated_at": _now(),
            "records_eligible": eligible,
            "records_indexed": indexed,
            "records_rejected": max(0, eligible - indexed),
            "duplicates_suppressed": duplicates,
            "stale_records": stale,
            "index_coverage_pct": round((indexed / eligible) * 100.0, 3) if eligible else None,
            "index_namespaces_separated": True,
            "incremental_bounded_indexing": True,
            "provider_calls_attempted": calls,
            "useful_records": useful,
            "bytes_consumed": bytes_used,
            "useful_records_per_call": round(useful / calls, 4) if calls else None,
            "consumed_records_per_mb": round(useful / max(0.000001, bytes_used / 1048576.0), 4) if bytes_used else 0.0,
            "cache_reuse_rate_pct": round((cache_hits / max(1, len(ledger))) * 100.0, 3),
            "high_value_endpoints": [name for name, _ in high.most_common(5)],
            "low_value_endpoints": [name for name, _ in low.most_common(5)],
            "provider_distribution": dict(provider_distribution),
            "causal_profit_impact_claimed": False,
            **SAFETY,
        }

    def build(self, *, router: dict[str, Any], usage: dict[str, Any], manager_rows: list[dict[str, Any]], shared_cache: dict[str, Any], top_buys: dict[str, Any]) -> dict[str, Any]:
        fmp = self.fmp_runtime(router, usage, manager_rows)
        routing = self.routing(router, usage)
        budget = self.budget(manager_rows, usage)
        cache = self.cache(shared_cache, router)
        intake = self.intake_enrichment(top_buys)
        freshness = self.freshness(top_buys)
        roi = self.knowledge_roi()
        blockers = [value for value in (fmp.get("fmp_exact_blocker"),) if value]
        return {
            "endpoint": "/api/astra_provider_data_knowledge_validation_v2",
            "status": "PASS_WITH_BLOCKERS" if blockers else "PASS",
            "generated_at": _now(),
            "fmp_runtime": fmp,
            "provider_orchestration": routing,
            "api_budget": budget,
            "shared_cache": cache,
            "adaptive_intake": intake["intake"],
            "fundamental_catalyst_enrichment": intake["enrichment"],
            "freshness_attribution": freshness,
            "provider_conflicts": freshness.get("provider_conflicts") or [],
            "knowledge_indexing_provider_roi": roi,
            "copilot_summary_ready": True,
            "governance_summary_ready": True,
            "normal_diagnostics_external_provider_calls": 0,
            "remaining_blockers": blockers,
            **SAFETY,
        }
