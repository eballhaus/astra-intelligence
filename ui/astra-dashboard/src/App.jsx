import React from "react";
import Dashboard from "./pages/Dashboard";
import "./dashboard/styles/dashboard.css";
import "./dashboard/styles/market.css";

export default function App() {
  return (
    <div className="dashboard-root">
      <Dashboard />
    </div>
  );
}
