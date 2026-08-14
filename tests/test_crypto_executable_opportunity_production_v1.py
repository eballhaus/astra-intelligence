"""Bounded CRYPTO executable-opportunity evidence and refresh regressions."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from engine.astra_crypto_executable_pair_quality_v1 import (
    apply_crypto_executable_quality_tiebreak_v1,
    quality_for_crypto_pair_v1,
    record_crypto_quote_observation_v1,
    select_crypto_hybrid_rotation_batch_v1,
)
from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def _observation(symbol: str, age: float, *, bid_ask: bool = True) -> dict:
    return {
        "symbol": symbol,
        "quote_timestamp": _iso(-int(age)),
        "quote_observed_at": _iso(),
        "quote_age_seconds": age,
        "provider_bid": 100.0 if bid_ask else None,
        "provider_ask": 100.1 if bid_ask else None,
        "spread_pct": 0.1 if bid_ask else None,
    }


def _state(symbol: str, ages: list[float]) -> dict:
    state: dict = {}
    for age in ages:
        state = record_crypto_quote_observation_v1(state, _observation(symbol, age))
    return state


class CryptoExecutablePairQualityTests(unittest.TestCase):
    def test_repeatedly_fresh_pair_becomes_positive_after_bounded_sample(self):
        quality = quality_for_crypto_pair_v1(_state("ADA/USD", [3, 5, 7, 9]), "ADA/USD")
        self.assertEqual(quality["quality"], "RELIABLE_EXECUTABLE")
        self.assertEqual(quality["freshness_pass_rate"], 1.0)
        self.assertEqual(quality["quality_preference"], 1)

    def test_repeatedly_stale_pair_is_lower_quality_only_after_sufficient_sample(self):
        quality = quality_for_crypto_pair_v1(_state("POL/USD", [45, 51, 80, 120]), "POL/USD")
        self.assertEqual(quality["quality"], "CHRONICALLY_STALE")
        self.assertEqual(quality["quality_preference"], -1)

    def test_insufficient_and_single_observations_remain_neutral(self):
        for ages in ([45], [4, 5, 6]):
            with self.subTest(ages=ages):
                quality = quality_for_crypto_pair_v1(_state("BTC/USD", ages), "BTC/USD")
                self.assertEqual(quality["quality"], "UNKNOWN_NEUTRAL")
                self.assertEqual(quality["quality_preference"], 0)

    def test_recent_observations_are_bounded_and_preserve_bid_ask_evidence(self):
        quality = quality_for_crypto_pair_v1(_state("BCH/USD", [4] * 20), "BCH/USD")
        self.assertEqual(quality["native_quote_observation_count"], 12)
        self.assertEqual(quality["bid_ask_available_count"], 12)

    def test_reliable_pair_wins_only_comparable_score_tiebreak(self):
        state = _state("ADA/USD", [4, 5, 6, 7])
        for age in [50, 60, 70, 80]:
            state = record_crypto_quote_observation_v1(state, _observation("POL/USD", age))
        ordered = apply_crypto_executable_quality_tiebreak_v1([
            {"symbol": "POL/USD", "ranking_score": 90.0},
            {"symbol": "ADA/USD", "ranking_score": 89.5},
        ], state)
        self.assertEqual([row["symbol"] for row in ordered], ["ADA/USD", "POL/USD"])
        not_comparable = apply_crypto_executable_quality_tiebreak_v1([
            {"symbol": "POL/USD", "ranking_score": 95.0},
            {"symbol": "ADA/USD", "ranking_score": 89.5},
        ], state)
        self.assertEqual(not_comparable[0]["symbol"], "POL/USD")

    def test_hybrid_rotation_prioritizes_reliable_evidence_and_keeps_two_fair_slots(self):
        universe = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "POL/USD"]
        state = _state("BTC/USD", [3, 4, 5, 6])
        for age in [45, 50, 60, 70]:
            state = record_crypto_quote_observation_v1(state, _observation("POL/USD", age))

        rotation = select_crypto_hybrid_rotation_batch_v1(universe, 0, state, batch_size=3)

        self.assertEqual(rotation["crypto_rotation_mode"], "HYBRID")
        self.assertEqual(rotation["priority_pair"], "BTC/USD")
        self.assertEqual(len(rotation["batch_pairs"]), 3)
        self.assertEqual(len(set(rotation["batch_pairs"])), 3)
        self.assertEqual(len(rotation["exploration_pairs"]), 2)
        self.assertNotIn("BTC/USD", rotation["exploration_pairs"])
        self.assertEqual(rotation["exploration_pairs"], ["ADA/USD", "ETH/USD"])

    def test_hybrid_rotation_uses_symbol_as_a_deterministic_quality_tie_break(self):
        universe = ["ETH/USD", "BTC/USD", "SOL/USD"]
        state = _state("ETH/USD", [3, 4, 5, 6])
        for age in [3, 4, 5, 6]:
            state = record_crypto_quote_observation_v1(state, _observation("BTC/USD", age))

        rotation = select_crypto_hybrid_rotation_batch_v1(universe, 0, state, batch_size=3)

        self.assertEqual(rotation["priority_pair"], "BTC/USD")

    def test_hybrid_rotation_falls_back_to_existing_fair_rotation_without_usable_quality(self):
        universe = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "POL/USD"]

        rotation = select_crypto_hybrid_rotation_batch_v1(universe, 1, {}, batch_size=3)

        self.assertEqual(rotation["crypto_rotation_mode"], "FAIR_FALLBACK")
        self.assertEqual(rotation["batch_pairs"], ["BTC/USD", "ETH/USD", "POL/USD"])
        self.assertEqual(rotation["exploration_pairs"], rotation["batch_pairs"])

    def test_insufficient_stale_or_malformed_quality_cannot_claim_priority(self):
        universe = ["BTC/USD", "ETH/USD", "SOL/USD"]
        insufficient = _state("BTC/USD", [3, 4, 5])
        stale = _state("BTC/USD", [3, 4, 5, 6])
        stale["pairs"]["BTC/USD"]["observations"][-1]["observed_at"] = _iso(-3601)
        cases = (
            ("insufficient", insufficient),
            ("stale", stale),
            ("malformed", {"pairs": {"BTC/USD": "not-a-quality-record"}}),
        )

        for name, state in cases:
            with self.subTest(name=name):
                rotation = select_crypto_hybrid_rotation_batch_v1(universe, 0, state, batch_size=3)
                self.assertEqual(rotation["crypto_rotation_mode"], "FAIR_FALLBACK")
                self.assertEqual(rotation["priority_pair"], "")
                self.assertEqual(rotation["batch_pairs"], ["BTC/USD", "ETH/USD", "SOL/USD"])

    def test_hybrid_rotation_exploration_eventually_visits_the_full_universe(self):
        universe = [f"COIN{index:02d}/USD" for index in range(30)]
        state = _state("COIN00/USD", [3, 4, 5, 6])
        cursor, observed = 0, set()

        for _ in range(30):
            rotation = select_crypto_hybrid_rotation_batch_v1(universe, cursor, state, batch_size=3)
            observed.update(rotation["batch_pairs"])
            cursor = rotation["next_cursor"]

        self.assertEqual(observed, set(universe))


class CryptoFinalRefreshTests(unittest.TestCase):
    def _engine(self, reply: dict, calls: list[int]) -> PaperAutopilotEngine:
        directory = tempfile.TemporaryDirectory(prefix="astra_crypto_final_refresh_")
        self.addCleanup(directory.cleanup)
        return PaperAutopilotEngine(
            db_path=os.path.join(directory.name, "paper.db"),
            state_path=os.path.join(directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: calls.append(1) or dict(reply),
        )

    def _stale_candidate(self) -> dict:
        return {
            "symbol": "BTC/USD", "asset_type": "crypto", "price": 100.0,
            "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
            "generated_at": _iso(), "candidate_generated_at": _iso(),
        }

    def test_stale_candidate_receives_exactly_one_fresh_native_refresh(self):
        calls: list[int] = []
        engine = self._engine({
            "symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0,
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        }, calls)
        assigned = engine._assign_trusted_quote_to_candidate(self._stale_candidate())
        repeated = engine._assign_trusted_quote_to_candidate(assigned)
        self.assertEqual(len(calls), 1)
        self.assertTrue(repeated["trusted_quote_for_buys"])
        self.assertEqual(repeated["crypto_final_quote_refresh_result"], "FRESH")
        self.assertEqual(repeated["crypto_final_quote_refresh_attempt_count"], 1)

    def test_stale_or_missing_refresh_remains_fail_closed_without_a_loop(self):
        for reply, expected in (
            ({"symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0, "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE"}, "STALE_PROVIDER_NATIVE_TIMESTAMP"),
            ({"symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0, "generated_at": _iso(), "market_source_type": "QUOTE"}, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE"),
            ({"symbol": "BTC/USD", "asset_type": "crypto", "price": 101.0, "data_unavailable_reason": "budget_guard_block", "market_source_type": "QUOTE"}, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE"),
        ):
            with self.subTest(expected=expected):
                calls: list[int] = []
                engine = self._engine(reply, calls)
                assigned = engine._assign_trusted_quote_to_candidate(self._stale_candidate())
                repeated = engine._assign_trusted_quote_to_candidate(assigned)
                self.assertEqual(len(calls), 1)
                self.assertFalse(repeated["trusted_quote_for_buys"])
                self.assertEqual(repeated["quote_assignment_blocker"], expected)
                self.assertEqual(repeated["quote_assignment_state"], "CRYPTO_STALE_REFRESH_CONSUMED")

    def test_fresh_day_assignment_uses_existing_behavior_without_crypto_refresh_metadata(self):
        calls: list[int] = []
        engine = self._engine({
            "symbol": "AAPL", "asset_type": "stock", "price": 101.0,
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        }, calls)
        assigned = engine._assign_trusted_quote_to_candidate({"symbol": "AAPL", "asset_type": "stock", "price": 100.0})
        self.assertTrue(assigned["trusted_quote_for_buys"])
        self.assertEqual(len(calls), 1)
        self.assertNotIn("crypto_final_quote_refresh_attempted", assigned)


if __name__ == "__main__":
    unittest.main()
