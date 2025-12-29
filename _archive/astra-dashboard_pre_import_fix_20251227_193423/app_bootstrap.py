"""
AstraBootstrap - Central import path initializer for Astra Intelligence
This ensures that all key project directories are added to sys.path
no matter how Streamlit executes the modules.
"""

import os
import sys

# Define the project root and submodule paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(PROJECT_ROOT, "engine")
CORE_PATH = os.path.join(PROJECT_ROOT, "core")
UI_PATH = os.path.join(PROJECT_ROOT, "ui")
ASTRA_MODULES_PATH = os.path.join(PROJECT_ROOT, "astra_modules")

# Insert all paths if missing
for path in [PROJECT_ROOT, ENGINE_PATH, CORE_PATH, UI_PATH, ASTRA_MODULES_PATH]:
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)

print(f"[AstraBootstrap] ✅ sys.path initialized:")
for i, path in enumerate(sys.path[:6]):
    print(f"  {i}: {path}")

# Optional: Change working directory (important for Streamlit)
if os.getcwd() != PROJECT_ROOT:
    os.chdir(PROJECT_ROOT)
    print(f"[AstraBootstrap] cwd set to: {PROJECT_ROOT}")
