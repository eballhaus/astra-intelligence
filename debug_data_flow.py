#!/usr/bin/env python3
"""
Astra Intelligence — Data Flow Debugger
----------------------------------------
Traces where bad data is coming from in your Astra system.
"""

import sys
import os
from datetime import datetime
import pandas as pd

# Add current directory to path
sys.path.append(".")


def debug_data_flow(symbol="AAPL"):
    print(f"\n{'='*60}")
    print(f"🔍 DEBUGGING DATA FLOW FOR: {symbol}")
    print(f"{'='*60}")

    # Test 1: Direct AstraAPI call
    print("\n📡 Test 1: Direct AstraAPI call")
    try:
        from astra_core.core.api_client import AstraAPI

        api = AstraAPI()
        df_api = api.get_market_data(symbol)
        print(f"   Shape: {df_api.shape}")
        print(f"   Columns: {list(df_api.columns)}")
        if not df_api.empty:
            print("   First 2 rows:")
            print(df_api.head(2).to_string())
            if hasattr(df_api, "attrs"):
                print(f"   Attributes: {df_api.attrs}")
                print(f"   Source: {df_api.attrs.get('source', 'NOT SET')}")
            else:
                print("   No attributes found!")

            # Check if prices look realistic
            if "close" in df_api.columns:
                avg_price = df_api["close"].mean()
                print(f"   Average price: ${avg_price:.2f}")
                realistic = True
                if symbol == "AAPL" and (avg_price < 100 or avg_price > 300):
                    realistic = False
                    print(
                        f"   ⚠️ AAPL price unrealistic! Expected $150-250, got ${avg_price:.2f}"
                    )
                print(f"   Realistic price? {'✅ YES' if realistic else '❌ NO'}")
        else:
            print("   DataFrame is empty!")
    except Exception as e:
        print(f"   ❌ AstraAPI error: {e}")
        import traceback

        traceback.print_exc()

    # Test 2: Dashboard data loader
    print("\n📊 Test 2: Dashboard data loader")
    try:
        from astra_core.ui.dashboard.dashboard_data import load_data

        df_dash = load_data(symbol)
        print(f"   Shape: {df_dash.shape}")
        print(f"   Columns: {list(df_dash.columns)}")
        if not df_dash.empty:
            print(f"   Source from attrs: {df_dash.attrs.get('source', 'NOT SET')}")
            print(
                f"   First close: {df_dash['close'].iloc[0] if 'close' in df_dash.columns else 'MISSING'}"
            )
            print(
                f"   Last close: {df_dash['close'].iloc[-1] if 'close' in df_dash.columns else 'MISSING'}"
            )

            # Check for synthetic data patterns
            if "close" in df_dash.columns:
                unique_prices = df_dash["close"].nunique()
                print(f"   Unique prices: {unique_prices}")
                if unique_prices == 1:
                    print("   ⚠️ Only one price value - likely synthetic!")
    except Exception as e:
        print(f"   ❌ Dashboard data error: {e}")

    # Test 3: Check fetch_unified
    print("\n🌐 Test 3: fetch_unified module")
    try:
        # Try different import paths
        try:
            from fetch_unified import get_symbol_data
        except ImportError:
            try:
                import sys

                sys.path.append(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
                from fetch_unified import get_symbol_data
            except ImportError:
                print("   ❌ fetch_unified not found in any path")
                return

        df_unified = get_symbol_data(symbol, period="1d", interval="1m")
        print(f"   Shape: {df_unified.shape}")
        print(f"   Columns: {list(df_unified.columns)}")
        if not df_unified.empty:
            if hasattr(df_unified, "attrs"):
                print(
                    f"   Source from attrs: {df_unified.attrs.get('source', 'NOT SET')}"
                )
            print(
                f"   Latest price: {df_unified['close'].iloc[-1] if 'close' in df_unified.columns else 'MISSING'}"
            )

            # Check price range
            if "close" in df_unified.columns:
                price_range = df_unified["close"].max() - df_unified["close"].min()
                print(f"   Price range: ${price_range:.2f}")
        else:
            print("   DataFrame is empty!")
    except Exception as e:
        print(f"   ❌ fetch_unified error: {e}")

    # Test 4: Check backend API directly
    print("\n🔌 Test 4: Direct backend API call")
    try:
        import requests

        backend_url = os.getenv("ASTRA_BACKEND_URL", "http://127.0.0.1:8000")
        print(f"   Backend URL: {backend_url}")

        response = requests.get(f"{backend_url}/v1/data/{symbol}", timeout=10)
        print(f"   Status code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and "data" in data:
                df_backend = pd.DataFrame(data["data"])
                print(f"   Shape: {df_backend.shape}")
                if not df_backend.empty and "close" in df_backend.columns:
                    print(f"   Latest price: ${df_backend['close'].iloc[-1]:.2f}")
            else:
                print(f"   Response structure: {type(data)}")
                if isinstance(data, list):
                    print(f"   List length: {len(data)}")
    except Exception as e:
        print(f"   ❌ Backend API error: {e}")


def main():
    print("🧠 Astra Data Flow Debugger")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version}")

    # Check environment variables
    print("\n🔧 Environment Variables:")
    env_vars = [
        "ASTRA_API_BASE",
        "ASTRA_API_KEY",
        "ASTRA_BACKEND_URL",
        "ASTRA_LIVE_MODE",
    ]
    for var in env_vars:
        value = os.getenv(var)
        print(f"   {var}: {'✅ SET' if value else '❌ NOT SET'}")

    for symbol in ["AAPL", "BTC/USD"]:
        debug_data_flow(symbol)


if __name__ == "__main__":
    main()
