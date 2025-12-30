import React from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import "../../App.css";

export default function LearningTab() {
  // --- Mock analytics data (UI-only) ---
  const accuracyTrend = [
    { date: "Mon", accuracy: 72 },
    { date: "Tue", accuracy: 74 },
    { date: "Wed", accuracy: 76 },
    { date: "Thu", accuracy: 78 },
    { date: "Fri", accuracy: 79 },
  ];

  const categoryData = [
    { category: "Day", value: 3.2 },
    { category: "Swing", value: 7.5 },
    { category: "BigCap", value: 6.3 },
    { category: "MidCap", value: 4.1 },
    { category: "SmallCap", value: 2.8 },
    { category: "Crypto", value: 9.7 },
  ];

  const pnlTrend = [
    { date: "Mon", pnl: 1.2 },
    { date: "Tue", pnl: 3.5 },
    { date: "Wed", pnl: 5.1 },
    { date: "Thu", pnl: 7.4 },
    { date: "Fri", pnl: 9.2 },
  ];

  return (
    <div className="learning-view">
      <h2 className="learning-title">📘 Astra Learning Overview</h2>

      {/* Metric Summary Cards */}
      <div className="metrics-grid glassy">
        <div><strong>🏆 Win Rate:</strong> 76.4%</div>
        <div><strong>📊 Accuracy:</strong> 79.2%</div>
        <div><strong>💡 Confidence:</strong> 84%</div>
        <div><strong>🧠 Learning Rate:</strong> +1.2% / week</div>
        <div><strong>💰 Cumulative PnL:</strong> +12.8%</div>
      </div>

      {/* Charts Row */}
      <div className="charts-row">
        <div className="chart-card">
          <h3>Accuracy Improvement Over Time</h3>
          <LineChart width={500} height={250} data={accuracyTrend}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="accuracy" stroke="#00ffc8" strokeWidth={2} />
          </LineChart>
        </div>

        <div className="chart-card">
          <h3>Performance by Trade Type</h3>
          <BarChart width={500} height={250} data={categoryData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="category" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Bar dataKey="value" fill="#4affef" />
          </BarChart>
        </div>
      </div>

      {/* Cumulative Profit Area Chart */}
      <div className="chart-card wide">
        <h3>Cumulative Profit Curve</h3>
        <AreaChart width={1050} height={250} data={pnlTrend}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Area
            type="monotone"
            dataKey="pnl"
            stroke="#00ffc8"
            fill="rgba(0, 255, 200, 0.3)"
          />
        </AreaChart>
      </div>
    </div>
  );
}

