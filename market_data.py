from __future__ import annotations

from datetime import datetime
from typing import List

import pandas as pd
import requests
import yfinance as yf


def fetch_nasdaq_symbols() -> List[str]:
    url = "https://datahub.io/core/nasdaq-listings/r/nasdaq-listed-symbols.csv"
    df = pd.read_csv(url)
    symbol_col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    symbols = df[symbol_col].dropna().astype(str).str.upper().unique().tolist()
    return symbols


def fetch_price_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    data = yf.download(symbol, start=start_date, end=end_date, progress=False, auto_adjust=True)
    if not isinstance(data, pd.DataFrame) or data.empty:
        return pd.DataFrame()
    return data


def fetch_dividends(symbol: str, start_date: str, end_date: str) -> pd.Series:
    ticker = yf.Ticker(symbol)
    div = ticker.dividends
    if div is None or div.empty:
        return pd.Series(dtype="float64")
    # Filter by date range
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    return div[(div.index >= start) & (div.index <= end)]
