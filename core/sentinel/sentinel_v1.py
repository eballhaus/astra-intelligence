import os
import json
from datetime import datetime

ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
INDEX_PATH = os.path.join(ASTRA_ROOT, 'state', 'ASTRA_LIVE_INDEX.json')

EXCLUDED_DIRS = {".git", "__pycache__", ".streamlit", ".idea", ".vscode", "venv", "archive", "backups", "legacy_backups", "_quarantine"}

def is_python_package(path: str) -> bool:
    return os.path.isfile(os.path.join(path, '__init__.py'))

def scan_repo(root_dir: str) -> dict:
    structure = {
        'timestamp': datetime.now().isoformat(),
        'root': root_dir,
        'subsystems': {},
        'duplicates': [],
        'orphans': [],
    }
    seen_files = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        rel_path = os.path.relpath(dirpath, root_dir)
        subsystem = rel_path.split(os.sep)[0] if rel_path != '.' else 'root'
        if subsystem not in structure['subsystems']:
            structure['subsystems'][subsystem] = {'packages': [], 'modules': [], 'non_py_files': []}
        if is_python_package(dirpath):
            structure['subsystems'][subsystem]['packages'].append(rel_path)
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            if f.endswith('.py'):
                rel_file = os.path.relpath(full_path, root_dir)
                if f not in seen_files:
                    seen_files[f] = rel_file
                else:
                    structure['duplicates'].append({
                        'filename': f,
                        'existing': seen_files[f],
                        'duplicate': rel_file
                    })
                structure['subsystems'][subsystem]['modules'].append(rel_file)
            else:
                structure['subsystems'][subsystem]['non_py_files'].append(f)
    return structure

def write_index(index_data: dict, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, indent=4)

def main():
    print("\\n🔍 Running ASTRA SENTINEL v1 — Structural Scan...\\n")
    index = scan_repo(ASTRA_ROOT)
    write_index(index, INDEX_PATH)
    print(f"✅ Astra Live Index written to: {INDEX_PATH}")
    print(f"   Timestamp: {index['timestamp']}")
    print(f"   Subsystems scanned: {len(index['subsystems'])}")
    print(f"   Duplicates found: {len(index['duplicates'])}\\n")

if __name__ == '__main__':
    main()
