import { DashboardGrid } from "../layout/DashboardGrid";
import "../styles/dashboard.css";

export default function DashboardPage() {
  return (
    <div className="dashboard-root">
      <header>
        <h1>Market Overview</h1>
        <div className="market-strip">
          <div className="market-item up">S&P 500: 5,203 ▲ +0.72%</div>
          <div className="market-item up">NASDAQ: 17,024 ▲ +0.68%</div>
          <div className="market-item down">DOW JONES: 38,142 ▼ -0.14%</div>
          <div className="market-item up">BTC: $51,320 ▲ +1.25%</div>
        </div>
      </header>

      <DashboardGrid />

      <footer>
        Astra Intelligence — Guardian v7 | Funnel v11 | Sentinel Tier 2
      </footer>
    </div>
  );
}
