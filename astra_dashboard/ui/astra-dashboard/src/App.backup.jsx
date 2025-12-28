import React from "react";
import Header from "./components/Header";
import SystemPanels from "./components/SystemPanels";
import TickerGrid from "./components/TickerGrid";
import AdvancedChart from "./components/AdvancedChart";

export default function App() {
  const timestamp = new Date().toUTCString();

  console.log("🚀 Testing AdvancedChart component...");

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#0b1020] to-[#0f2240] text-white p-8">
      <Header timestamp={timestamp} />
      <SystemPanels />
      <TickerGrid />
      <AdvancedChart />
      <h1 className="text-3xl text-green-400 mt-8 text-center">
        ✅ AdvancedChart Loaded OK
      </h1>
    </div>
  );
}

