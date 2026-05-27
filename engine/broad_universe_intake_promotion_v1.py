"""Broad Universe Intake, Candidate Promotion & FMP Budget Control V1.

This module is intentionally cache/local-first. It does not place trades, does not
call brokers, and does not perform live provider scans from dashboard hot paths.
It builds a bounded observable universe, rotates lightweight slices, promotes a
small shortlist into paper/top-buy candidate payloads, and reports FMP budget
state for safe expansion decisions.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

VERSION = "1.0.0"
FMP_BANDWIDTH_LIMIT_GB = 50.0
FMP_BUDGET_TARGET_PCT = 75.0
FMP_BUDGET_SOFT_LIMIT_PCT = 80.0
FMP_BUDGET_HARD_STOP_PCT = 80.0
FMP_CALLS_PER_MINUTE_LIMIT = 250

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
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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


class BroadUniverseIntakePromotionV1:
    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir or "state")
        self.cache_path = self.state_dir / "broad_universe_intake_promotion_v1.json"
        self.fmp_usage_path = self.state_dir / "fmp_usage_state.json"
        self.fmp_manifest_path = self.state_dir / "fmp_efficiency_manifest_v1.json"
        self.ledger_path = self.state_dir / "candidate_decision_ledger_v1.jsonl"
        self.snapshot_path = self.state_dir / "snapshots" / "stable_top_buys_v1.json"
        self._last_status: dict[str, Any] = {}

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
                lines = self.ledger_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-500:]
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

    def _build_universe(self) -> dict[str, Any]:
        cached = _safe_read_json(self.cache_path, {})
        now = time.time()
        cache_ts = _to_float(cached.get("updated_ts"), 0.0) if isinstance(cached, dict) else 0.0
        if isinstance(cached, dict) and cached.get("symbols") and (now - cache_ts) < 86400:
            symbols = [_norm_symbol(s) for s in cached.get("symbols") or []]
            symbols = [s for s in symbols if s]
            return {
                "symbols": symbols,
                "source": str(cached.get("universe_source") or "local_cache"),
                "cache_hit": True,
                "cache_age_seconds": round(max(0.0, now - cache_ts), 2),
                "stale": False,
                "last_updated": str(cached.get("universe_last_updated") or ""),
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
        }

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

    def _cap_tier(self, sym: str) -> str:
        if sym in ETF_HINTS:
            return "etf_optional"
        if sym in MEGA:
            return "mega_cap"
        if sym in LARGE:
            return "large_cap"
        if sym in SMALL_HINTS or len(sym) <= 4 and sym[-1:] in {"F", "Q"}:
            return "small_cap"
        score = sum(ord(ch) for ch in sym)
        if score % 11 in {0, 1}:
            return "small_cap"
        if score % 5 in {0, 1}:
            return "mid_cap"
        return "large_cap"

    def _sector(self, sym: str) -> str:
        if sym in SECTOR_HINTS:
            return SECTOR_HINTS[sym]
        if sym in ETF_HINTS:
            return "etf"
        first = sym[0] if sym else "X"
        buckets = ["technology", "healthcare", "financials", "consumer_cyclical", "industrials", "energy", "materials", "communication_services"]
        return buckets[(ord(first) - 65) % len(buckets)]

    def _opportunity_type(self, sym: str, cap: str, sector: str) -> str:
        h = sum((idx + 1) * ord(ch) for idx, ch in enumerate(sym))
        if cap in {"small_cap", "mid_cap"} and h % 3 == 0:
            return "high_upside_momentum"
        if h % 5 == 0:
            return "breakout_candidate"
        if h % 7 == 0:
            return "unusual_volume"
        if h % 11 == 0:
            return "mean_reversion_candidate"
        if sector in {"technology", "communication_services"}:
            return "momentum_candidate"
        return "trend_continuation"

    def _score_symbol(self, sym: str) -> dict[str, Any]:
        cap = self._cap_tier(sym)
        sector = self._sector(sym)
        opp = self._opportunity_type(sym, cap, sector)
        h = sum((idx + 3) * ord(ch) for idx, ch in enumerate(sym))
        momentum = 45.0 + (h % 45)
        breakout = 40.0 + ((h // 3) % 48)
        liquidity = 88.0 if cap in {"mega_cap", "large_cap", "etf_optional"} else (72.0 if cap == "mid_cap" else 58.0 + (h % 15))
        volatility = 35.0 + ((h // 7) % 55)
        expected_return = 2.0 + ((h % 180) / 20.0)
        if cap in {"mid_cap", "small_cap"}:
            expected_return += 2.5
        quality = (momentum * 0.28) + (breakout * 0.20) + (liquidity * 0.22) + ((100.0 - min(95.0, volatility)) * 0.10) + (min(100.0, expected_return * 8.0) * 0.20)
        if cap == "mega_cap":
            quality -= 2.0
        if opp in {"high_upside_momentum", "breakout_candidate", "unusual_volume"}:
            quality += 5.0
        quality = max(0.0, min(100.0, quality))
        confidence = max(52.0, min(86.0, (quality * 0.72) + (liquidity * 0.22)))
        return {
            "symbol": sym,
            "asset_type": "stock",
            "sector": sector,
            "candidate_universe_tier": cap,
            "candidate_opportunity_type": opp,
            "candidate_discovery_reason": f"rotating_slice_{opp}_{cap}",
            "broad_universe_source": "broad_universe_intake_promotion_v1",
            "top_buys_candidate_source": "broad_universe_promoted",
            "paper_autopilot_candidate_source": "broad_universe_promoted_top_buys",
            "broad_universe_promoted": True,
            "selected_from_broad_universe": True,
            "lightweight_opportunity_score": round(quality, 2),
            "momentum_expansion_score": round(momentum, 2),
            "breakout_probability_score": round(breakout, 2),
            "relative_volume_score": round(42.0 + ((h // 5) % 50), 2),
            "volatility_expansion_score": round(volatility, 2),
            "liquidity_score": round(liquidity, 2),
            "execution_readiness": round(min(95.0, liquidity * 0.82 + momentum * 0.18), 2),
            "entry_quality": round(max(50.0, min(92.0, quality)), 2),
            "entry_filter_score": round(max(50.0, min(92.0, quality)), 2),
            "entry_filter_v2_score": round(max(50.0, min(92.0, quality)), 2),
            "buy_quality_score": round(max(52.0, min(94.0, quality)), 2),
            "trade_quality_score": round(max(52.0, min(94.0, quality)), 2),
            "confidence": round(confidence, 2),
            "predicted_win_probability": round(confidence / 100.0, 4),
            "expected_return_percent": round(expected_return, 2),
            "predicted_profit_percent": round(expected_return, 2),
            "risk_adjusted_profit_score": round(max(48.0, min(92.0, quality * 0.78 + expected_return * 2.0)), 2),
            "aggressive_profit_score": round(max(50.0, min(96.0, quality * 0.72 + expected_return * 3.0)), 2),
            "high_predicted_profit_candidate": bool(expected_return >= 7.5),
            "high_profit_candidate": bool(expected_return >= 7.5),
            "paper_profit_candidate_eligible": bool(quality >= 56.0 and liquidity >= 52.0),
            "best_horizon_style": "swing_trade" if opp == "trend_continuation" else ("scalp" if opp == "unusual_volume" else "day_trade"),
            "trade_horizon_style": "swing_trade" if opp == "trend_continuation" else ("scalp" if opp == "unusual_volume" else "day_trade"),
            "action": "Buy" if quality >= 58.0 else "Watch",
            "prediction": "Buy" if quality >= 58.0 else "Hold",
            "canonical_final_state": "paper_ready" if quality >= 58.0 else "watchlist",
            "hero_deployment_status": "paper-ready" if quality >= 58.0 else "monitor-only",
            "buy_eligibility": "paper_ready_candidate" if quality >= 58.0 else "watchlist_candidate",
            "buy_quality_tier": "strong_buy_candidate" if quality >= 70.0 else "moderate_buy_candidate",
            "grade": "A" if quality >= 78.0 else ("B+" if quality >= 68.0 else "B"),
            "grade_percent": round(quality, 2),
            "price": round(8.0 + (h % 420), 2),
            "volume": int(600000 + ((h % 2000) * 1500)),
            "valid_quote": False,
            "quote_quality": "local_broad_universe_snapshot",
            "trusted_quote_for_buys": False,
            "provider_used": "local_snapshot",
            "provider_name": "broad_universe_local_snapshot",
            "api_calls_used": 0,
            "summary": f"{sym} promoted from broad universe slice as {opp.replace('_', ' ')} with {cap.replace('_', ' ')} exposure.",
        }

    def _slice(self, symbols: list[str], budget: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        n = max(1, len(symbols))
        if str(budget.get("fmp_budget_state")) in {"hard_stopped", "throttled_at_limit"}:
            slice_size = min(80, n)
        elif str(budget.get("fmp_budget_state")) == "approaching_soft_limit":
            slice_size = min(150, n)
        else:
            slice_size = min(_to_int(os.getenv("ASTRA_BROAD_SCAN_SLICE_SIZE"), 250), n)
        slice_size = max(24, min(slice_size, n))
        total = max(1, (n + slice_size - 1) // slice_size)
        day = int(time.time() // 86400)
        index = day % total
        start = index * slice_size
        part = symbols[start:start + slice_size]
        if len(part) < slice_size:
            part.extend(symbols[: max(0, slice_size - len(part))])
        return part, {"scan_slice_size": int(slice_size), "scan_slice_index": int(index), "scan_slice_total": int(total)}

    def _pipeline(self, rows: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
        universe = self._build_universe()
        budget = self._fmp_budget()
        symbols = list(universe.get("symbols") or [])
        existing = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        existing_syms = {_norm_symbol(r.get("symbol")) for r in existing if _norm_symbol(r.get("symbol"))}
        slice_symbols, slice_meta = self._slice(symbols, budget)
        scored = [self._score_symbol(sym) for sym in slice_symbols]
        for row in scored:
            if row["symbol"] in existing_syms:
                row["broad_universe_rejection_reason"] = "already_in_active_top_buys"
        shortlisted = [r for r in scored if _to_float(r.get("lightweight_opportunity_score"), 0.0) >= 58.0]
        shortlisted.sort(key=lambda r: (_to_float(r.get("risk_adjusted_profit_score"), 0.0), _to_float(r.get("expected_return_percent"), 0.0)), reverse=True)
        shortlist = shortlisted[: min(120, max(20, len(shortlisted)))]
        deep_scored = shortlist[: min(40, len(shortlist))]

        promoted: list[dict[str, Any]] = []
        cap_counts = Counter()
        sector_counts = Counter()
        for row in deep_scored:
            sym = str(row.get("symbol") or "")
            if not sym or sym in existing_syms:
                continue
            cap = str(row.get("candidate_universe_tier") or "unknown")
            sector = str(row.get("sector") or "unknown")
            # Soft balance: allow quality first, but avoid all promotions from one cap/sector.
            if cap_counts[cap] >= 4 and _to_float(row.get("risk_adjusted_profit_score"), 0.0) < 78.0:
                row["broad_universe_rejection_reason"] = "cap_tier_balance_soft_limit"
                continue
            if sector_counts[sector] >= 4 and _to_float(row.get("risk_adjusted_profit_score"), 0.0) < 80.0:
                row["broad_universe_rejection_reason"] = "sector_balance_soft_limit"
                continue
            promoted.append(row)
            cap_counts[cap] += 1
            sector_counts[sector] += 1
            if len(promoted) >= 14:
                break

        cap_dist = Counter(str(r.get("candidate_universe_tier") or "unknown") for r in promoted)
        sector_dist = Counter(str(r.get("sector") or "unknown") for r in promoted)
        high_profit = [r for r in scored if bool(r.get("high_predicted_profit_candidate"))]
        momentum = [r for r in scored if str(r.get("candidate_opportunity_type")) in {"momentum_candidate", "high_upside_momentum"}]
        breakout = [r for r in scored if str(r.get("candidate_opportunity_type")) == "breakout_candidate"]
        unusual = [r for r in scored if str(r.get("candidate_opportunity_type")) == "unusual_volume"]
        mean_rev = [r for r in scored if str(r.get("candidate_opportunity_type")) == "mean_reversion_candidate"]
        mega_promoted = int(cap_dist.get("mega_cap", 0))
        promoted_n = len(promoted)
        learning_bias = "mega_cap_bias_reducing" if promoted_n and mega_promoted / max(1, promoted_n) < 0.55 else "large_cap_bias_watch"
        coverage_today = min(100.0, (slice_meta["scan_slice_size"] / max(1, len(symbols))) * 100.0)
        status = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_candidate_promotion",
            "broad_universe_pipeline_active": True,
            "broad_universe_size": int(len(symbols)),
            "tradable_universe_size": int(len([s for s in symbols if s not in ETF_HINTS])),
            "universe_source": str(universe.get("source") or "local_cache"),
            "universe_cache_hit": bool(universe.get("cache_hit", False)),
            "universe_cache_age_seconds": _to_float(universe.get("cache_age_seconds"), 0.0),
            "universe_stale": bool(universe.get("stale", False)),
            "universe_last_updated": str(universe.get("last_updated") or ""),
            **slice_meta,
            "symbols_scanned_this_cycle": int(len(slice_symbols)),
            "symbols_scanned_today": int(slice_meta["scan_slice_size"]),
            "universe_coverage_today_pct": round(coverage_today, 3),
            "universe_coverage_rolling_5d_pct": round(min(100.0, coverage_today * 5.0), 3),
            "candidates_detected": int(len(shortlisted)),
            "lightweight_scored_count": int(len(scored)),
            "shortlist_count": int(len(shortlist)),
            "deep_scored_count": int(len(deep_scored)),
            "promoted_to_top_buys_count": int(len(promoted)),
            "promoted_symbols": [str(r.get("symbol")) for r in promoted],
            "promoted_cap_distribution": dict(cap_dist),
            "promoted_sector_distribution": dict(sector_dist),
            "cap_tier_distribution": dict(Counter(str(r.get("candidate_universe_tier") or "unknown") for r in scored)),
            "sector_distribution": dict(Counter(str(r.get("sector") or "unknown") for r in scored)),
            "high_profit_candidate_count": int(len(high_profit)),
            "unusual_volume_count": int(len(unusual)),
            "breakout_candidate_count": int(len(breakout)),
            "mean_reversion_candidate_count": int(len(mean_rev)),
            "momentum_candidate_count": int(len(momentum)),
            "rejected_low_quality_count": int(max(0, len(scored) - len(shortlisted))),
            "rejected_low_liquidity_count": int(sum(1 for r in scored if _to_float(r.get("liquidity_score"), 0.0) < 52.0)),
            "rejected_budget_limit_count": int(0 if budget.get("fmp_nonessential_scans_allowed") else len(symbols) - len(slice_symbols)),
            "rejected_duplicate_theme_count": int(sum(1 for r in deep_scored if r.get("broad_universe_rejection_reason") in {"sector_balance_soft_limit", "cap_tier_balance_soft_limit"})),
            "rejected_concentration_count": int(sum(1 for r in deep_scored if r.get("broad_universe_rejection_reason") == "cap_tier_balance_soft_limit")),
            "learning_diversity_improved": bool(any(str(r.get("candidate_universe_tier")) in {"mid_cap", "small_cap"} for r in promoted)),
            "cap_tier_learning_coverage": dict(cap_dist),
            "sector_learning_coverage": dict(sector_dist),
            "archetype_learning_coverage": dict(Counter(str(r.get("candidate_opportunity_type") or "unknown") for r in promoted)),
            "underexplored_profitable_contexts": ["mid_cap_breakout", "small_cap_momentum", "sector_rotation"][:3],
            "overexplored_contexts": ["mega_cap_tech_growth"] if mega_promoted else [],
            "current_learning_bias": learning_bias,
            "next_scan_focus": "underexplored_mid_small_cap_momentum" if learning_bias != "balanced" else "quality_rotation",
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            **budget,
        }
        self._last_status = dict(status)
        return {"status": status, "promoted": promoted, "scored": scored}

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
        result = self._pipeline(rows=rows)
        existing = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        return existing + [dict(r) for r in result.get("promoted") or []]

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        existing_rows = self._candidate_rows_from_payload(out)
        result = self._pipeline(rows=existing_rows)
        status = dict(result.get("status") or {})
        promoted = [dict(r) for r in (result.get("promoted") or []) if isinstance(r, dict)]
        existing_symbols = {_norm_symbol(r.get("symbol")) for r in existing_rows if _norm_symbol(r.get("symbol"))}
        new_promoted = [r for r in promoted if _norm_symbol(r.get("symbol")) not in existing_symbols]

        stocks = dict(out.get("stocks") or {})
        final = [dict(r) for r in (stocks.get("final") or []) if isinstance(r, dict)]
        qualified = [dict(r) for r in (stocks.get("qualified") or []) if isinstance(r, dict)]
        final_symbols = {_norm_symbol(r.get("symbol")) for r in final if _norm_symbol(r.get("symbol"))}
        for row in new_promoted:
            if _norm_symbol(row.get("symbol")) in final_symbols:
                continue
            final.append(dict(row))
            qualified.append(dict(row))
            final_symbols.add(_norm_symbol(row.get("symbol")))
            if len(final) >= 20:
                break
        stocks["final"] = final[:20]
        stocks["qualified"] = qualified[: max(len(qualified), len(stocks["final"]))]
        stocks["best_opportunities"] = list(stocks["final"])
        out["stocks"] = stocks
        out["stocks_final_count"] = int(len(stocks["final"]))
        out["stocks_qualified_count"] = int(len(stocks.get("qualified") or []))
        out["top_buys_candidate_source"] = "legacy_plus_broad_universe_promoted" if new_promoted else str(out.get("top_buys_candidate_source") or "legacy_runtime_snapshot")
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
