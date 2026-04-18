import React from "react";

// MarketSummary.jsx - Phase 2 feature
// TEMPORARY: Uses mock data. Will connect to /api/market_overview in Phase 2.1
// TEMPORARY: Inline styles for mock-up. Will migrate to CSS/Tailwind in Phase 2.2

export default function MarketSummary({ markets = [] }) {
  const fallbackMarkets = [
    { id: "sp500", symbol: "SPX", name: "S&P 500", value: 4927.35, change: 0.83, type: "index" },
    { id: "dow", symbol: "DJI", name: "DOW", value: 38121.27, change: -0.25, type: "index" },
    { id: "nasdaq", symbol: "NDX", name: "NASDAQ", value: 15312.77, change: 1.12, type: "index" },
    { id: "bitcoin", symbol: "BTC", name: "Bitcoin", value: 47805.22, change: 0.58, type: "crypto" },
  ];
  const marketRows = Array.isArray(markets) && markets.length > 0 ? markets : fallbackMarkets;

  const formatMarketItem = (item) => {
    const isUp = item.change >= 0;
    const arrow = isUp ? "▲" : "▼";
    const color = isUp ? "green" : "red";
    const formattedValue = item.value.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
    const formattedChange = Math.abs(item.change).toFixed(2);
    return { arrow, color, formattedValue, formattedChange, isUp };
  };

  return (
    <div
      className="market-summary-bar"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(165px, 1fr))",
        gap: "0.6rem",
      }}
      data-testid="market-summary"
    >
      {marketRows.map((market) => {
        const { arrow, color, formattedValue, formattedChange } = formatMarketItem(market);
        return (
          <div
            key={market.id}
            className="market-item"
            style={{
              display: "grid",
              gap: "0.25rem",
              alignItems: "center",
              border: "1px solid #d8e1ee",
              borderRadius: "10px",
              background: "#ffffff",
              padding: "0.5rem 0.65rem",
              boxShadow: "0 8px 20px rgba(8, 20, 40, 0.12)",
            }}
            data-symbol={market.symbol}
            data-type={market.type}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 700, color: "#1c2f49", fontSize: "0.78rem" }}>{market.name}</span>
              <span style={{ color: "#627a97", fontSize: "0.72rem" }}>{market.symbol}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ color: "#11243a", fontWeight: 700, fontSize: "0.92rem" }}>${formattedValue}</span>
              <span style={{ color, fontWeight: 700, fontSize: "0.78rem" }}>{arrow} {formattedChange}%</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
