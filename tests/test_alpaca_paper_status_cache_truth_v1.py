"""Regression coverage for cache-first broker-truth reporting."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import server_extend


class AlpacaPaperStatusCacheTruthTests(unittest.TestCase):
    def setUp(self):
        self._cache_before = copy.deepcopy(server_extend._CACHE.get("alpaca_paper_status_v1"))
        self._trace_cache_before = copy.deepcopy(server_extend._CACHE.get("paper_autopilot_authoritative_trace_v3"))

    def tearDown(self):
        if self._cache_before is None:
            server_extend._CACHE.pop("alpaca_paper_status_v1", None)
        else:
            server_extend._CACHE["alpaca_paper_status_v1"] = self._cache_before
        if self._trace_cache_before is None:
            server_extend._CACHE.pop("paper_autopilot_authoritative_trace_v3", None)
        else:
            server_extend._CACHE["paper_autopilot_authoritative_trace_v3"] = self._trace_cache_before

    def test_stale_verified_snapshot_is_not_replaced_by_zero_fallback(self):
        server_extend._CACHE["alpaca_paper_status_v1"] = {
            "ts": 100.0,
            "data": {
                "paper_mode_verified": True,
                "open_positions_count": 42,
                "open_orders_count": 0,
                "broker_snapshot_status": "FRESH_READ_ONLY",
                "broker_snapshot_source": "alpaca_paper_account_positions_open_orders",
                "broker_live_endpoint_allowed": False,
            },
        }
        broker = unittest.mock.Mock()
        broker.safety_status.return_value = {"paper_mode_verified": True}

        with patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend.time, "time", return_value=201.0
        ):
            result = server_extend.alpaca_paper_status_v1()

        self.assertEqual(result["open_positions_count"], 42)
        self.assertTrue(result["cache_hit"])
        self.assertTrue(result["broker_status_refresh_deferred"])
        self.assertEqual(result["broker_snapshot_status"], "STALE_CACHED_READ_ONLY")
        self.assertEqual(result["broker_status_refresh_deferred_reason"], "cached_broker_snapshot_stale_refresh_requires_force_true")
        broker.status.assert_not_called()

    def test_cold_cache_status_fallback_reads_canonical_worker_state_without_broker_refresh(self):
        server_extend._CACHE.pop("alpaca_paper_status_v1", None)
        broker = unittest.mock.Mock()
        broker.safety_status.return_value = {
            "paper_mode_verified": True,
            "paper_endpoint_detected": True,
            "live_endpoint_detected": False,
            "live_endpoint_rejected": True,
            "broker_execution_enabled": True,
        }
        worker_state = {
            "worker_generation_id": "test-generation",
            "cycle_count": 12,
            "heartbeat_at": "2026-08-05T13:30:00Z",
            "last_cycle_utc": "2026-08-05T13:30:00Z",
        }

        with patch.object(server_extend, "ALPACA_PAPER_BROKER", broker), patch.object(
            server_extend, "_canonical_worker_state", return_value=worker_state
        ), patch.object(server_extend, "_astra_evidence_state_json", return_value={}):
            result = server_extend.alpaca_paper_status_v1()

        self.assertTrue(result["paper_mode_verified"])
        self.assertTrue(result["broker_status_refresh_deferred"])
        self.assertFalse(result["broker_live_endpoint_allowed"])
        self.assertEqual(result["paper_autopilot_status"]["last_cycle_utc"], "2026-08-05T13:30:00Z")
        broker.status.assert_not_called()

    def test_authoritative_lane_trace_prefers_persisted_worker_contract(self):
        """A GET diagnostic must not replace worker-enriched contracts."""
        persisted = {
            "last_autopilot_cycle_at": "2026-08-10T19:42:00Z",
            "per_candidate_decision_trace": [{
                "symbol": "RIVN",
                "lane_id": "DAY",
                "pretrade_decision_contract": {
                    "contract_status": "VALID",
                    "missing_required_fields": [],
                },
            }],
        }
        server_extend._CACHE.pop("paper_autopilot_authoritative_trace_v3", None)
        with patch.object(server_extend, "_paper_autopilot_persisted_trace_v1", return_value=(persisted, "paper_autopilot_persisted_state")), patch.object(
            server_extend.PAPER_AUTOPILOT, "operational_dry_run"
        ) as dry_run:
            result = server_extend._paper_autopilot_authoritative_trace_v3(force=True)

        self.assertEqual(result["trace_owner"], "PaperAutopilot.canonical_worker_checkpoint")
        self.assertEqual(result["trace_source"], "paper_autopilot_persisted_state")
        self.assertFalse(result["dry_run_only"])
        self.assertEqual(result["per_candidate_decision_trace"][0]["symbol"], "RIVN")
        dry_run.assert_not_called()

    def test_authoritative_lane_trace_does_not_evaluate_unobserved_cache_rows(self):
        """No worker candidate is evidence pending, not a contract defect."""
        server_extend._CACHE.pop("paper_autopilot_authoritative_trace_v3", None)
        with patch.object(server_extend, "_paper_autopilot_persisted_trace_v1", return_value=({}, "paper_autopilot_unavailable")), patch.object(
            server_extend.PAPER_AUTOPILOT, "operational_dry_run"
        ) as dry_run:
            result = server_extend._paper_autopilot_authoritative_trace_v3(force=True)

        self.assertEqual(result["final_blocker_reason"], "NO_CURRENT_WORKER_CANDIDATES")
        self.assertEqual(result["per_candidate_decision_trace"], [])
        self.assertFalse(result["dry_run_only"])
        dry_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
