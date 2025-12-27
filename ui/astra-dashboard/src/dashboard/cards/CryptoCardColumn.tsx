import { useMarketData } from "../hooks/useMarketData";
import { AssetCard } from "./AssetCard";

export function CryptoCardColumn() {
  const { cryptos } = useMarketData();
  return (
    <div>
      {cryptos.map((c: any, i: number) => (
        <AssetCard key={i} asset={c} />
      ))}
    </div>
  );
}
