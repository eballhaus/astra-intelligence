"""Final-selected crypto candidate submission must honor a genuinely fresh
provider-native quote.

Regression contract for the final worker preflight path
(``_open_position_from_row`` -> ``_merge_latest_quote_for_submission`` ->
``_crypto_execution_integrity_gate``).  The merge must promote the freshly
retrieved provider observation into the authoritative ``provider_quote_timestamp``
field that ``candidate_execution_integrity`` reads first, and must never let a
stale rotation/ranking row timestamp (or a local retrieval time) masquerade as
the executed market evidence.  Failing closed on stale/missing/provider-failure
quotes is preserved exactly.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from engine.candidate_execution_integrity_v1 import candidate_execution_integrity
from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset_seconds: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _crypto_row(**overrides) -> dict:
    row = {
        "symbol": "BTC/USD",
        "asset_class": "crypto",
        "asset_type": "crypto",
        "price": 100.0,
        "current_price": 100.0,
        "quote_quality": "live",
        "candidate_id": "crypto:btc",
        "recommendation_id": "recommendation:btc",
        "entry_lane_horizon_contract_v1": {},
        "paper_limits_ok": True,
    }
    row.update(overrides)
    return row


def _engine(
    quote: dict | None = None,
    weight: list = None,
) -> PaperAutopilotEngine:
    calls = weight
    directory = tempfile.TemporaryDirectory(prefix="astra_final_quote_")

    def _quote(_symbol, _asset):
        if calls is not None:
            calls.append(1)
        return quote or {}

    engine = PaperAutopilotEngine(
        db_path=os.path.join(directory.name, "paper.db"),
        state_path=os.path.join(directory.name, "state.json"),
        enabled=False,
        get_latest_row_fn=_quote,
    )
    engine._tmpdir = directory
    return engine


class FinalCandidateFreshCryptoQuoteTests(unittest.TestCase):
    def _merge(self, row: dict, quote: dict | None) -> dict:
        engine = _engine()
        self.addCleanup(engine._tmpdir.cleanup)
        return engine._merge_latest_quote_for_submission(row, quote or {}, 100.0)

    def test_fresh_provider_quote_is_promoted_at_submission(self):
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
            },
        )
        self.assertTrue(merged["valid_quote"])
        self.assertTrue(merged["trusted_quote_for_buys"])
        self.assertIsNotNone(merged["provider_quote_timestamp"])
        self.assertEqual(merged["market_observation_timestamp"], merged["provider_quote_timestamp"])
        self.assertEqual(merged["freshness_result"], "FRESH")
        self.assertTrue(merged["final_candidate_refresh_succeeded"])
        self.assertEqual(merged["provider_calls_added"], 0)

    def test_fresh_provider_quote_passes_final_integrity_gate(self):
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
                "bid": 100.0,
                "ask": 100.1,
                "volume_24h": 1000.0,
                "data_quality_score": 90.0,
            },
        )
        result = candidate_execution_integrity(
            merged,
            supported_pairs={"BTC/USD"},
            tradable_pairs={"BTC/USD"},
            lane_state="LANE_PAPER_ACTIVE_BOUNDED",
            paper_mode_verified=True,
            broker_reconciliation_ok=True,
            kill_switch_enabled=False,
        )
        # Freshness must read the freshly promoted provider timestamp. Other
        # gates (spread/liquidity/capacity/horizon) are out of scope here and
        # fail only because this offline fixture omits their evidence.
        self.assertEqual(result["gate_status"]["timestamp_freshness"], "PASS")
        self.assertIn(result["first_causal_blocker"]["gate"], {
            "quote_spread", "volume_liquidity", "data_quality",
            "capacity_concentration", "confidence_ranking", "horizon_assignment",
        })

    def test_stale_quote_still_fails_closed(self):
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(-45),
                "market_source_type": "QUOTE",
            },
        )
        self.assertFalse(merged["valid_quote"])
        self.assertFalse(merged["trusted_quote_for_buys"])
        self.assertEqual(merged["quote_assignment_blocker"], "STALE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertIsNone(merged.get("provider_quote_timestamp"))
        self.assertIsNone(merged["quote_age_seconds"])
        self.assertFalse(merged["final_candidate_refresh_succeeded"])
        self.assertEqual(merged["freshness_result"], "STALE")

    def test_missing_provider_timestamp_fails_closed(self):
        merged = self._merge(
            _crypto_row(),
            {"symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0, "provider_used": "ALPACA"},
        )
        self.assertFalse(merged["valid_quote"])
        self.assertFalse(merged["trusted_quote_for_buys"])
        self.assertIsNone(merged.get("provider_quote_timestamp"))
        self.assertEqual(merged["quote_assignment_blocker"], "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_provider_failure_still_fails_closed(self):
        merged = self._merge(_crypto_row(), {})
        self.assertFalse(merged["valid_quote"])
        self.assertFalse(merged["trusted_quote_for_buys"])
        self.assertIsNone(merged.get("provider_quote_timestamp"))
        self.assertEqual(merged["freshness_result"], "UNAVAILABLE")

    def test_local_retrieval_time_cannot_masquerade_as_provider_timestamp(self):
        # A bare local ``timestamp`` (retrieval clock) must not become quote time.
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "timestamp": _iso(),
                "retrieval_timestamp": _iso(),
            },
        )
        self.assertFalse(merged["valid_quote"])
        self.assertFalse(merged["trusted_quote_for_buys"])
        self.assertEqual(merged["quote_assignment_blocker"], "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_future_provider_timestamp_fails_closed(self):
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(5000),
                "market_source_type": "QUOTE",
            },
        )
        self.assertFalse(merged["valid_quote"])
        self.assertEqual(merged["quote_assignment_blocker"], "FUTURE_PROVIDER_NATIVE_TIMESTAMP")

    def test_stale_carriage_does_not_masquerade_behind_fresh_evidence(self):
        # A candidate row that carried an old rotation cached provider timestamp
        # must not win over the genuinely fresh quote fetched at submission.
        stale_candidate = _crypto_row(provider_quote_timestamp=_iso(-45))
        merged = self._merge(
            stale_candidate,
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
            },
        )
        self.assertTrue(merged["valid_quote"])
        self.assertEqual(merged["submission_reason"], "final_candidate_fresh_provider_quote_promoted")
        self.assertEqual(merged["provider_quote_timestamp"], merged["market_observation_timestamp"])
        age = merged["quote_age_at_submission"]
        self.assertIsNotNone(age)
        self.assertGreaterEqual(age, 0.0)
        self.assertLess(age, 5.0)

    def test_non_final_candidates_do_not_trigger_a_second_provider_lookup(self):
        calls: list[int] = []
        engine = _engine({
            "symbol": "BTC/USD",
            "asset_type": "crypto",
            "price": 101.0,
            "provider_used": "ALPACA",
            "provider_quote_timestamp": _iso(),
            "market_source_type": "QUOTE",
        }, weight=calls)
        self.addCleanup(engine._tmpdir.cleanup)
        row = engine._assign_trusted_quote_to_candidate(_crypto_row())
        self.assertEqual(len(calls), 1)
        # Revalidation of ya-consumed evidence does not perform a second lookup.
        row2 = engine._assign_trusted_quote_to_candidate(dict(row))
        self.assertEqual(len(calls), 1)
        self.assertEqual(row2["quote_assignment_state"], "ASSIGNED_AND_CONSUMED")

    def test_provider_calls_added_is_zero_at_submission_merge(self):
        merged = self._merge(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
            },
        )
        self.assertEqual(merged["provider_calls_added"], 0)

    def test_no_live_trading_change_advisory_fail_closed_state(self):
        calls: list[int] = []
        engine = _engine({
            "symbol": "BTC/USD",
            "asset_type": "crypto",
            "price": 101.0,
            "provider_used": "ALPACA",
            "provider_quote_timestamp": _iso(),
            "market_source_type": "QUOTE",
        }, weight=calls)
        self.addCleanup(engine._tmpdir.cleanup)
        self.assertFalse(engine._enabled)
        merged = engine._merge_latest_quote_for_submission(
            _crypto_row(),
            {
                "symbol": "BTC/USD",
                "asset_type": "crypto",
                "price": 101.0,
                "provider_used": "ALPACA",
                "provider_quote_timestamp": _iso(),
                "market_source_type": "QUOTE",
            },
            101.0,
        )
        self.assertTrue(merged["valid_quote"])
        self.assertNotIn("live_trading", merged)
        self.assertFalse(merged.get("live_trading_changed", False))


if __name__ == "__main__":
    unittest.main()