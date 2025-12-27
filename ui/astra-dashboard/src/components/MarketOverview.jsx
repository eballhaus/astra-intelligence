import React from "react";

const markets = [
  { name: "S&P 500", value: 4875.12, change: 0.31 },
  { name: "NASDAQ", value: 15724.33, change: 0.27 },
  { name: "Gold", value: 2045.72, change: -0.12 },
  { name: "Bitcoin", value: 51325.41, change: 0.56 },
];

export default function MarketOverview() {
  return (
    <div className="bg-[#141a2e] p-6 rounded-2xl shadow-lg border border-blue-800">
      <h3 className="text-lg font-semibold mb-4">Market Overview</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        {markets.map((m, i) => (
          <div key={i} className="flex flex-col items-center">
            <p className="text-gray-300">{m.name}</p>
            <p className="text-blue-300 font-semibold">{m.value}</p>
            <p className={m.change >= 0 ? "text-green-400" : "text-red-400"}>
              {m.change >= 0 ? "▲" : "▼"} {Math.abs(m.change)}%
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
