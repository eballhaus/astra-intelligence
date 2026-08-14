"""CRYPTO final quote refresh is spent only after non-market gates pass."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from engine.paper_autopilot import PaperAutopilotEngine


def _iso(offset: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def _candidate(**extra) -> dict:
    row = {
        "symbol": "BCH/USD", "asset_type": "crypto", "asset_class": "crypto",
        "lane_id": "CRYPTO", "price": 100.0, "current_price": 100.0,
        "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
        "candidate_generated_at": _iso(), "generated_at": _iso(),
        "buy_eligibility": "qualified", "buy_quality_tier": "strong",
        "buy_quality_score": 75.0, "confidence": 80.0, "consensus_strength": 80.0,
        "entry_edge_score": 0.2, "persona_disagreement_index": 20.0,
        "uncertainty_score": 20.0, "uncertainty_tier": "normal",
        "paper_entry_horizon_style": "day_trade", "trade_horizon_style": "day_trade",
        "spread_pct": 0.2, "volume_24h": 1000.0, "data_quality_score": 90.0,
        "candidate_id": "candidate-bch", "recommendation_id": "recommendation-bch",
        "decision_id": "decision-bch", "selection_id": "selection-bch",
        **extra,
    }
    return row


def _valid_contract(**extra) -> dict:
    return {
        "contract_status": "VALID", "contract_state": "CONTRACT_COMPLETE",
        "order_ready_allowed": True, "candidate_risk_envelope_v1": {}, **extra,
    }


class CryptoFinalRefreshPlacementTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="astra_crypto_refresh_placement_")
        self.addCleanup(self.directory.cleanup)
        self.calls: list[int] = []
        self.reply = {
            "symbol": "BCH/USD", "asset_type": "crypto", "price": 101.0,
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
            "spread_pct": 0.2, "volume_24h": 1000.0, "data_quality_score": 90.0,
        }
        self.engine = PaperAutopilotEngine(
            db_path=os.path.join(self.directory.name, "paper.db"),
            state_path=os.path.join(self.directory.name, "state.json"),
            enabled=False,
            get_latest_row_fn=lambda _symbol, _asset: self.calls.append(1) or dict(self.reply),
        )

    def _deferred(self, row: dict | None = None) -> dict:
        return self.engine._assign_trusted_quote_to_candidate(
            row or _candidate(), refresh_crypto_stale=False,
        )

    def _trace(
        self,
        row: dict,
        *,
        integrity_ok: bool = True,
        contract: dict | None = None,
        open_syms: set[str] | None = None,
        crypto_capacity: int = 2,
        crypto_active: bool = True,
    ):
        activation = {"execution_enabled": True, "paper_only_preserved": True}
        crypto_activation = {"paper_active_bounded": crypto_active, "capability": {}}
        def integrity(_row, **_kwargs):
            return integrity_ok, "crypto_execution_integrity_passed" if integrity_ok else "duplicate_pending", {}
        with (
            patch("engine.paper_autopilot.canonical_lane_activation_contract", return_value=activation),
            patch("engine.paper_autopilot.enrich_candidate_for_pretrade_contract", side_effect=lambda value, **_kwargs: dict(value)),
            patch("engine.paper_autopilot.build_pretrade_decision_contract", return_value=contract or _valid_contract()),
            patch.object(self.engine, "_crypto_paper_activation_status", return_value=crypto_activation),
            patch.object(self.engine, "_crypto_execution_integrity_gate", side_effect=integrity),
        ):
            return self.engine._candidate_trace_row(
                row, open_syms=open_syms or set(), stock_capacity=2,
                crypto_capacity=crypto_capacity, total_capacity=2,
                broker_reconciliation_active=True,
            )

    def test_commitment_failure_does_not_spend_final_refresh(self):
        trace, allowed, reason, _ = self._trace(
            _candidate(
                consensus_strength=0.0,
                entry_edge_score=-1.0,
                persona_disagreement_index=100.0,
                uncertainty_score=60.0,
            )
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "entry_commitment_below_threshold")
        self.assertEqual(self.calls, [])
        self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_missing_pretrade_contract_does_not_spend_final_refresh(self):
        trace, allowed, reason, _ = self._trace(
            _candidate(), contract=_valid_contract(order_ready_allowed=False, fail_closed_reason="PRETRADE_DECISION_CONTRACT_INVALID"),
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "PRETRADE_DECISION_CONTRACT_INVALID")
        self.assertEqual(self.calls, [])
        self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_integrity_failure_does_not_spend_final_refresh(self):
        trace, allowed, reason, _ = self._trace(_candidate(), integrity_ok=False)
        self.assertFalse(allowed)
        self.assertEqual(reason, "duplicate_pending")
        self.assertEqual(self.calls, [])
        self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_other_non_market_gate_failures_do_not_spend_final_refresh(self):
        cases = (
            ("risk", _candidate(portfolio_diversification_block_reason="correlation_overload"), {}),
            ("capacity", _candidate(), {"crypto_capacity": 0}),
            ("duplicate", _candidate(), {"open_syms": {"BCH/USD"}}),
            ("session", _candidate(), {"crypto_active": False}),
        )
        for name, row, options in cases:
            with self.subTest(name=name):
                self.calls.clear()
                trace, allowed, _reason, _ = self._trace(row, **options)
                self.assertFalse(allowed)
                self.assertEqual(self.calls, [])
                self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_otherwise_ready_stale_candidate_refreshes_once_and_becomes_ready(self):
        trace, allowed, reason, _ = self._trace(_candidate())
        self.assertTrue(allowed, reason)
        self.assertEqual(self.calls, [1])
        self.assertTrue(trace["crypto_final_quote_refresh_attempted"])
        self.assertEqual(trace["crypto_final_quote_refresh_attempt_count"], 1)
        self.assertEqual(trace["crypto_final_quote_refresh_result"], "FRESH")
        self.assertLessEqual(trace["crypto_final_refresh_quote_age_seconds"], 20.0)

    def test_stale_or_missing_final_native_quote_remains_blocked(self):
        for reply, quote_blocker in (
            ({**self.reply, "provider_quote_timestamp": _iso(-21)}, "STALE_PROVIDER_NATIVE_TIMESTAMP"),
            ({key: value for key, value in self.reply.items() if key != "provider_quote_timestamp"}, "crypto_quote_freshness_missing"),
        ):
            with self.subTest(quote_blocker=quote_blocker):
                self.reply = reply
                self.calls.clear()
                trace, allowed, reason, _ = self._trace(_candidate())
                self.assertFalse(allowed)
                if quote_blocker == "STALE_PROVIDER_NATIVE_TIMESTAMP":
                    self.assertEqual(trace["quote_assignment_blocker"], quote_blocker)
                else:
                    self.assertEqual(reason, quote_blocker)
                self.assertEqual(self.calls, [1])
                self.assertTrue(trace["crypto_final_quote_refresh_attempted"])

    def test_generated_at_cannot_satisfy_final_freshness(self):
        self.reply = {**self.reply, "generated_at": _iso()}
        self.reply.pop("provider_quote_timestamp")
        _trace, allowed, reason, _ = self._trace(_candidate())
        self.assertFalse(allowed)
        self.assertEqual(reason, "crypto_quote_freshness_missing")

    def test_second_finalization_does_not_refresh_again(self):
        deferred = self._deferred()
        refreshed = self.engine._finalize_crypto_quote_refresh_v1(deferred, pre_market_gates_passed=True)
        repeated = self.engine._finalize_crypto_quote_refresh_v1(refreshed, pre_market_gates_passed=True)
        self.assertEqual(self.calls, [1])
        self.assertTrue(repeated["trusted_quote_for_buys"])
        self.assertEqual(repeated["crypto_final_quote_refresh_attempt_count"], 1)

    def test_non_crypto_assignment_retains_existing_single_lookup_behavior(self):
        row = {
            "symbol": "AAPL", "asset_type": "stock", "price": 100.0,
            "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
        }
        self.reply = {"symbol": "AAPL", "asset_type": "stock", "price": 101.0, "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE"}
        assigned = self.engine._assign_trusted_quote_to_candidate(row)
        self.assertTrue(assigned["trusted_quote_for_buys"])
        self.assertEqual(self.calls, [1])


if __name__ == "__main__":
    unittest.main()
