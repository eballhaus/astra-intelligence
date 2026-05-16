"""Advanced Metrics Snapshot V1.

Fast, read-only snapshot aggregator for Learning Tab advanced metrics. It runs
card providers with short per-card timeouts and returns partial/stale status
instead of letting one slow diagnostic block the whole UI.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from datetime import UTC, datetime
from typing import Any, Callable

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class AdvancedMetricsSnapshot:
    def __init__(
        self,
        *,
        per_card_timeout_seconds: float = 2.5,
        whole_snapshot_timeout_seconds: float = 4.8,
        fresh_ttl_seconds: float = 45.0,
        stale_ttl_seconds: float = 300.0,
        max_workers: int = 6,
    ) -> None:
        self.per_card_timeout_seconds = max(0.5, min(5.0, float(per_card_timeout_seconds)))
        self.whole_snapshot_timeout_seconds = max(1.0, min(8.0, float(whole_snapshot_timeout_seconds)))
        self.fresh_ttl_seconds = max(5.0, float(fresh_ttl_seconds))
        self.stale_ttl_seconds = max(self.fresh_ttl_seconds, float(stale_ttl_seconds))
        self.max_workers = max(1, min(16, int(max_workers)))
        self._snapshot: dict[str, Any] | None = None
        self._snapshot_ts = 0.0

    def _empty_card(self, spec: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
        now = _now_iso()
        return {
            "key": spec.get("key"),
            "title": spec.get("title"),
            "status": status,
            "primary_value": "Unavailable" if status in {"unavailable", "error"} else "Still computing",
            "secondary_value": reason,
            "detail_value": reason,
            "updated_at": now,
            "source_endpoint": spec.get("source_endpoint"),
            "error_reason": reason,
        }

    def _run_card(self, spec: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        provider = spec.get("provider")
        extractor = spec.get("extractor")
        if not callable(provider):
            return self._empty_card(spec, "unavailable", "provider_unavailable")
        try:
            payload = provider()
            if not isinstance(payload, dict):
                return self._empty_card(spec, "unavailable", "non_object_payload")
            if callable(extractor):
                card = extractor(payload)
                if not isinstance(card, dict):
                    card = {}
            else:
                card = {}
            status = str(card.get("status") or ("loaded" if payload.get("enabled", True) is not False else "unavailable"))
            return {
                "key": spec.get("key"),
                "title": spec.get("title"),
                "status": status,
                "primary_value": str(card.get("primary_value", "Loaded")),
                "secondary_value": str(card.get("secondary_value", "")),
                "detail_value": str(card.get("detail_value", "")),
                "updated_at": str(card.get("updated_at") or payload.get("generated_at") or payload.get("last_updated_utc") or _now_iso()),
                "source_endpoint": spec.get("source_endpoint"),
                "error_reason": str(card.get("error_reason", "")),
                "elapsed_seconds": round(max(0.0, time.time() - started), 3),
            }
        except Exception as exc:
            return self._empty_card(spec, "error", f"card_error: {exc}")

    def snapshot(self, card_specs: list[dict[str, Any]], *, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        age = max(0.0, now - self._snapshot_ts) if self._snapshot else None
        if self._snapshot and not force_refresh and age is not None and age <= self.fresh_ttl_seconds:
            out = dict(self._snapshot)
            out["snapshot_age_seconds"] = round(age, 3)
            out["load_strategy"] = "fresh_in_memory_snapshot"
            return out

        specs = [dict(s) for s in list(card_specs or []) if isinstance(s, dict)]
        started = time.time()
        cards_by_key: dict[str, dict[str, Any]] = {}
        timed_out: set[str] = set()
        executor = ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(specs))))
        try:
            future_to_spec = {executor.submit(self._run_card, spec): spec for spec in specs}
            try:
                for future in as_completed(future_to_spec, timeout=self.whole_snapshot_timeout_seconds):
                    spec = future_to_spec[future]
                    key = str(spec.get("key") or spec.get("title") or "unknown")
                    try:
                        cards_by_key[key] = future.result(timeout=self.per_card_timeout_seconds)
                    except TimeoutError:
                        timed_out.add(key)
                        cards_by_key[key] = self._empty_card(spec, "still_computing", f"timeout_after_{self.per_card_timeout_seconds}s")
                    except Exception as exc:
                        cards_by_key[key] = self._empty_card(spec, "error", f"card_error: {exc}")
            except TimeoutError:
                pass
            for future, spec in future_to_spec.items():
                key = str(spec.get("key") or spec.get("title") or "unknown")
                if key in cards_by_key:
                    continue
                timed_out.add(key)
                cards_by_key[key] = self._empty_card(spec, "still_computing", f"snapshot_timeout_after_{self.whole_snapshot_timeout_seconds}s")
        finally:
            # Do not wait for abandoned diagnostic workers; the UI needs a bounded
            # snapshot response and slow cards are represented as still_computing.
            executor.shutdown(wait=False, cancel_futures=True)

        cards = [cards_by_key.get(str(s.get("key") or s.get("title") or "unknown"), self._empty_card(s, "unavailable", "not_loaded")) for s in specs]
        prior_cards = {str(c.get("key")): c for c in (self._snapshot or {}).get("cards", []) if isinstance(c, dict)} if self._snapshot else {}
        if prior_cards:
            for card in cards:
                if card.get("status") in {"still_computing", "error", "unavailable"} and card.get("key") in prior_cards:
                    stale = dict(prior_cards[card.get("key")])
                    stale["status"] = "stale"
                    stale["error_reason"] = str(card.get("error_reason") or "using_previous_snapshot")
                    cards[cards.index(card)] = stale

        unavailable = [c for c in cards if c.get("status") in {"unavailable", "error", "still_computing"}]
        stale = [c for c in cards if c.get("status") == "stale"]
        loaded = [c for c in cards if c.get("status") == "loaded"]
        elapsed = max(0.0, time.time() - started)
        payload = {
            "enabled": True,
            "version": VERSION,
            "mode": "fast_snapshot_read_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "advanced_metrics_snapshot_v1": True,
            "snapshot_generated_at": _now_iso(),
            "snapshot_age_seconds": 0.0,
            "snapshot_elapsed_seconds": round(elapsed, 3),
            "cards": cards,
            "unavailable_cards": [c.get("key") for c in unavailable],
            "stale_cards": [c.get("key") for c in stale],
            "timeout_cards": sorted(timed_out),
            "total_cards": len(cards),
            "cards_loaded": len(loaded),
            "cards_failed": len(unavailable),
            "load_strategy": "parallel_fast_snapshot_with_card_timeouts",
            "per_card_timeout_seconds": self.per_card_timeout_seconds,
            "whole_snapshot_timeout_seconds": self.whole_snapshot_timeout_seconds,
            "recommended_action": "show_loaded_stale_or_unavailable_cards_without_blocking_learning_tab",
        }
        self._snapshot = dict(payload)
        self._snapshot_ts = time.time()
        return payload
