import React from "react";

export default function Header({ timestamp }) {
  return (
    <header className="text-center mb-8">
      <h1 className="text-5xl font-bold text-blue-200 tracking-tight">
        Astra Intelligence
      </h1>
      <p className="text-blue-400 text-lg">
        Autonomous Prediction & Learning System
      </p>
      <p className="text-sm text-gray-400 mt-2">
        Live System Snapshot — {timestamp}
      </p>
    </header>
  );
}
