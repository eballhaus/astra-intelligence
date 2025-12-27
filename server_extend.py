from fastapi import APIRouter
import requests, os, json, time

router = APIRouter()
POLYGON = os.getenv("POLYGON_API_KEY", "")
MORALIS = os.getenv("MORALIS_API_KEY", "")
STATE = "state"
TTL = 240

def cache_path(name): return os.path.join(STATE, name)
def read_cache(name):
    p = cache_path(name)
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < TTL:
        with open(p) as f: return json.load(f)
    return None
def write_cache(name, data):
    with open(cache_path(name), "w") as f: json.dump(data, f)

@router.get("/api/chart/{symbol}")
def chart(symbol: str):
    name = f"chart_{symbol.upper()}.json"
    cached = read_cache(name)
    if cached: return cached
    if "-" in symbol or symbol.upper() in ["BTC","ETH","SOL"]:
        url = f"https://deep-index.moralis.io/api/v2/market-data/ohlcv/{symbol}/?interval=5m"
        headers = {"X-API-Key": MORALIS}
    else:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/5/minute/2024-01-01/2024-12-31?apiKey={POLYGON}"
        headers = {}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        write_cache(name, data)
        return data
    except Exception as e:
        return {"error": str(e)}

@router.get("/api/top_signals")
def top_signals():
    p = os.path.join(STATE, "learning_metrics.json")
    if not os.path.exists(p): 
        return {"error": "no data"}
    with open(p) as f: data = json.load(f)

    if isinstance(data, list): signals = data
    elif isinstance(data, dict): signals = data.get("signals", [])
    else: signals = []

    # add safety defaults
    for s in signals:
        s.setdefault("prediction_price", None)
        s.setdefault("prediction_percent", None)
        s.setdefault("stop_loss", None)
        s.setdefault("stop_loss_percent", None)

    stocks = [s for s in signals if s.get("asset_type")=="stock"]
    cryptos = [s for s in signals if s.get("asset_type")=="crypto"]
    key = lambda s: s.get("brain_grade",0)*0.6 + s.get("persona_grade",0)*0.4

    return {
        "stocks": sorted(stocks, key=key, reverse=True)[:6],
        "cryptos": sorted(cryptos, key=key, reverse=True)[:6],
        "count": len(signals)
    }
