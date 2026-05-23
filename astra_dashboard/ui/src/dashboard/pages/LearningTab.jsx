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
  const [endpointStatus, setEndpointStatus] = useState({});
  const [timeline, setTimeline] = useState([]);
  const [data, setData] = useState({
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
          fetchJson("learning_snapshot_fast_v1", "/api/learning_snapshot_fast_v1", {}, { timeoutMs: 6000 }),
          fetchJson("paper_performance", "/api/paper_performance", {}, { timeoutMs: 12000 }),
          fetchJson("paper_status", "/api/paper_status", {}, { timeoutMs: 10000 }),
        ]);
        fastResults.push(...primaryBatch);

        const secondaryBatch = await Promise.all([
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
          fetchJson("market_session_execution_timing", "/api/market_session_execution_timing_status_v1", {}, { timeoutMs: 8000 }),
          fetchJson("paper_opportunity_allocation", "/api/paper_opportunity_allocation_status_v1", {}, { timeoutMs: 8000 }),
          fetchJson("learning_insights", "/api/learning_insights", {}, { timeoutMs: 25000 }),
        ]);
        secondaryResults.push(...secondaryBatch);
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
  }, [resolvedApiBase]);

  const paper = data.paper || {};
  const paperStatus = data.paperStatus || {};
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
