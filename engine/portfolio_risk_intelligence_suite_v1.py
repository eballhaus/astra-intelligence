from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _text(value: Any, default: str = "") -> str:
    out = str(value or default).strip()
    return out if out else str(default)


def _norm(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _label(score: float, *, positive: str = "strong", neutral: str = "neutral", negative: str = "weak") -> str:
    if score >= 75:
        return f"strong_{positive}"
    if score >= 60:
        return f"moderate_{positive}"
    if score <= 35:
        return f"high_{negative}"
    if score <= 48:
        return f"moderate_{negative}"
    return neutral


def _risk_label(score: float, neutral: str = "normal") -> str:
    if score >= 75:
        return "high_risk"
    if score >= 60:
        return "elevated_risk"
    if score <= 35:
        return "low_risk"
    return neutral


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _norm(row.get("market_cap_category") or row.get("market_cap_bucket") or row.get("cap_bucket") or row.get("market_cap_group"))
    cap = _f(row.get("market_cap") or row.get("market_capitalization"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000:
        return "mega_cap"
    if "large" in raw or cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (0 < cap < 300_000_000):
        return "micro_cap"
    return "unknown"


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for section in ("final", "qualified", "watchlist", "fill"):
        for row in ((payload.get("stocks") or {}).get(section) or []):
            if isinstance(row, dict):
                rows.append(row)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        sym = _text(row.get("symbol") or row.get("ticker")).upper()
        key = sym or str(id(row))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


class PortfolioRiskIntelligenceSuiteV1:
    """Shadow-only allocation and portfolio-risk diagnostics for candidate cards."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def _peer_counts(self, rows: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], Counter[str]]:
        sectors: Counter[str] = Counter()
        themes: Counter[str] = Counter()
        caps: Counter[str] = Counter()
        for row in rows:
            if not isinstance(row, dict):
                continue
            sector = _text(row.get("sector") or row.get("sector_name") or row.get("theme"), "unknown").lower()
            theme = _text(row.get("theme") or row.get("setup_type") or row.get("sector") or row.get("sector_name"), "unknown").lower()
            cap = _market_cap_bucket(row)
            if sector != "unknown":
                sectors[sector] += 1
            if theme != "unknown":
                themes[theme] += 1
            if cap != "unknown":
                caps[cap] += 1
        return sectors, themes, caps

    def score_row(self, row: dict[str, Any], peer_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        peers = [dict(r) for r in list(peer_rows or []) if isinstance(r, dict)]
        reasons: list[str] = []
        penalties: list[str] = []

        confidence = _f(out.get("confidence"), 50.0)
        expected_return = _f(out.get("expected_return_pct"), _f(out.get("expected_move_percent"), 0.0))
        entry_quality = _f(out.get("entry_quality_v3_score"), _f(out.get("entry_quality_score"), 50.0))
        context_score = _f(out.get("context_score"), 50.0)
        execution_quality = _f(out.get("execution_quality_score"), _f(out.get("entry_quality_score"), 50.0))
        portfolio_heat = _f(out.get("portfolio_heat_score"), 45.0)
        stop_distance = _f(out.get("stop_distance_pct"), 0.0)
        if stop_distance <= 0:
            price = _f(out.get("current_price"), _f(out.get("price"), 0.0))
            stop = _f(out.get("stop_loss"), _f(out.get("stop"), 0.0))
            if price > 0 and stop > 0:
                stop_distance = max(0.0, (price - stop) / price * 100.0)

        sectors, themes, caps = self._peer_counts(peers)
        sector = _text(out.get("sector") or out.get("sector_name") or out.get("theme"), "unknown").lower()
        theme = _text(out.get("theme") or out.get("setup_type") or out.get("sector") or out.get("sector_name"), "unknown").lower()
        cap = _market_cap_bucket(out)
        peer_n = max(1, len(peers))
        sector_share = sectors.get(sector, 0) / peer_n if sector != "unknown" else 0.0
        theme_share = themes.get(theme, 0) / peer_n if theme != "unknown" else 0.0
        cap_share = caps.get(cap, 0) / peer_n if cap != "unknown" else 0.0

        correlation_risk = _clamp(max(sector_share, theme_share, cap_share) * 100.0)
        correlation_label = _risk_label(correlation_risk, neutral="diversified_or_unknown")
        if correlation_risk >= 60:
            penalties.append("candidate_correlated_with_current_top_list")
        elif correlation_risk <= 35:
            reasons.append("candidate_adds_diversification")

        concentration_risk = _clamp((sector_share * 40.0) + (theme_share * 42.0) + (cap_share * 18.0))
        concentration_score = _clamp(100.0 - concentration_risk)
        concentration_label = _label(concentration_score, positive="diversification", negative="concentration_risk")
        if concentration_score < 50:
            penalties.append("theme_or_sector_concentration_elevated")

        heat_limit = 55.0 if correlation_risk >= 65 or concentration_score < 45 else 65.0 if portfolio_heat < 60 else 60.0
        heat_adjustment = _clamp(1.0 - max(0.0, portfolio_heat - heat_limit) / 100.0 - max(0.0, correlation_risk - 55.0) / 180.0, 0.35, 1.0)
        if heat_adjustment < 0.8:
            penalties.append("portfolio_heat_requires_position_size_reduction")

        drawdown_risk = _clamp((portfolio_heat * 0.34) + (correlation_risk * 0.26) + (max(0.0, stop_distance) * 2.1) + (max(0.0, 55.0 - confidence) * 0.25))
        drawdown_label = _risk_label(drawdown_risk, neutral="normal_drawdown_risk")
        if drawdown_risk >= 60:
            penalties.append("drawdown_pressure_elevated")

        upside_component = _clamp(50.0 + expected_return * 4.0)
        quality_mix = _clamp(confidence * 0.26 + upside_component * 0.20 + entry_quality * 0.18 + context_score * 0.16 + execution_quality * 0.12 + concentration_score * 0.08)
        risk_drag = (correlation_risk * 0.14) + (drawdown_risk * 0.16) + max(0.0, portfolio_heat - 50.0) * 0.18
        capital_score = _clamp(quality_mix - risk_drag + 12.0)
        capital_label = _label(capital_score, positive="allocation_candidate", negative="allocation_caution")
        if capital_score >= 68:
            reasons.append("risk_adjusted_allocation_supported")
        if capital_score < 45:
            penalties.append("capital_allocation_score_weak")

        base_size = (capital_score / 100.0) * 12.0
        if confidence >= 85 and expected_return > 8:
            base_size += 2.0
        if expected_return < 3:
            base_size -= 1.5
        recommended_size = _clamp(base_size * heat_adjustment, 0.0, 20.0)
        if drawdown_risk >= 70:
            recommended_size = min(recommended_size, 5.0)
        elif correlation_risk >= 75:
            recommended_size = min(recommended_size, 6.0)

        portfolio_risk_score = _clamp(100.0 - (drawdown_risk * 0.34 + correlation_risk * 0.26 + concentration_risk * 0.22 + portfolio_heat * 0.18))
        portfolio_risk_label = _label(portfolio_risk_score, positive="risk_adjusted", negative="risk_caution")
        summary = (
            f"Shadow allocation {recommended_size:.1f}% with {portfolio_risk_label.replace('_', ' ')} posture; "
            f"correlation={correlation_label.replace('_', ' ')}, concentration={concentration_label.replace('_', ' ')}, "
            f"drawdown={drawdown_label.replace('_', ' ')}."
        )
        out.update({
            "portfolio_risk_intelligence_suite_v1": True,
            "portfolio_risk_shadow_only": True,
            "recommended_position_size_pct": round(recommended_size, 3),
            "capital_allocation_score": round(capital_score, 3),
            "capital_allocation_label": capital_label,
            "correlation_risk_score": round(correlation_risk, 3),
            "correlation_risk_label": correlation_label,
            "concentration_score": round(concentration_score, 3),
            "concentration_label": concentration_label,
            "drawdown_risk_score": round(drawdown_risk, 3),
            "drawdown_risk_label": drawdown_label,
            "recommended_portfolio_heat_limit": round(heat_limit, 3),
            "heat_adjustment_factor": round(heat_adjustment, 3),
            "portfolio_risk_score": round(portfolio_risk_score, 3),
            "portfolio_risk_label": portfolio_risk_label,
            "portfolio_risk_reasons": list(dict.fromkeys(reasons))[:8],
            "portfolio_risk_penalties": list(dict.fromkeys(penalties))[:8],
            "portfolio_risk_summary": summary,
            "api_calls_used": 0,
        })
        return out

    def enrich_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        peers = [dict(r) for r in list(rows or []) if isinstance(r, dict)]
        return [self.score_row(dict(r), peers) for r in peers]

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        peer_rows = _rows_from_payload(out)
        for bucket in ("stocks", "crypto"):
            section = dict(out.get(bucket) or {})
            for key in ("final", "qualified", "watchlist", "fill"):
                rows = section.get(key)
                if isinstance(rows, list):
                    section[key] = [self.score_row(dict(r), peer_rows) if isinstance(r, dict) else r for r in rows]
            out[bucket] = section
        out["portfolio_risk_intelligence_suite_v1"] = True
        out["portfolio_risk_intelligence_summary"] = self.status(rows=peer_rows)
        out["api_calls_used"] = int(_f(out.get("api_calls_used"), 0.0))
        return out

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = self.enrich_rows([dict(r) for r in list(rows or []) if isinstance(r, dict)]) if rows else []
        n = max(1, len(scored))
        avg_size = sum(_f(r.get("recommended_position_size_pct"), 0.0) for r in scored) / n
        avg_risk = sum(_f(r.get("portfolio_risk_score"), 0.0) for r in scored) / n
        avg_alloc = sum(_f(r.get("capital_allocation_score"), 0.0) for r in scored) / n
        max_corr = max([_f(r.get("correlation_risk_score"), 0.0) for r in scored] or [0.0])
        max_conc_risk = max([100.0 - _f(r.get("concentration_score"), 100.0) for r in scored] or [0.0])
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "portfolio_risk_intelligence_status_v1": True,
            "candidates_evaluated": len(scored),
            "average_recommended_position_size_pct": round(avg_size, 3),
            "average_portfolio_risk_score": round(avg_risk, 3),
            "average_capital_allocation_score": round(avg_alloc, 3),
            "highest_correlation_risk": round(max_corr, 3),
            "highest_concentration_risk": round(max_conc_risk, 3),
            "dynamic_position_sizing_enabled": True,
            "correlation_control_enabled": True,
            "theme_concentration_limits_enabled": True,
            "portfolio_heat_management_enabled": True,
            "drawdown_protection_enabled": True,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "review_shadow_allocation_guidance_without_changing_execution",
        }
