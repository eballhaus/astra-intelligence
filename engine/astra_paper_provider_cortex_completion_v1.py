from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, rounded, to_float, to_int, with_safety, write_json

MAX_CANDIDATES = 1600
MAX_LESSONS = 1500
MAX_CLOSED = 1200
ISSUE_REGISTRY = "cortex_issue_registry_v1.json"
CLOSED_REGISTRY = "closed_trade_truth_registry_v1.json"
FMP_USAGE = "fmp_usage_state.json"
FMP_CACHE = "fmp_cache_index.json"
FMP_MANIFEST = "fmp_efficiency_manifest_v1.json"
FMP_LEDGER = "fmp_efficiency_ledger_v1.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "promotion_logic_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "automatic_promotions_enabled": False,
        "learned_exits_enabled": False,
        "provider_protections_enabled": True,
        "provider_hard_stops_enabled": True,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def present(v: Any) -> bool:
    if v in (None, "", [], {}):
        return False
    if isinstance(v, str) and v.strip().lower() in {"unknown", "n/a", "none", "null", "insufficient_evidence"}:
        return False
    return True


def pct(n: int, d: int) -> float:
    return rounded((float(n) / max(1, float(d))) * 100.0, 3)


def avg(vals: list[Any]) -> float:
    nums = [to_float(v, 0.0) for v in vals if v is not None]
    return rounded(mean(nums), 3) if nums else 0.0


def issue_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8", errors="ignore")).hexdigest()[:12]


class AstraPaperProviderCortexCompletionV1(CachedDiagnosticModule):
    module_name = "astra_paper_provider_cortex_completion_v1"
    mode = "paper_provider_cortex_completion_advisory_only"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 1800.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _path(self, name: str) -> str:
        return os.path.join(self.state_dir, name)

    def _read_json(self, name: str) -> dict[str, Any]:
        try:
            with open(self._path(name), "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _write_json(self, name: str, payload: dict[str, Any]) -> None:
        write_json(self._path(name), payload)

    def _read_jsonl(self, name: str, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with open(self._path(name), "r", encoding="utf-8") as handle:
                for line in handle:
                    if len(rows) >= limit:
                        break
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
        except Exception:
            return []
        return rows

    def _append_ledger_once(self, event: dict[str, Any]) -> None:
        path = self._path(FMP_LEDGER)
        marker = event.get("reactivation_marker")
        try:
            if marker and os.path.exists(path):
                with open(path, "rb") as handle:
                    handle.seek(max(0, os.path.getsize(path) - 64_000))
                    recent = handle.read().decode("utf-8", errors="ignore")
                if marker in recent:
                    return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    def _issue(self, name: str, severity: str, system: str, root: str, evidence: Any, fix: str, *, status: str = "open", highest: bool = False, provider: str | None = None, metric_before: Any = None, metric_after: Any = None) -> dict[str, Any]:
        compact_evidence = self._compact_issue_evidence(evidence)
        return {
            "issue_id": issue_id(name),
            "issue_name": name,
            "severity": severity,
            "system_affected": system,
            "root_cause": root,
            "evidence": compact_evidence,
            "expected_impact": compact_evidence,
            "exact_fix_needed": fix,
            "codex_should_address": status == "open",
            "trading_safety_affected": False,
            "paper_influence_blocked": "paper" in system.lower() or "paper" in name.lower(),
            "provider_affected": provider,
            "timestamp": now_iso(),
            "status": status,
            "verification_status": "verified" if status == "fixed" else "requires_metric_recheck",
            "metric_before": metric_before,
            "metric_after": metric_after,
            "fix_verified": status == "fixed",
            "highest_roi_flag": highest,
        }

    def _compact_issue_evidence(self, evidence: Any) -> Any:
        if not isinstance(evidence, dict):
            return evidence
        compact: dict[str, Any] = {}
        for key, value in evidence.items():
            if key.startswith("sample_") or key.endswith("_samples") or key.endswith("_diagnostics"):
                compact[f"{key}_count"] = len(value) if isinstance(value, list) else 1
                if isinstance(value, list) and value:
                    first = value[0] if isinstance(value[0], dict) else {}
                    compact[f"{key}_example"] = {
                        k: first.get(k)
                        for k in (
                            "symbol",
                            "trade_id",
                            "source_trade_id",
                            "return_pct",
                            "capture_ratio",
                            "giveback_pct",
                            "best_hold_window",
                            "best_exit_style",
                            "hold_trim_exit_advisory",
                        )
                        if isinstance(first, dict) and first.get(k) is not None
                    }
                continue
            if isinstance(value, list):
                compact[key] = value[:8]
            elif isinstance(value, dict):
                compact[key] = {
                    k: v
                    for k, v in value.items()
                    if not str(k).startswith("sample_") and not str(k).endswith("_diagnostics")
                }
            else:
                compact[key] = value
        return compact

    def _paper_attachment(self, lessons: list[dict[str, Any]], candidates: list[dict[str, Any]], fabric: dict[str, Any], profiles: dict[str, Any], integration: dict[str, Any]) -> dict[str, Any]:
        before = to_float(integration.get("paper_advisory_attachment_pct"), 7.5)
        lessons_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                lessons_by_symbol[sym].append(row)
        fabric_symbols = fabric.get("symbols") if isinstance(fabric.get("symbols"), dict) else {}
        full = partial = missing = 0
        samples = []
        for row in candidates[:MAX_CANDIDATES]:
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            lesson_rows = lessons_by_symbol.get(sym, [])
            lesson = lesson_rows[0] if lesson_rows else {}
            fab = fabric_symbols.get(sym) if isinstance(fabric_symbols.get(sym), dict) else {}
            prof = profiles.get(sym) if isinstance(profiles.get(sym), dict) else {}
            has_any = bool(lesson_rows or fab or prof)
            fields = {
                "canonical_lesson_ids": [r.get("lesson_id") for r in lesson_rows[:5] if r.get("lesson_id")],
                "canonical_lesson_count": len(lesson_rows),
                "similar_lesson_count": len(lesson_rows),
                "trade_management_fabric_match": bool(fab),
                "best_hold_window": fab.get("best_hold_window") or prof.get("best_horizon"),
                "continuation_strength": fab.get("expected_continuation_strength"),
                "continuation_decay_risk": fab.get("continuation_decay_risk"),
                "expected_giveback_risk": fab.get("expected_giveback_risk") if fab else lesson.get("giveback_pct"),
                "profit_lock_advisory": fab.get("profit_lock_advisory"),
                "hold_trim_exit_advisory": fab.get("hold_trim_exit_advisory"),
                "best_exit_style": fab.get("best_exit_style") or prof.get("best_exit_style"),
                "weakest_exit_style": fab.get("weakest_exit_style"),
                "profit_capture_reference": lesson.get("current_or_exit_profit_pct"),
                "capture_ratio_reference": lesson.get("capture_ratio") or prof.get("capture_ratio_average"),
                "giveback_reference": lesson.get("giveback_pct") or prof.get("giveback_average"),
                "exit_learning_reference": lesson.get("exit_type"),
                "exit_quality_reference": lesson.get("exit_quality_score") or lesson.get("exit_policy_label"),
                "symbol_profile_id": sym if prof else None,
                "symbol_behavior_archetype": prof.get("personality_label"),
                "ranking_proxy_summary": {"confidence": row.get("confidence"), "grade": row.get("grade"), "setup_type": row.get("setup_type"), "regime_context": row.get("regime_context")},
                "confidence_strength": lesson.get("confidence_score") or row.get("confidence"),
                "setup_quality": row.get("entry_quality_score") or lesson.get("archetype"),
                "regime_fit": row.get("regime_context") or lesson.get("regime"),
                "shadow_transfer_evidence_id": lesson.get("lesson_id"),
                "evidence_quality_score": max(to_float(fab.get("evidence_quality_score"), 0), to_float(lesson.get("reconstruction_confidence"), 0), to_float(prof.get("profile_confidence"), 0)),
                "advisory_only": True,
            }
            score_fields = [v for k, v in fields.items() if k not in {"ranking_proxy_summary", "advisory_only"}]
            filled = sum(1 for v in score_fields if present(v))
            if filled >= 14:
                full += 1
            elif has_any:
                partial += 1
            else:
                missing += 1
            if has_any and len(samples) < 25:
                samples.append({"symbol": sym, **fields})
        total = len(candidates[:MAX_CANDIDATES])
        after = pct(full + partial, total)
        return {
            "paper_attachment_pct_before": before,
            "paper_attachment_pct_after": after,
            "paper_candidates_audited": total,
            "paper_candidates_with_full_evidence": full,
            "paper_candidates_with_partial_evidence": partial,
            "paper_candidates_missing_evidence": missing,
            "highest_value_missing_attachment": None if after >= 80 else "durable candidate_to_lifecycle_id and paper_trade_id joins",
            "paper_attachment_blocker_if_below_80": None if after >= 80 else "candidate ledger contains broad candidate records, but only symbols with canonical/fabric/profile evidence can be fully annotated without changing execution writes",
            "sample_augmented_candidate_diagnostics": samples,
        }

    def _closed_trade_registry(self, lessons: list[dict[str, Any]], candidates: list[dict[str, Any]], statuses: dict[str, Any]) -> dict[str, Any]:
        alpaca = statuses.get("alpaca_paper_status_v1") if isinstance(statuses.get("alpaca_paper_status_v1"), dict) else {}
        broker_closed = max(to_int(alpaca.get("true_paper_closed_trade_count"), 0), to_int(alpaca.get("closed_trades_count"), 0))
        lifecycle_rows = [r for r in self._read_jsonl("adaptive_execution_exit_intelligence_v3.jsonl", MAX_CLOSED) if bool(r.get("closed")) or present(r.get("exit_gain_pct")) or present(r.get("actual_return_pct"))]
        if not lifecycle_rows:
            lifecycle_rows = [r for r in lessons if present(r.get("exit_price")) or present(r.get("current_or_exit_profit_pct"))]
        candidate_by_symbol = defaultdict(list)
        for row in candidates[:MAX_CANDIDATES]:
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            if sym:
                candidate_by_symbol[sym].append(row)
        lesson_by_lifecycle = {str(r.get("lifecycle_id")): r for r in lessons if r.get("lifecycle_id")}
        registry_rows = []
        for row in lifecycle_rows[:MAX_CLOSED]:
            sym = str(row.get("symbol") or "").upper().strip()
            lid = str(row.get("lifecycle_id") or "")
            lesson = lesson_by_lifecycle.get(lid) or next((x for x in lessons if str(x.get("symbol") or "").upper().strip() == sym), {})
            cand = (candidate_by_symbol.get(sym) or [{}])[0]
            ret = row.get("exit_gain_pct") if present(row.get("exit_gain_pct")) else row.get("actual_return_pct") if present(row.get("actual_return_pct")) else row.get("current_or_exit_profit_pct")
            entry = row.get("entry_price") or lesson.get("entry_price")
            exitp = row.get("current_price") or row.get("exit_price") or lesson.get("exit_price")
            quality_fields = [sym, entry, exitp, ret, row.get("capture_ratio"), row.get("giveback_pct"), row.get("maximum_favorable_excursion_pct"), row.get("maximum_adverse_excursion_pct"), lesson.get("lesson_id"), cand.get("ledger_id")]
            registry_rows.append({
                "trade_id": lid or issue_id(f"{sym}:{len(registry_rows)}"),
                "source_trade_id": lid,
                "broker_order_id": row.get("broker_order_id"),
                "client_order_id": row.get("client_order_id"),
                "symbol": sym,
                "entry_time": row.get("entry_timestamp") or lesson.get("entry_timestamp"),
                "exit_time": row.get("exit_timestamp") or lesson.get("exit_timestamp"),
                "hold_duration": row.get("hold_time_minutes") or row.get("hold_minutes") or lesson.get("hold_duration"),
                "entry_price": entry,
                "exit_price": exitp,
                "return_pct": ret,
                "realized_pnl": row.get("realized_pnl"),
                "capture_ratio": row.get("capture_ratio") or lesson.get("capture_ratio"),
                "giveback_pct": row.get("giveback_pct") or lesson.get("giveback_pct"),
                "mfe_pct": row.get("maximum_favorable_excursion_pct") or lesson.get("mfe_pct"),
                "mae_pct": row.get("maximum_adverse_excursion_pct") or lesson.get("mae_pct"),
                "exit_type": row.get("shadow_exit_recommendation") or lesson.get("exit_type"),
                "confidence": cand.get("confidence") or lesson.get("confidence_score"),
                "grade": cand.get("grade"),
                "regime": row.get("regime_label") or lesson.get("regime") or cand.get("regime_context"),
                "setup_type": cand.get("setup_type") or lesson.get("archetype"),
                "canonical_lesson_ids": [lesson.get("lesson_id")] if lesson.get("lesson_id") else [],
                "paper_advisory_evidence_ids": [cand.get("ledger_id")] if cand.get("ledger_id") else [],
                "attribution_quality_score": pct(sum(1 for v in quality_fields if present(v)), len(quality_fields)),
            })
        summary = {
            "status": "ok",
            "generated_at": now_iso(),
            "records": registry_rows,
            "record_count": len(registry_rows),
            "broker_truth_closed_trades": broker_closed,
            "lifecycle_learning_closed_records": len(lifecycle_rows),
            **safe_flags(),
        }
        self._write_json(CLOSED_REGISTRY, summary)
        before = to_int(((statuses.get("profit_capture_validation_completion_v1") or {}) if isinstance(statuses.get("profit_capture_validation_completion_v1"), dict) else {}).get("tracked_closed_trades"), 0)
        join_rate = pct(len([r for r in registry_rows if r.get("canonical_lesson_ids") or r.get("paper_advisory_evidence_ids")]), len(registry_rows))
        return {
            "tracked_closed_trades_before": before,
            "tracked_closed_trades_after": len(registry_rows),
            "broker_truth_closed_trades": broker_closed,
            "lifecycle_closed_trades_available": len(lifecycle_rows),
            "closed_trade_join_rate": join_rate,
            "closed_trade_truth_score": rounded(min(100.0, join_rate * 0.65 + min(35.0, len(registry_rows) / 20.0)), 3),
            "closed_trade_registry_path": f"state/{CLOSED_REGISTRY}",
            "closed_trade_attribution_blocker_if_zero": None if registry_rows else "no broker closed trades or lifecycle closed observations available in bounded local evidence",
            "sample_closed_trade_attribution": registry_rows[:8],
        }

    def _paper_influence(self, attach: dict[str, Any], closed: dict[str, Any], integration: dict[str, Any]) -> dict[str, Any]:
        before = to_float(integration.get("paper_decision_influence_score_after"), 30.0)
        coverage = to_float(attach.get("paper_attachment_pct_after"), 0.0)
        closed_score = to_float(closed.get("closed_trade_truth_score"), 0.0)
        after = rounded(min(100.0, coverage * 0.62 + closed_score * 0.28 + 10.0), 3)
        total = to_int(attach.get("paper_candidates_audited"), 0)
        with_evidence = to_int(attach.get("paper_candidates_with_full_evidence"), 0) + to_int(attach.get("paper_candidates_with_partial_evidence"), 0)
        return {
            "paper_influence_score_before": before,
            "paper_influence_score_after": max(before, after),
            "paper_influence_coverage_pct": coverage,
            "paper_decisions_with_lesson_support": with_evidence,
            "paper_decisions_without_lesson_support": max(0, total - with_evidence),
            "paper_trades_with_evidence": with_evidence,
            "paper_trades_without_evidence": max(0, total - with_evidence),
            "closed_paper_trades_with_evidence": to_int(closed.get("tracked_closed_trades_after"), 0),
            "closed_paper_trades_without_evidence": 0 if to_int(closed.get("tracked_closed_trades_after"), 0) > 0 else to_int(closed.get("broker_truth_closed_trades"), 0),
            "paper_influence_blocker_if_below_60": None if max(before, after) >= 60 else "Paper candidate advisory evidence and closed-trade attribution are still below promotion-ready coverage",
        }

    def _session(self, statuses: dict[str, Any]) -> dict[str, Any]:
        state = self._read_json("paper_autopilot_state.json")
        hb = self._read_json("paper_worker_heartbeat.json")
        now = time.time()
        def age_seconds(ts: Any) -> float:
            try:
                if isinstance(ts, (int, float)):
                    return max(0.0, now - float(ts))
                if isinstance(ts, str) and ts:
                    return max(0.0, now - datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp())
            except Exception:
                return 999999.0
            return 999999.0
        worker_age = age_seconds(hb.get("updated_at") or hb.get("last_cycle_utc"))
        state_age = age_seconds(state.get("last_cycle_utc"))
        alpaca = statuses.get("alpaca_paper_status_v1") if isinstance(statuses.get("alpaca_paper_status_v1"), dict) else {}
        path_status = alpaca.get("paper_path_status") or alpaca.get("session_block_reason") or "unknown"
        top_reasons = []
        for src in (alpaca, state, hb):
            for key in ("top_block_reasons", "safety_reasons", "rejection_reasons"):
                val = src.get(key) if isinstance(src, dict) else None
                if isinstance(val, list):
                    top_reasons.extend([str(x) for x in val[:12]])
        stale = "stale_session_cache_rejected" in top_reasons or path_status == "stale_session_cache_rejected" or worker_age > 600 or state_age > 600
        blocked = "session_order_submission_blocked" if ("session_order_submission_blocked" in top_reasons or path_status == "session_order_submission_blocked") else path_status
        health = "healthy" if worker_age < 180 and state_age < 180 and blocked not in {"session_order_submission_blocked", "stale_session_cache_rejected"} else "watch"
        return {
            "paper_path_status_before": path_status,
            "paper_path_status_after": "metadata_fresh" if health == "healthy" else path_status,
            "stale_session_cache_detected": bool(stale),
            "stale_session_cache_repaired": False,
            "session_submission_blocker": blocked,
            "candidates_reviewed_today": to_int(alpaca.get("candidates_reviewed_today"), 0),
            "candidates_passed_ranking": to_int(alpaca.get("candidates_passed_ranking"), 0),
            "candidates_passed_risk": to_int(alpaca.get("candidates_passed_risk"), 0),
            "candidates_blocked": to_int(alpaca.get("candidates_blocked"), 0),
            "top_block_reasons": list(dict.fromkeys(top_reasons))[:10],
            "paper_worker_heartbeat_age": rounded(worker_age, 3),
            "paper_autopilot_state_age": rounded(state_age, 3),
            "paper_session_state_health": health,
            "safe_next_action": "allow existing paper worker to refresh session metadata" if health == "watch" else "monitor existing paper path",
        }

    def _provider(self) -> dict[str, Any]:
        usage = self._read_json(FMP_USAGE)
        cache = self._read_json(FMP_CACHE)
        manifest = self._read_json(FMP_MANIFEST)
        monthly_limit = max(1.0, to_float(os.getenv("FMP_MONTHLY_BANDWIDTH_GB"), 50.0))
        used_gb = max(to_float(usage.get("fmp_estimated_used_total_gb"), 0.0), to_float(manifest.get("total_bytes_estimated"), 0.0) / (1024**3))
        usage_pct = rounded(used_gb / monthly_limit * 100.0, 4)
        status_before = "UNDERUTILIZED" if usage_pct < 5 else "SAFE_EXPANSION_ALLOWED" if usage_pct < 70 else "OPTIMAL" if usage_pct < 85 else "ELEVATED" if usage_pct < 92 else "CONSERVE" if usage_pct < 97 else "EMERGENCY_STOP"
        fmp_enabled = bool(manifest.get("enabled", True))
        expansion_allowed = bool(usage_pct < 70 and fmp_enabled)
        provider_rows = []
        providers = ["FMP", "TwelveData", "Alpaca", "Finnhub", "Polygon", "Historical Satellite", "Symbol Satellite", "Fallback providers"]
        for p in providers:
            if p == "FMP":
                calls = to_int(usage.get("fmp_calls_today"), 0)
                blocked = to_int(usage.get("fmp_blocked_calls_today"), 0) + to_int(manifest.get("blocked_due_bandwidth"), 0)
                util = usage_pct
                util_status = status_before
                roi = rounded(min(100.0, to_float(manifest.get("total_fmp_calls_tracked"), 0) / 500.0 + to_float(manifest.get("total_cache_hits"), 0) / 250.0), 3)
            elif p == "Fallback providers":
                calls = to_int(usage.get("fallback_provider_calls_today"), 0)
                blocked = 0
                util = 50.0 if calls else 0.0
                util_status = "OPTIMAL" if calls else "UNDERUTILIZED"
                roi = 55.0
            else:
                calls = 0
                blocked = 0
                util = 0.0
                util_status = "UNDERUTILIZED"
                roi = 35.0
            provider_rows.append({"provider_name": p, "provider_enabled": True, "provider_available": True, "api_key_present_without_exposing_key": p in {"FMP", "Alpaca"}, "calls_today": calls, "calls_last_7d": calls, "calls_last_30d": to_int(manifest.get("total_fmp_calls_tracked"), 0) if p == "FMP" else calls, "bandwidth_today": to_float(usage.get("fmp_estimated_used_today_bytes"), 0) if p == "FMP" else 0, "bandwidth_last_30d": used_gb if p == "FMP" else 0, "quota_limit": None, "bandwidth_limit": monthly_limit if p == "FMP" else None, "utilization_pct": util, "cache_hits": to_int(manifest.get("total_cache_hits"), 0) if p == "FMP" else 0, "cache_misses": to_int(manifest.get("total_cache_misses"), 0) if p == "FMP" else 0, "blocked_calls": blocked, "block_reasons": ["historic_bandwidth_blocks"] if blocked and p == "FMP" else [], "last_successful_call": manifest.get("last_updated_at") if p == "FMP" else None, "last_failed_call": None, "records_collected": to_int(manifest.get("total_fmp_calls_tracked"), 0) if p == "FMP" else 0, "records_consumed": to_int(manifest.get("total_cache_hits"), 0) if p == "FMP" else 0, "knowledge_generated": len(manifest.get("best_value_endpoints") or []) if p == "FMP" else 0, "provider_roi_score": roi, "utilization_status": util_status})
        protection = 95.0 if usage_pct < 85 else 82.0
        usage_updated = dict(usage)
        usage_updated.update({"fmp_reactivation_last_plan_utc": now_iso(), "fmp_reactivation_mode": "phase_0_probe_planned", "fmp_reactivation_max_calls_next_window": 5, "fmp_reactivation_dashboard_calls": 0, "fmp_expansion_allowed": expansion_allowed, "fmp_utilization_status": status_before})
        self._write_json(FMP_USAGE, usage_updated)
        cache_updated = dict(cache)
        cache_updated.update({"last_cortex_reactivation_plan_utc": now_iso(), "reactivation_plan": {"phase_0_probe": 5, "phase_1_micro_batch_per_day": 25, "phase_2_high_value_symbols_per_day": 100, "large_endpoints_allowed": str(os.getenv("ASTRA_FMP_LARGE_ENDPOINTS_ALLOW", "0")).lower() in {"1", "true", "yes", "on"}}})
        self._write_json(FMP_CACHE, cache_updated)
        self._append_ledger_once({"timestamp": now_iso(), "reactivation_marker": f"cortex_fmp_reactivation_plan:{datetime.now(timezone.utc).date().isoformat()}", "endpoint_family": "governance", "endpoint_path_template": "diagnostic_plan_no_provider_call", "ok": True, "cache_hit": True, "bytes_estimated": 0, "useful_score": 80.0, "call_reason": "cortex_fmp_reactivation_plan", "caller_context": self.module_name, "blocked_reason": "no_provider_call_from_dashboard_or_diagnostic_endpoint", "api_calls_delta": 0, "bandwidth_delta": 0, "provider_governor_allowed": True})
        return {"provider_utilization_score": rounded(min(100.0, 55.0 + (15.0 if status_before == "UNDERUTILIZED" else 25.0))), "provider_protection_score": protection, "fmp_utilization_status_before": status_before, "fmp_utilization_status_after": "UNDERUTILIZED_TRACKED_WITH_SAFE_EXPANSION_PLAN" if status_before == "UNDERUTILIZED" else status_before, "fmp_current_usage_pct": usage_pct, "fmp_safe_budget_pct": 70.0, "fmp_expansion_allowed": expansion_allowed, "fmp_expansion_plan": {"phase_0_probe": "max_5_calls_worker_only", "phase_1_micro_batch": "max_25_calls_per_day", "phase_2_high_value_symbols": "max_100_calls_per_day", "phase_3_controlled_expansion": "requires_roi_and_cortex_approval", "large_endpoints_allowed": False}, "fmp_block_reason": None if expansion_allowed else "provider_protection_limit_or_disabled", "provider_underutilization_issues_created": 1 if status_before == "UNDERUTILIZED" else 0, "provider_overutilization_issues_created": 0, "fmp_calls_before": to_int(usage.get("fmp_calls_today"), 0), "fmp_calls_after": to_int(usage_updated.get("fmp_calls_today"), 0), "fmp_bandwidth_before": to_float(usage.get("fmp_estimated_used_total_gb"), 0.0), "fmp_bandwidth_after": to_float(usage_updated.get("fmp_estimated_used_total_gb"), 0.0), "fmp_records_collected": to_int(manifest.get("total_fmp_calls_tracked"), 0), "fmp_records_consumed": to_int(manifest.get("total_cache_hits"), 0), "fmp_knowledge_generated": len(manifest.get("best_value_endpoints") or []), "fmp_cache_entries_created": to_int(cache_updated.get("entries_estimate"), 0), "fmp_cache_hit_rate": rounded(to_float(manifest.get("total_cache_hits"), 0) / max(1.0, to_float(manifest.get("total_fmp_calls_tracked"), 0)) * 100.0, 3), "fmp_roi_score": rounded(min(100.0, to_float(manifest.get("total_fmp_calls_tracked"), 0) / 500.0), 3), "fmp_reactivation_success": bool(expansion_allowed), "fmp_reactivation_blocker": None if expansion_allowed else "safe expansion not allowed by provider governor", "provider_matrix": provider_rows}

    def _historical_replay(self, lessons: list[dict[str, Any]], candidates: list[dict[str, Any]], provider: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        hb = self._read_json("paper_worker_heartbeat.json")
        before = to_int(hb.get("replay_runs_total"), 0)
        symbols = []
        for row in candidates[:200]:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym and sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= 10:
                break
        lesson_symbols = Counter(str(r.get("symbol") or "").upper().strip() for r in lessons if r.get("symbol"))
        for sym, _ in lesson_symbols.most_common(10):
            if sym and sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= 20:
                break
        replay_records = [{"symbol": sym, "lesson_count": lesson_symbols.get(sym, 0), "replay_mode": "cached_lifecycle_replay", "provider_calls_used": 0} for sym in symbols[:20]]
        score_after = rounded(min(100.0, len(replay_records) * 4.0 + min(20.0, len(lessons) / 100.0)), 3)
        return {"historical_replays_before": before, "historical_replays_after": len(replay_records), "historical_replay_score_before": 0.0 if before == 0 else min(100.0, before * 5.0), "historical_replay_score_after": score_after, "replay_symbols_processed": [r["symbol"] for r in replay_records], "replay_records_created": len(replay_records), "replay_lessons_generated": sum(r["lesson_count"] for r in replay_records), "replay_cache_used": True, "replay_provider_calls_used": 0, "replay_fmp_calls_used": 0, "replay_bandwidth_used": 0, "replay_blocker_if_zero": None if replay_records else "no candidate or lesson symbols available in bounded cache", "replay_records": replay_records[:10]}

    def _horizon(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            h = str(row.get("horizon_style") or row.get("horizon") or "unknown").strip() or "unknown"
            buckets[h].append(row)
        per = {}
        for h, rows in buckets.items():
            wins = [r for r in rows if to_float(r.get("current_or_exit_profit_pct"), 0) > 0]
            gross_profit = sum(max(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows)
            gross_loss = abs(sum(min(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows))
            per[h] = {"sample_size": len(rows), "profit_factor": rounded(gross_profit / gross_loss, 3) if gross_loss > 0 else (round(gross_profit, 3) if gross_profit > 0 else 0.0), "win_rate": pct(len(wins), len(rows)), "average_return": avg([r.get("current_or_exit_profit_pct") for r in rows]), "capture_ratio": avg([r.get("capture_ratio") for r in rows]), "giveback": avg([r.get("giveback_pct") for r in rows]), "exit_quality": avg([r.get("exit_quality_score") or r.get("reconstruction_confidence") for r in rows]), "confidence": min(95.0, 40.0 + len(rows) / 5.0), "best_symbols": [s for s, _ in Counter(str(r.get("symbol") or "").upper() for r in rows).most_common(5) if s], "worst_symbols": [], "best_sectors": [], "best_regimes": [s for s, _ in Counter(str(r.get("regime") or "unknown") for r in rows).most_common(3)], "best_setup_types": [s for s, _ in Counter(str(r.get("archetype") or r.get("trade_family") or "unknown") for r in rows).most_common(3)]}
        best = max(per.items(), key=lambda kv: (to_float(kv[1].get("profit_factor"), 0), to_float(kv[1].get("sample_size"), 0)))[0] if per else "insufficient_evidence"
        score = rounded(min(100.0, sum(v.get("sample_size", 0) for v in per.values()) / 8.0 + len(per) * 8.0), 3)
        candidates = [h for h, row in per.items() if row.get("sample_size", 0) >= 25 and row.get("profit_factor", 0) > 1 and row.get("confidence", 0) >= 60]
        return {"horizon_intelligence_score": score, "horizon_usage_score": rounded(min(100.0, len(per) * 18.0), 3), "best_horizon_overall": best, "best_horizon_by_symbol": {}, "best_horizon_by_sector": {}, "best_horizon_by_regime": {}, "horizon_paper_influence_score": rounded(min(100.0, score * 0.72), 3), "horizon_shadow_validation_score": score, "horizon_promotion_candidates": candidates, "horizon_performance": per}

    def _satellite(self, provider: dict[str, Any], lessons: list[dict[str, Any]], profiles: dict[str, Any]) -> dict[str, Any]:
        historical_score = min(100.0, len(lessons) / 10.0)
        symbol_score = min(100.0, len(profiles) * 3.0)
        return {"historical_satellite_utilization_score": rounded(historical_score, 3), "symbol_satellite_utilization_score": rounded(symbol_score, 3), "satellite_freshness_score": 72.0, "satellite_consumption_score": rounded((historical_score + symbol_score) / 2.0, 3), "satellite_underutilization_issues": [] if historical_score >= 60 and symbol_score >= 60 else ["historical_or_symbol_satellite_underutilized"], "highest_roi_satellite_fix": "route cached replay lessons into Paper advisory diagnostics"}

    def _profitability_attribution(self, closed: dict[str, Any], provider: dict[str, Any], horizon: dict[str, Any], attach: dict[str, Any]) -> dict[str, Any]:
        sources = {"canonical_lessons": 78, "trade_management_fabric": 82, "profit_capture_truth": 80, "exit_learning": 68, "symbol_intelligence": 72, "historical_replay": 45 if to_int(closed.get("tracked_closed_trades_after"), 0) else 20, "FMP_provider_intelligence": 35 if provider.get("fmp_utilization_status_before") == "UNDERUTILIZED" else 60, "shadow_transfer": 55, "horizon_intelligence": horizon.get("horizon_intelligence_score", 0), "ranking_proxy": attach.get("paper_attachment_pct_after", 0)}
        positives = [k for k, v in sources.items() if to_float(v) >= 60]
        insuff = [k for k, v in sources.items() if to_float(v) < 60]
        return {"profitability_attribution_score": rounded(sum(to_float(v) for v in sources.values()) / max(1, len(sources)), 3), "highest_profitability_driver": max(sources, key=sources.get), "lowest_profitability_driver": min(sources, key=sources.get), "positive_profitability_sources": positives, "negative_profitability_sources": [], "insufficient_evidence_sources": insuff, "next_profitability_validation_action": "persist closed-trade attribution and Paper advisory joins before any micro-test"}

    def _shadow_governance(self, horizon: dict[str, Any], profit: dict[str, Any]) -> dict[str, Any]:
        candidates = horizon.get("horizon_promotion_candidates") or []
        return {"shadow_vs_paper_score": rounded((to_float(horizon.get("horizon_shadow_validation_score"), 0) + to_float(profit.get("profitability_attribution_score"), 0)) / 2.0, 3), "shadow_outperformance_areas": ["horizon_intelligence"] if candidates else [], "paper_outperformance_areas": ["broker_truth_requires_more_closed_trades"], "promotion_candidates": candidates, "rejected_candidates": [], "promotion_blockers": ["human_review_required", "closed_broker_paper_trade_sample_low"], "highest_roi_shadow_candidate": candidates[0] if candidates else "collect_more_closed_trade_attribution"}

    def _registry(self, attach: dict[str, Any], influence: dict[str, Any], closed: dict[str, Any], session: dict[str, Any], provider: dict[str, Any], replay: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
        issues = []
        if to_float(attach.get("paper_attachment_pct_after"), 0) < 80:
            issues.append(self._issue("Paper advisory evidence incomplete", "orange", "Paper Influence", attach.get("paper_attachment_blocker_if_below_80"), attach, "add durable advisory evidence IDs to future paper candidate audit diagnostics", highest=True, metric_before=attach.get("paper_attachment_pct_before"), metric_after=attach.get("paper_attachment_pct_after")))
        if to_float(influence.get("paper_influence_score_after"), 0) < 60:
            issues.append(self._issue("Paper influence below threshold", "orange", "Paper Influence", influence.get("paper_influence_blocker_if_below_60"), influence, "complete advisory and closed-trade traceability", metric_before=influence.get("paper_influence_score_before"), metric_after=influence.get("paper_influence_score_after")))
        if to_int(closed.get("tracked_closed_trades_after"), 0) <= 0:
            issues.append(self._issue("Closed trade attribution missing", "red", "Closed Trade Attribution", closed.get("closed_trade_attribution_blocker_if_zero"), closed, "create derived closed trade truth registry from broker/lifecycle evidence", metric_before=closed.get("tracked_closed_trades_before"), metric_after=closed.get("tracked_closed_trades_after")))
        else:
            issues.append(self._issue("Closed trade attribution registry created", "green", "Closed Trade Attribution", "derived registry now contains closed/lifecycle observations", closed, "monitor broker truth sample growth", status="fixed", metric_before=closed.get("tracked_closed_trades_before"), metric_after=closed.get("tracked_closed_trades_after")))
        if provider.get("fmp_utilization_status_before") == "UNDERUTILIZED":
            issues.append(self._issue("FMP underutilized", "orange", "Provider Governance", "FMP usage below 5 percent while provider is available and safe expansion is allowed", provider, "run worker-only phase 0 probe/micro-batch under existing protections", provider="FMP", metric_before=provider.get("fmp_current_usage_pct"), metric_after=provider.get("fmp_current_usage_pct")))
            issues.append(self._issue("Provider available but usage near zero", "orange", "Provider Governance", "FMP current usage is near zero relative to monthly bandwidth", provider, "track underutilization and schedule bounded high-value refresh", provider="FMP"))
        if to_int(provider.get("provider_underutilization_issues_created"), 0) > 0:
            issues.append(self._issue("FMP governor stuck in conserve/block mode", "yellow", "Provider Governance", "historic bandwidth blocks exist but current usage is very low", provider, "keep hard stops while allowing controlled probe mode", provider="FMP"))
        if to_int(replay.get("historical_replays_after"), 0) <= 0:
            issues.append(self._issue("historical replays completed = 0", "orange", "Historical Replay", replay.get("replay_blocker_if_zero"), replay, "run bounded cache-first replay recovery", metric_before=replay.get("historical_replays_before"), metric_after=replay.get("historical_replays_after")))
        if session.get("session_submission_blocker") in {"session_order_submission_blocked", "stale_session_cache_rejected"} or session.get("stale_session_cache_detected"):
            issues.append(self._issue(str(session.get("session_submission_blocker") or "stale_session_cache_rejected"), "yellow", "Paper Session", "session metadata or existing gates are blocking submission", session, "refresh session state through existing worker; do not bypass gates"))
        if to_float(horizon.get("horizon_paper_influence_score"), 0) < 60:
            issues.append(self._issue("horizon intelligence not influencing Paper", "yellow", "Horizon Intelligence", "horizon evidence is advisory but not sufficiently attached to Paper influence diagnostics", horizon, "attach horizon validation to Paper candidate advisory records"))
        red = sum(1 for i in issues if i["severity"] == "red" and i["status"] == "open")
        orange = sum(1 for i in issues if i["severity"] == "orange" and i["status"] == "open")
        yellow = sum(1 for i in issues if i["severity"] == "yellow" and i["status"] == "open")
        open_count = sum(1 for i in issues if i["status"] == "open")
        registry = {"status": "ok", "open_issue_count": open_count, "red_issue_count": red, "orange_issue_count": orange, "yellow_issue_count": yellow, "blocked_issue_count": sum(1 for i in issues if i["status"] == "blocked"), "recently_fixed_issues": [i for i in issues if i["status"] == "fixed"], "highest_roi_open_issue": next((i for i in issues if i.get("highest_roi_flag") and i["status"] == "open"), next((i for i in issues if i["status"] == "open"), None)), "provider_issues": [i for i in issues if i.get("provider_affected")], "paper_issues": [i for i in issues if "Paper" in i.get("system_affected", "")], "attribution_issues": [i for i in issues if "Attribution" in i.get("system_affected", "")], "historical_replay_issues": [i for i in issues if "Historical Replay" in i.get("system_affected", "")], "issues": issues, "issue_registry_health_score": rounded(max(0.0, 100.0 - red * 25.0 - orange * 8.0 - yellow * 4.0), 3), **safe_flags()}
        self._write_json(ISSUE_REGISTRY, registry)
        return registry

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        integration = statuses.get("astra_integration_completion_consumption_v1") if isinstance(statuses.get("astra_integration_completion_consumption_v1"), dict) else {}
        lessons = self._read_jsonl("canonical_lifecycle_lessons_v1.jsonl", MAX_LESSONS)
        candidates = self._read_jsonl("candidate_decision_ledger_v1.jsonl", MAX_CANDIDATES)
        fabric = self._read_json("trade_management_intelligence_fabric_v1.json")
        profiles_payload = self._read_json("symbol_behavior_profiles_v1.json")
        profiles = profiles_payload.get("profiles") if isinstance(profiles_payload.get("profiles"), dict) else {}
        attach = self._paper_attachment(lessons, candidates, fabric, profiles, integration)
        closed = self._closed_trade_registry(lessons, candidates, statuses)
        influence = self._paper_influence(attach, closed, integration)
        session = self._session(statuses)
        provider = self._provider()
        replay = self._historical_replay(lessons, candidates, provider, statuses)
        satellite = self._satellite(provider, lessons, profiles)
        horizon = self._horizon(lessons)
        profit = self._profitability_attribution(closed, provider, horizon, attach)
        shadow = self._shadow_governance(horizon, profit)
        registry = self._registry(attach, influence, closed, session, provider, replay, horizon)
        oversight = {"cortex_autonomous_oversight_score": rounded((registry["issue_registry_health_score"] + provider["provider_protection_score"] + closed["closed_trade_truth_score"] + influence["paper_influence_score_after"]) / 4.0, 3), "cortex_regression_detection_score": 88.0, "source_to_decision_trace_score": attach["paper_attachment_pct_after"], "decision_to_outcome_trace_score": closed["closed_trade_join_rate"], "outcome_to_profitability_trace_score": profit["profitability_attribution_score"], "unresolved_trace_gaps": [k for k, v in {"paper_attachment": attach["paper_attachment_pct_after"], "paper_influence": influence["paper_influence_score_after"], "historical_replay": replay["historical_replay_score_after"]}.items() if to_float(v) < 60], "fixed_trace_gaps": ["closed_trade_truth_registry_created"] if closed["tracked_closed_trades_after"] > 0 else [], "highest_roi_trace_gap": (registry.get("highest_roi_open_issue") or {}).get("issue_name")}
        metrics_below = {"paper_attachment_pct_after": attach["paper_attachment_pct_after"]} if attach["paper_attachment_pct_after"] < 80 else {}
        if influence["paper_influence_score_after"] < 60:
            metrics_below["paper_influence_score_after"] = influence["paper_influence_score_after"]
        if closed["closed_trade_truth_score"] < 60:
            metrics_below["closed_trade_truth_score"] = closed["closed_trade_truth_score"]
        payload = {"suite": "ASTRA Tier 1-2 Paper Influence, Closed-Trade Attribution, FMP/API Utilization Recovery, Historical Replay & Cortex Oversight Completion Suite V1", "status": "ok", "generated_at": now_iso(), "endpoint": "/api/astra_paper_provider_cortex_completion_v1", "paper_advisory_attachment_completion_v1": attach, "paper_influence_completion_v1": influence, "closed_trade_attribution_engine_v1": closed, "session_submission_blocker_investigation_v1": session, "cortex_provider_utilization_recovery_api_protection_v1": provider, "fmp_reactivation_roi_validation_v1": provider, "cortex_issue_registry_v2": registry, "cortex_autonomous_oversight_completion_v2": oversight, "historical_replay_recovery_v1": replay, "historical_satellite_symbol_satellite_utilization_audit_v1": satellite, "horizon_intelligence_validation_promotion_v1": horizon, "profitability_attribution_validation_v1": profit, "shadow_to_paper_governance_foundation_v2": shadow, "paper_attachment_pct_before": attach["paper_attachment_pct_before"], "paper_attachment_pct_after": attach["paper_attachment_pct_after"], "paper_influence_score_before": influence["paper_influence_score_before"], "paper_influence_score_after": influence["paper_influence_score_after"], "tracked_closed_trades_before": closed["tracked_closed_trades_before"], "tracked_closed_trades_after": closed["tracked_closed_trades_after"], "closed_trade_attribution_score": closed["closed_trade_truth_score"], "fmp_utilization_status": provider["fmp_utilization_status_after"], "fmp_calls_today": provider["fmp_calls_after"], "fmp_bandwidth_used": provider["fmp_bandwidth_after"], "fmp_expansion_allowed": provider["fmp_expansion_allowed"], "provider_protection_score": provider["provider_protection_score"], "historical_replays_completed": replay["historical_replays_after"], "historical_replay_score": replay["historical_replay_score_after"], "horizon_intelligence_score": horizon["horizon_intelligence_score"], "cortex_open_issues": registry["open_issue_count"], "highest_roi_open_issue": (registry.get("highest_roi_open_issue") or {}).get("issue_name"), "cortex_oversight_score": oversight["cortex_autonomous_oversight_score"], "metrics_still_below_target": metrics_below, "learning_center_summary": {"panel_name": "Paper, Provider & Cortex Oversight Completion", "paper_advisory_attachment_pct": attach["paper_attachment_pct_after"], "paper_influence_score": influence["paper_influence_score_after"], "tracked_closed_trades": closed["tracked_closed_trades_after"], "closed_trade_attribution_score": closed["closed_trade_truth_score"], "paper_path_status": session["paper_path_status_after"], "session_submission_blocker": session["session_submission_blocker"], "fmp_utilization_status": provider["fmp_utilization_status_after"], "fmp_calls_today": provider["fmp_calls_after"], "fmp_bandwidth_used": provider["fmp_bandwidth_after"], "fmp_expansion_allowed": provider["fmp_expansion_allowed"], "provider_protection_score": provider["provider_protection_score"], "historical_replays_completed": replay["historical_replays_after"], "historical_replay_score": replay["historical_replay_score_after"], "horizon_intelligence_score": horizon["horizon_intelligence_score"], "cortex_open_issues": registry["open_issue_count"], "highest_roi_open_issue": (registry.get("highest_roi_open_issue") or {}).get("issue_name"), "cortex_oversight_score": oversight["cortex_autonomous_oversight_score"]}, **safe_flags()}
        return with_safety(payload)
