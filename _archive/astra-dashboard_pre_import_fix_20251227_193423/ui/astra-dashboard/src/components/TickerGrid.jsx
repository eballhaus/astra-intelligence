import React from "react";
import { motion } from "framer-motion";

const mockData = [
  { symbol: "NVDA", type: "Stock", confidence: 97.4, grade: "A+", signal: "Strong Buy", price: 514.78, change: 0.32 },
  { symbol: "AAPL", type: "Stock", confidence: 94.2, grade: "A", signal: "Buy", price: 199.24, change: 0.18 },
  { symbol: "TSLA", type: "Stock", confidence: 91.6, grade: "A", signal: "Momentum", price: 271.38, change: 0.51 },
  { symbol: "MSFT", type: "Stock", confidence: 89.7, grade: "B+", signal: "Buy", price: 370.14, change: -0.09 },
  { symbol: "AMZN", type: "Stock", confidence: 87.3, grade: "B+", signal: "Hold", price: 149.23, change: -0.13 },
  { symbol: "GOOGL", type: "Stock", confidence: 92.8, grade: "A", signal: "Strong Buy", price: 140.56, change: 0.45 },
  { symbol: "BTC", type: "Crypto", confidence: 95.1, grade: "A+", signal: "Long Momentum", price: 51325.41, change: 0.72 },
  { symbol: "ETH", type: "Crypto", confidence: 93.3, grade: "A", signal: "Buy", price: 2471.65, change: 0.39 },
  { symbol: "SOL", type: "Crypto", confidence: 89.1, grade: "B+", signal: "Strong Buy", price: 78.31, change: 1.23 },
  { symbol: "ADA", type: "Crypto", confidence: 86.4, grade: "B", signal: "Buy", price: 0.62, change: 0.17 },
  { symbol: "XRP", type: "Crypto", confidence: 83.9, grade: "B", signal: "Hold", price: 0.54, change: -0.08 },
  { symbol: "AVAX", type: "Crypto", confidence: 91.2, grade: "A-", signal: "Strong Buy", price: 42.18, change: 1.11 },
];

export default function TickerGrid() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-6 mb-12">
      {mockData.map((a, i) => (
        <motion.div
          key={i}
          whileHover={{ scale: 1.05 }}
          className="bg-gradient-to-b from-[#182040] to-[#10182f] p-5 rounded-2xl shadow-lg border border-[#1e2a48]"
        >
          <div className="flex justify-between">
            <h3 className="text-lg font-semibold">{a.symbol}</h3>
            <span className="text-xs text-gray-400 uppercase">{a.type}</span>
          </div>
          <p className="text-2xl font-bold text-blue-300 mt-2">
            {a.confidence.toFixed(1)}%
          </p>
          <p className="text-sm text-gray-300">{a.grade}</p>
          <p className="text-sm text-gray-400 mt-1">{a.signal}</p>
          <div className="mt-2 flex justify-between text-sm">
            <span>${a.price.toFixed(2)}</span>
            <span className={a.change >= 0 ? "text-green-400" : "text-red-400"}>
              {a.change >= 0 ? "▲" : "▼"} {Math.abs(a.change).toFixed(2)}%
            </span>
          </div>
        </motion.div>
      ))}
    </div>
  );
}
