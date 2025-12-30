// 🚫 FROZEN DASHBOARD SECTION — DO NOT MODIFY
// This version is confirmed working with correct cards, layout, and chart.
// Any dashboard changes must first be tested in a duplicate file (App.dev.jsx).


import React, { useState, useEffect } from "react";
import "./App.css";
import Dashboard from "./dashboard/pages/Dashboard";

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="dashboard-header">
        <h1>Astra Intelligence</h1>
      </header>

      {/* Market overview strip */}
      <section className="market-overview">
        <div>
          <h2>S&P 500</h2>
          <p>4,835.21 (+0.64%)</p>
        </div>
        <div>
          <h2>NASDAQ</h2>
          <p>15,232.77 (+1.02%)</p>
        </div>
        <div>
          <h2>DOW</h2>
          <p>37,825.42 (-0.12%)</p>
        </div>
        <div>
          <h2>Bitcoin</h2>
          <p>$43,210 (+0.85%)</p>
        </div>
      </section>

      {/* Tab switch */}
      <nav className="tab-bar">
        <button
          className={activeTab === "dashboard" ? "active" : ""}
          onClick={() => setActiveTab("dashboard")}
        >
          Dashboard
        </button>
        <button
          className={activeTab === "learning" ? "active" : ""}
          onClick={() => setActiveTab("learning")}
        >
          Learning
        </button>
      </nav>

      {/* MAIN CONTENT */}
      {activeTab === "dashboard" && (
        <div className="dashboard-grid">
          <div className="stock-column">
            {/* 6 Stock Cards */}
            {[...Array(6)].map((_, i) => (
              <div key={i} className="asset-card">
                <h3>STK{i + 1}</h3>
                <p className="type">STOCK</p>
                <p className="confidence">87%</p>
                <p className="price">$123.45</p>
                <p className="change up">+1.24%</p>
                <p className="prediction">Astra Prediction: BUY</p>
                <p className="grade">Buy Grade: A</p>
                <p className="reason">
                  Astra selected this asset due to momentum, volume confirmation,
                  and trend strength.
                </p>
              </div>
            ))}
          </div>

          <div className="crypto-column">
            {/* 6 Crypto Cards */}
            {[...Array(6)].map((_, i) => (
              <div key={i} className="asset-card">
                <h3>CRY{i + 1}</h3>
                <p className="type">CRYPTO</p>
                <p className="confidence">91%</p>
                <p className="price">$2,345.67</p>
                <p className="change down">-0.56%</p>
                <p className="prediction">Astra Prediction: HOLD</p>
                <p className="grade">Buy Grade: B+</p>
                <p className="reason">
                  Astra selected this asset due to momentum, volume confirmation,
                  and trend strength.
                </p>
              </div>
            ))}
          </div>

          <div className="chart-column">
            <h2>Advanced Chart</h2>
            <iframe
              title="TradingView"
              src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_abcdef&symbol=NASDAQ:AAPL&interval=30&hidesidetoolbar=1&symboledit=1&saveimage=1&toolbarbg=f1f3f6&hideideas=1"
              width="100%"
              height="600"
              frameBorder="0"
              allowTransparency="true"
              allowFullScreen
            ></iframe>
          </div>
        </div>
      )}

      {activeTab === "learning" && (
        <div className="learning-panel">
          <h2>Learning Overview</h2>
          <p>Win rate, accuracy, confidence charts...</p>
        </div>
      )}
    </div>
  );
}
