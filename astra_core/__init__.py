
# === Compatibility bridge for legacy modules ===
import sys, os, importlib.util
legacy_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../astra_modules_backup_20251130_1720"))
if os.path.exists(legacy_path) and "astra_modules" not in sys.modules:
    sys.path.append(legacy_path)
    spec = importlib.util.spec_from_file_location("astra_modules", os.path.join(legacy_path, "__init__.py")) if os.path.exists(os.path.join(legacy_path, "__init__.py")) else None
    astra_modules = importlib.util.module_from_spec(spec) if spec else None
    if spec and astra_modules:
        sys.modules["astra_modules"] = astra_modules
        print("[AstraCompat] ✅ 'astra_modules' alias registered for astra_modules_backup_20251130_1720")
