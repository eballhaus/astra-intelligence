#!/bin/bash
echo "🚀 Astra All-in-One API Repair & Verification Starting..."

# ============================================================
# 1️⃣  Rebuild .env cleanly with all keys
# ============================================================
cat > .env <<'ENV'
FINNHUB_KEY=d42ee5hr01qorleqvvb0
FMP_KEY=xbgYJPXsiwJ3coLczphQSBsghO7fTklM
ALPHAVANTAGE_KEY=YJVYAJJSKKXF3ZQB
TWELVEDATA_KEY=452b5c89fc8747d4803ee6bda5f891b2
EODHD_KEY=6904e7a2ced028.25933984
EOD_KEY=6904e7a2ced028.25933984
MORALIS_KEY=your_moralis_api_key_here
ENV

# ============================================================
# 2️⃣  Load environment variables
# ============================================================
export $(grep -v '^#' .env | xargs)
echo "✅ Environment variables loaded."

# ============================================================
# 3️⃣  Test all APIs
# ============================================================
echo ""
echo "🌐 Testing TwelveData..."
curl -s "https://api.twelvedata.com/time_series?symbol=SPY&interval=1h&apikey=$TWELVEDATA_KEY&outputsize=3" | head -n 5

echo ""
echo "🌐 Testing Finnhub..."
curl -s "https://finnhub.io/api/v1/quote?symbol=SPY&token=$FINNHUB_KEY"

echo ""
echo "🌐 Testing EODHD..."
curl -s "https://eodhd.com/api/eod/SPY?api_token=$EODHD_KEY&fmt=json" | head -n 5

echo ""
echo "🌐 Testing Alpha Vantage..."
curl -s "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY&apikey=$ALPHAVANTAGE_KEY" | head -n 10

echo ""
echo "🌐 Testing FinancialModelingPrep..."
curl -s "https://financialmodelingprep.com/api/v3/historical-price-full/SPY?apikey=$FMP_KEY" | head -n 10

echo ""
echo "🌐 Testing Moralis..."
curl -s -H "X-API-Key: $MORALIS_KEY" "https://deep-index.moralis.io/api/v2/market-data/erc20/eth/usd/price"

# ============================================================
# 4️⃣  Run Astra Guardian API Health Monitor
# ============================================================
echo ""
echo "🧠 Running Astra Guardian API Health Monitor..."
python guardian/api_health_monitor.py

echo ""
echo "✅ All API systems checked. Review statuses above or in state/api_status.json"
