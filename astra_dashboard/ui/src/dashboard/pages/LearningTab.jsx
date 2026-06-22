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

function statusLabel(value, fallback = "INSUFFICIENT EVIDENCE") {
  const text = String(value || fallback).replaceAll("_", " ").toUpperCase();
  return text;
}

function metricDisplay(value, available = true, digits = 2, suffix = "") {
  if (!available || value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "insufficient evidence";
  }
  return `${safeNumber(value).toFixed(digits)}${suffix}`;
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

export default function LearningTab({ compact = false }) {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [loading, setLoading] = useState(false);
  const [lastFetchAt, setLastFetchAt] = useState("");
  const [fetchError, setFetchError] = useState("");
  const [showDebug, setShowDebug] = useState(false);
  const [showAdvancedSections, setShowAdvancedSections] = useState(false);
  const [showAdaptiveExitDetails, setShowAdaptiveExitDetails] = useState(false);
  const [showPortfolioDiversificationDetails, setShowPortfolioDiversificationDetails] = useState(false);
  const [showProfitExplorationDetails, setShowProfitExplorationDetails] = useState(false);
  const [showMarketCalendarDetails, setShowMarketCalendarDetails] = useState(false);
  const [showBroadUniverseDetails, setShowBroadUniverseDetails] = useState(false);
  const [showTradeLifecycleExcursionDetails, setShowTradeLifecycleExcursionDetails] = useState(false);
  const [showAdaptiveProfitCaptureDetails, setShowAdaptiveProfitCaptureDetails] = useState(false);
  const [showProfitCapturePeakDecayValidationDetails, setShowProfitCapturePeakDecayValidationDetails] = useState(false);
  const [showVirtualPaperConvergenceDetails, setShowVirtualPaperConvergenceDetails] = useState(false);
  const [showAcceleratedSymbolLearningDetails, setShowAcceleratedSymbolLearningDetails] = useState(false);
  const [showRealisticShadowLabDetails, setShowRealisticShadowLabDetails] = useState(false);
  const [showAdaptiveExitV3Details, setShowAdaptiveExitV3Details] = useState(false);
  const [showExitLearningExpansionDetails, setShowExitLearningExpansionDetails] = useState(false);
  const [showMarketContextLearningDetails, setShowMarketContextLearningDetails] = useState(false);
  const [showLearningAccelerationDetails, setShowLearningAccelerationDetails] = useState(false);
  const [showAdaptiveLearningInfrastructureDetails, setShowAdaptiveLearningInfrastructureDetails] = useState(false);
  const [showAdaptiveWorkerActivationDetails, setShowAdaptiveWorkerActivationDetails] = useState(false);
  const [showConfidenceAttributionDetails, setShowConfidenceAttributionDetails] = useState(false);
  const [showContextEvidenceExpansionDetails, setShowContextEvidenceExpansionDetails] = useState(false);
  const [showCatalystThemeNarrativeDetails, setShowCatalystThemeNarrativeDetails] = useState(false);
  const [showDecisionOptimizationDetails, setShowDecisionOptimizationDetails] = useState(false);
  const [showFullOpportunityLifecycleDetails, setShowFullOpportunityLifecycleDetails] = useState(false);
  const [showLongTermMemoryDetails, setShowLongTermMemoryDetails] = useState(false);
  const [showAdaptiveLearningPrioritizationDetails, setShowAdaptiveLearningPrioritizationDetails] = useState(false);
  const [showAutonomousGovernanceDetails, setShowAutonomousGovernanceDetails] = useState(false);
  const [showTradeArchetypeRegimeDetails, setShowTradeArchetypeRegimeDetails] = useState(false);
  const [showReplayCounterfactualDetails, setShowReplayCounterfactualDetails] = useState(false);
  const [showOpportunityCostDetails, setShowOpportunityCostDetails] = useState(false);
  const [showAdvancedLearningIntelligenceDetails, setShowAdvancedLearningIntelligenceDetails] = useState(false);
  const [showBlindSpotDetails, setShowBlindSpotDetails] = useState(false);
  const [showLearningIssueAuditDetails, setShowLearningIssueAuditDetails] = useState(false);
  const [showRemoteRuntimeDetails, setShowRemoteRuntimeDetails] = useState(false);
  const [showExecutionParticipationDetails, setShowExecutionParticipationDetails] = useState(false);
  const [copyStatus, setCopyStatus] = useState("");
  const [endpointStatus, setEndpointStatus] = useState({});
  const [timeline, setTimeline] = useState([]);
  const [data, setData] = useState({
    unifiedLearningDiagnostics: {},
    learningSnapshotFast: {},
    learningInsights: {},
    paper: {},
    paperStatus: {},
    workerStatus: {},
    model: {},
    topBuys: {},
    systemStatus: {},
    portfolioRiskIntel: {},
    observationThroughput: {},
    executionMarketLearning: {},
    autonomousSelfRegulation: {},
    paperThroughputExpansion: {},
    multiHorizonPaperTrading: {},
    adaptiveMarketIntake: {},
    alpacaPaperBroker: {},
    horizonPerformanceDashboard: {},
    dynamicOpportunityWeighting: {},
    opportunityDiscoveryExpansion: {},
    paperOpportunityAllocation: {},
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
      refreshInFlightRef.current = true;
      setLoading(true);
      setFetchError("");
      const hadUsableTopBuys =
        Array.isArray(data?.topBuys?.stocks?.final) && data.topBuys.stocks.final.length > 0;
      const fastResults = [];
      const secondaryResults = [];
      try {
        const primaryBatch = await Promise.all([
          fetchJson("unified_learning_diagnostics", "/api/unified_learning_diagnostics_v1", {}, { timeoutMs: 30000 }),
        ]);
        fastResults.push(...primaryBatch);

        if (showAdvancedSections) {
          const secondaryBatch = await Promise.all([
            fetchJson("learning_snapshot_fast_v1", "/api/learning_snapshot_fast_v1", {}, { timeoutMs: 6000 }),
            fetchJson("paper_performance", "/api/paper_performance", {}, { timeoutMs: 12000 }),
            fetchJson("paper_status", "/api/paper_status", {}, { timeoutMs: 10000 }),
            fetchJson("system_status", "/api/system_status", {}, { timeoutMs: 10000 }),
            fetchJson("model_status", "/api/model_status", {}, { timeoutMs: 10000 }),
            fetchJson("paper_worker_status", "/api/paper_worker_status", {}, { timeoutMs: 10000 }),
            fetchJson("top_buys", "/api/top_buys?buy_mode=balanced", {}, { timeoutMs: 15000 }),
            fetchJson("portfolio_risk_intel", "/api/portfolio_risk_intelligence_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("observation_throughput", "/api/observation_learning_throughput_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("execution_market_learning", "/api/execution_market_learning_expansion_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("autonomous_self_regulation", "/api/autonomous_research_self_regulation_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("paper_throughput_expansion", "/api/paper_autopilot_throughput_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("multi_horizon_paper_trading", "/api/multi_horizon_paper_trading_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("adaptive_market_intake", "/api/adaptive_market_intake_fmp_budget_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("alpaca_paper_broker", "/api/alpaca_paper_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("horizon_performance_dashboard", "/api/horizon_performance_dashboard_v1", {}, { timeoutMs: 8000 }),
            fetchJson("dynamic_opportunity_weighting", "/api/dynamic_opportunity_weighting_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("opportunity_discovery_expansion", "/api/opportunity_discovery_expansion_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("edge_development", "/api/edge_development_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("trade_management_portfolio", "/api/trade_management_portfolio_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("adaptive_learning_infrastructure", "/api/adaptive_learning_infrastructure_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("replay_lifecycle_expectancy", "/api/replay_lifecycle_expectancy_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("regime_execution_survivability", "/api/regime_execution_survivability_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("market_session_execution_timing", "/api/market_session_execution_timing_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("paper_opportunity_allocation", "/api/paper_opportunity_allocation_status_v1", {}, { timeoutMs: 8000 }),
            fetchJson("learning_insights", "/api/learning_insights", {}, { timeoutMs: 25000 }),
          ]);
          secondaryResults.push(...secondaryBatch);
        }
      } finally {
        refreshInFlightRef.current = false;
      }
      if (!mounted) return;

      const results = [...fastResults, ...secondaryResults];
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
      setEndpointStatus(statuses);
      setLoading(false);
      setLastFetchAt(new Date().toISOString());
      if (errors.length > 0) setFetchError(errors.join(" | "));

      const byKey = Object.fromEntries(results.map((r) => [r.key, r]));
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
        const unifiedLearningDiagnostics = selectPayload("unified_learning_diagnostics", prevSafe.unifiedLearningDiagnostics);
        const paper = selectPayload("paper_performance", prevSafe.paper);
        const paperStatus = selectPayload("paper_status", prevSafe.paperStatus);
        const workerStatus = selectPayload("paper_worker_status", prevSafe.workerStatus);
        const model = selectPayload("model_status", prevSafe.model);
        const topBuys = selectPayload("top_buys", prevSafe.topBuys);
        const portfolioRiskIntel = selectPayload("portfolio_risk_intel", prevSafe.portfolioRiskIntel);
        const observationThroughput = selectPayload("observation_throughput", prevSafe.observationThroughput);
        const executionMarketLearning = selectPayload("execution_market_learning", prevSafe.executionMarketLearning);
        const autonomousSelfRegulation = selectPayload("autonomous_self_regulation", prevSafe.autonomousSelfRegulation);
        const paperThroughputExpansion = selectPayload("paper_throughput_expansion", prevSafe.paperThroughputExpansion);
        const multiHorizonPaperTrading = selectPayload("multi_horizon_paper_trading", prevSafe.multiHorizonPaperTrading);
        const adaptiveMarketIntake = selectPayload("adaptive_market_intake", prevSafe.adaptiveMarketIntake);
        const alpacaPaperBroker = selectPayload("alpaca_paper_broker", prevSafe.alpacaPaperBroker);
        const horizonPerformanceDashboard = selectPayload("horizon_performance_dashboard", prevSafe.horizonPerformanceDashboard);
        const dynamicOpportunityWeighting = selectPayload("dynamic_opportunity_weighting", prevSafe.dynamicOpportunityWeighting);
        const opportunityDiscoveryExpansion = selectPayload("opportunity_discovery_expansion", prevSafe.opportunityDiscoveryExpansion);
        const edgeDevelopment = selectPayload("edge_development", prevSafe.edgeDevelopment);
        const tradeManagementPortfolio = selectPayload("trade_management_portfolio", prevSafe.tradeManagementPortfolio);
        const adaptiveLearningInfrastructure = selectPayload("adaptive_learning_infrastructure", prevSafe.adaptiveLearningInfrastructure);
        const replayLifecycleExpectancy = selectPayload("replay_lifecycle_expectancy", prevSafe.replayLifecycleExpectancy);
        const regimeExecutionSurvivability = selectPayload("regime_execution_survivability", prevSafe.regimeExecutionSurvivability);
        const marketSessionExecutionTiming = selectPayload("market_session_execution_timing", prevSafe.marketSessionExecutionTiming);
        const paperOpportunityAllocation = selectPayload("paper_opportunity_allocation", prevSafe.paperOpportunityAllocation);
        const systemStatus = selectPayload("system_status", prevSafe.systemStatus);
        const learningSnapshotFast = selectPayload("learning_snapshot_fast_v1", prevSafe.learningSnapshotFast);
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

        setTimeline((prevTimeline) => {
          const point = {
            ts: new Date().toLocaleTimeString(),
            winRate: safeNumber((paper?.paper_cohort_trends?.recent || {}).win_rate, paper?.win_rate),
            medianReturn: safeNumber((paper?.paper_cohort_trends?.recent || {}).median_return, paper?.avg_return),
            winsorized: safeNumber((paper?.paper_cohort_trends?.recent || {}).winsorized_avg_return, paper?.avg_return),
            buyConversion: safeNumber(buyConversionEngine?.buy_conversion_score),
            overblocking: safeNumber(buyConversionEngine?.overblocking_score),
            sellAccuracy: safeNumber(buyToPosition?.sell_signal_accuracy_score),
          };
          return [...prevTimeline, point].slice(-36);
        });

        return {
          unifiedLearningDiagnostics,
          learningSnapshotFast,
          learningInsights,
          paper,
          paperStatus,
          workerStatus,
          model,
          topBuys,
          systemStatus,
          portfolioRiskIntel,
          observationThroughput,
          executionMarketLearning,
          autonomousSelfRegulation,
          paperThroughputExpansion,
          multiHorizonPaperTrading,
          adaptiveMarketIntake,
          alpacaPaperBroker,
          horizonPerformanceDashboard,
          dynamicOpportunityWeighting,
          opportunityDiscoveryExpansion,
          edgeDevelopment,
          tradeManagementPortfolio,
          adaptiveLearningInfrastructure,
          replayLifecycleExpectancy,
          regimeExecutionSurvivability,
          marketSessionExecutionTiming,
          paperOpportunityAllocation,
        };
      });
    };

    refresh();
    const timer = setInterval(refresh, 15000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [resolvedApiBase, showAdvancedSections]);

  const paper = data.paper || {};
  const unifiedLearningDiagnostics = data.unifiedLearningDiagnostics || {};
  const paperStatus = data.paperStatus || {};
  const horizonCoverageSummary = unifiedLearningDiagnostics?.horizon_coverage_summary || {};
  const multiHorizonAdaptiveLifecycle = unifiedLearningDiagnostics?.multi_horizon_intelligence_adaptive_lifecycle_suite_v1 || {};
  const workerStatus = {
    ...(paperStatus?.worker || {}),
    ...(data.workerStatus || {}),
  };
  const learningInsights = data.learningInsights || {};
  const model = data.model || {};
  const topBuys = data.topBuys || {};
  const systemStatus = data.systemStatus || {};
  const portfolioRiskIntel = data.portfolioRiskIntel || {};
  const observationThroughput = data.observationThroughput || {};
  const executionMarketLearning = data.executionMarketLearning || {};
  const autonomousSelfRegulation = data.autonomousSelfRegulation || {};
  const paperThroughputExpansion = data.paperThroughputExpansion || {};
  const multiHorizonPaperTrading = data.multiHorizonPaperTrading || {};
  const adaptiveMarketIntake = data.adaptiveMarketIntake || {};
  const alpacaPaperBroker = data.alpacaPaperBroker || {};
  const horizonPerformanceDashboard = data.horizonPerformanceDashboard || {};
  const dynamicOpportunityWeighting = data.dynamicOpportunityWeighting || {};
  const opportunityDiscoveryExpansion = data.opportunityDiscoveryExpansion || {};
  const edgeDevelopment = data.edgeDevelopment || {};
  const tradeManagementPortfolio = data.tradeManagementPortfolio || {};
  const adaptiveLearningInfrastructure = data.adaptiveLearningInfrastructure || {};
  const replayLifecycleExpectancy = data.replayLifecycleExpectancy || {};
  const regimeExecutionSurvivability = data.regimeExecutionSurvivability || {};
  const marketSessionExecutionTiming = data.marketSessionExecutionTiming || {};
  const paperOpportunityAllocation = data.paperOpportunityAllocation || {};

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
  const learningPayloadSource = String(learningInsights?.learning_payload_source || "unknown");
  const learningPayloadStale = Boolean(learningInsights?.learning_payload_stale);
  const learningPayloadFalseEmptyPrevented = Boolean(
    learningInsights?.learning_payload_false_empty_prevented || learningInsights?.ui_false_empty_guard_active
  );
  const learningPayloadDegradedReason = String(
    firstNonEmpty(learningInsights?.learning_payload_degraded_reason, learningInsights?.ui_false_empty_guard_reason, "")
  );
  const cohortSamples = learningInsights?.cohort_sample_sizes || {};
  const cohortSampleTotal = safeNumber(cohortSamples?.released) + safeNumber(cohortSamples?.paper_ready) + safeNumber(cohortSamples?.blocked_watchlist);
  const learningEvidenceAvailable = learningPayloadHasEvidence(learningInsights) || fullValidClosedCount > 0;
  const snapshotInsufficientEvidence = !learningEvidenceAvailable || (
    cohortSampleTotal <= 0
    && !Boolean(evidenceReadinessSummary?.evidence_ready)
    && !Boolean(evidenceReadinessSummary?.confidence_ready)
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
  const snapshotDegradedLabel = snapshotInsufficientEvidence
    ? (learningPayloadFalseEmptyPrevented ? "last known good (degraded)" : "insufficient current evidence")
    : null;
  const primarySnapshotMetrics = [
    {
      key: "released_wr",
      title: "Current-Engine Released WR",
      subtitle: "How often current released picks are winning.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : fmtPct((learningInsights?.current_engine_outcome_evaluation || {}).released_hero_win_rate),
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(currentEngineWinRate, 58, 47),
    },
    {
      key: "released_gap",
      title: "Released vs Blocked WR Gap",
      subtitle: "Positive means released picks are outperforming blocked/watchlist.",
      value: snapshotInsufficientEvidence ? "Insufficient evidence" : `${releasedVsBlockedWinRateGap >= 0 ? "+" : ""}${releasedVsBlockedWinRateGap.toFixed(2)} pts`,
      tone: snapshotInsufficientEvidence ? "caution" : (releasedVsBlockedWinRateGap >= 2 ? "strong" : (releasedVsBlockedWinRateGap >= 0 ? "mixed" : "weak")),
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
      title: "Runtime & Learning Stability",
      subtitle: "Operational health of runtime + learning refresh cycle.",
      value: snapshotInsufficientEvidence ? (learningPayloadStale ? "Stale snapshot" : "Rebuild pending") : `${runtimeLearningStabilityScore.toFixed(1)}`,
      tone: snapshotInsufficientEvidence ? "caution" : metricTone(runtimeLearningStabilityScore, 70, 55),
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

  const unified = unifiedLearningDiagnostics || {};
  const executive = unified?.executive_snapshot || {};
  const performanceSummary = unified?.performance_summary || {};
  const masterCharts = unified?.master_charts || {};
  const staleStatus = unified?.stale_data_status || {};
  const evidenceStatus = unified?.evidence_maturity_status || {};
  const futureContract = unified?.future_suite_integration_contract || {};
  const advancedStatuses = unified?.advanced_panel_statuses || unified?.advanced_panel_links || {};
  const adaptiveExecutionExitV2 = unified?.adaptive_execution_exit_intelligence_v2 || {};
  const adaptiveExecutionIntelligence = adaptiveExecutionExitV2?.adaptive_execution_intelligence || unified?.adaptive_execution_intelligence || {};
  const exitIntelligenceV2 = adaptiveExecutionExitV2?.exit_intelligence_v2 || unified?.exit_intelligence_v2 || {};
  const regimeAdaptiveTrading = adaptiveExecutionExitV2?.regime_adaptive_trading || unified?.regime_adaptive_trading || {};
  const lifecycleAdaptation = adaptiveExecutionExitV2?.lifecycle_adaptation || unified?.lifecycle_adaptation || {};
  const adaptiveProfitabilityDiagnostics = adaptiveExecutionExitV2?.profitability_improvement_diagnostics || unified?.profitability_improvement_diagnostics || {};
  const portfolioDiversificationV2 = unified?.portfolio_diversification_correlation_v2 || {};
  const mobileRuntimeCompaction = unified?.mobile_runtime_compaction || {};
  const profitSeekingExploration = unified?.profit_seeking_adaptive_exploration || {};
  const marketCalendarKnowledge = unified?.market_calendar_knowledge || {};
  const broadUniverseIntake = unified?.broad_universe_intake_promotion || {};
  const tradeLifecycleExcursion = unified?.trade_lifecycle_excursion_v2 || unified?.trade_lifecycle_excursion || {};
  const adaptiveProfitCapture = unified?.adaptive_profit_capture_intelligence || {};
  const profitCapturePeakDecayExitValidation = unified?.profit_capture_peak_decay_exit_validation_suite_v1 || {};
  const virtualPaperConvergence = unified?.virtual_paper_convergence_symbol_attribution_v1 || {};
  const acceleratedSymbolLearning = unified?.accelerated_learning_symbol_intelligence_suite_v1 || {};
  const realisticShadowLab = unified?.realistic_shadow_evidence_learning_lab_v1 || {};
  const historicalMarketMemory = unified?.historical_intelligence_market_memory_suite_v1 || {};
  const catalystHistoricalExitMaturation = unified?.catalyst_classification_historical_exit_maturation_suite_v1 || {};
  const catalystPersistenceDecayCurves = unified?.catalyst_persistence_decay_curves_v2 || {};
  const catalystLifecycleIntelligence = unified?.catalyst_lifecycle_intelligence_v1 || {};
  const crossSectorCapitalFlowMemory = unified?.cross_sector_capital_flow_memory_v1 || {};
  const shadowVsPaperPerformanceAttribution = unified?.shadow_vs_paper_performance_attribution_v1 || {};
  const candidateRankingAttributionPromotion = unified?.candidate_ranking_attribution_promotion_intelligence_v1 || {};
  const intelligenceQualityLearningEfficiency = unified?.intelligence_quality_learning_efficiency_suite_v1 || {};
  const advancedAttributionControlledExitLearningRoi = unified?.advanced_attribution_controlled_exit_learning_roi_suite_v1 || {};
  const profitOptimizationContextIntelligence = unified?.profit_optimization_context_intelligence_suite_v1 || {};
  const tradeLifecycleAuditTruthHorizonIntegrity = unified?.trade_lifecycle_audit_truth_horizon_integrity_suite_v1 || {};
  const astraFoundationStabilizationGovernance = unified?.astra_foundation_stabilization_governance_bundle_v1 || {};
  const astraTier2aLibrarianExecutiveTruthLayer = unified?.astra_tier2a_librarian_executive_truth_layer_v1 || {};
  const astraSatelliteNetwork = unified?.astra_satellite_network_v1 || {};
  const astraTier3HistoricalSatelliteShadowAcceleration = unified?.astra_tier3_historical_satellite_shadow_acceleration_v1 || {};
  const astraFinalIntelligenceMaturation = unified?.astra_final_intelligence_maturation_bundle_v1 || {};
  const astraTargetedMaturityProfitCapture = unified?.astra_targeted_maturity_profit_capture_optimization_bundle_v1 || {};
  const astraHorizonLifecycleCapacityPromotion = unified?.astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1 || {};
  const astraProviderOrchestrationDataGovernance = unified?.astra_provider_orchestration_data_governance_v1 || {};
  const astraAiosIntelligenceMaturation = unified?.astra_aios_intelligence_maturation_bundle_v1 || {};
  const astraAiosThroughputInstitutionalMemory = unified?.astra_aios_throughput_institutional_memory_optimization_v1 || {};
  const tradeThesisValidation = unified?.trade_thesis_validation_v1 || {};
  const marketTransitionDetection = unified?.market_transition_detection_v1 || {};
  const tradeFamilyIntelligence = unified?.trade_family_intelligence_v1 || {};
  const marketConditionAttribution = unified?.market_condition_attribution_v1 || {};
  const marketBreadthIndexIntelligence = unified?.market_breadth_index_intelligence_v1 || {};
  const etfSectorRotationIntelligence = unified?.etf_sector_rotation_intelligence_v1 || {};
  const cryptoShadowLearning = unified?.crypto_shadow_learning_v1 || {};
  const crossMarketAttributionTransfer = unified?.cross_market_attribution_transfer_learning_v1 || {};
  const profitLockProfitCaptureMaturation = unified?.profit_lock_profit_capture_maturation_v2 || {};
  const shadowCorrectionValidation = unified?.shadow_correction_validation_attribution_v1 || {};
  const controlledPaperProfitProtection = unified?.controlled_paper_profit_protection_pilot_v1 || {};
  const adaptiveExecutionExitV3 = unified?.adaptive_execution_exit_intelligence_v3 || {};
  const exitLearningExpansion = unified?.exit_learning_expansion_suite_v1 || {};
  const marketContextLearning = unified?.market_context_learning_suite_v1 || {};
  const learningAccelerationRetention = unified?.learning_acceleration_retention_suite_v1 || {};
  const adaptiveLearningInfrastructureSuite = unified?.adaptive_learning_infrastructure_suite_v1 || {};
  const adaptiveWorkerActivation = unified?.adaptive_worker_activation_orchestration_v1 || {};
  const confidenceAttribution = unified?.confidence_calibration_performance_attribution_v1 || {};
  const contextEvidenceExpansion = unified?.context_evidence_expansion_suite_v1 || {};
  const catalystThemeNarrative = unified?.catalyst_theme_narrative_capital_flow_intelligence_v2 || {};
  const decisionOptimization = unified?.decision_optimization_trade_management_suite_v1 || {};
  const fullOpportunityLifecycle = unified?.full_opportunity_lifecycle_learning_suite_v1 || {};
  const longTermMemorySymbolRetrieval = unified?.long_term_memory_symbol_retrieval_suite_v1 || {};
  const adaptiveLearningPrioritization = unified?.adaptive_learning_prioritization_resource_allocation_v1 || {};
  const autonomousGovernance = unified?.autonomous_intelligence_validation_governance_v1 || {};
  const tradeArchetypeRegime = unified?.trade_archetype_regime_intelligence || {};
  const replayCounterfactual = unified?.replay_counterfactual_learning_v2 || {};
  const opportunityCostLearning = unified?.opportunity_cost_learning || {};
  const advancedLearningIntelligence = unified?.advanced_learning_intelligence || {};
  const blindSpotDetection = unified?.blind_spot_detection || {};
  const learningIssueAudit = unified?.learning_issue_audit || {};
  const remoteRuntimeConsistency = unified?.remote_runtime_consistency || {};
  const capacityExpansionStatus = unified?.capacity_expansion_status || {};
  const executionParticipationAudit = unified?.execution_participation_audit || {};
  const paperThroughputExitCatalyst = unified?.paper_throughput_exit_validation_catalyst_intelligence_v1 || {};
  const multiHorizonCapacityExitValidation = unified?.multi_horizon_paper_capacity_exit_validation_v1 || {};
  const controlledPaperLearnedExit = unified?.controlled_paper_learned_exit_validation_v1 || {};
  const astraIntelligenceGovernance = unified?.astra_intelligence_governance_v1 || {};
  const consensusEngine = unified?.consensus_engine_v1 || astraIntelligenceGovernance?.consensus_engine_v1 || {};
  const knowledgeGraphFoundation = unified?.knowledge_graph_foundation_v1 || astraIntelligenceGovernance?.knowledge_graph_foundation_v1 || {};
  const dataFreshnessTrust = unified?.data_freshness_trust_engine_v1 || astraIntelligenceGovernance?.data_freshness_trust_engine_v1 || {};
  const dataCoverageEngine = unified?.data_coverage_engine_v1 || astraIntelligenceGovernance?.data_coverage_engine_v1 || {};
  const astraMarketIntelligence = unified?.astra_market_intelligence_v1 || astraIntelligenceGovernance?.astra_market_intelligence_v1 || {};
  const astraCioIntelligence = unified?.astra_cio_intelligence_v1 || {};
  const metricDisplay = (metric, suffix = "") => {
    if (!metric || typeof metric !== "object") return "n/a";
    if (metric.value === null || metric.value === undefined) {
      return String(metric.maturity || metric.label || "insufficient_evidence").replaceAll("_", " ");
    }
    const value = Number(metric.value);
    if (!Number.isFinite(value)) return String(metric.label || "n/a").replaceAll("_", " ");
    return `${value.toFixed(Math.abs(value) >= 10 ? 1 : 2)}${suffix}`;
  };
  const metricToneFromMaturity = (metric, invert = false) => {
    const maturity = String(metric?.maturity || "").toLowerCase();
    if (["insufficient_closed_trades", "awaiting_replay_data", "awaiting_lifecycle_outcomes", "insufficient_evidence", "warming_up"].includes(maturity)) return "caution";
    const value = Number(metric?.value);
    if (!Number.isFinite(value)) return "caution";
    if (invert) {
      if (value <= 35) return "strong";
      if (value <= 65) return "mixed";
      return "weak";
    }
    return metricTone(value, 70, 50);
  };
  const chartSeries = (chart, keys) => {
    const timestamps = Array.isArray(chart?.timestamps) ? chart.timestamps : [];
    return timestamps.map((ts, idx) => {
      const row = { ts: String(ts || idx + 1).slice(0, 16) };
      keys.forEach((key) => {
        const series = Array.isArray(chart?.[key]) ? chart[key] : [];
        row[key] = safeNumber(series[idx], null);
      });
      return row;
    });
  };
  const equityChart = chartSeries(masterCharts?.equity_curve_drawdown_upgrade_timeline, ["equity_values", "drawdown_values", "portfolio_heat_markers"]);
  const expectancyChart = chartSeries(masterCharts?.rolling_expectancy_profit_factor_win_rate, ["rolling_expectancy", "rolling_profit_factor", "rolling_win_rate"]);
  const entryExitQualityChart = chartSeries(masterCharts?.entry_followthrough_exit_quality, ["entry_quality", "follow_through_quality", "exit_quality", "profit_giveback", "weak_follow_through_rate"]);
  const portfolioChart = chartSeries(masterCharts?.portfolio_survivability, ["portfolio_survivability", "concentration_risk", "correlation_risk", "portfolio_heat", "diversification_quality"]);
  const maturityChart = chartSeries(masterCharts?.learning_maturity_timeline, ["replay_maturity", "lifecycle_maturity", "expectancy_maturity", "closed_trade_coverage", "adaptive_confidence"]);
  const adaptiveExitChart = chartSeries(masterCharts?.adaptive_execution_exit_v2_trends, ["profit_giveback_trend", "continuation_quality_trend", "adaptive_hold_quality_trend", "regime_adjusted_expectancy_trend", "execution_timing_trend"]);
  const diversificationChart = chartSeries(masterCharts?.portfolio_diversification_correlation_v2_trends, ["diversification_quality_trend", "correlation_risk_trend", "concentration_risk_trend", "portfolio_fit_trend", "cluster_pressure_trend"]);
  const topMetricGroups = [
    ["Core Performance", executive?.core_performance || {}, [
      ["Released WR", "released_win_rate", "%"],
      ["Profit Factor", "profit_factor", ""],
      ["Expectancy", "expectancy_score", ""],
      ["Avg Return", "average_return", "%"],
      ["Buy Purity", "buy_list_purity", ""],
    ]],
    ["Execution Quality", executive?.execution_quality || {}, [
      ["Entry Quality", "entry_quality", ""],
      ["Exit Quality", "exit_quality", ""],
      ["Follow-Through", "follow_through_quality", ""],
      ["Confidence Truth", "confidence_truthfulness", ""],
    ]],
    ["Portfolio Health", executive?.portfolio_health || {}, [
      ["Survivability", "portfolio_survivability", ""],
      ["Concentration", "concentration_risk", ""],
      ["Correlation", "correlation_risk", ""],
      ["Heat", "portfolio_heat", ""],
    ]],
    ["Learning Status", executive?.learning_status || {}, [
      ["Replay", "replay_maturity", ""],
      ["Lifecycle", "lifecycle_maturity", ""],
      ["Expectancy", "expectancy_maturity", ""],
      ["Coverage", "closed_trade_coverage", ""],
      ["Adaptive Confidence", "adaptive_confidence", ""],
    ]],
    ["System Health", executive?.system_health || {}, [
      ["Runtime", "runtime_integrity", ""],
      ["Data Quality", "data_quality", ""],
      ["Provider Health", "provider_health", ""],
      ["Refresh Integrity", "learning_refresh_integrity", ""],
    ]],
  ];
  const reportCardMetrics = [
    ["Profit Factor", metricDisplay((executive?.core_performance || {}).profit_factor)],
    ["Win Rate", metricDisplay((executive?.core_performance || {}).released_win_rate, true, 1, "%")],
    ["Average Return", metricDisplay((executive?.core_performance || {}).average_return, true, 2, "%")],
    ["Buy Purity", metricDisplay((executive?.core_performance || {}).buy_list_purity)],
    ["Entry Quality", metricDisplay((executive?.execution_quality || {}).entry_quality)],
    ["Exit Quality", metricDisplay((executive?.execution_quality || {}).exit_quality)],
    ["Profit Capture", metricDisplay(profitCapturePeakDecayExitValidation?.shadow_capture_ratio ?? profitCapturePeakDecayExitValidation?.capture_ratio, true, 1)],
    ["Avg Giveback", metricDisplay(profitCapturePeakDecayExitValidation?.shadow_giveback_pct ?? profitCapturePeakDecayExitValidation?.giveback_pct, true, 1, "%")],
    ["Ranking Quality", metricDisplay(candidateRankingAttributionPromotion?.ranking_quality_score, true, 1)],
    ["Evidence Count", safeNumber(evidenceStatus?.evidence_count ?? performanceSummary?.evidence_count ?? candidateRankingAttributionPromotion?.evidence_count).toFixed(0)],
    ["System Health", statusLabel((executive?.system_health || {}).runtime_integrity?.label || (unified?.ok ? "healthy" : "needs_attention"), "healthy")],
    ["Failed Sources", safeNumber(unified?.failed_sources_count).toFixed(0)],
  ];
  const learningSummaryText = snapshotInsufficientEvidence
    ? "Astra is waiting for enough clean evidence to produce a confident learning summary. The Learning Center is showing cached diagnostics and last-known-good safeguards where available."
    : `Astra is finding opportunities with buy purity around ${buyPurityScore.toFixed(1)} and current entry quality near ${entryQualityScore.toFixed(1)}. Profit capture and exit quality remain the areas to watch, especially giveback reduction and natural exit timing validation.`;
  const copyText = async (label, text) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyStatus(`${label} copied`);
      window.setTimeout(() => setCopyStatus(""), 2400);
    } catch (_err) {
      setCopyStatus("Copy unavailable in this browser");
      window.setTimeout(() => setCopyStatus(""), 2400);
    }
  };
  const executiveSnapshotText = () => [
    "ASTRA EXECUTIVE SNAPSHOT",
    `Generated: ${String(unified?.generated_at || lastFetchAt || "n/a")}`,
    `Evidence: ${String(executive?.evidence_label || evidenceStatus?.label || "warming_up").replaceAll("_", " ")}`,
    `Confidence: ${String(executive?.confidence_label || "low").replaceAll("_", " ")}`,
    "",
    ...reportCardMetrics.map(([label, value]) => `${label}: ${value}`),
    "",
    "Plain-English Summary:",
    learningSummaryText,
    "",
    "What Needs Attention:",
    ...whatNeedsAttention.map((line) => `- ${line}`),
  ].join("\n");
  const fullDiagnosticSnapshotText = () => [
    "ASTRA FULL DIAGNOSTIC SNAPSHOT",
    `Generated: ${String(unified?.generated_at || lastFetchAt || "n/a")}`,
    `Failed sources: ${safeNumber(unified?.failed_sources_count).toFixed(0)}`,
    `Initial Learning Center endpoint count: ${safeNumber((unified?.frontend_endpoint_policy || {}).initial_learning_tab_endpoint_count, 1).toFixed(0)}`,
    "",
    "Report Card:",
    ...reportCardMetrics.map(([label, value]) => `${label}: ${value}`),
    "",
    "Suite Details:",
    JSON.stringify({
      executive_snapshot: executive,
      performance_summary: performanceSummary,
      intelligence_quality_learning_efficiency_suite_v1: intelligenceQualityLearningEfficiency,
      advanced_attribution_controlled_exit_learning_roi_suite_v1: advancedAttributionControlledExitLearningRoi,
      profit_optimization_context_intelligence_suite_v1: profitOptimizationContextIntelligence,
      trade_lifecycle_audit_truth_horizon_integrity_suite_v1: tradeLifecycleAuditTruthHorizonIntegrity,
      astra_foundation_stabilization_governance_bundle_v1: astraFoundationStabilizationGovernance,
      astra_tier2a_librarian_executive_truth_layer_v1: astraTier2aLibrarianExecutiveTruthLayer,
      astra_satellite_network_v1: astraSatelliteNetwork,
      astra_tier3_historical_satellite_shadow_acceleration_v1: astraTier3HistoricalSatelliteShadowAcceleration,
      astra_final_intelligence_maturation_bundle_v1: astraFinalIntelligenceMaturation,
      astra_targeted_maturity_profit_capture_optimization_bundle_v1: astraTargetedMaturityProfitCapture,
      astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1: astraHorizonLifecycleCapacityPromotion,
      candidate_ranking_attribution_promotion_intelligence_v1: candidateRankingAttributionPromotion,
      profit_capture_peak_decay_exit_validation_suite_v1: profitCapturePeakDecayExitValidation,
      realistic_shadow_evidence_learning_lab_v1: realisticShadowLab,
      advanced_panel_statuses: advancedStatuses,
    }, null, 2),
  ].join("\n");
  const advancedDiagnosticSnapshotText = () => [
    "ASTRA ADVANCED DIAGNOSTICS",
    `Generated: ${String(unified?.generated_at || lastFetchAt || "n/a")}`,
    JSON.stringify(advancedStatuses || {}, null, 2),
  ].join("\n");
  const ChartShell = ({ title, subtitle, children, empty }) => (
    <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 12, padding: 10, minHeight: 240 }}>
      <div style={{ fontSize: 13, color: "#dbeafe", fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: 11, color: "#91a8c8", marginBottom: 8 }}>{subtitle}</div>
      {empty ? (
        <div style={{ height: 190, display: "grid", placeItems: "center", color: "#9fb1cc", fontSize: 12, textAlign: "center" }}>
          Insufficient evidence for this chart. Astra is waiting for more natural lifecycle outcomes.
        </div>
      ) : children}
    </div>
  );

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
      <section
        style={{
          borderRadius: 28,
          padding: "22px",
          background: "#ffffff",
          border: "1px solid #d8e3f2",
          boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)",
          color: "#13243a",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          <div>
            <div style={{ color: "#246bfe", fontSize: 12, fontWeight: 900, letterSpacing: "0.12em", textTransform: "uppercase" }}>Learning Center V2</div>
            <h2 style={{ margin: "4px 0 6px", fontSize: "clamp(1.55rem, 3vw, 2.25rem)", color: "#13243a", letterSpacing: "-0.04em" }}>Astra Report Card</h2>
            <p style={{ margin: 0, maxWidth: 820, color: "#667994", lineHeight: 1.55 }}>{learningSummaryText}</p>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
            <button type="button" onClick={() => copyText("Executive snapshot", executiveSnapshotText())} style={{ border: "1px solid #c9d8eb", background: "#f7fbff", color: "#1b4f9c", borderRadius: 12, padding: "8px 11px", fontWeight: 900, cursor: "pointer" }}>
              Copy Executive Snapshot
            </button>
            <button type="button" onClick={() => copyText("Full diagnostics", fullDiagnosticSnapshotText())} style={{ border: "1px solid #c9d8eb", background: "#f7fbff", color: "#1b4f9c", borderRadius: 12, padding: "8px 11px", fontWeight: 900, cursor: "pointer" }}>
              Copy Full Diagnostic Snapshot
            </button>
            <button type="button" onClick={() => copyText("Advanced diagnostics", advancedDiagnosticSnapshotText())} style={{ border: "1px solid #c9d8eb", background: "#f7fbff", color: "#1b4f9c", borderRadius: 12, padding: "8px 11px", fontWeight: 900, cursor: "pointer" }}>
              Copy Advanced Diagnostics
            </button>
          </div>
        </div>
        {copyStatus ? <div style={{ marginTop: 10, color: "#1c9b63", fontWeight: 800, fontSize: 12 }}>{copyStatus}</div> : null}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginTop: 16 }}>
          {reportCardMetrics.map(([label, value]) => (
            <div key={label} style={{ border: "1px solid #dce6f3", borderRadius: 16, background: "#f7fbff", padding: "11px 12px" }}>
              <div style={{ color: "#667994", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 900 }}>{label}</div>
              <div style={{ color: "#13243a", fontSize: 18, fontWeight: 900, marginTop: 3 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
        </div>
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 }}>
        <div style={{ background: "#ffffff", border: "1px solid #d8e3f2", borderRadius: 22, boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)", padding: 16, color: "#13243a" }}>
          <h3 style={{ margin: 0, color: "#13243a" }}>What Needs Attention</h3>
          <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
            {whatNeedsAttention.map((item) => (
              <div key={item} style={{ border: "1px solid #e0e8f4", borderRadius: 14, background: "#f7fbff", padding: "9px 10px", color: "#314965", fontSize: 13 }}>
                {item}
              </div>
            ))}
          </div>
        </div>
        <div style={{ background: "#ffffff", border: "1px solid #d8e3f2", borderRadius: 22, boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)", padding: 16, color: "#13243a" }}>
          <h3 style={{ margin: 0, color: "#13243a" }}>Advanced Diagnostics</h3>
          <p style={{ margin: "8px 0 0", color: "#667994", fontSize: 13 }}>
            Full suite panels remain available below and collapsed by default. They are grouped by the existing diagnostic sections and continue to use the cached unified payload.
          </p>
          <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
            {["Performance & Selection", "Exit & Profit Capture", "Opportunity Cost & Ranking", "Catalyst & Market Context", "Shadow Learning", "Portfolio Risk", "System Health", "Governance", "Infrastructure / Runtime", "Experimental / Paper-only Validation"].map((label) => (
              <span key={label} style={{ borderRadius: 999, border: "1px solid #d5e1ef", background: "#f7fbff", padding: "6px 9px", color: "#31506f", fontSize: 11, fontWeight: 800 }}>{label}</span>
            ))}
          </div>
        </div>
      </section>

      <section style={{ background: "#ffffff", border: "1px solid #d8e3f2", borderRadius: 22, boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)", padding: 16, color: "#13243a" }}>
        <details>
          <summary style={{ cursor: "pointer", fontWeight: 900, color: "#13243a" }}>
            Astra Market Intelligence
            <span style={{ marginLeft: 10, color: "#667994", fontWeight: 700, fontSize: 12 }}>
              score {safeNumber(astraMarketIntelligence?.market_intelligence_score).toFixed(1)} · alignment {safeNumber(astraMarketIntelligence?.pillar_alignment_score).toFixed(1)}
            </span>
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginTop: 14 }}>
            {[
              ["Market Intelligence", safeNumber(astraMarketIntelligence?.market_intelligence_score).toFixed(1)],
              ["Pillar Alignment", safeNumber(astraMarketIntelligence?.pillar_alignment_score).toFixed(1)],
              ["Pillar Conflict", safeNumber(astraMarketIntelligence?.pillar_conflict_score).toFixed(1)],
              ["Strongest Pillar", astraMarketIntelligence?.strongest_pillar || "warming up"],
              ["Weakest Pillar", astraMarketIntelligence?.weakest_pillar || "warming up"],
              ["Market Regime", astraMarketIntelligence?.market_regime || "warming up"],
              ["Ask Speed", safeNumber(astraMarketIntelligence?.ask_astra_speed_score).toFixed(1)],
              ["Context Compression", safeNumber(astraMarketIntelligence?.context_compression_score).toFixed(1)],
            ].map(([label, value]) => (
              <div key={label} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px" }}>
                <div style={{ color: "#667994", fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                <div style={{ color: "#13243a", fontSize: 16, fontWeight: 900, marginTop: 3 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginTop: 12 }}>
            {[astraMarketIntelligence?.market_regime_summary, astraMarketIntelligence?.market_tailwind_summary, astraMarketIntelligence?.market_headwind_summary].filter(Boolean).map((line, idx) => (
              <div key={`${idx}-${line}`} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: 13, lineHeight: 1.45 }}>
                {String(line).replaceAll("_", " ")}
              </div>
            ))}
          </div>
        </details>
      </section>

      <section style={{ background: "#ffffff", border: "1px solid #d8e3f2", borderRadius: 22, boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)", padding: 16, color: "#13243a" }}>
        <details>
          <summary style={{ cursor: "pointer", fontWeight: 900, color: "#13243a" }}>
            Astra CIO Intelligence
            <span style={{ marginLeft: 10, color: "#667994", fontWeight: 700, fontSize: 12 }}>
              score {safeNumber(astraCioIntelligence?.overall_cio_intelligence_score).toFixed(1)} · weakest {String(astraCioIntelligence?.weakest_cio_area || "warming up").replaceAll("_", " ")}
            </span>
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginTop: 14 }}>
            {[
              ["Portfolio", safeNumber(astraCioIntelligence?.portfolio_intelligence_score).toFixed(1)],
              ["Exits", safeNumber(astraCioIntelligence?.exit_intelligence_score).toFixed(1)],
              ["Sector Rotation", safeNumber(astraCioIntelligence?.sector_rotation_score).toFixed(1)],
              ["Market Breadth", safeNumber(astraCioIntelligence?.market_breadth_score).toFixed(1)],
              ["Macro", safeNumber(astraCioIntelligence?.macro_intelligence_score).toFixed(1)],
              ["Fed", safeNumber(astraCioIntelligence?.fed_intelligence_score).toFixed(1)],
              ["Strongest Area", astraCioIntelligence?.strongest_cio_area || "warming up"],
              ["Exit Stage", astraCioIntelligence?.exit_activation_stage || "observe only"],
            ].map(([label, value]) => (
              <div key={label} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px" }}>
                <div style={{ color: "#667994", fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                <div style={{ color: "#13243a", fontSize: 16, fontWeight: 900, marginTop: 3 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginTop: 12 }}>
            {[astraCioIntelligence?.portfolio_health_summary, astraCioIntelligence?.exit_maturity_summary, astraCioIntelligence?.sector_rotation_summary, astraCioIntelligence?.market_breadth_summary, astraCioIntelligence?.macro_risk_summary].filter(Boolean).map((line, idx) => (
              <div key={`${idx}-${line}`} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: 13, lineHeight: 1.45 }}>
                {String(line).replaceAll("_", " ")}
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, color: "#667994", fontSize: 13, lineHeight: 1.5 }}>
            {astraCioIntelligence?.cio_summary || "CIO intelligence is warming up from cached portfolio, exit, breadth, sector, and macro diagnostics."}
          </div>
        </details>
      </section>

      <section style={{ background: "#ffffff", border: "1px solid #d8e3f2", borderRadius: 22, boxShadow: "0 18px 45px rgba(25, 47, 78, 0.10)", padding: 16, color: "#13243a" }}>
        <details>
          <summary style={{ cursor: "pointer", fontWeight: 900, color: "#13243a" }}>
            Astra Intelligence Governance
            <span style={{ marginLeft: 10, color: "#667994", fontWeight: 700, fontSize: 12 }}>
              consensus {safeNumber(astraIntelligenceGovernance?.consensus_score).toFixed(1)} · trust {safeNumber(astraIntelligenceGovernance?.data_trust_score).toFixed(1)}
            </span>
          </summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginTop: 14 }}>
            {[
              ["Executive Maturity", safeNumber(astraIntelligenceGovernance?.executive_maturity_score).toFixed(1)],
              ["CEO Maturity", safeNumber(astraIntelligenceGovernance?.ceo_maturity_score).toFixed(1)],
              ["Consensus", safeNumber(astraIntelligenceGovernance?.consensus_score).toFixed(1)],
              ["Knowledge Graph", safeNumber(astraIntelligenceGovernance?.knowledge_graph_score).toFixed(1)],
              ["Freshness", safeNumber(astraIntelligenceGovernance?.data_freshness_score).toFixed(1)],
              ["Trust", safeNumber(astraIntelligenceGovernance?.data_trust_score).toFixed(1)],
              ["Coverage", safeNumber(astraIntelligenceGovernance?.data_coverage_score).toFixed(1)],
              ["Consensus Label", statusLabel(consensusEngine?.consensus_label, "warming_up")],
            ].map(([label, value]) => (
              <div key={label} style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px" }}>
                <div style={{ color: "#667994", fontSize: 10, fontWeight: 900, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
                <div style={{ color: "#13243a", fontSize: 16, fontWeight: 900, marginTop: 3 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginTop: 12 }}>
            <div style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: 13, lineHeight: 1.45 }}>
              <strong>Biggest blind spot:</strong> {String(astraIntelligenceGovernance?.biggest_blind_spot || dataCoverageEngine?.biggest_blind_spot || "warming up").replaceAll("_", " ")}
            </div>
            <div style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: 13, lineHeight: 1.45 }}>
              <strong>Highest priority fix:</strong> {String(astraIntelligenceGovernance?.highest_priority_fix || dataFreshnessTrust?.recommended_data_fix || "keep cached governance summaries visible").replaceAll("_", " ")}
            </div>
            <div style={{ border: "1px solid #dce6f3", borderRadius: 14, background: "#f7fbff", padding: "10px 11px", color: "#314965", fontSize: 13, lineHeight: 1.45 }}>
              <strong>Graph coverage:</strong> {safeNumber(knowledgeGraphFoundation?.graph_coverage).toFixed(1)} with {safeNumber(knowledgeGraphFoundation?.graph_edge_count).toFixed(0)} relationships.
            </div>
          </div>
          <div style={{ marginTop: 12, color: "#667994", fontSize: 13, lineHeight: 1.5 }}>
            {astraIntelligenceGovernance?.governance_summary || "Governance summary is warming up from cached diagnostics. This section is advisory-only and does not change trading behavior."}
          </div>
        </details>
      </section>

      <div style={{ ...panelStyle, padding: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.18rem", color: "#f3f8ff" }}>Unified Learning Diagnostics</h2>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 4 }}>
              One fast control-tower snapshot for performance, execution, portfolio risk, learning maturity, and system health.
            </div>
            <div style={{ fontSize: 11, color: "#85a2c8", marginTop: 5 }}>
              Evidence: {String(executive?.evidence_label || evidenceStatus?.label || "warming_up").replaceAll("_", " ")}
              {" | "}
              Confidence: {String(executive?.confidence_label || "low").replaceAll("_", " ")}
              {" | "}
              Build: {safeNumber(unified?.build_ms).toFixed(1)}ms
              {" | "}
              Cache: {unified?.cache_hit ? `hit (${safeNumber(unified?.cache_age_seconds).toFixed(1)}s)` : "fresh"}
            </div>
          </div>
          <div style={{ fontSize: 11, color: "#9fb1cc", textAlign: "right" }}>
            Updated {String(unified?.generated_at || lastFetchAt || "n/a")}
            <br />
            Initial endpoint calls: 1
          </div>
        </div>
        {staleStatus?.stale || unified?.degraded_reason ? (
          <div style={{ marginTop: 12, border: "1px solid #765d2e", background: "rgba(103, 74, 22, 0.28)", borderRadius: 10, padding: "9px 10px", color: "#ffe2a1", fontSize: 12 }}>
            {String(staleStatus?.message || "Learning snapshot is using last-known-good data because some advanced diagnostics timed out.")}
          </div>
        ) : null}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 12 }}>
        {topMetricGroups.map(([groupTitle, groupPayload, metrics]) => (
          <div key={groupTitle} style={{ ...panelStyle, padding: 12 }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>{groupTitle}</h3>
            {groupTitle === "Core Performance" ? (
              <div style={{ margin: "-2px 0 8px", color: performanceSummary?.legacy_fallback_used ? "#fcd34d" : "#9fd3ff", fontSize: 11 }}>
                Source: {String(performanceSummary?.selected_metric_source || performanceSummary?.metric_source || "unknown").replaceAll("_", " ")}
                {performanceSummary?.legacy_fallback_used ? " | legacy fallback active" : ""}
                {" | Scope: "}
                {String(performanceSummary?.dataset_scope_label || "unknown").replaceAll("_", " ")}
              </div>
            ) : null}
            <div style={{ display: "grid", gap: 8 }}>
              {metrics.map(([label, key, suffix]) => {
                const metric = groupPayload?.[key] || {};
                const invert = ["concentration_risk", "correlation_risk", "portfolio_heat"].includes(key);
                const tone = toneColors(metricToneFromMaturity(metric, invert));
                return (
                  <div key={`${groupTitle}-${key}`} style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "8px 9px" }} title={String(metric?.explanation || "")}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                      <div style={{ fontSize: 11, color: "#9fb1cc" }}>{label}</div>
                      <div style={{ background: tone.badgeBg, border: `1px solid ${tone.badgeBorder}`, color: tone.badgeText, borderRadius: 999, padding: "1px 7px", fontSize: 9, textTransform: "uppercase" }}>
                        {String(metric?.maturity || metric?.label || "n/a").replaceAll("_", " ")}
                      </div>
                    </div>
                    <div style={{ fontSize: 19, color: "#f2f7ff", fontWeight: 800, marginTop: 4 }}>{metricDisplay(metric, suffix)}</div>
                    <div style={{ fontSize: 10, color: "#7892ba", marginTop: 3 }}>
                      Evidence {safeNumber(metric?.evidence_count).toFixed(0)}
                      {metric?.source ? ` | Source ${String(metric.source).replaceAll("_", " ")}` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>What Needs Attention</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 9, fontSize: 12 }}>
          <div style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "9px 10px" }}>
            <div style={{ color: "#9fb1cc", fontSize: 11 }}>Main weakness</div>
            <div style={{ fontWeight: 800, color: "#f2f7ff" }}>{String(executive?.main_current_weakness || "insufficient_evidence").replaceAll("_", " ")}</div>
          </div>
          <div style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "9px 10px" }}>
            <div style={{ color: "#9fb1cc", fontSize: 11 }}>Strongest area</div>
            <div style={{ fontWeight: 800, color: "#f2f7ff" }}>{String(executive?.strongest_current_area || "warming_up").replaceAll("_", " ")}</div>
          </div>
          <div style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "9px 10px" }}>
            <div style={{ color: "#9fb1cc", fontSize: 11 }}>Primary blocker</div>
            <div style={{ fontWeight: 800, color: "#f2f7ff" }}>{String(executive?.primary_blocker_reason || "none").replaceAll("_", " ")}</div>
          </div>
          <div style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "9px 10px" }}>
            <div style={{ color: "#9fb1cc", fontSize: 11 }}>Next best focus</div>
            <div style={{ fontWeight: 800, color: "#f2f7ff" }}>{String(executive?.next_best_focus || "collect more completed paper outcomes").replaceAll("_", " ")}</div>
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Master Charts</h3>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginBottom: 10 }}>
          Charts are powered by the unified snapshot and gracefully fall back when evidence is still warming up.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12 }}>
          <ChartShell title="Equity Curve + Drawdown" subtitle="System progress with drawdown pressure." empty={equityChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={equityChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="equity_values" stroke="#22c55e" strokeWidth={2} dot={false} name="Equity" />
                <Line type="monotone" dataKey="drawdown_values" stroke="#f43f5e" strokeWidth={2} dot={false} name="Drawdown" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Rolling Expectancy + PF + WR" subtitle="Whether Astra is getting smarter, not just busier." empty={expectancyChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={expectancyChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="rolling_expectancy" stroke="#38bdf8" strokeWidth={2} dot={false} name="Expectancy" />
                <Line type="monotone" dataKey="rolling_profit_factor" stroke="#f59e0b" strokeWidth={2} dot={false} name="Profit Factor" />
                <Line type="monotone" dataKey="rolling_win_rate" stroke="#a78bfa" strokeWidth={2} dot={false} name="Win Rate" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Entry -> Follow-Through -> Exit" subtitle="Execution and trade-management improvement." empty={entryExitQualityChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={entryExitQualityChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="entry_quality" stroke="#22c55e" strokeWidth={2} dot={false} name="Entry" />
                <Line type="monotone" dataKey="follow_through_quality" stroke="#38bdf8" strokeWidth={2} dot={false} name="Follow-Through" />
                <Line type="monotone" dataKey="exit_quality" stroke="#f59e0b" strokeWidth={2} dot={false} name="Exit" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Portfolio Survivability" subtitle="Risk control, concentration, heat, and diversification." empty={portfolioChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={portfolioChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="portfolio_survivability" stroke="#22c55e" strokeWidth={2} dot={false} name="Survivability" />
                <Line type="monotone" dataKey="concentration_risk" stroke="#f43f5e" strokeWidth={2} dot={false} name="Concentration" />
                <Line type="monotone" dataKey="correlation_risk" stroke="#f59e0b" strokeWidth={2} dot={false} name="Correlation" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Diversification & Correlation" subtitle="Portfolio fit, cluster pressure, concentration, and correlation." empty={diversificationChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={diversificationChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="diversification_quality_trend" stroke="#22c55e" strokeWidth={2} dot={false} name="Diversification" />
                <Line type="monotone" dataKey="portfolio_fit_trend" stroke="#38bdf8" strokeWidth={2} dot={false} name="Portfolio Fit" />
                <Line type="monotone" dataKey="correlation_risk_trend" stroke="#f59e0b" strokeWidth={2} dot={false} name="Correlation" />
                <Line type="monotone" dataKey="cluster_pressure_trend" stroke="#f43f5e" strokeWidth={2} dot={false} name="Cluster Pressure" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Learning Maturity Timeline" subtitle="Replay, lifecycle, expectancy, coverage, and adaptive confidence." empty={maturityChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={maturityChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="replay_maturity" stroke="#38bdf8" strokeWidth={2} dot={false} name="Replay" />
                <Line type="monotone" dataKey="lifecycle_maturity" stroke="#22c55e" strokeWidth={2} dot={false} name="Lifecycle" />
                <Line type="monotone" dataKey="expectancy_maturity" stroke="#a78bfa" strokeWidth={2} dot={false} name="Expectancy" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
          <ChartShell title="Adaptive Execution & Exit V2" subtitle="Giveback, continuation, hold quality, regime expectancy, and entry timing." empty={adaptiveExitChart.length === 0}>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={adaptiveExitChart}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 10 }} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="continuation_quality_trend" stroke="#22c55e" strokeWidth={2} dot={false} name="Continuation" />
                <Line type="monotone" dataKey="adaptive_hold_quality_trend" stroke="#38bdf8" strokeWidth={2} dot={false} name="Hold Quality" />
                <Line type="monotone" dataKey="execution_timing_trend" stroke="#a78bfa" strokeWidth={2} dot={false} name="Timing" />
                <Line type="monotone" dataKey="profit_giveback_trend" stroke="#f43f5e" strokeWidth={2} dot={false} name="Giveback" />
              </LineChart>
            </ResponsiveContainer>
          </ChartShell>
        </div>
      </div>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Historical Intelligence & Market Memory V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is gradually building long-term market memory from historical symbol, sector, regime, and catalyst behavior. It stores compressed lessons instead of raw history, uses FMP bandwidth only within strict monthly safety limits, and does not change trading behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Historical phase", historicalMarketMemory?.historical_phase],
            ["Symbols selected", safeNumber(historicalMarketMemory?.symbols_selected).toFixed(0)],
            ["Symbols completed", safeNumber(historicalMarketMemory?.symbols_completed).toFixed(0)],
            ["Compressed memory", safeNumber(historicalMarketMemory?.compressed_market_memory_records).toFixed(0)],
            ["Profiles updated", safeNumber(historicalMarketMemory?.symbol_profiles_updated).toFixed(0)],
            ["Peer groups", safeNumber(historicalMarketMemory?.peer_groups_created).toFixed(0)],
            ["Regimes detected", safeNumber(historicalMarketMemory?.regimes_detected).toFixed(0)],
            ["Catalyst records", safeNumber(historicalMarketMemory?.catalyst_records_created).toFixed(0)],
            ["Catalyst coverage", safeNumber(historicalMarketMemory?.catalyst_coverage_score).toFixed(1)],
            ["Unknown catalyst", `${safeNumber(historicalMarketMemory?.unknown_catalyst_rate).toFixed(1)}%`],
            ["Historical replays", safeNumber(historicalMarketMemory?.historical_replays_completed).toFixed(0)],
            ["Market memory", safeNumber(historicalMarketMemory?.market_memory_quality_score).toFixed(1)],
            ["Candidate diversity", safeNumber(historicalMarketMemory?.candidate_diversity_score).toFixed(1)],
            ["FMP usage", `${safeNumber(historicalMarketMemory?.fmp_usage_pct).toFixed(2)}%`],
            ["Monthly used", `${safeNumber(historicalMarketMemory?.fmp_monthly_bandwidth_used_gb).toFixed(3)} GB`],
            ["Remaining", `${safeNumber(historicalMarketMemory?.fmp_remaining_bandwidth_gb).toFixed(3)} GB`],
            ["Daily safe budget", `${safeNumber(historicalMarketMemory?.fmp_daily_safe_budget_gb).toFixed(4)} GB`],
            ["Projected month-end", `${safeNumber(historicalMarketMemory?.projected_month_end_usage_gb).toFixed(3)} GB`],
            ["Expansion allowed", historicalMarketMemory?.fmp_expansion_allowed ? "yes" : "no"],
            ["Expansion block", historicalMarketMemory?.fmp_expansion_block_reason],
            ["Storage pressure", safeNumber(historicalMarketMemory?.storage_pressure_score).toFixed(1)],
            ["Memory pressure", safeNumber(historicalMarketMemory?.memory_pressure_score).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(historicalMarketMemory?.shadow_recommendation || "Continue cache-only historical diagnostics.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Catalyst Classification, Historical Maturation & Exit Learning V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is classifying unknown catalysts from cached memory, maturing historical symbol/sector/regime learning, and scoring exit-learning readiness. This is shadow-only and does not change entries, exits, rankings, sizing, thresholds, broker behavior, or FMP budgets.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Catalyst coverage", `${safeNumber(catalystHistoricalExitMaturation?.catalyst_coverage_score).toFixed(1)}%`],
            ["Unknown catalyst", `${safeNumber(catalystHistoricalExitMaturation?.unknown_catalyst_rate).toFixed(1)}%`],
            ["Classified catalysts", safeNumber(catalystHistoricalExitMaturation?.classified_catalyst_count).toFixed(0)],
            ["Catalyst memory", safeNumber(catalystHistoricalExitMaturation?.catalyst_memory_quality).toFixed(1)],
            ["Catalyst confidence", safeNumber(catalystHistoricalExitMaturation?.catalyst_confidence_score).toFixed(1)],
            ["Dominant catalyst", catalystHistoricalExitMaturation?.dominant_catalyst],
            ["Historical growth", safeNumber(catalystHistoricalExitMaturation?.historical_memory_growth_score).toFixed(1)],
            ["Symbol growth", safeNumber(catalystHistoricalExitMaturation?.symbol_memory_growth_score).toFixed(1)],
            ["Sector growth", safeNumber(catalystHistoricalExitMaturation?.sector_memory_growth_score).toFixed(1)],
            ["Regime growth", safeNumber(catalystHistoricalExitMaturation?.regime_memory_growth_score).toFixed(1)],
            ["Transfer learning", safeNumber(catalystHistoricalExitMaturation?.historical_transfer_learning_score).toFixed(1)],
            ["Profit lock readiness", safeNumber(catalystHistoricalExitMaturation?.profit_lock_readiness_score).toFixed(1)],
            ["Catalyst decay learning", safeNumber(catalystHistoricalExitMaturation?.catalyst_decay_learning_score).toFixed(1)],
            ["Continuation failure", safeNumber(catalystHistoricalExitMaturation?.continuation_failure_learning_score).toFixed(1)],
            ["Hold duration", safeNumber(catalystHistoricalExitMaturation?.hold_duration_learning_score).toFixed(1)],
            ["Giveback reduction", safeNumber(catalystHistoricalExitMaturation?.giveback_reduction_score).toFixed(1)],
            ["Exit maturity", safeNumber(catalystHistoricalExitMaturation?.exit_learning_maturity_score).toFixed(1)],
            ["API impact", catalystHistoricalExitMaturation?.api_impact_estimate],
            ["Bandwidth impact", catalystHistoricalExitMaturation?.bandwidth_impact_estimate],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Categories: {(catalystHistoricalExitMaturation?.inferred_catalyst_categories || []).slice(0, 8).map((x) => String(x).replaceAll("_", " ")).join(", ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(catalystHistoricalExitMaturation?.shadow_recommendation || "Continue catalyst classification, historical maturation, and exit-learning diagnostics shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Catalyst Persistence & Decay Curves V2</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is learning how long catalysts tend to persist, when continuation weakens, and when exhaustion or giveback risk rises. This is advisory memory only and does not change hold times, exits, entries, rankings, sizing, thresholds, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Catalysts tracked", safeNumber(catalystPersistenceDecayCurves?.catalysts_tracked).toFixed(0)],
            ["Persistence score", safeNumber(catalystPersistenceDecayCurves?.catalyst_persistence_score).toFixed(1)],
            ["Decay score", safeNumber(catalystPersistenceDecayCurves?.catalyst_decay_score).toFixed(1)],
            ["Half-life estimate", `${safeNumber(catalystPersistenceDecayCurves?.catalyst_half_life_estimate).toFixed(1)} min`],
            ["Continuation probability", `${safeNumber(catalystPersistenceDecayCurves?.catalyst_continuation_probability).toFixed(1)}%`],
            ["Exhaustion probability", `${safeNumber(catalystPersistenceDecayCurves?.catalyst_exhaustion_probability).toFixed(1)}%`],
            ["Memory quality", safeNumber(catalystPersistenceDecayCurves?.catalyst_memory_quality).toFixed(1)],
            ["Strongest catalyst", catalystPersistenceDecayCurves?.strongest_persistence_catalyst],
            ["Fastest decay", catalystPersistenceDecayCurves?.fastest_decay_catalyst],
            ["Strongest pattern", catalystPersistenceDecayCurves?.strongest_persistence_pattern],
            ["Decay pattern", catalystPersistenceDecayCurves?.strongest_decay_pattern],
            ["Best half-life", `${safeNumber(catalystPersistenceDecayCurves?.best_catalyst_half_life).toFixed(1)} min`],
            ["Worst half-life", `${safeNumber(catalystPersistenceDecayCurves?.worst_catalyst_half_life).toFixed(1)} min`],
            ["Decay readiness", safeNumber(catalystPersistenceDecayCurves?.catalyst_decay_readiness).toFixed(1)],
            ["Decay confidence", safeNumber(catalystPersistenceDecayCurves?.catalyst_decay_confidence).toFixed(1)],
            ["Capture before decay", safeNumber(catalystPersistenceDecayCurves?.profit_capture_before_decay).toFixed(1)],
            ["Capture after decay", safeNumber(catalystPersistenceDecayCurves?.profit_capture_after_decay).toFixed(1)],
            ["Continuation after weakening", safeNumber(catalystPersistenceDecayCurves?.continuation_after_catalyst_weakening).toFixed(1)],
            ["Giveback after weakening", safeNumber(catalystPersistenceDecayCurves?.giveback_after_catalyst_weakening).toFixed(1)],
            ["API calls", safeNumber(catalystPersistenceDecayCurves?.api_calls_used).toFixed(0)],
            ["Provider calls", safeNumber(catalystPersistenceDecayCurves?.provider_calls_used).toFixed(0)],
            ["LLM calls", safeNumber(catalystPersistenceDecayCurves?.llm_calls_used).toFixed(0)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top curves: {(catalystPersistenceDecayCurves?.catalyst_curves || []).slice(0, 3).map((row) => `${String(row?.catalyst_type || "unknown").replaceAll("_", " ")} half-life ${safeNumber(row?.catalyst_half_life_estimate_minutes).toFixed(0)}m`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(catalystPersistenceDecayCurves?.shadow_recommendation || "Continue catalyst persistence and decay learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Catalyst Lifecycle Intelligence V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is mapping catalysts through emerging, accelerating, mature, peaking, decaying, and exhausted stages to estimate continuation, giveback, hold quality, and exit quality. This is shadow-only learning and does not change entries or exits.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(catalystLifecycleIntelligence?.evidence_count).toFixed(0)],
            ["Strongest stage", catalystLifecycleIntelligence?.strongest_catalyst_stage],
            ["Weakest stage", catalystLifecycleIntelligence?.weakest_catalyst_stage],
            ["Best lifecycle", catalystLifecycleIntelligence?.best_catalyst_lifecycle],
            ["Worst lifecycle", catalystLifecycleIntelligence?.worst_catalyst_lifecycle],
            ["Lifecycle confidence", safeNumber(catalystLifecycleIntelligence?.catalyst_lifecycle_confidence).toFixed(1)],
            ["Persistence", safeNumber(catalystLifecycleIntelligence?.average_persistence_score).toFixed(1)],
            ["Decay probability", safeNumber(catalystLifecycleIntelligence?.average_decay_probability).toFixed(1)],
            ["Continuation probability", safeNumber(catalystLifecycleIntelligence?.average_continuation_probability).toFixed(1)],
            ["Average lifespan", `${safeNumber(catalystLifecycleIntelligence?.average_lifespan_minutes).toFixed(1)} min`],
            ["Best stage profitability", safeNumber(catalystLifecycleIntelligence?.best_stage_profitability_score).toFixed(1)],
            ["Worst stage giveback", `${safeNumber(catalystLifecycleIntelligence?.worst_stage_giveback_pct).toFixed(2)}%`],
            ["API/provider/LLM", `${safeNumber(catalystLifecycleIntelligence?.api_calls_used).toFixed(0)} / ${safeNumber(catalystLifecycleIntelligence?.provider_calls_used).toFixed(0)} / ${safeNumber(catalystLifecycleIntelligence?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", catalystLifecycleIntelligence?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Stages: {(catalystLifecycleIntelligence?.lifecycle_stages || []).slice(0, 6).map((row) => `${String(row?.stage || "stage").replaceAll("_", " ")} cont ${safeNumber(row?.continuation_probability).toFixed(0)}%`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(catalystLifecycleIntelligence?.shadow_recommendation || "Continue catalyst lifecycle learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Cross-Sector Capital Flow Memory V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is building memory for sector inflows, outflows, rotations, theme transitions, and leadership changes using cached evidence only. This supports catalyst context without changing rankings, entries, exits, sizing, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(crossSectorCapitalFlowMemory?.evidence_count).toFixed(0)],
            ["Strongest inflow", crossSectorCapitalFlowMemory?.strongest_inflow_sector],
            ["Strongest outflow", crossSectorCapitalFlowMemory?.strongest_outflow_sector],
            ["Flow persistence", safeNumber(crossSectorCapitalFlowMemory?.flow_persistence).toFixed(1)],
            ["Rotation speed", safeNumber(crossSectorCapitalFlowMemory?.rotation_speed).toFixed(1)],
            ["Continuation after inflow", safeNumber(crossSectorCapitalFlowMemory?.continuation_after_inflow).toFixed(1)],
            ["Continuation after outflow", safeNumber(crossSectorCapitalFlowMemory?.continuation_after_outflow).toFixed(1)],
            ["Strongest capital flow", crossSectorCapitalFlowMemory?.strongest_capital_flow],
            ["Weakest capital flow", crossSectorCapitalFlowMemory?.weakest_capital_flow],
            ["Sector rotation", crossSectorCapitalFlowMemory?.strongest_sector_rotation],
            ["Theme rotation", crossSectorCapitalFlowMemory?.strongest_theme_rotation],
            ["Flow confidence", safeNumber(crossSectorCapitalFlowMemory?.sector_flow_confidence).toFixed(1)],
            ["Rotation confidence", safeNumber(crossSectorCapitalFlowMemory?.rotation_confidence).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(crossSectorCapitalFlowMemory?.api_calls_used).toFixed(0)} / ${safeNumber(crossSectorCapitalFlowMemory?.provider_calls_used).toFixed(0)} / ${safeNumber(crossSectorCapitalFlowMemory?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", crossSectorCapitalFlowMemory?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Sector rows: {(crossSectorCapitalFlowMemory?.sector_flow_rows || []).slice(0, 4).map((row) => `${String(row?.sector || "sector")} inflow ${safeNumber(row?.inflow_score).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(crossSectorCapitalFlowMemory?.shadow_recommendation || "Continue cross-sector capital-flow memory shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Shadow vs Paper Performance Attribution V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is comparing actual paper outcomes against shadow, virtual, replay, and shadow-influenced alternatives to measure whether Shadow intelligence is adding real value. This is attribution-only and does not change broker behavior, rankings, sizing, entries, exits, or policy application.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Reconciliation", statusLabel(shadowVsPaperPerformanceAttribution?.overall_reconciliation_status)],
            ["Canonical source", String(shadowVsPaperPerformanceAttribution?.canonical_performance_source || "unavailable").replaceAll("_", " ")],
            ["Canonical evidence", safeNumber(shadowVsPaperPerformanceAttribution?.canonical_closed_trade_count).toFixed(0)],
            ["Paper PF", metricDisplay(shadowVsPaperPerformanceAttribution?.paper_profit_factor_verified, shadowVsPaperPerformanceAttribution?.paper_profit_factor_available, 2)],
            ["Shadow PF", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_profit_factor_verified, shadowVsPaperPerformanceAttribution?.shadow_profit_factor_available, 2)],
            ["PF delta", metricDisplay(shadowVsPaperPerformanceAttribution?.profit_factor_delta, shadowVsPaperPerformanceAttribution?.paper_profit_factor_available && shadowVsPaperPerformanceAttribution?.shadow_profit_factor_available, 2)],
            ["Paper PF status", statusLabel(shadowVsPaperPerformanceAttribution?.paper_profit_factor_status)],
            ["Shadow PF status", statusLabel(shadowVsPaperPerformanceAttribution?.shadow_profit_factor_status)],
            ["Shadow PF blocker", String(shadowVsPaperPerformanceAttribution?.shadow_pf_blocker || "none").replaceAll("_", " ")],
            ["Paper WR", metricDisplay(shadowVsPaperPerformanceAttribution?.paper_win_rate, shadowVsPaperPerformanceAttribution?.paper_trade_count > 0, 1, "%")],
            ["Shadow WR", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_win_rate, shadowVsPaperPerformanceAttribution?.shadow_trade_count > 0, 1, "%")],
            ["Paper avg return", metricDisplay(shadowVsPaperPerformanceAttribution?.paper_avg_return, shadowVsPaperPerformanceAttribution?.paper_trade_count > 0, 3)],
            ["Shadow avg return", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_avg_return, shadowVsPaperPerformanceAttribution?.shadow_trade_count > 0, 3)],
            ["Paper gross P/L", `${safeNumber(shadowVsPaperPerformanceAttribution?.paper_gross_profit).toFixed(2)} / ${safeNumber(shadowVsPaperPerformanceAttribution?.paper_gross_loss).toFixed(2)}`],
            ["Shadow gross P/L", `${safeNumber(shadowVsPaperPerformanceAttribution?.shadow_gross_profit).toFixed(2)} / ${safeNumber(shadowVsPaperPerformanceAttribution?.shadow_gross_loss).toFixed(2)}`],
            ["Return delta", metricDisplay(shadowVsPaperPerformanceAttribution?.avg_return_delta, shadowVsPaperPerformanceAttribution?.paper_profit_factor_available && shadowVsPaperPerformanceAttribution?.shadow_profit_factor_available, 3)],
            ["Capture delta", metricDisplay(shadowVsPaperPerformanceAttribution?.profit_capture_delta, shadowVsPaperPerformanceAttribution?.paper_trade_count > 0 && shadowVsPaperPerformanceAttribution?.shadow_trade_count > 0, 2)],
            ["Exit quality delta", metricDisplay(shadowVsPaperPerformanceAttribution?.exit_quality_delta, shadowVsPaperPerformanceAttribution?.paper_trade_count > 0 && shadowVsPaperPerformanceAttribution?.shadow_trade_count > 0, 2)],
            ["Shadow alpha", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_alpha_score, shadowVsPaperPerformanceAttribution?.shadow_alpha_available, 1)],
            ["Alpha confidence", safeNumber(shadowVsPaperPerformanceAttribution?.shadow_alpha_confidence).toFixed(1)],
            ["20 trade PF", `${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_20_paper_pf, shadowVsPaperPerformanceAttribution?.rolling_20_paper_pf_status === "PASS", 2)} / ${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_20_shadow_pf, shadowVsPaperPerformanceAttribution?.rolling_20_shadow_pf_status === "PASS", 2)}`],
            ["50 trade PF", `${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_50_paper_pf, shadowVsPaperPerformanceAttribution?.rolling_50_paper_pf_status === "PASS", 2)} / ${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_50_shadow_pf, shadowVsPaperPerformanceAttribution?.rolling_50_shadow_pf_status === "PASS", 2)}`],
            ["100 trade PF", `${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_100_paper_pf, shadowVsPaperPerformanceAttribution?.rolling_100_paper_pf_status === "PASS", 2)} / ${metricDisplay(shadowVsPaperPerformanceAttribution?.rolling_100_shadow_pf, shadowVsPaperPerformanceAttribution?.rolling_100_shadow_pf_status === "PASS", 2)}`],
            ["Lifetime PF", `${metricDisplay(shadowVsPaperPerformanceAttribution?.lifetime_paper_pf, shadowVsPaperPerformanceAttribution?.lifetime_paper_pf_status === "PASS", 2)} / ${metricDisplay(shadowVsPaperPerformanceAttribution?.lifetime_shadow_pf, shadowVsPaperPerformanceAttribution?.lifetime_shadow_pf_status === "PASS", 2)}`],
            ["Reviewed", safeNumber(shadowVsPaperPerformanceAttribution?.recommendations_reviewed).toFixed(0)],
            ["Trade count", safeNumber(shadowVsPaperPerformanceAttribution?.trade_count).toFixed(0)],
            ["Shadow trades", safeNumber(shadowVsPaperPerformanceAttribution?.shadow_trade_count).toFixed(0)],
            ["Outperformance", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_outperformance_pct, shadowVsPaperPerformanceAttribution?.paper_profit_factor_available && shadowVsPaperPerformanceAttribution?.shadow_profit_factor_available, 1, "%")],
            ["Underperformance", metricDisplay(shadowVsPaperPerformanceAttribution?.shadow_underperformance_pct, shadowVsPaperPerformanceAttribution?.paper_profit_factor_available && shadowVsPaperPerformanceAttribution?.shadow_profit_factor_available, 1, "%")],
            ["API/provider/LLM", `${safeNumber(shadowVsPaperPerformanceAttribution?.api_calls_used).toFixed(0)} / ${safeNumber(shadowVsPaperPerformanceAttribution?.provider_calls_used).toFixed(0)} / ${safeNumber(shadowVsPaperPerformanceAttribution?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", shadowVsPaperPerformanceAttribution?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Cohorts: {(shadowVsPaperPerformanceAttribution?.build_cohort_comparison || []).map((row) => `${String(row?.cohort || "cohort").replaceAll("_", " ")} ${row?.cohort_status === "PASS" ? `PF ${metricDisplay(row?.cohort_profit_factor_verified, true, 2)}` : "insufficient evidence"}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Attribution: {(shadowVsPaperPerformanceAttribution?.source_attribution || []).slice(0, 4).map((row) => `${String(row?.source || "source").replaceAll("_", " ")} dPF ${safeNumber(row?.estimated_profit_factor_delta).toFixed(2)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Reconciliation checks: paper PF {shadowVsPaperPerformanceAttribution?.paper_pf_matches_unified ? "match" : "warning"} | returns {shadowVsPaperPerformanceAttribution?.paper_returns_match_unified ? "match" : "warning"} | evidence {shadowVsPaperPerformanceAttribution?.evidence_matches_unified ? "match" : "warning"} | cohort {shadowVsPaperPerformanceAttribution?.cohort_matches_unified ? "match" : "warning"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(shadowVsPaperPerformanceAttribution?.shadow_recommendation || "Continue shadow-vs-paper attribution observation-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Candidate Ranking Attribution & Promotion Intelligence V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is auditing why candidates were promoted, rejected, or missed so ranking quality can be improved safely later. This suite is attribution-only, shadow-only, and does not change ranking, promotion logic, entries, exits, sizing, thresholds, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(candidateRankingAttributionPromotion?.evidence_count).toFixed(0)],
            ["Promoted", safeNumber(candidateRankingAttributionPromotion?.promoted_candidates).toFixed(0)],
            ["Rejected", safeNumber(candidateRankingAttributionPromotion?.rejected_candidates).toFixed(0)],
            ["Selected", safeNumber(candidateRankingAttributionPromotion?.selected_candidates).toFixed(0)],
            ["Missed", safeNumber(candidateRankingAttributionPromotion?.missed_candidates).toFixed(0)],
            ["Ranking quality", safeNumber(candidateRankingAttributionPromotion?.ranking_quality_score).toFixed(1)],
            ["Promotion accuracy", safeNumber(candidateRankingAttributionPromotion?.promotion_accuracy).toFixed(1)],
            ["Rejection accuracy", safeNumber(candidateRankingAttributionPromotion?.rejection_accuracy).toFixed(1)],
            ["Predictive power", safeNumber(candidateRankingAttributionPromotion?.ranking_predictive_power).toFixed(1)],
            ["Reliability", safeNumber(candidateRankingAttributionPromotion?.ranking_reliability).toFixed(1)],
            ["Consistency", safeNumber(candidateRankingAttributionPromotion?.ranking_consistency).toFixed(1)],
            ["Overconfidence", safeNumber(candidateRankingAttributionPromotion?.ranking_overconfidence).toFixed(1)],
            ["Underconfidence", safeNumber(candidateRankingAttributionPromotion?.ranking_underconfidence).toFixed(1)],
            ["Strongest factor", candidateRankingAttributionPromotion?.most_predictive_ranking_factor],
            ["Weakest factor", candidateRankingAttributionPromotion?.least_predictive_ranking_factor],
            ["Most overvalued", candidateRankingAttributionPromotion?.most_overvalued_factor],
            ["Most undervalued", candidateRankingAttributionPromotion?.most_undervalued_factor],
            ["Missed promotion", candidateRankingAttributionPromotion?.biggest_missed_promotion],
            ["False promotion", candidateRankingAttributionPromotion?.biggest_false_promotion],
            ["Dominant mistake", candidateRankingAttributionPromotion?.dominant_ranking_mistake],
            ["Blind spot", candidateRankingAttributionPromotion?.dominant_ranking_blind_spot],
            ["Next focus", candidateRankingAttributionPromotion?.next_ranking_focus],
            ["Readiness", candidateRankingAttributionPromotion?.candidate_ranking_influence_readiness],
            ["Influence ready", candidateRankingAttributionPromotion?.influence_ready ? "yes" : "no"],
            ["Confidence", safeNumber(candidateRankingAttributionPromotion?.confidence_score).toFixed(1)],
            ["Truth score", safeNumber(candidateRankingAttributionPromotion?.ranking_truth_score).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(candidateRankingAttributionPromotion?.api_calls_used).toFixed(0)} / ${safeNumber(candidateRankingAttributionPromotion?.provider_calls_used).toFixed(0)} / ${safeNumber(candidateRankingAttributionPromotion?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", candidateRankingAttributionPromotion?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Factor audit: {(candidateRankingAttributionPromotion?.ranking_factor_rows || []).slice(0, 4).map((row) => `${String(row?.factor || "unknown").replaceAll("_", " ")} ${safeNumber(row?.predictive_score).toFixed(1)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Lessons: {String(candidateRankingAttributionPromotion?.strongest_ranking_lesson || "Continue candidate ranking audit shadow-only.").replaceAll("_", " ")} | {String(candidateRankingAttributionPromotion?.strongest_rejection_lesson || "Continue rejection audit shadow-only.").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(candidateRankingAttributionPromotion?.shadow_recommendation || "Continue candidate ranking audit before any ranking influence.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Intelligence Quality & Learning Efficiency Suite V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is measuring which learning systems produce the most value, where confidence is weakest, and where ranking or exit tournaments show regret. This suite is advisory-only, shadow-analysis only, and does not change rankings, entries, exits, sizing, thresholds, paper execution, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Suite status", intelligenceQualityLearningEfficiency?.status],
            ["Highest value system", intelligenceQualityLearningEfficiency?.highest_value_learning_system],
            ["Weighted evidence", safeNumber(intelligenceQualityLearningEfficiency?.weighted_evidence_count).toFixed(0)],
            ["Weakest confidence", intelligenceQualityLearningEfficiency?.weakest_confidence_component],
            ["Drift warning", intelligenceQualityLearningEfficiency?.drift_warning],
            ["Most similar regime", intelligenceQualityLearningEfficiency?.most_similar_regime],
            ["Ranking regret", safeNumber(intelligenceQualityLearningEfficiency?.ranking_tournament_regret).toFixed(1)],
            ["Exit capture gap", safeNumber(intelligenceQualityLearningEfficiency?.exit_tournament_capture_gap).toFixed(1)],
            ["Conviction calibration", safeNumber(intelligenceQualityLearningEfficiency?.conviction_calibration_score).toFixed(1)],
            ["Recommended focus", intelligenceQualityLearningEfficiency?.recommended_next_focus],
            ["Ranking tournaments", safeNumber(intelligenceQualityLearningEfficiency?.ranking_tournament_count).toFixed(0)],
            ["Exit tournaments", safeNumber(intelligenceQualityLearningEfficiency?.exit_tournament_count).toFixed(0)],
            ["API/provider/LLM", `${safeNumber(intelligenceQualityLearningEfficiency?.api_calls_used).toFixed(0)} / ${safeNumber(intelligenceQualityLearningEfficiency?.provider_calls_used).toFixed(0)} / ${safeNumber(intelligenceQualityLearningEfficiency?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", intelligenceQualityLearningEfficiency?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Insufficient evidence modules: {(intelligenceQualityLearningEfficiency?.modules_reporting_insufficient_evidence || []).join(" | ").replaceAll("_", " ") || "none"}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Advanced Attribution, Controlled Exit Validation & Learning ROI Suite V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is synthesizing attribution, profit-capture leakage, controlled exit candidates, catalyst/sector/regime context, and learning ROI into one shadow-only diagnostic layer. This suite is learning-only and does not change rankings, entries, exits, sizing, allocations, paper execution, broker behavior, or Alpaca behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", advancedAttributionControlledExitLearningRoi?.status],
            ["Evidence", safeNumber(advancedAttributionControlledExitLearningRoi?.evidence_count).toFixed(0)],
            ["Profit loss driver", advancedAttributionControlledExitLearningRoi?.why_profits_are_being_lost],
            ["Buy purity leak", advancedAttributionControlledExitLearningRoi?.why_buy_purity_is_below_target],
            ["Exit underperformance", advancedAttributionControlledExitLearningRoi?.why_exits_underperform],
            ["Best exit candidate", advancedAttributionControlledExitLearningRoi?.best_exit_candidate],
            ["Exit validation", safeNumber(advancedAttributionControlledExitLearningRoi?.exit_validation_score).toFixed(1)],
            ["Policy readiness", safeNumber(advancedAttributionControlledExitLearningRoi?.policy_readiness_score).toFixed(1)],
            ["Highest ROI area", advancedAttributionControlledExitLearningRoi?.highest_roi_improvement_area],
            ["Estimated PF gain", safeNumber(advancedAttributionControlledExitLearningRoi?.estimated_pf_gain).toFixed(3)],
            ["Profit lost estimate", safeNumber(advancedAttributionControlledExitLearningRoi?.profit_lost_estimate).toFixed(1)],
            ["Lifecycle quality", safeNumber(advancedAttributionControlledExitLearningRoi?.lifecycle_quality_score).toFixed(1)],
            ["Catalyst coverage", safeNumber(advancedAttributionControlledExitLearningRoi?.catalyst_coverage).toFixed(1)],
            ["Unknown catalyst", safeNumber(advancedAttributionControlledExitLearningRoi?.unknown_catalyst_rate).toFixed(1)],
            ["Strongest sector", advancedAttributionControlledExitLearningRoi?.strongest_sector],
            ["Weakest sector", advancedAttributionControlledExitLearningRoi?.weakest_sector],
            ["Best regime", advancedAttributionControlledExitLearningRoi?.best_regime],
            ["Best sector/regime", advancedAttributionControlledExitLearningRoi?.best_sector_regime_pair],
            ["Policy candidate", advancedAttributionControlledExitLearningRoi?.future_policy_candidate_closest_to_readiness],
            ["API/provider/LLM", `${safeNumber(advancedAttributionControlledExitLearningRoi?.api_calls_used).toFixed(0)} / ${safeNumber(advancedAttributionControlledExitLearningRoi?.provider_calls_used).toFixed(0)} / ${safeNumber(advancedAttributionControlledExitLearningRoi?.llm_calls_used).toFixed(0)}`],
            ["Auto apply", advancedAttributionControlledExitLearningRoi?.auto_apply_allowed ? "yes" : "no"],
            ["Behavior safe", advancedAttributionControlledExitLearningRoi?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top loss drivers: {(advancedAttributionControlledExitLearningRoi?.top_loss_drivers || []).slice(0, 4).map((row) => `${String(row?.factor || "unknown").replaceAll("_", " ")} pressure ${safeNumber(row?.loss_pressure).toFixed(1)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit candidates: {(advancedAttributionControlledExitLearningRoi?.exit_candidate_rows || []).slice(0, 4).map((row) => `${String(row?.exit_style || "exit").replaceAll("_", " ")} score ${safeNumber(row?.validation_score).toFixed(1)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            ROI ranking: {(advancedAttributionControlledExitLearningRoi?.highest_roi_improvement_areas || []).slice(0, 4).map((row) => `${String(row?.area || "area").replaceAll("_", " ")} PF +${safeNumber(row?.potential_pf_improvement).toFixed(3)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended focus: {String(advancedAttributionControlledExitLearningRoi?.recommended_next_focus || "continue shadow attribution").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Profit Optimization & Context Intelligence Suite V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is comparing exit candidates, catalyst quality, buy-purity leakage, symbol/sector/regime profiles, opportunity cost, and interaction effects to decide what should be validated next. This is shadow-only, advisory-only, and does not change ranking, entries, exits, sizing, allocations, broker behavior, Alpaca behavior, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", profitOptimizationContextIntelligence?.status],
            ["Evidence", safeNumber(profitOptimizationContextIntelligence?.evidence_count).toFixed(0)],
            ["Best exit candidate", profitOptimizationContextIntelligence?.best_exit_candidate],
            ["Highest ROI area", profitOptimizationContextIntelligence?.highest_roi_improvement_area],
            ["Expected PF impact", safeNumber(profitOptimizationContextIntelligence?.expected_pf_impact ?? profitOptimizationContextIntelligence?.expected_pf_improvement).toFixed(3)],
            ["Avg return impact", safeNumber(profitOptimizationContextIntelligence?.expected_avg_return_impact ?? profitOptimizationContextIntelligence?.expected_avg_return_improvement).toFixed(3)],
            ["Giveback reduction", safeNumber(profitOptimizationContextIntelligence?.expected_giveback_reduction).toFixed(3)],
            ["Buy purity leak", profitOptimizationContextIntelligence?.highest_roi_purity_fix],
            ["Unknown catalyst trend", profitOptimizationContextIntelligence?.unknown_catalyst_trend],
            ["Catalyst reliability", safeNumber(profitOptimizationContextIntelligence?.catalyst_reliability_score).toFixed(1)],
            ["Best interaction", profitOptimizationContextIntelligence?.best_interaction_combo],
            ["Validate next", profitOptimizationContextIntelligence?.best_improvement_to_validate_next],
            ["Readiness", profitOptimizationContextIntelligence?.readiness_level],
            ["Confidence", safeNumber(profitOptimizationContextIntelligence?.confidence).toFixed(1)],
            ["Auto apply", profitOptimizationContextIntelligence?.auto_apply ? "yes" : "no"],
            ["API/provider/LLM", `${safeNumber(profitOptimizationContextIntelligence?.api_calls_used).toFixed(0)} / ${safeNumber(profitOptimizationContextIntelligence?.provider_calls_used).toFixed(0)} / ${safeNumber(profitOptimizationContextIntelligence?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", profitOptimizationContextIntelligence?.behavior_safe_to_apply ? "yes" : "no"],
            ["Paper execution changed", profitOptimizationContextIntelligence?.paper_execution_changed ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit candidates: {(profitOptimizationContextIntelligence?.exit_candidate_rows || []).slice(0, 5).map((row) => `${String(row?.exit_style || "exit").replaceAll("_", " ")} confidence ${safeNumber(row?.confidence).toFixed(1)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Purity leakage: {(profitOptimizationContextIntelligence?.purity_leakage_ranking || []).slice(0, 5).map((row) => `${String(row?.source || "source").replaceAll("_", " ")} ${safeNumber(row?.leakage_pct).toFixed(1)}%`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Interactions: {(profitOptimizationContextIntelligence?.interaction_rows || []).slice(0, 3).map((row) => `${String(row?.combo || "combo").replaceAll("_", " ")} PF ${safeNumber(row?.pf).toFixed(2)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Reasoning: {String(profitOptimizationContextIntelligence?.reasoning_summary || "Continue shadow-only profit optimization diagnostics.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Trade Lifecycle Audit, Truth Validation & Horizon Integrity Suite V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is auditing every active Alpaca paper position to explain why it is still holding, whether the hold is intentional or drifting, and whether horizon integrity needs review. This panel is diagnostic-only and does not change broker behavior, ranking, entries, exits, sizing, thresholds, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", tradeLifecycleAuditTruthHorizonIntegrity?.status],
            ["Active positions", safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.total_active_positions).toFixed(0)],
            ["Rows audited", safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.position_rows_audited).toFixed(0)],
            ["Broker confirmed", safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.broker_confirmed_positions).toFixed(0)],
            ["Stale internal rows", safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.stale_internal_rows).toFixed(0)],
            ["Avg hold", `${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.average_hold_duration_days).toFixed(1)}d`],
            ["Oldest", tradeLifecycleAuditTruthHorizonIntegrity?.oldest_position],
            ["Most overdue", tradeLifecycleAuditTruthHorizonIntegrity?.most_overdue_position],
            ["Most profitable", `${String(tradeLifecycleAuditTruthHorizonIntegrity?.most_profitable_position || "n/a")} ${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.most_profitable_position_pct).toFixed(1)}%`],
            ["Highest giveback", tradeLifecycleAuditTruthHorizonIntegrity?.highest_giveback_risk_position],
            ["Top blocker", tradeLifecycleAuditTruthHorizonIntegrity?.biggest_exit_blocker],
            ["Dominant horizon", tradeLifecycleAuditTruthHorizonIntegrity?.dominant_active_horizon],
            ["Overdue", `${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.active_overdue_pct).toFixed(1)}%`],
            ["Repurchase today", `${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.would_repurchase_today_pct).toFixed(1)}%`],
            ["Horizon integrity", tradeLifecycleAuditTruthHorizonIntegrity?.horizon_integrity_needed ? "needed" : "not needed"],
            ["API/provider/LLM", `${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.api_calls_used).toFixed(0)} / ${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.provider_calls_used).toFixed(0)} / ${safeNumber(tradeLifecycleAuditTruthHorizonIntegrity?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", tradeLifecycleAuditTruthHorizonIntegrity?.behavior_safe_to_apply ? "yes" : "no"],
            ["Paper execution changed", tradeLifecycleAuditTruthHorizonIntegrity?.paper_execution_changed ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Hold assessment: {String(tradeLifecycleAuditTruthHorizonIntegrity?.is_astra_holding_everything_too_long || "insufficient data").replaceAll("_", " ")} | {String(tradeLifecycleAuditTruthHorizonIntegrity?.intentionally_holding_or_drifting || "insufficient data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            ROI fix: {String(tradeLifecycleAuditTruthHorizonIntegrity?.single_highest_roi_fix || "continue truth audit").replaceAll("_", " ")} | Next: {String(tradeLifecycleAuditTruthHorizonIntegrity?.safest_next_implementation || "review only diagnostics").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Active holds: {(tradeLifecycleAuditTruthHorizonIntegrity?.position_audit_rows || []).slice(0, 6).map((row) => `${String(row?.symbol || "symbol")} ${String(row?.normalized_horizon || "unknown").replaceAll("_", " ")} ${safeNumber(row?.pnl_percent).toFixed(1)}%: ${String(row?.why_still_holding || "warming up").replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Truth audit: {(tradeLifecycleAuditTruthHorizonIntegrity?.truth_validation_rows || []).slice(0, 6).map((row) => `${String(row?.symbol || "symbol")} ideal ${String(row?.ideal_action || "hold").replaceAll("_", " ")} confidence ${safeNumber(row?.truth_confidence).toFixed(1)}`).join(" | ") || "warming up"}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Tier 1 Foundation Stabilization & Governance Bundle V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is verifying trading integrity, exit visibility, profit-capture truth, capital efficiency, internal audit, operations oversight, resource governance, system registry, and knowledge preservation. This bundle is advisory-only and does not change broker behavior, ranking, entries, exits, sizing, thresholds, allocation, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraFoundationStabilizationGovernance?.status],
            ["Unknown horizons", safeNumber(astraFoundationStabilizationGovernance?.unknown_horizon_positions).toFixed(0)],
            ["Horizon inference fix", astraFoundationStabilizationGovernance?.infer_horizon_style_reads_paper_entry_horizon_style ? "verified" : "not verified"],
            ["Broker source of truth", astraFoundationStabilizationGovernance?.broker_confirmed_positions_source_of_truth ? "yes" : "no"],
            ["Stale rows distort active", astraFoundationStabilizationGovernance?.stale_internal_rows_distort_active_positions ? "yes" : "no"],
            ["Learned exit candidates", safeNumber(astraFoundationStabilizationGovernance?.learned_exit_candidates_today).toFixed(0)],
            ["Candidate diagnosis", astraFoundationStabilizationGovernance?.learned_exit_candidates_today_diagnosis],
            ["Exit due", safeNumber(astraFoundationStabilizationGovernance?.horizon_exit_due_count).toFixed(0)],
            ["Conversion candidates", safeNumber(astraFoundationStabilizationGovernance?.horizon_conversion_candidate_count).toFixed(0)],
            ["Biggest exit blocker", astraFoundationStabilizationGovernance?.biggest_exit_blocker],
            ["Biggest profit leak", astraFoundationStabilizationGovernance?.biggest_profit_capture_leak],
            ["Giveback", safeNumber(astraFoundationStabilizationGovernance?.giveback).toFixed(2)],
            ["Capture ratio", safeNumber(astraFoundationStabilizationGovernance?.capture_ratio).toFixed(3)],
            ["Trapped capital", astraFoundationStabilizationGovernance?.trapped_capital_status],
            ["Oversight governor", astraFoundationStabilizationGovernance?.oversight_governor_status],
            ["API governor", astraFoundationStabilizationGovernance?.api_governor_status],
            ["Registry", `${String(astraFoundationStabilizationGovernance?.registry_status || "warming up").replaceAll("_", " ")} (${safeNumber(astraFoundationStabilizationGovernance?.registered_system_count).toFixed(0)})`],
            ["Knowledge preservation", astraFoundationStabilizationGovernance?.knowledge_preservation_status],
            ["Dashboard provider calls", safeNumber(astraFoundationStabilizationGovernance?.dashboard_provider_calls_used).toFixed(0)],
            ["Behavior safe", astraFoundationStabilizationGovernance?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Horizon exit candidates: {(astraFoundationStabilizationGovernance?.horizon_exit_candidate_rows || []).slice(0, 6).map((row) => `${String(row?.symbol || "symbol")} ${String(row?.horizon || "unknown").replaceAll("_", " ")} due ${row?.exit_due ? "yes" : "no"}: ${String(row?.reason || "warming up").replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit pipeline: generated {safeNumber(astraFoundationStabilizationGovernance?.generated_exits).toFixed(0)}, suppressed {safeNumber(astraFoundationStabilizationGovernance?.suppressed_exits).toFixed(0)}, blocked {safeNumber(astraFoundationStabilizationGovernance?.blocked_exits).toFixed(0)}, rejected {safeNumber(astraFoundationStabilizationGovernance?.rejected_exits).toFixed(0)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Registered systems: {(astraFoundationStabilizationGovernance?.registered_systems || []).slice(0, 6).map((row) => `${String(row?.system_name || "system")} (${String(row?.owner || "owner")})`).join(" | ") || "warming up"}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Tier 2A Librarian, Executive Assistant & Unified Truth Layer V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is compressing existing intelligence into deduplicated lessons, retrieval indexes, master truths, and executive-priority insights. This section is shadow-only, advisory-only, and does not change rankings, entries, exits, sizing, allocations, broker behavior, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraTier2aLibrarianExecutiveTruthLayer?.status],
            ["Source systems reviewed", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.source_systems_reviewed).toFixed(0)],
            ["Lessons organized", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.lessons_organized).toFixed(0)],
            ["Duplicate findings reduced", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.duplicate_findings_reduced).toFixed(0)],
            ["Master truths", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.master_truths_created).toFixed(0)],
            ["Retrieval indexes", astraTier2aLibrarianExecutiveTruthLayer?.retrieval_indexes_created ? `${safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.retrieval_index_count).toFixed(0)} created` : "warming up"],
            ["Compression", astraTier2aLibrarianExecutiveTruthLayer?.compression_status],
            ["Executive Assistant", astraTier2aLibrarianExecutiveTruthLayer?.executive_assistant_status],
            ["Unified Truth", astraTier2aLibrarianExecutiveTruthLayer?.unified_truth_status],
            ["Strongest truth", astraTier2aLibrarianExecutiveTruthLayer?.strongest_master_truth],
            ["Tier 1 integration", astraTier2aLibrarianExecutiveTruthLayer?.tier1_integration_status],
            ["Shadow Lab integration", astraTier2aLibrarianExecutiveTruthLayer?.shadow_lab_integration_status],
            ["Dashboard calls added", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.dashboard_api_calls_added).toFixed(0)],
            ["Provider calls", safeNumber(astraTier2aLibrarianExecutiveTruthLayer?.provider_calls_used).toFixed(0)],
            ["Endpoint storm", astraTier2aLibrarianExecutiveTruthLayer?.dashboard_endpoint_storm_created ? "yes" : "no"],
            ["Behavior safe", astraTier2aLibrarianExecutiveTruthLayer?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top executive insights: {(astraTier2aLibrarianExecutiveTruthLayer?.top_5_insights || []).slice(0, 5).map((row) => `${String(row?.priority || "MEDIUM")}: ${String(row?.issue || "issue")} - ${String(row?.recommended_focus || "review").replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Master truths: {(astraTier2aLibrarianExecutiveTruthLayer?.master_issues || []).slice(0, 6).map((row) => `${String(row?.issue || "issue")} (${safeNumber(row?.confidence).toFixed(0)}%, ${safeNumber(row?.evidence_sources).toFixed(0)} sources)`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Registered Tier 2A systems: {(astraTier2aLibrarianExecutiveTruthLayer?.registered_systems || []).slice(0, 5).map((row) => `${String(row?.system_name || "system")} (${String(row?.owner || "owner")})`).join(" | ") || "warming up"}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Tier 2B Satellites 1-4 & Satellite Coordinator V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra’s first satellite network gathers market structure, sector rotation, catalyst, and trade-family context, compresses findings, and passes summaries through the Librarian, Unified Truth, and Executive Assistant chain. Satellites are shadow-only information systems and never influence trades, rankings, broker behavior, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraSatelliteNetwork?.status],
            ["Coordinator", astraSatelliteNetwork?.coordinator_status],
            ["Coordinator health", astraSatelliteNetwork?.coordinator_health],
            ["Satellites registered", safeNumber(astraSatelliteNetwork?.satellites_registered).toFixed(0)],
            ["Compression", astraSatelliteNetwork?.compression_status],
            ["Compressed lessons", safeNumber(astraSatelliteNetwork?.compressed_lessons_count).toFixed(0)],
            ["Duplicates prevented", safeNumber(astraSatelliteNetwork?.duplicates_prevented).toFixed(0)],
            ["Market Structure", astraSatelliteNetwork?.market_structure_status],
            ["Sector Rotation", astraSatelliteNetwork?.sector_rotation_status],
            ["Catalyst", astraSatelliteNetwork?.catalyst_status],
            ["Trade Family", astraSatelliteNetwork?.trade_family_status],
            ["Bandwidth impact", astraSatelliteNetwork?.bandwidth_impact],
            ["Provider/API impact", astraSatelliteNetwork?.provider_api_impact],
            ["Provider calls", safeNumber(astraSatelliteNetwork?.provider_calls_used).toFixed(0)],
            ["Endpoint storm", astraSatelliteNetwork?.dashboard_endpoint_storm_created ? "yes" : "no"],
            ["Behavior safe", astraSatelliteNetwork?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Satellite health: {(astraSatelliteNetwork?.satellite_statuses || astraSatelliteNetwork?.satellite_health_rows || []).slice(0, 4).map((row) => `${String(row?.satellite_name || "satellite")} ${String(row?.health || "warming up").replaceAll("_", " ")} (${safeNumber(row?.confidence).toFixed(0)}%)`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Market summary: {String(astraSatelliteNetwork?.market_structure_summary || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Sector summary: {String(astraSatelliteNetwork?.sector_rotation_summary || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Catalyst summary: {String(astraSatelliteNetwork?.catalyst_summary || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Trade-family summary: {String(astraSatelliteNetwork?.trade_family_summary || "warming up").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Tier 3 Historical Intelligence, Satellite Expansion & Shadow Acceleration V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is expanding years-of-experience style knowledge through compressed historical lessons, satellites 5-10, and shadow experiment units. Tier 3 remains advisory-only, shadow-only, cache-first, and routes compressed outputs through the Librarian, Unified Truth Layer, and Executive Assistant before Astra Brain.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraTier3HistoricalSatelliteShadowAcceleration?.status],
            ["Historical expansion", astraTier3HistoricalSatelliteShadowAcceleration?.historical_intelligence_status],
            ["Satellites registered", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.satellites_registered).toFixed(0)],
            ["Coordinator", astraTier3HistoricalSatelliteShadowAcceleration?.satellite_coordinator_status],
            ["Coordinator health", astraTier3HistoricalSatelliteShadowAcceleration?.satellite_coordinator_health],
            ["Shadow units", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.shadow_experiment_units).toFixed(0)],
            ["Shadow expansion", astraTier3HistoricalSatelliteShadowAcceleration?.shadow_experiment_expansion_status],
            ["Historical replays", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.historical_replays).toFixed(0)],
            ["Virtual exit tests", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.virtual_exit_tests).toFixed(0)],
            ["Horizon tests", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.horizon_tests).toFixed(0)],
            ["Compressed lessons", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.compressed_lessons_created).toFixed(0)],
            ["Compression", astraTier3HistoricalSatelliteShadowAcceleration?.compression_status],
            ["Bandwidth", astraTier3HistoricalSatelliteShadowAcceleration?.bandwidth_status],
            ["Provider calls", safeNumber(astraTier3HistoricalSatelliteShadowAcceleration?.provider_calls_used).toFixed(0)],
            ["Endpoint storm", astraTier3HistoricalSatelliteShadowAcceleration?.dashboard_endpoint_storm_created ? "yes" : "no"],
            ["Behavior safe", astraTier3HistoricalSatelliteShadowAcceleration?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Satellites 5-10: {(astraTier3HistoricalSatelliteShadowAcceleration?.satellites_added || []).slice(0, 6).map((name) => String(name).replaceAll("_", " ")).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top historical lesson: {String(astraTier3HistoricalSatelliteShadowAcceleration?.top_historical_lesson || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top satellite insight: {String(astraTier3HistoricalSatelliteShadowAcceleration?.top_satellite_insight || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top shadow lesson: {String(astraTier3HistoricalSatelliteShadowAcceleration?.top_shadow_lesson || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Integration: Librarian {String(astraTier3HistoricalSatelliteShadowAcceleration?.librarian_integration_status || "warming up").replaceAll("_", " ")}, Unified Truth {String(astraTier3HistoricalSatelliteShadowAcceleration?.unified_truth_integration_status || "warming up").replaceAll("_", " ")}, Executive Assistant {String(astraTier3HistoricalSatelliteShadowAcceleration?.executive_assistant_integration_status || "warming up").replaceAll("_", " ")}.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Final Intelligence Maturation Bundle V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra’s final major architecture bundle compresses knowledge, matures historical memory, prioritizes learning focus, coordinates safe research, monitors health, and keeps profit improvement advisory-only. This is shadow-only and does not change rankings, entries, exits, sizing, thresholds, broker behavior, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraFinalIntelligenceMaturation?.status],
            ["Compression", astraFinalIntelligenceMaturation?.compression_status],
            ["Compressed lessons", safeNumber(astraFinalIntelligenceMaturation?.compressed_lessons).toFixed(0)],
            ["Compression efficiency", `${safeNumber(astraFinalIntelligenceMaturation?.compression_efficiency).toFixed(1)}%`],
            ["Historical maturity", astraFinalIntelligenceMaturation?.historical_maturity_status],
            ["Memory maturity", safeNumber(astraFinalIntelligenceMaturation?.memory_maturity).toFixed(1)],
            ["Retrieval accuracy", safeNumber(astraFinalIntelligenceMaturation?.retrieval_accuracy).toFixed(1)],
            ["Learning priority", astraFinalIntelligenceMaturation?.learning_prioritization_status],
            ["Research department", astraFinalIntelligenceMaturation?.research_department_status],
            ["Research studies", `${safeNumber(astraFinalIntelligenceMaturation?.completed_research_studies).toFixed(0)} / ${safeNumber(astraFinalIntelligenceMaturation?.research_studies).toFixed(0)}`],
            ["Portfolio intelligence", astraFinalIntelligenceMaturation?.portfolio_intelligence_status],
            ["Capital efficiency", safeNumber(astraFinalIntelligenceMaturation?.capital_efficiency_score).toFixed(1)],
            ["Self optimization", astraFinalIntelligenceMaturation?.self_optimization_status],
            ["Health monitoring", astraFinalIntelligenceMaturation?.health_monitoring_status],
            ["Expected PF lift", safeNumber(astraFinalIntelligenceMaturation?.expected_pf_improvement).toFixed(3)],
            ["Provider calls", safeNumber(astraFinalIntelligenceMaturation?.provider_calls_used).toFixed(0)],
            ["LLM calls", safeNumber(astraFinalIntelligenceMaturation?.llm_calls_used).toFixed(0)],
            ["Endpoint storm", astraFinalIntelligenceMaturation?.dashboard_endpoint_storm_created ? "yes" : "no"],
            ["Behavior safe", astraFinalIntelligenceMaturation?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Focus allocation: {Object.entries(astraFinalIntelligenceMaturation?.attention_allocation_pct || {}).map(([key, value]) => `${String(key).replaceAll("_", " ")} ${safeNumber(value).toFixed(0)}%`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Self-optimization: weakness {String(astraFinalIntelligenceMaturation?.top_weakness || "warming up").replaceAll("_", " ")}, opportunity {String(astraFinalIntelligenceMaturation?.top_opportunity || "warming up").replaceAll("_", " ")}, bottleneck {String(astraFinalIntelligenceMaturation?.top_bottleneck || "warming up").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Profit focus: {(astraFinalIntelligenceMaturation?.focus_areas || []).slice(0, 5).map((name) => String(name).replaceAll("_", " ")).join(" | ") || "warming up"}; expected capture improvement {safeNumber(astraFinalIntelligenceMaturation?.expected_capture_improvement_pct).toFixed(2)}%, giveback reduction {safeNumber(astraFinalIntelligenceMaturation?.expected_giveback_reduction_pct).toFixed(2)}%, exit improvement {safeNumber(astraFinalIntelligenceMaturation?.expected_exit_improvement_pct).toFixed(2)}%.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Integration: Librarian {String(astraFinalIntelligenceMaturation?.librarian_integration_status || "warming up").replaceAll("_", " ")}, Unified Truth {String(astraFinalIntelligenceMaturation?.unified_truth_integration_status || "warming up").replaceAll("_", " ")}, Executive Assistant {String(astraFinalIntelligenceMaturation?.executive_assistant_integration_status || "warming up").replaceAll("_", " ")}, Astra Brain {String(astraFinalIntelligenceMaturation?.astra_brain_integration_status || "warming up").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(astraFinalIntelligenceMaturation?.intelligence_summary || astraFinalIntelligenceMaturation?.recommended_next_focus || "warming up").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Targeted Maturity & Profit-Capture Optimization Bundle V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is consolidating horizon management, exit review, profit capture, root-cause analysis, intelligence throughput, saturation, and safe universe recommendations. This section is advisory-only, shadow-only, cache-first, and does not change rankings, entries, exits, sizing, allocations, thresholds, broker behavior, or paper execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraTargetedMaturityProfitCapture?.status],
            ["Horizon status", astraTargetedMaturityProfitCapture?.horizon_status],
            ["Positions reviewed", safeNumber(astraTargetedMaturityProfitCapture?.positions_reviewed).toFixed(0)],
            ["Horizon drift", safeNumber(astraTargetedMaturityProfitCapture?.horizon_drift_count).toFixed(0)],
            ["Exit quality", astraTargetedMaturityProfitCapture?.exit_quality_status],
            ["Review-only exits", safeNumber(astraTargetedMaturityProfitCapture?.review_only_exit_candidates).toFixed(0)],
            ["Profit capture", astraTargetedMaturityProfitCapture?.profit_capture_status],
            ["Capture ratio", safeNumber(astraTargetedMaturityProfitCapture?.capture_ratio).toFixed(1)],
            ["Avg giveback", safeNumber(astraTargetedMaturityProfitCapture?.giveback).toFixed(1)],
            ["Top root cause", astraTargetedMaturityProfitCapture?.top_root_cause],
            ["Duplicate findings", safeNumber(astraTargetedMaturityProfitCapture?.duplicate_findings_detected).toFixed(0)],
            ["Merged findings", safeNumber(astraTargetedMaturityProfitCapture?.merged_findings).toFixed(0)],
            ["Throughput", astraTargetedMaturityProfitCapture?.throughput_meter_status],
            ["Efficiency ratio", safeNumber(astraTargetedMaturityProfitCapture?.intelligence_efficiency_ratio).toFixed(1)],
            ["Saturation", `${safeNumber(astraTargetedMaturityProfitCapture?.saturation_percentage).toFixed(1)}%`],
            ["Safe expansion", `${safeNumber(astraTargetedMaturityProfitCapture?.safe_expansion_capacity).toFixed(1)}%`],
            ["Next universe", safeNumber(astraTargetedMaturityProfitCapture?.next_safe_universe_target).toFixed(0)],
            ["Expected PF lift", safeNumber(astraTargetedMaturityProfitCapture?.expected_pf_improvement).toFixed(3)],
            ["Provider calls", safeNumber(astraTargetedMaturityProfitCapture?.provider_calls_used).toFixed(0)],
            ["LLM calls", safeNumber(astraTargetedMaturityProfitCapture?.llm_calls_used).toFixed(0)],
            ["Endpoint storm", astraTargetedMaturityProfitCapture?.dashboard_endpoint_storm_created ? "yes" : "no"],
            ["Behavior safe", astraTargetedMaturityProfitCapture?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Executive summary: {String(astraTargetedMaturityProfitCapture?.executive_summary || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Profit capture: biggest giveback {String(astraTargetedMaturityProfitCapture?.biggest_giveback_symbol || "unknown").replaceAll("_", " ")}, biggest leak {String(astraTargetedMaturityProfitCapture?.biggest_capture_leak || "warming up").replaceAll("_", " ")}, best protection candidate {String(astraTargetedMaturityProfitCapture?.best_profit_protection_candidate || "warming up").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Root cause: {String(astraTargetedMaturityProfitCapture?.top_root_cause || "warming up").replaceAll("_", " ")} affecting {(astraTargetedMaturityProfitCapture?.affected_metrics || []).slice(0, 6).map((name) => String(name).replaceAll("_", " ")).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Learning Center departments: {(astraTargetedMaturityProfitCapture?.departments || []).slice(0, 9).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Universe recommendation: current {safeNumber(astraTargetedMaturityProfitCapture?.current_universe).toFixed(0)}, next safe target {safeNumber(astraTargetedMaturityProfitCapture?.next_safe_universe_target).toFixed(0)}, mature target {String(astraTargetedMaturityProfitCapture?.mature_universe_target || "warming up").replaceAll("_", " ")}. {String(astraTargetedMaturityProfitCapture?.dynamic_universe_recommendation || "recommendation only").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Flow: {String(astraTargetedMaturityProfitCapture?.integration_flow || "Satellites/Historical/Shadow -> Librarian -> Unified Truth -> Executive Assistant -> Astra Brain").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra Horizon Lifecycle, Capacity Recycling & Promotion Readiness Bundle V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is reconciling broker-confirmed active positions with lifecycle audit rows, measuring scalp/day/swing learning balance, and preparing future horizon behavior through shadow readiness only. This panel is paper-safe, advisory-first, human-review required, and does not enable broker sells, learned exits, ranking changes, entry changes, sizing changes, allocation changes, or threshold changes.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraHorizonLifecycleCapacityPromotion?.status],
            ["Repair status", astraHorizonLifecycleCapacityPromotion?.repair_status],
            ["Position source", astraHorizonLifecycleCapacityPromotion?.active_position_source],
            ["Broker confirmed", safeNumber(astraHorizonLifecycleCapacityPromotion?.broker_confirmed_count).toFixed(0)],
            ["Rows audited", safeNumber(astraHorizonLifecycleCapacityPromotion?.lifecycle_rows_audited).toFixed(0)],
            ["Stale rows hidden", safeNumber(astraHorizonLifecycleCapacityPromotion?.stale_internal_rows_hidden).toFixed(0)],
            ["Unknown horizons", safeNumber(astraHorizonLifecycleCapacityPromotion?.unknown_horizon_positions).toFixed(0)],
            ["Conservative horizon repairs", safeNumber(astraHorizonLifecycleCapacityPromotion?.conservatively_classified_unknown_broker_rows).toFixed(0)],
            ["Capacity", astraHorizonLifecycleCapacityPromotion?.horizon_capacity_status],
            ["Total used", `${safeNumber(astraHorizonLifecycleCapacityPromotion?.total_used).toFixed(0)} / ${safeNumber(astraHorizonLifecycleCapacityPromotion?.total_capacity, 20).toFixed(0)}`],
            ["Scalp slots", safeNumber(astraHorizonLifecycleCapacityPromotion?.scalp_slots_used).toFixed(0)],
            ["Day slots", safeNumber(astraHorizonLifecycleCapacityPromotion?.day_trade_slots_used).toFixed(0)],
            ["Swing slots", safeNumber(astraHorizonLifecycleCapacityPromotion?.swing_slots_used).toFixed(0)],
            ["Underexposed", astraHorizonLifecycleCapacityPromotion?.underexposed_horizon],
            ["Overexposed", astraHorizonLifecycleCapacityPromotion?.overexposed_horizon],
            ["Preferred next", astraHorizonLifecycleCapacityPromotion?.preferred_next_horizon],
            ["Capacity mode", astraHorizonLifecycleCapacityPromotion?.capacity_mode],
            ["Rebalance status", astraHorizonLifecycleCapacityPromotion?.capacity_rebalance_status],
            ["Assignment used", astraHorizonLifecycleCapacityPromotion?.horizon_assignment_used ? "yes" : "no"],
            ["Assignment confidence", safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_assignment_confidence).toFixed(1)],
            ["Execution candidate", astraHorizonLifecycleCapacityPromotion?.horizon_execution_candidate?.symbol || "warming up"],
            ["Execution reason", astraHorizonLifecycleCapacityPromotion?.horizon_execution_reason],
            ["Execution blocker", astraHorizonLifecycleCapacityPromotion?.horizon_execution_blocker],
            ["Dropoff point", astraHorizonLifecycleCapacityPromotion?.horizon_assignment_dropoff_point],
            ["Tie-break blocker", astraHorizonLifecycleCapacityPromotion?.paper_tie_breaker_blocker],
            ["Practice blocker", astraHorizonLifecycleCapacityPromotion?.practice_bucket_blocker],
            ["Next fix", astraHorizonLifecycleCapacityPromotion?.next_required_fix],
            ["Participation score", safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_participation_score).toFixed(1)],
            ["Stale positions", safeNumber(astraHorizonLifecycleCapacityPromotion?.stale_positions_count).toFixed(0)],
            ["Trapped capital", safeNumber(astraHorizonLifecycleCapacityPromotion?.capital_trapped_score).toFixed(1)],
            ["Learning access", safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_learning_access_score).toFixed(1)],
            ["Profit retention", safeNumber(astraHorizonLifecycleCapacityPromotion?.profit_retention_score).toFixed(1)],
            ["Giveback score", safeNumber(astraHorizonLifecycleCapacityPromotion?.giveback_score).toFixed(1)],
            ["Lifecycle efficiency", safeNumber(astraHorizonLifecycleCapacityPromotion?.lifecycle_efficiency_score).toFixed(1)],
            ["Regime bias", astraHorizonLifecycleCapacityPromotion?.horizon_market_bias],
            ["Recycling", astraHorizonLifecycleCapacityPromotion?.dynamic_recycling_status],
            ["Recycled slots", safeNumber(astraHorizonLifecycleCapacityPromotion?.recycled_slots_available).toFixed(0)],
            ["Exposure balance", astraHorizonLifecycleCapacityPromotion?.horizon_exposure_balance],
            ["Balance score", safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_learning_balance_score).toFixed(1)],
            ["Top learning gap", astraHorizonLifecycleCapacityPromotion?.top_learning_exposure_gap],
            ["Practice bucket", astraHorizonLifecycleCapacityPromotion?.practice_bucket_status],
            ["Exit readiness", astraHorizonLifecycleCapacityPromotion?.exit_readiness_status],
            ["Provider calls", safeNumber(astraHorizonLifecycleCapacityPromotion?.provider_calls_used).toFixed(0)],
            ["LLM calls", safeNumber(astraHorizonLifecycleCapacityPromotion?.llm_calls_used).toFixed(0)],
            ["Paper sell enabled", astraHorizonLifecycleCapacityPromotion?.paper_sell_behavior_enabled ? "yes" : "no"],
            ["Learned exits", astraHorizonLifecycleCapacityPromotion?.learned_exits_enabled ? "yes" : "no"],
            ["Behavior safe", astraHorizonLifecycleCapacityPromotion?.behavior_safe_to_apply ? "yes" : "no"],
            ["True paper PF", safeNumber(astraHorizonLifecycleCapacityPromotion?.true_paper_pf).toFixed(3)],
            ["Learning PF", safeNumber(astraHorizonLifecycleCapacityPromotion?.learning_pf).toFixed(3)],
            ["Shadow PF", safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_pf || astraHorizonLifecycleCapacityPromotion?.shadow_expected_pf).toFixed(3)],
            ["Previous PF source", astraHorizonLifecycleCapacityPromotion?.previous_pf_source],
            ["New PF source", astraHorizonLifecycleCapacityPromotion?.new_pf_source],
            ["PF source", astraHorizonLifecycleCapacityPromotion?.displayed_dashboard_pf_source],
            ["PF trust", astraHorizonLifecycleCapacityPromotion?.displayed_dashboard_pf_trust_level],
            ["Metric reconciliation", astraHorizonLifecycleCapacityPromotion?.metric_reconciliation_status],
            ["Metric mismatch", astraHorizonLifecycleCapacityPromotion?.metric_scope_mismatch_detected ? "yes" : "no"],
            ["Session refresh", astraHorizonLifecycleCapacityPromotion?.session_refresh_status],
            ["Session stale", astraHorizonLifecycleCapacityPromotion?.session_is_stale ? "yes" : "no"],
            ["Session cache age", safeNumber(astraHorizonLifecycleCapacityPromotion?.session_cache_age).toFixed(1)],
            ["Active workflow rows", safeNumber(astraHorizonLifecycleCapacityPromotion?.active_workflow_rows).toFixed(0)],
            ["Archived workflow rows", safeNumber(astraHorizonLifecycleCapacityPromotion?.archived_workflow_rows).toFixed(0)],
            ["Stale rows compacted", safeNumber(astraHorizonLifecycleCapacityPromotion?.stale_rows_compacted).toFixed(0)],
            ["Archive retrieval", astraHorizonLifecycleCapacityPromotion?.archive_retrieval_health],
            ["Catalyst coverage", `${safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_coverage_pct).toFixed(1)}%`],
            ["Unknown catalysts", `${safeNumber(astraHorizonLifecycleCapacityPromotion?.unknown_catalyst_rate).toFixed(1)}%`],
            ["Catalyst readiness", safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_readiness_score).toFixed(1)],
            ["Catalyst improvement", safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_improvement_rate).toFixed(1)],
            ["Catalyst gap", astraHorizonLifecycleCapacityPromotion?.catalyst_learning_gap],
            ["Best exit policy", astraHorizonLifecycleCapacityPromotion?.best_exit_policy_candidate],
            ["Exit readiness", safeNumber(astraHorizonLifecycleCapacityPromotion?.exit_policy_readiness_score).toFixed(1)],
            ["Giveback opportunity", safeNumber(astraHorizonLifecycleCapacityPromotion?.giveback_reduction_opportunity).toFixed(1)],
            ["Capture improvement", safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_profit_capture_improvement).toFixed(1)],
            ["Promotion score", safeNumber(astraHorizonLifecycleCapacityPromotion?.promotion_readiness_score).toFixed(1)],
            ["Promotion candidates", safeNumber(astraHorizonLifecycleCapacityPromotion?.promotion_candidate_count).toFixed(0)],
            ["Promotion ROI", safeNumber(astraHorizonLifecycleCapacityPromotion?.promotion_roi).toFixed(1)],
            ["Shadow consensus", safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_consensus).toFixed(1)],
            ["Paper consensus", safeNumber(astraHorizonLifecycleCapacityPromotion?.paper_consensus).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Horizon distribution: {Object.entries(astraHorizonLifecycleCapacityPromotion?.horizon_distribution || {}).map(([key, value]) => `${String(key).replaceAll("_", " ")} ${safeNumber(value).toFixed(1)}%`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Performance Truth Layer: true paper PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.true_paper_pf).toFixed(3)} from {String(astraHorizonLifecycleCapacityPromotion?.true_paper_metric_source || "unavailable").replaceAll("_", " ")}, learning PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.learning_pf).toFixed(3)}, shadow PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_pf || astraHorizonLifecycleCapacityPromotion?.shadow_expected_pf).toFixed(3)}. Safest display: {String(astraHorizonLifecycleCapacityPromotion?.safest_metric_to_show_user || "label learning PF as learning metric").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Source repair: previous PF source {String(astraHorizonLifecycleCapacityPromotion?.previous_pf_source || "unknown").replaceAll("_", " ")}; new PF source {String(astraHorizonLifecycleCapacityPromotion?.new_pf_source || "broker_truth_engine_v1").replaceAll("_", " ")}; trust {String(astraHorizonLifecycleCapacityPromotion?.true_paper_metric_trust_level || "insufficient broker confirmed evidence").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Assigned horizons today: {Object.entries(astraHorizonLifecycleCapacityPromotion?.assigned_horizons_today || {}).map(([key, value]) => `${String(key).replaceAll("_", " ")} ${safeNumber(value).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow candidates: scalp {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_scalp_candidates).toFixed(0)}, day {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_day_trade_candidates).toFixed(0)}, swing {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_swing_trade_candidates).toFixed(0)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Qualified candidates: scalp {safeNumber(astraHorizonLifecycleCapacityPromotion?.qualified_scalp_candidates).toFixed(0)}, day {safeNumber(astraHorizonLifecycleCapacityPromotion?.qualified_day_trade_candidates).toFixed(0)}, swing {safeNumber(astraHorizonLifecycleCapacityPromotion?.qualified_swing_trade_candidates).toFixed(0)}; missing horizon fields {safeNumber(astraHorizonLifecycleCapacityPromotion?.missing_horizon_field_count).toFixed(0)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Missing horizon examples: {(astraHorizonLifecycleCapacityPromotion?.missing_horizon_field_examples || []).join(", ") || "none"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top stale positions: {(astraHorizonLifecycleCapacityPromotion?.top_stale_positions || []).map((row) => `${row?.symbol || "unknown"} ${safeNumber(row?.stale_score).toFixed(1)}`).join(" | ") || "none"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Best replacements: {(astraHorizonLifecycleCapacityPromotion?.best_replacement_candidates || []).map((row) => `${row?.symbol || "unknown"} ${safeNumber(row?.replacement_score).toFixed(1)}`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Learning access: scalp blocked {astraHorizonLifecycleCapacityPromotion?.scalp_learning_blocked ? "yes" : "no"}; day blocked {astraHorizonLifecycleCapacityPromotion?.day_learning_blocked ? "yes" : "no"}; swing overconcentration {astraHorizonLifecycleCapacityPromotion?.swing_overconcentration ? "yes" : "no"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Horizon participation: {String(astraHorizonLifecycleCapacityPromotion?.horizon_participation_recommendation || "maintain adaptive horizon learning").replaceAll("_", " ")}; blocker {String(astraHorizonLifecycleCapacityPromotion?.horizon_participation_blocker || "none").replaceAll("_", " ")}. This remains tie-breaker/advisory only and does not bypass ranking or safety gates.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Session repair: {String(astraHorizonLifecycleCapacityPromotion?.session_refresh_status || "cache fresh").replaceAll("_", " ")}; reason {String(astraHorizonLifecycleCapacityPromotion?.session_refresh_reason || "market session cache valid").replaceAll("_", " ")}; recovery {String(astraHorizonLifecycleCapacityPromotion?.session_recovery_status || "healthy").replaceAll("_", " ")}; last rebuild {String(astraHorizonLifecycleCapacityPromotion?.session_last_rebuild || "warming up").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Workflow compaction: active {safeNumber(astraHorizonLifecycleCapacityPromotion?.active_workflow_rows).toFixed(0)}, archived {safeNumber(astraHorizonLifecycleCapacityPromotion?.archived_workflow_rows).toFixed(0)}, stale compacted {safeNumber(astraHorizonLifecycleCapacityPromotion?.stale_rows_compacted).toFixed(0)}, hidden {safeNumber(astraHorizonLifecycleCapacityPromotion?.stale_rows_hidden).toFixed(0)}, archive integrity {astraHorizonLifecycleCapacityPromotion?.archive_integrity ? "yes" : "no"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Regime allocation: {String(astraHorizonLifecycleCapacityPromotion?.regime_allocation_recommendation || "balanced adaptive learning mix").replaceAll("_", " ")}; mix {Object.entries(astraHorizonLifecycleCapacityPromotion?.preferred_horizon_mix || {}).map(([key, value]) => `${String(key).replaceAll("_", " ")} ${safeNumber(value).toFixed(0)}%`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Catalyst context: coverage {safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_coverage_pct).toFixed(1)}%, unknown {safeNumber(astraHorizonLifecycleCapacityPromotion?.unknown_catalyst_rate).toFixed(1)}%, top unknown symbols {(astraHorizonLifecycleCapacityPromotion?.top_unknown_symbols || []).join(", ") || "none"}. Fix: {String(astraHorizonLifecycleCapacityPromotion?.recommended_catalyst_fix || "use cached context first").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Known catalysts: {(astraHorizonLifecycleCapacityPromotion?.top_known_symbols || []).join(", ") || "warming up"}; readiness {safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_readiness_score).toFixed(1)}; improvement rate {safeNumber(astraHorizonLifecycleCapacityPromotion?.catalyst_improvement_rate).toFixed(1)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Profit retention: {String(astraHorizonLifecycleCapacityPromotion?.profit_retention_status || "monitoring").replaceAll("_", " ")}; lifecycle {String(astraHorizonLifecycleCapacityPromotion?.lifecycle_efficiency_status || "monitoring").replaceAll("_", " ")}; recommendation {String(astraHorizonLifecycleCapacityPromotion?.reduce_giveback_recommendation || "monitor_giveback").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit maturation: best policy {String(astraHorizonLifecycleCapacityPromotion?.best_exit_policy_candidate || "warming up").replaceAll("_", " ")}, closest readiness {String(astraHorizonLifecycleCapacityPromotion?.closest_exit_policy_to_readiness || "warming up").replaceAll("_", " ")}, score {safeNumber(astraHorizonLifecycleCapacityPromotion?.exit_policy_readiness_score).toFixed(1)}, giveback reduction opportunity {safeNumber(astraHorizonLifecycleCapacityPromotion?.giveback_reduction_opportunity).toFixed(1)}, expected capture improvement {safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_profit_capture_improvement).toFixed(1)}. Human review required; automatic sells remain disabled.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow promotion: {String(astraHorizonLifecycleCapacityPromotion?.top_promotion_candidate_name || "warming up").replaceAll("_", " ")} readiness {String(astraHorizonLifecycleCapacityPromotion?.top_promotion_readiness || "advisory only").replaceAll("_", " ")}, score {safeNumber(astraHorizonLifecycleCapacityPromotion?.promotion_readiness_score).toFixed(1)}, PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_pf_improvement).toFixed(3)}, giveback {safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_giveback_reduction).toFixed(1)}, exit {safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_exit_improvement).toFixed(1)}. Human review required; automatic promotions remain disabled.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow readiness: {Object.entries(astraHorizonLifecycleCapacityPromotion?.readiness_by_horizon || {}).map(([key, value]) => `${String(key).replaceAll("_", " ")} ${String(value).replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit readiness: scalp {String(astraHorizonLifecycleCapacityPromotion?.scalp_exit_readiness || "collect_more_evidence").replaceAll("_", " ")}, day {String(astraHorizonLifecycleCapacityPromotion?.day_trade_exit_readiness || "collect_more_evidence").replaceAll("_", " ")}, swing {String(astraHorizonLifecycleCapacityPromotion?.swing_exit_readiness || "collect_more_evidence").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Practice bucket: {String(astraHorizonLifecycleCapacityPromotion?.practice_bucket_status || "advisory only disabled pending human review").replaceAll("_", " ")}; size {safeNumber(astraHorizonLifecycleCapacityPromotion?.bucket_size, 3).toFixed(0)}; used today {safeNumber(astraHorizonLifecycleCapacityPromotion?.bucket_used_today).toFixed(0)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recycling: {String(astraHorizonLifecycleCapacityPromotion?.recycling_recommendation || "monitor capacity until slot reopens").replaceAll("_", " ")}; block reason {String(astraHorizonLifecycleCapacityPromotion?.recycle_block_reason || "none").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Lifecycle reconciliation: unmatched broker {(astraHorizonLifecycleCapacityPromotion?.unmatched_broker_symbols || []).join(", ") || "none"}; unmatched internal {(astraHorizonLifecycleCapacityPromotion?.unmatched_internal_symbols || []).join(", ") || "none"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next action: {String(astraHorizonLifecycleCapacityPromotion?.next_recommended_action || "continue advisory horizon learning").replaceAll("_", " ")}; overconcentration warning {astraHorizonLifecycleCapacityPromotion?.overconcentration_warning ? "yes" : "no"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Activation: {astraHorizonLifecycleCapacityPromotion?.horizon_assignment_used ? "adaptive horizon tie-break active" : "diagnostic only"}; confidence {safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_assignment_confidence).toFixed(1)}; candidate {astraHorizonLifecycleCapacityPromotion?.horizon_execution_candidate?.symbol || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Flow: {String(astraHorizonLifecycleCapacityPromotion?.integration_flow || "Trade lifecycle / Shadow / Horizon systems -> Librarian -> Unified Truth -> Executive Assistant -> Learning Center").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>AIOS Learning Acceleration & Adaptive Feed Monitor</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is measuring whether AIOS is underfed across satellites, IHIE, Shadow, triage, compression, Teacher, memory, retrieval, AIC, Executive, CEO, and Copilot. This panel is advisory-only, cache-first, and does not change trading, Shadow logic, providers, broker behavior, rankings, entries, exits, sizing, allocation, or thresholds.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraAiosThroughputInstitutionalMemory?.status],
            ["Satellite utilization", `${safeNumber(astraAiosThroughputInstitutionalMemory?.satellite_utilization).toFixed(1)}%`],
            ["Satellite observations", safeNumber(astraAiosThroughputInstitutionalMemory?.satellite_observations_today).toFixed(0)],
            ["IHIE Collector", astraAiosThroughputInstitutionalMemory?.ihie_collector_status],
            ["IHIE enrichments", safeNumber(astraAiosThroughputInstitutionalMemory?.ihie_analyst_enrichments_today).toFixed(0)],
            ["Shadow experiments", safeNumber(astraAiosThroughputInstitutionalMemory?.shadow_experiments_today).toFixed(0)],
            ["Triage packets", safeNumber(astraAiosThroughputInstitutionalMemory?.triage_throughput).toFixed(0)],
            ["Compression", safeNumber(astraAiosThroughputInstitutionalMemory?.compression_throughput).toFixed(0)],
            ["Teacher lessons", safeNumber(astraAiosThroughputInstitutionalMemory?.teacher_lessons_today).toFixed(0)],
            ["Memory reinforces", safeNumber(astraAiosThroughputInstitutionalMemory?.memory_reinforcements_today).toFixed(0)],
            ["Retrieval candidates", safeNumber(astraAiosThroughputInstitutionalMemory?.retrieval_candidates_today).toFixed(0)],
            ["AIC priorities", safeNumber(astraAiosThroughputInstitutionalMemory?.aic_working_priorities_today).toFixed(0)],
            ["Weakest layer", astraAiosThroughputInstitutionalMemory?.weakest_layer],
            ["Strongest layer", astraAiosThroughputInstitutionalMemory?.strongest_layer],
            ["Feed monitor", astraAiosThroughputInstitutionalMemory?.adaptive_feed_monitor_status],
            ["Safe to scale", astraAiosThroughputInstitutionalMemory?.safe_to_scale ? "yes" : "no"],
            ["Dashboard provider calls", safeNumber(astraAiosThroughputInstitutionalMemory?.dashboard_provider_calls_used).toFixed(0)],
            ["Dashboard LLM calls", safeNumber(astraAiosThroughputInstitutionalMemory?.dashboard_llm_calls_used).toFixed(0)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended action: {String(astraAiosThroughputInstitutionalMemory?.recommended_action || "scale cached internal observations only where quality allows").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Underfed layers: {(astraAiosThroughputInstitutionalMemory?.layers_underfed || []).join(" | ") || "none"}; safe-to-scale layers: {(astraAiosThroughputInstitutionalMemory?.layers_safe_to_scale || []).join(" | ") || "none"}; paused layers: {(astraAiosThroughputInstitutionalMemory?.layers_paused || []).join(" | ") || "none"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Feed adjustments applied: {(astraAiosThroughputInstitutionalMemory?.feed_adjustments_applied || []).map((row) => `${String(row?.layer || "layer").replaceAll("_", " ")} ${String(row?.adjustment || "adjusted").replaceAll("_", " ")}`).join(" | ") || "none"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Safety: {String(astraAiosThroughputInstitutionalMemory?.provider_safety_status || "safe no provider polling increase").replaceAll("_", " ")}; {String(astraAiosThroughputInstitutionalMemory?.dashboard_safety_status || "safe zero dashboard provider and llm calls").replaceAll("_", " ")}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Capacity manager: {(astraAiosThroughputInstitutionalMemory?.aios_capacity_manager_v1?.layers || []).slice(0, 6).map((row) => `${String(row?.layer || "layer").replaceAll("_", " ")} ${safeNumber(row?.utilization_percent).toFixed(1)}%`).join(" | ") || "warming up"}.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Astra AIOS V1 & Intelligence Maturation</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is organizing existing intelligence through satellites, historical comparison, triage, compression, teaching, memory retrieval, and AIC coordination. This is advisory-only, cache-first, and does not change Shadow, rankings, entries, exits, sizing, allocation, broker behavior, or live trading.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraAiosIntelligenceMaturation?.status],
            ["AIOS maturity", safeNumber(astraAiosIntelligenceMaturation?.aios_maturity_score).toFixed(1)],
            ["Final health", safeNumber(astraAiosIntelligenceMaturation?.final_maturation_bundle_health).toFixed(1)],
            ["Exit maturity", safeNumber(astraAiosIntelligenceMaturation?.exit_intelligence_maturity).toFixed(1)],
            ["IHIE maturity", safeNumber(astraAiosIntelligenceMaturation?.ihie_maturity).toFixed(1)],
            ["Symbol memory", safeNumber(astraAiosIntelligenceMaturation?.symbol_behavioral_memory_maturity).toFixed(1)],
            ["Retrieval maturity", safeNumber(astraAiosIntelligenceMaturation?.memory_retrieval_maturity).toFixed(1)],
            ["Reinforcement", safeNumber(astraAiosIntelligenceMaturation?.learning_reinforcement_maturity).toFixed(1)],
            ["Ask V2 readiness", safeNumber(astraAiosIntelligenceMaturation?.ask_astra_v2_readiness).toFixed(1)],
            ["Exec/CEO readiness", safeNumber(astraAiosIntelligenceMaturation?.executive_ceo_v3_readiness).toFixed(1)],
            ["Satellites", safeNumber(astraAiosIntelligenceMaturation?.satellites_registered).toFixed(0)],
            ["Lessons created", safeNumber(astraAiosIntelligenceMaturation?.lessons_created).toFixed(0)],
            ["Triage acceptance", `${safeNumber(astraAiosIntelligenceMaturation?.triage_acceptance_rate).toFixed(1)}%`],
            ["Weakest area", astraAiosIntelligenceMaturation?.weakest_aios_area],
            ["AIC score", safeNumber(astraAiosIntelligenceMaturation?.astra_intelligence_core_v1?.aic_coordination_score).toFixed(1)],
            ["IHIE status", astraAiosIntelligenceMaturation?.institutional_historical_intelligence_engine_v1?.status],
            ["Triage accepted", safeNumber(astraAiosIntelligenceMaturation?.triage_relevance_gate_v1?.accepted).toFixed(0)],
            ["Triage rejected", safeNumber(astraAiosIntelligenceMaturation?.triage_relevance_gate_v1?.rejected).toFixed(0)],
            ["Compression", astraAiosIntelligenceMaturation?.multi_stage_compression_v1?.status],
            ["Teacher", astraAiosIntelligenceMaturation?.teacher_layer_v1?.status],
            ["Memory", astraAiosIntelligenceMaturation?.multi_tier_memory_v1?.status],
            ["Retrieval", astraAiosIntelligenceMaturation?.memory_retrieval_engine_v1?.status],
            ["Shadow changed", astraAiosIntelligenceMaturation?.shadow_logic_changed ? "yes" : "no"],
            ["Dashboard provider calls", safeNumber(astraAiosIntelligenceMaturation?.dashboard_provider_calls_used).toFixed(0)],
            ["Dashboard LLM calls", safeNumber(astraAiosIntelligenceMaturation?.dashboard_llm_calls_used).toFixed(0)],
            ["Behavior safe", astraAiosIntelligenceMaturation?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Flow: {(astraAiosIntelligenceMaturation?.architecture_flow || []).join(" -> ") || "Providers/APIs -> Controlled Data Acquisition -> Satellites -> IHIE -> Shadow Layer -> Triage -> Compression -> Teacher -> Memory -> AIC -> CIO/Executive/Copilot/Dashboard"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Highest priority focus: {String(astraAiosIntelligenceMaturation?.highest_priority_focus || "continue cache-first AIOS maturation").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Weakest remaining areas: {(astraAiosIntelligenceMaturation?.weakest_remaining_areas || []).map((row) => `${String(row?.area || "area").replaceAll("_", " ")} ${safeNumber(row?.score).toFixed(1)}`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit maturity: {String(astraAiosIntelligenceMaturation?.exit_intelligence_maturation_v2?.when_taking_profit_earlier_helps || "monitor giveback, profit decay, and catalyst weakening").replaceAll("_", " ")}; automatic exits {astraAiosIntelligenceMaturation?.automatic_exits_enabled ? "enabled" : "disabled"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Historical scope: {(astraAiosIntelligenceMaturation?.institutional_historical_intelligence_engine_v1?.historical_collection_priorities?.tier_1 || []).join(", ") || "SPY, QQQ, IWM, VIX, Sector ETFs"} first; full-market downloads {astraAiosIntelligenceMaturation?.institutional_historical_intelligence_engine_v1?.full_market_download_allowed ? "allowed" : "blocked"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Symbol memory labels: {(astraAiosIntelligenceMaturation?.symbol_behavioral_memory_expansion_v1?.personality_labels_supported || []).slice(0, 7).join(" | ") || "Momentum Leader | Catalyst Driven | High Giveback Risk"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Memory budgets: daily {safeNumber(astraAiosIntelligenceMaturation?.multi_tier_memory_v1?.learning_budgets?.daily_max_lessons, 100).toFixed(0)}, weekly {safeNumber(astraAiosIntelligenceMaturation?.multi_tier_memory_v1?.learning_budgets?.weekly_max_lessons, 500).toFixed(0)}, monthly {safeNumber(astraAiosIntelligenceMaturation?.multi_tier_memory_v1?.learning_budgets?.monthly_max_lessons, 2000).toFixed(0)}. Excess intelligence is compressed, archived, or discarded.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Satellite health: {(astraAiosIntelligenceMaturation?.satellite_request_manager_v1?.satellites || []).map((row) => `${String(row?.satellite_name || "satellite").replaceAll("_", " ")} ${String(row?.health || "warming up").replaceAll("_", " ")}`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Not changed: {(astraAiosIntelligenceMaturation?.intentionally_not_changed || []).join(" | ") || "Shadow logic | live trading | broker execution | rankings | entries | exits | sizing | allocation | thresholds"}.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Provider Orchestration & Data Governance V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is assigning one owner per data category, suppressing duplicate provider work, and keeping dashboard reads cache-only. This suite is governance-only and does not change ranking, entries, exits, sizing, allocation, broker behavior, paper execution, or live trading.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Status", astraProviderOrchestrationDataGovernance?.status],
            ["Institutional score", safeNumber(astraProviderOrchestrationDataGovernance?.institutional_intelligence_score).toFixed(1)],
            ["Data acquisition", safeNumber(astraProviderOrchestrationDataGovernance?.controlled_data_acquisition_score).toFixed(1)],
            ["Worker", astraProviderOrchestrationDataGovernance?.controlled_data_acquisition_orchestrator_v2?.background_worker_exists ? "exists" : "warming up"],
            ["Scheduler", astraProviderOrchestrationDataGovernance?.controlled_data_acquisition_orchestrator_v2?.scheduler_exists ? "exists" : "warming up"],
            ["Last collection", astraProviderOrchestrationDataGovernance?.controlled_data_acquisition_orchestrator_v2?.last_collection_at],
            ["Portfolio Intel", safeNumber(astraProviderOrchestrationDataGovernance?.portfolio_intelligence_score).toFixed(1)],
            ["Exit Intel", safeNumber(astraProviderOrchestrationDataGovernance?.exit_intelligence_score).toFixed(1)],
            ["Sector Rotation", safeNumber(astraProviderOrchestrationDataGovernance?.sector_rotation_score).toFixed(1)],
            ["Market Breadth", safeNumber(astraProviderOrchestrationDataGovernance?.market_breadth_score).toFixed(1)],
            ["Macro / Fed", `${safeNumber(astraProviderOrchestrationDataGovernance?.macro_intelligence_score).toFixed(1)} / ${safeNumber(astraProviderOrchestrationDataGovernance?.fed_intelligence_score).toFixed(1)}`],
            ["Regime", astraProviderOrchestrationDataGovernance?.market_regime_engine_v1?.market_regime],
            ["Consensus", safeNumber(astraProviderOrchestrationDataGovernance?.consensus_score).toFixed(1)],
            ["Knowledge Graph", safeNumber(astraProviderOrchestrationDataGovernance?.knowledge_graph_score).toFixed(1)],
            ["Strongest area", astraProviderOrchestrationDataGovernance?.strongest_area],
            ["Weakest area", astraProviderOrchestrationDataGovernance?.weakest_area],
            ["Primary model", astraProviderOrchestrationDataGovernance?.summary?.primary_provider_model],
            ["Best owner", astraProviderOrchestrationDataGovernance?.summary?.best_configured_owner],
            ["Provider scores", safeNumber(astraProviderOrchestrationDataGovernance?.provider_confidence_engine?.providers_scored).toFixed(0)],
            ["Configured", safeNumber(astraProviderOrchestrationDataGovernance?.provider_confidence_engine?.providers_configured).toFixed(0)],
            ["Healthy", safeNumber(astraProviderOrchestrationDataGovernance?.provider_confidence_engine?.providers_healthy).toFixed(0)],
            ["Avg score", safeNumber(astraProviderOrchestrationDataGovernance?.provider_confidence_engine?.average_overall_provider_score).toFixed(1)],
            ["FMP market data", astraProviderOrchestrationDataGovernance?.provider_owner_readiness?.fmp_ready_for_core_market_data ? "ready" : "not ready"],
            ["Alpaca broker truth", astraProviderOrchestrationDataGovernance?.provider_owner_readiness?.alpaca_ready_for_broker_truth ? "ready" : "not ready"],
            ["FRED macro", astraProviderOrchestrationDataGovernance?.provider_owner_readiness?.fred_ready_for_macro ? "ready" : "not ready"],
            ["Finnhub catalysts", astraProviderOrchestrationDataGovernance?.provider_owner_readiness?.finnhub_ready_for_news_catalysts ? "ready" : "not ready"],
            ["Moralis crypto", astraProviderOrchestrationDataGovernance?.provider_owner_readiness?.moralis_ready_for_crypto_context ? "ready" : "not ready"],
            ["Anti-overlap", astraProviderOrchestrationDataGovernance?.anti_overlap_engine?.enabled ? "enabled" : "warming up"],
            ["Backups", astraProviderOrchestrationDataGovernance?.anti_overlap_engine?.primary_success_suppresses_backups ? "suppressed after primary success" : "warming up"],
            ["Projected GB/mo", safeNumber(astraProviderOrchestrationDataGovernance?.bandwidth_governance?.projected_monthly_usage_gb).toFixed(3)],
            ["Bandwidth", astraProviderOrchestrationDataGovernance?.bandwidth_governance?.bandwidth_status],
            ["Target GB/mo", `${safeNumber(astraProviderOrchestrationDataGovernance?.bandwidth_governance?.target_low_gb, 5).toFixed(0)}-${safeNumber(astraProviderOrchestrationDataGovernance?.bandwidth_governance?.target_high_gb, 10).toFixed(0)}`],
            ["Soft limit GB", safeNumber(astraProviderOrchestrationDataGovernance?.bandwidth_governance?.soft_limit_gb, 15).toFixed(0)],
            ["Dashboard calls", safeNumber(astraProviderOrchestrationDataGovernance?.dashboard_provider_calls_used).toFixed(0)],
            ["LLM calls", safeNumber(astraProviderOrchestrationDataGovernance?.dashboard_llm_calls_used).toFixed(0)],
            ["Behavior safe", astraProviderOrchestrationDataGovernance?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Owners: historical/fundamentals/earnings FMP; broker truth Alpaca; macro/Fed FRED; news/catalysts Finnhub; crypto context Moralis. Polygon, TwelveData, EODHD, AlphaVantage, NASDAQ, SimFin, and DataJockey stay secondary or specialized.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            CIO feed priorities: {(astraProviderOrchestrationDataGovernance?.intelligent_data_acquisition_orchestrator_v2?.feed_priorities || []).slice(0, 5).map((row) => `${String(row?.system || "unknown").replaceAll("_", " ")} via ${String(row?.primary_owner || "cache")}`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Improvements: {(astraProviderOrchestrationDataGovernance?.cio_intelligence_maturation?.weaknesses_improved || []).map((item) => String(item).replaceAll("_", " ")).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Controlled acquisition: {(astraProviderOrchestrationDataGovernance?.controlled_data_acquisition_orchestrator_v2?.collection_schedule || []).map((row) => `${String(row?.cycle || "cycle").replaceAll("_", " ")} ${String(row?.window || "")}`).join(" | ") || "warming up"}. Provider calls stay inside the background/cache path.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Provider self-healing: {(astraProviderOrchestrationDataGovernance?.provider_self_healing_v1?.provider_rows || []).filter((row) => row?.fallback_used).slice(0, 4).map((row) => `${String(row?.provider_name || "provider")} fallback ${String(row?.fallback_provider || "none")}`).join(" | ") || "no active fallback needed"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            V3 focus: {String(astraProviderOrchestrationDataGovernance?.highest_roi_next_improvement || "continue controlled background evidence gathering").replaceAll("_", " ")}. Executive/Copilot/Ask Astra enrichment is cached and advisory-only.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Dashboard contract: {String(astraProviderOrchestrationDataGovernance?.summary?.dashboard_contract || "cache only no provider or LLM calls").replaceAll("_", " ")}.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Shadow-to-Paper Promotion Engine V2</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Controlled promotion bridge for shadow-learned exits, horizon behavior, and rotation concepts. Human review remains required before any tiny paper test bucket.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Top candidate", astraHorizonLifecycleCapacityPromotion?.top_promotion_candidate_name],
            ["Readiness", astraHorizonLifecycleCapacityPromotion?.top_promotion_readiness],
            ["PF gain", safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_pf_improvement).toFixed(3)],
            ["Giveback reduction", safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_giveback_reduction).toFixed(1)],
            ["Capture improvement", safeNumber(astraHorizonLifecycleCapacityPromotion?.expected_capture_improvement).toFixed(3)],
            ["Test bucket", astraHorizonLifecycleCapacityPromotion?.test_bucket_status],
            ["Bucket used", `${safeNumber(astraHorizonLifecycleCapacityPromotion?.test_bucket_used_today).toFixed(0)} / ${safeNumber(astraHorizonLifecycleCapacityPromotion?.test_bucket_size, 2).toFixed(0)}`],
            ["Rollback", astraHorizonLifecycleCapacityPromotion?.rollback_status],
            ["Kill switch", astraHorizonLifecycleCapacityPromotion?.kill_switch_status],
            ["Biggest blocker", astraHorizonLifecycleCapacityPromotion?.top_promotion_blocker],
            ["Paper PF", safeNumber(astraHorizonLifecycleCapacityPromotion?.paper_pf).toFixed(3)],
            ["Shadow PF", safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_expected_pf).toFixed(3)],
            ["Exit delta", safeNumber(astraHorizonLifecycleCapacityPromotion?.exit_quality_delta).toFixed(1)],
            ["Horizon gap", safeNumber(astraHorizonLifecycleCapacityPromotion?.horizon_gap).toFixed(1)],
            ["Behavior safe", astraHorizonLifecycleCapacityPromotion?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Scorecard: paper PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.paper_pf).toFixed(3)}, shadow PF {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_expected_pf).toFixed(3)}, giveback {safeNumber(astraHorizonLifecycleCapacityPromotion?.paper_giveback).toFixed(1)} to {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_expected_giveback).toFixed(1)}, capture {safeNumber(astraHorizonLifecycleCapacityPromotion?.paper_capture_ratio).toFixed(3)} to {safeNumber(astraHorizonLifecycleCapacityPromotion?.shadow_capture_ratio).toFixed(3)}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Promotion candidates: {(astraHorizonLifecycleCapacityPromotion?.promotion_candidates_v2 || []).map((row) => `${String(row?.behavior_name || "unknown").replaceAll("_", " ")} ${String(row?.promotion_readiness || "warming up").replaceAll("_", " ")}`).join(" | ") || "warming up"}.
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next action: {String(astraHorizonLifecycleCapacityPromotion?.promotion_recommended_next_action || "human_review_before_any_tiny_paper_bucket").replaceAll("_", " ")}; bucket enabled {astraHorizonLifecycleCapacityPromotion?.test_bucket_enabled ? "yes" : "no"}.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Trade Thesis Validation V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is checking whether the original trade thesis actually matched what happened in the market across catalyst, symbol, sector, regime, horizon, entry, and exit reasoning. This remains learning-only and does not change entries, exits, sizing, thresholds, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(tradeThesisValidation?.evidence_count).toFixed(0)],
            ["Accuracy score", safeNumber(tradeThesisValidation?.thesis_accuracy_score).toFixed(1)],
            ["Failure rate", safeNumber(tradeThesisValidation?.thesis_failure_rate).toFixed(1)],
            ["Strongest thesis", tradeThesisValidation?.strongest_thesis_type],
            ["Weakest thesis", tradeThesisValidation?.weakest_thesis_type],
            ["Thesis confidence", safeNumber(tradeThesisValidation?.thesis_confidence).toFixed(1)],
            ["Top failed reason", tradeThesisValidation?.top_failed_thesis_reason],
            ["Top success reason", tradeThesisValidation?.top_successful_thesis_reason],
            ["API/provider/LLM", `${safeNumber(tradeThesisValidation?.api_calls_used).toFixed(0)} / ${safeNumber(tradeThesisValidation?.provider_calls_used).toFixed(0)} / ${safeNumber(tradeThesisValidation?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", tradeThesisValidation?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Thesis rows: {(tradeThesisValidation?.thesis_rows || []).slice(0, 4).map((row) => `${String(row?.thesis_type || "thesis").replaceAll("_", " ")} ${safeNumber(row?.accuracy_score).toFixed(0)}%`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(tradeThesisValidation?.shadow_recommendation || "Continue trade thesis validation shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Market Transition Detection V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is watching for early transition signals such as leadership weakening, sector rotation acceleration, continuation deterioration, and volatility regime shifts. This is advisory monitoring only and does not change trading behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(marketTransitionDetection?.evidence_count).toFixed(0)],
            ["Regime stability", safeNumber(marketTransitionDetection?.regime_stability_score).toFixed(1)],
            ["Transition risk", safeNumber(marketTransitionDetection?.transition_risk_score).toFixed(1)],
            ["Transition confidence", safeNumber(marketTransitionDetection?.transition_confidence).toFixed(1)],
            ["Strongest warning", marketTransitionDetection?.strongest_transition_warning],
            ["Current phase", marketTransitionDetection?.current_market_phase],
            ["Likely next phase", marketTransitionDetection?.likely_next_market_phase],
            ["API/provider/LLM", `${safeNumber(marketTransitionDetection?.api_calls_used).toFixed(0)} / ${safeNumber(marketTransitionDetection?.provider_calls_used).toFixed(0)} / ${safeNumber(marketTransitionDetection?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", marketTransitionDetection?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Warnings: {(marketTransitionDetection?.transition_warning_rows || []).slice(0, 4).map((row) => `${String(row?.warning || "warning").replaceAll("_", " ")} ${safeNumber(row?.score).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(marketTransitionDetection?.shadow_recommendation || "Continue market transition detection shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Trade Family Intelligence V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is grouping related symbols into behavior families so it can transfer lessons faster across AI leaders, semiconductors, quantum names, airlines, biotech, energy, meme names, and other peer clusters. This is transfer-learning only and does not alter rankings or execution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(tradeFamilyIntelligence?.evidence_count).toFixed(0)],
            ["Strongest family", tradeFamilyIntelligence?.strongest_trade_family],
            ["Weakest family", tradeFamilyIntelligence?.weakest_trade_family],
            ["Best family horizon", tradeFamilyIntelligence?.best_family_horizon],
            ["Best family exit", tradeFamilyIntelligence?.best_family_exit_style],
            ["Transfer confidence", safeNumber(tradeFamilyIntelligence?.family_transfer_confidence).toFixed(1)],
            ["Learning score", safeNumber(tradeFamilyIntelligence?.family_learning_score).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(tradeFamilyIntelligence?.api_calls_used).toFixed(0)} / ${safeNumber(tradeFamilyIntelligence?.provider_calls_used).toFixed(0)} / ${safeNumber(tradeFamilyIntelligence?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", tradeFamilyIntelligence?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Families: {(tradeFamilyIntelligence?.family_rows || []).slice(0, 4).map((row) => `${String(row?.trade_family || "family").replaceAll("_", " ")} PF ${safeNumber(row?.family_profit_factor).toFixed(2)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(tradeFamilyIntelligence?.shadow_recommendation || "Continue trade-family intelligence shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Market Condition Attribution V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is attributing performance to specific market conditions so conflicting horizon and exit readings can be separated by volatility, risk tone, continuation, chop, sector rotation, and catalyst density. This remains cached, shadow-only attribution.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(marketConditionAttribution?.evidence_count).toFixed(0)],
            ["Best condition", marketConditionAttribution?.best_condition],
            ["Weakest condition", marketConditionAttribution?.weakest_condition],
            ["Condition confidence", safeNumber(marketConditionAttribution?.condition_confidence_score).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(marketConditionAttribution?.api_calls_used).toFixed(0)} / ${safeNumber(marketConditionAttribution?.provider_calls_used).toFixed(0)} / ${safeNumber(marketConditionAttribution?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", marketConditionAttribution?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Condition rows: {(marketConditionAttribution?.condition_rows || []).slice(0, 4).map((row) => `${String(row?.market_condition || "condition").replaceAll("_", " ")} ${safeNumber(row?.condition_score).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Best horizons: {Object.entries(marketConditionAttribution?.best_horizon_by_condition || {}).slice(0, 4).map(([condition, horizon]) => `${String(condition).replaceAll("_", " ")} → ${String(horizon).replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(marketConditionAttribution?.shadow_recommendation || "Continue market-condition attribution shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Market Breadth & Index Intelligence V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is tracking broad market support through index and breadth proxies for context only. Index and ETF trading remain disabled, and this panel does not change stock entries, exits, sizing, allocation, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Indexes tracked", (marketBreadthIndexIntelligence?.index_symbols_tracked || []).join(", ")],
            ["Market health", safeNumber(marketBreadthIndexIntelligence?.overall_market_health).toFixed(1)],
            ["Risk on", safeNumber(marketBreadthIndexIntelligence?.risk_on_score).toFixed(1)],
            ["Risk off", safeNumber(marketBreadthIndexIntelligence?.risk_off_score).toFixed(1)],
            ["Trend strength", safeNumber(marketBreadthIndexIntelligence?.index_trend_strength).toFixed(1)],
            ["Momentum", safeNumber(marketBreadthIndexIntelligence?.index_momentum_score).toFixed(1)],
            ["Breadth proxy", safeNumber(marketBreadthIndexIntelligence?.breadth_proxy_score).toFixed(1)],
            ["Vol pressure", safeNumber(marketBreadthIndexIntelligence?.volatility_pressure_score).toFixed(1)],
            ["Transition risk", safeNumber(marketBreadthIndexIntelligence?.market_transition_risk).toFixed(1)],
            ["Equity support", safeNumber(marketBreadthIndexIntelligence?.market_support_for_equity_trades).toFixed(1)],
            ["Momentum support", safeNumber(marketBreadthIndexIntelligence?.market_support_for_momentum_trades).toFixed(1)],
            ["Small-cap support", safeNumber(marketBreadthIndexIntelligence?.market_support_for_small_caps).toFixed(1)],
            ["Growth support", safeNumber(marketBreadthIndexIntelligence?.market_support_for_growth_trades).toFixed(1)],
            ["Strongest index", marketBreadthIndexIntelligence?.strongest_index_signal],
            ["Weakest index", marketBreadthIndexIntelligence?.weakest_index_signal],
            ["Index regime", marketBreadthIndexIntelligence?.current_index_regime],
            ["Confidence", safeNumber(marketBreadthIndexIntelligence?.index_confidence_score).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(marketBreadthIndexIntelligence?.api_calls_used).toFixed(0)} / ${safeNumber(marketBreadthIndexIntelligence?.provider_calls_used).toFixed(0)} / ${safeNumber(marketBreadthIndexIntelligence?.llm_calls_used).toFixed(0)}`],
            ["Index trading", marketBreadthIndexIntelligence?.index_trading_enabled ? "enabled" : "disabled"],
            ["Behavior safe", marketBreadthIndexIntelligence?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Signals: {(marketBreadthIndexIntelligence?.index_signal_rows || []).slice(0, 5).map((row) => `${String(row?.symbol || "idx")} ${safeNumber(row?.signal).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(marketBreadthIndexIntelligence?.market_breadth_summary || "warming up").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>ETF Intelligence & Sector Rotation V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is learning ETF leadership and sector rotation context without trading ETFs. These signals support diagnostics and attribution only, with no changes to rankings, execution, sizing, thresholds, or broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["ETFs tracked", safeNumber((etfSectorRotationIntelligence?.etf_symbols_tracked || []).length).toFixed(0)],
            ["Strongest sector", etfSectorRotationIntelligence?.strongest_sector],
            ["Weakest sector", etfSectorRotationIntelligence?.weakest_sector],
            ["Inflow score", safeNumber(etfSectorRotationIntelligence?.sector_inflow_score).toFixed(1)],
            ["Outflow score", safeNumber(etfSectorRotationIntelligence?.sector_outflow_score).toFixed(1)],
            ["Rotation speed", safeNumber(etfSectorRotationIntelligence?.rotation_speed).toFixed(1)],
            ["Persistence", safeNumber(etfSectorRotationIntelligence?.sector_momentum_persistence).toFixed(1)],
            ["Decay risk", safeNumber(etfSectorRotationIntelligence?.sector_decay_risk).toFixed(1)],
            ["Position support", safeNumber(etfSectorRotationIntelligence?.sector_support_for_current_positions).toFixed(1)],
            ["Leadership score", safeNumber(etfSectorRotationIntelligence?.etf_leadership_score).toFixed(1)],
            ["Rotation confidence", safeNumber(etfSectorRotationIntelligence?.sector_rotation_confidence).toFixed(1)],
            ["Strongest rotation", etfSectorRotationIntelligence?.strongest_sector_rotation],
            ["Weakest rotation", etfSectorRotationIntelligence?.weakest_sector_rotation],
            ["Stock selection context", etfSectorRotationIntelligence?.sector_context_for_stock_selection],
            ["Profit capture context", etfSectorRotationIntelligence?.sector_context_for_profit_capture],
            ["API/provider/LLM", `${safeNumber(etfSectorRotationIntelligence?.api_calls_used).toFixed(0)} / ${safeNumber(etfSectorRotationIntelligence?.provider_calls_used).toFixed(0)} / ${safeNumber(etfSectorRotationIntelligence?.llm_calls_used).toFixed(0)}`],
            ["ETF trading", etfSectorRotationIntelligence?.etf_trading_enabled ? "enabled" : "disabled"],
            ["Behavior safe", etfSectorRotationIntelligence?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Sector rows: {(etfSectorRotationIntelligence?.sector_rows || []).slice(0, 5).map((row) => `${String(row?.sector || "sector")} ${safeNumber(row?.leadership_score).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(etfSectorRotationIntelligence?.sector_rotation_summary || "warming up").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Crypto Shadow Learning V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is learning crypto volatility, momentum, risk appetite, horizons, and families in a separate shadow engine. Crypto paper trading, live trading, and stock-trade influence are disabled.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Core symbols", (cryptoShadowLearning?.crypto_core_symbols_tracked || []).join(", ")],
            ["Rotating symbols", safeNumber((cryptoShadowLearning?.crypto_rotating_symbols_today || []).length).toFixed(0)],
            ["Scan symbols today", safeNumber(cryptoShadowLearning?.crypto_scan_symbols_today).toFixed(0)],
            ["Shadow opportunities", safeNumber(cryptoShadowLearning?.crypto_shadow_opportunities).toFixed(0)],
            ["Virtual paths", safeNumber(cryptoShadowLearning?.crypto_virtual_paths).toFixed(0)],
            ["Completed lifecycles", safeNumber(cryptoShadowLearning?.crypto_completed_lifecycles).toFixed(0)],
            ["Replay score", safeNumber(cryptoShadowLearning?.crypto_replay_score).toFixed(1)],
            ["Crypto PF status", cryptoShadowLearning?.crypto_profit_factor_status],
            ["Win rate", `${safeNumber(cryptoShadowLearning?.crypto_win_rate).toFixed(1)}%`],
            ["Avg return", safeNumber(cryptoShadowLearning?.crypto_avg_return).toFixed(3)],
            ["Avg MFE", safeNumber(cryptoShadowLearning?.crypto_avg_mfe).toFixed(3)],
            ["Avg MAE", safeNumber(cryptoShadowLearning?.crypto_avg_mae).toFixed(3)],
            ["Profit capture", safeNumber(cryptoShadowLearning?.crypto_profit_capture).toFixed(1)],
            ["Giveback", safeNumber(cryptoShadowLearning?.crypto_giveback).toFixed(1)],
            ["Best horizon", cryptoShadowLearning?.crypto_best_horizon],
            ["Weakest horizon", cryptoShadowLearning?.crypto_weakest_horizon],
            ["Best family", cryptoShadowLearning?.crypto_best_family],
            ["Weakest family", cryptoShadowLearning?.crypto_weakest_family],
            ["Best regime", cryptoShadowLearning?.crypto_best_regime],
            ["Transition score", safeNumber(cryptoShadowLearning?.crypto_transition_score).toFixed(1)],
            ["Vol learning", safeNumber(cryptoShadowLearning?.crypto_volatility_learning_score).toFixed(1)],
            ["Momentum learning", safeNumber(cryptoShadowLearning?.crypto_momentum_learning_score).toFixed(1)],
            ["Risk appetite", safeNumber(cryptoShadowLearning?.crypto_risk_appetite_score).toFixed(1)],
            ["API/provider/LLM", `${safeNumber(cryptoShadowLearning?.api_calls_used).toFixed(0)} / ${safeNumber(cryptoShadowLearning?.provider_calls_used).toFixed(0)} / ${safeNumber(cryptoShadowLearning?.llm_calls_used).toFixed(0)}`],
            ["Crypto paper/live", `${cryptoShadowLearning?.crypto_paper_trading_enabled ? "on" : "off"} / ${cryptoShadowLearning?.crypto_live_trading_enabled ? "on" : "off"}`],
            ["Behavior safe", cryptoShadowLearning?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Rotating pool: {(cryptoShadowLearning?.crypto_rotating_symbols_today || []).slice(0, 12).join(", ") || "warming up"}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Cross-Market Attribution & Transfer Learning V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is measuring whether index, ETF, and crypto context helps explain stock outcomes. Cross-market influence remains attribution-only and cannot change stock behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Transfer confidence", safeNumber(crossMarketAttributionTransfer?.cross_market_transfer_confidence).toFixed(1)],
            ["Crypto to stock", safeNumber(crossMarketAttributionTransfer?.crypto_to_stock_signal_score).toFixed(1)],
            ["Index to stock", safeNumber(crossMarketAttributionTransfer?.index_to_stock_signal_score).toFixed(1)],
            ["ETF to stock", safeNumber(crossMarketAttributionTransfer?.etf_to_stock_signal_score).toFixed(1)],
            ["Risk appetite", safeNumber(crossMarketAttributionTransfer?.risk_appetite_transfer_score).toFixed(1)],
            ["Market psychology", safeNumber(crossMarketAttributionTransfer?.market_psychology_score).toFixed(1)],
            ["Speculation score", safeNumber(crossMarketAttributionTransfer?.speculation_score).toFixed(1)],
            ["Alpha available", crossMarketAttributionTransfer?.cross_market_alpha_available ? "yes" : "no"],
            ["Alpha confidence", safeNumber(crossMarketAttributionTransfer?.cross_market_alpha_confidence).toFixed(1)],
            ["Strongest relationship", crossMarketAttributionTransfer?.strongest_cross_market_relationship],
            ["Weakest relationship", crossMarketAttributionTransfer?.weakest_cross_market_relationship],
            ["Recommended use", crossMarketAttributionTransfer?.recommended_cross_market_use],
            ["Bandwidth", `${safeNumber(crossMarketAttributionTransfer?.bandwidth_used_gb).toFixed(3)} GB`],
            ["Budget status", crossMarketAttributionTransfer?.bandwidth_budget_status],
            ["API/provider/LLM", `${safeNumber(crossMarketAttributionTransfer?.api_calls_used).toFixed(0)} / ${safeNumber(crossMarketAttributionTransfer?.provider_calls_used).toFixed(0)} / ${safeNumber(crossMarketAttributionTransfer?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", crossMarketAttributionTransfer?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Relationships: {(crossMarketAttributionTransfer?.relationship_rows || []).slice(0, 5).map((row) => `${String(row?.relationship || "relationship").replaceAll("_", " ")} ${safeNumber(row?.score).toFixed(0)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(crossMarketAttributionTransfer?.shadow_recommendation || "Keep cross-market attribution shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Profit Lock & Profit Capture Maturation V2</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is comparing virtual profit-lock models against natural holds to understand profit giveback, continuation retention, and capture improvement potential. These are simulations only and do not change actual exits.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Tracked trades", safeNumber(profitLockProfitCaptureMaturation?.tracked_trades).toFixed(0)],
            ["Capture ratio", `${(safeNumber(profitLockProfitCaptureMaturation?.average_capture_ratio) * 100).toFixed(1)}%`],
            ["Average giveback", `${safeNumber(profitLockProfitCaptureMaturation?.average_giveback_pct).toFixed(2)}%`],
            ["Average MFE", `${safeNumber(profitLockProfitCaptureMaturation?.average_MFE).toFixed(2)}%`],
            ["Average MAE", `${safeNumber(profitLockProfitCaptureMaturation?.average_MAE).toFixed(2)}%`],
            ["Profit lock readiness", safeNumber(profitLockProfitCaptureMaturation?.profit_lock_readiness_score).toFixed(1)],
            ["Capture maturity", safeNumber(profitLockProfitCaptureMaturation?.profit_capture_maturity_score).toFixed(1)],
            ["Giveback reduction", safeNumber(profitLockProfitCaptureMaturation?.giveback_reduction_score).toFixed(1)],
            ["Continuation failure", safeNumber(profitLockProfitCaptureMaturation?.continuation_failure_learning_score).toFixed(1)],
            ["Hold duration learning", safeNumber(profitLockProfitCaptureMaturation?.hold_duration_learning_score).toFixed(1)],
            ["Improvement potential", safeNumber(profitLockProfitCaptureMaturation?.profit_capture_improvement_potential).toFixed(1)],
            ["Best lock model", profitLockProfitCaptureMaturation?.best_virtual_profit_lock_model],
            ["Best capture model", profitLockProfitCaptureMaturation?.best_virtual_profit_capture_model],
            ["API/provider/LLM", `${safeNumber(profitLockProfitCaptureMaturation?.api_calls_used).toFixed(0)} / ${safeNumber(profitLockProfitCaptureMaturation?.provider_calls_used).toFixed(0)} / ${safeNumber(profitLockProfitCaptureMaturation?.llm_calls_used).toFixed(0)}`],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Virtual models: {(profitLockProfitCaptureMaturation?.virtual_profit_lock_scenarios || []).slice(0, 5).map((row) => `${String(row?.model || "model").replaceAll("_", " ")} impact ${safeNumber(row?.profitability_impact).toFixed(2)}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(profitLockProfitCaptureMaturation?.shadow_recommendation || "Continue virtual profit-lock and capture maturation shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Shadow Correction Validation & Attribution V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is validating whether shadow recommendations are actually improving paper outcomes over time. Phase 1 influence is capped at 3% and limited to candidate ranking, buy purity, and opportunity-cost confidence only; it cannot create trades, block trades, change exits, change sizing, alter broker behavior, or change capital allocation.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Influence enabled", shadowCorrectionValidation?.shadow_influence_enabled ? "yes" : "no"],
            ["Influence cap", `${safeNumber(shadowCorrectionValidation?.shadow_influence_cap_pct).toFixed(1)}%`],
            ["Ranking influence", `${safeNumber(shadowCorrectionValidation?.candidate_ranking_influence_pct).toFixed(2)}%`],
            ["Buy purity influence", `${safeNumber(shadowCorrectionValidation?.buy_purity_influence_pct).toFixed(2)}%`],
            ["Opportunity cost influence", `${safeNumber(shadowCorrectionValidation?.opportunity_cost_influence_pct).toFixed(2)}%`],
            ["Reviewed", safeNumber(shadowCorrectionValidation?.shadow_recommendations_reviewed).toFixed(0)],
            ["Validated", safeNumber(shadowCorrectionValidation?.validated_recommendations).toFixed(0)],
            ["Rejected", safeNumber(shadowCorrectionValidation?.rejected_recommendations).toFixed(0)],
            ["Validated recs", safeNumber(shadowCorrectionValidation?.total_validated_recommendations).toFixed(0)],
            ["Failed recs", safeNumber(shadowCorrectionValidation?.total_failed_recommendations).toFixed(0)],
            ["Improvement score", safeNumber(shadowCorrectionValidation?.validated_improvement_score).toFixed(1)],
            ["Avg improvement", safeNumber(shadowCorrectionValidation?.average_improvement_score).toFixed(1)],
            ["Confidence", safeNumber(shadowCorrectionValidation?.confidence_score).toFixed(1)],
            ["Readiness", safeNumber(shadowCorrectionValidation?.readiness_score).toFixed(1)],
            ["Strongest", shadowCorrectionValidation?.strongest_validated_improvement],
            ["Weakest", shadowCorrectionValidation?.weakest_validated_improvement],
            ["API/provider/LLM", `${safeNumber(shadowCorrectionValidation?.api_calls_used).toFixed(0)} / ${safeNumber(shadowCorrectionValidation?.provider_calls_used).toFixed(0)} / ${safeNumber(shadowCorrectionValidation?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", shadowCorrectionValidation?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Categories: {(shadowCorrectionValidation?.validation_categories || []).slice(0, 4).map((row) => `${String(row?.category || "unknown").replaceAll("_", " ")} ${String(row?.validated_status || "warming_up").replaceAll("_", " ")}`).join(" | ") || "warming up"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(shadowCorrectionValidation?.shadow_recommendation || "Continue shadow correction validation before broader influence.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Controlled Paper Profit Protection Pilot V1</summary>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 10 }}>
          Astra is evaluating evidence-backed profit-protection guidance for paper trades only. The pilot can inform profit-lock, exit-review, hold-review, and continuation-review scores within a 3% cap, but it cannot force exits, sell, place orders, change sizing, change allocations, or alter broker behavior.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Active", controlledPaperProfitProtection?.profit_protection_active ? "yes" : "no"],
            ["Influence cap", `${safeNumber(controlledPaperProfitProtection?.profit_protection_influence_cap_pct).toFixed(1)}%`],
            ["Closed evidence", safeNumber(controlledPaperProfitProtection?.closed_trade_evidence).toFixed(0)],
            ["Profit capture score", safeNumber(controlledPaperProfitProtection?.profit_capture_score).toFixed(1)],
            ["Giveback rate", `${safeNumber(controlledPaperProfitProtection?.giveback_rate).toFixed(2)}%`],
            ["Profit lock readiness", safeNumber(controlledPaperProfitProtection?.profit_lock_readiness).toFixed(1)],
            ["Giveback risk", safeNumber(controlledPaperProfitProtection?.giveback_risk_score).toFixed(1)],
            ["Catalyst decay risk", safeNumber(controlledPaperProfitProtection?.catalyst_decay_risk).toFixed(1)],
            ["Continuation failure", safeNumber(controlledPaperProfitProtection?.continuation_failure_probability).toFixed(1)],
            ["Hold efficiency", safeNumber(controlledPaperProfitProtection?.hold_duration_efficiency).toFixed(1)],
            ["Giveback reduction", safeNumber(controlledPaperProfitProtection?.estimated_giveback_reduction).toFixed(1)],
            ["Capture improvement", safeNumber(controlledPaperProfitProtection?.estimated_profit_capture_improvement).toFixed(1)],
            ["Expectancy improvement", safeNumber(controlledPaperProfitProtection?.estimated_expectancy_improvement).toFixed(1)],
            ["Recommendations", safeNumber(controlledPaperProfitProtection?.recommendation_count).toFixed(0)],
            ["Validated lock events", safeNumber(controlledPaperProfitProtection?.validated_profit_lock_events).toFixed(0)],
            ["Confidence", safeNumber(controlledPaperProfitProtection?.confidence_score).toFixed(1)],
            ["Readiness", safeNumber(controlledPaperProfitProtection?.readiness_score).toFixed(1)],
            ["Human review", controlledPaperProfitProtection?.human_review_required ? "yes" : "no"],
            ["Auto apply", controlledPaperProfitProtection?.auto_apply_allowed ? "yes" : "no"],
            ["Forced exits", controlledPaperProfitProtection?.forced_exits_enabled ? "yes" : "no"],
            ["API/provider/LLM", `${safeNumber(controlledPaperProfitProtection?.api_calls_used).toFixed(0)} / ${safeNumber(controlledPaperProfitProtection?.provider_calls_used).toFixed(0)} / ${safeNumber(controlledPaperProfitProtection?.llm_calls_used).toFixed(0)}`],
            ["Behavior safe", controlledPaperProfitProtection?.behavior_safe_to_apply ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Patterns: strongest {String(controlledPaperProfitProtection?.strongest_profit_protection_pattern || "warming up").replaceAll("_", " ")} | weakest {String(controlledPaperProfitProtection?.weakest_profit_protection_pattern || "warming up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Blockers: {(controlledPaperProfitProtection?.activation_blockers || []).map((item) => String(item).replaceAll("_", " ")).join(" | ") || "none"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(controlledPaperProfitProtection?.shadow_recommendation || "Keep profit-protection pilot advisory and paper-only.").replaceAll("_", " ")}
          </div>
        </div>
      </details>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Realistic Shadow Evidence Learning Lab V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is generating realistic shadow-only paper-trade simulations without placing broker orders. Each shadow trade must resemble a real paper-trade candidate, pass eligibility and realism checks, follow a full lifecycle, account for execution friction, and only promote high-quality lessons. Astra also verifies FMP/API freshness and budget safety without increasing dashboard API use.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowRealisticShadowLabDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showRealisticShadowLabDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Target shadow/day", realisticShadowLab?.target_shadow_opportunities_per_day],
            ["Shadow opportunities", realisticShadowLab?.shadow_opportunities_tracked],
            ["Shadow capacity used", `${safeNumber(realisticShadowLab?.shadow_capacity_used).toFixed(1)}%`],
            ["Shadow capacity remaining", realisticShadowLab?.shadow_capacity_remaining],
            ["Eligible shadow", realisticShadowLab?.eligible_shadow_trades],
            ["Near miss", realisticShadowLab?.near_miss_shadow_trades],
            ["Virtual paths", realisticShadowLab?.virtual_paths_created],
            ["Learning events", realisticShadowLab?.shadow_learning_events],
            ["Realism-weighted events", realisticShadowLab?.realism_weighted_learning_events],
            ["Completed lifecycles", realisticShadowLab?.completed_shadow_lifecycles],
            ["Realism score", safeNumber(realisticShadowLab?.average_shadow_realism_score).toFixed(1)],
            ["Mirror score", safeNumber(realisticShadowLab?.paper_engine_mirror_score).toFixed(1)],
            ["Portfolio realism", safeNumber(realisticShadowLab?.shadow_portfolio_realism_score).toFixed(1)],
            ["Execution realism", safeNumber(realisticShadowLab?.execution_realism_score).toFixed(1)],
            ["Price-path realism", safeNumber(realisticShadowLab?.price_path_realism_score).toFixed(1)],
            ["Price-path source", realisticShadowLab?.price_path_source],
            ["Price-path quality", realisticShadowLab?.price_path_data_quality],
            ["Price-path limitation", realisticShadowLab?.price_path_limitation],
            ["Evidence quality", safeNumber(realisticShadowLab?.evidence_quality_score).toFixed(1)],
            ["High-value lessons", realisticShadowLab?.high_value_lessons],
            ["Discarded noise", realisticShadowLab?.discarded_noise_count],
            ["Consensus lesson", realisticShadowLab?.strongest_consensus_lesson],
            ["Weakness focus", realisticShadowLab?.active_weakness_focus],
            ["Failure pattern", realisticShadowLab?.top_failure_pattern],
            ["Winning policy", realisticShadowLab?.winning_policy],
            ["Policy confidence", safeNumber(realisticShadowLab?.policy_confidence).toFixed(1)],
            ["Storage pressure", safeNumber(realisticShadowLab?.storage_pressure_score).toFixed(1)],
            ["Memory pressure", safeNumber(realisticShadowLab?.memory_pressure_score).toFixed(1)],
            ["FMP status", realisticShadowLab?.fmp_status],
            ["Smart budget", realisticShadowLab?.fmp_smart_budget_enabled ? "enabled" : "disabled"],
            ["Refresh allowed now", realisticShadowLab?.fmp_refresh_allowed_now ? "yes" : "no"],
            ["Refresh block reason", realisticShadowLab?.fmp_refresh_block_reason],
            ["Zero usage reason", realisticShadowLab?.fmp_zero_usage_reason],
            ["Last fresh FMP", realisticShadowLab?.fmp_last_fresh_data_timestamp],
            ["FMP cache hit", `${safeNumber(realisticShadowLab?.fmp_cache_hit_rate).toFixed(1)}%`],
            ["FMP call limit", realisticShadowLab?.fmp_daily_call_limit],
            ["FMP bandwidth limit", realisticShadowLab?.fmp_daily_bandwidth_limit],
            ["FMP budget", realisticShadowLab?.fmp_budget_status],
            ["Bandwidth pressure", safeNumber(realisticShadowLab?.bandwidth_pressure_score).toFixed(1)],
            ["Data freshness", safeNumber(realisticShadowLab?.data_freshness_score).toFixed(1)],
            ["Provider warning", realisticShadowLab?.provider_warning],
            ["Recommended fix", realisticShadowLab?.recommended_safe_fix],
            ["Safe fix applied", realisticShadowLab?.safe_fix_applied ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(realisticShadowLab?.shadow_recommendation || "Continue realistic shadow evidence learning with no broker actions.").replaceAll("_", " ")}
          </div>
        </div>
        {showRealisticShadowLabDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Lifecycle & Path Quality</div>
              <div>Best path: {String(realisticShadowLab?.best_virtual_path || "warming up").replaceAll("_", " ")}</div>
              <div>Best exit style: {String(realisticShadowLab?.best_exit_style || "warming up").replaceAll("_", " ")}</div>
              <div>Virtual path score: {safeNumber(realisticShadowLab?.virtual_path_quality_score).toFixed(1)}</div>
              <div>Shadow MFE/MAE: {safeNumber(realisticShadowLab?.shadow_avg_MFE).toFixed(2)} / {safeNumber(realisticShadowLab?.shadow_avg_MAE).toFixed(2)}</div>
              <div>Capture/giveback: {safeNumber(realisticShadowLab?.shadow_capture_ratio).toFixed(2)} / {safeNumber(realisticShadowLab?.shadow_giveback_pct).toFixed(2)}</div>
              <div>Price-path source: {String(realisticShadowLab?.price_path_source || "cached_lifecycle_replay_counterfactual_summaries").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Lesson Pipeline</div>
              <div>Raw observations: {safeNumber(realisticShadowLab?.raw_observations).toFixed(0)}</div>
              <div>Candidate lessons: {safeNumber(realisticShadowLab?.candidate_lessons).toFixed(0)}</div>
              <div>Validated lessons: {safeNumber(realisticShadowLab?.validated_lessons).toFixed(0)}</div>
              <div>High-confidence lessons: {safeNumber(realisticShadowLab?.high_confidence_lessons).toFixed(0)}</div>
              <div>Future policy candidates: {safeNumber(realisticShadowLab?.future_policy_candidates).toFixed(0)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Governance Firewall</div>
              <div>Shadow lab safe: {realisticShadowLab?.shadow_lab_safe ? "yes" : "no"}</div>
              <div>Paper orders placed: {realisticShadowLab?.paper_orders_placed ? "yes" : "no"}</div>
              <div>Alpaca orders placed: {realisticShadowLab?.alpaca_orders_placed ? "yes" : "no"}</div>
              <div>API/provider/LLM calls: {safeNumber(realisticShadowLab?.api_calls_used).toFixed(0)}/{safeNumber(realisticShadowLab?.provider_calls_used).toFixed(0)}/{safeNumber(realisticShadowLab?.llm_calls_used).toFixed(0)}</div>
              <div>Raw archive scanned: {realisticShadowLab?.raw_archive_scanned ? "yes" : "no"}</div>
              <div>Behavior safe to apply: {realisticShadowLab?.behavior_safe_to_apply ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Accelerated Learning & Symbol Intelligence V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is accelerating learning by mining existing trade, replay, virtual, rejected, and opportunity history. It builds symbol-specific behavior profiles, learns best horizons and exits per stock, detects when symbol behavior changes, compresses lessons, and retrieves knowledge quickly. This does not change trading behavior.
            </div>
            <div style={{ fontSize: 12, color: "#9fb1cc", marginTop: 6 }}>
              Astra is comparing similar stocks, sectors, industries, themes, and peer groups so it can learn faster from related symbols. This helps Astra recognize that stocks like NVDA/AMD/AVGO or QBTS/RGTI/IONQ may share trading behaviors while still treating each stock individually.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAcceleratedSymbolLearningDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAcceleratedSymbolLearningDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Historical reviewed", acceleratedSymbolLearning?.historical_records_reviewed],
            ["Learning events", acceleratedSymbolLearning?.accelerated_learning_events],
            ["Replay acceleration", safeNumber(acceleratedSymbolLearning?.replay_acceleration_score).toFixed(1)],
            ["Dominant gap cause", acceleratedSymbolLearning?.dominant_gap_cause],
            ["Symbol profiles", acceleratedSymbolLearning?.symbol_profiles_tracked],
            ["Strongest symbol", acceleratedSymbolLearning?.strongest_symbol_profile],
            ["Highest giveback", acceleratedSymbolLearning?.highest_giveback_symbol],
            ["Most reliable", acceleratedSymbolLearning?.most_reliable_symbol],
            ["Best horizon", Object.entries(acceleratedSymbolLearning?.best_horizon_by_symbol || {}).slice(0, 1).map(([k, v]) => `${k} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Best exit", Object.entries(acceleratedSymbolLearning?.best_exit_style_by_symbol || {}).slice(0, 1).map(([k, v]) => `${k} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Best catalyst", Object.entries(acceleratedSymbolLearning?.best_catalyst_by_symbol || {}).slice(0, 1).map(([k, v]) => `${k} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Best regime", Object.entries(acceleratedSymbolLearning?.best_regime_by_symbol || {}).slice(0, 1).map(([k, v]) => `${k} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Strongest cluster", acceleratedSymbolLearning?.strongest_symbol_cluster],
            ["Missed profit driver", acceleratedSymbolLearning?.top_missed_profit_driver],
            ["Highest ROI area", acceleratedSymbolLearning?.highest_roi_learning_area],
            ["Behavior drift", (acceleratedSymbolLearning?.symbols_with_behavior_drift || []).join(", ") || "none"],
            ["Highest drift", acceleratedSymbolLearning?.highest_drift_symbol],
            ["Most stable", acceleratedSymbolLearning?.most_stable_symbol],
            ["Regime overrides", acceleratedSymbolLearning?.regime_override_count],
            ["Compressed lessons", acceleratedSymbolLearning?.compressed_lessons],
            ["Retrieval latency", `${safeNumber(acceleratedSymbolLearning?.retrieval_latency_ms).toFixed(2)}ms`],
            ["Strongest sector", acceleratedSymbolLearning?.strongest_sector_behavior],
            ["Strongest industry", acceleratedSymbolLearning?.strongest_industry_behavior],
            ["Strongest theme", acceleratedSymbolLearning?.strongest_theme_behavior],
            ["Strongest peer group", acceleratedSymbolLearning?.strongest_peer_group_behavior],
            ["Best peer horizon", Object.entries(acceleratedSymbolLearning?.best_peer_group_horizon || {}).slice(0, 1).map(([k, v]) => `${String(k).replaceAll("_", " ")} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Best peer exit", Object.entries(acceleratedSymbolLearning?.best_peer_group_exit_style || {}).slice(0, 1).map(([k, v]) => `${String(k).replaceAll("_", " ")} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Giveback peer", acceleratedSymbolLearning?.highest_giveback_peer_group],
            ["Transfer confidence", safeNumber(acceleratedSymbolLearning?.transferable_learning_confidence).toFixed(1)],
            ["Peer learning", safeNumber(acceleratedSymbolLearning?.peer_group_learning_score).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(acceleratedSymbolLearning?.shadow_recommendation || "Continue accelerated symbol learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showAcceleratedSymbolLearningDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Peer & Cluster Learning</div>
              <div>Clusters: {JSON.stringify(acceleratedSymbolLearning?.symbol_clusters || {})}</div>
              <div>Transferable lessons: {(acceleratedSymbolLearning?.transferable_lessons || []).join(", ") || "warming up"}</div>
              <div>Cross-symbol pattern: {String(acceleratedSymbolLearning?.strongest_cross_symbol_pattern || "warming up").replaceAll("_", " ")}</div>
              <div>Cluster score: {safeNumber(acceleratedSymbolLearning?.cluster_learning_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Drift & Recency Guards</div>
              <div>Drift warning: {String(acceleratedSymbolLearning?.symbol_drift_warning || "warming up").replaceAll("_", " ")}</div>
              <div>Sector/theme/peer drift: {safeNumber(acceleratedSymbolLearning?.sector_drift_score).toFixed(1)} / {safeNumber(acceleratedSymbolLearning?.theme_drift_score).toFixed(1)} / {safeNumber(acceleratedSymbolLearning?.peer_group_drift_score).toFixed(1)}</div>
              <div>Symbol stability: {safeNumber(acceleratedSymbolLearning?.symbol_stability_score).toFixed(1)}</div>
              <div>Regime override count: {safeNumber(acceleratedSymbolLearning?.regime_override_count).toFixed(0)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Compression & Safety</div>
              <div>Indexed records: {safeNumber(acceleratedSymbolLearning?.indexed_learning_records).toFixed(0)}</div>
              <div>Full scans avoided: {safeNumber(acceleratedSymbolLearning?.full_scan_avoided_count).toFixed(0)}</div>
              <div>Dashboard scan rows: {safeNumber(acceleratedSymbolLearning?.dashboard_scan_rows).toFixed(0)}</div>
              <div>API/provider/LLM calls: {safeNumber(acceleratedSymbolLearning?.api_calls_used).toFixed(0)}/{safeNumber(acceleratedSymbolLearning?.provider_calls_used).toFixed(0)}/{safeNumber(acceleratedSymbolLearning?.llm_calls_used).toFixed(0)}</div>
              <div>Behavior safe to apply: {acceleratedSymbolLearning?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Ranking changed: {acceleratedSymbolLearning?.ranking_behavior_changed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Learning Prioritization & Resource Allocation V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is automatically identifying its highest-value weaknesses and safely shifting learning focus, replay analysis, worker attention, and memory priority toward the areas most likely to improve future performance. This does not change trades, rankings, exits, sizing, or broker behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveLearningPrioritizationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveLearningPrioritizationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Top weakness", adaptiveLearningPrioritization?.top_weakness],
            ["Secondary weakness", adaptiveLearningPrioritization?.secondary_weakness],
            ["Highest value focus", adaptiveLearningPrioritization?.highest_value_learning_focus],
            ["Expected improvement", safeNumber(adaptiveLearningPrioritization?.expected_improvement_score).toFixed(1)],
            ["Learning ROI", safeNumber(adaptiveLearningPrioritization?.learning_roi_score).toFixed(1)],
            ["Weakness focus", `${safeNumber(adaptiveLearningPrioritization?.weakness_focus_allocation).toFixed(0)}%`],
            ["Balanced learning", `${safeNumber(adaptiveLearningPrioritization?.balanced_learning_allocation).toFixed(0)}%`],
            ["Strength validation", `${safeNumber(adaptiveLearningPrioritization?.strength_validation_allocation).toFixed(0)}%`],
            ["System health", `${safeNumber(adaptiveLearningPrioritization?.system_health_allocation).toFixed(0)}%`],
            ["Worker focus", adaptiveLearningPrioritization?.recommended_worker_focus],
            ["Replay focus", adaptiveLearningPrioritization?.recommended_replay_focus],
            ["Governance", adaptiveLearningPrioritization?.governance_status],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(adaptiveLearningPrioritization?.shadow_recommendation || "Continue adaptive learning prioritization shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showAdaptiveLearningPrioritizationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Weakness Detection</div>
              <div>Confidence: {safeNumber(adaptiveLearningPrioritization?.weakness_confidence).toFixed(1)}</div>
              <div>Trend: {String(adaptiveLearningPrioritization?.weakness_trend || "warming up").replaceAll("_", " ")}</div>
              <div>Persistence: {safeNumber(adaptiveLearningPrioritization?.weakness_persistence).toFixed(1)}</div>
              <div>Real vs noise: {String(adaptiveLearningPrioritization?.weakness_is_real_vs_noise || "warming up").replaceAll("_", " ")}</div>
              {(adaptiveLearningPrioritization?.weakness_rankings || []).slice(0, 5).map((row) => (
                <div key={row?.weakness}>{String(row?.weakness || "unknown").replaceAll("_", " ")}: value {safeNumber(row?.expected_learning_value).toFixed(1)}, noise {safeNumber(row?.noise_risk_score).toFixed(1)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Allocation Guardrails</div>
              <div>Allocation safe: {adaptiveLearningPrioritization?.allocation_safe ? "yes" : "no"}</div>
              <div>Guardrail status: {String(adaptiveLearningPrioritization?.allocation_guardrail_status || "warming up").replaceAll("_", " ")}</div>
              <div>Blocked reason: {String(adaptiveLearningPrioritization?.blocked_allocation_reason || "none").replaceAll("_", " ")}</div>
              <div>Allocation confidence: {safeNumber(adaptiveLearningPrioritization?.allocation_confidence).toFixed(1)}</div>
              <div>Active focus: {Object.entries(adaptiveLearningPrioritization?.active_focus_distribution || {}).map(([k, v]) => `${String(k).replaceAll("_", " ")} ${safeNumber(v).toFixed(0)}%`).join(", ") || "warming up"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Worker, Replay & Memory Focus</div>
              <div>Worker reason: {String(adaptiveLearningPrioritization?.worker_focus_reason || "warming up").replaceAll("_", " ")}</div>
              <div>Worker change: {String(adaptiveLearningPrioritization?.worker_focus_change || "warming up").replaceAll("_", " ")}</div>
              <div>Replay reason: {String(adaptiveLearningPrioritization?.replay_priority_reason || "warming up").replaceAll("_", " ")}</div>
              <div>Memory focus: {String(adaptiveLearningPrioritization?.memory_focus || "warming up").replaceAll("_", " ")}</div>
              <div>Memory weighting: {safeNumber(adaptiveLearningPrioritization?.memory_weighting_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Weakness Drift</div>
              <div>Improving: {String(adaptiveLearningPrioritization?.improving_weakness || "none detected").replaceAll("_", " ")}</div>
              <div>Worsening: {String(adaptiveLearningPrioritization?.worsening_weakness || "none detected").replaceAll("_", " ")}</div>
              <div>Emerging: {String(adaptiveLearningPrioritization?.emerging_weakness || "none detected").replaceAll("_", " ")}</div>
              <div>Resolved: {String(adaptiveLearningPrioritization?.resolved_weakness || "none detected").replaceAll("_", " ")}</div>
              <div>Drift score: {safeNumber(adaptiveLearningPrioritization?.weakness_drift_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Governance & Safety</div>
              <div>Policy readiness: {String(adaptiveLearningPrioritization?.policy_readiness_status || "not ready").replaceAll("_", " ")}</div>
              <div>Behavior safe to apply: {adaptiveLearningPrioritization?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {adaptiveLearningPrioritization?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {adaptiveLearningPrioritization?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {adaptiveLearningPrioritization?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Portfolio allocation changed: {adaptiveLearningPrioritization?.portfolio_allocation_changed ? "yes" : "no"}</div>
              <div>API/provider/LLM calls: {safeNumber(adaptiveLearningPrioritization?.api_calls_used).toFixed(0)}/{safeNumber(adaptiveLearningPrioritization?.provider_calls_used).toFixed(0)}/{safeNumber(adaptiveLearningPrioritization?.llm_calls_used).toFixed(0)}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Autonomous Intelligence, Validation & Governance V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is validating whether its lessons are trustworthy, diagnosing why weaknesses are occurring, proposing safe virtual improvement tests, and monitoring platform safety, learning quality, storage, API use, workers, and performance. This does not change trades, exits, sizing, rankings, or broker behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAutonomousGovernanceDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAutonomousGovernanceDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Truth validation", safeNumber(autonomousGovernance?.truth_validation_score).toFixed(1)],
            ["Lesson reliability", safeNumber(autonomousGovernance?.lesson_reliability_score).toFixed(1)],
            ["Governance score", safeNumber(autonomousGovernance?.governance_score).toFixed(1)],
            ["Warning level", autonomousGovernance?.warning_level],
            ["Primary risk", autonomousGovernance?.primary_risk],
            ["Secondary risk", autonomousGovernance?.secondary_risk],
            ["Top root cause", autonomousGovernance?.top_root_cause],
            ["Highest-value hypothesis", autonomousGovernance?.highest_value_hypothesis],
            ["Recommended virtual test", autonomousGovernance?.recommended_virtual_test],
            ["Closest policy", autonomousGovernance?.closest_policy_to_readiness],
            ["Readiness blocker", autonomousGovernance?.readiness_blocker],
            ["Policy readiness", safeNumber(autonomousGovernance?.policy_readiness_score).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(autonomousGovernance?.shadow_recommendation || "Continue autonomous validation and governance shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showAutonomousGovernanceDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Evidence Truth Validation</div>
              <div>Evidence count: {safeNumber(autonomousGovernance?.evidence_count).toFixed(0)}</div>
              <div>Sample quality: {safeNumber(autonomousGovernance?.sample_size_quality).toFixed(1)}</div>
              <div>Evidence consistency: {safeNumber(autonomousGovernance?.evidence_consistency).toFixed(1)}</div>
              <div>Conflict score: {safeNumber(autonomousGovernance?.conflicting_evidence_score).toFixed(1)}</div>
              <div>Outlier risk: {safeNumber(autonomousGovernance?.outlier_risk_score).toFixed(1)}</div>
              <div>Status: {String(autonomousGovernance?.truth_validation_status || "warming up").replaceAll("_", " ")}</div>
              <div>Strongest lesson: {String(autonomousGovernance?.strongest_validated_lesson || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest lesson: {String(autonomousGovernance?.weakest_validated_lesson || "warming up").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Self-Healing Diagnostics</div>
              <div>Likely systems: {(autonomousGovernance?.likely_contributing_systems || []).slice(0, 4).map((v) => String(v).replaceAll("_", " ")).join(", ") || "warming up"}</div>
              <div>Hypothesis: {String(autonomousGovernance?.improvement_hypothesis || autonomousGovernance?.highest_value_hypothesis || "warming up").replaceAll("_", " ")}</div>
              <div>Expected gain: {safeNumber(autonomousGovernance?.expected_gain).toFixed(1)}</div>
              <div>Confidence: {safeNumber(autonomousGovernance?.confidence).toFixed(1)}</div>
              <div>Virtual test: {String(autonomousGovernance?.virtual_test_recommended || autonomousGovernance?.recommended_virtual_test || "warming up").replaceAll("_", " ")}</div>
              <div>Status: {String(autonomousGovernance?.self_healing_status || "shadow diagnostics only").replaceAll("_", " ")}</div>
              <div>Repair readiness: {String(autonomousGovernance?.autonomous_repair_readiness || "not ready").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Governance Safety</div>
              <div>Trading safety: {String(autonomousGovernance?.trading_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Learning safety: {String(autonomousGovernance?.learning_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Storage safety: {String(autonomousGovernance?.storage_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Performance safety: {String(autonomousGovernance?.performance_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>API safety: {String(autonomousGovernance?.api_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Infrastructure safety: {String(autonomousGovernance?.infrastructure_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Knowledge safety: {String(autonomousGovernance?.knowledge_safety_status || "warming up").replaceAll("_", " ")}</div>
              <div>Recommendation: {String(autonomousGovernance?.governance_recommendation || "continue shadow governance monitoring").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Policy Readiness</div>
              <div>Ready policies: {(autonomousGovernance?.ready_policies || []).join(", ") || "none"}</div>
              <div>Not ready count: {(autonomousGovernance?.not_ready_policies || []).length}</div>
              <div>Human review required: {autonomousGovernance?.human_review_required === false ? "no" : "yes"}</div>
              <div>Auto apply allowed: {autonomousGovernance?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Behavior safe to apply: {autonomousGovernance?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Paper execution changed: {autonomousGovernance?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Broker behavior changed: {autonomousGovernance?.broker_behavior_changed ? "yes" : "no"}</div>
              <div>Ranking changed: {autonomousGovernance?.ranking_behavior_changed ? "yes" : "no"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Fast Path & API Guardrails</div>
              <div>Build time: {safeNumber(autonomousGovernance?.build_ms).toFixed(2)}ms</div>
              <div>Dashboard scan rows: {safeNumber(autonomousGovernance?.dashboard_scan_rows).toFixed(0)}</div>
              <div>Raw history scanned: {autonomousGovernance?.raw_history_scanned ? "yes" : "no"}</div>
              <div>Raw archive scanned: {autonomousGovernance?.raw_archive_scanned ? "yes" : "no"}</div>
              <div>Bandwidth saving: {autonomousGovernance?.bandwidth_saving_mode === false ? "no" : "yes"}</div>
              <div>API/provider/LLM calls: {safeNumber(autonomousGovernance?.api_calls_used).toFixed(0)}/{safeNumber(autonomousGovernance?.provider_calls_used).toFixed(0)}/{safeNumber(autonomousGovernance?.llm_calls_used).toFixed(0)}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Context & Evidence Expansion Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is learning from active trades before they close, from rejected candidates it did not select, and from catalysts that may explain why stocks are moving. This helps Astra learn faster without taking more trades or changing behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowContextEvidenceExpansionDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showContextEvidenceExpansionDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Active trades tracked", safeNumber(contextEvidenceExpansion?.active_trades_tracked).toFixed(0)],
            ["Strongest open trade", contextEvidenceExpansion?.strongest_open_trade],
            ["Weakest open trade", contextEvidenceExpansion?.weakest_open_trade],
            ["Highest giveback", contextEvidenceExpansion?.highest_giveback_symbol],
            ["Rejected reviewed", safeNumber(contextEvidenceExpansion?.rejected_candidates_reviewed).toFixed(0)],
            ["Rejection accuracy", `${safeNumber(contextEvidenceExpansion?.rejection_accuracy).toFixed(1)}%`],
            ["Missed winners", safeNumber(contextEvidenceExpansion?.missed_winners).toFixed(0)],
            ["Avoided losers", safeNumber(contextEvidenceExpansion?.avoided_losers).toFixed(0)],
            ["Biggest missed", contextEvidenceExpansion?.biggest_missed_symbol],
            ["Dominant catalyst", contextEvidenceExpansion?.dominant_catalyst_type],
            ["Unknown catalyst rate", `${safeNumber(contextEvidenceExpansion?.unknown_catalyst_rate).toFixed(1)}%`],
            ["Catalyst coverage", safeNumber(contextEvidenceExpansion?.catalyst_coverage_score).toFixed(1)],
            ["Best catalyst horizon", contextEvidenceExpansion?.best_catalyst_horizon],
            ["Top learning gap", contextEvidenceExpansion?.top_learning_gap],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(contextEvidenceExpansion?.shadow_recommendation || "Collecting open-trade, rejected-candidate, and catalyst evidence.").replaceAll("_", " ")}
          </div>
        </div>
        {showContextEvidenceExpansionDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Open Trade Learning</div>
              <div>Symbols: {(contextEvidenceExpansion?.active_trade_symbols || []).join(", ") || "warming up"}</div>
              <div>Profit decay symbol: {String(contextEvidenceExpansion?.highest_profit_decay_symbol || "warming up")}</div>
              <div>Best horizon: {String(contextEvidenceExpansion?.best_open_trade_horizon || "warming up").replaceAll("_", " ")}</div>
              <div>Continuation score: {safeNumber(contextEvidenceExpansion?.open_trade_continuation_score).toFixed(1)}</div>
              <div>Profit capture score: {safeNumber(contextEvidenceExpansion?.open_trade_profit_capture_score).toFixed(1)}</div>
              <div>Confidence: {safeNumber(contextEvidenceExpansion?.open_trade_learning_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Rejected Candidate Learning</div>
              <div>Correct rejections: {safeNumber(contextEvidenceExpansion?.correct_rejections).toFixed(0)}</div>
              <div>Best correct rejection: {String(contextEvidenceExpansion?.best_correct_rejection || "warming up")}</div>
              <div>Worst reason: {String(contextEvidenceExpansion?.worst_rejection_reason || "warming up").replaceAll("_", " ")}</div>
              <div>Learning score: {safeNumber(contextEvidenceExpansion?.rejection_learning_score).toFixed(1)}</div>
              <div>Confidence: {safeNumber(contextEvidenceExpansion?.rejected_candidate_learning_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Catalyst Expansion</div>
              <div>Records: {safeNumber(contextEvidenceExpansion?.catalyst_records).toFixed(0)}</div>
              <div>Strongest: {String(contextEvidenceExpansion?.strongest_catalyst_type || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest: {String(contextEvidenceExpansion?.weakest_catalyst_type || "warming up").replaceAll("_", " ")}</div>
              <div>Highest giveback catalyst: {String(contextEvidenceExpansion?.highest_giveback_catalyst || "warming up").replaceAll("_", " ")}</div>
              <div>Confidence: {safeNumber(contextEvidenceExpansion?.catalyst_learning_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Provider calls: {safeNumber(contextEvidenceExpansion?.provider_calls_used).toFixed(0)}</div>
              <div>LLM calls: {safeNumber(contextEvidenceExpansion?.llm_calls_used).toFixed(0)}</div>
              <div>Behavior safe to apply: {contextEvidenceExpansion?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Ranking changed: {contextEvidenceExpansion?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {contextEvidenceExpansion?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Forced exits: {contextEvidenceExpansion?.forced_exits_enabled ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Long-Term Memory, Symbol Intelligence & Retrieval V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is organizing long-term memory, learning how individual symbols behave, cleaning up old low-value raw data, and indexing historical knowledge so it can retrieve useful lessons quickly without slowing the dashboard.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowLongTermMemoryDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showLongTermMemoryDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Storage health", safeNumber(longTermMemorySymbolRetrieval?.storage_health_score).toFixed(1)],
            ["Memory pressure", safeNumber(longTermMemorySymbolRetrieval?.memory_pressure_score).toFixed(1)],
            ["Cleanup status", longTermMemorySymbolRetrieval?.cleanup_status],
            ["Days until pressure", safeNumber(longTermMemorySymbolRetrieval?.estimated_days_until_storage_pressure).toFixed(0)],
            ["Symbol profiles", safeNumber(longTermMemorySymbolRetrieval?.symbol_profiles_tracked).toFixed(0)],
            ["Strongest symbol", longTermMemorySymbolRetrieval?.strongest_symbol_profile],
            ["Highest giveback", longTermMemorySymbolRetrieval?.highest_giveback_symbol],
            ["Symbol memory", safeNumber(longTermMemorySymbolRetrieval?.symbol_memory_quality_score).toFixed(1)],
            ["Indexed records", safeNumber(longTermMemorySymbolRetrieval?.indexed_records).toFixed(0)],
            ["Retrieval latency", `${safeNumber(longTermMemorySymbolRetrieval?.retrieval_latency_ms).toFixed(2)}ms`],
            ["Retrieval health", safeNumber(longTermMemorySymbolRetrieval?.retrieval_health_score).toFixed(1)],
            ["Cache freshness", longTermMemorySymbolRetrieval?.cache_freshness],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(longTermMemorySymbolRetrieval?.shadow_recommendation || "Continue long-term memory and retrieval learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showLongTermMemoryDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Storage Retention</div>
              <div>Raw event size: {safeNumber(longTermMemorySymbolRetrieval?.raw_event_size_bytes).toFixed(0)} bytes</div>
              <div>Summary size: {safeNumber(longTermMemorySymbolRetrieval?.summary_size_bytes).toFixed(0)} bytes</div>
              <div>Cache size: {safeNumber(longTermMemorySymbolRetrieval?.cache_size_bytes).toFixed(0)} bytes</div>
              <div>Archive size: {safeNumber(longTermMemorySymbolRetrieval?.archive_size_bytes).toFixed(0)} bytes</div>
              <div>Cleanup action taken: {String(longTermMemorySymbolRetrieval?.cleanup_action_taken || "none diagnostics only").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Symbol Intelligence</div>
              <div>Weakest symbol: {String(longTermMemorySymbolRetrieval?.weakest_symbol_profile || "warming up").replaceAll("_", " ")}</div>
              <div>Best behavioral edge: {String(longTermMemorySymbolRetrieval?.best_behavioral_edge_symbol || "warming up").replaceAll("_", " ")}</div>
              <div>Most reliable symbol: {String(longTermMemorySymbolRetrieval?.most_reliable_symbol || "warming up").replaceAll("_", " ")}</div>
              {(longTermMemorySymbolRetrieval?.symbol_profile_sample || []).slice(0, 4).map((profile) => (
                <div key={profile?.symbol}>{profile?.symbol || "unknown"}: edge {safeNumber(profile?.behavioral_edge_score).toFixed(2)}, giveback {safeNumber(profile?.giveback_risk).toFixed(2)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Knowledge Retrieval</div>
              <div>Strongest index: {String(longTermMemorySymbolRetrieval?.strongest_index || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest index: {String(longTermMemorySymbolRetrieval?.weakest_index || "warming up").replaceAll("_", " ")}</div>
              <div>Lookup success: {safeNumber(longTermMemorySymbolRetrieval?.recent_lookup_success_rate).toFixed(1)}%</div>
              <div>Full scans avoided: {safeNumber(longTermMemorySymbolRetrieval?.full_scan_avoided_count).toFixed(0)}</div>
              <div>Index fields: {(longTermMemorySymbolRetrieval?.index_fields || []).slice(0, 6).join(", ") || "warming up"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Dashboard Fast Path</div>
              <div>Dashboard scan rows: {safeNumber(longTermMemorySymbolRetrieval?.dashboard_scan_rows).toFixed(0)}</div>
              <div>Hot rows scanned on rebuild: {safeNumber(longTermMemorySymbolRetrieval?.hot_rows_scanned_for_rebuild).toFixed(0)}</div>
              <div>Cache status: {String(longTermMemorySymbolRetrieval?.cache_status || "warming up").replaceAll("_", " ")}</div>
              <div>Raw archive scanned during render: {longTermMemorySymbolRetrieval?.raw_archive_scan_during_render ? "yes" : "no"}</div>
              <div>SQLite adapter: {String(longTermMemorySymbolRetrieval?.sqlite_archive_adapter_status || "prepared optional").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Behavior safe to apply: {longTermMemorySymbolRetrieval?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {longTermMemorySymbolRetrieval?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {longTermMemorySymbolRetrieval?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {longTermMemorySymbolRetrieval?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Position sizing changed: {longTermMemorySymbolRetrieval?.position_sizing_changed ? "yes" : "no"}</div>
              <div>Thresholds changed: {longTermMemorySymbolRetrieval?.thresholds_changed ? "yes" : "no"}</div>
              <div>API/provider/LLM calls: {safeNumber(longTermMemorySymbolRetrieval?.api_calls_used).toFixed(0)}/{safeNumber(longTermMemorySymbolRetrieval?.provider_calls_used).toFixed(0)}/{safeNumber(longTermMemorySymbolRetrieval?.llm_calls_used).toFixed(0)}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Full Opportunity Lifecycle Learning Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is learning from every opportunity it sees, including trades taken, rejected, skipped, ignored, blocked, virtual-only, winning, and losing opportunities. It routes each opportunity through relevant learning systems while keeping raw memory separate from fast dashboard summaries.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowFullOpportunityLifecycleDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showFullOpportunityLifecycleDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Opportunities tracked", safeNumber(fullOpportunityLifecycle?.opportunities_tracked).toFixed(0)],
            ["Learning completeness", `${safeNumber(fullOpportunityLifecycle?.learning_completeness_score).toFixed(1)}%`],
            ["Missed winners", safeNumber(fullOpportunityLifecycle?.missed_winners).toFixed(0)],
            ["Avoided losers", safeNumber(fullOpportunityLifecycle?.avoided_losers).toFixed(0)],
            ["Strongest connection", fullOpportunityLifecycle?.strongest_learning_connection],
            ["Most predictive feature", fullOpportunityLifecycle?.most_predictive_feature],
            ["Highest value focus", fullOpportunityLifecycle?.highest_value_learning_focus],
            ["Memory quality", safeNumber(fullOpportunityLifecycle?.memory_quality_score).toFixed(1)],
            ["Storage health", safeNumber(fullOpportunityLifecycle?.storage_health_score).toFixed(1)],
            ["Memory pressure", safeNumber(fullOpportunityLifecycle?.memory_pressure_score).toFixed(1)],
            ["Cache freshness", fullOpportunityLifecycle?.cache_freshness],
            ["Dashboard scan rows", safeNumber(fullOpportunityLifecycle?.dashboard_scan_rows).toFixed(0)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(fullOpportunityLifecycle?.shadow_recommendation || "Continue full opportunity lifecycle learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showFullOpportunityLifecycleDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Lifecycle Coverage</div>
              <div>Paper trades: {safeNumber(fullOpportunityLifecycle?.paper_trades_tracked).toFixed(0)}</div>
              <div>Virtual trades: {safeNumber(fullOpportunityLifecycle?.virtual_trades_tracked).toFixed(0)}</div>
              <div>Rejected: {safeNumber(fullOpportunityLifecycle?.rejected_tracked).toFixed(0)}</div>
              <div>Skipped: {safeNumber(fullOpportunityLifecycle?.skipped_tracked).toFixed(0)}</div>
              <div>Ignored: {safeNumber(fullOpportunityLifecycle?.ignored_tracked).toFixed(0)}</div>
              <div>Blocked: {safeNumber(fullOpportunityLifecycle?.blocked_tracked).toFixed(0)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Cross-System Learning Graph</div>
              <div>Nodes: {safeNumber(fullOpportunityLifecycle?.graph_nodes).toFixed(0)}</div>
              <div>Edges: {safeNumber(fullOpportunityLifecycle?.graph_edges).toFixed(0)}</div>
              <div>Cross-system score: {safeNumber(fullOpportunityLifecycle?.cross_system_learning_score).toFixed(1)}</div>
              <div>Weakest connection: {String(fullOpportunityLifecycle?.weakest_learning_connection || "warming up").replaceAll("_", " ")}</div>
              <div>Systems receiving evidence: {Object.keys(fullOpportunityLifecycle?.systems_receiving_evidence || {}).length}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Predictive Feature Attribution</div>
              <div>Least predictive feature: {String(fullOpportunityLifecycle?.least_predictive_feature || "warming up").replaceAll("_", " ")}</div>
              <div>Attribution confidence: {safeNumber(fullOpportunityLifecycle?.feature_attribution_confidence).toFixed(1)}</div>
              <div>Top profit features: {(fullOpportunityLifecycle?.top_profit_features || []).length ? fullOpportunityLifecycle.top_profit_features.slice(0, 3).join(", ") : "warming up"}</div>
              <div>Top loss features: {(fullOpportunityLifecycle?.top_loss_features || []).length ? fullOpportunityLifecycle.top_loss_features.slice(0, 3).join(", ") : "warming up"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Memory & Storage Optimization</div>
              <div>Last updated: {String(fullOpportunityLifecycle?.last_updated || "warming up")}</div>
              <div>Cache status: {String(fullOpportunityLifecycle?.cache_status || "warming up").replaceAll("_", " ")} | Age: {fullOpportunityLifecycle?.cache_age_seconds === null || fullOpportunityLifecycle?.cache_age_seconds === undefined ? "n/a" : `${safeNumber(fullOpportunityLifecycle?.cache_age_seconds).toFixed(1)}s`}</div>
              <div>Raw events: {safeNumber(fullOpportunityLifecycle?.raw_event_count).toFixed(0)} | Summaries: {safeNumber(fullOpportunityLifecycle?.compact_summary_count).toFixed(0)} | Archives: {safeNumber(fullOpportunityLifecycle?.archive_count).toFixed(0)}</div>
              <div>Compaction: {String(fullOpportunityLifecycle?.compaction_status || "warming up").replaceAll("_", " ")}</div>
              <div>API calls: {safeNumber(fullOpportunityLifecycle?.api_calls_used).toFixed(0)} | Provider calls: {safeNumber(fullOpportunityLifecycle?.provider_calls_used).toFixed(0)} | LLM calls: {safeNumber(fullOpportunityLifecycle?.llm_calls_used).toFixed(0)}</div>
              <div>Bandwidth saving: {fullOpportunityLifecycle?.bandwidth_saving_mode ? "enabled" : "review"} | API budget: {String(fullOpportunityLifecycle?.api_budget_status || "cached_local_only").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Behavior safe to apply: {fullOpportunityLifecycle?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {fullOpportunityLifecycle?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {fullOpportunityLifecycle?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {fullOpportunityLifecycle?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Position sizing changed: {fullOpportunityLifecycle?.position_sizing_changed ? "yes" : "no"}</div>
              <div>Thresholds changed: {fullOpportunityLifecycle?.thresholds_changed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Confidence Calibration & Performance Attribution V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying whether higher-confidence trades actually perform better, which grades produce the best outcomes, where profits and losses come from, and whether confidence-weighted position sizing could eventually be justified. No sizing or trading behavior is changed yet.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowConfidenceAttributionDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showConfidenceAttributionDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Best confidence bucket", confidenceAttribution?.best_confidence_bucket],
            ["Worst confidence bucket", confidenceAttribution?.worst_confidence_bucket],
            ["Calibration score", safeNumber(confidenceAttribution?.confidence_calibration_score).toFixed(1)],
            ["Predictive power", safeNumber(confidenceAttribution?.confidence_predictive_power).toFixed(1)],
            ["Sizing readiness", safeNumber(confidenceAttribution?.sizing_readiness_score || confidenceAttribution?.confidence_sizing_readiness).toFixed(1)],
            ["Best grade", confidenceAttribution?.best_grade],
            ["Best confidence / horizon", confidenceAttribution?.best_confidence_horizon_pair],
            ["Top profit driver", confidenceAttribution?.top_profit_driver],
            ["Top loss driver", confidenceAttribution?.top_loss_driver],
            ["Daily positive rate", `${safeNumber(confidenceAttribution?.daily_positive_rate).toFixed(1)}%`],
            ["Current day return", `${safeNumber(confidenceAttribution?.current_day_return).toFixed(2)}%`],
            ["Current day status", confidenceAttribution?.current_day_status],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(confidenceAttribution?.shadow_recommendation || "Keep confidence and sizing decisions shadow-only until evidence is stronger.").replaceAll("_", " ")}
          </div>
        </div>
        {showConfidenceAttributionDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Confidence Buckets</div>
              {Object.entries(confidenceAttribution?.confidence_bucket_stats || {}).slice(0, 7).map(([bucket, stats]) => (
                <div key={bucket}>
                  {String(bucket).replaceAll("_", " ")}: {safeNumber(stats?.trade_count).toFixed(0)} trades, {safeNumber(stats?.avg_return).toFixed(2)}% avg
                </div>
              ))}
              <div>Return monotonicity: {safeNumber(confidenceAttribution?.return_monotonicity).toFixed(1)}</div>
              <div>Risk monotonicity: {safeNumber(confidenceAttribution?.risk_adjusted_monotonicity).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Grade Calibration</div>
              {Object.entries(confidenceAttribution?.grade_bucket_stats || {}).slice(0, 5).map(([grade, stats]) => (
                <div key={grade}>
                  {grade}: {safeNumber(stats?.trade_count).toFixed(0)} trades, {safeNumber(stats?.win_rate).toFixed(1)}% WR, {safeNumber(stats?.avg_return).toFixed(2)}% avg
                </div>
              ))}
              <div>Weakest grade: {String(confidenceAttribution?.weakest_grade || "warming up").replaceAll("_", " ")}</div>
              <div>Grade predictive power: {safeNumber(confidenceAttribution?.grade_predictive_power).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Attribution</div>
              <div>Profit by horizon: {Object.entries(confidenceAttribution?.profit_by_horizon || {}).slice(0, 4).map(([k, v]) => `${String(k).replaceAll("_", " ")} ${safeNumber(v).toFixed(2)}%`).join(", ") || "warming up"}</div>
              <div>Profit by grade: {Object.entries(confidenceAttribution?.profit_by_grade || {}).slice(0, 4).map(([k, v]) => `${k} ${safeNumber(v).toFixed(2)}%`).join(", ") || "warming up"}</div>
              <div>Profit concentration: {safeNumber(confidenceAttribution?.concentration_of_profit).toFixed(1)}%</div>
              <div>Warning: {String(confidenceAttribution?.concentration_warning || "warming up").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Sizing Readiness Safety</div>
              <div>Ready for confidence-weighted sizing: {confidenceAttribution?.ready_for_confidence_weighted_sizing ? "yes" : "no"}</div>
              <div>Reason: {String(confidenceAttribution?.reason_not_ready || "minimum evidence still required").replaceAll("_", " ")}</div>
              <div>Minimum evidence: {String(confidenceAttribution?.minimum_evidence_needed || "more broker confirmed outcomes").replaceAll("_", " ")}</div>
              <div>Position sizing changed: {confidenceAttribution?.position_sizing_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {confidenceAttribution?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Behavior safe to apply: {confidenceAttribution?.behavior_safe_to_apply ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Catalyst, Theme, Narrative & Capital Flow Intelligence V2</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying why stocks move, which catalysts and themes are leading, how narratives spread, and where capital appears to be flowing. This is shadow-only and does not change trading behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowCatalystThemeNarrativeDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showCatalystThemeNarrativeDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(catalystThemeNarrative?.evidence_count).toFixed(0)],
            ["Catalyst records", safeNumber(catalystThemeNarrative?.catalyst_records).toFixed(0)],
            ["Dominant catalyst", catalystThemeNarrative?.dominant_catalyst],
            ["Strongest catalyst", catalystThemeNarrative?.strongest_catalyst_type],
            ["Weakest catalyst", catalystThemeNarrative?.weakest_catalyst_type],
            ["Coverage", `${safeNumber(catalystThemeNarrative?.catalyst_coverage_score).toFixed(1)}%`],
            ["Unknown rate", `${safeNumber(catalystThemeNarrative?.unknown_catalyst_rate).toFixed(1)}%`],
            ["Truth score", safeNumber(catalystThemeNarrative?.catalyst_truth_score).toFixed(1)],
            ["Strongest theme", catalystThemeNarrative?.strongest_theme],
            ["Dominant theme", catalystThemeNarrative?.dominant_theme],
            ["Strongest sector", catalystThemeNarrative?.strongest_sector],
            ["Weakest sector", catalystThemeNarrative?.weakest_sector],
            ["Dominant industry", catalystThemeNarrative?.dominant_industry],
            ["Capital flow", catalystThemeNarrative?.strongest_capital_flow],
            ["Market leader", catalystThemeNarrative?.market_leader],
            ["Learning gap", catalystThemeNarrative?.top_learning_gap],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(catalystThemeNarrative?.shadow_recommendation || "Continue catalyst, theme, narrative, and capital-flow learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showCatalystThemeNarrativeDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Multi-Catalyst Learning</div>
              <div>Secondary catalyst: {String(catalystThemeNarrative?.secondary_catalyst || "none").replaceAll("_", " ")}</div>
              <div>Supporting: {(catalystThemeNarrative?.supporting_catalysts || []).slice(0, 5).map((x) => String(x).replaceAll("_", " ")).join(", ") || "warming up"}</div>
              <div>Confidence: {safeNumber(catalystThemeNarrative?.catalyst_confidence).toFixed(1)}</div>
              <div>Agreement: {safeNumber(catalystThemeNarrative?.catalyst_agreement_score).toFixed(1)}</div>
              <div>Multi-catalyst score: {safeNumber(catalystThemeNarrative?.multi_catalyst_score).toFixed(1)}</div>
              <div>Most reliable: {String(catalystThemeNarrative?.most_reliable_catalyst || "warming up").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Catalyst Decay & Horizon</div>
              <div>Decay score: {safeNumber(catalystThemeNarrative?.catalyst_decay_learning_score).toFixed(1)}</div>
              <div>Longest lasting: {String(catalystThemeNarrative?.longest_lasting_catalyst || "warming up").replaceAll("_", " ")}</div>
              <div>Fastest decay: {String(catalystThemeNarrative?.fastest_decay_catalyst || "warming up").replaceAll("_", " ")}</div>
              <div>Horizon confidence: {safeNumber(catalystThemeNarrative?.catalyst_horizon_confidence).toFixed(1)}</div>
              {Object.entries(catalystThemeNarrative?.best_horizon_by_catalyst || {}).slice(0, 6).map(([name, horizon]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {String(horizon).replaceAll("_", " ")}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Theme & Rotation</div>
              <div>Weakest theme: {String(catalystThemeNarrative?.weakest_theme || "warming up").replaceAll("_", " ")}</div>
              <div>Emerging theme: {String(catalystThemeNarrative?.emerging_theme || "warming up").replaceAll("_", " ")}</div>
              <div>Fading theme: {String(catalystThemeNarrative?.fading_theme || "warming up").replaceAll("_", " ")}</div>
              <div>Theme persistence: {safeNumber(catalystThemeNarrative?.theme_persistence_score).toFixed(1)}</div>
              <div>Theme confidence: {safeNumber(catalystThemeNarrative?.theme_confidence).toFixed(1)}</div>
              <div>Sector rotation: {safeNumber(catalystThemeNarrative?.sector_rotation_score).toFixed(1)}</div>
              <div>Industry rotation: {safeNumber(catalystThemeNarrative?.industry_rotation_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Narrative & Capital Flow</div>
              <div>Strongest flow: {String(catalystThemeNarrative?.strongest_capital_flow || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest flow: {String(catalystThemeNarrative?.weakest_capital_flow || "warming up").replaceAll("_", " ")}</div>
              <div>Flow confidence: {safeNumber(catalystThemeNarrative?.capital_flow_confidence).toFixed(1)}</div>
              <div>Rotation signal: {String(catalystThemeNarrative?.institutional_rotation_signal || "warming up").replaceAll("_", " ")}</div>
              <div>Narrative chain: {String(catalystThemeNarrative?.strongest_narrative_chain || "warming up").replaceAll("_", " ")}</div>
              <div>Narrative score: {safeNumber(catalystThemeNarrative?.narrative_learning_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Archetype Pairing</div>
              <div>Best pair: {String(catalystThemeNarrative?.best_catalyst_archetype_pair || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest pair: {String(catalystThemeNarrative?.weakest_catalyst_archetype_pair || "warming up").replaceAll("_", " ")}</div>
              <div>Prediction accuracy: {safeNumber(catalystThemeNarrative?.catalyst_prediction_accuracy).toFixed(1)}</div>
              <div>Confidence truth: {safeNumber(catalystThemeNarrative?.catalyst_confidence_truth).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Provider calls: {safeNumber(catalystThemeNarrative?.provider_calls_used).toFixed(0)}</div>
              <div>LLM calls: {safeNumber(catalystThemeNarrative?.llm_calls_used).toFixed(0)}</div>
              <div>Behavior safe to apply: {catalystThemeNarrative?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {catalystThemeNarrative?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {catalystThemeNarrative?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {catalystThemeNarrative?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Forced exits: {catalystThemeNarrative?.forced_exits_enabled ? "enabled" : "disabled"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Learning Acceleration & Retention Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying which lessons are most important, which evidence should be trusted most, where learning coverage is weak, and which learning systems agree or conflict. This helps Astra learn more from each trade without increasing trading risk.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowLearningAccelerationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showLearningAccelerationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Top priority", learningAccelerationRetention?.top_learning_priority],
            ["Weighted confidence", safeNumber(learningAccelerationRetention?.weighted_confidence_score).toFixed(1)],
            ["Knowledge retention", safeNumber(learningAccelerationRetention?.knowledge_retention_score).toFixed(1)],
            ["Coverage score", safeNumber(learningAccelerationRetention?.coverage_score).toFixed(1)],
            ["Agreement score", safeNumber(learningAccelerationRetention?.agreement_score).toFixed(1)],
            ["Conflict status", learningAccelerationRetention?.conflict_detected ? String(learningAccelerationRetention?.conflict_type || "conflict detected") : "no conflict"],
            ["Meta-learning score", safeNumber(learningAccelerationRetention?.meta_learning_score).toFixed(1)],
            ["Strongest lesson", learningAccelerationRetention?.strongest_new_lesson],
            ["Weakest coverage", learningAccelerationRetention?.weakest_coverage_area],
            ["Worker focus", learningAccelerationRetention?.recommended_worker_focus],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(learningAccelerationRetention?.shadow_learning_recommendation || "Collecting meta-learning evidence.").replaceAll("_", " ")}
          </div>
        </div>
        {showLearningAccelerationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Priority Engine</div>
              <div>Top: {String(learningAccelerationRetention?.top_learning_priority || "insufficient data").replaceAll("_", " ")}</div>
              <div>Secondary: {String(learningAccelerationRetention?.secondary_learning_priority || "insufficient data").replaceAll("_", " ")}</div>
              <div>Lowest: {String(learningAccelerationRetention?.lowest_learning_priority || "insufficient data").replaceAll("_", " ")}</div>
              <div>Confidence: {safeNumber(learningAccelerationRetention?.priority_confidence).toFixed(1)}</div>
              <div>Reason: {String(learningAccelerationRetention?.priority_reason || "warming up").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Evidence Weighting</div>
              <div>Strongest source: {String(learningAccelerationRetention?.strongest_evidence_source || "insufficient data").replaceAll("_", " ")}</div>
              <div>Weakest source: {String(learningAccelerationRetention?.weakest_evidence_source || "insufficient data").replaceAll("_", " ")}</div>
              <div>Quality: {String(learningAccelerationRetention?.evidence_quality_label || "warming up").replaceAll("_", " ")}</div>
              {Object.entries(learningAccelerationRetention?.evidence_mix || {}).slice(0, 8).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Knowledge Retention</div>
              <div>Consolidated lessons: {safeNumber(learningAccelerationRetention?.consolidated_lessons_count).toFixed(0)}</div>
              <div>Status: {String(learningAccelerationRetention?.overnight_consolidation_status || "warming up").replaceAll("_", " ")}</div>
              {(learningAccelerationRetention?.promoted_lessons || []).slice(0, 4).map((lesson) => (
                <div key={lesson}>{String(lesson)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Coverage Monitor</div>
              <div>Strongest area: {String(learningAccelerationRetention?.strongest_coverage_area || "insufficient data").replaceAll("_", " ")}</div>
              <div>Weakest area: {String(learningAccelerationRetention?.weakest_coverage_area || "insufficient data").replaceAll("_", " ")}</div>
              <div>Focus: {String(learningAccelerationRetention?.recommended_evidence_collection_focus || "collect more evidence").replaceAll("_", " ")}</div>
              <div>Underexplored: {(learningAccelerationRetention?.underexplored_contexts || []).join(", ") || "warming up"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Agreement & Conflict</div>
              <div>Agreement: {String(learningAccelerationRetention?.strongest_cross_system_agreement || "insufficient data").replaceAll("_", " ")}</div>
              <div>Agreeing systems: {(learningAccelerationRetention?.agreeing_systems || []).join(", ") || "none"}</div>
              <div>Disagreement systems: {(learningAccelerationRetention?.disagreement_systems || []).join(", ") || "none"}</div>
              <div>Conflict: {learningAccelerationRetention?.conflict_detected ? "yes" : "no"}</div>
              <div>Resolution: {String(learningAccelerationRetention?.likely_resolution || "no resolution needed").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Meta-Learning Safety</div>
              <div>Most predictive: {String(learningAccelerationRetention?.most_predictive_learning_system || "insufficient data").replaceAll("_", " ")}</div>
              <div>Least predictive: {String(learningAccelerationRetention?.least_predictive_learning_system || "insufficient data").replaceAll("_", " ")}</div>
              <div>Meta confidence: {safeNumber(learningAccelerationRetention?.meta_learning_confidence).toFixed(1)}</div>
              <div>Behavior safe to apply: {learningAccelerationRetention?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Ranking changed: {learningAccelerationRetention?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {learningAccelerationRetention?.paper_execution_behavior_changed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Learning Infrastructure Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is coordinating background learning jobs, prioritizing evidence collection, reducing redundant work, and gathering information in areas where knowledge is limited. This improves learning efficiency without changing trading behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveLearningInfrastructureDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveLearningInfrastructureDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Active workers", safeNumber(adaptiveLearningInfrastructureSuite?.active_worker_count).toFixed(0)],
            ["Learning load", safeNumber(adaptiveLearningInfrastructureSuite?.learning_load_score).toFixed(1)],
            ["Worker efficiency", safeNumber(adaptiveLearningInfrastructureSuite?.worker_efficiency_score).toFixed(1)],
            ["API budget", safeNumber(adaptiveLearningInfrastructureSuite?.api_budget_score).toFixed(1)],
            ["Evidence gap", safeNumber(adaptiveLearningInfrastructureSuite?.evidence_gap_score).toFixed(1)],
            ["Health score", safeNumber(adaptiveLearningInfrastructureSuite?.health_score).toFixed(1)],
            ["Strongest coverage", adaptiveLearningInfrastructureSuite?.strongest_coverage_area],
            ["Weakest coverage", adaptiveLearningInfrastructureSuite?.weakest_coverage_area],
            ["Recommended focus", adaptiveLearningInfrastructureSuite?.recommended_focus],
            ["Orchestration", adaptiveLearningInfrastructureSuite?.orchestration_health],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(adaptiveLearningInfrastructureSuite?.shadow_recommendation || "Preparing background learning infrastructure.").replaceAll("_", " ")}
          </div>
        </div>
        {showAdaptiveLearningInfrastructureDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Background Workers</div>
              {(adaptiveLearningInfrastructureSuite?.active_workers || []).slice(0, 4).map((worker) => (
                <div key={worker?.worker_type || worker?.status}>
                  {String(worker?.worker_type || "worker").replaceAll("_", " ")}: {String(worker?.status || "warming up").replaceAll("_", " ")}
                </div>
              ))}
              <div>Completed jobs: {safeNumber(adaptiveLearningInfrastructureSuite?.completed_jobs).toFixed(0)}</div>
              <div>Failed jobs: {safeNumber(adaptiveLearningInfrastructureSuite?.failed_jobs).toFixed(0)}</div>
              <div>Dashboard blocking: {adaptiveLearningInfrastructureSuite?.dashboard_request_blocking ? "yes" : "no"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Orchestrator & Queue</div>
              <div>Highest priority: {String(adaptiveLearningInfrastructureSuite?.highest_priority_task || "warming up").replaceAll("_", " ")}</div>
              <div>Lowest priority: {String(adaptiveLearningInfrastructureSuite?.lowest_priority_task || "warming up").replaceAll("_", " ")}</div>
              <div>Queue depth: {safeNumber(adaptiveLearningInfrastructureSuite?.worker_queue_depth).toFixed(0)}</div>
              <div>Total tasks: {safeNumber(adaptiveLearningInfrastructureSuite?.total_tasks).toFixed(0)}</div>
              <div>Stale tasks: {safeNumber(adaptiveLearningInfrastructureSuite?.stale_task_count).toFixed(0)}</div>
              <div>Retries: {safeNumber(adaptiveLearningInfrastructureSuite?.retry_count).toFixed(0)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Evidence Collection</div>
              <div>Target area: {String(adaptiveLearningInfrastructureSuite?.targeted_learning_area || "warming up").replaceAll("_", " ")}</div>
              <div>Focus: {String(adaptiveLearningInfrastructureSuite?.evidence_collection_focus || "collect more evidence").replaceAll("_", " ")}</div>
              <div>Collected evidence: {safeNumber(adaptiveLearningInfrastructureSuite?.collected_evidence_count).toFixed(0)}</div>
              <div>Underexplored: {(adaptiveLearningInfrastructureSuite?.underexplored_contexts || []).join(", ") || "warming up"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Budget & Safety</div>
              <div>Highest value source: {String(adaptiveLearningInfrastructureSuite?.highest_value_source || "local cached learning").replaceAll("_", " ")}</div>
              <div>Lowest value source: {String(adaptiveLearningInfrastructureSuite?.lowest_value_source || "none").replaceAll("_", " ")}</div>
              <div>Cache utilization: {safeNumber(adaptiveLearningInfrastructureSuite?.cache_utilization).toFixed(1)}%</div>
              <div>Worker alerts: {(adaptiveLearningInfrastructureSuite?.worker_alerts || []).join(", ").replaceAll("_", " ") || "none"}</div>
              <div>Behavior safe to apply: {adaptiveLearningInfrastructureSuite?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Paper execution changed: {adaptiveLearningInfrastructureSuite?.paper_execution_behavior_changed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Worker Activation & Orchestration V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is coordinating learning workers that collect premarket, after-hours, open-trade, replay, and coverage-gap evidence in the background. This helps Astra learn faster without changing trading behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveWorkerActivationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveWorkerActivationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Orchestrator status", adaptiveWorkerActivation?.orchestrator_status],
            ["Active workers", safeNumber(adaptiveWorkerActivation?.active_worker_count).toFixed(0)],
            ["Completed jobs", safeNumber(adaptiveWorkerActivation?.completed_jobs).toFixed(0)],
            ["Failed / skipped", `${safeNumber(adaptiveWorkerActivation?.failed_jobs).toFixed(0)} / ${safeNumber(adaptiveWorkerActivation?.skipped_jobs).toFixed(0)}`],
            ["Queue depth", safeNumber(adaptiveWorkerActivation?.queue_depth).toFixed(0)],
            ["API budget score", safeNumber(adaptiveWorkerActivation?.api_budget_score).toFixed(1)],
            ["Cache hit rate", `${safeNumber(adaptiveWorkerActivation?.cache_hit_rate).toFixed(1)}%`],
            ["Premarket worker", adaptiveWorkerActivation?.premarket_worker_status],
            ["Open trade worker", adaptiveWorkerActivation?.open_trade_worker_status],
            ["After-hours worker", adaptiveWorkerActivation?.after_hours_worker_status],
            ["Replay worker", adaptiveWorkerActivation?.replay_worker_status],
            ["Coverage worker", adaptiveWorkerActivation?.coverage_worker_status],
            ["Next focus", adaptiveWorkerActivation?.recommended_next_worker_focus],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(adaptiveWorkerActivation?.shadow_recommendation || "Preparing cached worker activation diagnostics.").replaceAll("_", " ")}
          </div>
        </div>
        {showAdaptiveWorkerActivationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Premarket Worker</div>
              <div>Snapshots: {safeNumber(adaptiveWorkerActivation?.snapshots_collected).toFixed(0)}</div>
              <div>Strongest: {String(adaptiveWorkerActivation?.strongest_premarket_symbol || "warming up")}</div>
              <div>Weakest: {String(adaptiveWorkerActivation?.weakest_premarket_symbol || "warming up")}</div>
              <div>Confidence: {safeNumber(adaptiveWorkerActivation?.premarket_context_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Open Trade Worker</div>
              <div>Active monitored: {safeNumber(adaptiveWorkerActivation?.active_trades_monitored).toFixed(0)}</div>
              <div>Profit decay alerts: {safeNumber(adaptiveWorkerActivation?.profit_decay_alerts).toFixed(0)}</div>
              <div>Strongest open: {String(adaptiveWorkerActivation?.strongest_open_trade || "warming up")}</div>
              <div>Weakest open: {String(adaptiveWorkerActivation?.weakest_open_trade || "warming up")}</div>
              <div>Confidence: {safeNumber(adaptiveWorkerActivation?.open_trade_learning_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>After-Hours Worker</div>
              <div>Snapshots: {safeNumber(adaptiveWorkerActivation?.after_hours_snapshots_collected).toFixed(0)}</div>
              <div>Strongest: {String(adaptiveWorkerActivation?.strongest_after_hours_symbol || "warming up")}</div>
              <div>Gap-fade risk: {String(adaptiveWorkerActivation?.highest_gap_fade_risk_symbol || "warming up")}</div>
              <div>Confidence: {safeNumber(adaptiveWorkerActivation?.after_hours_context_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Replay & Coverage</div>
              <div>Replay jobs: {safeNumber(adaptiveWorkerActivation?.replay_jobs_completed).toFixed(0)}</div>
              <div>Replay value: {safeNumber(adaptiveWorkerActivation?.replay_learning_value).toFixed(1)}</div>
              <div>Replay runtime: {safeNumber(adaptiveWorkerActivation?.replay_runtime_ms).toFixed(1)}ms</div>
              <div>Coverage targets: {(adaptiveWorkerActivation?.targeted_contexts || []).join(", ").replaceAll("_", " ") || "warming up"}</div>
              <div>New evidence: {safeNumber(adaptiveWorkerActivation?.new_evidence_collected).toFixed(0)}</div>
              <div>Weakest remaining: {String(adaptiveWorkerActivation?.weakest_remaining_context || "warming up").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Provider calls: {safeNumber(adaptiveWorkerActivation?.provider_calls_used).toFixed(0)}</div>
              <div>LLM calls: {safeNumber(adaptiveWorkerActivation?.llm_calls_used).toFixed(0)}</div>
              <div>Bounded scans: {adaptiveWorkerActivation?.bounded_scans_only === false ? "no" : "yes"}</div>
              <div>Timeouts: {adaptiveWorkerActivation?.worker_timeouts_enabled === false ? "no" : "yes"}</div>
              <div>Behavior safe to apply: {adaptiveWorkerActivation?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Paper execution changed: {adaptiveWorkerActivation?.paper_execution_behavior_changed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Execution & Exit Intelligence V3</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is finding profitable trades, but some winners are giving back too much profit before exit. This panel studies which trade types should be held longer and which should have profits protected sooner. No trading behavior is changed yet.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveExitV3Details((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveExitV3Details ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Profit capture score", adaptiveExecutionExitV3?.profit_capture_score === null || adaptiveExecutionExitV3?.profit_capture_score === undefined ? "warming up" : safeNumber(adaptiveExecutionExitV3?.profit_capture_score).toFixed(1)],
            ["Avg giveback", adaptiveExecutionExitV3?.avg_giveback === null || adaptiveExecutionExitV3?.avg_giveback === undefined ? "warming up" : `${safeNumber(adaptiveExecutionExitV3?.avg_giveback).toFixed(2)}%`],
            ["Capture ratio", adaptiveExecutionExitV3?.capture_ratio === null || adaptiveExecutionExitV3?.capture_ratio === undefined ? "warming up" : `${(safeNumber(adaptiveExecutionExitV3?.capture_ratio) * 100).toFixed(1)}%`],
            ["Worst giveback", (adaptiveExecutionExitV3?.worst_giveback_symbols || [])[0] || "warming up"],
            ["Best capture", (adaptiveExecutionExitV3?.best_capture_symbols || [])[0] || "warming up"],
            ["Best horizon", adaptiveExecutionExitV3?.most_profitable_horizon],
            ["Weakest horizon", adaptiveExecutionExitV3?.highest_giveback_horizon],
            ["Protect profit score", adaptiveExecutionExitV3?.protect_profit_score === null || adaptiveExecutionExitV3?.protect_profit_score === undefined ? "warming up" : safeNumber(adaptiveExecutionExitV3?.protect_profit_score).toFixed(1)],
            ["Hold longer score", adaptiveExecutionExitV3?.hold_longer_score === null || adaptiveExecutionExitV3?.hold_longer_score === undefined ? "warming up" : safeNumber(adaptiveExecutionExitV3?.hold_longer_score).toFixed(1)],
            ["Continuation probability", adaptiveExecutionExitV3?.continuation_probability === null || adaptiveExecutionExitV3?.continuation_probability === undefined ? "warming up" : `${safeNumber(adaptiveExecutionExitV3?.continuation_probability).toFixed(1)}%`],
            ["Shadow bias", adaptiveExecutionExitV3?.shadow_exit_bias],
            ["Auto apply", adaptiveExecutionExitV3?.auto_apply_allowed ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommendation: {String(adaptiveExecutionExitV3?.shadow_only_recommendation || "Collecting shadow exit evidence.").replaceAll("_", " ")}
          </div>
        </div>
        {showAdaptiveExitV3Details ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Horizon Profitability</div>
              {Object.entries(adaptiveExecutionExitV3?.horizon_profitability || {}).slice(0, 5).map(([horizon, row]) => (
                <div key={horizon} style={{ color: "#b8c7e6", marginBottom: 4 }}>
                  {String(horizon).replaceAll("_", " ")}: trades {safeNumber(row?.trade_count).toFixed(0)} | WR {safeNumber(row?.win_rate).toFixed(1)}% | avg {safeNumber(row?.avg_return).toFixed(2)}% | capture {(safeNumber(row?.capture_ratio) * 100).toFixed(1)}%
                </div>
              ))}
              {Object.keys(adaptiveExecutionExitV3?.horizon_profitability || {}).length === 0 ? (
                <div style={{ color: "#b8c7e6" }}>Horizon evidence is warming up.</div>
              ) : null}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Context Diagnostics</div>
              <div>Strongest exit context: {String(adaptiveExecutionExitV3?.strongest_exit_context || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Weakest exit context: {String(adaptiveExecutionExitV3?.weakest_exit_context || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Biggest giveback context: {String(adaptiveExecutionExitV3?.biggest_giveback_context || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Best retention context: {String(adaptiveExecutionExitV3?.best_profit_retention_context || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Protect sooner: {String(adaptiveExecutionExitV3?.protect_gains_sooner_context || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Hold longer: {String(adaptiveExecutionExitV3?.hold_longer_context || "insufficient_data").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Peak Decay</div>
              <div>Continued after profit: {safeNumber(adaptiveExecutionExitV3?.continued_after_profit_count).toFixed(0)}</div>
              <div>Faded after profit: {safeNumber(adaptiveExecutionExitV3?.faded_after_profit_count).toFixed(0)}</div>
              <div>Reversed after profit: {safeNumber(adaptiveExecutionExitV3?.reversed_after_profit_count).toFixed(0)}</div>
              <div>Avg time to peak: {safeNumber(adaptiveExecutionExitV3?.average_time_to_peak).toFixed(1)} min</div>
              <div>Peak decay risk: {safeNumber(adaptiveExecutionExitV3?.peak_decay_risk).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Shadow Recommendations</div>
              {(adaptiveExecutionExitV3?.shadow_exit_recommendations || []).slice(0, 5).map((row) => (
                <div key={`${row?.symbol}-${row?.recommendation}`} style={{ color: "#b8c7e6", marginBottom: 5 }}>
                  {row?.symbol || "unknown"}: {String(row?.recommendation || "insufficient_evidence").replaceAll("_", " ")} | confidence {safeNumber(row?.confidence).toFixed(1)}
                </div>
              ))}
              <div>Behavior safe to apply: {adaptiveExecutionExitV3?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Forced exits: {adaptiveExecutionExitV3?.forced_exits_enabled ? "enabled" : "disabled"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Market Context Learning Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying what happened before the market opened, after the market closed, and what catalyst may be driving each move. This helps Astra learn whether a trade should behave more like a scalp, day trade, or swing trade. This is shadow-only and does not change trading behavior yet.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowMarketContextLearningDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showMarketContextLearningDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Tracked symbols", safeNumber(marketContextLearning?.tracked_symbols).toFixed(0)],
            ["Premarket profile", marketContextLearning?.strongest_premarket_profile],
            ["Catalyst type", marketContextLearning?.dominant_catalyst_type],
            ["After-hours profile", marketContextLearning?.strongest_after_hours_profile],
            ["Best context horizon", marketContextLearning?.best_context_horizon],
            ["Highest giveback context", marketContextLearning?.highest_giveback_context],
            ["Gap-and-fade risk", marketContextLearning?.gap_and_fade_probability === null || marketContextLearning?.gap_and_fade_probability === undefined ? "warming up" : safeNumber(marketContextLearning?.gap_and_fade_probability).toFixed(1)],
            ["Continuation probability", marketContextLearning?.premarket_continuation_probability === null || marketContextLearning?.premarket_continuation_probability === undefined ? "warming up" : safeNumber(marketContextLearning?.premarket_continuation_probability).toFixed(1)],
            ["Context confidence", safeNumber(marketContextLearning?.context_confidence).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(marketContextLearning?.shadow_context_recommendation || "Collecting premarket, catalyst, and after-hours evidence.").replaceAll("_", " ")}
          </div>
        </div>
        {showMarketContextLearningDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Premarket Intelligence</div>
              <div>Strongest profile: {String(marketContextLearning?.strongest_premarket_profile || "insufficient data").replaceAll("_", " ")}</div>
              <div>Weakest profile: {String(marketContextLearning?.weakest_premarket_profile || "insufficient data").replaceAll("_", " ")}</div>
              <div>Momentum score: {safeNumber(marketContextLearning?.premarket_momentum_score).toFixed(1)}</div>
              <div>Gap risk: {safeNumber(marketContextLearning?.gap_risk_score).toFixed(1)}</div>
              <div>Giveback risk: {safeNumber(marketContextLearning?.premarket_giveback_risk).toFixed(1)}</div>
              {Object.entries(marketContextLearning?.premarket_profile_distribution || {}).slice(0, 5).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Catalyst Intelligence</div>
              <div>Dominant catalyst: {String(marketContextLearning?.dominant_catalyst_type || "insufficient data").replaceAll("_", " ")}</div>
              <div>Strongest catalyst: {String(marketContextLearning?.strongest_catalyst_type || "insufficient data").replaceAll("_", " ")}</div>
              <div>Weakest catalyst: {String(marketContextLearning?.weakest_catalyst_type || "insufficient data").replaceAll("_", " ")}</div>
              {Object.entries(marketContextLearning?.catalyst_type_distribution || {}).slice(0, 6).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>After-Hours Intelligence</div>
              <div>Strongest profile: {String(marketContextLearning?.strongest_after_hours_profile || "insufficient data").replaceAll("_", " ")}</div>
              <div>Highest fade risk: {String(marketContextLearning?.highest_gap_fade_risk_profile || "insufficient data").replaceAll("_", " ")}</div>
              <div>Overnight momentum: {safeNumber(marketContextLearning?.overnight_momentum_score).toFixed(1)}</div>
              <div>Gap-and-run probability: {safeNumber(marketContextLearning?.gap_and_run_probability).toFixed(1)}</div>
              <div>Gap-and-fade probability: {safeNumber(marketContextLearning?.gap_and_fade_probability).toFixed(1)}</div>
              {Object.entries(marketContextLearning?.after_hours_profile_distribution || {}).slice(0, 5).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Context Horizons</div>
              <div>Best context horizon: {String(marketContextLearning?.best_context_horizon || "insufficient data").replaceAll("_", " ")}</div>
              <div>Highest giveback context: {String(marketContextLearning?.highest_giveback_context || "insufficient data").replaceAll("_", " ")}</div>
              {Object.entries(marketContextLearning?.best_horizon_by_catalyst || {}).slice(0, 6).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Behavior safe to apply: {marketContextLearning?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {marketContextLearning?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {marketContextLearning?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {marketContextLearning?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Forced exits: {marketContextLearning?.forced_exits_enabled ? "enabled" : "disabled"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Exit Learning Expansion Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying whether winners should be held, partially protected, or exited sooner based on time of day, trade personality, holding time, and profit decay. This is shadow-only learning and does not change trading behavior yet.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowExitLearningExpansionDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showExitLearningExpansionDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Tracked trades", safeNumber(exitLearningExpansion?.tracked_trades).toFixed(0)],
            ["Best partial variant", exitLearningExpansion?.best_partial_exit_variant],
            ["Partial delta", exitLearningExpansion?.partial_exit_profit_delta === null || exitLearningExpansion?.partial_exit_profit_delta === undefined ? "warming up" : `${safeNumber(exitLearningExpansion?.partial_exit_profit_delta).toFixed(2)}%`],
            ["Best profit window", exitLearningExpansion?.best_profit_window],
            ["Highest giveback window", exitLearningExpansion?.highest_giveback_window],
            ["Dominant personality", exitLearningExpansion?.dominant_trade_personality],
            ["Weakest personality", exitLearningExpansion?.weakest_trade_personality],
            ["Best hold window", exitLearningExpansion?.best_hold_window],
            ["Highest decay milestone", exitLearningExpansion?.highest_decay_milestone],
            ["Protect profit score", exitLearningExpansion?.protect_profit_score === null || exitLearningExpansion?.protect_profit_score === undefined ? "warming up" : safeNumber(exitLearningExpansion?.protect_profit_score).toFixed(1)],
            ["Hold longer score", exitLearningExpansion?.hold_longer_score === null || exitLearningExpansion?.hold_longer_score === undefined ? "warming up" : safeNumber(exitLearningExpansion?.hold_longer_score).toFixed(1)],
            ["Continuation after profit", exitLearningExpansion?.continuation_after_profit_score === null || exitLearningExpansion?.continuation_after_profit_score === undefined ? "warming up" : safeNumber(exitLearningExpansion?.continuation_after_profit_score).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(exitLearningExpansion?.shadow_exit_learning_recommendation || "Collecting partial-exit and decay evidence.").replaceAll("_", " ")}
          </div>
        </div>
        {showExitLearningExpansionDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Partial Exit Learning</div>
              <div>Best variant: {String(exitLearningExpansion?.best_partial_exit_variant || "insufficient data").replaceAll("_", " ")}</div>
              <div>Profit delta: {safeNumber(exitLearningExpansion?.partial_exit_profit_delta).toFixed(2)}%</div>
              <div>Capture improvement: {(safeNumber(exitLearningExpansion?.partial_exit_capture_improvement) * 100).toFixed(1)}%</div>
              <div>Confidence: {safeNumber(exitLearningExpansion?.partial_exit_confidence).toFixed(1)}</div>
              <div>Recommendation: {String(exitLearningExpansion?.partial_exit_recommendation || "shadow review only").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Time-of-Day Learning</div>
              <div>First 15 min: {fmtPct(exitLearningExpansion?.first_15_min_return)}</div>
              <div>First 30 min: {fmtPct(exitLearningExpansion?.first_30_min_return)}</div>
              <div>First 60 min: {fmtPct(exitLearningExpansion?.first_60_min_return)}</div>
              <div>Lunch period: {fmtPct(exitLearningExpansion?.lunch_period_return)}</div>
              <div>Power hour: {fmtPct(exitLearningExpansion?.power_hour_return)}</div>
              <div>Overnight: {fmtPct(exitLearningExpansion?.overnight_return)}</div>
              <div>Exit bias: {String(exitLearningExpansion?.time_of_day_exit_bias || "insufficient data").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Trade Personality</div>
              {Object.entries(exitLearningExpansion?.trade_personality_distribution || {}).slice(0, 6).map(([name, count]) => (
                <div key={name}>{String(name).replaceAll("_", " ")}: {safeNumber(count).toFixed(0)}</div>
              ))}
              {Object.keys(exitLearningExpansion?.trade_personality_distribution || {}).length === 0 ? (
                <div>Personality evidence is warming up.</div>
              ) : null}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Holding-Time Optimization</div>
              <div>Avg profitable hold: {safeNumber(exitLearningExpansion?.avg_profitable_hold_time).toFixed(1)} min</div>
              <div>Median profitable hold: {safeNumber(exitLearningExpansion?.median_profitable_hold_time).toFixed(1)} min</div>
              <div>Optimal window: {String(exitLearningExpansion?.optimal_hold_window || "insufficient data").replaceAll("_", " ")}</div>
              <div>Hold too short: {safeNumber(exitLearningExpansion?.hold_too_short_count).toFixed(0)}</div>
              <div>Hold too long: {safeNumber(exitLearningExpansion?.hold_too_long_count).toFixed(0)}</div>
              <div>Confidence: {safeNumber(exitLearningExpansion?.holding_time_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Profit Decay Curve</div>
              <div>Highest decay milestone: {String(exitLearningExpansion?.highest_decay_milestone || "insufficient data").replaceAll("_", " ")}</div>
              <div>Decay risk: {safeNumber(exitLearningExpansion?.profit_decay_risk).toFixed(1)}</div>
              <div>Milestone bias: {String(exitLearningExpansion?.milestone_exit_bias || "insufficient data").replaceAll("_", " ")}</div>
              {Object.entries(exitLearningExpansion?.milestone_stats || {}).slice(0, 4).map(([name, row]) => (
                <div key={name}>
                  {String(name).replaceAll("_", " ")}: decay {safeNumber(row?.decay_probability).toFixed(1)}% | continuation {safeNumber(row?.continuation_probability).toFixed(1)}%
                </div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Behavior safe to apply: {exitLearningExpansion?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {exitLearningExpansion?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Partial sells: {exitLearningExpansion?.partial_sells_enabled ? "enabled" : "disabled"}</div>
              <div>Forced exits: {exitLearningExpansion?.forced_exits_enabled ? "enabled" : "disabled"}</div>
              <div>Trailing stops: {exitLearningExpansion?.automatic_trailing_stops_enabled ? "enabled" : "disabled"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Replay & Counterfactual Learning V2</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow replay diagnostics comparing actual paper outcomes with virtual entry, exit, and hold alternatives.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowReplayCounterfactualDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showReplayCounterfactualDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Lifecycles", replayCounterfactual?.tracked_lifecycles],
            ["Counterfactuals", replayCounterfactual?.counterfactuals_generated],
            ["Actual avg", replayCounterfactual?.average_actual_return === null || replayCounterfactual?.average_actual_return === undefined ? "warming up" : `${safeNumber(replayCounterfactual?.average_actual_return).toFixed(2)}%`],
            ["Best virtual avg", replayCounterfactual?.average_best_counterfactual_return === null || replayCounterfactual?.average_best_counterfactual_return === undefined ? "warming up" : `${safeNumber(replayCounterfactual?.average_best_counterfactual_return).toFixed(2)}%`],
            ["Missed improvement", replayCounterfactual?.average_counterfactual_improvement === null || replayCounterfactual?.average_counterfactual_improvement === undefined ? "warming up" : `${safeNumber(replayCounterfactual?.average_counterfactual_improvement).toFixed(2)}%`],
            ["Replay score", replayCounterfactual?.replay_learning_score === null || replayCounterfactual?.replay_learning_score === undefined ? "warming up" : safeNumber(replayCounterfactual?.replay_learning_score).toFixed(1)],
            ["Best pattern", replayCounterfactual?.best_counterfactual_pattern],
            ["Recommendation", replayCounterfactual?.replay_learning_recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Most common missed improvement: {String(replayCounterfactual?.most_common_missed_improvement || "insufficient_data").replaceAll("_", " ")}
          </div>
        </div>
        {showReplayCounterfactualDetails ? (
          <div style={{ marginTop: 12, color: "#b8c7e6", fontSize: 12 }}>
            Human review required: {replayCounterfactual?.human_review_required ? "yes" : "no"} | Auto apply: {replayCounterfactual?.auto_apply_allowed ? "yes" : "no"} | API calls: {safeNumber(replayCounterfactual?.api_calls_used).toFixed(0)}
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Decision Optimization & Trade Management Suite V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is simulating exit policies, continuation failure signals, rejection quality, opportunity cost, and confidence truth. This is shadow-only learning and does not change entries, exits, sizing, ranking, broker behavior, or paper execution.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowDecisionOptimizationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showDecisionOptimizationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Evidence", safeNumber(decisionOptimization?.evidence_count).toFixed(0)],
            ["Best exit policy", decisionOptimization?.best_virtual_exit_policy],
            ["Highest improvement", decisionOptimization?.highest_improvement_policy],
            ["Most reliable policy", decisionOptimization?.most_reliable_policy],
            ["Failure probability", `${safeNumber(decisionOptimization?.continuation_failure_probability).toFixed(1)}%`],
            ["Failure signal", decisionOptimization?.strongest_failure_signal],
            ["Continuation quality", safeNumber(decisionOptimization?.continuation_quality_score).toFixed(1)],
            ["Rejection accuracy", `${safeNumber(decisionOptimization?.rejection_accuracy).toFixed(1)}%`],
            ["Missed winner rate", `${safeNumber(decisionOptimization?.missed_winner_rate).toFixed(1)}%`],
            ["Decision quality", safeNumber(decisionOptimization?.decision_quality_score).toFixed(1)],
            ["Confidence truth", safeNumber(decisionOptimization?.confidence_truth_score).toFixed(1)],
            ["Sizing readiness", safeNumber(decisionOptimization?.sizing_readiness_score).toFixed(1)],
            ["Biggest gap", decisionOptimization?.biggest_decision_gap],
            ["Top exit focus", decisionOptimization?.top_exit_learning_focus],
            ["Calibration status", decisionOptimization?.confidence_calibration_status],
            ["Management score", safeNumber(decisionOptimization?.trade_management_intelligence_score).toFixed(1)],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(decisionOptimization?.shadow_recommendation || "Continue decision optimization diagnostics shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showDecisionOptimizationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Adaptive Exit Policy</div>
              <div>Completed lifecycles: {safeNumber(decisionOptimization?.completed_lifecycles_reviewed).toFixed(0)}</div>
              <div>Actual average: {decisionOptimization?.actual_average_result === null || decisionOptimization?.actual_average_result === undefined ? "warming up" : `${safeNumber(decisionOptimization?.actual_average_result).toFixed(2)}%`}</div>
              {Object.entries(decisionOptimization?.virtual_exit_policy_stats || {}).slice(0, 5).map(([policy, stats]) => (
                <div key={policy}>
                  {String(policy).replaceAll("_", " ")}: sim {safeNumber(stats?.average_simulated_result).toFixed(2)}%, delta {safeNumber(stats?.average_improvement_delta).toFixed(2)}%
                </div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Continuation Failure Intelligence</div>
              <div>Weakest signal: {String(decisionOptimization?.weakest_failure_signal || "warming up").replaceAll("_", " ")}</div>
              <div>Lead time: {safeNumber(decisionOptimization?.average_failure_lead_time_minutes).toFixed(1)} min</div>
              {Object.entries(decisionOptimization?.failure_signal_scores || {}).slice(0, 6).map(([signal, score]) => (
                <div key={signal}>{String(signal).replaceAll("_", " ")}: {safeNumber(score).toFixed(1)}</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Opportunity Cost Intelligence</div>
              <div>Rejected reviewed: {safeNumber(decisionOptimization?.rejected_candidates_reviewed).toFixed(0)}</div>
              <div>Avoided loser rate: {safeNumber(decisionOptimization?.avoided_loser_rate).toFixed(1)}%</div>
              <div>Highest opportunity cost: {safeNumber(decisionOptimization?.highest_opportunity_cost).toFixed(2)}%</div>
              <div>Strongest reason: {String(decisionOptimization?.strongest_rejection_reason || "warming up").replaceAll("_", " ")}</div>
              <div>Weakest reason: {String(decisionOptimization?.weakest_rejection_reason || "warming up").replaceAll("_", " ")}</div>
              {(decisionOptimization?.top_missed_opportunities || []).slice(0, 4).map((row) => (
                <div key={`${row?.symbol}-${row?.selected_symbol}`}>{row?.symbol || "unknown"} missed gap {safeNumber(row?.opportunity_cost_pct).toFixed(2)}%</div>
              ))}
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Confidence Truth Expansion</div>
              <div>Best bucket: {String(decisionOptimization?.best_confidence_bucket || "warming up").replaceAll("_", " ")}</div>
              <div>Worst bucket: {String(decisionOptimization?.worst_confidence_bucket || "warming up").replaceAll("_", " ")}</div>
              <div>Predictive power: {safeNumber(decisionOptimization?.predictive_power).toFixed(1)}</div>
              <div>Monotonicity: {safeNumber(decisionOptimization?.confidence_monotonicity).toFixed(1)}</div>
              <div>Higher confidence better: {decisionOptimization?.higher_confidence_produces_better_outcomes ? "yes" : "not proven"}</div>
              <div>Future confidence sizing justified: {decisionOptimization?.confidence_weighted_sizing_may_eventually_be_justified ? "shadow maybe" : "no"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Behavior safe to apply: {decisionOptimization?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {decisionOptimization?.auto_apply_allowed ? "yes" : "no"}</div>
              <div>Ranking changed: {decisionOptimization?.ranking_behavior_changed ? "yes" : "no"}</div>
              <div>Paper execution changed: {decisionOptimization?.paper_execution_behavior_changed ? "yes" : "no"}</div>
              <div>Position sizing changed: {decisionOptimization?.position_sizing_changed ? "yes" : "no"}</div>
              <div>Thresholds changed: {decisionOptimization?.thresholds_changed ? "yes" : "no"}</div>
              <div>Forced exits: {decisionOptimization?.forced_exits_enabled ? "enabled" : "disabled"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Opportunity Cost Learning</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow comparison of selected paper trades versus rejected or non-selected candidates.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowOpportunityCostDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showOpportunityCostDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Selected reviewed", opportunityCostLearning?.selected_candidates_reviewed],
            ["Rejected reviewed", opportunityCostLearning?.rejected_candidates_reviewed],
            ["Avg opportunity cost", opportunityCostLearning?.average_opportunity_cost === null || opportunityCostLearning?.average_opportunity_cost === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.average_opportunity_cost).toFixed(2)}%`],
            ["Missed count", opportunityCostLearning?.missed_opportunity_count],
            ["Correct count", opportunityCostLearning?.correct_selection_count],
            ["Selection quality", opportunityCostLearning?.selection_quality_score === null || opportunityCostLearning?.selection_quality_score === undefined ? "warming up" : safeNumber(opportunityCostLearning?.selection_quality_score).toFixed(1)],
            ["Missed best", opportunityCostLearning?.missed_best_symbol],
            ["Recommendation", opportunityCostLearning?.ranking_improvement_recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
        </div>
        {showOpportunityCostDetails ? (
          <div style={{ marginTop: 12, color: "#b8c7e6", fontSize: 12, display: "grid", gap: 6 }}>
            <div>Best selected: {String(opportunityCostLearning?.best_selected_symbol || "insufficient_data").replaceAll("_", " ")} | Worst selected: {String(opportunityCostLearning?.worst_selected_symbol || "insufficient_data").replaceAll("_", " ")} | Best rejected: {String(opportunityCostLearning?.best_rejected_symbol || "insufficient_data").replaceAll("_", " ")}</div>
            <div>Avg selected return: {opportunityCostLearning?.avg_selected_return === null || opportunityCostLearning?.avg_selected_return === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.avg_selected_return).toFixed(2)}%`} | Avg rejected return: {opportunityCostLearning?.avg_rejected_return === null || opportunityCostLearning?.avg_rejected_return === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.avg_rejected_return).toFixed(2)}%`} | Median cost: {opportunityCostLearning?.median_opportunity_cost === null || opportunityCostLearning?.median_opportunity_cost === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.median_opportunity_cost).toFixed(2)}%`}</div>
            <div>Largest positive gap: {opportunityCostLearning?.largest_positive_gap === null || opportunityCostLearning?.largest_positive_gap === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.largest_positive_gap).toFixed(2)}%`} ({String(opportunityCostLearning?.largest_positive_gap_symbol || "n/a")}) | Largest negative gap: {opportunityCostLearning?.largest_negative_gap === null || opportunityCostLearning?.largest_negative_gap === undefined ? "warming up" : `${safeNumber(opportunityCostLearning?.largest_negative_gap).toFixed(2)}%`} ({String(opportunityCostLearning?.largest_negative_gap_symbol || "n/a")})</div>
            <div>Outliers: {(opportunityCostLearning?.outlier_symbols || []).length ? opportunityCostLearning.outlier_symbols.join(", ") : "none detected"}.</div>
            <div style={{ color: "#9fb1cc" }}>Formula: {String(opportunityCostLearning?.calculation_method || "opportunity cost = rejected return - selected return")}</div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Learning Issue Audit</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Reconciles confusing Learning Tab readings and separates real weaknesses from display or calculation ambiguity.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowLearningIssueAuditDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showLearningIssueAuditDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Likely cause", learningIssueAudit?.likely_cause_summary],
            ["Opportunity cost", learningIssueAudit?.issue_status?.opportunity_cost?.issue_status],
            ["Execution audit", learningIssueAudit?.issue_status?.execution_participation?.issue_status],
            ["Profit capture", learningIssueAudit?.issue_status?.profit_capture?.issue_status],
            ["Follow-through", learningIssueAudit?.issue_status?.follow_through_continuation?.issue_status],
            ["Buy purity", learningIssueAudit?.issue_status?.buy_purity?.issue_status],
            ["Exit quality", learningIssueAudit?.issue_status?.exit_quality?.issue_status],
            ["Behavior safe to change", learningIssueAudit?.safe_to_change_behavior ? "yes" : "no"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(learningIssueAudit?.recommended_action || "Collecting issue evidence.")}
          </div>
        </div>
        {showLearningIssueAuditDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Metric Source</div>
              <div>Selected: {String(performanceSummary?.selected_metric_source || learningIssueAudit?.core_metric_source_diagnostics?.selected_metric_source || "unknown").replaceAll("_", " ")}</div>
              <div>Legacy fallback: {(performanceSummary?.legacy_fallback_used ?? learningIssueAudit?.core_metric_source_diagnostics?.legacy_fallback_used) ? "yes" : "no"}</div>
              <div>Reason: {String(performanceSummary?.source_selection_reason || learningIssueAudit?.core_metric_source_diagnostics?.source_selection_reason || "collecting").replaceAll("_", " ")}</div>
              <div>Advanced sample: {safeNumber(performanceSummary?.advanced_learning_sample_size ?? learningIssueAudit?.dataset_scope_diagnostics?.advanced_learning_sample_size).toFixed(0)} | Replay sample: {safeNumber(performanceSummary?.replay_sample_size ?? learningIssueAudit?.dataset_scope_diagnostics?.replay_sample_size).toFixed(0)}</div>
              <div>Scope mismatch: {(performanceSummary?.dataset_scope_mismatch_detected ?? learningIssueAudit?.dataset_scope_diagnostics?.dataset_scope_mismatch_detected) ? "yes" : "no"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Opportunity Cost</div>
              <div>Avg selected: {learningIssueAudit?.opportunity_cost_diagnostics?.avg_selected_return === null || learningIssueAudit?.opportunity_cost_diagnostics?.avg_selected_return === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.opportunity_cost_diagnostics?.avg_selected_return).toFixed(2)}%`}</div>
              <div>Avg rejected: {learningIssueAudit?.opportunity_cost_diagnostics?.avg_rejected_return === null || learningIssueAudit?.opportunity_cost_diagnostics?.avg_rejected_return === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.opportunity_cost_diagnostics?.avg_rejected_return).toFixed(2)}%`}</div>
              <div>Median cost: {learningIssueAudit?.opportunity_cost_diagnostics?.median_opportunity_cost === null || learningIssueAudit?.opportunity_cost_diagnostics?.median_opportunity_cost === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.opportunity_cost_diagnostics?.median_opportunity_cost).toFixed(2)}%`}</div>
              <div>Outliers: {(learningIssueAudit?.opportunity_cost_diagnostics?.outlier_symbols || []).join(", ") || "none"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Execution Blocks</div>
              <div>Unique reviewed: {safeNumber(learningIssueAudit?.execution_participation_diagnostics?.unique_candidates_reviewed).toFixed(0)}</div>
              <div>Duplicate symbol blocks: {safeNumber(learningIssueAudit?.execution_participation_diagnostics?.duplicate_symbol_blocks).toFixed(0)}</div>
              <div>Active-position blocks: {safeNumber(learningIssueAudit?.execution_participation_diagnostics?.active_position_blocks).toFixed(0)}</div>
              <div>Confirmation required: {safeNumber(learningIssueAudit?.execution_participation_diagnostics?.confirmation_required_blocks).toFixed(0)}</div>
              <div>Unique submission rate: {safeNumber(learningIssueAudit?.execution_participation_diagnostics?.submission_rate_unique_candidates).toFixed(1)}%</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Profit / Continuation</div>
              <div>Avg peak gain: {learningIssueAudit?.profit_capture_diagnostics?.avg_peak_gain === null || learningIssueAudit?.profit_capture_diagnostics?.avg_peak_gain === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.profit_capture_diagnostics?.avg_peak_gain).toFixed(2)}%`}</div>
              <div>Avg current/exit gain: {learningIssueAudit?.profit_capture_diagnostics?.avg_current_or_exit_gain === null || learningIssueAudit?.profit_capture_diagnostics?.avg_current_or_exit_gain === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.profit_capture_diagnostics?.avg_current_or_exit_gain).toFixed(2)}%`}</div>
              <div>Avg giveback: {learningIssueAudit?.profit_capture_diagnostics?.avg_giveback === null || learningIssueAudit?.profit_capture_diagnostics?.avg_giveback === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.profit_capture_diagnostics?.avg_giveback).toFixed(2)}%`}</div>
              <div>Capture ratio: {learningIssueAudit?.profit_capture_diagnostics?.capture_ratio === null || learningIssueAudit?.profit_capture_diagnostics?.capture_ratio === undefined ? "warming up" : `${(safeNumber(learningIssueAudit?.profit_capture_diagnostics?.capture_ratio) * 100).toFixed(1)}%`}</div>
              <div>Continued: {safeNumber(learningIssueAudit?.follow_through_diagnostics?.continued_as_expected_count).toFixed(0)} | Stalled: {safeNumber(learningIssueAudit?.follow_through_diagnostics?.stalled_count).toFixed(0)} | Reversed: {safeNumber(learningIssueAudit?.follow_through_diagnostics?.reversed_count).toFixed(0)}</div>
              <div>Worst giveback: {(learningIssueAudit?.profit_capture_diagnostics?.worst_giveback_symbols || []).join(", ") || "none"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Replay Scope</div>
              <div>Replay scope: {String(learningIssueAudit?.replay_conflict_diagnostics?.replay_scope_label || replayCounterfactual?.replay_scope_label || "unknown").replaceAll("_", " ")}</div>
              <div>Actual avg: {learningIssueAudit?.replay_conflict_diagnostics?.average_actual_return === null || learningIssueAudit?.replay_conflict_diagnostics?.average_actual_return === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.replay_conflict_diagnostics?.average_actual_return).toFixed(2)}%`}</div>
              <div>Best virtual: {learningIssueAudit?.replay_conflict_diagnostics?.average_best_counterfactual_return === null || learningIssueAudit?.replay_conflict_diagnostics?.average_best_counterfactual_return === undefined ? "warming up" : `${safeNumber(learningIssueAudit?.replay_conflict_diagnostics?.average_best_counterfactual_return).toFixed(2)}%`}</div>
              <div>Open included: {learningIssueAudit?.replay_conflict_diagnostics?.replay_open_included ? "yes" : "no"} | Closed only: {learningIssueAudit?.replay_conflict_diagnostics?.replay_closed_only ? "yes" : "no"}</div>
              <div>Negative drivers: {Object.entries(learningIssueAudit?.replay_conflict_diagnostics?.replay_negative_return_drivers || {}).slice(0, 3).map(([k, v]) => `${k} (${v})`).join(", ") || "none"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Display Mapping</div>
              <div>Buy purity cause: {String(learningIssueAudit?.issue_status?.buy_purity?.likely_cause || "warming_up").replaceAll("_", " ")}</div>
              <div>Exit quality cause: {String(learningIssueAudit?.issue_status?.exit_quality?.likely_cause || "warming_up").replaceAll("_", " ")}</div>
              <div>Exit source: {String(learningIssueAudit?.exit_quality_diagnostics?.exit_quality_source || "unknown").replaceAll("_", " ")}</div>
              <div>Exit scope: {String(learningIssueAudit?.exit_quality_diagnostics?.exit_quality_scope_label || "unknown").replaceAll("_", " ")}</div>
              <div>Exit confidence: {safeNumber(learningIssueAudit?.exit_quality_diagnostics?.exit_quality_confidence).toFixed(1)}</div>
              <div>Shadow only: {String(learningIssueAudit?.shadow_only_recommendation || "no behavior change")}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Advanced Learning Intelligence</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Metric reconciliation, trade-memory similarity, knowledge graph links, and evidence-backed explanations.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdvancedLearningIntelligenceDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdvancedLearningIntelligenceDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Metric confidence", safeNumber(advancedLearningIntelligence?.metric_confidence_score).toFixed(1)],
            ["Evidence consistency", safeNumber(advancedLearningIntelligence?.evidence_consistency_score).toFixed(1)],
            ["Memory quality", safeNumber(advancedLearningIntelligence?.memory_quality_score).toFixed(1)],
            ["Graph maturity", advancedLearningIntelligence?.graph_maturity],
            ["Explanation quality", safeNumber(advancedLearningIntelligence?.explanation_quality_score).toFixed(1)],
            ["Similar trades", advancedLearningIntelligence?.similar_trade_count],
            ["Strongest connection", advancedLearningIntelligence?.strongest_learning_connection],
            ["Recommendation", advancedLearningIntelligence?.recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(advancedLearningIntelligence?.reconciliation_summary || "Waiting for metric reconciliation evidence.")}
          </div>
        </div>
        {showAdvancedLearningIntelligenceDetails ? (
          <div style={{ marginTop: 12, color: "#b8c7e6", fontSize: 12, display: "grid", gap: 8 }}>
            <div>
              Core metrics: WR {advancedLearningIntelligence?.win_rate === null || advancedLearningIntelligence?.win_rate === undefined ? "warming up" : `${safeNumber(advancedLearningIntelligence?.win_rate).toFixed(1)}%`} | PF {advancedLearningIntelligence?.profit_factor === null || advancedLearningIntelligence?.profit_factor === undefined ? "warming up" : safeNumber(advancedLearningIntelligence?.profit_factor).toFixed(2)} | Avg return {advancedLearningIntelligence?.average_return === null || advancedLearningIntelligence?.average_return === undefined ? "warming up" : `${safeNumber(advancedLearningIntelligence?.average_return).toFixed(2)}%`}
            </div>
            <div>
              Weakest connection: {String(advancedLearningIntelligence?.weakest_learning_connection || "insufficient_data").replaceAll("_", " ")}
            </div>
            <div>
              Graph insights: {(advancedLearningIntelligence?.graph_insights || []).length ? advancedLearningIntelligence.graph_insights.join(" ") : "Waiting for graph insight evidence."}
            </div>
            <div>
              Explanation template: {String(advancedLearningIntelligence?.candidate_explanation_template || "Waiting for evidence-backed explanations.")}
            </div>
            <div>
              Human review required: {advancedLearningIntelligence?.human_review_required ? "yes" : "no"} | Auto apply: {advancedLearningIntelligence?.auto_apply_allowed ? "yes" : "no"} | API calls: {safeNumber(advancedLearningIntelligence?.api_calls_used).toFixed(0)}
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Blind Spot Detection</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow-only review of missed contexts, opportunity-cost blind spots, and selection bias.
            </div>
          </div>
          <button type="button" onClick={() => setShowBlindSpotDetails((v) => !v)} style={{
            background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
            color: "#dce7ff",
            border: "1px solid #496a97",
            borderRadius: "6px",
            fontSize: "0.72rem",
            padding: "0.25rem 0.55rem",
            cursor: "pointer",
          }}>
            {showBlindSpotDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Blind spot score", safeNumber(blindSpotDetection?.blind_spot_score).toFixed(1)],
            ["Missed opportunities", blindSpotDetection?.missed_opportunity_count],
            ["Strongest blind spot", blindSpotDetection?.strongest_blind_spot],
            ["Cap tier bias", blindSpotDetection?.cap_tier_bias],
            ["Horizon bias", blindSpotDetection?.horizon_bias],
            ["Recommendation", blindSpotDetection?.recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
        </div>
        {showBlindSpotDetails ? (
          <div style={{ marginTop: 12, color: "#b8c7e6", fontSize: 12, display: "grid", gap: 6 }}>
            <div>Top missed symbols: {(blindSpotDetection?.top_missed_symbols || []).length ? blindSpotDetection.top_missed_symbols.join(", ") : "warming up"}</div>
            <div>Underselected sectors: {(blindSpotDetection?.underselected_sectors || []).length ? blindSpotDetection.underselected_sectors.join(", ") : "none detected"}</div>
            <div>Overselected sectors: {(blindSpotDetection?.overselected_sectors || []).length ? blindSpotDetection.overselected_sectors.join(", ") : "none detected"}</div>
            <div>Underselected archetypes: {(blindSpotDetection?.underselected_archetypes || []).length ? blindSpotDetection.underselected_archetypes.join(", ") : "none detected"}</div>
            <div>Human review required: {blindSpotDetection?.human_review_required ? "yes" : "no"} | Auto apply: {blindSpotDetection?.auto_apply_allowed ? "yes" : "no"}</div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Remote Runtime Consistency & Paper Capacity</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Checks whether the mirrored UI is looking at fresh unified diagnostics and shows the current bounded paper-learning capacity.
            </div>
          </div>
          <button type="button" onClick={() => setShowRemoteRuntimeDetails((v) => !v)} style={{
            background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
            color: "#dce7ff",
            border: "1px solid #496a97",
            borderRadius: "6px",
            fontSize: "0.72rem",
            padding: "0.25rem 0.55rem",
            cursor: "pointer",
          }}>
            {showRemoteRuntimeDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Backend", remoteRuntimeConsistency?.local_backend_ok ? "ok" : "review"],
            ["Frontend", remoteRuntimeConsistency?.frontend_ok ? "ok" : "review"],
            ["Remote status", remoteRuntimeConsistency?.remote_consistency_status],
            ["UI stale", remoteRuntimeConsistency?.stale_ui_detected ? "yes" : "no"],
            ["Stock capacity", capacityExpansionStatus?.current_stock_capacity_limit],
            ["Total capacity", capacityExpansionStatus?.current_total_capacity_limit],
            ["Capacity mode", capacityExpansionStatus?.paper_learning_capacity_expansion_active ? "expanded paper learning" : "baseline"],
            ["Action", remoteRuntimeConsistency?.recommended_action],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>{typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}</div>
            </div>
          ))}
        </div>
        {showRemoteRuntimeDetails ? (
          <div style={{ marginTop: 12, color: "#b8c7e6", fontSize: 12, display: "grid", gap: 6 }}>
            <div>Backend URL: {String(remoteRuntimeConsistency?.backend_url || "http://127.0.0.1:8000")}</div>
            <div>Frontend URL: {String(remoteRuntimeConsistency?.frontend_url || "http://127.0.0.1:5173")}</div>
            <div>Unified timestamp: {String(remoteRuntimeConsistency?.unified_timestamp || "warming up")} | Cache age: {safeNumber(remoteRuntimeConsistency?.cache_age_seconds).toFixed(1)}s</div>
            <div>Initial endpoint count: {safeNumber(remoteRuntimeConsistency?.learning_tab_endpoint_count, 1).toFixed(0)} | Advanced metrics visible: {remoteRuntimeConsistency?.advanced_learning_metrics_visible ? "yes" : "no"}</div>
            <div>Suggested horizon mix: scalp {safeNumber((capacityExpansionStatus?.suggested_horizon_mix || {}).scalp).toFixed(0)}, day trade {safeNumber((capacityExpansionStatus?.suggested_horizon_mix || {}).day_trade).toFixed(0)}, swing/short-swing max {safeNumber((capacityExpansionStatus?.suggested_horizon_mix || {}).swing_short_swing_max).toFixed(0)}</div>
            <div>Safety: market-session gate {capacityExpansionStatus?.market_session_gate_preserved ? "preserved" : "review"}, duplicate symbol block {capacityExpansionStatus?.duplicate_active_symbol_block_preserved ? "preserved" : "review"}, broker safeguards {capacityExpansionStatus?.broker_safeguards_preserved ? "preserved" : "review"}</div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Trade Archetype & Market Regime Intelligence</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Paper-only archetype/regime learning matrix for understanding which trade types fit which market environments.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowTradeArchetypeRegimeDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showTradeArchetypeRegimeDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Tracked trades", tradeArchetypeRegime?.tracked_trades],
            ["Best archetype", tradeArchetypeRegime?.best_archetype],
            ["Weakest archetype", tradeArchetypeRegime?.weakest_archetype],
            ["Current regime", tradeArchetypeRegime?.current_regime],
            ["Best regime", tradeArchetypeRegime?.best_regime],
            ["Weakest regime", tradeArchetypeRegime?.weakest_regime],
            ["Supported archetype", tradeArchetypeRegime?.current_best_supported_archetype],
            ["Alignment", tradeArchetypeRegime?.current_archetype_regime_alignment_score === null || tradeArchetypeRegime?.current_archetype_regime_alignment_score === undefined ? "warming up" : safeNumber(tradeArchetypeRegime?.current_archetype_regime_alignment_score).toFixed(1)],
            ["Recommendation", tradeArchetypeRegime?.shadow_recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Best pair: {String(tradeArchetypeRegime?.best_archetype_regime_pair || "insufficient_data").replaceAll("_", " ").replace("|", " in ")} | Weakest pair: {String(tradeArchetypeRegime?.weakest_archetype_regime_pair || "insufficient_data").replaceAll("_", " ").replace("|", " in ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(tradeArchetypeRegime?.summary || "Trade archetype and regime diagnostics are collecting lifecycle evidence.")}
          </div>
        </div>
        {showTradeArchetypeRegimeDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Archetype Distribution</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(tradeArchetypeRegime?.archetype_distribution || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Regime Distribution</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(tradeArchetypeRegime?.regime_distribution || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Shadow Review</div>
              <div>Most consistent: {String(tradeArchetypeRegime?.most_consistent_archetype || "insufficient_data").replaceAll("_", " ")}</div>
              <div>High giveback: {String(tradeArchetypeRegime?.highest_giveback_archetype || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Best follow-through: {String(tradeArchetypeRegime?.best_follow_through_archetype || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Worst follow-through: {String(tradeArchetypeRegime?.worst_follow_through_archetype || "insufficient_data").replaceAll("_", " ")}</div>
              <div>Human review: {tradeArchetypeRegime?.human_review_required ? "yes" : "no"}</div>
              <div>Auto apply: {tradeArchetypeRegime?.auto_apply_allowed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Profit Capture Intelligence</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Watch-only profit-retention, giveback, and peak-decay diagnostics from paper lifecycle evidence.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveProfitCaptureDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveProfitCaptureDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Capture ratio", adaptiveProfitCapture?.average_profit_capture_ratio === null || adaptiveProfitCapture?.average_profit_capture_ratio === undefined ? "warming up" : `${(safeNumber(adaptiveProfitCapture?.average_profit_capture_ratio) * 100).toFixed(1)}%`],
            ["Avg giveback", adaptiveProfitCapture?.average_profit_giveback_pct === null || adaptiveProfitCapture?.average_profit_giveback_pct === undefined ? "warming up" : `${safeNumber(adaptiveProfitCapture?.average_profit_giveback_pct).toFixed(2)}%`],
            ["Missed profit", adaptiveProfitCapture?.average_missed_profit_pct === null || adaptiveProfitCapture?.average_missed_profit_pct === undefined ? "warming up" : `${safeNumber(adaptiveProfitCapture?.average_missed_profit_pct).toFixed(2)}%`],
            ["Retention score", adaptiveProfitCapture?.average_profit_retention_score === null || adaptiveProfitCapture?.average_profit_retention_score === undefined ? "warming up" : safeNumber(adaptiveProfitCapture?.average_profit_retention_score).toFixed(1)],
            ["Capture quality", adaptiveProfitCapture?.profit_capture_quality_score === null || adaptiveProfitCapture?.profit_capture_quality_score === undefined ? "warming up" : safeNumber(adaptiveProfitCapture?.profit_capture_quality_score).toFixed(1)],
            ["High giveback", adaptiveProfitCapture?.high_giveback_trade_count],
            ["Worst giveback", adaptiveProfitCapture?.worst_giveback_symbol],
            ["Watchlist", adaptiveProfitCapture?.open_position_watchlist_count],
            ["Recommendation", adaptiveProfitCapture?.profit_capture_recommendation],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Contexts: best {String(adaptiveProfitCapture?.best_profit_capture_context || "insufficient_data").replaceAll("_", " ")} | weakest {String(adaptiveProfitCapture?.weakest_profit_capture_context || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(adaptiveProfitCapture?.profit_capture_reason || adaptiveProfitCapture?.summary || "Adaptive profit capture diagnostics are collecting lifecycle evidence.")}
          </div>
        </div>
        {showAdaptiveProfitCaptureDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Giveback Patterns</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(adaptiveProfitCapture?.top_giveback_patterns || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Capture Labels</div>
              <div>Excellent: {safeNumber(adaptiveProfitCapture?.excellent_capture_count).toFixed(0)}</div>
              <div>Weak: {safeNumber(adaptiveProfitCapture?.weak_capture_count).toFixed(0)}</div>
              <div>Severe giveback: {safeNumber(adaptiveProfitCapture?.severe_giveback_count).toFixed(0)}</div>
              <div>Human review: {adaptiveProfitCapture?.human_review_required ? "yes" : "no"}</div>
              <div>Auto apply: {adaptiveProfitCapture?.auto_apply_allowed ? "yes" : "no"}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Open Watchlist</div>
              {(adaptiveProfitCapture?.open_position_watchlist || []).slice(0, 5).map((row) => (
                <div key={row?.symbol || JSON.stringify(row)} style={{ color: "#b8c7e6", marginBottom: 4 }}>
                  {row?.symbol || "unknown"}: {String(row?.giveback_severity_label || "watch").replaceAll("_", " ")} | attention {safeNumber(row?.profit_protection_attention_score).toFixed(1)}
                </div>
              ))}
              {(!adaptiveProfitCapture?.open_position_watchlist || adaptiveProfitCapture.open_position_watchlist.length === 0) ? (
                <div style={{ color: "#b8c7e6" }}>No active profit-capture watch items.</div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Virtual-to-Paper Convergence & Symbol Attribution V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is comparing actual paper results against virtual and replay alternatives, then explaining why the paper result did not match the best virtual outcome. It links those gaps to symbol behavior, horizon, catalyst, regime, exit style, and profitability drivers. This does not change trading behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowVirtualPaperConvergenceDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showVirtualPaperConvergenceDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Actual return", virtualPaperConvergence?.average_actual_return === null || virtualPaperConvergence?.average_actual_return === undefined ? "warming up" : `${safeNumber(virtualPaperConvergence?.average_actual_return).toFixed(2)}%`],
            ["Virtual return", virtualPaperConvergence?.average_virtual_return === null || virtualPaperConvergence?.average_virtual_return === undefined ? "warming up" : `${safeNumber(virtualPaperConvergence?.average_virtual_return).toFixed(2)}%`],
            ["Convergence gap", virtualPaperConvergence?.average_convergence_gap === null || virtualPaperConvergence?.average_convergence_gap === undefined ? "warming up" : `${safeNumber(virtualPaperConvergence?.average_convergence_gap).toFixed(2)}%`],
            ["Virtual outperformance", `${safeNumber(virtualPaperConvergence?.virtual_outperformance_rate).toFixed(1)}%`],
            ["Dominant gap cause", virtualPaperConvergence?.dominant_gap_cause],
            ["Gap to reduce", virtualPaperConvergence?.highest_value_gap_to_reduce],
            ["Largest gap symbol", virtualPaperConvergence?.largest_convergence_gap_symbol],
            ["Strongest symbol edge", virtualPaperConvergence?.strongest_symbol_behavior_edge],
            ["Weakest symbol edge", virtualPaperConvergence?.weakest_symbol_behavior_edge],
            ["Most reliable symbol", virtualPaperConvergence?.most_reliable_symbol],
            ["Best symbol / horizon", virtualPaperConvergence?.best_symbol_horizon_pair],
            ["Worst symbol / horizon", virtualPaperConvergence?.worst_symbol_horizon_pair],
            ["Best exit style", Object.entries(virtualPaperConvergence?.best_exit_style_by_symbol || {}).slice(0, 1).map(([k, v]) => `${k} -> ${String(v).replaceAll("_", " ")}`).join(", ") || "warming up"],
            ["Profit lock symbols", (virtualPaperConvergence?.symbols_needing_profit_lock || []).join(", ") || "none"],
            ["Continuation-exit symbols", (virtualPaperConvergence?.symbols_needing_continuation_exit || []).join(", ") || "none"],
            ["Missed profit driver", virtualPaperConvergence?.top_missed_profit_driver],
            ["Profitability lever", virtualPaperConvergence?.highest_value_profitability_lever],
            ["Strongest virtual policy", virtualPaperConvergence?.strongest_virtual_policy],
            ["Closest policy review", virtualPaperConvergence?.closest_policy_to_future_review],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(virtualPaperConvergence?.shadow_recommendation || "Continue virtual-to-paper convergence learning shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showVirtualPaperConvergenceDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Symbol Horizon Fit</div>
              <div>Best by symbol: {JSON.stringify(virtualPaperConvergence?.best_horizon_by_symbol || {})}</div>
              <div>Worst by symbol: {JSON.stringify(virtualPaperConvergence?.worst_horizon_by_symbol || {})}</div>
              <div>Horizon gap score: {safeNumber(virtualPaperConvergence?.horizon_gap_score).toFixed(1)}</div>
              <div>Horizon confidence: {safeNumber(virtualPaperConvergence?.horizon_fit_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Regime & Catalyst Fit</div>
              <div>Best regime: {JSON.stringify(virtualPaperConvergence?.best_regime_by_symbol || {})}</div>
              <div>Best catalyst: {JSON.stringify(virtualPaperConvergence?.best_catalyst_by_symbol || {})}</div>
              <div>Catalyst fit: {safeNumber(virtualPaperConvergence?.catalyst_symbol_fit_score).toFixed(1)}</div>
              <div>Regime fit: {safeNumber(virtualPaperConvergence?.regime_symbol_fit_score).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Policy Attribution Safety</div>
              <div>Policy confidence: {safeNumber(virtualPaperConvergence?.policy_improvement_confidence).toFixed(1)}</div>
              <div>Attribution score: {safeNumber(virtualPaperConvergence?.policy_attribution_score).toFixed(1)}</div>
              <div>API calls: {safeNumber(virtualPaperConvergence?.api_calls_used).toFixed(0)} | Provider calls: {safeNumber(virtualPaperConvergence?.provider_calls_used).toFixed(0)} | LLM calls: {safeNumber(virtualPaperConvergence?.llm_calls_used).toFixed(0)}</div>
              <div>Behavior safe to apply: {virtualPaperConvergence?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Auto apply: {virtualPaperConvergence?.auto_apply_allowed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Profit Capture, Peak Decay & Exit Validation V1</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Astra is studying how profits are captured, where profits are being surrendered, when trades begin to weaken, and which virtual exit policies appear most effective. This does not change actual exits, rankings, sizing, or broker behavior.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowProfitCapturePeakDecayValidationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showProfitCapturePeakDecayValidationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Capture ratio", profitCapturePeakDecayExitValidation?.average_capture_ratio === null || profitCapturePeakDecayExitValidation?.average_capture_ratio === undefined ? "warming up" : `${(safeNumber(profitCapturePeakDecayExitValidation?.average_capture_ratio) * 100).toFixed(1)}%`],
            ["Avg giveback", profitCapturePeakDecayExitValidation?.average_giveback_pct === null || profitCapturePeakDecayExitValidation?.average_giveback_pct === undefined ? "warming up" : `${safeNumber(profitCapturePeakDecayExitValidation?.average_giveback_pct).toFixed(2)}%`],
            ["Highest giveback trade", profitCapturePeakDecayExitValidation?.highest_giveback_trade],
            ["Best capture trade", profitCapturePeakDecayExitValidation?.best_capture_trade],
            ["Strongest milestone", profitCapturePeakDecayExitValidation?.strongest_profit_milestone],
            ["Weakest milestone", profitCapturePeakDecayExitValidation?.weakest_profit_milestone],
            ["Failure probability", profitCapturePeakDecayExitValidation?.continuation_failure_probability === null || profitCapturePeakDecayExitValidation?.continuation_failure_probability === undefined ? "warming up" : `${safeNumber(profitCapturePeakDecayExitValidation?.continuation_failure_probability).toFixed(1)}%`],
            ["Strongest failure signal", profitCapturePeakDecayExitValidation?.strongest_failure_signal],
            ["Hold quality", profitCapturePeakDecayExitValidation?.hold_duration_quality_score === null || profitCapturePeakDecayExitValidation?.hold_duration_quality_score === undefined ? "warming up" : safeNumber(profitCapturePeakDecayExitValidation?.hold_duration_quality_score).toFixed(1)],
            ["Best exit policy", profitCapturePeakDecayExitValidation?.best_exit_policy],
            ["Highest improvement policy", profitCapturePeakDecayExitValidation?.highest_improvement_policy],
            ["Best policy by horizon", profitCapturePeakDecayExitValidation?.best_exit_policy_by_horizon ? Object.entries(profitCapturePeakDecayExitValidation.best_exit_policy_by_horizon).slice(0, 1).map(([k, v]) => `${String(k).replaceAll("_", " ")} -> ${String(v).replaceAll("_", " ")}`).join(", ") : "warming up"],
            ["Closest to readiness", profitCapturePeakDecayExitValidation?.closest_exit_policy_to_readiness],
            ["Readiness blocker", profitCapturePeakDecayExitValidation?.readiness_blocker],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Shadow recommendation: {String(profitCapturePeakDecayExitValidation?.shadow_recommendation || "Continue profit capture and exit validation shadow-only.").replaceAll("_", " ")}
          </div>
        </div>
        {showProfitCapturePeakDecayValidationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Horizon Exit Policies</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(profitCapturePeakDecayExitValidation?.best_exit_policy_by_horizon || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Hold Duration & Failure</div>
              <div>Best hold by horizon: {JSON.stringify(profitCapturePeakDecayExitValidation?.best_hold_duration_by_horizon || {})}</div>
              <div>Capture by horizon: {JSON.stringify(profitCapturePeakDecayExitValidation?.capture_ratio_by_horizon || {})}</div>
              <div>Giveback by horizon: {JSON.stringify(profitCapturePeakDecayExitValidation?.giveback_by_horizon || {})}</div>
              <div>Continuation by horizon: {JSON.stringify(profitCapturePeakDecayExitValidation?.continuation_by_horizon || {})}</div>
              <div>Readiness score: {safeNumber(profitCapturePeakDecayExitValidation?.readiness_score).toFixed(1)}</div>
              <div>Policy confidence: {safeNumber(profitCapturePeakDecayExitValidation?.policy_confidence).toFixed(1)}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Tracked trades: {safeNumber(profitCapturePeakDecayExitValidation?.tracked_trades).toFixed(0)}</div>
              <div>API calls: {safeNumber(profitCapturePeakDecayExitValidation?.api_calls_used).toFixed(0)} | Provider calls: {safeNumber(profitCapturePeakDecayExitValidation?.provider_calls_used).toFixed(0)} | LLM calls: {safeNumber(profitCapturePeakDecayExitValidation?.llm_calls_used).toFixed(0)}</div>
              <div>Behavior safe to apply: {profitCapturePeakDecayExitValidation?.behavior_safe_to_apply ? "yes" : "no"}</div>
              <div>Human review: {profitCapturePeakDecayExitValidation?.human_review_required ? "yes" : "no"}</div>
              <div>Auto apply: {profitCapturePeakDecayExitValidation?.auto_apply_allowed ? "yes" : "no"}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Execution Participation Audit & Calibration</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow-only funnel diagnostics showing where valid paper candidates are suppressed before broker submission.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowExecutionParticipationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showExecutionParticipationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Participation", executionParticipationAudit?.participation_label],
            ["Efficiency", `${safeNumber(executionParticipationAudit?.participation_efficiency_score).toFixed(1)}`],
            ["Suppression", `${safeNumber(executionParticipationAudit?.participation_suppression_score).toFixed(1)}`],
            ["Reviewed", executionParticipationAudit?.candidates_execution_reviewed],
            ["Unique reviewed", executionParticipationAudit?.unique_candidates_reviewed],
            ["Eligible", executionParticipationAudit?.eligible_candidates],
            ["Submitted", executionParticipationAudit?.candidates_submitted],
            ["Eligible -> Submitted", `${safeNumber(executionParticipationAudit?.eligible_to_submitted_rate).toFixed(1)}%`],
            ["Missed pressure", `${safeNumber(executionParticipationAudit?.missed_opportunity_pressure).toFixed(1)}`],
            ["Overprotection", `${safeNumber(executionParticipationAudit?.overprotection_risk).toFixed(1)}`],
            ["Underparticipation", `${safeNumber(executionParticipationAudit?.underparticipation_risk).toFixed(1)}`],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top rejection reasons: {Object.entries(executionParticipationAudit?.top_rejection_reasons || {}).slice(0, 4).map(([k, v]) => `${String(k).replaceAll("_", " ")} (${v})`).join(", ") || "collecting suppression evidence"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(executionParticipationAudit?.summary || "Execution participation audit is collecting funnel evidence.")}
          </div>
        </div>
        {showExecutionParticipationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Execution Funnel</div>
              <div>Seen: {safeNumber(executionParticipationAudit?.candidates_seen).toFixed(0)}</div>
              <div>Promoted: {safeNumber(executionParticipationAudit?.candidates_promoted).toFixed(0)}</div>
              <div>Deep scored: {safeNumber(executionParticipationAudit?.candidates_deep_scored).toFixed(0)}</div>
              <div>Execution reviewed: {safeNumber(executionParticipationAudit?.candidates_execution_reviewed).toFixed(0)}</div>
              <div>Unique reviewed: {safeNumber(executionParticipationAudit?.unique_candidates_reviewed).toFixed(0)}</div>
              <div>Submitted: {safeNumber(executionParticipationAudit?.candidates_submitted).toFixed(0)}</div>
              <div>Filled: {safeNumber(executionParticipationAudit?.candidates_filled).toFixed(0)}</div>
              <div>Unique submission rate: {safeNumber(executionParticipationAudit?.submission_rate_unique_candidates).toFixed(1)}%</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Rejection Stages</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(executionParticipationAudit?.rejection_stage_counts || {})}</div>
              <div style={{ marginTop: 6 }}>Duplicate: {safeNumber(executionParticipationAudit?.duplicate_symbol_blocks).toFixed(0)} | Active-position: {safeNumber(executionParticipationAudit?.active_position_blocks).toFixed(0)} | Confirmation: {safeNumber(executionParticipationAudit?.confirmation_required_blocks).toFixed(0)}</div>
              <div>Quality: {safeNumber(executionParticipationAudit?.quality_rejections).toFixed(0)} | Risk: {safeNumber(executionParticipationAudit?.risk_rejections).toFixed(0)} | Portfolio fit: {safeNumber(executionParticipationAudit?.portfolio_fit_rejections).toFixed(0)}</div>
              <div>Eligible not submitted reason: {String(executionParticipationAudit?.eligible_not_submitted_reason || "none").replaceAll("_", " ")}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Missed Opportunity Tracking</div>
              <div>High-expectancy missed: {safeNumber(executionParticipationAudit?.missed_high_expectancy_candidates).toFixed(0)}</div>
              <div>Missed breakout: {safeNumber(executionParticipationAudit?.missed_breakout_count).toFixed(0)}</div>
              <div>Missed continuation: {safeNumber(executionParticipationAudit?.missed_continuation_count).toFixed(0)}</div>
              <div>Capture rate: {safeNumber(executionParticipationAudit?.market_opportunity_capture_rate).toFixed(1)}%</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Trade Lifecycle Excursion & Exit Learning V2</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Paper-only hold-duration, profit giveback, continuation, and natural-exit learning without changing execution.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowTradeLifecycleExcursionDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showTradeLifecycleExcursionDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Active tracked", tradeLifecycleExcursion?.tracked_active_trades],
            ["Closed tracked", tradeLifecycleExcursion?.tracked_closed_trades],
            ["Avg MFE", tradeLifecycleExcursion?.average_mfe_pct === null || tradeLifecycleExcursion?.average_mfe_pct === undefined ? "warming up" : `${safeNumber(tradeLifecycleExcursion?.average_mfe_pct).toFixed(2)}%`],
            ["Avg MAE", tradeLifecycleExcursion?.average_mae_pct === null || tradeLifecycleExcursion?.average_mae_pct === undefined ? "warming up" : `${safeNumber(tradeLifecycleExcursion?.average_mae_pct).toFixed(2)}%`],
            ["Profit giveback", tradeLifecycleExcursion?.average_profit_giveback_pct === null || tradeLifecycleExcursion?.average_profit_giveback_pct === undefined ? "warming up" : `${safeNumber(tradeLifecycleExcursion?.average_profit_giveback_pct).toFixed(2)}%`],
            ["Capture ratio", tradeLifecycleExcursion?.average_profit_capture_ratio === null || tradeLifecycleExcursion?.average_profit_capture_ratio === undefined ? "warming up" : `${(safeNumber(tradeLifecycleExcursion?.average_profit_capture_ratio) * 100).toFixed(1)}%`],
            ["Avg hold", tradeLifecycleExcursion?.average_hold_duration_minutes === null || tradeLifecycleExcursion?.average_hold_duration_minutes === undefined ? "warming up" : `${safeNumber(tradeLifecycleExcursion?.average_hold_duration_minutes).toFixed(1)} min`],
            ["Hold quality", tradeLifecycleExcursion?.average_hold_duration_quality === null || tradeLifecycleExcursion?.average_hold_duration_quality === undefined ? "warming up" : safeNumber(tradeLifecycleExcursion?.average_hold_duration_quality).toFixed(1)],
            ["Follow-through", (tradeLifecycleExcursion?.average_follow_through_quality ?? tradeLifecycleExcursion?.follow_through_quality_score) === null || (tradeLifecycleExcursion?.average_follow_through_quality ?? tradeLifecycleExcursion?.follow_through_quality_score) === undefined ? "warming up" : safeNumber(tradeLifecycleExcursion?.average_follow_through_quality ?? tradeLifecycleExcursion?.follow_through_quality_score).toFixed(1)],
            ["Exit quality", (tradeLifecycleExcursion?.average_exit_quality ?? tradeLifecycleExcursion?.exit_quality_score) === null || (tradeLifecycleExcursion?.average_exit_quality ?? tradeLifecycleExcursion?.exit_quality_score) === undefined ? "awaiting closes" : safeNumber(tradeLifecycleExcursion?.average_exit_quality ?? tradeLifecycleExcursion?.exit_quality_score).toFixed(1)],
            ["High giveback", tradeLifecycleExcursion?.high_giveback_trade_count],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Learning readiness: {String(tradeLifecycleExcursion?.learning_readiness || (tradeLifecycleExcursion?.learning_ready ? "ready" : tradeLifecycleExcursion?.maturity) || "warming_up").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(tradeLifecycleExcursion?.summary || "Trade lifecycle excursion diagnostics are waiting for paper lifecycle evidence.")}
          </div>
        </div>
        {showTradeLifecycleExcursionDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Exit Labels</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(tradeLifecycleExcursion?.exit_label_distribution || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Follow-Through Labels</div>
              <div style={{ color: "#b8c7e6" }}>{JSON.stringify(tradeLifecycleExcursion?.follow_through_distribution || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Contexts</div>
              <div>Best follow-through: {String(tradeLifecycleExcursion?.best_follow_through_context || tradeLifecycleExcursion?.strongest_follow_through_context || "insufficient_evidence").replaceAll("_", " ")}</div>
              <div>Weakest follow-through: {String(tradeLifecycleExcursion?.weakest_follow_through_context || "insufficient_evidence").replaceAll("_", " ")}</div>
              <div>Best capture: {String(tradeLifecycleExcursion?.best_profit_capture_context || "insufficient_evidence").replaceAll("_", " ")}</div>
              <div>Worst giveback symbol: {String(tradeLifecycleExcursion?.worst_giveback_symbol || "insufficient_evidence").replaceAll("_", " ")}</div>
              <div>Premature exits: {safeNumber(tradeLifecycleExcursion?.premature_exit_count).toFixed(0)}</div>
              <div>Overstayed exits: {safeNumber(tradeLifecycleExcursion?.overstayed_exit_count).toFixed(0)}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Broad Universe Intake & Candidate Promotion</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Cached rotating-symbol discovery that shortlists broad-market opportunities without slowing the main Learning tab.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowBroadUniverseDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showBroadUniverseDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Universe observed", broadUniverseIntake?.broad_universe_size],
            ["Tradable universe", broadUniverseIntake?.tradable_universe_size],
            ["Scanned today", broadUniverseIntake?.symbols_scanned_today],
            ["Coverage today", `${safeNumber(broadUniverseIntake?.universe_coverage_today_pct).toFixed(1)}%`],
            ["Candidates detected", broadUniverseIntake?.candidates_detected],
            ["Deep scored", broadUniverseIntake?.deep_scored_count],
            ["Promoted", broadUniverseIntake?.promoted_to_top_buys_count],
            ["FMP budget", broadUniverseIntake?.fmp_budget_state],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Current bias: {String(broadUniverseIntake?.current_learning_bias || "warming_up").replaceAll("_", " ")} | Next scan: {String(broadUniverseIntake?.next_scan_focus || "quality_rotation").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(broadUniverseIntake?.summary || "Broad universe promotion diagnostics are warming up.")}
          </div>
        </div>
        {showBroadUniverseDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 10, fontSize: 12 }}>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Promoted Symbols</div>
              <div style={{ color: "#b8c7e6" }}>
                {(broadUniverseIntake?.promoted_symbols || []).slice(0, 14).join(", ") || "waiting for scan slice"}
              </div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Cap / Sector Mix</div>
              <div>Cap: {JSON.stringify(broadUniverseIntake?.promoted_cap_distribution || {})}</div>
              <div>Sector: {JSON.stringify(broadUniverseIntake?.promoted_sector_distribution || {})}</div>
            </div>
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Budget</div>
              <div>FMP usage: {safeNumber(broadUniverseIntake?.fmp_usage_pct).toFixed(2)}%</div>
              <div>Bandwidth: {safeNumber(broadUniverseIntake?.fmp_bandwidth_used_gb).toFixed(4)} / {safeNumber(broadUniverseIntake?.fmp_bandwidth_limit_gb, 50).toFixed(1)} GB</div>
              <div>Universe source: {String(broadUniverseIntake?.universe_source || "local_cache").replaceAll("_", " ")}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Market Calendar & Market Knowledge</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Cached market-session truth plus structured context for timing, style fit, and behavioral risk.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowMarketCalendarDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showMarketCalendarDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Current session", marketCalendarKnowledge?.current_session_type],
            ["Tradable", marketCalendarKnowledge?.session_tradable ? "yes" : "blocked"],
            ["Orders", marketCalendarKnowledge?.broker_order_submission_allowed ? "allowed" : "blocked"],
            ["Holiday", marketCalendarKnowledge?.is_market_holiday ? (marketCalendarKnowledge?.holiday_name || "yes") : "no"],
            ["Early close", marketCalendarKnowledge?.is_early_close ? (marketCalendarKnowledge?.early_close_time || "yes") : "no"],
            ["Session posture", marketCalendarKnowledge?.session_execution_posture],
            ["Market structure", marketCalendarKnowledge?.market_structure_label],
            ["Best style", marketCalendarKnowledge?.trade_style_environment],
            ["Behavior", marketCalendarKnowledge?.behavioral_market_state],
            ["Knowledge confidence", marketCalendarKnowledge?.market_knowledge_confidence],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(1) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next open: {String(marketCalendarKnowledge?.next_market_open || "n/a")} | Next close: {String(marketCalendarKnowledge?.next_market_close || "n/a")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(marketCalendarKnowledge?.market_context_summary || "Market context diagnostics are warming up.")}
          </div>
        </div>
        {showMarketCalendarDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 10, fontSize: 12 }}>
            {[
              ["Calendar source", marketCalendarKnowledge?.market_calendar_source],
              ["Calendar cache", marketCalendarKnowledge?.market_calendar_cache_hit ? "hit" : "fresh/local"],
              ["Calendar stale", marketCalendarKnowledge?.market_calendar_stale ? "yes" : "no"],
              ["Session risk", marketCalendarKnowledge?.session_risk_score],
              ["Risk label", marketCalendarKnowledge?.session_risk_label],
              ["Confirmation", marketCalendarKnowledge?.session_confirmation_requirement],
              ["Exploration support", marketCalendarKnowledge?.market_context_supports_exploration ? "yes" : "no"],
              ["Exploration quality", marketCalendarKnowledge?.exploration_context_quality],
            ].map(([label, value]) => (
              <div key={label} style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
                <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
                <div style={{ color: "#dbeafe", fontWeight: 800 }}>
                  {typeof value === "number" ? value.toFixed(1) : String(value || "n/a").replaceAll("_", " ")}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Profit-Seeking Adaptive Exploration</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Paper-only calibration for bounded exploratory trades when normal gates over-block valid profit-seeking setups.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowProfitExplorationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showProfitExplorationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Participation status", profitSeekingExploration?.caution_aggression_label || profitSeekingExploration?.mode],
            ["Over-cautious risk", profitSeekingExploration?.over_cautious_risk],
            ["Under-cautious risk", profitSeekingExploration?.under_cautious_risk],
            ["Exploration allocation", `${safeNumber(profitSeekingExploration?.exploration_allocation_pct).toFixed(1)}%`],
            ["Exploitation allocation", `${safeNumber(profitSeekingExploration?.exploitation_allocation_pct, 100).toFixed(1)}%`],
            ["Used today", `${safeNumber(profitSeekingExploration?.exploration_trades_used_today).toFixed(0)} / ${safeNumber(profitSeekingExploration?.exploration_trades_allowed_today).toFixed(0)}`],
            ["Missed opportunity pressure", profitSeekingExploration?.missed_opportunity_pressure],
            ["Participation quality", profitSeekingExploration?.participation_quality_score],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(1) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommendation: {String(profitSeekingExploration?.adaptive_exploration_recommendation || "Maintain bounded profit-seeking exploration.").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(profitSeekingExploration?.summary || "Profit-seeking adaptive exploration is waiting for unified diagnostics.")}
          </div>
        </div>
        {showProfitExplorationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 10, fontSize: 12 }}>
            {[
              ["Underexplored contexts", profitSeekingExploration?.underexplored_contexts || []],
              ["Overexplored contexts", profitSeekingExploration?.overexplored_contexts || []],
            ].map(([title, values]) => (
              <div key={title} style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
                <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>{title}</div>
                {(Array.isArray(values) && values.length > 0) ? values.slice(0, 6).map((item) => (
                  <div key={`${title}-${item}`} style={{ color: "#b8c7e6", marginBottom: 4 }}>{String(item).replaceAll("_", " ")}</div>
                )) : <div style={{ color: "#9fb1cc" }}>waiting for context evidence</div>}
              </div>
            ))}
            <div style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
              <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>Safety</div>
              <div>Random trades: {profitSeekingExploration?.exploration_randomness_allowed ? "allowed" : "disabled"}</div>
              <div>Decay active: {profitSeekingExploration?.exploration_decay_active ? "yes" : "no"}</div>
              <div>Decay reason: {String(profitSeekingExploration?.exploration_decay_reason || "warming_up").replaceAll("_", " ")}</div>
            </div>
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>Mobile Runtime Compaction & Learning Fast-Path</h3>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginBottom: 12 }}>
          Compact display diagnostics for broker-confirmed positions, stale internal workflow rows, and canceled-order noise.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, fontSize: 12 }}>
          {[
            ["Broker active positions", mobileRuntimeCompaction?.true_broker_active_positions],
            ["Displayed active positions", mobileRuntimeCompaction?.display_active_positions_count],
            ["Internal workflow rows", mobileRuntimeCompaction?.internal_open_workflow_rows],
            ["Stale rows hidden", mobileRuntimeCompaction?.stale_rows_hidden_count],
            ["Canceled orders compacted", mobileRuntimeCompaction?.canceled_orders_compacted_count],
            ["Learning fast path", mobileRuntimeCompaction?.learning_fast_path_active ? "active" : "warming up"],
            ["Mobile payload", mobileRuntimeCompaction?.mobile_payload_compacted ? "compacted" : "standard"],
            ["Full history", mobileRuntimeCompaction?.full_history_preserved ? "preserved" : "check"],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(0) : String(value ?? "n/a").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(mobileRuntimeCompaction?.summary || "Mobile runtime compaction is waiting for broker/workflow evidence.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Portfolio Diversification & Correlation Intelligence</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow-only portfolio-fit diagnostics for concentration, duplicate themes, cluster pressure, and quality-preserving diversification.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowPortfolioDiversificationDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showPortfolioDiversificationDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Concentration risk", portfolioDiversificationV2?.average_concentration_pressure_score],
            ["Correlation risk", portfolioDiversificationV2?.average_correlation_pressure_score],
            ["Diversification quality", portfolioDiversificationV2?.average_diversification_quality_score],
            ["Portfolio fit quality", portfolioDiversificationV2?.average_portfolio_fit_score],
            ["Largest cluster", portfolioDiversificationV2?.largest_cluster],
            ["Top duplicate theme", portfolioDiversificationV2?.top_duplicate_theme],
            ["Penalized / boosted", `${safeNumber(portfolioDiversificationV2?.candidates_penalized_for_correlation).toFixed(0)} / ${safeNumber(portfolioDiversificationV2?.candidates_boosted_for_diversification).toFixed(0)}`],
            ["Balance label", portfolioDiversificationV2?.current_portfolio_balance_label],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(1) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(portfolioDiversificationV2?.summary || "Portfolio diversification diagnostics are waiting for more candidate and position evidence.")}
          </div>
        </div>
        {showPortfolioDiversificationDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 10, fontSize: 12 }}>
            {[
              ["Cluster summary", (portfolioDiversificationV2?.candidate_cluster_summary || {}).clusters || {}],
              ["Theme families", (portfolioDiversificationV2?.candidate_cluster_summary || {}).families || {}],
              ["Market-cap distribution", (portfolioDiversificationV2?.candidate_cluster_summary || {}).market_cap_distribution || {}],
              ["Fit labels", (portfolioDiversificationV2?.candidate_cluster_summary || {}).portfolio_fit_labels || {}],
            ].map(([title, payload]) => (
              <div key={title} style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
                <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>{title}</div>
                {Object.keys(payload || {}).length === 0 ? (
                  <div style={{ color: "#9fb1cc" }}>n/a</div>
                ) : Object.entries(payload || {}).slice(0, 8).map(([key, value]) => (
                  <div key={`${title}-${key}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                    <span style={{ color: "#9fb1cc" }}>{String(key).replaceAll("_", " ")}</span>
                    <span style={{ color: "#f2f7ff", fontWeight: 700 }}>{String(value)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>Adaptive Execution & Exit Intelligence V2</h3>
            <div style={{ fontSize: 12, color: "#9fb1cc" }}>
              Shadow-only diagnostics for entry timing discipline, natural-exit review, regime posture, lifecycle stability, and profit capture.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAdaptiveExitDetails((v) => !v)}
            style={{
              background: "linear-gradient(180deg, #1f3c64 0%, #163254 100%)",
              color: "#dce7ff",
              border: "1px solid #496a97",
              borderRadius: "6px",
              fontSize: "0.72rem",
              padding: "0.25rem 0.55rem",
              cursor: "pointer",
            }}
          >
            {showAdaptiveExitDetails ? "Hide Details" : "Show Details"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 9, marginTop: 12, fontSize: 12 }}>
          {[
            ["Execution posture", adaptiveExecutionExitV2?.execution_posture],
            ["Exit quality", adaptiveExecutionExitV2?.exit_quality],
            ["Continuation quality", adaptiveExecutionExitV2?.continuation_quality],
            ["Chase risk", adaptiveExecutionExitV2?.chase_risk],
            ["Adaptive profitability", adaptiveExecutionExitV2?.adaptive_profitability],
            ["Lifecycle stability", adaptiveExecutionExitV2?.lifecycle_stability],
            ["Strongest behavior", adaptiveExecutionExitV2?.strongest_adaptive_behavior],
            ["Biggest weakness", adaptiveExecutionExitV2?.biggest_weakness],
          ].map(([label, value]) => (
            <div key={label} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
              <div style={{ color: "#9fb1cc", fontSize: 11 }}>{label}</div>
              <div style={{ color: "#f2f7ff", fontWeight: 800 }}>
                {typeof value === "number" ? value.toFixed(1) : String(value || "warming up").replaceAll("_", " ")}
              </div>
            </div>
          ))}
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(adaptiveExecutionExitV2?.summary || "Adaptive execution and exit diagnostics are waiting for more candidate and lifecycle evidence.")}
          </div>
        </div>
        {showAdaptiveExitDetails ? (
          <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
            {[
              ["Execution timing", adaptiveExecutionIntelligence, ["execution_timing_quality", "breakout_confirmation_quality", "momentum_extension_risk", "entry_realism_score"]],
              ["Exit intelligence", exitIntelligenceV2, ["continuation_strength", "profit_protection_quality", "profit_giveback_pressure", "exit_efficiency_score"]],
              ["Regime adaptation", regimeAdaptiveTrading, ["current_regime_behavior", "regime_execution_posture", "regime_adaptive_score", "regime_chase_risk"]],
              ["Lifecycle adaptation", lifecycleAdaptation, ["adaptive_review_urgency", "hold_quality", "lifecycle_stability", "invalidation_pressure"]],
              ["Profitability diagnostics", adaptiveProfitabilityDiagnostics, ["expected_profit_capture_quality", "expectancy_survivability_score", "continuation_adjusted_expectancy", "adaptive_profitability_score"]],
            ].map(([title, payload, keys]) => (
              <div key={title} style={{ background: "rgba(10,22,41,0.48)", border: "1px solid #29476f", borderRadius: 10, padding: "9px 10px" }}>
                <div style={{ color: "#dbeafe", fontWeight: 800, marginBottom: 6 }}>{title}</div>
                {keys.map((key) => {
                  const value = payload?.[key];
                  return (
                    <div key={`${title}-${key}`} style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                      <span style={{ color: "#9fb1cc" }}>{String(key).replaceAll("_", " ")}</span>
                      <span style={{ color: "#f2f7ff", fontWeight: 700 }}>
                        {value && typeof value === "object" ? metricDisplay(value) : String(value || "n/a").replaceAll("_", " ")}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Learning Maturity & System Health</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, fontSize: 12 }}>
          <div>Evidence maturity: {String(evidenceStatus?.label || "warming_up").replaceAll("_", " ")}</div>
          <div>Closed trade evidence: {safeNumber(evidenceStatus?.closed_trade_count, evidenceStatus?.evidence_count).toFixed(0)}</div>
          <div>Replay ready: {evidenceStatus?.replay_ready ? "yes" : "no"}</div>
          <div>Lifecycle ready: {evidenceStatus?.lifecycle_ready ? "yes" : "no"}</div>
          <div>Expectancy ready: {evidenceStatus?.expectancy_ready ? "yes" : "no"}</div>
          <div>API calls used: {safeNumber(unified?.api_calls_used).toFixed(0)}</div>
          <div>Failed advanced sources: {safeNumber(unified?.failed_sources_count).toFixed(0)}</div>
          <div>Future suites use adapter: {futureContract?.use_unified_learning_adapter ? "yes" : "no"}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            {String(evidenceStatus?.explanation || "Learning maturity diagnostics are warming up.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle, padding: "10px 12px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px", flexWrap: "wrap" }}>
        <div style={{ fontSize: 12, color: "#9fb1cc" }}>
          Advanced diagnostics are collapsed and lazy-loaded. New suites should feed this unified snapshot instead of adding initial frontend calls.
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
            padding: "0.25rem 0.55rem",
            cursor: "pointer",
          }}
        >
          {showAdvancedSections ? "Hide Advanced Diagnostics" : "Load Advanced Diagnostics"}
        </button>
      </div>

      {showAdvancedSections ? (
        <div style={{ ...panelStyle }}>
          <h3 style={{ marginTop: 0 }}>Advanced Diagnostics Status</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 9, fontSize: 12 }}>
            {Object.entries(advancedStatuses || {}).map(([name, status]) => (
              <div key={name} style={{ background: "rgba(12,24,42,0.42)", border: "1px solid #2f4a72", borderRadius: 10, padding: "8px 10px" }}>
                <div style={{ color: "#dbeafe", fontWeight: 700 }}>{String(name).replaceAll("_", " ")}</div>
                <div>Status: {String(status?.status || "not_loaded").replaceAll("_", " ")}</div>
                <div>Maturity: {String(status?.maturity || "summary_only").replaceAll("_", " ")}</div>
                <div>Blocker: {String(status?.blocker || "none").replaceAll("_", " ")}</div>
                <div>API calls: {safeNumber(status?.api_calls_used).toFixed(0)} | Stale: {status?.stale ? "yes" : "no"}</div>
              </div>
            ))}
          </div>
          {fetchError ? (
            <details style={{ marginTop: 12, fontSize: 12, color: "#f0c6b1" }}>
              <summary style={{ cursor: "pointer" }}>Advanced fetch details</summary>
              <div style={{ marginTop: 6 }}>{fetchError}</div>
            </details>
          ) : null}
        </div>
      ) : null}

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Learned Exit Validation Live</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12, marginTop: 12 }}>
          <div>Bucket enabled: {controlledPaperLearnedExit?.learned_exit_bucket_enabled ? "yes" : "no"}</div>
          <div>Paper exit path verified: {controlledPaperLearnedExit?.paper_exit_path_verified ? "yes" : "no"}</div>
          <div>Used today / max: {safeNumber(controlledPaperLearnedExit?.learned_exits_used_today).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.max_learning_corrected_exits_per_day, 5).toFixed(0)}</div>
          <div>Remaining today: {safeNumber(controlledPaperLearnedExit?.learned_exits_remaining_today, 5).toFixed(0)}</div>
          <div>Scalp/day/swing coverage: {String(controlledPaperLearnedExit?.scalp_day_swing_coverage_status || "not_started").replaceAll("_", " ")}</div>
          <div>Top policy used: {String(controlledPaperLearnedExit?.top_policy_used || "none").replaceAll("_", " ")}</div>
          <div>Candidates reviewed: {safeNumber(controlledPaperLearnedExit?.learned_exit_candidates_today).toFixed(0)}</div>
          <div>Exits applied: {safeNumber(controlledPaperLearnedExit?.learned_corrected_exits_today).toFixed(0)}</div>
          <div>Rejected candidates: {safeNumber(controlledPaperLearnedExit?.rejected_learned_exit_candidates).toFixed(0)}</div>
          <div>Baseline vs learned: {String(controlledPaperLearnedExit?.baseline_vs_learned_status || "controlled_bucket_disabled_until_exit_path_verified").replaceAll("_", " ")}</div>
          <div>PF delta: {safeNumber(controlledPaperLearnedExit?.profit_factor_delta).toFixed(2)}</div>
          <div>WR delta: {safeNumber(controlledPaperLearnedExit?.win_rate_delta).toFixed(2)}</div>
          <div>Expectancy delta: {safeNumber(controlledPaperLearnedExit?.expectancy_delta).toFixed(2)}</div>
          <div>Giveback delta: {safeNumber(controlledPaperLearnedExit?.giveback_delta).toFixed(2)}</div>
          <div>Capacity freed: {safeNumber(controlledPaperLearnedExit?.capacity_freed_by_learned_exits).toFixed(0)}</div>
          <div>Rollback status: {String(controlledPaperLearnedExit?.rollback_status || "auto_disabled").replaceAll("_", " ")}</div>
          <div>Rollback reason: {String(controlledPaperLearnedExit?.rollback_reason || "none").replaceAll("_", " ")}</div>
          <div>Kill switch: {String(controlledPaperLearnedExit?.kill_switch_status || "enabled").replaceAll("_", " ")}</div>
          <div>Safety status: {String(controlledPaperLearnedExit?.safety_status || "safe_disabled").replaceAll("_", " ")}</div>
          <div>API/provider/LLM calls: {safeNumber(controlledPaperLearnedExit?.api_calls_used).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.provider_calls_used).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.llm_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Path blockers: {(controlledPaperLearnedExit?.paper_exit_path_blockers || ["none"]).map((item) => String(item).replaceAll("_", " ")).join(", ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next recommended action: {String(controlledPaperLearnedExit?.next_recommended_action || "keep_bucket_disabled_until_verified").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Astra is checking whether its learned exits can be safely tested on a tiny paper-only bucket. The bucket stays disabled unless the paper sell path, duplicate-exit protection, broker fill confirmation, evidence thresholds, and rollback controls are all verified.
          </div>
        </div>
      </details>
    </div>
  );

  return (
    <div style={{ display: "grid", gap: "12px" }}>
      {fetchError ? (
        <div style={{ ...panelStyle, borderColor: "#7f3f4a", color: "#ffd8dd", fontSize: 12 }}>
          Some learning endpoints failed: {fetchError}
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
        <h3 style={{ marginTop: 0 }}>Snapshot Graphs</h3>
        <div style={{ fontSize: 12, color: "#9fb1cc", marginBottom: 10 }}>
          Quick visuals for trend, entry quality, follow-through pressure, and buy conversion.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(250px, 1fr))", gap: 12 }}>
          <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
            <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Released WR Trend</div>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={timeline}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="winRate" stroke="#38bdf8" strokeWidth={2} dot={false} name="Win Rate" />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
            <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Good vs Bad Entries</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={[entryExitBars[0]]}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="good" fill="#22c55e" name="Good Entries" />
                <Bar dataKey="bad" fill="#ef4444" name="Bad Entries" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
            <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Exit Timing Pressure</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={[entryExitBars[1]]}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="early" fill="#38bdf8" name="Early Exits" />
                <Bar dataKey="late" fill="#f59e0b" name="Late Exits" />
                <Bar dataKey="missed" fill="#f43f5e" name="Missed Profit" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
            <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Follow-Through & Failure Pressure</div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={topSnapshotFollowthroughBars}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="value" fill="#a78bfa" name="Score / Rate" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div style={{ background: "rgba(12,24,42,0.35)", border: "1px solid #2f4a72", borderRadius: 10, padding: 8 }}>
            <div style={{ fontSize: 12, color: "#cfe1ff", marginBottom: 4 }}>Buy Conversion Trend</div>
            <ResponsiveContainer width="100%" height={180}>
              <LineChart data={timeline}>
                <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
                <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
                <Tooltip />
                <Line type="monotone" dataKey="buyConversion" stroke="#22c55e" strokeWidth={2} dot={false} name="Buy Conversion" />
              </LineChart>
            </ResponsiveContainer>
          </div>
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, minHeight: 200 }}>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeline}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="winRate" stroke="#38bdf8" strokeWidth={2} dot={false} name="Win Rate" />
            </LineChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={timeline}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="ts" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Line type="monotone" dataKey="winsorized" stroke="#f59e0b" strokeWidth={2} dot={false} name="Average Return" />
            </LineChart>
          </ResponsiveContainer>
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
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, minHeight: 200 }}>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={[entryExitBars[0]]}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="good" fill="#22c55e" name="Good Entries" />
              <Bar dataKey="bad" fill="#ef4444" name="Bad Entries" />
            </BarChart>
          </ResponsiveContainer>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={[entryExitBars[1]]}>
              <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
              <XAxis dataKey="name" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <YAxis tick={{ fill: "#8ea1c3", fontSize: 11 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="early" fill="#38bdf8" name="Early Exits" />
              <Bar dataKey="late" fill="#f59e0b" name="Late Exits" />
              <Bar dataKey="missed" fill="#f43f5e" name="Missed Profit" />
            </BarChart>
          </ResponsiveContainer>
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

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Observation & Learning Throughput</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Trades opened today: {safeNumber(observationThroughput?.trades_opened_today).toFixed(0)}</div>
          <div>Trades closed today: {safeNumber(observationThroughput?.trades_closed_today).toFixed(0)}</div>
          <div>Labels created today: {safeNumber(observationThroughput?.labels_created_today).toFixed(0)}</div>
          <div>Observation completion: {safeNumber(observationThroughput?.observation_completion_score).toFixed(1)}</div>
          <div>Learning throughput: {safeNumber(observationThroughput?.learning_throughput_score).toFixed(1)}</div>
          <div>Completed coverage: {safeNumber(observationThroughput?.completed_trade_coverage_pct).toFixed(1)}%</div>
          <div>
            Average time to close: {firstFiniteOrNull(observationThroughput?.average_time_to_close_hours) === null
              ? "n/a"
              : `${safeNumber(observationThroughput?.average_time_to_close_hours).toFixed(2)}h`}
          </div>
          <div>Primary bottleneck: {String(observationThroughput?.primary_learning_bottleneck || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(observationThroughput?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommendation: {String(observationThroughput?.throughput_recommendation_summary || "Waiting for observation throughput diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Execution, Market Knowledge & Learning Expansion</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Current entries today: {safeNumber(executionMarketLearning?.current_entries_today).toFixed(0)}</div>
          <div>Current closures today: {safeNumber(executionMarketLearning?.current_closures_today).toFixed(0)}</div>
          <div>Projected opened/day: {safeNumber(executionMarketLearning?.projected_trades_opened_per_day).toFixed(1)}</div>
          <div>Projected closed/day: {safeNumber(executionMarketLearning?.projected_trades_closed_per_day).toFixed(1)}</div>
          <div>Projected labels/day: {safeNumber(executionMarketLearning?.projected_labels_created_per_day).toFixed(1)}</div>
          <div>Learning speed multiplier: {safeNumber(executionMarketLearning?.projected_learning_speed_multiplier, 1).toFixed(2)}x</div>
          <div>Execution readiness: {safeNumber(executionMarketLearning?.execution_readiness_score).toFixed(1)}</div>
          <div>Market knowledge: {safeNumber(executionMarketLearning?.market_knowledge_score).toFixed(1)}</div>
          <div>Learning expansion: {safeNumber(executionMarketLearning?.learning_expansion_score).toFixed(1)}</div>
          <div>Master Suite 3 score: {safeNumber(executionMarketLearning?.master_suite_3_score).toFixed(1)}</div>
          <div>Primary constraint: {String(executionMarketLearning?.primary_learning_constraint || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(executionMarketLearning?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(executionMarketLearning?.master_suite_3_summary || "Waiting for execution and learning expansion diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Autonomous Research & Self-Regulation</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Primary weakness: {String(autonomousSelfRegulation?.primary_trading_weakness || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>
            Likely root cause: {String(
              Array.isArray(autonomousSelfRegulation?.likely_root_causes)
                ? autonomousSelfRegulation.likely_root_causes[0]
                : autonomousSelfRegulation?.root_cause_summary || "waiting_for_data"
            ).replaceAll("_", " ")}
          </div>
          <div>Highest priority experiment: {String(autonomousSelfRegulation?.highest_priority_experiment || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Structural health: {safeNumber(autonomousSelfRegulation?.structural_health_score).toFixed(1)}</div>
          <div>Learning pipeline integrity: {safeNumber(autonomousSelfRegulation?.learning_pipeline_integrity_score).toFixed(1)}</div>
          <div>Promotion recommendation: {String(autonomousSelfRegulation?.promotion_recommendation || "monitor_only").replaceAll("_", " ")}</div>
          <div>Next best action: {String(autonomousSelfRegulation?.next_best_action_summary || "continue_shadow_monitoring").replaceAll("_", " ")}</div>
          <div>Suite 4 score: {safeNumber(autonomousSelfRegulation?.suite_4_score).toFixed(1)}</div>
          <div>API calls used: {safeNumber(autonomousSelfRegulation?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(autonomousSelfRegulation?.suite_4_summary || "Waiting for autonomous self-regulation diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Paper Autopilot Throughput Expansion</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Max new paper trades/cycle: {safeNumber(paperThroughputExpansion?.current_max_new_per_cycle).toFixed(0)}</div>
          <div>Max concurrent positions: {safeNumber(paperThroughputExpansion?.current_max_concurrent_positions).toFixed(0)}</div>
          <div>Cooldown seconds: {safeNumber(paperThroughputExpansion?.current_cooldown_seconds).toFixed(0)}</div>
          <div>Soft candidates: {paperThroughputExpansion?.soft_candidate_expansion_enabled ? "enabled" : "disabled"}</div>
          <div>Projected opened/day: {safeNumber(paperThroughputExpansion?.projected_trades_opened_per_day).toFixed(1)}</div>
          <div>Projected closed/day: {safeNumber(paperThroughputExpansion?.projected_trades_closed_per_day).toFixed(1)}</div>
          <div>Projected labels/day: {safeNumber(paperThroughputExpansion?.projected_labels_created_per_day).toFixed(1)}</div>
          <div>Learning speed multiplier: {safeNumber(paperThroughputExpansion?.projected_learning_speed_multiplier, 1).toFixed(2)}x</div>
          <div>API calls used: {safeNumber(paperThroughputExpansion?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(paperThroughputExpansion?.throughput_expansion_summary || "Waiting for paper throughput expansion diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Paper Path Gating Summary</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Paper path status: {String(alpacaPaperBroker?.paper_path_gating_summary?.paper_path_status || "unknown_blocker").replaceAll("_", " ")}</div>
          <div>Top blocker: {String(alpacaPaperBroker?.paper_path_gating_summary?.top_blocker || "unknown_blocker").replaceAll("_", " ")}</div>
          <div>Candidates reviewed: {safeNumber(alpacaPaperBroker?.paper_path_gating_summary?.candidates_reviewed_today).toFixed(0)}</div>
          <div>Candidates blocked: {safeNumber(alpacaPaperBroker?.paper_path_gating_summary?.candidates_blocked).toFixed(0)}</div>
          <div>Current open positions: {safeNumber(alpacaPaperBroker?.paper_path_gating_summary?.current_open_positions, paperStatus?.open_positions_count).toFixed(0)}</div>
          <div>Open position rows: {safeNumber(alpacaPaperBroker?.paper_path_gating_summary?.open_position_rows_count).toFixed(0)}</div>
          <div>Capacity available: {safeNumber(alpacaPaperBroker?.paper_path_gating_summary?.capacity_available).toFixed(0)}</div>
          <div>Capacity blocked: {alpacaPaperBroker?.paper_path_gating_summary?.capacity_blocked ? "yes" : "no"}</div>
          <div>Learned exits applied: {alpacaPaperBroker?.paper_path_gating_summary?.learned_exits_applied ? "yes" : "no"}</div>
          <div>Learned exits readiness: {String(alpacaPaperBroker?.paper_path_gating_summary?.readiness_status || "not_ready").replaceAll("_", " ")}</div>
          <div>Best shadow exit policy: {String(alpacaPaperBroker?.paper_path_gating_summary?.best_shadow_exit_policy || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Best shadow hold window: {String(alpacaPaperBroker?.paper_path_gating_summary?.best_shadow_hold_window || "insufficient_data").replaceAll("_", " ")}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended safe action: {String(alpacaPaperBroker?.paper_path_gating_summary?.recommended_safe_action || "Waiting for paper-path gating diagnostics.")}
          </div>
        </div>
      </div>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Paper Throughput, Exit Validation & Catalyst Intelligence V1</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12, marginTop: 12 }}>
          <div>Paper throughput status: {String(paperThroughputExitCatalyst?.paper_throughput_status || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Top blocker: {String(paperThroughputExitCatalyst?.top_blocker || "unknown_blocker").replaceAll("_", " ")}</div>
          <div>Reviewed / eligible / submitted: {safeNumber(paperThroughputExitCatalyst?.reviewed_today).toFixed(0)} / {safeNumber(paperThroughputExitCatalyst?.eligible_today).toFixed(0)} / {safeNumber(paperThroughputExitCatalyst?.submitted_today).toFixed(0)}</div>
          <div>Blocked today: {safeNumber(paperThroughputExitCatalyst?.blocked_today).toFixed(0)}</div>
          <div>Suppression rate: {safeNumber(paperThroughputExitCatalyst?.suppression_rate).toFixed(1)}%</div>
          <div>Missed evidence estimate: {safeNumber(paperThroughputExitCatalyst?.missed_evidence_estimate).toFixed(0)}</div>
          <div>True capacity available: {safeNumber(paperThroughputExitCatalyst?.true_capacity_available).toFixed(0)}</div>
          <div>Safe capacity available: {safeNumber(paperThroughputExitCatalyst?.safe_capacity_available).toFixed(0)}</div>
          <div>Duplicate / confirmation blocks: {safeNumber(paperThroughputExitCatalyst?.duplicate_blocks).toFixed(0)} / {safeNumber(paperThroughputExitCatalyst?.confirmation_blocks).toFixed(0)}</div>
          <div>Stale row blocks: {safeNumber(paperThroughputExitCatalyst?.stale_row_blocks).toFixed(0)}</div>
          <div>Learned exit validation status: {String(paperThroughputExitCatalyst?.readiness_status || "not_ready_more_evidence_required").replaceAll("_", " ")}</div>
          <div>Best shadow exit policy: {String(paperThroughputExitCatalyst?.best_shadow_exit_policy || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Current vs learned PF: {safeNumber(paperThroughputExitCatalyst?.current_policy_profit_factor).toFixed(2)} / {safeNumber(paperThroughputExitCatalyst?.best_policy_profit_factor).toFixed(2)}</div>
          <div>Improvement delta: {safeNumber(paperThroughputExitCatalyst?.improvement_delta).toFixed(2)}</div>
          <div>Learned exit bucket enabled: {paperThroughputExitCatalyst?.learned_exit_validation_bucket_enabled ? "yes" : "no"}</div>
          <div>Catalyst coverage: {safeNumber(paperThroughputExitCatalyst?.catalyst_coverage).toFixed(1)}</div>
          <div>Unknown catalyst rate: {safeNumber(paperThroughputExitCatalyst?.unknown_catalyst_rate).toFixed(1)}%</div>
          <div>Best catalyst horizon: {String(
            typeof paperThroughputExitCatalyst?.best_horizon_by_catalyst === "object"
              ? Object.entries(paperThroughputExitCatalyst.best_horizon_by_catalyst || {})[0]?.join(": ")
              : paperThroughputExitCatalyst?.best_horizon_by_catalyst || "insufficient_data"
          ).replaceAll("_", " ")}</div>
          <div>API/provider/LLM calls: {safeNumber(paperThroughputExitCatalyst?.api_calls_used).toFixed(0)} / {safeNumber(paperThroughputExitCatalyst?.provider_calls_used).toFixed(0)} / {safeNumber(paperThroughputExitCatalyst?.llm_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended next action: {String(paperThroughputExitCatalyst?.recommended_next_action || "continue_collecting_paper_and_shadow_evidence").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Astra is diagnosing paper-throughput blockers, comparing learned shadow exits against current paper exits, and improving catalyst visibility using cached evidence only. This does not enable live trading, learned exits, broker changes, sizing changes, or ranking changes.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Multi-Horizon Capacity & Controlled Exit Validation V1</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12, marginTop: 12 }}>
          <div>Total capacity: {safeNumber(multiHorizonCapacityExitValidation?.total_capacity, 20).toFixed(0)}</div>
          <div>Total used / available: {safeNumber(multiHorizonCapacityExitValidation?.total_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.total_available).toFixed(0)}</div>
          <div>Swing 8 used/available: {safeNumber(multiHorizonCapacityExitValidation?.swing_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.swing_available).toFixed(0)}</div>
          <div>Day 8 used/available: {safeNumber(multiHorizonCapacityExitValidation?.day_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.day_available).toFixed(0)}</div>
          <div>Scalp 4 used/available: {safeNumber(multiHorizonCapacityExitValidation?.scalp_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.scalp_available).toFixed(0)}</div>
          <div>Top capacity blocker: {String(multiHorizonCapacityExitValidation?.top_capacity_blocker || "none").replaceAll("_", " ")}</div>
          <div>Blocked by capacity: {safeNumber(multiHorizonCapacityExitValidation?.candidates_blocked_by_horizon_capacity).toFixed(0)}</div>
          <div>Missed evidence from capacity: {safeNumber(multiHorizonCapacityExitValidation?.missed_evidence_due_to_capacity).toFixed(0)}</div>
          <div>Unknown horizon positions: {safeNumber(multiHorizonCapacityExitValidation?.unknown_horizon_positions).toFixed(0)}</div>
          <div>Stale internal rows: {safeNumber(multiHorizonCapacityExitValidation?.stale_internal_rows).toFixed(0)}</div>
          <div>Learning-corrected bucket enabled: {multiHorizonCapacityExitValidation?.learned_exit_bucket_enabled ? "yes" : "no"}</div>
          <div>Learned exits used today: {safeNumber(multiHorizonCapacityExitValidation?.learned_exits_used_today).toFixed(0)}</div>
          <div>Baseline vs learned: {String(multiHorizonCapacityExitValidation?.baseline_vs_learned_status || "learning_bucket_disabled_collecting_baseline").replaceAll("_", " ")}</div>
          <div>Best learned exit policy: {String(multiHorizonCapacityExitValidation?.best_learned_exit_policy || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Learned exit PF delta: {safeNumber(multiHorizonCapacityExitValidation?.profit_factor_delta).toFixed(2)}</div>
          <div>Rollback status: {multiHorizonCapacityExitValidation?.learned_exit_bucket_auto_disabled ? "auto-disabled" : "active"}</div>
          <div>Rollback reason: {String(multiHorizonCapacityExitValidation?.rollback_reason || "none").replaceAll("_", " ")}</div>
          <div>Safety status: {String(multiHorizonCapacityExitValidation?.safety_status || "safe_disabled").replaceAll("_", " ")}</div>
          <div>API/provider/LLM calls: {safeNumber(multiHorizonCapacityExitValidation?.api_calls_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.provider_calls_used).toFixed(0)} / {safeNumber(multiHorizonCapacityExitValidation?.llm_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next recommended action: {String(multiHorizonCapacityExitValidation?.next_recommended_action || "continue_horizon_capacity_monitoring").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Astra is separating paper capacity into swing, day-trade, and scalp pools so long holds cannot consume all learning slots. A tiny learned-exit validation bucket is visible and reversible, but remains guarded by paper-only mode, human review, evidence thresholds, and a kill switch.
          </div>
        </div>
      </details>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Learned Exit Validation Live</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12, marginTop: 12 }}>
          <div>Bucket enabled: {controlledPaperLearnedExit?.learned_exit_bucket_enabled ? "yes" : "no"}</div>
          <div>Paper exit path verified: {controlledPaperLearnedExit?.paper_exit_path_verified ? "yes" : "no"}</div>
          <div>Used today / max: {safeNumber(controlledPaperLearnedExit?.learned_exits_used_today).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.max_learning_corrected_exits_per_day, 5).toFixed(0)}</div>
          <div>Remaining today: {safeNumber(controlledPaperLearnedExit?.learned_exits_remaining_today, 5).toFixed(0)}</div>
          <div>Scalp/day/swing coverage: {String(controlledPaperLearnedExit?.scalp_day_swing_coverage_status || "not_started").replaceAll("_", " ")}</div>
          <div>Top policy used: {String(controlledPaperLearnedExit?.top_policy_used || "none").replaceAll("_", " ")}</div>
          <div>Candidates reviewed: {safeNumber(controlledPaperLearnedExit?.learned_exit_candidates_today).toFixed(0)}</div>
          <div>Exits applied: {safeNumber(controlledPaperLearnedExit?.learned_corrected_exits_today).toFixed(0)}</div>
          <div>Rejected candidates: {safeNumber(controlledPaperLearnedExit?.rejected_learned_exit_candidates).toFixed(0)}</div>
          <div>Baseline vs learned: {String(controlledPaperLearnedExit?.baseline_vs_learned_status || "controlled_bucket_disabled_until_exit_path_verified").replaceAll("_", " ")}</div>
          <div>PF delta: {safeNumber(controlledPaperLearnedExit?.profit_factor_delta).toFixed(2)}</div>
          <div>WR delta: {safeNumber(controlledPaperLearnedExit?.win_rate_delta).toFixed(2)}</div>
          <div>Expectancy delta: {safeNumber(controlledPaperLearnedExit?.expectancy_delta).toFixed(2)}</div>
          <div>Giveback delta: {safeNumber(controlledPaperLearnedExit?.giveback_delta).toFixed(2)}</div>
          <div>Capacity freed: {safeNumber(controlledPaperLearnedExit?.capacity_freed_by_learned_exits).toFixed(0)}</div>
          <div>Rollback status: {String(controlledPaperLearnedExit?.rollback_status || "auto_disabled").replaceAll("_", " ")}</div>
          <div>Rollback reason: {String(controlledPaperLearnedExit?.rollback_reason || "none").replaceAll("_", " ")}</div>
          <div>Kill switch: {String(controlledPaperLearnedExit?.kill_switch_status || "enabled").replaceAll("_", " ")}</div>
          <div>Safety status: {String(controlledPaperLearnedExit?.safety_status || "safe_disabled").replaceAll("_", " ")}</div>
          <div>API/provider/LLM calls: {safeNumber(controlledPaperLearnedExit?.api_calls_used).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.provider_calls_used).toFixed(0)} / {safeNumber(controlledPaperLearnedExit?.llm_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Path blockers: {(controlledPaperLearnedExit?.paper_exit_path_blockers || ["none"]).map((item) => String(item).replaceAll("_", " ")).join(", ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next recommended action: {String(controlledPaperLearnedExit?.next_recommended_action || "keep_bucket_disabled_until_verified").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Astra is checking whether its learned exits can be safely tested on a tiny paper-only bucket. The bucket stays disabled unless the paper sell path, duplicate-exit protection, broker fill confirmation, evidence thresholds, and rollback controls are all verified.
          </div>
        </div>
      </details>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Horizon Coverage Summary</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Scalp coverage: {safeNumber(horizonCoverageSummary?.scalp_coverage_pct).toFixed(1)}%</div>
          <div>Day coverage: {safeNumber(horizonCoverageSummary?.day_coverage_pct).toFixed(1)}%</div>
          <div>Swing coverage: {safeNumber(horizonCoverageSummary?.swing_coverage_pct).toFixed(1)}%</div>
          <div>Dominant horizon: {String(horizonCoverageSummary?.dominant_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Best horizon: {String(horizonCoverageSummary?.best_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Weakest horizon: {String(horizonCoverageSummary?.weakest_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Paper horizon bias: {String(horizonCoverageSummary?.paper_horizon_bias || "balanced_mix").replaceAll("_", " ")}</div>
          <div>Horizon mismatch risk: {safeNumber(horizonCoverageSummary?.horizon_mismatch_risk_score).toFixed(1)}</div>
          <div>Shadow horizon balance: {safeNumber(horizonCoverageSummary?.shadow_horizon_balance).toFixed(1)}</div>
          <div>Learned exits applied: {horizonCoverageSummary?.learned_exits_applied ? "yes" : "no"}</div>
          <div>Learned horizon status: {String(horizonCoverageSummary?.learned_horizon_status || "shadow_only_not_applied").replaceAll("_", " ")}</div>
          <div>Tested horizons: {(Array.isArray(horizonCoverageSummary?.tested_horizons) ? horizonCoverageSummary.tested_horizons : []).join(", ").replaceAll("_", " ") || "waiting for data"}</div>
          <div>Missing horizons: {Array.isArray(horizonCoverageSummary?.missing_horizons)
            ? horizonCoverageSummary.missing_horizons.slice(0, 5).join(", ").replaceAll("_", " ") || "none"
            : `coarse ${(Array.isArray(horizonCoverageSummary?.missing_horizons?.coarse) ? horizonCoverageSummary.missing_horizons.coarse : []).join(", ").replaceAll("_", " ") || "none"}; fine ${(Array.isArray(horizonCoverageSummary?.missing_horizons?.fine) ? horizonCoverageSummary.missing_horizons.fine : []).slice(0, 5).join(", ").replaceAll("_", " ") || "none"}`}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Hold buckets: 15m {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["15m"]).toFixed(0)}
            {" | "}30m {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["30m"]).toFixed(0)}
            {" | "}45m {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["45m"]).toFixed(0)}
            {" | "}60m {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["60m"]).toFixed(0)}
            {" | "}2h {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["2h"]).toFixed(0)}
            {" | "}4h {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["4h"]).toFixed(0)}
            {" | "}EOD {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["eod"]).toFixed(0)}
            {" | "}1d {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["1d"]).toFixed(0)}
            {" | "}2d {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["2d"]).toFixed(0)}
            {" | "}3d {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["3d"]).toFixed(0)}
            {" | "}5d {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["5d"]).toFixed(0)}
            {" | "}10d {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["10d"]).toFixed(0)}
            {" | "}10d+ {safeNumber((horizonCoverageSummary?.observed_hold_bucket_counts || {})["10d_plus"]).toFixed(0)}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next recommended horizon test: {String(horizonCoverageSummary?.next_recommended_horizon_test || "waiting for diagnostics").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Why long holds persist: {String(horizonCoverageSummary?.why_positions_hold_long || "waiting for diagnostics").replaceAll("_", " ")}
          </div>
        </div>
      </div>

      <details style={{ ...panelStyle }}>
        <summary style={{ cursor: "pointer", fontWeight: 700 }}>Multi-Horizon Intelligence & Adaptive Lifecycle Suite V1</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12, marginTop: 12 }}>
          <div>Suite status: {String(multiHorizonAdaptiveLifecycle?.suite_status || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Horizons tested: {(Array.isArray(multiHorizonAdaptiveLifecycle?.horizons_tested) ? multiHorizonAdaptiveLifecycle.horizons_tested : []).join(", ").replaceAll("_", " ") || "waiting for data"}</div>
          <div>Missing horizons: {Array.isArray(multiHorizonAdaptiveLifecycle?.missing_horizons)
            ? multiHorizonAdaptiveLifecycle.missing_horizons.join(", ").replaceAll("_", " ") || "none"
            : `fine ${(Array.isArray(multiHorizonAdaptiveLifecycle?.missing_horizons?.fine) ? multiHorizonAdaptiveLifecycle.missing_horizons.fine : []).slice(0, 6).join(", ").replaceAll("_", " ") || "none"}`}</div>
          <div>Dominant paper horizon: {String(multiHorizonAdaptiveLifecycle?.dominant_paper_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Dominant shadow horizon: {String(multiHorizonAdaptiveLifecycle?.dominant_shadow_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Best horizon: {String(multiHorizonAdaptiveLifecycle?.best_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Weakest horizon: {String(multiHorizonAdaptiveLifecycle?.weakest_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Horizon mismatch risk: {safeNumber(multiHorizonAdaptiveLifecycle?.horizon_mismatch_risk_score).toFixed(1)}</div>
          <div>Best symbol horizon: {String(multiHorizonAdaptiveLifecycle?.best_symbol_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Worst symbol horizon: {String(multiHorizonAdaptiveLifecycle?.worst_symbol_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Strongest setup horizon: {String(multiHorizonAdaptiveLifecycle?.strongest_setup_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Strongest catalyst horizon: {String(multiHorizonAdaptiveLifecycle?.strongest_catalyst_horizon || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Strongest peer pattern: {String(multiHorizonAdaptiveLifecycle?.strongest_peer_group_pattern || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Estimated profit lost to mismatch: {safeNumber(multiHorizonAdaptiveLifecycle?.estimated_profit_lost_to_horizon_mismatch).toFixed(2)}</div>
          <div>Learned exits applied: {multiHorizonAdaptiveLifecycle?.learned_exits_applied ? "yes" : "no"}</div>
          <div>Behavior safe to apply: {multiHorizonAdaptiveLifecycle?.behavior_safe_to_apply ? "yes" : "no"}</div>
          <div>API/provider/LLM calls: {safeNumber(multiHorizonAdaptiveLifecycle?.api_calls_used).toFixed(0)} / {safeNumber(multiHorizonAdaptiveLifecycle?.provider_calls_used).toFixed(0)} / {safeNumber(multiHorizonAdaptiveLifecycle?.llm_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Next recommended test: {String(multiHorizonAdaptiveLifecycle?.next_recommended_test || "waiting for diagnostics").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Astra is learning whether each opportunity behaves best as a scalp, day trade, or swing by comparing horizon outcomes, lifecycle signals, and peer-group behavior. This remains shadow-only and does not change exits, entries, sizing, or broker behavior.
          </div>
        </div>
      </details>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Multi-Horizon Paper Trading Learning</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Current phase: {String(multiHorizonPaperTrading?.current_learning_phase || "phase_1_foundation").replaceAll("_", " ")}</div>
          <div>Recommended next phase: {String(multiHorizonPaperTrading?.recommended_next_phase || "remain_phase_1_foundation").replaceAll("_", " ")}</div>
          <div>Scalp target/day: {String(multiHorizonPaperTrading?.suggested_scalp_trades_per_day || "0-2")}</div>
          <div>Day-trade target/day: {String(multiHorizonPaperTrading?.suggested_day_trades_per_day || "5-10")}</div>
          <div>Swing target/day: {String(multiHorizonPaperTrading?.suggested_swing_trades_per_day || "2-5")}</div>
          <div>Total target/day: {String(multiHorizonPaperTrading?.suggested_total_paper_trades_per_day || "7-17")}</div>
          <div>Entries: scalp {safeNumber(multiHorizonPaperTrading?.scalp_entries_today).toFixed(0)} / day {safeNumber(multiHorizonPaperTrading?.day_trade_entries_today).toFixed(0)} / swing {safeNumber(multiHorizonPaperTrading?.swing_trade_entries_today).toFixed(0)}</div>
          <div>Closures: scalp {safeNumber(multiHorizonPaperTrading?.scalp_closures_today).toFixed(0)} / day {safeNumber(multiHorizonPaperTrading?.day_trade_closures_today).toFixed(0)} / swing {safeNumber(multiHorizonPaperTrading?.swing_trade_closures_today).toFixed(0)}</div>
          <div>Best horizon: {String(multiHorizonPaperTrading?.best_current_horizon || "day_trade").replaceAll("_", " ")}</div>
          <div>Weakest horizon: {String(multiHorizonPaperTrading?.weakest_current_horizon || "scalp").replaceAll("_", " ")}</div>
          <div>Learning score: {safeNumber(multiHorizonPaperTrading?.multi_horizon_learning_score).toFixed(1)}</div>
          <div>Natural exits preserved: {multiHorizonPaperTrading?.natural_exit_preserved === false ? "no" : "yes"}</div>
          <div>API calls used: {safeNumber(multiHorizonPaperTrading?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(multiHorizonPaperTrading?.multi_horizon_summary || "Waiting for multi-horizon paper trading diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Dynamic Opportunity Weighting & Profit Optimization</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>
            Current profile: expected return {safeNumber((dynamicOpportunityWeighting?.current_weight_profile || {}).expected_return_percent, 0.3).toFixed(2)}
            {" "} / confidence {safeNumber((dynamicOpportunityWeighting?.current_weight_profile || {}).probability_confidence, 0.25).toFixed(2)}
          </div>
          <div>Average aggressive profit score: {safeNumber(dynamicOpportunityWeighting?.average_aggressive_profit_score).toFixed(1)}</div>
          <div>Average risk-adjusted profit score: {safeNumber(dynamicOpportunityWeighting?.average_risk_adjusted_profit_score).toFixed(1)}</div>
          <div>High-profit candidates found: {safeNumber(dynamicOpportunityWeighting?.high_predicted_profit_candidate_count).toFixed(0)}</div>
          <div>High-profit approved: {safeNumber(dynamicOpportunityWeighting?.high_profit_approved_count).toFixed(0)}</div>
          <div>High-profit blocked: {safeNumber(dynamicOpportunityWeighting?.high_profit_blocked_count).toFixed(0)}</div>
          <div>Large-cap bias detected: {dynamicOpportunityWeighting?.large_cap_bias_detected ? "yes" : "no"}</div>
          <div>Candidate diversity score: {safeNumber(dynamicOpportunityWeighting?.candidate_diversity_score).toFixed(1)}</div>
          <div>Weight confidence: {String(dynamicOpportunityWeighting?.weight_confidence || "low").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(dynamicOpportunityWeighting?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended adjustments: {Object.entries(dynamicOpportunityWeighting?.recommended_weight_adjustments || {}).map(([k, v]) => `${String(k).replaceAll("_", " ")}: ${String(v).replaceAll("_", " ")}`).join(" | ") || "Waiting for outcome samples."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Funnel summary: {String(dynamicOpportunityWeighting?.opportunity_funnel_summary || "Waiting for dynamic opportunity weighting diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Opportunity Discovery Expansion & Momentum Intelligence</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Market-cap distribution: {String(opportunityDiscoveryExpansion?.market_cap_distribution_summary || "waiting for candidate mix")}</div>
          <div>Discovery diversity: {safeNumber(opportunityDiscoveryExpansion?.average_discovery_diversity_score, opportunityDiscoveryExpansion?.discovery_diversity_score).toFixed(1)}</div>
          <div>Momentum opportunities: {safeNumber(opportunityDiscoveryExpansion?.momentum_opportunity_count).toFixed(0)}</div>
          <div>Breakout candidates: {safeNumber(opportunityDiscoveryExpansion?.breakout_candidate_count).toFixed(0)}</div>
          <div>Unusual volume count: {safeNumber(opportunityDiscoveryExpansion?.unusual_volume_count).toFixed(0)}</div>
          <div>High-upside candidates: {safeNumber(opportunityDiscoveryExpansion?.high_upside_candidate_count, opportunityDiscoveryExpansion?.high_predicted_profit_candidate_count).toFixed(0)}</div>
          <div>Mega-cap concentration: {safeNumber(opportunityDiscoveryExpansion?.mega_cap_concentration_score).toFixed(1)}</div>
          <div>Non-mega candidates: {safeNumber(opportunityDiscoveryExpansion?.non_mega_candidate_count).toFixed(0)}</div>
          <div>API calls used: {safeNumber(opportunityDiscoveryExpansion?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top opportunity types: {(opportunityDiscoveryExpansion?.top_opportunity_types || [])
              .slice(0, 5)
              .map((item) => `${String(item?.type || "unknown").replaceAll("_", " ")} (${safeNumber(item?.count).toFixed(0)})`)
              .join(" | ") || "Waiting for opportunity type diagnostics."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Survival statistics: boosted {safeNumber((opportunityDiscoveryExpansion?.opportunity_survival_statistics || {})?.boosted_candidates).toFixed(0)}
            {" "} / penalized {safeNumber((opportunityDiscoveryExpansion?.opportunity_survival_statistics || {})?.penalized_candidates).toFixed(0)}
            {" "} / avg multiplier {safeNumber((opportunityDiscoveryExpansion?.opportunity_survival_statistics || {})?.average_multiplier, 1).toFixed(3)}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(opportunityDiscoveryExpansion?.opportunity_discovery_summary || "Waiting for opportunity discovery expansion diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Edge Development & Expectancy Intelligence</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Candidates evaluated: {safeNumber(edgeDevelopment?.candidates_evaluated).toFixed(0)}</div>
          <div>Average opportunity quality: {safeNumber(edgeDevelopment?.average_opportunity_quality).toFixed(1)}</div>
          <div>Average expectancy: {safeNumber(edgeDevelopment?.average_expectancy, edgeDevelopment?.average_expected_value_score).toFixed(1)}</div>
          <div>Average win probability: {safeNumber(edgeDevelopment?.average_expected_win_probability).toFixed(1)}%</div>
          <div>Average reward/risk: {safeNumber(edgeDevelopment?.average_expected_reward_risk_ratio).toFixed(2)}</div>
          <div>Best current archetype: {String(edgeDevelopment?.best_current_archetype || "insufficient_data").replaceAll("_", " ")}</div>
          <div>Strongest regime alignment: {String(edgeDevelopment?.strongest_regime_alignment || "insufficient_data").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(edgeDevelopment?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Archetype breakdown: {Object.entries(edgeDevelopment?.archetype_distribution || {})
              .slice(0, 6)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for archetype diagnostics."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Opportunity quality: {Object.entries(edgeDevelopment?.opportunity_quality_distribution || {})
              .slice(0, 5)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for opportunity quality distribution."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Edge composite: {Object.entries(edgeDevelopment?.edge_distribution || {})
              .slice(0, 5)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for edge composite distribution."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Regime alignment: {String(edgeDevelopment?.regime_alignment_summary || "Waiting for regime alignment diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(edgeDevelopment?.edge_summary || "Waiting for edge development diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Trade Management & Portfolio Intelligence</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Portfolio heat: {safeNumber(tradeManagementPortfolio?.portfolio_heat_score).toFixed(1)}</div>
          <div>Correlation risk: {safeNumber(tradeManagementPortfolio?.portfolio_correlation_risk).toFixed(1)}</div>
          <div>Sector concentration: {safeNumber(tradeManagementPortfolio?.sector_concentration_score).toFixed(1)}</div>
          <div>Correlated exposure: {safeNumber(tradeManagementPortfolio?.correlated_exposure_score).toFixed(1)}</div>
          <div>Portfolio stability: {safeNumber(tradeManagementPortfolio?.portfolio_stability_score).toFixed(1)}</div>
          <div>Diversification quality: {safeNumber(tradeManagementPortfolio?.diversification_quality_score).toFixed(1)}</div>
          <div>Avg exit quality: {safeNumber(tradeManagementPortfolio?.average_exit_quality_score).toFixed(1)}</div>
          <div>Avg position size: {safeNumber(tradeManagementPortfolio?.average_intelligent_position_size_pct).toFixed(2)}%</div>
          <div>Avg survivability: {safeNumber(tradeManagementPortfolio?.average_survivability_score).toFixed(1)}</div>
          <div>Avg trade management: {safeNumber(tradeManagementPortfolio?.average_trade_management_score).toFixed(1)}</div>
          <div>Portfolio risk label: {String(tradeManagementPortfolio?.portfolio_risk_label || "stable").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(tradeManagementPortfolio?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Exit intelligence: {Object.entries(tradeManagementPortfolio?.exit_readiness_distribution || {})
              .slice(0, 5)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for exit readiness diagnostics."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Sizing diagnostics: {Object.entries(tradeManagementPortfolio?.sizing_distribution || {})
              .slice(0, 5)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for sizing diagnostics."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Trade management distribution: {Object.entries(tradeManagementPortfolio?.trade_management_distribution || {})
              .slice(0, 5)
              .map(([k, v]) => `${String(k).replaceAll("_", " ")} (${safeNumber(v).toFixed(0)})`)
              .join(" | ") || "Waiting for managed-trade diagnostics."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Survivability: {String(tradeManagementPortfolio?.survivability_diagnostics || "Waiting for survivability diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(tradeManagementPortfolio?.trade_management_summary || "Waiting for trade management portfolio diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Adaptive Intelligence & Learning Infrastructure</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Adaptive intelligence: {safeNumber(adaptiveLearningInfrastructure?.adaptive_intelligence_score).toFixed(1)}</div>
          <div>Infrastructure maturity: {safeNumber(adaptiveLearningInfrastructure?.infrastructure_maturity_score).toFixed(1)}</div>
          <div>Learning readiness: {safeNumber(adaptiveLearningInfrastructure?.learning_readiness_score).toFixed(1)}</div>
          <div>Behavioral awareness: {safeNumber(adaptiveLearningInfrastructure?.behavioral_awareness_score).toFixed(1)}</div>
          <div>Trading day health: {safeNumber(adaptiveLearningInfrastructure?.trading_day_health_score).toFixed(1)}</div>
          <div>Daily survivability: {safeNumber(adaptiveLearningInfrastructure?.daily_survivability_score).toFixed(1)}</div>
          <div>Replay ready: {adaptiveLearningInfrastructure?.replay_learning_ready ? "yes" : "no"}</div>
          <div>Counterfactual tracking: {adaptiveLearningInfrastructure?.counterfactual_tracking_ready === false ? "not ready" : "ready"}</div>
          <div>Copilot ready: {adaptiveLearningInfrastructure?.ollama_copilot_ready ? "yes" : "no"}</div>
          <div>Hermes compatible: {adaptiveLearningInfrastructure?.hermes_agent_compatible ? "yes" : "no"}</div>
          <div>AI execution authority: {adaptiveLearningInfrastructure?.ai_execution_authority ? "yes" : "no"}</div>
          <div>API calls used: {safeNumber(adaptiveLearningInfrastructure?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Strongest edge: {String(adaptiveLearningInfrastructure?.strongest_current_edge || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Weakest area: {String(adaptiveLearningInfrastructure?.weakest_current_area || adaptiveLearningInfrastructure?.current_primary_weakness || "waiting_for_self_review").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Portfolio health: {String(adaptiveLearningInfrastructure?.portfolio_heat_summary || "Waiting for portfolio health diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Blockers: {String(adaptiveLearningInfrastructure?.top_blocker_reason || "none").replaceAll("_", " ")}
            {" / "}
            Rejections: {String(adaptiveLearningInfrastructure?.most_common_rejection_reason || "none").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Self-review: {String(adaptiveLearningInfrastructure?.self_review_summary || "Waiting for self-review diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Market behavior: {String(adaptiveLearningInfrastructure?.current_market_behavior_summary || adaptiveLearningInfrastructure?.behavioral_risk_summary || "Waiting for behavioral diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Replay/session readiness: {String(adaptiveLearningInfrastructure?.replay_context_summary || "Replay hooks waiting for candidate snapshots.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Copilot: {String(adaptiveLearningInfrastructure?.astra_copilot_summary || "Copilot diagnostics are explanation-only.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Replay, Lifecycle & Expectancy Learning</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Replay learning score: {safeNumber(replayLifecycleExpectancy?.replay_learning_score).toFixed(1)}</div>
          <div>Replay maturity: {safeNumber(replayLifecycleExpectancy?.replay_learning_maturity_score).toFixed(1)}</div>
          <div>Lifecycle quality: {safeNumber(replayLifecycleExpectancy?.lifecycle_tracking_quality_score).toFixed(1)}</div>
          <div>Expectancy maturity: {safeNumber(replayLifecycleExpectancy?.expectancy_learning_maturity_score).toFixed(1)}</div>
          <div>Adaptive maturity: {safeNumber(replayLifecycleExpectancy?.adaptive_learning_maturity_score).toFixed(1)}</div>
          <div>Policy readiness: {safeNumber(replayLifecycleExpectancy?.adaptive_policy_readiness_score).toFixed(1)}</div>
          <div>Expectancy sample size: {safeNumber(replayLifecycleExpectancy?.expectancy_sample_size).toFixed(0)}</div>
          <div>Win rate: {safeNumber(replayLifecycleExpectancy?.expectancy_win_rate).toFixed(1)}%</div>
          <div>Profit factor: {safeNumber(replayLifecycleExpectancy?.expectancy_profit_factor).toFixed(2)}</div>
          <div>Avg return: {safeNumber(replayLifecycleExpectancy?.expectancy_avg_return).toFixed(3)}%</div>
          <div>Replay ready: {replayLifecycleExpectancy?.replay_learning_ready ? "yes" : "no"}</div>
          <div>Policy auto-apply: {replayLifecycleExpectancy?.adaptive_policy_auto_apply_allowed ? "yes" : "no"}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Strongest expectancy archetype: {String(replayLifecycleExpectancy?.top_expectancy_archetype || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Weakest expectancy archetype: {String(replayLifecycleExpectancy?.weakest_expectancy_archetype || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Learning signals: {String(replayLifecycleExpectancy?.strongest_learning_signal || "insufficient_data").replaceAll("_", " ")}
            {" / "}
            {String(replayLifecycleExpectancy?.weakest_learning_signal || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Adaptive policy: {String(replayLifecycleExpectancy?.current_policy_recommendation || replayLifecycleExpectancy?.adaptive_policy_recommendation || "waiting_for_policy_review").replaceAll("_", " ")}
            {" ("}
            {safeNumber(replayLifecycleExpectancy?.adaptive_policy_confidence).toFixed(1)}
            {")"}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Policy reason: {String(replayLifecycleExpectancy?.current_policy_reason || replayLifecycleExpectancy?.adaptive_policy_reason || "Waiting for expectancy evidence.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Counterfactual: {String(replayLifecycleExpectancy?.replay_counterfactual_summary || "Waiting for replay counterfactual summary.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Lifecycle: {String(replayLifecycleExpectancy?.lifecycle_summary || "Waiting for lifecycle tracking summary.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Loop summary: {String(replayLifecycleExpectancy?.learning_loop_summary || "Waiting for replay/lifecycle/expectancy loop diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Regime, Execution & Survivability Intelligence</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Current regime: {String(regimeExecutionSurvivability?.current_market_regime || "uncertain_regime").replaceAll("_", " ")}</div>
          <div>Regime confidence: {safeNumber(regimeExecutionSurvivability?.regime_confidence).toFixed(1)}</div>
          <div>Execution quality: {safeNumber(regimeExecutionSurvivability?.execution_quality_score).toFixed(1)}</div>
          <div>Breakout quality: {safeNumber(regimeExecutionSurvivability?.breakout_quality_score).toFixed(1)}</div>
          <div>Chase risk: {safeNumber(regimeExecutionSurvivability?.chase_risk_score).toFixed(1)}</div>
          <div>Follow-through: {safeNumber(regimeExecutionSurvivability?.follow_through_probability).toFixed(1)}</div>
          <div>Survivability: {safeNumber(regimeExecutionSurvivability?.survivability_score).toFixed(1)}</div>
          <div>Risk compression: {safeNumber(regimeExecutionSurvivability?.risk_compression_score).toFixed(1)}</div>
          <div>Portfolio survivability: {safeNumber(regimeExecutionSurvivability?.portfolio_survivability_score).toFixed(1)}</div>
          <div>Concentration risk: {safeNumber(regimeExecutionSurvivability?.portfolio_concentration_risk).toFixed(1)}</div>
          <div>Correlation risk: {safeNumber(regimeExecutionSurvivability?.portfolio_correlation_risk).toFixed(1)}</div>
          <div>Market context: {safeNumber(regimeExecutionSurvivability?.market_context_awareness_score).toFixed(1)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Strongest regime: {String(regimeExecutionSurvivability?.strongest_regime || "insufficient_data").replaceAll("_", " ")}
            {" / "}
            Weakest regime: {String(regimeExecutionSurvivability?.weakest_regime || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Survivability archetypes: {String(regimeExecutionSurvivability?.strongest_survivability_archetype || "insufficient_data").replaceAll("_", " ")}
            {" / "}
            {String(regimeExecutionSurvivability?.weakest_survivability_archetype || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Execution environments: {String(regimeExecutionSurvivability?.strongest_execution_environment || "insufficient_data").replaceAll("_", " ")}
            {" / "}
            {String(regimeExecutionSurvivability?.weakest_execution_environment || "insufficient_data").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Portfolio balance: {String(regimeExecutionSurvivability?.portfolio_balance_summary || "Waiting for portfolio adaptation diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Risk compression: {String(regimeExecutionSurvivability?.portfolio_risk_compression_summary || "Waiting for risk compression diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Adaptive execution: {String(regimeExecutionSurvivability?.adaptive_execution_summary || "Waiting for adaptive execution diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Market Session, Execution Timing & Replay Readiness</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Session mode: {String(marketSessionExecutionTiming?.market_session_mode || "unknown_closed").replaceAll("_", " ")}</div>
          <div>Market open: {marketSessionExecutionTiming?.market_is_open ? "yes" : "no"}</div>
          <div>Tradable: {marketSessionExecutionTiming?.market_is_tradable ? "yes" : "no"}</div>
          <div>Orders allowed: {marketSessionExecutionTiming?.paper_order_submission_allowed ? "yes" : "blocked"}</div>
          <div>Confirmation required: {marketSessionExecutionTiming?.execution_confirmation_required === false ? "no" : "yes"}</div>
          <div>Open confirmation: {String(marketSessionExecutionTiming?.open_confirmation_label || "watch_only").replaceAll("_", " ")} ({safeNumber(marketSessionExecutionTiming?.open_confirmation_score).toFixed(1)})</div>
          <div>Open orders: {safeNumber(marketSessionExecutionTiming?.open_orders_count).toFixed(0)}</div>
          <div>Stale open orders: {safeNumber(marketSessionExecutionTiming?.stale_open_orders_count).toFixed(0)}</div>
          <div>Weekend queued orders: {safeNumber(marketSessionExecutionTiming?.weekend_queued_orders_count).toFixed(0)}</div>
          <div>Intent status: {String(marketSessionExecutionTiming?.execution_intent_status || "intent_pending").replaceAll("_", " ")}</div>
          <div>Replay ready: {marketSessionExecutionTiming?.replay_learning_ready ? "yes" : "no"}</div>
          <div>Session tracking: {marketSessionExecutionTiming?.session_timing_outcome_tracking_ready === false ? "not ready" : "ready"}</div>
          <div>Auto-cancel stale orders: {marketSessionExecutionTiming?.auto_cancel_stale_paper_orders ? "enabled" : "disabled"}</div>
          <div>API calls used: {safeNumber(marketSessionExecutionTiming?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Recommended action: {String(marketSessionExecutionTiming?.recommended_action || "create_execution_intent_and_wait_for_open_confirmation").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Session reason: {String(marketSessionExecutionTiming?.session_reason || marketSessionExecutionTiming?.open_confirmation_reason || "Waiting for session timing diagnostics.")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Stale order reason: {String(marketSessionExecutionTiming?.stale_order_reason || "no_stale_open_orders_detected").replaceAll("_", " ")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Paper Opportunity Allocation & Exploration</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Lane targets: core {safeNumber(paperOpportunityAllocation?.core_lane_target_pct, 55).toFixed(0)}% / momentum {safeNumber(paperOpportunityAllocation?.momentum_lane_target_pct, 30).toFixed(0)}% / exploration {safeNumber(paperOpportunityAllocation?.exploration_lane_target_pct, 15).toFixed(0)}%</div>
          <div>Current lanes: core {safeNumber(paperOpportunityAllocation?.current_core_lane_count).toFixed(0)} / momentum {safeNumber(paperOpportunityAllocation?.current_momentum_lane_count).toFixed(0)} / exploration {safeNumber(paperOpportunityAllocation?.current_exploration_lane_count).toFixed(0)}</div>
          <div>Valid exploration candidates: {safeNumber(paperOpportunityAllocation?.valid_exploration_candidates).toFixed(0)}</div>
          <div>High-upside approved/rejected: {safeNumber(paperOpportunityAllocation?.high_upside_candidates_approved).toFixed(0)} / {safeNumber(paperOpportunityAllocation?.high_upside_candidates_rejected).toFixed(0)}</div>
          <div>Mega-cap concentration: {safeNumber(paperOpportunityAllocation?.mega_cap_concentration_pct).toFixed(1)}%</div>
          <div>Non-mega candidates: {safeNumber(paperOpportunityAllocation?.non_mega_candidate_count).toFixed(0)}</div>
          <div>Recommended weights: core {safeNumber(paperOpportunityAllocation?.recommended_core_lane_weight, 0.55).toFixed(2)} / momentum {safeNumber(paperOpportunityAllocation?.recommended_momentum_lane_weight, 0.3).toFixed(2)} / exploration {safeNumber(paperOpportunityAllocation?.recommended_exploration_lane_weight, 0.15).toFixed(2)}</div>
          <div>Confidence: {String(paperOpportunityAllocation?.allocation_confidence || "low").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(paperOpportunityAllocation?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Top rejection reasons: {(paperOpportunityAllocation?.top_exploration_rejection_reasons || [])
              .slice(0, 4)
              .map((item) => `${String(item?.reason || "unknown").replaceAll("_", " ")} (${safeNumber(item?.count).toFixed(0)})`)
              .join(" | ") || "No exploration rejection reasons yet."}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Adjustment: {String(paperOpportunityAllocation?.allocation_adjustment_reason || "waiting_for_lane_outcomes").replaceAll("_", " ")}
          </div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(paperOpportunityAllocation?.allocation_summary || "Waiting for paper allocation diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Adaptive Market Intake & FMP Budget</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Current utilization: {safeNumber(adaptiveMarketIntake?.current_utilization_pct).toFixed(3)}%</div>
          <div>
            Monthly used / limit: {safeNumber(adaptiveMarketIntake?.current_monthly_bandwidth_used_gb).toFixed(3)} GB / {safeNumber(adaptiveMarketIntake?.monthly_bandwidth_limit_gb, 50).toFixed(1)} GB
          </div>
          <div>
            Target range: {safeNumber(adaptiveMarketIntake?.target_utilization_low_pct, 75).toFixed(0)}-{safeNumber(adaptiveMarketIntake?.target_utilization_high_pct, 80).toFixed(0)}%
          </div>
          <div>Remaining bandwidth: {safeNumber(adaptiveMarketIntake?.remaining_bandwidth_gb).toFixed(2)} GB</div>
          <div>Intake mode: {String(adaptiveMarketIntake?.intake_mode || adaptiveMarketIntake?.adaptive_intake_mode || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Refresh intensity: {String(adaptiveMarketIntake?.recommended_refresh_intensity || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Exploration multiplier: {safeNumber(adaptiveMarketIntake?.recommended_exploration_multiplier, 1).toFixed(2)}x</div>
          <div>Small/mid-cap multiplier: {safeNumber(adaptiveMarketIntake?.recommended_small_mid_cap_scan_multiplier, 1).toFixed(2)}x</div>
          <div>Runtime protection: {adaptiveMarketIntake?.runtime_protection_active ? "active" : "clear"}</div>
          <div>Provider pressure: {adaptiveMarketIntake?.provider_pressure_detected ? "detected" : "clear"}</div>
          <div>API calls used: {safeNumber(adaptiveMarketIntake?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(adaptiveMarketIntake?.intake_summary || "Waiting for adaptive market intake diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Alpaca Paper Broker Status</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Enabled: {alpacaPaperBroker?.enabled ? "yes" : "no"}</div>
          <div>Paper mode verified: {alpacaPaperBroker?.paper_mode_verified ? "yes" : "no"}</div>
          <div>Broker execution enabled: {alpacaPaperBroker?.broker_execution_enabled ? "yes" : "no"}</div>
          <div>Equity: ${safeNumber(alpacaPaperBroker?.account_equity).toFixed(2)}</div>
          <div>Buying power: ${safeNumber(alpacaPaperBroker?.buying_power).toFixed(2)}</div>
          <div>Open positions: {safeNumber(alpacaPaperBroker?.open_positions_count).toFixed(0)}</div>
          <div>Open orders: {safeNumber(alpacaPaperBroker?.open_orders_count).toFixed(0)}</div>
          <div>Safety: {String(alpacaPaperBroker?.safety_status || "disabled_or_blocked").replaceAll("_", " ")}</div>
          <div>Last order: {String(alpacaPaperBroker?.last_order_status || "not_checked").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(alpacaPaperBroker?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Safety reasons: {(Array.isArray(alpacaPaperBroker?.safety_reasons) ? alpacaPaperBroker.safety_reasons : ["waiting_for_data"]).join(", ").replaceAll("_", " ")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Horizon Performance Dashboard</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "10px", fontSize: 12 }}>
          {[
            ["Scalp", horizonPerformanceDashboard?.scalp || {}],
            ["Day Trade", horizonPerformanceDashboard?.day_trade || {}],
            ["Swing Trade", horizonPerformanceDashboard?.swing_trade || {}],
          ].map(([label, metrics]) => (
            <div key={label} style={{ border: "1px solid rgba(124,154,201,0.35)", borderRadius: 10, padding: 10, background: "rgba(7,20,38,0.32)" }}>
              <div style={{ color: "#dce7ff", fontWeight: 700, marginBottom: 6 }}>{label}</div>
              <div>Entries today: {safeNumber(metrics?.entries_today).toFixed(0)}</div>
              <div>Exits today: {safeNumber(metrics?.exits_today).toFixed(0)}</div>
              <div>Open positions: {safeNumber(metrics?.open_positions).toFixed(0)}</div>
              <div>Win rate: {safeNumber(metrics?.win_rate).toFixed(1)}%</div>
              <div>Average return: {safeNumber(metrics?.average_return_pct).toFixed(2)}%</div>
              <div>Average hold: {safeNumber(metrics?.average_hold_time_hours, metrics?.average_hold_time).toFixed(2)}h</div>
              <div>Fill quality: {safeNumber(metrics?.broker_fill_quality, 100).toFixed(1)}</div>
              <div>Slippage: {safeNumber(metrics?.average_slippage_bps).toFixed(1)} bps</div>
              <div>Rejected orders: {safeNumber(metrics?.rejected_orders).toFixed(0)}</div>
              <div>Natural exits: {safeNumber(metrics?.natural_exit_count).toFixed(0)}</div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Best horizon: {String(horizonPerformanceDashboard?.best_current_horizon || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Weakest horizon: {String(horizonPerformanceDashboard?.weakest_current_horizon || "waiting_for_data").replaceAll("_", " ")}</div>
          <div>Natural exits preserved: {horizonPerformanceDashboard?.natural_exit_preserved === false ? "no" : "yes"}</div>
          <div>API calls used: {safeNumber(horizonPerformanceDashboard?.api_calls_used).toFixed(0)}</div>
          <div style={{ gridColumn: "1 / -1", color: "#b8c7e6" }}>
            Summary: {String(horizonPerformanceDashboard?.overall_horizon_summary || "Waiting for horizon performance diagnostics.")}
          </div>
        </div>
      </div>

      <div style={{ ...panelStyle, padding: "10px 12px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "10px" }}>
        <div style={{ fontSize: 12, color: "#9fb1cc" }}>
          Advanced learning diagnostics are available below when needed.
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
          {showAdvancedSections ? "Hide Advanced Details" : "Show Advanced Details"}
        </button>
      </div>

      {showAdvancedSections ? (
      <>
      <div style={{ ...panelStyle }}>
        <h3 style={{ marginTop: 0 }}>Portfolio & Risk Intelligence Suite V1</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "8px", fontSize: 12 }}>
          <div>Average position size: {safeNumber(portfolioRiskIntel?.average_recommended_position_size_pct).toFixed(1)}%</div>
          <div>Average portfolio risk: {safeNumber(portfolioRiskIntel?.average_portfolio_risk_score).toFixed(1)}</div>
          <div>Average capital allocation: {safeNumber(portfolioRiskIntel?.average_capital_allocation_score).toFixed(1)}</div>
          <div>Highest correlation risk: {safeNumber(portfolioRiskIntel?.highest_correlation_risk).toFixed(1)}</div>
          <div>Highest concentration risk: {safeNumber(portfolioRiskIntel?.highest_concentration_risk).toFixed(1)}</div>
          <div>Candidates evaluated: {safeNumber(portfolioRiskIntel?.candidates_evaluated).toFixed(0)}</div>
          <div>Mode: {String(portfolioRiskIntel?.mode || "shadow_only").replaceAll("_", " ")}</div>
          <div>API calls used: {safeNumber(portfolioRiskIntel?.api_calls_used).toFixed(0)}</div>
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
