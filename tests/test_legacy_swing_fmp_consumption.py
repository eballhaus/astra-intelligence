import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_unified_position_lifecycle_v1 import build_legacy_swing_required_evidence_v1, classify_legacy_swing_lifecycle_v1
from engine.paper_autopilot import PaperAutopilotEngine
from engine.provider_router import ProviderRouter


class _FmpSuccess:
    def __init__(self):
        self.calls = []

    def __call__(self, symbol):
        self.calls.append(symbol)
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return {
            "provider": "FMP", "endpoint_family": "company_profile", "symbol": symbol,
            "requested_at": now, "response_at": now,
            "http_status": 200, "authentication_state": "PRESENT", "entitlement_state": "UNKNOWN",
            "response_state": "SUCCESS", "records_received": 1, "records_valid": 1,
            "normalized_fields": {"company_name": "Fixture Co", "sector": "Technology", "industry": "Software"},
        }


class _FmpFailure:
    def __call__(self, symbol):
        return {
            "provider": "FMP", "endpoint_family": "company_profile", "symbol": symbol,
            "response_state": "AUTHENTICATION_FAILED", "error_category": "missing_fmp_credential",
        }


def _engine(fetcher):
    engine = object.__new__(PaperAutopilotEngine)
    engine._runtime_state = {}
    engine._legacy_swing_fmp_fetcher = fetcher
    return engine


def _registry():
    return {
        "activation-a": {
            "activation_id": "activation-a", "baseline_id": "legacy-forward:asset-a", "position_id": "asset-a",
            "symbol": "AAA", "legacy_activation_timestamp": "2026-07-15T12:00:00Z", "activation_price": 10,
        }
    }


class LegacySwingFmpConsumptionTests(unittest.TestCase):
    def test_existing_router_normalizes_a_valid_profile_response(self):
        router = ProviderRouter()
        router._key_for = lambda *_args: "test-key"  # type: ignore[method-assign]
        router._temp_fmp_rest_disabled = False
        router._request = lambda *_args, **_kwargs: (  # type: ignore[method-assign]
            {"_list": [{"symbol": "AAA", "companyName": "Fixture Co", "sector": "Technology", "industry": "Software"}]}, 200, "", 1.0
        )
        result = router.fetch_fmp_profile_context("AAA")
        self.assertEqual(result["response_state"], "SUCCESS")
        self.assertEqual(result["normalized_fields"]["sector"], "Technology")
        self.assertFalse(result["secret_exposed"])

    def test_missing_or_stale_fmp_evidence_triggers_bounded_worker_refresh(self):
        fetcher = _FmpSuccess()
        engine = _engine(fetcher)
        records, activity = engine._refresh_legacy_swing_fmp_evidence(_registry())
        self.assertEqual(fetcher.calls, ["AAA"])
        self.assertEqual(activity["requests_attempted_this_cycle"], 1)
        self.assertEqual(records["activation-a"]["response_state"], "SUCCESS")
        self.assertEqual(records["activation-a"]["records_stored"], 1)
        # A fresh canonical record is reused without another provider request.
        engine._refresh_legacy_swing_fmp_evidence(_registry())
        self.assertEqual(fetcher.calls, ["AAA"])

    def test_prior_valid_record_is_retained_and_labeled_stale_after_failure(self):
        engine = _engine(_FmpFailure())
        stale_at = (datetime.now(UTC) - timedelta(hours=7)).isoformat().replace("+00:00", "Z")
        engine._runtime_state["legacy_swing_fmp_evidence"] = {
            "activation-a": {
                "record_id": "legacy-fmp:company-profile:activation-a", "symbol": "AAA",
                "response_state": "SUCCESS", "as_of": stale_at,
                "normalized_fields": {"sector": "Technology"}, "retry_count": 0,
            }
        }
        records, _activity = engine._refresh_legacy_swing_fmp_evidence(_registry())
        record = records["activation-a"]
        self.assertEqual(record["response_state"], "STALE_PRIOR_USED")
        self.assertEqual(record["freshness_state"], "STALE")
        self.assertEqual(record["normalized_fields"]["sector"], "Technology")

    def test_fmp_record_is_consumed_by_the_thesis_evidence_builder_without_inventing_a_thesis(self):
        evidence = build_legacy_swing_required_evidence_v1(
            {"symbol": "AAA", "current_price": 10, "fmp_thesis_context": {
                "record_id": "fmp-a", "response_state": "SUCCESS", "endpoint_family": "company_profile",
                "normalized_fields": {"sector": "Technology", "industry": "Software"},
            }},
            {"baseline_id": "baseline-a", "activation_price": 10},
        )
        thesis = evidence["THESIS_STATE"]
        self.assertEqual(thesis["status"], "CURRENT")
        self.assertEqual(thesis["thesis_state"], "UNKNOWN")
        self.assertEqual(thesis["source"], "FMP.company_profile")
        row = {"symbol": "AAA", "current_price": 10, "momentum_state": "HEALTHY", "thesis_state": "UNKNOWN", "liquidity_state": "ADEQUATE"}
        classified = classify_legacy_swing_lifecycle_v1(row, evidence={"evidence_rows": [{"source": "current_direct", "available": True, "consumed": True}]}, confidence=0.9)
        self.assertNotEqual(classified["classification"], "THESIS_BROKEN")

    def test_worker_persists_consumer_acknowledgement_and_influence_without_broker_actions(self):
        engine = _engine(_FmpSuccess())
        engine._alpaca_safety_snapshot = lambda: {"paper_mode_verified": True, "live_endpoint_detected": False}  # type: ignore[method-assign]
        engine._runtime_state["legacy_forward_activations"] = _registry()
        result = engine._refresh_legacy_swing_canary_pre_submit({
            "AAA": {"symbol": "AAA", "asset_id": "asset-a", "qty": 2, "market_value": 20, "current_price": 10, "unrealized_plpc": 0},
        })
        record = engine._runtime_state["legacy_swing_fmp_evidence"]["activation-a"]
        self.assertTrue(result["CANARY_CONFIGURATION_CONSUMED_BY_WORKER"])
        self.assertTrue(record["consumer_acknowledged"])
        self.assertEqual(record["acknowledgement_state"], "CONSUMED_BY_UNIFIED_DECISION")
        self.assertIn(record["influence_state"], {"NEUTRAL", "BLOCKING"})
        self.assertEqual(engine._runtime_state["legacy_swing_canary"]["broker_actions"], 0)


if __name__ == "__main__":
    unittest.main()
