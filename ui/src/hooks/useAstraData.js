import { useState, useEffect } from "react";

export default function useAstraData(endpoint, interval = 10000) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;

    async function fetchData() {
      try {
        const res = await fetch("http://127.0.0.1:8000" + endpoint);
        const json = await res.json();
        if (active) setData(json);
      } catch (err) {
        if (active) setError(err.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    fetchData();
    const timer = setInterval(fetchData, interval);
    return () => { active = false; clearInterval(timer); };
  }, [endpoint, interval]);

  return { data, loading, error };
}
