from .forecast_engine import run_forecast

def get_cached_forecast(symbol):
    return run_forecast(symbol)
