"""Worker-owned, bounded crypto market-data capability matrix.

Trading capability and market-data observability are distinct facts.  The
matrix reads committed worker evidence only and never performs a provider,
broker, order, or GET-route action.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from engine.provider_router import canonical_crypto_market_symbol_v1


VERSION = "1.0.0"
MAX_PAIRS = 30


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def _classification(row: dict[str, Any]) -> tuple[str, str, str]:
    diagnostic = dict(row.get("provider_diagnostics") or {})
    failed = [dict(item) for item in diagnostic.get("failed_probes") or [] if isinstance(item, dict)]
    status = next((int(item.get("http_status")) for item in failed if str(item.get("http_status") or "").isdigit()), 0)
    error = " ".join(str(item.get("error") or "") for item in failed).lower()
    if status == 401 or "missing_alpaca_secret" in error or "missing_api_key" in error:
        return "PROVIDER_AUTHENTICATION_FAILURE", "provider authentication -> quote response", "verify configured market-data credentials; do not print or write secrets"
    if status == 403:
        return "PROVIDER_ENTITLEMENT_LIMITATION", "provider entitlement -> quote response", "verify market-data entitlement/feed; do not change trading configuration"
    if status == 429 or "rate" in error or "budget_guard" in error:
        return "PROVIDER_RATE_LIMIT", "provider request budget -> quote response", "wait for approved provider cooldown"
    if failed and all(bool(item.get("empty_response")) for item in failed):
        return "PROVIDER_EMPTY_RESPONSE", "provider response -> response key lookup", "retain fail-closed state and inspect response-key diagnostics"
    if not row.get("quote_received"):
        return "PROVIDER_TEMPORARY_UNAVAILABLE", "ProviderRouter -> provider response", "wait for bounded worker recheck"
    if row.get("quote_received") and (not row.get("bid_present") or not row.get("ask_present")):
        return "LEGITIMATE_NO_CURRENT_DATA", "provider quote -> bid/ask availability", "require real bid and ask before spread"
    return "PASS", "", ""


class CryptoMarketDataCapabilityMatrixV1:
    def __init__(self, state_dir: str | Path = "state") -> None:
        self.path = Path(state_dir) / "astra_crypto_market_data_capability_matrix_v1.json"

    def load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(value) if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def build(self, *, capability: dict[str, Any], ranking_snapshot: dict[str, Any], max_pairs: int = MAX_PAIRS) -> dict[str, Any]:
        previous = self.load()
        limit = max(1, min(MAX_PAIRS, int(max_pairs)))
        pairs = [str(value).upper().replace("-", "/") for value in (ranking_snapshot.get("crypto_discovery_universe") or capability.get("tradable_pairs") or [])]
        pairs = list(dict.fromkeys(pair for pair in pairs if pair.endswith("/USD")))[:limit]
        evidence = {str(row.get("symbol") or "").upper(): dict(row) for row in ranking_snapshot.get("crypto_quote_integrity_rows") or [] if isinstance(row, dict)}
        previous_rows = {str(row.get("symbol") or "").upper(): dict(row) for row in previous.get("pairs") or [] if isinstance(row, dict)}
        supported = {str(value).upper().replace("-", "/") for value in capability.get("supported_pairs") or []}
        tradable = {str(value).upper().replace("-", "/") for value in capability.get("tradable_pairs") or []}
        rows: list[dict[str, Any]] = []
        for position, pair in enumerate(pairs, start=1):
            identity, observed, old = canonical_crypto_market_symbol_v1(pair), dict(evidence.get(pair) or {}), dict(previous_rows.get(pair) or {})
            attempted = bool(observed)
            received = bool(observed.get("quote_received"))
            classification, handoff, action = _classification(observed) if attempted else ("LEGITIMATE_NO_CURRENT_DATA", "rotation -> pair not yet evaluated", "await bounded rotation evaluation")
            streak = 0 if received else int(old.get("quote_failure_streak") or 0) + (1 if attempted else 0)
            bid, ask = observed.get("provider_bid"), observed.get("provider_ask")
            bid_present, ask_present = bool(observed.get("bid_present")), bool(observed.get("ask_present"))
            spread_present = bool(observed.get("spread_present"))
            last_quote_timestamp = observed.get("quote_timestamp") or old.get("last_quote_timestamp")
            last_bar_timestamp = observed.get("bar_timestamp") or old.get("last_completed_bar_timestamp")
            completed_bar_observable = bool(observed.get("bar_timestamp"))
            last_spread = observed.get("spread_pct") if observed.get("spread_pct") is not None else old.get("last_spread")
            try:
                numeric_bid, numeric_ask = float(bid), float(ask)
                if last_spread is None and numeric_bid > 0 and numeric_ask >= numeric_bid:
                    midpoint = (numeric_bid + numeric_ask) / 2.0
                    last_spread = round(((numeric_ask - numeric_bid) / midpoint) * 100.0, 8) if midpoint > 0 else None
            except (TypeError, ValueError):
                pass
            rows.append({
                "symbol": identity["internal_pair"], "base_asset": identity["base_asset"], "quote_asset": identity["quote_asset"],
                "provider": (observed.get("quote_provider") or "ALPACA").upper(), "feed": "us",
                "quote_endpoint": "/v1beta3/crypto/us/latest/quotes", "bar_endpoint": "/v1beta3/crypto/us/bars",
                "request_symbol": identity["provider_request_symbol"], "response_symbol": (observed.get("provider_diagnostics") or {}).get("response_key"),
                "broker_supported": pair in supported, "broker_tradable": pair in tradable,
                "snapshot_endpoint_supported": True, "latest_quote_observable": received, "snapshot_quote_observable": received,
                "bid_observable": bid_present, "ask_observable": ask_present, "spread_observable": spread_present,
                "latest_trade_observable": False, "bar_endpoint_supported": True, "bar_data_observable": bool(observed.get("bars_available")),
                "completed_bar_observable": completed_bar_observable, "completed_volume_observable": bool(observed.get("volume_available")),
                "websocket_configured": False, "websocket_observable": False,
                "quote_freshness_eligible": bool(received and observed.get("quote_timestamp")), "spread_eligible": spread_present,
                "liquidity_eligible": bool(observed.get("volume_available")), "data_quality_ready": bool(observed.get("candidate_persisted")),
                "execution_readiness_eligible": False, "last_quote_attempt_at": observed.get("quote_observed_at"),
                "last_quote_success_at": observed.get("quote_timestamp") if received else old.get("last_quote_success_at"),
                "last_bar_attempt_at": observed.get("quote_observed_at") if received else old.get("last_bar_attempt_at"),
                "last_bar_success_at": observed.get("bar_timestamp") or old.get("last_bar_success_at"), "last_websocket_success_at": None,
                "last_bid": bid if bid_present else old.get("last_bid"), "last_ask": ask if ask_present else old.get("last_ask"),
                "last_spread": last_spread, "last_quote_timestamp": last_quote_timestamp,
                "last_completed_bar_timestamp": last_bar_timestamp, "last_completed_volume": observed.get("rolling_completed_bar_volume") if observed.get("rolling_completed_bar_volume") is not None else old.get("last_completed_volume"),
                "quote_failure_streak": streak, "bar_failure_streak": 0 if completed_bar_observable else int(old.get("bar_failure_streak") or 0) + (1 if received else 0),
                "failure_classification": classification, "first_bad_handoff": handoff, "confidence": "VERIFIED" if attempted else "MODERATE",
                "governance_status": "PASS" if classification == "PASS" else "LEGITIMATE_WAITING" if classification.startswith("PROVIDER_") or classification == "LEGITIMATE_NO_CURRENT_DATA" else "UNKNOWN_FAIL_CLOSED",
                "recommended_action": action, "rotation_position": position, "rotation_cycle_id": ranking_snapshot.get("generated_at"),
                "unobservable_pair_cooldown": bool(streak >= 3), "next_recheck_at": None if streak < 3 else "bounded_worker_cooldown",
            })
        summary = {"pairs_monitored": len(rows), "broker_tradable": sum(bool(row["broker_tradable"]) for row in rows), "quote_observable": sum(bool(row["latest_quote_observable"]) for row in rows), "bid_ask_observable": sum(bool(row["bid_observable"] and row["ask_observable"]) for row in rows), "spread_eligible": sum(bool(row["spread_eligible"]) for row in rows), "bar_observable": sum(bool(row["bar_data_observable"]) for row in rows), "completed_volume_observable": sum(bool(row["completed_volume_observable"]) for row in rows), "data_quality_ready": sum(bool(row["data_quality_ready"]) for row in rows), "execution_readiness_eligible": 0}
        roots = list(dict.fromkeys(row["failure_classification"] for row in rows if row["failure_classification"] not in {"PASS", "LEGITIMATE_NO_CURRENT_DATA"}))
        return {"schema_version": VERSION, "generated_at": _now(), "provider": "ALPACA", "feed": "us", "pairs": rows, "summary": summary, "root_causes": roots, "human_actions": [row["recommended_action"] for row in rows if row["failure_classification"] in {"PROVIDER_AUTHENTICATION_FAILURE", "PROVIDER_ENTITLEMENT_LIMITATION"}], "rotation_fairness_status": "BOUNDED_ROTATION_ACTIVE", "provider_calls_from_get": 0, "broker_actions_from_get": 0, "llm_calls_from_get": 0, "state_mutations_from_get": 0, "paper_only_preserved": True, "behavior_safe_to_apply": False}

    def write(self, payload: dict[str, Any]) -> None:
        _atomic(self.path, dict(payload))

    def snapshot(self) -> dict[str, Any]:
        value = self.load()
        return {"endpoint": "/api/crypto_market_data_capability_matrix_v1", "status": "PASS" if value and int((value.get("summary") or {}).get("quote_observable") or 0) else "PARTIAL" if value else "FAIL_CLOSED", **value, "provider_calls_from_get": 0, "broker_actions_from_get": 0, "llm_calls_from_get": 0, "state_mutations_from_get": 0, "get_route_read_only": True, "paper_only_preserved": True, "behavior_safe_to_apply": False}
