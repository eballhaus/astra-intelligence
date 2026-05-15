import React, { useState } from "react";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";

console.log("🔥 APP FILE ACTIVE:", import.meta.url);

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const isDashboard = activeTab === "dashboard";
  const isLearning = activeTab === "learning";
  const isRemote = activeTab === "remote";

  const shellStyle = {
    width: "100%",
    minHeight: "100vh",
    padding: "16px 18px 20px",
    color: "#e6f0ff",
    display: "grid",
    alignContent: "start",
    gap: "12px",
  };

  const tabRailStyle = {
    display: "inline-flex",
    gap: "8px",
    padding: "6px",
    borderRadius: "11px",
    border: "1px solid #2d4a74",
    background: "rgba(10, 24, 44, 0.78)",
    width: "fit-content",
  };

  const tabButtonStyle = (active) => ({
    padding: "8px 14px",
    background: active
      ? "linear-gradient(180deg, #2f7cf5 0%, #1f62cb 100%)"
      : "rgba(17, 37, 64, 0.82)",
    color: active ? "#ffffff" : "#cfe1ff",
    border: "1px solid " + (active ? "#5ea0ff" : "#2b496f"),
    borderRadius: "8px",
    cursor: "pointer",
    fontWeight: 700,
    letterSpacing: "0.01em",
  });

  return (
    <div style={shellStyle}>
      <div style={tabRailStyle}>
        <button
          onClick={() => setActiveTab("dashboard")}
          style={tabButtonStyle(isDashboard)}
        >
          Dashboard
        </button>
        <button
          onClick={() => setActiveTab("learning")}
          style={tabButtonStyle(isLearning)}
        >
          Learning
        </button>
        <button
          onClick={() => setActiveTab("remote")}
          style={tabButtonStyle(isRemote)}
        >
          Remote
        </button>
      </div>

      {isDashboard && <Dashboard />}
      {isLearning && <LearningTab />}
      {isRemote && <Dashboard remoteMode />}
    </div>
  );
}

export default App;
