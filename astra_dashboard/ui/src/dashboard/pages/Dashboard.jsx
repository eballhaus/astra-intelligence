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
  background: "linear-gradient(180deg, rgba(15, 34, 58, 0.96), rgba(9, 24, 44, 0.96))",
  border: "1px solid rgba(129, 170, 229, 0.22)",
  borderRadius: "22px",
  padding: "16px",
  boxShadow: "0 22px 54px rgba(0, 0, 0, 0.25)",
  color: "#eef6ff",
};

const panelTitleStyle = {
  margin: 0,
  fontSize: "1rem",
  color: "#f4f8ff",
  fontWeight: 900,
};

const stripGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "8px",
};

const statusPillStyle = {
  borderRadius: "14px",
  border: "1px solid rgba(129, 170, 229, 0.20)",
  background: "rgba(255, 255, 255, 0.06)",
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
  color: "#9fb3cf",
  fontSize: "0.83rem",
  padding: "8px 0",
};

const insightGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
  gap: "14px",
};

const execSubcardStyle = {
  borderRadius: 14,
  border: "1px solid rgba(129, 170, 229, 0.18)",
  background: "rgba(255, 255, 255, 0.065)",
  color: "#dbeafe",
};

const execMutedText = "#9fb3cf";
const execBodyText = "#dce9fb";
const execAccent = "#6db2ff";

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
  if (!Number.isFinite(n)) return "Data Not Available";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function metricOrUnavailable(value, suffix = "") {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Warming Up";
  return `${n.toFixed(1)}${suffix}`;
}

function metricObjectValue(metric, fallback = null) {
  if (metric && typeof metric === "object" && Number.isFinite(Number(metric.value))) return Number(metric.value);
  if (Number.isFinite(Number(metric))) return Number(metric);
  return fallback;
}

function metricObjectLabel(metric, fallback = "Warming Up") {
  if (metric && typeof metric === "object" && metric.label) return labelize(metric.label);
  return fallback;
}

function formatScore(score, suffix = "") {
  const n = Number(score);
  if (!Number.isFinite(n)) return "Warming Up";
  return `${n.toFixed(1)}${suffix}`;
}

function formatPctFromRatio(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "Warming Up";
  return `${(n <= 1 ? n * 100 : n).toFixed(1)}%`;
}

function qualitativeScore(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "Warming Up";
  if (n >= 65) return "Strong";
  if (n >= 45) return "Neutral";
  return "Weak";
}

function normalizeAllocationRows(positionsMeta = {}, systemStatus = {}) {
  const source =
    positionsMeta?.allocation_summary
    || positionsMeta?.asset_allocation
    || positionsMeta?.portfolio_allocation
    || systemStatus?.allocation_summary
    || systemStatus?.asset_allocation
    || systemStatus?.portfolio_allocation;

  if (Array.isArray(source)) {
    return source
      .map((row) => {
        const label = labelize(row?.label || row?.name || row?.asset_class || row?.category || "");
        const pct = Number(row?.percent ?? row?.pct ?? row?.weight ?? row?.allocation_pct);
        if (!label || !Number.isFinite(pct)) return null;
        return [label, `${pct.toFixed(1)}%`];
      })
      .filter(Boolean);
  }

  if (source && typeof source === "object") {
    return Object.entries(source)
      .map(([label, value]) => {
        const pct = Number(value?.percent ?? value?.pct ?? value?.weight ?? value);
        if (!Number.isFinite(pct)) return null;
        return [labelize(label), `${pct.toFixed(1)}%`];
      })
      .filter(Boolean);
  }

  return [];
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

function normalizeMarketSummary(systemStatus = {}, unifiedDiagnostics = {}) {
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
    map("nasdaq", "NDX", "NASDAQ", ["nasdaq", "ndx"]),
    map("dow", "DJI", "DOW", ["dow", "dji"]),
    map("vix", "VIX", "VIX", ["vix", "volatility_index"]),
    map("bitcoin", "BTC", "Bitcoin", ["bitcoin", "btc"]),
  ];
  const hasReal = rows.some((r) => Number.isFinite(Number(r.value)) && Number(r.value) > 0);
  if (hasReal) return rows.filter((r) => Number.isFinite(Number(r.value)) && Number(r.value) > 0);

  const marketBreadth = unifiedDiagnostics?.market_breadth_index_intelligence_v1 || {};
  const proxyRows = Array.isArray(marketBreadth?.index_signal_rows) ? marketBreadth.index_signal_rows : [];
  const proxyLabels = {
    SPY: ["sp500_proxy", "S&P 500 / SPY Proxy", "SPY"],
    QQQ: ["nasdaq_proxy", "Nasdaq / QQQ Proxy", "QQQ"],
    DIA: ["dow_proxy", "Dow / DIA Proxy", "DIA"],
    IWM: ["small_cap_proxy", "Small Caps / IWM Proxy", "IWM"],
    VIX: ["vix_pressure", "VIX Pressure", "VIX"],
  };
  const mapped = proxyRows
    .filter((row) => proxyLabels[String(row?.symbol || "").toUpperCase()])
    .slice(0, 5)
    .map((row) => {
      const symbol = String(row.symbol || "").toUpperCase();
      const [id, name, displaySymbol] = proxyLabels[symbol];
      const signal = Number(row.signal);
      return {
        id,
        symbol: displaySymbol,
        name,
        value: signal,
        valueKind: "score",
        displayValue: Number.isFinite(signal) ? `${signal.toFixed(1)}` : "Score unavailable",
        detail: labelize(row.role || "context proxy"),
        sourceLabel: "Astra Score",
        type: "context",
      };
    });
  return mapped;
}

export default function Dashboard({ remoteSection = "dashboard", remoteMode = false, onNavigate }) {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [endpointStatus, setEndpointStatus] = useState({});
  const [topBuys, setTopBuys] = useState({});
  const [systemStatus, setSystemStatus] = useState({});
  const [unifiedDiagnostics, setUnifiedDiagnostics] = useState({});
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

  useEffect(() => {
    let mounted = true;
    let busy = false;

    const refreshUnifiedDiagnostics = async () => {
      if (busy) return;
      busy = true;
      const result = await fetchJsonWithFallback("/api/unified_learning_diagnostics_v1", {
        preferredBase: resolvedApiBase || API_BASE,
        fallbackValue: {},
        timeoutMs: 45000,
      });
      if (mounted && result.ok && result.parsed) {
        setUnifiedDiagnostics(result.parsed || {});
        setEndpointStatus((prev) => ({
          ...(prev || {}),
          unified_diagnostics: { ok: result.ok, status: result.httpStatus, error: result.error || "" },
        }));
      }
      busy = false;
    };

    refreshUnifiedDiagnostics();
    const timer = setInterval(refreshUnifiedDiagnostics, 120000);
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
  const marketSummary = useMemo(() => normalizeMarketSummary(systemStatus, unifiedDiagnostics), [systemStatus, unifiedDiagnostics]);
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
    ? (remoteSection === "positions" ? "positions" : remoteSection === "copilot" ? "copilot" : "buys")
    : "dashboard";
  const performanceSummary = unifiedDiagnostics?.performance_summary || {};
  const executiveSnapshot = unifiedDiagnostics?.executive_snapshot || {};
  const executionQuality = unifiedDiagnostics?.execution_quality_summary || executiveSnapshot?.execution_quality || {};
  const portfolioHealth = unifiedDiagnostics?.portfolio_health_summary || executiveSnapshot?.portfolio_health || {};
  const learningMaturity = unifiedDiagnostics?.learning_maturity_summary || executiveSnapshot?.learning_status || {};
  const systemHealth = unifiedDiagnostics?.system_health_summary || executiveSnapshot?.system_health || {};
  const marketBreadth = unifiedDiagnostics?.market_breadth_index_intelligence_v1 || {};
  const sectorRotation = unifiedDiagnostics?.etf_sector_rotation_intelligence_v1 || {};
  const marketTransition = unifiedDiagnostics?.market_transition_detection_v1 || {};
  const iqSuite = unifiedDiagnostics?.intelligence_quality_learning_efficiency_suite_v1 || {};
  const profitCapture = unifiedDiagnostics?.profit_capture_peak_decay_exit_validation_suite_v1 || {};
  const rankingAttribution = unifiedDiagnostics?.candidate_ranking_attribution_promotion_intelligence_v1 || {};
  const marketIntelligence = executiveSnapshot?.market_intelligence || {};
  const portfolioHeatScore = metricObjectValue(portfolioHealth?.portfolio_heat);
  const concentrationRiskScore = metricObjectValue(portfolioHealth?.concentration_risk);
  const correlationRiskScore = metricObjectValue(portfolioHealth?.correlation_risk);
  const portfolioRiskMetric = [portfolioHeatScore, concentrationRiskScore, correlationRiskScore]
    .filter((n) => Number.isFinite(Number(n)));
  const portfolioRiskScore = portfolioRiskMetric.length
    ? portfolioRiskMetric.reduce((sum, n) => sum + Number(n), 0) / portfolioRiskMetric.length
    : null;
  const portfolioRiskLabel = portfolioRiskScore == null
    ? "Warming Up"
    : portfolioRiskScore >= 70
    ? "Elevated"
    : portfolioRiskScore >= 45
    ? "Moderate"
    : "Controlled";
  const mainWeakness = labelize(
    iqSuite?.weakest_confidence_component
      || iqSuite?.summary?.weakest_confidence_component
      || profitCapture?.readiness_blocker
      || "Warming Up",
  );
  const nextFocus = labelize(
    iqSuite?.recommended_next_focus
      || iqSuite?.summary?.recommended_next_focus
      || profitCapture?.closest_exit_policy_to_readiness
      || "Review top ranked candidates",
  );
  const learningConfidenceScore = metricObjectValue(learningMaturity?.adaptive_confidence)
    ?? Number(iqSuite?.conviction_calibration_score);
  const learningConfidenceLabel = Number.isFinite(Number(learningConfidenceScore))
    ? `${Number(learningConfidenceScore).toFixed(0)}%`
    : "Warming Up";
  const evidenceCount = Number(unifiedDiagnostics?.evidence_maturity_status?.evidence_count ?? performanceSummary?.closed_trade_count ?? unifiedDiagnostics?.evidence_count);
  const marketSupportScore = Number(marketBreadth?.market_support_for_equity_trades ?? marketBreadth?.overall_market_health);
  const marketBiasSource = marketTransition?.current_market_phase
    || marketIntelligence?.current_regime
    || marketBreadth?.current_index_regime;
  const highConfidenceCount = stocks.filter((row) => safeNumber(row?.confidence) >= 70).length;
  const bestOpportunity = stocks[0] || {};
  const stockThemes = stocks
    .map((row) => row?.theme || row?.catalyst || row?.sector)
    .filter(Boolean)
    .map((theme) => labelize(theme));
  const strongestTheme = labelize(
    bestOpportunity?.theme
      || bestOpportunity?.catalyst
      || bestOpportunity?.sector
      || sectorRotation?.strongest_sector
      || marketIntelligence?.best_archetype
      || systemStatus?.leadership_theme
      || "theme data unavailable",
  );
  const marketTone = Number.isFinite(marketSupportScore)
    ? (marketSupportScore >= 60 ? "Bullish" : marketSupportScore >= 42 ? "Neutral" : "Bearish")
    : runtimeIntegrity && highConfidenceCount >= 2
    ? "Bullish"
    : runtimeIntegrity
    ? "Neutral"
    : "Bearish";
  const volatilityKnown = systemStatus?.vix !== undefined || systemStatus?.volatility_status;
  const volatilityStatus = safeNumber(systemStatus?.vix, 0) > 25
    ? "elevated"
    : labelize(systemStatus?.volatility_status || (Number.isFinite(Number(marketBreadth?.volatility_pressure_score)) ? `${qualitativeScore(100 - Number(marketBreadth.volatility_pressure_score))} volatility pressure` : (volatilityKnown ? "controlled" : "Warming Up")));
  const breadthStatus = labelize(systemStatus?.breadth_status || (Number.isFinite(Number(marketBreadth?.breadth_proxy_score)) ? `${formatScore(marketBreadth.breadth_proxy_score)} breadth proxy` : (validQuotes > 0 ? "active coverage" : "warming up")));
  const riskMode = Number.isFinite(Number(marketBreadth?.risk_on_score)) && Number.isFinite(Number(marketBreadth?.risk_off_score))
    ? (Number(marketBreadth.risk_on_score) >= Number(marketBreadth.risk_off_score) ? "Risk-On" : "Risk-Off")
    : marketTone === "Bearish" ? "Risk-Off" : "Risk-On";
  const marketConfidenceRaw = systemStatus?.market_confidence
    ?? systemStatus?.market_confidence_pct
    ?? systemStatus?.environment_confidence
    ?? systemStatus?.market_environment_confidence
    ?? marketBreadth?.index_confidence_score
    ?? marketTransition?.transition_confidence;
  const marketConfidence = Number.isFinite(Number(marketConfidenceRaw)) ? Number(marketConfidenceRaw) : null;
  const portfolioRiskText = portfolioRiskScore == null
    ? "portfolio risk diagnostics are warming up"
    : `${portfolioRiskLabel} risk: heat ${formatScore(portfolioHeatScore)}, concentration ${formatScore(concentrationRiskScore)}, correlation ${formatScore(correlationRiskScore)}`;
  const astraBrief = [
    `Astra's cached market context is ${marketTone.toLowerCase()}${marketBiasSource ? ` (${labelize(marketBiasSource)})` : ""}.`,
    `Breadth reads ${breadthStatus}, with ${strongestTheme} as the strongest current leadership clue.`,
    `Astra has ${highConfidenceCount} high-confidence opportunit${highConfidenceCount === 1 ? "y" : "ies"} and ${portfolioRiskText}.`,
    `Next focus: ${nextFocus}.`,
  ].join(" ");
  const portfolioValue = formatMoney(positionsMeta?.portfolio_value ?? positionsMeta?.total_value ?? systemStatus?.portfolio_value);
  const cashValue = formatMoney(positionsMeta?.cash ?? positionsMeta?.buying_power ?? systemStatus?.cash);
  const buyingPowerValue = formatMoney(positionsMeta?.buying_power ?? positionsMeta?.cash ?? systemStatus?.buying_power ?? systemStatus?.cash);
  const allocationRows = normalizeAllocationRows(positionsMeta, systemStatus).slice(0, 4);
  const riskLines = [
    [
      "Portfolio risk",
      portfolioRiskScore == null ? "Warming Up" : `${portfolioRiskLabel} (${formatScore(portfolioRiskScore)})`,
    ],
    ["Concentration", Number.isFinite(Number(concentrationRiskScore)) ? `${formatScore(concentrationRiskScore)} ${metricObjectLabel(portfolioHealth?.concentration_risk, "")}` : "Warming Up"],
    ["Correlation", Number.isFinite(Number(correlationRiskScore)) ? `${formatScore(correlationRiskScore)} ${metricObjectLabel(portfolioHealth?.correlation_risk, "")}` : "Warming Up"],
    ["Portfolio heat", Number.isFinite(Number(portfolioHeatScore)) ? `${formatScore(portfolioHeatScore)} ${metricObjectLabel(portfolioHealth?.portfolio_heat, "")}` : "Warming Up"],
    ["Allocation", allocationRows.length ? allocationRows.map(([label, pct]) => `${label} ${pct}`).join(" / ") : "Warming Up"],
  ];
  const sortedByPnl = [...positions].sort((a, b) => safeNumber(b?.pnl_percent) - safeNumber(a?.pnl_percent));
  const biggestWinner = sortedByPnl[0];
  const biggestLoser = sortedByPnl[sortedByPnl.length - 1];
  const largestPosition = [...positions].sort((a, b) => safeNumber(b?.market_value ?? b?.position_value) - safeNumber(a?.market_value ?? a?.position_value))[0];
  const avgPositionPnl = positions.length
    ? positions.reduce((sum, row) => sum + safeNumber(row?.pnl_percent), 0) / positions.length
    : 0;
  const performanceHealth = runtimeIntegrity && highConfidenceCount > 0 ? "healthy" : runtimeIntegrity ? "warming up" : "needs attention";
  const marketSession = labelize(
    systemStatus?.market_session
      || systemStatus?.market_phase
      || systemStatus?.session_status
      || "market context",
  );
  const watchingItems = [
    bestOpportunity?.symbol ? `${bestOpportunity.symbol} leadership / follow-through` : "Opportunity watchlist warming up",
    strongestTheme === "theme data unavailable" ? "Theme context data unavailable" : `${strongestTheme} theme persistence`,
    `Breadth ${breadthStatus}`,
    `Volatility ${volatilityStatus}`,
    `Symbols: ${stocks.slice(0, 4).map((row) => row.symbol).filter(Boolean).join(", ") || "Warming Up"}`,
  ];
  const opportunityRows = stocks.slice(0, 5).map((row, idx) => ({
    rank: idx + 1,
    symbol: row.symbol || row.ticker || "N/A",
    company: row.company_name || row.name || row.company || "",
    confidence: safeNumber(row.confidence ?? row.buy_confidence ?? row.predicted_win_probability, 0),
    horizon: labelize(row.best_horizon_style || row.best_profit_horizon || row.horizon || row.trade_horizon_style || "intraday"),
    why: String(row.why_this_is_a_buy || row.why_made_list || row.buy_reason || row.rationale || row.ranked_universe_action_explanation || "Astra sees favorable quality, confidence, and setup context.").slice(0, 88),
    trendBias: Number.isFinite(Number(row.change_percent ?? row.expected_move_pct ?? row.predicted_return_pct))
      ? Number(row.change_percent ?? row.expected_move_pct ?? row.predicted_return_pct)
      : null,
    risk: labelize(row.portfolio_risk_label || row.risk_label || "Risk Warming Up"),
    consistency: safeNumber(row.rolling_conviction_10r ?? row.conviction_display_score ?? row.buy_quality_score, 0),
  }));
  const copilotStatus = unifiedDiagnostics?.astra_copilot_suite_v1 || {};
  const askLocalAiStatus = unifiedDiagnostics?.ask_astra_local_ai_status_v1 || {};
  const astraExecutive = unifiedDiagnostics?.astra_executive_polish_v1 || {};
  const astraCeo = unifiedDiagnostics?.astra_ceo_polish_v1 || {};
  const copilotRows = opportunityRows.map((row) => {
    const action = row.confidence >= 82 ? "BUY_NOW" : row.confidence >= 68 ? "WATCH_CLOSELY" : "HOLD";
    const signalLabel = action === "BUY_NOW" ? "🟢 Buy Now" : action === "WATCH_CLOSELY" ? "🟡 Watch Closely" : "🔵 Hold";
    return {
      ...row,
      action,
      actionLabel: action === "BUY_NOW" ? "Buy Now" : action === "WATCH_CLOSELY" ? "Watch Closely" : "Hold",
      signal: signalLabel,
    };
  });
  const leadingThemes = Array.isArray(systemStatus?.current_themes)
    ? systemStatus.current_themes.slice(0, 3).map((theme) => labelize(theme))
    : Array.from(new Set([
      strongestTheme,
      sectorRotation?.strongest_sector,
      marketIntelligence?.best_archetype,
      ...stockThemes,
    ].filter(Boolean).map((theme) => labelize(theme)))).slice(0, 3);
  const topSectors = Array.isArray(systemStatus?.top_sectors)
    ? systemStatus.top_sectors.slice(0, 5).map((row) => [
      labelize(row?.sector || row?.name || "Sector"),
      Number.isFinite(Number(row?.change_pct ?? row?.change_percent))
        ? formatSignedPct(row?.change_pct ?? row?.change_percent)
        : "Warming Up",
      safeNumber(row?.change_pct ?? row?.change_percent, 0) >= 0,
    ])
    : Array.isArray(sectorRotation?.sector_rows)
    ? sectorRotation.sector_rows.slice(0, 6).map((row) => [
      labelize(row?.sector || "Sector"),
      `${formatScore(row?.leadership_score)}`,
      Number(row?.leadership_score) >= 45,
      qualitativeScore(row?.leadership_score),
    ])
    : [];
  const calendarItems = Array.isArray(systemStatus?.calendar_items)
    ? systemStatus.calendar_items.slice(0, 4).map((row) => [
      String(row?.time || row?.timestamp || "TBD"),
      String(row?.event || row?.title || "Calendar item"),
    ])
    : [];
  const modelConfidenceRaw = systemStatus?.model_confidence
    ?? systemStatus?.learning_confidence
    ?? systemStatus?.confidence_score
    ?? systemStatus?.adaptive_confidence
    ?? learningMaturity?.adaptive_confidence?.value
    ?? iqSuite?.conviction_calibration_score;
  const modelConfidence = Number.isFinite(Number(modelConfidenceRaw)) ? Number(modelConfidenceRaw) : null;
  const modelConfidenceLabel = modelConfidence == null ? "Warming Up" : `${modelConfidence.toFixed(0)}%`;
  const paperReadyCount = stocks.filter((row) => String(row?.grade || row?.buy_eligibility || "").toLowerCase().includes("paper")).length;
  const opportunitySummary = [
    ["High confidence", `${highConfidenceCount}`],
    ["Paper-ready", `${paperReadyCount}`],
    ["Strongest theme", strongestTheme],
    ["Market bias", marketTone],
  ];
  const actionCenterItems = [
    copilotRows.some((r) => r.action === "BUY_NOW") ? "Buy after confirmation: review top Copilot buy-now names" : "Buy after confirmation: wait for stronger confirmation",
    "Hold validated leaders: keep broker truth and paper state separated",
    "Watch catalyst changes: monitor theme persistence before chasing",
    "Prepare exits: review profit capture without enabling automatic sells",
  ];
  const radarItems = [
    `Earnings Watch: ${calendarItems[0]?.[1] || "calendar feed warming up"}`,
    `Catalyst Watch: ${strongestTheme}`,
    `Horizon Watch: ${copilotRows[0]?.horizon || "warming up"}`,
    `Market Regime Watch: ${marketTone}${marketBiasSource ? ` / ${labelize(marketBiasSource)}` : ""}`,
  ];
  const decisionSummary = [
    astraCeo?.strategic_posture ? `Posture: ${astraCeo.strategic_posture}` : `Market tone ${marketTone}${marketBiasSource ? ` / ${labelize(marketBiasSource)}` : ""}`,
    astraExecutive?.top_opportunity_summary || `Best opportunity ${bestOpportunity?.symbol || "Warming Up"}`,
    astraExecutive?.needs_attention_summary || `Main weakness ${mainWeakness}`,
    astraCeo?.what_astra_should_learn_next ? `Next learning: ${astraCeo.what_astra_should_learn_next}` : `Next review ${highConfidenceCount > 0 ? "top ranked candidates" : "wait for fresh opportunity evidence"}`,
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
      <section style={{ ...panelStyle, padding: "12px 14px" }}>
        <MarketSummary markets={marketSummary} asOf={asOf} marketSession={marketSession} />
      </section>

      {topSection === "dashboard" && (
        <>
          <section style={{ display: "grid", gridTemplateColumns: "0.95fr 1.55fr 1.05fr", gap: 14, alignItems: "stretch" }}>
            <div style={{ ...panelStyle, minHeight: 246, display: "grid", alignContent: "start", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                <h2 style={panelTitleStyle}>Market Context</h2>
                <span style={{ color: execAccent, fontWeight: 900 }}>Live</span>
              </div>
              <div>
                <div style={{ color: marketTone === "Bearish" ? "#c43d4b" : marketTone === "Neutral" ? "#d88a19" : "#079246", fontSize: 28, fontWeight: 950, letterSpacing: "-0.04em" }}>{marketTone}</div>
                <div style={{ color: "#eaf3ff", fontWeight: 900, marginTop: 2 }}>
                  {marketConfidence == null ? "Warming Up" : `${marketConfidence.toFixed(0)}%`} <span style={{ color: execMutedText, fontWeight: 700 }}>Confidence</span>
                </div>
              </div>
              <div style={{ height: 1, background: "rgba(129, 170, 229, 0.20)" }} />
              {[
                ["Risk Environment", riskMode],
                ["Volatility", volatilityStatus],
                ["Market Breadth", breadthStatus],
                ["Leadership", strongestTheme],
              ].map(([label, value]) => (
                <div key={label} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, alignItems: "center" }}>
                  <span style={{ color: execMutedText, fontWeight: 800, fontSize: 12.5 }}>{label}</span>
                  <strong style={{ color: String(value).toLowerCase().includes("risk-off") ? "#c43d4b" : "#078943", fontSize: 12.5, textAlign: "right" }}>{value}</strong>
                </div>
              ))}
              <button type="button" onClick={() => (typeof onNavigate === "function" ? onNavigate("reports") : null)} style={{ marginTop: "auto", border: "1px solid rgba(109, 178, 255, 0.32)", background: "rgba(36, 107, 254, 0.14)", color: "#b9d5ff", borderRadius: 12, padding: "9px 11px", fontWeight: 900, cursor: "pointer" }}>
                View Market Details →
              </button>
            </div>

            <div style={{ ...panelStyle, minHeight: 246, display: "grid", alignContent: "start", gap: 12 }}>
              <h2 style={panelTitleStyle}>Astra's Plain-English Take</h2>
              <p style={{ margin: 0, color: execBodyText, fontSize: 13, lineHeight: 1.62 }}>{astraCeo?.plain_english_take || astraBrief}</p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: "auto" }}>
                {[
                  ["Market Outlook", astraExecutive?.market_outlook_summary || marketTone, ""],
                  ["Needs Attention", astraExecutive?.needs_attention_summary || mainWeakness, ""],
                  ["Portfolio Health", portfolioRiskLabel, portfolioRiskScore == null ? "warming up" : `${formatScore(portfolioRiskScore)} score`],
                  ["Astra Confidence", modelConfidence == null ? "Warming Up" : modelConfidence >= 80 ? "High" : modelConfidence >= 55 ? "Moderate" : "Developing", modelConfidenceLabel],
                ].map(([label, value, sub]) => (
                  <div key={label} style={{ ...execSubcardStyle, padding: "9px 10px", display: "grid", gap: 3 }}>
                    <div style={{ color: execMutedText, fontSize: 10, fontWeight: 900 }}>{label}</div>
                    <div style={{ color: "#f5f9ff", fontSize: 13, fontWeight: 950, lineHeight: 1.25 }}>{value}</div>
                    {sub ? <div style={{ color: execMutedText, fontSize: 9 }}>{sub}</div> : null}
                  </div>
                ))}
              </div>
              <button type="button" onClick={() => (typeof onNavigate === "function" ? onNavigate("learning") : null)} style={{ border: "1px solid rgba(109, 178, 255, 0.32)", background: "rgba(36, 107, 254, 0.14)", color: "#b9d5ff", borderRadius: 12, padding: "9px 11px", fontWeight: 900, cursor: "pointer" }}>
                Read Full Analysis →
              </button>
            </div>

            <div onClick={() => (typeof onNavigate === "function" ? onNavigate("ask", { question: "What are the best short-term opportunities today?" }) : null)} style={{ borderRadius: 22, padding: 16, background: "radial-gradient(260px 150px at 80% 0%, rgba(45, 119, 255, 0.36), transparent 70%), linear-gradient(135deg, #071a33, #08244b)", boxShadow: "0 22px 54px rgba(0, 0, 0, 0.26)", color: "#ffffff", minHeight: 246, display: "grid", gap: 12, cursor: "pointer", border: "1px solid rgba(129, 170, 229, 0.24)" }}>
              <h2 style={{ margin: 0, fontSize: "1rem", color: "#ffffff" }}>Ask Astra</h2>
              <p style={{ margin: 0, color: "#c8d8ef", fontSize: 13 }}>Local AI executive assistant. Fast mode uses Qwen only after you submit.</p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8 }}>
                {[
                  ["Local AI", askLocalAiStatus?.local_ai_status || "warming up"],
                  ["Primary", "Qwen3:8B"],
                  ["Fallback", "Qwen3:14B"],
                  ["Mode", askLocalAiStatus?.response_mode || "fast fallback"],
                ].map(([label, value]) => (
                  <div key={label} style={{ borderRadius: 10, border: "1px solid rgba(180, 209, 255, 0.18)", background: "rgba(255,255,255,0.07)", padding: "7px 8px" }}>
                    <div style={{ color: "#8fb1df", fontSize: 9, fontWeight: 900, textTransform: "uppercase" }}>{label}</div>
                    <div style={{ color: "#ffffff", fontSize: 11, fontWeight: 900 }}>{value}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, border: "1px solid rgba(180, 209, 255, 0.22)", borderRadius: 14, background: "rgba(255,255,255,0.08)", padding: 10, color: "#f5f9ff", marginTop: 2, alignItems: "center" }}>
                <span style={{ color: "#d9e7fa", fontSize: 13 }}>What are the best short-term opportunities today?</span>
                <button type="button" onClick={(event) => { event.stopPropagation(); if (typeof onNavigate === "function") onNavigate("ask", { question: "What are the best short-term opportunities today?" }); }} style={{ border: 0, borderRadius: 12, background: "#2b76ff", color: "#fff", width: 34, height: 34, fontWeight: 900, cursor: "pointer" }}>→</button>
              </div>
              <div style={{ color: "#8fb1df", fontSize: 11, fontWeight: 900, textTransform: "uppercase" }}>Suggested Questions</div>
              {["Explain Astra status simply.", "Why did Astra choose this?", "What changed today?", "What is Astra learning?"].map((q) => (
                <button key={q} type="button" onClick={(event) => { event.stopPropagation(); if (typeof onNavigate === "function") onNavigate("ask", { question: q }); }} style={{ textAlign: "left", border: 0, borderRadius: 10, background: "rgba(255,255,255,0.08)", color: "#eaf3ff", padding: "8px 10px", cursor: "pointer" }}>{q}</button>
              ))}
            </div>
          </section>

          <section style={{ ...panelStyle, overflow: "hidden", display: "grid", alignContent: "start" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div>
                <h2 style={panelTitleStyle}>Astra Copilot</h2>
                <div style={{ color: execMutedText, fontSize: 12, marginTop: 2 }}>Top 5 actions Astra recommends right now.</div>
              </div>
              <button type="button" onClick={() => (typeof onNavigate === "function" ? onNavigate("copilot") : null)} style={{ border: 0, background: "transparent", color: "#8dbbff", fontWeight: 900, cursor: "pointer" }}>
                View Copilot Guidance
              </button>
            </div>
            <div style={{ display: "grid", gap: 0 }}>
              <div style={{ display: "grid", gridTemplateColumns: "132px minmax(90px, .75fr) minmax(94px, .75fr) minmax(120px, .9fr) minmax(0, 3fr)", gap: 10, padding: "8px 0", color: execMutedText, fontSize: 10, fontWeight: 950, textTransform: "uppercase", borderBottom: "1px solid rgba(129, 170, 229, 0.18)" }}>
                <span>Signal</span><span>Asset</span><span>Confidence</span><span>Horizon</span><span>Why Astra Chose It</span>
              </div>
              {copilotRows.length === 0 ? (
                <div style={{ border: "1px dashed rgba(129, 170, 229, 0.24)", borderRadius: 14, color: "#9fb3cf", background: "rgba(255,255,255,0.06)", padding: 16, marginTop: 12, fontSize: 13, lineHeight: 1.45 }}>
                  Copilot guidance is warming up from cached rankings. No provider, broker, or model calls are made by this card.
                </div>
              ) : copilotRows.map((row) => (
                <div key={`${row.rank}-${row.symbol}`} onClick={() => (typeof onNavigate === "function" ? onNavigate("copilot") : null)} style={{ display: "grid", gridTemplateColumns: "132px minmax(90px, .75fr) minmax(94px, .75fr) minmax(120px, .9fr) minmax(0, 3fr)", gap: 10, padding: "10px 0", alignItems: "center", borderBottom: "1px solid rgba(129, 170, 229, 0.12)", cursor: "pointer" }}>
                  <strong style={{ color: row.action === "BUY_NOW" ? "#5ee6a8" : row.action === "WATCH_CLOSELY" ? "#f6c453" : "#8dbbff", fontSize: 12 }}>{row.signal}</strong>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ color: "#f5f9ff", fontWeight: 950, fontSize: 13 }}>{row.symbol}</div>
                    <div style={{ color: execMutedText, fontSize: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.company || row.risk}</div>
                  </div>
                  <strong style={{ color: "#5ee6a8", fontSize: 15 }}>{row.confidence.toFixed(0)}%</strong>
                  <div style={{ display: "grid", gap: 2 }}>
                    <strong style={{ color: "#b9d5ff", fontSize: 11.5 }}>{row.horizon}</strong>
                    <span style={{ color: execMutedText, fontSize: 9.5 }}>Consistency {row.consistency ? row.consistency.toFixed(0) : "Warming Up"}</span>
                  </div>
                  <span style={{ color: execBodyText, fontSize: 11.5, lineHeight: 1.35, minWidth: 0 }}>{row.why}</span>
                </div>
              ))}
            </div>
          </section>

          <section style={{ display: "grid", gridTemplateColumns: "1.05fr 1.45fr 0.9fr", gap: 14 }}>
            <div style={panelStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                <h2 style={panelTitleStyle}>Portfolio Overview & Positioning</h2>
                <button type="button" onClick={() => (typeof onNavigate === "function" ? onNavigate("portfolio") : null)} style={{ border: 0, background: "transparent", color: "#8dbbff", fontWeight: 900, cursor: "pointer" }}>View Portfolio</button>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginTop: 14 }}>
                {[["Total Value", portfolioValue], ["Day's P/L", formatSignedPct(avgPositionPnl)], ["Cash", cashValue]].map(([label, value]) => (
                  <div key={label}>
                    <div style={{ color: "#9fb3cf", fontSize: 11, fontWeight: 900, textTransform: "uppercase" }}>{label}</div>
                    <div style={{ color: label === "Day's P/L" && avgPositionPnl < 0 ? "#c43d4b" : "#f5f9ff", fontSize: 19, fontWeight: 950 }}>{value}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "122px 1fr", gap: 16, alignItems: "center", marginTop: 16 }}>
                <div style={{ width: 114, height: 114, borderRadius: "50%", background: "#eef4fa", border: "10px solid #dce8f5", display: "grid", placeItems: "center", margin: "0 auto" }}>
                  <div style={{ width: 70, height: 70, borderRadius: "50%", background: "#ffffff", display: "grid", placeItems: "center", color: "#f5f9ff", fontWeight: 950 }}>{brokerActiveCount}<br /><span style={{ fontSize: 10, color: "#9fb3cf" }}>Open</span></div>
                </div>
                <div style={{ display: "grid", gap: 8, fontSize: 12 }}>
                  <div style={{ color: "#dce9fb", fontWeight: 800 }}>
                    Risk {portfolioRiskScore == null ? "Warming Up" : `${portfolioRiskLabel} (${formatScore(portfolioRiskScore)})`}
                  </div>
                  {allocationRows.length === 0 ? (
                    <div style={{ color: "#9fb3cf", fontWeight: 800 }}>Allocation Warming Up</div>
                  ) : allocationRows.map(([label, pct]) => (
                    <div key={`${label}-${pct}`} style={{ color: "#dce9fb", fontWeight: 800 }}>{label} {pct}</div>
                  ))}
                </div>
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Astra Performance</h2>
              <p style={{ margin: "8px 0 12px", color: "#dce9fb", fontSize: 13 }}>Verified learning metrics from unified diagnostics.</p>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10 }}>
                {[
                  ["Win Rate", metricOrUnavailable(performanceSummary?.released_win_rate?.value ?? systemStatus?.win_rate ?? systemStatus?.released_win_rate, "%")],
                  ["Profit Factor", metricOrUnavailable(performanceSummary?.profit_factor?.value ?? systemStatus?.profit_factor)],
                  ["Avg Return", metricOrUnavailable(performanceSummary?.average_return?.value, "%")],
                  ["Buy Purity", metricOrUnavailable(performanceSummary?.buy_list_purity?.value ?? systemStatus?.buy_purity, "%")],
                ].map(([label, value]) => (
                  <div key={label} style={{ border: "1px solid rgba(129, 170, 229, 0.20)", borderRadius: 14, padding: "10px 11px", background: "rgba(255,255,255,0.06)" }}>
                    <div style={{ color: "#079246", fontSize: 20, fontWeight: 950 }}>{value}</div>
                    <div style={{ color: "#9fb3cf", fontSize: 11, fontWeight: 900 }}>{label}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Sector Heat Map</h2>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                {leadingThemes.length === 0 ? (
                  <span style={{ background: "rgba(255,255,255,0.06)", color: "#9fb3cf", border: "1px dashed rgba(129, 170, 229, 0.24)", borderRadius: 8, padding: "7px 12px", fontSize: 12, fontWeight: 900 }}>Theme Data Warming Up</span>
                ) : leadingThemes.map((theme) => (
                  <span key={theme} style={{ background: "#e8f7ec", color: "#087a41", borderRadius: 8, padding: "7px 12px", fontSize: 12, fontWeight: 900 }}>{theme}</span>
                ))}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: topSectors.length ? "repeat(3, 1fr)" : "1fr", gap: 8, marginTop: 14 }}>
                {topSectors.length === 0 ? (
                  <div style={{ border: "1px dashed rgba(129, 170, 229, 0.24)", borderRadius: 12, background: "rgba(255,255,255,0.06)", color: "#9fb3cf", padding: "12px 13px", fontSize: 13 }}>
                    Sector intelligence is warming up from cached diagnostics.
                  </div>
                ) : topSectors.slice(0, 6).map(([sector, change, positive, qualitative]) => (
                  <div key={sector} style={{ background: positive ? "#e9f8ee" : "#fdebed", color: positive ? "#087a41" : "#b7283a", borderRadius: 10, padding: 10 }}>
                    <div style={{ color: "#dce9fb", fontSize: 11, fontWeight: 900 }}>{sector}</div>
                    <div style={{ fontWeight: 950 }}>{change}</div>
                    {qualitative ? <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 800, marginTop: 2 }}>{qualitative}</div> : null}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={{ display: "grid", gridTemplateColumns: "1.18fr 1.1fr 0.92fr", gap: 14 }}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Latest Learning Insights</h2>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 12 }}>
                {[
                  ["Learning", learningConfidenceLabel],
                  ["Ranking", formatScore(rankingAttribution?.ranking_quality_score)],
                  ["Exit Quality", formatScore(executionQuality?.exit_quality?.value)],
                  ["Capture", formatPctFromRatio(profitCapture?.average_capture_ratio)],
                ].map(([label, value]) => (
                  <div key={label} style={{ border: "1px solid rgba(129, 170, 229, 0.20)", borderRadius: 12, background: "rgba(255,255,255,0.06)", padding: "10px 11px" }}>
                    <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 900 }}>{label}</div>
                    <div style={{ color: "#f5f9ff", fontWeight: 950, marginTop: 4 }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Astra Action Center</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {actionCenterItems.map((item) => (
                  <div key={item} style={{ border: "1px solid rgba(129, 170, 229, 0.20)", borderRadius: 12, background: "rgba(255,255,255,0.06)", padding: "10px 11px", color: "#dce9fb", fontSize: 12.5, lineHeight: 1.4 }}>
                    {item}
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Market Calendar</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {calendarItems.length === 0 ? (
                  <div style={{ border: "1px dashed rgba(129, 170, 229, 0.24)", borderRadius: 12, background: "rgba(255,255,255,0.06)", color: "#9fb3cf", padding: "12px 13px", fontSize: 13 }}>
                    Source-backed event calendar is not connected in the cached dashboard payload.
                  </div>
                ) : calendarItems.map(([time, event]) => (
                  <div key={`${time}-${event}`} style={{ display: "grid", gridTemplateColumns: "74px 1fr", gap: 10, color: "#dce9fb", fontSize: 13 }}>
                    <strong style={{ color: "#8dbbff" }}>{time}</strong>
                    <span>{event}</span>
                  </div>
                ))}
              </div>
              <button type="button" disabled={calendarItems.length === 0} style={{ marginTop: 14, width: "100%", border: "1px solid rgba(129, 170, 229, 0.24)", background: calendarItems.length ? "rgba(255,255,255,0.06)" : "rgba(255,255,255,0.04)", color: calendarItems.length ? "#8dbbff" : "#7f91a8", borderRadius: 12, padding: "10px 12px", fontWeight: 900, cursor: calendarItems.length ? "pointer" : "not-allowed" }}>
                {calendarItems.length ? "See Full Economic Calendar →" : "Calendar Feed Unavailable"}
              </button>
            </div>
          </section>

          <section style={{ display: "grid", gridTemplateColumns: "1.25fr 1fr", gap: 14 }}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Astra Radar</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {radarItems.map((item) => (
                  <div key={item} style={{ ...execSubcardStyle, padding: "10px 11px", color: execBodyText, fontSize: 12.5, lineHeight: 1.4 }}>
                    {item}
                  </div>
                ))}
              </div>
            </div>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Today's Decision Summary</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
                {decisionSummary.map((item) => (
                  <div key={item} style={{ borderRadius: 12, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "10px 11px", color: "#dce9fb", fontSize: 12.5, fontWeight: 800 }}>
                    {item}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={{ ...panelStyle, display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 0, padding: 0, overflow: "hidden" }}>
            {[
              ["Learning Status", Number.isFinite(evidenceCount) ? `Evidence ${evidenceCount.toFixed(0)}` : "Evidence Warming Up", `Learning Confidence ${modelConfidenceLabel}`],
              ["Model Quality", labelize(performanceHealth), `Status ${labelize(performanceHealth)}`],
              ["Risk Summary", portfolioRiskText, "Source-aware portfolio risk"],
              ["Watching", watchingItems.slice(0, 3).join(" · "), "Observation-only context"],
              ["Go to Learning Center", "Deep dive into Astra intelligence", "Open diagnostics and latest insights"],
            ].map(([title, main, sub], idx) => (
              <button
                key={title}
                type="button"
                onClick={() => (idx === 4 && typeof onNavigate === "function" ? onNavigate("learning") : null)}
                style={{ border: 0, borderRight: idx < 4 ? "1px solid rgba(129, 170, 229, 0.20)" : 0, background: "transparent", padding: 16, textAlign: "left", cursor: idx === 4 ? "pointer" : "default" }}
              >
                <div style={{ color: "#f5f9ff", fontWeight: 950, fontSize: 13 }}>{title}</div>
                <div style={{ color: idx === 4 ? "#8dbbff" : "#dce9fb", fontWeight: 850, fontSize: 12, marginTop: 7 }}>{main}</div>
                <div style={{ color: "#9fb3cf", fontSize: 11, marginTop: 4 }}>{sub}</div>
              </button>
            ))}
          </section>
        </>
      )}

      {topSection !== "dashboard" && (
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
          {error ? <div style={{ marginTop: "8px", color: "#b14450", fontSize: "0.76rem" }}>{error}</div> : null}
        </section>
      )}

      {(topSection === "buys" || topSection === "copilot") && (
        <>
          <section style={{ display: "grid", gridTemplateColumns: "1.1fr 2fr", gap: 14 }}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>{topSection === "copilot" ? "Today's Actions" : "Opportunity Summary"}</h2>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10, marginTop: 12 }}>
                {(topSection === "copilot" ? [
                  ["Buy Now", `${copilotRows.filter((r) => r.action === "BUY_NOW").length}`],
                  ["Hold", `${copilotRows.filter((r) => r.action === "HOLD").length}`],
                  ["Watch Closely", `${copilotRows.filter((r) => r.action === "WATCH_CLOSELY").length}`],
                  ["System Status", copilotStatus?.status || "cached"],
                ] : opportunitySummary).map(([label, value]) => (
                  <div key={label} style={{ borderRadius: 14, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "11px 12px" }}>
                    <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 900, textTransform: "uppercase" }}>{label}</div>
                    <div style={{ color: "#f5f9ff", fontSize: 17, fontWeight: 950, marginTop: 4 }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>{topSection === "copilot" ? "Copilot Guidance Center" : "Astra Opportunity Center"}</h2>
              <p style={{ margin: "10px 0 0", color: "#9fb3cf", fontSize: "0.9rem", lineHeight: 1.55 }}>
                {topSection === "copilot"
                  ? "Copilot translates Astra's existing rankings, horizon context, and diagnostics into advisory actions. It does not create trades, block trades, sell positions, or change ranking logic."
                  : "A consumer-ready view of Astra's ranked opportunities. Confidence, horizon, risk fit, and plain-English rationale are surfaced first while deeper technical evidence remains available inside expandable details."}
              </p>
            </div>
          </section>

          {topSection === "copilot" && (
            <section style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 10 }}>
              {[
                ["BUY_NOW", "Buy Now"],
                ["HOLD", "Hold"],
                ["WATCH_CLOSELY", "Watch Closely"],
                ["APPROACHING_SELL", "Approaching Sell"],
                ["SELL_RECOMMENDED", "Sell Recommended"],
              ].map(([action, label]) => (
                <div key={action} style={{ ...panelStyle, padding: 14, minHeight: 120 }}>
                  <h2 style={{ ...panelTitleStyle, fontSize: 13 }}>{label}</h2>
                  <div style={{ color: "#f5f9ff", fontSize: 24, fontWeight: 950, marginTop: 8 }}>
                    {copilotRows.filter((r) => r.action === action).length}
                  </div>
                  <div style={{ color: "#9fb3cf", fontSize: 11, marginTop: 6 }}>
                    {action === "APPROACHING_SELL" || action === "SELL_RECOMMENDED"
                      ? "Exit center remains advisory. No paper sell behavior is enabled."
                      : "Derived from existing cached rankings."}
                  </div>
                </div>
              ))}
            </section>
          )}

          <section style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              <div>
                <h2 style={panelTitleStyle}>{topSection === "copilot" ? "Why Astra Chose This" : "Astra Opportunities"}</h2>
                <div style={{ color: "#9fb3cf", fontSize: "0.84rem", marginTop: 3 }}>
                  {topSection === "copilot"
                    ? "These cards reuse the unchanged ranked opportunity payload. Copilot language is advisory-only and source-aware."
                    : "Ranking logic is unchanged. Technical details stay collapsible so the default experience feels like an opportunity center rather than a diagnostic dump."}
                </div>
              </div>
            </div>
            <TickerGrid
              stocks={stocks}
              stockTitle="Ranked Opportunity Detail"
              showCryptoColumn={false}
              emptyText={loading ? "Loading stock opportunities…" : "No stock signals found"}
              cardContext="top-buy"
              onAddPosition={handleAddPosition}
              positionActionState={effectivePositionActionState}
            />
          </section>

          {topSection === "copilot" && (
            <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
              {[
                ["Exit Center", "Approaching sell and sell-recommended categories are visible for review only. Natural exits remain preserved."],
                ["What Changed Today", "Copilot refreshes from cached dashboard data and unified diagnostics. No model/provider calls happen during render."],
                ["Copilot System Sources", "Cached top_buys, unified diagnostics, horizon lifecycle readiness, candidate ranking attribution, and portfolio context."],
              ].map(([title, copy]) => (
                <div key={title} style={panelStyle}>
                  <h2 style={panelTitleStyle}>{title}</h2>
                  <p style={{ color: "#9fb3cf", fontSize: 13, lineHeight: 1.55 }}>{copy}</p>
                </div>
              ))}
            </section>
          )}
        </>
      )}

      {topSection === "positions" && (
        <>
          <section style={{ display: "grid", gridTemplateColumns: "1.1fr 1.3fr 1fr", gap: 14 }}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Portfolio Summary</h2>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 10, marginTop: 12 }}>
                {[
                  ["Total value", portfolioValue],
                  ["Day P/L", formatSignedPct(avgPositionPnl)],
                  ["Buying power", buyingPowerValue],
                  ["Active positions", `${brokerActiveCount}`],
                ].map(([label, value]) => (
                  <div key={label} style={{ borderRadius: 14, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "10px 11px" }}>
                    <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 900, textTransform: "uppercase" }}>{label}</div>
                    <div style={{ color: "#f5f9ff", fontSize: 17, fontWeight: 950, marginTop: 4 }}>{value}</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={panelStyle}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center" }}>
                <h2 style={panelTitleStyle}>Performance Overview</h2>
                <div style={{ display: "flex", gap: 6 }}>
                  {["Daily", "Weekly"].map((label, idx) => (
                    <button key={label} type="button" style={{ border: "1px solid #d6e2ef", background: idx === 0 ? "#eef4ff" : "#fff", color: idx === 0 ? "#8dbbff" : "#9fb3cf", borderRadius: 10, padding: "5px 9px", fontSize: 11, fontWeight: 900, cursor: "pointer" }}>{label}</button>
                  ))}
                </div>
              </div>
              <div style={{ color: avgPositionPnl >= 0 ? "#079246" : "#c43d4b", fontSize: 28, fontWeight: 950, marginTop: 8 }}>{formatSignedPct(avgPositionPnl)}</div>
              <svg viewBox="0 0 520 160" width="100%" height="160" role="img" aria-label="Portfolio performance overview">
                <defs>
                  <linearGradient id="astraPortfolioTabFill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#2c7cff" stopOpacity="0.24" />
                    <stop offset="100%" stopColor="#2c7cff" stopOpacity="0.03" />
                  </linearGradient>
                </defs>
                <path d="M0 120 C 60 128, 112 88, 168 92 S 285 62, 344 68 S 438 34, 520 38 L520 160 L0 160 Z" fill="url(#astraPortfolioTabFill)" />
                <path d="M0 120 C 60 128, 112 88, 168 92 S 285 62, 344 68 S 438 34, 520 38" fill="none" stroke="#1468f0" strokeWidth="4" strokeLinecap="round" />
              </svg>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Risk & Allocation</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                {riskLines.map(([label, value]) => (
                  <div key={label} style={{ borderRadius: 12, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "10px 11px", color: "#dce9fb", fontSize: 12.5, fontWeight: 800 }}>
                    <span style={{ color: "#9fb3cf" }}>{label}: </span>{value}
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Top Movers</h2>
              <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
                <div style={{ borderRadius: 14, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "11px 12px" }}>
                  <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 900, textTransform: "uppercase" }}>Biggest winner</div>
                  <div style={{ color: "#f5f9ff", fontWeight: 950, marginTop: 4 }}>{biggestWinner?.symbol || "Data Not Available"}</div>
                  <div style={{ color: "#079246", fontSize: 13, marginTop: 2 }}>{biggestWinner?.symbol ? formatSignedPct(biggestWinner?.pnl_percent) : "Warming Up"}</div>
                </div>
                <div style={{ borderRadius: 14, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "11px 12px" }}>
                  <div style={{ color: "#9fb3cf", fontSize: 10, fontWeight: 900, textTransform: "uppercase" }}>Biggest loser</div>
                  <div style={{ color: "#f5f9ff", fontWeight: 950, marginTop: 4 }}>{biggestLoser?.symbol || "Data Not Available"}</div>
                  <div style={{ color: "#c43d4b", fontSize: 13, marginTop: 2 }}>{biggestLoser?.symbol ? formatSignedPct(biggestLoser?.pnl_percent) : "Warming Up"}</div>
                </div>
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Largest Position</h2>
              <div style={{ marginTop: 12, borderRadius: 16, border: "1px solid rgba(129, 170, 229, 0.20)", background: "rgba(255,255,255,0.06)", padding: "14px 14px" }}>
                <div style={{ color: "#f5f9ff", fontSize: 20, fontWeight: 950 }}>{largestPosition?.symbol || "Data Not Available"}</div>
                <div style={{ color: "#9fb3cf", fontSize: 12, marginTop: 4 }}>Broker-confirmed label remains source-aware.</div>
                <div style={{ color: "#dce9fb", fontSize: 12.5, marginTop: 10 }}>{largestPosition ? `Current ${formatMoney(largestPosition?.current_price ?? largestPosition?.price)}` : "Warming up from cached portfolio context."}</div>
              </div>
            </div>

            <div style={panelStyle}>
              <h2 style={panelTitleStyle}>Portfolio Status</h2>
              <div
                style={{
                  marginTop: 12,
                  padding: "11px 12px",
                  borderRadius: "14px",
                  background: "#0b1d36",
                  color: "#d7e6fb",
                  fontSize: "0.8rem",
                  lineHeight: 1.45,
                }}
              >
                {brokerTruthKnown && brokerActiveCount === 0
                  ? "No broker-confirmed active positions."
                  : compactionSummary}
                {staleRowsHidden > 0 ? ` ${staleRowsHidden} stale internal workflow row${staleRowsHidden === 1 ? "" : "s"} hidden from default view.` : ""}
                {canceledOrdersCompacted > 0 ? ` ${canceledOrdersCompacted} canceled paper order${canceledOrdersCompacted === 1 ? "" : "s"} hidden from default view.` : ""}
              </div>
            </div>
          </section>

          <section style={panelStyle}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: "8px", flexWrap: "wrap", marginBottom: "10px" }}>
              <div>
                <div style={panelTitleStyle}>Active Positions</div>
                <div style={{ color: "#9fb3cf", fontSize: "0.82rem", marginTop: 3 }}>
                  {brokerTruthKnown ? `${brokerActiveCount} broker-confirmed positions` : `${positions.length} workflow positions`} shown in a cleaner portfolio view.
                </div>
              </div>
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
        </>
      )}

      {remoteMode && remoteSection === "sell_alerts" && (
        <section style={panelStyle}>
          <div style={{ ...panelTitleStyle, marginBottom: "8px" }}>Sell Alerts</div>
          <div style={emptyStyle}>Sell alerts are available in the main learning/trading flows.</div>
        </section>
      )}

      {topSection !== "dashboard" && (
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
      )}
    </div>
  );
}
