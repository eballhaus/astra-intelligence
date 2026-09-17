"""Bounded equity discovery inventory and rotation.

This owner manages symbols and discovery provenance only. It never creates
market evidence or promotes a symbol into a tradable candidate: the existing
quote, ranking, and qualification owners remain authoritative.
"""

from __future__ import annotations

import json
import os
import threading
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
ALPACA_UNIVERSE_TTL_SECONDS = 86_400
DEFAULT_BROAD_OBSERVATION_REFRESH_SECONDS = 60
DEFAULT_BROAD_OBSERVATION_BATCH_SIZE = 100
MAX_BROAD_OBSERVATION_SYMBOLS = 3_000

LANE_DISCOVERY_LANES = ("SCALP", "DAY", "SWING")
LANE_HOT_LIST_LIMITS = {"SCALP": 150, "DAY": 150, "SWING": 300}
LANE_DEEP_ANALYSIS_LIMITS = {"SCALP": 20, "DAY": 25, "SWING": 25}
HOT_LIST_HOLD_SECONDS = 600

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
        self.lane_hot_list_path = self.state_dir / "lane_aware_discovery_v1.json"
        self.broad_observation_path = self.state_dir / "broad_live_observations_v1.json"
        self._last_status: dict[str, Any] = {}
        self._provider_router = ProviderRouter() if ProviderRouter is not None else None
        self._observation_lock = threading.RLock()
        self._observation_thread: threading.Thread | None = None
        self._observation_rows: list[dict[str, Any]] = []
        self._observation_status: dict[str, Any] = {
            "status": "NOT_STARTED",
            "observation_role": "BROAD_DISCOVERY_TIER0",
            "observation_authority": False,
            "executable_evidence": False,
        }
        self._observation_publisher: Any = None

    def set_observation_publisher(self, publisher: Any) -> None:
        """Attach the existing worker-owned observation publisher only."""
        self._observation_publisher = publisher if callable(publisher) else None

    @staticmethod
    def _provider_timestamp_epoch(value: Any) -> float | None:
        try:
            text = str(value or "").strip()
            if not text:
                return None
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return None
            return parsed.astimezone(timezone.utc).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _normalize_snapshot_row(cls, raw: dict[str, Any], *, received_at: float) -> dict[str, Any] | None:
        symbol = _norm_symbol(raw.get("symbol"))
        snapshot = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else {}
        quote = snapshot.get("latestQuote") if isinstance(snapshot.get("latestQuote"), dict) else {}
        trade = snapshot.get("latestTrade") if isinstance(snapshot.get("latestTrade"), dict) else {}
        minute = snapshot.get("minuteBar") if isinstance(snapshot.get("minuteBar"), dict) else {}
        timestamps = [
            (quote.get("t"), "quote"),
            (trade.get("t"), "trade"),
            (minute.get("t"), "bar"),
        ]
        timestamps = [(value, kind, cls._provider_timestamp_epoch(value)) for value, kind in timestamps]
        timestamps = [(value, kind, epoch) for value, kind, epoch in timestamps if epoch is not None]
        if not symbol or not timestamps:
            return None
        native_value, native_kind, native_epoch = max(timestamps, key=lambda item: item[2])
        bid = _to_float(quote.get("bp"), 0.0)
        ask = _to_float(quote.get("ap"), 0.0)
        trade_price = _to_float(trade.get("p"), 0.0)
        price = trade_price or ((bid + ask) / 2.0 if bid > 0.0 and ask > 0.0 else _to_float(minute.get("c"), 0.0))
        if price <= 0.0:
            return None
        bar_close = _to_float(minute.get("c"), 0.0)
        previous_close = _to_float((snapshot.get("prevDailyBar") or {}).get("c"), 0.0)
        age = max(0.0, received_at - native_epoch)
        return {
            "symbol": symbol,
            "price": price,
            "bid": bid or None,
            "ask": ask or None,
            "spread": round(ask - bid, 8) if bid > 0.0 and ask >= bid else None,
            "trade_price": trade_price or None,
            "trade_size": _to_float(trade.get("s"), 0.0) or None,
            "open": _to_float(minute.get("o"), 0.0) or None,
            "high": _to_float(minute.get("h"), 0.0) or None,
            "low": _to_float(minute.get("l"), 0.0) or None,
            "close": bar_close or None,
            "volume": _to_float(minute.get("v"), 0.0) or None,
            "change_percent": round(((bar_close - previous_close) / previous_close) * 100.0, 6) if bar_close > 0.0 and previous_close > 0.0 else None,
            "provider_native_timestamp": str(native_value),
            "provider_native_timestamp_kind": native_kind,
            "receive_timestamp": received_at,
            "quote_age_seconds": round(age, 3),
            "freshness_state": "CURRENT" if age <= 120.0 else "STALE",
            "provider": "ALPACA_SIP_BROAD_SNAPSHOT",
            "provider_used": "ALPACA_SIP_BROAD_SNAPSHOT",
            "provider_provenance": "ALPACA_SIP_BATCH_SNAPSHOT",
            "observation_role": "BROAD_DISCOVERY_TIER0",
            "observation_authority": False,
            "discovery_only": True,
            "executable_evidence": False,
            "candidate_evidence_fabricated": False,
        }

    def current_broad_observation_rows(self) -> list[dict[str, Any]]:
        with self._observation_lock:
            if self._observation_rows:
                rows = [dict(row) for row in self._observation_rows]
            else:
                rows = []
        if not rows:
            payload = _safe_read_json(self.broad_observation_path, {})
            rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, dict)] if isinstance(payload, dict) else []
        return [
            row for row in rows
            if str(row.get("freshness_state") or "").upper() == "CURRENT"
            and _to_float(row.get("quote_age_seconds"), 10_000.0) <= 120.0
        ]

    def _write_observation_state(self, *, rows: list[dict[str, Any]], status: dict[str, Any]) -> None:
        payload = {
            "schema_version": "astra_broad_live_observations_v1",
            "generated_at": _now_iso(),
            "rows": rows[:MAX_BROAD_OBSERVATION_SYMBOLS],
            "status": dict(status),
            "observation_authority": False,
            "executable_evidence": False,
            "broker_actions_added": 0,
        }
        _safe_write_json(self.broad_observation_path, payload)

    def _refresh_broad_observations(self, symbols: list[str]) -> None:
        started = time.perf_counter()
        received_at = time.time()
        inventory = self._refresh_alpaca_universe(
            _safe_read_json(self.cache_path, {}), received_at
        )
        provider_symbols = [
            _norm_symbol(symbol) for symbol in inventory.get("alpaca_symbols") or []
            if _norm_symbol(symbol)
        ]
        target_symbols = provider_symbols or symbols
        fetcher = getattr(self._provider_router, "fetch_alpaca_stock_snapshots", None)
        result = fetcher(
            target_symbols[:MAX_BROAD_OBSERVATION_SYMBOLS],
            feed="sip",
            batch_size=max(1, min(100, _to_int(os.getenv("ASTRA_BROAD_OBSERVATION_BATCH_SIZE"), DEFAULT_BROAD_OBSERVATION_BATCH_SIZE))),
        ) if callable(fetcher) else {"ok": False, "error": "provider_snapshot_method_unavailable", "rows": []}
        normalized = []
        for raw in result.get("rows") or []:
            row = self._normalize_snapshot_row(raw, received_at=received_at)
            if row is not None:
                normalized.append(row)
        status = {
            "status": "CURRENT" if normalized else "FAILED_NO_OBSERVATIONS",
            "last_refresh_at": _now_iso(),
            "symbols_requested": len(target_symbols[:MAX_BROAD_OBSERVATION_SYMBOLS]),
            "symbols_observed": len(normalized),
            "symbols_deferred": max(0, len(target_symbols) - len(target_symbols[:MAX_BROAD_OBSERVATION_SYMBOLS])),
            "master_universe_size": len(target_symbols),
            "inventory_source": "alpaca_active_tradable" if provider_symbols else "existing_cached_inventory",
            "provider_calls": _to_int(result.get("provider_calls"), 0),
            "batches": _to_int(result.get("batches"), 0),
            "response_bytes": _to_int(result.get("response_bytes"), 0),
            "errors": list(result.get("errors") or [])[:16],
            "refresh_elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "observation_role": "BROAD_DISCOVERY_TIER0",
            "observation_authority": False,
            "executable_evidence": False,
            "broker_actions_added": 0,
        }
        with self._observation_lock:
            self._observation_rows = normalized
            self._observation_status = status
        if self._observation_publisher is not None:
            try:
                self._observation_publisher(normalized)
            except Exception:
                status["publisher_error"] = "canonical_observation_publisher_failed"
        self._write_observation_state(rows=normalized, status=status)

    def schedule_broad_observation_refresh(
        self,
        symbols: Iterable[str],
        *,
        resource_state: str = "",
        cycle_elapsed_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Schedule one background batch refresh; never block the worker cycle."""
        if str(os.getenv("ASTRA_PROCESS_ROLE", "api") or "api").strip().lower() != "worker":
            return {"status": "NOT_WORKER", "scheduled": False}
        state = str(resource_state or "").upper()
        elapsed = _to_float(cycle_elapsed_seconds, 0.0)
        if state in {"RESOURCE_CRITICAL", "CRITICAL", "RESOURCE_STOPPED"} or elapsed >= 18.0:
            return {"status": "THROTTLED_RESOURCE", "scheduled": False, "resource_state": state, "cycle_elapsed_seconds": elapsed}
        normalized = sorted({_norm_symbol(symbol) for symbol in symbols if _norm_symbol(symbol)})
        if not normalized:
            return {"status": "NO_SYMBOLS", "scheduled": False}
        now = time.time()
        refresh_seconds = max(30.0, min(900.0, _to_float(os.getenv("ASTRA_BROAD_OBSERVATION_REFRESH_SECONDS"), DEFAULT_BROAD_OBSERVATION_REFRESH_SECONDS)))
        with self._observation_lock:
            running = self._observation_thread is not None and self._observation_thread.is_alive()
            last_refresh = self._provider_timestamp_epoch(self._observation_status.get("last_refresh_at")) or 0.0
            if running or (last_refresh and now - last_refresh < refresh_seconds):
                return {"status": "RUNNING" if running else "COOLDOWN", "scheduled": False, "symbols": len(normalized)}
            self._observation_status = {**self._observation_status, "status": "SCHEDULED", "scheduled_at": _now_iso(), "symbols_requested": min(len(normalized), MAX_BROAD_OBSERVATION_SYMBOLS)}
            thread = threading.Thread(target=self._refresh_broad_observations, args=(normalized,), name="astra-broad-observation", daemon=True)
            self._observation_thread = thread
            thread.start()
        return {"status": "SCHEDULED", "scheduled": True, "symbols": len(normalized)}

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
        for key in (
            "alpaca_symbols",
            "alpaca_universe_attempted_ts",
            "alpaca_universe_last_updated",
            "alpaca_universe_error",
            "alpaca_universe_provider_rows",
        ):
            if key in cached:
                payload[key] = cached[key]
        _safe_write_json(self.cache_path, payload)
        return payload

    def _refresh_alpaca_universe(self, cached: dict[str, Any], now: float) -> dict[str, Any]:
        """Add active Alpaca inventory without replacing the FMP contract."""
        existing = dict(cached or {})
        attempted = _to_float(existing.get("alpaca_universe_attempted_ts"), 0.0)
        retry_ttl = ALPACA_UNIVERSE_TTL_SECONDS if existing.get("alpaca_symbols") else 300.0
        if attempted and now - attempted < retry_ttl:
            return existing
        fetcher = getattr(self._provider_router, "fetch_alpaca_tradable_equity_assets", None)
        if not callable(fetcher):
            return existing
        result = fetcher()
        symbols = sorted({
            _norm_symbol(row.get("symbol"))
            for row in result.get("rows") or []
            if isinstance(row, dict)
            and bool(row.get("tradable", True))
            and str(row.get("status") or "active").lower() == "active"
            and _is_equity_inventory_symbol(_norm_symbol(row.get("symbol")))
        })
        existing.update({
            "alpaca_symbols": symbols[:MAX_BROAD_OBSERVATION_SYMBOLS],
            "alpaca_universe_attempted_ts": now,
            "alpaca_universe_last_updated": _now_iso() if symbols else str(existing.get("alpaca_universe_last_updated") or ""),
            "alpaca_universe_error": str(result.get("error") or "")[:160],
            "alpaca_universe_provider_rows": len(result.get("rows") or []),
        })
        _safe_write_json(self.cache_path, existing)
        return existing

    def _build_universe(self, *, allow_provider_refresh: bool = False) -> dict[str, Any]:
        cached = _safe_read_json(self.cache_path, {})
        now = time.time()
        if not isinstance(cached, dict):
            cached = {}
        if allow_provider_refresh:
            cached = self._refresh_alpaca_universe(cached, now)
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
            symbols.extend(_norm_symbol(s) for s in cached.get("alpaca_symbols") or [])
            symbols = sorted({s for s in symbols if s})
            symbols = [s for s in symbols if s]
            return {
                "symbols": symbols,
                "source": "+".join(filter(None, (str(cached.get("universe_source") or "local_cache"), "alpaca_active_tradable" if cached.get("alpaca_symbols") else ""))),
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
        alpaca_symbols = [_norm_symbol(s) for s in cached.get("alpaca_symbols") or []] if isinstance(cached, dict) else []
        symbols = sorted(set(symbols).union(s for s in alpaca_symbols if s))
        payload = {
            "symbols": symbols,
            "universe_source": source,
            "universe_last_updated": _now_iso(),
            "updated_ts": now,
            "alpaca_symbols": alpaca_symbols,
            "alpaca_universe_attempted_ts": _to_float(cached.get("alpaca_universe_attempted_ts"), 0.0) if isinstance(cached, dict) else 0.0,
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

    def market_discovery_from_canonical_rows_v1(
        self,
        rows: Iterable[dict[str, Any]] | None,
        *,
        now_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Route future SIP rows through this owner's existing mover cache.

        The current FMP refresh remains the compatibility path until the paid
        SIP cutover. This method is a dormant handoff contract, not a provider
        call and not executable candidate authority.
        """
        combined: dict[str, dict[str, Any]] = {}
        results = {}
        for mode in ("biggest_gainers", "most_actives"):
            result = derive_alpaca_sip_market_discovery_v1(
                rows, mode=mode, limit=MARKET_DISCOVERY_LIMIT, now_timestamp=now_timestamp,
            )
            results[mode] = result
            for raw in result.get("rows") or []:
                symbol = _norm_symbol(raw.get("symbol"))
                if not symbol:
                    continue
                candidate = dict(raw)
                existing = combined.get(symbol)
                if existing is None or self._market_priority(candidate) > self._market_priority(existing):
                    combined[symbol] = candidate
        ordered = sorted(combined.values(), key=self._market_priority, reverse=True)[:MARKET_DISCOVERY_LIMIT]
        payload = {
            "updated_ts": float(now_timestamp if now_timestamp is not None else time.time()),
            "updated_at": _now_iso(),
            "rows": ordered,
            "provider": "ALPACA_SIP",
            "source": "alpaca_sip_derived_market_discovery",
            "gainers_status": results["biggest_gainers"].get("status"),
            "most_actives_status": results["most_actives"].get("status"),
            "executable_evidence": False,
            "candidate_evidence_fabricated": False,
        }
        return {**payload, "cache_hit": False, "cache_age_seconds": 0.0}

    def reference_universe_from_canonical_rows_v1(
        self,
        rows: Iterable[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Apply the current universe filter to future Alpaca references."""
        return build_alpaca_reference_universe_v1(rows, limit=AUTHORITATIVE_UNIVERSE_LIMIT)

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

    @staticmethod
    def _lane_from_existing_row(row: dict[str, Any]) -> str:
        lane = str(
            row.get("lane_ranked_entry_lane")
            or row.get("lane_id")
            or row.get("lane")
            or ""
        ).upper().strip()
        if lane in LANE_DISCOVERY_LANES:
            return lane
        horizon = str(row.get("best_horizon_style") or row.get("trade_horizon_style") or "").lower().strip()
        return {"scalp": "SCALP", "day_trade": "DAY", "swing_trade": "SWING"}.get(horizon, "")

    @staticmethod
    def _row_is_current_lane_evidence(row: dict[str, Any]) -> bool:
        if not bool(row.get("lane_ranked_entry_funnel_v1")):
            return False
        if not bool(row.get("qualified") or row.get("eligible")):
            return False
        freshness = str(
            row.get("candidate_snapshot_freshness")
            or row.get("candidate_freshness_status")
            or row.get("freshness_state")
            or ""
        ).upper()
        return not any(token in freshness for token in ("STALE", "EXPIRED", "MISSING", "INVALID", "REJECTED"))

    @staticmethod
    def _lane_rank(row: dict[str, Any]) -> int | None:
        for key in ("lane_finalist_rank", "lane_shortlist_rank"):
            value = _to_int(row.get(key), 0)
            if value > 0:
                return value
        return None

    def _discovery_capacity(self, *, resource_state: str = "", cycle_elapsed_seconds: float | None = None) -> dict[str, Any]:
        """Keep discovery bounded without changing trading-critical limits."""
        state = str(resource_state or "").upper().strip()
        elapsed = _to_float(cycle_elapsed_seconds, 0.0) if cycle_elapsed_seconds is not None else 0.0
        if state in {"RESOURCE_CRITICAL", "CRITICAL", "RESOURCE_STOPPED"}:
            factor = 0.0
        elif state in {"RESOURCE_ELEVATED", "ELEVATED", "RESOURCE_DEGRADED"} or elapsed >= 18.0:
            factor = 0.25
        elif elapsed >= 16.0:
            factor = 0.5
        else:
            factor = 1.0
        hot_limits = {
            lane: int(LANE_HOT_LIST_LIMITS[lane] * factor) for lane in LANE_DISCOVERY_LANES
        }
        deep_limits = {
            lane: min(LANE_DEEP_ANALYSIS_LIMITS[lane], hot_limits[lane])
            for lane in LANE_DISCOVERY_LANES
        }
        return {
            "resource_state": state or "UNKNOWN",
            "cycle_elapsed_seconds": round(elapsed, 3) if cycle_elapsed_seconds is not None else None,
            "discovery_capacity_factor": factor,
            "hot_list_limits": hot_limits,
            "deep_analysis_limits": deep_limits,
        }

    def build_lane_aware_discovery_v1(
        self,
        rows: Iterable[dict[str, Any]] | None = None,
        *,
        master_universe_size: int = 0,
        rotation_size: int = 0,
        resource_state: str = "",
        cycle_elapsed_seconds: float | None = None,
        now_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Index current canonical lane evidence without creating candidates.

        Inventory and mover rows only schedule/describe discovery. A symbol
        enters a lane hot list here only when the existing allocator has
        already attached a lane, ranking, qualification, and current evidence.
        This keeps the broad funnel observational until a canonical observation
        publisher is available for the rotated inventory slice.
        """
        now = float(now_timestamp if now_timestamp is not None else time.time())
        now_iso = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
        capacity = self._discovery_capacity(
            resource_state=resource_state,
            cycle_elapsed_seconds=cycle_elapsed_seconds,
        )
        previous = _safe_read_json(self.lane_hot_list_path, {})
        previous_by_key: dict[str, dict[str, Any]] = {}
        for lane_rows in (previous.get("hot_lists") or {}).values() if isinstance(previous, dict) else ():
            for record in lane_rows or ():
                if not isinstance(record, dict):
                    continue
                key = f"{str(record.get('lane') or '').upper()}:{_norm_symbol(record.get('symbol'))}"
                if key.split(":", 1)[0] in LANE_DISCOVERY_LANES and key.split(":", 1)[1]:
                    previous_by_key[key] = record

        candidates: dict[str, dict[str, dict[str, Any]]] = {lane: {} for lane in LANE_DISCOVERY_LANES}
        rejected = Counter()
        for raw in rows or ():
            if not isinstance(raw, dict):
                continue
            symbol = _norm_symbol(raw.get("symbol"))
            lane = self._lane_from_existing_row(raw)
            if not symbol or not lane:
                rejected["missing_symbol_or_lane"] += 1
                continue
            if not self._row_is_current_lane_evidence(raw):
                rejected["not_current_qualified_lane_evidence"] += 1
                continue
            score_value = raw.get("lane_ranked_entry_score")
            if score_value in (None, ""):
                rejected["missing_existing_lane_score"] += 1
                continue
            score = _to_float(score_value, 0.0)
            rank = self._lane_rank(raw)
            key = f"{lane}:{symbol}"
            prior = dict(previous_by_key.get(key) or {})
            prior_score = prior.get("eligibility_score")
            material_score_change = round(score - _to_float(prior_score, score), 3) if prior_score not in (None, "") else None
            selected_at_epoch = _discovery_timestamp_epoch(prior.get("selected_at")) or now
            expires_epoch = _discovery_timestamp_epoch(prior.get("expires_at"))
            if expires_epoch is None or expires_epoch <= now:
                expires_epoch = now + HOT_LIST_HOLD_SECONDS
                selected_at_epoch = now
            record = {
                "symbol": symbol,
                "lane": lane,
                "source_lane": lane,
                "eligibility_score": round(score, 3),
                "rank": rank,
                "reason": str(
                    raw.get("candidate_discovery_reason")
                    or raw.get("candidate_opportunity_type")
                    or raw.get("candidate_source")
                    or "EXISTING_CANONICAL_LANE_RANKING"
                ),
                "first_seen": str(prior.get("first_seen") or now_iso),
                "last_seen": now_iso,
                "latest_refresh": now_iso,
                "selected_at": datetime.fromtimestamp(selected_at_epoch, timezone.utc).isoformat().replace("+00:00", "Z"),
                "expires_at": datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat().replace("+00:00", "Z"),
                "freshness": str(
                    raw.get("candidate_snapshot_freshness")
                    or raw.get("candidate_freshness_status")
                    or raw.get("freshness_state")
                    or "CURRENT"
                ),
                "source_provenance": raw.get("source_provenance") or raw.get("candidate_source") or "paper_opportunity_allocation_engine_v1",
                "candidate_id": str(raw.get("candidate_id") or raw.get("recommendation_id") or ""),
                "managed_position": bool(raw.get("managed_position")),
                "material_score_change": material_score_change,
                "discovery_only": True,
                "executable_evidence": False,
                "execution_authority": False,
                "candidate_evidence_fabricated": False,
            }
            prior_record = candidates[lane].get(symbol)
            if prior_record is None or _to_float(record.get("eligibility_score"), 0.0) > _to_float(prior_record.get("eligibility_score"), 0.0):
                candidates[lane][symbol] = record

        hot_lists: dict[str, list[dict[str, Any]]] = {}
        for lane in LANE_DISCOVERY_LANES:
            ordered = sorted(
                candidates[lane].values(),
                key=lambda record: (
                    _to_float(record.get("eligibility_score"), 0.0),
                    -(record.get("rank") or 9999),
                    str(record.get("symbol") or ""),
                ),
                reverse=True,
            )
            bounded = ordered[: capacity["hot_list_limits"][lane]]
            for index, record in enumerate(bounded, start=1):
                record["current_rank"] = index
            hot_lists[lane] = bounded

        payload = {
            "schema_version": "astra_lane_aware_discovery_v1",
            "version": VERSION,
            "generated_at": now_iso,
            "hot_lists": hot_lists,
            "active_symbols": sorted({record["symbol"] for values in hot_lists.values() for record in values}),
            "total_count": sum(len(values) for values in hot_lists.values()),
            "per_lane_count": {lane: len(hot_lists[lane]) for lane in LANE_DISCOVERY_LANES},
            "eligible_count": {lane: len(candidates[lane]) for lane in LANE_DISCOVERY_LANES},
            "hot_list_churn_count": len(
                {
                    f"{record.get('lane')}:{record.get('symbol')}"
                    for values in hot_lists.values() for record in values
                }.symmetric_difference(set(previous_by_key))
            ),
            "master_universe_size": max(0, int(master_universe_size)),
            "symbols_scheduled_for_tier0": max(0, int(rotation_size)),
            "symbols_scanned_this_cycle": 0,
            "tier0_scan_method": "cached_canonical_observations_and_deterministic_rotation_only",
            "deep_analysis_target": capacity["deep_analysis_limits"],
            "resource_capacity": capacity,
            "rejected_rows": dict(rejected),
            "multiple_lane_symbol_count": sum(
                1 for symbol in {record["symbol"] for values in hot_lists.values() for record in values}
                if sum(1 for values in hot_lists.values() if any(row["symbol"] == symbol for row in values)) > 1
            ),
            "bounded": True,
            "discovery_only": True,
            "candidate_evidence_fabricated": False,
            "broker_actions_added": 0,
            "trading_policy_changed": False,
        }
        _safe_write_json(self.lane_hot_list_path, payload)
        return payload

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

    def cached_inventory_symbols(self) -> list[str]:
        """Return inventory without doing provider I/O from the cycle path."""
        return [
            symbol
            for symbol in (self._build_universe(allow_provider_refresh=False).get("symbols") or [])
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
        broad_rows = self.current_broad_observation_rows()
        rotation = self.select_rotation(known_rows=rows, market_rows=broad_rows)
        status = dict(rotation["status"])
        actual_rows = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        lane_discovery = self.build_lane_aware_discovery_v1(
            actual_rows,
            master_universe_size=_to_int(status.get("broad_universe_size"), 0),
            rotation_size=_to_int(status.get("rotation_size"), 0),
        )
        lane_discovery["symbols_scanned_this_cycle"] = len(broad_rows)
        lane_discovery["tier0_scan_method"] = (
            "alpaca_sip_batch_snapshots_worker_owned"
            if broad_rows else "alpaca_sip_batch_snapshots_pending"
        )
        lane_discovery["observation_status"] = dict(self._observation_status)
        lane_counts = dict(lane_discovery.get("eligible_count") or {})
        hot_list_counts = dict(lane_discovery.get("per_lane_count") or {})
        status.update({
            "symbols_scanned_this_cycle": 0,
            "lightweight_scored_count": 0,
            "shortlist_count": 0,
            "candidates_detected": len(actual_rows),
            "actual_candidate_rows_observed": len(actual_rows),
            "promoted_symbols": [],
            "api_calls_used": 0,
            "tier0_scan_method": lane_discovery.get("tier0_scan_method"),
            "tier0_symbols_scheduled": lane_discovery.get("symbols_scheduled_for_tier0", 0),
            "tier0_symbols_observed": len(broad_rows),
            "tier0_symbols_deferred": max(0, _to_int(status.get("broad_universe_size"), 0) - len(broad_rows)),
            "tier0_observation_method": "alpaca_sip_batch_snapshots_worker_owned" if broad_rows else "alpaca_sip_batch_snapshots_pending",
            "tier0_observation_status": dict(self._observation_status),
            "lane_eligible_counts": lane_counts,
            "lane_hot_list_sizes": hot_list_counts,
            "lane_hot_list_churn_count": lane_discovery.get("hot_list_churn_count", 0),
            "deep_analysis_count": 0,
            "deep_analysis_target": lane_discovery.get("deep_analysis_target", {}),
            "finalist_count": sum(
                1 for row in actual_rows
                if bool(row.get("lane_finalist")) and bool(row.get("lane_ranked_entry_funnel_v1"))
            ),
            "multiple_lane_symbol_count": lane_discovery.get("multiple_lane_symbol_count", 0),
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "lane_aware_discovery_v1": lane_discovery,
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


def _discovery_timestamp_epoch(value: Any) -> float | None:
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
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def derive_alpaca_sip_market_discovery_v1(
    rows: Iterable[dict[str, Any]] | None,
    *,
    mode: str,
    limit: int = MARKET_DISCOVERY_LIMIT,
    max_quote_age_seconds: float | None = None,
    now_timestamp: float | None = None,
) -> dict[str, Any]:
    """Derive bounded mover indexes from canonical Alpaca market rows.

    This helper is deliberately provider-independent at the call site: a
    future SIP publisher supplies current rows, while the existing discovery
    owner keeps custody of filtering and rotation. It only creates
    discovery evidence, never executable candidates.
    """
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"biggest_gainers", "most_actives"}:
        return {"status": "UNSUPPORTED_MODE", "mode": normalized_mode, "rows": [], "executable_evidence": False}
    bounded_limit = max(1, min(int(limit or MARKET_DISCOVERY_LIMIT), MARKET_DISCOVERY_LIMIT))
    now = float(now_timestamp if now_timestamp is not None else time.time())
    dedup: dict[str, dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        symbol = _norm_symbol(raw.get("symbol"))
        if not symbol or not BroadUniverseIntakePromotionV1._is_common_stock_discovery_row(raw):
            continue
        provider = str(raw.get("provider") or raw.get("provider_used") or "").strip().upper()
        feed = str(raw.get("feed") or raw.get("data_feed") or "").strip().upper()
        if provider not in {"ALPACA_SIP", "ALPACA_WS_SIP", "ALPACA"} and feed != "SIP":
            continue
        native_timestamp = (
            raw.get("provider_native_timestamp")
            or raw.get("provider_quote_timestamp")
            or raw.get("quote_timestamp")
            or raw.get("timestamp")
        )
        native_epoch = _discovery_timestamp_epoch(native_timestamp)
        if native_epoch is None:
            continue
        freshness_state = str(raw.get("freshness_state") or "").strip().upper()
        if freshness_state and freshness_state not in {"CURRENT", "FRESH", "VALID"}:
            continue
        if max_quote_age_seconds is not None:
            age = max(0.0, now - native_epoch)
            if age > max(0.0, float(max_quote_age_seconds)):
                continue
        price = _to_float(raw.get("price", raw.get("current_price", raw.get("close"))), 0.0)
        previous_close = _to_float(raw.get("previous_close", raw.get("prev_close")), 0.0)
        volume = _to_float(raw.get("session_volume", raw.get("volume")), 0.0)
        trade_count = _to_int(raw.get("trade_count", raw.get("trades")), 0)
        if price <= 0.0:
            continue
        if normalized_mode == "biggest_gainers":
            if previous_close <= 0.0:
                continue
            metric = ((price - previous_close) / previous_close) * 100.0
            if metric <= 0.0:
                continue
        else:
            if volume <= 0.0 and trade_count <= 0:
                continue
            metric = volume if volume > 0.0 else float(trade_count)
        candidate = {
            "symbol": symbol,
            "price": price,
            "previous_close": previous_close if previous_close > 0.0 else None,
            "volume": volume if volume > 0.0 else None,
            "trade_count": trade_count if trade_count > 0 else None,
            "change_percent": round(metric, 8) if normalized_mode == "biggest_gainers" else None,
            "activity_metric": metric,
            "provider": "ALPACA_SIP",
            "provider_native_timestamp": native_timestamp,
            "discovery_source": f"alpaca_sip_derived_{normalized_mode}",
            "candidate_discovery_source": f"alpaca_sip_derived_{normalized_mode}",
            "discovery_evidence_only": True,
            "executable_evidence": False,
            "provenance": {
                "source": "ALPACA_SIP",
                "source_timestamp": native_timestamp,
                "calculation": "session_price_change_from_previous_close" if normalized_mode == "biggest_gainers" else "session_volume_or_trade_count",
            },
        }
        prior = dedup.get(symbol)
        if prior is None or candidate["activity_metric"] > prior["activity_metric"]:
            dedup[symbol] = candidate
    ordered = sorted(
        dedup.values(),
        key=lambda row: (
            _to_float(row.get("change_percent"), 0.0) if normalized_mode == "biggest_gainers" else _to_float(row.get("activity_metric"), 0.0),
            _to_float(row.get("volume"), 0.0),
            str(row.get("symbol") or ""),
        ),
        reverse=True,
    )[:bounded_limit]
    return {
        "status": "READY" if ordered else "NO_VALID_CANONICAL_ROWS",
        "mode": normalized_mode,
        "provider": "ALPACA_SIP",
        "source": f"alpaca_sip_derived_{normalized_mode}",
        "rows": ordered,
        "executable_evidence": False,
        "candidate_evidence_fabricated": False,
    }


def build_alpaca_reference_universe_v1(
    rows: Iterable[dict[str, Any]] | None,
    *,
    limit: int = AUTHORITATIVE_UNIVERSE_LIMIT,
) -> dict[str, Any]:
    """Apply the existing liquid-common-stock filter to canonical references.

    The current FMP refresh remains unchanged. This pure handoff contract is
    for a later Alpaca asset/reference cutover and cannot create evidence.
    """
    bounded_limit = max(1, min(int(limit or AUTHORITATIVE_UNIVERSE_LIMIT), AUTHORITATIVE_UNIVERSE_LIMIT))
    accepted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        provider = str(row.get("provider") or row.get("source") or "").strip().upper()
        if provider not in {"ALPACA", "ALPACA_REFERENCE", "ALPACA_SIP"}:
            continue
        row["symbol"] = _norm_symbol(row.get("symbol"))
        if not row["symbol"] or row["symbol"] in seen:
            continue
        # Accept canonical reference aliases without changing the existing
        # filter thresholds or its common-stock semantics.
        row.setdefault("marketCap", row.get("market_cap"))
        row.setdefault("price", row.get("last_price", row.get("current_price")))
        row.setdefault("volume", row.get("session_volume"))
        if "active" in row:
            row["isActivelyTrading"] = row.get("active")
        if "is_etf" in row:
            row["isEtf"] = row.get("is_etf")
        if "is_fund" in row:
            row["isFund"] = row.get("is_fund")
        if not BroadUniverseIntakePromotionV1._is_liquid_common_stock(row):
            continue
        seen.add(row["symbol"])
        accepted.append(row)
    accepted.sort(key=lambda row: str(row.get("symbol") or ""))
    symbols = [str(row["symbol"]) for row in accepted[:bounded_limit]]
    return {
        "status": "READY" if symbols else "NO_VALID_CANONICAL_ROWS",
        "symbols": symbols,
        "rows": accepted[:bounded_limit],
        "source": "ALPACA_REFERENCE_EXISTING_LIQUID_COMMON_STOCK_FILTER",
        "provider": "ALPACA_REFERENCE",
        "authoritative": bool(symbols),
        "candidate_evidence_fabricated": False,
    }
