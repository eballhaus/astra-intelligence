import React, { useEffect, useState } from "react";
import "./App.css";

export default function App() {
  const [dashboardData, setDashboardData] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch("/api/dashboard-data");
        const json = await res.json();
        setDashboardData(json);
      } catch (err) {
        console.warn("⚠️ Dashboard fetch failed:", err);
      }
    }
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, []);

  const mockStocks = Array.from({ length: 6 }, (_, i) => ({
    ticker: `STK${i + 1}`,
    type: "STOCK",
    confidence: "87%",
    price: "$123.45",
    change: "+1.24%",
    prediction: "BUY",
    grade: "A",
  }));

  const mockCryptos = Array.from({ length: 6 }, (_, i) => ({
    ticker: `CRY${i + 1}`,
    type: "CRYPTO",
    confidence: "91%",
    price: "$2,345.67",
    change: "-0.56%",
    prediction: "HOLD",
    grade: "B+",
  }));

  const stocks = dashboardData?.stocks || mockStocks;
  const cryptos = dashboardData?.cryptos || mockCryptos;

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <h1>Astra Intelligence</h1>
        <div className="market-overview">
          <span>S&P 500 4,760 ▲1.2%</span> | 
          <span>NASDAQ 15,020 ▲0.9%</span> | 
          <span>Dow Jones 37,800 ▲0.4%</span> | 
          <span>BTC 44,250 ▲2.1%</span>
        </div>
      </header>
      <main className="dashboard-grid">
        <section className="stock-column">
          {stocks.map((item, i) => (
            <div key={i} className="card stock-card">
              <h2>{item.ticker}</h2>
              <p className="asset-type">STOCK</p>
              <div className="confidence">{item.confidence}</div>
              <p className="price">{item.price}</p>
              <p className="change positive">{item.change}</p>
              <p className="prediction">
                Astra Prediction: <strong>{item.prediction}</strong>
              </p>
              <p className="grade">Buy Grade: {item.grade}</p>
              <p className="reason">
                Astra selected this asset due to momentum, volume confirmation, and trend strength.
              </p>
            </div>
          ))}
        </section>
        <section className="crypto-column">
          {cryptos.map((item, i) => (
            <div key={i} className="card crypto-card">
              <h2>{item.ticker}</h2>
              <p className="asset-type">CRYPTO</p>
              <div className="confidence">{item.confidence}</div>
              <p className="price">{item.price}</p>
              <p className="change negative">{item.change}</p>
              <p className="prediction">
                Astra Prediction: <strong>{item.prediction}</strong>
              </p>
              <p className="grade">Buy Grade: {item.grade}</p>
              <p className="reason">
                Astra selected this asset due to momentum, volume confirmation, and trend strength.
              </p>
            </div>
          ))}
        </section>
        <section className="chart-column">
          <div className="chart-placeholder">
            <h3>Advanced Chart Area</h3>
            <p>(Candlestick chart placeholder)</p>
          </div>
        </section>
      </main>
    </div>
  );
}
