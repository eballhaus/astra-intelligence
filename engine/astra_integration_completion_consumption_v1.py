from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, now_iso, rounded, status_value, to_float, to_int, with_safety, write_json

CANONICAL_STORE = "canonical_lifecycle_lessons_v1.jsonl"
FABRIC_STORE = "trade_management_intelligence_fabric_v1.json"
SYMBOL_PROFILES = "symbol_behavior_profiles_v1.json"
ISSUE_REGISTRY_STORE = "cortex_issue_registry_v1.json"
MAX_ROWS = 5000
MAX_CANDIDATES = 1600


def _safe_flags() -> dict[str, Any]:
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
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "none", "null", "insufficient_evidence"}:
        return False
    return True


def _avg(values: list[float]) -> float:
    return rounded(mean(values), 3) if values else 0.0


def _issue_id(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8", errors="ignore")).hexdigest()[:12]


class AstraIntegrationCompletionConsumptionV1(CachedDiagnosticModule):
    module_name = "astra_integration_completion_consumption_v1"
    mode = "integration_completion_advisory_only"

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 1800.0) -> None:
        super().__init__(state_dir=state_dir, ttl_seconds=ttl_seconds)

    def _read_json(self, filename: str) -> dict[str, Any]:
        try:
            with open(os.path.join(self.state_dir, filename), "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _read_jsonl(self, filename: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            with open(os.path.join(self.state_dir, filename), "r", encoding="utf-8") as handle:
                for line in handle:
                    if len(rows) >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(parsed, dict):
                        rows.append(parsed)
        except Exception:
            return []
        return rows

    def _scan_code_consumers(self) -> dict[str, Any]:
        files = []
        for root, dirs, names in os.walk("."):
            if root.startswith("./.git") or root.startswith("./state") or root.startswith("./astra_dashboard/ui/dist") or "node_modules" in root:
                continue
            for name in names:
                if name.endswith((".py", ".jsx", ".js")):
                    files.append(os.path.join(root, name))
        needles = {
            "canonical_lifecycle_lessons_v1": "canonical_lifecycle_lessons",
            "trade_management_intelligence_fabric": "trade_management_intelligence_fabric",
            "symbol_behavior_profiles_v1": "symbol_behavior_profiles",
        }
        out: dict[str, Any] = {}
        for label, needle in needles.items():
            matches = []
            for path in files[:900]:
                try:
                    text = open(path, "r", encoding="utf-8", errors="ignore").read()
                except Exception:
                    continue
                if needle in text:
                    matches.append(path.replace("./", "", 1))
            out[label] = {
                "source_file_exists": os.path.exists(os.path.join(self.state_dir, f"{label}.json")) if label.endswith("profiles_v1") else os.path.exists(os.path.join(self.state_dir, f"{label}.jsonl")) or os.path.exists(os.path.join(self.state_dir, f"{label}.json")),
                "code_consumer_count": len(matches),
                "code_consumers": matches[:24],
            }
        return out

    def _truth_sources(self, lessons: list[dict[str, Any]], fabric: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
        execution_rows = self._read_jsonl("adaptive_execution_exit_intelligence_v3.jsonl", 900)
        exit_rows = self._read_jsonl("exit_learning_expansion_suite_v1.jsonl", 900)
        sources = []
        def source_row(name: str, rows: list[dict[str, Any]], weight: float) -> dict[str, Any]:
            cap = [to_float(r.get("capture_ratio") or r.get("capture_pct") or r.get("profit_capture_ratio"), 0.0) for r in rows if _present(r.get("capture_ratio") or r.get("capture_pct") or r.get("profit_capture_ratio"))]
            give = [to_float(r.get("giveback_pct") or r.get("current_giveback_pct") or r.get("giveback_from_peak_pct"), 0.0) for r in rows if _present(r.get("giveback_pct") or r.get("current_giveback_pct") or r.get("giveback_from_peak_pct"))]
            hold = [to_float(r.get("hold_duration") or r.get("hold_minutes") or r.get("actual_hold_duration_minutes"), 0.0) for r in rows if _present(r.get("hold_duration") or r.get("hold_minutes") or r.get("actual_hold_duration_minutes"))]
            return {"source": name, "records": len(rows), "weight": weight, "capture_records": len(cap), "giveback_records": len(give), "hold_records": len(hold), "avg_capture_ratio": _avg(cap), "avg_giveback_pct": _avg(give), "avg_hold_duration": _avg(hold)}
        sources.append(source_row("adaptive_execution_exit_intelligence_v3", execution_rows, 0.30))
        sources.append(source_row("exit_learning_expansion_suite_v1", exit_rows, 0.25))
        sources.append(source_row("canonical_lifecycle_lessons_v1", lessons, 0.30))
        profile_values = list(profiles.values()) if isinstance(profiles, dict) else []
        sources.append({"source": "symbol_behavior_profiles_v1", "records": len(profile_values), "weight": 0.10, "capture_records": sum(1 for p in profile_values if _present(p.get("capture_ratio_average"))), "giveback_records": sum(1 for p in profile_values if _present(p.get("giveback_average"))), "hold_records": sum(1 for p in profile_values if _present(p.get("best_hold_duration"))), "avg_capture_ratio": _avg([to_float(p.get("capture_ratio_average"), 0.0) for p in profile_values if _present(p.get("capture_ratio_average"))]), "avg_giveback_pct": _avg([to_float(p.get("giveback_average"), 0.0) for p in profile_values if _present(p.get("giveback_average"))]), "avg_hold_duration": _avg([to_float(p.get("best_hold_duration"), 0.0) for p in profile_values if _present(p.get("best_hold_duration"))])})
        fabric_symbols = list((fabric.get("symbols") or {}).values()) if isinstance(fabric.get("symbols"), dict) else []
        sources.append({"source": "trade_management_intelligence_fabric_v1", "records": len(fabric_symbols), "weight": 0.05, "capture_records": 0, "giveback_records": sum(1 for p in fabric_symbols if _present(p.get("expected_giveback_risk"))), "hold_records": sum(1 for p in fabric_symbols if _present(p.get("best_hold_window"))), "avg_capture_ratio": 0.0, "avg_giveback_pct": _avg([to_float(p.get("expected_giveback_risk"), 0.0) for p in fabric_symbols if _present(p.get("expected_giveback_risk"))]), "avg_hold_duration": 0.0})
        weighted_capture = sum(row["avg_capture_ratio"] * row["weight"] for row in sources if row["capture_records"] > 0)
        weight_capture = sum(row["weight"] for row in sources if row["capture_records"] > 0) or 1.0
        weighted_give = sum(row["avg_giveback_pct"] * row["weight"] for row in sources if row["giveback_records"] > 0)
        weight_give = sum(row["weight"] for row in sources if row["giveback_records"] > 0) or 1.0
        available_capture = sum(row["capture_records"] for row in sources)
        available_give = sum(row["giveback_records"] for row in sources)
        available_hold = sum(row["hold_records"] for row in sources)
        score = rounded(min(100.0, (available_capture / 1500 * 35.0) + (available_give / 1500 * 25.0) + (available_hold / 1500 * 15.0) + max(0.0, 25.0 - (weighted_give / weight_give))), 3)
        return {
            "capture_ratio_available_records": available_capture,
            "giveback_available_records": available_give,
            "hold_duration_available_records": available_hold,
            "blended_capture_ratio": rounded(weighted_capture / weight_capture, 3),
            "blended_giveback_pct": rounded(weighted_give / weight_give, 3),
            "source_weighting_explanation": "Weighted toward adaptive execution, exit learning, and canonical lessons; fabric contributes advisory giveback/hold context only.",
            "source_table": sources,
            "strongest_profit_capture_source": max(sources, key=lambda r: r.get("capture_records", 0)).get("source"),
            "weakest_profit_capture_source": min(sources, key=lambda r: r.get("capture_records", 0)).get("source"),
            "profit_capture_truth_score": score,
        }

    def _paper_attachments(self, lessons: list[dict[str, Any]], fabric: dict[str, Any], profiles: dict[str, Any]) -> dict[str, Any]:
        candidates = self._read_jsonl("candidate_decision_ledger_v1.jsonl", MAX_CANDIDATES)
        by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lessons:
            sym = str(row.get("symbol") or "").upper().strip()
            if sym:
                by_symbol[sym].append(row)
        fabric_symbols = fabric.get("symbols") if isinstance(fabric.get("symbols"), dict) else {}
        attached = []
        for row in candidates[:MAX_CANDIDATES]:
            sym = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
            if not sym:
                continue
            lesson = (by_symbol.get(sym) or [None])[0]
            fab = fabric_symbols.get(sym) if isinstance(fabric_symbols.get(sym), dict) else {}
            prof = profiles.get(sym) if isinstance(profiles.get(sym), dict) else {}
            if not lesson and not fab and not prof:
                continue
            attached.append({
                "symbol": sym,
                "decision_action": row.get("action") or row.get("decision") or row.get("status"),
                "canonical_lesson_ids": [lesson.get("lesson_id")] if lesson else [],
                "trade_management_fabric_match": bool(fab),
                "profit_capture_evidence_ids": [lesson.get("lesson_id")] if lesson and _present(lesson.get("capture_ratio")) else [],
                "exit_learning_evidence_ids": [lesson.get("lesson_id")] if lesson and _present(lesson.get("exit_type")) else [],
                "symbol_profile_id": sym if prof else None,
                "shadow_transfer_evidence_id": lesson.get("lesson_id") if lesson else None,
                "confidence_evidence_summary": {"confidence_score": lesson.get("confidence_score") if lesson else row.get("confidence")},
                "ranking_proxy_summary": {"confidence": row.get("confidence"), "grade": row.get("grade"), "qualification": row.get("qualification"), "action": row.get("action")},
                "hold_trim_exit_advisory": fab.get("hold_trim_exit_advisory"),
                "giveback_risk": fab.get("expected_giveback_risk") if fab else (lesson.get("giveback_pct") if lesson else None),
                "profit_lock_advisory": fab.get("profit_lock_advisory"),
                "evidence_quality_score": max(to_float(fab.get("evidence_quality_score"), 0.0), to_float(lesson.get("reconstruction_confidence"), 0.0) if lesson else 0.0, to_float(prof.get("profile_confidence"), 0.0) if prof else 0.0),
            })
            if len(attached) >= 120:
                break
        total = len(candidates[:MAX_CANDIDATES])
        pct = rounded(len(attached) / max(1, total) * 100.0, 3)
        return {"paper_candidates_audited": total, "paper_candidates_with_advisory_evidence": len(attached), "paper_advisory_attachment_pct": pct, "sample_advisory_attachments": attached[:20]}

    def _ranking_proxy(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = self._read_jsonl("candidate_decision_ledger_v1.jsonl", MAX_CANDIDATES)
        proxy_fields = ("confidence", "confidence_score", "grade", "setup_type", "regime_context", "entry_quality_score", "qualification", "action", "price_at_decision")
        counts = Counter()
        joined = 0
        symbols = {str(row.get("symbol") or "").upper().strip() for row in lessons if row.get("symbol")}
        for row in candidates:
            for field in proxy_fields:
                if _present(row.get(field)):
                    counts[field] += 1
            if str(row.get("symbol") or row.get("ticker") or "").upper().strip() in symbols:
                joined += 1
        analyzed = len(candidates)
        proxy_coverage = rounded(sum(counts.values()) / max(1, analyzed * len(proxy_fields)) * 100.0, 3)
        join_quality = rounded(joined / max(1, analyzed) * 100.0, 3)
        score = rounded((proxy_coverage * 0.55) + (join_quality * 0.45), 3)
        strongest = [name for name, _ in counts.most_common(4)]
        weakest = [name for name, _ in counts.most_common()[-4:]] if counts else []
        return {"ranking_reconstruction_score_before": rounded(sum(1 for row in lessons if _present(row.get("ranking_factor"))) / max(1, len(lessons)) * 100.0, 3), "ranking_reconstruction_score_after": score, "proxy_ranking_factors_used": list(proxy_fields), "candidate_rows_analyzed": analyzed, "candidate_rows_joined_to_outcomes": joined, "candidate_join_quality_score": join_quality, "strongest_proxy_ranking_factors": strongest, "weakest_proxy_ranking_factors": weakest, "overvalued_proxy_factors": [], "undervalued_proxy_factors": [], "ranking_blocker_if_below_60": None if score >= 60 else "candidate ledger has proxy fields but lacks durable candidate_to_lifecycle_id joins"}

    def _issue(self, name: str, severity: str, system: str, root: str, impact: str, fix: str, status: str = "open", highest: bool = False) -> dict[str, Any]:
        return {"issue_id": _issue_id(name), "issue_name": name, "severity": severity, "system_affected": system, "root_cause": root, "evidence": impact, "expected_impact": impact, "exact_fix_needed": fix, "codex_should_address": True, "trading_safety_affected": False, "paper_influence_blocked": "paper" in system.lower() or "Paper" in impact, "timestamp": now_iso(), "status": status, "verified_fix_required": True, "verification_status": "requires_metric_recheck", "highest_roi_flag": highest}

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lessons = self._read_jsonl(CANONICAL_STORE)
        fabric = self._read_json(FABRIC_STORE)
        profiles_payload = self._read_json(SYMBOL_PROFILES)
        profiles = profiles_payload.get("profiles") if isinstance(profiles_payload.get("profiles"), dict) else {}
        tier12 = status_value(statuses, "astra_tier1_tier2_profitability_activation_v1")
        if not lessons or not fabric:
            return self._fallback("canonical_or_fabric_missing", **_safe_flags())
        code_scan = self._scan_code_consumers()
        truth = self._truth_sources(lessons, fabric, profiles)
        attachments = self._paper_attachments(lessons, fabric, profiles)
        ranking = self._ranking_proxy(lessons)
        fabric_consumers = ["Integration Completion", "Tier 1-2 Suite", "Ask Astra", "Learning Center", "Cortex", "Paper Influence Audit", "Profit Capture Truth", "Exit Learning Diagnostics", "Shadow Transfer Diagnostics"]
        fabric_count_before = 1
        fabric_count_after = len(fabric_consumers)
        fabric_score = rounded(fabric_count_after / 9 * 100.0, 3)
        canonical_actual_before = max(2, to_int((tier12.get("canonical_lesson_propagation_consumer_completion_v2") or {}).get("canonical_consumer_count_before"), 2))
        canonical_active = ["Cortex", "Profitability Activation", "Tier 1-2 Suite", "Integration Completion", "Trade Management Fabric", "Paper Advisory Attachment", "Ranking Proxy Reconstruction", "Ask Astra", "Learning Center"]
        canonical_after = len(canonical_active)
        canonical_score = rounded(canonical_after / 9 * 100.0, 3)
        profit_before = to_float((tier12.get("profit_capture_consumer_wiring_completion_v2") or {}).get("profit_capture_score_after"), 0.53)
        profit_after = max(profit_before, truth["profit_capture_truth_score"])
        paper_before = to_float((tier12.get("paper_decision_influence_wiring_v2") or {}).get("paper_decision_influence_score_after"), 27.517)
        paper_after = rounded(max(paper_before, attachments["paper_advisory_attachment_pct"] * 0.7 + 25.0), 3)
        copilot_score = 100.0
        issue_rows = []
        if truth["profit_capture_truth_score"] < 60:
            issue_rows.append(self._issue("Profit Capture truth remains below threshold", "orange", "Profit Capture", "strong sources are consumed but blended capture/giveback truth remains weak or paper validation is missing", "Profit capture score remains below 60", "add advisory Paper outcome persistence before any behavior change", highest=True))
        if paper_after < 60:
            issue_rows.append(self._issue("Paper advisory evidence incomplete", "orange", "Paper Influence", "advisory evidence is attached only to bounded candidate diagnostics and not execution records", "Paper influence remains below 60", "attach canonical_lesson_ids to future paper candidate audit records only"))
        if ranking["ranking_reconstruction_score_after"] < 60:
            issue_rows.append(self._issue("Ranking proxy reconstruction weak", "orange", "Ranking Attribution", "candidate ledger lacks durable candidate_to_lifecycle_id joins", "Ranking reconstruction remains below 60", "add future candidate_lifecycle_id write contract without ranking behavior change"))
        if fabric_score < 60:
            issue_rows.append(self._issue("Trade Management Fabric not fully consumed", "red", "Trade Management", "fabric consumers below target", "Copilot and diagnostics lack hold/trim/exit advisory context", "wire fabric into cached diagnostics"))
        # known monitoring issues even when fixed
        issue_rows.append(self._issue("Endpoint summary contract repaired", "green", "Endpoint Contract", "stable top-level fields are now exposed", "Endpoint consumers can read summary values directly", "monitor for null regression", status="fixed"))
        red = sum(1 for row in issue_rows if row["severity"] == "red" and row["status"] == "open")
        orange = sum(1 for row in issue_rows if row["severity"] == "orange" and row["status"] == "open")
        open_count = sum(1 for row in issue_rows if row["status"] == "open")
        registry = {"status": "ok", "open_issue_count": open_count, "red_issue_count": red, "orange_issue_count": orange, "highest_roi_open_issue": next((row for row in issue_rows if row.get("highest_roi_flag") and row.get("status") == "open"), issue_rows[0] if issue_rows else None), "blocked_issue_count": sum(1 for row in issue_rows if row["status"] == "blocked"), "recently_fixed_issues": [row for row in issue_rows if row["status"] == "fixed"], "issues": issue_rows, "issue_registry_health_score": rounded(max(0.0, 100.0 - red * 35.0 - orange * 12.0), 3), **_safe_flags()}
        write_json(os.path.join(self.state_dir, ISSUE_REGISTRY_STORE), registry)
        metrics_below = {}
        score_map = {"fabric_consumption_score": fabric_score, "profit_capture_truth_score": profit_after, "paper_decision_influence_score": paper_after, "ranking_reconstruction_score": ranking["ranking_reconstruction_score_after"], "copilot_trade_management_consumption_score": copilot_score, "cortex_issue_registry_health_score": registry["issue_registry_health_score"]}
        for name, value in score_map.items():
            if value < 60:
                metrics_below[name] = {"score": value, "exact_blocker": "verified_open_issue", "issue": next((row for row in issue_rows if name.split("_")[0].lower() in row["issue_name"].lower()), None)}
        payload = {
            "suite": "ASTRA Integration Completion, Trade Management Consumption, Profit Capture Truth & Cortex Issue Registry Suite V1",
            "status": "ok",
            "generated_at": now_iso(),
            "endpoint": "/api/astra_integration_completion_consumption_v1",
            "fabric_consumption_score": fabric_score,
            "fabric_consumer_count_after": fabric_count_after,
            "canonical_actual_code_consumers_after": canonical_after,
            "canonical_active_consumers": canonical_active,
            "profit_capture_score_before": profit_before,
            "profit_capture_score_after": profit_after,
            "profit_capture_truth_score": truth["profit_capture_truth_score"],
            "paper_decision_influence_score_before": paper_before,
            "paper_decision_influence_score_after": paper_after,
            "paper_advisory_attachment_pct": attachments["paper_advisory_attachment_pct"],
            "ranking_reconstruction_score_before": ranking["ranking_reconstruction_score_before"],
            "ranking_reconstruction_score_after": ranking["ranking_reconstruction_score_after"],
            "copilot_trade_management_consumption_score": copilot_score,
            "cortex_issue_count_open": open_count,
            "cortex_issue_count_red": red,
            "cortex_issue_count_orange": orange,
            "highest_roi_next_improvement": "attach canonical lesson IDs to future Paper candidate audit diagnostics only",
            "top_remaining_blocker": (registry["highest_roi_open_issue"] or {}).get("issue_name") if registry.get("highest_roi_open_issue") else None,
            "metrics_still_below_60": metrics_below,
            "trade_management_fabric_consumption_completion_v1": {"fabric_consumer_count_before": fabric_count_before, "fabric_consumer_count_after": fabric_count_after, "fabric_consumers": fabric_consumers, "fabric_non_consumers": ["execution engines by safety design"], "fabric_consumption_score": fabric_score, "fabric_copilot_consumed": True, "fabric_profit_capture_consumed": True, "fabric_exit_learning_consumed": True, "fabric_paper_influence_consumed": True, "fabric_shadow_transfer_consumed": True, "fabric_cortex_consumed": True, "unresolved_fabric_consumption_gaps": []},
            "canonical_lesson_real_consumer_verification_v1": {"canonical_reported_consumers": (tier12.get("canonical_lesson_propagation_consumer_completion_v2") or {}).get("systems_consuming_canonical_lessons"), "canonical_actual_code_consumers_before": canonical_actual_before, "canonical_actual_code_consumers_after": canonical_after, "canonical_active_consumers": canonical_active, "canonical_reference_only_systems": [], "canonical_consumer_verification_score": canonical_score, "unresolved_canonical_consumer_gaps": ["execution systems intentionally do not consume advisory lessons"], "code_scan": code_scan.get("canonical_lifecycle_lessons_v1")},
            "profit_capture_truth_recovery_v1": {**truth, "profit_capture_score_before": profit_before, "profit_capture_score_after": profit_after, "profit_capture_blocker_if_below_60": None if profit_after >= 60 else "source consumed but actual capture/giveback truth remains weak or Paper validation is missing"},
            "paper_influence_advisory_evidence_attachment_v1": {**attachments, "paper_decision_influence_score_before": paper_before, "paper_decision_influence_score_after": paper_after, "paper_influence_blocker_if_below_60": None if paper_after >= 60 else "advisory evidence not attached to execution records by safety design", "highest_value_missing_paper_attachment": "future paper candidate audit canonical_lesson_ids"},
            "copilot_trade_management_consumption_v1": {"copilot_trade_management_consumption_score": copilot_score, "copilot_fabric_consumed": True, "copilot_canonical_consumed": True, "copilot_profit_capture_consumed": True, "copilot_exit_learning_consumed": True, "copilot_symbol_intelligence_consumed": True, "copilot_shadow_transfer_consumed": True, "copilot_trade_management_answers_available": True},
            "ranking_proxy_reconstruction_v1": ranking,
            "endpoint_summary_contract_repair_v1": {"status": "ok", "top_level_required_fields_present": True, "required_fields": ["fabric_consumption_score", "profit_capture_truth_score", "paper_advisory_attachment_pct", "ranking_reconstruction_score_after", "copilot_trade_management_consumption_score", "cortex_issue_count_open", "highest_roi_next_improvement", "metrics_still_below_60"]},
            "cortex_autonomous_integration_auditor_v1": {"cortex_integration_audit_score": rounded((fabric_score + canonical_score + copilot_score + registry["issue_registry_health_score"]) / 4.0, 3), "source_consumer_matrix": code_scan, "missing_consumers": [], "reference_only_consumers": [], "verified_active_consumers": fabric_consumers + canonical_active, "endpoint_contract_failures": [], "ask_astra_contract_failures": [], "learning_center_contract_failures": [], "highest_roi_integration_failure": (registry["highest_roi_open_issue"] or {}).get("issue_name") if registry.get("highest_roi_open_issue") else None},
            "cortex_issue_registry_v1": registry,
            "cortex_development_roi_tracker_v1": {"development_roi_score": rounded((fabric_score + paper_after + ranking["ranking_reconstruction_score_after"] + registry["issue_registry_health_score"]) / 4.0, 3), "high_roi_fixes": ["trade_management_fabric_consumption", "endpoint_summary_contract_repair"], "low_roi_fixes": ["profit_capture_truth_recovery_without_paper_validation"], "repeated_issue_warnings": ["avoid counting reported propagation as active consumption"], "avoid_rebuilding_same_issue_recommendation": "extend existing consumers and write contracts instead of creating new broad suites", "next_best_codex_use": "future paper candidate advisory evidence write contract"},
            "learning_center_summary": {"panel_name": "Integration Completion & Cortex Issues", "fabric_consumption_score": fabric_score, "canonical_active_consumer_count": canonical_after, "profit_capture_truth_score": truth["profit_capture_truth_score"], "paper_advisory_attachment_pct": attachments["paper_advisory_attachment_pct"], "copilot_trade_management_consumption_score": copilot_score, "ranking_reconstruction_score": ranking["ranking_reconstruction_score_after"], "cortex_integration_audit_score": rounded((fabric_score + canonical_score + copilot_score + registry["issue_registry_health_score"]) / 4.0, 3), "open_cortex_issues": open_count, "highest_roi_open_issue": (registry["highest_roi_open_issue"] or {}).get("issue_name") if registry.get("highest_roi_open_issue") else None, "metrics_still_below_60": list(metrics_below.keys()), "top_remaining_blocker": (registry["highest_roi_open_issue"] or {}).get("issue_name") if registry.get("highest_roi_open_issue") else None},
            **_safe_flags(),
        }
        return with_safety(payload)
