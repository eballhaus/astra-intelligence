"""
Astra Legacy Module Alias Bridge
Automatically maps 'astra_modules' imports to
'astra_modules_backup_20251130_1720' to support legacy systems.
"""
import sys, os, importlib.util

legacy_path = os.path.abspath("astra_modules_backup_20251130_1720")
if os.path.exists(legacy_path) and "astra_modules" not in sys.modules:
    sys.path.append(legacy_path)
    spec_path = os.path.join(legacy_path, "__init__.py")
    spec = importlib.util.spec_from_file_location("astra_modules", spec_path) if os.path.exists(spec_path) else None
    astra_modules = importlib.util.module_from_spec(spec) if spec else None
    if spec and astra_modules:
        sys.modules["astra_modules"] = astra_modules
        print("[AstraCompat] ✅ 'astra_modules' alias registered globally.")
