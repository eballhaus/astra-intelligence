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
  if (!Number.isFinite(value) || value <= 0) return "Price unavailable";
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

function clampScore(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

function symbolGlyph(symbol) {
  const s = String(symbol || "").toUpperCase();
  if (s === "BTC") return "₿";
  if (s === "VIX") return "V";
  return s.slice(0, 1) || "A";
}

function scoreTone(score) {
  const n = clampScore(score);
  if (n >= 65) return { fg: "#0f8b55", bg: "#e8f7ee", bar: "#1eae6f" };
  if (n >= 45) return { fg: "#2255a4", bg: "#edf4ff", bar: "#2b76ff" };
  return { fg: "#b56c0d", bg: "#fff3df", bar: "#d88a19" };
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
          const isScore = market?.valueKind === "score";
          const hasValue = Boolean(market?.displayValue) || isScore || (Number.isFinite(Number(market?.value)) && Number(market.value) > 0);
          const hasChange = Number.isFinite(Number(market?.change));
          const change = hasChange ? safeNumber(market?.change, 0) : 0;
          const positive = isScore ? clampScore(market?.value) >= 50 : change >= 0;
          const tone = isScore ? scoreTone(market?.value) : { fg: positive ? "#149455" : "#d14b57", bg: positive ? "#e8f7ee" : "#fdebed", bar: positive ? "#149455" : "#d14b57" };
          const score = clampScore(market?.value);
          return (
            <div
              key={market.id || market.symbol}
              style={{
                borderRadius: 18,
                border: "1px solid #dbe6f2",
                background: "radial-gradient(120px 70px at 100% 0%, rgba(43, 118, 255, 0.10), transparent 70%), linear-gradient(180deg, #ffffff, #f8fbff)",
                padding: "10px 12px",
                display: "grid",
                gap: 6,
                minHeight: 84,
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: 12,
                      display: "grid",
                      placeItems: "center",
                      flex: "0 0 auto",
                      color: tone.fg,
                      background: tone.bg,
                      border: "1px solid rgba(19, 36, 58, 0.06)",
                      fontSize: 13,
                      fontWeight: 950,
                    }}
                  >
                    {symbolGlyph(market.symbol)}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: "#6c8098", fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.08em", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {market.name}
                    </div>
                    <div style={{ color: "#11243c", fontSize: 14, fontWeight: 950, marginTop: 2 }}>
                      {formatValue(market)}
                    </div>
                    {market?.detail ? (
                      <div style={{ color: "#6c8098", fontSize: 10.5, fontWeight: 750, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{market.detail}</div>
                    ) : null}
                  </div>
                </div>
                {hasValue && hasChange && !isScore ? (
                  <svg viewBox="0 0 48 28" width="48" height="28" aria-hidden="true">
                    <path d={sparkPath(change)} fill="none" stroke={positive ? "#149455" : "#d14b57"} strokeWidth="2.4" strokeLinecap="round" />
                  </svg>
                ) : isScore ? (
                  <div style={{ width: 48, display: "grid", gap: 4 }}>
                    <div style={{ height: 6, borderRadius: 999, background: "#e3ebf5", overflow: "hidden" }}>
                      <div style={{ width: `${score}%`, height: "100%", borderRadius: 999, background: tone.bar }} />
                    </div>
                    <span style={{ color: tone.fg, fontSize: 10, fontWeight: 900, textAlign: "right" }}>Context</span>
                  </div>
                ) : (
                  <span style={{ color: "#92a3b8", fontSize: 11, fontWeight: 800 }}>Unavailable</span>
                )}
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                {hasValue && hasChange && !isScore ? (
                  <span style={{ color: positive ? "#149455" : "#d14b57", fontWeight: 900, fontSize: 13 }}>
                    {positive ? "+" : ""}{change.toFixed(2)}%
                  </span>
                ) : (
                  <span style={{ color: tone.fg || "#52718f", fontWeight: 900, fontSize: 13 }}>{market?.sourceLabel || "Cached context"}</span>
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
