import { useChartData } from "../hooks/useChartData";
import { createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { ChartIndicators } from "./ChartIndicators";

export function MainChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const data = useChartData("NVDA");

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: { background: { color: "#0b1120" }, textColor: "#fff" },
      grid: { vertLines: { color: "#1e293b" }, horzLines: { color: "#1e293b" } },
      width: containerRef.current.clientWidth,
      height: 480,
    });
    const candleSeries = chart.addCandlestickSeries();
    candleSeries.setData(
      data.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
    );
    return () => chart.remove();
  }, [data]);

  return (
    <div className="flex flex-col gap-2">
      <ChartIndicators />
      <div ref={containerRef} className="chart-container"></div>
    </div>
  );
}
