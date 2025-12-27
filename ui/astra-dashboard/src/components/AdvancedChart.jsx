import React, { useEffect, useRef } from "react";
import { createChart, ColorType } from "lightweight-charts";

export default function AdvancedChart() {
  const chartContainerRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Create chart instance with Astra dark theme
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#0b1020" },
        textColor: "#cbd5e1",
      },
      grid: {
        vertLines: { color: "#1e2a48", style: 1 },
        horzLines: { color: "#1e2a48", style: 1 },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: "#4f46e5", width: 1, style: 1, labelBackgroundColor: "#4f46e5" },
        horzLine: { color: "#4f46e5", width: 1, style: 1, labelBackgroundColor: "#4f46e5" },
      },
      timeScale: {
        borderColor: "#1e2a48",
        timeVisible: true,
        secondsVisible: false,
      },
      rightPriceScale: {
        borderColor: "#1e2a48",
      },
      width: chartContainerRef.current.clientWidth,
      height: 400,
    });

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    // Example candle data
    candleSeries.setData([
      { time: "2025-12-16", open: 100, high: 105, low: 97, close: 102 },
      { time: "2025-12-17", open: 102, high: 108, low: 101, close: 107 },
      { time: "2025-12-18", open: 107, high: 109, low: 104, close: 106 },
      { time: "2025-12-19", open: 106, high: 110, low: 103, close: 104 },
      { time: "2025-12-20", open: 104, high: 108, low: 100, close: 107 },
      { time: "2025-12-21", open: 107, high: 113, low: 106, close: 112 },
      { time: "2025-12-22", open: 112, high: 115, low: 109, close: 110 },
    ]);

    // Resize responsiveness
    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  return (
    <div className="bg-[#0b1020] border border-[#1e2a48] rounded-2xl p-6 mt-8 shadow-lg shadow-[#000]/50">
      <h2 className="text-xl font-semibold text-blue-400 mb-4 text-center">
        📊 Astra Advanced Market Intelligence
      </h2>
      <div ref={chartContainerRef} className="w-full h-[400px] rounded-xl overflow-hidden" />
    </div>
  );
}
