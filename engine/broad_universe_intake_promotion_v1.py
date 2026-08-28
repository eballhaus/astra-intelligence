"""Bounded equity discovery inventory and rotation.

This owner manages symbols and discovery provenance only. It never creates
market evidence or promotes a symbol into a tradable candidate: the existing
quote, ranking, and qualification owners remain authoritative.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from engine.provider_router import ProviderRouter
except Exception:  # pragma: no cover - offline import safety
    ProviderRouter = None  # type: ignore[assignment]

VERSION = "1.0.0"
FMP_BANDWIDTH_LIMIT_GB = 50.0
FMP_BUDGET_TARGET_PCT = 75.0
FMP_BUDGET_SOFT_LIMIT_PCT = 80.0
FMP_BUDGET_HARD_STOP_PCT = 80.0
FMP_CALLS_PER_MINUTE_LIMIT = 250
DEFAULT_ROTATION_SIZE = 24
MAX_ROTATION_SIZE = 30
DEFAULT_ROTATION_SECONDS = 300
AUTHORITATIVE_UNIVERSE_TTL_SECONDS = 86_400
MARKET_DISCOVERY_TTL_SECONDS = 300
AUTHORITATIVE_UNIVERSE_LIMIT = 650
MARKET_DISCOVERY_LIMIT = 250

# A compact built-in seed keeps the engine useful offline. Larger local or
# provider-backed universes replace this automatically when available.
BUILTIN_US_EQUITY_SEED = """
AAPL MSFT NVDA AMZN META GOOGL GOOG TSLA AVGO AMD INTC QCOM MU ARM SMCI TSM ASML AMAT LRCX KLAC MRVL
CRM ORCL ADBE NOW SNOW NET DDOG MDB PLTR U CRWD ZS PANW FTNT OKTA SHOP SQ PYPL COIN HOOD
JPM BAC WFC C GS MS SCHW CBOE ICE CME BLK BX KKR AXP V MA DFS COF SOFI AFRM UPST
LLY NVO UNH JNJ ABBV MRK PFE BMY AMGN GILD REGN VRTX MRNA BIIB ISRG TMO DHR SYK BSX
XOM CVX COP SLB HAL OXY EOG DVN FANG MRO MPC VLO PSX LNG ENPH FSLR SEDG
WMT COST HD LOW TGT TJX ROST NKE LULU SBUX MCD CMG YUM DPZ CAVA ELF ULTA
NFLX DIS ROKU SPOT WBD PARA EA TTWO PINS SNAP RDDT MTCH UBER LYFT DASH ABNB BKNG EXPE
CAT DE GE HON MMM RTX LMT NOC BA TXT UPS FDX UNP CSX NSC ETN EMR PH GEHC
NEE SO DUK AEP EXC SRE D XEL PCG PEG ED WEC AWK
PG KO PEP MDLZ KHC CL KMB GIS HSY PM MO CELH MNST STZ
LIN SHW APD ECL FCX NEM SCCO ALB NUE STLD CLF AA MOS CF
SPY QQQ IWM DIA XLK XLF XLE XLV XLY XLI XLP XLU XLB XLC SMH SOXX ARKK
RIVN LCID F GM TM HMC STLA NIO LI XPEV RACE
AI PATH SOUN BBAI IONQ RGTI QBTS LAES SERV RXRX TEM
MARA RIOT CLSK HUT BITF WULF IREN MSTR
HOOD DKNG PENN MGM WYNN LVS CZR RBLX SE BILI TME
RKT OPEN RDFN Z PTON BYND CHWY W GME AMC BB NOK
ASTS RKLB LUNR PL ACHR JOBY ENVX QS STEM BE BLDP PLUG RUN
SOUN AEHR ALGM MP WOLF ON MCHP NXPI SWKS QRVO TER COHR
FSLY TWLO DOCU ZM TEAM WDAY INTU ANET CSCO IBM HPQ DELL HPE
TGTX VKTX ALT NTRA EXAS IOVA CRSP EDIT NTLA BEAM BLUE SAVA
CELH DUOL CART INST ARMK WING TXRH BJ FIVE BROS
ONON DECK CROX BIRK SKX GOLF VFC LEVI
CCL RCL NCLH DAL UAL AAL LUV JBLU SAVE
CHPT BLNK EVGO BEEM NKLA ARVL GOEV MULN FFIE
TGTX HALO NBIX SRPT ALNY RARE BPMC FATE IMVT
CAVA SG ULCC TOST BILL GLBE FOUR PAYO MQ
""".split()

SECTOR_HINTS = {
    "AAPL": "technology", "MSFT": "technology", "NVDA": "technology", "AMD": "technology", "AVGO": "technology",
    "META": "communication_services", "GOOGL": "communication_services", "GOOG": "communication_services", "NFLX": "communication_services",
    "JPM": "financials", "BAC": "financials", "WFC": "financials", "GS": "financials", "MS": "financials",
    "LLY": "healthcare", "UNH": "healthcare", "JNJ": "healthcare", "MRK": "healthcare", "PFE": "healthcare",
    "XOM": "energy", "CVX": "energy", "OXY": "energy", "SLB": "energy", "MPC": "energy",
    "WMT": "consumer_defensive", "COST": "consumer_defensive", "PG": "consumer_defensive", "KO": "consumer_defensive", "PEP": "consumer_defensive",
    "HD": "consumer_cyclical", "LOW": "consumer_cyclical", "TSLA": "consumer_cyclical", "NKE": "consumer_cyclical", "SBUX": "consumer_cyclical",
    "CAT": "industrials", "DE": "industrials", "GE": "industrials", "BA": "industrials", "HON": "industrials",
    "NEE": "utilities", "DUK": "utilities", "SO": "utilities", "AEP": "utilities",
    "LIN": "materials", "FCX": "materials", "NEM": "materials", "ALB": "materials", "NUE": "materials",
}

MEGA = {"AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AVGO", "LLY", "JPM", "XOM", "WMT"}
LARGE = {"AMD", "NFLX", "ORCL", "CRM", "ADBE", "COST", "HD", "BAC", "UNH", "V", "MA", "JNJ", "CVX", "MRK", "ABBV", "NOW", "QCOM", "INTC", "IBM"}
SMALL_HINTS = {"SOUN", "BBAI", "IONQ", "RGTI", "QBTS", "LUNR", "ACHR", "JOBY", "ENVX", "PLUG", "BLNK", "EVGO", "OPEN", "RKT", "ASTS", "RKLB", "AEHR", "WULF", "BITF", "HUT", "LAES", "SERV"}
ETF_HINTS = {"SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLC", "SMH", "SOXX", "ARKK"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        return default
    return default


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, default=str)
        tmp.replace(path)
    except Exception:
        pass


def _norm_symbol(raw: Any) -> str:
    sym = str(raw or "").upper().strip().replace("/", "-")
    if not sym or len(sym) > 8:
        return ""
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ.-")
    if any(ch not in allowed for ch in sym):
        return ""
    if sym.endswith(".W") or sym.endswith(".U") or sym.endswith(".R"):
        return ""
    return sym


def _is_equity_inventory_symbol(symbol: str) -> bool:
    """Keep crypto ledger symbols out of the equity-discovery workload."""
    sym = _norm_symbol(symbol)
    if not sym:
        return False
    # The authoritative universe is U.S.-listed. Dot-suffixed listings such
    # as ``.TO`` are foreign listings and are not valid for this workload.
    if "." in sym:
        return False
    if sym.endswith(("-USD", "-USDT", "-EUR")):
        return False
    return sym not in {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "SHIB", "ONDO"}


class BroadUniverseIntakePromotionV1:
    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir or "state")
        self.cache_path = self.state_dir / "broad_universe_intake_promotion_v1.json"
        self.fmp_usage_path = self.state_dir / "fmp_usage_state.json"
        self.fmp_manifest_path = self.state_dir / "fmp_efficiency_manifest_v1.json"
        self.ledger_path = self.state_dir / "candidate_decision_ledger_v1.jsonl"
        self.snapshot_path = self.state_dir / "snapshots" / "stable_top_buys_v1.json"
        self.cohort_path = self.state_dir / "adaptive_discovery_v1.json"
        self.quality_cohort_path = self.state_dir / "candidate_quality_selection_v1.json"
        self.market_snapshot_path = self.state_dir / "fmp_market_discovery_snapshot_v1.json"
        self._last_status: dict[str, Any] = {}
        self._provider_router = ProviderRouter() if ProviderRouter is not None else None

    def _existing_symbol_sources(self) -> tuple[list[str], list[str]]:
        symbols: list[str] = []
        sources: list[str] = []

        for path in (self.snapshot_path, self.state_dir / "learning_insights_last_good.json"):
            data = _safe_read_json(path, {})
            before = len(symbols)
            symbols.extend(self._symbols_from_obj(data))
            if len(symbols) > before:
                sources.append(path.name)

        try:
            if self.ledger_path.exists():
                # Discovery needs recent symbols, not a full ledger scan.
                with self.ledger_path.open("rb") as handle:
                    handle.seek(0, 2)
                    handle.seek(max(0, handle.tell() - 256_000))
                    lines = handle.read().decode("utf-8", errors="ignore").splitlines()[-500:]
                before = len(symbols)
                for line in lines:
                    try:
                        symbols.extend(self._symbols_from_obj(json.loads(line)))
                    except Exception:
                        continue
                if len(symbols) > before:
                    sources.append(self.ledger_path.name)
        except Exception:
            pass

        env_path = os.getenv("ASTRA_BROAD_UNIVERSE_SYMBOLS_PATH", "").strip()
        if env_path:
            path = Path(env_path)
            if path.exists():
                before = len(symbols)
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    if path.suffix.lower() == ".json":
                        symbols.extend(self._symbols_from_obj(json.loads(text)))
                    else:
                        for token in text.replace(",", "\n").splitlines():
                            parts = [p.strip() for p in token.split() if p.strip()]
                            symbols.extend(parts[:1])
                except Exception:
                    pass
                if len(symbols) > before:
                    sources.append(str(path))

        symbols.extend(BUILTIN_US_EQUITY_SEED)
        sources.append("builtin_us_equity_seed")
        return symbols, sources

    def _symbols_from_obj(self, obj: Any) -> list[str]:
        out: list[str] = []
        if isinstance(obj, dict):
            for key in ("symbol", "ticker"):
                if key in obj:
                    out.append(str(obj.get(key) or ""))
            for value in obj.values():
                if isinstance(value, (dict, list, tuple)):
                    out.extend(self._symbols_from_obj(value))
        elif isinstance(obj, (list, tuple)):
            for item in obj:
                out.extend(self._symbols_from_obj(item))
        elif isinstance(obj, str):
            out.append(obj)
        return out

    @staticmethod
    def _is_common_stock_discovery_row(row: dict[str, Any]) -> bool:
        symbol = _norm_symbol(row.get("symbol"))
        if not _is_equity_inventory_symbol(symbol):
            return False
        if row.get("isActivelyTrading") is False:
            return False
        if bool(row.get("isEtf")) or bool(row.get("isFund")):
            return False
        name = str(row.get("name") or row.get("companyName") or "").upper()
        if any(token in name for token in (" ETF", " FUND", " RIGHTS", " WARRANT", " UNIT", " PREFERRED")):
            return False
        exchange = str(row.get("exchangeShortName") or row.get("exchange") or "").upper()
        if exchange and any(token in exchange for token in ("TORONTO", "TSX", "LONDON", "LSE", "XETRA", "FRANKFURT", "PARIS")):
            return False
        return True

    @classmethod
    def _is_liquid_common_stock(cls, row: dict[str, Any]) -> bool:
        if not cls._is_common_stock_discovery_row(row):
            return False
        return (
            _to_float(row.get("marketCap"), 0.0) >= 1_000_000_000
            and _to_float(row.get("price"), 0.0) >= 5.0
            and _to_float(row.get("volume"), 0.0) >= 500_000
        )

    def _refresh_authoritative_universe(self, cached: dict[str, Any], now: float) -> dict[str, Any] | None:
        if self._provider_router is None:
            return None
        attempted_at = _to_float(cached.get("authoritative_attempted_ts"), 0.0) if isinstance(cached, dict) else 0.0
        if attempted_at and (now - attempted_at) < 900.0:
            return None
        result = self._provider_router.fetch_fmp_bounded_discovery(
            mode="company_screener",
            limit=AUTHORITATIVE_UNIVERSE_LIMIT,
        )
        if not result.get("ok"):
            if isinstance(cached, dict):
                cached["authoritative_attempted_ts"] = now
                cached["authoritative_last_error"] = str(result.get("error") or "unavailable")[:160]
                _safe_write_json(self.cache_path, cached)
            return None
        accepted = [row for row in (result.get("rows") or []) if self._is_liquid_common_stock(row)]
        symbols = sorted({_norm_symbol(row.get("symbol")) for row in accepted if _norm_symbol(row.get("symbol"))})
        if not symbols:
            return None
        payload = {
            "symbols": symbols[:AUTHORITATIVE_UNIVERSE_LIMIT],
            "universe_source": "fmp_company_screener_liquid_common_stock",
            "universe_last_updated": _now_iso(),
            "updated_ts": now,
            "authoritative_attempted_ts": now,
            "authoritative_last_error": "",
            "liquid_filter": {
                "market_cap_min": 1_000_000_000,
                "price_min": 5.0,
                "volume_min": 500_000,
                "exclude_etf_fund": True,
                "active_only": True,
            },
            "provider": "FMP",
            "provider_rows_received": len(result.get("rows") or []),
            "eligible_rows": len(symbols),
            "response_bytes": _to_int(result.get("response_bytes"), 0),
        }
        _safe_write_json(self.cache_path, payload)
        return payload

    def _build_universe(self, *, allow_provider_refresh: bool = False) -> dict[str, Any]:
        cached = _safe_read_json(self.cache_path, {})
        now = time.time()
        cache_ts = _to_float(cached.get("updated_ts"), 0.0) if isinstance(cached, dict) else 0.0
        is_authoritative = str(cached.get("universe_source") or "").startswith("fmp_company_screener") if isinstance(cached, dict) else False
        if allow_provider_refresh and (not is_authoritative or (now - cache_ts) >= AUTHORITATIVE_UNIVERSE_TTL_SECONDS):
            refreshed = self._refresh_authoritative_universe(cached if isinstance(cached, dict) else {}, now)
            if refreshed:
                cached = refreshed
                cache_ts = now
                is_authoritative = True
        if isinstance(cached, dict) and cached.get("symbols") and (now - cache_ts) < AUTHORITATIVE_UNIVERSE_TTL_SECONDS:
            symbols = [_norm_symbol(s) for s in cached.get("symbols") or []]
            symbols = [s for s in symbols if s]
            return {
                "symbols": symbols,
                "source": str(cached.get("universe_source") or "local_cache"),
                "cache_hit": True,
                "cache_age_seconds": round(max(0.0, now - cache_ts), 2),
                "stale": False,
                "last_updated": str(cached.get("universe_last_updated") or ""),
                "authoritative": bool(is_authoritative),
                "provider_rows_received": _to_int(cached.get("provider_rows_received"), 0),
                "liquid_filter": dict(cached.get("liquid_filter") or {}),
            }

        raw_symbols, sources = self._existing_symbol_sources()
        seen = set()
        symbols: list[str] = []
        for raw in raw_symbols:
            sym = _norm_symbol(raw)
            if not sym or sym in seen:
                continue
            seen.add(sym)
            symbols.append(sym)
        symbols = sorted(symbols)
        source = "+".join(dict.fromkeys(sources)) or "builtin_us_equity_seed"
        payload = {
            "symbols": symbols,
            "universe_source": source,
            "universe_last_updated": _now_iso(),
            "updated_ts": now,
        }
        _safe_write_json(self.cache_path, payload)
        return {
            "symbols": symbols,
            "source": source,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "stale": False,
            "last_updated": payload["universe_last_updated"],
            "authoritative": False,
            "provider_rows_received": 0,
            "liquid_filter": {},
        }

    @staticmethod
    def _market_priority(row: dict[str, Any]) -> tuple[float, float, str]:
        raw_change = row.get("changesPercentage", row.get("changePercentage", row.get("change_percent", 0.0)))
        try:
            change = abs(float(str(raw_change or "0").replace("%", "").strip()))
        except Exception:
            change = 0.0
        volume = _to_float(row.get("volume"), 0.0)
        return (change, volume, _norm_symbol(row.get("symbol")))

    def refresh_market_discovery(self) -> dict[str, Any]:
        """Fetch two compact FMP mover indexes without emitting executable data."""
        cached = _safe_read_json(self.market_snapshot_path, {})
        now = time.time()
        cached_at = _to_float(cached.get("updated_ts"), 0.0) if isinstance(cached, dict) else 0.0
        if isinstance(cached, dict) and cached.get("rows") and (now - cached_at) < MARKET_DISCOVERY_TTL_SECONDS:
            cached_rows = [
                dict(row) for row in (cached.get("rows") or [])
                if isinstance(row, dict) and self._is_common_stock_discovery_row(row)
            ]
            return {**cached, "rows": cached_rows, "cache_hit": True, "cache_age_seconds": round(now - cached_at, 2)}
        if self._provider_router is None:
            return {"rows": [], "provider": "FMP", "error": "provider_router_unavailable", "cache_hit": False}
        combined: dict[str, dict[str, Any]] = {}
        failures: list[str] = []
        calls = 0
        bytes_used = 0
        for mode, source in (("biggest_gainers", "fmp_biggest_gainers"), ("most_actives", "fmp_most_actives")):
            result = self._provider_router.fetch_fmp_bounded_discovery(mode=mode, limit=MARKET_DISCOVERY_LIMIT)
            calls += 1 if result.get("status") is not None else 0
            bytes_used += _to_int(result.get("response_bytes"), 0)
            if not result.get("ok"):
                failures.append(f"{mode}:{result.get('error') or 'unavailable'}")
                continue
            for raw in result.get("rows") or []:
                symbol = _norm_symbol(raw.get("symbol"))
                row = dict(raw)
                row["symbol"] = symbol
                if not self._is_common_stock_discovery_row(row):
                    continue
                row["discovery_source"] = source
                row["candidate_discovery_source"] = source
                row["discovery_evidence_only"] = True
                existing = combined.get(symbol)
                if existing is None or self._market_priority(row) > self._market_priority(existing):
                    combined[symbol] = row
        rows = sorted(combined.values(), key=self._market_priority, reverse=True)[:MARKET_DISCOVERY_LIMIT]
        payload = {
            "updated_ts": now,
            "updated_at": _now_iso(),
            "rows": rows,
            "provider": "FMP",
            "calls": calls,
            "response_bytes": bytes_used,
            "failures": failures,
            "executable_evidence": False,
        }
        if rows:
            _safe_write_json(self.market_snapshot_path, payload)
        return {**payload, "cache_hit": False, "cache_age_seconds": 0.0}

    def _fmp_budget(self) -> dict[str, Any]:
        usage = _safe_read_json(self.fmp_usage_path, {})
        manifest = _safe_read_json(self.fmp_manifest_path, {})
        used_gb = _to_float(
            usage.get("fmp_estimated_used_month_gb"),
            _to_float(usage.get("estimated_monthly_bandwidth_used_gb"), _to_float(usage.get("fmp_estimated_used_today_gb"), 0.0) * 30.0),
        )
        limit_gb = max(0.01, _to_float(os.getenv("FMP_MONTHLY_BANDWIDTH_GB"), _to_float(usage.get("fmp_bandwidth_limit_gb"), FMP_BANDWIDTH_LIMIT_GB)))
        usage_pct = max(0.0, min(999.0, (used_gb / limit_gb) * 100.0))
        calls_today = _to_int(usage.get("fmp_calls_today"), _to_int(manifest.get("fmp_calls_today"), 0))
        calls_per_min = _to_float(usage.get("fmp_calls_per_minute"), 0.0)
        hard_stop = bool(usage_pct >= FMP_BUDGET_HARD_STOP_PCT or usage.get("fmp_hard_stop_active"))
        if hard_stop:
            state = "hard_stopped"
        elif usage_pct >= FMP_BUDGET_SOFT_LIMIT_PCT:
            state = "throttled_at_limit"
        elif usage_pct >= FMP_BUDGET_TARGET_PCT:
            state = "approaching_soft_limit"
        elif used_gb <= 0 and calls_today <= 0:
            state = "degraded_unknown_usage"
        else:
            state = "under_utilizing"
        return {
            "fmp_usage_pct": round(usage_pct, 3),
            "fmp_bandwidth_used_gb": round(used_gb, 6),
            "fmp_bandwidth_limit_gb": round(limit_gb, 3),
            "fmp_calls_per_minute": round(calls_per_min, 3),
            "fmp_calls_per_minute_limit": FMP_CALLS_PER_MINUTE_LIMIT,
            "fmp_budget_target_pct": FMP_BUDGET_TARGET_PCT,
            "fmp_budget_soft_limit_pct": FMP_BUDGET_SOFT_LIMIT_PCT,
            "fmp_budget_hard_stop_pct": FMP_BUDGET_HARD_STOP_PCT,
            "fmp_budget_state": state,
            "fmp_nonessential_scans_allowed": not hard_stop,
        }

    @staticmethod
    def _actual_signal_score(row: dict[str, Any]) -> float | None:
        """Use only observed fields to prioritize the next discovery batch."""
        values: list[float] = []
        for key in ("confidence", "grade_percent", "momentum_score", "relative_volume_score", "liquidity_score"):
            value = row.get(key)
            if value not in (None, ""):
                values.append(max(0.0, min(100.0, _to_float(value))))
        if not values:
            return None
        age = _to_float(row.get("quote_age_seconds"), -1.0)
        return round((sum(values) / len(values)) + (4.0 if 0.0 <= age <= 120.0 else 0.0), 4)

    def _record_cohort_marker(self) -> dict[str, Any]:
        existing = _safe_read_json(self.cohort_path, {})
        if isinstance(existing, dict) and existing.get("change_id") == "ADAPTIVE_DISCOVERY_V1":
            return existing
        marker = {
            "change_id": "ADAPTIVE_DISCOVERY_V1",
            "activated_at": _now_iso(),
            "scope": ["DAY", "SCALP", "SWING"],
            "measurement_checkpoints": [10, 20, 30],
            "mode": "paper_only_discovery_provenance",
        }
        _safe_write_json(self.cohort_path, marker)
        return marker

    def _record_quality_selection_marker(self) -> dict[str, Any]:
        existing = _safe_read_json(self.quality_cohort_path, {})
        if isinstance(existing, dict) and existing.get("change_id") == "CANDIDATE_QUALITY_SELECTION_V1":
            return existing
        marker = {
            "change_id": "CANDIDATE_QUALITY_SELECTION_V1",
            "activated_at": _now_iso(),
            "scope": ["DAY", "SCALP", "SWING"],
            "measurement_checkpoints": [10, 20, 30],
            "mode": "paper_only_selection_provenance",
        }
        _safe_write_json(self.quality_cohort_path, marker)
        return marker

    def inventory_symbols(self) -> list[str]:
        """Return a normalized local symbol inventory without market claims."""
        return [
            symbol
            for symbol in (self._build_universe(allow_provider_refresh=True).get("symbols") or [])
            if _is_equity_inventory_symbol(symbol)
        ]

    def select_rotation(
        self,
        *,
        known_rows: Iterable[dict[str, Any]] | None = None,
        excluded_symbols: Iterable[str] | None = None,
        inventory_symbols: Iterable[str] | None = None,
        market_rows: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Select inventory symbols only; no candidates or quote evidence are made here."""
        universe = self._build_universe()
        budget = self._fmp_budget()
        excluded = {_norm_symbol(symbol) for symbol in (excluded_symbols or []) if _norm_symbol(symbol)}
        inventory = list(inventory_symbols or universe.get("symbols") or [])
        symbols = []
        seen = set()
        for raw in inventory:
            symbol = _norm_symbol(raw)
            if _is_equity_inventory_symbol(symbol) and symbol not in excluded and symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        requested = _to_int(os.getenv("ASTRA_DISCOVERY_ROTATION_SIZE"), DEFAULT_ROTATION_SIZE)
        rotation_size = max(8, min(MAX_ROTATION_SIZE, requested, len(symbols))) if symbols else 0
        if str(budget.get("fmp_budget_state")) in {"hard_stopped", "throttled_at_limit"}:
            rotation_size = min(rotation_size, 8)
        elif str(budget.get("fmp_budget_state")) == "approaching_soft_limit":
            rotation_size = min(rotation_size, 16)

        ranked_by_symbol: dict[str, float] = {}
        source_by_ranked_symbol: dict[str, str] = {}
        symbol_set = set(symbols)
        for row in market_rows or []:
            if not isinstance(row, dict):
                continue
            symbol = _norm_symbol(row.get("symbol"))
            if symbol not in symbol_set:
                continue
            change, volume, _ = self._market_priority(row)
            # This controls scan order only; it cannot qualify or promote an
            # entry. Mover and volume values stay discovery provenance.
            score = (change * 1_000_000.0) + min(volume, 10_000_000_000.0) / 10_000.0
            if score > ranked_by_symbol.get(symbol, -1.0):
                ranked_by_symbol[symbol] = score
                source_by_ranked_symbol[symbol] = str(row.get("discovery_source") or "fmp_market_index")
        for row in known_rows or []:
            if not isinstance(row, dict):
                continue
            symbol = _norm_symbol(row.get("symbol"))
            score = self._actual_signal_score(row)
            if symbol in symbol_set and score is not None:
                if score > ranked_by_symbol.get(symbol, -1.0):
                    ranked_by_symbol[symbol] = score
                    source_by_ranked_symbol[symbol] = str(row.get("discovery_source") or "opportunity_weighted_cached_signal")
        ranked = sorted(((score, symbol) for symbol, score in ranked_by_symbol.items()), key=lambda item: (-item[0], item[1]))
        weighted_target = min(len(ranked), int(round(rotation_size * 0.75)))
        weighted = [symbol for _, symbol in ranked[:weighted_target]]
        remaining = [symbol for symbol in symbols if symbol not in set(weighted)]
        rotation_seconds = max(60, min(900, _to_int(os.getenv("ASTRA_DISCOVERY_ROTATION_SECONDS"), DEFAULT_ROTATION_SECONDS)))
        epoch = int(time.time() // rotation_seconds)
        start = (epoch * max(1, rotation_size)) % max(1, len(remaining)) if remaining else 0
        exploration = (remaining[start:] + remaining[:start])[: max(0, rotation_size - len(weighted))]
        selected = weighted + exploration
        source_by_symbol = {
            symbol: source_by_ranked_symbol.get(symbol, "opportunity_weighted_cached_signal") if symbol in set(weighted) else "exploration_rotation"
            for symbol in selected
        }
        return {
            "symbols": selected,
            "source_by_symbol": source_by_symbol,
            "status": {
                "enabled": True,
                "version": VERSION,
                "mode": "paper_only_real_evidence_discovery",
                "broad_universe_pipeline_active": True,
                "broad_universe_size": len(inventory),
                "tradable_universe_size": len(symbols),
                "universe_source": str(universe.get("source") or "local_cache"),
                "authoritative_universe": bool(universe.get("authoritative", False)),
                "authoritative_provider_rows_received": _to_int(universe.get("provider_rows_received"), 0),
                "universe_liquid_filter": dict(universe.get("liquid_filter") or {}),
                "universe_cache_hit": bool(universe.get("cache_hit", False)),
                "universe_cache_age_seconds": _to_float(universe.get("cache_age_seconds"), 0.0),
                "universe_stale": bool(universe.get("stale", False)),
                "universe_last_updated": str(universe.get("last_updated") or ""),
                "rotation_size": len(selected),
                "opportunity_weighted_count": len(weighted),
                "exploration_count": len(exploration),
                "opportunity_weighted_percent": round((len(weighted) / max(1, len(selected))) * 100.0, 2),
                "exploration_percent": round((len(exploration) / max(1, len(selected))) * 100.0, 2),
                "known_signal_symbols": len(ranked),
                "market_index_symbols": len([row for row in (market_rows or []) if isinstance(row, dict)]),
                "excluded_duplicate_or_active_symbols": len(excluded),
                "rotation_epoch": epoch,
                "rotation_seconds": rotation_seconds,
                "deep_scored_count": 0,
                "promoted_to_top_buys_count": 0,
                "candidate_evidence_fabricated": False,
                "prospective_cohort": self._record_cohort_marker(),
                "quality_selection_cohort": self._record_quality_selection_marker(),
                **budget,
            },
        }

    def _pipeline(self, rows: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
        rotation = self.select_rotation(known_rows=rows)
        status = dict(rotation["status"])
        actual_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        status.update({
            "symbols_scanned_this_cycle": 0,
            "lightweight_scored_count": 0,
            "shortlist_count": 0,
            "candidates_detected": len(actual_rows),
            "actual_candidate_rows_observed": len(actual_rows),
            "promoted_symbols": [],
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        })
        self._last_status = dict(status)
        return {"status": status, "promoted": [], "scored": []}

    def status(self, rows: Iterable[dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        if self._last_status and not force:
            age = time.time() - _to_float(self._last_status.get("_built_ts"), 0.0)
            if 0.0 <= age < 20.0:
                out = dict(self._last_status)
                out.pop("_built_ts", None)
                out["cache_hit"] = True
                return out
        result = self._pipeline(rows=rows)
        out = dict(result["status"])
        out["_built_ts"] = time.time()
        self._last_status = dict(out)
        public = dict(out)
        public.pop("_built_ts", None)
        public["cache_hit"] = False
        return public

    def decorate_candidates(self, rows: Iterable[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        # Inventory membership is never candidate evidence.
        return [dict(row) for row in (rows or []) if isinstance(row, dict)]

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        existing_rows = self._candidate_rows_from_payload(out)
        status = dict(self._pipeline(rows=existing_rows).get("status") or {})
        out["top_buys_candidate_source"] = str(out.get("top_buys_candidate_source") or "legacy_runtime_snapshot")
        out["broad_universe_intake_promotion"] = status
        out["broad_universe_pipeline_active"] = True
        for key in (
            "broad_universe_size", "tradable_universe_size", "scan_slice_size", "candidates_detected",
            "shortlist_count", "deep_scored_count", "promoted_to_top_buys_count", "promoted_cap_distribution",
            "promoted_sector_distribution", "promoted_symbols", "fmp_budget_state",
        ):
            out[key] = status.get(key)
        return out

    def _candidate_rows_from_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key in ("rows", "top_buys"):
            value = payload.get(key)
            if isinstance(value, list):
                rows.extend([dict(r) for r in value if isinstance(r, dict)])
        for bucket in ("stocks", "crypto"):
            b = payload.get(bucket) if isinstance(payload.get(bucket), dict) else {}
            for key in ("final", "qualified", "watchlist"):
                rows.extend([dict(r) for r in (b.get(key) or []) if isinstance(r, dict)])
        dedup: dict[str, dict[str, Any]] = {}
        for row in rows:
            sym = _norm_symbol(row.get("symbol"))
            if sym and sym not in dedup:
                dedup[sym] = row
        return list(dedup.values())
