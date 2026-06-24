import React from "react";

const cardBaseStyle = {
  background: "#ffffff",
  border: "1px solid #d8e1ee",
  borderRadius: "14px",
  padding: "10px",
  boxShadow: "0 8px 18px rgba(8, 20, 40, 0.12)",
  display: "grid",
  gap: "6px",
  color: "#15263f",
};

const rowStyle = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: "8px",
};

const labelStyle = {
  color: "#5f728d",
  fontSize: "0.7rem",
  letterSpacing: "0.01em",
};

const valueStyle = {
  color: "#1a2a42",
  fontSize: "0.78rem",
  fontWeight: 600,
};

const progressTrackStyle = {
  height: "7px",
  background: "#e7edf5",
  borderRadius: "999px",
  overflow: "hidden",
};

const intelligenceBoxStyle = {
  color: "#294364",
  background: "#f1f7ff",
  border: "1px solid #cfe0f5",
  borderRadius: "9px",
  padding: "0.34rem 0.45rem",
};

const intelligenceScrollStyle = {
  overflowY: "auto",
  paddingRight: "2px",
  whiteSpace: "normal",
  wordBreak: "break-word",
};

function formatPrice(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "$0.00";
  return `$${num.toFixed(2)}`;
}

function formatPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0.00%";
  const sign = num > 0 ? "+" : "";
  return `${sign}${num.toFixed(2)}%`;
}

function scoreOrNull(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function formatConviction(value) {
  const n = scoreOrNull(value);
  return n == null ? "n/a" : n.toFixed(1);
}

function formatPredictionUsd(value) {
  const n = scoreOrNull(value);
  if (n == null) return "$n/a";
  return `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;
}

function symbolBadge(symbol) {
  const text = String(symbol || "?").slice(0, 3).toUpperCase();
  return text;
}

function qualityColor(score) {
  const n = Number(score || 0);
  if (n >= 85) return "#24995f";
  if (n >= 70) return "#2f6fc9";
  if (n >= 55) return "#ad7b2c";
  return "#b14450";
}

function fmtValue(value, fallback = "n/a", digits = 1) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(digits) : fallback;
}

export default function TickerCard({
  item,
  context = "default",
  compact = false,
  onAddPosition,
  positionState = "idle",
  onRemovePosition,
  removeState = "idle",
}) {
  const isTopBuy = context === "top-buy";
  const isPosition = context === "position";
  const canonicalState = String(item?.canonical_final_state || item?.canonical_release_state || "").toLowerCase();
  const canonicalActionLabel = canonicalState === "released_buy"
    ? "Released Buy"
    : canonicalState === "paper_ready"
    ? "Paper Ready"
    : canonicalState === "watchlist"
    ? "Watchlist"
    : canonicalState === "rejected"
    ? "Blocked"
    : "";

  const symbol = item?.symbol ?? "N/A";
  const action = isTopBuy
    ? (canonicalActionLabel || item?.top_buy_action || item?.action || "Buy")
    : (isPosition ? (item?.status ?? item?.position_status ?? "Open") : (item?.action ?? item?.prediction ?? "N/A"));

  const price = formatPrice(item?.price);
  const actionLabel = item?.grade ?? "N/A";
  const astraGrade = item?.astra_grade ?? item?.grade ?? item?.buy_grade ?? item?.qualification ?? item?.buy_eligibility ?? "N/A";
  const stopLoss = item?.stop_loss == null ? "n/a" : formatPrice(item.stop_loss);
  const timestamp = item?.timestamp ?? "n/a";
  const qualification = item?.buy_eligibility || "QUALIFIED";
  const fallbackCandidate = Boolean(item?.dashboard_fallback_candidate);
  const rationale = String(item?.why_this_is_a_buy || item?.why_made_list || "").trim();
  const nearThresholdBlocker = String(item?.primary_promotion_blocker || "").trim();
  const deploymentStatus = String(item?.hero_card_deployment_label || item?.hero_deployment_status || "paper-ready").toLowerCase();
  const whyNotLiveReady = String(item?.why_not_live_ready || "").trim();
  const whatWouldUpgrade = String(item?.what_would_upgrade_this || item?.what_would_promote_this_to_buy || "").trim();
  const rankedActionExplanation = String(item?.ranked_universe_action_explanation || "").trim();

  const confidenceRaw = Number(item?.confidence);
  const confidence = Number.isFinite(confidenceRaw) ? Math.max(0, Math.min(100, confidenceRaw)) : 0;
  const confidenceColor = confidence >= 80 ? "#24995f" : confidence >= 60 ? "#ad7b2c" : "#b14450";
  const qualityScore = Number(item?.buy_quality_score ?? item?.trade_quality_score ?? item?.final_action_score ?? item?.grade_percent ?? 0);
  const qualityText = Number.isFinite(qualityScore) ? `${qualityScore.toFixed(1)}` : "n/a";
  const releaseStatus = canonicalActionLabel || String(item?.hero_deployment_status || item?.hero_card_deployment_label || "watchlist").replaceAll("_", " ");
  const releaseStatusLower = String(releaseStatus || "").toLowerCase();
  const predictionPctRaw = scoreOrNull(item?.profit_prediction_pct ?? item?.expected_move_pct ?? item?.expected_move_percent ?? item?.predicted_return_pct);
  const predictionUsdRaw = scoreOrNull(item?.profit_prediction_usd ?? item?.expected_move_dollars ?? item?.expected_move_usd ?? item?.predicted_profit_dollars);
  const predictionText = `${formatPredictionUsd(predictionUsdRaw)} / ${predictionPctRaw == null ? "n/a" : formatPercent(predictionPctRaw)}`;
  const conviction10 = scoreOrNull(item?.rolling_conviction_10r ?? item?.conviction_display_score);
  const conviction5 = scoreOrNull(item?.rolling_conviction_5r);
  const conviction20 = scoreOrNull(item?.rolling_conviction_20r);
  const isPaperReady = releaseStatusLower.includes("paper ready") || releaseStatusLower.includes("released buy");
  const isWatchOrMonitor = releaseStatusLower.includes("watchlist") || releaseStatusLower.includes("monitor");
  const statusToneBg = isPaperReady ? "#e7f7ee" : isWatchOrMonitor ? "#fef4e4" : "#e8effa";
  const statusToneColor = isPaperReady ? "#1f8b53" : isWatchOrMonitor ? "#a67418" : "#22497d";

  const summaryText = rationale || rankedActionExplanation || whyNotLiveReady || whatWouldUpgrade || nearThresholdBlocker || "Remote monitor card";
  const primaryDriver = String(item?.primary_driver || item?.setup || item?.archetype || summaryText || "setup quality and participation").trim();
  const catalystTheme = String(item?.catalyst || item?.theme || item?.sector || "Cached catalyst context is developing").trim();
  const marketFit = String(item?.market_fit || item?.market_regime || item?.regime || "Best when participation and follow-through remain supportive").trim();
  const expectedHorizon = String(item?.best_horizon_style || item?.best_profit_horizon || item?.trade_horizon_style || item?.horizon || "Warming up").replaceAll("_", " ");
  const mainRisk = String(item?.portfolio_risk_label || item?.risk_label || "Volatility and follow-through uncertainty").replaceAll("_", " ");
  const invalidation = String(item?.invalidation || item?.invalidation_reason || item?.what_would_invalidate || "Momentum, catalyst support, or market participation weakens").trim();
  const intelligenceText = String(
    item?.ollama_buy_explanation
      || item?.ollama_explanation
      || item?.astra_intelligence_note
      || item?.user_buy_summary
      || item?.ollama_expected_move_summary
      || item?.why_this_is_a_buy
      || item?.buy_reason
      || summaryText
      || ""
  ).trim();

  const entryPriceText = formatPrice(item?.entry_price ?? item?.avg_entry_price ?? item?.average_entry_price);
  const currentPriceText = formatPrice(item?.current_price ?? item?.price ?? item?.mark_price);
  const pnlPctRaw = Number(item?.pnl_percent ?? item?.unrealized_pnl_percent ?? item?.pnl_pct ?? 0);
  const pnlPctText = Number.isFinite(pnlPctRaw) ? `${pnlPctRaw >= 0 ? "+" : ""}${pnlPctRaw.toFixed(2)}%` : "0.00%";
  const positionNote = String(item?.management_note || item?.position_note || item?.sell_note || item?.rationale || "").trim();
  const recommendedPositionSizeText = Number.isFinite(Number(item?.recommended_position_size_pct))
    ? `${Number(item.recommended_position_size_pct).toFixed(1)}%`
    : "n/a";
  const portfolioRiskScoreText = `${fmtValue(item?.portfolio_risk_score)} (${String(item?.portfolio_risk_label || "n/a").replaceAll("_", " ")})`;
  const capitalAllocationText = `${fmtValue(item?.capital_allocation_score)} (${String(item?.capital_allocation_label || "n/a").replaceAll("_", " ")})`;
  const correlationRiskText = `${fmtValue(item?.correlation_risk_score)} (${String(item?.correlation_risk_label || "n/a").replaceAll("_", " ")})`;
  const concentrationRiskText = `${fmtValue(item?.concentration_score)} (${String(item?.concentration_label || "n/a").replaceAll("_", " ")})`;
  const drawdownRiskText = `${fmtValue(item?.drawdown_risk_score)} (${String(item?.drawdown_risk_label || "n/a").replaceAll("_", " ")})`;
  const portfolioRiskSummaryText = String(item?.portfolio_risk_summary || "Portfolio risk diagnostics unavailable.");
  const bestHorizonStyleText = String(item?.best_horizon_style || item?.trade_horizon_style || "n/a").replaceAll("_", " ");
  const horizonSummaryText = String(item?.horizon_style_summary || "Multi-horizon paper diagnostics unavailable.");
  const aggressiveProfitScoreText = fmtValue(item?.aggressive_profit_score);
  const riskAdjustedProfitScoreText = fmtValue(item?.risk_adjusted_profit_score);
  const bestProfitHorizonText = String(item?.best_profit_horizon || "n/a").replaceAll("_", " ");
  const highProfitCandidateText = item?.high_profit_candidate === true ? "yes" : item?.high_profit_candidate === false ? "no" : "n/a";
  const profitOptimizationSummaryText = String(item?.profit_optimization_summary || "Profit optimization diagnostics unavailable.");

  const actionText = positionState === "working" ? "Adding..." : positionState === "added" ? "Added" : positionState === "failed" ? "Retry Add" : "Add to Positions";
  const removeText = removeState === "working" ? "Removing..." : removeState === "failed" ? "Retry Remove" : "Remove";

  return (
    <article style={{ ...cardBaseStyle, padding: compact ? "9px" : "10px" }}>
      <div style={rowStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "999px",
              background: "linear-gradient(180deg, #2b6ccf 0%, #1c4a96 100%)",
              color: "#f5f9ff",
              display: "grid",
              placeItems: "center",
              fontSize: "0.64rem",
              fontWeight: 700,
              letterSpacing: "0.03em",
            }}
          >
            {symbolBadge(symbol)}
          </div>
          <div>
            <div style={{ color: "#12243a", fontSize: "0.9rem", fontWeight: 800, lineHeight: 1.1 }}>{symbol}</div>
            <div style={{ ...labelStyle, fontSize: "0.64rem" }}>{timestamp}</div>
          </div>
        </div>
        <div style={{ display: "grid", gap: "4px", justifyItems: "end" }}>
          <div
            style={{
              fontSize: "0.64rem",
              fontWeight: 700,
              padding: "3px 8px",
              borderRadius: "999px",
              background: "#e8effa",
              color: "#22497d",
              textTransform: "uppercase",
            }}
          >
            {action}
          </div>
          {isTopBuy ? (
            <div
              style={{
                fontSize: "0.6rem",
                fontWeight: 700,
                padding: "2px 7px",
                borderRadius: "999px",
                background:
                  deploymentStatus === "live-ready"
                    ? "#e7f7ee"
                    : deploymentStatus === "paper-ready"
                    ? "#e7effa"
                    : deploymentStatus === "monitor-only"
                    ? "#fef4e4"
                    : "#fde9ec",
                color:
                  deploymentStatus === "live-ready"
                    ? "#1f8b53"
                    : deploymentStatus === "paper-ready"
                    ? "#2b6ccf"
                    : deploymentStatus === "monitor-only"
                    ? "#a67418"
                    : "#b83a48",
                textTransform: "uppercase",
              }}
            >
              {deploymentStatus}
            </div>
          ) : null}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "5px 8px" }}>
        {isPosition ? (
          <>
            <div style={rowStyle}><span style={labelStyle}>Entry</span><span style={valueStyle}>{entryPriceText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Current</span><span style={valueStyle}>{currentPriceText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>PnL</span><span style={{ ...valueStyle, color: pnlPctRaw >= 0 ? "#24995f" : "#b14450" }}>{pnlPctText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Quality</span><span style={{ ...valueStyle, color: qualityColor(qualityScore) }}>{qualityText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Astra Grade</span><span style={{ ...valueStyle, fontWeight: 800 }}>{astraGrade}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Stop</span><span style={valueStyle}>{stopLoss}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Status</span><span style={valueStyle}>{action}</span></div>
          </>
        ) : (
          <>
            <div style={rowStyle}><span style={labelStyle}>Status</span><span style={{ ...valueStyle, color: statusToneColor }}>{releaseStatus}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Grade</span><span style={{ ...valueStyle, fontWeight: 800 }}>{astraGrade}</span></div>
            <div
              style={{
                gridColumn: "1 / -1",
                border: "1px solid #d8e2f0",
                borderRadius: "9px",
                background: "#f7faff",
                padding: "0.28rem 0.45rem",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span style={{ ...labelStyle, fontSize: "0.66rem", color: "#3a567e", fontWeight: 700 }}>Consistency</span>
              <span style={{ ...valueStyle, fontSize: "0.82rem", fontWeight: 800, color: "#16365f" }}>{formatConviction(conviction10)}</span>
            </div>
            <div style={rowStyle}><span style={labelStyle}>Quality</span><span style={{ ...valueStyle, color: qualityColor(qualityScore) }}>{qualityText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Candidate Type</span><span style={valueStyle}>{action}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Profit Prediction</span><span style={valueStyle}>{predictionText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Stop</span><span style={valueStyle}>{stopLoss}</span></div>
          </>
        )}
      </div>

      <div style={{ display: "grid", gap: "4px" }}>
        <div style={rowStyle}><span style={labelStyle}>Confidence</span><span style={{ ...valueStyle, fontSize: "0.74rem" }}>{`${confidence.toFixed(1)}%`}</span></div>
        <div style={progressTrackStyle}>
          <div
            style={{
              width: `${confidence}%`,
              height: "100%",
              background: confidenceColor,
              transition: "width 180ms ease-out",
            }}
          />
        </div>
      </div>

      {isTopBuy ? (
        <div style={{ display: "grid", gap: "4px", marginTop: "1px" }}>
          <div style={{ ...labelStyle, color: "#3f5f8b" }}>Candidate status: {qualification}</div>
          {item?.conviction_window_status ? (
            <div style={{ ...labelStyle, color: "#3f5f8b" }}>
              Evidence window: {String(item.conviction_window_status).replaceAll("_", " ")}
            </div>
          ) : null}
          {fallbackCandidate ? (
            <div style={{ ...labelStyle, color: "#6d5a2b" }}>
              Display mode: candidate fallback
            </div>
          ) : null}
          {canonicalState ? <div style={{ ...labelStyle, color: "#3f5f8b" }}>Astra status: {canonicalState.replaceAll("_", " ")}</div> : null}
          <div style={{ fontSize: "0.7rem", lineHeight: 1.35, color: "#3a5375" }}>
            <strong style={{ color: "#27456d" }}>Why Astra likes it:</strong> {summaryText.slice(0, 110)}
          </div>
          <div style={{ display: "grid", gap: 3, border: "1px solid #d8e2f0", borderRadius: 9, background: "#f7faff", padding: "0.4rem 0.48rem", fontSize: "0.66rem", color: "#4a6388" }}>
            <div><strong>Primary Driver:</strong> {primaryDriver.slice(0, 150)}</div>
            <div><strong>Catalyst / Theme:</strong> {catalystTheme.slice(0, 120)}</div>
            <div><strong>Market Fit:</strong> {marketFit.slice(0, 140)}</div>
            <div><strong>Expected Horizon:</strong> {expectedHorizon}</div>
            <div><strong>Main Risk:</strong> {mainRisk}</div>
            <div><strong>Invalidation:</strong> {invalidation.slice(0, 150)}</div>
          </div>
          <details style={{ border: "1px solid #d8e2f0", borderRadius: "8px", padding: "0.25rem 0.4rem", background: "#f8fbff" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.66rem", color: "#315078", fontWeight: 700 }}>View Details</summary>
            <div style={{ display: "grid", gap: "3px", marginTop: "4px", fontSize: "0.64rem", color: "#4a6388" }}>
              <div>5R Conviction: {formatConviction(conviction5)}</div>
              <div>20R Conviction: {formatConviction(conviction20)}</div>
              <div>Appearance 5R/10R/20R: {item?.appearance_count_5r ?? "n/a"} / {item?.appearance_count_10r ?? "n/a"} / {item?.appearance_count_20r ?? "n/a"}</div>
              <div>Avg Rank 10R: {item?.avg_rank_10r ?? "n/a"}</div>
              <div>Paper-ready Rate 10R: {item?.paper_ready_rate_10r == null ? "n/a" : `${Number(item.paper_ready_rate_10r).toFixed(2)}%`}</div>
              <div>Rank Stability 10R: {item?.rank_stability_10r ?? "n/a"}</div>
              <div>Window Status: {item?.conviction_window_status ?? "n/a"}</div>
              <div>Recommended Position Size: {recommendedPositionSizeText}</div>
              <div>Portfolio Risk Score: {portfolioRiskScoreText}</div>
              <div>Capital Allocation: {capitalAllocationText}</div>
              <div>Correlation Risk: {correlationRiskText}</div>
              <div>Concentration Risk: {concentrationRiskText}</div>
              <div>Drawdown Risk: {drawdownRiskText}</div>
              <div>Portfolio Risk Summary: {portfolioRiskSummaryText}</div>
              <div>Best Horizon Style: {bestHorizonStyleText}</div>
              <div>Scalp Fit: {fmtValue(item?.scalp_fit_score)}</div>
              <div>Day Trade Fit: {fmtValue(item?.day_trade_fit_score)}</div>
              <div>Swing Trade Fit: {fmtValue(item?.swing_trade_fit_score)}</div>
              <div>Horizon Summary: {horizonSummaryText}</div>
              <div>Aggressive Profit Score: {aggressiveProfitScoreText}</div>
              <div>Risk-Adjusted Profit Score: {riskAdjustedProfitScoreText}</div>
              <div>Best Profit Horizon: {bestProfitHorizonText}</div>
              <div>High-Profit Candidate: {highProfitCandidateText}</div>
              <div>Profit Optimization Summary: {profitOptimizationSummaryText}</div>
            </div>
          </details>
          {intelligenceText ? (
            <div
              style={{
                ...intelligenceBoxStyle,
                fontSize: "0.7rem",
                lineHeight: 1.32,
              }}
            >
              <strong style={{ color: "#1f3d67", display: "block", marginBottom: "2px" }}>Astra Intelligence:</strong>
              <div style={{ ...intelligenceScrollStyle, maxHeight: "56px" }}>
                {intelligenceText}
              </div>
            </div>
          ) : null}
          {deploymentStatus !== "live-ready" && whyNotLiveReady ? (
            <div style={{ ...labelStyle, color: "#b14a56" }}>
              Why not live-ready: {whyNotLiveReady.replaceAll("_", " ")}
            </div>
          ) : null}
          {deploymentStatus !== "live-ready" && whatWouldUpgrade ? (
            <div style={{ ...labelStyle, color: "#4a6388" }}>
              Upgrade path: {whatWouldUpgrade.replaceAll("_", " ")}
            </div>
          ) : null}
          {nearThresholdBlocker && nearThresholdBlocker !== "none" ? (
            <div style={{ ...labelStyle, color: "#b14a56" }}>
              Near-threshold blocker: {nearThresholdBlocker.replaceAll("_", " ")}
            </div>
          ) : null}
          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            {typeof onAddPosition === "function" ? (
              <button
                type="button"
                onClick={() => onAddPosition(item)}
                disabled={positionState === "working" || positionState === "added"}
                style={{
                  border: "1px solid #2a63b6",
                  background: "linear-gradient(180deg, #2d73cf 0%, #225da8 100%)",
                  color: "#f5f9ff",
                  borderRadius: "8px",
                  padding: "0.3rem 0.55rem",
                  fontSize: "0.64rem",
                  fontWeight: 700,
                  cursor: positionState === "working" ? "wait" : "pointer",
                }}
              >
                {actionText}
              </button>
            ) : null}
          </div>
        </div>
      ) : (
        isPosition ? (
          <div style={{ display: "grid", gap: "6px" }}>
            <div
              style={{
                ...intelligenceBoxStyle,
                fontSize: "0.74rem",
                lineHeight: 1.32,
              }}
            >
              <strong style={{ color: "#1f3d67", display: "block", marginBottom: "2px" }}>Astra Intelligence:</strong>
              <div style={{ ...intelligenceScrollStyle, maxHeight: "62px" }}>
                {positionNote || summaryText}
              </div>
            </div>
            {typeof onRemovePosition === "function" ? (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  onClick={() => onRemovePosition(item)}
                  disabled={removeState === "working"}
                  style={{
                    border: "1px solid #b34b57",
                    background: "linear-gradient(180deg, #c35b66 0%, #9e3e48 100%)",
                    color: "#fff7f8",
                    borderRadius: "8px",
                    padding: "0.3rem 0.55rem",
                    fontSize: "0.64rem",
                    fontWeight: 700,
                    cursor: removeState === "working" ? "wait" : "pointer",
                  }}
                >
                  {removeText}
                </button>
              </div>
            ) : null}
          </div>
        ) : rankedActionExplanation ? (
          <div style={{ ...labelStyle, color: "#4a6388" }}>
            Note: {rankedActionExplanation}
          </div>
        ) : null
      )}
    </article>
  );
}
