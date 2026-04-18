import React, { useEffect, useState } from "react";
import TickerCard from "./TickerCard";

const wrapperBaseStyle = {
  display: "grid",
  gap: "12px",
  width: "100%",
};

const columnStyle = {
  background: "rgba(255, 255, 255, 0.08)",
  border: "1px solid rgba(215, 227, 244, 0.35)",
  borderRadius: "12px",
  padding: "10px",
  display: "grid",
  gap: "9px",
};

const headingStyle = {
  margin: 0,
  color: "#e7f0ff",
  fontSize: "0.9rem",
  fontWeight: 700,
};

const listStyle = {
  display: "grid",
  gap: "10px",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  alignItems: "start",
};

const emptyStyle = {
  color: "#b9c8de",
  fontSize: "0.86rem",
  padding: "8px 0",
};

export default function TickerGrid({
  stocks = [],
  cryptos = [],
  stockTitle = "Top Stocks",
  cryptoTitle = "Top Crypto",
  showCryptoColumn = true,
  emptyText = "No rankings available",
  cardContext = "default",
  compact = false,
  onAddPosition,
  onAddCryptoPosition,
  positionActionState = {},
}) {
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth <= 900);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const safeStocks = Array.isArray(stocks) ? stocks.slice(0, 6) : [];
  const safeCryptos = Array.isArray(cryptos) ? cryptos.slice(0, 6) : [];

  return (
    <section style={{ ...wrapperBaseStyle, gridTemplateColumns: mobile || !showCryptoColumn ? "1fr" : "repeat(2, minmax(0, 1fr))" }}>
      <div style={columnStyle}>
        <h3 style={headingStyle}>{stockTitle}</h3>
        {safeStocks.length === 0 ? (
          <div style={emptyStyle}>{emptyText}</div>
        ) : (
          <div style={listStyle}>
            {safeStocks.map((item, idx) => (
              <TickerCard
                key={`${item?.symbol ?? "stock"}-${idx}`}
                item={item}
                context={cardContext}
                compact
                onAddPosition={onAddPosition}
                positionState={positionActionState?.[String(item?.symbol || "").toUpperCase()] || "idle"}
              />
            ))}
          </div>
        )}
      </div>

      {showCryptoColumn ? (
        <div style={columnStyle}>
          <h3 style={headingStyle}>{cryptoTitle}</h3>
          {safeCryptos.length === 0 ? (
            <div style={emptyStyle}>{emptyText}</div>
          ) : (
            <div style={listStyle}>
              {safeCryptos.map((item, idx) => (
                <TickerCard
                  key={`${item?.symbol ?? "crypto"}-${idx}`}
                  item={item}
                  context={cardContext}
                  compact
                  onAddPosition={onAddCryptoPosition || onAddPosition}
                  positionState={positionActionState?.[String(item?.symbol || "").toUpperCase()] || "idle"}
                />
              ))}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
