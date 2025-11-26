# ================================================================
# Astra DevTools — AST Structural Analyzer
# ================================================================

import os
import ast

ASTRA_ROOT = "astra_modules"


class ASTValidator(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.issues = []

    def visit_FunctionDef(self, node):
        if not node.body:
            self.issues.append(f"⚠ Empty function '{node.name}' in {self.path}")
        if isinstance(node.body[0], ast.Pass):
            self.issues.append(f"⚠ Function '{node.name}' contains only 'pass' in {self.path}")
        self.generic_visit(node)

    def visit_Import(self, node):
        if not node.names:
            self.issues.append(f"⚠ Empty import in {self.path}")
        self.generic_visit(node)

    def visit_Assign(self, node):
        # If variable assigned None suspiciously
        if isinstance(node.value, ast.Constant) and node.value.value is None:
            self.issues.append(f"⚠ Variable assigned None in {self.path} line {node.lineno}")
        self.generic_visit(node)


def validate_file(path):
    try:
        with open(path, "r") as f:
            tree = ast.parse(f.read(), filename=path)
    except Exception as e:
        return [f"❌ AST Parse Error in {path}: {e}"]

    validator = ASTValidator(path)
    validator.visit(tree)
    return validator.issues


def run_ast_validation():
    issues = []

    for root, _, files in os.walk(ASTRA_ROOT):
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                problems = validate_file(fpath)
                for p in problems:
                    print(p)
                issues.extend(problems)

    if not issues:
        print("✔ AST structural validation passed.")

    return issues
