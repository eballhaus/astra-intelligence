from __future__ import annotations


class PersonaFunnel:
    def __init__(self, *args, **kwargs):
        self.ttl_seconds = int(kwargs.get("ttl_seconds") or 8)

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            if value is None:
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _clip(value, low, high):
        return max(float(low), min(float(high), float(value)))

    @staticmethod
    def _norm_key(value, default="unknown"):
        txt = str(value or "").strip().lower()
        if txt in {"", "none", "null"}:
            return str(default)
        return txt

    def _signal_from_score(self, score):
        if score >= 62.0:
            return "buy"
        if score <= 40.0:
            return "avoid"
        return "hold"

    def _resolve_weight_hint(self, learning_weights, scope, key):
        """
        Supports several hint shapes conservatively:
        - {"scope": {"key": x}}
        - {"scope": {"key": {"multiplier": x}}}
        - {"scope:key": x}
        """
        if not isinstance(learning_weights, dict):
            return 1.0
        scope_map = learning_weights.get(scope)
        if isinstance(scope_map, dict):
            val = scope_map.get(key)
            if isinstance(val, dict):
                val = val.get("multiplier", 1.0)
            return self._clip(self._to_float(val, 1.0), 0.92, 1.08)
        compact = learning_weights.get(f"{scope}:{key}")
        return self._clip(self._to_float(compact, 1.0), 0.92, 1.08)

    def _evaluate_symbol(
        self,
        sym,
        idx,
        q,
        market_regime_key,
        cap_bucket,
        learning_weights,
        trading_style,
    ):
        price = self._to_float(q.get("price"), 0.0)
        prev_close = self._to_float(q.get("prev_close"), 0.0)
        provider_agreement = self._clip(self._to_float(q.get("provider_agreement"), 0.0), 0.0, 1.0)
        quote_quality = self._norm_key(q.get("quote_quality"), "unknown")
        provider_used = self._norm_key(q.get("provider_used"), "none")
        data_unavailable = bool(q.get("data_unavailable_reason"))
        quote_age_seconds = max(0.0, self._to_float(q.get("quote_age_seconds"), 0.0))

        has_valid_quote = bool(price > 0.0 and prev_close > 0.0)
        change_pct = ((price - prev_close) / prev_close * 100.0) if has_valid_quote else 0.0
        abs_change_pct = abs(change_pct)

        quote_quality_score = 0.0
        if has_valid_quote:
            quote_quality_score += 38.0
        quote_quality_score += provider_agreement * 22.0
        if quote_quality in {"fresh", "trusted", "high", "clean"}:
            quote_quality_score += 10.0
        elif quote_quality in {"placeholder", "degraded", "stale"}:
            quote_quality_score -= 8.0
        if data_unavailable:
            quote_quality_score -= 14.0
        if quote_age_seconds > 0:
            quote_quality_score -= min(10.0, quote_age_seconds / 18.0)
        quote_quality_score = self._clip(quote_quality_score, 0.0, 100.0)

        # Regime/setup-style context shaping (bounded).
        momentum_context = self._clip(50.0 + (change_pct * 4.0), 0.0, 100.0)
        technical_context = self._clip(
            52.0 + (quote_quality_score - 50.0) * 0.45 + (change_pct * 1.4),
            0.0,
            100.0,
        )
        volume_context = self._clip(
            50.0 + (provider_agreement * 30.0) + (5.0 if provider_used not in {"none", "unknown"} else -6.0),
            0.0,
            100.0,
        )
        psychology_context = self._clip(
            55.0 - (abs_change_pct * 1.1) + ((quote_quality_score - 50.0) * 0.20),
            0.0,
            100.0,
        )

        if market_regime_key in {"trending", "trend", "momentum"}:
            momentum_context += 4.0
            technical_context += 2.0
        elif market_regime_key in {"ranging", "range", "choppy"}:
            psychology_context += 4.0
            momentum_context -= 4.0
        elif market_regime_key in {"volatile", "risk_off", "stress"}:
            psychology_context += 5.0
            momentum_context -= 6.0
            technical_context -= 2.0

        if trading_style in {"intraday", "day", "daytrading"}:
            momentum_context += 2.0
            technical_context += 2.0
            psychology_context -= 1.0
        elif trading_style in {"swing", "position"}:
            psychology_context += 2.0

        # Cap-bucket moderation (reduce tiny-cap overconfidence).
        if cap_bucket in {"nano", "micro", "small"}:
            psychology_context += 2.0
            technical_context -= 1.0
        elif cap_bucket in {"mega", "large"}:
            technical_context += 1.0
            volume_context += 1.0

        technical_context = self._clip(technical_context, 0.0, 100.0)
        momentum_context = self._clip(momentum_context, 0.0, 100.0)
        volume_context = self._clip(volume_context, 0.0, 100.0)
        psychology_context = self._clip(psychology_context, 0.0, 100.0)

        ctx_regime_mult = self._resolve_weight_hint(learning_weights, "regime", market_regime_key)
        ctx_cap_mult = self._resolve_weight_hint(learning_weights, "cap_bucket", cap_bucket)
        ctx_provider_mult = self._resolve_weight_hint(learning_weights, "provider", provider_used)
        context_weight = self._clip((ctx_regime_mult * ctx_cap_mult * ctx_provider_mult) ** (1.0 / 3.0), 0.94, 1.06)

        p_tech = self._clip(technical_context * context_weight, 0.0, 100.0)
        p_momo = self._clip(momentum_context * context_weight, 0.0, 100.0)
        p_vol = self._clip(volume_context * context_weight, 0.0, 100.0)
        p_psy = self._clip(psychology_context * context_weight, 0.0, 100.0)

        persona_scores = {
            "technical": round(p_tech, 2),
            "momentum": round(p_momo, 2),
            "volume": round(p_vol, 2),
            "psychology": round(p_psy, 2),
        }

        # Consensus + disagreement (deterministic).
        vals = list(persona_scores.values())
        avg_score = sum(vals) / float(max(1, len(vals)))
        spread = max(vals) - min(vals) if vals else 0.0
        disagreement = self._clip((spread * 1.4) + (max(0.0, 35.0 - quote_quality_score) * 0.45), 8.0, 72.0)
        consensus_strength = self._clip(avg_score - (disagreement * 0.22), 0.0, 100.0)

        sorted_personas = sorted(persona_scores.items(), key=lambda kv: kv[1], reverse=True)
        best_fit = sorted_personas[0][0] if sorted_personas else "technical"
        best_score = sorted_personas[0][1] if sorted_personas else 0.0

        persona_grades = {}
        buy_votes = 0
        for name, pscore in persona_scores.items():
            sig = self._signal_from_score(pscore)
            if sig == "buy":
                buy_votes += 1
            persona_grades[name] = {
                "persona_signal": sig,
                "persona_score": round(pscore, 2),
                "persona_reason": f"{name}_lens score={round(pscore,1)} regime={market_regime_key}",
            }

        # Core funnel score with light readiness pressure.
        readiness_penalty = 0.0
        if quote_quality_score < 45.0:
            readiness_penalty += (45.0 - quote_quality_score) * 0.25
        if disagreement > 45.0:
            readiness_penalty += (disagreement - 45.0) * 0.18
        if not has_valid_quote:
            readiness_penalty += 10.0

        base_score = (
            (quote_quality_score * 0.34)
            + (consensus_strength * 0.28)
            + (best_score * 0.20)
            + ((100.0 - disagreement) * 0.12)
            + (min(100.0, abs_change_pct * 12.0) * 0.06)
        )
        recency_penalty = min(4.0, idx * 0.02)
        funnel_score = self._clip(base_score - readiness_penalty - recency_penalty, 0.0, 100.0)

        quality_reasons = []
        if quote_quality_score >= 65.0:
            quality_reasons.append("trusted_quote_quality")
        elif quote_quality_score < 45.0:
            quality_reasons.append("weak_quote_quality")
        if consensus_strength >= 62.0 and disagreement <= 35.0:
            quality_reasons.append("strong_persona_consensus")
        elif disagreement > 45.0:
            quality_reasons.append("high_persona_disagreement")
        if data_unavailable:
            quality_reasons.append("provider_data_gap")
        if not quality_reasons:
            quality_reasons.append("balanced_mixed_signal")

        row_hint = {
            "symbol": sym,
            "funnel_score_total": round(funnel_score, 2),
            "persona_weighted_grade": round(avg_score, 2),
            "persona_grades": persona_grades,
            "persona_consensus_summary": {
                "consensus_strength": round(consensus_strength, 2),
                "disagreement_index": round(disagreement, 2),
                "persona_best_fit": best_fit,
                "funnel_score_total": round(funnel_score, 2),
                "majority_signal": "buy" if buy_votes >= 2 else "hold",
                "buy_vote_count": int(buy_votes),
            },
            "candidate_quality_reasons": quality_reasons[:4],
            "quote_quality_score": round(quote_quality_score, 2),
            "funnel_quality_bucket": (
                "high" if funnel_score >= 72.0 else ("medium" if funnel_score >= 56.0 else "low")
            ),
        }
        return funnel_score, row_hint

    def rank_candidates(self, rows=None, *args, **kwargs):
        """
        Compatibility behavior:
        - Legacy mode: rank_candidates(rows=[...]) -> returns ranked row list
        - Runtime mode: rank_candidates(symbols=..., quote_map=..., candidate_target=...)
          -> returns dict expected by server_extend._build_funnel_candidates(...)
        """
        # Runtime keyword-call path used by server_extend.
        if kwargs.get("symbols") is not None or kwargs.get("quote_map") is not None:
            symbols = [str(s or "").upper() for s in (kwargs.get("symbols") or []) if str(s or "").strip()]
            quote_map = kwargs.get("quote_map") if isinstance(kwargs.get("quote_map"), dict) else {}
            cap_map = kwargs.get("cap_map") if isinstance(kwargs.get("cap_map"), dict) else {}
            market_regime = kwargs.get("market_regime") if isinstance(kwargs.get("market_regime"), dict) else {}
            learning_weights = kwargs.get("learning_weights") if isinstance(kwargs.get("learning_weights"), dict) else {}
            trading_style = self._norm_key(kwargs.get("trading_style"), "swing")
            candidate_target = int(kwargs.get("candidate_target") or 50)
            candidate_target = max(1, min(200, candidate_target))
            regime_key = self._norm_key(
                (market_regime.get("current_regime") if isinstance(market_regime, dict) else None),
                "neutral",
            )

            scored = []
            scores_by_symbol = {}
            for idx, sym in enumerate(symbols):
                q = quote_map.get(sym, {}) if isinstance(quote_map.get(sym), dict) else {}
                cap_bucket = self._norm_key(cap_map.get(sym), "unknown")
                score, row_hint = self._evaluate_symbol(
                    sym=sym,
                    idx=idx,
                    q=q,
                    market_regime_key=regime_key,
                    cap_bucket=cap_bucket,
                    learning_weights=learning_weights,
                    trading_style=trading_style,
                )
                scores_by_symbol[sym] = row_hint
                scored.append((score, sym))

            scored.sort(key=lambda item: item[0], reverse=True)
            candidate_symbols = [sym for score, sym in scored if score >= 34.0][:candidate_target]
            if not candidate_symbols:
                # Conservative continuity: keep a small top slice rather than empty output.
                candidate_symbols = [sym for _, sym in scored[: min(12, len(scored))]]

            return {
                "candidate_symbols": candidate_symbols,
                "scores_by_symbol": scores_by_symbol,
                "rows_evaluated": int(len(symbols)),
                "candidate_count": int(len(candidate_symbols)),
            }

        # Legacy positional rows-call path.
        ranked_rows = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        ranked_rows.sort(key=lambda r: self._to_float(r.get("predicted_win_probability"), 0.0), reverse=True)
        return ranked_rows
