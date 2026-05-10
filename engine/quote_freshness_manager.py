from __future__ import annotations


class QuoteFreshnessManager:
    def __init__(self, *args, **kwargs):
        pass

    def classify_closed_trade(self, row, tiny_epsilon=1e-6):
        # Conservative default: treat row as valid unless clearly missing key prices.
        entry = row.get("entry_price") if isinstance(row, dict) else None
        exit_ = row.get("exit_price") if isinstance(row, dict) else None
        if not entry or not exit_:
            return False, ["missing_price"]
        return True, []

