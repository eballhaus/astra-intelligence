import { StockCardColumn } from "../cards/StockCardColumn";
import { CryptoCardColumn } from "../cards/CryptoCardColumn";
import { MainChart } from "../chart/MainChart";
import "../styles/dashboard.css";

export function DashboardGrid() {
  return (
    <main className="dashboard-grid">
      <div className="cards-container">
        <div className="cards-row">
          <StockCardColumn />
          <CryptoCardColumn />
        </div>
      </div>
      <section className="chart">
        <MainChart />
      </section>
    </main>
  );
}
