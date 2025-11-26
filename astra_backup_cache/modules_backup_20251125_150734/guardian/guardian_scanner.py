import os

class DirectoryScanner:
    def __init__(self, base_path):
        self.base_path = base_path

    def scan_structure(self):
        issues = []
        for root, _, files in os.walk(self.base_path):
            for file in files:
                full_path = os.path.join(root, file)
                if os.path.getsize(full_path) == 0:
                    issues.append(os.path.relpath(full_path, self.base_path))
        for required in ["__init__.py", "guardian_v6.py"]:
            if not os.path.exists(os.path.join(self.base_path, required)):
                issues.append(required)
        return issues
