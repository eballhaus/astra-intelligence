import React, { Component, useEffect, useMemo, useState } from "react";
import Dashboard from "./dashboard/pages/Dashboard";
import LearningTab from "./dashboard/pages/LearningTab";
import { API_BASE_STORAGE_KEY, fetchJsonWithFallback, getInitialApiBase } from "./apiBase";
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
  { id: "dashboard", label: "🏠 Dashboard", icon: "dashboard" },
  { id: "copilot", label: "🤖 Copilot", icon: "copilot" },
  { id: "portfolio", label: "💼 Portfolio", icon: "portfolio" },
  { id: "watchlists", label: "👀 Watchlists", icon: "watchlists" },
  { id: "ask", label: "💬 Ask Astra", icon: "ask" },
  { id: "learning", label: "🧠 Learning Center", icon: "learning" },
  { id: "alerts", label: "🚨 Alerts", icon: "alerts" },
  { id: "reports", label: "📄 Reports", icon: "reports" },
  { id: "settings", label: "⚙️ Settings", icon: "settings" },
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

function AstraMark() {
  return (
    <svg viewBox="0 0 88 88" aria-hidden="true" className="astra-brand-mark-svg">
      <defs>
        <linearGradient id="astraMarkPrimary" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#6db2ff" />
          <stop offset="100%" stopColor="#1e64ea" />
        </linearGradient>
        <linearGradient id="astraMarkSecondary" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#1b4dbf" />
          <stop offset="100%" stopColor="#0d2f73" />
        </linearGradient>
      </defs>
      <path d="M13 66 34 18c1.6-3.8 7-3.8 8.7 0L64 66c1.1 2.4-.6 5-3.2 5H45.8c-1.6 0-3-.9-3.7-2.3l-3.6-7.4h-11l5.7-12.7h-3.5l-7.9 17.8c-.6 1.4-2 2.3-3.6 2.3H16c-2.7 0-4.4-2.7-3-5.7Z" fill="url(#astraMarkPrimary)" />
      <path d="M51 71c-1.6 0-3-.9-3.7-2.3L33.2 39.4c-1.3-2.7.7-5.9 3.7-5.9h8.4c1.6 0 3 .9 3.7 2.3L65.7 68c1.3 2.7-.7 6-3.8 6H51Z" fill="url(#astraMarkSecondary)" />
    </svg>
  );
}

function NavIcon({ kind }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "1.8",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
  };
  if (kind === "dashboard") {
    return <svg {...common}><path d="M4 13h7V4H4zM13 20h7v-9h-7zM13 4h7v7h-7zM4 20h7v-5H4z" /></svg>;
  }
  if (kind === "opportunities" || kind === "copilot") {
    return <svg {...common}><path d="m4 15 5-5 4 4 7-8" /><path d="M20 10V4h-6" /></svg>;
  }
  if (kind === "portfolio") {
    return <svg {...common}><path d="M3 7h18v12H3z" /><path d="M8 7V5h8v2" /><path d="M3 12h18" /></svg>;
  }
  if (kind === "ask") {
    return <svg {...common}><path d="M12 3c4.4 0 8 3 8 6.8 0 3.7-3.6 6.7-8 6.7-.8 0-1.6-.1-2.4-.3L5 19l1.2-3.7C4.8 14 4 11.9 4 9.8 4 6 7.6 3 12 3Z" /><path d="M9 10h.01M12 10h.01M15 10h.01" /></svg>;
  }
  if (kind === "watchlists") {
    return <svg {...common}><path d="M6 4h12v16l-6-3-6 3z" /></svg>;
  }
  if (kind === "learning") {
    return <svg {...common}><path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 0-4 4Z" /><path d="M9 4v16" /></svg>;
  }
  if (kind === "alerts") {
    return <svg {...common}><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></svg>;
  }
  if (kind === "reports") {
    return <svg {...common}><path d="M5 3h10l4 4v14H5z" /><path d="M15 3v5h5" /><path d="M8 13h8M8 17h6" /></svg>;
  }
  if (kind === "settings") {
    return <svg {...common}><path d="M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z" /><path d="M4 12h2M18 12h2M12 4v2M12 18v2M6.3 6.3l1.4 1.4M16.3 16.3l1.4 1.4M17.7 6.3l-1.4 1.4M7.7 16.3l-1.4 1.4" /></svg>;
  }
  return <svg {...common}><path d="M5 12h14" /><path d="M12 5v14" /></svg>;
}

function AskAstraPage({ initialQuestion = "" }) {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [answer, setAnswer] = useState("");
  const [localStatus, setLocalStatus] = useState({});

  useEffect(() => {
    const next = String(initialQuestion || "").trim();
    if (next) {
      setQuestion(next);
      setStatus("prefilled");
      setMessage("Question prefilled from the dashboard. Submit when you are ready.");
    }
  }, [initialQuestion]);

  useEffect(() => {
    let mounted = true;
    const refreshStatus = async () => {
      const result = await fetchJsonWithFallback("/api/ask_astra_status_v1", {
        preferredBase: getInitialApiBase(),
        fallbackValue: {},
        timeoutMs: 6000,
      });
      if (mounted && result.ok && result.parsed) setLocalStatus(result.parsed || {});
    };
    refreshStatus();
    return () => {
      mounted = false;
    };
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const cleanQuestion = question.trim();
    if (!cleanQuestion) {
      setStatus("error");
      setMessage("Type a question first, then submit.");
      return;
    }
    setStatus("working");
    setMessage("Asking Astra from cached context. No automatic dashboard LLM calls are made.");
    setAnswer("");
    const result = await fetchJsonWithFallback("/api/ask_astra_v1", {
      preferredBase: getInitialApiBase(),
      fallbackValue: { ok: false, error: "ask_astra_unavailable" },
      timeoutMs: 70000,
      init: {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: cleanQuestion, context_scope: "copilot", response_mode: "fast" }),
      },
    });
    if (result.ok && result.parsed?.ok) {
      setStatus("ready");
      setMessage(`Mode: ${result.parsed?.ask_astra_mode || "fast"} · Response: ${result.parsed?.response_mode || result.parsed?.local_ai_status?.response_mode || "structured_fallback"} · ${result.parsed?.generation_ms ?? 0}ms.`);
      setAnswer(String(result.parsed?.answer || ""));
      setLocalStatus(result.parsed?.local_ai_status || localStatus || {});
    } else {
      setStatus("error");
      setMessage(String(result.parsed?.error || result.error || "Ask Astra endpoint unavailable."));
    }
  };

  const aiStatusText = localStatus?.local_ai_status || "checking";
  const modelText = localStatus?.selected_model || localStatus?.primary_model || "qwen3:8b";

  return (
    <div className="astra-page-grid">
      <form className="astra-ai-panel astra-ai-panel-page" onSubmit={handleSubmit}>
        <div>
          <span className="astra-ai-kicker">Premium AI Panel</span>
          <h1>Ask Astra</h1>
          <p>
            Ask Astra remains user-triggered only. Dashboard render never calls a model; submitted questions use local Qwen through Ollama when available, or a structured cached-data fallback.
          </p>
          <div className="astra-ai-status-grid">
            <span>Local AI status <strong>{aiStatusText}</strong></span>
            <span>Ollama reachable <strong>{localStatus?.ollama_reachable ? "yes" : "no"}</strong></span>
            <span>Primary model <strong>{localStatus?.primary_model || "qwen3:8b"}</strong></span>
            <span>Fallback model <strong>{localStatus?.fallback_model || "qwen3:14b"}</strong></span>
            <span>Active model <strong>{modelText}</strong></span>
            <span>Response mode <strong>{localStatus?.response_mode || "structured_fallback"}</strong></span>
          </div>
        </div>
        <div className="astra-ai-input-row">
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about opportunities, risk, learning progress, or portfolio context..."
          />
          <button type="submit" disabled={!question.trim()}>
            Ask Astra
          </button>
        </div>
        {message ? (
          <div className={`astra-ai-status astra-ai-status-${status}`}>
            {message}
          </div>
        ) : null}
        {answer ? <div className="astra-ai-answer">{answer}</div> : null}
      </form>
      <ShellCard title="Safe Interaction Model" eyebrow="No automatic AI calls">
        <p>
          Astra only contacts local AI after you submit a question. If Ollama or Qwen is offline, the page returns a safe structured answer from cached Astra data.
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
          <button type="button" onClick={() => setActiveTab("copilot")}>Copilot</button>
        </div>
      </ShellCard>
    </div>
  );
}

function PageHeading({ activeTab }) {
  const copy = useMemo(() => ({
    dashboard: ["Executive Command Dashboard", "What is happening, why it matters, and what deserves attention right now."],
    copilot: ["Copilot", "Astra's advisory action center: buy-now candidates, holds, watch items, and exit-review context."],
    portfolio: ["Portfolio Command", "Portfolio health, performance, allocation, and active paper positions in one consumer-ready view."],
    ask: ["Ask Astra", "A premium AI workspace that stays idle until you explicitly submit a question."],
    watchlists: ["Watchlists", "Safe watchlist shells using cached context and graceful empty states."],
    learning: ["Learning Center", "Astra’s report card, trend diagnostics, and full advanced learning panels."],
    alerts: ["Alerts", "Read-only risk, market, and portfolio alerts from existing diagnostics."],
    reports: ["Reports", "Export-ready summaries remain consolidated in Learning Center diagnostics."],
    settings: ["Settings", "Safe frontend shell for configuration awareness; no trading behavior changes."],
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
  const [askPrefill, setAskPrefill] = useState("");

  const handleNavigate = (tabId, options = {}) => {
    if (tabId === "ask") {
      const question = String(options?.question || "").trim();
      if (question) setAskPrefill(question);
    }
    setActiveTab(tabId);
  };

  const renderTab = () => {
    if (activeTab === "dashboard") return <Dashboard onNavigate={handleNavigate} />;
    if (activeTab === "copilot") return <Dashboard remoteMode remoteSection="copilot" onNavigate={handleNavigate} />;
    if (activeTab === "portfolio") return <Dashboard remoteMode remoteSection="positions" onNavigate={handleNavigate} />;
    if (activeTab === "ask") return <AskAstraPage initialQuestion={askPrefill} />;
    if (activeTab === "watchlists") return <WatchlistsPage />;
    if (activeTab === "learning") return <LearningTab />;
    if (["alerts", "reports", "settings"].includes(activeTab)) return <MorePage setActiveTab={handleNavigate} />;
    return <MorePage setActiveTab={handleNavigate} />;
  };

  return (
    <div className="astra-desktop-shell">
      <aside className="astra-sidebar">
        <div className="astra-brand">
          <div className="astra-brand-mark">
            <AstraMark />
          </div>
          <div className="astra-brand-copy">
            <strong>ASTRA</strong>
            <span>INTELLIGENCE</span>
            <em>Executive market intelligence</em>
          </div>
        </div>
        <nav className="astra-nav" aria-label="Primary">
          {primaryTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`astra-nav-item ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => handleNavigate(tab.id)}
            >
              <span className="astra-nav-icon"><NavIcon kind={tab.icon} /></span>
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="astra-sidebar-footer">
          <div className="astra-sidebar-footer-row">
            <span className="astra-sidebar-dot" />
            <span>Paper-safe mode</span>
          </div>
          <strong>No behavior changes</strong>
          <small>{getInitialApiBase().replace(/^https?:\/\//, "")}</small>
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
