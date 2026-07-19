from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from unittest.mock import Mock

from engine.alpaca_paper_broker import AlpacaPaperBroker
from engine.candidate_execution_integrity_v1 import candidate_execution_integrity
from engine.crypto_operational_integrity_readiness_v1 import build_crypto_operational_integrity_readiness_v1
from engine.shadow_profit_loss_protection_validation_v1 import build_shadow_profit_loss_protection_validation_v1
from engine.trade_lifecycle_excursion_v1 import TradeLifecycleExcursionV1


NOW = datetime.now(timezone.utc)


def _candidate(**overrides):
    row = {
        "candidate_id": "crypto-candidate-1", "symbol": "BTC/USD", "asset_class": "crypto",
        "quote_age_seconds": 10, "spread_pct": 0.2, "volume_24h": 1000, "data_quality_score": 90,
        "confidence": 85, "paper_entry_horizon_style": "day_trade", "notional": 50,
    }
    row.update(overrides)
    return row


def _lane(**overrides):
    row = {
        "activation_requested": False, "paper_crypto_enabled": False, "paper_mode_verified": True,
        "capital_configured": True, "capital_limit": 1000, "kill_switch_enabled": False,
        "day_trade_capacity_available": 1, "short_swing_capacity_available": 1,
        "lane_state": "LANE_PAPER_ACTIVE_BOUNDED", "broker_reconciliation_ok": True,
    }
    row.update(overrides)
    return row


def _capability(**overrides):
    row = {
        "paper_mode_verified": True, "live_endpoint_detected": False, "crypto_trading_supported": True,
        "supported_pairs": ["BTC/USD"], "tradable_pairs": ["BTC/USD"],
        "supported_order_types": ["market"], "supported_time_in_force": ["gtc"],
        "fractional_quantity_supported": True,
    }
    row.update(overrides)
    return row


def _canonical_capability(**overrides):
    row = _capability(
        generated_at=NOW.isoformat(), market_data_entitlement_confirmed=True, market_data_status="PASS",
        source="alpaca_crypto_capability_v2_cache", cache_only=True,
        supported_pairs=["LINK/USD", "LTC/USD"], tradable_pairs=["LINK/USD", "LTC/USD"],
        asset_rules={
            "LINK/USD": {"tradable": True, "status": "active", "fractionable": True, "min_order_size": "0.1", "min_trade_increment": "0.000000001", "price_increment": "0.000000001"},
            "LTC/USD": {"tradable": True, "status": "active", "fractionable": True, "min_order_size": "0.02", "min_trade_increment": "0.000000001", "price_increment": "0.000000001"},
        },
    )
    row.update(overrides)
    return row


def _lifecycle(lifecycle_id: str, price: float, *, closed: bool = False, timestamp: datetime | None = None,
               lane_id: str = "DAY", symbol: str = "BTC/USD", asset_class: str = "crypto", verified: bool = True):
    return {
        "lifecycle_id": lifecycle_id, "symbol": symbol, "asset_class": asset_class, "lane_id": lane_id,
        "entry_price": 100.0, "current_price": price, "entry_price_verified": verified,
        "loss_calibration_eligible": verified, "diagnostic_only": not verified, "closed": closed,
        "entry_timestamp": (NOW - timedelta(hours=1)).isoformat(),
        "current_timestamp": (timestamp or NOW).isoformat(), "paper_entry_horizon_style": "day_trade",
        "strategy_cohort": "test", "regime": "neutral",
    }


class CryptoOperationalIntegrityShadowProtectionTests(unittest.TestCase):
    def test_canonical_capability_and_pair_rules_win_over_empty_activation_fields(self):
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability=_canonical_capability(),
            candidates=[_candidate(symbol="LINK/USD"), _candidate(symbol="LTC/USD")],
        )
        self.assertNotEqual(payload["status"], "BROKER_NOT_READY")
        self.assertTrue(payload["broker_capability"]["crypto_trading_supported"])
        self.assertEqual(payload["broker_capability"]["supported_pairs_count"], 2)
        self.assertEqual(payload["broker_capability"]["tradable_pairs_count"], 2)
        evaluated = {row["symbol"]: row for row in payload["pair_eligibility"]["evaluated_candidates"]}
        self.assertEqual(evaluated["LINK/USD"]["pair_eligibility"], "TRADABLE")
        self.assertEqual(evaluated["LTC/USD"]["pair_eligibility"], "TRADABLE")
        self.assertTrue(evaluated["LINK/USD"]["asset_rule"]["fractionable"])
        self.assertEqual(payload["pair_eligibility"]["canonical_pair_capability"]["LINK/USD"]["pair_eligibility"], "TRADABLE")

    def test_missing_capability_remains_broker_not_ready_without_fabricating_pairs(self):
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability={}, candidates=[_candidate(symbol="LINK/USD")],
        )
        self.assertEqual(payload["status"], "BROKER_NOT_READY")
        self.assertFalse(payload["paper_execution_currently_allowed"])
        self.assertEqual(payload["broker_capability"]["supported_pairs"], [])

    def test_public_capability_accessor_is_cache_only_and_sanitized(self):
        with tempfile.TemporaryDirectory() as root:
            broker = AlpacaPaperBroker()
            broker._crypto_capability_path = f"{root}/capability.json"
            with open(broker._crypto_capability_path, "w", encoding="utf-8") as handle:
                json.dump({**_canonical_capability(), "api_key": "not-exported", "asset_rules": {"LINK/USD": _canonical_capability()["asset_rules"]["LINK/USD"]}}, handle)
            broker._request = Mock(side_effect=AssertionError("cache accessor made broker request"))
            payload = broker.cached_crypto_capability()
            self.assertTrue(payload["cache_only"])
            self.assertEqual(payload["broker_actions_used"], 0)
            self.assertNotIn("api_key", payload)
            broker._request.assert_not_called()

    def test_bid_ask_spread_calculates_without_fabricating_missing_sides(self):
        passing = candidate_execution_integrity(
            _candidate(symbol="LINK/USD", bid=10.00, ask=10.10, spread_pct=None),
            supported_pairs={"LINK/USD"}, tradable_pairs={"LINK/USD"}, lane_state="LANE_PAPER_ACTIVE_BOUNDED",
            paper_mode_verified=True, capacity_available=True, broker_reconciliation_ok=True,
        )
        self.assertAlmostEqual(passing["mid"], 10.05)
        self.assertAlmostEqual(passing["spread_pct"], 0.9950248756, places=6)
        self.assertEqual(passing["gate_status"]["quote_spread"], "PASS")
        missing = candidate_execution_integrity(
            _candidate(symbol="LINK/USD", bid=10.0, ask=None, spread_pct=None),
            supported_pairs={"LINK/USD"}, tradable_pairs={"LINK/USD"}, lane_state="LANE_PAPER_ACTIVE_BOUNDED",
            paper_mode_verified=True, capacity_available=True, broker_reconciliation_ok=True,
        )
        self.assertIsNone(missing["spread_pct"])
        self.assertEqual(missing["gate_status"]["quote_spread"], "PENDING_SPREAD")

    def test_excessive_spread_remains_a_liquidity_blocker(self):
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(activation_requested=True), capability=_canonical_capability(), candidates=[_candidate(symbol="LINK/USD", bid=10, ask=10.5, spread_pct=None)],
        )
        candidate = payload["pair_eligibility"]["evaluated_candidates"][0]
        self.assertEqual(candidate["gate_status"]["quote_spread"], "REJECTED_EXCESSIVE_SPREAD")
        self.assertEqual(payload["status"], "LIQUIDITY_NOT_READY")

    def test_legacy_unverified_lineage_is_reported_but_not_an_active_blocker(self):
        legacy = [{
            "lifecycle_id": f"legacy-{index}", "asset_class": "crypto", "symbol": "LINK/USD",
            "entry_price_verified": False, "loss_calibration_eligible": False, "diagnostic_only": True,
        } for index in range(199)]
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability=_canonical_capability(), candidates=[_candidate(symbol="LINK/USD")], lifecycle_rows=legacy,
        )
        lineage = payload["lineage_readiness"]
        self.assertEqual(lineage["legacy_unverified_entries"], 199)
        self.assertEqual(lineage["active_unverified_entries"], 0)
        self.assertFalse(lineage["active_lineage_blocking"])
        self.assertNotEqual(payload["status"], "LINEAGE_NOT_READY")

    def test_active_unverified_lineage_blocks_but_verified_lineage_does_not(self):
        active_unverified = [{"position_id": "open-1", "symbol": "LINK/USD", "asset_class": "crypto", "entry_order_id": "entry-1", "entry_price_verified": False}]
        blocked = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(activation_requested=True), capability=_canonical_capability(), candidates=[_candidate(symbol="LINK/USD")], open_positions=active_unverified,
        )
        self.assertEqual(blocked["status"], "LINEAGE_NOT_READY")
        self.assertIn("CRYPTO_ENTRY_LINEAGE_UNVERIFIED", blocked["exact_blockers"])
        verified = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(activation_requested=True), capability=_canonical_capability(), candidates=[_candidate(symbol="LINK/USD")],
            open_positions=[{**active_unverified[0], "entry_price_verified": True}],
        )
        self.assertEqual(verified["lineage_readiness"]["active_verified_entries"], 1)
        self.assertEqual(verified["lineage_readiness"]["active_unverified_entries"], 0)

    def test_crypto_capital_absent_fails_closed_without_enabling_execution(self):
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(capital_configured=False, capital_limit=None), capability=_capability(), candidates=[_candidate()],
        )
        self.assertEqual(payload["status"], "NOT_CONFIGURED")
        self.assertEqual(payload["capital_readiness"]["blocker"], "CRYPTO_PAPER_CAPITAL_NOT_CONFIGURED")
        self.assertFalse(payload["paper_execution_currently_allowed"])
        self.assertFalse(payload["behavior_safe_to_apply"])

    def test_crypto_identity_data_liquidity_and_duplicate_gates_remain_explicit(self):
        unsupported = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability=_capability(), candidates=[_candidate(symbol="COST/USD")], known_equity_symbols={"COST"},
        )
        self.assertEqual(unsupported["pair_eligibility"]["evaluated_candidates"][0]["identity_status"], "REJECTED_EQUITY_SYMBOL_CONTAMINATION")
        stale = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability=_capability(), candidates=[_candidate(quote_age_seconds=999)],
        )
        self.assertEqual(stale["data_readiness"]["status"], "DATA_STALE")
        illiquid = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(paper_crypto_enabled=True), capability=_capability(), candidates=[_candidate(spread_pct=2.0, volume_24h=0)],
        )
        self.assertEqual(illiquid["liquidity_readiness"]["status"], "LIQUIDITY_NOT_READY")
        self.assertFalse(illiquid["paper_execution_currently_allowed"])
        duplicate = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(), capability=_capability(), candidates=[_candidate()],
            open_positions=[{"symbol": "BTC/USD", "asset_type": "crypto", "entry_price_verified": True}],
        )
        self.assertEqual(duplicate["duplicate_exposure"]["duplicate_candidate_count"], 1)

    def test_each_candidate_reports_one_ordered_first_causal_blocker(self):
        payload = build_crypto_operational_integrity_readiness_v1(
            lane=_lane(activation_requested=True), capability=_canonical_capability(),
            candidates=[_candidate(symbol="LINK/USD", quote_age_seconds=999, spread_pct=None, volume_24h=0, data_quality_score=0)],
        )
        candidate = payload["pair_eligibility"]["evaluated_candidates"][0]
        self.assertEqual(candidate["first_causal_blocker"]["gate"], "timestamp_freshness")
        self.assertEqual(payload["candidate_execution_blockers"], ["timestamp_freshness"])
        self.assertEqual(payload["candidate_first_causal_blockers"][0]["symbol"], "LINK/USD")

    def test_provider_timestamp_wins_over_a_fresh_receipt_age(self):
        result = candidate_execution_integrity(
            _candidate(
                symbol="LINK/USD", quote_age_seconds=1,
                provider_quote_timestamp=(NOW - timedelta(minutes=10)).isoformat(),
            ),
            supported_pairs={"LINK/USD"}, tradable_pairs={"LINK/USD"},
            lane_state="LANE_PAPER_ACTIVE_BOUNDED", paper_mode_verified=True,
            capacity_available=True, broker_reconciliation_ok=True,
        )
        self.assertEqual(result["gate_status"]["timestamp_freshness"], "REJECTED_STALE_QUOTE")
        self.assertEqual(result["first_causal_blocker"]["gate"], "timestamp_freshness")

    def test_lifecycle_lineage_keeps_verified_and_unverified_entries_separate(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        lifecycle = TradeLifecycleExcursionV1(state_path=f"{tmp.name}/lifecycle.jsonl")
        base = {
        "position_id": "verified-crypto", "symbol": "BTC/USD", "asset_type": "crypto", "lane_id": "CRYPTO",
        "strategy_cohort": "crypto_day", "paper_entry_horizon_style": "day_trade", "entry_price": 100,
        "entry_price_verified": True, "entry_price_evidence_class": "BROKER_CONFIRMED_ENTRY",
        "entry_timestamp": NOW.isoformat(), "row_json": "{}",
    }
        verified = lifecycle._build_record(base, {"price": 101, "timestamp": NOW.isoformat()})
        unverified = lifecycle._build_record({**base, "position_id": "unverified-crypto", "entry_price_verified": False}, {"price": 101, "timestamp": NOW.isoformat()})
        self.assertEqual(verified["asset_class"], "crypto")
        self.assertEqual(verified["lane_id"], "CRYPTO")
        self.assertTrue(verified["loss_calibration_eligible"])
        self.assertFalse(unverified["loss_calibration_eligible"])
        self.assertTrue(unverified["diagnostic_only"])

    def test_fixed_loss_and_profit_protection_replays_are_lane_isolated_and_shadow_only(self):
        path = [
        _lifecycle("day-1", 100, asset_class="stock", symbol="NVDA", timestamp=NOW - timedelta(minutes=30)),
        _lifecycle("day-1", 97, asset_class="stock", symbol="NVDA", timestamp=NOW - timedelta(minutes=20)),
        _lifecycle("day-1", 95, asset_class="stock", symbol="NVDA", timestamp=NOW - timedelta(minutes=10)),
        _lifecycle("day-1", 101, asset_class="stock", symbol="NVDA", closed=True, timestamp=NOW),
        _lifecycle("crypto-1", 100, lane_id="CRYPTO", timestamp=NOW - timedelta(minutes=30)),
        _lifecycle("crypto-1", 105, lane_id="CRYPTO", timestamp=NOW - timedelta(minutes=20)),
        _lifecycle("crypto-1", 103, lane_id="CRYPTO", closed=True, timestamp=NOW),
    ]
        payload = build_shadow_profit_loss_protection_validation_v1(path)
        day = payload["lane_results"]["DAY"]
        replay = day["fixed_loss_threshold_results"]["-3"]
        self.assertEqual(replay["crossing_count"], 1)
        self.assertEqual(replay["recovered_to_profitable_close_count"], 1)
        self.assertEqual(replay["counterfactual_evidence_class"], "SHADOW_COUNTERFACTUAL")
        protection = payload["lane_results"]["CRYPTO"]["profit_protection_results"]["trigger_3_giveback_20"]
        self.assertEqual(protection["triggered_count"], 1)
        self.assertFalse(payload["forced_exits_enabled"])
        self.assertFalse(payload["learned_exits_enabled"])

    def test_corrupted_rows_excluded_and_small_or_concentrated_samples_never_promote(self):
        corrupted = _lifecycle("bad", 90, closed=True, verified=False)
        insufficient = build_shadow_profit_loss_protection_validation_v1([corrupted])
        self.assertEqual(insufficient["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(insufficient["exclusion_reasons"]["entry_price_unverified"], 1)
        concentrated = []
        for index in range(50):
            concentrated.extend([
            _lifecycle(f"same-{index}", 100, timestamp=NOW - timedelta(minutes=1)),
            _lifecycle(f"same-{index}", 95, closed=True, timestamp=NOW),
            ])
        result = build_shadow_profit_loss_protection_validation_v1(concentrated)
        candidate = result["lane_results"]["CRYPTO"]["human_review_assessment"]
        self.assertEqual(candidate["readiness_tier"], "REVIEW_READY")
        self.assertFalse(candidate["human_review_candidate"])
        self.assertEqual(candidate["blocker"], "symbol_concentration")

    def test_position_advisories_are_not_orders_or_policy_activation(self):
        payload = build_shadow_profit_loss_protection_validation_v1([], [{
        "position_id": "active", "symbol": "ETH/USD", "asset_class": "crypto", "entry_price": 100,
        "current_price": 104, "entry_price_verified": True, "profit_giveback_pct": 1.0,
        }])
        self.assertEqual(payload["position_level_advisories"][0]["recommended_advisory_action"], "PROTECT_PROFIT")
        self.assertFalse(payload["automatic_activation_allowed"])
        self.assertFalse(payload["broker_behavior_changed"])


if __name__ == "__main__":
    unittest.main()
