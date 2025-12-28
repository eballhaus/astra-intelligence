export default function FunnelWidget({ stages }) {
  return (
    <div className="bg-blue-950/60 rounded-2xl p-4 border border-blue-800/40 shadow-md">
      <h3 className="text-cyan-300 font-semibold mb-2">🧭 Astra Funnel</h3>
      <ol className="space-y-1 text-sm text-gray-300">
        {stages.map((s, i) => (
          <li key={i}>
            <span className="text-cyan-400">{i + 1}.</span> {s.name} — {s.status}
          </li>
        ))}
      </ol>
    </div>
  );
}
