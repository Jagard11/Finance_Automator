from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Callable, TypeVar
import time

import pandas as pd
import requests
import yfinance as yf
import os

from prefetch import cache_dir as get_cache_dir

T = TypeVar("T")


def _with_retries(func: Callable[[], T], attempts: int = 3, base_delay: float = 2.0) -> Optional[T]:
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(base_delay * (2 ** i))
    # Final failure
    return None


def fetch_nasdaq_symbols() -> List[str]:
    url = "https://datahub.io/core/nasdaq-listings/r/nasdaq-listed-symbols.csv"
    df = pd.read_csv(url)
    symbol_col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    symbols = df[symbol_col].dropna().astype(str).str.upper().unique().tolist()
    return symbols


def fetch_price_history(symbol: str, start_date: str, end_date: str, avoid_network: bool = False) -> pd.DataFrame:
    # Prefer cached CSV from prefetch when available, then fall back to yfinance
    def _read_cache() -> Optional[pd.DataFrame]:
        path = os.path.join(get_cache_dir(), f"{symbol.upper()}_prices.csv")
        if not os.path.exists(path):
            return None
        try:
            # Parse the first column as date index explicitly to avoid per-row dateutil fallback
            df = pd.read_csv(path, index_col=0)
            # Ensure index is datetime
            df.index = pd.to_datetime(df.index, format="%Y-%m-%d", errors="coerce")
            df = df[~df.index.isna()]
            if df is None or df.empty:
                return None
            # Filter to requested window; cache uses index as date
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df.index >= start) & (df.index <= end)]
            return df
        except Exception:  # noqa: BLE001
            return None

    def _call_api() -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        data = ticker.history(start=start_date, end=end_date, auto_adjust=True, timeout=20)
        if not isinstance(data, pd.DataFrame) or data.empty:
            return pd.DataFrame()
        return data

    cached = _read_cache()
    if cached is not None and not cached.empty:
        return cached

    if avoid_network:
        return pd.DataFrame()

    result = _with_retries(_call_api)
    if result is None:
        return pd.DataFrame()
    return result


def fetch_dividends(symbol: str, start_date: str, end_date: str) -> pd.Series:
    ticker = yf.Ticker(symbol)
    div = ticker.dividends
    if div is None or div.empty:
        return pd.Series(dtype="float64")
    # Ensure index is tz-naive for safe comparison
    if isinstance(div.index, pd.DatetimeIndex) and div.index.tz is not None:
        div.index = div.index.tz_convert("UTC").tz_localize(None)
    # Filter by date range
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    return div[(div.index >= start) & (div.index <= end)]
