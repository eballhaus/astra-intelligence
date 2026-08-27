"""Focused safety contracts for bounded real-evidence discovery."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from engine.broad_universe_intake_promotion_v1 import BroadUniverseIntakePromotionV1


def test_inventory_does_not_inject_synthetic_candidates() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        original = [{"symbol": "AAPL", "price": 200.0, "provider_quote_timestamp": "2026-08-27T14:00:00Z"}]
        assert owner.decorate_candidates(original) == original


def test_rotation_is_bounded_and_preserves_exploration(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        monkeypatch.setenv("ASTRA_DISCOVERY_ROTATION_SIZE", "24")
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        inventory = [f"A{chr(65 + (i // 26))}{chr(65 + (i % 26))}" for i in range(40)]
        known = [
            {"symbol": "AAA", "confidence": 90.0, "quote_age_seconds": 10.0},
            {"symbol": "AAB", "confidence": 80.0, "quote_age_seconds": 10.0},
        ]
        result = owner.select_rotation(known_rows=known, inventory_symbols=inventory)
        symbols = result["symbols"]
        status = result["status"]
        assert len(symbols) == 24
        assert len(set(symbols)) == 24
        assert symbols[:2] == ["AAA", "AAB"]
        assert status["exploration_count"] > 0
        assert status["candidate_evidence_fabricated"] is False


def test_known_duplicate_is_pruned_before_rotation() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        result = owner.select_rotation(
            inventory_symbols=["AAPL", "MSFT", "NVDA"],
            excluded_symbols=["MSFT"],
        )
        assert "MSFT" not in result["symbols"]
        assert result["status"]["excluded_duplicate_or_active_symbols"] == 1


def test_prospective_marker_is_write_once() -> None:
    with TemporaryDirectory() as directory:
        owner = BroadUniverseIntakePromotionV1(state_dir=directory)
        first = owner.select_rotation(inventory_symbols=["AAPL"])["status"]["prospective_cohort"]
        second = owner.select_rotation(inventory_symbols=["MSFT"])["status"]["prospective_cohort"]
        assert first == second
        assert (Path(directory) / "adaptive_discovery_v1.json").exists()
