from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_provider_consumption_telemetry_v1 import (
    build_provider_consumption_telemetry_v1,
    load_provider_consumption_telemetry_v1,
    save_provider_consumption_telemetry_v1,
)
from engine.provider_router import ProviderRouter
from engine.paper_autopilot import PaperAutopilotEngine


class FmpProviderConsumptionTests(unittest.TestCase):
    def test_smart_budget_default_does_not_hard_limit_fmp(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASTRA_FMP_REST_HARD_LIMIT_ENABLED", None)
            self.assertFalse(ProviderRouter._fmp_probe_hard_limited())

    def test_explicit_hard_limit_remains_respected(self):
        with patch.dict(os.environ, {"ASTRA_FMP_REST_HARD_LIMIT_ENABLED": "1"}, clear=False):
            self.assertTrue(ProviderRouter._fmp_probe_hard_limited())

    def test_profile_response_is_accepted_without_exposing_secret(self):
        router = ProviderRouter()
        router._key_for = lambda *_args: "test-key"  # type: ignore[method-assign]
        router._temp_fmp_rest_disabled = False
        router._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            {"_list": [{"symbol": "AAA", "companyName": "Fixture", "sector": "Technology"}]}, 200, "", 2.0
        )
        result = router.fetch_fmp_profile_context("AAA")
        self.assertEqual(result["response_state"], "SUCCESS")
        self.assertFalse(result["secret_exposed"])

    def test_earnings_and_news_contexts_are_symbol_scoped_and_parsed(self):
        router = ProviderRouter()
        router._key_for = lambda *_args: "test-key"  # type: ignore[method-assign]
        router._temp_fmp_rest_disabled = False
        responses = iter((
            ({"_list": [{"symbol": "AAA", "date": "2026-08-01", "eps": 1.2}]}, 200, "", 2.0),
            ({"_list": [{"symbol": "AAA", "title": "Fixture headline", "publishedDate": "2026-07-24T00:00:00Z"}]}, 200, "", 2.0),
        ))
        router._request = lambda *_args, **_kwargs: next(responses)  # type: ignore[method-assign]
        earnings = router.fetch_fmp_earnings_context("AAA")
        news = router.fetch_fmp_news_context("AAA")
        self.assertEqual(earnings["response_state"], "SUCCESS")
        self.assertEqual(earnings["normalized_fields"]["earnings_date"], "2026-08-01")
        self.assertEqual(news["response_state"], "SUCCESS")
        self.assertEqual(news["normalized_fields"]["headline"], "Fixture headline")
        self.assertFalse(earnings["secret_exposed"])

    def test_telemetry_records_accepted_consumed_response_and_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "fmp_efficiency_ledger_v1.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-24T00:00:00Z", "endpoint_family": "company_profile", "ok": True, "useful_fields_count": 3, "bytes_actual_if_available": 91, "status_code": 200}) + "\n")
            telemetry = build_provider_consumption_telemetry_v1(
                state_dir=directory, configured=True, key_fingerprint="deadbeef",
                consumer_events=[{
                    "endpoint_family": "company_profile",
                    "consumer": "legacy_position_risk_triage_v1",
                    "consumer_record_id": "legacy-triage:AAA",
                    "symbol": "AAA",
                    "assigned": True,
                    "consumed": True,
                }],
            )
            provider = telemetry["providers"][0]
            self.assertEqual(provider["responses_accepted"], 1)
            self.assertEqual(provider["last_consumer"], "legacy_position_risk_triage_v1")
            self.assertEqual(provider["bytes_received"], 91)
            family = provider["endpoint_families"][0]
            self.assertEqual(family["responses_assigned"], 1)
            self.assertEqual(family["responses_consumed"], 1)
            self.assertTrue(provider["telemetry_complete"])
            self.assertNotIn("test-key", json.dumps(telemetry))
            save_provider_consumption_telemetry_v1(telemetry, directory)
            self.assertEqual(load_provider_consumption_telemetry_v1(directory)["provider_count"], 1)

    def test_governor_block_is_not_counted_as_provider_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "fmp_efficiency_ledger_v1.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-24T00:00:00Z", "ok": False, "blocked_reason": "call_limit"}) + "\n")
            telemetry = build_provider_consumption_telemetry_v1(state_dir=directory, configured=True, key_fingerprint="deadbeef")
            provider = telemetry["providers"][0]
            self.assertEqual(provider["governor_blocked"], 1)
            self.assertEqual(provider["failed_calls"], 0)
            self.assertEqual(provider["network_sent"], 0)

    def test_accepted_but_unassigned_remains_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "fmp_efficiency_ledger_v1.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-24T00:00:00Z", "endpoint_family": "company_profile", "ok": True, "useful_fields_count": 2, "status_code": 200}) + "\n")
            telemetry = build_provider_consumption_telemetry_v1(state_dir=directory, configured=True, key_fingerprint="deadbeef")
            provider = telemetry["providers"][0]
            self.assertEqual(provider["responses_accepted"], 1)
            self.assertFalse(provider["telemetry_complete"])
            self.assertEqual(provider["endpoint_families"][0]["responses_assigned"], 0)

    def test_telemetry_window_excludes_prior_worker_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "fmp_efficiency_ledger_v1.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": "2026-07-24T00:00:00Z", "endpoint_family": "company_profile", "ok": True, "useful_fields_count": 2}) + "\n")
                handle.write(json.dumps({"timestamp": "2026-07-24T01:00:00Z", "endpoint_family": "company_profile", "ok": True, "useful_fields_count": 2}) + "\n")
            telemetry = build_provider_consumption_telemetry_v1(state_dir=directory, configured=True, key_fingerprint="deadbeef", window_start="2026-07-24T00:30:00Z")
            self.assertEqual(telemetry["providers"][0]["responses_accepted"], 1)

    def test_scanner_detects_configured_unused_provider_and_success_not_consumed(self):
        telemetry = {"providers": [{"provider": "FMP", "configured": True, "attempted_calls": 0, "responses_accepted": 1, "last_consumer": ""}]}
        signals, _waiting, _compliance = ContinuousSystemIntegrityScannerV1._signals(
            {"provider_consumption_telemetry": telemetry}, {}, 10
        )
        kinds = {row["kind"] for row in signals}
        self.assertIn("CONFIGURED_PROVIDER_UNUSED", kinds)
        self.assertIn("PROVIDER_SUCCESS_NOT_CONSUMED", kinds)

    def test_worker_verification_is_bounded_and_never_creates_trade_artifacts(self):
        class Router:
            def deliberate_fmp_probe(self, symbol):
                return {"probe_attempted": True, "probe_success": True, "status_code": 200, "response_bytes": 17}
        with tempfile.TemporaryDirectory() as directory:
            engine = object.__new__(PaperAutopilotEngine)
            engine.state_path = os.path.join(directory, "paper_autopilot_state.json")
            engine._runtime_state = {}
            engine._legacy_swing_fmp_router = Router()
            engine._legacy_swing_fmp_fetcher = lambda symbol: {"response_state": "SUCCESS", "http_status": 200, "records_valid": 1, "normalized_fields": {"sector": "Technology"}}
            engine._legacy_swing_fmp_historical_fetcher = lambda symbol, **_kwargs: {"response_state": "SUCCESS", "http_status": 200, "records_valid": 2}
            result = engine._run_fmp_production_verification_v1({"AAA": {"symbol": "AAA"}})
            self.assertEqual(result["attempted_count"], 3)
            self.assertEqual(result["successful_count"], 3)
            self.assertFalse(result["candidate_created"])
            self.assertFalse(result["order_created"])
            self.assertEqual(result["broker_actions_used"], 0)
            evidence = engine._runtime_state["legacy_swing_fmp_evidence"]["fmp-production-profile:AAA"]
            self.assertEqual(evidence["acknowledgement_state"], "CONSUMED_BY_LEGACY_POSITION_RISK_TRIAGE_V1")


if __name__ == "__main__":
    unittest.main()
