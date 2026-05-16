from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"
MACRO_SYMBOLS = ["SPY", "QQQ", "IWM", "VIX", "TLT", "DXY", "GLD", "BTC"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class MacroCrossAssetContextEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.snapshot_path = os.path.join(self.state_dir, "runtime_top_buys_snapshot.json")
        self.fmp_cache_path = os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json")

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def status(self) -> dict[str, Any]:
        cache = self._read_json(self.fmp_cache_path)
        snapshot = self._read_json(self.snapshot_path)
        available = [s for s in MACRO_SYMBOLS if s in cache or s in snapshot]
        top_rows = []
        stocks = snapshot.get("stocks") if isinstance(snapshot.get("stocks"), dict) else {}
        if isinstance(stocks.get("final"), list):
            top_rows = [r for r in stocks.get("final") if isinstance(r, dict)]
        avg_conf = sum(_to_float(r.get("confidence"), _to_float(r.get("score"), 50.0)) for r in top_rows) / max(1, len(top_rows))
        risk_on = avg_conf >= 65.0 and "VIX" not in available
        regime = "risk_on_constructive" if risk_on else "neutral_or_defensive"
        confidence = min(90.0, 35.0 + len(available) * 5.0 + len(top_rows) * 2.0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_macro_cross_asset_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "macro_context_status_v1": True,
            "tracked_symbols": MACRO_SYMBOLS,
            "available_cached_symbols": available,
            "uses_existing_providers_or_caches_only": True,
            "uncontrolled_new_data_collection": False,
            "market_regime": regime,
            "risk_state": "risk_on" if risk_on else "risk_off_or_mixed",
            "volatility_state": "unknown_from_cache" if "VIX" not in available else "cache_available",
            "trend_state": "constructive" if avg_conf >= 65.0 else "mixed",
            "macro_confidence": round(confidence, 3),
            "macro_adaptation_score": round(min(100.0, avg_conf * 0.6 + confidence * 0.4), 3),
            "confidence_score": round(confidence, 3),
            "next_recommended_action": "use_macro_context_as_shadow_overlay_until_cached_macro_history_is_deeper",
        }
