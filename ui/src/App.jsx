import SignalsPanel from "./components/SignalsPanel";
import PaperTradesPanel from "./components/PaperTradesPanel";
import MetricsPanel from "./components/MetricsPanel";

export default function App() {
  return (
    <div className="grid grid-cols-3 gap-4 p-6">
      <SignalsPanel />
      <PaperTradesPanel />
      <MetricsPanel />
    </div>
  );
}
