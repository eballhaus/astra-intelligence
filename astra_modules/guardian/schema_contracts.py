"""
schema_contracts.py — Guardian 3.0
Defines official Phase-50 schemas for SmartScan, HybridScan, and Ranking Engine.
Used by pipeline_sanitizer and auto_repair to validate and repair output.
"""

SMARTSCAN_SCHEMA = {
    "symbol": str,
    "df": "DataFrame",
    "metrics": {
        "buy_score": float,
        "trend_slope": float,
        "volatility": float,
        "price": float,
        "confidence": int,
    },
}

HYBRIDSCAN_SCHEMA = {
    "symbol": str,
    "df": "DataFrame",
    "hybrid_score": float,
    "stability": float,
    "safety_score": float,
    "vol_conf": float,
    "volatility": float,
    "last_close": float,
    "summary_text": str,
    "forecast": str,
    "sparkline": list,
}

RANKING_SCHEMA = {
    "ticker": str,
    "final_score": float,
    "price": float,
    "buy_score": float,
    "confidence": float,
    "safety_score": float,
    "summary_text": str,
    "forecast": str,
    "sparkline": list,
}
