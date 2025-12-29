"""
Astra Intelligence - Replay Buffer Seeder
-----------------------------------------
Seeds the ReplayBuffer with clean, numeric mock data and runs a
manual LearningEngine training cycle for validation.

Safe for repeated use — normalizes existing data, cleans dict states,
and ensures compatibility with all Astra Learning v7.5+ components.
"""

import numpy as np
from astra_dashboard.learning.replay_buffer import ReplayBuffer
from astra_dashboard.learning.learning_engine import train_learning_engine


def _normalize_state(st):
    """Convert dicts, nested lists, or scalars into clean numeric arrays."""
    if isinstance(st, dict):
        # Flatten dict values
        st = list(st.values())

    if isinstance(st, (list, tuple)):
        cleaned = []
        for elem in st:
            if isinstance(elem, dict):
                cleaned.extend(list(elem.values()))
            elif isinstance(elem, (list, tuple)):
                cleaned.extend([float(x) if isinstance(x, (int, float)) else 0.0 for x in elem])
            elif isinstance(elem, (int, float)):
                cleaned.append(float(elem))
            else:
                cleaned.append(0.0)
        st = cleaned
    elif not isinstance(st, np.ndarray):
        # Handle scalars or other weird types
        st = [float(st) if isinstance(st, (int, float)) else 0.0]

    return np.array(st, dtype=float)


# === 1️⃣ Initialize buffer ===
buffer = ReplayBuffer()

# === 2️⃣ Normalize any existing states in buffer ===
if hasattr(buffer, "buffer"):
    for sample in buffer.buffer:
        sample["state"] = _normalize_state(sample.get("state", []))

# === 3️⃣ Add fresh mock experiences ===
for i in range(5):
    state_vec = np.array([float(i), float(i) * 0.1, float(i) * 0.05])
    buffer.add(
        state=state_vec,
        prediction=float(0.5 if i % 2 == 0 else -0.3),
        reward=float(0.1 * i),
        symbol=f"TICKER{i}",
        confidence=float(0.8),
    )

print(f"🧩 Seeded {len(buffer.buffer)} normalized numeric experiences.")

# === 4️⃣ Run a full learning cycle ===
train_learning_engine()
print("✅ Manual training cycle complete.")
