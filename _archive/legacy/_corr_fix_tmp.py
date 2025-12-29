def _compute_correlation_weights(self):
    """
    Compute new correlation weights based on replay buffer content.
    Robustly handles nested, dict, and inconsistent numeric data.
    """
    samples = self.buffer.sample(100)
    if not samples:
        print("[Astra LearningEngine] No data available to compute correlations.")
        return self.state.get("weights", np.ones(10))

    try:
        flat_states = []
        for s in samples:
            st = s.get("state")

            # --- Handle dict states like {"feature": 0.1} ---
            if isinstance(st, dict):
                st = list(st.values())

            # --- Handle wrapped single-element lists ---
            if isinstance(st, (list, tuple)) and len(st) == 1 and isinstance(st[0], (list, tuple)):
                st = st[0]

            # --- Force flattening into numeric vector ---
            try:
                flat_states.append(np.ravel(st).astype(float))
            except Exception:
                flat_states.append(np.array([0.0]))

        # Build consistent numeric arrays
        X = np.vstack(flat_states)
        y = np.array([s.get("reward", 0.0) for s in samples], dtype=float)

        corr = np.corrcoef(X.T, y)[-1, :-1]
        corr = np.nan_to_num(corr)

        corr = corr / (np.linalg.norm(corr) + 1e-9)
        print("[Astra LearningEngine] ✅ Correlation weights computed successfully.")
        return corr

    except Exception as e:
        print(f"[Astra LearningEngine] ❌ Correlation computation failed (robust): {e}")
        traceback.print_exc()
        return self.state.get("weights", np.ones(10))
