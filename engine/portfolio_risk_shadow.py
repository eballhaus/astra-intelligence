from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_json, _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PortfolioRiskShadow:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        positions_payload = _read_json(f"{self.state_dir}/positions_snapshot.json") or _read_json(f"{self.state_dir}/paper_positions.json")
        positions = positions_payload.get("positions") if isinstance(positions_payload.get("positions"), list) else []
        rows = positions if positions else _stable_rows(self.state_dir)
        sectors = Counter(str(r.get("sector") or r.get("theme") or "unknown").lower() for r in rows if isinstance(r, dict))
        caps = Counter(str(r.get("market_cap_bucket") or r.get("cap_bucket") or "unknown").lower() for r in rows if isinstance(r, dict))
        stop_risks = []
        for row in rows:
            price = _to_float(row.get("current_price"), _to_float(row.get("price"), 0.0))
            stop = _to_float(row.get("stop"), _to_float(row.get("stop_loss"), 0.0))
            if price > 0 and stop > 0:
                stop_risks.append(max(0.0, (price - stop) / price * 100.0))
        max_sector_share = (max(sectors.values()) / max(1, len(rows))) * 100.0 if rows else 0.0
        avg_stop_risk = sum(stop_risks) / max(1, len(stop_risks))
        heat = min(100.0, max_sector_share * 0.45 + avg_stop_risk * 1.8 + len(rows) * 2.0)
        warning = "concentration_watch" if max_sector_share >= 50.0 else "normal_shadow_risk"
        tier = "high" if heat >= 70 else "medium" if heat >= 45 else "low"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_first",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "portfolio_risk_shadow_status_v1": True,
            "positions_evaluated": len(rows),
            "total_exposure": "n/a_shadow_snapshot_only",
            "theme_concentration": dict(sectors.most_common(6)),
            "sector_concentration": dict(sectors.most_common(6)),
            "market_cap_balance": dict(caps.most_common(6)),
            "open_risk_by_stop_distance_pct": round(avg_stop_risk, 3),
            "max_suggested_risk_per_trade_pct": 1.0 if tier == "high" else 1.5 if tier == "medium" else 2.0,
            "portfolio_heat_score": round(heat, 3),
            "concentration_warning": warning,
            "suggested_risk_adjustment": "reduce_new_same_theme_exposure_shadow" if warning == "concentration_watch" else "maintain_shadow_risk_limits",
            "risk_tier": tier,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(80.0, 24.0 + len(rows) * 4.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "keep_portfolio_risk_controls_shadow_only_until_broker_policy_review",
        }
