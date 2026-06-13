import React, { useEffect, useMemo, useState } from "react";
import {
  API_BASE_CHANGED_EVENT,
  fetchJsonWithFallback,
  getInitialApiBase,
  resolveApiBase,
} from "../../apiBase";
import MarketSummary from "../components/MarketSummary";
import TickerGrid from "../components/TickerGrid";
import TickerCard from "../components/TickerCard";

const API_BASE = resolveApiBase();

const shellStyle = {
  display: "grid",
  gap: "16px",
};

const panelStyle = {
  background: "#ffffff",
  border: "1px solid #d8e3f2",
  borderRadius: "22px",
  padding: "16px",
  boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)",
  color: "#13243a",
};

const panelTitleStyle = {
  margin: 0,
  fontSize: "1rem",
  color: "#13243a",
  fontWeight: 900,
};

const stripGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "8px",
};

const statusPillStyle = {
  borderRadius: "14px",
  border: "1px solid #d7e1ef",
  background: "#f7fbff",
  padding: "0.62rem 0.72rem",
  display: "grid",
  gap: "0.2rem",
};

const positionsGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  gap: "10px",
};

const emptyStyle = {
  color: "#667994",
  fontSize: "0.83rem",
  padding: "8px 0",
};

const insightGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
  gap: "14px",
};

function safeNumber(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function formatTimestamp(v) {
  const s = String(v || "").trim();
  if (!s) return "n/a";
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function labelize(value, fallback = "warming up") {
  const raw = String(value || fallback).trim();
  return (raw || fallback).replaceAll("_", " ");
}

function formatMoney(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "not available";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function formatSignedPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.00%";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function normalizeTopBuys(raw) {
  const stockFinal = Array.isArray(raw?.stocks?.final) ? raw.stocks.final : [];
  const cryptoFinal = Array.isArray(raw?.crypto?.final) ? raw.crypto.final : [];
  const stockReleased = Array.isArray(raw?.top_action_views?.canonical_release_views?.stocks_released_hero_buys)
    ? raw.top_action_views.canonical_release_views.stocks_released_hero_buys
    : [];
  const stockCandidates = Array.isArray(raw?.top_action_views?.canonical_decision_views?.stocks_buy_candidates)
    ? raw.top_action_views.canonical_decision_views.stocks_buy_candidates
    : [];
  const cryptoReleased = Array.isArray(raw?.top_action_views?.canonical_release_views?.crypto_released_hero_buys)
    ? raw.top_action_views.canonical_release_views.crypto_released_hero_buys
    : [];
  const stocksPrimary = stockFinal.length > 0 ? stockFinal : stockReleased;
  const stocks = [...stocksPrimary];
  const stockSeen = new Set(
    stocks
      .map((row) => String(row?.symbol || row?.ticker || "").trim().toUpperCase())
      .filter(Boolean),
  );
  if (stocks.length < 6) {
    for (const row of stockCandidates) {
      if (!row || typeof row !== "object") continue;
      const symbol = String(row?.symbol || row?.ticker || "").trim().toUpperCase();
      if (!symbol || stockSeen.has(symbol)) continue;
      stockSeen.add(symbol);
      stocks.push({
        ...row,
        dashboard_fallback_candidate: true,
      });
      if (stocks.length >= 6) break;
    }
  }
  const cryptos = cryptoFinal.length > 0 ? cryptoFinal : cryptoReleased;
  const mapRow = (row, kind) => {
    if (!row || typeof row !== "object") return null;
    return {
      ...row,
      type: row.type || row.asset_type || kind,
      symbol: row.symbol || row.ticker || "—",
      price: row.price ?? row.current_price ?? row.last_price ?? null,
      change_percent: row.change_percent ?? row.change_pct ?? row.percent_change ?? row.daily_change_pct ?? 0,
      confidence: row.confidence ?? row.buy_confidence ?? row.predicted_win_probability ?? 0,
      buy_quality_score: row.buy_quality_score ?? row.trade_quality_score ?? row.quality_score ?? 0,
      grade: row.grade ?? row.buy_grade ?? row.qualification ?? row.buy_eligibility ?? "N/A",
      stop_loss: row.stop_loss ?? row.stop_price ?? row.stop ?? null,
      timestamp: row.timestamp || row.updated_at || row.last_quote_utc || "",
      why_this_is_a_buy: row.why_this_is_a_buy || row.rationale || row.summary || row.buy_reason || "",
      dashboard_fallback_candidate: Boolean(row.dashboard_fallback_candidate),
    };
  };
  return {
    stocks: stocks.map((r) => mapRow(r, "stock")).filter(Boolean).slice(0, 6),
    cryptos: cryptos.map((r) => mapRow(r, "crypto")).filter(Boolean).slice(0, 6),
  };
}

function normalizePositions(raw) {
  const rows = Array.isArray(raw?.positions)
    ? raw.positions
    : (Array.isArray(raw?.open_positions) ? raw.open_positions : []);
  return rows.map((row) => ({
    ...row,
    symbol: row.symbol || row.ticker || "—",
    price: row.current_price ?? row.price ?? row.mark_price ?? null,
    current_price: row.current_price ?? row.latest_price ?? row.price ?? row.mark_price ?? null,
    entry_price: row.entry_price ?? row.avg_entry_price ?? row.average_entry_price ?? null,
    pnl_percent: row.pnl_percent ?? row.unrealized_pnl_percent ?? row.return_percent ?? 0,
    confidence:
      row.confidence
      ?? row.position_confidence
      ?? (Number.isFinite(Number(row.current_predicted_probability))
        ? (Number(row.current_predicted_probability) * 100.0)
        : 0),
    buy_quality_score: row.buy_quality_score ?? row.trade_quality_score ?? row.quality_score ?? 0,
    stop_loss: row.stop_loss ?? row.stop ?? row.stop_price ?? null,
    status: row.status ?? row.position_status ?? "open",
    timestamp: row.updated_at || row.last_update_ts || row.opened_at || row.entry_timestamp || row.timestamp || "",
    management_note:
      row.management_note
      || row.rationale
      || row.exit_hint
      || row.current_risk_sell_posture
      || row.position_lifecycle_state
      || row.note
      || "",
  }));
}

function normalizeMarketSummary(systemStatus = {}) {
  const markets = systemStatus?.market_summary || systemStatus?.market_overview || systemStatus?.indices || {};
  const get = (keys = []) => {
    for (const key of keys) {
      const v = markets?.[key];
      if (v && typeof v === "object") return v;
    }
    return null;
  };
  const map = (id, symbol, name, keys) => {
    const src = get(keys);
    return {
      id,
      symbol,
      name,
      value: safeNumber(src?.value ?? src?.price ?? src?.last, 0),
      change: safeNumber(src?.change ?? src?.change_percent ?? src?.percent_change ?? 0, 0),
      type: id === "bitcoin" ? "crypto" : "index",
    };
  };
  const rows = [
    map("sp500", "SPX", "S&P 500", ["sp500", "spx", "s_and_p_500"]),
    map("dow", "DJI", "DOW", ["dow", "dji"]),
    map("nasdaq", "NDX", "NASDAQ", ["nasdaq", "ndx"]),
    map("bitcoin", "BTC", "Bitcoin", ["bitcoin", "btc"]),
  ];
  const hasReal = rows.some((r) => Number.isFinite(Number(r.value)) && Number(r.value) > 0);
  return hasReal ? rows : [];
}

export default function Dashboard({ remoteSection = "dashboard", remoteMode = false, onNavigate }) {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [endpointStatus, setEndpointStatus] = useState({});
  const [topBuys, setTopBuys] = useState({});
  const [systemStatus, setSystemStatus] = useState({});
  const [positions, setPositions] = useState([]);
  const [positionsMeta, setPositionsMeta] = useState({});
  const [isMobileView, setIsMobileView] = useState(false);
  const [positionActionState, setPositionActionState] = useState({});
  const [positionRemoveState, setPositionRemoveState] = useState({});

  useEffect(() => {
    const syncBase = () => setResolvedApiBase(getInitialApiBase());
    window.addEventListener(API_BASE_CHANGED_EVENT, syncBase);
    return () => window.removeEventListener(API_BASE_CHANGED_EVENT, syncBase);
  }, []);

  useEffect(() => {
    const onResize = () => setIsMobileView(window.innerWidth <= 760);
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let mounted = true;
    let busy = false;

    const fetchJson = async (key, path, fallback, timeoutMs) => {
      const result = await fetchJsonWithFallback(path, {
        preferredBase: resolvedApiBase || API_BASE,
        fallbackValue: fallback,
        timeoutMs,
      });
      return {
        key,
        ok: result.ok,
        parsed: result.parsed,
        error: result.error || "",
        status: result.httpStatus,
      };
    };

    const refresh = async () => {
      if (busy) return;
      busy = true;
      setLoading(true);
      const outcomes = await Promise.all([
        fetchJson("top_buys", "/api/top_buys?buy_mode=balanced", {}, 45000),
        fetchJson("system_status", "/api/system_status", {}, 15000),
        fetchJson("positions", "/api/positions", {}, 15000),
      ]);
      if (!mounted) return;
      const byKey = Object.fromEntries(outcomes.map((o) => [o.key, o]));
      const statusMap = {};
      const errors = [];
      outcomes.forEach((o) => {
        statusMap[o.key] = { ok: o.ok, status: o.status, error: o.error };
        if (!o.ok) errors.push(`${o.key}: ${o.error || "fetch_failed"}`);
      });
      setEndpointStatus(statusMap);
      setError(errors.join(" | "));
      if (byKey.top_buys?.ok && byKey.top_buys?.parsed) setTopBuys(byKey.top_buys.parsed || {});
      if (byKey.system_status?.ok && byKey.system_status?.parsed) setSystemStatus(byKey.system_status.parsed || {});
      if (byKey.positions?.ok && byKey.positions?.parsed) {
        const parsedPositions = byKey.positions.parsed || {};
        setPositions(normalizePositions(parsedPositions));
        setPositionsMeta(parsedPositions.mobile_runtime_compaction || {});
      }
      setLoading(false);
      busy = false;
    };

    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [resolvedApiBase]);

  const { stocks } = useMemo(() => normalizeTopBuys(topBuys), [topBuys]);
  const openPositionSymbols = useMemo(
    () => new Set((positions || []).map((p) => String(p?.symbol || "").toUpperCase()).filter(Boolean)),
    [positions]
  );
  const effectivePositionActionState = useMemo(() => {
    const out = { ...(positionActionState || {}) };
    openPositionSymbols.forEach((sym) => {
      out[sym] = "added";
    });
    return out;
  }, [positionActionState, openPositionSymbols]);
  const marketSummary = useMemo(() => normalizeMarketSummary(systemStatus), [systemStatus]);
  const runtimeIntegrity = Boolean(
    systemStatus?.runtime_integrity_ok
    ?? systemStatus?.runtime_integrity_status?.runtime_integrity_ok
  );
  const backendStatus = endpointStatus?.system_status?.ok
    ? "online"
    : "degraded";
  const validQuotes = safeNumber(systemStatus?.live_buy_valid_quote_count, 0);
  const universeSize = safeNumber(systemStatus?.live_buy_universe_size, 0);
  const quotesStatus = universeSize > 0
    ? `${validQuotes}/${universeSize} live`
    : (validQuotes > 0 ? `${validQuotes} live` : "no live quotes");
  const readiness = runtimeIntegrity
    ? (safeNumber(systemStatus?.final_ranked_count, 0) > 0 ? "ranked-ready" : "minimal-payload")
    : "degraded";
  const asOf = formatTimestamp(systemStatus?.last_updated_utc || topBuys?.last_updated_utc || "");
  const activePreviewLimit = isMobileView
    ? safeNumber(positionsMeta?.active_positions_preview_limit, 5)
    : safeNumber(positionsMeta?.desktop_active_positions_preview_limit, 10);
  const displayedPositions = useMemo(
    () => (Array.isArray(positions) ? positions.slice(0, activePreviewLimit) : []),
    [positions, activePreviewLimit],
  );
  const hiddenPositionCount = Math.max(
    0,
    safeNumber(positionsMeta?.display_active_positions_count, positions.length) - displayedPositions.length,
  );
  const brokerTruthKnown = positionsMeta?.true_broker_active_positions !== undefined && positionsMeta?.true_broker_active_positions !== null;
  const brokerActiveCount = safeNumber(positionsMeta?.true_broker_active_positions, positions.length);
  const staleRowsHidden = safeNumber(positionsMeta?.stale_rows_hidden_count, 0);
  const canceledOrdersCompacted = safeNumber(positionsMeta?.canceled_orders_compacted_count, 0);
  const compactionSummary = String(
    positionsMeta?.summary
      || (brokerTruthKnown && brokerActiveCount === 0
        ? "No broker-confirmed active positions."
        : "Active position display is compacted for mobile runtime speed.")
  );

  const topSection = remoteMode
    ? (remoteSection === "positions" ? "positions" : "buys")
    : "dashboard";
  const highConfidenceCount = stocks.filter((row) => safeNumber(row?.confidence) >= 70).length;
  const bestOpportunity = stocks[0] || {};
  const strongestTheme = labelize(
    bestOpportunity?.theme
      || bestOpportunity?.catalyst
      || bestOpportunity?.sector
      || systemStatus?.leadership_theme
      || "technology and quality momentum",
  );
  const marketTone = runtimeIntegrity && highConfidenceCount >= 2
    ? "Constructive"
    : runtimeIntegrity
    ? "Neutral"
    : "Cautious";
  const volatilityStatus = safeNumber(systemStatus?.vix, 0) > 25
    ? "elevated"
    : labelize(systemStatus?.volatility_status || "controlled");
  const breadthStatus = labelize(systemStatus?.breadth_status || (validQuotes > 0 ? "active coverage" : "warming up"));
  const riskMode = marketTone === "Cautious" ? "risk-off / selective" : "risk-on / selective";
  const astraBrief = `Markets look ${marketTone.toLowerCase()} from Astra's cached dashboard view. ${strongestTheme} is the current leadership context, volatility is ${volatilityStatus}, and Astra sees ${highConfidenceCount} high-confidence opportunity${highConfidenceCount === 1 ? "" : "ies"} while portfolio risk remains ${brokerActiveCount > 8 ? "elevated" : "moderate"}.`;
  const portfolioValue = formatMoney(positionsMeta?.portfolio_value ?? positionsMeta?.total_value ?? systemStatus?.portfolio_value);
  const cashValue = formatMoney(positionsMeta?.cash ?? positionsMeta?.buying_power ?? systemStatus?.cash);
  const sortedByPnl = [...positions].sort((a, b) => safeNumber(b?.pnl_percent) - safeNumber(a?.pnl_percent));
  const biggestWinner = sortedByPnl[0];
  const biggestLoser = sortedByPnl[sortedByPnl.length - 1];
  const avgPositionPnl = positions.length
    ? positions.reduce((sum, row) => sum + safeNumber(row?.pnl_percent), 0) / positions.length
    : 0;
  const performanceHealth = runtimeIntegrity && highConfidenceCount > 0 ? "healthy" : runtimeIntegrity ? "warming up" : "needs attention";
  const actionItems = [
    `${highConfidenceCount} high-confidence cached opportunit${highConfidenceCount === 1 ? "y" : "ies"} visible.`,
    `Primary market risk: ${runtimeIntegrity ? "watch volatility, breadth, and failed follow-through" : "runtime integrity is degraded"}.`,
    brokerActiveCount > 0 ? `Portfolio: ${brokerActiveCount} broker-confirmed active position${brokerActiveCount === 1 ? "" : "s"}.` : "Portfolio: no broker-confirmed active positions.",
    `Next review focus: ${highConfidenceCount > 0 ? "validate why Astra likes the top opportunities" : "wait for cleaner opportunity evidence"}.`,
  ];
  const watchingItems = [
    strongestTheme,
    `Sector/breadth context: ${breadthStatus}`,
    `Volatility: ${volatilityStatus}`,
    `Symbols: ${stocks.slice(0, 5).map((row) => row.symbol).filter(Boolean).join(", ") || "warming up"}`,
  ];

  const refreshPositions = async () => {
    const result = await fetchJsonWithFallback("/api/positions", {
      preferredBase: resolvedApiBase || API_BASE,
      fallbackValue: {},
      timeoutMs: 15000,
    });
    if (result.ok && result.parsed) {
      setPositions(normalizePositions(result.parsed || {}));
      setPositionsMeta((result.parsed || {}).mobile_runtime_compaction || {});
      return true;
    }
    return false;
  };

  const handleAddPosition = async (item) => {
    const symbol = String(item?.symbol || item?.ticker || "").toUpperCase().trim();
    if (!symbol) return;
    if (openPositionSymbols.has(symbol)) {
      setPositionActionState((prev) => ({ ...(prev || {}), [symbol]: "added" }));
      return;
    }
    setPositionActionState((prev) => ({ ...(prev || {}), [symbol]: "working" }));
    const payload = {
      symbol,
      asset_type: "stocks",
      entry_price: Number.isFinite(Number(item?.price)) ? Number(item.price) : undefined,
      notes: "Added from dashboard top stock opportunity card",
      mode: "intraday",
    };
    const res = await fetchJsonWithFallback("/api/positions/open", {
      preferredBase: resolvedApiBase || API_BASE,
      fallbackValue: { ok: false },
      timeoutMs: 15000,
      init: {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      },
    });
    const ok = Boolean(res.ok && res.parsed && res.parsed.ok);
    if (ok) {
      setPositionActionState((prev) => ({ ...(prev || {}), [symbol]: "added" }));
      await refreshPositions();
    } else {
      setPositionActionState((prev) => ({ ...(prev || {}), [symbol]: "failed" }));
    }
  };

  const handleRemovePosition = async (item) => {
    const positionId = String(item?.position_id || "").trim();
    const symbol = String(item?.symbol || item?.ticker || "").toUpperCase().trim();
    const identifierRaw = positionId || symbol;
    const identifier = String(identifierRaw || "").trim().toUpperCase();
    if (!identifier) return;
    setPositionRemoveState((prev) => ({ ...(prev || {}), [identifier]: "working" }));
    const payload = positionId
      ? { position_id: positionId, exit_reason_manual: "dashboard_manual_untrack" }
      : { symbol, exit_reason_manual: "dashboard_manual_untrack" };
    const res = await fetchJsonWithFallback("/api/positions/close", {
      preferredBase: resolvedApiBase || API_BASE,
      fallbackValue: { ok: false },
      timeoutMs: 15000,
      init: {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      },
    });
    const ok = Boolean(res.ok && res.parsed && res.parsed.ok);
    if (ok) {
      setPositionRemoveState((prev) => ({ ...(prev || {}), [identifier]: "removed" }));
      await refreshPositions();
    } else {
      setPositionRemoveState((prev) => ({ ...(prev || {}), [identifier]: "failed" }));
    }
  };

  return (
    <div style={shellStyle}>
      <section style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", gap: "8px", flexWrap: "wrap" }}>
          <h2 style={{ ...panelTitleStyle, fontSize: "1rem" }}>Market Ticker Strip</h2>
          <span style={{ color: "#667994", fontSize: "0.78rem" }}>Last updated {asOf}</span>
        </div>
        <MarketSummary markets={marketSummary} />
      </section>

      {topSection === "dashboard" && (
        <>
          <section
            style={{
              borderRadius: 28,
              padding: "22px",
              background:
                "radial-gradient(420px 220px at 88% 10%, rgba(71, 139, 255, 0.30), transparent 70%), linear-gradient(135deg, #071a33 0%, #0d2c54 62%, #123e78 100%)",
              color: "#ffffff",
              boxShadow: "0 24px 60px rgba(6, 24, 48, 0.20)",
              display: "grid",
              gap: 10,
            }}
          >
            <div style={{ color: "#84b7ff", fontSize: 12, fontWeight: 900, letterSpacing: "0.12em", textTransform: "uppercase" }}>Astra Brief</div>
            <h2 style={{ margin: 0, fontSize: "clamp(1.45rem, 3vw, 2.35rem)", letterSpacing: "-0.04em" }}>What is happening now</h2>
            <p style={{ margin: 0, color: "#d6e5fb", maxWidth: 900, lineHeight: 1.55 }}>{astraBrief}</p>
          </section>

          <section style={insightGridStyle}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Market Environment</h2>
              <div style={stripGridStyle}>
                {[
                  ["Tone", marketTone],
                  ["Confidence", runtimeIntegrity ? "moderate" : "low"],
                  ["Risk mode", riskMode],
                  ["Volatility", volatilityStatus],
                  ["Breadth", breadthStatus],
                  ["Leadership", strongestTheme],
                ].map(([label, value]) => (
                  <div key={label} style={statusPillStyle}>
                    <span style={{ color: "#667994", fontSize: "0.72rem" }}>{label}</span>
                    <strong style={{ color: "#14263e", fontSize: "0.86rem" }}>{value}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Astra Action Center</h2>
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                {actionItems.map((item) => (
                  <div key={item} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: "0.88rem" }}>
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={insightGridStyle}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Portfolio Overview</h2>
              <div style={stripGridStyle}>
                {[
                  ["Total value", portfolioValue],
                  ["Avg position P/L", formatSignedPct(avgPositionPnl)],
                  ["Active positions", brokerTruthKnown ? `${brokerActiveCount} broker-confirmed` : `${positions.length} workflow`],
                  ["Cash", cashValue],
                  ["Biggest winner", biggestWinner?.symbol ? `${biggestWinner.symbol} ${formatSignedPct(biggestWinner.pnl_percent)}` : "not available"],
                  ["Biggest loser", biggestLoser?.symbol ? `${biggestLoser.symbol} ${formatSignedPct(biggestLoser.pnl_percent)}` : "not available"],
                ].map(([label, value]) => (
                  <div key={label} style={statusPillStyle}>
                    <span style={{ color: "#667994", fontSize: "0.72rem" }}>{label}</span>
                    <strong style={{ color: "#14263e", fontSize: "0.86rem" }}>{value}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Astra Performance</h2>
              <div style={stripGridStyle}>
                {[
                  ["Profit Factor", labelize(systemStatus?.profit_factor || "warming up")],
                  ["Buy Purity", labelize(systemStatus?.buy_purity || "warming up")],
                  ["Ranking Quality", labelize(systemStatus?.ranking_quality || readiness)],
                  ["Profit Capture", labelize(systemStatus?.profit_capture || "needs attention")],
                  ["Learning Confidence", labelize(systemStatus?.learning_confidence || "warming up")],
                  ["Status", performanceHealth],
                ].map(([label, value]) => (
                  <div key={label} style={statusPillStyle}>
                    <span style={{ color: "#667994", fontSize: "0.72rem" }}>{label}</span>
                    <strong style={{ color: label === "Status" && value === "needs attention" ? "#c43d4b" : "#14263e", fontSize: "0.86rem" }}>{value}</strong>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
              <h2 style={panelTitleStyle}>What Astra Is Watching</h2>
              <button
                type="button"
                onClick={() => (typeof onNavigate === "function" ? onNavigate("watchlists") : null)}
                style={{ border: "1px solid #c9d8eb", background: "#f7fbff", color: "#1b4f9c", borderRadius: 12, padding: "8px 11px", fontWeight: 900, cursor: "pointer" }}
              >
                Open Watchlists
              </button>
            </div>
            <div style={{ ...stripGridStyle, marginTop: 12 }}>
              {watchingItems.map((item, idx) => (
                <div key={`${item}-${idx}`} style={statusPillStyle}>
                  <span style={{ color: "#667994", fontSize: "0.72rem" }}>{idx === 0 ? "Theme" : idx === 1 ? "Market" : idx === 2 ? "Risk" : "Symbols"}</span>
                  <strong style={{ color: "#14263e", fontSize: "0.86rem" }}>{item}</strong>
                </div>
              ))}
            </div>
          </section>
        </>
      )}

      <section style={panelStyle}>
        <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Runtime Status</div>
        <div style={stripGridStyle}>
          <div style={statusPillStyle}>
            <span style={{ color: "#5f738f", fontSize: "0.72rem" }}>Backend</span>
            <strong style={{ color: "#1a2d45", fontSize: "0.86rem" }}>{backendStatus}</strong>
          </div>
          <div style={statusPillStyle}>
            <span style={{ color: "#5f738f", fontSize: "0.72rem" }}>Quotes</span>
            <strong style={{ color: "#1a2d45", fontSize: "0.86rem" }}>{quotesStatus}</strong>
          </div>
          <div style={statusPillStyle}>
            <span style={{ color: "#5f738f", fontSize: "0.72rem" }}>Readiness</span>
            <strong style={{ color: "#1a2d45", fontSize: "0.86rem" }}>{readiness}</strong>
          </div>
          <div style={statusPillStyle}>
            <span style={{ color: "#5f738f", fontSize: "0.72rem" }}>Runtime Integrity</span>
            <strong style={{ color: runtimeIntegrity ? "#24995f" : "#b14450", fontSize: "0.86rem" }}>
              {runtimeIntegrity ? "ok" : "degraded"}
            </strong>
          </div>
        </div>
        {error ? <div style={{ marginTop: "8px", color: "#ffb6bd", fontSize: "0.76rem" }}>{error}</div> : null}
      </section>

      {(topSection === "dashboard" || topSection === "buys") && (
        <>
          <section style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <h2 style={panelTitleStyle}>Astra Opportunities</h2>
                <div style={{ color: "#667994", fontSize: "0.84rem", marginTop: 3 }}>
                  Top cached opportunities with technical details kept inside each card. Ranking logic is unchanged.
                </div>
              </div>
              {topSection === "dashboard" ? (
                <button
                  type="button"
                  onClick={() => (typeof onNavigate === "function" ? onNavigate("opportunities") : null)}
                  style={{ border: "1px solid #c9d8eb", background: "#f7fbff", color: "#1b4f9c", borderRadius: 12, padding: "8px 11px", fontWeight: 900, cursor: "pointer" }}
                >
                  View All Opportunities
                </button>
              ) : null}
            </div>
            <TickerGrid
              stocks={stocks}
              stockTitle={topSection === "dashboard" ? "Top 6" : "Ranked Opportunity Detail"}
              showCryptoColumn={false}
              emptyText={loading ? "Loading stock opportunities…" : "No stock signals found"}
              cardContext="top-buy"
              onAddPosition={handleAddPosition}
              positionActionState={effectivePositionActionState}
            />
          </section>
        </>
      )}

      {(topSection === "dashboard" || topSection === "positions") && (
        <section style={panelStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap", marginBottom: "8px" }}>
            <div style={panelTitleStyle}>Active Positions</div>
            <span style={{ color: "#9cb3d6", fontSize: "0.74rem" }}>
              {brokerTruthKnown ? `${brokerActiveCount} broker-confirmed` : `${positions.length} workflow`} · compact view
            </span>
          </div>
          <div
            style={{
              marginBottom: "8px",
              padding: "8px 10px",
              borderRadius: "10px",
              background: "rgba(9, 20, 38, 0.38)",
              border: "1px solid rgba(141, 171, 212, 0.24)",
              color: "#c9d8ef",
              fontSize: "0.78rem",
              lineHeight: 1.35,
            }}
          >
            {brokerTruthKnown && brokerActiveCount === 0
              ? "No broker-confirmed active positions."
              : compactionSummary}
            {staleRowsHidden > 0 ? ` ${staleRowsHidden} stale internal workflow row${staleRowsHidden === 1 ? "" : "s"} hidden from active view.` : ""}
            {canceledOrdersCompacted > 0 ? ` ${canceledOrdersCompacted} canceled paper order${canceledOrdersCompacted === 1 ? "" : "s"} hidden from mobile view; full broker history remains available in Alpaca.` : ""}
          </div>
          {displayedPositions.length === 0 ? (
            <div style={emptyStyle}>{brokerTruthKnown ? "No broker-confirmed active positions" : "No active positions found"}</div>
          ) : (
            <div style={positionsGridStyle}>
              {displayedPositions.map((row, idx) => (
                <TickerCard
                  key={`${row.position_id || row.symbol || "POS"}-${idx}`}
                  item={row}
                  context="position"
                  onRemovePosition={handleRemovePosition}
                  removeState={
                    positionRemoveState[
                      String(row?.position_id || row?.symbol || "").trim().toUpperCase()
                    ] || "idle"
                  }
                />
              ))}
            </div>
          )}
          {hiddenPositionCount > 0 ? (
            <div style={{ ...emptyStyle, paddingTop: "10px" }}>
              {hiddenPositionCount} additional position row{hiddenPositionCount === 1 ? "" : "s"} hidden from compact view. Use Alpaca for full broker history.
            </div>
          ) : null}
        </section>
      )}

      {remoteMode && remoteSection === "sell_alerts" && (
        <section style={panelStyle}>
          <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Sell Alerts</div>
          <div style={emptyStyle}>Sell alerts are available in the main learning/trading flows.</div>
        </section>
      )}

      <section style={panelStyle}>
        <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Endpoint Health</div>
        <div style={stripGridStyle}>
          {Object.entries(endpointStatus || {}).map(([k, v]) => (
            <div key={k} style={statusPillStyle}>
              <span style={{ color: "#5f738f", fontSize: "0.72rem" }}>{k}</span>
              <strong style={{ color: v?.ok ? "#24995f" : "#b14450", fontSize: "0.82rem" }}>
                {v?.ok ? "ok" : "degraded"} {v?.status ? `(${v.status})` : ""}
              </strong>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
