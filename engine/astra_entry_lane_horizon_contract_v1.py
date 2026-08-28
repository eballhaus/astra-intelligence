"""Mandatory, fail-closed lane and horizon ownership for new paper entries."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


VERSION = "1.0.0"
VALID_LANES = {"DAY", "SCALP", "SWING", "CRYPTO"}
LANE_ALIASES = {
    "day": "DAY", "day_equity": "DAY", "day_etf": "DAY",
    "scalp": "SCALP",
    "swing": "SWING", "swing_equity": "SWING", "swing_etf": "SWING",
    "crypto": "CRYPTO", "cryptocurrency": "CRYPTO",
}
HORIZON_ALIASES = {
    "scalp": "scalp", "intraday": "day_trade", "day": "day_trade",
    "day_trade": "day_trade", "daytrading": "day_trade", "same_session": "day_trade",
    "short_swing": "swing_trade", "multi_day": "swing_trade", "position": "swing_trade",
    "position_trade": "swing_trade", "swing": "swing_trade", "swing_trade": "swing_trade",
    "crypto": "crypto_multi_horizon", "crypto_short": "crypto_multi_horizon",
    "crypto_multi_horizon": "crypto_multi_horizon",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize(value: Any, aliases: Mapping[str, str]) -> str:
    raw = _text(value).lower().replace("-", "_").replace(" ", "_")
    return aliases.get(raw, "")


def _attributable_value(value: Any) -> str:
    """Keep compatibility placeholders from shadowing canonical evidence."""
    text = _text(value)
    if text.lower().replace("-", "_").replace("/", "_").replace(" ", "_") in {
        "", "unknown", "unavailable", "missing", "none", "null", "n_a", "na",
    }:
        return ""
    return text


def _stable_id(prefix: str, *parts: Any) -> str:
    seed = "|".join(_text(part) for part in parts)
    return prefix + "-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def build_entry_lane_horizon_contract_v1(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build metadata from explicit pretrade evidence only; never default values."""
    source = dict(row or {})
    # `_entry_raw_*` are compatibility snapshots.  They may be blank when the
    # canonical lane registry derives an attributable lane/horizon later in
    # the same pretrade handoff, so only meaningful raw values may override
    # canonical evidence.
    explicit_lane = _attributable_value(source.get("_entry_raw_lane"))
    if not explicit_lane:
        # The paper bridge records the lane supplied by the producer before
        # its compatibility registry runs.  A blank snapshot means no
        # attributable lane existed, so do not validate a later inferred
        # display lane as entry authority.
        if "_entry_canonical_lane" in source:
            explicit_lane = _attributable_value(source.get("_entry_canonical_lane"))
        else:
            explicit_lane = _attributable_value(source.get("lane_id"))
    explicit_horizon = _attributable_value(source.get("_entry_raw_horizon"))
    if not explicit_horizon:
        for key in ("paper_entry_horizon_style", "trade_horizon_style", "best_horizon_style", "intended_horizon", "horizon"):
            value = _attributable_value(source.get(key))
            if value:
                explicit_horizon = value
                break
    lane = _normalize(explicit_lane, {**{key.lower(): value for key, value in LANE_ALIASES.items()}, **{key.lower(): key for key in VALID_LANES}})
    horizon = _normalize(explicit_horizon, HORIZON_ALIASES)
    candidate_id = _text(source.get("candidate_id"))
    selection_id = _text(source.get("selection_id"))
    symbol = _text(source.get("canonical_symbol") or source.get("symbol")).upper()
    asset_class = _text(source.get("asset_class") or source.get("asset_type")).lower()
    lane_source = _text(source.get("lane_assignment_source") or source.get("lane_source")) if lane else ""
    horizon_source = _text(source.get("paper_entry_horizon_source") or source.get("horizon_source")) if horizon else ""
    blockers: list[str] = []
    if not _text(explicit_lane): blockers.append("MISSING_CANONICAL_ENTRY_LANE")
    elif not lane: blockers.append("INVALID_CANONICAL_ENTRY_LANE")
    if not _text(explicit_horizon): blockers.append("MISSING_CANONICAL_ENTRY_HORIZON")
    elif not horizon: blockers.append("INVALID_CANONICAL_ENTRY_HORIZON")
    if lane and not lane_source: blockers.append("MISSING_CANONICAL_ENTRY_LANE_SOURCE")
    if horizon and not horizon_source: blockers.append("MISSING_CANONICAL_ENTRY_HORIZON_SOURCE")
    if not candidate_id or not symbol or not asset_class: blockers.append("ENTRY_LANE_HORIZON_IDENTITY_MISSING")
    order_intent_id = _stable_id("intent", candidate_id, selection_id, symbol, asset_class, lane, horizon) if candidate_id else ""
    if not order_intent_id: blockers.append("ENTRY_LANE_HORIZON_IDENTITY_MISSING")
    status = "RESOLVED" if not blockers else "UNAVAILABLE"
    assigned_at = _text(source.get("selection_timestamp") or source.get("candidate_generated_at") or source.get("generated_at") or _now())
    contract = {
        "schema_version": "astra_entry_lane_horizon_contract_v1", "metadata_generation": "V1_MANDATORY",
        "lane": lane or "UNAVAILABLE", "lane_status": status if lane else "UNAVAILABLE",
        "lane_source": lane_source or "UNAVAILABLE", "lane_assignment_id": _stable_id("lane", candidate_id, lane, lane_source) if lane else "",
        "lane_assigned_at": assigned_at if lane else "",
        "horizon": horizon or "UNAVAILABLE", "horizon_status": status if horizon else "UNAVAILABLE",
        "horizon_source": horizon_source or "UNAVAILABLE", "horizon_assignment_id": _stable_id("horizon", candidate_id, horizon, horizon_source) if horizon else "",
        "horizon_assigned_at": assigned_at if horizon else "",
        "candidate_id": candidate_id, "order_intent_id": order_intent_id,
        "astra_order_id": _stable_id("astra-order", order_intent_id) if order_intent_id else "",
        "broker_client_order_id": _text(source.get("client_order_id") or source.get("broker_client_order_id")),
        "broker_order_id": _text(source.get("broker_order_id") or source.get("entry_order_id")),
        "entry_fill_id": _text(source.get("entry_fill_id")), "lifecycle_id": _text(source.get("lifecycle_id")),
        "symbol": symbol, "asset_class": asset_class, "created_at": assigned_at, "updated_at": _now(),
        "exact_blockers": list(dict.fromkeys(blockers)),
    }
    # These optional fields are copied only from the producer's explicit,
    # bounded evidence envelope. Missing evidence remains absent and the
    # contract stays fail-closed; no horizon is inferred here.
    for key in (
        "horizon_evidence_status", "horizon_evidence_missing", "horizon_provenance",
        "horizon_source", "horizon_source_id", "horizon_source_timestamp",
        "horizon_assignment_version", "horizon_confidence", "horizon_evidence",
    ):
        if key in source and source.get(key) not in (None, "", [], {}):
            contract[key] = source[key]
    return contract


def validate_entry_submission_contract_v1(contract: Mapping[str, Any] | None) -> dict[str, Any]:
    item = dict(contract or {})
    blockers = list(item.get("exact_blockers") or [])
    if item.get("lane") not in VALID_LANES: blockers.append("INVALID_CANONICAL_ENTRY_LANE")
    if item.get("horizon") not in set(HORIZON_ALIASES.values()): blockers.append("INVALID_CANONICAL_ENTRY_HORIZON")
    for key in ("lane_source", "horizon_source", "candidate_id", "order_intent_id", "astra_order_id"):
        if not _text(item.get(key)) or item.get(key) == "UNAVAILABLE": blockers.append("ENTRY_LANE_HORIZON_IDENTITY_MISSING")
    blockers = list(dict.fromkeys(blockers))
    return {"allowed": not blockers, "exact_blockers": blockers, "contract": item,
            "paper_only_preserved": True, "broker_actions_used": 0, "provider_calls_used": 0}


def link_entry_contract_v1(contract: Mapping[str, Any], **identifiers: Any) -> dict[str, Any]:
    result = dict(contract or {})
    for key in ("broker_client_order_id", "broker_order_id", "entry_fill_id", "lifecycle_id"):
        if _text(identifiers.get(key)):
            result[key] = _text(identifiers[key])
    result["updated_at"] = _now()
    return result


class AstraEntryLaneHorizonLedgerV1:
    """Bounded atomic ledger of new entry metadata; never a broker authority."""
    def __init__(self, state_dir: str = "state") -> None:
        self.path = Path(state_dir) / "astra_entry_lane_horizon_integrity_v1.json"

    def snapshot(self) -> dict[str, Any]:
        try:
            return dict(json.loads(self.path.read_text()) or {})
        except Exception:
            return {"schema_version": VERSION, "entries": []}

    def ensure_snapshot(self) -> dict[str, Any]:
        """Worker-only initialization so an empty forward window is explicit."""
        current = self.snapshot()
        if current.get("generated_at"):
            return current
        return self._write([])

    def _write(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"schema_version": VERSION, "generated_at": _now(), "entries": entries[-250:],
                   "summary": {"entries": len(entries[-250:]), "blocked": sum(bool(x.get("exact_blockers")) for x in entries[-250:]),
                               "resolved": sum(not bool(x.get("exact_blockers")) for x in entries[-250:])}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name + ".", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w") as handle: json.dump(payload, handle, sort_keys=True)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
        return payload

    def record(self, contract: Mapping[str, Any], stage: str, blockers: list[str] | None = None) -> dict[str, Any]:
        current = self.snapshot(); entries = [dict(x) for x in current.get("entries") or [] if isinstance(x, dict)]
        item = dict(contract or {}); item["stage"] = stage; item["exact_blockers"] = list(dict.fromkeys(list(item.get("exact_blockers") or []) + list(blockers or [])))
        key = _text(item.get("order_intent_id"))
        prior = next((x for x in entries if _text(x.get("order_intent_id")) == key), {})
        frozen = prior.get("original_pretrade_prediction_snapshot_v1")
        if isinstance(frozen, Mapping) and bool(frozen.get("immutable_original_pretrade_prediction")):
            # Retry/acknowledgement stages may update order linkage but cannot
            # replace the values captured before the first broker attempt.
            item["original_pretrade_prediction_snapshot_v1"] = dict(frozen)
        entries = [x for x in entries if _text(x.get("order_intent_id")) != key]; entries.append(item)
        return self._write(entries)
