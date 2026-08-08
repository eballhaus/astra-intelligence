from __future__ import annotations

import hashlib
import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

MAX_SOURCE_SYSTEMS = 80
MAX_LESSONS = 160
MAX_INDEX_VALUES = 40
MAX_INSIGHTS = 25

MASTER_CATEGORIES = [
    "Exit Intelligence",
    "Entry Intelligence",
    "Profit Capture",
    "Catalyst Intelligence",
    "Regime Intelligence",
    "Symbol Intelligence",
    "Portfolio Intelligence",
    "Execution Intelligence",
    "Risk Intelligence",
    "Infrastructure Intelligence",
    "Learning Intelligence",
]

CATEGORY_KEYWORDS = {
    "Exit Intelligence": ("exit", "sell", "hold", "follow", "capture", "giveback", "peak", "profit_lock"),
    "Entry Intelligence": ("entry", "buy", "promotion", "ranking", "candidate", "selection", "purity"),
    "Profit Capture": ("profit", "capture", "giveback", "mfe", "mae", "peak", "expectancy"),
    "Catalyst Intelligence": ("catalyst", "theme", "decay", "persistence", "news", "earnings"),
    "Regime Intelligence": ("regime", "market", "transition", "breadth", "volatility", "risk_on", "risk_off"),
    "Symbol Intelligence": ("symbol", "family", "sector", "peer", "watchlist"),
    "Portfolio Intelligence": ("portfolio", "capital", "capacity", "allocation", "concentration", "correlation"),
    "Execution Intelligence": ("execution", "paper", "broker", "alpaca", "session", "order"),
    "Risk Intelligence": ("risk", "safety", "governance", "rollback", "heat", "drawdown"),
    "Infrastructure Intelligence": ("health", "endpoint", "worker", "runtime", "storage", "memory", "api", "bandwidth"),
    "Learning Intelligence": ("learning", "evidence", "confidence", "replay", "shadow", "thesis", "drift", "quality"),
}

PRIORITY_SCORES = {
    "CRITICAL": 95.0,
    "HIGH": 80.0,
    "MEDIUM": 60.0,
    "LOW": 35.0,
    "IGNORE": 5.0,
}

LOW_VALUE_KEYS = {
    "enabled",
    "version",
    "mode",
    "generated_at",
    "build_ms",
    "api_calls_used",
    "provider_calls_used",
    "llm_calls_used",
    "behavior_safe_to_apply",
    "shadow_analysis_mode",
    "advisory_only",
    "paper_only_preserved",
    "alpaca_paper_only_preserved",
    "live_trading_changed",
    "broker_behavior_changed",
    "ranking_behavior_changed",
    "promotion_logic_changed",
    "entry_behavior_changed",
    "exit_behavior_changed",
    "position_sizing_changed",
    "portfolio_allocation_changed",
    "thresholds_changed",
    "paper_execution_changed",
}


def _safe_flags(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
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
        "sell_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_exits_enabled": False,
        "forced_trades_enabled": False,
        "partial_sells_enabled": False,
        "automatic_trailing_stops_enabled": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
    }
    out.update(extra or {})
    return out


def _slug(value: Any) -> str:
    raw = str(value or "unknown").strip().lower()
    out = []
    last_sep = False
    for char in raw:
        if char.isalnum():
            out.append(char)
            last_sep = False
        elif not last_sep:
            out.append("_")
            last_sep = True
    return "".join(out).strip("_") or "unknown"


def _lesson_id(source_system: str, category: str, summary: str) -> str:
    digest = hashlib.sha1(f"{source_system}|{category}|{summary}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"lesson_{digest}"


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _priority_from(confidence: float, evidence: int, negative: bool = False) -> str:
    score = clamp(confidence) + min(20.0, evidence / 10.0) + (10.0 if negative else 0.0)
    if score >= 95.0:
        return "CRITICAL"
    if score >= 78.0:
        return "HIGH"
    if score >= 52.0:
        return "MEDIUM"
    if score >= 20.0:
        return "LOW"
    return "IGNORE"


def _category_for(key: str, value: Any = None) -> str:
    haystack = f"{key} {value}".lower()
    best = "Learning Intelligence"
    best_hits = -1
    for category, words in CATEGORY_KEYWORDS.items():
        hits = sum(1 for word in words if word in haystack)
        if hits > best_hits:
            best = category
            best_hits = hits
    return best


def _confidence_from_payload(payload: dict[str, Any]) -> float:
    candidates = [
        payload.get("confidence_score"),
        payload.get("confidence"),
        payload.get("readiness_score"),
        payload.get("validation_confidence"),
        payload.get("ranking_confidence_score"),
        payload.get("shadow_alpha_confidence"),
        payload.get("catalyst_lifecycle_confidence"),
        payload.get("sector_flow_confidence"),
    ]
    nums = [clamp(v) for v in candidates if v is not None]
    if nums:
        return rounded(sum(nums) / len(nums), 3)
    status = str(payload.get("status") or "").lower()
    if status == "ok":
        return 62.0
    if status == "healthy":
        return 70.0
    if status in {"warning", "degraded"}:
        return 45.0
    return 35.0


def _evidence_from_payload(payload: dict[str, Any]) -> int:
    keys = (
        "evidence_count",
        "closed_trade_count",
        "canonical_closed_trade_count",
        "validation_count",
        "lesson_count",
        "recommendation_count",
        "shadow_opportunities",
        "candidate_count",
        "tournament_count",
        "exit_tournament_count",
    )
    return max([to_int(payload.get(key), 0) for key in keys] + [0])


def _is_negative_signal(key: str, value: Any) -> bool:
    haystack = f"{key} {value}".lower()
    return any(word in haystack for word in ("weak", "fail", "blocked", "risk", "degraded", "giveback", "loss", "drift", "warning", "unknown", "insufficient"))


def _summary_from(key: str, value: Any) -> str:
    label = str(key or "finding").replace("_", " ").strip()
    if isinstance(value, bool):
        return f"{label}: {'yes' if value else 'no'}"
    if isinstance(value, (int, float)):
        return f"{label}: {rounded(value, 3)}"
    if isinstance(value, str):
        return f"{label}: {value[:140]}"
    if isinstance(value, dict):
        status = first(value.get("status"), value.get("summary"), value.get("recommended_focus"), default="structured finding")
        return f"{label}: {text(status)[:140]}"
    if isinstance(value, list):
        return f"{label}: {len(value)} item(s)"
    return f"{label}: observed"


class AstraTier2aLibrarianExecutiveTruthLayerV1(CachedDiagnosticModule):
    """Institutional organization layer for existing Astra intelligence.

    This module only compresses and indexes already-produced diagnostics. It does
    not create trading signals, alter ranking, influence paper execution, or call
    providers. The dashboard cache produced by CachedDiagnosticModule is the only
    persistence used for retrieval indexes.
    """

    module_name = "astra_tier2a_librarian_executive_truth_layer_v1"
    mode = "shadow_only_intelligence_organization"

    def _source_systems(self, statuses: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        systems: list[tuple[str, dict[str, Any]]] = []
        for name, payload in (statuses or {}).items():
            if not isinstance(payload, dict) or name == self.module_name:
                continue
            if name.startswith("_"):
                continue
            systems.append((name, dict(payload)))
        systems.sort(key=lambda item: (_evidence_from_payload(item[1]), _confidence_from_payload(item[1])), reverse=True)
        return systems[:MAX_SOURCE_SYSTEMS]

    def _build_lessons(self, systems: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        lessons: dict[str, dict[str, Any]] = {}
        for source_system, payload in systems:
            source_confidence = _confidence_from_payload(payload)
            source_evidence = _evidence_from_payload(payload)
            keys = [key for key in payload.keys() if key not in LOW_VALUE_KEYS]
            priority_keys = [
                key for key in keys
                if any(word in key.lower() for word in (
                    "weak", "strong", "risk", "quality", "confidence", "evidence", "focus", "blocker", "leak",
                    "capture", "giveback", "ranking", "promotion", "exit", "entry", "catalyst", "regime",
                    "portfolio", "health", "status", "truth", "readiness", "opportunity", "shadow", "paper",
                ))
            ]
            selected_keys = (priority_keys or keys)[:8]
            for key in selected_keys:
                value = payload.get(key)
                if value in (None, ""):
                    continue
                summary = _summary_from(key, value)
                category = _category_for(key, value)
                confidence = source_confidence
                if _is_negative_signal(key, value):
                    confidence = max(confidence, 68.0 if source_evidence else confidence)
                lesson = {
                    "lesson_id": _lesson_id(source_system, category, summary),
                    "source_system": source_system,
                    "category": category,
                    "confidence": rounded(confidence, 3),
                    "evidence_count": source_evidence,
                    "timestamp": now_iso(),
                    "priority": _priority_from(confidence, source_evidence, negative=_is_negative_signal(key, value)),
                    "retrieval_tags": sorted(set([
                        _slug(source_system),
                        _slug(category),
                        _slug(key),
                        *[_slug(token) for token in str(value).replace("/", " ").replace(",", " ").split()[:6]],
                    ]))[:12],
                    "compressed_summary": summary,
                }
                existing = lessons.get(lesson["lesson_id"])
                if not existing or lesson["confidence"] + lesson["evidence_count"] > existing["confidence"] + existing["evidence_count"]:
                    lessons[lesson["lesson_id"]] = lesson
        rows = list(lessons.values())
        rows.sort(key=lambda row: (PRIORITY_SCORES.get(row["priority"], 0.0), row["confidence"], row["evidence_count"]), reverse=True)
        return rows[:MAX_LESSONS]

    def _librarian(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        indexes: dict[str, dict[str, list[str]]] = {
            "symbol": {},
            "catalyst": {},
            "sector": {},
            "regime": {},
            "horizon": {},
            "trade_family": {},
            "issue": {},
            "priority": {},
            "confidence": {},
            "theme": {},
        }
        buckets = {
            "symbol": ("symbol", "ticker", "nvda", "qbts", "rgti", "ionq", "spy", "qqq", "btc"),
            "catalyst": ("catalyst", "theme", "earnings", "ai", "quantum", "crypto", "news"),
            "sector": ("sector", "technology", "energy", "healthcare", "financial", "industrial"),
            "regime": ("regime", "market", "risk", "volatility", "breadth", "transition"),
            "horizon": ("horizon", "scalp", "day", "swing", "intraday", "hold"),
            "trade_family": ("family", "archetype", "setup", "meme", "semiconductor", "biotech"),
            "issue": ("issue", "weak", "blocker", "leak", "risk", "quality", "capture", "exit"),
            "theme": ("theme", "ai", "quantum", "crypto", "rotation", "momentum"),
        }
        for lesson in lessons:
            lesson_id = text(lesson.get("lesson_id"))
            tags = [str(tag) for tag in lesson.get("retrieval_tags") or []]
            summary = str(lesson.get("compressed_summary") or "").lower()
            for index_name, words in buckets.items():
                matched = [tag for tag in tags if any(word in tag for word in words)]
                if not matched and any(word in summary for word in words):
                    matched = [_slug(lesson.get("category"))]
                for tag in matched[:4]:
                    indexes[index_name].setdefault(tag, [])
                    if lesson_id not in indexes[index_name][tag]:
                        indexes[index_name][tag].append(lesson_id)
            indexes["priority"].setdefault(str(lesson.get("priority") or "LOW"), []).append(lesson_id)
            confidence_bucket = "high" if to_float(lesson.get("confidence"), 0.0) >= 70 else "medium" if to_float(lesson.get("confidence"), 0.0) >= 45 else "low"
            indexes["confidence"].setdefault(confidence_bucket, []).append(lesson_id)
        compact_indexes = {
            name: {tag: ids[:12] for tag, ids in sorted(values.items())[:MAX_INDEX_VALUES]}
            for name, values in indexes.items()
        }
        categories: dict[str, int] = {}
        for lesson in lessons:
            categories[str(lesson.get("category") or "Learning Intelligence")] = categories.get(str(lesson.get("category") or "Learning Intelligence"), 0) + 1
        return {
            "system": "Astra Librarian V1",
            "status": "ok" if lessons else "insufficient_evidence",
            "lessons_organized": len(lessons),
            "compressed_lessons_only": True,
            "never_duplicate_lessons": True,
            "similar_lessons_merged": True,
            "categories": categories,
            "retrieval_indexes_created": True,
            "retrieval_indexes": compact_indexes,
            "cache_first_retrieval": True,
            **_safe_flags(),
        }

    def _truth_layer(self, lessons: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {category: [] for category in MASTER_CATEGORIES}
        for lesson in lessons:
            grouped.setdefault(str(lesson.get("category") or "Learning Intelligence"), []).append(lesson)
        master_issues = []
        duplicate_reduction = 0
        for category, rows in grouped.items():
            if not rows:
                continue
            source_systems = sorted({str(row.get("source_system")) for row in rows})
            confidence = rounded(sum(to_float(row.get("confidence"), 0.0) for row in rows) / max(1, len(rows)) + min(10.0, len(source_systems) * 1.5), 3)
            evidence = sum(to_int(row.get("evidence_count"), 0) for row in rows)
            high_priority = max(rows, key=lambda row: (PRIORITY_SCORES.get(str(row.get("priority")), 0.0), to_float(row.get("confidence"), 0.0)))
            priority = _priority_from(confidence, evidence, negative=True)
            issue = {
                "issue": category,
                "confidence": clamp(confidence),
                "evidence_sources": len(source_systems),
                "systems_contributing": source_systems[:12],
                "priority": priority,
                "recommended_focus": text(high_priority.get("compressed_summary"), f"Review {category.lower()}"),
                "lesson_count": len(rows),
            }
            master_issues.append(issue)
            duplicate_reduction += max(0, len(rows) - 1)
        master_issues.sort(key=lambda row: (PRIORITY_SCORES.get(str(row.get("priority")), 0.0), to_float(row.get("confidence"), 0.0), to_int(row.get("evidence_sources"), 0)), reverse=True)
        return {
            "system": "Unified Truth Layer V1",
            "status": "ok" if master_issues else "insufficient_evidence",
            "master_truths_created": len(master_issues),
            "duplicate_findings_reduced": duplicate_reduction,
            "master_issues": master_issues[:15],
            "strongest_master_truth": first((master_issues[0] if master_issues else {}).get("issue"), "insufficient_evidence"),
            "unified_truth_status": "active" if master_issues else "insufficient_evidence",
            **_safe_flags(),
        }

    def _executive_assistant(self, master: dict[str, Any], lessons: list[dict[str, Any]]) -> dict[str, Any]:
        insights = []
        for issue in _as_list(master.get("master_issues")):
            insights.append({
                "issue": text(issue.get("issue")),
                "confidence": rounded(issue.get("confidence"), 3),
                "evidence": to_int(issue.get("evidence_sources"), 0),
                "priority": text(issue.get("priority"), "MEDIUM"),
                "recommended_focus": text(issue.get("recommended_focus")),
            })
        if not insights:
            for lesson in lessons[:MAX_INSIGHTS]:
                insights.append({
                    "issue": text(lesson.get("category")),
                    "confidence": rounded(lesson.get("confidence"), 3),
                    "evidence": to_int(lesson.get("evidence_count"), 0),
                    "priority": text(lesson.get("priority"), "LOW"),
                    "recommended_focus": text(lesson.get("compressed_summary")),
                })
        insights.sort(key=lambda row: (PRIORITY_SCORES.get(str(row.get("priority")), 0.0), to_float(row.get("confidence"), 0.0), to_int(row.get("evidence"), 0)), reverse=True)
        actionable = [row for row in insights if row.get("priority") != "IGNORE"][:MAX_INSIGHTS]
        suppressed_low_value = max(0, len(lessons) - len(actionable))
        return {
            "system": "Executive Assistant / Orchestrator V1",
            "status": "ok" if actionable else "insufficient_evidence",
            "top_5": actionable[:5],
            "top_10": actionable[:10],
            "top_25": actionable[:25],
            "actionable_insights": actionable[:25],
            "suppressed_duplicates": to_int(master.get("duplicate_findings_reduced"), 0),
            "suppressed_low_value_findings": suppressed_low_value,
            "suppressed_low_confidence_conflicts": len([row for row in lessons if to_float(row.get("confidence"), 0.0) < 35.0]),
            "executive_assistant_status": "active" if actionable else "insufficient_evidence",
            **_safe_flags(),
        }

    def _compression(self, lessons: list[dict[str, Any]], master: dict[str, Any], executive: dict[str, Any]) -> dict[str, Any]:
        return {
            "system": "Knowledge Compression Engine V1",
            "status": "ok" if lessons else "insufficient_evidence",
            "compression_status": "active" if lessons else "insufficient_evidence",
            "raw_intelligence_sources": len({str(row.get("source_system")) for row in lessons}),
            "lessons": len(lessons),
            "patterns": len(set(str(row.get("category")) for row in lessons)),
            "master_truths": to_int(master.get("master_truths_created"), 0),
            "actionable_insights": len(_as_list(executive.get("actionable_insights"))),
            "preserve_evidence_references": True,
            "never_delete_source_evidence": True,
            **_safe_flags(),
        }

    def _tier1_integration(self) -> dict[str, Any]:
        systems = [
            ("Astra Librarian V1", "Knowledge Architecture", "Compressed lesson organization and retrieval indexes"),
            ("Executive Assistant / Orchestrator V1", "Knowledge Architecture", "Insight priority, dedupe and executive focus"),
            ("Unified Truth Layer V1", "Knowledge Architecture", "Master issue consolidation across systems"),
            ("Knowledge Compression Engine V1", "Knowledge Architecture", "Raw intelligence to lessons to master truths"),
            ("Retrieval Engine Integration V1", "Knowledge Architecture", "Cache-first indexes by symbol, catalyst, sector, regime and priority"),
        ]
        return {
            "system": "Tier 1 Integration",
            "status": "registered",
            "integrates_with": [
                "astra_system_registry_v1",
                "astra_knowledge_preservation_framework_v1",
                "astra_operations_department_v1",
                "astra_resource_manager_v1",
                "astra_internal_audit_department_v1",
                "api_governor",
            ],
            "registered_systems": [
                {
                    "system_name": name,
                    "owner": owner,
                    "purpose": purpose,
                    "inputs": ["cached_unified_diagnostics", "cached_learning_system_statuses"],
                    "outputs": ["compressed_lessons", "master_truths", "executive_insights", "retrieval_indexes"],
                    "dependencies": ["astra_foundation_stabilization_governance_bundle_v1", "unified_learning_diagnostics_v1"],
                    "health_status": "registered",
                    "enabled": True,
                    "api_budget": 0,
                    "bandwidth_budget": 0,
                }
                for name, owner, purpose in systems
            ],
            **_safe_flags(),
        }

    def _shadow_lab_integration(self) -> dict[str, Any]:
        return {
            "system": "Shadow Lab Integration",
            "status": "shadow_only",
            "observe": True,
            "validate": True,
            "compare": True,
            "stress_test": True,
            "approve": False,
            "promote": False,
            "human_review_required": True,
            "policy_promotion_enabled": False,
            "trade_influence_enabled": False,
            "ranking_influence_enabled": False,
            "broker_influence_enabled": False,
            "paper_execution_influence_enabled": False,
            **_safe_flags(),
        }

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        systems = self._source_systems(statuses)
        lessons = self._build_lessons(systems)
        librarian = self._librarian(lessons)
        truth = self._truth_layer(lessons)
        executive = self._executive_assistant(truth, lessons)
        compression = self._compression(lessons, truth, executive)
        tier1 = self._tier1_integration()
        shadow = self._shadow_lab_integration()
        top_focus = first((executive.get("top_5") or [{}])[0].get("recommended_focus") if executive.get("top_5") else None, "continue_cache_first_intelligence_organization")
        out = {
            "enabled": True,
            "version": VERSION,
            "suite": "ASTRA Tier 2A - Librarian, Executive Assistant & Unified Truth Layer V1",
            "status": "ok" if lessons else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "source_systems_reviewed": len(systems),
            "astra_librarian_v1": librarian,
            "executive_assistant_orchestrator_v1": executive,
            "unified_truth_layer_v1": truth,
            "knowledge_compression_engine_v1": compression,
            "retrieval_engine_integration_v1": {
                "system": "Retrieval Engine Integration V1",
                "status": "active" if librarian.get("retrieval_indexes_created") else "insufficient_evidence",
                "index_count": len(_as_dict(librarian.get("retrieval_indexes"))),
                "indexes": librarian.get("retrieval_indexes"),
                "fast_retrieval_only": True,
                "full_history_scans": False,
                "cache_first": True,
                **_safe_flags(),
            },
            "tier1_integration": tier1,
            "shadow_lab_integration": shadow,
            "lessons_organized": librarian.get("lessons_organized", 0),
            "duplicate_findings_reduced": truth.get("duplicate_findings_reduced", 0),
            "master_truths_created": truth.get("master_truths_created", 0),
            "retrieval_indexes_created": librarian.get("retrieval_indexes_created", False),
            "compression_status": compression.get("compression_status"),
            "executive_assistant_status": executive.get("executive_assistant_status"),
            "unified_truth_status": truth.get("unified_truth_status"),
            "top_5_insights": executive.get("top_5", []),
            "top_10_insights": executive.get("top_10", []),
            "top_25_insights": executive.get("top_25", []),
            "strongest_master_truth": truth.get("strongest_master_truth"),
            "recommended_next_focus": top_focus,
            "dashboard_provider_calls_used": 0,
            "dashboard_api_calls_added": 0,
            "dashboard_endpoint_storm_created": False,
            "dashboard_performance_impact": "single_unified_diagnostics_panel_cache_first",
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
            **_safe_flags(),
        }
        return with_safety(out)


def compress_historical_packet_handoffs_v1(packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Use the canonical Librarian compression contract for V10 packet handoffs.

    This is deliberately pure: it returns a handoff preview and never writes a
    cache, lesson registry, or authoritative truth.
    """
    compact = [dict(packet) for packet in packets[:MAX_LESSONS] if isinstance(packet, dict)]
    payload = {
        "historical_packet_handoffs": compact,
        "evidence_count": sum(to_int(item.get("raw_equivalent_count"), 0) for item in compact),
        "compression_status": "v10_handoff_preview",
        "source_packet_ids": [item.get("packet_id") for item in compact if item.get("packet_id")],
    }
    lessons = AstraTier2aLibrarianExecutiveTruthLayerV1()._build_lessons([
        ("astra_incremental_historical_learning_governor_v1", payload),
    ])
    return {
        "owner": "Knowledge Compression Engine V1",
        "status": "READY_FOR_TEACHER" if lessons else "INSUFFICIENT_EVIDENCE",
        "compressed_lessons": lessons,
        "source_packet_ids": payload["source_packet_ids"],
        "deduplication_owner": "Astra Librarian V1",
        "persisted": False,
        "full_history_scan_count": 0,
        **_safe_flags(),
    }
