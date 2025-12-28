import React, { useEffect, useState } from "react";
import axios from "axios";
import { motion } from "framer-motion";
import { RefreshCw, Activity, Brain, Terminal } from "lucide-react";
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Line,
  Area,
} from "recharts";

const API_SIGNALS = "http://127.0.0.1:8000/api/top_signals";
const API_HEALTH = "http://127.0.0.1:8000/api/system_health";
const API_CHART = "http://127.0.0.1:8000/api/nvda_chart";

export default function AstraDashboard() {
  const [signals, setSignals] = useState([]);
  const [health, setHealth] = useState({});
  const [chartData, setChartData] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [signalsRes, healthRes, chartRes] = await Promise.all([
        axios.get(API_SIGNALS),
        axios.get(API_HEALTH),
        axios.get(API_CHART),
      ]);
      setSignals(signalsRes.data);
      setHealth(healthRes.data);
      setChartData(chartRes.data);
    } catch (err) {
      console.error("Error fetching Astra data:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 300000); // 5 min
    return () => clearInterval(interval);
  }, []);

  const timestamp = new Date().toUTCString();

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0b1020] to-[#0f2240] text-white p-6">
      {/* HEADER */}
      <header className="text-center mb-8">
        <h1 className="text-4xl font-bold text-blue-200">Astra Intelligence</h1>
        <p className="text-sm text-blue-400">Autonomous Prediction & Learning System</p>
        <p className="text-xs text-gray-400 mt-1">
          Live System Snapshot — {timestamp}
        </p>
      </header>

      {/* STATUS PANELS */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-[#141a2e] p-4 rounded-2xl shadow-lg">
          <div className="flex items-center gap-2 mb-2">
            <Activity size={18} className="text-orange-400" />
            <h3 className="font-semibold text-gray-200">System Health</h3>
          </div>
          <p className="text-sm text-green-400">
            {health.system_status || "All tracked files unchanged ✅"}
          </p>
        </div>

        <div className="bg-[#141a2e] p-4 rounded-2xl shadow-lg">
          <div className="flex items-center gap-2 mb-2">
            <Brain size={18} className="text-blue-400" />
            <h3 className="font-semibold text-gray-200">Learning State</h3>
          </div>
          <p className="text-sm text-gray-300">
            Weights: {JSON.stringify(health.learning_weights || [0.577, 0.577, 0.577])}
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Last Updated: {health.last_update || "—"}
          </p>
        </div>

        <div className="bg-[#141a2e] p-4 rounded-2xl shadow-lg">
          <div className="flex items-center gap-2 mb-2">
            <Terminal size={18} className="text-purple-400" />
            <h3 className="font-semibold text-gray-200">Sentinel Activity</h3>
          </div>
          <ul className="text-xs text-gray-400 space-y-1">
            {(health.logs || []).map((log, i) => (
              <li key={i}>{log}</li>
            ))}
          </ul>
        </div>
      </div>

      {/* REFRESH */}
      <div className="flex justify-center mb-6">
        <motion.button
          onClick={fetchData}
          whileTap={{ scale: 0.9 }}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-2xl shadow-lg"
        >
          <RefreshCw size={18} />
          {loading ? "Refreshing..." : "Refresh Now"}
        </motion.button>
      </div>

      {/* SIGNAL GRID */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-6 mb-10">
        {signals.slice(0, 12).map((asset, idx) => (
          <motion.div
            key={idx}
            whileHover={{ scale: 1.05 }}
            className="bg-[#141a2e] p-4 rounded-2xl shadow-md border border-[#1e2a48]"
          >
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-semibold">{asset.symbol}</h3>
              <span className="text-sm text-gray-400">{asset.type}</span>
            </div>
            <p className="text-2xl font-bold text-blue-400 mt-1">
              {asset.confidence.toFixed(1)}%
            </p>
            <p className="text-sm text-gray-300">{asset.grade}</p>
            <p className="text-sm text-gray-400 mt-1">{asset.signal}</p>
            <div className="mt-2 flex justify-between text-sm">
              <span>${asset.price.toFixed(2)}</span>
              <span
                className={`${
                  asset.change >= 0 ? "text-green-400" : "text-red-400"
                }`}
              >
                {asset.change >= 0 ? "▲" : "▼"} {Math.abs(asset.change).toFixed(2)}%
              </span>
            </div>
          </motion.div>
        ))}
      </div>

      {/* ADVANCED NVDA CHART */}
      <div className="bg-[#141a2e] p-6 rounded-2xl shadow-lg mb-10">
        <h3 className="text-lg font-semibold mb-4">NVDA — Advanced Chart</h3>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2a48" />
              <XAxis dataKey="date" stroke="#aaa" />
              <YAxis stroke="#aaa" domain={["auto", "auto"]} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1a1f35", borderRadius: "8px" }}
              />
              <Bar dataKey="volume" yAxisId="left" fill="#1f77b4" barSize={20} />
              <Area
                yAxisId="right"
                type="monotone"
                dataKey="close"
                stroke="#82ca9d"
                fill="#0f2240"
              />
              <Line
                type="monotone"
                dataKey="close"
                stroke="#00ffcc"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* FOOTER */}
      <footer className="text-center text-sm text-gray-400 mt-8">
        Astra Intelligence — <span className="text-blue-400">Guardian v7</span> |{" "}
        <span className="text-green-400">Funnel v11</span> |{" "}
        <span className="text-purple-400">Sentinel Tier 2</span>
      </footer>
    </div>
  );
}
