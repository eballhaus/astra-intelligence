"""
forecast_engine.py
──────────────────────────────────────────────────────────────────
Unified forecasting interface for Astra Intelligence.
Integrates base forecasting models with EnsembleEngine for multi-agent predictions.

Phase 2 Upgrade:
- Added EnsembleEngine integration
- Standardized output format across all prediction methods
- Enhanced error handling and data validation
- Configurable confidence thresholds and scaling constants
- Defensive logging and type safety
- Future-proof post-hook support

Module Version: v3.0.1
Model Version: v3 (Hybrid Ensemble)
Author: Astra Intelligence Team
"""

import math
import numbers
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import pandas as pd

# ──────────────────────────────────────────────
# Core Forecast Import
# ──────────────────────────────────────────────
try:
    from .forecast_model import get_forecast
except ImportError:
    print(
        "[ForecastEngine] WARNING: forecast_model.get_forecast not found. Using fallback."
    )

    def get_forecast(symbol: str) -> Dict[str, Any]:
        """Fallback forecast when base model unavailable."""
        return {"predicted_change": 0.0, "confidence": 0.5, "model": "fallback"}


# ──────────────────────────────────────────────
# Ensemble Integration (Phase 2)
# ──────────────────────────────────────────────
try:
    from .ensemble_engine import EnsembleEngine
except ImportError:
    EnsembleEngine = None
    print("[ForecastEngine] EnsembleEngine not available. Running in base mode only.")


# ──────────────────────────────────────────────
# Type Aliases for Better Clarity
# ──────────────────────────────────────────────
AgentFunction = Callable[[str, Dict[str, Any]], float]
LogFunction = Callable[[str, str], None]


class ForecastEngine:
    """
    Unified forecasting interface for Astra Intelligence.

    Provides two prediction modes:
    1. Base prediction: Uses traditional forecast model
    2. Ensemble prediction: Multi-agent scoring with confidence aggregation

    Both methods return standardized dictionary format for consistent
    integration with dashboard, learning systems, and API endpoints.
    """

    # ──────────────────────────────────────────────
    # Configuration Constants
    # ──────────────────────────────────────────────
    BULLISH_THRESHOLD = 0.2
    BEARISH_THRESHOLD = -0.2
    ENSEMBLE_PCT_SCALE = 10.0  # maps [-1,1] → [-10%,+10%]
    ENSEMBLE_PRICE_MULT = 0.1  # multiplier for price projection
    REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}

    def __init__(self, log_callback: Optional[LogFunction] = None):
        """
        Initialize ForecastEngine with optional ensemble support.

        Args:
            log_callback: Optional logging function with signature (message, level).
                          If None, uses default print-based logging.
        """
        self.model_name = "Astra Forecast Hybrid v3"
        self.ensemble = None
        self.ensemble_ready = False
        self._post_hook = None

        # Setup logging
        self.log = log_callback or self._default_log

        # Configure thresholds (can be overridden externally)
        self.thresholds = {
            "bullish": self.BULLISH_THRESHOLD,
            "bearish": self.BEARISH_THRESHOLD,
        }

        # Initialize ensemble if available
        if EnsembleEngine is not None:
            try:
                null_agents = self._create_null_agents()
                self.ensemble = EnsembleEngine(null_agents)
                self.log("EnsembleEngine initialized with null agents.", "INFO")
                self.log("Call inject_agents() to activate real scoring.", "INFO")
            except Exception as e:
                self.log(f"EnsembleEngine init failed: {e}", "ERROR")
                self.ensemble = None

    # ──────────────────────────────────────────────
    # Logging
    # ──────────────────────────────────────────────
    def _default_log(self, message: str, level: str = "INFO") -> None:
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix}[ForecastEngine] {message}")

    # ──────────────────────────────────────────────
    # Agent Handling
    # ──────────────────────────────────────────────
    def _create_null_agents(self) -> Dict[str, AgentFunction]:
        def _null_agent(symbol: str, data: Dict[str, Any]) -> float:
            return 0.0

        names = ["momentum", "technical", "volume",
                 "risk", "psychology", "neural"]
        return {n: _null_agent for n in names}

    def inject_agents(self, real_agents: Dict[str, AgentFunction]) -> bool:
        if self.ensemble is None:
            self.log("Cannot inject agents: EnsembleEngine not available.", "ERROR")
            return False
        try:
            self.ensemble.agents = real_agents
            self.ensemble_ready = True
            self.log(
                f"Injected {len(real_agents)} real agents. Ensemble active.", "INFO"
            )
            return True
        except Exception as e:
            self.log(f"Agent injection failed: {e}", "ERROR")
            return False

    # ──────────────────────────────────────────────
    # Data Validation & Helpers
    # ──────────────────────────────────────────────
    def _validate_dataframe(self, df: Optional[pd.DataFrame], symbol: str) -> bool:
        if df is None or df.empty:
            return False
        missing_cols = self.REQUIRED_COLUMNS - set(df.columns)
        if missing_cols:
            self.log(
                f"{symbol}: Missing required columns: {missing_cols}", "WARNING")
            return False
        return True

    def _extract_current_price(self, df: pd.DataFrame, symbol: str) -> Optional[float]:
        try:
            last_close = df["close"].iloc[-1]
            if pd.isna(last_close) or not isinstance(last_close, numbers.Number):
                self.log(
                    f"{symbol}: Invalid close price (NaN/non-numeric).", "WARNING")
                return None
            price = float(last_close)
            if price <= 0 or price > 1_000_000:
                self.log(
                    f"{symbol}: Price {price} outside valid range.", "WARNING")
                return None
            return price
        except Exception as e:
            self.log(f"{symbol}: Price extraction failed: {e}", "ERROR")
            return None

    def _calculate_trend(self, score: float) -> str:
        if score > self.thresholds["bullish"]:
            return "bullish"
        elif score < self.thresholds["bearish"]:
            return "bearish"
        else:
            return "neutral"

    # ──────────────────────────────────────────────
    # Forecast Methods
    # ──────────────────────────────────────────────
    def predict(self, symbol: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        try:
            base = get_forecast(symbol)
            change_pct = base.get("predicted_change", 0.0)
            raw_conf = base.get("confidence", 0.5)
            if raw_conf < 0 or raw_conf > 1:
                self.log(
                    f"{symbol}: Confidence {raw_conf} out of range, clamping.",
                    "WARNING",
                )
            confidence = max(0.0, min(1.0, raw_conf))

            current_price, predicted_price = None, None
            if self._validate_dataframe(df, symbol):
                current_price = self._extract_current_price(df, symbol)
                if current_price is not None:
                    predicted_price = current_price * (1 + (change_pct / 100))

            trend = self._calculate_trend(change_pct / 100)
            result = {
                "symbol": symbol.upper(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "predicted_price": predicted_price,
                "current_price": current_price,
                "predicted_change": change_pct,
                "confidence": confidence,
                "trend": trend,
                "model": self.model_name,
                "source": "base_forecast",
            }
            if self._post_hook:
                self._post_hook(result)
            return result
        except Exception as e:
            self.log(f"Base forecast error for {symbol}: {e}", "ERROR")
            return self._error_response(symbol, "base_forecast")

    def predict_ensemble(
        self, symbol: str, df: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        if self.ensemble is None or not self.ensemble_ready:
            self.log(
                f"{symbol}: Ensemble not ready — using base forecast.", "INFO")
            return self.predict(symbol, df)
        try:
            data = df.to_dict() if self._validate_dataframe(df, symbol) else {}
            result = self.ensemble.score(symbol, data)

            ensemble_score = result.get("ensemble_score", 0.0)
            if math.isnan(ensemble_score) or math.isinf(ensemble_score):
                self.log(
                    f"{symbol}: Invalid ensemble score ({ensemble_score}), resetting.",
                    "WARNING",
                )
                ensemble_score = 0.0

            raw_conf = result.get("confidence", 0.5)
            if raw_conf < 0 or raw_conf > 1:
                self.log(
                    f"{symbol}: Confidence {raw_conf} out of range, clamping.",
                    "WARNING",
                )
            confidence = max(0.0, min(1.0, raw_conf))

            trend = self._calculate_trend(ensemble_score)
            predicted_change = ensemble_score * self.ENSEMBLE_PCT_SCALE

            current_price, predicted_price = None, None
            if self._validate_dataframe(df, symbol):
                current_price = self._extract_current_price(df, symbol)
                if current_price is not None:
                    predicted_price = current_price * (
                        1 + ensemble_score * self.ENSEMBLE_PRICE_MULT
                    )

            output = {
                "symbol": symbol.upper(),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "predicted_price": predicted_price,
                "current_price": current_price,
                "predicted_change": round(predicted_change, 3),
                "confidence": round(confidence, 3),
                "trend": trend,
                "ensemble_score": round(ensemble_score, 3),
                "agent_scores": {
                    k: round(v, 3) for k, v in result.get("scores", {}).items()
                },
                "model": self.model_name,
                "source": "ensemble",
            }
            if self._post_hook:
                self._post_hook(output)
            return output
        except Exception as e:
            self.log(f"Ensemble forecast failed for {symbol}: {e}", "ERROR")
            return self.predict(symbol, df)

    # ──────────────────────────────────────────────
    # Utilities
    # ──────────────────────────────────────────────
    def _error_response(self, symbol: str, source: str) -> Dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "predicted_price": None,
            "current_price": None,
            "predicted_change": 0.0,
            "confidence": 0.0,
            "trend": "neutral",
            "model": self.model_name,
            "source": f"{source}_error",
        }

    def register_hook(self, fn: Callable[[Dict[str, Any]], None]) -> None:
        """Registers a post-prediction callback for learning/Guardian pipelines."""
        self._post_hook = fn

    def get_status(self) -> Dict[str, Any]:
        return {
            "model": self.model_name,
            "ensemble_available": self.ensemble is not None,
            "ensemble_ready": self.ensemble_ready,
            "thresholds": self.thresholds,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def __repr__(self):
        return f"<ForecastEngine model={self.model_name}, ensemble_ready={self.ensemble_ready}>"


# ──────────────────────────────────────────────
# Module-Level Convenience
# ──────────────────────────────────────────────
_global_engine: Optional[ForecastEngine] = None


def get_engine() -> ForecastEngine:
    global _global_engine
    if _global_engine is None:
        _global_engine = ForecastEngine()
    return _global_engine


def quick_forecast(symbol: str, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    return get_engine().predict(symbol, df)


def quick_ensemble_forecast(
    symbol: str, df: Optional[pd.DataFrame] = None
) -> Dict[str, Any]:
    return get_engine().predict_ensemble(symbol, df)
