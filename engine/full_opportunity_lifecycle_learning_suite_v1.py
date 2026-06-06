from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

VERSION = "1.0.0"
CACHE_TTL_SECONDS = 18.0
MAX_TAIL_BYTES = 2_200_000
MAX_RAW_ROWS_SCANNED = 1800
MAX_HOT_LOOKBACK_DAYS = 7
MAX_FILE_SIZE_BEFORE_ROTATION = 8_000_000
DASHBOARD_CACHE_MAX_AGE_SECONDS = 120.0

SOURCE_FILES = (
    ("lifecycle_v2", "trade_lifecycle_excursion_v2.jsonl", 650),
    ("lifecycle_v1", "trade_lifecycle_excursion_v1.jsonl", 350),
    ("opportunity_cost", "opportunity_cost_learning_v1.jsonl", 700),
    ("execution_audit", "execution_suppression_audit_v1.jsonl", 700),
    ("candidate_ledger", "candidate_decision_ledger_v1.jsonl", 700),
    ("profit_capture", "adaptive_profit_capture_intelligence_v1.jsonl", 450),
    ("context_evidence", "context_evidence_expansion_suite_v1.jsonl", 350),
    ("catalyst_theme_v2", "catalyst_theme_narrative_capital_flow_intelligence_v2.jsonl", 350),
    ("decision_optimization", "decision_optimization_trade_management_suite_v1.jsonl", 250),
    ("confidence_attribution", "confidence_calibration_performance_attribution_v1.jsonl", 250),
)

LEARNING_SYSTEMS = (
    "confidence_calibration",
    "catalyst_theme_narrative",
    "market_context",
    "replay",
    "opportunity_cost",
    "decision_optimization",
    "exit_learning",
    "portfolio_risk",
    "regime_archetype",
    "profit_capture",
)

INDEX_FIELDS = (
    "opportunity_id",
    "symbol",
    "date",
    "decision_type",
    "horizon",
    "catalyst",
    "theme",
    "sector",
    "outcome_label",
    "confidence_bucket",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


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


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _tail_jsonl(path: str, max_rows: int = MAX_RAW_ROWS_SCANNED, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
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


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            parsed = json.load(handle)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        return


def _append_jsonl(path: str, row: dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    except Exception:
        return


def _symbol(row: dict[str, Any]) -> str:
    return _text(
        row.get("symbol") or row.get("ticker") or row.get("asset_symbol") or row.get("selected_symbol") or row.get("rejected_symbol"),
        "unknown",
    ).upper()


def _value(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if row.get(key) not in (None, ""):
            return _to_float(row.get(key), default)
    return float(default)


def _return_pct(row: dict[str, Any]) -> float:
    return _value(
        row,
        "current_or_exit_profit_pct",
        "actual_return_pct",
        "realized_return_pct",
        "current_return_pct",
        "exit_gain_pct",
        "return_pct",
        "selected_return_pct",
        "rejected_return_pct",
        "later_return_after_rejection",
        "opportunity_cost_pct",
        default=0.0,
    )


def _mfe(row: dict[str, Any]) -> float:
    return _value(row, "max_favorable_excursion_pct", "peak_unrealized_profit_pct", "peak_gain_pct", "later_mfe", "mfe_pct")


def _mae(row: dict[str, Any]) -> float:
    return _value(row, "max_adverse_excursion_pct", "worst_unrealized_drawdown_pct", "later_mae", "mae_pct")


def _confidence(row: dict[str, Any]) -> float | None:
    for key in ("confidence", "confidence_score", "entry_confidence", "conviction_score", "opportunity_confidence", "selection_confidence", "confidence_pct"):
        if row.get(key) not in (None, ""):
            val = _to_float(row.get(key))
            if 0 < val <= 1.5:
                val *= 100.0
            return _clamp(val)
    return None


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unknown_confidence"
    val = _clamp(value)
    if val >= 95:
        return "95_to_100"
    if val >= 90:
        return "90_to_94"
    if val >= 85:
        return "85_to_89"
    if val >= 80:
        return "80_to_84"
    if val >= 70:
        return "70_to_79"
    return "below_70"


def _horizon(row: dict[str, Any]) -> str:
    raw = _text(row.get("horizon_style") or row.get("horizon") or row.get("selected_horizon") or row.get("recommended_horizon") or row.get("hold_duration_bucket"), "unknown").lower()
    hold = _value(row, "hold_duration_minutes", "actual_hold_duration_minutes", "hold_time_minutes")
    if "scalp" in raw or (0 < hold < 30):
        return "scalp"
    if "short" in raw and "swing" in raw:
        return "short_swing"
    if "swing" in raw or hold >= 1440:
        return "swing"
    if "day" in raw or (0 < hold < 390):
        return "day_trade"
    return "unknown"


def _decision_type(row: dict[str, Any], source: str) -> str:
    raw = _text(row.get("decision_type") or row.get("final_execution_decision") or row.get("decision") or row.get("rejection_stage") or row.get("status"), "").lower()
    if source.startswith("lifecycle") or row.get("entry_price") or row.get("broker_submission_attempted") is True:
        return "entered"
    if source == "opportunity_cost" or row.get("rejected_symbol"):
        return "rejected"
    if "duplicate" in raw:
        return "duplicate"
    if "cancel" in raw:
        return "canceled"
    if "block" in raw:
        return "blocked"
    if "skip" in raw:
        return "skipped"
    if "ignore" in raw:
        return "ignored"
    if "virtual" in raw:
        return "virtual_only"
    if "reject" in raw:
        return "rejected"
    if source in {"execution_audit", "candidate_ledger"}:
        return "blocked" if row.get("suppression_reason") or row.get("rejection_reason") else "skipped"
    return "virtual_only"


def _outcome_label(ret: float, missed: bool, avoided: bool) -> str:
    if missed:
        return "missed_winner"
    if avoided:
        return "avoided_loser"
    if ret >= 3:
        return "winner"
    if ret <= -2:
        return "loser"
    return "neutral"


def _date_from_row(row: dict[str, Any]) -> str:
    raw = _text(row.get("timestamp") or row.get("generated_at") or row.get("current_timestamp") or row.get("entry_timestamp") or row.get("timestamp_seen"), "")
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        return raw[:10]
    return _now().date().isoformat()


def _stable_id(row: dict[str, Any], source: str, symbol: str, decision: str) -> str:
    existing = _text(row.get("opportunity_id") or row.get("lifecycle_id") or row.get("order_id") or row.get("audit_id"), "")
    if existing:
        return existing
    seed = "|".join([
        source,
        symbol,
        decision,
        _text(row.get("timestamp") or row.get("generated_at") or row.get("entry_timestamp") or row.get("current_timestamp"), ""),
        _text(row.get("rejection_reason") or row.get("decision_reason") or row.get("selected_symbol") or row.get("rejected_symbol"), ""),
    ])
    return hashlib.sha1(seed.encode("utf-8", "ignore")).hexdigest()[:18]


def _freshness_label(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "stale"
    if age_seconds <= 120:
        return "live"
    if age_seconds <= 900:
        return "fresh"
    if age_seconds <= 3600:
        return "warm"
    return "stale"


def _top(counter: Counter[str], default: str = "insufficient_data") -> str:
    return counter.most_common(1)[0][0] if counter else default


class FullOpportunityLifecycleLearningSuiteV1:
    """Shadow-only opportunity lifecycle, learning graph, and memory diagnostics."""

    def __init__(self, state_dir: str = "state", ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self.state_dir = str(state_dir or "state")
        self.ttl_seconds = float(ttl_seconds or CACHE_TTL_SECONDS)
        self.hot_dir = os.path.join(self.state_dir, "opportunities", "raw")
        self.warm_dir = os.path.join(self.state_dir, "opportunities", "summaries")
        self.archive_dir = os.path.join(self.state_dir, "opportunities", "archive")
        self.graph_latest = os.path.join(self.state_dir, "learning_graph", "latest_summary.json")
        self.graph_daily_dir = os.path.join(self.state_dir, "learning_graph", "daily")
        self.dashboard_cache_path = os.path.join(self.state_dir, "dashboard_cache", "full_opportunity_lifecycle_summary.json")
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0

    def _source_rows(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        remaining = MAX_RAW_ROWS_SCANNED
        for source, filename, limit in SOURCE_FILES:
            if remaining <= 0:
                break
            rows = _tail_jsonl(os.path.join(self.state_dir, filename), max_rows=min(limit, remaining))
            for row in rows:
                out.append((source, row))
            remaining -= len(rows)
        return out[-MAX_RAW_ROWS_SCANNED:]

    def _opportunity_from_row(self, source: str, row: dict[str, Any]) -> dict[str, Any] | None:
        sym = _symbol(row)
        if not sym or sym == "UNKNOWN":
            return None
        decision = _decision_type(row, source)
        ret = _return_pct(row)
        selected_ret = _value(row, "selected_return_pct", default=ret)
        rejected_ret = _value(row, "rejected_return_pct", "later_return_after_rejection", default=ret)
        missed = bool(row.get("missed_better_candidate_flag") or row.get("missed_winner_flag")) or (decision in {"rejected", "skipped", "ignored", "blocked"} and rejected_ret > max(1.5, selected_ret + 0.5))
        avoided = bool(row.get("correct_selection_flag") or row.get("avoided_loser_flag")) or (decision in {"rejected", "skipped", "ignored", "blocked"} and rejected_ret <= 0)
        confidence = _confidence(row)
        date = _date_from_row(row)
        outcome = _outcome_label(ret if decision == "entered" else rejected_ret, missed, avoided)
        horizon = _horizon(row)
        catalyst = _text(row.get("primary_catalyst") or row.get("catalyst_type") or row.get("dominant_catalyst") or row.get("dominant_catalyst_type"), "unknown_catalyst")
        theme = _text(row.get("theme") or row.get("theme_context_label") or row.get("dominant_theme"), "unknown_theme")
        sector = _text(row.get("sector") or row.get("sector_context_label") or row.get("market_sector"), "unknown_sector")
        opp = {
            "opportunity_id": _stable_id(row, source, sym, decision),
            "symbol": sym,
            "date": date,
            "timestamp_seen": _text(row.get("timestamp") or row.get("generated_at") or row.get("current_timestamp") or row.get("entry_timestamp"), _now_iso()),
            "source": source,
            "rank": _to_int(row.get("rank") or row.get("candidate_rank"), 0),
            "confidence": confidence,
            "confidence_bucket": _confidence_bucket(confidence),
            "grade": _text(row.get("grade") or row.get("letter_grade") or row.get("quality_grade"), "unknown"),
            "horizon": horizon,
            "archetype": _text(row.get("trade_archetype") or row.get("archetype") or row.get("setup_type") or row.get("opportunity_type"), "unknown"),
            "regime": _text(row.get("market_regime") or row.get("regime") or row.get("session_type"), "unknown"),
            "catalyst": catalyst,
            "theme": theme,
            "sector": sector,
            "market_context": _text(row.get("market_context_summary") or row.get("market_structure_label") or row.get("session_type"), "unknown"),
            "decision_type": decision,
            "decision_reason": _text(row.get("decision_reason") or row.get("rejection_reason") or row.get("suppression_reason") or row.get("final_blocker_reason"), "none"),
            "outcome_15m": _round(row.get("outcome_15m") or ret),
            "outcome_30m": _round(row.get("outcome_30m") or ret),
            "outcome_1h": _round(row.get("outcome_1h") or ret),
            "outcome_4h": _round(row.get("outcome_4h") or ret),
            "outcome_1d": _round(row.get("outcome_1d") or ret),
            "outcome_3d": _round(row.get("outcome_3d") or ret),
            "outcome_5d": _round(row.get("outcome_5d") or ret),
            "mfe": _round(_mfe(row)),
            "mae": _round(_mae(row)),
            "actual_return": _round(ret),
            "virtual_return": _round(row.get("counterfactual_return_pct") or row.get("best_counterfactual_return") or row.get("virtual_return_pct") or ret),
            "missed_winner_flag": missed,
            "avoided_loser_flag": avoided,
            "outcome_label": outcome,
            "lesson_generated": bool(row.get("lesson_generated") or missed or avoided or abs(ret) >= 2.0),
        }
        return opp

    def _dedup_opportunities(self, rows: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for source, row in rows:
            opp = self._opportunity_from_row(source, row)
            if not opp:
                continue
            latest[opp["opportunity_id"]] = opp
        return list(latest.values())[-MAX_RAW_ROWS_SCANNED:]

    def _storage_paths_for_date(self, date: str) -> tuple[str, str, str]:
        raw = os.path.join(self.hot_dir, f"{date}.jsonl")
        summary = os.path.join(self.warm_dir, f"{date}.summary.json")
        weekly = os.path.join(self.warm_dir, f"{date[:4]}-W{datetime.fromisoformat(date).isocalendar().week:02d}.weekly.summary.json")
        return raw, summary, weekly

    def _write_tiered_storage(self, opportunities: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
        today = _now().date().isoformat()
        by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for opp in opportunities:
            by_date[_text(opp.get("date"), today)].append(opp)
        raw_event_count = 0
        for date, items in by_date.items():
            raw_path, daily_path, weekly_path = self._storage_paths_for_date(date)
            # Hot tier stores compact raw event snapshots for recent evidence only.
            for item in items[-MAX_RAW_ROWS_SCANNED:]:
                _append_jsonl(raw_path, {k: item.get(k) for k in INDEX_FIELDS + ("source", "decision_reason", "actual_return", "virtual_return", "mfe", "mae", "lesson_generated")})
                raw_event_count += 1
            daily_summary = self._daily_summary(items, date)
            _write_json(daily_path, daily_summary)
            _write_json(weekly_path, self._weekly_summary(date))
        graph = self._graph_summary(opportunities, summary)
        _write_json(self.graph_latest, graph)
        _write_json(os.path.join(self.graph_daily_dir, f"{today}.graph.summary.json"), graph)
        _write_json(self.dashboard_cache_path, summary)
        return self._storage_health(raw_event_count=raw_event_count, dashboard_scan_rows=len(opportunities))

    def _daily_summary(self, items: list[dict[str, Any]], date: str) -> dict[str, Any]:
        decisions = Counter(_text(i.get("decision_type"), "unknown") for i in items)
        outcomes = Counter(_text(i.get("outcome_label"), "unknown") for i in items)
        indexes = {field: Counter(_text(i.get(field), "unknown") for i in items).most_common(20) for field in INDEX_FIELDS if field != "opportunity_id"}
        return {
            "date": date,
            "generated_at": _now_iso(),
            "opportunities": len(items),
            "decision_distribution": dict(decisions),
            "outcome_distribution": dict(outcomes),
            "missed_winners": sum(1 for i in items if i.get("missed_winner_flag")),
            "avoided_losers": sum(1 for i in items if i.get("avoided_loser_flag")),
            "average_actual_return": _avg([_to_float(i.get("actual_return")) for i in items]),
            "indexes": indexes,
        }

    def _weekly_summary(self, date: str) -> dict[str, Any]:
        try:
            anchor = datetime.fromisoformat(date).date()
        except Exception:
            anchor = _now().date()
        days = [(anchor - timedelta(days=i)).isoformat() for i in range(7)]
        totals = Counter()
        opportunity_count = 0
        for day in days:
            path = os.path.join(self.warm_dir, f"{day}.summary.json")
            payload = _read_json(path)
            opportunity_count += _to_int(payload.get("opportunities"), 0)
            totals.update(payload.get("decision_distribution") or {})
        return {"week_anchor": date, "generated_at": _now_iso(), "opportunities": opportunity_count, "decision_distribution": dict(totals)}

    def _archive_old_hot_files(self) -> int:
        os.makedirs(self.archive_dir, exist_ok=True)
        count = 0
        cutoff = _now().date() - timedelta(days=MAX_HOT_LOOKBACK_DAYS)
        try:
            for name in os.listdir(self.hot_dir):
                if not name.endswith(".jsonl"):
                    continue
                day = name[:-6]
                try:
                    file_date = datetime.fromisoformat(day).date()
                except Exception:
                    continue
                path = os.path.join(self.hot_dir, name)
                if file_date >= cutoff and os.path.getsize(path) <= MAX_FILE_SIZE_BEFORE_ROTATION:
                    continue
                archive_path = os.path.join(self.archive_dir, f"{name}.gz")
                if os.path.exists(archive_path):
                    continue
                with open(path, "rb") as src, gzip.open(archive_path, "wb") as dst:
                    dst.write(src.read())
                count += 1
        except Exception:
            return count
        return count

    def _storage_health(self, raw_event_count: int, dashboard_scan_rows: int) -> dict[str, Any]:
        archive_count = 0
        summary_count = 0
        raw_files = 0
        raw_bytes = 0
        for root, _, files in os.walk(os.path.join(self.state_dir, "opportunities")) if os.path.exists(os.path.join(self.state_dir, "opportunities")) else []:
            for name in files:
                path = os.path.join(root, name)
                if name.endswith(".summary.json") or ".weekly.summary.json" in name:
                    summary_count += 1
                elif name.endswith(".gz"):
                    archive_count += 1
                elif name.endswith(".jsonl"):
                    raw_files += 1
                    try:
                        raw_bytes += os.path.getsize(path)
                    except Exception:
                        pass
        cache_age = None
        if os.path.exists(self.dashboard_cache_path):
            try:
                cache_age = max(0.0, time.time() - os.path.getmtime(self.dashboard_cache_path))
            except Exception:
                cache_age = None
        memory_pressure = _clamp((raw_bytes / max(1, MAX_FILE_SIZE_BEFORE_ROTATION * 4)) * 100.0 + max(0, dashboard_scan_rows - 600) * 0.03)
        storage_health = _clamp(100.0 - memory_pressure * 0.65 - max(0, raw_files - 12) * 1.5 + min(10.0, summary_count * 0.25))
        return {
            "raw_event_count": raw_event_count,
            "compact_summary_count": summary_count,
            "archive_count": archive_count,
            "raw_hot_file_count": raw_files,
            "raw_hot_bytes": raw_bytes,
            "cache_age_seconds": round(cache_age, 3) if cache_age is not None else None,
            "cache_freshness": _freshness_label(cache_age),
            "freshness_status": _freshness_label(cache_age),
            "dashboard_scan_rows": dashboard_scan_rows,
            "max_raw_rows_scanned_per_build": MAX_RAW_ROWS_SCANNED,
            "max_file_size_before_rotation": MAX_FILE_SIZE_BEFORE_ROTATION,
            "max_hot_lookback_days": MAX_HOT_LOOKBACK_DAYS,
            "memory_pressure_score": _round(memory_pressure, 2),
            "storage_health_score": _round(storage_health, 2),
            "compaction_status": "healthy" if storage_health >= 70 else "watch_memory_pressure",
            "estimated_load_ms": _round(8.0 + dashboard_scan_rows * 0.015, 2),
        }

    def _graph_summary(self, opportunities: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
        edges: Counter[str] = Counter()
        systems: Counter[str] = Counter()
        for opp in opportunities:
            decision = _text(opp.get("decision_type"), "unknown")
            if opp.get("confidence") is not None:
                systems["confidence_calibration"] += 1
                edges[f"confidence_calibration->{opp.get('outcome_label')}"] += 1
            if _text(opp.get("catalyst"), "unknown_catalyst") not in {"unknown_catalyst", "unknown"}:
                systems["catalyst_theme_narrative"] += 1
                edges[f"catalyst_theme_narrative->{opp.get('catalyst')}"] += 1
            systems["market_context"] += 1
            systems["regime_archetype"] += 1
            edges[f"regime_archetype->{opp.get('archetype')}"] += 1
            if decision in {"rejected", "skipped", "ignored", "blocked"}:
                systems["opportunity_cost"] += 1
                edges[f"opportunity_cost->{opp.get('outcome_label')}"] += 1
            if decision == "entered":
                systems["profit_capture"] += 1
                systems["exit_learning"] += 1
                systems["replay"] += 1
                edges[f"profit_capture->{opp.get('horizon')}"] += 1
            systems["decision_optimization"] += 1
            systems["portfolio_risk"] += 1
        weakest = min((s for s in LEARNING_SYSTEMS), key=lambda s: systems.get(s, 0), default="insufficient_data")
        strongest = edges.most_common(1)[0][0] if edges else "insufficient_data"
        return {
            "generated_at": _now_iso(),
            "graph_nodes": len(set([o.get("symbol") for o in opportunities]) | set(LEARNING_SYSTEMS)),
            "graph_edges": sum(edges.values()),
            "strongest_learning_connection": strongest,
            "weakest_learning_connection": f"{weakest}->insufficient_evidence",
            "systems_receiving_evidence": dict(systems),
            "cross_system_learning_score": _round(_clamp(len([s for s in LEARNING_SYSTEMS if systems.get(s, 0) > 0]) / len(LEARNING_SYSTEMS) * 100.0), 2),
            "edge_sample": dict(edges.most_common(12)),
        }

    def _predictive_features(self, opportunities: list[dict[str, Any]]) -> dict[str, Any]:
        features = ("confidence_bucket", "grade", "horizon", "catalyst", "theme", "sector", "archetype", "regime", "market_context", "decision_reason")
        scores: dict[str, float] = {}
        profit_features: Counter[str] = Counter()
        loss_features: Counter[str] = Counter()
        for feature in features:
            groups: dict[str, list[float]] = defaultdict(list)
            for opp in opportunities:
                groups[_text(opp.get(feature), "unknown")].append(_to_float(opp.get("actual_return") or opp.get("virtual_return")))
            avgs = [_avg(v) or 0.0 for v in groups.values() if len(v) >= 2]
            if len(avgs) >= 2:
                scores[feature] = _round(max(avgs) - min(avgs), 4)
            else:
                scores[feature] = 0.0
        for opp in opportunities:
            feature_label = f"{opp.get('horizon')}:{opp.get('archetype')}:{opp.get('catalyst')}"
            if _to_float(opp.get("actual_return") or opp.get("virtual_return")) > 0:
                profit_features[feature_label] += 1
            elif _to_float(opp.get("actual_return") or opp.get("virtual_return")) < 0:
                loss_features[feature_label] += 1
        most = max(scores.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        least = min(scores.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        confidence = _round(_clamp(len(opportunities) / 120.0 * 100.0), 2)
        return {
            "most_predictive_feature": most,
            "least_predictive_feature": least,
            "feature_predictive_score": {k: _round(v, 4) for k, v in scores.items()},
            "top_profit_features": [k for k, _ in profit_features.most_common(8)],
            "top_loss_features": [k for k, _ in loss_features.most_common(8)],
            "feature_attribution_confidence": confidence,
        }

    def _meta_learning_priority(self, opportunities: list[dict[str, Any]], feature: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
        missed = sum(1 for o in opportunities if o.get("missed_winner_flag"))
        avoided = sum(1 for o in opportunities if o.get("avoided_loser_flag"))
        entered = sum(1 for o in opportunities if o.get("decision_type") == "entered")
        gaps = {
            "opportunity_cost_rejected_candidates": missed * 1.4,
            "profit_capture_entered_trades": entered * 0.8,
            "confidence_truth_calibration": 100.0 - _to_float(feature.get("feature_attribution_confidence"), 0.0),
            "cross_system_graph_routing": 100.0 - _to_float(graph.get("cross_system_learning_score"), 0.0),
            "avoid_loser_validation": avoided * 0.35,
        }
        high = max(gaps.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        low = min(gaps.items(), key=lambda kv: kv[1], default=("insufficient_data", 0.0))[0]
        return {
            "highest_value_learning_focus": high,
            "lowest_value_learning_focus": low,
            "recommended_worker_focus": high,
            "learning_roi_score": _round(_clamp(max(gaps.values()) if gaps else 0.0), 2),
            "priority_confidence": _round(_clamp(len(opportunities) / 160.0 * 100.0), 2),
            "learning_focus_scores": {k: _round(v, 2) for k, v in gaps.items()},
        }

    def _memory_decay(self, opportunities: list[dict[str, Any]]) -> dict[str, Any]:
        today = _now().date()
        reinforced = 0
        tentative = 0
        stale = 0
        retired = 0
        statuses: Counter[str] = Counter()
        for opp in opportunities:
            try:
                age = (today - datetime.fromisoformat(_text(opp.get("date"), today.isoformat())).date()).days
            except Exception:
                age = 0
            reinforced_flag = bool(opp.get("lesson_generated") and (opp.get("missed_winner_flag") or opp.get("avoided_loser_flag") or abs(_to_float(opp.get("actual_return"))) >= 2.0))
            if reinforced_flag and age <= 14:
                status = "reinforced"
                reinforced += 1
            elif age > 45:
                status = "retired"
                retired += 1
            elif age > 21:
                status = "stale"
                stale += 1
            else:
                status = "tentative" if not reinforced_flag else "active"
                tentative += int(status == "tentative")
            statuses[status] += 1
        quality = _round(_clamp((reinforced + statuses.get("active", 0)) / max(1, len(opportunities)) * 100.0 + min(20.0, len(opportunities) * 0.02) - stale * 0.2), 2)
        retention = _round(_clamp(100.0 - (stale + retired) / max(1, len(opportunities)) * 100.0), 2)
        return {
            "reinforced_lessons": reinforced,
            "active_lessons": statuses.get("active", 0),
            "tentative_lessons": tentative,
            "stale_lessons": stale,
            "retired_lessons": retired,
            "lesson_status_distribution": dict(statuses),
            "memory_quality_score": quality,
            "retention_efficiency_score": retention,
        }

    def _build_summary(self, opportunities: list[dict[str, Any]], statuses: dict[str, dict[str, Any]], start: float) -> dict[str, Any]:
        decisions = Counter(_text(o.get("decision_type"), "unknown") for o in opportunities)
        missed = sum(1 for o in opportunities if o.get("missed_winner_flag"))
        avoided = sum(1 for o in opportunities if o.get("avoided_loser_flag"))
        entered = decisions.get("entered", 0)
        virtual = decisions.get("virtual_only", 0)
        rejected = decisions.get("rejected", 0)
        skipped = decisions.get("skipped", 0)
        ignored = decisions.get("ignored", 0)
        blocked = decisions.get("blocked", 0) + decisions.get("duplicate", 0)
        graph = self._graph_summary(opportunities, {})
        feature = self._predictive_features(opportunities)
        priority = self._meta_learning_priority(opportunities, feature, graph)
        memory = self._memory_decay(opportunities)
        completeness_parts = [
            min(100.0, len(opportunities) / 180.0 * 100.0),
            min(100.0, len([o for o in opportunities if o.get("outcome_label") != "neutral"]) / max(1, len(opportunities)) * 140.0),
            _to_float(graph.get("cross_system_learning_score"), 0.0),
            _to_float(feature.get("feature_attribution_confidence"), 0.0),
        ]
        completeness = _round(_avg(completeness_parts) or 0.0, 2)
        storage_stub = self._storage_health(raw_event_count=0, dashboard_scan_rows=len(opportunities))
        recommendation = f"shadow_only_prioritize_{priority.get('highest_value_learning_focus')}; keep_dashboard_on_cached_summary_fast_path"
        summary = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_full_opportunity_lifecycle_learning",
            "generated_at": _now_iso(),
            "last_updated": _now_iso(),
            "opportunities_tracked": len(opportunities),
            "paper_trades_tracked": entered,
            "virtual_trades_tracked": virtual,
            "rejected_tracked": rejected,
            "skipped_tracked": skipped,
            "ignored_tracked": ignored,
            "blocked_tracked": blocked,
            "canceled_tracked": decisions.get("canceled", 0),
            "duplicate_tracked": decisions.get("duplicate", 0),
            "missed_winners": missed,
            "avoided_losers": avoided,
            "learning_completeness_score": completeness,
            "decision_distribution": dict(decisions),
            "outcome_distribution": dict(Counter(_text(o.get("outcome_label"), "unknown") for o in opportunities)),
            "graph_nodes": graph.get("graph_nodes", 0),
            "graph_edges": graph.get("graph_edges", 0),
            "strongest_learning_connection": graph.get("strongest_learning_connection", "insufficient_data"),
            "weakest_learning_connection": graph.get("weakest_learning_connection", "insufficient_data"),
            "systems_receiving_evidence": graph.get("systems_receiving_evidence", {}),
            "cross_system_learning_score": graph.get("cross_system_learning_score", 0.0),
            **feature,
            **priority,
            **memory,
            **storage_stub,
            "cache_status": "rebuilt",
            "cache_freshness": "live",
            "freshness_status": "live",
            "data_source_label": "compact_cached_summary_with_bounded_hot_scan_on_force",
            "hot_storage_path": "state/opportunities/raw/YYYY-MM-DD.jsonl",
            "warm_storage_path": "state/opportunities/summaries/YYYY-MM-DD.summary.json",
            "cold_storage_adapter": "optional_sqlite_or_gzip_archive_prepared",
            "dashboard_cache_path": "state/dashboard_cache/full_opportunity_lifecycle_summary.json",
            "index_fields": list(INDEX_FIELDS),
            "cache_invalidation_policy": "new_trade_event_or_position_change_or_market_session_change_or_stale_cache_or_force_true",
            "bandwidth_saving_mode": True,
            "api_budget_status": "cached_local_only",
            "bandwidth_pressure_score": 0.0,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
            "shadow_recommendation": recommendation,
            "summary": "Astra is learning from every observed opportunity while keeping raw memory separate from fast dashboard summaries.",
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
            "auto_apply_allowed": False,
            "human_review_required": True,
            "behavior_safe_to_apply": False,
        }
        storage = self._write_tiered_storage(opportunities, summary)
        self._archive_old_hot_files()
        storage = self._storage_health(raw_event_count=storage.get("raw_event_count", 0), dashboard_scan_rows=len(opportunities))
        summary.update(storage)
        summary["cache_status"] = "rebuilt"
        summary["cache_freshness"] = _freshness_label(0.0)
        summary["freshness_status"] = _freshness_label(0.0)
        summary["build_ms"] = _round((time.perf_counter() - start) * 1000.0, 3)
        _write_json(self.dashboard_cache_path, summary)
        return summary

    def _cached_summary(self) -> dict[str, Any] | None:
        payload = _read_json(self.dashboard_cache_path)
        if not payload:
            return None
        age = None
        try:
            age = max(0.0, time.time() - os.path.getmtime(self.dashboard_cache_path))
        except Exception:
            age = None
        payload["cache_hit"] = True
        payload["cache_status"] = "cache_hit"
        payload["cache_age_seconds"] = round(age, 3) if age is not None else None
        payload["cache_freshness"] = _freshness_label(age)
        payload["freshness_status"] = _freshness_label(age)
        payload["dashboard_scan_rows"] = 0
        payload["estimated_load_ms"] = min(_to_float(payload.get("estimated_load_ms"), 8.0), 12.0)
        payload["api_calls_used"] = 0
        payload["provider_calls_used"] = 0
        payload["llm_calls_used"] = 0
        payload["bandwidth_saving_mode"] = True
        payload["behavior_safe_to_apply"] = False
        return payload

    def status(self, statuses: dict[str, dict[str, Any]] | None = None, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if not force and self._cache and now - self._cache_ts < self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["dashboard_scan_rows"] = 0
            out["estimated_load_ms"] = min(_to_float(out.get("estimated_load_ms"), 8.0), 12.0)
            out["behavior_safe_to_apply"] = False
            return out
        if not force:
            cached = self._cached_summary()
            if cached and _to_float(cached.get("cache_age_seconds"), 999999.0) <= DASHBOARD_CACHE_MAX_AGE_SECONDS:
                self._cache = cached
                self._cache_ts = now
                return cached
        try:
            start = time.perf_counter()
            source_rows = self._source_rows()
            opportunities = self._dedup_opportunities(source_rows)
            out = self._build_summary(opportunities, statuses or {}, start)
            out["cache_hit"] = False
            self._cache = out
            self._cache_ts = now
            return out
        except Exception as exc:
            cached = self._cached_summary()
            if cached:
                cached["stale_cache"] = True
                cached["degraded_reason"] = f"full_opportunity_lifecycle_rebuild_failed_using_cache:{str(exc)[:140]}"
                cached["behavior_safe_to_apply"] = False
                return cached
            return {
                "enabled": False,
                "version": VERSION,
                "mode": "paper_only_full_opportunity_lifecycle_learning",
                "opportunities_tracked": 0,
                "learning_completeness_score": 0.0,
                "missed_winners": 0,
                "avoided_losers": 0,
                "strongest_learning_connection": "unavailable",
                "most_predictive_feature": "unavailable",
                "highest_value_learning_focus": "unavailable",
                "memory_quality_score": 0.0,
                "storage_health_score": 0.0,
                "memory_pressure_score": 0.0,
                "cache_freshness": "stale",
                "freshness_status": "stale",
                "dashboard_scan_rows": 0,
                "degraded_reason": f"full_opportunity_lifecycle_learning_suite_v1_unavailable:{str(exc)[:140]}",
                "api_calls_used": 0,
                "provider_calls_used": 0,
                "llm_calls_used": 0,
                "bandwidth_saving_mode": True,
                "api_budget_status": "cached_local_only",
                "bandwidth_pressure_score": 0.0,
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
                "partial_sells_enabled": False,
                "automatic_trailing_stops_enabled": False,
                "auto_apply_allowed": False,
                "human_review_required": True,
                "behavior_safe_to_apply": False,
            }
