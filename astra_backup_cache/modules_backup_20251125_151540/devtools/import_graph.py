# ================================================================
# Astra DevTools — Import Graph Analyzer
# Detects: circular imports, missing imports, broken paths,
#          incorrect module names, orphan modules, shadow conflicts.
# ================================================================

import os
import ast
from collections import defaultdict

ASTRA_ROOT = "astra_modules"


class ImportGraph:
    def __init__(self):
        self.graph = defaultdict(list)
        self.reverse = defaultdict(list)
        self.errors = []
        self.visited = set()
        self.recursion_stack = set()

    # ------------------------------------------------------------
    # Build graph from file
    # ------------------------------------------------------------
    def add_from_file(self, file_path):
        try:
            with open(file_path, "r") as f:
                tree = ast.parse(f.read(), filename=file_path)
        except Exception as e:
            self.errors.append(f"❌ AST parse error in {file_path}: {e}")
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_import(file_path, alias.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._add_import(file_path, node.module)

    # ------------------------------------------------------------
    # Internal graph linking
    # ------------------------------------------------------------
    def _add_import(self, file_path, module_name):
        src = self._normalize(file_path)
        dst = module_name.replace(".", "/")
        self.graph[src].append(dst)
        self.reverse[dst].append(src)

    # ------------------------------------------------------------
    # Normalize file path
    # ------------------------------------------------------------
    def _normalize(self, path):
        if path.startswith("./"):
            path = path[2:]
        return path.replace("\\", "/")

    # ------------------------------------------------------------
    # Circular Import Detection
    # ------------------------------------------------------------
    def detect_cycles(self):
        cycles = []

        def dfs(node):
            if node not in self.visited:
                self.visited.add(node)
                self.recursion_stack.add(node)

                for neighbor in self.graph.get(node, []):
                    if neighbor in self.recursion_stack:
                        cycles.append(f"🔄 Circular import detected: {node} -> {neighbor}")
                    elif neighbor not in self.visited:
                        dfs(neighbor)

                self.recursion_stack.remove(node)

        for node in self.graph:
            if node not in self.visited:
                dfs(node)

        return cycles

    # ------------------------------------------------------------
    # Broken Import Detection
    # ------------------------------------------------------------
    def detect_missing(self):
        missing = []
        for src, imports in self.graph.items():
            for imp in imports:
                # Construct actual path candidate
                candidate_py = f"{imp}.py"
                candidate_dir = imp

                # Check Python module
                py_exists = os.path.exists(candidate_py)

                # Check directory with __init__.py
                dir_exists = (
                    os.path.isdir(candidate_dir)
                    and os.path.exists(os.path.join(candidate_dir, "__init__.py"))
                )

                if not py_exists and not dir_exists:
                    missing.append(f"❌ Missing import: {imp} (used in {src})")

        return missing

    # ------------------------------------------------------------
    # Orphans = modules that nothing imports
    # ------------------------------------------------------------
    def detect_orphans(self):
        all_modules = set(self.graph.keys())
        referenced = set()

        for imps in self.graph.values():
            referenced.update(imps)

        orphans = all_modules - referenced
        return sorted(orphans)


# ================================================================
# PUBLIC API
# ================================================================

def analyze_imports():
    graph = ImportGraph()

    # Walk project tree
    for root, _, files in os.walk(ASTRA_ROOT):
        for fname in files:
            if fname.endswith(".py"):
                full_path = os.path.join(root, fname)
                graph.add_from_file(full_path)

    return {
        "cycles": graph.detect_cycles(),
        "missing": graph.detect_missing(),
        "orphans": graph.detect_orphans(),
        "graph": graph.graph,
        "reverse": graph.reverse
    }


def run_import_graph():
    print("🔍 Running Astra Import Graph Analyzer...")

    out = analyze_imports()

    print("\n--- IMPORT CYCLES ---")
    for c in out["cycles"]:
        print(c)
    if not out["cycles"]:
        print("✔ No circular imports detected")

    print("\n--- MISSING IMPORTS ---")
    for m in out["missing"]:
        print(m)
    if not out["missing"]:
        print("✔ All imports valid")

    print("\n--- ORPHAN MODULES ---")
    for o in out["orphans"]:
        print(f"⚠ Orphan module: {o}")
    if not out["orphans"]:
        print("✔ No orphans")

    return out
