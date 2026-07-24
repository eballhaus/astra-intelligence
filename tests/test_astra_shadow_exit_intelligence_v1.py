import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from engine.astra_shadow_exit_intelligence_v1 import (
    load_shadow_exit_state_v1,
    run_shadow_exit_cycle_v1,
    save_shadow_exit_cycle_v1,
    shadow_handoff_by_symbol_v1,
    shadow_position_identity_v1,
)
from engine.astra_unified_position_advisory_v1 import build_position_exit_readiness_v1, build_unified_position_advisory_v1


NOW = datetime(2026, 7, 24, 16, tzinfo=timezone.utc)


def _position(symbol="AAA", **extra):
    row = {"symbol": symbol, "asset_class": "equity", "broker_position_id": f"broker-{symbol}", "avg_entry_price": 100,
           "current_price": 95, "qty": 4, "market_value": 380, "unrealized_plpc": -0.05, "entry_timestamp": "2026-07-20T14:00:00Z"}
    row.update(extra)
    return row


def _inputs(symbol="AAA"):
    return {
        "recovery": {"positions": [{"symbol": symbol, "lane": "DAY", "horizon": "scalp", "lifecycle_id": "life-a"}]},
        "evidence": {"positions": [{"symbol": symbol, "quote_status": "FRESH", "quote_source": "ALPACA_MARKET_DATA", "quote_evidence_at": "2026-07-24T16:00:00Z", "current_price": 95}]},
        "exit_readiness": {"positions": [{"symbol": symbol, "recommendation": "EXIT_REVIEW", "generated_at": "2026-07-24T16:00:00Z", "profit_protection_state": "WATCH"}]},
    }


class ShadowExitFoundationTests(unittest.TestCase):
    def test_exact_identity_and_legacy_fingerprint_are_separated(self):
        exact = shadow_position_identity_v1(_position(), {"lifecycle_id": "life-a", "lane": "DAY", "horizon": "scalp"})
        legacy = shadow_position_identity_v1(_position(broker_position_id="", position_id=""), {"lane": "UNAVAILABLE", "horizon": "UNAVAILABLE"})
        self.assertEqual(exact["identity_confidence"], "CANONICAL")
        self.assertEqual(legacy["identity_source"], "BOUNDED_LEGACY_FINGERPRINT")
        self.assertNotEqual(exact["position_identity"], legacy["position_identity"])

    def test_reopened_and_quantity_changed_positions_have_new_identity(self):
        first = shadow_position_identity_v1(_position(entry_timestamp="2026-07-20T14:00:00Z"), {})
        reopened = shadow_position_identity_v1(_position(entry_timestamp="2026-07-24T14:00:00Z"), {})
        changed = shadow_position_identity_v1(_position(qty=9), {})
        self.assertNotEqual(first["position_identity"], reopened["position_identity"])
        self.assertNotEqual(first["position_identity"], changed["position_identity"])

    def test_recovered_active_lifecycle_id_is_exact_identity(self):
        identity = shadow_position_identity_v1(
            _position(broker_position_id="", position_id=""),
            {"lane": "DAY", "horizon": "scalp", "lane_source": "ACTIVE_POSITION_LIFECYCLE", "lane_source_id": "life-recovered"},
        )
        self.assertEqual(identity["lifecycle_id"], "life-recovered")
        self.assertEqual(identity["identity_confidence"], "CANONICAL")

    def test_cycle_creates_deduplicates_and_persists_baseline_evaluations(self):
        inputs = _inputs(); cycle = run_shadow_exit_cycle_v1({"AAA": _position()}, now=NOW, **inputs)
        self.assertEqual(len(cycle["state"]["evaluations"]), 5)
        self.assertEqual(cycle["diagnostics"]["positions_considered"], 1)
        self.assertGreater(cycle["diagnostics"]["pending_observations"], 0)
        repeat = run_shadow_exit_cycle_v1({"AAA": _position()}, previous={**cycle["state"], "observations": cycle["observations"]["observations"]}, now=NOW, **inputs)
        self.assertEqual(repeat["diagnostics"]["evaluations_created"], 0)
        with tempfile.TemporaryDirectory() as root:
            save_shadow_exit_cycle_v1(cycle, root)
            restored = load_shadow_exit_state_v1(root)
            self.assertEqual(len(restored["evaluations"]), 5)
            self.assertGreater(len(restored["observations"]), 0)

    def test_due_observation_uses_real_cached_price_only(self):
        inputs = _inputs(); first = run_shadow_exit_cycle_v1({"AAA": _position()}, now=NOW, **inputs)
        later = NOW + timedelta(hours=2)
        completed = run_shadow_exit_cycle_v1({"AAA": _position(current_price=97)}, previous={**first["state"], "observations": first["observations"]["observations"]}, now=later, **inputs)
        self.assertGreater(completed["diagnostics"]["completed_observations"], 0)
        stale = _inputs(); stale["evidence"]["positions"][0]["quote_status"] = "STALE"
        rejected = run_shadow_exit_cycle_v1({"AAA": _position()}, previous={**first["state"], "observations": first["observations"]["observations"]}, now=later, **stale)
        self.assertGreater(rejected["diagnostics"]["stale_rejected_observations"], 0)

    def test_handoff_is_advisory_only_and_broker_input_is_unchanged(self):
        position = _position(); before = dict(position); cycle = run_shadow_exit_cycle_v1({"AAA": position}, now=NOW, **_inputs())
        handoff = shadow_handoff_by_symbol_v1(cycle["state"])["AAA"]
        self.assertEqual(position, before)
        self.assertEqual(handoff["shadow_promotion_status"], "NOT_PROMOTED")
        self.assertEqual(handoff["shadow_signal_confidence"], "INSUFFICIENT_SAMPLE")

    def test_exit_and_unified_advisory_preserve_shadow_handoff(self):
        inputs = _inputs(); cycle = run_shadow_exit_cycle_v1({"AAA": _position()}, now=NOW, **inputs)
        handoff = shadow_handoff_by_symbol_v1(cycle["state"])
        exit_rows = build_position_exit_readiness_v1({"AAA": _position()}, evidence=inputs["evidence"], triage={}, shadow_handoff=handoff)
        advisory = build_unified_position_advisory_v1({"AAA": _position()}, evidence=inputs["evidence"], triage={}, exit_readiness=exit_rows, shadow_handoff=handoff)
        self.assertEqual(exit_rows["positions"][0]["shadow_promotion_status"], "NOT_PROMOTED")
        self.assertEqual(advisory["positions"][0]["execution_authority"], "DISABLED")
        self.assertTrue(advisory["positions"][0]["shadow_active_strategies"])
