import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from ui.dashboard.dashboard_data import load_data

def render_chart(symbol):
    st.markdown(f'### 📈 Astra Performance Chart — {symbol}')
    try:
        data = load_data(symbol)
        if data is None or data.empty:
            st.warning(f'⚠️ No data available for {symbol}')
            return

        df = pd.DataFrame(data)
        if 'time' not in df.columns:
            df['time'] = range(len(df))

        fig = go.Figure(data=[go.Candlestick(
            x=pd.to_datetime(df.get('time', range(len(df)))),
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            increasing_line_color='green',
            decreasing_line_color='red',
            name='Price'
        )])

        # Add moving averages
        df['MA5'] = df['close'].rolling(5).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(df.get('time', range(len(df)))),
            y=df['MA5'], line=dict(color='blue', width=1.2),
            name='5-MA'
        ))
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(df.get('time', range(len(df)))),
            y=df['MA20'], line=dict(color='orange', width=1.2),
            name='20-MA'
        ))

        fig.update_layout(
            height=420, template='plotly_dark',
            xaxis_rangeslider_visible=False,
            margin=dict(l=20, r=20, t=40, b=20),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
        )

        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f'❌ Chart error for {symbol}: {e}')
