FUNNEL_WEIGHTS = {
    "confidence_weight": 0.4,
    "momentum_weight": 0.2,
    "volume_weight": 0.15,
    "guardian_weight": 0.15,
    "sentiment_weight": 0.1
}

MIN_CONFIDENCE = 70
TOP_N_STOCKS = 6
TOP_N_CRYPTOS = 6
UNIVERSE_SOURCES = {
    "stocks": "data/universe_stocks.json",
    "cryptos": "data/universe_cryptos.json"
}
