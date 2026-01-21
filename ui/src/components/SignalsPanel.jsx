import useAstraData from "../hooks/useAstraData";

export default function SignalsPanel() {
  const { data: signals, loading } = useAstraData("/api/signals");

  if (loading) return <p>Loading signals…</p>;
  if (!signals.length) return <p>No current signals.</p>;

  return (
    <div className="p-4">
      <h2 className="text-xl font-bold mb-2">Active Signals</h2>
      <ul className="space-y-1">
        {signals.map((sig, i) => (
          <li key={i} className="border p-2 rounded-md">
            <span className="font-semibold">{sig.symbol}</span> — {sig.action}
          </li>
        ))}
      </ul>
    </div>
  );
}
