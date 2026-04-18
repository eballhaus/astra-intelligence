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
  const change = formatPercent(item?.change_percent);
  const actionLabel = item?.grade ?? "N/A";
  const astraGrade = item?.astra_grade ?? item?.grade ?? item?.buy_grade ?? item?.qualification ?? item?.buy_eligibility ?? "N/A";
  const stopLoss = item?.stop_loss == null ? "n/a" : formatPrice(item.stop_loss);
  const timestamp = item?.timestamp ?? "n/a";
  const qualification = item?.buy_eligibility || "QUALIFIED";
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

  const summaryText = rationale || rankedActionExplanation || whyNotLiveReady || whatWouldUpgrade || nearThresholdBlocker || "Remote monitor card";
  const intelligenceText = String(
    item?.astra_intelligence_note
      || item?.ollama_buy_explanation
      || item?.user_buy_summary
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
            <div style={rowStyle}><span style={labelStyle}>Price</span><span style={valueStyle}>{price}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Change</span><span style={{ ...valueStyle, color: Number(item?.change_percent) >= 0 ? "#24995f" : "#b14450" }}>{change}</span></div>
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
              <span style={{ ...labelStyle, fontSize: "0.66rem", color: "#3a567e", fontWeight: 700 }}>Astra Grade</span>
              <span style={{ ...valueStyle, fontSize: "0.82rem", fontWeight: 800, color: "#16365f" }}>{astraGrade}</span>
            </div>
            <div style={rowStyle}><span style={labelStyle}>Action Label</span><span style={valueStyle}>{actionLabel}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Quality</span><span style={{ ...valueStyle, color: qualityColor(qualityScore) }}>{qualityText}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Stop</span><span style={valueStyle}>{stopLoss}</span></div>
            <div style={rowStyle}><span style={labelStyle}>Status</span><span style={valueStyle}>{releaseStatus}</span></div>
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
          <div style={{ ...labelStyle, color: "#3f5f8b" }}>Qualification: {qualification}</div>
          {canonicalState ? <div style={{ ...labelStyle, color: "#3f5f8b" }}>Canonical state: {canonicalState.replaceAll("_", " ")}</div> : null}
          <div style={{ fontSize: "0.7rem", lineHeight: 1.35, color: "#3a5375" }}>
            <strong style={{ color: "#27456d" }}>Rationale:</strong> {summaryText.slice(0, 110)}
          </div>
          {intelligenceText ? (
            <div
              style={{
                fontSize: "0.7rem",
                lineHeight: 1.32,
                color: "#294364",
                background: "#f1f7ff",
                border: "1px solid #cfe0f5",
                borderRadius: "9px",
                padding: "0.34rem 0.45rem",
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              <strong style={{ color: "#1f3d67" }}>Astra Intelligence:</strong>{" "}
              {intelligenceText.slice(0, 150)}
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
                fontSize: "0.74rem",
                lineHeight: 1.32,
                color: "#294364",
                background: "#f1f7ff",
                border: "1px solid #cfe0f5",
                borderRadius: "9px",
                padding: "0.34rem 0.45rem",
                overflow: "hidden",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
              }}
            >
              <strong style={{ color: "#1f3d67" }}>Astra Intelligence:</strong>{" "}
              {(positionNote || summaryText).slice(0, 160)}
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
