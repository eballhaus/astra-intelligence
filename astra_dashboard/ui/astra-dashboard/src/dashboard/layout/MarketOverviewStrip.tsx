import { useEffect, useState } from "react";
import axios from "axios";
import "../styles/market.css";

export function MarketOverviewStrip() {
  const [data, setData] = useState<any[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await axios.get("http://127.0.0.1:8000/signals");
        const s = res.data;
        setData([
          { symbol: "S&P 500", price: 5125.21, change: 0.45 },
          { symbol: "NASDAQ", price: 16231.14, change: 0.38 },
          { symbol: "Dow Jones", price: 38291.55, change: 0.22 },
          { symbol: "Bitcoin", price: s.cryptos?.[0]?.price ?? 51325, change: s.cryptos?.[0]?.change ?? 0.7 },
        ]);
      } catch (e) {
        console.error(e);
      }
    };
    fetchData();
  }, []);

  return (
    <section className="market-strip">
      <span className="label">Market Overview:</span>
      {data.map((a, i) => (
        <div key={i} className="item">
          <span className="label">{a.symbol}</span>
          <span className={`value ${a.change >= 0 ? "up" : "down"}`}>
            {a.price.toFixed(2)} ({a.change >= 0 ? "▲" : "▼"}{a.change.toFixed(2)}%)
          </span>
        </div>
      ))}
    </section>
  );
}
