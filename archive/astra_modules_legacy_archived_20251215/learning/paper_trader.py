"""
Astra Intelligence - Paper Trader
---------------------------------
Simulated trading system for Astra Intelligence.
Creates virtual trades from forecasts and tracks their results
to feed into the learning system.

Responsibilities:
• Open & close paper trades based on Astra forecasts
• Track PnL, accuracy, and duration
• Send completed trade results to ReplayBuffer
• Never execute real trades (simulation only)
"""

import traceback
from datetime import datetime, timedelta

from astra_core.learning.performance_tracker import PerformanceTracker
from astra_core.learning.replay_buffer import ReplayBuffer


class PaperTrader:
    """Simulates trade entries/exits and logs learning outcomes."""

    def __init__(self, max_hold_minutes: int = 240, reward_scaler: float = 100):
        self.open_trades = []
        self.closed_trades = []
        self.max_hold = timedelta(minutes=max_hold_minutes)
        self.buffer = ReplayBuffer()
        self.tracker = PerformanceTracker()
        self.reward_scaler = reward_scaler

    # === Core Trading Logic ===
    def open_trade(
        self, symbol: str, direction: str, confidence: float = 0.5, price: float = None
    ):
        """Open a simulated trade position."""
        try:
            trade = {
                "symbol": symbol,
                "direction": direction.lower(),
                "confidence": confidence,
                "entry_price": float(price) if price else None,
                "entry_time": datetime.utcnow().isoformat(),
                "exit_price": None,
                "exit_time": None,
                "reward": None,
            }
            self.open_trades.append(trade)
            print(
                f"[Astra PaperTrader] 🟢 Opened {direction.upper()} trade for {symbol}"
            )
        except Exception as e:
            print(f"[Astra PaperTrader] Failed to open trade: {e}")

    def close_trade(self, symbol: str, price: float):
        """Close a simulated trade and compute reward."""
        try:
            # Find active trade
            trade = next((t for t in self.open_trades if t["symbol"] == symbol), None)
            if not trade:
                return

            trade["exit_price"] = float(price)
            trade["exit_time"] = datetime.utcnow().isoformat()

            # Compute reward
            direction = trade["direction"]
            entry_price = trade["entry_price"] or price
            price_change = (price - entry_price) / entry_price

            if direction == "buy":
                reward = price_change
            elif direction == "sell":
                reward = -price_change
            else:
                reward = 0.0

            # Scale reward for training
            reward *= self.reward_scaler

            trade["reward"] = reward
            self.closed_trades.append(trade)
            self.open_trades.remove(trade)

            print(
                f"[Astra PaperTrader] 🔴 Closed {direction.upper()} trade for {symbol} | Reward: {reward:.2f}"
            )

            # Log to replay buffer
            self.buffer.add(
                state=[entry_price, confidence],
                prediction=confidence if direction == "buy" else -confidence,
                reward=reward,
                symbol=symbol,
                confidence=confidence,
            )

            # Log performance
            self.tracker.record_performance(symbol=symbol, reward=reward)

        except Exception as e:
            print(f"[Astra PaperTrader] Failed to close trade: {e}")
            traceback.print_exc()

    # === Automatic Maintenance ===
    def auto_close_expired(self, latest_prices: dict):
        """Automatically close trades that have exceeded max holding time."""
        now = datetime.utcnow()
        expired = [
            t
            for t in self.open_trades
            if (now - datetime.fromisoformat(t["entry_time"])) > self.max_hold
        ]

        for trade in expired:
            symbol = trade["symbol"]
            if symbol in latest_prices:
                self.close_trade(symbol, latest_prices[symbol])
            else:
                print(f"[Astra PaperTrader] Skipped expired trade (no price): {symbol}")

    def get_open_positions(self):
        """Return list of active paper trades."""
        return self.open_trades

    def get_closed_positions(self, n: int = 20):
        """Return most recent closed trades."""
        return self.closed_trades[-n:]
