import React from "react";

// MarketSummary.jsx - Phase 2 feature
// TEMPORARY: Uses mock data. Will connect to /api/market_overview in Phase 2.1
// TEMPORARY: Inline styles for mock-up. Will migrate to CSS/Tailwind in Phase 2.2

export default function MarketSummary() {
  const mockMarkets = [
    { id: "sp500", symbol: "SPX", name: "S&P 500", value: 4927.35, change: 0.83, type: "index" },
    { id: "dow", symbol: "DJI", name: "DOW", value: 38121.27, change: -0.25, type: "index" },
    { id: "nasdaq", symbol: "NDX", name: "NASDAQ", value: 15312.77, change: 1.12, type: "index" },
    { id: "bitcoin", symbol: "BTC", name: "Bitcoin", value: 47805.22, change: 0.58, type: "crypto" },
  ];

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
        display: "flex",
        flexWrap: "wrap",
        justifyContent: "center",
        alignItems: "center",
        gap: "1.5rem",
        fontSize: "0.95rem",
        marginTop: "0.4rem",
        marginBottom: "1rem",
      }}
      data-testid="market-summary"
    >
      {mockMarkets.map((market) => {
        const { arrow, color, formattedValue, formattedChange } = formatMarketItem(market);
        return (
          <div
            key={market.id}
            className="market-item"
            style={{
              display: "flex",
              gap: "0.3rem",
              alignItems: "center",
            }}
            data-symbol={market.symbol}
            data-type={market.type}
          >
            <span style={{ fontWeight: "bold" }}>{market.name}:</span>
            <span>${formattedValue}</span>
            <span style={{ color }}>{arrow}</span>
            <span style={{ color }}>{formattedChange}%</span>
          </div>
        );
      })}
    </div>
  );
}
