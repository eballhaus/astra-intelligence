# ================================================================
# Astra DevTools — Syntax Validator
# ================================================================

import os
import ast

ASTRA_ROOT = "astra_modules"


def check_file(path):
    """Parse file with ast to detect syntax errors."""
    try:
        with open(path, "r") as f:
            code = f.read()
        ast.parse(code, filename=path)
        return None
    except SyntaxError as e:
        return f"❌ SyntaxError in {path}: {e}"
    except Exception as e:
        return f"❌ File Error in {path}: {e}"


def syntax_check_project():
    """Walk entire Astra project to detect syntax issues."""
    errors = []

    for root, _, files in os.walk(ASTRA_ROOT):
        for fname in files:
            if fname.endswith(".py"):
                full = os.path.join(root, fname)
                err = check_file(full)
                if err:
                    errors.append(err)
                    print(err)

    if not errors:
        print("✔ All Python files passed syntax validation.")

    return errors
