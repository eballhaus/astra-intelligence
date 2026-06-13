import React, { useEffect, useState } from "react";
import TickerCard from "./TickerCard";

const wrapperBaseStyle = {
  display: "grid",
  gap: "12px",
  width: "100%",
};

const columnStyle = {
  background: "#f7fbff",
  border: "1px solid #d8e3f2",
  borderRadius: "18px",
  padding: "12px",
  display: "grid",
  gap: "9px",
};

const headingStyle = {
  margin: 0,
  color: "#13243a",
  fontSize: "0.9rem",
  fontWeight: 900,
};

const listStyle = {
  display: "grid",
  gap: "10px",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  alignItems: "start",
};

const emptyStyle = {
  color: "#667994",
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

  const actionRank = (row) => {
    const status = String(
      row?.hero_card_deployment_label
      || row?.hero_deployment_status
      || row?.canonical_release_state
      || row?.canonical_final_state
      || ""
    ).toLowerCase();
    if (status.includes("paper-ready") || status.includes("paper_ready") || status.includes("released_buy")) return 0;
    if (status.includes("watchlist") || status.includes("monitor-only") || status.includes("monitor_only")) return 1;
    return 2;
  };
  const scoreValue = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const sortedStocks = Array.isArray(stocks)
    ? [...stocks].sort((a, b) => {
        const ar = actionRank(a);
        const br = actionRank(b);
        if (ar !== br) return ar - br;
        const ac = scoreValue(a?.rolling_conviction_10r ?? a?.conviction_display_score);
        const bc = scoreValue(b?.rolling_conviction_10r ?? b?.conviction_display_score);
        if (bc !== ac) return bc - ac;
        const ap = scoreValue(a?.profit_prediction_pct ?? a?.expected_move_pct ?? a?.expected_move_percent ?? a?.predicted_return_pct);
        const bp = scoreValue(b?.profit_prediction_pct ?? b?.expected_move_pct ?? b?.expected_move_percent ?? b?.predicted_return_pct);
        if (bp !== ap) return bp - ap;
        const aq = scoreValue(a?.buy_quality_score ?? a?.trade_quality_score ?? a?.grade_percent);
        const bq = scoreValue(b?.buy_quality_score ?? b?.trade_quality_score ?? b?.grade_percent);
        if (bq !== aq) return bq - aq;
        const aconf = scoreValue(a?.confidence);
        const bconf = scoreValue(b?.confidence);
        return bconf - aconf;
      })
    : [];
  const safeStocks = sortedStocks.slice(0, 6);
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
