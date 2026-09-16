from __future__ import annotations

import unittest

from engine.astra_position_lane_horizon_recovery_v1 import build_position_lane_horizon_recovery_v1
from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract
from engine.paper_autopilot import _normalize_paper_entry_bridge


STAMP = "2026-09-16T14:00:00Z"
GEHC_POSITION_ID = "3ac4501e-e101-4366-8dd8-4be3e67031b8"


def _candidate(**extra: object) -> dict[str, object]:
    return {
        "symbol": "GEHC",
        "asset_class": "equity",
        "lane_id": "SCALP",
        "paper_entry_horizon_style": "scalp",
        "paper_entry_horizon_source": "candidate_explicit_horizon",
        "lane_assignment_source": "candidate_explicit_lane",
        "candidate_id": "cand-gehc",
        "selection_id": "sel-gehc",
        "candidate_generated_at": STAMP,
        **extra,
    }


def _broker_position() -> dict[str, object]:
    return {
        "symbol": "GEHC",
        "asset_class": "us_equity",
        "qty": "1",
        "avg_entry_price": "100",
        "current_price": "101",
        "entry_timestamp": STAMP,
        "entry_fill_id": "fill-gehc",
    }


class ScalpHorizonContractPropagationTests(unittest.TestCase):
    def test_explicit_scalp_duration_survives_bridge_registry_and_entry_contract(self) -> None:
        bridged = _normalize_paper_entry_bridge(
            _candidate(
                expected_hold_window="30m-45m",
                expected_hold_minutes=45.0,
                expected_hold_days=0.03125,
                expected_max_hold="same_session",
            )
        )
        self.assertEqual(bridged["expected_hold_window"], "30m-45m")
        self.assertEqual(bridged["expected_hold_minutes"], 45.0)
        self.assertEqual(bridged["expected_max_hold"], "30m-45m")
        contract = bridged["entry_lane_horizon_contract_v1"]
        self.assertEqual(contract["expected_hold_window"], "30m-45m")
        self.assertEqual(contract["expected_hold_minutes"], 45.0)
        self.assertEqual(contract["expected_max_hold"], "30m-45m")

    def test_specific_window_wins_over_generic_same_session_marker(self) -> None:
        row = apply_trade_lane_contract(
            _candidate(expected_max_hold="same_session", expected_hold_window="15m-60m"),
            now=STAMP,
        )
        self.assertEqual(row["expected_max_hold"], "15m-60m")
        self.assertTrue(row["same_session_exit_required"])
        self.assertFalse(row["overnight_allowed"])

    def test_recovery_preserves_duration_and_exact_gehc_identity(self) -> None:
        evidence = {
            "symbol": "GEHC",
            "asset_type": "stock",
            "position_id": GEHC_POSITION_ID,
            "entry_fill_id": "fill-gehc",
            "entry_order_id": "order-gehc",
            "entry_timestamp": STAMP,
            "entry_filled_at": STAMP,
            "lane_id": "SCALP",
            "canonical_horizon": "scalp",
            "current_reconciled": True,
            "position_owner": "SCALP",
            "exit_policy_owner": "SCALP",
            "entry_metadata_json": {
                "lane": "SCALP",
                "horizon": "scalp",
                "expected_max_hold": "same_session",
                "expected_hold_window": "15m-60m",
                "expected_hold_minutes": 60.0,
                "same_session_exit_required": True,
                "overnight_allowed": False,
            },
            "recovery_source_type": "ACTIVE_POSITION_LIFECYCLE",
        }
        recovered = build_position_lane_horizon_recovery_v1(
            {"GEHC": _broker_position()}, evidence_rows=[evidence]
        )["positions"][0]
        self.assertEqual(recovered["canonical_position_id"], GEHC_POSITION_ID)
        self.assertEqual(recovered["canonical_lifecycle_id"], GEHC_POSITION_ID)
        self.assertEqual(recovered["expected_max_hold"], "15m-60m")
        self.assertEqual(recovered["expected_hold_window"], "15m-60m")
        self.assertEqual(recovered["expected_hold_minutes"], 60.0)
        self.assertTrue(recovered["same_session_exit_required"])
        self.assertFalse(recovered["overnight_allowed"])

    def test_missing_scalp_duration_uses_existing_bounded_policy_default(self) -> None:
        row = _normalize_paper_entry_bridge(_candidate())
        self.assertEqual(row["expected_hold_window"], "15m-60m")
        self.assertEqual(row["expected_hold_minutes"], 60.0)
        self.assertEqual(row["expected_max_hold"], "15m-60m")

    def test_day_and_swing_defaults_remain_unchanged(self) -> None:
        day = _normalize_paper_entry_bridge(
            _candidate(symbol="DAYX", lane_id="DAY", paper_entry_horizon_style="day_trade")
        )
        swing = _normalize_paper_entry_bridge(
            _candidate(symbol="SWINGX", lane_id="SWING", paper_entry_horizon_style="swing_trade")
        )
        self.assertEqual((day["expected_hold_window"], day["expected_hold_minutes"]), ("2h-EOD", 390.0))
        self.assertEqual((swing["expected_hold_window"], swing["expected_hold_minutes"]), ("1d-10d+", 14400.0))
        self.assertTrue(day["same_session_exit_required"])
        self.assertFalse(day["overnight_allowed"])
        self.assertFalse(swing["same_session_exit_required"])
        self.assertTrue(swing["overnight_allowed"])


if __name__ == "__main__":
    unittest.main()
