import React, { Component, useState } from "react";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";
import { API_BASE_STORAGE_KEY, getInitialApiBase } from "./apiBase";

console.log("🔥 APP FILE ACTIVE:", import.meta.url);

class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    try {
      console.error("[Astra] frontend render recovered", error, info);
    } catch (_e) {}
  }

  handleReconnect = () => {
    try {
      window.localStorage.removeItem(API_BASE_STORAGE_KEY);
    } catch (_e) {}
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 20,
        color: "#e6f0ff",
        background: "linear-gradient(135deg, #071426 0%, #102742 100%)",
      }}>
        <div style={{
          maxWidth: 560,
          border: "1px solid #31577f",
          borderRadius: 14,
          background: "rgba(9,24,44,0.92)",
          padding: 18,
          boxShadow: "0 18px 44px rgba(0,0,0,0.28)",
        }}>
          <h1 style={{ margin: "0 0 8px", fontSize: 22 }}>Astra Dashboard Recovered</h1>
          <p style={{ margin: "0 0 12px", color: "#b7c9e6", lineHeight: 1.45 }}>
            The frontend hit a recoverable render issue. This can happen on mobile after a cached dashboard bundle or API base becomes stale.
          </p>
          <div style={{ fontSize: 12, color: "#91aad0", marginBottom: 12 }}>
            Current API base: {getInitialApiBase()}
          </div>
          <button
            type="button"
            onClick={this.handleReconnect}
            style={{
              border: "1px solid #5ea0ff",
              background: "linear-gradient(180deg, #2f7cf5 0%, #1f62cb 100%)",
              color: "#fff",
              borderRadius: 8,
              padding: "8px 12px",
              fontWeight: 700,
            }}
          >
            Reconnect Backend
          </button>
        </div>
      </div>
    );
  }
}

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const isDashboard = activeTab === "dashboard";
  const isLearning = activeTab === "learning";

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
      </div>

      {isDashboard && <Dashboard />}
      {isLearning && <LearningTab />}
    </div>
  );
}

export default function AppWithBoundary() {
  return (
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  );
}
