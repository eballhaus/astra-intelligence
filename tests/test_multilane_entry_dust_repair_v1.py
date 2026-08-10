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
from engine.paper_autopilot import PaperAutopilotEngine


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

    def _dust_cleanup_engine(self, positions):
        class StubBroker:
            def __init__(self, current_positions):
                self.current_positions = current_positions
                self.orders_submitted = []

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

            def submit_paper_order(self, order):
                self.orders_submitted.append(dict(order))
                return {"ok": True, "paper_order_submitted": True, "order": {"id": "dust-order"}}

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
        self.assertEqual(len(broker.orders_submitted), 1)
        self.assertEqual(broker.orders_submitted[0]["symbol"], "DUST")
        self.assertEqual(broker.orders_submitted[0]["qty"], 0.0005)

    def test_cleanup_quarantines_unrepresentable_or_crypto_dust_without_submission(self):
        broker = self._dust_cleanup_engine([
            {"symbol": "TINY", "qty": "0.0000001", "market_value": "0.01", "asset_class": "us_equity"},
            {"symbol": "BTC/USD", "qty": "0.000001", "market_value": "0.01", "asset_class": "crypto"},
        ])
        result = self.engine.cleanup_verified_broker_dust_v1()
        self.assertEqual(set(result["unclosable"]), {"TINY", "BTC/USD"})
        self.assertEqual(broker.orders_submitted, [])
        records = self.engine._runtime_state["broker_dust_cleanup_v1"]
        self.assertEqual(records["TINY"]["status"], "BROKER_UNCLOSABLE_DUST")
        self.assertEqual(records["BTC/USD"]["first_causal_blocker"], "NATIVE_CRYPTO_EXIT_CONTRACT_REQUIRED")


if __name__ == "__main__":
    unittest.main()
