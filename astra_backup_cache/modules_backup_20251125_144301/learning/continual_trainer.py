"""
continual_trainer.py — Phase-90 Upgrade
Reads from ReplayBuffer and trains the MicroNeuralModel.
Supports hybrid supervised learning from PnL outcomes.
"""

from typing import List, Dict, Any


class ContinualTrainer:
    def __init__(self, neural_agent, replay_buffer):
        """
        neural_agent: NeuralAgent instance
        replay_buffer: ReplayBuffer instance
        """
        self.agent = neural_agent
        self.buffer = replay_buffer

    # ==================================================================
    # INTERNAL: CLEAN & VALIDATE TRAINING SAMPLES
    # ==================================================================
    def _extract_training_samples(self, batch) -> List[Dict[str, Any]]:
        """
        Converts replay buffer entries into valid training samples.

        ReplayBuffer entries look like:
        {
            "state": { "features": [...] },
            "prediction": float,
            "outcome": float   # PnL
        }
        """
        samples = []

        for exp in batch:
            try:
                if not isinstance(exp, dict):
                    continue

                state = exp.get("state", {})
                features = state.get("features")
                outcome = exp.get("outcome", None)

                # Skip malformed entries
                if features is None or outcome is None:
                    continue

                # Binary label for logistic model
                label = 1 if float(outcome) > 0 else 0

                samples.append({
                    "features": features,
                    "label": label
                })

            except Exception:
                # Skip any corrupted record safely
                continue

        return samples

    # ==================================================================
    # TRAIN STEP
    # ==================================================================
    def train_step(self, batch: List[dict]):
        """
        Perform one training pass over a sample batch.
        """

        try:
            if not batch:
                return "No data to train on."

            samples = self._extract_training_samples(batch)
            if not samples:
                return "No valid samples with features/outcomes."

            model = self.agent.model

            trained = 0
            for s in samples:
                features = s["features"]
                label = s["label"]

                # Train micro neural model
                model.train_step(features, label)
                trained += 1

            return f"Trained on {trained} samples."

        except Exception as e:
            return f"[Trainer] Error during train_step: {e}"

    # ==================================================================
    # PUBLIC TRAIN METHOD
    # ==================================================================
    def train(self, batch_size: int = 64):
        """
        Main training loop. Pulls a sample batch from ReplayBuffer
        and calls train_step().
        """
        try:
            batch = self.buffer.sample(batch_size)
            return self.train_step(batch)

        except Exception as e:
            return f"[Trainer] Error getting batch: {e}"
