"""Regression coverage for exact same-session horizon handoffs.

These tests use only local fixtures.  They do not invoke broker submission,
market providers, or the worker lifecycle.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import engine.paper_autopilot as paper_autopilot_module
from engine.astra_position_lane_horizon_recovery_v1 import build_position_lane_horizon_recovery_v1
from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_sentinel_causal_handoff_integrity_v1 import (
    causal_facts_from_position_horizon_handoffs_v1,
    classify_causal_handoff_facts_v1,
)
from engine.astra_unified_position_advisory_v1 import (
    build_position_exit_readiness_v1,
    build_unified_position_advisory_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


STAMP = "2026-08-18T14:30:00Z"


class _FilledOrderBroker:
    def __init__(self, order):
        self._order = dict(order)
        self.order_calls = 0

    def order(self, order_id):
        self.order_calls += 1
        return {"ok": True, "order": dict(self._order)}


def _broker(symbol: str, fill_id: str) -> dict:
    return {
        "symbol": symbol, "asset_class": "us_equity", "qty": "1",
        "entry_fill_id": fill_id, "entry_timestamp": STAMP,
    }


def _evidence(symbol: str, lane: str, horizon: str, *, fill_id: str = "fill-1", contract: bool = True) -> dict:
    metadata = {
        "metadata_generation": "V1_MANDATORY", "lane_id": lane,
        "intended_horizon": horizon, "candidate_id": f"cand-{symbol}",
    }
    if contract:
        metadata.update({
            "expected_max_hold": "same_session",
            "same_session_exit_required": True,
            "overnight_allowed": False,
        })
    return {
        "symbol": symbol, "asset_type": "stock", "position_id": f"pos-{symbol}",
        "entry_order_id": f"order-{symbol}", "entry_fill_id": fill_id,
        "entry_timestamp": STAMP, "entry_filled_at": STAMP, "lane_id": lane,
        "canonical_horizon": horizon, "current_reconciled": True,
        "position_owner": lane, "exit_policy_owner": lane,
        "entry_metadata_generation": "V1_MANDATORY",
        "entry_metadata_json": metadata,
    }


def _advisory_inputs(symbol: str) -> tuple[dict, dict]:
    return (
        {"positions": [{"symbol": symbol, "canonical_lane_status": "RESOLVED", "first_causal_blocker": "EVIDENCE_CURRENT"}]},
        {"positions": [{"symbol": symbol, "recommendation": "HOLD", "confidence": "HIGH", "first_causal_blocker": "EVIDENCE_CURRENT"}]},
    )


class CanonicalHorizonExitReadinessEnforcementTests(unittest.TestCase):
    def _recovery(self, symbol: str, lane: str, horizon: str, *, contract: bool = True) -> dict:
        return build_position_lane_horizon_recovery_v1(
            {symbol: _broker(symbol, f"fill-{symbol}")},
            evidence_rows=[_evidence(symbol, lane, horizon, fill_id=f"fill-{symbol}", contract=contract)],
        )

    def test_scalp_contract_propagates_from_reconciliation_to_lifecycle_and_readiness(self):
        broker = _FilledOrderBroker({
            "id": "order-GEHC", "client_order_id": "client-GEHC", "symbol": "GEHC", "status": "filled",
            "filled_qty": "1", "filled_avg_price": "73.094", "filled_at": STAMP, "paper_mode_verified": True,
        })
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            engine = PaperAutopilotEngine(db_path=str(root / "paper.db"), state_path=str(root / "state.json"), alpaca_paper_broker=broker)
            metadata = _evidence("GEHC", "SCALP", "scalp", fill_id="order-GEHC")["entry_metadata_json"]
            with engine._connect() as conn:
                conn.execute(
                    """INSERT INTO paper_positions(position_id,symbol,asset_type,status,quantity,entry_price,provisional_entry_price,source_broker_order_id,source_client_order_id,entry_order_id,entry_timestamp,lane_id,position_owner,exit_policy_owner,entry_metadata_generation,entry_metadata_json,row_json,lifecycle_notes,created_at,updated_at)
                    VALUES ('pos-GEHC','GEHC','stock','PENDING_ENTRY',0,73.0,73.0,'order-GEHC','client-GEHC','order-GEHC',?,'SCALP','SCALP','SCALP','V1_MANDATORY',?,'{}','{}',?,?)""",
                    (STAMP, json.dumps(metadata), STAMP, STAMP),
                )
                conn.commit()
            captured: list[dict] = []
            with patch.object(paper_autopilot_module, "create_lifecycle_record", lambda row: captured.append(dict(row))):
                result = engine._reconcile_entry_price_lineage_v1({"broker_reconciliation_active": True, "broker_position_by_symbol": {}})
            self.assertEqual(result["repaired"], 1)
            self.assertEqual(len(captured), 1)
            self.assertIs(captured[0]["same_session_exit_required"], True)
            self.assertIs(captured[0]["overnight_allowed"], False)
            self.assertEqual(captured[0]["expected_max_hold"], "same_session")

            with engine._connect() as conn:
                persisted = dict(conn.execute("SELECT * FROM paper_positions WHERE position_id='pos-GEHC'").fetchone())
            # The native exit owner consumes this materialized row, so this
            # proves the persisted contract reaches it without a new owner.
            exit_owner_row = engine._materialize_open_position_entry_contract(persisted)
            self.assertIs(exit_owner_row["same_session_exit_required"], True)
            self.assertIs(exit_owner_row["overnight_allowed"], False)
            self.assertEqual(exit_owner_row["expected_max_hold"], "same_session")

            recovery = self._recovery("GEHC", "SCALP", "scalp")
            recovered = recovery["positions"][0]
            self.assertEqual(recovered["lane"], "SCALP")
            self.assertEqual(recovered["horizon_contract_status"], "RESOLVED")
            evidence, triage = _advisory_inputs("GEHC")
            readiness = build_position_exit_readiness_v1({"GEHC": {"symbol": "GEHC"}}, evidence=evidence, triage=triage, recovery=recovery)
            row = readiness["positions"][0]
            self.assertEqual(row["recommendation"], "SAME_SESSION_EXIT_REQUIRED")
            self.assertEqual(row["generic_recommendation"], "HOLD")
            self.assertTrue(row["advisory_only"])
            self.assertEqual(row["execution_authority"], "DISABLED")

    def test_day_contract_propagates_without_generic_watch_shadowing(self):
        recovery = self._recovery("RIVN", "DAY", "day_trade")
        evidence, triage = _advisory_inputs("RIVN")
        readiness = build_position_exit_readiness_v1({"RIVN": {"symbol": "RIVN"}}, evidence=evidence, triage=triage, recovery=recovery)
        advisory = build_unified_position_advisory_v1(
            {"RIVN": {"symbol": "RIVN"}}, evidence=evidence, triage=triage,
            exit_readiness=readiness, recovery=recovery,
        )
        exit_row = readiness["positions"][0]
        unified_row = advisory["positions"][0]
        self.assertEqual(exit_row["horizon_exit_requirement"]["status"], "CANONICAL_SAME_SESSION_EXIT_REQUIRED")
        self.assertEqual(unified_row["final_advisory"], "SAME_SESSION_EXIT_REQUIRED")
        self.assertEqual(unified_row["generic_advisory"], "HOLD")
        self.assertFalse(unified_row["legacy_position"])
        self.assertEqual(unified_row["canonical_identity_status"], "RESOLVED")

    def test_missing_horizon_evidence_remains_unavailable_and_is_not_invented(self):
        recovery = self._recovery("OLD", "DAY", "day_trade", contract=False)
        recovered = recovery["positions"][0]
        self.assertEqual(recovered["horizon_contract_status"], "UNAVAILABLE")
        self.assertIsNone(recovered["same_session_exit_required"])
        evidence, triage = _advisory_inputs("OLD")
        readiness = build_position_exit_readiness_v1({"OLD": {"symbol": "OLD"}}, evidence=evidence, triage=triage, recovery=recovery)
        self.assertEqual(readiness["positions"][0]["recommendation"], "HOLD")

    def test_genuine_legacy_position_remains_legacy(self):
        evidence, triage = _advisory_inputs("LEGACY")
        advisory = build_unified_position_advisory_v1(
            {"LEGACY": {"symbol": "LEGACY"}}, evidence=evidence, triage=triage,
            recovery={"positions": [{"symbol": "LEGACY", "canonical_identity_status": "UNAVAILABLE"}]},
        )
        self.assertTrue(advisory["positions"][0]["legacy_position"])

    def test_sentinel_reports_only_actual_horizon_or_identity_handoff_loss(self):
        recovery = self._recovery("PTON", "DAY", "day_trade")
        mismatch_readiness = {"positions": [{"symbol": "PTON", "horizon_exit_requirement": {}}]}
        mismatch_advisory = {"positions": [{"symbol": "PTON", "canonical_identity_status": "LEGACY"}]}
        facts = causal_facts_from_position_horizon_handoffs_v1(recovery, mismatch_readiness, mismatch_advisory)
        result = classify_causal_handoff_facts_v1(facts)
        self.assertEqual(len(result["signals"]), 2)
        self.assertTrue(all(row["category"] == "CAUSAL_HANDOFF_LOSS" for row in result["signals"]))

        evidence, triage = _advisory_inputs("PTON")
        readiness = build_position_exit_readiness_v1({"PTON": {"symbol": "PTON"}}, evidence=evidence, triage=triage, recovery=recovery)
        advisory = build_unified_position_advisory_v1({"PTON": {"symbol": "PTON"}}, evidence=evidence, triage=triage, exit_readiness=readiness, recovery=recovery)
        healthy = classify_causal_handoff_facts_v1(causal_facts_from_position_horizon_handoffs_v1(recovery, readiness, advisory))
        self.assertEqual(healthy["signals"], [])

    def test_existing_sentinel_scanner_consumes_horizon_handoff_context(self):
        recovery = self._recovery("GEHC", "SCALP", "scalp")
        with tempfile.TemporaryDirectory() as directory:
            payload = ContinuousSystemIntegrityScannerV1(directory).run_if_due(
                worker_state={"active_worker_present": True, "process_role": "PAPER_AUTOPILOT_WORKER"},
                runtime_state={}, safety={},
                context={
                    "position_lane_horizon_recovery": recovery,
                    "position_exit_readiness": {"positions": [{"symbol": "GEHC", "horizon_exit_requirement": {}}]},
                    "unified_position_advisory": {"positions": [{"symbol": "GEHC", "canonical_identity_status": "RESOLVED"}]},
                },
            )
        findings = payload["causal_handoff_integrity_v1"]["signals"]
        self.assertTrue(any(row["causal_finding_v1"]["field"] == "same_session_exit_required" for row in findings))


if __name__ == "__main__":
    unittest.main()
