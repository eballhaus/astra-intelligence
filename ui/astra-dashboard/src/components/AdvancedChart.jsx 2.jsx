import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

export default function AdvancedChart() {
  const chartContainer = useRef();

  useEffect(() => {
    const chart = createChart(chartContainer.current, {
      layout: { backgroundColor: "#141a2e", textColor: "#ccc" },
      grid: { vertLines: { color: "#1e2a48" }, horzLines: { color: "#1e2a48" } },
      crosshair: { mode: 1 },
      width: chartContainer.current.clientWidth,
      height: 400,
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderDownColor: "#ef5350",
      borderUpColor: "#26a69a",
      wickDownColor: "#ef5350",
      wickUpColor: "#26a69a",
    });

    const volumeSeries = chart.addHistogramSeries({
      color: "#1f77b4",
      priceFormat: { type: "volume" },
      scaleMargins: { top: 0.85, bottom: 0 },
    });

    const data = Array.from({ length: 60 }).map((_, i) => ({
      time: `2025-12-${(i + 1).toString().padStart(2, "0")}`,
      open: 480 + Math.random() * 40,
      high: 490 + Math.random() * 40,
      low: 470 + Math.random() * 40,
      close: 475 + Math.random() * 40,
    }));
    const volume = data.map((d) => ({
      time: d.time,
      value: Math.round(10000 + Math.random() * 5000),
      color: d.close > d.open ? "#26a69a" : "#ef5350",
    }));

    candleSeries.setData(data);
    volumeSeries.setData(volume);

    window.addEventListener("resize", () => {
      chart.applyOptions({ width: chartContainer.current.clientWidth });
    });
  }, []);

  return (
    <div
      ref={chartContainer}
      className="bg-[#141a2e] rounded-2xl shadow-lg border border-blue-800 p-4 mb-12"
    />
  );
}
