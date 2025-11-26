"""
learning_store.py — Astra Intelligence (Phase-50 Rebuild)
Safe memory storage for learning data
"""

import json
import os
import time

DEFAULT_FILE = "learning_memory.json"

class LearningStore:
    def __init__(self, file_path=DEFAULT_FILE, max_memory_days=90):
        self.file_path = file_path
        self.max_memory_days = max_memory_days
        self.data = {"records": []}  # ensure dict structure

        # load existing memory safely
        self._load()
        self._cleanup()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict) and "records" in loaded:
                        self.data = loaded
                    else:
                        self.data = {"records": []}
            except Exception:
                self.data = {"records": []}
        else:
            self.data = {"records": []}

    def _cleanup(self):
        """Remove old records beyond max_memory_days."""
        now = time.time()
        cutoff = now - self.max_memory_days * 86400
        if isinstance(self.data, dict) and "records" in self.data:
            self.data["records"] = [r for r in self.data["records"]
                                    if r.get("timestamp", now) >= cutoff]

    def add_record(self, record):
        """Add a new learning record."""
        record["timestamp"] = time.time()
        if isinstance(self.data, dict) and "records" in self.data:
            self.data["records"].append(record)
        self._cleanup()
        self._save()

    def get_records(self):
        if isinstance(self.data, dict) and "records" in self.data:
            return self.data["records"]
        return []

    def _save(self):
        try:
            with open(self.file_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass
