from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Any

VERSION = "2.0.0"
CACHE_TTL_SECONDS = 14.0
MAX_TAIL_BYTES = 2_200_000
MAX_ROWS = 2000

CATALYST_TYPES = (
    "earnings_beat", "earnings_miss", "guidance_raise", "guidance_cut",
    "analyst_upgrade", "analyst_downgrade", "FDA_or_regulatory", "contract_award",
    "merger_acquisition", "sector_sympathy", "retail_social_momentum", "macro_news",
    "commodity_related", "interest_rate_related", "government_policy", "AI_theme",
    "quantum_theme", "crypto_theme", "defense_theme", "energy_theme", "nuclear_theme",
    "obesity_drug_theme", "semiconductor_theme", "unknown_catalyst", "no_detected_catalyst",
)

THEMES = (
    "AI", "Quantum", "Crypto", "Defense", "Nuclear", "Energy", "Semiconductors",
    "EV", "Autonomous Driving", "Obesity Drug", "Cybersecurity", "Cloud", "Biotech",
    "Small Cap Momentum",
)

MAJOR_SECTORS = (
    "Technology", "Healthcare", "Financials", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials", "Real Estate",
    "Communication Services",
)

SYMBOL_THEME_HINTS = {
    "NVDA": ("AI", "Semiconductors"), "AMD": ("AI", "Semiconductors"), "AVGO": ("AI", "Semiconductors"),
    "SMCI": ("AI", "Semiconductors"), "MU": ("AI", "Semiconductors"), "ARM": ("AI", "Semiconductors"),
    "TSLA": ("EV", "Autonomous Driving"), "RIVN": ("EV",), "LCID": ("EV",),
    "PLTR": ("AI", "Defense"), "CRWD": ("Cybersecurity",), "PANW": ("Cybersecurity",),
    "COIN": ("Crypto",), "MSTR": ("Crypto",), "MARA": ("Crypto",), "RIOT": ("Crypto",),
    "LLY": ("Obesity Drug",), "NVO": ("Obesity Drug",), "AMGN": ("Biotech",), "NBIX": ("Biotech",),
    "OXY": ("Energy",), "XOM": ("Energy",), "CVX": ("Energy",),
    "SMR": ("Nuclear",), "OKLO": ("Nuclear",), "IONQ": ("Quantum",), "RGTI": ("Quantum",),
    "LMT": ("Defense",), "RTX": ("Defense",), "NOC": ("Defense",),
}

SYMBOL_SECTOR_HINTS = {
    "NVDA": "Technology", "AMD": "Technology", "AVGO": "Technology", "MSFT": "Technology", "AAPL": "Technology",
    "META": "Communication Services", "GOOGL": "Communication Services", "GOOG": "Communication Services", "NFLX": "Communication Services",
    "LLY": "Healthcare", "NVO": "Healthcare", "NBIX": "Healthcare", "AMGN": "Healthcare", "BIIB": "Healthcare",
    "JPM": "Financials", "BAC": "Financials", "GS": "Financials", "WFC": "Financials",
    "OXY": "Energy", "XOM": "Energy", "CVX": "Energy", "SLB": "Energy",
    "DAL": "Industrials", "LMT": "Industrials", "RTX": "Industrials", "BA": "Industrials",
    "TSLA": "Consumer Discretionary", "BROS": "Consumer Discretionary", "BJ": "Consumer Staples", "AMC": "Communication Services",
}

SYMBOL_INDUSTRY_HINTS = {
    "NVDA": "Semiconductors", "AMD": "Semiconductors", "AVGO": "Semiconductors", "MU": "Semiconductors",
    "NFLX": "Streaming Media", "META": "Internet Platforms", "GOOGL": "Internet Platforms",
    "OXY": "Oil & Gas Exploration", "XOM": "Integrated Oil", "CVX": "Integrated Oil",
    "DAL": "Airlines", "AMC": "Entertainment", "BROS": "Restaurants", "BJ": "Retail",
    "NBIX": "Biotechnology", "BIIB": "Biotechnology", "LLY": "Pharmaceuticals",
    "JPM": "Banks", "BAC": "Banks", "TSLA": "Automobiles",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        if isinstance(value, str):
            value = value.strip().replace("%", "")
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _text(value: Any, default: str = "") -> str:
    out = str(value if value is not None else default).strip()
    return out or str(default)


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


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    except Exception:
        return


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _profit_factor(values: list[float]) -> float | None:
    gains = sum(v for v in values if v > 0)
    losses = abs(sum(v for v in values if v < 0))
    if gains <= 0 and losses <= 0:
        return None
    if losses <= 0:
        return round(gains, 4)
    return round(gains / losses, 4)


def _symbol(row: dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("selected_symbol") or row.get("rejected_symbol"), "unknown").upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(row, "current_or_exit_profit_pct", "actual_return_pct", "selected_return_pct", "rejected_return_pct", "later_return_after_rejection", "return_pct", "current_return_pct")


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "later_mfe", "mfe_pct", "peak_gain_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct", "later_mae", "mae_pct")


def _giveback(row: dict[str, Any]) -> float:
    return _value(row, "profit_giveback_pct", "current_giveback_pct", "giveback_from_peak_pct", "average_profit_giveback_pct")


def _capture(row: dict[str, Any]) -> float:
    raw = _value(row, "profit_capture_ratio", "capture_ratio", "average_profit_capture_ratio", default=-1.0)
    if raw >= 0:
        return _clamp(raw / 100.0 if raw > 1.5 else raw, 0.0, 1.25)
    peak = _mfe(row)
    return _clamp(_return_pct(row) / peak, 0.0, 1.25) if peak > 0 else 0.0


def _hold(row: dict[str, Any]) -> float:
    return _value(row, "hold_duration_minutes", "actual_hold_duration_minutes", "average_hold_duration_minutes")


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("selected_horizon") or row.get("recommended_horizon"), "unknown").lower()
    if "scalp" in raw:
        return "scalp"
    if "day" in raw:
        return "day_trade"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw:
        return "swing"
    hold = _hold(row)
    if 0 < hold < 30:
        return "scalp"
    if 0 < hold < 390:
        return "day_trade"
    if 0 < hold < 1440:
        return "short_swing"
    return "unknown"


def _sector(row: dict[str, Any]) -> str:
    sym = _symbol(row)
    raw = _text(row.get("sector") or row.get("sector_context_label") or row.get("market_sector"), "")
    if raw and raw.lower() not in {"unknown", "none"}:
        return raw.replace("_", " ").title()
    return SYMBOL_SECTOR_HINTS.get(sym, "Unknown")


def _industry(row: dict[str, Any]) -> str:
    sym = _symbol(row)
    raw = _text(row.get("industry") or row.get("industry_group") or row.get("sub_industry"), "")
    if raw and raw.lower() not in {"unknown", "none"}:
        return raw.replace("_", " ").title()
    return SYMBOL_INDUSTRY_HINTS.get(sym, "Unknown")


def _canonical_catalyst(raw: Any) -> str:
    value = _text(raw, "unknown_catalyst").lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "earnings": "earnings_beat", "earnings_positive": "earnings_beat", "earnings_negative": "earnings_miss",
        "guidance": "guidance_raise", "guidance_positive": "guidance_raise", "guidance_negative": "guidance_cut",
        "fda": "FDA_or_regulatory", "regulatory": "FDA_or_regulatory", "interest_rates": "interest_rate_related",
        "rate_policy_related": "interest_rate_related", "rate_policy": "interest_rate_related",
        "commodity": "commodity_related", "retail_momentum": "retail_social_momentum", "social": "retail_social_momentum",
        "ai": "AI_theme", "ai_theme": "AI_theme", "quantum": "quantum_theme", "crypto": "crypto_theme",
        "defense": "defense_theme", "energy": "energy_theme", "nuclear": "nuclear_theme",
        "obesity_drug": "obesity_drug_theme", "semiconductor": "semiconductor_theme", "semiconductors": "semiconductor_theme",
        "none": "no_detected_catalyst", "no_catalyst": "no_detected_catalyst",
    }
    mapped = aliases.get(value, value)
    for item in CATALYST_TYPES:
        if str(mapped).lower() == item.lower():
            return item
    return "unknown_catalyst" if mapped != "no_detected_catalyst" else "no_detected_catalyst"


def _infer_catalysts(row: dict[str, Any]) -> tuple[list[str], float, float]:
    text = " ".join(
        _text(row.get(k)).lower()
        for k in (
            "catalyst_type", "catalyst", "primary_catalyst", "secondary_catalyst", "supporting_catalysts",
            "theme_context_label", "theme", "trade_archetype", "opportunity_type", "summary", "market_context_summary",
        )
        if row.get(k) not in (None, "")
    )
    found: list[str] = []
    explicit = row.get("primary_catalyst") or row.get("catalyst_type") or row.get("dominant_catalyst_type") or row.get("catalyst")
    if explicit:
        found.append(_canonical_catalyst(explicit))
    token_map = [
        ("earnings_beat", ("earnings beat", "beat", "eps beat", "revenue beat")),
        ("earnings_miss", ("earnings miss", "miss", "eps miss", "revenue miss")),
        ("guidance_raise", ("guidance raise", "raised guidance", "outlook raise")),
        ("guidance_cut", ("guidance cut", "cut guidance", "lowered guidance")),
        ("analyst_upgrade", ("upgrade", "raised target", "buy rating")),
        ("analyst_downgrade", ("downgrade", "lowered target", "sell rating")),
        ("FDA_or_regulatory", ("fda", "regulatory", "approval", "clinical", "trial")),
        ("contract_award", ("contract", "award", "deal", "partnership")),
        ("merger_acquisition", ("merger", "acquisition", "takeover", "buyout")),
        ("sector_sympathy", ("sympathy", "sector", "rotation")),
        ("retail_social_momentum", ("retail", "social", "meme", "reddit", "short squeeze")),
        ("macro_news", ("macro", "fed", "cpi", "inflation", "jobs")),
        ("commodity_related", ("oil", "commodity", "gold", "copper")),
        ("interest_rate_related", ("interest rate", "rates", "yields", "treasury")),
        ("government_policy", ("government", "policy", "tariff", "subsidy")),
        ("AI_theme", (" ai ", "artificial intelligence", "genai", "gpu")),
        ("quantum_theme", ("quantum",)),
        ("crypto_theme", ("crypto", "bitcoin", "ethereum")),
        ("defense_theme", ("defense", "military", "aerospace")),
        ("energy_theme", ("energy", "oil", "gas")),
        ("nuclear_theme", ("nuclear", "uranium")),
        ("obesity_drug_theme", ("obesity", "glp", "weight loss")),
        ("semiconductor_theme", ("semiconductor", "chip", "gpu")),
    ]
    padded = f" {text} "
    for label, tokens in token_map:
        if any(token in padded for token in tokens):
            found.append(label)
    for theme in SYMBOL_THEME_HINTS.get(_symbol(row), ()):
        if theme == "AI":
            found.append("AI_theme")
        elif theme == "Semiconductors":
            found.append("semiconductor_theme")
        elif theme == "Crypto":
            found.append("crypto_theme")
        elif theme == "Defense":
            found.append("defense_theme")
        elif theme == "Energy":
            found.append("energy_theme")
        elif theme == "Nuclear":
            found.append("nuclear_theme")
        elif theme == "Quantum":
            found.append("quantum_theme")
        elif theme == "Obesity Drug":
            found.append("obesity_drug_theme")
    dedup: list[str] = []
    for item in found:
        item = _canonical_catalyst(item)
        if item not in dedup:
            dedup.append(item)
    if not dedup:
        dedup = ["no_detected_catalyst" if _symbol(row) == "UNKNOWN" else "unknown_catalyst"]
    strength = _clamp(_value(row, "catalyst_strength_score", "catalyst_context_score", "momentum_score", "entry_timing_score", default=50.0) + max(0, len(dedup) - 1) * 5.0)
    confidence = _clamp(_value(row, "catalyst_confidence", "context_confidence", default=35.0) + (20.0 if dedup[0] not in {"unknown_catalyst", "no_detected_catalyst"} else 0.0) + max(0, len(dedup) - 1) * 4.0)
    return dedup, strength, confidence


def _themes(row: dict[str, Any], catalysts: list[str]) -> list[str]:
    sym = _symbol(row)
    found = list(SYMBOL_THEME_HINTS.get(sym, ()))
    text = " ".join(_text(row.get(k)).lower() for k in ("theme", "theme_context_label", "summary", "catalyst_type") if row.get(k) not in (None, ""))
    for theme in THEMES:
        if theme.lower() in text:
            found.append(theme)
    catalyst_theme = {
        "AI_theme": "AI", "quantum_theme": "Quantum", "crypto_theme": "Crypto", "defense_theme": "Defense",
        "energy_theme": "Energy", "nuclear_theme": "Nuclear", "obesity_drug_theme": "Obesity Drug",
        "semiconductor_theme": "Semiconductors", "retail_social_momentum": "Small Cap Momentum",
    }
    for catalyst in catalysts:
        if catalyst in catalyst_theme:
            found.append(catalyst_theme[catalyst])
    dedup: list[str] = []
    for theme in found:
        if theme in THEMES and theme not in dedup:
            dedup.append(theme)
    return dedup or ["Unknown"]


def _archetype(row: dict[str, Any]) -> str:
    raw = _text(row.get("trade_archetype") or row.get("archetype") or row.get("selected_opportunity_type"), "unknown")
    return raw if raw and raw != "unknown" else "unknown"


def _normalize_row(row: dict[str, Any], source: str) -> dict[str, Any] | None:
    sym = _symbol(row)
    if not sym or sym == "UNKNOWN":
        return None
    catalysts, strength, confidence = _infer_catalysts(row)
    themes = _themes(row, catalysts)
    return {
        "symbol": sym,
        "source": source,
        "primary_catalyst": catalysts[0],
        "secondary_catalyst": catalysts[1] if len(catalysts) > 1 else "none",
        "supporting_catalysts": catalysts[2:6],
        "catalyst_count": len([c for c in catalysts if c not in {"unknown_catalyst", "no_detected_catalyst"}]) or len(catalysts),
        "catalyst_confidence": confidence,
        "catalyst_strength_score": strength,
        "catalysts": catalysts,
        "themes": themes,
        "sector": _sector(row),
        "industry": _industry(row),
        "horizon": _horizon(row),
        "archetype": _archetype(row),
        "return_pct": _return_pct(row),
        "mfe": _mfe(row),
        "mae": _mae(row),
        "giveback": _giveback(row),
        "capture_ratio": _capture(row),
        "hold_duration": _hold(row),
        "continuation": _value(row, "continuation_strength_score", "follow_through_quality_score", "premarket_continuation_probability", "continuation_after_entry_pct"),
        "timestamp": _text(row.get("generated_at") or row.get("timestamp") or row.get("current_timestamp") or row.get("entry_timestamp"), ""),
    }


def _group_metrics(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = row.get(key)
        if isinstance(values, list):
            labels = values
        else:
            labels = [row.get(key)]
        for label in labels:
            label_text = _text(label, "unknown")
            if label_text:
                grouped[label_text].append(row)
    out: dict[str, dict[str, Any]] = {}
    for label, items in grouped.items():
        returns = [_to_float(r.get("return_pct")) for r in items]
        out[label] = {
            "trade_count": len(items),
            "win_rate": round(sum(1 for v in returns if v > 0) / max(1, len(returns)) * 100.0, 4),
            "avg_return": _avg(returns),
            "profit_factor": _profit_factor(returns),
            "avg_mfe": _avg([_to_float(r.get("mfe")) for r in items]),
            "avg_mae": _avg([_to_float(r.get("mae")) for r in items]),
            "avg_giveback": _avg([_to_float(r.get("giveback")) for r in items]),
            "avg_capture_ratio": _avg([_to_float(r.get("capture_ratio")) for r in items]),
            "avg_hold_duration": _avg([_to_float(r.get("hold_duration")) for r in items]),
            "avg_continuation": _avg([_to_float(r.get("continuation")) for r in items]),
            "strength": _avg([_to_float(r.get("catalyst_strength_score")) for r in items]),
            "confidence": _avg([_to_float(r.get("catalyst_confidence")) for r in items]),
        }
    return out


def _best_metric(metrics: dict[str, dict[str, Any]], metric: str, *, reverse: bool = True, exclude_unknown: bool = True) -> str:
    items = []
    for label, payload in metrics.items():
        if exclude_unknown and label in {"unknown", "Unknown", "unknown_catalyst", "no_detected_catalyst", "none"}:
            continue
        if payload.get(metric) is not None and _to_int(payload.get("trade_count"), 0) > 0:
            items.append((label, _to_float(payload.get(metric))))
    if not items:
        return "insufficient_data"
    return sorted(items, key=lambda item: item[1], reverse=reverse)[0][0]


class CatalystThemeNarrativeCapitalFlowIntelligenceV2:
    """Shadow-only catalyst, theme, narrative, rotation, capital-flow, and leadership diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.state_path = os.path.join(self.state_dir, "catalyst_theme_narrative_capital_flow_intelligence_v2.jsonl")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _rows(self, name: str, limit: int = MAX_ROWS) -> list[dict[str, Any]]:
        return _tail_jsonl(os.path.join(self.state_dir, name), max_rows=limit)

    def _collect_rows(self) -> list[dict[str, Any]]:
        sources = {
            "market_context": self._rows("market_context_learning_suite_v1.jsonl", 720),
            "context_evidence": self._rows("context_evidence_expansion_suite_v1.jsonl", 420),
            "lifecycle": self._rows("trade_lifecycle_excursion_v2.jsonl", 720) + self._rows("trade_lifecycle_excursion_v1.jsonl", 320),
            "profit_capture": self._rows("adaptive_profit_capture_intelligence_v1.jsonl", 520),
            "archetype_regime": self._rows("trade_archetype_regime_intelligence_v1.jsonl", 420),
            "opportunity_cost": self._rows("opportunity_cost_learning_v1.jsonl", 520),
            "candidate": self._rows("candidate_decision_ledger_v1.jsonl", 420),
        }
        normalized: list[dict[str, Any]] = []
        for source, rows in sources.items():
            for row in rows:
                item = _normalize_row(row, source)
                if item:
                    normalized.append(item)
        return normalized[-MAX_ROWS:]

    def _strength_buckets(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        buckets = {"80_to_100": [], "60_to_79": [], "40_to_59": [], "below_40": []}
        for row in rows:
            strength = _to_float(row.get("catalyst_strength_score"))
            if strength >= 80:
                buckets["80_to_100"].append(row)
            elif strength >= 60:
                buckets["60_to_79"].append(row)
            elif strength >= 40:
                buckets["40_to_59"].append(row)
            else:
                buckets["below_40"].append(row)
        out: dict[str, dict[str, Any]] = {}
        for bucket, items in buckets.items():
            metrics = _group_metrics(items, "primary_catalyst")
            best = _best_metric(metrics, "avg_return", exclude_unknown=False)
            out[bucket] = metrics.get(best, {
                "trade_count": len(items),
                "win_rate": None,
                "avg_return": _avg([_to_float(r.get("return_pct")) for r in items]),
                "avg_continuation": _avg([_to_float(r.get("continuation")) for r in items]),
                "avg_giveback": _avg([_to_float(r.get("giveback")) for r in items]),
                "avg_hold_duration": _avg([_to_float(r.get("hold_duration")) for r in items]),
            })
        return out

    def _horizon_matrix(self, rows: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], float]:
        grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in rows:
            grouped[_text(row.get("primary_catalyst"), "unknown")][_text(row.get("horizon"), "unknown")].append(_to_float(row.get("return_pct")))
        best: dict[str, str] = {}
        worst: dict[str, str] = {}
        evidence = 0
        for catalyst, horizons in grouped.items():
            scored = [(h, mean(vals)) for h, vals in horizons.items() if vals and h != "unknown"]
            evidence += sum(len(vals) for vals in horizons.values())
            if scored:
                best[catalyst] = sorted(scored, key=lambda item: item[1], reverse=True)[0][0]
                worst[catalyst] = sorted(scored, key=lambda item: item[1])[0][0]
        confidence = _clamp(20.0 + min(70.0, evidence * 0.05))
        return best, worst, _round(confidence, 2)

    def _pair_scores(self, rows: list[dict[str, Any]]) -> tuple[str, str, dict[str, float]]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            catalyst = _text(row.get("primary_catalyst"), "unknown")
            arch = _text(row.get("archetype"), "unknown")
            if catalyst in {"unknown_catalyst", "no_detected_catalyst"} or arch == "unknown":
                continue
            grouped[f"{catalyst}+{arch}"].append(_to_float(row.get("return_pct")))
        scores = {k: round(mean(v), 4) for k, v in grouped.items() if v}
        if not scores:
            return "insufficient_data", "insufficient_data", {}
        return max(scores.items(), key=lambda item: item[1])[0], min(scores.items(), key=lambda item: item[1])[0], scores

    def _decay(self, metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        decay_curve: dict[str, dict[str, float]] = {}
        half_life: dict[str, str] = {}
        for catalyst, payload in metrics.items():
            cont = _to_float(payload.get("avg_continuation"), 0.0)
            giveback = _to_float(payload.get("avg_giveback"), 0.0)
            hold = _to_float(payload.get("avg_hold_duration"), 0.0)
            start = _clamp(50.0 + cont * 0.35 - giveback * 0.2)
            curve = {
                "1h": _round(start, 2),
                "4h": _round(start * 0.88, 2),
                "1d": _round(start * 0.72, 2),
                "3d": _round(start * 0.55, 2),
                "5d": _round(start * 0.42, 2),
                "10d": _round(start * 0.25, 2),
            }
            decay_curve[catalyst] = curve
            half_life[catalyst] = "10d" if hold >= 1440 else "3d" if hold >= 390 else "1d" if hold >= 60 else "4h"
        longest = max(half_life.items(), key=lambda item: {"4h": 1, "1d": 2, "3d": 3, "10d": 4}.get(item[1], 0), default=("insufficient_data", ""))[0]
        fastest = min(half_life.items(), key=lambda item: {"4h": 1, "1d": 2, "3d": 3, "10d": 4}.get(item[1], 9), default=("insufficient_data", ""))[0]
        score = _clamp(min(100.0, len(metrics) * 7.0))
        return {"catalyst_half_life": half_life, "catalyst_decay_curve": decay_curve, "longest_lasting_catalyst": longest, "fastest_decay_catalyst": fastest, "catalyst_decay_learning_score": _round(score, 2), "decay_confidence": _round(score * 0.85, 2)}

    def _narrative_and_flow(self, rows: list[dict[str, Any]], sector_metrics: dict[str, dict[str, Any]], theme_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
        flow_scores: dict[str, float] = defaultdict(float)
        chain_scores: dict[str, float] = defaultdict(float)
        leaders: Counter[str] = Counter()
        for row in rows:
            sym = _text(row.get("symbol"), "unknown")
            sector = _text(row.get("sector"), "Unknown")
            industry = _text(row.get("industry"), "Unknown")
            themes = row.get("themes") if isinstance(row.get("themes"), list) else ["Unknown"]
            ret = _to_float(row.get("return_pct"))
            mfe = _to_float(row.get("mfe"))
            score = ret + mfe * 0.35 + _to_float(row.get("catalyst_strength_score")) * 0.04
            for theme in themes:
                flow_scores[f"{sector} -> {industry} -> {theme} -> {sym}"] += score
                chain_scores[f"{row.get('primary_catalyst')} -> {sector} -> {theme} -> {sym}"] += score
            leaders[sym] += max(0, int(round(score)))
        strongest_flow = max(flow_scores.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        weakest_flow = min(flow_scores.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        strongest_chain = max(chain_scores.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        longest_chain = max(chain_scores.keys(), key=lambda item: len(item.split(" -> ")), default="insufficient_data")
        market_leader = leaders.most_common(1)[0][0] if leaders else "insufficient_data"
        strongest_sector = _best_metric(sector_metrics, "avg_return", exclude_unknown=True)
        strongest_theme = _best_metric(theme_metrics, "avg_return", exclude_unknown=True)
        confidence = _clamp(25.0 + min(60.0, len(flow_scores) * 0.8))
        return {
            "strongest_capital_flow": strongest_flow,
            "weakest_capital_flow": weakest_flow,
            "capital_flow_confidence": _round(confidence, 2),
            "institutional_rotation_signal": "possible_rotation_detected" if confidence >= 50 else "insufficient_rotation_evidence",
            "strongest_narrative_chain": strongest_chain,
            "longest_narrative_chain": longest_chain,
            "narrative_chain": strongest_chain,
            "chain_strength": _round(chain_scores.get(strongest_chain, 0.0), 4),
            "chain_duration": "shadow_estimated_from_cached_lifecycle_hold_times",
            "chain_follow_through": _round(_to_float((theme_metrics.get(strongest_theme) or {}).get("avg_continuation")), 2),
            "narrative_learning_score": _round(confidence, 2),
            "market_leader": market_leader,
            "sector_leaders": [label for label, _ in Counter(_text(r.get("sector"), "Unknown") for r in rows).most_common(5)],
            "industry_leaders": [label for label, _ in Counter(_text(r.get("industry"), "Unknown") for r in rows).most_common(5)],
            "theme_leaders": [label for label, _ in Counter(theme for r in rows for theme in (r.get("themes") or [])).most_common(5)],
            "symbol_leaders": [label for label, _ in leaders.most_common(8)],
            "strongest_leadership_group": strongest_theme if strongest_theme != "insufficient_data" else strongest_sector,
            "leadership_strength_score": _round(confidence, 2),
        }

    def _build(self, statuses: dict[str, dict[str, Any]]) -> dict[str, Any]:
        started = time.perf_counter()
        rows = self._collect_rows()
        catalyst_metrics = _group_metrics(rows, "primary_catalyst")
        theme_metrics = _group_metrics(rows, "themes")
        sector_metrics = _group_metrics(rows, "sector")
        industry_metrics = _group_metrics(rows, "industry")
        catalyst_counts = Counter(_text(r.get("primary_catalyst"), "unknown_catalyst") for r in rows)
        known_count = sum(v for k, v in catalyst_counts.items() if k not in {"unknown_catalyst", "no_detected_catalyst"})
        total_catalysts = sum(catalyst_counts.values())
        unknown_rate = round((total_catalysts - known_count) / max(1, total_catalysts) * 100.0, 4) if total_catalysts else 100.0
        coverage = _clamp(known_count / max(1, total_catalysts) * 100.0 if total_catalysts else 0.0)
        strengths = [_to_float(r.get("catalyst_strength_score")) for r in rows]
        confidences = [_to_float(r.get("catalyst_confidence")) for r in rows]
        dominant = catalyst_counts.most_common(1)[0][0] if catalyst_counts else "insufficient_data"
        secondary = catalyst_counts.most_common(2)[1][0] if len(catalyst_counts) > 1 else "none"
        best_horizon, worst_horizon, horizon_conf = self._horizon_matrix(rows)
        best_pair, weak_pair, pair_scores = self._pair_scores(rows)
        decay = self._decay(catalyst_metrics)
        flow = self._narrative_and_flow(rows, sector_metrics, theme_metrics)
        dominant_theme = Counter(theme for row in rows for theme in (row.get("themes") or [])).most_common(1)
        strongest_theme = _best_metric(theme_metrics, "avg_return", exclude_unknown=True)
        weakest_theme = _best_metric(theme_metrics, "avg_return", reverse=False, exclude_unknown=True)
        strongest_sector = _best_metric(sector_metrics, "avg_return", exclude_unknown=True)
        weakest_sector = _best_metric(sector_metrics, "avg_return", reverse=False, exclude_unknown=True)
        strongest_industry = _best_metric(industry_metrics, "avg_return", exclude_unknown=True)
        weakest_industry = _best_metric(industry_metrics, "avg_return", reverse=False, exclude_unknown=True)
        top_gap_scores = {
            "unknown_catalyst_reduction": unknown_rate,
            "catalyst_decay_evidence": 100.0 - _to_float(decay.get("catalyst_decay_learning_score"), 0.0),
            "theme_rotation_coverage": 100.0 - min(100.0, len(theme_metrics) * 8.0),
            "capital_flow_confidence": 100.0 - _to_float(flow.get("capital_flow_confidence"), 0.0),
        }
        top_gap = max(top_gap_scores.items(), key=lambda item: item[1], default=("insufficient_data", 0.0))[0]
        agreement = _clamp((_avg(confidences) or 0.0) * 0.7 + coverage * 0.3)
        truth_score = _clamp((_avg([abs(_to_float(r.get("return_pct"))) for r in rows]) or 0.0) * 3.0 + (_avg(confidences) or 0.0) * 0.45 + coverage * 0.25)
        prediction_accuracy = _clamp(sum(1 for r in rows if (_to_float(r.get("catalyst_strength_score")) >= 55 and _to_float(r.get("return_pct")) > 0) or (_to_float(r.get("catalyst_strength_score")) < 55 and _to_float(r.get("return_pct")) <= 0)) / max(1, len(rows)) * 100.0)
        most_reliable = _best_metric(catalyst_metrics, "profit_factor", exclude_unknown=True)
        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_catalyst_theme_narrative_capital_flow_intelligence",
            "generated_at": _now_iso(),
            "evidence_count": len(rows),
            "catalyst_records": total_catalysts,
            "dominant_catalyst": dominant,
            "secondary_catalyst": secondary,
            "primary_catalyst": dominant,
            "supporting_catalysts": [label for label, _ in catalyst_counts.most_common(8)][2:],
            "catalyst_count": len(catalyst_counts),
            "catalyst_confidence": _round(_avg(confidences) or 0.0, 2),
            "catalyst_agreement_score": _round(agreement, 2),
            "multi_catalyst_score": _round(_clamp(len(catalyst_counts) * 8.0 + agreement * 0.45), 2),
            "catalyst_coverage_score": _round(coverage, 2),
            "unknown_catalyst_rate": unknown_rate,
            "catalyst_strength_score": _round(_avg(strengths) or 0.0, 2),
            "average_strength_score": _round(_avg(strengths) or 0.0, 2),
            "avg_return_by_strength": self._strength_buckets(rows),
            "win_rate_by_strength": {k: v.get("win_rate") for k, v in self._strength_buckets(rows).items()},
            "continuation_by_strength": {k: v.get("avg_continuation") for k, v in self._strength_buckets(rows).items()},
            "giveback_by_strength": {k: v.get("avg_giveback") for k, v in self._strength_buckets(rows).items()},
            "hold_duration_by_strength": {k: v.get("avg_hold_duration") for k, v in self._strength_buckets(rows).items()},
            "strongest_catalyst_type": _best_metric(catalyst_metrics, "avg_return", exclude_unknown=True),
            "weakest_catalyst_type": _best_metric(catalyst_metrics, "avg_return", reverse=False, exclude_unknown=True),
            "catalyst_strength_reliability": _round(_clamp((_avg(strengths) or 0.0) * 0.5 + coverage * 0.5), 2),
            "catalyst_reliability": catalyst_metrics,
            "highest_winrate_catalyst": _best_metric(catalyst_metrics, "win_rate", exclude_unknown=True),
            "highest_return_catalyst": _best_metric(catalyst_metrics, "avg_return", exclude_unknown=True),
            "highest_giveback_catalyst": _best_metric(catalyst_metrics, "avg_giveback", exclude_unknown=False),
            "most_reliable_catalyst": most_reliable,
            "best_horizon_by_catalyst": best_horizon,
            "worst_horizon_by_catalyst": worst_horizon,
            "catalyst_horizon_confidence": horizon_conf,
            "best_catalyst_archetype_pair": best_pair,
            "weakest_catalyst_archetype_pair": weak_pair,
            "archetype_catalyst_score": pair_scores,
            "dominant_theme": dominant_theme[0][0] if dominant_theme else "insufficient_data",
            "strongest_theme": strongest_theme,
            "weakest_theme": weakest_theme,
            "theme_metrics": theme_metrics,
            "theme_persistence_score": _round(_clamp(len(theme_metrics) * 7.0 + (_avg([_to_float(v.get("avg_continuation")) for v in theme_metrics.values()]) or 0.0) * 0.25), 2),
            "theme_confidence": _round(_clamp(len(theme_metrics) * 6.0 + coverage * 0.35), 2),
            "theme_relative_strength": {k: v.get("avg_return") for k, v in theme_metrics.items()},
            "theme_relative_momentum": {k: v.get("avg_mfe") for k, v in theme_metrics.items()},
            "theme_rotation_score": _round(_clamp(len(theme_metrics) * 8.0), 2),
            "theme_persistence": {k: v.get("avg_continuation") for k, v in theme_metrics.items()},
            "emerging_theme": strongest_theme,
            "weakening_theme": weakest_theme,
            "fading_theme": _best_metric(theme_metrics, "avg_giveback", exclude_unknown=True),
            "dominant_sector": Counter(_text(r.get("sector"), "Unknown") for r in rows).most_common(1)[0][0] if rows else "insufficient_data",
            "current_leading_sector": strongest_sector,
            "strongest_sector": strongest_sector,
            "weakest_sector": weakest_sector,
            "improving_sector": _best_metric(sector_metrics, "avg_mfe", exclude_unknown=True),
            "weakening_sector": _best_metric(sector_metrics, "avg_giveback", exclude_unknown=True),
            "sector_relative_strength": {k: v.get("avg_return") for k, v in sector_metrics.items()},
            "sector_relative_momentum": {k: v.get("avg_mfe") for k, v in sector_metrics.items()},
            "sector_rotation_velocity": _round(_clamp(len(sector_metrics) * 6.0), 2),
            "sector_rotation_confidence": _round(_clamp(len(sector_metrics) * 8.0), 2),
            "sector_rotation_score": _round(_clamp(len(sector_metrics) * 8.0 + (_avg([_to_float(v.get("avg_return")) for v in sector_metrics.values()]) or 0.0)), 2),
            "dominant_industry": Counter(_text(r.get("industry"), "Unknown") for r in rows).most_common(1)[0][0] if rows else "insufficient_data",
            "leading_industry": strongest_industry,
            "strongest_industry": strongest_industry,
            "weakest_industry": weakest_industry,
            "improving_industry": _best_metric(industry_metrics, "avg_mfe", exclude_unknown=True),
            "weakening_industry": _best_metric(industry_metrics, "avg_giveback", exclude_unknown=True),
            "industry_rotation_strength": _round(_clamp(len(industry_metrics) * 5.0), 2),
            "industry_rotation_score": _round(_clamp(len(industry_metrics) * 6.0), 2),
            **decay,
            **flow,
            "catalyst_truth_score": _round(truth_score, 2),
            "catalyst_prediction_accuracy": _round(prediction_accuracy, 2),
            "catalyst_confidence_truth": _round(_clamp((truth_score + prediction_accuracy) / 2.0), 2),
            "top_learning_gap": top_gap,
            "learning_gap_scores": {k: _round(v, 2) for k, v in top_gap_scores.items()},
            "shadow_recommendation": f"shadow_only_focus_on_{top_gap}",
            "summary": "Astra is learning catalyst, theme, narrative, sector, industry, capital-flow, and leadership context without changing trading behavior.",
            "behavior_safe_to_apply": False,
            "auto_apply_allowed": False,
            "human_review_required": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "cache_hit": False,
            "build_ms": _round((time.perf_counter() - started) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "ranking_behavior_changed": False,
            "paper_execution_behavior_changed": False,
            "position_sizing_changed": False,
            "thresholds_changed": False,
            "paper_only_preserved": True,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "partial_sells_enabled": False,
            "automatic_trailing_stops_enabled": False,
        }
        return out

    def status(self, *, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        if self._cache and not force and (time.time() - self._cache_ts) < self.ttl_seconds:
            cached = dict(self._cache)
            cached["cache_hit"] = True
            return cached
        try:
            out = self._build(dict(statuses or {}))
            if time.time() - self._last_write >= 300.0:
                _append_jsonl(self.state_path, {k: out.get(k) for k in ("generated_at", "evidence_count", "dominant_catalyst", "strongest_theme", "strongest_sector", "strongest_capital_flow", "top_learning_gap", "behavior_safe_to_apply")})
                self._last_write = time.time()
            self._cache = dict(out)
            self._cache_ts = time.time()
            return out
        except Exception as exc:
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_catalyst_theme_narrative_capital_flow_intelligence",
                "evidence_count": 0,
                "catalyst_records": 0,
                "dominant_catalyst": "insufficient_data",
                "strongest_catalyst_type": "insufficient_data",
                "weakest_catalyst_type": "insufficient_data",
                "catalyst_coverage_score": 0.0,
                "unknown_catalyst_rate": 100.0,
                "catalyst_truth_score": 0.0,
                "catalyst_prediction_accuracy": 0.0,
                "strongest_theme": "insufficient_data",
                "weakest_theme": "insufficient_data",
                "dominant_theme": "insufficient_data",
                "strongest_sector": "insufficient_data",
                "weakest_sector": "insufficient_data",
                "dominant_industry": "insufficient_data",
                "strongest_capital_flow": "insufficient_data",
                "market_leader": "insufficient_data",
                "strongest_narrative_chain": "insufficient_data",
                "catalyst_decay_learning_score": 0.0,
                "best_horizon_by_catalyst": {},
                "most_reliable_catalyst": "insufficient_data",
                "top_learning_gap": "unavailable",
                "shadow_recommendation": "unavailable",
                "degraded_reason": f"catalyst_theme_narrative_capital_flow_v2_unavailable:{str(exc)[:140]}",
                "behavior_safe_to_apply": False,
                "api_calls_used": 0,
                "build_ms": 0.0,
                "live_trading_changed": False,
                "broker_behavior_changed": False,
                "ranking_behavior_changed": False,
                "paper_execution_behavior_changed": False,
                "position_sizing_changed": False,
                "thresholds_changed": False,
                "paper_only_preserved": True,
                "alpaca_paper_only_preserved": True,
                "natural_exit_preserved": True,
                "forced_trades_enabled": False,
                "forced_exits_enabled": False,
            }
