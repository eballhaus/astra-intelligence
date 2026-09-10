"""Read-only SEC EDGAR facts adapter for existing provider consumers.

This module is an adapter and parser, not a second routing or authority
layer.  ProviderRouter remains responsible for network access, coalescing,
governor accounting, and consumer selection.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from typing import Any, Callable, Mapping

import requests


SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_TIMEOUT_SECONDS = 4.5
SEC_TICKER_CACHE_SECONDS = 86_400.0
SEC_CONTEXT_CACHE_SECONDS = 900.0

# This is an advisory-only definition.  It is deliberately not wired into
# entry, exit, sizing, or risk decisions.
BETA_CONTRACT_V1 = {
    "benchmark": "SPY",
    "lookback": "252 aligned daily returns",
    "minimum_observations": 60,
    "method": "covariance(asset_returns, benchmark_returns) / benchmark_return_variance",
    "missing_data": "pairwise aligned rows; fail closed below minimum or zero benchmark variance",
    "authority": "ASTRA_DERIVED_ADVISORY_ONLY",
}

SEC_FACT_ALIASES: dict[str, tuple[tuple[str, str], ...]] = {
    "shares_outstanding": (("dei", "EntityCommonStockSharesOutstanding"),),
    "revenue": (("us-gaap", "Revenues"), ("us-gaap", "SalesRevenueNet")),
    "net_income": (("us-gaap", "NetIncomeLoss"),),
    "assets": (("us-gaap", "Assets"),),
    "liabilities": (("us-gaap", "Liabilities"),),
    "operating_income": (("us-gaap", "OperatingIncomeLoss"),),
    "cash_from_operations": (("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),),
    "eps": (("us-gaap", "EarningsPerShareDiluted"), ("us-gaap", "EarningsPerShareBasic")),
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _clean_cik(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def _iso_epoch(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            number = float(value)
            if number > 1_000_000_000_000:
                number /= 1000.0
            return number if number > 1_000_000_000 else None
        text = str(value).strip()
        if not text:
            return None
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            text = f"{text}T00:00:00+00:00"
        elif text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0.0 else None


def sec_user_agent() -> str:
    """Return the configured SEC identification header without secrets."""
    return str(os.getenv("ASTRA_SEC_USER_AGENT") or os.getenv("SEC_USER_AGENT") or "").strip()


def normalize_sec_submissions(
    payload: Mapping[str, Any] | None,
    *,
    symbol: str,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Normalize SEC submissions metadata while preserving filing identity."""
    data = dict(payload or {}) if isinstance(payload, Mapping) else {}
    cik = _clean_cik(data.get("cik") or data.get("cik_str"))
    tickers = [str(item).strip().upper() for item in (data.get("tickers") or []) if str(item).strip()]
    exchanges = [str(item).strip().upper() for item in (data.get("exchanges") or []) if str(item).strip()]
    normalized_symbol = _clean_symbol(symbol)
    fields = {
        "company_name": str(data.get("name") or "").strip() or None,
        "exchange": exchanges[0] if len(exchanges) == 1 else None,
        "exchanges": exchanges,
        "sic": str(data.get("sic") or "").strip() or None,
        "sic_description": str(data.get("sicDescription") or "").strip() or None,
        "tickers": tickers,
        "entity_type": str(data.get("entityType") or "").strip() or None,
    }
    fields = {key: value for key, value in fields.items() if value not in (None, [], "")}
    return {
        "provider": "SEC_EDGAR",
        "source": "SEC_EDGAR_SUBMISSIONS",
        "symbol": normalized_symbol,
        "cik": cik or None,
        "record_id": f"SEC:{cik}:{normalized_symbol}" if cik else None,
        "response_state": "SUCCESS" if (cik or fields) else "MALFORMED_RESPONSE",
        "normalized_fields": fields,
        "retrieved_at": str(retrieved_at or _now_iso()),
        "filing_provenance": {
            "cik": cik or None,
            "source_url_family": "data.sec.gov/submissions",
            "identity_source": "SEC_EDGAR",
        },
        "secret_exposed": False,
    }


def _concept_field(taxonomy: str, concept: str) -> str | None:
    for field, aliases in SEC_FACT_ALIASES.items():
        if (taxonomy, concept) in aliases:
            return field
    return None


def normalize_sec_companyfacts(
    payload: Mapping[str, Any] | None,
    *,
    symbol: str,
    cik: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Keep required SEC XBRL facts as period-specific provenance rows.

    No incompatible fiscal periods are flattened into a single value.  A
    downstream consumer must select a period explicitly and can fail closed
    when the records are ambiguous.
    """
    data = dict(payload or {}) if isinstance(payload, Mapping) else {}
    facts_root = data.get("facts") if isinstance(data.get("facts"), Mapping) else {}
    rows_by_field: dict[str, list[dict[str, Any]]] = {field: [] for field in SEC_FACT_ALIASES}
    normalized_symbol = _clean_symbol(symbol)
    normalized_cik = _clean_cik(cik or data.get("cik"))
    for taxonomy, concepts in facts_root.items():
        if not isinstance(concepts, Mapping):
            continue
        taxonomy_name = str(taxonomy or "").strip()
        for concept, definition in concepts.items():
            field = _concept_field(taxonomy_name, str(concept))
            if not field or not isinstance(definition, Mapping):
                continue
            units = definition.get("units") if isinstance(definition.get("units"), Mapping) else {}
            for unit, unit_rows in units.items():
                if not isinstance(unit_rows, list):
                    continue
                for raw in unit_rows:
                    if not isinstance(raw, Mapping) or "val" not in raw:
                        continue
                    start = str(raw.get("start") or "").strip() or None
                    end = str(raw.get("end") or "").strip() or None
                    filed = str(raw.get("filed") or "").strip() or None
                    row = {
                        "symbol": normalized_symbol,
                        "field": field,
                        "taxonomy": taxonomy_name,
                        "concept": str(concept),
                        "unit": str(unit),
                        "value": raw.get("val"),
                        "start": start,
                        "end": end,
                        "filed": filed,
                        "fiscal_year": raw.get("fy"),
                        "fiscal_period": raw.get("fp"),
                        "form": str(raw.get("form") or "").strip() or None,
                        "frame": str(raw.get("frame") or "").strip() or None,
                        "accession": str(raw.get("accn") or "").strip() or None,
                        "period_kind": "duration" if start and end else "instant" if end else "unknown",
                        "provenance": {
                            "provider": "SEC_EDGAR",
                            "cik": normalized_cik or None,
                            "filed": filed,
                            "fiscal_year": raw.get("fy"),
                            "fiscal_period": raw.get("fp"),
                            "form": str(raw.get("form") or "").strip() or None,
                            "accession": str(raw.get("accn") or "").strip() or None,
                            "source_url_family": "data.sec.gov/api/xbrl/companyfacts",
                        },
                    }
                    rows_by_field[field].append(row)
    available = {field: rows for field, rows in rows_by_field.items() if rows}
    return {
        "provider": "SEC_EDGAR",
        "source": "SEC_EDGAR_COMPANYFACTS",
        "symbol": normalized_symbol,
        "cik": normalized_cik or None,
        "response_state": "SUCCESS" if available else "NO_USABLE_FACTS",
        "facts_by_field": available,
        "fact_fields_available": sorted(available),
        "fact_count": sum(len(rows) for rows in available.values()),
        "retrieved_at": str(retrieved_at or _now_iso()),
        "secret_exposed": False,
    }


def build_sec_company_context(
    submissions_payload: Mapping[str, Any] | None,
    companyfacts_payload: Mapping[str, Any] | None,
    *,
    symbol: str,
    cik: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Combine SEC identity and raw fact records for an existing consumer."""
    at = str(retrieved_at or _now_iso())
    submissions = normalize_sec_submissions(submissions_payload, symbol=symbol, retrieved_at=at)
    resolved_cik = _clean_cik(cik or submissions.get("cik"))
    facts = normalize_sec_companyfacts(companyfacts_payload, symbol=symbol, cik=resolved_cik, retrieved_at=at)
    normalized_fields = dict(submissions.get("normalized_fields") or {})
    normalized_fields["fact_fields_available"] = list(facts.get("fact_fields_available") or [])
    return {
        "provider": "SEC_EDGAR",
        "source": "SEC_EDGAR_COMPANY_CONTEXT",
        "symbol": _clean_symbol(symbol),
        "cik": resolved_cik or None,
        "response_state": "SUCCESS" if submissions.get("response_state") == "SUCCESS" and facts.get("response_state") == "SUCCESS" else "PARTIAL",
        "normalized_fields": normalized_fields,
        "submissions": submissions,
        "companyfacts": facts,
        "retrieved_at": at,
        "secret_exposed": False,
    }


def select_sec_fact(
    records: list[Mapping[str, Any]] | None,
    *,
    period_kind: str | None = None,
) -> dict[str, Any] | None:
    """Select one unambiguous latest-filed fact without mixing periods."""
    candidates = [dict(row) for row in (records or []) if isinstance(row, Mapping)]
    if period_kind:
        candidates = [row for row in candidates if row.get("period_kind") == period_kind]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (str(row.get("filed") or ""), str(row.get("end") or "")), reverse=True)
    latest_filed = str(candidates[0].get("filed") or "")
    latest = [row for row in candidates if str(row.get("filed") or "") == latest_filed]
    values = {repr(row.get("value")) for row in latest}
    if len(values) != 1:
        return None
    return latest[0]


def derive_market_cap_from_sec(
    shares_fact: Mapping[str, Any] | None,
    quote: Mapping[str, Any] | None,
    *,
    max_alignment_seconds: float | None = 86_400.0,
) -> dict[str, Any]:
    """Derive advisory market cap only when source dates can be aligned."""
    shares = _positive((shares_fact or {}).get("value"))
    price = _positive((quote or {}).get("price"))
    shares_at = _iso_epoch((shares_fact or {}).get("end") or (shares_fact or {}).get("filed"))
    price_at = _iso_epoch(
        (quote or {}).get("provider_native_timestamp")
        or (quote or {}).get("provider_quote_timestamp")
        or (quote or {}).get("quote_timestamp")
    )
    if shares is None or price is None:
        return {"state": "UNRESOLVED", "reason": "missing_positive_shares_or_price", "execution_authority": "DISABLED"}
    if shares_at is None or price_at is None:
        return {"state": "UNRESOLVED", "reason": "missing_source_dates", "execution_authority": "DISABLED"}
    if max_alignment_seconds is not None and abs(price_at - shares_at) > max(0.0, float(max_alignment_seconds)):
        return {"state": "UNRESOLVED", "reason": "source_dates_not_aligned", "execution_authority": "DISABLED"}
    return {
        "state": "DERIVED",
        "market_cap": shares * price,
        "provider": "ASTRA_DERIVED",
        "source": "SEC_EDGAR_SHARES_X_ALPACA_CANONICAL_PRICE",
        "source_dates": {"shares": (shares_fact or {}).get("end") or (shares_fact or {}).get("filed"), "price": (quote or {}).get("provider_native_timestamp") or (quote or {}).get("quote_timestamp")},
        "provenance": {"shares": dict(shares_fact or {}), "quote": {key: (quote or {}).get(key) for key in ("symbol", "provider_name", "provider_used", "price", "quote_timestamp", "provider_native_timestamp")}},
        "execution_authority": "DISABLED",
        "use_for_entry_eligibility": False,
    }


RequestFn = Callable[..., tuple[dict[str, Any], int | None, str, float]]


class SecEdgarAdapter:
    """Bounded SEC client used through ProviderRouter's request owner."""

    def __init__(self, request_fn: RequestFn | None = None, *, user_agent: str | None = None) -> None:
        self._request_fn = request_fn
        self._user_agent = str(user_agent if user_agent is not None else sec_user_agent()).strip()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept-Encoding": "gzip"}

    def _request(self, url: str) -> tuple[dict[str, Any], int | None, str, float, bool]:
        now = datetime.now(UTC).timestamp()
        cached = self._cache.get(url)
        if cached and cached[0] > now:
            return dict(cached[1]), 200, "", 0.0, True
        if self._request_fn is not None:
            data, status, error, latency = self._request_fn(url, headers=self._headers())
        else:
            try:
                response = requests.get(url, headers=self._headers(), timeout=SEC_TIMEOUT_SECONDS)
                status = int(response.status_code)
                data = response.json() if response.content else {}
                error = "" if status < 400 else f"http_{status}"
                latency = 0.0
            except Exception as exc:  # pragma: no cover - network safety path
                return {}, None, str(exc)[:160], 0.0, False
        payload = dict(data or {}) if isinstance(data, Mapping) else {}
        if status and int(status) < 400 and payload:
            ttl = SEC_TICKER_CACHE_SECONDS if url == SEC_TICKER_MAP_URL else SEC_CONTEXT_CACHE_SECONDS
            self._cache[url] = (now + ttl, payload)
        return payload, status, str(error or ""), float(latency or 0.0), False

    def fetch_company_context(self, symbol: str, *, cik: str | None = None) -> dict[str, Any]:
        normalized_symbol = _clean_symbol(symbol)
        base = {
            "provider": "SEC_EDGAR",
            "source": "SEC_EDGAR_COMPANY_CONTEXT",
            "symbol": normalized_symbol,
            "secret_exposed": False,
        }
        if not normalized_symbol:
            return {**base, "response_state": "INVALID_SYMBOL"}
        if not self._user_agent:
            return {**base, "response_state": "CONFIGURATION_REQUIRED", "reason": "sec_user_agent_missing"}
        resolved_cik = _clean_cik(cik)
        if not resolved_cik:
            ticker_payload, status, error, _latency, _cache_hit = self._request(SEC_TICKER_MAP_URL)
            if int(status or 0) >= 400 or not ticker_payload:
                return {**base, "response_state": "PROVIDER_UNAVAILABLE", "http_status": status, "reason": error or "ticker_map_unavailable"}
            entries = ticker_payload.values() if isinstance(ticker_payload, Mapping) else []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                if _clean_symbol(entry.get("ticker")) == normalized_symbol:
                    resolved_cik = _clean_cik(entry.get("cik_str") or entry.get("cik"))
                    break
        if not resolved_cik:
            return {**base, "response_state": "SYMBOL_NOT_MAPPED", "reason": "sec_cik_not_found"}
        submissions_url = f"{SEC_DATA_BASE_URL}/submissions/CIK{resolved_cik}.json"
        facts_url = f"{SEC_DATA_BASE_URL}/api/xbrl/companyfacts/CIK{resolved_cik}.json"
        submissions, sub_status, sub_error, _sub_latency, _sub_cache = self._request(submissions_url)
        facts, facts_status, facts_error, _facts_latency, _facts_cache = self._request(facts_url)
        if int(sub_status or 0) >= 400 or int(facts_status or 0) >= 400:
            return {**base, "response_state": "PROVIDER_UNAVAILABLE", "cik": resolved_cik, "http_status": sub_status or facts_status, "reason": sub_error or facts_error or "sec_request_failed"}
        submission_identity = normalize_sec_submissions(submissions, symbol=normalized_symbol, retrieved_at=_now_iso())
        submission_tickers = set(str(item).upper() for item in (submission_identity.get("normalized_fields") or {}).get("tickers") or [])
        if submission_tickers and normalized_symbol not in submission_tickers:
            return {**base, "response_state": "MALFORMED_RESPONSE", "cik": resolved_cik, "reason": "sec_symbol_mismatch"}
        return build_sec_company_context(submissions, facts, symbol=normalized_symbol, cik=resolved_cik)
