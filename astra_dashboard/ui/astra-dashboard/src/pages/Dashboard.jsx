import React, { useEffect, useState, useRef } from "react";

export default function Dashboard() {
  const [liveData, setLiveData] = useState([]);
  const [selectedSymbol, setSelectedSymbol] = useState("AAPL");
  const prevPrices = useRef({});

  useEffect(() => {
    const loadData = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/api/top_signals");
        let data = await res.json();

        if (data && data.signals && typeof data.signals === "object") {
          data = Object.values(data.signals);
        }

        setLiveData(data);
      } catch (err) {
        console.error("Live data fetch failed", err);
      }
    };

    loadData();
    const REFRESH_INTERVAL = 10000;
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

  const stocks =
    liveData?.top_stocks ||
    liveData?.filter?.(
      (a) =>
        !a.symbol?.toUpperCase?.().includes("BTC") &&
        !a.symbol?.toUpperCase?.().includes("ETH")
    ) ||
    [];

  const cryptos =
    liveData?.top_cryptos ||
    liveData?.filter?.(
      (a) =>
        a.symbol?.toUpperCase?.().includes("BTC") ||
        a.symbol?.toUpperCase?.().includes("ETH")
    ) ||
    [];

  return (
    <div className="dashboard-container">
      <header className="astra-header">
        🧠 Astra Intelligence — Live Dashboard
      </header>

      <div className="columns">
        <div className="column stocks">
          <h2>📈 Stocks</h2>
          {stocks.length === 0 ? (
            <div className="placeholder">No stock data available.</div>
          ) : (
            stocks.map((a, i) => (
              <div
                key={`stock-${i}`}
                className={`astra-card white-card ${flashClass(
                  a.symbol,
                  a.price
                )}`}
                onClick={() => setSelectedSymbol(a.symbol)}
              >
                <div className="card-header">
                  <div className="logo-symbol">
                    <span className="symbol">{a.symbol || "--"}</span>
                  </div>
                  <span className="grade-badge">
                    {a.grade || "--"} • {a.confidence?.toFixed?.(1) || "--"}%
                  </span>
                </div>
                <div className="card-body">
                  <div className="price-line">
                    <span className="price">
                      ${a.price?.toFixed?.(2) || "--"}
                    </span>
                    {trendArrow(a.symbol, a.price)}
                  </div>
                  <div className="meta text-secondary">
                    Prediction: <b>{a.prediction || "--"}</b>
                  </div>
                  <div className="meta text-secondary">
                    Confidence: {a.confidence?.toFixed?.(1) || "--"}%
                  </div>
                  <div className="summary text-muted">
                    “{a.reason || "No insight"}”
                  </div>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="column cryptos">
          <h2>💰 Crypto</h2>
          {cryptos.length === 0 ? (
            <div className="placeholder">No crypto data available.</div>
          ) : (
            cryptos.map((a, i) => (
              <div
                key={`crypto-${i}`}
                className={`astra-card white-card ${flashClass(
                  a.symbol,
                  a.price
                )}`}
                onClick={() => setSelectedSymbol(a.symbol)}
              >
                <div className="card-header">
                  <div className="logo-symbol">
                    <span className="symbol">{a.symbol || "--"}</span>
                  </div>
                  <span className="grade-badge">
                    {a.grade || "--"} • {a.confidence?.toFixed?.(1) || "--"}%
                  </span>
                </div>
                <div className="card-body">
                  <div className="price-line">
                    <span className="price">
                      ${a.price?.toFixed?.(2) || "--"}
                    </span>
                    {trendArrow(a.symbol, a.price)}
                  </div>
                  <div className="meta text-secondary">
                    Prediction: <b>{a.prediction || "--"}</b>
                  </div>
                  <div className="meta text-secondary">
                    Confidence: {a.confidence?.toFixed?.(1) || "--"}%
                  </div>
                  <div className="summary text-muted">
                    “{a.reason || "No insight"}”
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
console.log("ASTRA LIVE DATA SAMPLE", JSON.stringify(data).slice(0,200));
