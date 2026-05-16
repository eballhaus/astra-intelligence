"""API Efficiency and Synthetic Learning Expansion Suite V1.

Planning/reporting only. This module reads local cache, warehouse, universe, and
replay metadata to reduce future API calls and expand shadow learning examples
without making provider calls, writing files, or changing trading behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, deque
from datetime import UTC, date, datetime, timedelta
from typing import Any


VERSION = "1.0.0"
BROAD_UNIVERSE_TARGET_COUNT = 7500
ACTIVE_UNIVERSE_TARGET_COUNT = 200
SMALL_BATCH_LIMIT = 25


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _today() -> str:
    return date.today().isoformat()


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:
        pass
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return None


class ApiEfficiencySuite:
    """Builds no-call efficiency, TTL, dedup, priority, and replay plans."""

    def __init__(self, state_dir: str = "state", fmp_optimizer: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.fmp_optimizer = fmp_optimizer
        self.paths = {
            "warehouse_manifest": os.path.join(self.state_dir, "market_data_warehouse_manifest_v1.json"),
            "fmp_enrichment_cache": os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json"),
            "fmp_cache_index": os.path.join(self.state_dir, "fmp_cache_index.json"),
            "runtime_snapshot": os.path.join(self.state_dir, "runtime_top_buys_snapshot.json"),
            "trade_lifecycle": os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"),
            "outcome_labels": os.path.join(self.state_dir, "outcome_labels_v1.jsonl"),
            "candidate_ledger": os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
            "replay_results": os.path.join(self.state_dir, "replay_results_v2.json"),
            "universe_cache": os.path.join("astra_dashboard", "universe", "universe_cache.json"),
        }
        self.ttl_policy = {
            "live_quotes": {
                "ttl_seconds": 30,
                "owner": "alpaca_iex",
                "fmp_duplicate_allowed": False,
                "refresh_style": "provider_owned_not_fmp_duplicate",
            },
            "recent_ohlcv": {"ttl_seconds": 3600, "owner": "fmp_when_optimizer_allows", "refresh_style": "delta_only_incremental"},
            "old_ohlcv": {"ttl_seconds": 2592000, "owner": "fmp_when_missing", "refresh_style": "rarely_or_never_after_complete"},
            "fundamentals": {"ttl_seconds": 604800, "owner": "fmp", "refresh_style": "weekly_to_monthly"},
            "ratios": {"ttl_seconds": 604800, "owner": "fmp", "refresh_style": "weekly_to_monthly"},
            "earnings_calendar": {"ttl_seconds": 86400, "owner": "fmp_or_finnhub_backup", "refresh_style": "daily"},
            "company_profile": {"ttl_seconds": 2592000, "owner": "fmp", "refresh_style": "monthly"},
            "sector_industry": {"ttl_seconds": 604800, "owner": "fmp", "refresh_style": "weekly_to_monthly"},
            "replay_counterfactual_source_data": {"ttl_seconds": 86400, "owner": "local_warehouse", "refresh_style": "when_missing_or_stale"},
        }
        self.scenarios = [
            "alternative_entry_times",
            "stop_loss_1pct",
            "stop_loss_2pct",
            "trailing_stop_50pct_capture",
            "trailing_stop_70pct_capture",
            "hold_time_half",
            "hold_time_double",
            "earlier_exit_comparison",
            "later_exit_comparison",
            "best_worst_capture_ratio",
        ]

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _tail_jsonl(self, path: str, max_rows: int = 5000) -> list[dict[str, Any]]:
        rows: deque[dict[str, Any]] = deque(maxlen=max(1, int(max_rows)))
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = str(raw or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return list(rows)

    def _count_jsonl(self, path: str, max_scan: int = 20000) -> int:
        if not os.path.exists(path):
            return 0
        count = 0
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for count, _line in enumerate(fh, start=1):
                    if count >= max_scan:
                        break
        except Exception:
            return 0
        return int(count)

    def _file_age_seconds(self, path: str) -> float | None:
        try:
            return max(0.0, time.time() - os.path.getmtime(path))
        except Exception:
            return None

    def _fmp_status(self) -> dict[str, Any]:
        if self.fmp_optimizer is None:
            return {
                "enabled": False,
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_unavailable",
            }
        try:
            payload = self.fmp_optimizer.status()
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            return {
                "enabled": False,
                "current_usage_pct_estimated": 0.0,
                "target_usage_pct": 70.0,
                "soft_throttle_active": False,
                "hard_stop_active": False,
                "call_allowance_state": "optimizer_error",
                "error": f"fmp_optimizer_unavailable: {exc}",
            }

    def _quota_state(self) -> dict[str, Any]:
        fmp = self._fmp_status()
        usage = _to_float(fmp.get("current_usage_pct_estimated"), 0.0)
        hard_stop = bool(fmp.get("hard_stop_active")) or bool(fmp.get("emergency_cutoff_active")) or usage >= 80.0
        soft = bool(fmp.get("soft_throttle_active")) or usage >= 70.0
        allowed = not hard_stop and not soft and str(fmp.get("call_allowance_state") or "").lower() not in {"hard_stop", "optimizer_denied"}
        blocked_reason = ""
        if hard_stop:
            blocked_reason = "fmp_optimizer_hard_stop_or_denial"
        elif soft:
            blocked_reason = "fmp_optimizer_soft_throttle_active"
        return {
            "authority": "FmpUtilizationOptimizer",
            "fmp": fmp,
            "optimizer_allows_new_calls": bool(allowed),
            "blocked_reason": blocked_reason,
            "target_utilization_pct": 70.0,
            "soft_throttle_above_pct": 70.0,
            "hard_stop_above_pct": 80.0,
            "minimum_reserve_pct": 20.0,
        }

    def _warehouse_rows(self) -> list[dict[str, Any]]:
        manifest = self._read_json(self.paths["warehouse_manifest"])
        symbols = manifest.get("symbols")
        if isinstance(symbols, dict):
            return [r for r in symbols.values() if isinstance(r, dict)]
        if isinstance(symbols, list):
            return [r for r in symbols if isinstance(r, dict)]
        cache = self._read_json(self.paths["fmp_enrichment_cache"])
        rows: list[dict[str, Any]] = []
        for symbol, entry in cache.items() if isinstance(cache, dict) else []:
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "asset_type": "stock",
                    "latest_history_date": entry.get("latest_history_date") or entry.get("history_latest_date"),
                    "data_types_available": [
                        name
                        for name, present in (
                            ("historical_ohlcv", bool(entry.get("history") or entry.get("ohlcv") or entry.get("latest_history_date"))),
                            ("fundamentals", bool(entry.get("fundamentals"))),
                            ("ratios", bool(entry.get("ratios"))),
                            ("earnings", bool(entry.get("earnings"))),
                            ("company_profile", bool(entry.get("profile"))),
                        )
                        if present
                    ],
                }
            )
        return rows

    def _universe_rows(self) -> list[dict[str, Any]]:
        universe = self._read_json(self.paths["universe_cache"])
        raw = universe.get("symbols") or universe.get("stocks") or universe.get("universe") or []
        if isinstance(raw, dict):
            raw = list(raw.values())
        rows: list[dict[str, Any]] = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, str):
                rows.append({"symbol": item.strip().upper(), "asset_type": "stock"})
            elif isinstance(item, dict):
                symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
                if symbol:
                    rows.append(dict(item, symbol=symbol, asset_type=str(item.get("asset_type") or item.get("type") or "stock").lower()))
        return rows

    def _runtime_symbols(self) -> set[str]:
        snapshot = self._read_json(self.paths["runtime_snapshot"])
        symbols: set[str] = set()
        def add_rows(rows: Any) -> None:
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        sym = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
                        if sym:
                            symbols.add(sym)
        if isinstance(snapshot.get("stocks"), dict):
            add_rows(snapshot.get("stocks", {}).get("final"))
        add_rows(snapshot.get("final"))
        add_rows(snapshot.get("rankings"))
        return symbols

    def _symbol_pool(self) -> list[dict[str, Any]]:
        by_symbol: dict[str, dict[str, Any]] = {}
        for row in self._universe_rows() + self._warehouse_rows():
            symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
            if not symbol:
                continue
            merged = by_symbol.setdefault(symbol, {"symbol": symbol})
            merged.update({k: v for k, v in row.items() if v not in (None, "", [])})
        for symbol in self._runtime_symbols():
            row = by_symbol.setdefault(symbol, {"symbol": symbol})
            row["prior_astra_interest"] = True
        return list(by_symbol.values())

    def _request_key(self, provider: str, symbol: str, data_type: str, start_date: str, end_date: str, interval: str) -> str:
        raw = "|".join([provider.lower(), symbol.upper(), data_type.lower(), start_date, end_date, interval.lower()])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _delta_refresh_plan(self) -> list[dict[str, Any]]:
        rows = self._symbol_pool()
        today = date.today()
        planned: list[dict[str, Any]] = []
        for row in rows[:SMALL_BATCH_LIMIT]:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            asset_type = str(row.get("asset_type") or "stock").lower()
            available = row.get("data_types_available") or row.get("data_types") or []
            if isinstance(available, str):
                available = [available]
            available_text = " ".join(str(v).lower() for v in available)
            latest_history = _parse_date(row.get("latest_history_date") or row.get("history_latest_date"))
            if "histor" not in available_text and "ohlcv" not in available_text:
                start = (today - timedelta(days=365 * 5)).isoformat()
                reason = "missing_history"
            elif latest_history and latest_history < today - timedelta(days=1):
                start = (latest_history + timedelta(days=1)).isoformat()
                reason = "history_delta_gap"
            else:
                start = ""
                reason = "history_fresh_or_unknown_no_refresh_needed"
            if start:
                planned.append(
                    {
                        "symbol": symbol,
                        "asset_type": "stock" if asset_type == "equity" else asset_type,
                        "data_type": "historical_ohlcv",
                        "provider": "financial_modeling_prep",
                        "start_date": start,
                        "end_date": _today(),
                        "interval": "1d",
                        "reason": reason,
                        "delta_only": True,
                    }
                )
            missing_enrichment = [name for name in ("fundamentals", "ratios", "earnings", "company_profile", "sector_industry") if name not in available_text]
            for data_type in missing_enrichment[:2]:
                planned.append(
                    {
                        "symbol": symbol,
                        "asset_type": "stock" if asset_type == "equity" else asset_type,
                        "data_type": data_type,
                        "provider": "financial_modeling_prep",
                        "start_date": "",
                        "end_date": _today(),
                        "interval": "snapshot",
                        "reason": "missing_enrichment_field",
                        "delta_only": True,
                    }
                )
        return planned[:SMALL_BATCH_LIMIT]

    def _batch_plan(self, delta_tasks: list[dict[str, Any]]) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for task in delta_tasks:
            key = f"{task.get('provider')}::{task.get('data_type')}::{task.get('interval')}"
            groups.setdefault(key, []).append(task)
        batchable = []
        non_batchable = []
        for key, tasks in groups.items():
            symbols = [str(t.get("symbol")) for t in tasks if t.get("symbol")]
            row = {
                "group_key": key,
                "provider": tasks[0].get("provider") if tasks else "unknown",
                "data_type": tasks[0].get("data_type") if tasks else "unknown",
                "symbols": symbols,
                "symbol_count": len(symbols),
                "estimated_calls_without_batch": len(symbols),
                "estimated_calls_with_batch": 1 if len(symbols) > 1 else len(symbols),
                "batch_preferred": len(symbols) > 1,
            }
            if len(symbols) > 1:
                batchable.append(row)
            else:
                non_batchable.append(row)
        calls_without = sum(_to_int(r.get("estimated_calls_without_batch"), 0) for r in batchable + non_batchable)
        calls_with = sum(_to_int(r.get("estimated_calls_with_batch"), 0) for r in batchable + non_batchable)
        return {
            "batchable_tasks": batchable,
            "non_batchable_tasks": non_batchable,
            "estimated_calls_without_batching": int(calls_without),
            "estimated_calls_with_batching": int(calls_with),
            "estimated_calls_saved_by_batching": max(0, int(calls_without - calls_with)),
        }

    def _deduplication(self, delta_tasks: list[dict[str, Any]]) -> dict[str, Any]:
        keys = []
        sample = []
        for task in delta_tasks:
            key = self._request_key(
                str(task.get("provider") or ""),
                str(task.get("symbol") or ""),
                str(task.get("data_type") or ""),
                str(task.get("start_date") or ""),
                str(task.get("end_date") or ""),
                str(task.get("interval") or ""),
            )
            keys.append(key)
            if len(sample) < 10:
                sample.append({"request_key": key, **task})
        counts = Counter(keys)
        duplicate_requests = sum(max(0, n - 1) for n in counts.values())
        warehouse_rows = self._warehouse_rows()
        row_ids = [str(r.get("symbol") or "").upper() + "::" + str(r.get("latest_history_date") or "") for r in warehouse_rows]
        storage_counts = Counter(row_ids)
        duplicate_storage_rows = sum(max(0, n - 1) for n in storage_counts.values() if n > 1)
        return {
            "duplicate_requests_blocked": int(duplicate_requests),
            "duplicate_storage_rows_avoided": int(duplicate_storage_rows),
            "deterministic_key_fields": ["provider", "symbol", "data_type", "start_date", "end_date", "interval"],
            "unique_request_key_count": len(counts),
            "sample_request_keys": sample,
        }

    def _symbol_priority(self) -> dict[str, Any]:
        rows = self._symbol_pool()
        runtime_symbols = self._runtime_symbols()
        ranked = []
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            volume = _to_float(row.get("volume"), _to_float(row.get("avg_volume"), 0.0))
            liquidity = min(100.0, max(_to_float(row.get("liquidity_score"), 0.0), volume / 1_000_000.0))
            data_types = row.get("data_types_available") or row.get("data_types") or []
            if isinstance(data_types, str):
                data_types = [data_types]
            completeness = min(100.0, len(set(str(v).lower() for v in data_types)) * 16.0)
            feature_gap = max(0.0, 100.0 - completeness)
            prior_interest = 100.0 if symbol in runtime_symbols or row.get("prior_astra_interest") else 0.0
            catalyst = 65.0 if any("earning" in str(v).lower() for v in data_types) else 35.0
            sector = 60.0 if row.get("sector") or row.get("industry") else 35.0
            score = (
                liquidity * 0.20
                + min(100.0, volume / 2_000_000.0) * 0.10
                + 50.0 * 0.10
                + sector * 0.10
                + catalyst * 0.10
                + prior_interest * 0.15
                + feature_gap * 0.15
                + (100.0 - completeness) * 0.05
                + 85.0 * 0.05
            )
            ranked.append(
                {
                    "symbol": symbol,
                    "asset_type": str(row.get("asset_type") or "stock").lower(),
                    "priority_score": round(score, 3),
                    "priority_reasons": [
                        reason
                        for reason, active in (
                            ("liquidity", liquidity > 0),
                            ("volume", volume > 0),
                            ("sector_leadership", bool(row.get("sector") or row.get("industry"))),
                            ("earnings_catalyst_relevance", catalyst >= 60.0),
                            ("proximity_to_active_200_funnel", prior_interest > 0),
                            ("feature_gaps", feature_gap > 0),
                            ("data_completeness_gaps", completeness < 100.0),
                            ("provider_reliability", True),
                        )
                        if active
                    ],
                    "feature_gap_score": round(feature_gap, 3),
                    "data_completeness_pct": round(completeness, 3),
                }
            )
        ranked.sort(key=lambda r: _to_float(r.get("priority_score"), 0.0), reverse=True)
        return {
            "symbol_priority_status_v1": True,
            "priority_dimensions": [
                "liquidity",
                "volume",
                "momentum",
                "sector_leadership",
                "earnings_catalyst_relevance",
                "proximity_to_active_200_funnel",
                "prior_astra_interest",
                "feature_gaps",
                "data_completeness_gaps",
                "provider_reliability",
            ],
            "candidate_count": len(ranked),
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
            "top_priority_symbols": ranked[:25],
        }

    def _synthetic_replay(self) -> dict[str, Any]:
        lifecycle = self._count_jsonl(self.paths["trade_lifecycle"])
        outcomes = self._count_jsonl(self.paths["outcome_labels"])
        candidates = self._count_jsonl(self.paths["candidate_ledger"])
        replay = self._read_json(self.paths["replay_results"])
        replay_rows = max(
            _to_int(replay.get("source_row_count"), 0),
            _to_int(replay.get("rows_evaluated"), 0),
            _to_int(replay.get("sample_count"), 0),
        )
        base_examples = min(10000, lifecycle + outcomes + candidates + replay_rows)
        planned = base_examples * len(self.scenarios)
        learning_value = "high" if planned >= 1000 else "moderate" if planned >= 100 else "needs_more_real_outcomes"
        return {
            "synthetic_replay_expansion_status_v1": True,
            "source_data_policy": "existing_stored_data_only",
            "provider_calls_required": False,
            "api_calls_used": 0,
            "base_examples_available": int(base_examples),
            "synthetic_examples_planned": int(planned),
            "scenario_templates": list(self.scenarios),
            "learning_value_estimate": learning_value,
            "source_counts": {
                "trade_lifecycle_rows": int(lifecycle),
                "outcome_label_rows": int(outcomes),
                "candidate_ledger_rows": int(candidates),
                "replay_rows_available": int(replay_rows),
            },
            "changes_live_rankings": False,
            "changes_live_top_buys": False,
            "changes_live_trading": False,
        }

    def _estimates(self, delta_tasks: list[dict[str, Any]], batch_plan: dict[str, Any]) -> dict[str, Any]:
        full_refresh_calls = BROAD_UNIVERSE_TARGET_COUNT * 3
        delta_calls = len(delta_tasks)
        batch_calls = _to_int(batch_plan.get("estimated_calls_with_batching"), delta_calls)
        calls_saved = max(0, full_refresh_calls - batch_calls)
        bandwidth_full_kb = full_refresh_calls * 180
        bandwidth_delta_kb = max(1, batch_calls) * 180
        bandwidth_saved = max(0, bandwidth_full_kb - bandwidth_delta_kb)
        return {
            "estimated_calls_saved": int(calls_saved),
            "estimated_bandwidth_saved": round(float(bandwidth_saved), 3),
            "estimated_full_refresh_calls_avoided": int(full_refresh_calls),
            "estimated_delta_or_batch_calls_planned": int(batch_calls),
        }

    def _base_payload(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "version": VERSION,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "generated_at": _now_iso(),
            "fmp_optimizer_authoritative": True,
            "fmp_alpaca_overlap_prevention_active": True,
            "fmp_duplicate_live_quote_blocked": True,
            "alpaca_iex_live_quote_ownership": True,
            "uncontrolled_collection_enabled": False,
            "changes_live_rankings": False,
            "changes_live_top_buys": False,
            "changes_live_trading": False,
            "quota_state": self._quota_state(),
        }

    def _build(self) -> dict[str, Any]:
        delta_tasks = self._delta_refresh_plan()
        batch_plan = self._batch_plan(delta_tasks)
        dedup = self._deduplication(delta_tasks)
        estimates = self._estimates(delta_tasks, batch_plan)
        synthetic = self._synthetic_replay()
        priority = self._symbol_priority()
        stale_ranges = [t for t in delta_tasks if t.get("reason") in {"missing_history", "history_delta_gap"}]
        payload = {
            **self._base_payload(),
            "mode": "planning_reporting_only",
            "api_efficiency_status_v1": True,
            "collection_enabled": True,
            "planned_calls": int(estimates.get("estimated_delta_or_batch_calls_planned", 0)),
            "estimated_bandwidth": round(float(max(1, _to_int(estimates.get("estimated_delta_or_batch_calls_planned"), 0)) * 180), 3),
            "estimated_calls_saved": estimates["estimated_calls_saved"],
            "estimated_bandwidth_saved": estimates["estimated_bandwidth_saved"],
            "duplicate_requests_blocked": dedup["duplicate_requests_blocked"],
            "duplicate_storage_rows_avoided": dedup["duplicate_storage_rows_avoided"],
            "synthetic_examples_planned": synthetic["synthetic_examples_planned"],
            "next_recommended_action": "execute_only_governed_delta_batches_when_fmp_optimizer_allows",
            "delta_only_refresh_planner_v1": {
                "enabled": True,
                "missing_or_stale_ranges": stale_ranges[:25],
                "planned_delta_tasks": delta_tasks[:25],
                "avoids_full_history_redownloads": True,
            },
            "batch_endpoint_optimizer_v1": batch_plan,
            "smart_ttl_policy_engine_v1": {
                "enabled": True,
                "policies": self.ttl_policy,
            },
            "synthetic_replay_expansion_v1": synthetic,
            "symbol_priority_scoring_v1": priority,
            "data_deduplication_hashing_v1": dedup,
            **estimates,
        }
        return payload

    def status(self) -> dict[str, Any]:
        return self._build()

    def plan(self) -> dict[str, Any]:
        payload = self._build()
        payload["api_efficiency_plan_v1"] = True
        payload["mode"] = "planning_reporting_only"
        return payload

    def synthetic_replay_status(self) -> dict[str, Any]:
        payload = {**self._base_payload(), **self._synthetic_replay()}
        payload.update(self._estimates(self._delta_refresh_plan(), self._batch_plan(self._delta_refresh_plan())))
        payload["mode"] = "local_synthetic_replay_planning_only"
        payload["writes_files"] = False
        payload["duplicate_requests_blocked"] = 0
        payload["next_recommended_action"] = "use_synthetic_examples_as_shadow_learning_labels_only"
        return payload

    def symbol_priority_status(self) -> dict[str, Any]:
        delta_tasks = self._delta_refresh_plan()
        batch = self._batch_plan(delta_tasks)
        payload = {**self._base_payload(), **self._symbol_priority(), **self._estimates(delta_tasks, batch)}
        payload["mode"] = "priority_scoring_planning_only"
        payload["writes_files"] = False
        payload["duplicate_requests_blocked"] = self._deduplication(delta_tasks)["duplicate_requests_blocked"]
        payload["synthetic_examples_planned"] = self._synthetic_replay()["synthetic_examples_planned"]
        payload["next_recommended_action"] = "spend_future_governed_calls_on_highest_priority_feature_gaps_first"
        return payload

    def data_deduplication_status(self) -> dict[str, Any]:
        delta_tasks = self._delta_refresh_plan()
        batch = self._batch_plan(delta_tasks)
        dedup = self._deduplication(delta_tasks)
        payload = {**self._base_payload(), **dedup, **self._estimates(delta_tasks, batch)}
        payload["data_deduplication_status_v1"] = True
        payload["mode"] = "deterministic_request_key_planning_only"
        payload["writes_files"] = False
        payload["synthetic_examples_planned"] = self._synthetic_replay()["synthetic_examples_planned"]
        payload["next_recommended_action"] = "check_request_key_before_any_future_provider_call_or_storage_write"
        return payload
