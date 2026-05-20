from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_text(value: Any, default: str = "") -> str:
    out = str(value or default).strip()
    return out if out else str(default)


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, float(value)))


def _risk_label(score: float) -> str:
    n = _clamp(score)
    if n >= 75.0:
        return "high_risk"
    if n >= 60.0:
        return "elevated_risk"
    if n <= 35.0:
        return "low_risk"
    return "moderate_risk"


def _allocation_label(score: float) -> str:
    n = _clamp(score)
    if n >= 80.0:
        return "strong_allocation_candidate"
    if n >= 65.0:
        return "moderate_allocation_candidate"
    if n >= 50.0:
        return "cautious_allocation_candidate"
    return "minimal_allocation_candidate"


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _safe_text(
        row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization"), 0.0)
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


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bucket in ("stocks", "crypto"):
        pack = payload.get(bucket)
        if not isinstance(pack, dict):
            continue
        for key in ("final", "qualified", "fill", "watchlist"):
            section = pack.get(key)
            if isinstance(section, list):
                for row in section:
                    if isinstance(row, dict):
                        rows.append(row)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
        key = symbol or str(id(row))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


class PortfolioRiskIntelligenceSuiteV1:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def _peer_counters(self, rows: list[dict[str, Any]]) -> tuple[Counter[str], Counter[str], Counter[str]]:
        sector_counts: Counter[str] = Counter()
        theme_counts: Counter[str] = Counter()
        cap_counts: Counter[str] = Counter()
        for row in rows:
            sector = _safe_text(row.get("sector") or row.get("sector_name"), "unknown").lower()
            theme = _safe_text(row.get("theme") or row.get("setup_type") or row.get("industry"), "unknown").lower()
            cap = _market_cap_bucket(row)
            if sector != "unknown":
                sector_counts[sector] += 1
            if theme != "unknown":
                theme_counts[theme] += 1
            if cap != "unknown":
                cap_counts[cap] += 1
        return sector_counts, theme_counts, cap_counts

    def _score_row(self, row: dict[str, Any], peers: list[dict[str, Any]]) -> dict[str, Any]:
        out = dict(row or {})
        reasons: list[str] = []
        penalties: list[str] = []

        confidence = _clamp(_to_float(out.get("confidence"), 50.0))
        expected_return = _clamp(_to_float(out.get("expected_return_pct"), _to_float(out.get("predicted_profit_percent"), 0.0)) + 50.0, 0.0, 100.0)
        entry_quality = _clamp(_to_float(out.get("entry_quality_v2_score"), _to_float(out.get("entry_filter_v2_score"), 50.0)))
        context_score = _clamp(_to_float(out.get("context_score"), 50.0))
        execution_quality = _clamp(
            _to_float(
                out.get("execution_quality_score"),
                _to_float(out.get("current_engine_exit_timing_score"), _to_float(out.get("entry_filter_v2_score"), 50.0)),
            )
        )
        portfolio_heat = _clamp(
            _to_float(
                out.get("portfolio_heat_score"),
                _to_float(out.get("portfolio_concentration_index"), 45.0),
            )
        )

        sector_counts, theme_counts, cap_counts = self._peer_counters(peers)
        peer_n = max(1, len(peers))
        sector = _safe_text(out.get("sector") or out.get("sector_name"), "unknown").lower()
        theme = _safe_text(out.get("theme") or out.get("setup_type") or out.get("industry"), "unknown").lower()
        cap = _market_cap_bucket(out)
        sector_share = sector_counts.get(sector, 0) / peer_n if sector != "unknown" else 0.0
        theme_share = theme_counts.get(theme, 0) / peer_n if theme != "unknown" else 0.0
        cap_share = cap_counts.get(cap, 0) / peer_n if cap != "unknown" else 0.0

        correlation_risk_score = _clamp(max(sector_share, theme_share, cap_share) * 100.0)
        correlation_risk_label = _risk_label(correlation_risk_score)

        concentration_raw = (sector_share * 42.0) + (theme_share * 38.0) + (cap_share * 20.0)
        concentration_risk_level = _clamp(concentration_raw * 100.0)
        concentration_score = _clamp(100.0 - concentration_risk_level)
        concentration_label = _risk_label(concentration_risk_level)

        stop_distance_pct = _to_float(out.get("stop_distance_pct"), -1.0)
        if stop_distance_pct < 0:
            current_price = _to_float(out.get("current_price"), _to_float(out.get("price"), 0.0))
            stop_price = _to_float(out.get("stop_loss"), _to_float(out.get("stop"), 0.0))
            if current_price > 0 and stop_price > 0:
                stop_distance_pct = max(0.0, ((current_price - stop_price) / current_price) * 100.0)
            else:
                stop_distance_pct = 5.0
        stop_distance_risk = _clamp(100.0 - _clamp(stop_distance_pct * 10.0))

        drawdown_risk_score = _clamp(
            (portfolio_heat * 0.34)
            + (correlation_risk_score * 0.27)
            + (stop_distance_risk * 0.19)
            + (_clamp(100.0 - confidence) * 0.20)
        )
        drawdown_risk_label = _risk_label(drawdown_risk_score)

        recommended_portfolio_heat_limit = 65.0
        if correlation_risk_score >= 70.0 or concentration_risk_level >= 70.0:
            recommended_portfolio_heat_limit = 55.0
        elif drawdown_risk_score >= 65.0:
            recommended_portfolio_heat_limit = 60.0
        heat_adjustment_factor = _clamp(
            1.0
            - max(0.0, portfolio_heat - recommended_portfolio_heat_limit) / 100.0
            - max(0.0, correlation_risk_score - 50.0) / 180.0,
            0.35,
            1.0,
        )

        capital_allocation_score = _clamp(
            (confidence * 0.24)
            + (expected_return * 0.20)
            + (entry_quality * 0.18)
            + (context_score * 0.12)
            + (execution_quality * 0.12)
            + (concentration_score * 0.14)
            - (drawdown_risk_score * 0.18)
            - (correlation_risk_score * 0.10)
            + 10.0
        )
        capital_allocation_label = _allocation_label(capital_allocation_score)

        base_size = (capital_allocation_score / 100.0) * 12.0
        if confidence >= 85.0:
            base_size += 1.5
        if drawdown_risk_score >= 70.0:
            base_size -= 2.0
        recommended_position_size_pct = _clamp(base_size * heat_adjustment_factor, 0.0, 20.0)

        portfolio_risk_score = _clamp(
            100.0
            - (drawdown_risk_score * 0.38 + correlation_risk_score * 0.28 + concentration_risk_level * 0.18 + portfolio_heat * 0.16)
        )
        portfolio_risk_label = _risk_label(100.0 - portfolio_risk_score)

        if correlation_risk_score >= 60.0:
            penalties.append("correlation_cluster_detected")
        else:
            reasons.append("correlation_within_shadow_limits")
        if concentration_risk_level >= 60.0:
            penalties.append("theme_or_sector_concentration_elevated")
        else:
            reasons.append("concentration_within_shadow_limits")
        if drawdown_risk_score >= 60.0:
            penalties.append("drawdown_risk_elevated")
        else:
            reasons.append("drawdown_risk_contained")
        if recommended_position_size_pct >= 8.0:
            reasons.append("allocation_supported_by_shadow_signals")
        else:
            penalties.append("allocation_size_reduced_by_risk_controls")

        portfolio_risk_summary = (
            f"Shadow position size {recommended_position_size_pct:.1f}% with "
            f"{portfolio_risk_label.replace('_', ' ')}; "
            f"corr={correlation_risk_label.replace('_', ' ')}, "
            f"conc={concentration_label.replace('_', ' ')}, "
            f"dd={drawdown_risk_label.replace('_', ' ')}."
        )

        out.update(
            {
                "portfolio_risk_intelligence_suite_v1": True,
                "portfolio_risk_shadow_only": True,
                "recommended_position_size_pct": round(recommended_position_size_pct, 3),
                "capital_allocation_score": round(capital_allocation_score, 3),
                "capital_allocation_label": capital_allocation_label,
                "correlation_risk_score": round(correlation_risk_score, 3),
                "correlation_risk_label": correlation_risk_label,
                "concentration_score": round(concentration_score, 3),
                "concentration_label": concentration_label,
                "drawdown_risk_score": round(drawdown_risk_score, 3),
                "drawdown_risk_label": drawdown_risk_label,
                "recommended_portfolio_heat_limit": round(recommended_portfolio_heat_limit, 3),
                "heat_adjustment_factor": round(heat_adjustment_factor, 3),
                "portfolio_risk_score": round(portfolio_risk_score, 3),
                "portfolio_risk_label": portfolio_risk_label,
                "portfolio_risk_reasons": list(dict.fromkeys(reasons))[:8],
                "portfolio_risk_penalties": list(dict.fromkeys(penalties))[:8],
                "portfolio_risk_summary": portfolio_risk_summary,
                "api_calls_used": 0,
            }
        )
        return out

    def enrich_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        peers = [dict(r) for r in rows if isinstance(r, dict)]
        return [self._score_row(dict(r), peers) for r in peers]

    def enrich_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        out = dict(payload or {})
        peers = []
        for bucket in ("stocks", "crypto"):
            pack = out.get(bucket)
            if not isinstance(pack, dict):
                continue
            for row in pack.get("final") or []:
                if isinstance(row, dict):
                    peers.append(dict(row))
        if not peers:
            peers = _candidate_rows(out)[:24]
        for bucket in ("stocks", "crypto"):
            pack = dict(out.get(bucket) or {})
            rows = pack.get("final")
            if isinstance(rows, list):
                pack["final"] = [self._score_row(dict(row), peers) if isinstance(row, dict) else row for row in rows]
            out[bucket] = pack
        out["portfolio_risk_intelligence_suite_v1"] = True
        out["portfolio_risk_intelligence_summary"] = self.status(rows=peers)
        out["api_calls_used"] = int(_to_float(out.get("api_calls_used"), 0.0))
        return out

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = self.enrich_rows([dict(r) for r in list(rows or []) if isinstance(r, dict)]) if rows else []
        n = max(1, len(scored))
        avg_size = sum(_to_float(r.get("recommended_position_size_pct"), 0.0) for r in scored) / n
        avg_portfolio_risk = sum(_to_float(r.get("portfolio_risk_score"), 0.0) for r in scored) / n
        avg_cap_alloc = sum(_to_float(r.get("capital_allocation_score"), 0.0) for r in scored) / n
        max_corr = max([_to_float(r.get("correlation_risk_score"), 0.0) for r in scored] or [0.0])
        max_conc = max([100.0 - _to_float(r.get("concentration_score"), 100.0) for r in scored] or [0.0])
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "portfolio_risk_intelligence_status_v1": True,
            "candidates_evaluated": int(len(scored)),
            "average_recommended_position_size_pct": round(avg_size, 3),
            "average_portfolio_risk_score": round(avg_portfolio_risk, 3),
            "average_capital_allocation_score": round(avg_cap_alloc, 3),
            "highest_correlation_risk": round(max_corr, 3),
            "highest_concentration_risk": round(max_conc, 3),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "review_shadow_portfolio_risk_fields_without_execution_changes",
        }
