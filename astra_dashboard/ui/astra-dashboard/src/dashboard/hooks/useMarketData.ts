import { useEffect, useState } from "react";
import axios from "axios";

export function useMarketData() {
  const [stocks, setStocks] = useState<any[]>([]);
  const [cryptos, setCryptos] = useState<any[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await axios.get("http://127.0.0.1:8000/signals");
        setStocks(res.data.stocks || []);
        setCryptos(res.data.cryptos || []);
      } catch (e) {
        console.error(e);
      }
    };
    fetchData();
  }, []);

  return { stocks, cryptos };
}
