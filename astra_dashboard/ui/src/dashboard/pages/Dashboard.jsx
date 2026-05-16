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
  gap: "12px",
};

const panelStyle = {
  background: "rgba(13, 30, 53, 0.64)",
  border: "1px solid rgba(117, 153, 204, 0.42)",
  borderRadius: "12px",
  padding: "10px 12px",
};

const panelTitleStyle = {
  margin: 0,
  fontSize: "0.94rem",
  color: "#dbe8ff",
  fontWeight: 700,
};

const stripGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "8px",
};

const statusPillStyle = {
  borderRadius: "9px",
  border: "1px solid #d7e1ef",
  background: "#ffffff",
  padding: "0.44rem 0.55rem",
  display: "grid",
  gap: "0.2rem",
};

const positionsGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
  gap: "10px",
};

const emptyStyle = {
  color: "#9db2d3",
  fontSize: "0.83rem",
  padding: "8px 0",
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

function normalizeTopBuys(raw) {
  const stableTop6 = Array.isArray(raw?.stable_top_6) ? raw.stable_top_6 : [];
  const stockFinal = stableTop6.length > 0 ? stableTop6 : (Array.isArray(raw?.stocks?.final) ? raw.stocks.final : []);
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
      ai_card_explanation_v2:
        row.ai_card_explanation_v2
        || row.card_explanation_v2
        || row.ollama_buy_explanation
        || row.ollama_explanation
        || row.why_this_is_a_buy
        || row.rationale
        || row.summary
        || row.buy_reason
        || "",
      ai_card_explanation_source: row.ai_card_explanation_source || row.explanation_layer_source || "",
      why_this_is_a_buy: row.why_this_is_a_buy || row.rationale || row.summary || row.buy_reason || "",
      dashboard_fallback_candidate: Boolean(row.dashboard_fallback_candidate),
      stable_display_state: row.stable_display_state || "",
      stable_composite_score: row.stable_composite_score ?? null,
      stable_retained: Boolean(row.stable_retained),
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

function normalizeDashboardSnapshot(raw = {}) {
  const payload = raw && typeof raw === "object" ? raw : {};
  return {
    topBuys: payload.top_buys || {},
    systemStatus: payload.system_status || {},
    positions: normalizePositions(payload.positions || {}),
    learningSummary: payload.learning_summary || {},
    paperPerformanceSummary: payload.paper_performance_summary || {},
    freshnessStatus: payload.freshness_status || "unknown",
    staleSections: Array.isArray(payload.stale_sections) ? payload.stale_sections : [],
    unavailableSections: Array.isArray(payload.unavailable_sections) ? payload.unavailable_sections : [],
  };
}

export default function Dashboard() {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [endpointStatus, setEndpointStatus] = useState({});
  const [topBuys, setTopBuys] = useState({});
  const [systemStatus, setSystemStatus] = useState({});
  const [positions, setPositions] = useState([]);
  const [askQuestion, setAskQuestion] = useState("How is Astra performing today?");
  const [askAnswer, setAskAnswer] = useState("");
  const [askLoading, setAskLoading] = useState(false);
  const [positionActionState, setPositionActionState] = useState({});
  const [positionRemoveState, setPositionRemoveState] = useState({});

  useEffect(() => {
    const syncBase = () => setResolvedApiBase(getInitialApiBase());
    window.addEventListener(API_BASE_CHANGED_EVENT, syncBase);
    return () => window.removeEventListener(API_BASE_CHANGED_EVENT, syncBase);
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
      try {
        const fast = await fetchJson("dashboard_fast_snapshot", "/api/dashboard_fast_snapshot_v1", {}, 5000);
        const statusMap = {};
        if (fast.ok && fast.parsed) {
          const snap = normalizeDashboardSnapshot(fast.parsed);
          setTopBuys(snap.topBuys);
          setSystemStatus(snap.systemStatus);
          setPositions(snap.positions);
          statusMap.dashboard_fast_snapshot = { ok: true, status: fast.status, error: "" };
          statusMap.top_buys = { ok: true, status: fast.status, error: snap.staleSections.includes("top_buys") ? "stale_snapshot" : "" };
          statusMap.system_status = { ok: true, status: fast.status, error: snap.staleSections.includes("system_status") ? "stale_snapshot" : "" };
          statusMap.positions = { ok: true, status: fast.status, error: snap.staleSections.includes("positions") ? "stale_snapshot" : "" };
          setEndpointStatus(statusMap);
          setError("");
        } else {
          statusMap.dashboard_fast_snapshot = { ok: false, status: fast.status, error: fast.error || "snapshot_unavailable" };
        }

        const outcomes = await Promise.all([
          fetchJson("stable_top_buys", "/api/stable_top_buys_v1?buy_mode=balanced", topBuys || {}, 5000),
          fetchJson("system_status", "/api/system_status", systemStatus || {}, 5000),
          fetchJson("positions", "/api/positions", { positions }, 5000),
        ]);
        if (!mounted) return;
        const byKey = Object.fromEntries(outcomes.map((o) => [o.key, o]));
        outcomes.forEach((o) => {
          statusMap[o.key] = {
            ok: Boolean(o.ok || (o.parsed && Object.keys(o.parsed || {}).length > 0)),
            status: o.status,
            error: o.ok ? "" : "using stale snapshot if available",
          };
        });
        setEndpointStatus({ ...statusMap });
        setError("");
        if (byKey.stable_top_buys?.parsed && Object.keys(byKey.stable_top_buys.parsed || {}).length > 0) {
          setTopBuys(byKey.stable_top_buys.parsed || {});
        } else {
          const fallbackTop = await fetchJson("top_buys", "/api/top_buys?buy_mode=balanced", topBuys || {}, 5000);
          if (fallbackTop?.parsed && Object.keys(fallbackTop.parsed || {}).length > 0) setTopBuys(fallbackTop.parsed || {});
          statusMap.top_buys = {
            ok: Boolean(fallbackTop?.ok || (fallbackTop?.parsed && Object.keys(fallbackTop.parsed || {}).length > 0)),
            status: fallbackTop?.status,
            error: fallbackTop?.ok ? "stable fallback" : "using stale snapshot if available",
          };
        }
        if (byKey.system_status?.parsed && Object.keys(byKey.system_status.parsed || {}).length > 0) setSystemStatus(byKey.system_status.parsed || {});
        if (byKey.positions?.parsed && Object.keys(byKey.positions.parsed || {}).length > 0) setPositions(normalizePositions(byKey.positions.parsed || {}));
      } finally {
        if (mounted) setLoading(false);
        busy = false;
      }
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

  const refreshPositions = async () => {
    const result = await fetchJsonWithFallback("/api/positions", {
      preferredBase: resolvedApiBase || API_BASE,
      fallbackValue: {},
      timeoutMs: 5000,
    });
    if (result.ok && result.parsed) {
      setPositions(normalizePositions(result.parsed || {}));
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
      timeoutMs: 5000,
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
      timeoutMs: 5000,
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

  const handleAskAstra = async () => {
    const question = String(askQuestion || "").trim();
    if (!question) return;
    setAskLoading(true);
    const result = await fetchJsonWithFallback(`/api/ask_astra_v1?q=${encodeURIComponent(question)}`, {
      preferredBase: resolvedApiBase || API_BASE,
      fallbackValue: { answer: "Ask-Astra is not loaded yet." },
      timeoutMs: 5000,
    });
    setAskAnswer(String(result?.parsed?.answer || "Ask-Astra is not loaded yet."));
    setAskLoading(false);
  };

  return (
    <div style={shellStyle}>
      <section style={panelStyle}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", gap: "8px", flexWrap: "wrap" }}>
          <h2 style={{ ...panelTitleStyle, fontSize: "1rem" }}>Astra Dashboard Snapshot</h2>
          <span style={{ color: "#9cb3d6", fontSize: "0.74rem" }}>As of {asOf}</span>
        </div>
        <MarketSummary markets={marketSummary} />
      </section>

      <section style={panelStyle}>
        <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Astra Runtime Status</div>
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

      <section style={panelStyle}>
        <TickerGrid
          stocks={stocks}
          stockTitle="Top 6 Stock Opportunities"
          showCryptoColumn={false}
          emptyText={loading ? "Loading stock opportunities…" : "No stock signals found"}
          cardContext="top-buy"
          onAddPosition={handleAddPosition}
          positionActionState={effectivePositionActionState}
        />
      </section>

      <section style={panelStyle}>
        <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Active Positions</div>
        {positions.length === 0 ? (
          <div style={emptyStyle}>No active positions found</div>
        ) : (
          <div style={positionsGridStyle}>
            {positions.map((row, idx) => (
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
      </section>

      <section style={panelStyle}>
        <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Ask-Astra</div>
        <div style={{ display: "grid", gap: 8 }}>
          <input
            value={askQuestion}
            onChange={(e) => setAskQuestion(e.target.value)}
            placeholder="Ask how Astra is performing..."
            style={{ borderRadius: 9, border: "1px solid #7599cc", padding: "9px 10px", fontSize: "0.9rem" }}
          />
          <button
            type="button"
            onClick={handleAskAstra}
            disabled={askLoading}
            style={{ borderRadius: 9, border: "1px solid #80a9e8", background: "#dcecff", color: "#153052", padding: "8px 10px", fontWeight: 800 }}
          >
            {askLoading ? "Asking..." : "Ask"}
          </button>
          <div style={{ color: "#dbe8ff", fontSize: "0.84rem", lineHeight: 1.45 }}>
            {askAnswer || "Ask a read-only question about Astra's current performance, positions, or learning state."}
          </div>
        </div>
      </section>

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
