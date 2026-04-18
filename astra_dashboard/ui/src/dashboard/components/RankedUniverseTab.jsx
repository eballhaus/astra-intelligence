import React, { useEffect, useState } from "react";
import TickerGrid from "./TickerGrid";
import { API_BASE_CHANGED_EVENT, fetchJsonWithFallback, getInitialApiBase } from "../../apiBase";

const containerStyle = {
  display: "grid",
  gap: "12px",
  width: "100%",
};

const statusStyle = {
  color: "#9fb0ca",
  fontSize: "0.92rem",
};

function annotateRows(rows, topBuys) {
  const topActionViews = (topBuys?.top_action_views || {});
  const symbolDecisions = (topActionViews?.canonical_symbol_decisions || {});
  return (Array.isArray(rows) ? rows : []).map((row) => {
    const sym = String(row?.symbol || "").toUpperCase();
    const decision = symbolDecisions?.[sym];
    if (!decision) return row;
    const action = String(row?.action || row?.prediction || "").toUpperCase();
    if (action.startsWith("BUY")) return row;
    const state = String(decision?.canonical_final_state || "").toLowerCase();
    let explanation = "broader universe hold, shortlist buy candidate";
    if (state === "released_buy") explanation = "shortlist released buy from canonical engine";
    else if (state === "paper_ready") explanation = "buy candidate but not fully actionable";
    else if (state === "watchlist") explanation = "buy candidate currently watchlist-only";
    else if (state === "rejected") explanation = "buy candidate blocked by canonical release gate";
    return {
      ...row,
      ranked_universe_action_explanation: explanation,
      hero_deployment_status: decision?.hero_deployment_status || "paper-ready",
      canonical_final_state: decision?.canonical_final_state || "",
    };
  });
}

export default function RankedUniverseTab() {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [stocks, setStocks] = useState([]);
  const [cryptos, setCryptos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const syncBase = () => setResolvedApiBase(getInitialApiBase());
    window.addEventListener(API_BASE_CHANGED_EVENT, syncBase);
    return () => window.removeEventListener(API_BASE_CHANGED_EVENT, syncBase);
  }, []);

  const fetchRankings = async () => {
    try {
      setLoading(true);
      const [stocksRes, cryptoRes, topBuysRes] = await Promise.all([
        fetchJsonWithFallback("/api/rankings", {
          preferredBase: resolvedApiBase,
          fallbackValue: [],
          timeoutMs: 20000,
        }),
        fetchJsonWithFallback("/api/crypto_rankings", {
          preferredBase: resolvedApiBase,
          fallbackValue: [],
          timeoutMs: 20000,
        }),
        fetchJsonWithFallback("/api/top_buys?buy_mode=balanced", {
          preferredBase: resolvedApiBase,
          fallbackValue: {},
          timeoutMs: 45000,
        }),
      ]);

      let stocksJson = null;
      if (stocksRes.ok) {
        const parsed = stocksRes.parsed;
        if (Array.isArray(parsed)) {
          stocksJson = parsed;
          console.log("[Astra] /api/rankings raw response", parsed);
        }
      }

      let cryptoJson = null;
      if (cryptoRes.ok) {
        const parsed = cryptoRes.parsed;
        if (Array.isArray(parsed)) {
          cryptoJson = parsed;
        }
      }

      if (stocksRes.ok && stocksRes.baseUsed && stocksRes.baseUsed !== resolvedApiBase) {
        setResolvedApiBase(stocksRes.baseUsed);
      } else if (cryptoRes.ok && cryptoRes.baseUsed && cryptoRes.baseUsed !== resolvedApiBase) {
        setResolvedApiBase(cryptoRes.baseUsed);
      }

      if (stocksJson === null && cryptoJson === null) {
        throw new Error("No rankings endpoints available");
      }

      const topBuys = topBuysRes?.parsed || {};
      if (stocksJson !== null) {
        setStocks(annotateRows(stocksJson, topBuys));
      }
      if (cryptoJson !== null) {
        setCryptos(annotateRows(cryptoJson, topBuys));
      }
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err || "Live feed interrupted");
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRankings();
    const timer = setInterval(fetchRankings, 15000);
    return () => clearInterval(timer);
  }, [resolvedApiBase]);

  return (
    <div style={containerStyle}>
      {loading && <div style={statusStyle}>Loading rankings...</div>}
      {error && <div style={statusStyle}>Backend offline or rankings endpoint unreachable.</div>}
      {!loading && !error && stocks.length === 0 && cryptos.length === 0 && (
        <div style={statusStyle}>Backend online, but no valid quotes/rankings are available in this cycle.</div>
      )}
      <TickerGrid stocks={stocks} cryptos={cryptos} />
    </div>
  );
}
