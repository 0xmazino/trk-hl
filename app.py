import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- CONFIGURATION ---
st.set_page_config(page_title="Hyperliquid Tracker", layout="wide", page_icon="📈")

# --- BACKEND FUNCTIONS ---

def fetch_hyperliquid_data(address):
    """
    Fetches user fills (trades) and funding history from Hyperliquid API.
    """
    url = "https://api.hyperliquid.xyz/info"
    headers = {"Content-Type": "application/json"}
    
    # 1. Fetch User Fills (Trade History)
    # Note: Returns max 2000 most recent fills. 
    # For a full production app, you would loop through time to get everything.
    fills_payload = {
        "type": "userFills",
        "user": address
    }
    
    # 2. Fetch User Funding (Fees/Rebates)
    # We fetch usually from a starting timestamp. Defaults to last 6 months approx for this demo.
    start_time = int((datetime.now() - timedelta(days=180)).timestamp() * 1000)
    funding_payload = {
        "type": "userFunding",
        "user": address,
        "startTime": start_time
    }

    try:
        r_fills = requests.post(url, json=fills_payload, headers=headers)
        r_funding = requests.post(url, json=funding_payload, headers=headers)
        
        if r_fills.status_code != 200 or r_funding.status_code != 200:
            st.error("API Error: Could not fetch data.")
            return None, None

        fills_data = r_fills.json()
        funding_data = r_funding.json()
        
        return fills_data, funding_data
    except Exception as e:
        st.error(f"Connection Error: {e}")
        return None, None

def process_data(fills, funding):
    """
    Process raw JSON into clean DataFrames for analysis.
    """
    if not fills:
        return pd.DataFrame(), pd.DataFrame()

    # --- PROCESS TRADES ---
    df_fills = pd.DataFrame(fills)
    
    # Convert types
    numeric_cols = ['closedPnl', 'fee', 'sz', 'px', 'startPosition']
    for col in numeric_cols:
        df_fills[col] = pd.to_numeric(df_fills[col], errors='coerce')
        
    df_fills['time'] = pd.to_datetime(df_fills['time'], unit='ms')
    df_fills['date'] = df_fills['time'].dt.date
    
    # --- PROCESS FUNDING ---
    if funding:
        df_funding = pd.DataFrame(funding)
        df_funding['usdc'] = pd.to_numeric(df_funding['usdc'], errors='coerce')
        df_funding['time'] = pd.to_datetime(df_funding['time'], unit='ms')
        df_funding['date'] = df_funding['time'].dt.date
    else:
        df_funding = pd.DataFrame(columns=['time', 'date', 'usdc', 'coin'])

    return df_fills, df_funding

# --- FRONTEND UI ---

st.title("⚡ Hyperliquid Portfolio Tracker")
st.markdown("Enter your wallet address below to track Realized PnL, Fees, and Performance.")

# Sidebar for Input
with st.sidebar:
    st.header("Settings")
    wallet_address = st.text_input("Wallet Address (0x...)", placeholder="Paste address here")
    st.info("Note: This tracker runs locally in your browser/server. Your keys are not required, only public address.")
    
    if st.button("Load Data"):
        if len(wallet_address) < 42:
            st.error("Invalid address format.")
        else:
            st.session_state['data_loaded'] = True
            st.session_state['address'] = wallet_address

if st.session_state.get('data_loaded'):
    with st.spinner('Fetching data from Hyperliquid...'):
        raw_fills, raw_funding = fetch_hyperliquid_data(st.session_state['address'])
        
        if raw_fills:
            df_fills, df_funding = process_data(raw_fills, raw_funding)
            
            # --- CALCULATIONS ---
            
            # 1. Total Realized PnL (from closed trades)
            total_closed_pnl = df_fills['closedPnl'].sum()
            
            # 2. Total Fees (Trading fees + Funding)
            # Funding: Positive = Received (Rebate), Negative = Paid
            # Fees: Usually positive in data, so we subtract them
            total_trading_fees = df_fills['fee'].sum()
            total_funding = df_funding['usdc'].sum() if not df_funding.empty else 0
            
            net_pnl = total_closed_pnl - total_trading_fees + total_funding
            
            # 3. Win Rate
            # We filter for trades that actually closed a position (closedPnl != 0)
            closed_trades = df_fills[df_fills['closedPnl'] != 0]
            if len(closed_trades) > 0:
                wins = closed_trades[closed_trades['closedPnl'] > 0]
                win_rate = (len(wins) / len(closed_trades)) * 100
            else:
                win_rate = 0

            # --- DISPLAY METRICS ---
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Net PnL (Realized)", f"${net_pnl:,.2f}", delta_color="normal")
            c2.metric("Win Rate", f"{win_rate:.1f}%")
            c3.metric("Trading Fees", f"${total_trading_fees:,.2f}")
            c4.metric("Net Funding", f"${total_funding:,.2f}", help="Positive means you received funding")

            st.divider()

            # --- PREPARE CHART DATA ---
            # Group by day to make the chart readable
            
            # Aggregate Fills PnL by Day
            daily_fills = df_fills.groupby('date')[['closedPnl', 'fee']].sum().reset_index()
            
            # Aggregate Funding by Day
            if not df_funding.empty:
                daily_funding = df_funding.groupby('date')[['usdc']].sum().reset_index()
                daily_combined = pd.merge(daily_fills, daily_funding, on='date', how='outer').fillna(0)
            else:
                daily_combined = daily_fills
                daily_combined['usdc'] = 0

            # Calculate Daily Net
            daily_combined['daily_net_pnl'] = daily_combined['closedPnl'] - daily_combined['fee'] + daily_combined['usdc']
            daily_combined = daily_combined.sort_values('date')
            daily_combined['cumulative_pnl'] = daily_combined['daily_net_pnl'].cumsum()

            # --- TABBED VIEW ---
            tab1, tab2, tab3 = st.tabs(["📈 Performance Chart", "📅 Calendar / Heatmap", "📝 Trade Log"])

            with tab1:
                st.subheader("Cumulative PnL ($)")
                if not daily_combined.empty:
                    fig = px.line(daily_combined, x='date', y='cumulative_pnl', 
                                  title='Account Growth (Realized PnL + Fees + Funding)',
                                  labels={'cumulative_pnl': 'Net PnL ($)', 'date': 'Date'})
                    
                    # Add a zero line
                    fig.add_hline(y=0, line_dash="dash", line_color="gray")
                    
                    # Color the line green if positive, red if negative (simple logic)
                    line_color = '#00CC96' if daily_combined['cumulative_pnl'].iloc[-1] >= 0 else '#EF553B'
                    fig.update_traces(line_color=line_color)
                    
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("No PnL history found.")

            with tab2:
                st.subheader("Daily PnL Calendar")
                if not daily_combined.empty:
                    # Create a heatmap-style table or bar chart
                    fig_cal = px.bar(daily_combined, x='date', y='daily_net_pnl',
                                     color='daily_net_pnl',
                                     color_continuous_scale=['red', 'gray', 'green'],
                                     title="Daily Net Profit/Loss")
                    st.plotly_chart(fig_cal, use_container_width=True)
                    
                    st.write("### Daily Breakdown")
                    st.dataframe(daily_combined.sort_values('date', ascending=False), use_container_width=True)

            with tab3:
                st.subheader("Recent Trades")
                # Clean up the display dataframe
                display_df = df_fills[['time', 'coin', 'dir', 'px', 'sz', 'closedPnl', 'fee']].copy()
                display_df = display_df.rename(columns={
                    'dir': 'Direction', 'px': 'Price', 'sz': 'Size', 'closedPnl': 'PnL'
                })
                st.dataframe(display_df.style.applymap(
                    lambda x: 'color: green' if x > 0 else 'color: red' if x < 0 else 'color: gray',
                    subset=['PnL']
                ), use_container_width=True)

        else:
            st.warning("No data found for this address.")
