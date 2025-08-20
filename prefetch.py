from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Iterable, Set

import pandas as pd
import yfinance as yf
from settings import vprint

import storage


def cache_dir() -> str:
	base = storage.default_data_dir()
	path = os.path.join(base, "cache")
	os.makedirs(path, exist_ok=True)
	return path


def collect_all_symbols() -> Set[str]:
	symbols: Set[str] = set()
	for path in storage.list_portfolio_paths():
		portfolio = storage.load_portfolio(path)
		for holding in portfolio.holdings:
			if holding.symbol:
				symbols.add(holding.symbol.upper())
	return symbols


def _save_dataframe_csv(df: pd.DataFrame, path: str) -> None:
	df.to_csv(path, index=True)


def _save_series_csv(series: pd.Series, path: str) -> None:
	series.to_csv(path, header=["value"])


def _is_valid_prices_cache(df: pd.DataFrame) -> bool:
	if df is None or df.empty:
		return False
	# Accept either Close or Adj Close (or similar)
	cols = set(df.columns)
	return ("Close" in cols) or ("Adj Close" in cols) or ("Adj_Close" in cols) or (len(cols) >= 1)


def fetch_and_cache_symbol(symbol: str) -> None:
	# Fetch up to 10 years by default to cover most portfolios
	end = date.today()
	start = end - timedelta(days=365 * 10)
	vprint(f"prefetch: download {symbol} {start}..{end}")
	df = yf.download(symbol, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), progress=False, auto_adjust=True)
	if isinstance(df, pd.DataFrame) and _is_valid_prices_cache(df):
		_save_dataframe_csv(df, os.path.join(cache_dir(), f"{symbol}_prices.csv"))
	# Dividends
	ticker = yf.Ticker(symbol)
	div = ticker.dividends
	if div is not None and not div.empty:
		_save_series_csv(div, os.path.join(cache_dir(), f"{symbol}_dividends.csv"))


def prefetch_all_symbols() -> None:
	symbols = collect_all_symbols()
	for sym in sorted(symbols):
		try:
			fetch_and_cache_symbol(sym)
		except Exception as exc:  # noqa: BLE001
			# Best-effort prefetch; do not crash app
			print(f"Prefetch failed for {sym}: {exc}")
