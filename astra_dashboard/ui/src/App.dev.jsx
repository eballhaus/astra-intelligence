// 🧪 DEVELOPMENT VERSION — SAFE TO EDIT
// Dashboard core remains untouched (App.jsx is locked)

import React, { useState } from "react";
import "./App.css";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  return (
    <div className="app-container">
      <div className="tab-bar">
        <button
          onClick={() => setActiveTab("dashboard")}
          className={activeTab === "dashboard" ? "active" : ""}
        >
          Dashboard
        </button>
        <button
          onClick={() => setActiveTab("learning")}
          className={activeTab === "learning" ? "active" : ""}
        >
          Learning
        </button>
      </div>

      {activeTab === "dashboard" && <Dashboard />}
      {activeTab === "learning" && <LearningTab />}
    </div>
  );
}

