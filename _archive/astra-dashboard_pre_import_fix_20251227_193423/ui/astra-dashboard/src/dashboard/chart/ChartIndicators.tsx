import { useState } from "react";

const indicators = [
  "SMA",
  "EMA",
  "VWAP",
  "RSI",
  "MACD",
  "Bollinger Bands",
  "Volume Profile",
  "Support/Resistance",
  "ATR",
  "Trendlines",
];

export function ChartIndicators({ onToggle }: { onToggle?: (name: string, enabled: boolean) => void }) {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(
    indicators.reduce((acc, i) => ({ ...acc, [i]: i === "SMA" || i === "EMA" || i === "Volume Profile" }), {})
  );

  const handleClick = (name: string) => {
    const next = !enabled[name];
    setEnabled({ ...enabled, [name]: next });
    if (onToggle) onToggle(name, next);
  };

  return (
    <div className="chart-controls">
      {indicators.map((i) => (
        <button
          key={i}
          onClick={() => handleClick(i)}
          className={`px-2 py-1 text-xs rounded-md ${
            enabled[i]
              ? "bg-blue-600 text-white border-blue-400"
              : "bg-transparent border-gray-600 text-gray-400"
          }`}
        >
          {i}
        </button>
      ))}
    </div>
  );
}
