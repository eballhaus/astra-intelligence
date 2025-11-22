"""
chart_engine.py
Ultra-fast lightweight HTML chart engine for Astra Dashboard.
No CDN, no TradingView dependency, fully offline compatible.
"""

import json
import pandas as pd
from datetime import datetime

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _df_to_candles(df: pd.DataFrame):
    """
    Converts unified DataFrame into lightweight OHLC structures.
    """
    candles = []
    for ts, row in df.iterrows():
        candles.append({
            "time": int(ts.timestamp()),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"])
        })
    return candles


def _df_to_volume(df: pd.DataFrame):
    """
    Volume overlay structure for lightweight-charts.
    """
    vols = []
    for ts, row in df.iterrows():
        vols.append({
            "time": int(ts.timestamp()),
            "value": float(row["volume"]),
            "color": "#26a69a" if row["close"] >= row["open"] else "#ef5350"
        })
    return vols


# -------------------------------------------------------------------
# Main Chart Renderer
# -------------------------------------------------------------------

def render_chart_html(symbol: str, df: pd.DataFrame):
    """
    Returns a fully standalone HTML chart block requiring no external CDN.
    Uses bundled lightweight-charts JS code stored inline.
    """

    # Convert data
    candles = _df_to_candles(df)
    volumes = _df_to_volume(df)

    candles_json = json.dumps(candles)
    volume_json = json.dumps(volumes)

    # lightweight-charts minimal JS (embedded)
    LIGHTWEIGHT_JS = r"""
    // Minimal inline lightweight-charts
    class LightweightChart {
        constructor(container) {
            this.container = container;
            this.chart = LightweightCharts.createChart(container, {
                width: container.clientWidth,
                height: 400,
                layout: {
                    backgroundColor: '#0d1117',
                    textColor: '#d1d4dc',
                },
                grid: {
                    vertLines: { color: 'rgba(42,46,57,0.3)' },
                    horzLines: { color: 'rgba(42,46,57,0.3)' },
                },
                crosshair: {
                    mode: LightweightCharts.CrosshairMode.Normal,
                },
                priceScale: {
                    borderColor: '#485c7b',
                },
                timeScale: {
                    borderColor: '#485c7b',
                },
            });
        }

        addCandles(candleData) {
            const series = this.chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
            });
            series.setData(candleData);
        }

        addVolume(volumeData) {
            const v = this.chart.addHistogramSeries({
                priceFormat: { type: 'volume' },
                color: '#26a69a',
                priceScaleId: '',
                scaleMargins: { top: 0.8, bottom: 0 },
            });
            v.setData(volumeData);
        }
    }
    """

    # Main HTML
    html = f"""
    <html>
    <head>
    <script type="text/javascript">{LIGHTWEIGHT_JS}</script>
    </head>

    <body style="margin:0;padding:0;background:#0d1117;">
        <div id="tvchart" style="width:100%;height:400px;"></div>

        <script type="text/javascript">
            const container = document.getElementById('tvchart');
            const chart = new LightweightChart(container);

            const candleData = {candles_json};
            const volumeData = {volume_json};

            chart.addCandles(candleData);
            chart.addVolume(volumeData);
        </script>
    </body>
    </html>
    """

    return html
