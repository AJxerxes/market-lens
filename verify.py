"""
Temporary Phase 2 diagnostic: Streamlit page showing companies table and Plotly price chart per ticker.
Delete when app.py is built in Phase 7.
Run: streamlit run verify.py
"""
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from market_lens.config import DATABASE_URL
import plotly.express as px

st.set_page_config(page_title="Market Lens Verify", layout="wide")
st.title("Market Lens — Phase 2 Verify")

engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    df = pd.read_sql(text("""
        SELECT ticker, name, current_price, market_cap, data_quality_flag,
               trailing_pe, sector
        FROM companies
        WHERE active = true
        ORDER BY ticker
    """), conn)
st.subheader("Companies (current price, market cap, data quality)")
st.dataframe(df, use_container_width=True)

ticker = st.selectbox("Select ticker for price chart", df["ticker"].tolist())
if ticker:
    with engine.connect() as conn:
        hist = pd.read_sql(text("""
            SELECT date, open, high, low, close, volume
            FROM price_history
            WHERE ticker = :t
            ORDER BY date
        """), conn, params={"t": ticker})
    if not hist.empty:
        fig = px.line(hist, x="date", y="close", title=f"{ticker} — Close Price")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No price history for this ticker.")
