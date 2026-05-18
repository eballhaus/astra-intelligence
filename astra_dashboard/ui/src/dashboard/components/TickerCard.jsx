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
  if (!Number.isFinite(num)) return "n/a";
  return `$${num.toFixed(2)}`;
}

function formatPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "n/a";
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
  if (n == null || Math.abs(n) < 0.005) return "n/a";
  return `${n >= 0 ? "+" : "-"}$${Math.abs(n).toFixed(2)}`;
}

function formatTargetZone(item) {
  const explicit = String(item?.target_zone_display || "").trim();
  if (explicit && !explicit.includes("n/a") && !explicit.includes("$0.00")) return explicit;
  const low = scoreOrNull(item?.target_zone_low ?? item?.target_1 ?? item?.expected_target_low);
  const high = scoreOrNull(item?.target_zone_high ?? item?.stretch_target ?? item?.expected_target_high);
  if (low != null && high != null && low > 0 && high > 0) return `$${low.toFixed(2)}-${high.toFixed(2)}`;
  return "n/a";
}

function qualityColor(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "#6a7b90";
  if (n >= 85) return "#24995f";
  if (n >= 70) return "#2f6fc9";
  if (n >= 55) return "#ad7b2c";
  return "#b14450";
}

function scoreLabel(score) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "Calculating";
  if (n >= 75) return "Strong";
  if (n >= 60) return "Good";
  if (n >= 45) return "Watch";
  return "Weak";
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

  const symbol = String(item?.symbol ?? item?.ticker ?? "N/A").toUpperCase();
  const rank = Number(item?.top_6_rank);
  const rankLabel = Number.isFinite(rank) && rank > 0 ? `#${rank}` : "#";
  const action = isTopBuy
    ? (item?.action_label || item?.top_buy_action || item?.action || "Buy")
    : (isPosition ? (item?.status ?? item?.position_status ?? "Open") : (item?.action ?? item?.prediction ?? "N/A"));

  const price = formatPrice(item?.price);
  const companyName = String(item?.company_name || item?.name || item?.security_name || symbol).trim();
  const actionLabel = item?.grade ?? "N/A";
  const astraGrade = item?.astra_grade ?? item?.grade ?? item?.buy_grade ?? item?.qualification ?? item?.buy_eligibility ?? "N/A";
  const stopLoss = item?.stop_loss == null ? "n/a" : formatPrice(item.stop_loss);
  const timestamp = item?.timestamp ?? "n/a";
  const qualification = item?.buy_eligibility || "QUALIFIED";
  const fallbackCandidate = Boolean(item?.dashboard_fallback_candidate);
  const stableState = String(item?.stable_layer_state || item?.stable_display_state || "").replaceAll("_", " ").trim();
  const rationale = String(item?.why_this_is_a_buy || item?.why_made_list || "").trim();
  const nearThresholdBlocker = String(item?.primary_promotion_blocker || "").trim();
  const deploymentStatus = String(item?.hero_card_deployment_label || item?.hero_deployment_status || "paper-ready").toLowerCase();
  const whyNotLiveReady = String(item?.why_not_live_ready || "").trim();
  const whatWouldUpgrade = String(item?.what_would_upgrade_this || item?.what_would_promote_this_to_buy || "").trim();
  const rankedActionExplanation = String(item?.ranked_universe_action_explanation || "").trim();

  const confidenceRaw = Number(item?.confidence);
  const confidence = Number.isFinite(confidenceRaw) ? Math.max(0, Math.min(100, confidenceRaw)) : null;
  const confidenceColor = confidence == null ? "#6a7b90" : confidence >= 80 ? "#24995f" : confidence >= 60 ? "#ad7b2c" : "#b14450";
  const qualityScore = scoreOrNull(item?.buy_quality_score ?? item?.trade_quality_score ?? item?.final_action_score ?? item?.grade_percent);
  const qualityText = qualityScore == null ? "calculating" : `${qualityScore.toFixed(1)}`;
  const readinessLabel = item?.readiness_label || canonicalActionLabel || String(item?.hero_deployment_status || item?.hero_card_deployment_label || "watchlist").replaceAll("_", " ");
  const releaseStatus = readinessLabel;
  const releaseStatusLower = String(releaseStatus || "").toLowerCase();
  const predictionPctRaw = scoreOrNull(item?.expected_move_percent ?? item?.profit_prediction_pct ?? item?.expected_move_pct ?? item?.expected_move_percent ?? item?.predicted_return_pct);
  const predictionUsdRaw = scoreOrNull(item?.expected_move ?? item?.profit_prediction_usd ?? item?.expected_move_dollars ?? item?.expected_move_usd ?? item?.predicted_profit_dollars);
  const hasExpectedMove = (predictionUsdRaw != null && Math.abs(predictionUsdRaw) >= 0.005) || (predictionPctRaw != null && Math.abs(predictionPctRaw) >= 0.005);
  const predictionText = hasExpectedMove ? `${formatPredictionUsd(predictionUsdRaw)} / ${predictionPctRaw == null ? "n/a" : formatPercent(predictionPctRaw)}` : "calculating";
  const conviction10 = scoreOrNull(item?.conviction_10r ?? item?.rolling_conviction_10r ?? item?.conviction_display_score);
  const conviction5 = scoreOrNull(item?.conviction_5r ?? item?.rolling_conviction_5r);
  const conviction20 = scoreOrNull(item?.conviction_20r ?? item?.rolling_conviction_20r);
  const isPaperReady = releaseStatusLower.includes("paper ready") || releaseStatusLower.includes("released buy");
  const isWatchOrMonitor = releaseStatusLower.includes("watchlist") || releaseStatusLower.includes("monitor");
  const statusToneBg = isPaperReady ? "#e7f7ee" : isWatchOrMonitor ? "#fef4e4" : "#e8effa";
  const statusToneColor = isPaperReady ? "#1f8b53" : isWatchOrMonitor ? "#a67418" : "#22497d";

  const summaryText = rationale || rankedActionExplanation || whyNotLiveReady || whatWouldUpgrade || nearThresholdBlocker || "Remote monitor card";
  const intelligenceText = String(
    item?.ai_card_explanation_v2
      || item?.card_explanation_v2
      || item?.ollama_buy_explanation
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
  const currentPriceText = formatPrice(item?.current_price ?? item?.price ?? item?.live_price ?? item?.last_price ?? item?.close ?? item?.mark_price);
  const astraScore = scoreOrNull(item?.astra_composite_score ?? item?.stability_score ?? item?.stable_composite_score);
  const astraScoreText = astraScore == null ? "calculating" : `${Math.max(0, Math.min(100, astraScore)).toFixed(0)}/100`;
  const opportunityScore = scoreOrNull(item?.opportunity_score_pct ?? item?.profit_priority_score);
  const opportunityGrade = String(item?.opportunity_grade || "").trim();
  const opportunityText = opportunityScore == null
    ? "calculating"
    : `${opportunityGrade || scoreLabel(opportunityScore)}, ${opportunityScore.toFixed(0)}%`;
  const opportunityColor = qualityColor(opportunityScore);
  const targetZoneText = formatTargetZone(item);
  const expectedReturnText = item?.expected_return_pct == null ? "n/a" : formatPercent(item.expected_return_pct);
  const rewardRiskText = item?.estimated_reward_to_risk == null ? "n/a" : `${Number(item.estimated_reward_to_risk).toFixed(2)}R`;
  const exitScoreText = item?.averaged_exit_score == null ? "n/a" : `${Number(item.averaged_exit_score).toFixed(1)}`;
  const rankStableText = stableState || (scoreOrNull(item?.stable_age_seconds) ? "stable" : "new");
  const confidenceText = confidence == null ? "calculating" : `${confidence.toFixed(1)}%`;
  const pnlPctRaw = Number(item?.pnl_percent ?? item?.unrealized_pnl_percent ?? item?.pnl_pct ?? 0);
  const pnlPctText = Number.isFinite(pnlPctRaw) ? `${pnlPctRaw >= 0 ? "+" : ""}${pnlPctRaw.toFixed(2)}%` : "0.00%";
  const positionNote = String(item?.management_note || item?.position_note || item?.sell_note || item?.rationale || "").trim();

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
              background: "linear-gradient(180deg, #112d52 0%, #1f6ac8 100%)",
              color: "#f5f9ff",
              display: "grid",
              placeItems: "center",
              fontSize: "0.7rem",
              fontWeight: 900,
              letterSpacing: "0.03em",
            }}
          >
            {isTopBuy ? rankLabel : symbol.slice(0, 3)}
          </div>
          <div>
            <div style={{ color: "#12243a", fontSize: "0.9rem", fontWeight: 800, lineHeight: 1.1 }}>{symbol}</div>
            <div style={{ ...labelStyle, fontSize: "0.64rem" }}>{companyName}</div>
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
            <div style={rowStyle}><span style={labelStyle}>Current Price</span><span style={valueStyle}>{currentPriceText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Readiness</span><span style={{ ...valueStyle, color: statusToneColor }}>{releaseStatus}</span></div>
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
              <span style={{ ...labelStyle, fontSize: "0.66rem", color: "#3a567e", fontWeight: 700 }}>Opportunity</span>
              <span style={{ ...valueStyle, fontSize: "0.82rem", fontWeight: 900, color: opportunityColor }}>{opportunityText}</span>
            </div>
            <div style={rowStyle}><span style={labelStyle}>Confidence</span><span style={{ ...valueStyle, color: confidenceColor }}>{confidenceText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Stop</span><span style={valueStyle}>{stopLoss}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Target</span><span style={{ ...valueStyle, fontWeight: 800 }}>{targetZoneText}</span></div>
          </>
        )}
      </div>

      <div style={{ display: "grid", gap: "4px" }}>
        <div style={rowStyle}><span style={labelStyle}>Confidence</span><span style={{ ...valueStyle, fontSize: "0.74rem" }}>{confidenceText}</span></div>
        <div style={progressTrackStyle}>
          <div
            style={{
              width: `${confidence == null ? 0 : confidence}%`,
              height: "100%",
              background: confidenceColor,
              transition: "width 180ms ease-out",
            }}
          />
        </div>
      </div>

      {isTopBuy ? (
        <div style={{ display: "grid", gap: "4px", marginTop: "1px" }}>
          <div style={{ ...labelStyle, color: "#3f5f8b" }}>Qualification: {qualification}</div>
          {item?.conviction_window_status ? (
            <div style={{ ...labelStyle, color: "#3f5f8b" }}>
              Conviction status: {String(item.conviction_window_status).replaceAll("_", " ")}
            </div>
          ) : null}
          {fallbackCandidate ? (
            <div style={{ ...labelStyle, color: "#6d5a2b" }}>
              Display mode: candidate fallback (not released-final)
            </div>
          ) : null}
          {stableState ? (
            <div style={{ ...labelStyle, color: "#2f6fc9", fontWeight: 700 }}>
              Stable layer: {stableState}
            </div>
          ) : null}
          {canonicalState ? <div style={{ ...labelStyle, color: "#3f5f8b" }}>Canonical state: {canonicalState.replaceAll("_", " ")}</div> : null}
          <div style={{ fontSize: "0.7rem", lineHeight: 1.35, color: "#3a5375" }}>
            <strong style={{ color: "#27456d" }}>Rationale:</strong> {summaryText.slice(0, 110)}
          </div>
          {Number(item?.top_6_rank) === 1 && item?.ranked_reason ? (
            <div style={{ ...intelligenceBoxStyle, background: "#fffaf0", borderColor: "#edd89f", fontSize: "0.68rem", color: "#654d18" }}>
              <strong>Why ranked #1:</strong> {item.ranked_reason}
            </div>
          ) : null}
          <details style={{ border: "1px solid #d8e2f0", borderRadius: "8px", padding: "0.25rem 0.4rem", background: "#f8fbff" }}>
            <summary style={{ cursor: "pointer", fontSize: "0.66rem", color: "#315078", fontWeight: 700 }}>Expanded Details</summary>
            <div style={{ display: "grid", gap: "3px", marginTop: "4px", fontSize: "0.64rem", color: "#4a6388" }}>
              <div>Quality: {qualityText}</div>
              <div>Astra Score: {astraScoreText} · {scoreLabel(astraScore)}</div>
              <div>Opportunity: {opportunityText}</div>
              <div>Expected Return: {expectedReturnText}</div>
              <div>Target 1: {item?.target_1 == null ? "n/a" : formatPrice(item.target_1)}</div>
              <div>Target 2: {item?.target_2 == null ? "n/a" : formatPrice(item.target_2)}</div>
              <div>Stretch Target: {item?.stretch_target == null ? "n/a" : formatPrice(item.stretch_target)}</div>
              <div>Reward-to-risk: {rewardRiskText}</div>
              <div>5R Conviction: {formatConviction(conviction5)}</div>
              <div>10R Conviction: {formatConviction(conviction10)}</div>
              <div>20R Conviction: {formatConviction(conviction20)}</div>
              <div>Entry Quality V3: {item?.entry_quality_v3_score ?? "n/a"}</div>
              <div>Exit Score: {exitScoreText} ({String(item?.pullback_vs_breakdown_label || "n/a").replaceAll("_", " ")})</div>
              <div>Trailing Stop: {item?.trailing_stop_price == null ? "n/a" : formatPrice(item.trailing_stop_price)}</div>
              <div>Sell Zone: {String(item?.recommended_sell_zone || "n/a").replaceAll("_", " ")}</div>
              <div>Multi-Brain Consensus: {item?.multi_brain_agreement ?? item?.multi_brain_score ?? "n/a"}</div>
              <div>Psychology Brain: {item?.psychology_score ?? "n/a"}</div>
              <div>Rank Stability: {rankStableText}</div>
              <div>Appearance 5R/10R/20R: {item?.appearance_count_5r ?? "n/a"} / {item?.appearance_count_10r ?? "n/a"} / {item?.appearance_count_20r ?? "n/a"}</div>
              <div>Average Rank: {item?.average_rank ?? item?.avg_rank_10r ?? "n/a"}</div>
              <div>Top 3 Persistence: {item?.time_in_top_3_seconds == null ? "n/a" : `${Math.round(Number(item.time_in_top_3_seconds) / 60)}m`}</div>
              <div>Paper-ready Rate 10R: {item?.paper_ready_rate_10r == null ? "n/a" : `${(Number(item.paper_ready_rate_10r) * 100).toFixed(0)}%`}</div>
              <div>Rank Stability 10R: {item?.rank_stability_10r ?? item?.rank_stability_score ?? "n/a"}</div>
              <div>Window Status: {item?.conviction_window_status ?? "n/a"}</div>
              {targetZoneText === "n/a" ? <div>Target unavailable: {item?.target_unavailable_reason || "insufficient target inputs"}</div> : null}
              <div>Benchmarks: Good 60+ · Strong 75+ · Elite 85+ for 10R, Entry Quality, Multi-Brain, Buy List Purity, and Confidence.</div>
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
              {item?.ai_card_explanation_v2 ? (
                <span style={{ color: "#517199", fontSize: "0.62rem", display: "block", marginBottom: "2px" }}>
                  Plain-English AI explanation
                </span>
              ) : null}
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
