from __future__ import annotations

import uuid
from datetime import UTC, datetime


class _HistoricalDatasetStub:
    def credentials_loaded(self):
        return False

    def fmp_credentials_loaded(self):
        return False

    def depth_summary(self):
        return {"symbols_with_history": 0, "total_bars": 0}

    def premium_backfill_status(self):
        return {"ok": True, "in_progress": False, "mode": "stub"}

    def run_premium_backfill_step(self, symbols, max_symbols=30):
        return {"ok": True, "symbols_processed": min(len(symbols or []), int(max_symbols or 0))}

    def backfill_symbol(self, symbol, asset_type="stock", days_back=180, resolution="D"):
        return {"ok": True, "symbol": symbol, "bars_ingested": 0, "reason": "stub_no_history"}


class PaperReplayTrainer:
    def __init__(self, *args, **kwargs):
        self.historical_dataset = _HistoricalDatasetStub()
        self._history = []
        self._in_progress = False
        self._last_run = {}

    def run(self, cfg=None):
        cfg = dict(cfg or {})
        self._in_progress = True
        run_id = str(cfg.get("run_id") or f"replay-{uuid.uuid4().hex[:8]}")
        summary = {
            "run_id": run_id,
            "trades_generated": 0,
            "valid_trades": 0,
            "invalid_trades": 0,
            "avg_return": 0.0,
            "win_rate": 0.0,
            "historical_ingest": {"local_dataset_hits": 0, "live_fetch_hits": 0, "no_history_symbols": 0},
            "finished_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        self._history.insert(0, summary)
        self._history = self._history[:100]
        self._last_run = dict(summary)
        self._in_progress = False
        return {"ok": True, "run_id": run_id, "summary": summary}

    def status(self):
        return {
            "ok": True,
            "in_progress": bool(self._in_progress),
            "last_run": dict(self._last_run),
            "history_count": len(self._history),
        }

    def history(self, limit=10):
        return list(self._history[: max(1, int(limit or 10))])

