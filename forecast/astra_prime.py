
# ============================================================
# === ASTRA PRIME SMART PREDICTOR (v1) =======================
# ============================================================
import time
from core.guardian.guardian_v7 import guardian_log

_last_prediction = {}
_prediction_interval = {
    "day": 1800,   # 30 min
    "swing": 14400 # 4 hr
}

def smart_predict(symbol, mode="day"):
    """Only run predictions when enough time has passed."""
    now = time.time()
    last = _last_prediction.get(symbol, 0)
    interval = _prediction_interval[mode]

    if now - last < interval:
        guardian_log.info(f"[SmartPredict] {symbol}: cached ({interval}s window active)")
        return None

    guardian_log.info(f"[SmartPredict] Running AstraPrime for {symbol}")
    _last_prediction[symbol] = now
    return get_predictions(symbol)

