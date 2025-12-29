import { useEffect, useState } from "react";
import axios from "axios";

export function useChartData(symbol: string) {
  const [candles, setCandles] = useState<any[]>([]);

  useEffect(() => {
    const fetchChart = async () => {
      try {
        const res = await axios.get("http://127.0.0.1:8000/chart");
        setCandles(res.data || []);
      } catch (e) {
        console.error(e);
      }
    };
    fetchChart();
  }, [symbol]);

  return candles;
}
