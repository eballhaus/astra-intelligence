import { useMarketData } from "../hooks/useMarketData";
import { AssetCard } from "./AssetCard";

export function StockCardColumn() {
  const { stocks } = useMarketData();
  return (
    <div>
      {stocks.map((s: any, i: number) => (
        <AssetCard key={i} asset={s} />
      ))}
    </div>
  );
}
