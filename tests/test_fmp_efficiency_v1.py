from __future__ import annotations

import json
import time

import server_extend as module


class _EmptyResponse:
    status_code = 200
    text = "{}"

    @staticmethod
    def json():
        return {}


def _allow_fmp(monkeypatch):
    monkeypatch.setattr(module, "_extract_fmp_key", lambda: "fixture-key")
    monkeypatch.setattr(module, "_fmp_usage_governor_snapshot", lambda update=False: {
        "fmp_rest_governor_allowed": True,
        "fmp_hard_stop_active": False,
    })
    monkeypatch.setattr(module, "get_call_permission", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "record_call", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "record_error", lambda *_args, **_kwargs: None)


def test_empty_response_enters_negative_cache_and_expires(monkeypatch, tmp_path):
    cache_path = tmp_path / "fmp_enrichment_cache_v1.json"
    monkeypatch.setattr(module, "FMP_ENRICHMENT_CACHE_PATH", str(cache_path))
    _allow_fmp(monkeypatch)
    calls = []
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: calls.append(args[0]) or _EmptyResponse())

    first = module._fmp_small_endpoint_request("profile", "AAA", {"calls_made": 0, "bytes_used": 0}, "test")
    second_state = {"calls_made": 0, "bytes_used": 0, "suppressed_by_cooldown": 0}
    second = module._fmp_small_endpoint_request("profile", "AAA", second_state, "test")

    assert first["blocked_reason"] == "empty_response"
    assert second["blocked_reason"] == "negative_cache_cooldown"
    assert second_state["suppressed_by_cooldown"] == 1
    assert len(calls) == 1

    payload = json.loads(cache_path.read_text())
    payload["profile::AAA"]["expires_at"] = time.time() - 1
    cache_path.write_text(json.dumps(payload))
    third = module._fmp_small_endpoint_request("profile", "AAA", {"calls_made": 0, "bytes_used": 0}, "test")
    assert third["blocked_reason"] == "empty_response"
    assert len(calls) == 2


def test_enrichment_cache_is_bounded(monkeypatch, tmp_path):
    cache_path = tmp_path / "fmp_enrichment_cache_v1.json"
    monkeypatch.setattr(module, "FMP_ENRICHMENT_CACHE_PATH", str(cache_path))
    seeded = {
        f"profile::S{index}": {"ts": float(index), "payload": {"sector": "Technology"}, "bytes": 20}
        for index in range(module.FMP_ENRICHMENT_CACHE_MAX_ENTRIES + 3)
    }
    cache_path.write_text(json.dumps(seeded))
    module._fmp_enrichment_cache_set("profile", "LATEST", {"sector": "Technology"}, 20)
    payload = json.loads(cache_path.read_text())
    assert len(payload) <= module.FMP_ENRICHMENT_CACHE_MAX_ENTRIES
