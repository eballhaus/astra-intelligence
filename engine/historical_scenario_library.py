"""Historical Scenario Library V1, local-only scenario metadata."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class HistoricalScenarioLibrary:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.scenarios: list[dict[str, Any]] = [
            {
                "name": "2008 Financial Crisis",
                "period": "2007-2009",
                "regime_type": "credit_crisis_bear_market",
                "volatility_profile": "extreme_and_persistent",
                "interest_rate_backdrop": "rapid_policy_easing_after_credit_stress",
                "sector_leadership": ["defensives", "gold", "high_quality_balance_sheets"],
                "winning_setup_families": ["capital_preservation", "short_weak_financials", "defensive_relative_strength"],
                "losing_setup_families": ["levered_cyclicals", "falling_knife_value", "unconfirmed_breakouts"],
            },
            {
                "name": "2020 COVID Crash",
                "period": "2020",
                "regime_type": "exogenous_shock_crash_then_liquidity_rebound",
                "volatility_profile": "fast_spike_then_compression",
                "interest_rate_backdrop": "zero_rate_policy_and_emergency_liquidity",
                "sector_leadership": ["mega_cap_tech", "software", "stay_at_home", "biotech"],
                "winning_setup_families": ["liquidity_reversal", "relative_strength_after_capitulation", "digital_growth"],
                "losing_setup_families": ["travel_reopening_before_confirmation", "high_debt_cyclicals"],
            },
            {
                "name": "2021 Bull Expansion",
                "period": "2021",
                "regime_type": "liquidity_driven_bull_market",
                "volatility_profile": "moderate_with_speculative_bursts",
                "interest_rate_backdrop": "low_rates_and_expansive_liquidity",
                "sector_leadership": ["growth", "semiconductors", "crypto", "consumer_discretionary"],
                "winning_setup_families": ["momentum_continuation", "breakout_follow_through", "risk_on_rotation"],
                "losing_setup_families": ["early_mean_reversion_shorts", "low_growth_defensives"],
            },
            {
                "name": "2022 Bear Market",
                "period": "2022",
                "regime_type": "inflation_rate_hike_bear_market",
                "volatility_profile": "high_with_failed_rallies",
                "interest_rate_backdrop": "aggressive_hiking_cycle",
                "sector_leadership": ["energy", "defensives", "cash_flow_quality"],
                "winning_setup_families": ["defensive_rotation", "short_duration_quality", "failed_rally_fades"],
                "losing_setup_families": ["long_duration_unprofitable_growth", "dip_buying_without_regime_confirmation"],
            },
            {
                "name": "2023 AI/Mega-Cap Rotation",
                "period": "2023",
                "regime_type": "narrow_leadership_growth_rotation",
                "volatility_profile": "index_calm_with_underlying_dispersion",
                "interest_rate_backdrop": "restrictive_rates_with_soft_landing_expectations",
                "sector_leadership": ["mega_cap_tech", "semiconductors", "ai_infrastructure"],
                "winning_setup_families": ["mega_cap_relative_strength", "ai_catalyst_momentum", "quality_growth"],
                "losing_setup_families": ["low_quality_small_caps", "broad_beta_without_leadership"],
            },
            {
                "name": "2024-2026 Current Cycle",
                "period": "2024-2026",
                "regime_type": "ai_capex_rates_and_selective_risk_cycle",
                "volatility_profile": "episodic_spikes_with_leadership_rotation",
                "interest_rate_backdrop": "higher_for_longer_transition_to_policy_optionalität",
                "sector_leadership": ["ai_infrastructure", "mega_cap_quality", "select_industrials", "crypto_when_liquidity_expands"],
                "winning_setup_families": ["quality_momentum", "earnings_revision_leaders", "cash_flow_plus_catalyst"],
                "losing_setup_families": ["crowded_chase_after_exhaustion", "weak_balance_sheet_laggers", "macro_sensitive_without_confirmation"],
            },
        ]

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "local_historical_scenario_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "historical_scenario_status_v1": True,
            "scenario_count": len(self.scenarios),
            "scenarios": self.scenarios,
            "scenario_names": [s["name"] for s in self.scenarios],
            "confidence_score": 100.0,
            "next_recommended_action": "map future replay_windows_to_scenario_tags_without_live_strategy_changes",
            "changes_live_trading": False,
        }
