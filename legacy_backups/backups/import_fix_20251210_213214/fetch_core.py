import pandas as pd
import yfinance as yf


class FetchUnified:
    def get_symbol_data(self, symbol: str):
        """Fetch latest OHLC data for a symbol (basic placeholder)."""
        try:
            data = yf.download(symbol, period="5d", interval="1h", progress=False)
            return data.reset_index()
        except Exception as e:
            print(f"[FetchUnified] ⚠️ Data fetch failed for {symbol}: {e}")
            return pd.DataFrame()


fetch_unified = FetchUnified()
