"""Canonical early runtime environment loading for Astra.

The loader is intentionally small and side-effect limited: it reads the
repository-root .env once, never overrides explicitly exported variables, and
never exposes values through diagnostics.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPOSITORY_ROOT / ".env"
SUPPORTED_FMP_KEY_NAMES = (
    "FMP_API_KEY",
    "FINANCIALMODELINGPREP_API_KEY",
    "FINANCIAL_MODELING_PREP_API_KEY",
    "FINANCIAL_MODELING_PREP_KEY",
)

_LOADED = False


def load_runtime_environment() -> dict[str, object]:
    """Load Astra's local environment without replacing exported variables."""
    global _LOADED
    if not _LOADED:
        load_dotenv(dotenv_path=ENV_PATH, override=False)
        _LOADED = True
    return {
        "repository_root": str(REPOSITORY_ROOT),
        "env_path_absolute": str(ENV_PATH),
        "env_file_present": ENV_PATH.is_file(),
        "loaded_before_provider_initialization": True,
        "exported_environment_precedence_preserved": True,
    }


def resolve_fmp_key() -> tuple[str, str]:
    """Return the first supported FMP credential and its source name."""
    load_runtime_environment()
    for name in SUPPORTED_FMP_KEY_NAMES:
        value = str(os.getenv(name, "") or "").strip()
        if value and not value.startswith("YOUR_"):
            if name != "FMP_API_KEY" and not str(os.getenv("FMP_API_KEY", "") or "").strip():
                os.environ["FMP_API_KEY"] = value
            return value, name
    return "", "missing"


load_runtime_environment()
