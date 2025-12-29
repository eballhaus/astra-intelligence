import React from "react";

import { useEffect, useState } from "react";
import { API_BASE_URL } from "../../config";

export default function Dashboard() {
  const [liveData, setLiveData] = useState(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${API_BASE_URL}/live`);
        const json = await res.json();
        setLiveData(json.data || json);
        console.log("✅ Live dashboard data:", json);
      } catch (err) {
        console.error("❌ Live API error:", err);
      }
    }
    fetchData();
    const id = setInterval(fetchData, 30000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{
      padding: "2rem",
      fontFamily: "system-ui, sans-serif",
      textAlign: "center"
    }}>
      <h1>🚀 Astra Dashboard React UI</h1>
      <p>Your front-end is successfully connected and running on Vite.</p>
    </div>
  );
}
// test rebuild Sun Dec 28 14:00:27 EST 2025
