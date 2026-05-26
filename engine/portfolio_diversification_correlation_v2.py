from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

try:
    from engine.profit_seeking_adaptive_exploration_v1 import ProfitSeekingAdaptiveExplorationV1
except Exception:  # pragma: no cover - additive hook
    ProfitSeekingAdaptiveExplorationV1 = None  # type: ignore[assignment]

VERSION = "2.0.0"
MAX_TAIL_BYTES = 2_000_000
MAX_ROWS = 900
CACHE_TTL_SECONDS = 10.0

MEGA_CAP_SYMBOLS = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "AVGO", "BRK.B", "BRK-A",
    "LLY", "JPM", "V", "MA", "COST", "WMT", "NFLX", "ORCL", "XOM", "AMD", "CRM", "ADBE",
}
AI_SEMI_SYMBOLS = {"NVDA", "AMD", "AVGO", "ARM", "TSM", "SMCI", "MU", "QCOM", "INTC", "ASML", "LRCX", "KLAC", "AMAT"}
MEGA_TECH_SYMBOLS = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META", "TSLA", "AVGO", "NFLX", "ORCL", "CRM", "ADBE"}
CONSUMER_GROWTH_SYMBOLS = {"AMZN", "TSLA", "NFLX", "COST", "HD", "LOW", "NKE", "SBUX", "MCD"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_text(value: Any, default: str = "") -> str:
    text = str(value or default).strip()
    return text if text else str(default)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except Exception:
        return low


def _score(value: Any, default: float = 50.0) -> float:
    out = _to_float(value, default)
    if out <= 1.0:
        out *= 100.0
    return _clamp(out)


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def _candidate_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pack_key in ("stocks", "crypto"):
        pack = payload.get(pack_key)
        if not isinstance(pack, dict):
            continue
        for section in ("final", "qualified", "watchlist", "fill"):
            values = pack.get(section)
            if isinstance(values, list):
                rows.extend([dict(v) for v in values if isinstance(v, dict)])
    dedup: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
        if symbol and symbol not in dedup:
            dedup[symbol] = row
    return list(dedup.values())


def _market_cap_bucket(row: dict[str, Any]) -> str:
    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
    raw = _safe_text(
        row.get("candidate_universe_tier")
        or row.get("market_cap_bucket")
        or row.get("market_cap_group")
        or row.get("market_cap_category")
        or row.get("cap_bucket")
    ).lower()
    cap = _to_float(row.get("market_cap") or row.get("market_capitalization") or row.get("marketCap"), 0.0)
    if "mega" in raw or cap >= 200_000_000_000 or symbol in MEGA_CAP_SYMBOLS:
        return "mega_cap"
    if "large" in raw or cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (0.0 < cap < 300_000_000):
        return "micro_cap"
    return "unknown"


def _quality(row: dict[str, Any]) -> float:
    return _score(
        row.get("edge_composite_score"),
        _score(row.get("risk_adjusted_trade_quality"), _score(row.get("risk_adjusted_profit_score"), _score(row.get("paper_allocation_priority"), 55.0))),
    )


def _expectancy(row: dict[str, Any]) -> float:
    return _score(
        row.get("adaptive_profitability_score"),
        _score(row.get("expected_value_score"), _score(row.get("expectancy_score"), _score(row.get("risk_adjusted_profit_score"), 55.0))),
    )


def _cluster_for(row: dict[str, Any]) -> tuple[str, str]:
    symbol = _safe_text(row.get("symbol") or row.get("ticker")).upper()
    sector = _safe_text(row.get("sector") or row.get("sector_name"), "unknown").lower().replace(" ", "_")
    industry = _safe_text(row.get("industry") or row.get("industry_name"), "").lower()
    cap = _market_cap_bucket(row)
    opp = _safe_text(row.get("candidate_opportunity_type") or row.get("allocation_lane") or row.get("setup_type"), "").lower()
    arch = _safe_text(row.get("trade_archetype") or row.get("setup_type"), "").lower()
    tags_raw = row.get("theme_tags") or row.get("entry_signal_tags") or row.get("signal_tags") or []
    tags = " ".join([str(x).lower() for x in tags_raw]) if isinstance(tags_raw, list) else str(tags_raw or "").lower()
    text = " ".join([sector, industry, opp, arch, tags])
    if symbol in AI_SEMI_SYMBOLS or any(x in text for x in ("semiconductor", "semi", "ai", "chip", "gpu")):
        return "ai_semiconductor_cluster", "AI / semiconductor cluster"
    if symbol in MEGA_TECH_SYMBOLS or (cap == "mega_cap" and any(x in sector for x in ("technology", "communication"))):
        return "mega_cap_tech_growth", "Mega-cap tech growth"
    if symbol in CONSUMER_GROWTH_SYMBOLS or ("consumer" in sector and cap in {"mega_cap", "large_cap"}):
        return "consumer_discretionary_growth", "Consumer discretionary growth"
    if any(x in text for x in ("momentum", "breakout", "runner", "unusual_volume")) or _score(row.get("momentum_expansion_score"), 50.0) >= 68.0:
        return "high_volatility_momentum_cluster", "High-volatility momentum cluster"
    if cap in {"mega_cap", "large_cap"}:
        return "broad_index_beta_cluster", "Broad index beta cluster"
    if sector and sector != "unknown":
        return f"{sector}_cluster", sector.replace("_", " ").title()
    return "unknown_cluster", "Unknown cluster"


def _family_for(row: dict[str, Any]) -> str:
    cluster, _ = _cluster_for(row)
    cap = _market_cap_bucket(row)
    horizon = _safe_text(row.get("best_horizon_style") or row.get("trade_horizon_style"), "unknown").lower()
    arch = _safe_text(row.get("trade_archetype") or row.get("setup_type") or row.get("allocation_lane"), "unknown").lower().replace(" ", "_")
    return f"{cluster}:{cap}:{horizon}:{arch}"


def _balance_label(score: float, concentration: float, correlation: float) -> str:
    if correlation >= 82.0:
        return "correlation_overload"
    if concentration >= 82.0:
        return "highly_concentrated"
    if concentration >= 65.0 or correlation >= 65.0:
        return "concentrated"
    if score >= 72.0:
        return "well_diversified"
    return "acceptable_balance"


def _maturity(rows: list[dict[str, Any]], has_metadata: bool) -> str:
    if not rows:
        return "insufficient_positions"
    if not has_metadata:
        return "insufficient_sector_metadata"
    if len(rows) < 6:
        return "warming_up"
    return "healthy_balance"


class PortfolioDiversificationCorrelationV2:
    """Paper-only/shadow-first portfolio diversification and correlation diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.labels_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")
        self.ledger_path = os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self.profit_seeking_exploration = (
            ProfitSeekingAdaptiveExplorationV1(state_dir=self.state_dir) if ProfitSeekingAdaptiveExplorationV1 is not None else None
        )

    def _history(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        rows.extend(_tail_jsonl(self.lifecycle_path, max_rows=350))
        rows.extend(_tail_jsonl(self.labels_path, max_rows=300))
        rows.extend(_tail_jsonl(self.ledger_path, max_rows=250))
        return rows[-MAX_ROWS:]

    def _peer_context(self, rows: list[dict[str, Any]], open_positions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        peers = [dict(r) for r in (rows or []) if isinstance(r, dict)][:180]
        open_rows = [dict(r) for r in (open_positions or []) if isinstance(r, dict)][:80]
        combined = peers + open_rows
        cluster_counts = Counter(_cluster_for(r)[0] for r in combined)
        family_counts = Counter(_family_for(r) for r in combined)
        sector_counts = Counter(_safe_text(r.get("sector") or r.get("sector_name"), "unknown").lower() for r in combined)
        cap_counts = Counter(_market_cap_bucket(r) for r in combined)
        arch_counts = Counter(_safe_text(r.get("trade_archetype") or r.get("setup_type") or r.get("allocation_lane"), "unknown").lower().replace(" ", "_") for r in combined)
        horizon_counts = Counter(_safe_text(r.get("best_horizon_style") or r.get("trade_horizon_style"), "unknown").lower() for r in combined)
        total = max(1, len(combined))
        largest_cluster, largest_count = cluster_counts.most_common(1)[0] if cluster_counts else ("unknown_cluster", 0)
        top_family, top_family_count = family_counts.most_common(1)[0] if family_counts else ("unknown", 0)
        mega = cap_counts.get("mega_cap", 0)
        metadata_count = sum(1 for r in combined if _safe_text(r.get("sector") or r.get("sector_name") or r.get("industry")))
        return {
            "peers": peers,
            "open_positions": open_rows,
            "combined": combined,
            "total": total,
            "cluster_counts": cluster_counts,
            "family_counts": family_counts,
            "sector_counts": sector_counts,
            "cap_counts": cap_counts,
            "arch_counts": arch_counts,
            "horizon_counts": horizon_counts,
            "largest_cluster": largest_cluster,
            "largest_cluster_count": int(largest_count),
            "top_duplicate_theme": top_family,
            "top_duplicate_theme_count": int(top_family_count),
            "mega_cap_concentration_pct": round((mega / total) * 100.0, 2),
            "metadata_coverage_pct": round((metadata_count / total) * 100.0, 2),
        }

    def score_row(self, row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        r = dict(row or {})
        cluster_id, cluster_label = _cluster_for(r)
        family = _family_for(r)
        total = max(1, _to_int(context.get("total"), 1))
        cluster_count = _to_int((context.get("cluster_counts") or {}).get(cluster_id), 0)
        family_count = _to_int((context.get("family_counts") or {}).get(family), 0)
        cap = _market_cap_bucket(r)
        cap_count = _to_int((context.get("cap_counts") or {}).get(cap), 0)
        sector = _safe_text(r.get("sector") or r.get("sector_name"), "unknown").lower()
        sector_count = _to_int((context.get("sector_counts") or {}).get(sector), 0)
        arch = _safe_text(r.get("trade_archetype") or r.get("setup_type") or r.get("allocation_lane"), "unknown").lower().replace(" ", "_")
        arch_count = _to_int((context.get("arch_counts") or {}).get(arch), 0)
        horizon = _safe_text(r.get("best_horizon_style") or r.get("trade_horizon_style"), "unknown").lower()
        horizon_count = _to_int((context.get("horizon_counts") or {}).get(horizon), 0)
        cluster_share = cluster_count / total
        family_share = family_count / total
        cap_share = cap_count / total
        sector_share = sector_count / total
        arch_share = arch_count / total
        horizon_share = horizon_count / total
        quality = _quality(r)
        expectancy = _expectancy(r)
        edge = _score(r.get("edge_composite_score"), quality)
        liquidity = _score(r.get("liquidity_score"), _score(r.get("execution_readiness_score"), 55.0))
        survivability = _score(r.get("survivability_score"), _score(r.get("portfolio_survivability_score"), 55.0))
        concentration_pressure = _clamp(max(cluster_share, sector_share, cap_share) * 100.0)
        correlation_pressure = _clamp((cluster_share * 55.0) + (family_share * 30.0) + (arch_share * 15.0))
        duplicate_theme = _clamp((family_share * 65.0) + (cluster_share * 25.0) + (horizon_share * 10.0))
        hidden_correlation = _clamp(correlation_pressure * 0.55 + (100.0 if cluster_id in {"mega_cap_tech_growth", "ai_semiconductor_cluster", "broad_index_beta_cluster"} else 35.0) * 0.25 + max(0.0, cap_share * 100.0 - 55.0) * 0.20)
        sector_balance = _clamp(100.0 - sector_share * 100.0)
        cap_balance = _clamp(100.0 - cap_share * 100.0)
        arch_balance = _clamp(100.0 - arch_share * 100.0)
        horizon_balance = _clamp(100.0 - horizon_share * 100.0)
        diversification_quality = _clamp((sector_balance * 0.25) + (cap_balance * 0.22) + (arch_balance * 0.20) + (horizon_balance * 0.13) + ((100.0 - correlation_pressure) * 0.20))
        portfolio_balance = _clamp(diversification_quality * 0.55 + (100.0 - concentration_pressure) * 0.25 + (100.0 - hidden_correlation) * 0.20)
        low_quality = quality < 52.0 or liquidity < 42.0 or survivability < 42.0
        diversify_bonus = 0.0
        if cluster_count <= 1 and family_count <= 1 and quality >= 58.0:
            diversify_bonus = min(9.0, (quality - 52.0) * 0.16 + (liquidity - 45.0) * 0.08)
        concentration_penalty = max(0.0, correlation_pressure - 45.0) * 0.24 + max(0.0, duplicate_theme - 45.0) * 0.18 + max(0.0, concentration_pressure - 70.0) * 0.16
        elite_override = bool(edge >= 82.0 or (quality >= 80.0 and expectancy >= 72.0))
        if elite_override:
            concentration_penalty *= 0.45
        if low_quality:
            diversify_bonus = 0.0
        portfolio_fit = _clamp((quality * 0.34) + (expectancy * 0.20) + (survivability * 0.18) + (liquidity * 0.12) + diversification_quality * 0.16 + diversify_bonus - concentration_penalty)
        corr_expectancy = _clamp(expectancy - concentration_penalty * 0.42 + diversify_bonus * 0.35)
        conc_expectancy = _clamp(expectancy - max(0.0, concentration_pressure - 55.0) * 0.22 + diversify_bonus * 0.25)
        adjusted_opportunity = _clamp(_score(r.get("paper_allocation_priority"), quality) * 0.58 + portfolio_fit * 0.30 + corr_expectancy * 0.12)
        label = "good_portfolio_fit"
        reason = "portfolio fit acceptable with current candidate mix"
        selection_reason = "balanced_quality_and_portfolio_fit"
        block_reason = ""
        if portfolio_fit < 35.0 and not elite_override:
            label = "poor_portfolio_fit"
            reason = "candidate adds concentrated/correlated exposure without enough quality edge"
            block_reason = "poor_portfolio_fit"
            selection_reason = "deprioritize_concentration_pressure"
        elif hidden_correlation >= 78.0 and duplicate_theme >= 70.0 and not elite_override:
            label = "correlation_overload"
            reason = "candidate duplicates an already crowded correlation cluster"
            block_reason = "correlation_overload"
            selection_reason = "deprioritize_duplicate_cluster"
        elif duplicate_theme >= 72.0 and not elite_override:
            label = "duplicate_theme_watch"
            reason = "candidate belongs to an overrepresented opportunity family"
            block_reason = "duplicate_theme_overstack" if portfolio_fit < 48.0 else ""
            selection_reason = "watch_duplicate_theme_pressure"
        elif diversify_bonus > 0:
            label = "diversifying_quality_fit"
            reason = "candidate adds quality exposure outside the largest current cluster"
            selection_reason = "diversification_quality_bonus"
        elif elite_override:
            label = "elite_edge_survives_concentration"
            reason = "elite quality/expectancy survives concentration penalty in shadow review"
            selection_reason = "elite_edge_override"
        theme_label = "theme_crowding_watch" if duplicate_theme >= 62.0 else "theme_balance_ok"
        if duplicate_theme >= 82.0:
            theme_label = "duplicate_theme_overstack"
        balance_label = _balance_label(diversification_quality, concentration_pressure, hidden_correlation)
        return {
            "portfolio_diversification_v2_active": True,
            "portfolio_diversification_shadow_only": True,
            "correlation_cluster_id": cluster_id,
            "correlation_cluster_label": cluster_label,
            "correlation_cluster_score": round(_clamp(100.0 - hidden_correlation), 2),
            "cluster_member_count": int(cluster_count),
            "cluster_overstack_risk": round(concentration_pressure, 2),
            "hidden_correlation_risk": round(hidden_correlation, 2),
            "duplicate_theme_score": round(duplicate_theme, 2),
            "duplicate_theme_label": theme_label,
            "duplicate_theme_reason": f"Family {family} has {family_count} of {total} reviewed candidates/positions.",
            "opportunity_family": family,
            "opportunity_family_count": int(family_count),
            "theme_crowding_score": round(duplicate_theme, 2),
            "theme_crowding_label": theme_label,
            "diversification_quality_score": round(diversification_quality, 2),
            "diversification_quality_label": balance_label,
            "portfolio_balance_score": round(portfolio_balance, 2),
            "portfolio_concentration_pressure": round(concentration_pressure, 2),
            "correlation_pressure_score": round(correlation_pressure, 2),
            "sector_balance_score": round(sector_balance, 2),
            "cap_tier_balance_score": round(cap_balance, 2),
            "archetype_balance_score": round(arch_balance, 2),
            "horizon_balance_score": round(horizon_balance, 2),
            "correlation_adjusted_expectancy": round(corr_expectancy, 2),
            "concentration_adjusted_expectancy": round(conc_expectancy, 2),
            "diversification_adjusted_opportunity_score": round(adjusted_opportunity, 2),
            "portfolio_fit_score": round(portfolio_fit, 2),
            "portfolio_fit_label": label,
            "portfolio_fit_reason": reason,
            "diversification_selection_reason": selection_reason,
            "portfolio_diversification_block_reason": block_reason,
            "elite_candidate_survived_concentration_penalty": bool(elite_override and concentration_penalty > 0.0),
            "candidate_deprioritized_for_correlation": bool(block_reason in {"correlation_overload", "duplicate_theme_overstack", "poor_portfolio_fit"}),
            "candidate_boosted_for_diversification": bool(diversify_bonus > 0),
            "current_portfolio_balance_label": balance_label,
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
        }

    def decorate_candidates(self, rows: list[dict[str, Any]] | None, open_positions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        base = [dict(r) for r in (rows or []) if isinstance(r, dict)][:220]
        context = self._peer_context(base, open_positions=open_positions)
        out: list[dict[str, Any]] = []
        for row in base:
            r = dict(row)
            try:
                r.update(self.score_row(r, context))
            except Exception:
                r.update({
                    "portfolio_diversification_v2_active": True,
                    "portfolio_diversification_shadow_only": True,
                    "correlation_cluster_id": "unknown_cluster",
                    "correlation_cluster_label": "Unknown cluster",
                    "portfolio_fit_score": 50.0,
                    "portfolio_fit_label": "warming_up",
                    "portfolio_fit_reason": "portfolio diversification scorer fallback",
                    "diversification_quality_score": 50.0,
                    "duplicate_theme_label": "unknown",
                    "natural_exit_preserved": True,
                    "live_trading_changed": False,
                    "api_calls_used": 0,
                })
            out.append(r)
        return out

    def rank_for_paper_selection(self, rows: list[dict[str, Any]] | None, open_positions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        decorated = self.decorate_candidates(rows, open_positions=open_positions)
        def key(row: dict[str, Any]) -> tuple[float, float, float]:
            quality_priority = _score(row.get("paper_allocation_priority"), _quality(row))
            fit = _score(row.get("portfolio_fit_score"), 50.0)
            adjusted = _score(row.get("diversification_adjusted_opportunity_score"), quality_priority)
            return (quality_priority * 0.72 + fit * 0.18 + adjusted * 0.10, quality_priority, fit)
        ranked = sorted(decorated, key=key, reverse=True)
        for idx, row in enumerate(ranked, start=1):
            row["portfolio_diversification_rank"] = idx
        return ranked

    def enrich_payload(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(payload or {})
        rows = _candidate_rows(out)
        context = self._peer_context(rows)
        for pack_key in ("stocks", "crypto"):
            pack = out.get(pack_key)
            if not isinstance(pack, dict):
                continue
            new_pack = dict(pack)
            for section in ("final", "qualified", "watchlist", "fill"):
                values = new_pack.get(section)
                if isinstance(values, list):
                    new_values = []
                    for value in values:
                        if not isinstance(value, dict):
                            continue
                        row = dict(value)
                        try:
                            row.update(self.score_row(row, context))
                        except Exception:
                            row.setdefault("portfolio_diversification_v2_active", True)
                        new_values.append(row)
                    new_pack[section] = new_values
            out[pack_key] = new_pack
        out["portfolio_diversification_correlation_v2"] = True
        out["portfolio_diversification_correlation_summary_v2"] = self.status(rows=rows)
        return out

    def status(self, rows: list[dict[str, Any]] | None = None, open_positions: list[dict[str, Any]] | None = None, force: bool = False, **_: Any) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            cached["cache_age_seconds"] = round(now - self._cache_ts, 3)
            cached["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return cached
        base = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        history = self._history()
        if not base:
            base = history[-120:]
        decorated = self.decorate_candidates(base, open_positions=open_positions)
        context = self._peer_context(decorated, open_positions=open_positions)
        values = lambda key: [_to_float(r.get(key), 0.0) for r in decorated if r.get(key) not in (None, "")]
        avg = lambda key, default=None: round(mean(values(key)), 2) if values(key) else default
        cluster_counts = Counter(_safe_text(r.get("correlation_cluster_label"), "Unknown cluster") for r in decorated)
        theme_counts = Counter(_safe_text(r.get("opportunity_family"), "unknown") for r in decorated)
        label_counts = Counter(_safe_text(r.get("portfolio_fit_label"), "unknown") for r in decorated)
        largest_cluster, largest_count = cluster_counts.most_common(1)[0] if cluster_counts else ("Unknown cluster", 0)
        top_theme, _theme_count = theme_counts.most_common(1)[0] if theme_counts else ("unknown", 0)
        penalized = [r for r in decorated if r.get("candidate_deprioritized_for_correlation")]
        boosted = [r for r in decorated if r.get("candidate_boosted_for_diversification")]
        elite_survived = [r for r in decorated if r.get("elite_candidate_survived_concentration_penalty")]
        non_mega_quality = [r for r in decorated if _market_cap_bucket(r) not in {"mega_cap"} and _quality(r) >= 58.0]
        corr_pressure = avg("correlation_pressure_score", None)
        conc_pressure = avg("portfolio_concentration_pressure", None)
        div_quality = avg("diversification_quality_score", None)
        fit = avg("portfolio_fit_score", None)
        balance = Counter(_safe_text(r.get("current_portfolio_balance_label"), "warming_up") for r in decorated).most_common(1)[0][0] if decorated else "insufficient_positions"
        has_metadata = _to_float(context.get("metadata_coverage_pct"), 0.0) > 20.0
        maturity = _maturity(decorated, has_metadata)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_shadow_diversification",
            "maturity": maturity,
            "portfolio_diversification_v2_active": True,
            "candidates_evaluated": int(len(decorated)),
            "average_portfolio_fit_score": fit,
            "average_diversification_quality_score": div_quality,
            "average_correlation_pressure_score": corr_pressure,
            "average_concentration_pressure_score": conc_pressure,
            "largest_cluster": largest_cluster,
            "largest_cluster_count": int(largest_count),
            "top_duplicate_theme": top_theme,
            "mega_cap_concentration_pct": _to_float(context.get("mega_cap_concentration_pct"), 0.0),
            "non_mega_quality_candidates": int(len(non_mega_quality)),
            "correlation_adjusted_expectancy_avg": avg("correlation_adjusted_expectancy", None),
            "concentration_adjusted_expectancy_avg": avg("concentration_adjusted_expectancy", None),
            "candidates_penalized_for_correlation": int(len(penalized)),
            "candidates_boosted_for_diversification": int(len(boosted)),
            "elite_candidates_survived_penalty": int(len(elite_survived)),
            "current_portfolio_balance_label": balance,
            "candidate_cluster_summary": {
                "clusters": dict(cluster_counts.most_common(10)),
                "families": dict(theme_counts.most_common(8)),
                "portfolio_fit_labels": dict(label_counts),
                "market_cap_distribution": dict(context.get("cap_counts") or {}),
                "sector_distribution": dict(context.get("sector_counts") or {}),
            },
            "portfolio_survivability": _clamp(100.0 - _to_float(conc_pressure, 50.0) * 0.30 - _to_float(corr_pressure, 50.0) * 0.25 + _to_float(div_quality, 50.0) * 0.55),
            "concentration_risk": conc_pressure,
            "correlation_risk": corr_pressure,
            "diversification_quality": div_quality,
            "portfolio_fit_quality": fit,
            "summary": f"Largest cluster {largest_cluster} ({largest_count}); balance {balance}; penalized {len(penalized)}, boosted {len(boosted)}.",
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "stale": False,
            "degraded_reason": "" if decorated else "waiting_for_candidate_or_position_data",
            "api_calls_used": 0,
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "provider_rewrite_changed": False,
            "profit_seeking_adaptive_exploration_hooks_ready": bool(self.profit_seeking_exploration is not None),
            "generated_at": _now_iso(),
        }
        out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
        self._cache = dict(out)
        self._cache_ts = now
        return out
