import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API_BASE_CHANGED_EVENT, fetchJsonWithFallback, getInitialApiBase, resolveApiBase } from "../../apiBase";

const API_BASE = resolveApiBase();

const panelStyle = {
  background: "linear-gradient(180deg, rgba(19,43,74,0.92) 0%, rgba(14,33,58,0.92) 100%)",
  border: "1px solid #335381",
  borderRadius: "12px",
  padding: "12px",
  color: "#e7f0ff",
};

function safeNumber(v, fallback = 0) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function firstNonEmpty(...values) {
  for (const v of values) {
    if (v === undefined || v === null) continue;
    if (typeof v === "string" && v.trim() === "") continue;
    return v;
  }
  return null;
}

function firstFinite(...values) {
  for (const v of values) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return 0;
}

function firstFiniteOrNull(...values) {
  for (const v of values) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function clampValue(value, min = 0, max = 100) {
  return Math.max(min, Math.min(max, Number(value) || 0));
}

function fmtPct(v) {
  return `${safeNumber(v).toFixed(2)}%`;
}

function learningPayloadHasEvidence(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const totals = payload.totals || {};
  const combined = totals.combined || {};
  const validTrades = Number(totals.valid_trades);
  const combinedTradeCount = Number(combined.trade_count);
  const sampleSizes = payload.cohort_sample_sizes || {};
  const cohortReleased = Number(sampleSizes.released);
  const cohortPaper = Number(sampleSizes.paper_ready);
  const cohortBlocked = Number(sampleSizes.blocked_watchlist);
  if (Number.isFinite(validTrades) && validTrades > 0) return true;
  if (Number.isFinite(combinedTradeCount) && combinedTradeCount > 0) return true;
  for (const key of ["closed_trades_count", "valid_labels_count", "replay_rows_available", "replay_rows_integrated", "lifecycle_events_count"]) {
    const n = Number(payload[key]);
    if (Number.isFinite(n) && n > 0) return true;
  }
  const truth = payload.learning_truth_status_v1 || payload.truth || {};
  if (truth && typeof truth === "object") {
    for (const key of ["closed_trades_count", "valid_labels_count", "replay_rows_available", "replay_rows_integrated", "lifecycle_events_count"]) {
      const n = Number(truth[key]);
      if (Number.isFinite(n) && n > 0) return true;
    }
  }
  if (
    (Number.isFinite(cohortReleased) && cohortReleased > 0)
    || (Number.isFinite(cohortPaper) && cohortPaper > 0)
    || (Number.isFinite(cohortBlocked) && cohortBlocked > 0)
  ) return true;
  return false;
}

function learningPayloadLooksFalseEmpty(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const totals = payload.totals || {};
  const combined = totals.combined || {};
  const validTrades = Number(totals.valid_trades);
  const combinedTradeCount = Number(combined.trade_count);
  const runtimeHealth = Number(((payload.runtime_hardening || {}).runtime_health_score));
  const replayContinuity = Number(((payload.worker_watchdog_reliability || {}).replay_continuity_score));
  const learningRefreshContinuity = Number(((payload.worker_watchdog_reliability || {}).learning_refresh_continuity_score));
  const workerInterval = Number(((payload.performance_optimization_suite || {}).worker_interval_seconds));
  const replayInterval = Number(((payload.performance_optimization_suite || {}).replay_interval_seconds));
  const stale = Boolean(payload.learning_payload_stale);
  const source = String(payload.learning_payload_source || "").toLowerCase();
  const hasEvidence = learningPayloadHasEvidence(payload);
  const coreZero =
    (!Number.isFinite(validTrades) || validTrades <= 0)
    && (!Number.isFinite(combinedTradeCount) || combinedTradeCount <= 0)
    && (!Number.isFinite(runtimeHealth) || runtimeHealth <= 0)
    && (!Number.isFinite(replayContinuity) || replayContinuity <= 0)
    && (!Number.isFinite(learningRefreshContinuity) || learningRefreshContinuity <= 0)
    && (!Number.isFinite(workerInterval) || workerInterval <= 0)
    && (!Number.isFinite(replayInterval) || replayInterval <= 0);
  if (hasEvidence) return false;
  if (!coreZero) return false;
  return stale || source.includes("default") || source.includes("warmup") || source.includes("fallback");
}

function metricTone(score, strongCut = 70, mixedCut = 50) {
  const n = safeNumber(score);
  if (n >= strongCut) return "strong";
  if (n >= mixedCut) return "mixed";
  return "weak";
}

function toneColors(tone) {
  if (tone === "strong") {
    return { badgeBg: "rgba(24,95,68,0.45)", badgeBorder: "#2fb681", badgeText: "#a9f8d1" };
  }
  if (tone === "mixed") {
    return { badgeBg: "rgba(108,83,27,0.45)", badgeBorder: "#d9aa3b", badgeText: "#ffe2a1" };
  }
  if (tone === "caution") {
    return { badgeBg: "rgba(110,52,22,0.45)", badgeBorder: "#f38f52", badgeText: "#ffd2b4" };
  }
  return { badgeBg: "rgba(102,44,55,0.45)", badgeBorder: "#df6a85", badgeText: "#ffd0dc" };
}

const ADVANCED_METRIC_FALLBACK_CARDS = [
  { key: "entryQuality", title: "Entry Quality V2", source_endpoint: "/api/entry_quality_status_v2" },
  { key: "consensus", title: "Multi-Brain Consensus", source_endpoint: "/api/multi_brain_consensus_status_v1" },
  { key: "learningDataQuality", title: "Learning Data Quality V2", source_endpoint: "/api/learning_data_quality_v1" },
  { key: "tradeLifecycle", title: "Trade Lifecycle Intelligence", source_endpoint: "/api/trade_lifecycle_status_v1" },
  { key: "policyCompare", title: "Policy Backtest V2", source_endpoint: "/api/policy_compare_v1" },
  { key: "selfCorrection", title: "Self-Correction V2", source_endpoint: "/api/self_correction_recommendations_v1" },
  { key: "fmpUtilization", title: "FMP Utilization", source_endpoint: "/api/fmp_utilization_status_v1" },
  { key: "jsonlMaintenance", title: "JSONL Maintenance", source_endpoint: "/api/jsonl_maintenance_status_v1" },
  { key: "replayCounterfactual", title: "Replay Counterfactual Analysis", source_endpoint: "/api/replay_counterfactual_status_v1" },
  { key: "marketDataOrchestration", title: "Market Data Orchestration", source_endpoint: "/api/market_data_orchestration_status_v1" },
  { key: "acceleratedLearning", title: "Accelerated Learning", source_endpoint: "/api/accelerated_learning_status_v1" },
  { key: "consensusReplay", title: "Consensus Replay", source_endpoint: "/api/multi_brain_consensus_replay_status_v1" },
  { key: "parallelReplay", title: "Parallel Replay Orchestrator", source_endpoint: "/api/parallel_replay_orchestrator_status_v1" },
  { key: "marketKnowledge", title: "Market Knowledge", source_endpoint: "/api/market_knowledge_status_v1" },
  { key: "walkForward", title: "Walk-Forward Validation", source_endpoint: "/api/walk_forward_validation_status_v1" },
  { key: "performanceOptimization", title: "Performance Optimization", source_endpoint: "/api/performance_optimization_status_v1" },
];

const LEARNING_TREND_WINDOWS = [
  { key: "1D", label: "1 Day", points: 36 },
  { key: "1W", label: "1 Week", points: 84 },
  { key: "1M", label: "1 Month", points: 120 },
  { key: "3M", label: "3 Months", points: 180 },
  { key: "1Y", label: "1 Year", points: 240 },
];

const LEARNING_TAB_CACHE_TTL_MS = 15 * 60 * 1000;
let LEARNING_TAB_MEMORY_CACHE = {
  data: null,
  endpointStatus: null,
  timeline: null,
  lastFetchAt: "",
  cachedAtMs: 0,
  freshness: null,
  truth: null,
};

function metricValue(...values) {
  const n = firstFiniteOrNull(...values);
  return n === null ? "Not loaded yet" : n.toFixed(1);
}

function statusText(value, fallback = "Not loaded yet") {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value).replaceAll("_", " ");
}

function InstitutionalMetricCard({ title, value, detail, status }) {
  const normalizedStatus = String(status || "unavailable").toLowerCase();
  const statusLabel = normalizedStatus === "loaded"
    ? "Loaded"
    : normalizedStatus === "stale"
      ? "Stale"
      : normalizedStatus === "still_computing"
        ? "Still computing"
        : normalizedStatus === "error"
          ? "Error"
          : "Unavailable";
  const statusColor = normalizedStatus === "loaded" ? "#a9f8d1" : normalizedStatus === "stale" ? "#ffe2a1" : "#ffd2b4";
  return (
    <div style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 8, padding: "10px 11px", display: "grid", gap: 5 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
        <div style={{ fontSize: 12, color: "#d5e6ff", fontWeight: 700 }}>{title}</div>
        <div style={{ color: statusColor, fontSize: 10, textTransform: "uppercase" }}>
          {statusLabel}
        </div>
      </div>
      <div style={{ fontSize: 18, lineHeight: 1.1, fontWeight: 800, color: "#f2f7ff" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#97afcf" }}>{detail}</div>
    </div>
  );
}

function normalizeAdvancedSnapshotCards(rawCards, fallbackReason = "Snapshot did not load within the UI timeout.") {
  const asArray = Array.isArray(rawCards)
    ? rawCards
    : (rawCards && typeof rawCards === "object"
      ? Object.entries(rawCards).map(([key, value]) => ({ key, ...(value || {}) }))
      : []);
  return asArray.map((card, idx) => {
    const fallbackCard = ADVANCED_METRIC_FALLBACK_CARDS.find((item) => item.key === card?.key) || ADVANCED_METRIC_FALLBACK_CARDS[idx] || {};
    const rawStatus = String(card?.status || "unavailable").toLowerCase();
    const status = rawStatus === "fresh" ? "loaded" : rawStatus;
    return {
      key: card?.key || fallbackCard.key || `advancedCard${idx}`,
      title: card?.title || fallbackCard.title || "Advanced Metric",
      status: ["loaded", "stale", "still_computing", "error", "unavailable"].includes(status) ? status : "unavailable",
      primary_value: firstNonEmpty(card?.primary_value, card?.primary, card?.value, "Snapshot unavailable"),
      secondary_value: firstNonEmpty(card?.secondary_value, card?.secondary, ""),
      detail_value: firstNonEmpty(card?.detail_value, card?.detail, card?.error_reason, fallbackReason),
      updated_at: card?.updated_at || new Date().toISOString(),
      source_endpoint: card?.source_endpoint || fallbackCard.source_endpoint || "/api/advanced_metrics_snapshot_v1",
      error_reason: firstNonEmpty(card?.error_reason, status === "loaded" || status === "stale" ? "" : fallbackReason, ""),
    };
  });
}

export default function LearningTab({ compact = false }) {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [loading, setLoading] = useState(false);
  const [secondaryLoading, setSecondaryLoading] = useState(false);
  const [lastFetchAt, setLastFetchAt] = useState(LEARNING_TAB_MEMORY_CACHE.lastFetchAt || "");
  const [fetchError, setFetchError] = useState("");
  const [showDebug, setShowDebug] = useState(false);
  const [showAdvancedSections, setShowAdvancedSections] = useState(false);
  const [learningTrendWindow, setLearningTrendWindow] = useState("1D");
  const [manualRefreshNonce, setManualRefreshNonce] = useState(0);
  const [advancedLoading, setAdvancedLoading] = useState(false);
  const [advancedLoadedOnce, setAdvancedLoadedOnce] = useState(false);
  const [advancedInstitutional, setAdvancedInstitutional] = useState({});
  const [advancedEndpointStatus, setAdvancedEndpointStatus] = useState({});
  const [advancedSnapshot, setAdvancedSnapshot] = useState(null);
  const [advancedSnapshotMessage, setAdvancedSnapshotMessage] = useState("");
  const [adaptiveQuantStatus, setAdaptiveQuantStatus] = useState(null);
  const [adaptiveQuantMessage, setAdaptiveQuantMessage] = useState("Not requested");
  const [multiHorizonStatus, setMultiHorizonStatus] = useState(null);
  const [multiHorizonMessage, setMultiHorizonMessage] = useState("Not requested");
  const [learningExecutionStatus, setLearningExecutionStatus] = useState(null);
  const [learningExecutionMessage, setLearningExecutionMessage] = useState("Not requested");
  const [contextProfitabilityStatus, setContextProfitabilityStatus] = useState(null);
  const [contextProfitabilityMessage, setContextProfitabilityMessage] = useState("Not requested");
  const [portfolioRiskIntelStatus, setPortfolioRiskIntelStatus] = useState(null);
  const [portfolioRiskIntelMessage, setPortfolioRiskIntelMessage] = useState("Not requested");
  const [institutionalTrend, setInstitutionalTrend] = useState([]);
  const [endpointStatus, setEndpointStatus] = useState(LEARNING_TAB_MEMORY_CACHE.endpointStatus || {});
  const [timeline, setTimeline] = useState(LEARNING_TAB_MEMORY_CACHE.timeline || []);
  const [learningFreshness, setLearningFreshness] = useState(LEARNING_TAB_MEMORY_CACHE.freshness || {});
  const [learningTruth, setLearningTruth] = useState(LEARNING_TAB_MEMORY_CACHE.truth || {});
  const [manualRefreshMessage, setManualRefreshMessage] = useState("");
  const [data, setData] = useState(LEARNING_TAB_MEMORY_CACHE.data || {
    learningSnapshotFast: {},
    learningInsights: {},
    paper: {},
    paperStatus: {},
    workerStatus: {},
    model: {},
    topBuys: {},
    systemStatus: {},
  });
  const refreshInFlightRef = useRef(false);

  useEffect(() => {
    const syncBase = () => setResolvedApiBase(getInitialApiBase());
    window.addEventListener(API_BASE_CHANGED_EVENT, syncBase);
    return () => window.removeEventListener(API_BASE_CHANGED_EVENT, syncBase);
  }, []);

  useEffect(() => {
    let mounted = true;

    const fetchJson = async (key, path, fallback, opts = {}) => {
      const result = await fetchJsonWithFallback(path, {
        preferredBase: resolvedApiBase || API_BASE,
        fallbackValue: fallback,
        timeoutMs: opts.timeoutMs,
      });
      try {
        const parsed = result.parsed;
        if (
          (Array.isArray(parsed) && parsed.length === 0) ||
          (parsed && typeof parsed === "object" && Object.keys(parsed).length === 0)
        ) {
          console.warn("[Astra] empty response", {
            endpoint: result.url,
            responseShapeKeys: parsed && typeof parsed === "object" ? Object.keys(parsed) : [],
          });
        }
        if (result.ok && mounted && result.baseUsed && result.baseUsed !== resolvedApiBase) {
          setResolvedApiBase(result.baseUsed);
        }
        return {
          key,
          url: result.url,
          ok: result.ok,
          httpStatus: result.httpStatus,
          parsed,
          error: result.error || "",
        };
      } catch (err) {
        return {
          key,
          url: result.url,
          ok: false,
          httpStatus: result.httpStatus ?? null,
          parsed: fallback,
          error: result.error || (err instanceof Error ? err.message : String(err)),
        };
      }
    };

    const refresh = async () => {
      if (refreshInFlightRef.current) return;
      const cacheAgeMs = Date.now() - Number(LEARNING_TAB_MEMORY_CACHE.cachedAtMs || 0);
      if (
        LEARNING_TAB_MEMORY_CACHE.data
        && cacheAgeMs >= 0
        && cacheAgeMs < LEARNING_TAB_CACHE_TTL_MS
      ) {
        setData(LEARNING_TAB_MEMORY_CACHE.data);
        setEndpointStatus(LEARNING_TAB_MEMORY_CACHE.endpointStatus || {});
        setTimeline(LEARNING_TAB_MEMORY_CACHE.timeline || []);
        setLearningFreshness(LEARNING_TAB_MEMORY_CACHE.freshness || {});
        setLearningTruth(LEARNING_TAB_MEMORY_CACHE.truth || {});
        setLastFetchAt(LEARNING_TAB_MEMORY_CACHE.lastFetchAt || "");
        setLoading(false);
        setSecondaryLoading(false);
        setFetchError("");
        return;
      }
      refreshInFlightRef.current = true;
      setLoading(true);
      setSecondaryLoading(false);
      setFetchError("");
      const hadUsableTopBuys =
        Array.isArray(data?.topBuys?.stocks?.final) && data.topBuys.stocks.final.length > 0;
      try {
        const fastSnapshot = await fetchJson(
          "learning_snapshot_fast_v1",
          "/api/learning_snapshot_fast_v1",
          {},
          { timeoutMs: 8000 },
        );
        if (mounted) {
          setEndpointStatus((prev) => ({
            ...(prev || {}),
            learning_snapshot_fast_v1: {
              url: fastSnapshot.url,
              httpStatus: fastSnapshot.httpStatus ?? null,
              error: fastSnapshot.ok ? "" : String(fastSnapshot.error || ""),
            },
          }));
          if (fastSnapshot.ok && fastSnapshot.parsed && typeof fastSnapshot.parsed === "object") {
            setData((prev) => {
              const prevSafe = prev || {};
              const learningSnapshotFast = fastSnapshot.parsed || {};
              const fastSnapshotAsInsights = {
                current_engine_outcome_evaluation: {
                  released_hero_win_rate: safeNumber(learningSnapshotFast.current_engine_released_wr),
                  released_vs_blocked_win_rate_delta: safeNumber(learningSnapshotFast.released_vs_blocked_wr_gap),
                },
                entry_quality_score: safeNumber(learningSnapshotFast.entry_quality),
                follow_through_quality_score: safeNumber(learningSnapshotFast.follow_through_quality),
                buy_list_purity_score: safeNumber(learningSnapshotFast.buy_list_purity),
                current_engine_exit_timing_score: safeNumber(learningSnapshotFast.exit_quality),
                learning_quality: {
                  quality_score: safeNumber(learningSnapshotFast.runtime_learning_stability),
                  trend: String(learningSnapshotFast.current_trend || "stable"),
                },
                runtime_hardening: {
                  resilience_score: safeNumber(learningSnapshotFast.runtime_learning_stability),
                },
                learning_payload_degraded_reason: String(learningSnapshotFast.degraded_reason || ""),
                best_worst: {
                  best_setup_type: String(learningSnapshotFast.strongest_area || "insufficient_data"),
                  worst_setup_type: String(learningSnapshotFast.biggest_weakness || "insufficient_data"),
                },
                execution_readiness_controls: {
                  readiness_tier: String(learningSnapshotFast.operating_posture || "guarded"),
                },
                generated_at: String(learningSnapshotFast.updated_at || ""),
                last_updated_utc: String(learningSnapshotFast.updated_at || ""),
                learning_payload_source: firstNonEmpty(learningSnapshotFast.learning_payload_source, learningSnapshotFast.source, "learning_snapshot_fast_v1"),
                learning_payload_stale: Boolean(learningSnapshotFast.fallback_snapshot_used),
                learning_truth_status_v1: learningSnapshotFast.truth || {},
                };
              const existingInsights = prevSafe.learningInsights && typeof prevSafe.learningInsights === "object"
                ? prevSafe.learningInsights
                : {};
              return {
                ...prevSafe,
                learningSnapshotFast,
                learningInsights: {
                  ...fastSnapshotAsInsights,
                  ...existingInsights,
                  current_engine_outcome_evaluation: {
                    ...(fastSnapshotAsInsights.current_engine_outcome_evaluation || {}),
                    ...(existingInsights.current_engine_outcome_evaluation || {}),
                  },
                  learning_quality: {
                    ...(fastSnapshotAsInsights.learning_quality || {}),
                    ...(existingInsights.learning_quality || {}),
                  },
                  runtime_hardening: {
                    ...(fastSnapshotAsInsights.runtime_hardening || {}),
                    ...(existingInsights.runtime_hardening || {}),
                  },
                  best_worst: {
                    ...(fastSnapshotAsInsights.best_worst || {}),
                    ...(existingInsights.best_worst || {}),
                  },
                  execution_readiness_controls: {
                    ...(fastSnapshotAsInsights.execution_readiness_controls || {}),
                    ...(existingInsights.execution_readiness_controls || {}),
                  },
                },
              };
            });
          }
          setLoading(false);
          setLastFetchAt(new Date().toISOString());
          setSecondaryLoading(true);
        }
        if (!mounted) return;

        const secondaryBatch = await Promise.all([
          fetchJson("paper_performance", "/api/paper_performance", {}, { timeoutMs: 8000 }),
          fetchJson("paper_status", "/api/paper_status", {}, { timeoutMs: 8000 }),
          fetchJson("system_status", "/api/system_status", {}, { timeoutMs: 5000 }),
          fetchJson("model_status", "/api/model_status", {}, { timeoutMs: 5000 }),
          fetchJson("paper_worker_status", "/api/paper_worker_status", {}, { timeoutMs: 5000 }),
          fetchJson("top_buys", "/api/top_buys?buy_mode=balanced", {}, { timeoutMs: 5000 }),
          fetchJson("learning_insights", "/api/learning_insights", {}, { timeoutMs: 8000 }),
          fetchJson("learning_freshness", "/api/learning_freshness_status_v1", {}, { timeoutMs: 5000 }),
          fetchJson("learning_truth", "/api/learning_truth_status_v1", {}, { timeoutMs: 5000 }),
        ]);
        if (!mounted) return;

        const results = [...secondaryBatch];
        const statuses = {};
        const errors = [];
        results.forEach((r) => {
        const isTransientTopBuysTimeout =
          r.key === "top_buys"
          && !r.ok
          && String(r.error || "").startsWith("timeout_after_")
          && hadUsableTopBuys;
        const effectiveError = isTransientTopBuysTimeout ? "" : String(r.error || "");
        statuses[r.key] = { url: r.url, httpStatus: r.httpStatus ?? null, error: r.ok ? "" : String(r.error || "") };
        if (isTransientTopBuysTimeout) {
          statuses[r.key] = {
            url: r.url,
            httpStatus: r.httpStatus ?? null,
            error: "stale_top_buys_retained",
          };
        }
        if (!r.ok && !isTransientTopBuysTimeout) errors.push(`${r.key}: ${effectiveError}`);
        });
        setEndpointStatus((prev) => ({ ...(prev || {}), ...statuses }));
        setLoading(false);
        setSecondaryLoading(false);
        setLastFetchAt(new Date().toISOString());
        if (errors.length > 0) setFetchError(errors.join(" | "));

        const byKey = Object.fromEntries(results.map((r) => [r.key, r]));
        const freshnessPayload = byKey.learning_freshness?.parsed && typeof byKey.learning_freshness.parsed === "object"
          ? byKey.learning_freshness.parsed
          : {};
        if (Object.keys(freshnessPayload).length > 0) setLearningFreshness(freshnessPayload);
        const truthPayload = byKey.learning_truth?.parsed && typeof byKey.learning_truth.parsed === "object"
          ? byKey.learning_truth.parsed
          : {};
        if (Object.keys(truthPayload).length > 0) setLearningTruth(truthPayload);
        const isNonEmptyObject = (v) =>
        Boolean(v && typeof v === "object" && !Array.isArray(v) && Object.keys(v).length > 0);
      const selectPayload = (key, previousValue = {}) => {
        const r = byKey[key] || {};
        const parsed = r.parsed;
        if (r.ok && (isNonEmptyObject(parsed) || Array.isArray(parsed))) return parsed;
        return previousValue || {};
      };

        setData((prev) => {
        const prevSafe = prev || {};
        const paper = selectPayload("paper_performance", prevSafe.paper);
        const paperStatus = selectPayload("paper_status", prevSafe.paperStatus);
        const workerStatus = selectPayload("paper_worker_status", prevSafe.workerStatus);
        const model = selectPayload("model_status", prevSafe.model);
        const topBuys = selectPayload("top_buys", prevSafe.topBuys);
        const systemStatus = selectPayload("system_status", prevSafe.systemStatus);
        const learningSnapshotFast = prevSafe.learningSnapshotFast || {};
        const learningCandidate = selectPayload("learning_insights", prevSafe.learningInsights);
        const prevLearning = (prevSafe.learningInsights && typeof prevSafe.learningInsights === "object")
          ? prevSafe.learningInsights
          : {};
        const candidateLooksFalseEmpty = learningPayloadLooksFalseEmpty(learningCandidate);
        const prevHasEvidence = learningPayloadHasEvidence(prevLearning);
        const candidateHasEvidence = learningPayloadHasEvidence(learningCandidate);
        const paperValidClosed = safeNumber((paper?.combined || {}).valid_closed, paper?.closed_trades_count);
        let learningInsights = learningCandidate;
        if (candidateLooksFalseEmpty && (prevHasEvidence || paperValidClosed > 0)) {
          learningInsights = {
            ...prevLearning,
            learning_payload_source: firstNonEmpty(prevLearning?.learning_payload_source, "ui_last_known_good_guard"),
            learning_payload_stale: true,
            learning_payload_degraded_reason: "ui_false_empty_guard_active",
            learning_payload_false_empty_prevented: true,
            ui_false_empty_guard_active: true,
            ui_false_empty_guard_reason: paperValidClosed > 0
              ? "paper_history_present_false_empty_suppressed"
              : "previous_learning_evidence_present_false_empty_suppressed",
            ui_false_empty_guard_ts: new Date().toISOString(),
          };
        } else if (!candidateHasEvidence && prevHasEvidence && candidateLooksFalseEmpty) {
          learningInsights = {
            ...prevLearning,
            learning_payload_source: firstNonEmpty(prevLearning?.learning_payload_source, "ui_last_known_good_guard"),
            learning_payload_stale: true,
            learning_payload_degraded_reason: "ui_false_empty_guard_active",
            learning_payload_false_empty_prevented: true,
            ui_false_empty_guard_active: true,
            ui_false_empty_guard_reason: "previous_evidence_retained",
            ui_false_empty_guard_ts: new Date().toISOString(),
          };
        }
        const fastSnapshotAsInsights =
          learningSnapshotFast && typeof learningSnapshotFast === "object"
            ? {
              current_engine_outcome_evaluation: {
                released_hero_win_rate: safeNumber(learningSnapshotFast.current_engine_released_wr),
                released_vs_blocked_win_rate_delta: safeNumber(learningSnapshotFast.released_vs_blocked_wr_gap),
              },
              entry_quality_score: safeNumber(learningSnapshotFast.entry_quality),
              follow_through_quality_score: safeNumber(learningSnapshotFast.follow_through_quality),
              buy_list_purity_score: safeNumber(learningSnapshotFast.buy_list_purity),
              current_engine_exit_timing_score: safeNumber(learningSnapshotFast.exit_quality),
              learning_quality: {
                quality_score: safeNumber(learningSnapshotFast.runtime_learning_stability),
                trend: String(learningSnapshotFast.current_trend || "stable"),
              },
              runtime_hardening: {
                resilience_score: safeNumber(learningSnapshotFast.runtime_learning_stability),
              },
              learning_payload_degraded_reason: String(learningSnapshotFast.degraded_reason || ""),
              best_worst: {
                best_setup_type: String(learningSnapshotFast.strongest_area || "insufficient_data"),
                worst_setup_type: String(learningSnapshotFast.biggest_weakness || "insufficient_data"),
              },
              execution_readiness_controls: {
                readiness_tier: String(learningSnapshotFast.operating_posture || "guarded"),
              },
              generated_at: String(learningSnapshotFast.updated_at || ""),
              last_updated_utc: String(learningSnapshotFast.updated_at || ""),
              learning_payload_source: firstNonEmpty(learningSnapshotFast.learning_payload_source, learningSnapshotFast.source, "learning_snapshot_fast_v1"),
              learning_payload_stale: Boolean(learningSnapshotFast.fallback_snapshot_used),
              learning_truth_status_v1: learningSnapshotFast.truth || truthPayload || {},
            }
            : {};
        if (
          (!learningInsights || Object.keys(learningInsights).length === 0)
          && fastSnapshotAsInsights
          && Object.keys(fastSnapshotAsInsights).length > 0
        ) {
          learningInsights = fastSnapshotAsInsights;
        } else if (
          learningInsights
          && typeof learningInsights === "object"
          && fastSnapshotAsInsights
          && Object.keys(fastSnapshotAsInsights).length > 0
        ) {
          learningInsights = {
            ...fastSnapshotAsInsights,
            ...learningInsights,
            current_engine_outcome_evaluation: {
              ...(fastSnapshotAsInsights.current_engine_outcome_evaluation || {}),
              ...((learningInsights || {}).current_engine_outcome_evaluation || {}),
            },
            learning_quality: {
              ...(fastSnapshotAsInsights.learning_quality || {}),
              ...((learningInsights || {}).learning_quality || {}),
            },
            runtime_hardening: {
              ...(fastSnapshotAsInsights.runtime_hardening || {}),
              ...((learningInsights || {}).runtime_hardening || {}),
            },
            best_worst: {
              ...(fastSnapshotAsInsights.best_worst || {}),
              ...((learningInsights || {}).best_worst || {}),
            },
            execution_readiness_controls: {
              ...(fastSnapshotAsInsights.execution_readiness_controls || {}),
              ...((learningInsights || {}).execution_readiness_controls || {}),
            },
          };
        }
        const promotionSummary = topBuys?.candidate_promotion_summary || {};
        const buyConversionEngine = promotionSummary?.buy_conversion_engine || {};
        const buyToPosition = promotionSummary?.buy_to_position_feedback_suite || {};

        const timelinePoint = {
          ts: new Date().toLocaleTimeString(),
          winRate: safeNumber((paper?.paper_cohort_trends?.recent || {}).win_rate, paper?.win_rate),
          medianReturn: safeNumber((paper?.paper_cohort_trends?.recent || {}).median_return, paper?.avg_return),
          winsorized: safeNumber((paper?.paper_cohort_trends?.recent || {}).winsorized_avg_return, paper?.avg_return),
          buyConversion: safeNumber(buyConversionEngine?.buy_conversion_score),
          entryQuality: safeNumber(learningInsights?.entry_quality_score, learningSnapshotFast?.entry_quality),
          buyListPurity: safeNumber(learningInsights?.buy_list_purity_score, learningSnapshotFast?.buy_list_purity),
          followThroughQuality: safeNumber(learningInsights?.follow_through_quality_score, learningSnapshotFast?.follow_through_quality),
          confidenceTruthfulness: safeNumber(learningInsights?.confidence_truthfulness_score, buyConversionEngine?.confidence_truthfulness_score),
          overblocking: safeNumber(buyConversionEngine?.overblocking_score),
          sellAccuracy: safeNumber(buyToPosition?.sell_signal_accuracy_score),
        };
        const nextTimeline = [...(Array.isArray(timeline) ? timeline : []), timelinePoint].slice(-36);
        setTimeline(nextTimeline);

        const nextData = {
          learningSnapshotFast,
          learningInsights,
          paper,
          paperStatus,
          workerStatus,
          model,
          topBuys,
          systemStatus,
        };
        LEARNING_TAB_MEMORY_CACHE = {
          data: nextData,
          endpointStatus: { ...statuses },
          timeline: nextTimeline,
          lastFetchAt: new Date().toISOString(),
          cachedAtMs: Date.now(),
          freshness: freshnessPayload,
          truth: truthPayload,
        };
        return nextData;
        });
      } finally {
        refreshInFlightRef.current = false;
      }
    };

    refresh();
    const timer = setInterval(refresh, LEARNING_TAB_CACHE_TTL_MS);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [resolvedApiBase, manualRefreshNonce]);

  const handleManualLearningRefresh = async () => {
    setManualRefreshMessage("Refreshing local learning snapshot...");
    try {
      const result = await fetchJsonWithFallback("/api/rebuild_learning_snapshot_v1?safe=true", {
        preferredBase: resolvedApiBase || API_BASE,
        fallbackValue: { ok: false, error: "rebuild request failed" },
        timeoutMs: 8000,
      });
      const parsed = result?.parsed || {};
      if (parsed.ok) {
        LEARNING_TAB_MEMORY_CACHE = { ...LEARNING_TAB_MEMORY_CACHE, cachedAtMs: 0 };
        setLearningTruth(parsed.learning_truth || {});
        setManualRefreshMessage("Learning snapshot refreshed from local sources.");
        setManualRefreshNonce((value) => value + 1);
      } else {
        setManualRefreshMessage(`Refresh unavailable: ${parsed.error || result.error || "unknown reason"}`);
      }
    } catch (err) {
      setManualRefreshMessage(`Refresh failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  useEffect(() => {
    if (!showAdvancedSections || advancedLoadedOnce) return undefined;
    let cancelled = false;
    const controller = new AbortController();
    let timeoutId = null;

    const fallbackSnapshot = (reason) => ({
      enabled: false,
      mode: "frontend_timeout_fallback",
      snapshot_generated_at: new Date().toISOString(),
      snapshot_age_seconds: 0,
      cards: ADVANCED_METRIC_FALLBACK_CARDS.map((card) => ({
        key: card.key,
        title: card.title,
        status: "unavailable",
        primary_value: "Snapshot unavailable",
        secondary_value: "Advanced metrics unavailable or still computing",
        detail_value: reason || "Snapshot did not load within the UI timeout.",
        updated_at: new Date().toISOString(),
        source_endpoint: card.source_endpoint,
        error_reason: reason || "frontend_snapshot_timeout",
      })),
      unavailable_cards: ADVANCED_METRIC_FALLBACK_CARDS.map((card) => card.key),
      stale_cards: [],
      total_cards: ADVANCED_METRIC_FALLBACK_CARDS.length,
      cards_loaded: 0,
      cards_failed: ADVANCED_METRIC_FALLBACK_CARDS.length,
      load_strategy: "frontend_timeout_fallback",
      recommended_action: "Advanced metrics unavailable or still computing",
    });

    const fetchAdvancedSnapshot = async () => {
      timeoutId = window.setTimeout(() => {
        try { controller.abort(); } catch (_e) {}
      }, 8000);
      const response = await fetch("/api/advanced_metrics_snapshot_v1", {
        method: "GET",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`${response.status} ${response.statusText}${body ? ` :: ${body.slice(0, 160)}` : ""}`);
      }
      return response.json();
    };

    const loadAdvancedInstitutional = async () => {
      setAdvancedLoading(true);
      setAdvancedSnapshotMessage("Loading fast advanced metrics snapshot...");
      try {
        const parsed = await fetchAdvancedSnapshot();
        const snapshot = parsed && typeof parsed === "object" ? parsed : fallbackSnapshot("advanced_metrics_snapshot_unavailable");
        const cards = normalizeAdvancedSnapshotCards(snapshot.cards, "Advanced metrics unavailable or still computing");
        snapshot.cards = cards;
        snapshot.total_cards = Number(snapshot.total_cards || cards.length || ADVANCED_METRIC_FALLBACK_CARDS.length);
        snapshot.cards_loaded = Number(snapshot.cards_loaded ?? cards.filter((card) => ["loaded", "stale"].includes(String(card.status || "").toLowerCase())).length);
        snapshot.cards_failed = Number(snapshot.cards_failed ?? cards.filter((card) => !["loaded", "stale"].includes(String(card.status || "").toLowerCase())).length);
        const statuses = {};
        cards.forEach((card) => {
          statuses[card.key] = {
            label: card.title,
            url: card.source_endpoint,
            httpStatus: 200,
            loaded: ["loaded", "stale"].includes(String(card.status || "").toLowerCase()),
            status: card.status || "unavailable",
            error: card.error_reason || "",
          };
        });
        if (!cancelled) {
          setAdvancedSnapshot(snapshot);
          setAdvancedEndpointStatus(statuses);
          setAdvancedInstitutional({});
          setAdvancedSnapshotMessage(
            `${snapshot.cards_loaded || 0}/${snapshot.total_cards || cards.length} advanced cards loaded`
          );
          setInstitutionalTrend((prev) => {
            const cardByKey = Object.fromEntries(cards.map((card) => [card.key, card]));
            const fastSnapshot = data.learningSnapshotFast || {};
            const learning = data.learningInsights || {};
            const numeric = (value) => {
              const match = String(value || "").match(/-?\d+(\.\d+)?/);
              return match ? Number(match[0]) : 0;
            };
            const point = {
              ts: new Date().toLocaleTimeString(),
              entryQuality: numeric(cardByKey.entryQuality?.primary_value),
              consensus: numeric(cardByKey.consensus?.primary_value),
              releasedWinRate: safeNumber(fastSnapshot?.current_engine_released_wr, numeric(cardByKey.tradeLifecycle?.primary_value)),
              buyListPurity: safeNumber(fastSnapshot?.buy_list_purity, learning?.buy_list_purity_score),
            };
            return [...prev, point].slice(-24);
          });
        }
      } catch (err) {
        if (!cancelled) {
          const reason = err?.name === "AbortError" ? "Snapshot request timed out after 8 seconds" : (err instanceof Error ? err.message : String(err));
          const snapshot = fallbackSnapshot(reason);
          snapshot.cards = normalizeAdvancedSnapshotCards(snapshot.cards, reason);
          setAdvancedSnapshot(snapshot);
          setAdvancedEndpointStatus(Object.fromEntries(snapshot.cards.map((card) => [card.key, {
            label: card.title,
            url: card.source_endpoint,
            httpStatus: null,
            loaded: false,
            status: card.status,
            error: card.error_reason,
          }])));
          setAdvancedSnapshotMessage("Advanced metrics unavailable or still computing");
        }
      } finally {
        if (timeoutId) window.clearTimeout(timeoutId);
        if (!cancelled) {
          setAdvancedLoadedOnce(true);
          setAdvancedLoading(false);
        }
      }
    };

    loadAdvancedInstitutional();
    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
      try { controller.abort(); } catch (_e) {}
    };
  }, [showAdvancedSections, advancedLoadedOnce, resolvedApiBase, data.learningSnapshotFast, data.learningInsights]);

  useEffect(() => {
    if (!showAdvancedSections || adaptiveQuantStatus) return undefined;
    let mounted = true;
    const loadAdaptiveQuant = async () => {
      setAdaptiveQuantMessage("Loading shadow optimization summary...");
      try {
        const result = await fetchJsonWithFallback("/api/adaptive_quant_optimization_status_v1", {
          preferredBase: resolvedApiBase || API_BASE,
          fallbackValue: {
            enabled: false,
            mode: "shadow_only",
            api_calls_used: 0,
            promotion_allowed: false,
            live_trading_changed: false,
            production_weights_changed: false,
            paper_trading_changed: false,
            error: "adaptive quant summary unavailable",
          },
          timeoutMs: 8000,
        });
        if (!mounted) return;
        const parsed = result?.parsed && typeof result.parsed === "object" ? result.parsed : {};
        setAdaptiveQuantStatus(parsed);
        setAdaptiveQuantMessage(parsed.enabled === false ? "Shadow optimization unavailable" : "Shadow optimization loaded");
      } catch (err) {
        if (!mounted) return;
        setAdaptiveQuantStatus({
          enabled: false,
          mode: "shadow_only",
          api_calls_used: 0,
          promotion_allowed: false,
          live_trading_changed: false,
          production_weights_changed: false,
          paper_trading_changed: false,
          error: err instanceof Error ? err.message : String(err),
        });
        setAdaptiveQuantMessage("Shadow optimization unavailable");
      }
    };
    loadAdaptiveQuant();
    return () => {
      mounted = false;
    };
  }, [showAdvancedSections, adaptiveQuantStatus, resolvedApiBase]);

  useEffect(() => {
    if (!showAdvancedSections || multiHorizonStatus) return undefined;
    let mounted = true;
    const loadMultiHorizon = async () => {
      setMultiHorizonMessage("Loading multi-horizon shadow summary...");
      try {
        const result = await fetchJsonWithFallback("/api/multi_horizon_intraday_meta_suite_status_v1", {
          preferredBase: resolvedApiBase || API_BASE,
          fallbackValue: {
            enabled: false,
            mode: "shadow_only",
            api_calls_used: 0,
            promotion_allowed: false,
            live_trading_changed: false,
            production_rankings_changed: false,
            production_weights_changed: false,
            paper_trading_changed: false,
            error: "multi-horizon summary unavailable",
          },
          timeoutMs: 8000,
        });
        if (!mounted) return;
        const parsed = result?.parsed && typeof result.parsed === "object" ? result.parsed : {};
        setMultiHorizonStatus(parsed);
        setMultiHorizonMessage(parsed.enabled === false ? "Multi-horizon summary unavailable" : "Multi-horizon shadow summary loaded");
      } catch (err) {
        if (!mounted) return;
        setMultiHorizonStatus({
          enabled: false,
          mode: "shadow_only",
          api_calls_used: 0,
          promotion_allowed: false,
          live_trading_changed: false,
          production_rankings_changed: false,
          production_weights_changed: false,
          paper_trading_changed: false,
          error: err instanceof Error ? err.message : String(err),
        });
        setMultiHorizonMessage("Multi-horizon summary unavailable");
      }
    };
    loadMultiHorizon();
    return () => {
      mounted = false;
    };
  }, [showAdvancedSections, multiHorizonStatus, resolvedApiBase]);

  useEffect(() => {
    if (!showAdvancedSections || learningExecutionStatus) return undefined;
    let mounted = true;
    const loadLearningExecution = async () => {
      setLearningExecutionMessage("Loading learning execution summary...");
      try {
        const result = await fetchJsonWithFallback("/api/learning_execution_suite_status_v1", {
          preferredBase: resolvedApiBase || API_BASE,
          fallbackValue: {
            enabled: false,
            mode: "shadow_first",
            api_calls_used: 0,
            promotion_allowed: false,
            live_trading_changed: false,
            broker_execution_changed: false,
            production_rankings_changed: false,
            production_weights_changed: false,
            paper_trading_changed: false,
            error: "learning execution summary unavailable",
          },
          timeoutMs: 8000,
        });
        if (!mounted) return;
        const parsed = result?.parsed && typeof result.parsed === "object" ? result.parsed : {};
        setLearningExecutionStatus(parsed);
        setLearningExecutionMessage(parsed.enabled === false ? "Learning execution summary unavailable" : "Learning execution summary loaded");
      } catch (err) {
        if (!mounted) return;
        setLearningExecutionStatus({
          enabled: false,
          mode: "shadow_first",
          api_calls_used: 0,
          promotion_allowed: false,
          live_trading_changed: false,
          broker_execution_changed: false,
          production_rankings_changed: false,
          production_weights_changed: false,
          paper_trading_changed: false,
          error: err instanceof Error ? err.message : String(err),
        });
        setLearningExecutionMessage("Learning execution summary unavailable");
      }
    };
    loadLearningExecution();
    return () => {
      mounted = false;
    };
  }, [showAdvancedSections, learningExecutionStatus, resolvedApiBase]);

  useEffect(() => {
    if (!showAdvancedSections || contextProfitabilityStatus) return undefined;
    let mounted = true;
    const loadContextProfitability = async () => {
      setContextProfitabilityMessage("Loading context profitability summary...");
      try {
        const result = await fetchJsonWithFallback("/api/context_search_profitability_status_v1", {
          preferredBase: resolvedApiBase || API_BASE,
          fallbackValue: {
            enabled: false,
            mode: "shadow_only",
            api_calls_used: 0,
            candidates_evaluated: 0,
            average_context_score: 0,
            strongest_context_tailwind: "unavailable",
            strongest_context_penalty: "unavailable",
            error: "context profitability summary unavailable",
          },
          timeoutMs: 8000,
        });
        if (!mounted) return;
        const parsed = result?.parsed && typeof result.parsed === "object" ? result.parsed : {};
        setContextProfitabilityStatus(parsed);
        setContextProfitabilityMessage(parsed.enabled === false ? "Context profitability unavailable" : "Context profitability loaded");
      } catch (err) {
        if (!mounted) return;
        setContextProfitabilityStatus({
          enabled: false,
          mode: "shadow_only",
          api_calls_used: 0,
          candidates_evaluated: 0,
          average_context_score: 0,
          strongest_context_tailwind: "unavailable",
          strongest_context_penalty: "unavailable",
          error: err instanceof Error ? err.message : String(err),
        });
        setContextProfitabilityMessage("Context profitability unavailable");
      }
    };
    loadContextProfitability();
    return () => {
      mounted = false;
    };
  }, [showAdvancedSections, contextProfitabilityStatus, resolvedApiBase]);

  useEffect(() => {
    if (!showAdvancedSections || portfolioRiskIntelStatus) return undefined;
    let mounted = true;
    const loadPortfolioRiskIntel = async () => {
      setPortfolioRiskIntelMessage("Loading portfolio risk intelligence...");
      try {
        const result = await fetchJsonWithFallback("/api/portfolio_risk_intelligence_status_v1", {
          preferredBase: resolvedApiBase || API_BASE,
          fallbackValue: {
            enabled: false,
            mode: "shadow_only",
            api_calls_used: 0,
            average_recommended_position_size_pct: 0,
            average_portfolio_risk_score: 0,
            average_capital_allocation_score: 0,
            highest_correlation_risk: 0,
            highest_concentration_risk: 0,
            error: "portfolio risk intelligence unavailable",
          },
          timeoutMs: 8000,
        });
        if (!mounted) return;
        const parsed = result?.parsed && typeof result.parsed === "object" ? result.parsed : {};
        setPortfolioRiskIntelStatus(parsed);
        setPortfolioRiskIntelMessage(parsed.enabled === false ? "Portfolio risk intelligence unavailable" : "Portfolio risk intelligence loaded");
      } catch (err) {
        if (!mounted) return;
        setPortfolioRiskIntelStatus({
          enabled: false,
          mode: "shadow_only",
          api_calls_used: 0,
          average_recommended_position_size_pct: 0,
          average_portfolio_risk_score: 0,
          average_capital_allocation_score: 0,
          highest_correlation_risk: 0,
          highest_concentration_risk: 0,
          error: err instanceof Error ? err.message : String(err),
        });
        setPortfolioRiskIntelMessage("Portfolio risk intelligence unavailable");
      }
    };
    loadPortfolioRiskIntel();
    return () => {
      mounted = false;
    };
  }, [showAdvancedSections, portfolioRiskIntelStatus, resolvedApiBase]);

  const paper = data.paper || {};
  const paperStatus = data.paperStatus || {};
  const workerStatus = {
    ...(paperStatus?.worker || {}),
    ...(data.workerStatus || {}),
  };
  const learningInsights = data.learningInsights || {};
  const learningSnapshotFast = data.learningSnapshotFast || {};
  const model = data.model || {};
  const topBuys = data.topBuys || {};
  const systemStatus = data.systemStatus || {};
  const entryQualityV2 = advancedInstitutional.entryQuality || {};
  const multiBrainConsensus = advancedInstitutional.consensus || {};
  const learningDataQualityV2 = advancedInstitutional.learningDataQuality || {};
  const tradeLifecycleIntel = advancedInstitutional.tradeLifecycle || {};
  const policyCompareV2 = advancedInstitutional.policyCompare || {};
  const selfCorrectionV2 = advancedInstitutional.selfCorrection || {};
  const fmpUtilization = advancedInstitutional.fmpUtilization || {};
  const jsonlMaintenance = advancedInstitutional.jsonlMaintenance || {};
  const replayCounterfactual = advancedInstitutional.replayCounterfactual || {};
  const marketDataOrchestration = advancedInstitutional.marketDataOrchestration || {};

  const paperOutcome = paper?.paper_outcome_summary?.combined || {};
  const paperCohort = paper?.paper_cohort_trends || {};
  const liTotals = learningInsights?.totals || {};
  const buyQualityPolicy = learningInsights?.buy_quality_policy || {};
  const bestWorst = learningInsights?.best_worst || {};
  const exitPolicyHints = learningInsights?.exit_policy_hints || {};
  const regimePolicyHints = learningInsights?.regime_policy_hints || {};
  const personaPolicyHints = learningInsights?.persona_policy_hints || {};
  const entryQualityHints = learningInsights?.entry_quality_hints || {};
  const entryTimingHints = learningInsights?.entry_timing_hints || {};
  const contextualEntryTimingHints = learningInsights?.contextual_entry_timing_hints || {};
  const convictionFramework = learningInsights?.conviction_framework || {};
  const lifecycleStateHints = learningInsights?.lifecycle_state_hints || {};
  const followThroughLearning = learningInsights?.follow_through_learning || {};
  const entryExecutionPolicy = learningInsights?.entry_execution_policy || {};
  const deteriorationInvalidationHints = learningInsights?.deterioration_invalidation_hints || {};
  const followThroughFailureHints = learningInsights?.follow_through_failure_hints || {};
  const patientFastReviewPolicy = learningInsights?.patient_fast_review_policy || {};
  const convictionActionMapping = learningInsights?.conviction_action_mapping || {};
  const advancedLifecycle = learningInsights?.advanced_lifecycle_intelligence || {};
  const contextualExecutionRefinement = learningInsights?.contextual_execution_refinement || {};
  const tradeManagementRealism = learningInsights?.trade_management_realism || {};
  const runtimeHardening = learningInsights?.runtime_hardening || {};
  const workerWatchdogReliability = learningInsights?.worker_watchdog_reliability || {};
  const workerContinuity = learningInsights?.worker_continuity || workerWatchdogReliability?.worker_continuity || {};
  const performanceOptimizationSuite = learningInsights?.performance_optimization_suite || {};
  const tradeQualitySelectivitySuite = learningInsights?.trade_quality_selectivity_suite || {};
  const portfolioIntelligenceSuite = learningInsights?.portfolio_intelligence_suite || {};
  const capitalAllocationIntelligence = learningInsights?.capital_allocation_intelligence || {};
  const overlapRiskControls = learningInsights?.overlap_risk_controls || {};
  const executionReadinessControls = learningInsights?.execution_readiness_controls || {};
  const liveReadinessSuite = learningInsights?.live_readiness_suite || {};
  const paperToLiveGuardrails = learningInsights?.paper_to_live_guardrails || {};
  const actionTierControls = learningInsights?.action_tier_controls || {};
  const degradedHealthyMode = learningInsights?.degraded_healthy_mode || {};
  const executionHandoffControls = learningInsights?.execution_handoff_controls || {};
  const operatorGoNoGo = learningInsights?.operator_go_no_go || {};
  const marketCatalystIntelligence = learningInsights?.market_catalyst_intelligence || {};
  const macroRegimeAwareness = learningInsights?.macro_regime_awareness || {};
  const sectorThemeRotationIntelligence = learningInsights?.sector_theme_rotation_intelligence || {};
  const externalContextClassification = learningInsights?.external_context_classification || {};
  const marketConditionAdaptation = learningInsights?.market_condition_adaptation || {};
  const forecastingQualityRefinement = learningInsights?.forecasting_quality_refinement || {};
  const confidenceCalibration = learningInsights?.confidence_calibration || {};
  const contradictionSelfCheck = learningInsights?.contradiction_self_check || {};
  const autonomousExplanationRefinement = learningInsights?.autonomous_explanation_refinement || {};
  const crossLayerDecisionCoherence = learningInsights?.cross_layer_decision_coherence || {};
  const providerBlendingReliability = learningInsights?.provider_blending_reliability || {};
  const quoteHealthStaleRecovery = learningInsights?.quote_health_stale_recovery || {};
  const cryptoCoverageReliability = learningInsights?.crypto_coverage_reliability || {};
  const quoteQualityAssurance = learningInsights?.quote_quality_assurance || {};
  const quoteActionabilityTiers = learningInsights?.quote_actionability_tiers || {};
  const symbolDataQualityProfiles = learningInsights?.symbol_data_quality_profiles || {};
  const providerHealthIntelligence = learningInsights?.provider_health_intelligence || {};
  const dataEnvironmentPosture = learningInsights?.data_environment_posture || {};
  const stockDataQualitySuite = learningInsights?.stock_data_quality_suite || {};
  const cryptoDataQualitySuite = learningInsights?.crypto_data_quality_suite || {};
  const rollingProviderDataQualityMemory = learningInsights?.rolling_provider_data_quality_memory || {};
  const metadataDataQualityEnrichment = learningInsights?.metadata_data_quality_enrichment || {};
  const learningSystemStatus = learningInsights?.learning_system_status || {};
  const evidenceReadinessSummary = learningInsights?.evidence_readiness_summary || {};
  const runtimePerformanceSummary = learningInsights?.runtime_performance_summary || {};
  const actionabilityQualitySuite = learningInsights?.actionability_quality_suite || {};
  const entryExecutionQuality = learningInsights?.entry_execution_quality || {};
  const followthroughQuality = learningInsights?.followthrough_quality || {};
  const releasedHeroQualitySuite = learningInsights?.released_hero_quality_suite || {};
  const sellSignalQuality = learningInsights?.sell_signal_quality || {};
  const positionQualitySummary = learningInsights?.position_quality_summary || {};
  const topActionViewsHealth = learningInsights?.top_action_views_health || {};
  const releaseQualityGuardrailStatus = learningInsights?.release_quality_guardrail_status || {};
  const postChangeCurrentEngineQualityGate = learningInsights?.post_change_current_engine_quality_gate || {};
  const astraOperatingStandard = learningInsights?.astra_operating_standard || {};
  const strongBuyActionabilityRecalibration = learningInsights?.strong_buy_actionability_recalibration || {};
  const compactConfidenceTruthfulnessEngine = learningInsights?.confidence_truthfulness_engine || learningInsights?.confidence_calibration || {};
  const currentEngineWinRate = safeNumber(learningInsights?.released_hero_win_rate);
  const currentEngineExpectancy = safeNumber(learningInsights?.released_hero_expectancy);
  const postChangeReleasedWinRate = safeNumber(learningInsights?.post_change_released_win_rate);
  const postChangeReleasedExpectancy = safeNumber(learningInsights?.post_change_released_expectancy);
  const compactCards = [
    { label: "Wins / Losses", value: `${safeNumber(paperOutcome?.wins, paper?.wins).toFixed(0)} / ${safeNumber(paperOutcome?.losses, paper?.losses).toFixed(0)}` },
    { label: "Long-History Win Rate", value: fmtPct(paperOutcome?.win_rate) },
    { label: "Recent Win Rate (Legacy Mix)", value: fmtPct((paperCohort?.recent || {}).win_rate) },
    { label: "Buy Ranking Quality", value: `${safeNumber(learningInsights?.buy_ranking_quality_score ?? learningInsights?.buy_list_purity_score).toFixed(1)}` },
    { label: "Sell Quality", value: `${safeNumber(learningInsights?.current_engine_exit_timing_score ?? learningInsights?.sell_quality_enforcement_engine?.sell_quality_enforcement_score).toFixed(1)}` },
    { label: "Released Hero Quality", value: `${currentEngineWinRate.toFixed(2)}% / ${currentEngineExpectancy.toFixed(4)}%` },
    { label: "Confidence Truthfulness", value: `${safeNumber(compactConfidenceTruthfulnessEngine?.confidence_truthfulness_score).toFixed(1)}` },
    { label: "Evidence Status", value: String(learningSystemStatus?.status || (learningInsights?.post_change_evidence_ready ? "ready" : "sample-limited")).replaceAll("_", " ") },
  ];

  const failureVisibilityRecovery = learningInsights?.failure_visibility_recovery || {};
  const personaStyleAdaptation = learningInsights?.persona_style_adaptation || {};
  const seasonalityRefinement = learningInsights?.seasonality_refinement || {};
  const catalystNewsIntelligence = learningInsights?.catalyst_news_intelligence || {};
  const contextConfidenceEvidence = learningInsights?.context_confidence_evidence || {};
  const exitTimingPatterns = learningInsights?.exit_timing_patterns || {};
  const learningQuality = learningInsights?.learning_quality || {};
  const replayLearningQuality = learningInsights?.replay_learning_quality || {};
  const positionSizingPolicy = learningInsights?.position_sizing_policy || {};
  const policyAdaptation = learningInsights?.policy_adaptation || {};
  const contextualPolicyHints = learningInsights?.contextual_policy_hints || {};
  const contextualLearning = learningInsights?.contextual_learning || {};
  const contextualExitHints = learningInsights?.contextual_exit_hints || {};
  const contextualHardSoftPolicy = learningInsights?.contextual_hard_soft_policy || {};
  const contextualHoldTimeHints = learningInsights?.contextual_hold_time_hints || {};
  const holdTimePolicyHints = learningInsights?.hold_time_policy_hints || {};
  const contextualTradeMgmt = learningInsights?.contextual_trade_management_patterns || {};
  const gradeScaleLearning = learningInsights?.grade_scale_learning_summary || {};
  const positiveActionLearning = learningInsights?.positive_action_learning || {};
  const boundaryLearning = learningInsights?.boundary_learning || {};
  const negativeSuppressionLearning = learningInsights?.negative_suppression_learning || {};
  const abstainLearning = learningInsights?.abstain_learning || {};
  const rejectOptionControls = learningInsights?.reject_option_controls || {};
  const noTradeZoneDetection = learningInsights?.no_trade_zone_detection || {};
  const watchlistOnlyZoneDetection = learningInsights?.watchlist_only_zone_detection || {};
  const confirmationRequiredZoneDetection = learningInsights?.confirmation_required_zone_detection || {};
  const liveBlockedZoneDetection = learningInsights?.live_blocked_zone_detection || {};
  const expectancyFrictionRealism = learningInsights?.expectancy_friction_realism || {};
  const hardSoftRefinement = learningInsights?.hard_soft_refinement || {};
  const cohortKillswitchCooldown = learningInsights?.cohort_killswitch_cooldown || {};
  const counterfactualLearning = learningInsights?.counterfactual_learning || {};
  const missedOpportunityLearning = learningInsights?.missed_opportunity_learning || {};
  const executionErrorLearning = learningInsights?.execution_error_learning || {};
  const postTradeDiagnostic = learningInsights?.post_trade_diagnostic_intelligence || {};
  const decisionFeedback = paper?.decision_feedback || {};
  const tradePathQuality = paper?.trade_path_quality || {};
  const closedPathQuality = tradePathQuality?.closed_journal || {};
  const openPathQuality = tradePathQuality?.open_positions || {};

  const segmentRows = useMemo(() => {
    const segments = paper?.decision_feedback_segments || {};
    const rows = [];
    const addRows = (segmentType, map) => {
      const source = map || {};
      Object.keys(source).forEach((k) => {
        const row = source[k] || {};
        const sample = safeNumber(row.sample_size || row.trade_count);
        if (sample < 25 || ["", "unknown", "none"].includes(String(k).toLowerCase())) return;
        rows.push({
          segmentType: segmentType.replace("by_", ""),
          segmentKey: k,
          sample,
          good: safeNumber(row.good_entries),
          bad: safeNumber(row.bad_entries),
          early: safeNumber(row.early_exits),
          late: safeNumber(row.late_exits),
          missed: safeNumber(row.missed_profit_cases),
        });
      });
    };
    addRows("by_regime", segments.by_regime);
    addRows("by_persona", segments.by_persona);
    addRows("by_cap_bucket", segments.by_cap_bucket);
    addRows("by_setup_type", segments.by_setup_type);
    return rows.sort((a, b) => b.sample - a.sample).slice(0, 8);
  }, [paper]);

  const learningConfidence = useMemo(() => {
    const validClosed = safeNumber((paper?.combined || {}).valid_closed, paper?.closed_trades_count);
    const rates = [
      safeNumber(closedPathQuality?.mfe_population_rate_percent),
      safeNumber(closedPathQuality?.mae_population_rate_percent),
      safeNumber(closedPathQuality?.peak_population_rate_percent),
      safeNumber(closedPathQuality?.drawdown_population_rate_percent),
      safeNumber(closedPathQuality?.time_to_peak_population_rate_percent),
      safeNumber(closedPathQuality?.time_to_exit_population_rate_percent),
    ];
    const completeness = rates.reduce((acc, v) => acc + v, 0) / Math.max(1, rates.length);
    if (validClosed >= 200 && completeness >= 55) return "stronger";
    if (validClosed >= 75 && completeness >= 30) return "moderate";
    return "low";
  }, [paper, closedPathQuality]);

  const overallTrend = String(paperCohort?.overall_trend || "mixed");
  const recentVsPriorReturnDelta = safeNumber(paperCohort?.delta?.winsorized_avg_return);
  const recentVsPriorWinDelta = safeNumber(paperCohort?.delta?.win_rate);
  const hardBuyPerf = liTotals?.hard_buy || paperOutcome?.hard_buy_performance || {};
  const softBuyPerf = liTotals?.soft_buy || paperOutcome?.soft_buy_performance || {};
  const hardSoftDelta = safeNumber(liTotals?.hard_vs_soft_delta_avg_return, paperOutcome?.hard_vs_soft_delta_avg_return);
  const hardSoftWinsorizedDelta = safeNumber(liTotals?.hard_vs_soft_delta_winsorized_avg_return, hardSoftDelta);
  const sourceContribution = liTotals?.source_contribution || {};
  const policyAction = String(buyQualityPolicy?.action || "keep");
  const policyReason = String(buyQualityPolicy?.reason || "");

  const fullValidClosedCount = safeNumber((paper?.combined || {}).valid_closed, liTotals?.valid_trades);
  const recentSampleClosedCount = safeNumber(paperOutcome?.trade_count, (closedPathQuality?.sample_size || 0));
  const inferredHardSoft = (() => {
    const byTier = (learningInsights?.segments || {}).by_buy_quality_tier || {};
    let hard = 0;
    let soft = 0;
    Object.entries(byTier || {}).forEach(([k, v]) => {
      const key = String(k || "").toLowerCase();
      const sample = safeNumber((v || {}).sample_size, (v || {}).trade_count);
      if (key.includes("hard") || key.includes("qualified")) hard += sample;
      if (key.includes("soft")) soft += sample;
    });
    return { hard, soft };
  })();
  const hardBuyCount = firstFinite(
    liTotals?.hard_buy?.trade_count,
    paperOutcome?.hard_buy_performance?.trade_count,
    decisionFeedback?.hard_buy_trade_count,
    inferredHardSoft.hard
  );
  const softBuyCount = firstFinite(
    liTotals?.soft_buy?.trade_count,
    paperOutcome?.soft_buy_performance?.trade_count,
    decisionFeedback?.soft_buy_trade_count,
    inferredHardSoft.soft
  );
  const replayShareFromPerf = (() => {
    const replay = safeNumber((paper?.replay_paper || {}).valid_closed);
    const combined = safeNumber((paper?.combined || {}).valid_closed);
    if (combined <= 0) return 0;
    return (replay / combined) * 100.0;
  })();
  const replaySharePercent = (() => {
    const liShare = safeNumber(sourceContribution?.replay_paper_share_percent, -1);
    return liShare >= 0 ? liShare : replayShareFromPerf;
  })();
  const replayEnabled = firstNonEmpty(
    workerStatus?.replay_training_enabled,
    paperStatus?.worker?.replay_training_enabled,
    safeNumber((paper?.decision_feedback_source_breakdown || {}).replay_weight_applied, 0) > 0 ? true : null
  );
  const replayEnabledLabel = replayEnabled === undefined || replayEnabled === null ? "unknown" : String(Boolean(replayEnabled));
  const workerRunningRaw = firstNonEmpty(workerStatus?.running_effective, workerStatus?.running, null);
  const workerRunning = workerRunningRaw === null
    ? Boolean(firstNonEmpty(paperStatus?.last_cycle_utc, paperStatus?.worker?.last_cycle_utc, false))
    : Boolean(workerRunningRaw);
  const lastReplayRunUtc = firstNonEmpty(
    workerStatus?.last_replay_run_utc,
    paperStatus?.worker?.last_replay_run_utc,
    (paper?.paper_replay_cohort_trends || {}).last_run_utc
  );
  const lastReplayTrades = firstFiniteOrNull(
    workerStatus?.last_replay_trades_generated,
    paperStatus?.worker?.last_replay_trades_generated,
    ((paper?.paper_replay_cohort_trends || {}).recent || {}).trade_count
  );
  const lastReplayValid = firstFiniteOrNull(
    workerStatus?.last_replay_valid_trades,
    paperStatus?.worker?.last_replay_valid_trades
  );
  const lastLearningRefreshUtc = firstNonEmpty(
    workerStatus?.last_learning_refresh_utc,
    paperStatus?.worker?.last_learning_refresh_utc,
    learningInsights?.last_updated_utc,
    learningInsights?.generated_at,
    paper?.last_updated_utc
  );
  const derivedQualityScore = (() => {
    const fullValid = Math.max(1, safeNumber((paper?.combined || {}).valid_closed, 0));
    const labeled = safeNumber(liTotals?.valid_trades, 0);
    const labelCoveragePct = clampValue((labeled / fullValid) * 100, 0, 100);
    const pathRates = [
      safeNumber(closedPathQuality?.mfe_population_rate_percent),
      safeNumber(closedPathQuality?.mae_population_rate_percent),
      safeNumber(closedPathQuality?.peak_population_rate_percent),
      safeNumber(closedPathQuality?.drawdown_population_rate_percent),
      safeNumber(closedPathQuality?.time_to_peak_population_rate_percent),
      safeNumber(closedPathQuality?.time_to_exit_population_rate_percent),
    ];
    const pathCoveragePct = pathRates.reduce((acc, v) => acc + v, 0) / Math.max(1, pathRates.length);
    if (labeled <= 0) return 0;
    return (labelCoveragePct * 0.7) + (pathCoveragePct * 0.3);
  })();
  const qualityScore = firstFinite(
    learningQuality?.quality_score,
    (learningInsights?.learning_quality || {}).quality_score,
    derivedQualityScore
  );
  const tradeQualityEvidenceUsable = Boolean(tradeQualitySelectivitySuite?.expectancy_evidence_usable);
  const tradeQualityEvidenceLabel = String(
    tradeQualitySelectivitySuite?.expectancy_evidence_label || (tradeQualityEvidenceUsable ? "usable" : "insufficient_evidence")
  );
  const tradeQualitySelectivityScore = firstFiniteOrNull(tradeQualitySelectivitySuite?.expectancy_score);
  const tradeQualityProfitFactor = firstFiniteOrNull(tradeQualitySelectivitySuite?.profit_factor);
  const tradeQualityMedianReturn = firstFiniteOrNull(tradeQualitySelectivitySuite?.median_return);
  const validLabeledCount = firstFinite(
    learningQuality?.valid_labeled_count,
    liTotals?.valid_trades,
    paper?.closed_trades_count
  );
  const setupTaxonomyTrackedCount = Math.max(
    Object.keys(((learningInsights?.segments || {}).by_setup_type) || {}).length,
    Object.keys(learningInsights?.setup_policy_hints || {}).length,
    Object.keys(((paper?.decision_feedback_segments || {}).by_setup_type) || {}).length
  );
  const contextualAdjustmentCount = firstFinite(
    policyAdaptation?.contextual_adjustment_count,
    safeNumber(tradeQualitySelectivitySuite?.weak_cohort_counts?.contextual_soft),
    Object.keys(contextualPolicyHints?.season_setup || {}).length
      + Object.keys(contextualPolicyHints?.earnings_season_setup || {}).length
      + Object.keys(contextualPolicyHints?.risk_season_persona || {}).length
  );
  const regimePolicyKeys = Object.keys(regimePolicyHints || {});
  const personaPolicyKeys = Object.keys(personaPolicyHints || {});
  const regimePolicyLabel = regimePolicyKeys.length > 0
    ? regimePolicyKeys.slice(0, 4).join(", ")
    : (safeNumber(policyAdaptation?.regime_adjustment_count) > 0
      ? `${safeNumber(policyAdaptation?.regime_adjustment_count)} learned adjustments`
      : (safeNumber(tradeQualitySelectivitySuite?.weak_cohort_counts?.regimes) > 0
        ? `${safeNumber(tradeQualitySelectivitySuite?.weak_cohort_counts?.regimes)} weak cohorts tracked`
        : "none"));
  const personaPolicyLabel = personaPolicyKeys.length > 0
    ? personaPolicyKeys.slice(0, 4).join(", ")
    : (safeNumber(policyAdaptation?.persona_adjustment_count) > 0
      ? `${safeNumber(policyAdaptation?.persona_adjustment_count)} learned adjustments`
      : (safeNumber(tradeQualitySelectivitySuite?.weak_cohort_counts?.personas) > 0
        ? `${safeNumber(tradeQualitySelectivitySuite?.weak_cohort_counts?.personas)} weak cohorts tracked`
        : "none"));
  const contextualExitSetupCount = Math.max(
    Object.keys(contextualExitHints?.setup_regime || {}).length,
    (contextualTradeMgmt?.best_quicker_exit_contexts || []).length
  );
  const contextualExitPersonaCount = Math.max(
    Object.keys(contextualExitHints?.persona_regime || {}).length,
    0
  );
  const contextualHoldSetupCount = Math.max(
    Object.keys(contextualHoldTimeHints?.setup_regime || {}).length,
    (contextualTradeMgmt?.best_longer_hold_contexts || []).length
  );
  const contextualHoldPersonaCount = Math.max(
    Object.keys(contextualHoldTimeHints?.persona_regime || {}).length,
    0
  );
  const contextualSizingCount = Math.max(
    safeNumber(positionSizingPolicy?.contextual_evidence_count),
    (contextualTradeMgmt?.strongest_sizing_contexts || []).length
  );
  const replayContributionPercent = firstFinite(
    replayLearningQuality?.share_of_valid_trades_percent,
    replaySharePercent
  );
  const convictionActionTierCount = Object.keys(convictionActionMapping?.tiers || {}).length;
  const convictionTierPerf = convictionFramework?.tier_performance || {};
  const lifecycleStates = lifecycleStateHints?.states || {};
  const followThroughPatterns = followThroughLearning?.patterns || {};
  const entryTimingContextsTracked =
    Object.keys(contextualEntryTimingHints?.setup_regime || {}).length
    + Object.keys(contextualEntryTimingHints?.persona_regime || {}).length
    + Object.keys(contextualEntryTimingHints?.setup_cap_bucket || {}).length
    + Object.keys(contextualEntryTimingHints?.season_setup || {}).length;
  const truthPanel = learningTruth && Object.keys(learningTruth || {}).length > 0
    ? learningTruth
    : (learningInsights?.learning_truth_status_v1 || learningSnapshotFast?.truth || {});
  const truthSourceNames = Array.isArray(truthPanel?.source_names) ? truthPanel.source_names : [];
  const learningPayloadSource = String(
    firstNonEmpty(
      learningInsights?.learning_payload_source,
      learningSnapshotFast?.learning_payload_source,
      learningSnapshotFast?.source,
      truthSourceNames.length > 0 ? truthSourceNames.join(", ") : "",
      "unknown"
    )
  );
  const learningPayloadStale = Boolean(learningInsights?.learning_payload_stale);
  const learningPayloadFalseEmptyPrevented = Boolean(
    learningInsights?.learning_payload_false_empty_prevented || learningInsights?.ui_false_empty_guard_active
  );
  const learningPayloadDegradedReason = String(
    firstNonEmpty(learningInsights?.learning_payload_degraded_reason, learningInsights?.ui_false_empty_guard_reason, "")
  );
  const cohortSamples = learningInsights?.cohort_sample_sizes || {};
  const cohortSampleTotal = safeNumber(cohortSamples?.released) + safeNumber(cohortSamples?.paper_ready) + safeNumber(cohortSamples?.blocked_watchlist);
  const learningEvidenceAvailable = Boolean(truthPanel?.active_learning_available)
    || learningPayloadHasEvidence(learningInsights)
    || fullValidClosedCount > 0;
  const snapshotInsufficientEvidence = !learningEvidenceAvailable || (
    cohortSampleTotal <= 0
    && !Boolean(evidenceReadinessSummary?.evidence_ready)
    && !Boolean(evidenceReadinessSummary?.confidence_ready)
    && !Boolean(truthPanel?.active_learning_available)
  );

  const keyTakeaways = useMemo(() => {
    const list = [];
    const good = safeNumber(decisionFeedback?.good_entries);
    const bad = safeNumber(decisionFeedback?.bad_entries);
    const early = safeNumber(decisionFeedback?.early_exits);
    const late = safeNumber(decisionFeedback?.late_exits);
    const missed = safeNumber(decisionFeedback?.missed_profit_cases);

    list.push(
      good >= bad
        ? "Entry quality is stable: good entries are at or above bad entries."
        : "Entry quality is under pressure: bad entries are exceeding good entries."
    );
    if (recentVsPriorWinDelta > 0) {
      list.push(`Recent cohort win rate improved by ${recentVsPriorWinDelta.toFixed(2)} points.`);
    } else if (recentVsPriorWinDelta < 0) {
      list.push(`Recent cohort win rate softened by ${Math.abs(recentVsPriorWinDelta).toFixed(2)} points.`);
    } else {
      list.push("Recent cohort win rate is flat versus prior cohort.");
    }
    list.push(
      missed > 0
        ? `Missed-profit pressure remains (${missed} cases); exit timing still has upside.`
        : "Missed-profit pressure is low; exit discipline is improving."
    );
    if (safeNumber(entryTimingHints?.entry_timing_score) > 0) {
      list.push(
        `Entry timing score is ${safeNumber(entryTimingHints?.entry_timing_score).toFixed(1)} with mode ${String(
          entryTimingHints?.recommended_entry_mode || "confirmation_needed"
        ).replaceAll("_", " ")}.`
      );
    }
    if (safeNumber((convictionTierPerf?.elite || {}).trade_count) > 0) {
      list.push(
        `Conviction ladder active: elite tier WR ${fmtPct((convictionTierPerf?.elite || {}).win_rate)} vs acceptable ${fmtPct(
          (convictionTierPerf?.acceptable || {}).win_rate
        )}.`
      );
    }
    if (safeNumber(deteriorationInvalidationHints?.invalidation_score) > 0) {
      list.push(
        `Invalidation score is ${safeNumber(deteriorationInvalidationHints?.invalidation_score).toFixed(1)} (${String(
          deteriorationInvalidationHints?.review_urgency || "normal"
        )} review urgency).`
      );
    }
    if (safeNumber(contextualExecutionRefinement?.execution_refinement_score) > 0) {
      list.push(
        `Execution posture is ${String(contextualExecutionRefinement?.recommended_execution_posture || "balanced")} with refinement score ${safeNumber(
          contextualExecutionRefinement?.execution_refinement_score
        ).toFixed(1)}.`
      );
    }
    if (safeNumber(tradeManagementRealism?.review_escalation_score) > 0) {
      list.push(
        `Trade-management escalation score is ${safeNumber(tradeManagementRealism?.review_escalation_score).toFixed(1)} (${String(
          tradeManagementRealism?.recommended_management_mode || "balanced_review"
        ).replaceAll("_", " ")}).`
      );
    }
    list.push(`Exit timing pressure: early exits ${early}, late exits ${late}.`);
    list.push(`Current baseline: ${fmtPct(paperOutcome?.win_rate)} win rate, median return ${safeNumber(paperOutcome?.median_return).toFixed(4)}%.`);
    if (policyAction && policyAction !== "keep") {
      list.push(`Policy update: soft buys are ${policyAction.replaceAll("_", " ")} (${policyReason || "performance-based"}).`);
    }
    if (safeNumber(learningQuality?.quality_score) > 0) {
      list.push(`Learning data quality score is ${safeNumber(learningQuality?.quality_score).toFixed(1)} (${String(learningQuality?.maturity || "low")}).`);
    }
    if (contextualLearning?.seasonality_available) {
      list.push("Context-aware learning is active: persona/setup behavior is now segmented by regime and seasonal context.");
    }
    if (safeNumber(contextConfidenceEvidence?.overall_confidence_score) > 0) {
      list.push(
        `Context confidence is ${safeNumber(contextConfidenceEvidence?.overall_confidence_score).toFixed(1)} (${String(
          contextConfidenceEvidence?.overall_confidence_label || "insufficient_contextual_evidence"
        ).replaceAll("_", " ")}).`
      );
    }
    if (String(catalystNewsIntelligence?.catalyst_risk_level || "normal") !== "normal") {
      list.push(`Catalyst risk regime is ${String(catalystNewsIntelligence?.catalyst_risk_level || "normal").replaceAll("_", " ")}; execution is being tightened.`);
    }
    if (safeNumber(externalContextClassification?.external_context_score) > 0) {
      list.push(
        `External context is ${String(externalContextClassification?.external_environment_tier || "caution")} (${safeNumber(
          externalContextClassification?.external_context_score
        ).toFixed(1)} score).`
      );
    }
    if (safeNumber(macroRegimeAwareness?.macro_adaptation_score) > 0) {
      list.push(
        `Macro regime is ${String(macroRegimeAwareness?.current_macro_regime || "neutral")} with adaptation score ${safeNumber(
          macroRegimeAwareness?.macro_adaptation_score
        ).toFixed(1)}.`
      );
    }
    if (safeNumber(forecastingQualityRefinement?.forecast_quality_score) > 0) {
      list.push(
        `Forecast quality/stability: ${safeNumber(forecastingQualityRefinement?.forecast_quality_score).toFixed(1)} / ${safeNumber(
          forecastingQualityRefinement?.forecast_stability_score
        ).toFixed(1)} (${String(forecastingQualityRefinement?.forecast_outlook_tier || "unstable")}).`
      );
    }
    if (safeNumber(confidenceCalibration?.confidence_calibration_score) > 0) {
      list.push(
        `Confidence calibration: ${safeNumber(confidenceCalibration?.confidence_calibration_score).toFixed(1)} (${String(
          confidenceCalibration?.confidence_realism_label || "insufficient_evidence"
        ).replaceAll("_", " ")}).`
      );
    }
    if (safeNumber(contradictionSelfCheck?.contradiction_count) > 0) {
      list.push(
        `Self-check contradictions: ${safeNumber(contradictionSelfCheck?.contradiction_count)} (severity ${safeNumber(
          contradictionSelfCheck?.contradiction_severity
        ).toFixed(1)}).`
      );
    }
    if (safeNumber(crossLayerDecisionCoherence?.coherence_score) > 0) {
      list.push(
        `Cross-layer coherence/integrity: ${safeNumber(crossLayerDecisionCoherence?.coherence_score).toFixed(1)} / ${safeNumber(
          crossLayerDecisionCoherence?.decision_integrity_score
        ).toFixed(1)}.`
      );
    }
    if (safeNumber(providerBlendingReliability?.provider_blend_score) > 0) {
      list.push(
        `Provider blend reliability: ${safeNumber(providerBlendingReliability?.provider_blend_score).toFixed(1)} (${String(
          providerBlendingReliability?.fallback_reliability_label || "weak"
        )}).`
      );
    }
    if (safeNumber(quoteHealthStaleRecovery?.quote_freshness_quality_score) > 0) {
      list.push(
        `Quote freshness/stale risk: ${safeNumber(quoteHealthStaleRecovery?.quote_freshness_quality_score).toFixed(1)} / ${safeNumber(
          quoteHealthStaleRecovery?.stale_data_risk_score
        ).toFixed(1)} (${String(quoteHealthStaleRecovery?.quote_recovery_reason || "unknown")}).`
      );
    }
    if (safeNumber(cryptoCoverageReliability?.crypto_trust_continuity_score) > 0) {
      list.push(
        `Crypto continuity: ${safeNumber(cryptoCoverageReliability?.crypto_trust_continuity_score).toFixed(1)} (${String(
          cryptoCoverageReliability?.crypto_recovery_mode || "degraded"
        )}).`
      );
    }
    if (safeNumber(performanceOptimizationSuite?.endpoint_efficiency_score) > 0) {
      list.push(
        `Endpoint/cache efficiency: ${safeNumber(performanceOptimizationSuite?.endpoint_efficiency_score).toFixed(1)} / ${safeNumber(
          performanceOptimizationSuite?.cache_quality_score
        ).toFixed(1)}.`
      );
    }
    if (safeNumber(tradeQualitySelectivitySuite?.expectancy_score) > 0) {
      list.push(
        `Trade selectivity score: ${safeNumber(tradeQualitySelectivitySuite?.expectancy_score).toFixed(1)} (PF ${safeNumber(
          tradeQualitySelectivitySuite?.profit_factor
        ).toFixed(2)}, median ${safeNumber(tradeQualitySelectivitySuite?.median_return).toFixed(4)}%).`
      );
    }
    if (safeNumber(gradeScaleLearning?.ab_trade_count) + safeNumber(gradeScaleLearning?.c_trade_count) + safeNumber(gradeScaleLearning?.df_trade_count) > 0) {
      list.push(
        `Grade memory split A/B:C:D/F = ${safeNumber(gradeScaleLearning?.ab_trade_count).toFixed(0)}:${safeNumber(
          gradeScaleLearning?.c_trade_count
        ).toFixed(0)}:${safeNumber(gradeScaleLearning?.df_trade_count).toFixed(0)}.`
      );
    }
    if (safeNumber(abstainLearning?.abstain_score) > 0 || Boolean(noTradeZoneDetection?.active)) {
      list.push(
        `Abstain intelligence score ${safeNumber(abstainLearning?.abstain_score).toFixed(1)}; no-trade=${String(
          Boolean(noTradeZoneDetection?.active)
        )}, confirmation-required=${String(Boolean(confirmationRequiredZoneDetection?.active))}.`
      );
    }
    if (safeNumber(expectancyFrictionRealism?.friction_aware_quality_score) > 0) {
      list.push(
        `Friction-aware quality is ${safeNumber(expectancyFrictionRealism?.friction_aware_quality_score).toFixed(1)} (${String(
          expectancyFrictionRealism?.usability_label || "insufficient_evidence"
        ).replaceAll("_", " ")}).`
      );
    }
    return list.slice(0, 5);
  }, [decisionFeedback, paperOutcome, recentVsPriorWinDelta, policyAction, policyReason, learningQuality, contextualLearning, convictionTierPerf, entryTimingHints, deteriorationInvalidationHints, contextualExecutionRefinement, tradeManagementRealism, contextConfidenceEvidence, catalystNewsIntelligence, externalContextClassification, macroRegimeAwareness, forecastingQualityRefinement, confidenceCalibration, contradictionSelfCheck, crossLayerDecisionCoherence, providerBlendingReliability, quoteHealthStaleRecovery, cryptoCoverageReliability, performanceOptimizationSuite, tradeQualitySelectivitySuite, gradeScaleLearning, abstainLearning, noTradeZoneDetection, confirmationRequiredZoneDetection, expectancyFrictionRealism]);

  const statusSummary = [
    ["learning_insights", endpointStatus?.learning_insights?.httpStatus ?? "n/a"],
    ["paper_performance", endpointStatus?.paper_performance?.httpStatus ?? "n/a"],
    ["paper_status", endpointStatus?.paper_status?.httpStatus ?? "n/a"],
    ["paper_worker_status", endpointStatus?.paper_worker_status?.httpStatus ?? "n/a"],
    ["model_status", endpointStatus?.model_status?.httpStatus ?? "n/a"],
    ["system_status", endpointStatus?.system_status?.httpStatus ?? "n/a"],
  ];

  const whatAstraIsDoingNow = useMemo(() => {
    const lines = [];
    if (snapshotInsufficientEvidence) {
      lines.push("Current learning snapshot has insufficient fresh evidence for directional claims.");
      lines.push(
        learningPayloadFalseEmptyPrevented
          ? "False-empty regression was prevented; displaying last known good learning state."
          : "Live learning rebuild is pending; treat this snapshot as provisional."
      );
      lines.push(
        `Payload source: ${learningPayloadSource.replaceAll("_", " ")}${learningPayloadStale ? " (stale)" : ""}.`
      );
      if (learningPayloadDegradedReason) {
        lines.push(`Degraded reason: ${learningPayloadDegradedReason.replaceAll("_", " ")}.`);
      }
      lines.push(
        `Available historical evidence: ${safeNumber(fullValidClosedCount).toFixed(0)} closed trades; current cohort samples ${safeNumber(cohortSampleTotal).toFixed(0)}.`
      );
      return lines.slice(0, 5);
    }
    const stableRuntime = Boolean(astraOperatingStandard?.stable_runtime);
    const trustedActionability = Boolean(astraOperatingStandard?.trusted_actionability);
    const entryScore = safeNumber(entryExecutionQuality?.entry_quality_score, astraOperatingStandard?.entry_quality_score);
    const followScore = safeNumber(followthroughQuality?.follow_through_entry_score, astraOperatingStandard?.follow_through_quality_score);
    const sellScore = safeNumber(sellSignalQuality?.sell_signal_accuracy_score, astraOperatingStandard?.sell_signal_quality_score);
    const winDeltaBlocked = safeNumber((learningInsights?.current_engine_outcome_evaluation || {}).released_vs_blocked_win_rate_delta, learningInsights?.released_vs_blocked_win_rate_delta);
    const evidenceReady = Boolean(evidenceReadinessSummary?.evidence_ready);
    const confidenceReady = Boolean(evidenceReadinessSummary?.confidence_ready);
    const mainWeakness = entryScore < 45 ? "entries" : followScore < 52 ? "follow-through" : sellScore < 55 ? "sell discipline" : "sample quality and consistency";

    if (stableRuntime && trustedActionability) {
      lines.push("Astra is stable, trusted, and actively producing buy candidates.");
    } else if (!stableRuntime) {
      lines.push("Astra runtime is currently unstable; treat signal quality with caution.");
    } else {
      lines.push("Astra is running, but trust/actionability is not fully clean.");
    }
    lines.push(
      `Current-engine released quality is ${winDeltaBlocked >= 0 ? "holding above" : "below"} blocked/watchlist by ${winDeltaBlocked.toFixed(2)} win-rate points.`
    );
    lines.push(
      `Entry quality ${entryScore.toFixed(1)} and follow-through quality ${followScore.toFixed(1)} indicate the biggest weakness is ${mainWeakness}.`
    );
    lines.push(
      `Evidence readiness is ${evidenceReady ? "ready" : "limited"}${confidenceReady ? " with confidence buckets ready" : " and confidence buckets are still limited"}.`
    );
    return lines;
  }, [
    astraOperatingStandard,
    entryExecutionQuality,
    followthroughQuality,
    sellSignalQuality,
    evidenceReadinessSummary,
    learningInsights,
    snapshotInsufficientEvidence,
    learningPayloadFalseEmptyPrevented,
    learningPayloadSource,
    learningPayloadStale,
    learningPayloadDegradedReason,
    fullValidClosedCount,
    cohortSampleTotal,
  ]);


  const stocksFinal = ((topBuys?.stocks || {}).final || []).length;
  const cryptoFinal = ((topBuys?.crypto || {}).final || []).length;
  const promotionSummary = topBuys?.candidate_promotion_summary || {};
  const stockPromotion = promotionSummary?.stocks || {};
  const cryptoPromotion = promotionSummary?.crypto || {};
  const stockHoldDiag = stockPromotion?.hold_vs_buy_diagnostics || {};
  const cryptoHoldDiag = cryptoPromotion?.hold_vs_buy_diagnostics || {};
  const abRankedCount = safeNumber(promotionSummary?.a_b_ranked_count,
    actionabilityQualitySuite?.a_b_ranked,
    safeNumber(((topBuys?.stocks || {}).strong_buy_conversion_summary || {}).ab_ranked_count)
    + safeNumber(((topBuys?.crypto || {}).strong_buy_conversion_summary || {}).ab_ranked_count)
  );
  const abPromotedCount = safeNumber(promotionSummary?.a_b_promoted_to_strong_buy_count,
    actionabilityQualitySuite?.a_b_promoted,
    safeNumber(((topBuys?.stocks || {}).strong_buy_conversion_summary || {}).ab_promoted_to_strong_buy_count)
    + safeNumber(((topBuys?.crypto || {}).strong_buy_conversion_summary || {}).ab_promoted_to_strong_buy_count)
  );
  const abBlockedCount = safeNumber(promotionSummary?.a_b_blocked_count,
    actionabilityQualitySuite?.a_b_blocked,
    safeNumber(((topBuys?.stocks || {}).a_b_candidates_blocked_count))
    + safeNumber(((topBuys?.crypto || {}).a_b_candidates_blocked_count))
  );
  const abConversionRate = abRankedCount > 0 ? (abPromotedCount / abRankedCount) * 100.0 : 0.0;
  const topPromotionBlockers = useMemo(() => {
    const merged = {};
    const stockBlockers = stockPromotion?.promotion_blocker_summary || {};
    const cryptoBlockers = cryptoPromotion?.promotion_blocker_summary || {};
    [...Object.entries(stockBlockers), ...Object.entries(cryptoBlockers)].forEach(([k, v]) => {
      merged[k] = safeNumber(merged[k]) + safeNumber(v);
    });
    return Object.entries(merged)
      .sort((a, b) => safeNumber(b[1]) - safeNumber(a[1]))
      .slice(0, 3)
      .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
      .join(", ");
  }, [stockPromotion, cryptoPromotion]);
  const highGradeHoldCount = safeNumber(stockHoldDiag?.high_grade_hold_count) + safeNumber(cryptoHoldDiag?.high_grade_hold_count);
  const cSoftPromotedDueToABBlocks = safeNumber(promotionSummary?.c_soft_promoted_due_to_a_b_blocks_count);
  const strongerReplacementCount = safeNumber(promotionSummary?.stronger_candidate_replacement_count);
  const falseNegativeABCount = safeNumber(promotionSummary?.false_negative_a_b_count);
  const falsePositiveABCount = safeNumber(promotionSummary?.false_positive_a_b_count);
  const promotionEfficiencyScore = firstFiniteOrNull(promotionSummary?.promotion_efficiency_score);
  const promotionIntegrityScore = firstFiniteOrNull(promotionSummary?.promotion_integrity_score);
  const highGradeHoldRatePercent = firstFiniteOrNull(promotionSummary?.high_grade_hold_rate_percent);
  const thresholdTightness = promotionSummary?.threshold_tightness || {};
  const cSoftFallbackTuning = promotionSummary?.c_soft_fallback_tuning || {};
  const actionabilityTuningSuggestions = promotionSummary?.actionability_tuning_suggestions || {};
  const decisionEngineSummary = promotionSummary?.decision_engine_summary || {};
  const decisionEnvironmentPosture = promotionSummary?.decision_environment_posture || {};
  const actionabilityBoundary = promotionSummary?.actionability_boundary_intelligence || {};
  const cSoftTrueUnavailableCount = safeNumber(promotionSummary?.c_soft_due_to_true_a_b_unavailability_count);
  const productionConversionTuning = promotionSummary?.strong_buy_conversion_tuning || {};
  const noStrongBuyDiagnostics = promotionSummary?.no_strong_buy_diagnostics || {};
  const topPickProductionPriority = promotionSummary?.top_pick_production_priority || {};
  const secondaryBucketSeparation = promotionSummary?.secondary_bucket_separation || {};
  const heroSecondaryAlignment = promotionSummary?.hero_secondary_alignment_checks || {};
  const heroReleaseControls = promotionSummary?.strong_buy_hero_release_controls || {};
  const buyFirstActionEngine = promotionSummary?.buy_first_action_engine || {};
  const decisionConversionSuite = promotionSummary?.decision_conversion_improvement_suite || {};
  const candidateLearningSuite = promotionSummary?.candidate_learning_quality_suite || {};
  const heroRankedAlignmentSuite = promotionSummary?.hero_ranked_alignment_suite || {};
  const buyConversionEngine = promotionSummary?.buy_conversion_engine || {};
  const blockerRecalibrationSuite = promotionSummary?.blocker_recalibration_suite || {};
  const paperReadyConversionSuite = promotionSummary?.paper_ready_conversion_suite || {};
  const heroCandidateQualitySuite = promotionSummary?.hero_candidate_quality_suite || {};
  const trustQuoteUnlockSuite = promotionSummary?.trust_quote_promotion_unlock_suite || {};
  const safeTrustReliefEngine = promotionSummary?.safe_trust_relief_engine || {};
  const safeQuoteReliefEngine = promotionSummary?.safe_quote_quality_relief_engine || {};
  const abQuoteTrustUnlockSuite = promotionSummary?.a_b_quote_trust_unlock_suite || {};
  const heroTierUpgradeSuite = promotionSummary?.hero_tier_upgrade_suite || {};
  const rankedBuyCoherenceSuite = promotionSummary?.ranked_buy_coherence_suite || {};
  const buyToPositionFeedbackSuite = promotionSummary?.buy_to_position_feedback_suite || {};
  const buyConversionTrendSuite = promotionSummary?.buy_conversion_trend || {};
  const performanceRecoveryEngine = learningInsights?.performance_recovery_engine || {};
  const confidenceRecalibrationEngine = learningInsights?.confidence_recalibration_engine || {};
  const outcomeFirstLearningSuite = learningInsights?.outcome_first_learning_suite || {};
  const tradeOutcomeQualitySuite = learningInsights?.trade_outcome_quality_suite || {};
  const entryTimingRecoverySuite = learningInsights?.entry_timing_recovery_suite || {};
  const exitTimingRecoverySuite = learningInsights?.exit_timing_recovery_suite || {};
  const positionDegradationEngine = learningInsights?.position_degradation_engine || {};
  const sellTruthfulnessLearningSuite = learningInsights?.sell_truthfulness_learning_suite || {};
  const sellTimingAccuracySuite = learningInsights?.sell_timing_accuracy_suite || {};
  const holdVsExitDecisionQualitySuite = learningInsights?.hold_vs_exit_decision_quality_suite || {};
  const buyPositionSellContinuitySuite = learningInsights?.buy_position_sell_continuity_suite || {};
  const workflowTruthfulnessSuite = learningInsights?.workflow_truthfulness_suite || {};
  const selectivityHardeningEngine = promotionSummary?.selectivity_hardening_engine || learningInsights?.selectivity_hardening_engine || {};
  const heroOutcomeQualitySuite = promotionSummary?.hero_outcome_quality_suite || learningInsights?.hero_outcome_quality_suite || {};
  const abReleaseQualitySuite = promotionSummary?.a_b_release_quality_suite || learningInsights?.a_b_release_quality_suite || {};
  const nearStrongOutcomeSuite = promotionSummary?.near_strong_outcome_suite || learningInsights?.near_strong_outcome_suite || {};
  const heroConversionQualitySuite = promotionSummary?.hero_conversion_quality_suite || learningInsights?.hero_conversion_quality_suite || {};
  const abBlockReductionEngine = promotionSummary?.a_b_block_reduction_engine || learningInsights?.a_b_block_reduction_engine || {};
  const confidenceTruthfulnessEngine = promotionSummary?.confidence_truthfulness_engine || learningInsights?.confidence_truthfulness_engine || {};
  const highConfidenceFalsePositiveSuppressionEngine = promotionSummary?.high_confidence_false_positive_suppression_engine || learningInsights?.high_confidence_false_positive_suppression_engine || {};
  const falseConfidenceBreakdownSuite = promotionSummary?.false_confidence_breakdown_suite || learningInsights?.false_confidence_breakdown_suite || {};
  const weakHighConfidenceSetupPenalty = promotionSummary?.weak_high_confidence_setup_penalty || learningInsights?.weak_high_confidence_setup_penalty || {};
  const prePromotionFalsePositiveGate = promotionSummary?.pre_promotion_false_positive_gate || learningInsights?.pre_promotion_false_positive_gate || {};
  const falsePositiveEnforcementEngine = promotionSummary?.false_positive_enforcement_engine || learningInsights?.false_positive_enforcement_engine || {};
  const weakHighConfidenceReleaseBlocker = promotionSummary?.weak_high_confidence_release_blocker || learningInsights?.weak_high_confidence_release_blocker || {};
  const heroReleaseEnforcementEngine = promotionSummary?.hero_release_enforcement_engine || learningInsights?.hero_release_enforcement_engine || {};
  const heroQualityEnforcementGate = promotionSummary?.hero_quality_enforcement_gate || learningInsights?.hero_quality_enforcement_gate || {};
  const enforcementVsOpportunityBalanceSuite = promotionSummary?.enforcement_vs_opportunity_balance_suite || learningInsights?.enforcement_vs_opportunity_balance_suite || {};
  const aBReleaseBalanceEngine = promotionSummary?.a_b_release_balance_engine || learningInsights?.a_b_release_balance_engine || {};
  const lowEdgeTradeSuppressionEngine = promotionSummary?.low_edge_trade_suppression_engine || learningInsights?.low_edge_trade_suppression_engine || {};
  const entryTimingRefinementEngine = promotionSummary?.entry_timing_refinement_engine || learningInsights?.entry_timing_refinement_engine || {};
  const exitTimingRefinementEngine = promotionSummary?.exit_timing_refinement_engine || learningInsights?.exit_timing_refinement_engine || {};
  const exitTimingRecoveryEngine = promotionSummary?.exit_timing_recovery_engine || learningInsights?.exit_timing_recovery_engine || {};
  const degradationDetectionRefinementEngine = promotionSummary?.degradation_detection_refinement_engine || learningInsights?.degradation_detection_refinement_engine || {};
  const earlyBreakdownWarningSuite = promotionSummary?.early_breakdown_warning_suite || learningInsights?.early_breakdown_warning_suite || {};
  const degradationExitEnforcementEngine = promotionSummary?.degradation_exit_enforcement_engine || learningInsights?.degradation_exit_enforcement_engine || {};
  const earlyWeakeningExitTrigger = promotionSummary?.early_weakening_exit_trigger || learningInsights?.early_weakening_exit_trigger || {};
  const lateExitPenaltyEnforcement = promotionSummary?.late_exit_penalty_enforcement || learningInsights?.late_exit_penalty_enforcement || {};
  const prematureExitDisciplineEngine = promotionSummary?.premature_exit_discipline_engine || learningInsights?.premature_exit_discipline_engine || {};
  const sellTruthfulnessRefinementEngine = promotionSummary?.sell_truthfulness_refinement_engine || learningInsights?.sell_truthfulness_refinement_engine || {};
  const exitTriggerQualityEngine = promotionSummary?.exit_trigger_quality_engine || learningInsights?.exit_trigger_quality_engine || {};
  const sellQualityEnforcementEngine = promotionSummary?.sell_quality_enforcement_engine || learningInsights?.sell_quality_enforcement_engine || {};
  const earlyLossPreventionEngine = promotionSummary?.early_loss_prevention_engine || learningInsights?.early_loss_prevention_engine || {};
  const candidateToExitWorkflowSuite = promotionSummary?.candidate_to_exit_workflow_suite || learningInsights?.candidate_to_exit_workflow_suite || {};
  const outcomeFeedbackEnforcementEngine = promotionSummary?.outcome_feedback_enforcement_engine || learningInsights?.outcome_feedback_enforcement_engine || {};
  const degradationEnforcementStabilitySuite = promotionSummary?.degradation_enforcement_stability_suite || learningInsights?.degradation_enforcement_stability_suite || {};
  const prematureExitReductionSuite = promotionSummary?.premature_exit_reduction_suite || learningInsights?.premature_exit_reduction_suite || {};
  const lateExitReductionSuite = promotionSummary?.late_exit_reduction_suite || learningInsights?.late_exit_reduction_suite || {};
  const earlyDegradationExitQualitySuite = promotionSummary?.early_degradation_exit_quality_suite || learningInsights?.early_degradation_exit_quality_suite || {};
  const heroReleasePrecisionEngine = promotionSummary?.hero_release_precision_engine || learningInsights?.hero_release_precision_engine || {};
  const fastLossLearningEngine = promotionSummary?.fast_loss_learning_engine || learningInsights?.fast_loss_learning_engine || {};
  const smartWinReinforcementEngine = promotionSummary?.smart_win_reinforcement_engine || learningInsights?.smart_win_reinforcement_engine || {};
  const weakSetupSuppressionEngine = promotionSummary?.weak_setup_suppression_engine || learningInsights?.weak_setup_suppression_engine || {};
  const strictEntryQualityEngine = promotionSummary?.strict_entry_quality_engine || learningInsights?.strict_entry_quality_engine || {};
  const earlyDegradationExitEngine = promotionSummary?.early_degradation_exit_engine || learningInsights?.early_degradation_exit_engine || {};
  const recentOutcomeWeightingEngine = promotionSummary?.recent_outcome_weighting_engine || learningInsights?.recent_outcome_weighting_engine || {};
  const recentRegimeAdaptationSuite = promotionSummary?.recent_regime_adaptation_suite || learningInsights?.recent_regime_adaptation_suite || {};
  const actionableVsInterestingEngine = promotionSummary?.actionable_vs_interesting_engine || learningInsights?.actionable_vs_interesting_engine || {};
  const entryQualityRecoveryEngine = promotionSummary?.entry_quality_recovery_engine || learningInsights?.entry_quality_recovery_engine || {};
  const buyListPurityRepairEngine = promotionSummary?.buy_list_purity_repair_engine || learningInsights?.buy_list_purity_repair_engine || {};
  const actionableCandidateRecoverySuite = promotionSummary?.actionable_candidate_recovery_suite || learningInsights?.actionable_candidate_recovery_suite || {};
  const heroRecoveryEngine = promotionSummary?.hero_recovery_engine || learningInsights?.hero_recovery_engine || {};
  const confirmationFollowthroughRepairEngine = promotionSummary?.confirmation_followthrough_repair_engine || learningInsights?.confirmation_followthrough_repair_engine || {};
  const postEntryFollowthroughPredictivenessEngine = promotionSummary?.post_entry_followthrough_predictiveness_engine || learningInsights?.post_entry_followthrough_predictiveness_engine || {};
  const lossSuppressionBalanceSuite = promotionSummary?.loss_suppression_balance_suite || learningInsights?.loss_suppression_balance_suite || {};
  const finalHeroReleaseCalibrationEngine = promotionSummary?.final_hero_release_calibration_engine || learningInsights?.final_hero_release_calibration_engine || {};
  const paperReadyToHeroConversionEngine = promotionSummary?.paper_ready_to_hero_conversion_engine || learningInsights?.paper_ready_to_hero_conversion_engine || {};
  const eliteCandidateReleaseBalanceSuite = promotionSummary?.elite_candidate_release_balance_suite || learningInsights?.elite_candidate_release_balance_suite || {};
  const heroUnderreleaseDetectionEngine = promotionSummary?.hero_underrelease_detection_engine || learningInsights?.hero_underrelease_detection_engine || {};
  const heroBlockerTruthfulnessSuite = promotionSummary?.hero_blocker_truthfulness_suite || learningInsights?.hero_blocker_truthfulness_suite || {};
  const heroQualityPreservationEngine = promotionSummary?.hero_quality_preservation_engine || learningInsights?.hero_quality_preservation_engine || {};
  const heroReleaseSuppressionBalanceSuite = promotionSummary?.hero_release_suppression_balance_suite || learningInsights?.hero_release_suppression_balance_suite || {};
  const canonicalDecisionEngine = promotionSummary?.canonical_decision_engine || {};
  const thresholdTightnessLabel = [
    `strong:${String(thresholdTightness?.strong_buy_threshold_tightness || "n/a")}`,
    `confirm:${String(thresholdTightness?.confirmation_threshold_tightness || "n/a")}`,
    `quality:${String(thresholdTightness?.quality_selectivity_penalty_tightness || "n/a")}`,
  ].join(" | ");
  const actionTierCounts = actionTierControls?.tier_counts || {};
  const allTrusted = useMemo(() => {
    const s = ((topBuys?.stocks || {}).final || []);
    const c = ((topBuys?.crypto || {}).final || []);
    const all = [...s, ...c];
    return all.length > 0 && all.every((x) => Boolean(x?.trusted_quote_for_buys));
  }, [topBuys]);
  const stocksSizing = ((topBuys?.stocks || {}).position_sizing_summary || {});
  const cryptoSizing = ((topBuys?.crypto || {}).position_sizing_summary || {});

  const performanceCards = [
    { label: "Total Trades (Long-History)", value: safeNumber(fullValidClosedCount).toFixed(0) },
    { label: "Win Rate (Long-History)", value: fmtPct(paperOutcome?.win_rate) },
    { label: "Recent Win Rate (Long-History)", value: fmtPct((paperCohort?.recent || {}).win_rate) },
    { label: "Current-Engine Released WR", value: fmtPct((learningInsights?.current_engine_outcome_evaluation || {}).released_hero_win_rate) },
    { label: "Learning Confidence", value: String(learningConfidence || "insufficient evidence") },
    { label: "Current Trend", value: String(overallTrend || "flat").replaceAll("_", " ") },
    { label: "Recovery Score", value: safeNumber(performanceRecoveryEngine?.trade_quality_recovery_score).toFixed(1) },
  ];

  const performanceSummaryRows = [
    { label: "Average Return", value: `${safeNumber(paperOutcome?.avg_return).toFixed(4)}%` },
    { label: "Median Return", value: `${safeNumber(paperOutcome?.median_return).toFixed(4)}%` },
    { label: "Profit Factor", value: firstFiniteOrNull(tradeQualityProfitFactor) === null ? "insufficient evidence" : safeNumber(tradeQualityProfitFactor).toFixed(2) },
    { label: "Trade Quality Recovery", value: `${safeNumber(performanceRecoveryEngine?.trade_quality_recovery_score).toFixed(1)}` },
    { label: "Win/Loss Separation", value: `${safeNumber(outcomeFirstLearningSuite?.win_loss_separation_quality).toFixed(1)}` },
    { label: "Confidence Truthfulness", value: `${safeNumber(confidenceTruthfulnessEngine?.confidence_truthfulness_score).toFixed(1)}` },
    { label: "Over-Enforcement", value: `${safeNumber(falsePositiveEnforcementEngine?.over_enforcement_score).toFixed(1)}` },
    { label: "A/B Overblocking", value: `${safeNumber(abBlockReductionEngine?.a_b_overblocking_score).toFixed(1)}` },
    { label: "Released Hero Quality", value: `${safeNumber(canonicalDecisionEngine?.released_buy_quality_score).toFixed(1)}` },
    { label: "Fast Loss Learning", value: `${safeNumber(fastLossLearningEngine?.fast_loss_learning_score).toFixed(1)}` },
    { label: "Smart Win Reinforcement", value: `${safeNumber(smartWinReinforcementEngine?.smart_win_reinforcement_score).toFixed(1)}` },
    { label: "Recent Outcome Weighting", value: `${safeNumber(recentOutcomeWeightingEngine?.recent_outcome_weighting_score).toFixed(1)}` },
    { label: "Recent Improvement", value: `${safeNumber(canonicalDecisionEngine?.recent_improvement_score).toFixed(1)}` },
    { label: "Learning Confidence", value: String(learningConfidence || "insufficient evidence") },
    { label: "Trend", value: String(overallTrend || "flat").replaceAll("_", " ") },
  ];

  const entryExitBars = [
    { name: "Entries", good: safeNumber(decisionFeedback?.good_entries), bad: safeNumber(decisionFeedback?.bad_entries) },
    { name: "Exits", early: safeNumber(decisionFeedback?.early_exits), late: safeNumber(decisionFeedback?.late_exits), missed: safeNumber(decisionFeedback?.missed_profit_cases) },
  ];

  const entryQualityScore = clampValue(
    safeNumber(decisionFeedback?.good_entries) + safeNumber(decisionFeedback?.bad_entries) > 0
      ? (safeNumber(decisionFeedback?.good_entries) / Math.max(1, safeNumber(decisionFeedback?.good_entries) + safeNumber(decisionFeedback?.bad_entries))) * 100.0
      : 0.0
  );
  const releasedVsBlockedWinRateGap = safeNumber(
    (learningInsights?.current_engine_outcome_evaluation || {}).released_vs_blocked_win_rate_delta,
    learningInsights?.released_vs_blocked_win_rate_delta
  );
  const followThroughScore = safeNumber(
    followthroughQuality?.follow_through_entry_score,
    learningInsights?.follow_through_quality_score,
    50
  );
  const buyPurityScore = safeNumber(
    actionableVsInterestingEngine?.buy_list_purity_score,
    buyListPurityRepairEngine?.clean_buy_list_rate,
    learningInsights?.buy_list_purity_score
  );
  const exitQualityScore = safeNumber(
    learningInsights?.current_engine_exit_timing_score,
    sellSignalQuality?.sell_signal_accuracy_score,
    buyToPositionFeedbackSuite?.exit_timing_quality_score
  );
  const runtimeLearningStabilityScore = safeNumber(
    runtimeHardening?.runtime_health_score,
    runtimePerformanceSummary?.runtime_health_score,
    0
  );
  const currentTrendLabel = String(overallTrend || "mixed").replaceAll("_", " ");
  const currentTrendTone = /improv|strong|up/i.test(currentTrendLabel)
    ? "strong"
    : (/wors|down|weak/i.test(currentTrendLabel) ? "weak" : "mixed");
  const learningConfidenceScore = firstFinite(
    learningInsights?.confidence_truthfulness_score,
    compactConfidenceTruthfulnessEngine?.confidence_truthfulness_score,
    (currentEngineWinRate + entryQualityScore + buyPurityScore + followThroughScore) / 4.0
  );
  const selectedTrendWindow = LEARNING_TREND_WINDOWS.find((w) => w.key === learningTrendWindow) || LEARNING_TREND_WINDOWS[0];
  const visibleLearningTrend = timeline.slice(-selectedTrendWindow.points);
  const snapshotDegradedLabel = snapshotInsufficientEvidence
    ? (learningPayloadFalseEmptyPrevented ? "last known good (degraded)" : "insufficient current evidence")
    : null;
  const primarySnapshotMetrics = [
    {
      key: "released_wr",
      title: "Released WR",
      subtitle: "How often current released picks are winning.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : fmtPct((learningInsights?.current_engine_outcome_evaluation || {}).released_hero_win_rate),
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(currentEngineWinRate, 58, 47),
    },
    {
      key: "entry_quality",
      title: "Entry Quality",
      subtitle: "Balance of good entries versus weak entries.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${entryQualityScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(entryQualityScore, 62, 50),
    },
    {
      key: "follow_through",
      title: "Follow-Through Quality",
      subtitle: "How often entries continue cleanly after entry.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${followThroughScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(followThroughScore, 62, 50),
    },
    {
      key: "buy_purity",
      title: "Buy List Purity",
      subtitle: "Cleanliness of promoted opportunities.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${buyPurityScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(buyPurityScore, 63, 50),
    },
    {
      key: "exit_quality",
      title: "Exit Quality",
      subtitle: "Timing/discipline quality of sell execution.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${exitQualityScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(exitQualityScore, 62, 50),
    },
    {
      key: "runtime",
      title: "Runtime Stability",
      subtitle: "Operational health of runtime + learning refresh cycle.",
      value: snapshotInsufficientEvidence ? (learningPayloadStale ? "Stale snapshot" : "Rebuild pending") : `${runtimeLearningStabilityScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(runtimeLearningStabilityScore, 70, 55),
    },
    {
      key: "learning_confidence",
      title: "Learning Confidence",
      subtitle: "Truthfulness and consistency of current learning signals.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${learningConfidenceScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(learningConfidenceScore, 70, 55),
    },
    {
      key: "trend",
      title: "Current Trend",
      subtitle: "Direction of recent live quality signals.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : currentTrendLabel,
      tone: snapshotInsufficientEvidence ? "caution" : currentTrendTone,
    },
  ];
  const topSnapshotMainWeakness = entryQualityScore < followThroughScore
    ? "entries"
    : (followThroughScore < exitQualityScore ? "follow-through" : "sell execution");
  const topSnapshotStrongestArea = exitQualityScore >= Math.max(entryQualityScore, followThroughScore)
    ? "exits"
    : (entryQualityScore >= followThroughScore ? "entries" : "follow-through");
  const operatingPosture = runtimeLearningStabilityScore >= 70 && buyPurityScore >= 55
    ? "selective execution"
    : (runtimeLearningStabilityScore >= 50 ? "cautious selective mode" : "stability caution");
  const whatNeedsAttention = snapshotInsufficientEvidence
    ? [
      "Biggest current weakness: insufficient fresh evidence for a confident weakness call.",
      "Strongest current area: withheld until live rebuild has usable samples.",
      `Operating posture: ${learningPayloadStale ? "degraded snapshot / use caution" : "live rebuild pending"}.`,
      `Main concern: ${learningPayloadFalseEmptyPrevented ? "false-empty snapshot was prevented; showing last known good state." : "learning snapshot is currently insufficient."}`,
      `Trend: ${snapshotDegradedLabel || "insufficient current evidence"}.`,
    ]
    : [
      `Biggest current weakness: ${topSnapshotMainWeakness}.`,
      `Strongest current area: ${topSnapshotStrongestArea}.`,
      `Operating posture: ${operatingPosture}.`,
      `Main concern: ${followThroughScore < 52 ? "weak follow-through after entry." : "maintaining clean promotion quality."}`,
      `Trend: ${currentTrendLabel}.`,
    ];
  const followThroughFailureRate = safeNumber(followThroughFailureHints?.immediate_failure_bias);
  const weakFollowThroughRate = safeNumber(deteriorationInvalidationHints?.weak_follow_through_rate_percent);
  const topSnapshotFollowthroughBars = [
    { name: "Follow-Through", value: followThroughScore },
    { name: "Weak Follow-Through", value: weakFollowThroughRate },
    { name: "Immediate Failure", value: followThroughFailureRate },
  ];
  const secondaryMetricCards = [
    { label: "Good Entries", value: safeNumber(decisionFeedback?.good_entries).toFixed(0), note: "Confirmed clean entries." },
    { label: "Bad Entries", value: safeNumber(decisionFeedback?.bad_entries).toFixed(0), note: "Entries that failed quality checks in hindsight." },
    { label: "Weak Follow-Through Rate", value: `${weakFollowThroughRate.toFixed(1)}%`, note: "Higher means continuation risk." },
    { label: "Immediate Failure Rate", value: `${followThroughFailureRate.toFixed(1)}%`, note: "Fast breakdown pressure after entry." },
    { label: "Confidence Truthfulness", value: `${safeNumber(compactConfidenceTruthfulnessEngine?.confidence_truthfulness_score).toFixed(1)}`, note: "How honest confidence buckets are." },
    { label: "Fast Loss Learning", value: `${safeNumber(fastLossLearningEngine?.fast_loss_learning_score).toFixed(1)}`, note: "Suppression of quick-failure patterns." },
    { label: "Smart Win Reinforcement", value: `${safeNumber(smartWinReinforcementEngine?.smart_win_reinforcement_score).toFixed(1)}`, note: "Reinforcement of clean winners." },
    { label: "Degradation Detection", value: `${safeNumber(positionDegradationEngine?.degradation_detection_score).toFixed(1)}`, note: "How quickly deterioration is recognized." },
    { label: "Early Breakdown Warning", value: `${safeNumber(earlyBreakdownWarningSuite?.early_breakdown_warning_score).toFixed(1)}`, note: "Warning quality before invalidation." },
    { label: "Candidate→Position Quality", value: `${safeNumber(buyToPositionFeedbackSuite?.candidate_to_position_quality_score).toFixed(1)}`, note: "Conversion quality into held positions." },
    { label: "Sell Truthfulness", value: `${safeNumber(sellTruthfulnessRefinementEngine?.sell_truthfulness_refinement_score, sellTruthfulnessLearningSuite?.sell_truthfulness_score).toFixed(1)}`, note: "Sell labels aligned with outcomes." },
  ];

  const sectorPerformanceRows = useMemo(() => {
    const bySector = (learningInsights?.segments || {}).by_sector || (paper?.decision_feedback_segments || {}).by_sector || {};
    return Object.entries(bySector)
      .map(([k, v]) => ({
        key: String(k || "unknown"),
        sample: safeNumber((v || {}).sample_size, (v || {}).trade_count),
        winRate: safeNumber((v || {}).win_rate),
        avgReturn: safeNumber((v || {}).avg_friction_return, (v || {}).avg_return),
      }))
      .filter((r) => r.sample >= 10 && r.key && r.key.toLowerCase() !== "unknown")
      .sort((a, b) => b.winRate - a.winRate)
      .slice(0, 8);
  }, [learningInsights, paper]);

  const personaPerformanceRows = useMemo(() => {
    const byPersona = (learningInsights?.segments || {}).by_persona || (paper?.decision_feedback_segments || {}).by_persona || {};
    return Object.entries(byPersona)
      .map(([k, v]) => ({
        key: String(k || "unknown"),
        sample: safeNumber((v || {}).sample_size, (v || {}).trade_count),
        winRate: safeNumber((v || {}).win_rate),
        avgReturn: safeNumber((v || {}).avg_friction_return, (v || {}).avg_return),
      }))
      .filter((r) => r.sample >= 10 && r.key && r.key.toLowerCase() !== "unknown")
      .sort((a, b) => b.winRate - a.winRate)
      .slice(0, 8);
  }, [learningInsights, paper]);

  const regimePerformanceRows = useMemo(() => {
    const byRegime = (learningInsights?.segments || {}).by_regime || (paper?.decision_feedback_segments || {}).by_regime || {};
    return Object.entries(byRegime)
      .map(([k, v]) => ({
        key: String(k || "unknown"),
        sample: safeNumber((v || {}).sample_size, (v || {}).trade_count),
        winRate: safeNumber((v || {}).win_rate),
      }))
      .filter((r) => r.sample >= 10 && r.key && r.key.toLowerCase() !== "unknown")
      .sort((a, b) => b.winRate - a.winRate)
      .slice(0, 6);
  }, [learningInsights, paper]);

  const confidenceBucketRows = useMemo(() => {
    const buckets = (confidenceCalibration?.confidence_bucket_performance || {});
    return Object.entries(buckets)
      .map(([k, v]) => ({
        key: String(k),
        winRate: safeNumber((v || {}).win_rate),
        sample: safeNumber((v || {}).sample_size),
      }))
      .filter((r) => r.sample >= 10)
      .slice(0, 6);
  }, [confidenceCalibration]);

  const conversionBars = [
    { name: "A/B", ranked: safeNumber(abRankedCount), promoted: safeNumber(abPromotedCount), blocked: safeNumber(abBlockedCount) },
  ];

  const readinessStack = [
    {
      name: "Status",
      live: safeNumber((promotionSummary?.final_buy_release_engine || {}).live_ready_hero_count, canonicalDecisionEngine?.released_hero_count),
      paper: safeNumber((promotionSummary?.final_buy_release_engine || {}).paper_ready_hero_count, canonicalDecisionEngine?.paper_ready_count),
      monitor: safeNumber((promotionSummary?.final_buy_release_engine || {}).watchlist_hero_count, canonicalDecisionEngine?.watchlist_count),
      blocked: safeNumber((promotionSummary?.final_buy_release_engine || {}).blocked_hero_count, canonicalDecisionEngine?.blocked_count),
    },
  ];

  const positionSellBars = [
    { name: "Candidate→Position", value: safeNumber(buyToPositionFeedbackSuite?.candidate_to_position_quality_score) },
    { name: "Position Survival", value: safeNumber(buyToPositionFeedbackSuite?.position_survival_score) },
    { name: "Sell Accuracy", value: safeNumber(buyToPositionFeedbackSuite?.sell_signal_accuracy_score, candidateLearningSuite?.sell_alert_accuracy_score) },
    { name: "Exit Timing", value: safeNumber(buyToPositionFeedbackSuite?.exit_timing_quality_score, candidateLearningSuite?.exit_timing_quality_score) },
    { name: "Premature Exit", value: safeNumber(buyToPositionFeedbackSuite?.premature_exit_score) },
  ];

  const advancedStatusFor = (key) => advancedEndpointStatus[key] || {};
  const snapshotCards = Array.isArray(advancedSnapshot?.cards) ? advancedSnapshot.cards : [];
  const institutionalCards = snapshotCards.length > 0
    ? snapshotCards.map((card) => ({
      key: card.key,
      title: card.title,
      value: card.primary_value || "Unavailable",
      detail: card.detail_value || card.secondary_value || card.error_reason || "Advanced metrics unavailable or still computing",
      status: String(card.status || "unavailable").toLowerCase(),
      secondary: card.secondary_value || "",
    }))
    : ADVANCED_METRIC_FALLBACK_CARDS.map((card) => ({
      key: card.key,
      title: card.title,
      value: advancedLoading ? "Loading" : "Unavailable",
      detail: advancedLoading ? "Fast snapshot request in progress" : "Advanced metrics unavailable or still computing",
      status: advancedLoading ? "still_computing" : "unavailable",
      secondary: "",
    }));
  const adaptiveQuantWeights = adaptiveQuantStatus?.recommended_shadow_weights || {};
  const adaptiveQuantBestWeight = adaptiveQuantStatus?.best_recommended_weight_change
    || Object.entries(adaptiveQuantWeights)[0]?.join(": ")
    || "baseline unchanged";
  const adaptiveQuantExit = adaptiveQuantStatus?.exit_optimization_summary || {};
  const adaptiveQuantSizing = adaptiveQuantStatus?.position_sizing_summary || {};
  const adaptiveQuantScorecard = adaptiveQuantStatus?.strategy_scorecard_summary || {};
  const adaptiveQuantWalkForward = adaptiveQuantStatus?.walk_forward_summary || {};
  const multiHorizonBest = multiHorizonStatus?.best_horizon_summary || {};
  const multiHorizonIntraday = multiHorizonStatus?.intraday_summary || {};
  const multiHorizonFactors = Array.isArray(multiHorizonStatus?.top_predictive_factors) ? multiHorizonStatus.top_predictive_factors : [];
  const learningExecutionAcceleration = learningExecutionStatus?.learning_acceleration_summary || {};
  const learningExecutionReplay = learningExecutionStatus?.replay_summary || {};
  const learningExecutionCounterfactual = learningExecutionStatus?.counterfactual_summary || {};
  const learningExecutionMemory = learningExecutionStatus?.memory_retention_summary || {};
  const learningExecutionQuality = learningExecutionStatus?.execution_quality_summary || {};
  const learningExecutionPortfolio = learningExecutionStatus?.portfolio_risk_summary || {};
  const contextProfitabilityTailwind = statusText(contextProfitabilityStatus?.strongest_context_tailwind, "neutral or insufficient data");
  const contextProfitabilityPenalty = statusText(contextProfitabilityStatus?.strongest_context_penalty, "none detected");
  const portfolioRiskIntelMode = statusText(portfolioRiskIntelStatus?.mode, "shadow_only");
  const portfolioRiskIntelPromotion = portfolioRiskIntelStatus?.promotion_allowed ? "yes" : "No";
  const combinedInstitutionalTrend = institutionalTrend.length > 0
    ? institutionalTrend
    : timeline.map((point) => ({
      ts: point.ts,
      releasedWinRate: safeNumber(point.winRate),
      buyListPurity: safeNumber(point.buyConversion),
    }));
  const learningFreshnessLabel = statusText(learningFreshness?.mode, "snapshot cache active");
  const learningFreshnessChanged = learningFreshness?.data_changed_since_last_rebuild === true ? "yes" : "no";
  const learningLastRefresh = firstNonEmpty(learningFreshness?.last_learning_refresh, lastFetchAt, "n/a");
  const learningNextRefresh = firstNonEmpty(learningFreshness?.next_learning_refresh, "scheduled by TTL");
  const learningNextAdvancedRefresh = firstNonEmpty(learningFreshness?.next_advanced_refresh, "scheduled by TTL");
  const truthRows = [
    ["Active learning", truthPanel?.active_learning_available ? "yes" : "no"],
    ["Real data source", truthPanel?.real_sources_found ? "yes" : "no"],
    ["Last real update", firstNonEmpty(truthPanel?.last_real_learning_update, learningLastRefresh, "unavailable")],
    ["Last snapshot build", firstNonEmpty(truthPanel?.last_snapshot_build, learningSnapshotFast?.updated_at, lastFetchAt, "unavailable")],
    ["Next refresh", learningNextRefresh],
    ["Replay integrated", truthPanel?.replay_rows_integrated ?? "n/a"],
    ["Labels created", truthPanel?.valid_labels_count ?? "n/a"],
    ["Closed trades", truthPanel?.closed_trades_count ?? "n/a"],
    ["Fallback used", truthPanel?.fallback_snapshot_used ? "yes" : "no"],
  ];

  if (compact) {
    return (
      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ ...panelStyle, padding: "14px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: "1.1rem", color: "#f3f8ff" }}>Learning Summary</h2>
              <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 4 }}>
                Current-engine learning only. Fresh evidence remains sample-gated.
              </div>
            </div>
            <div style={{ fontSize: 11, color: "#9fb1cc" }}>
              Updated {lastFetchAt || "n/a"}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
            {compactCards.map((card) => (
              <div
                key={card.label}
                style={{
                  background: "rgba(10, 22, 41, 0.56)",
                  border: "1px solid #29476f",
                  borderRadius: 12,
                  padding: "10px 11px",
                  display: "grid",
                  gap: 4,
                }}
              >
                <div style={{ fontSize: 11, color: "#90a8ca", textTransform: "uppercase", letterSpacing: "0.04em" }}>{card.label}</div>
                <div style={{ fontSize: 18, fontWeight: 800, color: "#eff5ff" }}>{card.value}</div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ ...panelStyle, padding: "14px" }}>
          <h3 style={{ marginTop: 0 }}>Current Engine</h3>
          <div style={{ display: "grid", gap: 6, fontSize: 12, color: "#dce8ff" }}>
            <div>Released vs paper win-rate delta: {safeNumber(learningInsights?.released_vs_paper_ready_win_rate_delta).toFixed(2)} pts</div>
            <div>Released vs blocked win-rate delta: {safeNumber(learningInsights?.released_vs_blocked_win_rate_delta).toFixed(2)} pts</div>
            <div>Released expectancy: {currentEngineExpectancy.toFixed(4)}%</div>
            <div>High vs medium confidence: {safeNumber(learningInsights?.released_high_confidence_win_rate).toFixed(2)}% / {safeNumber(learningInsights?.released_medium_confidence_win_rate).toFixed(2)}%</div>
            <div>Sell timing / protection: {safeNumber(learningInsights?.current_engine_exit_timing_score).toFixed(1)} / {safeNumber(learningInsights?.current_engine_profit_protection_score).toFixed(1)}</div>
          </div>
        </div>

        <div style={{ ...panelStyle, padding: "14px" }}>
          <h3 style={{ marginTop: 0 }}>Fresh Evidence</h3>
          <div style={{ display: "grid", gap: 6, fontSize: 12, color: "#dce8ff" }}>
            <div>Status: {String(learningSystemStatus?.status || "hold_and_measure_sample_limited").replaceAll("_", " ")}</div>
            <div>Post-change released / paper / blocked: {safeNumber((learningInsights?.post_change_sample_sizes || {}).released).toFixed(0)} / {safeNumber((learningInsights?.post_change_sample_sizes || {}).paper_ready).toFixed(0)} / {safeNumber((learningInsights?.post_change_sample_sizes || {}).blocked_watchlist).toFixed(0)}</div>
            <div>Post-change win rate / expectancy: {postChangeReleasedWinRate.toFixed(2)}% / {postChangeReleasedExpectancy.toFixed(4)}%</div>
            <div>Evidence ready: {String(Boolean(learningInsights?.post_change_evidence_ready))} | confidence ready: {String(Boolean(learningInsights?.post_change_confidence_ready))}</div>
            <div>Readiness progress: {safeNumber(evidenceReadinessSummary?.overall_post_change_readiness_pct).toFixed(1)}%</div>
            <div>Runtime bottleneck: {String(runtimePerformanceSummary?.dominant_bottleneck || "unknown").replaceAll("_", " ")}</div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: "12px" }}>
      {fetchError ? (
        <div style={{ ...panelStyle, borderColor: "#7f3f4a", color: "#ffd8dd", fontSize: 12 }}>
          Some learning endpoints failed: {fetchError}
        </div>
      ) : null}
      {secondaryLoading ? (
        <div style={{ ...panelStyle, fontSize: 12, color: "#c9d9f3", padding: "10px 12px" }}>
          <div>Loading advanced diagnostics…</div>
          <div style={{ marginTop: 4, color: "#9fb1cc" }}>
            Loading policy comparison… | Loading self-correction recommendations…
          </div>
        </div>
      ) : null}

      <div style={{ ...panelStyle, padding: "14px 14px 12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.08rem", color: "#f3f8ff" }}>Astra Learning Snapshot</h2>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 4 }}>
              High-signal view of current-engine quality, stability, and trend.
            </div>
            <div style={{ fontSize: 11, color: "#85a2c8", marginTop: 4 }}>
              Source: {learningPayloadSource.replaceAll("_", " ")}{learningPayloadStale ? " (stale)" : ""}{learningPayloadFalseEmptyPrevented ? " | false-empty prevented" : ""}
            </div>
            {learningPayloadDegradedReason ? (
              <div style={{ fontSize: 11, color: "#f0c6b1", marginTop: 2 }}>
                Degraded reason: {learningPayloadDegradedReason.replaceAll("_", " ")}
              </div>
            ) : null}
          </div>
          <div style={{ fontSize: 11, color: "#9fb1cc" }}>
            Updated {lastFetchAt || "n/a"}
          </div>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "#bfd3ef" }}>
            <span>Freshness: {learningFreshnessLabel.replaceAll("_", " ")}</span>
            <span>Last refreshed: {learningLastRefresh}</span>
            <span>Next learning refresh: {learningNextRefresh}</span>
            <span>Next advanced refresh: {learningNextAdvancedRefresh}</span>
            <span>Data changed: {learningFreshnessChanged}</span>
          </div>
          <button
            type="button"
            onClick={handleManualLearningRefresh}
            style={{
              border: "1px solid #42628f",
              borderRadius: 999,
              background: "rgba(12,24,42,0.35)",
              color: "#cfe1ff",
              padding: "5px 9px",
              fontSize: 11,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Refresh Learning Snapshot
          </button>
        </div>
        {manualRefreshMessage ? (
          <div style={{ marginBottom: 10, fontSize: 11, color: manualRefreshMessage.includes("failed") || manualRefreshMessage.includes("unavailable") ? "#ffd2b4" : "#a9f8d1" }}>
            {manualRefreshMessage}
          </div>
        ) : null}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, marginBottom: 10 }}>
          {truthRows.map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.38)", border: "1px solid #2f4a72", borderRadius: 8, padding: "7px 9px" }}>
              <div style={{ fontSize: 10, color: "#8ea8cc", textTransform: "uppercase", letterSpacing: "0.04em" }}>{label}</div>
              <div style={{ fontSize: 12, color: "#e6f0ff", fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis" }}>{String(value ?? "n/a")}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 9 }}>
          {primarySnapshotMetrics.map((metric) => {
            const tone = toneColors(metric.tone);
            return (
              <div
                key={metric.key}
                style={{
                  background: "rgba(10, 22, 41, 0.56)",
                  border: "1px solid #29476f",
                  borderRadius: 12,
                  padding: "10px 11px",
                  display: "grid",
                  gap: 5,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <div style={{ fontSize: 12, color: "#d5e6ff", fontWeight: 600 }}>{metric.title}</div>
                  <div style={{ background: tone.badgeBg, border: `1px solid ${tone.badgeBorder}`, color: tone.badgeText, borderRadius: 999, padding: "2px 8px", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                    {metric.tone}
                  </div>
                </div>
                <div style={{ fontSize: 21, lineHeight: 1.1, fontWeight: 800, color: "#f2f7ff" }}>{metric.value}</div>
                <div style={{ fontSize: 11, color: "#97afcf" }}>{metric.subtitle}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0, marginBottom: 8 }}>What Needs Attention</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "8px", fontSize: 12 }}>
          {whatNeedsAttention.map((line, idx) => (
            <div key={`attention-${idx}`} style={{ background: "rgba(12,24,42,0.40)", border: "1px solid #2f4a72", borderRadius: 8, padding: "8px 10px" }}>
              {line}
            </div>
          ))}
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
          <div>
            <h3 style={{ margin: 0 }}>Unified Learning Quality Trend</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 4 }}>
              One clean trend view for the current-engine quality signals.
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {LEARNING_TREND_WINDOWS.map((windowOption) => (
              <button
                key={windowOption.key}
                type="button"
                onClick={() => setLearningTrendWindow(windowOption.key)}
                style={{
                  border: "1px solid #42628f",
                  borderRadius: 999,
                  background: learningTrendWindow === windowOption.key ? "#dcecff" : "rgba(12,24,42,0.35)",
                  color: learningTrendWindow === windowOption.key ? "#123052" : "#cfe1ff",
                  padding: "5px 9px",
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                {windowOption.label}
              </button>
            ))}
          </div>
        </div>
        <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={visibleLearningTrend}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="winRate" stroke="#38bdf8" strokeWidth={2} dot={false} name="Released WR" />
              <Line type="monotone" dataKey="entryQuality" stroke="#22c55e" strokeWidth={2} dot={false} name="Entry Quality" />
              <Line type="monotone" dataKey="buyListPurity" stroke="#f59e0b" strokeWidth={2} dot={false} name="Buy List Purity" />
              <Line type="monotone" dataKey="followThroughQuality" stroke="#a78bfa" strokeWidth={2} dot={false} name="Follow-Through" />
              <Line type="monotone" dataKey="confidenceTruthfulness" stroke="#f472b6" strokeWidth={2} dot={false} name="Confidence Truthfulness" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Secondary Metrics</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8 }}>
          {secondaryMetricCards.map((metric) => (
            <div key={metric.label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>{metric.label}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#f2f7ff" }}>{metric.value}</div>
              <div style={{ fontSize: 11, color: "#8ea1c3", marginTop: 3 }}>{metric.note}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>What Astra Is Doing Now</h3>
        <div style={{ display: "grid", gap: 6, fontSize: 12, marginBottom: 10 }}>
          {whatAstraIsDoingNow.map((line, idx) => (
            <div key={`summary-${idx}`}>• {line}</div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 8, fontSize: 12 }}>
          <div>Current-engine mode: {String((learningInsights?.current_engine_outcome_evaluation || {}).cohort_mode || "unavailable").replaceAll("_", " ")}</div>
          <div>Post-change mode: {String(postChangeCurrentEngineQualityGate?.post_change_cohort_mode || "unavailable").replaceAll("_", " ")}</div>
          <div>Legacy context sample (long-history): {safeNumber(fullValidClosedCount).toFixed(0)} trades</div>
          <div>Current released / paper / blocked samples: {safeNumber((learningInsights?.cohort_sample_sizes || {}).released).toFixed(0)} / {safeNumber((learningInsights?.cohort_sample_sizes || {}).paper_ready).toFixed(0)} / {safeNumber((learningInsights?.cohort_sample_sizes || {}).blocked_watchlist).toFixed(0)}</div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Trade Quality & Entry/Exit</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "8px", marginBottom: 10 }}>
          {performanceCards.map((c) => (
            <div key={c.label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 8, padding: "8px 10px" }}>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>{c.label}</div>
              <div style={{ fontSize: 15, fontWeight: 700 }}>{c.value}</div>
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px", fontSize: 12, marginBottom: 8 }}>
          {performanceSummaryRows.map((r) => (
            <div key={r.label}>{r.label}: {r.value}</div>
          ))}
        </div>
        <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: "9px 10px", fontSize: 12, color: "#cfe1ff" }}>
          Detailed trade-quality inputs are summarized here; the unified trend chart above owns the repeated win-rate and quality trend visualization.
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Promotion / Buy Quality</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px", fontSize: 12, marginBottom: 10 }}>
          <div>Good entries: {safeNumber(decisionFeedback?.good_entries)}</div>
          <div>Bad entries: {safeNumber(decisionFeedback?.bad_entries)}</div>
          <div>Early exits: {safeNumber(decisionFeedback?.early_exits)}</div>
          <div>Late exits: {safeNumber(decisionFeedback?.late_exits)}</div>
          <div>Missed profit cases: {safeNumber(decisionFeedback?.missed_profit_cases)}</div>
          <div>Entry quality score: {entryQualityScore.toFixed(1)}</div>
          <div>Refined entry timing: {safeNumber(entryTimingRefinementEngine?.refined_entry_timing_score).toFixed(1)}</div>
          <div>Exit timing recovery: {safeNumber(exitTimingRecoveryEngine?.exit_timing_recovery_score, exitTimingRecoverySuite?.exit_timing_recovery_score).toFixed(1)}</div>
          <div>Refined exit timing: {safeNumber(exitTimingRefinementEngine?.refined_exit_timing_score, buyToPositionFeedbackSuite?.exit_timing_quality_score).toFixed(1)}</div>
          <div>Degradation detection refinement: {safeNumber(degradationDetectionRefinementEngine?.degradation_detection_refinement_score).toFixed(1)}</div>
          <div>Early breakdown warning: {safeNumber(earlyBreakdownWarningSuite?.early_breakdown_warning_score).toFixed(1)}</div>
          <div>Late exit discipline: {safeNumber(lateExitPenaltyEnforcement?.late_exit_penalty_enforcement_score, lateExitReductionSuite?.late_exit_reduction_score).toFixed(1)}</div>
          <div>Premature exit discipline: {safeNumber(prematureExitDisciplineEngine?.premature_exit_discipline_score, prematureExitReductionSuite?.premature_exit_reduction_score).toFixed(1)}</div>
          <div>Strict entry quality: {safeNumber(strictEntryQualityEngine?.strict_entry_quality_score, entryQualityRecoveryEngine?.entry_quality_recovery_score).toFixed(1)}</div>
          <div>Bad entry prevention: {safeNumber(strictEntryQualityEngine?.bad_entry_prevention_score).toFixed(1)}</div>
          <div>Early degradation exit: {safeNumber(earlyDegradationExitEngine?.early_degradation_exit_score, earlyDegradationExitQualitySuite?.early_degradation_exit_score).toFixed(1)}</div>
          <div>Fast loss containment: {safeNumber(earlyDegradationExitEngine?.fast_loss_containment_score, earlyLossPreventionEngine?.early_loss_prevention_score).toFixed(1)}</div>
          <div>Elite confirmation: {safeNumber(entryQualityRecoveryEngine?.elite_entry_confirmation_score).toFixed(1)}</div>
          <div>Follow-through recovery: {safeNumber(entryQualityRecoveryEngine?.followthrough_entry_recovery_score).toFixed(1)}</div>
          <div>Breakout separation: {safeNumber(confirmationFollowthroughRepairEngine?.breakout_separation_score, entryQualityRecoveryEngine?.true_breakout_validation_score).toFixed(1)}</div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>What Works / What Fails</h3>
        {sectorPerformanceRows.length === 0 && personaPerformanceRows.length === 0 ? (
          <div style={{ fontSize: 12, color: "#9fb1cc" }}>Insufficient evidence for sector/persona performance this cycle.</div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart layout="vertical" data={sectorPerformanceRows}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis type="number" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis type="category" dataKey="key" tick={{ fill: "#8ea1c3", fontSize: 11 }} width={80} />
                <Tooltip />
                <Bar dataKey="winRate" fill="#38bdf8" name="Sector Win Rate" />
              </BarChart>
            </ResponsiveContainer>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart layout="vertical" data={personaPerformanceRows}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis type="number" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis type="category" dataKey="key" tick={{ fill: "#8ea1c3", fontSize: 11 }} width={90} />
                <Tooltip />
                <Bar dataKey="winRate" fill="#22c55e" name="Persona Win Rate" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 12 }}>
          <div style={{ fontSize: 12 }}>
            <div style={{ color: "#9fb1cc", marginBottom: 4 }}>Best Setups</div>
            {(bestWorst?.best_setups || []).slice(0, 3).map((r, i) => (
              <div key={`best-setup-${i}`}>{String(r?.setup_type || "n/a")}: {fmtPct(r?.win_rate)}</div>
            ))}
          </div>
          <div style={{ fontSize: 12 }}>
            <div style={{ color: "#9fb1cc", marginBottom: 4 }}>Worst Setups</div>
            {(bestWorst?.worst_setups || []).slice(0, 3).map((r, i) => (
              <div key={`worst-setup-${i}`}>{String(r?.setup_type || "n/a")}: {fmtPct(r?.win_rate)}</div>
            ))}
          </div>
          <div style={{ fontSize: 12 }}>
            <div style={{ color: "#9fb1cc", marginBottom: 4 }}>Regime Performance</div>
            {regimePerformanceRows.length === 0 ? (
              <div>Insufficient evidence</div>
            ) : (
              regimePerformanceRows.slice(0, 4).map((r, i) => (
                <div key={`regime-${i}`}>{r.key}: {r.winRate.toFixed(1)}%</div>
              ))
            )}
            <div style={{ marginTop: 6 }}>Best sector WR: {safeNumber(tradeOutcomeQualitySuite?.best_sector_win_rate).toFixed(1)}%</div>
            <div>Worst sector WR: {safeNumber(tradeOutcomeQualitySuite?.worst_sector_win_rate).toFixed(1)}%</div>
            <div>Best persona WR: {safeNumber(tradeOutcomeQualitySuite?.best_persona_win_rate).toFixed(1)}%</div>
            <div>Worst persona WR: {safeNumber(tradeOutcomeQualitySuite?.worst_persona_win_rate).toFixed(1)}%</div>
            <div>Best setup score: {safeNumber(tradeOutcomeQualitySuite?.best_setup_type_score).toFixed(1)}</div>
            <div>Worst setup score: {safeNumber(tradeOutcomeQualitySuite?.worst_setup_type_score).toFixed(1)}</div>
            <div>Recent regime weighting: {safeNumber(recentRegimeAdaptationSuite?.regime_weighting_quality_score, recentOutcomeWeightingEngine?.recent_regime_adaptation_score).toFixed(1)}</div>
            <div>Recent sector weighting: {safeNumber(recentRegimeAdaptationSuite?.sector_weighting_quality_score, smartWinReinforcementEngine?.sector_weighting_quality_score).toFixed(1)}</div>
            <div>Recent persona weighting: {safeNumber(recentRegimeAdaptationSuite?.persona_weighting_quality_score, smartWinReinforcementEngine?.persona_weighting_quality_score).toFixed(1)}</div>
            <div>Elite setup repeatability: {safeNumber(smartWinReinforcementEngine?.elite_setup_repeat_score).toFixed(1)}</div>
          </div>
        </div>
        {confidenceBucketRows.length > 0 ? (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginBottom: 4 }}>Confidence Accuracy</div>
            <ResponsiveContainer width="100%" height={170}>
              <BarChart data={confidenceBucketRows}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="key" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="winRate" fill="#a78bfa" name="Win Rate by Confidence" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Promotion / Buy Quality</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "8px", fontSize: 12, marginBottom: 10 }}>
          <div>A/B ranked: {safeNumber(abRankedCount).toFixed(0)}</div>
          <div>A/B promoted: {safeNumber(abPromotedCount).toFixed(0)}</div>
          <div>A/B blocked: {safeNumber(abBlockedCount).toFixed(0)}</div>
          <div>High-grade hold rate: {safeNumber(highGradeHoldRatePercent, (promotionSummary?.final_buy_release_engine || {}).effective_hold_bias_score).toFixed(1)}%</div>
          <div>Buy conversion score: {safeNumber(buyConversionEngine?.buy_conversion_score).toFixed(1)}</div>
          <div>Overblocking score: {safeNumber(buyConversionEngine?.overblocking_score).toFixed(1)}</div>
          <div>Hero candidate count: {safeNumber((promotionSummary?.final_buy_release_engine || {}).hero_candidate_count, releasedHeroQualitySuite?.released_hero_count, canonicalDecisionEngine?.released_hero_count, topBuys?.released_hero_count).toFixed(0)}</div>
          <div>Paper-ready candidate count: {safeNumber(paperReadyConversionSuite?.paper_ready_buy_candidate_count).toFixed(0)}</div>
          <div>Near-strong candidate count: {safeNumber(paperReadyConversionSuite?.near_strong_upgrade_count).toFixed(0)}</div>
          <div>Effective hold bias: {safeNumber((promotionSummary?.final_buy_release_engine || {}).effective_hold_bias_score, buyConversionEngine?.hold_bias_score).toFixed(1)}</div>
          <div>Actionable A/B release rate: {safeNumber(strongBuyActionabilityRecalibration?.actionable_a_b_release_rate, abBlockReductionEngine?.actionable_a_b_release_rate).toFixed(1)}%</div>
          <div>Truly blocked A/B rate: {safeNumber(abBlockReductionEngine?.truly_blocked_a_b_rate).toFixed(1)}%</div>
          <div>Elite setup separation: {safeNumber(performanceRecoveryEngine?.elite_setup_separation_score).toFixed(1)}</div>
          <div>Low-edge suppression: {safeNumber(lowEdgeTradeSuppressionEngine?.low_edge_trade_suppression_score, selectivityHardeningEngine?.low_edge_trade_suppression_score).toFixed(1)}</div>
          <div>Hero outcome quality: {safeNumber(heroOutcomeQualitySuite?.hero_outcome_quality_score).toFixed(1)}</div>
          <div>A/B release quality: {safeNumber(abReleaseQualitySuite?.a_b_release_quality_score).toFixed(1)}</div>
          <div>Near-strong quality: {safeNumber(nearStrongOutcomeSuite?.near_strong_conversion_quality_score).toFixed(1)}</div>
          <div>Hero quality spread: {safeNumber(heroReleasePrecisionEngine?.hero_quality_spread_score).toFixed(1)}</div>
          <div>False-confidence breakdown: {safeNumber(falseConfidenceBreakdownSuite?.false_confidence_breakdown_score).toFixed(1)}</div>
          <div>Prevented false promotion rate: {safeNumber(falsePositiveEnforcementEngine?.prevented_false_promotion_rate, prePromotionFalsePositiveGate?.prevented_false_promotion_rate).toFixed(1)}%</div>
          <div>A/B release balance: {safeNumber(strongBuyActionabilityRecalibration?.a_b_release_balance_score, aBReleaseBalanceEngine?.a_b_release_balance_score).toFixed(1)}</div>
          <div>Weak setup suppression: {safeNumber(weakSetupSuppressionEngine?.weak_setup_suppression_score).toFixed(1)}</div>
          <div>Actionable vs interesting: {safeNumber(actionableVsInterestingEngine?.actionable_vs_interesting_score).toFixed(1)}</div>
          <div>Buy list purity: {safeNumber(actionableVsInterestingEngine?.buy_list_purity_score).toFixed(1)}</div>
          <div>Trade frequency quality: {safeNumber(weakSetupSuppressionEngine?.trade_frequency_quality_score).toFixed(1)}</div>
          <div>Actionable candidate recovery: {safeNumber(actionableCandidateRecoverySuite?.actionable_candidate_recovery_score, buyListPurityRepairEngine?.actionable_candidate_recovery_score).toFixed(1)}</div>
          <div>Shortlist quality recovery: {safeNumber(buyListPurityRepairEngine?.shortlist_quality_recovery_score).toFixed(1)}</div>
          <div>Clean buy list rate: {safeNumber(buyListPurityRepairEngine?.clean_buy_list_rate).toFixed(1)}%</div>
          <div>Paper-ready to hero conversion: {safeNumber(paperReadyToHeroConversionEngine?.paper_ready_to_hero_conversion_score).toFixed(1)}</div>
          <div>Valid paper-ready release rate: {safeNumber(finalHeroReleaseCalibrationEngine?.valid_paper_ready_release_rate).toFixed(1)}%</div>
          <div>Artificial release block rate: {safeNumber(heroBlockerTruthfulnessSuite?.artificial_release_block_rate).toFixed(1)}%</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, minHeight: 200 }}>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={conversionBars}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="ranked" fill="#94a3b8" name="Ranked" />
              <Bar dataKey="promoted" fill="#22c55e" name="Promoted" />
              <Bar dataKey="blocked" fill="#ef4444" name="Blocked" />
            </BarChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={readinessStack}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="live" stackId="a" fill="#22c55e" name="Live-ready" />
              <Bar dataKey="paper" stackId="a" fill="#38bdf8" name="Paper-ready" />
              <Bar dataKey="monitor" stackId="a" fill="#f59e0b" name="Monitor-only" />
              <Bar dataKey="blocked" stackId="a" fill="#ef4444" name="Blocked" />
            </BarChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeline}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="buyConversion" stroke="#38bdf8" strokeWidth={2} dot={false} name="Buy Conversion" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Position / Sell Performance</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "8px", fontSize: 12, marginBottom: 10 }}>
          <div>Open positions: {safeNumber(paperStatus?.open_positions_count, paper?.open_positions_count)}</div>
          <div>Candidate→position quality: {safeNumber(positionQualitySummary?.candidate_to_position_consistency_score, buyToPositionFeedbackSuite?.candidate_to_position_quality_score).toFixed(1)}</div>
          <div>Position survival score: {safeNumber(buyToPositionFeedbackSuite?.position_survival_score).toFixed(1)}</div>
          <div>Sell signal accuracy: {safeNumber(sellSignalQuality?.sell_signal_accuracy_score, buyToPositionFeedbackSuite?.sell_signal_accuracy_score, candidateLearningSuite?.sell_alert_accuracy_score).toFixed(1)}</div>
          <div>Exit timing quality: {safeNumber(buyToPositionFeedbackSuite?.exit_timing_quality_score, candidateLearningSuite?.exit_timing_quality_score).toFixed(1)}</div>
          <div>Average drawdown after peak: {safeNumber((closedPathQuality || {}).avg_drawdown_after_peak).toFixed(4)}%</div>
          <div>Sell alert reliability: {safeNumber(((promotionSummary?.final_position_lifecycle_engine || {}).sell_alert_reliability_score)).toFixed(1)}</div>
          <div>Degradation detection: {safeNumber(positionDegradationEngine?.degradation_detection_score).toFixed(1)}</div>
          <div>Early degradation exit quality: {safeNumber(earlyDegradationExitQualitySuite?.early_degradation_exit_score).toFixed(1)}</div>
          <div>Sell truthfulness: {safeNumber(sellTruthfulnessRefinementEngine?.sell_truthfulness_refinement_score, sellTruthfulnessLearningSuite?.sell_truthfulness_score).toFixed(1)}</div>
          <div>Sell timing accuracy: {safeNumber(sellTimingAccuracySuite?.sell_accuracy_score, exitTimingRecoveryEngine?.exit_timing_recovery_score).toFixed(1)}</div>
          <div>Exit trigger quality: {safeNumber(exitTriggerQualityEngine?.exit_trigger_quality_score).toFixed(1)}</div>
          <div>Early weakening exit trigger: {safeNumber(earlyWeakeningExitTrigger?.early_weakening_exit_trigger_score).toFixed(1)}</div>
          <div>Sell quality enforcement: {safeNumber(sellQualityEnforcementEngine?.sell_quality_enforcement_score).toFixed(1)}</div>
          <div>Candidate→exit workflow: {safeNumber(candidateToExitWorkflowSuite?.candidate_to_exit_workflow_score, buyPositionSellContinuitySuite?.buy_to_exit_workflow_quality_score).toFixed(1)}</div>
          <div>Future decision loop quality: {safeNumber(outcomeFeedbackEnforcementEngine?.future_decision_loop_quality_score).toFixed(1)}</div>
          <div>Degradation enforcement stability: {safeNumber(degradationEnforcementStabilitySuite?.degradation_enforcement_stability_score).toFixed(1)}</div>
          <div>Sell enforcement stability: {safeNumber(degradationEnforcementStabilitySuite?.sell_enforcement_stability_score, sellQualityEnforcementEngine?.sell_enforcement_stability_score).toFixed(1)}</div>
          <div>Overreactive exit risk: {safeNumber(degradationEnforcementStabilitySuite?.overreactive_exit_risk_score).toFixed(1)}</div>
          <div>Early loss prevention: {safeNumber(earlyLossPreventionEngine?.early_loss_prevention_score).toFixed(1)}</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, minHeight: 200 }}>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeline}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="sellAccuracy" stroke="#22c55e" strokeWidth={2} dot={false} name="Sell Signal Accuracy" />
            </LineChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={positionSellBars}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#38bdf8" name="Score" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ ...panelStyle, padding: "10px 12px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px" }}>
        <div style={{ fontSize: 12, color: "#9fb1cc" }}>
          Advanced Institutional Metrics load from a fast snapshot only when expanded.
        </div>
        <button
          type="button"
          onClick={() => setShowAdvancedSections((v) => !v)}
          style={{
            background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
            color: "#dce7ff",
            border: "1px solid #496a97",
            borderRadius: "6px",
            fontSize: "0.72rem",
            padding: "0.2rem 0.5rem",
            cursor: "pointer",
          }}
        >
          {showAdvancedSections ? "Hide Advanced Institutional Metrics" : "Show Advanced Institutional Metrics"}
        </button>
      </div>

      {showAdvancedSections ? (
      <>
      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
          <div>
            <h3 style={{ margin: 0 }}>Advanced Institutional Metrics</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 4 }}>
              Snapshot-first diagnostics; slow cards show stale, unavailable, or still-computing status without blocking the tab.
            </div>
          </div>
          <div style={{ fontSize: 11, color: advancedLoading ? "#ffd2b4" : "#a9f8d1" }}>
            {advancedLoading ? "Loading fast snapshot..." : (advancedLoadedOnce ? (advancedSnapshotMessage || "Metrics snapshot loaded") : "Snapshot not requested")}
          </div>
        </div>
        {advancedLoadedOnce && advancedSnapshot?.cards_failed > 0 ? (
          <div style={{ marginBottom: 10, padding: "8px 10px", borderRadius: 8, border: "1px solid #6b5630", background: "rgba(88, 62, 22, 0.24)", color: "#ffe2a1", fontSize: 12 }}>
            Advanced metrics unavailable or still computing for {advancedSnapshot.cards_failed} card{advancedSnapshot.cards_failed === 1 ? "" : "s"}. Loaded and stale cards remain visible.
          </div>
        ) : null}
        {advancedLoadedOnce ? (
          <div style={{ marginBottom: 10, display: "flex", gap: 8, flexWrap: "wrap", fontSize: 11, color: "#bfd3ef" }}>
            <span>Fresh: {safeNumber(advancedSnapshot?.fresh_cards)}</span>
            <span>Stale: {safeNumber(advancedSnapshot?.stale_cards_count, Array.isArray(advancedSnapshot?.stale_cards) ? advancedSnapshot.stale_cards.length : 0)}</span>
            <span>Computing: {safeNumber(advancedSnapshot?.computing_cards)}</span>
            <span>Unavailable: {safeNumber(advancedSnapshot?.unavailable_cards_count, Array.isArray(advancedSnapshot?.unavailable_cards) ? advancedSnapshot.unavailable_cards.length : 0)}</span>
            <span>Last update: {statusText(advancedSnapshot?.snapshot_generated_at, "not available")}</span>
            <span>Refresh: {statusText(advancedSnapshot?.freshness_status, "unknown")}</span>
          </div>
        ) : null}
        <div style={{ marginBottom: 12, border: "1px solid #345983", borderRadius: 10, background: "rgba(9, 22, 39, 0.48)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#e7f0ff", fontWeight: 700 }}>Adaptive Quant Optimization</div>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>
                Shadow-only recommendations; no production weights, paper decisions, or live trading behavior are changed.
              </div>
            </div>
            <div style={{ fontSize: 11, color: adaptiveQuantStatus?.enabled === false ? "#ffe2a1" : "#a9f8d1" }}>
              {adaptiveQuantMessage}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, fontSize: 12 }}>
            <div><span style={{ color: "#8ea1c3" }}>Mode:</span> {statusText(adaptiveQuantStatus?.mode, "shadow_only")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Projected improvement:</span> {safeNumber(adaptiveQuantStatus?.projected_improvement_pct).toFixed(2)}%</div>
            <div><span style={{ color: "#8ea1c3" }}>Best weight change:</span> {statusText(adaptiveQuantBestWeight, "baseline unchanged")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Regime:</span> {statusText(adaptiveQuantStatus?.current_regime, "unknown")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Exit finding:</span> {statusText(adaptiveQuantExit?.best_shadow_exit_policy, "collect more exits")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Sizing:</span> {statusText(adaptiveQuantSizing?.risk_tier, "shadow sizing")} {adaptiveQuantSizing?.suggested_position_size_pct != null ? `(${safeNumber(adaptiveQuantSizing.suggested_position_size_pct).toFixed(1)}%)` : ""}</div>
            <div><span style={{ color: "#8ea1c3" }}>Top strategy:</span> {statusText(adaptiveQuantScorecard?.top_strategy, "collect more outcomes")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Walk-forward:</span> {adaptiveQuantWalkForward?.passed_walk_forward ? "passed shadow gate" : statusText(adaptiveQuantWalkForward?.promotion_recommendation, "not promoted")}</div>
          </div>
        </div>
        <div style={{ marginBottom: 12, border: "1px solid #345983", borderRadius: 10, background: "rgba(9, 22, 39, 0.48)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#e7f0ff", fontWeight: 700 }}>Multi-Horizon, Intraday & Meta-Learning</div>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>
                Shadow-only timeframe, intraday, and factor-predictiveness diagnostics. No production ranking or trading changes.
              </div>
            </div>
            <div style={{ fontSize: 11, color: multiHorizonStatus?.enabled === false ? "#ffe2a1" : "#a9f8d1" }}>
              {multiHorizonMessage}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, fontSize: 12 }}>
            <div><span style={{ color: "#8ea1c3" }}>Mode:</span> {statusText(multiHorizonStatus?.mode, "shadow_only")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Best horizon:</span> {statusText(multiHorizonStatus?.best_horizon_detected || multiHorizonBest?.best_horizon_detected, "n/a")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Top factor:</span> {statusText(multiHorizonStatus?.top_predictive_factor || multiHorizonFactors[0]?.factor, "collecting evidence")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Intraday candidates:</span> {safeNumber(multiHorizonStatus?.intraday_candidate_count, multiHorizonIntraday?.day_trade_candidate_count).toFixed(0)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Projected improvement:</span> {safeNumber(multiHorizonStatus?.projected_improvement_pct).toFixed(2)}%</div>
            <div><span style={{ color: "#8ea1c3" }}>Promotion allowed:</span> {multiHorizonStatus?.promotion_allowed ? "yes" : "No"}</div>
          </div>
        </div>
        <div style={{ marginBottom: 12, border: "1px solid #345983", borderRadius: 10, background: "rgba(9, 22, 39, 0.48)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#e7f0ff", fontWeight: 700 }}>Learning Acceleration & Execution Quality</div>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>
                Shadow-first learning, replay, counterfactual, execution, scale, and risk diagnostics. No broker or production behavior changes.
              </div>
            </div>
            <div style={{ fontSize: 11, color: learningExecutionStatus?.enabled === false ? "#ffe2a1" : "#a9f8d1" }}>
              {learningExecutionMessage}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, fontSize: 12 }}>
            <div><span style={{ color: "#8ea1c3" }}>Mode:</span> {statusText(learningExecutionStatus?.mode, "shadow_first")}</div>
            <div><span style={{ color: "#8ea1c3" }}>Learning speedup:</span> {safeNumber(learningExecutionStatus?.projected_learning_speedup, learningExecutionAcceleration?.acceleration_factor || 1).toFixed(2)}x</div>
            <div><span style={{ color: "#8ea1c3" }}>Replay candidates:</span> {safeNumber(learningExecutionReplay?.replay_candidate_count).toFixed(0)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Counterfactual cases:</span> {safeNumber(learningExecutionCounterfactual?.counterfactual_cases_created).toFixed(0)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Memory quality:</span> {safeNumber(learningExecutionMemory?.memory_quality_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Execution quality:</span> {safeNumber(learningExecutionQuality?.execution_quality_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Target accuracy:</span> {safeNumber(learningExecutionQuality?.target_accuracy_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Portfolio heat:</span> {safeNumber(learningExecutionPortfolio?.portfolio_heat_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Promotion allowed:</span> {learningExecutionStatus?.promotion_allowed ? "yes" : "No"}</div>
          </div>
        </div>
        <div style={{ marginBottom: 12, border: "1px solid #345983", borderRadius: 10, background: "rgba(9, 22, 39, 0.48)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#e7f0ff", fontWeight: 700 }}>Context, Search & Profitability Suite V1</div>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>
                Shadow-only context tailwinds and penalties for sector, market-cap, catalyst, seasonality, crowding, and profit context.
              </div>
            </div>
            <div style={{ fontSize: 11, color: contextProfitabilityStatus?.enabled === false ? "#ffe2a1" : "#a9f8d1" }}>
              {contextProfitabilityMessage}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, fontSize: 12 }}>
            <div><span style={{ color: "#8ea1c3" }}>Average context:</span> {safeNumber(contextProfitabilityStatus?.average_context_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Candidates evaluated:</span> {safeNumber(contextProfitabilityStatus?.candidates_evaluated).toFixed(0)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Strongest tailwind:</span> {contextProfitabilityTailwind}</div>
            <div><span style={{ color: "#8ea1c3" }}>Strongest penalty:</span> {contextProfitabilityPenalty}</div>
            <div><span style={{ color: "#8ea1c3" }}>API calls used:</span> {safeNumber(contextProfitabilityStatus?.api_calls_used).toFixed(0)}</div>
          </div>
        </div>
        <div style={{ marginBottom: 12, border: "1px solid #345983", borderRadius: 10, background: "rgba(9, 22, 39, 0.48)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 13, color: "#e7f0ff", fontWeight: 700 }}>Portfolio & Risk Intelligence Suite V1</div>
              <div style={{ fontSize: 11, color: "#9fb1cc" }}>
                Shadow-only allocation, correlation, concentration, drawdown, and portfolio heat guidance. No execution or production ranking changes.
              </div>
            </div>
            <div style={{ fontSize: 11, color: portfolioRiskIntelStatus?.enabled === false ? "#ffe2a1" : "#a9f8d1" }}>
              {portfolioRiskIntelMessage}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 8, fontSize: 12 }}>
            <div><span style={{ color: "#8ea1c3" }}>Mode:</span> {portfolioRiskIntelMode}</div>
            <div><span style={{ color: "#8ea1c3" }}>Avg position size:</span> {safeNumber(portfolioRiskIntelStatus?.average_recommended_position_size_pct).toFixed(1)}%</div>
            <div><span style={{ color: "#8ea1c3" }}>Avg portfolio risk:</span> {safeNumber(portfolioRiskIntelStatus?.average_portfolio_risk_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Avg capital allocation:</span> {safeNumber(portfolioRiskIntelStatus?.average_capital_allocation_score).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Highest correlation risk:</span> {safeNumber(portfolioRiskIntelStatus?.highest_correlation_risk).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Highest concentration risk:</span> {safeNumber(portfolioRiskIntelStatus?.highest_concentration_risk).toFixed(1)}</div>
            <div><span style={{ color: "#8ea1c3" }}>API calls used:</span> {safeNumber(portfolioRiskIntelStatus?.api_calls_used).toFixed(0)}</div>
            <div><span style={{ color: "#8ea1c3" }}>Promotion allowed:</span> {portfolioRiskIntelPromotion}</div>
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 10, marginBottom: 12 }}>
          {institutionalCards.map((card) => {
            const status = card.status || "unavailable";
            const endpoint = advancedStatusFor(card.key);
            return (
              <InstitutionalMetricCard
                key={card.key}
                title={card.title}
                value={card.value}
                detail={card.detail || statusText(endpoint.error, "Advanced metrics unavailable or still computing")}
                status={card.status || status}
              />
            );
          })}
        </div>
        <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 8, padding: 8 }}>
          <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Institutional Quality Trend</div>
          <ResponsiveContainer width="100%" height={230}>
            <LineChart data={combinedInstitutionalTrend}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="entryQuality" stroke="#22c55e" strokeWidth={2} dot={false} name="Entry Quality V2" connectNulls />
              <Line type="monotone" dataKey="consensus" stroke="#38bdf8" strokeWidth={2} dot={false} name="Consensus" connectNulls />
              <Line type="monotone" dataKey="releasedWinRate" stroke="#f59e0b" strokeWidth={2} dot={false} name="Released Win Rate" connectNulls />
              <Line type="monotone" dataKey="buyListPurity" stroke="#a78bfa" strokeWidth={2} dot={false} name="Buy List Purity" connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px" }}>
        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Hard vs Soft Buy Performance</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Hard buys: {hardBuyCount} trades | WR {fmtPct(hardBuyPerf?.win_rate)} | Avg {safeNumber(hardBuyPerf?.avg_return).toFixed(4)}%</div>
            <div>Soft buys: {softBuyCount} trades | WR {fmtPct(softBuyPerf?.win_rate)} | Avg {safeNumber(softBuyPerf?.avg_return).toFixed(4)}%</div>
            <div>Delta (hard-soft, winsorized): {hardSoftWinsorizedDelta >= 0 ? "+" : ""}{hardSoftWinsorizedDelta.toFixed(4)}%</div>
            <div>Median delta: {(safeNumber(hardBuyPerf?.median_return) - safeNumber(softBuyPerf?.median_return)).toFixed(4)}%</div>
            <div>Policy: {policyAction.replaceAll("_", " ")} | Soft multiplier: {safeNumber(buyQualityPolicy?.soft_buy_multiplier, 1).toFixed(3)}</div>
          </div>
        </div>

        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Learning Source Mix</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Live paper share: {safeNumber(sourceContribution?.live_paper_share_percent).toFixed(1)}%</div>
            <div>Replay share: {safeNumber(replaySharePercent).toFixed(1)}%</div>
            <div>Replay contribution (learning rows): {replayContributionPercent.toFixed(1)}%</div>
            <div>Replay setup-label coverage: {fmtPct((replayLearningQuality?.label_coverage || {}).setup_type_percent)}</div>
            <div>Valid labels (learning rows): {safeNumber(liTotals?.valid_trades, fullValidClosedCount)}</div>
            <div>Sample window (recent closed): {recentSampleClosedCount}</div>
            <div>Invalid labels: {safeNumber(liTotals?.invalid_trades, paper?.invalid_trades_excluded_count)}</div>
          </div>
        </div>

        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Institutional Learning Controls</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Grade-scale memory: A/B {safeNumber(gradeScaleLearning?.ab_trade_count).toFixed(0)} | C {safeNumber(gradeScaleLearning?.c_trade_count).toFixed(0)} | D/F {safeNumber(gradeScaleLearning?.df_trade_count).toFixed(0)}</div>
            <div>Positive action multiplier: {safeNumber(positiveActionLearning?.actionability_multiplier, 1).toFixed(3)} | negative suppression: {safeNumber(negativeSuppressionLearning?.suppression_multiplier, 1).toFixed(3)}</div>
            <div>Boundary confirmation bias: {safeNumber(boundaryLearning?.confirmation_bias_multiplier, 1).toFixed(3)} | boundary score {safeNumber(boundaryLearning?.actionable_boundary_score).toFixed(1)}</div>
            <div>Abstain/no-trade score: {safeNumber(abstainLearning?.abstain_score).toFixed(1)} | no-trade {String(Boolean(noTradeZoneDetection?.active))}</div>
            <div>Reject mode: {String(Boolean(rejectOptionControls?.force_reject_mode))} | reasons {(rejectOptionControls?.reasons || []).slice(0, 2).join(", ") || "none"}</div>
            <div>Watchlist-only: {String(Boolean(watchlistOnlyZoneDetection?.active))} ({safeNumber(watchlistOnlyZoneDetection?.score).toFixed(1)})</div>
            <div>Confirmation-required: {String(Boolean(confirmationRequiredZoneDetection?.active))} ({safeNumber(confirmationRequiredZoneDetection?.score).toFixed(1)})</div>
            <div>Live-blocked: {String(Boolean(liveBlockedZoneDetection?.active))} ({safeNumber(liveBlockedZoneDetection?.score).toFixed(1)})</div>
            <div>Friction-aware quality: {safeNumber(expectancyFrictionRealism?.friction_aware_quality_score).toFixed(1)} ({String(expectancyFrictionRealism?.usability_label || "insufficient_evidence").replaceAll("_", " ")})</div>
            <div>Hard/soft refinement: {String(hardSoftRefinement?.recommended_soft_treatment || "keep").replaceAll("_", " ")} x{safeNumber(hardSoftRefinement?.soft_actionability_multiplier, 1).toFixed(3)}</div>
            <div>Cohort kill-switch: {String(Boolean(cohortKillswitchCooldown?.active))} | blocked families {(cohortKillswitchCooldown?.blocked_families || []).length}</div>
            <div>Counterfactual quality: {safeNumber(counterfactualLearning?.counterfactual_signal_quality_score).toFixed(1)} | exec error {safeNumber(executionErrorLearning?.execution_error_score).toFixed(1)}</div>
            <div>Missed opportunity pressure: {safeNumber(missedOpportunityLearning?.missed_opportunity_pressure_score).toFixed(1)} | post-trade diagnostics {safeNumber(postTradeDiagnostic?.diagnostic_quality_score).toFixed(1)}</div>
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>What Works / What Fails</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "10px", fontSize: 12 }}>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Setups</div>
            {(bestWorst?.best_setups || []).slice(0, 3).map((r, idx) => (
              <div key={`bs-${idx}`}>{r.setup_type}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Worst Setups</div>
            {(bestWorst?.worst_setups || []).slice(0, 3).map((r, idx) => (
              <div key={`ws-${idx}`}>{r.setup_type}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Regimes</div>
            {(bestWorst?.best_regimes || []).slice(0, 3).map((r, idx) => (
              <div key={`br-${idx}`}>{r.regime}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Personas</div>
            {(bestWorst?.best_personas || []).slice(0, 3).map((r, idx) => (
              <div key={`bp-${idx}`}>{r.persona}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Setup x Regime</div>
            {(bestWorst?.best_setup_regime || []).slice(0, 3).map((r, idx) => (
              <div key={`bsr-${idx}`}>{r.context}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Weakest Setup x Regime</div>
            {(bestWorst?.worst_setup_regime || []).slice(0, 3).map((r, idx) => (
              <div key={`wsr-${idx}`}>{r.context}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Contextual Learning</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "10px", fontSize: 12 }}>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Persona x Regime</div>
            {((contextualLearning?.top_persona_regime || {}).best || []).slice(0, 3).map((r, idx) => (
              <div key={`cpr-best-${idx}`}>{r.context_key}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Setup x Regime</div>
            {((contextualLearning?.top_setup_regime || {}).best || []).slice(0, 3).map((r, idx) => (
              <div key={`csr-best-${idx}`}>{r.context_key}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Setup x Cap Bucket</div>
            {((contextualLearning?.top_setup_cap_bucket || {}).best || []).slice(0, 3).map((r, idx) => (
              <div key={`csc-best-${idx}`}>{r.context_key}: {fmtPct(r.win_rate)} | {safeNumber(r.avg_friction_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Seasonality</div>
            <div>Seasonality data: {String(Boolean(contextualLearning?.seasonality_available))}</div>
            <div>Seasonal contexts tracked: {Object.keys(contextualPolicyHints?.season_setup || {}).length}</div>
            <div>Earnings-season contexts tracked: {Object.keys(contextualPolicyHints?.earnings_season_setup || {}).length}</div>
            <div>Seasonality strength score: {safeNumber(seasonalityRefinement?.seasonality_strength_score).toFixed(1)}</div>
            <div>Contextual adjustment count: {contextualAdjustmentCount}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Persona x Style Adaptation</div>
            <div>Confidence: {safeNumber(personaStyleAdaptation?.confidence_score).toFixed(1)} ({String(personaStyleAdaptation?.confidence_label || "low")})</div>
            <div>Contexts tracked: {safeNumber(personaStyleAdaptation?.context_count)}</div>
            <div>Evidence rows: {safeNumber(personaStyleAdaptation?.evidence_count)}</div>
            <div>Best contexts: {(personaStyleAdaptation?.best_fit_contexts || []).length}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Catalyst / News Context</div>
            <div>Catalyst share: {fmtPct(catalystNewsIntelligence?.catalyst_present_share_percent)}</div>
            <div>Risk level: {String(catalystNewsIntelligence?.catalyst_risk_level || "normal")}</div>
            <div>High-risk catalyst contexts: {(catalystNewsIntelligence?.high_risk_contexts || []).length}</div>
            <div>Favorable catalyst contexts: {(catalystNewsIntelligence?.favorable_contexts || []).length}</div>
            <div>Earnings context quality: {safeNumber(marketCatalystIntelligence?.earnings_context_quality_score).toFixed(1)}</div>
            <div>Post-earnings behavior score: {safeNumber(marketCatalystIntelligence?.post_earnings_behavior_score).toFixed(1)}</div>
            <div>Event uncertainty: {String(marketCatalystIntelligence?.event_uncertainty_level || "normal")}</div>
            <div>Catalyst confidence weight: {safeNumber(marketCatalystIntelligence?.catalyst_confidence_weight).toFixed(1)}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Context Confidence</div>
            <div>Overall confidence: {safeNumber(contextConfidenceEvidence?.overall_confidence_score).toFixed(1)}</div>
            <div>Confidence label: {String(contextConfidenceEvidence?.overall_confidence_label || "insufficient_contextual_evidence")}</div>
            <div>Strong edges: {safeNumber(contextConfidenceEvidence?.strong_edge_count)}</div>
            <div>Tentative edges: {safeNumber(contextConfidenceEvidence?.tentative_edge_count)}</div>
            <div>Total contextual evidence: {safeNumber(contextConfidenceEvidence?.total_evidence_count)}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Operational Readiness</div>
            <div>Runtime health score: {safeNumber(runtimeHardening?.runtime_health_score).toFixed(1)}</div>
            <div>Quote health score: {safeNumber(runtimeHardening?.quote_health_score).toFixed(1)}</div>
            <div>Replay continuity: {safeNumber(workerWatchdogReliability?.replay_continuity_score).toFixed(1)}</div>
            <div>Learning refresh continuity: {safeNumber(workerWatchdogReliability?.learning_refresh_continuity_score).toFixed(1)}</div>
            <div>Recommended posture: {String(executionReadinessControls?.recommended_posture || "caution").replaceAll("_", " ")}</div>
            <div>Deployment mode: {String(degradedHealthyMode?.mode || "degraded")} | penalties {safeNumber(degradedHealthyMode?.confidence_penalty_total).toFixed(1)}</div>
            <div>Readiness blockers: {(liveReadinessSuite?.readiness_blockers || []).length}</div>
            <div>Guardrail blockers: {(paperToLiveGuardrails?.guardrail_blockers || []).length}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Live Data Quality Assurance</div>
            <div>Current data mode: {String(dataEnvironmentPosture?.current_data_mode || "degraded")} | confidence {safeNumber(dataEnvironmentPosture?.live_data_confidence_score).toFixed(1)}</div>
            <div>Quote environment: {String(quoteQualityAssurance?.quote_environment_tier || "degraded")} | score {safeNumber(quoteQualityAssurance?.quote_quality_assurance_score).toFixed(1)}</div>
            <div>Live quality score: {safeNumber(quoteQualityAssurance?.live_quality_score).toFixed(1)} | cache penalty {safeNumber(quoteQualityAssurance?.cached_dependency_penalty).toFixed(1)}</div>
            <div>Tier thresholds: display {safeNumber(quoteActionabilityTiers?.display_quality_threshold, 35).toFixed(0)}, monitor {safeNumber(quoteActionabilityTiers?.monitor_quality_threshold, 50).toFixed(0)}, action {safeNumber(quoteActionabilityTiers?.action_quality_threshold, 64).toFixed(0)}, strong {safeNumber(quoteActionabilityTiers?.strong_buy_quality_threshold, 78).toFixed(0)}</div>
            <div>Tier counts: display {safeNumber(quoteQualityAssurance?.display_quality_count).toFixed(0)}, monitor {safeNumber(quoteQualityAssurance?.monitor_quality_count).toFixed(0)}, action {safeNumber(quoteQualityAssurance?.action_quality_count).toFixed(0)}, strong {safeNumber(quoteQualityAssurance?.strong_buy_quality_count).toFixed(0)}</div>
            <div>Provider health: {safeNumber(providerHealthIntelligence?.provider_health_score).toFixed(1)} ({String(providerHealthIntelligence?.provider_confidence_tier || "low")})</div>
            <div>Provider pressure/rescue: {safeNumber(providerHealthIntelligence?.provider_failure_pressure).toFixed(1)} / {safeNumber(providerHealthIntelligence?.provider_rescue_dependence).toFixed(1)}</div>
            <div>Stock continuity: {safeNumber(stockDataQualitySuite?.continuity_score).toFixed(1)} ({String(stockDataQualitySuite?.mode || "degraded")})</div>
            <div>Crypto continuity: {safeNumber(cryptoDataQualitySuite?.continuity_score).toFixed(1)} ({String(cryptoDataQualitySuite?.mode || "degraded")})</div>
            <div>Rolling 1h quality: {safeNumber((rollingProviderDataQualityMemory?.recent_1h_provider_quality || {}).provider_quality_score).toFixed(1)} | 6h {safeNumber((rollingProviderDataQualityMemory?.recent_6h_provider_quality || {}).provider_quality_score).toFixed(1)} | 24h {safeNumber((rollingProviderDataQualityMemory?.recent_24h_provider_quality || {}).provider_quality_score).toFixed(1)}</div>
            <div>Posture blockers: {(dataEnvironmentPosture?.posture_blockers || []).join(', ') || "none"}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Macro Regime Awareness</div>
            <div>Current regime: {String(macroRegimeAwareness?.current_macro_regime || "neutral")}</div>
            <div>Macro confidence: {safeNumber(macroRegimeAwareness?.macro_regime_confidence).toFixed(1)}</div>
            <div>Environment tier: {String(macroRegimeAwareness?.macro_environment_tier || "mixed")}</div>
            <div>Risk posture: {String(macroRegimeAwareness?.risk_posture || "balanced")}</div>
            <div>Volatility state: {String(macroRegimeAwareness?.volatility_state || "unknown")}</div>
            <div>Trend state: {String(macroRegimeAwareness?.trend_state || "unknown")}</div>
            <div>Macro adaptation score: {safeNumber(macroRegimeAwareness?.macro_adaptation_score).toFixed(1)}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Sector / Theme Rotation</div>
            <div>Rotation intensity: {safeNumber(sectorThemeRotationIntelligence?.sector_rotation_intensity_score).toFixed(1)}</div>
            <div>Theme crowding: {safeNumber(sectorThemeRotationIntelligence?.theme_crowding_score).toFixed(1)}</div>
            <div>Rotation label: {String(sectorThemeRotationIntelligence?.theme_rotation_label || "neutral")}</div>
            <div>Sector setup contexts: {safeNumber(sectorThemeRotationIntelligence?.sector_setup_context_count)}</div>
            <div>Leaders tracked: {(sectorThemeRotationIntelligence?.sector_leaders || []).length}</div>
            <div>Laggards tracked: {(sectorThemeRotationIntelligence?.sector_laggards || []).length}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>External Context Classification</div>
            <div>External score: {safeNumber(externalContextClassification?.external_context_score).toFixed(1)}</div>
            <div>Environment tier: {String(externalContextClassification?.external_environment_tier || "caution")}</div>
            <div>Context confidence: {safeNumber(externalContextClassification?.external_context_confidence).toFixed(1)}</div>
            <div>Favorable families: {(externalContextClassification?.favorable_context_families || []).length}</div>
            <div>Caution families: {(externalContextClassification?.caution_context_families || []).length}</div>
            <div>Hostile families: {(externalContextClassification?.hostile_context_families || []).length}</div>
            <div>Environment mismatch count: {safeNumber(externalContextClassification?.environment_mismatch_count)}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Forecasting & Self-Check</div>
            <div>Forecast quality score: {safeNumber(forecastingQualityRefinement?.forecast_quality_score).toFixed(1)}</div>
            <div>Forecast stability score: {safeNumber(forecastingQualityRefinement?.forecast_stability_score).toFixed(1)}</div>
            <div>Forecast outlook tier: {String(forecastingQualityRefinement?.forecast_outlook_tier || "unstable")}</div>
            <div>Disagreement-aware hint: {String(forecastingQualityRefinement?.disagreement_aware_forecast_hint || "low_confidence_forecast").replaceAll("_", " ")}</div>
            <div>Calibration score: {safeNumber(confidenceCalibration?.confidence_calibration_score).toFixed(1)}</div>
            <div>Calibration label: {String(confidenceCalibration?.confidence_realism_label || "insufficient_evidence").replaceAll("_", " ")}</div>
            <div>Overconfidence detected: {String(Boolean(confidenceCalibration?.overconfidence_detected))}</div>
            <div>Contradictions: {safeNumber(contradictionSelfCheck?.contradiction_count)} / severity {safeNumber(contradictionSelfCheck?.contradiction_severity).toFixed(1)}</div>
            <div>Coherence / integrity: {safeNumber(crossLayerDecisionCoherence?.coherence_score).toFixed(1)} / {safeNumber(crossLayerDecisionCoherence?.decision_integrity_score).toFixed(1)}</div>
            <div>Posture confidence: {safeNumber(crossLayerDecisionCoherence?.final_recommendation_posture_confidence).toFixed(1)}</div>
            <div>Blocking factors: {(autonomousExplanationRefinement?.what_is_blocking_stronger_action || []).length}</div>
            <div>Refinement priorities: {(autonomousExplanationRefinement?.refinement_priorities || []).length}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Provider / Data Reliability</div>
            <div>Provider success rate: {safeNumber(providerBlendingReliability?.provider_success_rate_percent).toFixed(1)}%</div>
            <div>Provider blend score: {safeNumber(providerBlendingReliability?.provider_blend_score).toFixed(1)}</div>
            <div>Retry discipline score: {safeNumber(providerBlendingReliability?.retry_discipline_score).toFixed(1)}</div>
            <div>Cache fallback ratio: {safeNumber(providerBlendingReliability?.fallback_to_cache_ratio_percent).toFixed(1)}%</div>
            <div>Quote freshness score: {safeNumber(quoteHealthStaleRecovery?.quote_freshness_quality_score).toFixed(1)}</div>
            <div>Stale-data risk score: {safeNumber(quoteHealthStaleRecovery?.stale_data_risk_score).toFixed(1)}</div>
            <div>Quote recovery reason: {String(quoteHealthStaleRecovery?.quote_recovery_reason || "unknown")}</div>
            <div>Crypto continuity score: {safeNumber(cryptoCoverageReliability?.crypto_trust_continuity_score).toFixed(1)}</div>
            <div>Crypto recovery mode: {String(cryptoCoverageReliability?.crypto_recovery_mode || "degraded")}</div>
            <div>Crypto degraded reasons: {(cryptoCoverageReliability?.crypto_degraded_reasons || []).length}</div>
            <div>Metadata quality score: {safeNumber(metadataDataQualityEnrichment?.metadata_quality_score).toFixed(1)}</div>
            <div>Runtime recovery score: {safeNumber(failureVisibilityRecovery?.runtime_recovery_score).toFixed(1)}</div>
            <div>Failure blocker count: {(failureVisibilityRecovery?.blocking_reasons || []).length}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Performance / Scalability</div>
            <div>Rankings builds/cache hits: {safeNumber(performanceOptimizationSuite?.rankings_build_count)} / {safeNumber(performanceOptimizationSuite?.rankings_cache_hit_count)}</div>
            <div>Rankings cache hit rate: {safeNumber(performanceOptimizationSuite?.rankings_cache_hit_rate_percent).toFixed(1)}%</div>
            <div>Top-buys builds/cache hits: {safeNumber(performanceOptimizationSuite?.top_buys_build_count)} / {safeNumber(performanceOptimizationSuite?.top_buys_cache_hit_count)}</div>
            <div>Top-buys cache hit rate: {safeNumber(performanceOptimizationSuite?.top_buys_cache_hit_rate_percent).toFixed(1)}%</div>
            <div>Learning builds/cache hits: {safeNumber(performanceOptimizationSuite?.learning_insights_build_count)} / {safeNumber(performanceOptimizationSuite?.learning_insights_cache_hit_count)}</div>
            <div>Learning cache hit rate: {safeNumber(performanceOptimizationSuite?.learning_insights_cache_hit_rate_percent).toFixed(1)}%</div>
            <div>Endpoint efficiency score: {safeNumber(performanceOptimizationSuite?.endpoint_efficiency_score).toFixed(1)}</div>
            <div>Cache quality score: {safeNumber(performanceOptimizationSuite?.cache_quality_score).toFixed(1)}</div>
            <div>Refresh efficiency score: {safeNumber(performanceOptimizationSuite?.learning_refresh_efficiency_score).toFixed(1)}</div>
            <div>Worker interval/replay interval: {safeNumber(performanceOptimizationSuite?.worker_interval_seconds)}s / {safeNumber(performanceOptimizationSuite?.replay_interval_seconds)}s</div>
            <div>Last learning refresh age: {performanceOptimizationSuite?.last_learning_refresh_age_seconds ?? "n/a"}s</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Contextual Hard vs Soft</div>
            <div>Setup-regime policies: {Object.keys(contextualHardSoftPolicy?.setup_regime || {}).length}</div>
            <div>Persona-regime policies: {Object.keys(contextualHardSoftPolicy?.persona_regime || {}).length}</div>
            <div>Setup-cap policies: {Object.keys(contextualHardSoftPolicy?.setup_cap_bucket || {}).length}</div>
            <div>Soft suppression contexts: {safeNumber(policyAdaptation?.contextual_soft_suppression_count)}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>A/B Promotion Diagnostics</div>
            <div>A/B ranked: {abRankedCount.toFixed(0)}</div>
            <div>A/B promoted strong buys: {abPromotedCount.toFixed(0)} ({abConversionRate.toFixed(1)}%)</div>
            <div>A/B blocked: {abBlockedCount.toFixed(0)}</div>
            <div>High-grade holds: {highGradeHoldCount.toFixed(0)}</div>
            <div>High-grade hold rate: {highGradeHoldRatePercent === null ? "n/a" : `${highGradeHoldRatePercent.toFixed(1)}%`}</div>
            <div>False negatives: {falseNegativeABCount.toFixed(0)} | False positives: {falsePositiveABCount.toFixed(0)}</div>
            <div>Efficiency / integrity: {promotionEfficiencyScore === null ? "n/a" : promotionEfficiencyScore.toFixed(1)} / {promotionIntegrityScore === null ? "n/a" : promotionIntegrityScore.toFixed(1)}</div>
            <div>Threshold tightness: {thresholdTightnessLabel}</div>
            <div>Top blockers: {topPromotionBlockers || "none"}</div>
            <div>C soft promoted from A/B blocks: {cSoftPromotedDueToABBlocks.toFixed(0)}</div>
            <div>C soft due to true A/B unavailability: {cSoftTrueUnavailableCount.toFixed(0)}</div>
            <div>Stronger A/B replacements: {strongerReplacementCount.toFixed(0)}</div>
            <div>C-soft overuse: {safeNumber(cSoftFallbackTuning?.c_soft_overuse_score).toFixed(1)} | fill pressure {safeNumber(cSoftFallbackTuning?.c_soft_fill_pressure).toFixed(1)}%</div>
            <div>Decision engine score: {safeNumber(decisionEngineSummary?.final_action_score).toFixed(1)} (data {safeNumber(decisionEngineSummary?.data_stage_score).toFixed(1)}, runtime {safeNumber(decisionEngineSummary?.runtime_stage_score).toFixed(1)}, candidate {safeNumber(decisionEngineSummary?.candidate_stage_score).toFixed(1)}, promotion {safeNumber(decisionEngineSummary?.promotion_stage_score).toFixed(1)})</div>
            <div>Action environment: {String(decisionEnvironmentPosture?.stocks_current_action_environment || "degraded")} / {String(decisionEnvironmentPosture?.crypto_current_action_environment || "degraded")} | actionability {safeNumber(decisionEnvironmentPosture?.environment_actionability_score).toFixed(1)}</div>
            <div>Environment eligibility: strong-buy {String(Boolean(decisionEnvironmentPosture?.strong_buy_environment_eligible))}, watchlist-only {String(Boolean(decisionEnvironmentPosture?.watchlist_only_due_to_environment))}, no-trade {String(Boolean(decisionEnvironmentPosture?.no_trade_due_to_environment))}</div>
            <div>Actionability boundaries: strong {safeNumber(actionabilityBoundary?.strong_actionable_count).toFixed(0)}, soft {safeNumber(actionabilityBoundary?.soft_actionable_count).toFixed(0)}, watchlist {safeNumber(actionabilityBoundary?.watchlist_count).toFixed(0)}, no-trade {safeNumber(actionabilityBoundary?.no_trade_count).toFixed(0)}, blocked {safeNumber(actionabilityBoundary?.blocked_count).toFixed(0)}</div>
            <div>Conversion tuning score: {safeNumber(productionConversionTuning?.strong_buy_conversion_tuning_score).toFixed(1)} | hold bias {safeNumber(productionConversionTuning?.high_grade_hold_bias_score).toFixed(1)}</div>
            <div>Release blockers/enablers: {(productionConversionTuning?.strongest_release_blockers || []).slice(0, 2).join(", ") || "n/a"} / {(productionConversionTuning?.strongest_release_enablers || []).slice(0, 2).join(", ") || "n/a"}</div>
            <div>No-strong reasons: {(noStrongBuyDiagnostics?.no_strong_buy_primary_reasons || []).slice(0, 3).join(", ") || "n/a"}</div>
            <div>What creates strong buys now: {(noStrongBuyDiagnostics?.what_would_create_a_strong_buy_now || []).slice(0, 3).join(", ") || "n/a"}</div>
            <div>Hero release controls: candidates {safeNumber(heroReleaseControls?.hero_release_candidate_count).toFixed(0)}, promoted {safeNumber(heroReleaseControls?.hero_release_promoted_count).toFixed(0)}, blocked {safeNumber(heroReleaseControls?.hero_release_blocked_count).toFixed(0)}, quality {safeNumber(heroReleaseControls?.hero_release_quality_score).toFixed(1)}</div>
            <div>Secondary split: near-strong {safeNumber(secondaryBucketSeparation?.near_strong_buy_count).toFixed(0)}, true-soft {safeNumber(secondaryBucketSeparation?.true_soft_buy_count).toFixed(0)}, A/B secondary {safeNumber(secondaryBucketSeparation?.a_b_in_secondary_count).toFixed(0)}, C-only secondary {safeNumber(secondaryBucketSeparation?.c_only_in_secondary_count).toFixed(0)}</div>
            <div>Secondary integrity: {safeNumber(secondaryBucketSeparation?.secondary_bucket_integrity_score).toFixed(1)} | misalignment {safeNumber(heroSecondaryAlignment?.hero_release_misalignment_score).toFixed(1)} | consistency {safeNumber(heroSecondaryAlignment?.hero_release_consistency_score).toFixed(1)}</div>
            <div>Over-strict blockers: {(actionabilityTuningSuggestions?.top_over_strict_blockers || []).join(", ") || "n/a"}</div>
            <div>Under-strict blockers: {(actionabilityTuningSuggestions?.top_under_strict_blockers || []).join(", ") || "n/a"}</div>
            <div>Safest relax targets: {(actionabilityTuningSuggestions?.safest_thresholds_to_relax || []).join(", ") || "n/a"}</div>
            <div>A/B over C priority active: {String(Boolean(promotionSummary?.a_b_over_c_priority_active))}</div>
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Hold-Time Intelligence</div>
            <div>Avg hold (global): {safeNumber(holdTimePolicyHints?.global_avg_time_to_exit_seconds).toFixed(0)}s</div>
            <div>Median hold (global): {safeNumber(holdTimePolicyHints?.global_median_time_to_exit_seconds).toFixed(0)}s</div>
            <div>Faster-review contexts: {safeNumber(holdTimePolicyHints?.faster_review_context_count)}</div>
            <div>Patient-hold contexts: {safeNumber(holdTimePolicyHints?.patient_hold_context_count)}</div>
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "12px" }}>
        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Entry Timing & Conviction</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Entry timing score: {safeNumber(entryTimingHints?.entry_timing_score).toFixed(1)}</div>
            <div>Recommended mode: {String(entryTimingHints?.recommended_entry_mode || "confirmation_needed").replaceAll("_", " ")}</div>
            <div>Immediate entry rate: {fmtPct(entryTimingHints?.immediate_entry_rate_percent)}</div>
            <div>Confirmation-needed rate: {fmtPct(entryTimingHints?.confirmation_needed_rate_percent)}</div>
            <div>Scale-in cautious rate: {fmtPct(entryTimingHints?.scale_in_cautious_rate_percent)}</div>
            <div>Skip-despite-ranking rate: {fmtPct(entryTimingHints?.skip_despite_ranking_rate_percent)}</div>
            <div>Contextual timing policies tracked: {entryTimingContextsTracked}</div>
            <div>Conviction policy confidence: {String(convictionFramework?.policy_confidence || "low")}</div>
            <div>Soft-buy treatment: {String(convictionFramework?.recommended_soft_buy_treatment || "keep").replaceAll("_", " ")}</div>
            <div>Conviction action map: {convictionActionTierCount} tiers ({String(convictionActionMapping?.policy_confidence || "low")})</div>
            <div>Entry execution mode: {String(entryExecutionPolicy?.recommended_mode || "confirmation_required").replaceAll("_", " ")}</div>
            <div>Entry execution policy confidence: {String(entryExecutionPolicy?.policy_confidence || "low")}</div>
            <div>Execution posture: {String(contextualExecutionRefinement?.recommended_execution_posture || "balanced")} ({safeNumber(contextualExecutionRefinement?.execution_refinement_score).toFixed(1)})</div>
            <div>Execution evidence count: {safeNumber(contextualExecutionRefinement?.execution_evidence_count)}</div>
            <div>Top wait contexts: {(contextualExecutionRefinement?.top_wait_contexts || []).length} | immediate contexts: {(contextualExecutionRefinement?.top_immediate_contexts || []).length}</div>
            <div>Elite tier trades: {safeNumber((convictionTierPerf?.elite || {}).trade_count)} | WR {fmtPct((convictionTierPerf?.elite || {}).win_rate)}</div>
            <div>Strong tier trades: {safeNumber((convictionTierPerf?.strong || {}).trade_count)} | WR {fmtPct((convictionTierPerf?.strong || {}).win_rate)}</div>
          </div>
        </div>

        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Exit Policy Quality</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Early exits: {fmtPct(exitPolicyHints?.early_exit_rate_percent)}</div>
            <div>Late exits: {fmtPct(exitPolicyHints?.late_exit_rate_percent)}</div>
            <div>Missed profit rate: {fmtPct(exitPolicyHints?.missed_profit_rate_percent)}</div>
            <div>Capture ratio: {fmtPct(exitPolicyHints?.avg_capture_ratio_percent)}</div>
            <div>Exit quality score: {safeNumber(exitPolicyHints?.exit_quality_score).toFixed(1)} ({String(exitPolicyHints?.exit_quality_trend || "unknown")})</div>
            <div>Entry edge score: {safeNumber(entryQualityHints?.entry_edge_score).toFixed(2)} ({String(entryQualityHints?.entry_quality_trend || "unknown")})</div>
            <div>Trailing pullback threshold: {safeNumber(exitPolicyHints?.trailing_pullback_exit_threshold_percent).toFixed(2)}%</div>
            <div>Stop-loss threshold: {safeNumber(exitPolicyHints?.stop_loss_threshold_percent).toFixed(2)}%</div>
            <div>Best exit reason: {String(((exitTimingPatterns?.best_exit_reasons || [])[0] || {}).exit_reason || "n/a")}</div>
            <div>Worst exit reason: {String(((exitTimingPatterns?.worst_exit_reasons || [])[0] || {}).exit_reason || "n/a")}</div>
            <div>Contextual exit contexts: {contextualExitSetupCount} setup-regime, {contextualExitPersonaCount} persona-regime</div>
            <div>Contextual hold contexts: {contextualHoldSetupCount} setup-regime, {contextualHoldPersonaCount} persona-regime</div>
            <div>Lifecycle faster-review states: {(lifecycleStateHints?.faster_review_states || []).join(", ") || "none"}</div>
            <div>Lifecycle patient states: {(lifecycleStateHints?.patient_states || []).join(", ") || "none"}</div>
            <div>Patient/Fast review default: {String(patientFastReviewPolicy?.recommended_default_review_mode || "balanced_review").replaceAll("_", " ")}</div>
            <div>Review policy score: {safeNumber(patientFastReviewPolicy?.review_policy_score).toFixed(1)}</div>
            <div>Invalidation score: {safeNumber(deteriorationInvalidationHints?.invalidation_score).toFixed(1)}</div>
            <div>Weak follow-through rate: {fmtPct(deteriorationInvalidationHints?.weak_follow_through_rate_percent)}</div>
            <div>Immediate failure rate: {fmtPct(deteriorationInvalidationHints?.immediate_failure_rate_percent)}</div>
            <div>Follow-through failure score: {safeNumber(followThroughFailureHints?.failure_score).toFixed(1)}</div>
            <div>Deteriorating setup WR: {fmtPct((lifecycleStates?.deteriorating_setup || {}).win_rate)}</div>
            <div>Healthy continuation WR: {fmtPct((followThroughPatterns?.healthy_continuation || {}).win_rate)}</div>
            <div>Immediate failure WR: {fmtPct((followThroughPatterns?.immediate_failure || {}).win_rate)}</div>
            <div>Lifecycle review urgency: {safeNumber(advancedLifecycle?.review_urgency_score).toFixed(1)} ({String(advancedLifecycle?.review_urgency_default || "balanced_review").replaceAll("_", " ")})</div>
            <div>Early confirmation vs weak: {fmtPct(advancedLifecycle?.early_confirmation_rate_percent)} / {fmtPct(advancedLifecycle?.weak_confirmation_rate_percent)}</div>
            <div>Management realism: {safeNumber(tradeManagementRealism?.realism_score).toFixed(1)} ({String(tradeManagementRealism?.recommended_management_mode || "balanced_review").replaceAll("_", " ")})</div>
            <div>Escalation score: {safeNumber(tradeManagementRealism?.review_escalation_score).toFixed(1)} | Decay risk: {safeNumber(tradeManagementRealism?.conviction_decay_risk_score).toFixed(1)}</div>
            <div>Policy reason: {String(exitPolicyHints?.policy_reason || "insufficient_data")}</div>
          </div>
        </div>
        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Sizing & Regime Intelligence</h3>
          <div style={{ display: "grid", gap: "6px", fontSize: 12 }}>
            <div>Stocks size tiers: {JSON.stringify(stocksSizing?.size_tier_counts || {})}</div>
            <div>Crypto size tiers: {JSON.stringify(cryptoSizing?.size_tier_counts || {})}</div>
            <div>Stocks risk classes: {JSON.stringify(stocksSizing?.risk_class_counts || {})}</div>
            <div>Crypto risk classes: {JSON.stringify(cryptoSizing?.risk_class_counts || {})}</div>
            <div>Sizing policy confidence: {String(positionSizingPolicy?.policy_confidence || "low")}</div>
            <div>Contextual sizing confidence: {safeNumber(positionSizingPolicy?.contextual_confidence_score).toFixed(1)} ({contextualSizingCount} contexts)</div>
            <div>Sizing policy reason: {String(positionSizingPolicy?.policy_reason || "insufficient_data")}</div>
            <div>Regime policy keys: {regimePolicyLabel}</div>
            <div>Persona policy keys: {personaPolicyLabel}</div>
            <div>Setup taxonomy tracked: {setupTaxonomyTrackedCount}</div>
            <div>Policy adaptation: {String(policyAdaptation?.hard_vs_soft_action || "keep").replaceAll("_", " ")}</div>
            <div>Contextual soft suppression: {safeNumber(policyAdaptation?.contextual_soft_suppression_count)} contexts</div>
            <div>Contextual faster-review: {safeNumber(policyAdaptation?.contextual_hold_faster_review_count)}</div>
            <div>Contextual patient-hold: {safeNumber(policyAdaptation?.contextual_hold_patient_count)}</div>
            <div>Entry execution confidence: {String(policyAdaptation?.entry_execution_policy_confidence || "low")}</div>
            <div>Entry execution skip contexts: {safeNumber(policyAdaptation?.entry_execution_skip_context_count)}</div>
            <div>Conviction action mappings: {safeNumber(policyAdaptation?.conviction_action_mapping_count)}</div>
            <div>Deterioration high-risk contexts: {safeNumber(policyAdaptation?.deterioration_high_risk_context_count)}</div>
            <div>Follow-through failure contexts: {safeNumber(policyAdaptation?.follow_through_failure_context_count)}</div>
            <div>Lifecycle high-risk states: {safeNumber(policyAdaptation?.advanced_lifecycle_high_risk_count)}</div>
            <div>Contextual execution evidence: {safeNumber(policyAdaptation?.contextual_execution_evidence_count)}</div>
            <div>Trade realism score: {safeNumber(policyAdaptation?.trade_management_realism_score).toFixed(1)}</div>
            <div>Trade escalation score: {safeNumber(policyAdaptation?.trade_management_escalation_score).toFixed(1)}</div>
            <div>Trade quality score: {safeNumber(tradeQualitySelectivitySuite?.expectancy_score).toFixed(1)} | PF {safeNumber(tradeQualitySelectivitySuite?.profit_factor).toFixed(2)}</div>
            <div>Quality floor: {safeNumber(tradeQualitySelectivitySuite?.min_quality_score_floor, 62).toFixed(1)} | min prob {safeNumber(tradeQualitySelectivitySuite?.strong_min_probability, 0.61).toFixed(3)}</div>
            <div>Weak cohort counts: setup {safeNumber((tradeQualitySelectivitySuite?.weak_cohort_counts || {}).setups)}, regime {safeNumber((tradeQualitySelectivitySuite?.weak_cohort_counts || {}).regimes)}, persona {safeNumber((tradeQualitySelectivitySuite?.weak_cohort_counts || {}).personas)}</div>
            <div>Overtrading guard: {String(Boolean(tradeQualitySelectivitySuite?.overtrading_guard_active))} | max context repeat {safeNumber(tradeQualitySelectivitySuite?.max_low_conviction_context_repeat, 2).toFixed(0)}</div>
            <div>Portfolio concentration index: {safeNumber(portfolioIntelligenceSuite?.sector_concentration_index).toFixed(1)}</div>
            <div>Duplicate-theme score: {safeNumber(portfolioIntelligenceSuite?.duplicate_theme_exposure_score).toFixed(1)}</div>
            <div>Overlap risk score: {safeNumber(overlapRiskControls?.overlap_risk_score).toFixed(1)}</div>
            <div>Allocation quality score: {safeNumber(capitalAllocationIntelligence?.allocation_quality_score).toFixed(1)}</div>
            <div>Allocation mode: {String(capitalAllocationIntelligence?.allocation_mode || "neutral_fallback").replaceAll("_", " ")}</div>
            <div>Total suggested allocation: {safeNumber(capitalAllocationIntelligence?.total_suggested_allocation_percent).toFixed(1)}%</div>
            <div>Paper-to-live tier: {String(paperToLiveGuardrails?.paper_to_live_tier || "not_live_ready").replaceAll("_", " ")}</div>
            <div>Guardrail checks: evidence {String(Boolean(paperToLiveGuardrails?.minimum_evidence_passed))}, confidence {String(Boolean(paperToLiveGuardrails?.confidence_floor_passed))}, quote {String(Boolean(paperToLiveGuardrails?.quote_health_passed))}</div>
            <div>Action tiers: live {safeNumber(actionTierCounts?.live_candidate)} | high-conviction {safeNumber(actionTierCounts?.high_conviction_live_candidate)} | blocked {safeNumber(actionTierCounts?.blocked_degraded)}</div>
            <div>Decision handshake: {String(actionTierControls?.decision_handshake_state || "blocked").replaceAll("_", " ")}</div>
            <div>Execution handoff: {String(executionHandoffControls?.handoff_state || "observe_only").replaceAll("_", " ")}</div>
            <div>Operator confidence: {String(operatorGoNoGo?.confidence_label || "low")} ({safeNumber(operatorGoNoGo?.confidence_score).toFixed(1)})</div>
            <div>Market ranking/sizing mult: {safeNumber(marketConditionAdaptation?.ranking_multiplier, 1).toFixed(3)} / {safeNumber(marketConditionAdaptation?.sizing_multiplier, 1).toFixed(3)}</div>
            <div>Lifecycle review mult: {safeNumber(marketConditionAdaptation?.lifecycle_review_multiplier, 1).toFixed(3)} | Deterioration tolerance: {safeNumber(marketConditionAdaptation?.deterioration_tolerance_multiplier, 1).toFixed(3)}</div>
            <div>Follow-through expectation: {safeNumber(marketConditionAdaptation?.follow_through_expectation_score).toFixed(1)} | Adapt confidence: {String(marketConditionAdaptation?.adaptation_confidence || "low")}</div>
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Trade Management Patterns</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "10px", fontSize: 12 }}>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Longer-Hold Contexts</div>
            {(contextualTradeMgmt?.best_longer_hold_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`blh-${idx}`}>{r.scope}:{r.context_key} | sample {safeNumber(r.sample_size)} | bias {safeNumber(r.hold_bias).toFixed(2)}</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Best Quicker-Exit Contexts</div>
            {(contextualTradeMgmt?.best_quicker_exit_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`bqe-${idx}`}>{r.scope}:{r.context_key} | sample {safeNumber(r.sample_size)} | bias {safeNumber(r.hold_bias).toFixed(2)}</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Strongest Sizing Contexts</div>
            {(contextualTradeMgmt?.strongest_sizing_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`ssc-${idx}`}>{r.scope}:{r.context_key} | WR {fmtPct(r.win_rate)} | {safeNumber(r.winsorized_avg_return).toFixed(4)}%</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Soft-Buy Suppression Contexts</div>
            {(contextualTradeMgmt?.soft_buy_suppression_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`sbs-${idx}`}>{r.scope}:{r.context_key} | {String(r.action)} | mult {safeNumber(r.soft_buy_multiplier, 1).toFixed(3)}</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Execution Wait Contexts</div>
            {(contextualExecutionRefinement?.top_wait_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`ewc-${idx}`}>{r.scope}:{r.context_key} | {String(r.entry_mode).replaceAll("_", " ")} | sample {safeNumber(r.sample_size)}</div>
            ))}
          </div>
          <div>
            <div style={{ color: "#9fb1cc", marginBottom: 6 }}>Execution Immediate Contexts</div>
            {(contextualExecutionRefinement?.top_immediate_contexts || []).slice(0, 3).map((r, idx) => (
              <div key={`eic-${idx}`}>{r.scope}:{r.context_key} | sample {safeNumber(r.sample_size)} | score {safeNumber(r.entry_timing_score).toFixed(1)}</div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Key Insights</h3>
        <ol style={{ margin: 0, paddingLeft: 16 }}>
          {keyTakeaways.map((line, idx) => (
            <li key={`insight-${idx}`} style={{ marginBottom: 6, fontSize: 13 }}>{line}</li>
          ))}
        </ol>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Segment Learning</h3>
        {segmentRows.length === 0 ? (
          <div style={{ color: "#8ea1c3", fontSize: 12 }}>
            More history needed before segment-level learning is reliable.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ color: "#9fb1cc" }}>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Segment</th>
                <th style={{ textAlign: "left", padding: "6px 8px" }}>Key</th>
                <th style={{ textAlign: "right", padding: "6px 8px" }}>Sample</th>
                <th style={{ textAlign: "right", padding: "6px 8px" }}>Good</th>
                <th style={{ textAlign: "right", padding: "6px 8px" }}>Bad</th>
              </tr>
            </thead>
            <tbody>
              {segmentRows.map((r, idx) => (
                <tr key={`${r.segmentType}-${r.segmentKey}-${idx}`}>
                  <td style={{ padding: "6px 8px", borderTop: "1px solid #1d2533" }}>{r.segmentType}</td>
                  <td style={{ padding: "6px 8px", borderTop: "1px solid #1d2533" }}>{r.segmentKey}</td>
                  <td style={{ padding: "6px 8px", borderTop: "1px solid #1d2533", textAlign: "right" }}>{r.sample}</td>
                  <td style={{ padding: "6px 8px", borderTop: "1px solid #1d2533", textAlign: "right" }}>{r.good}</td>
                  <td style={{ padding: "6px 8px", borderTop: "1px solid #1d2533", textAlign: "right" }}>{r.bad}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      </>
      ) : null}

      <div style={{ ...panelStyle, fontSize: 12, color: "#9fb1cc" }}>
        Trusted output check: stocks={stocksFinal}, crypto={cryptoFinal}, all_top_trusted_for_buys={String(allTrusted)}
      </div>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontSize: 13, color: "#9fb1cc" }}>Advanced diagnostics (debug)</summary>
        <div style={{ marginTop: 8 }}>
          <button
            type="button"
            onClick={() => setShowDebug((v) => !v)}
            style={{
              background: "#1a2740",
              color: "#dce7ff",
              border: "1px solid #344b73",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.2rem 0.5rem",
              cursor: "pointer",
              width: "fit-content",
            }}
          >
            {showDebug ? "Hide Raw JSON" : "Show Raw JSON"}
          </button>
          {showDebug ? (
            <pre
              style={{
                marginTop: "0.5rem",
                maxHeight: "240px",
                overflow: "auto",
                background: "#0b1320",
                border: "1px solid #22314c",
                borderRadius: "6px",
                padding: "0.5rem",
                color: "#cddbf5",
                fontSize: "0.7rem",
              }}
            >
              {JSON.stringify(
                {
                  learning_insights: learningInsights,
                  paper_performance: paper,
                  model_status: model,
                  system_status: {
                    live_buy_universe_size: systemStatus?.live_buy_universe_size,
                    live_buy_valid_quote_count: systemStatus?.live_buy_valid_quote_count,
                    tier1_trusted_quote_count: systemStatus?.tier1_trusted_quote_count,
                  },
                },
                null,
                2
              )}
            </pre>
          ) : null}
        </div>
      </details>
    </div>
  );
}
