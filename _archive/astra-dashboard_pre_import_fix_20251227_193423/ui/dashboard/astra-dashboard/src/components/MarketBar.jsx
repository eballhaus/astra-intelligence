import React, { useEffect, useState } from "react";
import axios from "axios";

const MarketBar = () => {
  const [indices, setIndices] = useState([]);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await axios.get("/api/market_overview");
        setIndices(res.data);
      } catch (e) {
        console.error("Error fetching market overview:", e);
      }
    }
    fetchData();
  }, []);

  return (
    <div className="flex justify-between text-sm text-gray-700 mb-4">
      {indices.map((idx) => (
        <div key={idx.name} className="flex items-center gap-1">
          <span className="font-bold">{idx.name}</span>
          <span>{idx.value}</span>
          <span className={idx.change >= 0 ? "text-green-500" : "text-red-500"}>
            {idx.change >= 0 ? "▲" : "▼"} {idx.change.toFixed(2)}%
          </span>
        </div>
      ))}
    </div>
  );
};

export default MarketBar;
