import pandas as pd
from core.guardian.guardian_v7 import guardian_log

def select_top_assets(mode='live', limit: int = 6):
    """
    Rank and return top assets by momentum & volatility.
    Returns DataFrame with consistent columns: symbol, momentum, volatility, score.
    """
    guardian_log.info(f"🧠 [DataFunnel] Selecting top assets (mode={mode})")

    try:
        # Placeholder data until live integration
        data = {
            "symbol": ["AAPL", "MSFT", "GOOG", "TSLA", "NVDA", "AMZN", "META", "BTCUSD", "ETHUSD", "NFLX"],
            "momentum": [0.85, 0.78, 0.65, 0.72, 0.91, 0.55, 0.48, 0.82, 0.76, 0.44],
            "volatility": [0.62, 0.58, 0.60, 0.79, 0.75, 0.53, 0.47, 0.83, 0.88, 0.41],
        }

        df = pd.DataFrame(data)
        df["score"] = (df["momentum"] * 0.6) + (df["volatility"] * 0.4)
        df = df.sort_values("score", ascending=False)
        top = df.head(limit)

        guardian_log.info(f"✅ [DataFunnel] Top {limit} assets selected: {', '.join(top['symbol'])}")
        return top[["symbol", "momentum", "volatility", "score"]]

    except Exception as e:
        guardian_log.error(f"❌ [DataFunnel] Failed to select assets: {e}")
        return pd.DataFrame(columns=["symbol", "momentum", "volatility", "score"])
