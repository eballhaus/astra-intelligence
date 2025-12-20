#!/bin/bash
set -e

echo "🔥 NUCLEAR OPTION: Complete Dashboard Rebuild"
echo ""

cd ~/Desktop/astra-intelligence

echo "🗑️  Step 1: Removing broken ui/dashboard/tab_dashboard.py..."
rm -f ui/dashboard/tab_dashboard.py
echo "✅ Deleted"

echo ""
echo "✅ Step 2: Verifying clean dashboard exists..."
if [ ! -f "ui/dashboard/tab_dashboard_v7.py" ]; then
    echo "❌ tab_dashboard_v7.py missing! Creating..."
    cat > ui/dashboard/tab_dashboard_v7.py << 'CLEANBOARD'
# -*- coding: utf-8 -*-
"""
Astra Intelligence - Clean Dashboard
No broken imports, works with Streamlit
"""

import streamlit as st
from learning.funnel.astra_funnel import AstraFunnel

def render_dashboard():
    st.header("📊 Astra Intelligence Dashboard")
    try:
        funnel = AstraFunnel()
        predictions = funnel.run()
        if not predictions:
            st.info("⚠️ No predictions available yet.")
            return
        stocks = [p for p in predictions if "/" not in p.get("symbol", "")]
        cryptos = [p for p in predictions if "/" in p.get("symbol", "")]
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📈 Top Stocks")
            for stock in stocks[:3]:
                with st.container(border=True):
                    st.write(f"**{stock.get('symbol', 'N/A')}**")
                    st.write(f"Grade: {stock.get('grade', 'N/A')}")
                    st.write(f"Confidence: {stock.get('confidence', 0):.1f}%")
        with col2:
            st.subheader("💹 Top Cryptos")
            for crypto in cryptos[:3]:
                with st.container(border=True):
                    st.write(f"**{crypto.get('symbol', 'N/A')}**")
                    st.write(f"Grade: {crypto.get('grade', 'N/A')}")
                    st.write(f"Confidence: {crypto.get('confidence', 0):.1f}%")
        st.divider()
        s1, s2, s3 = st.columns(3)
        with s1:
            st.metric("Total Picks", len(predictions))
        with s2:
            avg = sum(p.get("confidence", 0) for p in predictions) / len(predictions) if predictions else 0
            st.metric("Avg Confidence", f"{avg:.1f}%")
        with s3:
            a_picks = sum(1 for p in predictions if p.get("grade", "").startswith("A"))
            st.metric("A-Grade Picks", a_picks)
    except Exception as e:
        st.error(f"❌ Dashboard Error: {str(e)}")
        import traceback
        st.write(traceback.format_exc())
CLEANBOARD
else
    echo "✅ Clean dashboard found"
fi

echo ""
echo "🔧 Step 3: Fixing app.py to use clean dashboard..."
sed -i.bak 's/from ui.dashboard.tab_dashboard import/from ui.dashboard.tab_dashboard_v7 import/g' app.py
sed -i.bak 's/render_dashboard_tab/render_dashboard as render_dashboard_tab/g' app.py
echo "✅ app.py fixed"

echo ""
echo "🧹 Step 4: Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
rm -rf ~/.streamlit/cache ~/.cache/streamlit .streamlit 2>/dev/null
echo "✅ Cache cleared"

echo ""
echo "📦 Step 5: Ensuring all packages have __init__.py..."
touch engine/__init__.py
touch core/__init__.py
touch ui/__init__.py
touch ui/dashboard/__init__.py
echo "✅ Package structure ready"

echo ""
echo "================================"
echo "🚀 LAUNCHING ASTRA"
echo "================================"
echo ""
echo "✅ Open browser: http://localhost:8501"
echo ""

PYTHONPATH=. streamlit run app.py

