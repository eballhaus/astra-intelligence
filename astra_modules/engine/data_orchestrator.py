# -*- coding: utf-8 -*-
"""
Astra Intelligence — Data Orchestrator (Guardian v7 Integrated)
---------------------------------------------------------------
Bridges AstraAPI (multi-API client) with dashboard and agents.
"""

from astra_modules.engine.rate_safe_fetcher import rate_safe_get
from astra_modules.guardian.security import api_keys
from astra_modules.guardian.guardian_v7 import guardian_log
from astra_modules.engine.rate_safe_fetcher import rate_safe_get, time
import requests
import time
from datetime import datetime

import pandas as pd

from core.api_client import AstraAPI
from core.guardian.guardian_v7 import guardian_log


class DataOrchestrator:
    """Unified interface for live Astra data with Guardian audit logging."""

    def __init__(self):
        self.api = AstraAPI()

    def get_live_market_data(self, symbols=None):
        if symbols is None:
            symbols = ["BTC/USD", "AAPL", "SPY"]

        frames = []
        guardian.log(
            f"[DataOrchestrator] 🧠 Initiating live data pull for {len(symbols)} symbols."
        )

        for sym in symbols:
            start_time = time.time()
            try:
                df = self.api.get_data(sym)
                latency = round(time.time() - start_time, 3)

                if df is not None and not df.empty:
                    df["symbol"] = sym
                    df["latency_s"] = latency
                    frames.append(df)
                    guardian.log(
                        f"[DataOrchestrator] ✅ {sym} fetched successfully "
                        f"(rows={len(df)}, latency={latency}s)"
                    )
                else:
                    guardian.warn(
                        f"[DataOrchestrator] ⚠️ Empty DataFrame returned for {sym}"
                    )
            except Exception as e:
                guardian.error(
                    f"[DataOrchestrator] ❌ Failed to fetch {sym}: {e}")

        if not frames:
            guardian.error(
                "[DataOrchestrator] ❌ No data frames returned from any API."
            )
            return pd.DataFrame(
                columns=["symbol", "price", "change", "timestamp", "latency_s"]
            )

        combined = pd.concat(frames, ignore_index=True)
        combined["timestamp"] = datetime.utcnow()

        if "close" in combined.columns:
            combined["price"] = combined["close"]

        if "open" in combined.columns and "close" in combined.columns:
            try:
                combined["change"] = (
                    (combined["close"] - combined["open"]) / combined["open"]
                ) * 100
            except Exception as e:
                guardian.warn(f"[DataOrchestrator] ⚠️ Change% issue: {e}")
                combined["change"] = 0.0
        else:
            combined["change"] = 0.0

        for col in ["price", "change"]:
            if col in combined.columns:
                combined[col] = pd.to_numeric(
                    combined[col], errors="coerce").fillna(0)

        guardian.log(
            f"[DataOrchestrator] 🧩 Aggregation complete — {len(combined)} rows, "
            f"{combined['symbol'].nunique()} symbols."
        )
        return combined[["symbol", "price", "change", "timestamp", "latency_s"]]


# ============================================================
# 🧠 ASTRA INTELLIGENCE — Multi-API Smart Feed Extension
# Integrates Moralis (crypto) + TwelveData + Finnhub + Alpha Vantage fallback
# ============================================================


API_ORDER = ["moralis", "twelvedata", "finnhub", "alphavantage"]


def get_data(symbol, asset_type="stock"):
    """Unified data access with fallback rotation."""
    for api in API_ORDER:
        try:
            if asset_type == "crypto" and api == "moralis":
                return get_crypto_moralis(symbol)
            elif api == "twelvedata":
                return get_stock_twelvedata(symbol)
            elif api == "finnhub":
                return get_stock_finnhub(symbol)
            elif api == "alphavantage":
                return get_stock_alphavantage(symbol)
        except Exception as e:
            guardian_log(
                f"[DataOrchestrator] {api.upper()} failed for {symbol}: {e}")
            continue
    guardian_log(f"[DataOrchestrator] ❌ All APIs failed for {symbol}")
    return None


# ------------------------- Individual Handlers -------------------------


def get_crypto_moralis(symbol: str):
    """Fetch live crypto price from Moralis API v2.3."""
    url = f"https://deep-index.moralis.io/api/v2.3/market-data/token-prices?symbols={symbol}&vsCurrency=usd"
    headers = {"X-API-Key": api_keys.MORALIS_API_KEY}
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    price = list(data.values())[0].get("usd")
    guardian_log(f"[Moralis] {symbol}/USD → {price}")
    return price


def get_stock_twelvedata(symbol: str):
    """Fetch price and change from TwelveData."""
    base = "https://api.twelvedata.com"
    params = {"symbol": symbol, "apikey": api_keys.TWELVEDATA_API_KEY}
    p = requests.get(f"{base}/price", params=params, timeout=10).json()
    q = requests.get(f"{base}/quote", params=params, timeout=10).json()
    price = p.get("price")
    change = q.get("percent_change")
    guardian_log(f"[TwelveData] {symbol} → {price} ({change}%)")
    return {"price": price, "change": change}


def get_stock_finnhub(symbol: str):
    """Fetch latest quote from Finnhub."""
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_keys.FINNHUB_API_KEY}"
    r = requests.get(url, timeout=10).json()
    price = r.get("c")
    change = r.get("dp")
    guardian_log(f"[Finnhub] {symbol} → {price} ({change}%)")
    return {"price": price, "change": change}


def get_stock_alphavantage(symbol: str):
    """Fetch daily close price from Alpha Vantage."""
    url = f"https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": api_keys.ALPHA_VANTAGE_API_KEY,
    }
    r = requests.get(url, params=params, timeout=10).json()
    latest = next(iter(r.get("Time Series (Daily)", {}).values()), {})
    price = latest.get("4. close")
    guardian_log(f"[AlphaVantage] {symbol} → {price}")
    return {"price": price}


# ============================================================
# 🔁 ASTRA SELF-HEALING DATA FETCH SYSTEM (Crypto + Stocks)
# ============================================================


def get_crypto_price(symbol: str):
    """Fetch crypto price with caching and backup API fallback to avoid rate limits."""
    import time

    import requests

    from astra_modules.guardian.guardian_v7 import guardian_log

    api_keys = __import__(
        "astra_modules.guardian.security.api_keys", fromlist=[""])
    _cache = getattr(get_crypto_price, "_cache", {})
    now = time.time()

    # ✅ Reuse cached price if less than 60 seconds old
    if symbol in _cache and now - _cache[symbol]["time"] < 60:
        guardian_log(
            f"[Cache] {symbol} reused cached price: {_cache[symbol]['price']}")
        return {"price": _cache[symbol]["price"]}

    # --- PRIMARY: TwelveData ---
    try:
        td_key = getattr(api_keys, "TWELVE_DATA_API_KEY", None)
        r = rate_safe_get(
            "https://api.twelvedata.com/price",
            params={"symbol": f"{symbol}/USD", "apikey": td_key},
        )
        data = r.json()
        price = float(data.get("price", 0))
        if price:
            guardian_log(f"[TwelveData] {symbol} → {price}")
            _cache[symbol] = {"price": price, "time": now}
            get_crypto_price._cache = _cache
            return {"price": price}
    except Exception as e:
        guardian_log(f"[TwelveData] ❌ {symbol} failed: {e}")

    # --- BACKUP: Moralis (if available) ---
    try:
        moralis_key = getattr(api_keys, "MORALIS_API_KEY", None)
        headers = {"X-API-Key": moralis_key} if moralis_key else {}
        url = f"https://deep-index.moralis.io/api/v2.3/market-data/token-price"
        params = {"symbol": symbol, "vsCurrency": "usd"}
        r = requests.get(url, headers=headers, params=params, timeout=5)
        data = r.json()
        price = data.get("price") or data.get("usdPrice")
        if price:
            guardian_log(f"[Moralis] {symbol} → {price}")
            _cache[symbol] = {"price": price, "time": now}
            get_crypto_price._cache = _cache
            return {"price": price}
    except Exception as e:
        guardian_log(f"[Moralis] ❌ {symbol} failed: {e}")

    guardian_log(f"[DataOrchestrator] ❌ All sources failed for {symbol}")
    return {"price": None}

    """Fetch crypto price using hybrid fallback."""

    import requests

    from astra_modules.guardian.guardian_v7 import guardian_log

    api_keys = __import__(
        "astra_modules.guardian.security.api_keys", fromlist=[""])

    # Try CoinMarketCap first
    try:
        cmc_key = getattr(api_keys, "COINMARKETCAP_API_KEY", None)
        headers = {"X-CMC_PRO_API_KEY": cmc_key} if cmc_key else {}
        r = requests.get(
            f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol}&convert=USD",
            headers=headers,
            timeout=5,
        )
        data = r.json()
        price = (
            data.get("data", {})
            .get(symbol, {})
            .get("quote", {})
            .get("USD", {})
            .get("price")
        )
        if price:
            guardian_log(f"[CMC] {symbol} → {price}")
            return {"price": price}
    except Exception as e:
        guardian_log(f"[CMC] ❌ {symbol} failed: {e}")

    # Try TwelveData next
    try:
        td_key = getattr(api_keys, "TWELVE_DATA_API_KEY", None)
        r = rate_safe_get(
            "https://api.twelvedata.com/price",
            params={"symbol": f"{symbol}/USD", "apikey": td_key},
        )
        data = r.json()
        price = data.get("price")
        if price:
            guardian_log(f"[TwelveData] {symbol} → {price}")
            return {"price": price}
    except Exception as e:
        guardian_log(f"[TwelveData] ❌ {symbol} failed: {e}")

    guardian_log(f"[DataOrchestrator] ❌ All sources failed for {symbol}")
    return {"price": None}
    symbol = symbol.upper()
    headers = {"X-API-Key": api_keys.MORALIS_API_KEY}
    moralis_url = f"https://deep-index.moralis.io/api/v2.3/market-data/token-price"
    params = {"pairAddress": f"{pair}"}

    # Try Moralis
    try:
        r = requests.get(moralis_url, headers=headers,
                         params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            price = data.get("price")
            if price:
                guardian_log(f"[Moralis] {symbol} → {price}")
                return float(price)
        else:
            guardian_log(f"[Moralis] ⚠️ {symbol} HTTP {r.status_code}")
    except Exception as e:
        guardian_log(f"[Moralis] ❌ {symbol} failed: {e}")

    # Try CoinMarketCap (fallback)
    try:
        cmc_url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        headers = {"X-CMC_PRO_API_KEY": api_keys.COINMARKETCAP_API_KEY}
        params = {"symbol": symbol, "convert": "USD"}
        r = requests.get(cmc_url, headers=headers, params=params, timeout=8)
        if r.status_code == 200:
            data = r.json()
            price = data["data"][symbol]["quote"]["USD"]["price"]
            guardian_log(f"[CMC] {symbol} → {round(price, 4)}")
            return float(price)
        else:
            guardian_log(f"[CMC] ⚠️ {symbol} HTTP {r.status_code}")
    except Exception as e:
        guardian_log(f"[CMC] ❌ {symbol} failed: {e}")

    # Final fallback → TwelveData
    try:
        td_url = "https://api.twelvedata.com/price"
        params = {"symbol": f"{symbol}/USD",
                  "apikey": api_keys.TWELVE_DATA_API_KEY}
        r = requests.get(td_url, params=params, timeout=8)
        data = r.json()
        price = data.get("price")
        if price:
            guardian_log(f"[TwelveData] {symbol} → {price}")
            return float(price)
    except Exception as e:
        guardian_log(f"[TwelveData] ❌ {symbol} failed: {e}")

    guardian_log(f"[DataOrchestrator] ❌ All sources failed for {symbol}")
    return None


# ============================================================
# 🧠 Moralis Symbol Mapper (BTC → bitcoin-usd)
# ============================================================

PAIR_MAP = {
    "BTC": "bitcoin-usd",
    "ETH": "ethereum-usd",
    "SOL": "solana-usd",
    "BNB": "binancecoin-usd",
    "ADA": "cardano-usd",
    "AVAX": "avalanche-usd",
    "XRP": "ripple-usd",
    "DOGE": "dogecoin-usd",
}


def get_crypto_price(symbol: str):
    """Fetch crypto price with caching and backup API fallback to avoid rate limits."""
    import time

    import requests

    from astra_modules.guardian.guardian_v7 import guardian_log

    api_keys = __import__(
        "astra_modules.guardian.security.api_keys", fromlist=[""])
    _cache = getattr(get_crypto_price, "_cache", {})
    now = time.time()

    # ✅ Reuse cached price if less than 60 seconds old
    if symbol in _cache and now - _cache[symbol]["time"] < 60:
        guardian_log(
            f"[Cache] {symbol} reused cached price: {_cache[symbol]['price']}")
        return {"price": _cache[symbol]["price"]}

    # --- PRIMARY: TwelveData ---
    try:
        td_key = getattr(api_keys, "TWELVE_DATA_API_KEY", None)
        r = rate_safe_get(
            "https://api.twelvedata.com/price",
            params={"symbol": f"{symbol}/USD", "apikey": td_key},
        )
        data = r.json()
        price = float(data.get("price", 0))
        if price:
            guardian_log(f"[TwelveData] {symbol} → {price}")
            _cache[symbol] = {"price": price, "time": now}
            get_crypto_price._cache = _cache
            return {"price": price}
    except Exception as e:
        guardian_log(f"[TwelveData] ❌ {symbol} failed: {e}")

    # --- BACKUP: Moralis (if available) ---
    try:
        moralis_key = getattr(api_keys, "MORALIS_API_KEY", None)
        headers = {"X-API-Key": moralis_key} if moralis_key else {}
        url = f"https://deep-index.moralis.io/api/v2.3/market-data/token-price"
        params = {"symbol": symbol, "vsCurrency": "usd"}
        r = requests.get(url, headers=headers, params=params, timeout=5)
        data = r.json()
        price = data.get("price") or data.get("usdPrice")
        if price:
            guardian_log(f"[Moralis] {symbol} → {price}")
            _cache[symbol] = {"price": price, "time": now}
            get_crypto_price._cache = _cache
            return {"price": price}
    except Exception as e:
        guardian_log(f"[Moralis] ❌ {symbol} failed: {e}")

    guardian_log(f"[DataOrchestrator] ❌ All sources failed for {symbol}")
    return {"price": None}

    """Fetch crypto price using hybrid fallback."""

    import requests

    from astra_modules.guardian.guardian_v7 import guardian_log

    api_keys = __import__(
        "astra_modules.guardian.security.api_keys", fromlist=[""])

    # Try CoinMarketCap first
    try:
        cmc_key = getattr(api_keys, "COINMARKETCAP_API_KEY", None)
        headers = {"X-CMC_PRO_API_KEY": cmc_key} if cmc_key else {}
        r = requests.get(
            f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol}&convert=USD",
            headers=headers,
            timeout=5,
        )
        data = r.json()
        price = (
            data.get("data", {})
            .get(symbol, {})
            .get("quote", {})
            .get("USD", {})
            .get("price")
        )
        if price:
            guardian_log(f"[CMC] {symbol} → {price}")
            return {"price": price}
    except Exception as e:
        guardian_log(f"[CMC] ❌ {symbol} failed: {e}")

    # Try TwelveData next
    try:
        td_key = getattr(api_keys, "TWELVE_DATA_API_KEY", None)
        r = rate_safe_get(
            "https://api.twelvedata.com/price",
            params={"symbol": f"{symbol}/USD", "apikey": td_key},
        )
        data = r.json()
        price = data.get("price")
        if price:
            guardian_log(f"[TwelveData] {symbol} → {price}")
            return {"price": price}
    except Exception as e:
        guardian_log(f"[TwelveData] ❌ {symbol} failed: {e}")

    guardian_log(f"[DataOrchestrator] ❌ All sources failed for {symbol}")
    return {"price": None}
    symbol = symbol.upper()
    pair = PAIR_MAP.get(symbol, f"{symbol.lower()}-usd")

    headers = {"X-API-Key": api_keys.MORALIS_API_KEY}
    moralis_url = "https://deep-index.moralis.io/api/v2.3/market-data/token-price"
    params = {"pairAddress": pair}
    ...
