import React from "react";
import { Activity, Brain, Terminal } from "lucide-react";

export default function SystemPanels() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
      <div className="bg-[#141a2e] p-5 rounded-2xl shadow-lg border border-blue-800">
        <div className="flex items-center gap-2 mb-2">
          <Activity className="text-green-400" size={20} />
          <h3 className="text-gray-200 font-semibold">System Health</h3>
        </div>
        <p className="text-green-400 text-sm">Operational — Guardian v7 ✅</p>
      </div>

      <div className="bg-[#141a2e] p-5 rounded-2xl shadow-lg border border-blue-800">
        <div className="flex items-center gap-2 mb-2">
          <Brain className="text-blue-400" size={20} />
          <h3 className="text-gray-200 font-semibold">Learning State</h3>
        </div>
        <p className="text-sm text-gray-300">Weights: [0.52, 0.44, 0.59]</p>
        <p className="text-xs text-gray-500 mt-1">Last Updated: 3m ago</p>
      </div>

      <div className="bg-[#141a2e] p-5 rounded-2xl shadow-lg border border-blue-800">
        <div className="flex items-center gap-2 mb-2">
          <Terminal className="text-purple-400" size={20} />
          <h3 className="text-gray-200 font-semibold">Sentinel Activity</h3>
        </div>
        <ul className="text-xs text-gray-400 space-y-1">
          <li>Guardian scan OK — 12 assets synced</li>
          <li>Funnel alignment stable</li>
          <li>Latency 42 ms</li>
        </ul>
      </div>
    </div>
  );
}
