from core.agents.base_agent import BaseAgent

"""
Astra Intelligence — RiskAgent (v2 Safe Extension)
--------------------------------------------------
Computes stop-loss and risk parameters for given symbols.
Now includes universal compute_stop() for dashboard integration.
"""

import pandas as pd


class RiskAgent(BaseAgent):
    """
    Evaluates volatility-adjusted risk and computes stop-loss levels.
    """

    def __init__(self):
        self.default_stop_pct = 5.0  # fallback stop-loss 5%

    def compute_stop(self, symbol: str, df: pd.DataFrame):
        """
        Compute a stop-loss price and percentage based on volatility.
        Returns (stop_price, stop_loss_pct)
        """
        try:
            if df is None or df.empty or "close" not in df.columns:
                return None, -self.default_stop_pct

            closes = df["close"].astype(float)
            current_price = closes.iloc[-1]
            vol = closes.pct_change().std() * 100

            # Adjust stop-loss dynamically
            stop_loss_pct = max(-3.0, min(-vol, -self.default_stop_pct))
            stop_price = current_price * (1 + (stop_loss_pct / 100))

            return round(stop_price, 2), round(stop_loss_pct, 2)

        except Exception as e:
            print(f"[RiskAgent] compute_stop() error for {symbol}: {e}")
            return None, -self.default_stop_pct

    def predict(self, x=None):
        """Temporary calibration stub."""
        self.g_log(f"[{self.__class__.__name__}] Predict placeholder executed.")
        return 0.5
