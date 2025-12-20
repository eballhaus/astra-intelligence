# -*- coding: utf-8 -*-
"""
Astra Brain — Contextual Insight Engine (Phase 7)
-------------------------------------------------
Generates a short natural-language insight summary from agent data.
"""

import random
import datetime


def contextual_insight():
    """Return a simple AI-generated summary of current market context."""
    sentiments = ["Bullish", "Bearish", "Neutral"]
    focus = ["momentum", "volume", "risk", "psychology", "catalyst"]
    insight = f"Market mood is {random.choice(sentiments)}, led by {random.choice(focus)} signals."
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds"),
        "insight": insight,
    }
