import React, { useState, useEffect } from "react";

export default function LearningTab() {
  const [metrics, setMetrics] = useState(null);

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const res = await fetch("/state/learning_metrics.json?_=" + Date.now());
        const data = await res.json();
        setMetrics(data);
      } catch (err) {
        console.error("[LearningTab] Failed to load metrics:", err);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 15000); // refresh every 15 s
    return () => clearInterval(interval);
  }, []);

  if (!metrics) {
    return (
      <div className="bg-gray-900 rounded-2xl p-4 mt-4 text-gray-400">
        <h2 className="text-xl mb-2">🧠 Astra Learning</h2>
        <p>Loading live metrics…</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 rounded-2xl p-4 mt-4 text-white">
      <h2 className="text-xl mb-2">🧠 Astra Learning — Live Metrics</h2>
      <p>Cycle: <b>{metrics.cycle}</b></p>
      <p>Average Reward: <b>{metrics.avg_reward.toFixed(4)}</b></p>
      <p>Correlation Weight: <b>{metrics.correlation_weight.toFixed(4)}</b></p>
      <p className="text-gray-400 text-sm mt-2">
        Last Update: {new Date(metrics.timestamp).toLocaleString()}
      </p>
    </div>
  );
}
