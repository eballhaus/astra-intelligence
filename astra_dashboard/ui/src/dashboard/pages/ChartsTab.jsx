import React, { useEffect, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { API_BASE_CHANGED_EVENT, fetchJsonWithFallback, getInitialApiBase } from "../../apiBase";

const panelStyle = {
  background: "#0f1522",
  border: "1px solid #273142",
  borderRadius: "12px",
  padding: "14px",
  color: "#dce7f7",
};

function formatMoney(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0.00";
  return `$${n.toFixed(2)}`;
}

function sma(data, period, index) {
  if (index < period - 1) return null;
  let sum = 0;
  for (let i = index - period + 1; i <= index; i += 1) {
    sum += Number(data[i]?.c ?? 0);
  }
  return period > 0 ? sum / period : null;
}

function vwap(data, index) {
  let pv = 0;
  let vol = 0;
  for (let i = 0; i <= index; i += 1) {
    const c = Number(data[i]?.c ?? 0);
    const v = Number(data[i]?.v ?? 0);
    pv += c * v;
    vol += v;
  }
  return vol > 0 ? pv / vol : null;
}

function buildChartRows(candles, overlays, trades) {
  const tradeMarkers = [];
  if (Array.isArray(trades)) {
    for (const t of trades) {
      if (!t || !t.symbol) continue;
      if (t.status === "open" && Number.isFinite(Number(t.entry_price))) {
        tradeMarkers.push({
          ts: t.entry_timestamp,
          marker_price: Number(t.entry_price),
          marker_type: "ENTRY",
        });
      } else if (t.status === "closed" && Number.isFinite(Number(t.exit_price))) {
        tradeMarkers.push({
          ts: t.exit_timestamp,
          marker_price: Number(t.exit_price),
          marker_type: "EXIT",
        });
      }
    }
  }

  return (candles || []).map((row, idx) => {
    const date = new Date((Number(row.t) || 0) * 1000);
    const stamp = Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
    const o = Number(row.o ?? 0);
    const h = Number(row.h ?? 0);
    const l = Number(row.l ?? 0);
    const c = Number(row.c ?? 0);
    const v = Number(row.v ?? 0);
    const isUp = c >= o;
    const bodyBottom = Math.min(o, c);
    const bodyTop = Math.max(o, c);
    const marker = tradeMarkers.find((m) => stamp.startsWith(new Date(m.ts || "").toLocaleDateString()));
    return {
      idx,
      stamp,
      o,
      h,
      l,
      c,
      v,
      bodyBottom,
      bodyTop,
      wickRange: h - l,
      isUp,
      volume: overlays.volume ? v : null,
      sma20: overlays.sma20 ? sma(candles, 20, idx) : null,
      sma50: overlays.sma50 ? sma(candles, 50, idx) : null,
      vwap: overlays.vwap ? vwap(candles, idx) : null,
      marker_price: marker ? marker.marker_price : null,
      marker_type: marker ? marker.marker_type : null,
    };
  });
}

export default function ChartsTab() {
  const [resolvedApiBase, setResolvedApiBase] = useState(getInitialApiBase());
  const [rankings, setRankings] = useState([]);
  const [symbol, setSymbol] = useState("AAPL");
  const [assetType, setAssetType] = useState("stock");
  const [resolution, setResolution] = useState("15");
  const [candles, setCandles] = useState([]);
  const [meta, setMeta] = useState({ cached: false, source: "n/a", last_updated_utc: null, data_unavailable: null });
  const [trades, setTrades] = useState([]);
  const [news, setNews] = useState([]);
  const [overlays, setOverlays] = useState({ sma20: true, sma50: false, vwap: false, volume: true, markers: true });

  useEffect(() => {
    const syncBase = () => setResolvedApiBase(getInitialApiBase());
    window.addEventListener(API_BASE_CHANGED_EVENT, syncBase);
    return () => window.removeEventListener(API_BASE_CHANGED_EVENT, syncBase);
  }, []);

  const fetchJsonPath = async (path, fallback) => {
    const result = await fetchJsonWithFallback(path, { preferredBase: resolvedApiBase, fallbackValue: fallback });
    if (result.ok && result.baseUsed && result.baseUsed !== resolvedApiBase) {
      setResolvedApiBase(result.baseUsed);
    }
    return result.parsed;
  };

  useEffect(() => {
    const loadRankings = async () => {
      try {
        const data = await fetchJsonPath("/api/rankings", []);
        if (Array.isArray(data)) {
          setRankings(data);
          if (data[0]?.symbol) {
            setSymbol((prev) => prev || data[0].symbol);
          }
        }
      } catch (_e) {
        setRankings([]);
      }
    };
    loadRankings();
  }, [resolvedApiBase]);

  useEffect(() => {
    const loadCandles = async () => {
      try {
        const data = await fetchJsonPath(
          `/api/candles?symbol=${encodeURIComponent(symbol)}&asset_type=${assetType}&resolution=${resolution}&lookback_days=30`,
          {}
        );
        setCandles(Array.isArray(data?.candles) ? data.candles : []);
        setMeta({
          cached: Boolean(data?.cached),
          source: data?.source || "n/a",
          last_updated_utc: data?.last_updated_utc || null,
          data_unavailable: data?.data_unavailable || null,
        });
      } catch (e) {
        setCandles([]);
        setMeta({ cached: false, source: "n/a", last_updated_utc: null, data_unavailable: String(e) });
      }
    };
    loadCandles();
  }, [symbol, assetType, resolution, resolvedApiBase]);

  useEffect(() => {
    const loadPerformance = async () => {
      try {
        const data = await fetchJsonPath("/api/live_performance", {});
        setTrades(Array.isArray(data?.trades) ? data.trades : []);
      } catch (_e) {
        setTrades([]);
      }
    };
    loadPerformance();
  }, [resolvedApiBase]);

  useEffect(() => {
    const loadNews = async () => {
      try {
        const data = await fetchJsonPath(`/api/news?symbol=${encodeURIComponent(symbol)}&limit=6`, {});
        setNews(Array.isArray(data?.items) ? data.items : []);
      } catch (_e) {
        setNews([]);
      }
    };
    loadNews();
  }, [symbol, resolvedApiBase]);

  const chartRows = useMemo(
    () => buildChartRows(candles, overlays, overlays.markers ? trades.filter((t) => t.symbol === symbol) : []),
    [candles, overlays, trades, symbol]
  );

  const symbols = useMemo(() => {
    const rankedSymbols = rankings.map((r) => r?.symbol).filter(Boolean);
    const defaults = ["AAPL", "TSLA", "MSFT", "NVDA", "AMZN", "GOOG", "BTC", "ETH", "SOL"];
    return Array.from(new Set([...rankedSymbols, ...defaults]));
  }, [rankings]);

  return (
    <div style={{ display: "grid", gap: "12px" }}>
      <div style={{ ...panelStyle, display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
        <label>
          Symbol
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} style={{ marginLeft: "8px" }}>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Asset
          <select value={assetType} onChange={(e) => setAssetType(e.target.value)} style={{ marginLeft: "8px" }}>
            <option value="stock">Stock</option>
            <option value="crypto">Crypto</option>
          </select>
        </label>
        <label>
          Resolution
          <select value={resolution} onChange={(e) => setResolution(e.target.value)} style={{ marginLeft: "8px" }}>
            <option value="1">1m</option>
            <option value="5">5m</option>
            <option value="15">15m</option>
            <option value="60">1h</option>
            <option value="D">1D</option>
          </select>
        </label>
        {["sma20", "sma50", "vwap", "volume", "markers"].map((k) => (
          <label key={k} style={{ fontSize: "0.9rem" }}>
            <input
              type="checkbox"
              checked={Boolean(overlays[k])}
              onChange={() => setOverlays((p) => ({ ...p, [k]: !p[k] }))}
            />{" "}
            {k.toUpperCase()}
          </label>
        ))}
        <span style={{ marginLeft: "auto", fontSize: "0.82rem", color: "#9fb0ca" }}>
          {meta.data_unavailable
            ? `Data unavailable: ${meta.data_unavailable}`
            : `Source: ${meta.source} | ${meta.cached ? "cached" : "live"} | Updated: ${meta.last_updated_utc || "n/a"}`}
        </span>
      </div>

      <div style={{ ...panelStyle, height: "460px" }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartRows} margin={{ top: 18, right: 24, left: 4, bottom: 10 }}>
            <CartesianGrid stroke="#223047" strokeDasharray="2 2" />
            <XAxis dataKey="idx" tick={{ fill: "#8ea1c3", fontSize: 11 }} />
            <YAxis yAxisId="price" domain={["auto", "auto"]} tick={{ fill: "#8ea1c3", fontSize: 11 }} />
            <YAxis yAxisId="volume" orientation="right" tick={{ fill: "#8ea1c3", fontSize: 10 }} hide={!overlays.volume} />
            <Tooltip
              formatter={(value, name) => {
                if (name === "volume") return [value, "Volume"];
                return [formatMoney(value), name];
              }}
              labelFormatter={(label) => chartRows[label]?.stamp || ""}
            />
            <Bar yAxisId="price" dataKey="wickRange" fill="transparent" stroke="#7b8ca8" />
            <Bar
              yAxisId="price"
              dataKey="bodyTop"
              fill="#22c55e"
              stroke="#22c55e"
              shape={(props) => {
                const { x, y, width, height, payload } = props;
                const openY = y + (payload.h - payload.o) * (height / Math.max(payload.h - payload.l, 0.0001));
                const closeY = y + (payload.h - payload.c) * (height / Math.max(payload.h - payload.l, 0.0001));
                const top = Math.min(openY, closeY);
                const bodyH = Math.max(Math.abs(closeY - openY), 1.2);
                return (
                  <rect
                    x={x + width * 0.26}
                    y={top}
                    width={Math.max(width * 0.48, 2)}
                    height={bodyH}
                    fill={payload.isUp ? "#22c55e" : "#ef4444"}
                    stroke={payload.isUp ? "#22c55e" : "#ef4444"}
                  />
                );
              }}
            />
            {overlays.sma20 && <Line yAxisId="price" type="monotone" dataKey="sma20" stroke="#3b82f6" dot={false} strokeWidth={1.5} />}
            {overlays.sma50 && <Line yAxisId="price" type="monotone" dataKey="sma50" stroke="#f59e0b" dot={false} strokeWidth={1.4} />}
            {overlays.vwap && <Line yAxisId="price" type="monotone" dataKey="vwap" stroke="#a855f7" dot={false} strokeWidth={1.4} />}
            {overlays.volume && <Bar yAxisId="volume" dataKey="volume" fill="#475569" opacity={0.35} />}
            {overlays.markers && (
              <Scatter
                yAxisId="price"
                dataKey="marker_price"
                fill="#60a5fa"
                shape={(props) => {
                  const { cx, cy, payload } = props;
                  if (payload.marker_price == null) return null;
                  const color = payload.marker_type === "EXIT" ? "#ef4444" : "#10b981";
                  return <circle cx={cx} cy={cy} r={4} fill={color} stroke="#111827" strokeWidth={1} />;
                }}
              />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div style={{ ...panelStyle }}>
        <h3 style={{ margin: "0 0 10px 0" }}>News ({symbol})</h3>
        {news.length === 0 ? (
          <div style={{ color: "#9fb0ca" }}>No news available.</div>
        ) : (
          <div style={{ display: "grid", gap: "8px" }}>
            {news.map((n, idx) => (
              <a
                key={`${n?.url || "news"}-${idx}`}
                href={n?.url || "#"}
                target="_blank"
                rel="noreferrer"
                style={{ color: "#cfe0ff", textDecoration: "none", borderBottom: "1px solid #1f2a3a", paddingBottom: "6px" }}
              >
                <div style={{ fontWeight: 600 }}>{n?.headline || "Untitled"}</div>
                <div style={{ fontSize: "0.82rem", color: "#9fb0ca" }}>{n?.source || "Unknown source"}</div>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
