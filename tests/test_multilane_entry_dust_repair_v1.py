"""Focused regression coverage for the current-candidate risk handoff."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_canonical_ownership_contract_v1 import classify_dust_position_v1
from engine.astra_premarket_certification_v1 import (
    build_pretrade_decision_contract,
    enrich_candidate_for_pretrade_contract,
)
from engine.astra_unified_position_lifecycle_v1 import build_position_management_overlay_v1
from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.paper_autopilot import PaperAutopilotEngine, _execution_trace_event


def _future() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")


def _candidate(lane: str) -> dict:
    horizon = "day_trade" if lane == "DAY" else "scalp"
    return {
        "symbol": f"{lane}X", "candidate_id": f"cand-{lane}", "recommendation_id": f"rec-{lane}",
        "lane_id": lane, "paper_entry_horizon_style": horizon,
        "expected_hold_minutes": 45 if lane == "SCALP" else 390,
        "strategy_archetype": "momentum_breakout", "thesis": "Current momentum is supported.",
        "thesis_supporting_conditions": ["current momentum"],
        "expected_return_pct": 3.0, "price": 100.0, "confidence": 80.0,
        "generated_at": _future(), "expires_at": _future(),
    }


class MultiLaneEntryDustRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="astra_entry_dust_")
        self.addCleanup(self.tmp.cleanup)
        self.engine = PaperAutopilotEngine(
            db_path=os.path.join(self.tmp.name, "paper.db"),
            state_path=os.path.join(self.tmp.name, "state.json"), enabled=False,
        )

    def _dust_cleanup_engine(self, positions, close_result=None):
        class StubBroker:
            def __init__(self, current_positions):
                self.current_positions = current_positions
                self.close_requests = []

            def safety_status(self):
                return {
                    "enabled_requested": True, "paper_mode_verified": True,
                    "broker_execution_enabled": True, "live_endpoint_detected": False,
                    "live_endpoint_rejected": True, "safety_reasons": [],
                }

            def positions(self):
                return {"ok": True, "positions": list(self.current_positions)}

            def orders(self, **_kwargs):
                return {"ok": True, "orders": []}

            def close_paper_position(self, symbol, qty):
                self.close_requests.append((symbol, qty))
                return close_result or {"ok": True, "paper_order_submitted": True, "order": {"id": "dust-order"}}

        broker = StubBroker(positions)
        self.engine.alpaca_paper_broker = broker
        return broker

    def _attach_and_contract(self, lane: str, *, valid_until: float | None = None):
        candidate = _candidate(lane)
        self.engine._runtime_state["equity_risk_envelopes_snapshot_v1"] = {
            "status": "CURRENT", "valid_until_epoch": valid_until or (time.time() + 60.0),
            "rows": [{
                "symbol": candidate["symbol"], "atr_pct": 1.25,
                "downside_range_pct": 1.6, "quote_execution_eligible": True,
                "quote_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "completed_bar_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "bar_evidence": {"resolution": "15Min", "count": 6},
            }],
        }
        enriched = enrich_candidate_for_pretrade_contract(
            self.engine._attach_current_equity_risk_evidence_v1(candidate)
        )
        return enriched, build_pretrade_decision_contract(enriched)

    def test_day_contract_consumes_current_symbol_risk_observation(self):
        enriched, contract = self._attach_and_contract("DAY")
        self.assertEqual(enriched["equity_risk_evidence_join_v1"]["status"], "CURRENT_SYMBOL_MATCHED")
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["expected_downside_range"])
        self.assertTrue(contract["expected_drawdown"])
        self.assertTrue(contract["expected_return_per_day_range"])

    def test_scalp_contract_consumes_current_symbol_risk_observation(self):
        enriched, contract = self._attach_and_contract("SCALP")
        self.assertEqual(enriched["equity_risk_evidence_join_v1"]["status"], "CURRENT_SYMBOL_MATCHED")
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertTrue(contract["expected_return_per_day_range"])

    def test_expired_or_missing_risk_observation_still_fails_closed(self):
        enriched, contract = self._attach_and_contract("DAY", valid_until=time.time() - 1.0)
        self.assertNotIn("equity_risk_evidence_join_v1", enriched)
        self.assertFalse(contract["order_ready_allowed"])
        self.assertIn("expected_downside_range", contract["missing_required_fields"])

    def test_full_cycle_risk_refresh_receives_exact_current_equity_candidates(self):
        current = [_candidate("DAY"), _candidate("SCALP"), {"symbol": "BTCUSD", "asset_class": "crypto"}]
        observed = {}

        def refresh():
            observed["handoff"] = dict(self.engine._runtime_state.get("equity_risk_candidate_handoff_v1") or {})
            return {"status": "CURRENT", "provider_calls_used": 2, "broker_actions_used": 0}

        self.engine.refresh_equity_risk_envelopes_fn = refresh
        result = self.engine._refresh_current_equity_risk_envelopes_v1(current)
        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual([row["symbol"] for row in observed["handoff"]["rows"]], ["DAYX", "SCALPX"])
        self.assertNotIn("BTCUSD", [row["symbol"] for row in observed["handoff"]["rows"]])

    def test_day_batch_handoff_preserves_current_symbols_for_contract_enrichment(self):
        """A partial lane slice must not be replaced by a later source read."""
        current = [{**_candidate("DAY"), "symbol": f"DAY{index}"} for index in range(5)]
        observed = {}

        def refresh():
            observed["rows"] = list(
                (self.engine._runtime_state.get("equity_risk_candidate_handoff_v1") or {}).get("rows") or []
            )
            self.engine._runtime_state["equity_risk_envelopes_snapshot_v1"] = {
                "status": "CURRENT",
                "valid_until_epoch": time.time() + 60.0,
                "rows": [
                    {
                        "symbol": row["symbol"],
                        "atr_pct": 1.25,
                        "downside_range_pct": 1.6,
                        "quote_execution_eligible": True,
                        "quote_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "completed_bar_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "bar_evidence": {"resolution": "15Min", "count": 6},
                    }
                    for row in observed["rows"]
                ],
            }
            return {"status": "CURRENT", "provider_calls_used": 2, "broker_actions_used": 0}

        self.engine.refresh_equity_risk_envelopes_fn = refresh
        self.engine._refresh_current_equity_risk_envelopes_v1(current)
        self.assertEqual([row["symbol"] for row in observed["rows"]], [row["symbol"] for row in current])
        for candidate in current:
            enriched = enrich_candidate_for_pretrade_contract(
                self.engine._attach_current_equity_risk_evidence_v1(candidate),
                current_candidates=current,
            )
            contract = build_pretrade_decision_contract(enriched)
            self.assertEqual(contract["contract_status"], "VALID")
            self.assertEqual(contract["missing_required_fields"], [])

    def test_capacity_trace_preserves_attached_current_risk_contract(self):
        """A capacity rejection must not erase current risk evidence."""
        candidate = _candidate("DAY")
        self.engine._runtime_state["equity_risk_envelopes_snapshot_v1"] = {
            "status": "CURRENT",
            "valid_until_epoch": time.time() + 60.0,
            "rows": [{
                "symbol": candidate["symbol"], "atr_pct": 1.25,
                "downside_range_pct": 1.6, "quote_execution_eligible": True,
                "quote_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "completed_bar_timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "bar_evidence": {"resolution": "15Min", "count": 6},
            }],
        }
        trace = _execution_trace_event(
            self.engine._attach_current_equity_risk_evidence_v1(candidate),
            eligible=False,
            selected=False,
            decision_reason="max_new_positions_per_cycle_reached",
        )
        contract = trace["pretrade_decision_contract"]
        self.assertEqual(contract["contract_status"], "VALID")
        self.assertEqual(contract["missing_required_fields"], [])
        self.assertEqual(trace["equity_risk_evidence_join_v1"]["status"], "CURRENT_SYMBOL_MATCHED")

    def test_risk_handoff_preserves_one_current_candidate_per_equity_lane(self):
        current = [
            {**_candidate("DAY"), "symbol": f"DAY{index}"}
            for index in range(11)
        ] + [
            {**_candidate("SCALP"), "symbol": "SCALP1"},
            {**_candidate("DAY"), "symbol": "SWING1", "lane_id": "SWING", "paper_entry_horizon_style": "swing_trade"},
        ]
        handoff = self.engine._publish_equity_risk_candidate_handoff_v1(current)
        self.assertEqual(len(handoff), 12)
        self.assertEqual({row["lane_id"] for row in handoff}, {"DAY", "SCALP", "SWING"})
        self.assertIn("SCALP1", [row["symbol"] for row in handoff])
        self.assertIn("SWING1", [row["symbol"] for row in handoff])

    def test_canonical_dust_is_not_normal_managed_position(self):
        position = {"symbol": "DUST", "qty": 0.0005, "market_value": 0.001, "lane_id": "DAY"}
        dust = classify_dust_position_v1(position)
        overlay = build_position_management_overlay_v1(position)
        self.assertFalse(dust["counts_toward_exposure"])
        self.assertTrue(dust["counts_toward_reconciliation"])
        self.assertEqual(overlay["classification"], "BROKER_DUST_MONITORED")
        self.assertFalse(overlay["normal_position_management"])
        self.assertFalse(overlay["full_risk_included"])

    def test_cleanup_submits_only_exact_equity_dust_and_preserves_meaningful_positions(self):
        broker = self._dust_cleanup_engine([
            {"symbol": "DUST", "qty": "0.000500", "market_value": "0.01", "asset_class": "us_equity"},
            {"symbol": "KEEP", "qty": "2", "market_value": "200", "asset_class": "us_equity"},
        ])
        result = self.engine.cleanup_verified_broker_dust_v1()
        self.assertTrue(result["ok"])
        self.assertEqual(result["submitted"], ["DUST"])
        self.assertEqual(result["meaningful_untouched"], ["KEEP"])
        self.assertEqual(broker.close_requests, [("DUST", "0.000500")])

    def test_cleanup_quarantines_unrepresentable_dust_without_submission(self):
        broker = self._dust_cleanup_engine([
            {"symbol": "TINY", "qty": "0.0000000001", "market_value": "0.01", "asset_class": "us_equity"},
        ])
        result = self.engine.cleanup_verified_broker_dust_v1()
        self.assertEqual(result["unclosable"], ["TINY"])
        self.assertEqual(broker.close_requests, [])
        records = self.engine._runtime_state["broker_dust_cleanup_v1"]
        self.assertEqual(records["TINY"]["status"], "BROKER_UNCLOSABLE_DUST")

    def test_cleanup_uses_exact_native_close_for_crypto_dust(self):
        broker = self._dust_cleanup_engine([
            {"symbol": "BTCUSD", "qty": "0.000000500", "market_value": "0.01", "asset_class": "crypto"},
        ])
        result = self.engine.cleanup_verified_broker_dust_v1()
        self.assertEqual(result["submitted"], ["BTCUSD"])
        self.assertEqual(broker.close_requests, [("BTCUSD", "0.000000500")])

    def test_rejected_dust_close_stays_quarantined_without_false_closure(self):
        self._dust_cleanup_engine(
            [{"symbol": "DUST", "qty": "0.000500", "market_value": "0.01", "asset_class": "us_equity"}],
            close_result={"ok": False, "error": "minimum quantity not supported"},
        )
        result = self.engine.cleanup_verified_broker_dust_v1()
        self.assertEqual(result["submitted"], [])
        self.assertEqual(result["unclosable"], ["DUST"])
        self.assertEqual(self.engine._runtime_state["broker_dust_cleanup_v1"]["DUST"]["status"], "BROKER_UNCLOSABLE_DUST")
        quarantine = self.engine._runtime_state["broker_dust_quarantine_v1"]["broker:DUST"]
        self.assertFalse(quarantine["operational_lifecycle"])
        self.assertFalse(quarantine["strict_truth_eligible"])

    def test_adapter_close_preserves_exact_nine_decimal_quantity(self):
        broker = AlpacaPaperBroker()
        requests = []
        broker.safety_status = lambda: {"broker_execution_enabled": True, "live_endpoint_detected": False}
        broker._request = lambda method, path, body=None: (requests.append((method, path, body)) or (True, {"id": "close-1", "status": "accepted"}, ""))
        result = broker.close_paper_position("BTCUSD", "0.000000500")
        self.assertTrue(result["ok"])
        self.assertEqual(result["qty"], "0.000000500")
        self.assertEqual(requests, [("DELETE", "/positions/BTCUSD?qty=0.000000500", None)])

    def test_adapter_close_rejects_unrepresentable_quantity_without_request(self):
        broker = AlpacaPaperBroker()
        broker.safety_status = lambda: {"broker_execution_enabled": True, "live_endpoint_detected": False}
        broker._request = lambda *_args, **_kwargs: self.fail("broker request must not occur")
        result = broker.close_paper_position("TINY", "0.0000000001")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "close_quantity_precision_unsupported")


if __name__ == "__main__":
    unittest.main()
