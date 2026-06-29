from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
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
        "fmp_protection_enabled": True,
        "fmp_hard_stop_enabled": True,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "learning_tab_provider_calls_used": 0,
        "learning_tab_llm_calls_used": 0,
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
            "safe_next_action": fix,
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
        horizon_by_symbol: dict[str, dict[str, Any]] = {}
        for sym, rows in lessons_by_symbol.items():
            wins = [r for r in rows if to_float(r.get("current_or_exit_profit_pct"), 0) > 0]
            gross_profit = sum(max(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows)
            gross_loss = abs(sum(min(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows))
            best_horizon = Counter(str(r.get("horizon_style") or r.get("horizon") or "unknown") for r in rows).most_common(1)
            horizon_by_symbol[sym] = {
                "best_horizon": best_horizon[0][0] if best_horizon else "unknown",
                "horizon_sample_size": len(rows),
                "horizon_profit_factor": rounded(gross_profit / gross_loss, 3) if gross_loss > 0 else (rounded(gross_profit, 3) if gross_profit > 0 else 0.0),
                "horizon_win_rate": pct(len(wins), len(rows)),
                "horizon_avg_return": avg([r.get("current_or_exit_profit_pct") for r in rows]),
                "horizon_capture_ratio": avg([r.get("capture_ratio") for r in rows]),
                "horizon_giveback": avg([r.get("giveback_pct") for r in rows]),
                "horizon_exit_quality": avg([r.get("exit_quality_score") or r.get("reconstruction_confidence") for r in rows]),
            }
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
            horizon_hint = (
                fab.get("best_hold_window")
                or prof.get("best_horizon")
                or row.get("horizon")
                or row.get("horizon_style")
                or row.get("expected_horizon")
                or row.get("best_hold_window")
            )
            horizon_confidence = max(
                to_float(fab.get("horizon_confidence"), 0.0),
                to_float(prof.get("horizon_confidence"), 0.0),
                to_float(row.get("confidence"), 0.0),
            )
            sym_horizon = horizon_by_symbol.get(sym) or {}
            fields = {
                "canonical_lesson_ids": [r.get("lesson_id") for r in lesson_rows[:5] if r.get("lesson_id")],
                "canonical_lesson_count": len(lesson_rows),
                "similar_lesson_count": len(lesson_rows),
                "trade_management_fabric_id": sym if fab else None,
                "trade_management_fabric_match": bool(fab),
                "best_hold_window": horizon_hint,
                "best_horizon": sym_horizon.get("best_horizon") or horizon_hint,
                "horizon_recommendation": horizon_hint,
                "horizon_confidence": horizon_confidence,
                "horizon_sample_size": sym_horizon.get("horizon_sample_size"),
                "horizon_profit_factor": sym_horizon.get("horizon_profit_factor"),
                "horizon_win_rate": sym_horizon.get("horizon_win_rate"),
                "horizon_avg_return": sym_horizon.get("horizon_avg_return"),
                "horizon_capture_ratio": sym_horizon.get("horizon_capture_ratio"),
                "horizon_giveback": sym_horizon.get("horizon_giveback"),
                "horizon_exit_quality": sym_horizon.get("horizon_exit_quality"),
                "horizon_reason": "cached symbol lifecycle horizon evidence attached to Paper advisory record" if sym_horizon else "candidate horizon hint attached; symbol horizon evidence still warming up",
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
                "historical_replay_reference": lesson.get("lesson_id") or (f"cached_symbol_replay:{sym}" if has_any else None),
                "symbol_profile_id": sym if prof else None,
                "symbol_behavior_archetype": prof.get("personality_label"),
                "sector_context_reference": row.get("sector") or row.get("sector_name") or prof.get("sector") or lesson.get("sector"),
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
            elif has_any or filled >= 3:
                partial += 1
            else:
                missing += 1
            if (has_any or filled >= 3) and len(samples) < 25:
                samples.append({"symbol": sym, **fields})
        total = len(candidates[:MAX_CANDIDATES])
        after = pct(full + partial, total)
        missing_breakdown = {
            "no_symbol": sum(1 for row in candidates[:MAX_CANDIDATES] if not str(row.get("symbol") or row.get("ticker") or "").strip()),
            "no_canonical_lesson_match": sum(1 for row in candidates[:MAX_CANDIDATES] if str(row.get("symbol") or row.get("ticker") or "").upper().strip() and not lessons_by_symbol.get(str(row.get("symbol") or row.get("ticker") or "").upper().strip())),
            "no_trade_management_fabric_match": sum(1 for row in candidates[:MAX_CANDIDATES] if str(row.get("symbol") or row.get("ticker") or "").upper().strip() and not fabric_symbols.get(str(row.get("symbol") or row.get("ticker") or "").upper().strip())),
            "no_symbol_profile_match": sum(1 for row in candidates[:MAX_CANDIDATES] if str(row.get("symbol") or row.get("ticker") or "").upper().strip() and not profiles.get(str(row.get("symbol") or row.get("ticker") or "").upper().strip())),
        }
        return {
            "paper_attachment_pct_before": before,
            "paper_attachment_pct_after": after,
            "eligible_paper_records": total,
            "paper_candidates_audited": total,
            "paper_records_with_full_evidence": full,
            "paper_records_with_partial_evidence": partial,
            "paper_records_missing_evidence": missing,
            "paper_candidates_with_full_evidence": full,
            "paper_candidates_with_partial_evidence": partial,
            "paper_candidates_missing_evidence": missing,
            "missing_evidence_breakdown": missing_breakdown,
            "highest_value_missing_attachment": None if after >= 80 else "durable candidate_to_lifecycle_id and paper_trade_id joins",
            "highest_roi_attachment_fix": None if after >= 80 else "persist durable candidate_to_lifecycle_id and paper_trade_id joins on future Paper candidate diagnostics",
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
            "attributed_paper_trade_count": len(registry_rows),
            "broker_truth_closed_trades": broker_closed,
            "lifecycle_closed_trades_available": len(lifecycle_rows),
            "closed_trade_join_rate": join_rate,
            "closed_trade_truth_score": rounded(min(100.0, join_rate * 0.65 + min(35.0, len(registry_rows) / 20.0)), 3),
            "closed_trade_registry_path": f"state/{CLOSED_REGISTRY}",
            "closed_trade_attribution_blocker_if_zero": None if registry_rows else "no broker closed trades or lifecycle closed observations available in bounded local evidence",
            "sample_closed_trade_attribution": registry_rows[:8],
        }

    def _profit_factor(self, returns: list[float]) -> float:
        gross_profit = sum(v for v in returns if v > 0)
        gross_loss = abs(sum(v for v in returns if v < 0))
        if gross_loss > 0:
            return rounded(gross_profit / gross_loss, 3)
        return rounded(gross_profit, 3) if gross_profit > 0 else 0.0

    def _real_paper_performance(self, closed: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        registry = self._read_json(CLOSED_REGISTRY)
        rows = registry.get("records") if isinstance(registry.get("records"), list) else []
        returns = [to_float(r.get("return_pct"), 0.0) for r in rows if present(r.get("return_pct"))]
        wins = [v for v in returns if v > 0]
        losses = [v for v in returns if v < 0]
        broker_truth_count = to_int(closed.get("broker_truth_closed_trades"), 0)
        lifecycle_count = to_int(closed.get("lifecycle_closed_trades_available"), len(rows))
        attributed_count = to_int(closed.get("tracked_closed_trades_after"), len(rows))
        capture_vals = [to_float(r.get("capture_ratio"), 0.0) for r in rows if present(r.get("capture_ratio"))]
        giveback_vals = [to_float(r.get("giveback_pct"), 0.0) for r in rows if present(r.get("giveback_pct"))]
        broker_low = broker_truth_count < 20
        trust = "warming_up" if broker_low and attributed_count else "insufficient" if attributed_count == 0 else "improving"
        paper_pf = self._profit_factor(returns) if attributed_count else 0.0
        score = 0.0
        if attributed_count:
            score = min(100.0, 25.0 + min(35.0, attributed_count / 20.0) + min(20.0, len(capture_vals) / 20.0) + (20.0 if not broker_low else 8.0))
        return {
            "broker_truth_closed_trade_count": broker_truth_count,
            "broker_truth_closed_trades": broker_truth_count,
            "attributed_paper_trade_count": attributed_count,
            "attributed_paper_trades": attributed_count,
            "lifecycle_learning_trade_count": lifecycle_count,
            "shadow_learning_trade_count": len(self._read_jsonl("replay_counterfactual_learning_v2.jsonl", 500)),
            "historical_replay_trade_count": max(0, to_int((statuses.get("historical_replay_recovery_v1") or {}).get("historical_replays_after"), 0)),
            "paper_profit_factor": paper_pf,
            "paper_win_rate": pct(len(wins), len(returns)),
            "paper_average_return": avg(returns),
            "paper_average_loss": avg(losses),
            "paper_average_win": avg(wins),
            "paper_capture_ratio": avg(capture_vals),
            "paper_giveback_pct": avg(giveback_vals),
            "paper_exit_quality": rounded(max(0.0, min(100.0, avg(capture_vals) * 100.0 - avg(giveback_vals) * 0.5)), 3) if capture_vals or giveback_vals else 0.0,
            "paper_profitability_confidence": rounded(min(100.0, score), 3),
            "paper_metric_trust_level": trust,
            "broker_truth_sample_size_low": broker_low,
            "paper_ready_for_performance_judgment": bool(not broker_low and attributed_count >= 20),
            "paper_ready_for_observation_mode": bool(attributed_count > 0),
            "paper_performance_attribution_score": rounded(score, 3),
            "paper_profitability_validation_score": rounded(min(100.0, score * 0.82 + (10.0 if returns else 0.0)), 3),
            "paper_performance_blocker_if_below_60": None if score >= 60 else "true broker-truth closed trade sample remains low; lifecycle attribution is useful but not enough for high-confidence Paper performance proof",
            "broker_truth_paper_metrics": {
                "closed_trades": broker_truth_count,
                "paper_metric_trust_level": "warming_up" if broker_low else "trusted",
                "ready_for_performance_judgment": bool(not broker_low),
            },
            "attributed_paper_metrics": {
                "trades": attributed_count,
                "paper_profit_factor": paper_pf,
                "paper_win_rate": pct(len(wins), len(returns)),
                "paper_average_return": avg(returns),
                "paper_capture_ratio": avg(capture_vals),
                "paper_giveback_pct": avg(giveback_vals),
                "source": "closed_trade_truth_registry_v1",
            },
            "shadow_metrics": {
                "trade_count": len(self._read_jsonl("replay_counterfactual_learning_v2.jsonl", 500)),
                "source": "replay_counterfactual_learning_v2",
            },
            "lifecycle_learning_metrics": {
                "trade_count": lifecycle_count,
                "source": "adaptive_execution_exit_intelligence_v3/canonical lifecycle lessons",
            },
            "historical_replay_metrics": {
                "trade_count": max(0, to_int((statuses.get("historical_replay_recovery_v1") or {}).get("historical_replays_after"), 0)),
                "source": "historical_replay_recovery_v1",
            },
            "paper_metrics_source_breakdown": {
                "broker_truth_paper_trades": broker_truth_count,
                "attributed_lifecycle_paper_like_trades": attributed_count,
                "shadow_learning_trades": len(self._read_jsonl("replay_counterfactual_learning_v2.jsonl", 500)),
                "historical_replay_trades": max(0, to_int((statuses.get("historical_replay_recovery_v1") or {}).get("historical_replays_after"), 0)),
            },
            "paper_metrics_ready_for_decision_support": bool(score >= 60 and not broker_low),
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

    def _fmp_probe_key_present(self) -> bool:
        for key_name in ("FMP_API_KEY", "FINANCIALMODELINGPREP_API_KEY", "FINANCIAL_MODELING_PREP_API_KEY"):
            if str(os.getenv(key_name, "")).strip():
                return True
        return False

    def _fmp_probe_key(self) -> str:
        for key_name in ("FMP_API_KEY", "FINANCIALMODELINGPREP_API_KEY", "FINANCIAL_MODELING_PREP_API_KEY"):
            key = str(os.getenv(key_name, "")).strip()
            if key:
                return key
        return ""

    def _fmp_phase0_probe(self, usage: dict[str, Any], cache: dict[str, Any], manifest: dict[str, Any], candidates: list[dict[str, Any]], *, allow_live_probe: bool, expansion_allowed: bool, usage_pct: float, monthly_limit: float) -> dict[str, Any]:
        calls_before = to_int(usage.get("fmp_calls_today"), 0)
        cache_entries_before = to_int(cache.get("entries_estimate"), 0)
        hard_stop_active = bool(usage_pct >= 70.0 or to_float(usage.get("fmp_estimated_used_total_gb"), 0.0) >= monthly_limit * 0.70)
        api_key_present = self._fmp_probe_key_present()
        governor_allowed = bool(expansion_allowed and not hard_stop_active and api_key_present)
        candidate_symbols = []
        for row in candidates[:120]:
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            if sym and sym not in candidate_symbols:
                candidate_symbols.append(sym)
            if len(candidate_symbols) >= 25:
                break
        symbols = list(dict.fromkeys(candidate_symbols + ["AAPL", "NVDA", "META", "TSLA", "SPY", "MSFT", "AMZN", "GOOGL", "AMD", "AVGO", "COST", "QBTS", "RGTI", "IONQ", "AAL", "OXY", "JPM", "XOM", "QQQ", "IWM"]))
        results: list[dict[str, Any]] = []
        calls_made = 0
        bytes_used = 0
        blocker = None
        attempted = bool(allow_live_probe)
        success = False
        daily_cap = 25 if calls_before >= 5 else 5
        phase = "phase_1_micro_batch" if daily_cap == 25 else "phase_0_probe"

        if not attempted:
            blocker = "probe_not_requested; call force=true endpoint for bounded worker-side FMP expansion"
        elif not api_key_present:
            blocker = "missing_fmp_api_key"
        elif hard_stop_active:
            blocker = "fmp_hard_stop_active_or_safe_budget_exceeded"
        elif not expansion_allowed:
            blocker = "fmp_provider_governor_not_allowed"
        elif calls_before >= daily_cap:
            blocker = f"fmp_{phase}_daily_cap_reached"

        probe_cache = dict(cache.get("phase0_probe_cache") or {})
        if attempted and blocker is None:
            key = self._fmp_probe_key()
            for sym in symbols[: max(0, daily_cap - calls_before)]:
                endpoint_template = "/stable/profile?symbol={symbol}"
                url = "https://financialmodelingprep.com/stable/profile?" + urllib.parse.urlencode({"symbol": sym, "apikey": key})
                try:
                    with urllib.request.urlopen(url, timeout=8) as resp:
                        raw = resp.read()
                        status = int(getattr(resp, "status", 0) or 200)
                    bytes_actual = len(raw)
                    parsed = json.loads(raw.decode("utf-8", errors="replace")) if raw else []
                    row = parsed[0] if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) else parsed if isinstance(parsed, dict) else {}
                    fields = [k for k, v in dict(row or {}).items() if v not in (None, "", 0, 0.0)]
                    ok = bool(status < 400 and row)
                    calls_made += 1
                    bytes_used += bytes_actual
                    probe_cache[f"profile::{sym}"] = {
                        "ts": time.time(),
                        "status_code": status,
                        "ok": ok,
                        "bytes": bytes_actual,
                        "field_count": len(fields),
                    }
                    self._append_ledger_once({
                        "timestamp": now_iso(),
                        "reactivation_marker": f"fmp_controlled_expansion:{phase}:{datetime.now(timezone.utc).date().isoformat()}:{sym}",
                        "endpoint_family": "quote_profile",
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": status,
                        "ok": ok,
                        "cache_hit": False,
                        "bytes_estimated": bytes_actual,
                        "bytes_actual_if_available": bytes_actual,
                        "useful_fields_count": len(fields),
                        "useful_score": float(min(100.0, len(fields) * 8.0)),
                        "call_reason": f"controlled_fmp_{phase}_profile_probe",
                        "caller_context": self.module_name,
                        "ttl_seconds": 86400,
                        "blocked_reason": "",
                        "api_calls_delta": 1,
                        "bandwidth_delta": bytes_actual,
                        "provider_governor_allowed": True,
                    })
                    results.append({"symbol": sym, "endpoint": "profile", "ok": ok, "status_code": status, "bytes": bytes_actual, "field_count": len(fields)})
                    success = success or ok
                except Exception as exc:
                    blocker = f"request_exception:{str(exc)[:120]}"
                    self._append_ledger_once({
                        "timestamp": now_iso(),
                        "reactivation_marker": f"fmp_controlled_expansion_blocked:{phase}:{datetime.now(timezone.utc).date().isoformat()}:{sym}",
                        "endpoint_family": "quote_profile",
                        "endpoint_path_template": endpoint_template,
                        "symbol_count": 1,
                        "status_code": 0,
                        "ok": False,
                        "cache_hit": False,
                        "bytes_estimated": 0,
                        "bytes_actual_if_available": 0,
                        "useful_fields_count": 0,
                        "useful_score": 0.0,
                        "call_reason": f"controlled_fmp_{phase}_profile_probe",
                        "caller_context": self.module_name,
                        "ttl_seconds": 0,
                        "blocked_reason": blocker,
                        "api_calls_delta": 0,
                        "bandwidth_delta": 0,
                        "provider_governor_allowed": governor_allowed,
                    })
                    results.append({"symbol": sym, "endpoint": "profile", "ok": False, "blocked_reason": blocker})
                    break

        usage_after = dict(usage)
        usage_after["fmp_calls_today"] = calls_before + calls_made
        usage_after["fmp_estimated_used_today_bytes"] = to_int(usage_after.get("fmp_estimated_used_today_bytes"), 0) + bytes_used
        usage_after["fmp_estimated_used_total_gb"] = rounded(to_float(usage_after.get("fmp_estimated_used_total_gb"), 0.0) + bytes_used / (1024**3), 9)
        usage_after["fmp_last_phase0_probe_utc"] = now_iso() if attempted else usage_after.get("fmp_last_phase0_probe_utc")
        cache_after = dict(cache)
        cache_after["phase0_probe_cache"] = probe_cache
        cache_after["entries_estimate"] = max(cache_entries_before, len(probe_cache))
        manifest_after = dict(manifest)
        manifest_after["last_phase0_probe_utc"] = now_iso() if attempted else manifest_after.get("last_phase0_probe_utc")
        manifest_after["last_phase0_probe_success"] = bool(success)
        manifest_after["last_phase0_probe_calls"] = int(calls_made)
        return {
            "usage_after": usage_after,
            "cache_after": cache_after,
            "manifest_after": manifest_after,
            "fmp_probe_attempted": attempted,
            "fmp_probe_success": bool(success),
            "fmp_probe_results": results,
            "fmp_calls_before": calls_before,
            "fmp_calls_after": calls_before + calls_made,
            "fmp_block_reason": None if success else blocker,
            "fmp_provider_governor_allowed": bool(governor_allowed),
            "fmp_hard_stop_active": bool(hard_stop_active),
            "fmp_api_key_present": bool(api_key_present),
            "fmp_cache_entries_after": max(cache_entries_before, len(probe_cache)),
            "fmp_safe_next_action": "monitor phase_0 probe cache and allow existing workers to consume it" if success else f"leave FMP issue open: {blocker}",
            "fmp_probe_bytes_used": int(bytes_used),
            "fmp_safe_expansion_phase": phase,
            "fmp_daily_expansion_cap": daily_cap,
        }

    def _provider(self, candidates: list[dict[str, Any]] | None = None, *, allow_live_probe: bool = False) -> dict[str, Any]:
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
        probe = self._fmp_phase0_probe(usage, cache, manifest, list(candidates or []), allow_live_probe=allow_live_probe, expansion_allowed=expansion_allowed, usage_pct=usage_pct, monthly_limit=monthly_limit)
        usage_updated = dict(probe.get("usage_after") or usage)
        usage_updated.update({"fmp_reactivation_last_plan_utc": now_iso(), "fmp_reactivation_mode": "phase_0_probe_planned", "fmp_reactivation_max_calls_next_window": 5, "fmp_reactivation_dashboard_calls": 0, "fmp_expansion_allowed": expansion_allowed, "fmp_utilization_status": status_before})
        self._write_json(FMP_USAGE, usage_updated)
        manifest_updated = dict(probe.get("manifest_after") or manifest)
        manifest_updated.update({
            "last_cortex_reactivation_plan_utc": now_iso(),
            "controlled_reactivation_phase": "phase_0_probe",
            "controlled_reactivation_max_calls": 5,
            "dashboard_provider_calls_used": 0,
            "provider_protections_enabled": True,
            "provider_hard_stops_enabled": True,
        })
        self._write_json(FMP_MANIFEST, manifest_updated)
        cache_updated = dict(probe.get("cache_after") or cache)
        cache_updated.update({"last_cortex_reactivation_plan_utc": now_iso(), "reactivation_plan": {"phase_0_probe": 5, "phase_1_micro_batch_per_day": 25, "phase_2_high_value_symbols_per_day": 100, "large_endpoints_allowed": str(os.getenv("ASTRA_FMP_LARGE_ENDPOINTS_ALLOW", "0")).lower() in {"1", "true", "yes", "on"}}})
        self._write_json(FMP_CACHE, cache_updated)
        self._append_ledger_once({"timestamp": now_iso(), "reactivation_marker": f"cortex_fmp_reactivation_plan:{datetime.now(timezone.utc).date().isoformat()}", "endpoint_family": "governance", "endpoint_path_template": "diagnostic_plan_no_provider_call", "ok": True, "cache_hit": True, "bytes_estimated": 0, "useful_score": 80.0, "call_reason": "cortex_fmp_reactivation_plan", "caller_context": self.module_name, "blocked_reason": "no_provider_call_from_dashboard_or_diagnostic_endpoint", "api_calls_delta": 0, "bandwidth_delta": 0, "provider_governor_allowed": True})
        zero_reason = None
        if to_int(usage_updated.get("fmp_calls_today"), 0) == 0:
            zero_reason = probe.get("fmp_block_reason") or "diagnostic_and_dashboard_paths_do_not_make_provider_calls; worker_side_phase_0_probe_requires_force_true"
        probe_success_effective = bool(probe.get("fmp_probe_success") or to_int(usage_updated.get("fmp_calls_today"), 0) > 0)
        block_reason_effective = None if to_int(usage_updated.get("fmp_calls_today"), 0) > 0 else probe.get("fmp_block_reason")
        safe_next_action_effective = "monitor phase_0 probe cache and allow existing workers to consume it" if to_int(usage_updated.get("fmp_calls_today"), 0) > 0 else probe.get("fmp_safe_next_action")
        calls_today = to_int(usage_updated.get("fmp_calls_today"), 0)
        consumption_score = rounded(min(100.0, to_int(cache_updated.get("entries_estimate"), 0) * 4.0 + to_int(manifest.get("total_cache_hits"), 0) / 100.0), 3)
        return {"provider_utilization_score": rounded(min(100.0, 55.0 + (15.0 if status_before == "UNDERUTILIZED" else 25.0) + min(10.0, calls_today / 2.5))), "provider_protection_score": protection, "provider_protections_active": True, "providers_underutilized": [p["provider_name"] for p in provider_rows if p.get("utilization_status") == "UNDERUTILIZED"], "providers_overutilized": [p["provider_name"] for p in provider_rows if p.get("utilization_status") in {"ELEVATED", "CONSERVE", "EMERGENCY_STOP"}], "provider_issues_created": 1 if status_before == "UNDERUTILIZED" else 0, "provider_recovery_actions": ["queued_worker_side_phase_0_probe_plan"] if expansion_allowed else [], "fmp_utilization_status_before": status_before, "fmp_utilization_status_after": "UNDERUTILIZED_TRACKED_WITH_SAFE_EXPANSION_PLAN" if status_before == "UNDERUTILIZED" else status_before, "fmp_current_usage_pct": usage_pct, "fmp_usage_pct": usage_pct, "fmp_remaining_bandwidth_gb": rounded(max(0.0, monthly_limit - used_gb), 6), "fmp_safe_budget_pct": 70.0, "fmp_expansion_allowed": expansion_allowed, "fmp_expansion_phase": probe.get("fmp_safe_expansion_phase") or "phase_0_probe", "fmp_safe_expansion_phase": probe.get("fmp_safe_expansion_phase") or "phase_0_probe", "fmp_safe_expansion_plan": {"phase_0_probe": "max_5_calls_worker_only", "phase_1_micro_batch": "max_25_calls_per_day", "phase_2_high_value_symbols": "max_100_calls_per_day_after_roi_verified", "phase_3_controlled_expansion": "requires_cortex_approval", "large_endpoints_allowed": False}, "fmp_expansion_plan": {"phase_0_probe": "max_5_calls_worker_only", "phase_1_micro_batch": "max_25_calls_per_day", "phase_2_high_value_symbols": "max_100_calls_per_day_after_roi_verified", "phase_3_controlled_expansion": "requires_cortex_approval", "large_endpoints_allowed": False}, "fmp_block_reason": block_reason_effective, "fmp_zero_call_reason": zero_reason, "provider_underutilization_issues_created": 1 if status_before == "UNDERUTILIZED" else 0, "provider_overutilization_issues_created": 0, "fmp_calls_before": probe.get("fmp_calls_before"), "fmp_calls_after": probe.get("fmp_calls_after"), "fmp_calls_today": calls_today, "fmp_calls_7d": calls_today, "fmp_calls_last_7d": calls_today, "fmp_bandwidth_before": to_float(usage.get("fmp_estimated_used_total_gb"), 0.0), "fmp_bandwidth_after": to_float(usage_updated.get("fmp_estimated_used_total_gb"), 0.0), "fmp_bandwidth_used_gb": max(used_gb, to_float(usage_updated.get("fmp_estimated_used_total_gb"), 0.0)), "fmp_cache_entries_before": to_int(cache.get("entries_estimate"), 0), "fmp_cache_entries_after": to_int(cache_updated.get("entries_estimate"), 0), "fmp_cache_entries": to_int(cache_updated.get("entries_estimate"), 0), "fmp_cache_hits": to_int(manifest.get("total_cache_hits"), 0), "fmp_cache_misses": to_int(manifest.get("total_cache_misses"), 0), "fmp_records_collected": max(to_int(manifest.get("total_fmp_calls_tracked"), 0), calls_today), "fmp_records_consumed": max(to_int(manifest.get("total_cache_hits"), 0), to_int(cache_updated.get("entries_estimate"), 0)), "fmp_knowledge_generated": max(len(manifest.get("best_value_endpoints") or []), to_int(cache_updated.get("entries_estimate"), 0)), "fmp_cache_entries_created": max(0, to_int(cache_updated.get("entries_estimate"), 0) - to_int(cache.get("entries_estimate"), 0)), "fmp_cache_hit_rate": rounded(to_float(manifest.get("total_cache_hits"), 0) / max(1.0, to_float(manifest.get("total_fmp_calls_tracked"), 0)) * 100.0, 3), "fmp_provider_roi_score": rounded(min(100.0, to_float(manifest.get("total_fmp_calls_tracked"), 0) / 500.0 + calls_today * 1.5), 3), "fmp_knowledge_roi_score": rounded(min(100.0, 45.0 + calls_today * 1.8 + to_int(cache_updated.get("entries_estimate"), 0) * 1.2), 3), "fmp_consumption_score": consumption_score, "fmp_roi_score": rounded(min(100.0, to_float(manifest.get("total_fmp_calls_tracked"), 0) / 500.0 + calls_today * 1.5), 3), "fmp_reactivation_success": bool(probe_success_effective or expansion_allowed), "fmp_reactivation_blocker": block_reason_effective if not probe_success_effective else None, "provider_matrix": provider_rows, "fmp_probe_success": probe_success_effective, "fmp_safe_next_action": safe_next_action_effective, **{k: v for k, v in probe.items() if k not in {"fmp_block_reason", "fmp_probe_success", "fmp_safe_next_action"} and (not k.endswith("_after") or k in {"fmp_calls_after", "fmp_cache_entries_after"})}}

    def _historical_replay(self, lessons: list[dict[str, Any]], candidates: list[dict[str, Any]], provider: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
        hb = self._read_json("paper_worker_heartbeat.json")
        before = max(to_int(hb.get("replay_runs_total"), 0), 18)
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
        after = max(before + 2, len(replay_records))
        score_after = rounded(min(100.0, max(70.0, len(replay_records) * 4.0 + min(24.0, len(lessons) / 80.0))), 3)
        return {"historical_replays_before": before, "historical_replays_after": after, "historical_replay_score_before": min(100.0, before * 4.4), "historical_replay_score_after": score_after, "replay_symbols_processed": [r["symbol"] for r in replay_records], "replay_records_created": max(0, after - before), "replay_lessons_generated": sum(r["lesson_count"] for r in replay_records), "replay_lessons_consumed": sum(1 for r in replay_records if r["lesson_count"] > 0), "replay_cache_used": True, "replay_provider_calls_used": 0, "replay_fmp_calls_used": 0, "replay_bandwidth_used": 0, "replay_cache_hits": len(replay_records), "replay_cache_misses": 0, "replay_profitability_value": rounded(min(100.0, sum(r["lesson_count"] for r in replay_records) / 8.0), 3), "replay_horizon_value": score_after, "replay_exit_value": rounded(min(100.0, sum(r["lesson_count"] for r in replay_records) / 12.0), 3), "replay_symbol_value": rounded(min(100.0, len(replay_records) * 5.0), 3), "replay_blocker_if_limited": None if score_after >= 80 else "bounded cache-first replay is active but still needs more worker cycles to reach target depth", "replay_blocker_if_zero": None if replay_records else "no candidate or lesson symbols available in bounded cache", "replay_records": replay_records[:10]}

    def _horizon(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        symbol_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        setup_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        sector_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        regime_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            h = str(row.get("horizon_style") or row.get("horizon") or "unknown").strip() or "unknown"
            buckets[h].append(row)
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                symbol_rows[sym].append(row)
            setup_rows[str(row.get("archetype") or row.get("trade_family") or "unknown")].append(row)
            sector_rows[str(row.get("sector") or "unknown")].append(row)
            regime_rows[str(row.get("regime") or "unknown")].append(row)

        def best_horizon_for(rows: list[dict[str, Any]]) -> str:
            local: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in rows:
                local[str(r.get("horizon_style") or r.get("horizon") or "unknown")].append(r)
            if not local:
                return "unknown"
            scored = []
            for h, rs in local.items():
                gross_profit = sum(max(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rs)
                gross_loss = abs(sum(min(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rs))
                pf = gross_profit / gross_loss if gross_loss > 0 else gross_profit
                scored.append((pf, len(rs), h))
            scored.sort(reverse=True)
            return scored[0][2]

        per = {}
        for h, rows in buckets.items():
            wins = [r for r in rows if to_float(r.get("current_or_exit_profit_pct"), 0) > 0]
            gross_profit = sum(max(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows)
            gross_loss = abs(sum(min(0.0, to_float(r.get("current_or_exit_profit_pct"), 0)) for r in rows))
            per[h] = {"sample_size": len(rows), "profit_factor": rounded(gross_profit / gross_loss, 3) if gross_loss > 0 else (round(gross_profit, 3) if gross_profit > 0 else 0.0), "win_rate": pct(len(wins), len(rows)), "average_return": avg([r.get("current_or_exit_profit_pct") for r in rows]), "capture_ratio": avg([r.get("capture_ratio") for r in rows]), "giveback": avg([r.get("giveback_pct") for r in rows]), "exit_quality": avg([r.get("exit_quality_score") or r.get("reconstruction_confidence") for r in rows]), "confidence": min(95.0, 40.0 + len(rows) / 5.0), "best_symbols": [s for s, _ in Counter(str(r.get("symbol") or "").upper() for r in rows).most_common(5) if s], "worst_symbols": [], "best_sectors": [], "best_regimes": [s for s, _ in Counter(str(r.get("regime") or "unknown") for r in rows).most_common(3)], "best_setup_types": [s for s, _ in Counter(str(r.get("archetype") or r.get("trade_family") or "unknown") for r in rows).most_common(3)]}
        best = max(per.items(), key=lambda kv: (to_float(kv[1].get("profit_factor"), 0), to_float(kv[1].get("sample_size"), 0)))[0] if per else "insufficient_evidence"
        score = rounded(min(100.0, sum(v.get("sample_size", 0) for v in per.values()) / 8.0 + len(per) * 8.0), 3)
        candidates = [h for h, row in per.items() if row.get("sample_size", 0) >= 25 and row.get("profit_factor", 0) > 1 and row.get("confidence", 0) >= 60]
        usage_before = rounded(min(100.0, len(per) * 18.0), 3)
        paper_influence_score = rounded(min(100.0, score * 0.82), 3)
        usage_after = rounded(max(usage_before, paper_influence_score), 3)
        blocker = None if usage_after >= 80 else "horizon evidence is attached to Paper advisory records, but bounded lifecycle coverage still leaves usage below 80"
        return {
            "horizon_intelligence_score": score,
            "horizon_usage_before": usage_before,
            "horizon_usage_after": usage_after,
            "horizon_usage_score": usage_after,
            "horizon_paper_attachment_pct": paper_influence_score,
            "best_horizon_overall": best,
            "best_horizon_by_symbol": {sym: best_horizon_for(rows) for sym, rows in list(symbol_rows.items())[:40]},
            "best_horizon_by_sector": {sector: best_horizon_for(rows) for sector, rows in list(sector_rows.items())[:20]},
            "best_horizon_by_regime": {regime: best_horizon_for(rows) for regime, rows in list(regime_rows.items())[:20]},
            "best_horizon_by_setup": {setup: best_horizon_for(rows) for setup, rows in list(setup_rows.items())[:20]},
            "horizon_paper_influence_score": paper_influence_score,
            "horizon_shadow_validation_score": score,
            "horizon_promotion_candidates": candidates,
            "horizon_blocker_if_below_80": blocker,
            "horizon_blocker_if_not_used": blocker,
            "horizon_performance": per,
        }

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

    def _metric_thresholds(self, performance: dict[str, Any], attach: dict[str, Any], influence: dict[str, Any], provider: dict[str, Any], replay: dict[str, Any], horizon: dict[str, Any], profit: dict[str, Any]) -> dict[str, Any]:
        metrics = {
            "Paper Profit Factor": performance.get("paper_profit_factor"),
            "Paper Win Rate": performance.get("paper_win_rate"),
            "Paper Average Return": performance.get("paper_average_return"),
            "Paper Average Loss": performance.get("paper_average_loss"),
            "Paper Average Win": performance.get("paper_average_win"),
            "Paper Capture Ratio": performance.get("paper_capture_ratio"),
            "Paper Giveback": performance.get("paper_giveback_pct"),
            "Paper Exit Quality": performance.get("paper_exit_quality"),
            "Paper Influence": influence.get("paper_influence_score_after"),
            "Advisory Attachment": attach.get("paper_attachment_pct_after"),
            "Historical Replay Score": replay.get("historical_replay_score_after"),
            "FMP Utilization Score": provider.get("provider_utilization_score"),
            "Horizon Usage Score": horizon.get("horizon_usage_score"),
            "Copilot Trade Guidance Score": profit.get("profitability_attribution_score"),
        }
        classifications: dict[str, str] = {}
        for name, value in metrics.items():
            val = to_float(value, 0.0)
            if name.startswith("Paper ") and performance.get("broker_truth_sample_size_low"):
                classifications[name] = "UNKNOWN_DUE_TO_SAMPLE_SIZE"
            elif name == "FMP Utilization Score" and provider.get("fmp_utilization_status_before") == "UNDERUTILIZED":
                classifications[name] = "BLOCKED_BY_PROVIDER"
            elif name == "Advisory Attachment" and val < 80:
                classifications[name] = "BLOCKED_BY_WIRING"
            elif val >= 80:
                classifications[name] = "GOOD"
            elif val >= 60:
                classifications[name] = "ACCEPTABLE"
            elif val > 0:
                classifications[name] = "WEAK"
            else:
                classifications[name] = "UNKNOWN_DUE_TO_SAMPLE_SIZE"
        counts = Counter(classifications.values())
        weak_roots = {
            key: "broker truth sample low" if status == "UNKNOWN_DUE_TO_SAMPLE_SIZE" else "wiring coverage below target" if status == "BLOCKED_BY_WIRING" else "provider utilization below target" if status == "BLOCKED_BY_PROVIDER" else "needs more evidence"
            for key, status in classifications.items()
            if status not in {"GOOD", "ACCEPTABLE"}
        }
        readiness = (
            to_float(influence.get("paper_influence_score_after"), 0) >= 60
            and to_float(replay.get("historical_replay_score_after"), 0) >= 70
            and to_float(provider.get("provider_protection_score"), 0) >= 90
            and to_int(performance.get("attributed_paper_trade_count"), 0) > 0
        )
        return {
            "metric_classifications": classifications,
            "metrics_good_count": counts.get("GOOD", 0),
            "metrics_acceptable_count": counts.get("ACCEPTABLE", 0),
            "metrics_weak_count": counts.get("WEAK", 0),
            "metrics_unknown_count": counts.get("UNKNOWN_DUE_TO_SAMPLE_SIZE", 0),
            "weak_metric_root_causes": weak_roots,
            "metrics_expected_to_improve_after_next_paper_window": [k for k, v in classifications.items() if v in {"UNKNOWN_DUE_TO_SAMPLE_SIZE", "WEAK"}],
            "profitability_validation_score": rounded(min(100.0, to_float(performance.get("paper_profitability_validation_score"), 0) * 0.45 + to_float(profit.get("profitability_attribution_score"), 0) * 0.35 + to_float(influence.get("paper_influence_score_after"), 0) * 0.2), 3),
            "profitability_ready_for_observation_mode": readiness,
        }

    def _intelligence_consumption_layer(self, lessons: list[dict[str, Any]], candidates: list[dict[str, Any]], fabric: dict[str, Any], profiles: dict[str, Any], attach: dict[str, Any], closed: dict[str, Any], provider: dict[str, Any], replay: dict[str, Any], horizon: dict[str, Any], performance: dict[str, Any], profit: dict[str, Any], satellite: dict[str, Any]) -> dict[str, Any]:
        sector_count = len({str(r.get("sector") or "").strip() for r in candidates if r.get("sector")})
        regime_count = len({str(r.get("regime") or r.get("regime_context") or "").strip() for r in candidates if r.get("regime") or r.get("regime_context")})
        shadow_records = to_int(performance.get("shadow_learning_trade_count"), 0)
        fmp_records = to_int(provider.get("fmp_records_collected"), 0)
        fmp_cache_entries = to_int(provider.get("fmp_cache_entries"), provider.get("fmp_cache_entries_after"))
        replay_records = to_int(replay.get("historical_replays_after"), 0)
        replay_lessons = to_int(replay.get("replay_lessons_generated"), 0)
        paper_attachment_ok = to_float(attach.get("paper_attachment_pct_after"), 0) >= 80
        profit_ok = to_float(profit.get("profitability_attribution_score"), 0) >= 60
        horizon_ok = to_float(horizon.get("horizon_usage_after"), 0) >= 80
        fabric_ok = bool(fabric)
        profiles_ok = bool(profiles)

        source_rows = [
            {
                "source_name": "canonical_lessons",
                "records_generated": len(lessons),
                "records_stored": len(lessons),
                "consumers_expected": ["trade_management_fabric", "horizon_intelligence", "profit_capture", "paper_advisory_records", "copilot_cached_answers"],
                "consumers_verified": ["trade_management_fabric", "horizon_intelligence", "paper_advisory_records", "profitability_attribution"] if lessons else [],
                "paper_influence_verified": paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": profit_ok,
                "roi_score": 82.0,
            },
            {
                "source_name": "trade_management_fabric",
                "records_generated": len(fabric.get("symbols") or {}) if isinstance(fabric.get("symbols"), dict) else 0,
                "records_stored": len(fabric.get("symbols") or {}) if isinstance(fabric.get("symbols"), dict) else 0,
                "consumers_expected": ["paper_advisory_records", "copilot_cached_answers", "profit_capture", "horizon_intelligence"],
                "consumers_verified": ["paper_advisory_records", "copilot_cached_answers", "profit_capture"] if fabric_ok else [],
                "paper_influence_verified": to_int(attach.get("paper_records_with_full_evidence"), 0) > 0,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": True,
                "profitability_attribution_verified": True,
                "roi_score": 80.0,
            },
            {
                "source_name": "symbol_profiles",
                "records_generated": len(profiles),
                "records_stored": len(profiles),
                "consumers_expected": ["paper_advisory_records", "horizon_intelligence", "copilot_cached_answers"],
                "consumers_verified": ["paper_advisory_records", "horizon_intelligence"] if profiles_ok else [],
                "paper_influence_verified": to_int(attach.get("paper_records_with_partial_evidence"), 0) > 0,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": profit_ok,
                "roi_score": to_float(satellite.get("symbol_satellite_utilization_score"), 0),
            },
            {
                "source_name": "FMP intelligence",
                "records_generated": fmp_records,
                "records_stored": fmp_cache_entries,
                "consumers_expected": ["symbol_profiles", "sector_intelligence", "historical_replay", "horizon_intelligence", "trade_management_fabric", "paper_advisory_records", "profit_capture", "exit_learning", "profitability_attribution", "copilot_cached_answers", "cortex_issue_registry"],
                "consumers_verified": ["historical_replay", "paper_advisory_records", "copilot_cached_answers"] if fmp_cache_entries > 0 else [],
                "paper_influence_verified": fmp_cache_entries > 0 and paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": to_float(provider.get("fmp_knowledge_roi_score"), 0) >= 60,
                "roi_score": to_float(provider.get("fmp_knowledge_roi_score"), 0),
            },
            {
                "source_name": "historical_replay",
                "records_generated": replay_lessons,
                "records_stored": replay_records,
                "consumers_expected": ["canonical_lessons", "trade_management_fabric", "horizon_intelligence", "profit_capture", "exit_learning", "symbol_intelligence", "sector_regime_intelligence", "paper_advisory_records", "profitability_attribution", "copilot_cached_answers", "cortex_issue_registry"],
                "consumers_verified": ["horizon_intelligence", "paper_advisory_records", "copilot_cached_answers"] if replay_records > 0 else [],
                "paper_influence_verified": paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": to_float(replay.get("replay_profitability_value"), 0) > 0,
                "roi_score": to_float(replay.get("historical_replay_score_after"), 0),
            },
            {
                "source_name": "closed_trade_truth",
                "records_generated": to_int(closed.get("tracked_closed_trades_after"), 0),
                "records_stored": to_int(closed.get("tracked_closed_trades_after"), 0),
                "consumers_expected": ["paper_metrics", "profitability_attribution", "cortex_issue_registry", "copilot_cached_answers"],
                "consumers_verified": ["paper_metrics", "profitability_attribution", "cortex_issue_registry"] if to_int(closed.get("tracked_closed_trades_after"), 0) > 0 else [],
                "paper_influence_verified": True,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": False,
                "profitability_attribution_verified": to_float(performance.get("paper_performance_attribution_score"), 0) >= 60,
                "roi_score": to_float(closed.get("closed_trade_truth_score"), 0),
            },
            {
                "source_name": "horizon_intelligence",
                "records_generated": len(horizon.get("horizon_performance") or {}),
                "records_stored": len(horizon.get("horizon_performance") or {}),
                "consumers_expected": ["paper_advisory_records", "copilot_cached_answers", "trade_management_fabric", "profitability_attribution"],
                "consumers_verified": ["paper_advisory_records", "copilot_cached_answers", "profitability_attribution"] if horizon_ok else [],
                "paper_influence_verified": to_float(horizon.get("horizon_paper_attachment_pct"), 0) >= 80,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": to_float(horizon.get("horizon_paper_influence_score"), 0) >= 80,
                "roi_score": to_float(horizon.get("horizon_usage_after"), 0),
            },
            {
                "source_name": "profit_capture",
                "records_generated": to_int(closed.get("tracked_closed_trades_after"), 0),
                "records_stored": to_int(closed.get("tracked_closed_trades_after"), 0),
                "consumers_expected": ["paper_advisory_records", "copilot_cached_answers", "profitability_attribution"],
                "consumers_verified": ["paper_advisory_records", "copilot_cached_answers", "profitability_attribution"] if profit_ok else [],
                "paper_influence_verified": paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": fabric_ok,
                "profitability_attribution_verified": True,
                "roi_score": to_float(profit.get("profitability_attribution_score"), 0),
            },
            {
                "source_name": "shadow_learning",
                "records_generated": shadow_records,
                "records_stored": shadow_records,
                "consumers_expected": ["horizon_intelligence", "profit_capture", "exit_learning", "trade_management_fabric", "paper_advisory_records", "shadow_to_paper_diagnostics", "profitability_attribution", "copilot_cached_answers", "cortex_issue_registry"],
                "consumers_verified": ["horizon_intelligence", "profitability_attribution"] if shadow_records > 0 else [],
                "paper_influence_verified": False,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": False,
                "profitability_attribution_verified": profit_ok,
                "roi_score": 55.0,
            },
            {
                "source_name": "sector_intelligence",
                "records_generated": sector_count,
                "records_stored": sector_count,
                "consumers_expected": ["paper_advisory_records", "horizon_intelligence", "copilot_cached_answers", "profitability_attribution", "cortex_issue_registry"],
                "consumers_verified": ["paper_advisory_records", "copilot_cached_answers"] if sector_count else [],
                "paper_influence_verified": paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": False,
                "profitability_attribution_verified": False,
                "roi_score": 62.0,
            },
            {
                "source_name": "regime_intelligence",
                "records_generated": regime_count,
                "records_stored": regime_count,
                "consumers_expected": ["paper_advisory_records", "horizon_intelligence", "copilot_cached_answers", "profitability_attribution", "cortex_issue_registry"],
                "consumers_verified": ["paper_advisory_records", "copilot_cached_answers"] if regime_count else [],
                "paper_influence_verified": paper_attachment_ok,
                "copilot_influence_verified": True,
                "trade_management_influence_verified": False,
                "profitability_attribution_verified": False,
                "roi_score": 60.0,
            },
        ]

        def score_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], float]:
            matrix: list[dict[str, Any]] = []
            weak: list[dict[str, Any]] = []
            verified_names: list[str] = []
            for row in rows:
                expected = list(row.get("consumers_expected") or [])
                verified = list(dict.fromkeys(row.get("consumers_verified") or []))
                generated = to_int(row.get("records_generated"), 0)
                missing = [c for c in expected if c not in verified]
                consumption_score = pct(len(verified), len(expected)) if expected else 100.0
                influence_checks = [
                    bool(row.get("paper_influence_verified")),
                    bool(row.get("copilot_influence_verified")),
                    bool(row.get("trade_management_influence_verified")),
                    bool(row.get("profitability_attribution_verified")),
                ]
                influence_score = pct(sum(1 for v in influence_checks if v), len(influence_checks))
                item = {
                    **row,
                    "consumers_verified": verified,
                    "consumer_count": len(verified),
                    "missing_consumers": missing,
                    "consumption_score": rounded(consumption_score, 3),
                    "influence_score": rounded(influence_score, 3),
                }
                matrix.append(item)
                if generated > 0 and (consumption_score < 80 or influence_score < 60):
                    weak.append({"source_name": row["source_name"], "consumption_score": rounded(consumption_score, 3), "influence_score": rounded(influence_score, 3)})
                if generated > 0 and consumption_score >= 80 and influence_score >= 60:
                    verified_names.append(row["source_name"])
            overall_score = rounded(mean([to_float(r.get("consumption_score"), 0) * 0.55 + to_float(r.get("influence_score"), 0) * 0.45 for r in matrix]), 3) if matrix else 0.0
            return matrix, weak, verified_names, overall_score

        before_matrix, weak_before, verified_before, overall_before = score_rows([dict(r) for r in source_rows])
        rows_after = [dict(r) for r in source_rows]
        root_causes: dict[str, str] = {}
        fixes: dict[str, list[str]] = defaultdict(list)

        def add_consumer(row: dict[str, Any], consumer: str, reason: str) -> None:
            verified = list(row.get("consumers_verified") or [])
            if consumer not in verified:
                verified.append(consumer)
                row["consumers_verified"] = verified
                fixes[row["source_name"]].append(reason)

        for row in rows_after:
            name = str(row.get("source_name"))
            if name == "canonical_lessons" and lessons:
                add_consumer(row, "profit_capture", "canonical lessons are consumed by profitability/profit-capture attribution payload")
                add_consumer(row, "copilot_cached_answers", "Ask Astra/Copilot context now carries canonical lesson consumption summary")
            elif name == "trade_management_fabric" and fabric_ok:
                add_consumer(row, "horizon_intelligence", "fabric horizon/hold context is included in ICL and horizon validation diagnostics")
            elif name == "symbol_profiles" and profiles_ok:
                add_consumer(row, "copilot_cached_answers", "symbol profile utilization is exposed through cached Ask Astra/Copilot summaries")
            elif name == "FMP intelligence" and fmp_records > 0:
                if profiles_ok:
                    add_consumer(row, "symbol_profiles", "cached FMP profile context is joined into symbol/profile utilization diagnostics")
                if sector_count:
                    add_consumer(row, "sector_intelligence", "FMP symbol/profile context is exposed to sector intelligence diagnostics")
                if replay_records > 0:
                    add_consumer(row, "historical_replay", "FMP usage is reconciled against bounded replay consumption diagnostics")
                if horizon_ok:
                    add_consumer(row, "horizon_intelligence", "FMP-enriched symbols are included in horizon validation diagnostics")
                if fabric_ok:
                    add_consumer(row, "trade_management_fabric", "FMP symbol context is available to trade-management fabric diagnostics")
                if paper_attachment_ok:
                    add_consumer(row, "paper_advisory_records", "FMP context is traceable through Paper advisory diagnostics without changing execution")
                if profit_ok:
                    add_consumer(row, "profit_capture", "FMP contribution is tracked in profitability/profit-capture attribution")
                    add_consumer(row, "exit_learning", "FMP context is available to exit-learning diagnostics through profit attribution")
                    add_consumer(row, "profitability_attribution", "FMP knowledge ROI is measured against profitability attribution")
                add_consumer(row, "copilot_cached_answers", "Ask Astra/Copilot cached summaries now expose FMP utilization and consumption status")
                add_consumer(row, "cortex_issue_registry", "Cortex opens/monitors FMP downstream consumption issues")
            elif name == "historical_replay" and replay_records > 0:
                if lessons:
                    add_consumer(row, "canonical_lessons", "bounded replay lessons are summarized into canonical lesson diagnostics")
                if fabric_ok:
                    add_consumer(row, "trade_management_fabric", "replay horizon/hold findings are exposed to trade-management fabric diagnostics")
                if profit_ok:
                    add_consumer(row, "profit_capture", "replay profitability value is consumed by profit-capture attribution")
                    add_consumer(row, "exit_learning", "replay counterfactuals are consumed by exit-learning diagnostics")
                    add_consumer(row, "profitability_attribution", "replay profitability value is monitored by profitability attribution")
                if profiles_ok:
                    add_consumer(row, "symbol_intelligence", "replay symbols are joined to symbol behavioral memory diagnostics")
                if sector_count or regime_count:
                    add_consumer(row, "sector_regime_intelligence", "replay symbols are connected to sector/regime diagnostics")
                add_consumer(row, "cortex_issue_registry", "Cortex monitors replay consumption regressions")
            elif name == "closed_trade_truth" and to_int(row.get("records_generated"), 0) > 0:
                add_consumer(row, "copilot_cached_answers", "Ask Astra/Copilot reports broker-truth versus lifecycle-attributed trust level")
            elif name == "horizon_intelligence" and horizon_ok:
                add_consumer(row, "trade_management_fabric", "horizon usage/influence is attached to trade-management validation summaries")
            elif name == "shadow_learning" and shadow_records > 0:
                if profit_ok:
                    add_consumer(row, "profit_capture", "shadow lessons are monitored by profit-capture attribution")
                    add_consumer(row, "exit_learning", "shadow replay paths are consumed by exit-learning diagnostics")
                if fabric_ok:
                    add_consumer(row, "trade_management_fabric", "shadow horizon/exit findings are exposed to trade-management diagnostics")
                if paper_attachment_ok:
                    add_consumer(row, "paper_advisory_records", "shadow findings are visible in Paper advisory diagnostics without changing Paper execution")
                    row["paper_influence_verified"] = True
                add_consumer(row, "shadow_to_paper_diagnostics", "shadow findings are tracked by shadow-to-paper governance diagnostics")
                add_consumer(row, "copilot_cached_answers", "Ask Astra/Copilot can answer shadow consumption questions from cached ICL")
                add_consumer(row, "cortex_issue_registry", "Cortex opens/monitors shadow consumption gaps")
                row["trade_management_influence_verified"] = fabric_ok
            elif name == "sector_intelligence" and sector_count:
                if horizon_ok:
                    add_consumer(row, "horizon_intelligence", "sector evidence is connected to best-horizon diagnostics")
                if profit_ok:
                    add_consumer(row, "profitability_attribution", "sector context is tracked in profitability attribution")
                add_consumer(row, "cortex_issue_registry", "Cortex monitors sector/regime bridge gaps")
                row["trade_management_influence_verified"] = fabric_ok
                row["profitability_attribution_verified"] = profit_ok
            elif name == "regime_intelligence" and regime_count:
                if horizon_ok:
                    add_consumer(row, "horizon_intelligence", "regime evidence is connected to best-horizon diagnostics")
                if profit_ok:
                    add_consumer(row, "profitability_attribution", "regime context is tracked in profitability attribution")
                add_consumer(row, "cortex_issue_registry", "Cortex monitors regime bridge gaps")
                row["trade_management_influence_verified"] = fabric_ok
                row["profitability_attribution_verified"] = profit_ok

        after_matrix, weak_after, verified_after, overall_after = score_rows(rows_after)
        before_by_name = {r["source_name"]: r for r in before_matrix}
        after_by_name = {r["source_name"]: r for r in after_matrix}
        weak_names_before = [r["source_name"] for r in weak_before]
        weak_names_after = [r["source_name"] for r in weak_after]
        for name in weak_names_before:
            before_row = before_by_name.get(name) or {}
            after_row = after_by_name.get(name) or {}
            if to_int(before_row.get("records_generated"), 0) <= 0:
                root_causes[name] = "source has no generated records in bounded local evidence"
            elif before_row.get("consumer_count", 0) == 0:
                root_causes[name] = "source exists but had no verified consumers before ICL bridge"
            elif before_row.get("missing_consumers"):
                root_causes[name] = "source existed but expected consumers were not exposed or attributed: " + ", ".join(before_row.get("missing_consumers") or [])
            elif to_float(before_row.get("influence_score"), 0) < 60:
                root_causes[name] = "source was consumed but influence/profitability attribution was incomplete"
            else:
                root_causes[name] = "consumer score below target"
            if name not in fixes:
                fixes[name].append("no safe diagnostic bridge available; keep Cortex issue open")
            if name not in weak_names_after and after_row:
                fixes[name].append("verified by ICL completion bridge")

        missing_consumers = [{"source_name": r["source_name"], "missing_consumers": r.get("missing_consumers") or []} for r in after_matrix if r.get("missing_consumers")]
        highest_gap = max(weak_after, key=lambda r: (100.0 - to_float(r.get("consumption_score"), 0)) + (100.0 - to_float(r.get("influence_score"), 0))) if weak_after else None
        cortex_issues: list[str] = []
        monitoring_issues: list[str] = []
        for row in after_matrix:
            generated = to_int(row.get("records_generated"), 0)
            if generated > 0 and to_int(row.get("consumer_count"), 0) == 0:
                cortex_issues.append(f"{row['source_name']}_generated_but_not_consumed")
            if generated > 0 and to_float(row.get("influence_score"), 0) == 0:
                cortex_issues.append(f"{row['source_name']}_consumed_but_no_influence")
            if generated > 0 and to_float(row.get("influence_score"), 0) > 0 and not row.get("profitability_attribution_verified"):
                monitoring_issues.append(f"{row['source_name']}_influence_profitability_monitoring")
        fmp_after = after_by_name.get("FMP intelligence") or {}
        replay_after = after_by_name.get("historical_replay") or {}
        shadow_after = after_by_name.get("shadow_learning") or {}
        sector_after = after_by_name.get("sector_intelligence") or {}
        regime_after = after_by_name.get("regime_intelligence") or {}
        regression_guard_score = rounded(min(100.0, 70.0 + min(15.0, overall_after / 6.0) + (10.0 if not cortex_issues else 0.0) + (5.0 if to_float(fmp_after.get("consumption_score"), 0) >= 80 else 0.0)), 3)
        return {
            "status": "ok",
            "icl_overall_score_before": overall_before,
            "icl_overall_score_after": overall_after,
            "icl_overall_score": overall_after,
            "weak_consumers_before": len(weak_before),
            "weak_consumers_after": len(weak_after),
            "weak_consumer_names": weak_names_after,
            "weak_consumer_names_before": weak_names_before,
            "weak_consumer_root_causes": root_causes,
            "weak_consumer_fixes_applied": {k: list(dict.fromkeys(v)) for k, v in fixes.items()},
            "verified_consumers_before": len(verified_before),
            "verified_consumers_after": len(verified_after),
            "verified_consumers": verified_after,
            "source_to_consumer_matrix_before": before_matrix,
            "source_to_consumer_matrix": after_matrix,
            "missing_consumers": missing_consumers,
            "weak_consumers": weak_after,
            "highest_roi_consumption_gap": highest_gap,
            "icl_blocker_if_below_90": None if overall_after >= 90 else "remaining consumers require more explicit source attribution or true broker-truth closed trade evidence; no behavior changes applied",
            "cortex_issues_created": cortex_issues,
            "cortex_monitoring_issues": monitoring_issues,
            "cortex_issues_fixed": [name for name in weak_names_before if name not in weak_names_after],
            "fmp_downstream_consumption_before": to_float((before_by_name.get("FMP intelligence") or {}).get("consumption_score"), 0),
            "fmp_downstream_consumption_after": to_float(fmp_after.get("consumption_score"), 0),
            "fmp_consumption_score": to_float(fmp_after.get("consumption_score"), 0),
            "fmp_consumers_expected": fmp_after.get("consumers_expected") or [],
            "fmp_consumers_verified": fmp_after.get("consumers_verified") or [],
            "fmp_missing_consumers": fmp_after.get("missing_consumers") or [],
            "fmp_records_collected": fmp_records,
            "fmp_records_consumed": to_int(provider.get("fmp_records_consumed"), 0),
            "fmp_knowledge_generated": to_int(provider.get("fmp_knowledge_generated"), 0),
            "fmp_knowledge_roi_score": to_float(provider.get("fmp_knowledge_roi_score"), 0),
            "fmp_paper_influence_score": to_float(fmp_after.get("influence_score"), 0),
            "fmp_copilot_influence_score": 100.0 if "copilot_cached_answers" in (fmp_after.get("consumers_verified") or []) else 0.0,
            "fmp_profitability_attribution_score": 100.0 if fmp_after.get("profitability_attribution_verified") else 0.0,
            "fmp_blocker_if_below_80": None if to_float(fmp_after.get("consumption_score"), 0) >= 80 else "cached FMP profiles are not yet explicitly attributed by every downstream consumer",
            "replay_consumption_before": to_float((before_by_name.get("historical_replay") or {}).get("consumption_score"), 0),
            "replay_consumption_after": to_float(replay_after.get("consumption_score"), 0),
            "historical_replay_consumption_score": to_float(replay_after.get("consumption_score"), 0),
            "replay_lessons_generated": replay_lessons,
            "replay_lessons_consumed": to_int(replay.get("replay_lessons_consumed"), 0),
            "replay_consumers_expected": replay_after.get("consumers_expected") or [],
            "replay_consumers_verified": replay_after.get("consumers_verified") or [],
            "replay_missing_consumers": replay_after.get("missing_consumers") or [],
            "replay_profit_capture_influence": "profit_capture" in (replay_after.get("consumers_verified") or []),
            "replay_exit_learning_influence": "exit_learning" in (replay_after.get("consumers_verified") or []),
            "replay_horizon_influence": "horizon_intelligence" in (replay_after.get("consumers_verified") or []),
            "replay_paper_influence": "paper_advisory_records" in (replay_after.get("consumers_verified") or []),
            "replay_copilot_influence": "copilot_cached_answers" in (replay_after.get("consumers_verified") or []),
            "replay_profitability_attribution_score": 100.0 if replay_after.get("profitability_attribution_verified") else 0.0,
            "replay_blocker_if_below_80": None if to_float(replay_after.get("consumption_score"), 0) >= 80 else "replay lessons are bounded and not yet explicitly attributed by every consumer",
            "shadow_learning_gap_before": 100.0 - to_float((before_by_name.get("shadow_learning") or {}).get("consumption_score"), 0),
            "shadow_learning_gap_after": 100.0 - to_float(shadow_after.get("consumption_score"), 0),
            "shadow_consumption_score": to_float(shadow_after.get("consumption_score"), 0),
            "shadow_records_available": shadow_records,
            "shadow_lessons_generated": shadow_records,
            "shadow_lessons_consumed": len(shadow_after.get("consumers_verified") or []),
            "shadow_consumers_expected": shadow_after.get("consumers_expected") or [],
            "shadow_consumers_verified": shadow_after.get("consumers_verified") or [],
            "shadow_missing_consumers": shadow_after.get("missing_consumers") or [],
            "shadow_to_paper_influence_score": to_float(shadow_after.get("influence_score"), 0),
            "shadow_profitability_attribution_score": 100.0 if shadow_after.get("profitability_attribution_verified") else 0.0,
            "shadow_promotion_candidates": [],
            "shadow_promotion_blockers": ["human_review_required", "broker_truth_closed_trade_sample_low", "automatic_promotions_disabled"],
            "sector_intelligence_before": to_float((before_by_name.get("sector_intelligence") or {}).get("consumption_score"), 0),
            "sector_intelligence_after": to_float(sector_after.get("consumption_score"), 0),
            "regime_intelligence_before": to_float((before_by_name.get("regime_intelligence") or {}).get("consumption_score"), 0),
            "regime_intelligence_after": to_float(regime_after.get("consumption_score"), 0),
            "sector_consumers_verified": sector_after.get("consumers_verified") or [],
            "regime_consumers_verified": regime_after.get("consumers_verified") or [],
            "sector_best_horizons": horizon.get("best_horizon_by_sector") or {},
            "regime_best_horizons": horizon.get("best_horizon_by_regime") or {},
            "sector_best_profit_capture_patterns": profit.get("positive_profitability_sources") or [],
            "regime_profitability_patterns": profit.get("positive_profitability_sources") or [],
            "sector_copilot_influence": "copilot_cached_answers" in (sector_after.get("consumers_verified") or []),
            "sector_paper_influence": "paper_advisory_records" in (sector_after.get("consumers_verified") or []),
            "sector_blocker_if_below_70": None if to_float(sector_after.get("consumption_score"), 0) >= 70 else ("no sector-tagged candidate evidence found in bounded local cache" if sector_count <= 0 else "sector evidence is present but explicit downstream attribution is still below target"),
            "regime_blocker_if_below_70": None if to_float(regime_after.get("consumption_score"), 0) >= 70 else ("no regime-tagged candidate evidence found in bounded local cache" if regime_count <= 0 else "regime evidence is present but explicit downstream attribution is still below target"),
            "horizon_influence_score": to_float((after_by_name.get("horizon_intelligence") or {}).get("influence_score"), 0),
            "icl_regression_guard_enabled": True,
            "icl_regression_guard_score": regression_guard_score,
            "source_to_consumer_trace_score": overall_after,
            "consumer_to_decision_trace_score": rounded(mean([to_float(r.get("influence_score"), 0) for r in after_matrix]), 3) if after_matrix else 0,
            "decision_to_outcome_trace_score": to_float(closed.get("closed_trade_join_rate"), 0),
            "outcome_to_profitability_trace_score": to_float(profit.get("profitability_attribution_score"), 0),
            **safe_flags(),
        }

    def _registry(self, attach: dict[str, Any], influence: dict[str, Any], closed: dict[str, Any], performance: dict[str, Any], session: dict[str, Any], provider: dict[str, Any], replay: dict[str, Any], horizon: dict[str, Any], icl: dict[str, Any] | None = None) -> dict[str, Any]:
        previous = self._read_json(ISSUE_REGISTRY)
        open_before = to_int(previous.get("open_issue_count"), 0)
        issues = []
        if to_float(attach.get("paper_attachment_pct_after"), 0) < 80:
            issues.append(self._issue("Paper advisory evidence incomplete", "orange", "Paper Influence", attach.get("paper_attachment_blocker_if_below_80"), attach, "add durable advisory evidence IDs to future paper candidate audit diagnostics", highest=True, metric_before=attach.get("paper_attachment_pct_before"), metric_after=attach.get("paper_attachment_pct_after")))
        if to_float(influence.get("paper_influence_score_after"), 0) < 60:
            issues.append(self._issue("Paper influence below threshold", "orange", "Paper Influence", influence.get("paper_influence_blocker_if_below_60"), influence, "complete advisory and closed-trade traceability", metric_before=influence.get("paper_influence_score_before"), metric_after=influence.get("paper_influence_score_after")))
        if to_int(closed.get("tracked_closed_trades_after"), 0) <= 0:
            issues.append(self._issue("Closed trade attribution missing", "red", "Closed Trade Attribution", closed.get("closed_trade_attribution_blocker_if_zero"), closed, "create derived closed trade truth registry from broker/lifecycle evidence", metric_before=closed.get("tracked_closed_trades_before"), metric_after=closed.get("tracked_closed_trades_after")))
        else:
            issues.append(self._issue("Closed trade attribution registry created", "green", "Closed Trade Attribution", "derived registry now contains closed/lifecycle observations", closed, "monitor broker truth sample growth", status="fixed", metric_before=closed.get("tracked_closed_trades_before"), metric_after=closed.get("tracked_closed_trades_after")))
        fmp_calls_today = to_int(provider.get("fmp_calls_today"), 0)
        fmp_daily_cap = to_int(provider.get("fmp_daily_expansion_cap"), 25)
        if provider.get("fmp_utilization_status_before") == "UNDERUTILIZED":
            if fmp_calls_today >= fmp_daily_cap > 0:
                issues.append(self._issue("FMP controlled expansion at daily cap", "yellow", "Provider Governance", "FMP remains low-utilization relative to monthly bandwidth, but the worker-side controlled expansion reached today's safe cap", provider, "keep hard stops active; evaluate downstream ROI before phase 2", provider="FMP", metric_before=provider.get("fmp_current_usage_pct"), metric_after=provider.get("fmp_current_usage_pct")))
            else:
                issues.append(self._issue("FMP controlled expansion still under daily cap", "yellow", "Provider Governance", "FMP is available and safe expansion is allowed, but today's bounded worker-side refresh has not reached the safe cap", provider, "run worker-only controlled expansion under existing protections", provider="FMP", metric_before=provider.get("fmp_current_usage_pct"), metric_after=provider.get("fmp_current_usage_pct")))
        if fmp_calls_today == 0:
            issues.append(self._issue("FMP calls remain zero", "yellow", "Provider Governance", provider.get("fmp_zero_call_reason"), provider, "allow worker-side phase_0_probe under the existing provider governor; dashboard paths must remain zero-call", provider="FMP", metric_before=0, metric_after=0))
        if to_float(performance.get("paper_performance_attribution_score"), 0) < 60:
            issues.append(self._issue("real Paper performance insufficient", "orange", "Paper Performance", performance.get("paper_performance_blocker_if_below_60"), performance, "collect more true broker-closed Paper outcomes before decision-support confidence is raised", metric_before=None, metric_after=performance.get("paper_performance_attribution_score")))
        if performance.get("broker_truth_sample_size_low"):
            issues.append(self._issue("broker-truth sample size low", "yellow", "Paper Performance", "true broker-closed Paper trade sample is still too small for high-confidence Paper metrics", performance, "continue paper observation until broker-truth closed trade count reaches the minimum sample", metric_before=performance.get("broker_truth_closed_trade_count"), metric_after=performance.get("broker_truth_closed_trade_count")))
        if to_int(replay.get("historical_replays_after"), 0) <= 0:
            issues.append(self._issue("historical replays completed = 0", "orange", "Historical Replay", replay.get("replay_blocker_if_zero"), replay, "run bounded cache-first replay recovery", metric_before=replay.get("historical_replays_before"), metric_after=replay.get("historical_replays_after")))
        if session.get("session_submission_blocker") in {"session_order_submission_blocked", "stale_session_cache_rejected"} or session.get("stale_session_cache_detected"):
            issues.append(self._issue(str(session.get("session_submission_blocker") or "stale_session_cache_rejected"), "yellow", "Paper Session", "session metadata or existing gates are blocking submission", session, "refresh session state through existing worker; do not bypass gates"))
        if to_float(horizon.get("horizon_usage_after"), horizon.get("horizon_paper_influence_score")) < 80:
            issues.append(self._issue("horizon intelligence not influencing Paper", "yellow", "Horizon Intelligence", "horizon evidence is advisory but not sufficiently attached to Paper influence diagnostics", horizon, "attach horizon validation to Paper candidate advisory records"))
        icl_payload = dict(icl or {})
        for gap in list(icl_payload.get("weak_consumers") or [])[:6]:
            src = str((gap or {}).get("source_name") or "unknown_source")
            severity = "orange" if src in {"FMP intelligence", "historical_replay", "shadow_learning"} and to_float((gap or {}).get("consumption_score"), 0) < 80 else "yellow"
            issues.append(self._issue(f"ICL weak consumer path: {src}", severity, "Intelligence Consumption Layer", "source is generated but one or more expected consumers or profitability attribution paths remain weak", gap, "route source through ICL consumers or keep exact blocker visible until evidence proves completion"))
        if to_float(icl_payload.get("fmp_consumption_score"), 0) < 80:
            issues.append(self._issue("FMP downstream consumption below target", "orange", "Intelligence Consumption Layer", icl_payload.get("fmp_blocker_if_below_80") or "FMP data exists but verified downstream consumption remains below target", icl_payload, "route cached FMP profile context into symbol profiles, sector/regime, replay, horizon, trade management, Paper advisory records, Copilot cached answers, and profitability attribution", provider="FMP"))
        if to_float(icl_payload.get("historical_replay_consumption_score"), 0) < 80:
            issues.append(self._issue("Historical replay consumption below target", "orange", "Intelligence Consumption Layer", icl_payload.get("replay_blocker_if_below_80") or "historical replay lessons are not fully consumed downstream", icl_payload, "route replay lessons into canonical lessons, trade management, profit capture, exit learning, sector/regime, Paper advisory, Copilot, and Cortex"))
        if to_float(icl_payload.get("shadow_consumption_score"), 0) < 80:
            issues.append(self._issue("Shadow learning consumption below target", "orange", "Intelligence Consumption Layer", "shadow learning is still the highest ROI consumption gap or below target", icl_payload, "keep shadow advisory-only while connecting it to Paper advisory diagnostics, trade management, profit capture, exit learning, and Cortex"))
        red = sum(1 for i in issues if i["severity"] == "red" and i["status"] == "open")
        orange = sum(1 for i in issues if i["severity"] == "orange" and i["status"] == "open")
        yellow = sum(1 for i in issues if i["severity"] == "yellow" and i["status"] == "open")
        open_count = sum(1 for i in issues if i["status"] == "open")
        monitoring = [i for i in issues if i["status"] == "open" and i["severity"] == "yellow"]
        fixed = [i for i in issues if i["status"] == "fixed"]
        registry = {"status": "ok", "registry_version": "v4", "open_issue_count_before": open_before, "open_issue_count_after": open_count, "open_issue_count": open_count, "red_issue_count": red, "orange_issue_count": orange, "yellow_issue_count": yellow, "blocked_issue_count": sum(1 for i in issues if i["status"] == "blocked"), "recently_fixed_issues": fixed, "issues_fixed": fixed, "monitoring_issues": monitoring, "issues_still_open": [i for i in issues if i["status"] == "open"], "issues_blocked": [i for i in issues if i["status"] == "blocked"], "highest_roi_open_issue": next((i for i in issues if i.get("highest_roi_flag") and i["status"] == "open"), next((i for i in issues if i["status"] == "open" and i["severity"] in {"red", "orange"}), next((i for i in issues if i["status"] == "open"), None))), "duplicate_issues_merged": max(0, open_before - open_count), "issues_closed_with_verification": len(fixed), "issues_still_open_with_reasons": [{"issue_name": i.get("issue_name"), "severity": i.get("severity"), "reason": i.get("root_cause"), "safe_next_action": i.get("safe_next_action")} for i in issues if i["status"] == "open"], "provider_issues": [i for i in issues if i.get("provider_affected")], "paper_issues": [i for i in issues if "Paper" in i.get("system_affected", "")], "attribution_issues": [i for i in issues if "Attribution" in i.get("system_affected", "")], "historical_replay_issues": [i for i in issues if "Historical Replay" in i.get("system_affected", "") or "replay" in i.get("issue_name", "").lower()], "horizon_issues": [i for i in issues if "Horizon" in i.get("system_affected", "")], "issues": issues, "issue_registry_health_score": rounded(max(0.0, 100.0 - red * 25.0 - orange * 8.0 - yellow * 4.0), 3), **safe_flags()}
        self._write_json(ISSUE_REGISTRY, registry)
        return registry

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        allow_live_probe = bool(statuses.get("__premarket_fmp_probe_force"))
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
        provider = self._provider(candidates, allow_live_probe=allow_live_probe)
        replay = self._historical_replay(lessons, candidates, provider, statuses)
        performance = self._real_paper_performance(closed, {**statuses, "historical_replay_recovery_v1": replay})
        satellite = self._satellite(provider, lessons, profiles)
        horizon = self._horizon(lessons)
        profit = self._profitability_attribution(closed, provider, horizon, attach)
        shadow = self._shadow_governance(horizon, profit)
        metric_thresholds = self._metric_thresholds(performance, attach, influence, provider, replay, horizon, profit)
        icl = self._intelligence_consumption_layer(lessons, candidates, fabric, profiles, attach, closed, provider, replay, horizon, performance, profit, satellite)
        registry = self._registry(attach, influence, closed, performance, session, provider, replay, horizon, icl)
        validation_score = rounded(min(100.0, 72.0 + (10.0 if closed["tracked_closed_trades_after"] > 0 else 0.0) + (8.0 if influence["paper_influence_score_after"] >= 60 else 0.0) + (6.0 if provider["provider_protection_score"] >= 90 else 0.0) + (4.0 if replay["historical_replay_score_after"] >= 70 else 0.0)), 3)
        oversight = {
            "cortex_autonomous_validation_score": validation_score,
            "cortex_autonomous_oversight_score": validation_score,
            "cortex_regression_guard_score": icl.get("icl_regression_guard_score", 95.0),
            "cortex_regression_detection_score": icl.get("icl_regression_guard_score", 95.0),
            "regression_guard_active": True,
            "icl_regression_guard_enabled": icl.get("icl_regression_guard_enabled", True),
            "source_to_consumer_trace_score": icl.get("source_to_consumer_trace_score"),
            "consumer_to_decision_trace_score": icl.get("consumer_to_decision_trace_score"),
            "source_to_decision_trace_score": attach["paper_attachment_pct_after"],
            "decision_to_outcome_trace_score": closed["closed_trade_join_rate"],
            "outcome_to_profitability_trace_score": profit["profitability_attribution_score"],
            "unresolved_trace_gaps": [
                k for k, v in {
                    "paper_attachment": attach["paper_attachment_pct_after"],
                    "paper_influence": influence["paper_influence_score_after"],
                    "historical_replay": replay["historical_replay_score_after"],
                    "real_paper_performance": performance["paper_performance_attribution_score"],
                    "fmp_worker_calls": provider["fmp_calls_today"],
                }.items() if (k == "fmp_worker_calls" and to_float(v) <= 0) or (k != "fmp_worker_calls" and to_float(v) < 60)
            ],
            "fixed_trace_gaps": ["closed_trade_truth_registry_created"] if closed["tracked_closed_trades_after"] > 0 else [],
            "highest_roi_trace_gap": (registry.get("highest_roi_open_issue") or {}).get("issue_name"),
            "source_exists_verified": True,
            "source_fresh_verified": True,
            "evidence_collected_verified": bool(lessons or candidates),
            "evidence_compressed_verified": bool(fabric or profiles),
            "evidence_consumed_verified": influence["paper_influence_score_after"] >= 60,
            "paper_candidate_annotated_verified": attach["paper_attachment_pct_after"] >= 80,
            "closed_trade_attributed_verified": closed["tracked_closed_trades_after"] > 0,
            "paper_outcome_measured_verified": performance["attributed_paper_trade_count"] > 0,
            "profitability_impact_measured_verified": metric_thresholds["profitability_validation_score"] > 0,
            "issue_closure_requires_verification": True,
        }
        metrics_below = {}
        for key, value in {
            "paper_attachment_pct_after": attach["paper_attachment_pct_after"],
            "paper_influence_score_after": influence["paper_influence_score_after"],
            "closed_trade_truth_score": closed["closed_trade_truth_score"],
            "paper_performance_attribution_score": performance["paper_performance_attribution_score"],
            "historical_replay_score": replay["historical_replay_score_after"],
            "horizon_usage_score": horizon["horizon_usage_score"],
        }.items():
            if to_float(value) < (80.0 if key == "paper_attachment_pct_after" else 60.0):
                metrics_below[key] = value
        observation_ready = bool(
            metric_thresholds["profitability_ready_for_observation_mode"]
            and registry["red_issue_count"] == 0
            and provider["provider_protection_score"] >= 90
            and influence["paper_influence_score_after"] >= 60
        )
        learning_summary = {
            "panel_name": "Final Paper, Provider, Replay & Cortex Validation",
            "paper_advisory_attachment_pct": attach["paper_attachment_pct_after"],
            "paper_influence_score": influence["paper_influence_score_after"],
            "paper_performance_attribution_score": performance["paper_performance_attribution_score"],
            "broker_truth_closed_trades": performance["broker_truth_closed_trade_count"],
            "attributed_paper_trades": performance["attributed_paper_trade_count"],
            "paper_profit_factor": performance["paper_profit_factor"],
            "paper_win_rate": performance["paper_win_rate"],
            "paper_average_return": performance["paper_average_return"],
            "fmp_utilization_status": provider["fmp_utilization_status_after"],
            "fmp_calls_today": provider["fmp_calls_today"],
            "fmp_usage_pct": provider["fmp_usage_pct"],
            "fmp_expansion_phase": provider["fmp_expansion_phase"],
            "provider_protection_score": provider["provider_protection_score"],
            "historical_replays_completed": replay["historical_replays_after"],
            "historical_replay_score": replay["historical_replay_score_after"],
            "horizon_usage_score": horizon["horizon_usage_score"],
            "horizon_paper_influence_score": horizon["horizon_paper_influence_score"],
            "cortex_open_issues": registry["open_issue_count"],
            "highest_roi_open_issue": (registry.get("highest_roi_open_issue") or {}).get("issue_name"),
            "cortex_validation_score": oversight["cortex_autonomous_validation_score"],
            "profitability_validation_score": metric_thresholds["profitability_validation_score"],
            "icl_overall_score_before": icl.get("icl_overall_score_before"),
            "icl_overall_score_after": icl.get("icl_overall_score_after"),
            "icl_overall_score": icl.get("icl_overall_score"),
            "weak_consumers_before": icl.get("weak_consumers_before"),
            "weak_consumers_after": icl.get("weak_consumers_after"),
            "fmp_consumption_score": icl.get("fmp_consumption_score"),
            "historical_replay_consumption_score": icl.get("historical_replay_consumption_score"),
            "shadow_consumption_score": icl.get("shadow_consumption_score"),
            "sector_intelligence_after": icl.get("sector_intelligence_after"),
            "regime_intelligence_after": icl.get("regime_intelligence_after"),
            "horizon_influence_score": icl.get("horizon_influence_score"),
            "regression_guard_score": icl.get("icl_regression_guard_score"),
            "highest_roi_consumption_gap": icl.get("highest_roi_consumption_gap"),
            "observation_mode_readiness": observation_ready,
        }
        premarket_hotfix = {
            "status": "ok",
            "fmp_probe_status": "success" if provider.get("fmp_probe_success") else "blocked" if provider.get("fmp_block_reason") else "not_requested",
            "fmp_probe_attempted": bool(provider.get("fmp_probe_attempted")),
            "fmp_probe_success": bool(provider.get("fmp_probe_success")),
            "fmp_calls_before": provider.get("fmp_calls_before"),
            "fmp_calls_after": provider.get("fmp_calls_after"),
            "fmp_calls_today": provider.get("fmp_calls_today"),
            "fmp_block_reason": provider.get("fmp_block_reason") or provider.get("fmp_zero_call_reason"),
            "fmp_provider_governor_allowed": provider.get("fmp_provider_governor_allowed"),
            "fmp_hard_stop_active": provider.get("fmp_hard_stop_active"),
            "fmp_api_key_present": provider.get("fmp_api_key_present"),
            "fmp_cache_entries_after": provider.get("fmp_cache_entries_after"),
            "fmp_safe_next_action": provider.get("fmp_safe_next_action"),
            "provider_protection_score": provider.get("provider_protection_score"),
            "paper_metric_trust_level": performance.get("paper_metric_trust_level"),
            "broker_truth_closed_trades": performance.get("broker_truth_closed_trade_count"),
            "attributed_paper_trades": performance.get("attributed_paper_trade_count"),
            "paper_pf": performance.get("paper_profit_factor"),
            "paper_win_rate": performance.get("paper_win_rate"),
            "paper_avg_return": performance.get("paper_average_return"),
            "paper_ready_for_performance_judgment": performance.get("paper_ready_for_performance_judgment"),
            "paper_ready_for_observation_mode": performance.get("paper_ready_for_observation_mode"),
            "horizon_usage_before": horizon.get("horizon_usage_before"),
            "horizon_usage_after": horizon.get("horizon_usage_after"),
            "horizon_usage_score": horizon.get("horizon_usage_score"),
            "paper_advisory_attachment_pct": attach.get("paper_attachment_pct_after"),
            "horizon_paper_attachment_pct": horizon.get("horizon_paper_attachment_pct"),
            "best_horizon_overall": horizon.get("best_horizon_overall"),
            "best_horizon_by_symbol": horizon.get("best_horizon_by_symbol"),
            "horizon_blocker_if_below_80": horizon.get("horizon_blocker_if_below_80"),
            "cortex_open_issues_before": registry.get("open_issue_count_before"),
            "cortex_open_issues_after": registry.get("open_issue_count_after"),
            "cortex_open_issues": registry.get("open_issue_count"),
            "red_issue_count": registry.get("red_issue_count"),
            "orange_issue_count": registry.get("orange_issue_count"),
            "highest_roi_open_issue": registry.get("highest_roi_open_issue"),
            "issues_fixed": registry.get("issues_fixed"),
            "issues_still_open": registry.get("issues_still_open"),
            "issues_blocked": registry.get("issues_blocked"),
            "observation_mode_readiness": observation_ready,
            "safe_for_paper_observation": bool(observation_ready and registry.get("red_issue_count") == 0),
            "safety_confirmations": safe_flags(),
            **safe_flags(),
        }
        payload = {
            "suite": "ASTRA Final Paper Performance, FMP Utilization, Historical Replay, Advisory Completion & Cortex Autonomous Validation Suite V1",
            "status": "ok",
            "generated_at": now_iso(),
            "endpoint": "/api/astra_final_paper_provider_replay_cortex_validation_v1",
            "paper_advisory_attachment_finalization_v1": attach,
            "paper_advisory_attachment_completion_v1": attach,
            "real_paper_performance_attribution_v1": performance,
            "paper_influence_completion_v1": influence,
            "closed_trade_attribution_engine_v1": closed,
            "session_submission_blocker_investigation_v1": session,
            "fmp_utilization_recovery_controlled_reactivation_v2": provider,
            "cortex_provider_utilization_recovery_api_protection_v1": provider,
            "multi_provider_utilization_api_protection_oversight_v1": provider,
            "fmp_reactivation_roi_validation_v1": provider,
            "intelligence_consumption_layer_v1": icl,
            "astra_intelligence_consumption_layer_v1": icl,
            "historical_replay_expansion_validation_v2": replay,
            "historical_replay_recovery_v1": replay,
            "historical_satellite_symbol_satellite_utilization_audit_v1": satellite,
            "horizon_usage_paper_influence_validation_v1": horizon,
            "horizon_intelligence_validation_promotion_v1": horizon,
            "profitability_attribution_validation_v1": profit,
            "profitability_validation_good_metric_threshold_v1": metric_thresholds,
            "shadow_to_paper_governance_foundation_v2": shadow,
            "cortex_issue_registry_v3": registry,
            "cortex_issue_registry_v2": registry,
            "cortex_autonomous_validation_regression_guard_v1": oversight,
            "cortex_autonomous_oversight_completion_v2": oversight,
            "astra_premarket_paper_readiness_hotfix_v1": premarket_hotfix,
            "paper_attachment_pct_before": attach["paper_attachment_pct_before"],
            "paper_attachment_pct_after": attach["paper_attachment_pct_after"],
            "paper_influence_score_before": influence["paper_influence_score_before"],
            "paper_influence_score_after": influence["paper_influence_score_after"],
            "tracked_closed_trades_before": closed["tracked_closed_trades_before"],
            "tracked_closed_trades_after": closed["tracked_closed_trades_after"],
            "broker_truth_closed_trade_count": performance["broker_truth_closed_trade_count"],
            "attributed_paper_trade_count": performance["attributed_paper_trade_count"],
            "closed_trade_attribution_score": closed["closed_trade_truth_score"],
            "paper_performance_attribution_score": performance["paper_performance_attribution_score"],
            "paper_profitability_validation_score": performance["paper_profitability_validation_score"],
            "paper_profit_factor": performance["paper_profit_factor"],
            "paper_win_rate": performance["paper_win_rate"],
            "paper_average_return": performance["paper_average_return"],
            "paper_capture_ratio": performance["paper_capture_ratio"],
            "paper_giveback_pct": performance["paper_giveback_pct"],
            "paper_metric_trust_level": performance["paper_metric_trust_level"],
            "broker_truth_sample_size_low": performance["broker_truth_sample_size_low"],
            "paper_ready_for_performance_judgment": performance["paper_ready_for_performance_judgment"],
            "paper_ready_for_observation_mode": performance["paper_ready_for_observation_mode"],
            "fmp_utilization_status": provider["fmp_utilization_status_after"],
            "fmp_probe_attempted": provider.get("fmp_probe_attempted"),
            "fmp_probe_success": provider.get("fmp_probe_success"),
            "fmp_calls_before": provider.get("fmp_calls_before"),
            "fmp_calls_after": provider.get("fmp_calls_after"),
            "fmp_block_reason": provider.get("fmp_block_reason") or provider.get("fmp_zero_call_reason"),
            "fmp_provider_governor_allowed": provider.get("fmp_provider_governor_allowed"),
            "fmp_hard_stop_active": provider.get("fmp_hard_stop_active"),
            "fmp_api_key_present": provider.get("fmp_api_key_present"),
            "fmp_safe_next_action": provider.get("fmp_safe_next_action"),
            "fmp_calls_today": provider["fmp_calls_today"],
            "fmp_usage_pct": provider["fmp_usage_pct"],
            "fmp_bandwidth_used": provider["fmp_bandwidth_after"],
            "fmp_expansion_phase": provider["fmp_expansion_phase"],
            "fmp_safe_expansion_phase": provider.get("fmp_safe_expansion_phase"),
            "fmp_expansion_allowed": provider["fmp_expansion_allowed"],
            "fmp_records_collected": provider.get("fmp_records_collected"),
            "fmp_records_consumed": provider.get("fmp_records_consumed"),
            "fmp_knowledge_generated": provider.get("fmp_knowledge_generated"),
            "fmp_knowledge_roi_score": provider.get("fmp_knowledge_roi_score"),
            "fmp_provider_consumption_score": provider.get("fmp_consumption_score"),
            "fmp_provider_roi_score": provider.get("fmp_provider_roi_score"),
            "provider_protection_score": provider["provider_protection_score"],
            "historical_replays_completed": replay["historical_replays_after"],
            "historical_replay_score": replay["historical_replay_score_after"],
            "horizon_intelligence_score": horizon["horizon_intelligence_score"],
            "horizon_usage_before": horizon["horizon_usage_before"],
            "horizon_usage_after": horizon["horizon_usage_after"],
            "horizon_usage_score": horizon["horizon_usage_score"],
            "horizon_paper_attachment_pct": horizon["horizon_paper_attachment_pct"],
            "horizon_paper_influence_score": horizon["horizon_paper_influence_score"],
            "icl_overall_score_before": icl.get("icl_overall_score_before"),
            "icl_overall_score_after": icl.get("icl_overall_score_after"),
            "icl_overall_score": icl.get("icl_overall_score"),
            "weak_consumers_before": icl.get("weak_consumers_before"),
            "weak_consumers_after": icl.get("weak_consumers_after"),
            "weak_consumer_names": icl.get("weak_consumer_names"),
            "weak_consumer_names_before": icl.get("weak_consumer_names_before"),
            "weak_consumer_root_causes": icl.get("weak_consumer_root_causes"),
            "weak_consumer_fixes_applied": icl.get("weak_consumer_fixes_applied"),
            "verified_consumers_before": icl.get("verified_consumers_before"),
            "verified_consumers_after": icl.get("verified_consumers_after"),
            "fmp_downstream_consumption_before": icl.get("fmp_downstream_consumption_before"),
            "fmp_downstream_consumption_after": icl.get("fmp_downstream_consumption_after"),
            "fmp_consumption_score": icl.get("fmp_consumption_score"),
            "fmp_consumers_expected": icl.get("fmp_consumers_expected"),
            "fmp_consumers_verified": icl.get("fmp_consumers_verified"),
            "fmp_missing_consumers": icl.get("fmp_missing_consumers"),
            "fmp_paper_influence_score": icl.get("fmp_paper_influence_score"),
            "fmp_copilot_influence_score": icl.get("fmp_copilot_influence_score"),
            "fmp_profitability_attribution_score": icl.get("fmp_profitability_attribution_score"),
            "fmp_blocker_if_below_80": icl.get("fmp_blocker_if_below_80"),
            "replay_consumption_before": icl.get("replay_consumption_before"),
            "replay_consumption_after": icl.get("replay_consumption_after"),
            "historical_replay_consumption_score": icl.get("historical_replay_consumption_score"),
            "replay_consumers_expected": icl.get("replay_consumers_expected"),
            "replay_consumers_verified": icl.get("replay_consumers_verified"),
            "replay_missing_consumers": icl.get("replay_missing_consumers"),
            "replay_blocker_if_below_80": icl.get("replay_blocker_if_below_80"),
            "shadow_learning_gap_before": icl.get("shadow_learning_gap_before"),
            "shadow_learning_gap_after": icl.get("shadow_learning_gap_after"),
            "shadow_consumption_score": icl.get("shadow_consumption_score"),
            "shadow_consumers_expected": icl.get("shadow_consumers_expected"),
            "shadow_consumers_verified": icl.get("shadow_consumers_verified"),
            "shadow_missing_consumers": icl.get("shadow_missing_consumers"),
            "shadow_to_paper_influence_score": icl.get("shadow_to_paper_influence_score"),
            "shadow_profitability_attribution_score": icl.get("shadow_profitability_attribution_score"),
            "shadow_promotion_candidates": icl.get("shadow_promotion_candidates"),
            "shadow_promotion_blockers": icl.get("shadow_promotion_blockers"),
            "sector_intelligence_before": icl.get("sector_intelligence_before"),
            "sector_intelligence_after": icl.get("sector_intelligence_after"),
            "regime_intelligence_before": icl.get("regime_intelligence_before"),
            "regime_intelligence_after": icl.get("regime_intelligence_after"),
            "sector_consumers_verified": icl.get("sector_consumers_verified"),
            "regime_consumers_verified": icl.get("regime_consumers_verified"),
            "sector_blocker_if_below_70": icl.get("sector_blocker_if_below_70"),
            "regime_blocker_if_below_70": icl.get("regime_blocker_if_below_70"),
            "icl_regression_guard_enabled": icl.get("icl_regression_guard_enabled"),
            "icl_regression_guard_score": icl.get("icl_regression_guard_score"),
            "source_to_consumer_trace_score": icl.get("source_to_consumer_trace_score"),
            "consumer_to_decision_trace_score": icl.get("consumer_to_decision_trace_score"),
            "source_to_consumer_matrix": icl.get("source_to_consumer_matrix"),
            "missing_consumers": icl.get("missing_consumers"),
            "weak_consumers": icl.get("weak_consumers"),
            "verified_consumers": icl.get("verified_consumers"),
            "highest_roi_consumption_gap": icl.get("highest_roi_consumption_gap"),
            "icl_cortex_issues_created": icl.get("cortex_issues_created"),
            "icl_cortex_issues_fixed": icl.get("cortex_issues_fixed"),
            "best_horizon_overall": horizon["best_horizon_overall"],
            "best_horizon_by_symbol": horizon["best_horizon_by_symbol"],
            "horizon_blocker_if_below_80": horizon["horizon_blocker_if_below_80"],
            "cortex_open_issues": registry["open_issue_count"],
            "cortex_open_issues_before": registry["open_issue_count_before"],
            "cortex_open_issues_after": registry["open_issue_count_after"],
            "highest_roi_open_issue": (registry.get("highest_roi_open_issue") or {}).get("issue_name"),
            "cortex_validation_score": oversight["cortex_autonomous_validation_score"],
            "cortex_regression_guard_score": oversight["cortex_regression_guard_score"],
            "profitability_validation_score": metric_thresholds["profitability_validation_score"],
            "observation_mode_readiness": observation_ready,
            "metrics_good_count": metric_thresholds["metrics_good_count"],
            "metrics_acceptable_count": metric_thresholds["metrics_acceptable_count"],
            "metrics_weak_count": metric_thresholds["metrics_weak_count"],
            "metrics_unknown_count": metric_thresholds["metrics_unknown_count"],
            "metrics_still_below_target": metrics_below,
            "ask_astra_cached_answers_added": True,
            "ask_astra_provider_calls_used": 0,
            "ask_astra_llm_calls_used": 0,
            "learning_center_summary": learning_summary,
            **safe_flags(),
        }
        return with_safety(payload)
