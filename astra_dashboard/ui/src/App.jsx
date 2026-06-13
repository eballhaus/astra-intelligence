import React, { Component, useMemo, useState } from "react";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";
import { API_BASE_STORAGE_KEY, getInitialApiBase } from "./apiBase";
import "./App.css";

console.log("ASTRA APP FILE ACTIVE:", import.meta.url);

class AppErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    try {
      console.error("[Astra] frontend render recovered", error, info);
    } catch (_e) {}
  }

  handleReconnect = () => {
    try {
      window.localStorage.removeItem(API_BASE_STORAGE_KEY);
    } catch (_e) {}
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="astra-recovery">
        <div className="astra-recovery-card">
          <h1>Astra Dashboard Recovered</h1>
          <p>
            The frontend hit a recoverable render issue. This can happen after a cached dashboard bundle or API base becomes stale.
          </p>
          <div className="astra-recovery-base">Current API base: {getInitialApiBase()}</div>
          <button type="button" onClick={this.handleReconnect}>Reconnect Backend</button>
        </div>
      </div>
    );
  }
}

const primaryTabs = [
  { id: "dashboard", label: "Dashboard", icon: "D" },
  { id: "opportunities", label: "Opportunities", icon: "O" },
  { id: "portfolio", label: "Portfolio", icon: "P" },
  { id: "ask", label: "Ask Astra", icon: "A" },
  { id: "watchlists", label: "Watchlists", icon: "W" },
  { id: "learning", label: "Learning Center", icon: "L" },
  { id: "more", label: "More", icon: "M" },
];

const moreLinks = [
  { title: "Settings", copy: "Configuration and environment controls remain available through existing backend/admin paths." },
  { title: "Reports", copy: "Performance and diagnostic exports are consolidated in Learning Center copy tools." },
  { title: "Alerts", copy: "Risk, market, and portfolio alerts remain read-only in dashboard diagnostics." },
  { title: "Raw Diagnostics", copy: "Advanced panels stay collapsed inside Learning Center to avoid endpoint storms." },
  { title: "Admin / Dev Utilities", copy: "Operational utilities remain behind existing routes and are not invoked on page load." },
];

function ShellCard({ title, eyebrow, children, tone = "light" }) {
  return (
    <section className={`astra-card astra-card-${tone}`}>
      {eyebrow ? <div className="astra-card-eyebrow">{eyebrow}</div> : null}
      <h2>{title}</h2>
      <div>{children}</div>
    </section>
  );
}

function AskAstraPage() {
  const [question, setQuestion] = useState("");
  return (
    <div className="astra-page-grid">
      <section className="astra-ai-panel">
        <div>
          <span className="astra-ai-kicker">Premium AI Panel</span>
          <h1>Ask Astra</h1>
          <p>
            Ask Astra remains user-triggered only. This panel does not call an LLM, provider, broker, or dashboard endpoint until an existing submit path is connected.
          </p>
        </div>
        <div className="astra-ai-input-row">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about opportunities, risk, learning progress, or portfolio context..."
          />
          <button type="button" disabled title="Existing Ask Astra submit path not wired in this shell">
            Submit
          </button>
        </div>
      </section>
      <ShellCard title="Safe Interaction Model" eyebrow="No automatic AI calls">
        <p>
          Astra will only contact an AI/provider service when an explicit existing Ask Astra submit flow is available and the user submits a question.
        </p>
      </ShellCard>
    </div>
  );
}

function WatchlistsPage() {
  const watchlists = [
    ["Astra Watchlist", "Symbols Astra is monitoring from cached opportunities."],
    ["My Watchlist", "Frontend-safe placeholder until user watchlist storage is available."],
    ["High Conviction", "Candidates with strong confidence or quality when cached data is available."],
    ["Earnings Watchlist", "Graceful empty state; no provider calls are made here."],
    ["Theme Watchlist", "AI, quantum, semis, sector rotation, and other cached themes."],
  ];
  return (
    <div className="astra-page-grid astra-watchlist-grid">
      {watchlists.map(([title, copy]) => (
        <ShellCard key={title} title={title} eyebrow="Watchlist">
          <p>{copy}</p>
          <div className="astra-empty-state">Warming up from cached dashboard context.</div>
        </ShellCard>
      ))}
    </div>
  );
}

function MorePage({ setActiveTab }) {
  return (
    <div className="astra-page-grid">
      <ShellCard title="More" eyebrow="Lower-use workspace">
        <p>
          Lower-use destinations are grouped here so the main sidebar stays focused on daily decision flow.
        </p>
        <div className="astra-more-grid">
          {moreLinks.map((item) => (
            <div className="astra-more-tile" key={item.title}>
              <strong>{item.title}</strong>
              <span>{item.copy}</span>
            </div>
          ))}
        </div>
      </ShellCard>
      <ShellCard title="Fast Links" eyebrow="Backwards-compatible">
        <div className="astra-button-row">
          <button type="button" onClick={() => setActiveTab("dashboard")}>Dashboard</button>
          <button type="button" onClick={() => setActiveTab("learning")}>Learning Center</button>
          <button type="button" onClick={() => setActiveTab("opportunities")}>Opportunities</button>
        </div>
      </ShellCard>
    </div>
  );
}

function PageHeading({ activeTab }) {
  const copy = useMemo(() => ({
    dashboard: ["Command Dashboard", "What is happening, why it matters, and what Astra is watching."],
    opportunities: ["Astra Opportunities", "A focused deep dive into cached ranked opportunities. Ranking logic is unchanged."],
    portfolio: ["Portfolio", "Broker-confirmed and internal position context, displayed without changing Alpaca behavior."],
    ask: ["Ask Astra", "A premium AI workspace that stays idle until you explicitly submit a question."],
    watchlists: ["Watchlists", "Safe watchlist shells using cached context and graceful empty states."],
    learning: ["Learning Center", "Astra’s report card, trend diagnostics, and full advanced learning panels."],
    more: ["More", "Settings, reports, raw diagnostics, alerts, and admin/dev utilities."],
  }), []);
  const [title, subtitle] = copy[activeTab] || copy.dashboard;
  return (
    <header className="astra-page-heading">
      <div>
        <div className="astra-overline">Astra Intelligence</div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="astra-safe-pill">Paper-safe UI redesign · no behavior changes</div>
    </header>
  );
}

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");

  const renderTab = () => {
    if (activeTab === "dashboard") return <Dashboard onNavigate={setActiveTab} />;
    if (activeTab === "opportunities") return <Dashboard remoteMode remoteSection="buys" onNavigate={setActiveTab} />;
    if (activeTab === "portfolio") return <Dashboard remoteMode remoteSection="positions" onNavigate={setActiveTab} />;
    if (activeTab === "ask") return <AskAstraPage />;
    if (activeTab === "watchlists") return <WatchlistsPage />;
    if (activeTab === "learning") return <LearningTab />;
    return <MorePage setActiveTab={setActiveTab} />;
  };

  return (
    <div className="astra-desktop-shell">
      <aside className="astra-sidebar">
        <div className="astra-brand">
          <div className="astra-brand-mark">A</div>
          <div>
            <strong>Astra</strong>
            <span>Investment Intelligence</span>
          </div>
        </div>
        <nav className="astra-nav" aria-label="Primary">
          {primaryTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`astra-nav-item ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <span>{tab.icon}</span>
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="astra-sidebar-footer">
          <span>API base</span>
          <strong>{getInitialApiBase().replace(/^https?:\/\//, "")}</strong>
        </div>
      </aside>
      <main className="astra-main">
        <PageHeading activeTab={activeTab} />
        {renderTab()}
      </main>
    </div>
  );
}

export default function AppWithBoundary() {
  return (
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  );
}
