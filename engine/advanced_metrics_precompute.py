"""Advanced Metrics Background Precompute Worker V1.

Change-aware, snapshot-first support for Learning Tab diagnostics. The worker is
safe by default: bounded time budgets, no provider/API calls of its own, atomic
small JSON writes, and stale-valid fallback when heavy diagnostics are slow.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _slug(value: Any) -> str:
    raw = str(value or "unknown").strip() or "unknown"
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in raw)[:80]


class AdvancedMetricsPrecomputeStore:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.snapshot_dir = os.path.join(self.state_dir, "snapshots", "advanced_metrics_cards")
        self.max_age_by_weight = {
            "lightweight": 60,
            "medium": 300,
            "heavy": 1800,
            "very_heavy": 21600,
            "daily": 86400,
        }
        self.refresh_intervals = {
            "lightweight": 45,
            "medium": 180,
            "heavy": 900,
            "very_heavy": 3600,
            "daily": 86400,
        }
        self._lock = threading.Lock()
        self._warmup_started = False
        self._last_warmup_at = ""
        self._last_warmup_status = "not_started"

    def _path(self, card_id: str) -> str:
        return os.path.join(self.snapshot_dir, f"{_slug(card_id)}.json")

    def _weight(self, spec: dict[str, Any]) -> str:
        raw = str(spec.get("diagnostic_weight") or "medium").lower()
        return raw if raw in self.max_age_by_weight else "medium"

    def _ttl(self, spec: dict[str, Any]) -> int:
        return int(spec.get("ttl_seconds") or self.max_age_by_weight[self._weight(spec)])

    def _interval(self, spec: dict[str, Any]) -> int:
        return int(spec.get("refresh_interval_seconds") or self.refresh_intervals[self._weight(spec)])

    def _file_signature(self, path: str) -> dict[str, Any]:
        try:
            return {
                "path": path,
                "exists": os.path.exists(path),
                "mtime": os.path.getmtime(path) if os.path.exists(path) else None,
                "size": os.path.getsize(path) if os.path.exists(path) else 0,
            }
        except Exception as exc:
            return {"path": path, "exists": False, "mtime": None, "size": 0, "error": str(exc)[:120]}

    def source_fingerprint(self, spec: dict[str, Any]) -> str:
        sources = list(spec.get("fingerprint_sources") or [])
        parts: list[Any] = [VERSION, spec.get("key"), spec.get("source_endpoint"), self._weight(spec)]
        for path in sources:
            parts.append(self._file_signature(str(path)))
        marker = spec.get("version_marker")
        if marker:
            parts.append(str(marker))
        encoded = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:24]

    def load_card(self, card_id: str) -> dict[str, Any] | None:
        try:
            with open(self._path(card_id), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return None
            generated = _safe_float(data.get("generated_monotonic"), 0.0)
            age = max(0.0, time.time() - generated) if generated > 0 else 0.0
            data["age_seconds"] = round(age, 3)
            ttl = _safe_float(data.get("ttl_seconds"), 300.0)
            if data.get("status") == "fresh" and age > ttl:
                data["status"] = "stale"
            return data
        except Exception:
            return None

    def _atomic_write(self, card_id: str, payload: dict[str, Any]) -> bool:
        os.makedirs(self.snapshot_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=f".{_slug(card_id)}.", suffix=".tmp", dir=self.snapshot_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, separators=(",", ":"))
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, self._path(card_id))
            return True
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return False

    def _empty_card(self, spec: dict[str, Any], status: str, reason: str, fingerprint: str) -> dict[str, Any]:
        now = _now_iso()
        ttl = self._ttl(spec)
        return {
            "card_id": spec.get("key"),
            "key": spec.get("key"),
            "title": spec.get("title"),
            "status": status,
            "primary_value": "Snapshot unavailable" if status in {"unavailable", "error"} else "Still computing",
            "secondary_value": reason,
            "detail_value": reason,
            "generated_at": now,
            "generated_monotonic": time.time(),
            "age_seconds": 0.0,
            "ttl_seconds": ttl,
            "source_endpoint": spec.get("source_endpoint"),
            "last_success_at": "",
            "last_error": reason,
            "error_reason": reason,
            "compute_duration_seconds": 0.0,
            "source_fingerprint": fingerprint,
            "last_fingerprint": fingerprint,
            "changed_since_last_snapshot": True,
            "refresh_reason": reason,
            "refresh_interval_seconds": self._interval(spec),
            "refresh_priority": self._weight(spec),
            "refresh_status": status,
            "next_refresh_due": now,
        }

    def _compute_card(self, spec: dict[str, Any], fingerprint: str) -> dict[str, Any]:
        started = time.time()
        provider = spec.get("provider")
        extractor = spec.get("extractor")
        if not callable(provider):
            return self._empty_card(spec, "unavailable", "provider_unavailable", fingerprint)
        payload = provider()
        if not isinstance(payload, dict):
            return self._empty_card(spec, "unavailable", "non_object_payload", fingerprint)
        card = extractor(payload) if callable(extractor) else {}
        if not isinstance(card, dict):
            card = {}
        status = str(card.get("status") or ("fresh" if payload.get("enabled", True) is not False else "unavailable")).lower()
        if status == "loaded":
            status = "fresh"
        if status not in {"fresh", "stale", "unavailable", "still_computing", "error"}:
            status = "fresh"
        now = _now_iso()
        interval = self._interval(spec)
        ttl = self._ttl(spec)
        return {
            "card_id": spec.get("key"),
            "key": spec.get("key"),
            "title": spec.get("title"),
            "status": status,
            "primary_value": str(card.get("primary_value", "Loaded")),
            "secondary_value": str(card.get("secondary_value", "")),
            "detail_value": str(card.get("detail_value", "")),
            "generated_at": now,
            "generated_monotonic": time.time(),
            "age_seconds": 0.0,
            "ttl_seconds": ttl,
            "source_endpoint": spec.get("source_endpoint"),
            "last_success_at": now if status in {"fresh", "stale"} else "",
            "last_error": str(card.get("error_reason", "")),
            "error_reason": str(card.get("error_reason", "")),
            "compute_duration_seconds": round(max(0.0, time.time() - started), 3),
            "source_fingerprint": fingerprint,
            "last_fingerprint": fingerprint,
            "changed_since_last_snapshot": False,
            "refresh_reason": "source_changed",
            "refresh_interval_seconds": interval,
            "refresh_priority": self._weight(spec),
            "refresh_status": "complete" if status in {"fresh", "stale"} else status,
            "next_refresh_due": datetime.fromtimestamp(time.time() + interval, UTC).isoformat().replace("+00:00", "Z"),
        }

    def refresh_card(self, spec: dict[str, Any], *, force: bool = False, timeout_seconds: float = 2.5) -> dict[str, Any]:
        key = str(spec.get("key") or spec.get("title") or "unknown")
        fingerprint = self.source_fingerprint(spec)
        prior = self.load_card(key)
        now = time.time()
        prior_age = _safe_float((prior or {}).get("age_seconds"), 999999.0)
        ttl = self._ttl(spec)
        changed = bool(prior and prior.get("source_fingerprint") != fingerprint)
        if prior and not force and not changed and prior_age <= ttl:
            out = dict(prior)
            out["changed_since_last_snapshot"] = False
            out["refresh_reason"] = "skipped_no_change"
            out["refresh_status"] = "skipped_no_change"
            return out
        reason = "manual_refresh" if force else ("no_prior_snapshot" if not prior else ("source_changed" if changed else "max_age_exceeded"))
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._compute_card, spec, fingerprint)
        try:
            card = future.result(timeout=max(0.5, min(5.0, float(timeout_seconds))))
            card["refresh_reason"] = reason
            card["changed_since_last_snapshot"] = bool(changed or not prior)
            self._atomic_write(key, card)
            return card
        except TimeoutError:
            if prior:
                out = dict(prior)
                out["status"] = "stale"
                out["changed_since_last_snapshot"] = bool(changed)
                out["refresh_reason"] = reason
                out["refresh_status"] = "compute_running_using_stale_valid_snapshot"
                out["last_error"] = f"timeout_after_{timeout_seconds}s"
                return out
            card = self._empty_card(spec, "unavailable", f"timeout_after_{timeout_seconds}s", fingerprint)
            card["refresh_reason"] = reason
            self._atomic_write(key, card)
            return card
        except Exception as exc:
            if prior:
                out = dict(prior)
                out["status"] = "stale"
                out["refresh_reason"] = reason
                out["refresh_status"] = "error_using_stale_valid_snapshot"
                out["last_error"] = str(exc)[:180]
                return out
            return self._empty_card(spec, "error", f"card_error: {str(exc)[:180]}", fingerprint)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def snapshot(self, card_specs: list[dict[str, Any]], *, force_refresh: bool = False, time_budget_seconds: float = 7.0) -> dict[str, Any]:
        started = time.time()
        cards: list[dict[str, Any]] = []
        for spec in card_specs:
            if not isinstance(spec, dict):
                continue
            remaining = max(0.0, float(time_budget_seconds) - (time.time() - started))
            prior = self.load_card(str(spec.get("key") or spec.get("title") or "unknown"))
            if remaining < 0.6 and prior:
                card = dict(prior)
                card["status"] = "stale" if card.get("status") == "fresh" else card.get("status", "stale")
                card["refresh_status"] = "budget_exhausted_using_stale_valid_snapshot"
                card["refresh_reason"] = "skipped_no_change"
            elif remaining < 0.6:
                fingerprint = self.source_fingerprint(spec)
                card = self._empty_card(spec, "unavailable", "precompute_budget_exhausted_no_prior_snapshot", fingerprint)
                card["refresh_status"] = "budget_exhausted_no_prior_snapshot"
                card["refresh_reason"] = "no_prior_snapshot"
                self._atomic_write(str(spec.get("key") or spec.get("title") or "unknown"), card)
            else:
                card = self.refresh_card(spec, force=force_refresh, timeout_seconds=min(2.5, max(0.5, remaining)))
            cards.append(card)
        elapsed = max(0.0, time.time() - started)
        return self.payload_from_cards(cards, elapsed_seconds=elapsed, load_strategy="freshness_aware_card_snapshot_store")

    def payload_from_cards(self, cards: list[dict[str, Any]], *, elapsed_seconds: float = 0.0, load_strategy: str = "card_snapshot_store") -> dict[str, Any]:
        fresh = [c for c in cards if c.get("status") == "fresh"]
        stale = [c for c in cards if c.get("status") == "stale"]
        computing = [c for c in cards if c.get("status") == "still_computing"]
        unavailable = [c for c in cards if c.get("status") in {"unavailable", "error"}]
        slowest = max(cards, key=lambda c: _safe_float(c.get("compute_duration_seconds"), 0.0), default=None)
        ages = [_safe_float(c.get("age_seconds"), 0.0) for c in cards]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "freshness_aware_snapshot_store",
            "local_only": True,
            "writes_files": True,
            "api_calls_used": 0,
            "advanced_metrics_snapshot_v1": True,
            "snapshot_generated_at": _now_iso(),
            "snapshot_age_seconds": 0.0,
            "snapshot_elapsed_seconds": round(elapsed_seconds, 3),
            "cards": cards,
            "total_cards": len(cards),
            "cards_loaded": len(fresh) + len(stale),
            "cards_failed": len(computing) + len(unavailable),
            "fresh_cards": len(fresh),
            "stale_cards_count": len(stale),
            "computing_cards": len(computing),
            "unavailable_cards_count": len(unavailable),
            "stale_cards": [c.get("key") for c in stale],
            "unavailable_cards": [c.get("key") for c in unavailable],
            "timeout_cards": [c.get("key") for c in computing],
            "slowest_card": slowest,
            "oldest_snapshot_age_seconds": round(max(ages), 3) if ages else 0,
            "average_compute_time": round(sum(_safe_float(c.get("compute_duration_seconds"), 0.0) for c in cards) / max(1, len(cards)), 3),
            "freshness_status": "fresh" if len(fresh) == len(cards) else ("stale_valid" if fresh or stale else "partial"),
            "load_strategy": load_strategy,
            "recommended_action": "serve_fresh_or_stale_card_snapshots_and_precompute_changed_cards_outside_ui_path",
        }

    def load_snapshot(self, card_specs: list[dict[str, Any]]) -> dict[str, Any]:
        cards = []
        for spec in card_specs:
            key = str((spec or {}).get("key") or (spec or {}).get("title") or "unknown")
            prior = self.load_card(key)
            if prior:
                cards.append(prior)
            else:
                cards.append(self._empty_card(spec, "still_computing", "no_prior_snapshot", self.source_fingerprint(spec)))
        return self.payload_from_cards(cards, elapsed_seconds=0.0, load_strategy="instant_card_snapshot_read")

    def start_warmup(self, card_specs: list[dict[str, Any]], *, force: bool = False, time_budget_seconds: float = 20.0) -> bool:
        with self._lock:
            if self._warmup_started and not force:
                return False
            self._warmup_started = True
            self._last_warmup_status = "running"
        def _run() -> None:
            started = time.time()
            try:
                self.snapshot(card_specs, force_refresh=force, time_budget_seconds=time_budget_seconds)
                self._last_warmup_status = "complete"
            except Exception as exc:
                self._last_warmup_status = f"error:{str(exc)[:120]}"
            finally:
                self._last_warmup_at = _now_iso()
        thread = threading.Thread(target=_run, name="advanced_metrics_precompute_warmup", daemon=True)
        thread.start()
        return True

    def freshness_status(self, card_specs: list[dict[str, Any]]) -> dict[str, Any]:
        started = time.time()
        payload = self.load_snapshot(card_specs)
        cards = list(payload.get("cards") or [])
        payload.update({
            "diagnostics_freshness_status_v1": True,
            "snapshot_load_time_seconds": round(max(0.0, time.time() - started), 3),
            "last_warmup_at": self._last_warmup_at,
            "warmup_status": self._last_warmup_status,
            "precompute_worker": {
                "enabled": True,
                "mode": "single_shot_safe_background_warmup",
                "uncontrolled_loop_enabled": False,
                "cpu_ram_limits": "bounded_by_small_thread_pool_and_per_card_timeouts",
            },
        })
        return payload
