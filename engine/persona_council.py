from __future__ import annotations

import math
from typing import Any


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _grade_letter(score: float) -> str:
    if score >= 85.0:
        return "A"
    if score >= 72.0:
        return "B"
    if score >= 60.0:
        return "C"
    if score >= 45.0:
        return "D"
    return "F"


def _persona_signal(score: float) -> str:
    if score >= 62.0:
        return "buy"
    if score <= 42.0:
        return "avoid"
    return "neutral"


class PersonaCouncil:
    """
    Persona Council V2 (conservative, deterministic).

    Produces multiple interpretable lenses:
    - technical
    - momentum
    - volume
    - psychology

    Output remains backward-compatible with current callers while adding
    explicit persona signal/reason fields for downstream explainability.
    """

    _BASE_PERSONAS = ("technical", "momentum", "volume", "psychology")

    def __init__(self, *args, **kwargs):
        self.max_context_adjustment = _clip(
            _to_float(kwargs.get("max_context_adjustment"), 0.10),
            0.03,
            0.15,
        )
        self.max_learning_adjustment = _clip(
            _to_float(kwargs.get("max_learning_adjustment"), 0.06),
            0.02,
            0.10,
        )

    def _context_weight_map(self, payload: dict[str, Any]) -> dict[str, float]:
        regime = str(payload.get("regime_context") or "").strip().lower()
        vol = _clip(_to_float(payload.get("volatility_factor"), 0.0), 0.0, 100.0)
        momentum = _clip(_to_float(payload.get("momentum_weight"), 0.0), -1.0, 1.0)
        tf_align = _clip(_to_float(payload.get("timeframe_alignment_score"), 50.0), 0.0, 100.0)
        walkforward = _clip(_to_float(payload.get("walkforward_stability_score"), 50.0), 0.0, 100.0)

        weights = {name: 1.0 for name in self._BASE_PERSONAS}

        # Bounded regime hooks (conservative, additive-neutral).
        if regime in {"trending", "trend", "momentum"}:
            weights["momentum"] += 0.04
            weights["technical"] += 0.02
        elif regime in {"ranging", "range", "choppy"}:
            weights["psychology"] += 0.03
            weights["volume"] += 0.02
            weights["momentum"] -= 0.03
        elif regime in {"volatile", "risk_off", "stress"}:
            weights["psychology"] += 0.05
            weights["volume"] += 0.03
            weights["momentum"] -= 0.04

        # Volatility profile hooks.
        if vol >= 65.0:
            weights["psychology"] += 0.03
            weights["volume"] += 0.02
            weights["momentum"] -= 0.02
        elif vol <= 28.0:
            weights["technical"] += 0.02
            weights["momentum"] += 0.01

        # Stability hooks.
        if walkforward >= 65.0 and tf_align >= 60.0:
            weights["technical"] += 0.02
            weights["momentum"] += 0.02
        elif walkforward <= 40.0:
            weights["psychology"] += 0.03
            weights["technical"] -= 0.02

        # Momentum sign sensitivity.
        if momentum <= -0.35:
            weights["momentum"] -= 0.03
            weights["psychology"] += 0.02
        elif momentum >= 0.35:
            weights["momentum"] += 0.02

        out: dict[str, float] = {}
        for name, raw in weights.items():
            delta = _clip(raw - 1.0, -self.max_context_adjustment, self.max_context_adjustment)
            out[name] = round(_clip(1.0 + delta, 0.88, 1.12), 4)
        return out

    def _learning_weight_map(self, payload: dict[str, Any]) -> dict[str, float]:
        """
        Optional bounded learning hooks.
        Accepts either:
        - payload["persona_policy_hints"] = {persona: {"multiplier": x, "sample_size": n}}
        - payload["persona_performance_memory"] = {persona: {"multiplier": x, "evidence_count": n}}
        """
        hints = payload.get("persona_policy_hints")
        if not isinstance(hints, dict):
            hints = payload.get("persona_performance_memory")
        out = {name: 1.0 for name in self._BASE_PERSONAS}
        if not isinstance(hints, dict):
            return out

        for name in self._BASE_PERSONAS:
            h = hints.get(name)
            if not isinstance(h, dict):
                continue
            base_mult = _to_float(h.get("multiplier"), 1.0)
            sample = _to_float(h.get("sample_size"), _to_float(h.get("evidence_count"), 0.0))
            # Evidence-gated blending toward 1.0 to prevent overfit.
            evidence = _clip(sample / 40.0, 0.0, 1.0)
            blended = 1.0 + (base_mult - 1.0) * evidence
            delta = _clip(blended - 1.0, -self.max_learning_adjustment, self.max_learning_adjustment)
            out[name] = round(_clip(1.0 + delta, 0.90, 1.10), 4)
        return out

    def evaluate(self, persona_payload):
        payload = dict(persona_payload or {})
        provider_agreement = _clip(_to_float(payload.get("provider_agreement"), 0.0), 0.0, 1.0)
        volatility = _clip(_to_float(payload.get("volatility_factor"), 0.0), 0.0, 100.0)
        momentum = _clip(_to_float(payload.get("momentum_weight"), 0.0), -1.0, 1.0)
        timeframe_alignment = _clip(_to_float(payload.get("timeframe_alignment_score"), 50.0), 0.0, 100.0)
        walkforward = _clip(_to_float(payload.get("walkforward_stability_score"), 50.0), 0.0, 100.0)

        context_weights = self._context_weight_map(payload)
        learning_weights = self._learning_weight_map(payload)
        combined_weights = {}
        for name in self._BASE_PERSONAS:
            raw = context_weights.get(name, 1.0) * learning_weights.get(name, 1.0)
            combined_weights[name] = round(_clip(raw, 0.86, 1.14), 4)

        # Deterministic base persona scoring.
        base_scores = {
            "technical": _clip(
                50.0
                + ((timeframe_alignment - 50.0) * 0.75)
                + ((walkforward - 50.0) * 0.25)
                - (max(0.0, volatility - 65.0) * 0.12),
                5.0,
                95.0,
            ),
            "momentum": _clip(
                50.0
                + (momentum * 32.0)
                + ((timeframe_alignment - 50.0) * 0.20)
                - (max(0.0, volatility - 70.0) * 0.10),
                5.0,
                95.0,
            ),
            "volume": _clip(
                50.0
                + ((provider_agreement - 0.5) * 44.0)
                + ((timeframe_alignment - 50.0) * 0.12)
                + (min(30.0, volatility) * 0.08),
                5.0,
                95.0,
            ),
            "psychology": _clip(
                50.0
                + ((walkforward - 50.0) * 0.32)
                + ((provider_agreement - 0.5) * 22.0)
                - (abs(momentum) * 8.0)
                - (max(0.0, volatility - 75.0) * 0.09),
                5.0,
                95.0,
            ),
        }

        rows = []
        for name in self._BASE_PERSONAS:
            base = _to_float(base_scores.get(name), 50.0)
            weighted = _clip(base * _to_float(combined_weights.get(name), 1.0), 0.0, 100.0)
            signal = _persona_signal(weighted)
            reason_bits = []
            if name == "technical":
                reason_bits.append(f"timeframe_alignment={round(timeframe_alignment, 1)}")
                reason_bits.append(f"walkforward={round(walkforward, 1)}")
            elif name == "momentum":
                reason_bits.append(f"momentum_weight={round(momentum, 3)}")
                reason_bits.append(f"alignment={round(timeframe_alignment, 1)}")
            elif name == "volume":
                reason_bits.append(f"provider_agreement={round(provider_agreement, 3)}")
                reason_bits.append(f"volatility={round(volatility, 1)}")
            else:
                reason_bits.append(f"walkforward={round(walkforward, 1)}")
                reason_bits.append(f"volatility={round(volatility, 1)}")

            reason_text = f"{name}_lens:{signal}; " + ", ".join(reason_bits[:2])
            confidence = _clip(
                48.0 + (abs(weighted - 50.0) * 0.9) + (_to_float(combined_weights.get(name), 1.0) - 1.0) * 35.0,
                35.0,
                94.0,
            )
            rows.append(
                {
                    # Backward-compatible keys
                    "persona": name,
                    "score": round(weighted, 4),
                    "confidence": round(confidence, 4),
                    "grade": round(weighted, 4),
                    "reason": reason_text,
                    # Explicit v2 keys
                    "persona_name": name,
                    "numeric_score": round(weighted, 4),
                    "grade_percent": round(weighted, 4),
                    "grade_letter": _grade_letter(weighted),
                    "buy_hold_sell_signal": "Buy" if signal == "buy" else ("Hold" if signal == "neutral" else "Avoid"),
                    "persona_signal": signal,
                    "persona_score": round(weighted, 4),
                    "persona_reason": reason_text,
                    "persona_reasons": [reason_text],
                    "persona_signal_weights_used": {
                        "context_weight": _to_float(context_weights.get(name), 1.0),
                        "learning_weight": _to_float(learning_weights.get(name), 1.0),
                        "combined_weight": _to_float(combined_weights.get(name), 1.0),
                    },
                }
            )
        return rows


class PersonaCouncilAggregator:
    def __init__(self, *args, **kwargs):
        pass

    def aggregate(self, persona_breakdown, regime_context=None):
        rows = [r for r in (persona_breakdown or []) if isinstance(r, dict)]
        if not rows:
            return {
                "majority_signal": "neutral",
                "consensus_strength": 0.0,
                "persona_disagreement_index": 100.0,
                "persona_best_fit": "unknown",
                "weighted_average_grade_percent": 50.0,
                "persona_consensus_score": 50.0,
                "persona_weighted_grade": 50.0,
                "persona_weights_applied": {},
                "persona_weight_drift_score": 0.0,
                "regime_context": regime_context or "unknown",
            }

        weighted_scores = []
        vote_weights = {"buy": 0.0, "neutral": 0.0, "avoid": 0.0}
        persona_weights_applied: dict[str, float] = {}
        for row in rows:
            name = str(row.get("persona_name") or row.get("persona") or "unknown").strip().lower()
            score = _clip(
                _to_float(
                    row.get("numeric_score"),
                    _to_float(row.get("grade_percent"), _to_float(row.get("score"), 50.0)),
                ),
                0.0,
                100.0,
            )
            w = _clip(
                _to_float(
                    (row.get("persona_signal_weights_used") or {}).get("combined_weight"),
                    1.0,
                ),
                0.85,
                1.15,
            )
            persona_weights_applied[name] = round(w, 4)
            weighted_scores.append((name, score, w))
            sig = str(row.get("persona_signal") or "").strip().lower()
            if sig not in {"buy", "neutral", "avoid"}:
                bhs = str(row.get("buy_hold_sell_signal") or "").strip().lower()
                if "buy" in bhs:
                    sig = "buy"
                elif "avoid" in bhs or "sell" in bhs:
                    sig = "avoid"
                else:
                    sig = "neutral"
            vote_weights[sig] = _to_float(vote_weights.get(sig), 0.0) + w

        total_w = max(0.0001, sum(w for _, _, w in weighted_scores))
        weighted_avg = sum(score * w for _, score, w in weighted_scores) / total_w
        winning_signal, winning_weight = max(vote_weights.items(), key=lambda kv: kv[1])
        consensus_strength = _clip((winning_weight / max(0.0001, sum(vote_weights.values()))) * 100.0, 0.0, 100.0)

        # Disagreement combines vote fragmentation and score dispersion.
        mean = weighted_avg
        variance = sum(((score - mean) ** 2) * w for _, score, w in weighted_scores) / total_w
        stddev = math.sqrt(max(0.0, variance))
        normalized_std = _clip(stddev / 25.0, 0.0, 1.0)  # ~25 points spread => max disagreement component
        vote_entropy_proxy = 1.0 - (winning_weight / max(0.0001, sum(vote_weights.values())))
        disagreement_index = _clip((normalized_std * 60.0) + (vote_entropy_proxy * 40.0), 0.0, 100.0)

        best_fit = max(weighted_scores, key=lambda x: x[1] * x[2])[0] if weighted_scores else "unknown"
        drift = 0.0
        if persona_weights_applied:
            drift = (
                sum(abs(_to_float(v, 1.0) - 1.0) for v in persona_weights_applied.values())
                / float(len(persona_weights_applied))
            ) * 100.0

        return {
            "majority_signal": winning_signal,
            "consensus_strength": round(consensus_strength, 4),
            "persona_consensus_score": round(weighted_avg, 4),
            "weighted_average_grade_percent": round(weighted_avg, 4),
            # Backward-compatible aliases
            "persona_weighted_grade": round(weighted_avg, 4),
            "persona_disagreement_index": round(disagreement_index, 4),
            "persona_best_fit": str(best_fit or "unknown"),
            "persona_weights_applied": dict(persona_weights_applied),
            "persona_weight_drift_score": round(_clip(drift, 0.0, 100.0), 4),
            "regime_context": regime_context or "unknown",
            "vote_weight_summary": {
                "buy": round(_to_float(vote_weights.get("buy"), 0.0), 4),
                "neutral": round(_to_float(vote_weights.get("neutral"), 0.0), 4),
                "avoid": round(_to_float(vote_weights.get("avoid"), 0.0), 4),
            },
            "evidence_confidence_tier": (
                "moderate"
                if len(weighted_scores) >= 4
                else ("low" if len(weighted_scores) >= 2 else "insufficient")
            ),
        }
