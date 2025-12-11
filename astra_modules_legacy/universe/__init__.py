"""
universe — Phase-90
-------------------
Handles Astra Intelligence market universe management.

This module initializes the Universe subsystem and provides
a safe import path for UniverseBuilder and related tools.
"""

from astra_core.universe.universe_builder import build_universe

__all__ = ["build_universe"]
