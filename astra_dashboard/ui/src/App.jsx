import React, { useEffect, useState } from "react";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";
import ChartsTab from "./dashboard/pages/ChartsTab";

console.log("🔥 APP FILE ACTIVE:", import.meta.url);

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [remoteMode, setRemoteMode] = useState(false);

  useEffect(() => {
    const onResize = () => setRemoteMode(window.innerWidth <= 1100);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const tabs = remoteMode
    ? [
        { key: "dashboard", label: "Buys" },
        { key: "positions", label: "Positions" },
        { key: "sell_alerts", label: "Sell Alerts" },
        { key: "learning", label: "Learning" },
      ]
    : [
        { key: "dashboard", label: "Dashboard" },
        { key: "charts", label: "Charts" },
        { key: "learning", label: "Learning" },
      ];

  return (
    <div className="astra-app-shell">
      <div className="astra-tabbar">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`astra-tab-btn ${activeTab === tab.key ? "active" : ""}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {(activeTab === "dashboard" || activeTab === "positions" || activeTab === "sell_alerts") && (
        <Dashboard remoteSection={activeTab} remoteMode={remoteMode} />
      )}
      {!remoteMode && activeTab === "charts" && <ChartsTab />}
      {activeTab === "learning" && <LearningTab compact={remoteMode} />}
    </div>
  );
}

export default App;
