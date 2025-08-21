from __future__ import annotations

from datetime import datetime
import json
from typing import List, Optional, Callable, TypeVar, Tuple, Dict
import time

import pandas as pd
import requests
import yfinance as yf
import os

from prefetch import cache_dir as get_cache_dir
from settings import vprint, VERBOSE

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
    vprint("fetch_nasdaq_symbols: start")
    url = "https://datahub.io/core/nasdaq-listings/r/nasdaq-listed-symbols.csv"
    df = pd.read_csv(url)
    symbol_col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    symbols = df[symbol_col].dropna().astype(str).str.upper().unique().tolist()
    vprint(f"fetch_nasdaq_symbols: symbols={len(symbols)}")
    return symbols


def fetch_price_history(symbol: str, start_date: str, end_date: str, avoid_network: bool = False, prefer_cache: bool = True) -> pd.DataFrame:
    vprint(f"fetch_price_history: sym={symbol} {start_date}..{end_date} avoid_network={avoid_network} prefer_cache={prefer_cache}")
    # Prefer cached CSV from prefetch when available, then fall back to yfinance
    def _read_cache() -> Optional[pd.DataFrame]:
        path = os.path.join(get_cache_dir(), f"{symbol.upper()}_prices.csv")
        if not os.path.exists(path):
            return None
        try:
            header_only = pd.read_csv(path, nrows=0)
            columns = list(header_only.columns)
            price_col: Optional[str] = None
            for name in ("Close", "Adj Close", "Adj_Close"):
                if name in columns:
                    price_col = name
                    break
            if price_col is not None:
                usecols = [0, price_col]
            else:
                usecols = [0]
                if len(columns) > 1:
                    usecols.append(columns[1])
            df = pd.read_csv(path, index_col=0, usecols=usecols, memory_map=True)
            # Ensure index is datetime (accept date or datetime) and tz-naive
            idx = pd.to_datetime(df.index, errors="coerce")
            try:
                idx = idx.tz_localize(None)
            except Exception:
                pass
            mask = ~idx.isna()
            if not mask.any():
                return None
            df = df.loc[mask]
            df.index = idx[mask]
            if df.empty:
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
        # Ensure tz-naive index to avoid compare errors downstream
        try:
            if isinstance(data.index, pd.DatetimeIndex) and data.index.tz is not None:
                data.index = data.index.tz_convert("UTC").tz_localize(None)
        except Exception:
            try:
                # Some yfinance versions use tz-aware without tzinfo set directly
                data.index = pd.to_datetime(data.index, errors="coerce").tz_localize(None)
            except Exception:
                pass
        return data

    cached = _read_cache() if prefer_cache else None
    if cached is not None and not cached.empty:
        vprint(f"fetch_price_history: cache hit rows={len(cached)} cols={list(cached.columns)}")
        return cached

    if avoid_network:
        vprint("fetch_price_history: avoid_network; returning empty")
        return pd.DataFrame()

    result = _with_retries(_call_api)
    if result is None:
        vprint("fetch_price_history: api failed")
        return pd.DataFrame()
    vprint(f"fetch_price_history: api rows={len(result)}")
    return result


def fetch_dividends(symbol: str, start_date: str, end_date: str) -> pd.Series:
    vprint(f"fetch_dividends: sym={symbol} {start_date}..{end_date}")
    ticker = yf.Ticker(symbol)
    div = ticker.dividends
    if div is None or div.empty:
        vprint("fetch_dividends: empty")
        return pd.Series(dtype="float64")
    # Ensure index is tz-naive for safe comparison
    if isinstance(div.index, pd.DatetimeIndex) and div.index.tz is not None:
        div.index = div.index.tz_convert("UTC").tz_localize(None)
    # Filter by date range
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    out = div[(div.index >= start) & (div.index <= end)]
    vprint(f"fetch_dividends: rows={len(out)}")
    return out


def fetch_dividend_payment_dates(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Best-effort fetch of dividend payment dates.

    yfinance exposes a dividends Series indexed by ex-dividend date. Payment dates are not
    directly available reliably; attempt to use corporate actions if available, else return empty.
    Returns DataFrame with columns: ex_date (datetime64), payment_date (datetime64), amount (float).
    """
    try:
        ticker = yf.Ticker(symbol)
        # Some versions expose actions with Dividends; often only ex-date. Keep code defensive.
        actions = getattr(ticker, "actions", None)
        if isinstance(actions, pd.DataFrame) and not actions.empty and "Dividends" in actions.columns:
            df = actions.copy()
            # Add ex_date as index; try payment date if present in index/columns (rare)
            df = df.reset_index().rename(columns={df.columns[0]: "date", "Dividends": "amount"})
            df["ex_date"] = pd.to_datetime(df["date"], errors="coerce")
            df["payment_date"] = pd.NaT  # unknown by default
            df = df.dropna(subset=["ex_date"])  # require ex-date
            # Filter window
            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            df = df[(df["ex_date"] >= start) & (df["ex_date"] <= end)]
            return df[["ex_date", "payment_date", "amount"]]
    except Exception:
        pass
    return pd.DataFrame(columns=["ex_date", "payment_date", "amount"]).astype({"ex_date": "datetime64[ns]"})


# ---- Realtime price caching ----

def realtime_price_cache_path(symbol: str) -> str:
    return os.path.join(get_cache_dir(), f"{symbol.upper()}_realtime.json")


def read_realtime_price(symbol: str) -> Tuple[Optional[float], Optional[datetime]]:
    path = realtime_price_cache_path(symbol)
    if not os.path.exists(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        price = None
        ts = None
        try:
            price = float(data.get("price"))
        except Exception:
            price = None
        tval = data.get("timestamp")
        if isinstance(tval, (int, float)):
            try:
                ts = datetime.fromtimestamp(float(tval))
            except Exception:
                ts = None
        elif isinstance(tval, str):
            try:
                ts = pd.to_datetime(tval, errors="coerce").to_pydatetime()
            except Exception:
                ts = None
        return price, ts
    except Exception:
        return None, None


def fetch_realtime_price(symbol: str) -> Optional[float]:
    vprint(f"fetch_realtime_price: {symbol}")
    try:
        ticker = yf.Ticker(symbol)
        try:
            df = ticker.history(period="1d", interval="1m", auto_adjust=True, timeout=20)
        except Exception:
            df = ticker.history(period="1d", interval="1m", auto_adjust=True)
        if isinstance(df, pd.DataFrame) and not df.empty:
            series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
            s = series.dropna()
            if not s.empty:
                return float(s.iloc[-1])
        # Fallback to fast_info/regularPrice if available
        try:
            info = getattr(ticker, "fast_info", None)
            if info and hasattr(info, "last_price"):
                return float(info.last_price)
        except Exception:
            pass
    except Exception:
        pass
    return None


def update_realtime_price_cache(symbol: str) -> bool:
    price = fetch_realtime_price(symbol)
    if price is None:
        return False
    data = {"symbol": symbol.upper(), "price": float(price), "timestamp": datetime.now().isoformat()}
    try:
        path = realtime_price_cache_path(symbol)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False


def fetch_realtime_prices_batch(symbols: List[str]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    for s in symbols:
        try:
            out[s] = fetch_realtime_price(s)
        except Exception:
            out[s] = None
    return out


def write_realtime_snapshot(symbol_to_price: Dict[str, float], snapshot_ts: Optional[datetime] = None) -> int:
    ts = snapshot_ts or datetime.now()
    wrote = 0
    for s, p in symbol_to_price.items():
        try:
            path = realtime_price_cache_path(s)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"symbol": s.upper(), "price": float(p), "timestamp": ts.isoformat()}, f)
            wrote += 1
        except Exception:
            continue
    return wrote
