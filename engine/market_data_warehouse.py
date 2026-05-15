"""Local Market Data Warehouse V1.

Metadata-first local warehouse catalog. It is safe when files are missing and
does not bulk-write collected market data.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any


VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


class MarketDataWarehouse:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.manifest_path = os.path.join(self.state_dir, "market_data_warehouse_manifest_v1.json")
        self.fmp_cache_path = os.path.join(self.state_dir, "fmp_enrichment_cache_v1.json")
        self.cache_index_path = os.path.join(self.state_dir, "fmp_cache_index.json")
        self.runtime_snapshot_path = os.path.join(self.state_dir, "runtime_top_buys_snapshot.json")
        self.collection_enabled = False

    def _read_json(self, path: str) -> dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _age_seconds(self, path: str) -> float | None:
        try:
            return max(0.0, datetime.now(UTC).timestamp() - os.path.getmtime(path))
        except Exception:
            return None

    def _cache_catalog(self) -> list[dict[str, Any]]:
        manifest = self._read_json(self.manifest_path)
        rows = manifest.get("symbols") if isinstance(manifest.get("symbols"), list) else []
        if rows:
            return [r for r in rows if isinstance(r, dict)][:200]
        fmp_cache = self._read_json(self.fmp_cache_path)
        catalog: list[dict[str, Any]] = []
        for symbol, entry in list(fmp_cache.items())[:200]:
            if not isinstance(entry, dict):
                continue
            profile = entry.get("profile") if isinstance(entry.get("profile"), dict) else {}
            ratios = entry.get("ratios") if isinstance(entry.get("ratios"), dict) else {}
            catalog.append(
                {
                    "symbol": str(symbol).upper(),
                    "asset_type": str(profile.get("asset_type") or profile.get("type") or "unknown"),
                    "data_types_available": [
                        name
                        for name, present in (
                            ("company_profile", bool(profile)),
                            ("financial_ratios", bool(ratios)),
                            ("fundamentals", bool(entry.get("fundamentals"))),
                            ("earnings", bool(entry.get("earnings"))),
                            ("sector_industry", bool(profile.get("sector") or profile.get("industry"))),
                        )
                        if present
                    ],
                    "latest_history_date": entry.get("latest_history_date"),
                    "fundamentals_available": bool(entry.get("fundamentals")),
                    "earnings_available": bool(entry.get("earnings")),
                    "sector": profile.get("sector"),
                    "industry": profile.get("industry"),
                    "provider_source": "financial_modeling_prep",
                    "freshness": "unknown",
                    "cache_location": self.fmp_cache_path,
                }
            )
        return catalog

    def status(self) -> dict[str, Any]:
        catalog = self._cache_catalog()
        symbols_with_history = sum(1 for r in catalog if r.get("latest_history_date"))
        symbols_with_fundamentals = sum(1 for r in catalog if bool(r.get("fundamentals_available")))
        symbols_with_earnings = sum(1 for r in catalog if bool(r.get("earnings_available")))
        symbols_with_sector = sum(1 for r in catalog if bool(r.get("sector") or r.get("industry")))
        planned_calls = 0
        bandwidth = 0.0
        blocked_reason = "warehouse_metadata_only_collection_disabled"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "metadata_catalog_only",
            "local_only": True,
            "writes_files": False,
            "collection_enabled": False,
            "api_calls_used": 0,
            "planned_calls": planned_calls,
            "estimated_bandwidth": bandwidth,
            "blocked_reason": blocked_reason,
            "next_recommended_action": "populate_manifest_from_future_governed_collection",
            "market_data_warehouse_status_v1": True,
            "manifest_path": self.manifest_path,
            "manifest_exists": os.path.exists(self.manifest_path),
            "storage_sources": {
                "fmp_enrichment_cache": {
                    "path": self.fmp_cache_path,
                    "exists": os.path.exists(self.fmp_cache_path),
                    "age_seconds": self._age_seconds(self.fmp_cache_path),
                },
                "fmp_cache_index": {
                    "path": self.cache_index_path,
                    "exists": os.path.exists(self.cache_index_path),
                    "age_seconds": self._age_seconds(self.cache_index_path),
                },
            },
            "symbol_count": len(catalog),
            "coverage": {
                "history_symbols": symbols_with_history,
                "fundamentals_symbols": symbols_with_fundamentals,
                "earnings_symbols": symbols_with_earnings,
                "sector_industry_symbols": symbols_with_sector,
            },
            "required_metadata_fields": [
                "symbol",
                "asset_type",
                "data_types_available",
                "latest_history_date",
                "fundamentals_availability",
                "earnings_availability",
                "sector_industry",
                "provider_source",
                "freshness",
                "cache_location",
            ],
            "sample_symbols": catalog[:20],
            "metadata_rows_estimated": _to_int(len(catalog), 0),
        }
