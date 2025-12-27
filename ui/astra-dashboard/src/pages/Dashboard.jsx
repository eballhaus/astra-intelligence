import React, { useState, useEffect, useRef } from "react";
import "../styles/dashboard.css";

const REFRESH_INTERVAL = 10000;

// Simple logo resolver using Clearbit (free, no key required)
const getLogo = (symbol) =>
  `https://logo.clearbit.com/${symbol.toLowerCase()}.com`;

export default function Dashboard() {
  const [liveData, setLiveData] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");
  const prevPrices = useRef({});

  const loadData = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/live-data");
      let data = await res.json();

      // --- Add static Astra metrics (temporary until backend supports it) ---
      data = data.map((a) => ({
        ...a,
        prediction: a.symbol === "TSLA" ? "Bearish" : "Bullish",
        stop_loss:
          a.symbol === "TSLA"
            ? (a.price * 0.9).toFixed(2)
            : (a.price * 0.95).toFixed(2),
        grade_percent:
          a.grade === "A"
            ? 95
            : a.grade === "A-"
            ? 90
            : a.grade === "B"
            ? 85
            : 80,
        summary:
          a.symbol === "TSLA"
            ? "Recent volatility detected; potential short-term retrace."
            : "Strong momentum and positive market breadth.",
      }));

      // --- Add live crypto feed ---
      const cryptoRes = await fetch(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
      );
      const cryptoJson = await cryptoRes.json();

      const now = new Date().toISOString();
      data.push({
        symbol: "BTC",
        price: cryptoJson.bitcoin.usd,
        prediction: "Bullish",
        stop_loss: (cryptoJson.bitcoin.usd * 0.92).toFixed(2),
        grade: "A",
        grade_percent: 96,
        confidence: 88,
        summary: "Institutional accumulation trend detected.",
        timestamp: now,
      });
      data.push({
        symbol: "ETH",
        price: cryptoJson.ethereum.usd,
        prediction: "Bullish",
        stop_loss: (cryptoJson.ethereum.usd * 0.93).toFixed(2),
        grade: "A-",
        grade_percent: 91,
        confidence: 85,
        summary: "Layer-2 strength and on-chain activity remain strong.",
        timestamp: now,
      });

      setLiveData(data);
    } catch (e) {
      console.error("❌ Live data error:", e);
    }
  };

  useEffect(() => {
    loadData();
    const id = setInterval(loadData, REFRESH_INTERVAL);
    return () => clearInterval(id);
  }, []);

  const flashClass = (symbol, price) => {
    const prev = prevPrices.current[symbol];
    prevPrices.current[symbol] = price;
    if (prev === undefined) return "";
    if (price > prev) return "flash-green";
    if (price < prev) return "flash-red";
    return "";
  };

  const formatTime = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const trendArrow = (symbol, price) => {
    const prev = prevPrices.current[symbol];
    if (prev === undefined) return null;
    if (price > prev) return <span className="trend-up">▲</span>;
    if (price < prev) return <span className="trend-down">▼</span>;
    return null;
  };

  const fillToSix = (arr) => {
    if (arr.length === 0) return [];
    const out = [];
    for (let i = 0; i < 6; i++) out.push(arr[i % arr.length]);
    return out;
  };

  const stocks = fillToSix(
    liveData.filter(
      (a) =>
        !a.symbol.toUpperCase().includes("BTC") &&
        !a.symbol.toUpperCase().includes("ETH")
    )
  );
  const cryptos = fillToSix(
    liveData.filter(
      (a) =>
        a.symbol.toUpperCase().includes("BTC") ||
        a.symbol.toUpperCase().includes("ETH")
    )
  );

  return (
    <div className="dashboard-container">
      <header className="astra-header">🧠 Astra Intelligence — Live Dashboard</header>

      <div className="astra-layout">
        {/* LEFT COLUMN — STOCKS */}
        <div className="column stocks">
          <h2>📈 Stocks</h2>
          {stocks.map((a, i) => (
            <div
              key={`stock-${i}`}
              className={`astra-card white-card ${flashClass(a.symbol, a.price)}`}
              onClick={() => setSelectedSymbol(a.symbol)}
            >
              <div className="card-header">
                <div className="logo-symbol">
                  <img
                    src={getLogo(a.symbol)}
                    alt={a.symbol}
                    onError={(e) => (e.target.style.display = "none")}
                  />
                  <span className="symbol">{a.symbol}</span>
                </div>
                <span className="grade-badge">
                  {a.grade} • {a.grade_percent}%
                </span>
              </div>
              <div className="card-body">
                <div className="price-line">
                  <span className="price">${a.price?.toFixed(2)}</span>
                  {trendArrow(a.symbol, a.price)}
                </div>
                <div className="meta text-secondary">
                  Prediction: <b>{a.prediction}</b> | Stop-Loss: ${a.stop_loss}
                </div>
                <div className="meta text-secondary">
                  Confidence: {a.confidence}% • {formatTime(a.timestamp)}
                </div>
                <div className="summary text-muted">“{a.summary}”</div>
              </div>
            </div>
          ))}
        </div>

        {/* MIDDLE COLUMN — CRYPTOS */}
        <div className="column cryptos">
          <h2>💰 Crypto</h2>
          {cryptos.map((a, i) => (
            <div
              key={`crypto-${i}`}
              className={`astra-card white-card ${flashClass(a.symbol, a.price)}`}
              onClick={() => setSelectedSymbol(a.symbol)}
            >
              <div className="card-header">
                <div className="logo-symbol">
                  <img
                    src={getLogo(a.symbol)}
                    alt={a.symbol}
                    onError={(e) => (e.target.style.display = "none")}
                  />
                  <span className="symbol">{a.symbol}</span>
                </div>
                <span className="grade-badge">
                  {a.grade} • {a.grade_percent}%
                </span>
              </div>
              <div className="card-body">
                <div className="price-line">
                  <span className="price">${a.price?.toFixed(2)}</span>
                  {trendArrow(a.symbol, a.price)}
                </div>
                <div className="meta text-secondary">
                  Prediction: <b>{a.prediction}</b> | Stop-Loss: ${a.stop_loss}
                </div>
                <div className="meta text-secondary">
                  Confidence: {a.confidence}% • {formatTime(a.timestamp)}
                </div>
                <div className="summary text-muted">“{a.summary}”</div>
              </div>
            </div>
          ))}
        </div>

        {/* RIGHT COLUMN — CHART */}
        <div className="column chart">
          <h2>📊 Chart</h2>
          <iframe
            src={`https://s.tradingview.com/widgetembed/?symbol=${selectedSymbol}&interval=30&theme=light`}
            className="chart-frame"
            title="Astra Chart"
          ></iframe>
        </div>
      </div>
    </div>
  );
}
