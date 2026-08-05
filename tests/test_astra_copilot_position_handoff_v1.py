"""Canonical handoff from current paper positions to the Copilot priority queue.

Covers:
- current meaningful positions outrank stale legacy/dust rows and candidates
- legacy/reconciliation/dust positions are suppressed
- returned rows carry numeric confidence, market regime, price, daily change
- frontend confidence formatting uses a categorical-safe helper
"""
from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

import server_extend


ROOT = pathlib.Path(__file__).resolve().parents[1]
COPILOT_PAGE = ROOT / "astra_dashboard" / "ui" / "src" / "dashboard" / "pages" / "CopilotPage.jsx"


def _position_row(
    symbol: str,
    *,
    lane_id: str = "DAY",
    source_bucket: str = "paper_autopilot_controlled_profit_seeking_exploration",
    current_price: float = 10.0,
    current_return: float = 0.5,
    hold_seconds: float = 0.0,
    review_state: str = "monitoring",
    lifecycle_stage: str = "monitoring",
    confidence: float = 75.0,
    market_regime: str = "RANGE_LOW_VOL",
    quantity: float = 10.0,
    row_json: dict | None = None,
) -> dict:
    return {
        "position_id": f"pos-{symbol}",
        "symbol": symbol,
        "asset_type": "stock",
        "status": "OPEN",
        "lane_id": lane_id,
        "source_bucket": source_bucket,
        "entry_price": 10.0,
        "quantity": quantity,
        "qty": quantity,
        "latest_price": current_price,
        "unrealized_pnl_percent": current_return,
        "lifecycle_notes": {
            "current_price": current_price,
            "current_return_percent": current_return,
            "quote_quality": "live",
            "lifecycle_stage": lifecycle_stage,
            "review_state": review_state,
            "hold_seconds": hold_seconds,
            "hold_posture": "hold",
        },
        "row_json": row_json
        or {
            "confidence": confidence,
            "regime_context": market_regime,
            "market_regime": market_regime,
            "summary": f"{symbol} is monitored.",
            "asset_type": "stock",
            "asset_class": "equity",
            "best_horizon_style": "day_trade",
            "trade_horizon_style": "day_trade",
            "sector": "Technology",
        },
    }


class CurrentPositionHandoffTests(unittest.TestCase):
    def _patch_positions(self, rows: list[dict]):
        return patch.object(server_extend.PAPER_AUTOPILOT, "paper_positions", return_value=rows)

    def test_current_positions_outrank_stale_candidates(self):
        current = [
            _position_row("SG", current_price=5.78, current_return=-2.86, hold_seconds=31392, review_state="deteriorating"),
            _position_row("PTON", current_price=6.17, current_return=-6.16, hold_seconds=31740, review_state="deteriorating"),
            _position_row("RIVN", current_price=15.73, current_return=0.22, hold_seconds=32102),
        ]
        stale_candidates = [
            {"symbol": "AAL", "action": "BUY_NOW", "confidence": 85.0},
            {"symbol": "ALNY", "action": "BUY_NOW", "confidence": 82.0},
            {"symbol": "CRSP", "action": "BUY_NOW", "confidence": 80.0},
            {"symbol": "IONQ", "action": "BUY_NOW", "confidence": 78.0},
            {"symbol": "KLAC", "action": "BUY_NOW", "confidence": 76.0},
        ]
        with self._patch_positions(current), patch.object(
            server_extend,
            "_latest_top_buys_runtime_snapshot",
            return_value={"stocks": {"final": stale_candidates}},
        ):
            payload = server_extend._astra_copilot_suite_v1(limit=5)

        top = payload["top_actions"]
        symbols = [a["symbol"] for a in top]
        self.assertEqual(symbols[:3], ["SG", "PTON", "RIVN"])
        # Current positions occupy the priority queue ahead of any stale candidates.
        self.assertTrue(all(a["position_state"] == "POSITION_OPEN" for a in top[:3]))
        for action in top[:3]:
            self.assertIsInstance(action["confidence"], float)
            self.assertIn("price", action)
            self.assertIn("daily_change", action)
            self.assertIn("market_regime", action)
            self.assertEqual(action["position_state"], "POSITION_OPEN")

    def test_legacy_managed_positions_suppressed(self):
        rows = [
            _position_row("SG", lane_id="DAY", source_bucket="paper_autopilot_controlled_profit_seeking_exploration"),
            _position_row("AAL", lane_id="", source_bucket="LEGACY_MANAGED"),
            _position_row("KLAC", lane_id="", source_bucket=""),
        ]
        with self._patch_positions(rows):
            actions = server_extend._current_position_actions_v1(limit=5)
        self.assertEqual([a["symbol"] for a in actions], ["SG"])

    def test_dust_recon_positions_suppressed(self):
        rows = [
            _position_row("SG", lane_id="DAY"),
            {
                "position_id": "recon:XLB:1",
                "symbol": "XLB",
                "status": "OPEN",
                "lane_id": "",
                "source_bucket": None,
                "lifecycle_notes": {
                    "current_price": 51.0,
                    "current_return_percent": 0.1,
                    "quote_quality": "live",
                    "lifecycle_stage": "monitoring",
                    "review_state": "monitoring",
                },
                "row_json": {},
            },
        ]
        with self._patch_positions(rows):
            actions = server_extend._current_position_actions_v1(limit=5)
        self.assertEqual([a["symbol"] for a in actions], ["SG"])

    def test_real_fractional_dust_position_is_suppressed(self):
        rows = [
            _position_row("SG", lane_id="DAY", current_price=5.78),
            {
                **_position_row("PH", lane_id="SCALP", current_price=992.65),
                "quantity": 0.000000926,
                "qty": 0.000000926,
            },
            {
                **_position_row("WDAY", lane_id="DAY", current_price=171.72),
                "quantity": 0.000000842,
                "qty": 0.000000842,
            },
        ]
        with self._patch_positions(rows):
            actions = server_extend._current_position_actions_v1(limit=5)

        self.assertEqual([a["symbol"] for a in actions], ["SG"])

    def test_position_action_numeric_confidence_and_market_regime(self):
        row = _position_row("SG", confidence=75.63, market_regime="TREND_UP")
        with self._patch_positions([row]):
            actions = server_extend._current_position_actions_v1(limit=5)
        self.assertEqual(len(actions), 1)
        action = actions[0]
        self.assertEqual(action["confidence"], 75.63)
        self.assertEqual(action["market_regime"], "TREND_UP")
        self.assertEqual(action["market_regime_context"], "TREND_UP")
        self.assertEqual(action["price"], 10.0)
        self.assertEqual(action["daily_change"], 0.5)
        self.assertEqual(action["position_state"], "POSITION_OPEN")
        self.assertTrue(action["paper_autopilot_eligible"])
        self.assertTrue(action["advisory_only"])

    def test_urgent_positions_sorted_before_hold_positions(self):
        rows = [
            _position_row("RIVN", current_return=0.22, hold_seconds=32102),
            _position_row("PTON", current_return=-6.16, hold_seconds=31740, review_state="deteriorating"),
            _position_row("SG", current_return=-2.86, hold_seconds=31392, review_state="deteriorating"),
        ]
        with self._patch_positions(rows):
            actions = server_extend._current_position_actions_v1(limit=5)
        symbols = [a["symbol"] for a in actions]
        self.assertEqual(symbols, ["SG", "PTON", "RIVN"])
        self.assertEqual(actions[0]["canonical_lifecycle_state"], "LOSING_MOMENTUM")
        self.assertEqual(actions[1]["canonical_lifecycle_state"], "LOSING_MOMENTUM")
        self.assertEqual(actions[2]["canonical_lifecycle_state"], "HOLD")

    def test_frontend_confidence_formatting_uses_format_helper(self):
        source = COPILOT_PAGE.read_text(encoding="utf-8")
        self.assertIn("function formatConfidence", source)
        self.assertIn("formatConfidence(row.confidence)", source)
        self.assertIn("formatConfidence(selectedRow.confidence)", source)
        self.assertNotIn("${row.confidence}%", source)
        self.assertNotIn("${selectedRow.confidence}%", source)


if __name__ == "__main__":
    unittest.main()
