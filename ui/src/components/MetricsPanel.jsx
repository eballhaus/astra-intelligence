import useAstraData from "../hooks/useAstraData";

export default function MetricsPanel() {
  const { data: metrics, loading } = useAstraData("/api/performance_metrics");

  if (loading) return <p>Loading metrics…</p>;
  if (!metrics.length) return <p>No metrics yet.</p>;

  const latest = metrics[metrics.length - 1];
  return (
    <div className="p-4">
      <h2 className="text-xl font-bold mb-2">Performance Metrics</h2>
      <ul>
        <li>Win Rate: {latest.win_rate ?? "–"}</li>
        <li>Loss Rate: {latest.loss_rate ?? "–"}</li>
        <li>Expectancy: {latest.expectancy ?? "–"}</li>
        <li>Trades: {latest.realized_trades ?? 0}</li>
        <li>Status: {latest.status}</li>
      </ul>
    </div>
  );
}
