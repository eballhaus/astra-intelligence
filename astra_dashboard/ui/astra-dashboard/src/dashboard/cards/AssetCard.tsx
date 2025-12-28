interface AssetCardProps {
  asset: any;
}

export function AssetCard({ asset }: AssetCardProps) {
  const color =
    asset.signal?.includes("Strong Buy")
      ? "text-green-400"
      : asset.signal?.includes("Buy")
      ? "text-yellow-400"
      : asset.signal?.includes("Hold")
      ? "text-orange-400"
      : "text-red-400";

  return (
    <div className="asset-card p-3 rounded-xl bg-[#101827] border border-gray-700 mb-3 hover:border-blue-500 transition-colors">
      <div className="flex justify-between items-center">
        <h3 className="font-semibold">{asset.symbol}</h3>
        <span className={color}>{asset.confidence?.toFixed(1)}%</span>
      </div>
      <div className="text-sm mt-1">
        <p>{asset.type.toUpperCase()}</p>
        <p className="text-xl font-bold">{asset.price.toFixed(2)}</p>
        <p className={asset.change >= 0 ? "text-green-400" : "text-red-400"}>
          {asset.change >= 0 ? "+" : ""}
          {asset.change.toFixed(2)}%
        </p>
        <p className="text-sm mt-1 opacity-70">{asset.signal}</p>
      </div>
    </div>
  );
}
