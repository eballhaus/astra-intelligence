"""Bounded, lineage-first reconstruction of historical paper lifecycles.

Reconstruction produces diagnostic evidence only.  It never writes into the
authoritative broker-truth, paper-execution, lifecycle, or performance stores,
and reconstructed records are deliberately kept distinct from broker-confirmed
round trips.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract, safety_fields

try:
    from engine.intelligence_quality_common_v1 import (
        CachedDiagnosticModule,
        tail_jsonl,
    )
except Exception:  # pragma: no cover - defensive import path for isolated tests
    CachedDiagnosticModule = object  # type: ignore

    def tail_jsonl(_path: str, max_rows: int = 100, max_bytes: int = 1_000_000) -> List[Dict[str, Any]]:
        return []


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PROJECT_ROOT / "state" / "long_term_memory" / "pladeu_historical_lifecycle_reconstruction_v1.json"
MAX_ROWS_PER_SOURCE = 250
MAX_BYTES_PER_SOURCE = 1_000_000
IDENTIFIER_FIELDS = (
    "lifecycle_id",
    "broker_order_id",
    "client_order_id",
    "recommendation_id",
    "candidate_id",
    "decision_id",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    os.replace(temporary, path)


def _first(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(record.get(key))
        if value:
            return value
    return ""


def _timestamp(record: Mapping[str, Any]) -> str:
    return _first(record, "exit_timestamp", "closed_at", "updated_at", "timestamp", "created_at")


def _strong_keys(record: Mapping[str, Any]) -> List[str]:
    keys: List[str] = []
    for field in IDENTIFIER_FIELDS:
        value = _text(record.get(field))
        if value:
            keys.append(f"{field}:{value}")
    return keys


def _source_name(record: Mapping[str, Any], fallback: str) -> str:
    return _text(record.get("_pladeu_source")) or fallback


def _outcome_present(record: Mapping[str, Any]) -> bool:
    return any(
        record.get(key) not in (None, "")
        for key in ("realized_pnl", "return_pct", "outcome", "exit_price", "closed_at", "exit_timestamp")
    )


def _broker_truth_complete(records: Sequence[Mapping[str, Any]]) -> bool:
    truth_labels = {
        "broker_confirmed_complete",
        "broker_truth_complete",
        "broker_confirmed",
    }
    return any(
        _text(item.get("evidence_class")).lower() in truth_labels
        or bool(item.get("broker_fill_confirmed"))
        or bool(item.get("broker_round_trip_confirmed"))
        for item in records
    )


def _compatible(records: Sequence[Mapping[str, Any]]) -> Tuple[bool, str]:
    symbols = {_text(item.get("symbol")).upper() for item in records if _text(item.get("symbol"))}
    assets = {_text(item.get("asset_class")).lower() for item in records if _text(item.get("asset_class"))}
    quantities = {
        _text(item.get("quantity") or item.get("qty"))
        for item in records
        if _text(item.get("quantity") or item.get("qty"))
    }
    if len(symbols) > 1:
        return False, "symbol_conflict"
    if len(assets) > 1:
        return False, "asset_class_conflict"
    if len(quantities) > 1:
        return False, "quantity_conflict"
    lanes = {_text(item.get("lane_id")).upper() for item in records if _text(item.get("lane_id"))}
    if len(lanes) > 1:
        return False, "lane_conflict"
    for item in records:
        entry = _text(item.get("entry_timestamp") or item.get("opened_at"))
        exit_time = _text(item.get("exit_timestamp") or item.get("closed_at"))
        if entry and exit_time and exit_time < entry:
            return False, "timestamp_conflict_exit_before_entry"
    return True, ""


def _confidence(records: Sequence[Mapping[str, Any]], evidence_class: str) -> int:
    if evidence_class == "BROKER_CONFIRMED_COMPLETE":
        return 100
    identifiers = len({key for record in records for key in _strong_keys(record)})
    source_count = len({_source_name(record, "unknown") for record in records})
    has_outcome = any(_outcome_present(record) for record in records)
    score = 35 + min(30, identifiers * 10) + min(20, source_count * 8) + (15 if has_outcome else 0)
    return min(95, score)


def _classify(records: Sequence[Mapping[str, Any]]) -> Tuple[str, str]:
    compatible, reason = _compatible(records)
    if not compatible:
        return "AMBIGUOUS_REJECTED", reason
    if not records:
        return "AMBIGUOUS_REJECTED", "empty_group"
    sources = " ".join(_source_name(item, "").lower() for item in records)
    stages = " ".join(_text(item.get("lifecycle_stage")).lower() for item in records)
    if any(bool(item.get("incomplete_invalid")) for item in records):
        return "INCOMPLETE_INVALID", "source_marked_invalid"
    if "replay" in sources:
        return "REPLAY_COUNTERFACTUAL", "replay_source_linked"
    if "shadow" in sources:
        return (
            "PAPER_SHADOW_TWIN" if any(_strong_keys(item) for item in records if "paper" in _source_name(item, "").lower())
            else "SHADOW_ONLY",
            "shadow_source_linked",
        )
    if any(bool(item.get("eligible_but_untraded")) for item in records):
        return "ELIGIBLE_BUT_UNTRADED", "eligible_without_submission"
    if any(bool(item.get("advisory_only")) for item in records):
        return "ADVISORY_ONLY", "advisory_context_only"
    if "open" in stages or "active" in stages:
        return "ACTIVE_PAPER_CHECKPOINT", "active_lifecycle_checkpoint"
    if _broker_truth_complete(records) and any(_outcome_present(item) for item in records):
        return "BROKER_CONFIRMED_COMPLETE", "broker_confirmed_round_trip"
    if _broker_truth_complete(records):
        return "BROKER_CONFIRMED_PARTIAL", "broker_fill_without_complete_exit"
    identifiers = {key for record in records for key in _strong_keys(record)}
    has_outcome = any(_outcome_present(item) for item in records)
    source_count = len({_source_name(record, "unknown") for record in records})
    if identifiers and has_outcome and source_count >= 2:
        return "HIGH_CONFIDENCE_RECONSTRUCTED", "linked_identifier_with_outcome"
    if identifiers and has_outcome:
        return "MEDIUM_CONFIDENCE_RECONSTRUCTED", "single_source_identifier_with_outcome"
    if identifiers:
        return "PARTIAL_LIFECYCLE", "identifier_without_completed_outcome"
    return "AMBIGUOUS_REJECTED", "no_stable_identifier"


def _compact_record(records: Sequence[Mapping[str, Any]], evidence_class: str, reason: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for record in records:
        for key, value in record.items():
            if key.startswith("_") or key in merged or value in (None, ""):
                continue
            merged[key] = value
    merged = apply_trade_lane_contract(merged, legacy=True)
    lineage = [
        {
            "source": _source_name(record, "unknown"),
            "identifiers": _strong_keys(record),
            "timestamp": _timestamp(record),
        }
        for record in records
    ]
    unique_sources = len({_source_name(record, "unknown") for record in records})
    return {
        "reconstruction_id": "|".join(sorted({key for record in records for key in _strong_keys(record)}))
        or f"ambiguous:{merged.get('symbol') or 'unknown'}",
        "symbol": _text(merged.get("symbol")).upper(),
        "asset_class": merged.get("asset_class"),
        "lane_id": merged.get("lane_id"),
        "strategy_cohort": merged.get("strategy_cohort"),
        "evidence_class": evidence_class,
        "reconstruction_reason": reason,
        "confidence": _confidence(records, evidence_class),
        "confidence_rationale": {
            "stable_identifiers": len({key for record in records for key in _strong_keys(record)}),
            "source_count": unique_sources,
            "source_rows": len(lineage),
            "outcome_complete": any(_outcome_present(item) for item in records),
            "symbol_only_matching_disabled": True,
            "class_reason": reason,
        },
        "lineage": lineage,
        "source_count": unique_sources,
        "source_rows": len(lineage),
        "outcome_present": any(_outcome_present(item) for item in records),
        "broker_truth_eligible": evidence_class == "BROKER_CONFIRMED_COMPLETE",
        "official_performance_eligible": evidence_class == "BROKER_CONFIRMED_COMPLETE",
        "reconstructed_at": datetime.now(timezone.utc).isoformat(),
    }


def reconstruct_lifecycles(sources: Mapping[str, Iterable[Mapping[str, Any]]]) -> Dict[str, Any]:
    """Reconstruct only records connected through stable identifiers.

    Symbol-only joins are intentionally rejected.  The returned compact records
    are diagnostic evidence, never a replacement for broker truth.
    """

    groups: MutableMapping[str, List[Dict[str, Any]]] = defaultdict(list)
    rejected: List[Dict[str, Any]] = []
    rows_read: Dict[str, int] = {}
    for source, rows in sources.items():
        capped_rows = list(rows or [])[-MAX_ROWS_PER_SOURCE:]
        rows_read[source] = len(capped_rows)
        for raw in capped_rows:
            record = dict(raw or {})
            record["_pladeu_source"] = source
            keys = _strong_keys(record)
            if not keys:
                rejected.append(
                    _compact_record([record], "AMBIGUOUS_REJECTED", "no_stable_identifier")
                )
                continue
            # Multiple keys point at the same shared group; the first key gives
            # deterministic grouping without a symbol-only fallback.
            groups[sorted(keys)[0]].append(record)

    reconstructed: List[Dict[str, Any]] = []
    for records in groups.values():
        evidence_class, reason = _classify(records)
        compact = _compact_record(records, evidence_class, reason)
        if evidence_class == "AMBIGUOUS_REJECTED":
            rejected.append(compact)
        else:
            reconstructed.append(compact)

    classes = Counter(item["evidence_class"] for item in reconstructed + rejected)
    accepted = [
        item
        for item in reconstructed
        if item["evidence_class"]
        not in {"PARTIAL_LIFECYCLE", "ACTIVE_PAPER_CHECKPOINT", "ADVISORY_ONLY", "ELIGIBLE_BUT_UNTRADED"}
    ]
    linked = [item for item in reconstructed if item["evidence_class"] != "AMBIGUOUS_REJECTED"]
    lane_mismatches = sum(1 for item in rejected if item.get("reconstruction_reason") == "lane_conflict")
    asset_mismatches = sum(1 for item in rejected if item.get("reconstruction_reason") == "asset_class_conflict")
    timestamp_conflicts = sum(1 for item in rejected if "timestamp_conflict" in str(item.get("reconstruction_reason") or ""))
    return {
        "status": "ok",
        "rows_read": rows_read,
        "reconstructed_records": reconstructed,
        "accepted_records": accepted,
        "rejected_records": rejected,
        "evidence_class_counts": dict(classes),
        "broker_confirmed_complete_count": classes.get("BROKER_CONFIRMED_COMPLETE", 0),
        "records_inspected": sum(rows_read.values()),
        "records_linked": len(linked),
        "complete_reconstructed_lifecycles": sum(
            1 for item in reconstructed if item["evidence_class"] in {"HIGH_CONFIDENCE_RECONSTRUCTED", "MEDIUM_CONFIDENCE_RECONSTRUCTED"}
        ),
        "reconstructed_evidence_count": sum(
            classes.get(key, 0)
            for key in ("HIGH_CONFIDENCE_RECONSTRUCTED", "MEDIUM_CONFIDENCE_RECONSTRUCTED")
        ),
        "partial_lifecycle_count": classes.get("PARTIAL_LIFECYCLE", 0),
        "active_checkpoint_count": classes.get("ACTIVE_PAPER_CHECKPOINT", 0),
        "ambiguous_rejected_count": classes.get("AMBIGUOUS_REJECTED", 0),
        "duplicate_linkage_attempts": 0,
        "orphan_recommendations": 0,
        "orphan_orders": 0,
        "orphan_fills": 0,
        "orphan_exits": 0,
        "lane_mismatches": lane_mismatches,
        "asset_class_mismatches": asset_mismatches,
        "timestamp_conflicts": timestamp_conflicts,
        "reconstruction_confidence_distribution": dict(Counter(str(item.get("confidence")) for item in reconstructed)),
        "source_coverage": {key: bool(value) for key, value in rows_read.items()},
        "symbol_only_matching_disabled": True,
        "full_history_scans": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
    }


class AstraHistoricalLifecycleReconstructionV1(CachedDiagnosticModule):
    module_name = "astra_historical_lifecycle_reconstruction_v1"

    def __init__(self, state_dir: str = "state", *args: Any, **kwargs: Any) -> None:
        super().__init__(state_dir=state_dir, *args, **kwargs)
        self.reconstruction_state_path = Path(self.state_dir) / "long_term_memory" / "pladeu_historical_lifecycle_reconstruction_v1.json"

    def _source_rows(self, statuses: Mapping[str, Any]) -> Dict[str, List[Mapping[str, Any]]]:
        supplied = statuses.get("pladeu_reconstruction_sources")
        if isinstance(supplied, Mapping):
            return {str(key): list(value or [])[-MAX_ROWS_PER_SOURCE:] for key, value in supplied.items()}
        paths = {
            "candidate_decisions": PROJECT_ROOT / "state" / "candidate_decision_ledger_v1.jsonl",
            "trade_lifecycle": PROJECT_ROOT / "state" / "trade_lifecycle_v1.jsonl",
            "outcomes": PROJECT_ROOT / "state" / "outcome_labels_v1.jsonl",
        }
        return {
            name: tail_jsonl(str(path), max_rows=MAX_ROWS_PER_SOURCE, max_bytes=MAX_BYTES_PER_SOURCE)
            for name, path in paths.items()
        }

    def _build(self, statuses: Mapping[str, Any] | None = None) -> Dict[str, Any]:
        statuses = statuses or {}
        result = reconstruct_lifecycles(self._source_rows(statuses))
        authoritative = statuses.get("authoritative_broker_truth")
        if not isinstance(authoritative, Mapping):
            authoritative = {}
        authoritative_count = int(authoritative.get("broker_confirmed_complete_records") or 0)
        # Reconstruction is deliberately scoped to bounded local lifecycle rows;
        # it must never masquerade as the platform-wide broker-truth registry.
        result["authoritative_broker_confirmed_complete_count"] = authoritative_count
        result["newly_reconstructed_complete_count"] = int(result.get("complete_reconstructed_lifecycles") or 0)
        result["reconstructed_partial_count"] = int(result.get("partial_lifecycle_count") or 0) + int(result.get("evidence_class_counts", {}).get("BROKER_CONFIRMED_PARTIAL", 0) or 0)
        result["authoritative_truth_source"] = str(
            authoritative.get("truth_registry_path") or "state/broker_truth_records_v1.json"
        )
        result["reconstruction_scope"] = "bounded_local_lifecycle_sources_only"
        previous = _read_json(self.reconstruction_state_path)
        watermark = max(
            [entry.get("reconstructed_at", "") for entry in result["reconstructed_records"]] or [""],
        )
        manifest = {
            "watermark": watermark,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "record_count": len(result["reconstructed_records"]),
            "previous_watermark": previous.get("watermark", ""),
            "accepted_records": result["accepted_records"],
            "partial_records": [
                item for item in result["reconstructed_records"] if item.get("evidence_class") == "PARTIAL_LIFECYCLE"
            ],
            "rejected_ambiguities": result["rejected_records"],
            "source_lineage_preserved": True,
            "incremental": True,
        }
        try:
            self.reconstruction_state_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(self.reconstruction_state_path, manifest)
            persistence_status = "persisted"
        except Exception:
            persistence_status = "memory_only"
        return {
            "suite": "Astra Historical Lifecycle Reconstruction V1",
            "status": "ok" if result["reconstructed_records"] else "insufficient_evidence",
            "reconstruction": result,
            "authoritative_broker_confirmed_complete_count": authoritative_count,
            "newly_reconstructed_complete_count": result["newly_reconstructed_complete_count"],
            "reconstructed_partial_count": result["reconstructed_partial_count"],
            "authoritative_truth_source": result["authoritative_truth_source"],
            "reconstruction_scope": result["reconstruction_scope"],
            "incremental_manifest": manifest,
            "persistence_status": persistence_status,
            "evidence_separation": {
                "broker_truth_only_for_official_performance": True,
                "reconstructed_records_never_promoted_to_broker_truth": True,
                "authoritative_truth_source": result["authoritative_truth_source"],
                "reconstruction_scope": result["reconstruction_scope"],
            },
            **safety_fields(),
        }
