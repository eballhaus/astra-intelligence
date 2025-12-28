export default function TickerCard({ symbol, grade, price, prediction, stop, confidence, brainScore, insight }) {
  return (
    <div className="bg-gradient-to-b from-blue-900 to-gray-900 rounded-2xl p-5 shadow-lg border border-blue-700/40 hover:scale-[1.02] transition-all duration-200">
      <h2 className="text-2xl font-bold mb-1">{symbol}</h2>
      <p className="text-sm text-gray-400 mb-3">
        Grade: <span className="text-green-400 font-semibold">{grade}</span>
      </p>
      <div className="space-y-1 text-sm">
        <p>💰 <b>Live Price:</b> ${price?.toFixed(2) || "--"}</p>
        <p>📈 <b>Prediction:</b> ${prediction.value} ({prediction.percent}%)</p>
        <p>🛑 <b>Stop-Loss:</b> ${stop.value} ({stop.percent}%)</p>
        <p>📊 <b>Confidence:</b> {confidence}%</p>
        <p>🧠 <b>Brain Score:</b> {brainScore}%</p>
      </div>
      <div className="mt-3 p-2 bg-blue-800/30 rounded-xl text-sm italic border-t border-blue-700/30">
        {insight}
      </div>
    </div>
  );
}
