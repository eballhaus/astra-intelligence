import React, { useEffect, useState } from "react";

export default function Dashboard() {
  const [data, setData] = useState([]);
  const [status, setStatus] = useState("connecting");

  useEffect(() => {
    async function loadData() {
      try {
        const res = await fetch("http://localhost:8000/api/live-data");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        setData(json);
        setStatus("connected");
      } catch (err) {
        console.error("Live data fetch failed:", err);
        setStatus("offline");
      }
    }

    loadData();
    const interval = setInterval(loadData, 60000); // refresh every minute
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="dashboard-root p-4">
      <h2 className="text-xl font-bold mb-2">Live Market Feed</h2>
      <p className={`mb-4 ${status === "connected" ? "text-green-600" : "text-red-600"}`}>
        Status: {status}
      </p>
      <ul className="space-y-1">
        {data.map((item) => (
          <li key={item.symbol}>
            {item.symbol}: ${item.price.toFixed(2)} ({item.grade})
          </li>
        ))}
      </ul>
    </div>
  );
}
