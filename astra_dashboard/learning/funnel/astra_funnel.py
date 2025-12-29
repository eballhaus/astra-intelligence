# -*- coding: utf-8 -*-
"""
Astra Intelligence - Funnel System
Responsible for generating ranked stock and crypto predictions
and logging learning state evolution.
"""

import os
import json
import random
import datetime
from astra_dashboard.engine.data_orchestrator import fetch_live_data


class AstraFunnel:
    def __init__(self):
        """Initialize Astra Funnel."""
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.state_path = os.path.join("state", "learning_state.json")
        os.makedirs("state", exist_ok=True)

    def run(self, mode="stocks", context=None):
        """Returns top 6 ranked predictions for both stocks and crypto."""
        all_results = []

        for data_mode in ["stocks", "crypto"]:
            try:
                # Define candidate pools
                if data_mode == "crypto":
                    pool = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "BNB-USD", "AVAX-USD"]
                else:
                    pool = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "META", "NFLX", "AMD", "GOOGL", "SHOP"]

                # Rank and score
                ranked = self._rank_assets(pool)

                # Package initial results
                results = []
                for symbol, score in ranked[:6]:
                    grade = self._get_grade(score)
                    brain_score = self._generate_brain_score(score)
                    results.append({
                        "symbol": symbol,
                        "grade": grade,
                        "confidence": score,
                        "brain_score": brain_score,
                        "summary": f"{symbol} shows {grade}-level momentum ({score:.1f}% confidence)",
                        "timestamp": self.timestamp,
                        "type": "crypto" if data_mode == "crypto" else "stock"
                    })

                # --- Enrich with Live Data ---
                live = fetch_live_data()
                live_map = {x.get("symbol"): x for x in live if isinstance(x, dict)}

                for r in results:
                    sym = r.get("symbol")
                    if sym in live_map:
                        r.update({
                            "price": live_map[sym].get("price"),
                            "target": live_map[sym].get("target"),
                            "pred_pct": live_map[sym].get("pred_pct"),
                            "stop": live_map[sym].get("stop"),
                            "stop_pct": live_map[sym].get("stop_pct"),
                            "type": live_map[sym].get("type", r.get("type", "unknown")),
                        })

                    # --- Astra local forecast augmentation ---
                    if r.get("price"):
                        r["target"] = r.get("target") or round(
                            r["price"] * (1 + (r.get("confidence", 80) - 70) / 1000), 2
                        )
                        r["stop"] = r.get("stop") or round(
                            r["price"] * (1 - (r.get("confidence", 80) - 70) / 1500), 2
                        )
                        r["pred_pct"] = round(((r["target"] - r["price"]) / r["price"]) * 100, 2)

                print(f"[AstraFunnel] ✅ 6 {data_mode} predictions enriched with live data.")
                all_results.extend(results)

            except Exception as e:
                print(f"[AstraFunnel] Error processing {data_mode}: {e}")

        # Persist learning state
        self._log_learning_state(all_results)

        return all_results

    # --- Ranking & Grading ---
    def _rank_assets(self, pool):
        """Mock ranking logic. Replace with real agents later."""
        random.seed(datetime.datetime.now().timestamp())
        scored = [(symbol, random.uniform(75, 99)) for symbol in pool]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _get_grade(self, confidence):
        """Convert numeric confidence into a letter grade."""
        if confidence >= 95:
            return "A+"
        elif confidence >= 90:
            return "A"
        elif confidence >= 85:
            return "B+"
        elif confidence >= 80:
            return "B"
        else:
            return "C"

    def _generate_brain_score(self, confidence):
        """Simulate Astra Brain meta-evaluation output."""
        noise = random.uniform(-2, 2)
        adjusted = confidence + noise
        return max(70.0, min(round(adjusted, 2), 99.9))

    def _log_learning_state(self, predictions):
        """Append each prediction cycle to Astra's learning state file."""
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r") as f:
                    data = json.load(f)
            else:
                data = {"history": []}

            cycle_entry = {
                "timestamp": self.timestamp,
                "total_predictions": len(predictions),
                "average_confidence": round(sum(p["confidence"] for p in predictions) / len(predictions), 2),
                "average_brain_score": round(sum(p["brain_score"] for p in predictions) / len(predictions), 2),
                "symbols": [
                    {
                        "symbol": p["symbol"],
                        "type": p.get("type"),
                        "confidence": p["confidence"],
                        "brain_score": p["brain_score"],
                        "pred_pct": p.get("pred_pct"),
                        "price": p.get("price"),
                        "target": p.get("target"),
                        "summary": p.get("summary"),
                    }
                    for p in predictions
                ],
            }

            data["history"].append(cycle_entry)

            with open(self.state_path, "w") as f:
                json.dump(data, f, indent=2)

            print(f"[AstraFunnel] 🧠 Learning state updated ({len(predictions)} entries logged).")

        except Exception as e:
            print(f"[AstraFunnel] ⚠️ Failed to log learning state: {e}")
