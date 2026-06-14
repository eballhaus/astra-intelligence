import React from "react";

function safeNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatValue(item) {
  if (item?.displayValue) return item.displayValue;
  if (item?.valueKind === "score") {
    const score = Number(item?.value);
    if (!Number.isFinite(score)) return "Score unavailable";
    return `${score.toFixed(1)}`;
  }
  const value = Number(item?.value);
  if (!Number.isFinite(value) || value <= 0) return "Data Not Available";
  const digits = item?.symbol === "VIX" ? 2 : 2;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function sparkPath(change) {
  const normalized = Math.max(-4, Math.min(4, safeNumber(change, 0)));
  const mid = 18 - normalized * 1.5;
  const tail = 9 - normalized * 2.2;
  return `M1 24 C 10 ${mid + 3}, 16 ${mid - 2}, 24 ${mid} S 38 ${tail + 2}, 47 ${tail}`;
}

export default function MarketSummary({ markets = [], asOf = "n/a", marketSession = "market context" }) {
  const incoming = Array.isArray(markets) ? markets : [];
  const rows = incoming.filter(Boolean).slice(0, 6);
  const unavailable = rows.length === 0;

  return (
    <div
      style={{
        display: "grid",
        gap: 10,
      }}
      data-testid="market-summary"
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span
            style={{
              borderRadius: 999,
              padding: "6px 10px",
              fontSize: 11,
              fontWeight: 900,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              background: "#edf4ff",
              color: "#2255a4",
              border: "1px solid #d8e4f4",
            }}
          >
            {marketSession}
          </span>
          <span style={{ color: "#6c8098", fontSize: 12 }}>Executive market pulse</span>
        </div>
        <span style={{ color: "#6c8098", fontSize: 12 }}>Last updated {asOf}</span>
      </div>

      {unavailable ? (
        <div style={{ border: "1px dashed #cbd8e8", borderRadius: 16, background: "#f7fbff", color: "#536a85", padding: "12px 14px", fontSize: 13, fontWeight: 800 }}>
          Market data source unavailable. Astra will show cached index, breadth, and sector context when available.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(148px, 1fr))",
            gap: 10,
          }}
        >
        {rows.map((market) => {
          const hasValue = Boolean(market?.displayValue) || market?.valueKind === "score" || (Number.isFinite(Number(market?.value)) && Number(market.value) > 0);
          const hasChange = Number.isFinite(Number(market?.change));
          const change = hasChange ? safeNumber(market?.change, 0) : 0;
          const positive = change >= 0;
          return (
            <div
              key={market.id || market.symbol}
              style={{
                borderRadius: 18,
                border: "1px solid #dbe6f2",
                background: "linear-gradient(180deg, #ffffff, #f8fbff)",
                padding: "10px 12px",
                display: "grid",
                gap: 6,
                minHeight: 76,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <div>
                  <div style={{ color: "#6c8098", fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                    {market.name}
                  </div>
                  <div style={{ color: "#11243c", fontSize: 12, fontWeight: 900, marginTop: 2 }}>
                    {formatValue(market)}
                  </div>
                  {market?.detail ? (
                    <div style={{ color: "#6c8098", fontSize: 10.5, fontWeight: 750, marginTop: 2 }}>{market.detail}</div>
                  ) : null}
                </div>
                {hasValue && hasChange ? (
                  <svg viewBox="0 0 48 28" width="48" height="28" aria-hidden="true">
                    <path d={sparkPath(change)} fill="none" stroke={positive ? "#149455" : "#d14b57"} strokeWidth="2.4" strokeLinecap="round" />
                  </svg>
                ) : (
                  <span style={{ color: "#92a3b8", fontSize: 11, fontWeight: 800 }}>{market?.valueKind === "score" ? "Score" : "Unavailable"}</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                {hasValue && hasChange ? (
                  <span style={{ color: positive ? "#149455" : "#d14b57", fontWeight: 900, fontSize: 13 }}>
                    {positive ? "+" : ""}{change.toFixed(2)}%
                  </span>
                ) : (
                  <span style={{ color: "#52718f", fontWeight: 900, fontSize: 13 }}>{market?.sourceLabel || "Cached context"}</span>
                )}
                <span style={{ color: "#92a3b8", fontSize: 11 }}>{market.symbol}</span>
              </div>
            </div>
          );
        })}
        </div>
      )}
    </div>
  );
}
