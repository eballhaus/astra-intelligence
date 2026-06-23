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
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "copilot", label: "Copilot", icon: "copilot" },
  { id: "portfolio", label: "Portfolio", icon: "portfolio" },
  { id: "watchlists", label: "Watchlists", icon: "watchlists" },
  { id: "ask", label: "Ask Astra", icon: "ask" },
  { id: "learning", label: "Learning Center", icon: "learning" },
  { id: "alerts", label: "Alerts", icon: "alerts" },
  { id: "reports", label: "Reports", icon: "reports" },
  { id: "settings", label: "Settings", icon: "settings" },
];

const moreLinks = [
  { title: "Ask Astra", copy: "Open the user-triggered AI assistant with the current selected-symbol context when available.", tab: "ask" },
  { title: "Radar", copy: "Forward-looking watch items stay on the dashboard and Copilot surfaces without adding endpoint loops.", tab: "dashboard" },
  { title: "Recovery Center", copy: "Check backend, frontend, watchdog, remote access, and learning-protection status.", tab: "recovery" },
  { title: "Calendar", copy: "Cached event context remains visible on the executive dashboard when connected.", tab: "dashboard" },
  { title: "Watchlists", copy: "Safe watchlist shells and cached monitoring context.", tab: "watchlists" },
  { title: "Settings", copy: "Configuration and environment controls remain available through existing backend/admin paths." },
  { title: "Reports", copy: "Performance and diagnostic exports are consolidated in Learning Center copy tools." },
  { title: "Alerts", copy: "Risk, market, and portfolio alerts remain read-only in dashboard diagnostics." },
  { title: "Raw Diagnostics", copy: "Advanced panels stay collapsed inside Learning Center to avoid endpoint storms." },
  { title: "Admin / Dev Utilities", copy: "Operational utilities remain behind existing routes and are not invoked on page load." },
];

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(String(text || ""));
    return true;
  } catch (_error) {
    return false;
  }
}

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

const mobileTabs = [
  { id: "dashboard", label: "Dashboard", icon: "dashboard" },
  { id: "copilot", label: "Copilot", icon: "copilot" },
  { id: "portfolio", label: "Portfolio", icon: "portfolio" },
  { id: "watchlists", label: "Watchlist", icon: "watchlists" },
  { id: "learning", label: "Learning", icon: "learning" },
  { id: "more", label: "More", icon: "settings" },
];

function AskAstraPage({ initialQuestion = "", selectedSymbol = "" }) {
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
        body: JSON.stringify({
          question: cleanQuestion,
          context_scope: "copilot",
          response_mode: "fast",
          selected_symbol: selectedSymbol || undefined,
          current_symbol_context: selectedSymbol || undefined,
        }),
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
          {selectedSymbol ? (
            <div className="astra-selected-symbol-pill">
              Current symbol context: <strong>{selectedSymbol}</strong>
            </div>
          ) : null}
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
    ["Emerging Opportunities", "Symbols Astra is observing from cached opportunities before any future promotion decision."],
    ["Earnings Watch", "Event-aware watch context when already present in cached dashboard data; no provider calls are made here."],
    ["Catalyst Watch", "Themes, catalysts, and narrative changes Astra is monitoring in read-only mode."],
    ["Sector Leaders", "Sector and family leaders surfaced from cached market intelligence."],
    ["Behavioral Changes", "Symbols with changing horizon, catalyst, or profit-capture behavior."],
    ["Potential Copilot Candidates", "Future Copilot candidates remain observational and do not change ranking or paper execution."],
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

function RecoveryCenterPage() {
  const [payload, setPayload] = useState({});
  const [status, setStatus] = useState("loading");
  const [copyStatus, setCopyStatus] = useState("");

  useEffect(() => {
    let mounted = true;
    const loadRecovery = async () => {
      setStatus("loading");
      const result = await fetchJsonWithFallback("/api/astra_recovery_center_v1", {
        preferredBase: getInitialApiBase(),
        fallbackValue: { ok: false, status: "unavailable" },
        timeoutMs: 9000,
      });
      if (!mounted) return;
      setPayload(result.parsed || {});
      setStatus(result.ok ? "ready" : "error");
    };
    loadRecovery();
    return () => {
      mounted = false;
    };
  }, []);

  const services = payload?.astra_services || {};
  const learning = payload?.learning_protection || {};
  const recovery = payload?.recovery || {};
  const remote = payload?.remote_access || {};
  const system = payload?.system || {};

  const snapshotText = [
    "Astra Recovery Center Snapshot",
    `Status: ${payload?.status_label || payload?.status || status}`,
    `Recovery score: ${payload?.recovery_health_score ?? "n/a"}`,
    `Backend: running=${services?.backend_running} health=${services?.backend_health}`,
    `Frontend: running=${services?.frontend_running} health=${services?.frontend_health}`,
    `tmux: backend=${services?.tmux_backend_session} frontend=${services?.tmux_frontend_session}`,
    `Learning active: ${learning?.learning_active}`,
    `Learning gap detected: ${learning?.learning_gap_detected}`,
    `Last learning: ${learning?.last_learning_timestamp || "n/a"}`,
    `Last recovery action: ${recovery?.last_recovery_action || "none"}`,
    `SSH open: ${remote?.ssh_port_open}`,
    `Screen sharing open: ${remote?.screen_sharing_port_open}`,
    `Tailscale: ${remote?.tailscale_status || "not_available"} ${remote?.tailscale_ip || ""}`.trim(),
    "Safety: behavior_safe_to_apply=false, no broker/trading/ranking/entry/exit/sizing/allocation changes.",
  ].join("\n");

  const handleCopy = async (label, text = snapshotText) => {
    const ok = await copyText(text);
    setCopyStatus(ok ? `${label} copied.` : `${label} could not be copied by this browser.`);
  };

  const statusCards = [
    ["Recovery Health", payload?.status_label || status, `${payload?.recovery_health_score ?? "n/a"} / 100`],
    ["Backend", services?.backend_health ? "Healthy" : "Needs attention", `Port ${services?.backend_port || 8000}`],
    ["Frontend", services?.frontend_health ? "Healthy" : "Needs attention", `Port ${services?.frontend_port || 5173}`],
    ["Learning Protection", learning?.learning_gap_detected ? "Catch-up recommended" : "Active", learning?.last_learning_timestamp || "timestamp warming up"],
    ["Remote Access", remote?.tailscale_detected ? remote?.tailscale_status : "manual setup", remote?.tailscale_ip || "SSH/Screen Sharing are local checks"],
    ["Logs", recovery?.logs_available?.astra_recovery_log ? "Recovery log found" : "Recovery log warming up", "Startup/watchdog logs are local only"],
  ];

  return (
    <div className="astra-page-grid">
      <ShellCard title="Recovery Center" eyebrow="Infrastructure reliability">
        <p>
          Read-only service recovery diagnostics for backend, frontend, watchdog, remote access, and learning freshness. This page does not trade, call providers, or call an LLM.
        </p>
        <div className="astra-recovery-grid">
          {statusCards.map(([title, value, detail]) => (
            <div className="astra-recovery-tile" key={title}>
              <span>{title}</span>
              <strong>{String(value || "warming up")}</strong>
              <small>{String(detail || "")}</small>
            </div>
          ))}
        </div>
        <div className="astra-button-row astra-recovery-actions">
          <button type="button" onClick={() => handleCopy("Recovery snapshot")}>Copy Recovery Snapshot</button>
          <button type="button" onClick={() => handleCopy("Startup diagnostics", `Startup diagnostics\nBackend=${services?.backend_health}\nFrontend=${services?.frontend_health}\nLast recovery=${recovery?.last_recovery_action || "none"}\nLogs=${JSON.stringify(recovery?.logs_available || {})}`)}>Copy Startup Diagnostics</button>
          <button type="button" onClick={() => handleCopy("Remote access status", `Remote access\nSSH=${remote?.ssh_port_open}\nScreenSharing=${remote?.screen_sharing_port_open}\nTailscale=${remote?.tailscale_status || "not_available"}\nTailscaleIP=${remote?.tailscale_ip || ""}`)}>Copy Remote Access Status</button>
        </div>
        {copyStatus ? <div className="astra-ai-status astra-ai-status-ready">{copyStatus}</div> : null}
      </ShellCard>
      <ShellCard title="System Snapshot" eyebrow="Local only">
        <div className="astra-ai-status-grid">
          <span>Host <strong>{system?.hostname || "warming up"}</strong></span>
          <span>User <strong>{system?.username || "local"}</strong></span>
          <span>Disk used <strong>{system?.disk_usage?.used_pct ?? "n/a"}%</strong></span>
          <span>Provider calls <strong>{payload?.provider_calls_used ?? 0}</strong></span>
          <span>LLM calls <strong>{payload?.llm_calls_used ?? 0}</strong></span>
          <span>Behavior safe to apply <strong>{String(payload?.behavior_safe_to_apply ?? false)}</strong></span>
        </div>
      </ShellCard>
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
            <button
              type="button"
              className="astra-more-tile"
              key={item.title}
              onClick={() => (item.tab ? setActiveTab(item.tab) : null)}
            >
              <strong>{item.title}</strong>
              <span>{item.copy}</span>
            </button>
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
    recovery: ["Recovery Center", "Backend, frontend, watchdog, remote access, and learning-protection health in one read-only view."],
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
  const [selectedSymbol, setSelectedSymbol] = useState("");

  const handleNavigate = (tabId, options = {}) => {
    if (tabId === "ask") {
      const question = String(options?.question || "").trim();
      if (question) setAskPrefill(question);
    }
    const symbol = String(options?.symbol || "").trim().toUpperCase();
    if (symbol) setSelectedSymbol(symbol);
    setActiveTab(tabId);
  };

  const handleSelectSymbol = (symbol, options = {}) => {
    const clean = String(symbol || "").trim().toUpperCase();
    if (!clean) return;
    setSelectedSymbol(clean);
    if (options?.navigateTo) handleNavigate(options.navigateTo, { symbol: clean, question: options.question });
  };

  const renderTab = () => {
    if (activeTab === "dashboard") return <Dashboard onNavigate={handleNavigate} selectedSymbol={selectedSymbol} onSelectSymbol={handleSelectSymbol} />;
    if (activeTab === "copilot") return <Dashboard remoteMode remoteSection="copilot" onNavigate={handleNavigate} selectedSymbol={selectedSymbol} onSelectSymbol={handleSelectSymbol} />;
    if (activeTab === "portfolio") return <Dashboard remoteMode remoteSection="positions" onNavigate={handleNavigate} selectedSymbol={selectedSymbol} onSelectSymbol={handleSelectSymbol} />;
    if (activeTab === "ask") return <AskAstraPage initialQuestion={askPrefill} selectedSymbol={selectedSymbol} />;
    if (activeTab === "watchlists") return <WatchlistsPage />;
    if (activeTab === "learning") return <LearningTab />;
    if (activeTab === "recovery") return <RecoveryCenterPage />;
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
        {selectedSymbol ? (
          <div className="astra-current-symbol-context">
            <span>Current symbol context</span>
            <strong>{selectedSymbol}</strong>
            <button type="button" onClick={() => handleNavigate("ask", { symbol: selectedSymbol, question: `Why does Astra like ${selectedSymbol}?` })}>
              Ask Astra
            </button>
          </div>
        ) : null}
        {renderTab()}
      </main>
      <nav className="astra-mobile-bottom-nav" aria-label="Mobile primary">
        {mobileTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={activeTab === tab.id ? "active" : ""}
            onClick={() => handleNavigate(tab.id)}
          >
            <span><NavIcon kind={tab.icon} /></span>
            {tab.label}
          </button>
        ))}
      </nav>
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
