from __future__ import annotations

from datetime import UTC, datetime


class _AlpacaWsMonitor:
    def __init__(self):
        self._symbols = []
        self._last_reset_reason = ""

    def configure_symbols(self, symbols=None, **kwargs):
        self._symbols = [str(s).upper().strip() for s in (symbols or []) if str(s).strip()]
        return {"ok": True, "symbol_count": len(self._symbols)}

    def get_quote(self, symbol, max_age_seconds=20, **kwargs):
        return None

    def status(self):
        return {
            "ok": True,
            "active": False,
            "symbol_count": len(self._symbols),
            "symbols": list(self._symbols[:20]),
            "last_reset_reason": self._last_reset_reason,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def contention_diagnostics(self):
        return {"ok": True, "contention_events": 0, "notes": []}

    def reset_for_diagnostics(self, reason="", **kwargs):
        self._last_reset_reason = str(reason or "manual_reset")
        return {"ok": True, "reset": True, "reason": self._last_reset_reason}


ALPACA_WS_MONITOR = _AlpacaWsMonitor()

