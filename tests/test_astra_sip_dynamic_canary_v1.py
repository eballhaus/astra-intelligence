from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from engine.alpaca_ws_monitor import AlpacaWSMonitor
from engine.astra_sip_dynamic_canary_v1 import build_sip_dynamic_canary_selection_v1


def _row(symbol: str, lane: str, rank: int, *, generated_at: str = "2026-09-14T14:00:00Z", eligible: bool = True) -> dict:
    return {
        "symbol": symbol,
        "lane_ranked_entry_lane": lane,
        "lane_ranked_entry_funnel_v1": True,
        "lane_finalist": True,
        "lane_finalist_rank": rank,
        "qualified": eligible,
        "candidate_id": f"candidate-{symbol}-{lane}",
        "candidate_generated_at": generated_at,
        "candidate_source": "paper_opportunity_allocation_engine_v1",
    }


def _positions(count: int, lane: str = "DAY") -> list[dict]:
    return [
        {
            "symbol": f"OPEN{index:02d}",
            "lane_id": lane,
            "asset_type": "stock",
            "position_id": f"position-{index}",
        }
        for index in range(count)
    ]


class DynamicSipCanaryTests(unittest.TestCase):
    def test_managed_equities_are_pinned_and_crypto_is_excluded(self):
        positions = _positions(2) + [{"symbol": "ETH/USD", "lane_id": "CRYPTO", "asset_type": "crypto"}]
        result = build_sip_dynamic_canary_selection_v1(
            managed_positions=positions,
            now_epoch=1789395000,
        )
        selected = {row["symbol"] for row in result["symbols"]}
        self.assertTrue({"OPEN00", "OPEN01"}.issubset(selected))
        self.assertNotIn("ETH/USD", selected)
        self.assertEqual(result["managed_position_count"], 2)

    def test_only_qualified_existing_lane_finalists_enter_lane_allocations(self):
        rows = [
            _row("SCP1", "SCALP", 1),
            _row("DAY1", "DAY", 1),
            _row("SWG1", "SWING", 1),
            _row("REJECTED", "SCALP", 2, eligible=False),
            {**_row("NOT_FINAL", "DAY", 2), "lane_finalist": False},
            {**_row("WRONG_LANE", "DAY", 3), "lane_ranked_entry_lane": "CRYPTO"},
        ]
        result = build_sip_dynamic_canary_selection_v1(
            candidate_rows=rows,
            now_epoch=1789395000,
        )
        selected = {row["symbol"]: row for row in result["symbols"]}
        self.assertEqual(selected["SCP1"]["source_lane"], "SCALP")
        self.assertEqual(selected["DAY1"]["source_lane"], "DAY")
        self.assertEqual(selected["SWG1"]["source_lane"], "SWING")
        self.assertNotIn("REJECTED", selected)
        self.assertNotIn("NOT_FINAL", selected)
        self.assertNotIn("WRONG_LANE", selected)
        self.assertEqual(result["selection_source"], "paper_opportunity_allocation_engine_v1_lane_finalists")

    def test_preferred_total_and_six_candidate_slots_per_lane(self):
        rows = [
            _row(f"{lane}{rank:02d}", lane, rank)
            for lane in ("SCALP", "DAY", "SWING")
            for rank in range(1, 11)
        ]
        result = build_sip_dynamic_canary_selection_v1(candidate_rows=rows, now_epoch=1789395000)
        self.assertEqual(result["total_count"], 18)
        self.assertEqual(result["target_count"], 18)
        self.assertEqual(result["selected_candidate_count_by_lane"], {"SCALP": 6, "DAY": 6, "SWING": 6})
        self.assertLessEqual(result["total_count"], 24)

    def test_managed_positions_expand_target_to_hard_cap(self):
        rows = [
            _row(f"{lane}{rank:02d}", lane, rank)
            for lane in ("SCALP", "DAY", "SWING")
            for rank in range(1, 8)
        ]
        result = build_sip_dynamic_canary_selection_v1(
            candidate_rows=rows,
            managed_positions=_positions(19),
            now_epoch=1789395000,
        )
        self.assertEqual(result["target_count"], 24)
        self.assertEqual(result["managed_position_count"], 19)
        self.assertEqual(result["total_count"], 24)
        self.assertLessEqual(result["total_count"], 24)

    def test_sticky_selection_avoids_small_rank_changes_and_rotates_material_improvement(self):
        initial = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[_row("KEEP", "SCALP", 5), _row("NEAR", "SCALP", 6)],
            now_epoch=1789395000,
        )
        small_change = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[_row("KEEP", "SCALP", 5), _row("NEAR", "SCALP", 4)],
            previous_state=initial,
            now_epoch=1789395060,
        )
        self.assertIn("KEEP", {row["symbol"] for row in small_change["symbols"]})
        material_change = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[_row("KEEP", "SCALP", 5), _row("BETTER", "SCALP", 1)],
            previous_state=initial,
            now_epoch=1789395120,
        )
        self.assertIn("BETTER", {row["symbol"] for row in material_change["symbols"]})
        chosen = next(row for row in material_change["symbols"] if row["symbol"] == "BETTER")
        self.assertEqual(chosen["reason"], "EXISTING_LANE_FINALIST")
        self.assertEqual(chosen["provenance"], "paper_opportunity_allocation_engine_v1")

    def test_current_ineligible_candidate_leaves_selection_and_stale_input_only_holds_until_expiry(self):
        initial = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[_row("STICKY", "DAY", 1)],
            now_epoch=1789395000,
        )
        removed = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[],
            previous_state=initial,
            candidate_source_current=True,
            now_epoch=1789395060,
        )
        self.assertNotIn("STICKY", {row["symbol"] for row in removed["symbols"]})
        held = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[],
            previous_state=initial,
            candidate_source_current=False,
            now_epoch=1789395060,
        )
        self.assertIn("STICKY", {row["symbol"] for row in held["symbols"]})
        expired = build_sip_dynamic_canary_selection_v1(
            candidate_rows=[],
            previous_state=initial,
            candidate_source_current=False,
            now_epoch=1789395700,
        )
        self.assertNotIn("STICKY", {row["symbol"] for row in expired["symbols"]})

    def test_selection_is_deterministic_and_diagnostic_only(self):
        args = {
            "candidate_rows": [_row(f"SYM{rank:02d}", "SWING", rank) for rank in range(1, 8)],
            "managed_positions": _positions(1, "SWING"),
            "now_epoch": 1789395000,
        }
        first = build_sip_dynamic_canary_selection_v1(**args)
        second = build_sip_dynamic_canary_selection_v1(**args)
        self.assertEqual(first, second)
        self.assertTrue(first["diagnostic_only"])
        self.assertFalse(first["execution_authority"])
        self.assertEqual(first["broker_actions"], 0)
        self.assertEqual(first["truth_mutations"], 0)

    def test_monitor_dynamic_set_is_independent_from_iex_and_crypto_sets(self):
        monitor = AlpacaWSMonitor()
        with patch.dict(os.environ, {"ASTRA_PROCESS_ROLE": "api"}, clear=False):
            monitor.configure_symbols(
                open_position_symbols=["OPEN1"],
                open_crypto_position_symbols=["ETH/USD"],
                near_entry_symbols=["IEXCANDIDATE"],
            )
            primary = monitor._stream_desired("equity")
            crypto = monitor._stream_desired("crypto")
            result = monitor.configure_sip_canary_symbols(
                ["SWING1", "SCALP1", "DAY1"],
                {"schema_version": "astra_sip_dynamic_canary_v1", "diagnostic_only": True},
            )
            self.assertTrue(result["ok"])
            self.assertEqual(monitor._stream_desired("equity"), primary)
            self.assertEqual(monitor._stream_desired("crypto"), crypto)
            self.assertEqual(monitor._stream_desired("equity_shadow"), {"SCALP1", "DAY1", "SWING1"})
            self.assertEqual(monitor._active_sip_canary_symbols(), ("DAY1", "SCALP1", "SWING1"))

    def test_monitor_rejects_over_cap_without_changing_previous_canary(self):
        monitor = AlpacaWSMonitor()
        monitor.configure_sip_canary_symbols(["AAPL"])
        result = monitor.configure_sip_canary_symbols([f"SYM{i}" for i in range(25)])
        self.assertFalse(result["ok"])
        self.assertEqual(monitor._active_sip_canary_symbols(), ("AAPL",))

    def test_dynamic_canary_promotes_only_selected_fresh_sip_observations(self):
        monitor = AlpacaWSMonitor()
        native = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        with patch.dict(
            os.environ,
            {
                "ASTRA_PROCESS_ROLE": "api",
                "ASTRA_ALPACA_WS_ENABLED": "1",
                "ASTRA_ALPACA_WS_FEED": "iex",
                "ASTRA_ALPACA_WS_SHADOW_ENABLED": "1",
                "ASTRA_ALPACA_WS_SHADOW_FEED": "sip",
                "ASTRA_ALPACA_SIP_ENTITLEMENT_VERIFIED": "1",
            },
            clear=False,
        ):
            monitor.configure_symbols(symbols=["AAPL"])
            monitor.configure_sip_canary_symbols(["MSFT"], {"diagnostic_only": True})
            monitor._record_message({"T": "q", "S": "MSFT", "bp": 100.0, "ap": 100.1, "t": native}, shadow=True)
            selected = monitor._sip_canary_quote("MSFT")
            unselected = monitor._sip_canary_quote("AAPL")
        self.assertEqual(selected["provider_used"], "ALPACA_WS_SIP_CANARY")
        self.assertIsNone(unselected)
        self.assertTrue(selected["market_observation_only"])
        self.assertTrue(selected["canary_only"])


if __name__ == "__main__":
    unittest.main()
