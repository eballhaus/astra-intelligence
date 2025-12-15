# -*- coding: utf-8 -*-
"""
Astra Brain — Contextual Insight Engine (Phase 7)
-------------------------------------------------
Generates short natural-language market insights from agent data.
"""

import random
import datetime

def contextual_insight():
    """Return a simulated insight summary."""
    sentiments = ["Bullish", "Bearish", "Neutral"]
    focus = ["momentum", "volume", "risk", "psychology", "catalyst"]
    insight = f"Market mood is {random.choice(sentiments)}, driven by {random.choice(focus)} factors."
    return {
        "timestamp": datetime.datetime.utcnow().isoformat(timespec='seconds'),
        "insight": insight
    }
