"""
paper_trader.py — Phase-90

Simulated trading engine for Astra Intelligence.
Tracks:
 • Trade entries
 • Exits
 • PnL
 • Outcome labels for NeuralAgent training
 • Storage inside ReplayBuffer

Supports:
 • open_trade()
 • close_trade()
 • get_open_positions()
 • get_closed_positions()

Perfect for Phase-90 learning loop.
"""

import time
from datetime import datetime


class PaperTrader:
    def __init__(self, buffer, guardian=None):
        """
        buffer: ReplayBuffer instance
        guardian: optional GuardianV3 for safe operations
        """
        self.buffer = buffer
        self.guardian = guardian

        self.open_positions = {}     # {ticker: {...}}
        self.closed_positions = []   # list of closed trade dicts

    # ---------------------------------------------------------------------
    # Safe helper
    # ---------------------------------------------------------------------
    def safe(self, func, *args, **kwargs):
        """Guardian wrapper if available."""
        if self.guardian:
            return self.guardian.safe_run(func, *args, **kwargs)
        try:
            return func(*args, **kwargs)
        except Exception:
            return None

    # ---------------------------------------------------------------------
    # OPEN TRADE
    # ---------------------------------------------------------------------
    def open_trade(self, ticker, price, context=None):
        """
        Opens a paper trade for a ticker.
        context = AstraPrime packet or metadata
        """
        ts = int(time.time())

        trade = {
            "ticker": ticker,
            "entry_price": price,
            "open_time": ts,
            "context": context or {},
        }

        self.open_positions[ticker] = trade
        return trade

    # ---------------------------------------------------------------------
    # CLOSE TRADE
    # ---------------------------------------------------------------------
    def close_trade(self, ticker, exit_price):
        """
        Closes a trade and computes outcome.
        Also stores sample to ReplayBuffer.
        """
        if ticker not in self.open_positions:
            return None

        trade = self.open_positions.pop(ticker)
        entry = trade["entry_price"]
        pnl = exit_price - entry
        label = 1 if pnl > 0 else 0

        closed = {
            "ticker": ticker,
            "entry": entry,
            "exit": exit_price,
            "pnl": pnl,
            "label": label,
            "open_time": trade["open_time"],
            "close_time": int(time.time()),
            "context": trade.get("context", {}),
        }

        # Store closed trade
        self.closed_positions.append(closed)

        # ---------------------------------------------------------
        # Store learning sample in ReplayBuffer
        # ---------------------------------------------------------
        packet = trade.get("context", {})
        vector = packet.get("neural_vector")

        if vector is not None:
            sample = {
                "vector": vector,
                "label": label,
                "ticker": ticker,
                "pnl": pnl,
                "timestamp": trade["open_time"],
            }
            self.safe(self.buffer.push, sample)

        return closed

    # ---------------------------------------------------------------------
    # GETTERS
    # ---------------------------------------------------------------------
    def get_open_positions(self):
        """Return list of current open paper trades"""
        return list(self.open_positions.values())

    def get_closed_positions(self):
        """Return list of historical completed trades"""
        return list(self.closed_positions)

    # ---------------------------------------------------------------------
    # UTILITY
    # ---------------------------------------------------------------------
    def auto_close_expired(self, price_lookup, max_minutes=120):
        """
        Optional utility: auto-close any trades older than max_minutes.
        price_lookup(ticker) must return current price.

        Useful for future Phase-100 auto-trading.
        """
        now = int(time.time())
        to_close = []

        for ticker, trade in list(self.open_positions.items()):
            age_min = (now - trade["open_time"]) / 60
            if age_min >= max_minutes:
                to_close.append(ticker)

        results = []
        for t in to_close:
            px = price_lookup(t)
            if px:
                closed = self.close_trade(t, px)
                if closed:
                    results.append(closed)

        return results
