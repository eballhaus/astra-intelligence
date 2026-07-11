import React, { useEffect, useMemo, useState } from "react";
import { fetchJsonWithFallback, getInitialApiBase } from "../../apiBase";
import "./CopilotPage.css";

const EMPTY_PAYLOAD = { recommendations: [], top_actions: [], status: "warming_up" };
let copilotRequest = null;

const ENTRY_STATES = new Set(["BUY_NOW_ADVISORY", "APPROACHING_BUY", "WATCH", "BLOCKED", "INSUFFICIENT_EVIDENCE", "NOT_READY"]);
const EXIT_STATES = new Set(["HOLD", "LOSING_MOMENTUM", "PROTECT_PROFIT", "APPROACHING_SELL", "SELL_RECOMMENDED", "INSUFFICIENT_EVIDENCE"]);

function loadCopilot() {
  if (!copilotRequest) {
    copilotRequest = fetchJsonWithFallback("/api/copilot_decision_command_v1", {
      preferredBase: getInitialApiBase(),
      fallbackValue: EMPTY_PAYLOAD,
      timeoutMs: 30000,
    }).then((result) => ({
      ok: result.ok,
      payload: result.ok && result.parsed ? result.parsed : EMPTY_PAYLOAD,
      error: result.error || "",
    }));
  }
  return copilotRequest;
}

function text(value, fallback = "Unavailable") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function present(value) {
  return value !== null && value !== undefined && value !== "" && !["UNAVAILABLE", "UNKNOWN", "UNRESOLVED", "N/A"].includes(String(value).toUpperCase());
}

function titleCase(value) {
  return text(value, "Unavailable").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function stateLabel(row) {
  return text(row?.canonical_lifecycle_state || row?.action, "INSUFFICIENT_EVIDENCE");
}

function stateClass(state) {
  return `copilot-state copilot-state-${String(state || "unknown").toLowerCase()}`;
}

function formatTimestamp(value) {
  if (!present(value)) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? text(value) : date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function displayValue(row, ...keys) {
  for (const key of keys) {
    if (present(row?.[key])) return row[key];
  }
  return null;
}

function arrayValue(row, ...keys) {
  for (const key of keys) {
    if (Array.isArray(row?.[key])) return row[key];
  }
  return [];
}

function historyItems(row) {
  return arrayValue(row, "recommendation_history", "history").slice(0, 12);
}

function changeItems(row) {
  return arrayValue(row, "what_changed", "change_history", "changes").slice(0, 12);
}

function rowSearchText(row) {
  return [row.symbol, row.company_name, row.company, row.asset_name, row.asset_type, row.asset_class].filter(present).join(" ").toLowerCase();
}

function Metric({ label, value, tone = "neutral", hint }) {
  return (
    <div className="copilot-metric">
      <span>{label}</span>
      <strong className={`copilot-metric-value copilot-tone-${tone}`}>{text(value)}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}

function StatusPill({ label, value, tone = "neutral" }) {
  return <div className={`copilot-status-pill copilot-pill-${tone}`}><span>{label}</span><strong>{text(value)}</strong></div>;
}

function ContextItem({ label, value }) {
  return <div className="copilot-context-item"><span>{label}</span><strong>{titleCase(value)}</strong></div>;
}

function CopilotHeader({ payload, rows, error }) {
  const attentionCount = rows.filter((row) => {
    const state = stateLabel(row);
    return ["LOSING_MOMENTUM", "PROTECT_PROFIT", "APPROACHING_SELL", "SELL_RECOMMENDED", "BLOCKED", "DATA_STALE", "INSUFFICIENT_EVIDENCE"].includes(state) || (row.blockers || []).length > 0;
  }).length;
  const first = rows[0] || {};
  return (
    <header className="copilot-command-header">
      <div>
        <div className="copilot-kicker">Astra Intelligence / Decision Command</div>
        <h1>Astra Copilot</h1>
        <p>Top actions Astra recommends right now. Advisory context only, sourced from the canonical Copilot contract.</p>
        <div className="copilot-summary-line">
          {error ? "Copilot is using its safe empty state while the backend reconnects." : rows.length ? `${rows.length} canonical recommendations are available for review.` : "No recommendations currently meet the available evidence requirements."}
        </div>
      </div>
      <div className="copilot-header-status">
        <StatusPill label="Backend" value={error ? "Error" : text(payload?.status, "Warming Up")} tone={error ? "danger" : "good"} />
        <StatusPill label="Needs attention" value={attentionCount} tone={attentionCount ? "warn" : "good"} />
        <StatusPill label="Freshness" value={text(first?.freshness, "Cached")} />
        <div className="copilot-updated">Last updated {formatTimestamp(payload?.generated_at)}</div>
      </div>
    </header>
  );
}

function MarketContextStrip({ rows }) {
  const row = rows[0] || {};
  const context = [
    ["Market regime", row.market_regime],
    ["Trade style", row.trade_style || row.horizon],
    ["Preferred horizon", row.preferred_horizon],
    ["Catalyst", row.catalyst_context],
    ["Breadth", row.breadth_context],
    ["Risk posture", row.risk_level],
  ];
  return (
    <section className="copilot-context-strip" aria-label="Market context">
      {context.map(([label, value]) => <ContextItem key={label} label={label} value={value} />)}
    </section>
  );
}

function FilterBar({ filter, onChange, rows, search, onSearch, onReset }) {
  const options = [
    ["ALL", "All"], ["OPPORTUNITIES", "Opportunities"], ["CURRENT_POSITIONS", "Positions"], ["NEEDS_ATTENTION", "Needs Attention"], ["EQUITIES", "Equities"], ["CRYPTO", "Crypto"],
    ["BUY_NOW", "Buy Now"], ["WATCH", "Watch"], ["HOLD", "Hold"], ["LOSING_MOMENTUM", "Losing Momentum"], ["PROTECT_PROFIT", "Protect Profit"],
    ["APPROACHING_BUY", "Approaching Buy"], ["APPROACHING_SELL", "Approaching Sell"], ["SELL_RECOMMENDED", "Sell Recommended"], ["PAPER_ELIGIBLE", "Paper Eligible"], ["BLOCKED", "Blocked"], ["INSUFFICIENT_EVIDENCE", "Insufficient Evidence"], ["STALE", "Stale"],
    ["DAY_TRADE", "Day Trade"], ["SHORT_SWING", "Short Swing"], ["STANDARD_SWING", "Standard Swing"],
  ];
  return (
    <div className="copilot-filter-bar" aria-label="Filter recommendations">
      <span className="copilot-filter-label">Filter</span>
      {options.map(([value, label]) => (
        <button key={value} type="button" className={filter === value ? "copilot-filter active" : "copilot-filter"} onClick={() => onChange(value)}>
          {label}<small>{value === "ALL" ? rows.length : ""}</small>
        </button>
      ))}
      <label className="copilot-search"><span className="sr-only">Search symbols</span><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search symbol or company" /></label>
      <button type="button" className="copilot-filter copilot-reset" onClick={onReset}>Reset</button>
    </div>
  );
}

function matchesFilter(row, filter) {
  const state = stateLabel(row);
  if (filter === "ALL") return true;
  if (filter === "OPPORTUNITIES") return ["BUY_NOW", "APPROACHING_BUY", "BUY_NOW_ADVISORY"].includes(state) || row.advisory_entry_state === "BUY_NOW_ADVISORY";
  if (filter === "CURRENT_POSITIONS") return row.position_state === "POSITION_OPEN";
  if (filter === "EQUITIES") return String(row.asset_class || row.asset_type || "").toLowerCase() === "equity" || String(row.asset_class || row.asset_type || "").toLowerCase() === "stock";
  if (filter === "CRYPTO") return String(row.asset_class || row.asset_type || "").toLowerCase() === "crypto";
  if (filter === "NEEDS_ATTENTION") return ["LOSING_MOMENTUM", "PROTECT_PROFIT", "APPROACHING_SELL", "SELL_RECOMMENDED", "BLOCKED", "DATA_STALE", "INSUFFICIENT_EVIDENCE"].includes(state) || (row.blockers || []).length > 0;
  if (filter === "PAPER_ELIGIBLE") return row.paper_autopilot_eligible === true;
  if (filter === "STALE") return String(row.freshness || "").toUpperCase() === "STALE";
  if (filter === "DAY_TRADE") return String(row.trade_style || row.horizon || "").toUpperCase().includes("DAY") || String(row.preferred_horizon || "").toUpperCase().includes("DAY");
  if (filter === "SHORT_SWING") return /1D|2D|3D|SHORT.*SWING/i.test(`${row.trade_style || ""} ${row.horizon || ""} ${row.preferred_horizon || ""}`);
  if (filter === "STANDARD_SWING") return /SWING|5D|10D/i.test(`${row.trade_style || ""} ${row.horizon || ""} ${row.preferred_horizon || ""}`);
  return state === filter || row.advisory_entry_state === filter || row.advisory_exit_state === filter;
}

function ActionCard({ row, selected, onSelect }) {
  const state = stateLabel(row);
  const urgent = ["LOSING_MOMENTUM", "PROTECT_PROFIT", "APPROACHING_SELL", "SELL_RECOMMENDED"].includes(state);
  const attention = urgent || state === "DATA_STALE" || state === "INSUFFICIENT_EVIDENCE" || (row.blockers || []).length > 0;
  return (
    <button type="button" className={`copilot-action-card ${selected ? "selected" : ""} ${urgent ? "urgent" : ""}`} onClick={() => onSelect(row.recommendation_id)} aria-pressed={selected}>
      <div className="copilot-card-topline"><span className="copilot-rank">#{text(row.rank, "-")}</span><span className={stateClass(state)}>{titleCase(state)}</span></div>
      <div className="copilot-symbol-row"><div><strong>{text(row.symbol)}</strong><small>{text(displayValue(row, "company_name", "company", "asset_name"), "Asset name unavailable")}</small></div><span>{titleCase(row.asset_type || row.asset_class || "equity")}</span></div>
      <div className="copilot-price-row"><span>{text(displayValue(row, "price", "last_price"), "Price unavailable")}</span><span className={Number(row.daily_change || row.change_pct) < 0 ? "copilot-negative" : "copilot-positive"}>{present(displayValue(row, "daily_change", "change_pct")) ? `${displayValue(row, "daily_change", "change_pct")}%` : "Daily change unavailable"}</span></div>
      <div className="copilot-card-meta"><span>{text(row.confidence, "Unavailable")}{present(row.confidence) ? "% confidence" : ""}</span><span>{titleCase(row.trade_style || row.horizon)}</span><span>{titleCase(row.preferred_horizon || row.horizon)}</span></div>
      <p>{text(row.simple_why || row.why_astra_chose_it, "No explanation is available yet.")}</p>
      <div className="copilot-card-factors"><span>{text(displayValue(row, "strongest_supporting_factor"), arrayValue(row, "positive_factors")[0] || "Supporting factor unavailable")}</span><span>{text(displayValue(row, "greatest_risk", "risk_reason"), titleCase(row.risk_level))}</span></div>
      <div className="copilot-card-footer"><span>{titleCase(row.evidence_quality)}</span><span>{titleCase(row.freshness)}</span><span>{row.paper_autopilot_eligible ? "Paper eligible" : "Advisory only"}</span><span>{attention ? "Attention" : titleCase(row.position_state || "No position")}</span></div>
    </button>
  );
}

function FactorList({ title, items, empty = "No supporting evidence is available." }) {
  const values = Array.isArray(items) ? items.filter(present) : [];
  return (
    <section className="copilot-detail-block">
      <h3>{title}</h3>
      {values.length ? <ul>{values.map((item, index) => <li key={`${item}-${index}`}>{text(item)}</li>)}</ul> : <div className="copilot-unavailable">{empty}</div>}
    </section>
  );
}

function ExecutionState({ row }) {
  const values = [
    ["Advisory entry", titleCase(row.advisory_entry_state)],
    ["Advisory exit", titleCase(row.advisory_exit_state)],
    ["Paper Autopilot", row.paper_autopilot_eligible ? "Eligible" : "Not eligible"],
    ["Broker", row.broker_eligible ? "Eligible" : "Not eligible"],
    ["Order", row.order_submitted ? "Submitted" : "Not submitted"],
    ["Fill", row.fill_confirmed ? "Confirmed" : "Not confirmed"],
    ["Position", titleCase(row.position_state)],
  ];
  return <div className="copilot-execution-grid">{values.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

function Timeline({ row }) {
  const stages = [
    ["Discovered", false, "History unavailable"],
    ["Ranked", present(row.rank), present(row.rank) ? "Canonical rank present" : "Rank unavailable"],
    ["Categorized", present(row.trade_style || row.horizon), present(row.trade_style || row.horizon) ? "Trade style present" : "Trade style unavailable"],
    ["Horizon evaluated", row.horizon_comparison?.status === "ADVISORY_ONLY", text(row.horizon_comparison?.reason, "Horizon comparison unavailable")],
    ["Copilot reviewed", true, "Canonical Copilot record"],
    ["Paper eligible", row.paper_autopilot_eligible === true, row.paper_autopilot_eligible ? "Eligible" : "Not eligible"],
    ["Order submitted", row.order_submitted === true, row.order_submitted ? "Submitted" : "Not submitted"],
    ["Filled", row.fill_confirmed === true, row.fill_confirmed ? "Confirmed" : "Not confirmed"],
    ["Monitoring", row.position_state === "POSITION_OPEN", row.position_state === "POSITION_OPEN" ? "Position open" : "No open position"],
    ["Exit review", present(row.advisory_exit_state) && EXIT_STATES.has(row.advisory_exit_state), text(row.advisory_exit_state, "Exit evidence unavailable")],
    ["Closed", row.position_state === "POSITION_CLOSED" || row.completed_lifecycle === true, "Lifecycle closure evidence"],
  ];
  return <div className="copilot-timeline">{stages.map(([label, complete, reason]) => <div className={`copilot-timeline-step ${complete ? "complete" : "pending"}`} key={label}><span className="copilot-timeline-dot" /><div><strong>{label}</strong><small>{complete ? "Verified in current payload" : reason}</small></div></div>)}</div>;
}

function HistoryView({ row }) {
  const items = historyItems(row);
  return (
    <section className="copilot-detail-block">
      <div className="copilot-subheading"><h3>Recommendation history</h3><span>{items.length ? `${items.length} shown` : "Bounded view"}</span></div>
      {items.length ? <div className="copilot-history-list">{items.map((item, index) => <article className="copilot-history-item" key={`${item.timestamp || item.at || index}-${index}`}><div><strong>{titleCase(item.previous_state || item.prior_state || "Initial")}</strong><span>to</span><strong>{titleCase(item.new_state || item.state || item.lifecycle_state)}</strong></div><small>{formatTimestamp(item.timestamp || item.at)} · {text(item.reason, "Reason unavailable")}</small><p>{[item.price, item.confidence, item.evidence_quality, item.horizon, item.position_state].filter(present).map((value) => text(value)).join(" · ") || "No additional history fields available."}</p></article>)}</div> : <div className="copilot-unavailable">No recommendation history was supplied by the canonical payload. Astra will not fabricate transitions.</div>}
    </section>
  );
}

function ChangesView({ row }) {
  const items = changeItems(row);
  const [changeFilter, setChangeFilter] = useState("ALL");
  const types = ["ALL", ...new Set(items.map((item) => String(item.type || item.change_type || "OTHER").toUpperCase()))];
  const filtered = items.filter((item) => changeFilter === "ALL" || String(item.type || item.change_type || "OTHER").toUpperCase() === changeFilter);
  return (
    <section className="copilot-detail-block">
      <div className="copilot-subheading"><h3>What changed</h3><span>{items.length ? `${items.length} shown` : "Bounded view"}</span></div>
      {items.length ? <><div className="copilot-mini-filters">{types.map((type) => <button type="button" key={type} className={changeFilter === type ? "active" : ""} onClick={() => setChangeFilter(type)}>{titleCase(type)}</button>)}</div><div className="copilot-change-feed">{filtered.map((item, index) => <article className="copilot-change-item" key={`${item.timestamp || item.at || index}-${index}`}><div><strong>{titleCase(item.type || item.change_type || "Change")}</strong><small>{formatTimestamp(item.timestamp || item.at)}</small></div><p>{text(item.explanation || item.reason, "Explanation unavailable")}</p><span>{text(item.previous_value || item.from, "Unavailable")} <b>→</b> {text(item.new_value || item.to, "Unavailable")}</span></article>)}</div></> : <div className="copilot-unavailable">No change history was supplied by the canonical payload.</div>}
    </section>
  );
}

function ComparisonWorkspace({ baseRow, rows, compareId, onCompare }) {
  const compareRow = rows.find((row) => row.recommendation_id === compareId) || null;
  if (!baseRow) return null;
  const fields = [
    ["Recommendation", (row) => titleCase(stateLabel(row))], ["Confidence", (row) => present(row.confidence) ? `${row.confidence}%` : null], ["Evidence", (row) => titleCase(row.evidence_quality)],
    ["Freshness", (row) => titleCase(row.freshness)], ["Price change", (row) => displayValue(row, "daily_change", "change_pct")], ["Trade style", (row) => titleCase(row.trade_style || row.horizon)], ["Horizon", (row) => titleCase(row.preferred_horizon || row.horizon)],
    ["Momentum", (row) => titleCase(row.momentum_state)], ["Regime fit", (row) => titleCase(row.market_regime)], ["Sector", (row) => titleCase(row.sector_context)], ["Breadth", (row) => titleCase(row.breadth_context)], ["Catalyst", (row) => titleCase(row.catalyst_context)], ["Fundamentals", (row) => titleCase(row.fundamental_context)], ["Risk", (row) => titleCase(row.risk_level)], ["Liquidity", (row) => titleCase(row.liquidity)], ["Opportunity cost", (row) => titleCase(row.opportunity_cost_state)], ["Capital efficiency", (row) => titleCase(row.capital_efficiency_state)], ["Paper eligibility", (row) => row.paper_autopilot_eligible ? "Eligible" : "Not eligible"], ["Blockers", (row) => (row.blockers || []).join(", ") || "None reported"],
  ];
  return (
    <section className="copilot-comparison" aria-label="Recommendation comparison">
      <div className="copilot-subheading"><div><div className="copilot-kicker">Advisory comparison</div><h2>Compare recommendations</h2></div><select value={compareId} onChange={(event) => onCompare(event.target.value)} aria-label="Choose comparison recommendation"><option value="">Choose a second recommendation</option>{rows.filter((row) => row.recommendation_id !== baseRow.recommendation_id).map((row) => <option key={row.recommendation_id} value={row.recommendation_id}>{row.symbol}</option>)}</select></div>
      {compareRow ? <div className="copilot-compare-grid"><div className="copilot-compare-head"><strong>{text(baseRow.symbol)}</strong><strong>{text(compareRow.symbol)}</strong></div>{fields.map(([label, getter]) => <div className="copilot-compare-row" key={label}><span>{label}</span><strong>{text(getter(baseRow))}</strong><strong>{text(getter(compareRow))}</strong></div>)}<p className="copilot-unavailable">Comparison displays backend fields only. It does not calculate a replacement decision or aggregate score.</p></div> : <div className="copilot-unavailable">Select another canonical recommendation to compare it with {text(baseRow.symbol)}.</div>}
    </section>
  );
}

function DecisionWorkspace({ row }) {
  if (!row) return <section className="copilot-workspace copilot-empty"><div className="copilot-empty-icon">◎</div><h2>Select a recommendation</h2><p>Choose a Top 5 action to inspect its evidence, blockers, lifecycle, and execution distinctions.</p></section>;
  const state = stateLabel(row);
  const context = [
    ["Market regime", row.market_regime], ["Trade archetype", row.trade_archetype], ["Sector", row.sector_context], ["Breadth", row.breadth_context],
    ["Catalyst", row.catalyst_context], ["Fundamentals", row.fundamental_context], ["Momentum", row.momentum_state], ["Thesis", row.thesis_state],
    ["Giveback risk", row.profit_giveback_risk], ["Opportunity cost", row.opportunity_cost_state], ["Capital efficiency", row.capital_efficiency_state],
  ];
  const contextValues = context.filter(([, value]) => present(value));
  return (
    <section className="copilot-workspace" aria-label={`Decision workspace for ${row.symbol}`}>
      <div className="copilot-workspace-heading"><div><div className="copilot-kicker">Selected recommendation</div><h2>{text(row.symbol)} <span>{titleCase(row.asset_type || "equity")}</span></h2><p>{text(row.simple_summary || row.simple_why)}</p></div><span className={stateClass(state)}>{titleCase(state)}</span></div>
      <div className="copilot-workspace-metrics"><Metric label="Confidence" value={present(row.confidence) ? `${row.confidence}%` : null} tone="blue" hint="Confidence is distinct from evidence quality" /><Metric label="Evidence" value={titleCase(row.evidence_quality)} tone={row.evidence_quality === "INSUFFICIENT_EVIDENCE" ? "warn" : "neutral"} /><Metric label="Freshness" value={titleCase(row.freshness)} /><Metric label="Trade style" value={titleCase(row.trade_style || row.horizon)} /><Metric label="Horizon" value={titleCase(row.preferred_horizon || row.horizon)} /></div>
      <ExecutionState row={row} />
      <div className="copilot-workspace-columns">
        <div>
          <section className="copilot-detail-block copilot-recommendation"><h3>Astra's recommendation</h3><p>{text(row.why_astra_chose_it || row.simple_why, "No recommendation explanation is available yet.")}</p><div className="copilot-advisory-note">Advisory recommendation only. This record does not create, submit, fill, or close an order.</div></section>
          <FactorList title="Why now" items={row.positive_factors} empty="No positive factors are available in the cached payload." />
          <FactorList title="Why not" items={row.weakening_factors} empty="No weakening factors are available in the cached payload." />
          <section className="copilot-detail-block"><h3>What would change Astra's view</h3><div className="copilot-change-box">{text(row.what_would_change, "No change condition is available yet.")}</div></section>
          <section className="copilot-detail-block"><h3>Blockers</h3>{row.blockers?.length ? <ul className="copilot-blockers">{row.blockers.map((blocker) => <li key={blocker}>{text(blocker)}</li>)}</ul> : <div className="copilot-unavailable">No blockers are reported in the canonical record.</div>}</section>
        </div>
        <div>
          <section className="copilot-detail-block"><h3>Conviction and evidence</h3><div className="copilot-evidence-grid"><Metric label="Overall confidence" value={present(row.confidence) ? `${row.confidence}%` : null} tone="blue" /><Metric label="Symbol evidence" value={titleCase(row.symbol_evidence_quality)} /><Metric label="Risk" value={titleCase(row.risk_level)} /><Metric label="Liquidity" value={titleCase(row.liquidity)} /></div>{contextValues.length ? <div className="copilot-context-grid">{contextValues.map(([label, value]) => <ContextItem key={label} label={label} value={value} />)}</div> : <div className="copilot-unavailable">Technical, market, sector, catalyst, and fundamental context is unavailable in this cached recommendation.</div>}</section>
          <section className="copilot-detail-block"><h3>Decision timeline</h3><Timeline row={row} /></section>
          <section className="copilot-detail-block"><h3>Recommendation lifecycle</h3><div className="copilot-lifecycle"><span className={stateClass(state)}>{titleCase(state)}</span><small>Only the current canonical state is available; historical transitions are not fabricated.</small></div></section>
          <HistoryView row={row} />
          <ChangesView row={row} />
        </div>
      </div>
      <div className="copilot-record-footer"><span>Recommendation ID: {text(row.recommendation_id)}</span><span>Trace: {text(row.influence_trace_reference)}</span><span>Updated: {formatTimestamp(row.generated_at)}</span></div>
    </section>
  );
}

export default function CopilotPage({ selectedSymbol = "", onSelectSymbol }) {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [compareId, setCompareId] = useState("");

  useEffect(() => {
    let mounted = true;
    loadCopilot().then((result) => {
      if (!mounted) return;
      setPayload(result.payload || EMPTY_PAYLOAD);
      setError(result.ok ? "" : result.error || "copilot_endpoint_unavailable");
    });
    return () => { mounted = false; };
  }, []);

  const rows = useMemo(() => Array.isArray(payload?.recommendations) ? payload.recommendations : [], [payload]);
  const filteredRows = useMemo(() => rows.filter((row) => matchesFilter(row, filter) && (!search.trim() || rowSearchText(row).includes(search.trim().toLowerCase()))), [rows, filter, search]);
  const selectedRow = useMemo(() => {
    const preferred = selectedSymbol ? rows.find((row) => String(row.symbol).toUpperCase() === String(selectedSymbol).toUpperCase()) : null;
    return rows.find((row) => row.recommendation_id === selectedId) || preferred || filteredRows[0] || rows[0] || null;
  }, [filteredRows, rows, selectedId, selectedSymbol]);

  const choose = (id) => {
    setSelectedId(id);
    const row = rows.find((item) => item.recommendation_id === id);
    if (row && typeof onSelectSymbol === "function") onSelectSymbol(row.symbol);
  };

  if (payload === null) return <div className="copilot-page"><div className="copilot-loading"><div className="copilot-loader" /><h1>Connecting Astra Copilot</h1><p>Loading one canonical recommendation payload.</p></div></div>;

  return (
    <div className="copilot-page">
      <CopilotHeader payload={payload} rows={rows} error={error} />
      <MarketContextStrip rows={rows} />
      {error ? <div className="copilot-alert copilot-alert-danger" role="alert">{error}. The page is showing a safe empty state and has not created a fallback recommendation.</div> : null}
      <FilterBar filter={filter} onChange={setFilter} rows={rows} search={search} onSearch={setSearch} onReset={() => { setFilter("ALL"); setSearch(""); }} />
      <div className="copilot-section-heading"><div><div className="copilot-kicker">Priority queue</div><h2>Top 5 actions</h2></div><span>{filteredRows.length} shown / {rows.length} available</span></div>
      {filteredRows.length ? <div className="copilot-action-grid">{filteredRows.slice(0, 5).map((row) => <ActionCard key={row.recommendation_id} row={row} selected={selectedRow?.recommendation_id === row.recommendation_id} onSelect={choose} />)}</div> : <div className="copilot-empty copilot-empty-compact"><h2>{rows.length ? "No actions match this filter" : "No Top 5 actions available"}</h2><p>{rows.length ? "Try All or another canonical lifecycle filter." : "Astra has not provided enough valid cached recommendations to populate this queue."}</p></div>}
      <div className="copilot-section-heading"><div><div className="copilot-kicker">Decision detail</div><h2>Selected workspace</h2></div><span>{selectedRow ? text(selectedRow.symbol) : "No selection"}</span></div>
      <DecisionWorkspace row={selectedRow} />
      <ComparisonWorkspace baseRow={selectedRow} rows={rows} compareId={compareId} onCompare={setCompareId} />
      <div className="copilot-safety-footer"><span>Paper-safe advisory interface</span><span>Provider calls: {text(payload?.provider_calls_used, "0")}</span><span>Broker calls: {text(payload?.broker_actions_used, "0")}</span><span>LLM calls: {text(payload?.llm_calls_used, "0")}</span><span>Behavior safe to apply: false</span></div>
    </div>
  );
}
