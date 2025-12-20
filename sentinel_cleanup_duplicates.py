#!/usr/bin/env python3
import os
import re
import shutil

TARGET_DIRS = ["engine", "core", "ui"]
FUNC_PATTERN = re.compile(r'^\s*def\s+(\w+)\s*\(')

def find_python_files():
    for root_dir in TARGET_DIRS:
        for root, _, files in os.walk(root_dir):
            for file in files:
                if file.endswith(".py") and not file.endswith(".bak"):
                    yield os.path.join(root, file)

def clean_duplicates(file_path):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    func_lines = [i for i, line in enumerate(lines) if FUNC_PATTERN.match(line)]
    if len(func_lines) <= 1:
        return False  # no duplicates

    seen = set()
    new_lines = []
    skip = False
    current_func = None

    for i, line in enumerate(lines):
        match = FUNC_PATTERN.match(line)
        if match:
            func_name = match.group(1)
            if func_name in seen:
                print(f"[SKIP] Duplicate function '{func_name}' found in {file_path}, removing later definitions.")
                skip = True
                current_func = func_name
                continue
            else:
                seen.add(func_name)
                skip = False
        elif skip and re.match(r'^\s*def\s+\w+\s*\(', line):
            skip = False  # reached next function

        if not skip:
            new_lines.append(line)

    # backup before overwriting
    backup_path = file_path + ".sentinel.bak"
    shutil.copy(file_path, backup_path)
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"[CLEANED] {file_path} → backup saved as {backup_path}")
    return True

if __name__ == "__main__":
    print("🔍 [Sentinel] Scanning for duplicate function definitions...\n")
    count = 0
    for py_file in find_python_files():
        if clean_duplicates(py_file):
            count += 1
    print(f"\n✅ Sentinel cleanup complete. {count} files cleaned.")
