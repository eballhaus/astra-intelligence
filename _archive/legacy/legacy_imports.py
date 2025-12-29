import sys
from importlib import import_module

# Redirect any legacy guardian imports to the unified core version
sys.modules["astra_modules.guardian.guardian_core"] = import_module(
    "core.guardian.guardian_core"
)
sys.modules["astra_modules.guardian.guardian_sentinel"] = import_module(
    "core.guardian.guardian_sentinel"
)
sys.modules["astra_modules.guardian"] = import_module("core.guardian")
