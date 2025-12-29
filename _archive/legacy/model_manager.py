"""
model_manager.py — Astra Learning Model Manager
Handles safe saving/loading of model weights and metadata.
"""

import os
import json
from datetime import datetime
from core.guardian.guardian_v7 import GuardianV7

guardian = GuardianV7()

MODEL_DIR = "state/models"
METADATA_FILE = os.path.join(MODEL_DIR, "model_metadata.json")


class ModelManager:
    def __init__(self):
        os.makedirs(MODEL_DIR, exist_ok=True)
        self.metadata = self._load_metadata()

    def _load_metadata(self):
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                guardian.error(f"Failed to load model metadata: {e}")
        return {}

    def save_model(self, model_name: str, model_obj, metrics: dict = None):
        """Safely save model weights and metadata."""
        try:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            model_path = os.path.join(MODEL_DIR, f"{model_name}_{timestamp}.pth")

            # Framework-agnostic save
            if hasattr(model_obj, "state_dict"):
                import torch
                torch.save(model_obj.state_dict(), model_path)
            else:
                with open(model_path, "wb") as f:
                    f.write(model_obj)

            self.metadata[model_name] = {
                "last_saved": timestamp,
                "path": model_path,
                "metrics": metrics or {},
            }
            with open(METADATA_FILE, "w") as f:
                json.dump(self.metadata, f, indent=2)

            guardian.info(f"✅ Model saved: {model_name} ({timestamp})")
        except Exception as e:
            guardian.error(f"Error saving model {model_name}: {e}")

    def load_model(self, model_name: str, model_obj=None):
        """Safely load model weights into an existing model object."""
        try:
            info = self.metadata.get(model_name)
            if not info:
                guardian.warn(f"No metadata found for model '{model_name}'.")
                return None
            path = info["path"]
            if not os.path.exists(path):
                guardian.warn(f"Model file not found: {path}")
                return None

            if model_obj and hasattr(model_obj, "load_state_dict"):
                import torch
                model_obj.load_state_dict(torch.load(path))
                guardian.info(f"✅ Model '{model_name}' loaded successfully.")
                return model_obj
            else:
                with open(path, "rb") as f:
                    data = f.read()
                return data
        except Exception as e:
            guardian.error(f"Error loading model {model_name}: {e}")
            return None
