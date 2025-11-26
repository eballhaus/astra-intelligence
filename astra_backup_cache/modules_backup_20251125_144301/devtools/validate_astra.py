# ========================================================================
# Astra Intelligence — Master Validation Suite (DevTools Core)
# ========================================================================
# This file orchestrates ALL diagnostics, repair tools, autodetection
# systems, performance profiling, import dependency maps, and UI validation.
# Each component lives inside astra_modules/devtools/ as a modular system.
#
# The goal: make Astra UNBREAKABLE, self-healing, and upgrade-resistant.
# ========================================================================

import os
import traceback

from astra_modules.devtools.file_scanner import scan_all_files
from astra_modules.devtools.import_graph import check_import_dependencies
from astra_modules.devtools.ast_checks import scan_for_syntax_and_structure_issues
from astra_modules.devtools.ui_checks import validate_ui_components
from astra_modules.devtools.schema_checks import validate_data_schema
from astra_modules.devtools.autofix import auto_fix_common_issues
from astra_modules.devtools.streamlit_sim import simulate_streamlit_launch
from astra_modules.devtools.profile_mode import run_performance_profile


# ========================================================================
# MASTER VALIDATOR
# ========================================================================

def run_full_validation():
    print("\n====================================================")
    print("🔍 ASTRA MASTER VALIDATION SYSTEM — STARTING")
    print("====================================================\n")

    results = {
        "file_scan": None,
        "import_graph": None,
        "syntax": None,
        "ui": None,
        "schema": None,
        "autofix": None,
        "simulate": None,
        "profile": None,
        "errors": []
    }

    try:
        print("📂 Scanning files...")
        results["file_scan"] = scan_all_files()

        print("🔗 Checking import graph...")
        results["import_graph"] = check_import_dependencies()

        print("🧠 Running AST + syntax validation...")
        results["syntax"] = scan_for_syntax_and_structure_issues()

        print("🎨 Validating UI components...")
        results["ui"] = validate_ui_components()

        print("📊 Validating schema & required fields...")
        results["schema"] = validate_data_schema()

        print("🛠  Running automatic fixes for common issues...")
        results["autofix"] = auto_fix_common_issues()

        print("🧪 Simulating Streamlit render...")
        results["simulate"] = simulate_streamlit_launch()

        print("🚀 Running performance profile...")
        results["profile"] = run_performance_profile()

        print("\n====================================================")
        print("✅ Astra Validation COMPLETE — see results above")
        print("====================================================\n")

    except Exception as e:
        tb = traceback.format_exc()
        results["errors"].append({"error": str(e), "traceback": tb})
        print("\n❌ VALIDATION FAILED — see traceback below:\n")
        print(tb)

    return results


# ========================================================================
# COMMAND-LINE SAFETY WRAPPER
# ========================================================================

if __name__ == "__main__":
    run_full_validation()
