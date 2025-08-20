from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Dict, Optional, Set

import pandas as pd

import storage
from models import Portfolio, Holding, EventType
from market_data import fetch_price_history
from prefetch import cache_dir as get_cache_dir
from settings import vprint


_DIRTY_FILE = os.path.join(get_cache_dir(), "dirty_symbols.json")


def values_cache_path(symbol: str) -> str:
    return os.path.join(get_cache_dir(), f"{symbol.upper()}_values.csv")


def _read_dirty() -> Set[str]:
    try:
        with open(_DIRTY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(str(s).upper() for s in data)
    except Exception:
        pass
    return set()


def _write_dirty(symbols: Set[str]) -> None:
    os.makedirs(os.path.dirname(_DIRTY_FILE), exist_ok=True)
    with open(_DIRTY_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(list(symbols)), f, indent=2)


def mark_symbol_dirty(symbol: str) -> None:
    syms = _read_dirty()
    syms.add(symbol.upper())
    _write_dirty(syms)


def clear_symbol_dirty(symbol: str) -> None:
    syms = _read_dirty()
    if symbol.upper() in syms:
        syms.remove(symbol.upper())
        _write_dirty(syms)


def read_values_cache(symbol: str) -> pd.DataFrame:
    vprint(f"read_values_cache: {symbol}")
    path = values_cache_path(symbol)
    if not os.path.exists(path):
        vprint("read_values_cache: missing")
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        df.sort_values("date", inplace=True)
        vprint(f"read_values_cache: rows={len(df)}")
        return df
    except Exception:
        vprint("read_values_cache: error")
        return pd.DataFrame()


def compute_and_write_values_for_holding(holding: Holding, start_iso: str, end_iso: Optional[str] = None) -> bool:
    vprint(f"compute_and_write_values_for_holding: {holding.symbol} {start_iso}->{end_iso}")
    symbol = holding.symbol.upper()
    end_iso = end_iso or date.today().isoformat()
    # Fetch prices
    end_plus = (date.fromisoformat(end_iso) + timedelta(days=1)).isoformat()
    df = fetch_price_history(symbol, start_iso, end_plus)
    if df is None or df.empty:
        # Still write empty to indicate attempted
        vprint("compute_and_write_values_for_holding: empty prices")
        pd.DataFrame({"date": [], "shares": [], "value": []}).to_csv(values_cache_path(symbol), index=False)
        return False
    series = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
    series = series.dropna()
    idx = series.index
    # Build shares cumulative series on same index
    changes = pd.Series(0.0, index=idx)
    for ev in sorted(holding.events, key=lambda e: e.date):
        if not ev.date:
            continue
        try:
            ts = pd.Timestamp(ev.date)
        except Exception:
            continue
        # Align event to the first index at or after the event date
        pos = changes.index.searchsorted(ts, side="left")
        if pos >= len(changes.index):
            # Event after last known price; skip
            continue
        if ev.type == EventType.PURCHASE:
            changes.iloc[pos] += float(ev.shares or 0.0)
        elif ev.type == EventType.SALE:
            changes.iloc[pos] -= float(ev.shares or 0.0)
    shares = changes.cumsum()
    values = (shares * series).fillna(0.0)
    out = pd.DataFrame({"date": values.index.date, "shares": shares.values, "value": values.values})
    os.makedirs(os.path.dirname(values_cache_path(symbol)), exist_ok=True)
    out.to_csv(values_cache_path(symbol), index=False)
    vprint(f"compute_and_write_values_for_holding: wrote rows={len(out)} -> {values_cache_path(symbol)}")
    return True


def warm_values_cache_for_portfolio(portfolio_path: str) -> int:
    vprint(f"warm_values_cache_for_portfolio: {portfolio_path}")
    portfolio = storage.load_portfolio(portfolio_path)
    changes = 0
    port_mtime = os.path.getmtime(portfolio_path) if os.path.exists(portfolio_path) else 0.0
    dirty = _read_dirty()
    for h in portfolio.holdings:
        symbol = h.symbol.upper()
        # Determine if cache missing or stale or marked dirty
        cache_path = values_cache_path(symbol)
        cache_mtime = os.path.getmtime(cache_path) if os.path.exists(cache_path) else 0.0
        if (not os.path.exists(cache_path)) or (cache_mtime < port_mtime) or (symbol in dirty):
            # Compute from first event to today
            dates = [ev.date for ev in h.events if ev.date]
            if not dates:
                continue
            start_iso = min(dates)
            if compute_and_write_values_for_holding(h, start_iso):
                changes += 1
            clear_symbol_dirty(symbol)
    vprint(f"warm_values_cache_for_portfolio: updated={changes}")
    return changes
