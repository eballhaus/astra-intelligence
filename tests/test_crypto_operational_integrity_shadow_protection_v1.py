from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
import unittest

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
