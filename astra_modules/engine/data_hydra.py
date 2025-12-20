from astra_modules.engine.rate_safe_fetcher import rate_safe_get
from astra_modules.guardian import security as api_keys
from astra_modules.guardian.guardian_v7 import guardian_log


# ------------------------------
# 🔷 STOCK FUNDAMENTALS & NEWS
# ------------------------------
def get_stock_meta(symbol):
    """Fetch fundamentals & news for stocks (DataJockey + Finnhub + EODHD)."""
    result = {}
    try:
        dj_key = getattr(api_keys, "DATAJOCKEY_API_KEY", None)
        if dj_key:
            data = rate_safe_get(
                "https://api.datajockey.io/v0/company/financials",
                params={"ticker": symbol, "apikey": dj_key},
            )
            result["fundamentals"] = data.get("data", {})
            guardian_log(f"[Hydra:DataJockey] {symbol} fundamentals ok")
    except Exception as e:
        guardian_log(f"[Hydra:DataJockey] ❌ {symbol} failed: {e}")

    try:
        fh_key = getattr(api_keys, "FINNHUB_API_KEY", None)
        if fh_key:
            news = rate_safe_get(
                "https://finnhub.io/api/v1/company-news",
                params={
                    "symbol": symbol,
                    "from": "2024-12-01",
                    "to": "2024-12-15",
                    "token": fh_key,
                },
            )
            if isinstance(news, list):
                result["news"] = news[:5]
            guardian_log(f"[Hydra:FinnhubNews] {symbol} ok")
    except Exception as e:
        guardian_log(f"[Hydra:FinnhubNews] ❌ {symbol} failed: {e}")

    return result


# ------------------------------
# 🟠 CRYPTO SENTIMENT & VOLUME
# ------------------------------
def get_crypto_meta(symbol):
    """Fetch sentiment, on-chain volume, and risk data for crypto."""
    result = {}
    try:
        pg_key = getattr(api_keys, "POLYGON_API_KEY", None)
        if pg_key:
            data = rate_safe_get(
                f"https://api.polygon.io/v2/aggs/ticker/X:{symbol}USD/prev",
                params={"apiKey": pg_key},
            )
            vol = data.get("results", [{}])[0].get("v")
            if vol:
                result["volume"] = vol
            guardian_log(f"[Hydra:Polygon] {symbol} volume ok")
    except Exception as e:
        guardian_log(f"[Hydra:Polygon] ❌ {symbol} volume failed: {e}")

    try:
        sim_key = getattr(api_keys, "SIMFIN_API_KEY", None)
        if sim_key:
            sdata = rate_safe_get(
                "https://api.simfin.com/api/v2/companies/list",
                params={"api-key": sim_key},
            )
            result["sentiment"] = (
                len(sdata.get("data", [])) % 100 / 100
            )  # placeholder normalization
            guardian_log(f"[Hydra:SimFin] {symbol} sentiment ok")
    except Exception as e:
        guardian_log(f"[Hydra:SimFin] ❌ {symbol} sentiment failed: {e}")

    return result


# ------------------------------
# 🧠 GLOBAL MARKET SENTIMENT
# ------------------------------
def get_market_sentiment():
    """Fetch Fear & Greed Index and macro sentiment."""
    result = {}
    try:
        data = rate_safe_get(
            "https://api.alternative.me/fng/", params={"limit": 1})
        fng = data.get("data", [{}])[0]
        result["fear_greed_index"] = int(fng.get("value", 50))
        result["fear_greed_text"] = fng.get("value_classification", "Neutral")
        guardian_log(
            f"[Hydra:FNG] Index {result['fear_greed_index']} ({result['fear_greed_text']})"
        )
    except Exception as e:
        guardian_log(f"[Hydra:FNG] ❌ failed: {e}")
    return result
