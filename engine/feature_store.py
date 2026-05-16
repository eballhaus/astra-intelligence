"""Feature Store V1.

Tracks reusable feature metadata and coverage priorities without computing or
persisting large feature matrices.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.1.0"
BROAD_UNIVERSE_TARGET_COUNT = 7500
ACTIVE_UNIVERSE_TARGET_COUNT = 200


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class FeatureStore:
    def __init__(self, state_dir: str = "state", warehouse: Any | None = None) -> None:
        self.state_dir = str(state_dir or "state")
        self.warehouse = warehouse
        self.manifest_path = os.path.join(self.state_dir, "feature_store_manifest_v1.json")
        self.learning_snapshot_path = os.path.join(self.state_dir, "learning_insights_last_good.json")
        self.feature_families = [
            "momentum",
            "volatility",
            "volume_pressure",
            "entry_quality",
            "consensus",
            "sector_strength",
            "regime",
            "drawdown_capture_metrics",
        ]

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _manifest_features(self) -> dict[str, Any]:
        manifest = self._read_json(self.manifest_path)
        features = manifest.get("features")
        return features if isinstance(features, dict) else {}

    def _warehouse_coverage(self) -> dict[str, Any]:
        if self.warehouse is None:
            return {}
        try:
            payload = self.warehouse.status()
            return payload.get("coverage") if isinstance(payload.get("coverage"), dict) else {}
        except Exception:
            return {}

    def status(self) -> dict[str, Any]:
        manifest_features = self._manifest_features()
        learning = self._read_json(self.learning_snapshot_path)
        warehouse_coverage = self._warehouse_coverage()
        availability = {}
        for family in self.feature_families:
            manifest_row = manifest_features.get(family) if isinstance(manifest_features.get(family), dict) else {}
            available_symbols = _to_float(manifest_row.get("available_symbols"), 0.0)
            stale_symbols = _to_float(manifest_row.get("stale_symbols"), 0.0)
            if family in {"entry_quality", "consensus"}:
                fallback_ready = bool(learning)
            elif family in {"sector_strength", "regime"}:
                fallback_ready = _to_float(warehouse_coverage.get("sector_industry_symbols"), 0.0) > 0
            elif family in {"momentum", "volatility", "volume_pressure", "drawdown_capture_metrics"}:
                fallback_ready = _to_float(warehouse_coverage.get("history_symbols"), 0.0) > 0
            else:
                fallback_ready = False
            availability[family] = {
                "available": bool(available_symbols > 0 or fallback_ready),
                "available_symbols": int(available_symbols),
                "stale_symbols": int(stale_symbols),
                "source": manifest_row.get("source") or ("local_learning_snapshot" if fallback_ready else "not_available"),
                "cache_location": manifest_row.get("cache_location") or self.manifest_path,
            }
        missing = [name for name, row in availability.items() if not bool(row.get("available"))]
        priorities = [
            "historical_ohlcv_for_momentum_volatility_drawdown",
            "volume_history_for_volume_pressure",
            "sector_industry_for_sector_strength",
            "entry_quality_and_consensus_shadow_scores",
            "regime_labels_from_market_context",
        ]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "metadata_catalog_and_active_universe_feature_planning",
            "local_only": True,
            "writes_files": False,
            "collection_enabled": True,
            "api_calls_used": 0,
            "planned_calls": 0,
            "estimated_bandwidth": 0.0,
            "quota_state": {
                "authority": "FmpUtilizationOptimizer",
                "feature_store_does_not_call_providers": True,
            },
            "blocked_reason": "feature_store_waiting_for_governed_broad_collection_inputs",
            "next_recommended_action": "prioritize_history_volume_sector_and_regime_features_for_active_universe_funnel",
            "feature_store_status_v1": True,
            "broad_universe_target_count": BROAD_UNIVERSE_TARGET_COUNT,
            "broad_universe_collected_count": int(_to_float(warehouse_coverage.get("history_symbols"), 0.0)),
            "active_universe_target_count": ACTIVE_UNIVERSE_TARGET_COUNT,
            "active_universe_current_count": min(
                ACTIVE_UNIVERSE_TARGET_COUNT,
                int(max(
                    _to_float(warehouse_coverage.get("history_symbols"), 0.0),
                    _to_float(warehouse_coverage.get("sector_industry_symbols"), 0.0),
                )),
            ),
            "collection_progress_pct": round(
                min(100.0, (_to_float(warehouse_coverage.get("history_symbols"), 0.0) / max(1, BROAD_UNIVERSE_TARGET_COUNT)) * 100.0),
                3,
            ),
            "manifest_path": self.manifest_path,
            "manifest_exists": os.path.exists(self.manifest_path),
            "feature_availability": availability,
            "feature_coverage": {
                "families_total": len(self.feature_families),
                "families_available": len(self.feature_families) - len(missing),
                "families_missing": len(missing),
                "coverage_pct": round(((len(self.feature_families) - len(missing)) / max(1, len(self.feature_families))) * 100.0, 3),
            },
            "feature_coverage_pct": round(((len(self.feature_families) - len(missing)) / max(1, len(self.feature_families))) * 100.0, 3),
            "next_feature_priorities": priorities,
            "missing_feature_priorities": priorities,
            "missing_feature_families": missing,
            "api_efficiency_metadata": {
                "feature_refresh_uses_delta_inputs": True,
                "feature_refresh_respects_smart_ttl": True,
                "synthetic_replay_features_shadow_only": True,
                "api_calls_used": 0,
            },
            "generated_at": _now_iso(),
        }
