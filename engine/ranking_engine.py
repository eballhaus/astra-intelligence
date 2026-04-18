"""
ASTRA INTELLIGENCE — RANKING ENGINE (STABLE VERSION)
----------------------------------------------------
Evaluates and ranks stock symbols using Astra AI logic.
"""

import numpy as np
import pandas as pd
import random
import time
import requests
import os
import json
from engine.adaptive_learning import AdaptiveLearningEngine
from engine.persona_council import PersonaCouncil, PersonaCouncilAggregator
from engine.persona_performance_tracker import PersonaPerformanceTracker


class RankingEngine:
    """Generates buy/sell grades based on performance, volatility, and momentum."""
    _wf_cache = None
    _wf_cache_ts = 0.0
    _tf_cache = {}
    _tf_cache_ttl_seconds = 8

    def __init__(self):
        self.grade_thresholds = {
            "A+": 90,
            "A": 80,
            "B+": 70,
            "B": 60,
            "C": 50,
            "D": 40,
            "F": 0,
        }
        self.gate_confidence_min = float(os.getenv("ASTRA_GATE_CONFIDENCE_MIN", "75"))
        self.gate_tf_align_min = float(os.getenv("ASTRA_GATE_TF_ALIGN_MIN", "55"))
        self.gate_vol_min = float(os.getenv("ASTRA_GATE_VOL_MIN", "0.1"))
        self.gate_vol_max = float(os.getenv("ASTRA_GATE_VOL_MAX", "8.0"))
        self.gate_rolling_sharpe_min = float(os.getenv("ASTRA_GATE_ROLLING_SHARPE_MIN", "0.0"))
        self.gate_wf_stability_min = float(os.getenv("ASTRA_GATE_WF_STABILITY_MIN", "0.2"))
        self._system_health_path = os.getenv("ASTRA_SYSTEM_HEALTH_PATH", "state/system_health.json")
        self._wf_cache_ttl_seconds = int(os.getenv("ASTRA_WF_CACHE_TTL_SECONDS", "900"))
        self.adaptive_learning = AdaptiveLearningEngine()
        self.persona_council = PersonaCouncil()
        self.persona_aggregator = PersonaCouncilAggregator()
        self.persona_tracker = PersonaPerformanceTracker()

    # -------------------------------------------------------------
    # Core Scoring
    # -------------------------------------------------------------
    def get_score(self, df: pd.DataFrame):
        """Calculate a numeric score (0–100) based on performance metrics."""
        try:
            if df is None or df.empty or "close" not in df.columns:
                return 0

            closes = df["close"].astype(float)
            returns = closes.pct_change().dropna()
            momentum = (closes.iloc[-1] / closes.iloc[-5]) - 1 if len(closes) > 5 else 0
            volatility = returns.std() * 100
            score = (momentum * 100) - (volatility * 0.5)
            return round(np.clip(score, 0, 100), 2)
        except Exception as e:
            print(f"[RankingEngine] get_score() error: {e}")
            return 0

    # -------------------------------------------------------------
    # Grade Lookup
    # -------------------------------------------------------------
    def get_grade(self, symbol: str, df: pd.DataFrame):
        """Return a letter grade (A–F) based on computed score."""
        score = self.get_score(df)
        for label, threshold in self.grade_thresholds.items():
            if score >= threshold:
                return label
        return "F"

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clip(value, lo=0.0, hi=100.0):
        return max(float(lo), min(float(hi), float(value)))

    def _entry_confirmation_score(
        self,
        timeframe_alignment_score,
        consensus_strength,
        persona_disagreement_index,
        volatility_factor,
        momentum_weight,
        predicted_win_probability,
    ):
        """
        Additive entry confirmation layer (0-100).
        This is intentionally parallel to existing confidence/quality gates.
        """
        tf = self._clip(self._safe_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        consensus = self._clip(self._safe_float(consensus_strength, 50.0), 0.0, 100.0)
        disagreement = self._clip(self._safe_float(persona_disagreement_index, 50.0), 0.0, 100.0)
        vol = abs(self._safe_float(volatility_factor, 0.0))
        momentum = abs(self._safe_float(momentum_weight, 0.0)) * 100.0
        win_prob = self._clip(self._safe_float(predicted_win_probability, 0.4) * 100.0, 0.0, 100.0)

        # Prefer aligned + consensual setups, penalize over-extension and disagreement.
        extension_penalty = self._clip(max(0.0, vol - 2.2) * 7.0, 0.0, 30.0)
        weak_momentum_penalty = self._clip(max(0.0, 0.25 - momentum) * 60.0, 0.0, 15.0)
        disagreement_penalty = self._clip((disagreement - 45.0) * 0.35, 0.0, 20.0)
        base = (tf * 0.34) + (consensus * 0.28) + (win_prob * 0.24) + (self._clip(momentum * 3.5, 0.0, 100.0) * 0.14)
        return round(self._clip(base - extension_penalty - weak_momentum_penalty - disagreement_penalty, 0.0, 100.0), 2)

    def _early_follow_through_score(
        self,
        momentum_weight,
        timeframe_alignment_score,
        consensus_strength,
        predicted_win_probability,
        regime_context,
    ):
        """
        Additive early follow-through likelihood layer (0-100).
        """
        momentum = self._safe_float(momentum_weight, 0.0) * 100.0
        tf = self._clip(self._safe_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        consensus = self._clip(self._safe_float(consensus_strength, 50.0), 0.0, 100.0)
        win_prob = self._clip(self._safe_float(predicted_win_probability, 0.4) * 100.0, 0.0, 100.0)
        regime = str(regime_context or "").lower()

        regime_bonus = 0.0
        if "trend" in regime or "breakout" in regime:
            regime_bonus = 4.0
        elif "risk_off" in regime:
            regime_bonus = -5.0
        elif "range_high_vol" in regime:
            regime_bonus = -3.0

        stall_penalty = self._clip(max(0.0, 0.15 - abs(momentum)) * 55.0, 0.0, 18.0)
        reversal_penalty = 8.0 if momentum < -0.10 else 0.0
        base = (tf * 0.32) + (consensus * 0.26) + (win_prob * 0.30) + (self._clip((momentum + 5.0) * 8.0, 0.0, 100.0) * 0.12)
        return round(self._clip(base + regime_bonus - stall_penalty - reversal_penalty, 0.0, 100.0), 2)

    def _deterioration_score(
        self,
        timeframe_alignment_score,
        consensus_strength,
        persona_disagreement_index,
        volatility_factor,
        momentum_weight,
        regime_context,
    ):
        """
        Additive deterioration risk layer (0-100, higher means worse structure).
        """
        tf = self._clip(self._safe_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        consensus = self._clip(self._safe_float(consensus_strength, 50.0), 0.0, 100.0)
        disagreement = self._clip(self._safe_float(persona_disagreement_index, 50.0), 0.0, 100.0)
        vol = abs(self._safe_float(volatility_factor, 0.0))
        momentum = self._safe_float(momentum_weight, 0.0) * 100.0
        regime = str(regime_context or "").lower()

        regime_risk = 0.0
        if "risk_off" in regime:
            regime_risk = 8.0
        elif "range_high_vol" in regime:
            regime_risk = 5.0

        risk = (
            max(0.0, 65.0 - tf) * 0.30
            + max(0.0, 62.0 - consensus) * 0.24
            + max(0.0, disagreement - 42.0) * 0.34
            + max(0.0, vol - 1.8) * 3.4
            + max(0.0, -momentum) * 0.36
            + regime_risk
        )
        return round(self._clip(risk, 0.0, 100.0), 2)

    def _promotion_quality_metrics(
        self,
        entry_confirmation_score,
        early_follow_through_score,
        deterioration_score,
        timeframe_alignment_score,
        consensus_strength,
        predicted_win_probability,
    ):
        """
        Additive promotion-quality shaping layer.
        Lower penalties should preserve trade flow; higher penalties suppress weak entries.
        """
        entry_conf = self._clip(self._safe_float(entry_confirmation_score, 50.0), 0.0, 100.0)
        early_ft = self._clip(self._safe_float(early_follow_through_score, 50.0), 0.0, 100.0)
        det = self._clip(self._safe_float(deterioration_score, 50.0), 0.0, 100.0)
        tf = self._clip(self._safe_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        consensus = self._clip(self._safe_float(consensus_strength, 50.0), 0.0, 100.0)
        win_prob = self._clip(self._safe_float(predicted_win_probability, 0.45), 0.0, 1.0)

        setup_clarity_penalty = self._clip(
            max(0.0, 58.0 - tf) * 0.22
            + max(0.0, 57.0 - consensus) * 0.20
            + max(0.0, 52.0 - entry_conf) * 0.30,
            0.0,
            18.0,
        )
        entry_followthrough_penalty = self._clip(
            max(0.0, 56.0 - early_ft) * 0.36
            + max(0.0, det - 55.0) * 0.24,
            0.0,
            20.0,
        )
        entry_failure_risk_penalty = self._clip(
            max(0.0, det - 62.0) * 0.36
            + max(0.0, 50.0 - entry_conf) * 0.24
            + max(0.0, 0.58 - win_prob) * 30.0,
            0.0,
            22.0,
        )
        weak_process_penalty = self._clip(
            max(0.0, 54.0 - early_ft) * 0.34
            + max(0.0, det - 58.0) * 0.28
            + max(0.0, 0.56 - win_prob) * 35.0
            + (entry_followthrough_penalty * 0.25)
            + (entry_failure_risk_penalty * 0.30),
            0.0,
            26.0,
        )
        entry_quality_penalty = round(
            self._clip(
                (setup_clarity_penalty * 0.40)
                + (entry_followthrough_penalty * 0.32)
                + (entry_failure_risk_penalty * 0.28),
                0.0,
                30.0,
            ),
            2,
        )
        promotion_quality_penalty = round(
            self._clip(
                (setup_clarity_penalty * 0.30)
                + (weak_process_penalty * 0.42)
                + (entry_quality_penalty * 0.28),
                0.0,
                40.0,
            ),
            2,
        )
        release_readiness_score = round(
            self._clip(
                (entry_conf * 0.26)
                + (early_ft * 0.26)
                + ((100.0 - det) * 0.20)
                + (tf * 0.12)
                + (consensus * 0.08)
                + ((win_prob * 100.0) * 0.08)
                - (promotion_quality_penalty * 0.62),
                0.0,
                100.0,
            ),
            2,
        )
        if release_readiness_score >= 75.0 and promotion_quality_penalty <= 8.0:
            reason = "high_clarity_high_follow_through"
        elif release_readiness_score >= 64.0:
            reason = "moderate_quality_needs_confirmation"
        else:
            reason = "weak_process_or_low_clarity_holdback"
        return {
            "setup_clarity_penalty": round(setup_clarity_penalty, 2),
            "entry_followthrough_penalty": round(entry_followthrough_penalty, 2),
            "entry_failure_risk_penalty": round(entry_failure_risk_penalty, 2),
            "entry_quality_penalty": entry_quality_penalty,
            "weak_process_penalty": round(weak_process_penalty, 2),
            "promotion_quality_penalty": promotion_quality_penalty,
            "release_readiness_score": release_readiness_score,
            "promotion_reason_summary": reason,
        }

    def _entry_discipline_metrics(
        self,
        confidence,
        release_readiness_score,
        promotion_quality_penalty,
        entry_confirmation_score,
        early_follow_through_score,
        deterioration_score,
        timeframe_alignment_score,
        consensus_strength,
        predicted_win_probability,
        volatility_factor,
        regime_context,
    ):
        """
        Lightweight entry-discipline gate score.
        Additive and bounded: discourages weak entries without hard-killing flow.
        """
        conf = self._clip(self._safe_float(confidence, 50.0), 0.0, 100.0)
        readiness = self._clip(self._safe_float(release_readiness_score, 50.0), 0.0, 100.0)
        quality_penalty = self._clip(self._safe_float(promotion_quality_penalty, 0.0), 0.0, 100.0)
        entry_conf = self._clip(self._safe_float(entry_confirmation_score, 50.0), 0.0, 100.0)
        early_ft = self._clip(self._safe_float(early_follow_through_score, 50.0), 0.0, 100.0)
        det = self._clip(self._safe_float(deterioration_score, 50.0), 0.0, 100.0)
        tf = self._clip(self._safe_float(timeframe_alignment_score, 50.0), 0.0, 100.0)
        consensus = self._clip(self._safe_float(consensus_strength, 50.0), 0.0, 100.0)
        win_prob = self._clip(self._safe_float(predicted_win_probability, 0.45), 0.0, 1.0)
        vol = abs(self._safe_float(volatility_factor, 0.0))
        regime = str(regime_context or "").lower()

        context_toxicity_penalty = 0.0
        holdback_reasons = []
        if (regime in {"ranging", "range_low_vol"} or "range" in regime) and vol <= 0.24:
            context_toxicity_penalty += 9.5
            holdback_reasons.append("range_low_vol_toxicity")
        if "risk_off" in regime and readiness < 66.0:
            context_toxicity_penalty += 7.0
            holdback_reasons.append("risk_off_weak_readiness")
        if vol >= 3.0 and entry_conf < 58.0:
            context_toxicity_penalty += 6.5
            holdback_reasons.append("overextended_weak_confirmation")
        if early_ft < 50.0 and det >= 60.0:
            context_toxicity_penalty += 7.5
            holdback_reasons.append("weak_follow_through_high_deterioration")
        if entry_conf < 50.0 and tf < 54.0:
            context_toxicity_penalty += 5.5
            holdback_reasons.append("weak_clarity_context")
        if early_ft < 46.0:
            context_toxicity_penalty += 4.0
            holdback_reasons.append("weak_follow_through_expectation")
        context_toxicity_penalty = self._clip(context_toxicity_penalty, 0.0, 24.0)

        entry_followthrough_penalty = self._clip(
            max(0.0, 55.0 - early_ft) * 0.26
            + max(0.0, det - 59.0) * 0.22,
            0.0,
            18.0,
        )
        entry_failure_risk_penalty = self._clip(
            max(0.0, det - 63.0) * 0.34
            + max(0.0, 50.0 - entry_conf) * 0.22
            + max(0.0, 0.57 - win_prob) * 24.0,
            0.0,
            18.0,
        )
        entry_quality_penalty = round(
            self._clip(
                (quality_penalty * 0.36)
                + (context_toxicity_penalty * 0.24)
                + (entry_followthrough_penalty * 0.22)
                + (entry_failure_risk_penalty * 0.18),
                0.0,
                36.0,
            ),
            2,
        )

        discipline_raw = (
            (readiness * 0.28)
            + (entry_conf * 0.20)
            + (early_ft * 0.21)
            + ((100.0 - det) * 0.15)
            + (tf * 0.06)
            + (consensus * 0.04)
            + ((win_prob * 100.0) * 0.04)
            + (conf * 0.02)
            - (quality_penalty * 0.24)
            - (context_toxicity_penalty * 0.95)
            - (entry_followthrough_penalty * 0.55)
            - (entry_failure_risk_penalty * 0.65)
        )
        entry_discipline_score = round(self._clip(discipline_raw, 0.0, 100.0), 2)
        entry_release_gate_score = round(
            self._clip((entry_discipline_score * 0.62) + (readiness * 0.38), 0.0, 100.0),
            2,
        )
        entry_release_confidence = round(
            self._clip(
                entry_release_gate_score - (entry_quality_penalty * 0.22) - (context_toxicity_penalty * 0.18),
                0.0,
                100.0,
            ),
            2,
        )

        if (
            entry_release_gate_score >= 74.0
            and context_toxicity_penalty <= 4.0
            and entry_failure_risk_penalty <= 8.0
        ):
            path = "release_candidate"
            holdback_reason = "none"
            refinement_reason = "entry_discipline_confirmed_for_release"
        elif entry_release_gate_score >= 60.0:
            path = "paper_safe_or_secondary"
            holdback_reason = "confirmation_pending_or_context_caution"
            refinement_reason = "entry_quality_moderate_reroute_for_confirmation"
        else:
            path = "watchlist_holdback"
            holdback_reason = holdback_reasons[0] if holdback_reasons else "weak_entry_discipline"
            refinement_reason = "weak_entry_quality_or_high_failure_risk_holdback"

        return {
            "entry_discipline_score": entry_discipline_score,
            "entry_release_gate_score": entry_release_gate_score,
            "entry_release_confidence": entry_release_confidence,
            "context_toxicity_penalty": round(float(context_toxicity_penalty), 2),
            "entry_quality_penalty": entry_quality_penalty,
            "entry_followthrough_penalty": round(float(entry_followthrough_penalty), 2),
            "entry_failure_risk_penalty": round(float(entry_failure_risk_penalty), 2),
            "entry_holdback_reason": holdback_reason,
            "entry_refinement_reason": refinement_reason,
            "promotion_path_decision": path,
        }

    def _finnhub_key(self):
        try:
            from api_keys import API_POOLS
            stock_pool = list(API_POOLS.get("stocks", []))
            for provider, key in stock_pool:
                if provider == "FINNHUB" and key and not str(key).startswith("YOUR_"):
                    return key
        except Exception:
            return None
        return None

    def _fmp_key(self):
        try:
            from api_keys import API_POOLS
            stock_pool = list(API_POOLS.get("stocks", []))
            for provider, key in stock_pool:
                if provider == "FMP" and key and not str(key).startswith("YOUR_"):
                    return key
        except Exception:
            return None
        return None

    def _fetch_finnhub_candles(self, symbol: str, resolution: str, lookback_seconds: int = 7200):
        key = self._finnhub_key()
        if not key:
            return []
        now = int(time.time())
        start = max(0, now - int(lookback_seconds))
        url = "https://finnhub.io/api/v1/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "from": start,
            "to": now,
            "token": key,
        }
        try:
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            closes = data.get("c", []) if isinstance(data, dict) else []
            if not isinstance(closes, list):
                return []
            return [self._safe_float(x, 0.0) for x in closes if self._safe_float(x, 0.0) > 0]
        except Exception:
            return []

    def _fetch_fmp_candles(self, symbol: str, resolution: str, lookback_seconds: int = 7200):
        key = self._fmp_key()
        if not key:
            return []
        interval_map = {
            "1": "1min",
            "5": "5min",
            "15": "15min",
            "30": "30min",
            "60": "1hour",
        }
        interval = interval_map.get(str(resolution), "")
        if not interval:
            return []
        # Use a bounded bar count from lookback horizon.
        bars = max(30, min(600, int(lookback_seconds / max(60, int(resolution) * 60))))
        url = (
            f"https://financialmodelingprep.com/stable/historical-chart/{interval}"
            f"?symbol={str(symbol).upper()}&apikey={key}"
        )
        try:
            r = requests.get(url, timeout=5)
            data = r.json()
            if not isinstance(data, list):
                return []
            closes = []
            for row in data[:bars]:
                if not isinstance(row, dict):
                    continue
                c = self._safe_float(row.get("close"), 0.0)
                if c > 0:
                    closes.append(c)
            # FMP historical chart is newest-first.
            closes.reverse()
            return closes
        except Exception:
            return []

    def _fetch_market_candles(self, symbol: str, resolution: str, lookback_seconds: int = 7200):
        # Prefer FMP premium for broader historical depth; fallback to Finnhub.
        fmp = self._fetch_fmp_candles(symbol, resolution, lookback_seconds)
        if len(fmp) >= 12:
            return fmp
        return self._fetch_finnhub_candles(symbol, resolution, lookback_seconds)

    @staticmethod
    def _slope_signal(closes):
        if not closes or len(closes) < 3:
            return 0
        start = closes[0]
        end = closes[-1]
        if start <= 0:
            return 0
        delta = (end - start) / start
        if delta > 0.001:
            return 1
        if delta < -0.001:
            return -1
        return 0

    @staticmethod
    def _ma_slope_signal(closes, window=20):
        if not closes or len(closes) < window + 1:
            return 0
        ma_prev = float(np.mean(closes[-(window + 1):-1]))
        ma_now = float(np.mean(closes[-window:]))
        if ma_prev <= 0:
            return 0
        slope = (ma_now - ma_prev) / ma_prev
        if slope > 0.0005:
            return 1
        if slope < -0.0005:
            return -1
        return 0

    def _multi_timeframe_alignment(self, symbol: str, prediction: str):
        cache_key = f"{str(symbol).upper()}::{str(prediction)}"
        cached = RankingEngine._tf_cache.get(cache_key)
        now = time.time()
        if cached and (now - float(cached.get("ts", 0.0))) <= RankingEngine._tf_cache_ttl_seconds:
            return float(cached.get("value", 50.0))
        # Pull 1m/5m/15m/1h candles via FMP primary with Finnhub fallback.
        c1 = self._fetch_market_candles(symbol, "1", 60 * 90)
        c5 = self._fetch_market_candles(symbol, "5", 60 * 60 * 8)
        c15 = self._fetch_market_candles(symbol, "15", 60 * 60 * 24)
        c60 = self._fetch_market_candles(symbol, "60", 60 * 60 * 24 * 5)

        short_sig = self._slope_signal(c1[-20:] if len(c1) >= 20 else c1)
        short_sig2 = self._slope_signal(c5[-20:] if len(c5) >= 20 else c5)
        mid_sig = self._slope_signal(c15[-20:] if len(c15) >= 20 else c15)
        high_sig = self._ma_slope_signal(c60, window=20) if len(c60) >= 21 else self._slope_signal(c60[-20:] if len(c60) >= 20 else c60)

        short_term = short_sig if short_sig != 0 else short_sig2
        if short_sig != 0 and short_sig2 != 0 and short_sig != short_sig2:
            short_term = 0

        tf_signals = [short_term, mid_sig, high_sig]
        valid = [s for s in tf_signals if s != 0]
        if not valid:
            return 50.0

        # Base score from directional consensus across timeframes.
        consensus = abs(sum(valid)) / len(valid)  # [0,1]
        score = 45.0 + (consensus * 40.0)

        pred = str(prediction or "").lower()
        pred_dir = 1 if pred == "buy" else -1 if pred == "sell" else 0
        if pred_dir != 0:
            aligned = [s for s in valid if s == pred_dir]
            conflicted = [s for s in valid if s == -pred_dir]
            score += len(aligned) * 7.0
            score -= len(conflicted) * 9.0
        else:
            score -= 5.0

        out = round(float(np.clip(score, 0, 100)), 2)
        RankingEngine._tf_cache[cache_key] = {"ts": now, "value": out}
        return out

    def _load_system_health(self):
        try:
            with open(self._system_health_path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {
            "system_active": True,
            "rolling_sharpe": 0.0,
        }

    def _walkforward_stability_score(self):
        now = time.time()
        if RankingEngine._wf_cache is not None and (now - RankingEngine._wf_cache_ts) < self._wf_cache_ttl_seconds:
            return float(RankingEngine._wf_cache)

        score = 0.0
        wf_path = "state/walkforward_validation.json"
        try:
            if os.path.exists(wf_path):
                with open(wf_path, "r") as f:
                    wf = json.load(f)
                score = float(wf.get("stability_score", 0.0))
                RankingEngine._wf_cache = score
                RankingEngine._wf_cache_ts = now
                return score
        except Exception:
            pass

        RankingEngine._wf_cache = score
        RankingEngine._wf_cache_ts = now
        return score

    @staticmethod
    def _infer_regime_context(momentum_weight, volatility_factor, timeframe_alignment_score):
        if abs(float(momentum_weight)) >= 0.008 and float(timeframe_alignment_score) >= 65:
            return "trending"
        if float(volatility_factor) <= 0.35:
            return "ranging"
        return "neutral"

    def _predicted_win_probability(self, persona_weighted_grade, consensus_strength, adaptive_weight_score):
        # Lightweight bounded probability calibration (safe realism envelope 0.40..0.75).
        z = (
            ((float(persona_weighted_grade) - 50.0) / 12.0)
            + ((float(consensus_strength) - 50.0) / 20.0)
            + ((float(adaptive_weight_score) - 100.0) / 35.0)
        )
        sig = 1.0 / (1.0 + np.exp(-z))
        base_prob = 0.40 + (0.35 * sig)  # [0.40, 0.75]
        calibration_error = self.persona_tracker.summary().get("probability_calibration_error", 0.0)
        # Penalize high error slightly, never boosting probability on calibration term.
        calibrated = base_prob - min(0.03, max(0.0, float(calibration_error)) * 0.15)
        return round(float(np.clip(calibrated, 0.40, 0.75)), 4)

    # -------------------------------------------------------------
    # Evaluation Routine (used by data_orchestrator)
    # -------------------------------------------------------------
    def evaluate_symbol(
        self,
        symbol: str,
        price: float = None,
        provider_agreement: float = 0.0,
        volatility_factor: float = 0.0,
        momentum_weight: float = 0.0,
    ):
        """Evaluate symbol and return Astra-style structured intelligence."""
        try:
            score = random.uniform(60, 100)
            grade_percent = round(score, 2)

            if score >= 85:
                prediction, grade = "Buy", "A"
            elif score >= 70:
                prediction, grade = "Hold", "B"
            else:
                prediction, grade = "Sell", "C"

            base_confidence = random.uniform(72, 90)
            agreement_component = max(0.0, min(1.0, provider_agreement)) * 8.0
            volatility_penalty = min(15.0, max(0.0, volatility_factor) * 0.25)
            momentum_component = max(-4.0, min(4.0, momentum_weight * 100.0 * 0.1))
            timeframe_alignment_score = self._multi_timeframe_alignment(symbol, prediction)
            regime_context = self._infer_regime_context(momentum_weight, volatility_factor, timeframe_alignment_score)
            confidence_raw = base_confidence + agreement_component + momentum_component - volatility_penalty
            if timeframe_alignment_score >= 70:
                confidence_raw += min(10.0, (timeframe_alignment_score - 70.0) * 0.25)
            elif timeframe_alignment_score <= 40:
                confidence_raw -= min(12.0, (40.0 - timeframe_alignment_score) * 0.35)
            try:
                adaptive_payload = self.adaptive_learning.get_adaptive_adjustments(
                    base_confidence=confidence_raw,
                    timeframe_alignment_score=timeframe_alignment_score,
                    volatility_factor=volatility_factor,
                    walkforward_stability_score=self._walkforward_stability_score(),
                    regime_context=regime_context,
                )
                if not isinstance(adaptive_payload, dict):
                    adaptive_payload = {}
            except Exception:
                adaptive_payload = {}
            learning_confidence_adjustment = self._safe_float(
                adaptive_payload.get("learning_confidence_adjustment"), 0.0
            )
            confidence_raw = confidence_raw + learning_confidence_adjustment
            persona_payload = {
                "symbol": symbol,
                "price": price,
                "provider_agreement": provider_agreement,
                "volatility_factor": volatility_factor,
                "momentum_weight": momentum_weight,
                "timeframe_alignment_score": timeframe_alignment_score,
                "walkforward_stability_score": self._walkforward_stability_score(),
            }
            persona_breakdown = self.persona_council.evaluate(persona_payload)
            persona_agg = self.persona_aggregator.aggregate(persona_breakdown, regime_context=regime_context)
            persona_weighted_grade = self._safe_float(persona_agg.get("weighted_average_grade_percent"), grade_percent)
            persona_disagreement_index = self._safe_float(persona_agg.get("persona_disagreement_index"), 50.0)
            persona_consensus_score = self._safe_float(persona_agg.get("persona_consensus_score"), 50.0)
            majority_signal = persona_agg.get("majority_signal", prediction)
            consensus_strength = self._safe_float(persona_agg.get("consensus_strength"), 50.0)
            persona_weights_applied = persona_agg.get("persona_weights_applied", {})
            persona_weight_drift_score = self._safe_float(persona_agg.get("persona_weight_drift_score"), 0.0)
            # If persona disagreement is high, damp confidence slightly without overriding gates.
            disagreement_penalty = max(0.0, min(8.0, (persona_disagreement_index - 35.0) * 0.12))
            confidence_raw -= disagreement_penalty
            confidence = round(max(0.0, min(100.0, confidence_raw)), 2)
            adaptive_weight_score = self._safe_float(adaptive_payload.get("adaptive_weight_score"), 100.0)
            predicted_win_probability = self._predicted_win_probability(
                persona_weighted_grade,
                consensus_strength,
                adaptive_weight_score,
            )
            system_health = self._load_system_health()
            system_active = bool(system_health.get("system_active", True))
            rolling_sharpe = self._safe_float(system_health.get("rolling_sharpe"), 0.0)
            walkforward_stability_score = self._walkforward_stability_score()
            vol_in_band = self.gate_vol_min <= float(volatility_factor) <= self.gate_vol_max

            decision_breakdown = {
                "checks": {
                    "confidence_ok": confidence >= self.gate_confidence_min,
                    "timeframe_alignment_ok": timeframe_alignment_score >= self.gate_tf_align_min,
                    "volatility_band_ok": vol_in_band,
                    "system_active_ok": system_active is True,
                    "rolling_sharpe_ok": rolling_sharpe >= self.gate_rolling_sharpe_min,
                    "walkforward_stability_ok": walkforward_stability_score >= self.gate_wf_stability_min,
                },
                "values": {
                    "confidence": confidence,
                    "timeframe_alignment_score": timeframe_alignment_score,
                    "volatility_factor": round(float(volatility_factor), 4),
                    "system_active": system_active,
                    "rolling_sharpe": rolling_sharpe,
                    "walkforward_stability_score": walkforward_stability_score,
                    "predicted_win_probability": predicted_win_probability,
                },
                "thresholds": {
                    "confidence_min": self.gate_confidence_min,
                    "timeframe_alignment_min": self.gate_tf_align_min,
                    "volatility_min": self.gate_vol_min,
                    "volatility_max": self.gate_vol_max,
                    "rolling_sharpe_min": self.gate_rolling_sharpe_min,
                    "walkforward_stability_min": self.gate_wf_stability_min,
                },
            }
            entry_confirmation_score = self._entry_confirmation_score(
                timeframe_alignment_score=timeframe_alignment_score,
                consensus_strength=consensus_strength,
                persona_disagreement_index=persona_disagreement_index,
                volatility_factor=volatility_factor,
                momentum_weight=momentum_weight,
                predicted_win_probability=predicted_win_probability,
            )
            early_follow_through_score = self._early_follow_through_score(
                momentum_weight=momentum_weight,
                timeframe_alignment_score=timeframe_alignment_score,
                consensus_strength=consensus_strength,
                predicted_win_probability=predicted_win_probability,
                regime_context=regime_context,
            )
            deterioration_score = self._deterioration_score(
                timeframe_alignment_score=timeframe_alignment_score,
                consensus_strength=consensus_strength,
                persona_disagreement_index=persona_disagreement_index,
                volatility_factor=volatility_factor,
                momentum_weight=momentum_weight,
                regime_context=regime_context,
            )
            promotion_quality_metrics = self._promotion_quality_metrics(
                entry_confirmation_score=entry_confirmation_score,
                early_follow_through_score=early_follow_through_score,
                deterioration_score=deterioration_score,
                timeframe_alignment_score=timeframe_alignment_score,
                consensus_strength=consensus_strength,
                predicted_win_probability=predicted_win_probability,
            )
            setup_clarity_penalty = float(promotion_quality_metrics.get("setup_clarity_penalty", 0.0) or 0.0)
            entry_followthrough_penalty = float(
                promotion_quality_metrics.get("entry_followthrough_penalty", 0.0) or 0.0
            )
            entry_failure_risk_penalty = float(
                promotion_quality_metrics.get("entry_failure_risk_penalty", 0.0) or 0.0
            )
            entry_quality_penalty = float(
                promotion_quality_metrics.get("entry_quality_penalty", 0.0) or 0.0
            )
            weak_process_penalty = float(promotion_quality_metrics.get("weak_process_penalty", 0.0) or 0.0)
            promotion_quality_penalty = float(
                promotion_quality_metrics.get("promotion_quality_penalty", 0.0) or 0.0
            )
            release_readiness_score = float(
                promotion_quality_metrics.get("release_readiness_score", 0.0) or 0.0
            )
            promotion_reason_summary = str(
                promotion_quality_metrics.get("promotion_reason_summary") or "quality_holdback_unknown"
            )
            entry_discipline_metrics = self._entry_discipline_metrics(
                confidence=confidence,
                release_readiness_score=release_readiness_score,
                promotion_quality_penalty=promotion_quality_penalty,
                entry_confirmation_score=entry_confirmation_score,
                early_follow_through_score=early_follow_through_score,
                deterioration_score=deterioration_score,
                timeframe_alignment_score=timeframe_alignment_score,
                consensus_strength=consensus_strength,
                predicted_win_probability=predicted_win_probability,
                volatility_factor=volatility_factor,
                regime_context=regime_context,
            )
            entry_discipline_score = float(entry_discipline_metrics.get("entry_discipline_score", 0.0) or 0.0)
            entry_release_gate_score = float(entry_discipline_metrics.get("entry_release_gate_score", 0.0) or 0.0)
            entry_release_confidence = float(entry_discipline_metrics.get("entry_release_confidence", 0.0) or 0.0)
            context_toxicity_penalty = float(entry_discipline_metrics.get("context_toxicity_penalty", 0.0) or 0.0)
            entry_quality_penalty = float(
                entry_discipline_metrics.get("entry_quality_penalty", entry_quality_penalty) or 0.0
            )
            entry_followthrough_penalty = float(
                entry_discipline_metrics.get("entry_followthrough_penalty", entry_followthrough_penalty) or 0.0
            )
            entry_failure_risk_penalty = float(
                entry_discipline_metrics.get("entry_failure_risk_penalty", entry_failure_risk_penalty) or 0.0
            )
            entry_holdback_reason = str(entry_discipline_metrics.get("entry_holdback_reason") or "none")
            entry_refinement_reason = str(
                entry_discipline_metrics.get("entry_refinement_reason") or "entry_refinement_not_set"
            )
            promotion_path_decision = str(entry_discipline_metrics.get("promotion_path_decision") or "paper_safe_or_secondary")
            # Soft shaping only: suppress weak process without hard clamping trade flow.
            confidence_shaping_penalty = min(
                6.2,
                (promotion_quality_penalty * 0.12)
                + (context_toxicity_penalty * 0.09)
                + (entry_failure_risk_penalty * 0.05),
            )
            confidence_shaping_bonus = min(1.5, max(0.0, (release_readiness_score - 74.0) * 0.08))
            confidence = round(
                self._clip(confidence - confidence_shaping_penalty + confidence_shaping_bonus, 0.0, 100.0),
                2,
            )
            decision_breakdown["values"]["entry_confirmation_score"] = entry_confirmation_score
            decision_breakdown["values"]["early_follow_through_score"] = early_follow_through_score
            decision_breakdown["values"]["deterioration_score"] = deterioration_score
            decision_breakdown["values"]["confidence"] = confidence
            decision_breakdown["values"]["setup_clarity_penalty"] = setup_clarity_penalty
            decision_breakdown["values"]["entry_followthrough_penalty"] = entry_followthrough_penalty
            decision_breakdown["values"]["entry_failure_risk_penalty"] = entry_failure_risk_penalty
            decision_breakdown["values"]["entry_quality_penalty"] = entry_quality_penalty
            decision_breakdown["values"]["weak_process_penalty"] = weak_process_penalty
            decision_breakdown["values"]["promotion_quality_penalty"] = promotion_quality_penalty
            decision_breakdown["values"]["release_readiness_score"] = release_readiness_score
            decision_breakdown["values"]["promotion_reason_summary"] = promotion_reason_summary
            decision_breakdown["values"]["entry_discipline_score"] = entry_discipline_score
            decision_breakdown["values"]["entry_release_gate_score"] = entry_release_gate_score
            decision_breakdown["values"]["entry_release_confidence"] = entry_release_confidence
            decision_breakdown["values"]["context_toxicity_penalty"] = context_toxicity_penalty
            decision_breakdown["values"]["entry_holdback_reason"] = entry_holdback_reason
            decision_breakdown["values"]["entry_refinement_reason"] = entry_refinement_reason
            decision_breakdown["values"]["promotion_path_decision"] = promotion_path_decision
            decision_breakdown["adaptive_weights_applied"] = adaptive_payload.get("adaptive_weights_applied", {
                "confidence": 1.0,
                "timeframe_alignment": 1.0,
                "volatility": 1.0,
                "walkforward_stability": 1.0,
            })
            decision_breakdown["persona_council"] = {
                "persona_count": len(persona_breakdown),
                "majority_signal": majority_signal,
                "consensus_strength": consensus_strength,
                "persona_disagreement_index": persona_disagreement_index,
                "persona_weight_drift_score": persona_weight_drift_score,
                "persona_weights_applied": persona_weights_applied,
            }
            gate_fail_reasons = [
                name for name, passed in decision_breakdown["checks"].items() if not passed
            ]
            gate_passed = len(gate_fail_reasons) == 0
            decision_breakdown["signal_quality_gate_passed"] = gate_passed
            decision_breakdown["blocked_reasons"] = gate_fail_reasons
            if prediction == "Buy" and not gate_passed:
                prediction = "Hold"
            stop_loss = round(price * 0.95, 2) if price else None
            summary = (
                f"{symbol} rated {grade} ({grade_percent}%) — {prediction} bias active."
            )

            return {
                "symbol": symbol,
                "prediction": prediction,
                "stop_loss": stop_loss,
                "grade": grade,
                "grade_percent": grade_percent,
                "confidence": confidence,
                "persona_breakdown": persona_breakdown,
                "persona_weighted_grade": persona_weighted_grade,
                "persona_consensus_score": persona_consensus_score,
                "persona_disagreement_index": persona_disagreement_index,
                "majority_signal": majority_signal,
                "consensus_strength": consensus_strength,
                "predicted_win_probability": predicted_win_probability,
                "timeframe_alignment_score": timeframe_alignment_score,
                "signal_quality_gate_passed": gate_passed,
                "adaptive_weight_score": adaptive_weight_score,
                "learning_confidence_adjustment": learning_confidence_adjustment,
                "regime_context": adaptive_payload.get("regime_context", regime_context),
                "entry_confirmation_score": entry_confirmation_score,
                "early_follow_through_score": early_follow_through_score,
                "deterioration_score": deterioration_score,
                "setup_clarity_penalty": setup_clarity_penalty,
                "entry_followthrough_penalty": entry_followthrough_penalty,
                "entry_failure_risk_penalty": entry_failure_risk_penalty,
                "entry_quality_penalty": entry_quality_penalty,
                "weak_process_penalty": weak_process_penalty,
                "promotion_quality_penalty": promotion_quality_penalty,
                "release_readiness_score": release_readiness_score,
                "promotion_reason_summary": promotion_reason_summary,
                "entry_discipline_score": entry_discipline_score,
                "entry_release_gate_score": entry_release_gate_score,
                "entry_release_confidence": entry_release_confidence,
                "context_toxicity_penalty": context_toxicity_penalty,
                "entry_holdback_reason": entry_holdback_reason,
                "entry_refinement_reason": entry_refinement_reason,
                "promotion_path_decision": promotion_path_decision,
                "decision_breakdown": decision_breakdown,
                "summary": summary,
            }
        except Exception as e:
            print(f"[RankingEngine] evaluate_symbol() error: {e}")
            return {
                "symbol": symbol,
                "prediction": "Neutral",
                "stop_loss": None,
                "grade": "C",
                "grade_percent": 50,
                "confidence": 50,
                "persona_breakdown": [],
                "persona_weighted_grade": 50.0,
                "persona_consensus_score": 0.0,
                "persona_disagreement_index": 100.0,
                "majority_signal": "Hold",
                "consensus_strength": 0.0,
                "predicted_win_probability": 0.4,
                "timeframe_alignment_score": 50.0,
                "signal_quality_gate_passed": False,
                "adaptive_weight_score": 100.0,
                "learning_confidence_adjustment": 0.0,
                "regime_context": "neutral",
                "entry_confirmation_score": 50.0,
                "early_follow_through_score": 50.0,
                "deterioration_score": 50.0,
                "setup_clarity_penalty": 0.0,
                "entry_followthrough_penalty": 0.0,
                "entry_failure_risk_penalty": 0.0,
                "entry_quality_penalty": 0.0,
                "weak_process_penalty": 0.0,
                "promotion_quality_penalty": 0.0,
                "release_readiness_score": 0.0,
                "promotion_reason_summary": "quality_holdback_unknown",
                "entry_discipline_score": 0.0,
                "entry_release_gate_score": 0.0,
                "entry_release_confidence": 0.0,
                "context_toxicity_penalty": 0.0,
                "entry_holdback_reason": "none",
                "entry_refinement_reason": "entry_refinement_not_set",
                "promotion_path_decision": "paper_safe_or_secondary",
                "decision_breakdown": {
                    "checks": {},
                    "values": {},
                    "thresholds": {},
                    "adaptive_weights_applied": {
                        "confidence": 1.0,
                        "timeframe_alignment": 1.0,
                        "volatility": 1.0,
                        "walkforward_stability": 1.0,
                    },
                    "signal_quality_gate_passed": False,
                    "blocked_reasons": ["ranking_engine_exception"],
                },
                "summary": f"{symbol} evaluation failed — fallback mode active.",
            }
