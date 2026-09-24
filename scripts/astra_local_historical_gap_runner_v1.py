#!/usr/bin/env python3
"""Bounded local historical-gap runner; never owns trading or truth authority.

Each provider response is retained as an immutable local shard before any PIT
normalization.  Checkpoints are atomic and provider work stops on non-normal
worker resources, authentication, entitlement, rate, or transport failures.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.astra_pit_metadata_contract_v1 import normalize_historical_record
from scripts.astra_historical_context_phase2_v1 import now_iso, read_json, worker_health
from scripts.astra_historical_data_infrastructure_v1 import acquisition_manifest, acquire, durable_write
from engine.astra_resource_aware_workload_scheduler_v1 import build_resource_aware_workload_plan

STATE_ROOT = Path("/Users/Shared/AstraRuntime/state")
SHARED_ENV = Path("/Users/Shared/AstraRuntime/.env")
LOCAL_ROOT_NAME = "historical_context_phase2_v1/local_gap_runner_v1"
REPORT_JSON = ROOT / "reports/astra_local_historical_gap_runner_v1.json"
REPORT_MD = ROOT / "reports/astra_local_historical_gap_runner_v1.md"
DEFAULT_MICRO_SYMBOLS = ("AAPL", "MSFT", "TSLA")
MAX_MICRO_SYMBOLS = 3
MAX_MICRO_DAYS = 5
MAX_MACRO_SERIES = 10
MAX_MACRO_YEARS = 5
MAX_ANALYST_SYMBOLS = 10
MAX_ANALYST_YEARS = 1
MAX_HISTORICAL_NEWS_SYMBOLS = 3
MAX_HISTORICAL_NEWS_DAYS = 3
ANALYST_ENTITLEMENT_BACKOFF_SECONDS = 24 * 60 * 60
TERMINAL_PROVIDER_STATES = {"AUTHENTICATION_FAILED", "ENTITLEMENT_BLOCKED", "RATE_LIMITED", "RESOURCE_BLOCKED"}
NY = ZoneInfo("America/New_York")

SAFETY = {
    "historical_replay_only": True,
    "execution_authority": "DISABLED",
    "broker_actions_added": 0,
    "truth_records_added": 0,
    "learning_acknowledgements_added": 0,
    "capacity_mutations": 0,
    "live_trading_changed": False,
    "policy_changed": False,
}


def load_shared_environment(path: Path = SHARED_ENV) -> dict[str, bool]:
    """Load shared credentials without logging values or overriding exports."""
    loaded: dict[str, bool] = {}
    try:
        from dotenv import dotenv_values

        values = dotenv_values(path)
    except Exception:
        values = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
        except OSError:
            values = {}
    for key, value in values.items():
        if value and key not in os.environ:
            os.environ[key] = str(value)
            loaded[str(key)] = True
    return loaded


def _root(state_dir: Path) -> Path:
    return Path(state_dir) / LOCAL_ROOT_NAME


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    durable_write(path, (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode())


def _atomic_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    body = "".join(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    durable_write(path, body.encode())


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def resource_gate(state_dir: Path = STATE_ROOT) -> dict[str, Any]:
    """Allow bounded history work during NORMAL or REDUCE_BATCH resource states."""
    health = worker_health(Path(state_dir))
    state = str(health.get("resource_state") or "UNKNOWN")
    worker_count = int(health.get("worker_count") or 0)
    last_error = bool(health.get("last_error"))
    allowed_states = {"RESOURCE_NORMAL", "RESOURCE_ELEVATED"}
    blocked = state not in allowed_states or worker_count != 1 or last_error
    mode = "REDUCED" if state == "RESOURCE_ELEVATED" and not blocked else "NORMAL" if not blocked else "BLOCKED"
    scheduler = build_resource_aware_workload_plan(health, previous=health.get("workload_scheduler_v1"))
    return {
        "allowed": not blocked,
        "mode": mode,
        "resource_state": state,
        "worker_count": worker_count,
        "reason": "REDUCE_BATCH" if mode == "REDUCED" else "RESOURCE_NORMAL" if mode == "NORMAL" else "worker_resource_or_health_gate",
        "health": {k: health.get(k) for k in ("worker_pid", "cycle_count", "updated_at", "last_error", "source_identity")},
        "scheduler": scheduler,
        "max_background_workers": scheduler["max_background_workers"],
    }


def _router():
    from engine.provider_router import ProviderRouter

    return ProviderRouter()


def _blocked_call() -> dict[str, Any]:
    return {
        "requested_at": now_iso(),
        "received_at": now_iso(),
        "http_status": 0,
        "error": "RESOURCE_BLOCKED",
        "latency_ms": 0.0,
        "data": {},
    }


def _call(
    router: Any,
    provider: str,
    url: str,
    *,
    params: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
    state_dir: Path = STATE_ROOT,
) -> dict[str, Any]:
    gate = resource_gate(Path(state_dir))
    if not gate["allowed"]:
        return _blocked_call()
    # Historical work stays deliberately low priority.
    time.sleep(10 if gate.get("mode") == "REDUCED" else 2)
    # Resource state may change while pacing; never issue a request after a
    # pause or worker-health failure.
    if not resource_gate(Path(state_dir))["allowed"]:
        return _blocked_call()
    requested_at = now_iso()
    data, status, error, latency = router._request(provider, url, params=dict(params), headers=dict(headers or {}))
    return {
        "requested_at": requested_at,
        "received_at": now_iso(),
        "http_status": status,
        "error": str(error or ""),
        "latency_ms": round(float(latency or 0.0), 3),
        "data": data if isinstance(data, dict) else {"_list": data},
    }


def _status(call: Mapping[str, Any]) -> str:
    code = int(call.get("http_status") or 0)
    error = str(call.get("error") or "")
    if code in (401, 403):
        return "AUTHENTICATION_FAILED" if code == 401 else "ENTITLEMENT_BLOCKED"
    if code == 429 or "budget" in error.lower() or "rate" in error.lower():
        return "RATE_LIMITED"
    if code >= 400 or error:
        return "PROVIDER_ERROR"
    return "SUCCESS"


def _safe_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}", symbol):
        raise ValueError("invalid bounded equity symbol")
    return symbol


def _iso_day(value: date) -> str:
    return value.isoformat()


def _bounded_days(end: str | None, max_days: int) -> list[str]:
    last = date.fromisoformat(end) if end else datetime.now(NY).date() - timedelta(days=1)
    days: list[str] = []
    cursor = last
    while len(days) < max_days:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return sorted(days)


def run_historical_news(
    *,
    state_dir: Path = STATE_ROOT,
    symbols: Iterable[str] = DEFAULT_MICRO_SYMBOLS,
    end: str | None = None,
    max_days: int = 1,
    router: Any = None,
) -> dict[str, Any]:
    """Run the existing Finnhub daily archive as a bounded resumable pilot."""
    gate = resource_gate(state_dir)
    result: dict[str, Any] = {
        "lane": "historical-news",
        **SAFETY,
        "resource_gate": gate,
        "provider_calls": 0,
        "records": 0,
    }
    if not gate["allowed"]:
        result.update(status="RESOURCE_BLOCKED", reason=gate["reason"])
        return result
    selected = sorted({_safe_symbol(symbol) for symbol in symbols})
    if not selected or len(selected) > MAX_HISTORICAL_NEWS_SYMBOLS:
        raise ValueError(f"historical-news pilot accepts 1-{MAX_HISTORICAL_NEWS_SYMBOLS} symbols")
    days = _bounded_days(end, min(max(1, int(max_days)), MAX_HISTORICAL_NEWS_DAYS))
    if len(selected) * len(days) > 10:
        raise ValueError("historical-news pilot exceeds ten daily windows")
    archive_root = _root(Path(state_dir)) / "historical-news" / "archive"
    manifest = acquisition_manifest(
        mode="BOUNDED_PILOT",
        symbols=selected,
        start=days[0],
        end=days[-1],
        checkpoint_path=str(archive_root / "index.sqlite3"),
        max_calls=10,
    )
    outcome = acquire(manifest, archive_root, router or _router(), Path(state_dir))
    result.update(
        status=str(outcome.get("status") or "PROVIDER_ERROR"),
        provider_calls=int(outcome.get("requests") or 0),
        symbols=selected,
        days=days,
        checkpoint_path=str(archive_root / "index.sqlite3"),
        exhaustive_coverage_proven=bool(outcome.get("exhaustive_coverage_proven")),
    )
    _atomic_json(_root(Path(state_dir)) / "historical_news_checkpoint.json", result)
    return result


def discover_fred_series(state_dir: Path = STATE_ROOT, *, limit: int = MAX_MACRO_SERIES) -> list[str]:
    """Return only series IDs already present in local retained evidence."""
    found: set[str] = set()
    roots = [Path(state_dir) / "historical_context_phase2_v1", ROOT / "reports"]
    for base in roots:
        if not base.exists():
            continue
        paths = list(base.glob("*.jsonl")) + list(base.glob("*.json"))
        for path in paths:
            try:
                with path.open(encoding="utf-8") as handle:
                    for line_no, line in enumerate(handle):
                        if line_no >= 20000:
                            break
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        candidates = [row] if isinstance(row, dict) else []
                        if isinstance(row, dict) and isinstance(row.get("record"), dict):
                            candidates.append(row["record"])
                        for candidate in candidates:
                            provider = str(candidate.get("source_provider") or candidate.get("provider") or "").upper()
                            value = candidate.get("series_id") or candidate.get("source_series")
                            if value and (provider in {"", "FRED"}):
                                found.add(str(value).strip().upper())
                                if len(found) >= limit:
                                    return sorted(found)[:limit]
            except OSError:
                continue
    return sorted(found)[: max(0, min(int(limit), MAX_MACRO_SERIES))]


def _macro_record(series: str, raw: Mapping[str, Any], *, receipt: str, source_file: str) -> dict[str, Any]:
    record = {
        "series_id": series,
        "observation_date": raw.get("date") or raw.get("observation_date"),
        "value": raw.get("value"),
        "realtime_start": raw.get("realtime_start"),
        "realtime_end": raw.get("realtime_end"),
        "provider_observed_time": raw.get("provider_observed_time"),
        "available_to_astra_time": raw.get("available_to_astra_time"),
        "ingested_at": receipt,
        "source_provider": "FRED",
        "source_record_id": f"{series}:{raw.get('date')}:{raw.get('realtime_start')}:{raw.get('realtime_end')}",
        "source_file": source_file,
        "original_timestamp_fields": {k: raw.get(k) for k in ("date", "observation_date", "realtime_start", "realtime_end", "vintage_date", "release_time") if raw.get(k) is not None},
    }
    pit = normalize_historical_record(record, dataset_type="fred", source_context={"replay_contract_valid": True})
    record["pit_metadata"] = pit
    record.update({k: pit[k] for k in ("point_in_time_status", "lookahead_risk", "replay_safe", "replay_safe_reason", "event_time", "publication_time", "available_to_astra_time")})
    return record


def run_macro(*, state_dir: Path = STATE_ROOT, max_series: int = MAX_MACRO_SERIES, max_years: int = MAX_MACRO_YEARS, router: Any = None) -> dict[str, Any]:
    gate = resource_gate(state_dir)
    result: dict[str, Any] = {"lane": "macro", **SAFETY, "resource_gate": gate, "provider_calls": 0, "records": 0}
    if not gate["allowed"]:
        result.update(status="RESOURCE_BLOCKED", series=[], reason=gate["reason"])
        return result
    series = discover_fred_series(state_dir, limit=max_series)
    result["series"] = series
    if not series:
        result.update(status="NO_SERIES_IDENTIFIED", reason="no concrete FRED series IDs exist in retained Astra evidence")
        return result
    load_shared_environment()
    key = str(os.getenv("FRED_API_KEY") or "").strip()
    if not key:
        result.update(status="AUTHENTICATION_FAILED", reason="FRED_API_KEY unavailable")
        return result
    router = router or _router()
    archive = _root(Path(state_dir)) / "macro"
    raw_dir, normalized_dir = archive / "raw", archive / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True); normalized_dir.mkdir(parents=True, exist_ok=True)
    start = (datetime.now(UTC).date() - timedelta(days=365 * min(max_years, MAX_MACRO_YEARS))).isoformat()
    end = datetime.now(UTC).date().isoformat()
    statuses = []
    for series_id in series:
        if not resource_gate(state_dir)["allowed"]:
            statuses.append({"series_id": series_id, "status": "RESOURCE_BLOCKED"}); break
        call = _call(router, "FRED", "https://api.stlouisfed.org/fred/series/observations", params={"series_id": series_id, "api_key": key, "file_type": "json", "observation_start": start, "observation_end": end, "realtime_start": start, "realtime_end": end}, state_dir=Path(state_dir))
        if call.get("error") == "RESOURCE_BLOCKED":
            statuses.append({"series_id": series_id, "status": "RESOURCE_BLOCKED"})
            result.update(status="RESOURCE_BLOCKED", series_status=statuses)
            _atomic_json(_root(Path(state_dir)) / "macro_checkpoint.json", result)
            return result
        result["provider_calls"] += 1
        state = _status(call)
        shard = raw_dir / f"{series_id}_{uuid.uuid4().hex}.json"
        _atomic_json(shard, {"provider": "FRED", "series_id": series_id, "request": {"start": start, "end": end}, "receipt": call["received_at"], "response": call["data"]})
        observations = call["data"].get("observations") if isinstance(call["data"], dict) else []
        normalized_rows = []
        for raw in observations if isinstance(observations, list) else []:
            normalized_rows.append(_macro_record(series_id, raw, receipt=call["received_at"], source_file=str(shard)))
        if normalized_rows:
            _atomic_jsonl(normalized_dir / f"{series_id}.jsonl", normalized_rows)
            result["records"] += len(normalized_rows)
        statuses.append({"series_id": series_id, "status": state, "records": len(normalized_rows), "raw_shard": str(shard)})
        if state in TERMINAL_PROVIDER_STATES or state != "SUCCESS":
            break
    result["series_status"] = statuses
    result["status"] = "COMPLETE" if statuses and all(s["status"] == "SUCCESS" for s in statuses) else statuses[-1]["status"] if statuses else "NO_SERIES_IDENTIFIED"
    _atomic_json(_root(Path(state_dir)) / "macro_checkpoint.json", result)
    return result


def _micro_record(symbol: str, feed: str, raw: Mapping[str, Any], *, receipt: str, source_file: str) -> dict[str, Any]:
    event_time = raw.get("t") or raw.get("timestamp") or raw.get("event_time")
    record = {
        "symbol": symbol,
        "feed": feed,
        "event_time": event_time,
        "provider_event_time": event_time,
        "provider_observed_time": raw.get("provider_observed_time") or raw.get("receive_time"),
        "available_to_astra_time": None,
        "bid": raw.get("bp"), "ask": raw.get("ap"), "bid_size": raw.get("bs"), "ask_size": raw.get("as"),
        "trade_price": raw.get("p"), "trade_size": raw.get("s"), "venue": raw.get("x"), "sequence": raw.get("i"),
        "source_provider": "ALPACA_SIP", "source_record_id": str(raw.get("i") or f"{symbol}:{feed}:{event_time}:{uuid.uuid4().hex}"),
        "ingested_at": receipt, "source_file": source_file, "original_timestamp_fields": {k: raw.get(k) for k in ("t", "timestamp", "event_time", "receive_time", "provider_observed_time") if raw.get(k) is not None},
    }
    pit = normalize_historical_record(record, dataset_type="microstructure", source_context={"replay_contract_valid": False})
    record["pit_metadata"] = pit
    record.update({k: pit[k] for k in ("point_in_time_status", "lookahead_risk", "replay_safe", "replay_safe_reason")})
    record.update(SAFETY)
    return record


def run_microstructure(*, state_dir: Path = STATE_ROOT, symbols: Iterable[str] = DEFAULT_MICRO_SYMBOLS, end: str | None = None, max_days: int = MAX_MICRO_DAYS, router: Any = None) -> dict[str, Any]:
    gate = resource_gate(state_dir)
    result: dict[str, Any] = {"lane": "microstructure", **SAFETY, "resource_gate": gate, "provider_calls": 0, "records": 0, "symbols": []}
    if not gate["allowed"]:
        result.update(status="RESOURCE_BLOCKED", reason=gate["reason"]); return result
    selected = sorted({_safe_symbol(s) for s in symbols})
    if not selected or len(selected) > MAX_MICRO_SYMBOLS:
        raise ValueError(f"microstructure pilot accepts 1-{MAX_MICRO_SYMBOLS} symbols")
    days = _bounded_days(end, min(int(max_days), MAX_MICRO_DAYS))
    router = router or _router(); archive = _root(Path(state_dir)) / "microstructure"
    raw_dir, normalized_dir, checkpoint_dir = archive / "raw", archive / "normalized", archive / "checkpoints"
    for directory in (raw_dir, normalized_dir, checkpoint_dir): directory.mkdir(parents=True, exist_ok=True)
    statuses = []
    for symbol in selected:
        for day in days:
            for feed, endpoint in (("quotes", "https://data.alpaca.markets/v2/stocks/quotes"), ("trades", "https://data.alpaca.markets/v2/stocks/trades")):
                key = f"{symbol}:{day}:{feed}"; cp_path = checkpoint_dir / f"{symbol}_{day}_{feed}.json"; cp = _read_json(cp_path, {}) or {}
                if cp.get("status") == "SUCCESS" and not cp.get("next_page_token"):
                    statuses.append({"key": key, "status": "SUCCESS", "pages": int(cp.get("pages") or 0), "resumed": True})
                    continue
                token = cp.get("next_page_token"); page = int(cp.get("pages") or 0)
                while True:
                    gate = resource_gate(state_dir)
                    if not gate["allowed"]:
                        statuses.append({"key": key, "status": "RESOURCE_BLOCKED", "page": page}); result["status"] = "RESOURCE_BLOCKED"; return result
                    params = {"symbols": symbol, "start": f"{day}T09:30:00-04:00", "end": f"{day}T16:00:00-04:00", "limit": 1000, "feed": "sip", "sort": "asc"}
                    if token: params["page_token"] = token
                    load_shared_environment(); api_key = str(os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or "").strip(); secret = str(os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "").strip()
                    if not api_key or not secret:
                        result.update(status="AUTHENTICATION_FAILED", reason="Alpaca credentials unavailable"); return result
                    call = _call(router, "ALPACA", endpoint, params=params, headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret}, state_dir=Path(state_dir))
                    if call.get("error") == "RESOURCE_BLOCKED":
                        statuses.append({"key": key, "status": "RESOURCE_BLOCKED", "page": page})
                        result.update(status="RESOURCE_BLOCKED", statuses=statuses)
                        return result
                    result["provider_calls"] += 1; state = _status(call); receipt = call["received_at"]
                    page_id = f"{symbol}_{day}_{feed}_{page:05d}"
                    raw_path = raw_dir / f"{page_id}.json"; normalized_path = normalized_dir / f"{page_id}.jsonl"
                    _atomic_json(raw_path, {"provider": "ALPACA_SIP", "symbol": symbol, "feed": feed, "request": params, "receipt": receipt, "response": call["data"]})
                    payload = (call["data"].get(feed) or []) if isinstance(call["data"], dict) else []
                    if isinstance(payload, dict):
                        rows = payload.get(symbol) or payload.get(symbol.upper()) or []
                    elif isinstance(payload, list):
                        rows = payload
                    else:
                        rows = []
                    normalized = [_micro_record(symbol, feed, row, receipt=receipt, source_file=str(raw_path)) for row in rows if isinstance(row, dict)]
                    if normalized: _atomic_jsonl(normalized_path, normalized); result["records"] += len(normalized)
                    token = call["data"].get("next_page_token") if isinstance(call["data"], dict) else None
                    cp = {"schema_version": "astra_local_historical_gap_runner_v1", "key": key, "status": state, "pages": page + 1, "records": int(cp.get("records") or 0) + len(normalized), "next_page_token": token, "last_raw_shard": str(raw_path), "updated_at": now_iso(), **SAFETY}
                    _atomic_json(cp_path, cp); page += 1
                    if state != "SUCCESS" or not token: break
                statuses.append({"key": key, "status": state, "pages": page})
                if state != "SUCCESS":
                    result.update(status=state, statuses=statuses); return result
    result.update(status="COMPLETE", statuses=statuses, symbols=selected, days=days)
    _atomic_json(_root(Path(state_dir)) / "microstructure_checkpoint.json", result)
    return result


def _analyst_record(symbol: str, provider: str, raw: Mapping[str, Any], *, receipt: str, source_file: str) -> dict[str, Any]:
    publication = raw.get("publication_time") or raw.get("publishedDate") or raw.get("published_at") or raw.get("publishedAt")
    event = raw.get("effective_time") or raw.get("date") or raw.get("event_time")
    record = {"symbol": symbol, "analyst": raw.get("analyst") or raw.get("analystName"), "firm": raw.get("firm") or raw.get("company"), "old_value": raw.get("old_value") or raw.get("oldGrade") or raw.get("oldTargetPrice"), "new_value": raw.get("new_value") or raw.get("newGrade") or raw.get("newTargetPrice"), "event_time": event, "publication_time": publication, "available_to_astra_time": publication, "ingested_at": receipt, "source_provider": provider, "source_record_id": str(raw.get("id") or raw.get("record_id") or f"{symbol}:{event}:{publication}"), "source_file": source_file, "original_timestamp_fields": {k: raw.get(k) for k in ("date", "effective_time", "publication_time", "publishedDate", "published_at", "publishedAt", "updatedDate") if raw.get(k) is not None}}
    pit = normalize_historical_record(record, dataset_type="analyst_revision", source_context={"replay_contract_valid": True})
    record["pit_metadata"] = pit; record.update({k: pit[k] for k in ("point_in_time_status", "lookahead_risk", "replay_safe", "replay_safe_reason")}); record.update(SAFETY)
    return record


def run_analyst(*, state_dir: Path = STATE_ROOT, symbols: Iterable[str] = DEFAULT_MICRO_SYMBOLS, max_symbols: int = MAX_ANALYST_SYMBOLS, max_years: int = MAX_ANALYST_YEARS, router: Any = None) -> dict[str, Any]:
    gate = resource_gate(state_dir); result: dict[str, Any] = {"lane": "analyst", **SAFETY, "resource_gate": gate, "provider_calls": 0, "records": 0}
    if not gate["allowed"]: result.update(status="RESOURCE_BLOCKED", reason=gate["reason"]); return result
    selected = sorted({_safe_symbol(s) for s in symbols})[: max(1, min(int(max_symbols), MAX_ANALYST_SYMBOLS))]
    load_shared_environment(); router = router or _router()
    finnhub_key = str(os.getenv("FINNHUB_API_KEY") or getattr(router, "_key_for", lambda *_: "")("FINNHUB", "stock") or "").strip()
    fmp_key = str(os.getenv("FMP_API_KEY") or getattr(router, "_key_for", lambda *_: "")("FMP", "stock") or "").strip()
    entitlement_path = _root(Path(state_dir)) / "analyst_entitlement_backoff.json"
    entitlement = _read_json(entitlement_path, {}) or {}
    blocked_until = float(entitlement.get("finnhub_blocked_until_epoch") or 0.0)
    finnhub_available = bool(finnhub_key and blocked_until <= time.time())
    provider = "FINNHUB" if finnhub_available else "FMP" if fmp_key else ""
    if not provider:
        if finnhub_key and blocked_until > time.time():
            result.update(
                status="ENTITLEMENT_BLOCKED",
                reason="Finnhub analyst entitlement backoff active and no FMP fallback is configured",
                finnhub_blocked_until_epoch=blocked_until,
            )
        else:
            result.update(status="AUTHENTICATION_FAILED", reason="no configured Finnhub/FMP credential")
        return result
    archive = _root(Path(state_dir)) / "analyst"; raw_dir, norm_dir = archive / "raw", archive / "normalized"; raw_dir.mkdir(parents=True, exist_ok=True); norm_dir.mkdir(parents=True, exist_ok=True)
    start = (datetime.now(UTC).date() - timedelta(days=365 * min(int(max_years), MAX_ANALYST_YEARS))).isoformat(); end = datetime.now(UTC).date().isoformat(); statuses=[]
    symbol_index = 0
    while symbol_index < len(selected):
        symbol = selected[symbol_index]
        if provider == "FINNHUB":
            specs = [("upgrade_downgrade", "https://finnhub.io/api/v1/stock/upgrade-downgrade", {"symbol": symbol, "from": start, "to": end, "token": finnhub_key}), ("price_target", "https://finnhub.io/api/v1/stock/price-target", {"symbol": symbol, "from": start, "to": end, "token": finnhub_key})]
        else:
            specs = [("analyst_estimates", "https://financialmodelingprep.com/stable/analyst-estimates", {"symbol": symbol, "apikey": fmp_key})]
        for family, endpoint, params in specs:
            if not resource_gate(state_dir)["allowed"]: result.update(status="RESOURCE_BLOCKED", statuses=statuses); return result
            call = _call(router, provider, endpoint, params=params, state_dir=Path(state_dir))
            if call.get("error") == "RESOURCE_BLOCKED":
                statuses.append({"symbol": symbol, "family": family, "status": "RESOURCE_BLOCKED"})
                result.update(status="RESOURCE_BLOCKED", statuses=statuses)
                return result
            result["provider_calls"] += 1; state = _status(call); receipt=call["received_at"]; raw_rows = call["data"].get("_list") if isinstance(call["data"], dict) and isinstance(call["data"].get("_list"), list) else call["data"] if isinstance(call["data"], list) else []
            shard=raw_dir/f"{symbol}_{family}.json"; _atomic_json(shard,{"provider":provider,"symbol":symbol,"family":family,"request":{"start":start,"end":end},"receipt":receipt,"response":call["data"]})
            normalized=[_analyst_record(symbol,provider,row,receipt=receipt,source_file=str(shard)) for row in raw_rows if isinstance(row,dict) and (row.get("publishedDate") or row.get("publication_time") or row.get("published_at") or row.get("publishedAt"))]
            if normalized: _atomic_jsonl(norm_dir/f"{symbol}_{family}.jsonl",normalized); result["records"] += len(normalized)
            statuses.append({"symbol":symbol,"family":family,"status":state,"raw_records":len(raw_rows),"normalized_records":len(normalized)})
            if state == "ENTITLEMENT_BLOCKED" and provider == "FINNHUB":
                _atomic_json(entitlement_path, {
                    "provider": "FINNHUB",
                    "status": "ENTITLEMENT_BLOCKED",
                    "finnhub_blocked_until_epoch": time.time() + ANALYST_ENTITLEMENT_BACKOFF_SECONDS,
                    "updated_at": now_iso(),
                    **SAFETY,
                })
                if fmp_key:
                    provider = "FMP"
                    result["fallback"] = "FMP_AFTER_FINNHUB_ENTITLEMENT_BLOCKED"
                    break
            if state != "SUCCESS": result.update(status=state,statuses=statuses); return result
        else:
            symbol_index += 1
            continue
        if provider == "FMP":
            continue
        result.update(status=state, statuses=statuses)
        return result
    result.update(status="COMPLETE",provider=provider,statuses=statuses,selection={"max_symbols":MAX_ANALYST_SYMBOLS,"max_years":MAX_ANALYST_YEARS})
    _atomic_json(_root(Path(state_dir))/"analyst_checkpoint.json",result); return result


def run_news_proof(*, state_dir: Path = STATE_ROOT) -> dict[str, Any]:
    result: dict[str, Any] = {"lane": "news-proof", **SAFETY, "provider_calls": 0, "records": 0, "replay_safe": False, "status": "UNPROVEN"}
    root = Path(state_dir) / "historical_context_phase2_v1"
    paths = list(root.glob("**/*.jsonl"))[:64]; seen=0; timing_proven=0; versions=0
    for path in paths:
        try:
            with path.open(encoding="utf-8") as handle:
                for line_no,line in enumerate(handle):
                    if line_no >= 10000: break
                    try: row=json.loads(line)
                    except ValueError: continue
                    provider=str(row.get("source_provider") or row.get("provider") or "").upper()
                    if provider != "FINNHUB": continue
                    seen += 1; versions += int(bool(row.get("version_id") or row.get("source_record_id")))
                    if row.get("historical_source_available_time") and row.get("publication_time") and (row.get("version_id") or row.get("source_record_id")): timing_proven += 1
        except OSError: continue
    result.update(records=seen, versioned_records=versions, timing_proven_records=timing_proven, status="PROVEN" if seen and timing_proven == seen else "UNPROVEN", replay_safe=bool(seen and timing_proven == seen), reason="retained evidence does not prove first provider availability/version timing" if timing_proven != seen else "retained provider availability and version timing are explicit")
    _atomic_json(_root(Path(state_dir))/"news_proof_checkpoint.json",result); return result


def _write_reports(results: Mapping[str, Any]) -> None:
    payload = {"schema_version": "astra_local_historical_gap_runner_v1", "generated_at": now_iso(), "results": dict(results), **SAFETY}
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True); _atomic_json(REPORT_JSON,payload)
    lines=["# Astra Local Historical Gap Runner V1", "", f"Generated: {payload['generated_at']}", "", "Read-only historical replay work; no trading, truth, learning, or broker authority.", ""]
    for name,value in results.items(): lines.extend([f"## {name}", "", f"- status: `{value.get('status')}`", f"- provider calls: `{value.get('provider_calls', 0)}`", f"- records: `{value.get('records', 0)}`", ""])
    durable_write(REPORT_MD, ("\n".join(lines) + "\n").encode())


def run_command(command: str, **kwargs: Any) -> dict[str, Any]:
    load_shared_environment()
    if command == "macro": result = run_macro(**kwargs)
    elif command == "microstructure": result = run_microstructure(**kwargs)
    elif command == "analyst": result = run_analyst(**kwargs)
    elif command == "news-proof": result = run_news_proof(**kwargs)
    elif command == "historical-news": result = run_historical_news(**kwargs)
    elif command == "all":
        result = {name: run_command(name, **kwargs) for name in ("news-proof", "historical-news", "macro", "analyst", "microstructure")}
    else: raise ValueError(f"unsupported command: {command}")
    _write_reports(result if command == "all" else {command: result})
    return result


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    for name in ("macro","microstructure","analyst","news-proof","historical-news","all"):
        p=sub.add_parser(name); p.add_argument("--state-dir",type=Path,default=STATE_ROOT); p.add_argument("--symbols",nargs="*",default=list(DEFAULT_MICRO_SYMBOLS)); p.add_argument("--end"); p.add_argument("--max-days",type=int,default=MAX_MICRO_DAYS); p.add_argument("--max-series",type=int,default=MAX_MACRO_SERIES); p.add_argument("--max-years",type=int,default=MAX_MACRO_YEARS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args=build_parser().parse_args(argv); values=vars(args); command=values.pop("command"); state_dir=values.pop("state_dir")
    if command in {"news-proof"}: values={}
    elif command == "historical-news": values={"symbols":values.pop("symbols"),"end":values.pop("end"),"max_days":values.pop("max_days")}
    elif command == "macro": values={"max_series":values.pop("max_series"),"max_years":values.pop("max_years")}
    elif command == "microstructure": values={"symbols":values.pop("symbols"),"end":values.pop("end"),"max_days":values.pop("max_days")}
    elif command == "analyst":
        symbols = values.pop("symbols")
        values = {"symbols": symbols, "max_symbols": min(len(symbols), MAX_ANALYST_SYMBOLS), "max_years": min(values.pop("max_years"), MAX_ANALYST_YEARS)}
    else: values={"state_dir":state_dir}
    result=run_command(command,**values); print(json.dumps(result,sort_keys=True,separators=(",",":"))); return 0


if __name__ == "__main__":
    raise SystemExit(main())
