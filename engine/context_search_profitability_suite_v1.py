from __future__ import annotations

import json
import os
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


def _read_jsonl(path: str, limit: int = 2000) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    rows: list[dict[str, Any]] = []
    try:
        max_bytes = 900_000
        with open(path, "rb") as fh:
            try:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_bytes), os.SEEK_SET)
            except Exception:
                fh.seek(0)
            raw = fh.read(max_bytes).decode("utf-8", errors="ignore")
        lines = raw.splitlines()
        if len(lines) > 1 and not raw.startswith("{"):
            lines = lines[1:]
        for line in lines[-limit:]:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    except Exception:
        return []
    return rows[-limit:]


def _rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return rows
    for section in ("final", "qualified", "watchlist", "fill"):
        for row in ((payload.get("stocks") or {}).get(section) or []):
            if isinstance(row, dict):
                rows.append(row)
    seen = set()
    unique = []
    for row in rows:
        sym = _text(row.get("symbol") or row.get("ticker")).upper()
        key = sym or id(row)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _market_cap_bucket(row: dict[str, Any]) -> str:
    raw = _norm(row.get("market_cap_category") or row.get("market_cap_bucket") or row.get("cap_bucket") or row.get("market_cap_group"))
    market_cap = _f(row.get("market_cap") or row.get("market_capitalization"), 0.0)
    if "mega" in raw or market_cap >= 200_000_000_000:
        return "mega_cap"
    if "large" in raw or market_cap >= 10_000_000_000:
        return "large_cap"
    if "mid" in raw or market_cap >= 2_000_000_000:
        return "mid_cap"
    if "small" in raw or market_cap >= 300_000_000:
        return "small_cap"
    if "micro" in raw or (market_cap > 0 and market_cap < 300_000_000):
        return "micro_cap"
    return "unknown"


def _label(score: float, positive: str = "tailwind", neutral: str = "neutral", negative: str = "headwind") -> str:
    if score >= 72:
        return f"strong_{positive}"
    if score >= 58:
        return f"moderate_{positive}"
    if score <= 35:
        return f"strong_{negative}"
    if score <= 45:
        return f"moderate_{negative}"
    return neutral


class ContextSearchProfitabilitySuiteV1:
    """Shadow-only context/profitability enrichment using local snapshot fields only."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def _seasonality_score(self, row: dict[str, Any]) -> tuple[float, str]:
        rows = _read_jsonl(os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"), limit=1200)
        if len(rows) < 12:
            return 50.0, "insufficient_data"
        now_month = datetime.now(UTC).month
        symbol = _text(row.get("symbol") or row.get("ticker")).upper()
        matches = []
        for item in rows:
            ts = _text(item.get("entry_timestamp") or item.get("signal_timestamp") or item.get("updated_at"))
            try:
                month = datetime.fromisoformat(ts.replace("Z", "+00:00")).month if ts else 0
            except Exception:
                month = 0
            if month == now_month or _text(item.get("symbol")).upper() == symbol:
                matches.append(item)
        if len(matches) < 4:
            return 50.0, "insufficient_matching_history"
        avg = sum(_f(r.get("realized_return_pct"), _f(r.get("pnl_pct"), 0.0)) for r in matches) / max(1, len(matches))
        score = _clamp(50.0 + avg * 7.0)
        return score, _label(score, positive="seasonal_tailwind", negative="seasonal_headwind")

    def score_row(self, row: dict[str, Any], peer_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        out = dict(row or {})
        peers = [p for p in list(peer_rows or []) if isinstance(p, dict)]
        reasons: list[str] = []
        penalties: list[str] = []

        sector = _text(out.get("sector") or out.get("sector_name") or out.get("industry_sector") or out.get("theme"), "unknown")
        sector_score_raw = out.get("sector_strength_score") or out.get("sector_context_score") or out.get("sector_momentum_score")
        if sector_score_raw is not None:
            sector_score = _clamp(_f(sector_score_raw, 50.0))
            sector_label = _label(sector_score, positive="sector_tailwind", negative="sector_headwind")
        elif sector != "unknown" and peers:
            same = sum(1 for p in peers if _text(p.get("sector") or p.get("sector_name") or p.get("theme"), "unknown") == sector)
            sector_score = _clamp(48.0 + min(18.0, same * 4.0))
            sector_label = "peer_supported_sector" if same > 1 else "sector_known_neutral"
        else:
            sector_score = 50.0
            sector_label = "sector_data_unavailable_neutral"

        cap_bucket = _market_cap_bucket(out)
        regime = _norm(out.get("market_regime") or out.get("regime") or out.get("risk_regime") or out.get("market_status"))
        risk_on = any(token in regime for token in ("risk_on", "bull", "momentum", "growth"))
        defensive = any(token in regime for token in ("defensive", "risk_off", "bear", "volatile"))
        cap_score = 50.0
        if cap_bucket in {"small_cap", "mid_cap", "micro_cap"} and risk_on:
            cap_score += 14.0
            reasons.append("risk_on_small_mid_upside_context")
        elif cap_bucket in {"mega_cap", "large_cap"} and defensive:
            cap_score += 12.0
            reasons.append("defensive_large_cap_preference")
        elif cap_bucket != "unknown":
            cap_score += 4.0
        cap_label = _label(_clamp(cap_score), positive="market_cap_tailwind", negative="market_cap_headwind") if cap_bucket != "unknown" else "market_cap_unknown_neutral"

        expected_return = _f(out.get("expected_return_pct"), _f(out.get("predicted_return_pct"), _f(out.get("expected_move_percent"), 0.0)))
        intraday = _f(out.get("intraday_score"), _f(out.get("momentum_score"), _f(out.get("trend_score"), 50.0)))
        opportunity = _f(out.get("opportunity_score_pct"), _f(out.get("profit_priority_score"), _f(out.get("astra_composite_score"), 50.0)))
        execution = _f(out.get("execution_quality_score"), _f(out.get("entry_quality_v3_score"), _f(out.get("entry_quality_score"), 50.0)))
        confidence = _f(out.get("confidence"), 50.0)
        liquidity = _f(out.get("liquidity_score"), _f(out.get("volume_score"), 55.0))
        spread_risk = _f(out.get("spread_risk"), _f(out.get("slippage_risk"), 0.0))
        portfolio_heat = _f(out.get("portfolio_heat_score"), 40.0)
        small_mid_base = 58.0 if cap_bucket in {"small_cap", "mid_cap", "micro_cap"} else 48.0
        small_mid_score = _clamp(
            small_mid_base
            + min(18.0, max(0.0, expected_return) * 2.0)
            + (intraday - 50.0) * 0.18
            + (opportunity - 50.0) * 0.22
            + (execution - 50.0) * 0.16
            - max(0.0, 55.0 - liquidity) * 0.35
            - max(0.0, 58.0 - confidence) * 0.22
            - spread_risk * 0.55
            - max(0.0, portfolio_heat - 60.0) * 0.18
        )
        if small_mid_score >= 65:
            reasons.append("small_mid_momentum_upside_supported")
        if liquidity < 45:
            penalties.append("liquidity_below_shadow_threshold")
        if confidence < 50:
            penalties.append("confidence_weak_for_momentum")

        catalyst_text = " ".join(_text(out.get(k)) for k in ("catalyst", "catalyst_context", "catalyst_text", "news_summary", "earnings_context"))
        earnings_days = _f(out.get("days_to_earnings"), 999.0)
        has_catalyst = bool(catalyst_text.strip()) or bool(out.get("has_catalyst") or out.get("earnings_nearby")) or abs(earnings_days) <= 14
        catalyst_score = 62.0 if has_catalyst else 50.0
        if abs(earnings_days) <= 3:
            catalyst_score += 8.0
            penalties.append("near_earnings_volatility")
        elif abs(earnings_days) <= 14:
            reasons.append("earnings_or_catalyst_window_present")
        catalyst_score = _clamp(catalyst_score)
        catalyst_label = _label(catalyst_score, positive="catalyst_tailwind", negative="catalyst_risk") if has_catalyst else "no_local_catalyst_detected_neutral"

        seasonality_score, seasonality_label = self._seasonality_score(out)

        theme_keys = []
        for p in peers:
            theme_keys.append(_text(p.get("theme") or p.get("sector") or p.get("market_cap_bucket") or p.get("setup_type"), "unknown"))
        counts = Counter(k for k in theme_keys if k and k != "unknown")
        own_theme = _text(out.get("theme") or out.get("sector") or out.get("market_cap_bucket") or out.get("setup_type"), "unknown")
        own_count = counts.get(own_theme, 0)
        crowding_score = _clamp(100.0 - min(55.0, max(0, own_count - 1) * 18.0)) if own_theme != "unknown" else 60.0
        crowding_label = "overcrowded_theme_shadow_penalty" if crowding_score < 55 else ("diversified_theme_context" if crowding_score >= 72 else "theme_crowding_neutral")
        if crowding_score < 55:
            penalties.append("theme_or_sector_overcrowded")

        context_score = _clamp(
            sector_score * 0.18
            + cap_score * 0.14
            + small_mid_score * 0.18
            + catalyst_score * 0.15
            + seasonality_score * 0.15
            + crowding_score * 0.10
            + opportunity * 0.10
        )
        profitability_score = _clamp(
            context_score * 0.30
            + opportunity * 0.24
            + max(0.0, min(100.0, expected_return * 8.0 + 50.0)) * 0.18
            + confidence * 0.12
            + execution * 0.10
            + small_mid_score * 0.06
        )
        if sector_score >= 62:
            reasons.append(f"sector_context_{sector_label}")
        if catalyst_score >= 62:
            reasons.append(f"catalyst_context_{catalyst_label}")
        if seasonality_score < 45:
            penalties.append("seasonality_shadow_headwind")
        summary = (
            f"Context is {_label(context_score, positive='supportive', negative='challenging').replace('_', ' ')}; "
            f"sector={sector_label.replace('_', ' ')}, cap={cap_label.replace('_', ' ')}, "
            f"crowding={crowding_label.replace('_', ' ')}."
        )
        out.update({
            "context_search_profitability_suite_v1": True,
            "context_shadow_only": True,
            "sector_context_score": round(sector_score, 3),
            "sector_context_label": sector_label,
            "market_cap_bucket": cap_bucket,
            "market_cap_context_score": round(_clamp(cap_score), 3),
            "market_cap_context_label": cap_label,
            "small_mid_momentum_score": round(small_mid_score, 3),
            "catalyst_context_score": round(catalyst_score, 3),
            "catalyst_context_label": catalyst_label,
            "seasonality_context_score": round(seasonality_score, 3),
            "seasonality_context_label": seasonality_label,
            "theme_crowding_score": round(crowding_score, 3),
            "theme_crowding_label": crowding_label,
            "context_score": round(context_score, 3),
            "context_label": _label(context_score, positive="context_tailwind", negative="context_headwind"),
            "profitability_context_score": round(profitability_score, 3),
            "profitability_context_label": _label(profitability_score, positive="profitability_tailwind", negative="profitability_headwind"),
            "context_reasons": list(dict.fromkeys(reasons))[:8],
            "context_penalties": list(dict.fromkeys(penalties))[:8],
            "context_summary": summary,
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
        summary = self.status(rows=peer_rows)
        out["context_search_profitability_suite_v1"] = True
        out["context_search_profitability_summary"] = summary
        out["api_calls_used"] = int(_f(out.get("api_calls_used"), 0.0))
        return out

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        source_rows = [dict(r) for r in list(rows or []) if isinstance(r, dict)]
        scored = self.enrich_rows(source_rows) if source_rows else []
        avg = sum(_f(r.get("context_score"), 0.0) for r in scored) / max(1, len(scored))
        tailwinds = []
        penalties = []
        for row in scored:
            tailwinds.extend(list(row.get("context_reasons") or []))
            penalties.extend(list(row.get("context_penalties") or []))
        tailwind_counts = Counter(tailwinds)
        penalty_counts = Counter(penalties)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "context_search_profitability_status_v1": True,
            "candidates_evaluated": len(scored),
            "average_context_score": round(avg, 3),
            "strongest_context_tailwind": tailwind_counts.most_common(1)[0][0] if tailwind_counts else "neutral_or_insufficient_data",
            "strongest_context_penalty": penalty_counts.most_common(1)[0][0] if penalty_counts else "none_detected",
            "sector_rotation_enabled": True,
            "market_cap_adaptation_enabled": True,
            "small_mid_momentum_enabled": True,
            "catalyst_context_enabled": True,
            "seasonality_learning_enabled": True,
            "theme_crowding_detection_enabled": True,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "review_context_profitability_fields_as_shadow_diagnostics_only",
        }
