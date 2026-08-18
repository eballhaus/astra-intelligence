"""CRYPTO final quote refresh is spent only after non-market gates pass."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
        self.executable_calls: list[int] = []
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
            get_executable_quote_fn=lambda _symbol, _asset: self.executable_calls.append(1) or dict(self.reply),
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
        self.assertEqual(self.executable_calls, [])
        self.assertFalse(trace["crypto_final_quote_refresh_attempted"])
        commitment = trace["entry_commitment_trace_v1"]
        self.assertEqual(commitment["commitment_score"], trace["commitment_score"])
        self.assertEqual(commitment["applied_minimum"], 58.0)
        self.assertEqual(commitment["applied_floor_type"], "base_commitment_floor")
        self.assertEqual(commitment["buy_or_trade_quality_score"], 75.0)
        self.assertEqual(commitment["confidence_or_predicted_win_probability"], 80.0)
        self.assertEqual(commitment["consensus_strength"], 0.0)
        self.assertEqual(commitment["input_sources"]["consensus_strength"], "consensus_strength")
        self.assertEqual(
            commitment["defaulted_inputs"],
            ["discipline_action", "discipline_tier", "follow_through_state"],
        )

    def test_crypto_missing_contract_trace_retains_risk_and_forecast_gaps(self):
        contract = _valid_contract(
            contract_status="INVALID",
            contract_state="CONTRACT_INCOMPLETE",
            order_ready_allowed=False,
            fail_closed_reason="PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
            missing_required_fields=[
                "candidate_risk_envelope_v1",
                "expected_return_range",
                "expected_return_per_day_range",
            ],
            candidate_risk_envelope_v1={
                "risk_envelope_state": "RISK_ENVELOPE_INCOMPLETE",
                "missing_inputs": ["expected_upside_range", "expected_downside_range"],
            },
        )
        trace, allowed, reason, _ = self._trace(
            _candidate(
                symbol="PEPE/USD",
                crypto_pretrade_forecast_v1={
                    "forecast_state": "FORECAST_INCOMPLETE",
                    "missing_inputs": ["completed_bar_continuation"],
                },
            ),
            contract=contract,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS")
        observed = trace["pretrade_contract_missing_fields_trace_v1"]
        self.assertEqual(observed["missing_required_fields"], contract["missing_required_fields"])
        self.assertEqual(observed["contract_lane"], "CRYPTO")
        self.assertEqual(observed["risk_envelope_state"], "RISK_ENVELOPE_INCOMPLETE")
        self.assertEqual(observed["risk_envelope_missing_fields"], ["expected_upside_range", "expected_downside_range"])
        self.assertEqual(observed["crypto_pretrade_forecast_state"], "FORECAST_INCOMPLETE")
        self.assertEqual(observed["crypto_pretrade_forecast_missing_fields"], ["completed_bar_continuation"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [])

    def test_scalp_missing_contract_trace_retains_lane_and_risk_gaps(self):
        contract = _valid_contract(
            contract_status="INVALID",
            contract_state="CONTRACT_INCOMPLETE",
            order_ready_allowed=False,
            fail_closed_reason="PRETRADE_DECISION_CONTRACT_MISSING_FIELDS",
            missing_required_fields=["candidate_risk_envelope_v1", "expected_return_range"],
            candidate_risk_envelope_v1={
                "risk_envelope_state": "RISK_ENVELOPE_INCOMPLETE",
                "missing_inputs": ["expected_downside_range"],
            },
        )
        trace, allowed, reason, _ = self._trace(
            _candidate(
                symbol="GEHC",
                asset_type="stock",
                asset_class="equity",
                lane_id="SCALP",
                paper_entry_horizon_style="scalp",
                trade_horizon_style="scalp",
                provider_quote_timestamp=_iso(),
                quote_assignment_state="ASSIGNED_AND_CONSUMED",
                valid_quote=True,
                trusted_quote_for_buys=True,
            ),
            contract=contract,
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "PRETRADE_DECISION_CONTRACT_MISSING_FIELDS")
        observed = trace["pretrade_contract_missing_fields_trace_v1"]
        self.assertEqual(observed["contract_lane"], "SCALP")
        self.assertEqual(observed["intended_horizon"], "scalp")
        self.assertEqual(observed["risk_envelope_missing_fields"], ["expected_downside_range"])
        self.assertEqual(observed["crypto_pretrade_forecast_state"], "NOT_APPLICABLE")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [])

    def test_missing_pretrade_contract_does_not_spend_final_refresh(self):
        trace, allowed, reason, _ = self._trace(
            _candidate(), contract=_valid_contract(order_ready_allowed=False, fail_closed_reason="PRETRADE_DECISION_CONTRACT_INVALID"),
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "PRETRADE_DECISION_CONTRACT_INVALID")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [])
        self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_integrity_failure_does_not_spend_final_refresh(self):
        trace, allowed, reason, _ = self._trace(_candidate(), integrity_ok=False)
        self.assertFalse(allowed)
        self.assertEqual(reason, "duplicate_pending")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [])
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
                self.executable_calls.clear()
                trace, allowed, _reason, _ = self._trace(row, **options)
                self.assertFalse(allowed)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.executable_calls, [])
                self.assertFalse(trace["crypto_final_quote_refresh_attempted"])

    def test_otherwise_ready_stale_candidate_refreshes_once_and_becomes_ready(self):
        trace, allowed, reason, _ = self._trace(_candidate())
        self.assertTrue(allowed, reason)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])
        self.assertTrue(trace["crypto_final_quote_refresh_attempted"])
        self.assertEqual(trace["crypto_final_quote_refresh_attempt_count"], 1)
        self.assertEqual(trace["crypto_final_quote_refresh_result"], "FRESH")
        self.assertLessEqual(trace["crypto_final_refresh_quote_age_seconds"], 20.0)

    def test_stale_or_missing_final_native_quote_remains_blocked(self):
        for reply, quote_blocker in (
            ({**self.reply, "provider_quote_timestamp": _iso(-21)}, "STALE_PROVIDER_NATIVE_TIMESTAMP"),
            ({key: value for key, value in self.reply.items() if key != "provider_quote_timestamp"}, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE"),
        ):
            with self.subTest(quote_blocker=quote_blocker):
                self.reply = reply
                self.calls.clear()
                self.executable_calls.clear()
                self.engine._hot_candidate_quote_refresh_counts_v1 = {}
                refreshed = self.engine._finalize_crypto_quote_refresh_v1(
                    self._deferred(), pre_market_gates_passed=True,
                )
                self.assertFalse(refreshed["trusted_quote_for_buys"])
                self.assertEqual(refreshed["quote_assignment_blocker"], quote_blocker)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.executable_calls, [1])
                self.assertTrue(refreshed["crypto_final_quote_refresh_attempted"])

    def test_stale_final_refresh_is_terminal_before_submission_handoff(self):
        self.reply = {**self.reply, "provider_quote_timestamp": _iso(-21)}

        trace, allowed, reason, gate_meta = self._trace(_candidate())

        self.assertFalse(allowed)
        self.assertEqual(reason, "STALE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertFalse(trace["order_ready"])
        self.assertTrue(trace["crypto_final_quote_refresh_attempted"])
        self.assertEqual(trace["crypto_final_quote_refresh_result"], "STALE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertFalse(gate_meta["_qualified_candidate_for_submission_v1"]["trusted_quote_for_buys"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

    def test_fresh_final_refresh_preserves_qualified_row_for_submission(self):
        trace, allowed, reason, gate_meta = self._trace(_candidate())

        self.assertTrue(allowed, reason)
        qualified = gate_meta["_qualified_candidate_for_submission_v1"]
        self.assertTrue(qualified["final_executable_quote_refresh_authoritative"])
        self.assertEqual(qualified["provider_quote_timestamp"], self.reply["provider_quote_timestamp"])
        self.assertEqual(qualified["price"], self.reply["price"])
        self.assertTrue(trace["crypto_final_quote_refresh_attempted"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

        submitted_rows: list[dict] = []
        self.engine._submit_alpaca_paper_entry_order = lambda row, _price, **_kwargs: (
            submitted_rows.append(dict(row))
            or {"ok": False, "enabled": True, "error": "test_block"}
        )
        opened = self.engine._open_position_from_row(qualified)
        self.assertFalse(opened["ok"])
        self.assertEqual(len(submitted_rows), 1)
        self.assertEqual(submitted_rows[0]["provider_quote_timestamp"], self.reply["provider_quote_timestamp"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

    def test_stale_refresh_persists_the_validated_provider_timestamp_and_age(self):
        refreshed_at = _iso(-21)
        self.reply = {**self.reply, "provider_quote_timestamp": refreshed_at}

        refreshed = self.engine._finalize_crypto_quote_refresh_v1(
            self._deferred(), pre_market_gates_passed=True,
        )

        self.assertFalse(refreshed["trusted_quote_for_buys"])
        self.assertEqual(refreshed["crypto_final_quote_refresh_result"], "STALE_PROVIDER_NATIVE_TIMESTAMP")
        self.assertEqual(refreshed["provider_quote_timestamp"], refreshed_at)
        self.assertGreater(refreshed["quote_age_seconds"], 20.0)
        self.assertEqual(
            refreshed["quote_age_seconds"],
            refreshed["crypto_final_refresh_validated_age_seconds"],
        )
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

    def test_generated_at_cannot_satisfy_final_freshness(self):
        self.reply = {**self.reply, "generated_at": _iso()}
        self.reply.pop("provider_quote_timestamp")
        _trace, allowed, reason, _ = self._trace(_candidate())
        self.assertFalse(allowed)
        self.assertEqual(reason, "PROVIDER_NATIVE_MARKET_OBSERVATION_UNAVAILABLE")

    def test_second_finalization_does_not_refresh_again(self):
        deferred = self._deferred()
        refreshed = self.engine._finalize_crypto_quote_refresh_v1(deferred, pre_market_gates_passed=True)
        repeated = self.engine._finalize_crypto_quote_refresh_v1(refreshed, pre_market_gates_passed=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])
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
        self.assertEqual(self.executable_calls, [])

    def test_scalp_hot_refresh_requires_regular_session_and_uses_executable_lookup(self):
        stale = {
            "symbol": "AAPL", "asset_type": "stock", "lane_id": "SCALP", "price": 100.0,
            "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
        }
        deferred = self.engine._assign_trusted_quote_to_candidate(stale, refresh_scalp_stale=False)
        self.assertEqual(deferred["quote_assignment_state"], "SCALP_STALE_REFRESH_DEFERRED")
        self.assertEqual(self.calls, [])

        self.reply = {
            "symbol": "AAPL", "asset_type": "stock", "price": 101.0,
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        }
        refreshed = self.engine._finalize_scalp_quote_refresh_v1(
            deferred, pre_market_gates_passed=True, regular_session_open=True,
        )
        self.assertTrue(refreshed["trusted_quote_for_buys"])
        self.assertEqual(refreshed["hot_candidate_quote_refresh_lane"], "SCALP")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

    def test_scalp_after_hours_does_not_consume_hot_refresh(self):
        deferred = self.engine._assign_trusted_quote_to_candidate({
            "symbol": "AAPL", "asset_type": "stock", "lane_id": "SCALP", "price": 100.0,
            "provider_quote_timestamp": _iso(-45), "market_source_type": "QUOTE",
        }, refresh_scalp_stale=False)
        blocked = self.engine._finalize_scalp_quote_refresh_v1(
            deferred, pre_market_gates_passed=True, regular_session_open=False,
        )
        self.assertEqual(blocked["quote_assignment_state"], "SCALP_STALE_REFRESH_DEFERRED")
        self.assertEqual(blocked["hot_candidate_quote_refresh_skipped_reason"], "REGULAR_SESSION_REQUIRED")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [])

    def test_regular_session_scalp_trace_spends_one_hot_refresh_after_pretrade(self):
        self.engine.market_session_timing_suite = SimpleNamespace(
            confirmation_for_candidate=lambda *_args, **_kwargs: {
                "paper_order_submission_allowed": True,
                "market_is_open": True,
                "market_is_tradable": True,
            },
        )
        self.reply = {
            "symbol": "AAPL", "asset_type": "stock", "price": 101.0,
            "provider_quote_timestamp": _iso(), "market_source_type": "QUOTE",
        }
        row = _candidate(
            symbol="AAPL", asset_type="stock", asset_class="equity", lane_id="SCALP",
            paper_entry_horizon_style="scalp", trade_horizon_style="scalp",
        )
        with (
            patch("engine.paper_autopilot.canonical_lane_activation_contract", return_value={"execution_enabled": True}),
            patch("engine.paper_autopilot.enrich_candidate_for_pretrade_contract", side_effect=lambda value, **_kwargs: dict(value)),
            patch("engine.paper_autopilot.build_pretrade_decision_contract", return_value=_valid_contract()),
            patch.object(self.engine, "_entry_commitment_gate_v1", return_value=(True, "eligible", {})),
        ):
            trace, allowed, reason, _ = self.engine._candidate_trace_row(
                row, open_syms=set(), stock_capacity=2, crypto_capacity=2, total_capacity=2,
            )
        self.assertTrue(allowed, reason)
        self.assertEqual(trace["hot_candidate_quote_refresh_lane"], "SCALP")
        self.assertTrue(trace["hot_candidate_quote_refresh_attempted"])
        self.assertTrue(trace["hot_candidate_quote_refresh_cache_bypass_requested"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.executable_calls, [1])

    def test_hot_refresh_per_lane_budget_is_one_by_default(self):
        first = self.engine._finalize_crypto_quote_refresh_v1(
            self._deferred(), pre_market_gates_passed=True,
        )
        second = self.engine._finalize_crypto_quote_refresh_v1(
            self._deferred(_candidate(symbol="ETH/USD", candidate_id="candidate-eth")),
            pre_market_gates_passed=True,
        )
        self.assertTrue(first["trusted_quote_for_buys"])
        self.assertEqual(second["quote_assignment_state"], "CRYPTO_STALE_REFRESH_DEFERRED_BY_BUDGET")
        self.assertEqual(self.executable_calls, [1])


if __name__ == "__main__":
    unittest.main()
