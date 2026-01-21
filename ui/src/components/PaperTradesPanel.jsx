import useAstraData from "../hooks/useAstraData";

export default function PaperTradesPanel() {
  const { data: trades, loading } = useAstraData("/api/paper_trades");

  if (loading) return <p>Loading trades…</p>;
  if (!trades.length) return <p>No open paper trades.</p>;

  return (
    <div className="p-4">
      <h2 className="text-xl font-bold mb-2">Paper Trades</h2>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th>Symbol</th><th>Entry</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i} className="border-b">
              <td>{t.symbol}</td>
              <td>{t.entry}</td>
              <td>{t.status || "open"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
